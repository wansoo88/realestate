#!/usr/bin/env bash
# ============================================================================
# monitor.sh — pjt13-realestate 운영 감시
#
# 배치 경로 : /opt/realestate/scripts/monitor.sh   (monitor-lib.sh 와 같은 디렉터리)
# 크론      : */5 * * * *  /opt/realestate/scripts/monitor.sh --fast  >>/dev/null 2>&1
#             5 9 * * *    /opt/realestate/scripts/monitor.sh --daily >>/dev/null 2>&1
#
# ---------------------------------------------------------------------------
# 왜 이것들만 보는가 (근거는 docs/05-monitoring/monitoring.md 에 자세히)
#   실제로 사고가 났고 사람이 우연히 발견한 것 + 조용히 나빠지는 것만 넣었다.
#   오탐이 결함이라는 원칙 때문에 "정상인데 우는" 항목은 일부러 뺐다:
#     · pg_postmaster_start_time  — 크래시 복구 때 **변하지 않는다**(실측 확인).
#       실제 사고 3건을 전부 놓쳤을 검사다. cgroup oom_kill 카운터로 대체.
#     · docker stats 의 MEM USAGE / MEM %  — page cache 라 정상적으로 한계에 닿는다.
#       memory.stat 의 anon 으로 대체.
#     · memory.events 의 max 카운터 — 오늘 이미 152,189 이다. 매번 운다.
#     · 호스트 free 메모리 / load / 응답시간 — 사고 이력이 없고 정상 기준선이 없다.
#
#   그리고 같은 원칙의 **반대쪽**도 지킨다(CR40-2):
#     · 검사 대상이 0개인 상태를 "이상 없음"으로 말하지 않는다. 못 본 것은 못 본 것이다.
#     · 못 봤을 때는 clear_alert 를 부르지 않는다 — 거짓 해소 통보가 더 나쁘다.
# ---------------------------------------------------------------------------
set -uo pipefail
# ⚠️ `set -e` 를 일부러 쓰지 않는다. 감시 스크립트가 중간에 죽으면 그게 조용한
#    실패다. 대신 모든 검사가 끝난 뒤에만 heartbeat 를 찍고, 그 heartbeat 가
#    낡으면 --daily 가 알린다(상호 감시).

# ⚠️ 로케일을 고정한다 — 취향이 아니라 **검사가 환경에 따라 다른 결과를 내는** 문제다.
#    ⛔ 근거를 사실대로 적는다(CR41-5 — 옛 주석은 원인을 잘못 짚고 있었다).
#      줄이 **정상 UTF-8** 이면 `grep 'A.*B'` 는 사이에 한글이 있어도 `C.UTF-8`·
#      `en_US.UTF-8`·`ko_KR.UTF-8` 에서 **매치한다**. 로케일 때문에 매치가 깨지는 것은
#      **유효하지 않은 바이트가 섞인 줄**뿐이다 — 실측: 그런 줄에서
#      `LC_ALL=C` 는 1건, `C.UTF-8`/`en_US.UTF-8`/`ko_KR.UTF-8` 는 **0건**이다.
#    그런데 그게 남 얘기가 아니다: nginx access/error 로그에는 스캐너가 보낸
#    유효하지 않은 바이트가 실제로 섞이고, 우리는 그 로그를 grep 해서 **유출을 판정**한다.
#    로케일이 정해져 있지 않으면 크론(로케일 비어 있음=POSIX)과 손 실행(UTF-8)이
#    **같은 파일에서 다른 답**을 낸다 — 보안 판정이 환경에 따라 달라지는 것이다.
#    그래서 바이트 단위로 고정한다.
#    (겹으로: `date -d "Aug 30 12:00:00 2026 GMT"` — 인증서 만료일 파싱도 안전해진다)
export LC_ALL=C

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)
# shellcheck source=./monitor-lib.sh
. "$HERE/monitor-lib.sh" || { echo "monitor-lib.sh 를 못 읽음 ($HERE)" >&2; exit 3; }

MODE=fast
case "${1:---fast}" in
  --fast)  MODE=fast ;;
  --daily) MODE=daily ;;
  --test-alert) MODE=test ;;
  -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
  *) echo "사용법: $0 [--fast|--daily|--test-alert]" >&2; exit 2 ;;
esac

# --- 임계값 (전부 환경변수로 덮어쓸 수 있다 — 실패 주입 시험에 쓴다) ---------
URL_MAIN="${RE_MON_URL_MAIN:-https://realestate.utilverse.info/}"
URL_HEALTH="${RE_MON_URL_HEALTH:-https://realestate.utilverse.info/api/v1/health}"
URL_MAP="${RE_MON_URL_MAP:-https://realestate.utilverse.info/api/v1/map/complexes?sw_lat=37.50&sw_lng=127.02&ne_lat=37.52&ne_lng=127.05}"
# ⚠️ 로컬은 8013 이다. **8000 은 itsmine-engine** 이다 — 거기를 찌르면 남의
#    서비스를 감시하면서 우리가 살아 있다고 착각한다(실측 확인).
URL_LOCAL="${RE_MON_URL_LOCAL:-http://127.0.0.1:8013/api/v1/health}"

WEB_STREAK="${RE_MON_WEB_STREAK:-2}"          # 5분×2 = 10분 연속 실패해야 알린다
DISK_MIN_KB="${RE_MON_DISK_MIN_KB:-1258291}"  # 1.2GiB. 오늘 2.0GiB → 안 운다
DISK_MAX_PCT="${RE_MON_DISK_MAX_PCT:-95}"     # 오늘 92% → 안 운다
ANON_MAX_MB="${RE_MON_ANON_MAX_MB:-130}"      # 한계 192MiB 의 68%. 오늘 db anon ≈ 1MiB
CERT_MIN_DAYS="${RE_MON_CERT_MIN_DAYS:-21}"   # certbot 은 30일에 갱신 → 21일이면 여러 번 실패한 것
JSONLOG_MAX_MB="${RE_MON_JSONLOG_MAX_MB:-300}"
API5XX_MIN="${RE_MON_API5XX_MIN:-1}"          # 트래픽이 거의 없다 → 1건도 사건이다
HEARTBEAT_MAX_MIN="${RE_MON_HEARTBEAT_MAX_MIN:-20}"
DAILY_MAX_HOURS="${RE_MON_DAILY_MAX_HOURS:-30}"
MARKET_INDEX_LOG="${RE_MON_MARKET_INDEX_LOG:-/var/log/realestate_market_index.log}"
# access 로그 mtime 신선도. 사람 트래픽이 아니라 **우리 감시 자체**가 5분마다
# https 로 4번 찌르므로 정상이면 하루 1,000줄 이상 쌓인다(실측: 하루치 회전본 195KB).
# 그래서 이 값은 "사용자가 안 들어와서 조용한 것"과 무관하다. 넉넉히 24시간.
ACCESS_FRESH_MAX_HOURS="${RE_MON_ACCESS_FRESH_MAX_HOURS:-24}"
# auth.log 신선도(SR38-3). **로그가 얼어붙은 것과 침입이 없는 것은 다르다.**
#   서버는 `Failed password` 가 88,316건 쌓여 있어 auth.log 가 상시 갱신된다 —
#   6시간이면 오탐이 사실상 0이고, rsyslog 정지/파이프 파손은 확실히 잡힌다.
AUTH_FRESH_MAX_HOURS="${RE_MON_AUTH_FRESH_MAX_HOURS:-6}"
# 시장지수 배치의 job 이름 — 감시가 '이번 달에 배치가 돌았는가'를 여기서 읽는다(CR42-1).
MARKET_JOB_NAME="${RE_MON_MARKET_JOB:-market-index}"

ACCESS_LOG="${RE_MON_ACCESS_LOG:-/var/log/nginx/realestate.access.log}"
ERROR_LOG="${RE_MON_ERROR_LOG:-/var/log/nginx/realestate.error.log}"
LOG_GLOB_DIR="${RE_MON_LOG_DIR:-/var/log/nginx}"
# 우리가 만든 로그도 본다 — 감시가 자기 산출물을 안 보던 사각지대였다(SR36-2 ③).
# `/var/log/realestate_market_index.log` 가 실제로 0644 로 남아 있었고,
# 이 프로젝트는 0644 로그에서 진짜 유출을 낸 적이 있다(SR32-1).
APP_LOG_GLOB="${RE_MON_APP_LOG_GLOB:-/var/log/realestate*.log*}"
AUTH_LOG="${RE_MON_AUTH_LOG:-/var/log/auth.log}"
LE_DIR="${RE_MON_LE_DIR:-/etc/letsencrypt/live}"
CONTAINERS="${RE_MON_CONTAINERS:-realestate-db realestate-api}"
PG_CONTAINER="${RE_MON_PG_CONTAINER:-realestate-db}"
PG_USER="${RE_MON_PG_USER:-}"
PG_DB="${RE_MON_PG_DB:-}"
APP_ENV="${RE_MON_APP_ENV:-/opt/realestate/.env}"

DIGEST=""
add() { DIGEST="${DIGEST}$1"$'\n'; }

# --- "검사 못 함" 을 모으는 자리 ---------------------------------------------
# ⛔ 이 저장소가 세 번 적발한 형태(빈 집합이 통과한다)를 여기서 막는다.
#    검사 대상 파일이 0개이거나 못 읽으면 그건 "이상 없음"이 아니라 **감시 불능**이다.
#    각 검사는 ① blind_add 로 사유를 남기고 ② clear_alert 를 부르지 않고 ③ 돌아간다.
#    마지막에 check_logblind 가 사유를 모아 **한 통**으로 경보한다(3통이 아니라).
BLIND=""
BLIND_DAILY=""
blind_add() { BLIND="$BLIND $1;"; }
# ⛔ CR43-1 — **사유에도 모드가 있다.** `check_cert`·`check_db_structure` 는 `--daily`
#    에만 도는데, 그 사유가 사람에게 닿는 길은 `logblind` **하나뿐**이다(둘 다
#    `raise_alert` 를 안 하고 `blind_add` 만 하도록 설계됐다). 그런데 5분 뒤 `--fast`
#    가 자기 `BLIND` 가 비었다는 이유로 그 경보를 **지웠다** — 인증서를 본 적도 없이
#    "해소: 로그 감시 대상 정상 (권한·유출·5xx·SSH 검사 전부 수행)" 을 보내면서.
#    재현: daily(대상 0개) → `.active` 생성 → fast → clear + 해소 1통 → 다음 daily 재발생.
#    쿨다운 21600 도 함께 무력화된다(`.sent` 가 지워지므로).
#    → daily 전용 사유는 **따로 모아 kv 에 남기고**, fast 는 그 키가 살아 있으면
#      **이번 실행이 재평가하지 못한 사유**로 보고 clear 하지 않는다.
blind_add_daily() { blind_add "$1"; BLIND_DAILY="$BLIND_DAILY $1;"; }
readable() { [ -f "$1" ] && [ -r "$1" ]; }

# --- 겹쳐 돌지 않게 (5분 크론이 8초짜리 curl 을 기다리다 쌓이면 안 된다) -----
LOCKF="$STATE_DIR/monitor.$MODE.lock"
exec 9>"$LOCKF" 2>/dev/null
# 잠금파일도 0600 (SR38-5). 상위가 0700 root 라 실질 노출은 없지만, kv_set·
# raise_alert 가 세운 원칙과 어긋난 채 두면 그 원칙이 “가끔” 이 된다.
chmod 600 "$LOCKF" 2>/dev/null
if command -v flock >/dev/null 2>&1; then
  flock -n 9 || { log "$MODE 이미 실행 중 — 건너뜀"; exit 0; }
fi

http_code() {
  local c
  c=$(curl -s -o /dev/null --max-time 8 -w '%{http_code}' "$1" 2>/dev/null)
  [ -n "$c" ] && printf '%s' "$c" || printf '000'
}

