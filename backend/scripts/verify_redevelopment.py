"""정비사업 판정 실호출 검증 — **실제 DB 의 단지**로 근거 문자열을 눈으로 본다.

왜 필요한가
-----------
단위 테스트는 내가 만든 픽스처로 돈다. 그 픽스처가 현실과 다르면 테스트는 전부 통과하면서
화면에는 이상한 문장이 뜬다. 그래서 **운영 DB 의 실제 단지**로 한 번 찍어 본다.

    python scripts/verify_redevelopment.py                     # 대표 단지 자동 선정
    python scripts/verify_redevelopment.py --complex-id 22 4337
    python scripts/verify_redevelopment.py --name 은마 목동신시가지3

⚠️ **정보가 없는 단지도 반드시 함께 출력한다.** '미확보'가 '없음'으로 보이지 않는지
   확인하는 것이 이 스크립트의 절반이다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import load_env, make_engine  # noqa: E402

from app.domain.redevelopment.analysis import (  # noqa: E402
    PURPOSE_INVEST,
    PURPOSE_LIVE,
    assert_no_cost_estimate,
    assess_redevelopment,
)
from app.repositories.postgis import PostgisRepository  # noqa: E402

#: 정보가 있는 대표 단지(재건축 단계가 서로 다른 것들) + **정보가 없는 단지**.
DEFAULT_NAMES = ["은마", "주공아파트 5단지", "상계주공5(저층)", "목동신시가지3", "한보미도맨션1"]

_PICK_BY_NAME = """
    SELECT c.id, c.name, c.built_year, rg.sigungu
      FROM complex c LEFT JOIN region rg ON rg.code = c.region_code
     WHERE c.name = :name
     ORDER BY c.id LIMIT 1
"""
_PICK_BY_ID = """
    SELECT c.id, c.name, c.built_year, rg.sigungu
      FROM complex c LEFT JOIN region rg ON rg.code = c.region_code
     WHERE c.id = :cid
"""
#: 정비사업 정보가 **없는** 단지 하나(대조군). 구축이면서 매칭이 안 된 것을 고른다.
_PICK_UNMATCHED = """
    SELECT c.id, c.name, c.built_year, rg.sigungu
      FROM complex c LEFT JOIN region rg ON rg.code = c.region_code
     WHERE c.built_year IS NOT NULL AND c.built_year <= 1990
       AND NOT EXISTS (SELECT 1 FROM redev_project_complex pc WHERE pc.complex_id = c.id)
     ORDER BY c.id LIMIT :limit
"""


def show(repo, row, purposes=(PURPOSE_LIVE, PURPOSE_INVEST)) -> None:
    from datetime import date

    project = repo.redevelopment_for_complex(row.id)
    print("=" * 78)
    print(f"#{row.id} {row.name} ({row.sigungu or '?'} · 준공 {row.built_year or '미상'})")
    for purpose in purposes:
        out = assess_redevelopment(project, purpose=purpose, as_of=date.today())
        label = "실거주" if purpose == PURPOSE_LIVE else "투자"
        print(f"\n  [{label}] score={out.score}  confidence={out.confidence}  "
              f"available={out.available}")
        print(f"  verdict : {out.verdict}")
        print(f"  근거    : {out.rationale}")
        for sev, detail in out.risks:
            print(f"  리스크  : ({sev}) {detail}")
        for up in out.upsides:
            print(f"  호재    : {up}")
        for mv in out.must_verify:
            print(f"  직접확인: {mv}")
        for m in out.missing:
            print(f"  미확보  : {m}")
        # 나가는 문장 전부를 분담금 금액 검사에 통과시킨다(실데이터에서도 한 번 더).
        assert_no_cost_estimate(out.rationale, out.verdict,
                                *(d for _, d in out.risks), *out.upsides,
                                *out.must_verify, *out.missing)
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description="정비사업 판정 실호출 검증")
    ap.add_argument("--complex-id", type=int, nargs="*", default=[])
    ap.add_argument("--name", nargs="*", default=[])
    ap.add_argument("--unmatched", type=int, default=1,
                    help="정비사업 정보가 없는 단지를 이만큼 함께 출력(기본 1)")
    args = ap.parse_args()

    load_env()
    engine = make_engine()
    repo = PostgisRepository(engine=engine)

    from sqlalchemy import text

    rows = []
    with engine.connect() as conn:
        for cid in args.complex_id:
            row = conn.execute(text(_PICK_BY_ID), {"cid": cid}).first()
            if row:
                rows.append(row)
        for name in (args.name or (DEFAULT_NAMES if not args.complex_id else [])):
            row = conn.execute(text(_PICK_BY_NAME), {"name": name}).first()
            if row:
                rows.append(row)
            else:
                print(f"(단지명 '{name}' 을 찾지 못했습니다 — 건너뜁니다)")
        if args.unmatched > 0:
            rows += list(conn.execute(text(_PICK_UNMATCHED),
                                      {"limit": args.unmatched}).all())

    if not rows:
        raise SystemExit("[FAIL] 출력할 단지가 없습니다.")
    for row in rows:
        show(repo, row)
    print("모든 출력 문장이 '분담금 금액 없음' 검사를 통과했습니다.")


if __name__ == "__main__":
    main()
