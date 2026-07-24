"""호가 매물 중복 제거와 신뢰도 산정.

설계 근거: docs/02-design/agents/01-listing-researcher.md, docs/02-design/erd.md §4

왜 중복 제거가 중요한가
-----------------------
같은 물건이 여러 중개사에 올라온다. 중복을 안 접으면 "매물 100건"이 실제로는 12건이다.
사용자는 선택지가 많다고 착각하고, 통계도 오염된다.

**다만 삭제하지 않는다.** 같은 물건을 올린 중개사 수 자체가
"많이 나왔는데 안 팔리는 물건" 이라는 신호이기 때문이다. 대표건에 묶어두고 개수를 센다.

trust_score 규약
----------------
**신뢰도**다. 1.0 = 신뢰할 만함, 0.0 = 매우 의심스러움. (의심도가 아니다 — 부호 주의)
그리고 이건 **판정이 아니라 의심도**다. 급매(진짜 싼 물건)와 미끼는 데이터만으로
구분되지 않는다. "허위매물입니다" 라고 단정하면 안 된다.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.domain.valuation.models import ListingRow

#: 호가가 이 비율 안이면 같은 물건일 수 있다고 본다.
PRICE_TOLERANCE = 0.01          # ±1%
#: 전용면적 매칭 허용 오차(㎡)
AREA_TOLERANCE_M2 = 0.5
#: 이 기간 이상 안 팔리면 의심 신호
STALE_DAYS = 90


@dataclass(frozen=True)
class ListingGroup:
    """중복으로 묶인 한 물건."""

    representative: ListingRow
    duplicates: tuple[ListingRow, ...] = ()

    @property
    def duplicate_count(self) -> int:
        """대표건 포함 등록 건수. 1이면 중복 없음."""
        return 1 + len(self.duplicates)

    @property
    def agencies(self) -> tuple[str, ...]:
        names = [l.agency for l in (self.representative, *self.duplicates) if l.agency]
        return tuple(sorted(set(names)))


def _same_unit(a: ListingRow, b: ListingRow) -> bool:
    if abs(a.area_m2 - b.area_m2) > AREA_TOLERANCE_M2:
        return False
    if a.floor != b.floor:
        return False
    # 동이 둘 다 표기됐는데 다르면 다른 물건이다.
    if a.building_id is not None and b.building_id is not None:
        if a.building_id != b.building_id:
            return False
    return True


def _price_close(a: ListingRow, b: ListingRow) -> bool:
    hi = max(a.ask_price_krw, b.ask_price_krw)
    if hi <= 0:
        return False
    return abs(a.ask_price_krw - b.ask_price_krw) / hi <= PRICE_TOLERANCE


def _periods_overlap(a: ListingRow, b: ListingRow) -> bool:
    """활성 기간이 겹치는가.

    둘 다 현재 활성이면 겹치는 것으로 본다. 아니면 [listed_at, collected_at] 구간 비교.
    날짜를 모르면 **겹친다고 가정한다** — 중복을 놓치는 쪽보다 묶는 쪽이 안전하다
    (묶어도 원본은 보존되므로 되돌릴 수 있다).
    """
    if a.status == "active" and b.status == "active":
        return True
    a_start, a_end = a.listed_at, a.collected_at
    b_start, b_end = b.listed_at, b.collected_at
    if None in (a_start, a_end, b_start, b_end):
        return True
    return a_start <= b_end and b_start <= a_end


def group_duplicates(listings: Iterable[ListingRow]) -> list[ListingGroup]:
    """중복 매물을 묶는다. 대표건은 **가장 먼저 등록된 것**(원출처에 가깝다)."""
    items = list(listings)
    # 등록일이 이른 순 → 없으면 id 순. 대표건 선택을 결정론적으로 만든다.
    items.sort(key=lambda l: (l.listed_at or dt.date.max, l.id))

    groups: list[list[ListingRow]] = []
    for item in items:
        for g in groups:
            rep = g[0]
            if _same_unit(rep, item) and _price_close(rep, item) and _periods_overlap(rep, item):
                g.append(item)
                break
        else:
            groups.append([item])

    return [ListingGroup(representative=g[0], duplicates=tuple(g[1:])) for g in groups]


def trust_score(
    group: ListingGroup,
    *,
    median_price_krw: int | None,
    as_of: dt.date | None = None,
) -> tuple[float, list[str]]:
    """신뢰도(1.0 = 신뢰할 만함)와 그 근거 신호 목록.

    시세를 모르면(`median_price_krw is None`) 가격 관련 감점은 하지 않는다.
    모르는 걸 근거로 감점하면 그것도 환각이다.
    """
    as_of = as_of or dt.date.today()
    rep = group.representative
    score = 1.0
    signals: list[str] = []

    # 1) 시세 대비 지나친 저가 — 미끼일 수 있다(급매일 수도 있다)
    if median_price_krw and median_price_krw > 0:
        gap = (rep.ask_price_krw - median_price_krw) / median_price_krw
        if gap <= -0.25:
            score -= 0.35
            signals.append(f"시세 대비 {gap * 100:.1f}% — 확인 필요")
        elif gap <= -0.15:
            score -= 0.20
            signals.append(f"시세 대비 {gap * 100:.1f}% — 급매 또는 미끼 가능")

    # 2) 장기 미거래 — 실재하지 않거나 안 팔리는 물건
    if rep.listed_at:
        days = (as_of - rep.listed_at).days
        if days >= STALE_DAYS * 2:
            score -= 0.20
            signals.append(f"등록 {days}일 경과")
        elif days >= STALE_DAYS:
            score -= 0.10
            signals.append(f"등록 {days}일 경과")

    # 3) 중복 등록 과다
    n = group.duplicate_count
    if n >= 8:
        score -= 0.20
        signals.append(f"{n}개 중개사 중복 등록")
    elif n >= 4:
        score -= 0.10
        signals.append(f"{n}개 중개사 중복 등록")

    # 4) 최근 수집으로 살아있음이 확인됨 — 소폭 가산
    if rep.collected_at and (as_of - rep.collected_at).days <= 1:
        score += 0.05
        signals.append("최근 확인됨")

    return round(min(1.0, max(0.0, score)), 3), signals


def filter_by_avoid(
    groups: Sequence[ListingGroup],
    avoid: dict[str, object] | None,
) -> tuple[list[ListingGroup], dict[str, int]]:
    """사용자 기피 조건으로 **제외**한다.

    기피는 가중치 감점이 아니라 제외다. "피하고 싶다"고 한 걸 점수로 상쇄해서
    추천에 올리면 사용자는 배신감을 느낀다.
    """
    avoid = avoid or {}
    kept: list[ListingGroup] = []
    dropped: dict[str, int] = {}

    for g in groups:
        rep = g.representative
        reason: str | None = None

        if avoid.get("first_floor") and rep.floor is not None and rep.floor <= 1:
            reason = "avoid_first_floor"
        elif avoid.get("top_floor_only") and rep.floor is not None and rep.floor >= 900:
            reason = "avoid_top_floor"

        max_floor = avoid.get("floor_below")
        if reason is None and isinstance(max_floor, int) and rep.floor is not None:
            if rep.floor < max_floor:
                reason = "avoid_low_floor"

        if reason:
            dropped[reason] = dropped.get(reason, 0) + 1
        else:
            kept.append(g)

    return kept, dropped
