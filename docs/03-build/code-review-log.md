# code-review-log.md — 코드리뷰 원장

> 3단계 구현의 필수 게이트. 커밋/푸시 전 매 변경마다 기록한다.

---

## CR-001 · 2026-07-24 · 1단계 산출물 최초 커밋

**판정: PASS**

### 리뷰 범위
**실행 코드 0줄.** 이번 변경은 인터뷰 산출물과 프로젝트 골격 문서뿐이므로,
코드 정확성 대신 **문서 일관성·설계 입력으로서의 완결성**을 기준으로 검토함.

| 대상 | 비고 |
|---|---|
| `CLAUDE.md`, `skill.md` | 스캐폴드 생성 후 도메인 내용 보강 |
| `docs/01-interview/*` | 브리프(JSON) + 요구사항 정의서 |
| `docs/02~06/*` | 다음 단계 플레이스홀더 |
| `.gitignore`, `.env.example` | 신규 작성 |

### 점검 항목 및 결과

| # | 항목 | 결과 | 근거 |
|---|---|---|---|
| C1 | 브리프 ↔ 문서 정합성 | ✅ PASS | `project-brief.json`의 스택·범위·제약이 `CLAUDE.md`·`requirements.md`에 불일치 없이 반영됨 |
| C2 | 인터뷰 답변 누락 | ✅ PASS | 4라운드 16문항 답변이 모두 브리프에 매핑됨 |
| C3 | 가정값 표시 | ✅ PASS | 확정되지 않은 5개 항목이 `_assumed`에 명시되고 `CLAUDE.md` 상단에 경고로 노출됨 |
| C4 | 요구사항 추적성 | ✅ PASS | 핵심 문제 ①~④가 기능요구 F1~F6과 담당 에이전트로 1:1 매핑됨 |
| C5 | 범위 명확성 | ✅ PASS | "범위 밖(Out of Scope)" 절이 있어 2단계 설계 폭주를 방지함 |
| C6 | JSON 유효성 | ✅ PASS | `project-brief.json` 파싱 성공 (스캐폴드 스크립트 정상 실행) |

### 지적 사항 (다음 단계 반영)

| ID | 내용 | 처리 |
|---|---|---|
| I-01 | `project_name`이 디렉터리명 기반 임시값 | 사용자 확정 시 갱신 |
| I-02 | 스캐폴드 템플릿이 AWS 3-tier 전제 — 실제 배포는 단일 VPS + Docker Compose | 2단계 `architecture-design`에서 치환(요구사항 §10에 명시) |
| I-03 | 런타임 에이전트 8종은 제안 로스터. MVP 5종 축소안도 병기 | 2단계에서 확정 |
| I-04 | `doc_store=confluence`가 기본값으로 들어감 — 실제로는 GitHub 저장소 문서를 쓸 가능성 | 사용자 확인 후 갱신 |

### 판정 사유
문서 산출물로서 2단계 설계의 입력이 되기에 충분히 일관·완결되었고, 미확정 항목이 가정값으로 명시 관리되고 있어 **PASS**.

> ⚠️ 이 판정은 **문서 커밋 한정**이다. 3단계에서 실제 코드가 들어오면 정확성·설계·테스트·성능 기준의 정식 코드리뷰를 새로 수행하고, 그 전까지 이 PASS를 코드 변경의 근거로 재사용하지 않는다.

---

## CR-002 · 2026-07-24 · 팀 오케스트레이션 스크립트

**판정: PASS (제한적 — PM 자체 검토)**

### 범위
`scripts/tell.py`, `scripts/team_up.py` — 에이전트 간 통신·팀 부팅 도구. **제품 코드 아님**(런타임에 실행되지 않음).

