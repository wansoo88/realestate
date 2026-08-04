"""점수 함수 — **전부 `AsOfCell` 만 본다.** 원본 거래를 받지 않는다.

설계 정본: `docs/02-design/backtest.md` §2-F · §6

왜 원본 거래를 안 받는가
------------------------
누출을 하고 싶어도 손이 닿지 않게 **타입으로** 막는다. 점수 축을 새로 만드는 사람이
"이 계산엔 원본이 좀 필요한데" 하고 손을 뻗는 순간이 이 종류의 코드에서 가장 흔한
사고 지점이다. `AsOfCell` 은 이미 as-of 뷰만 거쳐 만들어졌다.

여기 있는 축 / 없는 축
----------------------
있다  : 가격매력 · 가격추세 · 환금성  — 시변 축. 과거 값을 실거래로 복원할 수 있다.
없다  : 학군 · 교통 · 생활인프라       — **과거 상태를 알 방법이 없다.** 현재 스냅샷을
        상수로 가정하면 편향의 방향이 하필 나쁜 쪽이다(지금 인프라가 좋은 곳은 그동안
        좋아졌을 확률이 높고, 그 개선이 곧 가격 상승의 원인이다 → 자기 채점 도구가
        **자기에게 유리하게** 틀린다). 근거와 대안 검토는 문서 §2-F.

점수의 단위
-----------
모든 스코어러는 **유니버스 내 백분위(0~100)** 를 돌려준다. 원값을 그대로 쓰면 축마다
단위가 달라 가중 결합이 뜻을 잃는다. 순위만 쓰는 단일 축에서는 백분위든 원값이든
결과가 같으므로, 변환의 대가는 없고 결합 가능성만 얻는다.
"""
from __future__ import annotations

import bisect
import hashlib
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from app.domain.backtest.models import AsOfCell, CellRef

# --- 축 이름 ----------------------------------------------------------------
AXIS_PRICE_ATTRACTIVENESS = "price_attractiveness"
AXIS_PRICE_TREND = "price_trend"
AXIS_LIQUIDITY = "liquidity"

#: 현행 총점 가중치(`hexagon-report-data.md §8`) 중 **백테스트가 재현할 수 있는 셋**.
#: 원문: 학군 .20 · 교통 .20 · 인프라 .15 · 환금성 .15 · 가격매력 .20 · 가격추세 .10
#: 그리고 그 문서가 스스로 적어 둔 대로 **"설계 휴리스틱이며 실측 근거 없음"** 이다.
#: 여기 값을 고치는 것은 §6 의 교정 절차를 거친 뒤에만 한다.
CURRENT_TIMEVARYING_WEIGHTS: Mapping[str, float] = {
    AXIS_PRICE_ATTRACTIVENESS: 0.20,
    AXIS_LIQUIDITY: 0.15,
    AXIS_PRICE_TREND: 0.10,
}

#: 위 셋의 합. 나머지 **0.55(학군+교통+인프라)** 는 채점 대상 밖이라는 사실을 숫자로 남긴다.
TIMEVARYING_WEIGHT_SUM = round(sum(CURRENT_TIMEVARYING_WEIGHTS.values()), 4)   # 0.45

#: 1년 환산 상수(환금성). 창이 12개월이 아닐 때 회전율을 연율로 맞춘다.
MONTHS_PER_YEAR = 12


def percentile_ranks(values: Mapping[CellRef, float | None]) -> dict[CellRef, float | None]:
    """원값 → 유니버스 내 백분위(0~100). 동점은 **중간 순위**를 나눠 갖는다.

    손으로 확인 가능한 성질(테스트가 그대로 고정한다):
      · [10, 20, 30]  → 16.667 / 50.0 / 83.333   (대칭)
      · [10, 10, 30]  → 33.333 / 33.333 / 83.333 (동점은 같은 값)
      · 값이 하나뿐  → 50.0                       (특수 분기 없이 자연히 나온다)
    None 은 None 으로 남는다 — **0 점이 아니다**(0 은 '나쁘다', None 은 '모른다').
    """
    present = sorted(v for v in values.values() if v is not None)
    total = len(present)
    if total == 0:
        return dict.fromkeys(values, None)
    ranked: dict[CellRef, float | None] = {}
    for ref, value in values.items():
        if value is None:
            ranked[ref] = None
            continue
        low = bisect.bisect_left(present, value)
        high = bisect.bisect_right(present, value)
        ranked[ref] = round((low + high) / 2 / total * 100, 4)
    return ranked


