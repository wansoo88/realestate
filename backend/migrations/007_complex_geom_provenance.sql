-- 007_complex_geom_provenance.sql
-- CR-020 GEO-1 (high) — "이 좌표를 왜 믿는가"를 데이터로 남긴다.
--
-- 무엇이 문제였나 (2026-07-26 운영 DB 실측)
-- ----------------------------------------
-- 지오코딩이 카카오 응답 1위를 검증 없이 그대로 저장했다. 결과:
--   * 다른 단지와 좌표가 **완전히 같은 단지 514건(전체 6,538 중 7.9%)**
--   * 그중 **68건은 법정동이 서로 다름** (역삼동/도곡동/서초동 '대우디오빌' 계열 4건이 한 점)
-- 그런데 `complex` 에는 좌표 **출처도 신뢰도도 없어서**, 틀린 좌표와 맞은 좌표를
-- 사후에 구분할 방법이 없었다. 리포트는 `geom_pct 93.6%` 만 보고해 결함을 덮었다.
--
-- 이 마이그레이션이 하는 일
-- -------------------------
--   geom_source     — 좌표를 어디서 얻었나 ('kakao_keyword'). 다른 소스(건축물대장 등)
--                     추가 시 여기서 갈린다.
--   geom_confidence — 어떤 질의로 맞췄나.
--                       'exact'   원본 단지명 그대로 검증 통과
--                       'variant' 지번·동목록을 떼어낸 이름으로 검증 통과(한 단계 덜 확실)
--
-- ⚠️ 값이 NULL 인 geom 은 **검증 이력이 없는 레거시 좌표**다. 신뢰하지 말 것.
--    scripts/geocode_complexes.py --reverify 가 이를 비우고 검증 파이프라인으로 다시 채운다.
--
-- 하지 않는 일 (의도적)
-- ---------------------
--   * 파티션(trade)·자연키(004)는 건드리지 않는다.
--   * geom 자체의 제약은 걸지 않는다 — 좌표가 없는 단지는 정상 상태다
--     ("모르는 걸 모른다고 보여준다"). NOT NULL 을 걸면 오히려 추정 좌표를 부르게 된다.
--
-- 적용: 신규 DB 는 001→…→007 자동. 기존 DB 는 psql -f 로 수동.

BEGIN;

ALTER TABLE complex ADD COLUMN IF NOT EXISTS geom_source text;
ALTER TABLE complex ADD COLUMN IF NOT EXISTS geom_confidence text;

-- 오타로 조용히 이상한 값이 들어가는 걸 막는다. NULL 은 '미검증 레거시'라 허용해야 한다.
ALTER TABLE complex DROP CONSTRAINT IF EXISTS complex_geom_confidence_chk;
ALTER TABLE complex ADD CONSTRAINT complex_geom_confidence_chk
    CHECK (geom_confidence IS NULL OR geom_confidence IN ('exact', 'variant'));

COMMENT ON COLUMN complex.geom_source IS
    '좌표 출처. ''kakao_keyword'' = 카카오 로컬 키워드검색 + 법정동·시군구·단지명 검증 통과. '
    'NULL 이면 검증 이력 없는 레거시 좌표(신뢰 금지).';
COMMENT ON COLUMN complex.geom_confidence IS
    '좌표 신뢰도. ''exact''=원본 단지명으로 검증 통과, ''variant''=지번·동목록 제거 이름으로 통과. '
    'UI 에서 ''variant'' 는 추정 표기 대상(추정치를 확정처럼 보이지 않게).';

-- 미확보·저신뢰 단지를 골라내는 운영 조회용. 전체가 아니라 '문제 있는 쪽'만 색인한다.
CREATE INDEX IF NOT EXISTS complex_geom_confidence_idx
    ON complex (geom_confidence)
    WHERE geom IS NOT NULL AND geom_confidence IS DISTINCT FROM 'exact';

COMMIT;
