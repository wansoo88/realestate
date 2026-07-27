# API 명세 — 부동산 AI 자문 시스템

> 2단계 설계 산출물 · 2026-07-24 · FastAPI (OpenAPI 3.1)
> 기준: `erd.md` 데이터 모델, `architecture.md` 비동기 흐름
> Base URL: `https://<DEPLOY_HOST>/api/v1`

---

## 0. 공통 규약

| 항목 | 규칙 |
|---|---|
| 인증 | `Authorization: Bearer <access_token>` (JWT). 공개 엔드포인트 없음 — 개인 자산 기반 서비스 |
| 금액 | **원 단위 정수**(`bigint`). 소수·만원 단위 금지 (반올림 오차가 세금 계산을 망친다) |
| 면적 | ㎡ (`numeric`). 평은 화면에서만 변환 |
| 좌표 | WGS84 (EPSG:4326), `[경도, 위도]` 순서 |
| 날짜 | ISO 8601 (`2026-07-24`), 시각은 `timestamptz` |
| 에러 | `{ "error": {"code": "...", "message": "...", "detail": {...}} }` |
| 페이징 | `?limit=&cursor=` (커서 방식 — offset은 대용량에서 느림) |

### 공통 에러 코드
| HTTP | code | 의미 |
|---|---|---|
| 400 | `INVALID_PARAM` | 파라미터 오류 |
| 401 | `UNAUTHORIZED` | 토큰 없음/만료 |
| 403 | `CSRF_HEADER_REQUIRED` | 쿠키 인증 엔드포인트(`/auth/refresh`·`/auth/logout`)에 `X-Requested-With: XMLHttpRequest` 누락 |
| 403 | `PENDING_APPROVAL` | **관리자 승인 대기** 계정 (§1.5) |
| 403 | `ACCOUNT_REJECTED` | 가입이 거부된 계정 (§1.5) |
| 404 | `NOT_FOUND` | 대상 없음 |
| 409 | `JOB_IN_PROGRESS` | 동일 조건 분석이 이미 실행 중 |
| 409 | `LAST_ADMIN` | 마지막 관리자를 거부·강등하려 함 (§6.5) |
| 422 | `INSUFFICIENT_DATA` | **데이터 부족으로 판단 보류** (추정하지 않고 명시적으로 거부) |
| 429 | `RATE_LIMITED` | 호출 제한 |
| 503 | `UPSTREAM_UNAVAILABLE` | 공공API/Claude API 장애 |

> `422 INSUFFICIENT_DATA`는 이 서비스에서 **정상 동작**이다. 데이터가 없으면 지어내지 않는다.

> ### 스키마 검증 실패(422)의 본문 형식 — 클라이언트 계약 (SR25-4, 2026-07-28)
> 요청이 **스키마 검증**에서 떨어지면(FastAPI `RequestValidationError`) 본문은
> `{"error":{...}}` 가 아니라 **`{"detail":[...]}` 배열**이다. 각 항목은 세 키뿐이다:
> ```json
> {"detail":[{"type":"string_too_short","loc":["body","password"],
>             "msg":"String should have at least 12 characters"}]}
> ```
> * **`input` 키가 없다.** FastAPI 기본 핸들러는 사용자가 보낸 원본 값을 여기 실었고,
>   그래서 평문 비밀번호·자산 금액이 응답으로 되돌아왔다(security.md §3.3 참조).
>   `Infinity`·`NaN` 이 `input` 에 실려 422 가 500 으로 바뀌던 문제도 함께 닫혔다.
> * **`msg` 는 최대 200자**로 잘린다. 사람이 읽는 문장이며 **기계가 분기할 값이 아니다** —
>   분기는 `type`·`loc` 으로 한다(문구는 pydantic 버전에 따라 바뀔 수 있다).
> * 프론트는 `detail` 이 배열이면 `UNKNOWN` 으로 떨어뜨리고 폼 단에서 처리한다
>   (`frontend/src/api/client.ts`). 이 동작은 기본 핸들러 시절과 같다.

---

## 1. 인증

> **refresh 토큰은 응답 본문에 절대 실리지 않는다.** `httpOnly` 쿠키로만 오간다
> (security.md §2.1 / SR15-1). access 는 클라이언트 **메모리 전용**으로 보관한다 —
> `localStorage`·`sessionStorage` 금지.

### 공통 — refresh 쿠키
| 항목 | 값 |
|---|---|
| 이름 | `refresh_token` (JS 는 읽을 수 없다) |
| 속성 | `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth; Max-Age=604800` (7일) |
| `Secure` | 운영은 항상 붙는다. `COOKIE_SECURE=false` 는 `DEBUG=true` 인 로컬 http 개발에서만 유효 |
| 전송 범위 | `Path` 때문에 `/api/v1/auth/*` 요청에만 실린다 (지도·추천 요청에는 따라다니지 않는다) |

### `POST /auth/register`
가입은 **접수**될 뿐이다. 계정은 `pending` 으로 만들어지고 **관리자 승인 전에는 로그인할 수 없다**(§1.5).
```json
// req
{ "email": "me@example.com", "password": "..." }
// res 201
{ "user_id": 1, "status": "pending",
  "message": "가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다." }
```
| 코드 | 의미 |
|---|---|
| 409 `EMAIL_TAKEN` | 이미 가입된 이메일 |
| 422 | 비밀번호 12자 미만 등 형식 오류 |

> ⚠️ 알려진 잔여 노출: `409 EMAIL_TAKEN` 은 그 이메일이 가입돼 있음을 알려준다(기존 계약 유지).
> 로그인 경로의 열거 방지(§1.5)와 달리 여기서는 "이미 가입됨"을 알려주지 않으면 사용자가
> 같은 주소로 반복 신청하게 된다. 승인제가 켜져 있어 가입 사실만으로는 접근 권한이 없다.

### `POST /auth/login`
```json
// req
{ "email": "me@example.com", "password": "..." }
// res 200  — refresh_token 필드는 없다
{ "access_token": "...", "token_type": "bearer", "expires_in": 1800 }
```
```
Set-Cookie: refresh_token=<jwt>; HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth; Max-Age=604800
```
- `expires_in` = access 수명(초, 30분). 프론트는 만료 전에 미리 갱신한다.
- 401 은 **없는 계정과 틀린 비밀번호를 구분하지 않는다**(계정 열거 방지).
- 403 `PENDING_APPROVAL` / `ACCOUNT_REJECTED`: 비밀번호는 맞았지만 승인되지 않은 계정.
  **이 응답은 비밀번호가 맞을 때만 나온다** — 검사 순서가 계약의 일부다(§1.5).

### `POST /auth/refresh`
**요청 본문 없음.** 쿠키로 인증한다.
```
POST /api/v1/auth/refresh
X-Requested-With: XMLHttpRequest        ← 필수 (CSRF 2차 방어)
Cookie: refresh_token=...               ← 브라우저가 자동 첨부
```
```json
// res 200 — 응답 본문은 login 과 동일
{ "access_token": "...", "token_type": "bearer", "expires_in": 1800 }
```
- **쿠키를 회전시킨다** — 응답에 새 `Set-Cookie` 가 실리고 이전 refresh 는 브라우저에서 대체된다.
- 401 `UNAUTHORIZED`: 쿠키 없음·만료·서명 오류·access 토큰을 쿠키에 넣은 경우.
  **이 응답은 쿠키를 즉시 삭제한다**(`Max-Age=0`) → 클라이언트는 로그인 화면으로 보낸다.
- 403 `CSRF_HEADER_REQUIRED`: `X-Requested-With` 누락. **쿠키는 유지된다**(재시도 가능).
- 본문에 `refresh_token` 을 실어 보내는 경로는 **없다**(제거됨). 보내도 무시되고 401.

### `POST /auth/logout`
```
POST /api/v1/auth/logout
X-Requested-With: XMLHttpRequest        ← 필수
```
- **204 No Content** + `Set-Cookie: refresh_token=; Max-Age=0; Path=/api/v1/auth; ...`
- 인증 헤더가 필요 없다 — access 가 이미 만료돼도 로그아웃할 수 있어야 한다.
- 403 `CSRF_HEADER_REQUIRED`: 커스텀 헤더 누락.
- ⚠️ 현재는 **브라우저에서 지우는 것까지**다. 서버측 폐기(jti denylist)는 후속 과제 SR15-3.
  클라이언트는 로그아웃 시 메모리의 access 토큰도 함께 버려야 한다.

