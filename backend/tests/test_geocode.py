"""지오코딩 검증 — **틀린 좌표를 넣지 않는다**를 못박는 테스트.

왜 이 파일이 따로 있나
----------------------
CR-020 GEO-1(high): 지오코딩이 카카오 응답 1위를 검증 없이 저장해, 운영 DB 6,538개 중
**다른 단지와 좌표가 완전히 같은 단지 514건(7.9%)** 을 만들었다. 그중 **68건은 법정동까지
달랐다**(역삼동/도곡동/서초동 '대우디오빌' 계열 4건이 한 점). 확보율 93.6% 가 그 결함을
덮고 있었다.

여기 있는 테스트는 전부 **그 실데이터에서 뽑은 사례**다. 하나라도 깨지면
좌표 오염이 다시 새기 시작한 것이다. 특히:

- `test_다른_법정동_동명단지는_좌표를_공유하지_않는다` — 68건 cross-dong 회귀 방지
- `test_시공사_표기는_변형에서_떼지_않는다`       — '탑마을(경남)1' 4개 뭉침 회귀 방지
- `test_좌표충돌은_채택하지_않고_센다`            — 충돌 차단·계수 회귀 방지
"""
from __future__ import annotations

import pytest

from app.ingest.geocode import (
    APPLIABLE_METHODS,
    AddressHit,
    GeoFix,
    GeoTarget,
    KakaoAddressSearch,
    KakaoPlaceSearch,
    NullAddressSearch,
    NullGeocoder,
    NullPlaceSearch,
    Place,
    ReplayGeocoder,
    VerifiedGeocoder,
    different_parcel,
    different_reb_complex,
    dong_matches,
    enrich_geom,
    haversine_m,
    in_capital_bbox,
    name_contains,
    name_matches,
    paren_jibun,
    place_core,
    query_variants,
    same_complex,
    strip_name_noise,
    sweep_name_path,
    sweep_verdict,
    unsafe_shared_ids,
    verify,
    verify_address,
)
from app.ingest.ratelimit import RateLimiter


def _silent_clock_limiter() -> RateLimiter:
    t = [0.0]
    return RateLimiter(0.0, clock=lambda: t[0], sleeper=lambda s: None)


def _place(lon=127.05, lat=37.49, name="○○아파트", addr="서울 강남구 대치동 977") -> Place:
    return Place(lon=lon, lat=lat, place_name=name, address_name=addr)


def _target(name="○○아파트", dong="대치동", sgg="강남구", sido="서울특별시") -> GeoTarget:
    return GeoTarget(name=name, legal_dong=dong, sigungu=sgg, sido=sido)


class FakeSearch:
    """질의어 → 후보 목록. 카카오를 대신한다(네트워크 없음)."""

    def __init__(self, table: dict[str, list[Place]]) -> None:
        self.table = table
        self.calls: list[str] = []

    def search(self, query: str) -> list[Place]:
        self.calls.append(query)
        return list(self.table.get(query, []))


# ---------------------------------------------------------------------------
# 이름 정리 — 보수적으로 (통과조건 4)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, cleaned", [
    # 실측 2026-07-25: 미확보 277건 중 156건이 괄호·동목록이었다
    ("현대2차(10,11,20,23,24,25동)", "현대2차"),
    ("대치우성아파트1동,2동,3동,5동", "대치우성아파트"),
    ("럭키(963)", "럭키"),
    ("청학아파트에이동,비동,씨동", "청학아파트"),
    ("삼환나띠르빌(1002-10)", "삼환나띠르빌"),
    ("동부(101동~103동)", "동부"),
])
def test_지번과_동목록만_떼어낸다(raw, cleaned):
    assert strip_name_noise(raw) == cleaned


@pytest.mark.parametrize("raw", [
    "탑마을(경남)1",          # 시공사 — 떼면 탑마을(기산)1·(선경)1·(쌍용)1 과 한 이름이 된다
    "성산시영(대우)",         # 시공사
    "현대(관악)",             # 지역 구분자
    "은평뉴타운 제각말 푸르지오(5-1단지)",   # 단지 번호
    "무지개마을4단지(주공)",  # 시공사
])
def test_시공사_표기는_변형에서_떼지_않는다(raw):
    """⚠️ GEO-1 의 직접 원인. 괄호를 전부 떼면 다른 단지가 같은 검색어가 된다.

    야탑동 실측: '탑마을(경남)1'·'(기산)1'·'(선경)1'·'(쌍용)1' 네 단지가
    '탑마을1' 로 뭉쳐 **한 좌표**를 공유했다.
    """
    assert strip_name_noise(raw) == raw


def test_질의변형은_원본부터_그다음_정리본():
    variants = query_variants(_target(name="현대2차(10,11동)", dong="압구정동"))
    assert variants == [("압구정동 현대2차(10,11동)", "exact"),
                        ("압구정동 현대2차", "variant")]


def test_군더더기가_없으면_변형을_만들지_않는다():
    """불필요한 재시도는 카카오 쿼터만 태운다."""
    assert query_variants(_target()) == [("대치동 ○○아파트", "exact")]


def test_단지명이_통째로_사라지면_변형하지_않는다():
    """'(103동)' 을 떼면 '대치동' 만 남아 동 전체 중심에 좌표가 찍힌다 — 틀린 좌표."""
    assert query_variants(_target(name="(103동)")) == [("대치동 (103동)", "exact")]


# ---------------------------------------------------------------------------
# 결과 검증 (통과조건 1·2)
# ---------------------------------------------------------------------------

def test_법정동이_다르면_불합격():
    """실측 사례: '도곡동 대우디오빌' 질의에 역삼동 좌표가 돌아왔다."""
    place = _place(name="대우디오빌", addr="서울 강남구 역삼동 736-24")
    assert dong_matches(place, "역삼동") is True
    assert dong_matches(place, "도곡동") is False
    assert verify(place, _target(name="대우디오빌", dong="도곡동")) is False


def test_당산동4가와_5가는_다른_동이다():
    """실측 사례: 당산동4가 '당산반도유보라팰리스' 와 당산동5가 '반도유보라' 가 한 점."""
    place = _place(name="반도유보라", addr="서울 영등포구 당산동5가 42")
    assert dong_matches(place, "당산동5가") is True
    assert dong_matches(place, "당산동4가") is False


def test_읍면_지역은_읍면과_리를_둘_다_요구한다():
    """GEO-8 — MOLIT 은 읍·면에서 '오남읍 오남리' 처럼 두 토막으로 준다.

    예전 구현(`dong in addr.split()`)은 두 토막짜리 이름이 **어떤 주소와도** 같아질
    수 없어, 경기 외곽 읍·면 단지 1,009건이 전부 불합격 → 좌표 없음이었다.
    """
    place = _place(name="○○아파트", addr="경기 남양주시 오남읍 오남리 588")
    assert dong_matches(place, "오남읍 오남리") is True
    # 느슨해진 게 아니다 — 두 토막을 **둘 다** 요구한다.
    assert dong_matches(place, "진접읍 오남리") is False
    assert dong_matches(place, "오남읍 양지리") is False


