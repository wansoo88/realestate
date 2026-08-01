#!/usr/bin/env bash
# 시장지수 배치 — 적정가 밴드의 시점 보정용 (DEPLOY.md §5-3c)
#
# 매달 1일에 돈다. 그 시점이면 **직전 달**이 완결이다:
#   완결 조건 = 그 달이 끝나고 신고 지연 30일까지 지났는가 (부동산거래신고법 제3조)
#   예) 8/1 실행 → 7/2 가 열린 달 → 완결은 6월까지 → 기준월 2026-06
# 말일에 돌리면 직전 달이 아직 안 열려 한 달 뒤처진다. 그래서 1일이다.
#
# ⛔ 조용한 실패가 최악이다. 이 스크립트는
#    ① 실패하면 0 이 아닌 코드로 끝나고
#    ② 성공해도 **결과를 검증**해서 이상하면 실패로 만든다.
#    로그만 남기고 0 으로 끝나면 몇 달 뒤 낡은 값을 보고도 아무도 모른다.
#
# ⛔ CR42-1 / SR38-8 — **그러나 "실패"와 "조치할 것 없음"을 같은 말로 보내면 안 된다.**
#    기준월이 안 오르는 사유는 둘이고, 둘은 **전혀 다른 대응**을 부른다:
#      · `행없음`     — 그 달 원본 거래가 안 들어왔다(수집·신고 문제). → **진짜 사건 · rc=1**
#      · `(미완결)` — 표본 부족(계절적 거래량 감소). 적재는 전부 됐고 배치는 정상이다.
#        그 달은 `_complete_flags` 의 건수 검사가 계절성을 수집 누락과 구분 못해
#        생기는 **거짓 미완결**이고, 도메인 코드가 스스로 그렇게 적어 둔다
#        (`timeadjust.py` `_complete_flags` docstring — *"보수적인 쪽의 오류이고
#        그 달들이 기준월이 될 일은 없다"*). → **경고 · rc=0**
#    rc=1 로 둘을 묶으면 사용자가 받는 문장은 *"배치 실패"* 인데, 그건 사실과
#    어긋나고(51초에 전 행 적재했다) `last_success_at` 이 한 달 굳으며,
#    무엇보다 **조치할 것이 없는 경보**다. 그런 경보가 통로를 선점하면
#    같은 채팅으로 오는 `sshpw`·`authshrink` 까지 같은 손짓으로 넘기게 된다.
#    ⚠ 느슨해지는 것이 아니다 — `행없음`·`조회실패`·설명 불가는 전부 rc=1 이다.
#      경고도 조용히 넘어가지 않는다: `경고:` 줄을 job-run.sh 가 집어
#      **별도 경보 키(`warn_<이름>`)** 로 한 통 보낸다(월 1통).
#
# ⛔ 그리고 **기준월 신선도의 1차 단언은 여기(배치 자신)** 가 진다(CR40-1).
#    감시(monitor.sh --daily)는 그 뒤를 확인하는 2차 방어다. 배치가 자기 결과를
#    단언하지 않고 감시만 보게 두면, 감시는 배치 주기를 모른 채 날마다 재게 되고
#    그게 오탐이 된다 — 실제로 2026-07-31 에 그렇게 한 통 헛울었다.
set -euo pipefail

APP_ROOT=/opt/realestate
LOG_TAG="[market-index]"

log() { echo "$(date '+%F %T') $LOG_TAG $*"; }
fail() { log "실패: $*"; exit 1; }
# 경고 — 배치는 성공이지만 사람이 알아야 할 것이 있다. rc 를 바꾸지 않는다.
#   job-run.sh 가 `경고:` 로 시작하는 줄을 집어 `warn_<이름>` 키로 알린다.
#   (`실패:` 와 같은 경로이고, 같은 scrub() 을 통과한다)
warn() { log "경고: $*"; }

# --- 기대 기준월 -------------------------------------------------------------
# ⚠️ monitor-lib.sh 의 market_expected_ym() 과 **같은 함수**다(주석까지 같은 규칙).
#    거기를 source 하지 않는 이유: 이 스크립트는 `set -e` 아래에서 돌고,
#    monitor-lib.sh 는 로드 시점에 mkdir/chmod 를 한다 — 그게 실패하면 배치가
#    통째로 죽는다. 배치를 남의 파일의 부작용에 묶지 않는다.
#    두 사본이 갈라지지 않는지는 `deploy/monitor-selftest.sh` 가 대조한다.
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

