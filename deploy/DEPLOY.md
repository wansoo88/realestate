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
| **합계** | **384 MB (상한)** | **304 MB (추정 실사용)** |

**두 수치를 구분해서 봐야 한다.** 384MB 는 *두 컨테이너가 동시에 상한에 붙은 최악값*이고,
304MB(146+158)가 *평상시 예상 사용량*이다. 아래 표는 둘 다 적는다.

| 시나리오 | 여유 | vs 상한 384 | vs 추정 304 |
|---|---:|---|---|
| 지금 그대로 | 332 MB | ❌ 부족 (−52) | ⚠️ 28MB 남음 |
| **itsmine 중지 후** | **400 MB** | ✅ **16 MB 남음** | ✅ **96 MB 남음** |

즉 **평상시에는 96MB 정도 여유**가 있고, 16MB 는 최악의 순간에만 해당한다.
운영 판단은 최악값 기준으로 하되, "항상 16MB 밖에 없다"고 오해하지 말 것.

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

### 5-1b. 서버 소스 갱신 — **빌드보다 먼저** (2회차 이후 배포는 여기서 시작)

서버의 `/opt/realestate` 는 **자동으로 갱신되지 않는다.** 이걸 건너뛰면 §5-2 가 **낡은 소스로
이미지를 빌드**하고, §5-3b 는 새 마이그레이션 파일을 못 찾고, §5-5b 는 `manage_users.py` 가 없다고
멈춘다(CR-025 DEPLOY-2).

```bash
cd /opt/realestate
git fetch origin && git reset --hard origin/main
git log --oneline -1                     # 배포하려는 커밋인지 눈으로 확인
ls backend/migrations/ | tail -3         # 새 마이그레이션이 실제로 왔는지
ls backend/scripts/manage_users.py       # 관리자 CLI 가 왔는지
```

> ⚠️ `git reset --hard` 는 서버의 로컬 수정을 버린다. 서버에서 직접 고친 게 있으면(예: 임시
> nginx 블록은 `/etc/nginx` 라 무관) 먼저 확인한다.

### 5-2. API 이미지 빌드 — **db 를 올리기 전에 한다**

```bash
docker compose -f docker-compose.deploy.yml build api    # 수 분 소요
docker images realestate-api:local
```

> ⚠️ **왜 db 보다 먼저인가.** `docker build` 는 **`mem_limit` 의 보호를 받지 않는다.**
> 상한은 런타임 서비스에만 적용된다. 즉 이 절차 전체에서 **유일하게 상한이 없는
> 메모리 소비자**가 빌드다. db 를 먼저 띄우면 그만큼(약 146MB) 줄어든 자리에서
> 빌드하게 되고, 여기서 OOM 이 나면 cgroup 이 아니라 **호스트 전역 OOM killer** 가 돈다.
> 그 희생자는 RSS 가 가장 큰 **autobtc(195MB)** 가 되기 쉽다.
> 순서만 바꾸면 빌드가 400MB 를 온전히 쓴다.
>
> 더 안전한 대안(프론트와 같은 원칙 — 서버에서 빌드하지 않기):
> ```bash
> # [로컬 PC 에서] 빌드해서 이미지만 옮긴다
> docker build -t realestate-api:local ./backend
> docker save realestate-api:local | gzip | \
>   ssh <DEPLOY_USER>@<DEPLOY_HOST> 'gunzip | docker load'
> ```
> 이 경우 compose 가 다시 빌드하지 않도록 `up -d --no-build api` 로 올린다.

### 5-3. DB 기동 + 마이그레이션
```bash
docker compose -f docker-compose.deploy.yml up -d db
docker compose -f docker-compose.deploy.yml logs -f db     # "database system is ready" 까지
```
`backend/migrations/*.sql` 이 `docker-entrypoint-initdb.d` 로 **빈 볼륨 첫 기동에만**
001→002→… 순서로 자동 적용된다(CR-008 에서 검증된 경로).

> ### ⛔ 두 번째 배포부터는 이 자동 적용이 **돌지 않는다**
> `docker-entrypoint-initdb.d` 는 **데이터 디렉터리가 비어 있을 때만** 실행된다.
> 지금 운영 볼륨에는 실데이터(거래 60만 행 이상)가 들어 있으므로 **영원히 실행되지 않는다.**
> 새 마이그레이션은 **반드시 아래 5-3b 로 손수 적용**해야 한다.
>
> 이걸 빠뜨리면 어떻게 되는가 — 조용히 넘어가지 않고 **전면 장애**가 된다.
> 새 코드는 `app_user.status`·`is_admin` 을 SELECT 하는데(`postgis.py` `_USER_COLUMNS`),
> 그 컬럼이 없으면 `UndefinedColumn` → **로그인·토큰검증 포함 모든 인증 경로가 500**.
> (fail-closed 라 보안 사고는 아니지만 서비스가 통째로 멈춘다 — CR-024 DEPLOY-1)

확인:
```bash
docker exec realestate-db psql -U realestate -d realestate -c "\dt" | head -20
docker exec realestate-db psql -U realestate -d realestate \
  -c "SELECT extname FROM pg_extension WHERE extname IN ('postgis','citext');"
docker exec realestate-db psql -U realestate -d realestate \
  -c "SELECT count(*) FROM pg_tables WHERE schemaname='public';"
```

### 5-3b. 새 마이그레이션 손수 적용 — **코드보다 먼저**

**순서가 중요하다: 마이그레이션 → 코드.** 반대로 하면 위의 500 이 난다.

