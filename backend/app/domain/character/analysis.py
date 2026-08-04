"""단지 유형 판정 — "위닝식 유형 이름". 순수 함수, DB 를 모른다.

설계 근거: docs/02-design/ux/complex-typing.md (실측·탈락 규칙·한계 전부 거기 있다)

이 모듈이 지키는 규칙 (전부 테스트로 고정)
------------------------------------------
1. **유형은 '수준'이 아니라 '모양'이다.** 절대 점수가 높다고 유형을 주지 않는다.
   그 단지 **자신의 축 평균 대비** 두드러진 축으로 정한다. 절대 점수로 정하면
   비싼 동네가 전부 같은 유형이 되고 유형이 곧 가격의 다른 이름이 된다.
2. **축 원점수를 그대로 비교하지 않는다.** 축마다 척도가 달라(학군 평균 86.5 ·
   교통 60.3) 원점수로 비교하면 천장에 눌린 축이 항상 이긴다. 먼저 전국 백분위
   (`ladders.PERCENTILE_LADDERS`)로 바꾼다.
3. **축이 모자라면 판정하지 않는다.** `MIN_AXES` 미만이면 `TYPE_WITHHELD` 다.
   "특징 없음"과 "판정 안 함"은 다른 말이다 — 섞으면 그게 환각이다(G2).
4. **가격 주장은 표본이 있을 때만 한다.** `PRICE_MIN_SAMPLE` 미만이면 배율을
   계산했더라도 문구에 쓰지 않고, 왜 안 썼는지 `notes` 에 남긴다.
5. **한 줄 설명은 값에서 만든다.** 고정 문장을 유형에 매달지 않는다 —
   "대신 비쌉니다"는 배율이 실제로 높을 때만 나온다.
6. **이모지는 여기서 만들지 않는다.** 표시 관례는 프론트 한 곳에만 둔다
   (`lib/tags.ts` 규약과 같은 이유 — api-spec.md §4 "판정이 아니라 값을 준다").
"""
from __future__ import annotations

import statistics
from collections.abc import Mapping

from app.domain.character.ladders import (
    LADDER_AS_OF,
    PERCENTILE_LADDERS,
    percentile_of,
)
from app.domain.character.models import (
    AXIS_LABEL,
    AXIS_TO_TYPE,
    CHARACTER_AXES,
    PRICE_CHEAP,
    PRICE_PREMIUM,
    PRICE_TYPICAL,
    PRICE_UNKNOWN,
    TYPE_ALLROUND,
    TYPE_BALANCED,
    TYPE_LABEL,
    TYPE_VALUE,
    TYPE_WITHHELD,
    WITHHELD_TOO_FEW_AXES,
    AxisReading,
    ComplexCharacter,
    PriceContext,
)

# ---------------------------------------------------------------------------
# 임계값 — 전부 실측으로 고른 값이다. 근거는 complex-typing.md §3.
# ---------------------------------------------------------------------------

#: 유형을 붙이려면 축이 최소 몇 개 있어야 하는가.
#: 4축 중 3축은 좌표 하나로 같이 생기고(학군·교통·생활) 환금만 따로다. 그래서
#: 실질 선택지는 "3축(좌표 있음)" 이거나 "0~1축(좌표 없음)"뿐이다 —
#: 실측 16,462 중 4축 13,644 · 3축 1,917 · 1축 152 · 0축 749.
MIN_AXES = 3

