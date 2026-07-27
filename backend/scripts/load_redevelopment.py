"""정비사업 추진현황 수집 → `redev_project` 적재 → 단지 매칭 → **리포트**.

사용
----
    export DATABASE_URL=postgresql+psycopg://user:pw@host:5432/realestate
    python scripts/load_redevelopment.py                     # 서울 + 인천 내려받아 적재
    python scripts/load_redevelopment.py --dry-run           # 내려받아 파싱만(DB 미변경)
    python scripts/load_redevelopment.py --seoul-file a.csv --incheon-file b.csv
    python scripts/load_redevelopment.py --only seoul

규모 (2026-07-27 실측 — 대량 수집 컨펌 대상 아님)
-------------------------------------------------
HTTP 요청 **2건**(서울 CSV 1 + 인천 CSV 1), 합계 약 115KB, 수 초. 적재 행 616.
디스크 증가는 1MB 미만이다. 국토부 실거래 수집처럼 수천 요청이 나가는 작업이 아니다.

이 스크립트가 **하지 않는** 것
------------------------------
* 이름 유사도 매칭 — 하지 않는다. 대표지번(법정동코드·본번·부번) 정확일치뿐이다.
* 추가분담금 추정 — 애초에 담을 칸이 없다(migration 014 가 옛 칸을 NULL 로 잠갔다).
* 조용한 유실 — 파싱 실패 행도 사유와 함께 적재하고, 리포트가 사유별 건수를 낸다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    capped_get,
    database_url,
    load_env,
    make_engine,
    safe_dsn,
)

from app.ingest.redevelopment import (  # noqa: E402
    DONG_ADMIN_STRIPPED,
    SOURCE_INCHEON,
    SOURCE_SEOUL,
    STATUS_OK,
    RedevRecord,
    build_dong_index,
    decode_csv,
    parse_incheon_csv,
    parse_seoul_csv,
)
from app.domain.redevelopment.analysis import money_like_tokens  # noqa: E402
from app.domain.redevelopment.models import MATCH_PNU_ADMIN_DONG, MATCH_PNU_EXACT  # noqa: E402
from app.domain.redevelopment.stages import STAGE_UNKNOWN  # noqa: E402

logger = logging.getLogger("load_redevelopment")

#: 서울 열린데이터광장 시트 CSV 내려받기(로그인·인증키 **불필요**, https).
#:
#: ⚠️ 인증키 경로는 **의도적으로 없다** (SR24-1, 2026-07-27).
#:    예전에는 `SEOUL_OPENAPI_KEY` 가 있으면 `http://openapi.seoul.go.kr:8088/{key}/…` 를
#:    우선 썼는데, 그 형태는 결함이 셋이었다 — ① 평문 HTTP(TLS 없음, CWE-319)
#:    ② 키가 쿼리스트링이 아니라 **URL 경로 세그먼트**라 프록시·중계 로그에 원형으로 남고
#:    (CWE-598) `masking.py` 의 `key=value` 매칭이 구조적으로 못 잡음
#:    ③ `raise_for_status()` 예외 문자열이 그 URL 을 통째로 뱉음(CWE-532).
#:    발화 조건이 공격이 아니라 **아무 non-2xx 응답**이라 잠복이 아니라 예약이었다.
#:    마스킹을 덧대는 대신 경로를 지웠다 — **안 쓰는 비밀 경로가 없는 것이 가장 강한 방어다.**
#:    같은 데이터셋(OA-22856)을 무키 CSV 로 받아 616행을 실제 적재했으므로 잃은 기능은 없다.
SEOUL_CSV_URL = "https://datafile.seoul.go.kr/bigfile/iot/sheet/csv/download.do"
SEOUL_DATASET_ID = "OA-22856"
SEOUL_PAGE = "https://data.seoul.go.kr/dataList/OA-22856/S/1/datasetView.do"

#: 인천 CSV(공공데이터포털 파일데이터 15055212). 파일 ID 가 갱신되면 여기만 고친다.
INCHEON_CSV_URL = (
    "https://www.data.go.kr/cmm/cmm/fileDownload.do"
    "?atchFileId=FILE_000000003675032&fileDetailSn=1&insertDataPrcus=N"
)
INCHEON_REFERER = "https://www.data.go.kr/data/15055212/fileData.do"

#: 한 필지(법정동코드·본번·부번)에서 이만큼을 넘는 단지가 나오면 **매칭하지 않는다.**
#: 실측상 필지 13,449개는 단지 1곳, 151개가 2~6곳이다. 6곳까지 붙는 필지는 자료 품질
#: 문제일 가능성이 높아, 전부 이어 붙이는 대신 사유를 남기고 보류한다.
MAX_COMPLEXES_PER_PARCEL = 3

_REGION_SQL = """
    SELECT code, sido, sigungu, dong
      FROM region
     WHERE dong IS NOT NULL
       AND (code LIKE '11%' OR code LIKE '28%' OR code LIKE '41%')