def test_지번주소가_없으면_불합격():
    """대조할 수 없으면 채택하지 않는다 — 모르는 건 모른다고 둔다."""
    assert dong_matches(Place(127.0, 37.5, "○○아파트", ""), "대치동") is False


def test_시군구가_다르면_불합격():
    place = _place(name="○○아파트", addr="서울 송파구 대치동 977")
    assert verify(place, _target()) is False


def test_수도권_밖_좌표는_불합격():
    """부산 동명이인 단지 같은 이상치를 마지막에 거른다."""
    assert in_capital_bbox(129.07, 35.17) is False
    assert in_capital_bbox(127.05, 37.49) is True
    far = _place(lon=129.07, lat=35.17, addr="서울 강남구 대치동 977")
    assert verify(far, _target()) is False


@pytest.mark.parametrize("mine, theirs, ok", [
    ("래미안블레스티지", "래미안블레스티지", True),
    ("대치우성아파트1동,2동", "대치우성아파트", True),      # 동목록 제거 후 일치
    ("목동이-편한세상", "목동 이편한세상", True),           # 기호·공백 차이
    ("샹그레빌아파트", "샹그레빌", True),                   # '아파트' 표기 차이
    # 카카오가 돌려주는 실제 표기들 — 내 이름만 정리하고 저쪽은 날것으로 두면 다 놓친다
    ("반포훼미리(102동)", "반포훼밀리아파트 102동", True),
    ("가락우성", "가락우성아파트 상가", True),
    ("목동삼성", "목동삼성아파트 관리사무소", True),
    # 다른 단지 — 붙이면 안 되는 것들
    ("서초아파트", "서초그랑자이", False),                  # 실측 충돌쌍
    ("우성2", "우성5", False),                              # 숫자 하나가 단지를 가른다
    ("무지개마을4단지", "무지개마을청구", False),           # 구미동 무지개 뭉침 사례
    ("탑마을(경남)1", "탑마을선경아파트", False),
    ("태강아파트(아이파크)", "아이파크 공인중개사사무소", False),
    ("가락동현대", "현대자동차블루핸즈 가락점", False),
])
def test_단지명_대조(mine, theirs, ok):
    assert name_matches(mine, theirs) is ok


@pytest.mark.parametrize("mine, theirs", [
    # 운영 DB 실측(CR-021 GEO-4): 같은 법정동에서 차수만 다른 685쌍이 채택 단계를 통과했다.
    # 유사도가 임계값(0.80) 위라 퍼지 매칭이 이들을 '같은 단지'로 받아들였다.
    ("신현대12차", "신현대11차아파트"),                     # 압구정동 0.833
    ("현대14차(203,204,205,206동)", "현대13차"),            # 압구정동 0.800
    ("두산위브2단지", "두산위브1단지"),                     # 논현동 0.857
    ("무지개마을4단지", "무지개마을3단지아파트"),
])
def test_차수가_다르면_채택하지_않는다(mine, theirs):
    """차수 가드는 `same_complex`(공유)·`reb._hit`(매칭)뿐 아니라 **채택 단계에도** 있어야 한다.

    충돌 게이트는 소수점 6자리 완전 일치만 잡는다 — 카카오가 옆 단지의 다른 출입구
    좌표를 주면 몇 m 어긋난 채 그대로 들어간다. 그때는 막을 방법이 없다.
    """
    assert name_matches(mine, theirs) is False


@pytest.mark.parametrize("mine, theirs", [
    ("신현대11차", "신현대아파트 11차"),                    # 같은 차수 — 표기만 다르다
    ("목동2차삼성래미안", "목동2차삼성래미안아파트 경비실"),
])
def test_차수가_같으면_표기가_달라도_채택한다(mine, theirs):
    """가드는 **차수가 다를 때만** 막는다 — 멀쩡한 좌표까지 버리면 안 된다."""
    assert name_matches(mine, theirs) is True


def test_차수가_다른_이웃단지_좌표는_채택되지_않는다():
    """채택 경로 끝단(enrich_geom)까지 확인 — 법정동·시군구는 둘 다 통과하는 상황이다."""
    place = _place(lon=127.028000, lat=37.527000, name="신현대11차아파트",
                   addr="서울 강남구 압구정동 402")
    search = FakeSearch({"압구정동 신현대12차": [place]})
    res = enrich_geom([(1, _target(name="신현대12차", dong="압구정동"))],
                      VerifiedGeocoder(search), lambda *a: None, occupied={})

    assert res.resolved == 0 and res.rejected_mismatch == 1


def test_부속시설_장소는_단지명으로_대조한다():
    """단지 부지 안의 POI 라 좌표는 쓸 만하다 — 이름만 보고 버리지 않는다."""
    assert place_core("반포훼밀리아파트 경비실") == "반포훼밀리아파트"
    assert place_core("목동2차삼성래미안아파트입주자대표회의-2 전기차충전소") \
        == "목동2차삼성래미안아파트"
    assert place_core("서초더샵오데움1단지아파트 주차장입구") == "서초더샵오데움1단지아파트"


def test_검증_통과하면_좌표를_채택한다():
    assert verify(_place(), _target()) is True


# ---------------------------------------------------------------------------
# VerifiedGeocoder — 1위를 믿지 않는다
# ---------------------------------------------------------------------------

def test_1위가_틀리면_다음_후보를_본다():
    """size=1 로 1위만 받던 게 GEO-1 의 뿌리였다. 이제 상위 N 을 훑는다."""
    search = FakeSearch({"대치동 ○○아파트": [
        _place(lon=127.1, lat=37.5, name="○○아파트", addr="서울 강남구 역삼동 1"),  # 동 불일치
        _place(lon=127.2, lat=37.6, name="△△빌딩", addr="서울 강남구 대치동 2"),   # 이름 불일치
        _place(lon=127.056, lat=37.494, name="○○아파트", addr="서울 강남구 대치동 977"),
    ]})
    fix = VerifiedGeocoder(search).locate(_target())
    assert fix is not None
    assert (fix.lon, fix.lat) == (127.056, 37.494)
    assert fix.confidence == "exact"


def test_아무_후보도_검증을_통과하지_못하면_비운다():
    """확보율을 올리려고 아무거나 집지 않는다 — 좌표 없음이 틀린 좌표보다 낫다."""
    search = FakeSearch({"도곡동 대우디오빌": [
        _place(name="대우디오빌", addr="서울 강남구 역삼동 736-24")]})
    geo = VerifiedGeocoder(search)
    assert geo.locate(_target(name="대우디오빌", dong="도곡동")) is None
    assert geo.last_reason == "mismatch"       # '검색 0건' 과 구분해서 보고한다


