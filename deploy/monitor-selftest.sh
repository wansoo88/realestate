#!/usr/bin/env bash
# ============================================================================
# monitor-selftest.sh — 감시 스크립트 자체의 회귀 검사 (CR40-3)
#
# 왜 있나
#   `deploy/` 의 셸 4종은 **root 로 5분마다** 도는데 자동 검사가 하나도 없었다.
#   이 저장소는 `DEPLOY.md` 산문과 nginx 설정까지 테스트로 묶어 두면서, 정작
#   가장 권한이 큰 코드를 손 검증에만 맡기고 있었다. CR40-1·CR40-2 는 그래서
#   조용히 들어왔고, 고쳐도 같은 방식으로 되돌아올 수 있다.
#   이 파일은 **이번에 고친 자리**를 붙잡는다. 전부 덮지 않는다 — 덮는 척하지 않는다.
#
# 안전
#   · 네트워크로 아무것도 안 보낸다(RE_MON_DRY_RUN=1) · 운영 상태를 안 건드린다
#     (RE_MON_STATE/LOG 를 임시 디렉터리로 격리) · docker/psql 을 안 부른다.
#   · 웹 검사는 127.0.0.1:9(닫힌 포트)로 돌린다 → 즉시 실패하고, 그 경보는 무시한다.
#   · 실행해도 사용자 텔레그램으로 가는 것은 **0통**이다.
#
# 사용:  bash deploy/monitor-selftest.sh        (저장소에서든 서버에서든 그대로)
# 종료코드: 0 = 전부 통과, 1 = 하나라도 실패
# ============================================================================
set -uo pipefail
# ⚠️ 검사 자신도 바이트 단위로 맞춘다. 이유는 monitor.sh 머리말과 같다(CR41-5):
#    정상 UTF-8 줄이면 UTF-8 로케일에서도 `grep 'ALERT logperm.*644'` 는 사이의
#    한글을 넘어 **매치한다**. 깨지는 것은 **유효하지 않은 바이트가 섞인 줄**이고,
#    이 검사는 감시가 만든 로그를 그대로 읽으므로 그런 줄이 섞일 수 있다.
#    검사 결과가 로케일에 따라 달라지면 "잘 잡는 코드를 못 잡는다"고 보고하게 된다.
export LC_ALL=C

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)
TMPROOT=$(mktemp -d "${TMPDIR:-/tmp}/mon-selftest.XXXXXX") || exit 3
# 디스크 92% 서버다 — `timeout`/Ctrl-C 로 죽어도 임시본을 남기지 않는다(SR37-4).
trap 'rm -rf "$TMPROOT"' EXIT INT TERM HUP

