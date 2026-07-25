#!/usr/bin/env bash
# resume-itsmine.sh — pause-itsmine.sh 가 멈춘 컨테이너를 되돌린다
#
# `pause-itsmine.sh` 가 남긴 목록에 있는 것만 켠다.
# "이름이 itsmine 인 걸 전부 start" 하지 않는 이유는, 원래부터 꺼져 있던
# 컨테이너까지 켜 버리면 그건 복구가 아니라 **상태 변경**이기 때문이다.
#
# 사용:  sudo bash deploy/resume-itsmine.sh
#        sudo bash deploy/resume-itsmine.sh --force   # 목록 없이 이름 매칭으로 복구

set -euo pipefail

MATCH="${ITSMINE_MATCH:-itsmine}"
STATE_FILE="${ITSMINE_STATE_FILE:-/var/tmp/realestate-itsmine-paused.txt}"
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

echo "== itsmine 복구 =="

if [[ -f "${STATE_FILE}" ]]; then
    mapfile -t TARGETS < <(grep -v '^[[:space:]]*$' "${STATE_FILE}")
    echo "  복구 목록: ${STATE_FILE} (${#TARGETS[@]}건)"
elif [[ $FORCE -eq 1 ]]; then
    # 목록이 사라진 비상 경로. 무엇을 켜는지 사람이 보고 판단하라고 출력한다.
    mapfile -t TARGETS < <(docker ps -a --filter "name=${MATCH}" \
                                      --filter "status=exited" --format '{{.Names}}')
    echo "  ⚠️ 목록 파일이 없어 이름 매칭으로 찾았습니다(--force):"
else
    echo "  복구 목록(${STATE_FILE})이 없습니다."
    echo "  pause 를 실행한 적이 없거나 이미 복구했습니다."
    echo "  그래도 강제로 복구하려면: sudo bash deploy/resume-itsmine.sh --force"
    exit 0
fi

if [[ ${#TARGETS[@]} -eq 0 ]]; then
    echo "  복구할 컨테이너가 없습니다."
    exit 0
fi

FAILED=0
for c in "${TARGETS[@]}"; do
    if ! docker inspect "$c" >/dev/null 2>&1; then
        echo "  ⚠️ ${c} 컨테이너가 존재하지 않습니다 — 건너뜁니다"
        FAILED=1
        continue
    fi
    echo "  docker start ${c}"
    docker start "$c" >/dev/null || { echo "  ❌ ${c} 기동 실패"; FAILED=1; }
done

echo
docker ps --filter "name=${MATCH}" --format '  {{.Names}}\t{{.Status}}'

if [[ $FAILED -eq 0 && -f "${STATE_FILE}" ]]; then
    rm -f "${STATE_FILE}"
    echo "  복구 완료 — 목록 파일 삭제"
else
    # 하나라도 실패하면 목록을 남긴다. 지워 버리면 무엇이 안 돌아왔는지 잃는다.
    echo "  ⚠️ 일부 실패 — 목록 파일을 남겨 둡니다: ${STATE_FILE}"
    exit 1
fi

echo
free -m | awk 'NR==1 || /^Mem:/'