| # | 항목 | 결과 | 근거 |
|---|---|---|---|
| C1 | 셸 인젝션 | ✅ PASS | `subprocess.run([...])` 리스트 인자, `shell=True` 미사용 — 메시지 본문의 `\|`·따옴표가 명령으로 해석되지 않음 |
| C2 | 비밀정보 | ✅ PASS | 하드코딩된 키·경로·IP 없음 |
| C3 | 실패 처리 | ✅ PASS | `herdr` 비정상 종료 시 `SystemExit`로 즉시 중단, 조용한 실패 없음 |
| C4 | 멱등성 | ✅ PASS | `team_up.py`가 기존 pane을 이름으로 확인 후 건너뜀 |
| C5 | 실측 검증 | ✅ PASS | 6개 pane 구성·이름 등록·메시지 왕복 전달을 실제로 확인(워커가 한국어 지시를 정상 수신·수행) |

### 이 커밋에서 실제로 고친 결함
- `agent start` 연속 실행 시 포커스 pane에서만 분할돼 pane이 3줄까지 축소 → `pane split`(대상 명시) 방식으로 교체. 현재 워커 pane 14~16줄 확보.
- `pane rename`(label)과 `agent rename`(name)이 별개임을 확인 — `tell.py`는 `name`으로 조회하므로 **둘 다** 설정해야 함. `team_up.py`에 반영.

> ⚠️ **한계 명시**: 이 판정은 PM이 직접 수행한 것으로, CHARTER §2의 역할 분리 원칙상 정식 판정이 아니다.
> `re-review`가 가동되는 대로 팀 스캐폴딩 전체(스크립트 2종 + 헌장·역할 정의)를 재감사한다.

---

## CR-003 · 2026-07-24 · 2단계 설계 산출물

**판정: PASS (제한적 — PM 자체 검토)**

### 범위
`docs/02-design/**` 16개 파일. 실행 코드 없음 — **설계 정합성·완결성** 기준으로 검토.

| # | 항목 | 결과 | 근거 |
|---|---|---|---|
| C1 | 요구사항 추적성 | ✅ PASS | F1~F6이 API 엔드포인트(`api-spec.md` §8)와 에이전트 8종에 각각 매핑됨 |
| C2 | 문서 간 정합성 | ✅ PASS | MVP 5종 로스터가 `CLAUDE.md`·`agents/README.md`·`api-spec.md`에서 동일함을 grep으로 실측 |
| C3 | 미결정 항목 관리 | ✅ PASS | `erd.md` Q1~Q4, `api-spec.md` A1~A4로 명시. Q1(암호화)은 `security.md`에서 결정 후 원문 갱신 |
| C4 | 스캐폴드 템플릿 이탈 처리 | ✅ PASS | AWS 3-tier → 단일 VPS Docker Compose 치환을 `architecture.md` §0에 근거와 함께 기록(CR-001 I-02 해소) |
| C5 | 데이터 모델 타당성 | ✅ PASS | 단지→동→타입 3계층 분리, 실거래/호가 테이블 분리, 파티셔닝·GiST 인덱스 전략 명시 |
| C6 | 성능 병목 식별 | ✅ PASS | 지도 조회 1초 목표와 대응(줌별 군집), AI 분석 비동기화 근거 기재 |

### 이 단계에서 발견한 중대 사항

**F4(동·층·타입별 가치 차이)가 그냥은 성립하지 않는다.**
국토부 실거래가 공개 데이터에 **`동(棟)` 정보가 없다.** 층·타입별 편차는 실거래로 계산되지만
**동별은 좌표 기반 추정**일 수밖에 없다. 모르고 구현했으면 3단계에서 F4가 통째로 무너졌을 사안.

→ 대응을 스키마·API·에이전트 명세 전반에 반영:
- `building.geom` 좌표를 추정 근거로 확보
- `recommendation_item.building_id` nullable + `confidence`/`basis` 필드
- `GET /complexes/{id}/trades` 응답에 하드코딩 고지문
- `valuation-trader` 동별 판단 `confidence ≤ 0.6`, **금액 환산 금지**

### 지적 사항 (3단계 반영)

