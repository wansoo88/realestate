"""★ as-of 뷰 — **미래 정보 차단(look-ahead bias)이 전부 여기 한 곳에 있다.**

설계 정본: `docs/02-design/backtest.md` §2

이 모듈이 하는 일은 한 문장이다:

    "T 시점에 **보였다고 말할 수 있는** 거래만 남기고, 그때 몰랐던 칸은 지운다."

왜 한 곳에 모으는가
-------------------
누출 차단을 사용처마다 흩어 두면, 새 점수 축을 만드는 사람이 **모르고 뚫는다**.
그래서 자르는 곳은 여기 하나이고, 하위 계층(`outcome`·`scorers`)은 원본 거래를
아예 받지 못하게 타입으로 막는다(`AsOfCell` 만 본다).

무엇을 막고 무엇을 못 막는가 (요약 — 근거는 문서 §2)
----------------------------------------------------
  막는다   · 계약일 경계 (신고기한 30일)
           · `apt_dong` — 등기 후에야 채워진다 → T 시점 미등기분은 **동을 몰랐다**
           · `registered_at`·`cancelled_on` 의 미래값 (하위가 실수로 쓰지 못하게 지운다)
  못 막는다 · **지각 신고** — 기한을 넘겨 낸 신고. 신고일을 원천이 주지 않는다. 크기 [미측정]
           · **해제 시점** — `trade.cancelled_on` 컬럼이 없다. 상·하한 두 정책으로 범위만 말한다
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import replace
from enum import Enum

from app.domain.backtest.models import BacktestTrade

# ⚠️ 신고기한 상수는 **여기서 만들지 않는다.** 시점 보정과 같은 사실을 두 곳에 적으면
#    한쪽만 바뀌는 날 두 모듈이 서로 다른 과거를 본다.
from app.domain.valuation.timeadjust import REPORT_LAG_DAYS

__all__ = [
    "REPORT_LAG_DAYS",
    "CancellationPolicy",
    "LookAheadError",
    "visible_cutoff",
    "as_of_trades",
    "assert_as_of",
]


class LookAheadError(RuntimeError):
    """미래 정보를 쓰려 했다. **조용히 넘어가지 않는다** — 결과 전체가 거짓말이 된다."""


class CancellationPolicy(str, Enum):
    """해제 거래를 T 시점에 어떻게 볼 것인가.

    정확한 규칙은 `is_cancelled = false OR cancelled_on > T` 인데,
    **`trade` 테이블에 `cancelled_on` 컬럼이 없다**(수집기는 파싱하는데 적재에서 버린다 —
    `ingest/loader.py::_upsert_trade` 의 INSERT 컬럼 목록에 이름이 없다).
    그래서 정확히는 못 하고 **상·하한 두 번 돌려 범위로** 말한다(§2-D).
    """

    #: `NOT is_cancelled` — **운영 코드와 동일**. 그래서 기본값이다(우리가 채점하려는
    #: 대상은 이상적인 추천기가 아니라 **우리가 실제로 돌리는 코드**다).
    #: ⚠️ **누출이다** — 사후에 확정된 해제여부로 T 시점 표본을 청소한다.
    EXCLUDE_FINAL = "exclude_final"

    #: 해제 여부를 보지 않는다. T 이전에 이미 해제된 건까지 넣으므로 **과다 포함**.
    INCLUDE_ALL = "include_all"

    #: 정확한 규칙. `cancelled_on` 이 없으면 **예외로 멈춘다**(조용히 근사하지 않는다).
    #: 마이그레이션 017 이후에 쓸 자리. 지금 실데이터로는 쓸 수 없다.
    EXCLUDE_KNOWN_AT = "exclude_known_at"


#: 해제일 없이 `EXCLUDE_KNOWN_AT` 을 요구했을 때의 문구(테스트가 이 문자열을 본다).
NO_CANCEL_DATE_MSG = (
    "해제일(cancelled_on)이 없어 T 시점 해제 여부를 알 수 없습니다 — "
    "trade 테이블에 컬럼이 없습니다(마이그레이션 017 필요). "
    "EXCLUDE_FINAL / INCLUDE_ALL 을 둘 다 돌려 범위로 보고하세요(backtest.md §2-D).")


def visible_cutoff(as_of: dt.date, *, report_lag_days: int = REPORT_LAG_DAYS) -> dt.date:
    """T 시점에 **신고가 끝났다고 말할 수 있는** 마지막 계약일.

        cutoff(T) = T − 30일   (부동산거래신고법 §3① — 계약 체결일로부터 30일 이내 신고)

    ⚠️ 왜 `contract_date <= T` 가 아닌가 — T 당일 계약 건은 그날 API 에 없다.
       `<= T` 로 자르면 **T 시점 어느 화면에도 없던 가격**으로 점수를 매기게 된다.

    ⚠️ 이 경계가 완벽하지 않은 방향은 **둘**이고 위험도가 다르다(§2-A):
         · 남는 누출  — 지각 신고(기한 넘겨 낸 것)는 그대로 들어온다. **못 닫는다**
         · 버리는 정보 — T−20일 계약이 T−19일에 신고돼 보였던 건을 우리는 버린다
       정보 손실은 결과를 보수적으로 만들 뿐이고 누출은 부풀린다. **손실 쪽을 고른다.**
    """
    return as_of - dt.timedelta(days=report_lag_days)


def as_of_trades(
    trades: Iterable[BacktestTrade],
    *,
    as_of: dt.date,
    policy: CancellationPolicy = CancellationPolicy.EXCLUDE_FINAL,
    report_lag_days: int = REPORT_LAG_DAYS,
) -> list[BacktestTrade]:
    """`T` 시점 뷰를 만든다.

    **해제 여부(`is_cancelled`)를 제외하면 출력은 T 이후 데이터에 의존하지 않는다.**
    그 성질이 이 패키지 전체의 근거이므로 테스트가 직접 단언한다
    (`test_backtest.py` — T 이후 거래를 아무리 넣어도 출력이 바뀌지 않는다).

    ⚠️ **해제 축만은 예외이고, 무조건으로 적으면 다음 사람이 그대로 믿는다.**
       기본값 `EXCLUDE_FINAL` 은 *사후에 확정된* `is_cancelled` 로 T 시점 표본을
       청소한다(45줄 위 `CancellationPolicy` 주석과 같은 사실이다). 그 축은
       상·하한 두 정책으로 **범위로만** 말한다(backtest.md §2-D).

    하는 일 셋:
      1. `contract_date > cutoff(T)` 인 거래를 버린다.
      2. 해제 정책을 적용한다(`CancellationPolicy`).
      3. **T 시점에 몰랐던 칸을 지운다** — `registered_at > T` 면 등기 전이므로
         `apt_dong` 은 아직 비어 있었다(실측: 등기분 86.3% 보유 vs 등기 전 2.0%,
         `valuation/models.DONG_PERIOD_MONTHS` 주석). 미래 날짜 칸도 함께 지운다.

    반환은 **정렬된** 목록이다 — 입력 순서와 무관한 '집합의 함수'가 되게 해서,
    누출 테스트가 "뒤에 행을 덧붙였다"는 이유만으로 통과/실패하지 않게 한다.
    """
    cutoff = visible_cutoff(as_of, report_lag_days=report_lag_days)
    kept: list[BacktestTrade] = []

    for trade in trades:
        if trade.contract_date > cutoff:
            continue                                  # ① 아직 신고되지 않았을 수 있다

        # ② 해제 정책
        if trade.is_cancelled:
            if policy is CancellationPolicy.EXCLUDE_FINAL:
                continue
            if policy is CancellationPolicy.EXCLUDE_KNOWN_AT:
                if trade.cancelled_on is None:
                    raise LookAheadError(NO_CANCEL_DATE_MSG)
                if trade.cancelled_on <= as_of:
                    continue                          # 그때 이미 해제돼 있었다
            # INCLUDE_ALL: 아무것도 거르지 않는다

        # ③ T 시점에 몰랐던 칸 지우기
        registered = trade.registered_at
        if registered is not None and registered > as_of:
            registered = None
        cancelled_on = trade.cancelled_on
        if cancelled_on is not None and cancelled_on > as_of:
            cancelled_on = None
        apt_dong = trade.apt_dong if registered is not None else None

        if (registered is not trade.registered_at
                or cancelled_on is not trade.cancelled_on
                or apt_dong is not trade.apt_dong):
            trade = replace(trade, registered_at=registered,
                            cancelled_on=cancelled_on, apt_dong=apt_dong)
        kept.append(trade)

    kept.sort(key=BacktestTrade.sort_key)
    return kept


def assert_as_of(
    trades: Sequence[BacktestTrade],
    *,
    as_of: dt.date,
    report_lag_days: int = REPORT_LAG_DAYS,
) -> None:
    """계산 직전 마지막 그물. 뷰를 거치지 않은 거래가 섞였으면 **멈춘다**.

    `as_of_trades` 가 이미 걸렀는데 왜 또 보는가 — 호출부가 뷰를 만들고 나서
    "편의상" 원본을 한 번 더 합치는 실수가 이런 코드에서 가장 흔하다.
    그 실수는 결과를 조금 틀리게 만드는 게 아니라 **통째로 무효로** 만든다.
    """
    cutoff = visible_cutoff(as_of, report_lag_days=report_lag_days)
    late = [t for t in trades if t.contract_date > cutoff]
    if late:
        raise LookAheadError(
            f"as-of {as_of} 뷰에 cutoff({cutoff}) 이후 계약 {len(late)}건이 섞였습니다 "
            f"(가장 늦은 계약일 {max(t.contract_date for t in late)}). "
            "asof.as_of_trades 를 거치지 않은 경로가 있습니다.")
    dongs = [t for t in trades
             if t.apt_dong is not None
             and (t.registered_at is None or t.registered_at > as_of)]
    if dongs:
        raise LookAheadError(
            f"as-of {as_of} 뷰에 등기 전 거래의 apt_dong 이 {len(dongs)}건 남아 있습니다 — "
            "동 정보는 등기 완료 후에야 채워지므로 그 시점엔 몰랐습니다(backtest.md §2-B).")