> **fetch 주의**: 동일 오리진이므로 기본값(`credentials: "same-origin"`)으로 쿠키가 실린다.
> 프록시 뒤 다른 오리진에서 호출한다면 `credentials: "include"` 가 필요하고, 그때는
> 서버에 CORS 허용 오리진 설정이 별도로 있어야 한다(현재 없음 — 동일 오리진 전제).

### 1.5 가입 승인 상태 (2026-07-26 추가 · `migrations/009_user_approval.sql`)

이 서비스는 **보유현금·연소득·기존대출**을 저장한다. 계정 하나가 곧 개인 금융정보
저장소 하나이므로, 공개된 주소에서 **아무나 가입해 바로 쓰는** 상태를 두지 않는다.

| 상태 | 로그인 | 설명 |
|---|---|---|
| `pending` | ❌ 403 `PENDING_APPROVAL` | 가입 직후 기본값. 관리자 검토 대기 |
| `approved` | ✅ | 관리자가 승인함 |
| `rejected` | ❌ 403 `ACCOUNT_REJECTED` | 거부됨(승인 회수 포함) |

**검사 순서가 곧 보안 규약이다 (SR10-1 계정 열거 방지)**
1. 비밀번호를 **먼저** 검증한다. 틀리면 없는 계정과 **완전히 동일한** 401
   (본문·상태코드·응답시간 모두 — 없는 계정에도 같은 비용의 argon2 검증을 태운다).
2. 비밀번호가 맞은 **뒤에만** 승인 상태를 본다 → 403.

> 순서를 뒤집으면(“pending 이면 먼저 403”) 아무 비밀번호나 넣어 보는 것만으로
> **가입된 이메일 목록**을 만들 수 있다. 승인제가 오히려 "누가 대기 중인지"까지
> 알려주는 장치가 된다. `backend/tests/test_admin_approval.py` §2 가 이 성질을 고정한다.

**승인 회수는 즉시 적용된다.** `status` 는 토큰에 담기지 않고 **매 요청 DB 에서 다시 읽는다**.
- 이미 발급된 access 로 API 호출 → 403 (`PENDING_APPROVAL`/`ACCOUNT_REJECTED`)
- `POST /auth/refresh` → 401 + 쿠키 삭제 (사유를 구분하지 않는다)
- 서버측 토큰 폐기(SR15-3)가 없는 상태에서 **이 재확인이 유일한 회수 수단**이다.

---

## 2. 내 조건 (F2, F5)

### `GET /me/profile` · `PUT /me/profile`
```json
// PUT req — 자산 정보 (🔐 서버에서 암호화 저장)
{
  "cash_krw": 300000000,
  "income_krw": 90000000,
  "existing_loan_krw": 50000000,
  "owned_houses": 0,
  "household_size": 3
}
// res 200 — 응답에도 금액을 그대로 돌려주되, 로그에는 절대 남기지 않음
```
> ⚠️ 이 엔드포인트의 요청/응답 본문은 **접근 로그·에러 로그에서 제외**한다(G3).

### `GET /me/preferences` · `PUT /me/preferences` (F5)
```json
{
  "prefer": { "school_district": 5, "subway_within_m": 500, "built_after": 2010, "min_households": 500 },
  "avoid":  { "first_floor": true, "main_road_noise": true, "redevelopment_early_stage": true },
  "weights": { "price": 0.3, "location": 0.3, "value": 0.25, "risk": 0.15 }
}
```
> `weights` 는 **추천 총점 계산에 실제로 쓰인다** — 축 ↔ 에이전트 매핑과 재정규화·고지
> 규칙은 §5.3 참조. 서버가 다시 정규화하므로 합이 1 이 아니어도 되고, 모르는 키는
> 무시하되 추천 응답의 `notes` 에 남는다(조용히 버리지 않는다).

---

## 3. 실구매 가능 금액 (F2 · 동기 · 규칙 계산)

### `POST /affordability`
**LLM을 쓰지 않는다.** 세법·대출 규제 기반 결정론적 계산.

`max_purchase_krw` 의 UI 라벨은 **"최대 실구매 가능 금액"** 이다("실구매 가능 금액"이 아니다).
"내가 낼 수 있는 최대치"라는 뜻이 라벨에 드러나야 사용자가 희망가와 혼동하지 않는다.

```json
// req (생략 시 저장된 프로필 사용)
{ "purpose": "live",          // live | invest
  "area_m2": 84.0,
  "is_regulated_area": false,
  "annual_rate": 0.04,        // **소수**(0.04 = 연 4%). 응답은 퍼센트로 나간다.
  "years": 30,
  "target_price_krw": 900000000 }   // 희망 매매가 — 주면 `plan` 이 붙는다(선택)

// res 200
{
  "max_purchase_krw": 850000000,
  "breakdown": {
    "own_cash_krw": 300000000,
    "max_loan_krw": 550000000,
    "ltv_limit_pct": 70,
    "dsr_limit_pct": 40,
    "binding_constraint": "DSR"        // 무엇이 한도를 결정했는지
  },
  "acquisition_cost_krw": { "tax": 9350000, "brokerage": 5100000, "etc": 1000000 },
  "assumptions": [
    { "claim": "취득세율 1.1%", "source": "지방세법 §11 (1주택 6억 이하)",
      "as_of": "2026-07-24", "verifier": "위택스" },
    { "claim": "LTV 70%", "source": "<규제지역 여부에 따른 고시>", "as_of": "2026-07-24" }
  ],
  "disclaimer": "실제 한도는 금융기관 심사에 따라 달라집니다."
}
```
> `assumptions`는 **선택이 아니라 필수**다. 세율·한도가 출처·기준일자 없이 나가면 G2 위반.

> ⚠️ **권역(`region_group`·`target_region_code`)은 요청에 넣을 수 없다.** 사용자가 비수도권
> 코드를 보내 6억 절대한도를 끄고 예산을 부풀릴 수 있어서다(CR10-1). 서버가 판정하며
> 기본값은 **수도권(캡 적용)** 이다.

#### 희망 매매가 자금계획 — `target_price_krw` (선택)

`target_price_krw` 를 주면 응답에 **`plan`** 이 추가된다. **안 주면 `plan` 키 자체가 없다**
(기존 응답과 100% 동일 — 기존 클라이언트는 영향받지 않는다).
지도에서 단지를 클릭할 때마다 그 단지 가격으로 다시 호출하는 것이 정상 사용법이다.

```jsonc
{
  // ... 위 필드는 그대로 ...
  "plan": {
    "target_price_krw":   900000000,
    "total_needed_krw":   935700000,   // 매매가 + 취득세 + 중개보수 + 등기·법무
    "cost_breakdown":     { "tax": 29700000, "brokerage": 4500000,
                            "etc": 1500000, "total": 35700000 },
    "own_cash_krw":       280000000,   // = breakdown.own_cash_krw (보유현금 − 이사·수리 예비비)
    "shortfall_krw":      655700000,   // 더 필요한 돈 (= total_needed − own_cash, 음수는 0)
    "required_loan_krw":  655700000,   // 필요 대출 (부족분 전액을 대출로 메운다는 전제)
    "loan_feasible":      false,
    "loan_limit_krw":     587072543,   // LTV·DSR·DTI·절대한도 중 **최소**
    "over_limit_krw":     68627457,    // 한도 초과분 (불가일 때만, 아니면 null)
    "binding_constraint": "DSR",       // LTV | DSR | DTI | CAP — 무엇이 한도를 묶는가
    "feasible_loan_krw":  587072543,   // 한도 안에서 실제로 받을 수 있는 금액
    "monthly_payment_krw":          3130412,   // 필요 대출 전액 기준 월 원리금
    "monthly_payment_feasible_krw": 2802774,   // 한도까지만 빌렸을 때
    "total_interest_krw": 471248320,
    "terms": { "annual_rate_pct": 4.0, "years": 30,
               "repayment": "equal_total", "grace_months": 0 }
  }
}
```

**한도를 넘어도 200 이고, 계산을 끝까지 한다.** "불가능합니다"만 띄우면 사용자는
*얼마를 더 모아야 하는지* 알 수 없다. `over_limit_krw`(= 추가로 필요한 현금)와
`binding_constraint`(무엇이 막았는가)로 답한다. 같은 사실이 `warnings` 에 문장으로도 실린다.

