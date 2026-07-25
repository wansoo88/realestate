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

#: `lending` 아래에서 **요율이 아닌** 규칙으로 해석되는 예약 키.
#: 나머지 키(ltv·dsr·dti…)는 지금까지처럼 단일 요율 Bracket 으로 읽는다(하위호환).
LENDING_CAP_KEY = "absolute_cap"      # 대출 절대한도 (예: 수도권 주담대 6억)
LENDING_STRESS_KEY = "stress_dsr"     # 스트레스 DSR 가산금리


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


def _when_matches(when: dict[str, Any], facts: dict[str, Any]) -> bool:
    """`when` 조건을 모두 만족하는지.

    지원 접미사: `_max`(이하), `_min`(이상), 그 외는 완전일치.
    조건에 쓰인 사실이 주어지지 않으면 **매칭 실패**로 본다(모르면 적용하지 않는다).
    """
    for key, expected in when.items():
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
class ProgressiveFormula:
    """연속 누진 산식 밴드.

    구간별 고정요율로는 표현할 수 없는 **연속 함수** 세율을 담는다.
    예) 지방세법 §11①8 6~9억 주택 취득세: `세율% = 취득가액(억) × 2/3 − 3`
        → basis=price, unit_krw=1e8, coefficient=2/3, constant=-3

        rate_pct = (basis값 / unit_krw) × coefficient + constant   (clamp 적용)

    `min_rate_pct`·`max_rate_pct` 는 **필수**다. 계수를 잘못 적으면 음수 세율이나
    터무니없는 값이 조용히 나오는데, 그 오류는 수천만 원 단위로 예산을 틀어놓는다.
    구간 경계에서 클램프가 곧 정답이기도 하다(6억→1.0%, 9억→3.0%).
    """

    basis: str
    unit_krw: float
    coefficient: float
    constant: float
    min_rate_pct: float
    max_rate_pct: float

    def rate_pct_at(self, basis_value: float) -> float:
        raw = (basis_value / self.unit_krw) * self.coefficient + self.constant
        return min(self.max_rate_pct, max(self.min_rate_pct, raw))


@dataclass(frozen=True)
class Bracket:
    """구간별 요율 규칙 하나.

    `progressive` 가 있으면 **연속 누진 밴드**다. 이때 `rate_pct` 는 산식을 적용하지
    못하는 호출부를 위한 **폴백 대표값**이며(하위호환), 실제 세율은
    `rate_pct_for(price=...)` 로 얻는다.
    """

    id: str
    rate_pct: float
    when: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, float] = field(default_factory=dict)
    provenance: Provenance | None = None
    #: 연속 누진 산식(없으면 고정 요율 구간)
    progressive: ProgressiveFormula | None = None
    #: **본세율에 비례**하는 부가세율. 예) 지방교육세 = 취득세율 × 1/10 → 0.1
    #: (`extras` 는 거래금액 대비 %, 이쪽은 본세율 대비 배율 — 단위가 다르다)
    extras_ratio: dict[str, float] = field(default_factory=dict)

    def matches(self, **facts: Any) -> bool:
        return _when_matches(self.when, facts)

    @property
    def is_progressive(self) -> bool:
        return self.progressive is not None

    def rate_pct_for(self, **facts: Any) -> float:
        """이 구간의 **본세율(%)**. 누진 밴드면 산식으로, 아니면 고정 요율.

        산식의 기준 사실(`basis`)이 주어지지 않으면 폴백 대표값을 쓴다.
        `when` 에 그 사실의 범위 조건이 있으면 매칭 단계에서 이미 걸러지므로
        정상 경로에서는 여기 오지 않는다.
        """
        if self.progressive is None:
            return self.rate_pct
        value = facts.get(self.progressive.basis)
        if value is None:
            return self.rate_pct
        return self.progressive.rate_pct_at(float(value))

    def total_rate_pct(self, **facts: Any) -> float:
        """본세율 + 정률 부가세(`extras.*_pct`) + 본세 비례 부가세(`extras_ratio`).

        전부 **거래금액 대비 %** 로 환산해 더한다(engine 의 퍼센트 규약과 동일).
        """
        base = self.rate_pct_for(**facts)
        flat = sum(v for k, v in self.extras.items() if k.endswith("_pct"))
        derived = sum(base * ratio for ratio in self.extras_ratio.values())
        return base + flat + derived