def test_원본이_실패할_때만_변형을_쓰고_variant로_표시한다():
    search = FakeSearch({"압구정동 현대2차": [
        _place(lon=127.02, lat=37.52, name="현대2차아파트", addr="서울 강남구 압구정동 429")]})
    fix = VerifiedGeocoder(search).locate(
        _target(name="현대2차(10,11동)", dong="압구정동"))
    assert fix is not None and fix.confidence == "variant"
    assert search.calls == ["압구정동 현대2차(10,11동)", "압구정동 현대2차"]


def test_검색이_0건이면_이유를_no_result로_남긴다():
    geo = VerifiedGeocoder(NullPlaceSearch())
    assert geo.locate(_target()) is None
    assert geo.last_reason == "no_result"


def test_null_geocoder는_항상_None():
    assert NullGeocoder().locate(_target()) is None


# ---------------------------------------------------------------------------
# 좌표 충돌 차단 (통과조건 3) — 회귀 테스트의 핵심
# ---------------------------------------------------------------------------

def test_다른_법정동_동명단지는_좌표를_공유하지_않는다():
    """⛔ CR-020 GEO-1 회귀 방지 (실측 68건).

    역삼동 '대우디오빌' 과 도곡동 '대우디오빌' 은 이름이 같아도 **다른 단지**다.
    한 점을 둘이 쓰면 최소 하나는 틀렸다 — 뒤에 온 쪽은 채택하지 않는다.
    """
    point = _place(lon=127.02997, lat=37.49158, name="대우디오빌",
                   addr="서울 강남구 역삼동 736-24")
    # 카카오는 두 질의 모두에 같은(역삼동) 장소를 준다 — 실제로 그랬다.
    search = FakeSearch({"역삼동 대우디오빌": [point],
                         "도곡동 대우디오빌": [point]})
    geo = VerifiedGeocoder(search)

    updates: list[tuple[int, float, float, str]] = []
    res = enrich_geom(
        [(7, _target(name="대우디오빌", dong="역삼동")),
         (99, _target(name="대우디오빌", dong="도곡동"))],
        geo,
        lambda cid, fix: updates.append((cid, fix.lon, fix.lat, fix.confidence)),
        occupied={})

    assert [u[0] for u in updates] == [7]        # 도곡동 건은 좌표를 받지 못한다
    assert res.resolved == 1 and res.unresolved == 1
    # 도곡동 질의는 법정동 검증에서 이미 걸린다(충돌까지 갈 필요도 없다)
    assert res.rejected_mismatch + res.rejected_collision == 1


def test_좌표충돌은_채택하지_않고_센다():
    """같은 법정동이라도 **다른 단지**면 같은 점을 못 쓴다(서초동 자이 3형제 실측).

    이름 검증까지 통과한(둘 다 자기 이름의 장소를 받은) 뒤에도 좌표가 겹치면,
    카카오가 두 단지를 한 점으로 준 것이다 — 뒤에 온 쪽은 비운다.
    """
    lon, lat = 127.03887, 37.50677
    search = FakeSearch({
        "서초동 서초자이": [_place(lon=lon, lat=lat, name="서초자이",
                                   addr="서울 서초구 서초동 1350")],
        "서초동 서초그랑자이": [_place(lon=lon, lat=lat, name="서초그랑자이",
                                       addr="서울 서초구 서초동 1355")],
    })
    res = enrich_geom(
        [(1, _target(name="서초자이", dong="서초동", sgg="서초구")),
         (2, _target(name="서초그랑자이", dong="서초동", sgg="서초구"))],
        VerifiedGeocoder(search), lambda *a: None, occupied={})

    assert res.resolved == 1
    assert res.rejected_collision == 1
    assert res.samples and "충돌" in res.samples[0]


def test_시공사가_다른_동명단지는_이름검증에서_먼저_걸린다():
    """야탑동 '탑마을(경남)1'·'(기산)1'·'(선경)1'·'(쌍용)1' 4개 뭉침 사례.

    괄호 안 시공사를 남기니 '탑마을선경아파트' 장소가 '탑마을(경남)1' 의 좌표로
    채택되지 않는다 — 충돌 차단까지 가기 전에 이름 대조가 잡는다.
    """
    point = _place(lon=127.13, lat=37.41, name="탑마을선경아파트",
                   addr="경기 성남시 분당구 야탑동 341")
    search = FakeSearch({"야탑동 탑마을(선경)1": [point],
                         "야탑동 탑마을(경남)1": [point]})
    yatap = dict(dong="야탑동", sgg="성남시 분당구", sido="경기도")
    res = enrich_geom(
        [(1, _target(name="탑마을(선경)1", **yatap)),
         (2, _target(name="탑마을(경남)1", **yatap))],
        VerifiedGeocoder(search), lambda *a: None, occupied={})

    assert res.resolved == 1                 # 선경만 채택
    assert res.rejected_mismatch == 1        # 경남은 이름 대조에서 탈락


def test_같은_단지가_이름만_갈라진_경우는_좌표를_공유한다():
    """'대치우성아파트1동,2동' ~ '대치우성' 은 동 나열만 다른 한 단지다.

    이런 것까지 막으면 멀쩡한 단지가 지도에서 사라진다 — 충돌과 구분해서 센다.

    ⚠️ 2026-07-26 GEO-6: 예전에는 이 자리에 '삼환나띠르빌(1002-10)' ~ '(1002-11)' 을
       썼다. 부동산원 마스터가 그 표기들이 **각각 다른 단지고유번호**임을 보여줘
       사례를 바꿨다(같은 파일 아래 `test_괄호_지번이_다르면_...` 참조).
    """
    point = _place(lon=127.06, lat=37.49, name="대치우성아파트",
                   addr="서울 강남구 대치동 977")
    search = FakeSearch({q: [point] for q in
                         ("대치동 대치우성아파트1동,2동", "대치동 대치우성")})
    res = enrich_geom(
        [(1, _target(name="대치우성아파트1동,2동")),
         (2, _target(name="대치우성"))],
        VerifiedGeocoder(search), lambda *a: None, occupied={})

    assert res.resolved == 2
    assert res.rejected_collision == 0
    assert res.shared_point == 1


@pytest.mark.parametrize("a, b, expected", [
    # ⚠️ GEO-6: '삼환나띠르빌(1002-10)'/'(1002-22)' 는 여기 있었지만 **다른 단지**다.
    (("대치우성아파트1동,2동", "대치동"), ("대치우성", "대치동"), True),
    (("롯데캐슬(1057-0)", "신월동"), ("수명산롯데캐슬", "신월동"), True),
    (("청담2차이-편한세상(204동)", "청담동"), ("청담2차이-편한세상(205동)", "청담동"), True),
    (("탑마을(경남)1", "야탑동"), ("탑마을(기산)1", "야탑동"), False),
    (("대우디오빌", "역삼동"), ("대우디오빌", "도곡동"), False),   # 법정동이 다르면 끝
    (("서초자이", "서초동"), ("서초그랑자이", "서초동"), False),
    # 포함만 보면 '신세계' ⊂ '신세계3차' 라 통과한다 — 차수는 단지를 가르는 정보다
    (("신세계", "내발산동"), ("신세계3차101동", "내발산동"), False),
    (("우남퍼스트빌", "신사동"), ("우남퍼스트빌2차", "신사동"), False),
])
def test_같은_단지_판정(a, b, expected):
    ta = GeoTarget(name=a[0], legal_dong=a[1])
    tb = GeoTarget(name=b[0], legal_dong=b[1])
    assert same_complex(ta, tb) is expected