| 필드 | 뜻 | 화면 문구 예 |
|---|---|---|
| `shortfall_krw` | 얼마나 더 필요한가 | "6억 5,570만원이 더 필요합니다" |
| `required_loan_krw` | 얼마나 대출받아야 하나 | "대출 6억 5,570만원" |
| `monthly_payment_krw` | 얼마나 원리금 상환하나 | "월 313만원" |
| `over_limit_krw` | 왜 안 되나 / 얼마가 모자라나 | "DSR 한도를 6,862만원 초과" |

**금리·만기는 가정이다.** `annual_rate`(기본 0.04)·`years`(기본 30)로 **덮을 수 있고**,
어떤 값으로 계산했는지 `plan.terms` 가 되돌려 준다. 4%→5%면 월 상환액이 10% 넘게 뛰기 때문에
우리 기본값을 유일한 진실처럼 보여주면 그 자체가 근거 없는 단정이 된다(G2).
`assumptions` 에는 **1%p 올랐을 때의 월 상환액을 숫자로** 넣는다.

* 요청 `annual_rate` 는 **소수**(0.04), 응답 `plan.terms.annual_rate_pct` 는 **퍼센트**(4.0)다 —
  단위를 필드명에 박아 프론트가 100을 곱할지 헷갈리지 않게 했다.
* 세금·중개보수는 `/affordability` 최대 구매가 계산과 **같은 엔진·같은 `tax_rules.yaml`** 을 쓴다.
  두 벌로 나뉘면 "최대 8.4억까지 가능"과 "8.4억은 한도 초과"가 동시에 뜬다.
* 불변식: **`loan_feasible` ⟺ `target_price_krw` ≤ `max_purchase_krw`**. 두 숫자가 모순되면 버그다.
* 검증: `target_price_krw` 는 **양수·1,000억 이하**. 0·음수·초과는 **422**(단위 실수를 조용히 계산하지 않는다).

---

## 4. 지도 · 매물 조회 (F1)

### `GET /map/complexes` — 화면 범위 내 단지
목표 응답 **1초 이내**. 지도를 움직일 때마다 호출된다.

| 파라미터 | 예 | 설명 |
|---|---|---|
| `bbox` | `126.9,37.5,127.1,37.6` | minLon,minLat,maxLon,maxLat |
| `zoom` | `14` | **줌에 따라 반환 단위가 바뀐다** |
| `max_price_krw` | `850000000` | `/affordability` 결과 연동 |
| `area_min_m2` / `area_max_m2` | `59` / `85` | 각각 `> 0`. **min > max 는 400** (조용히 뒤집지 않는다) |
| `built_after` | `2010` | |

```json
// res 200 — zoom < 13 : 군집(클러스터)
{ "level": "cluster",
  "items": [ { "region_code": "1168000000", "name": "강남구", "count": 342,
               "center": [127.047, 37.517], "median_price_krw": 1850000000 } ] }

// res 200 — zoom >= 13 : 단지 단위
{ "level": "complex",
  "items": [ { "id": 1024, "name": "○○아파트", "point": [127.051, 37.514],
               "households": 1200, "built_year": 2008,
               "recent_price_krw": 1420000000,
               "price_as_of": "2026-06-30",
               "price_confidence": "estimated",
               "active_listings": 7 } ] }
```
> `price_as_of` + `price_confidence`를 **항상 함께 반환**한다. 실거래 신고 지연 최대 30일 →
> 클라이언트가 "현재가"로 표시하면 안 된다.

### `GET /complexes/{id}` — 단지 상세
```json
{ "id": 1024, "name": "○○아파트", "region": {...},
  "built_year": 2008, "total_households": 1200, "total_buildings": 12,
  "floor_area_ratio": 249.8, "building_coverage": 18.2,
  "unit_types": [ { "id": 5, "area_m2": 84.97, "type_name": "84A", "rooms": 3 } ],
  "buildings": [ { "id": 88, "name": "101동", "point": [127.0512, 37.5141], "floors": 25 } ],
  "redevelopment": null }
```

### `GET /complexes/{id}/trades` — 실거래 이력 (F4)
`?area_m2=84.97&months=24&group_by=floor_band`

```json
{ "items": [ { "contract_date": "2026-06-12", "price_krw": 1420000000,
               "floor": 14, "area_m2": 84.97, "apt_dong": "101", "is_cancelled": false } ],
  "stats": { "median_krw": 1400000000, "n": 37,
             "by_floor_band": { "1-5": 1310000000, "6-15": 1405000000, "16+": 1455000000 } },
  "note": "실거래는 신고까지 최대 30일이 걸려 최근 거래가 반영되지 않았을 수 있습니다." }
```
> ⚠️ **설계 정정(2026-07-25)**: 초안은 여기에 *"동(棟)별 구분은 국토부 공개 데이터에 포함되지 않습니다"* 를
> 하드코딩 고지로 두고 동별 분석을 불가능으로 봤다. 그러나 **운영 API 는 `aptDong` 을 77~93% 제공**한다
> (`erd.md` §0 정정, 실호출 실측). 그래서 `apt_dong` 을 응답에 싣고, 동별 편차는 추천 결과의
> `dong_valuation`(§5)에서 **실측/추정을 `basis`·`confidence` 로 구분해** 제공한다.
> `apt_dong` 은 **결측(null)일 수 있다** — 클라이언트는 없는 경우를 반드시 처리해야 하고,
> 없는 값을 추정해 채워 넣으면 안 된다(G2).

### `GET /complexes/{id}/listings` — 현재 호가
```json
{ "items": [ { "id": 9901, "ask_price_krw": 1480000000, "floor": 9,
               "building": { "id": 88, "name": "101동" },
               "listed_at": "2026-07-01", "days_on_market": 23,
               "duplicate_count": 4, "trust_score": 0.82 } ],
  "source_note": "호가는 희망 가격이며 실거래가와 다릅니다." }
```

---

## 5. AI 추천 (F1·F3·F6 · 비동기)

### `POST /recommendations` → `202 Accepted`
```json
// req
{ "region_codes": ["1168000000","4113500000"],
  "bbox": "127.01,37.45,127.12,37.54",  // "이 주변에서 검색" (선택)
  "purpose": "live",
  "budget_override_krw": null,        // 희망 매매가 = **예산 상한**.
                                      // null 이면 최대 실구매 가능 금액을 상한으로 사용
  // --- 내 조건 (후보 선별 · 2026-07-27 추가) ---------------------------
  "area_min_m2": 59, "area_max_m2": 85,   // 전용면적. `/map/complexes` 와 **같은 규칙**
  "built_after": 2000,                    // 준공연도(이후)
  "min_households": 500,                  // 최소 세대수
  "use_saved_conditions": true,           // false 면 저장된 "내 조건"을 이번엔 쓰지 않는다
  "agents": ["listing-researcher","finance-tax-advisor","valuation-trader",
             "location-analyst","portfolio-advisor"],   // 생략 시 MVP 5종
  "top_n": 10 }

// res 202
{ "job_id": "rec_01J...", "status": "queued",
  "poll_url": "/api/v1/recommendations/rec_01J...",
  "note": "분석을 시작했습니다. 잠시 후 결과를 조회하세요." }
```

> **구현 상태(2026-07-26)** — 분석은 redis·워커 없이 **인프로세스 BackgroundTask** 로 돈다
> (배포 최소구성이 api+db 다). 그래서 `estimated_seconds`·`stream_url`·`progress` 는
> **구현하지 않았다** — 진행률을 셀 중간 상태가 없다. 폴링하면 `queued` 다음이 `done` 이다.
> 있는 척하면 프론트가 없는 필드를 기다린다. SSE(`/stream`)는 2차.

#### 검색 범위 — `region_codes` · `bbox` (REC-5, 2026-07-26)

| 필드 | 형식 | 의미 |
|---|---|---|
| `region_codes` | **숫자 2~10자리** 법정동코드 배열 (최대 50개) | 시도(2)·시군구(5)·읍면동(8)·리(10). **접두 매칭** |
| `bbox` | `minLon,minLat,maxLon,maxLat` | **`GET /map/complexes` 의 `bbox` 와 같은 형식** |

**조합 규칙**

| 보낸 것 | 대상 |
|---|---|
| 둘 다 없음 | 전체 (기존 동작) |
| `region_codes` 만 | 그 지역 |
| `bbox` 만 | 그 화면 범위 |
| **둘 다** | **교집합(AND)** — 두 조건을 모두 만족하는 단지 |

