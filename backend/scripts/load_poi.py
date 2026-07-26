"""입지(F3) 적재 — `data/raw/poi/*.json` → poi · road_segment · transit_plan.

    python scripts/load_poi.py --dataset all
    python scripts/load_poi.py --dataset subway --suffix _pilot
    python scripts/load_poi.py --dataset school --geocode      # 카카오 주소검색 사용

`fetch_poi.py` 가 저장한 **원문**만 읽는다(네트워크 없음, 학교 지오코딩 제외).
파싱 규칙이 바뀌어도 다시 받지 않고 재적재할 수 있게 나눠 둔 구조다.

멱등
----
`(source, source_ref)` 유니크(011) 위 upsert 라 몇 번을 돌려도 행이 안 쌓인다.
자연키가 없는 레코드는 **건너뛰고 세어서** 보고한다 — 조용히 버리지 않는다.

ingest_log
----------
데이터셋마다 한 행을 남긴다. 원문에 실패 타일이 있었으면 status=partial 이다 —
"적재 성공"과 "완전한 수집"은 다르고, 그 차이를 원장에 남기지 않으면 나중에
"왜 이 동네만 역이 없지"를 설명할 수 없다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Any

import _common  # noqa: F401  (import 부작용: 로깅 억제·마스킹 설치)
from _common import REPO_ROOT, load_env, make_engine

from app.ingest import poi as poi_mod
from app.ingest.poi_loader import PoiLoadResult, PostgisPoiLoader

logger = logging.getLogger("scripts.load_poi")

RAW_DIR = REPO_ROOT / "data" / "raw" / "poi"

#: 데이터셋 → (대상 표, 파싱 함수 이름). 학교·노선관계는 따로 다룬다.
POI_DATASETS = {
    "subway": poi_mod.CAT_SUBWAY,
    "park": poi_mod.CAT_PARK,
    "mart": poi_mod.CAT_MART,
    "hospital": poi_mod.CAT_HOSPITAL,
    "hazard": poi_mod.CAT_HAZARD,
}
ALL_DATASETS = (*POI_DATASETS, "road", "transit_plan", "school")


def _read(name: str, suffix: str) -> dict[str, Any] | None:
    path = RAW_DIR / f"{name}{suffix}.json"
    if not path.exists():
        logger.warning("원문 없음 — 건너뜀: %s", path.name)
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _log_ingest(engine: Any, *, source: str, target: str, started: dt.datetime,
                result: PoiLoadResult, status: str, message: str) -> None:
    """ingest_log 한 행. **조용한 실패 금지**가 이 표의 존재 이유다."""
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO ingest_log (source, target_table, started_at, finished_at,
                                    rows_ok, rows_failed, status, message)
            VALUES (:source, :target, :started, now(), :ok, :failed, :status, :message)
        """), {"source": source, "target": target, "started": started,
               "ok": result.total, "failed": result.skipped,
               "status": status, "message": message[:2000]})


def _status_for(payload: dict[str, Any], result: PoiLoadResult) -> tuple[str, str]:
    """수집 실패 타일·건너뛴 행을 반영한 상태."""
    failures = payload.get("failures") or []
    bits = [f"신규 {result.inserted}", f"갱신 {result.updated}"]
    if result.skipped:
        bits.append(f"건너뜀 {result.skipped}")
    if failures:
        bits.append(f"수집 실패 {len(failures)}건: " + "; ".join(str(f) for f in failures[:5]))
        return "partial", " / ".join(bits)
    return "ok", " / ".join(bits)


# ---------------------------------------------------------------------------
# 데이터셋별 적재
# ---------------------------------------------------------------------------