#: **채택된 규칙의 핵심 상수.** 자기 평균 대비 이만큼 위면 "두드러진다"고 말한다.
#:
#: 왜 20 인가 (운영 DB 16,462 단지 전수 판정으로 고른 값):
#:   15 → 최대 유형 22.0% · 평평한 유형 합 13.9%   (유형이 너무 쉽게 붙는다)
#:   20 → 최대 유형 20.6% · 평평한 유형 합 26.2%   ← 채택
#:   25 → 최대 유형 33.5% · 평평한 유형 합 41.2%   (절반 가까이가 '균형형'으로 몰린다)
#: 목표는 "5~8개 유형 · 최대 유형 40% 이하". 20 이 가장 고르게 갈렸다.
#:
#: ⚠️ 이 값은 **연속량을 자르는 선**이라 경계가 존재한다. 최대 편차가 20±3 인 단지가
#:    실측 16.9% 다 — 그 단지들은 임계를 조금만 옮겨도 유형이 바뀐다.
#:    그래서 `ComplexCharacter.borderline` 으로 그 사실을 응답에 남긴다.
DEVIATION_THRESHOLD = 20.0

#: 주 유형이 되려면 그 축이 **전국 중위 이상**이어야 한다.
#:
#: 왜 필요한가 — 편차만 보면 "네 축이 다 나쁜데 그중 덜 나쁜 축"이 유형이 된다.
#: 실측: 이 문턱이 없으면 304개(전체 1.8%)가 **전국 하위 50% 인 축**으로 이름을 얻었다
#: (거래활발형 145 · 학군형 81 · 역세권형 49 · 생활형 29). "이 축이 두드러진다"는
#: 자기 안에서 튄다는 뜻인 동시에 남들과 견줘 밀리지 않는다는 뜻이어야 한다.
#:
#: ⚠️ 이건 **바닥선이지 순위가 아니다.** 백분위가 높을수록 유형이 더 잘 붙는 게 아니라
#:    중위 미만이면 안 붙을 뿐이다. 순위로 쓰면 규칙 1(수준으로 정하지 않는다)이 깨진다.
TYPE_MIN_PERCENTILE = 50.0

#: 경계 표시 폭. 최대 편차가 임계에서 이 안쪽이면 `borderline=True`.
BORDERLINE_MARGIN = 3.0

#: 자기 평균 대비 이만큼 아래면 "약점"으로 문구에 적는다. 유형은 되지 않는다 —
#: 못하는 것으로 이름을 붙이면 유형이 곧 우열이 된다.
WEAK_THRESHOLD = -25.0

#: '올라운드형' 조건: **모든** 축이 이 백분위 이상. `min()` 이라 한 축만 낮아도 탈락한다.
#: 실측 304개(1.8%) — 드물어야 의미가 있는 유형이다.
ALLROUND_MIN_PERCENTILE = 65.0

#: 가격 배율이 이 이하면 '싸다', 이 이상이면 '비싸다'.
#:
#: 근거 — 홀/짝 반쪽 표본으로 잰 배율 자체의 잡음(운영 DB, 25,799 셀):
#:   표본 2~3건 sd 0.057 · 4~5건 0.049 · 6~9건 0.037 · 10~19건 0.027 · 50건+ 0.012
#: 표본 5건에서 잡음 sd ≈ 0.05 이므로 ±15% 는 약 3σ 다. 그보다 좁게 자르면
#: 표본 흔들림을 가격 특성이라고 말하게 된다.
PRICE_CHEAP_MAX = 0.85
PRICE_PREMIUM_MIN = 1.15

#: 가격 주장에 필요한 최소 실거래 건수. 3건으로 "가성비형"이라 하지 않는다.
PRICE_MIN_SAMPLE = 5

#: '최상위권'이라고 부를 백분위 경계. **문구에서만** 쓴다(유형 판정에는 안 쓴다).
#:
#: ⚠️ **축마다 도달 가능한 최대 백분위가 다르다.** 원점수가 천장(100)에 몰려 있어
#:    동점 중간순위가 상한을 만든다(실측):
#:      학군 94.6 · 교통 94.6 · **생활 89.6** · **환금 81.7**
#:    즉 생활·환금 축은 아무리 좋아도 이 문구를 **구조적으로 받지 못한다.**
#:    그래도 경계를 낮추지 않는다 — 환금 축은 회전율 5% 에서 캡되므로
#:    (`scoring.TURNOVER_FULL_SCORE_PCT`) 전체의 36%가 원점수 100 이고,
#:    그 36% 안에서 누가 더 나은지 **우리는 모른다.** 모르는 것을 '최상위'라고
#:    부르지 않는 편이 낫다. 대신 그 축은 "가장 두드러집니다(상위 n%)"를 받는다.
#:    한계는 complex-typing.md §8 에 적어 둔다.
TOP_TIER_PERCENTILE = 90.0