# ============================================================================
# 1) 사이트가 살아 있는가  ← nginx 설정 오류로 메인 404 사고
# ============================================================================
check_web() {
  local m h l mp fails=0 detail="" streak where
  m=$(http_code "$URL_MAIN")
  h=$(http_code "$URL_HEALTH")
  l=$(http_code "$URL_LOCAL")
  mp=$(http_code "$URL_MAP")

  [ "$m" = 200 ] || { fails=$((fails + 1)); detail="$detail 메인=$m"; }
  [ "$h" = 200 ] || { fails=$((fails + 1)); detail="$detail health=$h"; }
  # 지도는 인증이 필요하다 → 정상값은 401. 5xx 면 앱이 깨진 것이다.
  # ⚠️ 401 은 "앱이 응답한다"는 뜻일 뿐 **SQL 이 돈다는 증거가 아니다**.
  #    016 류(컬럼 누락)는 인증 검사가 먼저라 401 로 가려진다 → 구조 검사(--daily)와
  #    실사용 5xx 집계가 그 자리를 메운다.
  case "$mp" in
    401|403) ;;
    *) fails=$((fails + 1)); detail="$detail 지도=$mp" ;;
  esac

  add "웹      : 메인=$m health=$h 지도(무인증,기대401)=$mp 로컬8013=$l"

  streak=$(kv_get web_fail_streak); streak=${streak:-0}
  if [ "$fails" -gt 0 ]; then
    streak=$((streak + 1)); kv_set web_fail_streak "$streak"
    if [ "$streak" -ge "$WEB_STREAK" ]; then
      if [ "$l" = 200 ]; then where="앱(8013)은 200 → nginx/TLS/DNS 쪽을 먼저 본다"
      else where="앱(8013)도 비정상($l) → 컨테이너/DB 쪽을 먼저 본다"; fi
      raise_alert web 21600 "사이트 응답 이상 ${streak}회 연속:$detail · $where"
    else
      log "web 실패 1회 — 연속 $streak/$WEB_STREAK, 아직 알리지 않는다:$detail"
    fi
  else
    kv_set web_fail_streak 0
    clear_alert web "사이트 응답 정상 회복 (메인=200 health=200 지도=$mp)"
  fi
}

# ============================================================================
# 1b) 화면이 실제로 뜨는가 — index.html 이 참조하는 번들이 정말 있는가
#
#    메인이 200 이어도 화면은 빌 수 있다. 실제로 겪은 형태와 같은 계열이다:
#      · 배포 후 nginx root 가 옛 디렉터리를 본다 → index.html 은 옛것,
#        번들 파일명(해시)은 새것 → 브라우저가 404 를 받고 빈 화면이 된다
#      · index.html 만 올라가고 assets/ 가 안 올라갔다
#    ⚠️ 이 검사가 성립하는 근거: 이 사이트는 SPA 폴백이 있어서 **없는 경로도
#       200(index.html)** 이 된다(실측). 그래서 "없는 경로 404" 로는 아무것도
#       못 잡는다. 반면 `/assets/` 는 폴백에서 빠져 있어 없는 파일이 404 로
#       온다(실측) → 번들 검사만이 판별력을 가진다.
#    본문은 안 받는다(HEAD). 5분마다 297KB 를 받으면 감시가 대역폭을 먹는다.
# ============================================================================
check_frontend() {
  local body js code ct fails=0 detail="" streak
  body=$(curl -s --max-time 8 "$URL_MAIN" 2>/dev/null)
  js=$(printf '%s' "$body" | grep -oE '/assets/[A-Za-z0-9._-]+\.js' | head -1)
  if [ -z "$js" ]; then
    add "프론트  : index.html 에 /assets/*.js 참조가 없다"
    fails=1
    detail=" index.html 에 번들 참조가 없다 (기본 nginx 페이지이거나 빌드 결과가 아니다)"
  else
    read -r code ct <<<"$(curl -sI -o /dev/null --max-time 8 -w '%{http_code} %{content_type}' "${URL_MAIN%/}$js" 2>/dev/null)"
    add "프론트  : 번들 $js → ${code:-000} ${ct:-?}"
    if [ "${code:-000}" != 200 ]; then
      fails=1
      detail=" 번들 $js 가 ${code:-000} — nginx root 가 옛 배포를 보고 있을 수 있다"
    # ⛔ CR42-4 — 조건 자리에 파이프라인을 두지 않는다. 이 파일은 `set -o pipefail`
    #    아래에서 돌고, 파이프라인의 상태는 “안 맞았다” 말고도 (SIGPIPE·fork 실패로)
    #    0 이 아닐 수 있다. 하필 **부정형**이라 그때 피해가 나쁜 쪽이다.
    #    (오늘 안 터지는 것과 그런 형태를 남겨 두는 것은 다른 문제다 — CR41-6)
    elif ! case "$ct" in *[Jj][Aa][Vv][Aa][Ss][Cc][Rr][Ii][Pp][Tt]*) true ;; *) false ;; esac; then
      fails=1
      detail=" 번들 $js 의 Content-Type 이 $ct — SPA 폴백으로 index.html 이 돌아왔다"
    fi
  fi
  streak=$(kv_get fe_fail_streak); streak=${streak:-0}
  if [ "$fails" -gt 0 ]; then
    streak=$((streak + 1)); kv_set fe_fail_streak "$streak"
    if [ "$streak" -ge "$WEB_STREAK" ]; then
      raise_alert frontend 21600 "화면이 안 뜰 상태 ${streak}회 연속:$detail"
    else
      log "frontend 실패 1회 — 연속 $streak/$WEB_STREAK:$detail"
    fi
  else
    kv_set fe_fail_streak 0
    clear_alert frontend "프론트 번들 정상 (200 · javascript)"
  fi
}

# ============================================================================
# 2) DB/API 가 OOM 으로 죽었는가  ← 운영 DB OOM 재기동 사고
#
#    가장 확실한 신호는 cgroup v2 의 memory.events oom_kill 카운터다.
#    · 커널이 세는 값이라 오탐이 0 이다.
#    · docker ps 는 이걸 못 본다: postmaster(PID 1)는 살아 있고 백엔드만
#      죽어서 크래시 복구를 하므로 컨테이너는 계속 "Up ... (healthy)" 다.
#      실제로 RestartCount=0 인 채로 7/27·7/28 에 재초기화가 있었다.
#    · 컨테이너를 재생성하면 cgroup 이 새로 만들어져 카운터가 0 이 된다 →
#      기준값보다 작아지면 "감소"가 아니라 "재생성"으로 처리한다(오탐 방지).
# ============================================================================
cg_path() {
  local name="$1" id p
  id=$(kv_get "cid_$name")
  if [ -n "$id" ]; then
    for p in "/sys/fs/cgroup/system.slice/docker-$id.scope" "/sys/fs/cgroup/docker/$id"; do
      [ -d "$p" ] && { printf '%s' "$p"; return 0; }
    done
  fi
  command -v docker >/dev/null 2>&1 || return 1
  id=$(docker inspect -f '{{.Id}}' "$name" 2>/dev/null)
  [ -n "$id" ] || return 1
  kv_set "cid_$name" "$id"
  kv_set "oomkill_$name" ""      # 새 컨테이너 = 카운터 기준값 리셋
  for p in "/sys/fs/cgroup/system.slice/docker-$id.scope" "/sys/fs/cgroup/docker/$id"; do
    [ -d "$p" ] && { printf '%s' "$p"; return 0; }
  done
  return 1
}

check_oom() {
  local name p cur prev delta
  for name in $CONTAINERS; do
    p=$(cg_path "$name")
    if [ -z "$p" ]; then
      add "OOM     : $name cgroup 을 못 찾음 (컨테이너가 없는가?)"
      raise_alert "cgroup_$name" 21600 "$name 의 cgroup 을 못 찾는다 — 컨테이너가 내려갔거나 감시가 눈이 먼 상태다"
      continue
    fi
    clear_alert "cgroup_$name" "$name cgroup 다시 보인다"
    cur=$(awk '$1=="oom_kill"{print $2}' "$p/memory.events" 2>/dev/null)
    [ -n "$cur" ] || { add "OOM     : $name memory.events 를 못 읽음"; continue; }
    prev=$(kv_get "oomkill_$name")
    if [ -z "$prev" ]; then
      kv_set "oomkill_$name" "$cur"
      add "OOM     : $name 기준값 설정 (누적 oom_kill=$cur · 이 값 자체는 알리지 않는다)"
      log "oom 기준값 초기화 $name=$cur"
      continue
    fi
    if [ "$cur" -lt "$prev" ]; then
      kv_set "oomkill_$name" "$cur"
      add "OOM     : $name 카운터 리셋 (컨테이너 재생성) 누적=$cur"
      log "oom 카운터 리셋 감지 $name prev=$prev cur=$cur"
      continue
    fi
    delta=$((cur - prev))
    kv_set "oomkill_$name" "$cur"
    if [ "$delta" -gt 0 ]; then
      raise_alert "oom_$name" 0 "$name 에서 OOM kill ${delta}건 발생 (누적 $cur). 컨테이너는 재시작 안 됐을 수 있다 — docker ps 로는 안 보인다. mem_limit 192m · 확인: docker logs $name | grep -i 'terminated by signal'"
    fi
    add "OOM     : $name 누적 oom_kill=$cur (이번 구간 +$delta)"
  done
}

# ============================================================================
# 3) DB 메모리가 위험선에 접근했는가 (조용히 나빠지는 것)
#    anon = 백엔드가 실제로 붙잡은 익명 메모리. page cache(file) 는 제외한다.
#    ⚠️ 5분 표본이라 몇 초짜리 급등은 놓친다 — 이건 조기 경고이고,
#       사후 확실한 증거는 (2) 의 oom_kill 이다. 감시할 수 없는 걸 감시하는
#       척하지 않기 위해 이 한계를 여기 적어 둔다.
# ============================================================================
check_dbmem() {
  local name p anon_b anon_mb swap_mb lim_mb
  for name in $CONTAINERS; do
    p=$(cg_path "$name") || continue
    [ -n "$p" ] || continue
    anon_b=$(awk '$1=="anon"{print $2}' "$p/memory.stat" 2>/dev/null)
    [ -n "$anon_b" ] || continue
    anon_mb=$((anon_b / 1048576))
    swap_mb=$(( $(cat "$p/memory.swap.current" 2>/dev/null || echo 0) / 1048576 ))
    lim_mb=$(( $(cat "$p/memory.max" 2>/dev/null || echo 0) / 1048576 ))
    add "메모리  : $name anon=${anon_mb}MiB swap=${swap_mb}MiB / 한계 ${lim_mb}MiB"
    if [ "$anon_mb" -ge "$ANON_MAX_MB" ]; then
      raise_alert "anon_$name" 21600 "$name 의 anon 메모리 ${anon_mb}MiB (임계 ${ANON_MAX_MB}MiB / 한계 ${lim_mb}MiB) — OOM kill 직전 상태일 수 있다"
    else
      clear_alert "anon_$name" "$name anon 메모리 ${anon_mb}MiB 로 내려왔다"
    fi
  done
}

# ============================================================================
# 4) 디스크  ← 오늘 92%. 차면 우리만 죽는 게 아니라 동거 서비스도 같이 죽는다
# ============================================================================
check_disk() {
  local avail pct
  avail=$(df -Pk / 2>/dev/null | awk 'NR==2{print $4}')
  pct=$(df -Pk / 2>/dev/null | awk 'NR==2{gsub(/%/,"",$5); print $5}')
  [ -n "$avail" ] || { add "디스크  : df 실패"; return; }
  add "디스크  : / 사용 ${pct}% · 여유 $((avail / 1024))MiB"
  if [ "$avail" -lt "$DISK_MIN_KB" ] || [ "${pct:-0}" -ge "$DISK_MAX_PCT" ]; then
    raise_alert disk 21600 "루트 디스크 ${pct}% · 여유 $((avail / 1024))MiB (임계 ${DISK_MAX_PCT}% / $((DISK_MIN_KB / 1024))MiB). 차면 동거 서비스까지 멈춘다"
  else
    clear_alert disk "디스크 여유 회복 (${pct}% · $((avail / 1024))MiB)"
  fi
}

# ============================================================================
# 5) 로그 권한  ← 자산 파생값이 0644 회전본에 남아 있던 사고
#    logrotate 설정은 `create 0640 www-data adm` 이지만, 설정이 아니라
#    **실제 파일 모드**를 본다. 사고는 설정이 아니라 파일에서 났다.
#
#    대상은 두 묶음이고 **각각** 0개인지 본다:
#      ① nginx  /var/log/nginx/realestate.{access,error}.log*  (회전본 포함)
#      ② 우리 것 /var/log/realestate*.log*  (감시 로그 · 배치 로그 — SR36-2 ③)
#    한쪽이 0개면 그 묶음은 **검사 못 한 것**이다. 0개를 "이상 없음"으로 넘기면
#    경로가 바뀌거나 로테이션이 깨졌을 때 감시가 눈이 먼 채로 조용해진다(CR40-2).
# ============================================================================
_perm_check_one() {
  # 모드가 0640/0600 이 아니면 " 이름:모드" 를 찍는다 (아니면 아무것도 안 찍는다)
  local f="$1" mode
  mode=$(stat -c %a "$f" 2>/dev/null)
  case "$mode" in
    600|640) ;;
    "") printf ' %s:모드확인불가' "$(basename "$f")" ;;
    *)  printf ' %s:%s' "$(basename "$f")" "$mode" ;;
  esac
}

