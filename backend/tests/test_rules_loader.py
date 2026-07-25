"""세율 설정 로더 테스트.

여기서 검증하는 것은 계산이 아니라 **가드레일**이다.
출처 없는 세율이나 빈 값이 시스템에 들어오지 못하게 막는 것이 이 로더의 존재 이유다.
"""
from __future__ import annotations

import datetime as dt

import pytest
import yaml

from app.domain.rules.loader import (
    ProgressiveFormula,
    Provenance,
    RuleValidationError,
    load_rules,
)

PROV = {"source": "s", "source_url": "u", "as_of": "2026-07-01"}


def _base_config(**overrides) -> dict:
    """로딩을 통과하는 최소 설정. 확장 스키마 테스트의 뼈대."""
    cfg = {
        "version": "x", "status": "verified",
        "acquisition_tax": [{"id": "a", "when": {}, "rate_pct": 1.0, **PROV}],
        "brokerage_fee": [{"id": "b", "when": {}, "rate_pct": 0.4, **PROV}],
        "lending": {
            "ltv": {"rate_pct": 70, **PROV},
            "dsr": {"rate_pct": 40, **PROV},
        },
        "fixed_costs": {"registration_krw": 0, "moving_reserve_krw": 0, **PROV},
    }
    cfg.update(overrides)
    return cfg


def _write(tmp_path, cfg: dict, name: str = "rules.yaml"):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return p


def test_운영_세율은_검증본으로_로딩된다(production_rules_path):
    """config/tax_rules.yaml 은 공식 출처로 채워진 검증본이어야 한다.

    (과거엔 빈 템플릿이라 로딩 거부를 검증했으나, ORDER 2026-07-25-04-data 로
     지방세법·공인중개사법 시행규칙·금융위 자료를 확인해 채웠다.
     실제값 회귀 검증은 test_tax_rules_real.py 가 담당한다.)
    """
    rules = load_rules(production_rules_path)
    assert rules.status == "verified"
    # 빈 값(null rate)이 하나라도 있으면 load_rules 가 예외를 던지므로, 여기 도달했다는
    # 것 자체가 모든 구간에 세율이 채워졌다는 뜻이다.
    assert rules.acquisition_tax and rules.brokerage_fee


def test_빈_세율은_여전히_거부된다(tmp_path):
    """가드레일 회귀 방지: rate_pct 가 비면 status 와 무관하게 거부돼야 한다."""
    bad = {
        "version": "x", "status": "verified",
        "acquisition_tax": [{"id": "a", "when": {}, "rate_pct": None,
                             "source": "s", "source_url": "u", "as_of": "2026-01-01"}],
        "brokerage_fee": [{"id": "b", "when": {}, "rate_pct": 0.4,
                           "source": "s", "source_url": "u", "as_of": "2026-01-01"}],
        "lending": {
            "ltv": {"rate_pct": 70, "source": "s", "source_url": "u", "as_of": "2026-01-01"},
            "dsr": {"rate_pct": 40, "source": "s", "source_url": "u", "as_of": "2026-01-01"},
        },
        "fixed_costs": {"registration_krw": 0, "moving_reserve_krw": 0,
                        "source": "s", "source_url": "u", "as_of": "2026-01-01"},
    }
    p = tmp_path / "empty_rate.yaml"
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(RuleValidationError) as exc:
        load_rules(p)
    assert any("rate_pct" in x for x in exc.value.problems)


def test_픽스처는_정상_로딩된다(test_rules):
    assert test_rules.status == "verified"
    assert test_rules.lending_rule("ltv").rate_pct == 70.0
    assert test_rules.lending_rule("dsr").rate_pct == 40.0
    assert test_rules.fixed_costs["registration_krw"] == 1_000_000