#: ⚠️ **"드문 조합"이라고 쓰지 않는 이유.** 요청 문구 예시는 "학군과 교통이 둘 다
#: 최상위인 **드문** 조합"이었는데, 두 축이 동시에 상위 20% 인 단지가 실측 3,622개
#: (**22.0%**)다. 다섯 중 하나는 드문 게 아니다. 상위 10% 기준이면 0.8%(126개)로
#: 드물지만, 그 경계는 환금 축이 구조적으로 도달할 수 없다(TOP_TIER_PERCENTILE 주석).
#: 그래서 문구에서 '드문'을 뺐다 — 값이 뒷받침하지 않는 낱말은 쓰지 않는다.
BOTH_TOP_TIER_PCT = 22.0

NOTE_LADDER = (
    f"유형은 수도권 전체 단지 분포({LADDER_AS_OF} 측정) 안에서의 상대 위치로 정합니다.")


# ---------------------------------------------------------------------------
# 한국어 조사 — 문구를 값으로 만들면 조사가 값에 따라 달라진다
# ---------------------------------------------------------------------------

def _has_jongseong(word: str) -> bool:
    """마지막 글자에 받침이 있는가. 한글이 아니면 없는 것으로 본다."""
    if not word:
        return False
    ch = word[-1]
    if not ("가" <= ch <= "힣"):
        return False
    return (ord(ch) - 0xAC00) % 28 != 0


def _josa(word: str, with_jong: str, without_jong: str) -> str:
    return f"{word}{with_jong if _has_jongseong(word) else without_jong}"


def _top_share(percentile: float) -> int:
    """백분위 → '상위 n%'. 100 분위는 상위 1% 로 말한다(상위 0% 는 말이 안 된다)."""
    return max(1, int(round(100.0 - percentile)))


def _bottom_share(percentile: float) -> int:
    return max(1, int(round(percentile)))


# ---------------------------------------------------------------------------
# 축 읽기
# ---------------------------------------------------------------------------

def read_axes(
    scores: Mapping[str, float | None],
    ladders: Mapping[str, tuple[float, ...]] | None = None,
) -> tuple[AxisReading, ...]:
    """축 원점수 → 백분위 + 자기 평균 대비 편차.

    ⚠️ **없는 축을 0 으로 채우지 않는다.** `score=None` 인 축은 평균 계산에서
       빠지고 `deviation` 도 None 이다. 0 으로 채우면 "모른다"가 "나쁘다"가 된다
       (viz-research §3-④ 가 그림에서 막은 것과 같은 결함의 숫자판).

    `ladders` 를 주입할 수 있게 둔 이유는 둘이다: ① 테스트가 손으로 계산할 수 있는
    사다리를 쓸 수 있어야 하고(101개 실측값을 손으로 검산할 수는 없다),
    ② 사다리를 재측정할 때 코드를 고치지 않고 갈아끼울 수 있어야 한다.
    기본값은 언제나 운영 실측 사다리다.
    """
    table = PERCENTILE_LADDERS if ladders is None else ladders
    present: dict[str, float] = {}
    for axis in CHARACTER_AXES:
        raw = scores.get(axis)
        if raw is None:
            continue
        ladder = table.get(axis)
        if ladder is None:          # 사다리가 없는 축은 백분위를 만들 수 없다
            continue
        present[axis] = percentile_of(float(raw), ladder)

    mean = statistics.mean(present.values()) if present else None
    return tuple(
        AxisReading(
            axis=axis,
            score=(None if scores.get(axis) is None else float(scores[axis])),
            percentile=present.get(axis),
            deviation=(None if axis not in present or mean is None
                       else round(present[axis] - mean, 1)),
        )
        for axis in CHARACTER_AXES
    )


