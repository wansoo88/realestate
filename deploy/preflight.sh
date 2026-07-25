#!/usr/bin/env bash
# preflight.sh — 배포 전 서버 상태 점검. **읽기 전용이다.**
#
# 이 스크립트는 아무것도 바꾸지 않는다. 숫자를 보여줄 뿐이고,
# "지금 올려도 되는가"는 **사람이 판단한다**(G5).
#
# 사용:  bash deploy/preflight.sh
#
# 판정 기준
#   필요 메모리 = api 192MB + db 192MB = 384MB (docker-compose.deploy.yml)
#   itsmine 을 멈추면 그만큼(약 68MB) 여유가 는다.

set -uo pipefail          # -e 는 쓰지 않는다 — 점검 하나가 실패해도 나머지를 계속 본다

NEED_MB=384
API_PORT="${API_BIND_PORT:-8013}"
DOMAIN="${DOMAIN:-realestate.utilverse.info}"

ok()   { echo "  [OK]   $*"; }
warn() { echo "  [주의] $*"; }
bad()  { echo "  [위험] $*"; }

echo "=========================================================="
echo " realestate 배포 사전점검  ($(date '+%Y-%m-%d %H:%M:%S'))"
echo "=========================================================="

# --- 1. 메모리 -------------------------------------------------------------
echo
echo "[1] 메모리"
free -m | awk 'NR==1 || /^Mem:|^Swap:/ {print "  " $0}'

AVAIL=$(free -m | awk '/^Mem:/ {print $7}')
echo
echo "  현재 available : ${AVAIL} MB"
echo "  필요(api+db)   : ${NEED_MB} MB"

ITSMINE_MB=$(docker ps --filter "name=itsmine" --format '{{.Names}}' 2>/dev/null \
    | while read -r c; do
          docker stats --no-stream --format '{{.MemUsage}}' "$c" 2>/dev/null \
            | awk -F'/' '{print $1}' | sed 's/[^0-9.]//g'
      done | awk '{s+=$1} END {printf "%.0f", s+0}')
ITSMINE_MB=${ITSMINE_MB:-0}
echo "  itsmine 사용   : ${ITSMINE_MB} MB (중지 시 확보 가능)"

AFTER=$(( AVAIL + ITSMINE_MB ))
echo "  itsmine 중지 후: ${AFTER} MB"

if   [[ $AVAIL -ge $((NEED_MB + 64)) ]]; then ok "여유 충분 — itsmine 중지 없이 가능"
elif [[ $AFTER -ge $((NEED_MB + 32)) ]]; then warn "itsmine 을 중지해야 함 (pause-itsmine.sh)"
elif [[ $AFTER -ge $NEED_MB ]];        then warn "itsmine 중지 후에도 여유가 얇다(<32MB). 사람 판단 필요"
else                                        bad "itsmine 중지해도 부족(${AFTER} < ${NEED_MB}). 배포 보류 권고"
fi

# --- 2. 디스크 -------------------------------------------------------------
echo
echo "[2] 디스크"
df -h / | awk 'NR==1 || NR==2 {print "  " $0}'
DISK_AVAIL_G=$(df -BG / | awk 'NR==2 {gsub(/G/,"",$4); print $4}')
if [[ ${DISK_AVAIL_G:-0} -ge 5 ]]; then ok "여유 ${DISK_AVAIL_G}GB"
else bad "여유 ${DISK_AVAIL_G}GB — 이미지 빌드(약 1GB)+DB 에 부족할 수 있음"; fi

# --- 3. 포트 충돌 ----------------------------------------------------------
echo
echo "[3] 포트 (api 바인드: 127.0.0.1:${API_PORT})"
if command -v ss >/dev/null 2>&1; then LISTEN=$(ss -lntp 2>/dev/null); else LISTEN=$(netstat -lntp 2>/dev/null); fi
if echo "$LISTEN" | grep -qE "[:.]${API_PORT}[[:space:]]"; then
    bad "${API_PORT} 이미 사용 중:"
    echo "$LISTEN" | grep -E "[:.]${API_PORT}[[:space:]]" | sed 's/^/        /'
    echo "        → .env 의 API_BIND_PORT 와 nginx proxy_pass 를 같이 바꾸세요"