```bash
cd /opt/realestate

# (1) 지금 무엇이 적용돼 있는지 사실 확인 — 문서나 기억이 아니라 DB 에 묻는다
docker exec realestate-db psql -U realestate -d realestate -c "
  SELECT column_name FROM information_schema.columns
   WHERE table_name='app_user' ORDER BY 1;"          # status·is_admin 이 있으면 009 적용됨
docker exec realestate-db psql -U realestate -d realestate -c "
  SELECT column_name FROM information_schema.columns
   WHERE table_name='recommendation_job' AND column_name='result_meta';"   # 있으면 010 적용됨
docker exec realestate-db psql -U realestate -d realestate -c "
  SELECT indexname FROM pg_indexes WHERE indexname='uq_poi_source_ref';"   # 있으면 011 적용됨
docker exec realestate-db psql -U realestate -d realestate -c "
  SELECT indexname FROM pg_indexes
   WHERE indexname='uq_school_district_source_ref';"                       # 있으면 012 적용됨
docker exec realestate-db psql -U realestate -d realestate -c "
  SELECT column_name FROM information_schema.columns
   WHERE table_name='school_district' AND column_name='school_level';"     # 있으면 013 적용됨
docker exec realestate-db psql -U realestate -d realestate -c "
  SELECT to_regclass('public.school_district_member');"                    # 있으면 013 적용됨
docker exec realestate-db psql -U realestate -d realestate -c "
  SELECT to_regclass('public.redev_project');"                             # 있으면 014 적용됨
docker exec realestate-db psql -U realestate -d realestate -c "
  SELECT to_regclass('public.market_price_index');"                        # 있으면 015 적용됨
docker exec realestate-db psql -U realestate -d realestate -c "
  SELECT column_name FROM information_schema.columns
   WHERE table_name='listing' AND column_name='created_by_user_id';"       # 있으면 016 적용됨

# (2) 백업 먼저 (파괴적이지 않아도 습관으로)
mkdir -p /root/realestate-backup
docker exec realestate-db pg_dump -U realestate -d realestate --schema-only \
  > /root/realestate-backup/schema-$(date +%Y%m%d-%H%M%S).sql

# (3) 미적용분만 순서대로. 파일은 모두 ADD COLUMN IF NOT EXISTS 라 재실행해도 안전하다
#     011 은 입지(F3) 수집의 멱등성(자연키)을 만든다 — 없으면 poi 재수집이 행을 쌓는다.
#     012 는 학구도(school_district)에 같은 자연키를 준다 — 학구도는 매년 3·9월
#     재배포되므로 없으면 재적재가 행을 쌓고 '배정 초등학교'가 어느 판인지 알 수 없어진다.
#     013 은 school_district.school_level 컬럼과 school_district_member 테이블을 만든다.
#     ⚠️ 코드(`postgis.py` `_SCHOOL_SQL`)가 이 둘을 **하드 참조**한다 — 빠뜨리면
#        UndefinedColumn 으로 **모든 입지 조회가 죽는다**(중·고 학구도 포함).
#     014 는 정비사업(재건축) 구역·매칭 테이블을 만든다. 없으면 추천의 '재건축' 축이
#     전 후보에서 '미확보'로 나가고, 001 의 추가분담금 칸(사용 금지)도 잠기지 않는다.
#     015 는 시장 가격지수(market_price_index) 표를 만든다 — 적정가 밴드의 시점 보정용.
#     ⚠️ 표만 만들 뿐 값은 배치가 채운다: `python scripts/build_market_index.py` (§5-3c).
#        비어 있어도 기능은 죽지 않고 **보정을 하지 않은 채** 동작한다(사유가 응답에 남는다).
#        다만 보정 없이는 서울 단지의 적정가 밴드가 평균 ~8% 낮게 나온다(§5-3c 실측).
#     016 은 `listing` 에 사용자 수동 입력 호가를 받는 칸(`created_by_user_id`·`as_of`)과
#     CHECK 제약을 더한다. 운영 `listing` 이 0행이라 가격·리스크 축이 죽어 있었고,
#     남은 합법적 경로가 사람이 손으로 옮겨 적는 것뿐이다(자세한 근거는 파일 머리말).
#     ⛔⛔ **016 은 코드보다 먼저다. 안 하면 지도와 추천이 통째로 죽는다.** (2026-07-29 실측)
#        피해 범위가 "수동 입력 API 만"이 아니다. 새 코드의 **읽기 경로 네 곳**이
#        016 의 신규 컬럼을 SQL 에서 하드 참조한다(`postgis.py`):
#          · `_BBOX_SQL`            → `complexes_in_bbox`      = **지도 전체**
#          · `_CANDIDATES_SQL_*`    → `recommendation_candidates` = **추천 후보 조회**
#          · `_SCOPE_STATS_*`(_AREA_MATCH_SQL) → `candidate_scope_stats` = 제외 사유 집계
#          · `_LISTINGS_SQL`        → `listings_for_complex`   = 후보의 호가 근거
#            (여기만 `li.as_of` 도 함께 참조한다 — 오류 메시지가 컬럼명이 달라 보인다)
#        016 없이 새 코드를 올리면 넷 다
#            `psycopg.errors.UndefinedColumn: column li.created_by_user_id does not exist`
#        로 실패한다 → 지도가 빈 화면이 되고 추천은 매번 error 로 끝난다.
#        013 과 같은 성격의 사고이며(그쪽은 입지 조회), 되돌리려면 016 을 적용하는 수밖에 없다.
#     ⚠️ 제약이 **출처와 소유자를 짝으로 강제**한다(`listing_user_source_pair`).
#        적용 시점 `listing` 0행이라 백필 대상이 없다 — 기존 행이 있었다면 전부
#        `created_by_user_id NULL`(= 수집분)이 되고 CHECK 도 그대로 만족한다.
#     ※ 운영 DB 에는 015 까지 **2026-07-28 적용 완료**(추가만 하는 마이그레이션 · 스키마 백업 후 실행).
#        016 은 미적용 — 배포 시 **코드 교체 전에** 적용한다.
for f in backend/migrations/009_user_approval.sql backend/migrations/010_job_result_meta.sql \
         backend/migrations/011_poi_natural_key.sql \
         backend/migrations/012_school_district_natural_key.sql \
         backend/migrations/013_school_level_and_zone_member.sql \
         backend/migrations/014_redevelopment_project.sql \
         backend/migrations/015_market_price_index.sql \
         backend/migrations/016_user_entered_listing.sql; do
  echo "--- $f ---"
  docker exec -i realestate-db psql -U realestate -d realestate -v ON_ERROR_STOP=1 < "$f"
done

# (4) 적용 확인 — (1)을 다시 돌려 컬럼이 생겼는지 눈으로 본다
#     016 은 컬럼만이 아니라 **CHECK 제약**까지 확인한다. 컬럼만 생기고 제약이 빠지면
#     출처와 소유자가 어긋난 행이 들어올 수 있고, 그 순간 "무엇이 근거였나"에 답할 수 없다.
docker exec realestate-db psql -U realestate -d realestate -c "
  SELECT conname FROM pg_constraint
   WHERE conrelid='listing'::regclass AND conname LIKE 'listing_user_%' ORDER BY 1;"
# 기대 — CHECK 제약 **7건** (ORDER BY 1 순서 그대로. 아래 목록과 한 줄씩 대조):
#   listing_user_area_range
#   listing_user_as_of
#   listing_user_dong_len
#   listing_user_floor_range
#   listing_user_note_len
#   listing_user_price_range
#   listing_user_source_pair
#     ⚠️ 016 이 만드는 CHECK 는 7개다(2026-07-29 운영 실측 `n_constraints = 7`).
#        예전 이 목록에는 층 범위 제약이 빠져 "6건"이라 적혀 있었다 — 7건이 나오는데
#        6건이라 적힌 목록은 확인 절차가 아니라 **혼란의 원인**이다(운영자가 멈추거나,
#        더 나쁘게는 세어 보지 않고 넘어간다). (CR35-5)
#        이 목록은 `test_절차서의_제약_확인_목록이_마이그레이션과_일치한다` 가
#        마이그레이션 파일과 대조한다 — 손으로 고치면 테스트가 먼저 깨진다.
```

> ⚠️ `psql` 에 `-v ON_ERROR_STOP=1` 을 반드시 준다. 없으면 **중간에 실패해도 0 으로 끝나** 실패가
> 성공으로 보인다.

> ### ⛔ 016 을 건너뛰고 코드만 올리면 — 되돌아오는 길이 하나뿐이다
> 마이그레이션이 먼저라는 규칙(§5-3b 머리말)이 016 에서 가장 세게 걸린다.
> `listing.created_by_user_id`(와 `listing.as_of`)는 수동 입력 API 만 쓰는 칸이 **아니라**
> 지도(`complexes_in_bbox`)· 추천 후보 조회(`recommendation_candidates`)·
> 제외 사유 집계(`candidate_scope_stats`)· 호가 근거 조회(`listings_for_complex`) SQL 이
> 모두 하드 참조한다. 없으면 네 경로가 동시에 `UndefinedColumn` 으로 죽어
> **지도는 빈 화면, 추천은 전건 error** 가 된다. 인증은 살아 있어서 "로그인은 되는데
> 아무것도 안 나오는" 형태라 원인을 짐작하기 어렵다 — 순서를 지키는 것이 유일한 예방이다.
> 이미 그 상태에 빠졌다면 016 을 적용하면 즉시 복구된다(코드 롤백 불필요).

### 5-3c. 시장지수 배치 — **적정가 밴드의 시점 보정** (015 적용 후)

015 는 빈 표만 만든다. 값을 채우는 것은 배치다. **외부 수집 없이 우리 `trade` 표만 읽어
계산**한다(네트워크·API 키 불필요).

```bash
cd /opt/realestate/backend
. .venv/bin/activate
export DATABASE_URL="postgresql+psycopg://realestate:<PW>@<DBIP>:5432/realestate"   # §5-5b 와 동일

python scripts/build_market_index.py --dry-run --scope sido --region 41   # 가장 무거운 한 곳만 확인
python scripts/build_market_index.py                                      # 전체(시군구+시도)
```

**2026-07-28 운영 실행 실측** (trade 611,518행 기준 · 같은 날 CR33-1 수정 후 재실행분)

| 항목 | 값 |
|---|---|
| 소요 | **47초** (시군구 82곳 + 시도 3곳, 지역 사이 0.4초 휴식 포함) |
| 적재 | **2,381행** (시군구 79곳 · 시도 3곳 × 최대 31개월) |
| 지수 없음 | 시군구 3곳(28710·41800·41820) — 월 표본 50건 미만. **시도 지수로 폴백** |
| db 메모리 | anon 64MB → **최대 77MB** (+13MB) · 한계 192MB |
| 가장 무거운 쿼리 | 경기 시도(339,470행) **4.6초** |
| postgres 재기동 | **없음** (`pg_postmaster_start_time` 불변) |
| 트랜잭션 | **지역 단위**(85개). 중간에 죽어도 앞선 지역은 남고, UPSERT 가 멱등이라 재실행하면 된다 |

> ⚠️ **메모리** — db 컨테이너는 `mem_limit 192MB` 이고 평상시 이미 ~137MB(anon 64 +
> shared_buffers 64)를 쓴다. 그래서 배치는 ① 지역 하나씩 돌고 ② 세션 `work_mem` 을
> **4MB** 로 낮춘다(서버 기본 2MB · 예전 값 12MB). 정렬이 디스크로 흘러 조금 느려지는
> 대신 컨테이너가 죽지 않는다. 실행 중 `docker stats` 의 `MEM USAGE` 가 192MB 에 닿는
> 것은 **page cache** 라 정상이다 — 위험 신호는 `memory.stat` 의 `anon` 이다.
>
> 실행 중 다른 무거운 작업(수집·지오코딩)을 겹치지 말 것.

