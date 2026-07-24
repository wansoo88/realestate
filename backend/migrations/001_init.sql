-- 001_init.sql — 초기 스키마
-- 설계: docs/02-design/erd.md · docs/02-design/schema.dbml
-- ⚠️ 이 파일은 로컬에 Docker 가 없어 **실제 DB 에서 미검증**이다 (implementation-plan.md §0).
--    첫 배포 시 반드시 빈 DB 에 적용해 검증할 것.

BEGIN;

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS citext;

--==========================================================================
-- 공간 · 마스터
--==========================================================================

CREATE TABLE region (
    code        char(10) PRIMARY KEY,               -- 법정동코드
    sido        text NOT NULL,
    sigungu     text,
    dong        text,
    geom        geometry(MultiPolygon, 4326)
);
CREATE INDEX idx_region_geom ON region USING GIST (geom);

CREATE TABLE complex (
    id                bigserial PRIMARY KEY,
    region_code       char(10) REFERENCES region(code),
    name              text NOT NULL,
    address_road      text,
    address_jibun     text,
    geom              geometry(Point, 4326),
    built_year        int,
    total_households  int,
    total_buildings   int,
    floor_area_ratio  numeric(6,2),                 -- 용적률
    building_coverage numeric(6,2),                 -- 건폐율
    heating_type      text,
    source            text,
    updated_at        timestamptz DEFAULT now()
);
CREATE INDEX idx_complex_geom   ON complex USING GIST (geom);
CREATE INDEX idx_complex_region ON complex (region_code, name);

-- 동(棟). 실거래에는 동 정보가 없으므로 이 좌표가 동별 가치 추정의 유일한 근거다.
CREATE TABLE building (
    id            bigserial PRIMARY KEY,
    complex_id    bigint NOT NULL REFERENCES complex(id) ON DELETE CASCADE,
    name          text,                             -- '101동'
    geom          geometry(Point, 4326),
    floors        int,
    households    int,
    direction_deg smallint CHECK (direction_deg BETWEEN 0 AND 359),
    source        text,
    UNIQUE (complex_id, name)
);
CREATE INDEX idx_building_geom    ON building USING GIST (geom);
CREATE INDEX idx_building_complex ON building (complex_id);

CREATE TABLE unit_type (
    id             bigserial PRIMARY KEY,
    complex_id     bigint NOT NULL REFERENCES complex(id) ON DELETE CASCADE,
    area_m2        numeric(8,4) NOT NULL,           -- 전용면적
    supply_area_m2 numeric(8,4),
    type_name      text,
    rooms          smallint,
    baths          smallint,
    UNIQUE (complex_id, area_m2, type_name)
);
CREATE INDEX idx_unit_type_complex ON unit_type (complex_id, area_m2);

--==========================================================================
-- 거래 · 시세
--==========================================================================

-- 실거래: 확정된 과거 거래. 신고 지연 최대 30일.
-- 호가(listing)와 절대 섞지 않는다 — 신뢰도가 다른 데이터다.
CREATE TABLE trade (
    id            bigserial,
    complex_id    bigint NOT NULL REFERENCES complex(id),
    unit_type_id  bigint REFERENCES unit_type(id),  -- 면적 매칭 실패 시 NULL
    contract_date date   NOT NULL,
    price_krw     bigint NOT NULL CHECK (price_krw > 0),
    floor         smallint,                         -- 동(棟)은 공개되지 않음
    area_m2       numeric(8,4),
    is_cancelled  boolean NOT NULL DEFAULT false,   -- 해제여부: 통계에서 제외
    registered_at date,
    trade_type    text,
    source        text NOT NULL,
    ingested_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, contract_date)
) PARTITION BY RANGE (contract_date);