> 교집합인 이유: 사용자가 지역을 고르고 "이 주변"까지 눌렀다면 둘 다 만족하는 결과를
> 기대한다. 합집합이면 "강남 선택 + 평촌 화면"이 강남 **전체 + 평촌 전체**가 되어,
> 조건을 좁히려고 누른 버튼이 오히려 범위를 넓히는 셈이 된다.
> 교집합을 적용하면 `notes` 에 그 사실을 싣는다.

**입력 검증 — 위반 시 `422`** (`/map/complexes` 는 쿼리 파라미터라 기존대로 `400`)

- `bbox`: 값 4개 · 숫자(NaN/Inf 불가) · 경도 −180~180 · 위도 −90~90 ·
  `min < max` · 한 변 **2.0도 이하**(수도권 전체를 덮는 크기).
  빈 문자열 `""` 은 "안 보냄"과 같게 본다.
- `region_codes`: `^\d{2,10}$`. **`%`·`_` 는 거절한다** — SQL 접두 매칭에 섞이면
  에러 없이 전 지역이 매칭되어 지역 선택이 **조용히 무력화**된다(SR21-4).

#### 내 조건 — 평수·연식·세대수 (2026-07-27 · 사용자 제보 수정)

> **사고 요약**: 지도(`GET /map/complexes`)에는 `area_min_m2`/`area_max_m2` 가 있는데
> **추천 요청 스키마에는 평수가 아예 없었다.** 같은 화면의 같은 조건이 지도는 거르고
> 추천은 안 걸러서, 사용자는 "조건에 안 맞는 매물이 추천된다"를 겪었다.
> 운영 실측(강남 11680, 조건 55~62㎡): 조건 없이 나온 추천 10건 중 **9건이 조건 밖**
> (18~44㎡·84㎡). 수정 후 4건 전부 조건 안.

| 필드 | 검증 | 의미 |
|---|---|---|
| `area_min_m2` / `area_max_m2` | `> 0` · **min > max 는 400** | 전용면적(㎡) |
| `built_after` | `1900~2100` | 이 연도 **이후** 준공 |
| `min_households` | `0~1,000,000` | 단지 세대수 하한 |

**요청 우선 · 저장된 "내 조건" 폴백.** 요청에 없으면 서버가
`user_preference.prefer`(같은 이름의 키)를 쓴다. 프론트가 한 줄을 빠뜨려도 조건이
증발하지 않게 하려는 것이다(이번 사고의 모양이 정확히 그것이었다).

**끄는 방법도 있다 — `use_saved_conditions: false`.** 폴백만 두면 화면에서 면적 칩을
껐는데 추천은 계속 걸러지는 상태가 된다(끈 조건이 계속 켜져 있는, 이번 사고의 거울상).
`null` 은 "안 보냄"과 같아 값으로는 '조건 없음'을 표현할 수 없으므로 스위치를 둔다.
`false` 면 요청 본문에 실린 조건만 적용하고, 적용된 조건이 없으면 조건 고지도 내지 않는다.

**평수는 "제외 사유"가 아니라 후보 선별(hard filter)이다.** 59㎡를 원하는 사람에게
84㎡는 제외 사유를 붙일 대상이 아니라 애초에 후보가 아니다. 그래서 `excluded[]` 에
수천 건을 쌓지 않고 **몇 건이 걸러졌는지 `notes` 로 말한다**:

> *"전용 55~62㎡ 조건으로 범위 내 단지 506개 중 410개를 제외했습니다 — 해당 면적대의
> 실거래·매물·타입 근거가 없거나 면적 정보가 확인되지 않은 단지입니다."*
> *"조회된 단지에서 면적 조건 밖 후보 61건을 제외했습니다."*

**미상(NULL)은 통과시키지 않는다.** 면적·연식·세대수를 모르는 대상은 조건이 걸린 순간
빠진다 — 모르는 것을 "조건에 맞다"고 우기면 제보가 그대로 재현되기 때문이다.
대신 **미상으로 빠진 수를 따로 세어 고지한다**(모름 ≠ 아님).

**판정 단위는 단지가 아니라 후보(단지 × 면적대)다.** 59㎡와 84㎡를 함께 가진 단지는
쿼리를 통과하지만 84㎡ 후보는 결과에 나오지 않는다. 쿼리 필터는 조회 상한(50개 단지)이
조건 밖 단지로 차는 것을 막는 **성능 장치**이고, 계약을 지키는 곳은 후보 조립이다.

> **회귀 방지 구조** — `app/domain/conditions.py` 의 조건 레지스트리가 정본이고,
> `backend/tests/test_condition_reach.py` 가 ① 화면(`Preferences`)이 수집하는 키가 전부
> 레지스트리에 있는지 ② "반영된다"고 선언한 조건이 **켜고 끌 때 결과가 실제로 달라지는지**
> 를 검사한다. 새 조건을 UI 에 추가하고 서버 배선을 잊으면 테스트가 먼저 실패한다.
> 반영하지 않는 조건(`역세권`·`1층 기피`·`재건축 초기 기피`·`학군 중요도`)은
> **설정된 경우에만** `notes` 로 "아직 반영되지 않습니다"라고 말한다.

#### 희망 매매가 — `budget_override_krw` (2026-07-26)

**의미는 '상한'이다.** 이 값을 주면 **그 금액 이하** 후보만 본다. `null` 이면
`/affordability` 의 `max_purchase_krw`(최대 실구매 가능 금액)를 상한으로 쓴다.
프론트의 "희망 매매가 슬라이더"는 이 필드로 보낸다.

> **왜 상한이고 ±N% 대역이 아닌가**
> ① 이 필드는 원래 "이 금액 이하만 보여 달라"는 뜻으로 만들어졌고 후보 조회·제외 판정이
> 이미 그렇게 동작한다 — 같은 필드가 호출자에 따라 다른 뜻이 되면 안 된다.
> ② 대역으로 바꾸면 희망가보다 **싼** 좋은 후보가 하한에 걸려 사라진다.
> 예산은 "여기까지"이지 "여기쯤"이 아니다 — 싸게 사는 것은 실패가 아니다.
> (대역이 필요하면 `min_price_krw` 를 새로 만들 일이지 이 필드를 바꿀 일이 아니다.)

**희망가가 최대 실구매 가능 금액을 넘어도 후보를 보여준다.** 다만 `notes` 로 고지한다 —
*"희망 매매가 9억원을 예산 상한으로 적용했습니다 … 다만 이 금액은 산정된 최대 실구매 가능
금액 8억 3,775만원을 6,225만원 초과합니다 — 초과분은 추가 현금이 필요합니다."*

> ⚠️ **회귀 주의(2026-07-26 수정)** — 예전에는 파이프라인이 **항상** `max_purchase_krw` 로만
> 예산을 판정해서, `budget_override_krw` 가 후보 *조회*에만 닿고 *제외 판정*에는 닿지 않았다.
> 그래서 희망가를 자기 한도보다 높게 잡으면 조회를 통과한 후보가 전부 "예산 초과"로 잘려
> **결과가 통째로 비었다**(슬라이더를 올릴수록 결과가 사라진다). 서울 실데이터 실측:
> 희망가 9억으로 조회한 후보 50건 중 **5건**이 한도(8.3775억)~희망가(9억) 구간에 있었고
> 전부 사라졌다. 지금은 `AnalysisContext.budget_krw` 로 명시 전달한다.

각 추천 카드에는 **적용 예산 대비 차액**이 실린다(프론트가 "희망가보다 1.2억 저렴"을 표시).

| 필드 | 뜻 |
|---|---|
| `budget_gap_krw` | `est_price_krw − 적용예산`. **음수 = 희망가보다 싸다**. 예산을 모르면 `null` |
| `budget_gap_pct` | 같은 값의 % (소수 1자리) |

**⚠️ bbox 는 좌표가 있는 단지만 찾는다**
`complex.geom` 이 NULL 인 단지(주소 지오코딩 미완)는 공간 연산에서 구조적으로 빠진다.
서버는 그때그때 좌표 확보율을 세어 `notes` 에 싣는다 —
예: *"'이 주변' 검색은 좌표가 확인된 단지만 대상입니다. 전체 단지 16,462개 중 901개(5.5%)는
주소 좌표가 아직 없어 이 결과에서 빠졌습니다 — 지역으로 검색하면 포함됩니다."*
(2026-07-26 서버 실측: 전체 94.53% · 강남 11680 은 99.21%)

