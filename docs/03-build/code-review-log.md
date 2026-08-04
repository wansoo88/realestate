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
| 테이블 | 34개 (앱 base **20** + PostGIS `spatial_ref_sys` 1 + trade 파티션 13) ※CR-009 정정 |
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
JSON 리터럴 `'{"a":1}'` 의 **`:1` 을 바인드 파라미터로 오해석**.
※CR-009 정정: **빈 배열 `'[]'` 거부만 검증됨**(IntegrityError). 비배열 케이스는 SQL이 DB에
도달조차 못 해 CHECK 동작은 **미검증**이다(211-212 주석의 22023 단정은 과잉 — G2). → re-arch 전달:
`text()` → `exec_driver_sql` 또는 콜론 이스케이프.

### 부수 발견 (다음 라운드 반영)
- `backend/requirements.txt` 에 `pytest` 누락 — 런타임 의존성만 있어 테스트 실행 시 별도 설치 필요.
  dev 의존성 분리(`requirements-dev.txt`) 권장.

### 결론
**마이그레이션은 실제로 돈다.** CR-004 최우선 이월 항목과 SR4-1 이 실측으로 해소됨.
서버는 원상복구(실서비스 무영향) 확인.

---

## CR-009 · 2026-07-25 · CR-008 독립 재검증 (re-review)

**판정: CR-008 결론 CONFIRM (PASS)** · 단 원장 문구 **2건 정정 요구**

CR-008 은 PM 이 배포서버에서 직접 수행한 것으로 re-review 의 독립검증이 아니다(CHARTER §2 —
만든 자와 검증하는 자의 분리). 지시 `2026-07-25-12-review` 로 원장 기록이 실측과 일치하는지,
needs_db 실패 1건이 정말 프로덕션 무관인지를 **DB 없이 정적·재현 가능한 방법으로** 재검증했다.

### 1) 원장 수치 vs 마이그레이션 SQL 정적 대조 — 전부 일치

| CR-008 기록 | 재검증 근거 | 결과 |
|---|---|---|
| GiST 인덱스 6 | `001_init.sql` `USING GIST` 6건 (L22·40·55·190·199·209) | ✅ 일치 |
| trade 파티션 13 | `PARTITION OF` 13건 (2016~2027 12 + default) | ✅ 일치 |
| 테이블 34 | `CREATE TABLE` 33건 + PostGIS 확장이 만드는 `spatial_ref_sys` 1 = 34 | ✅ 총계 일치 |
| UNIQUE(user_id) | `002_add_user_preference_unique.sql` | ✅ |
| agent_finding CHECK | `jsonb_array_length(evidence) > 0`, `confidence BETWEEN 0 AND 1` | ✅ |
| needs_db 29건(28+1) | `pytest -m needs_db --collect-only` → **29** (모듈 `pytestmark`, 함수 29) | ✅ 일치 |

> **정정 ①** — "테이블 34개(**base 21** + 파티션 13)" 의 내역 라벨이 부정확하다.
> 마이그레이션이 만드는 앱 base 테이블은 **20개**(trade 부모 포함)이고, 21번째는 PostGIS 확장이
> 만드는 **시스템 테이블 `spatial_ref_sys`** 다. 총계 34 는 맞으나 "base 21" 은 앱 테이블 수로
> 오독될 수 있다. → `base 20 + spatial_ref_sys 1 + 파티션 13 = 34` 로 표기 권장.

### 2) needs_db 실패 1건 = 테스트 버그 · 프로덕션 무관 — **CONFIRM (독립 재현 완료)**

이 실패는 SQL 이 DB 에 도달하기 *전* SQLAlchemy 컴파일 단계에서 터지므로 **DB 없이 재현된다.**
`backend/` 에서 직접 실행해 확인했다:

- `text()` 가 `'{"a":1}'` 의 `:1` 을 바인드 파라미터로 파싱 → `_bindparams == ['1', 'iid']`
- `literal_binds` 렌더 결과 **`'{"a"NULL}'::jsonb`** — 깨진 JSON. 즉 의도한 SQL 이 아예 아니다.
- 실행 시 파라미터 `1` 값이 없어 **`StatementError`** 발생. `DBAPIError` 는 `StatementError` 의
  **하위**클래스이므로(`issubclass(DBAPIError, StatementError) == True`, 역은 False)
  `pytest.raises(DBAPIError)` 가 못 잡는다 → 실패. **CR-008 의 진단은 정확하다.**
- `::jsonb` 캐스트(콜론 2개)와 1번째 케이스 `'[]'` 는 정규식 lookbehind 로 영향 없음 — 확인.

**프로덕션 전파 여부 전수조사**: `app/` + `tests/` 의 `text()` 블록 **55개**를 SQLAlchemy 의
바인드 정규식으로 전수 스캔한 결과, 식별자가 아닌 바인드가 파싱되는 곳은
**`tests/test_postgis_repo.py:215` 단 1곳**. 프로덕션 `text()` 는 전부 안전.
→ **"프로덕션 무관" 확인.** 수정은 `exec_driver_sql` 또는 `\:` 이스케이프 (re-arch 몫).

> **정정 ②** — CR-008 의 "**CHECK 자체는 정상**" 은 **과잉 주장**이다.
> 실측된 것은 1번째 케이스(`'[]'` → IntegrityError)뿐이고, 2번째 케이스(비배열 `'{"a":1}'`)는
> **SQL 이 DB 에 도달조차 못 했으므로 검증되지 않았다.** 그런데
> `test_postgis_repo.py:211-212` 주석은 "배열이 아닌 값은 CHECK 위반이 아니라 함수 오류(22023)로
> 터진다 — API 에서 잡는 예외도 달라진다"고 **단정**한다. 이 단정에는 현재 **측정 근거가 없다**
> (G2 원칙 1 출처·6 재현성).
> 이론상으론 옳다(`jsonb_array_length(비배열)` → 22023 → SQLAlchemy `DataError` ⊂ `DBAPIError`).
> 즉 테스트의 *의도*는 맞고 리터럴만 깨졌다. → 원장을 "정상 확인"이 아니라 **"미검증"** 으로
> 정정하고, 테스트 수정 후 재실행으로 자동 해소할 것.
> 참고: 현재 `agent_finding` 에 INSERT 하는 **프로덕션 코드가 존재하지 않는다**
> (`loader.py:60`·`base.py:65` 는 docstring 언급뿐). "API 가 잡는 예외" 우려는 아직 가설이며,
> 추천 결과 영속화를 배선할 때 실측하면 된다.

### 3) 재현 증적 미보존 (G2 원칙 6 — 비차단 권고)

CR-008 커밋(86614d4)은 `code-review-log.md`·`ledger.md` **문서 2개만** 담았다. 파티션 라우팅·
GiST `Index Scan` 같은 **서버 실측 원문(psql 출력·EXPLAIN)이 저장소에 없고** 검증 컨테이너는
삭제됐다. 결론 자체는 위 정적 근거(DDL)와 교차검증되어 신뢰하나, 재현하려면 서버 작업을 통째로
다시 해야 한다. → 다음 실검증부터 EXPLAIN·psql 원문을 `docs/03-build/evidence/` 에 첨부 권장.

### 4) 부수 발견 확인 + 신규

- `requirements.txt` 에 `pytest` 누락 — **확인**(`requirements-dev.txt` 없음). CR-008 기록 정확.
- **회귀 기준선 갱신**: 전체 `pytest` **286건 · 29 skip(needs_db) · 257 실행**.
  ledger 의 "239 passed" 는 그 이후 re-domain/re-data 작업으로 증가한 값이다.
- ⚠️ **신규 발견 — 8회 중 1회 flaky 실패**: `tests/test_security.py::test_비밀번호_해시_검증`
  → `argon2.exceptions.HashingError: Memory allocation error`.
  단순 flake 가 아니라 **배포 대상 VPS 에서 재현될 수 있는 자원 고갈 문제**다. → **SR-008** 참조.

### 판정
**CR-008 CONFIRM (PASS).** 핵심 결론 — *마이그레이션은 실제로 돌고, needs_db 실패 1건은
프로덕션 무관 테스트 버그* — 는 독립 재현으로 확인했다. CR-004 / SR4-1 해소 유지.
위 **정정 ①②는 사실 기술의 정확성 문제**이므로 원장 문구를 고칠 것(게이트 차단 아님).

---

## CR-010 · 2026-07-25 · 14-domain 최종 재감사 — 6억캡·누진·하위호환 (re-review)

**판정: PASS** · 지시 `2026-07-25-12-review` (B) · 대상 `ORDER 2026-07-25-14-domain`(engine 6억캡·
`PropertyFacts.region_group`) + `15-data`(값) + `10-arch`(로더)

점검 항목 C1~C6 은 **구현을 보기 전에** `docs/03-build/evidence/README.md` 에 사전 등록했다.
기준선(`baseline_head.json`)과 정답표(`expected_after_cap.json`)도 **변경 전에** 떠 두었다.
결과를 본 뒤에 기준을 만들면 무엇이 나오든 합리화하게 된다.

### C1 캡이 계산에 실제로 배선되는가 (최우선 · SR4-2 동일 실패유형) — **PASS**

구조: `engine._limits_at()` 에 `candidates.append(("CAP", cap_krw))` 로 **경합 후보**로 들어가
`min()` 에 참여하고, 그 `limits_at()` 클로저를 `shortfall()` 이 사용해 **이분탐색을 구동**한다.
리포트 문자열 전용이 아니다.

수치: re-review 독립 참조구현 정답표와 **정확히 일치**(차이 0원).

| 시나리오 | 캡 전(HEAD 213684c) | 캡 후 실측 | 정답표 | 차이 | binding |
|---|---:|---:|---:|---:|:--:|
| S3 | 1,411,500,000 | **1,039,010,000** | 1,039,010,000 | **0** | CAP |
| S4 | 2,289,700,000 | **1,326,750,000** | 1,326,750,000 | **0** | CAP |
| S5 | 2,877,940,000 | **1,517,780,000** | 1,517,780,000 | **0** | CAP |

대출액 전 시나리오 6억 이하(599,99x,xxx). **캡은 실제로 실구매 가능액을 낮춘다** —
고소득 차주 기준 최대 **13.6억** 과대 산정이 해소됐다.

### C2 `region_group` 기본값이 캡을 무력화하지 않는가 — **PASS**
`effective_region_group` = 명시값 → 코드파생 → **기본 "수도권"(캡 적용)**. 안전기본 방향이 옳다.
`engine.py:143`(`prop or PropertyFacts()`)·`routes.py:222`(무지정) 양쪽 다 캡이 걸린다.
법정동코드 파생 실측: `11680`·`41135`·`28185` → 수도권 / `26110`·`48170` → 비수도권 / `None` → 수도권.
비수도권 지정 시 `cap=None`·`binding=LTV`·값이 캡 전으로 복귀 — **오적용 없음**.

### C4 하위호환 — **PASS**
- S1(2.49억) **불변**. S2 는 −2,370,000(−0.28%) 변동인데, 기여분 분해 결과
  **전액 L1 누진세 정정분**이고 캡·스트레스 기여는 0 이다(S2 는 대출이 6억 미만이라 캡 미적용).
  즉 회귀가 아니라 **의도된 정확도 개선**이다.
- 전체 회귀 **320 passed · 0 failed · 34 skipped**(CR-009 기준선 286/29 대비 +34건).
  스킵 34 건은 전부 `test_postgis_repo.py` 의 DB 부재 스킵(29→34 는 re-arch 003 추가분) — 숨은 스킵 없음.
- 기존 `PropertyFacts(area_m2=84.0)` 호출 20여 곳 무손상(신규 필드가 기본값 보유).

### C5 누진 계산 정확성 — **PASS**
- **경계 연속**: 6억 직전/직후 모두 1.1000%, 9억 직전/직후 모두 3.3000% — 점프 없음.
- **법정 산식 대비 오차 0.0000%p** (지방세법 §11①8 `세율%=가액(억)×2/3−3`, 지교=본세×1/10).
  구 근사방식은 ±0.2%p 였다. L1 완전 해소.
- 5억~10억 구간 5백만원 간격 전수 스캔 — 세율 **역행 0건**(단조 비감소 유지, 이분탐색 전제 보존).

### C6 스트레스 DSR 기여분 분리 — **PASS (내 정답표의 구멍을 먼저 메움)**
정답표는 캡만 반영했으므로 그대로 대조하면 스트레스가 검증되지 않는다. 실제로 S1~S5 에서
**스트레스 기여가 0** 이었다 — DSR 이 한 번도 binding 이 아니었기 때문이다(LTV/CAP 이 먼저 뭄).
그래서 **DSR 이 binding 인 시나리오를 따로 만들어** 검증했다:

| 시나리오 | 스트레스 없음 | 적용 | 차이 | binding |
|---|---:|---:|---:|:--:|
| 현금多·소득少 | 579,270,000 | 546,420,000 | −32,850,000 | DSR |
| 현금多·소득中 | 960,900,000 | 897,680,000 | −63,220,000 | DSR |
| 기존대출 有 | 674,180,000 | 642,950,000 | −31,230,000 | DSR |

DSR 한도 자체도 209,461,240 → 176,121,763 원으로 감소(1.5%p 가산). **no-op 아님.**
스트레스 금리가 실상환액이 아니라 **한도 산정용 가정**으로만 쓰이는 것도 확인
(`assumptions` 에 "실제 상환금리 아님" 명시).

### G2 근거 감사 — PASS
`evidence` 에 취득세·LTV·DSR·**절대한도**·**스트레스 DSR** 5건이 전부 `source`·`source_url`·
`as_of` 와 함께 노출된다(금융위 6.27 대책·스트레스DSR 3단계·지방세법). `stale_rules()` 0건.
`binding_constraint: "CAP"`·`absolute_cap_krw` 가 API 로 드러나 사용자가 **무엇이 제약인지** 안다.
면책 고지 유지.

### 신규 발견 `CR10-1` — `target_region_code` 가 클라이언트 입력인데 무시된다 (비차단)
`AffordabilityIn.target_region_code`(`app/api/schemas.py:52`)는 **공개 API 가 받는 클라이언트 값**인데,
`routes.py:222` 의 `PropertyFacts(...)` 는 이 값을 **넘기지 않는다**(전수 grep: 정의 외 사용처 0).
- **현재는 안전하다** — 무시되므로 기본 수도권이 적용돼 캡이 항상 걸린다. 활성 취약점 아님.
- 그러나 **두 가지가 어긋나 있다**:
  1. **API 계약이 오도한다.** 필드를 광고하고 아무 일도 하지 않는다(프론트는 아직 미사용 — 확인함).
  2. **`models.py:55-57` docstring 이 사실과 다르다.** "사용자(클라이언트)가 보내는 값이 아니다 …
     서버가 단지 region(PostGIS)에서 판정한다"고 적혀 있으나, 실제 API 표면은 정확히 그 파생 입력을
     클라이언트 손에 쥐어주고 있다. 이는 SR-005 에서 반려했던 **문서-현실 불일치**와 같은 범주다.
- **잠재 위험**: 필드명이 배선을 유도하고 docstring 이 그 배선을 정답처럼 서술한다. 누군가
  `body.target_region_code` 를 한 줄 연결하는 순간, **사용자가 비수도권 코드를 보내 6억캡을 끄고**
  실구매 가능액을 13.6억 부풀릴 수 있다 — 이 작업 전체가 고치려던 바로 그 버그로 되돌아간다.
- **통과 조건(택1)**: ⓐ `AffordabilityIn` 에서 필드 제거(서버가 단지 region 으로 판정할 때까지), 또는
  ⓑ 필드를 유지하되 **서버 판정값으로 덮어쓰고** docstring 을 실제 동작에 맞게 정정. 어느 쪽이든
  "클라이언트가 못 바꾼다"는 서술과 코드가 일치해야 한다.

### 판정
**PASS.** 재감사 3대 질문 — ① 6억캡이 실제로 실구매 가능액을 낮추는가 ② 누진 계산 정확성
③ 하위호환 회귀 — 전부 통과했고, 특히 ①은 **독립 참조구현과 원 단위까지 일치**한다.
경고했던 두 no-op 경로(캡 미배선 / 기본값 무캡)는 **둘 다 발생하지 않았다.**
`CR10-1` 은 현재 무해하나 배선 한 줄이면 G2 구멍이 되므로 **다음 라운드에 반드시 정리**할 것.

---

## CR-011 · 2026-07-25 · CR10-1 수정 재검증 (re-review)

**판정: `CR10-1` CLOSE (PASS)** · 지시 `2026-07-25-20-review` · 커밋 `5aeac7d`

내가 제시한 통과조건 중 **ⓐ(필드 제거)** 를 택했다. 문서-현실 불일치가 해소됐다.

### 문서-현실 일치 — PASS
- `AffordabilityIn.target_region_code` **제거됨**. 자리에 이유를 남겼다 —
  "권역은 클라이언트 입력이 아니다 … 사용자가 비수도권 코드를 보내 6억 캡을 끄고 예산을
  부풀릴 수 있어(약 13.6억) G2 위반" + 근거 문서 링크.
- `PropertyFacts.target_region_code` 는 **유지** — 옳다. 도메인 모델은 단지별 분석에서
  **서버가** 법정동코드를 채워야 하므로 필드 자체는 필요하다. 문제였던 건 *클라이언트가
  보낼 수 있다는 점*이지 필드의 존재가 아니었다.
- `models.py` docstring 정정 확인: "**API 요청 스키마에 필드가 없다(CR10-1)**" — 이제 **사실과 일치**한다.
  기존 서술("서버가 판정한다")이 실제 API 표면과 어긋나던 문제가 사라졌다.
- 앱 코드 전수 grep: 잔존 참조는 도메인 모델 2곳뿐, 스키마·라우터·프론트 **0건**.

### 우회 불가 e2e 실증 — PASS
캡이 무는 고소득 차주(현금 8억·소득 3억, CR-010 정답표 S4)로 실제 API 를 5가지로 두드렸다:

| 시도 | status | 최대구매가 | binding | cap |
|---|:--:|---:|:--:|---:|
| 정상(권역 미지정) | 200 | 1,326,750,000 | CAP | 600,000,000 |
| `target_region_code: "26110"`(부산) | 200 | **1,326,750,000** | CAP | 600,000,000 |
| `region_group: "비수도권"` 직접 주입 | 200 | **1,326,750,000** | CAP | 600,000,000 |
| 둘 다 주입(`48170` + 비수도권) | 200 | **1,326,750,000** | CAP | 600,000,000 |
| 대소문자·공백 변형 | 200 | **1,326,750,000** | CAP | 600,000,000 |

**전 시도 동일**하며, 값은 CR-010 정답표의 캡 적용값과 **정확히 일치**한다
(캡 미적용 시 2,289,700,000 → 우회 성공이면 이 값이 나왔어야 한다).
Pydantic 이 미정의 필드를 무시하므로 주입 자체가 성립하지 않는다. **우회 불가 확인.**

### 회귀
전체 **327 passed · 0 failed · 34 skipped** — 3회 연속 동일.

### 판정
**`CR10-1` CLOSE (PASS).** 「클라이언트가 못 바꾼다」는 서술과 코드가 이제 일치하고,
그 사실이 e2e 로 실증된다.

---

## CR-013 · 2026-07-25 · 추천 실행 경로 + 수집 파이프라인 검증 (re-review)

**판정: FAIL — 수집 2건 수정 필요(`INGEST-1`·`INGEST-2`). 추천 4개 항목은 전부 PASS.**
지시 `2026-07-25-27-review` · 대상 `24-domain`·`25-data`(커밋 `debeedd`) · 회귀 **351 passed · 0 failed · 34 skipped**

---

### 추천 실행 경로 (24-domain)

#### (1) IDOR — **PASS**
- 생성 `repo.create_job(job_id, user.id, …)` — JWT 의 `CurrentUser` 에서만 온다.
- 조회 `repo.get_job(job_id, user.id)` → 소유자 불일치면 `None` → **404 로 통일**해
  *남의 작업이 존재한다는 사실조차* 알려주지 않는다(`routes.py:374-380`).
- 저장 `save_job_result(job_id, user_id, …)` 가 **소유권을 다시 확인**한다(`memory.py`) —
  BackgroundTask 가 엉뚱한 job 에 쓰지 못한다. 방어가 두 겹이다.

#### (2) 예외 격리 — **PASS (5개 실패 모드 실측)**
| 상황 | status | items | 예외 유출 |
|---|:--:|:--:|:--:|
| 프로필 없음 | `done` | 0 | 없음 |
| 데이터 없음(수집 전) | `done` | 0 | 없음 |
| LLM 전면 장애 | `done` | 정상 | 없음 |
| repo 예외(DB down) | `error` | 0 | 없음 |
| 세율파일 없음 | `error` | 0 | 없음 |

**`queued` 영구정지 0건.** "데이터가 없다"(`done`+빈결과)와 "실패했다"(`error`)를 구분하는 것도 옳다.
- 비차단 관찰: `_persist` 가 `save_job_result` 자체의 예외를 삼키므로, **저장이 실패하면**
  job 이 `queued` 로 남는다. 다만 같은 DB 에 `error` 도 못 쓰는 상황이라 실질 대안이 적다 — 기록만 남긴다.

#### (3) ★ SR4-2 구조 유지 — **PASS (실행 검증)**
문서 주장이 아니라 **`run_recommendation_job` 을 실제로 돌려 프롬프트를 압수**했다.
특이값(현금 812,345,678 / 소득 234,567,890 / 기존대출 123,456,789)을 암호화 저장하고,
`FakeLLM` 이 받은 system·user 프롬프트 전문(2,898자)에서 원/콤마/억/만 표기를 전부 탐색:

| 대상 | 결과 |
|---|:--:|
| 원본 현금·소득·기존대출 | **0건** |
| **가용현금(현금−예비비)** — 예비비 2,000만이 `assumptions` 에 공개돼 **역산 가능**한 값 | **0건** |

역산 가능한 파생값까지 확인한 이유는 `AffordabilityResult.usable_cash_krw` 가
`AnalysisContext` 에 실려 들어가기 때문이다. **그것도 프롬프트에 닿지 않는다.**
`forbidden_amounts` tripwire 도 실값으로 무장돼 있다(빈 배열 아님 → fail-loud 조건 미발동).

> **부수 확인(강점)**: LLM 정상 vs **전면 장애**에서 findings·`total_score` 가 **완전히 동일**했다
> (91.2 / 동일 4개 finding). 즉 추천 수치가 **LLM 추론이 아니라 계산식**에서 나온다 —
> G2 원칙 3("계산식으로 구현되었는가")이 실제 경로에서 충족됨을 실측으로 확인했다.
> LLM 의존 부분은 headline 뿐이고 실패 시 "분석 요약(자동 생성)" 으로 폴백한다.

#### (4) 결측 처리 — **PASS**
데이터가 모자라면 지어내지 않고 **사유를 특정해 판단을 보류**한다:
"표본 1건으로 최소 5건에 미달", "입지 데이터(학군·교통·인프라) 미수집" — confidence 0.0.
크래시 없음. G2 원칙 4(불확실성 표기)에 부합.

---

### 수집 파이프라인 (25-data)

#### (5) 멱등성 — **PASS**
같은 거래 3회 재수집 → `inserted=1, skipped_dup=2`, **저장 1행**. 증분 재수집이 최근 2개월을
다시 받아도 중복이 쌓이지 않는다. PostGIS 는 같은 자연키로 `WHERE NOT EXISTS` — 인메모리와 규칙 동일.

#### (6) rate limit · ingest_log · robots — **1건 결함**
| 점검 | 결과 |
|---|---|
| rate limit | ✅ 요청 6회에 `limiter.wait()` **6회** — 매 요청 전 호출 확인 |
| 키 없음 | ✅ 즉시 `failed` + ingest_log 기록. **가짜 성공 없음** |
| fetch 실패 | ✅ 실패로 집계 + ingest_log 기록 |
| robots | ✅ fail-closed — 판정 불가면 **거부**(`robots.py:43`) |
| **적재 실패** | ⛔ **`INGEST-1`** |

#### ⛔ `INGEST-1` (medium) — 적재 실패 시 `ingest_log` 가 남지 않는다
`row_sink(trades)`(DB 적재) 호출이 **try 밖**에 있고 `log_sink(run)` 이 **`finally` 가 아니다**
(`runner.py:142·151`). 적재기가 던지면 예외가 `run_molit_trade_ingest` 밖으로 나가고
**ingest_log 는 0건**이 된다 — 실측 확인.
모듈 자신이 `runner.py:10` 에 *"ingest_log — 성공/실패 건수와 상태를 반드시 남긴다.
**'조용한 실패'가 가장 위험하다**"* 라고 적어 둔 원칙과 어긋난다.
DB 연결 끊김·FK 위반(예: `region_code` 마스터 미적재)은 현실적인 실패 모드다.
**통과 조건**: `row_sink` 호출을 같은 `try/except` 안에 넣어 실패로 집계 + `log_sink(run)` 을 `finally` 로.

#### (7) 원천 데이터 커밋 — **PASS**
추적 파일 중 수집 원천은 `tests/fixtures/molit_apt_trade_sample.xml` **1개(3.5KB)** 뿐 —
파서 회귀용 소형 픽스처다. `data/raw/`·`data/cache/` 는 `.gitignore` 등재, 대량 데이터 **0건**.

#### ⛔ `INGEST-2` (high) — 해제거래가 원본을 무효화하지 못한다
**dedup 자연키에 `is_cancelled` 가 포함**돼 있다(`normalize.py:97`, `loader.py:228`).
그래서 같은 거래가 나중에 **'해제'로 재유입되면 중복 행이 하나 더 생기고 원본은 그대로 남는다.**
실측:

```
1회차 정상 신고        → inserted=1              저장 1행 (is_cancelled=False)
2·3회차 재수집         → skipped_dup             저장 1행  ← 멱등 정상
4회차 '해제'로 재유입   → inserted=1  ⛔          저장 2행 (False + True)
```

`stats.py:65` 와 `postgis.py:350,500` 은 **해제건만 제외**하므로, 남아 있는 원본
(is_cancelled=False)이 **여전히 시세 통계에 잡힌다.** 즉 **해제 신고가 아무 효과가 없다.**
- 실측에서 해제된 15억 거래가 통계 대상으로 그대로 남았다.
- 허위신고 후 해제(가격 띄우기)는 국내 실거래가의 **알려진 조작 수법**이고, `is_cancelled` 를
  추적하는 목적 자체가 그것을 걷어내는 것이다. 지금은 추적만 하고 **걷어내지 못한다.**
- CHARTER §0 최대 리스크(*틀린 근거로 수억 원짜리 매수 결정*)에 직결된다.
**통과 조건**: ① dedup 키에서 `is_cancelled` 제거(거래 동일성은 단지·날짜·가격·면적·층으로 판단),
② 해제 신고 유입 시 기존 행을 **UPDATE**(`is_cancelled=true`, `cancelled_on`)하도록 upsert,
③ "정상→해제 재유입 후 통계에서 사라진다" 회귀 테스트 1건.

---

### 실 DB 미검증분 (다음 DB 라운드에 명시)
`needs_db` **34건 전부 skip**(로컬 DB 부재). 이번 검증은 **인메모리 구현·정적 SQL 판독**으로 했다.
다음 DB 라운드에서 실측할 것:
1. `PostgisTradeLoader` 의 `WHERE NOT EXISTS` 멱등성이 **실제 SQL 로도** 성립하는지
   (인메모리와 규칙은 같으나 `IS NOT DISTINCT FROM` 의 NULL 처리는 실행해 봐야 안다).
2. `INGEST-2` 수정 후 **해제 UPDATE 가 파티션 테이블에서 동작**하는지
   (`trade` 는 연도 파티션 — 파티션 키 밖 UPDATE 는 제약이 따른다).
3. `complex`/`unit_type` get-or-create 의 **동시성**(유니크 인덱스 없이 경합 시 중복 생성 여부).
   → re-arch 에 요청된 자연키 유니크 인덱스(004)가 붙은 뒤 재확인.
4. CR-009 에서 이월된 `agent_finding` 비배열 CHECK 실측(needs_db 34/34).

### 판정
**FAIL.** 추천 실행 경로는 IDOR·예외격리·SR4-2·결측처리 **4개 전부 통과**했고, 특히 SR4-2 는
역산 가능한 파생값까지 실행 검증했다. 수집은 멱등성·rate limit·robots·원천데이터 통제가 견고하나
**`INGEST-2`(해제거래 무효)는 시세 정확성에 직접 영향**하므로 반드시 고쳐야 한다.
`INGEST-1` 은 실패 관측 가능성 문제로 함께 처리 권고.

---

## CR-014 · 2026-07-25 · INGEST-1/2 수정 + payload 최종 재검증 (re-review)

**판정: 검증 범위 3건 전부 PASS → `INGEST-1`·`INGEST-2` CLOSE · 27-review 종결.**
**단 "3단계 구현 완성" 판정은 보류(FAIL) — 아래 §4.**
지시 `2026-07-25-30-review` · 대상 커밋 `d5d7a46` · 회귀 **390 passed · 0 failed · 50 skipped(needs_db)**

### 1) `INGEST-2` — CLOSE
**자연키에서 `is_cancelled` 제거 + dedup→upsert 전환이 실제로 시세조작을 막는다.**

`normalize.TradeNaturalKey` = (complex, contract_date, price_krw, area_m2, floor) — `is_cancelled` 없음.
인메모리 로더 실측:

| 단계 | 결과 |
|---|---|
| 정상 신고 → 재수집 2회 | inserted=1 → updated=1,1 · **1행 유지**(멱등) |
| **'해제'로 재유입** | **updated=1 · 여전히 1행**, `is_cancelled=True`, `cancelled_on=2026-06-01` |
| 시세(NOT is_cancelled) | 전체 1행 / **통계 사용 0행** → **해제된 15억이 시세에서 사라졌다** ✅ |
| 해제 취소(정상 재유입) | `is_cancelled=False` 로 **복원** |
| 과다병합 점검 | 가격 다름 → 2행 · 층 다름 → 2행 (**서로 다른 거래는 각각 유지**) |

`004_trade_natural_key.sql` 도 요구대로다:
- `UNIQUE NULLS NOT DISTINCT (complex_id, contract_date, price_krw, area_m2, floor)`
  → **`is_cancelled` 제외 ✅ · `unit_type_id` 제외 ✅**
- 파티션 키(`contract_date`) 포함 — 파티션 테이블 유니크 요건 충족
- `NULLS NOT DISTINCT`(PG15+, 배포 이미지 postgis:16-3.4 → PG16) — `floor`·`area_m2` 가 NULL 인
  행이 유니크를 우회하지 못하게 막는다. **중복이 가장 많이 생기는 자리를 정확히 겨냥**했다.
- 제약 코멘트에 "나중에 이 컬럼을 키에 추가하면 방어가 조용히 깨진다" 경고까지 남겼다.

**pg_constraint 단언 테스트 존재 확인**(`test_postgis_repo.py:747-756`):
`assert "is_cancelled" not in cols` + `assert set(cols) == {complex_id, contract_date, price_krw, area_m2, floor}`
→ 자연키에 컬럼이 추가되면 즉시 깨진다. 행위 테스트(허위 고가 30억 해제 → `live` 에 15억만 남음)도 함께 있다.
⚠️ 단 이 둘은 **`needs_db` 라 로컬에서 실행되지 않았다** — §5 참조.

### 2) `INGEST-1` — CLOSE
`row_sink` 가 `try` 안으로 들어오고 `log_sink(run)` 이 항상 호출된다. 실측:

| 상황 | 예외 유출 | status | ingest_log |
|---|:--:|:--:|:--:|
| **적재(row_sink) 실패** | **없음** | `failed` | **1건 ✅** (`'11680:202605', '수집/적재 실패: DB 연결 끊김 / FK 위반'`) |
| 일부 배치만 적재 실패 | 없음 | `partial` | 1건 (rows_ok=12 / failed=1, 실패 지역·달 특정) |
| 정상 / fetch 실패 / 키 없음 | 없음 | ok / failed / failed | 각 1건 |

실패 내역에 **어느 지역·어느 달이 깨졌는지**가 남아 재수집 대상을 특정할 수 있다.
`log_sink` 자체가 던지면 예외가 전파되는데, **원장을 못 남기는 상황을 호출자에게 알리는 것이 옳다**
(여기서 삼키면 그게 진짜 조용한 실패다) — 의도된 동작으로 본다.

### 3) payload — PASS
- 파이프라인 항목에 `headline`·`why`·`why_not`·`next_actions` **전부 존재**(실측).
- **판단 보류 사유 보존 확인**: `location-analyst` 의 "입지 데이터(학군·교통·인프라) 미수집" 은
  `evidence` 가 비어 `agent_finding` 의 `CHECK (jsonb_array_length(evidence) > 0)` 에 막혀
  저장할 수 없는데, **payload 가 이를 살린다.** 005 의 설계 의도대로 동작한다.
- **`agent_finding` CHECK 는 그대로**(001 원문 유지, 이후 마이그레이션에 ALTER/DROP 없음) —
  CHECK 를 완화해 우회하지 않고 별도 컬럼으로 푼 것이 옳다(G2 유지).
- `_item_to_dict` 복원: payload 있는 행 → 본문 5종 전부 복원, `id`·`rank` 는 DB 값이 정본.
- **NULL payload 옛 행 → 예외 없음**, 정규화 컬럼으로 최소 복원(rank·total_score·timing_signal).
  `ADD COLUMN IF NOT EXISTS` + nullable 이라 마이그레이션도 비파괴적이다.
- payload JSON 직렬화 정상(2,717 bytes).

### 4) ⛔ "3단계 구현 완성" 판정 — **보류(FAIL)**
지시는 "통과면 … 3단계 구현 완성 판정"이었다. **검증 범위 3건은 통과했으나 완성 판정은 못 한다.**
`CLAUDE.md:91` 이 미완으로 적어 둔 5건 중 **2건이 여전히 미완이고, 둘 다 팀 통제 범위 안**이다:

| 항목 | 상태 | 근거 |
|---|---|---|
| PostGIS 리포지토리 | ✅ 코드 완료 | `postgis.py` +350줄, region 마스터·4종 메서드 |
| 세율 실제값 | ✅ 완료 | CR-010 에서 검증 |
| **로그인 화면** | ⛔ **미완** | `App.tsx`(134줄)에 **로그인 폼이 없다.** token·input·form·password 어느 것도 없고 문자열 `"로그인이 필요합니다."`(51행)뿐. **백엔드 인증은 완성인데 사용자가 로그인할 방법이 없다** — 배포해도 앱을 쓸 수 없다 |
| **지도 마커** | ⛔ **미완** | `MapView.tsx`(95줄)는 지도를 만들고 bbox 를 `onBoundsChange` 로 emit 할 뿐 **마커를 하나도 그리지 않는다.** `kakao.maps.Marker`·`MarkerClusterer` 인스턴스화 0건이며, SDK 를 `libraries=clusterer` 로 로드해 놓고 **쓰지 않는다.** F1(지도 기반 추천)의 핵심 화면이 비어 있다 |
| 실데이터 수집 | ⏸ 사람 대기 | `MOLIT_API_KEY` 미발급 — G5/사람 몫이라 팀 책임 아님 |

앞의 2건은 **"동작하는 제품"의 최소 조건**이다. 백엔드·도메인·수집은 견고하지만
사용자가 **로그인할 수 없고 지도에서 아무것도 볼 수 없는** 상태를 3단계 완성이라 부를 수 없다.
→ **`FE-1`(로그인 화면)·`FE-2`(지도 마커)** 로 등록한다. 이 2건이 닫히면 완성 판정이 가능하다.

### 5) 실 DB 미검증분 (다음 DB 라운드)
`needs_db` **50건**(34→50 증가) 전부 skip. 이번 검증은 인메모리 구현·정적 SQL 판독 기반이다.
1. **`trade_natural_key` 제약이 실제로 생성되는지** + pg_constraint 컬럼 단언 실행
   (파티션 테이블 `UNIQUE NULLS NOT DISTINCT` 는 PG16 에서 실행해 봐야 확정된다).
2. **해제 UPDATE 가 연도 파티션에서 동작**하는지(파티션 키 밖 컬럼 UPDATE).
3. `PostgisTradeLoader` 의 UPDATE→INSERT 멱등성 실 SQL 검증(`IS NOT DISTINCT FROM` NULL 처리).
4. `complex`/`unit_type` get-or-create 동시성(유니크 인덱스 없이 경합 시 중복 생성).
5. payload 왕복(jsonb 저장→복원)과 NULL 옛 행 복원 실측.
6. CR-009 이월: `agent_finding` 비배열 evidence CHECK 실측.

> 비차단 관찰: `PostgisTradeLoader._insert_trade` 는 UPDATE→(없으면)INSERT 인데 주석은
> "유니크 제약이 아직 없어 `ON CONFLICT` 대신"이라 적혀 있다. **004 가 제약을 추가했으므로
> 주석이 낡았고**, 동시 실행 시 둘 다 INSERT 하여 유니크 위반이 날 수 있다(일 1회 배치라 실사용
> 위험은 낮다). 004 코멘트가 권하는 `ON CONFLICT DO UPDATE` 로 바꾸면 경합이 사라진다 — 권고.

### 판정
**검증 범위 PASS — `INGEST-1`·`INGEST-2` CLOSE, 27-review 종결.**
해제거래 시세조작 방어는 자연키·마이그레이션·로더·테스트 네 층에서 일관되게 구현됐고 실측으로 확인했다.
**단 3단계 구현 완성은 `FE-1`·`FE-2` 해소 후 재판정한다.**

---

## CR-015 · 2026-07-25 · apt_dong/동 실측 기능 (molit·loader·migration 006·erd §0 정정)

**판정: FAIL — 로더 규칙 불일치 1건(`APTDONG-1`). 파싱·마이그레이션·자연키 방어는 전부 PASS.**
검증자: `code-reviewer` (herdr re-review 대행 — 독립 감사) · 대상: working tree(미커밋)
회귀: 대상 `tests/test_ingest.py`+`tests/test_ingest_loader.py` **46 passed** · 전체 **341 passed · 50 skipped(needs_db)**

> 배경: 운영 MOLIT API(RTMSDataSvcAptTrade)가 `aptDong` 을 77~93% 제공(강남87·종로77·분당93·인천91%,
> 실호출 e2e 검증)한다는 사실을 반영해 `trade.apt_dong` 컬럼을 추가하는 변경. 설계 초안 erd §0 "동 없음"을 정정.

### 통과한 불변식 (반례 탐색 후)

| # | 불변식 | 결과 | 근거 |
|---|---|---|---|
| 1 | ⛔ apt_dong 이 **자연키에 절대 없어야** 함(INGEST-2 방어) | ✅ PASS | 세 곳 모두 5컬럼 유지: `normalize.trade_natural_key`(normalize.py:95-102)=(complex, contract_date, price_krw, area_m2, floor) · `004` UNIQUE 미변경 · loader UPDATE WHERE(loader.py:246-250). **006 은 ADD COLUMN + 부분 인덱스만**이고 자연키 제약을 건드리지 않음 |
| 2 | UPDATE 가 기존값을 NULL 로 덮지 않음 + INSERT 컬럼/값 정합 | ✅ PASS(PostGIS) | UPDATE `apt_dong = COALESCE(:apt_dong, apt_dong)`(loader.py:240). INSERT 컬럼 **12개**=VALUES **12개**, 순서 1:1 정확(…floor, area_m2, **apt_dong**, is_cancelled…) |
| 3 | normalize_apt_dong: 빈값/공백/'-'/'0'→None, 실표기 strip 보존 | ✅ PASS | molit.py:96-107. `not raw`→None, strip 후 `""`·`"-"`·`"0"`→None, 그 외 원본 보존. "없는 걸 지어내지 않는다" 준수 |
| 5 | 파티션(RANGE by contract_date) 부모 ADD COLUMN/CREATE INDEX 전파 | ✅ PASS | `001` trade = `PARTITION BY RANGE (contract_date)` 확인. 부모에 ADD COLUMN·partitioned INDEX(부분·`WHERE apt_dong IS NOT NULL`) 는 PG16 에서 각 파티션에 전파. 006 주석의 전제와 일치 |

파싱 회귀 테스트도 견고하다: `test_동은_운영API에_존재한다`(있음 '410' / 결측 None), `test_동_정규화`(6케이스),
한글`<동>`·영문`aptDong` 양쪽 별칭 파싱, `청담(103)` 이름형 원본 보존까지 못박음.

### ⛔ `APTDONG-1` (blocking · 불변식 4 위반) — 두 로더가 재적재 시 apt_dong 을 다르게 다룬다

**PostGIS 는 COALESCE 로 보존하는데, InMemory 는 row 전체를 교체하며 apt_dong 을 NULL 로 덮는다.**

- PostGIS `_upsert_trade` UPDATE(loader.py:240): `apt_dong = COALESCE(:apt_dong, apt_dong)` → 새 값이 NULL 이면 **기존 동 유지**.
- InMemory `load` update 경로(loader.py:130-132): `self.trades[nk] = row` 로 **딕셔너리 전체 교체** → `row["apt_dong"] = t.apt_dong` 가 그대로 들어가 **결측(None) 재유입 시 기존 동이 소실**된다.

**실측 반례**(인메모리 직접 호출, `backend/`):
```
1) load(동='103')            → trades[nk]['apt_dong'] = '103'
2) load(같은 자연키, 동 결측·해제) → trades[nk]['apt_dong'] = None   ⛔  (PostGIS 였다면 COALESCE 로 '103' 유지)
   InMemory: before='103'  after=None   /   PostGIS COALESCE: '103' 보존
```
즉 **동일 입력에 두 로더가 다른 상태**를 만든다. 이 코드베이스의 중심 원칙(loader.py:12 "둘은 같은 규칙을 써야
한다 — 규칙이 갈리면 '테스트는 되는데 운영엔 [문제]'가 된다")을 정면으로 어긴다. 개발자가 PostGIS 에 **일부러
COALESCE 를 넣었다는 것 자체가 '결측 재유입으로 동이 지워지는 경로가 실재한다'는 전제를 인정한 것**인데
(006 주석: "적재 시 COALESCE 로 기존 값을 덮어쓰지 않게 채운다"), 그 방어가 InMemory(=테스트 오라클)에는 없다.

발생 경로: 정상거래(동 有)가 나중에 **'해제'로 재유입될 때 해제피드에 동이 빠지면**(결측 10~23% 범위) 트리거된다 —
INGEST-2 가 다루는 바로 그 재유입 경로다. (같은 달 단순 재수집은 동 값이 안정적이라 divergence 미발생.)

부수 문제 — **핵심 write-path 테스트 부재**: 이번 변경의 쓰기측 핵심 동작인 "COALESCE 로 apt_dong 보존"을
검증하는 테스트가 **0건**이다. `test_ingest_loader.py` 에 apt_dong 적재/재적재 케이스가 아예 없다. 게다가 InMemory 는
보존과 반대로 동작하므로, 지금 InMemory 기반으로 재적재 테스트를 짜면 **PostGIS 의 의도와 상반된 값을 정답으로
못박게** 된다. 누군가 PostGIS 에서 COALESCE 를 떼어도 어떤 테스트도 못 잡고 운영에서 동이 조용히 지워진다 —
이 코드베이스가 가장 경계하는 실패 형태다.

**통과 조건(전부 충족해야 재판정 PASS)**:
1. `InMemoryTradeLoader.load` 의 update 경로가 COALESCE 와 **동일 규칙**을 따르게 수정 — 재적재 시 `t.apt_dong` 이
   None 이면 기존 `self.trades[nk]["apt_dong"]` 을 보존(예: `row["apt_dong"] = t.apt_dong if t.apt_dong is not None
   else self.trades[nk].get("apt_dong")`). insert 경로는 현행 유지.
2. 재적재 회귀 테스트 1건 추가: "동(有) 거래 → 동 결측(해제 포함)으로 재유입 후에도 apt_dong 이 보존된다" 를
   InMemory 로 검증. PostGIS COALESCE 동일 동작은 `needs_db` 로도 1건 걸어 다음 DB 라운드에 실측 권고.

### 비차단 코멘트 (pass 무관 — 이번 변경 밖)

- `trade` 테이블에 `cancelled_on` 컬럼이 **없다**(001:76-90). loader params 는 `cancelled_on` 을 담지만 INSERT/UPDATE
  에서 미사용이고, InMemory 는 row 에 저장한다 → **기존부터 존재하던** 로더 divergence(이번 diff 무관, 범위 밖). 별도 정리 권고.
- `normalize_apt_dong` 의 `"0"`·`"-"`→None 은 합리적. `"00"` 같은 다중 0 은 미처리이나 실데이터에서 비현실적 — 비차단.
- loader.py:21-22 의 "유니크 제약 없어 UPDATE→INSERT" 주석은 004 이후 낡음(CR-014 §5 비차단 관찰과 동일 사안).

### 판정
**FAIL.** 파싱·정규화·마이그레이션 구조·자연키 방어(불변식 1·2·3·5)는 모두 견고하고 파싱 회귀도 잘 못박혀 있다.
그러나 **불변식 4(두 로더 동일 규칙)가 깨졌다** — InMemory 가 재적재 시 apt_dong 을 NULL 로 덮어 PostGIS 의 COALESCE
보존과 어긋나고(반례 실증), 그 보존 로직에 테스트가 없다. 위 통과 조건 2건을 채우면 재판정 PASS.

---

## CR-016 · 2026-07-25 · APTDONG-1 수정 재검증 (code-reviewer, herdr re-review 대행)

**판정: `APTDONG-1` CLOSE (PASS) — CR-015 FAIL 해소.**
대상: working tree(미커밋) `loader.py`(InMemory update 경로)·`test_ingest_loader.py`(회귀 1건)
회귀: 대상 `tests/test_ingest.py`+`tests/test_ingest_loader.py` **47 passed**(신규 +1) · 전체 **342 passed · 50 skipped(needs_db)**

### 수정 확인 — 두 로더가 이제 동일 규칙

`InMemoryTradeLoader.load` update 경로(loader.py:130-139)에 COALESCE 동등 로직이 들어갔다:
```python
if nk in self.trades:
    if row["apt_dong"] is None:                     # 새 값이 결측이면
        row["apt_dong"] = self.trades[nk].get("apt_dong")   # 기존 동 보존
    self.trades[nk] = row
```
- 새 값 有 → 최신값 채택 / 새 값 None → 기존값 보존. PostGIS `apt_dong = COALESCE(:apt_dong, apt_dong)`(loader.py:244, **미변경**)와 **의미 동일**.
- `git diff` 로 확인: loader.py 변경은 InMemory 블록뿐이고 PostGIS COALESCE·INSERT 정합은 그대로다.

### 독립 재현 — 원 반례 + 경계 6종 전부 정상

| # | 시나리오 | apt_dong | 판정 |
|---|---|---|---|
| ① | **CR-015 원 반례**: '103' → 결측·해제 재유입 | **'103' 보존**(is_cancelled=True) | ✅ 해소 |
| ② | '103' → '105' 재유입 | '105'(최신 우선) | ✅ |
| ③ | 결측 → '103' 재유입(뒤늦게 채움) | '103' | ✅ |
| ④ | 결측 → 결측 | None | ✅ |
| ⑤ | '103' → '103' 동일 재수집(멱등) | '103' | ✅ |
| ⑥ | '103' → 결측해제 → 정상결측 복원 | '103'·is_cancelled=False | ✅ |

①은 CR-015에서 `after=None`(동 소실)로 실패했던 바로 그 입력인데, 이제 '103'이 보존된다.
is_cancelled 는 여전히 최신값으로 갱신돼 INGEST-2(해제→시세 제외) 방어도 무손상이다.

### 회귀 테스트 — 핵심 write-path 커버

`test_동은_결측_재유입에도_보존된다` 추가(test_ingest_loader.py). `_deal_xml(..., dong=None)` 로 `<동>`
필드를 제어하며 parse_response→normalize→load 전 구간을 탄다. **보존(None 재유입)·최신우선(신규값)·
is_cancelled 갱신** 세 축을 한 테스트에서 못박아, 누가 InMemory 든 PostGIS 든 규칙을 되돌리면 즉시 깨진다.
(PostGIS COALESCE 실 SQL 동일동작은 needs_db 로 추후 실측 권고 — 비차단, needs_db_carryover 에 준함.)

### 판정
**PASS. `APTDONG-1` CLOSE.** CR-015의 통과 조건 2건(① InMemory update 를 COALESCE 규칙과 일치,
② 재적재 보존 회귀 테스트)이 모두 충족됐다. 두 로더가 apt_dong 을 동일하게 다루며(불변식4 회복),
CR-015에서 PASS 판정했던 불변식 1·2·3·5(자연키 미포함·INSERT/UPDATE 정합·정규화·파티션 전파)는
이번 수정으로 영향받지 않는다. **apt_dong/동 실측 기능 변경 전체가 이제 PASS.**

---

## CR-017 · 2026-07-25 · F4 동별 실측(dong_effect·orchestrator·postgis) (code-reviewer, herdr re-review 대행)

**판정: PASS.** apt_dong 을 F4 밸류에이션에 연결한 변경 전체가 정확성·설계·테스트·G2 관점에서 견고하다.
scope: F4 동별 실측(dong_effect·orchestrator·postgis) · reviewer: code-reviewer (herdr re-review 대행 — 독립 감사)
회귀: `tests/test_valuation.py`+`tests/test_agents.py` 대상 통과, 전체 **352 passed · 50 skipped(needs_db)** 재현(exit 0).

> PM 직접 구현이므로 문서 신뢰 대신 **함수를 직접 호출·정독해 반례를 찾았다.** 아래 7개 검증축 전부에서
> 지어낸 값·off-by-one·창 불일치·나눗셈 결함을 찾지 못했다.

### 반례 탐색 결과 — 7개 검증축 전부 PASS

| # | 검증축 | 결과 | 근거(파일:라인) |
|---|---|---|---|
| 1 | ₩/㎡ 정규화(면적 구성편차 보정) | ✅ | `stats.py:128,134` 이 절대가 아니라 `price_krw/area_m2` 로 overall·동별 모두 계산. `test_동별은_면적당가격으로_구성편차를_보정한다` 가 면적 120 vs 60 이지만 ₩/㎡ 동일 → 두 동 ratio≈1.0(abs 0.01) 로 착시 제거를 **실제로** 검증 |
| 1b | area==0 나눗셈 방어 | ✅ | `stats.py:120-121` elig 필터에 `if t.area_m2 > 0`. overall_ppm·by_dong 모두 elig 만 사용 → 0-나눗셈 불가. (전용 테스트는 없으나 구조적으로 차단) |
| 2 | 기준(분모) 선택 | ✅ | `overall_ppm` = **단지 전체** elig(동 결측 포함)의 ₩/㎡ 중위(`stats.py:128`). 배율 의미 "이 동 vs 단지 평균" 과 일치. `coverage = with_dong/elig`(`stats.py:129-130`) 정확 |
| 3 | 표본 임계값 경계 | ✅ | 전체 `len(elig) < MIN_SAMPLE(5)`(`:122`) → 5 포함. 동별 `len(ppms) < min_sample_dong(3)`(`:138`) → **정확히 3 포함**. `test_동별_편차를_실측한다`(동당 3건)·`test_동_표본이_부족한_동은_빠진다`(총 5=경계, 동 4/1)로 양 경계 실검증. off-by-one 없음 |
| 4 | method 분기 | ✅ | 실측(aptDong)=stats_out 有 / 표본부족=elig<5 / 동정보없음=stats_out 空&coverage==0.0 / 동표본부족=stats_out 空&coverage!=0.0. coverage==0.0 은 with_dong 空일 때 `0/n=0.0` 정확값이라 부동소수 문제 없음(`:148-152`) |
| 5 | 지어내지 않기(G2) | ✅ | `models.py:126-127` available=False → `to_evidence()==[]`. `_dong_valuation_dict` 폴백 confidence=**0.0**(`orchestrator.py`), 실측만 0.85. 폴백은 dongs 데이터 미노출·사유만. 추정을 실측처럼 내놓는 경로 없음. `test_동정보가_없으면_동정보없음_폴백`·`test_모든_동이_표본부족이면_폴백을_알린다`(to_evidence==[]) 검증 |
| 6 | 오케스트레이터 정합 | ✅ | `_dong_valuation_dict` 가 None(실거래부족)/False(폴백)/True(실측) 3경우 모두 처리. `valuation_finding`(`:172`)·pipeline(`:477`) 둘 다 `months=band.period_months` **동일 창**. target_floor 는 period 산정에 무관(ladder 는 floor 무필터)이라 두 band 의 period_months 동일 → 창 불일치 없음 |
| 7 | 정렬 | ✅ | `stats.py:160` `sort(key=ratio, reverse=True)` → 비싼 동→싼 동. `dongs[0]`=대표(top). `test_동별_편차를_실측한다` 가 `dv.dongs[0].dong=="101"`(비싼 동) 확인 |

### 문서 정정 확인
`03-valuation-trader.md`·`api-spec.md` 가 초안("실거래에 동 없음→좌표추정만")을 운영 API aptDong 77~93%
실측 1순위로 정정하고, **basis(trade_measured vs listing_reported)·confidence 로 실측/추정 구분**을 명시.
`stats.py:11-13` 규칙4 docstring 도 동일하게 정정됨. 문서-코드 일치.

### 비차단 관찰(코멘트 — pass 유지)

| ID | 내용 |
|---|---|
| CR17-1 | **중복 계산**: pipeline(`orchestrator.py:475,477`)이 `fair_price_band`+`dong_effect` 를 `valuation_finding` 내부(`:151,172`)와 별개로 다시 계산 — 후보당 각 2회. 입력 동일이라 결과 일치(정확성 무영향), 기존 I-13 중복 패턴의 확장. 성능 사안 |
| CR17-2 | **coverage 반올림 극단 왜곡**: with_dong 이 비어있지 않으나 극단 편중(동 비율 <0.05%)이면 `round(...,1)==0.0` 이 되어 method 가 "동표본부족" 대신 "동정보없음"으로 오라벨될 수 있음. 운영 API 77~93% 에선 사실상 발생 불가이고, **어느 쪽이든 available=False·confidence 0.0·evidence [] 로 동일**해 값 조작·G2 위반 없음(사유 문구만 부정확). |
| CR17-3 | area==0·overall==4(표본부족) 등 방어 분기에 전용 테스트는 없으나 로직이 단순·명시적이라 회귀 위험 낮음 |

### 판정
**PASS.** dong_effect 가 ₩/㎡ 로 면적 구성편차를 보정하고, 분모를 단지 전체로 두어 배율 의미가 정확하며,
표본 경계(전체 5·동별 3)에 off-by-one 이 없고, 실측/폴백을 basis·confidence 로 구조적으로 구분해 G2 를
지킨다. 오케스트레이터가 None/폴백/실측 3경우를 모두 처리하고 dong_effect 를 밴드와 동일 창으로 부른다.
테스트 10건(단위 7·통합 3)이 핵심 주장을 실제로 검증하며 전체 회귀 352 passed·50 skipped 재현. 비차단 3건은
성능·문구 사안으로 게이트를 막지 않는다.

---

## CR-018 · 2026-07-25 · 프론트 FE-1 로그인 · FE-2 지도 마커 (code-reviewer, herdr re-review 대행)

**판정: FAIL — FE-1 PASS / FE-2 REJECT (`CR18-1` 1건)**
scope=프론트 FE-1 로그인·FE-2 지도마커 · reviewer=code-reviewer (herdr re-review 대행)
대상: working tree 미커밋 diff + 신규 파일(`client.ts`·`useAuth.ts`·`AuthForm.tsx`·`mapMarkers.ts`·
`MapView.tsx`·`App.tsx`·`ComplexCard.tsx`·`BottomSheet.tsx`·`validation.ts`·`notices.ts` + 테스트 3종)

### 재현
```
frontend: npm run typecheck  ✅ 무출력(통과)
          npm test           ✅ 36 passed (4 files: format 15 · client 7 · mapMarkers 10 · AuthForm 4)
          npm run build      ✅ tsc -b + vite — 42 modules, dist 161.42 kB
backend : pytest -p no:warnings ✅ 352 passed · 50 skipped (기준선 일치, 이 diff 는 백엔드 무변경)
```
> ⚠️ 백엔드 3회 실행 중 1회에서 `test_security.py` 5건이 `argon2 HashingError: Memory allocation error` 로
> 실패했다. **SR-008 에 이미 기록된 로컬 자원 flake** 이고 이 diff 와 무관하다(백엔드 파일 변경 0건).
> 재실행 2회는 352 passed. 기록만 남긴다.

### 검증 방법
문서·주석을 믿지 않고 **임시 반례 테스트 파일을 만들어 5개 가설을 실행으로 검증**한 뒤 삭제했다
(working tree 원상복구 확인). 아래 ✅/⛔ 는 전부 그 실행 결과다.

---

### FE-1 로그인 — **PASS**

| # | 검증축(지시) | 결과 | 근거(파일:라인) |
|---|---|---|---|
| 1a | 401→refresh 1회→실패 시 폐기+로그아웃 | ✅ | `client.ts:180-206`. 재시도는 `raw()` 직접 호출이라 **정확히 1회** |
| 1b | **무한 재시도 루프 불가** | ✅ | `request()` 는 자기 자신을 재귀호출하지 않는다. refresh 도 `request` 가 아니라 `raw("/auth/refresh")`(`:190`) — 재진입 경로가 구조적으로 없다 |
| 1c | refresh 요청 자체가 401 이면 | ✅ | `raw` 가 던짐 → `catch{ logout(); throw e }`(`:195-198`). 원 401 을 전파하고 토큰 폐기. 테스트 `refresh 가 실패하면 토큰을 폐기하고 로그아웃을 방송한다` 가 fetch 2회로 실검증 |
| 1d | refresh 성공 후 원 요청 1회만 재시도 | ✅ | `:199-204`. 테스트가 `fetch` 3회 + 재시도 헤더 `Bearer a2` 를 단언 |
| 1e | 재시도도 401 이면 | ✅ | `:202` logout 후 e2 전파 |
| 2a | localStorage 폴백 실동작 | ✅ | `browserStorage()`(`:83-98`)가 `typeof` 검사 + **probe write/remove** 로 판정 → 사파리 프라이빗처럼 setItem 이 던지는 환경에서 `memoryStorage()` 로 대체(`:100`) |
| 2b | 로그아웃 시 access·refresh **둘 다** 소거 | ✅ | `logout()→setTokens(null,null)`(`:146`) → 메모리 2개 `null` + `storage.remove` 2개(`:132-133`) + `emitAuth`(`:135`). 누락 없음 |
| 3 | 네트워크 오류를 401 로 오인하지 않는가 | ✅ | `:184` `!(e instanceof ApiException)` 이면 즉시 전파 — fetch reject 로 로그아웃되지 않는다 |
| 4 | 게이트 배선 | ✅ | `App.tsx:154-159` 미인증→`AuthForm`. `useAuth.ts:13` 이 `subscribeAuth` 구독 → 401 폐기가 화면 전환으로 자동 연결 |
| 5 | 모바일 퍼스트 UX | ✅ | `inputMode`·`enterKeyHint`·`autoComplete(username/current-password/new-password)`·`autoCapitalize=none`(`AuthForm.tsx:82-105`), 입력 `--fs-body 17px`(≥16px → iOS 포커스 확대 없음), 토글 44px·제출 50px·전환 44px, 에러는 alert 아닌 필드 하단 `role="alert"` |
| 6 | 계정열거 방지 | ✅ | `messageFor()`(`:171-182`)가 401 을 "이메일 또는 비밀번호가 올바르지 않습니다" 하나로 합침. 테스트 있음 |
| 7 | 서버 계약 복사 | ✅ | `validation.ts:10-11` 이 `RegisterIn` 의 12/256 을 그대로 복사하고 "서버보다 엄격히 막지 않는다"를 문서화. 권장규칙(문자종류)은 `required:false` 라 제출을 막지 않음 |

#### 비차단 관찰 (FE-1 — 게이트 무차단)

| ID | 심각도 | 내용 · 근거 |
|---|:--:|---|
| `CR18-2` | medium | **동시 refresh 중복(단일비행 없음).** 반례 재현: 401 이 될 요청 2건을 `Promise.all` 로 동시 투입 → `/auth/refresh` 가 **2회** 나갔다(기대 1회). 현재는 무해하다 — 백엔드 `routes.py:98-119` 가 stateless JWT 재발급이라 **회전·블랙리스트가 없고**, `deploy/nginx-realestate.conf:85` 의 엄격 존(1r/s)은 login/register 만 걸려 refresh 는 `re_api`(10r/s)다. 그러나 나중에 refresh rotation 을 넣는 순간 "먼저 도착한 요청이 뒤 요청의 토큰을 무효화 → 세션 중 강제 로그아웃"으로 **조용히** 바뀐다. 권고: 진행 중 refresh Promise 를 모듈 변수에 캐시해 공유 |
| `CR18-3` | low | **저장소 런타임 쓰기 실패 시 상태 불일치.** 반례 재현: `storage.set` 이 `QuotaExceededError` 를 던지게 하고 로그인 → HTTP 는 성공했는데 `setTokens`(`:129`)가 던져 **`emitAuth`(`:135`)에 도달하지 못한다**. 결과 `isAuthenticated()===true` 인데 방송 0건 → 화면은 로그인 폼에 머물고 "가입/로그인 실패" 에러만 뜬다. 생성 시점 probe 는 통과했으나 세션 중 쿼터가 찬 경우가 경로다. 권고: `storage.set` 을 try/catch 로 감싸 저장 실패해도 메모리 토큰+방송은 진행 |
| `CR18-4` | low | `isAuthenticated()`(`:151`)가 `accessToken !== null`. `configureAuthStorage` 로 RN AsyncStorage 어댑터를 끼웠을 때 `get` 이 `undefined` 를 돌려주면 **토큰 없이 인증 판정**이 나고 게이트가 열린다(그 뒤 401→refresh 없음→logout 으로 자가치유하나 한 프레임 노출). `!= null` 또는 truthy 판정 권고 |
| `CR18-9` | low | `useAuth` 가 `useState(isAuthenticated)` + `useEffect` 구독이라 렌더~구독 사이 변경을 놓칠 수 있다(고전적 tearing). 실사용 위험은 사실상 0. React 18 이면 `useSyncExternalStore` 가 정석 |

---

### FE-2 지도 마커 — **REJECT (`CR18-1`)**

| # | 검증축(지시) | 결과 | 근거(파일:라인) |
|---|---|---|---|
| 1 | 단지 마커 렌더링 | ✅ | `mapMarkers.ts:124-155` `setComplexes` 가 항목당 CustomOverlay 생성·`setMap(map)`. 테스트가 3건→오버레이 3개 확인 |
| 2 | 줌 레벨별 클러스터링 | ✅ | `setClusters`(`:164-184`) + 탭 시 `panTo`+`setLevel(-2)`(`MapView.tsx:124-129`) |
| 3 | **`CLUSTER_ZOOM_THRESHOLD` 규약 준수** | ✅ | 프론트는 **13 을 하드코딩해 분기하지 않는다.** `App.tsx:40-47` 이 오직 서버 응답 `res.level` 로만 items/clusters 를 가른다 → 백엔드 `routes.py:245 CLUSTER_ZOOM_THRESHOLD = 13` 이 바뀌어도 자동 추종. 소스의 `13` 은 `MapView.tsx:20-21,111,121` **주석 4곳뿐**(grep 전수) — 분기 코드 0건. 어긋날 여지 없음 |
| 4a | 좌표 변환 뒤집힘 | ✅ | `mapMarkers.ts:101` `LatLng(point[1], point[0])`, `MapView.tsx:127` 동일. 백엔드 `routes.py:318 point:[c.lon,c.lat]` · `:306 center:[lon,lat]` 와 정합. **직접 실행 확인**: `point=[127.0,37.5]` → `LatLng.lat===37.5 && .lng===127.0` |
| 4b | bbox 축 순서 | ✅ | `MapView.tsx:94` `sw.getLng(),sw.getLat(),ne.getLng(),ne.getLat()` = 백엔드 `routes.py:252` `minLon,minLat,maxLon,maxLat` |
| 5a | 마커·리스너 정리 | ✅ | `detach()`(`:186-190`)가 click·keydown `removeEventListener` + `setMap(null)`. **실행 검증**: 재렌더 후 옛 el 클릭 → `onSelect` 미호출 / `destroy()` 후에도 미호출 + `setMap(null)` 기록 |
| 5b | 이동마다 누수 | ✅ | `setComplexes`/`setClusters` 가 **먼저 `clear*()`** 를 호출(`:125,165`) → 이전 오버레이가 남지 않는다. 언마운트 시 `MapView.tsx:106` `layerRef.current?.destroy()` |
| 6 | **양방향 동기화 루프** | ⛔ | **`CR18-1`** — 아래 |
| 7 | 탭 → 바텀시트 연동 | ✅ | 마커 click/Enter → `onSelect(id)`(`:109-121`) → `App.handleSelect`(`:80-83`) `setSelected` + 시트 `peek→half` → `ComplexCard` 가 `selected` 시 `scrollIntoView({block:"nearest"})`(신규) 로 해당 카드로 스크롤. 역방향(카드 탭)도 같은 핸들러 |
| 8 | XSS | ✅ | `buildLabelEl`(`:39-49`)이 `textContent` 만 사용, `innerHTML`·`dangerouslySetInnerHTML` 0건. 테스트가 이미지 태그 주입으로 실검증 |
| 9 | 디자인 이탈(CustomOverlay) | ✅ 수용 | 기능 의도(렌더·줌별 군집·탭→시트) 충족 확인. 승인된 이탈이므로 이탈 자체로 반려하지 않음. 단 성능은 `CR18-7` 로 지적 |

#### ⛔ `CR18-1` (high · **차단**) — 선택이 유지되면 지도가 사용자의 팬을 되감는다

**결함**: `mapMarkers.ts:158-161` 이 `setComplexes` **호출될 때마다** `selectedId != null` 이면 무조건
`map.panTo(선택단지)` 를 실행한다. "선택이 **바뀌었을 때**" 가 아니라 "**그릴 때마다**" 다.

**실행 반례** (직접 재현):
```
selectedId 를 7 로 고정한 채 setComplexes 를 3회 호출 → map.panTo 호출 3회 (기대 1회)
```

**실제 사용자 경로로의 전파** (코드 3개가 맞물린다):
1. `MapView.tsx:112-119` 의 마커 effect deps 에 `items` 가 있다.
2. `App.tsx:39-46` 은 조회가 성공할 때마다 `setItems(res.items)` 로 **새 배열**을 넣는다 → 지도를 움직여
   재조회될 때마다 effect 가 다시 돈다.
3. `App.tsx:71-77` `onBoundsChange` 는 `setSnap` + `fetchArea` 뿐 — **`selected` 를 해제하지 않는다.**

→ 마커나 카드를 한 번 탭한 뒤 사용자가 지도를 조금 끌면:
`idle → 350ms 디바운스 → 조회 → setItems → effect → setComplexes → panTo(선택단지)` 로
**지도가 원래 자리로 되감긴다.** 선택 단지가 새 bbox 안에 남아 있으면(화면 한 폭 미만의 팬은 거의 항상)
확정적으로 재현되고, 크게 끌어 선택 단지가 화면 밖으로 나가야만 팬이 유지된다 — 동작이 들쭉날쭉하다.

**부수 피해**: 되감김 자체가 다시 `idle` 을 일으켜 **팬 1회에 서버 조회가 2회** 나간다. 두 번째 조회는
사용자가 아니라 우리 코드가 만든 것이다. 같은 파일(`App.tsx:30`)이 "지도를 움직일 때마다 요청이 나가면
서버가 죽는다"며 디바운스를 넣어 놓고, 그 절약분을 이 경로가 되돌린다.

> **과장하지 않는다**: 무한 루프는 **아니다**. 두 번째 `panTo` 는 이미 같은 중심이라 이동이 없어 2사이클에서
> 멈춘다. 문제는 무한성이 아니라 **사용자 입력이 되돌려지고 요청이 2배가 된다**는 점이다.
> 지도가 이 제품의 주 화면(F1)이고, 되감김의 방아쇠가 바로 그 화면의 주 동작(마커 탭)이라 차단으로 본다.

**통과 조건**
1. `panTo` 를 **선택이 바뀐 순간에만** 실행한다. 예: `MarkerLayer` 에 `lastPannedId` 를 두고 직전과 다를
   때만 이동, 또는 `setComplexes` 에서 `panTo` 를 떼어내 `focusComplex(id)` 로 분리하고 `MapView` 가
   `useEffect(..., [selectedId])` **하나에서만** 부른다.
2. 회귀 테스트 1건 — **같은 `selectedId` 로 `setComplexes` 를 2회 이상 호출해도 `panTo` 는 1회**.
3. (함께) `CR18-5` 해소 — 좌표 순서 단언 1건. 지금 구현은 옳지만 **그물이 없다**. `LatLng(point[0],point[1])`
   로 한 글자만 뒤집혀도 마커 전부가 엉뚱한 곳에 찍히는데 36개 테스트 중 이를 잡는 것이 하나도 없다.
   내가 쓴 단언은 3줄이었다: `expect(pos.lat).toBe(37.5); expect(pos.lng).toBe(127.0)`.

#### 비차단 관찰 (FE-2)

| ID | 심각도 | 내용 · 근거 |
|---|:--:|---|
| `CR18-5` | medium | **좌표 변환 회귀 테스트 부재.** `mapMarkers.test.ts` 는 `opts.position` 을 한 번도 단언하지 않는다(목 `LatLng` 이 lat/lng 을 보관하는데도). 이 기능에서 가장 조용하고 가장 치명적인 회귀축이 무방비. → `CR18-1` 통과조건 3에 포함 |
| `CR18-6` | medium | **지도 이벤트 리스너 미해제.** `MapView.tsx:98` `addListener(map,"idle",emit)` 에 대응하는 `removeListener` 가 cleanup(`:104-108`)에 없고 `mapRef.current` 도 null 로 되돌리지 않는다. 로그아웃→재로그인마다 옛 map 객체와 그 핸들러(옛 컴포넌트의 `onBoundsRef` 를 캡처)가 남는다. `MarkerLayer.destroy()` 는 제대로 부른다 |
| `CR18-7` | medium | **CustomOverlay 대량 DOM(승인된 이탈의 대가).** 서버 상한이 `limit=500`(`repositories/memory.py:80`)이라 최악 500 오버레이 × (div+span) + 리스너 2개 ≈ 2,000+ 노드. 게다가 `setComplexes` 가 id 기준 diff 없이 **매 갱신마다 전량 파괴 후 재생성**하므로, 팬 한 번(350ms 디바운스)마다 500개를 새로 만든다. `kakao.maps.Marker` 는 내부적으로 묶어 그리지만 CustomOverlay 는 매 이동마다 개별 DOM 을 재배치한다 — 중급 모바일에서 프레임 드랍이 예상된다. 완화안: (a) id 기준 재사용(diff), (b) 화면당 표시 상한 + "N개 더" 표기, (c) 임계 개수 초과 시 pill→점(dot) 강등 |
| `CR18-8` | low | **문서-현실 불일치.** `MapView.css:36` 주석은 "탭 영역 44px 확보"라고 적었으나 `.map-pill--complex` 는 `min-height:34px`(`:68`)이고 `padding:8px`(border-box)라 실제 높이가 34px 다 — 프로젝트 자체 기준(CR-006 C8 터치 44px) 미달. 값을 고치든 주석을 고치든 둘을 일치시킬 것 |
| `CR18-10` | low | `MapView` 의 `rankById`(순위 배지) 를 `App.tsx:89-95` 가 넘기지 않아 현재 **죽은 경로**다. 추천 배선 시 연결하거나 지울 것 |
| — | 참고(선재) | 넓게 줌아웃하면 bbox 폭이 `_MAX_BBOX_DEGREES=2.0`(`routes.py:246`)을 넘어 400 `조회 범위가 너무 넓습니다` 가 뜬다. `zoom = 20 - map.getLevel()`(`MapView.tsx:92`) 매핑상 카카오 level 11 이상에서 발생 가능 — **군집이 보여야 할 구간에서 에러만 보인다.** 이 diff 가 만든 결함은 아니나(bbox emit 은 CR-006), 마커가 붙은 지금 사용자 눈에 처음 띄는 자리다 |

---

### 테스트의 실효성 (지시 7)

목만 검증하는 자기충족적 테스트인가 — **대체로 아니다.** 근거:
- **401 refresh 경로**: fetch 호출 **횟수**(1/2/3)와 재시도 요청의 **Authorization 헤더값**(`Bearer a2`)까지
  단언한다. "refresh 없으면 fetch 1회" 는 재시도가 실수로 생기면 즉시 깨지는 진짜 그물이다.
- **마커 정리 경로**: `setMapCalls` 에 `null` 이 담기는지 확인 — 오버레이 해제 회귀는 잡는다.
  다만 **리스너 해제는 단언하지 않는다**(별도로 확인했고 실제로는 정상).
- **AuthForm**: `userEvent` 로 실제 타이핑·클릭을 태워 disabled 전이·에러 문구·type 토글을 본다. 목은 경계인
  `api.login/register` 에만 걸려 있어 폼 로직은 실제로 돈다.
- **구멍 2개**: (1) 좌표 순서(`CR18-5`) (2) `CR18-1` 이 잡히지 않은 이유 — 마커 테스트가 `setComplexes` 를
  **한 번만** 부른다. 두 번 부르는 순간 드러났을 결함이다(반례는 3회 호출).

### 판정

**FAIL.** FE-1 은 통과조건 1(폼·토큰 저장/첨부·401 처리) 2(모바일 퍼스트)를 모두 충족하고, 지시가 요구한
반례 축(무한루프·refresh 401·1회 재시도·완전 로그아웃·저장소 폴백)에서 결함이 나오지 않았다 — **PASS**.
FE-2 는 통과조건 1(마커+줌별 군집, 규약을 하드코딩하지 않고 응답 level 로 추종) 2(탭→시트)를 충족하고
좌표 변환·마커 정리도 정확하나, **`CR18-1` 되감기 결함이 주 화면의 주 동작 뒤 지도 조작을 망가뜨리고
요청을 2배로 만든다** — 수정 비용이 몇 줄인 반면 방치 시 실사용에서 즉시 드러나는 종류라 **REJECT**.

`CR18-1` 통과조건 3개(panTo 를 선택 변경 시로 한정 · 회귀 테스트 1건 · 좌표 순서 단언 1건)를 충족하면
FE-2 를 CLOSE 한다. `CR18-2`~`CR18-10` 은 게이트를 막지 않으며 다음 라운드 권고다.

---

## CR-019 · 2026-07-25 · CR18-1 수정 재검증 + 쿠키 인증 전환 (code-reviewer, herdr re-review 대행)

**판정: PASS — `CR18-1` CLOSE · FE-2 CLOSE · 쿠키 인증 전환 PASS**
scope=프론트 FE-2 재검증(CR18-1·5·6·8) + FE-1 부수수정(CR18-2·3) + **인증 계약 쿠키 전환**(SR15-1 대응, 백엔드 포함)
reviewer=code-reviewer (herdr re-review 대행) · 대상: working tree 미커밋 diff + 신규 `backend/app/api/cookies.py`

### 재현
```
frontend: npm run typecheck  ✅ 무출력  ·  npm test ✅ 49 passed(15/13/17/4)  ·  npm run build ✅ 성공
backend : pytest -p no:warnings ✅ 369 passed · 50 skipped  (CR-018 기준선 352 대비 +17)
```

### 검증 방법 — **변이 테스트(mutation testing)**
"회귀 테스트가 실제로 회귀를 잡는가"는 테스트가 초록불이라는 사실로는 증명되지 않는다.
그래서 **가드를 하나씩 부러뜨려 해당 테스트가 실제로 FAIL 하는지** 확인하고 원복했다.
전 파일 md5 대조로 원상복구를 확인했다(`mapMarkers.ts` `ba3063b7…`, `client.ts` `c0e2f5d5…`,
`routes.py` `7c57ab8c…`, `cookies.py` `a63b8117…`).

| # | 변이(가드 제거) | 결과 | 실제 실패 메시지 |
|---|---|:--:|---|
| A | `mapMarkers.ts` 의 `if (selectedId === this.lastPannedId) return;` 삭제 | ✅ **FAIL 발생** | `CR18-1 회귀 …` → `expected "spy" to be called 1 times, but got 3 times` |
| B | `LatLng(point[1], point[0])` → `(point[0], point[1])` 로 뒤집음 | ✅ **FAIL 3건** | `expected 127.0276 to be 37.4979` (마커·panTo·군집 3곳 전부) |
| C | `client.ts` 의 `if (refreshInFlight) return refreshInFlight;` 삭제 | ✅ **FAIL 발생** | `CR18-2 회귀 — 동시 401 이 N 개여도 refresh 는 1회만` |
| D | `cookies.py` 삭제 쿠키 `path` 를 `/` 로 어긋냄 | ✅ **FAIL 2건** | `test_유효하지않은_refresh_쿠키는_401이면서_쿠키가_삭제된다`, `test_logout은_쿠키를_만료시킨다` |
| E | `/auth/refresh` 의 `dependencies=[Depends(require_ajax_header)]` 제거 | ✅ **FAIL 발생** | `test_커스텀_헤더_없는_refresh는_거부` → `assert 200 == 403` |

**구현자의 주장("가드를 빼서 테스트가 깨지는 것까지 확인했다")은 사실이다.** 5개 전부 자기충족적이지 않다.
특히 A 는 CR-018 에서 내가 계측한 증상(panTo 3회)과 **숫자까지 동일**하게 재현된다.

---

### 1. `CR18-1` (차단이었던 결함) — **CLOSE**

`mapMarkers.ts:175-191` 에 `syncFocus()` 신설. 판정 축 5개를 코드와 테스트로 확인:

| 상황 | 기대 | 구현 | 확인 |
|---|---|---|:--:|
| 같은 선택으로 다시 그림(지도 팬 → 재조회) | panTo 없음 | `selectedId === lastPannedId` → return(`:182`) | ✅ 회귀 테스트 + 변이 A |
| 선택이 바뀜 | panTo 1회 | `lastPannedId` 갱신(`:190`) | ✅ `선택이 바뀌면 그때는 다시 panTo` |
| 선택 해제 후 같은 단지 재선택 | 다시 이동 | `selectedId === null` 이면 기억 소거(`:176-179`) | ✅ 전용 테스트 |
| 선택 단지가 응답에 없음 | 이동 안 함 + **기억 남기지 않음** | `if (!sel …) return`(`:187`) — `lastPannedId` 미갱신 | ✅ 코드 |
| 선택 없음 | 지도 안 움직임 | `selectedId == null` 경로 | ✅ 전용 테스트 |

`destroy()` 가 `lastPannedId` 도 초기화한다(`:234`) — 레이어를 다시 만들면 첫 선택에서 정상 이동한다.
**되감김 경로가 끊겼고, 그로 인해 팬 1회당 조회가 2회 나가던 부수 피해도 함께 사라진다.**

### 2. 함께 처리된 비차단 지적

| ID | 결과 | 확인 |
|---|:--:|---|
| `CR18-5` 좌표 회귀 테스트 부재 | ✅ 해소 | 단지 마커 `position`·`panTo` 대상·군집 `center` **3곳** 단언. 경도(127.0276)>위도(37.4979)로 값을 잡아 뒤집히면 반드시 깨지게 설계. 변이 B 로 3건 동시 FAIL 확인 |
| `CR18-2` 동시 refresh 중복 | ✅ 해소 | `refreshInFlight` 공유 Promise(`client.ts:174-207`). 테스트가 **10ms 지연을 넣어** 직렬 실행으로 우연히 통과하는 것을 막는다(테스트 설계가 좋다). 변이 C 로 확인 |
| `CR18-6` idle 리스너 미해제 | ✅ 해소 | `removeIdle` 클로저를 만들어 cleanup 에서 호출 + `layerRef.destroy()` + `mapRef.current = null`(`MapView.tsx:102,108-115`) |
| `CR18-3` 저장소 예외로 방송 끊김 | ✅ 해소(형태 변경) | 저장소 자체가 사라졌다(메모리 전용). 상태 변경이 `setAccessToken → emitAuth` 단일 경로로 모이고, `emitAuth` 가 **구독자 예외를 삼켜** 나머지 구독자에게 도달을 보장(`client.ts:122-131`) |
| `CR18-8` 44px 탭 영역 | ✅ 해소 | `.map-pill{position:relative}` + `.map-pill::before{content:"";position:absolute;inset:-5px}` → 34px + 5×2 = **44px**. 의사요소는 별도 이벤트 타깃이 아니라 **생성 원본 요소로 히트가 전달**되므로 리스너(`.map-pill`)가 그대로 받는다. `pointer-events:none` 없음·`overflow:hidden` 없음 확인. 시각 34px 유지로 "지도가 pill 로 덮이는" 부작용도 피했다. 군집은 46px 라 원래 충족 |
| `CR18-10` `rankById` 죽은 경로 | ⏸ 유지 | 추천 배선 시점 과제 |

---

### 3. 인증 계약 쿠키 전환 (SR15-1 대응) — **PASS**

정확성·설계·테스트 관점의 독립 감사. 문서 주장을 믿지 않고 **TestClient 로 실제 헤더를 떠서** 대조했다
(운영과 동일하게 `Secure=on` 인 https 클라이언트로 왕복 — 테스트가 설정을 느슨하게 풀어 우회하지 않은 점은 좋은 설계다).

#### 3-1. 지시 5개 축

| # | 축 | 결과 | 근거 |
|---|---|:--:|---|
| ① | StrictMode/동시성에서 `restoreSession` 1회 | ✅ | `main.tsx:25` **모듈 최상위** 호출 — 이펙트가 아니므로 StrictMode 이중 마운트와 무관하게 모듈당 1회. 게다가 single-flight 가 2겹으로 받쳐 **`restoreSession()` 을 동시에 2번 불러도 refresh 는 1회**(실측) |
| ② | `checked` 3상태 누락 없음 | ✅ | `App.tsx:160/171/172` = 판정전(boot)·미인증(AuthForm)·인증(MapHome). `useAuth.ts:16` 이 **구독 직전에 `getAuthState()` 를 한 번 당겨** 렌더~구독 사이 놓친 방송을 메운다(CR18-9 로 지적했던 tearing 도 함께 해소) |
| ③ | 로그아웃 중 refresh 완료로 세션 부활 | ✅ **실측 차단** | `clearSession()` 이 `refreshInFlight = null`(`:145`), refresh 의 `.then` 이 `refreshInFlight !== p` 면 결과를 버린다(`:194-196`). **반례 실행**: refresh 를 게이트로 붙잡아 두고 `logout()` 실행 → 이후 refresh 200 도착 → `isAuthenticated() === false` 유지(부활 없음) |
| ④ | 쿠키 삭제 속성 = 발급 속성 | ✅ **실측 일치** | 발급 `HttpOnly; Max-Age=604800; Path=/api/v1/auth; SameSite=Strict; Secure` / 삭제 `""; Max-Age=0; Path=/api/v1/auth; HttpOnly; SameSite=Strict; Secure` — `path·httponly·secure·samesite` **4개 전부 일치**, 클라이언트 저장소에서 쿠키가 실제로 사라짐. 401 경로도 동일(서버 발급 쿠키로 재확인) |
| ⑤ | 401 vs 403 처리 분리 | ⚠️ **부분** | 일반 API 403 은 refresh 를 시도조차 하지 않아 로그인 상태 유지 ✅(실측). 그러나 **refresh 가 403 이면 401 과 똑같이 세션을 폐기**한다 → `CR19-1` |

> ④ 가 중요한 이유: 속성이 하나만 어긋나도 브라우저는 다른 쿠키로 보고 원본을 남긴다 —
> 로그아웃이 연출로 끝난다. 구현이 `expired_refresh_cookie_header()`(`cookies.py:68-77`)에서
> **문자열을 손으로 조립하지 않고 `delete_refresh_cookie` 를 프로브 Response 에 태워 재사용**하는 방식이라
> 발급·삭제가 구조적으로 어긋날 수 없다. 좋은 설계다.

#### 3-2. 계약 실측 (TestClient · https)

| 항목 | 실측 |
|---|---|
| login 응답 body | `access_token`·`token_type`·`expires_in` — **`refresh_token` 없음** ✅ |
| login `Set-Cookie` | `HttpOnly`·`Secure`·`SameSite=Strict`·`Path=/api/v1/auth`·`Max-Age=604800`(7일) **5속성 전부** ✅ |
| refresh 회전 | 호출마다 쿠키 값이 바뀜 ✅ (`jti` 도입으로 **같은 초에 발급해도 문자열이 다르다** — 회전이 이름뿐이 되는 함정 회피) |
| 옛 계약(body 로 refresh) | **401** — 본문 경로 완전 차단 ✅ (`RefreshIn` 스키마 잔존 0건) |
| access 를 refresh 쿠키에 투입 | **401** — `typ` 검증 유효 ✅ |
| 잘못된 쿠키 | 401 + 삭제 헤더, 쿠키 실제 제거 ✅ |
| CSRF 헤더 없는 refresh/logout | **403 + 쿠키 유지** ✅ — 로그아웃 CSRF(남의 세션 끊기)를 만들지 않는 판단이 옳다(`deps.py` 주석과 일치) |
| 헤더 값 관용범위 | 대소문자·앞뒤 공백 허용, `fetch`·빈값 거부 ✅ (헤더의 방어력은 값이 아니라 **크로스오리진에서 붙일 수 없다**는 데서 나오므로 관용이 맞다. `CORSMiddleware` 미설치 확인 — 프리플라이트로 뚫을 경로 없음) |
| 운영 `Secure` 강제 | `DEBUG=false` + `COOKIE_SECURE=false` → **True** ✅ 설정 실수로 평문 전송되는 경로를 구조적으로 봉쇄 |
| TTL | refresh 604800s(7일) · access 1800s ✅ 문서와 일치 |

#### 3-3. 설계·문서

- **계약 문서 일치**: `api-spec.md` 가 쿠키 속성·403 코드·회전·"본문 경로 없음"을 실제 구현과 같게 기술.
  `schemas.TokenOut` 에 *"refresh_token 필드를 다시 추가하지 마라"* 를 이유와 함께 박아둔 것도 좋다 —
  이 저장소가 반복적으로 겪은 문서-현실 괴리를 코드 쪽에서 막는다.
- **상수 단일 출처**: `ACCESS_TTL_SECONDS`/`REFRESH_TTL_SECONDS` 를 `security.py` 가 소유하고 라우터·쿠키가 참조 —
  `expires_in=1800` 하드코딩이 사라졌다.
- **레이어**: 쿠키 조립이 `cookies.py` 한 곳, CSRF 관문이 `deps.py` 한 곳. 라우터는 호출만 한다. 위반 없음.
- **REFRESH_TTL 14→7일 단축**의 근거(서버측 폐기 수단 부재 → 노출 창을 시간으로 줄임)가 상수 옆에 기록돼 있고,
  denylist 를 후속(SR15-3)으로 남긴 것도 정직하다.

---

### 4. 비차단 지적

| ID | 심각도 | 내용 · 근거 |
|---|:--:|---|
| `CR19-1` | low | **refresh 의 403 을 401 과 똑같이 취급해 세션을 버린다.** 실측: refresh 403 → `isAuthenticated()===false`. 서버는 일부러 쿠키를 살려두고(`deps.require_ajax_header` 주석) `api-spec.md` 도 *"403 … **쿠키는 유지된다**(재시도 가능)"* 라고 적었는데, **우리 클라이언트가 그 재시도 가능성을 스스로 버린다**(`client.ts:222-225` 가 refresh 실패 사유를 구분하지 않음). 발생 조건은 중간 프록시·확장이 `X-Requested-With` 를 떼는 경우로 드물고, 같은 헤더로 재시도하면 어차피 또 403 이라 자동 복구가 불가능하므로 **피해는 "다시 로그인" + 원인을 감춘 오해 유발**에 그친다. 권고: 403 은 `clearSession()` 하지 말고 "보안 헤더가 차단되었습니다" 로 구분해 알리고 사용자가 새로고침/재시도하게 한다. 클라이언트 403 경로 테스트도 0건 |
| `CR19-2` | low | `restoreSession()` 의 catch 가 `accessToken = null` 을 **직접** 대입한다(`client.ts:251`). 같은 파일이 *"상태 변화는 반드시 `emitAuth` 한 곳을 지난다"*(`:119`)고 선언했는데 이 한 줄만 우회한다(`finally` 의 `emitAuth` 덕에 결과는 같고, `checked=false` 동안 로그인 화면이 안 뜨므로 동시 로그인과 겹칠 수도 없다 — **현재는 무해**). `clearSession()` 으로 통일 권고 |
| `CR19-3` | low | 로그아웃-중-refresh race(③)는 **실측으로 막혀 있으나 테스트가 없다.** `refreshInFlight !== p` 한 줄이 방어의 전부라 리팩터링 한 번에 조용히 사라질 수 있다. 내가 쓴 반례(게이트로 refresh 를 붙잡고 logout → 늦은 200 도착)를 그대로 회귀 테스트로 넣기를 권고 |
| `CR19-4` | 정보 | StrictMode 개발 모드에서 `loadSdk` 가 `window.kakao` 확정 전에 두 번 불려 `<script>` 가 2개 붙는다(운영 무관·브라우저 캐시로 실피해 없음). 지도는 `cancelled` 가드로 1개만 생성됨을 확인 |

### 5. `CR18-7`(CustomOverlay 전량 재생성) — **의견: 이번 게이트는 비차단 유지, 단 실데이터 투입 전 필수**

수치로 정리한다. `/map/complexes` 는 상한 `limit=500`(memory·postgis 동일)이고 프론트는 응답 전량을 그린다.
- 최악 500 pill × (카카오 래퍼 div + 우리 div + span 1~2) ≈ **1,500~2,000 DOM 노드**
- CustomOverlay 는 지도 이동마다 **오버레이별로 위치를 개별 갱신**한다(Marker 처럼 묶어 그리지 않는다) → 팬/줌 중 500회 스타일 쓰기
- 게다가 `setComplexes` 가 id 기준 diff 없이 **매 조회마다 전량 파괴 후 재생성** → 팬 1회에 요소 500개 생성 + `addEventListener` 1,000회

**지금 게이트를 막지 않는 이유**: 정확성 결함이 아니고, 실데이터가 아직 없어(`MOLIT_API_KEY` 사람 대기)
현재 관측 가능한 증상이 없다. 리뷰는 실측 없이 성능을 이유로 차단하지 않는다.
**그러나 실데이터가 들어오면 강남·송파 같은 밀집 지역에서 zoom≥13 한 화면에 수백 개가 나온다 — 그때는 확실히 드러난다.**
→ **실데이터 수집 완료를 게이트로 삼아 그 전에 처리할 것.** 구체적 통과선 제안:
① id 기준 오버레이 재사용(diff) — 이동 시 재생성 0, 위치·클래스만 갱신
② 화면당 표시 상한(150~200) + "N개 더 있음" 표기 — 상한 초과는 지도가 아니라 목록으로 유도
③ 임계 초과 시 pill → dot 강등(라벨 DOM 제거)
④ 실측 근거 첨부(중급 기기 팬 시 프레임 타임) — 숫자 없이 고쳤다고 하지 말 것

---

### 판정

**PASS.** CR-018 의 차단 사유 `CR18-1` 은 해소됐고, 그 해소가 **변이 테스트로 검증된 회귀 그물**을 갖췄다
(가드를 빼면 테스트가 실제로 깨진다 — 5/5 확인). 함께 들어온 쿠키 인증 전환도 정확성·설계·테스트 모두
기준을 넘는다: 지시 5개 축 중 ①②③④는 **실측으로 확인**했고, ⑤만 부분 미충족(`CR19-1`, low)이다.
발급/삭제 속성 일치처럼 "틀리면 로그아웃이 연출로 끝나는" 지점을 구조적으로(프로브 Response 재사용) 막은 점,
테스트가 설정을 풀어 우회하지 않고 운영과 같은 `Secure=on` https 로 왕복시킨 점은 특히 좋다.

**FE-2 CLOSE.** 3단계 프론트 차단 항목(FE-1·FE-2)이 모두 해소됐다.
`CR19-1`~`CR19-4` 는 게이트를 막지 않는다. `CR18-7` 은 **실데이터 투입 전 필수 과제**로 승계한다.

---

## CR-020 · 2026-07-26 · 실데이터 수집 파이프라인 독립 감사 (code-reviewer, herdr re-review 대행)

**판정: FAIL — 차단 3건(`GEO-1`·`SEC-1`·`SEC-2`). 페이지네이션 수정은 전부 PASS.**
대상: working tree 미커밋분(신규 스크립트 7 + `app/ingest/*`·`worker`·`postgis`·`valuation`·`orchestrator`·테스트 5 + config 2)
재현: `cd backend && python -m pytest -q` → **380 passed · 50 skipped**(junit tests=430 failures=0 errors=0) — 지시 수치와 일치.

### 감사 방법
초록불을 믿지 않았다. ① 페이지 루프에 **반례 8종을 직접 투입**(A~H), ② F4 회귀 테스트를 **변이(mutation)로 부러뜨려** 실제로 잡는지 확인,
③ 지오코딩 변형 로직을 **운영 DB 의 실제 단지명 6,538건에 돌려** 충돌을 셌다, ④ 운영 PostgreSQL 에 직접 `PREPARE` 를 걸어 42P08 을 재현,
⑤ 비밀 유출은 `httpx` 예외를 만들어 산출 파일까지 따라갔다. 변이 후 원본 복구는 `git diff --stat` 동일성으로 확인(445 insertions / 47 deletions 불변).

---

### ★1. 페이지네이션 — **전 항목 PASS**. 최대 결함이 실제로 닫혔다

지시가 요구한 4가지를 반례로 각각 계측했다(모두 `run_molit_trade_ingest` 직접 호출).

| # | 반례 | 결과 | 판정 |
|---|---|---|:--:|
| A | totalCount 가 rows 의 **정확한 배수** 1000/2000/3000 | pages `[1]`/`[1,2]`/`[1,2,3]` · rows_ok 정확 · **군더더기 요청 0** | ✅ off-by-one 없음 |
| B | totalCount=0 (진짜 무거래) | 1페이지 · status=ok · failures 0 | ✅ 무거래를 실패로 오인하지 않음 |
| C | **화성 동탄 재현** totalCount=1411 | pages `[1,2]` · rows_ok=**1411** · ok | ✅ 411건 유실 해소 |
| D | rate limit 우회 | `limiter.wait()` 호출수 == fetch 호출수 (2/2) | ✅ **페이지마다 지켜짐** |
| E | 서버가 pageNo 무시(항상 1페이지) | 2페이지에서 종료 — **무한루프 아님** | ⚠️ 중복 sink(ING-3) |
| F | totalCount 없음 + 마지막이 정확히 numOfRows | pages `[1,2,3]` · 20건 · ok | ✅ '덜 찬 페이지' 종료조건 정상 |
| G | totalCount 5만 초과(MAX_PAGES) | fetch 50회에서 정지 · **status=failed** · 사유 명시 | ✅ 조용히 자르지 않음 |
| H | 2페이지에서 실패(1페이지는 이미 적재됨) | status=failed · 실패 집계 | ⚠️ rows_ok 과소(ING-2) |

- **"totalCount 를 못 채우면 ok 가 아니라 실패"** — 확인. `collected < total` 이면 `MolitPaginationError` 로 올라가 runner 가 `rows_failed` 로 집계하고
  status 가 ok 가 될 수 없다. 회귀 테스트 `test_총건수를_못채우면_성공으로_기록하지_않는다` 도 존재.
- **numOfRows ↔ totalCount 일치** — `build_params(rows=rows_per_page)` 와 종료조건 `len(trades) < rows_per_page` 가 같은 값을 쓴다. 일관됨.
- `parse_response` 가 깨진 항목을 조용히 버리지 않고 예외로 올리므로(molit.py:184·192) `collected` 는 응답 item 수와 항상 같다 —
  즉 "파싱에서 몇 건 새서 totalCount 를 못 채운다" 는 오검출 경로가 없다. 이 점이 종료조건의 신뢰를 떠받친다.

> 이 부분은 잘 만들었다. 특히 **G(상한 초과)를 성공으로 처리하지 않은 것**과 **D(루프가 limiter 를 우회하지 않는 것)** 는
> 대충 짜면 반드시 놓치는 자리다.

---

### ★2. `GEO-1` (high · **차단**) — 지오코딩이 **조용히 틀린 좌표**를 만든다. 실데이터로 이미 발생 중

`VariantGeocoder` 의 폴백 순서·조기 종료 자체는 옳다(원본 우선, 실패 시에만 변형, 변형 없으면 재시도 안 함 — 테스트로 못박힘).
문제는 **변형된 질의가 어느 단지를 가리키는지 아무도 확인하지 않는다**는 것이다.

**운영 DB 실측 (complex 6,538건 · geom 6,121건)**

| 계측 | 값 |
|---|---:|
| 변형(2차 질의)이 생기는 단지 | **992** |
| 변형 후 **서로 다른 단지가 같은 질의로 뭉치는** 그룹 | **191 그룹 / 496 단지** |
| 실제로 **다른 단지와 좌표가 완전히 같은** 단지 | **514 (7.9%)** — 237 그룹 |
| 그중 변형 충돌군과 겹치는 것 | 216 |
| 변형과 무관(원본 질의만으로도 발생) | 298 ← 선재 결함 |
| ★ **법정동이 서로 다른데 좌표가 동일**한 단지 | **68** |

```
[구미동 무지개] ← 무지개(1단지)(대림), (2단지)(엘지), (3단지)(건영), (3단지)(신한), (4단지)(주공),
                  (5단지)(청구), (6단지)(건영), (7단지)(라이프), (8단지)(제일), (9단지)(동아),
                  (10단지)(삼성), (10단지)(건영), (11단지)(금강센테리움), (12단지)(주공)   ← 14개 단지 → 질의 1개
[이매동 이매촌] ← 진흥/한신/금강/청구/삼성/동신3/동신9/삼환/동부코오롱/성지        ← 10개
[서현동 효자촌] ← 현대/럭키/임광/삼환/화성/미래타운/대창/동아/대우                  ← 9개

실제 DB 에서 좌표가 이미 겹친 예:
  방배동 삼환나띠르빌(1002-10)/(1002-21)/(1002-11)/(1002-9)/(1002-7)/(1002-22)  → 6개 단지가 한 점
  역삼동 대우디오빌 / 도곡동 대우디오빌 / 서초동 서초대우 / 서초동 서초동대우디오빌프라임 → 법정동 3개가 한 점
  야탑동 탑마을(경남)1/(선경)1/(기산)1/(쌍용)1                                    → 4개 단지가 한 점
```

**왜 차단인가**

1. **코드가 스스로 내세운 안전 전제가 실데이터에서 깨졌다.** `geocode.py:73` 은 "법정동은 절대 떼지 않는다 — 동 안에서
   이름이 겹칠 확률은 훨씬 낮다" 를 근거로 변형을 정당화한다. 그런데 **법정동을 붙인 채로도 68건이 다른 동과 같은 점을 받았다.**
   카카오 키워드 검색은 앞의 법정동을 관련도 힌트로 쓸 뿐 필터가 아니다. 전제가 틀렸으면 근거도 무효다.
2. **1기 신도시 명명규칙이 정확히 최악의 케이스다.** `마을(N단지)(시공사)` 에서 괄호는 군더더기가 아니라 **유일한 식별자**다.
   이걸 떼면 "구미동 무지개" 14개 단지가 한 질의가 되고, `size=1` 이라 **최소 13개는 틀린 좌표**를 받는다. 경기도는 서비스 범위 한복판이다.
3. **틀린 것을 맞은 것과 구분할 방법이 없다.** 반환 place_name·address_name 대조 없음, 권역(region_code) 포함 검증 없음,
   좌표 출처(원본/변형·어떤 질의였는지) 컬럼 없음. `ingest_report.py` 는 `geom_pct` **93.6%** 만 보고한다 —
   **성과 지표가 결함을 덮는다.** 85.5%→93.6% 라는 이번 라운드의 성과에 오염분이 얼마나 섞였는지 아무도 재지 않았다.
4. 좌표는 지도(F1)·입지 분석(F5)·동별 추정 폴백(F4)의 입력이다. 수백 m 어긋나면 역세권·학군 판정이 뒤집힌다.
   모듈 docstring(`geocode.py:22`, `:72`)이 **"틀린 좌표는 좌표 없음보다 나쁘다"** 라고 두 번 적어 놓고 코드가 그걸 어긴다.

**정직한 귀속**: 514건 중 298건은 원본 질의만으로도 나던 **선재 결함**이다. 이번 변경이 만든 게 아니다.
다만 이번 변경은 992개 단지에 **더 넓은 2차 질의**를 추가해 문제를 넓혔고(216건 중첩), 그 대가를 재지 않은 채
커버리지 수치만 성과로 보고했다. 선재 결함이라는 사실이 지금 닫지 않아도 되는 이유가 되지는 않는다 —
**실데이터가 이미 들어왔고, 지금이 틀린 좌표를 걸러낼 수 있는 마지막 시점**이다.

**통과조건 (택1 이상 + ⑤ 필수)**
- ① **결과 검증**: 카카오 응답의 `address_name` 법정동이 질의 법정동과 일치하는지, 또는 `place_name` 과 단지명 유사도가 임계 이상인지 확인.
  불일치면 채택하지 않고 `unresolved` 로 남긴다(좌표 없음 > 틀린 좌표).
- ② **권역 검증**: `complex.region_code` 를 이미 알고 있으므로 반환 좌표가 해당 시군구 안인지 확인(PostGIS `region.geom` 없으면 bbox 근사라도).
- ③ **충돌 차단**: 이미 다른 complex 가 쓰는 좌표면 그대로 저장하지 않는다(거부하거나 `confidence` 를 낮춰 별도 표기).
- ④ **괄호 보존 규칙**: 괄호 안에 `단지`·`차`·시공사명이 들어가면 식별자이므로 **떼지 않는다**(현재 117건이 이 유형).
- ⑤ **가시화·회귀(필수)**: `ingest_report.py` 에 좌표 충돌 건수·법정동 교차 건수 쿼리를 추가하고,
  "같은 폴백 질의로 뭉치는 두 단지에 같은 좌표를 주면 감지된다" 는 회귀 테스트 1건. 현재 신규 테스트 4건은 **행복경로만** 검증한다.

---

### ★3. `SEC-1` (medium · **차단**) — API 키가 **예외 메시지**로 새어 커밋 대상 파일에 저장된다

이번 라운드의 헤드라인 수정(httpx·httpcore·urllib3 를 WARNING 으로)은 **로깅 경로만** 막았다. 예외 경로가 그대로 열려 있다.

```
run_molit.make_http_fetch → resp.raise_for_status()
  → httpx.HTTPStatusError: "Client error '403 Forbidden' for url
     'https://apis.data.go.kr/...?serviceKey=<키>%3D%3D&LAWD_CD=11680&DEAL_YMD=202605'"
```
- 실증: 키 본문은 **평문**, `=` 만 `%3D` 로 인코딩된다 → `urllib.parse.unquote()` 한 번이면 원문 복원(확인함).
- 유출 지점 ⓐ `verify_region_codes.probe:82` → `classify:91` → **`config/region_code_verification.yaml` 의 `verdict:` 로 파일 저장**.
  이 파일은 **커밋 대상 신규 파일**이다. 들어가면 git 이력에 영구히 남고 키 회수는 이력 재작성이 된다.
- 유출 지점 ⓑ `run_ingest.py:116` — `run.failures` 를 그대로 stdout 출력(터미널·CI 로그·스크롤백).
- **관측된 실패모드다.** `run_molit.py:25` 주석이 "Dev 엔드포인트는 이 키로 **403 Forbidden**" 이라고 스스로 적어 놓았다.
  data.go.kr 의 일일 한도 초과·게이트웨이 5xx 도 같은 경로를 탄다.
- 현재 생성본은 `error: 0` 이라 **실유출은 없다**(확인함: `grep -c 'serviceKey|%3D|Authorization' → 0`). 지금 닫으면 이력 오염 없이 끝난다.

**통과조건**: fetch 계층에서 URL 을 마스킹해 예외를 감싸 올린다(`_common.safe_dsn` 과 같은 원리로 `serviceKey=***`).
진입점마다 `configure_logging` 을 부르는 방식과 달리 **부르는 사람이 잊을 수 없는 자리**다. 회귀 테스트 1건:
키가 든 `HTTPStatusError` 를 주입하고 산출 YAML·stdout·`run.failures` 어디에도 키 조각이 없음을 단언.

**부수 — `LOG-1`(low, 비차단)**: `configure_logging` 을 부르는 스크립트는 `run_ingest.py`·`verify_recommendation.py` **2개뿐**이다.
네트워크를 쓰는 `verify_region_codes.py`(94코드×3개월=282회 호출)·`geocode_complexes.py`·`fetch_legal_dong_codes.py` 는 안 부른다.
지금은 무해하다 — 그 import 사슬에 `basicConfig` 가 없어 root 가 WARNING 이라 httpx INFO 가 애초에 안 나온다(실측 확인).
그러나 **방어가 "우연히 아무도 basicConfig 를 안 불렀다" 에 걸려 있다.** `import app.worker` 한 줄이면 다시 샌다.
SEC-1 을 fetch 계층에서 고치면 이 항목도 함께 닫힌다.

---

### ★4. `SEC-2` (medium · **차단**) — 운영 DB 에서 통하는 계정 비밀번호가 커밋 대상 스크립트에 하드코딩

`backend/scripts/verify_recommendation.py:50`
```python
TEST_PASSWORD = "<평문 비밀번호 리터럴 — SR17-2 조치 시 삭제·리뷰로그에서도 제거>"   # 검증 전용 계정
```
> 원문에는 실제 값이 적혀 있었으나, 이 문서 자체가 **공개 저장소 커밋 대상**이라
> 리뷰로그에 남기는 것만으로도 같은 유출이다. SR17-2 조치와 함께 지웠다.
- `ensure_user()` 가 이 비밀번호로 **운영 DB 에 실제 사용자를 만든다.** 서버 실측: `app_user` 의 **유일한 행**이
  `verify+recommend@example.invalid`(2026-07-25 13:56 생성)이고 `user_profile` 1건이 붙어 있다.
- 스크립트 자신이 "삭제는 사람이 판단한다" 고 적어 두어 **계정이 남는다.**
- 현재 API 컨테이너가 안 떠 있어(`docker ps` 에 `realestate-db-1` 만 존재) **외부 노출은 없다**. 즉 지금은 잠재 위험이다.
  그러나 커밋되면 자격증명이 git 이력에 영구히 박히고, G5 배포 순간 유효해진다.

**통과조건**: `secrets.token_urlsafe()` 로 실행마다 생성하거나 `VERIFY_PASSWORD` 환경변수를 필수화(`_common.require` 재사용).
이미 만들어진 계정은 비밀번호 교체 또는 삭제.

---

### 4. F4 창 분리 — 방향은 옳다. 그러나 **회귀 그물이 실제 변경을 지키지 못한다**

**① 통계적 타당성 — 조건부 타당 (PASS, 단서 있음)**
"동별 배율은 **같은 창의** 단지 전체 중위 대비 상대값이라 드리프트가 상쇄된다" 는 논리는 **분자·분모가 같은 표본 창을 쓰는 한 맞다.**
코드도 그렇게 되어 있다(`stats.py:133` overall_ppm 과 `:139` 동별 ppm 이 동일한 `elig` 에서 나온다).
가장 걱정했던 경로 — **밴드(6개월) 중위값 × 동 배율(24개월)** 로 금액을 환산하는 혼용 — 은 **일어나지 않는다**:
`orchestrator.py:200`·`_dong_valuation_dict:244` 모두 `vs_complex_pct`(상대 %)로만 노출하고 금액으로 바꾸지 않는다(CR-003 의 "금액 환산 금지" 유지).
따라서 창 분리가 **잘못된 금액을 만들지는 않는다.**

남는 단서(`F4-3`, low): 상쇄는 **각 동의 거래가 창 안에서 비슷하게 분포한다**는 가정 위에 선다.
A동 거래가 24개월 전에, B동 거래가 최근에 몰리면 배율에 **시점 효과가 섞인다**(2년간 20% 오른 장이면 최대 ~10%p 왜곡).
현재 시점 보정(분기 지수 나눗셈 등)은 없다. `period_months`·`coverage_pct` 는 응답에 노출되므로 은폐는 아니다.
→ 권고: `DongStat` 에 동별 **거래 중위 시점**을 함께 실어 사용자가 시점 쏠림을 볼 수 있게.

**② 호출부 2곳 — 둘 다 변경됨 (PASS)**
`orchestrator.py:176`(`valuation_finding`)·`:461`(`run_mvp_pipeline`) 모두 `months=` 인자를 제거해 자체 창을 쓴다. grep 상 잔존 0건.

**③ ★회귀 테스트가 회귀를 잡는가 — 변이로 확인 (`F4-1`, medium · 비차단)**

가드를 부러뜨려 봤다.

| 변이 | 내용 | 전체 회귀 결과 | 판정 |
|---|---|---|:--:|
| M1 | **호출부 2곳을 예전처럼 `months=band.period_months` 로 되돌림** | **430 passed · 0 failed** | ❌ **못 잡는다** |
| M2 | `dong_effect` 기본값을 `None`(창 없음)으로 | **430 passed · 0 failed** | ❌ 못 잡는다 |
| M3 | `DONG_PERIOD_MONTHS = 6` | 1 failed | ✅ 잡는다 |
| M3 | `= 12` / `= 18` | 각각 1 failed | ✅ 잡는다 |
| M3 | `= 36` / `= 999` | 0 failed | (창을 넓히는 변경이라 무해 — 허용 가능) |

즉 `test_동실측은_밴드기간이_아니라_자체창을_쓴다` 는 **`dong_effect` 의 기본 인자만** 못박는다.
**이번에 PM 이 실제로 한 변경(호출부에서 `months=` 를 뗀 것)은 통째로 되돌려도 테스트가 전부 초록이다.**
CR-019 에서 칭찬한 "가드를 빼서 깨지는 것까지 확인" 기준을 이 항목은 통과하지 못한다.
→ 통과조건: `valuation_finding`/`run_mvp_pipeline` 을 **호출해서** 검증하는 테스트 1건 —
밴드가 6개월에서 멈추고 동 정보가 과거에만 있는 후보를 넣어 `dong_valuation.available is True` 를 단언.
(호출부를 되돌리면 반드시 깨지도록.)

**④ `F4-2` (low, 비차단) — 검증 스크립트가 아직 옛 방식으로 잰다**
`verify_recommendation.py:132-134` 는 여전히 `months = band.period_months if band.available else 36` 을 계산해
`dong_effect(..., months=months)` 로 넘긴다. **이번 수정이 없애려던 바로 그 결합**이다.
결과적으로 F4 실측 검증 스크립트가 **운영 경로와 다른 창**으로 측정한다 — "8/8" 같은 수치를 다시 뽑아도 운영을 대표하지 않는다.
→ `months=` 를 빼서 운영과 같은 경로로 재게.

---

### 5. PM 수정 2건 — **둘 다 타당 (PASS)**. 하나는 실 DB 로 직접 재현

**① `postgis.py` `CAST(:area_m2 AS numeric) IS NOT NULL` — 실 DB 재현 확인**
운영 PostgreSQL 에 직접 걸었다:
```
PREPARE bad  AS SELECT 1 WHERE $1 IS NOT NULL;                 → ERROR: could not determine data type of parameter $1  (42P08)
PREPARE good AS SELECT 1 WHERE CAST($1 AS numeric) IS NOT NULL; → PREPARE
```
`area_m2` 가 NULL 로 오면 타입 추론에 쓸 다른 문맥이 없어 준비 단계에서 터진다 —
**추천 저장이 통째로 크래시**한다는 진단과 수정 모두 정확하다. 인메모리 리포지토리로 재현 안 되는 경로라는 설명도 맞다.
(부수, 무해: `ut.area_m2 = CAST(:area_m2 AS numeric)` 만으로도 NULL 이면 행이 안 나오므로 추가된 절은 논리적으로 잉여다.
 다만 의도를 드러내고 타입을 확정하는 값이 있어 그대로 두어도 좋다.)

**② `test_postgis_repo.py` raw 커서 — 근거 확인, 실행 재현은 못 함(정직 기재)**
`migrations/006_trade_apt_dong.sql:28` 의 `COMMENT ... '운영 MOLIT API 가 77~93% 제공...'` 에 **`%` 가 문자열 리터럴로 들어 있음**을 확인했다.
SQLAlchemy `exec_driver_sql` 은 빈 파라미터 시퀀스를 DBAPI 로 넘기므로 psycopg3 가 클라이언트측 `%` 자리표시자 변환을 수행하게 되고,
그 결과 정상 마이그레이션이 깨진다는 설명은 정합적이다. **"운영은 psql 로 적용되므로 테스트도 파라미터 없이 raw 로 실행해야 검증이 운영을 대표한다"**
는 논리가 이 수정의 핵심이며 옳다. 커넥션이 `isolation_level="AUTOCOMMIT"` 이라 raw 커서도 같은 오토커밋을 상속한다(psycopg 속성 레벨).
⚠️ 다만 `needs_db` 50건은 **이번 감사에서 실행하지 못했다**(로컬 스킵, 서버로 테스트 러너를 옮기지 않음).
   위 판정은 SQL 정적 확인 + PostgreSQL 동작 실증에 근거한 것이며, 마이그레이션 실행 재현은 아니다.

---

### 6. region 스크립트 — 구조는 PASS. 다만 **"조용히 비는" 구멍이 두 곳 남았다**

**PASS 항목**
- 폐지 코드 처리: `load_regions.py:104` 가 `폐지` 행을 제외한다(없어진 동에 단지를 매핑하지 않음). 정확.
- 인코딩: CP949→UTF-8-SIG→UTF-8 순 추정 후 **한글이 실제로 보이는지 확인**하고 채택(`_read_lines:79`). ZIP 파일명도 `cp437→cp949` 복원. 정확.
- ZIP 아닌 응답(세션 없이 받으면 오는 alert HTML)을 명시적으로 실패시킴 — "조용히 깨진 데이터" 방지. 좋다.
- 생성 결과: 91건(서울 25 · 인천 11 · 경기 55) · 중복 0 · 수도권 외 코드 0. 검증 94코드 → has_data 82 / parent_of_gu 8 / no_data 4 / error 0.
- **`parent_of_gu` 8건 제외 판단은 타당하다.** 하드코딩이 아니라 **자식 구 합계가 0보다 큰지 데이터로 판정**한다(`classify:96-102`).
  수원 5,339 / 용인 5,150 / 화성 4,825 … 구 코드가 실제로 데이터를 갖고 있음이 근거로 남아 있다. 설계 요구("0건을 조용히 넘기지 않는다")에 부합.

**`REG-1` (medium, 비차단) — 3개월 프로브 판정을 다년 백필의 화이트리스트로 재사용한다**
- `verify_region_codes` 는 **최근 3개월(202604~202606)** 만 찌른다. 그런데 `run_ingest.py` 의 **기본 동작(`--verified`)** 이
  그 결과의 `has_data` 만 수집 대상으로 삼는다 → 91 → **82개로 조용히 좁아진다.**
- 이 스크립트 자신의 docstring 이 "갓 신설된 코드는 **개편 이전 계약분이 옛 코드에 남아** 신설 코드로 0건이 온다" 고 경고해 놓고,
  판정은 **최근 3개월로만** 내린다. 옛 코드(28110·28140·28260)는 `no_data` 로 떨어져 백필에서도 영구 제외된다.
  마찬가지로 `parent_of_gu`(화성 41590 등)는 **구 창설 이전 기간에는 부모 코드에 데이터가 있을 수 있는데** 그 기간을 확인하지 않았다.
  실측 정황: `41597 화성시 동탄구` 는 **2025·2026 만** 존재하고 화성 2024 는 0건이다.
- `run_ingest.py` 는 `[INFO] 시군구 82개` 만 찍고 **무엇이 왜 빠졌는지 말하지 않는다.**
- 통과조건: ① 실행 시작 시 제외된 코드와 사유를 한 줄씩 출력 ② 백필(`--today` 과거)에는 `parent_of_gu`·`no_data` 도 포함하거나,
  해당 기간으로 재검증한 뒤 판정할 것 ③ `no_data` 는 만료(예: 90일) 후 재검증을 강제.

**`REG-2` (medium, 비차단) — 실행 원장은 있는데 **커버리지 원장**이 없다**
운영 DB 실측:

| 시도 | 적재된 시군구 | 기간 | 거래 |
|---|---:|---|---:|
| 서울(11) | 25 (2024는 4) | 2024-01~2026-07 | 95,032 |
| 경기(41) | **2** | 2025~2026 | 24,102 |
| 인천(28) | **0** | — | **0** |

`ingest_log` 6행이 **전부 `status=ok` · `rows_failed=0`** 이다. 각 실행은 "시도한 것"만 정직하게 보고하므로 거짓말은 아니다.
그러나 **"수도권 91 시군구 중 27개만 들어왔고 인천은 통째로 비어 있다"** 를 말해 주는 곳이 시스템 어디에도 없다.
`ingest_report.py` 는 시군구별 상위 15만 찍어 **없는 지역은 화면에 나타나지 않는다** — 빠진 것을 빠졌다고 보여주지 못하는 보고서다.
CHARTER 가 최대 위험으로 꼽은 "조용히 비는 데이터" 가 바로 이 형태다.
→ 통과조건: `ingest_report.py` 에 **(검증된 시군구 × 대상 월) 대비 실제 적재 0건 조합**을 나열하는 쿼리 1개 추가.
  백필이 진행 중인 것과, 빠진 줄 모르는 것은 다르다.

---

### 7. 비밀정보 — 나머지는 PASS
- `_common.safe_dsn()` 이 DSN 비밀번호를 `***` 로 가리고, DB 를 쓰는 3개 스크립트가 전부 이걸 통해 출력한다. 좋다.
- `require()` 가 키 없을 때 "도는 척" 하지 않고 즉시 `SystemExit`. 가짜 성공 금지 원칙 유지.
- `.gitignore` 에 `data/reference/` 추가 — `git check-ignore` 로 실제 무시됨 확인. 2.4MB 배포본 대신 재다운로드 스크립트를 둔 판단 옳음.
- 신규 스크립트·생성 config 하드코딩 스캔: `SEC-2` 외 0건. 생성된 `region_code_verification.yaml` 에 URL·키 흔적 0건.
- `fetch_legal_dong_codes.py` 는 인증이 없어 유출 소재 자체가 없다.

---

### 8. 비차단 관찰 (수집 루프)

| ID | 심각도 | 내용 |
|---|---|---|
| `ING-1` | medium | **`run_ingest.py:119` 가 `partial` 에 종료코드 0 을 준다.** `MolitPaginationError`(총건수 미달)는 partial 로 집계되므로 — **이번 라운드가 존재하는 이유인 바로 그 실패가** cron·CI 에서 성공으로 보인다. 실패를 찾아낸 뒤 종료코드로 숨기는 셈. 권고: partial → 1. |
| `ING-2` | low | 페이지 도중 실패 시 **앞 페이지는 이미 적재됐는데 `rows_ok` 는 0**(probe H: 1000건 sink · rows_ok=0). upsert 가 멱등이라 재실행하면 맞춰지지만, 원장과 실제 DB 가 어긋난 채 남는다. |
| `ING-3` | low | 서버가 `pageNo` 를 무시하면 무한루프는 아니나(probe E) **같은 1000건을 두 번 sink** 한다. 자연키 dedup 이 흡수하지만 탐지는 없다. 또 `rows_per_page` 상한 검증이 없어 서버 캡(1000)보다 큰 값을 넘기면 `totalCount` 가 없는 응답에서 조용히 1페이지로 끝난다(있으면 fail-closed 라 안전). |
| `GEO-2` | low | `geocode_complexes.py` 의 `--after` 기본값이 0 이라 **커서가 실행 내부에서만 작동**한다. docstring 이 경고한 "실패 건만 계속 재시도" 함정은 실행 간에는 그대로다(매 실행이 미확보 417건을 먼저 다시 태운다). `--max` 와 함께 쓰면 새 단지에 영영 도달하지 못할 수 있다. |
| `LOAD-1` | low | `make_db_region_resolver` 가 매핑 실패 시 `region_code = NULL` 로 두는 것은 옳다(추측 금지). 다만 **NULL 인 단지는 추천 쿼리(`region_code LIKE :pat`)에서 통째로 빠진다** — 현재 4건이라 무해하나, 매핑률이 떨어지면 조용히 후보가 준다. `ingest_report` 가 `region_pct` 를 찍는 점은 좋다. 임계 경고 추가 권고. |

---

### 판정

**FAIL.** 차단 3건: `GEO-1`(틀린 좌표가 실데이터에 이미 들어와 있고 구분할 수단이 없다) ·
`SEC-1`(API 키가 예외 메시지로 커밋 대상 파일에 저장되는 경로) · `SEC-2`(운영 DB 자격증명 하드코딩).

이번 라운드의 **핵심 성과인 페이지네이션 수정은 전부 통과**했다. 반례 8종을 던져도 종료조건이 흔들리지 않고,
상한 초과·총건수 미달을 성공으로 처리하지 않으며, rate limiter 를 우회하지 않는다. `postgis` CAST 수정은 실 DB 로 재현해 확인했다.

문제는 **같은 원칙이 지오코딩에는 적용되지 않았다**는 점이다. 수집 루프는 "못 채우면 실패로 남긴다" 를 지켰는데,
지오코딩은 "못 찾으면 비슷한 걸 준다" 를 하고 있고 그 결과를 커버리지 93.6% 라는 성공 지표로 보고한다.
`GEO-1` 은 이 프로젝트가 스스로 최대 리스크로 규정한 **"틀린 근거로 수억 원짜리 매수 결정"** 의 입력에 직접 닿는다.

`F4-1` 은 차단하지 않지만 기록해 둔다 — **이번에 실제로 한 변경을 지키는 테스트가 없다.**
변이 M1(호출부 원복)에서 430개 테스트가 전부 초록이었다. 다음 라운드에 반드시 메울 것.


### 부기 — 동시 진행된 SR-017 과의 대조 (중복 추적 방지)

이 감사와 **병렬로** 수행된 `SR-017`(security-reviewer)이 같은 결함 2건을 독립적으로 찾았다.
서로의 결과를 보지 않고 도달한 것이므로 **교차검증이 성립**한다. 추적 번호는 SR 쪽으로 통일한다.

| 내 번호 | SR-017 번호 | 상태 |
|---|---|---|
| `SEC-1` (예외 메시지로 API 키 유출 → 커밋 대상 yaml 저장) | **`SR17-1`** | 동일 결함 — SR 번호로 통일 |
| `SEC-2` (운영 DB 계정 비밀번호 하드코딩) | **`SR17-2`** | 동일 결함 — SR 번호로 통일 |

`.review-state.json` 의 `code_review.blocking` 도 `["GEO-1", "SR17-1", "SR17-2"]` 로 기록했다.

SR-017 이 추가로 확인한 사실 하나가 **두 건의 심각도를 올린다**: 이 저장소의 origin 이 **공개 저장소**라는 점이다.
내 판정은 "커밋되면 git 이력에 영구히 남는다" 까지였으나, 공개 저장소라면 **커밋 = 즉시 인터넷 공개**다.
→ `SR17-1`·`SR17-2` 는 커밋 전에 반드시 닫아야 하고, MOLIT 키 재발급 판단은 SR-017 의 결론을 따른다.

반대로 SR-017 이 다루지 않은 것이 **`GEO-1`(정확성)** 이다. 이쪽은 보안이 아니라 **데이터가 조용히 틀리는** 문제이며,
코드리뷰 게이트의 독립 차단 사유로 남는다. 세 건이 모두 닫혀야 G1 을 통과한다.

---

## CR-021 · 2026-07-26 · GEO-1 수정 검증 + 부동산원 단지 마스터 + 실거래 기준 후보 (code-reviewer, herdr re-review 대행)

**판정: FAIL** · 차단 **1건(`GEO-3`)** · `GEO-1` 은 **RESOLVED**
지시 `2026-07-26-code-review` · 대상 `git log -1`(5703bca) 이후 working tree 전체(28 tracked + 신규 untracked)

### 재현 · 검증 방법

기준 테스트 **539 passed / 54 skipped** 재현(junit `tests=593 failures=0 errors=0 skipped=54`) — 지시 수치와 일치.
초록불을 믿지 않았다. 이번 감사의 근거는 **(1) 29개 변이 테스트 (2) 운영 DB 직접 SQL 재측정
(3) 실단지 6,538건에 대한 함수 직접 실행** 이다. 변이·측정 후 소스는 **바이트 단위로 원복**했고
(4개 파일 바이트 대조 OK), `git diff --stat` 이 감사 전후 동일함(28 files / 2891 insertions / 235 deletions)을 확인했다.

> 서버는 **조회만** 했다. 동거 실서비스(itsmine-*·autobtc)에 중지·재시작·설정변경·삭제 0회. 운영 DB 쓰기 0회.

---

### A. `GEO-1` 차단 이슈 해소 검증 → **RESOLVED**

#### A① 법정동 교차충돌 0 — **직접 SQL 재측정으로 CONFIRM**

담당자 보고를 믿지 않고 운영 DB 에서 내가 직접 집계했다.

```sql
WITH pts AS (SELECT id, address_jibun, region_code,
                    round(ST_X(geom)::numeric,6) lon, round(ST_Y(geom)::numeric,6) lat
             FROM complex WHERE geom IS NOT NULL),
     grp AS (SELECT lon,lat,count(*) n,count(DISTINCT address_jibun) n_dong,
                    count(DISTINCT region_code) n_region
             FROM pts GROUP BY lon,lat HAVING count(*)>1)
```

| 지표 | CR-020 실측 | 이번 실측 | 판정 |
|---|---:|---:|---|
| 좌표 충돌 단지 | 514 (7.9%) | **199 (3.2%)** | 보고와 일치 |
| 충돌 그룹 | 237 | **93** | — |
| **법정동 교차 충돌** | **68** | **0** | ✅ **핵심 지표 해소** |
| 시군구 교차 충돌 | — | **0** | ✅ |
| 좌표 확보 | 6,121 (93.6%, 오염 포함) | **6,303 / 6,538 = 96.41%** | 산술 확인 |

`geom_source` 내역도 실측: `kakao_keyword/exact` 4,914 · `kakao_address/address` 1,072 · `kakao_keyword/variant` 317.
**GEO-1 의 통과조건 (1)~(5) 는 전부 이행됐다** — 결과검증·권역검증·충돌차단·보수적 변형이 코드에 있고,
`ingest_report.py` 가 `collision_rows`·`collision_pct`·`crossdong_rows` 를 쿼리로 노출하며("0이어야 정상"이라 명시),
회귀 테스트도 `test_다른_법정동_동명단지는_좌표를_공유하지_않는다` 등으로 존재한다.

#### A④ "`same_complex` 는 유사도를 쓰지 않는다" — **실데이터 임계값 스윕으로 CONFIRM**

코드를 읽는 데 그치지 않고 **반증을 시도**했다. 실단지 6,538건을 법정동별로 묶어
모든 쌍(409개 TRUE 쌍)에 대해 `NAME_SIMILARITY` 를 **0.0 → 1.0** 으로 스윕했다.

| `NAME_SIMILARITY` | `same_complex` TRUE 쌍 | 기준선 대비 차이 |
|---:|---:|---:|
| 0.80(기본) | 409 | — |
| 0.0 / 0.5 / 0.99 / 1.0 | 409 / 409 / 409 / 409 | **0 / 0 / 0 / 0** |

임계값을 어떻게 흔들어도 판정이 **한 건도** 바뀌지 않는다. `name_contains` → `_compare(fuzzy=False)` 로
퍼지 분기가 실행되지 않는다는 주장은 **사실**이다.

#### A⑤ 회귀 테스트가 자기충족적인가 — **변이 테스트 17종 → 자기충족 아님**

`test_geocode.py` 44건을 포함한 전체 스위트에 대해 검증 로직을 하나씩 부러뜨렸다.

| 변이 | 결과 | 변이 | 결과 |
|---|---|---|---|
| `verify` 에서 `dong_matches` 제거 | ✅ KILLED (3) | `verify_address` REGION 허용 | ✅ KILLED (1) |
| `verify` 에서 `name_matches` 제거 | ✅ KILLED (2) | `verify_address` `b_code` 제거 | ✅ KILLED (2) |
| `verify` 에서 `region_matches` 제거 | ✅ KILLED (1) | `verify_address` 본번·부번 제거 | ✅ KILLED (1) |
| `verify` 에서 bbox 제거 | ✅ KILLED (1) | `verify_address` 산번지 제거 | ✅ KILLED (1) |
| **괄호 전부 제거(GEO-1 이전 동작)** | ✅ **KILLED (7)** | `SEARCH_SIZE` 5→1(1위 신뢰) | ✅ KILLED (1) |
| 충돌 게이트 OFF | ✅ KILLED (4) | 주소보다 키워드 우선 | ✅ KILLED (4) |
| `same_complex` 항상 True | ✅ KILLED (9) | `NAME_SIMILARITY` 0.80→0.50 | ✅ KILLED (5) |
| `same_complex` 차수 가드 제거 | ✅ KILLED (2) | | |

**16개 유효 변이 중 15개 KILLED.** 생존 1건(`verify_address` 의 "대조 근거 없으면 불합격" 가드 제거)은
상류 불변식(주소가 있으면 부동산원 매칭이 있고 그러면 `legal_dong_code`·`main_no` 가 항상 존재)에
가려진 방어적 가드라 **low**. ※ `query_variants` 의 `append`→`insert(0)` 변이는 빈 리스트라 **등가 변이**(무효)로 제외.

→ CR-020 이 지적한 "신규 테스트 4건은 전부 행복경로"는 해소됐다. **테스트가 실제로 동작을 구속한다.**

#### A③ 유사도 임계값 0.80 의 근거 — **조건부 타당 · 단 적용 지점에 구멍(`GEO-4`)**

문서가 든 근거(`무지개마을4단지` vs `무지개마을청구`=0.67, `우성2` vs `우성5`=0.67)는 재현되고,
0.80 을 0.50 으로 낮추면 테스트가 깨진다(변이 KILLED 5). **임계값 자체는 타당하다.**

문제는 임계값이 아니라 **가드의 비대칭**이다. `name_phases`(차수·단지번호) 가드가
`same_complex`(공유 판정)와 `reb._hit`(매칭)에는 있는데 **`name_matches`(좌표 채택)에는 없다.**
실단지로 측정: 같은 법정동 안에서 `name_matches` 가 **수락**하는 서로 다른 단지 쌍이 1,521건,
그중 퍼지(≥0.80)로만 붙는 것이 1,049건, **그중 차수가 서로 다른 것이 619건**이다.

```
압구정동  신현대12차 ↔ 신현대11차                              0.833   ← 채택 단계에서 통과
압구정동  현대14차(203,204,205,206동) ↔ 현대13차(208~211동)    0.800
논현동    두산위브2단지 ↔ 두산위브1단지                        0.857
```

같은 법정동이라 `dong_matches`·`region_matches` 는 둘 다 통과한다. 현재 이것이 오좌표로 **터지지 않은** 이유는
충돌 게이트가 막아주기 때문인데, 그 게이트는 **소수점 6자리 완전 일치**만 잡는다 —
카카오가 같은 단지의 다른 출입구/부속시설 좌표를 주면 몇 m 어긋난 값이 되어 게이트를 그냥 통과한다.
→ **`GEO-4`(medium, 비차단)**: `name_matches` 에도 `name_phases` 가드를 적용할 것. `same_complex`·`_hit` 와 같은 규칙이면 된다.

---

### ⛔ A② 남은 199건이 "지리적으로 옳은 공유"인가 → **아니다. `GEO-3`(high) 차단**

담당자는 "총 충돌 514 → 199(**전부 같은 법정동 내 동일단지라 허용**)"이라고 보고했다.
이 주장을 **이번 라운드가 새로 들여온 부동산원 마스터로 대조**한 결과 **반증된다.**

```sql
-- 같은 점을 쓰는데 reb_complex_id 가 서로 다른 그룹
grp AS (... HAVING count(*)>1 AND count(DISTINCT reb_complex_id) >= 2)
→ 그룹 15개 / 단지 30건
```

부동산원은 **필지고유번호(PNU)가 다르고 세대수도 다른, 명백히 별개의 단지**라고 말하는데
좌표는 **완전히 같은 한 점**이다. 즉 각 쌍에서 **최소 하나는 틀린 좌표**다.

| complex | 부동산원 주소 | 세대수 | 공유 좌표 |
|---|---|---:|---|
| #7 `대우디오빌` | 강남구 **역삼동 720-25** | 457 | 127.031112, 37.497585 |
| #74 `대우디오빌플러스` | 강남구 **역삼동 824-25** | 168 | *(동일)* |
| #2603 `장안현대홈타운(336)` | 동대문구 **장안동 336** | 2,182 | 127.074496, 37.570023 |
| #2641 `장안현대` | 동대문구 **장안동 95-1** | 456 | *(동일)* |
| #5685 `명수대현대` | 동작구 **흑석동 10** | 660 | 126.966917, 37.507865 |
| #5732 `명수대` | 동작구 **흑석동 97-2** | 51 | *(동일)* |
| #4681 `우장산롯데캐슬` | 강서구 **화곡동 1145** | 1,164 | 126.848040, 37.555187 |
| #4713 `우장산롯데` | 강서구 **화곡동 1148** | 206 | *(동일)* |

(그 외 `신금호두산위브`/`신금호`, `서초한신리빙타워`/`서초한신`, `라이프`/`라이프미성`,
`정릉스카이쌍용아파트`/`스카이아파트`, `강서뉴타워`/`강서뉴`, `노원센트럴푸르지오`/`센트럴` 등 15그룹)

#### 근본 원인 — `same_reb_complex` 를 **긍정 신호로만** 쓰고 부정 신호로 안 쓴다

`app/ingest/geocode.py:665-683`

```python
def same_complex(a, b):
    if same_reb_complex(a, b):
        return True          # reb_id 가 같으면 확정 — 여기까지는 옳다
    if a.legal_dong != b.legal_dong: return False
    if _phases(a.name) != _phases(b.name): return False
    return name_contains(a.name, b.name)   # ← reb_id 가 서로 "다를" 때 이 줄로 떨어진다
```

`reb_id` 가 **양쪽 다 있고 서로 다르면 그 시점에 다른 단지가 확정**인데, 그 사실을 버리고
이름 포함 관계로 내려간다. `대우디오빌` ⊂ `대우디오빌플러스` 라서 통과한다.

**3줄로 재현(운영 DB 실제 행):**

```python
a = GeoTarget(name="대우디오빌",       legal_dong="역삼동", reb_id="11680100001439")
b = GeoTarget(name="대우디오빌플러스", legal_dong="역삼동", reb_id="11680100448473")
same_reb_complex(a, b)  # False — 부동산원은 다른 단지라고 말한다
same_complex(a, b)      # True  ← 결함: 좌표 공유를 허용한다
```

`개포자이`/`개포자이르네`, `롯데캐슬`/`롯데캐슬리베`, `삼호빌라A동`/`삼호빌라씨동` 도 동일하게 True.

#### 기존 테스트가 이 결함을 못 잡는 이유 (자기충족 사례 1건)

`tests/test_geocode.py:535 test_부동산원_번호가_다르면_공유하지_않는다` 는 통과하지만
**엉뚱한 이유로 통과한다** — 이름을 `청운현대` vs `다른단지` 로 잡아서 `reb_id` 검사가 아니라
`name_contains` 가 거부한다. `reb_id` 분기는 한 번도 실행되지 않는다.
A⑤ 에서 테스트 품질이 전반적으로 우수하다고 판정했으나, **이 한 건만은 자기충족적**이다.

#### 왜 차단인가

- 좌표는 지도(F1)·입지분석(F5)·동별 폴백(F4)의 입력이다. `역삼동 720-25` 와 `824-25`,
  `장안동 336` 과 `95-1` 은 수백 m 떨어져 있고, GEO-1 이 "수백 m 어긋나면 역세권·학군 판정이 뒤집힌다"고
  차단 사유로 삼았던 바로 그 크기다.
- 모듈 docstring 이 **"틀린 좌표는 좌표 없음보다 나쁘다"** 를 두 번 적어 놓았고, 코드가 30건에서 그것을 어긴다.
  CR-020 이 GEO-1 을 차단한 논리와 **완전히 같다**(규모만 514 → 30 으로 줄었다).
- **판정에 필요한 근거가 이미 DB 에 있다.** 새 데이터도 새 API 호출도 필요 없고 수정은 3줄이다.
- 잠재 노출은 30건이 아니다: `same_complex` 가 부동산원과 **모순되는 쌍이 98쌍**이며,
  미확보 235건과 재실행에서 계속 실현된다.
- 원장에 "199건 전부 정상"이 검증된 사실로 남으면, GEO-1 이 반려당한 이유("성과 지표가 결함을 덮는다")가 반복된다.

#### `GEO-3` 통과 조건

1. `same_complex` 에 **부정 신호** 추가 — 양쪽에 `reb_id` 가 있고 서로 다르면 즉시 `False`
   (이름 대조로 내려가지 않는다). 부동산원 매칭은 "후보 2개 이상이면 아무것도 안 쓴다"는
   엄격 규칙을 통과한 것이므로 이름보다 신뢰도가 높다.
2. **회귀 테스트** — `reb_id` 가 다르면서 이름이 서로를 품는 쌍(`대우디오빌`/`대우디오빌플러스`)으로
   `rejected_collision` 을 단언. 기존 `test_부동산원_번호가_다르면_공유하지_않는다` 는
   이름이 달라서 통과하므로 **이 케이스로 교체하거나 추가**할 것.
3. **이미 들어간 30건 정리** — 수정 후 해당 좌표를 무효화(`geom=NULL`)해 주소 경로로 재확보하거나,
   최소한 `geom_confidence` 를 강등해 하류가 구분할 수 있게 한다. 지금은 `exact` 로 저장돼 있어
   "확인된 좌표"와 구분되지 않는다.
4. `ingest_report.py` 에 **"같은 점 · 서로 다른 `reb_complex_id`"** 건수 쿼리 추가
   (`crossdong_rows` 와 같은 자리에서 0 이어야 정상).

---

### B. 신규 — 부동산원 단지 마스터 + 주소 기반 지오코딩

실측 대조: `complex` 6,538 · `reb_complex` **33,003** · `reb_building` **72,584**
(보고된 72,590 과 **6행 차이** — 오차는 무시할 수준이나 원장 수치는 실측으로 정정할 것) ·
매칭 5,666(=보고와 일치, `5,666+546+326=6,538` 정합).
매칭 방법 내역 실측: `name_exact` **5,644** · `name_contains` 18 · `name_fuzzy` **4**
→ 가장 느슨한 퍼지(0.88) 경로는 4건뿐이라 **폭발 반경이 작다.**

#### B① "애매하면 매칭 안 함"이 강제되나 — **변이 6종으로 CONFIRM**

| 변이 | 결과 |
|---|---|
| `ambiguous` → 첫 후보를 그냥 채택 | ✅ KILLED (3) |
| `ambiguous` → 더 느슨한 단계로 진행 | ✅ KILLED (3) |
| `_hit` 차수 가드 제거(`신현대11차`==`12차`) | ✅ KILLED (1) |
| `REB_NAME_SIMILARITY` 0.88 → 0.50 | ✅ KILLED (1) |
| `parse_pnu` 길이 검증 제거(추측 허용) | ✅ KILLED (5) |
| `dong_label` 판독 실패 시 라벨 날조 | ✅ KILLED (5) |

`match_complex` 는 한 단계에서 서로 다른 `reb_id` 가 2개 이상이면 **그 자리에서 종료**하고
더 느슨한 단계로 내려가지 않는다. `assert REB_NAME_SIMILARITY >= NAME_SIMILARITY` 로
"매칭 기준이 좌표 채택 기준보다 느슨해질 수 없다"를 **모듈 로드 시점에** 강제하는 것도 좋다.

**역방향 반례 탐색**(한 `reb_id` 를 우리 단지 2개 이상이 주장): 실측 **3건뿐**(2개씩).
MOLIT 이름 오염으로 갈라진 정상 케이스이며 설계 의도와 일치. → **B① PASS.**

#### B② 주소 경로가 GEO-1 검증을 우회하나 — **우회 없음 (PASS)**

`VerifiedGeocoder.locate` 는 주소를 먼저 보지만 `verify_address` 를 **반드시** 통과해야 하고,
그 뒤 `enrich_geom` 의 **좌표 충돌 게이트를 키워드 경로와 똑같이** 탄다(변이 "주소경로도 충돌차단" KILLED).
검증 항목이 이름 경로보다 오히려 많다(bbox + `address_type` REGION 거부 + `b_code` 10자리 + 본번 + 부번 + 산번지).
문자열 동명이 아니라 **코드 대조**라 더 단단하다. 위 변이표대로 5개 검증 각각을 떼면 전부 테스트가 깨진다.

#### B③ 96.41% 가 틀린 좌표로 부풀려졌나 — **총량은 정확, 단 30건은 오염(= `GEO-3`)**

6,303 / 6,538 = **96.41%** 산술 확인. 총량 자체를 부풀린 흔적은 없다.
다만 그 안에 A② 의 30건이 섞여 있고, 아래 B⑤ 의 2건은 담당자 스스로 "틀려 보인다"고 판단한 좌표다.

#### B④ 교차검증(250건 표본, 중앙값 2m·p90 49m)이 신뢰할 만한가 — **설계는 타당, 표본 대표성은 제한적**

**설계는 진짜 교차검증이다.** 이름 경로 좌표와 부동산원 **주소** 경로 좌표를 대조하는데,
두 경로는 입력(단지명 vs 지번주소)도 알고리즘도 다르다. 둘이 2m 안에서 만나면 우연이 아니다.

그러나 `verify_reb_matching.py:55-57` 의 표본 정의에 **구조적 구멍**이 있다.

```sql
AND c.geom_source = 'kakao_keyword'
AND c.geom_confidence = 'exact'      -- ← variant 317건을 통째로 제외
```

| 모집단 | 건수 | 교차검증 대상 |
|---|---:|---|
| 좌표 확보 전체 | 6,303 | — |
| 교차검증 **가능** 모집단 | **4,422** | 표본 250 = **5.7%** |
| `variant` 좌표(군더더기 제거 질의) | **317** | ❌ **구조적으로 제외** |
| 부동산원 미매칭 키워드 좌표 | **661** | ❌ 제외 |

`variant` 는 **GEO-1 이 지목한 가장 위험한 부류**(한 단계 덜 확실)인데 검증에서 정확히 그 부류가 빠진다.
결과적으로 확보 좌표의 **29.8%(1,881건)** 는 한 번도 대조되지 않았다.
또 `verify_address` 불합격 건은 거리 통계에서 제외된다(건수는 출력하므로 은폐는 아니다).
→ **`GEO-5`(low, 비차단)**: `geom_confidence` 필터를 풀고 `exact`/`variant` 를 **나눠서** 보고할 것.
"2m/49m"은 *검증된 부분집합에 대해* 참이며, 전체 좌표 품질의 증거로 확대 해석하면 안 된다.

#### B⑤ 미해결로 남긴 2건 — **덮지 않은 판단은 옳다. 그러나 라벨이 사실과 어긋난다**

| # | 단지 | 부동산원 주소 | 이름경로와의 거리 | 현재 `geom_confidence` |
|---|---|---|---:|---|
| 723 | `가락동 씨티빌` | 송파구 가락동 11-3 | 1,114m | **`exact`** |
| 593 | `양재동 삼익양재빌라` | 서초구 양재동 91 | 543m | **`exact`** |

- **덮지 않은 것은 옳다.** 어느 쪽이 맞는지 모르는 상태에서 임의로 주소 좌표를 밀어 넣으면
  "추측하지 않는다" 원칙을 깬다. 사람이 확인할 목록에 올린 것도 스크립트 설계대로다.
- **그러나 현재 상태가 판단과 모순된다.** 담당자는 "기존 이름경로 좌표가 **틀린 것으로 보인다**"고
  결론지었는데, 그 좌표는 최고 신뢰 라벨인 **`exact`** 로 저장돼 있고 아무 표식이 없다.
  모듈 원칙("틀린 좌표는 좌표 없음보다 나쁘다")대로라면 **`geom=NULL` 또는 신뢰도 강등**이 정답이다.
  1,114m 는 역세권·학군 판정을 확실히 뒤집는 거리다.
- 표본 250건 중 2건(0.8%)이 400m 초과였다는 사실도 그대로 남는다 — 4,422 모집단에 단순 외삽하면
  **약 35건**이며, 검증되지 않은 `variant` 317건은 여기에 포함되지도 않았다.
- → **`GEO-3` 통과조건 (3) 에 함께 처리**할 것(신뢰도 강등 또는 무효화).

---

### C. 실거래 기준 후보(G4 충족) — **PASS**

#### C① 실거래 중위가가 호가로 둔갑하는 경로가 하나라도 있나 — **없다 (변이 4종 KILLED)**

이번 라운드의 핵심 G2 질문이라 **파생 속성부터 DB 저장까지 전 구간**을 반례 탐색했다.

| 변이(둔갑을 인위적으로 만듦) | 결과 |
|---|---|
| `ask_price_krw` 가 호가 없을 때 값을 반환하도록 | ✅ KILLED (7) |
| `price_basis` 를 항상 `listing` 으로 | ✅ KILLED (7) |
| `price_estimated` 를 항상 `False` 로 | ✅ KILLED (1) |
| `if not listings: continue` 복원(G4 회귀) | ✅ KILLED (5) |

구조적으로도 막혀 있다 — `ask_price_krw`·`price_basis`·`target_floor` 가 **`group` 하나에서 파생**되므로
호출부가 어긋나게 조합할 여지가 없다(`group is None` ⟺ `ask_price_krw is None` ⟺ `price_basis=="trade"`).
`ask_gap_pct` 는 `ask_price_krw is not None` 일 때만 계산하고, `listing_finding` 은 `group is None` 이면
"정상 매물"이 아니라 **판단 보류**를 낸다. `valuation_finding` 은 갭 대신 밴드 자체를 근거로 제시한다.
**실거래 중위를 호가 자리에 넣어 0% 갭을 만드는 경로는 없다.**

#### C② `total_score=null`(모름) vs `0`(나쁨) — **파이프라인은 일관 · DB 폴백 경로에 표기 손실(`REC-1`, low)**

`scored` 가 비면 `None`(변이 `None`→`0.0` KILLED), 정렬은 `is not None` 을 1순위 키로 써서
"모름"이 "나쁨"보다 뒤로 가되 0점과 섞이지 않는다. `score_basis: None` 과 `notes` 고지도 붙는다.

다만 `postgis.py:165 _item_to_dict` 의 **payload 없는 폴백 경로**는 `est_price_krw` 만 돌려주고
`price_basis`·`price_estimated`·`ask_price_krw` 를 **싣지 않는다** — 이 응답만 보면
실거래 추정가와 호가를 구분할 수 없다. 현재는 무해하다(실측: `recommendation_item` 0행,
`save_job_result` 가 항상 payload 를 쓴다). 정규화 컬럼에 `price_basis` 가 없다는 점만 남는다.
→ **`REC-1`(low)**: `recommendation_item.price_basis` 컬럼 추가 또는 폴백 dict 에 최소한 `price_estimated` 포함.

#### C③ 예산 필터를 `WHERE` 가 아니라 `ORDER BY` 로 둔 판단 — **옳다 (운영 DB 실측)**

`WHERE` 로 자르면 사용자가 "왜 후보에 없는지"를 못 본다(ux/README.md §4, CR-006 C4 와 일관).
`ORDER BY` 로 두면 예산 초과 단지도 `LIMIT` 안에 남아 파이프라인이 **사유와 함께** 떨어뜨린다.
효과를 운영 DB 에서 **읽기전용으로 재측정**(예산 13억, 지역 무제한, 상위 50):

| 정렬 | ≥5건 거래 단지 | 최근 거래 합 | **예산내 거래 합** |
|---|---:|---:|---:|
| 기존 `active_listings DESC, id` | 42 / 50 | 2,847 | **450** |
| 신규 `… affordable DESC, recent DESC, id` | **50 / 50** | 8,461 | **8,094** |

예산 내 근거가 **18배** 늘었다. 판단은 옳고 효과도 실측된다.

> 다만 **원인 설명 한 줄은 실데이터와 다르다.** 지시문의 "`ORDER BY … c.id` 라서 `LIMIT 50` 이
> **거래 0건 단지로 채워졌다**"는 재현되지 않는다 — 기존 정렬에서도 50개 중 **42개**가 거래 5건 이상이었다.
> 실제 병목은 (a) `if not listings: continue`(호가 0이라 전멸)와 (b) 예산 미반영 정렬(450/8,094)이었다.
> 코드 주석("송파 136 후보 중 117 예산초과")은 정확하다. 원장 문구만 정정 권고(`REC-2`, info).

#### C④ 호가가 생기면 listing 경로로 복귀하나 — **PASS**

`_assemble_candidates` 가 `if listings:` 로 분기해 호가가 있으면 `group_duplicates` 그룹 단위 후보를 만들고
`continue` 로 실거래 경로를 타지 않는다. 변이 C-M2 가 KILLED 로 이 분기를 지킨다.
현재 운영 DB `listing` **0행**이라 G4(공공API 만으로 성립) 요구가 **실데이터로 입증**된다.

---

### D. F4 창 분리 회귀 테스트(PM 작성) — **절반만 유효 (`F4-1` 부분 해소 · medium 유지)**

PM 의 주장("호출부를 `months=band.period_months` 로 되돌리면 실패")을 **변이로 재확인**했다.

| 변이 | 결과 |
|---|---|
| **M1**: 호출부 **2곳 모두** 원복 (`valuation_finding` + `run_mvp_pipeline`) | ✅ **KILLED (1 failed)** |
| **M1b**: `run_mvp_pipeline` 호출부(`orchestrator.py:594`) **만** 원복 | ⛔ **SURVIVED (0 failed)** |

- 신규 `test_밴드가_6개월이어도_동실측은_살아있다` 는 `valuation_finding` 을 **직접 호출**하므로
  그 호출부(`orchestrator.py:251`)는 확실히 보호된다. CR-020 이 지적한 "기본 인자만 못박는다"는 해소됐다.
- 그러나 **`run_mvp_pipeline` 안의 두 번째 호출부(`:594`)는 여전히 무방비**다.
  이 호출부가 만드는 값이 사용자에게 나가는 `dong_valuation` 필드 그 자체다.
- CR-020 `F4-1` 의 통과조건은 "`valuation_finding` **/ `run_mvp_pipeline`** 을 실제로 호출해 검증하는 테스트"였다.
  **앞의 절반만 이행됐다.** "변이 테스트로 확인했다"는 보고는 M1(둘 다 원복)에 대해서만 참이다.
- 비차단으로 유지한다(정확성 결함이 아니라 그물의 구멍이며, 실제 호출부는 올바르다).
  → 통과조건: `run_mvp_pipeline` 을 호출해 `items[0]["dong_valuation"]["available"] is True` 를 단언하는 테스트 1건
  (밴드가 6개월에 멈추고 동 정보가 과거에만 있는 후보 — 위 M1b 로 반드시 깨지는지 확인할 것).

---

### 그 외 확인 사항

- **`F4-2` 해소 확인**: `verify_recommendation.py` 에서 `months=band.period_months` 전달이 사라졌다.
- **`SR17-1`/`SR17-2` 코드측 수정 확인**(판정은 SR 소관): `app/core/masking.py` 신설
  (`mask_secrets`·`mask_url`·`masked_error`·`secret_safe`), `_httpx_get` 이 **fetch 계층에서** 예외를 마스킹해 다시 던진다
  — CR-020 이 권고한 "부르는 사람이 잊을 수 없는 자리"와 일치. `TEST_PASSWORD` 리터럴은 제거되고
  `VERIFY_TEST_PASSWORD` 환경변수 또는 1회용 난수로 대체. `tests/test_script_hygiene.py` 7건이
  비밀 리터럴·공통 진입점·마스킹 설치를 회귀로 고정한다. **구조가 옳은 방향이다.**
- **마이그레이션 007/008**: `IF NOT EXISTS` 로 멱등, `COMMENT ON` 으로 컬럼 의미를 DB 에 남김,
  `reb_complex_dong_idx (legal_dong_code, kind)` 가 매칭 쿼리 접근 경로와 일치. 부분 인덱스도 적절.
- **테스트 총평**: 이번 감사에서 돌린 **29개 변이 중 27개 KILLED**(등가변이 1 제외, 생존 1은 low).
  CR-020 이 "행복경로만 본다"고 반려한 지점이 실질적으로 개선됐다. `needs_db` 54건은 이번에도 미실행(로컬 스킵).

---

### 판정

**FAIL — 차단 1건(`GEO-3`).**

이번 라운드의 작업량과 품질은 높다. `GEO-1` 의 핵심 지표인 **법정동 교차충돌 68 → 0** 은
내가 직접 SQL 로 재측정해 확인했고, 확보율 96.41% 도 산술이 맞으며, 부동산원 매칭의
"애매하면 안 쓴다"와 실거래 후보의 "호가로 둔갑 금지"는 **변이 테스트로 실제 강제됨을 확인**했다.
`GEO-1` 은 **RESOLVED** 로 닫는다.

차단 사유는 하나다. 담당자가 스스로 검증을 요청한 명제 —
**"남은 199건은 전부 지리적으로 옳은 공유"** — 가 **이번 라운드가 새로 들여온 부동산원 마스터에 의해
반증**된다(15그룹 / 30단지). `same_complex` 가 `reb_complex_id` 를 긍정 신호로만 쓰고
**부정 신호로는 쓰지 않아** 생긴 3줄짜리 구멍이며, 판정에 필요한 데이터는 **이미 DB 안에 있다.**

GEO-1 을 차단했던 논리를 그대로 적용하면 이것도 차단이다 — 규모가 514 에서 30 으로 줄었을 뿐
성격이 같고(조용히 틀린 좌표), 하류(F1·F4·F5)가 같고, 고치는 비용은 훨씬 싸다.
여기서 통과시키면 "199건 전부 정상"이 검증된 사실로 원장에 남는데, 그것은 GEO-1 을 반려한 이유
("성과 지표가 결함을 덮는다")를 그대로 반복하는 일이다.

**비차단 이월**: `GEO-4`(medium, `name_matches` 차수 가드) · `F4-1`(medium, 파이프라인 호출부 미보호) ·
`GEO-5`(low, 교차검증 표본이 `variant` 제외) · `REC-1`(low, 정규화 컬럼에 `price_basis` 없음) ·
`REC-2`(info, 원장 원인 문구 정정) · `reb_building` 72,590 → **72,584** 수치 정정.



---

## CR-022 · 2026-07-26 · GEO-3 차단 해소 재검증 + GEO-4/GEO-5/F4-1 처리 (code-reviewer, herdr re-review 대행)

**판정: PASS** · 차단 **0건** · `GEO-3`·`GEO-4`·`F4-1` **RESOLVED** · `GEO-5` **CLOSED(측정 완료)**
지시 `2026-07-26-code-review-2` · CR-021 FAIL 후속

### 재현

기준 테스트 **558 passed / 54 skipped**(junit `tests=612 failures=0 errors=0 skipped=54`) — 지시 수치와 일치.
CR-021 대비 +19건. 감사 전후 md5 대조로 소스 무변경 확인(3파일). 서버는 **조회만**(운영 DB 쓰기 0회,
동거 실서비스 itsmine-*·autobtc 무접촉).

> 담당자 주장은 **하나도 그대로 받지 않았다.** 변이는 내가 다시 만들어 돌렸고, 수치는 내 SQL 로 다시 쟀다.

---

### 1. GEO-3 / GEO-4 수정이 진짜인가 — **변이로 직접 재현, 전부 KILLED**

내가 만든 변이 8종을 원본에 적용해 돌렸다.

| # | 변이 | 결과 |
|---|---|---|
| GEO3-M1 | `same_complex` 의 `different_reb_complex` 2줄 **삭제**(CR-021 차단 지점 원복) | ✅ **KILLED (9 failed)** |
| GEO3-M2 | `different_reb_complex` 를 항상 `False` 로(no-op 화) | ✅ KILLED (9) |
| GEO3-M3 | **한쪽만** 있어도 '다르다'로 판정(과잉 차단 방향) | ✅ KILLED (2) |
| GEO4-M1 | `name_matches` 의 차수 가드 **삭제** | ✅ **KILLED (5 failed)** |
| GEO4-M2 | 차수 비교를 `place_core` 대신 원문 `place_name` 으로 | ⚠️ SURVIVED (사실상 등가 — 아래) |
| REG | `unsafe_shared_ids` 제거(DB 재판정 헬퍼) | ✅ KILLED (1) |
| F4-M1a | `valuation_finding:251` 호출부만 원복 | ✅ KILLED (1) |
| F4-M1b | **`run_mvp_pipeline:594` 호출부만 원복** (CR-021 에서 SURVIVED 했던 그것) | ✅ **KILLED (1)** |

- **GEO3-M3 가 KILLED 인 점이 중요하다.** 부정 증거를 넣으면 반대 방향으로 과하게 막는 실수를 하기 쉬운데
  ("한쪽만 번호가 있어도 다른 단지"), 테스트가 그것도 잡는다. `different_reb_complex` 는
  "한쪽이라도 비면 **모른다**이지 **다르다**가 아니다"를 지킨다 — 미매칭 단지끼리 이름으로 붙던
  정상 경로를 막지 않는다. 양방향이 다 고정돼 있다.
- **GEO4-M2 는 실질적 등가 변이다.** `name_phases` 는 내부에서 `name_key`→`strip_name_noise` 를 거치므로
  `place_core` 와의 차이는 **부속시설 꼬리에 차수 토큰이 들어 있을 때**뿐이다('…아파트 2단지상가').
  실데이터에서 이 형태를 찾지 못했다. 테스트 구멍이 아니라 관측 불가능한 차이로 판단한다.
- 변이 후 **md5 바이트 대조로 원복 확인**: `geocode.py c041b2c9…` · `orchestrator.py e63dbb22…` ·
  `test_script_hygiene.py d9bb4f82…` (변이 전과 동일).

#### 운영 DB 재측정 — 내 SQL 로 다시 셌다

| 지표 | CR-021 | 이번 실측 | 보고값 | 판정 |
|---|---:|---:|---:|---|
| **reb 모순 충돌 그룹** | 15 | **0** | 0 | ✅ |
| **`same_complex` ↔ REB 모순 쌍** | 98 | **0** | 0 | ✅ |
| 총 충돌 단지 | 199 | **169** (78그룹) | 169 | ✅ |
| 법정동 교차 / 시군구 교차 | 0 / 0 | **0 / 0** | 0 | ✅ |
| 좌표 확보 | 6,303 (96.41%) | **6,303 (96.41%)** | 불변 | ✅ |
| `geom_source` | kw 5,191 / addr 1,112 | kw-exact 4,881 · kw-variant 310 · **addr 1,112** | — | 주소경로 +40 |
| 백업 테이블 | — | `backup.complex_geom_geo3` **40행** | 40 | ✅ |

`same_complex` TRUE 쌍은 **409 → 311**(정확히 모순 98쌍만 제거). 반드시 공유돼야 하는
**같은 `reb_id` 쌍 3건은 3건 모두 TRUE 유지** — 정상 경로 무손상. 수술이 정확하다.

**GEO-4**: 같은 법정동에서 `name_matches` 가 수락하는 **차수 상이 쌍 619 → 0**
(내 CR-021 측정 기준. 담당자의 685 는 집계 방식 차이). 같은 차수 쌍은 계속 수락된다(836쌍).

#### 내가 지목한 오좌표가 실제로 틀렸음이 확인됐다

| # | 단지 | 현재 좌표 | 옛 공유점(127.031112, 37.497585)과의 거리 | 현재 출처 |
|---|---|---|---:|---|
| 7 | 대우디오빌 | 127.042689, 37.501456 | **1,110m** | `kakao_address` |
| 74 | 대우디오빌플러스 | 127.031110, 37.497583 | **0m** | `kakao_address` |
| 593 | 삼익양재빌라 | 127.040753, 37.478553 | (재확보) | `kakao_address` |
| 723 | 씨티빌 | 127.126214, 37.501864 | (재확보) | `kakao_address` |

CR-021 은 "각 쌍에서 최소 하나는 틀렸다"까지만 말할 수 있었는데, **#7 이 1.1km 어긋나 있었고
그 점의 진짜 주인은 #74 였음**이 사후에 확정됐다. 내가 B⑤ 로 남긴 2건도 무효화 후 주소로 재확보됐다.
넷 다 이제 `kakao_address`(법정동코드·본번·부번 대조를 통과한 가장 강한 증거 등급)다.

#### 회귀 테스트가 제대로 들어왔다

`test_운영DB_모순쌍들이_전부_다른_단지로_판정된다` 가 **운영 DB 실사례 5쌍**(장안현대홈타운/장안현대,
명수대현대/명수대, 우장산롯데캐슬/우장산롯데, 서초한신리빙타워/서초한신, 신금호두산위브/신금호)을
실제 `reb_id` 와 함께 파라미터로 돌린다 — 전부 이름 포함관계라 이름 대조로는 못 막는 케이스다.
CR-021 이 "자기충족적"이라 지적한 옛 테스트(이름이 달라서 통과하던 것)가 **제대로 교체**됐다.
`unsafe_shared_ids` 도 #7/#74 실제 좌표로 "그룹 전체를 지목"과 "정당한 공유는 불건드림"을 양쪽 다 고정한다.

→ **GEO-3 · GEO-4 RESOLVED.**

---

### 2. 남은 169건에 대한 "전부 옳다고 주장하지 않는다" — **적절하다. 다만 한 걸음 더 갈 수 있다**

담당자의 3분류를 내 SQL 로 재현했다: **전원 매칭 0그룹 / 일부 매칭 7그룹 / 전원 미매칭 71그룹** — 정확히 일치.

**이 태도는 적절하다.** GEO-3 이 반증한 것은 "199건 전부 옳다"는 *주장*이었지 충돌의 존재 자체가 아니었다.
지금은 근거가 있는 것(0그룹)과 없는 것(71그룹)을 갈라 놓고, 없는 쪽에 대해 **아무 주장도 하지 않는다.**
근거 강도를 사실대로 보고하는 것이 G2 원칙이며, "형태만 바꾼 반복"이 아니다.
전원 매칭 그룹이 **0** 이라는 것도 중요하다 — 부동산원이 판정할 수 있는 충돌은 하나도 남지 않았다.

다만 **"주장하지 않는다"가 "조사할 수 없다"는 뜻은 아니다.** 미매칭 그룹에도 근거가 하나 남아 있다:
MOLIT 이름 괄호 안의 **지번**이다. `_strip_parens` 는 괄호 안이 숫자면 군더더기로 보고 통째로 떼는데,
그 숫자가 **본번까지 다르면 다른 필지**다. 내가 169건을 전수 훑어 셌다:

```
본번이 서로 다른데 좌표를 공유하는 그룹: 16 / 단지 37  (전부 reb 미매칭 0/N)
  본번[342, 957, 1076]  화곡동 근상프리즘(957-1) || (342-35) || 근상프리즘 || (1076-2)
  본번[4, 10, 1617]     서초동 상지리츠빌(1617-13) || (4) || (10)
  본번[402, 403]        응암동 뉴월드(403-32) || (402-42) || (402-120)
  본번[479, 597]        방화동 통일101동(597-38) || 통일(479-3)
  본번[798, 999]        방배동 월드빌라트(798-5) || (999)
```

반대로 `삼환나띠르빌(1002-10)~(1002-22)`·`새롬(1164-12)~(1164-14)` 는 **본번이 같고 부번만 다르다** —
같은 필지군의 한 단지이므로 공유가 맞다. 즉 **본번은 갈라야 할 것과 붙여야 할 것을 실제로 구분한다.**

⚠️ 단, 바로 규칙화하면 안 된다. `동궁리치웰문정(101)/(102)` 처럼 괄호 안 숫자가 **지번이 아니라 동 번호**인
경우가 섞여 있어(`_PAREN_DONGS` 가 맨숫자도 동으로 받는다), 무조건 본번으로 가르면 정상 공유를 깬다.
→ **`GEO-6`(low, 비차단)**: 부동산원 주소를 아는 이웃 단지와 대조하거나 자릿수·범위 휴리스틱으로
지번/동번호를 먼저 가른 뒤 적용할 것. 16그룹 37단지가 조사 대상이고, 전부 같은 법정동 안이라 오차는 유계다.

---

### 3. 전수 스윕(약 4,530 호출) — **판정: 지금이 아니라 후속. 단 G5 배포 전 필수로 못 박는다**

**지금 하지 않아도 되는 이유**
- 이건 **코드 결함이 아니라 잔존 데이터 문제**다. 채택 경로는 이제 fail-closed 로 고쳐졌고(GEO-3/4 변이로 확인),
  새로 들어오는 좌표는 이 문제를 만들지 않는다. 커밋 게이트가 막아야 할 것은 코드이지 과거 데이터가 아니다.
- 좌표는 **아직 아무에게도 안 보인다** — 미배포이고, `listing` 0행, `recommendation_item` 0행,
  프론트에 추천 렌더링 경로가 없다. 사용자 노출 위험이 현재 0 이다.
- 담당자의 자제가 **기술적으로 옳다**: `name_contains`/`name_fuzzy` 매칭(22건)에서는 주소 쪽이 틀렸을 수
  있어 일괄 NULL 이 오히려 오류를 심는다. 결정 규칙 없이 90건을 건드리는 것이 더 위험하다.
- 4,530 호출은 rate limit 0.25s 기준 **20~25분**이고 카카오 개인 쿼터(10만/일) 안이다 —
  급히 처리해야 할 만큼 비싸지도, 미루면 못 하게 될 만큼 어렵지도 않다.

**그래도 반드시 해야 하는 이유 — 그래서 `GEO-7` 로 등재한다**
- 표본 8/319·7/320 ≈ **2.2%**, 모집단 4,530 외삽 시 **약 90건**이 400m 초과로 어긋난다.
  1km 급 오차가 실재함은 #7 이 이미 증명했다(1,110m).
- 그 90건이 지금 **`geom_confidence='exact'`** 로 저장돼 "확인된 좌표"와 구분되지 않는다 —
  CR-021 B⑤ 에서 지적한 것과 **같은 문제**이며, 그때 2건은 고쳤지만 나머지는 미측정이다.
- 좌표는 F1(지도)·F5(입지)·F4(동별 폴백)의 입력이라 배포 시점에는 반드시 정리돼 있어야 한다.

**스윕 설계 권고(결정 규칙을 먼저 정하고 돌릴 것)**
1. `reb_match_method='name_exact'`(5,644건 = 매칭의 99.6%)만 1차 대상. 매칭이 거의 확실하므로
   400m 초과 시 **이름 경로 좌표를 의심**하는 추론이 성립한다.
2. `name_contains`/`name_fuzzy`(22건)는 자동 판정하지 않고 사람 확인 목록으로만.
3. 불일치 건은 **주소 좌표로 덮지 말고** 무효화 후 주소 경로로 재확보(GEO-3 정리와 같은 절차 —
   `verify_address` 를 통과해야만 들어간다).
4. `exact`/`variant` 를 나눠 보고(GEO-5 에서 이미 그렇게 바뀜).

---

### 4. GEO-5 처리 — **CLOSED. 측정이 내 지적을 뒷받침한다**

CR-021 은 "`geom_confidence='exact'` 필터가 가장 위험한 부류(variant)를 표본에서 제외한다"고 지적했다.
variant 를 포함해 재실행한 결과가 **그 우려를 수치로 확인**한다.

| 등급 | p90 | 400m 이내 |
|---|---:|---:|
| `exact` | 43~49m | 98.4~98.8% |
| `variant` | **184~185m** | **92.2~95.3%** |

variant 는 실제로 4배 나쁘다. 리포트가 둘을 합쳐 보고하지 않게 바뀐 것도 확인했다.
"평균 2m"로 묻히던 신호가 드러난다 — 이게 GEO-5 를 남긴 목적이었다. **CLOSED.**

---

### 5. F4-1 — **RESOLVED**

CR-021 이 "M1b(`run_mvp_pipeline:594` 만 원복)는 SURVIVED"라고 지목한 그 구멍이 닫혔다.
**두 호출부를 각각 따로 변이시켜** 확인했다:

- `orchestrator.py:251`(`valuation_finding`) 원복 → **1 failed** (기존 테스트가 잡는다)
- `orchestrator.py:594`(`run_mvp_pipeline`) 원복 → **1 failed** (신규 `test_파이프라인도_밴드기간이_아니라_자체창을_쓴다` 가 잡는다)

두 호출부가 **독립적으로** 보호된다. CR-020 `F4-1` 통과조건이 이제 완전히 충족됐다.

---

### 6. `test_script_hygiene.py` 가 자기충족적인가 — **아니다. 단 예외 규칙에 구멍 1개(`SEC-3`, low)**

문서·설정 검사기에 **진짜 유출을 심어** 잡히는지 봤다(12 케이스 · 검사기 함수를 직접 호출).

> ⚠️ 심은 값 자체는 여기 적지 않는다 — 이 원장은 커밋 대상이라 그럴듯한 난수를 적으면 그 자체가 검사기에 걸린다(아래 ※ 참조). 형태만 적는다.

| 심은 것(형태) | 결과 |
|---|---|
| `password = "<20자 영숫자 난수>"` | ✅ 잡힘 |
| **`TEST_PASSWORD=<20자 난수>`**(PM 이 고쳤다는 접두사 구멍) | ✅ **잡힘 — 수정이 진짜다** |
| `serviceKey=<난수>` · `MOLIT_API_KEY: <난수>` · `refresh_token="<JWT 형태>"` · yaml `db_password: <난수>` | ✅ 전부 잡힘 |
| `password="***"` · `api_key="your-key-here"` · `os.environ[...]` · `PASSWORD_ENV="VERIFY_TEST_PASSWORD"` | ✅ 전부 통과(오탐 없음) |

※ **이 검사기가 내 CR-022 초안을 실제로 반려했다.** 처음엔 위 표에 그럴듯한 난수문자열을 그대로 적었는데, 원장을 붙이고 테스트를 돌리자 `test_docs_and_config_do_not_contain_secret_values` 가 **3줄을 집어 실패**했다(`code-review-log.md:2082-2084`). 검사기가 살아 있고 리뷰 원장까지 실제로 덮는다는 가장 강한 증거다 — 감사자의 글조차 걸러냈다. 표기를 형태로 바꿔 해소했다.

**자기충족적이지 않다.** 특정 값이 아니라 형태를 보므로 새로 생길 비밀도 잡고, 유출값을 저장소에
남기지 않는다 — SR18-3 의 지적(값을 조각내 적어두고 그 조각을 찾던 검사기가 자기 자신을 면제)이
제대로 해소됐다. AST 검사기도 심은 리터럴 2종을 잡고 이름 상수 2종은 통과시킨다.

**남은 구멍(`SEC-3`, low)** — `_SYNTHETIC` 이 값 **전체에 대해 `search()`** 라, 값 안에 아무데나
`test`·`secret`·`example`·`fake`·`dummy` 가 **부분 문자열로** 들어 있으면 통째로 면제된다:

```
password = "Str0ngTestPassw0rd99"   → 면제됨(진짜 비밀인데 통과)
password = "MySecretRealValue123"   → 면제됨
```

사람이 짓는 비밀번호에 `Test`·`Secret` 이 섞이는 건 흔하다. 실제 사고(SR17-2)가 사람이 지은
비밀번호였다는 점에서 현실적인 회피 경로다. → 권고: `_SYNTHETIC` 을 **값 전체 일치**(`fullmatch`)로
좁히거나, 마커가 값의 대부분을 차지할 때만 면제. 지금은 1차 방어(AST + 런타임 생성)가 유효하고
이건 심층 방어의 그물이라 **low·비차단**이다.

---

### 판정

**PASS.** CR-021 의 차단 사유가 해소됐고, 해소되었다는 사실을 **담당자 보고가 아니라 내 변이 8종과
내 SQL 재측정으로** 확인했다. 특히:

- `same_complex` 의 2줄을 지우면 **9건이 깨진다** — 수정이 장식이 아니라 배선돼 있다.
- reb 모순 그룹 **15 → 0**, 모순 쌍 **98 → 0**, 정상 공유 3쌍 **무손상**, 확보율 **96.41% 불변**.
- 내가 지목했던 #7 대우디오빌은 **실제로 1.1km 틀린 좌표**였고, 옛 공유점의 주인은 #74 였다 —
  CR-021 의 차단이 이론이 아니라 실제 오좌표를 잡아낸 것으로 확정됐다.
- CR-021 이 SURVIVED 로 남긴 **F4 M1b 가 이제 KILLED** 다.
- GEO-5 재측정은 내 지적(variant 가 더 위험)을 **수치로 입증**했다(p90 43m vs 184m).

남은 169건에 대해 **"전부 옳다고 주장하지 않는다"** 는 태도는 적절하다. 근거 있는 것과 없는 것을
갈라 보고하고 없는 쪽에 주장을 얹지 않는 것이 정확히 G2 다. 다만 미매칭 그룹에도 아직 쓰지 않은
근거(괄호 안 본번)가 남아 있어 `GEO-6` 로 넘긴다.

**비차단 이월**: `GEO-6`(low, 본번 상이 공유 16그룹/37단지) · `GEO-7`(medium, **G5 배포 전 필수** —
전수 스윕으로 약 90건 추정 오차 정리) · `SEC-3`(low, `_SYNTHETIC` 부분일치 면제) ·
`GEO-4` 부수 관찰(low): 이름에 차수 토큰이 있는 단지 846건은 카카오가 차수를 생략한 이름을 주면
이제 채택되지 않는다 — 방향은 옳으나(미확보 > 오좌표) 재수집 시 확보율이 소폭 떨어질 수 있다.
현재 미확보는 19건뿐이라 실측 영향은 없다.

---

## CR-023 · 2026-07-26 · 배포(G5) 직전 최종 코드리뷰 (code-reviewer, herdr re-review 대행)

**판정: PASS** · 차단 **0건** · **배포 가능(deploy_ready)** · `GEO-6`·`GEO-7`·`SR18-7` **RESOLVED**
지시 `2026-07-26-code-review-3` · 대상 `49f602a` 이후 미커밋 변경 9 modified + 2 신규

### 재현

| 항목 | 결과 |
|---|---|
| `backend pytest` | **607 passed / 54 skipped** (junit `tests=661 failures=0 errors=0`) |
| `frontend typecheck` | ✅ `tsc --noEmit` 오류 0 |
| `frontend test` | **62 passed** (4 files) |
| `frontend build` | ✅ `built in 637ms` · js 162.84kB(gzip 53.73) |

지시 수치와 전부 일치. 감사에 쓴 변이 **24종**을 돌린 뒤 **바이트 단위 원복**을 확인했다
(`geocode.py`·`nginx-realestate.conf`·`geocode_complexes.py`·`mapMarkers.ts` 4파일).
서버는 **조회만** 했고 `/etc/nginx` 는 **읽기 전용**으로만 다뤘다(수정·reload 0회, 아래 §5 참조).

---

### 1. CR18-7 마커 성능 — **PASS**

#### 수치 정정이 맞는가 — **맞다(독립 실측)**

담당자의 "리뷰어의 '요소 500개'는 마커 수 기준이고 마커 1개=2요소라 실측은 1000" 주장을
말로 받지 않고, **`document.createElement`·`addEventListener` 를 계수하는 테스트를 직접 짜서** 쟀다.

| 측정 | 결과 |
|---|---|
| 마커 500개 최초 생성 | 요소 **1,000** · `addEventListener` **1,000** · 오버레이 **500** |
| **같은 목록 재조회** | 요소 **0** · 리스너 **0** · 오버레이 **0** |
| 400개 겹치고 400개 신규 | 요소 **800**(신규분만) · 리스너 **800** |

마커 1개 = `div` 1 + `span` 1 = **2요소**, 리스너 2개(`click`+`keydown`)가 맞다.
순위 배지가 붙으면 span 이 하나 늘어 3요소가 된다. 모듈 docstring(L148)의
"요소 1,000개 + addEventListener 1,000회 + 오버레이 500개"도 내부 정합적이다.
→ **정정이 정확하다.** 재조회 시 생성 0 은 "19.2→0.79ms"의 기전을 그대로 설명한다.

#### 변이 10종 — 9 KILLED

| 변이 | 결과 | 변이 | 결과 |
|---|---|---|---|
| `t.cb.activate` 갱신 제거(옛 콜백 호출) | ✅ KILLED (1) | **좌표 순서 뒤집기(CR18-5)** | ✅ **KILLED (4)** |
| 재사용 안 하고 매번 생성(CR18-7 원복) | ✅ KILLED (8) | **panTo 가드 제거(CR18-1)** | ✅ **KILLED (1)** |
| **사라진 마커 미정리(CR18-6)** | ✅ **KILLED (5)** | **`patchLabelEl` 을 innerHTML 로(XSS)** | ✅ **KILLED (1)** |
| 중복 키 방어 제거 | ✅ KILLED (1) | `className` 미반영 | ✅ KILLED (1) |
| 군집 좌표 미반영 | ✅ KILLED (1) | `detach` 에서 `keydown` 만 미제거 | ⚠️ SURVIVED |

**회귀 금지 4종이 전부 변이로 지켜짐을 확인했다** — CR18-1·CR18-5·CR18-6·XSS.
특히 XSS: 재사용 경로(`patchLabelEl`)까지 `textContent` 전용이고, 자식 제거도
`el.textContent = ""` 로 한다(`innerHTML` 0건). 재사용 최적화가 XSS 우회로가 되지 않았다.

유일한 생존은 `detach` 의 `keydown` 제거를 빼도 안 깨지는 것이다(`click` 쪽은 잡힌다).
오버레이가 `setMap(null)` 로 떨어지면 요소가 GC 대상이라 실피해는 없으나,
CR18-6 의 취지("리스너를 명시적으로 뗀다")가 절반만 고정돼 있다 → **`MARK-1`(low, 비차단)**.

#### 설계 관찰(비차단)
- `patch()` 가 `yAnchor`/`xAnchor` 를 반영하지 않는다. 현재는 단지 1.35·군집 0.5 로 **키별 상수**라
  무해하지만, 누가 선택 상태에 따라 앵커를 바꾸면 조용히 무시된다. `MarkerSpec` 에 필드가 있는데
  `patch` 에만 없어서 눈에 띄지 않는다 → `MARK-2`(low).
- `setZIndex?.()`·`setPosition?.()` 가 옵셔널 호출인데 **호출 성공과 무관하게** `t.zIndex`/`t.point` 를
  갱신한다. 메서드가 없는 SDK 라면 "반영했다고 기록만" 남아 이후 갱신이 건너뛰어진다.
  실제 카카오 `CustomOverlay` 는 둘 다 제공하므로 운영 영향 없음 → `MARK-3`(info).

---

### 2. GEO-7 좌표 재검증 — **PASS (세 질문 전부 확인)**

#### ① 69건이 실제로 임계 초과분만인가 — **그렇다**

`sweep_verdict` 는 `verify_address` 를 통과한 **첫 후보**에 대해서만 거리를 재고
`distance > tolerance_m` 일 때만 `mismatch` 다. 나머지는 `agree`/`unverified`/`no_result` 로
갈라 **손대지 않는다**. 이 규칙을 변이로 부러뜨려 확인했다.

| 변이 | 결과 |
|---|---|
| 임계값 무시하고 전부 `mismatch` | ✅ KILLED (2) |
| 임계값 400 → 5000(아무것도 안 걸림) | ✅ KILLED (3) |
| 주소 후보 0건인데 `agree` 로 판정 | ✅ KILLED (2) |

69 = **적용 65(`name_exact`) + 미적용 4(`name_contains`/`name_fuzzy`)** 로 나뉘고,
운영 DB 의 `backup.complex_geom_geo7` 이 정확히 **65행**이다.

#### ② 재확보가 검증 파이프라인을 우회하지 않나 — **우회하지 않는다**

좌표의 출처가 `sweep_verdict` 안의 **`verify_address` 통과분뿐**이다(법정동코드·본번·부번·
산번지·수도권 bbox 전부 대조). 그 뒤 `apply_fixes` → `ReplayGeocoder` → **`enrich_geom`** 으로
들어가 **충돌 게이트·`same_complex` 공유 판정을 평소와 똑같이** 탄다. 변이로 확인:

| 변이 | 결과 |
|---|---|
| sweep 이 `verify_address` 를 건너뜀 | ✅ KILLED (1) |
| `ReplayGeocoder` 가 없는 좌표를 지어냄 | ✅ KILLED (1) |
| `APPLIABLE_METHODS` 를 fuzzy 까지 넓힘 | ✅ KILLED (1) |

절차도 견고하다 — 백업·무효화가 **한 트랜잭션**이고, 점유표(`load_occupied`)를 **비운 뒤에**
다시 실어 방금 비운 점이 자기 자신을 막지 않게 했다. 대상도 판정 시점이 아니라 **반영 시점에
DB 에서 다시 읽는다**. `--methods` 는 스윕 범위만 넓힐 뿐 **반영 범위는 상수가 막는다** —
CLI 옵션으로 확대 불가.

#### ③ 확보율 유지가 진짜인가 — **직접 SQL 로 확인**

| 지표 | CR-022 | 이번 실측 | 판정 |
|---|---:|---:|---|
| `geom IS NOT NULL` | 6,303 | **6,303** | ✅ 불변 |
| 확보율 | 96.41% | **96.41%** (6,303/6,538) | ✅ |
| `geom_source='kakao_address'` | 1,112 | **1,177** (+65) | ✅ 정확히 재확보분 |
| `geom_source='kakao_keyword'` | 5,191 | **5,126** (−65) | ✅ |
| 충돌 / 법정동 교차 / 부동산원 모순 | 169 / 0 / 0 | **169 / 0 / 0** | ✅ 유지 |
| 백업 | — | `pre_geo7` **6,303행** · `geo7` **65행** | ✅ 되돌릴 수 있다 |

65건이 이름 경로에서 주소 경로로 **정확히 이동**했고 총량은 그대로다. 교차오염 0 도 재확인.
`--out` JSONL 에 판정이 한 줄씩 쌓여 중단 내성이 있고, `--from-file --apply` 가 같은 질문을
두 번 보내지 않는 설계도 카카오 쿼터 관점에서 옳다.

---

### 3. GEO-6 — **규칙 PASS. 데이터 정리를 미룬 판단도 옳다(배포 차단 아님)**

#### 규칙이 정상 공유를 깨지 않나 — **깨지 않는다. 그리고 내 CR-022 제안이 틀렸다**

CR-022 에서 나는 "본번이 다르면 다른 단지"를 제안했다. **그 제안이 실데이터로 반증됐다** —
`뉴월드(402-42)` 와 `뉴월드(402-120)` 은 **본번이 같은데도 다른 단지**다. 담당자는 본번이 아니라
**표기 전체(본번-부번)** 로 비교하도록 정했고, 부번 0 표기 흔들림(`(666)`/`(666-0)`)까지 정규화했다.
내 지적보다 정확하다.

부동산원 마스터를 직접 조회해 근거를 확인했다 — 이 모듈이 오랫동안 "한 단지"라고 적어둔
삼환나띠르빌은 **부동산원 기준 7개 단지**다:

```
11650100249289 삼환나띠르빌(1002-7)  15세대     11650100050187 삼환나띠르빌(1002-10) 16세대
11650100003082 삼환나띠르빌(1002-8)  30세대     11650100050188 삼환나띠르빌(1002-11) 16세대
11650100050186 삼환나띠르빌(1002-9)  19세대     11650100249290 삼환나띠르빌(1002-21) 15세대
                                              11650100249291 삼환나띠르빌(1002-22) 15세대
```

세대수가 전부 다르다 — 한 단지일 수 없다. **주석·테스트가 사실과 달랐다는 정정은 옳다.**

정상 공유를 깨지 않는 근거도 코드와 변이 양쪽에서 확인했다:
- `different_parcel` 은 **양쪽 다** 괄호 지번이 있을 때만 '다르다'로 본다.
  `롯데캐슬` vs `롯데캐슬(1057-1)` 은 갈리지 않는다(모르는 건 모른다).
- `_PAREN_JIBUN` 이 `^\d+(-\d+)?$` 라 `(101동)`·`(10,11,25동)` 같은 **동 목록은 보지 않는다.**

| 변이 | 결과 |
|---|---|
| `same_complex` 의 `different_parcel` 분기 삭제 | ✅ KILLED (8) |
| **본번만 비교(= 내 CR-022 제안)** | ✅ **KILLED (3)** — 반례가 테스트로 박혀 있다 |
| 한쪽만 있어도 '다르다'(과잉 차단) | ✅ KILLED (2) |
| 괄호 안 '동' 표기까지 지번으로 오인 | ✅ KILLED (3) |

#### 데이터 정리를 미룬 판단 — **옳다. 지우는 것보다 고치는 것이 낫고, 그게 가능하다**

새 규칙으로 현재 DB 를 재판정해 내가 직접 셌다: **29그룹 / 70행**(담당자 보고와 일치).
전부 부동산원 **미매칭**이라 코드가 판정할 근거가 없던 부류다.

담당자의 "괄호 포함 원문으로 매칭을 붙이면 지우는 대신 고칠 수 있다"는 주장은
**전제가 참임을 내가 확인했다**:

- 부동산원에는 `삼환나띠르빌(1002-7)` … `(1002-22)` 가 **문자 그대로** 들어 있다(위 조회).
- 우리 쪽 6행은 **전부 미매칭**이다. 이유가 명확하다 — `_strip_parens` 가 괄호를 떼어
  6행이 모두 `삼환나띠르빌` 로 축약되고, 같은 법정동의 부동산원 후보 7개도 똑같이 축약돼
  **후보 7개 = ambiguous → 매칭 포기**가 된다(`match_complex` 의 올바른 안전동작).
- 즉 **괄호를 보존해 매칭하면 1:1 로 붙고**, 그러면 각자의 지번주소로 **정확한 좌표를 따로**
  받을 수 있다. 지금 비우면 −1.11%(70/6,303)를 잃고 **되찾을 수 있었던 좌표를 버리는** 셈이다.

배포 차단이 아닌 근거를 실측으로 보강한다:

| 근거 | 실측 |
|---|---|
| 코드는 이미 옳다 | 새 좌표는 이 문제를 만들지 않는다(변이 4종 KILLED) |
| 오차가 유계다 | 70행 전부 **같은 법정동 안**. 법정동 교차 0 · 부동산원 모순 0 |
| **좌표를 쓰는 입지 분석이 아직 없다** | `school_district`·`poi`·`road_segment`·`transit_plan`·`redevelopment`·`market_index` **전부 0행** → `location_finding` 은 항상 '판단 보류'. 좌표는 현재 **지도 핀**과 F4 폴백에만 쓰인다 |
| 노출 규모 | 70행 중 최근 36개월 거래 **5건 이상은 23건** (후보로 뜰 수 있는 상한) |
| 되돌릴 수 있다 | `backup.complex_geom_*` 4종에 이력 보존 |

→ **`geo6_cleanup = later`.** 다만 "언젠가"가 아니라 **`GEO-8`(medium)** 로 등재해
"괄호 보존 매칭 → 재확보"를 정식 과제로 남긴다. 지금 비우는 선택지는 **택하지 말 것**.

---

### 4. SR18-7 속도 제한기 공유 — **PASS**

`build_geocoder()` 가 `RateLimiter` 를 **하나만** 만들어 키워드·주소 백엔드에 같이 넘긴다.
`address_only` 면 키워드 백엔드를 아예 `NullPlaceSearch` 로 두어 쿼터를 낭비하지 않는다.
변이로 확인: **주소 백엔드에 별도 limiter 를 만들면 → KILLED (1)**.
`rate_limiter`·`backends` 프로퍼티를 연 것도 "배선을 밖에서 검증 가능하게" 만든 옳은 선택이다.
가짜 시계로 고정해 실제 대기 없이 회귀를 잡는다.

---

### 5. SR15-4 배포 절차의 정확성 — **PASS (내가 서버에서 결합 검증했다)**

#### 버전 비호환이 더 없는가 — **없다. 그리고 격리 검증만으로는 부족했다**

서버 실측: **nginx/1.18.0 (Ubuntu)** · `--with-http_v2_module` 컴파일됨 · **OpenSSL 3.0.2**.
`listen 443 ssl http2;` 는 1.18 문법으로 정확하고 `http2 on;` 은 1.25.1+ 라는 진단도 맞다.
전 디렉티브를 1.18 기준으로 훑었다 — `map`·`limit_req_zone`·`add_header ... always`(1.7.5+)·
`try_files`·중첩 `location`·`proxy_intercept_errors`·`ssl_prefer_server_ciphers off` 모두 1.18 지원.
`ssl_protocols TLSv1.3` 도 OpenSSL 3.0.2 라 유효하다. **추가 비호환 0건.**

⚠️ 그런데 **담당자의 "격리 인스턴스 검증"으로는 못 잡는 위험이 하나 있었다.** 1.18 에서 `http2` 는
**소켓 단위 옵션**이라, 같은 `address:port` 에 옵션이 다른 `listen` 이 이미 있으면
`duplicate listen options` 로 nginx 가 **통째로 뜨지 않는다** — 그러면 동거 실서비스까지 죽는다.
실제로 이 서버에는 **`listen 443 ssl;`(http2 없음) 서버블록이 4개** 이미 있다
(`data`·`data.bak-visitlog`·`itsmine`·`stack`).

그래서 `/etc/nginx` 를 **전혀 건드리지 않고** `/tmp` 격리 prefix 에 활성 vhost **전부 + conf.d** 를
복사해 우리 설정과 **함께** `nginx -t` 를 돌렸다(포트 바인딩·reload 없음, 로그 경로도 격리):

```
### 함께 올린 vhost: data / data.bak-visitlog / default / itsmine / stack / zz-realestate
nginx: [warn] duplicate MIME type "text/html" in .../stack.utilverse.info:25      ← 기존 경고
nginx: [warn] conflicting server name "data.utilverse.info" on 0.0.0.0:443, ignored ← 기존(.bak 중복)
nginx: the configuration file ... syntax is ok
nginx: configuration file ... test is successful
```

**결합 상태에서 통과한다.** 경고 2건은 우리 것이 아니라 **기존 설정의 선재 문제**다
(`.bak-visitlog` 가 `sites-enabled` 에 남아 같은 server_name 이 중복 — 우리와 무관하나
운영 위생 차원에서 정리 권고). 검증 후 임시 디렉터리를 삭제했고 `/etc/nginx` 수정 0 ·
`systemctl is-active nginx` = **active** 를 확인했다.

부수 확인 — 우리가 **유일한 `[::]:443` 리스너**가 되므로 IPv6 기본서버 선점 우려가 있었으나,
서버에 **글로벌 IPv6 주소가 없고**(`ip -6 addr scope global` 없음) 도메인에도 실제 AAAA 가 없다
(`getent` 결과는 IPv4 매핑). **실질 영향 없음.**

#### `map $host $re_csp` — 값이 갈라질 수 없는 구조인가 — **그렇다. 테스트가 고정한다**

정의는 `map` 한 곳뿐이고 3개 블록(`server`·정적자산·`/index.html`)이 전부 `$re_csp` 를 참조한다.
`test_csp_값은_한_곳에서만_정의된다` 가 **`default-src` 등장 횟수 == 1** 과
**참조가 `["$re_csp"]*3`** 을 단언한다 — 누가 값을 직접 적으면 즉시 깨진다.
변이 확인: **`/index.html` 블록에서 CSP 를 빼면 → KILLED (2)**.
`add_header` 미상속(DEP-1) 대응도 3블록에 5종을 모두 재기재하고 정적 테스트가 막는다.

CSP 값 자체도 빌드 산출물과 대조했다:
- `MapView.tsx` 가 `https://dapi.kakao.com/v2/maps/sdk.js?...&libraries=clusterer` 로 로더를 붙인다 → `script-src` 일치.
- `dist` 산출물의 **`data:` URI 0건** → `img-src` 에 `data:` 를 뺀 판단이 실제 산출물과 맞다.
- `dist` 가 참조하는 외부 오리진은 `dapi.kakao.com` 뿐.
- `t1/mts/s1.daumcdn.net` 은 SDK 가 런타임에 부르는 것이라 정적으로는 확인 불가 —
  그래서 **Report-Only 선행**(DEPLOY.md §5-5(4)/(5))이 절차에 있는 것이 옳다. `'unsafe-eval'` 위반 1건이
  정상이라는 사전 고지까지 있어, 운영자가 놀라서 CSP 를 무력화하는 실수를 예방한다.

#### 비차단 발견 — `DEP-3`(low)

**`http2` 버전 회귀가 테스트로 고정돼 있지 않다.** `listen 443 ssl http2;` 를 `http2 on;` 으로
되돌리는 변이가 **SURVIVED** 했다. 배포를 통째로 막았을 바로 그 결함인데 그물이 없다.
`test_deploy_config.py` 는 CSP·헤더·중괄호는 촘촘히 보지만 리슨 문법은 보지 않는다.
→ `http2 on;` 부재 + `listen ... ssl http2` 형태를 단언하는 테스트 1건 권고(서버 1.18 근거 주석과 함께).

---

### 판정

**PASS · 배포 가능.**

배포 직전 게이트라 "돌아간다"가 아니라 **"틀렸을 때 티가 나는가"**를 기준으로 봤고,
이번 변경은 그 기준을 통과한다. 이번 감사에서 돌린 **변이 24종 중 21 KILLED**이며,
생존 3건은 전부 low/info(리스너 정리 절반·nginx 문법 회귀·앵커 미반영)로 **현재 동작에 결함이 없다.**

특히 좋았던 것:
- **담당자가 내 CR-022 지적(본번 비교)을 실데이터로 반증하고 더 정확한 규칙으로 바꿨다.**
  리뷰어 말을 그대로 따르지 않고 데이터로 확인한 것이 옳다. 반례를 테스트로 박아 둔 것도 맞다.
- **GEO-7 재확보가 검증을 우회하지 않는다** — 좌표 출처가 `verify_address` 통과분뿐이고
  충돌 게이트까지 다시 탄다. 확보율 96.41% 불변이 직접 SQL 로 확인된다.
- **`http2` 비호환을 배포 전에 잡았다.** 못 잡았으면 `nginx -t` 실패로 절차가 멈췄을 것이다.
  다만 격리 검증만으로는 부족했고, 내가 동거 vhost 4개와 **결합**해 재검증해 통과를 확인했다.

`GEO-6` 데이터 정리를 미룬 판단도 **옳다** — 부동산원에 괄호 이름이 그대로 있어
**지우는 대신 고칠 수 있음**을 내가 직접 조회로 확인했고, 지금 비우면 되찾을 수 있는 좌표
70개를 영구히 잃는다. 게다가 좌표를 소비하는 입지 데이터가 **아직 한 행도 없다.**

**배포 후 과제(비차단)**: `GEO-8`(medium — 괄호 보존 매칭으로 70행 복구) ·
`DEP-3`(low — nginx 리슨 문법 회귀 테스트) · `MARK-1`(low — `keydown` 정리 미고정) ·
`MARK-2`(low — `patch` 가 앵커 미반영) · 기존 이월 `SEC-3`·`REC-1`.
운영 위생: `sites-enabled/data.utilverse.info.bak-visitlog` 가 활성 상태로 남아
`conflicting server name` 경고를 내고 있다(선재 문제, 우리와 무관하나 정리 권고).

---

## CR-024 · 2026-07-26 · 배포(G5) 직전 최종 코드리뷰 — FE-3 · ADM-1/2 · REC-3 · INGEST-3/GEO-8 · JOB-1

**판정: FAIL** · 차단 **1건(`DEPLOY-1`)** · **배포 불가(현 상태 그대로는)**
지시 `2026-07-26-code-review-4` · 대상 `49402ef` 이후 미커밋 25 modified + 45 신규

> ⚠️ 차단은 **코드가 아니라 배포 절차**다. A~F 의 구현 품질은 전반적으로 높고 변이로 확인했다.
> 문제는 **지금 배포하면 앱이 통째로 죽는다**는 것이고, 그 원인이 실서버에서 이미 재현 가능한 상태다.

### 재현

| 항목 | 결과 |
|---|---|
| `backend pytest` | **664 passed / 63 skipped** (junit `failures=0 errors=0`) |
| `frontend typecheck / test / build` | ✅ / **190 passed** (16 files) / ✅ |

지시 수치와 일치. 감사 변이 **28종**을 돌린 뒤 13개 파일 **바이트 단위 원복**을 확인했다.
서버는 **조회만** 했고 운영 DB 에 **쓰기 0회**(트랜잭션 포함).

---

## ⛔ 차단 `DEPLOY-1` (high) — 지금 배포하면 로그인·모든 인증 요청이 500 이 된다

### 실측한 사실

운영 DB(`realestate-db`, 가동 3시간)를 직접 조회했다.

| 확인 | 결과 |
|---|---|
| `app_user.status` 컬럼 | **없음 (0)** |
| `app_user.is_admin` 컬럼 | **없음 (0)** |
| `user_status_event` 테이블 | **없음 (0)** |
| `recommendation_job.result_meta`(010) | **있음 (1)** ← 010 은 적용됨 |
| `trade` 행수 | **611,518** (볼륨이 비어 있지 않다) |

**즉 마이그레이션 010 은 수동 적용됐는데 009 는 적용되지 않았다.** 이건 가설이 아니라
**이미 한 번 빠뜨린 증거**다.

### 왜 앱이 죽는가 — 코드로 확인

`app/repositories/postgis.py:199` 의 `_USER_COLUMNS` 가

```sql
id, email::text AS email, password_hash, status, is_admin,
created_at, status_changed_at, status_changed_by, status_reason
```

이고, 이걸 `create_user`(RETURNING) · `get_user_by_email`(로그인) · `get_user`(**모든 인증 요청**의
`current_user`)가 전부 쓴다. 컬럼이 없으면 `UndefinedColumn` → 500 이다.
마이그레이션 009 자신도 그렇게 경고한다(L41-42): *"컬럼 없이 새 코드를 띄우면 로그인·토큰검증이
전부 500 이 된다"*. 설계 의도대로 **조용히 우회하지 않고 죽는다** — 그래서 더더욱 순서가 절대적이다.

### 그런데 배포 절차서에 그 단계가 없다

`deploy/DEPLOY.md` **§5-3 DB 기동 + 마이그레이션** 전문:

> `backend/migrations/*.sql` 이 `docker-entrypoint-initdb.d` 로 **빈 볼륨 첫 기동에만**
> 001→002→003 순서로 자동 적용된다

- 전수 grep 결과 DEPLOY.md 에 **`009`·`010`·`manage_users` 언급이 0건**이다.
- `docker-compose.deploy.yml:54` 가 migrations 를 `initdb.d` 로 마운트하지만, **볼륨이 비어 있지
  않으므로 절대 실행되지 않는다.**
- "기존 DB 에 마이그레이션을 수동 적용" 하는 절이 문서에 **없다.** 재배포 절이 통째로 없다.

절차서를 그대로 따르면 → 009 미적용 → §5-4 에서 새 API 기동 → **전면 500.**

### 두 번째 층 — 009 적용 직후 소유자가 잠긴다

009 는 `status NOT NULL DEFAULT 'pending'` 이라 **기존 계정 1건이 즉시 로그인 불가**가 된다.
이건 의도된 설계이고 마이그레이션 헤더에 근거·복구 절차가 잘 적혀 있다(선점 방지 — 판단은 옳다).
문제는 **그 복구 절차도 DEPLOY.md 에 없다**는 것, 그리고 실행 경로를 실측하니:

```
docker exec realestate-api ls /app/scripts/   →  No such file or directory
docker exec realestate-api ... DATABASE_URL set: False
```

**API 컨테이너 안에는 `manage_users.py` 가 없다.** 호스트(`/opt/realestate/backend`)에서
파이썬 환경 + `DATABASE_URL` 로 실행해야 하는데, 그 사실이 어디에도 적혀 있지 않다.
관리자 0명 상태에서 CLI 가 안 돌면 **소유자가 자기 서비스에서 영구히 잠긴다**(승인해 줄 사람이 없다).

### 통과 조건

1. **DEPLOY.md 에 "기존 DB 마이그레이션" 절 신설** — 009·010 을 순서대로 적용하는 명령과
   적용 여부 확인 쿼리(`information_schema.columns` 로 `status`·`is_admin` 존재 확인).
   `initdb.d` 는 **빈 볼륨에만** 돈다는 사실을 그 자리에 다시 못박을 것.
2. **순서 강제** — 009 적용 → 확인 → 그 다음에 API 이미지 교체. 문서에 "이 순서를 바꾸면 전면 500"을 명시.
3. **첫 관리자 부트스트랩 절 신설** — 호스트에서 `cd /opt/realestate/backend && python
   scripts/manage_users.py --list / --approve / --grant-admin`, 그리고 **API 컨테이너 안에는 없다**는 주의.
   실행 전 `DATABASE_URL` 을 어디서 얻는지도 함께.
4. **롤백 절차** — 009 적용 후 되돌릴 때 `status` 컬럼을 남긴 채 구코드로 돌아가면 되는지
   (구코드는 그 컬럼을 안 읽으므로 안전) 한 줄로 확인해 둘 것.

> 이 4가지는 문서 작업이고 코드 변경이 없다. 차단으로 두는 이유는 **비용이 작고 실패 시 손해가
> 전면 outage** 이며, 010/009 비대칭이 "빠뜨릴 수 있다"를 이미 실증했기 때문이다.

---

## A. FE-3 핵심 루프 — **PASS**

사용자 지적("조건을 넣으면 그에 맞게 조정돼 나와야")에 대한 응답으로 조건입력→예산→지도 필터→
추천→리포트 루프가 들어왔다. 검증의 핵심은 **정직한 렌더링이 구조로 강제되는가**였다.

`priceView()` 가 유일 통로이고 `price_basis !== "listing"` 이면 `askKrw`·`gapPct` 를 **입력에서
버린다**(서버가 계약을 어겨도 화면에 못 나온다). 변이 6종 전부 KILLED:

| 변이 | 결과 |
|---|---|
| `price_basis` 무시하고 항상 호가 취급 | ✅ KILLED (6) |
| 추정인데 `ask_price_krw` 통과 | ✅ KILLED (2) |
| 추정인데 `ask_gap_pct` 통과 | ✅ KILLED (1) |
| `estimated` 항상 false | ✅ KILLED (1) |
| `confidence` 항상 confirmed | ✅ KILLED (2) |
| `jobPhase` 가 `"failed"` 를 모름 | ✅ KILLED (1) |

`total_score=null → "점수 없음"`(0 렌더 금지)도 `scoreView` 로 분리돼 있다.
담당자가 "변이 1종이 처음 통과해 자기충족 테스트를 발견·강화했다"고 한 건 **지금 상태로는 재현되지
않는다** — 내가 돌린 6종이 전부 죽으므로 강화가 실제로 반영된 것으로 본다.

## B. ADM-1 가입 승인제 — **PASS (열거 방지 실측 확인)**

담당자 주장을 말로 받지 않고 **TestClient 로 직접 두드려** 확인했다.

| 확인 | 결과 |
|---|---|
| 없는 계정 vs 틀린 비밀번호 | **401 / body 동일 / 헤더 동일** (status·body·header 전부 일치) |
| 맞는 비밀번호 + 미승인 | **403 `PENDING_APPROVAL`**, 본문에 토큰 없음, `Set-Cookie` 없음 |
| **타이밍 오라클** | 없는 계정 **27.22ms** vs 틀린 비밀번호 **26.85ms** → 차이 **1.4%** → 오라클 없음 |
| 관리자 EP(비인증/405대상/422대상/정상id) | **전부 404** |
| 승인된 **일반** 사용자 | **404** (403 아님) |
| 깨진 토큰 | **404** |

`dummy_password_hash()` 가 `lru_cache(maxsize=1)` 라 **같은 argon2 파라미터**로 1회만 만들어
재사용된다 — 비용이 실제로 같아지는 구조다. `can_administer = is_admin AND is_approved` 이고
`admin_user` 가 **매 요청 DB 조회**로 판정한다(토큰 클레임 아님).

**마지막 관리자 보호가 리포지토리 길목에 있다**는 주장도 확인 — `set_user_admin`·`set_user_status`
**양쪽 모두** `LastAdminError` 로 막고, API 경유는 `409 LAST_ADMIN` 으로 나온다.
과보호도 아니다(관리자 2명이면 1명 강등 허용).

변이 7종 중 6 KILLED — **M5(가입 기본을 approved 로) → 36 failed** 로 담당자 수치와 정확히 일치.
로그인 순서 뒤집기(승인검사를 비밀번호보다 먼저) → 5 KILLED, 404→403 → 7 KILLED,
`can_administer` 에서 승인요구 제거 → 1 KILLED, 마지막관리자 보호 제거 → 2·3 KILLED.

> 생존 1건 **`SEC-4`(low)**: `dummy_password_hash()` 를 **싼 파라미터 해시로 바꿔도** 테스트가 안 깨진다.
> 타이밍 방어가 **현재 올바르지만 회귀 그물이 없다.** 이런 방어는 조용히 되돌아간다.

## C. ADM-2 관리자 화면 — **PASS**

- **서버에 물어본다**: `GET /admin/users` 200=관리자 / 404=아님. 404 를 "권한 없음"으로 표시하지
  않는 이유(서버가 숨긴 걸 화면이 도로 알려주는 꼴)가 주석에 정확히 적혀 있다. 변이(404→노출) KILLED (2).
- **`loginFeedback()` 401 우선 분기는 구조적 보장이 맞다.** 테스트가 백엔드가 실수로 친절해진 경우
  (`USER_NOT_FOUND`·`BAD_PASSWORD`·`PENDING_APPROVAL` 을 401 로 보냄)까지 넣고
  **렌더 결과의 distinct 개수가 1** 임을 단언한다 — 뒤에 분기를 추가해도 401 은 닿지 못한다.
- **범위 초과 1건(세션 도중 승인 회수 403 처리)은 타당하다.** 권한을 매 요청 DB 로 판정하는 이상
  세션 중 회수는 **실재하는 상태**이고, 처리하지 않으면 화면이 조용히 깨진다. 범위를 넘었지만
  같은 기능의 완결에 필요한 최소 조각이다.

> 생존 1건 **`ADM-3`(low)**: 네트워크 오류 등 **모르는 상황**에서 `availability` 를 fail-open 으로
> 바꿔도 테스트가 안 깨진다. 코드는 fail-closed 로 올바른데("모르면 숨긴다") 그물이 없다.

## D. REC-3 제외 사유 — **PASS**

- **불변식("조회한 단지는 추천이거나 제외")이 실제로 강제된다.** `below_rank_cutoff` 기록을 지우는
  변이 → KILLED (1). 실측에서 강남구 50개 중 4개가 흔적 없이 사라지던 문제의 직접 원인이 닫혔다.
- **`top_n` 수정은 타당하다.** 사유 문구가 "상위 N건 밖"인데 N 이 요청값과 다르면 그 문장이 거짓이 된다.
  이제 `criteria.top_n` → `max(1, min(MAX_TOP_N=50, …))` → 파이프라인까지 전달되고
  스키마 `le=50` 과 상수가 같다. 10 고정으로 되돌리는 변이 → KILLED (1).
- **자산 유출 방어는 실제로 동작한다** — 원본 금액이 섞인 사유를 심어 직접 호출하니 안전 문구로
  치환되고 로그가 남았으며, 깨끗한 사유는 **건드리지 않았다**(과잉 마스킹 없음). IDOR 유지 확인.

> 생존 1건 **`REC-2`(low)**: `_strip_asset_amounts` 를 **통째로 제거해도** 테스트가 안 깨진다.
> `result_meta` 는 **평문 jsonb** 로 저장되고 API 로 나가는 자리라 SR4-2 등급 방어인데 그물이 없다.

## E. INGEST-3 · GEO-8 — **PASS (SQL 로 직접 확인)**

- **GEO-8**: 옛 `dong in addr.split()` 은 `'오남읍 오남리'` 가 **어떤 주소와도 같아질 수 없는**
  통과 불가 조건이었다는 진단이 맞다(엄격함이 아니라 버그). 고친 뒤 **느슨해지지 않았는지**를
  변이로 확인 — `dong_matches` 를 무력화하면 KILLED. 한 토막은 기존과 동일, 두 토막은 읍·면과 리를
  **둘 다** 요구하는 구조다.
- **기간 정정 — 내 SQL 로 검증.** 시군구별 `min/max(contract_date)` 를 집계하니
  **82개 전부 `2024-01~2026-07`**, 서로 다른 (시작,종료) 조합 수 = **1**.
  "22개를 백필해 82개 전부 동일 구간" 주장이 **사실**이다.
- 거래가 있는 시군구 = **82** ✅ · trade **611,518** ✅ · complex **16,462** ✅ ·
  좌표 **15,561 = 94.53%** ✅ · 부동산원 매칭 **13,796** ✅ · `region_code` NULL **4** ✅
- **교차오염 0 재확인**: 충돌 171그룹/377단지이나 **법정동 교차 0 · 시군구 교차 0 · 부동산원 모순 0**.
  데이터가 2.5배로 늘었는데도 GEO-1/3/4/6 규칙이 그대로 버틴다.

## F. JOB-1 — **PASS · 마이그레이션 파싱 접근도 타당**

`JOB_FAILED = "failed"` 로 고쳤고, 회귀 테스트가 **`001_init.sql` 원문에서 CHECK 허용 목록을 파싱해**
`JOB_FAILED ∈ allowed` 를 단언한다. **이 접근은 타당하다** — 리터럴을 양쪽에 중복해 적는 대신
제약의 원천과 코드 상수를 묶으므로, 어느 쪽을 바꿔도 걸린다.

변이 확인: 실패 경로를 `"error"` 로 되돌림 → KILLED (1) · `JOB_FAILED` 상수를 `"error"` 로 → KILLED (1).
프론트도 `jobPhase` 가 `"failed"`·`"error"` 를 **둘 다** 실패로 받는다(한쪽만 고치면 증상이 같다는
진단이 정확했고, 방어적으로 둘 다 수용한 것도 옳다). 변이(`"failed"` 케이스 제거) → KILLED (1).

> **`JOB-3`(info)**: 파싱이 `001_init.sql` **한 파일만** 본다. 나중에 다른 마이그레이션이 이 CHECK 를
> `ALTER` 하면 테스트는 옛 파일을 읽고 계속 통과한다. 지금은 010 이 컬럼 추가만 해서 무해함을 확인했다.
> → 마이그레이션 전체를 순서대로 훑어 **마지막 정의**를 쓰도록 하면 닫힌다.
>
> **`JOB-2`(low)**: `run_recommendation_job` 의 초기값이 아직 `status = "error"` 다(`recommend.py:95`).
> 두 경로가 모두 덮어써서 **현재는 죽은 값**이지만, 하필 사고를 낸 그 문자열이 같은 함수에 남아 있다.
> `JOB_FAILED` 로 바꾸면 앞으로 어떤 경로가 새로 생겨도 합법값으로 떨어진다.

---

## 판단 요청 2 — 남은 문제 3건, 배포 차단인가 → **셋 다 아니다**

| 항목 | 실측 | 판정 |
|---|---|---|
| ① 신설 구 부동산원 마스터 부재 | 최저 커버리지 **28275 69.3%**(reb 0%) · 28125 70.0%(reb 0%) · 28290 79.7% · 화성 41591/93/95 84~86%(reb 0%) | **비차단.** 좌표가 **틀린 게 아니라 없는** 것이고(교차오염 0), 원칙대로 "정보 없음"으로 보인다. 외부 데이터 원천 한계 |
| ② `region_code` NULL 4건 | 한진해모로(신당동)·샹그레빌(청량리동)·관악푸르지오102동(사당동)·현대성우(도봉동), **거래 합계 8건** | **비차단.** 611,518건 중 8건(0.0013%). 조용히 사라지지 않고 카운트로 드러남 |
| ③ 고아 볼륨 228MB | `realestate-pgdata` 와 `realestate_pgdata` **둘 다 존재** | **비차단이나 배포 전 확인 권고** — 아래 `OPS-1` |

> ⚠️ **`OPS-1`(medium) — 내가 추가로 발견한 것**: 디스크가 **90% 사용(2.6GB 여유)** 이다.
> DEPLOY.md §5-2 는 **서버에서 API 이미지를 빌드**한다. 여유 2.6GB 에서 이미지 빌드는 실패하거나
> 디스크를 채울 수 있고, 그러면 **동거 실서비스(itsmine·autobtc)까지 영향**을 받는다.
> 배포 전 고아 볼륨 정리(어느 쪽이 현행인지 확인 후) + `docker system df` 확인을 권고한다.
> 볼륨 이름이 하이픈/언더스코어로 갈린 상태라 **잘못 지우면 운영 데이터가 날아간다** — 반드시 확인 후.

## 판단 요청 3 — REC-3 "조회 상한 50개" 가 제품 결함인가 → **결함은 아니다. 다만 medium 개선 대상**

운영 DB 실측:

| 지표 | 값 |
|---|---|
| 시군구 수 | 82 |
| **단지 50개를 넘는 시군구** | **76 / 82** |
| 단지 수 중앙값 | **184** |
| 최대 | **544** (강남구 506 언급과 같은 계열) |

즉 거의 모든 지역에서 사용자는 **184개 중 50개(27%)** 만 후보로 본다. 최대 지역은 9%다.

**그럼에도 "결함"이라고 부르지 않는 이유:**
1. 50개가 **임의로 잘리지 않는다.** 정렬이 `active_listings → affordable_trades → recent_trades → id`
   이고, 예산 내 체결 이력이 있는 단지가 먼저다(CR-021 에서 이 정렬의 효과를 A/B 로 실측 —
   예산 내 거래 450 → 8,094). 즉 "아무거나 50개"가 아니라 **예산에 맞는 쪽부터 50개**다.
2. **숨기지 않는다.** notes 에 "조회 상한 50개 단지"를 고지하고, 이번 REC-3 로
   후보에서 탈락한 것들도 사유가 남는다.
3. 상한의 이유가 **LLM/통계 비용**이라는 근거가 코드에 있다.

**그러나 사용자 지적의 본질과 맞닿아 있다** — "내 조건에 맞게 조정돼 나와야 한다"는 요구에서
모수가 27% 면 최적 후보가 애초에 후보에 못 든다. → **`REC-4`(medium)**:
(a) `listing` 이 0행이라 현재 파이프라인은 사실상 규칙 기반이므로 상한을 올릴 여지가 크다,
(b) 여러 시군구를 고르면 **50이 전체 합계**라 지역이 늘수록 지역당 모수가 더 줄어든다 —
지역별 배분이나 상한 상향을 검토할 것, (c) 고지 문구에 **"N개 중 50개"** 로 모수를 함께 보이면
사용자가 한계를 정확히 알 수 있다.

---

### 판정

**FAIL — 차단 1건(`DEPLOY-1`).**

A~F 의 **코드**에는 배포를 막을 결함이 없다. 변이 28종 중 24 KILLED 이고, 생존 4건은 전부
"현재 동작은 옳은데 회귀 그물이 없다"는 low 사안이다. 특히 ADM-1 의 계정 열거·타이밍 방어는
말이 아니라 **실측(401 완전 동일 · 타이밍 차이 1.4%)** 으로 확인했고, FE-3 의 정직한 렌더링은
`priceView` 라는 **유일 통로**로 구조화돼 서버가 계약을 어겨도 화면이 지켜진다.

막는 것은 **절차**다. 운영 DB 에 **009 가 적용돼 있지 않고**(010 은 적용됨), 절차서에는
기존 DB 에 마이그레이션을 적용하는 단계가 **아예 없다**. 이 상태로 새 코드를 올리면
`get_user` 가 없는 컬럼을 읽어 **모든 인증 요청이 500** 이 된다 — 로그인조차 안 된다.
게다가 009 적용 직후에는 **유일한 실사용자가 잠기고**, 복구 CLI 는 API 컨테이너 안에 없어
호스트에서 돌려야 하는데 그 사실도 문서에 없다.

문서 4개 절을 추가하는 작업이고 코드 변경이 없다. **그것만 채우면 즉시 배포 가능하다.**

**비차단 이월**: `REC-4`(medium, 후보 상한) · `OPS-1`(medium, 디스크 90%·고아 볼륨) ·
`SEC-4`(low, 타이밍 방어 그물) · `REC-2`(low, 자산 마스킹 그물) · `ADM-3`(low, 관리자 fail-closed 그물) ·
`JOB-2`(low, 죽은 `"error"` 초기값) · `JOB-3`(info, 마이그레이션 파싱이 001 만 봄) ·
`GEO-9`(low, 신설 구 좌표 69~87%) · `INGEST-4`(info, `region_code` NULL 4건).

---

## CR-025 · 2026-07-26 · DEPLOY-1 해소 재검증 (code-reviewer, herdr re-review 대행)

**판정: PASS** · 차단 **0건** · **배포 가능** · `DEPLOY-1` **RESOLVED** · 승격 **0건**
지시 `2026-07-26-code-review-5` · CR-024 FAIL 후속 · 코드 변경 0(문서 +100 / 테스트 +55)

### 재현

`backend pytest` **667 passed / 63 skipped**(664 + 신규 3) · frontend **190 passed**(무변경).
지시 수치와 일치. 변이 9종 후 `DEPLOY.md` **바이트 단위 원복** 확인. 서버는 **조회만**
(운영 DB 쓰기 0회, `/etc/nginx` 무수정, 임시 파일 정리 완료).

---

### 1. DEPLOY-1 이 실제로 닫혔나 — **닫혔다. 단계를 서버에서 하나씩 짚었다**

CR-024 의 통과조건 4개가 전부 이행됐다. 문서를 읽는 데 그치지 않고 **명령이 이 서버에서
실제로 동작하는 형태인지** 전제조건을 하나씩 실측했다.

#### ① §5-3b 명령이 서버에서 도는 형태인가 — **전부 확인**

| 전제 | 실측 |
|---|---|
| 컨테이너명 `realestate-db` | ✅ 존재(가동 중) |
| `docker exec -i ... psql < "$f"` 리다이렉션 | ✅ 형태 유효(`-i` 있음 — 없으면 stdin 이 안 붙는다) |
| `pg_dump --schema-only` 백업 | ✅ `docker exec`(비대화) + 호스트 리다이렉션으로 올바름 |
| `-v ON_ERROR_STOP=1` | ✅ 명시 + 없을 때의 결과("실패가 성공으로 보인다")까지 기재 |
| 적용 상태를 **DB 에 묻는** (1)·(4) | ✅ `information_schema.columns` 로 사실 확인 |

**(1)/(4) 를 앞뒤로 배치한 설계가 특히 좋다.** 문서·기억이 아니라 DB 가 답하고,
(4)에서 컬럼이 안 생겼으면 그 자리에서 멈춘다 — 아래 ③의 안전망이 여기서 나온다.
마이그레이션이 전부 `ADD COLUMN IF NOT EXISTS` 라 재실행 안전하다는 설명도 파일과 대조해 맞다.

#### ② §5-5b 의 CLI 실행 형태가 맞는가 — **전부 확인**

CR-024 에서 내가 지적한 "CLI 가 컨테이너에 없다"가 정확히 반영됐고, 대체 경로의 전제를 실측했다.

| 전제 | 실측 |
|---|---|
| 호스트 venv `/opt/realestate/backend/.venv/bin/activate` | ✅ **존재** |
| `.env` 의 `POSTGRES_PASSWORD` 키 | ✅ 존재(값은 출력하지 않고 개수만 확인) |
| `docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' realestate-db` | ✅ **`172.20.0.2`** 반환 |
| 비밀번호·IP 를 화면에 안 찍는 형태 | ✅ `PW=$(grep …)` / `DBIP=$(docker inspect …)` 로 변수에만 |

`docker exec realestate-api python scripts/manage_users.py` 가 **실패한다**는 사실을 굵게
적어 둔 것도 맞다(내가 CR-024 에서 `/app/scripts` 부재·`DATABASE_URL` 미설정으로 실측한 그대로).
잠김 복구 절과 "SSH 키를 잃으면 복구 불가"까지 적혀 있다.

#### ③ 순서(009 → 코드 → 차단해제 → 승인)에 빠진 고리가 없나 — **순서는 옳다. 다만 고리 하나 지적**

문서 순서: **5-3b(마이그레이션) → 5-4(API 기동) → 5-5(nginx/TLS) → 5-5b(첫 관리자) → 5-5c(가입차단 해제) → 5-6(최종확인)**.
이 배열은 정확하다 — 특히 **관리자를 만든 뒤에 가입을 연다**(5-5b → 5-5c)는 순서가 중요하다.
뒤집으면 승인해 줄 사람이 없는 채로 가입이 열린다.

> ⚠️ **빠진 고리 1개 — `DEPLOY-2`(medium, 비차단)**: 문서 어디에도 **서버 소스를 갱신하는 단계가 없다.**
> §4 는 `frontend/dist/` 만 rsync 하고, 백엔드 소스에 대한 `git pull`·rsync 절이 전무하다(전수 grep).
> 실측: 지금 서버 `/opt/realestate` 는 `49402ef` 라 **`migrations/009`·`010`·`manage_users.py` 가 아직 없다.**
> 절차서를 그대로 따르면 §5-2 가 **낡은 소스로 이미지를 빌드**하고 §5-3b 가 파일을 못 찾는다.
>
> **그럼에도 차단이 아닌 이유** — 이 실패는 **조용하지 않고, 두 곳에서 막힌다**:
> 1. §5-3b (3) 루프가 `No such file or directory` 를 찍고, 이어지는 **(4) 적용 확인**에서
>    컬럼이 안 생긴 것이 드러난다.
> 2. §5-5b 의 `manage_users.py` 도 없으므로 거기서 또 멈춘다.
>
> 즉 낡은 코드로 §5-5c(가입 차단 해제)까지 가려면 **명시적 확인 단계 두 개를 무시**해야 한다.
> 그래도 그 분기의 결과가 나쁘므로(낡은 코드는 `status` 를 안 읽어 **승인제가 없는 채로 가입이 열린다**)
> 아래 두 가지를 이번 배포에서 **함께 하기를 권고**한다:
> - **§5-0 소스 갱신 절 신설** — `cd /opt/realestate && git fetch && git checkout <커밋>` 을 §5-2 앞에.
> - **§5-5c 앞에 기능 확인 1줄** — 가입을 열기 전에 승인제가 실제로 사는지 확인:
>   `POST /api/v1/auth/register` → **201 + `status:"pending"`** 인지. 헤더 5종 확인만으로는
>   승인제 생존을 알 수 없다.

---

### 2. 새 회귀 테스트 3건이 자기충족적인가 — **아니다. 다만 결이 거칠고, 담당자 변이 주장은 부정확하다**

`DEPLOY.md` 를 9가지로 훼손해 돌렸다.

| 변이 | 결과 |
|---|---|
| `ON_ERROR_STOP` 안내 삭제 | ✅ KILLED |
| `scripts/manage_users.py` 삭제 | ✅ KILLED |
| `--grant-admin` 삭제 | ✅ KILLED |
| `--approve` 삭제 | ✅ KILLED |
| **최신 마이그레이션(010) 파일 참조 삭제** | ⛔ **SURVIVED** |
| 009 파일 참조 삭제 | ⛔ SURVIVED |
| "마이그레이션 → 코드" 문구 삭제 | ⛔ SURVIVED(정당 — 아래) |
| "CLI 는 호스트에서 돈다" 경고 삭제 | ⛔ SURVIVED |
| `DATABASE_URL` 조립 줄 삭제 | ⛔ SURVIVED |

**핵심 성과는 확인됐다.** 테스트의 선언된 목적("011 이 생기면 먼저 알려준다")을 직접 검증했다 —
빈 `migrations/011_probe_cr025.sql` 을 만들고 돌리니 **실제로 FAIL**했다:

```
AssertionError: 최신 마이그레이션 011_probe_cr025.sql 이 DEPLOY.md 에 없습니다.
```

(프로브 파일은 즉시 삭제, `git status` 잔여 0 확인.)
파일 목록에서 최신 것을 **자동으로 뽑는** 설계는 옳고, 001~008 을 요구하지 않도록 좁힌 판단도
타당하다 — 그것들은 initdb 로 이미 적용됐고 실제 사고 모드는 "새로 추가하고 문서를 안 고침"이다.

> **정정 — 담당자 주장이 부정확하다.** 보고서는 *"DEPLOY.md 에서 최신 마이그레이션(010) 언급을
> 지우면 → 실제로 FAIL"* 이라 했으나, **재현되지 않는다.** 검사식이
> `number in md`(= 문자열 `"010"` 이 문서 어딘가에 있는가)라서,
> §5-3b (3) 의 **실제 적용 루프에서 파일 경로를 지워도** 208행 주석("있으면 010 적용됨")의
> `010` 이 남아 **통과한다.** 즉 "언급을 지우면 실패"가 아니라 **"그 세 글자를 문서에서 전부
> 없애면 실패"** 다. 새 마이그레이션(011)에는 우연한 등장이 0건이라 목적은 달성되지만,
> 변이 결과를 이렇게 기술하면 그물이 실제보다 촘촘해 보인다.

같은 이유로 `"호스트"`·`"DATABASE_URL"`·`"코드보다 먼저"` 도 **문서 전체 대상 부분문자열 검사**라,
정작 §5-5b 의 명령 블록이 통째로 사라져도 다른 곳의 같은 단어로 통과할 수 있다
(`"호스트 nginx"` 등). ※ "마이그레이션 → 코드" 변이의 생존은 **정당하다** — 단언이 `or` 이고
대체 문구 "코드보다 먼저"가 §5-3b 제목에 살아 있어, 의미가 보존된 경우다.

→ **`DEPLOY-3`(low, 비차단)**: 토큰 존재가 아니라 **해당 절(5-3b / 5-5b) 안에** 있는지로 좁힐 것
(섹션을 잘라 그 구간에서만 검사). 지금도 "새 마이그레이션 누락"이라는 **주된 실패 모드는 잡는다.**

---

### 3. 비차단 항목 승격 심사 — **승격 0건**

#### OPS-1(디스크) — **승격하지 않는다. 내가 CR-024 에서 과대평가했다**

CR-024 에서는 "여유 2.6GB 에서 이미지 빌드"만 보고 medium 을 매겼는데, **필요량을 재지 않았다.**
이번에 실측했다.

| 항목 | 실측 |
|---|---|
| 디스크 여유 | **2.6GB** (25G 중 22G 사용, 90%) |
| `realestate-api:local` 이미지 | **240MB** |
| Docker 이미지 총량 / **회수 가능** | 8.564GB / **7.326GB (85%)** — 54개 중 활성 9개 |
| 빌드 캐시 | 1.317MB |

재빌드가 필요한 것은 맞다(코드가 바뀌었다). 그러나 **240MB 이미지 재빌드에 2.6GB 는 충분하다** —
새 레이어 + 구 이미지 병존을 감안해도 전이 사용량은 0.3~0.5GB 수준으로 여유의 1/5 이하다.
게다가 **7.3GB 가 즉시 회수 가능**해서(`docker image prune`) 비상 여유가 크다.
→ **위험하지 않다.** 승격 불가. OPS-1 은 위생 항목으로 유지한다.

**덤으로 CR-024 에서 내가 "확인 후에만 삭제하라"고 남긴 볼륨 이름 혼동을 해소했다:**

| 볼륨 | LINKS | 크기 | 판정 |
|---|---:|---:|---|
| `realestate-pgdata` (하이픈) | **1** | 468MB | **현행 — 건드리지 말 것** |
| `realestate_pgdata` (밑줄) | **0** | 237MB | **고아 — 삭제 대상** |

`LINKS=0` 이 곧 아무 컨테이너도 안 쓴다는 뜻이라 판정이 명확하다.

#### 나머지 — 전부 유지

| 항목 | 판정 근거 |
|---|---|
| `REC-4` 후보상한 50 | 제품 한계이고 **고지돼 있으며** 정렬이 예산 기반이라 임의 절단이 아니다. 배포와 무관 |
| `SEC-4` 타이밍 방어 그물 | **방어 자체는 동작한다**(CR-024 실측 1.4%). 테스트 부재일 뿐 |
| `REC-2` 자산 마스킹 그물 | **방어 자체는 동작한다**(CR-024 에서 원본을 심어 확인). 테스트 부재일 뿐 |
| `ADM-3` 관리자 fail-closed 그물 | 코드는 fail-closed 로 올바르다. 테스트 부재일 뿐 |
| `JOB-2` 죽은 `"error"` 초기값 | 두 경로가 모두 덮어써 **도달 불가**. 위생 |

**승격 사유가 있는 항목이 없다.** 넷은 "동작은 옳고 그물만 없다"이고, 그물 부재는 배포를
막는 사유가 아니다(배포 후 회귀 위험이지 배포 시점 결함이 아니다).

---

### 판정

**PASS · 배포 가능.** `DEPLOY-1` **RESOLVED.**

CR-024 에서 막은 이유는 "절차서대로 하면 인증이 전부 500 이 된다"였고, 그 구멍이 메워졌다.
문서를 읽고 끝내지 않고 **서버에서 전제조건을 실측**해 확인했다 — venv 존재, `.env` 키,
`docker inspect` 가 실제로 `172.20.0.2` 를 반환하는 것, 컨테이너명, `psql -i` 리다이렉션 형태까지.
특히 §5-3b 를 **"DB 에 물어보고 → 적용하고 → 다시 물어본다"** 로 짠 것이 좋다.
그 (4)번 확인이 아래 `DEPLOY-2` 의 안전망 역할까지 한다.

새 회귀 테스트는 **자기충족적이지 않다** — 선언된 목적(새 마이그레이션 누락)을 011 프로브로
직접 확인했고, `manage_users.py`·`--approve`·`--grant-admin`·`ON_ERROR_STOP` 삭제를 잡는다.
다만 검사가 문서 전체 부분문자열이라 결이 거칠고, **담당자의 "010 언급을 지우면 FAIL" 주장은
재현되지 않아 정정한다**(그 세 글자를 전부 없애야 실패한다).

`OPS-1` 은 **내가 CR-024 에서 필요량을 재지 않고 매긴 것**이라 이번에 실측해 내렸다 —
240MB 이미지에 2.6GB 여유이고 7.3GB 가 회수 가능하다. 재빌드는 위험하지 않다.

**배포 전 권고(차단 아님)** — `DEPLOY-2` 의 두 줄을 지금 넣는 것이 좋다:
① §5-2 앞에 **서버 소스 갱신** 절, ② §5-5c 앞에 **가입 열기 전 승인제 생존 확인**
(`register` → `201 status:"pending"`). 지금 상태로도 §5-3b(4)·§5-5b 에서 두 번 막히지만,
그 두 확인을 건너뛴 경우의 결과가 "승인제 없이 가입이 열림"이라 값싼 보험을 걸어 둘 값어치가 있다.

**비차단 이월**: `DEPLOY-2`(medium) · `DEPLOY-3`(low, 검사 범위 좁히기) ·
기존 `REC-4`(medium) · `OPS-1`(low 로 하향 · 고아 볼륨 `realestate_pgdata` 특정 완료) ·
`SEC-4` · `REC-2` · `ADM-3` · `JOB-2` · `JOB-3` · `GEO-9` · `INGEST-4`.

---

## CR-026 · 2026-07-26 · WEIGHT-1 가중치 반영 · UX-1 UI 재설계 (code-reviewer, herdr re-review 대행)

**판정: PASS** · 차단 **0건** · **배포 가능** · `prefer` 부채는 **후속(조건부)**
지시 `2026-07-26-code-review-6` · CR-025 이후 미커밋 60건

### 재현

`backend` **693 passed / 63 skipped** · `frontend` **358 passed**(27 files) · typecheck·build 통과.
지시 수치와 일치. 변이 **19종** 후 6개 파일 **바이트 단위 원복** 확인. 서버는 **조회만**
(운영 DB 쓰기 0회, 실사용자 계정 무접촉).

---

## A. WEIGHT-1 — **PASS**

### ⚠️ 가장 중요한 확인: "살아 있는 축은 가치 하나" — **사실이다**

담당자의 자기고백을 운영 DB 에서 직접 셌다.

| 축 | 원천 테이블 | 실측 | 결과 |
|---|---|---:|---|
| 가격(호가–적정가 갭) | `listing` | **0행** | 신호 없음 |
| 리스크(매물 신뢰도) | `listing` | **0행** | 신호 없음 |
| 입지(학군·역세권·인프라) | `poi`·`school_district`·`road_segment`·`transit_plan` | **전부 0행** | 신호 없음 |
| **가치(12개월 거래회전율)** | `trade` **611,518** · `complex.total_households` **13,796** | 있음 | **유일하게 살아 있음** |

**즉 지금 슬라이더를 어떻게 움직여도 순위를 바꾸는 축은 '가치' 하나뿐이고,
가격·리스크·입지에 100% 를 몰아주면 세 경우 모두 "점수 없음"으로 같은 결과가 된다.**
담당자 보고가 정확하다. 이걸 **결함이 아니라 데이터 부재**로 정직하게 처리한 것이 이 작업의 핵심이고,
`score_axes`·`score_notes`·`coverage_pct` 로 사용자에게 그 사실이 전달된다.

### 설계 판단 3건 — 전부 타당

**① `finance-tax-advisor` 를 어느 축에도 넣지 않은 것 — 옳다.**
예산은 취향이 아니라 **하드 제외**다(못 사는 집은 점수가 아무리 높아도 추천이 아니다).
게다가 `finance_finding` 의 `score` 는 항상 `None` 이라 예전 신뢰도 평균에도 들어간 적이 없다 —
"빼기로 했다"가 아니라 **원래 점수 축이 아니었던 것을 명시한 것**이다.

**② confidence 를 곱하지 않기로 한 정정 — 옳다.** 사용자 가중치는 *선호*이고 confidence 는
*인식론적 품질*이다. 곱하면 "가격에 100% 를 줬는데 confidence 0.85 라 85% 만 반영"이 되어
사용자가 자기 입력도 신뢰도도 해석할 수 없게 된다. confidence 는 축별 행에 **그대로 노출**되므로
숨긴 것도 아니다. 변이 **W4(가중치×confidence 로 되돌림) → KILLED** 로 이 판단이 잠겨 있다.

**③ 근거 없는 축은 0점이 아니라 제외 후 재정규화 — 옳다.** 0 은 "나쁘다"는 **없는 판정**을 만든다.

### 변이 10종 — 유효 9 중 7 KILLED

| 변이 | 결과 | 변이 | 결과 |
|---|---|---|---|
| **W1** 근거 없는 축에 0점 채움 | ✅ **KILLED (7)** | W5 모르는 키를 조용히 버림 | ✅ KILLED (2) |
| W2 재정규화 안 함 | ✅ KILLED (1) | W6 음수 가중치 사용 | ✅ KILLED (1) |
| W3 적용 축 0개일 때 None→0 | ✅ KILLED (3) | W8 커버리지 고지를 적용 축에만 | ✅ KILLED (1) |
| **W4 가중치×confidence** | ✅ **KILLED (1)** | W9 환금성 만점 기준 어긋냄 | ⛔ SURVIVED |
| W10 finance 를 가격 축에 추가 | ⛔ SURVIVED | W7 NaN/inf 통과 | (앵커 미스) |

> **`SCORE-1`(low)** — W9 생존은 **주석의 주장이 과하다**는 뜻이다.
> `TURNOVER_FULL_SCORE_PCT` 옆에 *"동기화는 `test_환금성_만점_기준이_좋음_등급_경계와_같다` 가
> 고정한다"* 고 적혀 있으나, 그 테스트는 상수에서 표본을 만들어 `grade == "좋음"` 과 `score == 100`
> 을 볼 뿐이라 **상수를 5.0 → 9.0 으로 올려도 통과한다**(9% 도 `>= 5.0` 이라 여전히 "좋음").
> 즉 "같다"가 아니라 **"경계 이상"만** 고정한다. 올리면 회전율 5% 단지가 rationale 에선 "좋음"인데
> 점수는 55.6 이 되어, 정확히 그 테스트가 막으려던 불일치가 생긴다.
> → 양방향 단언(경계 직전 값에서 `grade != "좋음"`)을 추가하거나, 두 상수를 한 곳에서 파생시킬 것.
>
> **`SCORE-2`(info)** — W10 생존: `agent_ids` 는 계산에 안 쓰이는 표시용 메타라 점수는 안 바뀐다.
> 다만 응답으로 "이 축이 무엇을 보는가"를 사용자에게 말하는 값이라 틀리면 오도한다. 낮은 우선순위.

---

## B. UX-1 — **PASS**

### `price_confidence` 판단 — **담당자가 옳다. 백엔드를 고쳐 `confirmed` 를 만들면 안 된다**

지적 자체는 사실이다. `routes.py:419` 가 `"estimated" if c.recent_price_krw else "unknown"` 이라
**`confirmed` 등급이 존재하지 않고**, 가격이 있는 마커는 100% '추정'이 된다.

**그런데 이건 백엔드 결함이 아니라 정직한 보고다.** 이 프로젝트가 CR-021 에서 확립한 계약은:

- `listing`(호가) = "지금 이 값에 살 수 있다" → **사실**
- `trade`(실거래) = "최근 이 정도에 거래됐다" → **추정**

지도 마커의 `recent_price_krw` 는 **실거래 파생값**이고, `listing` 은 **0행**이다.
따라서 `estimated` 는 정확한 라벨이고, `confirmed` 를 만들려면 **없는 확신을 지어내야** 한다 —
그건 CR-021 이 한 라운드를 통째로 써서 막은 바로 그 위반이다.

**"전부에 붙는 신호는 신호가 아니다"** 라는 판단도 옳다. 마커 100% 에 붙는 배지는 개별 항목을
구분하지 못하므로 정보량이 0 이면서 화면만 어지럽힌다. 다만 **사실 자체를 지우면 안 되고**,
실제로 지우지 않았다 — `MapLegend.tsx`(+ 테스트)로 옮겨 한 번 말한다. 마커 모듈 주석이
백엔드 코드 줄까지 인용해 근거를 남긴 것도 좋다. → **고칠 것은 없다.**

### CR18-7 diff 재사용이 깨지지 않았는가 — **깨지지 않았다(변이·계측 양쪽 확인)**

| 변이 | 결과 |
|---|---|
| **B1 id 기준 재사용 제거(CR18-7 원복)** | ✅ **KILLED (15)** |
| B2 사라진 마커 미정리(CR18-6) | ✅ KILLED (5) |
| B3 좌표 순서 뒤집기(CR18-5) | ✅ KILLED (4) |
| B4 콜백 상자 갱신 제거 | ✅ KILLED (1) |

성능도 **단독 실행으로 직접 계측**했다(병렬 시 CPU 경합 주의사항대로):

```
[perf] 같은 목록 재조회: 0.72ms (기준선 0.79ms)
[perf] 팬 1회(100개 교체): 3.89ms (기준선 5.43ms)
[perf] 선택 변경 0.79ms · hover 0.46ms · 단계 전이 price↔dot 7.90ms
```

담당자 보고(5.43 → 3.94ms)와 일치한다. 마커 3단계를 넣고도 재사용이 유지됐다.

### 나머지 UX 판단

| 항목 | 판정 |
|---|---|
| 순위 마커가 `['2위','추정 14.8억']` 이라 순위가 크고 금액이 작았다 | 지적 타당(숫자가 주인공 규칙 위반). 수정 확인 |
| 밀집 60 초과 시 전량 dot | 변이 `DENSITY_LIMIT=99999` → **KILLED (1)**. 예외(선택·추천·hover) 제거 → **KILLED (5)** — 되찾는 경로가 실제로 지켜진다 |
| 정렬 null ≠ 0 | 결측을 0 취급 → **KILLED (7)**, 결측을 항상 앞으로 → **KILLED (4)**. "시세 미상이 가장 싼 집"이 구조적으로 막혔다 |
| `region_codes` 실제 전송 | ✅ `App.tsx:123` 이 `rec.start({ purpose, top_n, region_codes })` 로 실제 전송. 과거엔 아예 안 보냈다는 지적과 일치 |
| **RegionPicker 를 FilterRail 이 아니라 추천 패널에** | **동의한다.** 지역 선택은 `POST /recommendations` 의 후보 범위만 좁히고 **지도 마커를 바꾸지 않는다.** FilterRail 에 두면 "지도가 걸러질 것"이라는 거짓 인상을 준다 — 컨트롤의 위치가 곧 약속이라는 판단이 맞다 |
| 역 검색을 지도 이동 전용으로 한정 + "필터가 아니다" 상시 노출 | 타당. 역 반경 추천을 미노출로 둔 것도 `poi` 0행 상태에서 옳다 |
| 데스크톱 레이아웃 반박 | 현재 구현이 판정 대상이므로 과거 CSS 의 성격은 다투지 않는다. 다만 **"시트를 옆으로 늘린 것"이라는 자기진단이 더 정확**해 보이며, 그 진단이 이번 재설계의 방향을 옳게 잡았다 |
| 지역 목록을 번들에 포함 | **현재로선 타당**(82개 시군구, 거의 정적, "데이터 없는 지역일 수 있음" 고지 있음). `/regions` 엔드포인트는 DB 를 단일 진실원으로 삼는다는 점에서 더 낫지만 **차단 사유는 아니다** → `UX-2`(low) |

테스트가 실버그 2건(`Number('')===0` → 지도가 (0,0)으로 이동 · '성남 분당' 0건)을 잡았다는 것과,
자기충족 테스트 1건(`user.keyboard` 로는 슬라이더 값이 안 바뀌어 조용히 통과)을 발견해 교체했다는
보고는 **이 원장이 반복해 요구해 온 자세** 그대로다.

---

## C. `prefer` 정직성 부채 — **판정: 후속(later) · 단 조건부**

### 사실 확인 — 부채는 실재한다

| 확인 | 결과 |
|---|---|
| `ConditionsScreen` 이 받는 값 | `subway_within_m`(역세권) · `school_district`(학군 0~5) · 세대수 · `area_min/max_m2` · `built_after` |
| `buildMapQuery` 가 보내는 값 | **`area_min_m2`·`area_max_m2`·`built_after` 뿐** |
| 백엔드가 `prefer` 를 읽는가 | `recommend.py`·`orchestrator.py`·`routes.py` 전수 grep → **0건** |

**역세권·학군·세대수는 저장만 되고 어디에도 쓰이지 않는다.** 담당자 진술이 정확하다.

### 왜 차단이 아닌가

1. **데이터가 아예 없다.** `poi`·`school_district`·`road_segment`·`transit_plan` **전부 0행**이다.
   배선해도 역세권·학군은 **전건 제외 아니면 무동작**이 된다. 지금 할 수 있는 정직한 일은
   기능 구현이 아니라 **고지**다.
2. **이번 라운드가 같은 병을 고친 쪽이다.** WEIGHT-1 이 정확히 "저장만 되던 슬라이더"를 없앴고,
   `prefer` 는 그 작업의 **범위 밖**이었다. 고친 사람이 남은 부채를 스스로 신고했다.
3. **피해 성격이 다르다.** 데이터 손상·보안·장애가 아니라 설정 화면 3개 입력의 오해다.
   사용자는 1인(소유자)이고, 이 지적을 한 당사자다.
4. 내가 이 원장에서 일관되게 적용해 온 기준은 **"능력이 없는 것"이 아니라 "숨기는 것"** 이다
   (REC-4 후보상한 50 을 통과시킨 이유가 그것이다 — 고지가 있었다).

### 그래서 조건을 붙인다 — `PREF-1`(medium)

같은 화면에 **이미 훌륭한 고지 장치가 있다.** 가중치 절은 `!weightsApplied()` 일 때
*"현재 이 비중은 저장만 되고 추천 순위 계산에는 아직 반영되지 않습니다"* 를 띄우고,
서버가 반영하기 시작하면 **자동으로 사라진다**(하드코딩이 아니라 관측값 기반).

`prefer` 3종에는 그 장치가 **없다.** 바로 옆 `area_min_m2`·`built_after` 는 **실제로 동작**하므로
사용자는 둘을 구분할 수 없다 — 이 비대칭이 진짜 결함이다.
→ **다음 라운드에서 반드시**: 같은 패턴으로 "데이터 수집 전이라 아직 반영되지 않습니다"를
역세권·학군·세대수에 붙일 것. UI 전용 변경이고 몇 줄이다.

> 이대로 고지 없이 오래 두면, WEIGHT-1 이 한 라운드를 들여 없앤 "작동하는 척"을
> 한 층 옆에서 그대로 반복하는 셈이 된다.

---

### 판정

**PASS · 배포 가능.** 차단 0건.

이번 라운드의 값어치는 **"가중치를 반영했다"가 아니라 "반영할 수 없는 축을 정직하게 드러냈다"** 에 있다.
근거 없는 축에 0점을 채우는 변이가 7건을 깨뜨리고, 재정규화·`None` 유지·커버리지 고지가 전부
변이로 잠겨 있다. 특히 **가격·리스크·입지 세 축이 지금 다 죽어 있다는 사실**을 내가 운영 DB 에서
독립적으로 확인했고, 그것이 제품 화면에 그대로 나타난다.

`price_confidence` 는 **고칠 것이 없다** — 실거래 파생값을 `estimated` 라 부르는 것은 정확하며,
`confirmed` 를 만드는 것이야말로 CR-021 이 막은 위반이다. 마커에서 글자를 빼고 범례로 옮긴 판단이 옳다.

CR18-7 diff 재사용은 마커 3단계를 얹고도 **유지된다**(재사용 제거 변이가 15건을 깨뜨리고,
팬 1회 3.89ms 를 단독 계측으로 확인).

**비차단 이월**: `PREF-1`(medium, `prefer` 3종 미반영 고지 — 다음 라운드 필수) ·
`SCORE-1`(low, 환금성 경계 동기화 테스트가 단방향이고 주석이 과장) ·
`UX-2`(low, 지역 목록 `/regions` 엔드포인트) · `SCORE-2`(info, `agent_ids` 메타 미보호) ·
기존 `DEPLOY-2`·`DEPLOY-3`·`REC-4`·`OPS-1`·`SEC-4`·`REC-2`·`ADM-3`·`JOB-2`.

> 배포 시 CR-025 의 `DEPLOY-2` 권고(**서버 소스 갱신 절** · **가입 열기 전 승인제 생존 확인**)는
> 여전히 유효하다 — 이번 라운드에서 해소되지 않았다.

---

## CR-027 · 2026-07-26 · POI-1 입지데이터 · LLM-1 배선 · REC-5 bbox · FIN 자금계획 (code-reviewer, herdr re-review 대행)

**판정: PASS** · 차단 **0건** · **배포 가능**
지시 `2026-07-26-code-review-7` · CR-026 이후 4개 라운드 · 미커밋 61건

### 재현

`backend` **890 passed / 63 skipped** · `frontend` **501 passed**(33 files) · typecheck 통과.
지시 수치와 일치(착수 시 693 / 358). 변이 **11종** 후 6개 파일 **바이트 단위 원복** 확인.
서버는 **조회만**(운영 DB 쓰기 0회, 실사용자 id=11 무접촉).

---

## B. LLM-1 — **PASS** (이번 라운드에서 가장 위험한 변경이라 먼저 봤다)

진짜 LLM 이 붙으면 **사용자 데이터가 처음으로 외부로 나간다.** 그래서 여기부터 검증했다.

### 비용 누수 수정 — **직접 계측으로 확인**

`CountingLLM` 으로 `complete_json` 호출을 세어 후보 수를 늘려 봤다(top_n=5):

| 후보 수 | LLM 실호출 | items |
|---:|---:|---:|
| 5 | **5** | 5 |
| 20 | **5** | 5 |
| **61** | **5** | 5 |

**후보가 61건이어도 호출은 5건.** 순위 확정 후 top_n 에만 요약을 만드는 2패스가 실제로 동작한다
("강남 61후보 → 실호출 5건" 주장과 일치). 예전 구조라면 최대 200건을 요약하고 190건을 버렸다 —
**상한이 아니라 호출 시점이 문제였다**는 진단이 정확하다.

### tripwire 를 비용 상한보다 먼저 둔 판단 — **옳다. 그리고 테스트가 그 순서를 강제한다**

`orchestrator.py:631` 에서 `assert_no_secrets` 가 돌고, 예산/회로차단은 `:636` 부터다.
판단 자체가 옳다 — **예산이 없다는 이유로 검사를 건너뛰면 상한에 걸린 날에만 방어가 사라진다.**
그런 방어는 방어가 아니다. 게다가 tripwire 는 문자열 스캔이라 비용이 사실상 0 이다.

말로만 옳은 게 아니라 **순서가 잠겨 있다**:

| 변이 | 결과 |
|---|---|
| `assert_no_secrets` 제거 | ✅ KILLED (3) |
| **`assert_no_secrets` 를 비용 상한 뒤로 이동** | ✅ **KILLED (3)** |

### HTTP 전송 본문 검사 — **설계가 옳고 자기충족적이지 않다**

`tests/test_llm_wiring.py` 가 `httpx.post` 를 가로채 **실제로 나갈 요청 본문**을 검사한다.
`FakeLLM` 이 아니라 egress 지점을 잡는 것이 맞다. 특히 좋은 점:

- `assert wire.requests, "호출이 없으면 이 테스트는 아무것도 증명하지 못한다"` —
  **호출이 없었으면 통과하지 못하게** 막아 뒀다. 내가 이 원장에서 반복해 요구해 온 바로 그 가드다.
- `extract_amounts(blob) & {CASH, INCOME}` 뿐 아니라 **콤마 표기(`f"{CASH:,}"`)까지** 원문 대조.
- 짝 테스트 `test_전송본문에_파생값은_있어도_된다` 로 **방어가 과해 근거까지 못 보내는 상태**가
  아닌지 반대 방향도 확인한다. 한쪽만 있으면 "전부 막으면 통과"가 되는데 그걸 막았다.
- `test_tripwire가_살아있다` 는 finding 에 원본을 심으면 **폴백이 아니라 호출 자체가 막히는지**를 본다.
  폴백으로 흘리면 유출이 정상 동작이 되므로 이 구분이 중요하다.

회로차단 2회·출력 900토큰(하드캡 2048)·입력 20,000자 초과 시 **자르지 않고 폐기**·4xx 재시도 없음도
확인했다. 자르면 문맥이 잘린 채 요약이 나가는데 그게 더 나쁘다 — 폐기가 맞다.

---

## D. FIN — **PASS** (계약 밖 버그를 실제로 재현하고, 수정도 재현했다)

`budget_override_krw` 반쪽 배선은 **결과가 통째로 비는** 종류라 직접 재현했다.
한도 885,710,000원 · 후보 3건 모두 12억:

| 조건 | items | 예산초과 제외 |
|---|---:|---:|
| `budget_krw` 미지정(한도 기준) | **0** | 3 |
| `budget_krw` = 15억(희망가) | **3** | 0 |

**희망가를 한도보다 높이면 조회는 통과하는데 제외 판정이 한도로 돌아 전부 잘리던** 구조가
`AnalysisContext.budget_krw` 로 닫혔다(필드 존재 확인). 변이로도 잠겨 있다 —
**`budget_krw` 를 배선에서 떼면 70건이 깨진다.** "서울 실측 50건 중 5건 소실"이라는 보고와
성격이 일치한다.

월 원리금을 **상수 없이 3중 검산**(할인계수 합 / 360회 스케줄 시뮬 / 역함수 왕복)한 것은 좋은 방식이다 —
공식을 한 번 잘못 적으면 세 방법이 같이 틀릴 확률은 낮다. 한도 초과여도 200 + 숫자 전부 제공(초과분·
binding·한도까지 받으면 얼마)은 이 원장이 요구해 온 "왜 안 되는지 말하라"와 일치한다.
희망가 하나가 세 요청(affordability·recommendations·map)에 동시 전달돼 **한 화면이 두 예산을
말하지 않게** 한 것도 옳다. PM 의 라벨 정정(`"최대 실구매 가능 X원"`)도 화면과 일치한다.

---

## A. POI-1 — **PASS** (F3 가 처음으로 동작한다)

### 적재·산출률 — 운영 DB 에서 직접 셌다

| 항목 | 실측 | 보고 |
|---|---:|---|
| park / subway / mart / hospital | 8,171 / 762 / 3,770 / 2,244 | 일치 |
| transit_plan | 34 | 일치 |
| **`poi.geom` NULL** | **0** | 좌표 100% ✅ |
| complex 전체 | 16,462 | |
| **좌표 없음(기존 결함)** | **901** | 일치 |
| 좌표 있음 | 15,561 | |

`16,462 − 901 − 27 = 15,534` → **94.36%**. 보고된 94.4% 와 일치한다.
반경 1km 안에 POI 가 하나도 없는 단지는 96 건인데, 도메인이 항목별로 다른 밴드
(`PROXIMITY_BANDS`)를 쓰므로 실제 미산출 27 과 모순되지 않는다(1km 밖·밴드 안에서 잡히는 69건).

### 전 지역에서만 드러난 결함 2건 — **두 수정 모두 옳고 도메인 계약과 일치**

**① KTX·SRT 분리** — 도메인은 `len(nearest.lines)` 로 **환승 가치**를 준다(`analysis.py:209-214`).
KTX 가 `lines` 에 섞이면 통근 환승이 아닌데 환승 가점이 붙는다. 실측으로 수정 효과를 확인했다:

| 역 | 통근 `lines` | `attrs.intercity` |
|---|---:|---:|
| **광명** | **1** | 3 (KTX 3종) |
| 수원 | 2 | 8 |
| 서울역 | 6 | 4~5 |

광명역이 통근 1개로 잡혀 **환승 가점을 못 받는다** — 보고된 결함이 실제로 닫혔다.
정보를 **버리지 않고** `attrs.intercity` 로 남긴 것도 옳다(간선 접근성은 별개 가치이고,
지금 점수에 안 쓴다는 사실이 데이터에 남는다). 변이 **"간선을 통근으로 되돌림" → KILLED (3)**.

**② 신설노선 병합** — `transit_plan` 에서 (이름, 단계) 중복 **0건** 확인. 신안산선 13중복이 닫혔다.
GTX-C 가 `계획`·`착공` 두 행인 것은 구간별 단계가 달라 **정상**이다(같은 키가 아니다).

노선 연결 739/762 = **97%** 확인. `intercity` 표시 43건.

### 변이

| 변이 | 결과 |
|---|---|
| 간선을 통근으로 되돌림(수원역 10노선 재발) | ✅ KILLED (3) |
| **응급실 미태그를 True 로(없는 응급실을 지어냄)** | ✅ **KILLED (3)** |
| `service` 기반 간선 판정 제거 | ⛔ SURVIVED — **등가 변이**(뒤의 `route=train → intercity` 폴백이 대부분을 그대로 잡는다) |

---

## 판정 요청 2 — 응급실 2.1% : **데이터 한계다(결함 아님) · 단 고지 필요**

내가 직접 세어 보니 보고보다 상황이 더 분명하다 — **세 값이지 두 값이 아니다**:

| `has_emergency_room` | 건수 | 뜻 |
|---|---:|---|
| `true` | **47** | 응급실 있음(확인됨) |
| `false` | **29** | 응급실 없음(확인됨) |
| **키 자체가 없음** | **2,168 (96.6%)** | **모름** — OSM 이 태그하지 않았다 |

**도메인은 이미 옳게 모델링돼 있다.** `models.py:82` 가 `has_emergency_room: bool | None = None` 로
**3값**이고, `analysis.py:258` 의 `(not er or p.has_emergency_room)` 에서 `None` 은 falsy 라
**모르는 병원은 점수에 넣지 않는다.** 이 방향이 맞다 — 모름을 "있음"으로 세면 없는 응급실을
지어내는 것이고, 대안(모든 병원을 동일 계산)은 **의원 하나를 종합병원과 같게** 취급해 더 나쁘다.
변이 P3(미태그를 True 로)가 **KILLED** 인 것도 이 규칙이 잠겨 있다는 뜻이다.

→ **결함이 아니라 원천 데이터 한계다.** 다만 실질적으로 infra 점수가 **마트+공원**으로 굴러가는 것은
사실이므로, WEIGHT-1 이 만들어 둔 `coverage_gap` 기계를 그대로 써서
*"생활 인프라는 현재 마트·공원까지만 봅니다 — 응급실 정보가 있는 병원이 2.1% 뿐입니다"* 를
노출할 것을 권고한다(`POI-2`, low). **점수를 바꾸라는 게 아니라 무엇을 봤는지 말하라는 것**이다.

## 판정 요청 3 — `parseBbox` 면적 상한 미포함 : **옳은 판단이다**

핵심은 **"못 읽음"과 "너무 넓음"이 다른 사실**이라는 것이다. `parseBbox` 가 넓은 bbox 에 `null` 을
돌려주면 호출부는 그것을 "bbox 없음"으로 읽고 **파라미터를 빼고** 보낸다 → 서버는 범위 제한 없이
전국을 뒤진다. **좁히려고 만든 버튼이 범위를 최대로 넓히는** 정확한 fail-open 이다.

구현이 그 구분을 지킨다: `parseBbox` 는 형식·좌표범위·`min<max` 만 보고(`bbox.ts:54-74`),
크기는 `MAX_BBOX_SIDE_DEG = 2.0` + `bboxSideDeg()` 라는 **별도 경로**로 판정해 버튼을 비활성화하고
사유를 문장으로 준다(*"지금 지도 범위(…)가 너무 넓어 검색할 수 없습니다 — 지도를 확대한 뒤…"*).
`AreaScope.test.tsx` 가 그 문구를 단언한다. 서버도 `_MAX_BBOX_DEGREES = 2.0` 으로 **독립 422** 를
낸다 — 클라이언트를 믿지 않는 이중 방어다. 소스 주석이 이 함정을 그대로 적어 둔 것도 좋다.

## C. REC-5 나머지 — **PASS**

- **SR21-4 구조적 차단 확인**: `LIKE rc || '%'` → `left(c.region_code, length(rc)) = rc`.
  변이로 LIKE 를 되돌리면 **KILLED (1)**. 와일드카드가 코드에 남을 수 없게 됐다.
- **GiST 사용을 서버 EXPLAIN 으로 재현**했다:
  ```
  Bitmap Heap Scan on complex c
    ->  Bitmap Index Scan on idx_complex_geom
          Index Cond: (geom && '…'::geometry)
  ```
  Seq Scan 이 아니다. 보고가 사실이다.
- 낡은 bbox 를 "누른 순간 고정"으로 처리하고 낡으면 경고+재잡기 — 지도가 계속 움직이는 UI 에서
  **언제의 범위인지**를 고정하는 것이 맞다.

## 판정 요청 4 — GTX 한글 음차 : **별칭 매핑을 넣지 마라(현행 유지). 단 위치가 중요하다**

실측해 보니 **두 곳의 사정이 다르다**:

| 위치 | 값 | 판단 |
|---|---|---|
| `poi.attrs.lines` (역) | **`"GTX-A"`** (수서역: `["3","수인·분당","GTX-A"]`) | 이미 정상 |
| `transit_plan.name` (신설노선) | `수도권광역급행철도에이선`·`비선`·`씨선` | 음차 |

즉 **점수에 쓰이는 역 노선명은 이미 `GTX-A` 로 정상**이고, 음차는 *계획노선 레코드의 이름*에만 있다.
원천 값을 임의로 고치지 않은 판단은 **옳다** — 수집기가 출처 문자열을 바꾸기 시작하면
"이 이름이 OSM 것인가 우리가 만든 것인가"를 아무도 답할 수 없게 된다(GEO-1 이후 이 원장이
지켜 온 원칙이다). 필요한 것은 **표시 계층의 별칭**이지 원천 변조가 아니다.
→ `POI-3`(low): 화면·검색에서 `수도권광역급행철도에이선 → GTX-A` 로 **보여줄 때만** 매핑하고
원본은 그대로 둘 것. 사용자가 "GTX" 로 검색할 길이 없는 것은 실제 불편이다.

## 판정 요청 5 — PREF-1 : **여전히 `later`. 다만 이번으로 데이터 핑계는 끝났다**

실측 확인 — **역세권·학군 중요도·최소 세대수는 그대로다**:
`buildMapQuery` 는 여전히 `area_min_m2`·`area_max_m2`·`built_after` 만 보내고,
백엔드 `prefer` 참조는 **0건**이며, `ConditionsScreen` 의 미반영 고지는 **가중치 절에만** 있다.

차단하지 않는 이유는 CR-026 과 같다(피해가 설정화면 3개 입력의 오해이고, 데이터 손상·보안·장애가
아니며, 사용자는 1인). 그리고 이번 라운드가 POI-1·LLM-1·REC-5·FIN 을 실제로 끝냈다.

**그러나 상황이 한 가지 바뀌었다.** POI-1 로 `subway` 762건이 들어와 **역세권은 이제 배선 가능하다** —
"데이터가 없어서 못 한다"가 더는 성립하지 않는다(학군은 `school_district` 0행이라 여전히 유효하고,
학구도 API 착수가 임박했으니 그때 함께 닿는다). 게다가 이번 라운드는 **동작하는 선호값(희망가)을
새로 추가**했으므로, 같은 화면에서 되는 것과 안 되는 것의 비대칭이 더 커졌다.

→ `PREF-1` 을 **medium 유지 · 다음 라운드 조건**으로 다시 둔다. 최소 조치는 여전히 **고지 5줄**이고,
학구도 작업이 이 화면을 어차피 건드린다. 다음 라운드에도 손대지 않으면 그때는 "백로그"가 아니라
**패턴**으로 보고 판정을 달리하겠다.

---

### 판정

**PASS · 배포 가능.** 차단 0건.

네 라운드 중 가장 위험한 것은 LLM-1 이었고(처음으로 사용자 데이터가 외부로 나간다) 거기를 가장
깊게 봤다. **tripwire 가 비용 상한보다 먼저 돈다는 판단은 옳고, 그 순서가 변이로 잠겨 있다.**
전송 본문 검사는 `httpx.post` 를 가로채 egress 를 직접 보고, "호출이 없으면 통과 못 한다"는
가드와 "과방어도 아니어야 한다"는 짝 테스트까지 갖췄다 — 이 원장이 요구해 온 형태 그대로다.
비용 수정도 **후보 61 → 호출 5** 로 직접 계측했다.

FIN 의 반쪽 배선은 **결과가 통째로 비는** 버그였고, 재현(0건)과 수정 후(3건)를 모두 직접 확인했다.
POI-1 은 전 지역 적재에서만 드러난 결함 2건을 잡아냈고, 광명역 통근 1노선을 실측으로 확인했다.
`parseBbox` 에 면적 상한을 넣지 않은 판단은 **옳다** — 넣었으면 좁히는 버튼이 전국 검색이 됐다.

**비차단 이월**: `PREF-1`(medium, 재확인 — 다음 라운드 조건) · `POI-2`(low, 인프라 커버리지 고지) ·
`POI-3`(low, GTX 표시 별칭) · `POI-4`(low, 서울역 등 분리 노드로 환승 가치 과소평가 — 보수적 방향) ·
기존 `SCORE-1`·`DEPLOY-2`·`DEPLOY-3`·`REC-4`·`OPS-1`·`SEC-4`·`REC-2`·`ADM-3`·`JOB-2`.

> 배포 시 CR-025 `DEPLOY-2` 는 여전히 유효하다 — **서버 소스 갱신 절**과
> **가입 열기 전 승인제 생존 확인**. 이번 라운드에서도 해소되지 않았다.
> `school` 축(가중치 0.35)이 아직 0 이라는 사실은 WEIGHT-1 의 `score_notes` 로 사용자에게 전달된다.

---

## CR-028 · 2026-07-27 · SCHOOL-1 학구도 적재 (code-reviewer, herdr re-review 대행)

**판정: PASS** · 차단 **0건** · **배포 가능**
지시 `2026-07-27-code-review-8` · CR-027 이후 1개 라운드 · 미커밋 9건

### 재현

`backend` **918 passed / 63 skipped**(890 → +28) · frontend 501 변경 없음. 지시 수치와 일치.
변이 **9종** 후 2개 파일 **바이트 단위 원복** 확인. 서버는 **조회만**(운영 DB 쓰기 0회).
`backend/docs`·`frontend/docs` 에 **아무 파일도 만들지 않았다**(커밋 훅 주의사항 준수).

> 이전 라운드의 "무키 경로 없음, 확정적 미확보" 판단이 틀렸음을 PM 이 잡아내 재착수시킨 건이다.
> **"확정적으로 없다"는 결론은 조사 범위의 한계였지 사실이 아니었다** — 이 원장이 여러 번
> 경고해 온 과잉단정의 사례이고, 스스로 뒤집은 것은 옳다.

---

### 1. ★ 거리 대체가 시작되지 않았나 — **시작되지 않았다 (실호출로 재현)**

이 앱에서 *"○○초까지 300m"* 와 *"○○초에 배정됨"* 을 섞는 것은 가장 위험한 종류의 거짓이다.
**말이 아니라 운영 DB 실호출로** 확인했다(`location_facts()` + `evaluate_location()`).

미포함 단지 6건 전수 — **한 건도 학교 이름이 붙지 않는다**:

```
#628   호반써밋양재                  in_district=False  name=None
#5038  금강(343)                    in_district=False  name=None
#5178  금강                         in_district=False  name=None
#8618  신검단중앙역금강펜테리움센트럴파크  in_district=False  name=None
#8622  검단호수공원역호반써밋           in_district=False  name=None
#9425  월드뷰                       in_district=False  name=None
   missing=['배정 초등학교 확인 불가(학구도 미포함) — 최근접 학교 거리로 대체하지 않음']
```

`assert name is None` 을 6건 모두에 걸어 통과시켰다. 담당자 보고(3건)보다 넓게 봤고 동일하다.

**비수도권**도 확인 — 부산 해운대·대전 유성 좌표에서 반경 20km 내 학구도 폴리곤 **0건**이라
`district_data_available=False` 경로로 갈린다(*"학구도 데이터 미확보 — 배정 학교를 거리로
대체하지 않음"*). **'미포함'과 '미확보'가 다른 문장으로 갈리는 것**이 중요하다 — 전자는
"우리는 아는데 여기 아니다", 후자는 "우리가 모른다"이고 사용자에게 다른 사실이다.

코드도 그 구조다(`analysis.py:143-155`): 두 경우 모두 **`fact.distance_m` 을 읽기 전에 반환**한다.
변이로 잠겨 있다:

| 변이 | 결과 |
|---|---|
| **미포함일 때 최근접 학교 이름으로 대체** | ✅ **KILLED (1)** |
| **미확보일 때도 배정을 단정** | ✅ **KILLED (2)** |

### 2. 도메인 실호출 결과 — **원 단위까지 재현**

| 단지 | 담당자 보고 | 내 재현 | 배정교 |
|---|---|---|---|
| 쎄비앙102동 | 948m | **948.058m** | 서울역삼초등학교 |
| 래미안블레스티지 | 215m | **215.334m** | 서울개현초등학교 |
| 압구정하이츠파크 | 1129m | **1128.574m** | 서울청담초등학교 |

세 건 모두 `in_district=True`. 보고가 정확하다.

### 3. 분류·산출률 — **직접 집계로 일치**

```
complex 16,462 · 좌표없음 901 · 포함 15,548 · 미포함 13
school_district 3,246행 · poi(school) 2,209행
school 축 활성화 = 15,548 / 16,462 = 94.45%
```

**901 + 15,548 + 13 = 16,462** — 한 행도 설명되지 않고 남지 않는다. 예측 94.5% 와 일치.

#### '전' 값 재구성이 적재 이전과 동일한가 — **동일하다(구조적으로 검증)**

담당자는 적재를 되돌리지 않고 `district_data_available=False` 만 되돌려 '전' 값을 만들었다.
이게 타당하려면 **그 플래그가 꺼졌을 때 school 축이 다른 입력을 전혀 안 봐야** 한다.
확인 결과 그렇다:

- `assess_school` 은 `not fact.district_data_available` 에서 **즉시 `(None, [...])` 반환** —
  `fact.distance_m`·`fact.name` 을 읽지 않는다.
- `_school_score(None)` → `None`.
- `school.distance_m` 의 유일한 다른 소비처(`analysis.py:458`)는 **건물 단위** 함수이고
  `b.school_in_district` 가 참일 때만 탄다 — 복합 단위 경로와 다르다.
- 이번 라운드가 추가한 `poi(category=school)` 2,209행은 **infra 축에 안 들어간다**
  (infra = mart·park·hospital_er, CR-027 확인). 즉 델타는 **school 축에만** 귀속된다.

→ 재구성은 school 축에 대해 적재 이전 상태와 **정확히 같은 도메인 입력**을 만든다. 방법이 옳다.
497/500(99.4%) 변동 · 평균 +0.48 · 범위 −27.6~+27.1 이라는 **양방향 분포**도
"일률 가점이 아니라 실제 변별"이라는 주장을 뒷받침한다(일률 가점이면 분산이 0에 가까워야 한다).

### 4. 원천 결함 2건 — **둘 다 옳고, 비대칭도 옳다**

**(가) 완전 중복 행 접기 — 타당하다.** `ON CONFLICT DO UPDATE` 는 한 문장에서 같은 대상 행을
두 번 건드리면 `cannot affect row a second time` 로 **문장 전체가 깨진다.** 배치 안에서 먼저
접는 것이 정석이고 `poi_loader` 와 같은 방식이라 일관적이다. **`ON_ERROR_STOP` 덕에 전부
롤백돼 가짜 성공이 없었다**는 점이 중요하다 — 이 원장이 `DEPLOY-1` 에서 요구했던 바로 그 설정이
실제 사고에서 값을 했다. 변이 **"접기 제거" → KILLED (1)**.

**(나) 애매한 학구ID 폐기 vs 동명 다중파트 병합 — 이 비대칭은 옳다.**
겉보기엔 "어떤 중복은 합치고 어떤 중복은 버린다"라 자의적으로 보이지만, 기준이 하나다 —
**모호성이 데이터로 해소되는가**:

| 상황 | 뜻 | 처리 | 근거 |
|---|---|---|---|
| 같은 학구ID · **같은 학교명** | 한 구역이 여러 폴리곤으로 쪼개짐(강·철도로 분단) | **MultiPolygon 병합** | 원본의 뜻이 그것이다. 정보 손실 0 |
| 같은 학구ID · **다른 학교명**(`고덕함박초`/`현민초`) | ID 가 서로 다른 두 구역에 재사용됨 | **버림** | 어느 폴리곤이 어느 학교 것인지 **알 방법이 없다** |

후자에서 하나를 고르면 **배정을 지어내는 것**이고, 이 앱이 절대 하면 안 되는 일이다.
버린 구역의 단지는 '미포함'이 되어 도메인이 배정을 단정하지 않는다 — **fail-closed** 이고
`reb.py` 의 "애매하면 매칭하지 않는다"와 일관된다. 변이 **"애매한 ID 를 하나 골라 쓴다" → KILLED (1)**.

### 5. 그 밖의 검증

| 항목 | 결과 |
|---|---|
| **자연키 `kesi:{학구ID}/{학교ID}`** | **실측으로 필요성 입증** — `school_district` 3,246행 중 DISTINCT 학구ID 는 **2,652**, **공동학구(학구ID 하나에 학교 2개 이상)가 462건**이다. 학구ID 단독으로는 키가 성립하지 않는다는 판단이 데이터로 확인된다. `source_ref` 중복 **0건** |
| **중·고 차단** | `ELEMENTARY` 필터가 파싱(`parse_link_csv`)·위치(`parse_location_csv`) **두 단계**에 걸려 있고 **양쪽 다 변이로 KILLED**. 위험(=`_SCHOOL_SQL` 이 학교급 구분 없이 최근접 1건을 골라 **가장 가까운 중학교가 '배정 초등학교'로 보고**됨)이 docstring 에 정확히 적혀 있다 |
| **M1 shx 워드→바이트 ×2** | ✅ **KILLED (2)** — "합성 shapefile 에 레코드 2개를 둬야 잡힌다(첫 레코드는 ×2 없이도 우연히 읽힌다)"는 설명대로, 실제로 잡힌다 |
| shp/shx/dbf 누락 검사 제거 | ✅ KILLED (1) |
| `achievement_pct` NULL 유지 | 옳다. 초등은 국가수준 평가 대상이 아니고, 출처·기준연도 없는 수치는 쓰지 않는다는 기존 규칙(`analysis.py:172-178`)과 일관 |
| 멱등 3회 | ⚠️ **내가 재현하지 못했다** — 로더 실행은 운영 DB **쓰기**라 지시(조회만)에 따라 돌리지 않았다. 대신 기전을 정적 확인했다: 자연키 UNIQUE(012) + `ON CONFLICT ... DO UPDATE` + 배치 내 접기. "2·3차 신규 0 / 갱신 3,246" 은 이 구조에서 나오는 결과와 정합적이다. **실행 재현이 아님을 명시해 둔다** |

#### stale 을 세기만 하고 지우지 않는 판단 — **옳다. 지우는 쪽이 더 위험하다**

핵심은 **"학구 폐지"와 "원천이 반쪽만 배포됨"을 구분할 수 없다**는 것이다.

- 지우면: 원천이 일부만 배포된 날 **배정이 광범위하게 사라진다.** 학군은 이 제품의 핵심 축이고
  (school 가중치 0.35) 사용자는 어제 되던 것이 오늘 '확인 불가'가 되는 것을 본다.
- 안 지우면: 실제로 폐지된 구역의 단지가 낡은 배정을 받는다.

두 번째가 덜 나쁘다. **구역 재조정은 같은 `kesi:{학구ID}/{학교ID}` 를 UPDATE 하므로 stale 을
만들지 않는다** — stale 은 ID 자체가 배포본에서 사라질 때만 생기고, 그건 폐지이거나 부분배포다.
게다가 낡은 행은 **`district_as_of`(기준연도)를 함께 들고 있고** `assess_school` 이 그 값을
결과에 실으므로 완전한 침묵은 아니다. 원장(`ingest_log`)에 *"이번 배포분에 없는 옛 행 N"* 이
기록되는 것도 맞다.

→ **`SCHOOL-2`(low)**: 다만 stale 이 **0 이 아닐 때** 로그 한 줄로만 남으면 아무도 안 본다.
`verify_school_district.py` 가 stale > 0 이면 **경고로 드러내고** 사람이 폐지/부분배포를
판정하도록 할 것. 지금은 첫 적재라 stale 0 이므로 실동작 확인은 다음 배포분에서 가능하다.

---

## 함께 판정 — `PREF-1` 3회 연속 이월

실측 확인: **아무것도 바뀌지 않았다.** `buildMapQuery` 는 여전히 `area_min_m2`·`area_max_m2`·
`built_after` 만 보내고, 백엔드 `prefer` 참조는 **0건**이며, `ConditionsScreen` 의
"아직 반영되지 않습니다" 고지는 **여전히 가중치 절 하나뿐**이다.

CR-027 에서 나는 *"다음 라운드에도 손대지 않으면 패턴으로 보고 판정을 달리하겠다"* 고 썼다.
**그 말을 이번에 집행하지 않는다. 이유를 밝힌다.**

- 차단은 **결과로 정당화되어야지 내가 앞서 한 경고로 정당화되어선 안 된다.** 피해는 3회 내내
  같다 — 설정 화면 3개 입력에 대한 오해이고, 데이터 손상·보안·장애가 아니며, 추천 결과 자체는
  여전히 정확하고 `score_axes`·`score_notes` 로 무엇이 반영됐는지 정직하게 표기된다.
- 여기서 차단하면 **사용자가 API 승인까지 받아 온 학구도 기능이 라벨 한 줄 때문에 미뤄진다.**
  그 거래는 사용자에게 손해다.
- 경고를 반복하는 것 자체가 조건을 값싸게 만든다는 지적은 옳다. 그래서 **"다음엔 진짜"라는 말을
  더 하지 않겠다.** 대신 아래로 좁힌다.

**다만 이번 라운드로 성격이 한 가지 나빠진 것은 사실이다.** school 축이 0% → **94.45%** 로 살아나면서,
`weights.location`(학군 포함, **동작함**)과 `prefer.school_district`(학군 중요도 0~5, **미동작·무고지**)가
같은 화면에서 **둘 다 "학군 중요도"로 읽히는데 하나만 동작한다.** 셋 중 이것이 가장 오도적이다.

→ `PREF-1` 을 **medium 유지**하되 요구를 **최소 한 줄**로 좁힌다:
`prefer.school_district` 슬라이더 옆에 *"이 값은 아직 순위에 반영되지 않습니다 — 학군 비중은
위 '무엇을 더 중요하게 볼까요'에서 조절됩니다"*. 프론트를 다음에 건드릴 때 **같이** 넣으면 된다.
역세권·세대수는 그다음이다.

## 함께 판정 — `road_segment` 0행

`crosses_main_road` 를 NULL 로 두는 현재 동작은 **옳다**(모르는 것을 False 로 쓰면 "대로를 안 건넌다"는
없는 판정이 된다). 담당자 말대로 **이제서야 의미가 생긴 것도 맞다** — `_school_score` 의
`crosses_main_road` 감점(−15)은 **배정이 확인된 뒤에만** 타는데, 그 전제가 94.45% 로 채워졌다.

→ **다음 라운드 필수는 아니다.** 결함이 아니라 **미구현 기능**이고 NULL 처리가 정직하다.
가치는 분명하므로(통학로 안전은 학군 판단의 실질 요소) **우선순위 높은 다음 후보**로 둔다.
`SCHOOL-3`(low)로 등재한다.

---

### 판정

**PASS · 배포 가능.** 차단 0건.

이 라운드에서 가장 중요한 것은 **"가까움"과 "배정됨"을 섞지 않는 것**이었고, 그것을 문서가 아니라
**운영 DB 실호출로** 확인했다 — 미포함 6건 전수에서 학교 이름이 붙지 않고, 미포함·미확보가
서로 다른 문장으로 갈린다. 두 경로 모두 `distance_m` 을 **읽기 전에** 반환하며, 대체를 시도하는
변이 2종이 모두 죽는다. 보고된 실호출 3건도 소수점까지 재현됐고, 분류 4종(901/15,548/13/0)은
16,462 에 정확히 떨어진다.

원천 결함 처리도 옳다. 특히 **애매한 학구ID 를 버리고 동명 다중파트는 합치는 비대칭**은 자의적이지
않다 — 기준은 "모호성이 데이터로 해소되는가" 하나이고, 해소되지 않으면 배정을 지어내지 않는다.
공동학구 **462건**이 실제로 존재하므로 자연키에 학교ID 를 넣은 판단도 데이터로 입증된다.
`stale` 을 지우지 않는 선택은 더 나쁜 실패(부분배포로 배정 전멸)를 피하는 쪽이라 지지한다.

**미검증을 명시한다**: 멱등 3회는 **재현하지 못했다**(로더 실행 = 운영 DB 쓰기). 기전만 정적 확인했다.

**비차단 이월**: `PREF-1`(medium, 요구를 학군 슬라이더 고지 한 줄로 축소) ·
`SCHOOL-2`(low, stale>0 을 verify 스크립트가 경고로 드러낼 것) · `SCHOOL-3`(low, road_segment) ·
기존 `POI-2`·`SCORE-1`·`DEPLOY-2`·`DEPLOY-3`·`REC-4`·`OPS-1`·`SEC-4`·`REC-2`·`ADM-3`·`JOB-2`.

> 배포 시 `DEPLOY-2` 는 **네 라운드째** 열려 있다 — **서버 소스 갱신 절**과
> **가입 열기 전 승인제 생존 확인**. 이번엔 마이그레이션 **012** 도 손수 적용 대상이고,
> 절차서에 012 절이 추가돼 테스트를 통과한 것은 확인했다.

---

## CR-029 · 2026-07-27 · 병렬 4작업 통합 리뷰 — A 조건반영 · B 중고학구도 · C 재건축 · D 우측패널

**판정: FAIL** · 차단 **3건** · **배포 불가**
지시 `2026-07-27-code-review-9` · CR-028 이후 1개 라운드 · 미커밋 63건(추적 40 + 신규 23)

### 재현

`backend` **1,064 passed / 76 skipped** · `frontend` **611 passed (38 files)** · `npm run build` 성공.
지시가 말한 "1,064~1,137"의 **하한과 정확히 일치**한다(상한은 재현되지 않음 — 76건은
`needs_db` 로 로컬 Docker 부재 때문이며 그 자체는 정상).

변이 **21종**(백엔드 15 · 프론트 6) 실행 후 모든 파일 원복 확인.
`backend/docs`·`frontend/docs` 에 아무 파일도 만들지 않았다.

### 0. 병렬 통합 지점 — **훼손 없음**

`app/repositories/postgis.py` 3자 동시 편집을 전 diff 로 확인했다. **충돌 없음**:
A(`_AREA_MATCH_SQL`/`_BUILT_MATCH_SQL`/`_HOUSEHOLDS_MATCH_SQL`/`candidate_scope_stats`) ·
B(`_SCHOOL_SQL`/`_DISTRICT_AVAILABLE_SQL`/`_fetch_school`/`_BUILDINGS_SQL`) ·
C(`redevelopment_for_complex`) 가 서로 다른 영역에 있고 파라미터 이름도 겹치지 않는다.
과거 `AmbiguousParameter` 사고 패턴(`CAST(:x AS numeric)` 양쪽 필요)은 A 의 신규 SQL
전부에서 지켜졌다 — `CAST(:area_min AS numeric) IS NULL` 과 비교 양변 모두 캐스팅돼 있다.
`app/agents/orchestrator.py` 의 A(3 hunk)·C(다수) 병합도 정상이다.
마이그레이션 013·014 는 번호가 순차이고 둘 다 `IF NOT EXISTS`/카탈로그 확인으로 재실행
가능하다. `DEPLOY.md` 에 014 적용 절이 추가돼 있다.

---

### ⛔ 차단 1 — 추가분담금 금액이 **LLM 요약 경로로 그대로 새 나간다** (C, high)

담당자 주장: *"추가분담금 3중 방어(스키마 CHECK · 모델에 칸 없음 · 런타임 assert)"*.
**LLM 경로에는 방어가 하나도 없다.** 실행으로 재현했다.

`assert_no_cost_estimate` 호출부는 두 곳뿐이다 — `domain/redevelopment/analysis.py:394`
(도메인이 만든 문장)과 `agents/orchestrator.py:538`(Finding). 그런데 사용자 카드에 실제로
찍히는 `headline`/`why`/`why_not`/`next_actions` 는 `portfolio_summary()` 가 만든
**LLM 출력**이고(`orchestrator.py:794-800`), 그 경로에는 검사가 없다.

FakeLLM 으로 재현:

```
headline     : 조합설립 단계 재건축 — 추가분담금 약 1.2억 원 예상
why_not      : ['조합원 추가분담금이 세대당 1억 2천만 원 수준으로 추정됩니다']
next_actions : ['추가분담금 규모는 조합 사무실…에서 직접 확인하세요 — 공개 데이터에 없습니다.',
                …, '분담금 2억 원을 감안해 자금계획을 세우세요']
summary_basis: llm
```

같은 카드가 **"공개 데이터에 없으니 직접 확인하라"와 "1억 2천만 원"을 동시에 말한다.**
사용자는 숫자를 읽는다. `test_redevelopment.py` 의 세 절대 규칙 중 ①("추가분담금 금액은
**어떤 경로로도** 출력되지 않는다")이 그대로 깨진다.

게다가 프롬프트가 **추정 재료를 직접 공급한다**. `llm.calls[0]["user"]` 검사:

```
프롬프트에 '건립 예정' 세대수    : True
프롬프트에 '1,588가구'          : True
프롬프트에 '2,300세대'          : True
시스템 프롬프트에 분담금 금지 지시 : False   ← PORTFOLIO_SYSTEM 6개 규칙에 없다
```

기존 테스트가 못 잡는 이유: `test_분담금_직접확인_안내가_추천_카드까지_도달한다` 는
`llm=None` 으로 돌아 **규칙 기반 폴백만** 검사한다. 폴백 문장은 이미 도메인 assert 를
통과한 것이라 구조적으로 통과할 수밖에 없다 — 이 방어의 실제 구멍은 검사 대상 밖이다.

**통과 조건**

1. `portfolio_summary()` 반환 직전에 `assert_no_cost_estimate(headline, *why, *why_not, *next_actions)`.
   적발 시 예외로 추천 전체를 죽이지 말고 **`_fallback_summary` 로 강등 + notes 고지**
   (LLM 실패 처리와 같은 등급으로).
2. `PORTFOLIO_SYSTEM` 에 절대 규칙 추가: "추가분담금·부담금 **금액**을 쓰지 마세요.
   세대수 증가율로 방향만 말하세요."
3. FakeLLM 이 금액을 뱉는 회귀 테스트. `llm=None` 만으로는 이 방어를 증명할 수 없다.

---

### ⛔ 차단 2 — 사용자 제보 버그의 **호가 경로**에 회귀 테스트가 없다 (A, medium-high)

`tests/test_condition_reach.py` 머리말 22행이 이렇게 주장한다:
*"후보 조립의 면적 판정을 지우면 → test_증명[area_filters_candidates]"*. **거짓이다.**

변이 M4 — `recommend.py::_assemble_candidates` 의 호가 분기에서

```python
if not conditions.area_ok(area):
    out.drop("area" if conditions.area_known(area) else "area_unknown")
    continue
```

를 통째로 삭제 → `test_condition_reach.py` **전체 초록**(SURVIVED).

원인: 이 파일의 `_seed()` 는 기본이 `listings=()` 라 **모든 시나리오가 실거래 분기**
(`kept = [...]`)만 탄다. "혼합단지"(59.9+84.97)조차 실거래로만 만들어져 있어 호가 분기는
한 번도 실행되지 않는다.

같은 이유로 변이 M6 — `FilterConditions.area_ok` 의 미상 처리를
`return False` → `return True` 로 뒤집어도 **SURVIVED**. 인메모리 리포지토리가 자기
`_area_ok` 로 단지 단위에서 이미 걸러 버려, 도메인 가드가 판정에 관여하는 상황이
테스트에 존재하지 않는다. `test_면적_미상_후보는_통과시키지_않고_건수를_말한다` 도
결과는 맞지만 그 결과를 만든 것은 리포 필터이지 검사 대상 가드가 아니다.

코드 자체는 **오늘은 옳다**(직접 프로브로 확인):

```
호가 59.9 + 84.97 한 단지, 조건 55~62 → 후보 [59.9], dropped {'area': 1}
호가 59.9 + 면적 0  한 단지, 조건 55~62 → 후보 [59.9], dropped {'area_unknown': 1}
```

문제는 이 동작이 **무방비**라는 것이다. 지금은 운영 호가가 0건이라 실거래 분기만 도는데,
포털 매물 수집이 붙는 순간 호가 분기가 주 경로가 된다 — 그때 이 줄이 리팩터링으로
사라지면 **사용자가 제보한 그 버그가 그대로 재발**하고 아무도 모른다.

**통과 조건**: `PROOFS["area_filters_candidates"]` 에 **호가가 있는 혼합 면적 단지**
케이스 추가(한 단지에 59.9·84.97 호가) + 면적 0/None 호가 케이스. 두 변이(M4·M6)가
KILLED 되는 것을 확인할 것.

---

### ⛔ 차단 3 — 오매칭 가드의 하중 부재(긴이름 우선)가 **무테스트** (C, medium)

지시가 물은 "가드가 충분한가 · 다른 부분문자열 충돌을 찾아보라"에 대한 답이다.

`_boundary_ok` 는 **앞 글자 하나만** 본다. 그리고 `_ALLOWED_PREV = ("구","시","군","면","읍")`
을 허용한다. 즉 **'면'+'목동'** 조합은 경계 검사를 통과한다. '면목동'(중랑구)이 '목동'
(양천구)으로 잘못 읽히는 것을 막는 것은 `_find_dong_spans` 의
`sorted(names, key=len, reverse=True)` **정렬 하나뿐**이다.

그 정렬을 뒤집어 실증했다(실제 법정동 색인 사용):

```
sorted(names, key=len)  ← 짧은 이름 우선
  '면목동 69-14' (서울/중랑구) → status=ok  ('목동','1147010100')=양천구 목동  scope=sido_unique
```

**중랑구 정비구역이 양천구 필지에 확정 매칭된다.** 상봉13구역→동작구 본동과 같은 계열이고,
`match_method='pnu_exact'` 로 저장돼 화면에는 "대표지번 정확일치"로 보인다.
그리고 이 변이로 **백엔드 1,064건 전체가 통과했다**(alphabetical `sorted(names)` 변이도 통과).

낱말경계 자체는 잘 작동한다 — `'망우본동 461-12'` → `unknown_dong` 으로 올바르게 거절되고
(M10: `_boundary_ok` 제거 시 `test_낱말_꼬리로_다른_구의_법정동을_잡지_않는다[면목본동69-14-중랑구]`
KILLED), `'신정동'`/`'정동'` 은 앞 글자 '신' 이 비허용 한글이라 경계 검사만으로 막힌다.
막지 못하는 것은 **접두가 구/시/군/면/읍인 부류**뿐이고, 거기에는 테스트가 없다.

**통과 조건**: 긴이름 우선 규칙을 고정하는 테스트. '면목동'/'목동' 은 둘 다 실재하는
서울 법정동이라 자기충족이 아닌 사례로 쓸 수 있다.

---

### 각 작업 주장 검증 — 나머지는 **사실로 확인**

**A(조건 반영)**

| 주장 | 검증 |
|---|---|
| "프론트 타입에서 키를 파싱해 대조" | **사실.** M1(프론트 `Preferences.prefer` 에 `balcony_expanded` 추가) → `test_UI가_수집하는_조건은_모두_서버_레지스트리에_있다` KILLED |
| "파싱이 0개면?" | **실패한다.** M2(prefer 블록 비우기) → 같은 테스트 KILLED. `missing` 이 아니라 **`stale` 검사**(레지스트리에만 있고 화면엔 없는 키)가 잡는다 — 가드가 있는 척이 아니다 |
| `use_saved_conditions:false` | **끈다.** M5(스위치 무력화) → `test_저장된_조건을_이번만_끌_수_있다` KILLED |
| `_avoid_tokens` 꺼진 값 버그 회귀 | **있다.** M3(수정 되돌리기) → `test_증명[avoid_excludes_and_off_restores]` KILLED |
| "면적 미상은 버리고 버린 수를 notes 로" | 숫자 계산은 옳다. `built_dropped ⊇ built_unknown` 이고 문구가 "이 중 N개"라 이중계산 없음. 인메모리·PostGIS 두 구현의 집계 규칙도 일치. **다만 차단 2** |

**B(학구도)** — 초등 회귀 없음 주장은 **구조적으로 성립**한다. 커밋된(013 이전)
`ingest/school_zone.py:547` 이 이미 `attrs["level"]` 을 적고 있었으므로 013 의 backfill
(`SET school_level = p.attrs->>'level'`)은 빈 UPDATE 가 아니다. 다만 검증 방법 자체는
지시가 의심한 대로 **약하다** — `verify_school_district.py` 의 "전"은
`district_data_available=False` 로 만든 **모의 상태**이지 013 이전 SQL 이 아니다. 즉 도메인
출력의 동등성은 보였지만 `_SCHOOL_SQL` 이 같은 초등학교를 돌려주는지는 그 스크립트로
증명되지 않는다. 급 필터 변이(M7·M8)는 로컬에서 SURVIVED 인데, 이는 해당 가드가
`needs_db`(`test_postgis_repo.py:1274` "★ 변이 가드")에 있어 76건 skip 에 포함되기
때문이다 — 가드는 존재하나 **이번 라운드에서 실행되지 않았다**.

**C(재건축)** — 비단조 곡선은 **사실**: `STAGE_PROFILE[invest]` 가 사업시행 85 정점 →
관리처분 65 → 이주 55 → 착공 50 → 준공 30 이고, M11(관리처분 95·이주 96 으로 단조화) →
`test_투자_프로파일은_비단조다` KILLED. 미매칭 `score=None` 도 M13 으로 KILLED 확인,
`build_axis_signals` 가 축을 총점에서 빼고 재정규화한다(0 으로 새는 경로 없음).
경기도 미커버 고지는 `NO_REDEV_REASON`·`AXIS_SPECS[redevelopment].coverage_gap`·
파이프라인 notes 세 곳에서 나가고 프론트 `scoreCoverage` 가 노출한다 — 확인.

**D(프론트)** — 변이 **6/6 KILLED**. 이번 라운드에서 가장 튼튼하다.
가격 미상→"예산 내"(D1) · 재건축 `available:false`→"아님"(D2) · 세대수 null→"대단지 아님"(D3) ·
태그 unknown 통과(D4) · 식별자 제거 해제(D5) · 숨긴 건수 미보고(D6) 전부 잡힌다.
"순위 재계산 안 함"·"반영률 헤드라인은 안 접힌다"(`ScoreCoverage.tsx:34` 가 `<details>`(40행)
**바깥**)도 코드로 확인.

---

### 판단을 요구받은 항목

**공동학구 21% — 점수는 두고 문구만 바꾼 선택은 옳다.**
근거 셋. ① 점수원이 되는 후보 집합이 **그 구역에 연계된 학교**로 한정돼 있다
(`_school_group_score`) — "아무 학교까지의 거리"가 아니라 "배정될 수 있는 학교 중 최근접"
이므로 배정 주장이 아니라 접근성 사실이다. ② 문구가 더 이상 배정을 단정하지 않는다
(`analysis.py:221` "공동학구 — 연계 초등학교 N곳 중 최근접 학교이며 배정 학교를 단정할 수 없음").
③ 점수를 깎거나 None 으로 두면 **공동학구라는 데이터 속성 때문에** 21% 를 벌주게 되는데,
선택지가 여럿인 것은 대체로 불리한 사실이 아니고, None 은 가중치 0.35 축의 신호를
21% 구간에서 통째로 날린다. 지금 선택이 정보 손실이 가장 적다.
급별 가중치 근거도 코드에 남아 있다(`analysis.py:81-90` — 초등 후보 1곳 79% · 중 4.46 · 고 14.39,
"성적이 좋아서가 아니라 우리가 아는 것이 가장 확실해서"). 다만 값을 뒤집어도
(0.55/0.30/0.15 → 0.15/0.30/0.55) 전 스위트가 통과한다(M9 SURVIVED) — 순서를 고정하는
테스트가 없다(`SCHOOL-4`, 비차단).

**성능 +0.9초 — 차단 사유 아니다.** 추천은 `POST → 202 → 폴링`인 비동기 잡이라 사용자가
막히지 않는다. 다만 회수할 몫이 크다: `_fetch_school` 이 `_SCHOOL_SQL` 결과와 무관하게
**항상** `_DISTRICT_AVAILABLE_SQL` 을 실행하고, 행이 있으면 그 값을 **버린다**
(`postgis.py:1469-1513`, `district_data_available=True` 로 하드코딩). 급 3종 × 단지당
= 불필요한 공간쿼리 3회다. `if row is None` 안으로 옮기면 9.3→24.3ms 증가분의 상당 부분이
사라진다(`PERF-1`, 비차단·권장).

---

### 변이 검증 요약 (21종)

| 변이 | 결과 |
|---|---|
| M1 프론트에 조건 키 추가 | **KILLED** |
| M2 프론트 prefer 블록 비우기(키 0개) | **KILLED** (stale 검사) |
| M3 `_avoid_tokens` 꺼진 값 무시 되돌리기 | **KILLED** |
| M4 호가 분기 면적 판정 삭제 | ⛔ **SURVIVED** → 차단 2 |
| M5 `use_saved_conditions` 무력화 | **KILLED** |
| M6 `area_ok` 미상을 통과로 | ⛔ **SURVIVED** → 차단 2 |
| M7/M8 학교급 필터 제거 | SURVIVED (needs_db 76 skip — 가드는 존재) |
| M9 급별 가중치 뒤집기 | SURVIVED (비차단 `SCHOOL-4`) |
| M10 `_boundary_ok` 제거 | **KILLED** |
| M11 단계 점수 단조화 | **KILLED** |
| M12 분담금 정규식 무력화 | **KILLED** |
| M13 미매칭 score 0 으로 | **KILLED** |
| M14 긴이름 우선 정렬 제거(alphabetical) | ⛔ **SURVIVED** |
| M14b 짧은이름 우선 정렬 | ⛔ **SURVIVED + 실제 오매칭 재현** → 차단 3 |
| D1~D6 프론트 6종 | **6/6 KILLED** |

자기충족 테스트는 **발견되지 않았다**. 값을 그대로 assert 하는 패턴 대신 켠/끈 대조가
일관되게 쓰였고(`test_condition_reach.py` Part 2), C 는 운영 실측 문자열
('망우본동461-12' 등)을 그대로 쓴다. 문제는 자기충족이 아니라 **경로 미도달**(차단 2)이다.

### 비차단 이월

`PERF-1`(medium, `_DISTRICT_AVAILABLE_SQL` 불필요 실행 3회/단지) ·
`SCHOOL-4`(low, 급별 가중치 순서 고정 테스트 부재) ·
`SCHOOL-5`(low, 013 초등 동등성을 SQL 레벨에서 재확인 — 현재 검증은 도메인 모의) ·
`COND-1`(low, `min_households` 가 추천에만 있고 `/map/complexes` 에는 없다 — 지도엔 보이는데
추천엔 안 나오는 단지가 생긴다. 이번에 고친 결함의 방향만 반대인 거울상) ·
`FE-PLAIN-1`(low, `plainText` 가 `(GTX-A)`·`(D-line)` 을 지운다. 현재 적용 지점
(missing·coverage_gap·score_notes)에는 그런 문자열이 없어 실피해는 없으나 주석의
"정상 표기는 건드리지 않는다"는 하이픈 고유명사에 대해 참이 아니다. 중첩 괄호
`A(B(C-d))` → `A(B)`) ·
`REDEV-W1`(low, 가중치를 하나도 저장하지 않은 사용자에게는 재건축 기본 0.15 가 주입되지
않는다 — `normalize_weights` 의 `total <= 0` 조기 반환. 의도로 보이나 "재건축을 반영한다"는
말이 참인 범위가 제한된다) ·
기존 `PREF-1`·`SCHOOL-2`·`SCHOOL-3`·`POI-2`·`SCORE-1`·`DEPLOY-2`·`DEPLOY-3`·`REC-4`·
`OPS-1`·`SEC-4`·`REC-2`·`ADM-3`·`JOB-2`.

> 차단 3건 중 **1건(LLM 분담금)만이 제품 결함**이고, 2·3 은 "동작은 맞으나 그것을 지키는
> 테스트가 없다"이다. 그럼에도 차단으로 둔 이유는 둘 다 **이번 라운드에서 담당자가
> 명시적으로 '방어했다'고 보고한 항목**이고, 그 보고를 근거로 다음 사람이 안심하고
> 그 줄을 지울 수 있기 때문이다. 지키지 못하는 방어를 지킨다고 적는 것이 이 프로젝트에서
> 가장 비싼 실패다.


## CR-030 · 2026-07-27 · CR-029 차단 3건 재검증 + 게이트 수정·P0 토큰 신규분

**판정: FAIL** · 차단 **1건**(CR-029 차단 1의 **부분 해소**) · **배포 불가**
CR-029 차단 2·3 은 **해소 확인**. 미커밋 88건.

### 재현 — 주장 숫자 전부 일치

| | 주장 | 실측 |
|---|---|---|
| backend | 1,092 / 76 skipped | **1,092 passed / 76 skipped / 0 failed** (junitxml 1,168−76) |
| frontend | 656 / 39 files | **656 passed / 39 files** |
| build · tsc | ok | **둘 다 exit 0** |

프론트 증가분 611→656(+45) · 38→39(+1) 은 신규 `tokens.contrast.test.ts` 45건과 정확히 일치한다 —
**기존 38개 파일의 건수는 하나도 변하지 않았다.** `vite.config.ts` 의 `test.css.include: [/tokens\.css/]`
가 다른 테스트의 전제를 건드리지 않았다는 뜻이다(`?raw` 임포트가 빈 문자열이면 첫 단언
`rootBlocks.length === 2` 가 먼저 깨지므로 조용한 통과도 불가능하다).

변이 11종 실행 · 전 파일 md5 원복 확인 · `git status` 88건 불변(프로브 잔여물 0).

---

### ✅ 해소 1 — CR-029 차단 2(호가 경로 무방비)

내가 살렸던 변이 2종을 **그대로 다시 넣어** 실행했다.

| 변이 | CR-029 | CR-030 |
|---|---|---|
| M4 `recommend.py:673-675` 호가 분기 면적 판정 3줄 삭제 | SURVIVED | **KILLED** — `test_증명[area_filters_candidates]` `AssertionError: [59.9, 59.9, 0.0, 84.97, 59.9, 59.9]` |
| M6 `conditions.py:323` 미상 처리 `False`→`True` | SURVIVED | **KILLED** — `AssertionError: [59.9, 59.9, 0.0, 59.9, 59.9]` |

담당자의 진단이 맞았다 — 한 단지 안에 **맞는 호가와 안 맞는 호가를 섞어야** 인메모리 repo 의
`_area_ok` 가 단지를 통과시키고 도메인 가드가 실제 판정자가 된다. `호가혼합단지`(59.9+84.97)와
`호가면적미상단지`(59.9+0.0) 시드가 정확히 그 상황을 만든다. 기준선 단언
(`0.0 in _areas(wide)`)이 함께 들어가 있어 "조건 없이도 0㎡가 안 나오는" 우연한 통과도 막힌다.

### ✅ 해소 2 — CR-029 차단 3(오매칭 가드)

두 겹 모두 하중을 받는다. 실행 확인:

| 변이 | 결과 |
|---|---|
| 어간 조건 `idx >= 2 and _is_hangul(text[idx-2])` → `True` | **KILLED** — `test_행정구역_접미사_예외는_어간이_있을_때만_허용된다` 가 `면목동 69-14` 를 `1147010100`(양천구 목동)으로 읽어 실패 |
| `by_head` 버킷 정렬을 짧은이름 우선으로 | **KILLED** — `test_법정동_구간_찾기는_이름_목록_순서에_의존하지_않는다` 가 **5개 파라미터 전부**에서 실패 |

**다른 우회로를 찾지 못했다.** 실재 서울·인천 법정동 21개로 색인을 만들어 직접 프로브했다.

* 정탐 13건 전부 정상: `양천구목동903` · `중랑구면목동69-14` · `금천구시흥동810` ·
  `중구정동1-1` · `광진구구의동245` · `구로구구로동100` · `남동구구월동1129` 등 —
  **접미사 뒤 어간이 있는 실주소는 하나도 막히지 않는다.**
* 오매칭 시도 전부 거절: `망우본동461-12` · `중계본동30-3` · `면목본동 69-14` → `unknown_dong`.

**오탐도 찾지 못했다.** 어간 조건이 막는 것은 `idx==1`(문두 한 글자 뒤) 또는 `text[idx-2]` 가
한글이 아닌 경우뿐인데, 한국 행정구역명은 접미사 앞에 반드시 한글 어간이 최소 1자 있다
(가장 짧은 자치구가 '중구'·'동구'로 2자). `제1구목동` 류는 어간 조건 이전에 이미
`_boundary_ok` 의 일반 규칙(앞 글자가 비허용 한글)에 걸리던 형태다.
위치 기준 최대일치는 정렬 방식보다 **엄격하거나 같으므로** 새 오매칭을 만들 수 없다.

---

### ⛔ 차단 1 (CR30-1, high) — LLM 분담금 방어가 **가장 그럴듯한 문장을 못 막는다** · 그리고 **오탐이 있다**

**구조는 옳게 고쳤다.** 검사가 `portfolio_summary()` 반환 직전이라는 자리 선택,
예외가 아니라 폴백 강등, `budget.cost_blocked` 카운트와 notes 고지, `PORTFOLIO_SYSTEM`
규칙 7, `must_verify` 의 도메인 assert 편입, 대조군 테스트 — 전부 맞는 조치다.
검사를 지우면 회귀가 죽는 것도 확인했다(`orchestrator.py:834` 제거 → 새 테스트 KILLED).

문제는 **판정 규칙**이다. `_COST_AMOUNT_RE` 는 분담금류 낱말과 금액이
**같은 문장 안에서 30자 이내**일 때만 잡는다. FakeLLM 으로 실파이프라인
(`run_mvp_pipeline`)을 돌려 **추천 카드 최종 출력**을 확인했다:

```
차단(폴백)   basis=fallback  고지=True   원문(CR-029 재현)               ← 막힌다
★ 금액 유출  basis=llm       고지=False  우회 C(문장 분리)
★ 금액 유출  basis=llm       고지=False  우회 E(30자 초과 거리)
★ 금액 유출  basis=llm       고지=False  우회 B('부담' — '금' 없음)
★ 금액 유출  basis=llm       고지=False  우회 K('분담액')
정상 채택    basis=llm       고지=False  정상(대조군)                    ← 폴백 안 함(옳다)
차단(폴백)   basis=fallback  고지=True   오탐 후보(가격+분담금 한 문장)   ← ★ 오탐
```

유출된 카드(우회 E)의 실제 문장:

```
why_not      : ['추가분담금은 조합 내부 자료라 확정할 수 없으나 업계에서는
                통상 1억 2천만 원 정도로 봅니다']
next_actions : ['추가분담금 규모는 조합 사무실·정비사업 정보몽땅에서 직접 확인하세요
                — 공개 데이터에 없습니다.']
summary_basis: llm      notes 의 폐기 고지: 없음
```

**CR-029 가 차단한 상태와 글자 그대로 같다** — 같은 카드가 "공개 데이터에 없으니 직접
확인하라"와 "1억 2천만 원"을 동시에 말한다. 그리고 이 문장은 적대적 입력이 아니라,
프롬프트가 `COST_DISCLOSURE`("조합 내부 자료라 확인할 수 없어")를 rationale 로 싣고
세대수(1,588→2,300)를 재료로 주는 상황에서 **모델이 가장 쓸 법한 완성문**이다.
방어가 놓친 것이 예외적 표현이 아니라 **최빈 표현**이다.

동시에 **오탐**이 있다. `최근 실거래 7억 원 수준이며 추가분담금은 확인되지 않았습니다` —
금액을 지어내지 않은 **모범 답안**인데 폴백으로 강등되고, 사용자에게는
`NOTE_LLM_COST_BLOCKED` 가 나간다:

> "AI 요약 1건이 추가분담금·부담금 **금액**을 언급해 폐기하고 … 이 시스템은
> **어떤 경로로도** 그 금액을 제시하지 않습니다"

두 문장 다 사실이 아니다. 앞은 언급하지 않은 것을 언급했다고 말하고(G2 위반 — 시스템이
사용자에게 거짓을 말한다), 뒤는 위 4종이 나가므로 거짓이다. `test_redevelopment.py` 의
절대 규칙 ①("어떤 경로로도 출력되지 않는다")도 같은 이유로 여전히 거짓이다.

> CR-029 를 닫은 문장을 그대로 적용한다 — **지키지 못하는 방어를 지킨다고 적는 것**이
> 이 프로젝트에서 가장 비싼 실패다. 이번엔 그 문장이 코드 주석이 아니라 **사용자 화면**에 있다.

**통과 조건**

1. 근접 30자 창을 버리고 **필드 단위 동시출현**으로 볼 것 — 한 필드(문자열 하나) 안에
   분담금류 낱말과 금액 토큰이 함께 있으면 차단. 이 필드들은 짧은 요약 문장이라
   창을 넓혀도 비용이 없다. (C·D·E 를 죽인다)
2. `_COST_WORD` 를 어간 단위로 넓힐 것 — `분담(금|액)?` · `부담(금|액)?` · `환급(금|액)?` ·
   `추가\s*비용`. (B·K 를 죽인다)
3. **고지 문구를 사실로 만들 것.** 1·2 를 넣으면 오탐(정상4)도 함께 걸리므로,
   `NOTE_LLM_COST_BLOCKED` 를 "AI 요약이 분담금 **금액으로 읽힐 수 있는 표현**을 포함해
   폐기했습니다" 로 바꾸고, **"어떤 경로로도 제시하지 않습니다"를 삭제**할 것
   (`test_redevelopment.py` 절대 규칙 ① 문구도 같이). 정규식은 원리적으로 완전할 수 없다 —
   완전하다고 쓰지만 않으면 된다.
4. 회귀 테스트: 위 C·E·B·K 4종을 **`run_mvp_pipeline` 최종 카드**에서 단언할 것
   (`assert_no_cost_estimate` 단위 호출만으로는 이번 구멍이 안 보인다). 대조군은 유지.

---

### 새로 발견 (비차단)

**CR30-2 (medium) — 위생 검사가 `.text`/`.json()` 을 못 보고, 로컬 파일 읽기를 오탐한다**

`test_downloaders_read_through_capped_helper` 의 docstring 은 *"새 수집기를 만들면서 잊으면
이 테스트가 먼저 넘어진다"* 고 적는다. 프로브로 확인한 실제 범위:

* `scripts/` 에 `return c.get(url).text` · `c.get(url).json()` 만 쓰는 수집기를 넣었더니
  **전 스위트 통과**. AST 검사는 `.content` 와 인자 없는 `.read()` 만 본다 —
  `.text`/`.json()` 도 본문을 통째로 메모리에 올리는 것은 같다.
  (실제로 `app/ingest/run_molit.py:62` 가 `resp.text`, `app/agents/llm.py:205` 가 `resp.json()` 이다.
  검사 대상이 `scripts/*.py` 뿐이라 `app/ingest/` 의 수집 경로는 애초에 보지 않는다.)
* 반대로 `with open(p) as fh: return fh.read()` (로컬 파일)를 넣으면 **오탐으로 실패**한다.
  `_LOCAL_READ_OK = ("read_bytes", "read_text")` 는 **죽은 코드**다 —
  조건이 `node.func.attr == "read"` 인데 `"read"` 가 그 튜플에 있을 수 없다.

차단하지 않는 이유: 기존 5개 다운로더는 **실제로 닫혔고**(`capped_get`·`capped_urlopen_read`),
헬퍼 자체는 MockTransport 로 스트리밍·상한·non-2xx 재전파까지 실동작 검증돼 있다.
96MB 상한도 실측 최대(학구도 SHP 23MB)의 4배 여유라 정상 수집을 막지 않고,
초과분은 청크 1개(256KB) 이내로 한정된다. 남은 것은 **미래 코드에 대한 약속**이다.

*통과 조건*: 검사에 `.text`/`.json()` 추가 · 대상에 `app/ingest/` 포함(또는 docstring 의
적용 범위를 사실대로 좁힐 것) · `_LOCAL_READ_OK` 를 실제로 동작하게 하거나 삭제.

**CR30-3 (medium) — DEPLOY.md 마이그레이션 검사의 기준선이 자기 자신이다**

`first = min(문서에 적힌 번호)` 라 **목록 아래쪽을 지우면 요구도 함께 사라진다.** 실측:

| 변이 | 결과 |
|---|---|
| 목록에서 **중간(013)** 참조 삭제 | **KILLED** (exit=1) — 이번 수정이 노린 SR24-5 는 확실히 닫혔다 |
| 목록에서 **최저번호(009·010)** 삭제 | ⛔ **SURVIVED** (exit=0) |

"이미 적용된 건 지우자"는 런북 정리는 흔하고, 그 결과는 DEPLOY-1 그대로다 —
빈 볼륨에서 재구축하면 `app_user.status` 가 없어 **모든 인증 경로가 500**.
docstring 이 기준선을 문서에서 가져온다고 밝히고는 있어 은폐는 아니다.
*통과 조건*: 손수 적용 시작 번호를 테스트 상수로 고정(예: `_MANUAL_FROM = 9`).

**CR30-4 (low) — 도메인 assert 에 새로 넣은 `must_verify` 가 무테스트**

`analysis.py:397` 에서 `*must_verify` 를 빼도 전 스위트 통과(SURVIVED).
이 인자를 넣은 것 자체는 옳다(`_merge_actions` 로 `next_actions` 에 합쳐지는 경로였다).
다만 그 사실을 고정하는 테스트가 없다. 문자열 생산자가 우리 코드(`_must_verify`)라 위험은 낮다.

### 이월 처리

* **PERF-1 → RESOLVED.** `postgis.py:1493` `_DISTRICT_AVAILABLE_SQL` 이 `if row is None`
  블록 안으로 들어갔다(급 3종 × 단지당 불필요 공간질의 3회 제거).
* **SR24-6 → RESOLVED.** `allow_inf_nan=False` + 저장 조건 경로의 `_rejected_value_note`
  로 이중 방어. 되비추는 원문은 40자로 자른다(SR21-2 계열 위생 준수).
* SCHOOL-4 · SCHOOL-5 · COND-1 · FE-PLAIN-1 · REDEV-W1 · PREF-1 · SCHOOL-2 · SCHOOL-3 ·
  POI-2 · SCORE-1 · DEPLOY-2 · DEPLOY-3 · REC-4 · OPS-1 · SEC-4 · REC-2 · ADM-3 · JOB-2 이월.

### 사실로 확인한 나머지 신규 변경

**`RequestValidationError` 핸들러 — 옳고, 프론트를 깨지 않는다.**
`type`/`loc`/`msg` 만 남긴다. 프론트 `client.ts:542` 는 `detail` 이 배열이면
`"code" in detail` 이 거짓이라 `UNKNOWN` 으로 떨어지는데, **FastAPI 기본 핸들러도 배열을
돌려줬으므로 동작이 바뀌지 않는다**(422 는 원래 폼 단에서 처리한다). 잃는 것은 `ctx`
(제약값)뿐이고 그 내용은 `msg` 문자열에 남는다. 회귀 2건(평문 비밀번호 미반사 ·
`Infinity` 가 500 이 아니라 422)이 함께 들어와 있다.

**디자인 토큰 — 계산으로 지켜진다(자기충족 아님).**

| 변이 | 결과 |
|---|---|
| `--text-estimated` → 옛 `#8e8e93` | **KILLED** — `expected 3.26 to be greater than or equal to 4.5` 외 3건 |
| `--accent` → iOS `#007aff` | **KILLED** — 1 failed / 44 passed |

값을 되받아 적는 대신 rgba 알파 합성 후 WCAG 상대휘도를 실제로 계산한다.
`--ff-num` 삭제 후 `var(--ff-num)` 잔존 참조 **0건**(주석·테스트 단언 제외) —
지운 토큰을 가리키는 CSS 가 남아 `font-family` 가 무효화되는 사고는 없다.
`--accent` 는 border/`accent-color` 로만 남고 글자색은 전부 `--accent-text` 로 갔다.

**`check_payload`(정비사업) · `_common.read_capped`** — HTML 오류 페이지가 `DictReader`
로 1행이 되어 `if not records` 를 통과하던 조용한 오적재가 닫혔고, 정상 CSV(서울 UTF-8 ·
인천 CP949 '구 역 명' 공백 헤더)는 그대로 통과하는 대조군까지 있다.

> 이번 라운드는 **두 개를 완전히 닫았고 하나를 절반 닫았다.** 남은 절반이 차단인 이유는
> 미해결이라서가 아니라, **닫혔다고 사용자 화면에 적혀 있기 때문**이다. 정규식은 완전할 수
> 없다 — 완전하다고 말하지 않으면 된다. 통과 조건 4개 중 3개는 문구 수정이다.
---

## CR-031 · 2026-07-28 · CR-030 차단 재검증(3라운드) — 분담금 주제 폐기 전환 · 마이그레이션 기준선 · 위생 검사 범위

**판정: PASS** · 차단 **0건** · 미커밋 97건
**CR30-1 해소 확인.** 신규 비차단 5건(CR31-1~5) · CR30-4 이월.

### 재현 — 주장 숫자 전부 일치

| | 주장 | 실측 |
|---|---|---|
| backend | 1,123 / 76 skipped | **1,123 passed / 76 skipped / 0 failed** (junitxml 1,199−76. 변이 원복 후 재실행에서도 동일) |
| frontend | 656 / 39 files | **656 passed / 39 files** |
| build · tsc | ok | **둘 다 exit 0** |

CR-030 시점 1,092 → 1,123(+31). 변이 14종 실행 · 전 파일 md5 원복 확인 · `git status` 97건 불변.

**줄바꿈 손상 — 없다.** HEAD 대비 **내용이 같고 줄바꿈만 다른 파일 0건**을 직접 계산했다
(`git show HEAD:f` 와 작업본을 `\r\n`→`\n` 정규화해 비교). 작업본에 CRLF 가 섞인 파일이
32개 있으나 `core.autocrlf=true` 이고 `git ls-files --eol` 이 **전부 `i/lf`** 라 커밋되는
블롭은 LF 이며, `git diff --stat` 도 70파일 6,371+/575− 로 부풀지 않았다. **지적할 것 없음.**

---

### ✅ 해소 — CR30-1 (CR-029 부터 3라운드째)

#### 1) 내가 뚫었던 것으로 다시 시도했다 — **전부 막힌다**

`FakeLLM` + `run_mvp_pipeline` **최종 카드**에서 실측(단위 호출 아님):

```
CR-029 원문      fallback  고지=True   clean
C 문장분리        fallback  고지=True   clean
E 30자초과       fallback  고지=True   clean
B '부담'         fallback  고지=True   clean
K '분담액'        fallback  고지=True   clean
F 필드분리        fallback  고지=True   clean     ← 담당자가 스스로 찾은 5번째
모범답안          fallback  고지=True   clean     ← 의도된 폐기(아래 3)
대조군(정상)      llm       고지=False  clean     ← 방어가 고장난 게 아니다
```

경계 3종도 확인했다: `why` 7번째 원소는 `[:6]` 절단이 **검사보다 먼저** 돌아 카드에
닿지 않고, `next_actions` 5번째 원소는 절단 뒤에도 남아 **검사에 걸려 폴백**하며,
`why_not` 이 리스트가 아니면 우리 risks 로 대체된다. 잘라서 통과시키는 구멍은 없다.

#### 2) 재료 제거가 **실제로** 됐다 — 프롬프트 실물을 떠서 확인

`llm.calls[0]["user"]`(3,218자)를 눈으로 확인했다. 재건축 finding 의 rationale 이
`…기존 1,588가구 → 건립 예정 2,300세대(1.448배)입니다.` 에서 끝나고 `COST_DISCLOSURE`
문장이 통째로 빠져 있다. 프롬프트 전체에 `분담`·`부담`·`환급`·`추가 비용` **0건**.
동시에 **사용자 카드에는 남는다** — `next_actions[0]` 이 "추가분담금 규모는 조합
사무실·정비사업 정보몽땅에서 직접 확인하세요", `findings[].rationale` 에 고지 원문,
`notes` 에 고정 문장 2줄. **프롬프트용 정리와 사용자 출력이 분리돼 있다.**

낱말이 아니라 **문장 단위로** 뺀 판단이 맞다. 낱말만 지웠다면 "…은 조합 내부 자료라
확인할 수 없어"라는 빈칸이 남고, 그건 모델에게 채우라는 지시나 다름없다.

#### 3) "잃는 정보가 0" — **실물로 확인했다. 대체로 참이다**

모범 답안(`최근 실거래 7억 원 수준이며 추가분담금은 확인되지 않았습니다`)이 폐기된
카드를 전부 떠서 대조했다:

| 폐기된 LLM 문장이 담던 정보 | 폴백 카드에 남는가 |
|---|---|
| 실거래 근거 | ✅ `why[1]`: "…실거래 8건 기준 적정가 밴드는 700,000,000~700,000,000원(중위 700,000,000원)…" — **원 문장보다 자세하다** |
| 분담금은 확인 안 됨 | ✅ `next_actions[0]` 고정 문구 + `notes` 2줄 |
| 폐기 사실 | ✅ `notes` 의 `NOTE_LLM_COST_BLOCKED` |

**한 가지는 잃는다 — `headline`.** `조합설립 단계 재건축 — 진행 확실성이 오르는 구간`
이 `분석 요약(자동 생성)` 이라는 자리표시자로 바뀐다. 다만 같은 내용이
`redevelopment.verdict`(조합설립인가 — 거주 기간이 제한될 수 있음)와 `why[2]` 에
남으므로 **정보가 아니라 문장 품질의 손실**이다. 테스트가 고정한 세 줄은 전부 참이다.

#### 4) 고지가 사실이 됐다

`NOTE_LLM_COST_BLOCKED` 를 실제 출력에서 떠서 검사했다:

> "AI 요약 1건이 추가분담금·부담 **관련 표현을 써서** 폐기하고 규칙 기반 요약으로
> 대체했습니다(금액 여부와 무관하게 폐기합니다). 분담금 자료는 공개 데이터에 없어
> AI 에게 전달하지도, 분석에 반영하지도 않았습니다 …"

CR-030 이 지적한 두 거짓이 **둘 다 사라졌다**: ① 폐기 사유가 '금액 언급'이 아니라
'표현'으로 정정돼 모범 답안이 걸려도 참이고 ② "어떤 경로로도"가 삭제됐다.
저장소 전수 검색에서 `어떤 경로로도` 는 **그렇게 쓰지 않는다는 설명 3곳과 그것을
고정하는 단언 1곳**(`test_redevelopment.py:992`)에만 남는다. 문구가 되돌아오면 테스트가 죽는다.

#### 5) 변이 — **10종 전부 KILLED**

가드가 "걸려 있다"가 아니라 "하중을 받는다"를 확인했다.

| 변이 | 결과 |
|---|---|
| `_COST_TOPIC_RE` 를 완성형(`추가분담금`·`부담금`)으로 되돌림 | **KILLED** |
| `assert_no_cost_topic` 을 no-op(`hit = None`) | **KILLED** |
| `redact_cost_topic` 무력화(원문 반환) | **KILLED** |
| 프롬프트 fail-safe `contains_cost_topic(user)` 제거 | **KILLED** |
| 출력 게이트 호출 자체 삭제 | **KILLED** |
| 고지 문구를 옛 문장("어떤 경로로도…")으로 복귀 | **KILLED** |
| `statement_timeout` connect_args 제거 | **KILLED** |
| 통계조회 실패를 조용히 삼킴(`return []`) | **KILLED** |
| 위생 검사 범위를 `scripts/` 로 축소 | **KILLED** |
| 위생 검사에서 `.text`/`.json()` 탐지 제거 | **KILLED** |

**자기충족 테스트 0건.** 5종 회귀는 `assert_no_cost_topic` 을 직접 부르지 않고
`run_mvp_pipeline` 결과 카드에서 `"1억 2천만"`·`"1억 원"`·`"1.2억"` 부재를 단언한다.

---

### ⚖️ 담당자의 논증 검증 — **절반만 맞다. 그러나 결론은 옳다**

> "모범 답안과 우회 E 는 텍스트로 같은 모양이다(주제어 + 금액이 한 문장).
> 가르려면 금액이 어느 명사에 붙는지 이해해야 하고 정규식은 못 한다."

**어휘 공기(共起) 규칙에 한해서는 성립한다.** 직접 확인했다 — 두 문장은 어순만
다르므로 '주제어가 금액보다 앞'을 규칙으로 삼으면 갈리지만, 그 규칙은
`추가분담금은 확인되지 않았습니다. 실거래는 7억 원입니다`(옳은 문장, 주제어가 앞)와
`1억 2천만 원이 추가분담금으로 예상됩니다`(틀린 문장, 주제어가 뒤)에서 **양방향으로
깨진다.** 부정어 근접("확인되지 않") 같은 보정도 `추가분담금은 확인되지 않았으나 통상
1억 2천만 원입니다` 한 줄로 무너진다. **"오탐 0 + 4종 차단"은 어휘 규칙으로 동시에
만족되지 않는다** — 이 부분은 참이다.

**그러나 "정규식은 못 한다 → 불가능하다"는 비약이다.** 남은 길이 하나 있다:
**금액의 출처 대조**(프롬프트에 없는 금액 토큰이면 폐기). 모범 답안의 `7억 원` 은
프롬프트의 `700,000,000원` 에서 나온 값이고, 우회 E 의 `1억 2천만 원` 은 프롬프트에
**없다.** 이 규칙은 두 문장을 정확히 가르고, 더구나 아래 잔여 위험 ★G 까지 함께 죽인다.
필요한 것은 "금액이 어느 명사에 붙는지"에 대한 이해가 아니라 **"이 숫자를 우리가 준 적이
있는가"** 이고, 그건 정규식+정규화로 가능하다.

**그럼에도 폐기 쪽을 고른 판단은 받아들인다.** 출처 대조는 한글 수사 정규화
(억/천만/만/쉼표)와 **반올림 허용 오차**가 필요하고, 오차를 좁게 잡으면
`700,000,000원`→`7억 원` 이라는 **바람직한 요약이 차단**되며 넓게 잡으면 지어낸 금액을
통과시킨다. 즉 대안에도 같은 종류의 거래가 있다. **기각 자체는 합리적이고, 기각 사유의
서술만 과하다**(불가능이 아니라 비용이다). `CR31-3` 으로 남긴다 — 논증을 코드에 그대로
적어 두면 다음 사람이 "원리적으로 불가능"으로 읽고 재검토를 접는다.

---

### ⚖️ 잔여 위험 ★G 처리 — **받아들인다**

담당자 보고대로 `비용어 없이 금액만 적는 문장` 은 여전히 통과한다. 직접 재현했다
(전부 `basis=llm`, 폐기 고지 없음, 카드에 금액 노출):

```
6a  조합원은 세대당 1억 2천만 원을 추가로 납부해야 합니다
6b  추납금이 세대당 1억 2천만 원 수준으로 추정됩니다
6c  공사비 인상분 1억 2천만 원이 조합원에게 전가됩니다
6g  세대당 1억 2천만 원을 더 낼 자금계획을 세우세요        (next_actions)
6l  1억 2천만 원을 더 준비하세요
6d/6e/6f/6h  '부  담'(공백) · 分擔金(한자) · bundamgeum · 제로폭 삽입
```

**6번째 우회로는 못 찾았다** — 위는 전부 ★G 와 같은 부류(주제어 회피)이고, 구조가 다른
경로(필드 절단 · `why_not` 비리스트 · 인젝션된 `zone_name` 경유)는 모두 막히거나
★G 로 수렴했다. 참고로 6c 는 프롬프트에 남아 있는 `시공사 선정·공사비 인상…` 이
유도하는 형태라, "재료를 하나도 안 준다"는 서술이 **분담금 4개 낱말에 한해서만** 참임을 보여준다.

**CR-030 이 차단한 이유는 "완전하지 않다"가 아니라 "완전하다고 사용자 화면에 적혀
있다"였다.** 지금은:

* 사용자 고지 — "어떤 경로로도" 삭제, 실제로 하는 일만 서술 (실물 확인)
* 코드 — `analysis.py:158-161` 이 한계를 명시하고 왜 그 방어를 안 쓰는지 적음
* 테스트 — `test_redevelopment.py:9-11` 절대 규칙 ① 이 "주장하지 않는다"로 정정
* 회귀 — 문구가 되돌아오면 `:992` 가 죽음

**요구했던 것이 그대로 됐다. 이것을 다시 차단하면 그것은 CR30-1 이 제기한 결함이 아니라
'언어모델이 숫자를 지어낼 수 있다'는 더 큰 문제를 이 게이트에서 처리하라는 요구가 된다** —
그 문제는 이 가드의 범위였던 적이 없고(모델은 분담금 말고도 "내년 8억까지 오릅니다"를
쓸 수 있다), 그에 대한 방어는 `PORTFOLIO_SYSTEM` 규칙 1·2·3 과 고정 고지다.
**차단은 결과로 정당화되어야지 앞선 경고로 정당화되어선 안 된다.**

다만 이 판단은 **고지가 사용자에게 실제로 닿는다**는 전제 위에 있고, 그 전제가 지금
절반만 참이다 → `CR31-2`.

---

### ✅ 해소 — CR30-3 (마이그레이션 기준선)

기준선이 `_MANUAL_FROM = 9` 상수 + 요구 목록이 **파일 시스템**(`migrations/*.sql` glob)으로
바뀌었다. 변이 실측:

| 변이 | CR-030 | CR-031 |
|---|---|---|
| 최저번호 **009·010** 참조 삭제 | ⛔ SURVIVED | **KILLED** |
| 중간 **013** 참조 삭제 | KILLED | **KILLED** |
| 최고 **014** 참조 삭제 | — | **KILLED** |
| 중간 **011** 하나만 삭제 | — | **KILLED** |

"이미 적용됐으니 지우자"는 런북 정리(=DEPLOY-1 재현 경로)가 **어느 위치에서든** 막힌다.
`_MANUAL_FROM` 이 실재하는 파일인지 확인하는 단언까지 있어 재번호 시 상수가 조용히
무의미해지는 것도 막는다. **CLOSE.**

**지시가 물은 '상수 자체를 올리는 변이' — 잡히지 않는다.** `_MANUAL_FROM = 13` 은
**SURVIVED**(exit=0)이고, 거기에 009·010 참조를 지운 조합(**정확히 DEPLOY-1**)도
**SURVIVED**. → `CR31-5`(low). 다만 성격이 다르다: 예전에는 **문서 한 곳**을 정리하면
가드가 사라졌고 지금은 **테스트 상수를 의도적으로 고쳐야** 한다. 명세를 스스로 낮추는 것은
어떤 상수 기반 검사도 못 막고, 값싼 보강이 있다(아래 통과 조건). 차단하지 않는다.

---

### ✅ 해소 — CR30-2 / SR25-1 (위생 검사)

검사가 "무엇을 읽는가"에서 **"누구의 본문을 읽는가"** 로 바뀌었다(`_is_response_like`
+ 대입 추적 + 이름 규칙). 직접 검사기를 돌려 확인:

* **범위 39파일** — `scripts/` 23 + `app/ingest/` 14 + `app/agents/llm.py` + `app/core/http.py`.
  `test_capped_scope_covers_the_containers_not_just_scripts` 가 범위를 따로 못박아
  "위반이 0건이라 범위를 줄여도 전부 초록"인 상태를 막는다(변이 KILLED 로 확인).
* **위반 0건** — 39파일을 직접 훑어 재확인했다. 주장 그대로다.
* **오탐 제거 확인** — `zf.read(name)` · `el.text` · `open().read()` · `p.read_text()`
  전부 통과. 죽은 코드 `_LOCAL_READ_OK` 는 삭제됐다(주석에 사유만 남음).
* **SR25-1 이 '통과(우회)'로 기록한 형태 6종 전부 적발**로 뒤집혔고, 실제 위반 5곳은
  신규 `app/core/http.py`(`request_capped`, 16MB, `client.stream`+`iter_bytes`)로 전환됐다.
  `read_error_body=False` 기본값으로 **오류 응답 본문을 안 읽는** 판단(프롬프트 되비침 차단)이 좋다.

**남은 우회 형태는 있다**(별칭 재대입 `x = resp; x.content` · 함수 인자 전달 ·
리스트/딕셔너리 경유 · walrus · `b"".join(iter_bytes())`). 다만 ① 저장소에 **실사용 0건**
② `iter_bytes` 는 헬퍼 자신이 쓰는 형태라 일괄 금지하면 헬퍼가 자기 검사에 걸린다
③ AST 별칭 추적은 비용 대비 이득이 낮다. **CLOSE** 하고 `CR31-4`(info)로만 남긴다.

---

### ✅ 확인 — SR24-4 / SR25-2 / SR25-3

**SR24-4 `statement_timeout`** — `create_db_engine` 이 libpq `options` 로 세션에 붙인다
(기본 10초, `DB_STATEMENT_TIMEOUT_MS`, `.env.example:47`). **"조용히 빈 결과가 되는 경로"를
찾아봤고, 없다:**

| 타임아웃 지점 | 사용자에게 보이는 것 |
|---|---|
| `candidate_scope_stats`(SR24-4 가 지목한 전역 스캔) | notes: "…세는 조회가 시간 내에 끝나지 않아 그 숫자는 생략했습니다 — 추천 결과 자체는 조건대로 계산됐습니다" |
| `geocode_coverage` | notes: 숫자 없는 좌표 고지로 강등(사라지지 않음) |
| 메인 후보 조회 | 예외 전파 → job `failed` → 프론트 `jobPhase("failed")="error"` → **"분석에 실패했습니다."** |

`conditions.active` 가 거짓이면 전역 스캔을 **아예 안 돈다**는 부수 효과까지 있다.
변이 2종(connect_args 제거 · except 를 `return []` 로) 모두 KILLED.

**SR25-2** — `_check_region_codes` 가 `region_codes[{idx}]` 로 **위치만** 지목하고,
핸들러가 `msg` 를 200자로 자른다. 직접 쏴서 확인: 비밀 문자열·3,000자 입력·bbox 3종
모두 **반사 0건**(msg 27~82자). 핸들러 독스트링에 "이 보증은 절대적이지 않다"와 이유가
적혔다. **CLOSE.**

**SR25-3 — 기계 키 유지 판단은 옳다.** `source` 는 `redev_project(source, source_key)`
자연키이고 적재가 그 값으로 지우고 다시 넣는다. 바꾸면 616행이 고아가 되고 마이그레이션
015 가 필요한데 **사용자가 얻는 이득은 0**(화면에 안 보이는 값이다). 표시명만
`SOURCE_LABELS` 로 분리한 것이 정확한 최소 변경이다. 모르는 키를 fallback 으로 뭉개지 않고
**그대로 돌려주는** 선택(`source_label`)도 옳다 — 뭉개면 라벨을 잊었을 때 틀린 출처가
조용히 표시된다. 판단 근거가 코드 주석으로 남았다. **CLOSE.**

---

### 새로 발견 (전부 비차단)

**CR31-1 (medium) — 도메인 tripwire 가 이제 *외부 데이터*로 발화하고, 발화하면 추천 job 전체가 죽는다**

CR-030 의 통과 조건 ①("근접 30자 창을 버리고 필드 전체")을 넣으면서 검사 단위가 넓어졌다.
그런데 `rationale` 은 `COST_DISCLOSURE` 를 **항상** 포함하므로 주제어 조건이 **언제나 참**이다.
즉 `assert_no_cost_estimate(rationale, …)` 는 사실상 **"rationale 에 금액 토큰이 하나라도
있으면 예외"** 가 됐다. 그리고 그 rationale 에는 수집 데이터(`zone_name`·`raw_stage`)가
그대로 보간된다(`analysis.py:465-466`).

실측 — `assess_redevelopment` 이 그냥 죽는다:

```
zone_name='1억원지구'               -> CostEstimateError (주제어 '분담' + 금액 '1억원')
raw_stage='조합설립(추정 5000만원)'  -> CostEstimateError
zone_name='제3원구역'               -> CostEstimateError (금액 '3원')  ← _MONEY_RE 맨 뒤 단독 '원'
zone_name='수원역구역'              -> OK (숫자 없음)
```

예외를 아무도 잡지 않는다 → `run_mvp_pipeline` → `run_recommendation_job` 의 포괄 except →
job `failed` + **빈 결과**. 후보 한 건의 구역명 때문에 **추천 전체가 사라진다.**

이 함수의 독스트링은 "사람이 친절하게 한 줄 넣는 순간 예외가 난다 — 그게 이 함수의 존재
이유다"라고 적는다. **개발자 문장에 대한 lint 로서는 옳다.** 문제는 같은 함수가 요청 경로에서
**런타임 외부 문자열**을 보게 된 것이다. lint 를 가용성 결함으로 바꾸는 형태다.
(CR-030 이전에는 근접 30자 + 문장 경계 조건 때문에 다른 문장의 외부 값과 고지문의 '분담'이
이어지지 않았다 — **이번 라운드가 실제로 넓힌 부분**이고, 그 조건을 요구한 것은 나다.)

지금 서울·인천 **616행이 이미 적재돼 있다.** 실제 구역명 표기(`장위4구역`,
`○○동 10번지 일원`)로는 `\d…원` 이 성립하지 않아 발화 가능성은 낮지만, **확인 없이
배포하면 첫 추천에서 알게 된다.**

*통과 조건*

* 배포 전 1회 확인(값싸다):
  `SELECT source, zone_name, raw_stage FROM redev_project WHERE zone_name ~ '\d[\d,.]*\s*(억|천만|백만|만\s*원|원)' OR raw_stage ~ '\d[\d,.]*\s*(억|천만|백만|만\s*원|원)';`
  → **0행이어야 한다.**
* 구조: 외부 문자열은 **적재 시점**에 검사하고(거기서 실패하는 게 옳다), 요청 경로에서는
  `redevelopment_assessment` 가 `CostGuardError` 를 잡아 **그 후보의 재건축 블록만
  '미확보'로 강등 + notes 고지**할 것. 요약 한 줄 때문에 추천을 안 죽인 것과 같은 원칙이다.
* `_MONEY_RE` 의 맨 뒤 단독 `원` 은 `3원`·`5원` 같은 무의미 매칭을 만든다 — 최소 자릿수나
  `만/억/천만` 동반을 요구할 것.

**CR31-2 (medium) — `summary_basis` 가 화면에 없다. 이번 라운드의 논증이 이것에 기댄다**

`orchestrator.py:1205` 는 *"이 카드의 문장이 AI 가 쓴 것인지 규칙이 쓴 것인지 **카드 단위로**
밝힌다. notes 만으로는 어느 카드가 규칙 기반인지 사용자가 알 수 없다"* 고 적고,
`api-spec.md §5.4` 가 계약으로 못박았다. **그런데 프론트에 `summary_basis` 참조가 0건이다**
(`client.ts` 타입에도 없다). `ReportCard.tsx:149` 는 `headline` 을 그냥 찍는다.

지금까지는 문서 지연 정도였지만 **이번 라운드에서 성격이 바뀌었다.** ★G 를 받아들인 근거가
"완전성을 주장하지 않고 한계를 고지한다"인데, 그 고지 체계의 한 축(어느 카드가 AI 문장인가)이
사용자에게 닿지 않는다. 추천 10건 중 3건이 폐기됐을 때 `notes` 는 "3건"이라고만 말하고
사용자는 **어느 카드**인지 모른다.

*통과 조건*: 카드에 한 줄 — `summary_basis === "llm"` 이면 "이 요약 문장은 AI 가 썼습니다
(순위·가격·제외 사유는 규칙 계산)", `"fallback"` 이면 "규칙 기반 요약".
`PREF-1` 처럼 프론트를 다음에 건드릴 때 함께 넣으면 되고 독립 라운드가 필요 없다.

**CR31-3 (low) — 시스템 프롬프트가 탐지 낱말 4개를 모델에게 알려 준다**

`PORTFOLIO_SYSTEM` 규칙 7 이 `'분담'·'부담'·'환급'·'추가 비용' 을 아예 쓰지 마세요` 로
**금지어 목록 = 탐지어 목록**을 그대로 공개한다. 두 가지가 걸린다:
① `assert_no_cost_topic` 독스트링은 "모델은 이 주제를 말할 근거를 받지 못하므로 출력에
주제어가 나타나면 스스로 지어낸 것"이라고 적는데, **시스템 프롬프트로는 주제를 전달하고 있다**
(재료 0 이라는 서술이 `user` 블록에 한해서만 참이다).
② 금지어를 알려 주면 모델은 **그 낱말을 피해 같은 말을 하는 쪽**으로 유도된다 —
그게 정확히 ★G(6a · 6b `추납금` · 6g)다. 방어 문장이 잔여 위험을 **키우는** 방향으로 짜여 있다.

또 담당자가 기각한 대안(금액 출처 대조)의 사유가 **코드에 없다**. 현재 주석은 "정규식을
더 정교하게는 답이 아니었다"까지만 적어 다음 사람이 "원리적으로 불가능"으로 읽는다.

*통과 조건*: 규칙 7 을 낱말 열거 대신 결과 서술로 — "분석 결과에 **없는 비용·금액을
추정하지 마세요.** 금액은 분석 결과에 있는 값만 인용하세요"(탐지어는 코드에만 둔다) ·
`analysis.py` 주석에 "출처 대조는 가능하나 한글 수사 정규화와 반올림 허용 오차 때문에
보류했다"를 한 줄.

**CR31-4 (info) — 위생 검사기의 남은 우회 · `budget=None` 경로**

① `_uncapped_reads` 는 별칭 재대입(`x = resp`)·함수 인자 전달·컨테이너 경유를 놓친다
(실사용 0건이라 CLOSE 유지). ② `portfolio_summary(findings, llm, forbidden)` 를 `budget`
없이 부르면 폐기해도 `cost_blocked` 가 안 세지고 **고지가 나가지 않는다.**
`run_mvp_pipeline` 은 항상 넘기므로 현재 경로는 안전하나, 공개 함수의 조용한 분기다.

**CR31-5 (low) — `_MANUAL_FROM` 을 올리는 변이는 안 잡힌다**

위 §CR30-3 참조. *통과 조건*(값싼 쪽): DEPLOY.md 본문에 "손수 적용은 **009부터**"를
한 줄 명시하고 테스트가 `_MANUAL_FROM` 과 그 선언 번호의 **일치**를 단언할 것 —
그러면 상수만 올리는 변이가 문서와 어긋나 죽는다.

### 이월 처리

* **CR30-4 → OPEN 유지(low).** `analysis.py:485` 의 `*must_verify` 를 빼도 전 스위트 통과
  (재확인, SURVIVED). 인자를 넣은 판단은 여전히 옳고 문자열 생산자가 우리 코드라 위험은 낮다.
  다만 `_must_verify` 에 `zone_name`(외부 값)이 들어가므로 `CR31-1` 과 같은 자리이기도 하다.
* **SR24-3 → CLOSE 권고**(보안 로그 소관). 탐지식 문제는 이번에 해소됐다.
* **`SR-025 §llm_key_precondition`(ANTHROPIC_API_KEY 투입 전 CR30-1 해소) → 선행 조건 충족.**
  단, 키 투입 시 `CR31-2`(카드 단위 고지)와 `SR22-5`(누적 소비 상한)를 함께 처리할 것.
* PREF-1 · SCHOOL-2/3/4/5 · COND-1 · FE-PLAIN-1 · REDEV-W1 · POI-2 · SCORE-1 ·
  DEPLOY-2/3 · REC-2/4 · OPS-1 · SEC-4 · ADM-3 · JOB-2 이월.

### 판정

**PASS — 커밋·배포로 진행 가능.**

CR-030 이 낸 통과 조건 4개 중 담당자는 **①②를 버리고 더 강한 것으로 대체했다.**
그 판단이 옳다는 것을 결과로 확인했다 — 뚫었던 5종이 최종 카드에서 전부 막히고,
대조군은 살아 있으며, 프롬프트에서 재료가 실제로 사라졌고, 변이 10종이 전부 죽는다.
③④(고지를 사실로 · 최종 카드 단언)는 요구한 그대로 됐다.

**차단하지 않는 이유를 분명히 한다.** 남은 ★G 는 CR-030 이 문제 삼은 결함이 아니다.
CR-030 이 차단한 것은 *"막지 못하는데 막는다고 사용자 화면에 적은 것"* 이었고, 그 문장은
삭제됐으며 되돌아오면 테스트가 죽는다. ★G 를 이유로 다시 막으면 그것은 "언어모델이 숫자를
지어낼 수 있다"는 별개의(그리고 이 가드의 범위였던 적 없는) 문제를 3라운드째에 끼워 넣는
것이 된다. 3라운드라는 사실이 통과 근거가 아니듯, 앞 라운드의 경고도 차단 근거가 아니다.

**새로 낸 CR31-1 은 medium 이지 차단이 아니다** — 발화 조건이 수집 문자열의 특정 형태이고,
실패가 조용하지 않으며(job failed → "분석에 실패했습니다"), 배포 전 SQL 한 줄로 확인
가능하다. 다만 **그 한 줄은 배포 전에 반드시 돌릴 것.** 616행이 이미 DB 에 있다.

> 이번 라운드에서 가장 값어치 있는 것은 **정규식을 정교하게 만드는 대신 주제를 없앤
> 결정**이다. 방어를 더 촘촘히 짜는 대신 방어할 것 자체를 줄였고, 그래서 "다음 변형"이 없다.
> 다만 같은 라운드에서 반대 방향의 일도 일어났다 — 넓힌 도메인 검사가 외부 데이터를 보게
> 됐다(CR31-1). **검사를 넓히면 그 검사가 보는 입력의 출처도 같이 넓어진다.**

---

## CR-032 — 2라운드 (CR31-1 조치 · MAP-2 · PERF-1 · REC-7 · FE-4/5 · CR31-2 · UX-5 · MAP-3 · 레지스트리)

**일시** 2026-07-28 · **리뷰어** code-reviewer · **대상** `c70b54c` 이후 미커밋 44파일
(백엔드 14 · 프론트 25 · 문서 1 · 신규 5) · **판정 PASS**

### 실행 검증 (전부 직접 돌림)

| 항목 | 주장 | 실측 | 결과 |
|---|---|---|---|
| 백엔드 | 1,175 passed / 78 skipped / 0 failed | junitxml: `tests=1253 skipped=78 failures=0 errors=0` → **1,175 passed** | ✅ 정확히 일치 |
| 프론트 | 735 passed / 41 files | `Test Files 41 passed · Tests 735 passed` | ✅ |
| 빌드 | — | `vite build` exit 0 · `tsc --noEmit` exit 0 | ✅ |
| 줄바꿈 | — | `core.autocrlf=true` 로 `git diff` 가 정규화 → 줄바꿈만 바뀐 파일 **0건**. 작업본 CRLF/LF 혼재는 커밋 블롭에 안 나타남 | ✅ |
| 대비 테스트 | 45 → 63 | `tokens.contrast.test.ts` **63 passed** | ✅ |

---

## ★ 최우선 — 파일 복구 사고: **바이트 단위 복구가 맞다** (독립 증명)

담당자의 근거(pyc 라인테이블·`source_size` 3바이트)는 **재검증 불가**다. 복구 직후 파일을
임포트한 순간 pyc 가 재생성됐고(현재 `source_size=47901` = 현재 파일 크기, mtime 일치),
서버 `/tmp/newapp` 사본도 삭제됐다. 그래서 **다른 증거를 찾았고, 더 강한 것이 나왔다.**

### 사고 재구성 (전 에이전트 트랜스크립트 원본에서)

`.claude/projects/…/subagents/agent-aaf29fdabef1f6e3e.jsonl` (레지스트리 담당, backend-docker):

| 시각(KST) | 행위 |
|---|---|
| 07:05:48 | **REC-7 담당**(`agent-a367b124…`)의 `recommend.py` 마지막 Edit |
| **07:31:37** | REC-7 담당이 `snap_before_mut.json` 작성 — `backend\app\agents\recommend.py` = **md5 `5343a7fe6581406bc53a291c5138a3eb`** |
| 07:32~07:34 | `mut_cr031.py` 변이 25종 실행 (원복은 `write_bytes(raw)` + md5 단언) |
| 07:38:48 | 레지스트리 담당이 duck-typing 주석을 **자기 작업으로** 수정 |
| 07:42:33 | 변이 M1 적용 — `redevelopment=redevelopment,`(28자) → `redevelopment=None,  # MUTATION`(31자) = **정확히 +3바이트** |
| **07:42:39** | **`git checkout -- backend/app/agents/recommend.py`** ← 사고. REC-7 작업 + 자기 주석까지 함께 소멸 |
| 07:45:52 / 07:46:47 / 07:47:03 | 복구 Edit 3건(상한 블록 · 상한 고지 · 자기 주석) |

### 검증 — md5 대조

07:31:37 스냅샷은 **사고보다 11분 앞서고, 사고를 낸 에이전트가 아닌 REC-7 담당이 직접**
전 백엔드 `*.py` 를 `read_bytes()` md5 로 찍은 것이다. 즉 **사고 전 진본의 지문**이다.
현재 파일에서 **스냅샷 이후에 들어온 레지스트리 담당 자신의 주석 편집만** 되돌리면:

```
current                 md5 = 17ec495d00855df53121273d57be45d6  (47,901 B)
minus 레지스트리 주석    md5 = 5343a7fe6581406bc53a291c5138a3eb  (47,619 B)
snapshot @07:31:37 KST      = 5343a7fe6581406bc53a291c5138a3eb   ← 완전 일치
```

**바이트 하나도 다르지 않다.** 주석 한 줄·공백·로직 조각 어느 것도 유실되지 않았다.
(대조군: HEAD 블롭은 LF `d20c8d21…` · CRLF `69c55adb…` 로 둘 다 불일치 — 우연이 아니다.)

* 변이 M1 의 +3바이트가 담당자가 말한 "3바이트"와 정확히 같은 값임도 트랜스크립트로 확인.
  그 논증 자체는 옳았고, 다만 **재현 불가**했다. 위 md5 대조는 재현 가능하다.

### 같은 사고가 다른 파일에도 있었는가 — **없다**

전 subagent + 메인 세션 트랜스크립트에서 `git checkout|restore|stash|reset|clean` 을 전수
스캔했다. 2026-07-27T22:00Z 이후 파괴적 명령은 **07:42:39 그 한 건뿐**이고 대상은
`recommend.py` 하나다. `scoring.py`(HEAD 와 동일 · git status 에 없음) ·
`orchestrator.py`(변이 M4 를 python 치환으로 정상 원복, 07:48:13) 는 무관 — 주장대로다.
저장소 전체 `MUTATION` 잔여 마커 **0건**.

> **재발 방지(권고, 비차단)**: 여러 에이전트가 같은 작업본을 공유하는 동안
> `git checkout --` 은 **자기 변경만 되돌리는 명령이 아니다.** `mut_cr031.py` 처럼
> 원본 바이트를 들고 있다가 `write_bytes(raw)` + md5 단언으로 되돌리는 방식이 정답이고,
> 그 파일이 이미 저장소 안에 있었는데 쓰이지 않았다. 변이 절차서에 한 줄 못박을 것.

---

## 각 작업 검증

### CR31-1 — 내가 낸 지적. 조치가 맞고, **검사는 약해지지 않았다**

발화 케이스 4종을 직접 태웠다 — 전부 살아난다(예외 없음):

```
zone_name='1억원지구'                 -> OK   (예전: CostEstimateError)
zone_name='제3원구역'                 -> OK   (_MONEY_RE 자릿수 하한)
raw_stage='조합설립(추정 5000만원)'    -> OK
zone_name='700,000,000원구역'         -> OK
```

동시에 **인용 밖의 우리 금액은 그대로 잡힌다**:
`"1억원지구 재건축입니다. 분담금은 약 3억원으로 예상됩니다."` + quotes=`('1억원지구',)`
→ **BLOCKED**. 인용 제거가 "검사 끄기"가 아니라 "대상 되돌리기"라는 서술이 실물로 성립한다.

`_MONEY_RE` 자릿수 하한도 진짜 금액을 놓치지 않는다:
`3억원`·`5000만원`·`1.2억`·`3000원`·`700,000,000원`·`1.5억 원` 전부 잡히고,
`3원`·`50원`·`999원`·`2026`·`1,588세대` 만 빠진다. **오탐만 정확히 줄었다.**

강등 문구는 '미확보'와 다르다 — 확인:
* 미확보 `"…매칭된 정비사업 구역이 없습니다 — … '확인되지 않았다'는 뜻"`
* 강등   `"…내부 금액 검사에 걸려 … '이번 분석에서 판정하지 못했다'는 뜻"`

그물도 제대로 짜였다: `redevelopment_pair` 가 판정+Finding 을 한 자리에서 만들고,
강등 집계를 **예외가 아니라 판정 객체**(`is_cost_guard_degraded`)에서 읽어 앞단 강등이
누락되는 자리를 막았다. 적재 시점 검사(`money_like_records`)도 리포트에 들어갔다.

**→ 우회 가능성은 담당자가 인정한 것보다 넓다 → `CR32-3`(low). 차단 아님.**

### MAP-2 — **1초 목표 안이다. 내가 직접 쟀다**

운영 DB 에 현재 코드를 읽기 전용으로 태워(`/tmp/cr032`, 돌고 있는 컨테이너 코드는 무손상)
최악 케이스를 5회씩 측정:

| bbox | 건수 | 중앙값 | **최대** | 역 확보 | 정비 매칭 | 블록 없음 |
|---|---|---|---|---|---|---|
| 밀집 0.2도(강남·서초, 격자 최대 1,278) | 500 | 134.4ms | **157.8ms** | 500 | 33 | 0 |
| 서울 전역 | 500 | 134.6ms | 140.4ms | 500 | 30 | 0 |
| 수도권 최대(2도) | 500 | 135.9ms | 153.4ms | 500 | 30 | 0 |

상한 500 이 LATERAL 보다 먼저 걸리므로 bbox 를 넓혀도 시간이 안 늘어난다 — 주장대로다.
`redevelopment` 블록이 **한 건도 빠지지 않는다**(블록 없음 0) → '없다'와 '모른다'가
같은 모양이 되는 경로가 실데이터에 없다.

`verdict`·`score` 미탑재 판단은 **옳다.** `STAGE_PROFILE` 에서 사업시행인가는 투자 85 /
실거주 35 로 뒤집힌다. 지도는 `purpose` 를 모르므로 목적 없이 만든 판정을 올리면 추천
카드와 다른 말을 하게 된다. 프론트 `tags.ts:redevelopmentFact` 도 `available:false` 를
`"no"` 가 아니라 `undefined`(모름)로 접는다 — 계약이 양쪽에서 맞다.
역 반경·정렬도 `_STATIONS_SQL` 과 동일(`subway` · 3,000m · `ORDER BY distance_m`).

응답 크기는 실측 **128.0 → 238.2 KiB (×1.86)** — 증가폭 자체는 정당하다.
문제는 절대값이고, 그건 코드가 아니라 배포 설정이다 → `CR32-1`.

### PERF-1 — **급이 섞이는 경로가 없다. 600단지로 재현**

옛 3벌 조회를 SQL 수준에서 그대로 재구성해(`= :level` · `LIMIT 1` · 카운트 무필터)
신규 1벌 결과와 대조:

```
표본 600 단지 (전체 15,561) · 1,800 판정
불일치 0건
급 불일치 0건
소요: 신규 1.37 ms/단지 · 옛(3벌) 2.10 ms/단지
```

담당자 보고(400단지)보다 넓은 표본에서 동일 결론. 보장 지점 4곳이 SQL 에 실재하고
(`= ANY(:levels)` · `DISTINCT ON (school_level)` · `c2.school_level = n.school_level` ·
`g.school_level = n.school_level`), 파이썬 쪽은 **행이 말한 `school_level` 로만** 가른다
(호출 순서 추정 없음). `DISTINCT ON` 의 `ORDER BY school_level, distance_m NULLS LAST, poi_id`
로 동률 시 재현성까지 확보.

**SURVIVED 변이(`= ANY(:levels)` → `IS NOT NULL`)는 "운영 데이터에서만 동치"보다 강하다.**
`_fetch_schools` 가 `for level in levels` 로만 결과를 읽으므로, 4번째 급(유치원 등)이
`containing` 에 들어와도 `DISTINCT ON` 이 급별로 가른 뒤 **읽히지 않고 버려진다** —
어떤 데이터에서도 관측 가능한 출력이 같다(비용만 늘 뿐). DB-free 테스트
(`test_요청하지_않은_급은_결과에_없다`)가 그 성질을 직접 고정한다. **덮개는 충분하다.**

### REC-7 — 실측이 맞다. **다만 120 의 근거 한 줄이 실측과 다르다**

운영 DB 실측(상한만 바꿔 3지역 × 2조건):

| | 상한 50 | 상한 120 | 상한 200 |
|---|---|---|---|
| 후보 조회 SQL | 0.80~1.26s | **0.81s** | **0.80s** |
| 강남 조립 | 1.42s | 2.33s | 3.13s |
| 강남 후보 수 | 93 | 123 | **151** |
| 강남 59~85㎡ 후보 수 | 60 | 83 | **195** |
| 송파 후보 수 | 121 | **200 = 상한** | 200 |

**"상한이 DB 부하를 안 줄이고 있었다"는 정확하다** — SQL 은 상한과 무관하게 0.8초로 평평하다.
비용은 단지당 조립(내 측정 ~13ms)이고 50→120 은 +0.9~1.0초. 추천은 **비동기 job** 이라
2.4s→3.4s 는 허용 가능하다(프론트가 진행 문구를 보이고, `statement_timeout` 10초와 무관).

**→ 그러나 "MAX_CANDIDATES 가 먼저 걸려 더 올려도 결과가 같다"는 송파에서만 참 → `CR32-2`.**

부수 확인: 상한 고지가 18회 중 17회 뜬다(상한 200 에서도). 50→120 은 고지를 없애지 못하고
"얼마나 봤는가"만 늘린다 — 고지 문구가 정직해서 이 사실이 사용자에게 그대로 전달된다.
`MAX_CANDIDATES` 절단도 `_capped` 가 notes 로 말한다(조용한 유실 없음).

### 프론트

**FE-4 — 처리가 옳고, 폴백은 더 없다.** `use_saved_conditions:false` 가 죽이는 폴백은
`_pick(..., use_saved=)` 를 타는 **두 곳뿐**이다(`conditions.py:411` 필터 4종 ·
`:455` `target_price_krw`). 프론트는 희망가를 `budget_override_krw` 로 **항상** 싣고
칩이 없는 `min_households` 를 명시 재전송한다 → **빠진 폴백 없음**. 가중치·기피조건은
`_pick` 을 안 타므로 애초에 영향받지 않는다. 요청 필드와 화면 문구를 같은 상태에서 같은
함수로 만든 것(`conditionFields`/`conditionPlan`)도 맞다.

**FE-5 — 서버와 정말 같은 규칙이다. 9케이스 교차검증.**
`effectiveWeights` 와 `scoring.normalize_weights` 를 같은 입력으로 돌려 축별 비교:

```
기존 사용자(redev 키 없음) : 0.2550/0.2550/0.2125/0.1275/0.1500  ← 서버·화면 동일
명시적 0 / 명시적 값 / 일부만 / 음수 섞임 / 모르는 키 / NaN     ← 전부 동일
```
"키 존재 여부로 판단(값 0 이어도 언급으로 침)" · `share/(1-share)*total` 삽입 · 상대비율
보존까지 같다. 레지스트리 증명(`weights_change_order_redevelopment`)도 명시 0 →
`status=="zero_weight"`, 0↔100% 순위 역전, **목적만 바꿔도 재역전**까지 단언한다 — 강하다.

**CR31-2 — 요구한 것 이상이다.** 카드마다 배지를 다는 대신 **"AI 가 돌았는데 이 카드만
규칙 기반"** 일 때만 표기한다(`llmSummaryActive`). LLM 미연결이면 전 카드가 fallback 이라
배지가 소음이 되고 그때 정말 강등된 한 건이 묻힌다 — 그 판단이 맞다. `notes` 문자열을
뒤지지 않고 `summary_basis` 값으로 판정하는 것도 맞다. 사유는 서버가 카드 단위로 주지
않으므로 **지어내지 않고** 하단 고지를 가리킨다(G2 준수).

**UX-5 — 시각 부작용 허용 가능.** 뒤에 오는 것이 우리가 색을 정하지 않는 지도 타일이므로
반투명으로는 어떤 텍스트 토큰으로도 4.5:1 을 보장할 수 없다 — **튜닝이 아니라 구조 문제**라는
진단이 맞다. 범례·pill 이 불투명해지는 것은 지도 위 가독성에서 이득이고, 대비 테스트 63건이
`--bg` 위 수치와 같아진 것을 고정한다. 죽은 `backdrop-filter` 는 남아 있다 → `CR32-6`.

**MAP-3 — 진단이 옳다. 라이브에서 직접 재현했다.**

```
GET https://dapi.kakao.com/v2/local/search/keyword.json
  Authorization: KakaoAK <배포된 JS 앱키>
  KA: … origin/https%3A%2F%2Frealestate.utilverse.info
→ HTTP 401
  {"errorType":"AccessDeniedError",
   "message":"domain mismatched! caller=https%3A%2F%2Frealestate.utilverse.info.
              check out registered web domains."}
```
그리고 라이브 CSP 는 `connect-src 'self' https://dapi.kakao.com` — **CSP 는 범인이 아니다.**
코드로 못 고치는 것이 맞다. 조용한 실패 4건 제거도 실물이다: 콜백 인자가 실패 시 한 칸씩
밀린다는 관찰(`data` 가 배열이 아님)로 판정해, 비동기 콜백 예외로 Promise 가 영영 미결이
되는 경로까지 막았다. 문구도 "잠시 후 다시 시도"(거짓)에서 **할 일**로 바뀌었다 —
실패가 보이고, 행동 가능하다.

---

## 새로 발견

**CR32-1 (medium) — 지도 응답이 gzip 되지 않는다. 238KiB 가 생짜로 나간다**

MAP-2 로 응답이 128.0 → 238.2 KiB 가 됐는데(실측), **JSON 이 압축되지 않는 상태**다.
호스트 nginx 는 `gzip on;` 이지만 `gzip_types` 가 **주석 처리**돼 있어 기본값
(`text/html`)만 압축한다. `deploy/nginx-realestate.conf`·`deploy/nginx.conf` 에도
`gzip` 지시어가 없다. 라이브 확인:

| 경로 | Content-Type | Content-Encoding |
|---|---|---|
| `/health` (SPA) | text/html | **gzip** |
| `/api/v1/health` | application/json | **없음** |

같은 payload 를 gzip 하면 **26.6 KiB**(×0.11). 지도는 팬할 때마다 다시 부르는
모바일 퍼스트 화면이라 이 차이는 셀룰러에서 그대로 체감된다.
**증가 자체는 정당하고 절대값이 문제이며, 고칠 곳은 코드가 아니라 배포 설정 한 줄이다.**

*통과 조건*: `deploy/nginx-realestate.conf` 에
`gzip on; gzip_types application/json; gzip_min_length 1024;` 를 넣고 배포 후
`Content-Encoding: gzip` 을 실측으로 확인. (배포 게이트 항목으로 이월)

**CR32-2 (low) — `CANDIDATE_COMPLEX_LIMIT=120` 의 주석 근거 한 줄이 실측과 다르다**

`recommend.py:85-88` 이 *"그 위로는 `MAX_CANDIDATES`(200)가 먼저 걸려 추가 조회가 버려지기
시작한다 … 상한을 더 올리면 시간만 늘고 **사용자가 보는 결과는 같아진다**"* 라고 적고
근거로 송파 실측을 든다. **송파에서만 참이다.** 내 실측:

| | 상한 120 | 상한 200 |
|---|---|---|
| 강남 (조건 없음) | 후보 123 | **후보 151** |
| 강남 59~85㎡ | 후보 83 | **후보 195** |
| 광진 (조건 없음) | 후보 140 | **후보 167** |
| 송파 (조건 없음) | 후보 200 = 상한 | 200 (주석대로) |

즉 상한을 올리면 **사용자가 보는 후보가 실제로 늘어난다.** 120 의 정당화는 **시간 예산**
(+0.9~1.0초)이지 "결과 불변"이 아니다. 값은 그대로 둬도 좋다 — 틀린 것은 이유다.
이 저장소는 주석을 근거로 취급하므로(그래서 다음 사람이 이 문장을 믿고 200 을 배제한다)
사실과 맞춰야 한다.

*통과 조건*: 해당 3줄을 실측대로 정정 — "송파처럼 단지가 조밀한 곳은 120 에서 이미
`MAX_CANDIDATES` 에 닿지만 강남·광진은 200 까지 후보가 계속 는다. 120 은 **시간 예산**
(조립 단지당 ~13ms · 50→120 이 +1.0초)으로 고른 값이다."

**CR32-3 (low) — 금액 가드 우회가 인정된 것보다 넓다: 인용문이 *주제어*를 포함하면 뚫린다**

담당자는 "`zone_name` 이 통째로 금액 문자열이면 인용으로 취급됨"만 인정했다. 직접 뚫어 본
결과 **주제어 쪽이 더 넓다** — `strip_source_quotes` 가 인용문의 **모든 출현**을 지우는데,
검사가 `topic AND money` 라서 **주제어가 지워지면 그것만으로 통과**한다:

```
우리 문장: "분담금은 약 1.2억원으로 예상됩니다."
  quotes=()            -> BLOCKED   (정상)
  quotes=('강남구',)     -> BLOCKED   (정상)
  quotes=('분담',)       -> PASS  ← 우회
  quotes=('분담금',)     -> PASS  ← 우회
  quotes=('억원',)       -> PASS  ← 우회
  quotes=('1.2억',)     -> PASS  ← 금액 토큰의 일부만으로도 우회
  quotes=('1.2억원',)   -> PASS  (담당자가 인정한 형태)
```

**차단하지 않는다.** 뚫리려면 ① 개발자가 없는 금액을 지어내고 ② 같은 요청의 수집값이
그 토큰(또는 주제어)을 **정확히** 품고 있어야 한다 — 결합 확률이 무시할 만하고, 이 함수는
런타임 방어가 아니라 개발자 문장 lint 다. 다만 **값싼 강화가 있다**:

*통과 조건(권고)*: 검사를 갈라라 — **주제어는 원문 전체**에서, **금액만 인용 제거본**에서
찾는다. CR31-1(구역명의 금액으로 job 이 죽는 것)은 그대로 고쳐지면서 주제어 우회가 완전히
닫힌다. 지금 문서에 적힌 *"우리 서술 부분은 그대로 다 본다"* 와도 더 잘 맞는다.
(더 가면: 금액 매치의 **위치**가 인용 구간 안인지 보면 `1.2억` 부분일치 우회도 닫힌다.)

**CR32-4 (low) — `detail.cost_guard_error` 가 API 응답에 실린다 (일관성 결함)**

`orchestrator.py:561` 이 `str(exc)` 를 `detail` 에 넣고 `_redev_dict` 가 `dict(assessment.detail)`
을 통째로 payload 에 싣는다. 실물:

```json
"detail": {"cost_guard_blocked": true,
           "cost_guard_error": "추가분담금 금액은 공개 데이터에 없습니다 — 지어낸 숫자를
                                출력할 수 없습니다(주제어 '분담' + 금액 '1.2억원'). …"}
```

민감정보는 아니고(매치된 토큰 2개뿐, 사용자 자산·내부 ID 없음) 화면도 렌더링하지 않는다.
다만 바로 위 `RedevAssessment.source_quotes` 에는 *"응답 payload 에는 싣지 않는다(사용자에게
의미 없는 내부 출처 표식이다)"* 라고 주석까지 달아 놓고 **내부 lint 메시지는 싣는다** —
같은 판단 기준이 두 필드에 다르게 적용됐다.
*통과 조건*: `cost_guard_error` 를 `logger.exception` 에만 남기고 payload 에서 빼거나,
싣는다면 왜 이건 괜찮은지 한 줄 근거를 남길 것.

**CR32-5 (low) — `client.ts` 주석이 이번 라운드에 거짓이 됐다**

`frontend/src/api/client.ts:110-111`:
> `특성 태그(역세권·재건축)용 사실값. **지도 응답에는 아직 오지 않는다** — 없으면 모름으로
> 다뤄 태그를 달지 않는다. 서버가 실어 주는 날 자동으로 붙는다.`

MAP-2 가 바로 그 "실어 주는 날"인데 문장이 남았다. 같은 파일을 이번에 46줄 고치면서
놓쳤다. *통과 조건*: 한 줄 정정.

**CR32-6 (low) — 죽은 `backdrop-filter` 가 남아 시각 효과 없이 비용만 낸다**

`--material` 이 불투명이 된 뒤 아래 선언들은 **아무 효과가 없다**:
`MapLegend.css:7-8` · `MapView.css:72-73`. 함께 붙은 `@supports not (backdrop-filter…)`
폴백 블록(`MapLegend.css:14` · `MapView.css:78`)도 죽었다 — 폴백이 넣는 `--bg` 가
이제 `--material` 과 같은 값이다. 순수 잉여가 아니다: `backdrop-filter` 는 합성 레이어
승격을 강제하고 일부 엔진은 블러를 계산한 뒤 버린다 — 지도 위 오버레이라 모바일에서 손해다.
*통과 조건*: 6줄 + `@supports` 블록 2개 삭제.

**CR32-7 (info) — 가중치가 전부 0 이면 화면과 서버가 다른 말을 한다 (이번 라운드 산물 아님)**

`sum<=0` 일 때 `normalizeWeights`/`effectiveWeights` 는 `DEFAULT_WEIGHTS` 를 보이고,
서버 `normalize_weights` 는 `{}` 를 돌려 **`agent_scores` 폴백**으로 간다(9케이스 교차검증에서
유일한 불일치). UI 로는 도달 불가하고(전부 0 저장 시 프론트가 기본값으로 되돌림) 서버가
`NOTE_NO_WEIGHTS` 로 고지하므로 조용하지 않다. 기록만 한다.

### 이월

* **CR31-1 → CLOSE**(위 검증). **CR31-2 → CLOSE**(카드 단위 고지 구현·표시 조건까지 정당).
* **CR31-3 / CR31-4 / CR31-5 → OPEN 유지** (이번 라운드 범위 밖).
* **CR30-4 → OPEN 유지(low)** — `*must_verify` 는 이제 `source_quotes` 로 인용분이 빠지므로
  CR31-1 과 같은 자리라는 우려는 해소됐다. 변이 SURVIVED 성질만 남는다.
* PREF-1 · SCHOOL-2/3/4/5 · COND-1 · FE-PLAIN-1 · REDEV-W1 · POI-2 · SCORE-1 ·
  DEPLOY-2/3 · REC-2/4 · OPS-1 · SEC-4 · ADM-3 · JOB-2 이월.

---

### 판정

**PASS — 커밋 가능. 배포는 `CR32-1`(nginx gzip) 을 함께 처리할 것.**

차단하지 않는 이유를 분명히 한다. **차단 사유 넷 중 어느 것도 없다** — 정확성 결함 0
(실측 1,800 판정 불일치 0 · 성능 목표 6배 여유 · 진단 재현 성공), 보안 냄새 0,
핵심 로직 테스트 부재 0(신규 5파일 포함 +52 테스트, 레지스트리 축은 API 전 구간 증명),
레이어 위반 0.

**오탐 관점에서도 통과다.** 이번 라운드의 핵심 변경(CR31-1)은 방어를 더 촘촘히 짜는 대신
**정상 동작을 막던 방어를 걷어낸** 것이고, 걷어낸 자리가 정확한지 직접 뚫어 확인했다 —
발화 4종이 살아나고 인용 밖 금액은 여전히 막힌다. `_MONEY_RE` 도 잡음(`3원`)만 줄이고
실금액은 전부 유지한다. 방어가 정상을 막는 자리는 못 찾았다.

새 발견 6건은 전부 **비차단**이다. `CR32-1` 만 medium 이고 그것도 코드가 아닌 배포 설정
한 줄이며, 나머지는 주석 정확성·죽은 코드·일관성이다. `CR32-3` 은 값싼 강화를 권고하지만
차단하지 않는다 — **차단은 결과로 정당화되어야 하고**, 이 우회는 개발자가 없는 금액을
지어내는 동시에 수집값이 그 토큰을 정확히 품어야 성립한다.

> 이번 라운드에서 가장 값어치 있는 것은 **복구 사고를 숨기지 않은 것**이다.
> 덕분에 스냅샷·트랜스크립트가 남아 제3자가 바이트 단위로 재검증할 수 있었다.
> 다만 교훈은 복구 기술이 아니라 그 앞이다 — **작업본을 공유하는 동안 `git checkout --`
> 은 되돌리기가 아니라 남의 작업 삭제다.** 원본 바이트 + md5 단언으로 되돌리는 러너가
> 이미 저장소에 있었는데 쓰이지 않았다. 도구가 없어서 난 사고가 아니다.

---

## CR-033 · 2026-07-28 · 시점 보정 배선 · 분담금 가드 재설계 · school_quality · fetch_academy

**리뷰어** code-reviewer · **대상** `077c2e5` 이후 미커밋 20파일 수정 + 신규 9 ·
**판정 ⛔ FAIL** (차단 2건 — `CR33-1` · `CR33-3`. 둘 다 이번 라운드 산물이고 둘 다 고치기 싸다)

### 실행 검증 (전부 직접 돌림)

| 항목 | 주장 | 실측 | 결과 |
|---|---|---|---|
| 백엔드 | 1,268 passed / 78 skipped / 0 failed | junitxml `tests=1346 skipped=78 failures=0 errors=0` → **1,268 passed** | ✅ 정확히 일치 |
| 프론트 | 736 passed / 41 files | `Test Files 41 passed · Tests 736 passed` | ✅ |
| 빌드 | — | `vite build` exit 0 · `tsc --noEmit` exit 0 | ✅ |
| 줄바꿈 | — | 20개 수정 파일 전부 실질 hunk 있음. 줄바꿈만 바뀐 파일 **0건** | ✅ |
| 운영 DB | 지수 2,381행 | `sido 3지역 93행 + sigungu 79지역 2,288행 = 2,381` · method 1종 | ✅ 정확히 일치 |

---

## ★ 최우선 판정 — 시점 보정은 **옳은 방향이다. 예전 결과가 틀렸던 것이다**

먼저 결론부터. **보정을 켠 것이 맞고, 그 전에 사용자가 본 '예산 안 259건'은 근거가
없는 숫자였다.** 7건이 빠진 것은 새 결함이 아니라 없던 잣대가 생긴 것이다.

근거를 순서대로 확인했다.

**① 고치려는 결함이 실재한다.** `fair_price_band` 는 6~36개월 창의 **명목가**를 그대로
섞어 중위를 낸다. 시장이 움직였으면 그 중위는 어느 달의 가격도 아니다. 운영 DB 에
적재된 지수(내가 직접 읽음, `scope='sido'`)로 확인:

```
서울(11)  2025-01 0.954294 → 2026-06 1.132986   (+18.7%)
경기(41)  2025-01 0.983530 → 2026-06 1.048664   (+ 6.6%)
인천(28)  2025-01 1.002350 → 2026-06 1.012918   (+ 1.1%)
```

시장은 멈춰 있지 않았고, **지역마다 크기가 다르다.** 보정하지 않으면 서울 후보만
조직적으로 싸 보인다 — 표시 편향이 아니라 **지역 편향**이다.

**② 보정 결과가 지수와 정합한다.** 12개월 창 기준 기대 이동폭을 적재값으로 직접 계산하면
서울 `1.1330 / mean(2025-07~2026-06) 1.0598 = +6.9%`, 6개월 창은 `+3.7%`, 18개월 창은
`+9.8%`. 담당자 보고(전체 중위 **+7.30%**, 6개월 +1.2% / 24개월 +5.3%)는 이 범위 안이고,
6개월 창이 내 균등가정보다 작은 것은 실제 거래가 최근 달에 몰려 있기 때문으로 설명된다.
**보고된 숫자는 지어낸 것이 아니다.**

**③ 방법이 옳다.** 중위에 계수 하나를 곱하지 않고 **거래를 각각 환산한 뒤 분위수를 낸다**
(`adjust_trades`). 창 안 거래 시점이 한쪽으로 쏠려 있어도 맞는 답이 나온다.
`test_각_거래를_개별_보정한다_중위에_계수를_곱하지_않는다` 가 그 성질을 직접 고정한다.

**④ 방향이 데이터에서 나온다.** 하락 지수를 주면 밴드가 **내려간다**
(`test_하락장에서는_보정이_밴드를_내린다`). "항상 올리는 보정"이 아니다.

**⑤ 못 하면 안 하고, 안 했다고 말한다.** 지수 없음·기준월 없음·커버리지 미달·표본 미달·
배율 이상 다섯 경로가 전부 `TimeAdjustment.reason` 을 남기고, 그게 카드
(`price_band.time_adjustment.reason`)·리스크·결과 notes 세 곳에 나온다. 내가 실행해
확인했다 — `indexes={}` 로 돌리면 `applied=false` + `REASON_NO_INDEX` + notes 문장이 뜬다.

**⑥ 추정치의 방향이 안전한 쪽이다.** 지수 추정량(`exp(median(ln(₩/㎡) − 그룹평균))`)은
거래 기간이 짧은 그룹이 잔차를 0 쪽으로 끌어당겨 **변화폭을 과소추정**한다.
`MIN_GROUP_MONTHS=2` 로 일부만 막는다. 즉 이 보정은 **덜 올리는 쪽으로 틀린다** —
후보를 과하게 쳐낼 위험보다 덜 쳐낼 위험이 크다. 스크리닝 도구에서는 맞는 방향이다.

> 따라서 "지금까지 사용자가 '예산 안'이라 믿고 봤다"는 것은 **보정을 막을 이유가 아니라
> 서둘러 켤 이유**다. 다만 켜는 방식에 결함이 둘 있고, 그건 아래에서 차단한다.

### 남은 약점 (판정에 영향 없음, 기록)

* `MAX_ADJUST_RATIO=2.0` 은 **현실적 고장을 못 잡는다.** 실측 최대 구간의 두 배라
  "지수가 통째로 깨진 경우"만 걸린다. 실제로 무서운 실패는 "+5% 가 맞는데 +25% 로 나오는
  것"이고 이 가드는 그걸 통과시킨다. 값을 조이라는 뜻이 아니라, **이 가드를 정확도 보증으로
  읽지 말라**는 뜻이다.
* `MIN_INDEX_MONTH_SAMPLE=50` · `MIN_REFERENCE_MONTH_SAMPLE=150` 의 근거는 **타당하다.**
  중위의 점근 표준오차 `1.253σ/√n` 에 실측 로그잔차 sd(서울 0.1013)를 넣으면 n=50 → ±1.8%,
  n=150 → ±1.0% 로 주석 숫자가 그대로 재현된다. 기준월에만 문턱을 높인 논리도 옳다 —
  개별 월 오차는 여러 거래에 흩어져 중위에서 상쇄되지만 **기준월 오차는 모든 거래에 같은
  방향으로 곱해진다**(공통모드). 상쇄되지 않는 오차에 더 큰 표본을 요구하는 것이 맞다.
  단, 이 ±는 **표집오차만**이다. 지배적인 오차는 위 ⑥의 설정오차이고 그건 n 으로 줄지
  않는다 — 주석이 "지수가 ±1% 정확하다"로 읽히지 않게 한 줄 보태면 좋다.

---

## ⛔ CR33-1 (medium · **차단**) — 기준월이 '아직 진행 중인 달'인 지역이 운영에 4곳 있다

`timeadjust` 규칙 3 은 이렇게 적혀 있다.

> **기준월은 '오늘'이 아니다.** … 덜 찬 달을 기준으로 삼으면 추정치가 며칠 뒤 이유 없이 바뀐다.

**운영 DB 에서 그 일이 이미 일어나 있다.** 내가 읽은 `market_price_index` 실측:

```
scope=sigungu 기준월 분포 (is_complete AND sample_size>=150 인 달 중 max)
  2026-07 : 4곳   ← ★ 오늘(2026-07-28) 기준 **진행 중인 달**
  2026-06 : 47곳
  2026-05 : 14곳 · 2026-04 1 · 2025-10 1 · 2025-06 1 · 2025-03 1 · 2024-10 1 · 2024-08 1 · 2024-06 1
  기준월 없음 : 7곳
scope=sido : 3곳 모두 2026-06 (2026-07 은 전부 is_complete=false — 여기선 옳게 걸렀다)
```

문제의 4곳과 그 값:

| region | 이름 | 단지수 | idx 2026-06 | **idx 2026-07** | n(07) | is_complete(07) |
|---|---|---|---|---|---|---|
| 41113 | 수원시 권선구 | 201 | 1.050590 | **1.068485** | 417 | **t** |
| 41370 | 오산시 | 120 | 1.006475 | **1.021605** | 291 | **t** |
| 41461 | 용인시 처인구 | 187 | 1.029180 | **1.048713** | 181 | **t** |
| 41595 | 화성시 병점구 | 73 | 1.039402 | **1.056266** | 308 | **t** |

**합계 581 단지 / 전체 16,462 = 3.5%.**

**왜 이렇게 됐나.** `_complete_flags` 는 그 달 건수를 **직전 6개(보존된) 달의 중위**와 비교해
80% 이상이면 완결로 본다. 위 4곳은 7월 건수가 그 중위의 78~98% 라 통과한다. 그런데
7월은 아직 끝나지도 않았고 신고 지연(최대 30일)도 안 지났다. **달력을 안 보기 때문에
'끝나지 않은 달'을 완결로 부를 수 있다.**

**왜 이번 라운드의 문제인가 — `_freshest_index` 가 이걸 *선호*한다.**
`max(usable, key=lambda i: (i.reference_ym, ...))` 이므로 `2026-07 > 2026-06`,
즉 이 4곳의 후보는 **시도 지수(2026-06)를 제치고 진행 중인 달로 환산된다.**
낡은 기준월을 피하려고 넣은 규칙이 정확히 반대편 함정을 밟는다.

**결과 셋 (전부 이 저장소가 이름 붙여 금지한 것):**

1. **재현 불가.** 같은 코드·같은 사용자 조건으로 며칠 뒤 배치를 다시 돌리면
   `idx(2026-07)` 이 바뀌고 밴드가 바뀐다. 새 정보가 하나도 없는데 **예산 경계의 후보가
   뒤집힌다.** 규칙 3 이 막겠다고 선언한 바로 그 현상이다.
2. **선택편향.** 7월 28일까지 신고된 7월 거래는 무작위 표본이 아니다. 담당자 본인이
   미등기 가설을 기각하며 측정한 값 — *같은 (단지,면적,계약월) 안에서 미등기가 등기보다
   +0.5~2.2% 비싸다* — 이 그대로 적용된다. 진행 중인 달의 지수는 위쪽으로 치우친다.
   실제로 이 4곳의 `idx(07)/idx(06)` 는 **+1.50 ~ +1.90%** 다.
3. **비교 불능 재발.** `_freshest_index` 를 넣은 이유가 "한 목록 안에서 후보마다 시점이
   다르면 한 예산으로 못 잰다"였는데, 이 4곳 후보는 `2026-07 시점 환산`, 나머지는
   `2026-06 시점 환산` 으로 **다시 갈린다.** `time_adjust_notes` 가 `"·"` 로 이어 붙여
   여러 기준월을 나열하는 것 자체가 이 상태를 전제하고 있다.

**덧 — 반대 방향 오탐도 적재값에 있다.** 서울 시도 `2025-07`·`2025-08`·`2025-11`·`2025-12`
가 1년이 지난 지금도 `is_complete=false` 다(2025-06 이 9,981건인데 2025-07 이 3,630건이라
비율에 걸림). 즉 이 판정은 "신고가 정착했는가"가 아니라 **"거래량이 최근 대비 많은가"**
를 재고 있다. `_complete_flags` docstring 의 *"건수는 거짓말하지 않는다"* 는 적재된
데이터가 양방향으로 반증한다.

**통과 조건**
* `_complete_flags` 에 **달력 하한**을 AND 로 추가한다 — `ym` 이 완전히 지났고
  신고 지연(30일)까지 지난 달만 완결 후보가 될 수 있다(`ym < ym_of(as_of - 30일)`).
  건수 검사는 **그대로 둔다**(수집 누락을 잡는 역할은 유효하다). 순수 함수 유지를 위해
  `build_index(..., as_of=)` 로 날짜를 주입할 것.
* 테스트 1건 추가: **"진행 중인 달은 표본이 많아도 완결이 아니다."** 지금 스위트에는
  `test_표본이_급감한_달은_미완결로_표시된다`(감소 케이스)만 있고 이 케이스가 없다 —
  그래서 운영에서 4곳이 통과했는데 테스트는 전부 초록이었다.
* 고친 뒤 **배치 재실행**(48.7초) + 위 쿼리로 `sigungu` 기준월에 `2026-07` 이 0곳임을 확인.

---

## ⛔ CR33-3 (medium · **차단**) — 카드가 보정된 값을 여전히 "국토교통부 실거래가"라고 부른다

백엔드는 이 라운드에서 **값의 이름을 정확히 부르려고 상당한 공을 들였다.**

* `models.PriceBand.to_evidence` — *"보정된 숫자를 원본 실거래 중위처럼 내보내면 안 된다 — 다른 값이다"* → claim 이 `2026-06 시점 환산 중위 …원` 으로 바뀐다.
* `orchestrator._price_band_dict` — `as_of_ym` · `time_adjusted` 를 새로 싣고 주석에 *"표시 문구가 여기서 갈린다"*.
* 예산 초과 제외 사유 — `f"{band.as_of_label} 시점 환산 중위 {price:,}원(추정)"`.

**그런데 프론트가 그 필드를 받지 않는다.**

| 위치 | 실제 렌더 |
|---|---|
| `frontend/src/api/client.ts:282-290` | `interface PriceBand` 에 `as_of_ym`·`time_adjusted` **없음** |
| `frontend/src/components/ReportCard.tsx:126-133` | `적정가 밴드 … 중위 {median} (**국토교통부 실거래가** · 최근 N개월 M건)` |
| `frontend/src/lib/recommendation.ts:55` | 헤드라인 가격 라벨 = `"최근 실거래 기준 추정가"` |
| `orchestrator.py:1500` | `price_note` = `TRADE_BASIS_NOTE` — 기준월 언급 **없음** |

즉 **같은 숫자가 두 이름을 갖는다.**

```
예산 초과로 제외된 후보 → "2026-06 시점 환산 중위 20.73억원(추정)"   ← 정직
추천 목록에 남은 후보   → "중위 20.73억원 (국토교통부 실거래가)"      ← 국토부가 준 값이 아니다
```

떨어진 후보에게만 진실을 말하고 통과한 후보에게는 말하지 않는다. 그리고 이 값은
**호가가 없는 후보에서 곧 예산 판정 기준가**이므로(운영 listing 0행 → 사실상 전 후보)
"이 숫자가 어느 시점 값인가"는 부가 정보가 아니라 값의 정의다.

**차단하는 이유.** 이 라운드가 직접 만든 불일치이고(`_price_band_dict` 주석이 스스로
"표시 문구가 여기서 갈린다"고 적어 놓고 갈리지 않았다), 배선 테스트 파일이 서두에서
경고한 실패 형태 — *"계산은 맞는데 아무 데도 연결되지 않는 것"* — 가 한 계층 바깥에서
그대로 재현됐다. 그리고 프론트 736건 중 이 문구를 보는 테스트가 하나도 없다.

**완화(그래서 medium 이지 high 가 아니다).** job 단위 notes 는 렌더된다
(`RecommendPanel.tsx:306`) — `"적정가 밴드는 2026-06 시점으로 환산했습니다(…)"` 가 목록
상단에 한 번 나온다. **조용하지는 않다.** 그러나 숫자 옆의 이름은 여전히 틀렸다.

**통과 조건**
* FE `PriceBand` 에 `as_of_ym?: string | null` · `time_adjusted?: boolean` 추가.
* `ReportCard` 밴드 줄과 `priceView` 라벨에 기준월을 박는다
  (예: `중위 20.73억 (2026-06 시점 환산 · 국토부 실거래가 + 자체 시장지수 · 최근 24개월 37건)`).
  보정된 값의 출처를 **"국토교통부 실거래가"만으로 적지 말 것** — 우리 계산이 섞여 있다.
* 테스트 1건: *"보정된 밴드는 카드에서도 환산 시점을 말한다 / 보정 안 된 밴드는 말하지 않는다."*

---

## `_freshest_index` — **규칙은 옳다. 있는 자리가 틀렸다**

### 규칙 판정: **옳다** (운영 실측으로 확인)

담당자가 발견한 현상은 사실이다. 위 표대로 시군구 기준월은 2024-06 부터 2026-07 까지
흩어져 있고, 시도 3곳은 전부 2026-06 이다. 담당자가 든 5개 극단 사례
(용산 2025-03 · 중구 2025-06 · 과천 2024-06 · 광주 2024-10 · 인천동구 2024-08)는
내 조회에서 **정확히 그 5개 값이 각 1곳씩** 나온다 — 지어낸 사례가 아니다.
(뒤처진 곳 수는 내 계산으로 **27곳**(기준월 있는 20 + 없는 7)이고 보고는 28곳이다.
경계 정의 차이로 보이며 결론에 영향 없다.)

"시군구 우선"을 그대로 쓰면:
* 상승장에서 2024-06 기준으로 환산 → 값이 **내려간다**. 밴드가 낮아 못 사는 단지를
  통과시키는 문제를 고치려다 그 지역에서 더 키운다. 보고된 중구 남산타운
  15.00억 → 13.16억(−12.3%)은 이 메커니즘으로 정확히 설명된다.
* 한 목록 안에서 후보마다 시점이 달라진다. **잣대 하나(예산)로 재는 목록에서 잣대가
  후보마다 다른 것**은 정밀도 손실이 아니라 판정 무효다.

그래서 **정밀도(시군구)보다 시점 일치(최신 기준월)를 앞세운 것은 맞다.** 이는
`select_index` 가 이미 택한 판단("구멍 뚫린 정밀한 지수보다 거친 시도 지수가 낫다")과
같은 방향이며, 기준월이 같으면 시군구를 쓰는 tie-break 도 옳다.

### 위치 판정: **틀렸다 → `CR33-2` (medium, 비차단)**

`_freshest_index` 는 `MarketIndex` 와 `TradeRow` 만 받아 `MarketIndex` 를 돌려주는
**순수 도메인 함수**다. 배선 고유의 것이 한 줄도 없다. 그런데 `orchestrator.py` 에 있고,
그 결과 **도메인 모듈이 폐기된 정책을 계속 공개 API 로 선언한다**:

```python
# timeadjust.py:243  (지금도 이렇게 적혀 있다)
def select_index(...):
    """시군구 지수를 우선하되, 이 거래들을 못 덮으면 시도로 내려간다."""
```

문제는 문서가 낡은 것이 아니라 **그 문서대로 쓰면 버그가 난다**는 것이다.
`fair_price_band(index=select_index(...))` 는 timeadjust 가 안내하는 정식 사용법이고,
그 경로는 남산타운 −12.3% 를 그대로 낸다. 다음 사람은 orchestrator 를 읽을 이유가 없다.
게다가 `test_valuation_timeadjust.py:337-360` 이 **도메인 계층에서 옛 정책을 못박고**
있어서, 두 파일이 서로 다른 정책을 각각 테스트로 고정한 상태다.

*통과 조건*: 기준월 우선 규칙을 `select_index` 안으로 옮긴다(또는
`select_index(..., prefer_freshest=True)` 를 기본값으로). `candidate_index` 는
**키 조회 + 사유 남기기 폴백**만 남긴다 — 그건 진짜 배선이다.
`test_valuation_timeadjust.py` 의 선택 테스트도 함께 옮길 것.

> 레이어 '위반'으로 부르지는 않는다. orchestrator 가 도메인 함수를 조합하는 것은 제 일이고,
> 실제 결함은 **`select_index` 가 거짓을 말하게 된 것**이다. 그래서 medium·비차단으로 둔다.

### `candidate_index` 의 폴백 사슬 — **판정: 옳다**

`_freshest_index` → `select_index` → 점 있는 지수 → 빈 지수 순으로 내려가며
**끝까지 None 을 안 돌려주는** 설계는 처음엔 과해 보이지만 맞다. `fair_price_band` 는
`index=None` 이면 `time_adjustment` 를 통째로 비우는데, 그건 "보정 못 함"이 아니라
"시도조차 안 함"이라 **왜 안 됐는지가 응답에서 사라진다.** 빈 `MarketIndex` 를 넘겨
`adjust_trades` 가 `REASON_NO_INDEX` 를 남기게 하는 것은 값을 지어내는 것이 아니다
(점이 0개라 보정은 구조적으로 불가능하다). 실행해서 확인했다.

---

## 분담금 가드 — **내가 뚫었던 5종 중 4종이 닫혔다. 6번째는 새 구현의 결함이 아니다**

### CR32-3 재시도 — 직접 다 태웠다

```
우리 문장: "분담금은 약 1.2억원으로 예상됩니다."
  quotes=()          -> BLOCK
  quotes=('강남구',)   -> BLOCK
  quotes=('분담',)     -> BLOCK   ← 예전 PASS (뚫렸던 것)
  quotes=('분담금',)   -> BLOCK   ← 예전 PASS
  quotes=('억원',)     -> BLOCK   ← 예전 PASS
  quotes=('1.2억',)   -> BLOCK   ← 예전 PASS
  quotes=('1.2억원',) -> PASS     ← 잔여 A8 (인정된 것)
```

**치환을 버리고 위치로 판정한 것이 정확한 처방이었다.** 원문을 안 바꾸므로 외부값이
검사어를 가를 수 없고(SR27-2 의 본체), 인용문이 금액을 **일부만** 덮는 경우가 닫힌다.

### CR31-1 회귀 — **현실 경로로도 안 죽는다**

`assert_no_cost_estimate` 단위가 아니라 `assess_redevelopment` 전 경로에 11종을 태웠다.
전부 정상 판정(예외 0):

```
1억원지구 · 제3원구역 · 700,000,000원구역 · raw_stage='조합설립(추정 5000만원)'
zone_name='분담' · raw_stage='분담' · zone_name='반포주공1234' · sigungu='3억원시' …
```

동시에 `_log_money_like_quotes` 가 `'1억원지구'→['1억원']` 처럼 **막지 않되 기록**한다 —
조용히 넘어가는 것과 막지 않는 것을 구분한 처리가 실물로 작동한다.

### CR32-4 (진단문 유출) — **해소 확인**

`cost_guard_error` 는 저장소 전체에서 사라졌다(남은 것은 "예전에는 이랬다"는 docstring 한 줄).
테스트가 특정 키가 아니라 **카드 JSON 전체를 `json.dumps` 해서 금액 토큰 5종을 훑는다** —
다음 사람이 다른 키로 같은 값을 실어도 잡힌다. 그리고 조용해지지 않았다: verdict·missing·
결과 notes·운영 로그 네 곳에 "판정하지 못했다"가 남고, 로그에는 원인 문자열이 남는다
(`caplog` 로 단언). **한 값이 두 독자를 겸하려다 샜다**는 진단이 정확하고 처방도 맞다.

### 6번째 우회 — 찾았다. 다만 **새 구현이 만든 것이 아니다**

```
"분담금은 약 일억 이천만 원으로 예상됩니다."     -> PASS   (한글 수사 — \d 불일치)
"조합원 추가 납부액은 약 1.2억원입니다."          -> PASS   (주제어 회피 — '추가\s*비용' 불일치)
"분담금은 약 ￦120,000,000 입니다."               -> PASS   ('원' 없음)
```

셋 다 `_MONEY_RE` / `_COST_TOPIC_RE` 의 원래 성질이고 이전 라운드에도 있었다.
새 구현 고유의 것은 A8 계열 둘뿐이며 둘 다 비현실적이다 — 두 인용문이 금액을 나눠 덮기,
2글자 인용 `'1억'` 이 2글자 금액 `1억` 을 덮기(수집값이 정확히 `"1억"` 이어야 한다).

**차단하지 않는다.** 이 함수는 런타임 방어가 아니라 **개발자 문장 lint** 이고, 이
코드베이스가 실제로 쓰는 금액 표기(`f"{v:,}원"`)는 전부 잡힌다. 다만
`assert_no_cost_topic` 에는 *"완전하지 않다"* 가 적혀 있는데
`assert_no_cost_estimate` 에는 없다 — 있는 편이 정직하다 → `CR33-8`.

### 잔여 2건 판정

* **D1(필드 분리) — 판단 타당.** 텍스트를 이어 붙여 검사하면 `rationale` 의
  `COST_DISCLOSURE` 주제어가 **모든 필드에 전이**돼, 어느 필드든 금액처럼 읽히는 토큰
  하나로 job 이 죽는다. 그건 CR31-1 을 더 큰 규모로 재현하는 것이다. 필드 단위가 맞다.
* **A8 — 판단 타당. 값싼 강화는 있다.** 인용문 **전체가 금액 토큰 하나로 소진되면**
  인용으로 인정하지 않으면 된다(`1억원지구` 는 금액보다 길어 계속 통과, `1.2억원` 은 막힘).
  권고이며 차단 아님 → `CR33-8` 에 함께.

---

## school_quality — **판정은 옳다. 다만 "서명이 가장 강한 방어선"은 과장이다**

**게이트는 실제로 잠겨 있다.** `COMPARABLE_ACHIEVEMENT_SOURCES` 가 빈 집합이라
`_screen` 의 허용목록 검사에서 **모든 근거가 탈락**한다 → `usable` 이 절대 안 채워진다 →
`assess_school_district_tag` 는 어떤 입력에도 `unavailable` 을 낸다. 코드로 확인했다.

**거절 사유 순서도 옳다.** 임계값 검사를 근거 검사 **뒤**에 둔 것 — 임계값 부재는
근거 부재의 *결과*이므로 앞에 두면 원인이 화면에서 사라진다. 테스트가 이 순서를 고정한다.

**질문에 답한다 — 서명 방어는 유효하되 '가장 강한' 것은 아니다.**
서명에 거리 인자가 없는 것은 *이 함수*를 거리로 통과시키지 못하게 할 뿐이고, 다른 곳에서
거리로 배지를 만드는 것은 못 막는다. 실제로 태그를 잠그고 있는 것은 ① 빈 허용목록
② 어디에도 배선되지 않음 ③ `TOP_PERCENTILE_THRESHOLD=None` 이다. 서명 고정 테스트는
유지 가치가 있다(다음 사람이 "거리도 같이 받자"고 할 때 정직하게 실패한다) — 문구만
낮출 것 → `CR33-7`.

**인용한 원천 설명의 실재 여부 — 재검증하지 않았다(명시).**
학교알리미는 세션·캡차 기반이라 실호출 재현이 리뷰 범위를 넘는다. 대신 확인한 것:
인용 원문이 **`school_quality.py` docstring 과 `config/sources.yaml: school_achievement`
두 곳에 원문 그대로 보존**돼 있고 서로 일치하며, "공시기관: 중, 고" 라는 진술이
①(초등 원천 부재)과 ②(교내 평가라 비교 불가)를 동시에 설명해 **내부 정합이 맞다.**
검증 가능한 형태로 남긴 것은 인정한다. 다만 *"실호출로 확인했다"* 는 이 리뷰가 보증하지 않는다.

**구조 기록(info).** `school_quality.py:220-251`(임계값 이후 판정·evidence 생성)은
빈 허용목록 때문에 **운영에서 도달 불가능**하고, 318줄 테스트가 monkeypatch 로만 태운다.
"켜는 날의 계약"이라는 의도는 이해하지만 사실은 기록해 둔다.

---

## 테스트 불안정 교체 — **옳다. 저장소 전체를 훑어 같은 형태가 더 없는지 확인했다**

`@parametrize("source", sorted(sq.NON_COMPARABLE_ACHIEVEMENT_SOURCES))` 는 모듈 집합이
비는 순간 **케이스 0개**가 되어 검사가 실패 없이 사라진다(테스트 수만 줄고 아무도 안 본다).
하드코딩 목록 + 일치 검사(`test_거절목록이_테스트_기대와_일치한다`)로 바꾼 것이 맞다.

**같은 형태가 더 있는지 전수 확인했다.** `parametrize` 에 비-리터럴 컬렉션을 쓰는 곳은
7군데인데, 나머지 6군데(`PROOFS` · `_NAME_ORDERINGS` · `SEOUL_RAW_STAGES+INCHEON_RAW_STAGES`
· `_COST_BYPASSES` · `PROTOCOLS` · `test_deploy_config.py`)는 전부 **같은 테스트 파일 안의
리터럴**이라 앱 코드 변경으로 비지 않는다. **유일한 위험 지점이 정확히 이곳이었다.**

**autouse tripwire 는 과하지 않다.** 비용은 테스트당 상수 비교 2회(≈0), 이득은 진단 문장
하나다. 다만 근거는 바뀌었다 — 원래 가설(전역 누수로 인한 간헐 실패)은 25회·6시드·37조합에서
**재현되지 않았다.** fixture 주석이 그 사실을 스스로 적어 둔 것은 정직하다. 유지 찬성.

---

## fetch_academy — **감지는 확실하다. 우회는 관측된 고장에는 없다**

**감지가 이중이다.**
* ⓐ `page==1 and total > len(rows) and pSize > len(rows)` — 무키 5행 상한을 **첫 요청에서**
  잡는다. 2페이지를 받아 볼 필요도 없다.
* ⓑ 연속 페이지 서명 일치 — pIndex 무시를 잡는다.
둘 다 `FetchError` 를 던지고 **파일을 쓰지 않는다.** 잘린 원문이 성공으로 남지 않는다.

**우회 가능성.** ⓑ 만으로는 서버가 1,2,1,2 로 번갈아 주면 못 잡고, `total` 파싱이 실패해
`None` 이면 ⓐ 가 꺼진다. 그러나 관측된 고장(같은 5행 반복)에는 ⓐ 하나로 충분하므로
**실질 위험 없음.**

**오탐 쪽이 더 신경 쓰인다(비차단).** ⓐ 는 정상 상황에서도 page 1 이 pSize 보다 짧게 오면
발화하고, `raise` 가 office 루프 **밖으로** 나가 3개 교육청 수집이 통째로 중단된다.
NEIS 는 pSize 를 정확히 채우므로 확률은 낮다.

**부분 수집이 exit 0 이다 → `CR33-6`.** `failures` 가 비지 않아도(예: "총 70,000행 중
3,000행만 수신") `main()` 은 0 을 돌려준다. 로그 warning 과 파일 안 `failures` 로 남으니
조용하지는 않지만, cron 은 성공으로 읽는다.

**`zone_academic` 이 행을 센다 → `CR33-5`.** `fetch_academy.py:268` 이
`zone_academic[...] += 1` 을 **행 단위**로 올린다. 모듈 docstring 이 스스로
*"행 수를 세면 종합학원이 있는 동네가 부풀어 보인다 — 이 통계가 태그 임계값의 모집단이
되므로 여기서 틀리면 전부 틀린다"* 라고 경고한 바로 그 형태다. 지금은 `len()` 만 쓰여
무해하지만, 값이 쓰이는 날 정확히 그 오류가 난다.

---

## 배치·마이그레이션 — **멱등하다. 트랜잭션 경계와 `method` 미필터는 손볼 것**

* **멱등성 ✅.** `ON CONFLICT (region_code, scope, ym) DO UPDATE` — 재실행이 안전하다.
  운영 적재 결과가 정확히 2,381행(93+2,288)으로 보고와 일치함을 직접 확인했다.
* **트랜잭션 경계 → `CR33-4`.** `with engine.begin()` 이 **전체 실행(85지역·48.7초)** 을
  하나로 감싼다. 원자성은 얻지만 ① 마지막 지역이 실패하면 앞의 84곳이 전부 롤백되고
  ② 48초짜리 트랜잭션이 vacuum 스냅샷을 잡는다(192MB 컨테이너에서 굳이). scope/지역 단위
  커밋이 낫다.
* **`method` 를 조회가 안 거른다 → `CR33-4`(같은 항목).** migration 015 는
  *"방법을 바꾸면 값이 달라지므로 섞이지 않게 기록한다"* 라고 적어 놓았는데
  `postgis._MARKET_INDEX_SQL` 은 `(region_code, scope)` 로만 읽는다. v2 로 부분 재계산하는
  날 **두 방법의 비율을 계산하게 된다.** 지금은 method 1종(직접 확인)이라 무해하다.
* 메모리 방어(`work_mem 4MB` · 지역 단위 분할 · 0.4초 휴식)와 그 근거 기록은 **좋다.**
  OOM 을 한 번 낸 뒤 값을 12MB→4MB 로 **낮추며 이유를 적은 것**은 이 저장소의 좋은 습관이다.

---

## 나머지 확인 (전부 통과)

* **CR32-2** — 상한 120 의 주석이 내 실측(강남 123→151, 광진 140→167)을 그대로 반영해
  "결과 불변"에서 "**시간 예산**"으로 정정됐다. 요구한 것보다 정확하다. **CLOSE**
* **CR32-5** — `client.ts` 주석 정정 + `available:false` 를 `no` 로 접지 않는 회귀
  테스트(App.test.tsx +59줄)까지 붙었다. 요구 이상. **CLOSE**
* **CR32-6** — 죽은 `backdrop-filter` 6줄 + `@supports` 블록 2개 삭제 확인. **CLOSE**
* **가격축 coverage full→partial** — `listing` 0행인데 `COVERAGE_FULL` 이었던 것을
  스스로 찾아 고쳤다. `coverage_gap` 이 *"'이 매물이 싼가'를 판정한 값이 아니라
  '이 단지가 얼마쯤인가'라서 후보 간 순위로 쓰지 않습니다"* 까지 적는다 — **G2 모범**이다.
* **조회 비용** — 후보 200건이어도 지역당 1회(`test_후보가_많아도_지역당_한_번만_조회한다`
  가 4회로 고정). 루프 안 조회로 되돌리면 잡힌다.
* **G2 · 내부 식별자** — payload 에 실리는 `scope`·`region_code`·`basis` 는 각각 공개
  법정동코드와 기존 `dong_valuation.basis` 와 같은 계약이다. 유출 아님.

**info — 동(棟) 효과는 보정되지 않는다.** `orchestrator.py:464` 의
`dong_effect(candidate.trades, …)` 는 **원본** 거래를 쓴다. 밴드는 2026-06 환산인데 같은
문장 안의 동별 ₩/㎡ 는 시점 혼합이다. 동 간 *상대* 비교라 기존 성질이 나빠진 것은 아니고
이번 라운드가 만든 결함도 아니다. 언젠가 정리할 것.

---

### 판정

**⛔ FAIL — 커밋 전 `CR33-1` · `CR33-3` 을 고칠 것.**

차단 사유를 분명히 한다. **차단은 결과로 정당화한다.**

* `CR33-1` — 운영 DB 에서 **581개 단지(3.5%)** 가 *아직 끝나지 않은 달*을 기준월로
  쓰고 있다. 배치를 며칠 뒤 다시 돌리면 새 정보 없이 밴드가 바뀌고 예산 경계의 후보가
  뒤집힌다. 모듈이 규칙 3 으로 막겠다고 선언한 현상이 **선언한 그 자리에서** 일어나 있고,
  이번에 넣은 `_freshest_index` 가 그 지수를 **선호**해 노출을 키운다. 가설이 아니라
  내가 조회한 값이다.
* `CR33-3` — 이 라운드의 핵심 주장은 "이 숫자는 **언제** 시점 값인가"인데, 정작 사용자가
  보는 카드에서 그 숫자가 여전히 **"국토교통부 실거래가"** 로 불린다. 떨어진 후보에게는
  시점을 말하고 통과한 후보에게는 말하지 않는다. 백엔드가 `as_of_ym`·`time_adjusted` 를
  만들어 놓고 한 계층을 안 이었다 — 배선 테스트 파일이 서두에 적은 실패 형태 그대로다.

둘 다 **고치기 싸다** — 완결 판정에 달력 하한 한 줄 + 테스트 1건 + 배치 48초 재실행,
프론트 타입 2필드 + 문구 + 테스트 1건. 그래서 차단이 비례한다고 본다.

**차단하지 않은 것도 분명히 한다.** 이 라운드의 **방향은 옳고**, 가장 어려운 판단
(시점 보정을 켠다 · 기준월 최신 우선 · 학군지 태그를 포기한다 · 무키 수집을 fail-closed 로
막는다)은 전부 맞다. 분담금 가드는 내가 뚫었던 5종 중 4종이 실제로 닫혔고, 남은 하나는
값싼 강화 여지가 있을 뿐 차단할 것이 아니다. 테스트도 부족하지 않다 — 신규 4파일 +93건이
"계산이 맞는가"가 아니라 **"실제로 연결됐는가"** 를 고정하고, 각 테스트에 변이 대상까지
적어 뒀다. `CR33-1` 이 통과한 이유가 *테스트가 없어서*(진행 중인 달 케이스 부재)라는 것도
그 파일들이 스스로 증명한다.

> 이번 라운드에서 가장 값어치 있는 것은 **미등기 가설을 실측하고 기각한 것**이다.
> "미등기 = 최신 체결가"는 그럴듯하고 구현도 쉽다. 그걸 재 보고 *"registered_at IS NULL 은
> 최근 3~4개월을 더 나쁘게 쓴 것"* 이라고 적은 뒤 버렸다. 그 절제가 없었으면 지금
> 선택편향이 든 추정가로 예산을 판정하고 있었을 것이다.
> 그런데 **그 편향이 다른 문으로 들어와 있다** — 진행 중인 달을 기준월로 쓰는 4개 지역이
> 정확히 같은 선택편향을 먹는다(`CR33-1`). 옳은 이유로 닫은 문은, 옆문도 같이 닫아야 한다.

---

## CR-034 · 2026-07-28 · CR-033 차단 2건 재검증 (code-reviewer, herdr re-review 대행)

**리뷰어** code-reviewer · **대상** `077c2e5` 이후 미커밋 — 수정 34파일 + 신규 9 ·
**판정 ✅ PASS** (차단 0. `CR33-1` · `CR33-3` 둘 다 해소를 **결과로** 확인했다)

### 실행 검증 (전부 직접 돌림)

| 항목 | 주장 | 실측 | 결과 |
|---|---|---|---|
| 백엔드 | 1,290 passed / 78 skipped / 0 failed | junitxml `tests=1368 skipped=78 failures=0 errors=0` → **1,290 passed** | ✅ 정확히 일치 |
| 프론트 | 764 passed / 41 files | `Test Files 41 passed · Tests 764 passed` | ✅ |
| 빌드 | — | `vite build` exit 0 (270.82 kB) · `tsc --noEmit` **exit 0** | ✅ |
| 배치 재실행 | 2,381행 | 운영 DB `sido 93 + sigungu 2,288 = 2,381` · `method` 1종 | ✅ |
| 줄바꿈 | — | `git diff --numstat` 에 0/0 파일 **0건**(실질 hunk 없는 파일 없음) | ✅ |

---

## ⛔→✅ CR33-1 (기준월이 진행 중인 달) — **해소**. 경계까지 검증했다

### ① 운영 DB 에서 직접 확인했다 — 4곳이 사라졌다

```
scope   | ref_ym  | count      (ref = max(ym) WHERE is_complete AND sample_size>=150)
--------+---------+------
sido    | 2026-05 |   3
sigungu | 2026-05 |  64 · 2026-04 2 · 2025-10 1 · 2025-06 1 · 2025-03 1 · 2024-10 1 · 2024-08 1 · 2024-06 1
```

**`sigungu` 기준월에 `2026-07` 은 0곳이다.** 문제의 4곳도 직접 조회했다:

| region | idx 2026-05 | idx 2026-06 | idx 2026-07 | is_complete(06/07) |
|---|---|---|---|---|
| 41113 수원권선 | 1.050747 (t) | 1.050590 | 1.068485 | **f / f** |
| 41370 오산 | 0.994752 (t) | 1.006475 | 1.021605 | **f / f** |
| 41461 용인처인 | 1.034823 (t) | 1.029180 | 1.048713 | **f / f** |
| 41595 화성병점 | 1.020291 (t) | 1.039402 | 1.056266 | **f / f** |

`2026-06`·`2026-07` 은 **전 지역 0곳 완결**(각 78행·63행 모두 `false`).
그리고 **`idx_value` 가 CR-033 에서 내가 기록해 둔 값과 소수점 6자리까지 같다**
(1.050590 · 1.068485 …). "바뀐 건 완결 플래그뿐"이라는 주장이 내 이전 기록과 대조돼 확인된다.

### ② 경계가 옳은지 — **법 근거와 4년치 전수 대조로 확인했다**

근거는 **부동산 거래신고 등에 관한 법률 제3조 제1항** — *거래계약의 **체결일**부터
**30일 이내** 신고*(2020-02-21 시행. 그 전은 60일이나, 60일 규칙이 적용되던 달은 이미
6년 전이라 오늘의 판정에 영향이 없다). 따라서 계약월 `M` 의 마지막 계약(M 말일)의
신고기한은 **M말 + 30일**이고, `M` 이 다 들어왔다고 말할 수 있는 날은 그 다음 날부터다.

`open_ym(as_of) = ym_of(as_of − 30일)` · 완결 조건 `ym < open_ym` 이 이 명제와
**동치인지**를 소스를 건드리지 않고 검증했다 — `as_of` 를 2024-01-01~2027-12-31
**매일**(1,461일) × 대상월 60개 = 87,660조합에 대해
`(코드의 완결 판정) == (as_of > ym말일 + 30일)` 을 대조:

```
4년치 전수 대조 불일치 건수: 0
open_ym(2026-07-27)=2026-06 · (7/28)=2026-06 · (7/30)=2026-06 · (7/31)=2026-07
open_ym(2026-01-30)=2025-12 · (2026-01-31)=2026-01 · (2026-03-30)=2026-02 · (3/31)=2026-03
```

**경계가 정확하다.** 특히 7/30 은 아직 6월을 열지 않고 7/31 에 연다 — 6/30 계약의
신고기한이 7/30 이므로 그날까지는 신고가 들어올 수 있다. 하루도 이르지 않고 늦지도 않다.

> **판정: 30일은 맞는 근거이고, 계약일 기준이 맞다.** 다만 이것은 *신고기한*이지
> *공개 시점*이 아니다 → `CR34-4`.

### ③ 2026-06 이 함께 닫힌 것 — **맞는 동작이다**

오늘(7/28)은 6/30 계약의 신고기한(7/30)이 아직 안 지났다. 그러므로 2026-06 을
완결이라 부르는 것이 **거짓**이고, 지금 전 지역 기준월이 2026-05 인 것이 옳다.
"7/31 이후 재실행하면 2026-06 으로 올라간다"도 옳다 — 그건 **새 정보(신고 마감)가
생겨서** 올라가는 것이지, CR33-1 이 문제 삼은 *"새 정보 없이 며칠 뒤 값이 바뀌는 것"* 과
성격이 정반대다. 테스트가 이 구분을 그대로 못박는다
(`test_이번_달은_기준월이_되지_않아_며칠_뒤에도_같은_값을_낸다`: 7/28·29·30 → 2026-05 고정,
7/31 → 2026-06).

### ④ 15개 구의 시도→시군구 전환 — **의도된 것이고, 정확도가 올라간 쪽이다**

`select_index` 규칙("기준월 최신 우선, 같으면 시군구")대로다. 시도가 2026-05 로
내려오면서 시군구 64곳과 동률이 됐고 tie-break 가 시군구를 택했다.
극단값 두 곳을 적재값으로 직접 확인했다:

```
ym       41131(성남중원)   41(경기)     11650(서초)   11(서울)
2025-05  0.977460          0.985849     1.031135      0.984056
2026-05  1.117498          1.034474     1.107597      1.112226
         → +14.3%          +4.9%        → +7.4%       +13.0%
```

* **41131 +11.9%** — 중원구가 경기 평균보다 실제로 훨씬 많이 올랐다(+14.3% vs +4.9%).
  경기 지수로 환산하던 동안 이 지역 밴드는 **체계적으로 낮게** 나오고 있었다.
* **11650 −7.7%** — 서초는 이미 2025 상반기에 올라 있었는데 서울 전체 지수는 그 뒤에
  다른 구가 따라오르며 더 크게 움직였다. 서울 지수로 환산하면 서초의 과거 거래가
  **과다 보정**된다. 시군구로 바꾸면서 그 과다분이 빠진 것이다.

즉 두 극단값은 **오차가 커진 신호가 아니라 지역 편차를 잡아낸 신호**다. 그리고
동률 tie-break 이므로 **환산 시점은 전 후보가 2026-05 로 동일** — CR-033 이 지켰던
"한 목록 한 잣대"가 깨지지 않는다. 확인했다.

> 이 전환의 부작용은 따로 기록한다 → `CR34-1`(달마다 scope 가 뒤집히며 밴드가 진동).

**CR33-1 CLOSE.**

---

## ⛔→✅ CR33-3 (카드가 보정값을 "국토교통부 실거래가"라 부름) — **해소**

### 렌더 결과를 확인했다

```
보정됨    : 적정가 밴드 13.8억~14.5억 · 중위 14.0억
            (2026-06 시점 환산 · 국토교통부 실거래가 · 최근 6개월 37건)
            헤드라인 금액 라벨 = "2026-06 시점 환산 추정가"
보정 안 됨 : … (시점 보정 없음 · 국토교통부 실거래가 · …)
            + "기간 내 거래를 시점 구분 없이 섞은 값이라 특정 시점의 가격이 아닙니다.
               거래 시점의 지수 확보율이 낮아 …"
필드 없음  : 시점에 대해 **아무 말도 하지 않는다**(예전 화면 그대로)
```

순서 고정이 `indexOf` 로 못박혀 있고(`ReportCard.test.tsx`), 뒤집히면 실패한다.
`priceView` 의 라벨 교체가 **`krw === band.median_krw` 일 때만** 붙는 것도 옳다 —
라벨은 *화면에 뜬 그 숫자*에 대한 주장이므로, 서버가 다른 값을 기준가로 쓰기 시작하면
근거를 잃는다. 호가 후보에서 라벨이 "호가"로 남는 것도 테스트가 고정한다.

### 아직 "국토교통부 실거래가"라고만 부르는 경로가 남았는지 — **훑었다**

| 경로 | 값 | 판정 |
|---|---|---|
| `ReportCard` 밴드 줄 | 보정된 중위 | ✅ 시점 꼬리표가 출처 **앞** |
| `recommendation.priceView` 헤드라인 | 보정된 중위 | ✅ `2026-06 시점 환산 추정가` |
| `PriceBand.to_evidence` claim | 보정된 중위 | ✅ `2026-06 시점 환산 중위 …원` |
| `adjustment_evidence` | 보정 자체 | ✅ source `자체 시장지수(국토교통부 실거래가 기반)` |
| `valuation_finding.rationale` | 보정된 중위 | ✅ `median_label` 에 기준월 삽입 |
| 예산 초과 제외 사유 | 보정된 중위 | ✅ (직전 라운드부터) |
| 결과 상단 notes | 목록 전체 | ✅ `NOTE_TIME_ADJUSTED` |
| `AffordabilityPanel`·지도 | `recent_price_krw` = **원본 최근 체결가**(미보정) | ✅ 라벨 정확. 단 → `CR34-3` |
| `TRADE_BASIS_NOTE`(`price_note`) | 가격 *근거*(호가 없음) 안내 | ⚠️ 시점 언급 없음 → `CR34-5`(경미) |

**보정된 값을 원본처럼 부르는 경로는 남아 있지 않다.** `CR33-3 CLOSE.`

> 통과 조건에 적었던 예시 문구(`… + 자체 시장지수 …`)와 달리 `source` 문자열 자체는
> `"국토교통부 실거래가"` 로 남았다. 그러나 ① 꼬리표가 **출처보다 앞에** 오고
> ② 같은 카드의 근거 목록이 `자체 시장지수(국토교통부 실거래가 기반)` 를 별도 항목으로
> 싣는다. 통과 조건의 **취지**(우리 계산이 섞였다는 사실이 숫자 옆에서 드러날 것)는
> 충족됐다고 본다. 문자열 개선은 `CR34-5` 로 남긴다.

---

## 비차단 조치 확인

### CR33-2 (`_freshest_index` 위치) — **CLOSE. 변이 판별력까지 직접 쟀다**

* `_freshest_index` 는 저장소에서 사라졌고 규칙이 `select_index` 안에 있다
  (`timeadjust.py:301-341`). docstring 이 폐기된 정책("시군구 우선")을 선언하던 결함 해소.
* **`select_index` 직접 호출 경로는 `candidate_index` 하나뿐이다** — 앱 코드 grep 결과
  `orchestrator.py:206` 단 1건(나머지는 테스트·주석). 확인했다.
* `candidate_index` 는 키 조회 + 사유 남기기 폴백만 한다 — 그건 진짜 배선이 맞다.

**"기존 배선 테스트가 두 정책을 구분 못 했다"는 발견과 그 수정이 실제로 구분하는가** —
소스를 건드리지 않고 옛 정책(시군구 우선)을 재구현해 **같은 테스트 입력**에 태웠다:

```
[test_기준월이_뒤처진_시군구_지수는_시도로_바꾼다 의 입력]
  cov(stale)=1.0  cov(fresh)=1.0        ← 커버리지가 아니라 기준월이 가른다
  현재 정책 select_index      → 11     (시도)
  옛  정책 select_index_old  → 11140  (시군구)      두 정책이 다른 답을 낸다: True
[도메인 test_시군구_기준월이_낡았으면_시도_지수를_쓴다 의 입력]  현재 11 / 옛 11140
```

**판별한다.** 예전 테스트가 못 잡던 이유(stale 이 거래를 못 덮어 커버리지에서 먼저
걸러졌다)를 테스트 주석이 정확히 적어 두었다. 자기 테스트의 무력함을 찾아 고친 것은
이 라운드에서 가장 값진 자기점검이다.

### CR33-1 테스트의 변이 판별력도 같은 방식으로 확인

```
[rows: 2026-01~06 각 1000건 + 2026-07 980건(직전 중위의 98%)]
  현재 _complete_flags : … 2026-05 True · 2026-06 False · 2026-07 False → reference_ym 2026-05
  옛 (달력 하한 제거)  : … 2026-06 True  · 2026-07 True                  → reference_ym 2026-07
```

달력 하한 한 줄을 지우면 **정확히 운영에서 났던 상태**로 되돌아가고 테스트가 잡는다.

### CR33-4 · CR33-5 — **CLOSE**

* 트랜잭션이 **지역 단위**다(`build_market_index.py:219-254` — `conn.commit()` 이 지역 루프 안).
  `as_of` 는 `run()` 에서 **한 번만** 읽어 내려보낸다 — 자정을 걸친 실행에서 지역별로
  판정이 갈리지 않는다. `points` 가 비면 `conn.rollback()` 으로 읽기 스냅샷도 놓는다.
* `postgis._MARKET_INDEX_SQL` 에 `AND method = :method` 추가 확인. 운영 `method` 1종 확인.
  PK 가 `(region_code, scope, ym)` 이라 방법이 바뀌면 같은 행을 덮어쓰고, 부분 재계산 시
  옛 방법 지역은 조회 0행 → **보정 안 함 + 사유**로 떨어진다. fail-safe 방향이 맞다.
* 문서 수치 정정(`timeadjust.py:14-25`)을 적재값으로 표본 대조했다
  (서울 2025-01 0.954294 → 2026-05 1.112226). **문서가 데이터와 일치한다.**
* `zone_academic` 이 `dict[str, set[str]]` 로 바뀌어 `ACA_ASNUM` 고유 집합을 센다
  (`fetch_academy.py:279·302`). 행 카운터 제거 확인.

---

## 담당자가 "못 고쳤다"고 보고한 것 — **논증이 성립한다. 받아들인다**

주장: 서울 sido `2025-07/08/11/12` 가 여전히 `is_complete=false` 지만 **영향 0**.

세 갈래로 직접 확인했다.

1. **`ratio_to_reference` 는 완결 여부를 보지 않는다** — `timeadjust.py:165-171` 이
   `self.points.get(ym)` 만 쓴다. 코드로 확인. 즉 그 달의 거래는 정상 보정된다.
2. **기준월은 '가장 최근'을 고른다** — 뒤에 완결 월이 하나라도 있으면 그 달은 후보가
   될 수 없다. 서울 sido 기준월은 실측 **2026-05** 다.
3. **가장 중요한 것 — "최신 월이 건수 검사로 강등된 지역이 있는가"를 쿼리로 쟀다.**

```sql
SELECT scope, count(*) FROM market_price_index
 WHERE ym='2026-05' AND sample_size>=150 AND NOT is_complete GROUP BY scope;
→ 0 rows
```

**한 곳도 없다.** 기준월이 뒤처진 6개 시군구(11140 중구·11170 용산·28155 인천동구·
41591 광주 …)도 원인을 따로 확인했더니 건수 검사가 아니라 **`sample_size` 가 150 미만**
(84~141)이어서였다 — `MIN_REFERENCE_MONTH_SAMPLE` 이 의도대로 작동한 것이지 오탐이 아니다.

> 따라서 "영향 0"은 **오늘 데이터에 대해 사실**이다. 구조적 보증은 아니지만
> (계절 저점이 최신 월에 오면 강등될 수 있다) 그때의 결과도 *더 거친 시도 지수로 폴백*
> 이지 틀린 기준월이 아니다 — **보수적인 방향의 오류**다. `_complete_flags` docstring 이
> 이 한계를 그대로 적고 있다. **차단하지 않는다.**

---

## 보안 조치(SR-029 지적분) — 함께 확인

### SR29-1 `enforce_runtime_settings` — **치명/경고 구분 기준이 타당하다**

기준이 한 줄로 적혀 있다: *"값이 잘못돼도 앱이 정상처럼 계속 도는가."*
이 기준을 항목마다 대입해 봤고, 전부 옳게 갈렸다.

| 항목 | 판정 | 근거 |
|---|---|---|
| `JWT_SECRET<32` | **치명** ✅ | 빈 문자열로도 HS256 서명·검증이 성공한다. 조용히 "누구나 아는 키" = 임의 user_id 위조 = 승인제 우회 |
| `FIELD_ENCRYPTION_KEY≠32` | **치명** ✅ | 사용 지점(`load_key`)이 막지만 그건 *사용자가 자산을 저장하는 순간* 500 이다. 기동 시점에 아는 편이 옳다 |
| `ARGON2_*` 하한 미만 | **치명** ✅ | 파라미터가 낮아도 **해시는 성공한다** — 조용한 약화의 전형 |
| `POSTGRES_PASSWORD` 빈 값 | 경고 ✅ | 첫 DB 접속에서 큰 소리로 죽는다. 게다가 repo 주입으로 DB 없이 뜨는 구성이 실재한다 |
| `COOKIE_SECURE=false` | 경고 ✅ | `refresh_cookie_secure` 가 운영에서 구조적으로 True 로 되돌린다 — 효력 없는 설정으로 서비스를 죽이는 건 비례하지 않는다 |

**기준이 일관되고, 기동 차단을 '조용한 약화' 한 종류에만 쓴다. 타당하다.**
`security.py` 에 2차 방어(`create_token` 이 짧은 키를 거부)를 둔 것도 옳다 —
`create_app()` 을 안 타는 배치·스크립트 경로가 생겨도 약한 키로 토큰이 나가지 않는다.

### **운영에서 기동 실패하지 않는가 — 운영 컨테이너에서 직접 쟀다**

```
$ docker exec realestate-api python -c "…"
debug= False   cookie_secure= True
jwt_len= 64    fek_len= 32    pgpw_set= True
argon2 = {memory_kib 19456, time_cost 2, parallelism 1, concurrency 2, wait_timeout 2.0}
argon2_parameter_problems() = []
validate_runtime()          = []      ← 문제 0건
```

**`problems` 가 비어 있으므로 `enforce_runtime_settings` 는 즉시 `[]` 를 반환하고
예외를 던지지 않는다. 배포해도 API 는 뜬다.** (담당자 실측치 jwt 64 · fek 32 ·
argon2 19456/2/1/2 도 그대로 일치.)
`install_log_masking()` 을 **점검보다 먼저** 호출하는 순서도 옳다 — 점검 로그가
마스킹 계층을 타야 한다.

### SR29-2/9 · SR29-3 — 확인

* `SECRET_ENV_VARS` 에 `NEIS_API_KEY` 등록 ✅. `.env.example` 대조 테스트가
  이름 규칙(`_KEY|_SECRET|_PASSWORD|_PASSWD|_TOKEN$`)으로 비밀 칸을 뽑아 목록과 맞춘다.
  한쪽 방향만 검사하는 것(목록이 과한 것은 허용)도 근거가 적혀 있고 타당하다.
  두 번째 테스트가 **경로형 URL·dict repr·JSON·원문 4문맥**에서 실제로 지워지는지까지 본다.
* `fetch_academy.result_fault` 가 데이터 블록 없는 응답(키 오류)에서 `FetchError` 를 던지고
  **`path.write_text` 에 도달하지 않는다**(`fetch()` 안에서 raise → `main()` 이 `SystemExit`).
  0행 파일이 남지 않는다 ✅.

---

## 새로 기록하는 것 (전부 비차단)

* **`CR34-1` (medium) — scope 전환에 따른 밴드 진동.**
  기준월 **동률일 때만** 시군구를 쓰므로, 시도가 한 달 먼저 열리는 시점(매월 말)에는
  같은 지역이 **시군구 → 시도 → 시군구** 로 오간다. 관측된 전환폭이 −7.7% ~ +11.9%
  이므로 예산 경계의 후보가 **시장 변화 없이** 월 단위로 뒤집힐 수 있다.
  CR-033 이 승인한 규칙("시점 일치 우선")의 직접적 귀결이라 차단하지 않는다.
  값싼 완화는 히스테리시스(시군구 기준월이 최신보다 K개월 이내면 유지)인데, 그건
  "한 목록 한 잣대"를 K개월만큼 허무는 거래다 — **의도적으로 권고하지 않는다.**
  대신 이 성질을 `select_index` docstring 과 DEPLOY §5-3c 에 한 줄 남길 것.
* **`CR34-2` (low) — 미완결 월이 *환산 원천*으로는 계속 쓰인다.**
  `ratio_to_reference` 가 완결 여부를 안 보므로(그래서 위 "영향 0" 논증이 성립한다),
  2026-06·07 거래는 **선택편향이 든 그 달 지수**(월중 신고분은 +1.5~1.9% 높다)로 환산된다.
  방향은 과소보정이고 가중치가 작아(12개월 창에서 2/12) 중위 영향은 0.5% 미만으로 본다.
  **고치라는 뜻이 아니다** — 미완결 월을 원천에서 빼면 6개월 창의 커버리지가
  67% < 80% 가 되어 짧은 창의 보정이 통째로 꺼진다. 지금 선택이 맞다. 다만
  `IndexPoint.is_complete` 주석("False 면 기준월로 쓰지 않는다")에
  *"원천으로는 쓴다 — 그 값에는 월중 편향이 있다"* 를 덧붙일 것.
* **`CR34-3` (low) — 화면마다 다른 가격이 뜬다.**
  추천 카드는 **2026-05 환산 밴드 중위**, 지도·자금계획(`AffordabilityPanel`)은
  **원본 최근 체결가**(`recent_price_krw`, `postgis.py:568`)다. 각자의 라벨은 정확하지만
  같은 단지를 두 화면에서 본 사용자에게는 값이 달라 보인다. 이번 라운드가 만든 격차다.
* **`CR34-4` (low) — `REPORT_LAG_DAYS=30` 은 *신고기한*만 덮는다.**
  기한 안에 낸 신고가 **공개 API 에 반영되는 지연**, 그리고 지연신고·해제신고는 덮지 않는다.
  즉 이 경계는 "가장 이른 방어 가능한 날"이지 보수적인 값이 아니다. 잔여 흔들림은
  지각 신고율만큼이라 작고 건수 검사가 큰 누락은 잡는다. 며칠 여유(예: 33~35일)는
  값싼 강화지만 **근거 없는 숫자를 넣지 말 것** — 넣으려면 지각 신고율을 재고 그 값을 적을 것.
* **`CR34-5` (info) — 문구 잔여.** ① 밴드 줄의 `source` 문자열이 여전히
  `"국토교통부 실거래가"` 다(꼬리표·근거 목록이 보완하므로 통과). ② `TRADE_BASIS_NOTE`
  는 시점을 말하지 않는다 — 그 문장의 주제가 *가격 근거(호가 없음)* 라 틀린 말은 아니다.

**이월(CR-033 비차단 잔여):** `CR33-6`(부분 수집 exit 0 — `main()` 이 `failures` 를 보지
않음, 이번에도 그대로) · `CR33-7`(`school_quality.py:9` "가장 강한 방어선" 문구 그대로) ·
`CR33-8`(`assert_no_cost_estimate` 에 "완전하지 않다" 한 줄 없음 · A8 강화 미적용).
셋 다 이번에도 차단 사유가 아니다.

---

### 판정

**✅ PASS — 커밋·배포로 진행 가능.**

통과시키는 근거를 결과로 적는다.

* `CR33-1` — 운영 DB 에서 **진행 중인 달을 기준월로 쓰는 지역이 0곳**임을 조회로 확인했고,
  `idx_value` 가 내 이전 기록과 소수 6자리까지 같아 "플래그만 바뀌었다"가 대조 확인된다.
  경계는 법 근거(신고기한 30일·계약일 기준)와 **87,660조합 전수 대조 불일치 0건**으로
  검증했다. 부수효과(2026-06 동반 폐쇄 · 15개 구 tie-break 전환)는 **둘 다 옳은 동작**이며,
  후자는 적재값으로 볼 때 정확도가 **올라간** 방향이다.
* `CR33-3` — 보정값이 원본처럼 불리는 경로가 카드·헤드라인·근거·rationale·notes
  전 경로에서 사라졌음을 훑어 확인했다. 세 갈래(보정됨/안 됨/모름)와 **순서**가
  테스트로 고정된다.
* 테스트·빌드·타입체크·적재행수가 **주장과 정확히 일치**한다(1,290 / 764 / exit 0 / 2,381).
* 보안 조치는 기준이 일관되고(조용한 약화만 차단), **운영 환경에서 기동이 막히지 않음을
  컨테이너에서 직접 측정**했다.

**차단하지 않은 것도 분명히 한다.** `CR34-1`(밴드 진동)은 값 영향이 두 자릿수 % 지만,
그것은 CR-033 이 스스로 옳다고 판정한 규칙의 귀결이고 대안이 다른 불변식을 허문다.
**앞선 라운드의 경고를 근거로 차단하지 않는다 — 차단은 결과로 정당화한다.** 오늘의
결과에는 차단할 것이 없다.

> 이번 라운드에서 가장 값진 것은 **자기 테스트의 무력함을 스스로 찾아낸 것**이다.
> "배선 테스트가 두 정책을 구분하지 못한다"는 지적은 밖에서 받은 적이 없고, 초록 불이
> 켜져 있는 동안에는 아무도 볼 이유가 없다. 그걸 찾아 stale 지수가 거래를 **전부 덮도록**
> 입력을 바꾼 뒤에야 그 테스트는 비로소 정책을 지킨다. `CR33-1` 이 운영까지 나간 이유가
> 정확히 "그 케이스의 테스트가 없어서"였다는 것을 생각하면, 이번 수정은 결함 하나가
> 아니라 **결함을 놓치는 방식** 하나를 닫았다.

---

## CR-035 · 2026-07-29 · PRICE-2(호가 수동 입력) · 배선 · CR34-3 가격 일관성

**리뷰어** code-reviewer · **대상** `8bf21dd` 이후 미커밋 — 수정 21파일 + 신규 5(마이그레이션 016 · 테스트 4) ·
**판정 ⛔ FAIL** (차단 2건. 최우선 지시 2건은 **둘 다 해소를 결과로 확인**했으나, 그 조치가 만든 **새 결함 2건**이 이 저장소의 하한선(조용한 유실 금지 · 없는 것을 있다고 말하지 않기)을 넘는다)

### 실행 검증 (전부 직접 돌림)

| 항목 | 주장 | 실측 | 결과 |
|---|---|---|---|
| 백엔드 | 1,368 passed / 102 skipped / 0 failed | junitxml `tests=1470 skipped=102 failures=0 errors=0` → **1,368 passed** | ✅ 정확히 일치 |
| 프론트 | 764 passed (무변경) | `Test Files 41 passed · Tests 764 passed` | ✅ |
| 빌드 | — | `vite build` exit 0 (270.82 kB) · `tsc --noEmit` **exit 0** | ✅ |
| 016 운영 미적용 | "미적용" | 운영 DB: `listing` 신규컬럼 **0/5** · `listing_user_%` 제약 **0건** · `listing` **0행** | ✅ |
| 총점 64.5 → 46.8 | 주장 | `run_mvp_pipeline` 직접 실행: **64.5 → 46.8**, 리스크 축 `applied 100.0` → `no_signal` | ✅ 소수까지 일치 |
| 낡음 기준 근거 | 서울 +0.99%/월 · 3개월 최대 +3.3% | 운영 `market_price_index`(sido) 11: 2025-10 `1.038446` → 2026-05 `1.112226` = **+7.105% / 7개월 = +0.985%/월**, 2026-02 `1.076446` → 2026-05 = **+3.32%** · 41 +0.434%/월 · 28 +0.069%/월 | ✅ 전부 일치 |
| 지도 면적 불일치 | 서울 400곳 중 176곳(44%) · 평균 26.8% | **독립 재측정**(서울 전역, 55~65㎡ 거래가 있는 단지 **2,507곳**): 조건 밖 표시 **1,274곳 = 50.8%** · 평균 \|차\| **22.2%** · 최대 **406.3%** | ✅ 결함 재현(범위를 넓히면 오히려 더 심하다) |
| 대우디오빌 사례 | 3.05억(30㎡) → 9.20억(59.5㎡) | 운영 DB: 전체최근 `305,000,000 / 30.0300 / 2026-06-23`, 55–65 최근 `920,000,000 / 59.5050 / 2026-06-22` = **+201.6%** | ✅ 정확히 일치 |
| DB CHECK | "6종 · BEGIN…ROLLBACK 실측" | **재현함**(운영 DB, 016 적용 → `SAVEPOINT`별 12케이스 → `ROLLBACK`): 제약 **7종**, 위반 8건 전부 정확한 제약명으로 거절, 정상 사용자행·정상 수집행 통과, 수집행 `floor=9999` 통과(수집 계약 불변). 롤백 후 잔여 0 | ⚠️ **6종이 아니라 7종** (CR35-5) |
| 자금계획 성능 18~26ms | 주장 | 운영 EXPLAIN ANALYZE: 최대 거래단지(9751 · 983행) `trades_for_complex` warm **0.82~0.87ms**(planning 2~13ms · 파티션 테이블) · `complex_region_code` **0.07~0.63ms** | ✅ 주장은 보수적 상한 |

**추가로 한 것 — `needs_db` 102건이 안 돌아간 자리를 일부 메웠다.** 변경된 SQL 10종
(`_BBOX_SQL` · `_CANDIDATES_SQL` · `_CANDIDATES_BBOX_SQL` · `_SCOPE_STATS_SQL` ·
`_SCOPE_STATS_BBOX_SQL` · `_LISTINGS_SQL` + 사용자 CRUD 4종)을 운영 DB 에서
**016 적용 후 `PREPARE`** 로 전부 통과시켰다(트랜잭션 롤백). 문법·컬럼 참조 오류 **0건**.
의미까지 증명하진 못하지만, 미검증 구간의 가장 큰 실패군(컬럼·문법)은 닫혔다.

---

## ⛔ CR35-1 (차단) — 면적 조건 **경계**에서 후보가 **흔적 없이** 사라진다

`backend/app/agents/recommend.py:925-926`

```python
areas = [a for a in _trade_area_groups(trades)
         if not any(abs(a - la) <= AREA_TOLERANCE_M2 for la in listing_areas)]
```

`listing_areas` 에는 **조건에 걸려 탈락한 호가의 면적까지** 들어간다(`:911` 주석이
의도라고 적어 두었다). 그래서 조건 **밖** 호가가 조건 **안** 실거래를 ±0.5㎡ 로 지운다.

### 재현 (인메모리 리포지토리 · `_assemble_candidates` 직접 호출)

| 입력 | 후보 | `dropped` | `excluded` |
|---|---|---|---|
| 조건 80~85㎡ · 호가 **85.3㎡**(조건 밖) · 실거래 **84.97㎡**(조건 **안**) | **0건** | `{'area': 1}` (호가분만) | **0건** |
| 같은 조건 · **호가 없음** (대조군) | **1건** (84.97 trade) | `{}` | 0건 |

호가 한 건을 넣었더니 **조건을 만족하는 실거래 후보가 사라졌고**, 사라진 사실이
`dropped` 에도 `excluded` 에도 남지 않는다. 사용자에게는 "호가를 입력했더니 그 단지가
결과에서 없어졌다"로 보이고 화면 어디에도 이유가 없다.
**이 변경이 없애려던 실패 모드(`if listings: … continue`)가 경계에서 그대로 되살아났다.**

### 이 규칙이 실제로 필요한지 — **필요 없다**

주석이 근거로 든 시나리오("84㎡ 호가가 조건 미달로 탈락 → 같은 84㎡ 가 실거래 후보로
되살아난다")는 뒤의 `kept = [a for a in areas if conditions.area_ok(a)]` 가 **이미 막는다.**
호가 면적 `la` 가 조건을 어겼고 실거래 면적 `a ≈ la` 라면 `a` 도 같은 조건을 어기므로
`kept` 에서 걸러진다. 두 값이 조건 경계를 사이에 두고 갈릴 때만 결과가 달라지고,
**그 경우가 바로 위 표의 유실**이다. 즉 이 규칙은 얻는 것이 없고 잃는 것만 있다.

재현으로 확인:

| 입력 | 후보 | `dropped` |
|---|---|---|
| 조건 55~65 · 호가 84.97 · 실거래 84.97 + 59.9 | 59.9(trade) 1건 | `{'area': 1}` |

결과는 이미 옳다(84.97 은 안 나온다). 다만 **면적 조건에 걸려 실제로 빠진 것이 둘(호가·실거래)인데 1로 센다** — 같은 뿌리의 부수 결함이다.

### 무엇을 고치면 PASS 인가
`listing_areas.append(area)` 를 **`conditions.area_ok(area)` 통과 뒤로** 옮긴다.
그러면 표 ①은 84.97 trade 후보가 살아나고, 표 ②는 결과가 그대로이면서 `dropped['area']` 가 2가 된다.
회귀 테스트로 **경계 케이스**(조건 밖 호가 + 조건 안 실거래가 ±`AREA_TOLERANCE_M2` 안)를 고정할 것 —
현재 `test_user_listing_wiring.py` 의 두 테스트(`_다른_면적대_후보가_살아있다` · `_또_세우지_않는다`)는
경계를 비껴간 입력만 쓴다.

---

## ⛔ CR35-2 (차단) — 사용자에게 **존재하지 않는 화면**으로 가라고 말한다

`backend/app/agents/scoring.py:181-187`(`NO_ASK_REASON`) · `:86-93`(`AXIS_PRICE.coverage_gap`)

이번 라운드에서 두 문자열이 이렇게 바뀌었다:

> …이 단지의 호가를 알고 계시면 **'내 매물'에서 직접 입력하시면 가격 축이 반영됩니다.**
> …호가는 **직접 입력하신 것만** 있습니다**(내 매물 → 호가 입력)**.

### 재현 — 이 문장은 실제로 사용자 화면까지 나간다

```
run_mvp_pipeline(...)["notes"]
  → "가격 가중치 21.2%가 후보 전부에서 반영되지 않았습니다 — … '내 매물'에서 직접
     입력하시면 가격 축이 반영됩니다.. 그만큼 나머지 축으로 재정규화했습니다."
items[0].score_axes[price].missing
  → ["… '내 매물'에서 직접 입력하시면 가격 축이 반영됩니다."]
```

`notes` 는 `frontend/src/components/RecommendPanel.tsx:306-310` 이, `missing` 은
`frontend/src/components/ReportCard.tsx:193` 이 **그대로 렌더**한다.

### 그 화면은 없다

```
$ grep -rn "내 매물\|me/listings\|myListings\|userListing" frontend/src
(0건)
```

프론트는 이번 라운드에 **무변경**(764 그대로)이고 `client.ts` 에 `/me/listings` 호출부가 없다.
즉 **웹앱 사용자에게는 이 기능으로 가는 길이 존재하지 않는다.** 서버가 안내하는 대로
하려고 해도 할 수가 없다.

이건 "프론트가 아직 없다"는 범위 문제가 아니라 **이번 델타가 새로 넣은 문장이 거짓**이라는
문제다. 이 저장소는 CR33-3 에서 "보정값을 원본처럼 부르는 경로"를 같은 이유로 막았다 —
화면에 나가는 문장은 사실이어야 한다.

### 무엇을 고치면 PASS 인가
둘 중 하나.
* (a) 프론트에 `/me/listings` 화면을 붙여 문장을 사실로 만든다, **또는**
* (b) 문장에서 화면 이름을 빼고 지금 사실인 것만 말한다
  (예: "호가는 직접 입력하신 것만 반영됩니다 — 입력 화면은 준비 중입니다").

덤으로 마침표가 두 번 찍히는 것(`반영됩니다.. 그만큼`)도 같이 고칠 것 —
`NO_ASK_REASON` 이 문장부호로 끝나는데 `summary_notes` 가 뒤에 `. ` 를 덧붙인다.

---

## ✅ 최우선 1 — 배포 순서. **위험 서술은 정확하다**(수치 두 개만 틀렸다)

`deploy/DEPLOY.md §5-3b · §5-4` 는 016 이 코드보다 먼저라는 것, 컨테이너는 정상 기동하고
헬스체크도 통과한다는 것, 복구는 016 적용뿐이라는 것을 **모두** 적었다. 배포 후
`/map/complexes` 를 실제로 한 번 부르라는 확인까지 넣었다. 이 부분은 그대로 두면 된다.

**결과로 확인했다** — 운영 DB(016 미적용)에서 새 SQL 을 `PREPARE` 했을 때:

```
_BBOX_SQL             ERROR: column li.created_by_user_id does not exist
_CANDIDATES_SQL       ERROR: column li2.created_by_user_id does not exist
_CANDIDATES_BBOX_SQL  ERROR: column li2.created_by_user_id does not exist
_SCOPE_STATS_SQL      ERROR: column li2.created_by_user_id does not exist
_SCOPE_STATS_BBOX_SQL ERROR: column li2.created_by_user_id does not exist
_LISTINGS_SQL         ERROR: column li.as_of does not exist     ← 문서에 없는 네 번째
```

### CR35-5 (경) — DEPLOY.md 확인 목록의 제약 수가 틀렸다
> 기대: `listing_user_area_range · listing_user_as_of · listing_user_dong_len · listing_user_note_len · listing_user_price_range · listing_user_source_pair` **(6건)**

실제는 **7건**이다 — `listing_user_floor_range` 가 빠졌다(운영 실측 `n_constraints = 7`).
운영자가 이 목록대로 대조하면 "7건이 나왔는데 6건이라니 뭐가 잘못됐나"로 멈추거나,
더 나쁘게는 세어 보지 않고 넘어간다. 확인 절차가 확인이 아니게 된다.

### CR35-6 (경) — "읽기 경로 **세 곳**"은 **네 곳**이다
`listings_for_complex`(`_LISTINGS_SQL`)도 `li.as_of` · `li.created_by_user_id` 를 하드 참조한다.
증상은 문서가 이미 적은 "추천 전건 error" 안에 들어가지만, **다른 하드 참조가 없는지 훑으라**는
지시에 대한 답으로 기록한다. 나머지는 없다 — `listing` 을 만지는 SQL 은 postgis 안 9곳뿐이고
(`652 · 932 · 980 · 1213 · 1289 · 1316 · 1337 · 1376 · 1396`) 전부 확인했다.
`scripts/verify_recommendation.py:186` 은 신규 컬럼을 쓰지 않는다.

---

## ✅ 최우선 2 — 사용자 입력이 점수를 부풀리던 것. **옳게 고쳤다**

### 재현 (`run_mvp_pipeline` · 출처만 다르고 나머지가 완전히 같은 두 후보 · 호가 +9.3%)

```
수집으로 취급   총점 64.5   price applied 53.55 · value applied 40.0 · risk applied 100.0
user_entered    총점 46.8   price applied 53.55 · value applied 40.0 · risk no_signal + 사유
```

### ① 갈림이 `source == "user_entered"` 인 것 — **옳다**

세 근거가 서로를 받친다.
* 분기가 필요한 곳은 **도메인**(`dedup.trust_score`)이고, 도메인이 리포지토리 상수를
  가져오면 의존 방향이 뒤집힌다. 정본을 `domain/valuation/models.LISTING_SOURCE_USER` 에
  두고 `repositories/base` 가 재수출하는 형태는 레이어를 지킨다.
* `ListingRow` 는 근거 문자열·LLM 프롬프트 경로로 흘러간다. 거기에 `created_by_user_id`
  를 얹지 않는 판단은 기존 규약(security.md §2.2)과 일치한다.
* 두 값이 **같은 사실**임을 DB 가 강제한다 — `listing_user_source_pair` 를 운영에서 직접
  깨 봤다: `user_entered` + 소유자 없음 **거절**, 소유자 있음 + `source='portal'` **거절**.
  즉 "덜 위험한 쪽을 든다"가 성립한다.

### ② 수집 데이터에서 여전히 작동하는가 — **작동한다**

```
수집 8건(시세 -25% · 등록 200일 · 8개 중개사)
  → (0.3, ['시세 대비 -25.0% — 확인 필요', '등록 200일 경과', '8개 중개사 중복 등록', '최근 확인됨'])
listing_finding(source=None) → score 100.0 · missing []
```
`source=None`(구형 호출부)도 수집으로 취급된다. 방어가 고장으로 번지지 않았다.

### ③ 혼합 그룹 — 사용자 1건이 중개사 수를 부풀리지 않는다

```
수집 3 + 사용자 1 → duplicate_count 4 · len(collected) 3 → '중개사 중복 등록' 신호 없음(문턱 4)
```
`rep = collected[0]` 은 `group_duplicates` 의 정렬(`listed_at`, `id`)을 물려받아 결정론적이고,
그룹 대표와 가격이 ±1% 안이라 시세갭 판정이 실질적으로 달라지지 않는다.

### ④ 다른 축에 같은 오염이 있는지 — **훑었다. 남은 것은 하나뿐이고 지금은 무해하다**

| 축 / 값 | 사용자 입력이 근거로 들어가나 | 판정 |
|---|---|---|
| price (`ask_gap_pct`) | 호가는 **채점 대상**이고 밴드는 실거래 | ✅ 자기참조 아님 |
| price 점수식 `100-\|gap\|*5` | 대칭 감점 | ✅ 싸게 적어도 점수가 안 오른다(실측 −57% → price 0.0 · 총점 20.0 < 수집 36.7) |
| value(환금성) | `turnover` = 실거래/세대수 | ✅ |
| `liquidity.active_listing_ratio_pct` | **사용자 행이 섞인다** | ⚠️ CR35-9 — 지금 미표시·미채점이고 주석이 경고. 무해하나 지뢰다 |
| `liquidity.median_days_on_market` | `listed_at=None` 이라 구조적으로 제외 | ✅ |
| 지도 `active_listings` · 후보 정렬 · scope 통계 | SQL 에서 `created_by_user_id IS NULL` 로 배제 | ✅ 교차 사용자 누출 차단(⑤) |
| risk(매물 신뢰도) | — | ✅ 이번에 고침 |

### ⑤ 지도 `active_listings` 에서 사용자 행을 뺀 것 — **옳고, 필요한 곳에 다 뺐다**

`complexes_in_bbox` · `recommendation_candidates` · `candidate_scope_stats` 셋 다 소유자 인자가
없는 조회다. 세면 A 의 입력이 B 의 화면·후보 순서·조건 통과 여부를 바꾼다(관측 가능한 누출).
세 곳 모두 배제되어 있고 소유자 인자가 있는 `listings_for_complex` 만 사용자 행을 준다.
**추가로 뺄 곳은 없다** — `listing` 을 세는 SQL 을 전수 확인했다.

---

## CR34-3 (가격 일관성) — 담당자의 기각을 **받아들인다**

### ① 격차 분해 기각 — 타당하다
지도는 500단지를 그리는데 **면적을 모른다**. 밴드 중위는 정의상 면적별 값이다.
따라서 "지도를 보정하면 맞아진다"는 내 전제가 틀렸다. 정의 차이가 시점 보정보다 크다는
실측(|A| 5.8% > |B| 3.4% · 67%)까지 붙었다. **"지도와 추천은 앞으로도 다르다"를 받아들인다.**
각 값에 `price_basis` 를 붙여 무엇인지 말하게 한 방향이 옳다.

### ② 더 큰 결함 발견 — **재현했고, 조치도 옳다**
독립 재측정에서 서울 전역 2,507단지 중 **50.8%** 가 조건 밖 면적을 표시하고 있었고
평균 |차| 22.2% · 최대 406.3%였다. 대우디오빌 사례도 정확히 재현된다.
조건 안에서 고르고 없으면 **null**(조건 밖 값으로 안 채움)은 이 저장소의 G2 와 일치한다.
프론트는 이미 `recent_price_krw === null` 을 "데이터 없음"으로 처리한다(`lib/mapMarkers.ts:36`).

### CR35-3 (중) — 그런데 **조치의 절반은 사용자에게 닿지 않는다**
서버는 `price_area_m2` · `price_basis` · `price_basis_note` 를 새로 싣지만
프론트는 셋 중 **아무것도 읽지 않는다**(`grep -rn "price_area_m2\|price_basis_note" frontend/src` → 0건).
"조건 안에서 고른다"(값이 바뀌는 쪽)는 배포되면 곧바로 효과가 있지만,
"무엇인지 말한다"(왜 추천과 다른지)는 **아직 아무 화면에도 없다.**

### CR35-4 (중) — **자금계획이 추천과 같은 함수를 쓰는 경로는 제품에서 도달 불가**
서버는 `AffordabilityIn.complex_id` 를 받아 `complex_reference_price` 로 추천과 같은 밴드를 만든다.
설계는 옳다(추천이 부르는 `reference_band` 를 그대로 부른다 — 정책이 갈라지지 않는다).
그러나 **프론트는 `complex_id` 를 보내지 않는다.**

```
frontend/src/api/client.ts:169-174  AffordabilityRequest { purpose?, target_price_krw? }   ← complex_id 없음
frontend/src/App.tsx:251            planComplexPrice = planComplex?.recent_price_krw ?? null
```

즉 실제 사용자 경로는 여전히 **지도의 최근 체결가 1건**을 자금계획에 보내고, 응답에는
`basis: "client_supplied"` + "서버가 근거를 확인하지 않았습니다" 문장만 새로 붙는다.
**CR34-3 의 자금계획 항목은 서버 계약만 준비된 상태**이며 "화면 간 불일치를 끊었다"는 보고는
아직 사실이 아니다. (다만 지도 가격이 면적 조건 안으로 바뀐 덕에 실질 격차는 줄었다 — 인정한다.)

---

## PRICE-2 개별 검증

### ✅ 낡음 90일 — 계산이 맞고 선(線)도 근거가 있다
운영 지수로 재계산: 서울 **+0.985%/월**(≈0.99), 3개월 최대 **+3.32%**(≈3.3).
가격 축이 `100-|gap|*5` 이므로 3.3% → **16.6점**(≈17). 판정이 뒤집히는 ±10%까지는 약 180일(+7.1%).
"30일 미만을 요구하지 않는 이유"(비교 대상 실거래도 최대 30일 지연)도 일관적이다.

### CR35-10 (경) — 다만 90일은 **서울 기준 하나**다
같은 지수로 인천은 +0.069%/월 → 90일 이동이 **0.2%**(점수 1점)다. 서울 기준으로 잘라
인천·경기 외곽의 멀쩡한 호가를 버린다. 지역별로 나누자는 게 아니라, **하나로 두는 근거**
(단순함·설명 가능성)를 상수 주석에 한 줄 남기면 나중에 흔들리지 않는다.

### ✅ IDOR fail-closed — 실제로 그렇고 다른 경로로도 안 샌다
```
repo.listings_for_complex(1)            → []      (소유자 없이 부르면 0건)
repo.listings_for_complex(1, user_id=1) → 1건
B 가 A 의 id 로 GET 목록 → []  · PATCH → 404 · DELETE → 404 · A 의 행은 그대로 1건
없는 id 로 DELETE(A)     → 404          (남의 것과 없는 것이 같은 404)
404 본문 {"code":"NOT_FOUND","message":"매물을 찾을 수 없습니다"}   ← 내부 식별자·SQL 노출 없음
```
PostGIS 도 같은 규칙이다 — `:user_id` 가 NULL 이면 `= NULL` 이 NULL 이라 사용자 행이 한 건도
안 나온다. CRUD 4문 전부 `created_by_user_id = :user_id AND source = :source` 를 문장 안에
들고 있고 파이썬에서 소유권을 검사하는 형태가 아니다. `_UPDATABLE_COLUMNS` 화이트리스트라
키가 SQL 로 조립되지 않는다.

### ✅ DB CHECK — 운영에서 재현했다 (`BEGIN` → 016 → `SAVEPOINT`×12 → `ROLLBACK`)
| # | 입력 | 결과 |
|---|---|---|
| 1 | `user_entered` + 소유자 없음 | ⛔ `listing_user_source_pair` |
| 2 | 소유자 있음 + `source='portal'` | ⛔ `listing_user_source_pair` |
| 3 | 사용자행 `as_of` 누락 | ⛔ `listing_user_as_of` |
| 4 | 9,999,999원 | ⛔ `listing_user_price_range` |
| 5 | `area_m2 = 0` | ⛔ `listing_user_area_range` |
| 6 | `floor = 9999` | ⛔ `listing_user_floor_range` |
| 7 | `note` 201자 | ⛔ `listing_user_note_len` |
| 8 | `apt_dong` 21자 | ⛔ `listing_user_dong_len` |
| 9 | `as_of = 1999-12-31` | ⛔ `listing_user_as_of` (하한도 실제로 막는다) |
| 10 | 정상 사용자행 | ✅ 통과 |
| 11 | 정상 수집행(소유자·as_of 없음) | ✅ 통과 |
| 12 | 수집행 `floor = 9999` | ✅ 통과 — **수집 계약을 안 건드렸다** |

롤백 후 운영 스키마·데이터 잔여 **0**(신규 컬럼 0 · probe 계정 0).

### ✅ PATCH 규칙 — 강제된다. 우회 경로 없음
```
{}                                   422   가격만                             422
가격+as_of                           200   가격+as_of:null                    422
as_of:null 단독                      422   status:null / area_m2:null         422
floor:null                           200 → floor None (비우기)
note:""                              200 → note None
미지 필드(trust_score)               422
미래 as_of / 366일 전 / 9,999,999원  422
status=traded                        200 → used_in_recommendation False
```
경계도 정확하다: `as_of` 30일 `fresh/used=True` · 31·90일 `aging/used=True` ·
91·365일 `stale/used=False` · 366일 `422`. SQL 의 `as_of >= today-90` 과
`listing_staleness` 의 `days <= 90` 이 같은 경계를 가리킨다.
`area_m2: Infinity` 도 `finite_number` 로 422(SR24-6 함정 방어 확인).

### CR35-11 (중) — 오타에 대한 **유일한 그물**이 사라졌다
사용자 입력에서 `trust_score` 를 끈 것은 옳지만, 부작용으로 "시세 대비 −25% — 확인 필요"
경고까지 사라졌다. `problems` 의 ₩/㎡ 검사(200만~6,000만/㎡)는 **자릿수 실수만** 잡는다 —
9.2억을 3.0억으로 잘못 적으면 353만원/㎡ 라 통과하고, 추천 카드에는 "**적정가 하단 — 급매 가능**"
이 뜬다(실측). 지금은 `complex_reference_price` 가 이미 있으니 `POST`/`PATCH` 시 그 단지·면적의
밴드와 대조해 `problems` 한 줄("이 단지 59㎡ 최근 실거래 중위 대비 −57%입니다 — 금액을 다시
확인해 주세요")을 넣는 것이 싸고 정확하다. 점수가 아니라 **고지**라 이번 수정의 논리와 충돌하지 않는다.

---

## 배선 — 면적대 소멸

* ✅ **중복은 생기지 않는다.** 호가 84.97 + 실거래 84.9 → 후보 1건(listing)만.
  호가 84.97 + 실거래 84.97·59.9 → 84.97(listing) + 59.9(trade), 겹침 없음.
* ✅ `AREA_TOLERANCE_M2`(0.5)를 `_trade_area_groups` 의 군집 기준과 **같은 값**으로 쓴 것은 옳다.
  다른 값을 쓰면 "여기선 한 덩어리인데 저기선 두 개"가 생긴다.
* ✅ 상한(`MAX_CANDIDATES` 200) 검사가 호가·실거래 두 루프에 다 있고 `_capped` 가 사용자에게 말한다.
* ✅ `funnel["trade_only"]` 를 "호가가 하나도 없는 단지"로 좁힌 것은 합 계산상 옳다.
* ⛔ **"조건 탈락 호가 면적대도 차지한 것으로 센다"는 옳지 않다** → CR35-1.

---

## 담당자 자진 신고 2건에 대한 판정

### 1. PostGIS 실DB 미검증(`needs_db` 102건) — **차단하지 않는다**
운영 메모리 여유는 실측 **225MB**(16MB 는 과소평가)였지만 그래도 전량 실행은 권하지 않는다.
대신 **변경된 SQL 10종을 016 적용 상태의 운영 스키마에서 `PREPARE` 로 전수 통과**시켰고
016 미적용 상태에서 정확히 어디가 깨지는지도 결과로 확인했다. 남은 위험은 "문법은 맞고
의미가 틀린" 구간뿐이며 그건 배포 후 §5-4 의 지도 호출 1회로 드러난다.

### 2. 후보 조회가 사용자 입력을 못 봄 (ⓐ 정렬 · ⓑ 면적 조건) — **차단하지 않는다. 단, 응답이 거짓말을 한다**

ⓐ·ⓑ 는 **교차 사용자 누출을 막기 위한 대가**이고 그 교환은 옳다(누출은 아무도 못 알아채고
결측은 사용자가 알아챈다). ⓐ 는 `CANDIDATE_COMPLEX_LIMIT`(120)에 걸리는 넓은 지역에서만
문제가 되고, 관심 단지 5~10곳이라는 사용 맥락에서는 지역을 좁히면 해소된다.

### CR35-7 (중) — 다만 `used_in_recommendation` 은 **서버가 보증할 수 없는 것을 보증한다**
`routes.py::_listing_out` 은 이 값을 `staleness` + `status` 로만 만든다. ⓑ 상황
(평수 조건 + 실거래·unit_type 없이 내 호가만 있는 면적대)에서 그 단지는 **후보 조회에 아예
안 들어오므로** 실제로는 반영되지 않는데 응답은 `true` 라고 말한다. 스키마 주석이
"이게 계산에 들어갔나는 **서버만 아는 사실**이라 서버가 말해야 한다"고 적은 바로 그 약속을 어긴다.
최소한 필드 설명과 `notes` 에 조건을 달 것 — "낡지 않고 활성이면 계산 대상입니다 — 다만 그 단지가
지역·예산·평수 조건으로 후보 조회에 들어오지 않으면 반영되지 않습니다".

---

## 나머지 지적 (전부 비차단)

* **CR35-8 (경)** `list_my_listings` 는 `limit` 기본 200으로 잘리는데 `summary` 와 중복 경고(`siblings`)가
  그 절단을 모른다. 201건째부터 "이미 N건 등록돼 있습니다"가 틀리고 `summary.total` 이 실제보다 작다.
  현실적 규모는 아니지만 **조용히** 틀린다.
* **CR35-9 (경)** `liquidity.active_listing_ratio_pct` 에 사용자 행이 섞인다. 지금은 미표시·미채점이고
  주석이 경고한다. 표시하려는 사람이 주석을 읽지 않을 수 있으니 `is_user_entered` 로 갈라 세는 쪽이
  낫다(계산 비용 0).
* **CR35-12 (경)** 시각 기준이 섞인다 — `created_at`/`updated_at` 은 UTC(`datetime.now(timezone.utc)`),
  `as_of`/`age_days`/`stale_cutoff` 는 로컬 `date.today()`. 실측에서 `as_of 2026-07-29` 인 행의
  `created_at` 이 `2026-07-28T23:21Z` 로 나왔다. 자정 근처에서 경과일이 하루 어긋난다.
* **(호평)** `_common.mask_secrets` 를 `SystemExit` 경로에 **직접** 건 것(SR30-6)은 문구만 고친 게 아니라
  적어 둔 방어가 실제로 그 일을 하게 만든 수정이다. `FIELD_ENCRYPTION_KEY` 를 바이트로 재게 한 것도
  마찬가지고, `MIN_JWT_SECRET_CHARS` 는 **재는 쪽이 옳고 이름이 틀렸다**는 판단이 정확하다
  (UTF-8 에서 문자 수 ≤ 바이트 수이므로 문자로 재는 게 더 엄격하다).
  `test_security.py:624` 가 옛 이름의 부활까지 막는다.

---

## 판정 요약

**⛔ FAIL — 차단 2건.**

| ID | 내용 | 통과 조건 |
|---|---|---|
| CR35-1 | 조건 밖 호가가 조건 안 실거래 후보를 ±0.5㎡ 안에서 **흔적 없이** 지운다 | `listing_areas.append` 를 `area_ok` 통과 뒤로 + 경계 회귀 테스트 |
| CR35-2 | 존재하지 않는 '내 매물' 화면으로 사용자를 안내한다(`notes`·`missing` 에 실제로 나감) | 화면을 붙이거나 문장에서 화면 이름을 뺀다(+ 이중 마침표) |

**차단하지 않은 것을 분명히 한다.** 최우선 지시 2건은 둘 다 해소를 결과로 확인했다 —
배포 순서 경고는 정확하고(수치 2개만 손보면 된다), 사용자 입력 신뢰도 오염은 옳은 자리에서
옳은 방법으로 끊겼으며 수집 경로는 회귀 없이 그대로 돈다. CR34-3 에서 담당자가 내 전제를
기각한 것도 받아들인다 — 근거가 내 것보다 낫다. 자진 신고 2건도 차단 사유가 아니다.
**차단은 오늘의 결과로만 정당화한다:** 위 두 건은 이번 델타가 **새로 만든** 것이고, 둘 다 이
저장소가 반복해서 지켜 온 하한선(조용히 잃지 않는다 · 없는 것을 있다고 말하지 않는다)을
직접 넘는다. 고치는 비용은 각각 한 줄과 한 문장이다.

> 이번 라운드에서 가장 값진 것은 **자기 조치가 만든 값을 스스로 되재 본 것**이다.
> "호가를 넣으면 가격 축이 산다"를 실측으로 붙였고(no_signal → applied 53.35 · 커버리지 20%→68%),
> "비싼 걸 넣을수록 점수가 오른다"를 숫자로 드러냈다(64.5 vs 56.0). 그 습관 덕에 내가 할 일은
> 재현과 경계 찌르기로 끝났다. 남은 두 건도 같은 성격이다 — **효과를 잰 자리 바로 옆의 경계**를
> 한 번 더 찔러 보면 나왔을 것들이다.

---

## CR-036 · 2026-07-29 · CR-035 차단 2건 재검증 · `eligible_for_recommendation` 계약 변경 · 내 매물 화면

**리뷰어** code-reviewer · **대상** `8bf21dd` 이후 미커밋 — 수정 44파일 + 신규 16 ·
**판정 ✅ PASS** (차단 0건. 차단 2건 **둘 다 결과로 해소 확인**. 아래 지적 6건은 전부 비차단이며,
그중 CR36-1·CR36-2 는 **다음 라운드에 닫을 것**)

### 실행 검증 (전부 직접 돌림 · 주장과 대조)

| 항목 | 주장 | 실측 | 결과 |
|---|---|---|---|
| 백엔드 | 1,398 passed / 103 skipped / 0 failed | junitxml `tests=1501 skipped=103 failures=0 errors=0` → **1,398 passed** | ✅ 정확히 일치 |
| 프론트 | 843 passed / 44 files | `Test Files 44 passed · Tests 843 passed` | ✅ |
| 빌드·타입 | — | `vite build` exit 0 (293.70 kB) · `tsc --noEmit` **exit 0** | ✅ |
| 변경 규모 | — | `git diff --stat` **44 files · +4,892 / −390** + 신규 16 | ✅ |
| `needs_db` 내역 | 21건 | `-rs` 실측: `test_postgis_repo` 81 · `test_postgis_user_listings` **22**(15+7) = 103 | ⚠️ 22건(집계 차이, 무해) |

리뷰 중 소스에 **변이 16종**을 넣었다 돌려놨다. 종료 시점 트리는 위 수치로 재확인했고
`MUTANT` 잔여 0 · `git diff --stat` 동일이다.

---

## ⛔→✅ CR35-1 (차단 해소) — API 전 구간으로 **직접 재현**했다

담당자 보고를 믿지 않고 리뷰어가 짠 스크립트로 `POST /api/v1/recommendations` → `GET .../{job_id}`
전 구간을 돌렸다(인메모리 리포지토리 · 실제 라우터·러너 경유).

| 케이스 | before(호가 넣기 전) | after(호가 넣은 뒤) |
|---|---|---|
| **A** 조건 80~85 · 호가 **85.3**(밖) · 실거래 **84.97**(안) | `[(84.97, trade)]` | `[(84.97, trade)]` · notes `면적 조건 밖 후보 1건` |
| **B** 조건 55~65 · 호가 84.97(밖) · 실거래 84.97+59.9 | `[(59.9, trade)]` dropped **1** | `[(59.9, trade)]` dropped **2** |

A 의 `after` 가 **대조군(before)과 완전히 같다** — 담당자 보고 그대로다. `excluded` 는 양쪽 0이고,
사라진 것이 아니라 애초에 사라지지 않으므로 기록할 것이 없다. B 는 결과가 그대로이면서
제외 건수가 1→2 로 **옳아졌다**(면적 조건에 실제로 걸린 것은 호가·실거래 둘).

### 중복이 안 생기는지 — **네 가지 형태로 찔러 봤다. 안 생긴다**

| 케이스 | 결과 |
|---|---|
| C 조건 없음 · 호가 84.97 · 실거래 84.97+59.9 | `[(59.9, trade), (84.97, listing)]` — 겹침 없음 |
| D 조건 없음 · 호가 **84.9**(실거래와 0.07 차) · 실거래 84.97+59.9 | `[(59.9, trade), (84.9, listing)]` — 오차 안이라 호가가 이긴다 |
| E 조건 없음 · 호가 84.97 **+ 85.4**(0.43 차) · 실거래 84.97 | `[(84.97, listing)]` — `group_duplicates` 가 접는다 |
| F 조건 80~85 · 호가 85.3(밖) **+ 84.5**(안) · 실거래 84.97 | `[(84.5, listing)]` · 제외 1건 — 밖은 떨어지고 안은 산다 |

### 회귀 테스트가 실제로 죽는가 — **변이 2종으로 확인**

| 변이 | 결과 |
|---|---|
| **M1** `listing_areas.append(area)` 를 `area_ok` **앞으로** 되돌림(= CR-035 당시 코드) | `test_조건_밖_호가가_조건_안_실거래_후보를_지우지_않는다` · `test_조건_밖_면적이_실거래로_되살아나지_않는다` **2건 FAIL** |
| **M2** `kept = [a for a in areas if conditions.area_ok(a)]` 필터 제거 | `test_조건_밖_면적이_실거래로_되살아나지_않는다` · `test_조건_안_호가는_여전히_같은_면적대_실거래를_대신한다` **2건 FAIL** |

경계 테스트는 **살아 있는 그물**이다(주석에 적힌 변이가 실제로 잡힌다).

### ⚖️ 담당자의 반박 — **옳다. 받아들인다**

CR-035 에 내가 쓴 문장:

> 호가 면적 `la` 가 조건을 어겼고 실거래 면적 `a ≈ la` 라면 `a` 도 같은 조건을 어긴다

**이 명제는 일반적으로 거짓이다.** 반례가 바로 이 결함이다 — `la=85.3` 은 `[80,85]` 를 어기고
`a=84.97` 은 만족하며 `|a−la|=0.33 ≤ 0.5` 다. 나는 바로 다음 문장에서 "두 값이 경계를 사이에 두고
갈릴 때만 결과가 달라진다"고 스스로 단서를 달았는데, 그러면 앞 문장은 **성립하지 않는 조건을
빼고 쓴 것**이 된다. 근거로 쓸 수 없는 문장이었다.

실제로 성립하는 논거는 담당자가 든 쪽이다: `kept = [a for a in areas if conditions.area_ok(a)]` 가
**실거래 면적에 조건을 독립적으로 다시 적용**한다. 그래서 `listing_areas` 가 무엇을 담든
"사용자가 배제한 면적이 실거래로 되살아나는" 일은 일어나지 않는다. 이 논거가 **빈말이 아니라
코드에 실제로 걸려 있다**는 것은 위 변이 M2 로 확인했다(지우면 84.97 이 되살아나 2건이 깨진다).
현재 코드 주석(`recommend.py:920-935`)도 이 이유를 적어 두었다 — 옳다.

> 정정 기록: CR-035 §"이 규칙이 실제로 필요한지"의 근거 문장을 위와 같이 대체한다.
> **결론(규칙 불필요)은 유지되고, 내가 댄 이유는 틀렸다.**

---

## ⛔→✅ CR35-2 (차단 해소) — 문구가 가리키는 화면에 **실제로 도달한다**

| 확인 | 결과 |
|---|---|
| 화면 존재 | `MyListingsScreen.tsx` · `ListingForm.tsx` · `useMyListings.ts` · `lib/userListings.ts` 신규 |
| **이름 일치** | 서버 문구 `'내 매물'에서 직접 입력하시면…` ↔ 시트 제목 `title = "내 매물"`(App.tsx:374) · 화면 헤딩 `내 매물 (직접 입력한 호가)` · 레일 버튼 `내 매물` |
| 이중 마침표 | `run_mvp_pipeline` 실행 → `notes`·`missing` 전문에서 `".."` **0건** |
| 진입로 ① 조건 레일 | `FilterRail` → `openListings(null)` — App 통합 테스트 있음 |
| 진입로 ② 주변 단지 | `{planComplex.name} 호가 입력` → `openListings({id,name})` — App 통합 테스트 있음 |
| 진입로 ③ AI 추천 카드 | `ReportCard` → `RecommendPanel` → `App.openListings` **배선은 있다**. 단 통합 테스트 없음 → **CR36-1** |

실제 문장(파이프라인 직접 실행):

```
notes[3] 가격 가중치 21.2%가 후보 전부에서 반영되지 않았습니다 — 활성 호가가 없어 …
        이 단지의 호가를 알고 계시면 '내 매물'에서 직접 입력하시면 가격 축이 반영됩니다.
        그만큼 나머지 축으로 재정규화했습니다.       ← ".." 없음
```

---

## ★ 계약 변경 (`used_in_recommendation` → `eligible_for_recommendation`) — **가드가 진짜다**

이번 라운드에서 가장 위험했던 것은 결함 자체가 아니라 **결함이 초록 위에 앉아 있던 것**이다
(`undefined === true` → 모든 호가가 "반영 안 됨" · TS 무력 · 목 때문에 전 테스트 통과).
그래서 새로 넣은 `src/test/apiContract.test.ts` 를 **변이 8종**으로 직접 찔렀다.

| 변이 | 기대 | 실측 |
|---|---|---|
| **F1a** `userListings.ts::eligibility` 만 옛 이름으로 되돌림 | 잡혀야 | ✅ 계약테스트 `src 전수 스캔` FAIL (+ 화면·순수함수 테스트 7건 동반 FAIL) |
| **F1b** src **+ 목까지** 옛 이름(앞뒤가 맞는 '옛 세계') | 잡혀야 | ✅ `호가 1건의 키가 같다` · `목록 키` · `전수 스캔` **3건 FAIL** |
| **F2** `api-spec.md` 201 예시만 옛 이름(문서→코드 방향) | 잡혀야 | ✅ `키가 같다` · `boolean 이다 — 옛 이름은 계약에 없다` **2건 FAIL** |
| **F6b** §2.5 의 201 예시 본문을 **통째로 비움(예시 0개)** | 잡혀야 | ✅ `JSON.parse("")` 로 **모듈 로드 실패 → Test File FAIL** |
| **F7** `#### POST /me/listings` 제목 문구 변경(마커 소실) | 잡혀야 | ✅ Test File FAIL |
| **F8** `// res 201` 주석 제거 | 잡혀야 | ✅ Test File FAIL |
| **F9** GET 목록 예시의 펜스 언어태그를 `jsonc` 로 | 잡혀야 | ✅ Test File FAIL |
| **F10** 문서에만 없는 필드(`verified`) 추가(문서가 앞서 나감) | 잡혀야 | ✅ 1건 FAIL |

**결론: 있는 척하는 가드가 아니다.** 양방향(목→문서 · 문서→목)이고, **예시가 0개가 되면
파싱이 조용히 통과하는 게 아니라 파일이 통째로 죽는다**(F6b·F7·F8·F9). 전수 스캔의 자기
방어(`RETIRED_FIELD` 를 조각으로 조립 · glob 이 비면 실패하는 별도 검사)도 옳은 설계다 —
`src` 파일 실측 **134개** 이고 검사 하한이 50이라 여유가 있다.

* 무해한 요철 하나: `indexOf("\`\`\`json")` 은 `\`\`\`jsonc` 에도 걸린다(접두 일치). POST 블록은
  `after: "// res 201"` 이 앞부분을 잘라내 결과가 같아 통과한다(변이 F5 실측). GET 블록에는
  `after` 가 없어 같은 변이가 잡힌다(F9). 지금은 결과가 옳지만, 개행까지 포함한 정확 매칭이
  의도를 더 분명히 한다.

### 서버가 새 필드를 안 보낼 때(구버전) — **"모른다"고 말한다**

`eligibility()` 가 `typeof raw === "boolean"` 이 아니면 `null` 을 준다 → 배지 **`반영 여부 미상`** ·
문장 "이 호가가 추천에 쓰일 수 있는지 서버가 알려 주지 않았습니다." 화면에 `추천에서 제외됨`
문자열이 **나오지 않는다**(테스트가 `not.toContain` 으로 못 박음). `summaryText` 도 숫자가
없으면 "반영 가능 N건"을 **아예 적지 않는다**. 모름을 아님으로 접지 않았다 — 이 저장소의 G2 다.

### 뜻까지 바꾼 것 — 옳다

배지를 `반영 가능`으로, 서버 `notes` 에 "실제로 반영되려면 그 단지가 …조건과 후보 조회 상한을
통과해야 합니다"를 **조건 없이 상시** 실었다(`routes.py::LISTING_ELIGIBILITY_NOTE`).
조건부로 붙이면 "지금은 해당 없음"을 서버가 판정해야 하는데 그건 알 수 없다 — 그 판단이 정확하다.
이름만 바꾸고 거짓을 남기지 않았다(CR35-7 · SR31-2 통과).

---

## CR35-5/6 (DEPLOY.md) — **CR30-3 에서 뚫린 그 구멍이 이번엔 막혔다**

`test_절차서의_제약_확인_목록이_마이그레이션과_일치한다` 에 변이 5종.

| 변이 | 결과 |
|---|---|
| **D1** 목록에서 `listing_user_floor_range` 삭제(개수 7 유지) | ✅ FAIL |
| **D2** 삭제 + 개수도 6으로(= CR-035 당시 상태) | ✅ FAIL |
| **D3 ★변이 D** 목록에서 빼고 **본문 다른 문단에 이름만 언급** | ✅ **FAIL** — 첫 시도에 살아남았던 그 변이가 죽는다 |
| **D4** 마이그레이션에 제약 1개 추가 · 문서 무변경 | ✅ FAIL |
| **D5** 목록 **순서만** 뒤집기 | ✅ PASS(옳다 — 집합 비교) |

D3 이 죽는 이유가 정확하다: `_EXPECT_BLOCK_RE` 가 `# 기대 … **N건** …:` **바로 뒤의 연속된
`#   listing_user_*` 줄만** 목록으로 본다. 문서 전체를 뒤지지 않으므로 "설명 문단에 한 번
언급했다"가 알리바이가 되지 않는다. 개수도 마이그레이션 기준으로 함께 잰다.
**고친 파싱은 충분하다.**

### 읽기 경로 4곳 — 내용은 맞다. 다만 **이쪽에는 그물이 없다** → CR36-3

리뷰어가 `postgis.py` 의 SQL 상수를 전수 추출해 016 신규 컬럼 참조를 독립 확인했다:

```
_BBOX_SQL                 created_by_user_id   (as_of 는 rp.as_of = 정비사업. 016 아님)
_AREA_MATCH_SQL           created_by_user_id   → _CANDIDATES_* · _SCOPE_STATS_* 가 공유
_CANDIDATES_SQL_TEMPLATE  created_by_user_id
_LISTINGS_SQL             created_by_user_id + li.as_of   ← 여기만 as_of 도 참조
(나머지는 CRUD: _USER_LISTING_COLUMNS · _DELETE_USER_LISTING_SQL)
```

문서의 네 줄과 "`_LISTINGS_SQL` 만 `li.as_of` 도 본다"는 단서까지 **전부 사실**이다.
그러나 제약 목록과 달리 **읽기 경로 목록을 코드와 대조하는 테스트가 없다** — 다섯 번째 경로가
생기면 문서는 조용히 낡는다. CR35-5 를 고칠 값어치가 있었다면 이쪽도 같다.

---

## SR31-1 / SR31-3 / SR31-4 판정

* **SR31-1 (제어문자 422)** — 계약을 좁은 쪽에 맞춘 판단은 **옳다**. 정규식
  `[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]` 는 `\t\n\r` 를 정확히 비껴간다. POST·PATCH 가
  `_clean_optional_text` **한 함수**를 공유해 "POST 로는 막히는데 PATCH 로는 들어가는" 상태가
  구조적으로 안 생긴다. 오류 문장에 입력값을 넣지 않은 것도 SR25-2 규약과 일치.
  ※ 정확히 말하면 PG 가 타입 수준에서 막는 것은 NUL 뿐이고 나머지 C0/C1 은 저장 가능하다 —
  즉 이건 "PG 에 맞춘 것"이 아니라 **표현 계층의 제품 판단**이다. 주석이 그 점을 이미 구분해
  적어 두었으므로 문제 없다(문구만 "좁은 쪽"보다 "표현 계층"이 정확하다).
* **SR31-3 (200건 · 409)** — `>=` 로 판정하고 목록 상한과 **같은 상수**를 쓴 것이 CR35-8 을
  구조적으로 닫는다(201건째가 만들어질 수 없으므로 `summary.total`·중복 경고가 절단 때문에
  틀릴 상태가 생기지 않는다). 409 + `LIMIT_REACHED` + 다음 행동 안내까지 옳다.
  다만 프로토콜 선언만 상수를 안 쓴다 → **CR36-4**.
* **SR31-4 (`SENSITIVE_PATHS`)** — `/api/v1/me/listings` 추가. `startswith` 라
  `/me/listings/{id}` 도 덮인다. 경로는 남기고 쿼리만 지우는 선택이 옳다(운영 시 어떤
  엔드포인트가 몇 번 불렸는지는 남아야 한다).

---

## CR35-4 (자금계획 = 추천) — **값이 실제로 같다. 단, 그걸 지키는 테스트가 API 경로에 없다**

프론트가 `complex_id`+`area_m2` 를 보내고 지도의 `recent_price_krw` 를 안 보내는 것은
`useAffordability.planRequest` · `App.tsx:656-663` 에서 확인했고 App 테스트가 고정한다
(*"고른 단지의 **id** 가 `/affordability` 로 나간다 — 금액은 화면이 정하지 않는다"*).

**같은 값인지 숫자로 확인했다** (시장지수 있음 · 조건 55~65 · 실거래 59.9와 64.8 두 무리):

```
추천 카드   area=59.9  est=529,699,059      area=64.8  est=738,514,957
자금(60.0)  krw=529,699,059  basis=time_adjusted_band  as_of_ym=2026-07
자금(59.9)  krw=529,699,059      자금(64.8)  krw=738,514,957
```

**원 단위까지 일치한다.** 설계(같은 `reference_band` 를 부른다)가 결과로 확인됐다.

### ⚠️ 그런데 그 일치는 `repo.complex_region_code` 가 있을 때만이다 → CR36-2

같은 시나리오에서 그 메서드만 없애면:

```
추천 카드  529,699,059 (시점 보정 적용)
자금계획   500,000,000 (basis=trade_band · 보정 안 함)   → 5.6% 괴리
```

`InMemoryRepository` 에는 `complex_region_code` 가 **없다**. 즉 인메모리를 쓰는 **모든 API
테스트에서 자금계획은 언제나 `trade_band` 로 떨어지고**, CR35-4 의 핵심 명제("추천과 같은 값")는
API 경로에서 **한 번도 실행되지 않는다**. 지금 그 명제를 지키는 것은 `test_price_consistency.py`
의 손수 만든 `_Repo` 하나뿐이다. 인메모리에 두 줄을 더하면 API 전 구간이 그물에 들어온다.

### 면적 선택 근거 문구 — 사실이다 (한 군데만 느슨)

`planArea` 는 ① 지도 체결가의 면적 → ② 내 조건 중앙값 → ③ 국민평형 84 순이고, 문구가 각각
정확하다(③ 은 "면적을 정하지 않아 국민평형으로 계산했습니다. 다른 평형이면 금액이 달라집니다"
로 **모름을 말한다**). 실측: 조건 밖 면적을 보내면 `표본 0건` 사유가 그대로 나오고 계획을
지어내지 않는다.
느슨한 곳은 `targetPriceView` 의 `time_adjusted_band` 상세 문장 *"추천 카드와 같은 값입니다"* 다 —
**어느** 카드인지는 말하지 않는다. 단지에 면적대가 둘이고 계획 면적이 `my_condition`(중앙값)에서
왔으면 사용자가 보고 있는 카드와 다른 카드의 값일 수 있다(위 실측에서 60.0 → 59.9 카드값).
바로 옆에 `planAreaNote` 가 면적을 적으므로 오독 여지는 작다 → **CR36-5(경)**.

---

## 이월 판단 (ⓐ 정렬 · ⓑ 면적 근거) — **동의한다**

* **ⓐ 오늘 실효 0** — 동의. 운영 `listing` 0행(CR-035 실측)이면 `active_listing` 항은 전 단지
  동률이라 순서를 정하는 것은 뒤의 기준들이다. 관측 가능한 차이가 없다.
* **ⓑ 재현되지만 조용하지 않다** — 동의. `_SCOPE_AREA_NOTE` 가 조건부 없이
  *"⚠️ 이 판정에는 **직접 입력하신 호가를 세지 않습니다** — … 그래서 내 호가만 있는 면적대는
  여기서 빠집니다."* 를 붙인다. 조건부로 달지 않은 이유(달려면 같은 누출 경로를 다시 열어야
  한다)까지 정확하다. API 테스트도 있다.
* **다음 라운드에 PG 컨테이너와 묶는다 — 동의.** 세 쿼리에 `:user_id` 를 흘리는 변경은
  교차 사용자 누출을 다시 여는 방향이라 **검증 없이는 손대면 안 되는 종류**인데,
  지금 그물이 `needs_db` **22건 전부 skip** 이다. 그물을 먼저 놓는 순서가 옳다.

**덤으로 확인한 것**: 담당자가 지시 밖에서 고친 제외 사유 문장("매물 근거가 없거나" → 사실 추가)은
방금 호가를 넣은 사용자에게 거짓으로 읽히던 문제를 정확히 겨냥했다. 지시받지 않은 자리에서
**사용자 눈으로 문장을 다시 읽은 것**이 이번 라운드에서 가장 값진 습관이다.

---

## 지적 (전부 비차단)

### CR36-1 (중) — 세 진입로 중 **하나가 그물 밖**이고, 끊기면 버튼이 조용히 사라진다
`frontend/src/App.tsx:607`(`onAddListing={openListings}`)

변이 실측:

| 변이 | 결과 |
|---|---|
| **A1** `App.tsx` 에서 `onAddListing={openListings}` 삭제 | **843 passed / 44 files 전부 통과** · `tsc --noEmit` **exit 0** |
| **A2** `FilterRail` 의 `onOpenListings` 삭제(대조군) | `내 조건 옆의 '내 매물' 버튼으로…` **FAIL** |

`onAddListing?` 이 선택 prop 이고 `ReportCard` 가 `price.askKrw === null && onAddListing` 일 때만
버튼을 그린다(죽은 버튼 금지 — 그 자체는 옳은 설계다). 그래서 **배선이 끊기면 오류가 아니라
버튼이 없어진다.** 그러면 CR35-2 가 막으려던 상태("서버는 가라는데 갈 길이 없다")가
추천 카드 자리에서 그대로 되살아난다. 지금 배선은 정상이고 두 진입로는 그물이 있으므로
차단하지 않는다. `App.test.tsx` 에 추천 결과 → `이 단지 호가 입력` → `내 매물` 도달 테스트 1건.

### CR36-2 (중) — 인메모리에 `complex_region_code` 가 없어 **CR35-4 의 명제가 API 에서 안 돈다**
`backend/app/repositories/memory.py`

근거·수치는 위 CR35-4 절. 이 결함의 성격은 "제품이 틀렸다"가 아니라 **"고쳤다고 보고한 것을
지키는 테스트가 실제로는 다른 분기를 밟는다"** 이고, 그건 이 라운드 전체의 주제(목이 낡아도
초록)와 같은 형태다. 인메모리에 `complex_region_code(complex_id) -> region_code` 를 더하고
`test_user_listing_wiring.py` 류에 "추천 카드 est == /affordability target_price.krw" 단언 1건.

### CR36-3 (경) — DEPLOY.md **읽기 경로 목록**에는 대조 테스트가 없다
`deploy/DEPLOY.md §5-3b` · `backend/tests/test_deploy_config.py`

내용은 오늘 기준 정확하다(위에서 전수 확인). 다만 제약 목록만 마이그레이션과 대조하고,
읽기 경로 넷은 손으로 적힌 채다. `postgis.py` 에서 `created_by_user_id` 를 참조하는 **SQL 상수
이름 집합**을 뽑아 문서 블록과 대조하면 같은 형태로 닫힌다(CRUD 상수는 제외 목록으로).

### CR36-4 (경) — 상한 상수가 **한 곳에 안 모였다**
`backend/app/repositories/base.py:558`

```python
def list_user_listings(self, user_id: int, *, complex_id: int | None = None,
                       limit: int = 200) -> list[UserListingRecord]: ...   # ← 리터럴
```

같은 파일 179행의 `MAX_USER_LISTINGS = 200` 주석이 *"나눠 두면 언젠가 한쪽만 바뀐다"* 라고
적어 둔 바로 그 형태다. 두 구현(`memory` · `postgis`)은 상수를 쓰는데 **프로토콜 선언만**
리터럴이다. `limit: int = MAX_USER_LISTINGS` 로.

### CR36-5 (경) — "추천 카드와 같은 값입니다"가 **어느 카드인지 말하지 않는다**
`frontend/src/lib/affordability.ts::targetPriceView`

근거는 위 CR35-4 절. 문장을 `map_trade` 기준일 때로 좁히거나, 면적을 문장 안에 넣어
*"84.97㎡ 추천 카드와 같은 값입니다"* 로 하면 오독 여지가 사라진다.

### CR36-6 (경) — 계약 대조가 **`/me/listings` 한 엔드포인트에만** 걸려 있다
`frontend/src/test/apiContract.test.ts`

이번 사고의 재발을 막는 것은 맞지만, 같은 사고가 지도·추천·자금계획 목에서 나면 그때도
전부 초록이다(그 목들은 문서와 대조되지 않는다). 지금 당장 넓히자는 게 아니라,
**어느 계약이 대조되고 어느 계약이 안 되는지**를 파일 머리말에 한 줄 남기면 다음 사람이
"계약 테스트가 있으니 괜찮다"고 오해하지 않는다.

### 이월 확인 (CR-035 에서 넘어온 것)
* **CR35-3 절반 해소** — `price_area_m2` 는 `ComplexCard` 가 `전용 84.97㎡` 로 렌더한다(✅).
  `price_basis_note` 는 여전히 타입만 있고 **아무 화면도 읽지 않는다**(client.ts:272).
* **CR35-10 해소** — `base.py:135-155` 에 서울/경기/인천 월간 변동률을 나란히 적어
  90일이 **서울 기준 보수적 상한**임을 읽을 수 있게 했다. 충분하다.
* **CR35-11 미해소(중, 유지)** — `_listing_problems` 는 여전히 ₩/㎡ 범위만 본다.
  9.2억을 3.0억으로 적어도(59.5㎡ → 504만원/㎡) 경고가 없고 카드에는 "적정가 하단 — 급매 가능"이
  뜬다. `complex_reference_price` 가 이미 `routes.py:638` 에 있으므로 POST/PATCH 에서 한 줄
  대조하는 비용이 거의 0이다.
* **CR35-9 · CR35-12** — 이번 델타에서 다루지 않았다(둘 다 경, 유지).

---

## 판정 요약

**✅ PASS — 차단 0건.**

| CR-035 차단 | 통과 조건 | 결과 |
|---|---|---|
| CR35-1 | `append` 를 `area_ok` 뒤로 + 경계 회귀 테스트 | ✅ API 전 구간 재현 · 중복 없음(4형태) · 변이 M1/M2 로 그물 확인 |
| CR35-2 | 화면을 붙이거나 문구에서 화면 이름을 뺀다(+이중 마침표) | ✅ 화면 신설 · 이름 일치 · `..` 0건 · 진입로 3개 배선(2개 그물, 1개는 CR36-1) |

**차단하지 않은 이유를 분명히 한다.** 남은 6건은 전부 *"제품이 지금 틀렸다"* 가 아니라
*"틀리게 되는 날 조용히 틀린다"* 이고, 그중 둘(CR36-1·CR36-2)은 다음 라운드에 닫아야 한다.
이번 델타가 **새로 만든** 거짓·유실은 없다. 오히려 이 라운드는 자기가 만든 사고
(`undefined === true`)를 **스스로 찾아내 그 사고를 잡는 그물까지 짜 왔고**, 그 그물이
변이 8종을 전부 죽인다는 것을 리뷰어가 결과로 확인했다.

> 이번 라운드에서 가장 값진 것은 **"테스트가 초록인데 화면은 거짓말을 하고 있었다"를
> 스스로 신고한 것**이다. 그 한 문장이 없었으면 나는 목을 읽고 "잘 돌아간다"고 썼을 것이다.
> 다음 라운드에서 볼 것도 같은 자리다 — **A1 변이가 살아남는 곳이 아직 있다.**

---

## CR-037 · 2026-07-29 · SR32-1(지도 예산 계약 변경) 재검증 · CR-036 비차단 이월분

**리뷰어** code-reviewer · **대상** `8bf21dd` 이후 미커밋 — 57파일 수정 +8,155 / −499 · 신규 3
**판정 ⛔ FAIL** — 차단 **1건**(`CR37-1`). 나머지 7건은 비차단.

> 요약: **SR32-1 의 본론은 제대로 닫혔다.** 금액이 URL 에서 사라졌고, 로그 방어를
> "민감경로 목록"에서 **"기본이 지운다"** 로 뒤집은 것(`main.log_target`)은 이 사고의
> 원인(목록은 언젠가 한 줄이 빠진다)을 정면으로 없앤 수정이다. CR-036 이월분 4건도
> 전부 결과로 확인했다 — CR36-2 는 변이 2종, CR35-11 은 오타 재현과 오탐 경계,
> CR36-4 는 리터럴 금지, CR36-1 은 배선 3곳이 모두 죽는다.
>
> 그런데 **이번에 새로 만든 "카나리아"가 정상 상황에서 운다.** 서버가 산출하는 지도
> 예산과 화면이 쓰는 예산은 `PropertyFacts` 가 달라 **원래 다른 숫자**다(운영 세율로
> 실측 1,026,560,000 vs 1,024,580,000). 그 차이가 곧바로 `conflicts` 로 잡혀
> 사용자에게 "예산 기준 금액이 서로 다릅니다"가 뜬다 — 아무것도 고장나지 않았는데.
> 코드 주석(`routes.py:805-808`)과 `api-spec §4` 가 *"지도·추천·자금계획이 같은 상한을
> 말한다"* 고 적은 문장이 **오늘 기준 사실이 아니다.**

---

### 실행 검증 (전부 직접 돌림 · 주장과 대조)

| 항목 | 주장 | 실측 | 결과 |
|---|---|---|---|
| 백엔드 | 1,424 passed / 103 skipped / 0 failed | junitxml `tests=1527 skipped=103 failures=0 errors=0` → **1,424 passed** | ✅ 정확히 일치 |
| 프론트 | 918 passed / 46 files | `Test Files 46 passed · Tests 918 passed` | ✅ |
| 빌드·타입 | — | `vite build` exit 0 (297.84 kB) · `tsc --noEmit` **exit 0** | ✅ |
| 변경 규모 | — | `git diff --stat` **57 files · +8,155 / −499** + 미추적 3 | ✅ |
| **프론트 병렬 크래시** | "간헐 크래시(기존 문제)" | **9회 연속 실행 전부 정상**(46/918) | ⚠️ **재현 안 됨** |

리뷰 중 소스에 변이 12종을 넣었다 되돌렸다. 종료 시점 `git diff --stat` 동일 ·
잔여 마커 0 · 양 스위트 재실행 그린을 확인했다.

> **병렬 크래시에 대한 판정**: 9회 중 0회다. **오늘의 결과로는 결함이라고 쓸 수 없다.**
> 다만 *만약* 실재한다면 그 자체가 결함이 맞다 — 간헐적으로 죽는 스위트는 게이트로 쓸 수
> 없고, "또 그거겠지"가 진짜 실패를 덮는다. 재현되면 로그를 남기고 `pool`/`maxWorkers`
> 를 조정하되, **재현 없이 설정을 만지지는 말 것**(원인 모르는 설정 변경은 증상만 숨긴다).

---

## ⛔ CR37-1 (차단 · 중대) — 지도 예산과 화면 예산은 **원래 다른 숫자**다. 카나리아가 그걸 사고로 신고한다

**파일** `backend/app/api/routes.py:888` · `backend/app/api/routes.py:686-693` ·
`frontend/src/App.tsx:176,255,277` · `frontend/src/lib/budgetStatus.ts:176-199`

### 무엇이 다른가

| | 함수 호출 | `PropertyFacts` |
|---|---|---|
| 지도(`budget=mine`) | `_resolve_map_budget` → `compute_affordability(borrower, rules, prop=PropertyFacts(purpose=purpose))` | `area_m2` **기본값 84.0** |
| 자금계획(`/affordability`) | `compute_affordability(..., prop=PropertyFacts(area_m2=body.area_m2, ...))` | `area_m2` = **고른 단지의 면적** |

프론트의 지도·목록 판정 예산은 `budgetKrw = afford.data.max_purchase_krw`(App.tsx:176)이고,
그 `afford` 는 **고른 단지 기준**으로 부른 것이다(`planTarget.kind === "complex"` →
`planRequest` 가 `area_m2` 를 싣는다). 즉 두 값의 `area_m2` 가 구조적으로 다르다.

### 실측 (운영 세율 `config/tax_rules.yaml` · 현금 5억 · 연소득 1억 · 무주택)

```
area=  84.00  max_purchase_krw = 1,026,560,000          <- 서버가 지도에 쓰는 값
area=  85.00  max_purchase_krw = 1,026,560,000
area=  85.01  max_purchase_krw = 1,024,580,000  (-1,980,000)   <- 농특세 0.2% (85m2 초과)
area= 114.00  max_purchase_krw = 1,024,580,000          <- 화면이 쓰는 값
```

### API 전 구간 재현 (희망가 미저장 · 114.5㎡ 단지 선택 · `budget=mine` · `purpose=live`)

```
화면 budgetKrw (선택 단지 114.5m2): 1,024,580,000
서버 budget 블록: {'applied': True, 'basis': 'max_purchase', 'reason': None}

             가격 | 서버 over_budget | 화면 판정
  1,020,000,000 |            False | False
  1,025,000,000 |            False | True     <- 갈림
  1,026,000,000 |            False | True     <- 갈림
  1,030,000,000 |             True | True
-> conflicts = 2
```

`budgetApplied` 는 **기본값 `true`**(App.tsx:163)이므로 이건 예외 경로가 아니라 **기본 경로**다.
그 결과 화면에 이 문장이 `role="status"` 로 뜬다(App.tsx:566):

> 예산 초과 표시가 서버 판정과 2건 어긋납니다 — 같은 가격을 보고 답이 갈렸다면
> 예산 기준 금액이 서로 다른 것입니다. 목록·지도에는 화면 판정을 표시합니다.

`basis` 는 양쪽 다 `max_purchase` 라 `budgetStatusView` 는 침묵한다. 즉 사용자가 받는
설명은 위 한 문장뿐이고, **원인은 제품 자신이 만든 것이라 사용자가 고칠 수 없다.**

### 왜 차단인가

1. **오탐이다.** 이번 라운드의 판정 기준에 "오탐도 결함"이 명시돼 있고, 지시는
   *"불일치 안내가 정상 상황에서 뜨지 않는지(늘 뜨는 경고는 아무도 안 읽습니다)"* 를
   확인하라고 했다. **뜬다.** 그리고 한 번 학습되면 이 안내가 잡으려던 진짜 신호
   (저장한 희망가가 서버에 안 닿았다)까지 함께 무시된다 — 카나리아가 자기 목적을 죽인다.
2. **문서와 주석이 오늘 기준 거짓이다.** `routes.py:807-808` *"프론트의
   `effectiveBudgetKrw`(희망가 ?? 한도)와 같은 규칙이라 지도·추천·자금계획이 같은 상한을
   말한다"* · `api-spec §4` 동일 문구. 우선순위 규칙은 같지만 **한도 계산의 입력이 달라
   금액이 다르다.** 이 저장소가 반복해서 지켜 온 "있는 척하지 않는다"에 직접 걸린다.
3. **이번 델타가 새로 만들었다.** 이전 계약에서는 프론트가 `max_price_krw` 로 **자기 숫자를
   그대로** 보냈으므로 서버와 화면이 어긋날 수 없었다. 금액을 URL 에서 빼는 것은 옳고
   되돌릴 일이 아니지만, 그 대가로 생긴 이 갈라짐이 지금 무방비다.
4. **지키는 테스트가 없다.** 1,424 + 918 중 이 명제를 밟는 테스트가 0건이다 —
   CR36-2 를 만든 이유와 정확히 같은 형태다("고쳤다고 보고한 것을 테스트가 안 밟는다").

### 통과 조건 (둘 중 하나 + 회귀 테스트)

* **(A) 같게 만든다** — 지도 판정에 쓰는 화면 예산과 서버 예산이 **같은
  `PropertyFacts`** 에서 나오게 한다. 예: 화면이 목록/지도 판정용 한도를 **면적을 싣지
  않은** `/affordability` 호출에서 얻고, 단지별 계획(`plan`)은 지금처럼 따로 부른다.
  (서버가 지도 응답에 금액을 싣는 방식은 **금지** — SR32-1 최소 노출 원칙.)
* **(B) 주장을 내린다** — `routes.py:805-808` · `api-spec §4` 에서 "같은 상한" 문구를 빼고,
  제품이 스스로 만드는 차이에 대해서는 `verdictConflictNotice` 가 울지 않게 한다
  (예: 차이의 근거를 서버가 밝혀 화면이 구분하게 한다).

어느 쪽이든 **API 전 구간 테스트 1건**을 요구한다: 85㎡ 초과 단지 · 희망가 미저장 ·
`budget=mine` 에서 `checkVerdicts(...).conflicts === 0`(또는 두 금액이 같음)을 단언할 것.
지금은 이 시나리오가 그린이므로, 테스트 없이 고치면 다음에 또 갈라져도 아무도 모른다.

---

## 검증 요청 항목별 판정

### 1. `over_budget` 정본을 화면 판정으로 — **논증은 성립한다. 카나리아의 결론만 틀렸다**

세 근거를 각각 확인했다.

| 근거 | 판정 | 확인 방법 |
|---|---|---|
| ① 카드가 보여주는 값이 `recent_price_krw` 라 배지도 그것으로 서야 한다 | ✅ 옳다 | `ComplexCard.tsx:54` · 금액 렌더 자리와 동일 필드 |
| ② 판정이 필요한 자리가 지도만이 아니다 | ✅ 옳다 | 서버 `over_budget` 은 `/map/complexes` 응답에만 있다. 목록(`filterList`)·예산 토글(`ListFilterBar`)·추천 패널(`RecommendPanel` 자체 `outcome`)은 전부 `listBudgetKrw` 로 판정한다 — 서버를 정본으로 삼으면 추천 카드는 판정 근거가 아예 없다 |
| ③ 응답에 금액이 없어 서버 판정을 되짚을 수 없다 | ✅ 옳다 | `_budget_block` 이 금액을 싣지 않는다(그 선택 자체는 옳다) |

**두 판정을 유지하는 비용은 이득보다 작다** — 비교 함수 하나(`checkVerdicts`)와 문장 하나뿐이고,
`?? false` 로 접지 않은 것도 정확하다(접으면 서버가 침묵한 항목이 전부 거짓 불일치가 된다).

그러나 카나리아가 전제에서 결론으로 넘어가는 한 걸음이 틀렸다. 전제
*"같은 가격 필드를 같은 방향으로 비교하므로 갈리면 원인은 예산 금액 차이 하나뿐"* 은 **참이다**
(`_over_budget` 은 `price > budget`, `budgetVerdict` 는 `price <= budget ? within : over` — 같은 방향).
틀린 것은 그 다음이다 — *"그건 사용자가 고칠 수 있는 사실"*. 실제로 가장 흔한 원인은
**제품이 만든 `PropertyFacts` 불일치**이고 사용자는 손댈 수 없다(CR37-1).

### 2. M1c 의 유일한 방어 — **충분하지 않다. 우회로가 있다** → `CR37-3`

먼저 관문이 진짜인지 확인했다.

| 변이 | 결과 |
|---|---|
| **M1c** `verdictToOverBudget` 의 `unknown → null` 을 `false` 로 | ✅ `listFilter.test.ts` **2건 FAIL**. 화면 테스트는 **전부 통과**(담당자 보고 그대로) |

그런데 관문이 지키는 것은 **함수**이지 **성질**이 아니다. 호출부를 바꾸면 뚫린다.

| 변이 | tsc | 테스트 |
|---|---|---|
| **M1c-bis** `App.tsx:255` 를 `budgetVerdict(...) === "over"` 로 (헬퍼 우회) | TS6133(안 쓰는 import) | **918 passed** |
| **M1c-bis2** 위 + 안 쓰게 된 import 정리(개발자가 자연히 할 일) | **exit 0** | **918 passed / 46 files** |

즉 `over_budget` 이 지도 항목 전부에서 `null → false` 로 접혀도 **타입도 테스트도 아무 말이
없다.** 오늘은 무해하다(읽는 곳이 `=== true` 라 화면이 같고, `checkVerdicts` 는 덮기 전
원본 `map.items` 를 본다). 그러나 이건 "증상이 없어서 안 잡힌다"이지 "그물이 있다"가 아니다.

**닫는 법(비차단, 다음 라운드)**: `apiContract.test.ts` 의 `=== true` 소스 스캔은 **읽는 쪽**만
본다 — **만드는 쪽**도 한 줄 넣으면 된다(`App.tsx` 가 `over_budget:` 을 `verdictToOverBudget(`
없이 대입하지 않는다). 또는 그 매핑을 순수 함수로 빼고 "가격 미상 항목은 `null` 로 남는다"를
단언한다.

### 3. `purpose` 필수 타입 — **타입이 먼저 깨진다(사실). 다만 현재 값은 아무것도 안 바꾼다** → `CR37-5`

| 변이 | 결과 |
|---|---|
| `buildMapQuery` 의 `purpose: f.purpose` 삭제 | ✅ `tsc` **TS2741 — Property 'purpose' is missing … required in type 'MapQuery'** (테스트를 돌리기도 전에 깨진다) |

옵셔널로 두면 서버 기본값이 조용히 쓰인다는 지적을 **타입 자리에서** 막은 것은 옳다.
`apiContract.test.ts` 가 문서·클라이언트·조립부 세 곳을 함께 못박는 것도 옳다.

**죽은 코드인가 — 아니다. 다만 주석이 사실보다 앞서 있다.**
`purpose` 는 `_lending_setup` 의 `cap_facts` 로 들어가지만, **`config/tax_rules.yaml` 에
`purpose` 를 조건으로 쓰는 규칙이 하나도 없다**(`absolute_cap`·`stress_dsr` 둘 다
`when: {region_group: …}` 뿐). 실측:

```
purpose=live    max_purchase_krw = 1,026,560,000
purpose=invest  max_purchase_krw = 1,026,560,000   <- 같다
```

그런데 `routes.py:951` · `mapFilters.ts:23-26` · `purpose.ts` 가 **현재형**으로
*"목적에 따라 대출 절대한도·스트레스 가산이 달라 한도 자체가 달라진다"* 라고 단언한다.
지금은 **엔진이 받을 준비만 돼 있고 데이터가 없다.** 배선은 남기되(값이 싸고, 생기는 날
한 줄이면 된다) 문장을 *"달라질 수 있어 — 현재 세율 데이터에는 목적별 차등이 없다"* 로
정정할 것. `purpose.ts` 가 이미 "투자는 2차"라고 적어 둔 것과 같은 정직함을 세 곳에 맞춘다.

### 4. 계약 대조 파서 — **취약하다. 예시를 지우면 조용히 통과한다** → `CR37-2`

`firstJsonObjectAfter`(`apiContract.test.ts:70`)는 `jsonBlockAfter` 와 달리 **펜스로 범위를
묶지 않는다** — 마커 뒤부터 **문서 끝까지** 훑어 첫 `{` 를 찾는다. 한 펜스에 객체가 둘이면
앞 예시가 사라졌을 때 **뒤 예시를 대신 읽는다.**

| 변이 | 기대 | 실측 |
|---|---|---|
| **P-A** `// res 200 — zoom < 13 : 군집` 뒤 **군집 예시를 통째로 삭제**(예시 0개) | 잡혀야 | ❌ **17 passed — 조용히 통과.** 단지 예시를 군집으로 읽었고, 둘 다 `budget` 키가 같아 단언이 성립했다 |
| **P-B** 군집 예시의 `budget` 블록만 삭제(계약 후퇴) | 잡혀야 | ✅ 1건 FAIL |

CR-036 이 `jsonBlockAfter` 에 대해 검증한 **F6b(예시 0개 → 파일이 통째로 죽는다)** 가
새 파서에서는 성립하지 않는다. 지금 문서가 옳으므로 제품 결함은 아니다 — 다만
**"지키는 척만 하는 검사"** 의 정확한 형태이므로 비차단으로 남긴다.

**한 줄이면 닫힌다**: 판별자를 단언한다.

```ts
expect(cluster.level).toBe("cluster");
expect(complex.level).toBe("complex");
```

(더 나은 쪽은 `jsonBlockAfter` 처럼 펜스 끝(`fenceEnd`)으로 상한을 두는 것이다.)

### 5. CR-036 이월분

#### CR36-2 ✅ **해소 — 변이 2종 모두 죽는다**

`test_user_listing_wiring.py::test_자금계획이_API_경로에서도_추천카드와_같은_금액을_쓴다`.
monkeypatch 없이 리포지토리에 지수·지역코드를 넣고 HTTP 두 번으로만 확인한다.

| 변이 | 결과 |
|---|---|
| ① `InMemoryRepository.complex_region_code` 제거 | ✅ FAIL — `700,000,000(trade_band) != 703,571,428` |
| ② `InMemoryRepository.market_index` 제거 | ✅ FAIL — 금액은 같아지지만 `basis != time_adjusted_band` 에서 죽는다 |

**CR35-4 의 명제가 이제 API 경로에서 실제로 실행된다.** ②를 함께 단언한 판단이 정확하다 —
"양쪽 다 보정을 못 하면 값은 같아진다"는 함정을 스스로 막았다.

#### CR35-11 ✅ **해소 — 오타는 잡히고 급매는 안 잡힌다**

`POST /me/listings` 전 구간 실측(단지 실거래 9.2억 · 전용 59.5㎡ 8건):

| 입력 | ratio | `problems` |
|---|---|---|
| **3.0억**(9.2→3.0 오타) | 33% | ✅ *"…최근 실거래 기준가 919,999,999원의 33% 로 크게 낮습니다 — 금액 자릿수…"* |
| 9.2억(정상) | 100% | 없음 |
| **7.5억(진짜 급매 −18%)** | 82% | **없음 — 오탐 아님** |
| 5.6억(−39%) | 61% | 없음 (경계 안) |
| 5.4억(−41%) | 59% | ⚠️ 경고 (경계 밖) |
| 14.5억(+58%) | 158% | 없음 |
| 14.8억(+61%) | 161% | ⚠️ 경고 |

경계가 `BAND_WARN_LOW_RATIO 0.6` / `HIGH 1.6` 과 정확히 일치한다. **거절하지 않고**
`201` + 고지이며 문장이 *"실제로 급매이거나 특수한 조건이면 그대로 두셔도 됩니다"* 로 끝난다.
실거래가 없는 단지에서는 *"이 단지·전용 59.5㎡ 의 실거래와 대조하지 못했습니다
(이 단지의 실거래 자료가 없습니다)"* — **못 한 것을 못 했다고 말한다.** G2 준수.
비용도 확인했다: `_listing_reference` 는 POST·PATCH 에서만 1행 부른다(목록 GET 은 안 부른다 — N+1 없음).

> **CR37-8 (경)** 문구 하나. −41% 케이스에도 첫 제안이 *"금액 자릿수(억·만원)를 다시
> 확인해 주세요"* 다. 자릿수 실수는 10배 단위라 −41% 와 모양이 다르다 — 비율이 2배/0.5배
> 밖일 때만 자릿수를 말하고, 그 안쪽은 *"이 단지 최근 실거래와 크게 다릅니다"* 로 두는 편이
> 사용자에게 덜 헷갈린다.

#### CR36-4 ✅ **해소 — 리터럴 금지 검사가 실제로 죽인다**

| 변이 | 결과 |
|---|---|
| `base.py` 선언만 `limit: int = 200` 으로 되돌림(**값은 동일**) | ✅ FAIL — `assert literal is None` |

값이 같은 동안에도 죽는다는 점이 핵심이다(`signature` 비교만으로는 통과한다). 정확한 설계다.

#### CR36-1 ✅ **해소 — 배선 3곳이 모두 잡힌다**

| 변이 | tsc | 테스트 |
|---|---|---|
| `App.tsx` 의 `onAddListing={openListings}` 삭제 | 통과 | ✅ **1건 FAIL** — *"'이 단지 호가 입력'이 실제로 내 매물 화면을 연다 (CR36-1 · onAddListing)"* |
| `ListFilterBar` 의 `onBudgetOnlyChange` 배선 삭제 | ✅ **TS2741**(필수 prop 화) | 2건 FAIL |
| `RecommendPanel` 의 `onBudgetOnlyChange` 배선 삭제 | 통과 | ✅ **1건 FAIL** — *"AI 추천 탭의 예산 스위치가 실제로 목록을 바꾼다"* |

**`ComplexCard.onHover` 를 미조치로 둔 판단 — 동의한다.** 판정 근거를 적어 둔다:
이 prop 이 끊기면 잃는 것은 **마커 하이라이트**뿐이고, 화면이 **없는 사실을 있다고 말하게
되지 않는다**. `onAddListing`(서버 문구가 가리키는 길)·`onBudgetOnlyChange`(눌러도 무반응인
스위치)와는 성격이 다르다. 게다가 이 제품은 모바일 퍼스트라 hover 는 데스크톱 부가 기능이다.
→ 다만 그 **기준을 어딘가에 한 줄로 남길 것**: *"선택 prop 은 끊겼을 때 화면이 거짓을
말하거나 안내가 가리키는 길이 사라지면 필수로 올린다. 표시 보조는 선택으로 둔다."*
다음 사람이 매번 다시 판단하지 않게.

> **CR37-4 (경)** `RecommendPanel.tsx:269` 의 `onBudgetOnlyChange={onBudgetOnlyChange ?? (() => {})}`
> 는 이번에 고친 그 모양(**스위치가 뜨는데 눌러도 무반응**)을 **한 층 위에 다시 만든다.**
> `ListFilterBar` 는 필수로 올렸지만 `RecommendPanel.onBudgetOnlyChange?` 는 여전히 선택이고,
> 없으면 no-op 을 대신 넣는다. 지금 유일한 방어는 위 App 테스트 1건이다(타입은 침묵한다).
> App 이 **항상** 넘기고 있으므로 그냥 필수로 올리면 된다 — 정말 없을 수 있다면
> 스위치를 **그리지 않는** 쪽이 맞다(죽은 버튼 금지 규칙과 같다).

---

## 그 밖의 확인 (호평 포함)

* **★ SR32-1 로그 방어의 구조 역전 — 이번 라운드에서 가장 값진 수정.**
  `main.log_target` 이 `"/api/v1/map/complexes [q: bbox,budget,zoom]"` 처럼 **이름만** 남긴다.
  `SENSITIVE_PATHS` 라는 민감경로 목록을 없애고 **기본이 '지운다'** 로 뒤집었다 —
  사고의 원인(목록은 사람이 기억해야 하고 기억은 언젠가 빠진다)을 증상이 아니라 원인에서 끊었다.
  `AccessLogQueryFilter` 를 **핸들러가 아니라 로거에** 건 판단도 정확하다(uvicorn `dictConfig`
  가 핸들러를 갈아끼워도 필터가 살아남는다 — 주석에 근거까지 적혀 있다).
* **M14 그물 확인.** `AccessLogQueryFilter.filter` 의 `record.msg` 폴백 2줄을 지우니
  `test_인자가_뭉개진_레코드에서도_쿼리를_지운다` 가 죽는다. *"2중 그물이라 어떤 테스트에도
  안 걸렸다"* 를 스스로 신고하고 **그 층만 겨냥한 단위 테스트**를 짠 것이 옳다 —
  첫 그물이 살아 있는 한 서버 로그로는 영영 관측되지 않는 층이다.
* **`max_price_krw` → 400 `PARAM_REMOVED`.** 받아서 무시하지 않고 값을 되비치지도 않는다.
  `_resolve_map_budget` 이 실패해도 지도를 죽이지 않고 **왜 못 세웠는지**를 세 갈래
  (`_BUDGET_NO_PROFILE`/`_DECRYPT_FAILED`/`_UNAVAILABLE`)로 말하는 것도 옳다(빈 실패 금지).
* **군집 응답에도 `budget` 을 싣는 판단이 옳다** — 줌아웃했다고 조건이 사라진 것처럼 보이면
  사용자는 조건이 풀린 줄 안다. 다만 아래 CR37-6.
* **`mapFilterKey` 가 실효 금액까지 보는 것**(mapFilters.ts:171)은 이번 계약 변경이 만든
  함정("희망가를 9억→7억으로 바꿔도 쿼리는 글자 하나 안 바뀐다")을 **먼저 찾아 막은 것**이다.
  이 자리를 스스로 발견한 것이 이번 델타에서 가장 좋은 습관이다.

### CR37-6 (경) — `api-spec §4` 군집 예시가 코드와 다르다 (새 계약 테스트가 읽는 바로 그 블록)

| | 문서 예시 | 서버 실제(`routes.py:1023-1032`) | 클라이언트(`ClusterItem`) |
|---|---|---|---|
| `name` | **있다**(`"강남구"`) | 없다 | 없다 |
| `price_basis` | 없다 | **있다**(`latest_trade`) | 있다(옵셔널) |

`firstJsonObjectAfter` 가 이 예시를 파싱하지만 `budget` 키만 비교해 드리프트가 살아남았다.
**문서가 정본**이라고 선언해 둔 이상 문서가 틀린 것은 그냥 틀린 것이다. 예시를 코드에 맞추고,
가능하면 군집 항목도 `keys()` 로 대조 범위에 넣을 것(CR36-6 의 "무엇이 대조되는지" 문제와 같은 뿌리).

### CR37-7 (경 · 이월) — 예산 칩은 **켜도 꺼도 화면이 안 바뀐다**

`filterChips` 의 `budget` 칩(`active: f.budgetApplied`)을 꺼도:
* `listBudgetKrw = effectiveBudget(filters).krw` 는 `budgetApplied` 를 **보지 않는다**(App.tsx:219) → 배지·목록 판정 그대로,
* 리포지토리가 `max_price_krw` 로 거르지 않으므로 서버 결과도 그대로(`postgis.py:713` · `memory.py:189` — 의도된 설계),
* 남는 변화는 카나리아가 조용해지는 것뿐.

**이번 델타가 만든 것은 아니다**(직전 커밋에서도 같았다). 아래 "남은 판단거리"에서 함께 답한다.

---

## 남은 판단거리 답변 — `FilterRail` 예산 칩 라벨

**결론: 실제로 거르지 마라. 문구만 고치는 것도 부족하다 — 칩에 뜻을 붙여라.**

* **거르는 쪽은 반대한다.** 두 리포지토리가 예산으로 거르지 않는 것은 실수가 아니라 결정이고
  (`ux/README.md §4` — *"왜 후보에 없는지 보이게 한다"*), 그 결정이 옳다. 예산 초과 단지를
  지도에서 지우면 "얼마나 모자란가"라는 이 제품의 핵심 정보가 사라진다. 게다가 **거르는
  스위치는 이미 따로 있다** — `ListFilterBar` 의 `예산 내` 토글이고, 그건 숨긴 건수까지
  말한다. 같은 일을 두 곳에서 하면 반드시 어긋난다.
* **"기준"으로만 바꾸는 것도 부족하다.** CR37-7 대로 지금 칩은 **꺼도 아무 일이 안 일어난다.**
  문구만 정직해지고 스위치는 여전히 죽어 있으면, 방금 `onBudgetOnlyChange` 에서 고친
  "눌러도 무반응"이 여기 남는 셈이다.
* **권고(a안)**: 칩이 **초과 표시를 켜고 끄게** 만든다. `listBudgetKrw` 를 `budgetApplied` 로
  게이트해서 끄면 배지·초과 집계가 실제로 사라지게 하고, 라벨을 **"희망가 9.00억 초과 표시"**
  로 한다. 사용자가 그걸 끄고 싶어할 이유가 실재한다(온통 빨간 지도).
* 대안(b안): 칩을 없애고 `예산 내` 토글 하나로 모은다 — 어긋날 데가 사라지지만 "내 조건"
  레일에서 예산이 보이지 않아 발견성이 떨어진다.
* 대안(c안): 칩이 아니라 **끌 수 없는 라벨**로 바꾸고 *"희망가 9.00억 기준으로 초과 표시 중"*
  이라고 적는다 — 가장 싸지만 조작을 하나 잃는다.

어느 쪽이든 **"이하"는 쓰지 마라.** 거르지 않는 한 그 단어는 거짓이다.
그리고 두 갈래 문구(`희망가 … 이하` / `내 예산 … 기준`)가 지금 서로 다른 어법인 것도 함께 맞출 것.

---

## 판정 요약

**⛔ FAIL — 차단 1건.**

| ID | 내용 | 통과 조건 |
|---|---|---|
| **CR37-1** | 지도 예산(서버, `area 84.0`)과 화면 예산(선택 단지 면적)이 다른데 새 카나리아가 그 차이를 사고로 신고한다. 기본 경로에서 재현(conflicts=2). 주석·`api-spec` 의 "같은 상한" 문장이 거짓 | (A) 두 값을 같은 `PropertyFacts` 에서 만들거나 (B) 주장을 내리고 제품이 만든 차이에는 울지 않게 한다 — **어느 쪽이든 API 전 구간 회귀 테스트 1건**(85㎡ 초과 단지 · 희망가 미저장 · `conflicts === 0`) |

**차단하지 않은 것을 분명히 한다.** SR32-1 의 본론(금액이 URL 에서 사라졌는가)은 닫혔고,
로그 방어를 목록에서 기본 삭제로 뒤집은 것은 이 사고를 **원인에서** 없앤 수정이다.
CR-036 이월 4건은 전부 변이로 죽는 것을 확인했다. 나머지 지적 7건(CR37-2~8)은
*"제품이 지금 틀렸다"* 가 아니라 *"틀리게 되는 날 조용히 틀린다"* 이거나 문구·문서 문제다.

**차단은 오늘의 결과로만 정당화한다.** CR37-1 은 오늘 코드·오늘 세율로 재현했고
(1,026,560,000 vs 1,024,580,000 · conflicts 2), **기본값 경로**에서 사용자에게 문장이 뜨며,
문서가 사실이 아닌 것을 사실이라고 적고 있고, 이 명제를 밟는 테스트가 2,342건 중 0건이다.
이 라운드가 세운 기준("오탐도 결함" · "고쳤다고 보고한 것을 테스트가 밟아야 한다")을
그대로 적용하면 통과시킬 수 없다.

> 이번 라운드에서 가장 값진 것은 **방어의 구조를 뒤집은 것**이다 — 민감경로 목록을 지우고
> "기본이 지운다"로 바꾼 한 수가, 앞으로 생길 모든 엔드포인트에 대해 같은 사고를 미리 막는다.
> 증상을 고치지 않고 사고가 가능했던 **모양**을 없앤 수정은 드물다.
> 다음에 볼 자리도 같은 성격이다 — **CR37-1 은 "두 화면이 같은 숫자를 말한다"를 계약으로
> 적어 놓고 그 계약을 밟는 테스트를 안 둔 자리**이고, CR37-2·CR37-3 은 **그물이 있는 줄
> 알았는데 옆으로 빠져나가는 길이 있는** 자리다. 셋 다 "적어 둔 것을 실제로 재는가"다.

---

## CR-038 · 2026-07-29 · CR37-1 재검증(2라운드) · CR-037 지적 7건 · SR-033 동반 조치

**리뷰어** code-reviewer · **대상** `8bf21dd` 이후 미커밋 — 64파일 +10,152 / −591
**판정 ⛔ FAIL** — 차단 **1건**(`CR38-1`). 나머지는 비차단.

> 요약: **서버 쪽 CR37-1 은 제대로 닫혔다.** 항목마다 그 항목 거래의 면적으로 상한을
> 세우고, 면적을 모르면 84 를 가정하지 않고 `null` 로 둔다 — 변이(고정 84 로 되돌림)에
> 파리티 테스트 5건이 죽는다. `api-spec §4` 도 "상한은 하나의 숫자가 아니다"로 정직하게
> 고쳐졌다. CR37-2·3·4·6, SR33-1·4 도 전부 변이로 죽는 것을 확인했다.
>
> 그런데 **화면은 고치지 않았고, 그래서 카나리아가 아직 운다.** 두 담당자가 갈린
> 지점을 직접 재현했다 — **면적이 섞인 bbox 에서 `conflicts = 2`.** 프론트 담당자가
> 옳다. 백엔드 담당자의 *"서버가 항목별로 정확하므로 프론트는 지금 형태를 유지하는
> 쪽을 권한다"* 는 **틀렸다**: 서버가 항목별로 정확해질수록, 한 숫자로 판정하는 화면과
> **더 자주** 갈린다.

---

### 실행 검증 (전부 직접 돌림 · 주장과 대조)

| 항목 | 주장 | 실측 | 결과 |
|---|---|---|---|
| 백엔드 | 1,444 passed / 103 skipped / 0 failed | junitxml `tests=1547 skipped=103 failures=0 errors=0` → **1,444 passed** | ✅ 일치 |
| 프론트 | 949 passed / 48 files | `Test Files 48 passed · Tests 949 passed` | ✅ 일치 |
| 빌드·타입 | — | `tsc --noEmit` **exit 0** · `vite build` exit 0 (298.27 kB) | ✅ |
| 변경 규모 | — | `git diff --stat` **64 files · +10,152 / −591** | ✅ |
| DB 여유 | — | 물리 메모리 여유 5.6GB / 16GB · 로컬 DB 미기동(needs_db 103 skip) | ✅ 안전 |

리뷰 중 소스에 변이 9종을 넣었다 되돌렸다(M1·M2·M3·M4·D1·D2·G1·S1 + 임시 테스트 1).
종료 시점 `git diff --stat` 동일(64 files · +10,152 / −591) · 잔여 마커 0 · 양 스위트 재실행 그린.
운영 서버는 **건드리지 않았다**(reload·재배포 없음).

---

## ⛔ CR38-1 (차단 · 중대) — 서버는 항목별, 화면은 **한 숫자**. 면적이 섞이면 다시 갈린다

**파일** `frontend/src/App.tsx:177,225-226,264,285,574-578` ·
`frontend/src/lib/mapFilters.ts:97-99` · `frontend/src/lib/budgetStatus.ts:173-200` ·
`backend/tests/test_map_budget_parity.py:203,218-240`

### 재현 (운영 세율 · 현금 5억 · 연소득 1억 · 무주택 · 희망가 미저장 · `budget=mine`)

면적이 섞인 bbox 를 만들었다. 가격은 두 상한 사이(1,025,570,000) 한 값으로 맞추고
면적만 59.9 / 84.0 / 114.5 / 120.0 으로 흩었다 — 실제 수도권 지도의 정상적인 모습이다.

```
한도  84.0㎡ = 1,026,560,000
한도 114.5㎡ = 1,024,580,000        (차이 1,980,000 · 농특세 0.2%)
서버 budget 블록: {'applied': True, 'basis': 'max_purchase', 'reason': None}

--- ① 114.5㎡ 단지를 선택: 화면 budgetKrw = 1,024,580,000
      면적            가격    서버   화면
      59.9  1,025,570,000  False   True  <== 갈림
      84.0  1,025,570,000  False   True  <== 갈림
     114.5  1,025,570,000   True   True
     120.0  1,025,570,000   True   True
   => conflicts = 2

--- ② 59.9㎡ 단지를 선택: 화면 budgetKrw = 1,026,560,000
     114.5  1,025,570,000   True  False  <== 갈림
     120.0  1,025,570,000   True  False  <== 갈림
   => conflicts = 2

--- ③ 단지 미선택(기본 진입 · area_m2 없음 → 서버 기본 84.0): 화면 = 1,026,560,000
     114.5  1,025,570,000   True  False  <== 갈림
     120.0  1,025,570,000   True  False  <== 갈림
   => conflicts = 2
```

**세 상태 전부 갈린다.** 특히 ③은 **로그인 직후 지도를 처음 여는 기본 경로**다
(`budgetApplied` 기본 `true` · `planComplex` 없음). 그러면 `App.tsx:574` 의 `role="status"`
문장이 그대로 뜬다 — 아무것도 고장나지 않았는데.

### 왜 백엔드 재현은 `conflicts=0` 이었나 — **단일 면적 지도였다**

`test_map_budget_parity.py:203`:

```python
_seed(client.repo, [(i, p, LARGE_AREA) for i, p in enumerate(prices, start=1)])
```

**모든 단지를 같은 면적(114.5㎡)으로** 깐다. 그러면 화면의 한 숫자와 서버의 항목별
숫자가 우연히 전부 같아져 `conflicts=0` 이 나온다. 그런데 이 수정의 **존재 이유**가
*"지도는 34㎡ 와 120㎡ 를 한 화면에 담는다"* 였다 — 검사는 그 전제를 스스로 빼고 돈다.

바로 아래 `test_지도_판정은_항목마다_그_단지_면적의_한도와_비교한다`(218행)는 면적을
섞어 깔지만 **`_check_verdicts` 를 부르지 않는다.** 부르면 죽는다(위 재현 ①과 같은 배치).
즉 *"섞인 지도"* 와 *"카나리아"* 가 같은 테스트에서 만나는 자리가 한 곳도 없다.
CR-037 이 지적한 것과 같은 형태다 — **명제를 밟는 테스트가 0건**.

### 카나리아가 오늘 잡을 수 있는 것은 **오탐뿐이다**

`checkVerdicts` 가 세는 것은 "같은 기준(basis)인데 금액이 다르다"이다. 그 상태가 생길
수 있는 길을 전부 짚었다:

| basis | 서버 | 화면 | 갈릴 수 있나 |
|---|---|---|---|
| `target_price` | 저장된 `prefer.target_price_krw` | 같은 저장값(`readTargetPrice`) | 클라이언트 캐시 경합 외엔 없음 |
| `max_purchase` | `f(항목 면적)` | `f(선택 단지 면적)` 또는 `f(84)` | **면적 구간 차이 — 제품이 만든다** |
| 기준이 다름 | — | — | `budgetStatusView.basisMismatch` 가 **이미** 잡는다(`budgetStatus.ts:142-154`) |

즉 카나리아가 원래 잡으려던 진짜 신호(*"저장한 희망가가 서버에 안 닿았다"*)는
`basisMismatch` 가 사유 문장까지 붙여 이미 처리한다. 카나리아에 남은 **체계적** 발화
사유는 면적 구간 차이 하나이고, 그건 사용자가 손댈 수 없다. **이 라운드의 기준
("오탐도 결함")에 정면으로 걸린다.**

### 카나리아 이전에 — **배지 자체가 틀린다**

이게 더 무겁다. `App.tsx:264` 는 `applyScreenBudget(map.items, listBudgetKrw)` 로
**모든 항목을 한 숫자로** 판정하고, 그 값이 카드 배지·마커 색·`예산 내` 토글의 숨김
건수까지 간다(`App.tsx:229-245`). 재현 ③에서 120㎡ 단지의 배지는 **84㎡ 의 한도**로
서 있다. 같은 단지를 눌러 자금계획을 열면 서버는 "예산 안"이라고 답한다 —
카나리아를 지워도 이 어긋남은 남는다.

### 완화되는 조건 (정직하게 적어 둔다)

* 사용자가 **85㎡ 를 가로지르지 않는 면적 조건**을 걸어 두면 안 난다. `_BBOX_SQL` 의
  LATERAL 이 조건 안에서 최근 1건을 고르므로(`postgis.py:630-645`) 지도의
  `price_area_m2` 가 전부 한 세율 구간에 들어간다. `api-spec §4`(532-535행)에 적힌 그대로다.
* 갈리는 가격 구간은 **1,980,000원 폭**(≈0.19%)이다. 넓지 않다.

그래도 차단으로 두는 이유: ① 기본 상태(면적 조건 없음 · 단지 미선택)에서 난다,
② 조건을 `59~114㎡` 처럼 걸면(흔하다) 그대로 난다, ③ 좁은 구간이라도 **판정 경계**라
사용자가 가장 신경 쓰는 자리다, ④ **CR-037 이 이미 한 번 차단한 사안이고 "conflicts=0"
으로 해소 보고됐다** — 그 근거가 단일 면적 지도였다.

### 어느 쪽을 고쳐야 하나 — **화면이 판정을 두 벌 갖는 구조를 없앤다**

두 안 다 성립한다. **(B) 를 권한다.**

* **(A) 화면이 항목별로 판정한다** — 서버가 `budget` 블록에 **구간별 상한**을 실어 준다
  (예: `caps: [{area_max_m2: 85.0, krw: …}, {area_min_m2: 85.0, krw: …}]`). 화면이 항목
  면적으로 골라 쓰면 배지도 맞고 conflicts 는 **구조적으로** 0 이 된다.
  · 비용: 금액이 응답 **본문**에 실린다. `/affordability` 가 이미 같은 성격의 금액을
    본문으로 주고 화면이 메모리에 들고 있으므로 한계 노출 증가는 사실상 없지만,
    SR32-1 최소 노출 원칙에 닿으므로 **security-reviewer 확인이 필요하다.**
  · 남는 문제: 판정 규칙이 여전히 두 벌이다 — 다음에 또 갈라질 자리가 남는다.
* **(B) 지도·목록 배지는 서버 `over_budget` 을 그대로 쓴다** — 화면 자체 판정은 서버가
  침묵하는 자리(추천 패널)에만 남긴다. 비교할 두 벌이 없어지므로 `checkVerdicts` ·
  `verdictConflictNotice` 는 **지운다**(진짜 신호는 `basisMismatch` 가 계속 잡는다).
  · `budgetStatus.ts` 머리말의 근거 ②③을 다시 써야 한다. ②(*"서버 판정은 지도 응답에만
    있다"*)는 목록이 `map.items` 를 그대로 쓰므로(`App.tsx:210-213`) 지도·목록에는 해당하지
    않는다. ③(*"되짚을 수 없다"*)은 사실이지만, **되짚을 수 있으나 틀린 숫자**보다
    **불투명하지만 맞는 숫자**가 낫다.
  · `예산 내` 토글의 숨김 건수도 `over_budget` 기준으로 세야 한다(면적 미상 `null` 은
    "숨기지 않음"으로 — 모르는 것을 초과로 취급하지 않는다).

### 통과 조건 (둘 중 하나 + 회귀 테스트)

**회귀 테스트는 반드시 면적이 섞인 bbox 여야 한다.** 다음 세 상태 전부에서
`conflicts === 0`(또는 항목별 화면 판정 == 서버 판정)을 단언할 것:

1. 단지 미선택(면적 없이 `/affordability` 호출) — **기본 진입 경로**
2. 85㎡ **이하** 단지 선택
3. 85㎡ **초과** 단지 선택

지도에는 85㎡ 를 가로지르는 면적 최소 2종을 깔고, 가격은 두 상한 **사이**를 포함할 것.
지금 `test_map_budget_parity.py:188` 은 1·2 를 밟지 않고 3 도 단일 면적으로만 밟는다.

---

## 해소 확인 — CR-037 지적분 (전부 변이로 검증)

### CR37-1 서버측 ✅ **해소** — 항목별 판정이 진짜다

| 변이 | 결과 |
|---|---|
| **M1** `_item_over_budget` 을 `budget_at(84.0)` 고정으로 되돌림 | ✅ `test_map_budget_parity.py` **5건 FAIL** |

`test_이_테스트가_밟는_경계가_실재한다`(166행)를 **맨 앞에** 둔 판단이 정확하다 —
픽스처 세율로는 두 구간 세율이 같아 이 파일 전체가 빈 검사가 되는데, 그 사실이
조용히 묻히지 않도록 **경계의 실재부터 단언**한다. 여기서만 운영 세율을 쓰는 이유를
머리말에 적어 둔 것도 옳다.

`_profile_budget` 의 구간 캐시(`acquisition_area_class`)도 테스트가 지킨다 —
면적 40종을 85㎡ 가로질러 깔고 `compute_affordability` 호출이 **2회**인지 센다
(`min(calls) <= 85 < max(calls)` 로 "한쪽에 몰려 공짜 통과"까지 막았다). 좋은 설계다.

`api-spec §4`(499-537행)도 *"상한은 하나의 숫자가 아니다"* 로 정직하게 다시 썼다 —
CR-037 이 "거짓"이라고 지적한 문장은 사라졌다. 면적 조건이 자동 반영되는 이유를
`_BBOX_SQL` 의 LATERAL 로 설명한 대목(532-535행)은 실제 SQL 과 일치한다(확인함).

### CR37-2 파서 ✅ **해소** — 내가 뚫었던 길이 막혔고, 새 길도 못 찾았다

| 변이 | 결과 |
|---|---|
| **P-A**(CR-037 에서 통과했던 그 우회) 군집 예시 통째 삭제 | ✅ **죽는다** — `SpecParseError` |
| **P-C**(신규) 예시 삭제 + 옆 마커 줄까지 삭제해 옆 예시를 끌어올림 | ✅ **죽는다** |
| **P-D**(신규) 예시를 빈 껍데기로 교체 | ✅ **죽는다** |

원인 진단이 정확했다 — *"주석을 먼저 걷어내면 옆 예시의 `{` 가 바로 다음 줄로 올라온다"*.
그래서 `blankCommentLines` 가 **줄 수를 유지한 채 비우고**, 시작 위치 판정은
**주석을 걷어내기 전의 원문**으로 한다(`specParser.ts:126`). 증상이 아니라 원인을 고쳤다.

`expect` 대신 **throw** 로 바꾼 판단이 이 수정의 핵심이다 — 그래야
`expect(() => …).toThrow()` 로 **검사를 검사**할 수 있고, `specParser.test.ts` 가
실제 `api-spec.md` 의 메모리 사본을 변이시켜 매 실행마다 다시 확인한다.
"죽는 이유"까지 `toThrow(/시작하지 않는다/)` 로 못박은 것도 옳다(우연히 죽는 것과 구분).

### CR37-3 관문 ✅ **해소(자연스러운 우회는 죽는다)** · ⚠️ 3중 우회는 여전히 통과 → `CR38-2`

| 변이 | tsc | 테스트 |
|---|---|---|
| **M2** `applyScreenBudget` 를 인라인으로 대체(CR-037 의 그 우회) | ✅ **TS2322 — Property '[SCREEN_BUDGET]' is missing** | (돌리기 전에 죽는다) |
| **M3** 위 + `as unknown as ScreenComplexItem[]` 캐스트 | exit 0 | ✅ `apiContract.test.ts` **3건 FAIL** |

**브랜드를 캐스트로 뚫으면 어떻게 되나** — tsc 는 통과하지만 세 단언이 죽는다:
`만드는 파일은 lib/screenBudget.ts 하나뿐이다` · `그 값은 verdictToOverBudget( 로만 만든다` ·
`타입 관문도 살아 있다`. **"셋 중 하나만 뚫어서는 통과하지 못한다"는 주장은 참이다.**
CR-037 이 실측한 우회(인라인 + 안 쓰는 import 정리 → tsc exit 0 · 918 passed)는 **죽었다.**

> **CR38-2 (경)** 다만 셋을 **동시에** 우회하면 통과한다. 실측:
> ① `as unknown as ScreenComplexItem[]` 캐스트, ② 키를 상수로 빼서
> `[OB_KEY]: …`(전수 검사 정규식 `/over_budget:\s*/` 이 안 걸린다), ③ 주석에
> `applyScreenBudget(` 를 남김 → **tsc exit 0 · 949 passed · apiContract 22 passed.**
> 이건 실수로 도달하는 모양이 아니라 **일부러 세 겹을 벗기는** 모양이라 차단하지 않는다.
> 관문의 목적(자연스러운 인라인 차단)은 달성됐다. 굳이 더 닫는다면 `over_budget` 키를
> 만드는 자리를 정규식이 아니라 **AST/타입**으로 세거나, `ComplexItem` 의 `over_budget`
> 을 `readonly` 로 두고 `applyScreenBudget` 만 `Omit`+재조립하게 하는 쪽이다.

### CR37-4 칩 라벨 ✅ **해소 — 실제로 5가지가 달라진다**

`App.test.tsx:1006-1143` 이 **DOM 으로** 고정한다. 칩을 끄면:
① 카드 배지 `예산 초과` 사라짐 ② 마커 클래스 `map-pill--over` 사라짐
③ 마커 `aria-label` 에서 `예산 초과` 사라짐 ④ *"예산 초과 표시를 꺼 두었습니다"* 문장이
뜸(`내 예산을 아직 계산하지 못해` 와 **구분**한다 — 껐다와 못 했다는 다른 사실이다)
⑤ `예산 내` 토글이 `disabled` + `aria-describedby` 로 사유가 붙음.
그리고 **단지는 그대로 보인다**(거르지 않는다) · **다시 켜면 되돌아온다**.

**`예산 내` 토글과 역할이 구분되는가 — 그렇다.** 칩 = 표시할지 / 토글 = 숨길지.
토글을 켜면 칩은 켜진 채로 초과분이 사라지고 *"예산 초과 1건 숨김"* 을 말한다
(`App.test.tsx:1132-1143`). 표시를 끄면 숨길 근거가 없어지므로 토글이 잠기는 것도 정합적이다.
라벨은 `내 예산 8.50억 초과 표시` / `희망가 9.00억 초과 표시` — **두 갈래가 같은 어법**이다.

**AI 추천 조건 문구가 `이하` 를 유지한 것 — 옳다.** 추천은 실제로 거른다:
후보 조회가 `max_price_krw` 로 좁히고 `price > budget` 을 **하드 제외**한다
(`agents/recommend.py:264-271`). 거르는 곳은 `이하`, 표시만 하는 곳은 `초과 표시` —
**같은 단어를 쓰지 않는 것이 정확하다.** 하는 일이 다르기 때문이다.

> **CR38-3 (경)** `recommendConditions.ts:121,127` 은 아직 `희망가 … 이하` / `내 예산 … 이내`
> 로 **어법이 갈린다**. 지도 칩은 맞췄으니 여기도 한쪽으로 모을 것(둘 다 거르는 일을 한다).

### CR37-5 `purpose` 주석 ⚠️ **부분 해소** → `CR38-4`

**테스트는 훌륭하다.** `test_tax_rules_real.py:195-218` 이 두 겹으로 못박는다 —
① `purpose` 를 `when` 으로 쓰는 규칙이 0개인가 ② 그 **결과**로 `live == invest` 인가.
①만 두면 배선 누락을 못 보고 ②만 두면 규칙 추가를 늦게 안다. 실패 메시지가
*"고칠 것은 이 테스트가 아니라 저 문장들"* 이라고 **고칠 자리 목록까지** 적어 둔 것이 특히 좋다.

백엔드 문장도 고쳐졌다(`routes.py:1044-1048` · `affordability/models.py:55-58` —
*"그때까지 '목적에 따라 한도가 달라진다'고 적지 않는다"*).

**그런데 프론트는 한 곳도 안 고쳤다.** 여전히 현재형으로 단언한다:

| 파일:라인 | 문장 |
|---|---|
| `frontend/src/lib/purpose.ts:6` | "목적에 따라 **대출 절대한도·스트레스 가산이 달라 한도 자체가 달라진다.**" |
| `frontend/src/lib/mapFilters.ts:25` | "…달라 **한도 자체가 다르기 때문**이다." |
| `frontend/src/App.tsx:85` | "…달라 한도 자체가 달라진다." |
| `frontend/src/api/client.ts:42, 1162` | 같은 문장 2회 |
| `frontend/src/test/urlPrivacy.test.tsx:287` | "…절대한도·스트레스 가산이 다르다." |

CR-037 이 **콕 집어 이름을 댄** `mapFilters.ts`·`purpose.ts` 가 그대로 남아 있다.
조치 보고(*"주석을 사실로 고치고"*)와 코드가 어긋난다. 비차단이지만, 이 저장소가
반복해서 지켜 온 *"있는 척하지 않는다"* 에 걸리는 자리다 — 위 표의 6곳을
*"달라질 수 있다 — 현재 세율 데이터에는 목적별 차등이 없다(`test_tax_rules_real.py` 참조)"*
로 맞출 것.

### CR37-6 문서↔실제 응답 ✅ **해소 — 양방향 그물이 실제로 작동한다**

| 변이 | 결과 |
|---|---|
| **D1** `api-spec §4` 군집 예시에 **문서에만 있는 키** 추가 | ✅ `test_문서의_군집_예시_키가_실제_응답과_같다` FAIL |
| **D2** 서버 군집 응답에 **문서에 없는 키** 추가 | ✅ 같은 테스트 FAIL |

*"프론트 계약 테스트는 문서를 정본으로 목을 대조하므로, 문서가 틀리면 프론트는 틀린
계약을 충실히 지키고 아무도 못 본다"* — 진단이 정확했고, 백엔드가 문서를 읽어 실제
응답과 대조하는 것으로 고리가 닫혔다. `test_문서에서_예시를_지우면_이_검사가_죽는다`(442행)로
**빈 검사 금지**까지 스스로 막았고, 파일을 훼손하지 않고 메모리 사본으로 때리는 판단
(프론트가 같은 파일을 동시에 읽는다)도 정확하다.

### SR33-1 `mask_sensitive` ✅ **해소**

| 변이 | 결과 |
|---|---|
| **S1** 문자열 분기 제거(= 옛 동작: 문자열을 그대로 반환) | ✅ `test_security.py` FAIL |

*"아무 일도 안 한다"와 "가렸다"가 겉보기에 같으면 다음 사람도 같은 실수를 한다* —
그래서 **가리지 못하는 입력은 통째로 가린다**(`security.py:390-422`). 방향이 옳다.
중첩 문자열은 그대로 두고 통째 문자열만 가리는 **구분의 근거를 자리로 설명**한 것도
정확하다(구조 안의 값은 키로 판정할 수 있고, 통째로 온 문자열은 판정할 수 없다).
문서 문자열에 대체수단(`log_target`)이 적혀 있는지까지 테스트가 본다(793행) — 좋다.

### SR33-4 `guard_site` ✅ **해소 — 새 블록이 생겨도 잡는다**

| 변이 | 결과 |
|---|---|
| **G1** `DEPLOY.md` 끝에 **가드 없이** `sed → /etc/nginx → nginx -t && reload` 하는 새 절 추가 | ✅ `test_설정을_설치하는_모든_블록이_가드를_거쳐_reload_한다` FAIL |

검사가 "알려진 3개 블록"을 세는 게 아니라 **`<APP_ROOT>` 치환 + sed + /etc/nginx 조건에
맞는 블록을 모아 전수로** 보므로, 새 블록이 생겨도 자동으로 대상이 된다. 이게 핵심이다.
`guard_site` 자체도 세 함정(치환 누락 · index.html 부재 · root 경로 부재)을 각각
`return 1` 로 끊고 호출부가 `&&` 로 묶는다 — 예전 `grep … && echo "진행 금지"` 는
**중단하지 않는 가드**였다는 진단이 정확하다.

> **CR38-5 (경·사소)** `DEPLOY.md:630` 의 root 경로 순회가 `for d in $(grep … | awk …)`
> 라 공백이 든 경로에서 단어 분리된다. nginx root 에 공백은 드물지만
> `while IFS= read -r` 로 바꾸면 공짜로 정확해진다.

---

## 그 밖의 확인

* **★ `_profile_budget` 의 캐시 설계가 좋다.** 면적마다 이분탐색을 새로 돌리는 대신
  `acquisition_area_class` 로 묶어 운영 세율에서 2회로 끝낸다. 그리고 **캐시를 요청
  안에서만 살게** 한 판단이 정확하다 — *"사용자 자산에서 나온 금액이라 프로세스 전역에
  남기지 않는다"*(`routes.py:906-910`). 성능 최적화가 보안 원칙을 깨지 않게 먼저 막았다.
* **`_over_budget` 의 3값 유지.** 예산 미상·가격 미상을 `false` 로 접지 않는다.
  그리고 ①(희망가) 기준일 때는 면적 미상도 판정한다 — *"금액 하나라 면적과 무관하다"*.
  두 기준의 성질 차이를 정확히 구분했고 테스트가 양쪽을 따로 밟는다(284행).
* **`test_map_budget_parity.py` 의 `_seed` 규약.** *"운영 PostGIS 는 가격·기준일·면적을
  한 거래 행에서 가져오므로 면적이 없으면 금액도 없다"* 를 픽스처가 지킨다 — 실물과
  다른 조합을 만들어 놓고 통과하는 테스트를 미리 막았다.

---

## 판정 요약

**⛔ FAIL — 차단 1건.**

| ID | 내용 | 통과 조건 |
|---|---|---|
| **CR38-1** | 서버는 항목별 면적으로 판정하는데 화면은 **한 숫자**(선택 단지 면적, 없으면 84)로 판정한다. 면적이 섞인 bbox 에서 `conflicts=2` 재현(단지 미선택 기본 경로 포함). 카나리아 오탐 이전에 **배지·마커·숨김 건수 자체가 틀린다** | (A) 화면이 항목별로 판정하게 하거나 (B) 지도·목록 배지를 서버 `over_budget` 으로 통일하고 카나리아를 지운다 — 어느 쪽이든 **면적이 섞인 bbox** 회귀 테스트(단지 미선택 · 85㎡ 이하 선택 · 85㎡ 초과 선택 3상태) |

**차단하지 않은 것을 분명히 한다.** CR37-1 의 **서버 절반은 제대로 닫혔다** — 항목별
판정도, 면적 미상 시 `null` 도, 구간 캐시도, `api-spec` 정정도 전부 결과로 확인했다.
CR37-2·3·4·6 과 SR33-1·4 는 **전부 변이로 죽는 것**을 봤다. 특히 CR37-2 는 원인
진단(주석 제거가 줄 위치를 밀었다)이 정확했고, 파서를 `throw` 로 바꿔 **검사를 검사할
수 있게** 만든 것이 이번 델타에서 가장 좋은 수정이다.

**차단은 오늘의 결과로만 정당화한다.** CR38-1 은 오늘 코드·오늘 세율로 세 가지 선택
상태 전부에서 재현했고(`conflicts=2`), **기본 진입 경로**가 포함되며, 그 명제를 밟는
테스트가 1,444 + 949 중 0건이다. 그리고 이 사안은 **CR-037 이 이미 차단했고
`conflicts=0` 으로 해소 보고된 건**이다 — 그 근거가 단일 면적 지도였다는 사실이
확인된 이상, 같은 기준으로 통과시킬 수 없다.

> 두 담당자가 갈린 지점에 대한 판정: **프론트가 옳다.** 그리고 백엔드의 권고가 틀린
> 이유는 미묘하다 — *"서버가 이미 항목별로 정확하다"* 는 **참이지만**, 그 정확도가
> 곧 화면과의 거리다. 서버를 정밀하게 만들수록 한 숫자로 판정하는 화면과 **더 자주**
> 갈린다. 정확해진 쪽이 있으면 나머지 한쪽도 같이 옮겨야 하고, 그러지 않으면
> "두 벌의 진실"은 사라지지 않고 **더 자주 드러날 뿐**이다.
>
> 다음 라운드에서 볼 자리는 하나다 — **면적이 섞인 지도에서, 화면이 보여주는 배지가
> 그 단지의 자금계획과 같은 말을 하는가.** 카나리아는 그 다음 문제다.

---

## CR-039 · 2026-07-29 · CR38-1 재검증(3라운드) — 화면 판정 폐기·서버 통일 · SR34-1 파생 위험

**판정: PASS** (차단 0건 · 비차단 5건)

### 0. 실행 검증 — 주장 수치 **전부 실측 일치**

```
backend   pytest (junitxml)  tests=1558 failures=0 errors=0 skipped=103  ->  1,455 passed
frontend  npm test           Test Files 48 passed · Tests 951 passed
frontend  tsc --noEmit       exit 0
frontend  npm run build      exit 0 (dist/assets/index-gGSz7oKZ.js 297.75 kB)
git diff --stat              64 files changed
```

델타 backend **+11** · frontend **+2** — 주장과 일치.
운영 서버 **미접촉**(SSH·reload·재배포 없음). `guard_site` 는 **로컬 격리 샌드박스**에서 실행했다.

※ `git diff --stat` 총계가 리뷰 도중 늘어난 것은 **security-reviewer 가 같은 시각 SR-035 를
기록**했기 때문이다(`security-review-log.md` 15:22 · `.review-state.json` 15:23). 소스 델타 아님.

---

### 1. 차단 CR38-1 — **해소.** 리뷰어가 직접 재현했다

프로젝트 테스트에 기대지 않고 **CR-038 에서 쓴 계산을 그대로 다시 돌렸다**
(운영 세율 · 현금 5억 · 연소득 1억 · 희망가 미저장 · 면적 7종 x 가격 3구간 + 면적 미상 = 22항목).

```
운영 세율 실측: 85m2이하 한도 1,026,560,000 · 85m2초과 1,024,580,000 (차이 1,980,000)
지도 항목 22건 · 면적 [34, 59.9, 84, 85.00, 85.01, 114.5, 120, None] · 서버 판정 {True, False, None}
```

| 화면 상태 | 옛 화면(한 숫자) | **새 화면(서버 릴레이)** |
|---|:--:|:--:|
| ① 단지 미선택(기본 진입 · 서버 기본 84㎡) | conflicts=**3** (단지 14·17·20) | **0** |
| ② 85㎡ 이하 단지 선택 | conflicts=**3** (단지 14·17·20) | **0** |
| ③ 85㎡ 초과 단지 선택(114.5㎡) | conflicts=**4** (단지 2·5·8·11) | **0** |

표시 스위치 OFF -> 전 항목 `null`(**`false` 로 접히지 않는다**).
CR-038 이 요구한 통과 조건(면적 섞인 bbox · 3상태 전부)을 **결과로 충족**한다.
권고 (B)를 택한 것도 옳다 — 화면은 면적별 상한을 알 수 없고(금액 미전송, SR32-1),
알게 만드는 순간 SR32-1 이 되돌아온다.

#### 1-1. 프론트가 되짚은 근거 3건 — **검증 결과 프론트가 옳다**

| 근거 | 리뷰어 판정 | 근거 |
|---|---|---|
| ① *"화면이 보여주는 숫자로"* -> 이제 서버를 가리킨다 | **성립** | 서버도 카드에 찍히는 `recent_price_krw` 로, 같은 방향(`price > cap`)으로 판정한다(`backend/app/api/routes.py:971-990`). 다른 건 상한뿐이고 그건 면적의 함수다 |
| ② *"판정 자리가 지도만이 아니다"* -> 범위 축소 | **성립** | `frontend/src/App.tsx:241-274` — 마커·카드·`예산 내` 토글이 **같은 `map.items`** 를 쓴다. 남는 자리는 추천 패널 하나 |
| ③ *"되짚을 수 없다"* -> 값을 정한다 | **성립** | 되짚기의 알맹이(`budget.basis`)는 오고 `budgetStatus.basisMismatch` 가 사유 문장까지 붙인다. 카나리아가 잡던 사실(희망가 미반영)은 그쪽에 남았고, **사용자가 손댈 수 없는 이유(면적 구간)로는 더 이상 울지 않는다** |

#### 1-2. *"같은 화면의 두 목록이 다른 말"* 이 되는가 — **안 된다**

추천 패널만 화면 판정(`budgetVerdict(est_price_krw, ...)`)을 남겼다. 프론트 논증을 실물로 확인했다:

* **추천 카드에 예산 배지가 없다** — `ReportCard` Props(`frontend/src/components/ReportCard.tsx:33-53`)는
  `item·tags·unknownTags·llmActive·onShowOnMap·onAddListing` 뿐, budget prop 자체가 없고
  파일 전체에 `over_budget`·`예산 초과` 문자열이 **0건**. 판정은 `예산 내` 토글 집계에만 쓰인다.
* **한 화면에 같이 서지 않는다** — `App.tsx:558`(`tab === "map"` -> ListFilterBar) 과
  `App.tsx:666`(`tab === "advice"` -> RecommendPanel)은 **배타적 탭**이다.
* **애초에 다른 금액** — 지도는 최근 체결 1건, 추천은 창 중위를 기준월로 환산한 추정가(CR35-4).

-> 논증 성립. 다만 잔여 위험은 남았고 CR39-2 로 이월한다(§4).

---

### 2. 관문 ㉡ 은 우회 가능한가 — **구조 검사만으로는 가능. 다만 3중 방어가 잡는다**

`frontend/src/test/apiContract.test.ts` 의 ㉡(`budgetVerdict(`·`recent_price_krw`·`budgetKrw` 부재
+ `item.over_budget ?? null` 존재)을 실제로 뚫어 보았다.
모든 변이는 검증 후 원복했고 최종 스위트 그린을 재확인했다.

| 변이 | tsc | 죽는 검사 |
|---|:--:|---|
| **F-M1** `?? null` -> `?? false` (조용한 접힘) | exit 0 | **4건** — apiContract ㉡ · screenBudget 2 · App.test "null 이면 배지가 없다" |
| **F-M2** `relayServerVerdict` 를 금액 판정으로 되돌림 | exit 0 | **9건** |
| **F-M3** `App.tsx` 목록 판정을 `budgetVerdict(price, 한 숫자)` 로 되돌림 | **TS6133** | **6건** — 3상태 ①②③ · 토글 집계 · 마커 2건 |
| **F-M4a** `App.tsx` 에서 자연스럽게 인라인 생성 | **TS2322** (`[SCREEN_BUDGET]` 누락) | — |
| **F-M4b** `as unknown as ScreenComplexItem[]` 캐스트로 타입 관문 우회 | exit 0 | **4건** — apiContract 3 + App.test 1 |
| **F-M5** 판정을 **별도 파일**로 옮기고 `(item.over_budget ?? null) ?? guess(item)` 로 리터럴만 남김 | exit 0 | **3건** — screenBudget.test 2 · App.test 1 (**apiContract 는 통과**) |

**결론**: 구조 관문(③)은 F-M5 처럼 *리터럴을 남기고 판정을 외부 모듈로 빼는* 형태로 우회된다
(CR38-2 와 같은 성질 — 고의적 형태). 그러나 **단위·화면 테스트가 잡는다.**
CR38-2 시점(3중 동시 우회가 **완전 통과**)보다 방어가 실제로 강해졌다.

**부작용 처리도 전부 회귀에 묶여 있다**(변이로 확인):

| 변이 | 죽는 검사 |
|---|---|
| **F-M6** `예산 내` 토글의 `disabled` 제거 | 4건 (App.test 2 · ListFilterBar.test 2) |
| **F-M7** `applied:false` 안내에서 *"초과 표시가 뜨지 않습니다"* 꼬리 제거 | 3건 |
| **F-M8** `budgetNotice` 의 "예산 판정 불가 N건" 집계 제거 | 1건 |

-> *"왜 배지가 없지?"* 에 대한 답은 **세 경로 모두** 화면에 있다:
서버가 못 세움 -> `applied:false` 사유 + *"초과 표시가 뜨지 않습니다"*(`frontend/src/lib/budgetStatus.ts:125-131`) ·
일부만 못 세움 -> *"예산 판정 불가 N건도 함께 보는 중"* · 전부 못 세움 -> 토글 잠금 + 사유.
옛 거짓 문장(*"화면이 판정한 값입니다"*)은 제거됐고 `budgetStatus.test.ts:69` 가 **재유입을 막는다**.
`가격 미상` -> `예산 판정 불가` 개명도 `frontend/src/lib/listFilter.ts:265,274` 에 반영·테스트 고정.

---

### 3. 백엔드 — **빈 통과 방지가 실제로 작동한다**

`backend/tests/test_map_budget_parity.py` 재작성분에 변이를 걸었다(전부 원복 확인).

| 변이 | 죽는 테스트 |
|---|:--:|
| **B-M1** `_item_over_budget` -> `budget_at(84.0)` 고정 | **11건** (주장과 일치, 전부 parity 파일) |
| **B-M2** `acquisition_area_class` 상수화(전 면적 한 묶음) | 9건 |
| **B-M3** 면적 미상 -> 84 가정 | 5건 |
| **B-M4** `_over_budget` 의 모름 -> `False` 접기 | 5건 |

빈 통과 방지 장치도 **실물로 확인**했다:
`checked_between == len(MIXED_AREAS)`(면적 7종 전부에서 `between` 가격을 밟는다) ·
`verdicts == {True, False, None}`(한 화면에 3값이 다 나온다) ·
`test_이_테스트가_밟는_경계가_실재한다`(경계 위치 85.00/85.01 까지 못박음) ·
`test_저장한_희망가_기준이면_면적이_섞여도_한_숫자로_맞는다`(*"항상 갈린다고 우기는 검사"* 가 아님을 반증).
내 독립 재현이 같은 숫자(1,026,560,000 / 1,024,580,000 / 차이 1,980,000)를 냈다.

#### 3-1. `test_api.py::test_지도_예산은_자산으로_서버가_계산한다` 의 주석 정직화 — **옳다**

담당자 주장(*"픽스처 세율에서 59.94·84.97·114.5㎡ 한도가 전부 568,250,000"*)을 검증했다:
`backend/tests/fixtures/tax_rules_test.yaml` 의 `t_first_small`(85㎡ 이하)과 `t_first_other` 는
**합계 세율이 둘 다 1.1%** — 면적이 한도를 못 바꾼다. 그리고 **B-M1 변이에서 이 테스트는
실제로 죽지 않았다**(11건 전부 parity 파일). 즉 주석은 **사실이었고, 이제 사실을 적는다.**

> 지킬 수 없는 파일에서 *"CR37-1 을 지킨다"* 고 적어 두는 것이 정확히 **CR-038 이 지적한 형태**다.
> 파일을 억지로 운영 세율로 옮기지 않고 **약한 명제만 주장**하도록 고친 판단이 옳다 —
> 그 파일이 지키는 것(`price_area_m2` 배선 + 비교 방향)은 여전히 유효하고,
> 강한 명제는 운영 세율로 도는 전용 파일이 진다. **역할 분리로 푼 것이 맞다.**

#### 3-2. **같은 형태가 더 있는가** — 1건 발견(CR39-2, 비차단)

`over_budget` 을 단언하는 테스트 6파일을 훑고, 면적 의존 명제를 픽스처 세율로 주장하는 자리를 찾았다.
테스트 쪽에는 **더 없다.** 대신 **제품 코드 쪽**에서 같은 형태를 찾았다 — §5 CR39-2.

---

### 4. SR34-1 조치와 그 파생 위험 — 판정

`guard_site()` 를 `deploy/DEPLOY.md:643-690` 에서 그대로 떼어 **로컬 격리 샌드박스**에서 실행했다.

| 케이스 | 결과 |
|---|---|
| 활성 링크 없음 | `[차단] 이 파일은 활성 사이트가 아니다` **rc=1** — ④ 가 SR34-1 함정을 잡는다 |
| 활성 + 공백 든 root(`/.../web root/dist`) | `치환 완료 · root 경로 존재 · 활성 사이트 확인` **rc=0** — 막지 않는다 |
| 존재하지 않는 root | `[차단] 존재하지 않는 root 경로: /nope/...` **rc=1** |

**CR38-5 도 실증했다** — 같은 설정에 옛 방식(`for d in $(...)`)을 돌리자
`/.../srv/web` 와 `root/dist` **두 개로 쪼개져** 정상 설정을 거짓으로 막았다. `while IFS= read -r` 이 옳다.
(④ 의 심볼릭 링크 해석은 Git Bash 가 `ln -s` 를 복사로 처리해 로컬에서 검증 불가 —
**SR-035 가 운영 서버에서 rc=0/rc=1 을 직접 확인**했으므로 그 결과를 채택한다.)

***"다음 reload 가 certbot 일 수 있다"* 는 지적 — 타당하다.** 오히려 약하게 적혔다:
SR-035 실측으로 갱신 설정 4개 중 3개가 `installer = nginx` 이고 certbot 이 nginx 설정을
**고치고 적용한 기록**이 남아 있다(다음 시도 약 8/3). 나쁜 파일을 디스크에 남기면 안 된다는 판단이 맞다.

**백업+되돌리기는 충분한가 — 아니다(CR39-3, 비차단).** 세 가지가 미흡하다:

1. 되돌리기가 **주석**이라 자동으로 돌지 않는다(`DEPLOY.md:731,779`). `&&` 체인이 끊긴 뒤
   사람이 한 줄 더 쳐야 한다 — 지적한 위험(무인 reload)의 시간창을 사람 손에 맡긴다.
   (SR35-1 과 동일 결론)
2. **백업 실패가 덮어쓰기를 막지 않는다** — `sudo cp "$SITE" "$BACKUP" && echo ...` 는
   실패해도 `&&` 가 echo 만 건너뛰고 **다음 줄에서 살아 있는 파일을 덮어쓴다**
   (`DEPLOY.md:713-715`, `767-770`). 백업 없는 상태로 되돌릴 곳이 사라진다.
3. `backend/tests/test_deploy_config.py` 에 **백업·되돌리기를 요구하는 검사가 없다** —
   지금 넣은 안전장치가 다음 정리에서 조용히 빠져도 아무도 모른다.
   (이름 통일·가드·`&&` 체인은 검사가 있다.)

---

### 5. 비차단 지적

| ID | 심각도 | 내용 | 수정 제안 |
|---|---|---|---|
| **CR39-1** | **high** | **`apiContract.test.ts` 의 전수 검사가 CRLF 체크아웃에서 무너진다.** 이 저장소는 `core.autocrlf=true` · `.gitattributes` 없음이고 `git ls-files --eol frontend/src/lib/tags.ts` 가 `i/lf  **w/crlf**` 다. `screenBudget.ts` 하나만 CRLF 로 바꿔 재현: `싣는 파일은 lib/screenBudget.ts 하나뿐이다` 가 `expected [] to deeply equal ['../lib/screenBudget.ts']` 로 **실패**한다. 원인은 `codeLines` 가 `split("\n")` 후 남는 `\r` 이고, JS 에서 `\r` 은 줄종결자라 `/over_budget:\s*(.*)$/` 가 **아예 매칭되지 않는다** -> `writes` 가 **빈 배열**. 즉 ① 정상 코드에서 **오탐**이고 ② 그 상태에서 `그 값은 relayServerVerdict( 로만 만든다` 루프가 **공허**해진다. 실패 메시지가 원인을 오도해("하나가 아니다") 다음 사람이 단언을 느슨하게 만들기 쉽다 | ① `.gitattributes` 에 `* text=auto eol=lf`(또는 `*.ts *.tsx *.css text eol=lf`) 추가 — 근본 해결. ② 겸해서 `codeLines` 를 `split(/\r?\n/)` 로. ③ CRLF 사본으로 파서를 때리는 검사 1건 추가(`specParser.test.ts` 와 같은 방식) |
| **CR39-2** | **high** | **같은 형태가 추천 경로에 남아 있다.** `backend/app/agents/recommend.py:155` 이 `PropertyFacts(purpose=...)` 로 만들고(`backend/app/domain/affordability/models.py:50` 기본 `area_m2=84.0`) 그 한 숫자를 후보 **하드 제외**(`price > budget`)와 `_budget_notes` 문구에 쓴다. 그런데 후보의 판정 단위는 `docs/02-design/api-spec.md:762` 가 못박듯 **단지 x 면적대**다 — 114㎡ 후보가 84㎡ 한도로 걸러진다. 방향은 **관대**(cap(84)=1,026,560,000 > cap(114.5)=1,024,580,000)라 *못 사는 후보가 통과*한다. 크기는 1,980,000원(약 0.19%)으로 추정가 오차보다 작지만, `api-spec §4`(499-536)가 *"예전에는 기본값 84.0 으로 한 숫자를 만들어 전부를 판정했다"* 고 **과거형으로** 적어 두어 추천도 고쳐진 것처럼 읽힌다. 덤으로 지도가 `예산 초과` 배지를 단 카드에 추천 순위 배지가 함께 설 수 있다(`App.tsx:200-206` rankById) | 어느 쪽이든 하나: **(가)** 추천도 후보 면적으로 상한을 세운다(`_profile_budget` 재사용 — 구간 캐시가 이미 있다). **(나)** 고칠 수 없다면 `api-spec` 과 `_budget_notes` 에 *"이 상한은 84㎡ 기준이다"* 를 **명시**하고 그 사실을 고정하는 테스트를 둔다 — §3-1 에서 칭찬한 "약한 명제만 주장" 과 같은 처리 |
| **CR39-3** | med | 런북의 백업·되돌리기가 약하다(§4 의 3가지) | ① 되돌리기를 `\|\| { sudo cp "$BACKUP" "$SITE"; sudo nginx -t; }` 로 **자동화**, ② 백업 `cp` 를 `\|\|`+중단으로 묶어 백업 실패 시 덮어쓰지 않게, ③ `test_deploy_config.py` 에 "설치 블록마다 백업+되돌리기가 있다" 검사 추가 |
| **CR39-4** | low | 구조 관문 우회(F-M5) — 판정을 외부 모듈로 빼고 리터럴만 남기면 `apiContract` 는 통과한다. 단위·화면 테스트가 잡으므로 실효 위험은 낮다(CR38-2 이월, 상태 개선됨) | 굳이 막는다면 `screenBudget.ts` 의 **import 가 타입뿐**임을 단언(값 import 0건). 지금 방어로 충분하다고 보면 미조치 가능 |
| **CR39-5** | low | `guard_site ③` 의 `grep -oE '^[[:space:]]*root...'` 는 **줄 시작의 `root` 만** 본다. `location / { root ...; }` 처럼 한 줄로 적으면 검사 대상에서 빠진다(현재 `deploy/nginx-realestate.conf` 의 root 3곳은 전부 줄 시작이라 오늘은 무해). 또 `roots` 가 비어도 ③ 은 통과한다 | 앵커를 `[[:space:]]*root[[:space:]]` 로 완화하거나, root 를 0개 찾으면 경고 |

---

### 6. 판정 사유

**차단하지 않는 이유는 결과다.** CR-038 이 건 조건은 *"면적이 섞인 bbox 에서 3상태 전부"* 였고,
나는 그 계산을 **오늘 코드·오늘 세율로 직접 다시 돌려** 옛 화면의 conflicts 3/3/4 가
**0/0/0** 이 되는 것을 봤다. 화면이 판정을 만들지 않는다는 새 명제(㉡)는 타입·호출부 축소·
전수 검사·단위·화면 5겹으로 지켜지고, 내가 건 6가지 되돌림 변이가 **전부 죽는다**.
`null`(모름)이 `false` 로 접히는 옛 명제(㉠)도 그대로 살아 있다 —
**관문을 지운 게 아니라 하나 더 얹었다.**

**부작용 처리도 인정한다.** 배지가 사라진 자리에 *"왜 안 뜨는가"* 가 세 갈래로 다 적혀 있고,
거짓이 된 옛 문장은 제거된 뒤 **재유입 방지 단언까지** 붙었다. 조용한 유실 없음.

**백엔드의 자기고발이 이 라운드에서 가장 좋은 항목이다.** 변이를 전 스위트에 걸어
*자기 테스트가 안 죽는다*는 사실을 찾아내 주석을 사실로 고친 것은, 검사를 늘리는 것보다
어려운 일이다. 내가 확인한 바로 그 판단은 정확했고(B-M1 에서 실제로 안 죽는다) 처리도 옳다.

**비차단으로 남긴 것을 분명히 한다.** CR39-1 은 *검사가 아니라 검사의 환경* 문제다 —
CRLF 에서 붉게 죽으므로 조용히 썩지 않고, 나머지 4겹은 줄바꿈에 영향받지 않는다.
CR39-2 는 **CR38-1 의 통과 조건 밖**이고(그 조건은 지도·목록 배지였다) 크기가 0.19% 이며
방향이 관대 쪽이다 — 조건을 충족한 델타에 사후에 골대를 옮겨 다는 것은 하지 않는다.
다만 둘 다 **다음 라운드에서 볼 자리**로 남기고, 특히 CR39-1 은 **커밋 전에 처리할 것을 권고**한다
(이 저장소를 Windows 에서 다시 체크아웃하면 그 순간 프론트 스위트가 붉어진다).

> 두 담당자가 갈렸던 CR-038 의 자리는 닫혔다. 프론트가 자기 근거 셋 중 둘이 무너졌다고
> 먼저 인정하고 판정 자리를 통째로 넘긴 것이 옳은 선택이었다 —
> **정확해진 쪽이 있으면 나머지 한쪽도 같이 옮겨야 한다**는 CR-038 의 문장이 그렇게 실행됐다.

### 리뷰 위생

변이 12종(F-M1~F-M8 · B-M1~B-M4) 전부 원복 확인 — `diff` 로 백업 대조 · 잔여 임시파일 0.
CRLF 실측 과정에서 `frontend/src` 줄바꿈을 일괄 변환했다가 되돌렸다:
내용 변경 있는 64파일은 `git diff --numstat` 로 동일 확인, 줄바꿈만 달라진 17파일은
`git checkout --` 로 원복 -> `git status --porcelain` 이 리뷰 전과 같은 **64 modified + 25 untracked**.
최종 재실행 그린(backend 1,455 / frontend 951 / tsc 0).

---

## CR-040 · 2026-08-01 · CR39-2 재검증(담당자 검증 없음) · 날짜 취약 테스트 · **5단계 감시 신규**

**판정: FAIL** — 차단 **2건**(둘 다 `deploy/monitor.sh`). CR39-2 와 날짜 수정은 **합격 · 재작업 불필요**.

> 이 라운드의 성격이 셋으로 갈린다. **차단은 세 번째(감시)에만 걸린다.**
> ① CR39-2 는 담당자가 막바지 검증 전에 멈춰 **검증 없이 넘어온 작업물**이라, 프로젝트 테스트에
> 기대지 않고 내가 API 전 구간을 직접 다시 돌렸다. ② 날짜 수정은 직전 라운드의 판단이 옳은지
> 되짚고 **같은 형태를 전수로** 훑었다. ③ 감시는 신규 코드다.

---

### 0. 실행 검증 — 주장 수치 **전부 실측 일치**

```
backend   pytest --junitxml   tests=1569 failures=0 errors=0 skipped=103  ->  1,466 passed
frontend  npm test            Test Files 48 passed · Tests 951 passed (78.97s)
bash -n   monitor.sh · monitor-lib.sh · job-run.sh · market-index.sh   -> 전부 exit 0
git diff --stat  소스 12파일 + 신규 7파일 (프론트 변경 0 — 951 무변경이 맞다)
```

델타 backend **+11**(1,455 -> 1,466) · frontend **0** — 주장과 일치.
운영 서버 **미접촉**(SSH·크론·reload·실패주입 모두 하지 않음). 감시 스크립트는 **로컬 격리
상태 디렉터리 + `RE_MON_DRY_RUN=1`** 로만 실행했다.

※ 리뷰 도중 `security-review-log.md`·`.review-state.json` 이 늘어난 것은 security-reviewer 가
같은 시각 **SR-036 / SR-036R** 를 기록했기 때문이다(소스 델타 아님). §3 에서 교차 참조한다.

---

### 1. CR39-2(추천 예산 상한을 면적별로) — **해소. 내가 직접 재현했다**

프로젝트 테스트를 믿지 않고 **리뷰어가 쓴 스크립트**로 API 전 구간을 다시 돌렸다
(운영 세율 · 현금 5억 · 연소득 1억 · 희망가 미저장 · 면적 7종 × 가격 3구간 + 면적 미상 = 22후보,
`POST /api/v1/recommendations` -> `GET /api/v1/recommendations/{job_id}`).

```
운영 세율 실측:  84.00m2 -> 1,026,560,000   114.50m2 -> 1,024,580,000
                85.00m2 -> 1,026,560,000    85.01m2 -> 1,024,580,000
                차이 1,980,000 (0.19%)   ·  기본(면적 미지정) = 1,026,560,000
```

CR-039 가 적은 숫자와 **완전히 같다**. 경계 위치(85.00 / 85.01)도 실재한다.

| 확인 항목 | 결과 |
|---|---|
| 옛 판정(84m2 한 숫자)과 서버 판정이 갈리는 후보 | **3건** — `85.01` · `114.50` · `120.00` 의 `between` 가격 |
| 방향 | 전부 **통과 -> 초과**. 즉 옛 판정이 **관대**했고 *못 사는 후보를 통과*시켰다(CR-039 지적 그대로) |
| 하드 제외라 후보가 사라지는가 | **사유가 남는다.** 제외 10건 전부 `reason_code`+문장이 있고, 문장에 적힌 한도가 **그 후보 면적으로 부른 `/affordability` 값과 일치**(전건 대조) |
| 조용한 유실 | **없다.** `items 12 + excluded 10 = 22` = 후보 총수. 어디에도 없는 후보 0건 |
| 면적 미상 후보 | 제외도, 84 가정도 아니다 — `items` 에 남고 `budget_gap_krw = null`, `notes` 에 *"후보 1건은 전용면적이 확인되지 않아 예산 상한을 세우지 못했고 … '예산 안'이라는 뜻이 아닙니다"* 가 실제로 실린다 |

#### 1-1. 변이 — 되돌리면 **죽는다**

| 변이 | 죽는 검사 |
|---|:--:|
| **M-1** `orchestrator.py:1458` `ctx.budget_cap_krw(cand.area_m2)` -> `ctx.effective_budget_krw`(옛 한 숫자) | **5건** (전부 `test_recommend_budget_parity.py`) |
| **M-2** 면적 미상 고지(`if budget_unknown_area:`)를 끔 | **1건** (`…제외도_통과도_아니라_고지된다`) |
| **M-3** 면적 미상을 **84 로 가정**(`cand.area_m2 or 84.0`) | **1건** (동일) |

세 변이 모두 원복 확인(`grep MUT- = 0` · `git diff --stat` 이 리뷰 전과 동일 63줄) 후
관련 5파일 161건 재실행 그린.

#### 1-2. **중복 구현이 아닌가** — 한 곳에서 온다. 확인함

`routes.py` 의 `_fixed_budget`·`_profile_budget` 은 **삭제**되고 `MapBudgetFn = BudgetFn` 별칭만
남았다. 전체 소스에서 `acquisition_area_class` 호출부는 `app/domain/affordability/budget.py:89`
**한 곳뿐**이고, `PropertyFacts(` 생성은 ① `budget.py`(면적별 조회기) ② `routes.py:696`
(`POST /affordability` — 요청이 준 면적) 두 곳뿐이다. 즉 **지도·추천·자금계획이 같은 함수를 탄다.**
러너가 라우터를 import 하면 순환(`routes -> agents.recommend`)이므로 도메인에 둔 배치도 옳다.

#### 1-3. 담당자가 손댄 `routes.py`·`main.py` — **의도 범위 안이다**

* `routes.py` — 함수 2개의 **이전(移轉)**과 호출부 2줄 교체뿐. 행동 변화 없음
  (`compute_affordability` import 는 `POST /affordability` 가 계속 쓰므로 남는 것이 맞다).
* `main.py` — **주석만 늘고 빈 줄 하나 줄었다.** 실행 코드 변화 0.
  내용은 원장 이월 항목 `SR33-3`(앱 미들웨어 접근 로그는 운영에서 한 줄도 안 나간다)의 사실 기록이고,
  나는 그 주장까지 확인했다: `app` 로거는 핸들러가 없고 uvicorn `LOGGING_CONFIG` 는 `uvicorn*` 만
  설정하므로 effective level 이 WARNING 이다. 유일한 `logging.basicConfig` 는 `app/worker.py:20`
  인데 **워커는 별도 컨테이너 커맨드**(`docker-compose.yml:57,72` `python -m app.worker`)라
  API 프로세스에 들어오지 않는다 — 주석이 사실이다.

---

### 2. 날짜 취약 테스트 — **판단은 옳다. 원인 진단까지 맞다**

#### 2-1. 재현

`_seed_two_areas_monthly` 를 **옛 시드(`_seed_two_areas`)로 되돌리는 변이**를 걸고 날짜를 고정해 돌렸다:

| 시각 | 결과 |
|---|:--:|
| 2026-07-29 / 07-30 | 통과 |
| **2026-07-31** | **FAIL** `test_user_listing_wiring.py:653` (`plan.target_price.krw > 7.0억`) |
| 2026-08-01 | 통과 |

산수도 맞는다: 7/31 이면 `TODAY-15i` 8건이 (0,0,0,1,1,2,2,3)개월 전으로 떨어지고, 보정배율
(0.99, 0.99, 0.99, 1.0, 1.0, 1.0101, 1.0101, 1.0204)의 **중위가 정확히 1.0** 이 된다.
*"월말에 여러 건이 이번 달로 몰려 배율이 1.0 이 된다"* 는 진단 그대로다.

#### 2-2. 고친 테스트가 여전히 무엇을 증명하는가 — **약해지지 않았다**

`_ym_back` 은 거래를 **매월 15일 · 기준월보다 항상 과거(2~9개월 전)** 에 심는다. 고친 뒤
2026-07-28~08-15 · 2026-02-27~28 전 날짜에서 통과.
공용 `_seed_two_areas`(19곳 사용)를 안 고친 판단도 옳다 — 밴드 창(6/12/24/36개월) 구성이 달라져
다른 검사의 의미까지 바뀐다. **역할 분리로 푼 것이 맞다**(CR-039 §3-1 과 같은 처리).

판별력은 그대로다: 지수를 없애면 `basis == "time_adjusted_band"` 가 먼저 깨지고,
`complex_region_code` 를 없애면 두 금액이 갈려 깨진다(파일 머리말의 변이 ①②가 그대로 성립).
⚠️ 다만 **마지막 단언 `> 7.0억` 의 성격은 바뀌었다**: 이제 시드가 "전부 과거 달"이라
*보정이 돌기만 하면* 참이다. 판별력을 지는 것은 `basis` 단언 쪽이다 -> **CR40-6(low)** 로 기록.

#### 2-3. ★ 같은 형태 **전수 조사** — 담당자가 못 끝낸 부분

`fakedate` 플러그인(`datetime.date`/`datetime` 을 교체해 `today()`/`now()` 고정)으로 실측했다.

| 범위 | 결과 |
|---|:--:|
| **전 스위트**(1,569) × 전진 날짜 7종 (08-31 · 09-01 · 12-31 · 2027-01-01 · 2028-02-29 · 10-15 · 11-30) | **failures 0** |
| **날짜 민감 파일 11개** × **하루씩 81일** (2026-08-01~08-31 전일 · 2027-01-25~03-05 · 2027-03-25~04-03) | **failures 0** |

대상 11파일은 `TODAY - timedelta(days=…)` 시드나 시장지수를 쓰는 전부:
`test_price_consistency` · `test_timeadjust_wiring` · `test_user_listing_wiring` ·
`test_valuation_timeadjust` · `test_valuation` · `test_agents` · `test_recommend` ·
`test_condition_reach` · `test_llm_wiring` · `test_redevelopment` · `test_user_listings`.

**정직하게 남긴다 — 내 방법의 한계와, 그 때문에 나온 가짜 1건.**
2026-02-28(**과거** 시뮬)에서 2건이 붉었다:
`test_price_consistency::test_자금계획이_단지id로_추천과_같은_기준가를_만든다` ·
`test_timeadjust_wiring::test_후보_조립이_지역코드를_실어_보낸다`.
원인을 파 보니 **두 파일의 `TODAY` 는 `dt.date(2026, 7, 28)` 상수**다 — 시계를 과거로 돌리면
거래가 미래가 되어 `eligible_trades` 에서 빠진다. **제품 결함이 아니라 내 시뮬레이션의 산물**이고,
시계가 전진하는 실제 방향으로는 무해하다. 지적으로 올리지 않는다.
다만 그 두 파일은 *시드는 고정 TODAY · 실행 `as_of` 는 `date.today()`* 가 섞여 있어 밴드 사다리
단계가 시간이 가면 조용히 6->12->24->36 으로 내려간다 -> **CR40-7(low)**.

---

### 3. 감시(5단계 신규) — ⛔ **차단 2건**

`bash -n` 4파일 전부 통과. 아래는 **로컬 격리 실행 + 산수 재현**으로 확인한 것이고,
운영 서버는 건드리지 않았다. 담당자 주장 중 서버 실측치(자원 13.5MiB·0.28초 / 실패주입 13종 /
정상 경보 0건)는 **로컬에서 재현할 수 없어 판정하지 않는다**(§3-4).

#### 3-1. `CR40-1` (**high · 차단**) — 시장지수 신선도 검사가 **연 35일 오탐**. 3월은 **29일 연속**

`monitor.sh:446` 이 기대 기준월을 **"오늘 기준으로 완결 가능한 최신 달"** 로 계산한다.

```bash
expected=$(date -d "$(date -d '-30 days' +%Y-%m-01) -1 month" +%Y-%m)
```

그런데 배치는 **매월 1일 04:10 에만** 돈다(`monitoring.md §1` 크론). 즉 DB 의 기준월은
*"이번 달 1일 기준"* 으로 고정돼 있는데 감시의 기대값은 **날마다 앞으로 간다.**
완결 규칙(`timeadjust.REPORT_LAG_DAYS=30` — 그 달 말일 + 30일)으로 한 해를 재 보면:

| 달 | 오탐 일수 | 예 |
|---|:--:|---|
| 2026-08 · 10 · 12 / 2027-01 · 05 · 07 | 각 **1일**(31일자) | 8/31 -> DB `2026-06` · 기대 `2026-07` |
| **2027-03** | **29일**(3/3 ~ 3/31) | 3/3 -> DB `2026-12` · 기대 `2027-01` |
| **합계** | **연 35일** | |

* 문구가 거짓이다 — *"시장지수 기준월 … (월배치가 안 돌았다)"* 인데 배치는 **정상으로 돌았고**
  1일에 1월을 완결로 표시할 수 없었을 뿐이다(1/31+30 = 3/2 > 3/1).
* **이미 한 번 울었을 값이다.** `monitoring.md §3` 이 적은 대로 7/30 시점 DB 기준월은 `2026-05`,
  2026-07-31 의 기대값은 `2026-06` -> 7/31 09:05 일일 점검에서 경보 조건이 선다.
  담당자의 *"정상 상태 경보 0건"* 은 **설치 당일(7/30) 한 시점의 관측**이고 지속 성질이 아니다.
* 피해가 오탐으로 끝나지 않는다. **배치가 진짜로 안 도는 상태를 잡는 경보가 이것뿐**이다
  (`check_jobs` 는 요약 줄만 만들고 경보하지 않는다 · `job-run.sh` 는 *실행됐을 때만* 알린다 ·
  `market-index.sh` 는 `REF` 를 로그로만 남기고 단언하지 않는다). 3월에 29통을 헛울면
  사람은 이 경보를 끄거나 무시하고, 그 다음 진짜 실패는 아무도 모른다.

**PASS 조건**: 기대값을 **배치 주기와 같은 기준**으로 만들 것 — 예:
`expected=$(date -d "$(date -d "$(date +%Y-%m-01) -30 days" +%Y-%m-01) -1 month" +%Y-%m)`
(= "이번 달 1일에 배치가 만들 수 있었던 값"). 그리고 신선도의 **1차 단언은 배치 자신**이
지게 할 것 — `market-index.sh` 는 실행 시점이 항상 1일이라 지금 공식이 그 자리에서는 옳다
(`REF` 를 기대값과 비교해 어긋나면 `fail`). 감시는 그 결과를 확인만 한다.

#### 3-2. `CR40-2` (**high · 차단**) — 로그 검사 3종이 **파일이 없어도 "이상 없음"** (fail-open)

격리 상태 디렉터리 + `RE_MON_DRY_RUN=1` 로 **로그 파일이 하나도 없는** 상황을 만들어 실행한 결과:

```
로그권한: 0개 검사 · 이상 없음
로그유출: access 쿼리 0건 · error request 쿼리 0건 (기대 0/0)
API 5xx : 기준값 설정 (현재 파일 누적 0건)
```

* `check_logperm`(`monitor.sh:281`) — 글롭이 0개면 `bad` 가 빈 문자열이라 **`clear_alert logperm`
  까지 부른다**. 켜져 있던 경보가 있으면 *"nginx 로그 권한 전부 0640 회복"* 이라는 **거짓 해소 통보**가
  사용자에게 간다.
* `check_logleak`(`:309-310`) · `check_api5xx`(`:327`) — `grep -c` 가 없는 파일에서 실패해
  `${e:-0}` / `${a:-0}` / `${cur:-0}` 로 **0** 이 되고, `cur < prev` 는 로그로테이션으로 해석돼
  `delta=0` 이다. 즉 **감시가 눈이 먼 상태와 정상이 구분되지 않는다.**
* 대조군도 확인했다 — 파일을 0644 로 두고 5xx 한 줄을 넣으면 두 검사 모두 **정확히 잡는다**
  (`로그권한 … 이상: realestate.access.log:644` · `API 5xx … 누적 1건`). 검사 로직은 옳고,
  **빈 집합이 통과한다는 사실**만이 결함이다.
* 이 저장소가 `guard_site` 에서 세 번 적발한 그 형태이고(CR39-5 *"roots 가 비어도 ③ 은 통과한다"*),
  하필 이 세 검사가 **실제로 유출 사고가 났던 경로**(0644 회전본 · 쿼리스트링)를 지킨다.
* 담당자의 *"실패 주입 13종 전부 감지"* 는 이 형태를 덮지 못한다 — 문서에 적힌 주입 7종
  (`monitoring.md §7`)은 전부 **임계값·URL 을 바꾸는** 방식이라 파일이 사라지는 경우를 만들지 않는다.

**PASS 조건**: 대상 파일이 0개거나 읽을 수 없으면 **경보**(또는 최소한 *"검사 못 함"* 으로 표시하고
`clear_alert` 를 호출하지 않을 것). 겸해서 `access.log` 의 mtime 신선도(예: 24시간)를 함께 볼 것 —
"파일은 있는데 아무것도 안 쓰인다"가 남는다.

#### 3-3. 확인하지 못한 것 — **정직하게 남긴다**

| 담당자 주장 | 내 판정 |
|---|---|
| 자원 5분 감시 13.5MiB · 0.28초 | **미검증**(운영 실측 · 로컬 재현 불가). 코드상 무거운 호출은 curl 4~5회 + `docker exec psql` 1회/일뿐이라 개연성은 있다 |
| 실패 주입 13종 전부 감지 | **부분 반증.** 13종의 목록이 문서에 없다(§7 예시는 7종). 그리고 §3-2 형태는 감지하지 못한다 |
| 정상 상태 경보 0건 | **시점 한정으로만 참.** §3-1 로 2026-07-31 · 08-31 에 경보 조건이 선다 |
| 민감정보: DSN 주입해도 알림 본문 0건 | **security-reviewer 가 서버 실측으로 확인**(SR-036 §3-1 — 로그 296KB grep 0건 · kv 12개 전수 · argv 노출 없음). 나는 `scrub()` 만 로컬 실행해 §4 `CR40-4` 를 보탠다 |
| 뺀 것(`pg_postmaster_start_time` · `docker stats` MEM · `memory.events max`) | **판단 타당.** 셋 다 "정상인데 우는" 신호이고 대체 신호(`oom_kill` 카운터 · `memory.stat anon`)가 더 정확하다. 특히 `RestartCount=0` 인 채로 크래시 복구가 났다는 실측은 `docker ps` 기반 감시를 배제할 충분한 근거다 |
| 8000 은 itsmine-engine · SPA 폴백이라 없는 경로도 200 | **설계에 옳게 반영됐다.** `URL_LOCAL` 이 8013 이고, 번들 검사(`check_frontend`)가 *"없는 경로 404"* 대신 `/assets/*.js` 의 200+`javascript` 를 본다 — 폴백이 있는 사이트에서 판별력을 갖는 유일한 형태다 |

**상호 감시**는 성립한다(fast <-> daily heartbeat). 다만 비대칭이 하나 있다 -> `CR40-5`.

---

### 4. 지적 사항

| ID | 심각도 | 내용 | 수정 제안 |
|---|---|---|---|
| **CR40-1** | **high · 차단** | 시장지수 신선도 기대월이 배치 주기와 어긋나 **연 35일 오탐**(2027-03 은 29일 연속). 문구는 *"월배치가 안 돌았다"*(거짓). 배치 미실행을 잡는 유일한 경보라 늑대소년이 되면 진짜 실패가 묻힌다 | 기대값을 **이번 달 1일 기준**으로 계산. 1차 단언은 `market-index.sh` 가 지게(그 시점 공식은 옳다) |
| **CR40-2** | **high · 차단** | `check_logperm`·`check_logleak`·`check_api5xx` 가 **대상 파일이 없어도 "이상 없음"** + `clear_alert` 까지 부른다(로컬 재현). 실제 유출 사고가 났던 경로를 지키는 세 검사다 | 대상 0개 = **경보**(또는 "검사 못 함"으로 두고 clear 금지) + `access.log` mtime 신선도 |
| **CR40-3** | med | **셸 4종(약 590줄)에 자동 검사가 0건.** 이 저장소는 `test_deploy_config.py` 로 `DEPLOY.md` 산문·nginx 설정까지 회귀에 묶는데, root 로 5분마다 도는 코드에는 아무것도 없다. CR40-1/2 가 조용히 재유입된다 | 텍스트 검사로 충분: ① 기대월 공식이 배치 주기와 같은 기준인가 ② 빈 글롭이 경보로 가는가 ③ `scrub()` 규칙 목록 ④ `monitoring.md` 의 크론 3줄과 스크립트 인자(`--fast`/`--daily`)가 일치하는가 |
| **CR40-4** | med | **`scrub()` 의 금액 마스킹이 문서대로 동작하지 않는다.** `monitoring.md §2` 는 *"9자리 이상 숫자는 `<num>` 으로 치환한다"* 고 단정하는데 실측은 `1026560000` 만 치환되고 `1026560000원`(UTF-8 로케일에서 `원`이 단어문자라 `\b` 불성립) · `1,026,560,000원`(앱이 실제로 쓰는 형식)은 **미치환**. `KEY: value`(콜론+공백)도 미치환 | 정규식 보강(`SR36-3` 이 같은 것을 low 로 이미 지적) — **문서 문장도 함께** 사실로 고칠 것. 지금은 문서가 방어를 과장한다 |
| **CR40-5** | med | **배치가 "아예 안 도는" 상태에 경보가 없다.** `check_jobs` 는 요약 줄만 만들고, `job-run.sh` 는 실행됐을 때만 알린다. 크론이 사라지거나 `flock` 에 매번 걸리면 `last_success_at` 이 낡은 채 조용히 남는다. 겸해서 fast 의 상호 감시는 `last_daily_run` 이 비면 **침묵**한다(daily 쪽은 비면 경보 — 비대칭) | `$JOBS/*.status` 의 `last_success_at` 이 N일 이상 낡으면 경보. fast 도 `last_daily_run` 이 비면 "일일 감시 기록 없음"으로 경보(설치 유예는 kv 에 설치시각을 두어 처리) |
| **CR40-6** | low | 고친 `test_자금계획이_API_경로에서도…` 의 마지막 단언(`> 7.0억`)은 시드가 "전부 과거 달"이라 **보정이 돌기만 하면 참**이 됐다. 판별력은 `basis == time_adjusted_band` 가 진다 | 시드에 기준월보다 **미래인 달**을 하나 섞어 배율 < 1 후보도 두거나, 단언을 "보정 전 명목 중위와 다르다"로 바꿔 방향이 아니라 **변화**를 못박기 |
| **CR40-7** | low | `test_timeadjust_wiring`·`test_price_consistency` 는 *시드 TODAY 는 상수(2026-07-28) · 실행 `as_of` 는 `date.today()`* 가 섞여 있어, 실제 시계가 가면 밴드 사다리가 조용히 6->12->24->36 으로 내려간다(2029년경 `test_후보_조립이_지역코드를_실어_보낸다` 가 표본 부족으로 죽는다) | 그 경로에도 `as_of=TODAY` 를 명시해 넘기거나, 시드를 `as_of` 기준 상대월로 만들 것 |
| **CR40-8** | low | `clear_alert` 는 `send_telegram` 실패에도 `.active`/`.sent` 를 지운다 — `monitor-lib.sh` 머리말 규칙 3(*"성공할 때까지 `.sent` 를 찍지 않는다"*)과 어긋나고 **해소 통보가 조용히 사라진다** | 전송 성공했을 때만 상태 제거 |
| **CR40-9** | low | 면적 미상 고지의 문장이 *"목록에 남겨 두었습니다"* 인데 카운터는 **기피 조건 제외·상위 N 밖으로 밀린 후보까지** 센다(`orchestrator.py:1458` 이 다른 하드 제외보다 앞) | 문구를 "예산 판정을 하지 않았습니다"로 바꾸거나 최종 `items` 기준으로 셀 것 |
| **CR40-10** | low | 문서 정합 2건 — ① `monitoring.md §6` 이 *"market-index.sh 를 저장소에 넣기(중간)"* 를 아직 할 일로 적는데 **이번 델타가 넣었다**. ② §7 실패주입 예시는 7종인데 본문은 *"13종 전부 감지"* — 어떤 13종인지 없어 다음 사람이 재현할 수 없다 | ① 항목 제거(또는 "서버 사본은 여전히 미추적"으로 축소) ② 13종 목록을 표로 |

---

### 5. 판정 사유

**차단은 감시 두 건에만 걸린다. 그리고 그 둘은 결과로 정당화된다.**
`CR40-1` 은 산수로 재현했고 **날짜까지 특정된다**(2026-08-31 · 2027-03-03~31 · 연 35일).
`CR40-2` 는 격리 실행으로 화면에 띄웠고, 정상 파일을 놓아 준 대조군에서 **같은 검사가 정확히
잡는 것**까지 확인했다 — 로직이 아니라 **빈 집합이 통과한다는 사실**만이 결함이다.
둘 다 판정 기준의 두 문장(*"오탐도 결함"* · *"조용한 유실 금지"*)에 정면으로 걸린다.

**차단하면서도 분명히 한다 — 다시 만들 것은 셸 두 자리뿐이다.**
CR39-2 산출물과 날짜 수정은 **합격**이고 손댈 필요가 없다. 특히 CR39-2 는 담당자 검증이
없는 채로 넘어왔는데, 내가 프로젝트 테스트에 기대지 않고 API 전 구간을 다시 돌려
**옛 판정과 갈리는 3건 · 방향(관대) · 사유 문구의 한도 일치 · 후보 보존(22=12+10) · 면적 미상 고지**
를 전부 실물로 봤다. 변이 세 종도 전부 죽는다. 이 항목은 **CR-039 가 요구한 것을 결과로 충족한다.**

**감시 설계 자체는 좋다는 말도 같이 적는다.** *"정상인데 우는 검사는 일부러 뺐다"* 는 태도와,
`pg_postmaster_start_time` 이 실제 사고 3건을 전부 놓쳤을 것이라는 실측, SPA 폴백 때문에
*"없는 경로 404"* 가 무력하다는 발견, `127.0.0.1:8000` 이 남의 서비스라는 발견 —
이 넷은 감시를 **만들기 전에 재 본 사람만** 쓸 수 있는 문장이다. 그래서 더더욱,
그 기준을 자기 코드의 두 자리에도 적용해야 한다. 지금 그 두 자리가 각각 **울지 말아야 할 때 울고**,
**울어야 할 때 조용하다.**

**커밋 순서에 대한 의견(권고).** SR-036R 이 옳게 지적했듯 *"서버에서 root 로 도는 코드가 어디에도
기록되지 않는 상태"* 는 그 자체로 위험이다. 그러므로 이 차단은 **길게 끌 것이 아니다** —
`monitor.sh` 두 자리(각 몇 줄)를 고치고, **서버 사본에도 같이 올린 뒤**(저장소만 고치면 도는 것은
옛 코드다), 재실행해 `CR40-1`·`CR40-2` 만 재검증하면 PASS 한다. 나머지 8건은 비차단이다.

---

### 리뷰 위생

* 변이 3종(M-1 · M-2 · M-3) 전부 원복 — `grep MUT- = 0`, `git diff --stat` 이 리뷰 전과 동일
  (`orchestrator.py` 63줄), 관련 5파일 161건 재실행 그린(failures 0 · errors 0).
* 감시 실행은 **전부 로컬 격리**(`RE_MON_STATE`/`RE_MON_LOG`/`RE_MON_LOG_DIR` 을 임시 경로로,
  `RE_MON_DRY_RUN=1`). 운영 서버 SSH·크론·설정 **미접촉**, 실패 주입 **하지 않음**
  (5분 크론이 돌고 있어 주입하면 사용자 텔레그램으로 알림이 간다).
* 날짜 시뮬레이션은 리뷰 전용 pytest 플러그인(`fakedate`)을 **스크래치패드에만** 두었다 —
  저장소에 추가한 파일 0건. 리뷰 후 `git status --porcelain` 이 리뷰 전과 동일.
* ⚠️ 한글 테스트명으로 `pytest -k` 는 쓰지 않았다(인코딩 문제). 전부 파일 단위 + `--junitxml` 파싱.

---

## CR-041 · 2026-08-01 · CR-040 차단 2건 재검증 (범위 `deploy/**` · `docs/05-monitoring/**`)

**판정: FAIL** — 차단 **2건**. 다만 **CR40-1 · CR40-2 는 둘 다 해소됐다**(내가 직접 재현했다).
차단은 **이번 델타가 새로 만든 것 1건**과 **저장소 관문이 붉어진 것 1건**에 걸린다.

> 이 라운드에서 담당자가 한 일의 질은 높다. 특히 *"경보를 미리 켜 놓고 돌린다"* 는
> 검증 설계와, *"기대보다 앞선 경우는 일부러 단언하지 않는다"* 는 판단은 둘 다 옳고,
> 내가 숫자로 재확인했다. 그래서 더더욱, 그 기준이 안 닿은 두 자리를 적는다.

---

### 0. 실행 검증 — 주장 대비 **1건 불일치**

```
bash -n deploy/*.sh                      8파일 전부 exit 0
bash deploy/monitor-selftest.sh          통과 49 · 실패 0 · 건너뜀 2   (주장 일치, 5m49s)
backend  python -m pytest -q             1,465 passed · **1 failed** · 103 skipped  <- 주장(1,466 유지)과 다르다
frontend npm test -- --run               48 files · 951 tests (개수 일치)
git diff --stat                          소스 무변경 + 신규 6파일(deploy 5 · monitoring.md)
sha256  서버 5/5 = 로컬 5/5              일치 확인 (아래 §5)
```

프론트 3건(`MapView.test.tsx` "SDK 로드가 실패할 때" · 각 1,000ms)은 **동시 부하에서만** 붉고
단독 실행은 19/19 그린이다. 프론트는 이번 델타에서 변경 0(`git status --short frontend/` 비어 있음) →
**환경 산물로 판단하고 지적하지 않는다.** 백엔드 1건은 다르다 → `CR41-1`.

---

### 1. `CR40-1` 시장지수 신선도 오탐 — **해소. 운영 로그가 내 예측을 확증했다**

#### 1-1. 서버 실물 (읽기만 했다. 실패 주입 없음)

```
2026-07-31 09:05:06 ALERT dbstruct :: 시장지수 기준월 2026-05 < 기대 2026-06(월배치가 안 돌았다)
2026-08-01 09:05:04 ALERT-CLEARED dbstruct :: DB 구조·시장지수 정상 (… 기준월 2026-06)
/var/lib/realestate-monitor/jobs/market-index.status -> last_rc=0 · 51초 · 2026-08-01 04:10:52 성공
```

CR-040 이 *"2026-07-31 에 경보 조건이 선다"* 고 적은 그 날짜·그 값이다. 배치는 정상이었고
**소음 2통이 실제로 사용자에게 갔다.** 담당자 보고가 사실이다.

#### 1-2. 365일을 **내가 직접** 돌렸다 — 담당자 모델을 쓰지 않았다

selftest 의 `model_db_ym()` 을 신뢰하지 않고, **파이썬 구현 규칙**(`timeadjust.open_ym` =
`ym_of(as_of − 30일)`, 완결 후보는 그보다 작은 달)을 직접 불러 모델을 세우고,
`market_expected_ym()` 을 파이썬으로 재구현해 **bash 본체와 100개 표본으로 대조**했다
(윤년 2028-02-29 · 2027-03 · 매월 1일 00:30/04:00/05:59/06:01 포함, **불일치 0**).

| 항목 | 결과 |
|---|---|
| 새 공식 오탐 | **0** — 2026-08-01~2030-07-31 **1,461일 × 점검시각 8종 = 11,688 평가** |
| 옛 공식 오탐 | 같은 4년 1,216 평가 · **09:05 만 세면 141일** |
| 주장한 365일 창(2026-08-01~2027-07-31) @09:05 | 옛 공식 **35일** — **주장·CR-040 실측과 정확히 일치** |
| 3월 연속 | 2027-03-03 ~ 03-31 = **29일 연속**(CR-040 이 센 것 그대로) |
| 매월 1일 경계 | 00:30·04:00·05:59·06:01·23:59 **오탐 0** |
| 변이 M-1(옛 공식 복귀) | **죽는다** — T2 에서 3건 실패(오탐 1일 · DB 모델 불일치 1일 · 경계 2건) |

`market_expected_ym()` 이 **기준 시각을 인자로 받게** 만든 설계가 이 검증을 가능하게 했다.
날짜 의존 코드를 검증 가능하게 만든 것은 이 라운드의 가장 좋은 판단이다.

#### 1-3. 판단 ③(**기대보다 앞선 경우는 단언하지 않는다**) — **옳다. 숫자로 확인했다**

* 대칭으로 단언하면(≠ 이면 실패) **월중 수동 실행이 365일 중 35일 죽는다.**
  그리고 그 35일은 **옛 공식이 헛울던 바로 그 35일**이다 — 같은 현상의 반대쪽이다.
* 앞선 방향이 방치되는가? 아니다. `< 기대` 검사와 `OPEN` 검사(진행 중인 달을 완결로
  표시하면 실패) **둘 다 통과하는 값**을 전수로 뽑아 보니 36건이고, **전부**
  *"월말에 손으로 돌려서 REF 가 직전 달"* 인 **정상 사례**였다. 위험한 쪽(너무 이른
  완결 표시)은 `OPEN` 이 이미 잡는다. → **일부러 안 한 것이 맞다.**

#### 1-4. 다만 조치 ②(**1차 단언을 배치가 짐**)는 **작동하지 않는다** → `CR41-2`

---

### 2. `CR40-2` 로그 검사 fail-open — **해소. 내 DRY-RUN 으로 다시 확인했다**

담당자가 말한 대로 **경보를 미리 켜 놓고** 돌렸다(`logperm`·`logleak`·`logfresh`·`api5xx`·
`sshpw`·`web` 6종을 `.active`+`.sent` 로 무장). 격리 상태 + `RE_MON_DRY_RUN=1`, 서버 미접촉.

| 시나리오 | 결과 |
|---|---|
| **A. 무장 상태 + 모든 로그 대상 소실** | `ALERT-CLEARED` **0줄** · 나간 메시지에 *"해소"* **0통** · 켜져 있던 6건 **전부 생존** · `logblind` **1통**(3통 아님) |
| **A'. 5xx 기준값** | 파일 소실 시 `kv/api5xx` **미생성/미변경** |
| **B. 로그 경로가 파일이 아니라 디렉터리** | `readable()` 이 걸러 `검사못함` + blind (엣지도 막힌다) |
| **C. 소실→복귀 사이클** | 기준값 1 유지 → 5xx 3줄 추가 후 복귀 시 **"이번 구간 3건"**(0 덮었으면 4건으로 폭증했을 자리) |
| **D. 부분 실명**(access 정상 · error 소실) | `logleak` **clear 안 함** · 요약 `access 0건 · error 검사못함` |
| **E. 양성 대조군**(정상 복귀) | `ALERT-CLEARED logleak` 실제로 나가고 `.active` 삭제 — **한쪽으로만 막지 않았다** |

**E 가 중요하다.** *"못 보면 clear 금지"* 를 넣다가 정상일 때도 해소 통보가 영영 안 오게
만들면 그것도 결함인데, 그 자리를 selftest 가 스스로 검사하고 있고(`T5`) 나도 재현했다.

#### 2-1. mtime 신선도 — 새벽 무트래픽에 **안 운다**

| mtime | 결과 |
|---|:--:|
| 4시간 전 | 조용 |
| 23시간 전 | 조용 (임계 24) |
| 25시간 전 | **경보** |

근거도 실물로 확인했다 — 서버 5분 감시 로그가 `로그신선: access 마지막 기록 0시간 전`,
`로그권한: nginx 11개 · 앱/배치 2개 검사 · 이상 없음`. **두 묶음 다 0개가 아니어서 새 코드가
운영에서 실제로 동작 중**이고, 09:56 배포 이후 **경보 0건**이다.

변이 **M-2**(0개일 때 `clear_alert` 복귀) **6건 실패로 죽고**, **M-4**(5xx 기준값 0 덮어쓰기)
**1건 실패로 죽는다**.

---

### 3. 함께 처리된 것 — 검증 결과

| 항목 | 판정 |
|---|---|
| **SR36-2 로그 권한 3부분** | **해소.** 서버 실측 `ls -l`: nginx 11개·앱/배치 2개 **전부 `-rw-r-----`**, `/var/log/realestate_market_index.log` 포함. 크론에 `umask 027` 실재, `job-run.sh` 매 실행 `chmod 640` 실재(기존 로그를 `:` 로 비우지 않는 것도 확인) |
| **SR-036R T2 `check_sshlogin`** | **판단이 옳다.** ① 성공만 세는 것 — 서버 `auth.log` 44MB 에 `Accepted (password\|keyboard-interactive)` **0건**, 실패 8.7만건을 세면 첫 실행에 폭발한다. ② 건수만 보내는 것 — 감시가 같은 채팅방으로 재유출하는 것을 막는다. ③ 마지막 바이트부터 읽기 — 서버 `sshpw_off=44,045,945` vs 파일 44,049,707 로 정상 추적 중. ④ 로테이션 — 주간 회전 + `delaycompress`(`.1` 평문 · `.2.gz`)라 `readable "$AUTH_LOG.1"` 가 성립하고, 회전 시 새 파일 전량 + 옛 파일 꼬리를 세는 분기가 맞다. **SR 코드를 그대로 안 쓰고 고친 판단은 정당하다** |
| **CR40-3 셸 테스트 49건** | 신설 자체가 옳다. 변이 6종 중 내가 올바로 적용한 **5종(M-1·M-2·M-3·M-4·M-5) 전부 죽고**, M-6 도 별도 재현으로 죽는다(아래). 다만 **7번째가 빠져나간다** → `CR41-3` |
| **CR40-4 `scrub`** | 선 자체는 방어 가능하나 **문서가 또 넓다** → `CR41-4` |
| **LC_ALL 진단** | **조치는 옳고 범위도 옳다. 진단 문장은 틀렸다** → `CR41-5` |

#### 3-1. 변이 6종 — 내가 다시 심었다

| 변이 | 결과 |
|---|:--:|
| M-1 기대월 공식 옛것으로 | **죽음** (T2 3건) |
| M-2 `check_logperm` fail-open 복귀 | **죽음** (T4/T5 6건) |
| M-3 `market-index.sh` 자기 단언 삭제 | **죽음** (T3 1건) |
| M-4 5xx 기준값 0 덮어쓰기 | **죽음** (T4 1건) |
| M-5 `scrub` 쉼표 규칙 제거 | **죽음** (T7 1건) — ※ 1차 시도는 **내 편집이 no-op** 이었다. 정정해 적는다 |
| M-6 SSH 정규식이 실패까지 셈 | **죽음** — 격리 재현으로 `sshpw_alert 0 -> 1`(누적 0건 → 1건) |

---

### 4. 지적 사항

| ID | 심각도 | 내용 | 수정 제안 |
|---|---|---|---|
| **CR41-1** | **high · 차단** | **백엔드 스위트가 붉다.** `tests/test_script_hygiene.py::test_docs_and_config_do_not_contain_secret_values` 가 `docs/03-build/security-review-log.md:9383-9384` 를 적발한다. 두 줄은 **이번 작업본에서 추가된 블록**(`git diff -U0` 훅 `@@ -9194,0 +9195,688 @@`) 안이고, CR-040 시점에는 `failures 0` 이었다. 값은 **진짜 비밀이 아니다** — 프로그램으로 `.env` 3개 키와 대조해 **일치 0** 을 확인했고 형태도 `1234…`·`aBcD…` 다. 그러나 ① 저장소의 **자기 관문이 붉고**(커밋 훅이 막는다) ② *"1,466 유지"* 주장이 **사실과 다르다**(1,465 passed · 1 failed) | 그 두 줄의 예시값을 `<예시>` 같은 마스킹 표기로 바꾸거나 `_SYNTHETIC` 이 받는 형태로 적을 것. 검증 벡터의 **정본은 이미 `monitor-selftest.sh` T7 에 있으므로** 로그는 그것을 가리키기만 해도 된다. **PASS 조건: `python -m pytest -q` 그린** |
| **CR41-2** | **high · 차단** | **조치 ②(1차 단언은 배치가 진다)가 실제로는 한 달 헐겁다.** `market-index.sh:94` 는 `market_expected_ym` 을 **인자 없이**(=now) 부르는데, 배치가 도는 시각은 **1일 04:10** 이라 `MARKET_BATCH_READY=06:00` 유예 분기에 걸려 `base` 가 **지난달로 되돌아간다.** 결과: 14회 중 **13회에서 EXPECTED 가 자기 REF 보다 한 달 뒤처진다**(실측: 2026-09-01 REF 2026-07 vs EXPECTED 2026-06 …). 즉 **원본 부족으로 완결월이 한 달 안 올라간 상태**(fail 문구가 스스로 적은 바로 그 실패)가 **rc=0 으로 통과**하고, `job-run.sh` 는 성공으로 기록한다(`last_success_at` 갱신 · `clear_alert job_market-index`). 감시가 5시간 뒤 09:05 에 잡기는 하나 그때 나가는 문구는 *"매월 1일 배치가 안 돌았거나 실패했다"* — **또 거짓이다**(배치는 돌았고 성공을 보고했다). `OPEN` 검사는 이 방향을 못 잡는다(그건 앞선 쪽 전용). selftest T3 은 **비교문이 있는지만** 보고 값이 맞는지는 안 본다 | 배치 안에서는 **배치 주기 시각으로** 부를 것 — `EXPECTED=$(market_expected_ym "$(date -d "$(date +%Y-%m-01) $MARKET_BATCH_READY" +%s)")`. 실측으로 5개월(2026-09·10 / 2027-01·03·04) 전부 REF 와 정확히 일치함을 확인했다. **그리고 selftest 에 "1일 04:10 에 배치의 EXPECTED == 그 배치가 만든 REF" 검사를 추가할 것** — 지금 없는 그 검사가 이걸 놓쳤다 |
| **CR41-3** | med | **7번째 변이가 빠져나간다.** `monitor.sh:484` 의 `blind_add`(SSH) **한 줄만 지우면** 자체검사는 **49/49 그대로 통과**한다. 그런데 *"다른 로그는 멀쩡하고 `auth.log` 만 사라진"* 상황을 만들어 보면 **현재 코드는 `logblind` 1통, 변이는 0통**이다(재현함). 즉 **SR-036R 이 요구한 T2 트립와이어가 조용히 눈이 멀고**, 남는 것은 사람이 읽어야 하는 일일 요약 한 줄뿐이다. 원인은 T4 가 ① 대상을 **전부** 지운 시나리오만 쓰고(다른 `blind_add` 가 대신 울어 준다) ② SSH 만은 **경보가 아니라 요약 문구**로 검사하기 때문 | T4 에 **묶음별 단독 소실** 시나리오를 넣을 것(`auth.log` 만 · `error.log` 만 · 앱로그만). 이미 nginx/앱 묶음은 그렇게 나눠 놓았으니 SSH 도 같은 대접을 하면 된다 |
| **CR41-4** | med | **`scrub` 의 선은 방어 가능하지만 문서가 또 넓다.** 실측으로 통과해 버리는 금액 형식: `50000000원`(5천만·8자리) · `3500000원`(7자리) · `95000000` · `5,000만원` · **`102,656만원`**(국토부 실거래가가 쓰는 **만원 단위** 형식) · `4.2억` · `10억 2656만원` · `1.02656e+09` · `{"cash_krw": 50000000}` · `X-Cash: 50000000`. `monitoring.md §2` 의 근거 문장 *"금액은 이 시스템에서 항상 백만 이상이고, 쉼표를 붙이는 것은 금액뿐"* 은 성립하지 않는다 — **백만은 7자리**라 규칙①(9자리)에 안 걸리고, 쉼표 1묶음 금액(`950,000원`)도 안 걸린다. **지금 살아 있는 유출 경로는 없다**(scrub 에 닿는 것은 감시 요약과 배치의 `실패:` 줄뿐이고 둘 다 금액을 담지 않는다 — 확인함). 그래도 이건 CR40-4 와 **같은 종류의 과장**이 문서에 다시 남은 것이다 | 자릿수 대신 **금액 토큰 인접**으로 걸 것(`원\|만원\|억\|krw\|cash\|price\|budget\|amount` 앞뒤의 수) — `1048576`·`288` 은 그대로 살아남고 위 10종이 전부 잡힌다. 아니면 문서 문장을 실제 선까지 좁힐 것 |
| **CR41-5** | med | **LC_ALL 진단이 사실과 다르다(조치는 옳다).** 재현: 줄이 **정상 UTF-8** 이면 `grep 'A.*B'` 는 사이에 한글이 있어도 `C.UTF-8`·`en_US.UTF-8` 에서 **매치한다**(1/1). 매치가 깨지는 것은 **유효하지 않은 바이트가 섞였을 때**뿐이다(`C.UTF-8` 0 · `LC_ALL=C` 1). 그런데 `monitoring.md §8-3b`·`monitor.sh:30-33`·`monitor-selftest.sh:22-24` 는 **"한글이 끼면 매치하지 않는다"** 를 머리 문장으로 적고 진짜 원인(유효하지 않은 바이트)은 곁가지로 적는다 → 다음 사람이 원인을 잘못 알고 되돌릴 수 있다. **조치 범위는 옳다**: `monitor.sh` 만 `export`, `scrub()`·`job-run.sh` 는 명령 단위(파이썬 배치 출력 인코딩 보존) — 그리고 새 `scrub` 규칙은 C/C.UTF-8/en_US.UTF-8 **세 로케일에서 결과가 동일**함을 확인했다. 다른 스크립트: `market-index.sh` 는 `.*` grep 이 없고 `[[ "$REF" < "$EXPECTED" ]]` 도 세 로케일 동일 → **안전**. `preflight.sh`·`pause/resume-itsmine.sh` 도 해당 없음 | 세 곳의 머리 문장을 *"유효하지 않은 바이트가 섞인 줄에서 UTF-8 로케일 정규식이 무력해진다"* 로 정정 |
| **CR41-6** | low | **자체검사가 간헐적으로 거짓 FAIL 을 낸다.** 변이 시험 하네스에서 연속 실행할 때 **8회 중 2회** 엉뚱한 검사가 붉었다 — 무변이 기준선이 `통과 48 · 실패 1`(T6 첫 검사)로 나온 적이 있고, M-2 회차에서는 T5/T6 3건이 추가로 붉었다. 단독 실행에서는 **재현 안 됨**(기본값 1회 + `SELFTEST_MONTHS=1` 4회 = 5/5 전부 `49 · 0 · 2`), 해당 시나리오를 격리해 돌려도 결정적(5/5, 2/2)이다. 원인 미상 | **오탐도 결함**이라는 이 프로젝트의 기준이 관문 자신에게도 적용된다. CI 에 걸기 전에 원인을 붙잡을 것(상태 디렉터리 재사용·프로세스 경합 의심) |
| **CR41-7** | low | `check_sshlogin` 이 `kv_set sshpw_off "$size"` 에 **읽기 전에 잰 크기**를 쓴다. `stat` 과 `tail` 사이에 붙은 줄은 이번에도 세고 다음에도 센다 → **실제 사건일 때만 중복 경보**. 무해하지만 기록해 둔다 | 읽은 뒤 크기를 다시 재거나, `tail` 출력 바이트 수로 오프셋을 전진시킬 것 |
| **CR41-8** | low | 서버 `kv/*` 파일이 **0644**(`-rw-r--r--`)다. 상위 디렉터리가 `0700 root` 라 실질 노출은 없고 내용도 epoch·컨테이너 ID 뿐이지만, `monitor-lib.sh` 는 **디렉터리만** `chmod 700` 하고 파일은 umask 에 맡긴다 | `kv_set` 뒤 `chmod 600`, 또는 스크립트 상단에서 `umask 077` |

---

### 5. 서버 반영 — 읽기만 했다

* **sha256 5/5 일치** — `monitor.sh 3258e581…` · `monitor-lib.sh 77e720cc…` · `job-run.sh 6798a2fa…` ·
  `market-index.sh f691ffa2…` · `monitor-selftest.sh 47cb67c8…` (로컬 원본과 전건 동일).
* **크론** — 우리 3줄(`10 4 1 * *` 배치 래핑 · `*/5` fast · `5 9` daily), 동거 서비스 5줄은
  그대로 있다(recostock · civicniche · adsense 3종). 우리 줄이 남의 줄을 건드리지 않았다.
* 배포 후(09:56~) `*/5` 감시가 정상 동작 중이고 **경보 0건 · 미해소 경보 0건**.
* ⚠️ **실패 주입은 하지 않았다** — 5분 크론이 돌고 있어 주입하면 사용자 텔레그램으로 간다.
* 자원 실측(13.3MiB · 0.36초)은 **판정하지 않는다**(운영 실행이 필요하고, 읽기 전용 원칙에 걸린다).

---

### 6. 판정 사유

**고치라고 한 두 가지는 고쳐졌고, 나는 그것을 담당자 도구가 아니라 내 도구로 확인했다.**
CR40-1 은 4년 11,688 평가에서 오탐 0 이고 옛 공식의 35일과 정확히 대비된다. 운영 로그가
*"그날 실제로 2통 갔다"* 를 증명한다. CR40-2 는 **경보를 켜 놓고** 돌려 거짓 해소가 0통임을
봤고, 반대쪽(정상 복귀 시 실제 해소)도 함께 봤다. 판단 ③ 은 숫자로 옳다.

**그럼에도 차단하는 이유는 둘 다 결과로 정당화된다.**
`CR41-1` 은 **관문이 붉다** — 이 프로젝트는 리뷰 게이트가 하드 스톱이고 훅이 커밋을 막는다.
값이 진짜 비밀이 아니라는 것까지 확인했으니 **고치는 데는 두 줄이면 된다.**
`CR41-2` 는 이번 라운드가 **스스로 약속한 조치 ②가 13/14 회 무력**하다는 것이고,
그 실패 모드는 *"배치는 성공을 보고했는데 기준월이 안 올라간"* — 정확히 CR-040 이
막으라고 한 조용한 실패다. 게다가 뒤늦게 나가는 감시 문구가 **또 거짓**이다.
둘 다 몇 줄짜리 수정이고, `CR41-2` 는 selftest 검사 한 줄을 같이 넣어야 재유입이 막힌다.

**좋았던 것도 분명히 적는다.** `market_expected_ym()` 에 **기준 시각을 인자로 넣은 것**,
**경보를 미리 켜 놓고 fail-open 을 시험한 것**, **앞선 방향은 일부러 단언하지 않은 것**,
**SR 이 준 코드를 그대로 쓰지 않고 성공만 세도록 고친 것** — 넷 다 재 보고 나서야 쓸 수 있는
판단이고, 내가 다시 재도 결론이 같았다. 남은 것은 그 기준을 **자기 배치의 단언 한 줄**과
**자기 로그의 예시 두 줄**에도 적용하는 일이다.

---

### 리뷰 위생

* 변이 7종 전부 원복 — `grep -c 'MUT-' deploy/*.sh` **전부 0**, `diff` 로 원본과 동일 확인.
  M-5 는 1차 편집이 no-op 이었음을 발견해 **다시 적용해 재판정**했고, 그 사실을 위에 남겼다.
* 감시 실행은 **전부 로컬 격리**(`RE_MON_STATE`/`RE_MON_LOG` 임시 경로 · `RE_MON_DRY_RUN=1` ·
  URL 은 닫힌 포트 127.0.0.1:9). 사용자에게 간 알림 **0통**.
* 서버는 **읽기 전용 명령만**(sha256sum · crontab -l · ls -l · cat status · grep 로그).
  설정 변경·재시작·실패 주입 **없음**.
* 날짜·공식 검증은 스크래치패드 스크립트로만 했다 — 저장소에 추가한 파일 **0건**
  (`git status --porcelain` 이 리뷰 전과 동일).
* ⚠️ 한글 테스트명으로 `pytest -k` 는 쓰지 않았다. 전 스위트 1회 + 파일 단위만 썼다.

---

## CR-042 · 2026-08-01 · CR-041 차단 2건 재검증 (범위 `deploy/**` · `docs/**`)

**판정: FAIL** — 차단 **3건**. **CR41-1 · CR41-2 는 둘 다 해소됐다**(내 도구로 재현했다).
차단은 전부 **이번 라운드가 계속 쫓던 계열 — "감시가 거짓말하는 자리"** 에서 나왔고,
셋 다 내가 격리 재현해 붙잡았다. 그중 하나는 **담당자가 스스로 보고한 판단의 볼륨 추정이
20배 틀렸다**는 것이고, 하나는 **9번째 변이**다.

> 이 라운드의 작업 질은 CR-041 때보다 더 높다. 특히 `market_batch_epoch`/`batch_expected_ym`
> 를 함수로 뽑아 selftest 가 **eval 로 그대로 돌려 값을 검증**하게 만든 것, `printf|grep -q`
> 의 파이프라인 결함을 **부정형에서 결함을 놓친다**는 데까지 밀고 간 것, 그리고 8번째 변이를
> **스스로 찾아 T5 에 심은 것** — 셋 다 내가 다시 재도 결론이 같았다. 그래서 더더욱,
> 그 기준이 아직 안 닿은 세 자리를 적는다.

---

### 0. 실행 검증 — **주장 전건 일치**

```
grep -rn "MUT-" deploy/                          시작 0 · 종료 0
bash -n deploy/*.sh                              8파일 전부 exit 0
bash deploy/monitor-selftest.sh                  통과 81 · 실패 0 · 건너뜀 2 · RC=0   (주장 일치)
backend python -m pytest -q -p no:warnings       tests=1569 · failures=0 · errors=0 · skipped=103
                                                  → **1,466 passed / 0 failed** (junit XML 로 확인)
git diff --stat                                  deploy/docs 만 · frontend `git status` 비어 있음
```

건너뜀 2건은 둘 다 **윈도우 파일시스템에서 `chmod` 가 안 먹어서**다(T5 권한 대조군 · T9 0640
실측). 리눅스에서는 실행된다 — 스킵 사유가 코드가 아니라 환경임을 selftest 가 스스로 적는다.

---

### 1. `CR41-1` 관문이 붉었던 것 — **해소. 검사·증거 양쪽 다 확인했다**

| 확인 | 결과 |
|---|---|
| 스위트 그린 | `failures=0 errors=0` · 1,466 passed (위) |
| **검사 미수정** | `git status --short backend/tests/test_script_hygiene.py` **비어 있음** — 관문에 손대지 않았다 |
| **관문이 여전히 잡는가** | 모듈을 그대로 import 해 `_SECRET_ASSIGN`/`_PLACEHOLDER`/`_MASKED`/`_SYNTHETIC` 를 직접 돌렸다. 마스킹 문구가 적은 **형태 그대로 값을 복원**(`1234567890:AAHq…36자`, `aBcD…%2F…%3D`)해 먹이니 **둘 다 CAUGHT**. 현재 두 줄은 `_MASKED` 로 통과 |
| **증거가 지워졌는가** | 안 지워졌다. `<봇토큰 형태 · 숫자10자리:영숫자32자>` · `<URL인코딩 키 형태 · 영숫자 + %2F %3D>` — **무엇을 시험했는지가 형태로 남아 있고**, 검증 벡터 정본은 `monitor-selftest.sh` T7 (15종) 에 있다 |

임시 파일로 가짜 비밀을 심어 관문이 반응하는지 본 것도 옳은 절차다. 다만 그건 **관문이
동작한다**는 증명이고, 위의 "복원해서 먹여 본다"가 **이 두 줄이 왜 걸렸는지**의 증명이다.
둘 다 있어야 완결이라 내가 후자를 채웠다.

---

### 2. `CR41-2` 배치 단언이 한 달 헐거웠던 것 — **해소. 숫자가 주장과 정확히 같다**

담당자 도구(selftest)를 쓰지 않고, `market-index.sh` 에서 세 함수를 **내가 따로 뽑아**
파이썬 완결 규칙(`open_ym = ym_of(as_of − 30일)`, 완결은 그보다 작은 달)을 독립 재구현해
대조했다.

| 항목 | 결과 | 주장 |
|---|---|---|
| 1일 04:10 배치 · **30개월** EXPECTED vs 자기 REF | **불일치 0** | 일치 |
| 같은 30개월을 **인자 없이**(옛 동작) | **28개월 어긋남** | 28/30 — 일치 |
| 월중 15일 + **말일** 수동 실행 **70회** | **거짓실패 0** | 70회 0 — 일치 |

#### 2-1. 부수 발견 — **T3 자체가 틀렸다는 주장도 사실이다**

옛 방식(`grep -A2 'if [[ "$REF" < "$EXPECTED" ]]; then' | grep 'fail "'`)을 **현재 파일에
그대로 적용**해 봤다 → `fail "` **0건**. 실제 간격은 **10줄**이다. 즉 그 검사는 코드가 아니라
**줄 간격**을 보고 있었고, 주석 두 줄만 끼워도 깨진다. 지금은 `${MI#*…}`/`${MI%%…}` 로
**비교 블록 전체**를 잘라 `fail "` 를 찾는다 — 파이프라인도 없다.

#### 2-2. **"함수로 뽑아 eval" 이 검사를 위해 코드 구조를 바꾼 것** — 대가를 재 봤다

* **얻은 것은 실재한다.** `grep` 만으로는 `batch_expected_ym` 안에서 인자를 빼는 변이를
  못 본다(비교문은 그대로 있으니까). T3b 는 `eval` 로 뽑아 **값**을 18개월 돌린다 —
  그리고 `b_naive` 검사(240행)가 *"기준 시각을 안 고정하면 몇 개월이 어긋나는가"* 를
  같이 확인해서, **이 검사가 아무것도 못 붙잡는 상태가 되면 그것도 FAIL** 이다. 드물게 보는
  좋은 설계다(검사의 검사).
* **치른 값도 실재한다.** ① `market-index.sh` 가 날짜 함수 3개를 갖게 됐고, ② selftest 가
  **소스 텍스트 모양**에 의존한다(`ext()` 는 `^이름() {$` … `^}$` 를 요구한다).
  `batch_expected_ym () {` 처럼 공백 하나만 넣어도 추출이 깨진다.
* **다만 그 취약성은 fail-closed 다** — 217~218행이 `declare -f` 로 추출 실패를 확인해
  **ng 로 떨어뜨린다**(조용히 건너뛰지 않는다). 그래서 **대가를 치를 값어치가 있다**고 본다.
  리뷰어 수정안을 그대로 쓰지 않은 판단은 정당하다.

---

### 3. 트립와이어(SR37-1 · CR41-3) — **5케이스 재현했다. 그리고 6번째를 찾았다**

#### 3-1. 격리 재현 (전부 `RE_MON_DRY_RUN=1` · 임시 상태디렉터리 · 서버 무접촉)

| 케이스 | 결과 |
|---|---|
| (a) 정상 회전 직전 구간 침입 | selftest T6 통과 |
| (b) `.1.gz` 만 남음 | 통과 (압축본을 풀어 **세는 것**까지 요구한다) |
| (c) `: > auth.log` | `authshrink` + `logblind` |
| **(c2)** 옛 `.1`(500줄) > off 인 채 truncate | **`authshrink` + `logblind`** — 내가 따로 만들어 확인했다. 리뷰어 3줄 수정안(inode 만)이라면 회전으로 오인했을 자리가 맞다 |
| (d) 회전 뒤 옛 오프셋 초과 성장 | T6 통과 |
| **대조군 (e) 정상 증가 · (f) 평범한 로테이션** | **둘 다 완전 침묵** — 매주 회전마다 울지 않는다 |

#### 3-2. inode 재사용 주장 — **확인 불가(반증도 아님)**

로컬은 NTFS/Git-Bash 라 삭제→재생성 **30/30 전부 다른 번호**가 나왔다. ext4 서버에서만
확인 가능한 주장이고, 서버는 읽기 전용 원칙이라 시험하지 않았다. → **판정 보류.**
다만 결론(“inode 만으로는 부족하다”)은 **어느 쪽이든 옳다** — 아래 3-3 이 그 이유다.

#### 3-3. ⛔ **9번째 변이 — 변이가 아니라 지금 코드에 있는 구멍이다** → `CR42-2`

담당자는 mtime 증거를 **`size < off` 경로에만** 붙였다(`monitor.sh:544-545`).
**inode 가 바뀐 경로(542행)는 증거 없이 곧바로 `rotated`** 다.
그래서 침입자가 `: >` 대신 **`rm auth.log && touch auth.log`** 를 쓰면 판정이 뒤집힌다.
실제로 만들어 돌렸다:

```
(h) rm+재생성 · 낡은 .1(500줄) > off(40줄)   -> <완전 침묵>
    요약 줄: "SSH     : 비밀번호 로그인 성공 이번 구간 0건 (기대 0)"
(l) 서버형 delaycompress(.1 평문 800줄 + .2.gz) · rm+재생성 -> <완전 침묵>
(c2) 같은 상황인데 : > 로 비우기(inode 유지)   ->  authshrink logblind   ← 잡는다
(j) rm+재생성 · 낡은 .1(10줄) < off(200줄)     ->  authshrink logblind   ← 잡는다
(k) rm+재생성 · 회전본 없음                    ->  authshrink logblind   ← 잡는다
(m) 대조군 · 평범한 회전                       ->  침묵 (정상)
```

`Accepted password` 한 줄이 **소리 없이 사라지고**, 그 자리에 **"이번 구간 0건(기대 0)"**
이라는 **적극적인 무사고 선언**이 남는다. 이 파일이 자기 머리말에 적은 원칙
(*"회전본으로 설명되지 않으면 조용히 넘기지 않는다. 못 본 것은 못 본 것이다"* — 495행)이
정확히 뒤집힌 자리다. 그리고 이건 **위험수용 SR36-1 을 지탱하는 유일한 기계**다.

---

### 4. `CR41-6` 동시 실행 거짓 FAIL — **진단이 맞다. 게다가 주장보다 강하다**

담당자는 *"간헐적"* 이라고 적었는데, 내가 재 보니 **결정적으로 재현된다.**

```
입력 12,120,212바이트(패턴은 첫 줄)
  옛 방식  printf '%s' "$BIG" | grep -q 패턴   (set -o pipefail)  → 40회 중 rc!=0 = 40회
           마지막 rc=141 · PIPESTATUS=(141 0)          ← 141 = 128+13 SIGPIPE
  새 방식  case 기반 has()                                        → 40회 중 실패 = 0회
```

원인은 담당자가 적은 그대로다: `grep -q` 가 첫 매치에서 즉시 끝나 **쓰는 쪽(printf)이
SIGPIPE 로 죽고**, `pipefail` 이 그것을 파이프라인 실패로 본다. 그리고 **부정형에서 더
나쁘다**는 지적도 실증했다 —

```
if printf '%s' "$BAD" | grep -q 'THIS_IS_A_DEFECT'; then …  → **결함을 놓쳤다**
if has "$BAD" 'THIS_IS_A_DEFECT'; then …                    → 결함 발견
```

동시 실행에서만 붉었던 이유(부하로 출력 크기·타이밍이 달라짐)도 이 메커니즘과 모순이 없다.
`grep -nE '^\s*(el)?if .*\|' deploy/monitor-selftest.sh` = **0건** — 조건 자리의 파이프라인이
실제로 전부 없어졌다. **진단·수정 둘 다 옳다.** (다만 `monitor.sh` 에 한 곳 남았다 → `CR42-4`)

---

### 5. ⚠️ 담당자가 스스로 보고한 것 — **판정: 절반은 옳고, 볼륨 추정이 20배 틀렸다** → `CR42-1`

**옳은 부분(내가 확인했다).**
`_complete_flags` 의 docstring(`timeadjust.py:262-266`)이 스스로 적어 둔 대로 건수 검사는
**거짓 미완결**을 낸다(*"운영 실측: 서울 시도 2025-07·08·11·12"*). 그 달이 끼면 `REF` 가
안 올라가는 것은 **사실**이고, 적정가 밴드의 시점 보정이 그만큼 낡는 것도 사실이다.
**단언을 느슨하게 두지 않은 판단은 옳다.** `행없음`/`(미완결)` 구분도 옳은 방향이다.

**틀린 부분.** `monitoring.md` 는 *"월 1회 배치라 최악이어도 **연 2~3통**"* 이라고 적는다.
그런데 같은 문단의 근거 ②가 *"감시(`--daily` #11)는 **이미 같은 비교**를 하고 있다"* 이다 —
**둘을 같은 기준으로 맞췄으므로, 그 달에는 감시도 매일 운다.** 감시의 쿨다운은 86400 이고
`--daily` 는 하루 한 번(`5 9 * * *`) 돈다 → **하루 1통**이다.

담당자 실측 전제(`scope='sido'` 완결 0 = 2025-07·2025-08)를 그대로 넣어 `market_expected_ym`
을 이식해 14개월 창을 전수로 돌렸다:

| | 결과 |
|---|---|
| `market-index.sh` 자기 단언 실패 | **2회** (2025-09: REF 2025-06 < 기대 2025-07 · 2025-10: < 2025-08) |
| **`check_db_structure` 일일 경보** | **61일** — 2025-09 **30일** + 2025-10 **31일** (평가 426일) |
| 사용자에게 가는 텔레그램 | 배치 실패 2통 + **일일 경보 61통 = 63통** |
| 그 기간 `job_market-index.active` | **다음 달 배치까지 미해소** → 일일 요약 머리말이 계속 *"미해소 N건"* |

**CR-040 이 차단한 옛 오탐이 연 35일이었다. 이건 연 61일이다.**
같은 잣대를 대면 이쪽이 더 크다. 그리고 담당자 자신이 적었다 — **"다음 배치(2026-09-01)가
이 사유로 실패할 수 있다"**. 한 달 남았다.

**그래서 오탐인가 참인가.** 사실 관계로는 **참**이다(완결월은 실제로 안 올라간다).
문구도 거짓이 아니다(*"안 돌았거나 실패했다"* — 실제로 실패했다). 결함은 **참/거짓이 아니라
전달**에 있다: ① 배치가 이미 한 통 보낸 **같은 사실**을 감시가 30일 동안 매일 다시 보낸다
② 그 기간 내내 대응할 수 있는 것이 **없다**(근본 원인은 `_complete_flags` — 범위 밖)
③ 그 결과 사람은 `dbstruct` 경보를 무시하게 되고, **그러면 016 컬럼 누락·시장지수 0행 같은
진짜 신호가 같은 경보 키에 묻힌다**(같은 `raise_alert dbstruct` 를 쓴다).
이 프로젝트가 CR-040 에서 차단한 피해와 **같은 피해**다. → **차단.**

---

### 6. 그 외 판정

| 항목 | 판정 |
|---|---|
| **CR41-4 scrub** | **수용.** 실측으로 지울 것 10종 전부 지워지고(`50000000원`·`3500000원`·`5,000만원`·`102,656만원`·`4.2억`·`850,000원`·`{"cash_krw": …}`·`X-Cash: …` 등), 남길 것 6종(`1048576`·`288`·`12,345`·`44049707`·`0.36`·`2026-06`) 전부 살아 있다. **자릿수를 8로 안 내린 판단이 옳다** — `auth.log 44049707` 이 T2 판정의 근거라는 근거도 사실이다. 못 막는 2형태(`95000000`·`1.02656e+09`)가 `monitoring.md:110-111` 과 `monitor-lib.sh:93-97` 과 T7 에 **셋 다 같은 말로** 적혀 있다. CR40-4/CR41-4 가 지적한 "문서가 방어를 과장한다"가 이번엔 없다 |
| **CR41-5 로케일** | **수용.** `monitor.sh:33` · `monitor-lib.sh:100` · `monitor-selftest.sh:24` · `monitoring.md:341-352` 네 곳 모두 머리 문장이 *"유효하지 않은 바이트"* 로 정정됐고, 옛 진단이 틀렸다는 것까지 적었다. 코드 범위(`monitor.sh` 만 `export`)는 그대로 — 옳다 |
| **CR41-7 `head -c` 절단** | **수용.** T6 이 ① 행동으로(같은 로그인 두 번 안 셈: 경보 1→1) ② 오프셋==파일크기 ③ 구조(`head -c "$((size - off))"`) 셋을 본다. 그리고 551-554행이 **"이건 약한 검사다"** 를 명시한다. 약한 것을 강한 척하지 않은 것이 이 항목의 핵심이고, 그게 지켜졌다 |
| **8번째 변이(`check_logblind` clear)** | **수용 · 확인.** `monitor-selftest.sh:376` 이 `logblind` 를 **켜 놓고 시작**해 `385-389` 에서 `ALERT-CLEARED logblind` + `.active` 삭제를 요구한다. 그 한 줄을 지우면 죽는다. **스스로 찾아 심은 것이 맞다** |
| **CR41-3 T4 묶음별 단독 소실** | **수용.** `s4a`(auth 만) · `s4b`(error 만) · `s4c`(nginx 묶음만) + **`s4d` 전부 정상 → 경보 없음**. 마지막 것이 없으면 앞 세 개가 "무조건 참"이 될 수 있다는 지적이 정확히 반영됐고, 한계(logleak/api5xx 는 같은 파일이라 분리 불가)를 329-330행에 적었다 |
| **CR41-8 / SR37-4** | **수용.** `kv_set` → `chmod 600`(`monitor-lib.sh:66`) · `raise_alert` 의 `.active`/`.sent` → `chmod 600`(215·225) · `job-run.sh` `STATUS` → 600(91) · selftest `trap … EXIT INT TERM HUP`(32) |

---

### 7. 지적 사항

| ID | 심각도 | 내용 | 수정 제안 |
|---|---|---|---|
| **CR42-1** | **high · 차단** | **같은 사실을 감시가 하루 한 통씩 최대 61일 보낸다.** 위 §5. 배치와 감시가 같은 비교(`REF < expected`)를 하게 되면서, `scope='sido'` 완결 0인 달이 끼면 `market-index.sh` 가 rc=1(1통) → `job_market-index.active` 가 한 달 유지되고, 별도로 `check_db_structure`(`monitor.sh:740-745`)가 **매일** `raise_alert dbstruct 86400` 을 낸다. 실측 전제(2025-07·08)로 전수 계산: **61일 · 63통.** 대응 수단이 없고(근본 원인 `_complete_flags` 는 범위 밖), 같은 경보 키를 016 컬럼 누락·시장지수 0행이 함께 쓰므로 **진짜 신호가 묻힌다.** CR-040 이 차단한 것이 연 35일이었다 — 이건 61일이다. `monitoring.md:392` 의 *"연 2~3통"* 은 사실과 다르다 | 단언은 그대로 두고 **중복만 없앤다**: `check_db_structure` 의 기준월 항목을 `dbstruct` 에서 떼어 **별도 키**(예: `marketstale`)로 옮기고, `$JOBS/market-index.status` 를 읽어 **이번 달 배치가 실제로 돌았고 그 사실을 이미 알렸으면 발송을 건너뛴다**(= 감시는 *"배치가 아예 안 돌아 아무 신호도 없는 경우"* 만 운다 — 683행이 적은 원래 목적 그대로다). 그러면 61통 → 0통이고, 배치 1통은 남는다. 배치 쪽은 선택: `행없음`(원본 미유입)은 rc=1 유지, `(미완결)`(표본 부족)은 rc=0 + 월 1통짜리 별도 경고로 내려 `last_success_at` 이 한 달 굳는 것도 막을 수 있다. **그리고 selftest 에 "완결 0인 달이 낀 상태에서 30일 돌려 발송 통수" 검사를 넣을 것** — 지금 그 검사가 없어서 이 볼륨을 아무도 못 셌다 |
| **CR42-2** | **high · 차단** | **9번째 변이 — 트립와이어가 `rm`+재생성에 눈이 먼다.** 위 §3-3. `monitor.sh:542` 는 `ino != prev_ino` 면 **증거 없이** `how=rotated` 로 확정한다. mtime 증거(`rot_evidence`)는 `size < off` 경로(544-545)에만 붙었다. 그래서 낡은 `.1` 이 오프셋보다 큰 채로 남아 있으면(= 서버의 주간 `delaycompress` 배치에서 **회전 직후 한동안 항상 그렇다**) `rm auth.log && touch auth.log` 가 **완전 침묵**으로 통과하고, 요약에는 *"이번 구간 0건(기대 0)"* 이라는 무사고 선언이 남는다(재현: (h)·(l)). `: >` 를 쓰는 (c2) 는 잡히는데 `rm` 을 쓰면 안 잡힌다 — **담당자 자신의 논리가 한쪽에만 적용됐다** | 542행에서도 **"이 회전본이 우리가 추적하던 그 파일인가"** 를 증명할 것: `old_ino=$(stat -c %i "$AUTH_LOG.1" 2>/dev/null)` 를 재서 `[ "$old_ino" = "$prev_ino" ]`(rename 기반 logrotate 는 inode 를 보존한다) **또는** `[ "$rot_evidence" = 1 ]`(copytruncate·compress 대비) 일 때만 `rotated`, 아니면 새 상태 `replaced` 로 보내 `blind_add` + `raise_alert authshrink` 를 태울 것. 기존 (a)(b)(d)(f) 전부와 호환된다(확인함 — (a)/(d)/(f) 는 `.1` 이 prev_ino 를 물려받고, (b) 는 `.1.gz` mtime 이 새것이다). **selftest T6 에 (h)·(l) 두 케이스를 추가할 것** |
| **CR42-3** | **high · 차단** | **`check_cert` 가 fail-open 이고 거짓 해소까지 보낸다** — CR40-2 가 로그 검사에서 차단한 바로 그 결함이 인증서 검사에 그대로 남아 있다. `monitor.sh:655-671` 은 `$LE_DIR` 하위에 `cert.pem` 이 하나도 없으면(경로 변경·certbot 재설치·openssl 부재) 루프를 한 번도 안 돌고 `worst=9999` 로 내려와 **`clear_alert cert`** 를 부른다. 재현(격리·DRY-RUN, `cert.active` 무장 후 빈 `LE_DIR`): `ALERT-CLEARED cert :: 인증서 여유 회복 (최단  9999일)` → **`.active` 삭제 · "해소" 통보 발송 · 이름은 빈 문자열 · 9999일은 존재하지 않는 값**. 요약 줄도 `인증서  : (임계 21일)` 로 빈 목록이다. `blind_add` 도 안 해서 `logblind` 로도 안 걸린다. 이 검사의 주석 자체가 *"우리 nginx 설정이 나쁘면 **동거 서비스 갱신이 실패**한다"* 고 적은, 남의 서비스까지 걸린 자리다. selftest 에 인증서 시나리오는 **0건**이다 | `check_cert` 에 대상 수 카운터를 두고 **0개면** ① `add "인증서  : 검사 못 함 (대상 0개)"` ② `blind_add "인증서 대상 0개($LE_DIR)"` ③ `clear_alert` **금지** — 로그 검사 3종과 정확히 같은 형태로 맞출 것(코드는 이미 그 자리에 있다). **T5 에 "LE_DIR 비었을 때 cert.active 가 살아남는가" 대조군을 넣을 것**(양성 대조군 = 정상 인증서 1개면 실제로 해소되는가, 도 함께) |
| **CR42-4** | low | `monitor.sh:185` — `elif ! printf '%s' "$ct" \| grep -qi javascript; then` 가 **조건 자리의 파이프라인**이고, `monitor.sh` 는 `set -uo pipefail`(24행) 아래에서 돈다. CR41-6 이 selftest 에서 전부 걷어낸 그 형태이고, **부정형**이라 피해가 나쁜 쪽이다. 지금은 안 터진다 — `$ct` 는 Content-Type 한 줄(수십 바이트)이라 `printf` 가 `grep` 보다 먼저 끝나 SIGPIPE 가 안 난다(파이프 버퍼 64KiB). 그래도 *"조건 자리의 파이프라인을 전부 제거했다"* 는 이번 라운드의 선언과 어긋난 채 남아 있다 | `case "$ct" in *javascript*\|*JAVASCRIPT*) ;; *) fails=1 ;; esac` — selftest 의 `has()` 와 같은 방식 |
| **CR42-5** | low | `check_api5xx` 에도 **회전 사각지대**가 남았다. `monitor.sh:458` 은 `cur < prev` 를 무조건 리셋으로 보고 `delta="$cur"` 로 간다 → 마지막 표본 이후 **회전으로 잘려 나간 꼬리의 5xx 는 영영 안 세고**, 요약은 그 구간을 `이번 구간 N건` 이라고 단정한다. SSH 쪽에서 (b)(c)(d) 로 정성껏 막은 것과 **같은 형태의 구멍**이다. 잃는 창이 ≤5분이고 5xx 는 임계 1·쿨다운 3600 이라 실해는 작다 | 최소한 주석에 한계를 적을 것(`monitor.sh:271-273` 이 `check_dbmem` 에서 이미 하는 방식). 고칠 거면 SSH 처럼 오프셋 추적으로 바꿀 것 |
| **CR42-6** | low | `scrub` 규칙 ③(`[0-9][0-9,.]*(만원\|억원\|원\|억)`)이 **한글 단어 안의 `원`/`억`** 에도 붙는다 — 실측 `지원 3원격` → `지원 <num>원격`. 과잉 세탁이라 **안전한 방향**이고 실제 알림 문자열에 그런 형태는 없다. 기록만 해 둔다 | 그대로 두어도 된다. 신경 쓰이면 `(원\|만원\|억)` 뒤에 단어경계 대신 `[^가-힣]` 를 요구할 것 |
| **CR42-7** | info | `job-run.sh:66` 은 `trap 'rm -f "$TMP"' EXIT` 뿐이고 selftest 는 `EXIT INT TERM HUP` 이다. 불일치가 신경 쓰여 재 봤다 — bash 는 SIGTERM 으로 죽어도 **EXIT trap 을 실행한다**(실측: 임시파일 정리됨). **결함 아님.** 통일하면 읽는 사람이 덜 헷갈린다 | 선택 |

---

### 8. 판정 사유

**고치라고 한 두 가지는 고쳐졌고, 나는 그것을 담당자 도구가 아니라 내 도구로 확인했다.**
CR41-2 는 30개월 불일치 0 / 인자 없으면 28개월 어긋남 / 수동 70회 거짓실패 0 — 주장한 숫자
그대로다. CR41-1 은 관문이 원본 형태를 **여전히 잡는다**는 것까지 봤고, 마스킹이 증거를
지우지 않았다. CR41-6 의 진단은 옳을 뿐 아니라 주장보다 강하고(40/40 결정적, 부정형에서
결함을 놓치는 것까지 실증), 8번째 변이는 실제로 T5 가 잡는다.

**그럼에도 차단하는 이유는 셋 다 결과로 정당화된다.**

`CR42-1` — 담당자가 **먼저 보고했다는 점은 높이 산다.** 판단의 절반(단언을 느슨하게 두지
않는다 · 사유를 구분한다)도 옳다. 그러나 *"최악이어도 연 2~3통"* 이 **63통**이고, 그중
61통은 **감시가 배치와 같은 사실을 매일 반복하는 것**이다. 근거 ②(*"감시가 이미 같은 비교를
한다"*)가 바로 그 피해의 원인인데 그 방향으로는 안 재 봤다. 대응 불가능한 경보를 30일
연속 보내면 사람은 그 경보 키를 끈다 — 그리고 그 키에는 016 컬럼 누락도 매달려 있다.
**CR-040 이 35일로 차단한 것을 61일로 되살릴 수는 없다.** 다음 발생은 2026-09-01, 한 달 뒤다.

`CR42-2` — 이번 라운드가 가장 공들인 트립와이어가, **가장 흔한 흔적 삭제 명령 한 줄**에
눈이 먼다. `: >` 는 잡고 `rm` 은 못 잡는다. 그 상태에서 요약은 `0건(기대 0)` 이라고 **적극적으로
안전을 선언한다.** 담당자 자신이 세운 원칙("회전본으로 설명되지 않으면 조용히 넘기지 않는다")을
inode 경로에만 적용하지 않은 것이고, 고치는 데는 조건 한 줄과 분기 하나면 된다.

`CR42-3` — CR40-2 가 로그 검사에서 차단한 fail-open 이 **인증서 검사에 그대로 살아 있다.**
켜져 있던 경보를 지우고 *"여유 회복 (최단  9999일)"* 이라는, 이름도 값도 없는 해소 통보를
보낸다. selftest 에 인증서 시나리오가 **0건**이라 아무도 못 봤다.

**공통점을 적는다.** 셋 다 *"감시가 자기가 못 본 것을 봤다고 말하는 자리"* 다.
이번 라운드는 그 계열을 여덟 개나 찾아냈고 — 그래서 남은 세 개도 같은 자리에 있었다.
**검사가 닿은 곳은 튼튼하고, 검사가 안 닿은 곳은 예외 없이 뚫려 있다.**
그러니 다음 라운드의 기준은 하나면 된다: **`clear_alert` 를 부르는 모든 경로와, "0건/이상
없음"을 적는 모든 경로에 대해, "그때 나는 실제로 봤는가"를 selftest 가 묻게 할 것.**
지금 그 질문을 받는 것은 `logperm`·`logleak`·`api5xx`·`sshpw`·`logblind` 다섯이고,
`cert`·`jsonlog`·`dbstruct` 는 아직 안 받는다.

---

### 9. PASS 조건

1. `CR42-1` — 감시의 기준월 경보가 **배치가 이미 알린 달에는 재발송하지 않는다**(또는 동등한
   억제). 같은 전제(완결 0인 달 2개)로 14개월 돌려 **총 발송 ≤ 4통**. selftest 에 그 계수 검사.
2. `CR42-2` — (h)·(l) 두 케이스에서 `authshrink`(또는 동등 경보) + `blind_add` 가 나고,
   기존 (a)(b)(c)(c2)(d) 와 대조군 (e)(f)(m) 이 **그대로** 유지될 것. selftest T6 에 케이스 추가.
3. `CR42-3` — `LE_DIR` 대상 0개일 때 `clear_alert cert` 를 **부르지 않고** `blind_add` 할 것.
   selftest 에 음성/양성 대조군 각 1건.
4. `bash deploy/monitor-selftest.sh` 그린 · `python -m pytest -q` 그린 · `grep -rn "MUT-" deploy/` = 0.

---

### 리뷰 위생

* **`grep -rn "MUT-" deploy/` 시작 0 · 종료 0.** 변이는 심지 않았다 — 이번에 찾은 것들은
  **변이가 아니라 현재 코드의 동작**이라, 원본 그대로 격리 재현으로 붙잡았다.
* 저장소 파일 **수정 0** (이 로그와 `.review-state.json` 제외). `git status --porcelain` 이
  리뷰 전과 동일하다.
* 감시 실행은 **전부 로컬 격리** — `RE_MON_STATE`/`RE_MON_LOG` 는 `mktemp -d` 아래,
  `RE_MON_DRY_RUN=1`, URL 은 닫힌 포트 `127.0.0.1:9`. **사용자에게 간 알림 0통.**
* **서버는 접속하지 않았다.** 실패 주입 0건(5분 크론이 돌고 있다). 서버 관련 사실은
  담당자 보고와 backend 소스(`timeadjust.py` docstring)에서만 인용했고, 인용임을 밝혔다.
* 날짜·볼륨 계산과 트립와이어 재현은 스크래치패드 스크립트로만 했다 — 저장소 추가 파일 0건.
* 한글 테스트명으로 `pytest -k` 는 쓰지 않았다(전 스위트 2회 + junit XML 집계만).


---

## CR-043 · 2026-08-01 · CR-042 차단 3건 재검증 (범위 `deploy/**` · `docs/**` + `backend/tests/test_script_hygiene.py`)

**판정: FAIL** — 차단 **2건**. **CR42-1 · CR42-2 · CR42-3 은 셋 다 해소됐다**(전부 내 도구로
격리 재현했다). 담당자가 스스로 찾은 10·11·12번째도 셋 다 실재하고 재현된다.

**그런데 13번째가 있다. 그리고 그건 `CR42-3` 을 고치면서 생겼다.**
`check_cert` 는 이제 `clear_alert cert` 를 안 부른다 — 옳다. 그러나 그 "못 봤다" 사유를
실어 나르는 `logblind` 를, **5분 뒤 `--fast` 가 인증서를 본 적도 없이 "해소" 라고 통보하고
지운다.** 사용자가 매일 받는 문장은 *"해소: 로그 감시 대상 정상 (권한·유출·5xx·SSH 검사
전부 수행)"* 이고, 그때 인증서 감시는 죽어 있다. **CR-040 이 차단하고 CR42-3 이 다시 차단한
바로 그 문장이다.**

그리고 14번째 — **이번 라운드의 가장 큰 변경(CR42-1 억제)의 극성을 뒤집어도 관문이
139/0/2/HARN 0 으로 초록이다.** 그 변이는 *진짜 미실행을 완전히 침묵*시킨다. PASS 조건 #1 이
지키라고 한 바로 그것이다.

> **먼저 적어 둔다.** 이 라운드의 작업은 CR-042 때보다 또 한 단계 높다. 세 차단의 조치를
> 나는 담당자 도구가 아니라 **내가 새로 짠 격리 하네스**로 다시 쟀고, 트립와이어는 담당자
> 케이스 5종에 **내가 만든 3종을 더해** 8/8, 대조군은 4종에 **3주 연속 주간 회전**을 더해
> 완전 침묵을 확인했다. 볼륨 산수(95/4/183/27)는 손으로 다시 계산해 **네 값 모두 일치**한다.
> 그래서 더더욱, 관문이 아직 안 닿은 두 자리를 적는다.

---

### 0. 실행 검증 — **주장 전건 일치**

```
grep -rn "MUT-" deploy/                     시작 0 · 종료 0
bash -n deploy/*.sh                          8파일 전부 exit 0
bash deploy/monitor-selftest.sh              통과 139 · 실패 0 · 건너뜀 2 · 하네스오류 0 · rc=0   (주장 일치)
backend python -m pytest -q -p no:warnings   1466 passed · 103 skipped · 0 failed (77s)          (주장 일치)
git diff --stat                              오늘(08-01) 손댄 것은 deploy/** · docs/** ·
                                             backend/tests/test_script_hygiene.py 뿐
                                             (나머지 backend 변경은 mtime 07-30·07-31 = 이전 라운드)
```

건너뜀 2건은 둘 다 윈도우에서 `chmod` 가 안 먹어서다(T5 권한 대조군 · T9 0640 실측).

**동시 3회는 재현되지 않았다** — 139/0/2/0 · 139/0/2/0 · **138/1/2/0**. → §7(CR43-3).

---

### 1. `CR42-1` 알림 폭주 — **해소. 숫자가 네 개 다 맞다. 과설계도 아니다**

담당자 주장을 **내 손계산으로 독립 검증**했다(모델을 다시 세워 16개월을 전수로).

| | 담당자 주장 | 내 계산 | 관문 출력 |
|---|---|---|---|
| 완결 0인 달이 낀 16개월 · 옛 규칙 | 95통 | **95통**(배치 3 + 일일 91 + 해소 1) | 95통 |
| 같은 기간 · 새 규칙 | 4통 | **4통**(경고 3 + 일일 0 + 해소 1) | 4통 |
| 진짜 미실행(크론 소실) | 183일 | **183일**(2026-04~09) | 183일 |
| 그때 발송 | 27통 | **27통**(183일 / 쿨다운 7일, 첫날 포함) | 27통 |

스테일이 되는 달도 내가 따로 짚었다 — `2025-07`·`2025-08` 은 **2025-09·2025-10** 배치를
넘어뜨리고, `2026-07` 은 **2026-09** 을 넘어뜨린다(2026-08 은 안 걸린다). 담당자 모델과 같다.

`_market_batch_ran_this_month` 의 fail-closed 4케이스(파일 없음 · 이번달 · 지난달 · 깨진 값)도
함수를 직접 뽑아 돌려 4/4 확인했다.

**과설계인가 — 아니다.** 세 층은 각각 다른 것을 고친다.

1. **배치 등급화**는 *문장*을 고친다. `rc=1` 이면 사용자가 받는 말이 *"배치 실패"* 인데
   그건 거짓이었고(51초에 전 행 적재), `last_success_at` 이 한 달 굳는 것도 그 때문이다.
2. **`warn_<이름>` 키**는 그 말이 나갈 *통로와 쉼도*를 준다. 1만 있고 2가 없으면 경고가
   아무 데로도 안 나간다(= 조용한 유실).
3. **감시 억제**만이 91통을 0으로 만든다. 1·2는 볼륨을 못 줄인다.

하나를 빼면 담당자가 이름 붙인 피해가 하나씩 그대로 남는다. **다만** 3은 셋 중 유일하게
**침묵을 만드는** 층이고, 그래서 가장 검사가 필요한데 — 그 검사가 없다(§6, CR43-2).

---

### 2. `CR42-2` 트립와이어 — **해소. 담당자 케이스 + 내가 만든 3종까지 전부 잡힌다**

담당자 하네스를 쓰지 않고 **내가 새로 짠 격리 스크립트**로 재현했다(`RE_MON_DRY_RUN=1` ·
`mktemp -d` 상태 · URL 은 닫힌 포트 `127.0.0.1:9` · 서버 무접촉 · 알림 0통).

| 시나리오 | 기대 | 실제 |
|---|---|---|
| (h) `rm auth.log` + 재생성 · 낡은 `.1`(500줄) > off | authshrink | **authshrink + logblind** ✅ |
| (l) 서버형 delaycompress(`.1` 평문 800줄 + `.2.gz`) + rm 재생성 | authshrink | **authshrink + logblind** ✅ |
| (x1) `: > auth.log` + `touch .1`(mtime 위조) | authshrink | **authshrink + logblind** ✅ |
| (x4) 정상 회전 뒤 `.1` 안의 줄 삭제(`sed -i`) | authedit | **authedit + logblind** ✅ |
| (x6) `auth.log` 동결 5일 | authfresh | **authfresh** ✅ |
| **(z1) 내가 추가** — `auth.log` 와 `.1` 을 **둘 다** 지우고 재생성 | ? | **authshrink + authedit + logblind** ✅ |
| **(z2) 내가 추가** — `copytruncate` 흉내(`cp` 후 원본 비움) | 오탐(문서화된 한계) | **authshrink** — 문서가 예고한 그대로 ✅ |
| **(z3) 내가 추가** — 회전 뒤 `.1` 을 **inode 보존한 채** 축소(`cat tmp > .1`) | authedit | **authedit + logblind** ✅ |

**대조군 — 여기가 진짜 시험대다. 전부 완전 침묵.**

| 대조군 | 결과 |
|---|---|
| (e) 정상 증가 | 무경보 ✅ |
| (f) 평범한 로테이션 | 무경보 ✅ |
| (m) **서버 설정 그대로**의 delaycompress 주간 회전 1회 + 전후 증가 | 무경보 ✅ |
| **(m2) 내가 추가** — 같은 회전을 **3주 연속** + 매주 평상시 증가 | 무경보 ✅ |

`(m2)` 를 넣은 이유는 한 주만 보면 `.2.gz`→`.3.gz` 밀림과 `prev_r1_ino` 이월이 누적되는
자리를 못 보기 때문이다. **3주 내내 조용하다.** 매주 오탐이 갈 걱정은 없다.

**`(h)` 의 요약 문구도 확인했다** — `이번 구간 0건 (기대 0)` 이 **안 적힌다**. 대신
`⚠️ 못 본 구간이 있다(...)` 로 나간다. 주장대로다.

**명시한 한계는 정직한가 — 그렇다.** ① `copytruncate` 구별 불가는 `(z2)` 로 실증했고,
경보 문구가 그 가능성을 **먼저** 적는다. ② *"회전 직후 `.1` 을 처음 보기 전의 편집"* 은
실제로 못 잡는 창이 맞다(`.1` 이 `off` 이상으로 남으면 `old_short` 도 안 걸린다) —
`monitor.sh:680-682` 이 그 조건까지 정확히 적어 뒀다. **없는 척하지 않았다.**

---

### 3. `CR42-3` 인증서 fail-open — **`cert` 키는 해소. 그러나 사유가 새는 자리가 남았다 → §5**

경보를 **미리 켜 놓고** 격리 재현했다.

| 확인 | 결과 |
|---|---|
| `LE_DIR` 대상 0개 → `clear_alert cert` | **안 부른다** ✅ |
| 켜져 있던 `cert.active` | **살아남는다** ✅ |
| 요약 문구 | `인증서  : 검사 못 함 (대상 0개 · …)` ✅ |
| `9999` 가 어디엔가 남는가 | **없다** ✅ |
| `blind_add` 로 사유가 실리는가 | **실린다** — `감시불능: 인증서 대상 0개(...)` ✅ |
| 양성 대조군(정상 인증서 1장) | 실제로 해소되고 이름·일수가 요약에 실린다 ✅ |

**순서 변경이 다른 검사를 깨뜨렸는가 — 아니다.** `--daily` 는 `check_cert` →
`check_db_structure` → `check_logblind` 순이고(1083·1084·1089), 순서 불변식 검사를
떼어 내 직접 돌려 봤다: 원본은 `fast` `daily` 둘 다 PASS, `check_logblind` 를 `check_cert`
앞으로 되돌리면 `--daily : FAIL — 뒤에 있는 검사: check_cert check_db_structure`.
**12번째(순서 불변식)는 실재하고 실제로 죽인다.** ✅

---

### 4. 담당자가 스스로 찾은 셋 — **전부 재현. 실재한다**

| | 확인 |
|---|---|
| **10번째** (`send_telegram` 의 `\| scrub`) | 격리 사본에서 `text=$(… \| scrub)` 를 `text="$1"` 로 바꾸니 DRY-RUN 출력에 `한도 1,026,560,000원 · SERVICE_KEY=abcd1234efgh` 가 **그대로** 나온다. T7 마지막 검사(`monitor-selftest.sh:922-935`)가 정확히 그 문자열을 본다. 지적이 옳다 — 세탁 규칙 21종을 다 통과해도 **나가는 길**이 무방비였다 |
| **11번째** (비밀 규칙 ④ 따옴표) | 옛 정규식과 새 정규식을 직접 돌렸다. 옛 규칙: `{"api_key": "sk-live-9wQ2kLp4RtZ"}` **원문 그대로 통과** · `{'TOKEN': …}` · `{'POSTGRES_PASSWORD': …}` 도 전부 통과. 새 규칙: 넷 다 `<redacted>`. **SR38-4 가 지적한 ③보다 넓다는 주장이 맞다** — ③은 금액이고 ④는 비밀이며, `psycopg.OperationalError: {"POSTGRES_PASSWORD": "…"}` 형태가 실제로 그 모양이다 |
| **12번째** (호출 순서 불변식) | 위 §3. `awk` 추출이 7개 함수를 정확히 잡고(`check_api5xx` 의 숫자 포함), 순서를 되돌리면 `--daily` 가 붉는다. **두 번 틀린 규칙을 기계에 넘긴 판단이 옳다** |

---

### 5. ⛔ **CR43-1 — 13번째. `--fast` 가 인증서를 본 적도 없이 "감시 정상" 이라고 해소 통보한다**

`check_cert`(`monitor.sh:838`) 와 `check_db_structure`(`monitor.sh:960`) 의 `blind_add` 는
**`--daily` 에만 있다**. 그런데 그 사유를 담는 통은 `BLIND` 하나이고, 이걸 비우고 채우는
`check_logblind` 는 **`--fast` 에서도 돈다**(`monitor.sh:1062`). `--fast` 에는 인증서 검사가
아예 없으니 `BLIND` 는 언제나 비고 → `monitor.sh:766` 의 `clear_alert logblind` 가
**무조건** 걸린다.

**격리 재현**(DRY-RUN · 빈 `LE_DIR` · 나머지 로그는 전부 정상):

```
1) --daily   → ALERT logblind ...  (감시불능: 인증서 대상 0개)      · .active = YES
2) 5분 뒤 --fast
   [DRY-RUN] [realestate] 해소: 로그 감시 대상 정상 (권한·유출·5xx·SSH 검사 전부 수행)
                                                                    · .active = NO   ← 지워졌다
3) 다음날 --daily → 또 ALERT logblind
   최종:  raise 2회 / clear 1회   (인증서 상태는 내내 그대로 나빴다)
```

**무엇이 잘못됐나.**

1. **거짓 해소 통보가 매일 한 통 나간다.** 문장은 *"권한·유출·5xx·SSH 검사 전부 수행"* 인데,
   그 순간 못 보고 있는 것은 **인증서**다. 이 검사의 주석 자체가
   *"우리 nginx 설정이 나쁘면 동거 서비스 갱신이 실패한다"*(`monitor.sh:805-807`)고 적은 자리다.
2. **쿨다운(21600)이 무력화된다.** `clear_alert` 가 `.sent` 까지 지우므로 다음 `--daily` 는
   억제 없이 다시 보낸다. 켜짐→거짓해소→켜짐이 **끝없이 반복**된다.
3. **CR42-3 의 절반이 되돌려진다.** `cert` 키는 안 지워지지만, 그 사유를 사람에게 전달하는
   유일한 경보(`logblind`)가 매일 "정상" 으로 덮인다. `check_cert` 가 `raise_alert` 를
   직접 하지 않고 `blind_add` 만 하도록 설계됐기 때문에, **사유가 이 통로밖에 없다.**

**이건 이번 라운드가 만든 결함이다.** CR42-3 이전에는 `blind_add` 를 부르는 검사가
전부 `fast`·`daily` 양쪽에 있었다. `check_cert`(CR42-3) 와 `check_db_structure`(CR42-1) 를
같은 통에 넣으면서 처음으로 **"한쪽 모드만 아는 사유"** 가 생겼고, 반대쪽 모드의 clear 는
그것을 모른다.

**관문이 왜 못 봤나.** T5b 는 `--daily` **한 번**만 돌린다(`monitor-selftest.sh:549`).
같은 상태 디렉터리로 `--fast` 를 이어 돌리는 시나리오가 **0건**이다.

> **판정 기준 그대로다** — *"`clear_alert` 를 부르는 모든 경로에 대해 '그때 나는 실제로
> 봤는가' 를 묻는다."* CR-042 §8 이 스스로 세운 문장이고, `check_logblind` 의 clear 경로는
> `--fast` 에서 그 질문에 **아니오** 라고 답해야 한다. → **차단.**

---

### 6. ⛔ **CR43-2 — 14번째. CR42-1 억제의 "후 = 0통" 은 계산이 아니라 상수다**

`monitor-selftest.sh:1050` 이 `new_daily=0` 으로 두고, 감시 루프의 새 규칙 자리
(`:1080`)는 **주석 한 줄과 no-op `:`** 다. 그리고 `:1097` 이 그 상수를 검사한다:

```bash
new_batch=0; new_daily=0; new_clear=0          # 1050
    old_daily=$((old_daily + ndays))           # 1079  ← 옛 규칙은 센다
    :                                          # 1080  ← 새 규칙: 아무것도 안 센다
if [ "$new_daily" -eq 0 ]; then ok "…한 통도 다시 보내지 않는다"   # 1097  ← 항상 참
```

즉 **"전 95통" 은 모형이 계산한 값이고, "후 4통" 의 0 은 사람이 적은 값이다.**
억제 규칙은 ① 함수 단위 4케이스(`:1140-1158`)와 ② 구획에 문자열 두 개가 있는지
(`:1175`)로만 검증된다. **둘 다 극성을 못 본다.**

**변이 2종을 격리 사본에 심어 관문 전체를 돌렸다**(저장소 무수정 · `MUT-` 0 유지):

| 변이 | 무엇이 망가지나 | 관문 |
|---|---|---|
| **M1** `monitor.sh:977` 을 `if ! _market_batch_ran_this_month; then` 로 극성 반전 | ① 배치가 **돈** 달에 다시 매주 발송(CR42-1 부활) ② **배치가 아예 안 돈 달에 완전 침묵** — 크론이 사라져도 아무 신호가 없다 | **통과 139 · 실패 0 · 건너뜀 2 · 하네스오류 0 · rc=0** ← **생존** |
| **M2** `monitor.sh:984` 쿨다운 `604800`→`31536000`(1년) | 진짜 미실행 183일에 **27통 → 1통** | **통과 139 · 실패 0 · 건너뜀 2 · 하네스오류 0 · rc=0** ← **생존** |

**M2 는 더 나쁘다 — 관문이 피해를 화면에 출력하면서 PASS 라고 적는다:**

```
        미실행 시나리오: 밀린 날 183일 → 발송 1통 (쿨다운 31536000초)
  PASS 배치가 **아예 안 돌면** 감시가 여전히 운다 (183일 → 1통 · 억제가 아니라 중복 제거다)
  PASS 그 경우에도 매일 울지는 않는다 (183일 중 1통 …)
```

상한 단언이 없어서 `SIM_SENT > 0` 과 `SIM_SENT < miss_days` 만 보고 초록이 된다
(`monitor-selftest.sh:1128`·`:1133`).

**왜 이게 차단인가.** M1 이 죽이는 것은 **CR-042 가 PASS 조건 #1 로 명시한 바로 그것**이다 —
*"억제가 아니라 중복 제거일 것 · 배치가 안 돌면 여전히 울 것."* 이번 라운드에서 유일하게
**침묵을 새로 만든 층**이 3(감시 억제)이고, 그 층의 방향이 관문에서 자유롭다. 그리고
이 코드는 `docker`+`psql` 이 필요해 **행동으로 한 번도 실행된 적이 없다** — 로컬에서도,
서버에서도(서버는 아직 옛 코드다). 즉 `check_db_structure` 의 ② 구획은 **오늘까지 단 한 번도
돌아 본 적이 없는 코드**이고, 관문은 그것을 문자열로만 본다. → **차단.**

---

### 7. 그 외 판정

| 항목 | 판정 |
|---|---|
| **SR38-7 관문 글롭 확대** | **수용 · 측정했다.** 대상 **39 → 68 파일(+29)**. `git ls-files '*.md'` 62개 중 **관문 밖 0개**. 검사는 **약해지지 않았다** — 지운 줄은 `for pattern` 한 줄뿐이고 나머지 로직·정규식·`.env.example` 예외는 그대로다. 범위 못 박는 단언도 공회전하지 않는다(`deploy/DEPLOY.md`·`team/CHARTER.md` 둘 다 실재). **+17/-1 · 허용 범위 안** |
| **SR38-9 `want()/avoid()/live()` + HARN** | **부분 수용** → CR43-3. 설계 의도(하네스 오류를 검사 실패와 분리)는 옳다. 그러나 **주장한 안정성(동시 3회 동일)은 재현되지 않았다** |
| **변이 배터리 "11 중 1 생존 = 동치"** | **검증 불가 · 그러나 반례를 찾았다.** 담당자가 생존 변이의 정체를 밝히지 않아 동치 여부를 판정할 수 없다. 대신 내가 심은 **M1·M2 는 동치가 아니다** — 각각 침묵과 발송량을 실제로 바꾼다. 그리고 둘 다 생존한다(§6) |
| **CR42-4 조건 자리 파이프라인** | **수용.** `monitor.sh:198` 이 `case` 기반으로 바뀌었고 대소문자 문자클래스까지 넣었다 |
| **CR42-5 5xx 회전 사각지대** | **수용.** `monitor.sh:471-476` 이 한계를 적었다 — *"모르는 창이 있다는 것을 적어 두는 것이 지금 할 수 있는 정직한 처리다."* 요구한 그대로다 |
| **문서** | **수용.** `monitoring.md:428-464` 이 옛 문장(*"연 2~3통"*)을 **지우지 않고 남긴 뒤** 표로 반박한다. `DEPLOY.md §9` 의 경보 키 표는 `warn_*` 가 *"즉시 조치를 요구하지 않는다"* 를 명시한다. 내가 다시 잰 네 숫자와 문서 값이 전부 같다 — **이번엔 과장이 없다** |
| **서버를 아직 안 올린 판단** | **옳다.** 게이트가 붉은 채로 올리면 CR43-1(매일 거짓 해소)과 **한 번도 안 돌아 본 억제 코드**를 그대로 배포하게 된다. 다만 **대가를 명시한다** — 옛 코드에는 CR42-2(트립와이어가 `rm` 에 눈멂)·CR42-3(인증서 fail-open)이 **지금 살아 있고**, CR42-1 폭주는 **2026-09-01 에 실제로 터진다.** 홀드는 옳지만 **길게 끌 수 없다** |

---

### 8. 지적 사항

| ID | 심각도 | 내용 | 수정 제안 |
|---|---|---|---|
| **CR43-1** | **high · 차단** | **`--fast` 가 `--daily` 전용 blind 사유를 모른 채 `logblind` 를 해소한다.** 위 §5. `check_cert`(`monitor.sh:838`)·`check_db_structure`(`:960`)의 `blind_add` 는 daily 전용인데, `check_logblind`(`:761-768`)는 fast 에서도 돌며(`:1062`) `BLIND` 가 비었다는 이유로 `:766` `clear_alert logblind` 를 무조건 부른다. 재현: daily(빈 `LE_DIR`) → `.active` 생성 → 5분 뒤 fast → **`해소: 로그 감시 대상 정상 (권한·유출·5xx·SSH 검사 전부 수행)` 발송 + `.active`/`.sent` 삭제** → 다음 daily 재발생(raise 2 / clear 1). 쿨다운 21600 도 함께 무력화된다. CR42-3 이 만든 결함이고, T5b 가 `--daily` 만 돌려서(`monitor-selftest.sh:549`) 못 봤다 | `BLIND` 를 모드별로 나누거나(권장: daily 전용 사유는 `kv_set` 으로 남기고 fast 는 그 키가 살아 있으면 clear 하지 않는다), daily 전용 사유는 **별도 키**(`certblind` 등)로 뺀다. 최소한 **`clear_alert logblind` 를 부르기 전에 "이번 실행이 그 사유를 실제로 재평가했는가"** 를 확인할 것. 문구도 모드에 맞출 것(daily 는 인증서·DB 도 봤다) |
| **CR43-2** | **high · 차단** | **CR42-1 억제의 극성이 관문에서 자유롭다.** 위 §6. `monitor-selftest.sh:1050`·`:1080`·`:1097` 이 "후 = 0통" 을 **상수로 단언**하고, 구조 검사(`:1175`)는 문자열 두 개만 본다. 변이 2종이 **139/0/2/HARN 0 · rc=0** 으로 생존: **M1**(`monitor.sh:977` 극성 반전 — 진짜 미실행이 **완전 침묵**) · **M2**(`:984` 쿨다운 1년 — 183일에 1통). M2 는 관문이 `발송 1통` 을 **출력하면서** PASS 라고 적는다(`:1128`·`:1133` 에 상한 단언 없음). 이 구획은 `docker`+`psql` 이 필요해 **행동으로 한 번도 실행된 적이 없다** | `check_db_structure` 의 **② 기준월 신선도 구획을 통째로 뽑아**(`ext` 로 이미 쓰는 방식) `_market_batch_ran_this_month` 와 `raise_alert` 를 가짜로 물려 **발송 여부를 행동으로** 재고, 그 값으로 `new_daily` 를 **계산**할 것. 그리고 미실행 시나리오에 **상한**을 걸 것(예: `SIM_SENT >= miss_days/10`). 합격선은 **M1·M2 가 각각 FAIL 로 죽는 것** |
| **CR43-3** | medium | **관문이 부하에서 결정적이지 않고, HARN 이 그것을 못 잡는다.** 동시 3회 실행: 139/0/2/0 · 139/0/2/0 · **138/1/2/0**. 붉은 것은 T3b `월중 수동 실행…` 이고 원인은 `fork: retry: Resource temporarily unavailable`(관문 출력에 그대로 찍혔다). `want()/avoid()/live()` 는 **로그 파일을 읽는 검사만** 덮는데, 포크를 가장 많이 쓰는 것은 **날짜 루프(T2·T3b·T10)** 다. 특히 `monitor-selftest.sh:287` 의 `[[ "$ref" < "$exp" ]]` 는 `$ref` 가 비면 **무조건 참** — `monitor.sh:957-962` 가 *"빈 문자열과 비교하면 무조건 참이 되어 헛운다"* 며 스스로 금지한 형태다. 반대로 T2 `:165` 는 같은 사고가 나면 **조용히 통과**한다(거짓 PASS 방향) | ① 날짜 루프의 `$exp`/`$ref`/`$db` 에 `[ -n … ]` 가드를 걸고, 비면 `harn` 으로 셀 것 ② `DEPLOY.md`·`monitoring.md` 의 *"HARN 이 0 이면 초록/빨강을 근거로 쓸 수 있다"* 는 지금 **참이 아니다** — 그 문장을 고치거나 ①로 참으로 만들 것 |
| **CR43-4** | low | `monitor.sh:831` — `days=$(( ( $(date -d "$end" +%s 2>/dev/null \|\| echo 0) - $(date +%s) ) / 86400 ))`. `openssl` 이 준 만료일을 `date` 가 못 읽으면 **0 으로 대체**되어 `days` 가 −20,000 대가 되고, 그대로 `worst` 가 되어 *"인증서 만료 임박: … -20321일 남음"* 오탐이 난다. 바로 위 `[ -z "$end" ]` 는 "못 읽음" 으로 정확히 처리하는데 **파싱 실패만 값으로 흘러든다**. `LC_ALL=C` 덕에 오늘은 안 터진다 | `epoch=$(date -d "$end" +%s 2>/dev/null)` 를 따로 받아 `[ -n "$epoch" ]` 가 아니면 `unreadable` 로 보낼 것 — `[ -z "$end" ]` 경로와 같은 처리 |
| **CR43-5** | info | `monitoring.md:510-512` 이 *"변이 12종 전부 죽는다(자체검사 83건 기준)"* 로 남아 있는데, 같은 문서 `:559`·`:563` 은 *"약 135건"*·*"20종"* 이다. 앞쪽이 이전 라운드의 잔여 문장이다. 틀린 것은 아니고 시점이 다를 뿐 | 앞 문단에 *"(CR-041 시점 기준)"* 한 마디 |

---

### 9. 판정 사유

**고치라고 한 셋은 다 고쳐졌고, 나는 그것을 담당자 도구가 아니라 내 도구로 확인했다.**
`CR42-1` 은 손계산 네 값이 전부 일치했고 세 층이 각각 다른 피해를 막는다는 것도 확인했다
(과설계 아님). `CR42-2` 는 담당자 케이스 5종 + **내가 만든 3종**이 8/8 잡히고, 대조군은
**3주 연속 주간 회전**까지 완전 침묵이다. `CR42-3` 은 음성·양성 대조군 양쪽이 맞다.
10·11·12번째도 셋 다 내가 재현했다 — 특히 11번째는 **옛 정규식이 `{"api_key": "…"}` 를
원문 그대로 내보낸다**는 것을 직접 봤다. 실재하는 구멍이었다.

**그럼에도 차단하는 이유는 둘 다 결과로 정당화된다.**

`CR43-1` — **이 라운드의 조치가 만든 결함이다.** `check_cert` 는 `raise_alert` 를 안 하고
`blind_add` 만 하도록 설계됐으므로, 그 사유가 사람에게 닿는 길은 `logblind` **하나뿐**이다.
그 하나를 5분 뒤 `--fast` 가 *"권한·유출·5xx·SSH 검사 전부 수행"* 이라는 문장과 함께
**매일 지운다.** 인증서를 본 적도 없이. CR-040 이 차단하고 CR42-3 이 다시 차단한 문장이
**세 번째로** 돌아왔고, 이번에는 고치는 과정에서 들어왔다. 관문은 `--daily` 를 한 번만
돌리기 때문에 이 자리를 구조적으로 볼 수 없다.

`CR43-2` — **이번 라운드가 새로 만든 유일한 "침묵" 에 방향 검사가 없다.** 1·2는 문장과
통로를 고치는 층이라 되돌리면 시끄러워질 뿐이지만, 3은 **경보를 안 보내게 만드는 층**이다.
그 극성을 뒤집으면 크론이 사라져도 아무 신호가 없는데, 관문은 **139/0/2/HARN 0** 이다.
쿨다운을 1년으로 늘려도 마찬가지이고, 그때 관문은 `발송 1통` 을 **눈앞에 출력하면서**
PASS 라고 적는다. 이 프로젝트가 CR-040 부터 다섯 라운드째 붙잡아 온 것이 정확히
*"검사가 닿은 곳은 튼튼하고 안 닿은 곳은 예외 없이 뚫린다"* 이고, `check_db_structure` 의
②구획은 **오늘까지 한 번도 실행된 적이 없는 코드**다(로컬은 `docker`/`psql` 없음, 서버는
아직 옛 코드). 문자열 검사만으로 배포할 자리가 아니다.

**공통점을 적는다.** 둘 다 **"관문이 한쪽 모드/한쪽 방향만 본다"** 이다. `CR43-1` 은
`--daily` 만 돌려서 `--fast` 의 되돌림을 못 봤고, `CR43-2` 는 "울면 안 되는 쪽" 만 상수로
단언해서 "울어야 하는 쪽" 을 못 봤다. 다음 라운드의 기준은 하나면 된다:
**억제·해소를 만드는 모든 코드에 대해, 그 반대 방향(울어야 하는 경우 · 다른 모드)에서도
한 번 돌려 볼 것.** 지금 그 대칭을 갖춘 것은 `logperm`·`logleak`·`cert`(T5b 음성/양성)·
`warn_`(T11 ②③) 넷이고, `logblind`(모드 대칭)와 `marketstale`(방향 대칭)은 아직 없다.

---

### 10. PASS 조건

1. **`CR43-1`** — `--daily` 에서 `logblind` 가 뜬 뒤 같은 상태로 `--fast` 를 돌렸을 때
   **`ALERT-CLEARED logblind` 0건 · `.active` 생존 · "해소" 통보 0통.**
   그리고 **양성 대칭**: 인증서가 정상으로 돌아온 뒤 `--daily` 를 돌리면 **실제로 해소**될 것.
   selftest T5b 에 그 2케이스 추가.
2. **`CR43-2`** — T10 의 "후" 일일 발송 수를 **억제 코드로 계산**할 것(상수 금지) + 미실행
   시나리오에 **상한 단언**. 합격선: **M1(극성 반전) · M2(쿨다운 1년) 두 변이가 각각
   `실패 >= 1` 로 죽을 것.** (§6 표의 변이를 그대로 쓰면 된다)
3. `bash deploy/monitor-selftest.sh` 그린 · `python -m pytest -q` 그린 ·
   `grep -rn "MUT-" deploy/` = 0.
4. (권고 · 차단 아님) CR43-3 의 날짜 루프 가드 — 안 하면 다음 라운드에도 관문의
   초록/빨강을 근거로 못 쓴다.

---

### 리뷰 위생

* **`grep -rn "MUT-" deploy/` 시작 0 · 종료 0.** 변이는 **저장소에 심지 않았다** —
  M1·M2 와 순서 변이는 전부 스크래치패드의 **사본**(`deploy/` 통째 복사)에 심고 거기서 돌렸다.
  리뷰 종료 시점 `git status --porcelain` 은 리뷰 전과 같다(이 로그와 `.review-state.json` 제외).
* **실패 주입 0건 · 서버 무접속.** 감시 실행은 전부 로컬 격리 — `RE_MON_STATE`/`RE_MON_LOG`
  는 `mktemp -d` 아래, `RE_MON_DRY_RUN=1`, URL 은 닫힌 포트 `127.0.0.1:9`,
  `RE_MON_CRED_FILES` 는 없는 경로. **사용자에게 간 알림 0통.**
* 트립와이어 재현 하네스는 **내가 새로 짰다**(담당자 것을 쓰지 않았다). 첫 판에
  감시 로그와 auth 로그 경로가 겹치는 **내 실수**가 있어 (x6)이 거짓 음성으로 나왔고,
  그것을 바로잡은 뒤 다시 쟀다 — 그 사실을 여기 적어 둔다.
* `monitor-selftest.sh` 전체 실행 **4회**(원본 3 + 스크래치 사본 1) · 변이 실행 2회 ·
  `pytest` 전체 3회. 동시 실행 결과의 불일치는 CR43-3 에 그대로 적었다.
* 서버 관련 사실은 담당자 보고와 SR-038 기록에서만 인용했고, 인용임을 밝혔다.

---

## CR-044 · 2026-08-02 · CR-043 차단 2건 재검증 (범위 `deploy/**` · `docs/**` + `backend/tests/test_script_hygiene.py`)

**판정: PASS** — 차단 **0건**. `CR43-1` · `CR43-2` 는 **둘 다 해소**됐고, 나는 그것을
담당자 관문이 아니라 **내가 새로 짠 격리 하네스**로 다시 쟀다. `CR-043` 이 §10 에 적은
합격선 넷 중 1·2·3 이 충족됐고, 4(권고)는 **절반만** 됐다.

그러나 **세 번째 변이(M3)를 찾았다.** `check_market_stale` 의 **`clear_alert` 경로는
관문이 아예 안 본다** — T10 이 그것을 `:` 로 물려 두었기 때문이다. 그 자리에 심은 변이는
`시장지수 기준월 회복 (n/a ≥ 기대 2026-06)` 이라는 **거짓 해소 통보**를 만드는데,
관문은 **T10 전건 통과**다. 이건 `CR42-3` 의 `인증서 여유 회복 (최단  9999일)` 과
**글자 모양까지 같은 결함**이다. 다만 **오늘 실려 있는 코드는 그 경로가 옳다**(내가 쟀다).
그래서 차단이 아니라 **CR44-2(중)** 으로 적는다.

그리고 살아 있는 것 하나 — **`sshjournal` 에는 해소 경로가 없다.** journald 가 **한 번**
응답을 못 하면 경보가 켜지고, journald 가 돌아와도 **영영 안 꺼진다**(실측: 정상 3회 뒤에도
`.active` 생존). 같은 함수 안의 형제 `authfresh`(같은 "출처가 죽었다" 부류)는 꺼진다.
**CR44-1(중).**

> **먼저 적는다.** 이 라운드는 내가 요구한 것을 요구한 방식으로 했다 —
> "후 = 0통" 이 **상수에서 계산으로** 바뀌었고, 그 계산이 **`docker`·`psql` 없이 돈다.**
> `--fast`/`--daily` 의 모드 대칭은 **양쪽 방향 모두** 시험되고, 내가 특히 물었던
> *"옛 사유가 굳어 fast 를 영구 봉인하지 않는가"* 는 **관문에 케이스로 들어가 있다**
> (`monitor-selftest.sh:714-719`). `log()` 세탁은 문장이 아니라 **피해로** 닫혔다.

---

### 0. 실행 검증 — **주장 전건 일치**

```
grep -rn "MUT-" deploy/                      시작 0 · 종료 0
bash -n deploy/*.sh                          8파일 전부 exit 0
bash deploy/monitor-selftest.sh              통과 167 · 실패 0 · 건너뜀 2 · 하네스오류 0 · rc=0  (주장 일치)
python -m pytest -q -p no:warnings           수집 1,571 = 1,468 passed · 103 skipped · 0 failed (주장 일치)
git diff --stat / mtime                      오늘(08-01~02) 손댄 것은
                                             deploy/{monitor.sh, monitor-lib.sh, monitor-selftest.sh, DEPLOY.md} ·
                                             docs/05-monitoring/{monitoring.md, monitoring-plan.md} ·
                                             backend/tests/test_script_hygiene.py 뿐.
                                             나머지 backend 변경은 mtime 07-30·07-31 = 이전 라운드
```

pytest 요약줄은 파이프에 잘렸으므로 **진행표시 문자를 세어** 확인했다 —
21줄×72 + 59 = 1,571자, 그중 `s` 가 103개 → **1,468 passed / 103 skipped**.
`--collect-only` 합계도 **1,571** 로 같다.

---

### 1. ⛔→✅ `CR43-1` 모드 대칭 — **해소. 양쪽 방향 다 내가 쟀다**

담당자 T5b 를 쓰지 않고 **내 격리 하네스**로 재현했다(DRY-RUN · `mktemp -d` 상태 ·
URL 은 닫힌 포트 `127.0.0.1:9` · 자격증명은 없는 경로 · **텔레그램 0통**).

| 단계 | 기대 | 실제 |
|---|---|---|
| ① `--daily` · `LE_DIR` 대상 0개 | `ALERT logblind` · 사유에 인증서 | 뜬다 · `kv/blind_daily` 에 사유 저장 ✅ |
| ② 5분 뒤 `--fast` | `ALERT-CLEARED logblind` **0건** | **0건** ✅ |
| | "해소" 통보 **0통** | **0통** ✅ |
| | `.active` 생존 | 생존 ✅ |
| | **`.sent` 생존(쿨다운 유지)** | **생존** ✅ |
| | 요약이 사유를 말하는가 | `감시불능: 5분 검사는 정상 · 일일 점검이 남긴 사유가 아직 있다 — 인증서 대상 0개(...)` ✅ |
| ③ `--fast` 8회 더 | 되풀이 재발 없음 | 누적 clear **0** · raise **1** (켜짐→거짓해소→켜짐 반복이 사라졌다) ✅ |
| ④ 인증서 정상 복귀 → `--daily` | **실제로 해소** | `ALERT-CLEARED logblind` 1 · `.active` 삭제 ✅ |
| | **`kv/blind_daily` 가 비는가** | **빈다** ✅ ← 영구 봉인 없음 |
| ⑤ 그 뒤 `--fast` | logblind 를 안 건드린다 | 0건 ✅ |

**반대 방향 결함(영구 봉인)이 없는 이유는 구조에 있다.** `check_logblind:866-870` 이
`--daily` 에서 **무조건** `kv_set blind_daily "$BLIND_DAILY"` 를 한다 — 사유가 없으면
빈 값으로 덮는다. 옛 값이 남을 경로가 없다. 관문도 그 자리를 **케이스로** 잡고 있다
(`monitor-selftest.sh:678` 이 어제 사유를 미리 심어 두고 `:714` 가 비었는지 본다).

**되돌리면 죽는가 — 죽는다.** `check_logblind:874` 의 `elif [ -n "$carried" ]` 를
무력화한 사본(M4)에 같은 하네스를 돌리면 **`ALERT-CLEARED logblind` 1 · 해소 1통 ·
`.active`/`.sent` 삭제** 로 CR43-1 이 그대로 재현된다. T5b 의
`avoid "$SC1.fastonly.log" 'ALERT-CLEARED logblind'`(`:642`)가 정확히 그 줄을 본다.

---

### 2. ⛔→✅ `CR43-2` 방향 대칭 — **해소. M1·M2 가 각각 죽는다**

합격선은 내가 §6 표에 적은 변이 두 개가 **각각 `실패 >= 1`** 이었다. 그대로 다시 심었다
(저장소 무수정 — 스크래치패드의 `deploy/` 통째 사본).

`check_market_stale()` 을 관문과 **똑같은 방식**(`ext` 로 뽑아 `_market_batch_ran_this_month`·
`raise_alert` 를 가짜로 물림)으로 떼어, T10 의 단언 6개를 그대로 돌렸다:

| 사본 | 배치 돈 달 | 미실행 183일 | 쿨다운 | T10 단언 |
|---|---|---|---|---|
| **대조군** | 91통 → **0통** | **27통** (최소 기대 18) | 604800 일치 | **6 통과 · 0 실패** |
| **M1** `if ! _market_batch_ran_this_month` | 91통 → **14통** | **0통 (완전 침묵)** | 없음 | **2 통과 · 4 실패** ← 죽는다 |
| **M2** 쿨다운 604800→31536000 | 0통 | **1통** (최소 기대 18) | 31536000 | **5 통과 · 1 실패** ← 죽는다 |

**관문 전체로도 확인**했다(축약 설정 `SELFTEST_MONTHS=3` · 문서 없는 사본이라
대조군 기준선이 **163/0/3**):

| 사본 | 관문 전체 | rc |
|---|---|---|
| 대조군 | 통과 163 · 실패 0 · 건너뜀 3 · **하네스오류 0** | 0 |
| **M1** | 통과 156 · **실패 7** · 건너뜀 3 · 하네스오류 0 | **1** |
| **M2** | 통과 162 · **실패 1** · 건너뜀 3 · 하네스오류 0 | **1** |
| **M3**(§3) | 통과 163 · **실패 0** · 건너뜀 3 · 하네스오류 0 | **0 ← 생존** |

M1 의 7건 중 5건이 정확히 이 자리다(`14통 재발송` · `16개월 18통` · `안 도는데 조용하다` ·
`183일 0통` · `쿨다운 불일치`). 나머지 2건은 M1 과 무관하고 §4 에 따로 적는다.
M2 의 1건은 **새로 넣은 상한 단언 바로 그것**이다 —
*"미실행 183일에 1통뿐이다 (최소 기대 18통)"*.

**두 단언이 각각 일한다.** 상한(`SIM_SENT >= miss_days/10`)이 M2 를 잡고, 극성은
`new_daily -eq 0` 과 `SIM_SENT > 0` 양쪽이 M1 을 잡는다. `MS_CD` 와 소스 쿨다운의
**일치 단언**은 "우리가 엉뚱한 `raise_alert` 줄을 읽고 계산했나"를 막는다 —
M1 에서 `없음 vs 604800` 으로 실제로 붉는다. 과설계가 아니다.

그리고 **판정 함수가 죽은 코드가 아닌지**도 못 박혀 있다(`:1571` 이
`check_market_stale "$ref" "$expected"` 호출을 본다). 순서 불변식 검사도
**한 겹 안쪽 함수를 부르는 쪽 위치로 재도록** 확장됐다(`:458-472`) — 검사를 고치면서
검사에 구멍을 내는 자리를 담당자가 먼저 막았다.

---

### 3. ⛔ **M3 — 세 번째 변이. `clear_alert` 경로를 관문이 안 본다**

T10 은 억제 판정을 행동으로 돌리면서 **`clear_alert() { :; }`**(`monitor-selftest.sh:1392`)
로 물린다. 그래서 `check_market_stale` 이 **언제 해소를 통보하는지**는 관문 밖이다.
구조 검사(`:1564`)도 `_market_batch_ran_this_month` 와 `raise_alert marketstale` 두
문자열만 본다.

**M3 — 판정 불가(`ref = n/a`/`none`) 조기 반환 한 줄을 지운다**(`monitor.sh:1144`).
그러면 `[[ "n/a" < "2026-06" ]]` 가 **거짓**이라 `stale=0` 으로 흘러
`clear_alert marketstale "시장지수 기준월 회복 (n/a ≥ 기대 2026-06)"` 를 부른다.

```
대조군   ref=n/a·none·빈값 3회 → clear_alert 호출 0회   T10 6통과/0실패 · 관문 163/0/3 rc=0
M3       같은 3회             → clear_alert 호출 2회   T10 6통과/0실패 · 관문 163/0/3 rc=0  ← 생존
```
**대조군과 숫자가 한 자리도 다르지 않다.**

**무엇이 문제인가.** `ref` 가 `n/a`(`market_price_index` 표 없음 = 016 미적용) 또는
`none`(완결 행 0)인 상태는 **실재하는 고장**이고, 그때 사람이 받는 문장은
*"시장지수 기준월 회복"* + `n/a ≥ 기대 2026-06` 이라는 **성립하지 않는 비교**다.
`CR42-3` 이 차단한 `인증서 여유 회복 (최단  9999일)` 과 **같은 모양**이고,
`CR-040`·`CR42-3`·`CR43-1` 이 각각 차단한 *"못 본 것을 해소라고 말하지 않는다"* 의
**네 번째 자리**다.

**차단하지 않는 이유는 하나뿐이다 — 오늘 실려 있는 코드는 옳다.** 조기 반환이 있고,
내가 대조군으로 쟀다(clear 0회). 이건 **관문의 구멍**이지 실린 결함이 아니다.
그리고 닫는 데 **두 줄**이면 된다(§8 CR44-2).

---

### 4. ⚠️ `CR43-3` — **절반만 됐다. 새로 쓴 T10 에는 가드가 없다**

`nz()` + `harn_if()` 는 T2(`:198`·`:227`)와 T3b(`:297`·`:321`)에 정확히 들어갔다.
내가 지적한 `:318` 의 `[[ "$ref" < "$exp" ]]` 도 `:317` 의 `nz` 뒤로 갔다. **거기까지는 옳다.**

**그런데 이번 라운드가 새로 쓴 T10 에는 `nz` 도 `harn_if` 도 없다.** 두 방향 다 실측했다
(T10 코드를 그대로 떼어 `date` 가 한 번 죽은 상황을 만든다):

| 무엇이 비었나 | 결과 | 방향 |
|---|---|---|
| `FROZEN_REF`(`:1472`) 한 번 | **실패 3 · 하네스오류 0** — `밀린 날 0일 → 0통` 으로 *"배치가 안 도는데도 조용하다"* 가 붉는다 | **없는 결함을 보고** |
| 스테일 달의 `dexp`(`:1424`) 한 번 | **통과 2 · 실패 0 · 하네스오류 0** — 볼륨 모형이 조용히 **91통 → 61통** 으로 약해진다 | **있는 결함을 놓친다** |

두 번째가 `CR41-6`·`SR38-9` 가 *"이쪽이 더 나쁘다"* 고 한 방향이다. `old_daily >= 40`
하한이 유일한 방어인데, 스테일 달 2개가 죽으면 그것도 뚫린다(91→31).

**그리고 `want()`/`avoid()` 의 HARN 그물에도 안 걸리는 자리를 하나 더 봤다.**
내 M1 관문 실행에서 SR39-1 교차 검사 2건이 붉었다:

```
(교차) auth.log 만 믿는다 — 같은 길이로 덮어쓴 침입을 반증할 방법이 없다      FAIL
(교차) 두 출처가 어긋난 사실이 알림 본문에 없다                                FAIL
```

M1 은 `check_market_stale` **한 줄**만 바꾼 사본이고, 대조군 사본에서는 같은 두 건이
**PASS** 였다. 바로 뒤의 `(교차 대조군)`·`(교차) journald 가 사라지면` 은 M1 에서도
PASS 였으므로 가짜 `journalctl` 자체는 살아 있었다 — 즉 `rj1` 두 번째 실행에서만
`journalctl -n 1` 이 실패해 `jd_ok=0` 이 된 것이다(그러면 `delta=0`·`jd` 미설정이라
`sshpw` 가 안 뜨고 두 검사가 정확히 이렇게 붉는다).
⚠️ **정직하게 적는다** — 그때 나는 `pytest` 를 동시에 돌리고 있었다. 즉 이건
`CR43-3` 이 말한 **부하 조건**이고, 그 조건에서 `want()` 는 로그 파일이 **있으므로**
HARN 이 아니라 **FAIL** 로 보고한다. 하네스가 못 만든 것이 로그 파일이 아니라
**픽스처 실행**일 때는 그물이 없다.

→ 그래서 `monitoring.md:684-685` · `DEPLOY.md:1172-1174` 의 *"HARN 이 0 이면 초록/빨강을
근거로 쓸 수 있다"* 는 **아직 참이 아니다.** T2/T3b 에서만 참이다.

---

### 5. `SR39-1` journald 교차 — **설계 판단은 옳다. 오탐도 안 난다. 그런데 안 꺼진다**

가짜 `journalctl` 로 배선해 직접 돌렸다.

| 시나리오 | 기대 | 실제 |
|---|---|---|
| **A** journald 정상 · 평상시 증가 **10회** | SSH 관련 경보 0 | **0건** ✅ · 요약은 매회 `SSH2차 : journald 같은 구간 0건 (auth.log 0건 · 기대 0/0)` |
| **C** journald 에만 성공 흔적(auth.log 0건) | `sshpw` | **뜬다** ✅ 본문에 `⚠️ 두 출처의 수가 다르다(journald 1 > auth.log 0)` |
| **B** journald 가 **한 번** 응답 실패 | `sshjournal` 1통 | **뜬다** ✅ |
| **B'** journald 복귀 + 정상 3회 | 해소 | **안 꺼진다** ⛔ `.active` 생존 |

**① 설계 판단(비교가 아니라 각자 세기)은 옳다.** `--since` 가 초 단위라 창 경계에서
두 출처가 1 어긋나는 것은 정상이고, 그 차이를 경보로 쓰면 오탐이 된다. 지금 코드는
차이를 **본문 문장**(`jd_gap`)으로만 싣고 경보 조건은 `delta > 0 || jd > 0` 이다 —
A 에서 10회 완전 침묵, C 에서 확실히 검출. **양쪽 다 맞다.**

**② 한계 서술도 정직하다.** *"journald 도 root 면 지운다 — 침입을 불가능하게 만들지
않고 두 곳을 다 지워야 하게 비용을 올릴 뿐"*(`monitor.sh:772-775`)은 사실이고,
그 비용을 치른 사실을 `sshjournal` 이 알리게 한 것도 일관된다. **자원 실측을 서버
절차(`DEPLOY.md` ── 4)로 넘긴 판단도 옳다** — 로컬에서는 잴 수 없다.

**③ 그런데 `sshjournal` 에는 `clear_alert` 가 없다.** `monitor.sh` 전체에서
`raise_alert sshjournal` 은 있고 `clear_alert sshjournal` 은 **한 번도 안 나온다**.
같은 함수 안의 `authfresh`(똑같이 "출처가 죽었다" 부류)는 `:604` 에서 꺼진다.
그래서 journald 가 잠깐 흔들리기만 해도 일일 요약 머리말이 **영영**
`미해소 N건 (… sshjournal …)` 이 된다. 이 저장소가 스스로 쓴 문장이
*"안 꺼지는 경보는 곧 무시되는 경보다"*(`monitor-selftest.sh:696-697`)이고,
`CR42-1` 을 차단한 근거가 *"조치 불가 알림이 통로를 선점하면 `sshpw` 가 울어도 같은
손짓으로 넘어간다"* 였다. → **CR44-1(중).**

**④ 5분 경로에 시간 상한이 없다.** `journalctl` 두 번 다 `timeout` 없이 돈다
(웹 검사는 `--max-time 8` 이 있다). 저널이 2.0G 인 서버에서 I/O 가 막히면 `--fast` 가
`flock` 아래 매달리고, 그 결과는 `fast_dead` 로 드러난다. 잡히긴 하지만 원인이
가려진다. → **CR44-3(하)**.

---

### 6. `SR39-6` 위생 관문 — **오탐 실측을 내가 다시 쟀다. 값이 같다**

담당자 규칙을 그대로 떼어 저장소 전체에 돌렸다.

| | 담당자 | 내 측정 |
|---|---|---|
| 관문 대상 파일 | 39 → 68 | **68** ✅ |
| `_SECRET_ENV_ASSIGN` 값 12자 이상 | 2건(둘 다 원장의 설명용 가짜값) | **2건** — `code-review-log.md:8137`(selftest 픽스처 인용) · `security-review-log.md:9388` ✅ |
| 값 **16자 이상** | 0건 | **0건** ✅ (14자 이상도 0건) |
| `_BARE_SECRET` | 0건 | **0건** ✅ |

**16자 선은 타당하다.** 이 저장소가 담을 키는 전부 32자 이상이고(NEIS 32 hex ·
Kakao 32 hex · Fernet 44 · 텔레그램 봇토큰 45), 고전적인 이름
(`*_API_KEY`·`*_SECRET`·`*_TOKEN`·`*PASSWORD*`)은 옛 규칙이 **8자부터** 잡는다.
12~15자 구간에 실제로 있던 것은 원장의 예시 두 개뿐이다. **정상 코드를 막지 않는다** —
관문 자신에 대한 시험 두 개(잡아야 하는 6형태 · **막으면 안 되는 7형태**)도
방향이 맞고, 내가 따로 먹인 정상 줄들도 통과했다.

**다만 `_BARE_SECRET` 에는 합성값 면제가 없다.** 이 규칙만 `_MASKED` 하나로 거르고
`_PLACEHOLDER`·`_SYNTHETIC` 를 안 태운다(`test_script_hygiene.py:195-198`).
그래서 **`sk-ant-` 접두 + `EXAMPLE` 이 들어간 명백한 가짜값**을 문서에 적으면 관문이
붉는다(직접 먹여 확인). 하필 그 규칙을 설명해야 하는 문서(`security-review-log.md`·
이 원장·`DEPLOY.md`)가 전부 관문 **안**이라, 다음에 이 규칙을 예시로 설명하려는 사람이
막힌다. 값 자체는 `_SYNTHETIC.fullmatch` 에 걸리므로 **한 줄**이면 닫힌다.
→ **CR44-5(하)**.

---

### 7. 15번째(`check_peer_alive`) 와 `log()` 세탁

**15번째 — 조치는 옳다. 30시간도 타당하다.** `--fast` 쪽이 `[ -z "$last" ]` 에서
조용히 `return 0` 하던 자리에 `first_fast_run` 기준의 유예를 넣었고, 임계는
`DAILY_MAX_HOURS=30` 으로 **아래 "낡음" 판정과 같은 값**이다 — 규칙이 하나다.
일일 점검은 09:05 에 하루 한 번이라 24시간 + 6시간 여유는 맞고, 설치 직후 오탐도 없다.
T6b 3케이스(① 설치 직후 무경보 + `first_fast_run` 기록 ② 40시간 뒤 경보
③ 반대쪽 `fast_dead` 생존)는 **이 결함에 대해서는 충분하다** — 대칭의 양쪽과
오탐 대조군이 다 있다.

**그런데 그 근거 문장이 사실과 다르다.** `monitor.sh:906-907` 과
`monitoring.md:621-622` 가 *"**지금 배포가 정확히 크론 2줄을 새로 넣는 일이다**"* 라고
적는데, 이 저장소의 **자기 실측**이 그 반대다:

* `CR-041` — *"크론 — 우리 3줄(`10 4 1 * *` 배치 래핑 · `*/5` fast · `5 9` daily)"*
* `SR-038` — *"root 크론 | 잡 **8줄** ✅ (recostock 1 · civicniche 1 · adsense 3 · **realestate 3**)"*
* `DEPLOY.md §9-1` — 바뀌는 것은 **셸 5개뿐** · *"서비스 중단 0 · 재기동 0"* · **crontab 단계 자체가 없다**

즉 크론 두 줄은 **2026-07-30 에 이미 들어가 있다.** 결함은 실재하고 조치도 옳지만,
그 **위험이 지금 실재한다는 근거는 재 보지 않은 문장**이다. 이 라운드가 스스로
*"문서가 안다고 적었지만 아무도 안 잰 것"* 을 반성한 바로 그 형태라 적어 둔다.
→ **CR44-4(하)**.

**`log()` 세탁 — 닫혔다. 문장이 아니라 행동으로 확인했다.**
배치가 `실패: postgresql+psycopg://re:<pw>@… · SERVICE_KEY=… · 한도 1,026,560,000원`
을 찍게 하고 감시 로그를 직접 봤다:

```
2026-08-02 00:26:07 ALERT job_probe :: 배치 실패: probe (종료코드 3 · 1초)
사유: 실패: postgresql+psycopg://re:<redacted>@172.20.0.2:5432/db · SERVICE_KEY=<redacted> · 한도 <num>원
```

세 값 전부 평문이 아니다. **그리고 관문은 이것을 구조로만 본다** —
`grep -A2 'log() {' | grep -q '| scrub'`(`monitor-selftest.sh:1242`). 같은 T7 의
이웃들(`send_telegram` 경로)은 **행동으로** 보는데 이쪽만 문자열이다. 이 라운드가
스스로 세운 문장이 *"못 도는 검사는 없는 검사다"* 이고, 여기는 세 줄이면 행동이 된다.
→ **CR44-7(정보)**.

**같은 형태("문서가 안다고 적었지만 아무도 안 잰 것")가 더 있는가 — 하나 남아 있다.**
`monitoring.md §8-4 아직 안 고친 것` 목록이 `SR36-3` 잔여(따옴표 낀 키)와
`SR36-4`(`log()` 세탁)를 **여전히 미해결로** 적는다. 둘 다 이번 라운드에 닫혔고
같은 문서 `:150-161` 이 그렇게 적는다. 방향은 반대(방어를 과장하는 게 아니라
성과를 낮춰 적는 쪽)지만 **목록을 아무도 안 맞췄다**는 사실은 같다.
→ **CR44-8(정보)**.

---

### 8. 서버 반영 절차(`DEPLOY.md §9-1`) 검토 — **실행하지 않았다. 검토만 했다**

**순서·묶음 판단은 옳다.**

* **라이브러리 먼저**가 맞다. `monitor.sh` 는 `monitor-lib.sh` 를 `source` 하므로
  교체 중 5분 크론이 끼면 두 조합 중 하나가 돈다. **옛 본체 + 새 라이브러리**는
  안전하다(새 lib 이 더한 것은 `scrub` 규칙과 `log()` 세탁뿐이고 인터페이스는 그대로 —
  내가 함수 목록을 대조했다. 새 본체가 lib 에서 쓰는 것은 전부 예전부터 있던 것들이다).
  반대 조합은 **그 5분 동안 `log()` 세탁과 새 비밀 규칙이 없는 채로** 돈다.
* **5개를 함께**도 맞다. `CR42-1` 은 3층인데 그중 ①②가 `market-index.sh`·`job-run.sh`
  에 산다 — `monitor.sh` 만 올리면 감시는 침묵하는데 배치는 여전히 *"배치 실패"* 를
  보낸다(= 사용자가 받는 문장이 최악 조합).
* **롤백은 실제로 된다.** `/root/backup-monitor-<날짜>/` + sha256 대조가 있고,
  `kv` 를 안 건드리는 것도 옳다 — 새 키(`blind_daily`·`first_fast_run`·`sshpw_mtime`·
  `sshpw_jd`)는 옛 코드가 **읽지 않으므로** 되돌려도 무해하고, 없으면 첫 회에 기준값만
  잡는다는 설명도 코드와 맞다(각 사용처에 `[ -n ... ]`/`case` 가드가 있는 것을 확인했다).

**그런데 빠진 단계가 있다.**

1. **돌고 있는 스크립트를 제자리에서 덮어쓴다.** ── 2 의
   `install -m 750 … /opt/realestate/scripts/<이름>` 은 **원본 inode 를 그대로 잘라 쓴다**.
   `*/5` 크론이 `monitor.sh` 를 실행하는 중에 그러면, bash 는 스크립트를 **오프셋 단위로
   나중에 읽으므로** 남은 절반이 새 파일의 엉뚱한 위치가 된다. §2 가 5분 창을 그렇게
   꼼꼼히 따지면서 **이쪽 창은 안 본다.** 고치는 법은 한 줄이다 —
   같은 디렉터리에 임시 이름으로 놓고 `mv -f`(rename 은 원자적이고, 돌던 프로세스는
   옛 inode 를 계속 읽는다). ── 6 롤백의 `cp -a` 도 같다. → **CR44-6(하)**.
2. **롤백 뒤 재확인이 없다.** ── 6 은 `sha256sum` 만 시킨다. 되돌린 조합이 실제로
   도는지(`monitor-selftest.sh` 또는 `RE_MON_DRY_RUN=1 --fast`)를 한 줄 더 넣을 것.
3. **서버에서 돌린 자체검사의 기대값이 로컬과 다르다.** ── 3 은
   *"윈도우에서 SKIP 되던 chmod 2건이 실제로 돈다"* 만 적는데,
   `/opt/realestate/scripts` 에는 `../docs/05-monitoring/monitoring.md` 가 없으므로
   T8 3건이 SKIP 1건으로 줄고 **T7 의 문서 일치 검사 1건은 SKIP 조차 없이 사라진다**
   (`monitor-selftest.sh:1251` 이 `[ -f "$DOC" ]` 로만 감싸고 `else` 가 없다).
   실측: 문서가 없는 사본에서 **167/0/2 → 163/0/3**. 사람이 숫자로 판단하는 절차이므로
   *"실패 0 · 하네스오류 0 만 본다"* 를 명시하거나 T7 에도 `skip` 을 달 것.
4. **`deploy/` 셸 5개가 아직 git 미추적이다**(`git status` 가 `??`). ── 2 의
   *"저장소를 서버에서 pull 한 뒤 cp"* 는 **커밋 뒤에만** 성립한다. 지금 상태로는
   `scp` 경로만 유효하다. 절차서에 그 전제를 적을 것.
5. *"그 조합은 **깨지고**"*(`:1220`)는 과장이다. 새 본체 + 옛 라이브러리는 **돈다** —
   잃는 것은 `log()` 세탁과 새 비밀 규칙이다(= 보안 후퇴이지 고장이 아니다).
   권고 자체는 옳으므로 문장만 사실로 바꿀 것.

---

### 9. 지적 사항

| ID | 심각도 | 내용 | 수정 제안 |
|---|---|---|---|
| **CR44-1** | **medium** | **`sshjournal` 에 해소 경로가 없다.** `monitor.sh:799` 가 `raise_alert sshjournal` 을 하는데 `clear_alert sshjournal` 은 파일 전체에 **없다**. 실측: 가짜 `journalctl` 을 1회 실패시키면 경보가 켜지고, 정상 복귀 + 3회 실행 뒤에도 `.active` 생존 → 일일 요약 머리말이 영영 `미해소 N건 (sshjournal)`. 같은 함수의 형제 `authfresh`(동일 부류)는 `:604` 에서 꺼진다. 이 저장소 자신의 문장이 *"안 꺼지는 경보는 곧 무시되는 경보다"* 이고 `CR42-1` 차단 근거가 통로 선점이었다 | `jd_ok=1` 이고 `prev_jd` 가 0/빈값이 아니었던 다음 실행에서 `clear_alert sshjournal "두 번째 출처(journald) 복구"` 를 부를 것. 의도적으로 끈적하게 둘 거라면 **그렇다고 적고** `DEPLOY.md §9` 경보 키 표의 "사람이 할 일" 에 `rm -f …/alerts/sshjournal.active` 를 명시할 것 |
| **CR44-2** | **medium** | **`check_market_stale` 의 `clear_alert` 경로가 관문에서 무관측 → M3 생존.** T10 이 `clear_alert() { :; }`(`monitor-selftest.sh:1392`)로 물리고 구조 검사(`:1564`)는 `raise` 쪽 두 문자열만 본다. 변이(판정 불가 조기 반환 `monitor.sh:1144` 제거) → `ref=n/a`/`none` 에서 **`시장지수 기준월 회복 (n/a ≥ 기대 …)` 거짓 해소**가 나가는데 **T10 6통과/0실패**. `CR42-3` 의 `인증서 여유 회복 (최단  9999일)` 과 같은 모양이고 이 저장소가 네 번째로 만나는 자리다. ⚠️ 실린 코드는 옳다(대조군 clear 0회) — 관문의 구멍이다 | T10 의 가짜 배선을 `clear_alert() { MS_CLEARED=$((MS_CLEARED+1)); }` 로 바꾸고, `ref` 가 `n/a`·`none`·빈값일 때 **`MS_CLEARED -eq 0`** 을 단언할 것(두 줄). 합격선: 위 M3 가 `실패 >= 1` 로 죽을 것 |
| **CR44-3** | **medium** | **`CR43-3` 이 절반만 됐다.** `nz()`/`harn_if()` 가 T2·T3b 에는 들어갔는데 **이번 라운드가 새로 쓴 T10 에는 없다**. 실측 두 방향: `FROZEN_REF`(`:1472`) 한 번 비면 **실패 3 · HARN 0**(없는 결함 보고) · 스테일 달의 `dexp`(`:1424`) 한 번 비면 볼륨 모형이 **91→61통** 으로 조용히 약해지고 **전건 통과 · HARN 0**(있는 결함 놓침 — `CR41-6` 이 "더 나쁘다"고 한 방향). 별개로 M1 관문 실행에서 SR39-1 교차 2건이 붉었는데(대조군은 PASS · 뒤 검사는 PASS) 원인은 가짜 `journalctl` 실행 실패이고, `want()` 는 **로그 파일이 있으므로** HARN 이 아니라 FAIL 로 보고한다 | ① T10 의 `dexp`·`dref`·`ndays`·`FROZEN_REF` 에 `nz` 가드 + 루프 뒤 `harn_if` ② 픽스처 바이너리(가짜 `journalctl`)가 기대대로 동작하는지 **한 번 확인하고 아니면 `harn`** ③ 그 전에는 `monitoring.md:684-685`·`DEPLOY.md:1172-1174` 의 *"HARN 0 이면 근거로 쓸 수 있다"* 를 "T2·T3b 한정" 으로 좁혀 적을 것 |
| **CR44-4** | low | **근거 문장이 실측과 어긋난다.** `monitor.sh:906-907` · `monitoring.md:621-622` 의 *"지금 배포가 정확히 크론 2줄을 새로 넣는 일이다"* 는 `CR-041`(우리 3줄) · `SR-038`(realestate 3줄) · `DEPLOY.md §9-1`(crontab 단계 없음)과 전부 어긋난다. 크론은 2026-07-30 에 이미 들어갔다. 결함·조치는 옳고 **근거만 안 잰 문장**이다 | 두 곳을 *"크론 한 줄이 사라지거나 다음에 다시 설치할 때"* 로 고칠 것. 조치는 그대로 둘 것 |
| **CR44-5** | low | **`_BARE_SECRET` 에 합성값 면제가 없다.** `test_script_hygiene.py:195-198` 이 `bare` 에는 `_MASKED` 만 태우고 `_PLACEHOLDER`·`_SYNTHETIC` 를 안 태운다. 직접 먹여 확인: `sk-ant-` 접두 + `EXAMPLE` 이 든 명백한 가짜값이 **관문을 붉힌다**. 그 규칙을 설명해야 할 문서(원장 2종·`DEPLOY.md`)가 전부 관문 안이라 다음 사람이 막힌다. 오늘 위반 0건이므로 잠재 오탐 | `if bare and not _MASKED.search(...) and not _SYNTHETIC.fullmatch(bare.group(0)):` 한 줄. 값이 `[a-z0-9_-]` 만으로 이뤄지고 `example`/`fake` 등을 포함할 때만 면제되므로 진짜 키는 계속 잡힌다 |
| **CR44-6** | low | **`DEPLOY.md §9-1` — 돌고 있는 스크립트를 제자리에서 덮어쓴다.** ── 2 의 `install -m 750 …`(과 ── 6 롤백의 `cp -a`)는 원본 inode 를 잘라 쓴다. `*/5` 크론이 `monitor.sh` 실행 중이면 bash 가 남은 절반을 새 파일에서 읽는다. §2 가 5분 창을 그렇게 따지면서 이 창은 안 본다 | 같은 디렉터리에 `install -m 750 … <이름>.new` 로 놓고 **`mv -f`**(원자적 rename). 그리고 ── 6 뒤에 `RE_MON_DRY_RUN=1 ./monitor.sh --fast` 재확인 한 줄. 함께: `:1220` 의 *"그 조합은 깨진다"* → *"그 5분 동안 log() 세탁과 새 비밀 규칙이 빠진 채로 돈다"* |
| **CR44-7** | info | `log()` 세탁을 관문이 **구조로만** 본다(`monitor-selftest.sh:1242` 의 `grep -A2 … '| scrub'`). 같은 T7 의 이웃(`send_telegram`)은 행동으로 본다. 나는 행동으로 확인했고 **닫혀 있다** — 다만 검사는 문자열이다 | `RE_MON_LOG` 를 임시로 두고 `log 'SERVICE_KEY=<가짜>'` 뒤 파일에 원문이 없는지 볼 것(세 줄) |
| **CR44-8** | info | `monitoring.md §8-4 아직 안 고친 것` 이 `SR36-3` 잔여·`SR36-4`(`log()` 세탁)를 여전히 미해결로 적는다. 둘 다 이번 라운드에 닫혔고 같은 문서 `:150-161` 이 그렇게 적는다. (`CR40-8`·`SR36-5` 는 실제로 여전히 열려 있다 — `clear_alert` 가 `send_telegram` 실패와 무관하게 `.active` 를 지우는 것을 코드에서 확인했다) | 두 항목을 지우고 남은 셋만 둘 것 |
| **CR44-9** | info | `api5xx` 만 형제 검사 중 유일하게 `clear_alert` 가 없다(`logperm`·`logleak`·`logfresh` 는 있다). 5xx 가 한 번 나면 일일 요약 머리말이 계속 `미해소`. `API5XX_MIN=1` 이라 문턱이 낮다. (이번 라운드 변경은 아니다) | 델타가 0인 실행에서 `clear_alert api5xx` 를 부르거나, 끈적함이 의도라면 §9 표에 적을 것 |
| **CR44-10** | info | `check_peer_alive` 가 `kv_get first_fast_run`·`last_daily_run` 을 **숫자 가드 없이** 산술에 쓴다(`:912-914`·`:919`). 같은 파일 `:783-786` 은 `prev_at` 에 `case "$x" in ''\|*[!0-9]*)` 관용구를 쓴다. 값이 깨지면 `set -u` 아래 산술이 실패해 **조용히 경보가 안 뜬다**(fail-open 방향). `kv` 는 0600 root 라 오늘 실해는 없다 | `:783` 과 같은 `case` 가드를 붙이고, 깨졌으면 기준값을 다시 잡을 것 |
| **CR44-11** | info | `deploy/{monitor,monitor-lib,monitor-selftest,job-run,market-index}.sh` 5개가 **git 미추적**이다. `DEPLOY.md §9-1 ── 2` 의 *"저장소를 서버에서 pull 한 뒤 cp"* 는 커밋 뒤에만 성립한다. 로컬 `.git/hooks/` 에는 커밋 차단 훅이 실제로 설치돼 있지 않다(샘플뿐) | 게이트 통과 뒤 커밋에 5개를 반드시 포함할 것. 절차서에는 그 전제를 한 줄 |

---

### 10. 판정 사유

**내가 §10 에 적은 합격선을 그대로 재고, 그대로 충족됐다.**

`CR43-1` 은 **내 하네스**로 다섯 자리를 다 봤다 — `--fast` 의 clear 0건 · 해소 0통 ·
`.active` **와 `.sent`** 생존(쿨다운이 실제로 유지된다) · 요약이 사유를 말함 ·
그리고 **되돌아오는 길**(인증서 복귀 시 실제 해소 + `kv/blind_daily` 비움). 내가 특별히
물었던 *"영구 봉인"* 은 구조적으로 불가능하고, 그 자리가 관문에 케이스로 있다.
되돌린 사본(M4)은 결함을 그대로 재현하고 T5b 가 그 줄을 본다.

`CR43-2` 는 **"후 = 0통" 이 상수에서 계산으로** 바뀌었고, 내가 심었던 M1·M2 가
각각 **4실패 / 1실패**로 죽는다(관문 전체로도 M1 은 156/7/rc=1). 상한 단언과 쿨다운
일치 단언이 각각 다른 변이를 잡는다. 그리고 그 판정이 **`docker`·`psql` 없이 돈다** —
*"못 도는 검사는 없는 검사다"* 를 코드로 지켰다.

**그럼에도 차단하지 않는 이유를 결과로 적는다.** 이번에 찾은 셋 중
`CR44-2`(M3)와 `CR44-3`(T10 HARN)은 **실린 코드가 아니라 관문의 구멍**이고 —
내가 대조군으로 잰 오늘의 동작은 둘 다 옳다 — `CR44-1`(sshjournal)만이 살아 있는 동작인데
그 피해는 **거짓 안심도 침묵도 아니고 "안 꺼지는 이름 하나"** 이며, 원인을 고친 뒤
손으로 끄는 절차가 `monitoring.md:317-320` 에 이미 적혀 있다. 반대로 **미루는 비용은
날짜가 박혀 있다** — 서버는 아직 `SR-038` 시점이라 `CR42-2`(트립와이어가 `rm` 에 눈멂)와
`CR42-3`(인증서 fail-open)이 **지금 열려 있고**, `CR42-1` 폭주는 **2026-09-01** 에 터진다.
`CR-043` 이 스스로 적은 *"홀드는 옳지만 길게 끌 수 없다"* 가 지금 적용될 자리다.

**수렴했는가 — 아직이다. 그러나 방향은 맞다.**
심각도는 확실히 내려갔다: `CR-042` 는 차단 3, `CR-043` 은 차단 2, 이번은 **0**이다.
그런데 **개수는 안 줄었고(11건), 새로 나온 것이 전부 같은 두 집안이다.**

* **집안 ①: `clear_alert` 를 부를 자격.** `CR-040`(로그 3종) → `CR42-3`(인증서) →
  `CR43-1`(모드 대칭) → 이번 `CR44-2`(M3, `marketstale`) · `CR44-1`(`sshjournal` 은
  반대로 **영영 clear 를 안 부른다**). 네 라운드 연속 같은 질문이다.
* **집안 ②: 관문이 자기 실패를 검사 결과와 섞는다.** `CR41-6`(파이프라인) →
  `SR38-9`(임시파일) → `CR43-3`(날짜 루프) → 이번 `CR44-3`(T10 · 픽스처 바이너리).
  고칠 때마다 **그 라운드에 새로 쓴 코드**가 다음 자리가 된다.

**그래서 다음 라운드의 기준은 하나면 된다 — 새 검사를 쓸 때 두 가지를 먼저 정할 것:**
**(가) 이 판정이 `clear` 를 부를 수 있는가, 부른다면 관문이 그것을 보는가.**
**(나) 이 검사가 쓰는 픽스처·값이 비었을 때 `ok`·`ng` 중 어디로 가는가.**
(가)를 **관문이 실제로 보는** 것은 `logperm`·`logleak`·`logfresh`·`cert`·`logblind`·`warn_*`
여섯뿐이다(`ALERT-CLEARED` 를 단언하는 자리가 그 여섯이다). `marketstale`·`dbstruct`·
`authfresh`·`authshrink`·`daily_dead`/`fast_dead` 는 **clear 경로는 있는데 관문이 안 보고**,
`sshjournal`·`api5xx` 는 **경로 자체가 없다**(`authfake`·`authedit`·`sshpw`·`oom_*` 는
쉼도 0 의 델타형이라 끈적한 것이 의도로 보이지만, 그렇다고 적힌 곳이 없다).
(나)를 갖춘 것은 T2·T3b 뿐이다. **그 두 목록이 다 차면 수렴했다고 말할 수 있다.** 지금은 아니다.

---

### 11. 다음 라운드 전에 (차단 아님 · 배포와 함께 가도 된다)

1. `CR44-1` — `clear_alert sshjournal` 두 줄. **서버에 올리기 전에 같이 가는 것이 낫다**
   (journald 가 흔들리는 순간부터 머리말이 더러워진다).
2. `CR44-2` — T10 의 `clear_alert` 가짜를 세는 것으로 바꾸고 `n/a`·`none` 에서 0 단언(두 줄).
   합격선은 §3 의 M3.
3. `CR44-3` — T10 에 `nz`/`harn_if`, 픽스처 실패를 `harn` 으로. 그 전에는 문서의
   *"HARN 0 이면 근거"* 문장을 좁힐 것.
4. `CR44-6` — `install` → `mv -f`. 배포 절차라 **올리기 전에** 고칠 것.

---

### 리뷰 위생

* **`grep -rn "MUT-" deploy/` 시작 0 · 종료 0.** 변이 M1·M2·**M3**·M4 는 전부
  스크래치패드의 **사본**(`deploy/` 통째 복사)에만 심었다. 리뷰 종료 시점
  `git status --porcelain` 은 리뷰 시작과 같다(이 원장과 `.review-state.json` 제외).
* **실패 주입 0건 · 서버 무접속.** 감시 실행은 전부 로컬 격리 — `RE_MON_STATE`/`RE_MON_LOG`
  는 `mktemp -d` 아래, `RE_MON_DRY_RUN=1`, URL 은 닫힌 포트 `127.0.0.1:9`,
  `RE_MON_CRED_FILES` 는 없는 경로. `ALERT-SENT` **0건 · 사용자에게 간 알림 0통**.
* 재현 하네스는 **내가 새로 짰다**(담당자 T5b·T10 을 쓰지 않았다): CR43-1 5단계 ·
  T10 두 구획 추출 · journald 3시나리오 · 위생 규칙 재측정 · T10 하네스오류 2방향.
  T10 추출본은 관문의 단언문을 **글자 그대로** 옮겼고, 뽑는 방식(`ext`)도 같다.
* `monitor-selftest.sh` 전체 실행 **5회**: 원본 기본값 1회(167/0/2/HARN0) ·
  축약(`SELFTEST_MONTHS=3`) 대조군 1회(163/0/3 — 문서가 없는 사본이라 T7 1건이 SKIP 없이
  사라지고 T8 3건→SKIP 1건) · M1(156/7/3) · M2(162/1/3) · M3(163/0/3).
  `pytest` 전체 1회 + `--collect-only` 1회. 변이 격리 실행(T10 추출본) 4회.
* **M1 관문 실행 때 `pytest` 를 동시에 돌리고 있었다.** 그때 붉은 SR39-1 교차 2건은
  M1 과 무관하며, 그 사실 자체를 `CR44-3` 의 증거로 적었다 — 숨기지 않는다.
* 서버 관련 사실은 `CR-041`·`SR-038` 기록에서만 인용했고, 인용임을 밝혔다.
* 이 항목에 비밀 형태 문자열(`sk-ant-` 접두 · `KakaoAK` + 값)을 **적지 않았다** —
  `CR44-5` 가 지적하는 그 관문에 스스로 걸리지 않기 위해서다.

---

## CR-045 · 2026-08-03 · `CR-044`/`SR-040` 반영분 + **PM 이 직접 쓴 CR45-1 프로브** (범위 `deploy/monitor.sh` · `deploy/monitor-selftest.sh` · `deploy/DEPLOY.md` · `docs/05-monitoring/monitoring.md` · 기준 `199d9fe`)

**판정: FAIL** — 차단 **2건**(H). 둘 다 **이번 라운드가 새로 넣은 CR45-1 코드**에 있다.

이 라운드는 "관문이 세 번 거짓 초록을 냈다"는 자각에서 출발했다. 그 자각은 옳다. 그런데
**네 번째 거짓 초록이 그 자각으로 만든 코드 안에 그대로 있다.**

* **CR45-1(H)** — 프로브는 *"누가 `-o cat` 을 빼면 눈멂 탐지가 영원히 안 돈다"* 를 막겠다고
  선언하는데, **프로브와 본질의가 서로 다른 명령줄**이라 **본질의에서만 `-o cat` 이 빠지면
  프로브는 깨끗하고 탐지는 죽는다.** 그 상태를 서버에서 재현했다: 공격 상태(저널 ssh 0줄)에서
  요약이 `기대 0/0 · 교차 대상 1줄` 이라고 **적극적으로 무사고를 선언**하고 경보는 0건인데,
  **자체검사는 201통과 · 실패 0 · rc=0** 이다. 이 저장소가 다섯 번째로 만나는 같은 형태다.
* **CR45-2(H)** — 새로 넣은 clear 가드(`jd_probe_bad = 0`)를 **관문이 못 본다.** 해당 단언
  (`monitor-selftest.sh:1314`)이 도는 시나리오(rj7)는 `sshjournal` 을 **한 번도 켜지 않아서**
  `clear_alert` 가 조기 return 한다 — 즉 **무엇을 지워도 통과하는 공허한 단언**이다.
  가드를 빼는 변이를 심으면 자체검사는 **201/0/0 · rc=0**, 그런데 런타임에서는
  **거짓 해소가 나가고 `.active` 가 지워진다**(둘 다 실측).

> 먼저 인정할 것 — 이번 델타의 **나머지는 튼튼하다.** 프로브 자체는 하중을 받고(변이 M1 →
> 3건 붉음), PM 이 걱정한 *"가짜가 `--until` 로 분기하니 나중에 본질의에 `--until` 을 붙이면
> 조용히 죽는다"* 는 **이미 대조군이 잡는다**(변이 M6 → 5건 붉음). `new_sshd`·문턱 무력화도
> 각각 3건씩 죽는다. `HARN` 은 `rc` 를 1 로 만들므로 **하네스 승격이 결함을 숨기지 않는다.**
> `(x9)` 의 결정성 수정과 `(교차)` 의 "응답 실패로 모사" 수정은 리눅스에서 실제로 옳다.

### 0. 내가 직접 잰 것 (전부 서버 격리 사본 `/root/rev-cr45` · 종료 시 삭제)

* 손에 든 것과 서버 `/opt/realestate/scripts` 의 셸 5개가 **sha256 5/5 일치** →
  리뷰 대상 = 서버에 도는 것. `/opt` 는 **읽기만** 했다(`cp` 로 빼내기 · 해시 · `ls` 뿐, 쓰기 0).
* 기준 실행(문서 포함 사본): **통과 201 · 실패 0 · 건너뜀 0 · 하네스오류 0 · rc=0**, 66초.
* 실측 재확인 (서버 systemd 249):
  · `journalctl -u ssh -u sshd --since @<미래> --until @<+60> --no-pager -o cat` → **0바이트**
  · 같은 질의에서 `-o cat` 만 빼면 → **`-- No entries --` (stdout)** — PM 주장과 일치.
  · 프로브 비용 **0.019초** · 5분 창 조회 **0.019초**.
  · 24시간 ssh 유닛 메시지 5분 버킷: **비어있지 않은 버킷 289개 · 최소 12줄**
    (문서·주석은 "최소 21" 이라고 적는다 — 결론은 유지되나 숫자가 다르다 → CR45-8).
* 심은 변이 **8종**(전부 격리 사본):

| 변이 | 무엇을 바꿨나 | 자체검사 결과 | 판정 |
|---|---|---|---|
| M1 | 프로브 무력화(`jd_probe_bad` 늘 0) | 198/**3**/0 · rc=1 | 잡힘(단 4건이 아니라 3건 — CR45-3) |
| **M2** | **본질의(`:842`)에서만 `-o cat` 제거** | **201/0/0 · rc=0** | **생존 = CR45-1** |
| M3 | 프로브·본질의 양쪽 `-o cat` 제거 | 198/3/0 · rc=1 | 잡힘(단 엉뚱한 자리에서 — CR45-7) |
| **M4** | **clear 조건에서 `jd_probe_bad=0` 제거** | **201/0/0 · rc=0** | **생존 = CR45-2** |
| M5 | 교차 j3 가짜 무력화 | 197/0/0 · **HARN 1** · rc=1 | 잡힘(하네스로 정확히 분리) |
| M6 | 본질의에 `--until` 추가 | 196/**5**/0 · rc=1 | 잡힘(PM 우려 ② 해소) |
| M7 | `new_sshd` 늘 0 | 198/**3**/0 · rc=1 | 잡힘 |
| M8 | `JD_MIN_SSHD` 문턱 무력화 | 198/**3**/0 · rc=1 | 잡힘 |

---

### CR45-1 (H · 차단) — 프로브가 **자기가 막겠다고 적은 위협**을 못 막는다

`deploy/monitor.sh:834-842`

```
jprobe=$(journalctl -u ssh -u sshd --since "@$((now_s+3600))" --until "@$((now_s+3660))" --no-pager -o cat 2>/dev/null)
...
jbuf=$(journalctl   -u ssh -u sshd --since "@$since"            --no-pager -o cat 2>/dev/null)
```

주석은 *"누가 디버깅하려고 `-o cat` 을 빼거나 systemd 가 형식을 바꾸면 `jtot` 이 늘 1 이상이
되어 눈멂 검사가 영원히 발동하지 않는다 → 그래서 매 실행 확인한다"* 라고 적는다. 그런데
**확인하는 것과 확인받아야 할 것이 서로 다른 명령줄**이다. 한쪽만 바뀌면 프로브는 계속
0바이트고 본질의만 거짓말한다 — 그 조합이 바로 주석이 말한 "누가 빼면" 의 가장 흔한 모양이다.

**재현(서버 · 현실 그대로의 가짜 journalctl = `-o cat` 이면 빈 출력, 없으면 `-- No entries --`)**

```
== 원본
SSH2차  : journald 교차 실질 불가 — 같은 300초 창에서 auth.log 는 sshd 줄 20개를 받았는데
          journald 는 ssh 메시지를 0줄 준다
   ALERT sshjournal = 떴다 · ALERT logblind = 떴다
== M2 (본질의에서만 -o cat 제거)
SSH2차  : journald 같은 구간 0건 (auth.log 0건 · 기대 0/0 · 교차 대상 1줄)
   ALERT sshjournal = **안 떴다** · ALERT logblind = 안 떴다
```

같은 M2 코드로 **자체검사 201/0/0 · rc=0**. 관문이 못 보는 이유도 명확하다 —
자체검사의 두 가짜(`JBIN`·`JMETA`)는 **둘 다 `-o cat` 을 무시한다.** 즉 "본질의만 메타줄을
받고 프로브는 깨끗한" 조합이 **픽스처 상에 존재할 수 없다.** `monitoring.md` 가 이 가짜를
*"현실 쪽으로 거짓말하는 가짜"* 라고 적었지만, 진짜 journalctl 은 `-o cat` 이 붙으면
**절대** 메타줄을 내지 않는다(위 실측). 여전히 **가짜가 현실이 아니라 우리 가정대로 군다.**

**pass 조건(둘 다)**
1. `monitor.sh` — 형식 플래그가 **갈라질 수 없게** 한 곳에서 만든다. 예:
   `_jssh() { journalctl -u ssh -u sshd --no-pager -o cat "$@" 2>/dev/null; }` 를 두고
   프로브와 창 조회가 **둘 다** 그것을 부른다. 그러면 M2 는 구성상 불가능해진다.
2. `monitor-selftest.sh` — 가짜가 **`-o cat` 을 실제로 존중**하게 고친다
   (`case "$*" in *"-o cat"*)` 로 메타줄을 억제). 고친 가짜에서 M2 를 다시 심어
   **붉어지는 것**까지 확인할 것. (내가 쓴 재현 하네스가 그 모양이다.)

---

### CR45-2 (H · 차단) — 새 clear 가드의 단언이 **공허**하다

`deploy/monitor-selftest.sh:1314` / `deploy/monitor.sh:898`

```
avoid "$TMPROOT/rj7.log" 'ALERT-CLEARED sshjournal' "(교차 j3) 못 믿는 수로 경보를 끄지 않는다"
```

rj7 시나리오는 **처음부터 끝까지 `sshjournal` 을 한 번도 raise 하지 않는다**(첫 실행부터
`JMETA` 가 메타줄을 주므로 늘 판정 보류다). `clear_alert` 는 `.active` 가 없으면
**첫 줄에서 return** 한다(`monitor-lib.sh:280`). 따라서 이 `avoid` 는 가드가 있든 없든,
심지어 `clear_alert` 를 무조건 부르게 만들어도 **항상 통과한다.**

**실측 두 방향**
* 자체검사: 가드 제거(M4) → **201/0/0 · rc=0** (관문이 전혀 못 본다)
* 런타임(`.active`/`.sent` 를 심고 프로브 나쁜 상태로 2회 실행):

```
== 원본   해소 안 나갔다 (정상) · .active 남아 있음
== M4     거짓 해소 나갔다 (ALERT-CLEARED sshjournal) · .active 지워짐 — 미해소 표시가 사라진다
```

즉 **가드는 옳고 하중도 받는데, 그것을 지키는 관문이 없다.** 이 라운드가 스스로 세운 규칙
(`CR44-2`: *"새 판정을 쓸 때 (가) 이 판정이 clear 를 부를 수 있는가, 부른다면 관문이 그것을
보는가를 먼저 정한다"*)을 **새 코드에서 다시 어겼다.**

**pass 조건** — rj7 시나리오를 `rj6` 처럼 만든다: `sshjournal` 을 먼저 켜 두고
(`.active`/`.sent` 선주입 또는 `JBIN` 으로 눈멂 상태를 한 번 만든 뒤 `JMETA` 로 전환)
그 상태에서 `avoid ALERT-CLEARED` + `.active` 생존을 함께 단언한다.

---

### CR45-3 (M) — 문서가 **안 재 본 숫자**를 다시 적었다 (`CR44-4` 와 같은 형태)

| 문서 | 적힌 것 | 실측 |
|---|---|---|
| `monitoring.md` 7b-⑥ | *"프로브를 무력화하는 변이를 심으면 **그 4건이 붉어진다(실측)**"* | **3건**(4번째가 CR45-2 의 공허한 단언이다) |
| `monitoring.md:728` | 검사 **197건** | **201건** |
| `deploy/DEPLOY.md:1223-1224,1272,1291` | 제자리 **197/0/0** · 사본 **193/0/1** | 제자리 **201/0/0** · 사본 **197/0/1** |
| `DEPLOY.md:1311` | *"5분마다 journalctl 을 **2회** 부른다"* | **3회**(`-n 1` · 프로브 · 창 조회) |

판정 기준을 *"숫자가 아니라 실패 0 · HARN 0 · rc=0"* 으로 바꾼 것은 **옳다**(그 문장은 유지).
그래도 **표에 적힌 실측치가 코드와 다르면** 배포자가 "왜 4개 더 많지" 에서 멈춘다.
특히 7b-⑥ 의 "4건" 은 **그 4번째가 공허하다는 사실을 가리는 문장**이라 그냥 오타가 아니다.

---

### CR45-4 (M) — `CR44-2` **"전수 훑기"** 주장이 사실이 아니다

`monitoring.md §8-6` 은 *"관문이 `ALERT-CLEARED` 를 행동으로 보는 키가 6개 → **12개**가 됐다 …
**남은 것은 `dbstruct`·`dbstruct_cfg` 뿐**이고 … 숨기지 않고 여기 적는다"* 라고 적는다.
`clear_alert` 호출을 전수로 세면 **남은 것이 8종 더 있다**:

`web`(:180) · `frontend`(:230) · `cgroup_*`(:273) · `anon_*`(:319) · `disk`(:336) ·
`pgcrash`(:1292) · `jsonlog`(:1314) · `job_*`(`job-run.sh:109`)
— 자체검사에 `ALERT-CLEARED` 단언이 **하나도 없다**.
(덧붙여 `logperm`·`logfresh` 는 **부정형 단언만** 있다 — "못 볼 때 끄지 않는다"는 보지만
"정상이면 꺼진다"는 안 본다. 12 라는 수는 그 둘을 긍정형으로 세고 있다.)

그리고 그중 둘은 **훑기가 찾으려던 바로 그 모양**이다:

* `check_pgcrash`(`monitor.sh:1286-1292`) — `docker logs` 가 **실패해도** `grep -c` 는 0 이라
  `n=0` → `clear_alert pgcrash "최근 24시간 DB 크래시 복구 흔적 없음"`.
  실측(서버): `docker logs --since 24h nosuchcontainer_xyz 2>&1 | grep -cE '…'` → **0**.
  컨테이너 이름이 바뀌거나 사라지면 **못 본 것을 "흔적 없음" 이라고 통보**한다.
* `check_jsonlog`(`monitor.sh:1301-1314`) — 컨테이너 json 로그를 **하나도 못 찾아도**
  `bad` 가 비어 `clear_alert jsonlog "정상"`. 같은 형태다.

둘 다 이번 델타가 만든 것은 아니다. 그러나 **이번 델타가 "전수로 훑었고 남은 것은 둘뿐"
이라고 적었다.** 그 문장이 다음 라운드의 탐색을 닫는다 — 이 저장소가 같은 형태를 네 번
놓친 이유가 정확히 그것이다. **주장을 사실로 좁히거나, 두 fail-open 을 닫을 것.**

---

### CR45-5 (M) — `CR44-10` 의 fail-open 가드도 **절반**이다 (`CR44-3` 과 같은 형태)

`check_peer_alive` 의 kv 3곳에는 `case "$last" in *[!0-9]*) last="" ;; esac` 가 붙었는데,
**같은 파일의 더 위험한 소비처**는 그대로다. 서버 격리 실행으로 두 방향을 쟀다:

* `kv/sshpw_off` 를 `zzz` 로 깨뜨리고 `Accepted password` 한 줄을 새로 넣었다 →
  요약: **`SSH : 비밀번호 로그인 성공 이번 구간 0건 (기대 0)`** · `ALERT sshpw` **없음** ·
  `blind_add` **없음**. `[ "$size" -gt "$off" ]` 가 오류(rc 2)로 거짓이 되어 `delta=0` 이 되고,
  `explained=1` 이라 `clear_alert authshrink` 까지 부른다.
  **T2 트립와이어가 "봤고 괜찮다"고 말하면서 눈이 먼다** — 이 파일이 다섯 번 막아 온 그 형태다.
* `kv/api5xx` 를 `abc` 로 깨뜨리면 `$((cur - prev))` 가 **`set -u` 아래 치명적 오류**라
  **`--fast` 실행 전체가 그 지점에서 끝난다**(그 실행의 요약 줄 자체가 안 남는다).
  뒤의 SSH·logblind·heartbeat 가 통째로 안 돈다. 드러나는 경로는 `fast_dead`(20분)뿐인데
  그것을 보는 `--daily` 는 하루 한 번이다.

**차단은 아니다.** 다만 `off` · `prev_amt` · `api5xx` 의 `prev` · `prev_r1_size` 에 같은 한 줄
가드를 붙이고, **깨진 값은 "없는 것"으로 보고 `blind_add`** 할 것. 지금은 "고쳤다" 고 적힌
클래스의 가장 나쁜 사례가 남아 있다.

---

### CR45-6 (M) — 게이트 전에 이미 서버에 올라가 있다 · 서버 문서는 옛판이다

* `/opt/realestate/scripts/monitor.sh` 의 mtime 은 **2026-08-03 17:57**, sha256 은 리뷰 대상과
  **일치**한다. `DEPLOY.md §9-1` 자신이 *"게이트(code-review / security-review)가 **둘 다
  통과한 뒤에만** 실행한다"* 라고 적는다. 이번 라운드는 그 순서를 지키지 않았다.
  (다행히 실려 있는 코드가 `199d9fe` 보다 **나쁘지는 않다** — CR45-1·2 는 잠재 구멍이지
  회귀가 아니다. 그래서 즉시 롤백은 요구하지 않는다. 다만 **절차를 지켰다고 적지 말 것.**)
* 서버의 `/opt/realestate/docs/05-monitoring/monitoring.md` 는 **2026-08-02 02:12 판**이고
  `7b-⑥` 행이 **없다**(해시 불일치 확인). 그런데 **제자리 자체검사는 그 문서를 읽는다**
  (`monitor-selftest.sh:1559` T7 · T8). `§9-1` 절차에 그 문서를 올리는 단계가 없어,
  앞으로도 서버의 "문서–코드 일치" 검사는 **옛 문서**를 본다.
  → §9-1 에 `docs/05-monitoring/monitoring.md` 도 함께 올리는 단계를 넣을 것.

---

### CR45-7 (L) — 프로브 실패의 **연쇄**와 창 선택

* 방향은 안전하다: `jd_probe_bad=1` 이면 경보도 해소도 안 하고 `blind_add` → `logblind` 가
  뜬다. 즉 **조용하지 않다**(PM 질문 ①b 에 대한 답: `logblind` 로 충분하다).
* 다만 그 상태가 지속되면 **`logblind` 는 영영 안 꺼진다.** 변이 M3(양쪽 `-o cat` 제거 →
  진짜 journalctl 이 늘 메타줄을 준다)에서 붉어진 3건이 전부 **인증서/`logblind` 해소** 쪽이었다.
  즉 프로브 오염 하나가 **다른 감시불능 사유들의 해소 표시까지 덮는다.** 설계상 맞고 요약이
  사유를 나열하므로 사람이 읽을 수는 있다 — 그대로 두어도 된다(알고 두는 것과 모르는 것은 다르다).
* 프로브 창이 `now+3600 ~ +3660` 이다. 시계가 1시간 이상 뒤로 점프하거나(NTP step)
  미래 타임스탬프 로그가 있으면 오염된다. **비용이 같으니 창을 `+7일` 쯤으로 멀리 둘 것**
  (0.019초 · 저널 크기와 무관).

### CR45-8 (L) — 오탐 0 의 근거 수치

내 재측정: 24시간 · 5분 버킷 **289개 전부 비어있지 않음 · 최소 12줄**(문서·주석은 "최소 21").
결론(`jtot=0` 은 정상 운영에 없다)은 그대로 유지되지만 **최소값이 문서와 다르다.**
`JD_MIN_SSHD`/`JD_MIN_WINDOW` 는 auth.log 쪽 문턱이라 영향 없음.

### CR45-9 (L) — 문구

`monitoring.md` 7b-④ 행: **"문턴(120초)"** → 문턱 · **"끔다"** → 끈다.

---

### 이번 라운드가 **정말로 고친 것**(내가 다시 확인함)

* `(x9)` — `touch -d '2 minutes ago'` 로 기준 mtime 을 못 박아 **결정적**이 됐고,
  못 만들면 `harn`(검사 실패 아님). 리눅스에서 3회 연속 통과.
* `(x9b)` — "자라는 창에서는 `authfake` 가 안 뜬다" 를 **검사로** 못 박았다(SR40-3).
  사정거리를 말이 아니라 관문으로 적은 것은 이 저장소에서 드문 미덕이다.
* `(교차)` — "사라짐" 을 **응답 실패**(`-n 1` 이 실패하는 가짜)로 모사해 진짜 journalctl 이
  있는 환경에서도 재현된다. M6 로 확인했듯 대조군(rj1·rj2·rj6)이 `--until` 오염까지 잡는다.
* `api5xx`·`authshrink`·`authfresh`·`daily_dead`/`fast_dead` 해소 경로 + **못 읽었을 때
  끄지 않는 대조군**(`S5Y`)까지 들어갔다.
* `HARN` 은 `rc=1` 을 만든다(`monitor-selftest.sh` 말미) — **하네스 승격이 결함을 숨기지 않는다.**
  M5 로 확인(197/0/0 · HARN 1 · rc=1).

---

### 리뷰 위생

* `grep -rnE 'MUT[-]' deploy/` **시작 0 · 종료 0**. 변이 8종은 **서버 격리 사본**
  `/root/rev-cr45/mut/*` 에만 심었고, 리뷰 종료 시 그 디렉터리를 통째로 **삭제**했다(확인).
* **`/opt/realestate/scripts/**` 는 읽기만 했다** — `cp` 로 빼내기 · `sha256sum` · `ls` 뿐,
  쓰기 0. 크론(`*/5`)은 그대로 옛 일정으로 돌았다.
* **텔레그램 발화 0통.** 모든 실행이 `RE_MON_DRY_RUN=1`(자체검사 하네스 기본값 ·
  내 재현 하네스도 명시 설정), URL 은 닫힌 포트 `127.0.0.1:9`, 상태·로그는 임시 경로.
  로그에 남은 것은 `DRY-RUN ::` 뿐이다.
* 서버에서 **`monitor-selftest.sh` 를 10회**(기준 1 + 변이 8 + 재확인 1) 돌렸다. 1회 66초.
  윈도우에서는 **돌리지 않았다**(50분 소요 · 이번 판정의 근거는 전부 리눅스 실측이다).
* 재현 하네스(현실적인 가짜 journalctl · 거짓 해소 · 깨진 kv)는 **내가 새로 짰다** —
  담당자 관문의 `sshrunj`/`age_window` 를 쓰지 않았다. 그래서 CR45-1 이 보였다.
* `frontend/**` · `docs/02-design/ux/**` 무접촉 · `git checkout --` 미사용 · 커밋 없음.

### pass 조건 (다음 라운드)

1. **CR45-1** — 형식 플래그를 한 곳에서 만들어 두 질의가 갈라지지 못하게 + 가짜가 `-o cat` 을
   존중하게. 고친 가짜에서 M2 를 심어 **붉어지는 것**을 실측으로 적을 것.
2. **CR45-2** — rj7 을 `sshjournal` 이 **켜져 있는 상태**에서 시작하게. 가드 제거 변이가
   **붉어지는 것**을 실측으로 적을 것.
3. CR45-3~6 은 차단 아님 — 문서 숫자 정정, "전수" 주장 축소(또는 `pgcrash`·`jsonlog` 닫기),
   kv 가드 마저 붙이기, `§9-1` 에 문서 배포 단계 추가.

## CR-046 · 2026-08-03 · `CR-045` 차단 2건 + `SR-041` High 2건 조치 재검증 (범위 `deploy/monitor.sh` · `deploy/monitor-lib.sh` · `deploy/monitor-selftest.sh` · `deploy/DEPLOY.md` · `docs/05-monitoring/monitoring.md` · 기준 `199d9fe`)

**판정: FAIL** — 차단 **3건**(H).

**`CR45-1` 과 `CR45-2` 는 둘 다 닫혔다** — 내가 심은 변이로 확인했다(M4·M5·M6). 그리고
`SR41-2` 가 지목한 두 결함(원격 위조 발화 · `keyboard-interactive/pam` 미탐)도 **코드에서는**
닫혔다(런타임 실측). 그런데 **그 마지막 수정이 리뷰 도중(21:13)에 들어왔고**, 그 결과
지금 작업트리는 **자기 자체검사에서 붉다(실패 2 · rc=1)** — 그리고 새로 들어온 코드
(앵커 재작성 · 메서드 분류 프로브 · `SR36-5` 하루 발송 상한)에 **관문이 하나도 안 붙었다.**

> 이 라운드의 한 줄: **고친 것은 맞는데, 고쳤다는 것을 증명하는 기계가 같이 안 왔다.**
> 그 기계가 없으면 다음 라운드에 같은 자리가 조용히 다시 열린다 — 이 저장소가
> 이미 다섯 번 겪은 형태이고, 이번에도 **픽스처가 약해서 초록이던 검사**를 하나 찾았다(M15).

### 0. 무엇을·언제 쟀는가 — **리뷰 중에 대상이 두 번 움직였다**

| 스냅샷 | `monitor.sh` sha256 | `monitor-selftest.sh` | 언제 |
|---|---|---|---|
| **A** (측정 시작 시점) | `9d401044…` | `9c067375…` | 20:45–21:11 · 변이 12종은 전부 여기서 |
| **B** (판정 대상 = 현재 작업트리) | `904ccb4f…` | `9c067375…` **(그대로)** | 21:13 수정분 · 재측정 21:15– |

* 스냅샷 B 에서는 `monitor-lib.sh` 도 새로 바뀌었다(`a10070ef…` · `SR36-5` 발송 상한 신규).
* **판정은 B 에 대해 내린다.** A 에서 잰 변이 결과는 *"관문이 무엇을 죽이는가"* 의 근거로
  그대로 유효하다(자체검사가 A→B 사이에 한 글자도 안 바뀌었다).
* 서버는 **읽기 전용**: `/opt/realestate/scripts/**` 세션 시작·종료 sha256 동일
  (`monitor.sh b0001419…`), 크론 5줄 그대로, 격리 사본 `/root/rev-cr46`·`/root/rev-cr46b`
  는 **종료 시 삭제 확인**. 텔레그램 **0통**(모든 실행 `RE_MON_DRY_RUN=1` · URL `127.0.0.1:9`).
* `bash -n deploy/*.sh` 8파일 실패 0 · `grep -rnE 'MUT[-]' deploy/` **시작 0 · 종료 0**.
* ✅ **이번 라운드는 게이트 전 배포를 하지 않았다**(CR45-6① 지켜짐) — `/opt` 해시가
  작업트리와 **다르다**. (다만 지금 서버에 도는 것은 `SR41-2` 취약판이다 — 별건.)

**직접 잰 기준값 (서버 · 리눅스)**

| 대상 | 결과 |
|---|---|
| 스냅샷 A · 문서 포함 | **통과 210 · 실패 0 · 건너뜀 0 · HARN 0 · rc=0** (44초) |
| 스냅샷 A · 문서 없는 사본 | **206 / 0 / 1 / HARN 0 · rc=0** → PM 주장(206·건너뜀 1) **재현** |
| **스냅샷 B (현재 작업트리)** | **통과 208 · 실패 2 · 건너뜀 0 · HARN 0 · rc=1** ⛔ |
| 실서버 실로그(`/var/log/auth.log` + 진짜 journald) 300초 창 2회 | 경보 오탐 **0** · `SSH2차 … 교차 대상 127줄` · `--fast` **0.225초** · 앵커 프로브 grep 2회 **3ms** |

### 0b. 심은 변이 (12종 · 전부 서버 격리 사본 · 스냅샷 A)

| 변이 | 무엇을 바꿨나 | 자체검사 | 판정 |
|---|---|---|---|
| **M1** | `jbuf=$(_jssh … **-o short**)` — 형식 플래그를 **뒤에 덧붙임** | **210/0/0 · rc=0** | **생존** → CR46-5 |
| M2 | `SSHPW_CORE` 의 `password` 갈래 무력화 | 200/**10**/0 · rc=1 | 잡힘 |
| M3 | 앵커 적합성 프로브 무력화 | 208/**2**/0 · rc=1 | 잡힘 |
| M4 | clear 가드에서 `jd_probe_bad = 0` 제거 | 208/**2**/0 · rc=1 | 잡힘 — **CR45-2 해소**(PM 주장 "정확히 2건" 일치) |
| M5 | `_jssh` 에서 `-o cat` 제거 | 201/**8**/0 · HARN 1 · rc=1 | 잡힘 — **CR45-1 해소** |
| M6 | 저널 픽스처를 auth.log 형식(`$HIT`)으로 되돌림 | 208/**2**/0 · rc=1 | 잡힘 — `HIT_JD` 분리가 하중을 받는다 |
| M7 | journald 계수에 auth.log 앵커 사용 | 208/**2**/0 · rc=1 | 잡힘 |
| M8 | `JD_MIN_SSHD` 문턱 무력화 | 205/**4**/0 · HARN 1 · rc=1 | 잡힘 |
| **M9** | **journald 앵커 `^` 제거** | **210/0/0 · rc=0** | **생존** → CR46-4 |
| M11 | 프로브 무력화(`jd_probe_bad` 늘 0) | 206/**4**/0 · rc=1 | 잡힘 — 문서 `7b-⑥` 의 "4건" 이 **이제 사실**이다 |
| M14 | auth.log 앵커의 syslog 접두부 제거 | 209/**1**/0 · rc=1 | 잡힘 |
| **M15** | **코드 무변경 · 위조 픽스처만 실측 문자열로** | **209/1/0 · rc=1** | **지금 코드가 붉다** → CR46-3 |

---

### CR46-1 (H · 차단) — 현재 작업트리가 **자기 관문에서 붉다** (`실패 2 · rc=1`)

서버 `/root/rev-cr46b` 격리 사본, 스냅샷 B 그대로:

```
통과 208 · 실패 2 · 건너뜀 0 · 하네스오류 0      rc=1
  FAIL (T2 앵커) 앵커가 한 줄도 못 맞추는데 '0건'이라고만 적는다 — 미탐이 정상으로 보인다
  FAIL (T2 앵커) 못 세는 상태가 감시불능에 안 실린다
```

원인은 21:13 수정이 프로브의 **판정 기준**을 바꿨는데(`Accepted publickey` 부분일치 →
`sshd\[pid\]: ` 존재 여부) 그 픽스처(`monitor-selftest.sh` 의 `fmt.auth.log` — 접두부가
아예 없는 줄)는 그대로 두었기 때문이다. 런타임으로도 재현했다: 그 형식의 auth.log 에서
새 프로브는 **한 마디도 안 하고**(`logblind` 0) 요약은 `기준값 설정 … 0건 · 기대 0` 이다.

`DEPLOY.md §9-1` 자신이 판정 기준을 **"실패 0 · 하네스오류 0 · rc=0"** 으로 못 박았다.
지금 상태로는 배포 절차 ②에서 멈춘다.

**pass 조건** — 픽스처와 판정을 맞춘다. 단, **픽스처를 판정에 맞춰 낮추지 말 것**:
그 접두부 없는 형식은 원래 *"우리 앵커가 이 호스트와 안 맞는다"* 를 보라고 만든 것이고,
아래 CR46-2 가 그 사정거리가 **좁아졌다**고 말한다. 프로브를 고치면 이 2건은 저절로 초록이다.

---

### CR46-2 (H · 차단) — 새 적합성 프로브가 **옛 프로브가 잡던 것을 못 잡는다** (조용한 축소)

`deploy/monitor.sh:703-707`

```
_anchor_sshd=$(grep -acE "sshd\[[0-9]+\]: " "$AUTH_LOG")
_anchor_head=$(grep -acE "${SYSLOG_HEAD}sshd\[[0-9]+\]: " "$AUTH_LOG")
if [ "$_anchor_sshd" -gt 0 ] && [ "$_anchor_head" -eq 0 ]; then …
```

두 수 **모두** `sshd\[pid\]: ` 를 요구한다. 그래서 **프로그램 이름이 바뀌는 형태**
(OpenSSH 9.8+ 는 연결 처리를 `sshd-session[…]` 이 찍는다 — `SR42-4` 가 예고한 자리)에서는
`_anchor_sshd` 도 0 이 되어 **조건 자체가 성립하지 않는다.** 옛 프로브는 그것을 잡았다.

**실측(서버 · 격리 · DRY-RUN · 같은 픽스처)**

| 파일 | 옛 loose / tight | 새 `_anchor_sshd` / `_anchor_head` | 결과 |
|---|---|---|---|
| `sshd-session[…]` 형식 auth.log(공개키 성공줄 포함) | **1 / 0 → 경보** | **0 / 0 → 침묵** | 새 쪽이 진다 |

그리고 그 상태에서 **진짜 비밀번호 로그인**(`sshd-session[903]: Accepted password for root …`)을
넣고 돌렸더니: `ALERT sshpw` **없음** · `ALERT logblind` **0** ·
요약은 **`SSH : 비밀번호 로그인 성공 이번 구간 0건 (기대 0)`**.
**못 본 것을 "괜찮다"로 말한다** — 이 파일이 `CR40-2` 이후 다섯 번 막아 온 바로 그 문장이다.

**pass 조건** — 느슨한 쪽 수(`_anchor_sshd`)는 **프로그램 이름을 고정하지 않는다.**
예: `sshd(-session)?\[[0-9]+\]: ` 로 세거나, `Accepted ` 성공줄 총수를 느슨한 쪽으로 쓴다
(원격 오염이 걱정이면 `SR42-3` 대로 **줄머리 앵커 + 프로그램명 와일드카드**를 쓰면 둘 다 산다).
그리고 `SSHD_RE`·`SSHPW_RE` 도 같은 확장을 받아야 한다 — 지금은 9.8+ 호스트에서
`delta`·`new_sshd` 가 **영구 0** 이라 교차 눈멂 판정(`jd_blind`)도 구조적으로 불가능하다.

---

### CR46-3 (H · 차단) — 새 코드에 **관문이 안 붙었다** · 초록이던 검사 하나는 **픽스처가 약해서** 초록이었다

`monitor-selftest.sh` 는 20:39 판(`9c067375…`) 그대로인데 그 뒤로 들어온 것이:
① 앵커 재작성(`SYSLOG_HEAD` · `SSHPW_METHOD`) ② 메서드 분류 프로브(`_m_unknown`)
③ **`monitor-lib.sh` 의 하루 발송 상한(`_send_quota`)** — ③은 **모든 알림 경로 앞에** 들어갔다.
셋 다 **검사 0건**이다.

특히 세 자리를 실측으로 못 박는다.

1. **`keyboard-interactive` 갈래에 픽스처가 없다.** 스냅샷 A 에서 `password` 갈래를 죽이면
   10건이 붉은데(M2), `keyboard-interactive` 갈래는 **어떤 검사도 안 본다** —
   그래서 `SR42-2`(PAM 미탐)가 관문을 그대로 통과했다. 지금 코드는 고쳐졌지만
   **고쳐진 것을 지키는 기계가 없다.** (런타임 확인: 스냅샷 B 는 `Accepted keyboard-interactive/pam`
   에 `ALERT sshpw` 를 띄운다 ✅ — 검사만 없다.)
2. **위조 픽스처가 실측 문자열보다 약하다.** `monitor-selftest.sh:1382` 의 `FORGE_PROTO` 는
   가짜 접두부가 없어서, 앵커가 부분일치로 뚫리던 시절에도 **초록**이었다.
   **코드는 한 글자도 안 고치고 그 픽스처만 실측 문자열**
   (`… client sent invalid protocol identifier "sshd[9]: Accepted password for q"`)로 바꾸니
   스냅샷 A 가 **209/1/0 · rc=1**, 붉은 것은 정확히 `(T2 위조) 원격에서 트립와이어를 켤 수 있다` 다(M15).
   런타임으로도 확인했다 — 그 줄 **하나**를 auth.log 에 넣으면 스냅샷 A 는 `ALERT sshpw` 를
   띄우고(쿨다운 0 · `*/5` = 하루 288통), 스냅샷 B 는 안 띄운다.
   즉 **그 검사가 초록이던 이유는 코드가 옳아서가 아니라 픽스처가 약해서였다.**
3. **`_send_quota` 는 `DRY_RUN` 보다 먼저** 도는데(주석이 *"그래야 자체검사가 이 경로를
   실제로 밟는다"* 라고 적는다) 정작 **밟는지 확인하는 검사가 없다.** 상한(60)·일자 롤오버·
   "억제 시작 한 통" 셋 다 무관측이다. 한 상태 디렉터리에서 60통을 넘기는 시나리오가 생기면
   **다른 검사들이 조용히 억제된 알림을 못 보게 된다** — 관문이 스스로 눈머는 길이다.

**pass 조건(셋 다)**
* kbdint 픽스처 검사 1건(그 줄에 `ALERT sshpw` 가 뜨는가) + **메서드 하나를 정규식에서 빼는
  변이가 붉어지는 것**을 실측으로 적을 것.
* `FORGE_PROTO` 를 실측 문자열로 교체(M15 를 그대로 관문에 넣으면 된다).
* `_send_quota` 검사 3건(상한 도달 시 억제 · 억제 통보 1통 · 다음 날 리셋).

---

### CR46-4 (M) — journald 앵커(`^`)를 지키는 관문이 **없다**

`SSHPW_JD_RE` 에서 `^` 를 지우는 변이(M9)가 **210/0/0 · rc=0** 으로 생존한다.
원격 위조 문자열을 실제로 막고 있는 것이 이 `^` 인데(스냅샷 A 실측: 같은 문자열에
auth.log 앵커 매칭 1 · journald 앵커 매칭 0), **위조 검사(rf1·rf2)는 auth.log 에만
위조 줄을 넣는다.** `CR44-2` 가 세우고 `CR45-2` 가 차단한 형태 — *가드는 옳은데 관문이 없다* — 의 재발.
조치: 저널 픽스처에 위조 줄을 넣은 시나리오 1건(그 상태에서 `avoid ALERT sshpw`).

### CR46-5 (M) — `_jssh` 는 **가장 흔한 모양**만 막는다 · journald 쪽엔 적합성 프로브가 없다

`-o` 를 **뒤에 덧붙이는** 변이(M1)가 생존한다(210/0/0). 진짜 journalctl(systemd 249) 실측:

| 질의 | 빈 창 | 5분 창 내용 | `^Accepted publickey for ` 매칭 |
|---|---|---|---|
| `-o cat` | 0바이트 | 접두부 없음 | **42** |
| `-o cat … -o short` | **0바이트**(`-o cat` 이 `arg_quiet` 를 켜고 안 꺼진다) | 접두부 붙음 | **0** |

즉 **눈멂 탐지(`jtot`)는 안 죽지만 `jd`(두 번째 출처의 성공 계수)가 조용히 영구 0** 이 되고,
요약은 `교차 대상 863줄` 이라 건강해 보인다. 구조 검사 2건은 `jbuf=$(_jssh` 가 있는지만 본다.
값싼 조치 둘: ① 구조 검사에 **`_jssh .*-o ` 0건** 단언을 더한다 ② **journald 쪽에도 적합성
프로브**를 둔다(창 안 `Accepted publickey` 가 있는데 `^` 앵커로 0 이면 `blind_add`).
②는 CR46-2·CR46-3-①의 미탐까지 한 번에 드러낸다.

### CR46-6 (M) — `CR45-5`(kv fail-open)가 **2라운드 연속 미조치** · 내가 다시 재현했다

숫자 가드는 `check_peer_alive` 3곳에만 있고 `sshpw_off`(:631) · `sshpw_r1_size` ·
`sshpw_mtime` · `api5xx`(:481) 은 그대로다. 서버 격리 실행 두 방향:

* `kv/sshpw_off` = `zzz` → **rc=0 인데** 요약이 `SSH : 비밀번호 로그인 성공 이번 구간 0건 (기대 0)`.
  같은 실행에 진짜 `Accepted password` 를 넣었는데 `ALERT sshpw` 0 · `logblind` 0 —
  **T2 가 "봤고 괜찮다"고 말하면서 눈이 먼다.**
* `kv/api5xx` = `abc` → `--fast` 가 **그 지점에서 죽는다**(rc=1 · 그 실행의 `fast 완료` 줄 자체가 없다).
  뒤의 SSH·교차·heartbeat 가 통째로 안 돈다.

CR46-2 와 **같은 집안**(T2 가 조용히 0건을 말한다)이다. 이번에 같이 닫을 것.

### CR46-7 (L) — `CR45-3` 문서 숫자, 절반만 맞다

* 좋아진 것: `monitoring.md 7b-⑥` 의 *"그 4건이 붉어진다"* 는 **이제 사실**이다(M11 = 4건).
* 그대로인 것: `monitoring.md:731` **197건** → 실측 **210**(문서 포함) / **206 + SKIP 1**(사본).
  `DEPLOY.md:1223-1224` 표 **197 / 193** → **210 / 206**.
  `DEPLOY.md:1311` *"journalctl 을 2회 부른다"* → **3회**(`-n 1` · 프로브 · 창 조회).

### CR46-8 (L) — `CR45-4` "전수 훑기" 주장과 fail-open 둘, 그대로

`monitoring.md:663` 은 여전히 *"남은 것은 `dbstruct`·`dbstruct_cfg` 뿐"* 인데
`check_pgcrash`(:1367) · `check_jsonlog`(:1389) 의 `clear_alert` 는 **못 봤을 때도 불린다**.
주장을 사실로 좁히거나 둘을 닫을 것.

### CR46-9 (L) — `CR45-6②` · `CR45-7` · `CR45-9` 미반영

* `DEPLOY.md §9-1` 에 **문서 배포 단계가 여전히 없다.** 서버 문서는 `405d6fd9…`(08-02 02:12),
  작업트리는 `f60a4322…` — 제자리 자체검사(T7)가 **옛 문서**와 코드를 맞춘다.
* 프로브 창은 `now+3600` 그대로(`SR41-5`/`CR45-7` 은 `+86400` 권고).
* `monitoring.md:240` 의 **"문턴"** · **"끔다"** 오타 그대로.

### CR46-10 (L) — `rj7` 사전조건 `HARN` 이 **뒤따르는 단언을 막지 않는다**

`monitor-selftest.sh:1325-1329` 의 `harn`/`ok` 는 if/else 로 끝나고 아래 5건이 조건 없이 계속 돈다.
실측(M5·M8): `HARN (교차 j3) 사전 조건` 과 `FAIL (교차 j3) .active 가 사라졌다` 가 **함께** 나온다 —
하네스가 시나리오를 못 만든 것을 **검사 실패로 보고**하는 형태(`CR44-3` 이 금지한 것)이고,
같은 상황에서 `avoid ALERT-CLEARED` 는 **초록**(공허)이다. `rc=1` 이라 숨지는 않으니 L.

---

### 이번 라운드가 **정말로 고친 것** (내가 다시 확인함)

* **`CR45-1` 해소** — 형식 플래그가 `_jssh` 한 곳. `-o cat` 을 빼면 **프로브가 먼저 운다**
  (M5: 8실패 + HARN 1 · rc=1). 가짜 journalctl 도 `-o cat` 을 실제로 존중한다.
* **`CR45-2` 해소** — `rj7` 이 `JBIN` 으로 경보를 **먼저 켜고** 시작한다. 가드 제거(M4)가
  **정확히 2건**(`켜져 있던 경보가 꺼진다` · `.active 가 사라졌다`)을 죽인다 — PM 주장 그대로.
  사전조건이 깨지면 `HARN` 이고 `HARN` 은 `rc=1` 이다(M5·M8 로 확인) — **하네스 승격이 결함을 숨기지 않는다.**
* **`HIT_JD` 분리가 하중을 받는다** — 저널 픽스처를 auth.log 형식으로 되돌리면 2건이 붉다(M6).
  다른 검사가 그것 때문에 약해진 흔적은 못 찾았다(M7 도 2건을 죽인다).
* **새 검사 5건은 서로를 가리지 않는다** — `rf1↔rf2`(위조는 막고 진짜는 잡는다)와
  `rf3↔rf4`(못 셀 때 말하고 정상이면 조용하다)가 **반대 방향 짝**이고, M2·M3·M14 가 각각
  다른 것을 죽인다. 실서버 auth.log 에서 옛 프로브 loose = tight = 277 → **오탐 0**.
* **`SR41-2` 의 두 결함은 코드에서 닫혔다**(스냅샷 B 런타임 실측):
  `Accepted keyboard-interactive/pam` → `ALERT sshpw` **뜬다** ·
  실측 위조 문자열 → **안 뜬다**. (관문이 없다는 것이 CR46-3 이다.)

### 리뷰 위생

* 변이 12종은 **서버 격리 사본**(`/root/rev-cr46/m-*` · `/root/rev-cr46b`)에만 심었고
  두 디렉터리 모두 **종료 시 삭제 확인**. 저장소 소스 **수정 0** · `git checkout --` 미사용 · 커밋 없음.
* **`/opt/realestate/scripts/**` 는 읽기만 했다** — `sha256sum`·`ls` 뿐. 세션 시작·종료 해시 동일.
* **텔레그램 0통.** 모든 실행 `RE_MON_DRY_RUN=1`(자체검사 `run_mon` 강제 + 내 하네스도 명시),
  URL 은 닫힌 포트 `127.0.0.1:9`, 상태·로그는 `/root/rev-cr46*` 임시 경로. 로그에 남은 것은 `DRY-RUN ::` 뿐.
* 서버에서 자체검사를 **16회** 돌렸다(기준 2 + 변이 13 + 스냅샷 B 1). 1회 44~48초.
  **윈도우에서는 돌리지 않았다** — 이번 판정의 근거는 전부 리눅스 실측이다.
* `frontend/**` · `docs/02-design/**` 무접촉.
* ⚠️ **작업트리가 리뷰 중에 두 번 움직였다**(21:13 `monitor.sh`·`monitor-lib.sh`).
  게이트는 움직이는 트리를 판정할 수 없다 — 다음 라운드에는 **리뷰 시작 시점 해시를 고정**하고,
  고칠 것이 생기면 라운드를 끝낸 뒤에 고치기를 권한다(그래야 "무엇을 통과시켰는지"가 남는다).

### pass 조건 (다음 라운드)

1. **CR46-1** — 자체검사 `실패 0 · HARN 0 · rc=0`(서버 실측으로). 지금은 2건 붉다.
2. **CR46-2** — 느슨한 쪽 수에서 프로그램 이름 고정을 푼다(`sshd(-session)?\[[0-9]+\]:`).
   `SSHD_RE`·`SSHPW_RE` 도 같이. **9.8+ 형식 픽스처에서 붉어지던 것이 초록이 되는 것**을 실측으로 적을 것.
3. **CR46-3** — kbdint 픽스처 · 실측 위조 문자열 픽스처 · `_send_quota` 검사 3건.
   각각 **그 검사를 죽이는 변이가 붉어지는 것**까지 적을 것.
4. CR46-4·5(관문 2건 · 구조 단언 1줄)는 차단 아니지만 **같이 닫는 것이 싸다**.
5. CR46-6~10 은 kv 가드 · 문서 숫자 · "전수" 주장 · 문서 배포 단계 · 오타.

---

## CR-047 · 2026-08-03 · `CR-046` 차단 3건 조치 재검증 (범위 `deploy/monitor.sh` · `deploy/monitor-lib.sh` · `deploy/monitor-selftest.sh` · `deploy/DEPLOY.md` · `docs/05-monitoring/monitoring.md` · 트리 동결)

**판정: fail** — 차단 2건(H) · M 4 · L 4.
CR46-1·CR46-2·CR46-3 은 **셋 다 실측으로 해소를 확인했다**. 그런데 같은 라운드가 함께
넣은 **하루 발송 상한(SR42-1 대응)** 이 새 결함을 하나 만들었고, 그것을 지킨다는 검사 3건이
**거의 전부 공허**하다. 즉 이번 라운드는 **T2 는 고쳤고 통보 채널을 깨뜨렸다.**

### 검증 조건 (판정 근거는 전부 리눅스 실측)

* 트리 동결 해시 **5/5 일치** 확인 후 시작. 리뷰 중 트리 변경 없음.
* 서버 격리 사본 `/root/rev-cr47/` (종료 시 삭제 확인). `/opt/realestate/scripts/**` **무접촉**.
* 자체검사 **21회** 실행(기준 1 + 변이 16 + 행동 실험 4). 1회 **50초**.
  기준선 = **통과 217 · 실패 0 · 건너뜀 1 · HARN 0 · rc=0** — PM 보고와 일치.
* 텔레그램 **0통**. 모든 실행 `RE_MON_DRY_RUN=1`, 예외인 발송 실험 2건은
  `RE_MON_CRED_FILES=/root/rev-cr47/does-not-exist.env` 로 **자격증명 자체를 없애** curl 미도달.

### 변이 시험 16종 — **6 죽음 / 10 생존**

| # | 변이 | 결과 |
|---|---|---|
| M1 | `SSHPW_RE` 의 `sshd(-session)?`→`sshd` | **216/1 rc=1 죽음** `(T2 9.8+)` |
| M2 | `SSHD_RE` 동일 변이 | 217/0 rc=0 **생존** |
| M3 | `_anchor_head` 동일 변이 | 217/0 rc=0 **생존** |
| M4 | `_m_unknown` 동일 변이 | 217/0 rc=0 **생존** |
| M5 | `_anchor_sshd` 동일 변이 | 217/0 rc=0 **생존** |
| M6 | `_send_quota` 의 **상한 통보(`return 2`) 제거** | 217/0 rc=0 **생존** |
| M7 | `send_count` 손상 시 `count=0`→`count=$SEND_MAX_DAY`(fail-closed) | 217/0 rc=0 **생존** |
| M8 | `send_day` 비교 `!=`→`=` | 215/2 rc=1 죽음 |
| M10 | `raise_alert sshpw 900`→`604800`(일주일) | 217/0 rc=0 **생존** |
| M11 | `sshpw_off` 손상 분기 침묵 | 215/2 rc=1 죽음 |
| M13 | `kv_set send_count "$((count+1))"` 제거(=상한이 영영 안 걸린다) | 217/0 rc=0 **생존** |
| M14 | 날짜 롤오버 블록 삭제(=상한이 영구화) | 217/0 rc=0 **생존** |
| M15 | `SEND_MAX_DAY` 기본값 `60`→`0`(**모든 경보 영구 침묵**) | 217/0 rc=0 **생존** |
| M16 | 앵커 `blind_add` 블록 삭제 | 215/2 rc=1 죽음 |
| M17 | `_m_unknown` 보고 블록 삭제 | 216/1 rc=1 죽음 |
| M18 | `SSHPW_METHOD` 에서 `keyboard-interactive` 제거 | 216/1 rc=1 죽음 |
| M19 | `SSHPW_JD_RE` 의 `^` 제거 (CR46-4) | 217/0 rc=0 **생존**(미반영 확인) |

---

## 차단 (H)

### CR47-1 (H · 차단) — **하루 발송 상한이 "전송 실패"를 상한으로 센다 → 채널이 잠깐 죽으면 자정까지 전면 침묵**

`monitor-lib.sh:225-238`(`_send_quota`) / `:240-286`(`send_telegram`).
결함이 둘이고 **서로를 증폭한다.**

1. **상한은 "보낸 통수"가 아니라 "시도 횟수"를 센다.** `_send_quota` 는 `send_telegram`
   맨 앞에서 카운터를 올린 뒤(`:236`), 그 아래에서 `alert_creds` 실패(`:261`)나 curl 3연속
   실패(`:283`)로 **한 통도 안 나가고 return 1** 한다. 그리고 `raise_alert` 는 원칙상
   **성공할 때까지 `.sent` 를 안 찍으므로**(머리말 원칙 3) 같은 경보가 5분마다 재시도된다
   → 채널 장애가 곧 상한 소진이다.
2. **`send_capped=1` 을 통보를 보내기 *전에* 찍는다**(`:233`). 그래서 상한에 닿는 그 한 통도
   같은 장애로 실패하면 **영영 다시 시도되지 않는다.** 설계가 스스로 못 박은
   *"상한에 닿을 때 **한 통은 나간다** — 그 한 통이 없으면 사람이 침묵과 억제를 구분할 수 없다"*
   (`:220-222`)가, **하필 상한에 닿는 가장 흔한 경로에서** 깨진다.

**재현(서버 격리 · 자격증명 없음 = 채널 사망 · `RE_MON_SEND_MAX_DAY=3`)**

```
시도1 rc=1  send_count=1 send_capped=0
시도2 rc=1  send_count=2 send_capped=0
시도3 rc=1  send_count=3 send_capped=0
시도4 rc=1  send_count=3 send_capped=1     ← 상한 통보를 시도했으나 같은 이유로 실패
시도5 rc=1  send_count=3 send_capped=1
감시로그: ALERT-CHANNEL-MISSING 4 · ALERT-SUPPRESSED 하루 상한 1
'경보 발송이 하루 상한' 이 실제로 나간 통수: 0        ← 로그에만 있다

[채널 복구 후]  DRY-RUN 발송 0통 · capped=1          ← 진짜 경보가 한 통도 안 나간다
```

즉 **발송 0통으로 상한을 다 쓰고, 복구된 뒤에는 그날이 끝날 때까지 전면 침묵**한다.
일일 요약까지 억제되므로 드러나는 유일한 경로가 *"아침 요약이 안 왔다"* 는 **사람의 기억**이다 —
이 파일이 CR40-2 이후 다섯 라운드 동안 거부해 온 바로 그 형태이고,
`SR42-1` 이 막으려던 것(채널이 죽어 진짜 경보가 묻힌다)을 **감시가 스스로 만든다.**

발생 조건은 가정이 아니다: 자격증명은 **동거 서비스 `pjt12-adsense/.env` 를 읽기만** 하는
구조라(`monitor-lib.sh:13-16`) 그쪽 로테이션·키 이름 변경이 곧 `alert_creds` 실패다.
텔레그램 429/5xx·DNS 실패도 같은 경로다. 경보가 하나만 켜져 있어도 12통/시간이 소진되어
기본 상한 60은 **5시간**, 두 개면 2.5시간이면 닿는다.

**pass 조건**
* 카운터는 **실제로 나간 통수**만 센다(DRY-RUN 은 나간 것으로 본다). 실패·억제는 안 센다.
  — 상한 *검사*를 DRY-RUN 앞에 두는 지금 순서는 그대로 두어도 된다(검사와 계상을 분리).
* `send_capped=1` 은 **상한 통보가 실제로 전달된 뒤**에만 찍는다. 실패하면 다음 실행이 다시 시도한다.
* 위 두 성질을 각각 죽이는 변이가 관문에서 붉어지는 것까지 적을 것(CR47-2 와 같이 닫힌다).

### CR47-2 (H · 차단) — **발송 상한 검사 3건이 공허하다** · `CR-046` pass 조건 #3 미달

`CR-046` 은 *"`_send_quota` 검사 3건. **각각 그 검사를 죽이는 변이가 붉어지는 것까지 적을 것**"*
을 pass 조건으로 걸었다. 검사는 들어왔지만(`monitor-selftest.sh:1459-1495`)
**상한 기능을 통째로 무력화하는 변이 5종이 전부 217/0/1 · rc=0 으로 생존한다.**

* **M6** — 상한 통보 분기(`return 2`)를 없애도 `PASS (발송 상한) 상한에 닿으면 **닿았다고 한 통 보낸다**`
  가 **그대로 초록**이다. 원인: `want "$TMPROOT/rcap.log" '하루 상한'` 이 찾는 문자열이
  억제 로그(`ALERT-SUPPRESSED 하루 상한 5통`)에도 들어 있어 **두 상태를 구분하지 못한다.**
  검사 이름이 단언하는 성질(= CR47-1 이 깨뜨린 바로 그 성질)을 이 검사는 재지 않는다.
* **M13** — `send_count` 증가를 지워 **상한이 실제 운영에서 영영 안 걸리게** 해도 초록.
  원인: `capseed` 가 `send_count=5` 를 **심어 놓고** 시작하므로 누적 경로가 한 번도 안 돈다.
* **M14** — 날짜 롤오버를 지워 **상한이 영구화**돼도 초록(같은 이유).
* **M15** — `SEND_MAX_DAY` 기본값을 `0` 으로 바꿔 **모든 경보를 영구 침묵**시켜도 초록.
  대조군 `rcap3` 이 `RE_MON_SEND_MAX_DAY=500` 을 **명시로 덮어써서** 기본값을 아무도 안 본다.
* **M7** — `send_count` 손상 시 fail-open(`count=0`)을 fail-closed(`count=$SEND_MAX_DAY`)로
  뒤집어도 초록. 리뷰가 지목한 *"fail-open 이어야 하는데 fail-closed 로 만든 자리"* 를
  관문이 못 본다는 뜻이다.

덧붙여 **대조군 `(다)` 는 문법상 절대 발동하지 않는다**(→ CR47-7).
그러므로 이 3건이 실제로 잡는 것은 `send_day` 비교(M8) 하나뿐이다.

**pass 조건**
* 상한 검사에서 **상태 심기를 빼거나**, 심는 검사와 **누적으로 도달하는 검사를 둘 다** 둘 것
  (`SEND_MAX_DAY=2` 로 실행 한 번에 3통 이상 나는 시나리오면 충분하다).
* `(가)` 는 **상한 통보 본문**(`경보 발송이 하루 상한`)만 매치하도록 좁힐 것 —
  지금은 억제 로그와 같은 문자열이다.
* 기본값(`:-60`)이 하중을 받는 검사 1건(대조군에서 `RE_MON_SEND_MAX_DAY` 를 안 주는 실행).
* M6·M7·M13·M14·M15 가 각각 붉어지는 것을 실측으로 적을 것.

---

## 비차단 (M)

### CR47-3 (M) — `sshpw` 쿨다운 `0`→`900` 이 **문서와 어긋나고, 관문이 없다**

* `docs/05-monitoring/monitoring.md:248` 은 여전히
  *"**사건형**(OOM kill · 배치 실패 · **SSH 비밀번호 로그인 성공**) → 쿨다운 **0**. 새 사건은 새 정보다."*
  라고 적는다. 코드는 `monitor.sh:747`·`:1028` 둘 다 `900` 이다. 이 저장소는 문서와 코드가
  같은 말이어야 한다는 규칙을 T7 로 강제하는데, 알림 정책표에는 그 관문이 없다.
* **M10**(`900`→`604800`)이 생존한다 — T2 의 재통보 주기는 **아무 검사도 지키지 않는다.**
  이번 라운드가 바꾼 것이 정확히 그 값인데도.
* 코드 동작 자체는 확인했다: `.sent` 가 없는 첫 통은 **즉시** 나가고(`raise_alert:298`),
  이후 15분에 1통 · `delta>0` 일 때만. **즉시성은 유지된다** — 성격이 바뀐 것은
  "같은 15분 안의 2번째 이후 사건은 로그에만 남는다" 뿐이라 트립와이어로서 수용 가능하다.
  다만 그 판단이 문서·검사 어디에도 없다.

### CR47-4 (M) — `CR46-6` 이 **`sshpw_off` 하나만** 닫혔다 · 나머지 kv 는 `set -u` 산술로 실행을 죽인다

`CR46-6` 은 `sshpw_off` · `sshpw_r1_size` · `sshpw_mtime` · `api5xx` 네 곳을 지목했다.
이번에 닫힌 것은 `sshpw_off` 뿐이다(M11 로 관문도 확인). 나머지는 그대로다 — **실측**:

```
kv/api5xx = 'abc' → --fast  rc=1 · 출력에 'SSH' 줄 0개 · last_fast_run 미갱신 · 'fast 완료' 미기록
```

`check_api5xx:494` 의 `delta=$((cur - prev))` 가 `set -u`(`:24`) 아래에서 **셸을 통째로 죽인다.**
그 뒤의 `check_sshlogin`(T2) · `check_logblind` · `check_peer_alive` 가 통째로 안 돈다.
크론은 `>>/dev/null 2>&1` 이라 **rc=1 이 아무 데도 안 남는다.**
같은 형태가 `check_oom:289`(`oomkill_$name`) · `check_web:170`(`web_fail_streak`) ·
`check_frontend:222`(`fe_fail_streak`) 에도 있다. `api5xx` 는 `kv_set` 이 산술 **앞**이라
한 회차만 잃고 자가복구되지만, **`oomkill_*` 은 `kv_set` 이 뒤라 매 실행 같은 자리에서 죽는다** —
그러면 3번 이후 검사가 **영구히** 안 돌고 `--daily` 도 요약 전에 죽는다.
`check_peer_alive:1099/1119/1135` 가 쓰는 `case "$last" in *[!0-9]*) last="" ;; esac` 관용구를
그대로 옮기면 끝난다(3라운드 연속 이월).

### CR47-5 (M) — 발송 상한이 **문서에 한 줄도 없다** · 오히려 "아직 안 고친 것"에 남아 있다

* `monitoring.md §3 알림 정책`(`:245-251`)에 상한 항목이 없다. **모든 경보를 멈출 수 있는
  유일한 스위치**(`RE_MON_SEND_MAX_DAY`)가 운영 문서 어디에도 없다 —
  당직자가 침묵을 만났을 때 볼 곳이 없다.
* `monitoring.md:437` 은 `### 8-4. 아직 안 고친 것` 에 **`SR36-5`(발송 상한)** 을 그대로 열어 둔다.
  구현된 기능이 문서에서는 미구현이다.
* `DEPLOY.md` 에도 상한·`sshd-session`(9.8+) 언급이 없다.

### CR47-6 (M) — `CR40-8` 미조치가 상한과 곱해진다 — 억제 구간에 켜졌다 풀린 경보는 **흔적이 사라진다**

`clear_alert`(`monitor-lib.sh:312-319`)는 `send_telegram` 의 결과와 무관하게
`rm -f "$af" "$sf"` 를 **무조건** 한다. 상한에 걸린 구간에서 어떤 경보가 켜졌다 풀리면
① 경보 통보 0통 ② 해소 통보 0통 ③ `.active` 삭제 → **일일 요약 머리말이 `이상 없음`**.
`monitoring.md:436` 이 `CR40-8` 을 스스로 열어 둔 항목인데, 상한이 들어오면서
**발동 조건이 훨씬 흔해졌다.** 최소 조치: 발송이 실패·억제됐으면 `.active` 는 남긴다.

---

## 비차단 (L)

### CR47-7 (L) — 대조군 `(발송 상한 대조군)` 이 **문법상 절대 발동하지 않는다**

`monitor-selftest.sh:1493` `avoid "$TMPROOT/rcap3.log" 'ALERT-SUPPRESSED|하루 상한'`.
`avoid()`(`:80`)는 `grep -aq` — **BRE** 다. BRE 에서 `|` 는 리터럴이라 이 패턴은
`ALERT-SUPPRESSED|하루 상한` 이라는 **문자열 하나**를 찾는다(실측: 매치 0). 즉 이 대조군은
무엇을 넣어도 통과한다. `grep -aqE` 를 쓰거나 `avoid` 를 두 번 부를 것.
(같은 파일의 다른 `avoid` 는 `.*` 만 쓰므로 BRE 에서도 동작한다 — 이 한 줄만이다.)

### CR47-8 (L) — `CR46-2` 는 **코드 5곳 전부 닫혔는데 관문은 1곳뿐**

읽기·실측 둘 다로 확인했다: `SSHPW_RE`(`:598`) · `SSHD_RE`(`:609`) · `_anchor_sshd`(`:721`) ·
`_anchor_head`(`:722`) · `_m_unknown`(`:731`) 다섯 곳 모두 `sshd(-session)?` 이고,
`SSHPW_JD_RE`(`:602`)는 `-o cat` 이라 데몬 이름을 안 본다 — **빠진 곳 없음**.
9.8+ 전체 모사(auth.log 를 `sshd-session[…]` 로만 쓰고 가짜 journald 를 물린 격리 실행)에서:

```
SSH : 분류 못 하는 SSH 성공 메서드가 있다 — gssapi-with-mic
SSH2차 : ... auth.log sshd 줄 1개 ...        ← SSHD_RE 가 sshd-session 을 센다
SSH : 비밀번호 로그인 성공 이번 구간 2건 (기대 0)   ← password + keyboard-interactive/pam
ALERT sshpw · '앵커와 다르다' 오탐 없음
```

다만 관문은 `(T2 9.8+)` 1건뿐이라 **M2·M3·M4·M5 가 생존**한다. 되돌리면
`SSHD_RE` → 9.8+ 에서 journald 눈멂 탐지(`jd_blind`)가 죽고, `_anchor_head` → 9.8+ 에서
`logblind` 오탐이 5분마다 난다. 픽스처 `rf7` 에 단언 2줄(`avoid '앵커와 다르다'`,
`want 'auth.log sshd 줄'`)만 더하면 M3·M2 가 죽는다.

### CR47-9 (L) — `CR46-7`(문서 숫자)도 절반만

`DEPLOY.md:1223-1224` 표는 여전히 **197 / 193**, `monitoring.md:670` 도 **197/0/0**,
`monitoring.md:731` 은 *"검사 **197건** … 실측 통과 218"* 로 **한 문장 안에서 어긋난다**.
고쳐진 것은 `DEPLOY.md:1272`·`:1291`(218/193) 과 *"숫자는 판정 기준이 아니다"* 문장뿐이다.
또 `monitoring.md §9` 의 T 목록에 이번에 늘어난 검사(`T2 9.8+`·`발송 상한`·`T2 상태손상`)가 없다.

### CR47-10 (L) — `CR46-4` · `CR46-8` · `CR46-9` · `CR46-10` **미반영 확인**

* `CR46-4` — `SSHPW_JD_RE` 의 `^` 를 지우는 변이(M19)가 **217/0/1 rc=0 생존**. 그대로다.
* `CR46-8` — `monitoring.md:663` 의 *"남은 것은 `dbstruct`·`dbstruct_cfg` 뿐"* 과
  `check_pgcrash`·`check_jsonlog` 의 무조건 `clear_alert` 그대로.
* `CR46-9` — `DEPLOY.md §9-1` 에 문서 배포 단계 없음 · 프로브 창 `+3600` 그대로 ·
  `monitoring.md:240` 의 **"문턴" · "끔다"** 오타 그대로.
* `CR46-10` — `rj7` 사전조건 `harn` 뒤 단언 5건이 여전히 조건 없이 돈다.

---

### 이번 라운드가 **정말로 고친 것**(내가 다시 확인함)

* **`CR46-1` 해소** — 서버 격리 사본 기준선 **217/0/1 · HARN 0 · rc=0**(50초). PM 보고와 일치.
* **`CR46-2` 해소** — 5곳 전부. 9.8+ 전체 모사에서 `password`·`keyboard-interactive/pam` 을
  잡고 `gssapi-with-mic` 를 "모른다"고 말하며 앵커 오탐이 없다(위 CR47-8 의 실행 로그).
  M1 이 관문에서 죽는다.
* **`CR46-3` 해소(픽스처 부분)** — 실측 위조 문자열(`FORGE_PREFIX`/`FORGE_UPREFIX`)이 들어왔고,
  `(T2 앵커)`·`(T2 메서드)` 는 **공허하지 않다**: M16(앵커 blind 삭제)→2건, M17(메서드 blind
  삭제)→1건, M18(kbdint 제거)→1건이 각각 붉어진다. 위조 대조군(`rf2`)도 진짜를 잡는다.
* **`CR46-6` 절반 해소** — `sshpw_off` 손상이 **행동으로** 잡힌다(M11 → 2건 붉음).
  첫 실행 `off=""` 는 조용하다(격리 실행에서 `기준값 설정` 만 나오고 사유 0건) — 정상 경로 무해.
* **HARN 이 실패를 숨기지 않는다** — 21회 실행 전부 `HARN 0`. 생존한 변이 10종도
  전부 `HARN 0` 인 채로 생존했다(하네스가 가린 것이 아니라 **검사가 없는 것**이다).

### 리뷰 위생

* 트리 **동결 해시 5/5 일치**로 시작·종료. **저장소 소스 수정 0** · `git checkout --` 미사용 ·
  **커밋 없음** · `frontend/**` · `docs/02-design/**` 무접촉 · LF 유지(세 셸 모두 CR 0바이트).
* 변이·실험은 전부 서버 격리 사본 `/root/rev-cr47/` 에만. **삭제 확인**(`No such file or directory`).
* `/opt/realestate/scripts/**` **무접촉** — 이 경로를 참조한 명령이 한 건도 없다.
* **텔레그램 0통.** 자체검사는 `RE_MON_DRY_RUN=1`(하네스 강제) · URL 은 닫힌 포트 `127.0.0.1:9`.
  발송 실험 2건만 `RE_MON_DRY_RUN=0` 이었고, 그때는 `RE_MON_CRED_FILES` 를 **없는 파일**로 두어
  `alert_creds` 가 실패했다 → curl 이 한 번도 실행되지 않았다(로그에 `ALERT-CHANNEL-MISSING` 만).
* **윈도우에서 `monitor-selftest.sh` 미실행** — 판정 근거는 전부 리눅스 실측이다.
* `pytest` 는 이번 범위(`deploy/**`·`docs/**`)에 해당 없어 돌리지 않았다.

### pass 조건 (다음 라운드)

1. **CR47-1** — 상한은 **나간 통수**만 세고, `send_capped` 는 **통보가 전달된 뒤**에 찍는다.
   "채널이 5시간 죽었다가 살아나면 그 뒤 경보가 나간다" 를 실측으로 적을 것.
2. **CR47-2** — 상한 검사에 ① 누적 도달 경로 ② 상한 통보 본문만 보는 좁은 패턴
   ③ 기본값이 하중을 받는 실행. M6·M7·M13·M14·M15 가 각각 붉어지는 것을 적을 것.
3. CR47-3~6 은 차단 아니지만 **CR47-1 과 같은 자리**라 같이 닫는 것이 싸다
   (특히 CR47-4 는 3라운드 연속 이월이고 `oomkill_*` 쪽은 자가복구도 안 된다).
4. CR47-7~10 은 한 줄짜리(대조군 `-E` · `rf7` 단언 2줄 · 문서 숫자 · 오타).

---

## CR-048 · 2026-08-04 · `CR-047` 차단 2건(CR47-1 · CR47-2) 조치 재검증 — **범위: 하루 발송 상한 하나** (트리 동결 · 기준 `199d9fe` 작업본)

**판정: PASS** — 차단(H) **0건**. CR47-1 · CR47-2 는 **읽기와 실측 양쪽으로 해소 확인**.
새로 남기는 것은 Medium 3 · Low 1 이며 전부 비차단이다.
(PM 지시대로 범위를 발송 상한으로 좁혔다. CR-047 의 비차단 이월분 CR47-3~CR47-10 은 이번 판정 대상이 아니며 **미검증 이월**이다.)

### 0. 동결·위생

동결 해시 3/3 시작·종료 모두 일치.

```
83bda3dd…  deploy/monitor.sh
7f8a35aa…  deploy/monitor-lib.sh
6c67f837…  deploy/monitor-selftest.sh
```

저장소 소스 수정 0 · `git checkout --` 미사용 · 커밋 0 · `frontend/**`·`docs/02-design/**` 무접촉 ·
`/opt/realestate/scripts/**` 무접촉(참조 명령 0건) · 텔레그램 0통 · LF 유지 ·
윈도우에서 `monitor-selftest.sh` 미실행. 격리 `/root/rev48/` 사용 후 삭제.
자체검사 실행 **4회**(기준값 1 + 변이 3), 각 55초.

### 1. CR47-1 → **해소.** `_send_quota_commit` 호출부 전수 확인

`grep -n "_send_quota" deploy/monitor-lib.sh` 결과 정의 2 · 호출 3 이 전부다.

| 위치 | 경로 | commit | 판정 |
|---|---|---|---|
| `:266` | `_send_quota_check; q=$?` | — | 상태 불변(날짜 롤오버만). 맞다 |
| `:268-269` | `q=1` 억제 후 `return 1` | 없음 | 맞다 — 안 나갔으니 안 센다 |
| `:277` | DRY-RUN 출력 후 `return 0` | **있음** | 성공 경로. 의도적(§5 참조) |
| `:285-286` | `alert_creds` 실패 → `return 1` | 없음 | 맞다 — CR47-1 이 지적한 그 경로 |
| `:296` | `code=200` 직후 | **있음** | 성공 경로. 맞다 |
| `:304-306` | curl 3연속 실패 → `return 1` | 없음 | 맞다 |

**성공 경로 2곳에 정확히 있고, 실패 경로 3곳에 정확히 없다. 빠진 곳·잘못 붙은 곳 없음.**
`send_capped=1` 도 `commit` 안(`:256`)으로 옮겨져 **상한 통보가 실제로 나간 뒤에만** 잠긴다 —
CR47-1 이 지적한 *"통보를 보내기 전에 잠가서 그 통보가 같은 장애로 실패하면 영영 재시도 없음"* 이 닫혔다.
`q=2` 로 전송이 실패하면 `send_capped` 가 0 인 채 `count` 도 그대로라, 다음 경보에서 다시 `q=2` 가 나와
**상한 통보를 재시도**한다(`:245-248`). 설계대로다.

fail-open 3중도 확인: 상한값이 비숫자→60(`:221-223`) · **0→60**(같은 줄의 `|0`) · `send_count` 손상→통과(`:244`).

### 2. CR47-2 → **해소.** 변이 3종이 **전부** 죽는다

서버 격리 사본(`/root/rev48/{base,A,B,C}`)에서 실측. 변이는 문자열 치환으로만 만들었고
`monitor-lib.sh` 한 파일만 다르다(나머지 4파일 해시 동일).

| | 변이 | 결과 | 죽인 검사 |
|---|---|---|---|
| **기준** | 없음 | **231 통과 · 실패 0 · 건너뜀 1 · HARN 0 · rc=0** | — |
| **A** | `commit` 을 `check` 직후로 이동 + 성공 지점 2곳에서 제거 (= CR47-1 옛 결함 복원) | 230/**1**/1 · HARN 0 · **rc=1** | `(발송 상한) 발송 실패도 상한으로 센다 …` (사) |
| **B** | `SEND_MAX_DAY` 기본값 `60→0` + `case` 에서 `\|0` 제거 (= 전 경보 영구 침묵) | 229/**2**/1 · HARN 0 · **rc=1** | `(발송 상한 대조군) 평범한 실행에서 경보가 억제된다` + `평시에 상한 통보가 나간다` (마) |
| **C** | `commit` 안의 `kv_set send_count "$((count + 1))"` 삭제 | 230/**1**/1 · HARN 0 · **rc=1** | `(발송 상한) send_count 가 안 오른다 — 상한이 영영 안 걸린다` (다) |

CR-047 에서 **생존**했던 M13(=C) · M15(=B) 가 이번에는 죽는다. HARN 은 4회 실행 전부 0 이라
초록/빨강을 근거로 쓸 수 있다. `(발송 상한)` 검사 8건은 기준값에서 전부 PASS.

### 3. 기준값 검증 — 판정 기준은 일치, **숫자는 불일치**

PM 보고 `226 통과 · 실패 0 · 건너뜀 3 · HARN 0 · rc=0` 에 대해
실측 `231 통과 · 실패 0 · 건너뜀 1 · HARN 0 · rc=0`.
`DEPLOY.md:1292-1294` 가 못 박은 **판정 기준(실패 0 · HARN 0 · rc=0)은 3/3 일치**하므로 판정에 영향 없음.
숫자 차이의 원인은 격리 사본의 구성이다 — 자세한 것은 CR48-4.
(첫 시도에서 `job-run.sh` 를 안 옮겨 실패 8 · HARN 4 가 났다. 이는 **내 반출 누락**이고 코드 결함이 아니다.
 `job-run.sh` 를 채운 뒤의 값이 위 231/0/1 이다.)

---

### CR48-1 (M) — HTTP 200 성공 경로의 `commit` 은 **관문이 한 번도 안 밟는다**

`monitor-lib.sh:296` 한 줄만 지우는 변이는 자체검사를 **통과한다**(실행 아님 · 읽기로 확정).
근거는 전수다:

* `monitor-selftest.sh:333` — `run_mon()` 이 **항상** `RE_MON_DRY_RUN=1` 을 넣는다.
* `:1543` — 유일하게 `RE_MON_DRY_RUN=0` 인 (사) 는 `RE_MON_CRED_FILES` 를 **빈 파일**로 줘서
  `alert_creds` 가 실패한다(`monitor-lib.sh:281`) → **curl 에 도달하지 않는다**.
* `:1807-1811` — 자체검사가 직접 부르는 `send_telegram` 도 `DRY_RUN=1`.

즉 상한을 소진시키는 두 지점 중 **운영에서 실제로 쓰이는 쪽**(`:296`)의 커버리지가 0 이다.
지우면 운영에서 `send_count` 가 영영 안 올라 상한이 **무력화**된다 — CR47-2 가 지적한
*"있으나 마나"* 와 같은 결과인데, 이번 조치는 DRY-RUN 쪽만 막았다.

차단으로 올리지 않는 이유: 현재 코드는 옳고, 이 줄이 죽어도 **경보는 계속 나간다**(소음 쪽으로 넘어짐).
침묵이 아니므로 이 프로젝트의 H 기준에 못 미친다.

**수정 제안(1줄, 이 파일의 기존 관례와 동일).** 네트워크 모사 없이 구조로 잰다 —
`:1558` 의 `raise_alert sshpw 900` 검사와 같은 방식이다.

```sh
# code=200 블록 안에 commit 이 있는가 (:296 을 지우는 변이 자리)
if sed -n '/if \[ "\$code" = "200" \]/,/^    fi$/p' "$HERE/monitor-lib.sh" | grep -q '_send_quota_commit'; then
  ok "(발송 상한) HTTP 200 성공 지점에서도 상한을 소진한다 (운영 경로 · CR48-1)"
else
  ng "(발송 상한) 진짜 전송 성공이 상한을 안 쓴다 — 운영에서 상한이 영영 안 걸린다"
fi
```

### CR48-2 (M) — 상한이 **일일 요약**까지 막는다. 이 프로젝트가 정한 "살아 있음" 신호가 오염된다

`monitor.sh:1512-1516` 의 일일 요약은 `send_telegram` 을 그대로 타므로 상한에 걸린다.
그런데 그 요약 본문이 스스로 이렇게 적는다:

```
※ 이 메시지가 아침에 오지 않으면 감시나 서버가 멈춘 것이다.
```

`monitor-lib.sh:283` 도 자격증명이 없을 때 *"매일 오는 요약이 안 오는 것으로 사람이 안다"* 를
최후의 안전장치로 삼는다. 상한이 소진된 날에는 그 신호가 **거짓**이 된다 —
소음 사고(폭주)가 **서버 사망**처럼 보인다. 상한 통보를 한 통 받긴 하지만, 그것은 폭주 시작 시점에
경보 수십 통에 섞여 오고 요약은 그로부터 몇 시간 뒤 안 온다.

**수정 제안**: 요약은 상한 밖에 둔다(하루 1통이라 폭주 위험이 없다).
`send_telegram` 에 2번째 인자 `bypass_cap` 을 두거나, `_send_quota_check` 를
`[ "${2:-}" = "always" ] || { _send_quota_check; q=$?; }` 로 감싼 뒤 `:1514` 만 `always` 로 부른다.
`:1456`(감시 채널 시험)도 같은 취급이 자연스럽다.

### CR48-3 (M) — 운영자 손검사(`RE_MON_DRY_RUN=1`)가 **운영 상태를 오염**시킨다. 상한은 그중 작은 쪽

`DEPLOY.md:1296` 과 `:1348` 이 지시하는 손검사 레시피에 `RE_MON_STATE` 가 없다.

```
RE_MON_DRY_RUN=1 RE_MON_PRINT=1 ./monitor.sh --fast    # 알림 안 나간다
```

`STATE_DIR="${RE_MON_STATE:-/var/lib/realestate-monitor}"`(`monitor-lib.sh:21`)이므로
이 실행은 **운영 상태 디렉터리**에 쓴다. 결과 둘:

1. (이번에 새로 생김) `:277` 이 `send_count` 를 올려 **운영 상한을 깎는다**.
2. (전부터 있었음, **이쪽이 더 크다**) DRY-RUN 이 `return 0` 이므로 `raise_alert` 가
   `alerts/<key>.sent` 를 찍는다(`monitor-lib.sh:327`). 그러면 **진짜 경보가 쿨다운만큼 억제**된다 —
   대부분 21600초(6시간), `cert`·`pgcrash`·`jsonlog`·`sshjournal`·`dbstruct_cfg` 는 **86400초(24시간)**.
   장애를 들여다보려고 손검사를 돌린 그 순간에 그 장애의 경보가 최대 하루 동안 안 온다.

한편 **자체검사는 결백하다** — `monitor-selftest.sh:126` 이 `source` 보다 먼저
`export RE_MON_STATE="$TMPROOT/state-lib"` 를 하고, `run_mon`(`:333`)도 상태를 넘긴다.
실측으로도 확인했다: 자체검사 4회를 돌린 뒤에도 `/var/lib/realestate-monitor/kv/` 의 `send_*` 파일은 **0개**다.

**수정 제안(코드 아님, 문서 1줄).** 상한에 예외를 파지 말고 손검사를 격리한다.

```
RE_MON_STATE=$(mktemp -d) RE_MON_LOG=/dev/null RE_MON_DRY_RUN=1 RE_MON_PRINT=1 ./monitor.sh --fast
```

한 줄로 위 두 부작용이 **동시에** 사라진다. 상한 코드에는 손댈 필요가 없다.

### CR48-4 (L) — 보고 숫자 `226/3` 과 실측 `231/1` 불일치

`DEPLOY.md:1291` 은 `218 / 실패 0 / SKIP 0 / HARN 0`, `:1292-1294` 는 *"숫자는 판정 기준이 아니다"* 를
못 박아 두었으므로 판정에는 영향이 없다. 다만 PM 보고 `226/0/3` 과 내 실측 `231/0/1` 이 다르다.
실측의 유일한 SKIP 은

```
SKIP (상태손상 oomkill) cgroup·docker 가 있어야 도달 — 행동으로 못 잼(아래 구조 검사로 대신)
```

이고, 서버는 cgroup/docker 가 있으니 PM 쪽 SKIP 3 은 **반출 사본에 파일이 덜 들어간 결과**로 보인다
(내 첫 시도도 `job-run.sh` 누락으로 실패 8 · HARN 4 가 났다). 자체검사가 읽는 파일은
`monitor.sh` · `monitor-lib.sh` · `market-index.sh` · `job-run.sh` · `../docs/05-monitoring/monitoring.md`
**5개 전부**다(`grep -oE '\$HERE/[A-Za-z0-9_./-]+'`).
→ `DEPLOY.md` 의 격리 실행 절차에 이 5개 목록을 못 박아 둘 것. 안 그러면 다음 라운드도 숫자가 또 달라진다.

---

### PM 질문 ① — DRY-RUN 을 "나간 것"으로 세는 결정, 부작용이 수용 가능한가

**수용 가능하다. 단 CR48-3 의 문서 1줄을 고치는 조건에서.** 근거 셋:

1. **관문은 운영을 안 건드린다.** 자체검사가 상태를 이미 격리하므로(위 실측: 4회 실행 후 운영 `send_*` 0개)
   "검사 때문에 운영 상한이 깎인다"는 시나리오는 **없다**.
2. **남은 노출은 운영자 손검사 하나뿐인데, 그 경로는 상한보다 훨씬 큰 부작용(쿨다운 `.sent` 오염,
   최대 24시간 침묵)을 이미 갖고 있다.** 즉 이번 결정이 새 문제 계열을 만든 게 아니라
   기존 문제의 항목 하나를 늘렸다. 고칠 지점은 상한이 아니라 **손검사 격리**다.
3. **반대로 상한만 DRY-RUN 예외로 빼면, 이 프로젝트가 두 라운드 동안 싸운 그 실패를 다시 만든다** —
   "관문이 못 밟는 경로"가 생긴다. 지금 `commit` 의 유일한 실행 커버리지가 DRY-RUN 경로다(CR48-1).
   그걸 빼면 커버리지가 0 이 된다.

### PM 질문 ② — 상한을 빼는 게 더 안전한가

**두세요(유지 권고).** 근거:

* **쿨다운은 상한을 대체하지 못한다.** `clear_alert` 가 `.active` 와 `.sent` 를 **함께** 지운다
  (`monitor-lib.sh:339`). 그래서 해소 직후 재발화는 쿨다운을 **거치지 않고** 즉시 나간다.
  즉 플래핑(뜬다↔풀린다) 경로는 쿨다운으로 전혀 안 막히고, `--fast` 1분 주기에서
  왕복 2통 × 1440 = **하루 2880통**이 이론상 가능하다. `sshpw 900` 과 무관한 경로다.
* **앵커는 다른 문제를 푼다.** 앵커는 *원격 위조*(남이 auth.log 에 심는 것)를 막는 장치이지
  *우리 쪽 폭주*를 막는 장치가 아니다. 상한의 대체재가 아니다.
* **폭주의 피해가 우리 채널을 넘는다.** 텔레그램 봇을 `pjt12-adsense` 와 **공유**해서 읽는다
  (`monitor-lib.sh:31-32`). 폭주하면 남의 채널까지 묻는다.
* **상한이 두 라운드 동안 낸 결함은 이번에 둘 다 닫혔다** — 변이 3종이 전부 죽고,
  fail-open 이 3중(비숫자→60 · 0→60 · `send_count` 손상→통과)이라
  "상한이 채널을 죽인다"는 최악 경로가 좁아졌다. 지금 빼면 **닫힌 결함 때문에 살아 있는 방어를 버리는 것**이다.

**단, 상한을 그대로 두되 아래 둘을 다음 라운드 후보로.**
(ㄱ) **CR48-2 — 일일 요약을 상한 밖으로.** 상한이 침묵 신호를 오염시키는 것만은 지금 구조의 실제 약점이다.
(ㄴ) **플래핑 근원 차단** — `clear_alert` 에도 최소 지속시간/쿨다운을 둔다. 그러면 상한은 진짜 마지막 방어선으로 내려가고,
     "상한이 발동한다 = 이미 뭔가 크게 잘못됐다" 가 되어 전역 60 이 남을 굶기는 문제도 같이 줄어든다.

### 다음 라운드에 무엇을 보면 pass 가 유지되나

이번은 **PASS** 이므로 조치 의무는 없다. 다만 CR48-1(관문 1줄) · CR48-2(요약 예외) ·
CR48-3(문서 1줄)은 셋 다 **작고 근거가 확정된 것**이라, 다음 변경에 묶어 넣는 것을 권한다.
셋을 넣으면 발송 상한 주제는 닫힌다.

---

## CR-049 · 2026-08-04 · fail2ban 감시 편입(A) + 백테스트 골격(B) + 단지 유형(C) — 커밋 전

**범위(3덩어리 · 전부 미커밋)**

| | 대상 |
|---|---|
| A | `deploy/monitor.sh`(+223) · `deploy/monitor-selftest.sh`(+299) · `docs/05-monitoring/monitoring.md`(+20) · `docs/05-monitoring/fail2ban.md`(신규) |
| B | `backend/app/domain/backtest/**`(7파일 1,530줄) · `backend/tests/test_backtest.py`(1,088줄 86검사) · `backend/scripts/run_backtest.py`(352줄) · `docs/02-design/backtest.md` |
| C | `backend/app/domain/character/**`(4파일 671줄) · `backend/tests/test_character.py`(448줄 47검사) · `docs/02-design/ux/complex-typing.md` · `docs/02-design/api-spec.md`(+60) |

**동결 해시 — 시작·종료 모두 일치(2/2)**
```
43169225702438ab3dc9769e032233c100adaba64df7550aa554fd55134a29d4  deploy/monitor.sh
ccc8590b50b7ebe853adf3cbe88bd9c8dcbcf623169cc2ce574f0e959807a052  deploy/monitor-selftest.sh
```
리뷰 중 트리 변경 0(`git status` 시작=종료). `backend/app/domain/backtest/asof.py` 는 변이 시험으로
잠시 고쳤다가 원복 — 종료 시 `1933fd89b99240f876bc580f9d2090042b5f4a5680cca36c1e922762ee253e1a`(원본).
`/opt/realestate/scripts/**` 무접촉 · 텔레그램 발화 0 · 격리 `/root/rev49/`(종료 시 삭제) · `frontend/**` 무접촉.

### 기준값 재현 (전부 내가 직접 실행)

| 항목 | 담당자/PM 보고 | 내 실측 | |
|---|---|---|---|
| 서버 격리 자체검사 | 271 / 0 / 1 / HARN 0 / rc=0 | **271 / 0 / 1 / HARN 0 / rc=0** | 일치 |
| `test_backtest.py` + `test_character.py` | 86 + 47 | **133 passed** | 일치 |

---

## 변이 시험 4종 — **4/4 죽었다**

관문이 공허하지 않은지 직접 확인했다. 변이는 python 문자열 치환으로 만들고 `tar`/`stdin` 으로만 옮겼다.

| # | 변이 | 결과 |
|---|---|---|
| ① | A — 규칙 존재 검사 제거 (`monitor.sh:1203` `if [ -z "$jump" ]` → `if false`) | **rc=1 · 실패 3** — `(규칙) 규칙이 통째로 빠졌는데 …조용하다` · `(규칙) 요약이 규칙 소실을 말하지 않는다` · `(규칙 해소) 규칙을 다시 걸어도 경보가 안 꺼진다` |
| ② | A — clear 경로 1개 제거 (`clear_alert f2b_stale` 줄 삭제) | **rc=1 · 실패 2** — `(필터 해소) 필터가 되살아나도 경보가 안 꺼진다` · `(필터 해소) …`.active` 가 남는다` |
| ③ | B — as-of 누출 가드 제거 (`asof.py:121` `if trade.contract_date > cutoff: continue` 무력화) | **rc=1 · 실패 15** — `TestLookAhead` 5건 전부 + `test_universe_is_built_from_the_as_of_view_only` + 손계산 검사들 |
| ④ | B — `apt_dong` 마스킹 제거 (`asof.py:142` → `apt_dong = trade.apt_dong`) | **rc=1 · 실패 1** — `test_apt_dong_is_masked_before_registration` (→ CR49-6) |

변이 ①이 포트 검사를 안 죽인 것은 정상이다(점프 grep 자체는 남겨 두고 "없음" 판정만 없앤 변이라
`--dports 2222` 픽스처는 여전히 `badport` 로 잡힌다). 즉 변이가 **의도한 검사 하나만** 정확히 겨눴다.

---

## A — fail2ban 감시. 담당자가 서버 실측으로 바꿨다는 4건을 내가 다시 쟀다

| # | 담당자 주장 | 내 실측(같은 서버·`fail2ban 0.11.2`) | |
|---|---|---|---|
| 1 | `fail2ban-client status <없는jail>` 은 **rc=0** | `Sorry but the jail 'x' does not exist`(stdout) + stderr `ERROR NOK` + **rc=255** | ❌ **틀렸다** → CR49-1 |
| 2 | 크론 PATH `/usr/bin:/bin` 인데 `iptables` 는 `/usr/sbin` 에만 | `ls /usr/bin/iptables` → `No such file` · `which iptables` → `/usr/sbin/iptables` · root crontab·`/etc/crontab` 에 `PATH` 지정 없음 | ✅ 맞다 |
| 3 | `is-active` 는 inactive 일 때 **rc=3 + stdout 낱말** | `systemctl is-active nosuchunit-xyz` → stdout `inactive` · **rc=3** | ✅ 맞다 |
| 4 | 하루 235~517건이 차단 조건에 닿는다 | 재계산 안 함(auth.log 전수 재생 비용). 현재 jail 실측은 `Total banned 24 / Total failed 220 / Currently banned 4` 로 **자릿수는 모순되지 않는다** | 미검증(수용) |

`iptables -S INPUT` 실측도 픽스처와 글자까지 같다: `-A INPUT -p tcp -m multiport --dports 22 -j f2b-sshd`.

### 좋은 점 — 이 저장소가 다섯 번 놓친 형태(CR-040·42-3·43-1·44-2·47-2)가 이번엔 안 났다

새 경보 키 3개의 clear 경로를 **행동으로** 밟는지 하나씩 확인했다.

| 키 | clear 조건 | 감시불능일 때 | 자체검사가 행동으로 보는가 |
|---|---|---|---|
| `f2b_dead` | `svc = active` (**낱말을 읽어서**) | `svc` 빈 문자열 → `:` — raise 도 clear 도 안 함 | (다) `ALERT-CLEARED` + `.active` 삭제까지 |
| `f2b_rule` | `rule=ok` (iptables 읽힘 ∧ 점프 존재 ∧ 포트 덮음) | `rule=unknown` → clear 금지 | (마) 해소 2검사 + (사) fail-open 4검사 |
| `f2b_stale` | `total > prev` **만** | `total` 빈 문자열 → clear 금지 · 카운터 **감소(재시작 리셋)도 clear 금지** | (자) 해소 2검사 + (차) 리셋 2검사 + (카) rc 오답 3검사 |

변이 ②가 (자)를 정확히 죽였다 = **문구 검사가 아니라 행동 검사**다.
"진짜 정지를 감시불능으로 덮는" 반대 방향도 막혀 있다 — `is-active` 를 **rc 가 아니라 stdout 낱말**로
읽으므로 rc=3(실측)이 와도 `inactive` 로 정확히 판정한다. 빈 출력만 감시불능이다.

### CR49-1 (M) — "없는 jail 에 rc=0" 은 **거짓 실측**이다. 세 파일이 그 거짓을 근거로 삼는다

**재현**
```
$ ssh root@<host> "fail2ban-client status nosuchjail-xyz >/dev/null 2>&1; echo \$?"
255
$ ssh root@<host> 'fail2ban-client status nosuchjail-xyz 2>/dev/null; echo RC=$?'
Sorry but the jail 'nosuchjail-xyz' does not exist
RC=255
```
`fail2ban-client status sshd` 는 rc=0 이다. 즉 **rc 로 가를 수 있다.** 그런데

* `deploy/monitor.sh` 머리주석(`⛔ fail2ban-client status <없는jail> → **rc=0** … 실측`)과
  본문 주석(`⛔ 여기가 rc 를 안 믿는 이유다 — 없는 jail 에도 rc=0 이 온다(실측)`)
* `deploy/monitor-selftest.sh` 머리주석 + 가짜 `fail2ban-client`(없는 jail에 `exit 0`) +
  하네스 전제 `PATH=… fail2ban-client status nosuchjail >/dev/null 2>&1`(= **rc=0 을 요구**)
* `docs/05-monitoring/monitoring.md` T6d 줄(`**없는 jail 에도 rc=0** 이라는 실측을 못 박음`)

**세 곳이 같은 틀린 사실을 정본처럼 적었다.**

**동작 결함은 아니다.** 코드는 rc 를 아예 안 보고 `Total banned:` 추출 성공 여부로만 판정하므로,
실제 rc=255 든 가정된 rc=0 이든 결과가 같다(`total` 빈 문자열 → `blind_add`). 오히려 rc 무시가 더 안전하다.
**문제는 픽스처가 현실과 다르게 군다는 것**이고, 그건 이 파일이 스스로 못 박은 규칙이다 —
*"픽스처가 현실과 다르게 굴면 검사가 공허해진다"*(monitor-selftest.sh 머리주석). 결과로:
실제 모양(**rc≠0 + stdout 에 `Sorry but…`**)은 자체검사에서 **한 번도 밟히지 않는다**.
그리고 하네스 전제 검사가 거짓 사실을 **요구**하므로, 누가 픽스처를 사실대로 고치면 하네스오류로 붉어진다.

**고칠 것**
1. 세 곳의 "실측 rc=0" 문구를 실측(rc=255 · stdout 에 `Sorry but…`)으로 정정.
2. 가짜 `fail2ban-client` 가 없는 jail 에 `exit 255` + 같은 stdout 을 내게 바꾸고, 하네스 전제도 그에 맞출 것
   (`! fail2ban-client status nosuchjail >/dev/null 2>&1`).
3. **코드는 그대로 둔다.** rc 를 안 믿는 판정이 옳다 — 근거만 "rc 가 버전·경로마다 다를 수 있어
   `Total banned:` 추출로 판정한다"로 바꾸면 된다.

### CR49-2 (L) — `monitoring.md` 신규 4행 오타 4개

설계 정본 문서라 낱말이 뜻을 바꾼다.

| 위치 | 지금 | 맞는 말 |
|---|---|---|
| 7d-① | 진짜 정지가 '감시불능'으로 **덤인다** | 덮인다 |
| 7d-③ | 진짜 증가가 **곰** 꺼 준다 | 곧 |
| 7d-④ | 알림·요약에 **IP 는 싫지 않는다** | 싣지 |
| 제외표 | 요약에 사실로만 **싰고** | 싣고 |

---

## B — 백테스트. **누출 차단은 진짜다.** 단, 실행기에 문제가 있다

### 누출 차단 — 내가 직접 확인한 결론

`asof.py` 를 읽고 변이 ③·④ 로 밟은 결과, **T 이후 데이터가 점수에 닿는 경로는 문서에 적힌 하나
(`is_cancelled`)뿐이고 그 밖의 미기재 누출은 찾지 못했다.** 확인한 경로:

| 경로 | 판정 |
|---|---|
| 계약일 경계 `cutoff = T − 30일` | ✅ 가드 있음. **변이 ③으로 15검사가 죽는다** — 담당자가 단언한 "가드를 끄면 상위 2가 뒤집힌다"는 `test_the_poison_is_actually_potent` 에 손계산과 함께 박혀 있고(`(c5,c3)` → `(c3,c1)`), 그 단언이 실제로 하중을 받는다 |
| `apt_dong` (등기 후 채워짐) | ✅ 가드 있음(`registered_at > T` 또는 `None` 이면 마스킹). 단 CR49-6 참조 |
| `registered_at`·`cancelled_on` 미래값 | ✅ 지운다 |
| 시장지수(`market_price_index`) | ✅ **읽지 않는다.** 양 끝을 같은 `price_point()` 로 재서 비만 쓴다(창 폭이 같아 시점 중심 오프셋도 같다) |
| 세대수(현재 스냅샷) | ✅ 시불변이 맞다. T 이후 준공 단지는 T 창에 거래가 없어 유니버스에 못 든다 |
| 피어 중위 | ✅ T 시점 셀들로만 만든다 |
| `outcomes`(미래 뷰) → 점수 | ✅ 구조적으로 차단. `run_fold` 가 `scorer(cells)` 로 점수를 **먼저 확정**하고, `Scorer` 는 `AsOfCell` 만 받는다(`AsOfCell` 에는 원본 거래도 미래 칸도 없다) |
| `is_cancelled`(기본 `EXCLUDE_FINAL`) | ⚠️ **누출이 맞고, 문서·주석·테스트가 그렇게 적고 있다.** 상·하한 두 정책으로 범위를 말하는 완화책도 있다 → 다만 CR49-4·CR49-5 |

즉 **B 의 핵심 주장은 성립한다.** 아래는 그 주변의 결함이다.

### CR49-3 (M·상 — 첫 실행 전 반드시) — 실행기가 전 구간 거래를 **한 번에 메모리에 올린다**

`backend/scripts/run_backtest.py:261`
```python
trades = list(repo.trades_for_backtest(start=start, end=end))
```
리포지토리는 제너레이터로 시군구 단위 스트리밍을 하는데(설계대로), **유일한 소비자가 그걸 통째로
리스트로 접는다.** `start/end` 는 폴드 **전체의 합집합**(`min`/`max`)이라 폴드가 늘수록 더 커진다.

**실측**

| 항목 | 값 | 근거 |
|---|---|---|
| `BacktestTrade` 1행 | **383 B** | `tracemalloc` 로 20만 행 생성 측정(실제 RSS 는 이보다 큼) |
| `backtest.md §8` 첫 실행 예시 `--as-of 2025-01-31` 의 필요 범위 | 2023-01-01 ~ 2026-01-01 | `FoldSpec.required_contract_range`(2W+H) |
| 그 범위의 행 수 | **613,228행** | 운영 DB 실측 SELECT |
| 예상 힙 | **≈235 MB**(tracemalloc 기준) | 613,228 × 383 B |
| 서버 메모리 | **총 957 MB · available 225 MB · 스왑 2 GB 중 이미 818 MB 사용 중** | `free -m` · `swapon --show` |

`repository.py` 머리주석과 `backtest.md §8` 이 **"운영 DB 는 `mem_limit 192MB` 다 — 시군구 단위로
나눠 읽고 스트리밍으로 넘긴다"** 를 규칙으로 못 박았는데, 실행기가 그 규칙의 목적을 무효로 만든다
(DB 쪽 결과집합은 실제로 잘려 있으니 **DB 는 안전하고, 위험한 쪽은 클라이언트다**).
`§7 한계` 12줄 어디에도 이 제약이 없다.

**왜 H 가 아니라 M(상) 인가** — 스왑이 1.2 GB 남아 있어 하드 OOM 보다는 **스래싱**으로 끝날 가능성이
높고, 오프라인·수동 실행 스크립트이며 데이터를 깨지 않는다(읽기 전용 SELECT). 다만 그 대가는
**API 컨테이너(mem_limit 192m)와 postgres 가 같은 상자에 산다**는 것이고, 문서의 **첫 실행 명령**이
바로 이 경로다. **첫 실행 전 필수 수정**으로 둔다. (PM 이 "서버 증설 불가·최소구성" 을 못 박은 프로젝트다.)

**고칠 것(택1 이상)**
1. 폴드별로 그 폴드 범위만 읽고, 시군구 묶음 단위로 **셀 집계까지 접은 뒤** 원본 행을 버린다
   (`build_cells`/`build_outcomes` 가 셀 단위 누적을 받게).
2. 최소한: 실행 전 `count(*)` 를 먼저 재서 **예상 행수·예상 메모리를 로그로 찍고 임계 초과면 멈춘다**
   (`--force` 로만 통과). `build_market_index.py` 가 이미 하는 방식과 맞춘다.
3. `§7 한계` 에 이 제약과 실측 숫자를 한 줄로 적는다.

### CR49-4 (M) — 산출 JSON 이 **해제 정책을 안 적는다** → "상·하한 두 번 돌려 범위로" 가 파일에서 사라진다

`--cancellation` 의 도움말이 직접 **"상·하한 두 번 돌려 범위로 보고하세요(§2-D)"** 라고 지시한다.
그런데 `run()` 의 payload(`run_backtest.py:299-309`)에도 `fold_row()`(`engine.py:482-506`)에도
`cancellation` 이 없다. `unmeasured_policy` 는 실린다.

결과: `--cancellation exclude_final` 로 만든 JSON 과 `include_all` 로 만든 JSON 이
**내용만으로는 구별되지 않는다.** 범위 보고의 두 끝을 나중에 아무도 증명할 수 없다.
같은 이유로 `min_trades` · `min_peer_cells` · `report_lag_days` · `seed` 도 payload 에 없어 **재현이 안 된다**
(`top_n` · `unmeasured_policy` 만 `fold_row` 에 있다).

**고칠 것**: payload 에 `params` 블록(`cancellation` · `min_trades` · `min_peer_cells` ·
`report_lag_days` · `seed` · `null_draws`)을 넣고, 두 정책 산출물이 서로 다른 파일임을 파일 내용이 말하게 할 것.

### CR49-5 (M) — 독스트링이 **무조건으로** "T 이후에 의존하지 않는다"고 단언한다. 기본 정책에서 거짓이다

`asof.py:102` / `engine.py:111`
> `"이 함수의 출력은 T 이후 데이터에 의존하지 않는다."`

기본값 `CancellationPolicy.EXCLUDE_FINAL` 에서는 **거짓**이다. `is_cancelled` 는 *사후에 확정된*
값이고, T 이후에 해제된 거래를 T 시점 표본에서 지운다. 같은 파일이 45줄 위에서
`#: ⚠️ **누출이다** — 사후에 확정된 해제여부로 T 시점 표본을 청소한다` 라고 적어 두었으므로
**두 문장이 서로 모순**이다.

누출 테스트도 이 축을 못 짚는다 — `test_future_trades_do_not_change_the_as_of_view` 의 독
(`LAG_WINDOW_POISON` · 미래 거래)에는 **해제 거래가 없어서** 이 차원은 자동으로 통과한다.
(대신 `TestCancellationPolicy.test_exclude_final_matches_production` 이 사실 자체는 못 박고 있다 — 그래서 M 이다.)

**고칠 것**: 두 독스트링을 조건부로. 예) *"해제 여부(`is_cancelled`)를 제외하면 출력은 T 이후 데이터에
의존하지 않는다. 해제 축은 §2-D 의 상·하한으로만 말한다."* 문장 하나면 된다 —
**이 패키지의 근거가 되는 문장이라 무조건으로 두면 다음 사람이 그대로 믿는다.**

### CR49-6 (L) — `apt_dong` 가드는 지금 **아무 계산에도 닿지 않는다**(변이 ④가 1검사만 죽였다)

`AsOfCell` 에 동 칸이 없고 어떤 스코어러도 동을 보지 않는다. 그래서 마스킹을 통째로 없앤 변이 ④에서
죽은 검사는 **전용 단위 검사 1개**뿐이고, `build_cells` 파이프라인 검사는 **하나도 안 죽었다**.
`assert_as_of` 의 동 그물(`asof.py:174-180`)도 파이프라인 경로에서 한 번도 밟히지 않는다는 뜻이다
(픽스처가 `apt_dong` 을 안 심는다).

방어 자체는 옳다(문서 §2-B 가 "놓치기 쉬운 실제 누출 경로"라 부르는 자리다). 다만 **"동을 쓰는 축이
생기면 막힌다"는 보장이 파이프라인 테스트에는 없다.**
**고칠 것**: `universe_trades()` 픽스처 일부에 `apt_dong` + `registered_at`(T 이후)를 심어,
`build_cells` 경로에서도 마스킹 제거가 `LookAheadError` 로 붉어지게 할 것.

### B 잔가지 (L · 비차단)

* `engine.py:359` `rng.sample(list(pool), top_n)` — 기본 `null_draws=1000` 이라 `list(pool)` 을 1,000번 새로 만든다. 루프 밖으로.
* `FoldResult.universe_size` 는 **전체 셀 수**인데 `universe_measured_rate_pct` 는 **점수가 매겨진 풀** 기준이다(`bench.universe_size`). 같은 표에 나란히 실려 있어 분모가 같다고 읽힌다 — 이름이나 주석으로 구분할 것.
* `summarize` 는 `verdict == measured` 이면서 `quotable_folds == 0` 인 조합을 허용한다(그때 표제 중위는 `None`). `may_calibrate_weights` 가 `>= 2` 를 요구해 결과적으로는 막히지만, 판정 문자열만 읽는 사람에게는 오해 소지.

---

## C — 단지 유형. 사다리 재측정 판단(요청 4번)

### CR49-7 (M) — 사다리는 **재측정 불필요**. 그러나 **같이 실린 실측치는 이미 낡았다**

**결론: `LADDER_AS_OF=2026-08-04` 사다리는 오늘 백필(61만 → 108만 행)로 무효가 되지 않는다.**

| 축 | 백필 영향 | 근거 |
|---|---|---|
| 학군·교통·생활 | **없음** | `complex.geom` + POI 만 본다. 거래를 안 읽는다 |
| 환금 | **없음** | `stats.py:66-70` — `eligible_trades(months=12, as_of=today)` 즉 **오늘 기준 후행 12개월**. 백필이 넣은 것은 2021~2023 로 **창 밖**이다 |

운영 DB 실측: `trade` 최소 계약일 **2021-01-01** · 최대 **2026-07-25** · 총 **1,076,262행**.
후행 12개월 창(2025-08~2026-08)에 들어가는 행은 백필로 늘지 않았다. → **재측정 사유 없음.**
`ladders.py` 머리주석이 이미 이 위험을 정확히 지목해 두었다(*"환금 축은 실거래가 쌓일 때마다 움직인다"*) —
맞는 경계지만 **이번 백필은 그 경계를 건드리지 않는다.**

**⚠️ 다만 같은 날짜로 함께 적힌 아래 값들은 백필 전 데이터이고 이미 틀렸다:**

| 위치 | 적힌 값 | 지금 |
|---|---|---|
| `complex-typing.md §0` | `trade` **611,518행**(취소 제외 578,733) | **1,076,262행** |
| `complex-typing.md §4` | 단지 배율 중위 0.969 · **표본 5건 미만 36.1%** · 홀/짝 잡음 sd 표(25,799셀) | 전부 재측정 필요 |

가격 배율은 **시점 보정 후 전 구간 거래**로 만들므로(§4) 백필에 직접 영향을 받는다. 셀당 표본이 늘면
`PRICE_MIN_SAMPLE=5` 로 걸리는 36.1% 가 줄고, 잡음 sd 가 작아져 `0.85/1.15`(n=5 에서 3σ)는
**필요보다 보수적**이 된다 — 방향이 안전한 쪽이라 지금 당장 위험하진 않다.

**고칠 것**: 배선(`api-spec.md §4.5` 가 🔴 미배선이라 적어 둔 그 작업) **전에 §4 를 재측정**하고
문서의 행 수·36.1%·sd 표를 갱신할 것. 사다리(`ladders.py`)는 손대지 말 것 — 근거 없이 재측정하면
`LADDER_AS_OF` 만 새 날짜가 되고 값은 같아져 이력이 거짓이 된다.
**지금은 응답에 안 실리므로 차단 사유는 아니다.**

### 자기충족 테스트 점검(요청 5번) — B 86 · C 47 표본 확인 결과 **문제 없음**

| 표본 | 기대값의 출처 |
|---|---|
| `test_fold_metrics_match_hand_calculation` | 독스트링에 손계산 전부(`B1=median(+10,+5,0,+10,−5)=+5.0` → 백분위 → 상위 2 → `−7.5`). 구현을 돌려 붙인 값이 아니다 |
| `test_the_poison_is_actually_potent` | `(c5,c3)` → `(c3,c1)` 이 되는 과정을 주석에 산식으로 적고 **튜플을 하드코딩** |
| `test_school_type` / `test_transit_type_…` / `test_two_axes_…` | `LINEAR_LADDER`(10칸) 주입으로 **백분위 = 원점수 + 5** 가 성립 → 전 판정을 암산 검산 가능. 파일 머리에 그 유도가 적혀 있다 |
| 운영 사다리 검사 | 값 자체를 고정하지 않고 **구조·문서화된 한계**만 본다(`101개` · 오름차순 · `환금은 최상위권 문구에 구조적으로 도달 못 함` · `생활 최대 89.6`) — 문서 §8 과 같은 값을 코드로 못 박는 형태라 스냅샷이 아니다 |

문서화된 원칙(*"검산할 수 없는 기대값은 테스트가 아니라 스냅샷이다"*)이 실제로 지켜졌다.

### C 잔가지 (L · 비차단)

* `analysis.py:255` 주석이 `RARE_COMBO_PCT` 를 가리키는데 실제 상수는 `BOTH_TOP_TIER_PCT`(126행). **없는 이름**이다.
* `test_ladder_population_recorded_for_every_axis` 가 `v > 0` 만 본다. 문서가 `15,561`·`13,796` 을 인용하므로 값을 고정할 것 — 사다리를 갈아끼우며 `LADDER_POPULATION` 만 안 고치는 사고를 지금은 못 잡는다.

---

## 판정 — **pass** (High 0)

| ID | 심각도 | 요지 |
|---|---|---|
| CR49-1 | **M** | "없는 jail 에 rc=0" 은 거짓 실측(실제 rc=255). monitor.sh·selftest·monitoring.md 3곳이 인용. 동작 결함 아님 · 픽스처가 현실과 다름 |
| CR49-2 | L | `monitoring.md` 신규 4행 오타 4개 |
| CR49-3 | **M(상)** | 실행기가 613,228행을 한 번에 메모리에 적재(≈235MB) — 서버 available 225MB. **첫 실행 전 필수** |
| CR49-4 | **M** | 산출 JSON 에 해제 정책·실행 파라미터 없음 → 상·하한 두 산출물이 구별 불가 |
| CR49-5 | **M** | 핵심 독스트링이 무조건으로 "T 이후에 의존하지 않는다" — 기본 정책에서 거짓(같은 파일이 스스로 반박) |
| CR49-6 | L | `apt_dong` 가드가 파이프라인 테스트로는 안 밟힌다(변이 ④가 1검사만 죽임) |
| CR49-7 | **M** | 사다리는 재측정 불필요(근거 실측). 단 `complex-typing.md §0·§4` 실측치는 이미 낡음 — 배선 전 재측정 |
| — | L | B 잔가지 3 · C 잔가지 2 |

**pass 근거**: 정확성 결함 없음 · 보안 냄새 없음(알림·요약·JSON 에 IP·자산 정보 없음 · SQL 은 전부
파라미터 바인딩 · 읽기 전용) · 핵심 로직 테스트 있음(변이 4/4 사망으로 공허하지 않음을 증명) ·
레이어 위반 없음(`repository.py` 금지 목록 준수 · 도메인에 SQL 없음, `test_backtest_domain_contains_no_sql_or_engine` 이 지킴).

**다음 커밋 전 처리 권고**: CR49-1(문구·픽스처 정정) · CR49-5(문장 1줄) · CR49-2 — 전부 저비용.
**첫 백테스트 실행 전 필수**: CR49-3. **배선 전 필수**: CR49-7.

---

## CR-050 · 2026-08-05 · `CR-049` Medium 조치 재검증 (CR49-1~7) + `SR-045` 감시 변경 — 커밋 전

**범위**

| | 대상 |
|---|---|
| B′ | **신규 `backend/app/domain/backtest/collect.py`(381줄)** · `asof.py` · `engine.py` · `outcome.py` · `__init__.py` · `scripts/run_backtest.py` · `tests/test_backtest.py`(신규 15검사) · `docs/02-design/backtest.md` §5-1·§7-13·§7-14 |
| C′ | `docs/02-design/ux/complex-typing.md` §0 (낡음/유효 구분표). **`app/domain/character/**` 는 이 라운드에 손대지 않았다**(mtime 확인 — 사다리 재측정 불필요 판정 존중) |
| A′ | `deploy/monitor.sh` · `deploy/monitor-selftest.sh`(`_f2b_bin` 재작성 · `_f2b_order_scan` 신설 · IP 가림 · 하네스 관문) · `docs/05-monitoring/{monitoring.md,fail2ban.md}` |

**동결 해시 — 시작·종료 일치(2/2), 서버 사본까지 3중 확인**
```
ea9c7f8e4266dc56a5a27c8d14f43cbc1d01ab0923da5e67d44df9eb41f72ff1  deploy/monitor.sh
b9164bfb853550f42fe1734b8d1392a4c6b81e017086e9fb78eff00c08c8b29c  deploy/monitor-selftest.sh
```
`git status` 시작=종료(동일). 변이 시험으로 잠시 고친 `collect.py`·`asof.py`·`engine.py` 는
**바이트 단위 원복 확인**(sha256 백업본과 IDENTICAL). `/opt/realestate/scripts/**` 무접촉 ·
텔레그램 발화 0 · 격리 `/root/rev50/`(종료 시 삭제 확인) · `frontend/**` 무접촉 ·
**백테스트 미실행**(`--dry-run` 까지만).

### 기준값 재현 — 전부 내가 직접 실행

| 항목 | PM 기준값 | 내 실측 | |
|---|---|---|---|
| 서버 격리 자체검사(문서 포함 트리 `/root/rev50/{deploy,docs}`) | 290 / 0 / 1 / HARN 0 / rc=0 | **290 / 0 / 1 / HARN 0 / rc=0** (1분 26초) | 일치 |
| 백엔드 `pytest` 전량 | 1,616 passed · 103 skipped | **1,616 passed · 103 skipped · 0 failed** | 일치 |
| `test_backtest.py` + `test_character.py` | — | **148 passed**(101+47) | — |
| `ruff check` (backtest · runner · tests) | — | All checks passed | — |

건너뜀 1건 = `(상태손상 oomkill) cgroup·docker 가 있어야 도달`.

---

## ★ 요청 1 — `FoldCollector` 가 상한을 지키는가 · **결과가 옛 경로와 같은가**

### (가) 동치성 — **독립 참조 구현으로 960회 비교, 불일치 0**

저장소의 동치 검사(`test_one_pass_over_many_folds_matches_the_per_fold_path`)는 **순환**이다 —
`build_cells`/`build_outcomes` 가 이제 `FoldCollector` 에 위임하므로(`engine.py:129`·`158`)
같은 구현끼리 비교한다. 그래서 `collect.py` 를 **전혀 쓰지 않는** 참조 구현을 따로 만들어
옛 경로(`asof.as_of_trades` 로 전량 뷰 → 셀별로 묶어 `outcome.price_point` 로 두 시점)를 재현하고 붙였다.

* 무작위 거래 **40시드 × 300~2,500행**(면적대 7종 · 해제 12% · 등기일 70% · `apt_dong` 80% · 지역 3종)
* × 해제정책 2종(`EXCLUDE_FINAL` · `INCLUDE_ALL`) × 청크 4종(**1 · 3 · 97 · 5,000**) × 폴드 3종
* = **960 비교에서 `AsOfCell`·`CellOutcome` 전량 일치. 불일치 0.**

→ **리팩터가 값을 바꾸지 않았다.** (한 가지 의도적 차이는 CR50-5 에 적었다.)

### (나) 변이 시험 6종

| # | 변이 | 죽은 검사 |
|---|---|---|
| ① | `feed` 의 `list(islice(source, chunk_rows))` → `list(source)` (청크 상한 제거) | **3** — `…never_holds_more_than_one_chunk…` · `…many_folds_do_not_increase…` · `…refuses_to_swallow_more_samples…` |
| ② | `_feed_chunk` 의 `SampleLimitExceeded` raise 제거 | **1** |
| ③ | `apt_dong` 마스킹 제거(`asof.py:148`) | **2** — 전용 단위 + **`build_cells` 파이프라인**(CR49-6 조치 확인. 전엔 1) |
| ④ | 창 하한 `<` → `<=` (`collect.py:275`) | **1** — 그런데 그게 메모리 검사다(아래 CR50-5) |
| ⑤ | `if window.kind == KIND_START` → `if True` (`collect.py:282`) | **0** (아래 CR50-5) |
| ⑥ | 감시 — `_f2b_order_scan` 의 `_f2b_rule_verdict` 호출을 `harmless` 로 고정 | **5** · rc=1 (SR45-7 순서 탐지 3 + 하위체인 감시불능 2) |

①②③⑥ 은 관문이 살아 있다. ④⑤ 가 이번 라운드의 빈 자리다.

---

## 발견

### CR50-1 (M) — 문서·검사가 단언하는 **"순간 보유 행 ≤ `chunk_rows`" 가 운영 데이터 모양에서는 2배**다

`collect.py:43-44` / `backtest.md §5-1` 표(`순간 보유 행 수 | chunk_rows = 5,000 (≈1.9MB)`) /
`test_backtest.py:1196` `assert counter.peak <= self.CHUNK + 8`.

**픽스처가 마스킹 경로를 한 번도 안 지난다.** `tracked_stream`(`:1166-1173`)이 `apt_dong` ·
`registered_at` 을 안 심으므로 `as_of_trades:150-154` 의 `dataclasses.replace()` 사본이 안 생긴다.
게다가 `LiveTradeCounter` 는 **스트림이 만든 원본에만** `weakref.finalize` 를 걸기 때문에,
사본이 생겨도 **셀 수가 없다**.

내가 잰 값(`gc` 로 살아 있는 `BacktestTrade` 전수 · `chunk_rows=250` · 20,000행):

| 입력 | 살아 있는 행 최대 |
|---|---|
| `apt_dong=None` (지금 픽스처) | **250** = 1× |
| `apt_dong='101'` + `registered_at`=T 이후 (**운영 모양**) | **500** = **2×** |

운영 `apt_dong` 보유율은 **77~93%**(`erd §0` 정정 · `asof.py:118` 이 스스로 인용)이므로
운영 경로가 정확히 후자다. 5,000행 기준 1.9MB → **3.8MB**. 사고는 아니다. 문제는 둘이다:
① 문서의 상한 숫자가 틀렸고, ② **그 상한을 "실측한다"는 검사가 마스킹 축에서 공허**하다 —
CR49-6 이 `apt_dong` 가드에 대해 지적한 사각지대가 **메모리 검사에서 그대로 재발**했다.

**고칠 것**: `tracked_stream` 에 `apt_dong` + `registered_at`(T 이후)를 심고 단언을
`2*CHUNK + 8` 로. 문서 두 곳(`collect.py` 머리주석 · `backtest.md §5-1` 표)을 "마스킹 사본 포함 2×" 로.

### CR50-2 (M) — `chunk_rows` 는 **도메인 객체**의 상한일 뿐이다. DB 드라이버가 시군구 하나치를 통째로 버퍼한다

`run_backtest.py:180-198` 의 `conn.execute(text(_TRADES_SQL), …)` 에 `stream_results` /
`yield_per` 가 없다(저장소 전체 검색 결과 **0건**). SQLAlchemy **2.0.51** + psycopg **3.2.3** 의
기본은 클라이언트 커서라 `execute()` 가 반환되는 시점에 **그 질의의 결과 전체가 클라이언트 메모리**에 있다.
질의는 시군구 단위(`left(c.region_code,:plen)=:region`)이므로 실제 상한은 *"가장 큰 시군구의 행 수"* 이고
**아무도 재지 않았다**.

그런데 `run_backtest.py:344-346` 은 `순간 보유 행 최대 N(상한 M)` 만 찍고, `backtest.md §7-13` 은
*"실행기가 쓸 수 있는 메모리에 상한이 있다 — 순간 보유 행 5,000"* 이라 적는다.
**CR49-3 이 문제 삼은 축(프로세스가 실제로 쥐는 메모리)에는 아직 상한이 없다.**

크기 추정(내 계산 · 미측정): 613,228행 / 거래 있는 시군구 82개 → 평균 ≈7.5천행. 편중을 5%로 잡아도
≈3만행 ≈ **11MB**(383B/행 환산). 235MB 는 확실히 죽었다 — **그래서 차단 사유가 아니다.**
다만 "상한"이라는 말이 아직 참이 아니다.

**고칠 것(한 줄)**: `conn.execution_options(stream_results=True, max_row_buffer=chunk_rows)`.
서버측 커서로 바뀌어도 `statement_timeout=120s` 는 FETCH 마다 따로 걸리므로 가드가 유지된다.
안 고칠 거면 §7-13 에 *"드라이버가 시군구 1개치를 버퍼한다 [미측정]"* 을 한계로 적을 것.

### CR50-3 (M) — **"두 번째 순회에서 조용히 0행" 함정은 아직 가능하다.** 공개 API 짝이 정확히 그 모양이다

`collect.py:36-39` 는 *"그래서 소비자를 '여러 번 훑는 코드'에서 '한 번 훑고 접는 코드'로 바꾸는 것이
수정의 본체다"* 라고 적어 함정이 닫힌 것처럼 읽힌다. 실제로 닫힌 것은 **실행기와 `run_backtest` 뿐**이고,
`build_cells` + `build_outcomes` 는 여전히 같은 `trades` 를 **두 번** 소비한다.

재현(직접 실행):
```python
gen   = iter(trades)
cells = build_cells(gen, spec=SPEC, households=…, min_peer_cells=3)   # 5셀 정상
outs  = build_outcomes(gen, cells, spec=SPEC)                          # ← 소진된 이터레이터
# → measured 0/5 · market_median_pct=None
#   warnings=(no_market_benchmark, no_peer_benchmark, low_coverage, no_null_control)
```
예외 없음. 경고 4개가 뜨긴 하지만 **리포트는 나온다**. 두 함수 모두 `Iterable` 을 받고,
`feed` 독스트링(`collect.py:244`)은 *"⛔ 여기에 `list(trades)` 를 쓰지 마라"* 로 **제너레이터를 권한다**. 검사는 0개다.

같은 계약이 코드로 강제되지 않는 자리 둘 더 (직접 실행):
* `feed` 를 두 번 부르면 **조용히 두 배로 센다** — `rows_seen` 75→150, `price.sample_size` 5→10.
  `window_trade_count` 는 **환금성 축의 분자**다.
* 같은 `FoldSpec` 을 두 번 넘기면 `_window_index` 의 `self._specs.index(spec)`(`collect.py:347`)이
  늘 첫 번째를 돌려줘 뒤쪽 창 3개는 **채워지되 안 읽힌다**(표본만 두 배로 쌓여 `max_samples` 를 먹는다).

운영 두 경로는 안전하다 — **그래서 M 이다.**
**고칠 것(저비용)**: ① `feed` 재진입 가드(두 번째 호출은 예외) ② `build_cells`/`build_outcomes` 타입을
`Sequence` 로 좁히거나 `collector.rows_seen == 0` 이면 멈추기(실행기는 이미 그렇게 한다 — `run_backtest.py:347-349`)
③ 중복 spec 거부. 검사 3개면 셋 다 잡힌다.

### CR50-4 (L) — 저장소의 동치 검사가 **순환**이다

`test_one_pass_over_many_folds_matches_the_per_fold_path`(`:1263`)의 독스트링은
*"…`build_cells`/`build_outcomes` 와 같은 답인가. 같지 않으면 우리가 채점하는 대상이 두 개가 된다"* 인데,
위임 이후 **구현이 하나뿐**이라 그 문장이 성립하지 않는다. 실제로 잡는 것은 창 색인 격리다(그건 가치 있다).
**고칠 것**: 20줄짜리 참조 구현(`as_of_trades` + `price_point`)을 테스트에 오라클로 두면 그 문장이 참이 된다
— 내가 이번에 쓴 것과 같은 형태이고, 그게 있었다면 나는 이 항목을 안 적었다.

### CR50-5 (L) — 변이 ④·⑤: **스트리밍 창 경계**와 `_region` 수집 규칙에 전용 검사가 없다

* **변이 ④**(창 하한 `<` → `<=`)로 죽는 검사는 `test_collector_never_holds_more_than_one_chunk_of_rows`
  **하나**이고, 그것도 `assert collector.samples == self.ROWS` 가 **우연히** 잡은 것이다.
  실패 문구가 *"순간 보유 행이 …"* 라 다음 사람이 엉뚱한 곳을 판다.
  T창과 직전창은 인접하므로(`(start, end]`) 경계를 포함으로 바꾸면 **경계일이 양쪽에서 세어진다** —
  그 실수를 잡는 검사가 없다. (`test_price_point_ignores_trades_outside_the_window`(`:450`)는
  이제 **운영 경로가 쓰지 않는** `price_point` 를 본다.)
* **변이 ⑤**(`if window.kind == KIND_START` → `if True`)로 죽는 검사 **0개**.
  `_region`/`_complex_ids` 를 T창에서만 모으는 규칙(`collect.py:282-285`)은 주석에 근거가 적혀 있는데
  검사가 없다. 옛 경로는 as-of 뷰 **전체**에서 `region_code` 를 골랐다(내 참조 구현 1차판이 그렇게 갈렸다) —
  운영에서는 `complex` JOIN 이라 단지당 하나뿐이어서 차이가 안 나지만, **그 전제가 코드에만 있다.**

### CR50-6 (L) — `…forces_read_only_at_the_database_not_just_in_a_lint` 는 **이름과 달리 여전히 린트**다

`:1317` 은 `SESSION_GUARDS` 상수 튜플의 순서만 본다. DB 도 커넥션도 안 본다.

> **SR45-6 담당자 주장 검증 — 맞다.** PostgreSQL 은 트랜잭션의 읽기전용 여부를 **트랜잭션 시작 시점의**
> `default_transaction_read_only` 로 정한다. 트랜잭션 도중의 `SET default_transaction_read_only = on` 은
> 세션 기본값만 바꾸고 **지금 트랜잭션에는 안 걸린다** → `SET TRANSACTION READ ONLY` 가 첫 줄이어야 한다는
> 지적은 옳고, `run_backtest.py:99-101` 이 그렇게 돼 있다.
> 표현도 확인했다 — `backtest.md §7-14` 가 *"이 항목은 '우발적 쓰기를 막는다'이지 **'차단한다'가 아니다**"* 로 바뀌었다. ✅

⚠️ **그 순서가 통하는 전제가 검사에 없다.** `SET TRANSACTION` 은 트랜잭션 블록 **밖**에서 부르면
경고만 내고 아무 효과가 없다. 지금은 `_common.make_engine`(`:115-118`)이 `isolation_level` 을 안 건드려
psycopg 가 비자동커밋(첫 문장 앞에 BEGIN) 이라 성립한다. 누군가 `AUTOCOMMIT` 으로 바꾸면 가드는
**조용히 무효**가 되고 이 검사는 그대로 초록이다. 한 줄(엔진 `isolation_level` 이 AUTOCOMMIT 이 아님을 단언) 권장.

### CR50-7 (L) — 표본 상한 검사의 단언이 헐겁다

`:1236-1237` `assert collector.samples <= 350` · `rows_seen <= 400`. 손계산 실제값은 **정확히 300 / 300**
(chunk 100 · cap 250 → 3번째 청크에서 멈춘다). 지금 단언은 "청크 두 개마다 검사"로 바꿔도 통과한다.
이 파일의 규칙(*"기대값은 손으로 적는다"*)대로 정확히 박을 것.

### CR50-8 (L) — 감시 문서의 자체검사 실측 줄이 낡았다

`monitoring.md:812` 가 `통과 271 · 실패 0 · 건너뜀 1 · 하네스오류 0`(2026-08-04) 그대로다.
같은 문서 `:719` 의 T6d 표제는 *"(2026-08-04 · **2026-08-05 보강**)"* 이라 적혀 있는데 실측 줄만 안 갱신됐다.
**지금 실측은 290**(내가 서버 격리 사본에서 확인). 한 줄.

### CR50-9 (L) — 낡은 `611,518` — 담당자가 밝힌 것보다 **많고**, `hexagon-report-data.md` 에는 **낡음 표시가 없다**

담당자가 밝힌 2곳 외에 실재하는 곳: `app/agents/scoring.py:15` · `app/domain/valuation/timeadjust.py:7` ·
`docs/02-design/api-spec.md:1171` · `docs/01-discovery/enhancement-research.md:33·153·219` ·
`docs/02-design/ux/hexagon-report-data.md:32·39`.

핵심은 개수가 아니라 **비대칭**이다. `complex-typing.md` 는 CR49-7 조치로 §0 에 낡음/유효 구분표를 얻었는데,
**같은 날 같은 DB 로 잰 형제 문서**인 `hexagon-report-data.md` 는 헤더가 `측정 2026-08-04` 뿐이고
백필 언급이 **한 줄도 없다**. 낡은 값: `trade 611,518`(`:32`) · `apt_dong 84.2%`(`:39`) ·
§0 의 **가격매력 51.7% / 가격추세 50.2%** 커버리지(창 안 표본 수에 직접 걸린다 → 백필로 오른다).
`backtest.md §1` 이 면적대 결정 근거로 이 문서 §2-A 를 인용한다.

그리고 `api-spec.md §4.5` 가 `price_status=="unknown"` 규칙의 근거로 **실측 36.1%** 를 인용하는데,
`complex-typing.md §0` 은 바로 그 값을 ❌**낡음(재측정 필요)** 으로 표시했다 — **두 문서가 어긋난다.**

### 잔가지 (L · 비차단)

* `run_backtest(trades: Sequence[BacktestTrade])`(`engine.py:406`) — 이제 한 번만 순회하므로 `Iterable` 이 맞다.
* `--max-samples -1` → 첫 청크에서 `누적 표본 1개가 상한 -1개를 넘었습니다` 로 죽는다(검증 없음).
  `--chunk-rows 0` 은 `SystemExit` 이 아니라 `ValueError` 트레이스백.
* `summarize` 의 `verdict==measured` & `quotable_folds==0` 조합 허용(CR49 잔가지) — 그대로.
* `analysis.py:255` 의 없는 상수 이름 · `LADDER_POPULATION` 값 미고정(CR49 C 잔가지) — 그대로.
  `character/` 를 이 라운드에 안 건드린 결과라 예상된 것이다.

---

## CR-049 조치 확인표

| CR49 | 조치 | 확인 |
|---|---|---|
| **1** (M) | 없는 jail `rc=0` 거짓 정정 | ✅ `monitor.sh` 주석 2곳 · 픽스처 `exit 255` · `monitoring.md` T6d · `fail2ban.md`. **경보 본문의 거짓도 제거** → *"종료코드는 안 믿는다 — 'Total banned:' 를 실제로 뽑았는지로 판정한다"* |
| **2** (L) | `monitoring.md` 오타 4+1 | ✅ (diff 확인) |
| **3** (M상) | 실행기 일괄 적재 | ✅ **구조로 해결**. 다만 CR50-1·2·3 |
| **4** (M) | payload 에 `params` | ✅ `run_params`(`:249-276`) — `cancellation`·`min_trades`·`min_peer_cells`·`report_lag_days`·`seed`·`null_draws`·`chunk_rows`·`max_samples`. 검사 `:1330` 이 `low != high` 로 두 산출물 구별을 단언. `--dry-run` 로그에도 찍히는 것 확인 |
| **5** (M) | 독스트링 조건부화 | ✅ `asof.py:104-111` · `engine.py:116-120` 둘 다. "해제 축은 §2-D 상·하한으로만 말한다"까지 |
| **6** (L) | `apt_dong` 파이프라인 검사 | ✅ 변이 ③이 **2건**을 죽인다(전엔 1) |
| **7** (M) | `complex-typing.md §0` 구분표 · 사다리 미변경 | ✅ 둘 다. `character/` mtime 이 이 라운드 이전 |
| B 잔가지 | `list(pool)` 루프 밖 · 분모 주석 | ✅ `engine.py:309` · `:194-196` |

## 자기충족 테스트 점검 (요청 4) — 신규 15건

| 표본 | 판정 |
|---|---|
| `test_chunk_size_does_not_change_the_result`(×4) | **건전.** 기대값 `{1000,1200,900,1100,800}` · `picked=(c5,c3)` · `−7.5` 가 `test_fold_metrics_match_hand_calculation` 의 손계산과 같은 값 |
| `test_collector_never_holds_more_than_one_chunk_of_rows` 등 3건 | 절반 건전 — `peak_chunk_rows == CHUNK` 는 정확. `counter.peak <= CHUNK+8` 은 **마스킹 축에서 공허**(CR50-1) |
| `test_collector_refuses_to_swallow_more_samples_than_the_cap` | 건전하나 단언이 헐겁다(CR50-7) |
| `test_default_bounds_are_…` | 의도적 변경감지기(문서 §5-1 계산이 근거) — 정당 |
| `test_one_pass_over_many_folds_matches_the_per_fold_path` | **순환**(CR50-4) |
| `test_runner_never_materialises_the_trade_stream` | 건전 — AST 로 `list(...trades_for_backtest...)` 를 잡는다 |
| `…forces_read_only_at_the_database_not_just_in_a_lint` | 이름 과장(CR50-6) |
| `test_report_payload_says_which_cancellation_policy_made_it` | 건전 — `low != high` 를 직접 단언 |
| `test_apt_dong_masking_is_load_bearing_in_the_build_cells_path` | 건전 — 변이 ③이 실제로 죽인다 |

## 감시(SR-045 조치) 확인 (요청 3)

* **`monitoring.md` 를 두 담당자가 동시에 만졌으나 덮어쓴 흔적·모순 없음** — diff 는 **추가 27줄, 삭제 0**.
  T6d 4칸 · 안 보는 것 2줄 · T6d 자체검사 항목 · 실측 블록. CR49-1 정정이 같은 문단 안에 들어 있어 서로 어긋나지 않는다.
  유일한 낡음은 실측 줄 하나(CR50-8).
* **PM 실수 ①**(픽스처 `exit 255` 후 자체검사 미실행 → T6d 40여 건 HARN) — 해소 확인.
  하네스 관문이 rc 를 막는다(`monitor-selftest.sh:2768` `[ "$FAIL" -eq 0 ] && [ "$HARN" -eq 0 ] && exit 0`),
  그리고 T6d 픽스처 관문(`:1875-1884`)이 **없는 jail rc≠0** 과 **`Banned IP list:` 에 실제 IP 가 나오는지**까지
  확인해서 SR45-4 유출 가드가 공허해지지 않게 했다. 실측 HARN **0**.
* **PM 실수 ②**(`blind_add` 가 거짓 `rc=0` 을 경보 본문으로 실어 보냄) — 해소 확인(위 표 CR49-1).
* `_f2b_bin`(`monitor.sh:91-105`) — `RE_MON_BIN_DIR` → **절대경로 목록** → 마지막에 PATH.
  SR45-5(시험 편의가 root 탐색 순서를 정하던 것) 해소. 자체검사가 *"PATH 앞의 가짜가 이기면 실패"* 로 뒤집혀 있다.
* `_f2b_order_scan` — 변이 ⑥으로 **5검사 사망**. 공허하지 않다.
* IP 가림 — 세 번째 자체검사에서 변이 적용에 실패해 **정적 확인만** 했다:
  검사(`:2075-2082`)가 `203.0.113.7` **부재**와 `<ip>` **존재**를 둘 다 보므로 "가린 척"이 통과할 수 없다.
  (변이 ⑥에서 `(순서) 규칙을 통째로 안 싣는다` 가 죽은 것으로 그 분기에 도달한다는 것까지는 확인됐다.)

## 담당자가 "못 했다"고 밝힌 것 (요청 5) — 전부 실재

* **사전 count 미도입** ✅ `run_backtest.py` 에 `COUNT` 없음. `--dry-run` 은 DB 에 안 닿는다(`:328-331`).
  운영자가 실행 전 규모를 알 방법이 없고 `max_samples` 로만 막는다. `backtest.md §5-1` 안 ④ *"부분 채택"* 과 일치 → **기록만**.
* **`max_samples` 200만은 계산값** ✅ `collect.py:48-52`. 문서가 계산임을 밝히므로 지적 아님.
  단 "약 55MB" 는 **값 통만**의 숫자다(CR50-1·2 를 감안하면 프로세스 총량이 아니다).
* **낡은 `611,518`** ✅ → CR50-9.

---

## 판정 — **pass** (High 0)

| ID | 심각도 | 요지 |
|---|---|---|
| CR50-1 | **M** | "순간 보유 행 ≤ chunk_rows" 가 운영 모양(동 마스킹)에서 **2배**. 그걸 재는 검사가 그 축에서 공허(픽스처가 `apt_dong` 을 안 심고, 카운터가 `replace()` 사본을 못 센다) |
| CR50-2 | **M** | `chunk_rows` 는 도메인 객체 상한일 뿐 — psycopg 클라이언트 커서가 **시군구 1개치를 통째로 버퍼**한다(`stream_results` 0건 · 미측정). 235MB 는 죽었으므로 비차단 |
| CR50-3 | **M** | "두 번째 순회에 조용히 0행" 함정이 `build_cells`+`build_outcomes` 짝에 **그대로 살아 있다**(재현함 · 예외 없음). `feed` 재호출·중복 spec 도 조용히 두 배 |
| CR50-4 | L | 저장소의 동치 검사가 순환(위임 이후 구현이 하나) |
| CR50-5 | L | 스트리밍 **창 경계**·`_region` 수집 규칙에 전용 검사 없음(변이 ④가 1건을 우연히, ⑤가 0건) |
| CR50-6 | L | 읽기전용 검사가 이름과 달리 린트. **SR45-6 주장 자체는 옳다(검증함)** · 표현도 "우발적 쓰기를 막는다"로 바뀜 |
| CR50-7 | L | 표본 상한 단언이 헐겁다(실제 300/300인데 350/400) |
| CR50-8 | L | `monitoring.md:812` 자체검사 실측 271 → 지금 **290** |
| CR50-9 | L | 낡은 `611,518` 8곳. `hexagon-report-data.md` 에는 낡음 표시가 **없다**(형제 문서와 비대칭) · `api-spec §4.5` 의 36.1% 와 `complex-typing §0` 이 어긋남 |
| — | L | 잔가지 4 |

**pass 근거**
* **정확성 결함 없음** — 리팩터 동치성을 독립 참조 구현으로 **960회 비교, 불일치 0** 으로 직접 확인했다.
  CR50-3 의 함정은 **운영 두 경로(실행기·`run_backtest`)에 존재하지 않는다**(코드 확인 + 실행기 가드 `:347-349`).
* **보안 냄새 없음** — 산출 JSON·로그·요약에 개인 정보 없음(검사가 단언) · SQL 전부 파라미터 바인딩 ·
  세션이 읽기 전용(`SET TRANSACTION READ ONLY` 가 첫 줄인 것을 확인) · 감시 알림에 IP 없음(가드 존재).
* **핵심 로직 테스트 있음** — 변이 6종 중 4종이 죽는다. 죽지 않은 2종(④⑤)은 **CR50-5 로 명시**했고,
  ④는 우연히라도 잡히며 ⑤는 운영에서 값을 바꾸지 않는다.
* **레이어 위반 없음** — `test_backtest_domain_contains_no_sql_or_engine` 이 `*.py` 글롭이라 신규 `collect.py` 도
  자동 포함(8파일). 도메인에 SQL·엔진 import 0. `ruff` 통과.

**다음 커밋 전 처리 권고(전부 저비용)**: CR50-1(픽스처 2줄 + 문서 2곳) · CR50-8(한 줄) · CR50-9(헤더 한 줄).
**첫 백테스트 실행 전 권고**: CR50-2(한 줄) — 안 고칠 거면 §7-13 에 한계로 적을 것.
**배선 전 필수(CR-049 유지)**: `complex-typing.md §4` 재측정.
CR50-3 은 다음 라운드에 검사 3개로 닫으면 된다 — 지금 도는 경로에는 없다.

---

## CR-051 · 2026-08-05 · `CR-050` 비차단 7건(CR50-1·2·3·6·7·8·9) 조치 재검증 + 감시 v6 편입(`check_v6ssh`) — 커밋 전

**범위**

| | 대상 |
|---|---|
| A | `backend/app/domain/backtest/collect.py`(381→**525줄** · `assert_rereadable` · `StreamAlreadyConsumed` · `_CLAIMED` · `peak_live_rows` 신설) · `asof.py` · `engine.py` · `scripts/run_backtest.py`(`apply_session_guards` · `stream_results`) · `tests/test_backtest.py`(**+10검사** · `_TrackedTrade` · `TestSecondPassTrap`) · `docs/02-design/backtest.md` §5-1·§7-13-B·§7-14-B |
| B | `deploy/monitor.sh`(7e 구획 · `_v6_rule_is_drop` · `_v6_scan` · `check_v6ssh`) · `deploy/monitor-selftest.sh`(T6e **+51검사**) · `docs/05-monitoring/monitoring.md` |
| C | `docs/02-design/ux/hexagon-report-data.md`(§0 낡음/유효 구분표 신설) · `api-spec.md` §4.5 |
| — | `app/domain/character/**` 는 이 라운드 **미변경**(mtime 08-04 13:46 — 이전 라운드). `frontend/**` 무접촉 |

**동결 해시 — 시작·종료·서버 격리사본 3중 일치(2/2)**
```
27d75faed4b8a08f43e2a9a7b6e2a199fa6ccdd2880abf6d433123d0fd94c7c5  deploy/monitor.sh
a9e661702993088747df63ab4125e297b225b9ec377f98679d1a9407e795e8b2  deploy/monitor-selftest.sh
```
`git status` 시작=종료(동일). **저장소 파일은 한 글자도 안 고쳤다** — 변이는 서버 격리 사본에만
넣고(scp 로 덮어쓴 뒤 원본을 다시 scp) sha256 으로 원복 확인. `/opt/realestate/scripts/**` 무접촉 ·
텔레그램 발화 0(`RE_MON_DRY_RUN=1`) · 서버 방화벽·유닛 **변경 0**(읽기만) · 격리 `/root/rev51/`
(종료 시 삭제) · **백테스트 미실행** · 윈도우에서 `monitor-selftest.sh` 실행 0회.

### 기준값 재현 — 전부 내가 직접 실행

| 항목 | PM 기준값 | 내 실측 | |
|---|---|---|---|
| 서버 격리 자체검사(`/root/rev51/{deploy,docs}` — 트리 유지) | 341 / 0 / 1 / HARN 0 / rc=0 | **341 / 0 / 1 / HARN 0 / rc=0** | 일치 |
| 백엔드 `pytest` 전량 | 1,626 passed · 103 skipped | **1,626 passed · 103 skipped · 0 failed · rc=0** | 일치 |
| `MUT-` 잔여 | 0건 | **0건**(저장소 전체 `grep -rn "MUT-"` — `*.sh`·`*.py`·`*.md`) | 일치 |
| `ruff check`(backtest · runner · tests) | — | All checks passed | — |

---

## ★ 요청 1 — CR50-1 의 계수가 **이제 정말 전수인가**

**결론: 그렇다.** 저장소 코드에 손대지 않고 `gc` 로 독립 계수했다
(`collect.as_of_trades` 를 런타임에 감싸 뷰 생성 직후 살아 있는 `BacktestTrade` 를 전수 세기 ·
20,000행 · `chunk_rows=250` · 160회 표집):

| 청크의 모양 | `gc` 실측 최대 살아있는 행 | `collector.peak_live_rows` | |
|---|---:|---:|---|
| **운영 모양**(`apt_dong='101'` · 미등기) | **501** | **500** | 일치(+1은 제너레이터 프레임이 쥔 한 행) |
| `apt_dong=None` | 250 | 500 | 코드가 **위로** 잡는다 |

두 번째 줄은 결함이 아니다 — `peak_live_rows` 독스트링(`collect.py:331-334`)이 *"정확히 말하면
**자리 수**이지 서로 다른 객체 수가 아니다 … 위로 잡은 상한"* 이라고 먼저 적어 두었다.
**운영 모양에서는 그 상한이 곧 실제값**이라는 주장도 위 표대로 참이다.

**다른 사본 생성 경로는 없다.** `BacktestTrade` 를 새로 만드는 자리는 `asof.py:153`
`replace(...)` **하나뿐**이고(패키지 전체 확인), `collect.py:522` 의 `replace` 는 `AsOfCell`
이며 행이 아니다. `attach_peer_medians` 는 행을 안 쥔다. 뷰는 `view.clear()`(`:423`)로
반복마다 끊기므로 뷰 둘이 동시에 살지 않는다 — `gc` 계수가 그것을 확인한다(최대 501).

**바이트 실측도 재현된다.** 문서 §5-1 이 *"3.8MB 라고 쓰려다 실제로 쟀다"* 며 올린 표를
내가 다시 쟀다(`tracemalloc` · 5,000행 청크 · 뷰 생성 증가분):

| 청크의 모양 | 문서 값 | 내 실측 | |
|---|---:|---:|---|
| **운영 모양** | **181 B/행** | **181 B/행** | 정확히 일치 |
| `apt_dong=None` | 44 B/행 | 57 B/행 | 같은 자리(목록 슬롯 · 과할당 차이) |

→ *"행 수는 2배지만 바이트는 2배가 아니다"* 는 **맞다**. 문서 두 곳(`collect.py:53-70` ·
`backtest.md §5-1`)과 로그(`run_backtest.py:404-408` — `순간 보유 행 최대 N[청크 C + 뷰]`)와
검사(`test_backtest.py:1265` `peak_live_rows == 2*CHUNK` **등호**)가 전부 같은 숫자를 말한다.
픽스처도 고쳤다 — `STREAM_APT_DONG='101'` · `STREAM_REGISTERED_AT=2030-01-01`(`:1219-1223`)에
`counter.copies > 0` **공허 방지 단언**이 붙었다. CR50-1 **해소**.

## ★ 요청 2 — CR50-3 가드가 **정상 경로를 막지 않는가**

**막지 않는다. 그리고 막아야 하는 것은 다섯 형 전부 막는다.** 직접 실행:

| 넘긴 것 | `build_cells` / `build_outcomes` |
|---|---|
| `list` · `tuple` · `dict_values` · `set` | **전부 통과**(cells·outcomes 정상 산출) |
| `list_iterator` · `generator` · `map` · `chain` · `filter` | **전부 `TypeError`** |

담당자가 밝힌 **약한 참조 한계**(`_CLAIMED` 주석 `:168-172` — `list_iterator`·`map`·`chain` 은
`WeakSet` 불가)가 공개 API 에서 실제로 `assert_rereadable` 로 막힌다는 것을 이 표가 보인다.
판정 근거도 표준 규약 하나(`iter(x) is x`)라 형 목록을 늘려 따라잡을 필요가 없다. 잔여 구멍은
CR51-4 에 적었다(직접 `FoldCollector` 를 쓸 때만 · 문서화돼 있다).

## ★ 요청 3 — 감시 v6 편입: 51건이 서로를 가리지 않는가 · clear 를 행동으로 보는가

**변이 3종을 한 번에 넣고 서버 격리 사본에서 1회 실행** — 죽은 검사가 **정확히 자기 무리만**이다.

| 변이 | 죽은 검사 | 무리 |
|---|---:|---|
| ① `_v6_scan` 의 `verdict=$(_f2b_rule_verdict …)` → `harmless`(앞 순서 판정 무력화) | **5** | (순서) 3 · (순서 fail-open) 2 |
| ② `check_v6ssh` 의 `elif [ -n "$act" ]` → `elif false`(유닛 부재 판정 제거) | **3** | (유닛 삭제) 3 |
| ③ `_v6_rule_is_drop` 의 `-s` 거부 제거 | **2** | (가짜 DROP) 1 · (v6 규칙 판정표) 1 |
| 합 | **10 · rc=1** | 서로 겹치지 않는다 |

→ **서로를 가리지 않는다.** 남은 41건은 이 변이들에 무반응이므로 다른 축을 본다는 뜻이고,
①이 (대조군)·(순서 대조군)을 **안** 죽인 것이 오탐 축이 따로 서 있다는 증거다.

**clear 경로를 행동으로 본다.** 이 저장소가 다섯 번 놓친 계열(CR40·42-3·43-1·44-2·47-2)을
T6e 가 두 방향으로 본다 — ⓐ 해소: `ALERT-CLEARED` **와** `alerts/*.active` **파일 삭제**를
둘 다 확인((다) 규칙 해소 · (카) 유닛 해소), ⓑ 거짓 해소 금지: 눈이 먼 상태로 들어가기 전에
`.active`·`.sent` 를 **미리 심어 두고**(`:2456`·`:2476`·`:2527`) `ALERT-CLEARED` 부재 **와**
`.active` 생존을 확인((아) ip6tables 없음 · (자) 실행 실패 · (파) systemd 불가).
빈 상태로 돌리면 `clear_alert` 가 조용히 지나가 아무것도 못 본다는 것을 알고 짠 구조다.

**하네스 관문이 있다.** `V6OK`(`:2323-2334`)가 가짜 `systemctl`·`ip6tables` 가 실측 모양대로
답하는지(없는 유닛 `is-enabled` = **빈 출력 + rc≠0**, 정상 출력에 **f2b-sshd 점프 포함**)
먼저 확인하고, 어긋나면 시나리오 전체를 `harn` 으로 돌린다 → 가짜가 관대해져 검사가
공허해지는 길이 막혔다. 실측 HARN **0**.

**실측 근거 3건 검증**

1. **`oneshot`+`RemainAfterExit` 는 규칙을 지워도 `active`** — 서버 유닛 파일을 읽어 확인:
   `Type=oneshot` · `RemainAfterExit=yes` · `ExecStart=/bin/sh -c "…ip6tables -C … || …-I INPUT 1 -p tcp --dport 22 -j DROP"`.
   `ExecStop` 이 없으므로 stop 해도 규칙이 안 걷힌다는 설명도 파일과 일치한다. **맞다.**
   그래서 ②의 기준을 `is-enabled` 로 둔 판단이 옳고, 요약이 `is-active` 를 *"보호의 증거는
   아니다"* 로 못박은 것도 옳다(대조군 검사가 그 문구를 직접 본다 · `:2361`).
2. **유닛 삭제와 systemd 불가가 `is-enabled` 에서 같은 모양** → `is-active` 로 가른 것: 픽스처가
   그 두 모양을 각각 세우고((타) `FAKE_V6_ENABLED= FAKE_V6_ACTIVE=inactive` / (파) 둘 다 빈 출력),
   전자는 **경보** · 후자는 **감시불능**으로 갈린다. 변이 ②로 3건이 죽는다 → 공허하지 않다. **맞다.**
3. **`_f2b_order_scan` 재사용을 버린 판단** — **맞다(직접 확인).** 그 함수는
   `case "$line" in *" -j $2"|*" -j $2 "*) break ;;`(`monitor.sh:1246`)이라 `$2=DROP` 이면
   **INPUT 의 첫 DROP 줄**에서 멈춘다. 예: `-A INPUT -p tcp --dport 3306 -j DROP` 이 위에 있으면
   그 뒤의 `--dport 22 -j ACCEPT` 를 **못 보고 "앞이 깨끗하다"** 고 답한다. 지금 `_v6_scan` 은
   루프만 따로 쓰고 줄 판정은 `_f2b_rule_verdict` 를 그대로 재사용해 이 함정을 피한다.
   ⚠️ 다만 **그 판단을 지키는 픽스처가 없다** → CR51-2.

**서버 현재 상태를 읽어 픽스처와 대조**(읽기 전용):
`ip6tables -S INPUT` = `-P INPUT ACCEPT` / `--dport 22 -j DROP` / `multiport --dports 22 -j f2b-sshd`
→ `ip6-ok.txt` 와 **한 글자도 다르지 않다**. *"가짜가 현실보다 관대하면 검사가 공허하다"* 는
주석이 지켜졌다. `/usr/sbin/ip6tables` 는 `/etc/alternatives` 심링크이고 유닛의 `ExecStart` 도
같은 경로를 쓰므로 legacy/nft 백엔드가 갈릴 여지도 없다(레거시 바이너리는 존재하나 미사용).

## ★ 요청 4 — 자기충족 테스트 점검 (신규 표본)

**백엔드 +10건**(1,616→1,626) — `TestSecondPassTrap` 7 + `test_read_only_guard_checks_its_own_premise…`
+ `test_runner_streams_trades_from_the_database…` + `test_stream_buffer_follows_chunk_rows…`

| 표본 | 판정 |
|---|---|
| `test_collector_never_holds_more_than_two_chunks_of_rows` | **건전.** `peak_live_rows == 2*CHUNK` **등호** · `counter.copies > 0` 공허 방지 · 내 `gc` 전수(501)와 일치 |
| `test_a_list_is_still_accepted_twice` | **건전 · 필수.** 가드가 정상 경로를 막지 않는 것을 직접 단언(내 실측표와 같은 결론) |
| `TestSecondPassTrap` 나머지 6 | **건전.** 리뷰어가 재현했던 그 코드가 그대로 검사가 됐다. `feed` 두 번 · 제너레이터 공유 · 중복 spec · `feed` 없이 산출 — 넷 다 예외를 단언하고, 두 번째는 `rows_seen`·`samples` 가 **안 늘었음**까지 본다 |
| `test_read_only_guard_checks_its_own_premise_and_refuses_autocommit` | **건전.** 가짜 연결로 ① 정상 순서 ② AUTOCOMMIT 거부(**가드를 걸어 보지도 않는다**를 `auto.statements == []` 로) ③ `SHOW` 가 `off` 면 정지 — 셋 다 본다. CR50-6 의 *"이름과 달리 린트"* 가 실제로 닫혔다 |
| `test_runner_streams_trades_from_the_database…` | **건전.** `exec_options == [{"stream_results": True, "max_row_buffer": 250}]` 를 **정확히** 단언 |
| `test_stream_buffer_follows_chunk_rows…` | 절반은 소스 문자열 검사(`"stream_rows=chunk_rows" in source`)라 약하지만, 기본값 쪽은 실제 객체를 본다 — 허용 |
| `test_collector_refuses_to_swallow_more_samples_than_the_cap` | **건전해졌다.** `<= 350/400` → **`== 300` / `== 300`**(손계산 근거 주석 포함). CR50-7 해소 |
| `test_one_pass_over_many_folds_matches_the_per_fold_path` | **여전히 순환**(CR50-4 · 이 라운드 범위 밖) |

**T6e +51건** — 위 변이 3종이 각각 자기 무리만 죽인다(합 10). 대조군 2무리((가)·(마))가
따로 서서 오탐 축을 지킨다. 함수 단위 판정표(`_v6_rule_is_drop` 12케이스)가 시나리오로 못 덮는
경계를 메우고, 구조 검사 2건(`--fast`/`--daily` 가 `check_v6ssh` 를 실제로 부르는가)이
"호출을 통째로 지우는" 변이를 막는다. **공허한 표본 없음.**

## ★ 요청 5 — 담당자가 밝힌 "못 잡는 것" 의 정직성

**정직하다. 과소도 과대도 거의 없다.**

* **CR50-2(드라이버 버퍼)** — `stream_results` 를 **켰고**(`run_backtest.py:236-238`), 그러고도
  `backtest.md §7-13-B` 를 세워 *"운영 DB 로 확인했는가 → **아니다**"* · *"5,000행이 드라이버 쪽에서
  몇 바이트인가 → **[미측정]**"* · *"postgres 쪽 커서 비용 → **[미측정]**"* · *"첫 실행 때 할 일"* 까지
  적었다. 옛 추정치 11MB 도 **"이 값은 [미측정] — 리뷰어 추정이고 나도 재지 않았다"** 로 표시했다.
  **그 정직성이 유지된다.**
* **감시 "못 잡는 것" 4줄**(`monitor.sh:1497-1506`) — v6 대입 자체 미계수 · 하위 체인 안 · sshd 가
  v6 를 정말 듣는지 · 다른 v6 포트. 넷 다 코드와 대조해 **실재**한다. 누락 1건은 CR51-3.
* **`hexagon-report-data.md`** — 형제 문서와의 비대칭이 해소됐고, 담당자가 리뷰어와 **판단이 갈린
  곳을 숨기지 않고 "확인 대상"으로** 남겼다(CR51-6 에서 담당자 손을 들어 준다).

---

## 발견

### CR51-1 (M) — 상한에 걸려 **멈춘** 수집기가 그 뒤 **부분 결과를 조용히 내놓는다**

`feed`(`collect.py:379`)가 `self._fed = True` 를 **소비 전에** 세운다. `_feed_chunk` 가
`SampleLimitExceeded`(`:425`)로 죽어도 그 값은 True 로 남고, `_require_fed`(`:481-484`)는
"`feed` 를 불렀는가"만 보므로 통과시킨다. 재현(직접 실행 · `test_backtest.py` 픽스처
`universe_trades()` 75행 · 정상은 5셀 · 셀당 창 안 거래 5건):

```python
col = FoldCollector([SPEC], min_peer_cells=3, chunk_rows=10, max_samples=40)
try: col.feed(trades)
except SampleLimitExceeded: pass          # ← 다음 사람이 여기서 넘어간다
col.cells(SPEC, households=HOUSEHOLDS)    # → **3셀** · window_trade_count 전부 5 · 예외/경고 없음
```

| `max_samples` | 나오는 것 | 정상 |
|---|---|---|
| 40 | 셀 **3개**(중위 900·1000·1200) · outcomes **3/3 measured** | 셀 5개(800~1200) |
| 60 | 셀 5개 · outcomes **4/5 measured** | 5/5 |

**겉으로 멀쩡하다** — 유니버스가 작고 커버리지가 낮은 것이 "데이터가 그렇다"로 읽힌다.
운영 실행기는 예외를 전파해 죽으므로(`run_backtest.py:401` 위로 아무도 안 잡는다) **지금 도는
경로에는 없다 → M.** 그러나 이 라운드가 CR50-3 에 대해 스스로 세운 기준이 그대로 적용되는
자리다 — `collect.py:41` *"「운영 경로엔 없다」는 대책이 아니다 — 다음 사람이 그 경로를 만든다"*.
게다가 `_require_fed` 가 존재하는 이유(*"빈 유니버스를 지어내지 않는다"*)와 **같은 실패 모양**이고,
`SampleLimitExceeded` 문구가 *"폴드를 나눠 돌리거나 --max-samples 로 상한을 올리세요"* 라
**폴드별로 감싸 돌리는 코드**를 유도한다.

**고칠 것(저비용)**: `_feed_chunk` 의 raise 직전(또는 `feed` 를 `try/except`로 감싸)
`self._aborted = True` 를 세우고 `_require_fed` 가 그때도 거부. 검사 1개면 잡힌다.

### CR51-2 (L) — `_f2b_order_scan` 을 버린 판단은 **옳은데**, 그 판단을 지키는 픽스처가 없다

`_v6_scan` 주석(`monitor.sh:1541-1549`)이 재사용을 버린 이유를 정확히 적었고 나는 그것이
맞다고 확인했다(요청 3-③). 문제는 **그 오답을 드러내는 입력이 T6e 에 없다**는 것이다.
`ip6-shadow.txt`(`:1911-1917`)는 `lo ACCEPT` → `ESTABLISHED ACCEPT` → `-s … --dport 22 ACCEPT`
→ 우리 DROP 순서라, **우리 DROP 앞에 다른 DROP 이 하나도 없다.** 그래서 누군가 주석을 무시하고
`_v6_scan` 을 `_f2b_order_scan "$out" DROP "$V6_PORT"` 재사용으로 "정리"해도 **51건이 전부 초록**이다
(그 판은 `-A INPUT -p tcp --dport 3306 -j DROP` 한 줄만 위에 있으면 뒤의 22번 ACCEPT 를 못 본다).

**고칠 것(한 줄)**: `ip6-shadow.txt` 맨 앞(정책 다음)에
`-A INPUT -p tcp -m tcp --dport 3306 -j DROP` 를 넣는다. 지금 코드는 그것을 `harmless` 로 보고
계속 훑으므로 결과가 안 바뀌고(`(순서)` 3건 그대로 통과), 재사용판은 그 줄에서 멈춰 죽는다.

### CR51-3 (L) — ②(재부팅 복구)는 유닛의 **이름과 enabled 상태만** 본다 · 그 한계가 목록에 없다

`check_v6ssh` 는 `is-enabled`/`is-active` 만 묻는다(`:1584-1585`). 유닛의 `ExecStart` 가 실제로
`tcp/${V6_PORT}` 를 DROP 하는지는 **안 본다.** 누가 유닛 내용을 바꾸거나 포트를 달리 적으면
`enabled` 인 채로 초록이고, 재부팅에 v6 22번이 열린다. 머리말은 `is-active` 에 대해서는
*"보호의 증거가 **아니다**"* 라고 못박아 놓고(`:1467-1473`), `is-enabled` 에 대해서는
*"재부팅 복구를 **보장**하는 것은 `is-enabled`"* 라고 적었다 — 같은 논법을 한쪽에만 적용했다.
그리고 *"이 검사가 못 잡는 것"* 4줄(`:1497-1506`)에 이 항목이 **없다**.

서버 실측으로 **지금 유닛은 올바르다**(`ExecStart` 가 `--dport 22 -j DROP`) → 사고가 아니라
목록의 누락이다. **고칠 것**: "못 잡는 것"에 한 줄 추가(가장 싸다). 굳이 닫으려면
`systemctl cat "$V6_UNIT"` 에서 `--dport ${V6_PORT}` 와 `DROP` 을 함께 확인하는 한 줄.

### CR51-4 (L) — `_CLAIMED` 의 약한 참조 구멍은 **문서대로 실재**한다(공개 API 는 안전)

직접 실행 — 같은 원천을 수집기 둘에 넘겼을 때:

| 원천 | 두 번째 `feed` |
|---|---|
| `generator` | **`StreamAlreadyConsumed`** ✅ |
| `map` · `chain` · `list_iterator` | **조용히 통과 · `rows_seen=0` · `cells()` 0개** ⚠️ |

`_CLAIMED` 주석(`:168-172`)이 이 한계를 먼저 밝혔고, 공개 API(`build_cells`/`build_outcomes`)는
`assert_rereadable` 이 다섯 형을 전부 막으며, 운영 원천은 제너레이터라 걸린다 — **그래서 L**이다.
다만 *"지금은 네 자리가 예외로 죽는다"* 표(`:44-49`)의 세 번째 줄은 괄호로 조건을 달았어도
표 제목이 단정형이라 조금 세게 읽힌다. **고칠 것(선택)**: 약한 참조가 안 걸리는 원천이면
`id()` 를 강한 참조와 함께 작은 목록에 남기거나, 최소한 그때 `log`/주석 한 줄.

### CR51-5 (L) — CR50-9 는 **절반만** 닫혔다. `api-spec §4.5` 의 어긋남은 **그대로**다

닫힌 것: `hexagon-report-data.md` 가 §0 구분표(❌낡음 / ✅유효 / ⚠️확인 필요)를 얻었고
`§1` 표의 해당 칸에도 ❌ 표시가 붙었다(`:53`·`:60`). **형제 문서 비대칭 해소 ✅** — 이게 핵심이었다.

안 닫힌 것:
* 낡은 `611,518` 이 **표시 없이** 5곳에 남아 있다 — `app/agents/scoring.py:15` ·
  `app/domain/valuation/timeadjust.py:7` · `deploy/DEPLOY.md:342` ·
  `docs/01-discovery/enhancement-research.md:33·153·219` · `docs/02-design/api-spec.md:1171`.
* **CR50-9 가 이름까지 짚은 어긋남이 남았다**: `api-spec.md:679`(§4.5)가 `price_status=="unknown"`
  규칙의 근거로 **실측 36.1%** 를 낡음 표시 **없이** 인용하는데, `complex-typing.md:31` 은 같은
  값을 ❌**낡음(재측정 필요) · "거의 확실히 줄어든다"** 로 적었다. 같은 절의 `901개(5.5%)` ·
  `2,775개(16.9%)` 도 같은 날(08-04) 같은 DB 값이다. §4.5 는 *"아직 응답에 실리지 않는다"* 를
  머리에 달아 두었으므로 **한 줄만 더**(⚠️ 수치는 백필 전 08-04 실측 · 배선 전 재측정) 붙이면 된다.

### CR51-6 (확인 · 정정) — CR50-9 의 "백필로 오른다"는 **리뷰어(CR-050)가 틀렸다**. 담당자가 맞다

PM 판정을 내가 운영 DB 에서 **직접 세어** 확인했다(읽기 전용 · `SET default_transaction_read_only=on`):

| | 값 |
|---|---:|
| `trade` 총계 | **1,076,262** |
| `contract_date >= 2024-01-01` | **611,518** |
| 그 이전 | 464,744 |
| 계약일 범위 | **2021-01-01 ~ 2026-07-25** |

**2024+ 부분합이 백필 전 총계(611,518)와 정확히 일치**한다 → 백필은 2021~2023 만 넣었고
**2024+ 는 한 건도 안 늘었다**. (적재기가 upsert 전용이라 "같은 수만큼 지우고 다시 넣었다"는
경우는 실질적으로 배제된다.) `hexagon-report-data.md` 가 정의한 창은 전부 2024-07 이후이므로
**가격매력 51.7% · 가격추세 50.2% 는 영향 없음** — ⚠️확인 필요 → ✅유효 로 옮길 근거가 섰다.
**고칠 것**: 그 줄을 ✅ 로 옮기고 근거(`2024+ 부분합 = 611,518 = 백필 전 총계`)를 한 줄 적을 것.

⚠️ **같은 표의 다른 ⚠️ 줄은 아직 열려 있다.** `market_price_index` 를 같이 쟀다 —
**2,381행 · 2024-01 ~ 2026-07**(문서 값 2,288행). **과거 달이 안 늘었다**(min 이 2024-01 그대로)
→ 백필 구간으로 **재생성되지 않았다**. 행 수만 +93 늘었다(최근 달 추가로 보인다).
그 줄은 ⚠️ 로 유지하되 이 실측을 적어 두면 다음 사람이 다시 안 잰다.

### CR51-7 (L · 확인만) — CR50-4·CR50-5 는 이 라운드 범위 밖이라 그대로다

* `test_one_pass_over_many_folds_matches_the_per_fold_path`(`:1345`)는 여전히 **순환**이다
  (`build_cells`/`build_outcomes` 가 `FoldCollector` 에 위임하므로 같은 구현끼리 비교).
* 스트리밍 **창 경계**(`collect.py:412` `(start, end]`)와 `_region`/`_complex_ids` 를 T창에서만
  모으는 규칙(`:419-422`)에 **전용 검사가 없다**(테스트 전체 검색 — 경계 검사는 면적대와 청크 경계뿐).

### 잔가지 (L · 비차단)

* `--max-samples -1` → 첫 청크에서 `누적 표본 1개가 상한 -1개를 넘었습니다` 로 죽는다(검증 없음) ·
  `--chunk-rows 0` 은 `SystemExit` 이 아니라 `ValueError` 트레이스백 — **CR50 그대로**.
* `run_backtest(trades: Sequence[BacktestTrade])`(`engine.py:416`) — 한 번만 순회하므로
  `Iterable` 이 맞다. **CR50 그대로**.
* `collect.py:76` *"그래도 남는 몫은 §7-13 에 **숫자로** 적었다"* — §7-13-B 의 그 숫자는
  **[미측정] 추정**이다(본문은 정직하다). 머리주석 쪽 표현만 살짝 세다.
* `summarize` 의 `verdict==measured` & `quotable_folds==0` 조합 허용 · `analysis.py` 의
  `LADDER_POPULATION` 값 미고정 — `character/` 미변경이라 예상된 잔존.

---

## CR-050 조치 확인표

| CR50 | 조치 | 확인 |
|---|---|---|
| **1** (M) | 순간 보유 상한 2배 정정 + 계수 전수화 | ✅ **해소.** `_TrackedTrade` 하위형이 `replace()` 사본까지 센다 · 픽스처가 마스킹을 지난다(`copies > 0` 단언) · `peak_live_rows`(청크+뷰) 신설 · 상한 `2 × chunk_rows` · 문서 2곳 정정. 내 `gc` 전수(운영 모양 **501** vs `peak_live_rows` 500)와 `tracemalloc`(**181 B/행**)이 모두 일치 |
| **2** (M) | `stream_results` | ✅ **켰다**(`run_backtest.py:236-238` · `max_row_buffer=chunk_rows` · `stream_rows=chunk_rows` 로 상한 하나). 운영 DB 미확인분은 §7-13-B 에 **[미측정] 3칸 + 첫 실행 때 할 일**로 세워 정직성 유지 |
| **3** (M) | 두 번째 순회 함정 | ✅ **구조로 닫았다.** `assert_rereadable`(다섯 형 전부 `TypeError` — 직접 확인) · `StreamAlreadyConsumed`(feed 재호출 · 제너레이터 공유) · 중복 `FoldSpec` `ValueError` · `_require_fed`. 리스트·튜플·`dict_values`·`set` 은 통과(직접 확인). 남은 구멍은 CR51-4, 새 구멍은 CR51-1 |
| **4** (L) | 순환 동치검사 | ⬜ 범위 밖 — 그대로(CR51-7) |
| **5** (L) | 창 경계·`_region` 전용 검사 | ⬜ 범위 밖 — 그대로(CR51-7) |
| **6** (L) | 읽기전용을 효과로 | ✅ **해소.** `apply_session_guards` 가 ① AUTOCOMMIT **거부**(가드를 걸어 보지도 않는다) ② `SHOW transaction_read_only` 로 되묻고 `on` 아니면 정지. 검사가 셋 다 본다. §7-14-B 신설 |
| **7** (L) | 표본 상한 단언 | ✅ `== 300` / `== 300` + 손계산 주석 |
| **8** (L) | `monitoring.md` 실측 줄 | ✅ `:846` **341 · 0 · 1 · HARN 0 · rc=0**(직전 290) + 변이 3종 사망 수 기록. 내 실측과 일치 |
| **9** (L) | 낡은 611,518 · 문서 비대칭 | ⚠️ **절반**(CR51-5) — 핵심(형제 문서 비대칭)은 해소, 5곳 표시 없음 + `api-spec §4.5` 36.1% 어긋남 잔존. 판단 갈린 곳은 CR51-6 에서 담당자 손을 들어 준다 |
| **B** | 감시 v6 편입 | ✅ 변이 3종이 각각 자기 무리만 죽인다(5·3·2) · clear 를 통보+`.active` 삭제로 본다 · fail-open 3종이 `.active` 생존을 본다 · 하네스 관문 있음 · 실측 근거 3건 전부 확인. 남은 것은 CR51-2·CR51-3(둘 다 L) |

---

## 판정 — **pass** (High 0)

| ID | 심각도 | 요지 |
|---|---|---|
| CR51-1 | **M** | 상한에 걸려 멈춘 수집기가 그 뒤 **부분 결과를 조용히** 낸다(재현: 5셀 → 3셀 · 예외/경고 0). 운영 경로엔 없으나 CR50-3 이 세운 기준과 `_require_fed` 의 존재 이유에 정면으로 걸린다 |
| CR51-2 | L | `_f2b_order_scan` 재사용을 버린 판단은 **옳은데**(확인함) 그것을 지키는 픽스처가 없다 — 재사용으로 "정리"해도 51건이 초록. 픽스처 한 줄이면 닫힌다 |
| CR51-3 | L | ②는 유닛의 **이름과 enabled 만** 본다(내용 미확인). `is-active` 에는 "증거 아님"을 못박고 `is-enabled` 에는 "보장"이라 적었다 · "못 잡는 것" 목록에 누락 |
| CR51-4 | L | `_CLAIMED` 약한참조 구멍 실재(`map`·`chain`·`list_iterator` 공유 시 조용히 0행) — 문서화돼 있고 공개 API 는 `assert_rereadable` 로 안전 |
| CR51-5 | L | CR50-9 절반만 — 낡은 `611,518` 5곳 표시 없음 · `api-spec §4.5` 36.1% 와 `complex-typing §0` 어긋남 잔존 |
| CR51-6 | 확인 | **담당자가 맞다.** 운영 DB 직접 계수: 총 1,076,262 · 2024+ **611,518**(= 백필 전 총계) · 2021-01-01~ → 가격 2축 커버리지 **영향 없음**. ⚠️→✅ 로 옮기고 근거를 적을 것. 덤: `market_price_index` 는 **재생성 안 됐다**(2,381행 · min 2024-01) |
| CR51-7 | L | CR50-4·5 범위 밖 잔존(순환 동치검사 · 창 경계/`_region` 전용 검사 없음) |
| — | L | 잔가지 4 |

**pass 근거**
* **정확성 결함 없음** — 리팩터 값이 안 바뀐 것은 CR-050 이 독립 참조 960회로 확인했고, 이번
  변경은 **가드·계측·문서**뿐이다(값 경로 무변화). 새 가드가 정상 경로를 막지 않는 것을
  네 컨테이너 형으로 직접 확인했고, 새 계측(`peak_live_rows`)은 `gc` 전수와 일치한다.
  CR51-1 은 **지금 도는 경로에 없다**(실행기가 예외를 전파해 죽는다 — 코드 확인).
* **보안 냄새 없음** — 산출 JSON·로그·요약에 개인 정보 없음(검사가 단언) · SQL 전부 파라미터
  바인딩 · 세션 읽기 전용을 **효과로** 확인(AUTOCOMMIT 거부 + `SHOW`) · 감시 알림에 v4·v6 주소
  모두 가림(`<ip>` 존재와 원문 부재를 둘 다 검사). 리뷰 중 서버 방화벽·유닛 변경 0.
* **핵심 로직 테스트 있음** — 감시 변이 3종이 각각 자기 무리만 죽인다(합 10 · rc=1) ·
  T6e 하네스 관문으로 가짜가 관대해지는 길이 막혔다 · 백엔드 신규 10건 중 공허한 것 없음.
* **레이어 위반 없음** — `test_backtest_domain_contains_no_sql_or_engine` 이 `*.py` 글롭이라
  신규 파일도 자동 포함. 도메인에 SQL·엔진 import 0. `ruff` 통과.

**다음 커밋 전 처리 권고(전부 저비용)**: CR51-1(가드 1줄 + 검사 1개) · CR51-2(픽스처 1줄) ·
CR51-3("못 잡는 것" 1줄) · CR51-6(문서 2줄 — ⚠️→✅ 와 `market_price_index` 실측).
**첫 백테스트 실행 때 필수**: `backtest.md §7-13-B` 의 `[미측정]` 3칸을 `docker stats` 와 함께 지울 것.
**배선 전 필수(CR-049 유지)**: `complex-typing.md §4` 재측정 — 그때 `api-spec §4.5` 의
36.1%·5.5%·16.9% 도 같이 갱신(CR51-5).
