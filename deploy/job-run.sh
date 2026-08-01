#!/usr/bin/env bash
# ============================================================================
# job-run.sh — 크론 배치를 감싸서 "조용한 실패"를 없앤다
#
# 배치 경로: /opt/realestate/scripts/job-run.sh
# 사용:      job-run.sh <이름> -- <명령...>
# 크론 예:   10 4 1 * * umask 027 && /opt/realestate/scripts/job-run.sh market-index -- \
#              /opt/realestate/scripts/market-index.sh >> /var/log/realestate_market_index.log 2>&1
#
# 왜 필요한가
#   크론은 종료코드를 로그에 남기지 않는다. market-index.sh 는 실패 시 0 이 아닌
#   코드로 끝나도록 잘 만들어져 있지만, **그 코드를 아무도 읽지 않는다**.
#   이 래퍼가 읽고, 알리고, 기록한다.
#
# 알림에 무엇을 넣는가 — 최소한만
#   배치 로그 원문을 그대로 보내면 안 된다. psycopg 트레이스백은 DATABASE_URL
#   (비밀번호 포함)을 그대로 뱉는다. 그래서 보내는 것은
#     ① 종료코드 ② 소요시간 ③ 우리가 직접 쓴 `실패:`/`경고:` 줄 1개 ④ 로그 파일 경로
#   뿐이고, 그마저 monitor-lib.sh 의 scrub() 를 통과한다.
#
# 등급이 **둘**인 이유 (CR42-1 / SR38-8)
#   이 래퍼는 오랫동안 “rc≠0 = 배치 실패” 하나만 알았다. 그러자 배치는
#   **조치할 것이 없는 상태**까지 rc=1 로 말할 수밖에 없었고(시장지수 기준월이
#   표본 부족으로 안 오르는 달), 사용자는 *"배치 실패"* 를 받았다 — 사실과 다르고
#   `last_success_at` 까지 한 달 굳었다. 그래서 배치가 **성공(rc=0)했지만 알려야 할
#   것이 있는** 등급을 만들었다: 배치가 `경고:` 로 시작하는 줄을 찍으면
#   **별도 경보 키 `warn_<이름>`** 로 쉼도를 두고 보낸다.
#   ⚠ 이건 약화가 아니다 — rc≠0 은 예전과 똑같이 쉼도 0 으로 즉시 간다.
#     바뀐 것은 **어느 상태를 어느 이름으로 부르느냐** 뿐이다.
# ============================================================================
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)
# shellcheck source=./monitor-lib.sh
. "$HERE/monitor-lib.sh" || { echo "monitor-lib.sh 를 못 읽음 ($HERE)" >&2; exit 3; }