### `GET /recommendations/{job_id}` — 결과 폴링
```json
// 진행 중 (아직 결과가 없다. progress 필드는 없다 — 위 구현 상태 참조)
{ "job_id": "rec_01J...", "status": "queued", "items": [],
  "excluded": [], "notes": [] }

// 완료
{ "status": "done",
  "criteria_snapshot": { ... },          // 재현성: 어떤 조건으로 돌렸는지 동결
  "items": [
    { "rank": 1, "total_score": 82.4,    // 점수 근거가 하나도 없으면 null (0 아님)
      "score_basis": "agent_scores",     // null 이면 total_score 도 null
      "complex": { "id": 1024, "name": "○○아파트" },
      "unit_type": { "area_m2": 84.97, "type_name": "84A" },
      "building": { "id": 88, "name": "101동", "confidence": 0.6,
                    "basis": "listing_reported" },   // 호가 없으면 null

      // --- 가격 근거 (price_basis) ---------------------------------------
      "price_basis": "listing",          // "listing" | "trade"
      "ask_price_krw": 1480000000,       // 호가. price_basis="trade" 면 **null**
      "est_price_krw": 1480000000,       // 판단·예산 비교에 실제로 쓴 기준가
      "price_estimated": false,          // true 면 est_price_krw 가 추정치
      "price_note": null,                // trade 기준일 때만 문구가 들어온다
      "ask_gap_pct": 5.7,                // 호가 vs 적정가 중위. trade 면 **null**
      // --- 적용 예산 대비 (희망 매매가 슬라이더) --------------------------
      "budget_gap_krw": -120000000,      // est_price − 적용예산. **음수 = 예산보다 싸다**
      "budget_gap_pct": -13.3,           // 예산을 모르면(자산 미입력 등) 둘 다 null
      "price_band": { "p25_krw": 1380000000, "median_krw": 1400000000,
                      "p75_krw": 1450000000, "sample_size": 37,
                      "period_months": 6, "expanded": false,
                      "source": "국토교통부 실거래가" },
      "dong_valuation": {                    // F4 동별 실측(erd §0 정정)
        "available": true, "method": "실측(aptDong)", "basis": "trade_measured",
        "confidence": 0.85, "coverage_pct": 87.0, "period_months": 6,
        "dongs": [ { "dong": "101", "vs_complex_pct": 5.2, "sample": 12,
                     "median_ppm_krw": 16800000 },
                   { "dong": "105", "vs_complex_pct": -4.1, "sample": 8,
                     "median_ppm_krw": 15300000 } ]
      },
      // 동 정보/표본 부족 시: { "available": false, "method": "동정보없음"|"동표본부족",
      //                       "confidence": 0.0, "reason": "...", "note": "좌표추정 폴백" }

      // --- 화면 배지용 **값** (2026-07-27) ---------------------------------
      // 🏢대단지·🚇역세권 배지는 임계값 판정이 아니라 **값**으로 내려간다.
      //  · 임계값(1,000세대·500m)은 표시 관례라 바뀐다. 서버가 boolean 으로 굳혀 보내면
      //    저장된 payload(실행 결과 스냅샷)에 옛 기준이 박혀 되돌릴 수 없다.
      //  · 모르면 **null**. 0·false 로 만들지 않는다 — 전체 16,462개 중 2,666개가
      //    세대수 미확보이고 "모름"과 "아님"은 다른 사실이다.
      "total_households": 1200,            // 모르면 null
      "nearest_station": { "name": "강남역", "distance_m": 320.0,
                           "line_count": 2, "lines": ["2호선","신분당선"],
                           "basis": "straight_line" },   // 입지 데이터 없으면 null
      // basis="straight_line": **직선거리**다. 도보 시간이 아니다(재계산하지 않고
      // location-analyst 가 이미 잰 값을 그대로 노출한다).
      "timing_signal": "unknown",          // MVP 에 타이밍 분석가 없음 — 있는 척하지 않는다
      // portfolio-advisor 종합. LLM 실패 시 규칙 기반으로 채운다(문장은 투박해도 근거는 정확).
      // summary_basis: "llm" | "fallback" — **이 카드의 문장을 누가 썼나**(§5.4).
      // notes 만으로는 어느 카드가 규칙 기반인지 알 수 없어 카드 단위로도 밝힌다.
      "summary_basis": "llm",
      "headline": "예산 안에서 가장 균형 잡힌 후보",
      "why": [ "동일 타입 중위 대비 호가 -2%", "역세권 350m" ],
      "why_not": [ "실거래 신고 지연으로 최근 거래가 빠졌을 수 있음" ],   // 항상 채운다
      "next_actions": [ "현장에서 소음·일조 확인" ],
      "findings": [
        { "agent_id": "finance-tax-advisor", "score": 88, "verdict": "적합",
          "rationale": "취득세 포함 총 필요자금 8.42억으로 한도 내.",
          "evidence": { "claim": "취득세 1.1%", "source": "지방세법 §11",
                        "as_of": "2026-07-24" },
          "confidence": 0.95 },
        { "agent_id": "valuation-trader", "score": 76, "verdict": "적정가 하단",
          "rationale": "최근 6개월 동일 타입 중위 14.0억 대비 호가 14.8억은 상단.",
          "evidence": [ { "claim": "중위 실거래가 1,400,000,000원",
                          "source": "국토교통부 실거래가", "data_rows": 37 } ],
          // 리스크는 **finding 안에** 들어간다(어느 에이전트가 말했는지가 근거의 일부다).
          "risks": [ { "severity": "medium",
                       "detail": "실거래는 신고까지 최대 30일이 걸려…" } ],
          // 판단을 보류하면 verdict="판단 보류" + missing 에 사유가 들어온다(score=null).
          "missing": [],
          "confidence": 0.80 }
      ] } ],

  // --- 왜 이건 안 나왔나 (§5.2) ------------------------------------------
  "excluded": [
    { "complex_id": 2048, "complex_name": "○○아파트", "area_m2": 84.97,
      "price_basis": "trade", "price_estimated": true,
      "reason_code": "over_budget",
      "reason": "예산 초과 (최근 실거래 중위 950,000,000원(추정) > 한도 850,000,000원)" } ],
  "notes": [ "일부 후보는 현재 등록된 매물이 없어 최근 실거래 기준으로 세운 추정입니다…" ],
  "disclaimer": "투자 권유가 아니며 개인 판단을 돕는 참고 자료입니다." }
```

**응답 설계 원칙**
1. 장점(`why`)과 단점(`why_not`)·`findings[].risks` 를 **항상 함께** 반환 — 장점만 나열하면 G2 위반
2. 모든 finding에 `evidence` + `confidence`
3. `dong_valuation.basis`/`confidence`로 **동별이 실측(trade_measured)인지 추정(listing_reported)인지 구조적으로 구분**. `building`은 특정 매물의 동 표기(호가 기준), `dong_valuation`은 단지 내 동별 실거래 편차(F4).
4. `criteria_snapshot`으로 재현성 확보
5. `price_basis`로 **호가인지 실거래 추정인지 구조적으로 구분**(아래 §5.1)
6. `excluded[]`로 **추천되지 않은 후보와 그 사유**를 함께 반환(아래 §5.2)

#### 5.1 `price_basis` — 호가와 실거래는 같은 숫자가 아니다 (2026-07-26 추가)

> **왜 생겼나.** 초안은 후보에 **대표 호가가 반드시 있다**고 가정했다. 그런데 공공 오픈API에는
> 호가가 없어 포털 수집이 없으면 `listing` 테이블이 통째로 빈다(실측: 단지 6,538 · 실거래 120,138 ·
> **호가 0**). 그 결과 추천이 **구조적으로 항상 0건**이 되어 CHARTER **G4**(포털 수집이 막혀도
> 공공API만으로 서비스가 성립해야 한다)와 정면 충돌했다. 이제 실거래만으로도 후보를 세우되,
> **어느 쪽 근거인지를 응답에 명시**한다.

| 값 | 뜻 | 사용자에게 보여야 할 것 |
|---|---|---|
| `listing` | "지금 이 값에 살 수 있다" — 실제 매도 호가 | 호가 · 적정가 대비 갭 |
| `trade` | "최근 이 정도에 거래됐다" — **지금 살 수 있는 물건은 없음** | 적정가 밴드 · 추정 표기 |

