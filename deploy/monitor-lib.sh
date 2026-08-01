#!/usr/bin/env bash
# ============================================================================
# monitor-lib.sh — 감시 공통 루틴 (알림 채널 · 상태 저장 · 비밀 세탁)
#
# monitor.sh 와 job-run.sh 가 함께 쓴다. 단독 실행용이 아니다.
#
# 설계 원칙 (이 파일이 지키는 것)
#  1) 알림 본문에 민감정보를 넣지 않는다. 넣을 수 있는 경로가 하나라도 있으면
#     결국 새기 때문에, 나가는 문자열은 전부 scrub() 를 통과한다.
#  2) 토큰을 명령줄 인자에 두지 않는다 (`ps` 로 보인다). curl -K 로 넣는다.
#  3) 알림 전송 실패는 조용히 넘기지 않는다 — 상태에 남기고, 다음 실행에서
#     다시 시도한다(성공할 때까지 `.sent` 를 찍지 않는다).
#  4) 자격증명을 복사하지 않는다. 동거 서비스(pjt12-adsense)가 이미 쓰는
#     텔레그램 봇을 **읽기만** 해서 재사용한다 — 복사하면 로테이션 때 우리만
#     조용히 죽는다. 대신 `source` 하지 않고 필요한 두 값만 뽑는다
#     (`source` 는 남의 파일을 실행하는 것이다).
#  5) **못 본 것을 "이상 없음"으로 말하지 않는다.** 검사 대상이 0개인 상태와
#     정상 상태는 다른 것이다(CR40-2). 판단은 monitor.sh 쪽 blind_add() 참조.
# ============================================================================

STATE_DIR="${RE_MON_STATE:-/var/lib/realestate-monitor}"
KV="$STATE_DIR/kv"
ALERTS="$STATE_DIR/alerts"
JOBS="$STATE_DIR/jobs"
MON_LOG="${RE_MON_LOG:-/var/log/realestate-monitor.log}"
MON_LOG_MAX_BYTES="${RE_MON_LOG_MAX_BYTES:-1048576}"   # 1MiB 넘으면 자체 절단(디스크 92%)
DRY_RUN="${RE_MON_DRY_RUN:-0}"

# 알림 자격증명을 찾을 순서. 앞이 우선.
#  · /etc/realestate-monitor.env  — 우리 전용 봇을 나중에 만들면 여기에 둔다
#  · /root/pjt12-adsense/.env     — 지금 실제로 쓰이는 채널(읽기만 한다)
RE_MON_CRED_FILES="${RE_MON_CRED_FILES:-/etc/realestate-monitor.env /root/pjt12-adsense/.env}"

mkdir -p "$KV" "$ALERTS" "$JOBS" 2>/dev/null
chmod 700 "$STATE_DIR" 2>/dev/null
chmod 700 "$KV" "$ALERTS" "$JOBS" 2>/dev/null
# 감시 로그도 0640 으로 만든다 — 0644 로 남았던 사고를 우리가 되풀이하지 않는다
[ -e "$MON_LOG" ] || : >"$MON_LOG" 2>/dev/null
chmod 640 "$MON_LOG" 2>/dev/null