check_logperm() {
  local f n_nginx=0 n_app=0 bad=""
  for f in "$LOG_GLOB_DIR"/realestate.access.log* "$LOG_GLOB_DIR"/realestate.error.log*; do
    [ -e "$f" ] || continue
    n_nginx=$((n_nginx + 1))
    bad="$bad$(_perm_check_one "$f")"
  done
  # shellcheck disable=SC2086
  for f in $APP_LOG_GLOB; do          # 글롭이라 일부러 인용하지 않는다
    [ -e "$f" ] || continue
    case "$f" in *.tmp) continue ;; esac   # log_trim 이 잠깐 만드는 임시본은 뺀다
    n_app=$((n_app + 1))
    bad="$bad$(_perm_check_one "$f")"
  done

  # 문구부터 정직해야 한다 — 대상이 0개인데 "이상 없음"이라고 적으면
  # 사람이 요약을 읽고 "권한은 봤구나"라고 잘못 안다.
  local status
  if [ -n "$bad" ]; then status="이상:$bad"
  elif [ "$n_nginx" -eq 0 ] || [ "$n_app" -eq 0 ]; then status="검사 못 함 (대상 0개)"
  else status="이상 없음"; fi
  add "로그권한: nginx ${n_nginx}개 · 앱/배치 ${n_app}개 검사 · $status"

  if [ "$n_nginx" -eq 0 ] || [ "$n_app" -eq 0 ]; then
    [ "$n_nginx" -eq 0 ] && blind_add "로그권한 nginx 대상 0개($LOG_GLOB_DIR/realestate.{access,error}.log*)"
    [ "$n_app" -eq 0 ] && blind_add "로그권한 앱/배치 대상 0개($APP_LOG_GLOB)"
    # 본 것 중에 이상이 있으면 그건 그대로 알린다. 다만 clear 는 하지 않는다.
    [ -n "$bad" ] && raise_alert logperm 21600 "로그 권한이 0640 이 아니다 —$bad (자산 파생값이 남았던 그 경로다)"
    return 0
  fi

  if [ -n "$bad" ]; then
    raise_alert logperm 21600 "로그 권한이 0640 이 아니다 —$bad (자산 파생값이 남았던 그 경로다)"
  else
    clear_alert logperm "로그 권한 전부 0640/0600 회복 (nginx ${n_nginx}개 · 앱/배치 ${n_app}개)"
  fi
}

# ============================================================================
# 6) 로그로 쿼리가 새는가  ← 보안리뷰가 "판단이 바뀌어야 하는 신호"로 지정
#    · access log 는 re_noquery 포맷($uri)이라 쿼리스트링이 안 남아야 한다.
#    · error log 는 log_format 의 대상이 **아니다** → `request: "...?..."` 로 남는다.
#    ⚠️ 알림에는 **건수만** 넣는다. 새어 나온 내용을 알림에 담으면 우리가 다시
#       유출하는 것이다.
#    알려진 오탐 하나: $uri 는 디코딩된 값이라 `/a%3Fb=c` 같은 스캐너 요청이
#    `?b=` 로 보일 수 있다. 드물지만 가능하다 — 그때도 "확인할 값어치"는 있다.
#
#    ⛔ 파일이 없으면 `grep -c` 가 실패해 0 이 된다 → 예전에는 그게 "0건 · 이상 없음"
#       으로 나가고 clear_alert 까지 불렀다. 하필 **실제로 유출이 났던 경로**를
#       지키는 검사다. 이제는 못 읽으면 세지 않고 blind 로 넘긴다(CR40-2).
# ============================================================================
check_logleak() {
  local e a seen=0 unseen=0
  if readable "$ERROR_LOG"; then
    e=$(grep -cE 'request: "[^"]*\?' "$ERROR_LOG" 2>/dev/null); e=${e:-0}; seen=1
  else
    e=-1; unseen=1; blind_add "로그유출 error 대상 없음/못읽음($ERROR_LOG)"
  fi
  if readable "$ACCESS_LOG"; then
    a=$(grep -cE '"(GET|POST|PUT|PATCH|DELETE) [^ "]*\?[A-Za-z_][A-Za-z0-9_]*=' "$ACCESS_LOG" 2>/dev/null); a=${a:-0}; seen=1
  else
    a=-1; unseen=1; blind_add "로그유출 access 대상 없음/못읽음($ACCESS_LOG)"
  fi

  add "로그유출: access $([ "$a" -ge 0 ] && printf '%s건' "$a" || printf '검사못함') · error $([ "$e" -ge 0 ] && printf '%s건' "$e" || printf '검사못함') (기대 0/0)"

  if [ "$a" -gt 0 ] || [ "$e" -gt 0 ]; then
    raise_alert logleak 21600 "로그에 쿼리스트링이 남았다 (access ${a}건 / error ${e}건). 내용은 알림에 담지 않는다 — 서버에서 직접 확인: $ACCESS_LOG · $ERROR_LOG"
  elif [ "$unseen" = 0 ] && [ "$seen" = 1 ]; then
    clear_alert logleak "로그에 쿼리스트링 0건"
  fi
  # 하나라도 못 봤으면 clear 하지 않는다 — 못 본 것을 "없다"로 통보하지 않는다
}

# ============================================================================
# 6b) access 로그가 **살아 있는가** (mtime 신선도)
#     ⚠️ "파일이 없다"(=결함 · 위에서 잡는다)와 "내용이 안 늘었다"는 다른 것이다.
#        사람 트래픽이 없는 새벽에 로그가 안 커지는 것은 **정상**이라 그것으로는
#        경보하지 않는다. 그런데 우리 감시가 5분마다 https 로 메인·health·지도·
#        번들을 찌른다 → 그 요청 자체가 하루 1,000줄 이상 남는다(실측).
#        즉 24시간째 mtime 이 멈춰 있으면 그건 "조용한 밤"이 아니라
#        **nginx 가 이 파일에 안 쓰거나 우리가 엉뚱한 파일을 보고 있는 것**이다.
# ============================================================================
check_logfresh() {
  local mt now age_h
  readable "$ACCESS_LOG" || return 0     # 없음은 check_logleak 이 blind 로 이미 잡았다
  mt=$(stat -c %Y "$ACCESS_LOG" 2>/dev/null)
  if [ -z "$mt" ]; then
    add "로그신선: access mtime 을 못 읽음"
    blind_add "access 로그 mtime 확인 불가($ACCESS_LOG)"
    return 0
  fi
  now=$(date +%s); age_h=$(((now - mt) / 3600))
  add "로그신선: access 마지막 기록 ${age_h}시간 전 (임계 ${ACCESS_FRESH_MAX_HOURS}시간)"
  if [ "$age_h" -ge "$ACCESS_FRESH_MAX_HOURS" ]; then
    raise_alert logfresh 21600 "access 로그가 ${age_h}시간째 안 늘었다 — 감시 자체가 5분마다 사이트를 찌르므로 정상이면 계속 쌓인다. nginx 가 이 파일에 안 쓰거나(설정 변경·로테이션 오류) 우리가 엉뚱한 파일을 본다: $ACCESS_LOG"
  else
    clear_alert logfresh "access 로그 정상 기록 중 (${age_h}시간 전)"
  fi
}

# ============================================================================
# 7) 실사용에서 5xx 가 나는가  ← "헬스체크는 통과하는데 지도가 죽는" 형태
#    합성 요청은 인증 때문에 401 에서 멈춘다. 실제 사용자가 인증된 요청을
#    보냈을 때 500 이 나는지는 접근 로그만이 안다.
#    한계: 트래픽이 없으면 신호도 없다(개인용이라 원래 적다).
#
#    ⛔ 파일을 못 읽으면 **기준값도 건드리지 않고** 돌아간다. 예전에는 0 으로
#       덮어써서, 파일이 돌아오는 순간 누적 전체가 델타로 잡혀 폭증 경보가 났다.
# ============================================================================
check_api5xx() {
  local cur prev delta
  if ! readable "$ACCESS_LOG"; then
    add "API 5xx : 검사 못 함 — $ACCESS_LOG 없음/못 읽음"
    blind_add "API 5xx 대상 없음/못읽음($ACCESS_LOG)"
    return 0
  fi
  cur=$(grep -cE '"(GET|POST|PUT|PATCH|DELETE) /api/[^ "]* HTTP/[0-9.]+" 5[0-9][0-9] ' "$ACCESS_LOG" 2>/dev/null)
  cur=${cur:-0}
  prev=$(kv_get api5xx); prev=${prev:-}
  kv_set api5xx "$cur"
  if [ -z "$prev" ]; then
    add "API 5xx : 기준값 설정 (현재 파일 누적 ${cur}건)"
    return
  fi
  # 자정에 로테이션되면 파일이 새로 시작한다 → 감소는 리셋으로 본다
  # ⚠ **한계를 적어 둔다(CR42-5).** 이 가정은 회전으로 잘려 나간 꼬리를 버린다 —
  #   마지막 표본(≤5분 전) 이후에 회전 직전까지 난 5xx 는 영영 안 세어지고,
  #   그런데도 아래 요약은 그 구간을 `이번 구간 N건` 이라고 단정한다.
  #   SSH 쪽(check_sshlogin)은 같은 형태를 오프셋 추적으로 막았는데 여기는 안 막았다.
  #   그렇게 둔 근거: 잃는 창이 ≤5분이고 임계 1·쉼도 3600 이라 실해가 작다.
  #   **모르는 창이 있다는 것을 적어 두는 것**이 지금 할 수 있는 정직한 처리다.
  if [ "$cur" -lt "$prev" ]; then delta="$cur"; else delta=$((cur - prev)); fi
  add "API 5xx : 이번 구간 ${delta}건 (현재 파일 누적 ${cur}건)"
  if [ "$delta" -ge "$API5XX_MIN" ]; then
    raise_alert api5xx 3600 "/api/ 응답에 5xx ${delta}건 — 헬스체크가 200 이어도 기능이 죽었을 수 있다(지도·추천). 확인: grep ' 5[0-9][0-9] ' $ACCESS_LOG | tail"
  fi
}