else
    ok "${API_PORT} 사용 가능"
fi
for p in 80 443; do
    echo "$LISTEN" | grep -qE "[:.]${p}[[:space:]]" \
        && ok "${p} 사용 중 (호스트 nginx — 정상)" \
        || warn "${p} 미사용 — 호스트 nginx 가 안 돌고 있을 수 있음"
done
echo "$LISTEN" | grep -qE "[:.](5432|6379)[[:space:]]" \
    && bad "5432/6379 가 열려 있음 — DB/Redis 외부 노출 확인 필요 (security.md §4.2)" \
    || ok "5432/6379 미개방"

# --- 4. 기존 컨테이너 ------------------------------------------------------
echo
echo "[4] 기존 컨테이너 (건드리면 안 되는 것들)"
docker ps -a --format '  {{.Names}}\t{{.Status}}\t{{.Image}}' 2>/dev/null \
    || bad "docker 를 실행할 수 없음 (권한? 데몬?)"

echo
echo "  현재 메모리 사용 상위:"
docker stats --no-stream --format '    {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' 2>/dev/null \
    | sort -k2 -h -r | head -10

for n in realestate-api realestate-db; do
    docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$n" \
        && warn "$n 이 이미 존재 — 재배포라면 정상, 아니면 이름 충돌 확인" \
        || ok "$n 이름 미사용"
done

# --- 5. 배포 준비물 --------------------------------------------------------
echo
echo "[5] 준비물"
[[ -f .env ]] && ok ".env 존재" || bad ".env 없음 — DEPLOY.md §3 참조"
if [[ -f .env ]]; then
    for k in JWT_SECRET FIELD_ENCRYPTION_KEY POSTGRES_PASSWORD POSTGRES_USER POSTGRES_DB; do
        v=$(grep -E "^${k}=" .env 2>/dev/null | head -1 | cut -d= -f2-)
        [[ -n "$v" ]] && ok "${k} 설정됨" || bad "${k} 비어 있음"
    done
    # 값 자체는 절대 출력하지 않는다 — 길이만 본다
    fk=$(grep -E '^FIELD_ENCRYPTION_KEY=' .env | head -1 | cut -d= -f2- | tr -d '\r\n')
    [[ ${#fk} -eq 32 ]] && ok "FIELD_ENCRYPTION_KEY 길이 32" \
                        || bad "FIELD_ENCRYPTION_KEY 길이 ${#fk} (정확히 32여야 기동)"
    grep -qE '^DEBUG=true' .env && bad "DEBUG=true — 운영에서는 꺼야 함" || ok "DEBUG 꺼짐"
fi
[[ -d frontend/dist ]] && ok "frontend/dist 존재 ($(du -sh frontend/dist 2>/dev/null | cut -f1))" \
                       || warn "frontend/dist 없음 — 로컬 빌드 후 업로드 (DEPLOY.md §4)"
[[ -f config/tax_rules.yaml ]] && ok "config/tax_rules.yaml 존재" \
                               || bad "config/tax_rules.yaml 없음 — /affordability 가 503"

# --- 6. TLS / DNS ----------------------------------------------------------
echo
echo "[6] 도메인·인증서 (${DOMAIN})"
resolved=$(getent hosts "${DOMAIN}" 2>/dev/null | awk '{print $1}' | head -1)
[[ -n "$resolved" ]] && ok "DNS → ${resolved}" || warn "DNS 미해석 — A 레코드 확인"
[[ -d "/etc/letsencrypt/live/${DOMAIN}" ]] \
    && ok "인증서 존재" || warn "인증서 없음 — certbot 발급 필요 (DEPLOY.md §5)"
nginx -t >/dev/null 2>&1 && ok "현재 nginx 설정 문법 정상" \
                         || warn "nginx -t 실패 또는 권한 없음 (sudo 로 재확인)"

echo
echo "=========================================================="
echo " 점검 끝. **아무것도 변경하지 않았습니다.**"
echo " [위험] 항목이 있으면 배포하지 말고 PM 에 보고하세요."
echo "=========================================================="
