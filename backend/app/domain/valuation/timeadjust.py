"""적정가 밴드의 **시점 보정**. 순수 함수 — DB 를 모른다.

무엇을 고치는가
---------------
`fair_price_band` 는 6/12/24/36개월 창의 중위값을 적정가로 쓴다. 창 안의 거래는 시점이
흩어져 있는데 아무 보정 없이 섞이므로, 밴드 중위는 **창의 중간 시점** 가격이다.
운영 DB 실측(611,518행, 2026-07-28) — 창별 거래의 평균 시점:

    6개월창 3.2개월 전 · 12개월창 5.8개월 전 · 24개월창 11.1개월 전 · 36개월창 14.4개월 전

시장이 멈춰 있으면 상관없다. 멈춰 있지 않았다.
아래는 **운영 DB `market_price_index` 에 실제로 적재된 값**이다(시도, 2026-07-28 배치):

    2025-01 → 2026-05   서울 0.954294→1.112226 (+16.5%)
                        경기 0.983530→1.034474 (+ 5.2%)
                        인천 1.002350→1.011518 (+ 0.9%)

같은 적재값으로 12개월 창의 중위 보정배율을 계산하면 **서울 +6.8% · 경기 +2.7% ·
인천 +0.5%** 다. 이게 보정하지 않았을 때 밴드 중위가 낮게 나오는 크기이고,
지역마다 크기가 달라서 보정하지 않으면 서울 후보만 조직적으로 싸 보인다.

⚠️ 이 숫자들은 **적재된 값과 대조해서 적는다.** 예전에는 여기 탐색 단계의 다른 계산
   (서울 +26.6% 등)이 적혀 있었는데 표에 실린 값과 달랐다 — 문서가 데이터와 다르면
   다음 사람이 둘 중 어느 쪽을 믿을지 알 수 없다(CR33-4).
   지수는 **창(window)에 따라 값이 달라지는 상대값**이므로, 창을 바꾸면 여기도 바꾼다.

⛔ '미등기 = 최신 체결가' 를 쓰지 않는 이유 (실측 후 기각)
----------------------------------------------------------
미등기 비율은 계약월의 함수일 뿐이다(2026-07 95.6% · 06 87.4% · 05 67.6% · 04 32.4% ·
03 7.7% · 02 2.0% · 2025년 이전 0.4~1.8%). `registered_at IS NULL` 은 "최근 3~4개월"을
**더 나쁘게** 쓴 것이다: ① 최근 4개월 거래의 34%(등기 완료분)를 버려 표본이 줄고,
② 같은 (단지,면적,계약월) 안에서 미등기가 등기보다 +0.5~2.2% 비싸며(선택편향),
③ 새 데이터 없이 시간만 지나도 미등기→등기로 바뀌어 추정치가 흔들린다.
그래서 등기 여부는 **보지 않는다**. 계약일과 지역 지수만 쓴다.

이 모듈이 지키는 규칙
---------------------
1. **지수가 없으면 보정하지 않는다.** 없는 계수를 지어내거나 0% 로 가정하지 않는다.
2. **보정한 값과 안 한 값을 한 중위에 섞지 않는다.** 섞으면 어느 시점 가격도 아닌
   숫자가 나온다. 커버리지가 기준 미만이면 통째로 보정을 포기한다.
3. **기준월은 '오늘'이 아니다.** 신고 지연(최대 30일)으로 이번 달은 표본이 덜 차 있다.
   덜 찬 달을 기준으로 삼으면 추정치가 며칠 뒤 이유 없이 바뀐다. 그래서 **완결된
   가장 최근 달**로 환산하고, 결과에 그 달을 적는다 — "현재 시세"라고 하지 않는다.
   완결 판정은 **달력과 건수를 둘 다** 본다(`_complete_flags`). 건수만 보면 진행 중인
   달도 거래가 많으면 완결로 불린다 — 실제로 운영에서 그 일이 났다(CR33-1).
4. **말이 안 되는 보정은 거부한다.** 지수가 깨졌을 때 조용히 2배짜리 추정가를 내느니
   보정을 포기하는 편이 낫다.
"""
from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from app.domain.valuation.models import MIN_SAMPLE, TradeRow

#: 지수 층위. 시군구가 있으면 시군구, 없으면 시도. 문구에 그대로 나간다.
SCOPE_SIGUNGU = "sigungu"
SCOPE_SIDO = "sido"
SCOPE_LABEL = {SCOPE_SIGUNGU: "시군구", SCOPE_SIDO: "시도"}