# ============================================================================
# 7b) 비밀번호로 SSH 로그인에 **성공**한 흔적 (SR-036R 트립와이어 T2)
#
#    소유자가 root SSH 를 지금은 두기로 했고, 보안리뷰가 그것을 위험수용으로
#    기록하면서 재차단 조건 3가지를 걸었다. 그중 T2 를 **사람의 기억이 아니라
#    기계**가 지게 만드는 자리다. 위험수용의 조건이 스스로 감시되지 않으면
#    그건 수용이 아니라 망각이다.
#
#    · 우리 접속은 전부 공개키다(실측: Accepted publickey 1,427 · password 0).
#    · **성공만** 센다. 실패 88,316건은 소음이라 세지 않는다.
#    · 알림에 담는 것은 **건수뿐**이다 — 사용자명·IP·로그 원문을 보내지 않는다.
#      (그걸 보내면 우리가 감시하면서 같은 채팅방으로 유출하는 셈이다)
#    · auth.log 는 43MB 다. 5분마다 전부 훑으면 감시가 디스크를 먹는다 →
#      **마지막으로 본 바이트 위치부터만** 읽는다. syslog 는 한 줄을 한 번의
#      write 로 쓰므로 그 경계는 항상 줄 경계다(잘린 줄이 생기지 않는다).
#    · 읽는 구간은 **이번에 잰 크기까지**로 자른다(CR41-7). stat 과 tail 사이에
#      붙은 줄을 이번에도 세고 다음에도 세면, 진짜 사건일 때 중복 경보가 된다.
#
# ---------------------------------------------------------------------------
# ⛔ 이 검사가 세 라운드에 걸쳐 배운 것 — **증거는 "무엇을 보는가"가 아니라
#    "누가 그 값을 만들 수 있는가"로 골라야 한다.**
#
#    1라운드(SR37-1) : "줄었으면 로테이션" → ⓑ.1.gz ⓒ`: >` ⓓ회전 후 초과성장을 놓쳤다.
#    2라운드(CR41-3) : inode 가 바뀌었으면 회전 / 줄었는데 회전본이 방금 생겼으면(mtime)
#                      회전 / 그 밖의 축소는 truncate. ⓒ는 잡혔다.
#    3라운드(CR42-2 · SR38-1/2/3) : **그 판정이 네 방향으로 더 뚫렸다.**
#      · `rm auth.log && touch auth.log` → inode 가 바뀌었으니 **증거 없이 회전 확정**.
#        낡은 `.1` 이 오프셋보다 크면 그 꼬리까지 세면서 **완전 침묵**했다.
#        (서버형 delaycompress 는 회전 직후 한동안 **항상** 그 조건이다)
#      · `: > auth.log` **+ `touch auth.log.1`** → mtime 증거는 **공격자가 만든다**.
#      · 회전 뒤 `.1` 안에서 그 줄만 지우기 → `.1` 은 크기만 보고 내용·정체는 안 봤다.
#      · `auth.log` 동결(rsyslog 정지) → 아무 변화가 없으니 **"이번 구간 0건(기대 0)"**.
#        공격 없이 **고장만으로도** 난다.
#
#    → 그래서 증거를 **위조 비용으로 등급을 나눈다.**
#      · 강한 증거 : `.1` 의 inode == 우리가 마지막으로 본 auth.log 의 inode.
#        `create` 방식 로테이션은 rename(2) 이라 이 값이 **보존된다**. 공격자가
#        이걸 맞추려면 auth.log 를 실제로 `.1` 로 옮겨야 하고, 그러면 **증거가
#        `.1` 안에 그대로 남아** 우리가 다음 회차에 센다. `touch` 로는 못 만든다.
#      · 약한 증거 : 회전본의 mtime 이 우리가 본 뒤다. `touch` 한 줄이면 만들어진다.
#        **단독으로는 회전을 확정하지 않는다.** 압축 회전본(`.1.gz`)은 gzip 이 새
#        파일을 만들어 inode 불변식이 성립하지 않으므로 거기서만 쓰고,
#        쓸 때는 반드시 `blind_add` 로 "약한 증거였다"를 남긴다.
#      · 새 파일인데 어느 증거도 없다 → `replaced`. **회전이라고 부르지 않는다.**
#
#    ⚠️ inode 만으로는 부족하다는 것도 그대로 유효하다(실측: ext4 는 지우고 곧바로
#       만들면 같은 번호를 재사용한다 — 서버 `/var/log` 의 번호 분포로 확인됐다).
#       그래서 "inode 가 바뀌었다"도 "inode 가 같다"도 **혼자서는 아무것도 증명하지
#       못한다.** 증명하는 것은 `.1` 이 우리가 추적하던 그 파일이라는 사실뿐이다.
#
#    ⚠️ **치른 값을 적어 둔다(정직하게).** 이 판정은 `copytruncate` 방식 로테이션을
#       흔적 삭제와 **구별하지 못한다** — 그쪽은 `.1` 을 새로 복사해 만들고 원본을
#       비우므로, 공격자가 "그럴듯한 `.1` 을 새로 만들고 원본을 비우는" 것과 파일
#       메타데이터가 같아진다. 둘 중 하나만 잡을 수 있고 우리는 후자를 골랐다.
#       근거: 이 서버의 `/etc/logrotate.d/rsyslog` 는 `create`(rename) + `delaycompress`
#       다(실측). 로테이션 방식을 `copytruncate` 로 바꾸면 **매주 authshrink 가 뜬다** —
#       그건 오탐이지만 침묵보다 낫고, 경보 문구가 그 가능성을 먼저 적어 둔다.
#
#    **회전본으로 설명되지 않으면 조용히 넘기지 않는다.** 못 본 것은 못 본 것이다.
# ============================================================================
SSHPW_RE='Accepted (password|keyboard-interactive)'
_sshpw_grep() { grep -cE "$SSHPW_RE" 2>/dev/null; }
check_sshlogin() {
  local size off ino prev_ino prev_at now_s cand cmt delta base old_size how explained=0 tail_old=0
  local rot_strong=0 rot_weak=0 gz_only=0 old_short=0 r1_ino="" r1_size="" prev_r1_ino prev_r1_size
  local amt a_age=0 auth_frozen=0 edit_why="" gap_why=""
  local prev_amt auth_fake=0 jd="" jd_ok=0 jd_txt="교차 불가" jd_gap="" prev_jd since
  if ! readable "$AUTH_LOG"; then
    add "SSH     : 검사 못 함 — $AUTH_LOG 없음/못 읽음"
    blind_add "SSH 비밀번호 로그인 감시 대상 없음/못읽음($AUTH_LOG)"
    return 0
  fi
  # ⚠️ 크기·inode·mtime 을 **한 번의 stat 으로** 읽는다. 따로 부르면 그 사이에 쓰기가
  #    끼어들어 "크기는 옛것 · mtime 은 새것" 이 정상적으로 만들어지고, 아래 ⓪b 가
  #    **없는 사건을 보고**한다. 서버는 Failed password 가 상시 쌓여(89,534건) 이 창이
  #    실제로 열려 있다. 오탐이 결함이라는 원칙은 새 검사에도 그대로 적용된다.
  IFS='|' read -r size ino amt <<<"$(stat -c '%s|%i|%Y' "$AUTH_LOG" 2>/dev/null)"
  size=${size:-0}
  now_s=$(date +%s)
  off=$(kv_get sshpw_off)
  prev_ino=$(kv_get sshpw_ino)
  prev_at=$(kv_get sshpw_at)
  prev_r1_ino=$(kv_get sshpw_r1_ino)
  prev_r1_size=$(kv_get sshpw_r1_size)
  if [ -f "$AUTH_LOG.1" ]; then
    r1_ino=$(stat -c %i "$AUTH_LOG.1" 2>/dev/null)
    r1_size=$(stat -c %s "$AUTH_LOG.1" 2>/dev/null)
  fi

  # --- ⓪ auth.log 자체가 살아 있는가 (SR38-3) --------------------------------
  #    ⚠️ 이건 공격자 전용이 아니라 **평범한 고장**에서도 난다 — rsyslog 가 멈추면
  #       파일은 그대로 있고 줄지도 않는다. 그러면 아래 계산은 전부 "변화 없음"이
  #       되고 요약은 `0건 (기대 0)` 이라고 **적극적으로 안전을 선언**한다.
  #       그건 "봤고 괜찮다"이지 "못 봤다"가 아니다 — CR40-2 가 세운 원칙을
  #       이 파일이 스스로 어기는 자리였다.
  #    check_logfresh 가 access 로그에 하는 것과 **같은 모양**이다. 이쪽만 없었다.
  #    임계 6시간의 근거: 서버는 `Failed password` 가 88,316건 쌓여 있어 auth.log 가
  #    상시 갱신된다 — 오탐이 사실상 0이다.
  if [ -z "$amt" ]; then
    add "SSH신선 : auth.log mtime 을 못 읽음"
    blind_add "auth.log mtime 확인 불가($AUTH_LOG)"
  else
    a_age=$(((now_s - amt) / 3600))
    add "SSH신선 : auth.log 마지막 기록 ${a_age}시간 전 (임계 ${AUTH_FRESH_MAX_HOURS}시간)"
    if [ "$a_age" -ge "$AUTH_FRESH_MAX_HOURS" ]; then
      auth_frozen=1
      blind_add "auth.log 가 ${a_age}시간째 안 늘었다 — T2 가 눈을 감고 있다($AUTH_LOG)"
      raise_alert authfresh 21600 "auth.log 가 ${a_age}시간째 기록되지 않는다 — 비밀번호 로그인 감시(T2)가 무효 상태다. 이 동안의 '0건'은 '괜찮다'가 아니라 '못 봤다'이다. 원인은 rsyslog 정지·파이프 파손·경로 변경일 수 있다. 확인: systemctl status rsyslog · ls -l ${AUTH_LOG}"
    else
      clear_alert authfresh "auth.log 정상 기록 중 (${a_age}시간 전)"
    fi
  fi

  # --- ⓪b mtime 은 새것인데 크기가 그대로다 (SR39-2 x10 · SR39-1 x9) ----------
  #   append-only 로그는 **쓰면 커진다.** "mtime 이 앞으로 갔는데 크기가 한 바이트도
  #   안 늘었다"는 조합은 정상 운영에 존재하지 않는다. 그런 상태를 만드는 길은 둘뿐이다:
  #     · `touch auth.log` — 로그는 얼어 있는데 **신선도 증거만 위조**한다(SR39-2 x10).
  #       ⓪ 의 증거가 mtime 하나뿐이라, 그 하나를 위조하면 `authfresh` 도 `blind` 도
  #       안 뜨고 완전히 침묵했다. 같은 라운드가 회전 판정에서는 *"mtime 은 위조 비용이
  #       0이라 단독으로 쓰지 않는다"* 고 못 박아 놓고 ⓪ 에는 그 원칙을 안 썼다.
  #     · 이미 쓰인 구간을 **같은 길이로 덮어쓴다**(SR39-1 x9) — 침입 줄을 평범한 줄로
  #       바꾼다. 크기·inode 는 보존되고 **mtime 만 바뀐다**. 그 하나가 유일한 증거다.
  #   ⚠️ 오탐 0의 조건이 위의 **한 번의 stat** 이다(따로 읽으면 정상 쓰기가 이 모양이 된다).
  #   ⚠️ 회전·교체·축소는 크기나 inode 가 달라지므로 여기 안 걸린다 — 그쪽은 ①②가 본다.
  prev_amt=$(kv_get sshpw_mtime)
  [ -n "$amt" ] && kv_set sshpw_mtime "$amt"
  if [ -n "$amt" ] && [ -n "$prev_amt" ] && [ -n "$off" ] && [ -n "$ino" ] && [ -n "$prev_ino" ] &&
     [ "$ino" = "$prev_ino" ] && [ "$size" = "$off" ] && [ "$size" -gt 0 ] &&
     [ "$amt" -gt "$prev_amt" ] 2>/dev/null; then
    auth_fake=1
    add "SSH     : auth.log mtime 이 갱신됐는데 크기가 ${size}바이트 그대로다"
    blind_add "auth.log 가 mtime 만 갱신되고 크기가 안 늘었다 — 신선도 위조 또는 같은 길이 덮어쓰기($AUTH_LOG)"
    raise_alert authfake 21600 "auth.log 의 mtime 은 새것인데 크기가 ${size}바이트 그대로다 — append-only 로그에서는 일어나지 않는 조합이다. ① touch 로 신선도 증거만 위조했거나(로그는 얼어 있다) ② 이미 기록된 구간을 같은 길이로 덮어썼을(흔적 삭제) 가능성이다. 어느 쪽이든 그 구간의 비밀번호 로그인 성공은 셀 수 없다. 확인: ls -l --time-style=full-iso ${AUTH_LOG} · systemctl status rsyslog · journalctl -u ssh --since -1h | grep Accepted"
  fi

  if [ -z "$off" ]; then
    # 기준값 설정. 이때는 파일 전체를 센다 — **이미 성공한 흔적이 있으면
    # 그것도 사건이다.** 0 이 아닌 채로 조용히 시작하지 않는다.
    base=$(grep -cE "$SSHPW_RE" "$AUTH_LOG" 2>/dev/null); base=${base:-0}
    kv_set sshpw_off "$size"; kv_set sshpw_ino "$ino"; kv_set sshpw_at "$now_s"
    kv_set sshpw_r1_ino "$r1_ino"; kv_set sshpw_r1_size "${r1_size:-}"
    add "SSH     : 기준값 설정 (비밀번호 로그인 성공 현재 파일 누적 ${base}건 · 기대 0)"
    if [ "$base" -gt 0 ]; then
      raise_alert sshpw 0 "비밀번호 SSH 로그인 성공 흔적 ${base}건이 이미 있다 (감시 첫 실행 · 우리 접속은 전부 공개키여야 한다). 즉시 확인: last | head · grep 'Accepted password' $AUTH_LOG | tail"
    fi
    return 0
  fi

  # --- ① 회전 증거를 모은다 (등급별) ------------------------------------------
  # 강한 증거: `.1` 의 inode == 우리가 마지막으로 본 auth.log 의 inode (rename 불변식)
  if [ -n "$r1_ino" ] && [ -n "$prev_ino" ] && [ "$r1_ino" = "$prev_ino" ]; then
    rot_strong=1
  fi
  # 약한 증거: 회전본이 우리가 마지막으로 본 뒤에 생겼다 (mtime — 위조 가능)
  for cand in "$AUTH_LOG.1" "$AUTH_LOG.1.gz"; do
    [ -f "$cand" ] || continue
    cmt=$(stat -c %Y "$cand" 2>/dev/null); cmt=${cmt:-0}
    if [ -z "$prev_at" ] || [ "$cmt" -ge "$prev_at" ]; then rot_weak=1; fi
  done
  # 압축 회전(`compress` · delaycompress 없음)은 `.1` 이 사라지고 `.1.gz` 만 남는다.
  # gzip 이 만든 **새 파일**이라 inode 불변식이 성립하지 않는다 → 약한 증거만 가능하다.
  if [ ! -f "$AUTH_LOG.1" ] && [ -f "$AUTH_LOG.1.gz" ]; then gz_only=1; fi

  # --- ② 마지막으로 본 뒤 이 파일이 어떻게 변했는가 ---------------------------
  if [ "$rot_strong" = 1 ]; then
    how=rotated                        # 증명됐다: `.1` 이 우리가 추적하던 그 파일이다
  elif [ "$gz_only" = 1 ] && [ "$rot_weak" = 1 ]; then
    how=rotated_gz                     # 약한 증거 — 세되 "약했다"를 남긴다
  elif [ -n "$prev_ino" ] && [ -n "$ino" ] && [ "$ino" != "$prev_ino" ]; then
    how=replaced                       # ⛔ 새 파일인데 회전본이 그것을 설명하지 못한다
  elif [ "$size" -lt "$off" ]; then
    how=shrunk
  else
    how=grown
  fi

  case "$how" in
    grown)
      if [ "$size" -gt "$off" ]; then
        delta=$(tail -c "+$((off + 1))" "$AUTH_LOG" 2>/dev/null | head -c "$((size - off))" | _sshpw_grep)
      else
        delta=0
      fi
      delta=${delta:-0}; explained=1
      ;;
    rotated|rotated_gz)
      # 새 파일은 처음부터 전부 (이번에 잰 크기까지만)
      delta=$(head -c "$size" "$AUTH_LOG" 2>/dev/null | _sshpw_grep); delta=${delta:-0}
      # 옛 파일에서 아직 안 본 꼬리 — 평문 `.1` 우선, 없으면 `.1.gz` 를 풀어서 본다
      if readable "$AUTH_LOG.1"; then
        old_size=$(stat -c %s "$AUTH_LOG.1" 2>/dev/null); old_size=${old_size:-0}
        if [ "$old_size" -ge "$off" ]; then
          tail_old=$(tail -c "+$((off + 1))" "$AUTH_LOG.1" 2>/dev/null | _sshpw_grep)
          delta=$((delta + ${tail_old:-0})); explained=1
        else
          old_short=1                  # 회전본이 우리가 본 구간보다 작다 = 그 안이 지워졌다
        fi
      elif [ -f "$AUTH_LOG.1.gz" ] && [ -r "$AUTH_LOG.1.gz" ] && command -v gzip >/dev/null 2>&1; then
        old_size=$(gzip -dc "$AUTH_LOG.1.gz" 2>/dev/null | wc -c); old_size=${old_size:-0}
        if [ "$old_size" -ge "$off" ]; then
          tail_old=$(gzip -dc "$AUTH_LOG.1.gz" 2>/dev/null | tail -c "+$((off + 1))" | _sshpw_grep)
          delta=$((delta + ${tail_old:-0})); explained=1
        else
          old_short=1
        fi
      fi
      if [ "$how" = rotated_gz ]; then
        # 약한 증거로 판정했다는 사실 자체를 남긴다 — "봤다"고 말하지 않는다.
        blind_add "auth.log 회전을 mtime(약한 증거 · 위조 가능)으로만 확인함 — 압축 회전본에는 inode 불변식이 없다($AUTH_LOG)"
      fi
      ;;
    replaced|shrunk)
      # 남아 있는 것만이라도 센다. 사라진 구간은 **셀 수 없다** — 그걸 0건이라 말하지 않는다.
      delta=$(head -c "$size" "$AUTH_LOG" 2>/dev/null | _sshpw_grep); delta=${delta:-0}
      ;;
  esac

  # --- ③ 회전본(.1) 이 회전 없이 바뀌었는가 (SR38-2) --------------------------
  #     회전본의 불변식: **`.1` 은 로테이션 때만 바뀐다.** 만들어진 뒤에는 내용도
  #     정체도 변하지 않고, 다음 회전 때 이름이 `.2` 로 밀릴 뿐이다.
  #     ⚠️ "같은 inode 인데 작아졌다"만 보면 부족하다 — `sed -i` 는 임시파일을 만들어
  #        rename 하므로 **inode 가 바뀐다**(직접 확인했다). 그래서 정체 변화도 본다.
  #     ⚠️ 한계: 회전 **직후**, 우리가 `.1` 을 처음 보기 **전에** 편집하면 이 검사로는
  #        못 잡는다. 그때는 아래 `old_short` 이 잡는데, 그것도 지운 양이 마지막
  #        표본(≤5분) 이후 늘어난 양보다 커야 걸린다. 못 잡는 창이 있다 — 없는 척하지 않는다.
  if [ -n "$prev_r1_ino" ]; then
    if [ -n "$r1_ino" ] && [ "$r1_ino" = "$prev_r1_ino" ]; then
      if [ -n "$prev_r1_size" ] && [ "${r1_size:-0}" -lt "$prev_r1_size" ]; then
        edit_why="같은 파일(inode 동일)인데 ${prev_r1_size}→${r1_size}바이트로 줄었다"
      fi
    else
      case "$how" in
        rotated) ;;                                 # 회전이면 `.1` 이 바뀌는 것이 정상이다
        rotated_gz)
          # ⛔ SR39-3 — `delaycompress` 서버에서 평문 `.1` 은 **압축본으로 바뀌지 않는다.**
          #    회전하면 `.1` 은 `.2` 로 밀리고 거기서 압축된다(`.2.gz`) — 즉 `.1.gz` 라는
          #    상태 자체가 없다(실측: 이 서버는 rotate 4 · weekly · compress · delaycompress).
          #    그러므로 "우리가 평문 `.1` 을 추적하고 있었는데 지금 `.1` 이 없고 `.1.gz` 만
          #    있다"는 정상 운영에 존재하지 않는다. `: > auth.log` + 가짜 `.1.gz` 가 정확히
          #    그 모양인데, 지금까지는 약한 증거(`rotated_gz`)로 **세어 주고** 있었고
          #    사람이 받는 이름은 "감시 불능"이라 흔적 삭제로 읽히지 않았다.
          #    ⚠️ 오탐 0인 근거는 조건이 **설정이 아니라 관측**이라는 것이다:
          #       `compress`(delaycompress 없음) 서버는 평문 `.1` 이 애초에 없어
          #       `prev_r1_ino` 가 비고 이 case 에 들어오지 못한다.
          if [ -z "$r1_ino" ]; then
            edit_why="추적하던 평문 .1 이 사라지고 .1.gz 만 남았다(delaycompress 로테이션에서는 .1 이 .2 로 밀린다 — 압축본으로 바뀌지 않는다). ※ 로테이션 설정을 compress 로 바꿨다면 그 때문일 수 있다"
          fi
          ;;
        *)
          if [ -n "$r1_ino" ]; then
            edit_why="로테이션이 없었는데 .1 이 다른 파일로 바뀌었다(편집 도구는 임시파일을 rename 하므로 inode 가 바뀐다)"
          elif [ ! -f "$AUTH_LOG.1.gz" ]; then
            # `.1` 이 사라졌다. 압축본이 생긴 것이라면 정상이므로 그때는 넘긴다.
            edit_why="로테이션이 없었는데 .1 이 사라졌다(압축본 .1.gz 도 없다)"
          fi
          ;;
      esac
    fi
  fi
  if [ -n "$edit_why" ]; then
    add "SSH     : 회전본 auth.log.1 이상 — $edit_why"
    blind_add "auth.log.1 이 로테이션 없이 바뀌었다($edit_why)"
    raise_alert authedit 21600 "회전본 auth.log.1 이 로테이션 없이 바뀌었다 — $edit_why. 회전본은 만들어진 뒤 변하지 않는다(다음 회전 때 이름이 밀릴 뿐이다): 흔적 삭제 가능성이다. 그 구간의 비밀번호 로그인 성공은 셀 수 없다. 확인: ls -li ${AUTH_LOG}*"
  fi

  # --- ③b 두 번째 출처(journald)와 교차 (SR39-1) ------------------------------
  #   ⛔ **메타데이터로는 원리적으로 못 보는 칸이 있다.** 위 증거는 전부 크기·inode·
  #      mtime 인데, 공격자가 바꾸는 것은 *우리가 아직 읽지 않은 구간의 내용*이다.
  #      ⓪b 가 "같은 길이 덮어쓰기"를 mtime 하나로 겨우 잡지만, 공격자가 직접 `mv` 로
  #      회전시켜 **강한 증거를 성립시킨 뒤** `.1` 을 덮어쓰면 그것도 못 본다 —
  #      `rename(2)` 은 **정체만** 보존하지 내용을 보존하지 않는다. 옛 주석은 뒤쪽까지
  #      증명한다고 적었는데 그건 과장이었다. 같은 파일 안에 반증할 값이 없다.
  #      **회피 표를 한 칸 더 채우는 방식으로는 이 칸에 못 닿는다.**
  #   → 그래서 **출처를 하나 더 본다.** 이 서버는 영구 journald 가 살아 있고
  #      (`/var/log/journal` · 아카이브 포함 2.0G · 24시간 sshd `Accepted` 258건 실측)
  #      sshd 메시지를 auth.log 와 **독립적으로** 보관한다. 바이너리 저널이라 바이트
  #      단위 in-place 덮어쓰기가 통하지 않는다. 공격자는 이제 **두 곳을 지워야** 한다.
  #   ⚠️ **한계를 적는다(없는 척하지 않는다).** journald 도 root 면 지울 수 있다
  #      (`journalctl --rotate --vacuum-time=1s`). 이 교차는 침입을 불가능하게 만들지
  #      않고 **비용을 한 단계 올릴 뿐**이다. 그래서 두 번째 출처가 **사라지는 것 자체**도
  #      신호로 본다(`sshjournal`). 그리고 journald 가 없는 호스트에서는 아무 일도 안 한다.
  #   ⚠️ 비교가 아니라 **각자 세는** 쪽을 골랐다. `--since` 는 초 단위라 창 경계에서 두
  #      출처가 정상적으로 1 만큼 어긋날 수 있고, 그 차이를 경보로 쓰면 오탐이 된다.
  #      대신 **어느 쪽이든 0 보다 크면 경보**다 — 이 서버의 기대값은 양쪽 다 0 이다
  #      (실측: 전 회전본 통틀어 `Accepted password` 0 · 성공은 전부 publickey 1,476).
  #      수가 어긋난 사실은 같은 알림 본문에 문장으로 싣는다.
  if command -v journalctl >/dev/null 2>&1 && journalctl -n 1 --no-pager >/dev/null 2>&1; then
    jd_ok=1
    case "$prev_at" in
      ''|*[!0-9]*) since=$((now_s - 86400)) ;;
      *) since="$prev_at"; [ $((now_s - since)) -le 86400 ] || since=$((now_s - 86400)) ;;
    esac
    jd=$(journalctl -u ssh -u sshd --since "@$since" --no-pager -o cat 2>/dev/null | grep -cE "$SSHPW_RE")
    jd=${jd:-0}; jd_txt="${jd}건"
    add "SSH2차  : journald 같은 구간 ${jd}건 (auth.log ${delta}건 · 기대 0/0)"
    if [ "$jd" -gt "$delta" ]; then
      jd_gap=" ⚠️ 두 출처의 수가 다르다(journald ${jd} > auth.log ${delta}) — auth.log 가 사후에 편집됐을 수 있다(같은 길이 덮어쓰기는 크기·inode 를 보존한다)."
    fi
  else
    add "SSH2차  : journald 교차 불가 — auth.log 한 출처만 본다(같은 길이 덮어쓰기를 반증할 방법이 없다)"
  fi
  prev_jd=$(kv_get sshpw_jd)
  if [ "$prev_jd" = 1 ] && [ "$jd_ok" = 0 ]; then
    blind_add "SSH 2차 출처(journald)가 사라졌다 — 교차 검증 불가"
    raise_alert sshjournal 86400 "어제까지 쓰던 두 번째 로그 출처(journald)가 응답하지 않는다 — auth.log 한 곳만 남으면 '같은 길이로 덮어쓴 침입 줄'을 반증할 방법이 없다(SR39-1). 확인: systemctl status systemd-journald · journalctl --disk-usage · ls -ld /var/log/journal"
  fi
  kv_set sshpw_jd "$jd_ok"

  kv_set sshpw_off "$size"; kv_set sshpw_ino "$ino"; kv_set sshpw_at "$now_s"
  kv_set sshpw_r1_ino "$r1_ino"; kv_set sshpw_r1_size "${r1_size:-}"

  # --- ④ 요약 한 줄 — **못 본 것을 "기대 0" 이라고 쓰지 않는다** ---------------
  #     이 한 줄이 CR42-2 / SR38-3 의 핵심이다. 옛 코드는 어떤 경우에도
  #     "이번 구간 0건 (기대 0)" 을 적었고, 그건 **적극적인 무사고 선언**이다.
  #     경보가 따로 나가더라도 요약이 "괜찮다"고 말하면 사람은 요약을 믿는다.
  if [ "$auth_frozen" = 1 ]; then
    gap_why="auth.log 가 ${a_age}시간째 안 늘었다"
  elif [ "$auth_fake" = 1 ]; then
    gap_why="auth.log 의 mtime 만 갱신되고 크기가 안 늘었다(같은 길이 덮어쓰기 가능성)"
  elif [ "$explained" != 1 ]; then
    case "$how" in
      replaced) gap_why="auth.log 가 회전 증거 없이 새 파일로 바뀌었다" ;;
      shrunk)   gap_why="auth.log 가 ${off}→${size}바이트로 줄었다(회전 아님)" ;;
      *)        if [ "$old_short" = 1 ]; then gap_why="회전본이 우리가 본 구간보다 작다"
                else gap_why="회전본(.1/.1.gz)을 못 읽었다"; fi ;;
    esac
  fi
  if [ -n "$gap_why" ]; then
    add "SSH     : 비밀번호 로그인 성공 이번 구간 ${delta}건 — ⚠️ 못 본 구간이 있다($gap_why). 이 0건은 '괜찮다'가 아니다"
  else
    add "SSH     : 비밀번호 로그인 성공 이번 구간 ${delta}건 (기대 0)"
  fi
  if [ "$delta" -gt 0 ] || [ "${jd:-0}" -gt 0 ]; then
    raise_alert sshpw 0 "비밀번호로 SSH 로그인 성공 — auth.log ${delta}건 · journald ${jd_txt} (기대 0/0).${jd_gap} 우리 접속은 전부 공개키다. 보안리뷰 트립와이어 T2 가 걸렸다: SSH 를 먼저 잠근다. 확인: last | head · grep 'Accepted password' $AUTH_LOG | tail · journalctl -u ssh --since -1h | grep Accepted"
  fi

  if [ "$explained" = 1 ]; then
    clear_alert authshrink "auth.log 추적 정상 (${how})"
  elif [ "$how" = shrunk ]; then
    add "SSH     : auth.log 가 ${off}→${size}바이트로 줄었다 — 회전이 아니다(회전본이 우리가 추적하던 파일이 아니다)"
    blind_add "auth.log 축소를 회전으로 설명 못함(truncate · $AUTH_LOG)"
    raise_alert authshrink 21600 "auth.log 가 ${off}→${size}바이트로 줄었는데 로테이션이 아니다 — 직전본 .1 이 우리가 추적하던 파일이 아니다(mtime 만 새것인 것은 증거가 아니다). 로그 truncate, 즉 흔적 삭제 가능성. 지워진 구간의 로그인 성공은 셀 수 없다. ※ 로테이션을 copytruncate 로 바꿨다면 그 때문일 수 있다(이 서버는 create+delaycompress 다). 확인: ls -li ${AUTH_LOG}* · last | head"
  elif [ "$how" = replaced ]; then
    add "SSH     : auth.log 가 새 파일로 바뀌었는데 회전본이 그것을 설명하지 못한다 (${off}→${size}바이트)"
    blind_add "auth.log 가 교체됨(.1 inode != 직전 inode · 회전 아님 · $AUTH_LOG)"
    raise_alert authshrink 21600 "auth.log 가 새 파일로 바뀌었는데 로테이션 증거가 없다 — 직전본 .1 의 inode 가 우리가 추적하던 파일과 다르다(진짜 회전은 rename 이라 반드시 같다). rm 후 재생성, 즉 흔적 삭제 가능성이다. 사라진 구간의 로그인 성공은 셀 수 없다. ※ 감시가 한 번의 로테이션 주기보다 오래 멈춰 있었다면 그 때문일 수도 있다(그 경우에도 그 구간은 못 센 것이 맞다). 확인: ls -li ${AUTH_LOG}* · last | head"
  elif [ "$old_short" = 1 ]; then
    add "SSH     : 회전했는데 직전본이 우리가 본 구간(${off}바이트)보다 작다"
    blind_add "auth.log 회전본이 오프셋보다 작아 못 본 구간을 셀 수 없다($AUTH_LOG.1)"
    raise_alert authshrink 21600 "auth.log 가 회전했는데 직전본이 우리가 마지막으로 본 위치(${off}바이트)보다 작다 — 회전본 안이 지워졌을 수 있다. 그 구간의 비밀번호 로그인 성공을 셀 수 없다. 확인: ls -l ${AUTH_LOG}*"
  else
    add "SSH     : auth.log 가 회전했는데 회전본을 못 읽었다"
    blind_add "auth.log 회전본(.1/.1.gz)을 못 읽어 못 본 구간을 셀 수 없다($AUTH_LOG)"
    raise_alert authshrink 21600 "auth.log 가 회전했는데 직전본(.1 또는 .1.gz)을 읽을 수 없다 — 회전 직전 구간의 비밀번호 로그인 성공을 셀 수 없다(압축 방식 변경·삭제·권한). 확인: ls -l ${AUTH_LOG}*"
  fi
}