| ID | 내용 | 처리 |
|---|---|---|
| I-05 | 큐 구현(Celery/RQ/BackgroundTasks) 미확정 | 3단계 구현계획에서 확정 |
| I-06 | 동 좌표 확보 경로(건축물대장 vs 지도API) 미확정 | 수집 설계 시 조사 필요 (`erd.md` Q3) |
| I-07 | Claude API 토큰 비용 추정치 부재 | 구현 후 실측해 `architecture.md` §6 갱신 |
| I-08 | 세율·대출한도 실제 값 미기입(의도적 공란) | `re-data`가 공식 출처에서 `config/tax_rules.yaml` 채움 |

> ⚠️ **한계 명시**: PM 자체 검토이며 CHARTER §2 역할 분리 원칙상 정식 판정이 아니다.
> herdr 복구 후 `re-review`가 **G2 근거 감사**를 포함해 재수행한다.

---

## CR-004 · 2026-07-24 · 3단계 구현 1차 (도메인 로직 · API · 수집기)

**판정: PASS (제한적 — PM 자체 검토 · 미검증 영역 명시)**

### 범위
`backend/**`, `config/tax_rules.yaml`, `docker-compose.yml`, `deploy/nginx.conf`

### 테스트 실측 결과
```
142 passed in 5.74s
  test_affordability.py  21   자금 계산 (F2)
  test_api.py            28   API 계약 · IDOR · 로그
  test_ingest.py         24   실거래가 파싱 · rate limit
  test_listings.py       18   중복제거 · 신뢰도
  test_rules_loader.py    8   세율 설정 가드레일
  test_security.py       24   암호화 · JWT · 마스킹
  test_valuation.py      19   적정가 밴드 · 층효과 · 환금성
```

| # | 항목 | 결과 | 근거 |
|---|---|---|---|
| C1 | 레이어 경계 | ✅ PASS | `domain/` 이 DB·FastAPI 를 import 하지 않음 → Docker 없이 테스트 성립 |
| C2 | 라우터가 얇은가 | ✅ PASS | 계산은 전부 `domain/`. 라우터는 검증·호출·직렬화만 |
| C3 | 대출한도를 가격의 함수로 풀었는가 | ✅ PASS | 이분탐색 구현. `test_불변식_최대가격에서_부등식이_성립한다`, `test_단순합산보다_반드시_작다` 로 회귀 방지 |
| C4 | 세율 하드코딩 | ✅ PASS | grep 결과 도메인 코드에 세율 상수 0건. 전부 `config` 경유 |
| C5 | 표본 부족 처리 | ✅ PASS | `n<5` 면 밴드 미산출, 기간 확장 시 `expanded=True` 로 표기 |
| C6 | 해제 거래 제외 | ✅ PASS | `test_해제거래가_밴드를_왜곡하지_않는다` |
| C7 | 금액 단위 변환 | ✅ PASS | 국토부 만원→원 변환 테스트. 누락 시 시세가 1/10000 이 되는 치명적 버그 |
| C8 | 미구현을 숨기지 않는가 | ✅ PASS | `app/worker.py` 가 조용히 도는 대신 **명시적으로 실패**. 추천 API 응답에 미구현 note |

### 구현 중 발견해 고친 설계 결함

1. **`trust_score` 부호가 문서마다 반대였다.**
   `schema.dbml`·`erd.md`는 "의심도", `01-listing-researcher.md` 예시는 "0.82 = 양호"(신뢰도).
   그대로 구현했으면 **추천 정렬이 뒤집혔다.** → **신뢰도(1=신뢰)** 로 통일하고 3개 문서 수정.

2. **`docker-compose.yml`의 `back: internal: true` 가 워커의 아웃바운드를 막았다.**
   worker-agent(Claude API)·worker-ingest(공공API)가 인터넷에 못 나간다. 배포 후에야 발견될 버그.
   → `edge`(외부 통신) / `data`(internal) 로 분리하고 워커를 양쪽에 배치.

3. **`NO_BODY_LOG_PATHS` 상수가 선언만 되고 쓰이지 않았다.**
   보안 요구사항이 문서에만 있고 코드에 없는 상태. → 접근 로그 미들웨어로 실제 구현하고 테스트 추가.