# ---------------------------------------------------------------------------
# 원값 계산 — 축 하나가 셀 하나에서 무엇을 보는가
# ---------------------------------------------------------------------------

def raw_price_attractiveness(cell: AsOfCell) -> float | None:
    """같은 (시군구, 면적대) 중위 대비 **얼마나 싼가**(%). 클수록 싸다.

    피어 중위가 없으면(피어 셀 부족) None — 비교 대상이 없는데 점수를 만들지 않는다.
    """
    peer = cell.peer_median_ppm_krw
    own = cell.price.median_ppm_krw
    if not peer or not own:
        return None
    return round((peer - own) / peer * 100, 4)


def raw_price_trend(cell: AsOfCell) -> float | None:
    """직전 창 대비 ₩/㎡ 변화율(%). **부호의 뜻이 정해져 있지 않다.**

    ⚠️ `hexagon §8` 이 이미 적었다 — 가격추세는 **비단조**다. 많이 오른 것이 더 오를지
       (모멘텀) 덜 오를지(평균회귀)를 우리는 모른다. 그래서 이 축의 부호는 백테스트가
       **정해 줘야 할 답**이지 넣어 줄 전제가 아니다. 여기서는 "많이 오른 쪽이 높은 점수"로
       두고, 국면별로 부호가 뒤집히는지를 §6-3 에서 확인한다.
    """
    now = cell.price.median_ppm_krw
    before = cell.prior_price.median_ppm_krw
    if not now or not before or not cell.prior_price.available:
        return None
    return round((now / before - 1) * 100, 4)


def raw_liquidity(cell: AsOfCell) -> float | None:
    """연율 거래회전율(%) = 창 안 거래 수 ÷ 세대수 (12/창개월 환산).

    세대수는 **상수 가정이 정당한 유일한 축**이다(준공 시 확정 — 문서 §2-E).
    """
    households = cell.total_households
    window = cell.price.window_months or 0
    if not households or households <= 0 or window <= 0:
        return None
    annualized = cell.window_trade_count * (MONTHS_PER_YEAR / window)
    return round(annualized / households * 100, 4)


#: 축 이름 → 원값 함수. **이 표가 정본이다**(축을 여기저기 흩뿌리지 않는다).
AXIS_RAW: Mapping[str, Callable[[AsOfCell], float | None]] = {
    AXIS_PRICE_ATTRACTIVENESS: raw_price_attractiveness,
    AXIS_PRICE_TREND: raw_price_trend,
    AXIS_LIQUIDITY: raw_liquidity,
}


def axis_ranks(cells: Sequence[AsOfCell], axis: str) -> dict[CellRef, float | None]:
    """한 축의 유니버스 백분위."""
    raw = AXIS_RAW[axis]
    return percentile_ranks({c.ref: raw(c) for c in cells})


# ---------------------------------------------------------------------------
# 스코어러
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Scorer:
    """이름 붙은 점수 함수. 유니버스 전체를 받아 셀별 점수를 돌려준다.

    왜 셀 하나가 아니라 유니버스를 받는가 — 가격매력·추세·회전율은 **상대값**이라
    비교 대상 없이는 점수가 되지 않는다. 축마다 몰래 전역 상태를 참조하는 것보다
    입력으로 받는 편이 정직하고 테스트가 쉽다.
    """

    name: str
    note: str
    fn: Callable[[Sequence[AsOfCell]], dict[CellRef, float | None]]

    def __call__(self, cells: Sequence[AsOfCell]) -> dict[CellRef, float | None]:
        return self.fn(list(cells))


