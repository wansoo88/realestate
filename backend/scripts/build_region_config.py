"""`region` 테이블 → `config/regions_capital.yaml` 생성.

`scripts/load_regions.py` 로 공식 법정동코드를 적재한 뒤 실행한다.
**코드를 만들어 내지 않고** DB 에 적재된 공식 값에서 시군구만 뽑는다.

사용
----
    export TEST_DATABASE_URL=postgresql+psycopg://user:pw@host:5432/realestate
    python scripts/build_region_config.py
    python scripts/build_region_config.py --dry-run     # 파일을 쓰지 않고 목록만 출력
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.regions import CAPITAL_SIDO, DEFAULT_PATH, READY_STATUS  # noqa: E402

SOURCE = "행정안전부 행정표준코드관리시스템 — 법정동코드 전체자료"
SOURCE_URL = "https://www.code.go.kr/stdcode/regCodeL.do"

#: 시군구 레벨 = 뒤 5자리가 00000 이고 시군구 3자리가 000 이 아닌 행.
#: '수원시' 와 '수원시 장안구' 가 둘 다 시군구 레벨로 존재한다.
#: 실거래가 API 의 LAWD_CD 는 **구가 있으면 구 단위**를 쓰므로 둘 다 넣고,
#: 어느 쪽을 쓸지는 수집기가 정하게 목록에 그대로 남긴다.
_QUERY = """
    SELECT DISTINCT ON (substr(code, 1, 5))
           substr(code, 1, 5) AS code5, sido, sigungu
    FROM region
    WHERE substr(code, 3, 3) <> '000'
      AND substr(code, 1, 2) = ANY(CAST(:sido AS text[]))
      AND sigungu IS NOT NULL
    ORDER BY substr(code, 1, 5), code
"""


def fetch(url: str) -> list[dict[str, str]]:
    from sqlalchemy import create_engine, text

    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(_QUERY),
                                {"sido": list(CAPITAL_SIDO)}).all()
    finally:
        engine.dispose()
    return [
        {"code": r.code5, "sido": (r.sido or "").strip(),
         "name": (r.sigungu or "").strip()}
        for r in rows
    ]


def render(entries: list[dict[str, str]], as_of: dt.date) -> str:
    lines = [
        "# regions_capital.yaml — 수도권 시군구 코드 (수집 배치 `run_daily` 입력)",
        "#",
        "# ⚠️ 이 파일은 **자동 생성**됩니다. 손으로 고치지 마세요.",
        "#    법정동은 신설·폐지·통합이 일어나므로, 자료를 갱신한 뒤 다시 생성하세요:",
        "#      python scripts/load_regions.py --file 법정동코드_전체자료.txt",
        "#      python scripts/build_region_config.py",
        "#",
        f"# 생성일: {as_of.isoformat()}",
        "",
        f'version: "{as_of.isoformat()}"',
        f"status: {READY_STATUS}",
        "",
        f'source: "{SOURCE}"',
        f'source_url: "{SOURCE_URL}"',
        f'as_of: "{as_of.isoformat()}"',
        "",
        "# 10자리 = 시도2 + 시군구3 + 읍면동3 + 리2",
        "sido:",
    ]
    for code, name in CAPITAL_SIDO.items():
        lines.append(f'  "{code}": {name}')
    lines += [
        "",
        "# 5자리 시군구 코드 = 국토교통부 실거래가 API 의 LAWD_CD 파라미터.",
        f"# 총 {len(entries)}건.",
        "sigungu:",
    ]
    for e in entries:
        lines.append(f'  - {{ code: "{e["code"]}", sido: {e["sido"]}, name: {e["name"]} }}')
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="region → regions_capital.yaml 생성")
    ap.add_argument("--out", default=str(DEFAULT_PATH))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--as-of", help="생성일(YYYY-MM-DD). 기본: 오늘")
    args = ap.parse_args(argv)

    url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL", "")
    if not url:
        print("[FAIL] TEST_DATABASE_URL(또는 DATABASE_URL)이 필요합니다.")
        return 2

    entries = fetch(url)
    if not entries:
        print("[FAIL] region 에 수도권 시군구가 없습니다.")
        print("       먼저: python scripts/load_regions.py --file <법정동코드_전체자료.txt>")
        return 1

    by_sido: dict[str, int] = {}
    for e in entries:
        by_sido[e["sido"]] = by_sido.get(e["sido"], 0) + 1
    print(f"[INFO] 시군구 {len(entries)}건")
    for sido, n in sorted(by_sido.items()):
        print(f"  {sido}: {n}건")
    print("  예시: " + ", ".join(f'{e["code"]} {e["name"]}' for e in entries[:5]))

    as_of = dt.date.fromisoformat(args.as_of) if args.as_of else dt.date.today()
    content = render(entries, as_of)

    if args.dry_run:
        print("\n" + content)
        print("[DONE] --dry-run 이므로 파일을 쓰지 않았습니다.")
        return 0

    out = Path(args.out)
    out.write_text(content, encoding="utf-8")
    print(f"[DONE] 생성: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