-- 파티션. 운영 중 연 1회 추가한다(5단계 모니터링에서 누락 경보).
CREATE TABLE trade_2016 PARTITION OF trade FOR VALUES FROM ('2016-01-01') TO ('2017-01-01');
CREATE TABLE trade_2017 PARTITION OF trade FOR VALUES FROM ('2017-01-01') TO ('2018-01-01');
CREATE TABLE trade_2018 PARTITION OF trade FOR VALUES FROM ('2018-01-01') TO ('2019-01-01');
CREATE TABLE trade_2019 PARTITION OF trade FOR VALUES FROM ('2019-01-01') TO ('2020-01-01');
CREATE TABLE trade_2020 PARTITION OF trade FOR VALUES FROM ('2020-01-01') TO ('2021-01-01');
CREATE TABLE trade_2021 PARTITION OF trade FOR VALUES FROM ('2021-01-01') TO ('2022-01-01');
CREATE TABLE trade_2022 PARTITION OF trade FOR VALUES FROM ('2022-01-01') TO ('2023-01-01');
CREATE TABLE trade_2023 PARTITION OF trade FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');
CREATE TABLE trade_2024 PARTITION OF trade FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
CREATE TABLE trade_2025 PARTITION OF trade FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
CREATE TABLE trade_2026 PARTITION OF trade FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE TABLE trade_2027 PARTITION OF trade FOR VALUES FROM ('2027-01-01') TO ('2028-01-01');
-- 범위 밖 유입을 조용히 잃지 않도록 기본 파티션을 둔다.
CREATE TABLE trade_default PARTITION OF trade DEFAULT;

CREATE INDEX idx_trade_complex_date ON trade (complex_id, contract_date DESC);
CREATE INDEX idx_trade_lookup       ON trade (complex_id, area_m2, floor);

-- 호가: 희망 가격. 허위·미끼 포함 가능.
CREATE TABLE listing (
    id            bigserial PRIMARY KEY,
    complex_id    bigint NOT NULL REFERENCES complex(id),
    building_id   bigint REFERENCES building(id),   -- 동이 표기된 매물만
    unit_type_id  bigint REFERENCES unit_type(id),
    ask_price_krw bigint NOT NULL CHECK (ask_price_krw > 0),
    floor         smallint,
    area_m2       numeric(8,4),
    status        text NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','traded','withdrawn')),
    listed_at     date,
    agency        text,
    source        text NOT NULL,
    collected_at  timestamptz NOT NULL DEFAULT now(),
    duplicate_of  bigint REFERENCES listing(id),    -- 대표건 연결(삭제하지 않는다)
    trust_score   numeric(4,3) CHECK (trust_score BETWEEN 0 AND 1)
);
CREATE INDEX idx_listing_active ON listing (complex_id) WHERE status = 'active';
CREATE INDEX idx_listing_dup    ON listing (duplicate_of);

CREATE TABLE market_index (
    id                bigserial PRIMARY KEY,
    region_code       char(10) REFERENCES region(code),
    as_of             date NOT NULL,
    jeonse_ratio      numeric(6,3),
    unsold_units      int,
    buyer_superiority numeric(6,2),
    move_in_supply    int,
    base_rate         numeric(5,3),
    source            text NOT NULL,
    UNIQUE (region_code, as_of, source)
);
CREATE INDEX idx_market_region ON market_index (region_code, as_of DESC);

--==========================================================================
-- 정책 · 정비사업
--==========================================================================

