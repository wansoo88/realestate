# 데이터 모델 · ERD — 부동산 AI 자문 시스템

> 2단계 설계 산출물 · 2026-07-24 · PostgreSQL 16 + PostGIS
> 입력: `docs/01-interview/requirements.md`, `architecture.md`

---

## 0. ⚠️ 먼저 짚어야 할 도메인 제약 — F4가 그냥은 안 된다

요구사항 **F4(같은 단지도 동·층·타입별 가치 차이)** 는 이 서비스의 차별점인데,
**국토부 실거래가 공개 데이터에는 `동(棟)` 정보가 없다.**

공개되는 필드는 대략 이 수준이다:
> 지역코드 · 단지명 · 전용면적 · **층** · 계약년월일 · 거래금액 · 건축년도 · 해제여부 · 거래유형

즉 **"101동 vs 105동 가격 차이"를 실거래만으로는 직접 계산할 수 없다.**
이 사실을 모르고 설계하면 3단계에서 F4가 통째로 무너진다.

**대응 전략 (스키마에 반영됨)**

| 축 | 데이터 근거 | 가능 여부 |
|---|---|---|
| **층별** 편차 | 실거래 `floor` | ✅ 직접 계산 가능 |
| **타입/면적별** 편차 | 실거래 `area_m2` → `unit_type` 매칭 | ✅ 직접 계산 가능 |
| **동별** 편차 | ① 호가 매물(`listing.building_id`) ② 동 좌표 기반 입지 추정 | ⚠️ **간접 추정** |
| 향·조망 | 동 좌표 + 배치 + POI 거리 | ⚠️ 추정 |

→ `building` 테이블에 **좌표(`geom`)** 를 두고, 역·학교·간선도로와의 거리를 계산해
**"동별 입지 점수"** 로 가치 차이를 **추정**한다. 실거래 기반이 아니므로 **신뢰도를 낮춰 표기**해야 한다.
`agent_finding.confidence`와 `evidence` 컬럼이 그 근거를 남기는 자리다.

> **이건 한계이지 결함이 아니다.** 다만 UI와 리포트에서 "동별 판단은 추정"임을 반드시 밝혀야 한다.
> 확정치처럼 보이게 만들면 G2(근거 감사) 위반이다.

---

## 1. ERD