# --- 로그 ------------------------------------------------------------------
# ⛔ **15번째 자리 — 이번에 스스로 찾았다. 세탁이 '나가는 길'에만 걸려 있었다.**
#    이 파일 머리말의 원칙 1은 *"나가는 문자열은 전부 scrub() 를 통과한다"* 인데
#    그 "나가는" 이 **텔레그램만** 뜻하고 있었다. `raise_alert`/`clear_alert` 는
#      log "ALERT $key :: $msg"      ← **원문**
#      send_telegram "... $msg"      ← scrub 통과
#    순서로 도는데, `$msg` 에 **남의 출력**이 들어오는 경로가 실재한다:
#    `job-run.sh` 의 `사유:`/`경고:` 줄은 **배치가 찍은 아무 문자열**이다.
#    실측(격리 재현): 배치가 `실패: ... postgresql+psycopg://re:<pw>@...` 를 찍게 하면
#      · 텔레그램(DRY-RUN) → `re:<redacted>@`  ✅
#      · **감시 로그 → 비밀번호 평문**       ⛔
#    감시 로그는 0640 root:root 라 오늘 당장 새지는 않는다. 그러나 이 저장소가
#    실제로 유출을 낸 곳이 **바로 로그 파일**이었고(SR32-1 · 0644), `check_logperm`
#    이 이 파일을 감시 대상으로 가지고 있는 이유가 그것이다. 그리고 SR39-4 가
#    적은 방아쇠가 지금 당겨진다 — NEIS·Anthropic 키를 쓰는 배치가 `job-run` 에
#    감싸이면, 그 배치의 트레이스백 한 줄로 키가 로그에 눍는다.
#    → **로그도 나가는 길이다.** 여기서 한 번 세탁한다.
#    ⚠️ 비용: `log()` 호출당 sed 1회. 한 실행에 1~4줄이라 무시할 수 있다.
#    ⚠️ 멱등: scrub 의 결과(`<num>`·`<redacted>`·`<token>`)는 어느 규칙에도 다시
#       안 걸린다 → `send_telegram` 이 이미 세탁한 문자열을 다시 넣어도 그대로다.
log() {
  printf '%s %s\n' "$(date '+%F %T')" "$(printf '%s' "$*" | scrub)" >>"$MON_LOG" 2>/dev/null
}

log_trim() {
  local sz
  sz=$(stat -c %s "$MON_LOG" 2>/dev/null) || return 0
  [ "${sz:-0}" -gt "$MON_LOG_MAX_BYTES" ] || return 0
  # 임시본도 처음부터 0640 으로 만든다 — umask 022 로 잠깐 0644 가 되면
  # 그 순간 check_logperm 이 자기 임시파일을 보고 운다(자기가 만든 오탐).
  : >"$MON_LOG.tmp" 2>/dev/null
  chmod 640 "$MON_LOG.tmp" 2>/dev/null
  tail -n 3000 "$MON_LOG" >"$MON_LOG.tmp" 2>/dev/null &&
    mv "$MON_LOG.tmp" "$MON_LOG" &&
    chmod 640 "$MON_LOG" 2>/dev/null
  log "감시 로그를 3000줄로 절단했다 (이전 ${sz}바이트)"
}

# --- 상태 (key=파일 하나. 파싱이 없으니 깨질 데가 없다) ----------------------
# ⚠️ 상위 디렉터리가 0700 root 라 실질 노출은 없지만, 파일 자체가 umask 022 로
#    0644 가 되는 것은 이 파일이 정한 원칙(0640/0600)과 어긋난다(CR41-8).
#    umask 를 통째로 바꾸지 않는 이유: job-run.sh 가 **남의 배치**를 실행하므로
#    그쪽이 만드는 파일까지 조용히 바뀐다. 우리가 만드는 파일만 우리가 맞춘다.
kv_get() { cat "$KV/$1" 2>/dev/null; }
kv_set() { printf '%s' "${2:-}" >"$KV/$1" 2>/dev/null; chmod 600 "$KV/$1" 2>/dev/null; }