def test_기존_좌표도_충돌_기준선이_된다():
    """DB 에 이미 있는 좌표(load_occupied)를 무시하면 배치마다 같은 점에 다시 뭉친다."""
    point = _place(lon=127.0, lat=37.5, name="서초그랑자이", addr="서울 서초구 서초동 1350")
    occupied = {(127.0, 37.5): (11, GeoTarget(name="서초자이", legal_dong="서초동"))}
    res = enrich_geom(
        [(22, _target(name="서초그랑자이", dong="서초동", sgg="서초구"))],
        VerifiedGeocoder(FakeSearch({"서초동 서초그랑자이": [point]})),
        lambda *a: None, occupied=occupied)
    assert res.resolved == 0 and res.rejected_collision == 1


# ---------------------------------------------------------------------------
# 카카오 어댑터
# ---------------------------------------------------------------------------

def test_kakao_는_x경도_y위도_순서로_돌려준다():
    """x=경도(lon), y=위도(lat). 뒤집으면 지도에서 바다에 찍힌다."""
    seen: dict[str, str] = {}

    def fake_get(url, headers, params):
        assert headers["Authorization"].startswith("KakaoAK ")
        seen.update(params)
        return {"documents": [{"x": "127.0561", "y": "37.4941",
                               "place_name": "○○아파트",
                               "address_name": "서울 강남구 대치동 977",
                               "road_address_name": "서울 강남구 도곡로 464"}]}

    places = KakaoPlaceSearch("KEY", http_get=fake_get,
                              rate_limiter=_silent_clock_limiter()).search("대치동 ○○아파트")
    assert (places[0].lon, places[0].lat) == (127.0561, 37.4941)
    assert places[0].address_name == "서울 강남구 대치동 977"
    assert seen["size"] == "5"                  # 1위만 믿지 않으려면 여러 개를 받아야 한다


def test_kakao_결과없으면_빈리스트():
    search = KakaoPlaceSearch("KEY", http_get=lambda u, h, p: {"documents": []},
                              rate_limiter=_silent_clock_limiter())
    assert search.search("없는단지") == []
    assert search.search("   ") == []           # 빈 질의는 호출도 안 함


def test_kakao_좌표가_깨진_문서는_버린다():
    def fake_get(url, headers, params):
        return {"documents": [{"place_name": "좌표없음"},
                              {"x": "127.0", "y": "37.5", "place_name": "정상"}]}

    places = KakaoPlaceSearch("KEY", http_get=fake_get,
                              rate_limiter=_silent_clock_limiter()).search("q")
    assert [p.place_name for p in places] == ["정상"]


def test_키가_없으면_생성_자체를_거부한다():
    """'도는 척' 하지 않는다 — 키 없이 조용히 0건을 내면 결함을 못 본다."""
    with pytest.raises(ValueError):
        KakaoPlaceSearch("")
    with pytest.raises(ValueError):
        KakaoAddressSearch("")


# ---------------------------------------------------------------------------
# 주소 경로 (REB-1) — **검증을 우회하지 않는다**
# ---------------------------------------------------------------------------

class FakeAddressSearch:
    """주소 → 후보 목록. 카카오 주소검색을 대신한다(네트워크 없음)."""

    def __init__(self, table: dict[str, list[AddressHit]]) -> None:
        self.table = table
        self.calls: list[str] = []

    def search(self, address: str) -> list[AddressHit]:
        self.calls.append(address)
        return list(self.table.get(address, []))


def _hit(**kw) -> AddressHit:
    base = dict(lon=126.967381, lat=37.586205, address_name="서울 종로구 청운동 56-45",
                address_type="REGION_ADDR", b_code="1111010100", main_no=56, sub_no=45,
                is_mountain=False, building_name="청운현대아파트")
    base.update(kw)
    return AddressHit(**base)


def _addr_target(**kw) -> GeoTarget:
    base = dict(name="청운현대", legal_dong="청운동", sigungu="종로구", sido="서울특별시",
                address="서울특별시 종로구 청운동 56-45", legal_dong_code="1111010100",
                main_no=56, sub_no=45, is_mountain=False, reb_id="11110100000004")
    base.update(kw)
    return GeoTarget(**base)


def test_주소경로도_법정동코드를_대조한다():
    """이름이 아니라 **코드**로 본다 — 문자열 동명 비교보다 단단하다."""
    assert verify_address(_hit(), _addr_target()) is True
    assert verify_address(_hit(b_code="1111010200"), _addr_target()) is False


def test_본번_부번이_다르면_불합격():
    """카카오가 근처 다른 지번으로 미끄러지는 걸 잡는다 — 필지가 다르면 단지가 다르다."""
    assert verify_address(_hit(main_no=57), _addr_target()) is False
    assert verify_address(_hit(sub_no=46), _addr_target()) is False


def test_동_중심점_결과는_받지_않는다():
    """⛔ address_type='REGION' 은 '지번을 못 찾아 동만 찍은' 결과다.

    이걸 받으면 한 법정동의 단지가 전부 한 점으로 뭉친다 — GEO-1 의 514건 뭉침과
    정확히 같은 실패다. ROAD(도로 자체)도 마찬가지로 받지 않는다.
    """
    assert verify_address(_hit(address_type="REGION"), _addr_target()) is False
    assert verify_address(_hit(address_type="ROAD"), _addr_target()) is False
    assert verify_address(_hit(address_type="ROAD_ADDR"), _addr_target()) is True


def test_산번지와_일반번지는_다른_필지다():
    """'정릉동 산87-85' 와 '정릉동 87-85' 는 다른 땅이다."""
    assert verify_address(_hit(is_mountain=True), _addr_target()) is False
    assert verify_address(_hit(is_mountain=True),
                          _addr_target(is_mountain=True)) is True


def test_대조할_근거가_없으면_불합격():
    """법정동코드·본번을 모르면 확인할 방법이 없다 — 모르면 넣지 않는다."""
    assert verify_address(_hit(), _addr_target(legal_dong_code="")) is False
    assert verify_address(_hit(), _addr_target(main_no=None)) is False


def test_수도권_밖_주소는_불합격():
    assert verify_address(_hit(lon=129.07, lat=35.17), _addr_target()) is False


