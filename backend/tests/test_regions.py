"""지역코드 — 설정 가드와 법정동코드 파서 (DB 없이 검증).

여기서 막으려는 사고는 하나다: **낡거나 빈 지역코드로 수집을 도는 것.**
없어진 코드로 수집하면 0건이 돌아오는데, 그게 "그 지역에 거래가 없었다"와
구분되지 않는다. 조용히 비는 데이터가 이 제품에서 가장 위험한 실패다.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

from app.core.regions import (
    CAPITAL_SIDO,
    READY_STATUS,
    RegionConfigError,
    capital_sigungu_codes,
    config_as_of,
    load_capital_sigungu,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


def _load_script(name: str):
    """scripts/ 는 패키지가 아니라 경로로 불러온다.

    exec 전에 sys.modules 에 등록해야 한다 — 스크립트가
    `from __future__ import annotations` + `@dataclass` 를 쓰는데,
    dataclasses 가 애노테이션을 풀 때 모듈을 sys.modules 에서 찾는다.
    """
    path = BACKEND_DIR / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write(tmp_path, cfg: dict) -> Path:
    p = tmp_path / "regions.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return p


def _generated(**over) -> dict:
    cfg = {
        "version": "2026-07-25", "status": READY_STATUS,
        "source": "s", "source_url": "u", "as_of": "2026-07-25",
        "sido": dict(CAPITAL_SIDO),
        "sigungu": [
            {"code": "11680", "sido": "서울특별시", "name": "강남구"},
            {"code": "41135", "sido": "경기도", "name": "성남시 분당구"},
            {"code": "28185", "sido": "인천광역시", "name": "연수구"},
        ],
    }
    cfg.update(over)
    return cfg


# ---------------------------------------------------------------------------
# 설정 가드
# ---------------------------------------------------------------------------

def test_수도권_시도코드():
    """10자리 = 시도2 + 시군구3 + 읍면동3 + 리2 (행정표준코드관리시스템)."""
    assert set(CAPITAL_SIDO) == {"11", "41", "28"}
    assert CAPITAL_SIDO["11"] == "서울특별시"


def test_채워지지_않은_설정은_거부한다(tmp_path):
    """빈 껍데기로 수집을 돌리는 사고를 막는다."""
    with pytest.raises(RegionConfigError) as exc:
        load_capital_sigungu(_write(tmp_path, _generated(status="unfilled")))
    # 어떻게 채우는지까지 알려줘야 실제로 막힌 사람이 진행할 수 있다
    assert "load_regions.py" in str(exc.value)
    assert "손으로 코드를 적지 마세요" in str(exc.value)


def test_저장소_기본설정은_아직_미채움_상태다():
    """커밋된 config/regions_capital.yaml 은 생성 전이라 거부돼야 정상이다."""
    with pytest.raises(RegionConfigError):
        load_capital_sigungu(REPO_ROOT / "config" / "regions_capital.yaml")


def test_파일이_없으면_거부한다(tmp_path):
    with pytest.raises(RegionConfigError, match="없습니다"):
        load_capital_sigungu(tmp_path / "없는파일.yaml")


def test_생성된_설정을_읽는다(tmp_path):
    p = _write(tmp_path, _generated())
    sgg = load_capital_sigungu(p)
    assert [s.code for s in sgg] == ["11680", "41135", "28185"]
    assert sgg[1].name == "성남시 분당구"
    assert sgg[0].sido_code == "11"
    assert capital_sigungu_codes(p) == ["11680", "41135", "28185"]
    assert config_as_of(p).isoformat() == "2026-07-25"


def test_수도권_밖_코드는_거부한다(tmp_path):
    """서비스 범위는 수도권이다. 부산(26)이 섞이면 수집이 조용히 범위를 넘는다."""
    cfg = _generated(sigungu=[{"code": "26110", "sido": "부산광역시", "name": "중구"}])
    with pytest.raises(RegionConfigError, match="수도권"):
        load_capital_sigungu(_write(tmp_path, cfg))


@pytest.mark.parametrize("bad", ["1168", "116800", "1168A", ""])
def test_시군구코드는_5자리_숫자여야_한다(tmp_path, bad):
    """LAWD_CD 는 5자리다. 길이가 틀리면 실거래가 API 가 0건을 돌려준다."""
    cfg = _generated(sigungu=[{"code": bad, "sido": "서울특별시", "name": "x"}])
    with pytest.raises(RegionConfigError, match="5자리"):
        load_capital_sigungu(_write(tmp_path, cfg))


def test_빈_목록은_거부한다(tmp_path):
    with pytest.raises(RegionConfigError, match="비어 있습니다"):
        load_capital_sigungu(_write(tmp_path, _generated(sigungu=[])))


# ---------------------------------------------------------------------------
# 법정동코드 파서 (scripts/load_regions.py)
# ---------------------------------------------------------------------------

SAMPLE = "\n".join([
    "법정동코드\t법정동명\t폐지여부",
    "1100000000\t서울특별시\t존재",
    "1111000000\t서울특별시 종로구\t존재",
    "1111010100\t서울특별시 종로구 청운동\t존재",
    "4113500000\t경기도 성남시 분당구\t존재",
    "4113510100\t경기도 성남시 분당구 정자동\t존재",
    "2818500000\t인천광역시 연수구\t존재",
    "1111010200\t서울특별시 종로구 없어진동\t폐지",
    "2611000000\t부산광역시 중구\t존재",
])


@pytest.fixture()
def regions_mod():
    return _load_script("load_regions")


def test_레벨을_코드로_판별한다(tmp_path, regions_mod):
    p = tmp_path / "codes.txt"
    p.write_text(SAMPLE, encoding="cp949")
    rows = {r.code: r for r in regions_mod.parse_file(p)}

    assert rows["1100000000"].level == "시도"
    assert rows["1111000000"].level == "시군구"
    assert rows["1111010100"].level == "읍면동"


def test_폐지된_법정동은_적재하지_않는다(tmp_path, regions_mod):
    """없어진 동에 단지를 매핑하면 지역 통계가 조용히 틀어진다."""
    p = tmp_path / "codes.txt"
    p.write_text(SAMPLE, encoding="cp949")
    codes = {r.code for r in regions_mod.parse_file(p)}
    assert "1111010200" not in codes


def test_수도권만_기본_적재한다(tmp_path, regions_mod):
    p = tmp_path / "codes.txt"
    p.write_text(SAMPLE, encoding="cp949")

    codes = {r.code for r in regions_mod.parse_file(p)}
    assert "2611000000" not in codes                      # 부산 제외
    assert {"1100000000", "4113510100", "2818500000"} <= codes

    all_codes = {r.code for r in regions_mod.parse_file(p, capital_only=False)}
    assert "2611000000" in all_codes                       # --all 이면 포함


def test_구가_있는_시는_시군구가_두_토막이다(tmp_path, regions_mod):
    """'성남시 분당구' 를 '분당구' 로만 저장하면 다른 시의 같은 구와 섞인다."""
    p = tmp_path / "codes.txt"
    p.write_text(SAMPLE, encoding="cp949")
    rows = {r.code: r for r in regions_mod.parse_file(p)}

    jeongja = rows["4113510100"]
    assert jeongja.sido == "경기도"
    assert jeongja.sigungu == "성남시 분당구"
    assert jeongja.dong == "정자동"

    cheongun = rows["1111010100"]
    assert (cheongun.sigungu, cheongun.dong) == ("종로구", "청운동")


@pytest.mark.parametrize("encoding", ["cp949", "utf-8"])
def test_인코딩을_추정해_읽는다(tmp_path, regions_mod, encoding):
    """틀린 인코딩으로 읽으면 한글이 깨진 채 그대로 적재된다."""
    p = tmp_path / "codes.txt"
    p.write_text(SAMPLE, encoding=encoding)
    rows = {r.code: r for r in regions_mod.parse_file(p)}
    assert rows["1111010100"].dong == "청운동"


def test_쉼표_구분_파일도_읽는다(tmp_path, regions_mod):
    """배포본에 따라 CSV 로 오는 경우가 있다."""
    p = tmp_path / "codes.csv"
    p.write_text(SAMPLE.replace("\t", ","), encoding="cp949")
    rows = {r.code: r for r in regions_mod.parse_file(p)}
    assert rows["1111010100"].dong == "청운동"
