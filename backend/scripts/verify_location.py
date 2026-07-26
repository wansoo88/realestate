"""입지 분석 실증 — `location_facts()` 실호출 + `evaluate_location()` 판정.

    python scripts/verify_location.py --region 11680 --limit 5
    python scripts/verify_location.py --complex-id 12345

"적재했다"로 끝내지 않기 위한 스크립트다. 실제 단지를 골라
  ① 리포지토리가 사실(역·마트·공원·병원 거리)을 실제로 돌려주는지
  ② 도메인이 **판단 보류를 벗어나** 점수를 내는지
를 숫자로 보여 준다.

판단 보류의 의미(analysis.evaluate_location)
--------------------------------------------
`score is None` 이면 "입지 판단에 쓸 실측 데이터가 부족합니다" 가 나온다.
score 는 transit·school·infra **세 축 중 하나라도** 있으면 계산된다(있는 것끼리 정규화).
따라서 학구도가 없어도 역·인프라만으로 보류를 벗어난다 —
다만 school 축(가중치 0.35)은 **학구도 없이는 영원히 비어 있다**(거리로 대체 금지).
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys

import _common  # noqa: F401  (import 부작용: 로깅 억제·마스킹 설치)
from _common import load_env, make_engine

from app.domain.location.analysis import evaluate_location
from app.repositories.postgis import PostgisRepository

logger = logging.getLogger("scripts.verify_location")


def pick_complexes(engine, *, region: str | None, limit: int,
                   complex_id: int | None) -> list[tuple[int, str]]:
    from sqlalchemy import text

    if complex_id is not None:
        sql = text("SELECT id, name FROM complex WHERE id = :cid")
        params = {"cid": complex_id}
    else:
        # 좌표가 있는 단지만. 좌표가 없으면 공간판정 자체가 불가능하다.
        sql = text("""
            SELECT c.id, c.name
            FROM complex c
            WHERE c.geom IS NOT NULL
              AND (CAST(:region AS text) IS NULL
                   OR c.region_code LIKE CAST(:region AS text) || '%')
            ORDER BY c.id
            LIMIT CAST(:limit AS int)
        """)
        params = {"region": region, "limit": limit}
    with engine.connect() as conn:
        return [(r.id, r.name) for r in conn.execute(sql, params).all()]


def describe(repo: PostgisRepository, complex_id: int, name: str) -> dict:
    facts = repo.location_facts(complex_id)
    if facts is None:
        print(f"[{complex_id}] {name}: 단지를 찾을 수 없음")
        return {"complex_id": complex_id, "found": False}

    assessment = evaluate_location(facts, as_of=dt.date.today())
    nearest = min(facts.stations, key=lambda s: s.distance_m) if facts.stations else None

    print(f"\n=== [{complex_id}] {name} ===")
    if nearest:
        print(f"  최근접역   : {nearest.name} {nearest.distance_m:.0f}m "
              f"노선 {list(nearest.lines)}")
    else:
        print("  최근접역   : (없음)")
    for poi in facts.pois:
        er = "" if poi.has_emergency_room is None else f" 응급실={poi.has_emergency_room}"
        print(f"  {poi.kind:9s}: {poi.name} {poi.distance_m:.0f}m{er}")
    print(f"  학교       : {facts.school}")
    print(f"  신설계획   : {[(p.name, p.status) for p in facts.plans]}")
    print(f"  유해요소   : {[(h.kind, round(h.distance_m)) for h in facts.hazards]}")
    print(f"  -> 점수 {assessment.score} / 신뢰도 {assessment.confidence}")
    print(f"  -> 판정 '{assessment.verdict}'")
    print(f"  -> 근거 {assessment.rationale}")
    if assessment.missing:
        print(f"  -> 미확보 {list(assessment.missing)}")
    return {
        "complex_id": complex_id,
        "name": name,
        "found": True,
        "station_m": nearest.distance_m if nearest else None,
        "lines": list(nearest.lines) if nearest else [],
        "amenities": dict(assessment.amenities),
        "score": assessment.score,
        "verdict": assessment.verdict,
        "held": assessment.score is None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="입지 분석 실호출 검증")
    ap.add_argument("--region", default=None, help="시군구 5자리 접두(예: 11680 강남구)")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--complex-id", type=int, default=None)
    args = ap.parse_args(argv)

    load_env()
    engine = make_engine()
    repo = PostgisRepository(engine)

    rows = pick_complexes(engine, region=args.region, limit=args.limit,
                          complex_id=args.complex_id)
    if not rows:
        print("대상 단지가 없습니다")
        return 1

    results = [describe(repo, cid, name) for cid, name in rows]
    held = [r for r in results if r.get("held")]
    print(f"\n요약: {len(results)}개 중 판단보류 {len(held)}개 "
          f"/ 점수산출 {len(results) - len(held)}개")
    if held:
        print("  판단보류 단지:", [r["complex_id"] for r in held])
    return 0


if __name__ == "__main__":
    sys.exit(main())
