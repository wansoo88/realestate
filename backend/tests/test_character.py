"""단지 유형(성격) 판정 — `app.domain.character`.

기대값은 **손으로 계산했다.** 코드에서 뽑아 오지 않았다.

손 계산이 가능하도록 대부분의 테스트가 `LINEAR_LADDER` 를 주입한다:
10칸 사다리 `(0, 10, …, 90)` 에서 원점수 v(10의 배수)의 중간순위 백분위는

    lo = bisect_left = v/10,  hi = bisect_right = v/10 + 1
    pct = (lo + hi) / 2 / 10 × 100 = v + 5

즉 **백분위 = 원점수 + 5** 다. 그러면 축 평균 대비 편차가 원점수 편차와 같아져
모든 판정을 암산으로 검산할 수 있다. (운영 사다리는 101개 실측값이라 손 검산이
불가능한데, 검산할 수 없는 기대값은 테스트가 아니라 스냅샷이다.)

운영 사다리 자체는 §"운영 사다리" 에서 **구조와 문서화된 한계**만 검증한다.
"""
from __future__ import annotations

import pytest

from app.domain.character.analysis import (
    ALLROUND_MIN_PERCENTILE,
    BORDERLINE_MARGIN,
    DEVIATION_THRESHOLD,
    MIN_AXES,
    PRICE_CHEAP_MAX,
    PRICE_MIN_SAMPLE,
    PRICE_PREMIUM_MIN,
    TOP_TIER_PERCENTILE,
    TYPE_MIN_PERCENTILE,
    classify_character,
    price_status,
    read_axes,
)
from app.domain.character.ladders import (
    LADDER_POPULATION,
    PERCENTILE_LADDERS,
    percentile_of,
)
from app.domain.character.models import (
    AXIS_INFRA,
    AXIS_LIQUIDITY,
    AXIS_SCHOOL,
    AXIS_TRANSIT,
    CHARACTER_AXES,
    PRICE_CHEAP,
    PRICE_PREMIUM,
    PRICE_TYPICAL,
    PRICE_UNKNOWN,
    TYPE_ALLROUND,
    TYPE_BALANCED,
    TYPE_LIQUIDITY,
    TYPE_SCHOOL,
    TYPE_TRANSIT,
    TYPE_VALUE,
    TYPE_WITHHELD,
    WITHHELD_TOO_FEW_AXES,
    PriceContext,
)

#: 백분위 = 원점수 + 5 가 되는 사다리 (위 docstring 참조).
_LINEAR = tuple(range(0, 100, 10))
LINEAR_LADDER = dict.fromkeys(CHARACTER_AXES, _LINEAR)


def cls(scores, price=None):
    return classify_character(scores, price, ladders=LINEAR_LADDER)


def four(school, transit, infra, liquidity):
    return {AXIS_SCHOOL: school, AXIS_TRANSIT: transit,
            AXIS_INFRA: infra, AXIS_LIQUIDITY: liquidity}


# ---------------------------------------------------------------------------
# 0. 사다리 산수 — 위 docstring 의 주장이 사실인지부터 못 박는다
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [0, 10, 30, 50, 70, 90])
def test_linear_ladder_percentile_is_raw_plus_five(raw):
    assert percentile_of(raw, _LINEAR) == pytest.approx(raw + 5)


def test_percentile_uses_midrank_for_ties():
    """동점은 중간 순위. 앞(0%)도 뒤(100%)도 아니다.

    사다리 `(5, 5, 5, 5)` 에서 5 는 lo=0, hi=4 → (0+4)/2/4 = 50%.
    """
    assert percentile_of(5, (5, 5, 5, 5)) == pytest.approx(50.0)
    assert percentile_of(4, (5, 5, 5, 5)) == pytest.approx(0.0)
    assert percentile_of(6, (5, 5, 5, 5)) == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# 1. 축 읽기 — 미확보를 0 으로 채우지 않는다
# ---------------------------------------------------------------------------

def test_missing_axis_is_not_zero():
    """`None`(미확보)과 `0`(재 봤더니 최하)은 다른 값이어야 한다."""
    missing = read_axes(four(70, None, 70, 70), LINEAR_LADDER)
    zeroed = read_axes(four(70, 0, 70, 70), LINEAR_LADDER)

    tr_missing = next(a for a in missing if a.axis == AXIS_TRANSIT)
    tr_zero = next(a for a in zeroed if a.axis == AXIS_TRANSIT)
    assert tr_missing.percentile is None and tr_missing.deviation is None
    assert tr_zero.percentile == pytest.approx(5.0)      # 0 + 5

    # 미확보 축은 **평균에서도 빠진다** → 남은 축의 편차가 0
    sc_missing = next(a for a in missing if a.axis == AXIS_SCHOOL)
    assert sc_missing.deviation == pytest.approx(0.0)
    # 0 으로 채우면 평균이 (75+5+75+75)/4 = 57.5 로 내려가 학군이 +17.5 로 부푼다
    sc_zero = next(a for a in zeroed if a.axis == AXIS_SCHOOL)
    assert sc_zero.deviation == pytest.approx(17.5)


