"""예산 상한 **조회기**(면적 → 상한). 지도와 추천이 같은 한 곳에서 만든다.

왜 이 모듈이 있는가 (CR37-1 → CR39-2)
-------------------------------------
`/map/complexes` 와 `POST /recommendations` 는 같은 질문에 답한다 — **이 물건을 내
자산으로 살 수 있는가.** 그런데 그 상한은 **한 숫자가 아니라 전용면적의 함수**다:
취득세의 농어촌특별세가 85㎡ 를 경계로 붙는다(운영 세율 · 현금 5억 · 연소득 1억 실측).

    84.00㎡ → 1,026,560,000        85.01㎡ → 1,024,580,000   (차이 1,980,000 · 0.19%)

CR37-1 로 **지도**는 항목마다 그 면적의 상한으로 판정하게 고쳤는데, **추천**은 그대로
`PropertyFacts()` 기본값 84.0 으로 만든 한 숫자로 후보를 하드 제외하고 있었다(CR39-2).
후보의 판정 단위는 `api-spec §5` 대로 **단지 × 면적대**라서, 114㎡ 후보가 84㎡ 한도로
판정됐다. 방향은 **관대**(84㎡ 한도가 더 크다) — 즉 *못 사는 후보가 통과*했다.

같은 계산을 두 벌 두면 반드시 다시 갈린다. 그래서 조회기를 여기 한 곳에 두고 라우터
(지도)와 러너(추천)가 **같은 함수**를 부른다. 라우터가 아니라 도메인에 있는 이유는
러너가 라우터를 import 하면 순환이 되기 때문이다(`routes` → `agents.recommend`).

계약 (⚠️ `None` 과 `0` 은 다르다)
---------------------------------
* **양수** — 그 금액이 상한이다.
* **`0`**  — 상한이 없다(자산 미입력 등으로 한도가 0). 호출부는 판정을 **하지 않는다**.
* **`None`** — 상한을 **세울 수 없다**(면적을 몰라 세율 구간을 못 고른다).
  84 같은 값을 가정해 채우지 않는다 — 그러면 사용자는 *다른 면적의 한도로 내린 판정*을
  자기 물건의 판정으로 읽는다(그게 CR37-1 의 본체였다).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.domain.affordability.engine import (
    acquisition_area_class,
    compute_affordability,
)
from app.domain.affordability.models import AffordabilityResult, PropertyFacts
from app.domain.rules.loader import RuleSet

#: 면적(㎡) → 그 면적의 예산 상한(원). 위 계약 참조.
BudgetFn = Callable[[float | None], int | None]

#: 면적(㎡) → 그 면적의 자금계획 결과. 면적을 모르면 `None`.
AffordabilityFn = Callable[[float | None], AffordabilityResult | None]

#: 면적을 모를 때 **결과 전체에 붙는 요약 문구**가 쓰는 기준 면적.
#: `PropertyFacts.area_m2` · `AffordabilityIn.area_m2` 의 기본값과 **같은 값이어야 한다** —
#: 다르면 "내 정보" 화면의 한도와 추천 고지의 한도가 서로 다른 숫자가 된다.
#: ⚠️ 이 값은 **후보 판정에 쓰지 않는다**(그게 CR39-2 였다). 판정은 항상 후보의 면적으로 한다.
SUMMARY_AREA_M2: float = PropertyFacts().area_m2


def fixed_budget(amount_krw: int) -> BudgetFn:
    """면적과 무관한 단일 상한(사용자가 정한 희망 매매가).

    사용자가 "9억까지 볼래"라고 정한 금액이다. 면적이 뭐든 그 숫자가 상한이므로
    **면적을 알 필요가 없다** — 면적 미상 물건도 판정한다.
    """
    def at(_area_m2: float | None) -> int | None:
        return amount_krw
    return at


def profile_affordability(borrower: Any, rules: RuleSet, purpose: str) -> AffordabilityFn:
    """자산으로 계산한 자금계획. **면적마다 다르다**(취득세 농특세 85㎡ 경계).

    `acquisition_area_class` 로 묶어 **같은 세율이 걸리는 면적은 한 번만 계산한다**
    (운영 세율이면 한 화면/한 추천에 최대 2회). 지도는 한 화면에 최대 500단지,
    추천은 후보 최대 200건이라 면적마다 이분탐색을 새로 돌리면(실측 0.75ms) 조회 SQL
    보다 오래 걸린다.

    캐시는 **이 조회기 안에서만** 산다 — 사용자 자산에서 나온 금액이라 프로세스 전역에
    남기지 않는다(요청이 끝나면 조회기와 함께 사라진다).

    ⚠️ 세율에 `progressive.basis: area` 나 모르는 `area_*` 조건이 생기면
    `acquisition_area_class` 가 **캐시를 스스로 끈다**(묶으면 틀리므로 옳은 선택이다).
    그날 계산이 면적 종류만큼 늘어 지도는 최대 500회(≈375ms), 추천은 최대 200회 늘어난다
    — **정확성은 안전하고 지연만 튄다**(SR34-2). 그 전환이 조용히 일어나지 않도록
    `test_map_budget_parity.py`·`test_recommend_budget_parity.py` 의
    "세율 구간이 같은 면적은 한 번만 계산한다"가 호출 횟수를 못박는다: 캐시가 꺼지면
    지도가 느려지기 전에 **테스트가 먼저 붉어진다**.
    """
    cache: dict[tuple[Any, ...], AffordabilityResult] = {}

    def at(area_m2: float | None) -> AffordabilityResult | None:
        # 0·음수는 면적이 아니다(수집 결손으로 0 이 들어온다). 모르는 것으로 다룬다.
        if not area_m2 or area_m2 <= 0:
            return None
        key = acquisition_area_class(rules, area_m2)
        hit = cache.get(key)
        if hit is None:
            hit = compute_affordability(
                borrower, rules,
                prop=PropertyFacts(area_m2=area_m2, purpose=purpose),
            )
            cache[key] = hit
        return hit

    return at


def summary_affordability(afford_at: AffordabilityFn) -> AffordabilityResult:
    """**기준 면적**(`SUMMARY_AREA_M2`)의 자금계획 — 결과 전체에 붙는 요약 숫자용.

    후보마다 다른 한도를 하나의 고지 문장에 담을 수는 없다. 그래서 요약은 기준 면적
    하나로 만들고, **그 면적이 무엇인지 문장에 밝힌다**(`recommend._budget_notes`).
    같은 조회기를 쓰므로 그 면적 구간의 계산이 **한 번 더 돌지 않는다**.
    """
    result = afford_at(SUMMARY_AREA_M2)
    if result is None:      # pragma: no cover - SUMMARY_AREA_M2 는 양수 상수다
        raise ValueError("기준 면적의 자금계획을 만들지 못했습니다")
    return result


def max_purchase_budget(afford_at: AffordabilityFn) -> BudgetFn:
    """자금계획 조회기 → 예산 상한 조회기(최대 실구매 가능 금액).

    같은 조회기를 넘겨 받으므로 **캐시를 공유한다** — 상한과 자금계획을 따로 계산해
    두 숫자가 갈리는 일이 없고, 계산 횟수도 늘지 않는다.
    """
    def at(area_m2: float | None) -> int | None:
        result = afford_at(area_m2)
        return None if result is None else result.max_purchase_krw
    return at


def profile_budget(borrower: Any, rules: RuleSet, purpose: str) -> BudgetFn:
    """자산으로 계산한 면적별 예산 상한(지도가 쓰는 조립).

    자금계획 결과 자체가 필요하면 `profile_affordability` 를 직접 쓰고
    `max_purchase_budget` 으로 감싼다 — 그러면 두 값이 **같은 계산**에서 나온다.
    """
    return max_purchase_budget(profile_affordability(borrower, rules, purpose))
