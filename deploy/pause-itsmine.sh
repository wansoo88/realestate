#!/usr/bin/env bash
# pause-itsmine.sh — itsmine 컨테이너를 **중지만** 한다 (메모리 확보용)
#
# 왜 필요한가
#   이 서버 여유가 332MB 뿐이라 realestate(api+db, 384MB)를 올릴 자리가 없다.
#   itsmine(약 68MB)을 잠시 내려 자리를 만든다.
#
# ⛔ 이 스크립트가 하지 않는 것 (되돌릴 수 없게 만드는 것들)
#   · docker rm      — 컨테이너를 지우지 않는다
#   · docker rmi     — 이미지를 지우지 않는다
#   · volume 제거    — 데이터를 건드리지 않는다
#   · 설정 파일 수정 — itsmine 의 어떤 파일도 고치지 않는다
#   `docker stop` 은 컨테이너를 멈출 뿐이라 `resume-itsmine.sh` 로 그대로 되돌아온다.
#
# 사용:  sudo bash deploy/pause-itsmine.sh          # 실제 중지
#        sudo bash deploy/pause-itsmine.sh --dry-run  # 무엇을 멈출지만 확인

set -euo pipefail

MATCH="${ITSMINE_MATCH:-itsmine}"
STATE_FILE="${ITSMINE_STATE_FILE:-/var/tmp/realestate-itsmine-paused.txt}"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

echo "== itsmine 중지 (match: '${MATCH}') =="

# 실행 중인 것만 고른다. 이미 멈춰 있던 컨테이너를 목록에 넣으면
# resume 이 '원래 꺼져 있던 것'까지 켜 버린다.
mapfile -t RUNNING < <(docker ps --filter "name=${MATCH}" --format '{{.Names}}')

if [[ ${#RUNNING[@]} -eq 0 ]]; then
    echo "  실행 중인 itsmine 컨테이너가 없습니다. 할 일 없음."
    echo "  (이름이 다르면 ITSMINE_MATCH=<패턴> 로 지정하세요)"
    exit 0
fi

echo "  대상:"
for c in "${RUNNING[@]}"; do
    mem=$(docker stats --no-stream --format '{{.MemUsage}}' "$c" 2>/dev/null || echo "?")
    echo "    - ${c}  (${mem})"
done

if [[ $DRY_RUN -eq 1 ]]; then
    echo "  --dry-run 이므로 중지하지 않았습니다."
    exit 0
fi

# 되돌리기 위해 '내가 멈춘 것'만 기록한다. resume 은 이 파일만 본다.
printf '%s\n' "${RUNNING[@]}" > "${STATE_FILE}"
echo "  복구 목록 기록: ${STATE_FILE}"

for c in "${RUNNING[@]}"; do
    echo "  docker stop ${c}"
    docker stop "$c" >/dev/null
done

echo
echo "== 중지 후 메모리 =="
free -m | awk 'NR==1 || /^Mem:/'
echo
echo "되돌리려면:  sudo bash deploy/resume-itsmine.sh"