def test_axes_always_returned_in_fixed_order():
    axes = read_axes(four(70, None, 70, None), LINEAR_LADDER)
    assert tuple(a.axis for a in axes) == CHARACTER_AXES


# ---------------------------------------------------------------------------
# 2. 각 유형
# ---------------------------------------------------------------------------

def test_school_type():
    """학군 90 / 나머지 40 → 백분위 95·45·45·45, 평균 57.5, 학군 편차 +37.5."""
    ch = cls(four(90, 40, 40, 40))
    assert ch.type_code == TYPE_SCHOOL
    assert ch.label == "학군형"
    assert ch.sub_type_code is None
    assert ch.axes_used == 4
    school = next(a for a in ch.axes if a.axis == AXIS_SCHOOL)
    assert school.percentile == pytest.approx(95.0)
    assert school.deviation == pytest.approx(37.5)
    # 95 >= TOP_TIER(90) → '최상위권'. 상위 100-95 = 5%
    assert ch.headline.startswith("학군이 최상위권입니다(상위 5%).")


def test_transit_type_below_top_tier_says_most_prominent():
    """교통 70 / 나머지 30 → 백분위 75·35·35·35, 평균 45, 편차 +30.

    75 < TOP_TIER(90) 이므로 '최상위권'이 아니라 '가장 두드러집니다'.
    """
    ch = cls({AXIS_SCHOOL: 30, AXIS_TRANSIT: 70, AXIS_INFRA: 30, AXIS_LIQUIDITY: 30})
    assert ch.type_code == TYPE_TRANSIT
    assert ch.headline.startswith("교통이 이 단지에서 가장 두드러집니다(상위 25%).")


def test_two_axes_get_sub_type_and_weak_clause():
    """학군·교통 90 / 생활·환금 10 → 백분위 95·95·15·15, 평균 55.

    편차 +40 · +40 · −40 · −40. 둘 다 임계(20) 이상 → 주+부.
    편차 −40 ≤ WEAK(−25) → 약점 문구. 조사: '학군'+과, '거래 회전'+은.
    """
    ch = cls(four(90, 90, 10, 10))
    assert ch.type_code == TYPE_SCHOOL
    assert ch.sub_type_code == TYPE_TRANSIT
    assert ch.labels == ("학군형", "역세권형")
    assert ch.weak_axis == AXIS_LIQUIDITY
    assert ch.headline == (
        "학군과 교통 둘 다 최상위인 조합입니다(상위 5% · 상위 5%)."
        " 다만 거래 회전은 하위 15%입니다.")


def test_allround_type():
    """모든 축 80 → 백분위 85, 편차 0. 최저 85 ≥ 65 → 올라운드형."""
    ch = cls(four(80, 80, 80, 80))
    assert ch.type_code == TYPE_ALLROUND
    assert ch.headline == "측정한 네 축이 모두 상위권입니다(가장 낮은 축도 상위 15%)."


def test_balanced_all_above_median():
    """70·70·60·50 → 백분위 75·75·65·55. 평균 67.5, 최대 편차 +7.5 < 20.

    최저 55 < 65 → 올라운드 아님. 최저가 50 이상 → '모두 전국 중위 이상'.
    """
    ch = cls(four(70, 70, 60, 50))
    assert ch.type_code == TYPE_BALANCED
    assert ch.headline == (
        "두드러지는 축이 없습니다 — 네 축이 모두 전국 중위 이상이지만 "
        "특별히 튀는 축은 없습니다.")


def test_balanced_all_below_median_says_so():
    """모든 축 20 → 백분위 25. 평평하지만 **전부 중위 아래**임을 숨기지 않는다."""
    ch = cls(four(20, 20, 20, 20))
    assert ch.type_code == TYPE_BALANCED
    assert ch.headline == "네 축이 모두 전국 중위 아래입니다(가장 높은 축도 하위 25%)."