# 이번 달 **배치 주기 시각**(1일 MARKET_BATCH_READY)의 epoch.
market_batch_epoch() {
  local now
  now="${1:-$(date +%s)}"
  date -d "$(date -d "@$now" +%Y-%m-01 2>/dev/null) $MARKET_BATCH_READY" +%s 2>/dev/null
}

# 이 배치가 만들어야 할 기대 기준월.
#
# ⛔ CR41-2 — 여기서 market_expected_ym 을 **인자 없이(=지금 시각)** 부르면 안 된다.
#    배치가 도는 시각은 **1일 04:10** 인데 유예값 MARKET_BATCH_READY 는 06:00 이다.
#    그래서 인자 없이 부르면 market_expected_ym 의 "이번 달 배치 시각이 아직 안 왔다"
#    분기에 걸려 기준이 **지난달로 롤백**되고, 기대월이 자기 REF 보다 한 달 뒤처진다
#    (실측: 14개월 중 13개월). 그러면 아래 `REF < EXPECTED` 단언이 그냥 통과해
#    **"돌긴 돌았는데 완결월이 안 올라간" 실패가 rc=0 으로 나가고**, job-run.sh 는
#    성공으로 기록한다. 5시간 뒤 감시가 내보내는 "배치가 안 돌았거나 실패했다" 문구도
#    그때는 거짓이다(배치는 돌았고 성공을 보고했다).
#    → 기준 시각을 **배치 주기 시각(그 달 1일 MARKET_BATCH_READY)** 으로 고정한다.
#      월중에 손으로 돌려도 기준이 그 달 1일이라 기대값이 DB 보다 앞서지 않는다
#      (앞선 쪽은 위의 OPEN 검사가 잡는다 — 여기서는 일부러 단언하지 않는다).
#
# 인자로 기준 시각(epoch)을 받는다 — `deploy/monitor-selftest.sh` T3b 가 이 함수를
# **그대로 뽑아 eval 해서** 여러 달로 돌리고, 그 달 배치가 실제로 만드는 기준월과 대조한다.
batch_expected_ym() {
  local at
  at=$(market_batch_epoch "${1:-}") || return 1
  [ -n "$at" ] || return 1
  market_expected_ym "$at"
}

cd "$APP_ROOT/backend" || fail "backend 디렉터리 없음"

# .env 를 그대로 읽는다. 비밀을 이 파일에 적지 않는다.
set -a
# shellcheck disable=SC1091
source "$APP_ROOT/.env" || fail ".env 읽기 실패"
set +a

: "${POSTGRES_USER:?POSTGRES_USER 없음}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD 없음}"
: "${POSTGRES_DB:?POSTGRES_DB 없음}"

# ⚠️ `.env` 의 POSTGRES_HOST 는 **도커 서비스명**이다(컨테이너 안에서만 풀린다).
#    이 스크립트는 호스트 venv 에서 도므로 컨테이너 IP 를 써야 한다.
#    **매 실행마다 조회한다** — 컨테이너를 재생성하면 IP 가 바뀌므로 박아두면
#    어느 배포 뒤에 조용히 죽는다(그 조용함이 이 스크립트가 막으려는 것이다).
DB_HOST=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' realestate-db 2>/dev/null || true)
[ -n "$DB_HOST" ] || fail "realestate-db 컨테이너 IP 를 못 찾음 (컨테이너가 떠 있는가?)"
DB_PORT=5432

export DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${DB_HOST}:${DB_PORT}/${POSTGRES_DB}"

# shellcheck disable=SC1091
source .venv/bin/activate || fail "venv 활성화 실패"

log "배치 시작 (기대 소요 ~50초)"
START=$(date +%s)
python scripts/build_market_index.py || fail "build_market_index.py 가 0 이 아닌 코드로 끝남"
log "배치 끝 ($(( $(date +%s) - START ))초)"

# --- 검증: 돌았다고 끝이 아니다 -------------------------------------------
# psql 은 컨테이너 안에서 돈다(호스트에 psql 이 없어도 된다).
q() { docker exec -i realestate-db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -c "$1"; }

ROWS=$(q "SELECT count(*) FROM market_price_index;")
[ "${ROWS:-0}" -gt 0 ] || fail "적재 0행"

