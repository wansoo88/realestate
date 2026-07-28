"""'학군지' 태그 판정 게이트 — **성취도 근거가 없으면 태그를 붙이지 않는다.**

사용자 결정(2026-07-28)
-----------------------
    "학업성취도까지 확보한 뒤 '학군지' 태그를 붙인다 — 배정 초등학교 거리만으로
     '학군지'라 부르면 과장이다."

그래서 이 모듈은 **거리를 입력으로 받지 않는다.** `assess_school_district_tag()` 의
서명에 거리 인자가 없다는 것이 가장 강한 방어선이다 — 없는 인자는 실수로 못 쓴다.
(회귀 테스트가 서명을 고정한다: `test_school_quality.py`)

실측 결론 (2026-07-28) — 붙일 수 없다. 셋이 **각각 독립적으로** 막는다
----------------------------------------------------------------------
① **초등 학업성취도 수치는 존재하지 않는다.**
   학교알리미(schoolinfo.go.kr) 지역별 공시정보에서 학교급별 공시항목 트리를 실호출로
   받아 확인했다(`HG_JONGRYU_GB` = 02/03/04).
     - 초등학교 렌더 항목 45종 중 「학업성취사항」 분류에 들어 있는 것은
       **「교과별(학년별) 교수ㆍ학습 및 평가계획에 관한 사항」(코드 43) 하나뿐**이다.
       이건 **평가 계획 문서**지 성취 수치가 아니다.
     - 「교과별 학업성취 사항」(코드 44)은 초등에 렌더되지 않는다. 원천이 밝힌
       공시기관도 "**중, 고**"다.
     - 「국가학업성취도 평가에 관한 사항」은 항목 코드표(56종)에 이름만 남아 있고
       **초·중·고 어느 급에도 렌더되지 않는다** — 학교별 공시가 끝난 항목이다.
   → 초등 '학군지' 태그는 **원천 부재**로 불가능하다. 이건 우리 수집의 한계가 아니라
     대한민국에 그 숫자가 학교 단위로 공개돼 있지 않다는 뜻이다.

② **중·고 「교과별 학업성취 사항」은 학교 간 비교 근거가 아니다.**
   원천(학교알리미)이 직접 그렇게 적어 놓았다. 항목 설명 원문:

       "●공시기관 : 중, 고
        ●공시내용 : **단위학교별 평가계획에 의거하여** 실시한 지필평가와 수행평가를
                    합산한 학기말 성적 결과
        【평균】: 학기말 성적의 학년별·과목별 평균
        【성취도별 분포비율】: 학기말 성적의 학년별·과목별 성취도별 분포비율"

   즉 **각 학교가 자기 시험을 자기가 내고 자기가 채점한 결과**다. 시험을 쉽게 내면
   평균과 A 비율이 올라간다. "A 비율 85%인 중학교가 70%인 중학교보다 학력이 높다"는
   문장은 데이터가 뒷받침하지 않으며, 오히려 변별을 위해 어렵게 내는 학교가 낮게
   나오는 역전이 가능하다. **숫자가 있다는 것과 비교할 수 있다는 것은 다르다.**
   거리로 판정하는 것보다 이쪽이 더 나쁠 수 있다 — 숫자라서 객관적으로 보이기 때문이다.

   덧붙여 기계 판독 경로도 없다: 학교알리미 OpenAPI 제공목록 35종
   (`/download/OpenAPI_Output.xlsx` 시트명 실측)과 '공개용 데이터' 35종 어디에도
   코드 44 가 없다. 남는 길은 학교별 웹페이지 스크래핑이고 사이트에는 캡차가 있다.

③ **확보하더라도 학교ID 로 붙일 수 없다.**
   우리 `poi(category='school')` 의 식별자는 한국교육시설안전원 학교ID(`kesi:B000008126`)다.
   원천 CSV(15159184, 18컬럼) 전체를 확인했고 **표준학교코드(NEIS `SD_SCHUL_CODE`)나
   정보공시 학교코드가 없다.** 학교알리미/NEIS 쪽 성취도를 가져와도 이름·주소
   퍼지매칭 말고는 붙일 방법이 없는데, 이 저장소는 배정처럼 **단정형 주장에는
   퍼지매칭을 끼우지 않는다**(`config/sources.yaml` school_info notes, `reb.py`).

임계값을 정하지 않는 이유
-------------------------
'상위 몇 %'는 **모집단 분포에서 나오는 수**다. 비교 가능한 모집단이 없으면 임계값도
없다. 그래서 `TOP_PERCENTILE_THRESHOLD` 는 `None` 이고, 이 게이트는 임계값이 없으면
판정하지 않는다. 여기에 20 이나 10 을 적어 두는 것은 근거가 생긴 척하는 것이다.

이 모듈이 추천 파이프라인에 배선돼 있지 않은 이유
--------------------------------------------------
붙일 태그가 없기 때문이다. 배선은 `COMPARABLE_ACHIEVEMENT_SOURCES` 가 비지 않는 날
`app/api/routes.py` 의 단지 응답에 필드를 싣는 것으로 시작한다(그 전에는 실을 값이 없다).
지금 이 모듈의 역할은 **정의를 한 곳에 두고, 거리로 우회하는 길을 막는 것**이다.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

__all__ = [
    "COMPARABLE_ACHIEVEMENT_SOURCES", "NON_COMPARABLE_ACHIEVEMENT_SOURCES",
    "TAG_DEFINITION", "TOP_PERCENTILE_THRESHOLD", "AchievementFact",
    "SchoolDistrictTag", "assess_school_district_tag",
]

#: 화면에 그대로 나갈 '학군지'의 정의. 태그를 붙이는 날 **이 문장이 근거로 함께 나간다.**
#: 정의를 화면에 못 적는 태그는 붙이지 않는다(사용자 지시).
TAG_DEFINITION = (
    "학교 간 비교가 가능한 공통 척도의 학업성취도에서, 배정(또는 후보) 학교가 "
    "같은 급 모집단 상위 X% 에 드는 단지"
)

#: **학교 간 비교가 가능한** 성취도 출처. 지금은 비어 있다 — 그런 출처를 못 찾았다.
#: 비어 있는 게 이 모듈의 결론이고, 채우는 것이 태그를 켜는 유일한 방법이다.
#: 채울 때 필요한 조건은 셋이다: (a) 전 학교 공통 척도일 것, (b) 학교 단위로 공개될 것,
#: (c) 우리 학교ID(`kesi:B…`)와 **정확일치로** 이어질 것.
COMPARABLE_ACHIEVEMENT_SOURCES: frozenset[str] = frozenset()

#: 숫자는 있지만 **학교 간 비교 근거가 아닌** 출처. 명시적으로 거절하기 위한 목록이다.
#: 빈 허용목록만 두면 "출처 미등록"이라는 애매한 사유가 나가는데, 여기 적힌 출처는
#: 애매한 게 아니라 **쓰면 안 되는 것**이라 사유를 따로 낸다(모듈 docstring ②).
NON_COMPARABLE_ACHIEVEMENT_SOURCES: frozenset[str] = frozenset({
    "학교알리미 교과별 학업성취 사항",
    "schoolinfo:44",
})

#: 상위 몇 % 를 '학군지'로 볼 것인가. **모집단이 없으므로 정할 수 없다**(docstring).
TOP_PERCENTILE_THRESHOLD: float | None = None

#: 판정 사유 코드. 문자열은 화면 문구, 코드는 로그·테스트용이다.
REASON_NO_FACT = "no_achievement_fact"
REASON_NO_VALUE = "no_achievement_value"
REASON_NO_PROVENANCE = "no_source_or_as_of"
REASON_SOURCE_NOT_COMPARABLE = "source_not_comparable"
REASON_SOURCE_UNKNOWN = "source_not_allowlisted"
REASON_NO_SCHOOL_ID = "no_school_id"
REASON_NO_PERCENTILE = "no_percentile"
REASON_NO_THRESHOLD = "no_threshold"


@dataclass(frozen=True)
class AchievementFact:
    """학교 하나의 학업성취 근거.

    ⚠️ **거리 필드가 없다.** 이 자료구조에 통학거리를 넣지 말 것 — 넣는 순간
       "가까우니까 학군지" 로 가는 길이 열린다(사용자가 명시적으로 거부한 방식).
    """

    #: 우리 `poi.attrs['school_id']` (예: 'B000008126'). 이게 없으면 어느 학교의
    #: 성취도인지 단정할 수 없다 — 이름 매칭은 동명 학교에서 틀린다.
    school_id: str | None
    level: str                       # 초등학교 | 중학교 | 고등학교
    #: 성취도 값. 단위·의미는 `source` 가 정한다(그래서 source 없이는 못 쓴다).
    value: float | None = None
    source: str | None = None
    #: 기준연도. **성취도는 해마다 바뀐다** — 연도 없는 수치는 근거가 아니다.
    as_of: str | None = None
    #: 같은 급 모집단 안에서의 백분위(0~100, 높을수록 상위). 임계값 비교의 유일한 입력.
    percentile: float | None = None
    #: 백분위를 계산한 모집단의 이름. 화면에 "무엇 중 상위 X%인지"를 적기 위해 필요하다.
    population: str | None = None


@dataclass(frozen=True)
class SchoolDistrictTag:
    """'학군지' 태그 판정 결과.

    `verdict` 는 셋이다 — `yes` / `no` / `unavailable`.
    ⚠️ `unavailable` 을 `no` 로 접지 않는다. "학군지가 아니다"와 "판정할 근거가 없다"는
       다른 말이고, 후자를 전자로 적으면 화면이 거짓 단언을 하게 된다
       (프론트 `tags.ts` 의 unknown 원칙과 같다).
    """

    verdict: str
    reason_code: str
    reason: str
    #: 태그를 붙였을 때만 채운다 — 정의 없이 이름만 나가는 배지를 만들지 않기 위해서다.
    definition: str | None = None
    evidence: tuple[dict, ...] = field(default_factory=tuple)

    @property
    def tagged(self) -> bool:
        return self.verdict == "yes"


def _reject(code: str, message: str) -> SchoolDistrictTag:
    return SchoolDistrictTag(verdict="unavailable", reason_code=code, reason=message)


def _screen(fact: AchievementFact) -> SchoolDistrictTag | None:
    """근거 하나를 검사한다. 통과하면 None, 아니면 거절 사유."""
    if fact.value is None:
        return _reject(
            REASON_NO_VALUE,
            f"{fact.level} 학업성취도 수치 미확보 — 통학거리로 대체하지 않음")
    if not fact.source or not fact.as_of:
        # 기존 `analysis.assess_school` 과 같은 규칙이다(원칙 5). 여기서 한 번 더 막는
        # 이유는 태그가 리포트보다 **단정적**이기 때문이다 — 배지에는 각주를 못 단다.
        return _reject(
            REASON_NO_PROVENANCE,
            f"{fact.level} 학업성취도의 출처 또는 기준연도 없음 — 수치 미사용")
    if fact.source in NON_COMPARABLE_ACHIEVEMENT_SOURCES:
        return _reject(
            REASON_SOURCE_NOT_COMPARABLE,
            f"'{fact.source}' 은 단위학교가 자체 출제·채점한 결과라 학교 간 비교 "
            f"근거가 아님 — 학군지 판정에 쓰지 않음")
    if fact.source not in COMPARABLE_ACHIEVEMENT_SOURCES:
        return _reject(
            REASON_SOURCE_UNKNOWN,
            f"'{fact.source}' 은 학교 간 비교 가능 출처로 확인되지 않음 — 판정 보류")
    if not fact.school_id:
        return _reject(
            REASON_NO_SCHOOL_ID,
            f"{fact.level} 성취도를 학교ID 로 잇지 못함 — 이름 매칭으로 단정하지 않음")
    if fact.percentile is None:
        return _reject(
            REASON_NO_PERCENTILE,
            f"{fact.level} 성취도의 모집단 내 백분위 미상 — '상위 X%' 를 말할 수 없음")
    return None


def assess_school_district_tag(
    facts: Sequence[AchievementFact] = (),
) -> SchoolDistrictTag:
    """'학군지' 태그를 붙일 수 있는지 판정한다.

    ⚠️ **인자에 거리가 없다.** 이 서명이 곧 규칙이다 — 거리로는 이 함수를 통과할 수
       없다. (`test_school_quality.py` 가 서명을 고정한다.)

    판정은 근거가 **하나라도** 요건을 다 갖추면 그 근거로 한다. 급이 여럿일 때
    가장 강한 근거를 쓰는 것이 맞고, 요건 미달 근거를 섞어 평균 내지 않는다.
    """
    if not facts:
        return _reject(REASON_NO_FACT, "학업성취도 근거 없음 — 학군지 판정 불가")

    rejections: list[SchoolDistrictTag] = []
    usable: list[AchievementFact] = []
    for fact in facts:
        rejection = _screen(fact)
        if rejection is None:
            usable.append(fact)
        else:
            rejections.append(rejection)

    if not usable:
        # 첫 사유를 대표로 낸다. 근거가 여럿이면 사유도 여럿이지만, 배지 옆에 붙는
        # 문장은 하나여야 읽힌다. 나머지는 로그로 남는다(호출부 책임).
        return rejections[0]

    if TOP_PERCENTILE_THRESHOLD is None:
        # ⚠️ 이 검사는 **근거 검사 뒤**에 온다. 순서가 뜻을 바꾸기 때문이다 —
        #    임계값이 없는 것은 비교 가능한 모집단이 없어서이고, 그건 근거가 없다는
        #    사실의 **결과**다. 앞에 두면 모든 단지가 "임계값 미정"이라는 파생 사유만
        #    받게 되고, 정작 원인("성취도 근거 없음")이 화면에서 사라진다.
        return _reject(
            REASON_NO_THRESHOLD,
            "'학군지' 임계값 미정 — 비교 가능한 모집단이 없어 상위 X% 를 정의할 수 없음")

    best = max(usable, key=lambda f: f.percentile or 0.0)
    passed = (best.percentile or 0.0) >= 100.0 - TOP_PERCENTILE_THRESHOLD
    evidence = tuple(
        {
            "claim": f"{f.level} 학업성취도 상위 {round(100.0 - (f.percentile or 0.0), 1)}%",
            "value": f.value,
            "percentile": f.percentile,
            "population": f.population,
            "school_id": f.school_id,
            "source": f.source,
            "as_of": f.as_of,
        }
        for f in usable
    )
    return SchoolDistrictTag(
        verdict="yes" if passed else "no",
        reason_code="assessed",
        reason=(f"{best.population or '모집단'} 상위 "
                f"{round(100.0 - (best.percentile or 0.0), 1)}% "
                f"(기준연도 {best.as_of})"),
        definition=TAG_DEFINITION,
        evidence=evidence,
    )
