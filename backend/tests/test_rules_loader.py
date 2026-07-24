"""세율 설정 로더 테스트.

여기서 검증하는 것은 계산이 아니라 **가드레일**이다.
출처 없는 세율이나 빈 값이 시스템에 들어오지 못하게 막는 것이 이 로더의 존재 이유다.
"""
from __future__ import annotations

import datetime as dt

import pytest
import yaml

from app.domain.rules.loader import Provenance, RuleValidationError, load_rules


def test_템플릿은_로딩이_거부된다(production_rules_path):
    """config/tax_rules.yaml 은 값이 비어 있으므로 절대 로딩되면 안 된다."""
    with pytest.raises(RuleValidationError) as exc:
        load_rules(production_rules_path)

    problems = "\n".join(exc.value.problems)
    assert "unverified" in problems, "status 검증이 동작해야 한다"
    assert "rate_pct" in problems, "빈 세율을 잡아내야 한다"


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
