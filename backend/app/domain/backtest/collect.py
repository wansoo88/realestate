"""거래를 **한 번만 흘려보내며** 폴드별 표본을 모은다 — 원본 행을 쌓지 않는다.

설계 정본: `docs/02-design/backtest.md` §5-1 · §7-13

왜 이 파일이 생겼는가 (CR49-3)
------------------------------
리포지토리는 `Iterator` 로 스트리밍을 약속한다(`repository.py` 머리주석:
*"운영 DB 는 mem_limit 192MB 다 — 시군구 단위로 나눠 읽고 스트리밍으로 넘긴다"*).
그런데 유일한 소비자가 그 이터레이터를 `list()` 로 접으면 약속이 통째로 무효가 된다.

**실측(2026-08-05, 2021~2023 백필 완료 후)**

| 항목 | 값 |
|---|---|
| `trade` 행 수 | 1,076,262 |
| 문서 §8 첫 실행 예시(`--as-of 2025-01-31`)의 필요 범위 | 613,228행 |
| `BacktestTrade` 1행 | 383 B (`tracemalloc`) |
| 그 목록의 힙 | **≈ 235 MB** |
| 서버 가용 메모리 | **261 MB** (총 957MB · 스왑 2G 중 698MB 사용 중) |

즉 **첫 폴드 하나가 가용 메모리의 90%** 였다. API 컨테이너(`mem_limit 192m`)와 postgres 가
같은 상자에 사는 서버다 — 하드 OOM 이 아니어도 스래싱이면 이미 사고다.

그래서 **소비 방식 자체를 바꾼다**: 거래를 청크로 끊어 읽고, 청크마다 as-of 뷰를 만들어
**셀별 ₩/㎡ 값(8바이트 double)만 남기고 행을 버린다.** 행은 청크를 넘기는 순간 참조가 끊긴다.

고른 길과 버린 길
-----------------
| 안 | 판정 | 이유 |
|---|---|---|
| ① 폴드마다 그 폴드 범위만 다시 조회 | **버렸다** | 창이 좁아져도 폴드 하나가 이미 235MB 다(위 실측이 바로 폴드 1개짜리다). 게다가 폴드 수만큼 DB 를 다시 훑어 `mem_limit 192MB` 짜리 db 컨테이너를 N 번 두드린다 |
| ② **한 번 순회하며 전 폴드의 셀을 동시 집계** | **채택** | DB 1회 통과. 폴드가 늘어도 **행** 보유량은 그대로다(느는 것은 float 통뿐) |
| ③ 행 자체를 줄이기(SQL 에서 미리 집계) | **버렸다** | 창 경계·해제 정책·`apt_dong` 마스킹이 SQL 로 내려가면 **자르는 곳이 두 곳**이 된다. `backtest.md §5-2` 가 정면으로 금지한 것이고, 한쪽만 고쳐지는 날 백테스트 전체가 조용히 거짓이 된다 |
| ④ 예상 행수를 미리 세어 임계 초과면 중단 | **부분 채택** | 이것만으로는 "안 돌린다"일 뿐 **못 돌린다**는 그대로다. 여기서는 ②를 하고, 그 위에 `max_samples` 상한을 얹어 폭주만 막는다 |

⚠️ **함정 하나** — 단순히 `list()` 를 벗기는 것으로는 안 됐다. `trades` 는 폴드(spec)마다
다시 순회되고 세대수 조회도 같은 집합을 쓰기 때문에, 제너레이터를 그대로 넘기면
**두 번째 순회에서 조용히 0행**이 된다(예외도 안 난다 — 유니버스가 빈 채로 리포트가 나온다).
그래서 소비자를 "여러 번 훑는 코드"에서 "한 번 훑고 접는 코드"로 바꾸는 것이 수정의 본체다.

**그리고 그 함정을 주석이 아니라 코드로 막는다**(CR50-3). "운영 경로엔 없다"는 대책이 아니다 —
다음 사람이 그 경로를 만든다. 지금은 네 자리가 예외로 죽는다:

| 실수 | 무슨 일이 났었나 | 지금 |
|---|---|---|
| `build_cells(gen)` → `build_outcomes(gen)` | 두 번째가 **조용히 0행** · `measured 0/N` 인데 예외 없음 | `TypeError` — 두 함수는 **다시 훑을 수 있는** 것만 받는다(`iter(x) is x` 면 거부) |
| `feed` 를 두 번 | `rows_seen`·`sample_size` 가 **조용히 두 배**(환금성 축의 분자다) | `StreamAlreadyConsumed` |
| 같은 제너레이터를 수집기 둘에 | 두 번째가 0행 | `StreamAlreadyConsumed` (약한 참조가 걸리는 원천에 한해 — 아래 `_CLAIMED` 참조) |
| 같은 `FoldSpec` 을 두 번 | 뒤 창이 **채워지되 안 읽힌다**(표본만 두 배로 쌓여 `max_samples` 를 먹는다) | `ValueError` |

이 파일이 지키는 두 상한 (둘 다 테스트가 단언한다)
--------------------------------------------------
1. **순간 보유 행 수 ≤ 2 × `chunk_rows`**(기본 5,000 → **10,000행**).
   살아 있는 것은 청크 하나와 그 as-of 뷰 하나다. 뷰는 원칙적으로 같은 객체를 가리키지만,
   **T 시점에 몰랐던 칸을 지우는 행은 `dataclasses.replace()` 사본이 된다**
   (`asof.py` ③). 운영 데이터는 `apt_dong` 보유율이 **77~93%**(erd §0)라 사실상
   **거의 모든 행이 사본**이다 → 청크 + 사본 = **행 수로 2배**. 그게 운영의 진짜 모양이다.

   바이트로는 2배가 아니다(사본이 문자열·날짜 객체를 원본과 공유한다). 실측(2026-08-05 ·
   `tracemalloc` · 5,000행 청크 하나의 뷰를 만들며 잰 증가분):

   | 청크의 모양 | 뷰가 더 먹은 양 | |
   |---|---:|---|
   | `apt_dong=None` (마스킹 없음) | **44 B/행** | 목록 슬롯만 |
   | `apt_dong='101'` + 미등기 (**운영 모양**) | **181 B/행** | 사본이 생긴다 |

   → `chunk_rows=5,000` 기준 청크 ≈1.9MB(383B/행) + 뷰 ≈**0.9MB** = **약 2.8MB**.
   ⚠️ 옛 판의 주석은 "사본은 마스킹된 행만"이라 적어 1배처럼 읽혔고, 그걸 재는 테스트는
   픽스처가 `apt_dong` 을 안 심어 **마스킹 경로를 한 번도 안 지났다**(CR50-1).
   → 지금은 `peak_live_rows` 가 **청크 + 뷰**를 같이 세고, 픽스처가 마스킹을 지난다.
2. **누적 표본 수 ≤ `max_samples`**(기본 2,000,000). 넘으면 `SampleLimitExceeded` 로 **멈춘다** —
   조용히 스왑으로 흘러 서버를 스래싱시키지 않는다.

⛔ **이 두 상한은 파이썬 객체의 상한이지 프로세스 총량이 아니다.** DB 드라이버가 그 앞에서
   따로 버퍼를 잡는다 — 실행기가 `stream_results` 로 서버측 커서를 쓰는 이유이고,
   그래도 남는 몫은 `backtest.md §7-13` 에 숫자로 적었다(CR50-2).

`max_samples` 기본값 근거: 표본 하나는 `array('d')` 안에서 8B, 버킷(셀×시점) 하나의 부대비용은
dict 항목+array 객체 ≈ 150B 다. 실측 분포에서 버킷당 표본이 대략 한 자릿수이므로
200만 표본 ≈ 값 16MB + 버킷 40MB 안팎 = **약 55MB**, 가용 261MB 의 1/5 이다.
첫 실행 예시(613,228행 · 폴드 1개)는 창 셋이 서로 겹치지 않아 행당 표본이 1개 이하 →
**약 61만 표본**으로 상한의 1/3 이다.
"""
from __future__ import annotations

