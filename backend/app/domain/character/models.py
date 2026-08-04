"""단지 성격(유형)의 자료형. 순수 데이터 — 계산은 `analysis.py` 에 있다."""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 축 — `ladders.PERCENTILE_LADDERS` 의 키와 **같은 문자열**이어야 한다.
# ---------------------------------------------------------------------------
AXIS_SCHOOL = "school"
AXIS_TRANSIT = "transit"
AXIS_INFRA = "infra"
AXIS_LIQUIDITY = "liquidity"

#: 응답·문서·테스트가 같은 순서를 본다. `scoring.WEIGHT_AXES` 와 같은 규약.
CHARACTER_AXES: tuple[str, ...] = (AXIS_SCHOOL, AXIS_TRANSIT, AXIS_INFRA, AXIS_LIQUIDITY)

#: 화면 문구용 축 이름.
AXIS_LABEL: dict[str, str] = {
    AXIS_SCHOOL: "학군",
    AXIS_TRANSIT: "교통",
    AXIS_INFRA: "생활 인프라",
    AXIS_LIQUIDITY: "거래 회전",
}

# ---------------------------------------------------------------------------
# 유형 코드
# ---------------------------------------------------------------------------
TYPE_SCHOOL = "school"
TYPE_TRANSIT = "transit"
TYPE_INFRA = "infra"
TYPE_LIQUIDITY = "liquidity"
TYPE_ALLROUND = "allround"
TYPE_VALUE = "value"
TYPE_BALANCED = "balanced"
#: 유형을 붙이지 않는다. **"특징 없음"이 아니라 "판정하지 않았다"** 이다.
TYPE_WITHHELD = "withheld"

TYPE_LABEL: dict[str, str] = {
    TYPE_SCHOOL: "학군형",
    TYPE_TRANSIT: "역세권형",
    TYPE_INFRA: "생활형",
    TYPE_LIQUIDITY: "거래활발형",
    TYPE_ALLROUND: "올라운드형",
    TYPE_VALUE: "가성비형",
    TYPE_BALANCED: "균형형",
    TYPE_WITHHELD: "유형 판정 보류",
}

#: 두드러진 축 → 유형 코드. 축과 유형을 **다른 이름**으로 둔 이유는,
#: `infra` 축이 두드러지면 유형은 `infra`(생활형)지만 축 이름은 '생활 인프라'라
#: 화면에서 두 낱말이 섞이면 안 되기 때문이다.
AXIS_TO_TYPE: dict[str, str] = {
    AXIS_SCHOOL: TYPE_SCHOOL,
    AXIS_TRANSIT: TYPE_TRANSIT,
    AXIS_INFRA: TYPE_INFRA,
    AXIS_LIQUIDITY: TYPE_LIQUIDITY,
}

# ---------------------------------------------------------------------------
# 판정 보류 사유 코드 (문구 고정 — 테스트·UI 가 같은 문자열을 본다)
# ---------------------------------------------------------------------------
WITHHELD_TOO_FEW_AXES = "too_few_axes"

#: 가격 판정 상태.
PRICE_CHEAP = "cheap"
PRICE_TYPICAL = "typical"
PRICE_PREMIUM = "premium"
PRICE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class AxisReading:
    """축 하나의 읽은 값.

    `score` 는 기존 도메인 함수가 내놓은 원점수(0~100), `percentile` 은 그 값을
    전국 사다리에 올린 위치, `deviation` 은 **이 단지 자신의 축 평균 대비** 편차다.
    유형은 오직 `deviation` 으로 정한다 — `percentile`(수준)로 정하지 않는다.
    """

    axis: str
    score: float | None = None
    percentile: float | None = None
    deviation: float | None = None

    @property
    def label(self) -> str:
        return AXIS_LABEL.get(self.axis, self.axis)

    @property
    def available(self) -> bool:
        return self.score is not None


@dataclass(frozen=True)
class PriceContext:
    """같은 시군구·같은 면적대 실거래 중위 대비 ₩/㎡ 배율.

    ⚠️ **호가가 아니라 실거래**다. 그리고 **면적대 안에서** 비교한 값이다 —
       면적을 섞으면 큰 평형이 많은 단지가 통째로 비싸 보인다(실측: 무통제 시
       동별 편차가 13.3% → 면적 통제 후 5.4%, viz-research §1-E).
    """

    #: 단지 중위 ₩/㎡ ÷ (같은 시군구·같은 면적대) 단지 중위들의 중위. 1.0 이 기준.
    ratio: float | None = None
    #: 배율을 만든 실거래 건수(시점 보정에 성공한 것만).
    sample_size: int = 0
    #: "강남구 60~85㎡" 처럼 **무엇과 비교했는지**. 문구에 그대로 나간다.
    scope_label: str = "같은 시군구·같은 면적대"
    #: 시점 환산 기준월(`timeadjust.MarketIndex.reference_ym`). 없으면 미보정.
    reference_ym: str | None = None


@dataclass(frozen=True)
class ComplexCharacter:
    """단지 하나의 유형 판정 결과."""

    type_code: str
    #: 화면에 뜨는 이름. 판정 보류면 "유형 판정 보류".
    label: str
    #: 두 번째로 두드러진 축의 유형(있을 때만). 예: 학군형 · 역세권형
    sub_type_code: str | None = None
    sub_label: str | None = None
    #: 값에서 생성한 한 줄 설명. **고정 문장이 아니다.**
    headline: str = ""
    axes: tuple[AxisReading, ...] = ()
    #: 자기 평균 대비 크게 낮은 축(있으면). 유형이 아니라 설명 재료다.
    weak_axis: str | None = None
    #: 최대 편차 − 임계. 0 에 가까울수록 경계선이다.
    margin: float | None = None
    borderline: bool = False
    price_status: str = PRICE_UNKNOWN
    #: 배율이 1.0 에서 몇 % 떨어져 있는가(양수=비싸다). 판정 못 하면 None.
    price_gap_pct: float | None = None
    #: 판정 보류 사유 코드. 유형이 있으면 None.
    withheld_reason: str | None = None
    #: 사람이 읽는 단서들(미확보 축, 표본 부족 등). 삼키지 않는다.
    notes: tuple[str, ...] = field(default_factory=tuple)
    #: 판정에 쓴 축 수 / 전체 축 수.
    axes_used: int = 0
    axes_total: int = len(CHARACTER_AXES)

    @property
    def assigned(self) -> bool:
        return self.type_code != TYPE_WITHHELD

    @property
    def labels(self) -> tuple[str, ...]:
        """화면 태그 목록. 부 유형이 있으면 두 개."""
        if not self.assigned:
            return ()
        return (self.label, self.sub_label) if self.sub_label else (self.label,)