**언제 다시 돌리나 — 한 번 돌리고 끝나는 배치가 아니다.**
지수의 **기준월**(환산 시점)은 이 표의 내용으로 정해진다. 재실행하지 않으면 새 실거래가
쌓여도 밴드는 계속 옛 기준월로 말한다. 틀린 값은 아니지만 점점 낡는다.
**실거래 수집 배치 뒤 월 1회** 재실행을 권장한다(멱등 UPSERT — 여러 번 돌려도 안전하다).

⚠️ **기준월이 언제 한 달 앞으로 가는지** — 완결 판정은 달력과 건수를 **둘 다** 본다
(`timeadjust._complete_flags`). 달력 조건은 *"그 달이 끝나고 신고 지연 30일까지 지났는가"*
이므로, **M월이 기준월 후보가 되는 것은 M말+30일 이후**다. 예: 2026-06 은 **2026-07-31**
부터 열린다. 그전에 돌리면 기준월이 2026-05 로 나오는데 그것이 정상이다.
(예전 판은 달력을 안 보고 건수만 봐서, 거래가 많은 4개 지역이 **진행 중인 달**(2026-07)을
기준월로 썼다 — 며칠 뒤 새 정보 없이 밴드가 바뀌는 상태였다. CR33-1.)

확인:
```bash
docker exec realestate-db psql -U realestate -d realestate -c "
  SELECT scope, count(DISTINCT region_code) AS regions, count(*) AS rows,
         max(ym) FILTER (WHERE is_complete AND sample_size>=150) AS ref_ym
    FROM market_price_index GROUP BY scope;"
# 기대: sido 3곳 · sigungu 79곳 · ref_ym 이 '오늘에서 30일 뺀 달'의 **직전 달**
# ⛔ ref_ym 에 진행 중인 달이 보이면 안 된다(그게 CR33-1 이다):
docker exec realestate-db psql -U realestate -d realestate -c "
  SELECT count(*) FROM market_price_index
   WHERE is_complete AND ym >= to_char(now() - interval '30 days', 'YYYY-MM');"
# 기대: 0
```

**적용 효과(운영 데이터 실측, 무작위 후보 360건)**: 밴드 중위가
**서울 +7.3% · 경기 +1.8% · 인천 +0.7%**(중위) 이동했다. 밴드 창이 넓을수록 크다
(6개월 +1.2% · 24개월 +5.3%). 고정 예산(서울 15억·경기 8억·인천 5억)에서
**'예산 안'이던 후보 259건 중 7건이 예산 초과로 바뀌었다** — 표시 오차가 아니라
**판정이 바뀌는 값**이다.
※ 위 수치는 CR33-1 수정 **전**(기준월 2026-06/07) 측정이다. 수정 후 재실행으로 기준월이
2026-05 로 내려가면서 밴드는 단지수 가중 평균 **−1.9%** 재조정됐다(지역별 −5.5% ~ +3.1%,
양방향). 방향이 갈리는 이유는 ① 한 달치 시점 차이 ② 시도 기준월도 2026-05 가 되면서
동률 tie-break 로 **시군구 지수를 쓰게 된 15개 구**(더 정밀한 지수로 바뀐 것)다.

### 5-3d. 이번 배포로 **지도 금액의 의미가 바뀐다** (CR34-3 · 배포 후 눈으로 확인할 것)

지도(`GET /map/complexes`)의 `recent_price_krw` 는 여전히 **최근 체결가 1건**이다.
바뀐 것은 **고르는 범위**다 — 사용자가 면적 조건을 걸면 그 조건 **안**의 최근 거래를 고른다.

왜 바꿨나 (운영 DB 실측 2026-07-29):
서울에서 55~65㎡ 를 가진 단지 400곳에 그 필터를 걸었을 때 **176곳(44%)** 의 표시가가
조건 **밖 면적**의 거래였고, 조건 안 최근 거래와 **평균 26.8%**(최대 168.6%) 어긋났다.
극단 사례: 대우디오빌 — 59㎡ 를 찾는 사용자에게 **30㎡ 체결가 3.05억**이 그 단지 가격으로
보였다(조건 안 최근 거래는 9.20억, **+201.6%**).

배포 후 확인:
```bash
# 면적 조건이 있는 요청과 없는 요청이 **다른 금액**을 내야 한다(같으면 배선이 안 걸린 것).
# (아래는 토큰이 필요한 인증 엔드포인트다 — 브라우저 개발자도구 Network 로 봐도 된다.)
docker exec realestate-db psql -U realestate -d realestate -c "
  WITH cx AS (SELECT id FROM complex WHERE name LIKE '대우디오빌%' LIMIT 1)
  SELECT '조건없음' AS q, price_krw, area_m2 FROM trade t, cx
   WHERE t.complex_id=cx.id AND NOT t.is_cancelled ORDER BY contract_date DESC LIMIT 1;"
```
* 조건에 맞는 거래가 **하나도 없으면 금액이 null** 이다(조건 밖 값으로 채우지 않는다).
  실측상 400곳 중 8곳(2%)이며, 화면은 그때 '해당 면적 실거래 없음'으로 보여야 한다.
* 성능 실측(warm 중위/최대 ms · 500개 상한): 강남송파 밀집 122.8/134 → 122.5/135,
  최대 bbox(2도)+면적조건 123.6/135 → **137.6/141**. 최악 +14ms — 1초 목표 대비 무시 가능.

> ⚠️ **지도 금액과 추천 카드 금액은 앞으로도 다르다.** 지도는 *체결된 1건*,
> 추천은 *창 중위를 기준월로 환산한 추정가*다. 실측(226단지)으로 격차를 분해하면
> 정의 차이 |중위| 5.8% · 시점 보정 |중위| 3.4% 이고 **67% 의 단지에서 정의 차이가 더 크다**
> — 지도를 시점 보정해도 두 값은 맞지 않는다. 그래서 서버가 각 값에 `price_basis` 를
> 붙여 무엇인지 말한다. 자금계획(`/affordability`)만은 `complex_id` 를 받으면 추천과
> **같은 함수**로 기준가를 만들어 값이 일치한다.

### 5-3e. 수집기 종료코드 계약 (cron 을 걸 때 반드시)

`scripts/fetch_academy.py` 는 이제 **부분 수집을 성공으로 끝내지 않는다**(CR33-6).

| 종료코드 | 뜻 | 운영자 조치 |
|---|---|---|
| 0 | 전량 수집 | 없음 |
| 1 | 실패 — **파일 없음**(인증키 오류·페이지네이션 고장) | 원인 해결 후 재실행 |
| 2 | 부분 수집 — **파일은 있으나 일부만** | 파일 안 `failures` 를 보고 그 교육청만 다시 |

`--allow-partial` 을 주면 2 대신 0 으로 끝난다. **cron 에는 쓰지 말 것** —
그 플래그는 "사람이 보고 넘기기로 했다"는 기록이다.
시장지수 크론 래퍼(`/opt/realestate/scripts/market-index.sh`)와 같은 규율이다.

> 아직 `fetch_academy` 는 cron 에 없다(수동 실행). 거는 날 이 표대로 래퍼를 쓸 것 —
> 로그만 남기고 0 으로 끝나면 몇 달 뒤 낡은 값을 보고도 아무도 모른다.

### 5-4. API 기동

> ⛔ **여기 오기 전에 §5-3b 가 끝나 있어야 한다.** 특히 **016**. 새 코드의 지도·추천
> 조회 SQL 이 `listing.created_by_user_id` 를 하드 참조하므로, 016 없이 API 를 띄우면
> 컨테이너는 정상 기동하고 헬스체크도 통과하는데 **지도가 빈 화면, 추천이 전건 error**
> 가 된다(§5-3b 참조). "떴으니 됐다"로 넘어가지 않도록 아래 확인을 반드시 한다.

```bash
docker compose -f docker-compose.deploy.yml up -d api    # 5-2 에서 이미 빌드됨
docker compose -f docker-compose.deploy.yml ps
curl -fsS http://127.0.0.1:8013/api/v1/health            # {"status":"ok","role":"api"}

# ⚠️ 헬스체크는 DB 컬럼을 안 본다. **지도를 실제로 한 번 불러 본다**(016 누락 탐지).
#    토큰이 필요하면 로그인 후 Authorization 헤더를 붙일 것.
curl -fsS "http://127.0.0.1:8013/api/v1/map/complexes?bbox=126.9,37.4,127.1,37.6&zoom=14" \
  -H "Authorization: Bearer <TOKEN>" | head -c 300
# 500 + 로그에 UndefinedColumn(li.created_by_user_id) → 016 미적용이다. §5-3b 로 돌아간다.
```

**(확인) 016 이 정말 사는지 — `/me/listings` 왕복 스모크 (SR-031 §9-10⑤)**

지도 조회는 `listing` 을 **읽기만** 한다. 016 의 쓰기 경로(제약 7건 · 소유자 컬럼)는
아래로 확인한다. 끝나면 지운 상태로 돌아간다 — 운영 데이터를 남기지 않는다.