#: (지역,월) 지수를 만들 최소 거래 수. 이보다 적으면 그 달 지수를 **만들지 않는다**.
#:
#: 값의 근거 — 운영 DB 로 잰 로그잔차 표준편차(2026-07-28):
#:   서울 0.1013 · 경기 0.0803 · 인천 0.0634
#: 중위의 표준오차 ≈ 1.253 × sd / √n 이므로 서울 기준:
#:   n=20 → ±2.8% · n=50 → ±1.8% · n=100 → ±1.3% · n=200 → ±0.9%
#: 우리가 고치려는 편향이 서울 ≈10% 라 ±1.8% 는 남는 장사지만 ±2.8% 는 아깝다.
#: 그래서 50 으로 둔다. 이 밑으로 떨어지는 시군구는 시도 지수로 폴백한다(`select_index`).
MIN_INDEX_MONTH_SAMPLE = 50

#: **기준월**에만 걸리는 더 높은 문턱.
#:
#: 왜 따로 두는가 — 기준월의 오차는 성격이 다르다. 개별 거래의 월 오차는 여러 거래에
#: 흩어져 중위에서 상쇄되지만, 기준월 오차는 **모든 거래에 같은 방향으로** 곱해져
#: 추정치 전체를 통째로 밀어버린다. 상쇄되지 않는 오차에는 더 큰 표본을 요구한다.
#: 서울 기준 n=150 → ±1.0%.
MIN_REFERENCE_MONTH_SAMPLE = 150

#: 완결 월 판정(건수 쪽). 그 달 표본이 직전 6개월 중위 건수의 이 비율 미만이면 '아직 덜 찼다'.
#: 실측: 2026-06 은 23,615건(직전 중위 대비 ~98%), 2026-07 은 11,965건(~50%, 진행 중).
#: ⚠️ 이 검사 **하나만으로는 부족하다**. 거래가 많은 지역은 진행 중인 달도 이 비율을
#:    넘긴다(운영 실측 4곳: 수원권선·오산·용인처인·화성병점이 2026-07-28 에 2026-07 을
#:    완결로 통과했다 — CR33-1). 달력 하한(`REPORT_LAG_DAYS`)과 **AND** 로 쓴다.
MIN_MONTH_COMPLETENESS = 0.80

#: 신고 지연 상한(일). 부동산 거래신고 등에 관한 법률상 계약일로부터 **30일 이내** 신고다.
#: 그래서 어떤 달의 거래가 다 들어왔는지는 **그 달 말일 + 30일**이 지나야 말할 수 있다.
REPORT_LAG_DAYS = 30

#: 지수 계산 방법 식별자. **방법을 바꾸면 값의 의미가 바뀐다** — 그래서 적재할 때만이
#: 아니라 **읽을 때도 걸러야** 한다(`postgis._MARKET_INDEX_SQL`). 두 방법의 값이 한
#: 지역에 섞이면 `idx(A)/idx(B)` 가 시장 변화가 아니라 방법 차이를 재게 된다.
INDEX_METHOD = "fe_median_log_ppm_v1"

#: 보정하려면 창 안 거래의 이 비율 이상이 지수를 가져야 한다. 미만이면 보정 포기.
#: (지수 있는 거래만 골라 쓰면 시점 분포가 편향되므로 부분 보정은 하지 않는다.)
MIN_ADJUST_COVERAGE = 0.80

#: 보정 배율 상한/하한. 이 밖이면 지수가 깨진 것으로 보고 **보정하지 않는다**.
#: 적재값 기준 최대 구간(서울 2024-01 0.8875 → 2026-07 1.1448, +29.0%)의 세 배 여유다.
#: ⚠️ 이 가드는 **정확도 보증이 아니다.** "+5% 가 맞는데 +25% 로 나오는" 종류의 고장은
#:    그대로 통과한다 — 잡는 것은 "지수가 통째로 깨진 경우"뿐이다(CR-033 지적).
MAX_ADJUST_RATIO = 2.0
MIN_ADJUST_RATIO = 0.5

