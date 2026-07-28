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
#     ※ 운영 DB 에는 **2026-07-28 적용 완료**(추가만 하는 마이그레이션 · 스키마 백업 후 실행).
for f in backend/migrations/009_user_approval.sql backend/migrations/010_job_result_meta.sql \
         backend/migrations/011_poi_natural_key.sql \
         backend/migrations/012_school_district_natural_key.sql \
         backend/migrations/013_school_level_and_zone_member.sql \
         backend/migrations/014_redevelopment_project.sql \
         backend/migrations/015_market_price_index.sql; do
  echo "--- $f ---"
  docker exec -i realestate-db psql -U realestate -d realestate -v ON_ERROR_STOP=1 < "$f"
done

# (4) 적용 확인 — (1)을 다시 돌려 컬럼이 생겼는지 눈으로 본다
```

> ⚠️ `psql` 에 `-v ON_ERROR_STOP=1` 을 반드시 준다. 없으면 **중간에 실패해도 0 으로 끝나** 실패가
> 성공으로 보인다.

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

### 5-4. API 기동
```bash
docker compose -f docker-compose.deploy.yml up -d api    # 5-2 에서 이미 빌드됨
docker compose -f docker-compose.deploy.yml ps
curl -fsS http://127.0.0.1:8013/api/v1/health            # {"status":"ok","role":"api"}
```

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

**(1) 부트스트랩 블록 배치 — HTTP 전용, 인증서 참조 없음**
```bash
sudo mkdir -p /var/www/certbot
sudo cp deploy/nginx-realestate-bootstrap.conf /etc/nginx/sites-available/realestate.conf
sudo ln -sfn ../sites-available/realestate.conf /etc/nginx/sites-enabled/realestate.conf
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

**(3) 본 설정으로 교체 — 단, CSP 는 `Report-Only` 로 먼저 올린다 (SR15-4)**

> ⚠️ **왜 두 단계인가.** CSP 를 잘못 좁히면 **지도가 죽는다.** 그런데 화면만 보면
> "지도가 안 보인다"까지만 알 수 있고 원인은 못 찾는다(타일 이미지가 막힌 건지,
> SDK 스크립트가 막힌 건지, 인라인 스타일이 막힌 건지). `Report-Only` 는
> **막지 않고 위반만 보고**하므로, 지도가 정상 동작하는 상태에서 "무엇이 걸리는지"를
> 먼저 눈으로 확인할 수 있다. 확인이 끝난 뒤 (5)에서 강제로 바꾼다.

```bash
sudo cp deploy/nginx-realestate.conf /etc/nginx/sites-available/realestate.conf
sudo sed -i "s|<APP_ROOT>|$(pwd)|g" /etc/nginx/sites-available/realestate.conf
grep -n '<APP_ROOT>' /etc/nginx/sites-available/realestate.conf && \
  echo "치환 안 된 자리가 남았다 — 진행 금지"

# CSP 만 Report-Only 로 바꾼다. 저장소 파일은 '강제'가 기본값이고,
# 여기서 이름만 바꿔 붙인다 — 되돌릴 때는 (5)에서 원본을 다시 복사하면 된다.
sudo sed -i 's/add_header Content-Security-Policy /add_header Content-Security-Policy-Report-Only /' \
  /etc/nginx/sites-available/realestate.conf
grep -c 'Content-Security-Policy-Report-Only' /etc/nginx/sites-available/realestate.conf
# → 3 이어야 한다 (server · 정적자산 · /index.html). 3 이 아니면 진행 금지.

# ⚠️ 반드시 문법 검사부터. 실패한 채 reload 하면 **동거 서비스까지 같이 죽는다.**
sudo nginx -t

# 통과했을 때만
sudo systemctl reload nginx
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
# 저장소 원본을 다시 복사한다(원본이 '강제' 상태다 — sed 를 되돌리지 않는다)
sudo cp deploy/nginx-realestate.conf /etc/nginx/sites-available/realestate.conf
sudo sed -i "s|<APP_ROOT>|$(pwd)|g" /etc/nginx/sites-available/realestate.conf
grep -c 'Content-Security-Policy-Report-Only' /etc/nginx/sites-available/realestate.conf
# → 0 이어야 한다(강제). 0 이 아니면 진행 금지.

sudo nginx -t && sudo systemctl reload nginx
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
sudo rm /etc/nginx/sites-enabled/realestate.conf
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
cp "$SITE" /root/realestate-backup/nginx-site-$(date +%Y%m%d-%H%M%S).conf

# 저장소 원본을 다시 깔면 임시 블록이 사라진다(원본에는 애초에 없다)
sed "s#<APP_ROOT>#/opt/realestate#g" /opt/realestate/deploy/nginx-realestate.conf > "$SITE"

nginx -t && systemctl reload nginx     # ⚠️ 검사 실패 시 reload 하지 마라(동거 서비스가 같이 죽는다)

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
check_headers "$BASE/"                 # → try_files 로 index.html 을 탄다(가장 중요)
check_headers "$BASE/index.html"
check_headers "$BASE/api/v1/health"
# 정적 자산 하나 (파일명은 빌드마다 다르다)
ASSET=$(curl -s "$BASE/" | grep -oE '/assets/[^"]+\.js' | head -1)
[ -n "$ASSET" ] && check_headers "$BASE$ASSET"
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