def single_axis_scorer(axis: str) -> Scorer:
    """축 하나만 쓰는 스코어러. **가중치 교정의 1차 도구**다(문서 §6-2) —
    축 하나가 무작위 대조군을 못 이기면 가중치 조정이 아니라 **제거**가 먼저다."""
    return Scorer(
        name=f"axis:{axis}",
        note=f"{axis} 단독(유니버스 백분위)",
        fn=lambda cells: axis_ranks(cells, axis),
    )


def weighted_scorer(weights: Mapping[str, float] = CURRENT_TIMEVARYING_WEIGHTS) -> Scorer:
    """현행 가중치(시변 축만)로 결합. **없는 축은 재정규화**한다.

    재정규화 규칙은 `app/agents/scoring.py` 와 같다 — 신호가 있는 축만 넣고 나머지
    가중치는 남은 축에 비례 배분한다. 근거가 없는 축에 0점을 주면 "나쁘다"는 없는
    판정이 생기기 때문이다(0 은 나쁘다, None 은 모른다).

    ⚠️ 이 점수는 **총점의 45%만** 반영한다. 나머지 55%(학군·교통·인프라)는 과거를 몰라
       채점 대상이 아니다. 결과를 "우리 총점의 성적"이라고 부르면 안 된다.
    """
    axes = tuple(weights)

    def score(cells: Sequence[AsOfCell]) -> dict[CellRef, float | None]:
        ranks = {axis: axis_ranks(cells, axis) for axis in axes}
        out: dict[CellRef, float | None] = {}
        for cell in cells:
            num = 0.0
            den = 0.0
            for axis in axes:
                value = ranks[axis].get(cell.ref)
                if value is None:
                    continue
                num += weights[axis] * value
                den += weights[axis]
            out[cell.ref] = round(num / den, 4) if den > 0 else None
        return out

    label = " · ".join(f"{a} {weights[a]:.2f}" for a in axes)
    return Scorer(name="current_weights",
                  note=f"현행 시변 축 가중 결합({label}, 합 {sum(weights.values()):.2f}) — "
                       "학군·교통·인프라(합 0.55)는 채점 대상 밖",
                  fn=score)


def random_scorer(seed: int) -> Scorer:
    """무작위 대조군. **시드가 같으면 언제나 같은 점수**(해시 기반 — 순서·실행에 무관).

    `random.Random` 을 순회하며 쓰지 않는 이유: 그러면 셀 목록의 순서가 점수를 바꾼다.
    같은 유니버스인데 정렬만 달라도 결과가 달라지면 대조군 구실을 못 한다.
    """
    def score(cells: Sequence[AsOfCell]) -> dict[CellRef, float | None]:
        out: dict[CellRef, float | None] = {}
        for cell in cells:
            token = f"{seed}:{cell.ref.complex_id}:{cell.ref.band}".encode()
            digest = hashlib.blake2b(token, digest_size=8).digest()
            out[cell.ref] = int.from_bytes(digest, "big") / 2**64 * 100
        return out

    return Scorer(name=f"random:{seed}", note="무작위 대조군(결정적 해시)", fn=score)


def constant_scorer(value: float = 50.0) -> Scorer:
    """전부 동점. 순위가 **정렬 규칙만으로** 정해지는 극단 대조군 —
    "우리 점수가 아무 일도 안 했을 때"의 바닥선을 본다."""
    return Scorer(name="constant", note="전부 동점(정렬 규칙만으로 선택)",
                  fn=lambda cells: {c.ref: value for c in cells})


def universe_axis_summary(cells: Sequence[AsOfCell]) -> dict[str, dict[str, float | int | None]]:
    """축별 원값의 커버리지·중위. 리포트에 그대로 실린다 — **무엇이 비는지 먼저 본다**."""
    summary: dict[str, dict[str, float | int | None]] = {}
    for axis, raw in AXIS_RAW.items():
        values = [raw(c) for c in cells]
        present = [v for v in values if v is not None]
        summary[axis] = {
            "cells": len(values),
            "with_value": len(present),
            "coverage_pct": (round(len(present) / len(values) * 100, 1)
                             if values else None),
            "median": round(statistics.median(present), 4) if present else None,
        }
    return summary
