"""수집 속도 제한.

설계 근거: docs/02-design/security.md §5 (G4 게이트)

왜 필요한가
-----------
공공 오픈API도 일일 호출 한도가 있고, 포털은 이용약관에 접근 빈도 조건이 있다.
빠르게 긁으면 차단되고, 차단되면 **서비스 자체가 죽는다.**
속도 제한은 예의가 아니라 **가용성 요구사항**이다.

시계를 주입받는 이유는 테스트에서 실제로 기다리지 않기 위해서다.
"""
from __future__ import annotations

import random
import time
from collections.abc import Callable


class RateLimiter:
    """요청 사이 최소 간격을 보장한다(토큰버킷보다 단순하고 예측 가능).

    `jitter` 를 주면 요청 간격이 기계적으로 일정하지 않게 된다.
    """

    def __init__(
        self,
        min_interval_sec: float,
        *,
        jitter_sec: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        if min_interval_sec < 0:
            raise ValueError("min_interval_sec 는 0 이상이어야 합니다")
        self.min_interval = min_interval_sec
        self.jitter = jitter_sec
        self._clock = clock
        self._sleep = sleeper
        self._rng = rng or random.Random()
        self._last: float | None = None

    def wait(self) -> float:
        """필요한 만큼 기다린다. 실제로 기다린 시간을 반환."""
        now = self._clock()
        slept = 0.0
        if self._last is not None:
            target = self._last + self.min_interval
            if self.jitter:
                target += self._rng.uniform(0, self.jitter)
            remaining = target - now
            if remaining > 0:
                self._sleep(remaining)
                slept = remaining
                now = now + remaining
        self._last = now
        return slept


def backoff_delays(attempts: int, *, base: float = 1.0, cap: float = 60.0) -> list[float]:
    """지수 백오프 지연 목록. 상한을 둬 무한정 늘어나지 않게 한다."""
    if attempts < 0:
        raise ValueError("attempts 는 0 이상")
    return [min(cap, base * (2 ** i)) for i in range(attempts)]
