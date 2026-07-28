"""'학군지' 태그 게이트 회귀 테스트.

이 파일이 지키는 것은 기능이 아니라 **약속**이다. 사용자 결정(2026-07-28):

    "학업성취도까지 확보한 뒤 '학군지' 태그를 붙인다 — 배정 초등학교 거리만으로
     '학군지'라 부르면 과장이다."

그래서 아래 테스트들은 "동작한다"가 아니라 **"이 우회로가 막혀 있다"** 를 고정한다.
각 테스트에는 그 가드를 깨뜨렸을 때 무엇이 잡히는지 적어 둔다(변이 테스트 대상).
"""
from __future__ import annotations

import inspect

import pytest

from app.domain.location import school_quality as sq
from app.domain.location.school_quality import (
    AchievementFact,
    assess_school_district_tag,
)

# ---------------------------------------------------------------------------
# 테스트 격리 — 이 파일은 **모듈 전역 상수**를 읽고 monkeypatch 로 임시 변경한다.
#
# 그래서 두 가지 사고에 노출된다:
#   ① 다른 테스트가 같은 상수를 바꿔 놓고 되돌리지 않으면(전역 상태 공유)
#      여기서만 **간헐적으로** 실패한다 — 원인이 이 파일에 없어 추적이 아주 어렵다.
#   ② 이 파일 자신이 실패해도 "왜 값이 다른가"가 assert 출력에 안 남는다.
# 아래 tripwire 가 **테스트 시작 시점**에 오염을 잡아 범인을 문장으로 말한다.
# (실측: 전체 실행 25회 · 무작위 순서 6회 · 모듈 쌍 37조합에서 오염은 관측되지 않았다.
#  그래도 남겨 둔다 — 다음에 생기면 한 줄로 진단되게 하는 것이 이 fixture 의 값어치다.)
# ---------------------------------------------------------------------------

#: 이 파일이 전제하는 모듈 상태. 변경은 **의도적 결정**이어야 하고, 그때는
#: 아래 테스트들이 정직하게 실패해야 한다(조용히 통과시키지 않는다).
PRISTINE_THRESHOLD = None
PRISTINE_COMPARABLE: frozenset[str] = frozenset()
#: 거절 목록. **collection 시점의 모듈 값을 그대로 쓰지 않고 여기 박아 둔다** —
#: 모듈 값이 비면 `parametrize` 가 **케이스 0개**가 되어 가드가 소리 없이 사라지기 때문이다
#: (이 저장소가 가장 경계하는 형태의 실패). 목록이 어긋나면 아래 테스트가 잡는다.
NON_COMPARABLE_EXPECTED = frozenset({
    "학교알리미 교과별 학업성취 사항",
    "schoolinfo:44",
})


@pytest.fixture(autouse=True)
def _no_leaked_module_state():
    """테스트가 **시작할 때** 모듈 상수가 원래 값인지 확인한다.

    monkeypatch 는 자기 테스트의 변경만 되돌린다. 다른 경로(모듈 임포트 부작용·
    직접 대입·되돌리지 않은 patch)로 들어온 오염은 여기서 잡히고, 그때 실패 메시지가
    **어느 상수가 어떻게 바뀌었는지** 말한다 — 'AssertionError: assert False' 로
    끝나면 다음 사람이 또 몇 시간을 태운다.
    """
    assert sq.TOP_PERCENTILE_THRESHOLD == PRISTINE_THRESHOLD, (
        f"테스트 시작 시점에 TOP_PERCENTILE_THRESHOLD 가 "
        f"{sq.TOP_PERCENTILE_THRESHOLD!r} 입니다(기대 {PRISTINE_THRESHOLD!r}). "
        "원인은 둘 중 하나입니다 — (a) 다른 테스트가 monkeypatch 없이 대입해 누수됐다, "
        "(b) 모듈 상수를 의도적으로 바꿨다. (b)라면 이 파일의 PRISTINE_* 도 함께 갱신하세요.")
    assert sq.COMPARABLE_ACHIEVEMENT_SOURCES == PRISTINE_COMPARABLE, (
        f"테스트 시작 시점에 COMPARABLE_ACHIEVEMENT_SOURCES 가 "
        f"{sq.COMPARABLE_ACHIEVEMENT_SOURCES!r} 입니다(기대 비어 있음). "
        "다른 테스트의 전역 누수이거나, '학군지' 태그 게이트를 여는 의도적 변경입니다 "
        "— 후자라면 PRISTINE_COMPARABLE 과 근거(공통 척도·학교ID 정확일치)를 함께 갱신하세요.")
    yield