# ============================================================================
# 7c) 위 로그 검사들이 **아무것도 못 본 상태**를 한 통으로 알린다
#     3개 검사가 각각 울면 3통이 간다 → 사유를 모아 한 통으로 보낸다.
#     이 경보가 켜져 있는 동안 로그권한·로그유출·5xx·SSH 는 "이상 없음"이 아니라
#     "모른다" 이다.
# ============================================================================
#     ⛔ CR43-1 — **모드 대칭.** 아래 `carried` 가 그것이다.
#        `--daily` 는 이번 실행에서 인증서·DB 까지 전부 재평가했으므로 `BLIND` 가 곧
#        전부다 → 비었으면 진짜 해소다(그리고 그 사실을 kv 에 남긴다).
#        `--fast` 는 그 둘을 **돌리지도 않았다** → 자기가 재평가하지 못한 사유가
#        살아 있으면 `clear_alert` 를 부를 자격이 없다. "못 본 것을 해소라고 말하지
#        않는다"(CR40-2)는 원칙은 **다른 모드가 본 것**에도 그대로 적용된다.
check_logblind() {
  local carried=""
  if [ "$MODE" = daily ]; then
    kv_set blind_daily "$BLIND_DAILY"
  else
    carried=$(kv_get blind_daily)
  fi
  if [ -n "$BLIND" ]; then
    add "감시불능:$BLIND"
    raise_alert logblind 21600 "로그 감시가 눈이 먼 상태 —$BLIND 대상이 0개인 것을 '이상 없음'으로 넘기지 않는다(경로 변경·로테이션 오류·마운트 누락을 의심). 확인: ls -l $LOG_GLOB_DIR/realestate.* $APP_LOG_GLOB $AUTH_LOG"
  elif [ -n "$carried" ]; then
    # 이번 5분 검사는 정상이지만, 일일 점검이 남긴 사유는 **우리가 다시 본 것이 아니다.**
    # 여기서 clear 하면 인증서를 본 적도 없이 인증서 사유를 해소하게 된다.
    add "감시불능: 5분 검사는 정상 · 일일 점검이 남긴 사유가 아직 있다 —$carried (다음 일일 점검이 다시 판정한다)"
  else
    if [ "$MODE" = daily ]; then
      clear_alert logblind "로그 감시 대상 정상 (권한·유출·5xx·SSH·인증서·DB 검사 전부 수행)"
    else
      clear_alert logblind "로그 감시 대상 정상 (권한·유출·5xx·SSH 검사 수행 · 인증서·DB 는 일일 점검이 본다)"
    fi
  fi
}