def test_주소가_있으면_이름보다_먼저_쓴다():
    """이름 경로가 실패한 단지를 회수하는 게 목적이다 — 주소를 먼저 물어본다."""
    search = FakeSearch({})
    addr = FakeAddressSearch({"서울특별시 종로구 청운동 56-45": [_hit()]})
    fix = VerifiedGeocoder(search, addr).locate(_addr_target())

    assert fix is not None
    assert fix.confidence == "address" and fix.source == "kakao_address"
    assert (fix.lon, fix.lat) == (126.967381, 37.586205)
    assert search.calls == []                  # 이름 질의로 쿼터를 태우지 않는다


def test_주소가_검증에_떨어지면_이름_경로로_내려간다():
    """주소 경로는 **추가 기회**지 대체가 아니다. 떨어지면 기존 경로가 그대로 돈다."""
    place = _place(lon=126.9, lat=37.58, name="청운현대", addr="서울 종로구 청운동 56-45")
    search = FakeSearch({"청운동 청운현대": [place]})
    addr = FakeAddressSearch({"서울특별시 종로구 청운동 56-45": [_hit(b_code="1168010100")]})
    fix = VerifiedGeocoder(search, addr).locate(_addr_target())

    assert fix is not None and fix.confidence == "exact"
    assert fix.source == "kakao_keyword"


def test_주소가_없으면_주소검색을_부르지_않는다():
    """주소를 모르는 단지에 주소를 지어내 물어보지 않는다."""
    addr = FakeAddressSearch({})
    VerifiedGeocoder(FakeSearch({}), addr).locate(_target())
    assert addr.calls == []


def test_주소경로도_좌표충돌_차단을_탄다():
    """검증을 통과해도 **다른 단지가 쓰는 점**이면 채택하지 않는다(경로 무관)."""
    occupied = {(126.967381, 37.586205): (11, GeoTarget(name="다른단지",
                                                        legal_dong="청운동"))}
    addr = FakeAddressSearch({"서울특별시 종로구 청운동 56-45": [_hit()]})
    res = enrich_geom([(22, _addr_target())],
                      VerifiedGeocoder(NullPlaceSearch(), addr),
                      lambda *a: None, occupied=occupied)
    assert res.resolved == 0 and res.rejected_collision == 1


def test_부동산원_단지고유번호가_같으면_좌표를_공유한다():
    """MOLIT 이름 오염으로 갈라진 행들 — 이름으로는 못 붙지만 매칭 결과로는 같은 단지다.

    '대치우성아파트1동,2동,3동' 과 '대치우성' 처럼 이름 대조로 묶이지 않는 쌍도,
    둘 다 (애매하지 않게) 같은 부동산원 단지에 매칭됐다면 같은 단지다.
    """
    addr = FakeAddressSearch({"서울특별시 종로구 청운동 56-45": [_hit()]})
    geo = VerifiedGeocoder(NullPlaceSearch(), addr)
    res = enrich_geom(
        [(1, _addr_target(name="청운현대(101동,102동)")),
         (2, _addr_target(name="청운현대아파트"))],
        geo, lambda *a: None, occupied={})

    assert res.resolved == 2 and res.rejected_collision == 0
    assert res.shared_point == 1
    assert res.resolved_by_address == 2


def test_부동산원_번호가_다르면_공유하지_않는다():
    """번호가 다르면 다른 단지다 — 같은 점을 쓰면 최소 하나는 틀렸다.

    ⚠️ 이 테스트만으로는 부족하다. 이름('청운현대' vs '다른단지')이 서로 달라
       `name_contains` 단계에서 이미 거부되므로 **번호 분기를 한 번도 실행하지 않는다**
       (CR-021 이 지목한 자기충족 테스트). 번호 분기 자체는 아래
       `test_번호가_다르면_이름이_포함관계여도_공유하지_않는다` 가 못박는다.
    """
    addr = FakeAddressSearch({
        "서울특별시 종로구 청운동 56-45": [_hit()],
        "서울특별시 종로구 청운동 56-46": [_hit(address_name="서울 종로구 청운동 56-46",
                                                sub_no=46)],
    })
    res = enrich_geom(
        [(1, _addr_target()),
         (2, _addr_target(name="다른단지", reb_id="99990000000001",
                          address="서울특별시 종로구 청운동 56-46", sub_no=46))],
        VerifiedGeocoder(NullPlaceSearch(), addr), lambda *a: None, occupied={})

    assert res.resolved == 1 and res.rejected_collision == 1


# ---------------------------------------------------------------------------
# CR-021 GEO-3 — 부동산원 번호는 **부정 증거로도** 쓴다
#
# 운영 DB 실측(2026-07-26): 같은 점을 쓰면서 `reb_complex_id` 가 서로 다른 그룹이
# 15개 / 30단지 있었다. `same_complex` 가 번호 불일치를 버리고 이름 포함 판정으로
# 내려간 탓이다 — '대우디오빌' ⊂ '대우디오빌플러스' 라서 통과했다.
# ---------------------------------------------------------------------------

#: 운영 DB #7 — 강남구 역삼동 720-25 · 457세대 · reb 11680100001439
_DIOVILLE = GeoTarget(name="대우디오빌", legal_dong="역삼동", sigungu="강남구",
                      sido="서울특별시", address="서울특별시 강남구 역삼동 720-25",
                      legal_dong_code="1168010100", main_no=720, sub_no=25,
                      reb_id="11680100001439")
#: 운영 DB #74 — 강남구 역삼동 824-25 · 168세대 · reb 11680100448473
_DIOVILLE_PLUS = GeoTarget(name="대우디오빌플러스", legal_dong="역삼동", sigungu="강남구",
                           sido="서울특별시", address="서울특별시 강남구 역삼동 824-25",
                           legal_dong_code="1168010100", main_no=824, sub_no=25,
                           reb_id="11680100448473")


def test_번호가_다르면_이름이_포함관계여도_공유하지_않는다():
    """이름 대조는 **통과한다** — 그래서 번호를 부정 증거로 쓰지 않으면 뚫린다.

    지번(720-25 vs 824-25)도 세대수(457 vs 168)도 다른 별개 단지인데, 이름이
    포함관계라 `name_contains` 가 True 를 낸다. 여기서 번호가 이름을 이겨야 한다.
    """
    assert name_contains(_DIOVILLE.name, _DIOVILLE_PLUS.name) is True   # 이름은 붙는다
    assert different_reb_complex(_DIOVILLE, _DIOVILLE_PLUS) is True
    assert same_complex(_DIOVILLE, _DIOVILLE_PLUS) is False             # 번호가 이긴다