def price_status(price: PriceContext | None) -> str:
    """가격 배율 → cheap | typical | premium | unknown. 표본이 얇으면 unknown."""
    if (price is None or price.ratio is None or price.ratio <= 0
            or price.sample_size < PRICE_MIN_SAMPLE):
        return PRICE_UNKNOWN
    if price.ratio <= PRICE_CHEAP_MAX:
        return PRICE_CHEAP
    if price.ratio >= PRICE_PREMIUM_MIN:
        return PRICE_PREMIUM
    return PRICE_TYPICAL


def _gap_pct(price: PriceContext | None) -> float | None:
    if price is None or price.ratio is None or price.ratio <= 0:
        return None
    return round((price.ratio - 1.0) * 100, 1)


# ---------------------------------------------------------------------------
# 한 줄 설명 — 전부 값에서 만든다
# ---------------------------------------------------------------------------

def _price_clause(status: str, gap: float | None, scope: str) -> str:
    """가격 조각. `typical`·`unknown` 이면 **아무 말도 하지 않는다.**"""
    if gap is None:
        return ""
    if status == PRICE_PREMIUM:
        return f" 대신 {scope} 단지들의 실거래 중위보다 ㎡당 {abs(gap):.0f}% 비쌉니다."
    if status == PRICE_CHEAP:
        return f" {scope} 단지들의 실거래 중위보다 ㎡당 {abs(gap):.0f}% 낮습니다."
    return ""


def _weak_clause(weak: AxisReading | None) -> str:
    if weak is None or weak.percentile is None:
        return ""
    return (f" 다만 {_josa(weak.label, '은', '는')} "
            f"하위 {_bottom_share(weak.percentile)}%입니다.")


def _strength_clause(top: AxisReading, second: AxisReading | None) -> str:
    top_share = _top_share(top.percentile or 0.0)
    if second is None:
        if (top.percentile or 0.0) >= TOP_TIER_PERCENTILE:
            return f"{_josa(top.label, '이', '가')} 최상위권입니다(상위 {top_share}%)."
        return (f"{_josa(top.label, '이', '가')} 이 단지에서 가장 두드러집니다"
                f"(상위 {top_share}%).")
    snd_share = _top_share(second.percentile or 0.0)
    both_top = ((top.percentile or 0.0) >= TOP_TIER_PERCENTILE
                and (second.percentile or 0.0) >= TOP_TIER_PERCENTILE)
    joined = f"{_josa(top.label, '과', '와')} {second.label}"
    tail = f"(상위 {top_share}% · 상위 {snd_share}%)"
    if both_top:
        # '드문'은 수사가 아니라 실측이다 — RARE_COMBO_PCT 참조.
        return f"{joined} 둘 다 최상위인 조합입니다{tail}."
    return f"{joined} 둘 다 두드러집니다{tail}."


def _count_word(n: int) -> str:
    return {2: "두", 3: "세", 4: "네"}.get(n, f"{n}개")


