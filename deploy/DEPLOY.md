# DEPLOY.md — 1차 배포 절차 (api + db)

> 작성 `re-arch` · ORDER 2026-07-25-19-arch · 2026-07-25
> ⚠️ **이 문서의 모든 명령은 사람이 승인·실행한다(G5).** 에이전트는 서버를 건드리지 않았다.
> 서버 IP·계정·키 경로는 저장소에 없다 → `deploy-target.local.md` 참조.

---

## 0. 이번 배포의 범위 — 무엇이 되고 무엇이 안 되는가

**되는 것 (동기 기능)**
- 회원가입 · 로그인 (JWT)
- 내 자산 프로필 저장/조회 (AES-256-GCM 암호화)
- 실구매 가능 금액 계산 (`/affordability`)
- 지도 단지 조회 (`/map/complexes`, PostGIS bbox)

**안 되는 것 (2차)**
- **추천 (`POST /api/v1/recommendations`)** — 202 를 돌려주지만 **완료되지 않는다.**
  큐 소비자(`app/worker.py`)가 미구현이다. 사용자에게 이 상태를 알려야 한다.
- 실데이터 수집 (worker-ingest) · Redis 큐

**왜 이렇게 나눴나**: `worker.py` 는 미구현이라 종료코드 2 로 죽는데
`restart: unless-stopped` 와 만나면 무한 재시작 루프가 된다. 메모리도 모자란다.
worker·redis 를 빼면 그 문제가 **자동으로 사라지고** 필요 메모리도 줄어든다.

---

## 1. 사전점검 (변경 없음 — 먼저 이것부터)

```bash
cd <APP_ROOT>            # 예: /opt/realestate
bash deploy/preflight.sh
```

메모리·디스크·포트충돌·기존 컨테이너·준비물·DNS/인증서를 찍는다. **아무것도 바꾸지 않는다.**
`[위험]` 항목이 하나라도 있으면 **진행하지 말고 PM 에 보고**한다.

---

## 2. 메모리 계산 (이 배포가 들어갈 자리가 있는가)

실측 기준: available **332MB**, swap 2GB, autobtc 195MB, itsmine 68MB.

| 항목 | 상한 | 근거 |
|---|---:|---|
| `realestate-db` | **192 MB** | shared_buffers 64 + wal 2 + 백엔드 20×~3 + 상시 ~20 ≈ **146MB** → 여유 46MB |
| `realestate-api` | **192 MB** | 파이썬 런타임 ~120 + Argon2 2×19MiB=38 ≈ **158MB** → 여유 34MB |
| **합계** | **384 MB** | |

| 시나리오 | 여유 | 판정 |
|---|---:|---|
| 지금 그대로 | 332 MB | ❌ 384 > 332 — **부족** |
| itsmine 중지 후 | 332 + 68 = **400 MB** | ✅ 400 − 384 = **16 MB 남음** |

> **여유 16MB 는 얇다.** 그래서 두 가지를 미리 걸어 뒀다.
> 1. `ARGON2_CONCURRENCY=2` — 동시 해시를 4→2 로 줄여 api 를 38MB 아꼈다.
>    (파라미터가 아니라 **동시성**을 줄인 것이다. 파라미터를 깎으면 비밀번호
>    크래킹 난이도가 그대로 내려가지만, 동시성은 느려질 뿐 강도가 유지된다.)
> 2. nginx `re_auth` rate limit 1r/s — 로그인 폭주가 곧 메모리 폭주라
>    **rate limit 이 메모리 방어선이기도 하다.**
>
> `memswap_limit = mem_limit` 이라 우리 컨테이너는 **스왑을 쓰지 않는다.**
> 상한을 넘기면 스왑으로 새며 호스트 전체를 느리게 만드는 대신,
> 컨테이너만 깔끔히 OOM-kill 되고 재시작된다. 동거 서비스(autobtc)를 지키는 선택이다.
>
> preflight 가 보고한 실제 available 이 400MB 에 못 미치면 **배포를 보류**하고 보고한다.

---

## 3. `.env` 준비 (서버에서, 커밋 금지)

```bash
cd <APP_ROOT>
cp .env.example .env
```

`.env` 를 열어 아래를 채운다. **생성 커맨드는 서버에서 실행한다.**

