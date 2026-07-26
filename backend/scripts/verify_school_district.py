"""학구도 적재 실증 — "적재했다"로 끝내지 않기 위한 스크립트.

    python scripts/verify_school_district.py --sample 200

무엇을 숫자로 보이는가
----------------------
① **school 축 활성화율** — 단지 몇 %에서 배정 초등학교가 실제로 나오는가.
② **'미확보'와 '미포함'의 구분이 살아 있는가** — 이게 깨지면 거리 대체가 시작된다.
   · 포함     : ST_Contains → `in_district=True`, 배정 확정
   · 미포함   : 주변에 학구도는 있는데 어느 구역에도 안 들어감 → 배정 **단정하지 않음**
   · 미확보   : 주변 5km 에 학구도 자체가 없음 → 학군 항목을 비움
   두 경우 모두 최근접 학교 거리로 대체하지 않는다(analysis.assess_school).
③ **입지 점수 전/후** — 같은 단지를 학구도 있는 그대로 / 없는 셈 치고 각각 평가해
   school 축(가중치 0.35)이 점수를 실제로 얼마나 움직였는지 본다.

왜 '전'을 이렇게 만드나
-----------------------
적재를 되돌려 재보는 건 실데이터에 위험하다. 대신 리포지토리가 돌려준 사실에서
`school` 만 떼어(`district_data_available=False`) 도메인을 다시 호출한다 —
적재 이전의 입력과 **정확히 같은 상태**다(그때도 school_district 가 0행이었으므로).
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import logging
import sys

import _common  # noqa: F401  (import 부작용: 로깅 억제·마스킹 설치)
from _common import load_env, make_engine

from app.domain.location.analysis import evaluate_location
from app.domain.location.models import LocationFacts, SchoolFact
from app.repositories.postgis import PostgisRepository

logger = logging.getLogger("scripts.verify_school_district")

#: 리포지토리의 `_DISTRICT_DATA_RADIUS_M` 과 같은 값을 도 단위로 (대략 5km).
_DISTRICT_DEG = 0.05

_CLASSIFY_SQL = """
SELECT CASE
         WHEN c.geom IS NULL THEN 'no_geom'
         WHEN EXISTS (SELECT 1 FROM school_district sd
                       WHERE sd.geom && c.geom AND ST_Contains(sd.geom, c.geom))
              THEN 'in_district'
         WHEN EXISTS (SELECT 1 FROM school_district sd
                       WHERE sd.geom && ST_Expand(c.geom,
                             CAST(:deg AS double precision)))
              THEN 'outside_district'
         ELSE 'no_data'
       END AS bucket,
       count(*) AS n
FROM complex c
GROUP BY 1
"""

_SAMPLE_SQL = """
SELECT c.id, c.name
FROM complex c
WHERE c.geom IS NOT NULL
ORDER BY c.id
LIMIT CAST(:limit AS int)
"""

#: 학구도 밖에 있는 단지(미포함)를 몇 개 뽑아 실제 판정을 보여 준다.
_OUTSIDE_SQL = """
SELECT c.id, c.name
FROM complex c
WHERE c.geom IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM school_district sd
                   WHERE sd.geom && c.geom AND ST_Contains(sd.geom, c.geom))