# ---------------------------------------------------------------------------
# 1. 근거가 없으면 태그가 없다 (가장 중요한 가드)
# ---------------------------------------------------------------------------

def test_성취도_근거가_없으면_태그를_붙이지_않는다():
    """변이: 이 게이트를 통과시키면 여기서 잡힌다."""
    tag = assess_school_district_tag()
    assert tag.verdict == "unavailable"
    assert tag.tagged is False


def test_판정불가를_아님으로_접지_않는다():
    """`unavailable` 을 `no` 로 접으면 화면이 '학군지 아님'이라고 거짓 단언을 한다."""
    assert assess_school_district_tag().verdict != "no"


def test_판정불가에는_사유가_함께_나온다():
    tag = assess_school_district_tag()
    assert tag.reason_code
    assert tag.reason.strip()


def test_태그를_못_붙이면_정의도_내보내지_않는다():
    """정의 없는 배지를 만들지 않기 위한 가드. 정의는 태그와 한 몸이다."""
    assert assess_school_district_tag().definition is None


# ---------------------------------------------------------------------------
# 2. 거리로는 이 함수를 통과할 수 없다 (서명 고정)
# ---------------------------------------------------------------------------

def test_판정_함수는_거리를_인자로_받지_않는다():
    """변이: `distance_m` 인자를 추가하면 여기서 잡힌다.

    없는 인자는 실수로 못 쓴다 — 문서보다 서명이 강한 방어선이다.
    """
    params = set(inspect.signature(assess_school_district_tag).parameters)
    assert not {p for p in params if "distance" in p or "dist" in p or "거리" in p}


def test_성취도_근거_구조에_거리_필드가_없다():
    """변이: `AchievementFact` 에 거리 필드를 넣으면 여기서 잡힌다."""
    names = set(AchievementFact.__dataclass_fields__)
    assert not {n for n in names if "distance" in n or "dist" in n}


# ---------------------------------------------------------------------------
# 3. 기준연도·출처 없는 수치는 쓰지 않는다
# ---------------------------------------------------------------------------

def _threshold(monkeypatch, value: float = 20.0):
    """임계값을 임시로 준다. **실제 상수는 None 이다**(모집단이 없어 못 정한다)."""
    monkeypatch.setattr(sq, "TOP_PERCENTILE_THRESHOLD", value)


def _allow(monkeypatch, *sources: str):
    monkeypatch.setattr(sq, "COMPARABLE_ACHIEVEMENT_SOURCES", frozenset(sources))


def test_임계값이_없으면_근거가_있어도_판정하지_않는다(monkeypatch):
    """'상위 X%'는 모집단 분포에서 나온다. 모집단이 없으면 임계값도 없다."""
    assert sq.TOP_PERCENTILE_THRESHOLD is None, (
        "임계값이 생겼습니다. 비교 가능한 모집단을 먼저 확보했는지 확인하세요 "
        "— 숫자만 적으면 근거가 생긴 척하는 것입니다(모듈 docstring '임계값을 정하지 않는 이유').")
    _allow(monkeypatch, "가상 공통척도")          # 근거 요건은 모두 갖춘 상태로 만든다
    tag = assess_school_district_tag([
        AchievementFact(school_id="B000008126", level="중학교", value=88.5,
                        source="가상 공통척도", as_of="2025",
                        percentile=95.0, population="수도권 중학교"),
    ])
    assert tag.verdict == "unavailable"
    assert tag.reason_code == sq.REASON_NO_THRESHOLD


def test_근거가_없을_때는_임계값이_아니라_근거를_사유로_낸다():
    """사유 순서 고정. 임계값 미정은 근거 부재의 **결과**지 원인이 아니다.

    변이: 임계값 검사를 근거 검사 앞으로 옮기면 모든 단지가 "임계값 미정"만 받게
    되고 원인이 화면에서 사라진다 — 여기서 잡힌다.
    """
    assert assess_school_district_tag().reason_code == sq.REASON_NO_FACT
    only_level = [AchievementFact(school_id=None, level="초등학교", value=None)]
    assert assess_school_district_tag(only_level).reason_code == sq.REASON_NO_VALUE