```bash
API=http://127.0.0.1:8013/api/v1 ; H="Authorization: Bearer <TOKEN>"
CID=$(curl -fsS "$API/map/complexes?bbox=126.9,37.4,127.1,37.6&zoom=14" -H "$H" \
      | python3 -c "import json,sys;print(json.load(sys.stdin)['items'][0]['id'])")

LID=$(curl -fsS -X POST "$API/me/listings" -H "$H" -H 'Content-Type: application/json' \
  -d "{\"complex_id\":$CID,\"ask_price_krw\":900000000,\"area_m2\":84.97,
       \"as_of\":\"$(date +%F)\"}" | python3 -c "import json,sys;print(json.load(sys.stdin)['item']['id'])")

curl -fsS "$API/me/listings" -H "$H" | head -c 200      # items 1건 · source_label "사용자 입력"
curl -fsS -o /dev/null -w "%{http_code}\n" -X DELETE "$API/me/listings/$LID" -H "$H"   # 204

docker exec realestate-db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "select count(*) from listing;"     # 스모크 전후 모두 0 이어야 한다
```
> 실패 형태로 016 미적용을 가려낸다: `UndefinedColumn(created_by_user_id)` → 016 없음.
> `CheckViolation(listing_user_*)` → 제약은 있는데 값이 어긋난 것이니 입력을 먼저 본다.

기동에 실패하면 `.env` 문제일 가능성이 높다(JWT_SECRET 32자↑, FIELD_ENCRYPTION_KEY 정확히 32).
```bash
docker compose -f docker-compose.deploy.yml logs api | tail -50
# 예: "기동 점검 실패: JWT_SECRET 이 없거나 32자 미만입니다"
```

> ⚠️ **DEBUG=false 에서 아래 셋 중 하나라도 틀리면 API 는 기동을 거부한다**(SR29-1):
> `JWT_SECRET`(32자 이상) · `FIELD_ENCRYPTION_KEY`(정확히 32바이트) · `ARGON2_*`(OWASP 하한).
> **뜨지 않는 것이 의도된 동작이다** — 셋 다 잘못돼도 앱은 정상처럼 돌기 때문이다
> (빈 `JWT_SECRET` 으로도 토큰은 발급·검증된다 = 누구나 토큰을 위조할 수 있다).
> 로그에는 **항목 이름만** 남고 값은 남지 않는다.
> `POSTGRES_PASSWORD` 비어 있음·`COOKIE_SECURE=false` 는 **경고만** 하고 기동한다
> (전자는 첫 DB 접속에서 큰 소리로 죽고, 후자는 운영에서 Secure 가 강제되어 효력이 없다).

**(확인) 서버측 쿼리 상한이 실제로 붙었는가 — SR24-4**

`statement_timeout` 은 코드(`app/repositories/postgis.py:create_db_engine`)가 커넥션마다
세션 설정으로 붙인다(기본 10초, `DB_STATEMENT_TIMEOUT_MS` 로 조정). **DB 서버 전역 설정이
아니므로 `SHOW`를 psql 로 찍으면 0 이 나온다** — 반드시 API 컨테이너의 커넥션에서 확인한다.

```bash
docker exec realestate-api python -c "
from sqlalchemy import text
from app.core.config import get_settings
from app.repositories.postgis import create_db_engine
with create_db_engine(get_settings()).connect() as c:
    print('statement_timeout =', c.execute(text('SHOW statement_timeout')).scalar())"
# 기대: statement_timeout = 10s      (0 이면 상한이 없는 것이다 — 배포를 멈추고 원인을 찾는다)
```

> 왜 필요한가: 추천의 범위 통계 쿼리(`candidate_scope_stats`)가 `complex` 전역을 훑고,
> 방아쇠는 공격이 아니라 평범한 사용이다(평수 하한 1㎡ + 지역 '11' = 서울 전역).
> db 컨테이너는 `mem_limit`/`memswap_limit` 이 192m 라 스왑이 없다.
> **클라이언트 타임아웃은 서버 쿼리를 멈추지 못한다** — 연결이 끊겨도 쿼리는 계속 돈다.
> 상한에 걸리면 추천은 죽지 않고, 범위 통계 고지만 "시간 내에 끝나지 않아 숫자를
> 생략했습니다"로 바뀐다(조용히 사라지지 않는다).

### 5-5. 호스트 nginx + TLS — **반드시 이 순서로**

> ⚠️ **인증서가 먼저다.** 본 설정(`nginx-realestate.conf`)의 443 블록은
> `ssl_certificate .../fullchain.pem` 을 요구하는데 그 파일은 certbot 이 만든다.
> 없는 상태로 배치하면 `nginx -t` 가
> `[emerg] cannot load certificate ... No such file or directory` 로 실패하고,
> 이어지는 `certbot --nginx` 도 깨진 설정을 파싱하다 실패해 **절차가 막힌다.**
> 그래서 HTTP 전용 부트스트랩 블록으로 먼저 발급받는다.

**(0) 사전 문법검사 — 서버 상태를 전혀 바꾸지 않고 `nginx -t` 를 돌린다** (선택이지만 권장)

`/etc/nginx` 를 건드리기 전에 **격리된 곳에서** 같은 nginx 바이너리로 문법을 본다.
여기서 통과하면 (3)에서 실패할 이유가 거의 없다 — 실패는 곧 동거 서비스 위험이다.

```bash
T=$(mktemp -d); mkdir -p "$T/logs" "$T/cert"
# 인증서는 문법검사용 자가서명이면 된다(실제 발급물과 무관, $T 안에서만 산다)
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=test" \
  -keyout "$T/cert/privkey.pem" -out "$T/cert/fullchain.pem" 2>/dev/null

sed -e "s|<APP_ROOT>|$(pwd)|g" \
    -e "s|/etc/letsencrypt/live/realestate.utilverse.info|$T/cert|g" \
    deploy/nginx-realestate.conf > "$T/realestate.conf"

# error_log 는 main 컨텍스트에 둔다 — `-e` 옵션은 nginx 1.19.5+ 라 1.18 에서는 못 쓴다
cat > "$T/nginx.conf" <<EOF
error_log $T/logs/error.log;
events {}
http {
    include $T/realestate.conf;
}
EOF

nginx -t -c "$T/nginx.conf" -p "$T" -g "pid $T/nginx.pid;"
rm -rf "$T"
```
> `-c/-p` 와 `$T` 안의 `error_log`·`pid` 로 설정·경로·로그·PID 를 전부 `$T` 로 돌리므로
> **`/etc/nginx` 와 실행 중인 nginx 는 손대지 않는다.**
> `syntax is ok / test is successful` 이 나와야 한다.
> CSP 값은 `map` 으로 한 번만 정의되므로, 이 검사가 통과하면 세 블록의 값은 자동으로 같다.
>
> **이 검사가 실제로 결함을 하나 잡았다(2026-07-26).** 설정에 `http2 on;` 이 있었는데
> 그 문법은 nginx 1.25.1+ 이고 이 서버는 **1.18.0** 이다. 그대로 (3)에 갔으면
> `unknown directive "http2"` 로 절차가 막혔을 것이다 — 지금은 `listen ... ssl http2` 다.
> 서버 nginx 버전은 `nginx -v` 로 확인한다.
>
> Report-Only 변형도 같은 방법으로 미리 검사할 수 있다(§5-5(3) 의 sed 를 `$T/realestate.conf`
> 에 적용한 뒤 `nginx -t` 를 한 번 더).

> ### ⛔ 사이트 파일 이름은 **하나다** — `realestate.utilverse.info` (SR34-1)
> 이 절의 모든 블록이 **같은 파일**에 쓴다:
>
> ```
> /etc/nginx/sites-enabled/realestate.utilverse.info
>   -> ../sites-available/realestate.utilverse.info      ← nginx 가 실제로 읽는 파일
> ```
>
> **왜 굳이 못 박는가** — 2026-07-29 보안리뷰가 이 문서에서 이름이 **세 곳으로 갈린**
> 것을 실측했다. §5-5c 만 위 이름을 쓰고, §5-5(3)·(5)·부트스트랩·롤백은
> `realestate.conf` 를 썼다. 운영 서버에 `realestate.conf` 는 **없다.**
> 갈린 이유는 이력이다: §5-5c 는 나중에 **살아 있는 서버를 보고** 썼고, 나머지는 초안의
> 일반 이름이 그대로 남았다. 그대로 따르면 새 파일 하나가 생기고 끝난다 —
> `guard_site` 통과 · `nginx -t` 통과 · `reload` 성공, 그리고 **새 설정은 안 걸린다.**
> `<APP_ROOT>` 함정과 같은 종류다(전부 통과하는데 동작만 안 함).
>
> 그래서 ① 이름을 하나로 모았고, ② `guard_site` 가 **그 파일이 활성 사이트인지**까지
> 보고(④), ③ `backend/tests/test_deploy_config.py` 가 이 문서에 `/etc/nginx` 경로로
> 다른 이름이 다시 새어 들어오면 깨진다.
>
> ⚠️ 링크를 새로 만들어 두 파일을 동시에 활성화하지 말 것 — 같은 `server_name` 블록이
> 둘이 되면 nginx 는 **먼저 읽은 쪽**을 쓰고 경고만 낸다(`nginx -t` 는 통과한다).