def test_출처가_없으면_거부한다(tmp_path):
    bad = {
        "version": "x", "status": "verified",
        "acquisition_tax": [{"id": "a", "when": {}, "rate_pct": 1.0}],  # source 없음
        "brokerage_fee": [{"id": "b", "when": {}, "rate_pct": 0.4,
                           "source": "s", "source_url": "u", "as_of": "2026-01-01"}],
        "lending": {
            "ltv": {"rate_pct": 70, "source": "s", "source_url": "u", "as_of": "2026-01-01"},
            "dsr": {"rate_pct": 40, "source": "s", "source_url": "u", "as_of": "2026-01-01"},
        },
        "fixed_costs": {"registration_krw": 0, "moving_reserve_krw": 0,
                        "source": "s", "source_url": "u", "as_of": "2026-01-01"},
    }
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")

    with pytest.raises(RuleValidationError) as exc:
        load_rules(p)
    assert any("출처 정보 누락" in x for x in exc.value.problems)


def test_잘못된_기준일자는_거부한다(tmp_path):
    bad = {
        "version": "x", "status": "verified",
        "acquisition_tax": [{"id": "a", "when": {}, "rate_pct": 1.0,
                             "source": "s", "source_url": "u", "as_of": "어제"}],
        "brokerage_fee": [{"id": "b", "when": {}, "rate_pct": 0.4,
                           "source": "s", "source_url": "u", "as_of": "2026-01-01"}],
        "lending": {
            "ltv": {"rate_pct": 70, "source": "s", "source_url": "u", "as_of": "2026-01-01"},
            "dsr": {"rate_pct": 40, "source": "s", "source_url": "u", "as_of": "2026-01-01"},
        },
        "fixed_costs": {"registration_krw": 0, "moving_reserve_krw": 0,
                        "source": "s", "source_url": "u", "as_of": "2026-01-01"},
    }
    p = tmp_path / "bad2.yaml"
    p.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")

    with pytest.raises(RuleValidationError) as exc:
        load_rules(p)
    assert any("as_of 형식 오류" in x for x in exc.value.problems)


def test_구간_매칭_순서(test_rules):
    """위에서부터 먼저 맞는 구간이 적용된다. 조건에 쓰인 사실이 없으면 매칭 실패."""
    small = test_rules.acquisition_bracket(
        houses_owned=1, price=500_000_000, area=84.0, regulated=False)
    assert small.id == "t_first_small"

    big = test_rules.acquisition_bracket(
        houses_owned=1, price=1_500_000_000, area=120.0, regulated=False)
    assert big.id == "t_first_other"

    multi = test_rules.acquisition_bracket(
        houses_owned=2, price=500_000_000, area=84.0, regulated=False)
    assert multi.id == "t_multi"


def test_모르는_사실은_매칭_실패로_본다(test_rules):
    """area 를 모르면 '85㎡ 이하' 구간을 적용하지 않는다 — 추정하지 않는다."""
    bracket = test_rules.acquisition_bracket(houses_owned=1, price=500_000_000)
    assert bracket.id == "t_first_other", "면적 미상일 때 소형 특례를 임의 적용하면 안 된다"


def test_오래된_기준일자는_경고한다():
    old = Provenance(source="s", source_url="u", as_of=dt.date(2020, 1, 1))
    assert old.is_stale(dt.date(2026, 7, 24))

    fresh = Provenance(source="s", source_url="u", as_of=dt.date(2026, 7, 1))
    assert not fresh.is_stale(dt.date(2026, 7, 24))


def test_evidence_형식(test_rules):
    """근거는 agent_finding.evidence 에 바로 들어갈 수 있어야 한다 (G2)."""
    ev = test_rules.lending_rule("ltv").provenance.to_evidence("LTV 상한 70%")
    assert set(ev) == {"claim", "source", "source_url", "as_of"}
    assert ev["as_of"] == "2026-07-01"


# ===========================================================================
# 확장 스키마 — 절대한도 · 스트레스 DSR · 누진 산식 밴드
#   ORDER 2026-07-25-10-arch. **계산 적용은 engine(re-domain) 몫**이고
#   여기서는 "로더가 값을 정확히 표현·로딩하는가"만 본다.
# ===========================================================================