#: 보정 미적용 사유(문구 고정 — 테스트·UI 가 같은 문자열을 본다).
REASON_NO_INDEX = "지역 시장지수가 없어 시점 보정을 하지 않았습니다"
REASON_NO_REFERENCE = "완결된 기준월이 없어 시점 보정을 하지 않았습니다"
REASON_LOW_COVERAGE = "거래 시점의 지수 확보율이 낮아 시점 보정을 하지 않았습니다"
REASON_TOO_FEW = "보정 가능한 거래가 최소 표본에 미달해 시점 보정을 하지 않았습니다"
REASON_OUT_OF_RANGE = "지수 보정 배율이 비정상 범위라 시점 보정을 하지 않았습니다"


def ym_of(date: dt.date) -> str:
    """'YYYY-MM'. 지수 키와 거래를 잇는 유일한 접점이라 한 곳에만 둔다."""
    return f"{date.year:04d}-{date.month:02d}"


@dataclass(frozen=True)
class IndexPoint:
    """한 (지역, 월) 의 지수. `value` 는 **상대값** — 다른 월과의 비만 의미가 있다."""

    ym: str
    value: float
    sample_size: int
    #: 신고 지연으로 아직 덜 찬 달인가. False 면 기준월로 쓰지 않는다.
    is_complete: bool = True

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise ValueError(f"지수는 양수여야 합니다: {self.ym}={self.value}")


@dataclass(frozen=True)
class MarketIndex:
    """한 지역의 월별 시장지수.

    `reference_ym` 은 "이 지수로 환산해 말할 수 있는 시점"이다. 오늘이 아니라 **완결된
    가장 최근 달** — 그래서 결과 문구가 "현재 시세"가 아니라 "2026-05 시점 환산"이 된다.
    """

    region_code: str
    scope: str
    points: dict[str, IndexPoint]

    @property
    def reference_ym(self) -> str | None:
        """환산 기준월. **완결됐고 표본이 충분한** 달 중 가장 최근. 없으면 None.

        표본 문턱이 개별 월(`MIN_INDEX_MONTH_SAMPLE`)보다 높은 이유는
        `MIN_REFERENCE_MONTH_SAMPLE` 주석 참조 — 기준월 오차는 상쇄되지 않는다.
        """
        done = [p.ym for p in self.points.values()
                if p.is_complete and p.sample_size >= MIN_REFERENCE_MONTH_SAMPLE]
        return max(done) if done else None

    @property
    def reference_point(self) -> IndexPoint | None:
        ref = self.reference_ym
        return self.points.get(ref) if ref else None

    def ratio_to_reference(self, ym: str) -> float | None:
        """`ym` 시점 가격을 기준월 수준으로 옮기는 배율. 둘 중 하나라도 없으면 None."""
        ref = self.reference_point
        src = self.points.get(ym)
        if ref is None or src is None:
            return None
        return ref.value / src.value

    @property
    def scope_label(self) -> str:
        return SCOPE_LABEL.get(self.scope, self.scope)


@dataclass(frozen=True)
class TimeAdjustment:
    """시점 보정 결과. **적용하지 않았으면 왜 안 했는지 반드시 남는다.**"""

    applied: bool
    reference_ym: str | None = None
    scope: str | None = None
    region_code: str | None = None
    #: 보정으로 중위가 몇 % 움직였는가. 방향이 곧 시장 방향이다(음수 가능).
    shift_pct: float | None = None
    #: 창 안 거래 중 지수를 가진 비율(%).
    coverage_pct: float | None = None
    sample_size: int = 0
    reason: str | None = None

    @property
    def basis(self) -> str:
        """근거 라벨. `dong_effect` 의 `basis` 와 같은 역할 — 실측/미보정을 구분한다."""
        return "trade_time_adjusted" if self.applied else "trade_raw"

    def note(self) -> str | None:
        """사람이 읽는 한 줄. **보정했으면 어느 시점으로 환산했는지 반드시 말한다.**"""
        if not self.applied:
            return self.reason
        scope = SCOPE_LABEL.get(self.scope or "", self.scope or "")
        return (
            f"{self.reference_ym} 시점으로 환산한 추정치입니다"
            f"({scope} 시장지수, 거래 {self.sample_size}건 보정, {self.shift_pct:+.1f}%). "
            f"현재 실제 거래가는 다를 수 있습니다."
        )