-- 출처와 발효일이 없는 정책은 저장하지 않는다 (G2).
CREATE TABLE policy (
    id             bigserial PRIMARY KEY,
    title          text NOT NULL,
    category       text CHECK (category IN ('규제지역','대출','세제','공급','정비사업')),
    effective_from date NOT NULL,
    effective_to   date,
    source_url     text NOT NULL,
    summary        text,
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE policy_region (
    policy_id   bigint REFERENCES policy(id) ON DELETE CASCADE,
    region_code char(10) REFERENCES region(code),
    PRIMARY KEY (region_code, policy_id)
);

CREATE TABLE redevelopment (
    id                 bigserial PRIMARY KEY,
    complex_id         bigint NOT NULL REFERENCES complex(id) ON DELETE CASCADE,
    stage              text,
    stage_date         date,
    est_extra_cost_krw bigint,        -- 추정치. 확정치처럼 표기 금지.
    source_url         text
);
CREATE INDEX idx_redev_complex ON redevelopment (complex_id);

--==========================================================================
-- 입지
--==========================================================================

CREATE TABLE poi (
    id       bigserial PRIMARY KEY,
    category text NOT NULL,          -- school/subway/mart/hospital/park/hazard/road
    name     text,
    geom     geometry(Point, 4326),
    attrs    jsonb NOT NULL DEFAULT '{}'::jsonb,
    source   text
);
CREATE INDEX idx_poi_geom     ON poi USING GIST (geom);
CREATE INDEX idx_poi_category ON poi (category);

CREATE TABLE school_district (
    id            bigserial PRIMARY KEY,
    school_poi_id bigint REFERENCES poi(id),
    geom          geometry(MultiPolygon, 4326),
    source        text
);
CREATE INDEX idx_school_district_geom ON school_district USING GIST (geom);

CREATE TABLE transit_plan (
    id            bigserial PRIMARY KEY,
    name          text NOT NULL,
    geom          geometry(Geometry, 4326),
    open_expected date,
    status        text CHECK (status IN ('계획','착공','개통')),
    source_url    text
);
CREATE INDEX idx_transit_geom ON transit_plan USING GIST (geom);

--==========================================================================
-- 사용자 (민감)
--==========================================================================

CREATE TABLE app_user (
    id            bigserial PRIMARY KEY,
    email         citext UNIQUE NOT NULL,
    password_hash text NOT NULL,                    -- argon2id
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- 🔐 금액 3종은 앱단 AES-256-GCM 암호문(bytea)만 저장한다.
--    평문 컬럼을 추가하지 말 것 (security.md §3.1, G3).
CREATE TABLE user_profile (
    user_id               bigint PRIMARY KEY REFERENCES app_user(id) ON DELETE CASCADE,
    cash_krw_enc          bytea,
    income_krw_enc        bytea,
    existing_loan_krw_enc bytea,
    owned_houses          smallint NOT NULL DEFAULT 0,
    household_size        smallint,
    updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_preference (
    id      bigserial PRIMARY KEY,
    user_id bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    prefer  jsonb NOT NULL DEFAULT '{}'::jsonb,
    avoid   jsonb NOT NULL DEFAULT '{}'::jsonb,
    weights jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_pref_user ON user_preference (user_id);

--==========================================================================
-- 분석 결과
--==========================================================================

CREATE TABLE recommendation_job (
    id                text PRIMARY KEY,             -- ULID
    user_id           bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    criteria_snapshot jsonb NOT NULL,               -- 재현성(G2)
    status            text NOT NULL DEFAULT 'queued'
                      CHECK (status IN ('queued','running','done','failed')),
    created_at        timestamptz NOT NULL DEFAULT now(),
    completed_at      timestamptz
);
CREATE INDEX idx_job_user ON recommendation_job (user_id, created_at DESC);

CREATE TABLE recommendation_item (
    id            bigserial PRIMARY KEY,
    job_id        text NOT NULL REFERENCES recommendation_job(id) ON DELETE CASCADE,
    complex_id    bigint NOT NULL REFERENCES complex(id),
    building_id   bigint REFERENCES building(id),   -- 동 추천은 추정 → NULL 허용
    unit_type_id  bigint REFERENCES unit_type(id),
    rank          smallint,
    total_score   numeric(6,3),
    est_price_krw bigint,
    timing_signal text
);
CREATE INDEX idx_item_job ON recommendation_item (job_id, rank);

-- evidence 가 비어 있으면 저장하지 않는다 — 출처 없는 근거는 제품이 아니다(G2).
CREATE TABLE agent_finding (
    id         bigserial PRIMARY KEY,
    item_id    bigint NOT NULL REFERENCES recommendation_item(id) ON DELETE CASCADE,
    agent_id   text NOT NULL,
    score      numeric(6,3),
    verdict    text,
    rationale  text,
    evidence   jsonb NOT NULL CHECK (jsonb_array_length(evidence) > 0),
    confidence numeric(4,3) CHECK (confidence BETWEEN 0 AND 1)
);
CREATE INDEX idx_finding_item ON agent_finding (item_id, agent_id);

--==========================================================================
-- 운영
--==========================================================================

-- 수집 실패를 조용히 넘기지 않기 위한 원장. 0건 연속 시 경보(5단계).
CREATE TABLE ingest_log (
    id           bigserial PRIMARY KEY,
    source       text NOT NULL,
    target_table text,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    rows_ok      int NOT NULL DEFAULT 0,
    rows_failed  int NOT NULL DEFAULT 0,
    status       text CHECK (status IN ('ok','partial','failed')),
    message      text
);
CREATE INDEX idx_ingest_log_source ON ingest_log (source, started_at DESC);

COMMIT;