# ============================================================================
# 8) 감시 자체가 살아 있는가 (상호 감시)
#    fast 는 daily 를, daily 는 fast 를 본다. 둘 다 죽으면 매일 오던 요약이
#    안 온다 — 그게 마지막 방어선이다(사람이 부재로 안다).
# ============================================================================
check_peer_alive() {
  local last now age first
  if [ "$MODE" = fast ]; then
    last=$(kv_get last_daily_run)
    if [ -z "$last" ]; then
      # ⛔ **15번째 자리 — 대칭이 같은 함수 안에서 깨져 있었다(내가 이번에 찾았다).**
      #    아래 daily 쪽은 *"5분 감시가 한 번도 돈 기록이 없다 — 크론(*/5)이 안 걸렸다"*
      #    를 **경보로** 만든다. 그런데 fast 쪽은 정확히 같은 상황(일일 점검이 한 번도
      #    안 돌았다)에서 `return 0` 으로 조용히 넘어갔다. 실측(격리): `--fast` 만 8회
      #    돌려도 `daily_dead` **0건** · 경보 목록에 그 이름이 아예 없다.
      #    잃는 것이 작지 않다 — `--daily` 에만 있는 검사가 인증서(9·9b)·DB구조(10·11b)·
      #    시장지수 신선도(11)·DB 크래시(12)·컨테이너 로그(13) **일곱 개**다. 그게 통째로
      #    없는 상태가 되고, 드러나는 유일한 경로가 *"아침 요약이 안 온다"* 라는
      #    **사람의 기억**이다. 이 파일이 CR40-2 부터 계속 거부해 온 바로 그 형태다.
      #    (그리고 지금이 그 위험이 실재하는 시점이다 — 크론 2줄을 서버에 **새로**
      #     넣는 배포가 눈앞이고, 한 줄을 빠뜨리면 이 자리가 조용히 열린다.)
      #    ⚠️ 설치 직후 곧바로 울면 그건 오탐이다(일일 점검은 하루 한 번뿐이다).
      #       → **첫 fast 실행 시각을 기억하고 거기서부터 유예**를 준다. 임계는
      #       아래 "낡음" 판정과 같은 값(DAILY_MAX_HOURS=30시간)이라 규칙이 하나다.
      first=$(kv_get first_fast_run)
      if [ -z "$first" ]; then kv_set first_fast_run "$(date +%s)"; return 0; fi
      now=$(date +%s); age=$(((now - first) / 3600))
      if [ "$age" -ge "$DAILY_MAX_HOURS" ]; then
        raise_alert daily_dead 21600 "일일 점검이 **한 번도** 돈 기록이 없다(5분 감시는 ${age}시간째 정상으로 돌고 있다) — 크론 '5 9 * * * ... monitor.sh --daily' 가 안 걸렸거나 매번 죽는다. 그러면 인증서·DB구조·시장지수 신선도·DB크래시·컨테이너로그 감시가 통째로 없는 상태다. 확인: crontab -l | grep monitor.sh"
      fi
      return 0
    fi
    now=$(date +%s); age=$(((now - last) / 3600))
    if [ "$age" -ge "$DAILY_MAX_HOURS" ]; then
      raise_alert daily_dead 21600 "일일 요약 감시가 ${age}시간 동안 안 돌았다 — 크론(5 9 * * *)이 사라졌거나 실패한다"
    else
      clear_alert daily_dead "일일 요약 감시 정상 (${age}시간 전)"
    fi
  else
    last=$(kv_get last_fast_run)
    if [ -z "$last" ]; then
      raise_alert fast_dead 21600 "5분 감시가 한 번도 돈 기록이 없다 — 크론(*/5)이 안 걸렸다"
      return 0
    fi
    now=$(date +%s); age=$(((now - last) / 60))
    if [ "$age" -ge "$HEARTBEAT_MAX_MIN" ]; then
      raise_alert fast_dead 21600 "5분 감시가 ${age}분 동안 안 돌았다 — 크론이 사라졌거나 스크립트가 중간에 죽는다"
    else
      clear_alert fast_dead "5분 감시 정상 (${age}분 전)"
    fi
  fi
}