"""

_UPSERT = """
    INSERT INTO redev_project (
        source, source_key, source_url, sido, sigungu, zone_name,
        raw_stage, stage, raw_biz_type, biz_type,
        address_jibun_raw, parse_status, parse_detail,
        legal_dong_code, main_no, sub_no, is_mountain, dong_match, dong_scope,
        zone_designated_on, committee_on, association_on, design_review_on,
        implementation_on, disposition_on, relocation_start_on, relocation_end_on,
        construction_start_on, existing_households, planned_households, as_of, loaded_at)
    VALUES (
        :source, :source_key, :source_url, :sido, :sigungu, :zone_name,
        :raw_stage, :stage, :raw_biz_type, :biz_type,
        :address_jibun_raw, :parse_status, :parse_detail,
        :legal_dong_code, :main_no, :sub_no, :is_mountain, :dong_match, :dong_scope,
        :zone_designated_on, :committee_on, :association_on, :design_review_on,
        :implementation_on, :disposition_on, :relocation_start_on, :relocation_end_on,
        :construction_start_on, :existing_households, :planned_households, :as_of, now())
    ON CONFLICT (source, source_key) DO UPDATE SET
        source_url = EXCLUDED.source_url,
        sido = EXCLUDED.sido, sigungu = EXCLUDED.sigungu,
        zone_name = EXCLUDED.zone_name,
        raw_stage = EXCLUDED.raw_stage, stage = EXCLUDED.stage,
        raw_biz_type = EXCLUDED.raw_biz_type, biz_type = EXCLUDED.biz_type,
        address_jibun_raw = EXCLUDED.address_jibun_raw,
        parse_status = EXCLUDED.parse_status, parse_detail = EXCLUDED.parse_detail,
        legal_dong_code = EXCLUDED.legal_dong_code,
        main_no = EXCLUDED.main_no, sub_no = EXCLUDED.sub_no,
        is_mountain = EXCLUDED.is_mountain,
        dong_match = EXCLUDED.dong_match, dong_scope = EXCLUDED.dong_scope,
        zone_designated_on = EXCLUDED.zone_designated_on,
        committee_on = EXCLUDED.committee_on,
        association_on = EXCLUDED.association_on,
        design_review_on = EXCLUDED.design_review_on,
        implementation_on = EXCLUDED.implementation_on,
        disposition_on = EXCLUDED.disposition_on,
        relocation_start_on = EXCLUDED.relocation_start_on,
        relocation_end_on = EXCLUDED.relocation_end_on,
        construction_start_on = EXCLUDED.construction_start_on,
        existing_households = EXCLUDED.existing_households,
        planned_households = EXCLUDED.planned_households,
        as_of = EXCLUDED.as_of, loaded_at = now()
    RETURNING id
"""

#: 매칭 후보. **부동산원 필지와 완전일치**만 본다(이름은 쳐다보지 않는다).
_MATCH_SQL = """
    SELECT c.id, c.name, c.built_year
      FROM complex c
      JOIN reb_complex r ON r.reb_complex_id = c.reb_complex_id
     WHERE r.legal_dong_code = :dong
       AND r.main_no = :main
       AND r.sub_no = :sub
       AND r.is_mountain = :mtn
     ORDER BY c.id