```mermaid
erDiagram
    REGION ||--o{ COMPLEX : "위치"
    COMPLEX ||--o{ BUILDING : "동"
    COMPLEX ||--o{ UNIT_TYPE : "면적 타입"
    COMPLEX ||--o{ TRADE : "실거래"
    COMPLEX ||--o{ LISTING : "호가 매물"
    COMPLEX ||--o| REDEVELOPMENT : "정비사업"
    BUILDING ||--o{ LISTING : "동 지정(있을 때만)"
    UNIT_TYPE ||--o{ TRADE : "면적 매칭"
    UNIT_TYPE ||--o{ LISTING : "면적 매칭"
    REGION ||--o{ MARKET_INDEX : "시장 지표"
    REGION ||--o{ POLICY_REGION : "규제 적용"
    POLICY ||--o{ POLICY_REGION : "대상 지역"
    SCHOOL_DISTRICT ||--o{ POI : "학교"

    APP_USER ||--|| USER_PROFILE : "자산(암호화)"
    APP_USER ||--o{ USER_PREFERENCE : "선호/기피"
    APP_USER ||--o{ RECOMMENDATION_JOB : "요청"
    RECOMMENDATION_JOB ||--o{ RECOMMENDATION_ITEM : "추천 결과"
    RECOMMENDATION_ITEM ||--o{ AGENT_FINDING : "에이전트별 근거"
    COMPLEX ||--o{ RECOMMENDATION_ITEM : "대상 단지"

    REGION {
        char10 code PK "법정동코드"
        text sido
        text sigungu
        text dong
        geometry geom "MULTIPOLYGON,4326"
    }
    COMPLEX {
        bigint id PK
        char10 region_code FK
        text name "단지명"
        text address_road
        geometry geom "POINT,4326"
        int built_year
        int total_households
        int total_buildings
        numeric floor_area_ratio "용적률"
        numeric building_coverage "건폐율"
        text heating_type
        timestamptz updated_at
    }
    BUILDING {
        bigint id PK
        bigint complex_id FK
        text name "101동"
        geometry geom "POINT,4326 — 동별 추정의 근거"
        int floors
        int households
        smallint direction_deg "향(방위각)"
        text source "좌표 출처"
    }
    UNIT_TYPE {
        bigint id PK
        bigint complex_id FK
        numeric area_m2 "전용면적"
        numeric supply_area_m2 "공급면적"
        text type_name "84A"
        smallint rooms
        smallint baths
    }
    TRADE {
        bigint id PK
        bigint complex_id FK
        bigint unit_type_id FK "면적 매칭(nullable)"
        date contract_date "PARTITION KEY"
        bigint price_krw "거래금액(원)"
        smallint floor "층 — 동은 공개 안 됨"
        numeric area_m2
        boolean is_cancelled "해제여부"
        date registered_at "등기일자"
        text source
        timestamptz ingested_at
    }
    LISTING {
        bigint id PK
        bigint complex_id FK
        bigint building_id FK "동 — 있을 때만"
        bigint unit_type_id FK
        bigint ask_price_krw "호가"
        smallint floor
        text status "active/traded/withdrawn"
        date listed_at
        text source
        timestamptz collected_at
        bigint duplicate_of FK "중복 대표건"
        numeric trust_score "허위/미끼 의심도"
    }
    MARKET_INDEX {
        bigint id PK
        char10 region_code FK
        date as_of "기준일"
        numeric jeonse_ratio "전세가율"
        int unsold_units "미분양"
        numeric buyer_superiority "매수우위지수"
        int move_in_supply "입주물량"
        text source
    }
    POLICY {
        bigint id PK
        text title
        text category "규제지역/대출/세제/공급"
        date effective_from "발효일"
        date effective_to
        text source_url "출처 — 필수"
        text summary
    }
    POLICY_REGION {
        bigint policy_id FK
        char10 region_code FK
    }
    REDEVELOPMENT {
        bigint id PK
        bigint complex_id FK
        text stage "조합설립/사업시행인가/관리처분/착공"
        date stage_date
        bigint est_extra_cost_krw "추가분담금 추정"
        text source_url
    }
    POI {
        bigint id PK
        text category "school/subway/mart/hospital/hazard"
        text name
        geometry geom "POINT,4326"
        jsonb attrs "학업성취도·노선 등"
    }
    SCHOOL_DISTRICT {
        bigint id PK
        bigint school_poi_id FK
        geometry geom "MULTIPOLYGON,4326 — 학구도"
    }

    APP_USER {
        bigint id PK
        citext email UK
        text password_hash "argon2id"
        timestamptz created_at
    }
    USER_PROFILE {
        bigint user_id PK-FK
        bytea cash_krw_enc "🔐 보유현금"
        bytea income_krw_enc "🔐 연소득"
        bytea existing_loan_krw_enc "🔐 기존대출"
        smallint owned_houses "보유주택수"
        smallint household_size
        timestamptz updated_at
    }
    USER_PREFERENCE {
        bigint id PK
        bigint user_id FK
        jsonb prefer "선호: 학군/역세권/신축/대단지"
        jsonb avoid "기피: 1층/대로변/재건축리스크"
        jsonb weights "가중치"
    }
    RECOMMENDATION_JOB {
        bigint id PK
        bigint user_id FK
        jsonb criteria_snapshot "요청 시점 조건 동결"
        text status "queued/running/done/failed"
        timestamptz created_at
        timestamptz completed_at
    }
    RECOMMENDATION_ITEM {
        bigint id PK
        bigint job_id FK
        bigint complex_id FK
        bigint building_id FK "추정 — nullable"
        bigint unit_type_id FK
        smallint rank
        numeric total_score
        bigint est_price_krw "적정가 추정"
        text timing_signal "매수/관망/회피"
    }
    AGENT_FINDING {
        bigint id PK
        bigint item_id FK
        text agent_id "listing-researcher 등 8종"
        numeric score
        text verdict "판정"
        text rationale "근거 문장"
        jsonb evidence "출처+기준일자 — G2 감사 대상"
        numeric confidence "0~1"
    }
```

---

## 2. 설계 원칙 (왜 이렇게 나눴나)

### P1. 단지 → 동 → 타입 3계층 분리
F4 대응의 뼈대. 하나의 `unit` 테이블에 다 넣으면 동별·타입별 집계가 전부 풀스캔이 된다.
`unit`(개별 호실) 테이블은 **만들지 않는다** — 실거래에 호수가 없어 채울 데이터가 없다.

### P2. 실거래(`TRADE`)와 호가(`LISTING`)를 절대 섞지 않는다
신뢰도가 다른 데이터다. 실거래는 **확정된 과거**(단 최대 30일 신고 지연),
호가는 **희망 가격**(허위·미끼 포함 가능). 한 테이블에 넣고 `type` 컬럼으로 구분하는 순간
평균가 계산에서 둘이 섞여 근거가 오염된다.