def load_poi_dataset(engine: Any, loader: PostgisPoiLoader, name: str,
                     suffix: str) -> PoiLoadResult | None:
    payload = _read(name, suffix)
    if payload is None:
        return None
    started = dt.datetime.now(dt.timezone.utc)

    if name == "subway":
        routes = _read("subway_routes", suffix)
        records = poi_mod.parse_stations(payload, routes)
        if routes is None:
            logger.warning("노선 관계(subway_routes)가 없어 lines 가 빈 배열이 됩니다 "
                           "— 환승역 가점이 반영되지 않습니다")
    elif name == "hazard":
        records = poi_mod.parse_hazards(payload)
    else:
        records = poi_mod.parse_amenities(payload, category=POI_DATASETS[name])

    records = poi_mod.dedupe(records)
    result = loader.load_pois(records)
    status, message = _status_for(payload, result)
    _log_ingest(engine, source=f"{payload.get('source', 'unknown')}:{name}",
                target="poi", started=started, result=result,
                status=status, message=message)
    logger.info("[%s] %s — %s", name, status, message)
    return result


def load_roads(engine: Any, loader: PostgisPoiLoader, suffix: str) -> PoiLoadResult | None:
    payload = _read("road", suffix)
    if payload is None:
        return None
    started = dt.datetime.now(dt.timezone.utc)
    as_of = dt.date.today()
    records = poi_mod.dedupe_keyed(poi_mod.parse_roads(payload, as_of=as_of))
    result = loader.load_roads(records)
    status, message = _status_for(payload, result)
    _log_ingest(engine, source="osm_overpass:road", target="road_segment",
                started=started, result=result, status=status, message=message)
    logger.info("[road] %s — %s", status, message)
    return result


def load_transit_plans(engine: Any, loader: PostgisPoiLoader,
                       suffix: str) -> PoiLoadResult | None:
    payload = _read("transit_plan", suffix)
    if payload is None:
        return None
    started = dt.datetime.now(dt.timezone.utc)
    # 같은 노선이 여러 way 로 쪼개져 있다 — 접지 않으면 리포트에 같은 호재가
    # 노선당 최대 13번 찍힌다(merge_transit_plans 주석).
    records = poi_mod.merge_transit_plans(
        poi_mod.dedupe_keyed(poi_mod.parse_transit_plans(payload)))
    result = loader.load_transit_plans(records, source=poi_mod.SOURCE_OSM)
    status, message = _status_for(payload, result)
    _log_ingest(engine, source="osm_overpass:transit_plan", target="transit_plan",
                started=started, result=result, status=status, message=message)
    logger.info("[transit_plan] %s — %s", status, message)
    return result


# ---------------------------------------------------------------------------
# 학교 — 주소만 있어 지오코딩이 필요하다
# ---------------------------------------------------------------------------

def _school_targets(payload: dict[str, Any]) -> list[poi_mod.SchoolRecord]:
    schools: list[poi_mod.SchoolRecord] = []
    seen: set[str] = set()
    for page in payload.get("pages") or []:
        for school in poi_mod.parse_neis_schools(page):
            if school.source_ref in seen:
                continue
            seen.add(school.source_ref)
            schools.append(school)
    return schools