def _flat_level_clause(used: list[AxisReading]) -> str:
    """모양이 평평할 때의 **수준** 문장.

    ⚠️ 평평하다는 말만 하면 "네 축이 다 상위권"과 "네 축이 다 하위권"이 같은 문장이
       된다. 두 단지는 전혀 다른 곳인데 화면에 같은 말이 뜬다 — 그건 유형이 아니라
       가림막이다. 그래서 평평한 유형은 반드시 **어디에 평평한지**를 함께 말한다.
       (범위를 "상위 33%~상위 49%"처럼 쓰지 않는 이유: 중위를 걸치면 '상위 93%'
        같은 읽기 어려운 말이 나온다. 중위 기준으로 갈라 말한다.)
    """
    ranked = sorted((a for a in used if a.percentile is not None),
                    key=lambda a: (a.percentile, a.axis))
    lowest, highest = ranked[0], ranked[-1]
    pcts = [a.percentile for a in ranked]
    median = statistics.median(pcts)
    word = _count_word(len(pcts))

    if pcts[0] >= 50.0:
        return (f"두드러지는 축이 없습니다 — {word} 축이 모두 전국 중위 이상이지만 "
                f"특별히 튀는 축은 없습니다.")
    if pcts[-1] < 50.0:
        return (f"{word} 축이 모두 전국 중위 아래입니다"
                f"(가장 높은 축도 하위 {_bottom_share(pcts[-1])}%).")
    # 중위를 걸친다. **중앙값**으로 어느 쪽인지 정하고 반대쪽 끝을 이름으로 짚는다 —
    # "중위 근처"라고만 쓰면 세 축이 상위권이고 한 축만 낮은 단지도 같은 문장이 된다.
    if median >= 50.0:
        return (f"두드러지는 축이 없습니다 — {word} 축이 대체로 전국 중위 이상이고, "
                f"가장 낮은 {lowest.label}만 하위 {_bottom_share(pcts[0])}%입니다.")
    return (f"두드러지는 축이 없습니다 — {word} 축이 대체로 전국 중위 아래이고, "
            f"가장 높은 {highest.label}만 상위 {_top_share(pcts[-1])}%입니다.")


# ---------------------------------------------------------------------------
# 본체
# ---------------------------------------------------------------------------