**(1) 부트스트랩 블록 배치 — HTTP 전용, 인증서 참조 없음**

> 인증서가 **이미 있는 서버**(재배포)라면 이 단계는 건너뛴다 — 살아 있는 사이트 설정을
> HTTP 전용으로 덮어쓰게 된다. `ls /etc/letsencrypt/live/realestate.utilverse.info/` 로 먼저 본다.

```bash
sudo mkdir -p /var/www/certbot
sudo cp deploy/nginx-realestate-bootstrap.conf \
        /etc/nginx/sites-available/realestate.utilverse.info
sudo ln -sfn ../sites-available/realestate.utilverse.info \
             /etc/nginx/sites-enabled/realestate.utilverse.info
sudo nginx -t                       # 인증서를 참조하지 않으므로 통과한다
sudo systemctl reload nginx         # 통과했을 때만
```

**(2) 인증서 발급 (`certonly --webroot`)**
```bash
sudo certbot certonly --webroot -w /var/www/certbot -d realestate.utilverse.info
sudo ls -l /etc/letsencrypt/live/realestate.utilverse.info/fullchain.pem   # 존재 확인
```
> `--nginx` 가 아니라 `certonly --webroot` 를 쓰는 이유: `--nginx` 는 nginx 설정을
> **자동으로 고쳐 쓴다.** 동거 서비스 설정이 있는 서버에서 자동 수정은 위험하다.
> `certonly` 는 인증서만 받고 설정은 건드리지 않는다.

**(2.5) ⛔ `guard_site` — `nginx -t` 가 **안 보는 것**을 본다 (SR33-4)**

> ### `nginx -t` 는 경로를 검사하지 않는다
> 운영 서버에서 직접 확인했다(2026-07-29):
>
> | 설정 | `nginx -t` |
> |---|:--:|
> | `<APP_ROOT>` → `/opt/realestate` (정상) | **통과** |
> | `<APP_ROOT>` → `/nonexistent/does/not/exist` | **통과** |
> | `<APP_ROOT>` **미치환 그대로** | **통과** |
>
> 문법만 보기 때문이다. 그리고 이 함정으로 **운영 메인이 404 가 된 적이 있다** —
> 물증이 서버에 남아 있다(`realestate.error.log.2.gz`):
> `stat() "/tmp/tmp.BrOsTCkDTX/dist/" failed (13: Permission denied)` — `$(pwd)` 치환이
> 다른 디렉터리에서 돈 흔적이다. 그때 `nginx -t` 는 통과했고 reload 도 성공했다.
>
> 예전 가드는 `grep … && echo "진행 금지"` **한 줄**이었고 **중단하지 않았다.**
> 아래 함수는 실패하면 이어지는 `nginx -t`·`reload` 가 **아예 실행되지 않는다**(`&&` 연결).

```bash
# 아래 (3)·(5)·§5-5c 에서 그대로 쓴다. 셸을 새로 열면 다시 붙여넣는다.
guard_site() {
  local site="$1" approot="$2" d rc=0 roots target link hit=0

  # ⓪ ⛔ 파일이 비었는가 (SR35-2) — 같은 함정의 **세 번째 얼굴**
  #    ①은 "틀린 내용", ④는 "다른 파일", ⓪은 **"아무것도 없는 경우"** 다.
  #    빈 파일은 `nginx -t` 를 통과하고 reload 도 성공한다. 문법 오류가 없으니까.
  #    그리고 그 순간 이 사이트의 server 블록이 통째로 사라져 **서비스만 조용히 없어진다.**
  #    §5-5c 의 `sed … > "$SITE"` 리다이렉트는 원본 경로가 틀리면 **살아 있는 파일을
  #    먼저 비운다** — 그래서 아래에서 그 줄도 `.new` + `mv` 로 바꿨다.
  if [ ! -s "$site" ]; then
    echo "⛔ 설정 파일이 비었다: $site"
    echo "   → 빈 파일도 nginx -t 는 통과한다. 백업에서 되돌린다."
    return 1
  fi
  if ! grep -qE '^[[:space:]]*server_name[[:space:]]+' "$site"; then
    echo "⛔ server_name 이 없다 — 이 파일은 우리 사이트 설정이 아니다: $site"
    return 1
  fi

  # ① 치환 누락 — nginx -t 가 통과시키는 첫 번째 함정
  if grep -q '<APP_ROOT>' "$site"; then
    echo "⛔ <APP_ROOT> 가 치환되지 않았다: $site"; return 1
  fi

  # ② SPA 진입 문서가 실제로 있는가 — 없으면 메인이 404 다(nginx -t 는 통과한다)
  if [ ! -f "$approot/frontend/dist/index.html" ]; then
    echo "⛔ root 경로에 index.html 이 없다: $approot/frontend/dist/index.html"
    echo "   → 프론트 산출물을 먼저 올린다(§4 rsync). 서버에서 빌드하지 않는다."
    return 1
  fi

  # ③ 설정에 적힌 **모든** root 경로가 실재하는가(certbot webroot 포함)
  #    ⚠️ `for d in $(…)` 로 돌면 공백이 든 경로가 단어 분리된다(CR38-5). 줄 단위로 읽는다.
  roots=$(grep -oE '^[[:space:]]*root[[:space:]]+[^;]+' "$site" \
          | sed -E 's/^[[:space:]]*root[[:space:]]+//; s/[[:space:]]+$//')
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    [ -d "$d" ] || { echo "⛔ 존재하지 않는 root 경로: $d"; rc=1; }
  done <<EOF
$roots
EOF
  [ "$rc" -eq 0 ] || return 1

  # ④ ⛔ 이 파일이 **nginx 가 실제로 읽는 파일**인가 (SR34-1)
  #    ①~③ 은 전부 파일의 *내용*만 본다. 내용이 완벽해도 nginx 가 안 읽는 파일이면
  #    가드도·`nginx -t` 도·`reload` 도 성공하고 **바뀌는 것은 아무것도 없다.**
  #    실제로 이 문서가 그 상태였다(§5-5 머리말 참조).
  target=$(readlink -f "$site")
  for link in /etc/nginx/sites-enabled/*; do
    [ -e "$link" ] || continue                       # 글롭이 안 맞으면 문자열 그대로 온다
    [ "$(readlink -f "$link")" = "$target" ] && { hit=1; break; }
  done
  if [ "$hit" -ne 1 ]; then
    echo "⛔ 이 파일은 활성 사이트가 아니다: $site"
    echo "   → nginx 는 sites-enabled 에 링크된 파일만 읽는다. 지금 활성인 것:"
    ls -l /etc/nginx/sites-enabled/ | sed 's/^/     /'
    echo "   → SITE 를 위 파일 이름으로 맞춘다(§5-5 머리말)."
    echo "      ⚠️ 링크를 새로 만들어 둘 다 켜지 말 것 — 같은 server_name 이 둘이면"
    echo "         nginx 는 먼저 읽은 쪽만 쓰고 경고만 낸다."
    return 1
  fi

  echo "✅ 치환 완료 · root 경로 존재 · 활성 사이트 확인"
}
```

**(3) 본 설정으로 교체 — 단, CSP 는 `Report-Only` 로 먼저 올린다 (SR15-4)**

> ⚠️ **왜 두 단계인가.** CSP 를 잘못 좁히면 **지도가 죽는다.** 그런데 화면만 보면
> "지도가 안 보인다"까지만 알 수 있고 원인은 못 찾는다(타일 이미지가 막힌 건지,
> SDK 스크립트가 막힌 건지, 인라인 스타일이 막힌 건지). `Report-Only` 는
> **막지 않고 위반만 보고**하므로, 지도가 정상 동작하는 상태에서 "무엇이 걸리는지"를
> 먼저 눈으로 확인할 수 있다. 확인이 끝난 뒤 (5)에서 강제로 바꾼다.

> ⚠️ **여기서 덮어쓰는 파일은 지금 서비스 중인 그 파일이다** (SR34-1 로 이름을 맞춘
> 결과다 — 예전 이름 `realestate.conf` 는 아무도 안 읽는 파일이라 덮어써도 티가 안 났다).
> 그래서 ① **먼저 백업**하고, ② 가드가 실패하면 **그 자리에서 백업으로 되돌린다.**
> 디스크의 설정이 나빠도 nginx 는 이미 읽어 둔 것으로 계속 돌지만, 다음 reload 는
> 사람이 아니라 **certbot 갱신 훅**일 수 있다 — 나쁜 파일을 남겨 두고 셸을 닫지 않는다.