# --- 비밀 세탁 -------------------------------------------------------------
# 알림·로그로 나가는 모든 문자열이 통과한다. 실제로 새어 본 것들을 막는다:
#  · DSN 의 비밀번호 (psycopg 트레이스백이 DATABASE_URL 을 그대로 뱉는다)
#  · 텔레그램 봇 토큰 (형태가 `숫자:영문` 이라 눈에 안 띈다)
#  · Bearer 토큰 / JWT
#  · KEY=/TOKEN=/SECRET=/PASSWORD= 꼴 (구분자 뒤 공백까지 — `KEY: value` 도 지운다)
#  · 금액으로 보이는 수 (자산 파생값 유출 재발 방지 — 감시는 금액을 다룰 일이 없다)
#
# ⚠️ 금액 규칙이 **셋**인 이유, 그리고 **어디까지만 막는지** (CR41-4)
#    문서 §2 와 이 주석과 selftest T7 은 셋 다 같은 말이어야 한다.
#   ① 구분자 없는 숫자는 **9자리 이상**만 지운다.
#   ② 쉼표로 3자리씩 묶인 수는 **2묶음 이상**(=1,000,000 이상)이면 지운다.
#   ③ **금액 토큰이 붙은 수**는 자릿수와 무관하게 지운다 —
#      뒤에 `원`/`만원`/`억`/`억원` 이 붙거나, 앞에 `cash`/`price`/`budget`/
#      `amount`/`krw`/`salary` 계열 키가 `=`·`:` 로 붙은 수.
#
#   ⛔ 왜 ①의 선을 9자리에서 더 못 내리는가 — **근거를 사실대로 적는다.**
#      옛 주석은 *"금액은 항상 백만 이상이라 이 선이 성립한다"* 고 적었는데
#      **그 문장은 성립하지 않는다**: 백만은 7자리라 ①(9자리)에 애초에 안 걸린다.
#      선을 8자리로 내리면 우리가 실제로 찍는 운영 수치가 죽는다 —
#      `auth.log` 크기 44,049,707(8자리)·오프셋·바이트 수가 통째로 `<num>` 이 되어
#      "얼마나 줄었는지"를 사람이 못 읽는다. 그래서 **자릿수를 내리는 대신
#      ③(금액 토큰 인접)을 추가**했다. 그러면 `1048576`·`288` 은 살고
#      `50000000원`·`3,500,000원`·`102,656만원`·`4.2억`·`{"cash_krw": 50000000}`·
#      `X-Cash: 50000000` 은 전부 지워진다.
#   ⛔ 남는 구멍(알고 남긴다): **토큰도 구분자도 없는 8자리 이하 순수 숫자**
#      (`95000000`)와 지수 표기(`1.02656e+09`)는 못 지운다. 바이트 수·행수와
#      구별할 방법이 없기 때문이다. 오늘 그 형태가 알림에 닿는 경로는 없다
#      (알림 문자열은 monitor.sh 가 만든 것과 job-run.sh 의 `실패:`/`경고:` 두 줄뿐이다).
#      배치가 늘어나 금액을 찍기 시작하면 그날 이 줄을 다시 본다.
#   ⛔ **그리고 SR38-4 가 지적한 것보다 넘어가는 것이 하나 더 있었다 — 내가 찾았다.**
#      리뷰는 따옴표 구멍을 **금액 규칙 ③** 에서만 봤는데, 똑같은 결함이
#      **비밀 규칙 ④** 에도 있었고 그쪽이 더 넓었다 — ④ 은 따옴표를
#      **아예 받지 않아서** JSON 큰따옴표 꼴조차 그대로 통과했다(실측):
#        `{"api_key": "..."}` · `{'TOKEN': '...'}` · `{'POSTGRES_PASSWORD': '...'}`
#      이쪽이 더 위험하다 — 파이썬 트레이스백과 dict 덤프가 정확히 그 모양이고,
#      금액과 달리 비밀은 한 번 나가면 되돌릴 수 없다. → ③④ 둘 다 넓혔다.
#   ⛔ SR38-4 — **그 서술이 실제보다 좁았다. 구멍이 하나 더 있었다.**
#      ③ 은 키 뒤 따옴표를 **큰따옴표 하나만** 받고 있었다(`"?`). 그런데 파이썬
#      `dict.__repr__` 은 **작은따옴표**를 쓴다 — 트레이스백에 실제로 나오는 꼴이
#      `{'cash_krw': 90000000}` 이고, 이건 **토큰도 구분자도 있는데 통과했다.**
#      위 문장("토큰도 구분자도 없는")이 사실과 달랐던 것이다 — 문서가 방어를
#      과장하던 것과 같은 종류의 잘못이라 여기에 적어 둔다.
#      → 문자클래스를 **작은따옴표·역따옴표까지** 받도록 넓혔다(세 글자).
# ⚠️ `LC_ALL=C` 를 **명령 단위**로 붙인다. 세탁은 보안 통제라 환경에 따라
#    달라지면 안 된다. 정확히 말하면(CR41-5): 줄이 정상 UTF-8 이면 UTF-8
#    로케일에서도 규칙은 그대로 동작한다. 무너지는 것은 **유효하지 않은 바이트가
#    섞인 줄**이다 — 그런 줄에서 UTF-8 로케일의 정규식은 조용히 매치를 놓친다
#    (실측: `LC_ALL=C` 1건 / `C.UTF-8`·`en_US.UTF-8`·`ko_KR.UTF-8` 0건).
#    nginx 로그에는 스캐너가 보낸 그런 바이트가 실제로 섞인다.
#    export 하지 않는 이유는 job-run.sh 가 돌리는 **배치(파이썬)의 출력 인코딩까지
#    바꾸면 안 되기** 때문이다.
#   ⛔ SR39-4 — **이름이 인접하지 않은 비밀은 규칙 ④가 못 본다.** 규칙 ④는
#      `이름=값` 꼴만 보는데, 실제 트레이스백·에러메시지는 값만 던진다:
#        `invalid x-api-key sk-ant-api03-...` · `KakaoAK 0123...` · `Authorization: Basic ...`
#        · 맨 JWT(`eyJ...`) · `credential=` · `pwd=`
#      오늘 그 형태가 알림에 닿는 경로는 없다. 그러나 **방아쇠가 지금 당겨진다** —
#      NEIS·Anthropic 키가 들어오면 그 키를 쓰는 배치가 `job-run` 에 감싸이고,
#      그 값이 `실패:` 줄에 실릴 수 있다. 접두 한 줄이 그날 가장 싼 보험이다.
#      ⚠️ 순서가 중요하다 — 숫자 규칙(`<num>`)보다 **앞**에 두어야 한다.
#      뒤에 두면 `KakaoAK 0123...` 의 숫자만 먼저 지워져 영문 절반이 남는다(실측).
scrub() {
  LC_ALL=C sed -E \
    -e 's#([a-zA-Z0-9+.-]+://[^:/@[:space:]]+):[^@[:space:]]*@#\1:<redacted>@#g' \
    -e 's#sk-ant-[A-Za-z0-9_-]{8,}#<redacted>#g' \
    -e 's#(KakaoAK[[:space:]]+)[A-Za-z0-9]{16,}#\1<redacted>#g' \
    -e 's#([Bb]asic[[:space:]]+)[A-Za-z0-9+/=]{16,}#\1<redacted>#g' \
    -e 's#eyJ[A-Za-z0-9_=-]{8,}\.[A-Za-z0-9_=-]{8,}\.[A-Za-z0-9_=+/-]{8,}#<redacted>#g' \
    -e 's#[0-9]{6,}:[A-Za-z0-9_-]{20,}#<token>#g' \
    -e 's#([Bb]earer[[:space:]]+)[A-Za-z0-9._~+/=-]{16,}#\1<redacted>#g' \
    -e 's#((PASSWORD|PASSWD|PWD|SECRET|TOKEN|APIKEY|API_KEY|SERVICE_KEY|CREDENTIAL|KEY)[A-Za-z_]*['"'"'"`]?[[:space:]]*[=:][[:space:]]*)[^[:space:]]+#\1<redacted>#gI' \
    -e 's#((CASH|PRICE|BUDGET|AMOUNT|KRW|SALARY)[A-Za-z_]*['"'"'"`]?[[:space:]]*[=:][[:space:]]*)[0-9][0-9,.]*#\1<num>#gI' \
    -e 's#[0-9][0-9,.]*(만원|억원|원|억)#<num>\1#g' \
    -e 's#[0-9]{1,3}(,[0-9]{3}){2,}#<num>#g' \
    -e 's#[0-9]{9,}#<num>#g'
}