import datetime as dt
import statistics
import weakref
from array import array
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from itertools import islice
from typing import NamedTuple

from app.domain.backtest.asof import (
    REPORT_LAG_DAYS,
    CancellationPolicy,
    as_of_trades,
    assert_as_of,
)
from app.domain.backtest.models import (
    MIN_TRADES_PER_ENDPOINT,
    AsOfCell,
    BacktestTrade,
    CellOutcome,
    CellRef,
    FoldSpec,
    sigungu_of,
)
from app.domain.backtest.outcome import (
    MIN_PEER_CELLS,
    make_outcome,
    price_from_values,
    price_window,
)

__all__ = [
    "DEFAULT_CHUNK_ROWS",
    "DEFAULT_MAX_SAMPLES",
    "KINDS_ALL",
    "KIND_END",
    "KIND_PRIOR",
    "KIND_START",
    "FoldCollector",
    "SampleLimitExceeded",
    "StreamAlreadyConsumed",
    "attach_peer_medians",
    "assert_rereadable",
]

#: 한 번에 손에 쥐는 거래 행 수. **이 숫자가 실행기의 (파이썬 쪽) 메모리 상한이다.**
#: 5,000행 × 383B ≈ 1.9MB + as-of 뷰 5,000행 × 181B ≈ 0.9MB = **약 2.8MB**
#: (행 수로는 2배 · 실측은 머리주석 상한 ①) — 서버 가용 261MB 에 견줘 무시할 수 있다.
#: 더 키워도 속도 이득은 거의 없다(병목은 DB 왕복이지 파이썬 루프가 아니다).
DEFAULT_CHUNK_ROWS = 5_000