def test_번호가_다른_두_단지는_같은_점을_채택하지_못한다():
    """운영 DB 에 실제로 들어간 오좌표 재현 — 한 점(127.031112, 37.497585) 공유.

    카카오가 두 질의 모두에 같은 POI 를 돌려주면(실제로 그랬다) 두 단지가 한 점을
    쓰게 된다. 충돌 게이트가 `same_complex` 에 물어보므로, 그 판정이 틀리면
    **공유(shared_point)로 조용히 통과**한다. 여기서는 거부돼야 한다.
    """
    place = _place(lon=127.031112, lat=37.497585, name="대우디오빌",
                   addr="서울 강남구 역삼동 720-25")
    search = FakeSearch({"역삼동 대우디오빌": [place],
                         "역삼동 대우디오빌플러스": [place]})
    res = enrich_geom([(7, _DIOVILLE), (74, _DIOVILLE_PLUS)],
                      VerifiedGeocoder(search), lambda *a: None, occupied={})

    assert res.resolved == 1                 # 먼저 온 단지만 그 점을 갖는다
    assert res.shared_point == 0             # '같은 단지의 이름 변형' 이 아니다
    assert res.rejected_collision == 1


@pytest.mark.parametrize("a_name, a_reb, b_name, b_reb", [
    # 운영 DB 15그룹에서 뽑은 실사례 — 전부 이름 포함관계라 이름 대조로는 못 막는다
    ("장안현대홈타운(336)", "11230100052691", "장안현대", "11230100000183"),
    ("명수대현대", "11590100001108", "명수대", "11590100001106"),
    ("우장산롯데캐슬", "11500100050602", "우장산롯데", "11500100249017"),
    ("서초한신리빙타워", "11650100002713", "서초한신", "11650100002712"),
    ("신금호두산위브", "11200120033868", "신금호", "11200100052951"),
])
def test_운영DB_모순쌍들이_전부_다른_단지로_판정된다(a_name, a_reb, b_name, b_reb):
    a = GeoTarget(name=a_name, legal_dong="○○동", reb_id=a_reb)
    b = GeoTarget(name=b_name, legal_dong="○○동", reb_id=b_reb)
    assert same_complex(a, b) is False


def test_재판정은_잘못_공유된_점을_통째로_지목한다():
    """어느 쪽이 틀렸는지 모르므로 그룹 전체를 비운다 — 절반의 확률로 승인하지 않는다."""
    point = (127.031112, 37.497585)
    ids = unsafe_shared_ids([
        (7, _DIOVILLE, *point),
        (74, _DIOVILLE_PLUS, *point),
        (99, _addr_target(), 126.967381, 37.586205),          # 혼자 쓰는 점 — 무관
    ])
    assert ids == [7, 74]


def test_재판정은_정당한_공유를_건드리지_않는다():
    """MOLIT 이름 오염으로 갈라진 같은 단지는 계속 공유해도 된다."""
    point = (126.967381, 37.586205)
    assert unsafe_shared_ids([
        (1, _addr_target(name="청운현대(101동,102동)"), *point),
        (2, _addr_target(name="청운현대아파트"), *point),
    ]) == []


def test_재판정은_전수_쌍을_본다():
    """`enrich_geom` 은 '먼저 온 단지 vs 새 단지'만 본다 — 3개 이상 모인 점에 구멍이 있다.

    A⊂B, A⊂C 라서 채택 시점에는 둘 다 통과했지만 B 와 C 는 서로 다른 단지일 수 있다.
    """
    point = (127.02, 37.55)
    a = GeoTarget(name="롯데캐슬", legal_dong="○○동")
    b = GeoTarget(name="롯데캐슬", legal_dong="○○동", reb_id="10000000000001")
    c = GeoTarget(name="롯데캐슬리베", legal_dong="○○동", reb_id="10000000000002")

    assert same_complex(a, b) is True and same_complex(a, c) is True   # 홀더와는 통과
    assert same_complex(b, c) is False                                 # 서로는 다른 단지
    assert unsafe_shared_ids([(1, a, *point), (2, b, *point), (3, c, *point)]) == [1, 2, 3]


def test_한쪽만_번호를_알면_다르다고_단정하지_않는다():
    """'모른다'는 '다르다'가 아니다 — 미매칭 단지끼리 이름으로 붙던 경로를 막지 않는다."""
    known = GeoTarget(name="청운현대(101동,102동)", legal_dong="청운동",
                      reb_id="11110100000004")
    unknown = GeoTarget(name="청운현대아파트", legal_dong="청운동")

    assert different_reb_complex(known, unknown) is False
    assert different_reb_complex(unknown, unknown) is False   # 둘 다 모름
    assert same_complex(known, unknown) is True               # 이름으로 붙는다(기존 경로)


def test_null_주소검색은_항상_빈결과():
    assert NullAddressSearch().search("서울특별시 종로구 청운동 56-45") == []


def test_kakao_주소검색_응답을_구조로_읽는다():
    """b_code·본번·부번·주소종류를 놓치면 검증이 통째로 무력해진다."""
    seen: dict[str, str] = {}

    def fake_get(url, headers, params):
        assert url.endswith("/search/address.json")
        assert headers["Authorization"].startswith("KakaoAK ")
        seen.update(params)
        return {"documents": [{
            "address_name": "서울 종로구 청운동 56-45", "address_type": "REGION_ADDR",
            "x": "126.967381797143", "y": "37.586205890259",
            "address": {"b_code": "1111010100", "main_address_no": "56",
                        "sub_address_no": "45", "mountain_yn": "N"},
            "road_address": {"building_name": "청운현대아파트"},
        }]}

    hits = KakaoAddressSearch("KEY", http_get=fake_get,
                              rate_limiter=_silent_clock_limiter()).search(
        "서울특별시 종로구 청운동 56-45")
    assert len(hits) == 1
    got = hits[0]
    assert (got.lon, got.lat) == (126.967381797143, 37.586205890259)
    assert got.b_code == "1111010100" and got.main_no == 56 and got.sub_no == 45
    assert got.address_type == "REGION_ADDR" and got.is_mountain is False
    assert got.building_name == "청운현대아파트"
    assert seen["query"].startswith("서울특별시")


def test_kakao_주소검색_부번이_없으면_0():
    """부번 없는 지번('청운동 1')을 0 으로 정규화해야 PNU(0000)와 대조된다."""
    def fake_get(url, headers, params):
        return {"documents": [{"x": "127.0", "y": "37.5", "address_type": "REGION_ADDR",
                               "address": {"b_code": "1111010100",
                                           "main_address_no": "1",
                                           "sub_address_no": ""}}]}

    hit = KakaoAddressSearch("KEY", http_get=fake_get,
                             rate_limiter=_silent_clock_limiter()).search("q")[0]
    assert hit.main_no == 1 and hit.sub_no == 0


def test_kakao_주소검색_빈질의는_호출도_안한다():
    def boom(url, headers, params):                    # pragma: no cover - 불려선 안 된다
        raise AssertionError("빈 질의로 카카오를 부르면 안 된다")

    assert KakaoAddressSearch("KEY", http_get=boom,
                              rate_limiter=_silent_clock_limiter()).search("  ") == []