ORDER BY c.id
LIMIT CAST(:limit AS int)
"""

_LABEL = {
    "in_district": "학구도 포함 (배정 확정)",
    "outside_district": "학구도 미포함 (데이터는 있음 · 배정 단정 안 함)",
    "no_data": "학구도 미확보 (학군 항목 비움)",
    "no_geom": "단지 좌표 없음 (공간판정 불가)",
}


def _without_school(facts: LocationFacts) -> LocationFacts:
    """학구도 적재 **이전** 상태의 사실. school 만 '미확보'로 되돌린다."""
    return dataclasses.replace(
        facts, school=SchoolFact(district_data_available=False))


def classify(engine) -> dict[str, int]:
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(text(_CLASSIFY_SQL), {"deg": _DISTRICT_DEG}).all()
    return {r.bucket: r.n for r in rows}


def show_examples(repo: PostgisRepository, engine, *, limit: int) -> int:
    """배정 초등학교가 실제로 나오는 단지 예시."""
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(text(_SAMPLE_SQL), {"limit": limit}).all()

    shown = 0
    for row in rows:
        facts = repo.location_facts(row.id)
        if facts is None or facts.school is None or not facts.school.in_district:
            continue
        school = facts.school
        before = evaluate_location(_without_school(facts))
        after = evaluate_location(facts)
        print(f"  [{row.id}] {row.name}")
        print(f"      배정 초등학교 : {school.name} · {school.distance_m:.0f}m "
              f"· 기준일자 {school.district_as_of}")
        print(f"      입지 점수     : {before.score} -> {after.score} "
              f"(school 축 반영)")
        shown += 1
        if shown >= 5:
            break
    return shown


def show_outside(repo: PostgisRepository, engine, *, limit: int = 3) -> None:
    """미포함 단지가 **거리로 대체되지 않는지** 확인한다."""
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(text(_OUTSIDE_SQL), {"limit": limit}).all()
    if not rows:
        print("  (학구도 밖 단지 없음)")
        return
    for row in rows:
        facts = repo.location_facts(row.id)
        if facts is None:
            continue
        school = facts.school
        assessment = evaluate_location(facts)
        print(f"  [{row.id}] {row.name}")
        print(f"      SchoolFact  : in_district={school.in_district} "
              f"data_available={school.district_data_available} name={school.name!r}")
        print(f"      미확보 사유 : {list(assessment.missing)}")
        assert school.name is None, "미포함인데 학교 이름이 붙었다 — 거리 대체 의심"


def score_delta(repo: PostgisRepository, engine, *, limit: int) -> None:
    """전/후 점수 차이의 분포."""
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(text(_SAMPLE_SQL), {"limit": limit}).all()

    deltas: list[float] = []
    activated = 0
    for row in rows:
        facts = repo.location_facts(row.id)
        if facts is None:
            continue
        before = evaluate_location(_without_school(facts))
        after = evaluate_location(facts)
        if facts.school and facts.school.in_district:
            activated += 1
        if before.score is not None and after.score is not None:
            deltas.append(round(after.score - before.score, 1))

    if not deltas:
        print("  비교 가능한 단지가 없습니다")
        return
    changed = [d for d in deltas if d != 0]
    print(f"  표본 {len(deltas)}개 · school 축 활성 {activated}개 "
          f"({activated / len(deltas) * 100:.1f}%)")
    print(f"  점수 변화 있음 {len(changed)}개 "
          f"· 평균 {sum(deltas) / len(deltas):+.2f}점 "
          f"· 최소 {min(deltas):+.1f} / 최대 {max(deltas):+.1f}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="학구도 적재 실증")
    ap.add_argument("--sample", type=int, default=200, help="점수 비교 표본 수")
    args = ap.parse_args(argv)

    load_env()
    engine = make_engine()
    repo = PostgisRepository(engine)

    buckets = classify(engine)
    total = sum(buckets.values())
    print("=== ① 단지별 학구도 상태 ===")
    for key in ("in_district", "outside_district", "no_data", "no_geom"):
        n = buckets.get(key, 0)
        print(f"  {_LABEL[key]:42s} {n:6,d}  ({n / total * 100:5.2f}%)")
    active = buckets.get("in_district", 0)
    print(f"  -> school 축 활성화율 {active:,}/{total:,} = {active / total * 100:.2f}%")

    print("\n=== ② 배정 초등학교 실호출 예시 ===")
    shown = show_examples(repo, engine, limit=args.sample)
    if not shown:
        print("  ⚠️ 배정이 나오는 단지가 하나도 없습니다 — 적재를 확인하세요")
        return 1

    print("\n=== ③ '미포함'은 거리로 대체되지 않는다 ===")
    show_outside(repo, engine)

    print("\n=== ④ 입지 점수 전/후 ===")
    score_delta(repo, engine, limit=args.sample)
    return 0


if __name__ == "__main__":
    sys.exit(main())