| 필드 | `listing` | `trade` |
|---|---|---|
| `ask_price_krw` | 호가(정수) | **`null`** — 없는 값을 실거래로 채우지 않는다 |
| `est_price_krw` | `ask_price_krw`와 동일 | 최근 실거래 중위(**추정**) |
| `price_estimated` | `false` | `true` |
| `price_note` | `null` | "현재 등록된 매물이 없습니다 — 최근 실거래 기준 추정가입니다…" |
| `ask_gap_pct` | 갭(%) | **`null`** — 비교 대상이 없으므로 계산하지 않는다 |
| `price_band` | 참고용 | **주 근거** (p25~p75 · 표본 · 기간) |
| `building` | 호가 표기 동(confidence 0.6) | `null` |
| `findings[valuation-trader].verdict` | "적정가 상단/하단/범위" | "현재 매물 없음 — 최근 실거래 기준" |
| `findings[listing-researcher]` | 신뢰도 판정 | "판단 보류" + `missing` |

**프론트 계약 (반드시 지킬 것)**
- `price_basis === "trade"` 면 가격 옆에 **추정 표기**를 붙이고 "즉시 매수 가능"으로 읽히는 UI를 쓰지 않는다.
  UI 컨셉 "확신의 농도" 상 `trade` 는 `listing` 보다 **약한 시각적 강도**로 표시한다.
- `ask_price_krw` · `ask_gap_pct` 는 `null` 일 수 있다. `est_price_krw` 로 **대체해 표시하면 안 된다**
  (그 순간 실거래 중위가 호가로 둔갑한다).
- `total_score` 는 `null` 일 수 있다(점수를 매길 근거가 없을 때). **0으로 렌더링하지 말 것** —
  `0`은 "나쁘다", `null`은 "모른다"다. `score_basis` 로 구분한다.
- `dong_valuation`(F4)은 실거래 기반이라 **`price_basis` 와 무관하게** 동작한다.

**DB 매핑 주의** — `recommendation_item.est_price_krw` 컬럼은 기준가만 담는다.
호가인지 추정인지는 **`payload.price_basis` 가 정본**이다. 컬럼만 보고 호가로 읽으면 안 된다.

#### 5.2 `excluded[]` — "왜 이건 안 나왔지"에 답한다 (2026-07-26 구현 반영)

> **왜 생겼나.** 파이프라인은 예전부터 떨어뜨린 후보와 사유를 만들었지만, 러너가 `items` 만
> 꺼내 저장해 **응답에 도달하지 못했다**(문서에도 없었다). 사용자가 자기 조건으로 추천을
> 돌렸는데 아는 단지가 빠졌을 때 이유를 못 대면, 맞는 결과도 믿을 수 없다.
> 추천 목록은 답의 절반이고 나머지 절반이 이것이다.

| 필드 | 뜻 |
|---|---|
| `complex_id` · `complex_name` | 어느 단지인가. **이름을 반드시 함께 준다** — id 만으로는 화면에 쓸 수 없다 |
| `area_m2` | 어느 면적대에서 떨어졌나(같은 단지도 면적대별로 판정이 다르다) |
| `price_basis` · `price_estimated` | 그 판정이 호가 기준인지 실거래 **추정** 기준인지 |
| `reason_code` | 기계가 읽는 축. 아래 4종 |
| `reason` | 사람이 읽는 문장(금액·표본 수 포함) |
| `total_score` | `below_rank_cutoff` 일 때만. `null` 이면 점수를 매길 근거가 없었다는 뜻 |
| `reason_redacted` | 사유 문장에서 민감정보를 가렸을 때만 `true`(아래 개인정보 규약) |

| `reason_code` | 언제 | 사용자에게 하는 말 |
|---|---|---|
| `no_price_evidence` | 활성 호가 없음 + 실거래 표본 부족 | 값을 말할 근거가 없어 판단하지 않았다 |
| `over_budget` | 기준가 > 실구매 가능 금액 | 못 사는 집은 추천이 아니다 |
| `avoided` | 사용자가 **기피**한 조건 해당(F5) | 가점 상쇄가 아니라 제외다 |
| `below_rank_cutoff` | 분석은 통과했으나 상위 `top_n` 밖 | 조건은 맞지만 근거가 더 약했다 |

**불변식** — 조회한 단지는 **추천이거나 제외**다. 말없이 사라지는 후보는 없다.
파이프라인 안에서는 `len(items) + len(excluded) == 후보 수` 가 정확히 성립하고, 응답에는
그 앞단(후보 조립)에서 떨어진 단지(`no_price_evidence`)가 더해진다 — 후보가 되기도 전에
사라지던 쪽이 사용자 질문("우리 단지가 아예 안 보인다")에 오히려 더 가깝기 때문이다.
크기는 유계다: 후보 상한 `MAX_CANDIDATES`(200) + 단지 조회 상한(50).

**개인정보 규약 (SR4-2)** — `reason` 문장에는 **한도·초과분 같은 파생값만** 적는다.
보유현금·연소득·기존대출 **원본 금액은 금지**다. 이 필드는 `recommendation_job.result_meta`
에 **평문 jsonb** 로 저장되므로(migrations/010), 자산 3종의 컬럼 암호화(security.md §3)가
사유 문장으로 무력화되면 안 된다. 러너가 저장 직전에 값 비교로 한 번 더 거르고,
걸리면 문장만 안전한 문구로 바꾸고 `reason_redacted: true` 를 붙인다(사유 자체는 남긴다).

**`notes[]`** — 결과 전체에 붙는 단서(추정가 포함 여부, 미구현 기능 고지, 프로필 미입력 등).
`items` 가 비어 있을 때 **왜 비었는지**를 말하는 자리이기도 하다. 조회·후보 **상한에 걸려
지역 전체를 보지 못한 경우**도 여기서 밝힌다(실측: 강남구 단지 506개 중 50개만 조회).

**저장 위치** — `recommendation_job.result_meta jsonb`(010). `recommendation_item` 에는
넣지 않는다 — 제외된 후보는 항목이 아니라서, 그 테이블에 섞이면 조회 필터 하나만 어긋나도
**제외된 단지가 추천으로 둔갑한다.**

**`top_n`** — 요청값을 실제로 지킨다(1~50, 기본 10). `below_rank_cutoff` 사유가 "상위 N건 밖"
이라고 말하므로, 그 N 은 사용자가 요청한 값과 같아야 한다.

**프론트 계약** — `excluded` 가 `null`/미포함이면 "이번 응답에 포함되지 않았습니다"로,
빈 배열이면 "제외된 후보 없음"으로 **다르게** 표시한다. 둘은 다른 사실이다.
`area_m2` 는 `null` 일 수 있다(`no_price_evidence` 는 면적대를 세우기 전에 떨어진 것이라
어느 면적대인지가 없다). 0 이나 임의 면적으로 채워 표시하지 않는다.

**실측 (2026-07-26 · 운영 데이터, 강남구 11680 · 예산 13.2억)**
단지 조회 50 → 후보 89 → **추천 10 · 제외 83**
(`over_budget` 44 · `below_rank_cutoff` 35 · `no_price_evidence` 4).
제외 83건 전부 `complex_name`·`reason_code` 를 갖고 있었고,
`recommendation_job.result_meta` 에 83건 그대로 저장·조회됐다.

#### 5.3 `total_score` — 사용자 가중치를 **실제로** 반영한다 (2026-07-26 추가)

> **왜 생겼나.** `user_preference.weights`(가격·입지·가치·리스크)는 화면 슬라이더로 받아
> DB 에 **저장만 되고 점수 계산에 전혀 쓰이지 않았다.** 총점은
> `Σ(score×confidence)/Σ(confidence)` — 에이전트 **신뢰도** 가중 평균이라 사용자가
> 슬라이더를 끝에서 끝까지 옮겨도 결과가 한 건도 바뀌지 않았다. 슬라이더가 있으니
> 사용자는 반영된다고 믿는다 — 이 제품이 가장 경계하는 "작동하는 척"이다.
> 정본 구현: `backend/app/agents/scoring.py`.

**축 ↔ 에이전트 ↔ 신호 매핑** (코드 상수 `AXIS_SPECS` 가 정본 · 문서와 같은 내용)

| 축(`weights` 키) | 라벨 | 담당 에이전트 | 점수로 쓰는 신호 | 커버리지 |
|---|---|---|---|---|
| `price` | 가격 | `valuation-trader` | 호가 − 적정가 밴드 중위 갭(`ask_gap_pct`) → `100 − |gap|×5` | full |
| `location` | 입지 | `location-analyst` | 학군(학구도)·역세권·생활 인프라 근접 종합 점수 | full |
| `value` | 가치(시세) | `valuation-trader` | 12개월 거래회전율(`liquidity.turnover_12m_pct`), 5% 이상 만점 | **partial** — 동별 편차(`dong_valuation`)는 "어느 동이 비싼가"라서 후보 점수로 환산하지 않는다 |
| `risk` | 리스크 | `listing-researcher` | 매물 신뢰도(허위·미끼·중복 등록 탐지) | **partial** — 권리관계·근저당·재건축 추가분담금·깡통전세(`risk-auditor`)는 2차 기능이라 들어가지 않는다 |