# ---------------------------------------------------------------------------
# CR-022 GEO-7 — 이름 경로 좌표를 주소 경로와 대조해 재판정
# ---------------------------------------------------------------------------
#
# 코드 결함이 아니라 **잔존 데이터** 문제였다. 좌표 충돌 게이트는 소수점 6자리까지
# 같을 때만 도므로, 카카오가 옆 단지의 다른 출입구를 주면 몇백 m 어긋난 채 들어간다.
# 표본에서 이름 경로 좌표의 약 2%가 주소 경로와 400m 넘게 어긋났다.


def _geo7_geo7_hit(lon=127.05, lat=37.49, *, b_code="1168010100", main=977, sub=0,
         atype="REGION_ADDR", mountain=False) -> AddressHit:
    return AddressHit(lon=lon, lat=lat, address_name="서울 강남구 대치동 977",
                      address_type=atype, b_code=b_code, main_no=main,
                      sub_no=sub, is_mountain=mountain)


def _geo7_target(name="○○아파트") -> GeoTarget:
    return GeoTarget(name=name, legal_dong="대치동", sigungu="강남구", sido="서울특별시",
                     address="서울특별시 강남구 대치동 977",
                     legal_dong_code="1168010100", main_no=977, sub_no=0,
                     reb_id="11680100000001")


def test_거리계산은_알려진_값과_맞는다():
    """haversine 회귀 — 여기가 틀리면 모든 판정이 조용히 틀린다."""
    # 위도 1도 ≒ 111.2km
    assert haversine_m(127.0, 37.0, 127.0, 38.0) == pytest.approx(111_195, rel=0.001)
    # 같은 점은 0
    assert haversine_m(127.05, 37.49, 127.05, 37.49) == 0.0
    # 400m 근방 — 임계값이 실제로 400m 언저리를 가르는지 확인한다.
    near = haversine_m(127.05, 37.49, 127.05, 37.49 + 0.0035)     # ≒ 389m
    assert 380 < near < 400


def test_주소와_가까우면_그대로_둔다():
    target = _geo7_target()
    verdict = sweep_verdict(target, 127.05, 37.49, [_geo7_geo7_hit(127.0505, 37.4902)],
                            complex_id=7)
    assert verdict.status == "agree" and verdict.complex_id == 7
    assert verdict.distance_m is not None and verdict.distance_m < 100
    assert verdict.is_mismatch is False


def test_주소와_400m_넘게_어긋나면_불일치():
    """실측 사례의 축소판 — 이름으로 찾은 점이 옆 단지에 붙은 경우."""
    target = _geo7_target()
    verdict = sweep_verdict(target, 127.05, 37.49, [_geo7_geo7_hit(127.06, 37.495)])
    assert verdict.is_mismatch
    assert verdict.distance_m > 400
    assert verdict.fix is not None
    # 재확보는 **주소 경로 좌표**로 한다 — 이름 경로 좌표를 그대로 두지 않는다.
    assert (verdict.fix.lon, verdict.fix.lat) == (127.06, 37.495)
    assert verdict.fix.source == "kakao_address" and verdict.fix.confidence == "address"


def test_임계값은_경계에서_넘을_때만_불일치():
    target = _geo7_target()
    lon, lat = 127.05, 37.49
    just_in = sweep_verdict(target, lon, lat, [_geo7_geo7_hit(lon, lat + 0.0035)])    # ≒389m
    just_out = sweep_verdict(target, lon, lat, [_geo7_geo7_hit(lon, lat + 0.0037)])   # ≒411m
    assert just_in.status == "agree"
    assert just_out.status == "mismatch"


def test_주소검증에_떨어지면_판정하지_않는다():
    """다른 번지·동중심점(REGION)을 받았으면 **모르는 것**이다 — 좌표를 건드리지 않는다.

    여기서 '불일치'로 처리하면, 카카오가 엉뚱한 답을 준 것만으로 멀쩡한 좌표가 지워진다.
    """
    target = _geo7_target()
    assert sweep_verdict(target, 127.05, 37.49, [_geo7_geo7_hit(main=978)]).status == "unverified"
    assert sweep_verdict(target, 127.05, 37.49,
                         [_geo7_geo7_hit(atype="REGION")]).status == "unverified"
    assert sweep_verdict(target, 127.05, 37.49, []).status == "no_result"


def test_스윕은_단지당_한_번만_묻는다():
    """4,500여 건을 도는 배치다. 두 번 물으면 카카오 쿼터가 두 배가 된다."""
    calls: list[str] = []

    class _Search:
        def search(self, address: str):
            calls.append(address)
            return [_geo7_geo7_hit(127.06, 37.495)]

    target = _geo7_target()
    verdicts = sweep_name_path([(1, target, 127.05, 37.49), (2, target, 127.05, 37.49)],
                               _Search())
    assert len(calls) == 2 and len(verdicts) == 2
    assert all(v.is_mismatch for v in verdicts)
    assert [v.complex_id for v in verdicts] == [1, 2]


def test_주소를_모르는_단지는_아예_묻지_않는다():
    class _Boom:
        def search(self, address: str):               # pragma: no cover - 불려선 안 된다
            raise AssertionError("주소가 없는 단지로 카카오를 부르면 안 된다")

    plain = GeoTarget(name="○○아파트", legal_dong="대치동")
    assert sweep_name_path([(1, plain, 127.0, 37.5)], _Boom())[0].status == "no_result"


def test_재확보는_충돌_게이트를_그대로_탄다():
    """무효화 후 다시 넣는 좌표도 **다른 단지가 쓰는 점이면 채택하지 않는다.**

    재확보가 새 오좌표를 만드는 경로를 막는다 — GEO-1 의 재발 방지선이다.
    """
    target = _geo7_target(name="개포우성1")
    other = GeoTarget(name="개포우성2", legal_dong="대치동", reb_id="11680100000009")
    fix = GeoFix(lon=127.06, lat=37.495, confidence="address", source="kakao_address")

    written: dict[int, GeoFix] = {}
    res = enrich_geom([(5, target)], ReplayGeocoder({target: fix}),
                      lambda cid, f: written.__setitem__(cid, f),
                      occupied={(127.06, 37.495): (9, other)})
    assert written == {} and res.rejected_collision == 1 and res.resolved == 0


def test_재확보는_같은_응답을_재사용한다():
    """`--apply` 단계가 카카오를 다시 부르지 않는다는 것을 구조로 못박는다."""
    target = _geo7_target()
    fix = GeoFix(lon=127.06, lat=37.495, confidence="address", source="kakao_address")
    replay = ReplayGeocoder({target: fix})

    assert replay.locate(target) is fix
    assert replay.last_reason == ""
    unknown = GeoTarget(name="모르는단지", legal_dong="대치동")
    assert replay.locate(unknown) is None
    assert replay.last_reason == "no_result"          # enrich_geom 이 '검색 0건'으로 센다