def open_ym(as_of: dt.date) -> str:
    """신고가 아직 덜 들어왔을 수 있는 **가장 이른 달**. 이 달부터는 완결로 보지 않는다.

    `as_of - REPORT_LAG_DAYS` 가 속한 달이다. 이 값보다 **작은** 달만 완결 후보가 된다:

        as_of 2026-07-28 → 2026-06-28 → "2026-06" → 완결 후보는 2026-05 까지
        as_of 2026-07-31 → 2026-07-01 → "2026-07" → 완결 후보는 2026-06 까지

    두 번째 줄이 이 규칙의 정확도를 보여준다 — 2026-06 의 마지막 계약(6/30)은 7/30 까지
    신고할 수 있으므로 7/31 이 되어야 '다 들어왔다'고 말할 수 있고, 규칙이 정확히
    그날부터 허용한다. `as_of` 를 **인자로 받는** 이유는 순수 함수를 지키기 위해서다 —
    함수 안에서 오늘을 읽으면 테스트가 시간에 흔들리고, 실패가 하루짜리가 된다.
    """
    return ym_of(as_of - dt.timedelta(days=REPORT_LAG_DAYS))


def _complete_flags(counts: dict[str, int], *, as_of: dt.date,
                    lookback: int = 6) -> dict[str, bool]:
    """각 월이 '표본이 다 찼는가'. **달력 하한 AND 건수 검사** — 둘 다 만족해야 완결이다.

    ① **달력**(`ym < open_ym(as_of)`) — 그 달이 완전히 지났고 신고 지연(30일)까지
       지났는가. 이게 없으면 *진행 중인 달*이 완결로 불린다. 건수가 많은 지역에서
       실제로 그렇게 됐고(운영 4곳, 581단지), 그 달의 지수는 **선택편향**을 먹는다 —
       월중에 신고된 거래는 무작위 표본이 아니다(같은 (단지,면적,계약월) 안에서
       미등기가 등기보다 +0.5~2.2% 비싸다는 실측이 그대로 적용된다). 게다가 새 정보
       없이 며칠만 지나도 값이 바뀌어 **재현이 안 된다**(모듈 규칙 3).

    ② **건수**(직전 `lookback` 개월 중위의 `MIN_MONTH_COMPLETENESS` 이상) — 달력만
       보면 못 잡는 실패가 있다. 수집이 밀리거나 한 달치가 통째로 비는 일이 실제로
       있었고(페이지네이션 누락), 그때 달력은 "완결"이라고 거짓말한다.

    ⚠️ AND 이므로 ②는 **거짓 미완결**을 낼 수 있다(운영 실측: 서울 시도 2025-07·08·
       11·12 가 1년 뒤에도 미완결). 계절적 거래량 감소를 수집 누락과 구분하지 못하기
       때문이다. 보수적인 쪽(기준월을 뒤로 미루는 쪽)의 오류이고, 기준월은 어차피
       '가장 최근'을 고르므로 그 달들이 기준월이 될 일은 없다. 고치려면 건수 검사를
       계절보정해야 하는데, 그건 이 함수가 하려는 일(수집 누락 탐지)보다 크다.
    """
    yms = sorted(counts)
    open_from = open_ym(as_of)
    flags: dict[str, bool] = {}
    for i, ym in enumerate(yms):
        if ym >= open_from:
            flags[ym] = False                 # 아직 신고가 들어오는 중인 달
            continue
        prev = [counts[y] for y in yms[max(0, i - lookback):i]]
        if not prev:
            # 비교 대상이 없는 첫 달은 건수로 판단하지 않는다(달력은 이미 통과했다).
            flags[ym] = True
            continue
        base = statistics.median(prev)
        flags[ym] = base <= 0 or counts[ym] >= base * MIN_MONTH_COMPLETENESS
    return flags


def build_index(
    rows: Iterable[tuple[str, float, int]],
    *,
    region_code: str,
    scope: str,
    as_of: dt.date,
    method: str = INDEX_METHOD,
) -> MarketIndex:
    """(ym, idx_value, sample_size) 행들로 `MarketIndex` 를 만든다.

    완결 여부는 **달력 하한 + 표본 수 흐름**으로 판정한다(`_complete_flags`). 표본이
    `MIN_INDEX_MONTH_SAMPLE` 미만인 달은 **버린다** — 지어내지 않는다.

    `as_of` 는 **필수**다. 기본값(오늘)을 주면 이 함수가 시계를 읽게 되고, 그 순간
    "같은 입력에 같은 출력"이 깨져 테스트가 날짜에 따라 통과·실패한다. 배치는 실행
    시각을 한 번 정해서 내려보낸다(`scripts/build_market_index.py`).
    """
    kept: dict[str, tuple[float, int]] = {
        ym: (val, n) for ym, val, n in rows if n >= MIN_INDEX_MONTH_SAMPLE and val > 0
    }
    flags = _complete_flags({ym: n for ym, (_v, n) in kept.items()}, as_of=as_of)
    points = {
        ym: IndexPoint(ym=ym, value=val, sample_size=n, is_complete=flags.get(ym, False))
        for ym, (val, n) in kept.items()
    }
    return MarketIndex(region_code=region_code, scope=scope, points=points)


