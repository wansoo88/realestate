"""호가 매물 중복 제거·신뢰도 테스트.

핵심: 중복은 **묶되 삭제하지 않는다.** 중개사 수 자체가 신호이기 때문이다.
"""
from __future__ import annotations

import datetime as dt

from app.domain.listings.dedup import (
    filter_by_avoid,
    group_duplicates,
    trust_score,
)
from app.domain.valuation.models import ListingRow

TODAY = dt.date(2026, 7, 24)
OKU = 100_000_000


def L(i, price_oku, *, area=84.97, floor=9, listed_days=10, agency=None,
      building=None, status="active") -> ListingRow:
    return ListingRow(
        id=i,
        ask_price_krw=int(price_oku * OKU),
        area_m2=area,
        floor=floor,
        listed_at=TODAY - dt.timedelta(days=listed_days),
        collected_at=TODAY,
        agency=agency,
        building_id=building,
        status=status,
    )


# ---------------------------------------------------------------------------
# 중복 제거
# ---------------------------------------------------------------------------

def test_같은_물건은_하나로_묶인다():
    listings = [L(1, 14.8, agency="A"), L(2, 14.8, agency="B"), L(3, 14.85, agency="C")]
    groups = group_duplicates(listings)

    assert len(groups) == 1
    assert groups[0].duplicate_count == 3
    assert set(groups[0].agencies) == {"A", "B", "C"}


def test_중복은_삭제되지_않고_보존된다():
    listings = [L(1, 14.8, agency="A"), L(2, 14.8, agency="B")]
    groups = group_duplicates(listings)

    all_ids = {groups[0].representative.id} | {d.id for d in groups[0].duplicates}
    assert all_ids == {1, 2}, "중복 원본이 사라지면 안 된다 (중개사 수가 신호다)"


def test_가격이_1퍼센트_넘게_다르면_다른_물건():
    listings = [L(1, 14.0), L(2, 14.5)]        # 3.5% 차이
    assert len(group_duplicates(listings)) == 2


def test_층이_다르면_다른_물건():
    assert len(group_duplicates([L(1, 14.8, floor=9), L(2, 14.8, floor=12)])) == 2


def test_면적이_다르면_다른_물건():
    assert len(group_duplicates([L(1, 14.8, area=84.97), L(2, 14.8, area=59.98)])) == 2


def test_동이_둘_다_표기되고_다르면_다른_물건():
    listings = [L(1, 14.8, building=101), L(2, 14.8, building=105)]
    assert len(group_duplicates(listings)) == 2


def test_동이_한쪽만_표기되면_같은_물건일_수_있다():
    listings = [L(1, 14.8, building=None), L(2, 14.8, building=101)]
    assert len(group_duplicates(listings)) == 1


def test_대표건은_가장_먼저_등록된_것():
    listings = [L(3, 14.8, listed_days=5), L(1, 14.8, listed_days=40),
                L(2, 14.8, listed_days=20)]
    groups = group_duplicates(listings)
    assert groups[0].representative.id == 1


def test_결정론적이다():
    listings = [L(1, 14.8), L(2, 14.8), L(3, 14.8)]
    a = group_duplicates(listings)
    b = group_duplicates(list(reversed(listings)))
    assert a[0].representative.id == b[0].representative.id


# ---------------------------------------------------------------------------
# 신뢰도
# ---------------------------------------------------------------------------

def test_정상_매물은_신뢰도가_높다():
    g = group_duplicates([L(1, 14.5, listed_days=10)])[0]
    score, signals = trust_score(g, median_price_krw=int(14.0 * OKU), as_of=TODAY)
    assert score >= 0.9


def test_시세보다_많이_싸면_신뢰도가_떨어진다():
    g = group_duplicates([L(1, 10.0, listed_days=5)])[0]     # 시세 14억 대비 -28%
    score, signals = trust_score(g, median_price_krw=int(14.0 * OKU), as_of=TODAY)

    assert score < 0.75
    assert any("시세 대비" in s for s in signals)


def test_시세를_모르면_가격으로_감점하지_않는다():
    g = group_duplicates([L(1, 10.0, listed_days=5)])[0]
    score, signals = trust_score(g, median_price_krw=None, as_of=TODAY)

    assert score >= 0.95, "모르는 걸 근거로 감점하면 그것도 환각이다"
    assert not any("시세" in s for s in signals)


def test_장기_미거래는_감점된다():
    fresh = group_duplicates([L(1, 14.5, listed_days=10)])[0]
    stale = group_duplicates([L(2, 14.5, listed_days=200)])[0]
    median = int(14.0 * OKU)

    s_fresh, _ = trust_score(fresh, median_price_krw=median, as_of=TODAY)
    s_stale, signals = trust_score(stale, median_price_krw=median, as_of=TODAY)

    assert s_stale < s_fresh
    assert any("경과" in s for s in signals)


def test_중복_과다는_감점된다():
    many = group_duplicates([L(i, 14.5, agency=f"A{i}") for i in range(1, 10)])[0]
    one = group_duplicates([L(1, 14.5, agency="A")])[0]
    median = int(14.0 * OKU)

    s_many, signals = trust_score(many, median_price_krw=median, as_of=TODAY)
    s_one, _ = trust_score(one, median_price_krw=median, as_of=TODAY)

    assert s_many < s_one
    assert any("중복 등록" in s for s in signals)


def test_신뢰도는_0과_1_사이():
    worst = group_duplicates(
        [L(i, 5.0, listed_days=400, agency=f"A{i}") for i in range(1, 12)])[0]
    score, _ = trust_score(worst, median_price_krw=int(14.0 * OKU), as_of=TODAY)
    assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# 기피 조건 — 가중치가 아니라 제외
# ---------------------------------------------------------------------------

def test_기피조건은_제외한다():
    groups = group_duplicates([L(1, 14.0, floor=1), L(2, 14.5, floor=9)])
    kept, dropped = filter_by_avoid(groups, {"first_floor": True})

    assert len(kept) == 1
    assert kept[0].representative.floor == 9
    assert dropped["avoid_first_floor"] == 1


def test_기피조건_없으면_전부_통과():
    groups = group_duplicates([L(1, 14.0, floor=1), L(2, 14.5, floor=9)])
    kept, dropped = filter_by_avoid(groups, None)
    assert len(kept) == 2
    assert dropped == {}


def test_제외_사유가_집계된다():
    """왜 이 매물이 안 보이는지 사용자에게 답할 수 있어야 한다."""
    groups = group_duplicates([L(i, 14.0 + i * 0.5, floor=1) for i in range(1, 4)])
    kept, dropped = filter_by_avoid(groups, {"first_floor": True})

    assert kept == []
    assert dropped["avoid_first_floor"] == 3
