# 구현 계획 — 부동산 AI 자문 시스템

> 3단계 산출물 · 2026-07-24
> 입력: `docs/02-design/{architecture,erd,api-spec,security}.md`, `agents/`, `ux/`
> ⚠️ **모든 커밋 전 `code-review` + `security-review` 통과 필수** (훅이 물리적으로 차단)

---

## 0. 개발 환경 제약 (실측)

| 도구 | 상태 | 영향 |
|---|---|---|
| Python 3.12 | ✅ | 백엔드·테스트 실행 가능 |
| Node 24 / npm 11 | ✅ | 프론트 빌드 가능 |
| **Docker** | ❌ **없음** | **로컬에서 PostGIS를 띄울 수 없다** |

**이 제약이 구현 순서를 결정한다.**
DB가 필요한 코드는 지금 검증할 수 없으므로, **DB 없이 검증 가능한 순수 로직을 먼저** 만든다.
그게 마침 가장 틀리면 안 되는 부분(자금 계산·시세 통계)이기도 하다.

> DB 의존 코드는 **리포지토리 인터페이스 뒤로 숨겨** 가짜 구현으로 테스트한다.
> 실 DB 검증은 서버 배포 시 또는 로컬 Docker 설치 후로 이월한다(미검증임을 명시).

---

## 1. 레이어 구조

```
backend/
  app/
    core/          설정·보안(암호화·해시·JWT)·예외          ← DB 무관
    domain/        ★ 순수 비즈니스 로직 (DB·프레임워크 무관)  ← 여기가 핵심
      affordability/   자금 계산 (LTV/DSR/DTI, 취득비용)
      valuation/       적정가 밴드, 층 보정, 갭, 환금성
      listings/        정규화·중복제거·신뢰도
      rules/           config 로더 (출처·기준일자 검증)
    repositories/  데이터 접근 인터페이스 + PostGIS 구현
    api/           FastAPI 라우터 (얇게 — 로직 없음)
    agents/        런타임 에이전트 오케스트레이션
    ingest/        수집기
    models/        SQLAlchemy ORM
  migrations/      SQL 마이그레이션
  tests/           pytest
config/
  tax_rules.yaml   세율·대출한도 (출처·기준일자 필수)
frontend/
  src/{api,hooks,components,pages,styles}
```

### 핵심 규칙
1. **`domain/`은 import 로 DB·FastAPI를 건드리지 않는다.** 순수 함수 + 데이터클래스만.
   → 그래야 Docker 없이 테스트된다. 그리고 로직 오류가 프레임워크에 가려지지 않는다.
2. **`api/`는 얇게.** 검증 → 도메인 호출 → 직렬화. 라우터에 계산식이 있으면 리뷰 반려.
3. **세율·한도는 코드에 없다.** `config/tax_rules.yaml`에서만 온다.

---

## 2. 작업 분할과 순서

| # | 작업 | 산출물 | 검증 방법 | 게이트 |
|---|---|---|---|---|
| T1 | 저장소 골격·compose·마이그레이션 | `docker-compose.yml`, `migrations/001_init.sql` | 문법 검토 (DB 미검증 명시) | CR·SR |
| T2 | **자금 계산 엔진** | `domain/affordability/` + `config/tax_rules.yaml` | **pytest 실측** | CR·SR |
| T3 | **시세·매물 로직** | `domain/valuation/`, `domain/listings/` | **pytest 실측** | CR |
| T4 | 보안 코어 | `core/security.py` (AES-GCM, Argon2id, JWT) | **pytest 실측** | **SR 중점** |
| T5 | FastAPI 앱·인증·엔드포인트 | `api/` | TestClient + 가짜 리포지토리 | CR·SR |
| T6 | 수집기 | `ingest/molit.py` | 픽스처 파싱 테스트 | CR·**SR(G4)** |
| T7 | 에이전트 오케스트레이션 | `agents/` | 모의 LLM 응답 테스트 | CR·**SR(G2)** |
| T8 | 프론트 골격 | `frontend/` | 빌드 성공 | CR |

**T2를 먼저 하는 이유**: 실구매 가능 금액이 없으면 후보를 못 거른다.
그리고 여기가 **금액이 틀리면 수천만 원이 틀어지는** 자리다. 가장 먼저, 가장 세게 테스트한다.

---

## 3. 작업별 상세

### T1 · 골격 · 마이그레이션
- `docker-compose.yml`: nginx / api / worker-agent / worker-ingest / redis / db
  - **`db`·`redis`에 `ports:` 를 쓰지 않는다** (`security.md` §4.2 — Docker가 ufw를 우회한다)