@dataclass(frozen=True)
class LendingCap:
    """대출 **절대한도**(원). 요율과 무관하게 대출금을 이 금액 이하로 묶는다.

    예) 6.27 대책(2025) 수도권 주택담보대출 6억원 한도.
    이게 빠지면 실구매 가능액이 **과대 산정**된다 — 지금까지 가장 큰 오차 원인이다.

    ⚠️ 계산 적용(min)은 engine(re-domain) 몫이다. 로더는 값과 출처만 제공한다.
    """

    id: str
    cap_krw: int
    when: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def matches(self, **facts: Any) -> bool:
        return _when_matches(self.when, facts)


@dataclass(frozen=True)
class LendingStress:
    """스트레스 DSR 가산금리(%p).

    DSR 한도를 계산할 때 **실제 금리 + 가산금리**로 상환액을 산정해 한도를 줄인다.
    지역·단계별로 다르므로(예: 수도권 1.5%p / 비수도권 0.75%p) 조건부 목록을 지원한다.

    ⚠️ 금리 가산 적용도 engine(re-domain) 몫이다.
    """

    id: str
    stress_rate_pct: float
    when: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def matches(self, **facts: Any) -> bool:
        return _when_matches(self.when, facts)


@dataclass(frozen=True)
class RuleSet:
    version: str
    status: str
    acquisition_tax: tuple[Bracket, ...]
    brokerage_fee: tuple[Bracket, ...]
    lending: dict[str, Bracket]
    fixed_costs: dict[str, int]
    fixed_costs_provenance: Provenance | None = None
    #: 대출 절대한도(조건부). 설정에 없으면 빈 튜플 — 기존 설정 파일도 그대로 로딩된다.
    lending_caps: tuple[LendingCap, ...] = ()
    #: 스트레스 DSR 가산금리(조건부).
    lending_stress: tuple[LendingStress, ...] = ()

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

    # -- 대출 절대한도 / 스트레스 DSR --------------------------------------

    def absolute_cap(self, **facts: Any) -> LendingCap | None:
        """조건에 맞는 절대한도 중 **가장 작은 것**. 없으면 None.

        여러 한도가 겹치면 가장 낮은 금액이 실제 제약이다. 큰 쪽을 고르면
        빌릴 수 없는 금액을 빌릴 수 있다고 말하게 된다.
        """
        matched = [c for c in self.lending_caps if c.matches(**facts)]
        return min(matched, key=lambda c: c.cap_krw) if matched else None

    def absolute_cap_krw(self, **facts: Any) -> int | None:
        cap = self.absolute_cap(**facts)
        return cap.cap_krw if cap else None

    def stress_rule(self, **facts: Any) -> LendingStress | None:
        """조건에 맞는 스트레스 가산금리 중 **가장 높은 것**. 없으면 None.

        가산금리는 높을수록 한도가 줄어든다. 겹칠 때 높은 쪽을 고르는 게 보수적이다.
        """
        matched = [s for s in self.lending_stress if s.matches(**facts)]
        return max(matched, key=lambda s: s.stress_rate_pct) if matched else None

    def stress_rate_pct(self, **facts: Any) -> float:
        """가산금리(%p). 설정에 없으면 **0.0** — 기존 동작과 같다(하위호환)."""
        rule = self.stress_rule(**facts)
        return rule.stress_rate_pct if rule else 0.0

    def stale_rules(self, today: _dt.date | None = None) -> list[str]:
        out: list[str] = []
        groups: tuple[tuple[Any, ...], ...] = (
            self.acquisition_tax, self.brokerage_fee, tuple(self.lending.values()),
            self.lending_caps, self.lending_stress,
        )
        for group in groups:
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


def _require_number(raw: dict[str, Any], key: str, where: str,
                    problems: list[str]) -> float | None:
    value = raw.get(key)
    if value is None:
        problems.append(f"{where}: {key} 가 비어 있습니다 — 공식 출처에서 확인한 값을 채우세요")
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        problems.append(f"{where}: {key} 가 숫자가 아닙니다 ({value!r})")
        return None
    return float(value)


