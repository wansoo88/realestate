"""수도권 지역코드 — 수집 배치(`run_daily`)의 입력.

왜 상수가 아니라 설정 파일인가
------------------------------
법정동은 신설·폐지·통합이 계속 일어난다. 시군구 66개를 코드에 박아 두면
언젠가 조용히 낡고, 그때 **없어진 코드로 수집을 돌면 0건이 돌아오는데
그게 "그 지역에 거래가 없었다"와 구분되지 않는다.**
그래서 목록은 공식 법정동코드에서 **생성**하고(`scripts/build_region_config.py`),
채워지지 않은 파일은 **쓰지 못하게 막는다**(세율 로더와 같은 원칙).

시도 코드 출처
--------------
행정안전부 행정표준코드관리시스템 — 법정동코드 체계
`https://www.code.go.kr/stdcode/regCodeL.do` (2026-07-25 확인)
10자리 = 시도(2) + 시군구(3) + 읍면동(3) + 리(2)
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PATH = REPO_ROOT / "config" / "regions_capital.yaml"

#: 수도권 시도 코드. 서비스 범위가 수도권 아파트다(CLAUDE.md 서비스 범위).
#: 이 셋은 체계상 고정값이라 상수로 둔다 — 바뀌는 건 그 아래 시군구다.
CAPITAL_SIDO: dict[str, str] = {
    "11": "서울특별시",
    "41": "경기도",
    "28": "인천광역시",
}

#: 이 값이 아니면 로딩을 거부한다. 빈 껍데기로 수집을 돌리는 사고를 막는다.
READY_STATUS = "generated"


class RegionConfigError(RuntimeError):
    """지역 설정을 쓸 수 없는 상태. 어떻게 채우는지 함께 알려준다."""


@dataclass(frozen=True)
class Sigungu:
    """시군구 하나. `code` 는 **5자리**(시도2+시군구3)로 국토부 실거래가 API 의
    `LAWD_CD` 파라미터에 그대로 들어간다."""

    code: str
    sido: str
    name: str

    @property
    def sido_code(self) -> str:
        return self.code[:2]


def load_capital_sigungu(path: str | Path | None = None) -> list[Sigungu]:
    """수도권 시군구 목록. 채워지지 않았으면 **예외**(추정해서 돌지 않는다)."""
    path = Path(path or DEFAULT_PATH)
    if not path.exists():
        raise RegionConfigError(
            f"지역 설정 파일이 없습니다: {path}\n"
            "  scripts/load_regions.py 로 region 을 적재한 뒤\n"
            "  scripts/build_region_config.py 로 생성하세요."
        )

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    status = str(raw.get("status") or "unfilled")
    if status != READY_STATUS:
        raise RegionConfigError(
            f"지역 설정이 '{status}' 상태입니다 ({path}).\n"
            "  공식 법정동코드로 생성해야 사용할 수 있습니다:\n"
            "    python scripts/load_regions.py --file <법정동코드_전체자료.txt>\n"
            "    python scripts/build_region_config.py\n"
            "  ⚠️ 손으로 코드를 적지 마세요 — 낡은 코드로 수집하면 0건이 돌아오는데\n"
            "     그게 '거래가 없었다'와 구분되지 않습니다."
        )

    out: list[Sigungu] = []
    for entry in raw.get("sigungu") or []:
        code = str(entry.get("code") or "").strip()
        if len(code) != 5 or not code.isdigit():
            raise RegionConfigError(f"시군구 코드는 5자리 숫자여야 합니다: {entry!r}")
        if code[:2] not in CAPITAL_SIDO:
            raise RegionConfigError(
                f"수도권(11·41·28) 밖의 코드가 있습니다: {code} — 서비스 범위 밖입니다")
        out.append(Sigungu(code=code,
                           sido=str(entry.get("sido") or CAPITAL_SIDO[code[:2]]),
                           name=str(entry.get("name") or "")))

    if not out:
        raise RegionConfigError(f"시군구 목록이 비어 있습니다: {path}")
    return out


def capital_sigungu_codes(path: str | Path | None = None) -> list[str]:
    """`run_daily` 에 그대로 넘길 5자리 코드 목록."""
    return [s.code for s in load_capital_sigungu(path)]


def config_as_of(path: str | Path | None = None) -> _dt.date | None:
    """이 목록을 언제 생성했는지. 근거 표기·갱신 판단에 쓴다."""
    path = Path(path or DEFAULT_PATH)
    if not path.exists():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    value = raw.get("as_of")
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None
