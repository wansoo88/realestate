"""백테스트 데이터 접근 경계 — **도메인은 SQL 을 모른다.**

설계 정본: `docs/02-design/backtest.md` §5

리포지토리에 금지된 것 (이게 이 파일의 존재 이유다)
---------------------------------------------------
1. **as-of 필터를 걸지 마라.** `contract_date <= :cutoff` 를 SQL 에 넣고 싶어지는데,
   그러면 자르는 곳이 두 곳이 되고 **한쪽만 고쳐지는 날**이 온다. 자르는 곳은
   `asof.as_of_trades` 하나다.
2. **`is_cancelled` 로 거르지 마라.** 해제 정책은 도메인이 정한다(상·하한 두 번 돌린다).
   여기서 미리 거르면 `INCLUDE_ALL` 정책이 조용히 무력화된다.
3. **`apt_dong` 을 지우지 마라.** 지우는 조건(등기 여부)은 as-of 시점에 따라 달라진다.

리포지토리가 해야 하는 것
-------------------------
* 계약일 범위로만 좁혀서(`FoldSpec.required_contract_range`) 필요한 만큼만 읽는다.
* 운영 DB 는 `mem_limit 192MB` 다 — 시군구 단위로 나눠 읽고 스트리밍으로 넘긴다
  (`scripts/build_market_index.py` 가 같은 이유로 같은 규칙을 따른다).
* **읽기 전용.** 이 경로에서 쓰기는 없다.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator, Sequence
from typing import Protocol, runtime_checkable

from app.domain.backtest.models import BacktestTrade


@runtime_checkable
class BacktestTradeRepository(Protocol):
    """백테스트가 필요로 하는 전부. 구현은 `scripts/run_backtest.py` 에 있다."""

    def trades_for_backtest(
        self,
        *,
        start: dt.date,
        end: dt.date,
        region_codes: Sequence[str] | None = None,
    ) -> Iterator[BacktestTrade]:
        """계약일 `[start, end]` 의 거래를 **거르지 않고** 흘려보낸다.

        `region_codes` 는 시군구 접두(5자리) 목록. None 이면 전부.
        해제 거래도, 등기 전 거래도, 동이 있는 거래도 **그대로** 준다 —
        무엇을 버릴지는 도메인이 as-of 시점을 보고 정한다.
        """
        ...

    def household_counts(self, complex_ids: Iterable[int]) -> dict[int, int | None]:
        """단지별 세대수. 없으면 None(0 이 아니다 — 0 이면 회전율이 무한이 된다).

        ⚠️ 이 값은 **현재 스냅샷**이다. 그래도 상수로 쓰는 근거는 backtest.md §2-E:
           준공 시 확정되고 변하지 않는다. 6축 중 상수 가정이 정당한 유일한 축이다.
        """
        ...


class InMemoryBacktestRepository:
    """테스트·소규모 실험용. 리스트를 그대로 들고 있는다.

    운영 DB 구현과 **같은 Protocol** 을 만족하는지 테스트가 `isinstance` 로 확인한다 —
    Protocol 은 선언만으로는 아무것도 강제하지 않기 때문이다.
    """

    def __init__(self, trades: Sequence[BacktestTrade],
                 households: dict[int, int | None] | None = None) -> None:
        self._trades = list(trades)
        self._households = dict(households or {})

    def trades_for_backtest(
        self,
        *,
        start: dt.date,
        end: dt.date,
        region_codes: Sequence[str] | None = None,
    ) -> Iterator[BacktestTrade]:
        prefixes = tuple(region_codes) if region_codes else None
        for trade in self._trades:
            if not (start <= trade.contract_date <= end):
                continue
            if prefixes and not (trade.region_code or "").startswith(prefixes):
                continue
            yield trade

    def household_counts(self, complex_ids: Iterable[int]) -> dict[int, int | None]:
        return {cid: self._households.get(cid) for cid in complex_ids}