- `finance-tax-advisor` 는 **어느 축에도 없다.** 예산은 가중치로 조절하는 취향이 아니라
  **하드 제외 조건**이다(못 사는 집은 점수가 높아도 추천이 아니다 → `over_budget`).
- 회전율 만점 기준(5%)은 `stats.liquidity()` 의 '좋음' 경계와 **같은 값**이어야 한다.
  등급 문구("환금성 보통")와 점수가 다른 경계를 쓰면 근거와 순위가 서로 다른 말을 한다.

**계산 규칙**

1. 서버는 저장된 가중치를 **다시 정규화**한다(음수·NaN·모르는 키 제거 후 합 1).
   프론트가 정규화해 보내지만 그건 클라이언트의 주장이고, `PUT /me/preferences` 는
   `dict[str,float]` 를 그대로 받는다. 모르는 키는 버리되 `notes` 에 남긴다.
2. **근거가 있는 축만** 총점에 넣고 나머지 가중치는 **재정규화**한다.
   `total = Σ(wᵢ·scoreᵢ) / Σ(wᵢ)` (i ∈ 근거 있는 축)
   - 근거 없는 축을 **0점으로 계산하지 않는다** — "입지가 나쁘다"는 없는 판정이 생긴다.
   - 조용히 빼지도 않는다 — 아래 고지가 **항상** 함께 나간다.
3. 가중치가 없거나 전부 0 → **기존 동작**(신뢰도 가중 평균)으로 폴백하고
   `score_basis="agent_scores"` + note 로 그 사실을 남긴다.
4. 가중치는 있는데 그 축들에 근거가 **하나도 없으면** `total_score=null`(모름)이다.
   사용자가 0 을 준 축의 점수로 총점을 만들지 않는다 — 그건 사용자의 질문에 대한 답이 아니다.

**응답 필드 (items[])**

| 필드 | 뜻 |
|---|---|
| `total_score` | `null` 이면 **모름**(0 아님) |
| `score_basis` | `user_weighted`(사용자 가중치) \| `agent_scores`(가중치 없어 폴백) \| `null` |
| `score_coverage_pct` | 사용자 가중치 중 실제로 반영된 비율(%). **후보마다 다를 수 있다** — 호가가 있는 후보는 가격·리스크 축이 살아 있고 없는 후보는 죽는다 |
| `score_axes[]` | 축별 `weight` · `applied_weight`(재정규화 후) · `score` · `confidence` · `status` · `missing` · `coverage_gap` |
| `score_notes[]` | 이 후보에서 반영되지 않은 가중치 고지(사람이 읽는 문장) |

`score_axes[].status`: `applied` | `no_signal`(가중치>0인데 근거 없음) |
`zero_weight`(사용자가 0) | `no_weights`(저장된 가중치 자체가 없음)

**고지 규약 (이걸 빼면 재정규화가 거짓말이 된다)**
- 반영되지 못한 축은 **비율과 사유**를 함께 말한다 —
  예: `"입지 가중치 30%가 반영되지 않았습니다 — 학구도 데이터 미확보…"`
- `coverage=partial` 인 축은 **반영 여부와 무관하게** "어디까지만 보는지"를 말한다.
  "호가가 없어 리스크가 반영되지 않았다"로만 끝나면 사용자는 "호가만 들어오면 리스크가
  다 반영된다"고 읽는다 — `risk-auditor` 가 애초에 없다는 사실이 가려진다.
- 같은 내용을 **결과 전체 `notes[]` 와 후보별 `score_notes[]` 양쪽**에 싣는다.
  한쪽에만 있으면 화면 구성에 따라 사용자가 영영 못 보는 경로가 생긴다.

**프론트 계약**
- `score_coverage_pct < 100` 이면 점수 옆에 **부분 반영 표기**를 붙인다. 25% 커버리지 점수와
  100% 커버리지 점수를 같은 강도로 그리면 "확신의 농도" 원칙이 깨진다.
- `score_basis === "agent_scores"` 는 "가중치가 반영된 점수"가 아니다. 그렇게 표시하면 안 된다.

**실측 (2026-07-26 · 운영 데이터, 강남구 11680 · 예산 30억 · 후보 17 · 제외 121)**
운영 DB 상태: `listing` 0행 · `poi`/`school_district`/`road_segment` 0행 · `trade` 611,518행.

| 시나리오 | 1위 | 점수 | `score_basis` | 커버리지 |
|---|---|---|---|---|
| 가중치 미저장 | 대치푸르지오발라드 41.4㎡ | `null` | `null` | – |
| 기본 30/30/25/15 | 역삼I'PARK 28.2㎡ | 62.8 | `user_weighted` | 25% |
| `price` 100% | 대치푸르지오발라드 41.4㎡ | `null` | `null` | 0% |
| `value` 100% | 역삼I'PARK 28.2㎡ | 62.8 | `user_weighted` | 100% |
| `location` 100% | 대치푸르지오발라드 41.4㎡ | `null` | `null` | 0% |

`price 100%` 와 `value 100%` 의 상위 10건은 **구성·순서가 모두 다르다**(측정값).
`price`·`location`·`risk` 100% 는 서로 같다 — 셋 다 근거가 0건이라 점수를 매기지 않고
표본 수 순으로 나열되기 때문이며, 그 사실이 `notes` 에 그대로 적힌다.

#### 5.4 `summary_basis` — 요약을 누가 썼나 (LLM-1 · 2026-07-26 추가)

> **왜 생겼나.** `AnthropicLLM` 은 있었지만 라우터가 러너에 `llm=` 을 넘기지 않아
> 파이프라인은 **항상** `None` 을 받았다. 사용자가 "AI 추천"을 눌러도 실제로는 언제나
> 규칙 기반 요약이었고, 그걸 알 방법이 없었다. 배선을 잇고 **그 상태를 응답에 드러낸다.**

| 값 | 뜻 |
|---|---|
| `"llm"` | Claude 가 쓴 요약 |
| `"fallback"` | 규칙 기반 요약 (키 없음 · 호출 실패 · 스키마 위반 · 비용 상한 · 프롬프트 초과) |

**LLM 은 요약 문장만 만든다.** `total_score`·`price_basis`·`excluded[]`·근거(`findings`)는
전부 규칙·통계 계산이므로 **키 유무와 무관하게 동일**하다. 키가 없다고 추천이 죽지 않는다.

폴백이 생기면 `notes` 에 사유가 실린다:

| 상황 | notes |
|---|---|
| 키 미설정 | `요약 문장은 규칙 기반으로 생성했습니다(AI 미연결 — ANTHROPIC_API_KEY 미설정). 추천 순위·가격 근거·제외 사유는 …무관합니다.` |
| 호출 실패 | `AI 요약 호출이 실패해 N건은 규칙 기반 요약으로 대체했습니다.` |
| 비용 상한 | `비용 상한(추천 1건당 AI 요약 10회)에 걸려 N건은 규칙 기반 요약입니다.` |
| 프롬프트 초과 | `근거가 많아 프롬프트 길이 상한을 넘은 N건은 규칙 기반 요약입니다(근거를 잘라서 요약하지 않습니다).` |

**비용·지연 상한** (`app/agents/orchestrator.py`, `app/agents/llm.py`)

| 항목 | 값 | 근거 |
|---|---|---|
| 요약 호출 시점 | **순위 확정 후 상위 `top_n` 에만** | 후보 61건 중 5건만 응답에 나가는데 61건을 요약하면 56건은 만들자마자 버려진다(서버 실측) |
| 호출 수 상한 | 추천 1건당 **10회** | 기본 `top_n` 과 동일 — 기본 요청은 전부 AI 요약을 받고 큰 `top_n` 만 상한에 걸린다 |
| 연속 실패 차단 | **2회** 실패 후 중단 | 장애는 전면적이다 — 후보 수만큼 타임아웃을 곱하지 않는다 |
| 출력 토큰 | 900 (하드캡 2048) | 요약은 몇 문장이면 된다 |
| 입력 프롬프트 | 20,000자 초과 시 **폐기** | 잘라서 요약하면 근거와 어긋난다(G2). 실측 평균 약 4,000자 |
| HTTP | 타임아웃 30초 · 최대 3회 시도 | 429/5xx/타임아웃만 재시도. **4xx 는 재시도하지 않는다**(같은 답이 온다) |