```bash
SITE=/etc/nginx/sites-available/realestate.utilverse.info
APP_ROOT=$(pwd)                      # ⚠️ 저장소 루트에서 실행하고 있는지 눈으로 확인할 것

sudo mkdir -p /root/realestate-backup
BACKUP=/root/realestate-backup/nginx-site-$(date +%Y%m%d-%H%M%S).conf
sudo cp "$SITE" "$BACKUP" && echo "백업: $BACKUP"   # 되돌릴 자리를 먼저 만든다

sudo cp deploy/nginx-realestate.conf "$SITE"
sudo sed -i "s|<APP_ROOT>|$APP_ROOT|g" "$SITE"

# CSP 만 Report-Only 로 바꾼다. 저장소 파일은 '강제'가 기본값이고,
# 여기서 이름만 바꿔 붙인다 — 되돌릴 때는 (5)에서 원본을 다시 복사하면 된다.
sudo sed -i 's/add_header Content-Security-Policy /add_header Content-Security-Policy-Report-Only /' \
  "$SITE"
grep -c 'Content-Security-Policy-Report-Only' "$SITE"
# → 3 이어야 한다 (server · 정적자산 · /index.html). 3 이 아니면 진행 금지.

# ⛔ 치환·경로 가드 → 문법 검사 → reload 를 **`&&` 로 묶는다.**
#    가드가 실패하면 nginx -t 도 reload 도 실행되지 않는다(SR33-4).
#    ⚠️ 문법 검사를 건너뛰고 reload 하면 **동거 서비스까지 같이 죽는다.**
#
# ⛔ 되돌리기를 **주석으로 두지 않는다** (SR35-1). 위가 fail-closed 인 바로 밑줄이
#    fail-open 이면 앞의 `&&` 가 무의미하다 — 나쁜 파일이 디스크에 그대로 남고,
#    **다음 reload 는 사람이 아니라 certbot 갱신 훅일 수 있다**(installer=nginx 가 3개).
#    그때는 우리 사이트가 아니라 **동거 서비스 인증서 갱신이 실패**한다.
guard_site "$SITE" "$APP_ROOT" && sudo nginx -t && sudo systemctl reload nginx \
  || { echo "⛔ 실패 — 백업으로 되돌린다"; sudo cp "$BACKUP" "$SITE"; sudo nginx -t; false; }
```

**(4) Report-Only 확인 — 지도가 살아 있는가 · 무엇이 걸리는가**

```bash
# 헤더가 Report-Only 로 나오는지 (값은 길다 — 잘라서 본다)
curl -sI https://realestate.utilverse.info/ | grep -i 'content-security-policy'
```

그다음 **데스크톱 브라우저로 실제 사이트를 연다.** DevTools 콘솔에서 확인한다:

| 보이는 것 | 뜻 | 조치 |
|---|---|---|
| 지도가 뜨고 타일·마커가 정상 | 출처가 맞다 | (5) 로 진행 |
| `Refused to ... because it violates ... "script-src"` 등 위반 | 빠뜨린 출처가 있다 | **강제 전환하지 말고** 위반에 찍힌 호스트를 PM 에 보고 |
| `Refused to evaluate a string as JavaScript`(eval) 1건 | **정상이다** | 카카오 SDK 의 `try{eval("document.namespaces")}catch{}` (IE VML 감지). 차단돼도 지도는 동작한다. ⚠️ 이걸 보고 `'unsafe-eval'` 을 넣으면 CSP 의 핵심 방어가 무너진다 |

> (선택) `style-src` 의 `'unsafe-inline'` 이 정말 필요한지 재보고 싶으면, **Report-Only
> 상태에서만** 그 토큰을 빼고 reload 한 뒤 콘솔에 style 위반이 찍히는지 본다.
> 위반이 없다면 빼도 된다. **강제 상태에서는 시험하지 말 것** — 그 순간 지도가 깨진다.
>
> 수집기(report-uri)를 두지 않은 이유: 받을 엔드포인트가 없고, nginx 는 `return 204`
> 로는 **요청 본문을 읽지 않아** 위반 내용을 로그로 남기지 못한다. 본문을 파일로
> 남기는 옵션(`client_body_in_file_only`)은 디스크가 87% 찬 이 서버에서 위험하다.
> 1인 서비스라 **브라우저 콘솔 확인이 더 정확하고 싸다.**

**(5) CSP 강제 전환 — 확인이 끝난 뒤에만**

```bash
SITE=/etc/nginx/sites-available/realestate.utilverse.info
APP_ROOT=$(pwd)

# (3)과 같은 이유로 **살아 있는 파일**을 덮어쓴다 — 먼저 백업한다.
sudo mkdir -p /root/realestate-backup
BACKUP=/root/realestate-backup/nginx-site-$(date +%Y%m%d-%H%M%S).conf
# ⛔ 백업이 실패하면 **거기서 멈춘다** (SR35-1). `&& echo` 만 달면 백업이 실패해도
#    다음 줄이 살아 있는 파일을 덮어쓴다 — 되돌릴 곳이 없어진 채로. 디스크가 92% 다.
sudo cp "$SITE" "$BACKUP" || { echo "⛔ 백업 실패 — 중단한다"; exit 1; }
echo "백업: $BACKUP"

# 저장소 원본을 다시 복사한다(원본이 '강제' 상태다 — sed 를 되돌리지 않는다)
sudo cp deploy/nginx-realestate.conf "$SITE"
sudo sed -i "s|<APP_ROOT>|$APP_ROOT|g" "$SITE"
grep -c 'Content-Security-Policy-Report-Only' "$SITE"
# → 0 이어야 한다(강제). 0 이 아니면 진행 금지.

# ⛔ (2.5) 의 가드를 여기서도 통과해야 한다 — 원본을 다시 깔았으므로 `<APP_ROOT>` 가
#    다시 들어왔고, 치환이 이번에도 제대로 됐는지는 **다시 확인해야 하는 사실**이다.
guard_site "$SITE" "$APP_ROOT" && sudo nginx -t && sudo systemctl reload nginx \
  || { echo "⛔ 실패 — 백업으로 되돌린다"; sudo cp "$BACKUP" "$SITE"; sudo nginx -t; false; }
```
전환 직후 **지도를 다시 한 번 연다.** 여기서 깨지면 (3)으로 되돌린다(Report-Only 재적용).

**(6) 자동 갱신 확인**
```bash
sudo certbot renew --dry-run
```
> 갱신도 `--webroot` 로 돌아간다(발급 때 쓴 방식이 기록된다).
> 부트스트랩 블록은 (3)에서 대체돼 사라졌지만, 본 설정의 80 블록에도
> `/.well-known/acme-challenge/` 가 남아 있어 갱신이 계속 동작한다.

**막혔을 때** — `nginx -t` 가 실패하면 **손으로 고치지 말고** 아래로 되돌린 뒤 보고한다.
그 상태에서 임의 수정이 동거 서비스를 위태롭게 하는 유일한 경로다.
```bash
sudo rm /etc/nginx/sites-enabled/realestate.utilverse.info
sudo nginx -t && sudo systemctl reload nginx
```

### 5-5b. 가입 승인제 — 첫 관리자 지정 (**009 적용 직후 반드시**)

009 를 적용하면 **기존 계정이 전부 `pending` 으로 바뀌어 로그인이 막힌다.** 의도된 설계지만,
**관리자가 0명인 상태**라 웹에서는 아무도 승인할 수 없다. 아래 CLI 로 부트스트랩해야 한다.

> ### ⛔ CLI 는 **호스트에서** 돈다 — API 컨테이너 안에 없다
> 컨테이너에는 `scripts/` 가 없고 `DATABASE_URL` 도 설정돼 있지 않다.
> `docker exec realestate-api python scripts/manage_users.py` 는 **실패한다.**
> 반드시 호스트의 venv 로, `DATABASE_URL` 을 주고 실행한다.

```bash
cd /opt/realestate/backend
. .venv/bin/activate

# 컨테이너 IP 와 비밀번호는 파일에서 읽는다(값을 화면에 찍지 않는다)
PW=$(grep '^POSTGRES_PASSWORD=' ../.env | cut -d= -f2-)
DBIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' realestate-db)
export DATABASE_URL="postgresql+psycopg://realestate:${PW}@${DBIP}:5432/realestate"

python scripts/manage_users.py --list                    # 대기자를 눈으로 확인
python scripts/manage_users.py --approve <이메일>
python scripts/manage_users.py --grant-admin <이메일>     # 승인된 계정에만 부여된다
python scripts/manage_users.py --list                    # approved·admin 으로 바뀌었는지 확인
```