# ⛔ CR33-1: 진행 중인 달을 완결로 표시하면 안 된다.
#    며칠 뒤 새 정보 없이 밴드가 바뀌는 상태가 된다.
OPEN=$(q "SELECT count(*) FROM market_price_index
           WHERE is_complete AND ym >= to_char(now() - interval '30 days', 'YYYY-MM');")
[ "${OPEN:-1}" -eq 0 ] || fail "진행 중인 달을 완결로 표시한 행 ${OPEN}건 (CR33-1 재발)"

REF=$(q "SELECT max(ym) FROM market_price_index WHERE scope='sido' AND is_complete;")

# ⛔ CR40-1: 신선도 1차 단언. 여기서 단언하지 않으면 "돌았지만 기준월이 안 올라간"
#    상태가 아무 신호 없이 지나가고, 감시만 남는다.
#    · 기대보다 **이전**이면 실패다(원본이 모자라거나 완결 규칙이 어긋났다).
#    · 기대보다 **이후**는 여기서 판정하지 않는다 — 위의 OPEN 검사가 이미 잡고,
#      손으로 월중에 돌리면 정상적으로 앞설 수 있다(그때 죽으면 그게 오탐이다).
#    · 기준 시각은 **지금**이 아니라 **이번 달 배치 주기 시각**이다(CR41-2 — 위 주석).
EXPECTED=$(batch_expected_ym) || true
[ -n "$EXPECTED" ] || fail "기대 기준월을 계산하지 못했다 (date -d 가 없거나 동작하지 않는다)"
[ -n "$REF" ] || fail "완결 기준월(sido)이 하나도 없다 — 기대 ${EXPECTED}"
STALE=0
if [[ "$REF" < "$EXPECTED" ]]; then
  # 사유를 **구분해서** 말하고, 거기서 끝내지 않고 **등급까지 나눈다**(CR42-1 / SR38-8).
  #   · 행이 아예 없다  → 그 달 원본 거래가 안 들어왔다(수집/신고 문제) → **rc=1**
  #   · 행은 있는데 미완결 → 표본 부족이다. `_complete_flags` 의 건수 검사가 계절적
  #     거래량 감소를 수집 누락과 구분하지 못한다(서버 실측: 2025-07·2025-08·2026-07 은
  #     시도 3곳이 **전부** 미완결이었다) → **rc=0 · 경고**
  #   · 그 밖에 설명되지 않는 모양 → **rc=1**(보수적으로). 모르는 것을 경고로 내리지 않는다.
  # 어느 쪽이든 **완결월이 안 올라간 것은 사실**이므로 조용히 넘기지 않는다.
  DIAG=$(q "SELECT coalesce(string_agg(region_code || ':' || sample_size ||
              CASE WHEN is_complete THEN '(완결)' ELSE '(미완결)' END, ' '), '행없음')
            FROM market_price_index WHERE scope='sido' AND ym='${EXPECTED}';" 2>/dev/null || true)
  DIAG=${DIAG:-조회실패}
  case "$DIAG" in
    *'(완결)'*)
      # 완결 행이 있는데 max(ym) 이 그보다 작다 — 설명할 수 없는 상태다.
      fail "기준월(sido) ${REF} 가 기대 ${EXPECTED} 보다 이전인데 ${EXPECTED} 에 완결 행이 있다 — 설명할 수 없는 상태다(max(ym) 계산과 완결 플래그가 어긋난다). ${EXPECTED} 시도 상태: ${DIAG}"
      ;;
    *'(미완결)'*)
      # ⬇ 등급을 내리는 자리. **숨기는 게 아니라 이름을 바로 붙이는 것이다.**
      STALE=1
      warn "기준월(sido) 가 ${REF} 에서 멈췄다(기대 ${EXPECTED}) — 배치는 정상이고 적재도 끝났다. ${EXPECTED} 은 표본이 모자라 완결로 안 바뀌었다(계절적 거래량 감소). 시도 상태: ${DIAG}. 적정가 밴드의 시점 보정이 그만큼 낡았다 — 다만 **지금 손으로 할 수 있는 조치는 없다**(근본은 _complete_flags 의 계절보정)"
      ;;
    *)
      fail "기준월(sido) ${REF} 가 기대 ${EXPECTED} 보다 이전이다 — ${EXPECTED} 시도 상태: ${DIAG}. '행없음'은 그 달 원본 거래가 통째로 안 들어왔다는 뜻이다(수집·신고 문제 — 진짜 사건)"
      ;;
  esac
fi

if [ "$STALE" = 1 ]; then
  log "적재 ${ROWS}행 · 기준월(sido) ${REF}(기대 ${EXPECTED} · 표본부족으로 정체) · 진행중인달 완결 0건"
  log "완료(경고 동반 · 종료코드 0)"
else
  log "적재 ${ROWS}행 · 기준월(sido) ${REF}(기대 ${EXPECTED}) · 진행중인달 완결 0건"
  log "완료"
fi