### P3. 모든 수집 데이터에 `source` + `ingested_at`/`collected_at`
G2(근거 감사)의 물리적 기반. "이 숫자 어디서 왔냐"에 답할 수 없으면 추천 근거가 성립하지 않는다.

### P4. 자산 정보는 `bytea` 암호화 컬럼
`USER_PROFILE`의 금액 3종은 평문으로 두지 않는다. 상세 방식은 `security.md` 참조.
`owned_houses`·`household_size`는 세금 계산에 필요하고 식별성이 낮아 평문 유지.

### P5. `AGENT_FINDING.evidence`는 JSONB 필수
```json
{ "claim": "취득세 1.1%", "source": "지방세법 §11", "as_of": "2026-07-24",
  "verifier": "wetax", "data_rows": [12345, 12346] }
```
출처·기준일자 없는 finding은 `re-review`가 반려한다(G2).

---

## 3. 인덱스 · 파티셔닝 전략

### 3.1 공간 인덱스 (성능의 핵심)
```sql
CREATE INDEX idx_complex_geom  ON complex  USING GIST (geom);
CREATE INDEX idx_building_geom ON building USING GIST (geom);
CREATE INDEX idx_poi_geom      ON poi      USING GIST (geom);
CREATE INDEX idx_region_geom   ON region   USING GIST (geom);
CREATE INDEX idx_school_geom   ON school_district USING GIST (geom);
```
지도 화면 범위 조회:
```sql
SELECT c.id, c.name, c.geom
FROM complex c
WHERE c.geom && ST_MakeEnvelope(:minx,:miny,:maxx,:maxy, 4326);   -- && 가 GiST 를 탄다
```
> `ST_Intersects` 대신 `&&`(bounding box) 를 먼저 태우고 필요 시 정밀 판정을 얹는다.

### 3.2 실거래 파티셔닝
```sql
CREATE TABLE trade (...) PARTITION BY RANGE (contract_date);
CREATE TABLE trade_2026 PARTITION OF trade
  FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
```
- 추정 200~300만 행, 매년 증가. **"최근 6개월 시세"** 조회가 가장 잦아 연도 파티션이 잘 맞는다.
- 파티션별 인덱스: `(complex_id, contract_date DESC)`, `(complex_id, area_m2, floor)`

### 3.3 그 외
| 테이블 | 인덱스 | 용도 |
|---|---|---|
| `listing` | `(complex_id, status)` where `status='active'` (부분 인덱스) | 현재 매물만 조회 |
| `listing` | `(duplicate_of)` | 중복 대표건 조회 |
| `market_index` | `(region_code, as_of DESC)` | 최신 지표 |
| `policy_region` | `(region_code, policy_id)` | 지역별 규제 |
| `agent_finding` | `(item_id, agent_id)` | 리포트 렌더링 |
| `complex` | `(region_code, name)` | 단지 검색 |

---

## 4. 중복 매물 처리 (호가 데이터의 최대 골칫거리)

같은 물건이 여러 중개사에 올라온다. 중복을 안 지우면 "매물 100건"이 실제로는 12건이다.

**중복 판정 키(제안)**: `complex_id` + `area_m2` + `floor` + `ask_price_krw`(±1% 허용) + 활성 기간 겹침
- 대표건 하나를 남기고 나머지는 `duplicate_of`로 연결 (**삭제하지 않는다** — 중개사 수 자체가
  "많이 나온 매물 = 안 팔리는 물건" 신호가 된다)
- `trust_score`: 시세 대비 비정상 저가, 장기 미거래, 중복 과다 → 허위·미끼 의심도

---

## 5. 결정 대기 항목

| # | 쟁점 | 선택지 | 결정 시점 |
|---|---|---|---|
| ~~Q1~~ | ~~자산 컬럼 암호화 방식~~ | **✅ 결정: 앱단 AES-256-GCM** (pgcrypto 탈락 — 키가 SQL 문에 실려 쿼리 로그에 남는다). AAD에 `user_id`+필드명 바인딩 | `security.md` §3.1 |
| Q2 | `geom` 타입 | `geometry(4326)` + 거리계산 시 캐스팅 vs `geography` | 수집 1차 후 실측 |
| Q3 | 동 좌표 확보 방법 | 건축물대장 vs 지도 API vs 수기 | `re-data` 조사 필요 |
| Q4 | 실거래-타입 매칭 | 전용면적 정확 일치 vs 허용오차 | 실데이터 확인 후 |

---

## 6. 다음
- `schema.dbml` — 동일 모델의 DBML 표현 (dbdiagram.io 에서 시각화)
- `api-spec.md` — 이 모델 위의 API 계약
- `security.md` — Q1 암호화 방식 확정