# --- 하위호환 --------------------------------------------------------------

def test_확장필드가_없어도_그대로_로딩된다(test_rules):
    """확장 필드가 없는 설정(픽스처)은 깨지지 않고 '한도 없음·가산 0'으로 동작한다.

    (운영 config/tax_rules.yaml 은 ORDER 2026-07-25-15-data 로 절대한도·스트레스 DSR·
     누진밴드가 채워졌다 — 더는 '확장 없음' 예시가 아니다. 그 실제값 검증은
     test_tax_rules_real.py 가 담당한다.)
    """
    rules = test_rules
    assert rules.lending_caps == ()
    assert rules.lending_stress == ()
    # 없으면 '한도 없음'·'가산 0' — 기존 계산 결과와 동일하다
    assert rules.absolute_cap_krw(region_group="수도권") is None
    assert rules.stress_rate_pct(region_group="수도권") == 0.0
    # 고정 요율 구간은 예전처럼 동작
    acq = rules.acquisition_bracket(houses_owned=1, price=500_000_000,
                                    area=84.0, regulated=False)
    assert acq.is_progressive is False
    assert acq.rate_pct_for(price=500_000_000) == acq.rate_pct


# --- 수도권 6억 절대한도 ---------------------------------------------------

def test_절대한도를_지역조건부로_로딩한다(tmp_path):
    cfg = _base_config()
    cfg["lending"]["absolute_cap"] = [
        {"id": "cap_capital_600m", "when": {"region_group": "수도권"},
         "absolute_cap_krw": 600_000_000, **PROV},
    ]
    rules = load_rules(_write(tmp_path, cfg))

    assert rules.absolute_cap_krw(region_group="수도권") == 600_000_000
    # 조건에 안 맞으면 한도 없음 — 비수도권까지 6억으로 묶으면 과소 산정이 된다
    assert rules.absolute_cap_krw(region_group="비수도권") is None
    # 지역을 모르면 적용하지 않는다(모르면 추정하지 않는다는 로더 원칙)
    assert rules.absolute_cap_krw() is None

    cap = rules.absolute_cap(region_group="수도권")
    assert cap.id == "cap_capital_600m"
    assert cap.provenance.to_evidence("주담대 한도 6억")["source"] == "s"


def test_한도가_겹치면_가장_작은_것이_적용된다(tmp_path):
    """큰 쪽을 고르면 빌릴 수 없는 금액을 빌릴 수 있다고 말하게 된다."""
    cfg = _base_config()
    cfg["lending"]["absolute_cap"] = [
        {"id": "cap_a", "when": {"region_group": "수도권"},
         "absolute_cap_krw": 600_000_000, **PROV},
        {"id": "cap_b", "when": {"region_group": "수도권"},
         "absolute_cap_krw": 400_000_000, **PROV},
    ]
    rules = load_rules(_write(tmp_path, cfg))
    assert rules.absolute_cap(region_group="수도권").id == "cap_b"


def test_단일_매핑_형태의_한도도_받는다(tmp_path):
    cfg = _base_config()
    cfg["lending"]["absolute_cap"] = {"absolute_cap_krw": 600_000_000, **PROV}
    rules = load_rules(_write(tmp_path, cfg))
    assert rules.absolute_cap_krw() == 600_000_000     # when 없음 = 무조건


@pytest.mark.parametrize("bad, expect", [
    ({"absolute_cap_krw": None, **PROV}, "absolute_cap_krw 가 비어 있습니다"),
    ({"absolute_cap_krw": 0, **PROV}, "0 보다 커야 합니다"),
    ({"absolute_cap_krw": "6억", **PROV}, "숫자가 아닙니다"),
    ({"absolute_cap_krw": 600_000_000}, "출처 정보 누락"),
])
def test_잘못된_절대한도는_거부한다(tmp_path, bad, expect):
    cfg = _base_config()
    cfg["lending"]["absolute_cap"] = [bad]
    with pytest.raises(RuleValidationError) as exc:
        load_rules(_write(tmp_path, cfg))
    assert any(expect in p for p in exc.value.problems), exc.value.problems