# ============================================================================
# --daily 전용
# ============================================================================

# 9) 인증서 만료 — 우리 것만 보지 않는다.
#    certbot 갱신이 3개 사이트에서 installer=nginx 라, 우리 nginx 설정이
#    나쁘면 **동거 서비스 갱신이 실패**한다. 그 실패는 그쪽 만료로만 드러난다.
#
#    ⛔ CR42-3 — 여기에 fail-open 이 남아 있었다. CR40-2 가 로그 검사 3종에서
#       막은 바로 그 형태다. `$LE_DIR` 밑에 `cert.pem` 이 하나도 없으면(경로 변경·
#       certbot 재설치·권한·openssl 부재) 루프를 한 번도 안 돌고 `worst=9999` 로
#       내려와 **`clear_alert cert` 를 불렀다.** 재현하면 이렇게 나간다:
#         ALERT-CLEARED cert :: 인증서 여유 회복 (최단  9999일)
#       이름은 빈칸이고 9999일은 존재하지 않는 값이며, 켜져 있던 경보를 지우고
#       "해소" 통보까지 보낸다. `blind_add` 도 없어 logblind 로도 안 걸렸다.
#       → 대상 수를 세고, **0개면 못 본 것이다**: 사유를 남기고 clear 는 하지 않는다.
check_cert() {
  local d name end epoch days worst=9999 worst_name="" line="" n=0 unreadable=0
  for d in "$LE_DIR"/*; do
    [ -f "$d/cert.pem" ] || continue
    name=$(basename "$d")
    n=$((n + 1))
    end=$(openssl x509 -enddate -noout -in "$d/cert.pem" 2>/dev/null | sed 's/notAfter=//')
    if [ -z "$end" ]; then
      # 파일은 있는데 만료일을 못 읽었다 — 이것도 "이상 없음"이 아니다.
      unreadable=$((unreadable + 1))
      line="$line ${name}=만료일못읽음"
      blind_add_daily "인증서 만료일을 못 읽음($d/cert.pem — openssl 없음/권한/형식)"
      continue
    fi
    # ⛔ CR43-4 — 예전에는 `$(date -d "$end" +%s || echo 0)` 로 **파싱 실패를 0 으로**
    #    흘려보냈다. 그러면 days 가 −20,000 대가 되고 그대로 worst 가 되어
    #    "인증서 만료 임박: … -20321일 남음" 오탐이 난다. 바로 위 `[ -z "$end" ]` 는
    #    "못 읽음"을 정확히 처리하는데 **파싱 실패만 값으로 흘러들던** 것이다.
    #    (오늘 `LC_ALL=C` 덕에 안 터진다 — 그건 이 코드가 옳다는 뜻이 아니다.)
    epoch=$(date -d "$end" +%s 2>/dev/null)
    case "$epoch" in
      ''|*[!0-9]*)
        unreadable=$((unreadable + 1))
        line="$line ${name}=만료일해석불가"
        blind_add_daily "인증서 만료일을 해석 못 함($d/cert.pem — date -d 가 openssl 출력을 못 읽는다)"
        continue
        ;;
    esac
    days=$(( (epoch - $(date +%s)) / 86400 ))
    line="$line ${name}=${days}일"
    if [ "$days" -lt "$worst" ]; then worst=$days; worst_name=$name; fi
  done

  if [ "$n" -eq 0 ]; then
    add "인증서  : 검사 못 함 (대상 0개 · $LE_DIR)"
    blind_add_daily "인증서 대상 0개($LE_DIR/*/cert.pem) — 경로 변경·certbot 재설치·권한을 의심"
    return 0                      # ⛔ clear_alert 금지: 못 본 것을 "해소"라고 통보하지 않는다
  fi

  add "인증서  : ${n}개 검사 ·$line (임계 ${CERT_MIN_DAYS}일)"

  if [ -z "$worst_name" ]; then
    # 대상은 있었는데 **하나도 못 읽었다**. 위에서 blind_add 는 이미 했다.
    return 0                      # ⛔ 여기서도 clear 하지 않는다
  fi
  if [ "$worst" -lt "$CERT_MIN_DAYS" ]; then
    raise_alert cert 86400 "인증서 만료 임박: $worst_name ${worst}일 남음. certbot 갱신이 반복 실패하는 상태다(nginx 설정 오류면 동거 서비스 갱신까지 막힌다). 확인: certbot renew --dry-run"
  elif [ "$unreadable" -eq 0 ]; then
    clear_alert cert "인증서 여유 회복 (${n}개 · 최단 $worst_name ${worst}일)"
  fi
  # 일부를 못 읽었으면 여유가 회복됐다고 말하지 않는다 — 못 읽은 그것이 임박했을 수 있다.
}

# 10) DB 구조 + 시장지수 신선도 — 하루 1회, DB 연결 1개만 쓴다.
#     연결 하나가 곧 백엔드 하나(메모리)라 fast 경로에서는 절대 하지 않는다.
#     · 016 이 만든 컬럼/제약이 있는가 → 없으면 지도·추천이 통째로 죽는다
#     · 시장지수 기준월이 밀렸는가 → 배치가 조용히 안 돈 것을 **결과로** 잡는다
#       (파일 mtime 이 아니라 DB 안의 값을 본다 — 돌았지만 값이 안 바뀐 경우도 잡힌다)
#
#     ⚠️ 신선도의 **1차 단언은 배치 자신(market-index.sh)** 이 진다. 배치는 자기가
#        만든 기준월을 그 자리에서 기대값과 대조해 어긋나면 알린다. 여기(감시)는
#        **그 뒤를 확인**하는 2차 방어다 — 배치가 아예 안 돌아서 아무 신호도 안
#        나는 경우를 잡는 자리다.
#
#     ⛔ CR42-1 / SR38-8 — **그 "2차 방어"가 1차와 같은 말을 매일 반복하고 있었다.**
#        CR41-2 로 배치와 감시가 같은 비교(`REF < expected`)를 하게 되면서,
#        `scope='sido'` 완결이 0인 달이 끼면 배치가 한 통 보내고 → 그 뒤 **감시가
#        하루 한 통씩 그 달 내내** 같은 사실을 다시 보냈다. 실측 전제(2025-07·08)로
#        14개월을 전수 계산하면 **61일 · 63통**이다. CR-040 이 차단한 옛 오탐이
#        연 35일이었으니 그보다 크다.
#        더 나쁜 것은 **같은 경보 키**다: 016 컬럼 누락·시장지수 0행이 `dbstruct` 를
#        함께 쓰므로, 사람이 그 키를 무시하게 되면 진짜 신호가 같이 묻힌다.
#        → 둘을 나눈다.
#          ① 기준월 항목을 `dbstruct` 에서 떼어 **별도 키 `marketstale`** 로 옮긴다.
#          ② **이번 달에 배치가 실제로 돌았으면** 감시는 말하지 않는다 — 그건 배치가
#             이미 한 말이다. 감시는 683행이 적은 원래 목적, 즉 **"배치가 아예 안 돌아
#             아무 신호도 없는 경우"** 만 운다.
#        ⚠️ 느슨해진 것이 아니다. 배치가 안 돌면 여전히 운다(아래 `_market_batch_ran`).
_market_batch_ran_this_month() {
  # 이번 달 배치가 실제로 돌았는가 — job-run.sh 가 남긴 기록을 읽는다.
  # 성공/실패는 따지지 않는다. **돌았으면 그쪽이 이미 사용자에게 말했다**는 것이 요점이다
  # (rc≠0 이면 job_market-index 로 즉시 한 통, rc=0+경고면 warn_market-index 로 한 통).
  local f start_at start_e month_start
  f="$JOBS/$MARKET_JOB_NAME.status"
  [ -f "$f" ] || return 1
  start_at=$(sed -n 's/^last_start_at=//p' "$f" | tail -1)
  [ -n "$start_at" ] || return 1
  start_e=$(date -d "$start_at" +%s 2>/dev/null) || return 1
  [ -n "$start_e" ] || return 1
  month_start=$(date -d "$(date +%Y-%m-01) 00:00" +%s 2>/dev/null) || return 1
  [ -n "$month_start" ] || return 1
  [ "$start_e" -ge "$month_start" ]
}