### ⚠️ 검증하지 못한 영역 (정직하게)

| 영역 | 이유 | 이월 |
|---|---|---|
| **PostGIS 마이그레이션 실행** | 로컬에 Docker 없음 | 첫 배포 시 빈 DB 에 적용해 검증 |
| **PostGIS 리포지토리 구현** | 위와 동일 — 현재 인메모리 구현만 존재 | 배포 환경에서 |
| **공공API 실호출** | 서비스키 미발급 | 키 확보 후. 파싱은 픽스처로 검증됨 |
| **에이전트 오케스트레이션(T7)** | 큐 구현 미확정 | 다음 작업 |
| **프론트엔드(T8)** | 미착수 | 다음 작업 |
| **세율 실제값** | 공식 출처 확인 필요 | `re-data` 담당 |

> 이 목록이 길다는 건 3단계가 아직 안 끝났다는 뜻이다. 끝난 척하지 않는다.

### 지적 사항 (다음 작업)

| ID | 내용 |
|---|---|
| I-09 | `ProfileRecord` 에 기존대출 연 상환액 컬럼이 없어 DSR 계산이 항상 0 가정. 스키마·API 확장 필요 |
| I-10 | `recommendation_job` 이 큐에 실제로 적재되지 않음 (worker 미구현) |
| I-11 | `deploy/nginx.conf` 의 `proxy_params_custom` 파일 미작성 |
| I-12 | 로그인 실패 횟수 제한이 nginx rate limit 에만 있고 앱 레벨 계정 잠금 미구현 |

> ⚠️ **한계**: PM 자체 검토. herdr 복구 후 `re-review` 재감사 필요.

---

## CR-005 · 2026-07-24 · 에이전트 오케스트레이션 (T7)

**판정: PASS (제한적 — PM 자체 검토)** · 테스트 **170 passed**

| # | 항목 | 결과 | 근거 |
|---|---|---|---|
| C1 | 파이프라인 순서 | ✅ | 자금 계산 → 후보 축소 → 분석 → 종합. 예산 상한 없이 LLM 을 태우지 않는다 |
| C2 | 하드 제외 | ✅ | 예산 초과는 점수와 무관하게 제외하고 **사유를 반환**한다 |
| C3 | LLM 의존성 격리 | ✅ | `LLMClient` Protocol + `FakeLLM` → 키 없이 전체 파이프라인 테스트 |
| C4 | 실패 격리 | ✅ | LLM 실패·스키마 이탈 시 제품이 죽지 않고 규칙 기반으로 대체 |
| C5 | 점수 집계에 confidence 반영 | ✅ | 신뢰도 낮은 추정이 순위를 흔들지 못한다 |

### 지적 사항
| ID | 내용 |
|---|---|
| I-13 | `valuation_finding` 이 밴드를 두 번 계산한다(중위값 재조회) — 캐시 필요 |
| I-14 | 파이프라인이 후보별 순차 실행 — 설계상 [3]은 병렬이어야 한다(성능) |
| I-15 | 추천 결과가 DB(`recommendation_item`)에 저장되지 않음 — 워커 연결 시 |

---

## CR-006 · 2026-07-25 · 프론트엔드 (T8)

**판정: PASS (제한적 — PM 자체 검토)**

### 검증
```
프론트: npm run build  ✅ 성공 (tsc strict + vite)
        npx vitest run ✅ 15 passed  (금액·면적·기준일 포맷)
백엔드: pytest         ✅ 170 passed
```