# --- 스트레스 DSR ----------------------------------------------------------

def test_스트레스_가산금리를_로딩한다(tmp_path):
    cfg = _base_config()
    cfg["lending"]["stress_dsr"] = [
        {"id": "stress_capital", "when": {"region_group": "수도권"},
         "stress_rate_pct": 1.5, **PROV},
        {"id": "stress_other", "when": {"region_group": "비수도권"},
         "stress_rate_pct": 0.75, **PROV},
    ]
    rules = load_rules(_write(tmp_path, cfg))

    assert rules.stress_rate_pct(region_group="수도권") == 1.5
    assert rules.stress_rate_pct(region_group="비수도권") == 0.75
    assert rules.stress_rate_pct() == 0.0              # 모르면 가산 없음
    assert rules.stress_rule(region_group="수도권").id == "stress_capital"


def test_가산금리가_겹치면_가장_높은_것이_적용된다(tmp_path):
    """가산금리는 높을수록 한도가 준다 — 겹칠 때 높은 쪽이 보수적이다."""
    cfg = _base_config()
    cfg["lending"]["stress_dsr"] = [
        {"id": "s1", "when": {}, "stress_rate_pct": 0.75, **PROV},
        {"id": "s2", "when": {}, "stress_rate_pct": 1.5, **PROV},
    ]
    rules = load_rules(_write(tmp_path, cfg))
    assert rules.stress_rule().id == "s2"


def test_음수_가산금리는_거부한다(tmp_path):
    """음수면 한도가 늘어난다 — 오타 하나로 예산이 과대 산정된다."""
    cfg = _base_config()
    cfg["lending"]["stress_dsr"] = [{"stress_rate_pct": -1.0, **PROV}]
    with pytest.raises(RuleValidationError) as exc:
        load_rules(_write(tmp_path, cfg))
    assert any("음수일 수 없습니다" in p for p in exc.value.problems)


# --- 6~9억 누진 산식 밴드 --------------------------------------------------

def test_누진산식이_구간경계에서_정확하다():
    """지방세법 §11①8: 세율% = 취득가액(억) × 2/3 − 3 (6~9억)."""
    f = ProgressiveFormula(basis="price", unit_krw=100_000_000,
                           coefficient=2 / 3, constant=-3.0,
                           min_rate_pct=1.0, max_rate_pct=3.0)
    assert f.rate_pct_at(600_000_000) == pytest.approx(1.0)
    assert f.rate_pct_at(750_000_000) == pytest.approx(2.0)
    assert f.rate_pct_at(900_000_000) == pytest.approx(3.0)
    # 클램프 — 계수를 잘못 적어도 음수 세율이나 터무니없는 값이 나가지 않는다
    assert f.rate_pct_at(100_000_000) == 1.0
    assert f.rate_pct_at(2_000_000_000) == 3.0


def test_누진밴드가_고정요율_구간과_공존한다(tmp_path):
    cfg = _base_config()
    cfg["acquisition_tax"] = [
        {"id": "flat_le6", "when": {"price_max": 600_000_000}, "rate_pct": 1.0,
         "extras": {"local_education_pct": 0.1}, **PROV},
        {"id": "prog_6_9", "when": {"price_min": 600_000_001, "price_max": 900_000_000},
         "rate_pct": 2.0,                       # 산식 미적용 호출부용 폴백
         "progressive": {"basis": "price", "unit_krw": 100_000_000,
                         "coefficient": 2 / 3, "constant": -3.0,
                         "min_rate_pct": 1.0, "max_rate_pct": 3.0},
         "extras_ratio": {"local_education_ratio": 0.1}, **PROV},
        {"id": "flat_over9", "when": {}, "rate_pct": 3.0,
         "extras": {"local_education_pct": 0.3}, **PROV},
    ]
    rules = load_rules(_write(tmp_path, cfg))

    flat = rules.acquisition_bracket(price=500_000_000)
    assert flat.id == "flat_le6" and flat.is_progressive is False
    assert flat.total_rate_pct(price=500_000_000) == pytest.approx(1.1)

    prog = rules.acquisition_bracket(price=750_000_000)
    assert prog.id == "prog_6_9" and prog.is_progressive is True
    # 본세 2.0% + 지방교육세(본세×1/10) 0.2% = 2.2%
    assert prog.rate_pct_for(price=750_000_000) == pytest.approx(2.0)
    assert prog.total_rate_pct(price=750_000_000) == pytest.approx(2.2)
    # 같은 밴드 안에서 가격이 다르면 세율도 연속적으로 달라진다(근사 아님)
    assert prog.rate_pct_for(price=650_000_000) == pytest.approx(4 / 3)

    over = rules.acquisition_bracket(price=1_000_000_000)
    assert over.id == "flat_over9"