#: 누적 표본(₩/㎡ 값) 상한. 넘으면 멈춘다 — 위 머리주석의 계산 참조.
DEFAULT_MAX_SAMPLES = 2_000_000

#: 시점 종류. 폴드 하나가 필요로 하는 가격 시점은 셋뿐이다.
KIND_START = "start"     #: T 시점 창 — 점수의 입력
KIND_PRIOR = "prior"     #: T−W 창 — 가격추세 축의 분모
KIND_END = "end"         #: T+H 창 — 결과 측정(점수에 닿지 않는다)
KINDS_ALL = (KIND_START, KIND_PRIOR, KIND_END)

#: `price_from_values` 에 넘길 빈 통. 매번 새로 만들지 않는다.
_EMPTY: tuple[float, ...] = ()


class SampleLimitExceeded(RuntimeError):
    """누적 표본이 상한을 넘었다. **더 담지 않고 멈춘다.**

    조용히 계속 담으면 서버(가용 261MB)가 스왑으로 흘러 API 컨테이너까지 굶는다.
    멈추는 쪽이 옳다 — 백테스트는 오프라인 도구이고, 다시 돌리면 된다.
    """


class StreamAlreadyConsumed(RuntimeError):
    """거래 스트림을 두 번 소비하려 했다. **조용히 0행을 돌려주지 않는다**(CR50-3).

    이 예외가 없던 판에서는 두 번째 소비가 빈 유니버스를 만들고도 리포트를 냈다 —
    `measured 0/5` 에 경고 몇 줄이 붙을 뿐이라 **읽는 사람이 알아채지 못한다.**
    """