def test_balanced_straddling_median_names_the_outlier():
    """80·80·80·20 → 백분위 85·85·85·25. 평균 70, 최대 편차 +15 < 20 → 평평.

    최저 25 < 50 이고 중앙값 85 ≥ 50 → '대체로 중위 이상 + 가장 낮은 축 이름'.
    (여기서 '중위 근처'라고만 쓰면 세 축이 상위권인 사실이 지워진다.)
    """
    ch = cls(four(80, 80, 80, 20))
    assert ch.type_code == TYPE_BALANCED
    assert ch.headline == (
        "두드러지는 축이 없습니다 — 네 축이 대체로 전국 중위 이상이고, "
        "가장 낮은 거래 회전만 하위 25%입니다.")


def test_value_type_needs_flat_shape_and_cheap_price():
    """평평 + 배율 0.80(≤0.85) + 표본 12(≥5) → 가성비형."""
    price = PriceContext(ratio=0.80, sample_size=12, scope_label="○○구 60~85㎡")
    ch = cls(four(20, 20, 20, 20), price)
    assert ch.type_code == TYPE_VALUE
    assert ch.price_status == PRICE_CHEAP
    assert ch.price_gap_pct == pytest.approx(-20.0)
    assert ch.headline == (
        "네 축이 모두 전국 중위 아래입니다(가장 높은 축도 하위 25%)."
        " 다만 ○○구 60~85㎡ 단지들의 실거래 중위보다 ㎡당 20% 낮아,"
        " 같은 예산으로 면적을 더 갑니다.")


def test_shape_beats_price_value_does_not_steal_a_standout_axis():
    """싸더라도 두드러진 축이 있으면 주 유형은 그 축이다. 가격은 문구로만 붙는다."""
    price = PriceContext(ratio=0.70, sample_size=30, scope_label="○○구 60~85㎡")
    ch = cls(four(90, 40, 40, 40), price)
    assert ch.type_code == TYPE_SCHOOL
    assert ch.price_status == PRICE_CHEAP
    assert ch.headline.endswith(
        "○○구 60~85㎡ 단지들의 실거래 중위보다 ㎡당 30% 낮습니다.")


def test_liquidity_type():
    """환금 90 / 나머지 40 → 거래활발형. 유형 코드가 축 코드와 이어진다."""
    ch = cls(four(40, 40, 40, 90))
    assert ch.type_code == TYPE_LIQUIDITY
    assert ch.label == "거래활발형"


# ---------------------------------------------------------------------------
# 3. 경계
# ---------------------------------------------------------------------------

def test_exactly_at_threshold_is_typed_and_flagged_borderline():
    """3축(환금 미확보) 70·40·40 → 백분위 75·45·45, 평균 55, 편차 **정확히 +20.**

    임계는 '이상'이므로 유형이 붙고, margin 0 이라 경계 표시가 켜진다.
    """
    ch = cls({AXIS_SCHOOL: 70, AXIS_TRANSIT: 40, AXIS_INFRA: 40, AXIS_LIQUIDITY: None})
    assert ch.type_code == TYPE_SCHOOL
    assert ch.margin == pytest.approx(0.0)
    assert ch.borderline is True
    assert ch.axes_used == 3


def test_just_below_threshold_falls_to_balanced():
    """3축 60·40·40 → 백분위 65·45·45, 평균 51.67, 편차 +13.3 < 20 → 평평."""
    ch = cls({AXIS_SCHOOL: 60, AXIS_TRANSIT: 40, AXIS_INFRA: 40, AXIS_LIQUIDITY: None})
    assert ch.type_code == TYPE_BALANCED
    assert ch.margin == pytest.approx(-6.7)
    assert ch.borderline is False


def test_borderline_window_matches_constant():
    """편차가 임계 + BORDERLINE_MARGIN 을 넘으면 경계가 아니다.

    90·10·10·10 → 백분위 95·15·15·15, 평균 (95+45)/4 = 35, 학군 편차 +60.
    margin = 60 − 20 = 40 이므로 경계 창(±3) 밖이다.
    """
    ch = cls(four(90, 10, 10, 10))
    assert ch.margin == pytest.approx(40.0)
    assert ch.borderline is False
    assert BORDERLINE_MARGIN == 3.0


def test_below_median_axis_never_becomes_a_type():
    """3축 40·10·10 → 백분위 45·15·15, 평균 25, 편차 **+20**(임계 통과).

    그런데 45 < TYPE_MIN_PERCENTILE(50) 이다. 전국 하위 절반인 축을 '강점'이라
    부르지 않는다 — '덜 나쁜 축'일 뿐이다. → 유형이 아니라 평평으로 떨어진다.
    """
    ch = cls({AXIS_SCHOOL: 40, AXIS_TRANSIT: 10, AXIS_INFRA: 10, AXIS_LIQUIDITY: None})
    assert ch.type_code == TYPE_BALANCED
    assert ch.headline == "세 축이 모두 전국 중위 아래입니다(가장 높은 축도 하위 45%)."
    assert TYPE_MIN_PERCENTILE == 50.0