def test_누진밴드는_기준사실이_없으면_폴백값을_쓴다(tmp_path):
    cfg = _base_config()
    cfg["acquisition_tax"] = [
        {"id": "prog", "when": {}, "rate_pct": 2.0,
         "progressive": {"basis": "price", "unit_krw": 100_000_000,
                         "coefficient": 2 / 3, "constant": -3.0,
                         "min_rate_pct": 1.0, "max_rate_pct": 3.0}, **PROV},
    ]
    rules = load_rules(_write(tmp_path, cfg))
    assert rules.acquisition_bracket().rate_pct_for() == 2.0


@pytest.mark.parametrize("prog, expect", [
    ({"unit_krw": 100_000_000, "coefficient": 0.66, "constant": -3.0,
      "min_rate_pct": 1.0}, "max_rate_pct 가 비어 있습니다"),
    ({"unit_krw": 0, "coefficient": 0.66, "constant": -3.0,
      "min_rate_pct": 1.0, "max_rate_pct": 3.0}, "unit_krw 는 0 보다 커야 합니다"),
    ({"unit_krw": 100_000_000, "coefficient": 0.66, "constant": -3.0,
      "min_rate_pct": 3.0, "max_rate_pct": 1.0}, "min_rate_pct 가 max_rate_pct 보다 큽니다"),
])
def test_잘못된_누진산식은_거부한다(tmp_path, prog, expect):
    cfg = _base_config()
    cfg["acquisition_tax"] = [{"id": "p", "when": {}, "rate_pct": 2.0,
                               "progressive": prog, **PROV}]
    with pytest.raises(RuleValidationError) as exc:
        load_rules(_write(tmp_path, cfg))
    assert any(expect in p for p in exc.value.problems), exc.value.problems