# --- 시장지수 기대 기준월 ---------------------------------------------------
# 배치는 **매월 1일 04:10 에만** 돈다(monitoring.md §1). 그러므로 "지금 DB 에 있어야
# 할 기준월"은 **오늘 날짜가 아니라 마지막 배치 시점**으로 재야 한다.
#
#   옛 공식(`date -d '-30 days'` 를 오늘 기준으로)은 달 중간에 기대값만 앞서 나갔다.
#   배치는 정상인데 감시가 "월배치가 안 돌았다"고 울었고 — **2026-07-31 09:05 에
#   실제로 한 통 갔다**(DB 2026-05 vs 기대 2026-06 · 서버 감시로그로 확인).
#   그대로 두면 연 35일, 2027-03 은 3/3~3/31 **29일 연속**이다(CR40-1).
#   배치 미실행을 잡는 경보가 이것 하나뿐이라, 헛울면 진짜 실패가 묻힌다.
#
# 완결 규칙은 market-index.sh 머리말과 같다 — 신고 지연 30일(timeadjust.REPORT_LAG_DAYS):
#   기대 기준월 = (마지막 배치일 − 30일)이 속한 달의 **직전 달**
#
# 인자로 기준 시각(epoch)을 받는다. 날짜를 바꿔 가며 검증하기 위해서다
# (`deploy/monitor-selftest.sh` 가 이 함수로 365일을 돌려 오탐 0 을 확인한다).
#
# ⚠️ market-index.sh 에 **같은 함수가 복사돼 있다**(그쪽은 이 파일을 source 하지
#    않는다 — `set -e` 아래에서 남의 파일의 mkdir/chmod 가 실패하면 배치가
#    통째로 죽기 때문이다). 두 사본이 갈라지지 않는지는 selftest 가 대조한다.
MARKET_BATCH_READY="${RE_MON_MARKET_BATCH_READY:-06:00}"   # 배치 04:10 + 유예(배치 소요 ~51초)
market_expected_ym() {
  local now base
  now="${1:-$(date +%s)}"
  base=$(date -d "@$now" +%Y-%m-01 2>/dev/null) || return 1
  # 이번 달 배치 시각이 아직 안 왔으면(=매월 1일 새벽) 마지막 배치는 지난달 1일이다
  if [ "$now" -lt "$(date -d "$base $MARKET_BATCH_READY" +%s 2>/dev/null || printf 0)" ]; then
    base=$(date -d "$base -1 month" +%Y-%m-01 2>/dev/null) || return 1
  fi
  date -d "$(date -d "$base -30 days" +%Y-%m-01 2>/dev/null) -1 month" +%Y-%m 2>/dev/null
}