**웹에는 관리자 부여 경로가 없다**(의도적 — SSH 접근자만 가능). 이후 다른 사람의 가입 승인은
관리자로 로그인해 화면에서 처리한다.

#### 잠김 복구 (관리자가 0명이 된 경우)
마지막 관리자 강등·거부는 API·CLI 양쪽에서 `LAST_ADMIN` 으로 막히지만, 그래도 0명이 되었다면
**위 CLI 가 유일한 복구 수단**이다. SSH 키를 잃으면 복구할 방법이 없으므로 키를 별도 보관한다.

### 5-5c. 임시 가입 차단 해제

> ### ⛔ 열기 전에 **승인제가 실제로 살아 있는지** 먼저 확인한다
> 낡은 코드가 떠 있으면 `status` 를 읽지 않아 **승인 없이 가입이 그대로 열린다** — 이번 배포에서
> 유일하게 나쁜 분기다(CR-025 DEPLOY-2). 차단을 풀기 **전에** 내부 포트로 직접 찔러 확인한다.
>
> ```bash
> # 임시 차단은 nginx 에만 걸려 있으므로 8013 으로 직접 부르면 앱의 실제 동작이 보인다
> curl -sS -X POST http://127.0.0.1:8013/api/v1/auth/register \
>   -H 'Content-Type: application/json' \
>   -d '{"email":"deploycheck@example.com","password":"deploycheck-2026!"}'
> # → 201 이고 본문에 "status":"pending" 이어야 한다. 200/토큰이 나오면 승인제가 안 걸린 것 —
> #   차단을 풀지 말고 5-1b(소스 갱신)·5-3b(마이그레이션)부터 다시 확인한다.
>
> # 확인용 계정은 바로 지운다(관리자 CLI 로 거부하거나 DB 에서 삭제)
> ```

승인제가 살아 있음을 확인했으면 임시 차단(`# === TEMP-REG-BLOCK ===`)을 제거한다.

```bash
SITE=/etc/nginx/sites-available/realestate.utilverse.info
APP_ROOT=/opt/realestate
BACKUP=/root/realestate-backup/nginx-site-$(date +%Y%m%d-%H%M%S).conf
cp "$SITE" "$BACKUP" || { echo "⛔ 백업 실패 — 중단한다"; exit 1; }

# ⛔ `> "$SITE"` 로 직접 쓰지 않는다 (SR35-2).
#    리다이렉트는 **명령이 실행되기 전에 파일을 먼저 비운다.** 원본 경로가 틀리면
#    sed 는 아무것도 못 읽고, 살아 있는 설정만 0바이트로 남는다.
#    빈 파일은 `nginx -t` 를 통과하고 reload 도 성공한다 — **서비스만 사라진다.**
#    그래서 새 파일에 쓰고, 내용이 있을 때만 갈아 끼운다.
sed "s#<APP_ROOT>#$APP_ROOT#g" "$APP_ROOT/deploy/nginx-realestate.conf" > "$SITE.new" \
  && [ -s "$SITE.new" ] \
  && mv "$SITE.new" "$SITE" \
  || { echo "⛔ 새 설정 생성 실패 — 원본을 건드리지 않았다"; rm -f "$SITE.new"; exit 1; }

# ⛔ (2.5) 의 가드. 여기는 `$(pwd)` 가 아니라 절대경로를 쓰지만, 그렇다고 검사를
#    건너뛰지 않는다 — 치환 실패(sed 패턴 오타)와 산출물 부재는 경로 방식과 무관하다.
guard_site "$SITE" "$APP_ROOT" && nginx -t && systemctl reload nginx \
  || { echo "⛔ 실패 — 백업으로 되돌린다"; cp "$BACKUP" "$SITE"; nginx -t; false; }
# ⚠️ 가드·검사 실패 시 reload 하지 마라(동거 서비스가 같이 죽는다)

# 확인: 가입이 403 이 아니라 정상 동작하고, 보안 헤더가 5종 다 붙는지
# ⚠️ `curl -sI`(HEAD)로 재지 마라 — register 는 POST 전용이라 405 가 나고 그 경로엔 헤더가
#    안 붙어서 **0/5 로 보인다**(실제로는 정상인데 장애로 오인한다. 배포 중 실제로 겪었다).
#    반드시 **실사용 경로인 POST** 로 잰다.
curl -sS -D - -o /dev/null -X POST https://realestate.utilverse.info/api/v1/auth/register \
  -H 'Content-Type: application/json' -d '{"email":"x@gmail.com","password":"short"}' \
  | grep -ciE "content-security-policy|strict-transport|x-frame|x-content|referrer"   # 5 이상 기대
```

> 임시 블록의 `location` 안에 `add_header` 를 쓰면 **상위 헤더 상속이 끊겨** 그 경로만 보안 헤더가
> 0개가 된다(SR20-2 에서 실제로 발생). 블록 제거가 곧 그 수정이다.

### 5-6. 최종 확인

**(1) 앱 응답**
```bash
curl -fsS https://realestate.utilverse.info/api/v1/health   # {"status":"ok","role":"api"}
```

**(2) 보안헤더 — 5종이 전부 나와야 한다 (DEP-1 · SR15-4 회귀 검사)**

`add_header` 는 상속되지 않으므로 **경로마다** 확인한다. 아래는 하나라도 빠지면
`[실패]` 를 찍는다 — grep 결과를 눈으로 보고 넘기지 말 것(그렇게 해서 놓쳤던 항목이다).

```bash
check_headers() {
  local url="$1" out
  out=$(curl -sI "$url")
  echo "  --- $url"
  for h in strict-transport-security x-frame-options \
           x-content-type-options referrer-policy \
           content-security-policy; do
    if grep -qi "^$h:" <<<"$out"; then echo "    [OK]   $h"
    else                               echo "    [실패] $h 없음"; fi
  done
}

BASE=https://realestate.utilverse.info

# ⛔ **먼저 상태코드부터**(SR33-4). `curl -sI` 는 헤더만 보고 200/404 를 구분하지 않아,
#    메인이 404 여도 헤더는 다 붙어 있어서 위 검사가 전부 [OK] 로 찍힌다.
#    `<APP_ROOT>` 오치환으로 실제로 겪은 형태다 — nginx -t 도 통과했었다.
MAIN_CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/")
[ "$MAIN_CODE" = "200" ] || { echo "⛔ 메인이 $MAIN_CODE 다 — root 경로/산출물을 확인하라"; }

check_headers "$BASE/"                 # → try_files 로 index.html 을 탄다(가장 중요)
check_headers "$BASE/index.html"
check_headers "$BASE/api/v1/health"
# 정적 자산 하나 (파일명은 빌드마다 다르다)
# ⚠️ 빈 값이면 **조용히 건너뛰지 않는다** — 메인이 404 면 여기가 항상 빈 값이 되고,
#    그러면 "검사 3개가 통과했다"로 보인다(실패가 실패로 안 보이는 자리).
ASSET=$(curl -s "$BASE/" | grep -oE '/assets/[^"]+\.js' | head -1)
if [ -n "$ASSET" ]; then check_headers "$BASE$ASSET"
else echo "  [실패] 메인 HTML 에서 /assets/*.js 를 못 찾았다 — 메인이 404 이거나 빌드 산출물이 다르다"; fi
```
`[실패]` 가 하나라도 있으면 **DEP-1 회귀**다. `nginx-realestate.conf` 에서 해당
location 에 보안헤더 5종이 다시 적혀 있는지 확인한다.

> ⚠️ `content-security-policy` 검사는 **강제 전환(§5-5(5)) 후에** 통과한다.
> Report-Only 단계에서는 헤더 이름이 `content-security-policy-report-only` 라
> 여기서 `[실패]` 로 찍히는 게 **정상**이다 — 그 상태로 §7 인수인계에 들어가지 말 것.
> 값까지 보고 싶으면:
> ```bash
> curl -sI https://realestate.utilverse.info/index.html | \
>   grep -i '^content-security-policy:' | tr ';' '\n'
> ```
> `script-src` 에 `'unsafe-eval'` 이나 `*` 가 보이면 **누가 손으로 넣은 것**이다 —
> 저장소 원본에는 없다(`backend/tests/test_deploy_config.py` 가 막는다).

**(3) 캐시 정책**
```bash
curl -sI https://realestate.utilverse.info/index.html | grep -i cache-control
# → no-store  (이게 없으면 배포해도 옛 화면이 남는다)
```

**(4) 리소스**
```bash
docker stats --no-stream
free -m
```
`docker stats` 의 MEM% 가 90% 를 넘으면 상한을 올리기 전에 **PM 에 보고**한다
(최악 여유가 16MB 뿐이라 임의로 올리면 동거 서비스가 위험하다).

