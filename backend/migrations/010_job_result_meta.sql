-- 010_job_result_meta.sql
-- 추천 결과의 **제외 사유(excluded)**·notes 를 담을 자리.
--
-- 왜 필요한가
-- -----------
-- 파이프라인(`run_mvp_pipeline`)은 예전부터 떨어뜨린 후보와 그 사유를 만들어 왔다.
-- 그런데 저장 경로가 `recommendation_item`(=추천된 것) 밖에 없어서, **제외된 후보는
-- 저장되지 못하고 사라졌다.** 그 결과 `GET /recommendations/{job_id}` 응답에 제외 사유가
-- 없었고, 사용자는 자기가 아는 단지가 빠졌을 때 "예산 초과라서"인지 "실거래 표본이
-- 없어서"인지 알 수 없었다. 이 제품의 신뢰는 근거에 있고, **"왜 저건 없는가"도 근거다.**
--
-- 왜 새 컬럼인가 (다른 후보를 왜 버렸는지)
-- ---------------------------------------
--   * `recommendation_item.payload` (005) — **항목 단위**다. 제외된 후보는 항목이 아니다.
--     여기에 끼워 넣으면 rank NULL 행이 `get_job` 의 items 조회에 그대로 딸려 나와,
--     필터 하나만 어긋나도 **제외된 단지가 추천으로 둔갑한다.** 그 사고는 조용히 일어난다.
--   * `recommendation_job.criteria_snapshot` — **입력**의 동결본이다(재현성 근거 · G2).
--     결과를 섞어 쓰면 "무엇으로 돌렸는가"가 오염되고, 재실행 시 입력이 결과에 오염된다.
--   * 정규화 테이블(`recommendation_excluded`) — 제외 사유는 집계·조인 대상이 아니라
--     **그 실행에서 사용자에게 보여줄 문장**이다. 스키마를 늘릴 만큼의 질의 요구가 없다
--     (005 가 payload 로 간 것과 같은 판단: '보여줄 것'은 jsonb, '따질 것'은 컬럼).
-- 그래서 job 한 행에 결과 메타를 붙인다. 마이그레이션 없이 갈 자리가 실제로 없었다.
--
-- 담기는 모양
--   {"excluded": [{"complex_id":…, "complex_name":…, "area_m2":…,
--                  "price_basis":…, "reason_code":…, "reason":"예산 초과 (…)"} …],
--    "notes": ["…"]}
--
-- ⚠️ 이 컬럼은 **평문**이다. 사용자 자산 원본(보유현금·연소득·기존대출)을 절대 넣지 않는다
--    — 자산 3종은 앱단 AES 로 암호화해 보관하는데(security.md §3), 사유 문장으로 새면
--    그 암호화가 무의미해진다. 한도·초과분 같은 **파생값**까지가 허용선이며,
--    러너(`app/agents/recommend.py::_strip_asset_amounts`)가 저장 직전에 한 번 더 거른다.
--
-- 하지 않는 일 (의도적)
--   * 파티션(trade)·자연키(004)·007·008·009 는 건드리지 않는다.
--   * 기존 행은 NULL 로 남는다 — 그 실행에는 제외 사유가 실제로 없었기 때문이다.
--     조회 코드는 NULL 을 빈 목록으로 읽는다(없는 걸 지어내지 않는다).
--
-- 적용: 신규 DB 는 001→…→010 자동. 기존 DB 는 아래로 수동(추가 전용이라 무중단).
--     docker exec -i realestate-db psql -U realestate -d realestate \
--         -v ON_ERROR_STOP=1 -f - < backend/migrations/010_job_result_meta.sql

BEGIN;

ALTER TABLE recommendation_job
    ADD COLUMN IF NOT EXISTS result_meta jsonb;

COMMENT ON COLUMN recommendation_job.result_meta IS
    '실행 결과 메타 JSON. excluded(제외된 후보와 사유)와 notes 를 담는다. '
    'items 는 recommendation_item 에 있고, 여기에는 "추천되지 않은 것"이 들어간다. '
    '⚠️ 평문이므로 사용자 자산 원본 금액을 넣지 않는다(파생값만).';

COMMIT;