"""


#: CSV 로 인정하기 위해 헤더에 있어야 하는 컬럼(공백 제거 후 대조).
#: 없으면 **저장·파싱하지 않는다** — 아래 `check_payload` 참조.
SEOUL_REQUIRED_COLUMNS = ("자치구", "구역명", "지번주소", "사업추진단계")
INCHEON_REQUIRED_COLUMNS = ("구명", "구역명", "위치", "진행단계")


def fetch(url: str, *, referer: str | None = None, data: dict | None = None,
          what: str = "응답") -> bytes:
    """상한이 걸린 다운로드. `_common.capped_get` 을 쓴다(SR24-2).

    ⚠️ `resp.content` 를 그냥 돌려주지 않는다 — 그러면 상한이 걸리기 전에 본문 전체가
       메모리에 올라가고, 상한은 사후 확인이라 의미가 없다.
    """
    import httpx

    headers = {"User-Agent": "pjt13-realestate/1.0 (personal, non-commercial)"}
    if referer:
        headers["Referer"] = referer
    with httpx.Client(timeout=120, follow_redirects=True, headers=headers) as client:
        if data:
            return capped_get(client, url, method="POST", data=data, what=what)
        return capped_get(client, url, what=what)


def check_payload(raw: bytes, *, required_columns: tuple[str, ...], what: str,
                  page: str) -> str:
    """받은 게 **정말 그 CSV 인지** 확인한다. 아니면 파싱하지 않는다 (SR24-2).

    왜 필요한가 — 포털이 오류 HTML 을 200 으로 돌려주는 일이 실제로 있다. HTML 은
    유효한 UTF-8 이라 `decode_csv` 가 성공하고, `csv.DictReader` 가 HTML 각 줄을
    '행'으로 만든다. 그러면 `if not records` 가드를 **통과하고**(행이 0건이 아니므로)
    모든 필드가 빈 문자열인 쓰레기 1행이 `redev_project` 에 UPSERT 된다.
    실패가 실패로 보이지 않는 형태이므로 여기서 막는다.
    """
    try:
        text = decode_csv(raw)
    except ValueError:
        preview = raw[:200].decode("utf-8", "replace")
        raise SystemExit(
            f"[FAIL] {what}: CSV 가 아닌 응답을 받았습니다(로그인 페이지·오류 HTML?).\n"
            f"       응답 앞부분: {preview!r}\n       수동 경로: {page}") from None
    header = text.splitlines()[0] if text.splitlines() else ""
    squeezed = re.sub(r"\s+", "", header)
    absent = [c for c in required_columns if c not in squeezed]
    if absent:
        preview = header[:200] if header else raw[:200].decode("utf-8", "replace")
        raise SystemExit(
            f"[FAIL] {what}: 헤더에 기대한 컬럼이 없습니다: {absent}\n"
            f"       실제 헤더: {preview!r}\n       수동 경로: {page}")
    return header[:160]


def fetch_seoul() -> bytes:
    """서울 자료 — **공개 CSV 한 경로뿐이다**(인증키 경로 없음, 위 SEOUL_CSV_URL 주석)."""
    return fetch(SEOUL_CSV_URL, what="서울 정비사업 CSV", data={
        "srvType": "S", "infId": SEOUL_DATASET_ID, "serviceKind": "1", "pageNo": "1",
        "gridTotalCnt": "10000", "ssUserId": "SAMPLE_VIEW", "strWhere": "",
        "strOrderby": "CODE DESC", "filterCol": "", "txtFilter": "",
    })


def load_dong_index(engine):
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = [(r.code, r.sido, r.sigungu, r.dong)
                for r in conn.execute(text(_REGION_SQL))]
    if not rows:
        raise SystemExit("[FAIL] region 테이블이 비어 있습니다 — load_regions.py 를 먼저 도세요.")
    logger.info("법정동 색인 %d행", len(rows))
    return build_dong_index(rows)


def _params(rec: RedevRecord) -> dict:
    return {
        "source": rec.source, "source_key": rec.source_key, "source_url": rec.source_url,
        "sido": rec.sido, "sigungu": rec.sigungu, "zone_name": rec.zone_name,
        "raw_stage": rec.raw_stage, "stage": rec.stage,
        "raw_biz_type": rec.raw_biz_type, "biz_type": rec.biz_type,
        "address_jibun_raw": rec.address_raw,
        "parse_status": rec.parse_status, "parse_detail": rec.parse_detail,
        "legal_dong_code": rec.legal_dong_code, "main_no": rec.main_no,
        "sub_no": rec.sub_no or 0, "is_mountain": rec.is_mountain,
        "dong_match": rec.dong_match, "dong_scope": rec.dong_scope,
        "zone_designated_on": rec.zone_designated_on, "committee_on": rec.committee_on,
        "association_on": rec.association_on, "design_review_on": rec.design_review_on,
        "implementation_on": rec.implementation_on,
        "disposition_on": rec.disposition_on,
        "relocation_start_on": rec.relocation_start_on,
        "relocation_end_on": rec.relocation_end_on,
        "construction_start_on": rec.construction_start_on,
        "existing_households": rec.existing_households,
        "planned_households": rec.planned_households,
        "as_of": rec.as_of,
    }


def load(engine, records: list[RedevRecord], *, sources: list[str]) -> dict:
    """적재 + 매칭. **한 트랜잭션**으로 — 반쪽 상태를 남기지 않는다."""
    from sqlalchemy import text

    stats: Counter = Counter()
    match_fail: Counter = Counter()
    samples: list[str] = []

    with engine.begin() as conn:
        # 이번 스냅샷이 담당하는 출처의 매칭만 지운다(다른 출처는 건드리지 않는다).
        conn.execute(text(
            "DELETE FROM redev_project_complex WHERE project_id IN "
            "(SELECT id FROM redev_project WHERE source = ANY(:srcs))"),
            {"srcs": sources})
        for rec in records:
            pid = conn.execute(text(_UPSERT), _params(rec)).scalar_one()
            stats["projects"] += 1
            if rec.parse_status != STATUS_OK:
                match_fail[rec.parse_status] += 1
                continue
            rows = conn.execute(text(_MATCH_SQL), {
                "dong": rec.legal_dong_code, "main": rec.main_no,
                "sub": rec.sub_no or 0, "mtn": rec.is_mountain,
            }).all()
            if not rows:
                match_fail["no_complex_at_parcel"] += 1
                continue
            if len(rows) > MAX_COMPLEXES_PER_PARCEL:
                # 한 필지에 단지가 너무 많다 → 애매하다 → 매칭하지 않는다.
                match_fail["too_many_complexes"] += 1
                continue
            method = (MATCH_PNU_ADMIN_DONG if rec.dong_match == DONG_ADMIN_STRIPPED
                      else MATCH_PNU_EXACT)
            for row in rows:
                conn.execute(text(
                    "INSERT INTO redev_project_complex (project_id, complex_id, "
                    "match_method) VALUES (:p, :c, :m) "
                    "ON CONFLICT (project_id, complex_id) DO UPDATE SET "
                    "match_method = EXCLUDED.match_method, matched_at = now()"),
                    {"p": pid, "c": row.id, "m": method})
                stats["links"] += 1
                if len(samples) < 25:
                    samples.append(f"{rec.sigungu} {rec.zone_name}[{rec.raw_stage}] "
                                   f"→ #{row.id} {row.name}({row.built_year})")
            stats["matched_projects"] += 1
    return {"stats": stats, "match_fail": match_fail, "samples": samples}


def money_like_records(records: list[RedevRecord]) -> list[tuple[str, str, str, str]]:
    """구역명·원문 단계명에 **금액처럼 읽히는 표기**가 있는 행. (출처, 키, 필드, 값)

    막지 않는다 — `제3원구역` 처럼 실제 지명일 수 있고, 원문을 우리가 고칠 권한도 없다.
    대신 **적재 시점에 눈에 띄게** 남긴다. 이 값들은 추천 카드의 rationale 에 그대로
    인용되므로, 화면에서 처음 마주치는 것보다 여기서 세어 두는 편이 낫다(CR31-1).
    """
    out: list[tuple[str, str, str, str]] = []
    for rec in records:
        for field_name, value in (("zone_name", rec.zone_name),
                                  ("raw_stage", rec.raw_stage)):
            if money_like_tokens(value):
                out.append((rec.source, rec.source_key, field_name, value))
    return out


def report(records: list[RedevRecord], outcome: dict) -> None:
    """무엇이 들어갔고 **무엇이 왜 안 들어갔는지**. 성공 건수만 찍지 않는다."""
    by_source = Counter(r.source for r in records)
    parse = Counter(r.parse_status for r in records)
    stages = Counter(r.stage for r in records)
    unknown_raw = Counter(r.raw_stage for r in records if r.stage == STAGE_UNKNOWN)

    print("\n=== 정비사업 적재 리포트 ===")
    print(f"수집 행: {len(records)}  " + " · ".join(f"{k}={v}" for k, v in by_source.items()))
    print("\n[주소 파싱]")
    for key, count in parse.most_common():
        print(f"  {key:<20} {count:>5}  ({count * 100.0 / max(1, len(records)):.1f}%)")
    print("\n[단계 정규화]")
    for key, count in stages.most_common():
        print(f"  {key:<20} {count:>5}")
    if unknown_raw:
        print("  ⚠️ 미분류 원문 단계명(버리지 않고 raw_stage 로 보존):")
        for raw, count in unknown_raw.most_common():
            print(f"     {raw!r}: {count}")
    else:
        print("  미분류 0건 — 정규화 표가 원문 단계명을 모두 덮었습니다.")

    stats, fails = outcome["stats"], outcome["match_fail"]
    print("\n[적재·매칭]")
    print(f"  redev_project        {stats['projects']}행")
    print(f"  매칭된 구역          {stats['matched_projects']}건")
    print(f"  redev_project_complex {stats['links']}행")
    print("  매칭 실패 사유:")
    for key, count in fails.most_common():
        print(f"     {key:<22} {count:>5}")
    if outcome["samples"]:
        print("\n[매칭 예시]")
        for line in outcome["samples"]:
            print(f"  {line}")
    money_like = money_like_records(records)
    print("\n[금액처럼 읽히는 수집 원문]")
    if money_like:
        print(f"  {len(money_like)}건 — **막지 않고 그대로 적재합니다.** 원문 인용이지 "
              "우리가 만든 금액이 아닙니다(추천 카드에도 원문 그대로 나갑니다).")
        for source, key, field_name, value in money_like[:20]:
            print(f"     {source} {key} · {field_name}={value!r}")
        if len(money_like) > 20:
            print(f"     … 외 {len(money_like) - 20}건")
    else:
        print("  0건")

    print("\n⚠️ 경기도는 이번 수집 범위 밖입니다 — 경기 단지의 '정비사업 정보 없음'은 "
          "'없다'가 아니라 '확인되지 않았다'입니다.")
    print("⚠️ 추가분담금은 공개 데이터에 없어 어떤 형태로도 저장·표시하지 않습니다.")


def main() -> None:
    ap = argparse.ArgumentParser(description="정비사업 추진현황 수집·적재")
    ap.add_argument("--only", choices=("seoul", "incheon"), help="한쪽만 처리")
    ap.add_argument("--seoul-file", type=Path, help="내려받는 대신 로컬 CSV 사용")
    ap.add_argument("--incheon-file", type=Path, help="내려받는 대신 로컬 CSV 사용")
    ap.add_argument("--as-of", type=dt.date.fromisoformat, default=dt.date.today(),
                    help="스냅샷 기준일(기본: 오늘)")
    ap.add_argument("--dry-run", action="store_true", help="파싱만 하고 DB 를 바꾸지 않는다")
    args = ap.parse_args()

    load_env()

    engine = make_engine()
    logger.info("DB %s", safe_dsn(database_url()))
    index = load_dong_index(engine)

    records: list[RedevRecord] = []
    sources: list[str] = []
    if args.only != "incheon":
        if args.seoul_file:
            raw, how = args.seoul_file.read_bytes(), f"file:{args.seoul_file.name}"
        else:
            raw, how = fetch_seoul(), "csv"
        # ★ 파싱 전에 **정말 그 CSV 인지** 확인한다(오류 HTML → 쓰레기 1행 UPSERT 방지).
        header = check_payload(raw, required_columns=SEOUL_REQUIRED_COLUMNS,
                               what="서울 정비사업 CSV", page=SEOUL_PAGE)
        logger.info("서울 자료 확보 (%s) 헤더: %s", how, header)
        recs = parse_seoul_csv(raw, as_of=args.as_of, dong_index=index)
        records += recs
        sources.append(SOURCE_SEOUL)
        logger.info("서울 %d행 파싱", len(recs))

    if args.only != "seoul":
        raw = (args.incheon_file.read_bytes() if args.incheon_file
               else fetch(INCHEON_CSV_URL, referer=INCHEON_REFERER,
                          what="인천 정비사업 CSV"))
        header = check_payload(raw, required_columns=INCHEON_REQUIRED_COLUMNS,
                               what="인천 정비사업 CSV", page=INCHEON_REFERER)
        logger.info("인천 자료 확보 헤더: %s", header)
        recs = parse_incheon_csv(raw, as_of=args.as_of, dong_index=index)
        records += recs
        sources.append(SOURCE_INCHEON)
        logger.info("인천 %d행 파싱", len(recs))

    if not records:
        raise SystemExit("[FAIL] 수집된 행이 0건입니다 — 출처 URL 을 확인하세요.")

    if args.dry_run:
        outcome = {"stats": Counter(), "match_fail": Counter(
            r.parse_status for r in records if r.parse_status != STATUS_OK),
            "samples": []}
        outcome["stats"]["projects"] = 0
        print("(--dry-run: DB 를 바꾸지 않았습니다)")
    else:
        outcome = load(engine, records, sources=sources)
    report(records, outcome)


if __name__ == "__main__":
    main()