def load_schools(engine: Any, loader: PostgisPoiLoader, suffix: str, *,
                 geocode: bool, limit: int | None) -> PoiLoadResult | None:
    """NEIS 학교 → poi(category=school). 좌표는 카카오 **주소검색**으로 얻는다.

    ⚠️ 좌표 검증은 우회하지 않는다 — `geocode.in_capital_bbox` 로 권역을 확인하고,
       카카오가 '동 중심점'(REGION)을 주면 **버린다**(geocode.ADDRESS_TYPES_OK).
       동 중심점을 받아 넣으면 한 동의 학교가 전부 한 점에 뭉친다(GEO-1 과 같은 실패).

    ⚠️ 학구도(school_district)가 없으면 이 좌표들은 **입지 점수에 쓰이지 않는다.**
       도메인이 배정을 거리로 대체하지 않기 때문이다(analysis.assess_school).
       그래도 적재하는 이유는 학구도가 확보되는 즉시 쓰이고, 근거 표시에도 필요해서다.
    """
    import os

    payload = _read("school", suffix)
    if payload is None:
        return None
    started = dt.datetime.now(dt.timezone.utc)
    schools = _school_targets(payload)
    if limit:
        schools = schools[:limit]
    logger.info("학교 대상 %d건 (지오코딩 %s)", len(schools), "함" if geocode else "안 함")

    if not geocode:
        logger.warning("--geocode 없이는 좌표가 없어 적재하지 않습니다 "
                       "(좌표 없는 poi 는 공간쿼리에 안 잡힙니다)")
        return None

    from app.ingest.geocode import (
        ADDRESS_TYPES_OK,
        KakaoAddressSearch,
        in_capital_bbox,
    )

    load_env()
    key = os.getenv("KAKAO_REST_API_KEY", "").strip()
    if not key:
        raise SystemExit("[FAIL] KAKAO_REST_API_KEY 가 필요합니다 — .env 를 확인하세요.")
    search = KakaoAddressSearch(key)

    records: list[poi_mod.PoiRecord] = []
    unresolved: list[str] = []
    for idx, school in enumerate(schools, 1):
        try:
            hits = search.search(school.address)
        except Exception as exc:                        # noqa: BLE001
            unresolved.append(f"{school.name}: 검색 실패 {type(exc).__name__}")
            continue
        chosen = None
        for hit in hits:
            # 동 중심점(REGION)은 받지 않는다 — 같은 동 학교가 한 점에 뭉친다.
            if hit.address_type not in ADDRESS_TYPES_OK:
                continue
            if not in_capital_bbox(hit.lon, hit.lat):
                continue
            chosen = hit
            break
        if chosen is None:
            # 못 찾으면 **추정하지 않고** 넣지 않는다.
            unresolved.append(f"{school.name}({school.address})")
            continue
        records.append(poi_mod.school_to_poi(
            school, chosen.lon, chosen.lat, geom_source="kakao_address"))
        if idx % 200 == 0:
            logger.info("지오코딩 %d/%d (미해결 %d)", idx, len(schools), len(unresolved))

    result = loader.load_pois(poi_mod.dedupe(records))
    result.skipped += len(unresolved)
    status = "partial" if unresolved else "ok"
    message = (f"신규 {result.inserted} / 갱신 {result.updated} / "
               f"좌표 미확보 {len(unresolved)}")
    if unresolved:
        message += " — 예: " + "; ".join(unresolved[:5])
    _log_ingest(engine, source="neis_schoolinfo:school", target="poi",
                started=started, result=result, status=status, message=message)
    logger.info("[school] %s — %s", status, message)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="입지 원천 적재 (poi/road_segment/transit_plan)")
    ap.add_argument("--dataset", default="all", choices=("all", *ALL_DATASETS))
    ap.add_argument("--suffix", default="", help="fetch 시 쓴 파일명 접미사")
    ap.add_argument("--chunk", type=int, default=500, help="한 트랜잭션 행 수(소형 VPS)")
    ap.add_argument("--geocode", action="store_true",
                    help="학교 주소를 카카오 주소검색으로 지오코딩한다")
    ap.add_argument("--limit", type=int, default=None, help="학교 지오코딩 상한(검증용)")
    args = ap.parse_args(argv)

    load_env()
    engine = make_engine()
    loader = PostgisPoiLoader(engine, chunk_size=args.chunk)

    names = list(ALL_DATASETS) if args.dataset == "all" else [args.dataset]
    total = PoiLoadResult()
    for name in names:
        if name in POI_DATASETS:
            res = load_poi_dataset(engine, loader, name, args.suffix)
        elif name == "road":
            res = load_roads(engine, loader, args.suffix)
        elif name == "transit_plan":
            res = load_transit_plans(engine, loader, args.suffix)
        elif name == "school":
            res = load_schools(engine, loader, args.suffix,
                               geocode=args.geocode, limit=args.limit)
        else:
            continue
        if res is not None:
            total = total.merge(res)

    logger.info("합계 — 신규 %d / 갱신 %d / 건너뜀 %d",
                total.inserted, total.updated, total.skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