# --- 텔레그램 --------------------------------------------------------------
_getvar() {
  # _getvar KEY FILE — 남의 .env 를 실행하지 않고 값 하나만 뽑는다
  sed -n "s/^[[:space:]]*\(export[[:space:]]\+\)\?$1=//p" "$2" 2>/dev/null |
    tail -1 |
    sed -e 's/^["'"'"']//' -e 's/["'"'"']$//' -e 's/[[:space:]]*$//'
}

TG_TOKEN=""; TG_CHAT=""; CRED_SRC=""
alert_creds() {
  TG_TOKEN=""; TG_CHAT=""; CRED_SRC=""
  local f
  for f in $RE_MON_CRED_FILES; do
    [ -r "$f" ] || continue
    TG_TOKEN=$(_getvar TELEGRAM_BOT_TOKEN "$f")
    TG_CHAT=$(_getvar TELEGRAM_CHAT_ID "$f")
    if [ -n "$TG_TOKEN" ] && [ -n "$TG_CHAT" ]; then CRED_SRC="$f"; return 0; fi
  done
  return 1
}

send_telegram() {
  local text code i
  text=$(printf '%s' "$1" | scrub)

  if [ "$DRY_RUN" = "1" ]; then
    printf '[DRY-RUN 전송하지 않음]\n%s\n' "$text"
    log "DRY-RUN :: $(printf '%s' "$text" | tr '\n' '|')"
    return 0
  fi

  if ! alert_creds; then
    # 여기가 최악의 경우다 — 알릴 수단이 없다. 로그와 상태에 남기는 것이
    # 우리가 할 수 있는 전부이고, 매일 오는 요약이 안 오는 것으로 사람이 안다.
    kv_set alert_channel_ok 0
    log "ALERT-CHANNEL-MISSING 자격증명 없음 — 보낼 수 없다 :: $(printf '%s' "$text" | tr '\n' '|')"
    return 1
  fi

  for i in 1 2 3; do
    code=$(printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$TG_TOKEN" |
      curl -s -K - --max-time 20 -o /dev/null -w '%{http_code}' \
        --data-urlencode "chat_id=${TG_CHAT}" \
        --data-urlencode "text=${text}" \
        --data-urlencode "disable_web_page_preview=true" 2>/dev/null)
    if [ "$code" = "200" ]; then
      kv_set alert_channel_ok 1
      kv_set alert_last_sent "$(date +%s)"
      log "ALERT-SENT http=200 src=$CRED_SRC"
      return 0
    fi
    [ "$i" -lt 3 ] && sleep 5
  done
  kv_set alert_channel_ok 0
  log "ALERT-SEND-FAIL http=${code:-none} src=$CRED_SRC"
  return 1
}

