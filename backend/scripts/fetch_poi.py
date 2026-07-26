"""입지(F3) 원천 내려받기 — OSM(Overpass) POI·도로·신설노선 + NEIS 학교.

    python scripts/fetch_poi.py --dataset all
    python scripts/fetch_poi.py --dataset road --tiles 4      # 도로만 다시
    python scripts/fetch_poi.py --dataset school              # NEIS 만

받은 원문을 `data/raw/poi/*.json` 에 그대로 저장한다(gitignore 대상).
**파싱·적재는 하지 않는다** — `load_poi.py` 가 한다. 나누는 이유는 원천 응답을 보존해
파싱 규칙이 바뀌어도 다시 받지 않고 재적재할 수 있게 하기 위해서다(rate limit 존중).

출처·라이선스
-------------
* OSM(Overpass API) — ODbL 1.0. 출처표시 "© OpenStreetMap contributors".
  공개 API 이며 크롤링이 아니다. 그래도 무료 공용 인스턴스라 **간격을 넉넉히** 둔다.
* NEIS 교육정보 개방 포털(교육부) — 인증키 없이 조회 가능한 공개 API.

⚠️ 이 스크립트는 비밀을 다루지 않지만, `_common` 을 거쳐 로깅 마스킹을 설치한다
   (tests/test_script_hygiene.py 가 모든 스크립트에 강제한다).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import _common  # noqa: F401  (import 부작용: 로깅 억제·마스킹 설치)
from _common import REPO_ROOT

from app.ingest.ratelimit import RateLimiter, backoff_delays

logger = logging.getLogger("scripts.fetch_poi")

OUT_DIR = REPO_ROOT / "data" / "raw" / "poi"

USER_AGENT = "pjt13-realestate/0.1 (personal, non-commercial)"

#: 공용 Overpass 인스턴스. 앞의 것부터 시도하고 실패하면 다음으로 넘어간다.
#: overpass-api.de 는 상시 혼잡(504)이라 뒤로 뺐다 — 실측(2026-07-26).
OVERPASS_ENDPOINTS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)

#: 수도권 전체(서울·경기·인천) 대략 bbox. geocode.CAPITAL_BBOX 보다 넉넉히 잡아
#: 경계 밖 역·도로도 받는다 — 단지 근처의 시설이 행정경계 밖일 수 있다.
CAPITAL_BBOX = (36.90, 126.00, 38.30, 127.90)      # (min_lat, min_lon, max_lat, max_lon)

#: Overpass 는 무료 공용 자원이다. 질의 하나가 60초씩 걸리므로 간격도 넉넉히.
OVERPASS_INTERVAL_SEC = 5.0
OVERPASS_TIMEOUT_SEC = 600

NEIS_URL = "https://open.neis.go.kr/hub/schoolInfo"
#: 수도권 시도교육청 코드. 학군은 시도교육청 단위로 관리된다.
NEIS_OFFICES = {"B10": "서울특별시교육청", "J10": "경기도교육청", "E10": "인천광역시교육청"}
NEIS_LEVELS = ("초등학교", "중학교", "고등학교")
NEIS_PAGE_SIZE = 1000
NEIS_INTERVAL_SEC = 0.5


class FetchError(RuntimeError):
    """원천에서 못 받았다. **부분 결과를 성공으로 저장하지 않기 위해** 올린다."""


# ---------------------------------------------------------------------------
# Overpass
# ---------------------------------------------------------------------------

def _bbox_str(bbox: tuple[float, float, float, float]) -> str:
    return ",".join(f"{v:.5f}" for v in bbox)


def tiles(bbox: tuple[float, float, float, float], n: int
          ) -> list[tuple[float, float, float, float]]:
    """bbox 를 n×n 격자로 쪼갠다.

    도로처럼 결과가 큰 질의는 한 번에 받으면 공용 인스턴스가 504 로 끊는다.
    타일 경계에 걸친 way 는 양쪽 타일에 모두 나오지만, 자연키(`source_ref`)로
    적재 단계에서 접히므로 중복이 남지 않는다.
    """
    min_lat, min_lon, max_lat, max_lon = bbox
    dlat = (max_lat - min_lat) / n
    dlon = (max_lon - min_lon) / n
    out = []
    for i in range(n):
        for j in range(n):
            out.append((min_lat + i * dlat, min_lon + j * dlon,
                        min_lat + (i + 1) * dlat, min_lon + (j + 1) * dlon))
    return out


def overpass(query: str, *, limiter: RateLimiter, attempts: int = 4) -> dict:
    """Overpass 질의 → JSON. 엔드포인트를 돌아가며 재시도한다.

    공용 인스턴스는 혼잡하면 504/429 를 준다. **재시도 없이 실패로 두면** 수집이
    통째로 비는데, 그건 조용한 유실과 같다 — 그래서 백오프하며 다른 인스턴스로 넘긴다.
    """
    delays = backoff_delays(attempts, base=3.0, cap=60.0)
    last_error: str = "시도 없음"
    for attempt in range(attempts):
        endpoint = OVERPASS_ENDPOINTS[attempt % len(OVERPASS_ENDPOINTS)]
        limiter.wait()
        try:
            req = urllib.request.Request(
                endpoint, data=query.encode("utf-8"),
                headers={"User-Agent": USER_AGENT,
                         "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=OVERPASS_TIMEOUT_SEC) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code} ({endpoint})"
        except Exception as exc:                       # noqa: BLE001
            last_error = f"{type(exc).__name__} {exc} ({endpoint})"
        logger.warning("Overpass 재시도 %d/%d — %s", attempt + 1, attempts, last_error)
        if attempt < attempts - 1:
            time.sleep(delays[attempt])
    raise FetchError(f"Overpass 실패: {last_error}")


def _q(body: str, bbox: tuple[float, float, float, float], out: str) -> str:
    return f"[out:json][timeout:300];{body.format(bbox=_bbox_str(bbox))}{out}"


#: 데이터셋 정의: (질의 본문 템플릿, out 절, 기본 타일 수)
#: `out center` — way/relation 의 대표 좌표를 받는다(poi.geom 은 Point 다).
#: `out geom`   — 선형 전체 좌표를 받는다(road_segment·transit_plan).
DATASETS: dict[str, tuple[str, str, int]] = {
    "subway": (
        'node["railway"~"^(station|halt)$"]({bbox});',
        "out body;", 1),
    # 관계뿐 아니라 **멤버 노드의 좌표까지** 받는다(`node(r.rt)`).
    # PTv2 에서 route 멤버는 정차지점(stop_position)이라 역 노드와 ID 가 다르다 —
    # 좌표가 없으면 노선을 역에 이을 방법이 없다(poi.assign_lines 주석).
    "subway_routes": (
        'relation["type"="route"]["route"~"^(subway|light_rail|train|monorail)$"]'
        '({bbox})->.rt;.rt out body;node(r.rt);',
        "out body;", 2),
    "park": (
        '(way["leisure"="park"]({bbox});node["leisure"="park"]({bbox}););',
        "out center tags;", 2),
    "mart": (
        '(node["shop"~"^(supermarket|department_store|mall|wholesale)$"]({bbox});'
        'way["shop"~"^(supermarket|department_store|mall|wholesale)$"]({bbox}););',
        "out center tags;", 2),
    "hospital": (
        '(node["amenity"="hospital"]({bbox});way["amenity"="hospital"]({bbox}););',
        "out center tags;", 2),
    "hazard": (
        '(node["power"~"^(substation|tower)$"]({bbox});'
        'way["power"="substation"]({bbox});'
        'way["man_made"="works"]({bbox});'
        'node["man_made"="works"]({bbox});'
        'way["landuse"="landfill"]({bbox}););',
        "out center tags;", 3),
    "road": (
        'way["highway"~"^(motorway|trunk|primary)$"]({bbox});',
        "out geom;", 4),
    "transit_plan": (
        'way["railway"~"^(construction|proposed)$"]({bbox});',
        "out geom;", 2),
}


def fetch_overpass_dataset(name: str, *, tile_n: int | None = None,
                           limiter: RateLimiter,
                           bbox: tuple[float, float, float, float] | None = None,
                           suffix: str = "") -> Path:
    body, out_clause, default_tiles = DATASETS[name]
    n = tile_n or default_tiles
    area = bbox or CAPITAL_BBOX
    boxes = tiles(area, n)
    elements: list[dict] = []
    failures: list[str] = []

    for idx, box in enumerate(boxes, 1):
        query = _q(body, box, out_clause)
        logger.info("[%s] 타일 %d/%d 요청", name, idx, len(boxes))
        try:
            payload = overpass(query, limiter=limiter)
        except FetchError as exc:
            # 타일 하나가 깨져도 나머지는 받되, **조용히 넘기지 않는다.**
            failures.append(f"tile{idx}: {exc}")
            logger.error("[%s] 타일 %d 실패 — %s", name, idx, exc)
            continue
        got = payload.get("elements") or []
        elements.extend(got)
        logger.info("[%s] 타일 %d/%d → %d건 (누적 %d)", name, idx, len(boxes),
                    len(got), len(elements))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}{suffix}.json"
    path.write_text(json.dumps({
        "dataset": name,
        "source": "osm_overpass",
        "license": "ODbL 1.0 — © OpenStreetMap contributors",
        "bbox": area,
        "tiles": n,
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        # 실패한 타일을 파일에 남긴다 — 적재 단계가 '완전한 수집'인지 알 수 있어야 한다.
        "failures": failures,
        "elements": elements,
    }, ensure_ascii=False), encoding="utf-8")
    logger.info("[%s] 저장 %s (%d건, 실패 타일 %d)", name, path.name,
                len(elements), len(failures))
    if failures and not elements:
        raise FetchError(f"{name}: 모든 타일 실패")
    return path


# ---------------------------------------------------------------------------
# NEIS 학교
# ---------------------------------------------------------------------------

def _neis_get(params: dict[str, str], *, limiter: RateLimiter) -> dict:
    limiter.wait()
    url = NEIS_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def fetch_schools(*, limiter: RateLimiter) -> Path:
    """수도권 3개 시도교육청 × 초·중·고 전체를 페이지네이션으로 받는다.

    ⚠️ 총건수(list_total_count)만큼 못 받으면 **실패로 남긴다.** 잘린 학교 목록을
       성공으로 저장하면 나중에 "이 동네만 학교가 없다"는 조용한 구멍이 된다.
    """
    from app.ingest.poi import neis_total_count, parse_neis_schools

    blocks: list[dict] = []
    failures: list[str] = []
    for office in NEIS_OFFICES:
        for level in NEIS_LEVELS:
            label = f"{office}/{level}"
            collected = 0
            total: int | None = None
            page = 1
            while True:
                params = {"Type": "json", "pIndex": str(page),
                          "pSize": str(NEIS_PAGE_SIZE),
                          "ATPT_OFCDC_SC_CODE": office,
                          "SCHUL_KND_SC_NM": level}
                try:
                    payload = _neis_get(params, limiter=limiter)
                except Exception as exc:               # noqa: BLE001
                    failures.append(f"{label} p{page}: {type(exc).__name__} {exc}")
                    logger.error("NEIS %s 페이지 %d 실패 — %s", label, page, exc)
                    break
                rows = parse_neis_schools(payload)
                if page == 1:
                    total = neis_total_count(payload)
                blocks.append(payload)
                collected += len(rows)
                logger.info("NEIS %s p%d → %d건 (누적 %d / 총 %s)",
                            label, page, len(rows), collected, total)
                if not rows or (total is not None and collected >= total):
                    break
                page += 1
                if page > 50:                          # 무한루프 방지
                    failures.append(f"{label}: 페이지 상한 초과")
                    break
            if total is not None and collected < total:
                failures.append(f"{label}: 총 {total}건 중 {collected}건만 수신")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "school.json"
    path.write_text(json.dumps({
        "dataset": "school",
        "source": "neis_schoolinfo",
        "license": "교육부 NEIS 교육정보 개방 포털 (공공누리)",
        "offices": NEIS_OFFICES,
        "levels": list(NEIS_LEVELS),
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "failures": failures,
        "pages": blocks,
    }, ensure_ascii=False), encoding="utf-8")
    logger.info("학교 저장 %s (응답 %d개, 실패 %d)", path.name, len(blocks), len(failures))
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="입지 원천 내려받기 (OSM + NEIS)")
    ap.add_argument("--dataset", default="all",
                    choices=("all", "school", *DATASETS))
    ap.add_argument("--tiles", type=int, default=None,
                    help="Overpass bbox 를 n×n 으로 쪼갠다(기본: 데이터셋별 권장값)")
    ap.add_argument("--bbox", default=None,
                    help="min_lat,min_lon,max_lat,max_lon — 일부 지역만 받는다"
                         "(단계적 수집·소량 검증용). 생략하면 수도권 전체.")
    ap.add_argument("--suffix", default="",
                    help="출력 파일명 접미사(부분 수집을 전체분과 섞지 않기 위해)")
    args = ap.parse_args(argv)

    bbox = None
    if args.bbox:
        parts = [float(x) for x in args.bbox.split(",")]
        if len(parts) != 4:
            ap.error("--bbox 는 min_lat,min_lon,max_lat,max_lon 4개 값이어야 합니다")
        bbox = (parts[0], parts[1], parts[2], parts[3])

    limiter = RateLimiter(min_interval_sec=OVERPASS_INTERVAL_SEC, jitter_sec=1.0)
    neis_limiter = RateLimiter(min_interval_sec=NEIS_INTERVAL_SEC, jitter_sec=0.2)

    targets = list(DATASETS) if args.dataset == "all" else (
        [] if args.dataset == "school" else [args.dataset])
    failed: list[str] = []

    for name in targets:
        try:
            fetch_overpass_dataset(name, tile_n=args.tiles, limiter=limiter,
                                   bbox=bbox, suffix=args.suffix)
        except FetchError as exc:
            logger.error("%s 수집 실패 — %s", name, exc)
            failed.append(name)

    if args.dataset in ("all", "school"):
        try:
            fetch_schools(limiter=neis_limiter)
        except Exception as exc:                        # noqa: BLE001
            logger.error("학교 수집 실패 — %s", exc)
            failed.append("school")

    if failed:
        logger.error("실패한 데이터셋: %s", ", ".join(failed))
        return 1
    logger.info("완료 → %s", OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