| # | 항목 | 결과 | 근거 |
|---|---|---|---|
| C1 | 모바일 퍼스트 | ✅ | 360px 기준 설계, 데스크톱은 미디어쿼리로 확장(시트 → 우측 고정 패널) |
| C2 | 바텀시트 3단 스냅 | ✅ | peek/half/full, 포인터 드래그 + **키보드 조작**(↑↓) 지원 |
| C3 | 추정치 시각 구분 | ✅ | `~` 접두 + 회색 + `추정` 배지 + 기준일 병기 |
| C4 | 예산 초과 처리 | ✅ | 목록에서 **지우지 않고** 흐리게 + 배지 — 왜 후보에 없는지 보이게 |
| C5 | RN 이식 대비 | ✅ | `api/`·`lib/` 는 뷰 무관 순수 TS. 지도·시트만 플랫폼 의존 |
| C6 | 지도 실패 처리 | ✅ | SDK 키 없으면 빈 화면 대신 **원인과 대안**을 안내 |
| C7 | 요청 폭주 방지 | ✅ | 지도 이동 350ms 디바운스 — 없으면 드래그마다 서버를 때린다 |
| C8 | 접근성 | ✅ | 터치 44px, `focus-visible`, 부호 병기(색 의존 제거), `prefers-reduced-motion` |
| C9 | 빌드 산출물 커밋 | ✅ | `dist/`·`node_modules/`·`*.tsbuildinfo` gitignore. `package-lock.json` 은 의도적 추적 |

### 미검증
| 내용 | 이유 |
|---|---|
| 실제 지도 렌더링 | 카카오 JS 앱키 없음 — 발급 후 확인 필요 |
| 실 API 연동 | 백엔드가 인메모리 리포지토리 상태 |
| 실기기 터치 동작 | 브라우저 시뮬레이션만 가능 |

### 지적 사항
| ID | 내용 |
|---|---|
| I-16 | 로그인 화면 미구현 — 현재 API 호출이 전부 401. 다음 작업 |
| I-17 | 마커 렌더링 미구현(지도는 배경만). 클러스터러 라이브러리 연결 필요 |
| I-18 | 토큰이 메모리에만 있어 새로고침 시 로그아웃됨. httpOnly 쿠키 전환 필요(설계상 예정) |

---

## CR-007 · 2026-07-25 · **re-review 독립 재감사** (지시 2026-07-25-05-review)

**판정: CONFIRM PASS** — CR-004·005·006(PM 자체 검토)을 재감사해 **정식 판정으로 승격**.
검증자: `re-review` (CHARTER §2 역할 분리 — 만든 사람이 아닌 자가 판정).

### 재감사 방법
문서를 읽는 데 그치지 않고 **함수를 직접 호출해 반례를 찾았다.** 실측 스크립트로
자금계산 경계·프롬프트 안전장치를 깨보고 결과를 기록. 기준 테스트 **170 passed** 재현 확인.

| # | PM 검토 항목 | 재감사 결과 | 확인 방법(re-review) |
|---|---|---|---|
| C1 | 레이어 경계(`domain/`이 DB·FastAPI 미import) | ✅ CONFIRM | import 그래프 정독 — `domain/*`에 `fastapi`·`sqlalchemy`·`app.repositories` 유입 0건 |
| C2 | 라우터 얇음 | ✅ CONFIRM | `api/routes.py` 전 핸들러가 검증→도메인 호출→직렬화. 계산식 0건 |
| C3 | 대출한도=가격의 함수(이분탐색) | ✅ CONFIRM | `compute_affordability` 단조성 검토. `shortfall(P)` 정의가 `min(LTV(P),DSR,DTI)` 로 P 의존 — 단순합산 아님 |
| C4 | 세율 하드코딩 0 | ✅ CONFIRM | 도메인 코드 grep + 로더가 유일 경로임을 확인 |
| C5 | 표본부족 처리 | ✅ CONFIRM | `fair_price_band` 사다리 소진 시 `available=False` 반환 — 지어내지 않음 |
| C8 | 미구현 은폐 안 함 | ✅ CONFIRM | `worker.py`가 rc=2로 명시 실패, 추천 API에 미구현 note |