**(5) ⛔ 접근 로그에 쿼리 값이 남지 않는가 (SR32-1 · 이 배포의 차단 사유였다)**

세 싱크를 **각각** 본다. 하나만 막혀 있으면 나머지가 계속 쓴다.
확인 전에 **지도를 한 번 호출해 로그 줄을 만든다** — 로그가 비어 있으면 grep 0건이
"막혔다"가 아니라 "아무 일도 없었다"는 뜻이다.

**먼저 한 줄 — 새 로그 포맷이 *활성 파일*에 들어갔는가 (SR34-1)**
```bash
# nginx 가 읽는 그 파일을 링크에서 되짚어 센다. 다른 파일에 잘 써 두고 여기서 0 이면
# 그게 정확히 SR34-1 의 증상이다(가드·nginx -t·reload 는 전부 성공한다).
sudo grep -c 're_noquery' \
  "$(readlink -f /etc/nginx/sites-enabled/realestate.utilverse.info)"   # → 4 기대
```

```bash
TOKEN=<로그인해서 받은 access_token>
BASE=https://realestate.utilverse.info

# 카나리를 일부러 쿼리에 실어 쏜다(둘 다 거절/무시되지만 로그 줄은 남는다)
curl -sS -o /dev/null -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/v1/map/complexes?bbox=126.9,37.4,127.1,37.6&zoom=14&budget=mine&canary=1314310000"
curl -sS -o /dev/null -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/v1/me/listings?complex_id=1234"

sleep 1
echo "--- nginx ---"
sudo grep -c "1314310000\|complex_id=1234\|max_price_krw=" \
     /var/log/nginx/realestate.access.log            # → 0 이어야 한다
sudo tail -2 /var/log/nginx/realestate.access.log    # 경로만 있고 '?' 가 없어야 한다
echo "--- uvicorn(app 컨테이너) ---"
docker logs --since 2m realestate-api | grep -c "1314310000\|complex_id=1234"   # → 0
docker logs --since 2m realestate-api | grep "map/complexes" | tail -2
```

기대 형태 — **경로만 남고 값은 없다**:
```
… "GET /api/v1/map/complexes HTTP/1.1" 200 …          ← nginx (re_noquery)
INFO: 127.0.0.1:… - "GET /api/v1/map/complexes HTTP/1.1" 200 OK   ← uvicorn (필터)
```

> ⚠️ **앱 미들웨어 줄(`GET … [q: …] 200`)은 나오지 않는다** (SR33-3, 2026-07-29 실측).
> `app` 로거의 INFO 는 **아무 데도 안 나간다** — uvicorn 의 `dictConfig` 는 root 로거를
> 설정하지 않아 핸들러가 0개이고, `logging.lastResort` 는 임계가 WARNING 이라 INFO 를
> 버린다. 그래서 실제로 도는 방어는 **uvicorn 필터와 nginx 포맷 둘**이고,
> `main.log_target` 은 그 둘의 규칙을 코드로 못박아 두는 자리 + 500 로그 경로다.
> **없다고 장애로 오인하지 말 것.** 대신 500 로그는 반드시 한 번 본다:
> ```bash
> docker logs --since 10m realestate-api | grep '처리되지 않은 오류' || echo "(500 없음 — 정상)"
> # 나온다면 그 줄에 `?` 뒤 값이 없어야 한다(SR33-1 · 경로 + `[q: 이름들]` 만)
> ```

한 줄이라도 `?` 뒤가 보이면 **배포를 되돌리고 원인을 찾는다.** 흔한 원인 셋:
① `nginx-realestate.conf` 의 `access_log` 에서 `re_noquery` 가 빠졌다(= 기본 combined),
② 서버에 **옛 conf 가 남아** 있다(`nginx -t` 는 통과한다 — 문법이 아니라 내용 문제),
③ 이미지가 옛 코드다(`docker compose ... build` 를 건너뛴 배포).

**(6) 옛 로그 정리 — 이번 배포 전의 줄은 그대로 남아 있다**
```bash
sudo zgrep -c "max_price_krw=" /var/log/nginx/realestate.access.log.*.gz 2>/dev/null

# ⚠️ 글롭은 `realestate.*` — access 만 잡으면 **error 로그가 빠진다**(SR33-2).
#    실측(2026-07-29): `realestate.error.log.2.gz` 가 0644(월드 리더블)로 남아 있었고,
#    `/var/log/nginx/` 자체가 0755 라 같은 호스트의 다른 계정이 들어올 수 있다.
sudo ls -l /var/log/nginx/realestate.*               # 0644 가 하나라도 있으면 아래를 돌린다
sudo chmod 640 /var/log/nginx/realestate.*
grep -n "create 0640" /etc/logrotate.d/nginx || echo "⚠️ logrotate create 권한을 확인할 것"

# nginx `error_log` 는 `log_format` 대상이 아니라 `request: "<원본 요청줄>"` 로
# **쿼리를 포함해** 쓴다(4xx/5xx·limit_req 초과 시). 즉 re_noquery 의 **밖**이다.
# 지금 URL 에 금액은 없지만, 실제로 남는지는 배포 후 한 번 눈으로 본다.
sudo grep -c 'request: "[^"]*?' /var/log/nginx/realestate.error.log || true   # → 0 기대
```
> logrotate 의 `create 0640 www-data adm` 은 **새로 만드는 파일**에만 걸린다.
> 압축 회전본(`*.gz`)이 0644 로 남는 사례를 실측했다 — 위 `chmod` 를 같이 돌린다.
>
> **`error_log` 를 끄지 않는 이유**: 그 파일이 장애 때 유일한 단서다. 대신
> ① 권한을 0640 으로 잠그고 ② 쿼리가 실린 줄이 실제로 생기는지 주기적으로 본다.
> 금액은 이미 URL 을 떠났으므로(SR32-1) 남을 값은 `bbox`·`complex_id` 급이다.
> 이 판단이 바뀌어야 하는 신호는 **위 grep 이 0 이 아닌 날**이다.

---

## 6. 롤백

문제가 생기면 **역순으로** 되돌린다. 각 단계는 독립적이라 필요한 것만 해도 된다.

```bash
# 1) 웹 노출 제거 (가장 먼저 — 사용자 영향 차단)
sudo rm /etc/nginx/sites-enabled/realestate.utilverse.info
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
| CSP | **강제(enforce)** — §5-5(5)까지 마쳤을 때. Report-Only 로 남겨 두면 방어가 0 이다. `check_headers()` 로 확인 |
| 세율 | `config/tax_rules.yaml` 마운트. 바뀌면 파일 교체 후 `docker compose restart api` |
| 백업 | **미설정** — `pg_dump` 정기 백업이 없다. 2차 과제 |

---

## 8. 자주 나오는 문제

| 증상 | 원인 | 조치 |
|---|---|---|
| api 가 기동 직후 죽음 | `.env` 검증 실패(기동 점검이 막은 것 — 의도된 동작) | `logs api` 에서 `기동 점검 실패:` 줄 확인. JWT_SECRET 32자↑, FIELD_ENCRYPTION_KEY 정확히 32, ARGON2_* 는 하한 이상 |
| 적정가 밴드가 몇 달 전 시점으로 나옴 | 시장지수 배치를 안 돌렸거나, 기준월이 아직 안 열림(M말+30일) | §5-3c 재실행. 기준월 규칙은 §5-3c ⚠️ 참조 |
| `/affordability` 가 503 `TAX_RULES_UNAVAILABLE` | `config/` 마운트 누락 또는 `status != verified` | compose 의 `./config:/srv/config:ro` 확인 |
| 로그인이 503 `BUSY` | Argon2 동시 한도 | 정상 동작(SR8-1/8-2). 잦으면 `ARGON2_CONCURRENCY` 조정 — **단 메모리 재계산 먼저** |
| nginx reload 실패 | `limit_req_zone` 이름 충돌 | `nginx -t` 메시지 확인. zone 이름 `re_api`/`re_auth` 를 다른 이름으로 |
| 지도에 단지가 없음 | 수집 데이터 없음 | 정상 — 실데이터 적재는 2차 |
| 지도가 아예 안 뜸 / 타일이 빈칸 | CSP 가 출처를 막음 | 브라우저 콘솔의 `Refused to load ...` 에 찍힌 호스트를 확인. **임시로 `*` 를 넣지 말고** §5-5(3)의 Report-Only 로 되돌린 뒤 PM 보고 |
| 콘솔에 `Refused to evaluate a string as JavaScript` 1건 | 카카오 SDK 의 IE 감지용 `eval` | **정상.** try/catch 안이라 지도는 동작한다. `'unsafe-eval'` 을 넣지 말 것 |
| db OOM-kill | 상한 192MB 초과 | `docker inspect realestate-db --format '{{.State.OOMKilled}}'`. PM 보고 후 조정 |
