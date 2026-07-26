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