### 자금계산 반례 탐색 (지시 요구 — 경계·음수·0·극단)
| 입력 | 결과 | 판정 |
|---|---|---|
| `principal_from_annual_payment(0)` | 0 | ✅ 정상(음의 예산 방지) |
| `principal_from_annual_payment(-1000)` | 0 | ✅ 정상(음수 상환액 0 클램프) |
| `annual_rate=0.0` (0% 금리 분기) | `monthly*n` = 360,000,000 | ✅ 정상(i==0 분기로 division-by-zero 회피) |
| `Borrower(cash=-1)` 등 음수 | `ValueError` | ✅ 정상(`__post_init__` 방어) |

### 비차단 관찰(이미 PM이 I-13/I-14로 인지 — 성능 사안, 정확성 아님)
- `valuation_finding`이 밴드를 두 번 계산(I-13). 결과 정확성엔 영향 없음.
- 파이프라인 [3] 단계가 순차 실행(I-14). 설계는 병렬. 성능 사안.

### 판정
**CR-004~006 CONFIRM PASS.** 구현 코드의 정확성·레이어·테스트는 견고하다. 보안 측면은
SR-006 참조 — **G1 코드리뷰는 통과, 단 SR4-2(자산유출 방어)는 SR-006에서 반려**한다.

---

## CR-008 · 2026-07-25 · PostGIS 마이그레이션 실검증 (배포 서버)

**판정: PASS** · CR-004 의 "PostGIS 마이그레이션 미검증" / SR4-1 **해소**

### 검증 환경
로컬에 Docker 부재로 미뤄졌던 실검증을, 사용자 승인 하에 배포 VPS 에서 수행.
⚠️ 실서비스 서버(autobtc·itsmine 운영 중, 메모리 여유 332MB)이므로 **전체 스택을 띄우지 않고**
PostGIS 컨테이너 1개만 256MB 제한으로 임시 기동 → 검증 → **완전 삭제**(원상복구 확인).

### 마이그레이션 실적용 (DoD 1) — 전부 통과
`001_init.sql` + `002_add_user_preference_unique.sql` 을 `docker-entrypoint-initdb.d` 로 자동 적용.

| 항목 | 결과 |
|---|---|
| `CREATE EXTENSION postgis` | ✅ PostGIS 3.4 (re-arch 가 superuser 권한 우려했던 지점 — postgis 이미지 initdb 로 통과) |
| 테이블 | 34개 (base 21 + trade 파티션 13) |
| trade 파티션 | ✅ 13개 (2016~2027 + default) |
| GiST 공간 인덱스 | ✅ 6개 |
| user_preference UNIQUE(user_id) | ✅ 002 적용 |
| agent_finding CHECK | ✅ evidence·confidence |
| **파티션 라우팅 실동작** | ✅ 2026 거래 INSERT → `trade_2026` 로 정확히 라우팅 |
| **GiST 인덱스 스캔** | ✅ `Index Scan using idx_complex_geom` (seqscan 아님 — 지도 조회 성능 근거) |

### 앱 동작 (DoD 2) — needs_db **28 passed / 1 failed**
PostGIS 실 DB 위에서 register·login·프로필 암복호화·bbox 조회·IDOR·파티션·GiST 전부 통과.

**실패 1건은 프로덕션 무관 — 테스트 코드 버그:**
`test_근거없는_agent_finding은_저장되지_않는다` 의 2번째 케이스에서 SQLAlchemy `text()` 가
JSON 리터럴 `'{"a":1}'` 의 **`:1` 을 바인드 파라미터로 오해석**. agent_finding CHECK 자체는
정상(1번째 케이스 `'[]'` 거부 = IntegrityError 확인). → re-arch 전달(다음 라운드):
`text()` → `exec_driver_sql` 또는 콜론 이스케이프.

### 부수 발견 (다음 라운드 반영)
- `backend/requirements.txt` 에 `pytest` 누락 — 런타임 의존성만 있어 테스트 실행 시 별도 설치 필요.
  dev 의존성 분리(`requirements-dev.txt`) 권장.

### 결론
**마이그레이션은 실제로 돈다.** CR-004 최우선 이월 항목과 SR4-1 이 실측으로 해소됨.
서버는 원상복구(실서비스 무영향) 확인.