def test_반영_대상은_name_exact_뿐이다():
    """`name_contains`/`name_fuzzy` 는 **주소 쪽이 틀렸을 수 있다**(개포자이프레지던스 1,317m).

    옵션이 아니라 상수로 막는다 — 옵션이면 언젠가 누가 넓힌다.
    """
    assert APPLIABLE_METHODS == ("name_exact",)


# ---------------------------------------------------------------------------
# SR18-7 — 카카오 호출은 **한 줄로 선다** (속도 제한기 공유)
# ---------------------------------------------------------------------------

def _fake_clock():
    """가짜 시계 — 잠든 만큼 시간이 흐른다. 테스트에서 실제로 기다리지 않는다."""
    now = [0.0]
    return now, (lambda: now[0]), (lambda sec: now.__setitem__(0, now[0] + sec))


def _alternate(limiters: list[RateLimiter], rounds: int) -> None:
    for _ in range(rounds):
        for limiter in limiters:
            limiter.wait()


def test_속도제한기를_따로_만들면_실효간격이_절반이_된다():
    """SR18-7 의 메커니즘을 눈에 보이게 못박는다.

    키워드·주소 백엔드에 제한기를 각각 주면 서로의 마지막 호출 시각을 모른다.
    카카오 입장에서는 **합의한 속도의 두 배**로 맞는 것이고, 차단되면 수집이 통째로 멈춘다.
    """
    now, clock, sleeper = _fake_clock()
    shared = RateLimiter(1.0, clock=clock, sleeper=sleeper)
    _alternate([shared, shared], 2)                    # 호출 4번
    assert now[0] == pytest.approx(3.0)                # 간격 3번 × 1초

    now2, clock2, sleeper2 = _fake_clock()
    separate = [RateLimiter(1.0, clock=clock2, sleeper=sleeper2),
                RateLimiter(1.0, clock=clock2, sleeper=sleeper2)]
    _alternate(separate, 2)                            # 같은 4번인데
    assert now2[0] == pytest.approx(1.0)               # 1초 만에 끝난다 = 두 배 속도


def test_지오코더_배선은_제한기를_공유한다():
    """실제 배선(`scripts/geocode_complexes.build_geocoder`)이 하나만 만드는지 확인한다."""
    import importlib.util
    import sys
    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "_test_geocode_complexes", scripts_dir / "geocode_complexes.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    geocoder = module.build_geocoder("KEY", min_interval=0.25)
    place, address = geocoder.backends
    assert place.rate_limiter is address.rate_limiter, (
        "키워드·주소 백엔드가 제한기를 따로 씁니다 — 카카오 실효 간격이 절반이 됩니다")
    assert place.rate_limiter.min_interval == 0.25

    # --address 모드에서는 키워드 백엔드를 아예 꽂지 않는다(같은 질의 재시도 금지).
    only_address = module.build_geocoder("KEY", min_interval=0.25, address_only=True)
    assert isinstance(only_address.backends[0], NullPlaceSearch)


# ---------------------------------------------------------------------------
# CR-022 GEO-6 — 괄호 안 지번은 잡음이 아니라 **단지 식별자**다
# ---------------------------------------------------------------------------
#
# 아래 사례는 전부 2026-07-26 운영 DB + 부동산원 마스터 실측이다. 좌표를 공유하던
# 16개 그룹/37단지를 전수 대조했더니 **모두** 부동산원에서 서로 다른 단지고유번호였다.


@pytest.mark.parametrize("name, expected", [
    ("삼환나띠르빌(1002-10)", {"1002-10"}),
    ("월드컵아이파크(666-0)", {"666"}),          # 부번 0 은 '(666)' 과 같은 필지
    ("월드컵아이파크(667)", {"667"}),
    ("동궁리치웰문정(101)", {"101"}),
    # 동 목록은 지번이 아니다 — 한 단지의 동들이다
    ("래미안목동아델리체(101동~118동)", set()),
    ("현대2차(10,11,20,23,24,25동)", set()),
    ("서초자연인아파트(102동)", set()),
    # 시공사·차수 표기도 지번이 아니다
    ("탑마을(경남)1", set()),
    ("은평뉴타운 제각말 푸르지오(5-1단지)", set()),
])
def test_괄호_지번만_골라낸다(name, expected):
    assert paren_jibun(name) == expected


@pytest.mark.parametrize("a, b", [
    # 부동산원 실측: 각각 별개 단지고유번호 · 세대수도 다르다
    ("삼환나띠르빌(1002-10)", "삼환나띠르빌(1002-22)"),   # 16세대 vs 15세대
    ("뉴월드(402-42)", "뉴월드(402-120)"),                # **본번이 같아도** 다른 단지
    ("우성(23)", "우성(1058)"),                           # 344세대 vs 296세대
    ("동궁리치웰문정(101)", "동궁리치웰문정(102)"),        # 문정1차 vs 문정2차
    ("근상프리즘(957-1)", "근상프리즘(1076-2)"),
    ("광남캐스빌(443-26)", "광남캐스빌(448-5)"),
    ("래미안삼성1차(103-22)", "래미안삼성1차(105-0)"),
    ("동탄숲속마을자연앤경남아너스빌(1115-0)",
     "동탄숲속마을자연앤경남아너스빌(1124-0)"),           # 641세대 vs 455세대
])
def test_괄호_지번이_다르면_좌표를_공유하지_않는다(a, b):
    """⚠️ 본번만 비교하면 '뉴월드(402-42)'/'(402-120)' 를 놓친다 — 부번까지 본다."""
    ta = GeoTarget(name=a, legal_dong="○○동")
    tb = GeoTarget(name=b, legal_dong="○○동")
    assert different_parcel(ta, tb) is True
    assert same_complex(ta, tb) is False


@pytest.mark.parametrize("a, b", [
    ("롯데캐슬", "롯데캐슬(1057-1)"),                  # 한쪽이 없으면 '모른다'
    ("월드컵아이파크(666)", "월드컵아이파크(666-0)"),   # 같은 필지의 다른 표기
    ("서초자연인아파트(101동)", "서초자연인아파트(102동)"),  # 동 — 한 단지
    ("대치우성아파트1동,2동", "대치우성"),
])
def test_지번이_아니거나_모르면_공유를_깨지_않는다(a, b):
    """규칙이 정상 공유까지 깨면 멀쩡한 단지가 지도에서 사라진다 — 그건 과잉교정이다."""
    ta = GeoTarget(name=a, legal_dong="○○동")
    tb = GeoTarget(name=b, legal_dong="○○동")
    assert different_parcel(ta, tb) is False
    assert same_complex(ta, tb) is True


def test_부동산원_번호가_같으면_괄호_지번보다_우선한다():
    """번호가 이름을 이긴다 — 엄격 매칭을 통과한 값이 표기보다 강하다(GEO-3 규약 유지)."""
    a = GeoTarget(name="○○(1002-10)", legal_dong="○○동", reb_id="11650100050187")
    b = GeoTarget(name="○○(1002-22)", legal_dong="○○동", reb_id="11650100050187")
    assert same_complex(a, b) is True