# --- 경보 (쿨다운 · 해소 통보) ----------------------------------------------
# raise_alert KEY COOLDOWN_SEC MESSAGE
#   COOLDOWN_SEC=0 → 매번 보낸다 (델타형 신호: 새 사건 = 새 정보)
#   COOLDOWN_SEC>0 → 상태형 신호. 같은 문제로 5분마다 울면 아무도 안 본다.
raise_alert() {
  local key="$1" cooldown="$2" msg="$3"
  local af="$ALERTS/$key.active" sf="$ALERTS/$key.sent" now last
  now=$(date +%s)
  [ -f "$af" ] || { printf '%s' "$now" >"$af"; chmod 600 "$af" 2>/dev/null; }

  if [ "$cooldown" -gt 0 ] && [ -f "$sf" ]; then
    last=$(cat "$sf" 2>/dev/null); last=${last:-0}
    if [ $((now - last)) -lt "$cooldown" ]; then
      log "ALERT-SUPPRESSED $key ($(((cooldown - (now - last)) / 60))분 남음) :: $msg"
      return 0
    fi
  fi
  log "ALERT $key :: $msg"
  if send_telegram "[realestate] 경보: $msg"; then printf '%s' "$now" >"$sf"; chmod 600 "$sf" 2>/dev/null; fi
}

# clear_alert KEY MESSAGE — 켜져 있던 경보가 풀렸을 때만 한 번 알린다
#   ⚠️ 부르는 쪽 규칙: **검사를 실제로 수행했을 때만** 부른다.
#      대상이 0개라 아무것도 못 본 상태에서 부르면 "해소됐다"는 거짓 통보가 된다(CR40-2).
clear_alert() {
  local key="$1" msg="$2"
  local af="$ALERTS/$key.active" sf="$ALERTS/$key.sent"
  [ -f "$af" ] || return 0
  log "ALERT-CLEARED $key :: $msg"
  if [ -f "$sf" ]; then send_telegram "[realestate] 해소: $msg"; fi
  rm -f "$af" "$sf"
}

active_alerts() {
  local f n=0 out=""
  for f in "$ALERTS"/*.active; do
    [ -e "$f" ] || continue
    n=$((n + 1))
    out="$out $(basename "$f" .active)"
  done
  printf '%s|%s' "$n" "${out# }"
}