```bash
# JWT_SECRET (32자 이상)
python3 -c "import secrets;print(secrets.token_urlsafe(48))"

# FIELD_ENCRYPTION_KEY (정확히 32바이트 — 틀리면 기동이 막힌다)
python3 -c "import secrets,string;a=string.ascii_letters+string.digits;print(''.join(secrets.choice(a) for _ in range(32)))"

# POSTGRES_PASSWORD
python3 -c "import secrets;print(secrets.token_urlsafe(24))"
```

| 키 | 값 |
|---|---|
| `POSTGRES_DB` | `realestate` |
| `POSTGRES_USER` | `realestate` |
| `POSTGRES_PASSWORD` | 위에서 생성 |
| `POSTGRES_HOST` | `db` (compose 가 덮어씀) |
| `JWT_SECRET` | 위에서 생성 |
| `FIELD_ENCRYPTION_KEY` | 위에서 생성 — **분실하면 저장된 자산 정보를 영영 복호화 못 한다. 별도 백업.** |
| `DEBUG` | `false` |
| `API_BIND_PORT` | `8013` (preflight 가 충돌 없다고 한 값) |
| `KAKAO_REST_API_KEY` | 카카오 개발자 콘솔 |
| `MOLIT_API_KEY` | 공공데이터포털 발급 후 (1차 배포엔 없어도 됨 — 수집은 2차) |
| `ANTHROPIC_API_KEY` | 추천 기능용 — **1차 배포엔 불필요** |

```bash
chmod 600 .env      # 다른 사용자가 읽지 못하게
```

---

## 4. 프론트 빌드 — **로컬에서 하고 결과물만 올린다**

```bash
# [로컬 PC 에서]
cd frontend
cp .env.example .env          # VITE_KAKAO_JS_APP_KEY 채우기
npm ci && npm run build       # → frontend/dist

# 업로드 (경로·계정은 deploy-target.local.md 참조)
rsync -avz --delete frontend/dist/ <DEPLOY_USER>@<DEPLOY_HOST>:<APP_ROOT>/frontend/dist/
```

> ⚠️ **서버에서 `npm run build` 를 돌리지 말 것.** vite/tsc 빌드가 이 서버의
> 남은 메모리보다 많이 먹어서, 빌드하다 **동거 실서비스가 OOM 될 수 있다.**
> `VITE_` 변수는 빌드 결과물에 그대로 박히므로 카카오 JS 키는
> 개발자 콘솔에서 **허용 도메인을 반드시 제한**한다.

---

## 5. 배포 실행 (여기부터 서버 상태가 바뀐다 — G5 승인 후)

### 5-1. itsmine 중지 (메모리 확보)
```bash
sudo bash deploy/pause-itsmine.sh --dry-run     # 무엇을 멈출지 먼저 확인
sudo bash deploy/pause-itsmine.sh               # 실제 중지
free -m
```
`docker stop` 만 한다. 컨테이너·이미지·볼륨을 지우지 않으므로 언제든 되돌아온다.

### 5-2. DB 기동 + 마이그레이션
```bash
docker compose -f docker-compose.deploy.yml up -d db
docker compose -f docker-compose.deploy.yml logs -f db     # "database system is ready" 까지
```
`backend/migrations/*.sql` 이 `docker-entrypoint-initdb.d` 로 **빈 볼륨 첫 기동에만**
001→002→003 순서로 자동 적용된다(CR-008 에서 검증된 경로).

확인:
```bash
docker exec realestate-db psql -U realestate -d realestate -c "\dt" | head -20
docker exec realestate-db psql -U realestate -d realestate \
  -c "SELECT extname FROM pg_extension WHERE extname IN ('postgis','citext');"
docker exec realestate-db psql -U realestate -d realestate \
  -c "SELECT count(*) FROM pg_tables WHERE schemaname='public';"   # 34 예상
```

### 5-3. API 빌드·기동
```bash
docker compose -f docker-compose.deploy.yml build api    # 수 분 소요
docker compose -f docker-compose.deploy.yml up -d api
docker compose -f docker-compose.deploy.yml ps
curl -fsS http://127.0.0.1:8013/api/v1/health            # {"status":"ok","role":"api"}
```

기동에 실패하면 `.env` 문제일 가능성이 높다(JWT_SECRET 32자↑, FIELD_ENCRYPTION_KEY 정확히 32).
```bash
docker compose -f docker-compose.deploy.yml logs api | tail -50
```