def test_sub_type_also_needs_median_floor():
    """주 축은 통과하고 부 축은 편차만 통과할 때 부 유형이 붙으면 안 된다.

    3축 90·40·10 → 백분위 95·45·15, 평균 51.67.
    편차 +43.3 / −6.7 / −36.7 → 부 후보(교통)는 편차부터 미달 → 부 유형 없음.
    """
    ch = cls({AXIS_SCHOOL: 90, AXIS_TRANSIT: 40, AXIS_INFRA: 10, AXIS_LIQUIDITY: None})
    assert ch.type_code == TYPE_SCHOOL
    assert ch.sub_type_code is None
    assert ch.weak_axis == AXIS_INFRA


# ---------------------------------------------------------------------------
# 4. 판정 보류 · 표본 부족 · 커버리지 부족
# ---------------------------------------------------------------------------

def test_withheld_when_too_few_axes():
    """축 2개(<3) → 유형을 붙이지 않는다. **'특징 없음'이 아니다.**"""
    ch = cls({AXIS_SCHOOL: 90, AXIS_LIQUIDITY: 40})
    assert ch.type_code == TYPE_WITHHELD
    assert ch.assigned is False
    assert ch.labels == ()
    assert ch.withheld_reason == WITHHELD_TOO_FEW_AXES
    assert ch.axes_used == 2
    assert "교통" in ch.headline and "생활 인프라" in ch.headline
    assert MIN_AXES == 3


def test_withheld_when_no_axis_at_all():
    ch = cls({})
    assert ch.type_code == TYPE_WITHHELD
    assert ch.axes_used == 0


def test_three_axes_leaves_a_note_about_the_missing_one():
    ch = cls({AXIS_SCHOOL: 90, AXIS_TRANSIT: 40, AXIS_INFRA: 40, AXIS_LIQUIDITY: None})
    assert ch.axes_used == 3
    assert any("거래 회전" in n and "미확보" in n for n in ch.notes)


def test_thin_price_sample_is_not_a_price_claim():
    """실거래 4건(<5)이면 배율이 아무리 낮아도 '가성비형'이라 하지 않는다."""
    price = PriceContext(ratio=0.50, sample_size=4)
    ch = cls(four(20, 20, 20, 20), price)
    assert ch.type_code == TYPE_BALANCED
    assert ch.price_status == PRICE_UNKNOWN
    assert "㎡당" not in ch.headline
    assert any("4건" in n for n in ch.notes)


def test_no_price_context_at_all_is_noted_not_guessed():
    ch = cls(four(20, 20, 20, 20), None)
    assert ch.price_status == PRICE_UNKNOWN
    assert ch.price_gap_pct is None
    assert any("가격 비교는 하지 않았습니다" in n for n in ch.notes)


@pytest.mark.parametrize(("ratio", "expected"), [
    (0.84, PRICE_CHEAP),
    (0.85, PRICE_CHEAP),      # 경계 포함
    (0.86, PRICE_TYPICAL),
    (1.14, PRICE_TYPICAL),
    (1.15, PRICE_PREMIUM),    # 경계 포함
    (2.00, PRICE_PREMIUM),
])
def test_price_status_boundaries(ratio, expected):
    assert price_status(PriceContext(ratio=ratio, sample_size=10)) == expected


def test_price_status_rejects_nonpositive_ratio():
    assert price_status(PriceContext(ratio=0.0, sample_size=99)) == PRICE_UNKNOWN
    assert price_status(PriceContext(ratio=None, sample_size=99)) == PRICE_UNKNOWN


def test_typical_price_says_nothing():
    """배율이 평범하면 가격 이야기를 **아예 하지 않는다**(빈말 금지)."""
    ch = cls(four(90, 40, 40, 40), PriceContext(ratio=1.0, sample_size=50))
    assert ch.price_status == PRICE_TYPICAL
    assert "비쌉니다" not in ch.headline and "낮습니다" not in ch.headline


# ---------------------------------------------------------------------------
# 5. 문구가 값에서 나오는가 — 고정 문장이 아님을 못 박는다
# ---------------------------------------------------------------------------

