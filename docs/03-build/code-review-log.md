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
