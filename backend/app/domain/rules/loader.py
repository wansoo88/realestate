"""세율·대출규제 설정 로더.

설계 근거: docs/02-design/agents/02-finance-tax-advisor.md

이 모듈의 존재 이유
-------------------
부동산 세제와 대출 규제는 자주 바뀐다. 세율을 코드에 박아두면 **조용히 틀린 답을 내는
시스템**이 된다. 그래서 모든 세율·한도는 설정 파일에서만 오고, 이 로더가 아래를 강제한다.

1. 모든 규칙에 `source` · `source_url` · `as_of` 가 있어야 한다. 없으면 **로딩 거부**.
2. 숫자 값이 비어 있으면(`null`) **로딩 거부**. "대충 이쯤"이 들어갈 자리가 없다.
3. `status: unverified` 인 파일은 프로덕션에서 거부한다. 공식 출처 대조 전에는 못 쓴다.
4. `as_of` 가 오래되면 경고를 남긴다(운영 중 갱신 누락 탐지).

이 규칙들이 답답해 보일 수 있는데, 세율 하나 틀리면 사용자 예산이 수천만 원 어긋난다.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# 이 기간이 지난 규칙은 갱신 경고를 낸다.
STALE_AFTER_DAYS = 180

REQUIRED_PROVENANCE = ("source", "source_url", "as_of")


class RuleValidationError(ValueError):
    """설정 파일이 사용 가능한 상태가 아님. 문제 목록을 함께 담는다."""

    def __init__(self, problems: list[str], path: Path | None = None):
        self.problems = problems
        self.path = path
        head = f"세율 설정을 사용할 수 없습니다 ({path})" if path else "세율 설정을 사용할 수 없습니다"
        super().__init__(head + ":\n" + "\n".join(f"  - {p}" for p in problems))


@dataclass(frozen=True)
class Provenance:
    """이 숫자가 어디서 왔는지. 근거 없는 값은 제품에 들어가지 않는다."""

    source: str
    source_url: str
    as_of: _dt.date

    def is_stale(self, today: _dt.date | None = None) -> bool:
        today = today or _dt.date.today()
        return (today - self.as_of).days > STALE_AFTER_DAYS

    def to_evidence(self, claim: str) -> dict[str, Any]:
        """agent_finding.evidence 에 그대로 넣을 수 있는 형태."""
        return {
            "claim": claim,
            "source": self.source,
            "source_url": self.source_url,
            "as_of": self.as_of.isoformat(),
        }


@dataclass(frozen=True)
class Bracket:
    """구간별 요율 규칙 하나."""

    id: str
    rate_pct: float
    when: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, float] = field(default_factory=dict)
    provenance: Provenance | None = None

    def matches(self, **facts: Any) -> bool:
        """`when` 조건을 모두 만족하는지.

        지원 접미사: `_max`(이하), `_min`(이상), 그 외는 완전일치.
        조건에 쓰인 사실이 주어지지 않으면 **매칭 실패**로 본다(모르면 적용하지 않는다).
        """
        for key, expected in self.when.items():
            if key.endswith("_max"):
                actual = facts.get(key[:-4])
                if actual is None or actual > expected:
                    return False
            elif key.endswith("_min"):
                actual = facts.get(key[:-4])
                if actual is None or actual < expected:
                    return False
            else:
                if facts.get(key) != expected:
                    return False
        return True


@dataclass(frozen=True)
class RuleSet:
    version: str
    status: str
    acquisition_tax: tuple[Bracket, ...]
    brokerage_fee: tuple[Bracket, ...]
    lending: dict[str, Bracket]
    fixed_costs: dict[str, int]
    fixed_costs_provenance: Provenance | None = None

    # -- 조회 -------------------------------------------------------------
    def acquisition_bracket(self, **facts: Any) -> Bracket:
        return _first_match(self.acquisition_tax, "취득세", **facts)

    def brokerage_bracket(self, **facts: Any) -> Bracket:
        return _first_match(self.brokerage_fee, "중개보수", **facts)

    def lending_rule(self, key: str) -> Bracket:
        rule = self.lending.get(key)
        if rule is None:
            raise RuleValidationError([f"대출 규칙 '{key}' 가 설정에 없습니다"])
        return rule

    def stale_rules(self, today: _dt.date | None = None) -> list[str]:
        out: list[str] = []
        for group in (self.acquisition_tax, self.brokerage_fee, tuple(self.lending.values())):
            for b in group:
                if b.provenance and b.provenance.is_stale(today):
                    out.append(f"{b.id} (as_of {b.provenance.as_of})")
        return out


def _first_match(brackets: tuple[Bracket, ...], label: str, **facts: Any) -> Bracket:
    for b in brackets:
        if b.matches(**facts):
            return b
    raise RuleValidationError(
        [f"{label} 구간을 찾지 못했습니다. 조건={facts}. "
         f"설정에 해당 구간이 없으면 추정하지 않고 계산을 중단합니다."]
    )


# --------------------------------------------------------------------------
# 파싱
# --------------------------------------------------------------------------

def _parse_provenance(raw: dict[str, Any], where: str, problems: list[str]) -> Provenance | None:
    missing = [k for k in REQUIRED_PROVENANCE if not raw.get(k)]
    if missing:
        problems.append(f"{where}: 출처 정보 누락 {missing} — 세율·한도는 출처 없이 쓸 수 없습니다")
        return None
    as_of = raw["as_of"]
    if isinstance(as_of, str):
        try:
            as_of = _dt.date.fromisoformat(as_of)
        except ValueError:
            problems.append(f"{where}: as_of 형식 오류 '{as_of}' (YYYY-MM-DD 이어야 함)")
            return None
    elif isinstance(as_of, _dt.datetime):
        as_of = as_of.date()
    elif not isinstance(as_of, _dt.date):
        problems.append(f"{where}: as_of 형식 오류 '{as_of}'")
        return None
    return Provenance(source=str(raw["source"]), source_url=str(raw["source_url"]), as_of=as_of)


def _parse_bracket(raw: dict[str, Any], where: str, problems: list[str]) -> Bracket | None:
    rid = str(raw.get("id") or where)
    rate = raw.get("rate_pct")
    if rate is None:
        problems.append(
            f"{where} ({rid}): rate_pct 가 비어 있습니다 — 공식 출처에서 확인한 값을 채우세요"
        )
        return None
    if not isinstance(rate, (int, float)):
        problems.append(f"{where} ({rid}): rate_pct 가 숫자가 아닙니다 ({rate!r})")
        return None

    extras: dict[str, float] = {}
    for k, v in (raw.get("extras") or {}).items():
        if v is None:
            problems.append(f"{where} ({rid}): extras.{k} 가 비어 있습니다")
            continue
        extras[str(k)] = float(v)

    prov = _parse_provenance(raw, f"{where} ({rid})", problems)
    return Bracket(
        id=rid,
        rate_pct=float(rate),
        when=dict(raw.get("when") or {}),
        extras=extras,
        provenance=prov,
    )


def load_rules(path: str | Path, *, allow_unverified: bool = False) -> RuleSet:
    """세율 설정을 읽고 검증한다. 문제가 하나라도 있으면 RuleValidationError.

    `allow_unverified=True` 는 **테스트 전용**이다. 프로덕션 경로에서 쓰지 말 것.
    """
    path = Path(path)
    if not path.exists():
        raise RuleValidationError([f"설정 파일이 없습니다: {path}"], path)

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    problems: list[str] = []

    version = str(raw.get("version") or "")
    status = str(raw.get("status") or "unverified")
    if not version:
        problems.append("version 이 없습니다")
    if status != "verified" and not allow_unverified:
        problems.append(
            f"status 가 '{status}' 입니다. 공식 출처와 대조해 값을 채운 뒤 "
            "'verified' 로 바꿔야 사용할 수 있습니다"
        )

    acq = tuple(
        b for b in (
            _parse_bracket(r, "acquisition_tax", problems)
            for r in (raw.get("acquisition_tax") or [])
        ) if b is not None
    )
    if not acq:
        problems.append("acquisition_tax 구간이 하나도 없습니다")

    brk = tuple(
        b for b in (
            _parse_bracket(r, "brokerage_fee", problems)
            for r in (raw.get("brokerage_fee") or [])
        ) if b is not None
    )
    if not brk:
        problems.append("brokerage_fee 구간이 하나도 없습니다")

    lending: dict[str, Bracket] = {}
    for key, r in (raw.get("lending") or {}).items():
        b = _parse_bracket({**r, "id": r.get("id", key)}, f"lending.{key}", problems)
        if b is not None:
            lending[str(key)] = b
    for required in ("ltv", "dsr"):
        if required not in lending:
            problems.append(f"lending.{required} 규칙이 없습니다")

    fixed_raw = raw.get("fixed_costs") or {}
    fixed: dict[str, int] = {}
    for k, v in fixed_raw.items():
        if k in REQUIRED_PROVENANCE:
            continue
        if v is None:
            problems.append(f"fixed_costs.{k} 가 비어 있습니다")
            continue
        fixed[str(k)] = int(v)
    fixed_prov = (
        _parse_provenance(fixed_raw, "fixed_costs", problems) if fixed_raw else None
    )

    if problems:
        raise RuleValidationError(problems, path)

    return RuleSet(
        version=version,
        status=status,
        acquisition_tax=acq,
        brokerage_fee=brk,
        lending=lending,
        fixed_costs=fixed,
        fixed_costs_provenance=fixed_prov,
    )