check_db_structure() {
  local user db out cols checks rows ref open expected stale=0 evaluated=0
  command -v docker >/dev/null 2>&1 || { add "DB구조  : docker 없음 — 건너뜀"; return; }
  user="$PG_USER"; db="$PG_DB"
  [ -n "$user" ] || user=$(_getvar POSTGRES_USER "$APP_ENV")
  [ -n "$db" ] || db=$(_getvar POSTGRES_DB "$APP_ENV")
  if [ -z "$user" ] || [ -z "$db" ]; then
    add "DB구조  : POSTGRES_USER/DB 를 못 읽음 ($APP_ENV) — 건너뜀"
    raise_alert dbstruct_cfg 86400 "DB 구조 검사를 할 수 없다: $APP_ENV 에서 POSTGRES_USER/POSTGRES_DB 를 못 읽었다"
    return
  fi
  clear_alert dbstruct_cfg "DB 구조 검사 설정 회복"

  out=$(docker exec "$PG_CONTAINER" psql -U "$user" -d "$db" -tA -F'|' -c "
SELECT
 (SELECT count(*) FROM information_schema.columns
   WHERE table_schema='public' AND table_name='listing'
     AND column_name IN ('created_by_user_id','as_of')),
 (SELECT count(*) FROM pg_constraint
   WHERE conrelid=to_regclass('public.listing') AND contype='c'
     AND conname LIKE 'listing_user_%'),
 (SELECT CASE WHEN to_regclass('public.market_price_index') IS NULL THEN -1
              ELSE (SELECT count(*) FROM market_price_index) END),
 (SELECT CASE WHEN to_regclass('public.market_price_index') IS NULL THEN 'n/a'
              ELSE coalesce((SELECT max(ym) FROM market_price_index
                              WHERE scope='sido' AND is_complete),'none') END),
 (SELECT CASE WHEN to_regclass('public.market_price_index') IS NULL THEN -1
              ELSE (SELECT count(*) FROM market_price_index
                     WHERE is_complete
                       AND ym >= to_char(now() - interval '30 days','YYYY-MM')) END)
" 2>&1 | tr -d ' ' | grep -E '^[0-9-]+\|' | head -1)

  if [ -z "$out" ]; then
    add "DB구조  : 조회 실패 (DB 가 응답하지 않는다)"
    raise_alert dbstruct 21600 "DB 구조 검사 조회가 실패했다 — $PG_CONTAINER 가 응답하지 않는다"
    return
  fi
  IFS='|' read -r cols checks rows ref open <<<"$out"

  # 기대 기준월은 **배치 주기(매월 1일 04:10)** 기준이다. 오늘 날짜로 재면
  # 배치가 정상인데도 달 중간에 기대값만 앞서 나가 헛운다(CR40-1 — 실제로 울었다).
  # 공식·근거는 monitor-lib.sh 의 market_expected_ym() 주석에 있다.
  expected=$(market_expected_ym)

  add "DB구조  : listing 신규컬럼 ${cols}/2 · CHECK ${checks}/7 · 시장지수 ${rows}행 · 기준월 ${ref}(기대 ${expected}) · 진행중인달완결 ${open}(기대 0)"

  # --- ① 구조 이상 (dbstruct) — 시장지수 신선도는 여기 섞지 않는다 -----------
  local prob=""
  [ "${cols:-0}" = 2 ] || prob="$prob listing 신규컬럼 ${cols}/2(016 미적용 → 지도·추천 전멸);"
  [ "${checks:-0}" = 7 ] || prob="$prob listing CHECK ${checks}/7;"
  [ "${rows:-0}" -gt 0 ] 2>/dev/null || prob="$prob 시장지수 ${rows}행(적정가 밴드 보정 없이 동작);"
  [ "${open:-1}" = 0 ] || prob="$prob 진행중인 달을 완결로 표시 ${open}건(CR33-1 재발);"
  if [ -n "$prob" ]; then
    raise_alert dbstruct 86400 "DB 상태 이상 —$prob"
  else
    clear_alert dbstruct "DB 구조 정상 (컬럼 2/2 · CHECK 7/7 · 시장지수 ${rows}행)"
  fi

  # --- ② 기준월 신선도 (marketstale) — 별도 키 · 배치가 말했으면 침묵 ---------
  #     판정 본체는 바로 아래 `check_market_stale()` 이다.
  #
  #     ⛔ CR43-2 — **왜 함수로 뺐나.** 이 구획은 `docker`+`psql` 이 있어야만 도달하므로
  #        자체검사가 문자열로만 볼 수 있었고, 그 사이에 억제의 **극성**과 **쿨다운**이
  #        관문에서 자유로웠다. 리뷰어가 심은 변이 2종이 통과 139·실패 0 으로 생존했다:
  #          M1 `if _market_batch_ran_this_month` 극성 반전
  #             → 배치가 **아예 안 돈 달에 완전 침묵**(크론이 사라져도 아무 신호가 없다).
  #               그건 CR-042 가 PASS 조건 #1 로 지키라고 한 바로 그것이다.
  #          M2 쿨다운 604800 → 31536000(1년)
  #             → 진짜 미실행 183일에 27통이 **1통**. 관문은 `발송 1통` 을 화면에
  #               출력하면서 PASS 라고 적었다(상한 단언이 없었다).
  #        이 프로젝트가 다섯 라운드째 붙잡아 온 문장이 *"검사가 닿은 곳은 튼튼하고
  #        안 닿은 곳은 예외 없이 뚫린다"* 이고, 여기는 **한 번도 실행된 적이 없는 코드**
  #        였다. → 판정을 인자만 받는 함수로 떼어, selftest 가 `ext` 로 뽑아 `raise_alert`·
  #        `_market_batch_ran_this_month` 를 가짜로 물리고 **행동으로** 통수를 센다.
  #        (그 함수는 `docker` 도 `psql` 도 필요 없다 — 못 도는 검사는 없는 검사다.)
  check_market_stale "$ref" "$expected"
}

# 10b) 기준월 신선도 판정 — 위 ② 의 본체.
#      $1 = DB 에 있는 완결 기준월(ref · 'n/a'/'none' 가능)   $2 = 기대 기준월(expected)
#      부르는 쪽이 주는 값 두 개 말고는 아무것도 안 읽는다. DB 도 docker 도 안 쓴다.
check_market_stale() {
  local ref="$1" expected="$2" stale=0 evaluated=0
  if [ -z "$expected" ]; then
    # 기대값을 못 만들었으면 비교를 건너뛴다 — 빈 문자열과 비교하면 무조건 참이 되어
    # "밀렸다"고 헛운다. 못 잰 것은 못 잰 것이고, 그래서 clear 도 하지 않는다.
    add "시장지수: 기대 기준월을 계산하지 못했다(date -d 확인) — 판정 못 함"
    blind_add_daily "시장지수 기대 기준월 계산 실패(date -d)"
    return 0
  fi
  if [ -z "$ref" ] || [ "$ref" = n/a ] || [ "$ref" = none ]; then
    # 표가 없거나 완결 행이 하나도 없다 → 위 ①의 `시장지수 N행` 이 이미 말한다.
    # 여기서 다시 비교할 근거가 없으므로 판정하지 않고, clear 도 하지 않는다.
    add "시장지수: 완결 기준월이 없다(${ref}) — 기준월 판정 못 함"
    return 0
  fi
  evaluated=1
  if [[ "$ref" < "$expected" ]]; then stale=1; fi

  if [ "$stale" = 0 ]; then
    add "시장지수: 기준월 ${ref} (기대 ${expected}) — 정상"
    [ "$evaluated" = 1 ] && clear_alert marketstale "시장지수 기준월 회복 (${ref} ≥ 기대 ${expected})"
    return 0
  fi
  if _market_batch_ran_this_month; then
    # 배치가 이번 달에 돌았다 = 이 사실은 **배치가 이미 알렸다**(실패 1통 또는 경고 1통).
    # 같은 사실을 매일 다시 보내면 사람은 이 경보 키를 끄게 되고, 그러면 016 컬럼
    # 누락 같은 진짜 신호가 같이 묻힌다. 요약에는 남기고 발송만 하지 않는다.
    add "시장지수: 기준월 ${ref} < 기대 ${expected} — 이번 달 배치는 돌았다(그쪽이 이미 알렸다). 여기서는 다시 보내지 않는다"
  else
    add "시장지수: 기준월 ${ref} < 기대 ${expected} · 이번 달 배치 기록 없음"
    raise_alert marketstale 604800 "시장지수 기준월이 ${ref} 로 기대 ${expected} 보다 이전인데, **이번 달 배치가 돌았다는 기록이 없다** — 매월 1일 04:10 크론이 사라졌거나 job-run.sh 가 기록을 못 남기고 있다(배치가 스스로 실패를 알렸다면 이 경보는 안 뜬다). 확인: crontab -l | grep market-index · ls -l $JOBS/$MARKET_JOB_NAME.status · tail $MARKET_INDEX_LOG"
  fi
  return 0
}

# 11) 크래시 복구 흔적 (하루 1회, 사람이 읽는 요약용 + oom 보강)
#     호스트 OOM killer 나 다른 원인으로 죽어도 여기 남는다.
check_pgcrash() {
  local n
  command -v docker >/dev/null 2>&1 || return 0
  n=$(docker logs --since 24h "$PG_CONTAINER" 2>&1 | grep -cE 'terminated by signal|all server processes terminated' )
  n=${n:-0}
  add "DB복구  : 최근 24시간 크래시 복구 흔적 ${n}줄 (기대 0)"
  if [ "$n" -gt 0 ]; then
    raise_alert pgcrash 86400 "$PG_CONTAINER 로그에 최근 24시간 크래시 복구 흔적 ${n}줄. docker ps 는 여전히 healthy 로 보인다 — 속지 말 것"
  else
    clear_alert pgcrash "최근 24시간 DB 크래시 복구 흔적 없음"
  fi
}

# 12) 컨테이너 json 로그 크기 — daemon.json 이 없어 회전 설정이 없다(실측).
#     디스크 92% 에서 이게 커지면 디스크 경보가 먼저 울지만, 원인을 알려면 필요하다.
check_jsonlog() {
  local name id f mb line="" bad=""
  command -v docker >/dev/null 2>&1 || return 0
  for name in $CONTAINERS; do
    id=$(kv_get "cid_$name"); [ -n "$id" ] || id=$(docker inspect -f '{{.Id}}' "$name" 2>/dev/null)
    [ -n "$id" ] || continue
    f="/var/lib/docker/containers/$id/$id-json.log"
    [ -f "$f" ] || continue
    mb=$(( $(stat -c %s "$f" 2>/dev/null || echo 0) / 1048576 ))
    line="$line ${name}=${mb}MiB"
    [ "$mb" -ge "$JSONLOG_MAX_MB" ] && bad="$bad ${name}=${mb}MiB"
  done
  add "컨테로그:$line (임계 ${JSONLOG_MAX_MB}MiB · 회전 설정 없음)"
  if [ -n "$bad" ]; then
    raise_alert jsonlog 86400 "컨테이너 json 로그가 크다 —$bad. /etc/docker/daemon.json 에 log-opts(max-size) 가 없다"
  else
    clear_alert jsonlog "컨테이너 json 로그 크기 정상"
  fi
}

# 13) 배치 상태 요약 (job-run.sh 가 남긴 기록. 즉시 경보는 job-run.sh 가 한다)
check_jobs() {
  local f name rc succ dur
  local any=0
  for f in "$JOBS"/*.status; do
    [ -e "$f" ] || continue
    any=1
    name=$(basename "$f" .status)
    rc=$(sed -n 's/^last_rc=//p' "$f" | tail -1)
    dur=$(sed -n 's/^last_duration_sec=//p' "$f" | tail -1)
    succ=$(sed -n 's/^last_success_at=//p' "$f" | tail -1)
    add "배치    : $name 종료코드=${rc:-?} ${dur:-?}초 · 마지막성공=${succ:-없음}"
  done
  [ "$any" = 1 ] || add "배치    : 아직 기록 없음 (월 1회 배치라 매월 1일 04:10 이 첫 기록이다 — 경보 아님)"
}

# ============================================================================
# 실행
# ============================================================================
case "$MODE" in
  test)
    printf '자격증명 탐색: '
    if alert_creds; then echo "$CRED_SRC"; else echo "없음"; fi
    send_telegram "[realestate] 감시 채널 시험 — $(hostname) $(date '+%F %T'). 이 메시지가 보이면 경보 경로가 살아 있다."
    exit $?
    ;;
  fast)
    check_web
    check_frontend
    check_oom
    check_dbmem
    check_disk
    check_logperm
    check_logleak
    check_logfresh
    check_api5xx
    check_sshlogin
    check_logblind        # ← 위 로그 검사들이 남긴 "검사 못 함"을 한 통으로
    check_peer_alive
    kv_set last_fast_run "$(date +%s)"        # ← 모든 검사를 통과한 뒤에만 찍는다
    log "fast 완료 :: $(printf '%s' "$DIGEST" | tr '\n' '|')"
    log_trim
    [ "${RE_MON_PRINT:-0}" = 1 ] && printf '%s' "$DIGEST"
    ;;
  daily)
    check_web
    check_frontend
    check_oom
    check_dbmem
    check_disk
    check_logperm
    check_logleak
    check_logfresh
    check_api5xx
    check_sshlogin
    # ⚠️ check_cert 도 blind_add 를 한다(CR42-3). 그러므로 **check_logblind 보다 앞**이어야
    #    한다 — 뒤에 두면 "인증서 대상 0개" 사유가 아무 데도 안 실려 조용히 사라진다.
    #    (fast 경로에는 check_cert 가 없으므로 그쪽 순서는 그대로다)
    check_cert
    check_db_structure
    # ⚠️ check_logblind 는 **blind_add 를 부르는 모든 검사보다 뒤**여야 한다.
    #    앞에 두면 뒤쪽 검사의 "못 봤다" 사유가 아무 데도 안 실리고 조용히 사라진다.
    #    (check_cert 를 옮기면서 이 자리를 한 번 틀렸다 — 그래서 selftest T4 가
    #     이제 fast·daily 두 경로의 **호출 순서 자체**를 검사한다.)
    check_logblind
    check_pgcrash
    check_jsonlog
    check_jobs
    check_peer_alive

    runs=$(kv_get fast_runs_today); runs=${runs:-0}
    aa=$(active_alerts); n_active=${aa%%|*}; names=${aa#*|}
    swap_h=$(free -m 2>/dev/null | awk '/Swap:/{print $3"/"$2"MiB"}')
    mem_h=$(free -m 2>/dev/null | awk '/Mem:/{print "사용 "$3"MiB · 여유(available) "$7"MiB"}')
    add "호스트  : 메모리 $mem_h · 스왑 $swap_h"
    add "감시    : 지난 24시간 fast 실행 ${runs}회 (기대 288) · 미해소 경보 ${n_active}건${names:+ ($names)}"
    kv_set fast_runs_today 0
    kv_set last_daily_run "$(date +%s)"

    head="[realestate] 일일 점검 $(date '+%F %H:%M') · $(hostname)"
    if [ "$n_active" = 0 ]; then head="$head — 이상 없음"; else head="$head — 미해소 ${n_active}건"; fi
    send_telegram "$head
$DIGEST
※ 이 메시지가 아침에 오지 않으면 감시나 서버가 멈춘 것이다."
    log "daily 완료 :: $(printf '%s' "$DIGEST" | tr '\n' '|')"
    log_trim
    [ "${RE_MON_PRINT:-0}" = 1 ] && printf '%s' "$DIGEST"
    ;;
esac

# fast 실행 횟수 누적 (일일 요약에서 "어제 몇 번 돌았나"를 말하기 위해)
if [ "$MODE" = fast ]; then
  r=$(kv_get fast_runs_today); r=${r:-0}
  kv_set fast_runs_today $((r + 1))
fi
exit 0
