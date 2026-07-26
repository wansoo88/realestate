"""부동산원 매칭이 맞는지 **독립적으로** 검증한다 (읽기 전용).

왜 필요한가
-----------
매칭률 86.7% 는 그 자체로 아무것도 증명하지 않는다. GEO-1 이 확보율 93.6% 로 결함을
덮었던 것과 똑같은 함정이다 — "몇 건 붙였나"가 아니라 **"붙인 게 맞나"** 를 물어야 한다.

어떻게 확인하는가 — 서로 다른 두 경로를 대조한다
------------------------------------------------
이미 **이름으로** 좌표를 확보하고 검증까지 통과한 단지(geom_source='kakao_keyword',
geom_confidence='exact')를 표본으로 잡고, 그 단지에 붙은 **부동산원 주소**를 지오코딩해
두 좌표의 거리를 잰다.

  · 매칭이 맞다면 두 좌표는 같은 단지의 다른 지점이다 → 보통 수십~수백 m
  · 매칭이 틀렸다면 남의 단지 주소를 붙인 것이다 → km 단위로 벌어진다

이름 경로와 주소 경로는 **입력도 알고리즘도 다르다.** 둘이 같은 곳을 가리키면
그건 우연이 아니다. 반대로 멀리 떨어진 건은 사람이 봐야 할 목록이다.

⚠️ CR-021 GEO-5 — 표본이 가장 위험한 부류를 구조적으로 빼고 있었다
------------------------------------------------------------------
이전 표본 정의는 `geom_confidence = 'exact'` 로 잘라서 **`variant` 317건을 통째로
제외**했다. `variant` 는 "군더더기를 떼어낸 이름으로 찾은 좌표" — GEO-1 이 지목한
**한 단계 덜 확실한** 부류다. 검증에서 정확히 그 부류가 빠지면 "중앙값 2m" 는
안전한 부분집합에 대한 숫자일 뿐이고, 전체 품질의 증거로 읽히면 GEO-1 때와 같은
"지표가 결함을 덮는" 상황이 된다.

그래서 이제
  · `exact` 와 `variant` 를 **둘 다** 표본에 넣고,
  · 거리 통계를 **신뢰도별로 나눠** 보고한다(합쳐서 하나로 말하지 않는다),
  · 대조가 **구조적으로 불가능한** 모집단(부동산원 미매칭 키워드 좌표, 주소 경로로
    얻은 좌표)의 크기도 같이 찍는다 — "무엇을 검증하지 못했나"가 보여야 한다.

⚠️ 이 스크립트는 DB 를 쓰지 않는다. 카카오 호출은 표본 수만큼만 하고 rate limit 을 지킨다.

사용
----
    export DATABASE_URL=...
    python scripts/verify_reb_matching.py --sample 200
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import database_url, load_env, make_engine, require, safe_dsn  # noqa: E402

from app.ingest.geocode import KakaoAddressSearch, row_target, verify_address  # noqa: E402
from app.ingest.ratelimit import RateLimiter  # noqa: E402

#: 같은 단지로 볼 수 있는 거리(m). 대단지는 부지 대각선이 300m 를 넘기도 하므로
#: 넉넉히 잡는다 — 여기서 정밀도를 재는 게 아니라 **다른 단지에 붙은 건**을 찾는 것이다.
SAME_COMPLEX_M = 400.0

#: 대조 대상 — **이름 경로로 얻은 좌표 전부**(exact + variant). 신뢰도로 자르지 않는다.
#: 주소 경로(`kakao_address`) 좌표는 대조 상대와 같은 경로라 재면 항상 0m 다 — 제외가 맞다.
_SQL = """
    SELECT c.id, c.name, c.address_jibun, r.sido, r.sigungu, c.reb_complex_id,
           b.address_jibun AS reb_address, b.legal_dong_code AS reb_dong_code,
           b.main_no AS reb_main_no, b.sub_no AS reb_sub_no,
           b.is_mountain AS reb_is_mountain,
           c.reb_match_method, c.geom_confidence,
           ST_X(c.geom) AS lon, ST_Y(c.geom) AS lat
    FROM complex c
    JOIN reb_complex b ON b.reb_complex_id = c.reb_complex_id
    LEFT JOIN region r ON r.code = c.region_code
    WHERE c.geom IS NOT NULL
      AND c.geom_source = 'kakao_keyword'
      AND b.address_jibun IS NOT NULL
    ORDER BY c.id