def test_premium_phrase_appears_only_when_actually_expensive():
    axes = four(90, 40, 40, 40)
    cheapish = cls(axes, PriceContext(ratio=1.0, sample_size=50))
    pricey = cls(axes, PriceContext(ratio=1.60, sample_size=50))
    assert "대신" not in cheapish.headline
    assert pricey.headline.endswith(
        "같은 시군구·같은 면적대 단지들의 실거래 중위보다 ㎡당 60% 비쌉니다.")


def test_headline_number_tracks_the_percentile():
    """같은 유형이라도 백분위가 다르면 문구의 숫자가 달라야 한다."""
    strong = cls(four(90, 40, 40, 40))     # 학군 백분위 95 → 상위 5%
    weaker = cls(four(70, 30, 30, 30))     # 학군 백분위 75 → 상위 25%
    assert strong.type_code == weaker.type_code == TYPE_SCHOOL
    assert "상위 5%" in strong.headline
    assert "상위 25%" in weaker.headline


def test_korean_particle_follows_the_word():
    """조사가 값에 따라 갈린다 — '학군과'(받침) vs '생활 인프라와'(받침 없음)."""
    with_jong = cls(four(90, 90, 10, 10))                     # 학군 + 교통
    without_jong = cls({AXIS_SCHOOL: 10, AXIS_TRANSIT: 10,
                        AXIS_INFRA: 90, AXIS_LIQUIDITY: 90})  # 생활 인프라 + 거래 회전
    assert "학군과 교통" in with_jong.headline
    assert "생활 인프라와 거래 회전" in without_jong.headline


def test_ladder_note_is_always_present():
    for ch in (cls(four(90, 40, 40, 40)), cls({AXIS_SCHOOL: 40})):
        assert any("분포" in n for n in ch.notes)


# ---------------------------------------------------------------------------
# 6. 운영 사다리 — 구조와 **문서화된 한계**를 회귀로 고정한다
# ---------------------------------------------------------------------------

def test_operational_ladders_are_well_formed():
    assert set(PERCENTILE_LADDERS) == set(CHARACTER_AXES)
    for axis, ladder in PERCENTILE_LADDERS.items():
        assert len(ladder) == 101, axis
        assert list(ladder) == sorted(ladder), axis
        assert 0 <= ladder[0] and ladder[-1] <= 100, axis


def test_liquidity_axis_cannot_reach_the_top_tier_phrase():
    """환금 축은 회전율 5% 에서 캡돼 원점수 100 이 36% 나 된다.

    그래서 **어떤 단지도** '거래 회전이 최상위권'을 받을 수 없다. 이건 버그가 아니라
    척도의 한계이고, 문서(§8)와 상수 주석이 그렇게 적혀 있다. 누군가 사다리를
    갈아끼우면서 이 사실이 바뀌면 문서가 거짓이 되므로 여기서 잡는다.
    """
    lad = PERCENTILE_LADDERS[AXIS_LIQUIDITY]
    assert percentile_of(100.0, lad) < TOP_TIER_PERCENTILE
    # 반대로 학군·교통은 받을 수 있어야 한다(문구가 죽은 코드가 아님을 확인).
    assert percentile_of(100.0, PERCENTILE_LADDERS[AXIS_SCHOOL]) >= TOP_TIER_PERCENTILE
    assert percentile_of(100.0, PERCENTILE_LADDERS[AXIS_TRANSIT]) >= TOP_TIER_PERCENTILE


def test_infra_axis_also_capped_below_top_tier():
    """생활 인프라도 천장 동점 때문에 최대 89.6 이다(문서 §8 과 같은 값)."""
    assert percentile_of(100.0, PERCENTILE_LADDERS[AXIS_INFRA]) == pytest.approx(89.6)


def test_ladder_population_recorded_for_every_axis():
    assert set(LADDER_POPULATION) == set(CHARACTER_AXES)
    assert all(v > 0 for v in LADDER_POPULATION.values())


def test_operational_ladder_classifies_without_crashing():
    """주입 없이 기본 사다리로도 돈다(회귀: 사다리 키 오타 방지)."""
    ch = classify_character(four(95.0, 40.0, 90.0, 50.0))
    assert ch.assigned
    assert all(a.percentile is not None for a in ch.axes)


def test_constants_match_the_documented_rule():
    """문서(complex-typing.md §3)가 인용하는 값들. 바뀌면 문서도 같이 바뀌어야 한다."""
    assert DEVIATION_THRESHOLD == 20.0
    assert ALLROUND_MIN_PERCENTILE == 65.0
    assert PRICE_CHEAP_MAX == 0.85
    assert PRICE_PREMIUM_MIN == 1.15
    assert PRICE_MIN_SAMPLE == 5