#: 이미 어느 수집기가 물어간 이터레이터. **약한 참조**라 스스로 비워진다.
#:
#: ⚠️ 한계를 적어 둔다: 약한 참조를 못 거는 이터레이터(`list_iterator`·`map`·
#:    `itertools.chain` 등)는 여기에 못 담는다 — CPython 이 그 형에 `__weakref__` 를
#:    두지 않는다. 운영 경로의 원천은 **제너레이터**(`repo.trades_for_backtest`)라
#:    걸린다. 나머지 구멍은 `assert_rereadable` 이 앞에서 막는다(두 번 훑는 API 는
#:    애초에 이터레이터를 못 받는다).
_CLAIMED: weakref.WeakSet = weakref.WeakSet()

_FEED_TWICE_MSG = (
    "이 수집기는 이미 거래를 받았습니다 — `feed` 는 한 번만 부릅니다. "
    "두 번 부르면 rows_seen 과 창 표본이 조용히 두 배가 되고, 그 표본 수는 "
    "환금성 축의 분자입니다(backtest.md §3-E). 스트림이 여럿이면 "
    "`itertools.chain(a, b)` 로 **하나로 합쳐** 한 번에 넘기세요.")

_CLAIMED_MSG = (
    "이 거래 스트림은 이미 다른 수집기가 소비했습니다 — 다시 넘기면 "
    "**조용히 0행**이 됩니다(빈 유니버스로 리포트가 나옵니다). "
    "원천을 다시 만들어(예: `repo.trades_for_backtest(...)` 를 새로 호출) 넘기세요.")

_NOT_FED_MSG = (
    "거래를 한 번도 받지 않은 수집기입니다 — `feed()` 를 먼저 부르세요. "
    "빈 유니버스를 지어내지 않습니다(CR50-3).")


def assert_rereadable(trades: Iterable[BacktestTrade], *, where: str) -> None:
    """`trades` 가 **다시 훑을 수 있는 것**인지 본다. 이터레이터면 거부한다.

    왜 필요한가 — `build_cells(gen)` 다음에 `build_outcomes(gen)` 을 부르면 두 번째는
    **소진된 이터레이터**를 받아 조용히 0행을 낸다(예외 없음 · `measured 0/N`).
    실제로 재현된 함정이고(CR50-3), 두 함수의 타입이 `Iterable` 인 한 다음 사람이
    똑같이 밟는다. 그래서 타입이 아니라 **값**으로 막는다.

    판정은 표준 규약 하나로 끝난다: **이터레이터는 `iter(x) is x` 다.**
    리스트·튜플 같은 다회 순회 가능 컨테이너는 `iter()` 가 매번 새 커서를 준다.
    """
    if iter(trades) is trades:
        raise TypeError(
            f"{where} 는 **다시 훑을 수 있는** 거래 모음만 받습니다 — "
            f"{type(trades).__name__} 은 한 번 쓰면 비는 이터레이터라, 같은 것을 "
            "두 번째 함수에 넘기면 조용히 0행이 됩니다(CR50-3). "
            "`list(...)` 로 접거나(작은 표본일 때만), 스트리밍이 필요하면 "
            "`FoldCollector` 를 직접 쓰세요 — 그쪽은 한 번만 훑습니다.")


class _Window(NamedTuple):
    """(폴드, 시점) 하나가 모으는 창. `(start, end]` — 하한 제외 · 상한 포함."""

    spec_index: int
    kind: str
    start: dt.date
    end: dt.date