**⚠️ SR4-2 — 이 경로가 이 제품에서 유일하게 사용자 데이터를 외부로 내보낸다.**
1차 방어는 **구조**다: `AnalysisContext` 는 자산 원본을 담지 않고 `AffordabilityResult`
(파생값)만 가지며, 각 `Finding` 은 한도·부대비용 같은 계산 결과만 싣는다.
2차는 `assert_no_secrets` tripwire — **호출 상한·회로 차단보다 먼저** 돌고, 걸리면
폴백이 아니라 **예외로 막는다**(유출을 정상 동작으로 만들지 않는다).
API 키는 헤더에만 실리며 예외 메시지에는 **상태코드만** 남는다(응답 본문에는 프롬프트가
되비쳐 나올 수 있어 싣지 않는다).

### `GET /recommendations/{job_id}/stream` — SSE **(미구현 · 2차)**
```
event: progress
data: {"done":2,"total":5,"current_agent":"location-analyst"}

event: item
data: {"rank":1,...}

event: done
data: {"item_count":10}
```
> 모바일에서 45초를 빈 화면으로 두면 이탈한다. 완료된 에이전트부터 순차 노출.

---

## 6. 시장 지표 · 정책 (F3)

### `GET /market/index?region_code=&months=24`
```json
{ "items": [ { "as_of": "2026-06-30", "jeonse_ratio": 0.523,
               "unsold_units": 412, "buyer_superiority": 88.4,
               "move_in_supply": 3120, "base_rate": 2.75,
               "source": "한국부동산원" } ] }
```

### `GET /policies?region_code=&active_on=2026-07-24`
```json
{ "items": [ { "id": 12, "title": "...", "category": "대출",
               "effective_from": "2026-06-01", "effective_to": null,
               "source_url": "https://...", "summary": "..." } ] }
```
> `source_url`이 없는 정책은 **응답에 포함하지 않는다**. 출처 없는 규제 정보는 위험하다.

---

## 6.9 관리자 — 가입 승인 (2026-07-26 추가)

> 대상: `app_user.is_admin = true` **이면서** `status = 'approved'` 인 사용자.

### 6.1 인가 규칙 (security.md §2.2 와 같은 강도)
- 권한은 **요청 시점에 서버가 DB 에서** 판정한다(`deps.admin_user`).
  **JWT 에 `admin`·`role`·`status` 클레임을 넣지 않는다** — 토큰에 실린 권한은 클라이언트의
  주장이고, 서명이 유효해도 **강등된 뒤까지 유효**하다. (`admin=true` 를 실은 위조 토큰이
  통하지 않음을 테스트가 고정한다.)
- 승인되지 않은 관리자는 관리자가 아니다(`is_admin AND approved` 동시 충족).

### 6.2 실패 응답 — **404 로 통일한다 (403 이 아니다)**
관리자가 아닌 모든 접근(토큰 없음·만료·일반 사용자·강등된 관리자·잘못된 사용자 id)은
**모르는 경로와 글자까지 동일한 404** 를 받는다.
```json
{ "detail": "Not Found" }
```
| 선택지 | 결과 |
|---|---|
| 403 | "여기 관리 기능이 있다"를 알려준다 → 인증 우회·파라미터 조작의 표적이 된다 |
| **404 (채택)** | 관리자가 아닌 쪽에서는 **존재하지 않는 경로와 구분되지 않는다** |

이 규약은 세 곳에서 함께 지켜져야 성립하며 전부 테스트로 고정돼 있다.
1. 본문 형태를 우리 규약(`{"detail": {"code": ...}}`)이 아니라 FastAPI 기본 404 와 맞춘다.
2. 인증 실패도 401 이 아니라 404 다(비인증 상태에서 401 이 나오면 그 자체가 존재 신호).
3. 메서드 불일치 405 도 404 로 덮는다(`PUT /admin/users` → 405 면 존재가 드러난다).

### 6.3 `GET /admin/users?status=pending&limit=100`
```json
{ "items": [
    { "id": 12, "email": "me@example.com", "status": "pending", "is_admin": false,
      "created_at": "2026-07-26T04:14:36Z",
      "status_changed_at": null, "status_changed_by": null, "status_reason": null }
  ],
  "active_admins": 1 }
```
- `status` 는 `pending|approved|rejected` (생략 시 전체). 오래된 신청이 먼저 온다.
- **비밀번호 해시·자산 금액은 응답에 없다.** 관리자는 가입 승인만 한다.

### 6.4 `POST /admin/users/{user_id}/approve` · `POST /admin/users/{user_id}/reject`
```json
// reject 요청(선택)
{ "reason": "본인 확인 불가" }
// res 200 — 변경된 사용자
{ "id": 12, "email": "...", "status": "approved", "is_admin": false,
  "status_changed_at": "2026-07-26T05:00:00Z", "status_changed_by": 3, "status_reason": null }
```
- `reject` 는 **승인 회수**에도 쓴다(이미 승인된 계정 → `rejected`).
- 거부 사유는 감사 기록으로만 남고 **로그인 응답에는 노출하지 않는다.**
- 모든 변경은 `app_user.status_changed_*` + `user_status_event`(append-only)에 남는다:
  누가(`actor_user_id`), 언제, 어떤 경로로(`actor`: `admin_api` | `cli` | `self`).

### 6.5 마지막 관리자 보호 — 409 `LAST_ADMIN`
승인된 관리자가 **0명이 되는 변경은 거부**한다(자기 자신을 거부/강등하는 경우 포함).
관리자가 없으면 어떤 신규 가입도 승인할 수 없고, 복구하려면 서버 SSH 가 필요하다.
검사는 라우터가 아니라 **리포지토리**가 한다 — API 와 CLI 두 경로 모두를 한 곳에서 막기 위해서다.

### 6.6 첫 관리자(부트스트랩) — API 로는 만들 수 없다
"첫 가입자를 자동 관리자"는 **쓰지 않는다.** 사이트가 이미 공개돼 있어 선점당한다.
관리자 부여는 **서버에서 실행하는 CLI** 로만 한다(SSH 가 있어야 실행된다).
```bash
cd /opt/realestate/backend
python scripts/manage_users.py --list                  # 대기자 확인
python scripts/manage_users.py --approve <email>       # 승인
python scripts/manage_users.py --grant-admin <email>   # 관리자 부여(승인된 계정만)
python scripts/manage_users.py --history <email>       # 감사 이력
```
- 이 CLI 는 **비밀번호를 다루지 않는다**(계정 생성·재설정 기능 없음). 승인만 한다.
- `--grant-admin` 은 승인되지 않은 계정을 거부한다 — 관리자 부여가 승인 절차를 건너뛰는
  뒷문이 되지 않게 한다.

---

## 7. 운영

### `GET /health`
```json
{ "status": "ok", "db": "ok", "redis": "ok",
  "last_ingest": { "trade": "2026-07-24T03:12:00Z", "listing": "2026-07-24T09:00:00Z" } }
```

---

## 8. 요구사항 추적

| 요구 | 엔드포인트 |
|---|---|
| F1 정보 통합 | `GET /map/complexes`, `GET /complexes/{id}`, `POST /recommendations` |
| F2 실구매 가능 금액 | `POST /affordability`, `PUT /me/profile` |
| F3 매수 타이밍 | `GET /market/index`, `GET /policies`, `timing_signal` |
| F4 동·층·타입 편차 | `GET /complexes/{id}/trades?group_by=`, `building.confidence` |
| F5 선호/기피 | `PUT /me/preferences` |
| F6 근거 제시 | `findings[].evidence`, `findings[].risks`, `why_not[]`, **`excluded[]`(§5.2)**, `disclaimer` |

---

## 9. 미확정 (3단계에서 확정)
| # | 쟁점 |
|---|---|
| A1 | 폴링 vs SSE — 모바일 백그라운드 전환 시 SSE 끊김 처리 |
| A2 | `job_id` 형식 (ULID 권장) |
| A3 | 리프레시 토큰 저장 위치 (httpOnly 쿠키 vs 앱 보안저장소) — RN 앱 확장 고려 |
| A4 | 줌 레벨별 군집 경계값(13) — 실데이터로 튜닝 |