def test_기준연도가_없으면_수치를_쓰지_않는다(monkeypatch):
    """변이: `as_of` 검사를 지우면 여기서 잡힌다. 성취도는 해마다 바뀐다."""
    _threshold(monkeypatch)
    _allow(monkeypatch, "가상 공통척도")
    tag = assess_school_district_tag([
        AchievementFact(school_id="B000008126", level="중학교", value=88.5,
                        source="가상 공통척도", as_of=None,
                        percentile=95.0, population="수도권 중학교"),
    ])
    assert tag.verdict == "unavailable"
    assert tag.reason_code == sq.REASON_NO_PROVENANCE


def test_출처가_없으면_수치를_쓰지_않는다(monkeypatch):
    _threshold(monkeypatch)
    _allow(monkeypatch, "가상 공통척도")
    tag = assess_school_district_tag([
        AchievementFact(school_id="B000008126", level="중학교", value=88.5,
                        source=None, as_of="2025",
                        percentile=95.0, population="수도권 중학교"),
    ])
    assert tag.verdict == "unavailable"
    assert tag.reason_code == sq.REASON_NO_PROVENANCE


def test_태그를_붙이면_기준연도가_사유와_근거에_남는다(monkeypatch):
    """변이: 기준연도 표기를 빼면 여기서 잡힌다."""
    _threshold(monkeypatch)
    _allow(monkeypatch, "가상 공통척도")
    tag = assess_school_district_tag([
        AchievementFact(school_id="B000008126", level="중학교", value=88.5,
                        source="가상 공통척도", as_of="2025",
                        percentile=95.0, population="수도권 중학교 1,206교"),
    ])
    assert tag.verdict == "yes"
    assert "2025" in tag.reason
    assert tag.evidence[0]["as_of"] == "2025"
    assert tag.evidence[0]["source"] == "가상 공통척도"
    assert tag.definition == sq.TAG_DEFINITION


# ---------------------------------------------------------------------------
# 4. 비교 불가능한 출처는 명시적으로 거절한다
# ---------------------------------------------------------------------------

def test_비교가능_출처_목록은_지금_비어_있다():
    """실측 결론의 코드 표현. 이 집합이 비어 있는 한 태그는 켜지지 않는다.

    변이: 여기에 아무 출처나 넣으면 이 테스트가 잡는다 — 출처를 추가하려면
    (a) 전 학교 공통 척도, (b) 학교 단위 공개, (c) 학교ID 정확일치를
    먼저 실증하라는 뜻이다.
    """
    assert sq.COMPARABLE_ACHIEVEMENT_SOURCES == PRISTINE_COMPARABLE, (
        "'학군지' 태그 게이트를 여는 변경입니다. 출처를 추가하려면 (a) 전 학교 공통 척도 "
        "(b) 학교 단위 공개 (c) 학교ID(kesi:B…) 정확일치 를 먼저 실증하고, "
        "이 테스트의 PRISTINE_COMPARABLE 도 함께 고치세요.")


def test_거절목록이_테스트_기대와_일치한다():
    """★ 아래 parametrize 가 **케이스 0개로 사라지는 것**을 막는 가드.

    예전에는 `sorted(sq.NON_COMPARABLE_ACHIEVEMENT_SOURCES)` 를 그대로 파라미터로 썼다.
    그러면 모듈 집합이 비는 순간 '단위학교 자체평가는 쓰지 않는다' 검사가 **아무 실패도
    없이 통째로 없어진다**(테스트 수만 줄어든다 — 아무도 안 본다).
    지금은 기대 목록을 테스트가 들고 있고, 어긋나면 여기서 잡힌다.
    """
    assert sq.NON_COMPARABLE_ACHIEVEMENT_SOURCES == NON_COMPARABLE_EXPECTED