class FoldCollector:
    """거래 스트림 → 폴드별 셀 표본. **행을 쌓지 않는다.**

    쓰는 법(실행기)::

        collector = FoldCollector(specs, policy=policy)
        collector.feed(repo.trades_for_backtest(start=start, end=end))   # ← 한 번만
        households = repo.household_counts(collector.complex_ids)
        for spec in specs:
            cells = collector.cells(spec, households=households)
            outcomes = collector.outcomes(spec, cells)

    ⛔ `feed` 에 넘기는 것을 `list()` 로 감싸지 마라. 그 한 줄이 CR49-3 이었다.
    """

    def __init__(
        self,
        specs: Sequence[FoldSpec],
        *,
        policy: CancellationPolicy = CancellationPolicy.EXCLUDE_FINAL,
        report_lag_days: int = REPORT_LAG_DAYS,
        min_trades: int = MIN_TRADES_PER_ENDPOINT,
        min_peer_cells: int = MIN_PEER_CELLS,
        kinds: Sequence[str] = KINDS_ALL,
        chunk_rows: int = DEFAULT_CHUNK_ROWS,
        max_samples: int | None = DEFAULT_MAX_SAMPLES,
    ) -> None:
        if chunk_rows <= 0:
            raise ValueError(f"chunk_rows 는 양수여야 합니다: {chunk_rows}")
        unknown = [k for k in kinds if k not in KINDS_ALL]
        if unknown:
            raise ValueError(f"모르는 시점 종류: {unknown}")

        self._specs = tuple(specs)
        # ⚠️ 중복 폴드를 받으면 `_window_index` 의 `.index(spec)` 이 늘 **첫 번째**를
        #    돌려주므로 뒤쪽 창은 채워지되 아무도 안 읽는다 — 표본만 두 배로 쌓여
        #    `max_samples` 를 갉아먹고, 결과는 멀쩡해 보인다(CR50-3). 그래서 거부한다.
        seen: list[FoldSpec] = []
        for spec in self._specs:
            if spec in seen:
                raise ValueError(
                    f"같은 폴드가 두 번 들어왔습니다: {spec.name} — 뒤쪽 창은 채워지되 "
                    "읽히지 않고 표본만 두 배로 쌓입니다(CR50-3). 폴드를 유일하게 주세요.")
            seen.append(spec)
        self._policy = policy
        self._report_lag_days = report_lag_days
        self._min_trades = min_trades
        self._min_peer_cells = min_peer_cells
        self._kinds = tuple(kinds)
        self._chunk_rows = int(chunk_rows)
        self._max_samples = max_samples

        self._windows: list[_Window] = []
        #: 창 하나당 통 하나. `CellRef → array('d')` — **행이 아니라 값만** 담는다.
        self._values: list[dict[CellRef, array]] = []
        #: as-of 날짜 → 그 뷰에서 채울 창들. 뷰는 날짜당 **한 번만** 만든다.
        self._by_as_of: dict[dt.date, list[int]] = {}
        #: `assert_as_of` 로 마지막 그물을 칠 날짜(= 점수에 쓰이는 T 뷰만).
        self._assert_dates: set[dt.date] = set()

        for index, spec in enumerate(self._specs):
            plan = (
                # (종류, 어느 as-of 뷰에서, 창의 기준시점)
                (KIND_START, spec.as_of, spec.as_of),
                (KIND_PRIOR, spec.as_of, spec.prior_as_of),
                (KIND_END, spec.outcome_as_of, spec.outcome_as_of),
            )
            for kind, view_as_of, point in plan:
                if kind not in self._kinds:
                    continue
                start, end = price_window(point, window_months=spec.window_months,
                                          report_lag_days=report_lag_days)
                self._by_as_of.setdefault(view_as_of, []).append(len(self._windows))
                self._windows.append(_Window(index, kind, start, end))
                self._values.append({})
                if kind in (KIND_START, KIND_PRIOR):
                    self._assert_dates.add(view_as_of)

        #: 셀 → 법정동 코드. 값은 `complex` 행에서 오므로 단지마다 하나뿐이다
        #: (그래서 청크 경계가 이 값을 흔들지 못한다).
        self._region: dict[CellRef, str] = {}
        self._complex_ids: set[int] = set()
        self._rows_seen = 0
        self._peak_chunk_rows = 0
        self._peak_live_rows = 0
        self._samples = 0
        self._fed = False

        self._aborted = False   # CR51-1 — 상한에 걸려 중단됐는가
    # -- 실측값 (로그·테스트가 읽는다) --------------------------------------

    @property
    def rows_seen(self) -> int:
        """지금까지 **통과시킨** 행 수. 보유량이 아니다."""
        return self._rows_seen

    @property
    def peak_chunk_rows(self) -> int:
        """한 청크의 최대 행 수. **`chunk_rows` 를 넘을 수 없다.**

        ⚠️ 이것은 **원본 행**만 센다. 진짜 순간 보유량은 `peak_live_rows` 다.
        """
        return self._peak_chunk_rows

    @property
    def peak_live_rows(self) -> int:
        """한 순간에 손에 쥔 최대 **행 자리** 수 = 청크 + 그 as-of 뷰. 상한 `2 × chunk_rows`.

        옛 판은 이 값을 재지 않고 `peak_chunk_rows` 만 로그에 찍어 상한을 **절반으로**
        말했다(CR50-1) — 운영 `apt_dong` 보유율이 77~93%라 뷰가 거의 전부
        `dataclasses.replace()` **사본**이기 때문이다.

        ⚠️ 정확히 말하면 **자리 수**이지 서로 다른 객체 수가 아니다. 마스킹이 안 걸리는
           행은 뷰가 원본을 그대로 가리키므로 실제 객체는 그만큼 적다. 즉 이 값은
           **위로 잡은 상한**이고, 운영 모양에서는 그 상한이 곧 실제값이다.
           (바이트로는 2배가 아니다 — 사본이 문자열·날짜를 공유한다. 머리주석 상한 ① 실측표.)
        """
        return self._peak_live_rows

    @property
    def samples(self) -> int:
        """누적 표본(₩/㎡ 값) 수. `max_samples` 로 상한이 걸린다."""
        return self._samples

    @property
    def chunk_rows(self) -> int:
        return self._chunk_rows

    @property
    def complex_ids(self) -> set[int]:
        """후보가 될 수 있는 단지 id — 세대수 조회에 쓴다.

        전 구간 거래의 단지가 아니라 **T 창에 거래가 있던 단지**뿐이다(그 밖은
        어차피 유니버스에 못 든다). 조회 대상이 줄어드는 것은 덤이다.
        """
        return set(self._complex_ids)

    # -- 수집 ---------------------------------------------------------------

    def feed(self, trades: Iterable[BacktestTrade]) -> None:
        """거래를 **청크 단위로만** 소비한다. ⚠️ **한 번만 부른다.**

        ⛔ 여기에 `list(trades)` 를 쓰지 마라 — 그러면 이 클래스의 존재 이유가 없어진다.
        청크를 넘기기 전에 `clear()` 로 참조를 끊으므로, 다음 청크를 만드는 순간에도
        직전 청크의 행은 이미 죽어 있다(청크가 겹쳐 쌓이지 않는다).

        두 번 부르면 `StreamAlreadyConsumed` 로 죽는다 — 옛 판은 **조용히 두 배로 셌고**,
        그 표본 수는 환금성 축의 분자다(CR50-3). 스트림이 여럿이면 `itertools.chain` 으로
        하나로 합쳐 넘긴다.
        """
        if self._fed:
            raise StreamAlreadyConsumed(_FEED_TWICE_MSG)
        source = iter(trades)
        if source in _CLAIMED:
            raise StreamAlreadyConsumed(_CLAIMED_MSG)
        try:
            _CLAIMED.add(source)
        except TypeError:
            # 약한 참조를 못 거는 이터레이터. 위 `_CLAIMED` 주석의 한계 그대로다.
            pass
        self._fed = True
        while True:
            chunk = list(islice(source, self._chunk_rows))
            if not chunk:
                return
            self._rows_seen += len(chunk)
            self._peak_chunk_rows = max(self._peak_chunk_rows, len(chunk))
            self._feed_chunk(chunk)
            chunk.clear()

    def _feed_chunk(self, chunk: list[BacktestTrade]) -> None:
        for view_as_of, window_ids in self._by_as_of.items():
            # 자르는 곳은 여기서도 `asof.as_of_trades` 하나다(§5-2). 청크로 나눠 부르는 것이
            # 결과를 바꾸지 않는 이유: 각 행의 생사는 **그 행과 as_of** 만으로 정해진다.
            view = as_of_trades(chunk, as_of=view_as_of, policy=self._policy,
                                report_lag_days=self._report_lag_days)
            # ★ 진짜 순간 보유량 = 청크 + 이 뷰. 뷰는 대부분 마스킹 **사본**이라
            #   같은 객체를 가리키지 않는다(CR50-1). 여기서 재지 않으면 상한을 절반으로
            #   말하게 된다 — 실제로 그랬다.
            live = len(chunk) + len(view)
            if live > self._peak_live_rows:
                self._peak_live_rows = live
            if view_as_of in self._assert_dates:
                assert_as_of(view, as_of=view_as_of,
                             report_lag_days=self._report_lag_days)
            for trade in view:
                ref = trade.cell
                if ref is None:
                    continue          # 면적을 모르면 면적대를 못 정한다 — 버린다
                ppm = trade.ppm_krw
                contract_date = trade.contract_date
                for index in window_ids:
                    window = self._windows[index]
                    if not (window.start < contract_date <= window.end):
                        continue
                    bucket = self._values[index].get(ref)
                    if bucket is None:
                        bucket = self._values[index][ref] = array("d")
                    bucket.append(ppm)
                    self._samples += 1
                    if window.kind == KIND_START:
                        self._complex_ids.add(ref.complex_id)
                        if trade.region_code and ref not in self._region:
                            self._region[ref] = trade.region_code
            view.clear()
        if self._max_samples is not None and self._samples > self._max_samples:
            # ⛔ CR51-1 — **중단된 수집은 부분 결과를 내면 안 된다.**
            #    예전에는 여기서 예외만 던지고 `_fed` 는 True 인 채였다. 호출자가 그 예외를
            #    잡고 `cells()` 를 물으면 **절반만 담긴 결과가 조용히 나갔다**(재현: 정상 5셀이
            #    max_samples=40 이면 3셀, 60 이면 outcomes 4/5 — 예외도 경고도 없이).
            #    "덜 본 것"과 "없는 것"이 같아 보이는, 이 저장소가 반복해 고친 그 형태다.
            self._aborted = True
            raise SampleLimitExceeded(
                f"누적 표본 {self._samples:,}개가 상한 {self._max_samples:,}개를 넘었습니다 "
                f"(행 {self._rows_seen:,}개 통과). 폴드를 나눠 돌리거나 "
                "--max-samples 로 상한을 올리세요 — 올리기 전에 서버 가용 메모리를 "
                "확인하세요(표본 1개 ≈ 8B + 버킷 부대비용, backtest.md §7-13).")

    # -- 산출 ---------------------------------------------------------------

    def cells(self, spec: FoldSpec, *,
              households: Mapping[int, int | None] | None = None) -> list[AsOfCell]:
        """모아 둔 표본 → T 시점 후보 유니버스. `build_cells` 와 같은 결과다."""
        self._require_fed()
        start_index = self._window_index(spec, KIND_START)
        prior_index = self._window_index(spec, KIND_PRIOR)
        start_window = self._windows[start_index]
        prior_window = self._windows[prior_index]
        counts = households or {}

        kept: list[AsOfCell] = []
        for ref, values in self._values[start_index].items():
            price = price_from_values(values, window_months=spec.window_months,
                                      window_end=start_window.end,
                                      min_trades=self._min_trades)
            if not price.available:
                continue
            prior = price_from_values(
                self._values[prior_index].get(ref, _EMPTY),
                window_months=spec.window_months, window_end=prior_window.end,
                min_trades=self._min_trades)
            kept.append(AsOfCell(
                ref=ref, as_of=spec.as_of,
                sigungu=sigungu_of(self._region.get(ref)),
                price=price, prior_price=prior,
                window_trade_count=price.sample_size,
                total_households=counts.get(ref.complex_id),
            ))
        return attach_peer_medians(kept, min_peer_cells=self._min_peer_cells)

    def outcomes(self, spec: FoldSpec,
                 cells: Sequence[AsOfCell]) -> dict[CellRef, CellOutcome]:
        """T+H 실현 결과. **점수는 이미 확정된 뒤에** 붙는다(`run_fold` 순서)."""
        self._require_fed()
        end_index = self._window_index(spec, KIND_END)
        end_window = self._windows[end_index]
        bucket = self._values[end_index]

        outcomes: dict[CellRef, CellOutcome] = {}
        for cell in cells:
            end = price_from_values(bucket.get(cell.ref, _EMPTY),
                                    window_months=spec.window_months,
                                    window_end=end_window.end,
                                    min_trades=self._min_trades)
            outcomes[cell.ref] = make_outcome(cell.ref, cell.sigungu,
                                              start=cell.price, end=end)
        return outcomes

    def _require_fed(self) -> None:
        """`feed` 없이 산출을 물으면 멈춘다 — 빈 결과가 '데이터가 없다'로 읽힌다."""
        if not self._fed:
            raise RuntimeError(_NOT_FED_MSG)
        # ⛔ CR51-1 — 중단된 수집의 산출은 **부분 결과**다. 내주지 않는다.
        if self._aborted:
            raise SampleLimitExceeded(
                "표본 상한에 걸려 수집이 중단됐습니다 — 산출은 부분 결과라 내주지 않습니다. "
                "--max-samples 를 올리거나 폴드를 나눠 다시 돌리세요.")

    def _window_index(self, spec: FoldSpec, kind: str) -> int:
        if kind not in self._kinds:
            raise ValueError(
                f"이 수집기는 {kind!r} 시점을 모으지 않았습니다 (모은 것: {self._kinds}).")
        try:
            spec_index = self._specs.index(spec)
        except ValueError:
            raise ValueError(f"이 수집기가 모르는 폴드입니다: {spec.name}") from None
        for index, window in enumerate(self._windows):
            if window.spec_index == spec_index and window.kind == kind:
                return index
        raise ValueError(f"창을 찾지 못했습니다: {spec.name} / {kind}")   # 도달 불가