def index_coverage(trades: Sequence[TradeRow], index: MarketIndex | None) -> float:
    """이 지수가 이 거래들의 시점을 얼마나 덮는가(0~1). 기준월이 없으면 0."""
    if index is None or not trades or index.reference_ym is None:
        return 0.0
    hit = sum(1 for t in trades
              if index.ratio_to_reference(ym_of(t.contract_date)) is not None)
    return hit / len(trades)


def select_index(
    trades: Sequence[TradeRow],
    *,
    sigungu: MarketIndex | None = None,
    sido: MarketIndex | None = None,
) -> MarketIndex | None:
    """이 거래들을 덮는 지수 중 **기준월이 가장 최근인 것**. 같으면 시군구(더 정밀).

    ① 먼저 커버리지 — 구멍 뚫린 정밀한 지수는 `MIN_ADJUST_COVERAGE` 에 걸려 **보정을
       통째로 못 하게** 만든다. 그럴 바엔 조금 거친 시도 지수로라도 시점을 맞추는 편이
       낫다(아무 보정 없는 밴드가 가장 나쁘다).

    ② 통과한 것들 중에서는 **정밀도(시군구)보다 시점 일치(최신 기준월)를 앞세운다.**
       왜 '시군구 우선'이 아닌가 (2026-07-28 운영 DB 실측) — 기준월은 표본 150건
       (`MIN_REFERENCE_MONTH_SAMPLE`)을 채운 완결 월 중 최신인데, 거래가 적은 구는 그
       조건을 최근 달에 못 채운다. 시군구 79곳 중 **28곳이 시도(전부 같은 최신월)보다
       뒤처졌고**, 그중 5곳은 8개월 이상 낡았다(11170 용산 2025-03 · 11140 중구
       2025-06 · 41290 과천 2024-06 · 41591 광주 2024-10 · 28155 인천동구 2024-08).
       낡은 기준월을 그대로 쓰면 두 가지가 깨진다:
         · **역효과** — 상승장에서 낡은 기준월로 환산하면 값이 **내려간다**(실측:
           중구 남산타운 15.00억 → 13.16억, −12.3%). "밴드가 낮아 못 사는 단지가
           예산 안으로 통과한다"를 고치려는 보정이 그 지역에서는 문제를 더 키운다.
         · **비교 불능** — 한 목록 안에서 후보마다 환산 시점이 달라진다. 잣대 하나
           (예산)로 재는 목록에서 잣대가 후보마다 다른 것은 정밀도 손실이 아니라
           판정 무효다.

    ⚠️ 둘 다 커버리지가 모자라면, 그래도 **더 나은 쪽**을 돌려준다 —
       `adjust_trades` 가 사유를 남기며 거부하게 하기 위해서다. 둘 다 0이면 None.
    """
    fine = index_coverage(trades, sigungu)
    coarse = index_coverage(trades, sido)
    # `index_coverage` 는 기준월이 없으면 0 을 주므로, 문턱을 넘긴 지수에는 기준월이 있다.
    usable = [idx for idx, cov in ((sigungu, fine), (sido, coarse))
              if idx is not None and cov >= MIN_ADJUST_COVERAGE]
    if usable:
        return max(usable, key=lambda i: (i.reference_ym or "", i.scope == SCOPE_SIGUNGU))
    # 어느 쪽도 기준을 못 넘겼다. 그래도 더 나은 쪽을 넘겨 `adjust_trades` 가
    # **사유를 남기며** 거부하게 한다(조용히 None 이 되면 왜 안 됐는지 사라진다).
    if fine == 0.0 and coarse == 0.0:
        return None
    return sigungu if fine >= coarse else sido