def _parse_progressive(raw: dict[str, Any], where: str,
                       problems: list[str]) -> ProgressiveFormula | None:
    """`progressive:` 블록 → 연속 누진 산식. 계수가 하나라도 비면 로딩 거부."""
    values: dict[str, float] = {}
    for key in ("unit_krw", "coefficient", "constant", "min_rate_pct", "max_rate_pct"):
        got = _require_number(raw, key, f"{where}.progressive", problems)
        if got is None:
            return None
        values[key] = got

    if values["unit_krw"] <= 0:
        problems.append(f"{where}.progressive: unit_krw 는 0 보다 커야 합니다")
        return None
    if values["min_rate_pct"] > values["max_rate_pct"]:
        problems.append(f"{where}.progressive: min_rate_pct 가 max_rate_pct 보다 큽니다")
        return None

    return ProgressiveFormula(basis=str(raw.get("basis") or "price"), **values)


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

    extras_ratio: dict[str, float] = {}
    for k, v in (raw.get("extras_ratio") or {}).items():
        if v is None:
            problems.append(f"{where} ({rid}): extras_ratio.{k} 가 비어 있습니다")
            continue
        extras_ratio[str(k)] = float(v)

    # 누진 밴드는 선택 사항이다 — 없으면 지금까지처럼 고정 요율 구간(하위호환).
    progressive = None
    prog_raw = raw.get("progressive")
    if prog_raw is not None:
        if not isinstance(prog_raw, dict):
            problems.append(f"{where} ({rid}): progressive 는 매핑이어야 합니다")
        else:
            progressive = _parse_progressive(prog_raw, f"{where} ({rid})", problems)
            if progressive is None:
                return None

    prov = _parse_provenance(raw, f"{where} ({rid})", problems)
    return Bracket(
        id=rid,
        rate_pct=float(rate),
        when=dict(raw.get("when") or {}),
        extras=extras,
        provenance=prov,
        progressive=progressive,
        extras_ratio=extras_ratio,
    )


def _as_rule_list(raw: Any) -> list[dict[str, Any]]:
    """단일 매핑도, 조건부 목록도 받는다.

    매핑 하나면 `when` 이 없는 무조건 규칙 하나로 본다(설정을 단순하게 쓰라고).
    """
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    return []


def _parse_lending_caps(raw: Any, problems: list[str]) -> tuple[LendingCap, ...]:
    out: list[LendingCap] = []
    for i, r in enumerate(_as_rule_list(raw)):
        rid = str(r.get("id") or f"{LENDING_CAP_KEY}[{i}]")
        where = f"lending.{LENDING_CAP_KEY} ({rid})"
        cap = _require_number(r, "absolute_cap_krw", where, problems)
        if cap is None:
            continue
        if cap <= 0:
            problems.append(f"{where}: absolute_cap_krw 는 0 보다 커야 합니다")
            continue
        out.append(LendingCap(
            id=rid,
            cap_krw=int(cap),
            when=dict(r.get("when") or {}),
            provenance=_parse_provenance(r, where, problems),
        ))
    return tuple(out)


def _parse_lending_stress(raw: Any, problems: list[str]) -> tuple[LendingStress, ...]:
    out: list[LendingStress] = []
    for i, r in enumerate(_as_rule_list(raw)):
        rid = str(r.get("id") or f"{LENDING_STRESS_KEY}[{i}]")
        where = f"lending.{LENDING_STRESS_KEY} ({rid})"
        rate = _require_number(r, "stress_rate_pct", where, problems)
        if rate is None:
            continue
        if rate < 0:
            # 음수 가산금리는 한도를 **늘린다**. 오타 하나로 예산이 과대 산정된다.
            problems.append(f"{where}: stress_rate_pct 는 음수일 수 없습니다 ({rate})")
            continue
        out.append(LendingStress(
            id=rid,
            stress_rate_pct=rate,
            when=dict(r.get("when") or {}),
            provenance=_parse_provenance(r, where, problems),
        ))
    return tuple(out)


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

    lending_raw = raw.get("lending") or {}
    lending: dict[str, Bracket] = {}
    for key, r in lending_raw.items():
        # 예약 키는 요율이 아니라 한도·가산금리다. 아래에서 따로 파싱한다.
        if key in (LENDING_CAP_KEY, LENDING_STRESS_KEY):
            continue
        b = _parse_bracket({**r, "id": r.get("id", key)}, f"lending.{key}", problems)
        if b is not None:
            lending[str(key)] = b
    for required in ("ltv", "dsr"):
        if required not in lending:
            problems.append(f"lending.{required} 규칙이 없습니다")

    # 절대한도·스트레스 DSR 은 **선택 사항**이다. 없으면 빈 튜플이 되고
    # 기존 설정 파일이 그대로 로딩된다(하위호환).
    lending_caps = _parse_lending_caps(lending_raw.get(LENDING_CAP_KEY), problems)
    lending_stress = _parse_lending_stress(lending_raw.get(LENDING_STRESS_KEY), problems)

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
        lending_caps=lending_caps,
        lending_stress=lending_stress,
    )
