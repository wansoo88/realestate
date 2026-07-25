"""법정동코드 마스터를 `region` 테이블에 적재한다.

출처 (2026-07-25 확인)
----------------------
행정안전부 **행정표준코드관리시스템** — 법정동코드 전체자료
  · 목록/다운로드: https://www.code.go.kr/stdcode/regCodeL.do
  · 공공데이터포털 API: https://www.data.go.kr/data/15077871/openapi.do
  · 공공데이터포털 파일: https://www.data.go.kr/data/15092039/fileData.do

코드 체계 (같은 출처에서 확인)
  10자리 = 시도(2) + 시군구(3) + 읍면동(3) + 리(2)
  예) 1111010100 → 11 서울특별시 / 110 종로구 / 101 청운동 / 00

  시도 레벨   : 뒤 8자리가 00000000
  시군구 레벨 : 뒤 5자리가 00000 (시군구 3자리는 000 이 아님)
  동 레벨     : 읍면동 3자리가 000 이 아님

⚠️ **이 스크립트는 코드를 만들어 내지 않는다.** 공식 파일을 그대로 옮긴다.
   법정동은 신설·폐지·통합이 계속 일어나므로, 손으로 적은 목록은 반드시 낡는다.

사용
----
    # 1) 위 출처에서 '법정동코드 전체자료' 를 받는다 (탭 구분 텍스트)
    # 2) 적재 (기본: 수도권만)
    export TEST_DATABASE_URL=postgresql+psycopg://user:pw@host:5432/realestate
    python scripts/load_regions.py --file 법정동코드_전체자료.txt

    python scripts/load_regions.py --file <파일> --all        # 전국
    python scripts/load_regions.py --file <파일> --dry-run    # 파싱만 확인
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

#: 수도권 시도 코드. 서비스 범위가 수도권 아파트다(CLAUDE.md).
CAPITAL_SIDO = ("11", "41", "28")      # 서울특별시 · 경기도 · 인천광역시

#: 파일 인코딩 후보. 행정표준코드 배포본은 통상 CP949 다.
_ENCODINGS = ("cp949", "utf-8-sig", "utf-8")

#: 폐지된 법정동을 뜻하는 값. 이 행은 넣지 않는다 —
#: 없어진 동에 단지를 매핑하면 지역 통계가 조용히 틀어진다.
_ABOLISHED = "폐지"


@dataclass(frozen=True)
class Region:
    code: str
    sido: str
    sigungu: str | None
    dong: str | None

    @property
    def level(self) -> str:
        if self.code[2:5] == "000":
            return "시도"
        if self.code[5:10] == "00000":
            return "시군구"
        return "읍면동"


def _read_lines(path: Path) -> list[str]:
    """인코딩을 추정해 읽는다. 틀린 인코딩으로 읽으면 한글이 깨진 채 적재된다."""
    raw = path.read_bytes()
    for enc in _ENCODINGS:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        # 한글이 보이면 맞게 읽은 것으로 본다
        if any("가" <= ch <= "힣" for ch in text[:5000]):
            print(f"[INFO] 인코딩 추정: {enc}")
            return text.splitlines()
    raise SystemExit(f"[FAIL] 인코딩을 판별하지 못했습니다: {path}")


def parse_file(path: Path, *, capital_only: bool = True) -> list[Region]:
    lines = _read_lines(path)
    out: list[Region] = []
    skipped_abolished = skipped_other = 0

    for i, line in enumerate(lines):
        if not line.strip():
            continue
        # 탭 구분이 표준이나, 배포본에 따라 쉼표인 경우가 있어 둘 다 받는다.
        cols = line.split("\t") if "\t" in line else line.split(",")
        cols = [c.strip().strip('"') for c in cols]
        if len(cols) < 2 or not cols[0].isdigit() or len(cols[0]) != 10:
            if i == 0:
                continue                      # 헤더 줄
            skipped_other += 1
            continue

        code, name = cols[0], cols[1]
        status = cols[2] if len(cols) > 2 else "존재"
        if _ABOLISHED in status:
            skipped_abolished += 1
            continue
        if capital_only and code[:2] not in CAPITAL_SIDO:
            continue

        parts = name.split()
        if not parts:
            skipped_other += 1
            continue

        sido = parts[0]
        if code[2:5] == "000":                       # 시도
            sigungu, dong = None, None
        elif code[5:10] == "00000":                  # 시군구 ('수원시 장안구' 처럼 둘일 수 있다)
            sigungu = " ".join(parts[1:]) or None
            dong = None
        else:                                        # 읍면동/리
            dong = parts[-1]
            sigungu = " ".join(parts[1:-1]) or None

        out.append(Region(code=code, sido=sido, sigungu=sigungu, dong=dong))

    print(f"[INFO] 파싱 {len(out)}건 "
          f"(폐지 제외 {skipped_abolished} · 형식불일치 {skipped_other})")
    return out


def load(regions: list[Region], url: str) -> int:
    from sqlalchemy import create_engine, text

    engine = create_engine(url, pool_pre_ping=True)
    sql = text("""
        INSERT INTO region (code, sido, sigungu, dong)
        VALUES (:code, :sido, :sigungu, :dong)
        ON CONFLICT (code) DO UPDATE SET
            sido = EXCLUDED.sido,
            sigungu = EXCLUDED.sigungu,
            dong = EXCLUDED.dong
    """)
    try:
        with engine.begin() as conn:
            # geom 은 건드리지 않는다 — 경계 폴리곤은 별도 출처(행정경계 SHP)이고
            # 여기서 NULL 로 덮으면 이미 적재된 경계가 날아간다.
            conn.execute(sql, [r.__dict__ for r in regions])
        return len(regions)
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="법정동코드 → region 적재")
    ap.add_argument("--file", required=True, help="법정동코드 전체자료 (탭 구분 텍스트)")
    ap.add_argument("--all", action="store_true", help="전국 (기본: 수도권만)")
    ap.add_argument("--dry-run", action="store_true", help="적재하지 않고 파싱만")
    args = ap.parse_args(argv)

    path = Path(args.file)
    if not path.exists():
        print(f"[FAIL] 파일이 없습니다: {path}")
        print("       행정표준코드관리시스템에서 '법정동코드 전체자료' 를 받으세요:")
        print("       https://www.code.go.kr/stdcode/regCodeL.do")
        return 2

    regions = parse_file(path, capital_only=not args.all)
    if not regions:
        print("[FAIL] 적재할 행이 없습니다. 파일 형식을 확인하세요.")
        return 1

    by_level: dict[str, int] = {}
    for r in regions:
        by_level[r.level] = by_level.get(r.level, 0) + 1
    for level, n in sorted(by_level.items()):
        print(f"  {level}: {n}건")

    print("  예시:")
    for r in regions[:3]:
        print(f"    {r.code}  {r.sido} {r.sigungu or ''} {r.dong or ''}".rstrip())

    if args.dry_run:
        print("[DONE] --dry-run 이므로 적재하지 않았습니다.")
        return 0

    url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL", "")
    if not url:
        print("[FAIL] TEST_DATABASE_URL(또는 DATABASE_URL)이 필요합니다.")
        return 2

    n = load(regions, url)
    print(f"[DONE] region 적재 {n}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