- `migrations/001_init.sql`: `schema.dbml` 그대로. PostGIS 확장, GiST 인덱스, `trade` 연 단위 파티션
- `.env.example` 갱신

### T2 · 자금 계산 엔진 (F2)
```
max_purchase = 이분탐색으로 P 를 구한다
    조건: P + 취득부대비용(P) ≤ 가용현금 + 대출한도(P)
    대출한도(P) = min(LTV(P), DSR(소득, 기존상환), DTI(...))
```
- **대출한도가 P의 함수**이므로 단순 덧셈이 아니다 — 이걸 놓치면 예산이 과대 산정된다
- `binding_constraint`(LTV/DSR/DTI 중 무엇이 묶었나)를 반환 — 사용자에게 가장 쓸모 있는 정보
- `config/tax_rules.yaml` 로더는 **`source`·`as_of`가 없으면 로딩을 거부**한다
- 실제 세율값은 공란 — `re-data`가 공식 출처에서 채운다. **테스트는 가상 세율로 로직만 검증**

### T3 · 시세·매물 로직 (F4)
- 적정가 밴드: 동일 단지·타입·최근 N개월, **해제 거래 제외**, `n<5`면 밴드 산출 거부 후 기간 확장
- 층 보정: 층대별 중위 비율
- 중복 판정: `complex+area+floor+price(±1%)+기간겹침` → 대표건 1개, 나머지 `duplicate_of`
- `trust_score`: 저가 이탈·장기 미거래·중복 과다

### T4 · 보안 코어
- `AES-256-GCM`, AAD = `user:{id}:{field}`, 저장 형식 `v1:nonce:ct`
- `Argon2id` 비밀번호 해시
- JWT access 30분 / refresh 14일
- **민감 필드 로그 마스킹 필터**

### T5 · API
- 리포지토리 인터페이스(Protocol) → PostGIS 구현 + 테스트용 InMemory 구현
- **모든 사용자 자원 쿼리에 `user_id` 조건 강제** (IDOR — `security.md` §2.2)
- `/me/profile`·`/affordability` 본문 로그 제외

### T6 · 수집기 (G4)
- rate limit(요청 간격·동시 1), 지수 백오프, User-Agent 명시
- `robots.txt` 파싱 후 금지 경로 요청 안 함
- 모든 레코드에 `source`·`ingested_at`
- `ingest_log` 기록, 0건 연속 시 경보

### T7 · 에이전트 (G2)
- 외부 텍스트는 데이터 블록으로만 전달(프롬프트 인젝션 방지)
- 출력 **스키마 검증** 후 저장, 위반 시 폐기·재시도
- **`evidence` 없는 finding 저장 거부**
- **Claude API 프롬프트에 원본 금액 미포함** (계산 결과만)

### T8 · 프론트
- 바텀시트 3단 스냅, 마커 3단 드릴다운
- 추정치 시각 구분(`--estimated` 회색 + `추정` 배지)
- 비즈니스 로직은 훅/스토어로 분리(RN 이식 대비)

---

## 4. 위험과 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| **Docker 부재로 DB 코드 미검증** | 배포 시 마이그레이션 실패 가능 | 리포지토리 추상화 + SQL 문법 정독. **미검증임을 리뷰 원장에 명시** |
| 공공API 키 없음 | 수집 실제 동작 미확인 | 픽스처 기반 파싱 테스트. 실호출은 키 확보 후 |
| Claude API 호출 비용 | 개발 중 낭비 | 모의 응답으로 개발, 실호출은 최소화 |
| 세율 실제값 부재 | 계산 결과가 실제와 다름 | 로직만 검증. **실값 없이 사용자에게 노출 금지** |
| 실거래 '동' 정보 부재 | F4 축소 | 설계 반영 완료(추정+신뢰도 표기) |

---

## 5. 완료 기준 (3단계 DoD)

- [ ] `pytest` 전체 통과 (도메인 로직 커버리지 중심)
- [ ] `security.md` §7 체크리스트 10항목 전수 확인
- [ ] `code-review`·`security-review` 원장에 PASS 기록
- [ ] `docker-compose config` 문법 검증 (실행은 서버에서)
- [ ] 프론트 빌드 성공
- [ ] **미검증 영역이 문서에 명시**되어 있을 것 (DB 실행, 실 API 호출)

---

## 6. 이월 (3단계 범위 밖)
- 실 서버 배포 (사람 승인 G5 필요)
- 실제 공공API 키 발급·실호출
- Claude API 실호출 비용 실측
- React Native 앱 (웹 검증 후)