def test_계약문서_검산표와_일치한다(tmp_path):
    """`docs/domain/lending-rules-contract.md` §4 표 그대로.

    문서와 코드가 갈라지면 re-domain 이 잘못된 기대값으로 engine 을 짠다.
    표를 여기 박아 두면 둘 중 하나가 바뀌는 순간 이 테스트가 깨진다.
    """
    cfg = _base_config()
    cfg["acquisition_tax"] = [
        {"id": "std_le6_small",
         "when": {"houses_owned_max": 2, "price_max": 600_000_000, "area_max": 85},
         "rate_pct": 1.0,
         "extras": {"local_education_pct": 0.1, "rural_special_pct": 0.0}, **PROV},
        {"id": "std_6_9_small",
         "when": {"houses_owned_max": 2, "price_min": 600_000_001,
                  "price_max": 900_000_000, "area_max": 85},
         "rate_pct": 2.0,
         "progressive": {"basis": "price", "unit_krw": 100_000_000,
                         "coefficient": 2 / 3, "constant": -3.0,
                         "min_rate_pct": 1.0, "max_rate_pct": 3.0},
         "extras_ratio": {"local_education_ratio": 0.1},
         "extras": {"rural_special_pct": 0.0}, **PROV},
        {"id": "std_over9_small",
         "when": {"houses_owned_max": 2, "area_max": 85},
         "rate_pct": 3.0, "extras": {"local_education_pct": 0.3}, **PROV},
    ]
    rules = load_rules(_write(tmp_path, cfg))

    def tax_at(price: int) -> tuple[str, int]:
        b = rules.acquisition_bracket(houses_owned=1, price=price,
                                      area=84.0, regulated=False)
        return b.id, int(price * b.total_rate_pct(price=price) / 100.0)

    # (취득가, 예상 취득세액) — 문서 §4
    for price, expected in [
        (600_000_000, 6_600_000),
        (650_000_000, 9_533_333),
        (750_000_000, 16_500_000),
        (850_000_000, 24_933_333),
        (900_000_000, 29_700_000),
    ]:
        _, tax = tax_at(price)
        assert tax == expected, f"{price:,}원에서 {tax:,} != {expected:,}"

    # 경계 연속성: 6억에서 아래 구간과, 9억에서 위 구간과 정확히 이어진다
    assert tax_at(600_000_000)[0] == "std_le6_small"
    assert tax_at(901_000_000)[0] == "std_over9_small"
    below = rules.acquisition_bracket(houses_owned=1, price=600_000_000,
                                      area=84.0, regulated=False)
    above = rules.acquisition_bracket(houses_owned=1, price=901_000_000,
                                      area=84.0, regulated=False)
    assert below.total_rate_pct(price=600_000_000) == pytest.approx(1.1)
    assert above.total_rate_pct(price=901_000_000) == pytest.approx(3.3)


def test_이분탐색_전제_단조성이_유지된다(tmp_path):
    """engine 은 f(P) 단조 비감소를 전제로 이분탐색한다(engine.py 머리말).

    누진 밴드를 넣어도 세액이 가격에 대해 줄어드는 구간이 생기면 안 된다.
    """
    cfg = _base_config()
    cfg["acquisition_tax"] = [
        {"id": "le6", "when": {"price_max": 600_000_000}, "rate_pct": 1.0,
         "extras": {"local_education_pct": 0.1}, **PROV},
        {"id": "prog", "when": {"price_min": 600_000_001, "price_max": 900_000_000},
         "rate_pct": 2.0,
         "progressive": {"basis": "price", "unit_krw": 100_000_000,
                         "coefficient": 2 / 3, "constant": -3.0,
                         "min_rate_pct": 1.0, "max_rate_pct": 3.0},
         "extras_ratio": {"local_education_ratio": 0.1}, **PROV},
        {"id": "over9", "when": {}, "rate_pct": 3.0,
         "extras": {"local_education_pct": 0.3}, **PROV},
    ]
    rules = load_rules(_write(tmp_path, cfg))

    prev = -1
    for price in range(500_000_000, 1_000_000_001, 10_000_000):
        b = rules.acquisition_bracket(price=price)
        tax = int(price * b.total_rate_pct(price=price) / 100.0)
        assert tax >= prev, f"{price:,}원에서 세액이 감소했다 ({prev:,} → {tax:,})"
        prev = tax


# --- 갱신 경보 -------------------------------------------------------------

def test_오래된_한도_가산금리도_경고에_잡힌다(tmp_path):
    """규제는 자주 바뀐다. 새 규칙도 갱신 누락 탐지 대상이어야 한다."""
    old = {"source": "s", "source_url": "u", "as_of": "2020-01-01"}
    cfg = _base_config()
    cfg["lending"]["absolute_cap"] = [
        {"id": "cap_old", "absolute_cap_krw": 600_000_000, **old}]
    cfg["lending"]["stress_dsr"] = [
        {"id": "stress_old", "stress_rate_pct": 1.5, **old}]
    rules = load_rules(_write(tmp_path, cfg))

    stale = rules.stale_rules(dt.date(2026, 7, 25))
    assert any("cap_old" in s for s in stale)
    assert any("stress_old" in s for s in stale)