### 5-4. 호스트 nginx 서버블록
```bash
# 1) 배치 (기존 서버블록은 건드리지 않는다)
sudo cp deploy/nginx-realestate.conf /etc/nginx/sites-available/realestate.conf
sudo sed -i "s|<APP_ROOT>|$(pwd)|g" /etc/nginx/sites-available/realestate.conf
sudo ln -sfn ../sites-available/realestate.conf /etc/nginx/sites-enabled/realestate.conf

# 2) ⚠️ 반드시 문법 검사부터. 실패한 채 reload 하면 **동거 서비스까지 같이 죽는다.**
sudo nginx -t

# 3) 통과했을 때만
sudo systemctl reload nginx
```

### 5-5. TLS 발급
```bash
sudo certbot --nginx -d realestate.utilverse.info
sudo nginx -t && sudo systemctl reload nginx
sudo certbot renew --dry-run        # 자동 갱신 확인
```

### 5-6. 최종 확인
```bash
curl -fsS https://realestate.utilverse.info/api/v1/health
curl -sI https://realestate.utilverse.info | grep -i strict-transport
docker stats --no-stream
free -m
```
`docker stats` 의 MEM% 가 90% 를 넘으면 상한을 올리기 전에 **PM 에 보고**한다
(여유가 16MB 뿐이라 임의로 올리면 동거 서비스가 위험하다).

---

## 6. 롤백

문제가 생기면 **역순으로** 되돌린다. 각 단계는 독립적이라 필요한 것만 해도 된다.

```bash
# 1) 웹 노출 제거 (가장 먼저 — 사용자 영향 차단)
sudo rm /etc/nginx/sites-enabled/realestate.conf
sudo nginx -t && sudo systemctl reload nginx

# 2) 우리 컨테이너 중지 (데이터는 남는다)
docker compose -f docker-compose.deploy.yml down

# 3) itsmine 복구 — 가장 중요
sudo bash deploy/resume-itsmine.sh
docker ps
free -m
```

**DB 데이터까지 지우는 완전 초기화** (마이그레이션을 다시 태우고 싶을 때만):
```bash
docker compose -f docker-compose.deploy.yml down -v    # ⚠️ realestate-pgdata 볼륨 삭제
```
> `-v` 는 **저장된 사용자 계정·자산 정보를 전부 지운다.** 되돌릴 수 없다.
> `docker-entrypoint-initdb.d` 는 빈 볼륨에만 도므로, 마이그레이션 재적용에는
> 이 방법뿐이다(1차 배포 초기라 데이터가 없을 때만 안전).

---

## 7. 배포 후 남는 상태 (인수인계)

| 항목 | 상태 |
|---|---|
| itsmine | **중지됨** — 다시 쓰려면 `resume-itsmine.sh`, 단 메모리가 다시 부족해진다 |
| 추천 기능 | 202 만 반환, 완료되지 않음 (worker 미구현) |
| 수집 데이터 | 없음 — 지도에 단지가 안 보인다. 실데이터 적재는 2차 |
| 세율 | `config/tax_rules.yaml` 마운트. 바뀌면 파일 교체 후 `docker compose restart api` |
| 백업 | **미설정** — `pg_dump` 정기 백업이 없다. 2차 과제 |

---

## 8. 자주 나오는 문제

| 증상 | 원인 | 조치 |
|---|---|---|
| api 가 기동 직후 죽음 | `.env` 검증 실패 | `logs api` 확인. JWT_SECRET 32자↑, FIELD_ENCRYPTION_KEY 정확히 32 |
| `/affordability` 가 503 `TAX_RULES_UNAVAILABLE` | `config/` 마운트 누락 또는 `status != verified` | compose 의 `./config:/srv/config:ro` 확인 |
| 로그인이 503 `BUSY` | Argon2 동시 한도 | 정상 동작(SR8-1/8-2). 잦으면 `ARGON2_CONCURRENCY` 조정 — **단 메모리 재계산 먼저** |
| nginx reload 실패 | `limit_req_zone` 이름 충돌 | `nginx -t` 메시지 확인. zone 이름 `re_api`/`re_auth` 를 다른 이름으로 |
| 지도에 단지가 없음 | 수집 데이터 없음 | 정상 — 실데이터 적재는 2차 |
| db OOM-kill | 상한 192MB 초과 | `docker inspect realestate-db --format '{{.State.OOMKilled}}'`. PM 보고 후 조정 |