if [ $# -lt 2 ]; then
  echo "사용법: $0 <이름> -- <명령...>" >&2
  exit 2
fi
NAME="$1"; shift
[ "${1:-}" = "--" ] && shift
if [ $# -lt 1 ]; then echo "실행할 명령이 없다" >&2; exit 2; fi

case "$NAME" in
  *[!A-Za-z0-9_-]*) echo "이름에 영문/숫자/_/- 만 쓸 수 있다: $NAME" >&2; exit 2 ;;
esac

STATUS="$JOBS/$NAME.status"
LOCK="$JOBS/$NAME.lock"
LOGHINT="${RE_MON_JOB_LOG:-/var/log/realestate_${NAME//-/_}.log}"

# --- 배치 로그를 0640 으로 (SR36-2) -----------------------------------------
# 크론 리다이렉트(`>> ...log`)가 root umask 022 로 파일을 만들면 **0644** 가 된다.
# 이 프로젝트는 0644 로그에서 실제로 유출을 냈다(SR32-1). 서버에는 비밀번호가 살아
# 있는 비-root 계정(autobtc)과 공개 8080 서비스가 있어 로컬 열람 경로가 실재한다.
# ⚠️ 한 번 `chmod` 해 두는 것으로는 지속되지 않는다 — 파일이 지워지고 다시 생기면
#    umask 로 되돌아간다. 그래서 **매 실행마다** 맞춘다(크론 쪽 umask 027 과 이중).
#    `[ -e ]` 로 감싸는 이유: 이미 있는 로그를 `:` 로 비우면 지난 기록이 날아간다.
if [ -n "$LOGHINT" ]; then
  [ -e "$LOGHINT" ] || : >"$LOGHINT" 2>/dev/null
  chmod 640 "$LOGHINT" 2>/dev/null
fi

exec 9>"$LOCK" 2>/dev/null
# 잠금파일도 0600 으로 (SR38-5). flock 전용 빈 파일이고 상위가 0700 root 라
# 실질 노출은 없지만, kv_set/raise_alert 가 세운 원칙과 어긋난 채로 둔다면
# 그 원칙은 “가끔” 이 된다. umask 를 통째로 바꾸지 않는 이유는 monitor-lib.sh 참조.
chmod 600 "$LOCK" 2>/dev/null
if command -v flock >/dev/null 2>&1; then
  # 겹쳐 돌면 DB 를 두 배로 쓴다 — 192MiB 한계에서 그건 OOM 이다
  flock -n 9 || {
    log "job $NAME 이 이미 실행 중 — 이번 실행은 건너뜀"
    echo "$(date '+%F %T') [job-run] $NAME 이 이미 실행 중이라 건너뜀"
    exit 0
  }
fi

TMP=$(mktemp "${TMPDIR:-/tmp}/jobrun.$NAME.XXXXXX") || { log "job $NAME mktemp 실패"; exit 3; }
trap 'rm -f "$TMP"' EXIT

START=$(date +%s)
echo "$(date '+%F %T') [job-run] $NAME 시작: $*"
"$@" >"$TMP" 2>&1
RC=$?
END=$(date +%s)
DUR=$((END - START))

cat "$TMP"          # 크론이 리다이렉트한 로그 파일로 그대로 흘려보낸다
echo "$(date '+%F %T') [job-run] $NAME 종료코드=$RC ${DUR}초"

PREV_SUCCESS=$(sed -n 's/^last_success_at=//p' "$STATUS" 2>/dev/null | tail -1)
{
  echo "name=$NAME"
  echo "last_start_at=$(date -d "@$START" '+%F %T')"
  echo "last_rc=$RC"
  echo "last_duration_sec=$DUR"
  if [ "$RC" -eq 0 ]; then
    echo "last_success_at=$(date -d "@$END" '+%F %T')"
  else
    echo "last_success_at=${PREV_SUCCESS}"
    echo "last_failure_at=$(date -d "@$END" '+%F %T')"
  fi
} >"$STATUS"
chmod 600 "$STATUS" 2>/dev/null

if [ "$RC" -eq 0 ]; then
  log "job $NAME 성공 (${DUR}초)"
  clear_alert "job_$NAME" "배치 $NAME 다시 성공 (${DUR}초)"
  # 성공했지만 배치가 `경고:` 를 남겼으면 낮은 등급으로 한 통 보낸다.
  # 쉼도 20일: 월 1회 배치라 **한 달에 한 통**이고, 연속된 두 달(최단 2월=28일)은
  # 각각 받는다. 같은 달에 손으로 여러 번 돌려도 두 번째부터는 안 보낸다.
  WARN=$(LC_ALL=C grep -m1 -E '경고:' "$TMP" 2>/dev/null | tail -1)
  if [ -n "$WARN" ]; then
    raise_alert "warn_$NAME" 1728000 "배치 $NAME 은 **성공**했다(종료코드 0 · ${DUR}초). 다만 확인할 것이 있다 — 즉시 조치를 요구하는 알림이 아니다.
${WARN}
로그: $LOGHINT"
  else
    clear_alert "warn_$NAME" "배치 $NAME 경고 해소 (${DUR}초)"
  fi
else
  # 우리가 쓴 사유 줄만 골라 보낸다 (트레이스백 원문은 보내지 않는다)
  # LC_ALL=C: 배치 출력에 유효하지 않은 바이트가 섞여도 사유 줄을 놓치지 않게
  REASON=$(LC_ALL=C grep -m1 -E '실패:' "$TMP" 2>/dev/null | tail -1)
  raise_alert "job_$NAME" 0 "배치 실패: $NAME (종료코드 $RC · ${DUR}초)
사유: ${REASON:-<사유 줄 없음 — 로그를 직접 볼 것>}
로그: $LOGHINT"
fi

exit "$RC"