PASS=0; FAIL=0; SKIP=0; HARN=0
ok()   { PASS=$((PASS + 1)); printf '  \033[32mPASS\033[0m %s\n' "$1"; }
ng()   { FAIL=$((FAIL + 1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; [ $# -gt 1 ] && printf '        %s\n' "$2"; return 0; }
skip() { SKIP=$((SKIP + 1)); printf '  \033[33mSKIP\033[0m %s\n' "$1"; }
sect() { printf '\n== %s\n' "$1"; }
# ⛔ CR41-6 — 자체검사가 **연속·동시 실행에서 간헐적으로 거짓 FAIL** 을 냈다.
#    실측(서버): 순차 30회·8회는 전부 정상, **4개 동시 실행에서는 24회 중 1회** 붉었다.
#    붉은 것은 언제나 `printf '%s' "$OUT" | grep -q ...` 로 **캡처한 출력**을 보는 검사였고,
#    같은 시나리오의 **파일(`$S.log`) grep 검사는 한 번도 붉지 않았다.**
#    감시 본체는 결백하다 — 같은 시나리오를 직접 200회 돌려 출력 결손 **0**을 확인했다.
#    즉 결함은 **하네스의 파이프라인**에 있다: 이 파일은 `set -o pipefail` 아래서 돌고,
#    파이프라인의 상태는 "안 맞았다" 말고도 (읽는 쪽이 먼저 끝나 쓰는 쪽이 SIGPIPE 로 죽거나
#    부하로 fork 가 실패해) 0 이 아닐 수 있다. 그러면 **없는 결함을 보고**하고,
#    부정형 검사(`if ... then ng`)에서는 반대로 **있는 결함을 놓친다** — 이쪽이 더 나쁘다.
#    → 캡처한 문자열 검사는 **fork 도 파이프도 없는 셸 내장 `case`** 로 바꾼다.
#    ⚠️ 오탐이 결함이라는 이 프로젝트의 기준은 **관문 자신에게도** 적용된다.
has()  { case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac; }

# ⛔ SR38-9 — CR41-6 이 고친 결함이 **모양만 바꿔 남아 있었다.**
#    CR41-6 은 *"파일을 보는 검사는 `grep -q 패턴 파일` 한 프로세스뿐이라 그대로 둔다"*
#    고 판단했는데, 재현된 붉은 자리가 바로 그 파일 검사였다 — 파이프라인이 아니라
#    **파일이 애초에 안 만들어져서**다(공용 `%TEMP%` 96% 사용). 그러면:
#      · 긍정형(`if grep -q ALERT; then ok`)  → 파일 없음 → ng = **없는 결함을 보고**
#      · 부정형(`if grep -q ALERT; then ng`)  → 파일 없음 → 조용히 ok = **있는 결함을 놓침**
#    두 번째가 더 나쁘다. 실측이 그것을 증명했다: 같은 파일을 2회 돌렸을 때
#    80/1/2 · 78/3/2 로 갈렸고, **검사 로직이 잡은 실패는 0건**이었다.
#    → 그래서 로그 파일을 보는 검사는 **전부 아래 두 함수만** 쓴다. 파일이 비었거나
#      없으면 `ok` 도 `ng` 도 아닌 **HARN**(하네스 오류)으로 보고하고, 마지막 요약이
#      그것을 **검사 실패와 분리해서** 말한다. 관문의 초록/빨강을 근거로 쓰려면
#      HARN 이 0 이어야 한다.
harn() { HARN=$((HARN + 1)); printf '  \033[35mHARN\033[0m %s\n' "$1"
         printf '        %s\n' "$2"; return 0; }
# want <로그파일> <패턴> <설명> [실패설명] [부가정보]  — 패턴이 **있어야** 통과
want() {
  if [ ! -s "$1" ]; then
    harn "$3" "감시 로그 $1 가 비었거나 없다 — **검사 결과가 아니다**(하네스·환경 문제: 임시파일 생성 실패)"
    return 0
  fi
  if grep -aq "$2" "$1"; then ok "$3"; else ng "${4:-$3}" "${5:-}"; fi
}
# avoid <로그파일> <패턴> <설명> [실패설명] [부가정보] — 패턴이 **없어야** 통과
avoid() {
  if [ ! -s "$1" ]; then
    harn "$3" "감시 로그 $1 가 비었거나 없다 — **검사 결과가 아니다**(하네스·환경 문제: 임시파일 생성 실패)"
    return 0
  fi
  if grep -aq "$2" "$1"; then ng "${4:-$3}" "${5:-}"; else ok "$3"; fi
}
# 복합 조건을 쓰는 자리에서 먼저 부르는 관문. rc 0 이면 검사를 진행해도 된다.
live() {
  [ -s "$1" ] && return 0
  harn "$2" "감시 로그 $1 가 비었거나 없다 — **검사 결과가 아니다**(하네스·환경 문제)"
  return 1
}
# ⛔ CR43-3 — **`want`/`avoid`/`live` 는 로그 파일을 읽는 검사만 덮었다.**
#    포크를 가장 많이 쓰는 것은 **날짜 루프**(T2·T3b·T10)인데 그쪽은 무방비였고,
#    거기서 `date` 가 죽으면 값이 **빈 문자열**이 된다. 그러면
#      · `[[ "$ref" < "$exp" ]]` 는 **무조건 참** → 없는 결함을 보고(T3b `:287`)
#      · `[ "$ref" != "$exp" ]` 도 참 → 같은 방향
#      · 반대로 어떤 자리는 조용히 통과 → **있는 결함을 놓친다**(이쪽이 더 나쁘다)
#    이건 `monitor.sh` 가 *"빈 문자열과 비교하면 무조건 참이 되어 헛운다"* 며
#    **스스로 금지한 형태**다(check_market_stale 의 `[ -z "$expected" ]` 분기).
#    실측: 같은 파일 3회 동시 실행에서 139/0/2 · 139/0/2 · **138/1/2** 로 갈렸고
#    붉은 것은 T3b, 원인은 `fork: retry: Resource temporarily unavailable`,
#    그런데 **HARN 은 0** 이었다 — HARN 을 만든 이유가 정확히 그것인데도.
#    → 값이 비면 `ok` 도 `ng` 도 아니라 **하네스 오류**로 센다.
nz() { local v; for v in "$@"; do [ -n "$v" ] || return 1; done; return 0; }
# 루프가 끝난 뒤 한 번만 보고한다(하루치마다 HARN 을 찍으면 화면이 무의미해진다)
harn_if() { # $1=건수 $2=이름 $3=설명
  [ "${1:-0}" -gt 0 ] || return 0
  harn "$2" "$3 — 날짜 계산이 ${1}회 빈 값을 냈다. **검사 결과가 아니다**(fork 실패 등 하네스·환경 문제)"
}

# ============================================================================
sect "T1. 문법 — bash -n (4파일)"
for f in monitor.sh monitor-lib.sh job-run.sh market-index.sh monitor-selftest.sh; do
  if bash -n "$HERE/$f" 2>/dev/null; then ok "bash -n $f"; else ng "bash -n $f"; fi
done

# ============================================================================
if grep -q '^export LC_ALL=C' "$HERE/monitor.sh"; then
  ok "monitor.sh 가 로케일을 고정한다 (크론과 손 실행이 같게 동작한다)"
else
  ng "monitor.sh 가 로케일을 안 고정한다 — 같은 코드가 환경에 따라 다른 결과를 낸다"
fi
if grep -q 'LC_ALL=C sed -E' "$HERE/monitor-lib.sh"; then
  ok "scrub 이 바이트 단위로 돌고, 그것을 export 하지 않는다 (배치 인코딩 보존)"
else
  ng "scrub 의 로케일이 고정되지 않았다"
fi

# 감시 라이브러리를 격리해서 읽어 온다 (market_expected_ym · scrub 을 쓰기 위해)
export RE_MON_STATE="$TMPROOT/state-lib" RE_MON_LOG="$TMPROOT/lib.log"
# shellcheck source=./monitor-lib.sh
. "$HERE/monitor-lib.sh" || { echo "monitor-lib.sh 를 못 읽음"; exit 3; }

# ============================================================================
sect "T2. 시장지수 기대월 — 한 해를 돌려 오탐 0 인가 (CR40-1)"

# 배치가 시각 t 에 돌면 DB 에 남길 최신 완결월. **파이썬 규칙을 그대로 옮긴다**
#   app/domain/valuation/timeadjust.py:244  latest_open_ym(as_of) = ym_of(as_of - 30일)
#   완결 후보 = 그보다 **작은** 달
# ⚠️ 이걸 "그 달 말일 + 30일이 지났는가"로 바꿔 적으면 윤년에 하루가 어긋난다:
#    2028-03-01 − 30일 = 2028-01-31 인데 1/31 은 1월의 말일이라 두 표현이 갈린다
#    (말일+30 규칙은 2028-01 을 완결로 보고, 실제 구현은 2027-12 까지만 본다).
#    DB 에 실제로 들어가는 값은 구현 쪽이므로 이쪽을 모델로 삼는다.
model_db_ym() {
  local t="$1" open cand i
  open=$(date -d "@$((t - 30 * 86400))" +%Y-%m)   # 달력이 아니라 초로 뺀다(다른 표현)
  for i in 1 2 3 4; do
    cand=$(date -d "$(date -d "@$t" +%Y-%m-01) -$i month" +%Y-%m)
    if [[ "$cand" < "$open" ]]; then printf '%s' "$cand"; return 0; fi
  done
  return 1
}

# 옛 공식 (CR40-1 이 지적한 것). 되돌리면 이 시험이 죽는다.
old_expected_ym() {
  local t="$1"
  date -d "$(date -d "@$((t - 30 * 86400))" +%Y-%m-01) -1 month" +%Y-%m
}

# 마지막으로 배치가 돌았어야 할 시각 (매월 1일 04:10)
last_batch_epoch() {
  local t="$1" b
  b=$(date -d "$(date -d "@$t" +%Y-%m-01) 04:10" +%s)
  if [ "$t" -lt "$b" ]; then b=$(date -d "$(date -d "@$t" +%Y-%m-01) -1 month" +%s); b=$((b + 4 * 3600 + 600)); fi
  printf '%s' "$b"
}

# 2026-08-01 ~ 2027-07-31 을 **하루도 빼지 않고** 돈다.
# 달 단위로 묶어 도는 이유는 속도뿐이다 — DB 모델값은 한 달 안에서 바뀌지 않는다
# (배치가 그 달 1일에 한 번만 돌기 때문). 검사 자체는 매일 한다.
# ⚠️ 기본은 12개월(=365일)이다. 리뷰가 요구한 "한 해를 돌려 오탐 0" 이 이 값이다.
#    변이 시험처럼 빨리 돌려 보고 싶을 때만 SELFTEST_MONTHS 를 줄인다.
SELFTEST_MONTHS="${SELFTEST_MONTHS:-12}"
new_bad=0; old_bad=0; mism=0; n=0; first_bad=""; old_bad_days=""; t2_harn=0
for mo in $(seq 0 $((SELFTEST_MONTHS - 1))); do
  mstart=$(date -d "2026-08-01 +$mo month" +%Y-%m-01)
  ndays=$(date -d "$mstart +1 month -1 day" +%d)
  if ! nz "$mstart" "$ndays"; then t2_harn=$((t2_harn + 1)); continue; fi
  ndays=$((10#$ndays))
  mstart_e=$(date -d "$mstart 09:05" +%s)
  db=$(model_db_ym "$(last_batch_epoch "$mstart_e")")     # 이 달 내내 같은 값
  if ! nz "$mstart_e" "$db"; then t2_harn=$((t2_harn + 1)); continue; fi
  dd=1
  while [ "$dd" -le "$ndays" ]; do
    t=$(( mstart_e + (dd - 1) * 86400 ))   # 일일 점검이 실제로 도는 시각(09:05)
    exp=$(market_expected_ym "$t")
    oldexp=$(old_expected_ym "$t")
    if ! nz "$exp" "$oldexp"; then t2_harn=$((t2_harn + 1)); dd=$((dd + 1)); continue; fi
    n=$((n + 1))
    # 감시의 경보 조건은 `ref < expected` 다. 오탐 = DB 는 정상인데 이게 참이 되는 날.
    if [[ "$db" < "$exp" ]]; then
      new_bad=$((new_bad + 1)); [ -n "$first_bad" ] || first_bad="$(date -d "@$t" +%F) db=$db exp=$exp"
    fi
    [ "$db" = "$exp" ] || mism=$((mism + 1))
    if [[ "$db" < "$oldexp" ]]; then
      old_bad=$((old_bad + 1)); old_bad_days="$old_bad_days $(date -d "@$t" +%F)"
    fi
    dd=$((dd + 1))
  done
done

harn_if "$t2_harn" "T2 기대월 365일 루프" "date/서브셸이 값을 못 냈다"
if [ "$new_bad" -eq 0 ]; then ok "${n}일 오탐 0 (2026-08-01~2027-07-31 · 매일 09:05 기준)"
else ng "${n}일 중 ${new_bad}일 오탐" "첫 사례: $first_bad"; fi
if [ "$mism" -eq 0 ]; then ok "${n}일 전부 기대월 == DB 실제값 (한 달도 어긋나지 않는다)"
else ng "기대월과 DB 모델이 ${mism}일 불일치"; fi
if [ "$old_bad" -gt 0 ]; then
  ok "옛 공식은 같은 기간에 ${old_bad}일 오탐 — 되돌리면 위 시험이 죽는다"
  printf '        오탐일:%s\n' "$(printf '%s' "$old_bad_days" | tr ' ' '\n' | grep -c . | xargs -I{} echo '{}일')"
  printf '        %s\n' "$(printf '%s' "$old_bad_days" | sed 's/^ //')"
else
  ng "옛 공식이 오탐 0 으로 나온다 — 시험이 무엇도 붙잡지 못하고 있다"
fi

# 매월 1일 새벽(배치 전) · 배치 직후 경계
edge_bad=0; edge_harn=0
for m in $(seq 1 "$SELFTEST_MONTHS"); do
  base=$(date -d "2027-$(printf '%02d' "$m")-01" +%s)
  for hm in "00:30" "04:00" "05:59" "06:01" "23:59"; do
    t=$(date -d "$(date -d "@$base" +%Y-%m-01) $hm" +%s)
    if ! nz "$base" "$t"; then edge_harn=$((edge_harn + 1)); continue; fi
    db=$(model_db_ym "$(last_batch_epoch "$t")")
    exp=$(market_expected_ym "$t")
    if ! nz "$db" "$exp"; then edge_harn=$((edge_harn + 1)); continue; fi
    if [[ "$db" < "$exp" ]]; then
      edge_bad=$((edge_bad + 1))
      printf '        경계 오탐 %s db=%s exp=%s\n' "$(date -d "@$t" '+%F %H:%M')" "$db" "$exp"
    fi
  done
done
harn_if "$edge_harn" "T2 매월 1일 경계" "date 가 값을 못 냈다"
if [ "$edge_bad" -eq 0 ]; then ok "매월 1일 경계(00:30·04:00·05:59·06:01·23:59) 오탐 0 — 배치 전 새벽에도 안 운다"
else ng "매월 1일 경계에서 ${edge_bad}건 오탐"; fi

# ============================================================================
sect "T3. 기대월 공식이 배치(market-index.sh)와 감시(monitor-lib.sh)에서 같은가"

# 함수 이름을 인자로 받는다 — market_expected_ym 말고도 뽑아 써야 한다(T3b).
ext() { sed -n '/^'"$2"'() {$/,/^}$/p' "$1"; }
LIB_FN=$(ext "$HERE/monitor-lib.sh" market_expected_ym)
BAT_FN=$(ext "$HERE/market-index.sh" market_expected_ym)
if [ -n "$LIB_FN" ] && [ "$LIB_FN" = "$BAT_FN" ]; then
  ok "두 사본의 market_expected_ym 본문이 글자까지 같다"
else
  ng "market-index.sh 와 monitor-lib.sh 의 market_expected_ym 이 갈렸다" "$(diff <(echo "$LIB_FN") <(echo "$BAT_FN") | head -10)"
fi
# 공식이 기대는 **상수**도 같아야 한다. 한쪽만 바꾸면 본문이 같아도 한 달이 어긋난다.
RA=$(grep -c '^MARKET_BATCH_READY="\${RE_MON_MARKET_BATCH_READY:-06:00}"' "$HERE/monitor-lib.sh")
RB=$(grep -c '^MARKET_BATCH_READY="\${RE_MON_MARKET_BATCH_READY:-06:00}"' "$HERE/market-index.sh")
if [ "$RA" = 1 ] && [ "$RB" = 1 ]; then ok "MARKET_BATCH_READY 기본값이 두 사본에서 같다 (06:00)"
else ng "MARKET_BATCH_READY 가 두 사본에서 갈렸다 (lib=$RA batch=$RB) — 본문이 같아도 결과가 갈린다"; fi

# ⚠️ 느슨하게(`REF.*EXPECTED` 로) 보면 마지막 log 줄에도 두 낱말이 있어서
#    단언을 통째로 지워도 통과한다(변이 M-5 를 그렇게 놓쳤다). 비교 **블록 전체**를 본다.
#    ⛔ 옛 방식(`grep -A2`)은 실패 문구 앞에 주석 두 줄만 끼워도 깨졌다 — 코드가 아니라
#       **줄 간격**을 검사하고 있었던 것이다(이 검사가 스스로 그걸 잡아서 여기를 고쳤다).
#    ⛔ 그리고 파이프라인도 쓰지 않는다(CR41-6) — 파일을 한 번만 읽어 셸 내장으로 자른다.
MI=$(cat "$HERE/market-index.sh")
MI_AFTER=${MI#*'if [[ "$REF" < "$EXPECTED" ]]; then'}
MI_BLK=${MI_AFTER%%$'\nfi\n'*}
if has "$MI" 'EXPECTED=$(batch_expected_ym)' &&
   [ "$MI_BLK" != "$MI_AFTER" ] && has "$MI_BLK" '  fail "'; then
  ok "배치가 자기 기준월을 스스로 단언한다 — 비교 블록이 fail 로 끝난다 (1차 방어는 배치가 진다)"
else
  ng "market-index.sh 가 REF 를 기대값과 대조해 fail 하지 않는다"
fi
if grep -q 'expected=\$(market_expected_ym)' "$HERE/monitor.sh"; then
  ok "감시는 공용 함수를 쓴다 (자기 자리에서 날짜를 다시 짜지 않는다)"
else
  ng "monitor.sh 가 market_expected_ym() 을 안 쓴다 — 공식이 또 갈라진다"
fi

# ============================================================================
sect "T3b. 배치의 기대월이 **자기가 만드는 기준월**과 같은가 (CR41-2)"

# ⛔ 왜 이 검사가 생겼나 — T3 은 "비교문이 있는가"만 봤고 **값이 맞는지**는 안 봤다.
#    그래서 배치가 기대월을 인자 없이(=지금 시각) 계산하는 바람에 1일 04:10 이
#    유예(06:00) 분기에 걸려 기대월이 한 달 뒤처지는 것을 놓쳤다. 그 상태에서는
#    "돌긴 돌았는데 완결월이 안 올라간" 실패가 rc=0 으로 통과한다.
# 배치 코드를 **그대로 뽑아 eval** 한다 — 여기서 다시 짜면 같은 실수를 두 번 한다.
eval "$(ext "$HERE/market-index.sh" market_batch_epoch)" 2>/dev/null
eval "$(ext "$HERE/market-index.sh" batch_expected_ym)" 2>/dev/null
if ! declare -f batch_expected_ym >/dev/null 2>&1 || ! declare -f market_batch_epoch >/dev/null 2>&1; then
  ng "market-index.sh 에서 batch_expected_ym()/market_batch_epoch() 을 못 뽑았다 — 배치가 기준 시각을 고정하지 않는다"
else
  BATCH_MONTHS="${SELFTEST_BATCH_MONTHS:-18}"
  b_bad=0; b_naive=0; bn=0; b_first=""; b_harn=0
  for mo in $(seq 0 $((BATCH_MONTHS - 1))); do
    ms=$(date -d "2026-08-01 +$mo month" +%Y-%m-01)
    t=$(date -d "$ms 04:10" +%s)        # 크론이 배치를 돌리는 바로 그 시각
    ref=$(model_db_ym "$t")             # 그 배치가 실제로 DB 에 남길 기준월(파이썬 규칙)
    exp=$(batch_expected_ym "$t")       # 배치가 스스로 단언하는 기대월
    naive=$(market_expected_ym "$t")    # 기준 시각을 안 고정하던 옛 동작
    if ! nz "$ms" "$t" "$ref" "$exp" "$naive"; then b_harn=$((b_harn + 1)); continue; fi
    bn=$((bn + 1))
    if [ "$ref" != "$exp" ]; then
      b_bad=$((b_bad + 1)); [ -n "$b_first" ] || b_first="$(date -d "@$t" +%F) REF=$ref EXPECTED=$exp"
    fi
    [ "$ref" = "$naive" ] || b_naive=$((b_naive + 1))
  done
  harn_if "$b_harn" "T3b 배치 기대월 18개월" "date 가 값을 못 냈다"
  if [ "$b_bad" -eq 0 ]; then
    ok "${bn}개월 전부 '1일 04:10 의 EXPECTED == 그 배치가 만드는 REF'"
  else
    ng "${bn}개월 중 ${b_bad}개월에서 배치 기대월이 자기 결과와 어긋난다" "첫 사례: $b_first"
  fi
  if [ "$b_naive" -gt 0 ]; then
    ok "기준 시각을 안 고정하면 ${bn}개월 중 ${b_naive}개월이 어긋난다 — 이 검사가 그것을 붙잡는다"
  else
    ng "기준 시각을 안 고정해도 통과한다 — 이 검사가 아무것도 붙잡지 못한다"
  fi
  # 월중에 손으로 돌려도 기대값이 DB 보다 앞서면 안 된다(앞서면 정상 실행이 죽는다)
  m_bad=0; m_harn=0
  for mo in $(seq 0 $((BATCH_MONTHS - 1))); do
    ms=$(date -d "2026-08-01 +$mo month" +%Y-%m-01)
    for dd in 9 27; do
      t=$(date -d "$ms +$((dd - 1)) day 11:00" +%s)
      ref=$(model_db_ym "$t"); exp=$(batch_expected_ym "$t")
      # ⛔ CR43-3 이 지적한 바로 그 줄이 아래다. `$ref` 가 비면 `<` 는 무조건 참이라
      #    fork 실패 한 번이 **없는 결함**으로 보고됐다(동시 실행 3회 중 1회 실측).
      if ! nz "$ms" "$t" "$ref" "$exp"; then m_harn=$((m_harn + 1)); continue; fi
      [[ "$ref" < "$exp" ]] && m_bad=$((m_bad + 1))
    done
  done
  harn_if "$m_harn" "T3b 월중 수동 실행" "date 가 값을 못 냈다"
  if [ "$m_bad" -eq 0 ]; then ok "월중 수동 실행에서도 기대값이 DB 를 앞서지 않는다 (정상 실행이 안 죽는다)"
  else ng "월중 수동 실행 ${m_bad}회에서 기대값이 DB 보다 앞선다 — 손으로 돌리면 배치가 죽는다"; fi
fi

# ============================================================================
sect "T4. 로그 검사 fail-open — 대상이 0개면 경보가 나는가 (CR40-2)"

EMPTY="$TMPROOT/emptylogs"; mkdir -p "$EMPTY"
run_mon() {
  # $1=상태디렉터리  $2=모드  나머지=추가 환경변수
  local st="$1" mode="$2"; shift 2
  env RE_MON_STATE="$st" RE_MON_LOG="$st.log" RE_MON_DRY_RUN=1 RE_MON_PRINT=1 \
      RE_MON_URL_MAIN="http://127.0.0.1:9/" RE_MON_URL_HEALTH="http://127.0.0.1:9/h" \
      RE_MON_URL_MAP="http://127.0.0.1:9/m" RE_MON_URL_LOCAL="http://127.0.0.1:9/l" \
      RE_MON_CONTAINERS=" " \
      "$@" bash "$HERE/monitor.sh" "$mode" 2>&1
}

# ⚠️ **경보가 이미 켜져 있는 상태**에서 시작한다. fail-open 의 실제 피해는
#    "거짓 해소 통보"이고, 그건 켜진 경보가 있어야만 드러난다 —
#    빈 상태로 돌리면 clear_alert 가 조용히 돌아가서 시험이 아무것도 못 본다.
#    (실제로 그렇게 짜다가 변이 M-2 를 놓쳤다. 그래서 이렇게 둔다.)
S1="$TMPROOT/s1"; mkdir -p "$S1/alerts"
NOWS=$(date +%s)
for k in logperm logleak logfresh; do
  printf '%s' "$NOWS" >"$S1/alerts/$k.active"; printf '%s' "$NOWS" >"$S1/alerts/$k.sent"
done
OUT1=$(run_mon "$S1" --fast \
  RE_MON_LOG_DIR="$EMPTY" RE_MON_APP_LOG_GLOB="$EMPTY/realestate*.log*" \
  RE_MON_ACCESS_LOG="$EMPTY/none.access.log" RE_MON_ERROR_LOG="$EMPTY/none.error.log" \
  RE_MON_AUTH_LOG="$EMPTY/none.auth.log")

# 하네스 자신이 고장난 경우를 **검사 실패와 구분**해서 말한다 (CR41-6 · SR38-9 에서 배운 것)
if [ -n "$OUT1" ]; then ok "감시가 요약을 냈다 (하네스가 정상 동작)"
else ng "감시가 아무 출력도 내지 않았다 — 코드가 아니라 하네스/환경 문제다"; fi
want "$S1.log" 'ALERT logblind' "대상 0개 → logblind 경보가 뜬다" \
     "대상 0개인데 경보가 없다 (fail-open 재발)" "$(printf '%s' "$OUT1" | head -20)"
avoid "$S1.log" 'ALERT-CLEARED logperm\|ALERT-CLEARED logleak\|ALERT-CLEARED logfresh' \
     "못 본 검사는 clear_alert 를 부르지 않는다 (켜져 있던 경보를 끄지 않는다)" \
     "아무것도 못 봤는데 clear_alert 를 불렀다 (거짓 해소 통보)"
still=1
for k in logperm logleak logfresh; do [ -f "$S1/alerts/$k.active" ] || still=0; done
if [ "$still" = 1 ]; then ok "켜져 있던 경보 3건이 그대로 남는다 (감시 불능이 경보를 지우지 못한다)"
else ng "감시가 눈이 먼 상태에서 켜져 있던 경보가 지워졌다"; fi
if has "$OUT1" '해소'; then
  ng "해소 통보가 나갔다 — 사용자는 문제가 풀린 줄 안다"
else ok "해소 통보가 한 통도 안 나간다"; fi
if has "$OUT1" '검사 · 이상 없음'; then
  ng "대상 0개인데 요약에 '이상 없음' 이라고 적는다"
else ok "요약 문구가 '검사 못 함' 이다 (0개를 '이상 없음' 이라 하지 않는다)"; fi
if has "$OUT1" 'API 5xx : 검사 못 함'; then ok "API 5xx 도 '검사 못 함' 으로 남는다"
else ng "API 5xx 가 0건으로 통과한다"; fi
if [ ! -e "$S1/kv/api5xx" ]; then ok "파일이 없을 때 5xx 기준값을 0 으로 덮지 않는다"
else ng "5xx 기준값이 0 으로 덮였다 — 파일이 돌아오면 누적 전체가 델타로 잡혀 폭증 경보가 난다"; fi
if has "$OUT1" 'SSH     : 검사 못 함'; then ok "auth.log 가 없으면 SSH 검사도 '검사 못 함'"
else ng "auth.log 가 없는데 SSH 검사가 0건으로 통과한다"; fi

# nginx 로그만 있고 우리 로그(/var/log/realestate*.log)가 0개인 경우 — SR36-2 ③ 회귀
HALF="$TMPROOT/halflogs"; mkdir -p "$HALF"
: >"$HALF/realestate.access.log"; : >"$HALF/realestate.error.log"
S2="$TMPROOT/s2"
OUT2=$(run_mon "$S2" --fast \
  RE_MON_LOG_DIR="$HALF" RE_MON_APP_LOG_GLOB="$EMPTY/realestate*.log*" \
  RE_MON_ACCESS_LOG="$HALF/realestate.access.log" RE_MON_ERROR_LOG="$HALF/realestate.error.log" \
  RE_MON_AUTH_LOG="$EMPTY/none.auth.log")
if live "$S2.log" "nginx 로그만 있고 앱/배치 로그가 0개"; then
  if grep -aq 'ALERT logblind' "$S2.log" && has "$OUT2" '앱/배치 0개'; then
    ok "nginx 로그만 있고 앱/배치 로그가 0개면 그것도 경보 (묶음별로 센다)"
  else
    ng "앱/배치 로그 묶음이 0개인데 조용하다 — 감시가 자기 산출물을 안 보는 상태"
  fi
fi


# ⛔ CR41-3 — **한 묶음만** 없애는 시나리오가 없어서, blind_add 한 줄을 지워도
#    자체검사가 49/49 그대로 통과했다(리뷰가 찾은 7번째 변이). 대상을 전부 지우면
#    다른 blind_add 가 대신 울어 주기 때문이다. 그래서 여기서는 **하나씩** 없앤다.
#    ⚠️ 남는 한계: logleak(access) 와 api5xx 는 **같은 파일 하나**를 보므로 시나리오로
#       분리할 수 없다. 둘 중 하나를 지워도 다른 하나가 운다 — 그건 여기 적어 둔다.
ONE="$TMPROOT/onelogs"; mkdir -p "$ONE"
echo '127.0.0.1 - - [01/Aug/2026:09:00:00 +0900] "GET /api/v1/health HTTP/1.1" 200 12' >"$ONE/realestate.access.log"
: >"$ONE/realestate.error.log"; : >"$ONE/realestate-monitor.log"
echo 'Aug  1 08:00:00 h sshd[1]: Accepted publickey for root from 5.6.7.8 port 2 ssh2' >"$ONE/auth.log"

ONE_ST=""
one_missing() {   # $1=상태이름  $2..=이번에만 덮어쓸 환경변수(그 하나만 없앤다)
  local st="$TMPROOT/$1"; ONE_ST="$st"; shift
  run_mon "$st" --fast RE_MON_LOG_DIR="$ONE" RE_MON_APP_LOG_GLOB="$ONE/realestate-monitor.log*" RE_MON_ACCESS_LOG="$ONE/realestate.access.log" RE_MON_ERROR_LOG="$ONE/realestate.error.log" RE_MON_AUTH_LOG="$ONE/auth.log" "$@" >/dev/null 2>&1
  live "$st.log" "T4 단독 소실 시나리오 $(basename "$st")" || return 2
  grep -aq 'ALERT logblind' "$st.log"
}
one_missing s4a RE_MON_AUTH_LOG="$EMPTY/none.auth.log"; r=$?
if [ "$r" = 0 ]; then
  ok "auth.log **만** 없어도 감시불능 경보 — SSH 만 눈이 먼 상태를 잡는다 (CR41-3)"
elif [ "$r" = 1 ]; then
  ng "auth.log 만 소실됐는데 조용하다 — T2 트립와이어가 혼자 눈이 멀어도 아무도 모른다"
fi
one_missing s4b RE_MON_ERROR_LOG="$EMPTY/none.error.log"; r=$?
if [ "$r" = 0 ]; then ok "error.log **만** 없어도 감시불능 경보"
elif [ "$r" = 1 ]; then ng "error.log 만 소실됐는데 조용하다"; fi
one_missing s4c RE_MON_LOG_DIR="$EMPTY"; r=$?
if [ "$r" = 0 ]; then ok "nginx 로그 묶음 **만** 0개여도 감시불능 경보"
elif [ "$r" = 1 ]; then ng "nginx 묶음만 0개인데 조용하다"; fi
one_missing s4d; r=$?
if [ "$r" = 0 ]; then
  ng "전부 정상인데 감시불능 경보가 뜬다 — 위 3건이 '무조건 참'이라 아무것도 못 붙잡는다"
elif [ "$r" = 1 ]; then
  ok "같은 조건에서 전부 정상이면 경보가 없다 (위 3건이 무조건 참이 아니다)"
fi

# ⛔ **구조 검사 — `check_logblind` 는 `blind_add` 를 부르는 모든 검사보다 뒤여야 한다.**
#    앞에 두면 뒤쪽 검사의 "못 봤다" 사유가 **아무 데도 안 실리고 조용히 사라진다.**
#    시나리오 검사로는 안 잡힌다 — 그 검사가 blind 를 낼 조건을 시나리오마다 만들어야
#    하기 때문이다. 그래서 **호출 순서 자체**를 본다.
#    (이 검사가 생긴 이유: CR42-3 으로 check_cert 에 blind_add 를 넣으면서 순서를 옮겼고,
#     그 다음 check_db_structure 에 blind_add 를 넣을 때 같은 실수를 **한 번 더** 했다.
#     두 번 틀린 규칙은 사람이 아니라 기계가 지켜야 한다.)
# ⚠ 함수명에 **숫자**가 들어간다(`check_api5xx`). `[a-z_]+` 만 쓰면 그 함수를
#    못 알아보고 그 안의 blind_add 를 **앞 함수 것으로 오인**한다 —
#    조용한 오답이라 결과가 맞을 때도 있고, 그러면 더 나쁘다(실측해서 고쳤다).
# ⚠ `blind_add_daily`(CR43-1) 도 세어야 한다 — `/blind_add "/` 로만 보면 `blind_add_daily "`
#    는 **안 걸려서**, 인증서·DB 의 사유가 순서 검사 밖으로 통째로 빠져나간다.
#    그리고 `blind_add*` 정의 자신은 검사 대상이 아니다(그건 함수가 아니라 헬퍼다).
blind_fns=$(awk '/^[a-z_][a-z0-9_]*\(\) \{/{fn=$1; sub(/\(\).*/,"",fn)} /blind_add(_daily)? "/{if(fn!="" && fn !~ /^blind_add/)print fn}' \
            "$HERE/monitor.sh" | sort -u)
if [ -z "$blind_fns" ]; then
  ng "monitor.sh 에서 blind_add 를 부르는 함수를 하나도 못 찾았다 — 검사가 무의미하다"
else
  for mode in fast daily; do
    blk=$(sed -n "/^  $mode)\$/,/^    ;;\$/p" "$HERE/monitor.sh")
    # ⚠ 줄 끝에 주석이 붙을 수 있다 — `$` 로 못 박으면 못 찾는다(그렇게 짜다가 한 번 붉었다).
    lb=$(printf '%s\n' "$blk" | grep -nE '^[[:space:]]*check_logblind([[:space:]]|$)' | head -1 | cut -d: -f1)
    bad=""
    for fn in $blind_fns; do
      pos=$(printf '%s\n' "$blk" | grep -nE "^[[:space:]]*$fn([[:space:]]|"'$'")" | head -1 | cut -d: -f1)
      if [ -z "$pos" ]; then
        # ⛔ 모드 블록에서 **직접** 안 불리는 함수 — 다른 검사가 부른다.
        #    예전에는 여기서 그냥 `continue` 했다. 그러면 `check_db_structure` 가 부르는
        #    `check_market_stale` 처럼 **한 겹 안쪽에서 blind_add 를 하는 함수**가
        #    순서 검사를 통째로 빠져나간다 — CR43-2 로 판정을 함수로 빼는 순간
        #    생긴 자리다(검사를 고치면서 검사에 구멍을 내는 그 형태).
        #    → 부르는 쪽을 찾아 **그 자리로** 잰다. 부르는 쪽도 없으면 죽은 코드라 넘어간다.
        callers=$(awk -v t="$fn" '
          /^[a-z_][a-z0-9_]*\(\) \{/ { f=$1; sub(/\(\).*/,"",f) }
          { if (f != "" && f != t && $0 ~ ("^[[:space:]]+" t "([[:space:]]|$)")) print f }
        ' "$HERE/monitor.sh" | sort -u)
        for c in $callers; do
          cpos=$(printf '%s\n' "$blk" | grep -nE "^[[:space:]]*$c([[:space:]]|"'$'")" | head -1 | cut -d: -f1)
          [ -n "$cpos" ] || continue
          if [ -z "$pos" ] || [ "$cpos" -gt "$pos" ]; then pos="$cpos"; fi
        done
      fi
      [ -n "$pos" ] || continue                 # 이 모드에서 (직접도 간접도) 안 부르면 넘어간다
      if [ -z "$lb" ] || [ "$pos" -gt "$lb" ]; then bad="$bad $fn"; fi
    done
    if [ -z "$lb" ]; then
      ng "--$mode 경로에 check_logblind 가 없다 — '못 봤다' 사유가 아무 데도 안 실린다"
    elif [ -n "$bad" ]; then
      ng "--$mode 경로에서 check_logblind 보다 **뒤에** blind_add 검사가 있다:$bad" \
         "그 검사들이 남긴 '못 봤다' 사유는 조용히 사라진다"
    else
      ok "--$mode 경로에서 check_logblind 가 blind_add 검사 전부보다 뒤다 (사유가 사라지지 않는다)"
    fi
  done
fi

# ============================================================================
sect "T5. 대조군 — 정상 파일이 있으면 제대로 판정하는가"

FULL="$TMPROOT/fulllogs"; mkdir -p "$FULL"
printf '127.0.0.1 - - [01/Aug/2026:09:00:00 +0900] "GET /api/v1/health HTTP/1.1" 200 12\n' >"$FULL/realestate.access.log"
: >"$FULL/realestate.error.log"
: >"$FULL/realestate-monitor.log"
printf 'Aug  1 08:00:00 h sshd[1]: Accepted publickey for root from 5.6.7.8 port 2 ssh2
' >"$FULL/auth.log"
chmod 640 "$FULL"/*.log 2>/dev/null
PERM_OK=$(stat -c %a "$FULL/realestate.access.log" 2>/dev/null)

S3="$TMPROOT/s3"; mkdir -p "$S3/alerts"
# 양성 대조군 — "못 보면 clear 금지"를 넣느라 **정상일 때도 clear 를 안 하게** 만들면
# 그것대로 결함이다(해소 통보가 영영 안 온다). 켜 놓고 시작해서 꺼지는지 본다.
printf '%s' "$(date +%s)" >"$S3/alerts/logleak.active"; printf '%s' "$(date +%s)" >"$S3/alerts/logleak.sent"
# ⛔ 스스로 찾은 8번째 변이 자리 — `check_logblind` 의 **clear 경로**는 아무도 안 봤다.
#    그 한 줄을 지우면 한 번 켜진 '감시불능'이 **영원히 안 꺼진다**. 사람은 곧 그 경보를
#    무시하게 되고, 그러면 fail-open 을 막으려고 만든 장치가 통째로 무의미해진다.
#    (T4 는 켜지는 것만, T5 는 logleak 만 봤다 — 그래서 이 자리가 비어 있었다)
printf '%s' "$(date +%s)" >"$S3/alerts/logblind.active"; printf '%s' "$(date +%s)" >"$S3/alerts/logblind.sent"
OUT3=$(run_mon "$S3" --fast \
  RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
  RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
  RE_MON_AUTH_LOG="$FULL/auth.log")

avoid "$S3.log" 'ALERT logblind' "파일이 정상이면 감시불능 경보가 안 뜬다 (오탐 없음)" \
      "파일이 다 있는데 감시불능 경보가 뜬다 (반대쪽 오탐)" "$(printf '%s' "$OUT3" | grep 감시불능)"
if live "$S3.log" "T5 감시불능 해소"; then
  if grep -aq 'ALERT-CLEARED logblind' "$S3.log" && [ ! -f "$S3/alerts/logblind.active" ]; then
    ok "감시불능이 풀리면 그 경보도 실제로 해소된다 (켜지기만 하고 안 꺼지면 사람이 무시하게 된다)"
  else
    ng "감시불능 경보가 정상 복귀 뒤에도 안 꺼진다 — 영구 경보는 곧 무시되는 경보다"
  fi
  if grep -aq 'ALERT-CLEARED logleak' "$S3.log" && [ ! -f "$S3/alerts/logleak.active" ]; then
    ok "정상으로 돌아오면 켜져 있던 경보가 실제로 해소된다 (한쪽으로만 막지 않았다)"
  else
    ng "정상인데 해소 통보가 안 나간다 — clear 경로를 통째 막아 버렸다"
  fi
fi

if [ "$PERM_OK" = "640" ]; then
  avoid "$S3.log" 'ALERT logperm' "0640 이면 권한 경보 없음" "0640 인데 권한 경보가 뜬다"
  chmod 644 "$FULL/realestate.access.log"
  S4="$TMPROOT/s4"
  run_mon "$S4" --fast \
    RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
    RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
    RE_MON_AUTH_LOG="$FULL/auth.log" >/dev/null 2>&1
  want "$S4.log" 'ALERT logperm.*644' "0644 파일 하나를 정확히 집어낸다" "0644 를 못 잡는다" \
       "$(stat -c '%a %n' "$FULL"/*.log 2>&1 | tr '\n' ' ')"
  chmod 640 "$FULL/realestate.access.log"
else
  skip "권한 판정 대조군 — 이 파일시스템은 chmod 가 안 먹는다(stat=$PERM_OK · 윈도우). 리눅스(서버)에서 확인할 것"
fi

# access 로그 mtime 신선도: 오래된 mtime 을 만들어 확인
if touch -d '3 days ago' "$FULL/realestate.access.log" 2>/dev/null; then
  S5="$TMPROOT/s5"
  run_mon "$S5" --fast \
    RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
    RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
    RE_MON_AUTH_LOG="$FULL/auth.log" >/dev/null 2>&1
  want "$S5.log" 'ALERT logfresh' "access 로그가 3일째 안 늘면 경보 (파일은 있는데 안 쓰이는 상태)" \
       "access 로그 mtime 이 3일 전인데 조용하다"
  touch "$FULL/realestate.access.log"
  S6="$TMPROOT/s6"
  run_mon "$S6" --fast \
    RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
    RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
    RE_MON_AUTH_LOG="$FULL/auth.log" >/dev/null 2>&1
  avoid "$S6.log" 'ALERT logfresh' "방금 기록된 로그면 신선도 경보 없음 — '없다'와 '안 늘었다'를 구분한다" \
        "방금 쓴 로그인데 신선도 경보가 뜬다 (새벽 무트래픽 오탐)"
else
  skip "mtime 신선도 — touch -d 를 못 쓴다"
fi

# 쿼리스트링 유출 대조군
printf '1.2.3.4 - - [01/Aug/2026:09:00:00 +0900] "GET /api/v1/x?token=abc HTTP/1.1" 200 12\n' >>"$FULL/realestate.access.log"
S7="$TMPROOT/s7"
run_mon "$S7" --fast \
  RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
  RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
  RE_MON_AUTH_LOG="$FULL/auth.log" >/dev/null 2>&1
want "$S7.log" 'ALERT logleak' "쿼리스트링이 실제로 남으면 잡는다 (검사 로직은 살아 있다)" \
     "쿼리스트링이 있는데 못 잡는다"
if live "$S7.log" "T5 유출 경보 본문"; then
  LEAKLINE=$(grep -a 'ALERT logleak' "$S7.log")
  if has "$LEAKLINE" 'token=abc'; then
    ng "경보 본문에 새어 나온 값이 실렸다 — 감시가 다시 유출한다"
  else ok "경보에는 건수만 실린다 (원문 미포함)"; fi
fi

# ============================================================================
sect "T5b. 인증서 검사의 fail-open — 대상 0개를 '여유 회복'이라 말하는가 (CR42-3)"

# ⛔ CR40-2 가 로그 검사 3종에서 막은 fail-open 이 **인증서 검사에는 그대로 남아 있었다.**
#    `$LE_DIR` 밑에 cert.pem 이 하나도 없으면 루프를 한 번도 안 돌고 worst=9999 로
#    내려와 `clear_alert cert` 를 불렀다 —
#      ALERT-CLEARED cert :: 인증서 여유 회복 (최단  9999일)   ← 이름 빈칸 · 없는 값
#    켜져 있던 경보를 지우고 "해소" 통보까지 보낸다. selftest 에 인증서 시나리오는 **0건**이었다.
#    ⚠️ **경보를 미리 켜 놓고** 시작한다 — 거짓 해소는 켜진 경보가 있어야만 드러난다
#       (T4 가 M-2 를 놓쳤던 것과 같은 이유다).
#
# check_cert 는 --daily 에만 있다. docker 를 부르는 검사들이 같이 도는데, 이 검사와
# 무관하고 환경에 따라 느리므로 **항상 실패하는 가짜 docker** 를 PATH 앞에 둔다
# (그러면 check_db_structure 는 설정 못 읽음으로 즉시 빠지고, 네트워크도 안 탄다).
FAKEBIN="$TMPROOT/fakebin"; mkdir -p "$FAKEBIN"
printf '#!/bin/sh\nexit 1\n' >"$FAKEBIN/docker"; chmod +x "$FAKEBIN/docker" 2>/dev/null

LE_EMPTY="$TMPROOT/le-empty"; mkdir -p "$LE_EMPTY"
SC1="$TMPROOT/sc1"; mkdir -p "$SC1/alerts"
printf '%s' "$(date +%s)" >"$SC1/alerts/cert.active"; printf '%s' "$(date +%s)" >"$SC1/alerts/cert.sent"
OUTC1=$(run_mon "$SC1" --daily PATH="$FAKEBIN:$PATH" RE_MON_LE_DIR="$LE_EMPTY" \
  RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
  RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
  RE_MON_AUTH_LOG="$FULL/auth.log")

avoid "$SC1.log" 'ALERT-CLEARED cert' \
      "(음성 대조군) 인증서 대상 0개면 clear_alert 를 부르지 않는다" \
      "대상 0개인데 '인증서 여유 회복' 해소 통보를 보낸다 (CR40-2 가 막은 그 형태)"
if [ -f "$SC1/alerts/cert.active" ]; then
  ok "(음성 대조군) 켜져 있던 cert 경보가 살아남는다 (못 본 것이 경보를 지우지 못한다)"
else
  ng "아무것도 못 봤는데 켜져 있던 cert 경보가 지워졌다 — 거짓 해소"
fi
if has "$OUTC1" '인증서  : 검사 못 함 (대상 0개'; then
  ok "요약 문구가 '검사 못 함 (대상 0개)' 다 (빈 목록을 이상 없음처럼 적지 않는다)"
else
  ng "대상 0개인데 요약이 '검사 못 함' 이라고 적지 않는다" "$(printf '%s' "$OUTC1" | grep -a 인증서)"
fi
want "$SC1.log" 'ALERT logblind' "인증서 대상 0개가 감시불능 사유로 한 통에 실린다" \
     "인증서를 못 봤는데 logblind 에도 안 실린다 — 아무 데도 안 남는다"
if has "$OUTC1" '인증서 대상 0개'; then ok "감시불능 사유에 인증서 항목이 이름으로 남는다"
else ng "감시불능 사유에 인증서가 안 보인다" "$(printf '%s' "$OUTC1" | grep -a 감시불능)"; fi
if has "$OUTC1" '9999'; then
  ng "요약/알림에 존재하지 않는 값 9999일 이 남아 있다"
else ok "존재하지 않는 값(9999일)이 어디에도 안 나온다"; fi

# ⛔ **CR43-1 — 13번째 자리. 여기에 모드 대칭이 없었다. (PASS 조건 1)**
#    `check_cert` 는 `raise_alert` 를 안 하고 `blind_add` 만 한다(그렇게 설계됐다).
#    그러므로 "인증서를 못 봤다"가 사람에게 닿는 길은 `logblind` **하나뿐**이다.
#    그런데 5분 뒤 `--fast` 는 인증서를 **돌리지도 않으면서** 자기 BLIND 가 비었다는
#    이유로 그 경보를 지우고 *"해소: 로그 감시 대상 정상 (권한·유출·5xx·SSH 검사
#    전부 수행)"* 을 보냈다. 그리고 다음 일일 점검이 다시 켠다 —
#    **raise 2 / clear 1 이 매일 반복**되고, 쿨다운 21600 도 `.sent` 가 지워져 무력화된다.
#    이 자리를 못 본 이유는 단순하다: T5b 가 `--daily` 를 **한 번만** 돌렸다.
#    → 같은 상태에 `--fast` 를 이어서 돌린다. 모드가 바뀌면 판단도 바뀌어야 한다.
SC1_PRE=$(wc -l <"$SC1.log" 2>/dev/null); SC1_PRE=${SC1_PRE:-0}
OUTC1F=$(run_mon "$SC1" --fast \
  RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
  RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
  RE_MON_AUTH_LOG="$FULL/auth.log")
tail -n +$((SC1_PRE + 1)) "$SC1.log" >"$SC1.fastonly.log" 2>/dev/null
avoid "$SC1.fastonly.log" 'ALERT-CLEARED logblind' \
      "**--fast 가 --daily 전용 사유(인증서)를 해소하지 않는다** (CR43-1 · 모드 대칭)" \
      "5분 감시가 인증서를 본 적도 없이 '로그 감시 대상 정상' 이라며 감시불능을 해소한다"
if [ -f "$SC1/alerts/logblind.active" ]; then
  ok "--fast 를 지나도 logblind 경보가 살아남는다 (다음 일일 점검이 다시 판정한다)"
else
  ng "--fast 가 logblind 를 지웠다 — 매일 raise 2 / clear 1 이 반복되고 쿨다운도 무력화된다"
fi
if has "$OUTC1F" '해소'; then
  ng "--fast 에서 '해소' 통보가 나갔다 — 사용자는 인증서 문제가 풀린 줄 안다" "$OUTC1F"
else
  ok "--fast 에서 해소 통보가 한 통도 안 나간다 (인증서를 본 적이 없으니 말할 자격이 없다)"
fi
if has "$OUTC1F" '일일 점검이 남긴 사유'; then
  ok "5분 요약이 '아직 사유가 남아 있다' 고 적는다 (침묵도 거짓 안심도 아니다)"
else
  ng "5분 요약이 남아 있는 감시불능 사유를 말하지 않는다" "$(printf '%s' "$OUTC1F" | grep -a 감시불능)"
fi

# 양성 대조군 — 정상 인증서가 하나 있으면 **실제로 해소**돼야 한다.
#   한쪽만 막고 반대쪽을 죽이면 그것도 결함이다(해소 통보가 영영 안 온다).
LE_OK="$TMPROOT/le-ok"; mkdir -p "$LE_OK/site.example"
CERT_MADE=0
if command -v openssl >/dev/null 2>&1; then
  # ⚠️ MSYS/Git-Bash 는 `/CN=...` 를 윈도우 경로로 **바꿔 버린다**(실측: subject 가
  #    'C:/Program Files/Git/CN=site.example' 이 된다). **`/CN=` 로 시작하는 인자만** 끈다 —
  #    `'*'` 로 통째로 끄면 `-keyout /tmp/...` 경로까지 변환이 안 돼 openssl 이 못 연다(실측).
  #    리눅스에서는 그냥 안 쓰이는 환경변수라 아무 영향이 없다.
  if MSYS2_ARG_CONV_EXCL='/CN=' openssl req -x509 -newkey rsa:2048 -nodes -days 90 \
       -keyout "$TMPROOT/k.pem" -out "$LE_OK/site.example/cert.pem" \
       -subj '/CN=site.example' >/dev/null 2>&1; then CERT_MADE=1; fi
fi
if [ "$CERT_MADE" = 1 ]; then
  SC2="$TMPROOT/sc2"; mkdir -p "$SC2/alerts" "$SC2/kv"
  # 옛 daily 사유가 kv 에 남아 있는 상태에서 시작한다 — 일일 점검이 그것을 **갱신**해야
  # 한다. 안 그러면 fast 는 영영 clear 를 못 하고, 그건 반대쪽 결함이다(CR43-1 대칭).
  printf '%s' " 인증서 대상 0개(어제 사유);" >"$SC2/kv/blind_daily"
  printf '%s' "$(date +%s)" >"$SC2/alerts/logblind.active"; printf '%s' "$(date +%s)" >"$SC2/alerts/logblind.sent"
  printf '%s' "$(date +%s)" >"$SC2/alerts/cert.active"; printf '%s' "$(date +%s)" >"$SC2/alerts/cert.sent"
  OUTC2=$(run_mon "$SC2" --daily PATH="$FAKEBIN:$PATH" RE_MON_LE_DIR="$LE_OK" \
    RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
    RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
    RE_MON_AUTH_LOG="$FULL/auth.log")
  if live "$SC2.log" "T5b 양성 대조군"; then
    if grep -aq 'ALERT-CLEARED cert' "$SC2.log" && [ ! -f "$SC2/alerts/cert.active" ]; then
      ok "(양성 대조군) 90일짜리 정상 인증서 1개면 켜져 있던 경보가 실제로 해소된다"
    else
      ng "정상 인증서가 있는데 해소가 안 된다 — fail-open 을 막으면서 clear 경로를 통째로 죽였다"
    fi
  fi
  if has "$OUTC2" 'site.example='; then ok "요약에 인증서 이름과 남은 일수가 실린다 (이름 빈칸 아님)"
  else ng "요약에 인증서 이름이 없다" "$(printf '%s' "$OUTC2" | grep -a 인증서)"; fi

  # ⛔ **CR43-1 양성 대칭 (PASS 조건 1의 뒷면).** 한쪽만 막고 반대쪽을 죽이면
  #    그것도 결함이다 — 그러면 감시불능 경보가 **영영 안 꺼지고**, 안 꺼지는 경보는
  #    곧 무시되는 경보다(8번째 변이가 정확히 그 자리였다).
  #    앞에서 `logblind` 를 띄운 **그 상태 그대로** 인증서만 정상으로 바꿔 일일 점검을
  #    다시 돌린다. 이번에는 인증서를 **실제로 봤으므로** 해소할 자격이 있다.
  SC1_PRE2=$(wc -l <"$SC1.log" 2>/dev/null); SC1_PRE2=${SC1_PRE2:-0}
  OUTC1R=$(run_mon "$SC1" --daily PATH="$FAKEBIN:$PATH" RE_MON_LE_DIR="$LE_OK" \
    RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
    RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
    RE_MON_AUTH_LOG="$FULL/auth.log")
  tail -n +$((SC1_PRE2 + 1)) "$SC1.log" >"$SC1.recover.log" 2>/dev/null
  want "$SC1.recover.log" 'ALERT-CLEARED logblind' \
       "(양성 대칭) 인증서가 정상으로 돌아오면 --daily 가 감시불능을 **실제로** 해소한다" \
       "fail-open 을 막으면서 해소 경로를 통째로 죽였다 — 감시불능이 영영 안 꺼진다"
  if [ ! -f "$SC1/alerts/logblind.active" ]; then
    ok "(양성 대칭) 해소되면 .active 도 지워진다"
  else
    ng "해소 통보는 갔는데 경보가 안 꺼졌다"
  fi
  if [ ! -s "$SC1/kv/blind_daily" ]; then
    ok "일일 점검이 daily 전용 사유 기록을 **매번 갱신**한다 (옛 사유가 굳어 fast 를 영구 봉인하지 않는다)"
  else
    ng "인증서가 정상인데 daily 전용 사유 기록이 남아 있다 — fast 가 영영 clear 를 못 하게 된다" \
       "$(cat "$SC1/kv/blind_daily" 2>/dev/null)"
  fi
  # 그리고 그 뒤의 5분 감시는 조용하다 (되풀이 재발 아님)
  SC1_PRE3=$(wc -l <"$SC1.log" 2>/dev/null); SC1_PRE3=${SC1_PRE3:-0}
  run_mon "$SC1" --fast \
    RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
    RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
    RE_MON_AUTH_LOG="$FULL/auth.log" >/dev/null 2>&1
  tail -n +$((SC1_PRE3 + 1)) "$SC1.log" >"$SC1.after.log" 2>/dev/null
  avoid "$SC1.after.log" 'ALERT logblind\|ALERT-CLEARED logblind' \
        "해소된 뒤의 5분 감시는 logblind 를 켜지도 끄지도 않는다 (상태가 안정된다)" \
        "해소 뒤에도 5분 감시가 logblind 를 다시 건드린다"

  # 임박 판정도 살아 있는가 (임계를 올려서 같은 인증서로 확인한다)
  SC3="$TMPROOT/sc3"
  run_mon "$SC3" --daily PATH="$FAKEBIN:$PATH" RE_MON_LE_DIR="$LE_OK" RE_MON_CERT_MIN_DAYS=3650 \
    RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
    RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
    RE_MON_AUTH_LOG="$FULL/auth.log" >/dev/null 2>&1
  want "$SC3.log" 'ALERT cert' "(양성 대조군) 임계 미만이면 실제로 만료 임박 경보가 난다" \
       "임계를 넘겼는데 인증서 경보가 안 난다 — 검사 로직이 죽었다"
else
  skip "인증서 양성 대조군 — openssl 로 시험용 인증서를 못 만들었다. 리눅스(서버)에서 확인할 것"
fi

# ============================================================================
sect "T6. SSH 비밀번호 로그인 성공 감시 (SR-036R T2)"

AUTH="$TMPROOT/auth.log"
{
  printf 'Aug  1 08:00:00 h sshd[1]: Failed password for root from 1.2.3.4 port 1 ssh2\n'
  printf 'Aug  1 08:01:00 h sshd[2]: Accepted publickey for root from 5.6.7.8 port 2 ssh2: RSA SHA256:xxx\n'
} >"$AUTH"
S8="$TMPROOT/s8"
OUT8=$(run_mon "$S8" --fast RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
  RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
  RE_MON_AUTH_LOG="$AUTH")
avoid "$S8.log" 'ALERT sshpw' "기준값 설정 — 공개키 성공·비밀번호 실패는 세지 않는다" \
      "공개키 로그인·실패만 있는데 경보가 뜬다 (실패 88,316건을 세면 안 된다)"
if has "$OUT8" 'SSH     : 기준값 설정'; then ok "첫 실행은 기준값만 잡는다"; else ng "기준값 줄이 없다"; fi

printf 'Aug  1 08:02:00 h sshd[3]: Accepted password for root from 9.9.9.9 port 3 ssh2\n' >>"$AUTH"
S8B="$S8"   # 같은 상태 디렉터리를 이어 쓴다 (증가분만 봐야 한다)
OUT8B=$(run_mon "$S8B" --fast RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
  RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
  RE_MON_AUTH_LOG="$AUTH")
want "$S8B.log" 'ALERT sshpw' "비밀번호 로그인 성공 1건 → 경보 (T2 가 기계 신호가 됐다)" \
     "비밀번호 로그인 성공을 못 잡는다 — T2 가 여전히 사람의 기억이다"
if live "$S8B.log" "T6 경보 본문"; then
  SSHLINE=$(grep -a 'ALERT sshpw' "$S8B.log")
  if has "$SSHLINE" '9.9.9.9' || has "$SSHLINE" 'Accepted password for root from'; then
    ng "경보에 로그 원문/IP 가 실렸다 — 건수만 보내야 한다"
  else ok "경보에 건수만 실린다 (사용자명·IP·원문 없음)"; fi
  # 문구가 바뀌었다(SR39-1 로 journald 건수가 같은 줄에 실린다) — 세는 값은 그대로다.
  if has "$SSHLINE" 'auth.log 1건'; then ok "증가분만 센다 (누적이 아니라 이번 구간)"
  else ng "증가분 계산이 어긋난다" "$SSHLINE"; fi
  if has "$SSHLINE" 'journald'; then ok "경보 본문이 두 번째 출처의 건수도 함께 말한다 (SR39-1)"
  else ng "경보 본문에 journald 교차 결과가 없다 — 출처가 하나뿐인지 사람이 알 수 없다"; fi
fi


# ⛔ SR37-1 / CR41-3 / CR42-2 / SR38-1·2·3 — 트립와이어를 뚫은 시나리오 전부.
#    (a) 정상 회전  (b) .1.gz 만 남음  (c) : > auth.log  (c2) 옛 .1 이 큰 채로 truncate
#    (d) 회전 뒤 옛 오프셋 초과 성장
#    (h) rm + 재생성 · 낡은 .1 이 오프셋보다 큼      ← CR42-2 (9번째 변이)
#    (l) 서버형 delaycompress(.1 평문 + .2.gz) · rm + 재생성  ← CR42-2
#    (x1) : > auth.log + touch .1 (mtime 위조)        ← SR38-1
#    (x4) 정상 회전 뒤 .1 안의 줄만 삭제              ← SR38-2
#    (x6) auth.log 동결(rsyslog 정지)                 ← SR38-3 (최우선)
#    + 대조군 — 여기서 울면 매주 로테이션마다 오탐이 된다.
RD="$TMPROOT/rot"; mkdir -p "$RD"
authgen() { local n=$1 i=1; while [ "$i" -le "$n" ]; do echo "Aug  1 07:00:00 h sshd[$i]: Failed password for root from 1.2.3.4 port 1 ssh2"; i=$((i + 1)); done; }
HIT='Aug  1 08:02:00 h sshd[9]: Accepted password for root from 9.9.9.9 port 3 ssh2'
# journald `-o cat` 은 **메시지 본문만** 준다(syslog 접두부 없음 — 서버 실측).
# 두 출처는 형식이 다르므로 픽스처도 달라야 한다. 같은 줄을 양쪽에 쓰면 그건 현실이 아니다.
HIT_JD='Accepted password for root from 9.9.9.9 port 3 ssh2'
sshrun() { local st="$TMPROOT/$1"; run_mon "$st" --fast RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" RE_MON_AUTH_LOG="$2" >/dev/null 2>&1; }

# --- 이 파일시스템이 판정에 필요한 것을 지원하는가 --------------------------
#     ① inode 를 읽을 수 있는가 ② 다른 파일이 다른 번호인가 ③ **rename 이 번호를 보존하는가**
#     ③이 새 판정(CR42-2 / SR38-1)의 근거다. 못 지원하면 그 케이스는 SKIP 하고 그렇게 적는다.
: >"$RD/i1"; : >"$RD/i2"
ii1=$(stat -c %i "$RD/i1" 2>/dev/null); ii2=$(stat -c %i "$RD/i2" 2>/dev/null)
mv "$RD/i1" "$RD/i1m" 2>/dev/null; ii1m=$(stat -c %i "$RD/i1m" 2>/dev/null)
INO_OK=0
if [ -n "$ii1" ] && [ -n "$ii2" ] && [ "$ii1" != "$ii2" ] && [ "$ii1" = "$ii1m" ]; then INO_OK=1; fi
if [ "$INO_OK" = 1 ]; then
  ok "이 파일시스템은 inode 를 구분하고 **rename 이 번호를 보존한다** — 회전 불변식을 시험할 수 있다"
else
  skip "inode 불변식 시험 불가 (읽기=$ii1/$ii2 · rename 후=$ii1m). 리눅스(서버)에서 확인할 것"
fi

AU="$RD/a.auth.log"; authgen 40 >"$AU"; sshrun ra "$AU"
echo "$HIT" >>"$AU"; mv "$AU" "$AU.1"; authgen 3 >"$AU"; sshrun ra "$AU"
want "$TMPROOT/ra.log" 'ALERT sshpw' "(a) 정상 회전 직전 구간의 비밀번호 로그인 성공을 잡는다" \
     "(a) 회전하면서 직전 구간의 침입을 놓친다"

# (b) `compress`(delaycompress 없음) — logrotate 가 `.1` 을 지우므로 새 auth.log 가
#     **옛 inode 를 재사용**할 수 있다(실측으로 그런다). inode 만 보는 판정은 여기서 깨진다.
#     그리고 여기서는 `.1` 이 없어 **강한 증거(rename 불변식)를 쓸 수 없다** —
#     약한 증거(mtime)로 세되, 그랬다는 사실을 blind 로 남기는지까지 본다.
AU="$RD/b.auth.log"; authgen 40 >"$AU"; sshrun rb "$AU"
echo "$HIT" >>"$AU"
if command -v gzip >/dev/null 2>&1 && gzip -c "$AU" >"$AU.1.gz" 2>/dev/null; then
  rm -f "$AU"; authgen 3 >"$AU"; sshrun rb "$AU"
  # ⚠️ "조용하지만 않으면 통과" 로 두면 압축본 처리를 통째로 지워도 살아남는다
  #    (변이로 확인했다 — authshrink 가 대신 울어 준다). **세는 것**까지 요구한다.
  if live "$TMPROOT/rb.log" "(b) 압축 회전본"; then
    if grep -aq 'ALERT sshpw' "$TMPROOT/rb.log"; then
      ok "(b) 회전본이 .1.gz 뿐이어도 압축본을 풀어 그 구간의 침입을 센다"
    elif grep -aq 'ALERT authshrink' "$TMPROOT/rb.log"; then
      ng "(b) .1.gz 를 못 읽어 '못 봤다'고만 한다 — 침묵보다 낫지만 셀 수 있는 것을 안 센다"
    else ng "(b) .1.gz 만 남으면 침입을 놓치고 침묵한다 — logrotate 설정 한 줄에 T2 가 꺼진다"; fi
  fi
  want "$TMPROOT/rb.log" '약한 증거' \
       "(b) 압축 회전은 **약한 증거(mtime)로 판정했다**는 사실을 남긴다 (SR38-1)" \
       "(b) 위조 가능한 증거로 회전을 확정하고 그 사실을 아무 데도 안 적는다"
else skip "(b) gzip 이 없어 압축 회전본을 만들 수 없다"; fi

AU="$RD/c.auth.log"; authgen 40 >"$AU"; sshrun rc "$AU"
echo "$HIT" >>"$AU"; : >"$AU"; sshrun rc "$AU"
want "$TMPROOT/rc.log" 'ALERT authshrink' "(c) auth.log 를 통째로 비우면 경보 — 가장 흔한 흔적 삭제 한 줄" \
     "(c) auth.log 를 비웠는데 조용하다 — 위험수용(SR36-1)을 지탱하는 유일한 기계가 눈이 먼다"
want "$TMPROOT/rc.log" 'ALERT logblind' "(c) 못 본 구간이 감시불능 사유에도 남는다" \
     "(c) 지워진 구간을 '0건'으로 넘긴다"
# (c 해소) ⛔ CR44-2 §10 — **clear 경로를 관문이 보는 것이 여섯뿐**이었다. `authshrink`
#   는 코드에 clear 가 있는데 아무도 안 봤다. 안 꺼지는 경보는 곧 무시되는 경보이고,
#   그 결함은 `sshjournal` 에서 실제로 났다. 추적이 정상으로 돌아오면 꺼져야 한다.
RCPRE=$(wc -l <"$TMPROOT/rc.log" 2>/dev/null); RCPRE=${RCPRE:-0}
authgen 6 >>"$AU"; sshrun rc "$AU"
tail -n +$((RCPRE + 1)) "$TMPROOT/rc.log" >"$TMPROOT/rc.after.log" 2>/dev/null
want "$TMPROOT/rc.after.log" 'ALERT-CLEARED authshrink' \
     "(c 해소) 추적이 정상으로 돌아오면 authshrink 가 꺼진다 (요약 머리말의 미해소가 풀린다)" \
     "(c 해소) 한 번 truncate 되면 authshrink 가 영영 안 꺼진다 — 사람이 그 이름을 무시하게 된다"
if [ ! -f "$TMPROOT/rc/alerts/authshrink.active" ]; then
  ok "(c 해소) .active 도 지워진다"
else ng "(c 해소) 해소 통보는 갔는데 .active 가 남는다 — 미해소 개수가 안 줄어든다"; fi

# (c2) **옛 회전본이 큰 채로 남아 있는 상태**에서의 truncate — (c) 보다 어려운 쪽이다.
#      "줄었는데 .1 이 오프셋보다 크다" 만 보면 회전으로 오인해 옛 구간을 다시 센다.
AU="$RD/c2.auth.log"; authgen 40 >"$AU"; authgen 200 >"$AU.1"
touch -d '3 days ago' "$AU.1" 2>/dev/null || touch -t 202607290000 "$AU.1" 2>/dev/null
sshrun rc2 "$AU"
echo "$HIT" >>"$AU"; : >"$AU"; sshrun rc2 "$AU"
want "$TMPROOT/rc2.log" 'ALERT authshrink' \
     "(c2) 옛 회전본이 큰 채로 있어도 truncate 를 회전으로 착각하지 않는다" \
     "(c2) 옛 .1 이 오프셋보다 크다는 이유로 흔적 삭제를 회전으로 설명해 버린다"

# (x1) ⛔ SR38-1 — (c2) 와 **완전히 같은 파괴 행위**인데 `.1` 의 mtime 만 새것이다.
#      옛 판정은 mtime 하나를 회전의 충분조건으로 썼다 → `touch` 한 줄에 침묵했다.
#      **mtime 은 공격자가 만드는 값이다.** 위조 비용이 0 인 증거는 증거가 아니다.
AU="$RD/x1.auth.log"; authgen 40 >"$AU"; authgen 200 >"$AU.1"
touch -d '3 days ago' "$AU.1" 2>/dev/null || true
sshrun rx1 "$AU"
echo "$HIT" >>"$AU"; : >"$AU"; touch "$AU.1"          # ← 회전 증거 위조
sshrun rx1 "$AU"
want "$TMPROOT/rx1.log" 'ALERT authshrink' \
     "(x1) ': > auth.log' + 'touch .1'(mtime 위조)에도 흔적 삭제를 잡는다 (SR38-1)" \
     "(x1) touch 한 줄로 회전을 위조하면 침묵한다 — mtime 을 단독 증거로 쓰고 있다"

if [ "$INO_OK" = 1 ]; then
  AU="$RD/d.auth.log"; authgen 40 >"$AU"; sshrun rd "$AU"
  mv "$AU" "$AU.1"; { echo "$HIT"; authgen 200; } >"$AU"; sshrun rd "$AU"
  want "$TMPROOT/rd.log" 'ALERT sshpw' \
       "(d) 회전 뒤 새 파일이 옛 오프셋을 넘게 자라도 앞부분을 건너뛰지 않는다" \
       "(d) 회전 뒤 새 파일 앞부분을 통째로 건너뛴다 — 크기만 보면 회전이 안 보인다"

  # (h) ⛔ CR42-2 (9번째 변이) — `: >` 대신 `rm` 을 쓰면 판정이 뒤집혔다.
  #     inode 가 바뀌었다는 이유만으로 **증거 없이** 회전을 확정했고, 낡은 `.1` 이
  #     오프셋보다 크면 그 꼬리까지 세면서 **완전 침묵**했다. 요약에는
  #     "이번 구간 0건 (기대 0)" 이라는 **적극적인 무사고 선언**이 남았다.
  AU="$RD/h.auth.log"; authgen 40 >"$AU"; authgen 500 >"$AU.1"
  touch -d '3 days ago' "$AU.1" 2>/dev/null || true
  sshrun rh "$AU"
  echo "$HIT" >>"$AU"; rm -f "$AU"; authgen 3 >"$AU"; sshrun rh "$AU"
  want "$TMPROOT/rh.log" 'ALERT authshrink' \
       "(h) 'rm auth.log && 재생성' + 낡은 .1 이 오프셋보다 커도 잡는다 (CR42-2)" \
       "(h) rm 후 재생성이 회전으로 통과한다 — ': >' 는 잡고 rm 은 못 잡는 상태다"
  want "$TMPROOT/rh.log" 'ALERT logblind' "(h) 못 본 구간이 감시불능 사유에도 남는다" \
       "(h) 사라진 구간을 아무 데도 안 남긴다"
  if has "$(cat "$TMPROOT/rh.log" 2>/dev/null)" '이번 구간 0건 (기대 0)'; then
    ng "(h) 침묵한 채 '0건 (기대 0)' 이라는 무사고 선언을 남긴다"
  else ok "(h) '0건 (기대 0)' 이라는 무사고 선언을 하지 않는다"; fi

  # (l) 서버의 **실제 설정**이 delaycompress 라, 회전 직후 한동안 `.1` 은 평문이고
  #     `.2.gz` 가 있다. 즉 (h) 의 조건이 **매주 한동안 항상 성립한다.**
  AU="$RD/l.auth.log"; authgen 40 >"$AU"; authgen 800 >"$AU.1"
  if command -v gzip >/dev/null 2>&1; then gzip -c "$AU.1" >"$AU.2.gz" 2>/dev/null || true; fi
  touch -d '3 days ago' "$AU.1" "$AU.2.gz" 2>/dev/null || true
  sshrun rl "$AU"
  echo "$HIT" >>"$AU"; rm -f "$AU"; authgen 3 >"$AU"; sshrun rl "$AU"
  want "$TMPROOT/rl.log" 'ALERT authshrink' \
       "(l) 서버형 delaycompress(.1 평문 + .2.gz) 상태에서도 rm+재생성을 잡는다 (CR42-2)" \
       "(l) 서버의 평상시 파일 배치에서 흔적 삭제가 그대로 통과한다"

  # (x4) ⛔ SR38-2 — 회전본은 만들어진 뒤 **변하지 않는다.** 그 불변식을 아무도 안 봤다.
  #      `sed -i` 는 임시파일을 만들어 rename 하므로 **inode 가 바뀐다** —
  #      "같은 inode 인데 작아졌다" 만 봤다면 이것도 놓쳤을 것이다(직접 확인했다).
  #      그래서 **회전이 아닌데 `.1` 의 정체가 바뀌었다**도 함께 본다.
  AU="$RD/x4.auth.log"; authgen 40 >"$AU"; sshrun rx4 "$AU"
  mv "$AU" "$AU.1"; authgen 3 >"$AU"; sshrun rx4 "$AU"      # 정상 회전 (여기까지는 조용)
  if command -v sed >/dev/null 2>&1 && sed -i '1,20d' "$AU.1" 2>/dev/null; then
    sshrun rx4 "$AU"
    want "$TMPROOT/rx4.log" 'ALERT authedit' \
         "(x4) 회전 뒤 .1 안의 줄을 지우면 잡는다 — 회전본은 변하지 않는다 (SR38-2)" \
         "(x4) 회전본을 편집해도 조용하다 — .1 은 크기만 보고 내용·정체는 안 본다"
  else skip "(x4) sed -i 를 못 써서 회전본 편집을 만들 수 없다"; fi
else
  skip "(d)(h)(l)(x4) — 이 파일시스템이 inode 불변식을 지원하지 않는다. 리눅스(서버)에서 확인할 것"
fi

# (x6) ⛔ SR38-3 (최우선) — **공격 없이 고장만으로도 난다.**
#      rsyslog 가 멈추면 auth.log 는 그대로 있고 줄지도 않는다. 옛 코드는 그 상태에서
#      "SSH : 비밀번호 로그인 성공 이번 구간 0건 (기대 0)" 이라고 적었다 —
#      **"봤고 괜찮다"** 이다. 실제로는 아무것도 못 본 것이다. check_logfresh 는
#      ACCESS_LOG 만 봐서 이 자리를 아무도 안 지켰다.
AU="$RD/x6.auth.log"; authgen 40 >"$AU"; sshrun rx6 "$AU"
if touch -d '5 days ago' "$AU" 2>/dev/null; then
  sshrun rx6 "$AU"
  want "$TMPROOT/rx6.log" 'ALERT authfresh' \
       "(x6) auth.log 가 5일째 안 늘면 경보 — 감시가 무효인 상태를 스스로 신고한다 (SR38-3)" \
       "(x6) 로그가 얼어붙었는데 조용하다 — rsyslog 정지 하나로 T2 가 꺼진다"
  want "$TMPROOT/rx6.log" 'ALERT logblind' "(x6) 얼어붙은 로그가 감시불능 사유에도 남는다" \
       "(x6) 못 보는 상태인데 감시불능 사유에 안 실린다"
  if has "$(cat "$TMPROOT/rx6.log" 2>/dev/null)" '이번 구간 0건 (기대 0)'; then
    ng "(x6) 얼어붙은 로그의 0건을 '기대 0' 이라고 적는다 — '못 봤다'를 '괜찮다'로 말한다"
  else ok "(x6) 얼어붙은 동안의 0건을 '기대 0' 이라 적지 않는다 (못 본 것이라고 적는다)"; fi
  # (x6 해소) 로그가 다시 흐르면 꺼지는가 — clear 경로를 관문이 **행동으로** 본다(CR44-2 §10).
  X6PRE=$(wc -l <"$TMPROOT/rx6.log" 2>/dev/null); X6PRE=${X6PRE:-0}
  authgen 4 >>"$AU"; touch "$AU" 2>/dev/null
  sshrun rx6 "$AU"
  tail -n +$((X6PRE + 1)) "$TMPROOT/rx6.log" >"$TMPROOT/rx6.after.log" 2>/dev/null
  want "$TMPROOT/rx6.after.log" 'ALERT-CLEARED authfresh' \
       "(x6 해소) auth.log 가 다시 기록되면 authfresh 가 꺼진다 (rsyslog 를 살린 뒤 표시가 실제로 풀린다)" \
       "(x6 해소) rsyslog 를 되살려도 authfresh 가 안 꺼진다 — 요약 머리말이 계속 미해소다"
  # 양성 대조군 — 신선하면 안 울어야 한다(안 그러면 5분마다 운다)
  touch "$AU"; sshrun rx6b "$AU"
  avoid "$TMPROOT/rx6b.log" 'ALERT authfresh' \
        "(x6 대조군) 방금 기록된 auth.log 에는 신선도 경보가 없다" \
        "정상 auth.log 인데 신선도 경보가 뜬다 — 5분마다 운다"
else skip "(x6) touch -d 를 못 써서 로그 동결을 만들 수 없다"; fi

AU="$RD/e.auth.log"; authgen 40 >"$AU"; sshrun re "$AU"; authgen 5 >>"$AU"; sshrun re "$AU"
avoid "$TMPROOT/re.log" 'ALERT sshpw\|ALERT authshrink\|ALERT authedit\|ALERT authfresh\|ALERT authfake' \
      "(대조군) 정상 증가에는 아무 경보도 없다" "(대조군) 정상 증가인데 경보가 뜬다"

AU="$RD/f.auth.log"; authgen 40 >"$AU"; sshrun rf "$AU"; mv "$AU" "$AU.1"; authgen 3 >"$AU"; sshrun rf "$AU"
avoid "$TMPROOT/rf.log" 'ALERT sshpw\|ALERT authshrink\|ALERT authedit\|ALERT authfresh\|ALERT authfake' \
      "(대조군) 침입 없는 로테이션에는 경보가 없다" \
      "(대조군) 침입 없는 평범한 로테이션인데 경보가 뜬다 — 매주 운다"

# (대조군 m) **서버의 실제 설정 그대로** — delaycompress 회전을 두 번 연속.
#   여기서 울면 매주 일요일마다 오탐이 간다. 새 판정(강한 증거)의 진짜 시험대다.
AU="$RD/m.auth.log"; authgen 40 >"$AU"; authgen 300 >"$AU.1"
if command -v gzip >/dev/null 2>&1; then gzip -c "$AU.1" >"$AU.2.gz" 2>/dev/null || true; fi
touch -d '6 days ago' "$AU.1" 2>/dev/null || true
sshrun rm1 "$AU"
authgen 10 >>"$AU"; sshrun rm1 "$AU"                        # 평상시 증가
[ -f "$AU.2.gz" ] && mv "$AU.2.gz" "$AU.3.gz" 2>/dev/null
if command -v gzip >/dev/null 2>&1; then gzip -c "$AU.1" >"$AU.2.gz" 2>/dev/null && rm -f "$AU.1"; fi
mv "$AU" "$AU.1"; authgen 2 >"$AU"; sshrun rm1 "$AU"        # 주간 회전 (delaycompress)
authgen 7 >>"$AU"; sshrun rm1 "$AU"                         # 회전 뒤 평상시 증가
avoid "$TMPROOT/rm1.log" 'ALERT sshpw\|ALERT authshrink\|ALERT authedit\|ALERT authfresh\|ALERT authfake' \
      "(대조군 m) 서버 설정 그대로의 delaycompress 주간 회전에도 완전 침묵" \
      "(대조군 m) 평범한 주간 회전에 경보가 난다 — 매주 오탐이 간다"

# ===========================================================================
# ⛔ **SR39-1 / SR39-2 — 메타데이터만으로는 못 보는 칸.** 여기부터가 이번 라운드다.
#    지금까지의 증거는 전부 크기·inode·mtime 이다. 그런데 공격자가 바꾸는 것은
#    *우리가 아직 읽지 않은 구간의 내용*이고, 그건 같은 파일 안에 반증할 값이 없다.
#    두 방향으로 닫는다: ① mtime 과 크기의 **모순**을 본다 ② **출처를 하나 더** 본다.
# ===========================================================================

# (x10) SR39-2 — rsyslog 정지(크기 그대로) + `touch` 로 신선도 증거만 위조한다.
#       ⓪ 의 증거가 mtime 하나뿐이라, 그 하나를 위조하면 authfresh 도 blind 도 안 뜨고
#       **완전히 침묵**했다. 같은 라운드가 회전 판정에서는 *"mtime 은 위조 비용이 0이라
#       단독으로 쓰지 않는다"* 고 못 박아 놓고 ⓪ 에는 그 원칙을 안 썼다.
AU="$RD/x10.auth.log"; authgen 40 >"$AU"; sshrun rx10 "$AU"     # 기준값(off·mtime 기록)
if touch -d '2 hours ago' "$AU" 2>/dev/null; then
  # mtime 을 과거로 — 여기서는 울지 않는다(전진이 아니다). 이 실행이 기준 mtime 이 된다.
  sshrun rx10 "$AU"
  touch -d '1 hour ago' "$AU" 2>/dev/null              # 크기 그대로 · mtime 만 **앞으로**
  X10PRE=$(wc -l <"$TMPROOT/rx10.log" 2>/dev/null); X10PRE=${X10PRE:-0}
  sshrun rx10 "$AU"
  tail -n +$((X10PRE + 1)) "$TMPROOT/rx10.log" >"$TMPROOT/rx10.last.log" 2>/dev/null
  want "$TMPROOT/rx10.last.log" 'ALERT authfake' \
       "(x10) 동결 + touch(신선도 위조)를 잡는다 — mtime 은 새것인데 크기가 그대로다 (SR39-2)" \
       "(x10) touch 한 줄로 동결을 감추면 침묵한다 — ⓪ 이 mtime 을 단독 증거로 쓰고 있다"
  # ⚠️ **이번 실행분만** 본다. 감시 로그는 누적이라, 앞선 정상 실행이 정당하게 적은
  #    '기대 0' 이 섞여 검사가 붉어진다(그렇게 짜서 한 번 붉었다 — 코드가 아니라
  #    검사의 잘못이었다. 같은 함정이 (h)(x6)에는 없었을 뿐이다).
  if has "$(cat "$TMPROOT/rx10.last.log" 2>/dev/null)" '이번 구간 0건 (기대 0)'; then
    ng "(x10) 위조된 신선도 아래의 0건을 '기대 0' 이라고 적는다"
  else ok "(x10) 위조가 의심되는 구간의 0건을 '기대 0' 이라 적지 않는다"; fi
else skip "(x10) touch -d 를 못 써서 동결+위조를 만들 수 없다"; fi

# (x9) SR39-1 — **침입 줄을 같은 길이의 평범한 줄로 in-place 덮어쓴다.**
#      크기·inode 가 **둘 다 보존**되므로 지금까지의 증거는 전부 통과한다.
#      바뀌는 것은 mtime 하나뿐이고, 그 하나가 유일한 증거다.
if command -v dd >/dev/null 2>&1; then
  AU="$RD/x9.auth.log"; authgen 30 >"$AU"; echo "$HIT" >>"$AU"
  X9OFF=$(( $(stat -c %s "$AU" 2>/dev/null || echo 0) - ${#HIT} - 1 ))
  # ⛔ **이 검사의 초록이 운(運)이었다 — 서버에서 붉었다(2026-08-02 실측).**
  #    ⓪b 의 조건은 `mtime(초 단위) 이 앞으로 갔는가` 인데, 기준값 실행과 dd 가
  #    **같은 초** 안에서 끝나면 그 조건이 성립하지 않는다. 리눅스에서 실제로 그랬고
  #    (02:19:16.361 → 02:19:16.541 · 둘 다 %Y=1785604756) 이 검사는 FAIL 했다.
  #    윈도우에서는 느려서 초 경계를 우연히 넘었고, 그래서 통과했다.
  #    → 기준 mtime 을 과거로 못 박아 시나리오를 **결정적으로** 만든다(x10 과 같은 수법).
  #      운영에서는 폴링 간격이 5분이라 이 문제가 없다 — 이것은 하네스의 결함이었다.
  touch -d '2 minutes ago' "$AU" 2>/dev/null || true
  X9SZ=$(stat -c %s "$AU" 2>/dev/null); X9INO=$(stat -c %i "$AU" 2>/dev/null)
  X9MT=$(stat -c %Y "$AU" 2>/dev/null)
  sshrun rx9 "$AU"                                     # 기준값 (누적 1건은 여기서 신고된다)
  X9NEW=$(printf '%s' "$HIT" | sed 's/Accepted password/Failed password0/')
  printf '%s' "$X9NEW" | dd of="$AU" bs=1 seek="$X9OFF" conv=notrunc status=none 2>/dev/null
  X9SZ2=$(stat -c %s "$AU" 2>/dev/null); X9INO2=$(stat -c %i "$AU" 2>/dev/null)
  X9MT2=$(stat -c %Y "$AU" 2>/dev/null)
  if [ "$X9SZ" != "$X9SZ2" ] || [ "$X9INO" != "$X9INO2" ]; then
    harn "(x9) 같은 길이 덮어쓰기" "dd conv=notrunc 가 크기(${X9SZ}→${X9SZ2})나 inode 를 바꿨다 — 시나리오를 못 만들었다"
  elif ! nz "$X9MT" "$X9MT2" || ! [ "$X9MT2" -gt "$X9MT" ] 2>/dev/null; then
    # 픽스처가 시나리오를 못 만든 것을 **검사 실패로 보고하지 않는다**(CR44-3 ② 와 같은 원칙).
    harn "(x9) 같은 길이 덮어쓰기" "mtime 이 앞으로 가지 않았다(${X9MT:-?}→${X9MT2:-?}) — touch -d 가 안 먹거나 초 해상도가 부족하다. **검사 결과가 아니다**"
  else
    sshrun rx9 "$AU"
    want "$TMPROOT/rx9.log" 'ALERT authfake' \
         "(x9) 같은 길이 in-place 덮어쓰기를 잡는다 — 크기·inode 가 보존돼도 mtime 은 못 속인다 (SR39-1)" \
         "(x9) 침입 줄을 같은 길이로 덮어쓰면 완전 침묵한다 — 메타데이터가 전부 보존된다"
  fi
else skip "(x9) dd 가 없어 in-place 덮어쓰기를 만들 수 없다"; fi

# (x9b) ⛔ SR40-3 — **위 (x9) 의 사정거리를 정확히 적는다.**
#   ⓪b 는 `size == off`, 즉 **창 안에 auth.log 가 한 바이트도 안 늘었을 때만** 발동한다.
#   그런데 서버는 `Failed password` 가 분당 ~9줄 쌓여 5분 창이 **항상** 자란다.
#   즉 **운영 조건의 x9 는 여기서 안 잡힌다.** 그것을 말이 아니라 검사로 못 박는다 —
#   같은 공격을 "자라는 로그" 위에서 재현하고, `authfake` 가 안 뜨는 것을 확인한다.
#   (그럼 무엇이 잡는가? 아래 ㉯ 의 journald 교차 하나뿐이다. 그래서 그 교차가
#    **살아 있는 척만 하는 상태**를 SR40-1 검사가 따로 본다.)
if command -v dd >/dev/null 2>&1; then
  AU="$RD/x9b.auth.log"; authgen 30 >"$AU"; echo "$HIT" >>"$AU"
  X9BOFF=$(( $(stat -c %s "$AU" 2>/dev/null || echo 0) - ${#HIT} - 1 ))
  touch -d '2 minutes ago' "$AU" 2>/dev/null || true
  sshrun rx9b "$AU"                                    # 기준값
  X9BNEW=$(printf '%s' "$HIT" | sed 's/Accepted password/Failed password0/')
  printf '%s' "$X9BNEW" | dd of="$AU" bs=1 seek="$X9BOFF" conv=notrunc status=none 2>/dev/null
  authgen 9 >>"$AU"                                    # ← 운영 조건: 같은 창에 로그가 자란다
  X9BPRE=$(wc -l <"$TMPROOT/rx9b.log" 2>/dev/null); X9BPRE=${X9BPRE:-0}
  sshrun rx9b "$AU"
  tail -n +$((X9BPRE + 1)) "$TMPROOT/rx9b.log" >"$TMPROOT/rx9b.last.log" 2>/dev/null
  avoid "$TMPROOT/rx9b.last.log" 'ALERT authfake' \
        "(x9b) 로그가 자라는 창에서는 authfake 가 뜨지 않는다 — 사정거리를 사실대로 안다 (SR40-3)" \
        "(x9b) authfake 가 자라는 로그에서도 뜬다 — 그 문턱이 바뀌었으니 오탐 근거를 다시 재야 한다"
else skip "(x9b) dd 가 없어 운영조건 in-place 덮어쓰기를 만들 수 없다"; fi

# (x11) SR39-3 — `: > auth.log` + 가짜 `.1.gz`.
#       이 서버는 delaycompress 라 회전하면 `.1` 이 `.2` 로 밀린다 — **`.1.gz` 라는 상태가 없다.**
#       그런데 예전 코드는 그것을 약한 증거(`rotated_gz`)로 **세어 주고** 넘어갔고,
#       사람이 받는 이름은 "감시 불능" 이라 흔적 삭제로 읽히지 않았다.
if [ "$INO_OK" = 1 ] && command -v gzip >/dev/null 2>&1; then
  AU="$RD/x11.auth.log"; authgen 40 >"$AU"; authgen 300 >"$AU.1"
  touch -d '3 days ago' "$AU.1" 2>/dev/null || true
  sshrun rx11 "$AU"                                    # 평문 .1 을 추적하는 상태를 만든다
  : >"$AU"; rm -f "$AU.1"; authgen 300 | gzip >"$AU.1.gz" 2>/dev/null
  sshrun rx11 "$AU"
  want "$TMPROOT/rx11.log" 'ALERT authedit' \
       "(x11) 추적하던 평문 .1 이 사라지고 .1.gz 만 남으면 잡는다 (SR39-3)" \
       "(x11) ': >' + 가짜 .1.gz 가 '약한 증거 회전' 으로 통과한다 — 흔적 삭제가 감시불능 이름으로 묻힌다"

  # (x11 대조군) `compress`(delaycompress 없음) 서버 — 평문 `.1` 이 애초에 없다.
  #   조건이 **설정이 아니라 관측**이라서 여기서는 조용해야 한다. 아니면 오탐 기계다.
  AU="$RD/x11b.auth.log"; authgen 40 >"$AU"; authgen 300 | gzip >"$AU.1.gz"
  touch -d '3 days ago' "$AU.1.gz" 2>/dev/null || true
  sshrun rx11b "$AU"
  authgen 12 >>"$AU"; sshrun rx11b "$AU"
  authgen 340 | gzip >"$AU.1.gz"; : >"$AU"; authgen 3 >"$AU"; sshrun rx11b "$AU"
  avoid "$TMPROOT/rx11b.log" 'ALERT authedit' \
        "(x11 대조군) compress 서버(평문 .1 이 없는 곳)에서는 오탐이 없다" \
        "(x11 대조군) 평문 .1 을 본 적도 없는데 authedit 이 뜬다 — 매주 오탐이 간다"
else skip "(x11) inode 불변식 또는 gzip 이 없어 압축회전 위조를 만들 수 없다"; fi

# --- SR39-1 ㉯ **두 번째 출처(journald) 교차** --------------------------------
#   메타데이터로 못 보는 칸은 회피 표를 늘려서 못 닫는다. 출처를 하나 더 본다.
#   여기서는 실제 저널을 읽지 않는다 — `journalctl` 을 가짜로 PATH 앞에 둔다
#   (그래야 systemd 없는 곳에서도 이 검사가 **돈다**. 못 도는 검사는 없는 검사다).
#
# ⛔ **이 구획이 서버(리눅스)에서 붉었다 — 그리고 그 빨강이 옳았다(2026-08-02).**
#    예전 ③ 은 "journald 가 사라진" 상태를 **PATH 에서 가짜를 빼는 것**으로 만들었는데,
#    서버에는 `/usr/bin/journalctl` 이 **진짜로 있다**. 그러니 `jd_ok` 는 1 그대로였고
#    경보가 안 떴다. 윈도우에서는 진짜가 없어서 우연히 통과했다 —
#    **관문의 초록이 환경 덕이었던 자리다.**
#    → 이제 "사라짐"을 **응답 실패**로 만든다(`journalctl -n 1` 이 실패하는 가짜를
#      PATH 앞에 둔다). 그것이 monitor.sh 가 실제로 보는 조건(`jd_ok=0`)이고,
#      진짜 journalctl 이 있든 없든 두 환경에서 똑같이 재현된다.
JBIN="$TMPROOT/jbin"; mkdir -p "$JBIN"
{ echo '#!/bin/sh'
  echo 'case "$*" in *"-n 1"*) exit 0 ;; esac'
  # ⛔ CR45-1 — monitor.sh 는 **반드시 비어야 하는 창**(미래 60초)을 한 번 물어서
  #    "빈 결과 = 빈 출력" 인지 확인한다. 그 프로브만 `--until` 을 쓴다.
  #    가짜가 창을 무시하고 픽스처를 뱉으면 프로브가 늘 non-empty 가 되고,
  #    그러면 **가짜 탓에 모든 교차 판정이 보류된다**(실제로 그렇게 붉었다).
  #    미래 창은 현실에서도 비어 있다 — 그대로 흉내낸다.
  # 미래 창(프로브)은 현실에서도 비어 있다. 창을 무시하고 픽스처를 뱉으면
  # 프로브가 늘 non-empty 가 되어 **가짜 탓에 모든 교차 판정이 보류된다**(실제로 그랬다).
  echo 'case "$*" in *--until*) FAKE_JOURNAL="" ;; esac'
  echo 'if [ -n "${FAKE_JOURNAL:-}" ] && [ -s "$FAKE_JOURNAL" ]; then'
  echo '  cat "$FAKE_JOURNAL"; exit 0'
  echo 'fi'
  # ⛔ CR45-1 — **가짜가 `-o cat` 을 실제로 존중한다.** 예전 가짜는 형식 플래그를 통째로
  #    무시해 "결과가 비면 늘 빈 출력" 이었다. 그러면 `-o cat` 을 빼는 변이가
  #    **픽스처 상에서 아무 일도 일으키지 않아** 관문이 그 변이를 못 본다(CR45-1 재현).
  #    진짜는 `-o cat` 이면 0바이트, 없으면 `-- No entries --` 다(실측). 그대로 흉내낸다.
  echo 'case "$*" in *"-o cat"*) exit 0 ;; esac'
  echo 'echo "-- No entries --"'
  echo 'exit 0'
} >"$JBIN/journalctl"
chmod +x "$JBIN/journalctl" 2>/dev/null
# 죽은 journald — `command -v` 로는 보이는데 `-n 1` 이 실패한다(= jd_ok 0).
JDEAD="$TMPROOT/jdead"; mkdir -p "$JDEAD"
{ echo '#!/bin/sh'; echo 'exit 1'; } >"$JDEAD/journalctl"
chmod +x "$JDEAD/journalctl" 2>/dev/null
JFIX="$TMPROOT/journal.txt"; : >"$JFIX"
JFIX2="$TMPROOT/journal-normal.txt"           # 평범한 ssh 메시지(성공 0건) → jtot > 0
: >"$TMPROOT/none.txt"                        # 아무것도 안 보이는 저널
# journald 가 정상일 때 창 안에 보이는 ssh 유닛 메시지. 서버 실측으로 5분 창 최소 21줄.
jgen() { local n=$1 i=1; while [ "$i" -le "$n" ]; do echo "Failed password for root from 1.2.3.4 port 1 ssh2"; i=$((i + 1)); done; }
# auth.log 가 **sshd 없이** 자라는 정상 경로(실측: CRON · systemd-logind · systemd-user).
crongen() { local n=$1 i=1; while [ "$i" -le "$n" ]; do echo "Aug  1 07:00:00 h CRON[$i]: pam_unix(cron:session): session opened for user root(uid=0) by (uid=0)"; i=$((i + 1)); done; }
jgen 60 >"$JFIX2"
sshrunj() { # $1=상태이름 $2=auth.log $3=저널 픽스처 [$4=PATH 앞에 둘 디렉터리]
  local st="$TMPROOT/$1"
  run_mon "$st" --fast PATH="${4:-$JBIN}:$PATH" FAKE_JOURNAL="${3:-/nonexistent}" \
    RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
    RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
    RE_MON_AUTH_LOG="$2" >/dev/null 2>&1
}
# 창 길이를 **결정적으로** 만든다. monitor.sh 는 `now - kv/sshpw_at` 을 창으로 쓰는데
# 자체검사는 실행을 1초 간격으로 이어 붙이므로 그냥 두면 창이 늘 몇 초다.
# ⚠️ 여기서 임계(JD_MIN_WINDOW)를 env 로 낮추지 **않는다** — 그러면 출하되는 기본값이
#    아니라 우리가 고른 값을 시험하게 된다. 상태 파일 쪽을 옮긴다.
age_window() { printf '%s' "$(( $(date +%s) - ${2:-300} ))" >"$TMPROOT/$1/kv/sshpw_at" 2>/dev/null; }

# ⛔ CR44-3 ② — **픽스처가 기대대로 도는지 먼저 확인한다.** 예전에는 `[ -x ]` 만 봤고,
#    파일이 실행은 되는데 출력이 안 나오는 경우를 **검사 실패**로 보고했다(리뷰 실측:
#    M1 관문 실행에서 교차 2건이 붉었는데 원인은 가짜 바이너리였다). 하네스 고장은
#    ok 도 ng 도 아니라 HARN 이다.
JPROBE="$TMPROOT/jprobe.txt"; printf 'probe-line\n' >"$JPROBE"
JOK=0
if PATH="$JBIN:$PATH" journalctl -n 1 --no-pager >/dev/null 2>&1 &&
   [ "$(PATH="$JBIN:$PATH" FAKE_JOURNAL="$JPROBE" journalctl -u ssh --since '@0' --no-pager -o cat 2>/dev/null)" = "probe-line" ] &&
   ! PATH="$JDEAD:$PATH" journalctl -n 1 --no-pager >/dev/null 2>&1; then
  JOK=1
fi
if [ "$JOK" != 1 ]; then
  harn "(교차) journald 시나리오 전체" "가짜 journalctl 이 기대대로 동작하지 않는다(응답·픽스처·죽음 중 하나) — **검사 결과가 아니다**(하네스·환경 문제)"
else
  # ① 두 출처가 어긋난다 — auth.log 는 조용한데 journald 는 성공 로그인을 본다(= x9 의 잔상)
  #    ⚠️ **이것이 운영 조건의 x9 다**(위 x9b 참조). auth.log 가 자라는 창에서 ⓪b 는
  #       발동하지 않으므로, 운영에서 그 공격을 반증하는 것은 이 교차 하나뿐이다.
  # ⚠️ **저널 픽스처는 `-o cat` 모양이어야 한다** — syslog 접두부(`… h sshd[9]: `)가 없다.
  #    예전에는 여기에 auth.log 형식인 `$HIT` 를 그대로 넣었다. 앵커가 없던 시절에는
  #    아무 데나 걸려서 통과했지만, 그건 **픽스처가 현실과 다른 것을 관문이 못 보던 것**이다
  #    (SR41-2 로 앵커를 달자마자 이 두 줄이 붉어졌다 — 검사가 옳았다).
  #    `jgen` 이 만드는 줄은 이미 접두부가 없다. 성공줄도 같은 모양으로 맞춘다.
  jgen 40 >"$JFIX"; echo "$HIT_JD" >>"$JFIX"
  AU="$RD/j1.auth.log"; authgen 40 >"$AU"
  sshrunj rj1 "$AU" "$TMPROOT/none.txt"      # 기준값 (저널 비어 있음)
  authgen 5 >>"$AU"; age_window rj1 300
  sshrunj rj1 "$AU" "$JFIX"
  want "$TMPROOT/rj1.log" 'ALERT sshpw' \
       "(교차) auth.log 는 0건인데 journald 가 성공 로그인을 보면 경보 (SR39-1 · 두 번째 출처)" \
       "(교차) auth.log 만 믿는다 — 같은 길이로 덮어쓴 침입을 반증할 방법이 없다"
  if has "$(cat "$TMPROOT/rj1.log" 2>/dev/null)" '두 출처의 수가 다르다'; then
    ok "(교차) 알림 본문이 '두 출처의 수가 다르다' 를 말한다 (사람이 무엇을 볼지 안다)"
  else ng "(교차) 두 출처가 어긋난 사실이 알림 본문에 없다"; fi

  # ② 대조군 — 두 출처가 **둘 다 살아 있고** 성공이 0건이면 조용해야 한다.
  #    ⚠️ 예전 대조군은 저널을 **빈 것**으로 두고 "두 출처가 다 0 이면 침묵" 을 확인했다.
  #       그런데 그 상태는 SR40-1 의 공격 성공 상태(j2)와 **글자 그대로 같다** —
  #       관문이 "오탐 0" 이라고 인증하던 것이 곧 "교차가 죽었다" 였다.
  #       그래서 정상 대조군은 이제 journald 가 **실제로 보이는** 상태로 만든다.
  AU="$RD/j2.auth.log"; authgen 40 >"$AU"
  sshrunj rj2 "$AU" "$JFIX2"
  authgen 5 >>"$AU"; age_window rj2 300; sshrunj rj2 "$AU" "$JFIX2"
  authgen 5 >>"$AU"; age_window rj2 300; sshrunj rj2 "$AU" "$JFIX2"
  avoid "$TMPROOT/rj2.log" 'ALERT sshpw\|ALERT sshjournal' \
        "(교차 대조군) 두 출처가 다 살아 있고 성공이 0건이면 침묵 (오탐 0)" \
        "(교차 대조군) 정상인데 교차 검사가 운다 — 5분마다 간다"

  # ③ ⛔ SR40-1 — **journalctl 은 응답하는데 ssh 조회만 0줄.**
  #    `journalctl --rotate --vacuum-time=1s` · `Storage=none` · ssh 유닛 이름 변경/
  #    소켓 활성화 · 저널 손상이 전부 이 모양이다. 예전에는 **완전 침묵**이었고,
  #    요약은 `journald 같은 구간 0건 (기대 0/0)` 이라며 무사고를 선언했다.
  AU="$RD/j3.auth.log"; authgen 40 >"$AU"
  sshrunj rj3 "$AU" "$JFIX2"                        # 기준값 (journald 정상)
  authgen 20 >>"$AU"; age_window rj3 300
  sshrunj rj3 "$AU" "$TMPROOT/none.txt"             # 응답 O · ssh 줄 0
  want "$TMPROOT/rj3.log" 'ALERT sshjournal' \
       "(교차 j2) journalctl 은 응답하는데 ssh 조회가 0줄이면 경보 (SR40-1 — 두 번째 출처가 눈만 감았다)" \
       "(교차 j2) 저널을 지워도 완전 침묵한다 — 운영에서 x9 를 잡는 유일한 수단이 조용히 없어진다"
  want "$TMPROOT/rj3.log" '교차 실질 불가' \
       "(교차 j2) 요약이 '못 봤다'고 적는다 — 0줄을 '기대 0/0' 이라 쓰지 않는다" \
       "(교차 j2) 눈이 먼 구간의 0건을 '기대 0/0' 이라고 적는다 (적극적인 무사고 선언)"
  want "$TMPROOT/rj3.log" 'ALERT logblind' \
       "(교차 j2) 그 사유가 감시불능 목록에도 남는다" \
       "(교차 j2) 교차가 죽었는데 감시불능 사유에 안 실린다"

  # ③ 대조군 (가) — **창이 짧으면 판정하지 않는다.** 실측 근거(서버 · 24시간):
  #    ssh 유닛 메시지가 5분 버킷 288개 중 0줄인 버킷은 **0개**(최소 21 · 평균 101)지만,
  #    **1분 버킷은 1,440개 중 30개가 0줄**이다. 손으로 연달아 돌릴 때가 그 창이다.
  AU="$RD/j4.auth.log"; authgen 40 >"$AU"
  sshrunj rj4 "$AU" "$JFIX2"
  authgen 20 >>"$AU"; sshrunj rj4 "$AU" "$TMPROOT/none.txt"   # 창 = 몇 초 (age_window 안 씀)
  avoid "$TMPROOT/rj4.log" 'ALERT sshjournal' \
        "(교차 j2 대조군) 창이 짧으면 0줄을 사고로 보지 않는다 (연달아 돌려도 안 운다)" \
        "(교차 j2 대조군) 짧은 창의 0줄에 운다 — 손으로 두 번 돌리면 경보가 간다"

  # ③ 대조군 (나) — auth.log 가 **sshd 아닌 줄**로만 자란 경우. auth.log 에는
  #    CRON·systemd-logind·systemd-user 가 함께 쌓인다(실측: 최근 5,000줄 중 79줄).
  #    ssh 트래픽이 없는 조용한 창에서 journald 가 0줄인 것은 **정상**이다.
  AU="$RD/j5.auth.log"; authgen 40 >"$AU"
  sshrunj rj5 "$AU" "$JFIX2"
  crongen 20 >>"$AU"; age_window rj5 300
  sshrunj rj5 "$AU" "$TMPROOT/none.txt"
  avoid "$TMPROOT/rj5.log" 'ALERT sshjournal' \
        "(교차 j2 대조군) sshd 가 한 줄도 안 쓴 창에서는 journald 0줄이 정상이다 (오탐 0)" \
        "(교차 j2 대조군) ssh 트래픽이 없는 창에 운다 — 조용한 시간마다 경보가 간다"

  # ④ 두 번째 출처가 **아예 응답하지 않는** 경우 — 그것 자체가 신호다. journald 도
  #    root 면 지울 수 있다. 이 교차는 침입을 불가능하게 만들지 않고 비용을 올릴 뿐이고,
  #    그 비용을 공격자가 치렀다는 사실은 우리가 알아야 한다.
  AU="$RD/j6.auth.log"; authgen 40 >"$AU"
  sshrunj rj6 "$AU" "$JFIX2"                            # 기준값
  authgen 5 >>"$AU"; age_window rj6 300
  sshrunj rj6 "$AU" "$JFIX2"                            # 정상 1회 (sshpw_jd=1 이 된다)
  authgen 5 >>"$AU"; age_window rj6 300
  sshrunj rj6 "$AU" "$JFIX2" "$JDEAD"                   # journalctl 이 응답하지 않는다
  want "$TMPROOT/rj6.log" 'ALERT sshjournal' \
       "(교차) 어제까지 있던 두 번째 출처가 응답을 멈추면 경보 — 위험수용의 조건이 조용히 꺼지지 않는다" \
       "(교차) journald 가 사라져도 아무 말이 없다 — 교차 검증이 조용히 없어진다"

  # ⑤ ⛔ CR44-1 — **해소 경로.** 형제 `authfresh` 는 꺼지는데 `sshjournal` 만 안 꺼졌다.
  #    그러면 journald 가 한 번 흔들린 뒤로 일일 요약 머리말이 영영 `미해소 (sshjournal)`
  #    이고, 안 꺼지는 경보는 곧 무시되는 경보다.
  #    ⚠️ 그런데 **아무 때나 꺼져도 안 된다** — 응답만 하고 0줄인 상태에서 끄면
  #       그것이 CR40-2 가 막은 거짓 해소다. 두 가지를 함께 본다(부를 자격 / 부를 의무).
  RJ6PRE=$(wc -l <"$TMPROOT/rj6.log" 2>/dev/null); RJ6PRE=${RJ6PRE:-0}
  authgen 20 >>"$AU"; age_window rj6 300
  sshrunj rj6 "$AU" "$TMPROOT/none.txt"                 # 돌아왔지만 ssh 줄은 0 (눈만 뜬 상태)
  tail -n +$((RJ6PRE + 1)) "$TMPROOT/rj6.log" >"$TMPROOT/rj6.blind.log" 2>/dev/null
  avoid "$TMPROOT/rj6.blind.log" 'ALERT-CLEARED sshjournal' \
        "(교차 해소) 응답만 하고 ssh 줄이 0 이면 **끄지 않는다** (거짓 해소 방지 · CR40-2)" \
        "(교차 해소) 눈이 먼 채로 해소 통보가 나간다 — 사람은 문제가 풀린 줄 안다"
  if [ -f "$TMPROOT/rj6/alerts/sshjournal.active" ]; then
    ok "(교차 해소) 그동안 경보가 켜진 채로 남는다 (.active 생존 · 요약 머리말이 미해소를 계속 말한다)"
  else
    ng "(교차 해소) 눈이 먼 상태인데 .active 가 사라졌다 — 미해소 표시가 없어진다"
  fi
  RJ6PRE2=$(wc -l <"$TMPROOT/rj6.log" 2>/dev/null); RJ6PRE2=${RJ6PRE2:-0}
  authgen 20 >>"$AU"; age_window rj6 300
  sshrunj rj6 "$AU" "$JFIX2"                            # 교차가 실제로 돌아왔다
  tail -n +$((RJ6PRE2 + 1)) "$TMPROOT/rj6.log" >"$TMPROOT/rj6.ok.log" 2>/dev/null
  want "$TMPROOT/rj6.ok.log" 'ALERT-CLEARED sshjournal' \
       "(교차 해소) 교차가 실제로 돌아오면 경보가 꺼진다 (CR44-1)" \
       "(교차 해소) journald 가 복구돼도 sshjournal 이 영영 안 꺼진다 — 요약 머리말이 계속 미해소다"
  if [ ! -f "$TMPROOT/rj6/alerts/sshjournal.active" ]; then
    ok "(교차 해소) .active 도 지워진다 (다음에 또 나면 새 사건으로 온다)"
  else
    ng "(교차 해소) 해소 통보는 갔는데 .active 가 남는다"
  fi

  # ⑥ ⛔ CR45-1 — **"빈 결과"를 빈 출력으로 안 주는 journalctl.**
  #    위 ③(j2)의 눈멂 탐지는 전부 `jtot == 0` 에 걸려 있고, 그 0 은 `-o cat` 이
  #    "해당 없음"을 0바이트로 준다는 데 걸려 있다. 실측(2026-08-03 · 서버 systemd 249):
  #      journalctl -u ssh --since @<미래> -o cat        → 0바이트
  #      journalctl -u ssh --since @<미래>               → `-- No entries --` (stdout!)
  #    즉 누가 디버깅하려고 `-o cat` 을 빼면 `jtot` 이 늘 1 이상이 되어
  #    **③ 이 영원히 발동하지 않는다.** 그런데 이 자체검사의 가짜 journalctl 은
  #    빈 출력을 주므로 **그 상태에서도 전부 초록이다** —
  #    픽스처가 현실이 아니라 우리 가정대로 굴어서 통과하는, 이 저장소의 그 형태다.
  #    → 그래서 **현실 쪽으로 거짓말하는 가짜**를 하나 더 둔다.
  JMETA="$TMPROOT/jmeta"; mkdir -p "$JMETA"
  { echo '#!/bin/sh'
    echo 'case "$*" in *"-n 1"*) exit 0 ;; esac'
    # ⚠️ 미래 창(프로브)도 **비어 있지만 메타줄을 준다** — 그게 이 가짜의 요점이다.
    #    실제 journalctl 이 `-o cat` 없이 하는 짓이 정확히 이것이다.
    echo 'case "$*" in *--until*) echo "-- No entries --"; exit 0 ;; esac'
    echo 'if [ -n "${FAKE_JOURNAL:-}" ] && [ -s "$FAKE_JOURNAL" ]; then'
    echo '  cat "$FAKE_JOURNAL"'
    echo 'else'
    echo '  echo "-- No entries --"'
    echo 'fi'
    echo 'exit 0'
  } >"$JMETA/journalctl"
  chmod +x "$JMETA/journalctl" 2>/dev/null
  if [ "$(PATH="$JMETA:$PATH" FAKE_JOURNAL=/nonexistent journalctl -u ssh --since '@0' --no-pager -o cat 2>/dev/null)" != "-- No entries --" ]; then
    harn "(교차 j3) 메타줄 가짜 journalctl" "가짜가 '-- No entries --' 를 안 준다 — **검사 결과가 아니다**(하네스 문제)"
  else
    # ⛔ CR45-2 — **경보를 먼저 켜 두고 시작한다.**
    #    예전 rj7 은 처음부터 `JMETA` 라 `sshjournal` 을 **한 번도 raise 하지 않았다.**
    #    `clear_alert` 는 `.active` 가 없으면 첫 줄에서 return 하므로(`monitor-lib.sh`),
    #    아래 `avoid ALERT-CLEARED` 가 **가드를 지워도 통과**했다 — 공허한 단언이었다
    #    (리뷰어 실측: 가드 제거 변이로 자체검사 201/0/0 · rc=0).
    #    → `JBIN` 으로 **진짜 눈멂 상태**를 한 번 만들어 경보를 켠 뒤 `JMETA` 로 전환한다.
    #      그래야 `clear_alert` 가 실제로 하중을 받고, 가드가 없으면 거짓 해소가 나간다.
    AU="$RD/j7.auth.log"; authgen 40 >"$AU"
    sshrunj rj7 "$AU" "$JFIX2"                          # 기준값 (journald 정상 · JBIN)
    authgen 20 >>"$AU"; age_window rj7 300
    sshrunj rj7 "$AU" "$TMPROOT/none.txt"               # 눈멂 → sshjournal 이 **켜진다**
    if [ ! -f "$TMPROOT/rj7/alerts/sshjournal.active" ]; then
      harn "(교차 j3) 사전 조건" "sshjournal 을 켜지 못했다 — 아래 해소 단언이 공허해진다(**검사 결과가 아니다**)"
    else
      ok "(교차 j3) 사전 조건 — sshjournal 이 실제로 켜져 있다 (해소 단언이 하중을 받는다 · CR45-2)"
    fi
    RJ7PRE=$(wc -l <"$TMPROOT/rj7.log" 2>/dev/null); RJ7PRE=${RJ7PRE:-0}
    authgen 20 >>"$AU"; age_window rj7 300
    sshrunj rj7 "$AU" "$TMPROOT/none.txt" "$JMETA"      # 형식이 바뀌었다(메타줄) → 판정 보류
    tail -n +$((RJ7PRE + 1)) "$TMPROOT/rj7.log" >"$TMPROOT/rj7.meta.log" 2>/dev/null
    want "$TMPROOT/rj7.log" '교차 판정 보류\|믿을 수 없어' \
         "(교차 j3) 빈 결과를 구분 못 하면 **판정을 보류한다** (CR45-1)" \
         "(교차 j3) 메타줄 1개를 ssh 메시지 1줄로 세고 정상이라고 적는다 — 눈멂 탐지가 통째로 죽는다"
    want "$TMPROOT/rj7.log" 'ALERT logblind' \
         "(교차 j3) 그 사유가 감시불능 목록에 남는다" \
         "(교차 j3) 줄 수를 못 믿는 상태가 감시불능에 안 실린다"
    # ⚠️ 패턴을 `SSH2차` 로 묶는다. `기대 0/0` 만 찾으면 **로그유출 줄**(매 실행 출력되는
    #    `로그유출: access 0건 · error 0건 (기대 0/0)`)에 걸려 늘 붉다 — 실제로 그랬다.
    #    관문이 엉뚱한 줄을 보고 우는 것도 오탐이고, 오탐은 관문을 못 믿게 만든다.
    avoid "$TMPROOT/rj7.log" 'SSH2차.*기대 0/0' \
          "(교차 j3) 못 믿는 수로 '기대 0/0' 무사고 선언을 하지 않는다" \
          "(교차 j3) 메타줄을 세어 놓고 '기대 0/0' 이라고 적는다 (적극적인 거짓 무사고)"
    # ⚠️ **켜 둔 경보가 있는 구간만** 본다(CR45-2). 전체 로그를 보면 앞의 정상 구간까지
    #    섞여 무엇 때문에 통과했는지 알 수 없다.
    avoid "$TMPROOT/rj7.meta.log" 'ALERT-CLEARED sshjournal' \
          "(교차 j3) 못 믿는 수로 경보를 끄지 않는다 (거짓 해소 방지 · CR40-2 · CR45-2)" \
          "(교차 j3) 메타줄 때문에 jtot>0 이 되어 켜져 있던 경보가 꺼진다"
    if [ -f "$TMPROOT/rj7/alerts/sshjournal.active" ]; then
      ok "(교차 j3) 경보가 켜진 채로 남는다 (.active 생존 · 요약 머리말이 미해소를 계속 말한다)"
    else
      ng "(교차 j3) 줄 수를 못 믿는 상태인데 .active 가 사라졌다 — 사람은 문제가 풀린 줄 안다"
    fi
  fi
fi

# ⛔ CR45-1 (구조) — **프로브와 본질의가 같은 형식 플래그를 쓰는가.**
#    행동 검사로는 못 잡는다: "본질의에서만 `-o cat` 을 빼는" 변이를 픽스처로 만들려면
#    가짜가 두 호출을 구분해야 하는데, 그러면 그 구분 자체가 우리 가정이 된다.
#    대신 **갈라질 수 없는 형태인지**를 본다. 약한 검사인 것을 밝혀 둔다 —
#    이 결함이 실제로 났고(CR45-1) 관문은 201/0/0 으로 초록이었다.
JSRC=$(cat "$HERE/monitor.sh")
if has "$JSRC" '_jssh() { journalctl' && has "$JSRC" 'jprobe=$(_jssh' && has "$JSRC" 'jbuf=$(_jssh'; then
  ok "(교차 구조) 저널 조회 형식이 _jssh 한 곳에서만 만들어진다 (프로브와 본질의가 갈라질 수 없다 · CR45-1)"
else
  ng "(교차 구조) 프로브와 본질의가 각자 형식 플래그를 만든다 — 한쪽만 바뀌면 프로브가 거짓말한다"
fi
if printf '%s\n' "$JSRC" | grep -q '=$(journalctl -u ssh'; then
  ng "(교차 구조) _jssh 를 거치지 않고 journalctl 을 직접 잡아 쓰는 자리가 있다 — 형식이 갈라진다"
else
  ok "(교차 구조) journalctl 출력을 직접 잡아 쓰는 자리가 없다"
fi

# ⛔ SR41-2 — **공격자가 원격에서 T2 를 켤 수 있는가.**
#    사용자명·프로토콜 식별자는 공격자가 정하고 sshd 는 그것을 그대로 적는다.
#    앵커가 없던 시절에는 그 안에 `Accepted password` 를 넣기만 하면 경보가 떴고,
#    `sshpw` 는 **쿨다운 0** 이라 5분마다 하루 288통이 나갔다(봇은 동거 서비스와 공유).
#    ⚠️ 아래 문자열은 **보안리뷰가 실서버에서 실증한 모양** 그대로다(SR42-1).
#       앞 라운드 픽스처는 `sshd[NN]: ` 접두부가 없어 **현실보다 약했다** — 그래서
#       접두부를 통째로 보내는 우회가 관문 초록인 채로 통했다. 공격자는 인증도 필요 없다.
FORGE_USER='Aug  1 09:00:00 h sshd[77]: Invalid user Accepted password for root from 9.9.9.9 from 1.2.3.4 port 5'
FORGE_PROTO='Aug  1 09:00:01 h sshd[78]: banner exchange: Connection from 1.2.3.4 port 5: client sent invalid protocol identifier "Accepted password for root"'
# ⛔ **접두부까지 통째로** — 앞 라운드의 앵커를 실제로 뚫은 모양이다.
FORGE_PREFIX='Aug  1 09:00:02 h sshd[79]: error: kex_exchange_identification: client sent invalid protocol identifier "sshd[9]: Accepted password for q"'
FORGE_UPREFIX='Aug  1 09:00:03 h sshd[80]: Invalid user sshd[9]: Accepted password for q from 1.2.3.4 port 5'
AU="$RD/forge.auth.log"; authgen 40 >"$AU"; sshrun rf1 "$AU"          # 기준값
printf '%s\n%s\n%s\n%s\n' "$FORGE_USER" "$FORGE_PROTO" "$FORGE_PREFIX" "$FORGE_UPREFIX" >>"$AU"; sshrun rf1 "$AU"
avoid "$TMPROOT/rf1.log" 'ALERT sshpw' \
      "(T2 위조) 공격자가 보낸 문자열로는 경보가 안 뜬다 — **접두부를 통째로 보내도** (SR42-1)" \
      "(T2 위조) **원격에서 트립와이어를 켤 수 있다** — 진짜 경보가 위조 더미에 묻힌다"
# 위조가 **눈멂 보고 채널**도 오염시키면 안 된다(SR42-3 — 프로브가 부분일치였을 때 그랬다).
avoid "$TMPROOT/rf1.log" '형식이 앵커와 다르다' \
      "(T2 위조) 위조 줄로 '형식이 다르다' 를 띄울 수 없다 (눈멂 채널 오염 차단 · SR42-3)" \
      "(T2 위조) 배너 한 줄로 감시불능 보고를 켤 수 있다 — 원격에서 관문을 흐린다"

# 대조군 — 앵커를 달아 놓고 **진짜를 놓치면** 그건 더 나쁘다. 같은 상태에서 진짜는 떠야 한다.
AU="$RD/forge2.auth.log"; authgen 40 >"$AU"; sshrun rf2 "$AU"
printf '%s\n%s\n%s\n' "$FORGE_PREFIX" "$HIT" "$FORGE_UPREFIX" >>"$AU"; sshrun rf2 "$AU"
want "$TMPROOT/rf2.log" 'ALERT sshpw' \
      "(T2 위조 대조군) 위조 줄에 섞여 있어도 **진짜 성공줄은 잡는다**" \
      "(T2 위조 대조군) 앵커가 진짜까지 막았다 — 미탐이다(오탐보다 나쁘다)"

# ⛔ SR41-2/SR42-2/SR42-3 (짝) — **앵커가 이 호스트에 맞는가 · 모르는 메서드가 있는가.**
#    앵커는 오탐을 막지만 **미탐**을 만들 수 있고, 미탐은 조용하다.
#    ⚠️ 프로브는 **줄머리로만** 센다 — 부분일치로 세면 공격자가 배너 한 줄로
#       '형식이 다르다'를 띄워 **눈멂 보고 채널**을 오염시킬 수 있다(SR42-3).
# (가) sshd 줄은 있는데 **줄머리 형식이 다르다**(ISO 타임스탬프 rsyslog).
AU="$RD/fmt.auth.log"
{ echo '2026-08-01T09:00:00+09:00 h sshd[5]: Accepted publickey for root from 1.2.3.4 port 5 ssh2'
  echo '2026-08-01T09:00:01+09:00 h sshd[6]: Failed password for root from 1.2.3.4 port 6 ssh2'; } >"$AU"
sshrun rf3 "$AU"
want "$TMPROOT/rf3.log" '줄머리 형식이 앵커와 다르다' \
      "(T2 앵커) 줄머리 형식이 다르면 **못 셀 수 있다고 말한다** (미탐을 침묵으로 두지 않는다)" \
      "(T2 앵커) 앵커가 한 줄도 못 맞추는데 '0건'이라고만 적는다 — 미탐이 정상으로 보인다"
want "$TMPROOT/rf3.log" 'ALERT logblind' \
      "(T2 앵커) 그 사유가 감시불능 목록에 남는다" \
      "(T2 앵커) 못 세는 상태가 감시불능에 안 실린다"
# (나) 대조군 — 형식이 맞으면 조용하다(매번 울면 아무도 안 본다).
AU="$RD/fmt2.auth.log"; authgen 5 >"$AU"
echo 'Aug  1 07:00:00 h sshd[5]: Accepted publickey for root from 1.2.3.4 port 5 ssh2' >>"$AU"
sshrun rf4 "$AU"
avoid "$TMPROOT/rf4.log" '줄머리 형식이 앵커와 다르다' \
      "(T2 앵커 대조군) 형식이 맞으면 조용하다 (오탐 0)" \
      "(T2 앵커 대조군) 정상 형식인데 '앵커와 다르다'고 운다"
# (다) ⛔ SR42-2 — `keyboard-interactive/pam`. `keyboard-interactive for` 만 적었더니
#     **PAM 경유 로그인을 통째로 놓쳤다.** PAM 2FA 도입이 정확히 그 설정을 켜는 일이다.
AU="$RD/kbd.auth.log"; authgen 20 >"$AU"; sshrun rf5 "$AU"
echo 'Aug  1 09:10:00 h sshd[91]: Accepted keyboard-interactive/pam for root from 9.9.9.9 port 7 ssh2' >>"$AU"
sshrun rf5 "$AU"
want "$TMPROOT/rf5.log" 'ALERT sshpw' \
      "(T2 메서드) Accepted keyboard-interactive/pam 을 비밀번호 계열로 잡는다 (SR42-2)" \
      "(T2 메서드) PAM 경유 로그인을 놓친다 — 2FA 를 켜는 순간 트립와이어가 조용히 죽는다"
# (라) 우리가 **분류 못 하는** 성공 메서드가 있으면 그렇다고 말해야 한다.
#     메서드 이름을 하나씩 적는 방식은 다음 이름이 생기면 또 조용히 뚫린다.
AU="$RD/meth.auth.log"; authgen 20 >"$AU"
echo 'Aug  1 09:20:00 h sshd[92]: Accepted hostbased for root from 1.2.3.4 port 8 ssh2' >>"$AU"
sshrun rf6 "$AU"
want "$TMPROOT/rf6.log" '분류 못 하는 SSH 성공 메서드' \
      "(T2 메서드) 모르는 성공 메서드를 만나면 **모른다고 말한다** (SR42-2 구조적 방어)" \
      "(T2 메서드) 새 인증 메서드가 생겨도 조용히 0건으로 넘어간다"
avoid "$TMPROOT/rf4.log" '분류 못 하는 SSH 성공 메서드' \
      "(T2 메서드 대조군) publickey 만 있으면 조용하다 (오탐 0)" \
      "(T2 메서드 대조군) 평범한 publickey 를 '모르는 메서드'라고 운다"

# ⛔ CR46-2 — **OpenSSH 9.8+ 는 `sshd-session[…]` 로 쓴다.** 데몬 이름을 박아 두면
#    그 버전에서 앵커도 프로브도 전부 0 이 되어 **완전 침묵**한다(리뷰 실측: 옛 프로브는 울었다).
AU="$RD/newssh.auth.log"
{ echo 'Aug  1 07:00:00 h sshd-session[11]: Failed password for root from 1.2.3.4 port 1 ssh2'
  echo 'Aug  1 07:00:01 h sshd-session[12]: Failed password for root from 1.2.3.4 port 2 ssh2'; } >"$AU"
sshrun rf7 "$AU"
echo 'Aug  1 07:00:02 h sshd-session[13]: Accepted password for root from 9.9.9.9 port 3 ssh2' >>"$AU"
sshrun rf7 "$AU"
want "$TMPROOT/rf7.log" 'ALERT sshpw' \
      "(T2 9.8+) sshd-session 으로 쓰는 OpenSSH 9.8+ 에서도 성공 로그인을 잡는다 (CR46-2)" \
      "(T2 9.8+) 데몬 이름이 바뀌면 **완전 침묵**한다 — 요약은 '0건 (기대 0)' 이라 적는다"

# ⛔ SR36-5 / CR47-2 — **하루 발송 상한.** 폭주가 채널을 죽이면 진짜 경보가 묻힌다.
#    ⚠️ 앞 라운드의 이 검사 3건은 **전부 공허했다**(변이 5종 생존). 이유가 셋이다:
#      ① `want '하루 상한'` 이 **억제 로그**에도 걸려서, 상한 통보를 지워도 초록이었다.
#      ② 상태를 심어(capseed) 시작해서 **누적 경로(count++ · 롤오버)를 한 번도 안 밟았다.**
#      ③ 대조군이 상한값을 명시로 덮어써 **기본값을 아무도 안 봤다** — 기본값을 0 으로
#         바꾸면 모든 경보가 영구 침묵인데 관문은 초록이었다.
#    → 셋을 각각 밟는 검사로 다시 쓴다.
AU="$RD/cap.auth.log"; authgen 5 >"$AU"; echo "$HIT" >>"$AU"
capseed() { mkdir -p "$TMPROOT/$1/kv" 2>/dev/null
  printf '%s' "${2:-$(date +%Y%m%d)}" >"$TMPROOT/$1/kv/send_day"
  printf '%s' "$3" >"$TMPROOT/$1/kv/send_count"
  printf '%s' "$4" >"$TMPROOT/$1/kv/send_capped"; }

# (가) 상한에 **닿는 순간** — 한 통은 나가야 한다.
#     ⚠️ 패턴을 통보 **본문**으로 고정한다. '하루 상한' 만 찾으면 억제 로그에도 걸린다(CR47-2①).
capseed rcap '' 5 0
run_mon "$TMPROOT/rcap" --fast RE_MON_SEND_MAX_DAY=5 \
  RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
  RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
  RE_MON_AUTH_LOG="$AU" >/dev/null 2>&1
want "$TMPROOT/rcap.log" '경보 발송이 하루 상한' \
      "(발송 상한) 상한에 닿으면 **닿았다고 한 통 보낸다** (침묵과 억제를 구분한다)" \
      "(발송 상한) 상한에 닿아도 아무 말이 없다 — 경보가 안 오는 건지 막힌 건지 모른다"

# (나) 이미 통보한 뒤 — 억제하되 **로그에는 남는다**.
#     ⚠️ `ALERT-SUPPRESSED` 는 쿨다운 억제도 쓰는 낱말이라 `-CAP` 으로 갈랐다.
capseed rcap2 '' 5 1
run_mon "$TMPROOT/rcap2" --fast RE_MON_SEND_MAX_DAY=5 \
  RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
  RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
  RE_MON_AUTH_LOG="$AU" >/dev/null 2>&1
want "$TMPROOT/rcap2.log" 'ALERT-SUPPRESSED-CAP' \
      "(발송 상한) 억제된 경보도 **로그에는 남는다** (조용히 유실되지 않는다)" \
      "(발송 상한) 상한을 넘긴 경보가 로그에도 안 남는다 — 조용히 유실된다"

# (다) ⛔ CR47-2② **누적 경로** — 상태를 안 심고 맨바닥에서 시작한다.
#     보낸 만큼 `send_count` 가 실제로 올라야 상한이 언젠가 걸린다.
run_mon "$TMPROOT/rcap4" --fast \
  RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
  RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
  RE_MON_AUTH_LOG="$AU" >/dev/null 2>&1
CAPN=$(cat "$TMPROOT/rcap4/kv/send_count" 2>/dev/null); CAPN=${CAPN:-0}
if [ "$CAPN" -gt 0 ] 2>/dev/null; then
  ok "(발송 상한) 보낸 만큼 send_count 가 실제로 오른다 (누적 경로가 돈다 · CR47-2②)"
else
  ng "(발송 상한) send_count 가 안 오른다 — 상한이 영영 안 걸린다(있으나 마나)"
fi

# (라) ⛔ CR47-2② **날짜 롤오버** — 어제 꽉 찼어도 오늘은 다시 보내야 한다.
capseed rcap5 20200101 999 1
run_mon "$TMPROOT/rcap5" --fast RE_MON_SEND_MAX_DAY=5 \
  RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
  RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
  RE_MON_AUTH_LOG="$AU" >/dev/null 2>&1
avoid "$TMPROOT/rcap5.log" 'ALERT-SUPPRESSED-CAP' \
      "(발송 상한) 날이 바뀌면 상한이 풀린다 (어제 폭주가 오늘을 막지 않는다)" \
      "(발송 상한) 하루 폭주가 **영구 침묵**이 된다 — 롤오버가 없다"

# (마) ⛔ CR47-2③ **기본값** — 상한값을 안 주는 평범한 실행이 조용해지면 안 된다.
#     기본값을 0 으로 바꾸는 변이가 여기서 죽는다(앞 라운드는 대조군이 =500 을 덮어써 못 잡았다).
run_mon "$TMPROOT/rcap3" --fast \
  RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
  RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
  RE_MON_AUTH_LOG="$AU" >/dev/null 2>&1
avoid "$TMPROOT/rcap3.log" 'ALERT-SUPPRESSED-CAP' \
      "(발송 상한 대조군) 상한값을 안 줘도 평시에는 억제가 없다 (기본값 경로 · CR47-2③)" \
      "(발송 상한 대조군) 평범한 실행에서 경보가 억제된다 — 감시가 통째로 막힌다"
avoid "$TMPROOT/rcap3.log" '경보 발송이 하루 상한' \
      "(발송 상한 대조군) 평시에는 상한 통보도 안 나간다" \
      "(발송 상한 대조군) 평시에 상한 통보가 나간다 — 늑대소년이 된다"

# (바) ⛔ CR47-2 / SR43-2 **상태 손상은 fail-open** — 막는 쪽으로 넘어지면 감시가 죽는다.
capseed rcap6 '' zzz 0
run_mon "$TMPROOT/rcap6" --fast RE_MON_SEND_MAX_DAY=5 \
  RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
  RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
  RE_MON_AUTH_LOG="$AU" >/dev/null 2>&1
avoid "$TMPROOT/rcap6.log" 'ALERT-SUPPRESSED-CAP' \
      "(발송 상한) send_count 가 깨져도 **막지 않는다** (fail-open · SR43-2)" \
      "(발송 상한) 상태가 깨지면 경보를 막는다 — 고장과 무사고가 같아 보인다"

# (사) ⛔ CR47-1 **보내지도 못한 통을 세지 않는다.** 자격증명이 없어 한 통도 못 나가면
#     상한이 소진되면 안 된다 — 채널 복구 뒤 자정까지 전면 침묵하던 결함이다.
CAPCRED="$TMPROOT/nocred.env"; : >"$CAPCRED"
run_mon "$TMPROOT/rcap7" --fast RE_MON_DRY_RUN=0 RE_MON_CRED_FILES="$CAPCRED" \
  RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
  RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
  RE_MON_AUTH_LOG="$AU" >/dev/null 2>&1
CAP7=$(cat "$TMPROOT/rcap7/kv/send_count" 2>/dev/null); CAP7=${CAP7:-0}
if [ "$CAP7" = 0 ]; then
  ok "(발송 상한) 한 통도 못 나갔으면 상한을 안 쓴다 (CR47-1)"
else
  ng "(발송 상한) 발송 실패도 상한으로 센다 — 0통 보내고 상한 소진 뒤 자정까지 침묵한다"
fi

# ⛔ CR47-3 (구조) — **재통보 주기가 관문 밖이었다.** 900 을 1주일로 바꿔도 아무도 안 울었다.
#    행동으로 재려면 15분을 기다려야 해 형태로 본다(약한 검사임을 밝혀 둔다).
#    ⚠️ 값 자체보다 **문서와 코드가 같은 수를 말하는가**가 핵심이다 — 달라진 채로 두면
#       사람이 문서를 믿고 잘못된 기대를 갖는다(CR47-3 이 그 형태였다).
if grep -qE 'raise_alert sshpw 900 ' "$HERE/monitor.sh"; then
  SSHPW_CD=$(grep -acE 'raise_alert sshpw 900 ' "$HERE/monitor.sh")
  SSHPW_ALL=$(grep -acE 'raise_alert sshpw ' "$HERE/monitor.sh")
  if [ "$SSHPW_CD" = "$SSHPW_ALL" ]; then
    ok "(T2 쿨다운) sshpw 경보 ${SSHPW_ALL}곳이 모두 900초다 (하루 288통 → 96통 · CR47-3)"
  else
    ng "(T2 쿨다운) sshpw 경보 ${SSHPW_ALL}곳 중 ${SSHPW_CD}곳만 900초 — 남은 곳이 폭주 경로다"
  fi
else
  ng "(T2 쿨다운) sshpw 쿨다운이 900초가 아니다 — 문서와 코드가 다른 수를 말한다"
fi
if grep -q '이제 \*\*900초\*\*' "$HERE/../docs/05-monitoring/monitoring.md" 2>/dev/null; then
  ok "(T2 쿨다운) 문서도 900초라고 적는다 (문서와 코드가 같은 수를 말한다)"
elif [ -f "$HERE/../docs/05-monitoring/monitoring.md" ]; then
  ng "(T2 쿨다운) 문서는 아직 쿨다운 0 이라 적는다 — 사람이 문서를 믿고 틀린 기대를 갖는다"
else
  skip "(T2 쿨다운) monitoring.md 를 못 찾음 — 서버 사본 실행이면 정상"
fi

# ⛔ CR47-4 — **상태(kv)가 깨져도 감시가 죽으면 안 된다.** 실측상 `--fast` 가 rc≠0 로
#    끝나고 그 실행의 검사가 통째로 사라졌다. 죽은 감시는 침묵과 구별되지 않는다.
AU="$RD/kvnum.auth.log"; authgen 5 >"$AU"
ST="$TMPROOT/rkn"; rm -rf "$ST" "$ST.log"
sshrun rkn "$AU"
printf '%s' 'abc' >"$ST/kv/api5xx"
run_mon "$ST" --fast RE_MON_LOG_DIR="$FULL" \
  RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*" \
  RE_MON_ACCESS_LOG="$FULL/realestate.access.log" \
  RE_MON_ERROR_LOG="$FULL/realestate.error.log" \
  RE_MON_AUTH_LOG="$AU" >/dev/null 2>&1
KRC=$?
if [ "$KRC" = 0 ]; then
  ok "(상태손상 api5xx) kv 가 깨져도 감시는 계속 돈다 (CR47-4)"
else
  ng "(상태손상 api5xx) kv 하나가 깨지면 --fast 가 rc=$KRC 로 죽는다 — 그 실행의 검사가 통째로 사라진다"
fi
want "$ST.log" 'ALERT logblind' \
      "(상태손상 api5xx) 못 세게 된 사실이 감시불능 목록에 남는다" \
      "(상태손상 api5xx) 상태가 깨진 것을 아무도 모른다"
# ⚠️ **OOM 쪽은 이 하네스에서 못 돈다** — `cg_path` 가 `/sys/fs/cgroup` 실경로와
#    `docker inspect` 를 쓰므로 임시 디렉터리로 못 돌린다. 가짜로 통과시키지 않는다.
#    행동으로 못 재니 **같은 가드가 그 분기에 있는지 형태로** 본다(약한 검사임을 밝혀 둔다).
skip "(상태손상 oomkill) cgroup·docker 가 있어야 도달 — 행동으로 못 잼(아래 구조 검사로 대신)"
if grep -q 'kv/oomkill_' "$HERE/monitor.sh" && grep -q '가 손상됐다 — 그 사이 OOM' "$HERE/monitor.sh"; then
  ok "(상태손상 oomkill · 구조) OOM 분기에도 같은 손상 가드가 있다 (CR47-4)"
else
  ng "(상태손상 oomkill · 구조) OOM 분기에 손상 가드가 없다 — kv 하나로 감시가 매 실행 죽는다"
fi

# ⛔ CR46-6 — 상태(kv)가 깨졌을 때 **조용히 기준값으로 돌아가지 않는다.**
#    예전에는 `이번 구간 0건 (기대 0)` 을 적고 rc=0 이었다 — 못 센 것을 없다고 말한 것이다.
AU="$RD/kvbad.auth.log"; authgen 20 >"$AU"; sshrun rkv "$AU"
printf '%s' 'zzz' >"$TMPROOT/rkv/kv/sshpw_off"
authgen 5 >>"$AU"; sshrun rkv "$AU"
want "$TMPROOT/rkv.log" '오프셋이 숫자가 아니다' \
      "(T2 상태손상) 저장된 오프셋이 깨지면 **못 센다고 말한다** (CR46-6)" \
      "(T2 상태손상) 깨진 상태를 조용히 기준값으로 넘기고 '0건 (기대 0)' 이라 적는다"
want "$TMPROOT/rkv.log" 'ALERT logblind' \
      "(T2 상태손상) 그 사유가 감시불능 목록에 남는다" \
      "(T2 상태손상) 상태가 깨진 사실이 감시불능에 안 실린다"
# ⛔ CR46-5 (구조) — `_jssh` 호출부에 `-o` 를 덧붙이면 나중 것이 이겨 **jd 가 영구 0** 이 된다.
#    행동으로 잡기 어려워 형태를 본다. 약한 검사인 것을 밝혀 둔다.
if printf '%s\n' "$JSRC" | grep -qE '_jssh .*-o '; then
  ng "(교차 구조) _jssh 호출부가 -o 를 덧붙인다 — 형식이 갈라져 jd 가 조용히 0 이 된다"
else
  ok "(교차 구조) _jssh 호출부가 출력 형식을 덧붙이지 않는다 (CR46-5)"
fi

# CR41-7 — 오프셋이 **읽은 구간과 정확히** 맞아야 한다(같은 줄을 두 번 세지 않는다)
AU="$RD/g.auth.log"; authgen 40 >"$AU"; sshrun rg "$AU"
echo "$HIT" >>"$AU"; sshrun rg "$AU"
if live "$TMPROOT/rg.log" "T6 중복 계수"; then
  n1=$(grep -ac 'ALERT sshpw' "$TMPROOT/rg.log")
  sshrun rg "$AU"; n2=$(grep -ac 'ALERT sshpw' "$TMPROOT/rg.log")
  if [ "$n1" = 1 ] && [ "$n2" = 1 ]; then ok "같은 로그인을 두 번 세지 않는다 (CR41-7)"
  else ng "같은 구간을 다시 센다 (경보 ${n1} -> ${n2})"; fi
  if [ "$(cat "$TMPROOT/rg/kv/sshpw_off" 2>/dev/null)" = "$(stat -c %s "$AU" 2>/dev/null)" ]; then
    ok "저장한 오프셋이 파일 크기와 정확히 같다 (다음 구간이 어긋나지 않는다)"
  else ng "저장한 오프셋이 파일 크기와 다르다 — 다음 구간이 겹치거나 빈다"; fi
fi
# ⚠️ **구조 검사인 것을 밝혀 둔다.** CR41-7 의 중복 계수는 `stat` 과 읽기 **사이에**
#    줄이 붙어야 일어난다 — 그 경합을 결정적으로 재현할 방법이 없어서(재현하려면
#    타이밍에 기대야 하고, 그러면 검사 자신이 간헐적이 된다) 코드 형태를 본다.
#    행동으로 잡는 것보다 약하다. 약한 것을 강한 척하지 않는다.
if grep -qF 'head -c "$((size - off))"' "$HERE/monitor.sh"; then
  ok "증가분을 **이번에 잰 크기까지만** 읽는다 (CR41-7 · 구조 검사)"
else
  ng "증가분을 파일 끝까지 읽는다 — stat 과 읽기 사이에 붙은 줄을 이번에도 다음에도 센다"
fi
# 강한 증거(rename 불변식)가 코드에 실제로 있는가 — 구조 검사(위 행동 검사의 보조)
MONSRC=$(cat "$HERE/monitor.sh")
if has "$MONSRC" 'rot_strong=1' && has "$MONSRC" 'how=replaced'; then
  # ⚠️ 예전에는 이 문장 안의 역따옴표가 **명령 치환**이라 매 실행마다
  #    `replaced: command not found` 가 stderr 로 새고 낱말이 사라진 채 출력됐다.
  #    (`| tail` 로 보면 안 보여서 오래 남아 있었다.) 검사 결과에는 영향이 없었지만,
  #    관문 출력에 원인 불명의 오류 줄이 있으면 사람이 초록/빨강을 못 믿는다.
  ok "회전 판정이 **강한 증거**와 replaced 상태를 갖는다 (CR42-2 · 구조 검사)"
else
  ng "회전 판정에 강한 증거/replaced 가 없다 — inode 변화만으로 회전을 확정하던 상태로 되돌아갔다"
fi

# ============================================================================
sect "T6b. 상호 감시의 대칭 — 일일 점검이 **한 번도** 안 돈 경우 (15번째 자리)"

# ⛔ `check_peer_alive` 의 daily 쪽은 *"5분 감시가 한 번도 돈 기록이 없다"* 를 경보로
#    만드는데, fast 쪽은 같은 상황에서 `return 0` 으로 조용히 넘어갔다 — 같은 함수
#    안에서 대칭이 깨져 있었다. 실측: `--fast` 만 8회 돌려도 `daily_dead` 0건.
#    그러면 `--daily` 크론 한 줄이 빠졌을 때 인증서·DB구조·시장지수·DB크래시·
#    컨테이너로그 **일곱 검사**가 통째로 없는 채로 아무 신호가 없다.
PA="$TMPROOT/pa"; mkdir -p "$PA/kv"
run_pa() { run_mon "$1" --fast     RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*"     RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log"     RE_MON_AUTH_LOG="$FULL/auth.log" >/dev/null 2>&1; }
# ① 설치 직후 — 울면 안 된다(일일 점검은 하루 한 번뿐이다)
run_pa "$PA"
avoid "$PA.log" 'ALERT daily_dead'       "(대조군) 설치 직후 첫 5분 감시는 일일 점검을 재촉하지 않는다 (오탐 없음)"       "설치하자마자 '일일 점검이 안 돈다'고 운다 — 하루 한 번짜리를 5분 만에 재촉한다"
if [ -s "$PA/kv/first_fast_run" ]; then
  ok "첫 5분 실행 시각을 기억한다 (유예의 기준점이 생긴다)"
else
  ng "첫 5분 실행 시각을 안 남긴다 — 유예를 잴 기준이 없다"
fi
# ② 5분 감시만 이틀 넘게 돈 상태 — 일일 크론이 아예 안 걸린 서버
PA2="$TMPROOT/pa2"; mkdir -p "$PA2/kv"
printf '%s' "$(( $(date +%s) - 40 * 3600 ))" >"$PA2/kv/first_fast_run"
run_pa "$PA2"
want "$PA2.log" 'ALERT daily_dead'      "5분 감시만 40시간째 돌고 일일 점검 기록이 없으면 경보 (크론 한 줄이 빠진 상태)"      "일일 점검이 한 번도 안 돌았는데 아무 말이 없다 — daily 전용 검사 7개가 조용히 없는 상태다"
# ③ 반대 방향은 원래 있었다 — 그것이 여전히 사는지도 함께 본다(대칭의 양쪽)
PA3="$TMPROOT/pa3"
run_mon "$PA3" --daily PATH="$FAKEBIN:$PATH" RE_MON_LE_DIR="$LE_EMPTY"   RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*"   RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log"   RE_MON_AUTH_LOG="$FULL/auth.log" >/dev/null 2>&1
want "$PA3.log" 'ALERT fast_dead'      "(대칭 반대쪽) 5분 감시 기록이 없으면 일일 점검이 그것을 신고한다 — 원래 있던 쪽"      "반대쪽 상호 감시까지 죽었다"
# ④ ⛔ CR44-2 §10 — **꺼지는 것까지 본다.** `daily_dead`·`fast_dead` 는 코드에 clear 가
#    있는데 관문이 안 봤다. 크론을 되살렸는데 경보가 안 꺼지면 사람은 그 이름을 무시하게
#    되고, 그러면 다음번 진짜 소실도 같이 묻힌다.
printf '%s' "$(date +%s)" >"$PA2/kv/last_daily_run"
PA2PRE=$(wc -l <"$PA2.log" 2>/dev/null); PA2PRE=${PA2PRE:-0}
run_pa "$PA2"
tail -n +$((PA2PRE + 1)) "$PA2.log" >"$PA2.after.log" 2>/dev/null
want "$PA2.after.log" 'ALERT-CLEARED daily_dead' \
     "(해소) 일일 점검이 돌기 시작하면 daily_dead 가 꺼진다 (크론을 고친 것이 표시에 반영된다)" \
     "(해소) 크론을 되살려도 daily_dead 가 안 꺼진다 — 미해소가 영영 남는다"
printf '%s' "$(date +%s)" >"$PA3/kv/last_fast_run"
PA3PRE=$(wc -l <"$PA3.log" 2>/dev/null); PA3PRE=${PA3PRE:-0}
run_mon "$PA3" --daily PATH="$FAKEBIN:$PATH" RE_MON_LE_DIR="$LE_EMPTY"   RE_MON_LOG_DIR="$FULL" RE_MON_APP_LOG_GLOB="$FULL/realestate-monitor.log*"   RE_MON_ACCESS_LOG="$FULL/realestate.access.log" RE_MON_ERROR_LOG="$FULL/realestate.error.log"   RE_MON_AUTH_LOG="$FULL/auth.log" >/dev/null 2>&1
tail -n +$((PA3PRE + 1)) "$PA3.log" >"$PA3.after.log" 2>/dev/null
want "$PA3.after.log" 'ALERT-CLEARED fast_dead' \
     "(해소) 5분 감시가 돌아오면 fast_dead 가 꺼진다 (대칭의 반대쪽도 꺼진다)" \
     "(해소) 5분 감시가 살아났는데 fast_dead 가 안 꺼진다"

# ============================================================================
sect "T6c. api5xx 해소 — 형제 중 유일하게 꺼지지 않던 자리 (CR44-9)"

# ⛔ `logperm`·`logleak`·`logfresh` 는 다 꺼지는데 `api5xx` 만 clear 경로가 **없었다**.
#    문턱이 `API5XX_MIN=1` 이라 5xx 한 건이면 켜지고, 그 뒤로 일일 요약 머리말이
#    계속 `미해소 (api5xx)` 다. 이 저장소의 문장이 *"안 꺼지는 경보는 곧 무시되는 경보"* 다.
A5="$TMPROOT/a5logs"; mkdir -p "$A5"
: >"$A5/realestate.error.log"; : >"$A5/realestate-monitor.log"
ACC5="$A5/realestate.access.log"
printf '%s\n' '1.2.3.4 - - [01/Aug/2026:00:00:01 +0900] "GET /api/v1/health HTTP/1.1" 200 5 "-" "-"' >"$ACC5"
run_a5() { run_mon "$1" --fast RE_MON_LOG_DIR="$A5" RE_MON_APP_LOG_GLOB="$A5/realestate-monitor.log*" \
  RE_MON_ACCESS_LOG="$ACC5" RE_MON_ERROR_LOG="$A5/realestate.error.log" \
  RE_MON_AUTH_LOG="$FULL/auth.log" >/dev/null 2>&1; }
S5X="$TMPROOT/s5x"
run_a5 "$S5X"                                    # 기준값
printf '%s\n' '1.2.3.4 - - [01/Aug/2026:00:00:02 +0900] "GET /api/v1/map/complexes HTTP/1.1" 502 5 "-" "-"' >>"$ACC5"
run_a5 "$S5X"
want "$S5X.log" 'ALERT api5xx' \
     "/api/ 5xx 한 건에 경보가 뜬다 (트래픽이 거의 없으니 1건도 사건이다)" \
     "5xx 가 났는데 조용하다 — 헬스체크 200 뒤에서 기능이 죽어도 아무 말이 없다"
S5XPRE=$(wc -l <"$S5X.log" 2>/dev/null); S5XPRE=${S5XPRE:-0}
printf '%s\n' '1.2.3.4 - - [01/Aug/2026:00:00:03 +0900] "GET /api/v1/health HTTP/1.1" 200 5 "-" "-"' >>"$ACC5"
run_a5 "$S5X"                                    # 새 5xx 없음 → 꺼져야 한다
tail -n +$((S5XPRE + 1)) "$S5X.log" >"$S5X.after.log" 2>/dev/null
want "$S5X.after.log" 'ALERT-CLEARED api5xx' \
     "5xx 가 멎으면 경보가 꺼진다 (CR44-9 — 형제들과 규칙이 같아진다)" \
     "5xx 가 멎어도 api5xx 가 영영 안 꺼진다 — 요약 머리말이 계속 미해소다"
if [ ! -f "$S5X/alerts/api5xx.active" ]; then
  ok "해소되면 .active 도 지워진다"
else ng "해소 통보는 갔는데 .active 가 남는다"; fi
# ⚠️ **못 읽은 상태에서는 꺼지면 안 된다** — CR40-2 가 막은 거짓 해소다.
#    (access 로그가 사라진 채로 clear 가 나가면 "5xx 0건" 은 본 것이 아니라 못 본 것이다)
S5Y="$TMPROOT/s5y"; mkdir -p "$S5Y/alerts"
printf '%s' "$(date +%s)" >"$S5Y/alerts/api5xx.active"; printf '%s' "$(date +%s)" >"$S5Y/alerts/api5xx.sent"
run_mon "$S5Y" --fast RE_MON_LOG_DIR="$A5" RE_MON_APP_LOG_GLOB="$A5/realestate-monitor.log*" \
  RE_MON_ACCESS_LOG="$EMPTY/none.access.log" RE_MON_ERROR_LOG="$A5/realestate.error.log" \
  RE_MON_AUTH_LOG="$FULL/auth.log" >/dev/null 2>&1
avoid "$S5Y.log" 'ALERT-CLEARED api5xx' \
      "(대조군) access 로그를 못 읽으면 api5xx 를 끄지 않는다 (못 본 것을 '0건'이라 하지 않는다)" \
      "access 로그가 사라졌는데 '5xx 해소' 를 보낸다 — 거짓 해소(CR40-2 재발)"

# ============================================================================
sect "T7. scrub — 알림에 실리면 안 되는 것 (CR40-4 / SR36-3)"

chk_scrub() { # chk_scrub <설명> <입력> <남아 있으면 안 되는 문자열>
  local out; out=$(printf '%s' "$2" | scrub)
  if has "$out" "$3"; then ng "$1" "결과: $out"; else ok "$1"; fi
}
chk_scrub "쉼표 금액 1,026,560,000원 을 지운다 (앱이 쓰는 형식 그 자체)" '한도 1,026,560,000원' '1,026,560,000'
chk_scrub "9자리 이상 숫자 + 한글 조사 (1026560000원)"                   '한도 1026560000원'   '1026560000'
chk_scrub "DSN 비밀번호"          'postgresql+psycopg://re:s3cr3t@172.20.0.2:5432/db' 's3cr3t'
chk_scrub "봇 토큰"               'token 123456789:AABBCCDDEEFFGGHHIIJJKKLLMMNNOOPP' 'AABBCCDDEEFFGGHHIIJJKKLLMMNNOOPP'
chk_scrub "KEY= 꼴"               'SERVICE_KEY=abcd1234efgh'  'abcd1234efgh'
chk_scrub "KEY: 꼴 (콜론+공백)"   'KAKAO_REST_KEY: abcd1234efgh' 'abcd1234efgh'
chk_scrub "Bearer 토큰"           'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc' 'eyJhbGciOiJIUzI1NiJ9'
# CR41-4 — **금액 토큰이 붙은 수**는 자릿수와 무관하게 지운다. 아래 7종은 리뷰가
#          "지금 규칙을 그냥 통과한다"고 실측해 온 형태 그대로다.
chk_scrub "8자리+원 (50000000원)"       '보유 50000000원'        '50000000'
chk_scrub "7자리+원 (3500000원)"        '월세 3500000원'         '3500000'
chk_scrub "만원 단위 (5,000만원)"       '전세 5,000만원'         '5,000'
chk_scrub "국토부 만원 단위 (102,656만원)" '거래가 102,656만원'  '102,656'
chk_scrub "억 표기 (4.2억)"             '호가 4.2억'             '4.2억'
chk_scrub "쉼표 1묶음+원 (850,000원)"   '월관리비 850,000원'     '850,000'
chk_scrub "금액 키 + 숫자 (JSON)"       '{"cash_krw": 50000000}' '50000000'
chk_scrub "금액 키 + 숫자 (헤더 꼴)"    'X-Cash: 50000000'       '50000000'

# 반대쪽 — 운영 수치까지 지우면 로그가 쓸모없어진다
keep() { local out; out=$(printf '%s' "$2" | scrub)
  if has "$out" "$3"; then ok "$1"; else ng "$1" "결과: $out"; fi; }
keep "바이트 수 1048576 은 남긴다"      '이전 1048576바이트' '1048576'
keep "일수·건수 288 은 남긴다"          'fast 실행 288회'    '288'
keep "쉼표 1묶음(12,345)은 남긴다"      '표본 12,345건'      '12,345'
# ⚠️ 여기가 균형점이다 — 자릿수를 8로 내리면 아래 두 줄이 죽고, 그러면
#    "auth.log 가 얼마나 줄었나"를 사람이 못 읽는다(그 숫자가 T2 판정의 근거다).
keep "8자리 바이트 수(44049707)는 남긴다" 'auth.log 44049707 -> 0 바이트' '44049707'
keep "소요 시간 0.36초는 남긴다"        'fast 0.36초'        '0.36'
keep "기준월 2026-06 은 남긴다"         '기준월 2026-06'     '2026-06'

# ⛔ SR38-4 — 파이썬 `dict.__repr__` 은 **작은따옴표**를 쓴다. 트레이스백에 실제로
#    나오는 꼴이 이것이고, 옛 규칙 ③은 큰따옴표 하나만 받아서 **그냥 통과했다.**
#    문서·주석은 남는 구멍을 *"토큰도 구분자도 없는 8자리 이하"* 라고 적었는데,
#    이 형태는 **토큰도 구분자도 있는데** 통과했다 — 서술이 실제보다 좁았던 것이다.
chk_scrub "파이썬 repr 작은따옴표 ({'cash_krw': 90000000})" "{'cash_krw': 90000000}" '90000000'
chk_scrub "파이썬 repr 여러 키"        "{'own_cash_krw': 90000000}" '90000000'
chk_scrub "역따옴표 키 (\`cash_krw\`: …)" '`cash_krw`: 90000000' '90000000'

# ⛔ **SR38-4 를 고치다 찾은 것 — 같은 결함이 비밀 규칙 ④에도 있었고 그쪽이 더 넓었다.**
#    리뷰는 금액 규칙 ③만 봤다. ④는 따옴표를 **아예 안 받아서** JSON 큰따옴표 꼴조차
#    통과했다(실측). psycopg·httpx 트레이스백과 dict 덤프가 정확히 그 모양이고,
#    금액과 달리 비밀은 한 번 나가면 되돌릴 수 없다.
chk_scrub "JSON 비밀 키 ({\"api_key\": \"…\"})"   '{"api_key": "sk-live-9wQ2kLp4RtZ"}' 'sk-live-9wQ2kLp4RtZ'
chk_scrub "파이썬 repr 비밀 키 ({'TOKEN': '…'})"  "{'TOKEN': 'x9wQ2kLp'}" 'x9wQ2kLp'
chk_scrub "파이썬 repr DB 비밀번호"               "{'POSTGRES_PASSWORD': 'Xq7vLm2pRt9Zb4'}" 'Xq7vLm2pRt9Zb4'

# ⛔ **10번째 변이 — 내가 스스로 찾은 자리.**
#    위 검사들은 전부 `scrub` 을 **직접** 부른다. 그런데 알림이 실제로 나가는 길은
#    `send_telegram()` 이고, 거기서 `| scrub` 을 **한 조각 지워도 이 파일 전체가 초록이었다.**
#    (T5 의 `token=abc` 검사는 `log()` 가 남긴 ALERT 줄을 보는데 `log()` 는 원래 scrub 을
#     안 탄다 — 그 검사가 통과하는 이유는 monitor.sh 가 값을 안 넣기 때문이지
#     scrub 이 동작해서가 아니다.) 즉 **비밀 세탁의 마지막 관문이 무방비였다.**
#    → 나가는 경로 자체를 시험한다.
#    ⚠️ 안전장치 두 겹: ① DRY_RUN=1 ② 자격증명 파일을 없는 경로로 바꾼다.
#       둘 중 하나만 있어도 네트워크로 아무것도 안 나간다(사용자 텔레그램 0통).
TG_OUT=$(
  DRY_RUN=1
  RE_MON_CRED_FILES="$TMPROOT/no-such-cred.env"
  send_telegram '한도 1,026,560,000원 · SERVICE_KEY=abcd1234efgh · token 123456789:AABBCCDDEEFFGGHHIIJJKKLLMMNNOOPP'
)
if has "$TG_OUT" '1,026,560,000' || has "$TG_OUT" 'abcd1234efgh' ||
   has "$TG_OUT" 'AABBCCDDEEFFGGHHIIJJKKLLMMNNOOPP'; then
  ng "send_telegram 이 scrub 을 안 태운다 — 세탁 규칙이 아무리 좋아도 나가는 길에서 새면 소용없다" \
     "결과: $TG_OUT"
else
  ok "**나가는 경로**(send_telegram)가 실제로 scrub 을 통과한다 (10번째 변이 자리)"
fi
if has "$TG_OUT" '[DRY-RUN'; then ok "그 시험이 DRY-RUN 으로 돌았다 (네트워크 전송 0)"
else ng "send_telegram 이 DRY-RUN 표시를 안 냈다 — 시험 격리가 깨졌을 수 있다" "결과: $TG_OUT"; fi

# ⛔ SR39-5 — **위 시험은 `DRY_RUN` 분기만 지나간다.** 네트워크를 안 쓰니 당연한데,
#    그래서 **진짜 나가는 줄**(`curl --data-urlencode "text=..."`)이 세탁을 안 타도
#    관문이 못 본다. 리뷰어가 그 한 글자를 바꾼 변이(`${text}`→`${1}`)를 심었더니
#    관문이 초록이었다 — 방금 닫은 구멍의 **한 겹 안쪽**이다.
#    행동으로 덮으려면 실제 전송이 필요하므로(그건 안 한다), 구조로 못 박는다.
if grep -q 'data-urlencode "text=\${text}"' "$HERE/monitor-lib.sh"; then
  ok "실제 전송 줄이 **세탁된 변수**를 쓴다 (curl 인자가 원문으로 바뀌면 이 검사가 죽는다)"
else
  ng "curl --data-urlencode 의 text 가 scrub 을 거친 변수가 아니다 — 세탁을 우회해 나간다" \
     "$(grep -n 'data-urlencode' "$HERE/monitor-lib.sh" | head -3)"
fi
# 그리고 로그도 나가는 길이다(15번째 자리) — `log()` 가 세탁을 타는가.
if grep -q 'log() {' "$HERE/monitor-lib.sh" && grep -A2 'log() {' "$HERE/monitor-lib.sh" | grep -q '| scrub'; then
  ok "감시 로그도 scrub 을 통과한다 (배치 출력이 그대로 로그에 눕지 않는다)"
else
  ng "log() 가 원문을 그대로 파일에 쓴다 — job-run 의 '사유:' 줄은 **배치가 찍은 아무 문자열**이다" \
     "$(grep -n -A2 'log() {' "$HERE/monitor-lib.sh" | head -5)"
fi
# ⛔ CR44-7 — 위 검사는 **구조(문자열)** 만 본다. 같은 T7 의 이웃(`send_telegram` 경로)은
#    행동으로 보는데 이쪽만 아니었다. 세 줄이면 행동이 된다 — 실제로 찍고 파일을 읽는다.
LGT="$TMPROOT/logscrub"; mkdir -p "$LGT"
(
  RE_MON_STATE="$LGT" RE_MON_LOG="$LGT/mon.log" RE_MON_DRY_RUN=1
  export RE_MON_STATE RE_MON_LOG RE_MON_DRY_RUN
  # shellcheck source=./monitor-lib.sh
  . "$HERE/monitor-lib.sh" 2>/dev/null || exit 3
  log 'SERVICE_KEY=Zm9vYmFyU2VjcmV0VmFsdWUxMjM0NTY3ODkwYWJjZGVm 한도 1,026,560,000원 postgresql+psycopg://re:p4ssw0rdX9@db:5432/x'
) >/dev/null 2>&1
if [ ! -s "$LGT/mon.log" ]; then
  harn "log() 세탁 (행동)" "감시 로그를 못 만들었다 — **검사 결과가 아니다**(하네스·환경 문제)"
else
  LGBAD=""
  for tok in 'Zm9vYmFyU2VjcmV0VmFsdWUxMjM0NTY3ODkwYWJjZGVm' '1,026,560,000' 'p4ssw0rdX9'; do
    grep -aq -- "$tok" "$LGT/mon.log" && LGBAD="$LGBAD $tok"
  done
  if [ -z "$LGBAD" ]; then
    ok "log() 가 실제로 세탁한다 — 키·금액·DSN 비밀번호가 로그 파일에 평문으로 없다 (구조가 아니라 행동으로 확인)"
  else
    ng "log() 가 쓴 로그 파일에 원문이 남아 있다:$LGBAD" "$(head -2 "$LGT/mon.log")"
  fi
fi

# 문서와 코드가 같은 말을 하는가 (CR40-4: 문서가 방어를 과장하고 있었다)
DOC="$HERE/../docs/05-monitoring/monitoring.md"
if [ -f "$DOC" ]; then
  if grep -q '쉼표' "$DOC" && grep -q '9자리' "$DOC" && grep -q '금액 토큰' "$DOC" && grep -q '95000000' "$DOC"; then
    ok "monitoring.md §2 가 금액 규칙 세 가지 + **못 지우는 형태**까지 적는다"
  else
    ng "monitoring.md 의 금액 마스킹 설명이 코드와 다르다 (규칙을 빠뜨렸거나 구멍을 안 적었다)"
  fi
fi

# ============================================================================
sect "T8. 문서(monitoring.md)의 크론과 스크립트가 맞는가"

if [ -f "$DOC" ]; then
  # 문서에 적힌 monitor.sh 인자가 스크립트가 받는 것인가
  bad_args=""
  for a in $(grep -oE 'monitor\.sh --[a-z-]+' "$DOC" | awk '{print $2}' | sort -u); do
    grep -qE "^  $a\)|\|$a\)| $a\)" "$HERE/monitor.sh" || bad_args="$bad_args $a"
  done
  if [ -z "$bad_args" ]; then ok "문서의 monitor.sh 인자를 스크립트가 전부 받는다"
  else ng "문서에만 있는 인자:$bad_args"; fi

  # 배치 크론이 '매월 1일' 인가 — 기대월 공식의 전제다
  if grep -qE '^10 4 1 \* \* .*job-run\.sh market-index' "$DOC"; then
    ok "문서의 배치 크론이 '매월 1일 04:10' — 기대월 공식의 전제와 같다"
  else
    ng "배치 크론이 문서에서 바뀌었다 — market_expected_ym() 의 전제(매월 1일)를 다시 봐야 한다"
  fi
  if grep -qE '^\*/5 \* \* \* \* .*monitor\.sh --fast' "$DOC" && grep -qE '^5 9 \* \* \* +.*monitor\.sh --daily' "$DOC"; then
    ok "문서의 감시 크론 2줄이 그대로 있다"
  else
    ng "문서의 감시 크론이 스크립트 사용법과 어긋난다"
  fi
else
  skip "monitoring.md 를 못 찾음 ($DOC) — 서버 사본 실행이면 정상"
fi

# ============================================================================
sect "T9. job-run.sh 가 배치 로그를 0640 으로 만드는가 (SR36-2 ②)"

JL="$TMPROOT/joblog.log"
: >"$JL"; chmod 666 "$JL" 2>/dev/null
env RE_MON_STATE="$TMPROOT/s9" RE_MON_LOG="$TMPROOT/s9.log" RE_MON_DRY_RUN=1 \
    RE_MON_JOB_LOG="$JL" bash "$HERE/job-run.sh" selftest -- true >/dev/null 2>&1
M=$(stat -c %a "$JL" 2>/dev/null)
if [ "$PERM_OK" = "640" ]; then
  if [ "$M" = "640" ]; then ok "job-run.sh 가 로그를 0640 으로 맞춘다 (매 실행마다)"
  else ng "배치 로그가 $M 로 남는다"; fi
else
  if grep -q 'chmod 640 "\$LOGHINT"' "$HERE/job-run.sh"; then
    skip "0640 실측 — 이 파일시스템은 chmod 가 안 먹는다(윈도우). 코드에 chmod 는 있다. 리눅스에서 확인할 것"
  else ng "job-run.sh 에 배치 로그 chmod 가 없다"; fi
fi
# 기존 로그를 지우지 않는가 (: > 로 비우면 지난 기록이 날아간다)
printf 'old line\n' >"$JL"
env RE_MON_STATE="$TMPROOT/s9" RE_MON_LOG="$TMPROOT/s9.log" RE_MON_DRY_RUN=1 \
    RE_MON_JOB_LOG="$JL" bash "$HERE/job-run.sh" selftest -- true >/dev/null 2>&1
if grep -q 'old line' "$JL"; then ok "기존 배치 로그를 비우지 않는다"
else ng "배치 로그를 덮어썼다 — 지난 기록이 날아간다"; fi

# ============================================================================
sect "T10. 경보 볼륨 — 완결 0인 달이 끼면 사용자에게 몇 통이 가는가 (CR42-1 / SR38-8)"

# ⛔ 왜 이 검사가 생겼나 — **아무도 통수를 안 세어 봤다.**
#    문서는 *"월 1회 배치라 최악이어도 연 2~3통"* 이라고 적었는데, 같은 문단의 근거가
#    *"감시도 이미 같은 비교를 한다"* 였다. 둘을 같은 기준으로 맞췄으니 그 달에는
#    **감시도 매일 운다.** 실측 전제(scope='sido' 완결 0)로 전수로 돌리면 배치 몇 통이
#    아니라 **수십 통**이다. 그리고 그것은 전부 **조치할 수 있는 것이 하나도 없는** 알림이다 —
#    사람은 그 경보 키를 끄게 되고, 같은 키에 매달린 016 컬럼 누락이 함께 묻힌다.
#    → 그래서 여기서 **센다.** 세지 않으면 또 같은 일이 난다.
#
# ⚠️ 하루 단위 판정은 **달 단위로 묶어** 센다(속도). 근거: 감시는 매일 09:05 에 도는데
#    market_expected_ym 도 model_db_ym 도 그 시각에는 한 달 안에서 값이 안 바뀐다
#    (배치가 그 달 1일에 한 번만 돌기 때문). 날짜별 정확성은 T2 가 365일로 따로 본다.

# 서버 실측 전제: `scope='sido'` 완결이 0인 달.
#   2025-07·2025-08 은 시도 3곳 전부 미완결(실측), 2026-07 도 이미 0/3
#   (최소표본 1,422 < 문턱 ≈2,080 — 신고지연 30일이 다 지나도 못 넘는다).
INCOMPLETE_YMS=" 2025-07 2025-08 2026-07 "
db_ref() {   # $1 = 그 시점 배치가 만들 수 있는 최신 완결후보월 → DB 에 실제로 남는 REF
  local m="$1" i=0
  while [ "$i" -lt 30 ]; do
    case "$INCOMPLETE_YMS" in
      *" $m "*) ;;                       # 이 달은 미완결이라 REF 가 될 수 없다
      *) printf '%s' "$m"; return 0 ;;
    esac
    m=$(date -d "$m-01 -1 month" +%Y-%m) || return 1
    i=$((i + 1))
  done
  return 1
}

# 쿨다운은 **코드에서 읽는다** — 누가 조용히 바꾸면 이 검사가 죽어야 한다.
CD_STALE=$(grep -oE 'raise_alert marketstale [0-9]+' "$HERE/monitor.sh" | head -1 | awk '{print $3}')
CD_WARN=$(grep -oE 'raise_alert "warn_\$NAME" [0-9]+' "$HERE/job-run.sh" | head -1 | awk '{print $3}')
if [ -n "$CD_STALE" ] && [ -n "$CD_WARN" ]; then
  ok "쿨다운 상수를 코드에서 읽었다 (marketstale=${CD_STALE}초 · warn=${CD_WARN}초)"
else
  ng "쿨다운 상수를 코드에서 못 읽었다 (marketstale='$CD_STALE' warn='$CD_WARN') — 볼륨 계산의 근거가 없다"
fi
CD_STALE=${CD_STALE:-604800}; CD_WARN=${CD_WARN:-1728000}

# raise_alert 와 **같은 규칙**의 쿨다운 모형 (monitor-lib.sh 의 raise_alert)
SIM_LAST=""; SIM_SENT=0
sim_reset() { SIM_LAST=""; SIM_SENT=0; }
sim_raise() { # $1=지금(epoch) $2=쿨다운
  if [ -z "$SIM_LAST" ] || [ $(( $1 - SIM_LAST )) -ge "$2" ]; then
    SIM_SENT=$((SIM_SENT + 1)); SIM_LAST="$1"
  fi
}

# --- 억제 판정을 **코드에서 뽑아 행동으로** 돌린다 (CR43-2 · PASS 조건 2) -----
# ⛔ 예전에는 "후 = 0통" 이 계산이 아니라 **상수**였다(`:` 한 줄에 주석만 달려 있었다).
#    그래서 억제의 **극성**과 **쿨다운**이 관문에서 자유로웠고, 리뷰어가 심은 변이
#    2종이 통과 139 · 실패 0 · HARN 0 · rc=0 으로 **생존**했다:
#      M1  `if _market_batch_ran_this_month` 극성 반전
#          → 배치가 **아예 안 돈 달에 완전 침묵**. 크론이 사라져도 아무 신호가 없다.
#            그건 CR-042 가 PASS 조건 #1 로 지키라고 한 바로 그것이다.
#      M2  쿨다운 604800 → 31536000(1년)
#          → 진짜 미실행 183일에 27통이 **1통**. 그런데 관문은 `발송 1통` 을 화면에
#            **출력하면서** PASS 라고 적었다 — 하한(>0)과 "매일은 아니다"만 봤기 때문이다.
#    게다가 그 코드는 `docker`+`psql` 이 있어야 도달해서 **오늘까지 한 번도 실행된 적이
#    없었다.** 문자열 검사만으로 배포할 자리가 아니다.
#    → `check_market_stale()` 을 통째로 뽑아, 그것이 부르는 것들을 전부 가짜로 물리고
#      **발송 여부를 행동으로** 센다. docker 도 psql 도 필요 없다 —
#      **못 도는 검사는 없는 검사다.**
MS_OK=0; MS_CD=""; SIM_BATCH_RAN=0; SIM_NOW=0; MS_CLEARED=0; MS_CLEAR_MSG=""
eval "$(ext "$HERE/monitor.sh" check_market_stale)" 2>/dev/null
if ! declare -f check_market_stale >/dev/null 2>&1; then
  ng "monitor.sh 에서 check_market_stale() 을 못 뽑았다 — 억제의 방향·쿨다운을 행동으로 검증할 수 없다(문자열 검사로 되돌아간다)"
else
  MS_OK=1
  ok "억제 판정(check_market_stale)을 코드에서 뽑아 왔다 — 아래 통수는 **그것을 돌려서** 센 값이다"
  # 가짜 배선: 판정이 부르는 것을 전부 우리가 받는다. 발송은 sim_raise 로 흘린다.
  # 뽑아 온 함수는 monitor.sh 의 변수 두 개를 **알림 문구 안에서** 쓴다.
  # `set -u` 아래라 비어 있으면 그 자리에서 관문이 통째로 죽는다(실측: line 1395 에서
  # 중단돼 T10 뒷부분과 T11 이 아예 안 돌았다 — 조용한 미실행이라 더 나쁘다).
  MARKET_JOB_NAME="${MARKET_JOB_NAME:-market-index}"
  MARKET_INDEX_LOG="${MARKET_INDEX_LOG:-/var/log/realestate_market_index.log}"
  _market_batch_ran_this_month() { [ "$SIM_BATCH_RAN" = 1 ]; }
  add() { :; }
  blind_add() { :; }
  blind_add_daily() { :; }
  # ⛔ CR44-2 — 예전에는 `clear_alert() { :; }` 였다. 그러면 판정이 **거짓 해소**를
  #    내보내도 관문이 아무것도 못 본다. 실제로 변이 M3(판정 불가 조기 반환 제거)가
  #    `시장지수 기준월 회복 (n/a ≥ 기대 2026-06)` 을 내보내는데 T10 은 6통과/0실패였다.
  #    이 저장소가 같은 형태를 만나는 **네 번째** 자리다(CR-040 → CR42-3 → CR43-1 → 여기).
  #    → 센다. 그리고 아래에서 **부를 자격이 없는 입력**에 0 을 단언한다.
  clear_alert() { MS_CLEARED=$((MS_CLEARED + 1)); MS_CLEAR_MSG="${2:-}"; }
  raise_alert() { MS_CD="$2"; sim_raise "$SIM_NOW" "$2"; }
fi

# --- clear 를 부를 **자격** (CR44-2 · 변이 M3) ------------------------------
# ⛔ 이 라운드가 스스로 세운 규칙: *새 판정을 쓸 때 (가) 이 판정이 clear 를 부를 수
#    있는가, 부른다면 관문이 그것을 보는가* 를 먼저 정한다. 여기가 그 (가)다.
#    `clear_alert` 는 켜져 있던 경보를 지우고 "해소" 한 통을 **보낸다**. 판정 못 한
#    입력으로 그것을 하면 CR40-2 가 막은 거짓 해소이고, 사람은 문제가 풀린 줄 안다.
if [ "$MS_OK" = 1 ]; then
  for badref in "n/a" "none" ""; do
    MS_CLEARED=0; MS_CLEAR_MSG=""; sim_reset; SIM_BATCH_RAN=0; SIM_NOW=$(date +%s)
    check_market_stale "$badref" "2026-06"
    if [ "$MS_CLEARED" -eq 0 ]; then
      ok "(M3) 완결 기준월이 '${badref:-빈값}' 이면 해소 통보를 보내지 않는다 (판정 못 한 것을 회복이라 말하지 않는다)"
    else
      ng "(M3) ref='${badref:-빈값}' 인데 거짓 해소가 나간다 — 켜져 있던 경보가 지워진다" \
         "clear_alert ${MS_CLEARED}회 · 문구: ${MS_CLEAR_MSG}"
    fi
    if [ "$SIM_SENT" -eq 0 ]; then
      ok "(M3) 그 입력에서 경보도 보내지 않는다 (판정 불가는 경보도 해소도 아니다)"
    else
      ng "(M3) ref='${badref:-빈값}' 인데 경보가 ${SIM_SENT}통 나간다 — 없는 사실로 운다"
    fi
  done
  # ⚠️ **대칭.** 위 단언은 "clear 를 아예 안 부르게" 만들어도 초록이 된다.
  #    그러면 진짜 회복에서 경보가 영영 안 꺼지는 결함(= sshjournal 이 걸렸던 그것)을
  #    이 관문이 못 본다. 그래서 반대쪽도 함께 요구한다.
  MS_CLEARED=0; MS_CLEAR_MSG=""; sim_reset; SIM_BATCH_RAN=0; SIM_NOW=$(date +%s)
  check_market_stale "2026-07" "2026-06"
  if [ "$MS_CLEARED" -ge 1 ]; then
    ok "(M3 대칭) 기준월이 기대 이상이면 해소를 보낸다 (clear 경로가 살아 있다)"
  else
    ng "(M3 대칭) 정상 회복인데 해소가 안 나간다 — marketstale 이 한 번 뜨면 영영 안 꺼진다"
  fi
fi

SIM_START="2025-06-01"; SIM_MONTHS=16
old_batch=0; old_daily=0; old_clear=0
new_batch=0; new_daily=0; new_clear=0
prev_old_stale=0; prev_new_stale=0
warn_last=""; warn_sent=0; stale_days=0
sim_reset; SIM_BATCH_RAN=1        # 이 시나리오는 **배치가 돈** 달들이다
# ⛔ CR44-3 — `nz`/`harn_if` 가 T2·T3b 에만 들어가고 **이번 라운드가 새로 쓴 T10 에는
#    없었다.** 실측 두 방향: 날짜 계산이 한 번 비면 이 루프는 조용히 그 달을 건너뛰어
#    볼륨 모형이 91→61통으로 **약해지는데 전건 통과 · HARN 0** 이다(있는 결함을 놓친다 —
#    CR41-6 이 "더 나쁘다"고 한 방향). 그래서 빈 값을 **센다.**
T10_BAD=0
for mo in $(seq 0 $((SIM_MONTHS - 1))); do
  ms=$(date -d "$SIM_START +$mo month" +%Y-%m-01)
  ndays=$(date -d "$ms +1 month -1 day" +%d)
  if ! nz "$ms" "$ndays"; then T10_BAD=$((T10_BAD + 1)); continue; fi
  ndays=$((10#$ndays))
  # --- 배치 (매월 1일 04:10) ---
  bt=$(date -d "$ms 04:10" +%s)
  bexp=$(batch_expected_ym "$bt")
  bref=$(db_ref "$(model_db_ym "$bt")")
  nz "$bt" "$bexp" "$bref" || T10_BAD=$((T10_BAD + 1))
  if [ -n "$bexp" ] && [ -n "$bref" ] && [[ "$bref" < "$bexp" ]]; then
    # 옛 규칙: rc=1 → job_market-index (쿨다운 0) = 무조건 1통
    old_batch=$((old_batch + 1)); prev_old_stale=1
    # 새 규칙: rc=0 + `경고:` → warn_market-index (쿨다운 CD_WARN)
    if [ -z "$warn_last" ] || [ $((bt - warn_last)) -ge "$CD_WARN" ]; then
      warn_sent=$((warn_sent + 1)); warn_last="$bt"
    fi
    prev_new_stale=1
  else
    # 회복하면 양쪽 다 clear_alert 로 "해소" 한 통을 더 보낸다
    [ "$prev_old_stale" = 1 ] && { old_clear=$((old_clear + 1)); prev_old_stale=0; }
    [ "$prev_new_stale" = 1 ] && { new_clear=$((new_clear + 1)); prev_new_stale=0; }
  fi
  # --- 감시 (매일 09:05 · 한 달 안에서 값이 안 바뀌므로 한 번 재고 일수를 곱한다) ---
  d1=$(date -d "$ms 09:05" +%s)
  dexp=$(market_expected_ym "$d1")
  dref=$(db_ref "$(model_db_ym "$(last_batch_epoch "$d1")")")
  nz "$d1" "$dexp" "$dref" || T10_BAD=$((T10_BAD + 1))
  if [ -n "$dexp" ] && [ -n "$dref" ] && [[ "$dref" < "$dexp" ]]; then
    stale_days=$((stale_days + ndays))
    old_daily=$((old_daily + ndays))   # 옛 규칙: raise_alert dbstruct 86400 · 하루 한 번 = 매일 한 통
    # 새 규칙: **억제 코드에 하루씩 직접 물어본다.** 상수 0 을 적지 않는다 —
    #          그 상수가 M1(극성 반전)을 통째로 못 보게 만들던 자리다.
    if [ "$MS_OK" = 1 ]; then
      dd=1
      while [ "$dd" -le "$ndays" ]; do
        SIM_NOW=$((d1 + (dd - 1) * 86400))
        check_market_stale "$dref" "$dexp"
        dd=$((dd + 1))
      done
    fi
  fi
done
harn_if "$T10_BAD" "T10 볼륨 모형(배치가 돈 달)" "날짜·기준월 계산이 빈 값을 냈다 — 아래 통수는 **검사 결과가 아니다**"
new_daily=$SIM_SENT                 # ← 계산된 값이다(상수 아님)
new_batch=$warn_sent
old_total=$((old_batch + old_daily + old_clear))
new_total=$((new_batch + new_daily + new_clear))

printf '        전 : 배치 %d통 + 일일 %d통 + 해소 %d통 = **%d통** (기준월이 밀린 날 %d일 / %d개월)\n' \
       "$old_batch" "$old_daily" "$old_clear" "$old_total" "$stale_days" "$SIM_MONTHS"
printf '        후 : 경고 %d통 + 일일 %d통 + 해소 %d통 = **%d통**\n' \
       "$new_batch" "$new_daily" "$new_clear" "$new_total"

if [ "$old_daily" -ge 40 ]; then
  ok "옛 규칙은 같은 ${SIM_MONTHS}개월에 일일 경보만 ${old_daily}통을 보냈다 — 이 검사가 그것을 붙잡는다"
else
  ng "옛 규칙 모형이 ${old_daily}통밖에 안 나온다 — 모형이 현실을 못 담고 있다(검사가 무의미해진다)"
fi
if [ "$MS_OK" = 1 ] && [ "$new_daily" -eq 0 ]; then
  ok "배치가 이미 말한 달에는 감시가 **한 통도 다시 보내지 않는다** (${old_daily}통 → ${new_daily}통 · 억제 코드를 ${stale_days}일치 돌려서 센 값)"
elif [ "$MS_OK" = 1 ]; then
  ng "감시가 배치와 같은 사실을 ${new_daily}통 다시 보낸다 — 억제의 극성이 뒤집혔다(M1)" \
     "배치가 돈 달인데 raise_alert 가 ${new_daily}회 불렸다"
fi
if [ "$new_total" -le 6 ]; then
  ok "${SIM_MONTHS}개월 전체 발송이 ${new_total}통이다 (완결 0인 달 3개 · 조치 불가 알림이 통로를 선점하지 않는다)"
else
  ng "${SIM_MONTHS}개월 발송이 ${new_total}통이다 — 여전히 많다"
fi

# ⚠️ **느슨해지지 않았는가** — 진짜 미실행은 여전히 잡혀야 한다.
#    배치가 2026-02 뒤로 아예 안 도는 시나리오(크론 소실)를 같은 모형으로 돌린다.
sim_reset; SIM_BATCH_RAN=0; MS_CD=""     # 이 시나리오는 **배치 기록이 없는** 달들이다
miss_days=0
FROZEN_REF=$(db_ref "$(model_db_ym "$(date -d '2026-02-01 04:10' +%s)")")
# ⛔ CR44-3 — `FROZEN_REF` 가 한 번 비면 아래 루프가 통째로 안 돌아 **실패 3 · HARN 0**
#    이 된다(없는 결함을 보고한다). 픽스처가 안 만들어진 것을 검사 실패로 말하지 않는다.
T10B_BAD=0
if ! nz "$FROZEN_REF"; then
  harn "T10 미실행 시나리오(3건)" "기준 REF 를 못 만들었다(date/db_ref 실패) — **검사 결과가 아니다**(하네스·환경 문제)"
else
for mo in $(seq 9 $((SIM_MONTHS - 1))); do          # 2026-03 ~ 2026-09
  ms=$(date -d "$SIM_START +$mo month" +%Y-%m-01)
  ndays=$(date -d "$ms +1 month -1 day" +%d)
  if ! nz "$ms" "$ndays"; then T10B_BAD=$((T10B_BAD + 1)); continue; fi
  ndays=$((10#$ndays))
  d1=$(date -d "$ms 09:05" +%s)
  dexp=$(market_expected_ym "$d1")
  nz "$d1" "$dexp" || T10B_BAD=$((T10B_BAD + 1))
  if [ -n "$dexp" ] && [ -n "$FROZEN_REF" ] && [[ "$FROZEN_REF" < "$dexp" ]]; then
    miss_days=$((miss_days + ndays))
    dd=1
    while [ "$dd" -le "$ndays" ]; do
      SIM_NOW=$((d1 + (dd - 1) * 86400))
      if [ "$MS_OK" = 1 ]; then
        check_market_stale "$FROZEN_REF" "$dexp"   # 울지 말지는 **억제 코드가** 정한다
      else
        sim_raise "$SIM_NOW" "$CD_STALE"
      fi
      dd=$((dd + 1))
    done
  fi
done
printf '        미실행 시나리오: 밀린 날 %d일 → 발송 %d통 (쿨다운 %d초)\n' "$miss_days" "$SIM_SENT" "$CD_STALE"
if [ "$SIM_SENT" -gt 0 ]; then
  ok "배치가 **아예 안 돌면** 감시가 여전히 운다 (${miss_days}일 → ${SIM_SENT}통 · 억제가 아니라 중복 제거다)"
else
  ng "배치가 안 도는데도 감시가 조용하다 — 중복을 없애면서 진짜 미실행까지 없앴다"
fi
if [ "$SIM_SENT" -lt "$miss_days" ]; then
  ok "그 경우에도 매일 울지는 않는다 (${miss_days}일 중 ${SIM_SENT}통 · 미해소 표시는 요약에 매일 남는다)"
else
  ng "미실행 시나리오에서 매일 운다 — 옛 볼륨 문제가 그대로다"
fi
# ⛔ **상한 단언 (PASS 조건 2).** 하한(>0)과 "매일은 아니다"만 보면 쿨다운을 몰래
#    늘려도 초록이다 — M2(1년)가 정확히 그렇게 생존했고, 관문은 `발송 1통` 을
#    눈앞에 출력하면서 PASS 라고 적었다. *"억제가 아니라 중복 제거"* 라는 말이
#    참이려면 **밀린 기간에 비례해 계속 와야** 한다. 쿨다운 7일이면 183일에 26~27통이
#    되므로, 여유를 두고 **밀린 날 10일당 최소 1통**을 요구한다.
min_sent=$((miss_days / 10))
if [ "$SIM_SENT" -ge "$min_sent" ]; then
  ok "미실행이 길어지면 통수도 비례해 는다 (${miss_days}일 → ${SIM_SENT}통 · 최소 기대 ${min_sent}통)"
else
  ng "미실행 ${miss_days}일에 ${SIM_SENT}통뿐이다 (최소 기대 ${min_sent}통) — 쿨다운이 늘어나 억제로 바뀌었다(M2)" \
     "억제 코드가 쓴 쿨다운: ${MS_CD:-?}초"
fi
# 그리고 억제 코드가 **실제로 쓴** 쿨다운이 위에서 소스로 읽은 값과 같은가.
# (다르면 우리가 엉뚱한 raise_alert 줄을 읽고 볼륨을 계산하고 있는 것이다)
if [ "$MS_OK" = 1 ] && [ -n "$MS_CD" ] && [ "$MS_CD" = "$CD_STALE" ]; then
  ok "억제 코드가 쓴 쿨다운(${MS_CD}초)이 소스에서 읽은 값과 같다 (계산의 근거가 실물이다)"
elif [ "$MS_OK" = 1 ]; then
  ng "억제 코드가 쓴 쿨다운(${MS_CD:-없음})이 소스에서 읽은 값(${CD_STALE})과 다르다 — 볼륨 계산의 근거가 어긋났다"
fi
fi
harn_if "$T10B_BAD" "T10 미실행 시나리오 날짜 루프" "날짜 계산이 빈 값을 냈다 — 위 3건은 **검사 결과가 아니다**"

# 가짜 배선을 걷어낸다 — 아래 구획이 **진짜** 함수를 쓰게 한다
unset -f check_market_stale _market_batch_ran_this_month add blind_add blind_add_daily 2>/dev/null
# shellcheck source=./monitor-lib.sh
. "$HERE/monitor-lib.sh" 2>/dev/null || true

# --- 억제 판정 함수를 **코드에서 뽑아 그대로** 돌린다 -------------------------
eval "$(ext "$HERE/monitor.sh" _market_batch_ran_this_month)" 2>/dev/null
if ! declare -f _market_batch_ran_this_month >/dev/null 2>&1; then
  ng "monitor.sh 에서 _market_batch_ran_this_month() 를 못 뽑았다 — 억제 규칙을 검증할 수 없다"
else
  SAVED_JOBS="$JOBS"; SAVED_MJN="${MARKET_JOB_NAME:-}"
  JOBS="$TMPROOT/jobs-sim"; MARKET_JOB_NAME=market-index; mkdir -p "$JOBS"
  if _market_batch_ran_this_month; then ng "status 파일이 없는데 '이번 달 돌았다'고 한다 (억제되면 미실행을 영영 못 잡는다)"
  else ok "status 파일이 없으면 '안 돌았다' — 감시가 운다"; fi
  printf 'last_start_at=%s\n' "$(date +%Y-%m-01) 04:10:12" >"$JOBS/market-index.status"
  if _market_batch_ran_this_month; then ok "이번 달 1일 기록이 있으면 '돌았다' — 감시는 침묵한다(배치가 이미 말했다)"
  else ng "이번 달 배치 기록이 있는데 '안 돌았다'고 한다 — 중복 발송이 그대로 난다"; fi
  printf 'last_start_at=%s\n' "$(date -d "$(date +%Y-%m-01) -1 month" +%Y-%m-%d) 04:10:12" >"$JOBS/market-index.status"
  if _market_batch_ran_this_month; then ng "지난달 기록을 '이번 달 돌았다'로 본다 — 크론이 사라져도 조용해진다"
  else ok "지난달 기록은 '이번 달 안 돌았다' — 크론 소실을 잡는다"; fi
  printf 'last_start_at=%s\n' "쓰레기값" >"$JOBS/market-index.status"
  if _market_batch_ran_this_month; then ng "깨진 값을 '돌았다'로 본다 (fail-open)"
  else ok "값이 깨졌으면 '안 돌았다' — 못 읽은 것을 '괜찮다'로 넘기지 않는다"; fi
  JOBS="$SAVED_JOBS"; MARKET_JOB_NAME="$SAVED_MJN"
fi

# --- 구조: 기준월이 dbstruct 키에서 실제로 분리됐는가 ------------------------
DBBLK=${MONSRC#*'--- ① 구조 이상 (dbstruct)'}
DBBLK=${DBBLK%%'--- ② 기준월 신선도'*}
# ⚠️ **주석은 빼고 코드만** 본다. 설명문에 낱말이 있다고 붉어지면 그건 검사가 아니라
#    낱말 세기다(이 검사 자신이 처음에 그렇게 짜여 한 번 붉었다 — 그래서 고쳤다).
DBCODE=$(printf '%s\n' "$DBBLK" | grep -v '^[[:space:]]*#')
if [ "$DBBLK" = "$MONSRC" ]; then
  ng "check_db_structure 에서 구조/기준월 구획을 못 찾았다 — 분리가 되돌려졌을 수 있다"
elif has "$DBCODE" '기준월'; then
  ng "기준월 판정이 아직 dbstruct 경보에 섞여 있다 — 016 컬럼 누락이 같은 키에 묻힌다" \
     "$(printf '%s' "$DBCODE" | grep -n 기준월 | head -3)"
else
  ok "기준월이 dbstruct 키에서 분리됐다 (016 컬럼 누락과 다른 경보 키를 쓴다)"
fi
MSBLK=${MONSRC#*'--- ② 기준월 신선도'}
if has "$MSBLK" '_market_batch_ran_this_month' && has "$MSBLK" 'raise_alert marketstale'; then
  ok "기준월 경보가 **배치 실행 기록을 먼저 확인**한 뒤에만 나간다"
else
  ng "기준월 경보가 배치 기록을 안 보고 나간다 — 배치가 한 말을 매일 되풀이한다"
fi
# 뽑아서 돌린 함수가 **진짜로 불리는가**. 안 불리면 위 행동 검사 전부가 죽은 코드를
# 시험한 것이 된다(검사를 통과시키려고 함수만 남겨 두는 형태를 여기서 막는다).
if has "$MONSRC" 'check_market_stale "$ref" "$expected"'; then
  ok "check_db_structure 가 그 판정 함수를 실제로 부른다 (죽은 코드를 시험한 것이 아니다)"
else
  ng "check_market_stale() 이 아무 데서도 안 불린다 — 위 행동 검사가 죽은 코드를 돌린 것이다"
fi

# ============================================================================
sect "T11. 배치 등급 — 성공(rc=0)인데 확인할 것이 있을 때 (CR42-1 / SR38-8)"

# ⛔ 배치는 51초에 전 행을 적재했고 안 오른 것은 완결 플래그 하나인데, 사용자가 받는
#    문장은 **"배치 실패"** 였다. 도메인 코드 자신이 그 달을 *"보수적인 쪽의 오류"* 라고
#    적어 놓은 상태에서 말이다. 등급을 나누되 **숨기지는 않는다** — 그것을 여기서 본다.
J11="$TMPROOT/j11.log"; : >"$J11"
runjob() { # $1=상태이름 $2=배치가 낼 출력·종료코드
  local st="$TMPROOT/$1"
  env RE_MON_STATE="$st" RE_MON_LOG="$st.log" RE_MON_DRY_RUN=1 RE_MON_JOB_LOG="$J11" \
      bash "$HERE/job-run.sh" wtest -- bash -c "$2" 2>&1
}
OUTW=$(runjob w1 'echo "2026-09-01 04:11:03 [market-index] 경고: 기준월(sido) 가 2026-06 에서 멈췄다(기대 2026-07) — 표본 부족"; exit 0')
RCW=$?
if [ "$RCW" = 0 ]; then ok "경고만 있는 배치는 **종료코드 0** 으로 끝난다 (last_success_at 이 굳지 않는다)"
else ng "경고인데 종료코드가 $RCW 다 — 여전히 실패로 기록된다"; fi
want "$TMPROOT/w1.log" 'ALERT warn_wtest' "성공+경고는 **별도 키(warn_)** 로 한 통 간다" \
     "성공+경고인데 아무 신호도 안 간다 — 조용히 넘긴다"
avoid "$TMPROOT/w1.log" 'ALERT job_wtest' "성공+경고를 '배치 실패'라고 부르지 않는다" \
      "성공했는데 '배치 실패: wtest' 가 나간다 (사실과 다른 문장)"
if has "$OUTW" '배치 실패'; then ng "알림 본문에 '배치 실패' 가 들어간다"
else ok "알림 본문이 '성공했다 · 확인할 것이 있다' 로 나간다"; fi
if has "$OUTW" '경고: 기준월'; then ok "경고 사유 줄이 그대로 실린다 (무슨 일인지 알 수 있다)"
else ng "경고 사유가 알림에 안 실린다 — 등급만 낮추고 내용을 없앴다"; fi
if grep -q '^last_rc=0' "$TMPROOT/w1/jobs/wtest.status" 2>/dev/null &&
   grep -qE '^last_success_at=[0-9]' "$TMPROOT/w1/jobs/wtest.status" 2>/dev/null; then
  ok "status 에 last_rc=0 · last_success_at 이 갱신된다 (한 달 굳던 것이 풀린다)"
else ng "status 가 성공으로 안 남는다" "$(tr '\n' ' ' <"$TMPROOT/w1/jobs/wtest.status" 2>/dev/null)"; fi

# ② 경고가 사라지면 해소된다 (켜지기만 하고 안 꺼지는 경보는 곧 무시된다)
runjob w1 'echo "정상"; exit 0' >/dev/null 2>&1
want "$TMPROOT/w1.log" 'ALERT-CLEARED warn_wtest' "경고가 사라지면 해소 통보가 간다" \
     "경고 경보가 영영 안 꺼진다 — 미해소 표시가 계속 남는다"
if [ ! -f "$TMPROOT/w1/alerts/warn_wtest.active" ]; then ok "해소되면 .active 도 지워진다"
else ng "해소 통보는 갔는데 .active 가 남는다"; fi

# ③ **진짜 실패는 그대로 잡힌다** — 등급을 나눈 것이 느슨해진 것이 아님을 여기서 본다
OUTF=$(runjob w2 'echo "2026-09-01 [market-index] 실패: 적재 0행"; exit 1'); RCF=$?
if [ "$RCF" = 1 ]; then ok "실패한 배치는 여전히 0 이 아닌 코드로 끝난다"; else ng "실패인데 종료코드가 $RCF"; fi
want "$TMPROOT/w2.log" 'ALERT job_wtest' "rc≠0 은 예전 그대로 '배치 실패' 로 즉시 간다" \
     "진짜 실패가 안 잡힌다 — 등급을 나누면서 실패 경로를 죽였다"
if has "$OUTF" '실패: 적재 0행'; then ok "실패 사유 줄이 그대로 실린다"; else ng "실패 사유가 안 실린다"; fi

# ④ 배치 본체가 '행없음' 과 '(미완결)' 을 **다른 등급으로** 나누는가 (구조 검사)
MIS=$(cat "$HERE/market-index.sh")
MIBLK=${MIS#*'if [[ "$REF" < "$EXPECTED" ]]; then'}
MIBLK=${MIBLK%%$'\nfi\n'*}
if [ "$MIBLK" = "$MIS" ]; then
  ng "market-index.sh 에서 기준월 비교 블록을 못 찾았다"
else
  if has "$MIBLK" '(미완결)' && has "$MIBLK" 'warn "' && has "$MIBLK" 'fail "'; then
    ok "배치가 같은 블록에서 warn(미완결)과 fail(행없음)을 **둘 다** 쓴다"
  else
    ng "배치가 사유를 등급으로 나누지 않는다 (warn/fail 이 함께 있어야 한다)"
  fi
  if has "$MIBLK" 'STALE=1'; then ok "미완결은 STALE 로 표시되고 rc 는 0 이다"
  else ng "미완결을 rc=0 으로 내리는 표시가 없다"; fi
fi

# ============================================================================
printf '\n=====================================================\n'
printf '통과 %d · 실패 %d · 건너뜀 %d · 하네스오류 %d\n' "$PASS" "$FAIL" "$SKIP" "$HARN"
if [ "$HARN" -gt 0 ]; then
  printf '\n\033[35m⚠️  하네스오류 %d 건 — 이것은 **검사 결과가 아니다.**\033[0m\n' "$HARN"
  printf '   이 환경이 자기 임시파일을 못 만들었다는 뜻이다(TMPDIR=%s).\n' "${TMPDIR:-/tmp}"
  printf '   관문의 초록/빨강을 근거로 쓰려면 이 값이 먼저 0 이어야 한다 (SR38-9).\n'
fi
if [ "$FAIL" -eq 0 ] && [ "$HARN" -eq 0 ]; then exit 0; fi
exit 1
