"""부동산원 단지 마스터 파싱·매칭 — **애매하면 매칭하지 않는다**를 못박는 테스트.

왜 이 파일이 따로 있나
----------------------
REB-1 은 GEO-1 직후의 작업이다. GEO-1 이 "틀린 좌표는 좌표 없음보다 나쁘다"로 정리됐는데,
매칭이 느슨하면 **틀린 좌표를 더 그럴듯한 경로로** 다시 만들어 낸다. 매칭이 틀리면
좌표뿐 아니라 동수·세대수·사용승인일까지 통째로 남의 단지 것이 붙는다.

여기 있는 사례는 대부분 운영 DB·부동산원 실파일(2026-07-26)에서 뽑았다.
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.ingest.reb import (
    REB_NAME_SIMILARITY,
    RebBuilding,
    RebComplex,
    address_is_mountain,
    decode_csv,
    dong_label,
    match_complex,
    parse_basic_csv,
    parse_dong_csv,
    parse_pnu,
)

BASIC_HEADER = ("단지고유번호,필지고유번호,주소,단지명_공시가격,단지명_건축물대장,"
                "단지명_도로명주소,단지종류,동수,세대수,사용승인일")
DONG_HEADER = "단지고유번호,동명_공시가격,동명_건축물대장,동명_도로명주소,지상층수"


def _reb(reb_id: str, *names: str, dong: str = "1168010100",
         main: int = 977, sub: int = 0, kind: str = "1") -> RebComplex:
    padded = (list(names) + ["", "", ""])[:3]
    return RebComplex(reb_id=reb_id,
                      parcel_id=f"{dong}1{main:04d}{sub:04d}",
                      name_price=padded[0], name_ledger=padded[1], name_road=padded[2],
                      kind=kind)


# ---------------------------------------------------------------------------
# 필지고유번호(PNU)
# ---------------------------------------------------------------------------

def test_pnu는_법정동코드와_본번_부번으로_쪼개진다():
    """PNU 19 = 법정동코드(10) + 산여부(1) + 본번(4) + 부번(4). 실파일 '청운동 56-45'."""
    parts = parse_pnu("1111010100100560045")
    assert parts is not None
    assert parts.legal_dong_code == "1111010100"
    assert parts.sigungu_code == "11110"
    assert (parts.main_no, parts.sub_no) == (56, 45)
    assert parts.is_mountain is False


def test_산번지_pnu():
    parts = parse_pnu("1129013300200870085")          # 성북구 정릉동 산87-85
    assert parts is not None and parts.is_mountain is True


@pytest.mark.parametrize("bad", ["", "12345", "1111010100X00560045", "1" * 20])
def test_형식이_아니면_추측하지_않는다(bad):
    assert parse_pnu(bad) is None


@pytest.mark.parametrize("address, mountain", [
    ("서울특별시 성북구 정릉동 산87-85", True),
    ("서울특별시 종로구 청운동 56-45", False),
    ("경기도 군포시 산본동 1102", False),              # '산본동' 에 걸리면 안 된다
])
def test_주소의_산번지_표기(address, mountain):
    assert address_is_mountain(address) is mountain


# ---------------------------------------------------------------------------
# CSV 파싱
# ---------------------------------------------------------------------------

def test_기본정보_한줄을_읽는다():
    text = (BASIC_HEADER + "\n"
            '"11110200000003","1111010100100010000","서울특별시 종로구 청운동 1",'
            '"청운벽산빌리지",,"청운벽산빌리지","2",9,126,"1988-11-11"\n')
    rows = parse_basic_csv(text)
    assert len(rows) == 1
    c = rows[0]
    assert c.reb_id == "11110200000003"
    assert c.legal_dong_code == "1111010100"
    assert c.names == ("청운벽산빌리지",)              # 빈 이름·중복은 접는다
    assert (c.building_count, c.household_count) == (9, 126)
    assert c.approved_on == dt.date(1988, 11, 11)


def test_사용승인일이_결측이면_None():
    """실파일에 '--' 가 5건 있다. 날짜를 지어내면 건축연도가 통째로 거짓이 된다."""
    text = (BASIC_HEADER + "\n"
            '"1","1111010100100010000","주소","가",,,"1",1,1,"--"\n')
    assert parse_basic_csv(text)[0].approved_on is None


def test_pnu가_깨진_행은_버린다():
    text = (BASIC_HEADER + "\n"
            '"1","깨짐","주소","가",,,"1",1,1,"2000-01-01"\n')
    assert parse_basic_csv(text) == []


def test_컬럼이_바뀌면_조용히_넘어가지_않는다():
    """배포 형식이 바뀌었는데 0건을 적재하고 '성공'이라 말하면 원인을 못 찾는다."""
    with pytest.raises(ValueError, match="컬럼"):
        parse_basic_csv("아무거나,컬럼\n1,2\n")


def test_인코딩을_판별하지_못하면_실패한다():
    """errors='replace' 로 넘어가면 깨진 이름이 적재되고 매칭이 전부 실패한다."""
    with pytest.raises(ValueError, match="인코딩"):
        decode_csv(b"no korean here at all")
    assert decode_csv("단지고유번호,x\n".encode("cp949")).startswith("단지고유번호")
    assert decode_csv("단지고유번호,x\n".encode("utf-8-sig")).startswith("단지고유번호")


def test_동정보를_읽는다():
    text = (DONG_HEADER + "\n"
            "11110100000004,청운현대(아)101동,,,5\n"
            "11110100000004,,,,5\n")
    rows = parse_dong_csv(text)
    assert [r.label for r in rows] == ["101동", None]
    assert rows[0].floors == 5


# ---------------------------------------------------------------------------
# 동(棟) 표기 — 읽히는 것만 인정한다
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, label", [
    ("101", "101동"),                     # 실파일에서 가장 흔한 표기
    ("제101", "101동"),
    ("청운현대(아)101동", "101동"),
    ("0101", "101동"),                    # 앞의 0 은 표기 차이일 뿐
    ("가", "가동"),
    ("가동", "가동"),
    ("A", "A동"),
])
def test_동_표기를_정규화한다(raw, label):
    assert dong_label(raw) == label


@pytest.mark.parametrize("raw", ["", "미도파당주빌딩", "도렴구역 제18지구", "경비실",
                                 "주건축물제1", "아파트"])
def test_읽을_수_없는_동_표기는_버린다(raw):
    """⚠️ 동수(개수)를 아는 것과 동 목록을 아는 것은 다르다.

    개수만큼 '101동…105동'을 지어내면 F4 동별 실측이 거짓 근거 위에서 돈다.
    """
    assert dong_label(raw) is None


def test_동이_하나도_안읽히면_label은_None():
    assert RebBuilding(reb_id="1", name_price="", name_ledger="", name_road="").label is None
    assert RebBuilding(reb_id="1", name_price="", name_ledger="101").label == "101동"


# ---------------------------------------------------------------------------
# 매칭 — 애매하면 매칭하지 않는다 (이 파일의 핵심)
# ---------------------------------------------------------------------------

def test_이름이_같으면_매칭된다():
    r = match_complex("래미안블레스티지", [_reb("A", "래미안블레스티지")])
    assert r.matched and r.reb_id == "A" and r.method == "name_exact"


def test_동목록이_붙은_MOLIT_이름도_매칭된다():
    """'대치우성아파트1동,2동,3동' — GEO-1 미확보 749건의 전형적인 형태."""
    r = match_complex("대치우성아파트1동,2동,3동", [_reb("A", "대치우성아파트")])
    assert r.matched and r.method == "name_exact"


def test_차수를_모르는_이름은_차수있는_단지에_붙지_않는다():
    """⛔ REB-1 의 핵심 회귀 방지 — ORDER 가 든 '가락동 우성' 사례.

    '우성' 만으로는 '가락우성1차' 인지 '2차' 인지 알 수 없다. 하나를 골라 붙이면
    좌표·동수·세대수·사용승인일이 통째로 남의 단지 것이 된다.
    차수 규칙이 애매 판정보다 먼저 잡으므로 결과는 'unmatched' 다 — 어느 쪽이든
    **아무것도 쓰지 않는다**는 것이 요점이다.
    """
    r = match_complex("우성", [_reb("A", "가락우성1차"), _reb("B", "가락우성2차")])
    assert not r.matched and r.reb_id == ""


def test_같은_법정동에_같은_이름이_둘이면_애매다():
    """표기만 다르고 이름이 같은 별개 단지 — 어느 쪽인지 고를 근거가 없다."""
    r = match_complex("삼성래미안", [_reb("A", "삼성래미안"), _reb("B", "삼성래미안아파트")])
    assert r.status == "ambiguous"
    assert r.reb_id == "" and r.method == "name_exact"
    assert set(r.rivals) == {"A", "B"}


def test_애매하면_더_느슨한_단계로_내려가지_않는다():
    """⛔ 포함 단계에서 둘이 걸렸는데 유사도 단계에서 하나만 남는다고 붙이면 안 된다.

    아래 후보는 포함 단계에서 둘 다 걸리고, 유사도 단계에서는 'A' 하나만 남는다
    ('대치우성아' 0.89 · '대치우성빌라디움' 0.67). 내려가면 A 로 매칭되지만,
    **하나만 남았다는 건 근거가 아니라 임계값이 만든 우연**이다.
    """
    r = match_complex("대치우성", [_reb("A", "대치우성아"), _reb("B", "대치우성빌라디움")])
    assert r.status == "ambiguous"
    assert r.method == "name_contains"


def test_한_단지가_여러_필지로_갈라져_있으면_매칭하지_않는다():
    """실파일 신교동: '우정(101동)'(6-13)·'우정(102동)'(6-11) 이 별개 단지로 등재돼 있다.

    둘 다 '우정아파트' 라 어느 필지가 우리 단지인지 고를 수 없다 — 좌표가 필지 단위라
    아무거나 고르면 틀린 필지에 찍힌다.
    """
    r = match_complex("우정", [_reb("A", "우정(101동)", "우정아파트", main=6, sub=13),
                               _reb("B", "우정(102동)", "우정아파트", main=6, sub=11)])
    assert r.status == "ambiguous"


def test_차수가_다르면_다른_단지다():
    """'신현대11차' ≠ '신현대12차' — 좌표 채택 규칙(geocode.same_complex)과 같은 기준."""
    r = match_complex("신현대12차", [_reb("A", "신현대11차"), _reb("B", "신현대12차")])
    assert r.matched and r.reb_id == "B"


def test_차수가_없는_이름은_차수가_있는_이름과_붙지_않는다():
    """'신세계' 를 '신세계3차' 에 붙이면 다른 단지가 된다(GEO-1 실측 9건 유형)."""
    assert match_complex("신세계", [_reb("A", "신세계3차")]).status == "unmatched"


def test_후보가_없으면_실패():
    assert match_complex("아무거나", []).status == "unmatched"
    assert match_complex("", [_reb("A", "가")]).status == "unmatched"


def test_부동산원_이름_셋을_모두_본다():
    """공시가격 이름에는 동이 섞여 오고, 정식 명칭은 건축물대장 쪽인 경우가 많다."""
    r = match_complex("청운현대", [_reb("A", "청운현대(아)104동", "청운현대아파트")])
    assert r.matched and r.method == "name_exact"


def test_같은_단지의_행이_여러개여도_단지고유번호가_같으면_애매가_아니다():
    """부동산원 파일에 표기만 다른 같은 단지 행이 겹쳐 들어오는 경우."""
    a1 = _reb("A", "청운현대아파트")
    a2 = _reb("A", "청운현대")
    r = match_complex("청운현대", [a1, a2])
    assert r.matched and r.reb_id == "A"


def test_유사도_단계는_좌표채택보다_엄격하다():
    """매칭이 틀리면 좌표만이 아니라 동수·세대수·사용승인일까지 남의 것이 붙는다."""
    assert REB_NAME_SIMILARITY > 0.80
    # 0.80~0.88 구간(좌표 채택은 통과하지만 매칭은 통과하면 안 되는 이름)
    assert match_complex("무지개마을4단지", [_reb("A", "무지개마을청구")]).status == "unmatched"
    assert match_complex("우성2", [_reb("A", "우성5")]).status == "unmatched"
