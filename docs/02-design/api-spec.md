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
| 404 | `NOT_FOUND` | 대상 없음 |
| 409 | `JOB_IN_PROGRESS` | 동일 조건 분석이 이미 실행 중 |
| 422 | `INSUFFICIENT_DATA` | **데이터 부족으로 판단 보류** (추정하지 않고 명시적으로 거부) |
| 429 | `RATE_LIMITED` | 호출 제한 |
| 503 | `UPSTREAM_UNAVAILABLE` | 공공API/Claude API 장애 |

> `422 INSUFFICIENT_DATA`는 이 서비스에서 **정상 동작**이다. 데이터가 없으면 지어내지 않는다.

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
```json
// req
{ "email": "me@example.com", "password": "..." }
// res 201
{ "user_id": 1 }
```
| 코드 | 의미 |
|---|---|
| 409 `EMAIL_TAKEN` | 이미 가입된 이메일 |
| 422 | 비밀번호 12자 미만 등 형식 오류 |

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

---

## 3. 실구매 가능 금액 (F2 · 동기 · 규칙 계산)

### `POST /affordability`
**LLM을 쓰지 않는다.** 세법·대출 규제 기반 결정론적 계산.

```json
// req (생략 시 저장된 프로필 사용)
{ "target_region_code": "1168000000", "purpose": "live" }   // live | invest

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

---

## 4. 지도 · 매물 조회 (F1)

### `GET /map/complexes` — 화면 범위 내 단지
목표 응답 **1초 이내**. 지도를 움직일 때마다 호출된다.

| 파라미터 | 예 | 설명 |
|---|---|---|
| `bbox` | `126.9,37.5,127.1,37.6` | minLon,minLat,maxLon,maxLat |
| `zoom` | `14` | **줌에 따라 반환 단위가 바뀐다** |
| `max_price_krw` | `850000000` | `/affordability` 결과 연동 |
| `area_min_m2` / `area_max_m2` | `59` / `85` | |
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
  "purpose": "live",
  "budget_override_krw": null,        // null 이면 /affordability 결과 사용
  "agents": ["listing-researcher","finance-tax-advisor","valuation-trader",
             "location-analyst","portfolio-advisor"],   // 생략 시 MVP 5종
  "top_n": 10 }

// res 202
{ "job_id": "rec_01J...", "status": "queued",
  "estimated_seconds": 45,
  "poll_url": "/api/v1/recommendations/rec_01J...",
  "stream_url": "/api/v1/recommendations/rec_01J.../stream" }
```

### `GET /recommendations/{job_id}` — 결과 폴링
```json
// 진행 중
{ "status": "running", "progress": { "done": 3, "total": 5,
  "current_agent": "valuation-trader" } }

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
      "timing_signal": "buy",
      "summary": "예산 8.5억 내, 전세가율 하락 구간 진입 전 매수 유리.",
      "findings": [
        { "agent_id": "finance-tax-advisor", "score": 88, "verdict": "적합",
          "rationale": "취득세 포함 총 필요자금 8.42억으로 한도 내.",
          "evidence": { "claim": "취득세 1.1%", "source": "지방세법 §11",
                        "as_of": "2026-07-24" },
          "confidence": 0.95 },
        { "agent_id": "valuation-trader", "score": 76, "verdict": "적정가 하단",
          "rationale": "최근 6개월 동일 타입 중위 14.0억 대비 호가 14.8억은 상단.",
          "evidence": { "data_rows": 37, "period": "2026-01~2026-06" },
          "confidence": 0.80 }
      ],
      "risks": [
        { "agent_id": "risk-auditor", "severity": "medium",
          "detail": "용적률 249%로 재건축 사업성 낮음." }
      ] } ],
  "disclaimer": "투자 권유가 아니며 개인 판단을 돕는 참고 자료입니다." }
```

**응답 설계 원칙**
1. `findings`와 `risks`를 **분리**해 항상 함께 반환 — 장점만 나열하면 G2 위반
2. 모든 finding에 `evidence` + `confidence`
3. `dong_valuation.basis`/`confidence`로 **동별이 실측(trade_measured)인지 추정(listing_reported)인지 구조적으로 구분**. `building`은 특정 매물의 동 표기(호가 기준), `dong_valuation`은 단지 내 동별 실거래 편차(F4).
4. `criteria_snapshot`으로 재현성 확보
5. `price_basis`로 **호가인지 실거래 추정인지 구조적으로 구분**(아래 §5.1)

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

### `GET /recommendations/{job_id}/stream` — SSE
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
| F6 근거 제시 | `findings[].evidence`, `risks[]`, `disclaimer` |

---

## 9. 미확정 (3단계에서 확정)
| # | 쟁점 |
|---|---|
| A1 | 폴링 vs SSE — 모바일 백그라운드 전환 시 SSE 끊김 처리 |
| A2 | `job_id` 형식 (ULID 권장) |
| A3 | 리프레시 토큰 저장 위치 (httpOnly 쿠키 vs 앱 보안저장소) — RN 앱 확장 고려 |
| A4 | 줌 레벨별 군집 경계값(13) — 실데이터로 튜닝 |