def classify_character(
    scores: Mapping[str, float | None],
    price: PriceContext | None = None,
    *,
    ladders: Mapping[str, tuple[float, ...]] | None = None,
) -> ComplexCharacter:
    """축 원점수(+가격 배율) → 단지 유형 하나.

    `scores` 는 `CHARACTER_AXES` 를 키로 하는 0~100 원점수 매핑이다. 값이 없으면
    키를 빼거나 None 을 준다 — **0 을 주지 말 것.** 0 은 "쟀는데 최하"라는 뜻이라
    (예: 역이 1.5km 밖) 미확보와 다르게 다뤄진다.
    """
    axes = read_axes(scores, ladders)
    used = [a for a in axes if a.percentile is not None]
    notes: list[str] = []

    # ① 축이 모자라면 판정하지 않는다.
    if len(used) < MIN_AXES:
        missing = [AXIS_LABEL[a.axis] for a in axes if a.percentile is None]
        return ComplexCharacter(
            type_code=TYPE_WITHHELD,
            label=TYPE_LABEL[TYPE_WITHHELD],
            headline=(
                f"측정된 축이 {len(used)}개뿐이라 유형을 붙이지 않았습니다"
                f"(미확보: {', '.join(missing)}). 없는 근거로 이름을 붙이지 않습니다."),
            axes=axes,
            withheld_reason=WITHHELD_TOO_FEW_AXES,
            notes=(NOTE_LADDER,),
            axes_used=len(used),
        )

    if len(used) < len(CHARACTER_AXES):
        missing = [AXIS_LABEL[a.axis] for a in axes if a.percentile is None]
        notes.append(
            f"{', '.join(missing)} 축이 미확보라 나머지 {len(used)}개 축만으로 "
            f"판정했습니다 — 그 축이 채워지면 유형이 바뀔 수 있습니다.")

    ranked = sorted(used, key=lambda a: (-(a.deviation or 0.0), a.axis))
    top, second = ranked[0], ranked[1]
    weak = ranked[-1] if (ranked[-1].deviation or 0.0) <= WEAK_THRESHOLD else None

    status = price_status(price)
    gap = _gap_pct(price)
    scope = price.scope_label if price else "같은 시군구·같은 면적대"
    if status == PRICE_UNKNOWN:
        n = price.sample_size if price else 0
        notes.append(
            f"실거래 표본이 {n}건뿐이라 가격 비교는 하지 않았습니다"
            f"(최소 {PRICE_MIN_SAMPLE}건)." if price and price.ratio is not None
            else "같은 면적대 실거래 기준선이 없어 가격 비교는 하지 않았습니다.")
    elif price is not None and price.reference_ym:
        notes.append(f"가격 비교는 {price.reference_ym} 시점으로 환산한 실거래 기준입니다.")

    top_dev = top.deviation or 0.0
    margin = round(top_dev - DEVIATION_THRESHOLD, 1)
    borderline = abs(margin) <= BORDERLINE_MARGIN

    def _stands_out(a: AxisReading) -> bool:
        """두드러짐 = 자기 안에서 튄다 **그리고** 전국 중위 이상이다(둘 다)."""
        return ((a.deviation or 0.0) >= DEVIATION_THRESHOLD
                and (a.percentile or 0.0) >= TYPE_MIN_PERCENTILE)

    # ② 두드러진 축이 있으면 그 축이 유형이다.
    if _stands_out(top):
        sub = second if _stands_out(second) else None
        type_code = AXIS_TO_TYPE[top.axis]
        sub_code = AXIS_TO_TYPE[sub.axis] if sub else None
        headline = (_strength_clause(top, sub)
                    + _weak_clause(weak if (sub is None or weak is not sub) else None)
                    + _price_clause(status, gap, scope))
        return ComplexCharacter(
            type_code=type_code, label=TYPE_LABEL[type_code],
            sub_type_code=sub_code,
            sub_label=TYPE_LABEL[sub_code] if sub_code else None,
            headline=headline, axes=axes,
            weak_axis=weak.axis if weak else None,
            margin=margin, borderline=borderline,
            price_status=status, price_gap_pct=gap,
            notes=tuple([NOTE_LADDER, *notes]), axes_used=len(used),
        )

    # ③ 모양이 평평하다. 여기서부터는 '무엇이 두드러지나'가 아니라 '어떤 평평함인가'다.
    lowest = min(a.percentile or 0.0 for a in used)
    if lowest >= ALLROUND_MIN_PERCENTILE:
        headline = (f"측정한 {_count_word(len(used))} 축이 모두 상위권입니다"
                    f"(가장 낮은 축도 상위 {_top_share(lowest)}%)."
                    + _price_clause(status, gap, scope))
        return ComplexCharacter(
            type_code=TYPE_ALLROUND, label=TYPE_LABEL[TYPE_ALLROUND],
            headline=headline, axes=axes, margin=margin, borderline=borderline,
            price_status=status, price_gap_pct=gap,
            notes=tuple([NOTE_LADDER, *notes]), axes_used=len(used),
        )

    if status == PRICE_CHEAP:
        headline = (
            _flat_level_clause(used)
            + f" 다만 {scope} 단지들의 실거래 중위보다 ㎡당 "
              f"{abs(gap or 0):.0f}% 낮아, 같은 예산으로 면적을 더 갑니다.")
        return ComplexCharacter(
            type_code=TYPE_VALUE, label=TYPE_LABEL[TYPE_VALUE],
            headline=headline, axes=axes,
            weak_axis=weak.axis if weak else None,
            margin=margin, borderline=borderline,
            price_status=status, price_gap_pct=gap,
            notes=tuple([NOTE_LADDER, *notes]), axes_used=len(used),
        )

    headline = _flat_level_clause(used) + _price_clause(status, gap, scope)
    return ComplexCharacter(
        type_code=TYPE_BALANCED, label=TYPE_LABEL[TYPE_BALANCED],
        headline=headline, axes=axes,
        weak_axis=weak.axis if weak else None,
        margin=margin, borderline=borderline,
        price_status=status, price_gap_pct=gap,
        notes=tuple([NOTE_LADDER, *notes]), axes_used=len(used),
    )
