"""정비사업(재건축·재개발) — 파싱·매칭 가드 · 단계 정규화 · 리스크-수익 판정.

이 파일이 지키는 **세 가지 절대 규칙** (깨지면 사용자가 틀린 근거로 수억을 쓴다)
------------------------------------------------------------------------------
① 추가분담금 **금액을 우리 코드가 만들지 않는다.** 도메인 문장은 주제어와 금액이
   한 필드에 같이 있으면 예외로 막고(`assert_no_cost_estimate`), LLM 에는 이 주제의
   재료를 **아예 주지 않고**(`redact_cost_topic`) 출력에 주제어가 보이면 금액 여부와
   무관하게 그 요약을 폐기한다(`assert_no_cost_topic`).
   ⚠️ "어떤 경로로도 막는다"고 **주장하지 않는다** — 주제어 없이 금액만 쓰는 문장은
      텍스트 검사로 잡히지 않는다(CR30-1). 지키지 못할 약속을 사용자 화면에 적는 것이
      이 프로젝트에서 가장 비싼 실패다.
② 단계는 **단조 점수가 아니다** — 목적(실거주/투자)에 따라 정반대 신호가 된다.
③ 매칭이 애매하면 **매칭하지 않는다** — 이름 유사도·부분 문자열로 잇지 않는다.

⚠️ 여기 테스트는 **자기충족이 되지 않도록** 실제 운영 데이터에서 관측된 문자열
   ('망우본동461-12', '경동 40번지 및 율목동 10번지 일원' 등)을 그대로 쓴다.
   상수를 바꾸면 데이터도 따라 움직이는 형태의 검사는 통과만 하고 아무것도 지키지 못한다.
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.domain.redevelopment.analysis import (
    COST_DISCLOSURE,
    PURPOSE_INVEST,
    PURPOSE_LIVE,
    STAGE_PROFILE,
    CostEstimateError,
    assert_no_cost_estimate,
    assess_redevelopment,
)
from app.domain.redevelopment.models import RedevProject
from app.domain.redevelopment.stages import (
    KIND_REBUILD,
    KIND_REDEVELOP,
    STAGE_ASSOCIATION,
    STAGE_CANDIDATE,
    STAGE_COMMITTEE,
    STAGE_COMPLETED,
    STAGE_CONSTRUCTION,
    STAGE_DESIGN_REVIEW,
    STAGE_DISPOSITION,
    STAGE_IMPLEMENTATION,
    STAGE_ORDER,
    STAGE_UNKNOWN,
    STAGE_ZONE_DESIGNATED,
    normalize_biz_type,
    normalize_stage,
)
from app.ingest.redevelopment import (
    DONG_ADMIN_STRIPPED,
    SIDO_INCHEON,
    SIDO_SEOUL,
    STATUS_MULTI_JIBUN,
    STATUS_OK,
    STATUS_ROAD_ONLY,
    STATUS_UNKNOWN_DONG,
    build_dong_index,
    parse_address,
    parse_incheon_csv,
    parse_seoul_csv,
)

TODAY = dt.date(2026, 7, 27)

# ---------------------------------------------------------------------------
# 픽스처 — 운영 `region` 스냅샷의 **실제 값**을 쓴다
# ---------------------------------------------------------------------------
#: (법정동코드, 시도, 시군구, 동). 오매칭 회귀를 재현하려면 '본동'(동작구)이 꼭 필요하다.
REGION_ROWS = [
    ("1168010600", SIDO_SEOUL, "강남구", "대치동"),
    ("1168010500", SIDO_SEOUL, "강남구", "압구정동"),
    ("1147010100", SIDO_SEOUL, "양천구", "목동"),
    ("1147010200", SIDO_SEOUL, "양천구", "신정동"),      # 마포구에도 '신정동'이 있다
    ("1144012700", SIDO_SEOUL, "마포구", "신정동"),
    ("1135010500", SIDO_SEOUL, "노원구", "상계동"),
    ("1159010200", SIDO_SEOUL, "동작구", "본동"),        # ← '망우본동' 의 꼬리와 겹친다
    ("1126010100", SIDO_SEOUL, "중랑구", "면목동"),      # ← '목동'(양천구)을 꼬리로 품는다
    ("1126010400", SIDO_SEOUL, "중랑구", "망우동"),
    ("1171010200", SIDO_SEOUL, "송파구", "잠실동"),
    ("1114010300", SIDO_SEOUL, "중구", "정동"),
    ("2812510700", SIDO_INCHEON, "제물포구", "송림동"),
    ("2812510500", SIDO_INCHEON, "제물포구", "창영동"),
    ("2812514100", SIDO_INCHEON, "제물포구", "경동"),
    ("2812513800", SIDO_INCHEON, "제물포구", "율목동"),
    ("2812510300", SIDO_INCHEON, "제물포구", "송현동"),
]


@pytest.fixture(scope="module")
def index():
    return build_dong_index(REGION_ROWS)


def _scope(index, sido, sigungu):
    return index.scope(sido, sigungu)


# ===========================================================================
# 규칙 ③ — 매칭이 애매하면 매칭하지 않는다
# ===========================================================================

def test_대표지번이_읽히면_법정동코드까지_확정된다(index):
    """은마아파트: 자료 '대치동316' → 강남구 대치동 316-0 (운영 DB 실측 필지와 일치)."""
    out = parse_address("대치동316", _scope(index, SIDO_SEOUL, "강남구"))
    assert out.status == STATUS_OK
    assert out.jibun.key == ("1168010600", 316, 0, False)


def test_시군구_접미사_뒤의_동은_읽는다(index):
    """'양천구목동903' 처럼 시군구가 붙어 있어도 목동 903 이다(목동3단지)."""
    out = parse_address("양천구목동903", _scope(index, SIDO_SEOUL, "양천구"))
    assert out.status == STATUS_OK
    assert out.jibun.key == ("1147010100", 903, 0, False)


def test_행정동_표기는_법정동으로_되돌려_읽되_그_사실을_남긴다(index):
    """'목2동523-45' 의 법정동은 목동이다. 되돌린 이름이 실제 법정동일 때만 인정한다."""
    out = parse_address("목2동523-45번지일대", _scope(index, SIDO_SEOUL, "양천구"))
    assert out.status == STATUS_OK
    assert out.jibun.key == ("1147010100", 523, 45, False)
    assert out.jibun.dong_match == DONG_ADMIN_STRIPPED     # 한 단계 덜 직접적이다
    assert "행정동" in out.detail


# --- ★ 오매칭 회귀 (실제로 났던 사고) --------------------------------------

@pytest.mark.parametrize("address, sigungu", [
    ("망우본동461-12", "중랑구"),      # 중랑구 상봉13구역 — '본동'(동작구)의 꼬리
    ("중계본동30-3", "노원구"),        # 노원구 백사마을
    ("면목본동69-14", "중랑구"),
])
def test_낱말_꼬리로_다른_구의_법정동을_잡지_않는다(index, address, sigungu):
    """★ 변이 테스트 대상.

    `_boundary_ok` 를 지우면 '망우본동'·'중계본동'의 꼬리 '본동' 이 **동작구 본동**으로
    잡혀 중랑구·노원구 재개발 구역이 동작구 필지에 붙는다(2026-07-27 실측으로 발견).
    놓치는 것(unknown_dong)이 정답이다.
    """
    out = parse_address(address, _scope(index, SIDO_SEOUL, sigungu))
    assert out.status == STATUS_UNKNOWN_DONG, out
    assert out.jibun is None


# --- ★ 오매칭 회귀 ② — 긴 이름이 짧은 이름에 먹히지 않는다 (CR-029 차단 3) ------
#
# '면목동'(중랑구)은 '목동'(양천구)을 **꼬리로 품는다.** 그리고 `_boundary_ok` 의
# `_ALLOWED_PREV` 에 '면' 이 들어 있어서 '면'+'목동' 조합은 낱말경계 검사를 통과한다.
# 예전에는 이걸 막는 것이 `sorted(names, key=len, reverse=True)` **정렬 한 줄**뿐이었고,
# 그 줄을 짧은 이름 우선으로 바꾸면 '면목동 69-14'(중랑구)가 **양천구 목동**으로
# 확정됐다(`match_method='pnu_exact'` 라 화면에는 "대표지번 정확일치"로 보인다).
# 그런데 그 변이로 백엔드 1,064건이 전부 통과했다 — 하중을 받는 축에 테스트가 없었다.
#
# 아래 둘이 그 축을 고정한다:
#   ① 결과 자체(면목동이어야 한다)
#   ② **이름 목록의 순서와 무관**해야 한다 — 순서에 의존하는 구현이 다시 들어오면
#      한 순서에서만 답이 달라지므로 여기서 잡힌다.

_NAME_ORDERINGS = {
    "as_given": list,
    "alphabetical": lambda ns: sorted(ns),
    "reverse_alphabetical": lambda ns: sorted(ns, reverse=True),
    "shortest_first": lambda ns: sorted(ns, key=len),          # ← 옛 사고를 낸 순서
    "longest_first": lambda ns: sorted(ns, key=len, reverse=True),
}


def test_긴_법정동명이_짧은_꼬리_이름에_먹히지_않는다(index):
    """★ '면목동 69-14'(중랑구)는 중랑구 면목동이다 — 양천구 목동이 아니다."""
    out = parse_address("면목동 69-14", _scope(index, SIDO_SEOUL, "중랑구"))
    assert out.status == STATUS_OK, out
    assert out.jibun.dong_name == "면목동"
    assert out.jibun.legal_dong_code == "1126010100", (
        "중랑구 정비구역이 양천구 목동 필지에 붙었다 — 가장 긴 이름 우선이 깨졌다")
    assert out.jibun.key == ("1126010100", 69, 14, False)


@pytest.mark.parametrize("ordering", sorted(_NAME_ORDERINGS))
def test_법정동_구간_찾기는_이름_목록_순서에_의존하지_않는다(ordering):
    """★ 구조 검사: 어떤 순서로 이름을 줘도 **같은 답**이 나와야 한다.

    정렬 순서에 기대는 구현(옛 `sorted(names, key=len, reverse=True)` 루프)이 다시
    들어오면, 이 파라미터 중 하나에서 답이 달라져 여기서 넘어진다.
    ⚠️ 아래 이름 집합은 **합성**이다(접두 포함쌍 '가나동' ⊂ '가나동3가' 를 만들려면
       실재 법정동만으로는 사례가 나오지 않는다). 실재 사례(면목동/목동)는 위 테스트가 본다.
    """
    from app.ingest.redevelopment import _find_dong_spans

    names = ["목동", "면목동", "본동", "가나동", "가나동3가"]
    cases = {
        # 꼬리 포함 — 긴 이름이 이겨야 한다
        "면목동 69-14": [(0, 3, "면목동")],
        # 접두 포함 — 역시 긴 이름이 이겨야 한다
        "가나동3가 12-3": [(0, 5, "가나동3가")],
        "가나동 12-3": [(0, 3, "가나동")],
        # 시군구 접미사 뒤는 읽는다
        "양천구목동903": [(3, 5, "목동")],
        # 더 긴 낱말의 꼬리는 읽지 않는다
        "망우본동461-12": [],
        # 여러 동이 나오면 왼쪽부터 전부
        "목동 1 및 본동 2": [(0, 2, "목동"), (7, 9, "본동")],
    }
    order = _NAME_ORDERINGS[ordering]
    for text, expected in cases.items():
        assert _find_dong_spans(text, order(names)) == expected, (
            f"{ordering}: {text!r} 의 결과가 이름 목록 순서에 따라 달라졌다")


def test_행정구역_접미사_예외는_어간이_있을_때만_허용된다():
    """★ '면'·'구' 한 글자만 앞에 있는 것은 행정구역이 아니라 **더 긴 낱말의 일부**다.

    긴 이름(면목동)이 색인에 없는 시도에서도 '면목동 69-14' 가 '목동' 으로 읽히면
    안 된다 — 정렬·최대일치와 **독립적인** 두 번째 방어가 필요한 이유다.
    `_boundary_ok` 의 어간 조건(`idx >= 2`)을 지우면 여기서 잡힌다.
    """
    partial = build_dong_index([
        ("1147010100", SIDO_SEOUL, "양천구", "목동"),      # '면목동' 은 일부러 뺀다
    ])
    out = parse_address("면목동 69-14", partial.scope(SIDO_SEOUL, "중랑구"))
    assert out.status == STATUS_UNKNOWN_DONG, out
    assert out.jibun is None
    # 반대로 진짜 행정구역 접미사 뒤(어간이 있다)는 계속 읽어야 한다.
    ok = parse_address("양천구목동903", partial.scope(SIDO_SEOUL, "양천구"))
    assert ok.status == STATUS_OK and ok.jibun.legal_dong_code == "1147010100"


def test_지번이_둘이면_매칭하지_않는다(index):
    """'경동 40번지 및 율목동 10번지 일원' — 어느 쪽이 대표인지 알 수 없다."""
    out = parse_address("경동 40번지 및 율목동 10번지 일원",
                        _scope(index, SIDO_INCHEON, "중구"))
    assert out.status == STATUS_MULTI_JIBUN
    assert out.jibun is None


def test_지번_나열도_매칭하지_않는다(index):
    """'송림동 2, 4번지 일원' — 콤마 나열은 대표지번이 아니다.

    ★ 변이 테스트 대상: `_JIBUN_LIST_RE` 에 `^` 를 되돌려 넣으면(match(s, pos) 에서
    `^` 는 pos 가 아니라 문자열 맨 앞만 본다) 이 가드가 조용히 무력화되고
    '송림동 2' 가 대표지번으로 통과한다.
    """
    out = parse_address("송림동 2, 4번지 일원", _scope(index, SIDO_INCHEON, "동구"))
    assert out.status == STATUS_MULTI_JIBUN
    assert out.jibun is None


def test_도로명만_있으면_지번을_지어내지_않는다(index):
    out = parse_address("제물량로 341 일원", _scope(index, SIDO_INCHEON, "동구"))
    assert out.status == STATUS_ROAD_ONLY
    assert out.jibun is None


def test_동명이_시도_안에서_중복이면_시군구로만_가른다(index):
    """'신정동' 은 양천구·마포구 둘 다 있다. 자료가 말한 구로만 확정한다."""
    yang = parse_address("신정동325", _scope(index, SIDO_SEOUL, "양천구"))
    mapo = parse_address("신정동325", _scope(index, SIDO_SEOUL, "마포구"))
    assert yang.jibun.legal_dong_code == "1147010200"
    assert mapo.jibun.legal_dong_code == "1144012700"

    # 자료의 시군구가 둘 다 아니면 **확정하지 않는다**(아무거나 고르지 않는다).
    other = parse_address("신정동325", _scope(index, SIDO_SEOUL, "강남구"))
    assert other.jibun is None


def test_서울_중구_주소가_인천_구역에_붙지_않는다(index):
    """'중구'는 서울에도 인천에도 있다. 시도로 색인하지 않으면 두 도시가 섞인다."""
    seoul = parse_address("정동 1-1", _scope(index, SIDO_SEOUL, "중구"))
    incheon = parse_address("정동 1-1", _scope(index, SIDO_INCHEON, "중구"))
    assert seoul.status == STATUS_OK and seoul.jibun.legal_dong_code == "1114010300"
    assert incheon.jibun is None, "인천 자료가 서울 법정동을 잡았다"


def test_매칭_SQL_은_이름을_보지_않는다():
    """★ 구조적 가드: 매칭 근거는 **필지(PNU) 정확일치 하나뿐**이다.

    이름 유사도를 한 줄이라도 넣으면 '○○1구역' 과 '○○아파트' 가 붙는다.
    문서로 약속하지 않고 소스를 검사한다.
    """
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1]
           / "scripts" / "load_redevelopment.py").read_text(encoding="utf-8")
    match_sql = src.split("_MATCH_SQL = \"\"\"")[1].split("\"\"\"")[0]
    # SELECT 절에 이름이 있는 건 리포트 출력용이라 괜찮다. 문제는 **무엇으로 고르는가** 다.
    predicate = match_sql.split("WHERE", 1)[1]
    for token in ("name", "similarity", "ILIKE", "LIKE", "levenshtein", "ST_D", "geom"):
        assert token not in predicate, f"매칭 조건에 이름/근접 매칭이 들어갔다: {token}"
    for column in ("legal_dong_code", "main_no", "sub_no", "is_mountain"):
        assert column in predicate, f"매칭 조건이 {column} 를 대조하지 않는다"


# ===========================================================================
# 단계 정규화 — 원문은 보존, 미분류는 버리지 않는다
# ===========================================================================

#: 2026-07-27 실측 원문(서울 7종 · 인천 15종). 하나라도 unknown 이면 커버리지 구멍이다.
SEOUL_RAW_STAGES = ["구역지정", "추진위", "조합설립", "건축심의", "사업시행",
                    "관리처분", "착공"]
INCHEON_RAW_STAGES = ["후보지 1차", "후보지 2차", "후보지 1차(추진위승인)",
                      "후보지 2차(추진위승인)", "정비구역지정", "정비구역지정(추진위승인)",
                      "추진위원회승인", "추진위원회 승인", "조합설립인가",
                      "사업시행계획인가", "사업시행자지정(신탁사)", "관리처분계획인가",
                      "착공", "착공(부분준공)", "준공"]


@pytest.mark.parametrize("raw", SEOUL_RAW_STAGES + INCHEON_RAW_STAGES)
def test_실측_원문_단계명이_전부_분류된다(raw):
    assert normalize_stage(raw) != STAGE_UNKNOWN, f"{raw!r} 가 미분류다"
    assert normalize_stage(raw) in STAGE_ORDER


def test_모르는_단계명은_지어내지_않고_미분류로_남는다():
    assert normalize_stage("듣도보도못한단계") == STAGE_UNKNOWN
    assert normalize_stage("") == STAGE_UNKNOWN
    assert normalize_stage(None) == STAGE_UNKNOWN


def test_사업시행인가와_사업시행자지정을_섞지_않는다():
    """글자가 겹치지만 뜻이 다르다 — 부분일치로 접으면 두 단계를 건너뛴 것으로 읽힌다."""
    assert normalize_stage("사업시행계획인가") == STAGE_IMPLEMENTATION
    assert normalize_stage("사업시행자지정(신탁사)") == STAGE_ASSOCIATION


def test_후보지는_구역지정_전으로_본다():
    """'후보지 2차(추진위승인)' 도 아직 구역이 지정되지 않았다. 보수적으로 읽는다."""
    assert normalize_stage("후보지 2차(추진위승인)") == STAGE_CANDIDATE


def test_사업유형_정규화():
    assert normalize_biz_type("공동주택재건축") == KIND_REBUILD
    assert normalize_biz_type("아파트지구재건축") == KIND_REBUILD
    assert normalize_biz_type("주택정비형재개발") == KIND_REDEVELOP
    # 인천 CSV 의 '사업유형' 칸에 단계 문구가 들어온 행 — 유형을 만들어내지 않는다.
    assert normalize_biz_type("정비구역지정(후보지 1차)") == "unknown"


# ===========================================================================
# 규칙 ① — 추가분담금 금액은 나가지 않는다
# ===========================================================================

@pytest.mark.parametrize("poisoned", [
    "추가분담금 약 1.2억 예상됩니다",
    "분담금은 1억 2천만원 수준으로 보입니다",
    "추가분담금 120,000,000원이 필요합니다",
    "조합원 부담금 3억원",
    "1.5억 원의 추가분담금이 예상됩니다",
    "추정 분담 5000만원",
    # --- CR-030 이 뚫은 4종. 근접 30자 창을 버리고 **필드 전체**를 보면서 닫혔다 ---
    "추가분담금이 발생합니다. 규모는 세대당 1억 2천만 원 정도입니다",       # 문장 분리
    "추가분담금은 조합 내부 자료라 확정할 수 없으나 업계에서는 통상 "
    "1억 2천만 원 정도로 봅니다",                                        # 30자 초과 거리
    "조합원 부담이 세대당 1억 원 수준입니다",                             # '부담'(금 없음)
    "분담액은 1억 2천만 원 수준입니다",                                   # 다른 어간
])
def test_분담금_금액이_섞이면_즉시_막는다(poisoned):
    """★ 변이 테스트 대상 — **우리 코드가 만든 문장**에 대한 검사다.

    `assert_no_cost_estimate` 를 no-op 으로 바꾸거나 근접 창(`[^.\\n]{0,30}`)을
    되살리면 뒤쪽 4종이 통과해 버린다. 실제 사고 문구를 그대로 쓴다.
    """
    with pytest.raises(CostEstimateError):
        assert_no_cost_estimate(poisoned)


@pytest.mark.parametrize("ok_text", [
    "기존 1,588가구 → 건립 예정 3,317세대(2.09배)입니다.",
    "구역지정 2025-12-04, 추진위원회 2025-12-11.",
    "중위 실거래가 1,350,000,000원입니다.",     # 시세 금액은 분담금이 아니다
    COST_DISCLOSURE,                            # 고지 문구 자체는 통과해야 한다
])
def test_정상_문장은_막지_않는다(ok_text):
    assert_no_cost_estimate(ok_text)            # 예외가 나면 실패


def _project(stage_raw: str, stage: str, **kw) -> RedevProject:
    base = dict(zone_name="테스트구역", sigungu="강남구", raw_stage=stage_raw,
                stage=stage, raw_biz_type="공동주택재건축", biz_type=KIND_REBUILD,
                source="test", as_of=TODAY)
    base.update(kw)
    return RedevProject(**base)


@pytest.mark.parametrize("stage", [s for s in STAGE_ORDER])
@pytest.mark.parametrize("purpose", [PURPOSE_LIVE, PURPOSE_INVEST])
def test_모든_판정에_분담금_미확인_고지가_붙는다(stage, purpose):
    """★ 변이 테스트 대상: `COST_DISCLOSURE` 를 빼면 여기서 전부 깨진다.

    고지가 없으면 사용자는 "분담금까지 따진 점수"로 읽는다 — 정반대다.
    """
    out = assess_redevelopment(_project("원문", stage), purpose=purpose, as_of=TODAY)
    assert COST_DISCLOSURE in out.rationale
    assert any("추가분담금" in v for v in out.must_verify)


def test_판정_출력_어디에도_분담금_금액이_없다():
    """rationale·verdict·risks·upsides 를 전부 훑는다(한 군데라도 새면 실패)."""
    project = _project("사업시행", STAGE_IMPLEMENTATION,
                       existing_households=1588, planned_households=3317,
                       zone_designated_on=dt.date(2020, 1, 1),
                       implementation_on=dt.date(2025, 6, 1))
    out = assess_redevelopment(project, purpose=PURPOSE_INVEST, as_of=TODAY)
    assert_no_cost_estimate(out.rationale, out.verdict,
                            *(d for _, d in out.risks), *out.upsides,
                            *out.must_verify)


def test_근거의_출처가_사람이_읽는_이름이다():
    """★ SR25-3 — 공공누리 4유형의 **출처표시** 의무는 기계 키로 충족되지 않는다.

    예전 표기는 `seoul_opendata_TbSeoulRedevStatus` 였다. 두 가지가 틀렸다:
      ① 사용자가 읽을 수 없다(출처표시가 형식적으로도 안 된다)
      ② `TbSeoulRedevStatus` 는 SR24-1 로 **삭제한 인증키 OpenAPI 의 테이블명**이라
         실제 출처(무키 CSV, OA-22856)와 어긋난다 — 없는 경로를 출처라고 적는 셈이다.
    식별자(`detail.source`)는 DB 자연키라 그대로 두고, **보이는 것만** 사람 말로 바꿨다.
    """
    from app.domain.redevelopment.models import (
        SOURCE_INCHEON,
        SOURCE_LABELS,
        SOURCE_SEOUL,
        source_label,
    )

    project = _project("사업시행", STAGE_IMPLEMENTATION, source=SOURCE_SEOUL,
                       existing_households=1588, planned_households=3317)
    out = assess_redevelopment(project, purpose=PURPOSE_INVEST, as_of=TODAY)

    sources = {e["source"] for e in out.evidence}
    assert sources, out.evidence
    for src in sources:
        assert "서울특별시" in src and "OA-22856" in src, src
        assert "TbSeoulRedevStatus" not in src
    # 식별자는 살아 있다(추적·재현용) — 표시명과 **둘 다** 남긴다.
    assert out.detail["source"] == SOURCE_SEOUL
    assert out.detail["source_label"] == SOURCE_LABELS[SOURCE_SEOUL]
    # 인천도 라벨이 있어야 한다. 모르는 키는 뭉개지 말고 그대로 보여준다.
    assert "인천광역시" in source_label(SOURCE_INCHEON)
    assert source_label("새로운_출처_키") == "새로운_출처_키"


# ===========================================================================
# 규칙 ② — 단조 점수 금지 (목적별 리스크-수익 프로파일)
# ===========================================================================

def test_투자_프로파일은_비단조다():
    """사업시행인가에서 정점을 찍고 관리처분 이후 **떨어진다**.

    ★ 변이 테스트 대상: 프로파일을 '단계가 뒤일수록 +' 로 바꾸면 여기서 깨진다.
    """
    p = STAGE_PROFILE[PURPOSE_INVEST]
    order = [s for s in STAGE_ORDER if s in p]
    values = [p[s] for s in order]
    rising = any(b > a for a, b in zip(values, values[1:]))
    falling = any(b < a for a, b in zip(values, values[1:]))
    assert rising and falling, "투자 프로파일이 단조다 — 도메인적으로 틀렸다"
    assert p[STAGE_IMPLEMENTATION] > p[STAGE_DISPOSITION] > p[STAGE_COMPLETED]
    assert p[STAGE_IMPLEMENTATION] > p[STAGE_CANDIDATE]


def test_실거주_프로파일은_뒤로_갈수록_나빠진다():
    """이주·철거가 임박할수록 실거주에는 불리하다 — 투자와 **정반대** 방향이다."""
    p = STAGE_PROFILE[PURPOSE_LIVE]
    assert p[STAGE_ZONE_DESIGNATED] > p[STAGE_IMPLEMENTATION] > p[STAGE_DISPOSITION]
    assert p[STAGE_CONSTRUCTION] < p[STAGE_COMPLETED]


@pytest.mark.parametrize("stage", [STAGE_DISPOSITION, STAGE_CONSTRUCTION])
def test_같은_단계가_목적에_따라_정반대다(stage):
    live = assess_redevelopment(_project("관리처분", stage), purpose=PURPOSE_LIVE,
                                as_of=TODAY)
    invest = assess_redevelopment(_project("관리처분", stage), purpose=PURPOSE_INVEST,
                                  as_of=TODAY)
    assert invest.score > live.score, (invest.score, live.score)
    assert "부적합" in live.verdict


@pytest.mark.parametrize("stage", [STAGE_ASSOCIATION, STAGE_DESIGN_REVIEW,
                                   STAGE_IMPLEMENTATION])
def test_판정_문구가_점수와_같은_방향을_가리킨다(stage):
    """실거주 사용자에게 '진행 확실성 상승 구간'이라고 하면 40점짜리 판정이 호재로 읽힌다.

    문구와 점수가 반대면 사용자는 어느 쪽도 믿지 않는다(실호출 검증에서 발견).
    """
    live = assess_redevelopment(_project("원문", stage), purpose=PURPOSE_LIVE,
                                as_of=TODAY)
    invest = assess_redevelopment(_project("원문", stage), purpose=PURPOSE_INVEST,
                                  as_of=TODAY)
    assert "확실성 상승" not in live.verdict, live.verdict
    assert "제한" in live.verdict
    assert "확실성 상승" in invest.verdict


def test_초기_단계는_상방과_하방을_모두_낸다():
    out = assess_redevelopment(_project("추진위", STAGE_COMMITTEE),
                               purpose=PURPOSE_INVEST, as_of=TODAY)
    assert out.upsides, "상방 근거가 없다 — 리스크만 나열하면 판단이 아니라 겁주기다"
    assert any(sev in ("high", "medium") for sev, _ in out.risks)
    assert out.early_stage is True
    assert any("10년" in d for _, d in out.risks)


def test_장기_정체는_감점되고_리스크로_말한다():
    """상계5 구역: 2008 구역지정 이후 2026 까지 건축심의 — 18년 정체(실측)."""
    stalled = _project("건축심의", STAGE_DESIGN_REVIEW,
                       zone_designated_on=dt.date(2008, 9, 11))
    fresh = _project("건축심의", STAGE_DESIGN_REVIEW,
                     zone_designated_on=dt.date(2025, 9, 11))
    a = assess_redevelopment(stalled, purpose=PURPOSE_INVEST, as_of=TODAY)
    b = assess_redevelopment(fresh, purpose=PURPOSE_INVEST, as_of=TODAY)
    assert a.score < b.score
    assert a.years_since_milestone > 15
    assert any("정체" in d for _, d in a.risks)


def test_일자를_모르면_정체로_감점하지_않는다():
    """인천 자료에는 단계별 일자가 없다. **모르는 것으로 벌주지 않는다.**"""
    no_dates = _project("조합설립인가", STAGE_ASSOCIATION)
    out = assess_redevelopment(no_dates, purpose=PURPOSE_INVEST, as_of=TODAY)
    assert out.score == STAGE_PROFILE[PURPOSE_INVEST][STAGE_ASSOCIATION]
    assert out.years_since_milestone is None
    assert out.confidence < 0.75, "일자가 없는데 신뢰도가 서울 수준이다"


def test_세대수_증가율은_사업성_방향만_말한다():
    big = _project("사업시행", STAGE_IMPLEMENTATION,
                   existing_households=1000, planned_households=2500)
    small = _project("사업시행", STAGE_IMPLEMENTATION,
                     existing_households=1000, planned_households=1050)
    a = assess_redevelopment(big, purpose=PURPOSE_INVEST, as_of=TODAY)
    b = assess_redevelopment(small, purpose=PURPOSE_INVEST, as_of=TODAY)
    assert a.score > b.score
    assert a.supply_ratio == 2.5
    # 방향만 말하고 **금액은 말하지 않는다**.
    assert_no_cost_estimate(a.rationale, b.rationale)


# ===========================================================================
# 모름 ≠ 없음
# ===========================================================================

def test_매칭된_구역이_없으면_0이_아니라_모름이다():
    out = assess_redevelopment(None, purpose=PURPOSE_LIVE, as_of=TODAY)
    assert out.available is False
    assert out.score is None, "0 점은 '재건축 가치 없음'으로 읽힌다 — 모름이어야 한다"
    assert "확인되지 않았다" in out.rationale or "확인되지" in out.rationale
    assert "경기" in out.rationale, "수집 범위를 말하지 않으면 '없다'로 읽힌다"
    assert out.must_verify


def test_단계를_분류하지_못해도_구역이_있다는_사실은_남긴다():
    out = assess_redevelopment(_project("듣도보도못한단계", STAGE_UNKNOWN),
                               purpose=PURPOSE_LIVE, as_of=TODAY)
    assert out.available is True          # 구역은 있다
    assert out.score is None              # 단계를 모르니 점수는 없다
    assert "듣도보도못한단계" in out.rationale, "원문 단계명을 잃어버렸다"
    assert COST_DISCLOSURE in out.rationale


# ===========================================================================
# CSV 파서 (실제 파일 형태)
# ===========================================================================

SEOUL_CSV = (
    '"CODE","순번","자치구","구역명","지번주소","도로명주소","사업방법_공공/민간",'
    '"사업방법_일반/재촉지구","사업유형","사업추진단계","기존가구수(멸실량)",'
    '"구역지정_최초","구역지정_변경최종","추진위원회","조합설립인가(사업시행자 지정일)",'
    '"건축심의","사업시행인가_최초","사업시행인가_변경(최종)","관리처분계획인가_최초",'
    '"관리처분계획인가_변경최종","이주시작일","이주종료일","착공일","건립세대수_총합계",'
    '"건립세대수_분양","건립세대수_임대"\n'
    '"2814","126","양천구","목동3단지","양천구목동903","양천구 목동서로 100","민간","일반",'
    '"공동주택재건축","추진위","1588","2025-12-04","2025-12-04","2025-12-11","","","","",'
    '"","","","","","3317","2919","398"\n'
    '"2777","433","중랑구","상봉13구역","망우본동461-12","-","민간","일반",'
    '"주택정비형재개발","조합설립","100","2020-01-01","","","2021-01-01","","","","",'
    '"","","","","200","180","20"\n'
)

INCHEON_CSV = (
    "구명,구 역 명,위치,면적(제곱미터)     ,사업유형,진행단계\n"
    '동구,"송현1,2차A",송현동 1번지 일원,50679.6,재건축,사업시행계획인가\n'
    '동구,송림4,"송림동 2, 4번지 일원",23915,주거환경개선(전면개량),착공\n'
)


def test_서울_CSV_파싱(index):
    recs = parse_seoul_csv(SEOUL_CSV, as_of=TODAY, dong_index=index)
    assert len(recs) == 2

    mokdong = recs[0]
    assert mokdong.zone_name == "목동3단지"
    assert mokdong.raw_stage == "추진위" and mokdong.stage == STAGE_COMMITTEE
    assert mokdong.parse_status == STATUS_OK
    assert (mokdong.legal_dong_code, mokdong.main_no) == ("1147010100", 903)
    assert mokdong.existing_households == 1588
    assert mokdong.planned_households == 3317
    assert mokdong.committee_on == dt.date(2025, 12, 11)
    # 빈 칸은 **None** 이다 — 0 이나 오늘로 채우지 않는다.
    assert mokdong.implementation_on is None

    sangbong = recs[1]
    assert sangbong.parse_status == STATUS_UNKNOWN_DONG   # 오매칭 대신 미매칭
    assert sangbong.legal_dong_code is None
    assert sangbong.raw_stage == "조합설립"                # 원문은 남는다


def test_인천_CSV_파싱(index):
    """헤더에 공백이 섞여 있고('구 역 명'), 단계별 일자가 **없다**."""
    recs = parse_incheon_csv(INCHEON_CSV, as_of=TODAY, dong_index=index)
    assert len(recs) == 2

    songhyeon = recs[0]
    assert songhyeon.sigungu == "동구"                     # 출처 표기 그대로 보존
    assert songhyeon.stage == STAGE_IMPLEMENTATION
    assert songhyeon.legal_dong_code == "2812510300"       # 개편 후 제물포구 송현동
    # 서울 형식에 맞춰 없는 일자를 만들어 넣지 않는다.
    assert songhyeon.implementation_on is None
    assert songhyeon.existing_households is None

    songnim = recs[1]
    assert songnim.parse_status == STATUS_MULTI_JIBUN
    assert songnim.legal_dong_code is None


# ===========================================================================
# 파이프라인 — 점수가 **양방향**으로 움직이고, 기피 조건이 실제로 동작한다
# ===========================================================================

def _pipeline_ctx(candidates, *, purpose=PURPOSE_LIVE, weights=None, avoid=None):
    from pathlib import Path

    from app.agents.orchestrator import AnalysisContext
    from app.domain.affordability.engine import compute_affordability
    from app.domain.affordability.models import Borrower, PropertyFacts
    from app.domain.rules.loader import load_rules

    rules = load_rules(Path(__file__).parent / "fixtures" / "tax_rules_test.yaml")
    afford = compute_affordability(
        Borrower(cash_krw=20_00_000_000, annual_income_krw=300_000_000), rules,
        prop=PropertyFacts(area_m2=84.0))
    return AnalysisContext(affordability=afford, candidates=candidates,
                           weights=weights or {}, avoid=avoid or {},
                           purpose=purpose, as_of=TODAY)


def _pipeline_candidate(cid, name, *, redevelopment=None):
    from app.agents.orchestrator import Candidate
    from app.domain.valuation.models import TradeRow

    trades = [TradeRow(contract_date=TODAY - dt.timedelta(days=15 * i),
                       price_krw=700_000_000, area_m2=84.97, floor=10)
              for i in range(8)]
    return Candidate(complex_id=cid, complex_name=name, unit_type_id=None,
                     area_m2=84.97, group=None, trades=trades,
                     total_households=500, listings=[],
                     redevelopment=redevelopment)


def test_재건축_축은_점수를_올리기도_내리기도_한다():
    """★ 전부 오르면 변별력이 없는 것이다 — **양방향**임을 실제 파이프라인으로 고정한다.

    같은 단지(가격·환금성 동일)에 정비사업 단계만 다르게 붙이고, 목적을 실거주로 둔다.
      · 관리처분(이주 임박) → 재건축 축이 총점을 **끌어내린다**
      · 준공(새 아파트)     → 재건축 축이 총점을 **끌어올린다**
    기준선은 '정보 없음'(그 축이 빠지고 재정규화된 총점)이다.
    """
    from app.agents.orchestrator import run_mvp_pipeline
    from app.agents.scoring import AXIS_REDEV, AXIS_VALUE

    weights = {AXIS_VALUE: 0.5, AXIS_REDEV: 0.5}

    def total(project):
        cand = _pipeline_candidate(1, "단지", redevelopment=project)
        out = run_mvp_pipeline(_pipeline_ctx([cand], weights=weights), llm=None)
        return out["items"][0]["total_score"]

    baseline = total(None)                       # 재건축 정보 없음 → 가치 축만 반영
    late = total(_project("관리처분", STAGE_DISPOSITION))
    done = total(_project("준공", STAGE_COMPLETED))

    assert late < baseline, ("내려가야 할 단계가 안 내려갔다", late, baseline)
    assert done > baseline, ("올라가야 할 단계가 안 올라갔다", done, baseline)
    # 전부 같은 방향으로만 움직이면 변별력이 없는 것이다.
    assert late != done


def test_정비사업_정보가_없으면_그_축은_빠지고_사유가_남는다():
    from app.agents.orchestrator import run_mvp_pipeline
    from app.agents.scoring import AXIS_REDEV, AXIS_VALUE, STATUS_NO_SIGNAL

    cand = _pipeline_candidate(1, "정보없는단지", redevelopment=None)
    out = run_mvp_pipeline(
        _pipeline_ctx([cand], weights={AXIS_VALUE: 0.5, AXIS_REDEV: 0.5}), llm=None)
    top = out["items"][0]

    axes = {r["axis"]: r for r in top["score_axes"]}
    assert axes[AXIS_REDEV]["status"] == STATUS_NO_SIGNAL
    assert axes[AXIS_REDEV]["score"] is None            # 0 이 아니다
    joined = " ".join(out["notes"]) + " ".join(top["score_notes"])
    assert "확인되지 않" in joined and "경기" in joined
    assert top["redevelopment"]["available"] is False


def test_기피조건_초기단계_재건축은_후보에서_제외된다():
    """api-spec §2 `avoid.redevelopment_early_stage` — 계약에만 있고 동작하지 않던 값."""
    from app.agents.orchestrator import EXCLUDED_AVOIDED, run_mvp_pipeline

    early = _pipeline_candidate(1, "추진위단지",
                                redevelopment=_project("추진위", STAGE_COMMITTEE))
    late = _pipeline_candidate(2, "관리처분단지",
                               redevelopment=_project("관리처분", STAGE_DISPOSITION))
    unknown = _pipeline_candidate(3, "정보없는단지", redevelopment=None)

    out = run_mvp_pipeline(
        _pipeline_ctx([early, late, unknown],
                      avoid={"redevelopment_early_stage": True}), llm=None)

    names = [it["complex"]["name"] for it in out["items"]]
    assert "추진위단지" not in names
    # ⚠️ **정보가 없는 단지는 빼지 않는다** — 모름을 '해당'으로 처리하면 경기도 단지가
    #    통째로 사라진다.
    assert "정보없는단지" in names and "관리처분단지" in names

    dropped = [e for e in out["excluded"] if e["reason_code"] == EXCLUDED_AVOIDED]
    assert len(dropped) == 1 and "초기 단계" in dropped[0]["reason"]


def test_기피조건_문자열_false는_켜지_않는다():
    from app.agents.orchestrator import avoids_early_redevelopment

    assert avoids_early_redevelopment({"redevelopment_early_stage": True}) is True
    assert avoids_early_redevelopment({"redevelopment_early_stage": "false"}) is False
    assert avoids_early_redevelopment({"redevelopment_early_stage": ""}) is False
    assert avoids_early_redevelopment({}) is False


def test_분담금_직접확인_안내가_추천_카드까지_도달한다():
    """★ 이게 이 기능에서 가장 중요한 출력이다 — 시스템이 **모르는 것**을 말해 준다."""
    from app.agents.orchestrator import run_mvp_pipeline

    cand = _pipeline_candidate(1, "재건축단지",
                               redevelopment=_project("조합설립", STAGE_ASSOCIATION))
    out = run_mvp_pipeline(_pipeline_ctx([cand]), llm=None)
    top = out["items"][0]

    assert any("추가분담금" in a for a in top["next_actions"]), top["next_actions"]
    assert any("추가분담금" in n for n in out["notes"])
    # 카드 어디에도 분담금 **금액**은 없다.
    assert_no_cost_estimate(*top["next_actions"], *top["why_not"], *top["why"],
                            top["headline"], *out["notes"])


# --- ★ LLM 경로 회귀 (CR-029 차단 1 / SR24-3) --------------------------------
#
# 위 테스트는 `llm=None` 으로 돌아 **규칙 기반 폴백만** 검사한다. 폴백 문장은 이미
# 도메인 assert 를 통과한 것이라 구조적으로 통과할 수밖에 없다 — 실제 구멍은
# `portfolio_summary()` 의 **LLM 출력**이었고, 그 경로에는 검사가 하나도 없었다.
# 아래 문자열은 리뷰어가 FakeLLM 으로 실제 재현한 값이다.

#: 모델이 뱉을 수 있는 "그럴듯한" 응답 — 금액이 네 필드에 골고루 섞여 있다.
_LLM_WITH_COST = {
    "headline": "조합설립 단계 재건축 — 추가분담금 약 1.2억 원 예상",
    "why": ["기존 1,588가구 → 건립 예정 2,300세대로 사업성이 양호합니다"],
    "why_not": ["조합원 추가분담금이 세대당 1억 2천만 원 수준으로 추정됩니다"],
    "next_actions": ["분담금 2억 원을 감안해 자금계획을 세우세요"],
}


def test_LLM이_추가분담금_금액을_뱉으면_규칙기반으로_강등하고_고지한다():
    """★ 변이 대상: `portfolio_summary` 반환 직전의 `assert_no_cost_estimate`.

    같은 카드가 "공개 데이터에 없으니 직접 확인하라"와 "1억 2천만 원"을 **동시에**
    말하던 상태의 회귀다. 사용자는 숫자를 읽는다.

    ⚠️ 예외로 죽이지 않는다 — 요약 한 줄 때문에 추천 전체가 사라지면 그것도 사고다.
       규칙 기반으로 **강등**하고 그 사실을 카드(`summary_basis`)와 notes 로 말한다.
    """
    from app.agents.llm import FakeLLM
    from app.agents.orchestrator import run_mvp_pipeline

    llm = FakeLLM(repeat=_LLM_WITH_COST)
    cand = _pipeline_candidate(1, "재건축단지",
                               redevelopment=_project("조합설립", STAGE_ASSOCIATION))
    # tripwire 검사값은 `_derive_forbidden` 이 affordability 파생값으로 무장한다.
    out = run_mvp_pipeline(_pipeline_ctx([cand]), llm=llm)
    top = out["items"][0]

    # ① LLM 은 실제로 호출됐다(테스트가 폴백 경로만 돌고 끝나지 않았다는 증거).
    assert llm.calls, "LLM 이 호출되지 않아 이 테스트는 아무것도 증명하지 못한다"
    # ② 그런데 금액이 든 응답은 채택되지 않았다.
    assert top["summary_basis"] == "fallback", top["summary_basis"]
    assert "1.2억" not in top["headline"] and "2,300세대" not in top["headline"]
    # ③ 카드 어느 필드에도 분담금 금액이 없다.
    #    ⚠️ "어떤 경로로도 없다"가 아니다 — 이 단언이 보장하는 것은 **이 응답에 대해**
    #       카드가 깨끗하다는 것뿐이다(파일 상단 규칙 ① 참조).
    assert_no_cost_estimate(top["headline"], *top["why"], *top["why_not"],
                            *top["next_actions"], *out["notes"])
    # ④ 조용히 바꾸지 않는다 — 폐기했다는 사실을 사용자에게 말한다.
    assert any("추가분담금" in n and "폐기" in n for n in out["notes"]), out["notes"]
    # ⑤ 분담금은 여전히 "직접 확인" 안내로 남는다(막았다고 침묵하지 않는다).
    assert any("추가분담금" in a for a in top["next_actions"]), top["next_actions"]


def test_금액이_없는_LLM_요약은_그대로_채택된다():
    """대조군. 위 방어가 **모든 LLM 요약을 폴백시키는** 것이라면 방어가 아니라 고장이다."""
    from app.agents.llm import FakeLLM
    from app.agents.orchestrator import run_mvp_pipeline

    clean = {
        "headline": "조합설립 단계 재건축 — 진행 확실성이 오르는 구간",
        "why": ["기존 1,588가구 → 건립 예정 2,300세대(1.45배)입니다"],
        "why_not": ["이주·철거가 남아 실거주 시점을 가늠하기 어렵습니다"],
        "next_actions": ["조합 사무실에서 사업시행계획을 확인하세요"],
    }
    llm = FakeLLM(repeat=clean)
    cand = _pipeline_candidate(1, "재건축단지",
                               redevelopment=_project("조합설립", STAGE_ASSOCIATION))
    # tripwire 검사값은 `_derive_forbidden` 이 affordability 파생값으로 무장한다.
    out = run_mvp_pipeline(_pipeline_ctx([cand]), llm=llm)
    top = out["items"][0]

    assert top["summary_basis"] == "llm", top["summary_basis"]
    assert top["headline"] == clean["headline"]
    assert not any("폐기" in n for n in out["notes"]), out["notes"]


def test_요약_시스템_프롬프트가_분담금_주제_자체를_금지한다():
    """프롬프트가 '추가분담금' 을 **먹여 주면서** 금지 조항은 없던 상태의 회귀.

    ⚠️ CR30-1 이후 금지 대상이 '금액' 에서 **낱말**로 바뀌었다. 규칙이 "금액을 쓰지
       말라"이면 모델은 금액이 아닌 척 쓰는 법을 찾는다("통상 …정도로 봅니다").
       재료를 안 주는 쪽으로 갔으므로 규칙도 "이 낱말을 쓰지 말라"로 단순해진다.
    """
    from app.agents.orchestrator import PORTFOLIO_SYSTEM

    assert "분담" in PORTFOLIO_SYSTEM and "부담" in PORTFOLIO_SYSTEM
    # 금액 여부와 무관하게 폐기한다는 사실을 모델에게 알린다(안 알리면 매번 폴백한다).
    assert "폐기" in PORTFOLIO_SYSTEM


# --- ★★ CR30-1 회귀 — 금액 표기 변형 4종 + 필드 분리 ------------------------
#
# CR-030 이 근접 정규식(`분담금` + 금액 30자 이내)을 **네 가지 흔한 완성문**으로
# 뚫었다. 아래 문자열은 리뷰어가 FakeLLM 으로 실제 재현한 값 그대로이고,
# `필드 분리`는 이번 수정 중에 내가 추가로 찾은 다섯 번째다 —
# "한 필드 안 동시출현"으로 고쳤다면 이것이 그대로 통과했다.
#
# ⚠️ 단언 지점은 **최종 카드**(`run_mvp_pipeline` 결과)다.
#    `assert_no_cost_topic` 을 직접 호출해 놓고 통과했다고 적으면 CR-029→CR-030 에서
#    이미 한 번 속은 그 방식이다(검사가 호출된다 ≠ 카드가 깨끗하다).

_COST_BYPASSES = {
    "문장분리": ["추가분담금이 발생합니다. 규모는 세대당 1억 2천만 원 정도입니다"],
    "30자초과": ["추가분담금은 조합 내부 자료라 확정할 수 없으나 업계에서는 "
                 "통상 1억 2천만 원 정도로 봅니다"],
    "부담_금없음": ["조합원 부담이 세대당 1억 원 수준입니다"],
    "분담액": ["분담액은 1억 2천만 원 수준입니다"],
    # 리뷰어가 제안한 '한 필드 동시출현' 규칙을 무력화하는 형태(문장을 배열로 쪼갠다).
    "필드분리": ["추가분담금이 발생합니다", "규모는 세대당 1억 2천만 원 정도입니다"],
}


@pytest.mark.parametrize("label", sorted(_COST_BYPASSES))
def test_LLM_분담금_우회_5종이_최종_카드에서_전부_막힌다(label):
    """★ 변이 대상: `portfolio_summary` 의 `assert_no_cost_topic` · `_COST_TOPIC_RE`.

    주제어를 `(?:추가\\s*)?분담금|부담금|…` 같은 **완성형 낱말**로 되돌리면
    '부담_금없음'·'분담액'이 살아나고, 검사를 필드/문장 단위 금액 근접으로 되돌리면
    '문장분리'·'30자초과'·'필드분리'가 살아난다.
    """
    from app.agents.llm import FakeLLM
    from app.agents.orchestrator import run_mvp_pipeline

    resp = {
        "headline": "조합설립 단계 재건축 — 진행 확실성이 오르는 구간",
        "why": ["기존 1,588가구 → 건립 예정 2,300세대로 사업성이 양호합니다"],
        "why_not": list(_COST_BYPASSES[label]),
        "next_actions": ["조합 사무실에서 사업시행계획을 확인하세요"],
    }
    llm = FakeLLM(repeat=resp)
    cand = _pipeline_candidate(1, "재건축단지",
                               redevelopment=_project("조합설립", STAGE_ASSOCIATION))
    out = run_mvp_pipeline(_pipeline_ctx([cand]), llm=llm)
    top = out["items"][0]

    assert llm.calls, "LLM 이 호출되지 않아 이 테스트는 아무것도 증명하지 못한다"
    assert top["summary_basis"] == "fallback", (label, top["summary_basis"])
    # 카드에 찍히는 네 필드 어디에도 지어낸 금액이 없다.
    card = " ".join([top["headline"], *top["why"], *top["why_not"],
                     *top["next_actions"]])
    for coined in ("1억 2천만", "1억 원", "1.2억"):
        assert coined not in card, (label, card)
    # 폐기 사실을 고지하고, 분담금 안내는 **고정 문구로** 그대로 남는다.
    assert any("폐기" in n for n in out["notes"]), out["notes"]
    assert any("추가분담금" in a for a in top["next_actions"]), top["next_actions"]


def test_요약_프롬프트에_분담금_재료가_실리지_않는다():
    """★ 이번 수정의 **본체**. 검사가 아니라 재료 차단이 1차 방어다.

    모델이 분담금을 말한 것은 우리가 `COST_DISCLOSURE` 를 rationale 로 실어 주고
    세대수 증감을 함께 줬기 때문이다. 재료를 빼면 주제어가 나타나는 것 자체가
    이상 신호가 되고, 그때부터 금액 표기 변형을 쫓을 필요가 없다.

    ★ 변이 대상: `portfolio_summary` 의 `_cost_free_finding` 호출을 `f.to_dict()` 로
      되돌리면 여기서 깨진다.
    """
    from app.agents.llm import FakeLLM
    from app.agents.orchestrator import run_mvp_pipeline

    clean = {
        "headline": "조합설립 단계 재건축 — 진행 확실성이 오르는 구간",
        "why": ["기존 1,588가구 → 건립 예정 2,300세대(1.45배)입니다"],
        "why_not": ["이주·철거가 남아 실거주 시점을 가늠하기 어렵습니다"],
        "next_actions": ["조합 사무실에서 사업시행계획을 확인하세요"],
    }
    llm = FakeLLM(repeat=clean)
    cand = _pipeline_candidate(1, "재건축단지",
                               redevelopment=_project("조합설립", STAGE_ASSOCIATION))
    out = run_mvp_pipeline(_pipeline_ctx([cand]), llm=llm)

    assert llm.calls, "LLM 이 호출되지 않았다"
    prompt = llm.calls[0]["user"]
    for word in ("분담", "부담", "환급"):
        assert word not in prompt, f"프롬프트에 '{word}' 재료가 남아 있다"
    # 그런데 **사용자에게는 그대로 보인다** — 재료를 뺀 것이지 고지를 뺀 게 아니다.
    top = out["items"][0]
    assert any("추가분담금" in a for a in top["next_actions"])
    assert any("추가분담금" in n for n in out["notes"])
    # 카드에 실리는 findings(응답)에는 고지가 살아 있다(프롬프트용 정리와 분리돼 있다).
    assert any(COST_DISCLOSURE in f["rationale"] for f in top["findings"])


def test_재료_정리가_뚫리면_LLM_을_아예_호출하지_않는다(monkeypatch):
    """★ 변이 대상: `portfolio_summary` 의 `contains_cost_topic(user)` fail-safe.

    `_cost_free_finding` 은 Finding 의 텍스트 필드를 **하나씩 명시적으로** 훑는다.
    나중에 텍스트 필드가 하나 더 생기고 이 함수를 갱신하지 않으면 분담금 재료가
    조용히 되살아난다 — 그 상황을 흉내 내서, 그때 **호출 자체가 막히는지** 본다.
    (재료가 남은 채로 보내면 모델이 다시 금액을 쓰고 우리는 다시 폴백한다.)
    """
    from app.agents import orchestrator as orch
    from app.agents.llm import FakeLLM

    monkeypatch.setattr(orch, "_cost_free_finding", lambda f: f.to_dict())
    llm = FakeLLM(repeat={"headline": "h", "why": ["w"], "why_not": ["r"],
                          "next_actions": ["a"]})
    cand = _pipeline_candidate(1, "재건축단지",
                               redevelopment=_project("조합설립", STAGE_ASSOCIATION))
    out = orch.run_mvp_pipeline(_pipeline_ctx([cand]), llm=llm)

    assert llm.calls == [], "분담금 재료가 남았는데도 프롬프트가 나갔다"
    assert out["items"][0]["summary_basis"] == "fallback"


def test_분담금을_언급만_해도_폐기하지만_잃는_정보가_없다():
    """★ 이 판정이 **의도된 것**임을 고정한다(오탐이 아니라 설계).

    '최근 실거래 7억 원 수준이며 추가분담금은 확인되지 않았습니다' — 금액을 지어내지
    않은 옳은 문장이다. 그런데 이 문장과 '…통상 1억 2천만 원 정도로 봅니다'는
    **텍스트 검사로는 같은 모양**이다(주제어 + 금액이 한 문장에 있다). 둘을 가르려면
    금액이 어느 명사에 붙는지를 이해해야 하고, 그건 정규식이 못 한다.

    그래서 **폐기하는 쪽**을 고른다. 근거는 잃는 정보가 0 이라는 것이다:
      · 분담금 안내는 코드가 고정 문구로 이미 말한다(next_actions · notes)
      · 실거래가는 규칙 기반 요약이 finding rationale 로 그대로 말한다
      · 폐기 사실은 고지된다
    이 세 줄이 깨지면 그때는 진짜 오탐이 된다 — 그래서 여기서 고정한다.
    """
    from app.agents.llm import FakeLLM
    from app.agents.orchestrator import run_mvp_pipeline

    modest = {
        "headline": "조합설립 단계 재건축 — 진행 확실성이 오르는 구간",
        "why": ["최근 실거래 7억 원 수준이며 추가분담금은 확인되지 않았습니다"],
        "why_not": ["이주·철거가 남아 실거주 시점을 가늠하기 어렵습니다"],
        "next_actions": ["조합 사무실에서 사업시행계획을 확인하세요"],
    }
    llm = FakeLLM(repeat=modest)
    cand = _pipeline_candidate(1, "재건축단지",
                               redevelopment=_project("조합설립", STAGE_ASSOCIATION))
    out = run_mvp_pipeline(_pipeline_ctx([cand]), llm=llm)
    top = out["items"][0]

    assert top["summary_basis"] == "fallback"
    # ① 분담금 안내는 그대로 나간다.
    assert any("추가분담금" in a for a in top["next_actions"])
    # ② 실거래 근거도 그대로 나간다(요약이 규칙 기반으로 바뀌었을 뿐).
    assert any("실거래" in w for w in top["why"]), top["why"]
    # ③ 폐기 고지가 **사실만** 말한다 — 지키지 못할 약속을 하지 않는다.
    note = next(n for n in out["notes"] if "폐기" in n)
    assert "어떤 경로로도" not in note, note
    assert "표현" in note and "폐기" in note


def test_목적이_투자면_같은_단지의_재건축_점수가_달라진다():
    from app.agents.orchestrator import run_mvp_pipeline

    project = _project("관리처분", STAGE_DISPOSITION)

    def redev_score(purpose):
        cand = _pipeline_candidate(1, "단지", redevelopment=project)
        out = run_mvp_pipeline(_pipeline_ctx([cand], purpose=purpose), llm=None)
        return out["items"][0]["redevelopment"]["score"]

    assert redev_score(PURPOSE_INVEST) > redev_score(PURPOSE_LIVE)


# ===========================================================================
# CR31-1 — 도메인 lint 가 **외부 수집 문자열** 때문에 job 을 죽이지 않는다
#
# 배경: CR-030 통과 조건으로 검사 창을 '필드 전체'로 넓혔더니, `rationale` 은
#       `COST_DISCLOSURE` 때문에 주제어가 **항상 참**이라 사실상
#       "rationale 에 금액 토큰이 하나라도 있으면 예외"가 됐다. 그 rationale 에는
#       수집 원문(구역명·원문 단계명)이 그대로 인용된다 → `제3원구역` 하나로
#       `CostEstimateError` → 아무도 안 잡음 → **추천 job 전체가 failed + 빈 결과.**
#
# 여기 테스트가 고정하는 것은 두 가지다:
#   ① 인용된 **수집 원문**은 이 lint 의 검사 대상이 아니다(우리가 지어낸 게 아니다).
#   ② 그럼에도 **우리가 쓴 문장**의 금액은 그대로 막힌다 — 인용문 제외가 우회로가
#      되면 이 검사는 껍데기가 된다.
# ===========================================================================

@pytest.mark.parametrize("field, value", [
    # CR-031 이 실제로 재현한 3종
    ("zone_name", "1억원지구"),
    ("raw_stage", "조합설립(추정 5000만원)"),
    ("zone_name", "제3원구역"),
    # 운영 DB 616행에 실재하는 표기(현재는 발화하지 않지만 형태를 고정해 둔다)
    ("zone_name", "장위4구역"),
    ("zone_name", "수원역구역"),
    # 경기도 추가 시 들어올 수 있는 형태
    ("zone_name", "1억5천만원구역"),
    ("raw_stage", "사업시행인가(2,000,000원 부과)"),
])
def test_수집_원문에_금액이_있어도_판정이_죽지_않는다(field, value):
    """★ 변이 가드 — `assess_redevelopment` 에서 `source_quotes=quotes` 를 빼면 죽는다.

    외부 값에 금액처럼 보이는 글자가 있어도 그건 **우리가 지어낸 금액이 아니다.**
    죽이면 후보 한 건의 구역명 때문에 추천 전체가 사라진다.
    """
    project = _project("조합설립", STAGE_ASSOCIATION, **{field: value})
    out = assess_redevelopment(project, purpose=PURPOSE_LIVE, as_of=TODAY)

    assert out.available is True
    # 원문은 지우지 않는다 — 인용은 그대로 사용자에게 간다.
    assert value in out.rationale
    assert value in out.source_quotes


def test_수집_원문_제외가_우회로가_되지_않는다():
    """★ 이 테스트가 없으면 위 완화는 그냥 검사를 끄는 것과 같다.

    인용문을 선언해도 **우리 서술 부분**의 금액은 그대로 걸려야 한다.
    """
    with pytest.raises(CostEstimateError):
        assert_no_cost_estimate(
            "제3원구역의 추가분담금은 세대당 1억 2천만 원으로 예상됩니다",
            source_quotes=("제3원구역", "조합설립"))


@pytest.mark.parametrize("text, quotes", [
    ("분담금 3억원", ("원", "억")),
    # ★ 한 글자짜리 조각들이 금액 토큰을 **통째로** 덮는 형태. `_MIN_QUOTE_LEN` 이
    #   없으면 이 조합만으로 우리 금액 전체가 '인용'으로 읽혀 통과한다.
    ("분담금 3억원", ("3", "억", "원")),
    ("분담금은 1.2억원입니다", ("1", ".", "2", "억", "원")),
])
def test_인용문이_짧으면_인용_구간으로_세지_않는다(text, quotes):
    """★ 변이 가드 — `_MIN_QUOTE_LEN` 을 1 로 낮추면 여기서 죽는다.

    한두 글자짜리 값('원'·'1')을 인용으로 인정하면, 그 조각들이 문장 곳곳을 덮어
    우리가 쓴 금액까지 인용으로 읽힌다.
    """
    with pytest.raises(CostEstimateError):
        assert_no_cost_estimate(text, source_quotes=quotes)


# ---------------------------------------------------------------------------
# SR27-2 / CR32-3 — **외부 수집값이 이 검사를 끌 수 없다**
#
# CR31-1 조치(인용문 제외)의 첫 구현은 인용문을 표식으로 **치환한 뒤** 그 결과에서
# 주제어와 금액을 찾았다. 치환은 문자열을 바꾸는 일이라 우리 **검사어까지 갈랐다** —
# `raw_stage="분담"` 두 글자면 고지 문구의 `추가분담금` 이 쪼개져 주제어가 사라지고,
# 그 필드의 lint 가 통째로 no-op 이 됐다. '검사 대상 축소'가 아니라
# **외부 데이터가 방어의 스위치를 쥐는** 상태였다.
#
# 지금 규칙은 두 줄이다:
#   · 주제어는 **원문 전체**에서 찾는다(치환하지 않으므로 갈라지지 않는다).
#   · 금액은 **인용 구간 밖에 한 글자라도 걸치면** 우리 것이다.
# ---------------------------------------------------------------------------

#: 우리(코드)가 쓴 문장. 고지 문구와 같은 주제어를 갖는다.
_OUR_SENTENCE = "추가분담금은 조합 내부 자료라 확인할 수 없습니다. 예상 분담금 1억 2천만 원."


@pytest.mark.parametrize("quote", [
    "분담",        # ← SR27-2 실측: 이 두 글자로 lint 가 통째로 꺼졌다
    "분담금",
    "추가분담금",
    "부담",
    "환급",
    "확인할 수 없습니다",   # 우리 문장의 일부를 인용이라 주장해도 마찬가지
])
def test_인용문이_주제어를_삼켜도_검사가_꺼지지_않는다(quote):
    """★ 변이 가드 — 주제어 탐색을 다시 '인용 제거본'에서 하면 여기서 죽는다.

    수집값이 우리 검사어와 겹친다는 이유로 검사가 무력화되면, 그 검사는 외부
    데이터가 끌 수 있는 스위치다. 인용문이 줄여도 되는 것은 **금액**뿐이다.
    """
    with pytest.raises(CostEstimateError):
        assert_no_cost_estimate(_OUR_SENTENCE, source_quotes=(quote,))


@pytest.mark.parametrize("quote", [
    "1.2억",      # 금액 토큰의 앞부분만 인용
    "억원",        # 단위만 인용
    "2억",        # 아예 다른 금액을 인용
])
def test_인용문이_금액을_일부만_덮으면_우리_금액이다(quote):
    """★ 인용 구간에 **완전히** 덮인 금액만 인용이다.

    치환 방식에서는 `'억원'` 만 인용해도 남은 `1.2` 가 금액으로 안 읽혀 통과했다.
    위치로 판정하면 토큰이 인용 밖으로 한 글자라도 나오는 순간 우리 것이다.
    """
    with pytest.raises(CostEstimateError):
        assert_no_cost_estimate("분담금은 약 1.2억원으로 예상됩니다.", source_quotes=(quote,))


def test_인용_구간에_완전히_덮인_금액만_통과한다():
    """경계의 반대쪽 — 인용문이 금액을 통째로 덮으면 그건 **사실의 인용**이다.

    이 성질이 곧 CR31-1 해소의 본체다(`1억원지구` 하나로 job 이 죽지 않는 이유).
    """
    from app.domain.redevelopment.analysis import money_outside_quotes

    text = "성북구 1억원지구 재건축 구역에 포함됩니다. " + COST_DISCLOSURE
    assert money_outside_quotes(text, ("1억원지구",)) is None
    # 같은 문장에 **우리가** 금액을 한 줄 더 쓰면 그건 잡힌다.
    poisoned = text + " 예상 분담금은 3억원입니다."
    hit = money_outside_quotes(poisoned, ("1억원지구",))
    assert hit is not None and hit.group(0) == "3억원"


def test_인용문이_여러_번_나와도_전부_인용으로_센다():
    """같은 구역명이 rationale 에 두 번 인용되는 문장(evidence 합류)에서도 안 죽는다."""
    from app.domain.redevelopment.analysis import money_outside_quotes

    text = "1억원지구 재건축입니다. 원문 '1억원지구' 기준입니다. " + COST_DISCLOSURE
    assert money_outside_quotes(text, ("1억원지구",)) is None


def test_인용_구간은_겹치는_출현까지_합쳐서_센다():
    """★ 변이 가드 — 출현 탐색을 `start+len`(겹침 무시)으로 좁히면 여기서 죽는다.

    합성 문자열이다(실데이터 구역명은 자기 자신과 겹치지 않는다). 고정하는 것은
    **성질**이다: 인용 구간은 모든 출현의 **합집합**이고, 좁게 잡으면 인용문 안의
    금액 꼬리가 '우리 것'으로 오인돼 판정이 죽는다 — CR31-1 과 같은 방향의 오탐이다.
    """
    # '1억1' 은 '1억1억1원' 안에서 offset 0 과 2 에 **겹쳐** 나온다.
    # 합집합 [0,5) 로 덮으면 금액 토큰('1억'·'1억')이 전부 인용 안이다.
    assert_no_cost_estimate("분담금 1억1억1원", source_quotes=("1억1",))


@pytest.mark.parametrize("text, expected", [
    ("제3원구역", ()),                       # ← CR31-1 이 지목한 무의미 매칭
    ("3원", ()),
    ("10원", ()),
    ("300원", ()),
    ("3000원", ("3000원",)),
    ("700,000,000원", ("700,000,000원",)),
    ("3억원", ("3억원",)),
    ("5000만원", ("5000만원",)),
    ("1.2억 원", ("1.2억 원",)),
])
def test_단위없는_원은_자릿수_하한이_있다(text, expected):
    """★ 변이 가드 — `_MONEY_RE` 를 옛 형태(`|원`)로 되돌리면 '제3원구역'이 걸린다."""
    from app.domain.redevelopment.analysis import money_like_tokens

    assert money_like_tokens(text) == expected


def test_분담금_방어가_걸려도_추천은_살아남는다(monkeypatch):
    """★ 그물 — 도메인이 뚫려 예외가 나도 **그 후보의 재건축 블록만** 내려놓는다.

    CR31-1 이 보고한 사고 경로 그대로다: 예외 → 아무도 안 잡음 →
    `run_recommendation_job` 포괄 except → job failed + 빈 결과.
    """
    from app.agents import orchestrator as O
    from app.agents.orchestrator import run_mvp_pipeline
    from app.domain.redevelopment.analysis import CostEstimateError

    def boom(*_a, **_kw):
        raise CostEstimateError("일부러 터뜨린 lint")

    monkeypatch.setattr(O, "assess_redevelopment", boom)

    cand = _pipeline_candidate(1, "재건축단지",
                               redevelopment=_project("조합설립", STAGE_ASSOCIATION))
    out = run_mvp_pipeline(_pipeline_ctx([cand]), llm=None)

    # ① 추천이 사라지지 않는다.
    assert len(out["items"]) == 1
    top = out["items"][0]
    assert top["est_price_krw"]                      # 가격 근거는 그대로다
    # ② 재건축 블록만 '판정 보류'로 내려간다 — **미확보와 문구가 다르다**.
    redev = top["redevelopment"]
    assert redev["available"] is False
    assert redev["detail"]["cost_guard_blocked"] is True
    assert "판정하지 못했다" in " ".join(redev["missing"])
    # ③ '정비사업이 없다'로 읽히면 안 된다.
    assert "뜻이 아니라" in " ".join(redev["missing"])
    # ④ 조용히 넘어가지 않는다 — 결과 notes 에 몇 건인지 적힌다.
    assert any("내부 금액 검사" in n and "1건" in n for n in out["notes"]), out["notes"]


# ---------------------------------------------------------------------------
# SR27-1 / CR32-4 — **막은 금액을 오류 메시지로 되돌려 주지 않는다**
#
# 가드가 발화하면 예전에는 `detail["cost_guard_error"]` 에 예외 문자열이 실렸고,
# 그 문자열은 `주제어 '분담' + 금액 '1억 2천만 원'` 처럼 **막은 값을 그대로 인용**해
# 사용자 카드까지 나갔다(실측). 방어의 실패 경로가 정확히 방어 대상을 보여 주는,
# SR-025 가 422 `input` 을 지우며 한 번 닫았던 패턴이다.
# ---------------------------------------------------------------------------

#: 발화용 수집값. 카드 어디에도 남으면 안 되는 금액 토큰을 품고 있다.
_MONEY_ZONE = "추가분담금 1억 2천만 원 예상구역"
_MONEY_TOKENS = ("1억 2천만 원", "1억 ", "2천만 원", "1억", "2천만")


def _fire_cost_guard(monkeypatch, zone_name=_MONEY_ZONE):
    """**현실 경로**로 가드를 발화시킨다 — 새 외부 필드를 문장에 끼우고
    `_source_quotes` 갱신을 잊은 상태(= docstring 이 대비한다고 말한 회귀)를 만든다.

    가짜 예외를 주입하지 않는 이유: 실제 lint 메시지의 **모양**(금액을 인용한다)이
    이 테스트의 대상이기 때문이다. 지어낸 메시지로는 그 성질을 고정하지 못한다.
    """
    from app.agents.orchestrator import run_mvp_pipeline
    from app.domain.redevelopment import analysis as A

    monkeypatch.setattr(A, "_source_quotes", lambda project: ())
    cand = _pipeline_candidate(
        1, "재건축단지",
        redevelopment=_project("조합설립", STAGE_ASSOCIATION, zone_name=zone_name))
    return run_mvp_pipeline(_pipeline_ctx([cand]), llm=None)


def test_강등_카드_어디에도_차단한_금액이_남지_않는다(monkeypatch):
    """★ 변이 가드 — `detail` 에 `cost_guard_error` 를 되살리면 여기서 죽는다.

    카드 JSON **전체**를 훑는다. 특정 키만 보면 다음 사람이 다른 키로 같은 값을
    싣는 순간 조용히 통과한다.
    """
    import json

    out = _fire_cost_guard(monkeypatch)
    redev = out["items"][0]["redevelopment"]

    # ① 발화는 실제로 일어났다(테스트가 자기충족이 되지 않게 먼저 확인).
    assert redev["detail"]["cost_guard_blocked"] is True
    # ② 진단문 키 자체가 없다.
    assert "cost_guard_error" not in redev["detail"], redev["detail"]
    # ③ 응답 전체에 금액 토큰이 없다 — 어느 키로도.
    blob = json.dumps(out, ensure_ascii=False, default=str)
    for token in _MONEY_TOKENS:
        assert token not in blob, f"차단한 금액 {token!r} 이 응답에 남아 있습니다"
    # 수집 원문(구역명)도 함께 사라진다 — 강등 카드는 그 구역을 인용하지 않는다.
    assert _MONEY_ZONE not in blob


def test_금액을_지우되_조용해지지는_않는다(monkeypatch, caplog):
    """막았다는 **사실**은 세 곳에 남는다 — 사용자 문구 · 결과 notes · 운영 로그.

    "응답에서 뺐다"가 "아무 일도 없었던 것처럼 보인다"가 되면 그건 조용한 실패다.
    """
    import logging

    with caplog.at_level(logging.ERROR, logger="agents"):
        out = _fire_cost_guard(monkeypatch)

    redev = out["items"][0]["redevelopment"]
    # ① 사용자: '없다'가 아니라 '판정하지 못했다'.
    assert redev["available"] is False
    assert redev["verdict"] == "정비사업 판정 보류"
    assert "판정하지 못했다" in " ".join(redev["missing"])
    # ② 결과 notes: 몇 건인지 적힌다.
    assert any("내부 금액 검사" in n and "1건" in n for n in out["notes"]), out["notes"]
    # ③ 운영자: 원인(주제어·금액)이 로그에는 남는다 — 여기까지 지우면 고칠 수 없다.
    logged = "\n".join(r.getMessage() + (str(r.exc_info[1]) if r.exc_info else "")
                       for r in caplog.records)
    assert "분담금 검사에 걸려" in logged
    assert "1억 " in logged, "원인 문자열이 로그에도 없으면 운영자가 고칠 수 없다"


def test_Finding_변환에서_걸려도_추천은_살아남는다(monkeypatch):
    """판정은 통과했는데 Finding 변환에서 걸리는 경로도 같은 대우를 받는다.

    (여기서 안 잡으면 카드에는 재건축 블록이 있는데 findings 에는 없는 반쪽 결과가 난다.)
    """
    from app.agents import orchestrator as O
    from app.agents.orchestrator import run_mvp_pipeline
    from app.domain.redevelopment.analysis import CostEstimateError

    real = O.redevelopment_finding
    calls = {"n": 0}

    def flaky(assessment):
        calls["n"] += 1
        if calls["n"] == 1:
            raise CostEstimateError("변환 단계에서 터뜨림")
        return real(assessment)

    monkeypatch.setattr(O, "redevelopment_finding", flaky)

    cand = _pipeline_candidate(1, "재건축단지",
                               redevelopment=_project("조합설립", STAGE_ASSOCIATION))
    out = run_mvp_pipeline(_pipeline_ctx([cand]), llm=None)

    assert len(out["items"]) == 1
    top = out["items"][0]
    assert top["redevelopment"]["available"] is False
    # 카드의 findings 에도 재건축 에이전트가 '판단 보류'로 남아 있다(사라지지 않는다).
    agents = {f["agent_id"] for f in top["findings"]}
    assert "redevelopment-analyst" in agents


def test_강등되지_않은_경우에는_그_고지가_뜨지_않는다():
    """늘 뜨는 고지는 읽히지 않는다 — 정상 경로에는 붙지 않아야 한다."""
    from app.agents.orchestrator import run_mvp_pipeline

    cand = _pipeline_candidate(1, "재건축단지",
                               redevelopment=_project("조합설립", STAGE_ASSOCIATION))
    out = run_mvp_pipeline(_pipeline_ctx([cand]), llm=None)
    assert not any("내부 금액 검사" in n for n in out["notes"]), out["notes"]


def test_새_외부필드를_문장에_끼우면_인용목록에도_있어야_한다():
    """★ 구조 가드 — rationale 에 보간되는 수집 값은 전부 `source_quotes` 에 있어야 한다.

    이 검사가 없으면 다음 사람이 문장에 새 외부 필드를 끼우고 `_source_quotes` 갱신을
    잊는다. 그러면 그 필드가 조용히 '우리가 쓴 말'로 취급돼 CR31-1 이 재현된다.
    """
    project = _project("조합설립(추정 5000만원)", STAGE_ASSOCIATION,
                       zone_name="1억원지구", sigungu="수원시 장안구",
                       raw_biz_type="주택정비형재개발")
    out = assess_redevelopment(project, purpose=PURPOSE_LIVE, as_of=TODAY)

    for value in (project.zone_name, project.sigungu, project.raw_stage):
        if value and value in out.rationale:
            assert value in out.source_quotes, (
                f"{value!r} 가 rationale 에 인용되는데 source_quotes 에 없습니다 — "
                "app/domain/redevelopment/analysis.py::_source_quotes 를 갱신하세요")