def adjust_trades(
    trades: Sequence[TradeRow],
    index: MarketIndex | None,
    *,
    min_sample: int = MIN_SAMPLE,
) -> tuple[list[TradeRow], TimeAdjustment]:
    """거래 가격을 기준월 수준으로 환산한다.

    **각 거래를 개별 보정한 뒤 중위를 낸다** — 중위에 계수 하나를 곱하는 방식과 달리,
    창 안의 거래 시점 분포가 한쪽으로 쏠려 있어도(최근 거래가 많은 단지 등) 올바르게
    처리된다.

    보정하지 않는 경우(그리고 그 사실을 `TimeAdjustment.reason` 에 남기는 경우):
      · 지수 자체가 없다
      · 완결된 기준월이 없다
      · 창 안 거래의 지수 확보율이 `MIN_ADJUST_COVERAGE` 미만이다 (부분 보정 금지)
      · 보정 후 표본이 `min_sample` 미만이다
      · 보정 배율이 비정상 범위다

    반환은 항상 `(쓸 거래 목록, 보정결과)` 다. 보정하지 않았으면 **원본 그대로** 돌려준다.
    """
    original = list(trades)
    if index is None or not index.points:
        return original, TimeAdjustment(applied=False, reason=REASON_NO_INDEX)

    ref_ym = index.reference_ym
    if ref_ym is None:
        return original, TimeAdjustment(
            applied=False, scope=index.scope, region_code=index.region_code,
            reason=REASON_NO_REFERENCE)

    if not original:
        return original, TimeAdjustment(
            applied=False, reference_ym=ref_ym, scope=index.scope,
            region_code=index.region_code, reason=REASON_TOO_FEW)

    adjusted: list[TradeRow] = []
    ratios: list[float] = []
    for t in original:
        ratio = index.ratio_to_reference(ym_of(t.contract_date))
        if ratio is None:
            continue
        ratios.append(ratio)
        adjusted.append(replace(t, price_krw=int(round(t.price_krw * ratio))))

    coverage = len(adjusted) / len(original)
    coverage_pct = round(coverage * 100, 1)

    if coverage < MIN_ADJUST_COVERAGE:
        return original, TimeAdjustment(
            applied=False, reference_ym=ref_ym, scope=index.scope,
            region_code=index.region_code, coverage_pct=coverage_pct,
            reason=REASON_LOW_COVERAGE)

    if len(adjusted) < min_sample:
        return original, TimeAdjustment(
            applied=False, reference_ym=ref_ym, scope=index.scope,
            region_code=index.region_code, coverage_pct=coverage_pct,
            reason=REASON_TOO_FEW)

    if not all(MIN_ADJUST_RATIO <= r <= MAX_ADJUST_RATIO for r in ratios):
        return original, TimeAdjustment(
            applied=False, reference_ym=ref_ym, scope=index.scope,
            region_code=index.region_code, coverage_pct=coverage_pct,
            reason=REASON_OUT_OF_RANGE)

    # 보정 대상과 **같은 거래**의 보정 전/후를 비교해야 이동폭이 정확하다
    # (지수 없는 거래를 분모에 섞으면 보정하지 않은 차이까지 보정 효과로 잡힌다).
    before = statistics.median(
        t.price_krw for t in original
        if index.ratio_to_reference(ym_of(t.contract_date)) is not None)
    after = statistics.median(t.price_krw for t in adjusted)
    shift = round((after - before) / before * 100, 2) if before > 0 else None

    return adjusted, TimeAdjustment(
        applied=True, reference_ym=ref_ym, scope=index.scope,
        region_code=index.region_code, shift_pct=shift,
        coverage_pct=coverage_pct, sample_size=len(adjusted))


def adjustment_evidence(adj: TimeAdjustment) -> list[dict[str, Any]]:
    """근거 항목. 보정하지 않았으면 **빈 목록** — 없는 근거를 만들지 않는다."""
    if not adj.applied:
        return []
    return [{
        "claim": (f"{adj.reference_ym} 시점 환산 "
                  f"({SCOPE_LABEL.get(adj.scope or '', adj.scope or '')} 시장지수 "
                  f"{adj.shift_pct:+.1f}%)"),
        "source": "자체 시장지수(국토교통부 실거래가 기반)",
        "as_of": f"{adj.reference_ym}-01",
        "data_rows": adj.sample_size,
        "coverage_pct": adj.coverage_pct,
        "basis": adj.basis,
    }]