@pytest.mark.parametrize("source", sorted(NON_COMPARABLE_EXPECTED))
def test_단위학교_자체평가_결과는_학군지_판정에_쓰지_않는다(monkeypatch, source):
    """학교알리미 「교과별 학업성취 사항」은 원천이 '단위학교별 평가계획에 의거'라고
    밝힌 교내 평가 결과다. 시험 난이도가 학교마다 달라 학교 간 비교가 성립하지 않는다.

    변이: 이 출처를 허용목록에 넣어도, 거절목록 검사가 먼저라 여전히 막힌다.
    """
    _threshold(monkeypatch)
    _allow(monkeypatch, source)                       # 일부러 허용목록에도 넣어 본다
    tag = assess_school_district_tag([
        AchievementFact(school_id="B000008126", level="중학교", value=88.5,
                        source=source, as_of="2025",
                        percentile=99.0, population="수도권 중학교"),
    ])
    assert tag.verdict == "unavailable"
    assert tag.reason_code == sq.REASON_SOURCE_NOT_COMPARABLE


def test_등록되지_않은_출처는_보류한다(monkeypatch):
    _threshold(monkeypatch)
    tag = assess_school_district_tag([
        AchievementFact(school_id="B000008126", level="중학교", value=88.5,
                        source="어디선가 본 숫자", as_of="2025",
                        percentile=95.0, population="수도권 중학교"),
    ])
    assert tag.verdict == "unavailable"
    assert tag.reason_code == sq.REASON_SOURCE_UNKNOWN


# ---------------------------------------------------------------------------
# 5. 학교ID 로만 잇는다 (이름 매칭 금지)
# ---------------------------------------------------------------------------

def test_학교ID_가_없으면_판정하지_않는다(monkeypatch):
    """변이: `school_id` 검사를 지우면 여기서 잡힌다.

    이름으로 이으면 동명 학교(예: 전국의 '중앙중학교')에서 조용히 틀린다.
    """
    _threshold(monkeypatch)
    _allow(monkeypatch, "가상 공통척도")
    tag = assess_school_district_tag([
        AchievementFact(school_id=None, level="중학교", value=88.5,
                        source="가상 공통척도", as_of="2025",
                        percentile=95.0, population="수도권 중학교"),
    ])
    assert tag.verdict == "unavailable"
    assert tag.reason_code == sq.REASON_NO_SCHOOL_ID


def test_백분위가_없으면_상위_X퍼센트를_말하지_않는다(monkeypatch):
    _threshold(monkeypatch)
    _allow(monkeypatch, "가상 공통척도")
    tag = assess_school_district_tag([
        AchievementFact(school_id="B000008126", level="중학교", value=88.5,
                        source="가상 공통척도", as_of="2025",
                        percentile=None, population="수도권 중학교"),
    ])
    assert tag.verdict == "unavailable"
    assert tag.reason_code == sq.REASON_NO_PERCENTILE


# ---------------------------------------------------------------------------
# 6. 임계값을 넘지 못하면 'no' 다 (근거가 다 있을 때만 'no' 를 말할 수 있다)
# ---------------------------------------------------------------------------

def test_근거가_충분하고_임계값에_못_미치면_아님이다(monkeypatch):
    _threshold(monkeypatch, 20.0)                     # 상위 20% 가 기준이라고 가정
    _allow(monkeypatch, "가상 공통척도")
    tag = assess_school_district_tag([
        AchievementFact(school_id="B000008126", level="중학교", value=60.0,
                        source="가상 공통척도", as_of="2025",
                        percentile=50.0, population="수도권 중학교"),
    ])
    assert tag.verdict == "no"
    assert tag.tagged is False


def test_요건_미달_근거를_평균내지_않는다(monkeypatch):
    """근거 둘 중 하나만 요건을 갖추면 **그 하나로** 판정한다.

    미달 근거를 섞어 평균 내면 출처 없는 수치가 결과에 스며든다.
    """
    _threshold(monkeypatch, 20.0)
    _allow(monkeypatch, "가상 공통척도")
    tag = assess_school_district_tag([
        AchievementFact(school_id="B1", level="중학교", value=10.0,
                        source=None, as_of=None,             # 미달 — 무시돼야 한다
                        percentile=1.0, population="수도권 중학교"),
        AchievementFact(school_id="B2", level="고등학교", value=95.0,
                        source="가상 공통척도", as_of="2025",
                        percentile=99.0, population="수도권 고등학교"),
    ])
    assert tag.verdict == "yes"
    assert len(tag.evidence) == 1
    assert tag.evidence[0]["school_id"] == "B2"