def attach_peer_medians(cells: Sequence[AsOfCell], *,
                        min_peer_cells: int = MIN_PEER_CELLS) -> list[AsOfCell]:
    """(시군구, 면적대) 별 ₩/㎡ 중위를 각 셀에 붙인다. 피어가 모자라면 **None**.

    ⚠️ 자기 자신을 포함한 중위다. 셀이 충분히 많으면 영향이 없고, 제외하면 셀마다
       분모가 달라져 '같은 잣대'가 아니게 된다(같은 목록을 다른 자로 재는 문제 —
       `timeadjust.select_index` 가 낡은 기준월을 거부하는 것과 같은 이유).
    """
    groups: dict[tuple[str, str], list[int]] = {}
    for cell in cells:
        key = cell.peer_key
        if key is None or not cell.price.median_ppm_krw:
            continue
        groups.setdefault(key, []).append(cell.price.median_ppm_krw)

    medians = {k: int(round(statistics.median(v)))
               for k, v in groups.items() if len(v) >= min_peer_cells}

    out: list[AsOfCell] = []
    for cell in cells:
        key = cell.peer_key
        peer = medians.get(key) if key else None
        out.append(cell if peer is None else replace(cell, peer_median_ppm_krw=peer))
    # 결정적 순서. 딕셔너리 삽입 순서(= 거래가 들어온 순서)가 결과에 새지 않게 한다.
    out.sort(key=lambda c: (c.ref.complex_id, c.ref.band))
    return out