"""

#: 모집단 지도 — "무엇을 검증했고 무엇을 못 했나"를 숫자로 남긴다(GEO-5).
_POPULATION_SQL = """
    SELECT count(*) FILTER (WHERE geom IS NOT NULL) AS with_geom,
           count(*) FILTER (WHERE geom IS NOT NULL
                              AND geom_source = 'kakao_keyword'
                              AND geom_confidence = 'exact')    AS keyword_exact,
           count(*) FILTER (WHERE geom IS NOT NULL
                              AND geom_source = 'kakao_keyword'
                              AND geom_confidence = 'variant')  AS keyword_variant,
           count(*) FILTER (WHERE geom IS NOT NULL
                              AND geom_source = 'kakao_keyword'
                              AND reb_complex_id IS NULL)       AS keyword_unmatched,
           count(*) FILTER (WHERE geom IS NOT NULL
                              AND geom_source = 'kakao_address') AS address_path
    FROM complex
"""


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[idx]


#: 신뢰도 구간마다 최소 이만큼은 본다. 비례 배분만 하면 작은 구간(`variant`)이
#: 몇 건으로 쪼그라들어 "봤다"고 말할 수 없게 된다 — GEO-5 가 지적한 그 구멍이다.
MIN_PER_BUCKET = 60


def stratified(rows: list, sample: int, seed: int) -> list:
    """신뢰도(`exact`/`variant`)별로 나눠 뽑는다 — 한 구간이 통째로 빠지지 않게.

    단순 무작위 표본은 모집단 비율(예: 4,422 : 317)을 그대로 따라가서 `variant` 가
    표본 250건 중 17건 정도로 줄어든다. 그 17건으로는 "덜 확실한 부류가 실제로
    더 나쁜가"를 말할 수 없다. 구간마다 하한을 두고 나머지를 비례 배분한다.
    """
    if not sample or sample >= len(rows):
        return rows
    buckets: dict[str, list] = {}
    for r in rows:
        buckets.setdefault(r.geom_confidence or "(미표기)", []).append(r)

    rng = random.Random(seed)
    quota = {k: min(len(v), MIN_PER_BUCKET) for k, v in buckets.items()}
    left = sample - sum(quota.values())
    if left > 0:
        rest = sum(len(v) - quota[k] for k, v in buckets.items()) or 1
        for k, v in buckets.items():
            quota[k] += min(len(v) - quota[k], round(left * (len(v) - quota[k]) / rest))

    out: list = []
    for k, v in buckets.items():
        take = min(len(v), max(0, quota[k]))
        out += rng.sample(v, take) if take < len(v) else v
    out.sort(key=lambda r: r.id)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="부동산원 매칭 교차검증 (읽기 전용)")
    ap.add_argument("--sample", type=int, default=200, help="표본 수(0=전부)")
    ap.add_argument("--seed", type=int, default=20260726)
    ap.add_argument("--min-interval", type=float, default=0.25)
    ap.add_argument("--far", type=float, default=SAME_COMPLEX_M,
                    help="이 거리(m)를 넘으면 '멀다'로 보고 사람이 확인할 목록에 올린다")
    args = ap.parse_args(argv)

    load_env()
    key = require("KAKAO_REST_API_KEY")
    url = database_url()
    engine = make_engine(url)
    print(f"[INFO] DB {safe_dsn(url)} (읽기 전용)")

    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(_SQL)).all()
            pop = conn.execute(text(_POPULATION_SQL)).one()
    finally:
        engine.dispose()

    # 무엇을 검증하지 못하는지부터 밝힌다 — 표본 밖은 "괜찮다"가 아니라 "모른다"다.
    print(f"[모집단] 좌표 확보 {pop.with_geom:,}건 = "
          f"이름/exact {pop.keyword_exact:,} + 이름/variant {pop.keyword_variant:,} + "
          f"주소 경로 {pop.address_path:,}")
    print(f"         대조 **불가** — 부동산원 미매칭 키워드 좌표 {pop.keyword_unmatched:,}건"
          f"(주소를 모른다) · 주소 경로 {pop.address_path:,}건(대조 상대와 같은 경로)")
    by_conf_pop: dict[str, int] = {}
    for r in rows:
        by_conf_pop[r.geom_confidence or "(미표기)"] = \
            by_conf_pop.get(r.geom_confidence or "(미표기)", 0) + 1
    print(f"[INFO] 대조 가능한 단지 {len(rows):,}건 {by_conf_pop} "
          "(이름 경로 좌표 + 부동산원 주소를 둘 다 가진 단지)")

    rows = stratified(rows, args.sample, args.seed)

    search = KakaoAddressSearch(
        key, rate_limiter=RateLimiter(min_interval_sec=args.min_interval, jitter_sec=0.15))

    distances: list[float] = []
    by_conf: dict[str, list[float]] = {}
    sampled: dict[str, int] = {}
    far: list[str] = []
    unverified = 0
    unverified_by_conf: dict[str, int] = {}
    for row in rows:
        conf = row.geom_confidence or "(미표기)"
        sampled[conf] = sampled.get(conf, 0) + 1
        target = row_target(row)
        hit = next((h for h in search.search(target.address)
                    if verify_address(h, target)), None)
        if hit is None:
            unverified += 1            # 주소검증 불합격 — 매칭이 틀렸다는 뜻은 아니다
            unverified_by_conf[conf] = unverified_by_conf.get(conf, 0) + 1
            continue
        d = haversine_m(row.lon, row.lat, hit.lon, hit.lat)
        distances.append(d)
        by_conf.setdefault(conf, []).append(d)
        if d > args.far:
            far.append(f"{d:8.0f}m  [{conf}] #{row.id} '{row.address_jibun} {row.name}' "
                       f"[{row.reb_match_method}] ↔ 부동산원 '{target.address}'")

    n = len(distances)
    print(f"\n[검증] 표본 {len(rows)}건 {sampled} · 두 경로 모두 좌표를 낸 것 {n}건 "
          f"· 주소검증 불합격 {unverified}건 {unverified_by_conf}")
    if not n:
        print("⛔ 대조할 쌍이 없습니다 — 매칭·주소 적재를 먼저 확인하세요.")
        return 1
    close = sum(1 for d in distances if d <= args.far)
    print(f"       [전체] 중앙값 {_percentile(distances, 0.5):.0f}m · "
          f"p90 {_percentile(distances, 0.9):.0f}m · 최대 {max(distances):.0f}m · "
          f"{args.far:.0f}m 이내 {close}/{n} ({close / n * 100:.1f}%)")
    # ⚠️ 신뢰도별로 **반드시 나눠서** 보고한다. 하나로 합친 숫자는 안전한 다수(exact)가
    #    위험한 소수(variant)를 덮는다 — GEO-1·GEO-5 가 같은 방식으로 결함을 덮었다.
    for conf in sorted(by_conf):
        ds = by_conf[conf]
        c = sum(1 for d in ds if d <= args.far)
        print(f"       [{conf}] n={len(ds)} 중앙값 {_percentile(ds, 0.5):.0f}m · "
              f"p90 {_percentile(ds, 0.9):.0f}m · 최대 {max(ds):.0f}m · "
              f"{args.far:.0f}m 이내 {c}/{len(ds)} ({c / len(ds) * 100:.1f}%)")
    if far:
        print(f"\n⚠️ 멀리 떨어진 {len(far)}건 — 사람이 확인할 목록(최대 20건 표시):")
        for line in sorted(far, reverse=True)[:20]:
            print(f"       {line}")
    else:
        print("       멀리 떨어진 건 없음 — 이름 경로와 주소 경로가 같은 곳을 가리킵니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
