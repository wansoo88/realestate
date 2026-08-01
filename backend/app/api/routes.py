"""API 라우터.

원칙: **라우터는 얇게.** 검증 → 도메인 호출 → 직렬화만 한다.
계산식이 라우터에 있으면 코드리뷰에서 반려한다(implementation-plan.md §1).
"""
from __future__ import annotations

import datetime as dt
import logging
import secrets
from typing import Annotated, Any

import jwt
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)

from app.agents.llm import build_llm
from app.agents.recommend import (
    PRICE_BASIS_CLIENT,
    PRICE_BASIS_TIME_ADJUSTED,
    PRICE_BASIS_TRADE_BAND,
    borrower_from_profile,
    complex_reference_price,
    run_recommendation_job,
)
from app.api import schemas
from app.api.cookies import (
    delete_refresh_cookie,
    expired_refresh_cookie_header,
    set_refresh_cookie,
)
from app.api.deps import (
    AdminUser,
    CurrentUser,
    SettingsDep,
    unapproved_detail,
    admin_not_found,
    get_encryption_key,
    get_repo,
    get_rules,
    require_ajax_header,
)
from app.core.config import Settings
from app.core.security import (
    ACCESS_TTL_SECONDS,
    DecryptionError,
    create_token,
    decode_token,
    decrypt_amount,
    dummy_password_hash,
    encrypt_amount,
    hash_password,
    verify_password,
)
from app.domain.affordability.budget import (
    BudgetFn,
    fixed_budget,
    profile_budget,
)
from app.domain.affordability.engine import compute_affordability
from app.domain.affordability.models import LoanTerms, PropertyFacts
from app.domain.conditions import resolve_budget_override
from app.domain.listings.dedup import AREA_TOLERANCE_M2
from app.domain.rules.loader import RuleSet
from app.repositories.base import (
    LISTING_SOURCE_USER_LABEL,
    LISTING_STALE_DAYS,
    MAX_USER_LISTINGS,
    STATUS_APPROVED,
    STATUS_REJECTED,
    LastAdminError,
)

logger = logging.getLogger("app")

router = APIRouter(prefix="/api/v1")

#: 자산 금액 필드 ↔ 암호문 컬럼 매핑
_AMOUNT_FIELDS = {
    "cash_krw": "cash_krw_enc",
    "income_krw": "income_krw_enc",
    "existing_loan_krw": "existing_loan_krw_enc",
}


# ---------------------------------------------------------------------------
# 운영
# ---------------------------------------------------------------------------

@router.get("/health", tags=["ops"])
def health(settings: SettingsDep) -> dict[str, Any]:
    """유일한 비인증 엔드포인트. 비밀값을 노출하지 않는다."""
    return {"status": "ok", "role": settings.app_role}


# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------

@router.post("/auth/register", status_code=status.HTTP_201_CREATED, tags=["auth"])
def register(body: schemas.RegisterIn, repo=Depends(get_repo)) -> schemas.RegisterOut:
    """가입을 **접수**한다. 계정은 `pending` 으로 만들어지고 로그인은 아직 안 된다.

    가입 자체를 막지 않는 이유: 관리자가 검토할 대상이 있어야 승인제가 성립한다.
    (예전에는 nginx 에서 이 경로를 403 으로 막아 두는 임시 조치였다.)
    """
    try:
        user = repo.create_user(str(body.email), hash_password(body.password))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "EMAIL_TAKEN", "message": str(exc)},
        ) from exc
    return schemas.RegisterOut(
        user_id=user.id,
        status=user.status,
        message="가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다.",
    )


@router.post("/auth/login", tags=["auth"])
def login(body: schemas.LoginIn, response: Response, settings: SettingsDep,
          repo=Depends(get_repo)) -> schemas.TokenOut:
    """access 는 본문으로, **refresh 는 쿠키로만** 준다 (security.md §2.1 / SR15-1).

    ⚠️ 검사 순서를 바꾸지 마라 (계정 열거 방지 · SR10-1)
    ---------------------------------------------------
    1. **비밀번호 먼저.** 틀리면 없는 계정과 **완전히 같은** 401 — 본문·상태·비용 모두.
    2. 승인 상태는 **비밀번호가 맞은 뒤에만** 본다. 이 순서라면 상태(승인 대기/거부)를
       알 수 있는 사람은 이미 그 계정의 비밀번호를 아는 사람뿐이라 열거 오라클이 아니다.

    순서를 뒤집어 "pending 이면 403" 을 먼저 내보내면, 공격자는 아무 비밀번호나 넣고
    403/401 만 보고 **가입된 이메일 목록**을 만들 수 있다. 승인제는 그때 오히려
    "누가 승인 대기 중인지"까지 알려주는 장치가 된다.
    """
    user = repo.get_user_by_email(str(body.email))
    # 없는 계정에도 **같은 비용의 해시 검증**을 태운다 — 응답 시간이 가입 여부를
    # 알려주지 않게 한다(dummy_password_hash 주석 참고).
    ok = verify_password(
        body.password,
        user.password_hash if user is not None else dummy_password_hash(),
    )
    if not ok or user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "이메일 또는 비밀번호가 올바르지 않습니다"},
        )

    # 여기부터는 비밀번호를 아는 사람이다 — 상태를 알려줘도 열거로 이어지지 않는다.
    if not user.is_approved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=unapproved_detail(user.status))

    set_refresh_cookie(
        response,
        create_token(user.id, secret=settings.jwt_secret, kind="refresh"),
        settings,
    )
    return schemas.TokenOut(
        access_token=create_token(user.id, secret=settings.jwt_secret, kind="access"),
        expires_in=ACCESS_TTL_SECONDS,
    )


def _refresh_rejected(settings: Settings) -> HTTPException:
    """갱신 거절 401. **응답과 함께 쿠키를 지운다.**

    못 쓰는 쿠키를 브라우저에 남겨두면 매 요청마다 실패를 반복하고, 사용자는
    "로그인했는데 안 된다"에 갇힌다. 실패했으면 그 자리에서 정리한다.
    거절 사유(없음/만료/서명오류/종류불일치)는 구분해서 알려주지 않는다.
    """
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail={"code": "UNAUTHORIZED", "message": "유효하지 않은 토큰입니다"},
        headers=expired_refresh_cookie_header(settings),
    )


@router.post("/auth/refresh", tags=["auth"],
             dependencies=[Depends(require_ajax_header)])
def refresh(
    response: Response,
    settings: SettingsDep,
    refresh_token: Annotated[str | None, Cookie()] = None,
    repo=Depends(get_repo),
) -> schemas.TokenOut:
    """쿠키로만 갱신한다. **요청 본문을 받지 않는다.**

    본문으로 refresh 를 받는 경로를 남겨두면 쿠키를 도입한 의미가 없다 —
    공격자는 언제나 더 편한 쪽(JS 로 읽어 본문에 실을 수 있는 쪽)을 고른다.

    갱신할 때마다 **쿠키를 회전**시킨다. 쓴 토큰은 새 토큰으로 덮이므로,
    유출본이 있더라도 정상 사용자가 한 번만 갱신하면 그 값은 브라우저에서 사라진다.
    (아직 서버측 폐기는 없다 — 유출본 자체는 만료까지 유효하다. 후속 SR15-3)
    """
    if not refresh_token:
        raise _refresh_rejected(settings)
    try:
        user_id = decode_token(refresh_token, secret=settings.jwt_secret,
                               expect="refresh")
    except jwt.PyJWTError as exc:
        raise _refresh_rejected(settings) from exc
    # 승인이 취소·거부된 계정은 **더 이상 갱신되지 않는다.** 여기서 막지 않으면
    # 거부 처리가 refresh 수명(7일) 동안 아무 효과가 없다(서버측 폐기 없음 — SR15-3).
    # 사유는 401 로 통일한다: 이 요청은 쿠키만 들고 오므로 상태를 알려줄 이유가 없고,
    # 프론트는 쿠키가 지워진 채 로그인 화면으로 가서 거기서 403 안내를 받는다.
    user = repo.get_user(user_id)
    if user is None or not user.is_approved:
        raise _refresh_rejected(settings)

    set_refresh_cookie(
        response,
        create_token(user_id, secret=settings.jwt_secret, kind="refresh"),
        settings,
    )
    return schemas.TokenOut(
        access_token=create_token(user_id, secret=settings.jwt_secret, kind="access"),
        expires_in=ACCESS_TTL_SECONDS,
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["auth"],
             dependencies=[Depends(require_ajax_header)])
def logout(settings: SettingsDep) -> Response:
    """쿠키를 만료시킨다. 인증을 요구하지 않는다 — 이미 만료된 access 로도 나갈 수 있어야 한다.

    ⚠️ 지금은 **브라우저에서 지우는 것**까지가 전부다. 이미 발급된 refresh 는
    서버가 회수하지 못한다(폐기 목록 없음). 후속 과제 SR15-3.
    """
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    delete_refresh_cookie(response, settings)
    return response


# ---------------------------------------------------------------------------
# 내 조건 (민감 — 로그 제외 대상)
# ---------------------------------------------------------------------------

def _profile_to_out(profile, user_id: int, key: bytes) -> schemas.ProfileOut:
    values: dict[str, int] = {}
    for plain, enc_col in _AMOUNT_FIELDS.items():
        try:
            values[plain] = decrypt_amount(
                getattr(profile, enc_col), user_id=user_id, field=plain, key=key) or 0
        except DecryptionError as exc:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "DECRYPTION_FAILED",
                        "message": "저장된 자산 정보를 읽을 수 없습니다. 다시 입력해 주세요."},
            ) from exc
    return schemas.ProfileOut(
        **values,
        existing_annual_repayment_krw=0,
        existing_annual_interest_krw=0,
        owned_houses=profile.owned_houses,
        household_size=profile.household_size,
    )


@router.get("/me/profile", tags=["me"])
def get_profile(user: CurrentUser, repo=Depends(get_repo),
                key: bytes = Depends(get_encryption_key)) -> schemas.ProfileOut:
    profile = repo.get_profile(user.id)
    if profile is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "자산 정보가 아직 없습니다"},
        )
    return _profile_to_out(profile, user.id, key)


@router.put("/me/profile", tags=["me"])
def put_profile(body: schemas.ProfileIn, user: CurrentUser,
                repo=Depends(get_repo),
                key: bytes = Depends(get_encryption_key)) -> schemas.ProfileOut:
    from app.repositories.base import ProfileRecord

    record = ProfileRecord(
        user_id=user.id,
        owned_houses=body.owned_houses,
        household_size=body.household_size,
    )
    for plain, enc_col in _AMOUNT_FIELDS.items():
        setattr(record, enc_col,
                encrypt_amount(getattr(body, plain), user_id=user.id, field=plain, key=key))
    repo.upsert_profile(record)
    return _profile_to_out(record, user.id, key)


@router.get("/me/preferences", tags=["me"])
def get_preferences(user: CurrentUser, repo=Depends(get_repo)) -> dict[str, Any]:
    return repo.get_preferences(user.id)


@router.put("/me/preferences", tags=["me"])
def put_preferences(body: schemas.PreferencesIn, user: CurrentUser,
                    repo=Depends(get_repo)) -> dict[str, Any]:
    return repo.set_preferences(user.id, body.model_dump())


# ---------------------------------------------------------------------------
# 관심 단지 호가 수동 입력 (migrations/016)
#
# 왜 이 엔드포인트가 생겼나
# -------------------------
# 운영 DB `listing` 0행(2026-07-29 실측). 공공 오픈API 에는 호가가 없고 포털 자동수집은
# 약관·판례상 하지 않기로 했다. 그래서 추천 가중치의 48%(가격 31% + 리스크 17%)가
# 구조적으로 죽어 있었다. 남은 합법적 경로가 **사용자가 손으로 옮겨 적는 것**이다.
#
# 이 데이터의 성격 (설계에 그대로 박혀 있다)
# ------------------------------------------
# · **내 것이다.** 모든 조회·수정·삭제가 `repo.*_user_listing(..., user.id)` 를 지난다.
#   남의 것과 없는 것은 **같은 404** 다 — 구분하면 그 차이가 곧 정보다.
# · **언제 본 값인지가 값의 일부다.** `as_of` 없이는 저장하지 않고(422),
#   90일이 지나면 추천 계산에서 빠진다(`listing_usable`).
# · **출처를 지우지 않는다.** 응답에 `source`·`source_label`("사용자 입력")을 항상 싣는다.
# ---------------------------------------------------------------------------

#: 같은 물건인지 볼 때 쓰는 면적 허용오차. 분석 계층(`dedup._same_unit`)과 **같은 값**이라야
#: "여기선 중복이라 경고했는데 저기선 다른 매물로 센다"가 생기지 않는다.
_LISTING_AREA_TOL_M2 = AREA_TOLERANCE_M2

#: 목록·단건 응답에 함께 나가는 고정 고지. 화면이 문구를 잊어도 서버가 말한다.
LISTING_SOURCE_NOTE = (
    "이 호가는 **사용자가 직접 보고 입력한 값**입니다(공공 데이터가 아닙니다). "
    "실거래가와 다르며, 매물이 이미 팔렸거나 가격이 바뀌었을 수 있습니다."
)
LISTING_STALE_NOTE = (
    f"확인한 지 {LISTING_STALE_DAYS}일이 지난 호가는 추천 계산에서 제외합니다 — "
    "서울 기준 3개월이면 시세가 최대 3%대로 움직여(자체 시장지수 실측) "
    "가격 판정이 그만큼 어긋납니다. 다시 확인해 날짜와 가격을 갱신하세요."
)
#: ★ CR35-7 · SR31-2. `eligible_for_recommendation` 이 답하지 **못하는** 절반을 말한다.
#:
#: 이 화면은 호가 한 건의 상태(활성·낡음)만 안다. 그 호가가 실제로 추천에 반영되려면
#: 그 **단지**가 추천 요청의 지역·예산·평수 조건과 후보 조회 상한을 통과해야 하는데,
#: 후보 조회는 소유자 인자를 받지 않는다(A 의 입력이 B 의 후보 순서·조건 통과를 바꾸는
#: 교차 사용자 누출을 막기 위해서다 — 그 교환은 의도된 것이다). 그래서 "내 호가만 있는
#: 면적대"는 조회 단계에서 근거로 세어지지 않는다.
#: 실측(2026-07-29): 인천 단지에 넣은 호가가 `true` 인데 서울만 요청한 추천은 그 호가를
#: 0회 본다. 조건을 말하지 않으면 사용자는 "서버는 반영됐다는데 왜 안 바뀌지"에 갇힌다.
#: ⚠️ **조건부로 붙이지 않는다.** 어떤 요청으로 추천을 돌릴지 이 화면은 모르므로,
#:    "지금은 해당 없음"을 서버가 판정할 수 없다.
LISTING_ELIGIBILITY_NOTE = (
    "'추천 반영 가능'은 이 호가가 활성이고 낡지 않았다는 뜻입니다 — "
    "**실제로 반영되려면 그 단지가 추천 요청의 지역·예산·평수 조건과 후보 조회 상한을 "
    "통과해야 합니다.** 지역을 좁혀 요청하면 잡힐 가능성이 높아집니다."
)


def _listing_out(rec: Any) -> schemas.UserListingOut:
    """레코드 → 응답. **낡음 판정을 여기서 다시 만들지 않는다** — 리포지토리 계층의
    `listing_staleness`/`listing_usable` 을 그대로 쓴다(계산 경로와 같은 판정)."""
    grade, age = rec.staleness()
    return schemas.UserListingOut(
        id=rec.id, complex_id=rec.complex_id, complex_name=rec.complex_name,
        ask_price_krw=rec.ask_price_krw, area_m2=rec.area_m2, floor=rec.floor,
        apt_dong=rec.apt_dong, as_of=rec.as_of, note=rec.note, status=rec.status,
        source=rec.source, source_label=LISTING_SOURCE_USER_LABEL,
        age_days=age or 0, staleness=grade,
        # ⚠️ 이름이 **자격**인 이유는 schemas.UserListingOut 주석에 있다 —
        #    서버는 여기서 "실제로 반영됐는가"를 알 수 없다(CR35-7 · SR31-2).
        eligible_for_recommendation=rec.usable(),
        price_per_m2_krw=round(rec.ask_price_krw / rec.area_m2),
        created_at=rec.created_at, updated_at=rec.updated_at,
    )


def _listing_reference(repo: Any, rec: Any) -> Any:
    """그 단지·그 면적의 적정가 밴드. **추천 카드·자금계획과 같은 함수**를 쓴다.

    실패해도 예외를 내지 않는다(`complex_reference_price` 계약) — 대조를 못 하는 것이
    저장을 막을 이유는 아니다.
    """
    return complex_reference_price(repo, rec.complex_id, rec.area_m2)


def _band_problem(rec: Any, reference: Any) -> str | None:
    """★ CR35-11. 입력한 호가를 **그 단지의 실거래**와 대조한다.

    ⚠️ **거절하지 않는다.** 진짜 급매일 수 있다 — 오히려 이 도구가 찾으려는 물건이다.
       그래서 말해 주기만 하고 저장은 그대로 한다. 판단은 사람이 한다.
    ⚠️ 대조를 못 했으면 **못 했다고 말한다.** 아무 말도 없으면 사용자는 "이 값이
       검증됐다"고 읽는다 — 이 저장소가 반복해서 막아 온 형태(모름을 통과로 읽기)다.
    """
    if reference is None:
        return None
    band = getattr(reference, "krw", None)
    if not band:
        reason = getattr(reference, "reason", None) or "실거래 자료가 없습니다"
        return (f"이 단지·전용 {rec.area_m2:g}㎡ 의 실거래와 대조하지 못했습니다 "
                f"({reason}). 입력값이 맞는지는 직접 확인해 주세요.")

    ratio = rec.ask_price_krw / band
    if schemas.BAND_WARN_LOW_RATIO <= ratio <= schemas.BAND_WARN_HIGH_RATIO:
        return None
    direction = "낮습니다" if ratio < 1 else "높습니다"
    return (
        f"입력하신 {rec.ask_price_krw:,}원은 이 단지·전용 {rec.area_m2:g}㎡ 의 "
        f"최근 실거래 기준가 {band:,}원의 {ratio * 100:.0f}% 로 크게 {direction} — "
        "금액 자릿수(억·만원)를 다시 확인해 주세요. "
        "실제로 급매이거나 특수한 조건이면 그대로 두셔도 됩니다("
        "저장은 이미 됐습니다).")


def _listing_problems(rec: Any, siblings: list[Any],
                      reference: Any = None) -> list[str]:
    """저장은 했지만 **조용히 넘기면 안 되는 것들**.

    거절(422)과 고지(problems)를 가르는 기준: *불가능한 값*은 거절하고,
    *가능하지만 이상한 값*은 저장하되 말한다. 이상하다는 이유로 막으면 강남 초고가나
    경기 외곽 저가처럼 정상인데 드문 값을 못 넣게 되고, 조용히 받으면 단위 실수가
    그대로 추천 점수를 바꾼다.

    ⚠️ 검사는 **두 층**이다(CR35-11):
       ① 절대값(₩/㎡) — 수도권 어디에도 없는 값을 잡는다. 단지를 모르고도 된다.
       ② 상대값(그 단지 실거래 밴드) — ①을 통과하는 자릿수 실수를 잡는다.
          9.2억→3.0억 오타는 353만원/㎡ 라 ①의 한가운데이고, ②만이 잡는다.
    """
    problems: list[str] = []
    ppm = rec.ask_price_krw / rec.area_m2
    if ppm < schemas.PPM_WARN_LOW_KRW or ppm > schemas.PPM_WARN_HIGH_KRW:
        problems.append(
            f"㎡당 {round(ppm):,}원입니다 — 최근 수도권 아파트 실거래 249,235건 중 "
            f"{schemas.PPM_WARN_LOW_KRW:,}~{schemas.PPM_WARN_HIGH_KRW:,}원/㎡ 밖은 "
            "1.2% 뿐입니다. 금액 단위(억·만원)를 다시 확인해 주세요. "
            "값이 맞다면 그대로 두셔도 됩니다.")

    grade, age = rec.staleness()
    if grade == "aging":
        problems.append(
            f"{age}일 전에 확인한 호가입니다. 추천에는 반영되지만 그 사이 시세가 "
            "움직였을 수 있습니다(서울 기준 월 약 1%).")
    elif grade == "stale":
        problems.append(
            f"{age}일 전 호가라 추천 계산에서 제외됩니다. " + LISTING_STALE_NOTE)

    band_problem = _band_problem(rec, reference)
    if band_problem:
        problems.append(band_problem)

    same = [
        s for s in siblings
        if s.id != rec.id and s.status == "active"
        and abs(s.area_m2 - rec.area_m2) <= _LISTING_AREA_TOL_M2
        and s.floor == rec.floor and (s.apt_dong or None) == (rec.apt_dong or None)
    ]
    if same:
        ids = ", ".join(f"#{s.id}" for s in same[:5])
        problems.append(
            f"같은 단지·면적·층·동으로 이미 {len(same)}건 등록돼 있습니다({ids}). "
            "실제로 매물이 여러 개면 그대로 두세요. **같은 매물의 가격이 바뀐 것이면 "
            "새로 넣지 말고 수정(PATCH)하세요** — 옛 호가가 남아 추천에 두 번 들어갑니다.")
    return problems


def _listing_not_found() -> HTTPException:
    """남의 것과 없는 것을 **같은 404** 로 만든다(IDOR — `get_recommendation` 과 같은 규칙)."""
    return HTTPException(
        status.HTTP_404_NOT_FOUND,
        detail={"code": "NOT_FOUND", "message": "매물을 찾을 수 없습니다"},
    )


@router.post("/me/listings", status_code=status.HTTP_201_CREATED, tags=["me"])
def create_my_listing(body: schemas.UserListingIn, user: CurrentUser,
                      repo=Depends(get_repo)) -> schemas.UserListingItemOut:
    """관심 단지에서 **직접 본** 호가를 등록한다.

    같은 단지·면적에 여러 건을 넣을 수 있다 — 실제로 매물이 여럿이기 때문이다.
    서버가 임의로 합치지 않고, 같은 조건의 기존 건이 있으면 `problems` 로 알려 준다
    (합치는 판단은 사람이 한다. 분석 계층의 `group_duplicates` 가 가격 ±1% 이내는
     자동으로 접지만, 가격이 바뀐 재입력은 접히지 않고 **두 매물로 센다**).
    """
    if repo.complex_name(body.complex_id) is None:
        # 없는 단지에 저장하면 FK 위반 500(운영) 또는 영영 조회 안 되는 행(인메모리)이
        # 된다. 둘 다 사용자에게는 "저장됐는데 안 보인다"로 보인다.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "단지를 찾을 수 없습니다"},
        )

    # ★ SR31-3. **행을 무제한 만드는 첫 엔드포인트**라 사용자당 상한을 둔다.
    #    근거와 값 선택은 `repositories.base.MAX_USER_LISTINGS` 주석에 있다.
    #    ⚠️ `list_user_listings` 의 목록 상한과 **같은 값**이라, 이 문을 지나는 한
    #       `summary.total` 과 중복 경고가 절단 때문에 틀리는 상태는 생기지 않는다
    #       (CR35-8). 그래서 `limit` 을 상한 그대로 두고 `>=` 로 판정한다.
    mine = repo.list_user_listings(user.id)
    if len(mine) >= MAX_USER_LISTINGS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "LIMIT_REACHED",
                    "message": (f"등록할 수 있는 호가는 최대 {MAX_USER_LISTINGS:,}건입니다 "
                                f"(현재 {len(mine):,}건). 팔렸거나 더 안 보는 매물을 "
                                "지우거나, 가격이 바뀐 것이면 새로 넣지 말고 "
                                "수정(PATCH)하세요")},
        )

    siblings = [r for r in mine if r.complex_id == body.complex_id]
    rec = repo.add_user_listing(
        user.id, complex_id=body.complex_id, ask_price_krw=body.ask_price_krw,
        area_m2=body.area_m2, as_of=body.as_of, floor=body.floor,
        apt_dong=body.apt_dong, note=body.note,
    )
    return schemas.UserListingItemOut(
        item=_listing_out(rec),
        problems=_listing_problems(rec, siblings, _listing_reference(repo, rec)),
        notes=[LISTING_SOURCE_NOTE, LISTING_ELIGIBILITY_NOTE])


@router.get("/me/listings", tags=["me"])
def list_my_listings(user: CurrentUser,
                     complex_id: int | None = Query(default=None, gt=0),
                     repo=Depends(get_repo)) -> schemas.UserListingListOut:
    """내가 넣은 호가 전부. **낡은 것도 보여준다** — 고치라고 있는 화면이다.

    `summary.eligible_for_recommendation` 가 "다 넣었는데 왜 추천이 안 바뀌지"의
    **절반**에 답한다. 나머지 절반(그 단지가 후보 조회에 잡혔는가)은 이 화면이 알 수
    없으므로 `LISTING_ELIGIBILITY_NOTE` 가 조건을 상시로 말한다(CR35-7 · SR31-2).
    """
    rows = repo.list_user_listings(user.id, complex_id=complex_id)
    items = [_listing_out(r) for r in rows]
    summary = {
        "total": len(items),
        "fresh": sum(1 for i in items if i.staleness == "fresh"),
        "aging": sum(1 for i in items if i.staleness == "aging"),
        "stale": sum(1 for i in items if i.staleness == "stale"),
        "inactive": sum(1 for i in items if i.status != "active"),
        "eligible_for_recommendation": sum(
            1 for i in items if i.eligible_for_recommendation),
    }
    notes = [LISTING_SOURCE_NOTE, LISTING_ELIGIBILITY_NOTE]
    if summary["stale"]:
        notes.append(f"{summary['stale']}건은 낡아서 추천에 반영되지 않습니다. "
                     + LISTING_STALE_NOTE)
    return schemas.UserListingListOut(items=items, summary=summary, notes=notes)


@router.patch("/me/listings/{listing_id}", tags=["me"])
def update_my_listing(listing_id: int, body: schemas.UserListingPatch,
                      user: CurrentUser,
                      repo=Depends(get_repo)) -> schemas.UserListingItemOut:
    """잘못 적은 값을 고친다. 준 필드만 바뀐다.

    ⚠️ **가격을 바꾸면 `as_of` 도 함께 받는다.** 호가는 "얼마"와 "언제 본 값"이
       분리될 수 없다 — 가격만 갱신하면 석 달 전 날짜에 오늘 가격이 붙어 낡음 판정이
       통째로 거짓이 되고, 그 상태는 화면 어디에도 드러나지 않는다.
    """
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_PARAM", "message": "수정할 항목이 없습니다"},
        )
    # 비울 수 없는 값에 `null` 을 보냈다. **조용히 무시하지 않는다** — 무시하면
    # 사용자는 지웠다고 믿고, 그 오해는 화면 어디에도 드러나지 않는다.
    not_clearable = sorted(k for k, v in fields.items()
                           if v is None and k not in schemas.UserListingPatch.CLEARABLE)
    if not_clearable:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_PARAM",
                    "message": (f"{', '.join(not_clearable)} 은(는) 비울 수 없습니다 — "
                                "바꾸려면 값을 주고, 그대로 두려면 항목을 빼세요")},
        )
    if "ask_price_krw" in fields and fields.get("as_of") is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_PARAM",
                    "message": ("호가를 바꿀 때는 확인한 날짜(as_of)도 함께 보내세요 — "
                                "가격만 갱신하면 옛 날짜에 새 가격이 붙어 "
                                "'언제 본 값인지'가 거짓이 됩니다")},
        )

    before = repo.get_user_listing(listing_id, user.id)
    if before is None:
        raise _listing_not_found()
    siblings = repo.list_user_listings(user.id, complex_id=before.complex_id)
    rec = repo.update_user_listing(listing_id, user.id, **fields)
    if rec is None:                      # 조회와 수정 사이에 지워진 경우
        raise _listing_not_found()
    return schemas.UserListingItemOut(
        item=_listing_out(rec),
        problems=_listing_problems(rec, siblings, _listing_reference(repo, rec)),
        notes=[LISTING_SOURCE_NOTE, LISTING_ELIGIBILITY_NOTE])


@router.delete("/me/listings/{listing_id}", status_code=status.HTTP_204_NO_CONTENT,
               tags=["me"])
def delete_my_listing(listing_id: int, user: CurrentUser,
                      repo=Depends(get_repo)) -> Response:
    """지운다. **되돌릴 수 없으면 아무도 이 기능을 안 쓴다** — 그래서 지우기를 준다.

    '팔렸다·내렸다'를 기록으로 남기고 싶으면 `PATCH {"status": "traded"}` 를 쓴다.
    """
    if not repo.delete_user_listing(listing_id, user.id):
        raise _listing_not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# 실구매 가능 금액 (F2) — 동기 · 규칙 계산 · LLM 미사용
# ---------------------------------------------------------------------------

#: 자금계획이 쓴 금액의 근거를 **사람이 읽는 한 줄**로 옮긴다.
#: 계약(`target_price.basis`)은 기계용이고 이 문장은 화면용이다 — 둘 다 필요하다.
#: 프론트가 문구를 각자 만들면 어느 화면에선가 빠지고, 빠진 화면에서는 추정가가
#: 체결가처럼 보인다(CR33-3 이 카드에서 고친 것과 같은 종류의 사고).
_PRICE_BASIS_SENTENCE = {
    PRICE_BASIS_TIME_ADJUSTED: ("희망 매매가는 이 단지·면적의 최근 {months}개월 실거래 "
                                "{n}건을 {ym} 시점으로 환산한 추정가입니다"
                                "(추천 카드와 같은 값입니다)."),
    PRICE_BASIS_TRADE_BAND: ("희망 매매가는 이 단지·면적의 최근 {months}개월 실거래 "
                             "{n}건의 중위값입니다 — **시점 보정을 하지 못해** 여러 시점의 "
                             "거래를 섞은 값이라 특정 시점의 가격이 아닙니다."),
    PRICE_BASIS_CLIENT: ("희망 매매가는 화면에서 넘어온 금액을 그대로 쓴 것입니다 — "
                         "서버가 근거를 확인하지 않았습니다."),
}
_PRICE_BASIS_NONE = ("희망 매매가를 정하지 못해 자금계획(필요 대출·부족액)을 "
                     "만들지 않았습니다.")


def _price_basis_assumption(ref: dict[str, Any]) -> str:
    """기준가 근거 문장. 근거가 없으면 **계획을 못 만들었다고** 말한다(빈 문자열 금지)."""
    if ref.get("krw") is None:
        reason = ref.get("reason")
        return f"{_PRICE_BASIS_NONE} 사유: {reason}" if reason else _PRICE_BASIS_NONE
    template = _PRICE_BASIS_SENTENCE.get(ref.get("basis") or "")
    if template is None:
        return "희망 매매가의 근거를 확인하지 못했습니다."
    sentence = template.format(months=ref.get("period_months"),
                               n=ref.get("sample_size"), ym=ref.get("as_of_ym"))
    reason = ref.get("reason")
    if reason and ref.get("basis") == PRICE_BASIS_TRADE_BAND:
        sentence = f"{sentence} (사유: {reason})"
    return sentence


@router.post("/affordability", tags=["analysis"])
def affordability(body: schemas.AffordabilityIn, user: CurrentUser,
                  repo=Depends(get_repo),
                  key: bytes = Depends(get_encryption_key),
                  rules: RuleSet = Depends(get_rules)) -> dict[str, Any]:
    profile = repo.get_profile(user.id)
    if profile is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INSUFFICIENT_DATA",
                    "message": "자산 정보를 먼저 입력해 주세요"},
        )

    try:
        # ⚠️ 추천 러너·지도 예산과 **같은 함수**로 만든다. 여기서 따로 조립하던 시절에는
        #    "기존 대출 연 상환액을 0 으로 둔다" 같은 규칙이 두 곳에 복사돼 있었다 —
        #    복사본은 언젠가 한쪽만 바뀌고, 그날 두 화면이 다른 한도를 말한다.
        borrower, _forbidden = borrower_from_profile(profile, user.id, key)
    except DecryptionError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "DECRYPTION_FAILED",
                    "message": "저장된 자산 정보를 읽을 수 없습니다"},
        ) from exc

    # --- 계획의 기준가를 정한다 (CR34-3) ---------------------------------
    # 이 숫자는 사용자 자산으로 **나눗셈**을 하는 값이다. 틀리면 "얼마나 더 필요한가"가
    # 통째로 틀리므로, 어디서 온 값인지를 응답이 반드시 말한다.
    target_price_krw = body.target_price_krw
    price_ref: dict[str, Any] | None = None
    if target_price_krw is not None:
        # 사용자가 직접 넣은 값. **서버는 이 숫자의 근거를 모른다** — 지도의 최근
        # 체결가일 수도, 손으로 친 값일 수도 있다. 모르는 것을 안다고 하지 않는다(G2).
        price_ref = {
            "krw": target_price_krw, "basis": PRICE_BASIS_CLIENT,
            "as_of_ym": None, "sample_size": 0, "period_months": None,
            "reason": ("요청에 실려 온 금액입니다 — 서버가 근거를 확인하지 않았습니다. "
                       "추천 카드의 추정가와 다를 수 있습니다."),
        }
    elif body.complex_id is not None:
        # 추천 카드와 **같은 함수**로 만든다(recommend.complex_reference_price).
        ref = complex_reference_price(repo, body.complex_id, body.area_m2)
        price_ref = ref.to_api()
        target_price_krw = ref.krw

    result = compute_affordability(
        borrower, rules,
        terms=LoanTerms(annual_rate=body.annual_rate, years=body.years,
                        apply_dti=body.apply_dti),
        prop=PropertyFacts(area_m2=body.area_m2,
                           is_regulated_area=body.is_regulated_area,
                           purpose=body.purpose),
        # 희망 매매가를 주면 `plan` 이 붙는다(필요 대출·부족액·월 원리금).
        # 단지를 클릭할 때마다 그 단지 가격으로 다시 호출하는 것이 정상 사용법이다.
        target_price_krw=target_price_krw,
    )
    payload = result.to_api()
    payload["assumptions"].append("기존 대출 상환액 미입력 — 0으로 계산했습니다")
    if price_ref is not None:
        # 계획을 세웠든(금액 있음) 못 세웠든(금액 None) **항상** 싣는다.
        # 금액이 None 인데 이 블록이 없으면 "계획을 왜 못 세웠는지"가 사라진다.
        payload["target_price"] = price_ref
        payload["assumptions"].append(_price_basis_assumption(price_ref))
    return payload


# ---------------------------------------------------------------------------
# 지도 (F1)
# ---------------------------------------------------------------------------

#: 이 줌 미만에서는 단지가 아니라 지역 군집을 반환한다 (ux/README.md §4)
CLUSTER_ZOOM_THRESHOLD = 13
_MAX_BBOX_DEGREES = 2.0


def _check_area_range(area_min_m2: float | None, area_max_m2: float | None) -> None:
    """전용면적 최소>최대는 **거절한다**(400).

    조용히 뒤집으면 사용자는 자기가 넣지 않은 조건의 결과를 자기 조건이라고 믿는다.
    조용히 무시하면 조건이 없는 결과를 조건이 걸린 결과라고 믿는다. 둘 다 이 제품이
    가장 경계하는 '실패가 실패로 보이지 않는' 형태다 — 그래서 되돌려 준다.
    지도(`/map/complexes`)와 추천(`POST /recommendations`)이 **같은 규칙**을 쓴다.
    """
    if area_min_m2 is None or area_max_m2 is None:
        return
    if area_min_m2 > area_max_m2:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PARAM",
                    "message": ("전용면적 최소값이 최대값보다 큽니다 "
                                f"({area_min_m2:g}㎡ > {area_max_m2:g}㎡)")},
        )


#: `redevelopment.available:false` 의 뜻. 추천의 `NO_PROJECT_REASON` 과 **같은 뜻**이다.
#:
#: ⚠️ **항목마다가 아니라 응답에 한 번** 싣는다. 지도 한 화면은 최대 500단지이고 그중
#:    대다수가 미매칭이라(운영 실측 500 중 470), 같은 문장을 470번 실으면 응답이
#:    64KiB 커진다 — 지도는 팬할 때마다 다시 부르는 모바일 화면이다. 뜻은 한 번만
#:    말하면 되고, 항목에 필요한 것은 **플래그**다.
REDEV_MAP_UNKNOWN_NOTE = (
    "redevelopment.available=false 는 '정비사업이 없다'가 아니라 "
    "'확인되지 않았다'는 뜻입니다 — 수집 범위는 서울·인천이며 경기도는 미수집입니다."
)

#: 지도 가격의 근거 식별자. **추천 카드의 값과 다른 양**이라는 사실을 이름으로 못박는다.
#: `latest_trade` = 실제로 체결된 1건. 추천 카드는 `time_adjusted_band`(창 중위를 기준월로
#: 환산한 추정가)다 — 둘은 같아질 수 없고, 같은 척하면 어느 쪽도 못 믿게 된다.
PRICE_BASIS_LATEST_TRADE = "latest_trade"

#: ⚠️ **왜 지도를 시점 보정하지 않는가** (CR34-3 판단 근거, 운영 DB 실측 2026-07-28)
#:
#: 지도와 추천의 격차를 두 성분으로 분해했다(226단지, 같은 단지·같은 면적):
#:   A 정의 차이(최근 체결 1건 vs 창 중위)  중위 −3.7% · p10 −18.8% · |중위| 5.8%
#:   B 시점 보정(창 중위를 기준월로 환산)    중위 +1.7% · p10  −3.1% · |중위| 3.4%
#:   → **67% 의 단지에서 |A| > |B|.** 지도를 보정해도 두 값은 여전히 A 만큼 다르다.
#: 게다가 밴드 중위는 **면적별** 값인데 지도는 대개 면적을 모른다(한 단지가 34~120㎡).
#: 즉 지도가 추천과 같은 숫자를 내는 것은 성능 문제 이전에 **정의상 불가능**하다.
#: (성능도 재 봤다: SQL 한 방으로 12개월 창을 환산해도 +103ms — 못 할 만큼 비싸지는
#:  않다. 그런데도 안 하는 이유는 값이 맞아지지 않기 때문이다.)
#: 그래서 **각 화면이 자기 숫자가 무엇인지 말하게** 한다. 대신 이 라운드에서 훨씬 큰
#: 격차 하나를 없앴다 — 지도 가격이 사용자의 면적 조건을 무시하던 것(44%·평균 26.8%).
MAP_PRICE_BASIS_NOTE = (
    "지도의 가격은 그 단지에서 **실제로 체결된 최근 1건**입니다(추정치가 아닙니다). "
    "추천 카드의 금액은 최근 6~36개월 거래를 한 시점으로 환산한 **추정가**라서 "
    "같은 단지라도 두 값은 다릅니다 — 운영 실측 중위 약 2%, 큰 쪽은 10%대입니다. "
    "면적 조건을 걸면 그 조건에 맞는 거래 중 최근 1건만 보여주며, 조건에 맞는 거래가 "
    "없으면 금액을 비워 둡니다(조건 밖 거래로 채우지 않습니다)."
)


# ---------------------------------------------------------------------------
# ★ SR32-1 — 지도의 예산 기준은 **서버가 정한다**
#
# 무엇이 잘못돼 있었나
# --------------------
# 클라이언트가 `?max_price_krw=1314310000` 을 보냈다. 그 숫자는 화면이 지어낸 값이
# 아니라 `/affordability` 가 **AES-256-GCM 으로 암호화된 현금·소득·대출을 복호화해
# 계산한 최대 구매가능 금액**이었다. 즉 이 저장소가 컬럼 암호화·본문 로그 금지·필드
# 마스킹으로 세 겹을 쌓아 지키던 값이, **URL 이라는 네 번째 길**로 나가 nginx·uvicorn
# 접근 로그에 평문으로 눌러앉았다(운영 실측 148줄 · 101줄은 0644 월드 리더블 ·
# 비루트 동거 계정으로 실제 열람됨).
#
# 왜 '로그를 가리는 것'으로 끝내지 않는가
# ---------------------------------------
# 로그 마스킹은 **완화**다. 값이 URL 에 실리는 한 프록시·브라우저 히스토리·Referer·
# 캐시·에러 리포팅처럼 우리가 통제하지 못하는 싱크가 계속 남는다. 이 저장소의 규칙은
# *"개인·민감정보를 URL 파라미터나 쿼리 문자열에 넣지 않는다"* 이고, 여기는 **인증된
# 경로**이며 **서버가 이미 그 사용자의 프로필을 갖고 있다.** 클라이언트가 금액을
# 계산해 보낼 이유가 없다.
#
# 그래서: 금액 대신 **기준(basis)만** 받는다.
#     GET /map/complexes?...&budget=profile     ← 저장된 내 조건·프로필로 서버가 산출
#     GET /map/complexes?...                    ← 기본값 off (예산 판정 안 함)
#
# 희망가(슬라이더)는 자산 파생인가 — **그 질문에 답할 필요가 없어졌다**
# ------------------------------------------------------------------
# 사용자가 직접 정한 희망 매매가는 "내가 얼마짜리를 살 생각인가"라는 **개인 금융정보**다
# (자산에서 파생됐는지와 무관하게 URL 에 실을 값이 아니다). 그런데 그 값은 이미
# `user_preference.prefer.target_price_krw` 에 **서버가 저장하고 있다**(화면도 그것을
# 정본으로 읽는다 — `App.tsx::readTargetPrice`). 그래서 클라이언트가 실어 보낼 이유가
# 없고, 서버가 저장본을 읽으면 된다. **두 값 다 URL 에서 사라진다.**
#
# 우선순위는 추천 러너와 **같은 함수**(`resolve_budget_override`)로 정한다:
#     저장된 희망 매매가 > 프로필로 계산한 최대 구매가능 금액
# 프론트의 `effectiveBudgetKrw`(희망가 ?? 한도)와 **같은 우선순위**다. 규칙을 여기서
# 새로 쓰면 언젠가 세 화면이 다른 순서를 갖는다.
#
# ⚠️ 그런데 **우선순위가 같다고 금액이 같아지지는 않는다** (CR37-1, 2026-07-29)
# ------------------------------------------------------------------------
# ②(프로필로 계산한 한도)는 **면적의 함수**다 — 취득세의 농어촌특별세가 전용 85㎡ 를
# 경계로 붙어서 그렇다. 운영 세율·현금 5억·연소득 1억 무주택 실측:
#
#     area  84.00 → max_purchase_krw 1,026,560,000
#     area  85.01 → max_purchase_krw 1,024,580,000   (−1,980,000 · 농특세 0.2%)
#     area 114.00 → max_purchase_krw 1,024,580,000
#
# 예전에는 지도가 `PropertyFacts()` 의 **기본 면적 84.0** 으로 한 숫자를 만들어 화면
# 전체를 판정했다. 그런데 화면(`/affordability`)은 사용자가 고른 단지의 면적으로 부른다.
# 85㎡ 를 사이에 두면 두 값이 갈리고, 프론트의 대조 카나리아가 **아무것도 고장나지
# 않았는데** "예산 기준 금액이 서로 다릅니다"를 띄웠다(실측 conflicts=2).
#
# 한 숫자로 지도 전체를 맞출 수는 없다 — 지도는 34㎡ 와 120㎡ 를 한 화면에 담는다.
# 그래서 **맞추는 척하지 않고, 단지마다 그 단지 값의 면적으로 한도를 계산한다**:
#
#     over_budget = recent_price_krw > max_purchase(area = price_area_m2)
#
# 이러면 `POST /affordability`(같은 `complex_id`·같은 `area_m2`)가 돌려주는
# `max_purchase_krw` 와 **같은 숫자**가 되어, 지도와 자금계획이 실제로 같은 상한을
# 말한다(api-spec §4 · `test_map_budget_parity.py` 가 API 전 구간에서 못박는다).
# 면적을 모르면(`price_area_m2 = null`) 84 같은 값을 가정해 채우지 않고 **판정하지
# 않는다**(`over_budget = null`) — 모르는 것을 아는 척하지 않는다(G2).
#
# ①(저장된 희망 매매가)은 사용자가 정한 **금액 하나**라 면적과 무관하다. 그때는
# 예전과 똑같이 단일 상한으로 판정한다.
# ---------------------------------------------------------------------------

#: `?budget=` 이 받는 값. **금액이 아니라 '무엇을 기준으로 할지'만** 받는다.
#: 이름을 `mine` 으로 둔 이유: 이 제품의 화면 어휘가 "내 조건"·"내 매물"이고,
#: 사용자가 켜는 스위치의 뜻이 정확히 *"내 예산 기준으로 봐 달라"* 다.
#: 프론트는 끌 때 파라미터를 **아예 빼고**(기본 off), 켤 때만 `budget=mine` 을 싣는다.
BUDGET_OFF = "off"
BUDGET_MINE = "mine"
_BUDGET_MODES = f"^({BUDGET_OFF}|{BUDGET_MINE})$"

#: 서버가 무엇으로 상한을 정했는지. 화면이 "내 희망가 기준"·"내 한도 기준"을 구분해
#: 말할 수 있어야 한다 — 어느 쪽인지 모르면 사용자는 자기가 켠 조건을 확인할 수 없다.
BUDGET_BASIS_TARGET_PRICE = "target_price"
BUDGET_BASIS_MAX_PURCHASE = "max_purchase"

#: 폐기된 파라미터. **조용히 무시하지 않는다** — 무시하면 옛 화면에서 예산 조건이
#: 소리 없이 풀리고, 사용자는 조건이 걸린 결과라고 믿은 채 예산 밖 단지를 본다.
LEGACY_BUDGET_PARAM = "max_price_krw"
LEGACY_BUDGET_MESSAGE = (
    "max_price_krw 는 더 이상 받지 않습니다 — 금액이 URL(그리고 접근 로그)에 남기 "
    "때문입니다. 예산은 서버가 저장된 내 조건·자산으로 계산합니다. "
    "`budget=mine` 을 쓰세요(예산 판정을 끄려면 파라미터를 빼면 됩니다)."
)

#: 예산 기준을 세우지 못했을 때 **왜인지**. 빈 값으로 두지 않는다(조용한 실패 금지).
_BUDGET_NO_PROFILE = ("자산 정보가 없어 예산 기준을 세우지 못했습니다 — "
                      "내 정보에서 보유 현금·연소득을 입력하거나 희망 매매가를 정하면 "
                      "예산 초과 여부를 표시합니다.")
_BUDGET_DECRYPT_FAILED = "저장된 자산 정보를 읽지 못해 예산 기준을 세우지 못했습니다."
_BUDGET_UNAVAILABLE = ("예산 계산에 필요한 설정을 읽지 못해 예산 기준을 "
                       "세우지 못했습니다(지도는 그대로 동작합니다).")


def _budget_block(applied: bool, basis: str | None = None,
                  reason: str | None = None) -> dict[str, Any]:
    """응답에 싣는 예산 기준 설명. **금액은 싣지 않는다.**

    화면은 그 숫자를 `/affordability` 로 이미 알고 있고, 여기 또 실으면 같은 값이
    흐르는 길이 하나 더 늘어난다(본문은 로그에 안 남지만, 최소 노출이 원칙이다).
    """
    return {"applied": applied, "basis": basis, "reason": reason}


#: 지도 예산 상한 조회기. **면적(㎡)을 받아 그 면적의 상한(원)을 돌려준다.**
#:
#: 한 숫자(`int`)가 아닌 이유는 위 주석(CR37-1) 그대로다 — ②(자산으로 계산한 한도)는
#: 전용 85㎡ 경계에서 갈리는데 지도는 여러 면적을 한 화면에 담는다. 면적을 모르면
#: `None`(판정 못 함)을 돌려준다.
#:
#: ⚠️ 조회기 **구현은 `app/domain/affordability/budget.py` 에 있다**(CR39-2, 2026-07-30).
#:    추천 러너도 같은 판정을 해야 하는데 러너가 이 파일을 import 하면 순환이 되기
#:    때문이다(routes → agents.recommend). 같은 계산을 두 벌 두면 반드시 다시 갈린다 —
#:    실제로 지도만 고쳤던 동안 추천은 84㎡ 한 숫자로 후보를 제외하고 있었다.
MapBudgetFn = BudgetFn


def _resolve_map_budget(repo: Any, *, user: Any, settings: Settings,
                        purpose: str) -> tuple[MapBudgetFn | None, dict[str, Any]]:
    """지도의 예산 상한 **조회기**와 그 근거. 실패해도 **지도를 죽이지 않는다**.

    세율 설정·암호화 키가 잘못돼 있으면 `/affordability` 는 503 이어야 하지만
    (그건 계산이 본업인 엔드포인트다), 지도는 공공 데이터를 그리는 화면이라
    예산 배지 하나 때문에 통째로 죽으면 안 된다. 대신 **왜 못 세웠는지**를 말한다.
    """
    prefer = {}
    try:
        prefer = (repo.get_preferences(user.id) or {}).get("prefer") or {}
    except Exception:  # noqa: BLE001 - 선호 조회 실패로 지도를 죽이지 않는다
        logger.exception("지도 예산: 선호 조회 실패 (user=%s)", user.id)

    # 저장된 희망 매매가가 있으면 그것이 상한이다(추천 러너와 같은 함수·같은 순서).
    target = resolve_budget_override(None, prefer)
    if target is not None:
        return fixed_budget(target), _budget_block(True, BUDGET_BASIS_TARGET_PRICE)

    profile = repo.get_profile(user.id)
    if profile is None:
        return None, _budget_block(False, reason=_BUDGET_NO_PROFILE)

    try:
        rules = get_rules(settings)
        key = get_encryption_key(settings)
    except HTTPException:
        logger.warning("지도 예산: 세율/키 설정을 읽지 못해 예산 기준 없이 응답합니다")
        return None, _budget_block(False, reason=_BUDGET_UNAVAILABLE)

    try:
        borrower, _forbidden = borrower_from_profile(profile, user.id, key)
    except DecryptionError:
        logger.exception("지도 예산: 자산 복호화 실패 (user=%s)", user.id)
        return None, _budget_block(False, reason=_BUDGET_DECRYPT_FAILED)

    return (profile_budget(borrower, rules, purpose),
            _budget_block(True, BUDGET_BASIS_MAX_PURCHASE))


def _over_budget(price_krw: int | None, budget_krw: int | None) -> bool | None:
    """예산 초과 판정. **모르면 `null`** — false 로 접지 않는다.

    예전에는 예산을 모를 때도 `false`(= 예산 안)였다. 가격이 없을 때도 `false` 였다.
    "예산 안"과 "판정 못 함"이 같은 값이면 화면은 그 둘을 구분할 수 없다.
    """
    if budget_krw is None or not price_krw:
        return None
    return price_krw > budget_krw


def _item_over_budget(c: Any, budget_at: MapBudgetFn | None) -> bool | None:
    """지도 항목 하나의 예산 초과 판정.

    **그 항목 가격의 면적(`price_area_m2`)으로 계산한 상한**과 비교한다 —
    같은 단지·같은 면적으로 `/affordability` 를 부른 값과 같은 숫자다(CR37-1).
    """
    if budget_at is None:
        return None
    return _over_budget(c.recent_price_krw, budget_at(c.price_area_m2))


def _map_tag_facts(c: Any) -> dict[str, Any]:
    """지도 항목의 특성 태그용 사실 — `nearest_station` · `redevelopment` (MAP-2).

    **판정이 아니라 값을 준다.** '역세권(500m)'·'대단지(1,000세대)' 임계값은 표시
    관례라 바뀌고, 서버가 boolean 으로 굳혀 보내면 화면이 기준을 되돌릴 수 없다.

    ⚠️ `redevelopment` 는 매칭이 없어도 **블록을 실어 보낸다.** `available:false` 는
       '정비사업 없음'이 아니라 **'확인되지 않음'** 이고(수집 범위: 서울·인천),
       프론트는 그 false 를 "모름"으로 접는다(`lib/tags.ts:redevelopmentFact`).
       블록 자체를 빼면 '없다'와 '모른다'가 같은 모양이 되어 구분이 사라진다.
    """
    station = c.nearest_station
    redev = c.redevelopment
    return {
        "nearest_station": (None if station is None else {
            "name": station.name,
            "distance_m": station.distance_m,
            "line_count": station.line_count,
            "lines": list(station.lines),
            # 직선거리다. 도보 거리가 아니라는 사실을 값 옆에 붙여 보낸다.
            "basis": station.basis,
        }),
        # 지도에는 **판정(verdict)·점수를 싣지 않는다.** 그 둘은 목적(실거주/투자)에
        # 따라 정반대가 되는데 지도는 사용자의 목적을 모른다 — 목적 없이 만든
        # 판정을 화면에 올리면 추천 카드와 다른 말을 하게 된다.
        # `available:false` 의 뜻은 응답의 `redevelopment_note` 에 한 번 적는다.
        "redevelopment": (None if redev is None else {
            "available": redev.available,
            "stage": redev.stage,
            "raw_stage": redev.raw_stage,
            "zone_name": redev.zone_name,
        }),
    }


@router.get("/map/complexes", tags=["map"])
def map_complexes(
    request: Request,
    user: CurrentUser,
    settings: SettingsDep,
    bbox: str = Query(description="minLon,minLat,maxLon,maxLat"),
    zoom: int = Query(ge=1, le=22),
    #: ★ SR32-1 — **금액이 아니라 기준만 받는다.** 근거는 `_resolve_map_budget` 위 주석.
    budget: str = Query(
        default=BUDGET_OFF, pattern=_BUDGET_MODES,
        description=("예산 초과 표시 기준. `mine` 이면 서버가 저장된 희망 매매가 "
                     "또는 자산으로 계산한 한도를 쓴다. 금액은 받지 않는다.")),
    #: 목적은 한도 계산에 **입력으로 들어간다**(`_lending_setup` 의 `cap_facts` →
    #: 대출 절대한도·스트레스 가산 조회). `/affordability`·`/recommendations` 와
    #: 같은 값 집합을 쓰므로 세 화면이 같은 가정으로 계산한다.
    #:
    #: ⚠️ **오늘은 두 값의 한도가 같다**(CR37-5, 2026-07-29 실측 1,026,560,000 동일).
    #:    `config/tax_rules.yaml` 의 `absolute_cap`·`stress_dsr` 이 `region_group` 만
    #:    조건으로 쓰고 `purpose` 를 쓰는 규칙이 **하나도 없기 때문**이다. 배선을 남겨
    #:    두는 이유는 목적별 규칙이 생기는 날 설정 한 줄이면 되기 때문이고, 그때까지
    #:    "달라진다"고 적지 않는다 — 있는 척하지 않는다.
    purpose: str = Query(default="live", pattern="^(live|invest)$"),
    # ⚠️ `allow_inf_nan=False` — `Infinity` 는 `gt=0` 을 **통과한다**(inf > 0). 그러면
    #    하류에서 조건이 조용히 사라지고 사용자는 조건 없는 결과를 조건이 걸린 결과로
    #    읽는다(SR24-6). `NaN`·`-Infinity` 는 이미 422 이므로 여기서 규칙을 맞춘다.
    area_min_m2: float | None = Query(default=None, gt=0, allow_inf_nan=False),
    area_max_m2: float | None = Query(default=None, gt=0, allow_inf_nan=False),
    built_after: int | None = Query(default=None, ge=1900, le=2100),
    repo=Depends(get_repo),
) -> dict[str, Any]:
    # 옛 클라이언트가 금액을 실어 보내면 **거절한다**(400). 받아서 무시하면 예산 조건이
    # 조용히 풀리고, 사용자는 조건이 걸린 줄 알고 예산 밖 단지를 본다 — 이 저장소가
    # 가장 경계하는 '실패가 실패로 보이지 않는' 형태다. 값은 응답에 되비치지 않는다.
    if LEGACY_BUDGET_PARAM in request.query_params:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "PARAM_REMOVED", "message": LEGACY_BUDGET_MESSAGE},
        )

    try:
        parts = [float(x) for x in bbox.split(",")]
        min_lon, min_lat, max_lon, max_lat = parts
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PARAM",
                    "message": "bbox 는 minLon,minLat,maxLon,maxLat 형식이어야 합니다"},
        ) from exc

    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PARAM", "message": "bbox 범위가 올바르지 않습니다"},
        )
    # 지나치게 넓은 범위는 서버를 태운다. 줌아웃은 군집으로 처리한다.
    if (max_lon - min_lon) > _MAX_BBOX_DEGREES or (max_lat - min_lat) > _MAX_BBOX_DEGREES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PARAM", "message": "조회 범위가 너무 넓습니다"},
        )
    _check_area_range(area_min_m2, area_max_m2)

    # 예산 상한은 **여기서, 서버가** 정한다(SR32-1). `off` 면 계산 자체를 하지 않는다 —
    # 필요 없는 자산 복호화를 매 지도 요청마다 돌리지 않기 위해서다.
    if budget == BUDGET_MINE:
        budget_at, budget_info = _resolve_map_budget(
            repo, user=user, settings=settings, purpose=purpose)
    else:
        budget_at, budget_info = None, _budget_block(False)

    rows = repo.complexes_in_bbox(
        # ⚠️ `max_price_krw` 를 **넘기지 않는다.** 두 리포지토리 모두 이 값으로 거르지
        #    않는 것이 결정이고(ux/README.md §4 — 왜 후보에 없는지 보이게 한다),
        #    그 위에 이제는 **넘길 단일 금액 자체가 없다**: 상한이 단지 면적마다
        #    다르고(CR37-1), 그 면적은 이 조회의 **결과**다. 조회 전에 알 수 없는 값을
        #    여기 지어내지 않는다.
        min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat,
        area_min_m2=area_min_m2,
        area_max_m2=area_max_m2, built_after=built_after,
    )

    if zoom < CLUSTER_ZOOM_THRESHOLD:
        clusters: dict[str, dict[str, Any]] = {}
        for c in rows:
            g = clusters.setdefault(c.region_code, {
                "region_code": c.region_code, "count": 0,
                "lon_sum": 0.0, "lat_sum": 0.0, "prices": [],
            })
            g["count"] += 1
            g["lon_sum"] += c.lon
            g["lat_sum"] += c.lat
            if c.recent_price_krw:
                g["prices"].append(c.recent_price_krw)
        items = []
        for g in clusters.values():
            prices = sorted(g["prices"])
            items.append({
                "region_code": g["region_code"],
                "count": g["count"],
                "center": [round(g["lon_sum"] / g["count"], 6),
                           round(g["lat_sum"] / g["count"], 6)],
                "median_price_krw": prices[len(prices) // 2] if prices else None,
                # 군집 중위도 **최근 체결가들의 중위**다(시점 보정도, 면적 통일도 없다).
                # 단지 항목과 같은 이름을 쓴다 — 이름이 다르면 프론트가 두 벌로 해석한다.
                "price_basis": PRICE_BASIS_LATEST_TRADE,
            })
        return {"level": "cluster", "items": items,
                # 군집에는 예산 판정이 없다(중위값 하나로 초과를 말할 수 없다).
                # 그래도 **기준이 걸렸는지**는 말한다 — 줌아웃했다고 조건이 사라진
                # 것처럼 보이면 사용자는 조건이 풀린 줄 안다.
                "budget": budget_info,
                "price_basis_note": MAP_PRICE_BASIS_NOTE}

    return {
        "level": "complex",
        "items": [
            {
                "id": c.id,
                "name": c.name,
                "point": [c.lon, c.lat],
                "households": c.total_households,
                "built_year": c.built_year,
                "recent_price_krw": c.recent_price_krw,
                # 실거래 신고 지연이 있으므로 '현재가'라고 말하지 않는다.
                "price_as_of": c.price_as_of,
                # 이 금액이 **어느 면적**의 체결가인지. null 이면 금액도 null 이다.
                # 면적을 안 주면 화면은 그 값을 사용자가 보는 평형의 값으로 읽는다(CR34-3).
                "price_area_m2": c.price_area_m2,
                # 값의 **근거**. 추천 카드는 `time_adjusted_band` 라 이름부터 다르다.
                # 금액이 없으면 근거도 없다(null) — 없는 근거를 이름 붙이지 않는다.
                "price_basis": (PRICE_BASIS_LATEST_TRADE
                                if c.recent_price_krw else None),
                "price_confidence": "estimated" if c.recent_price_krw else "unknown",
                "active_listings": c.active_listings,
                # `null` = **판정 못 함**(예산 기준이 없거나, 이 단지의 가격을 모르거나,
                # 그 가격이 **어느 면적**의 거래인지 몰라 한도를 못 세움).
                # false 로 접으면 "예산 안"과 구분이 사라진다(SR32-1 · G2).
                # ⚠️ 상한은 **이 항목의 `price_area_m2` 로** 계산한다 — 같은 단지·같은
                #    면적으로 부른 `/affordability` 의 `max_purchase_krw` 와 같은 값이다
                #    (CR37-1: 한 숫자로 여러 면적을 판정하면 85㎡ 경계에서 갈린다).
                "over_budget": _item_over_budget(c, budget_at),
                # --- 화면 배지용 값 (MAP-2) --------------------------------
                # 추천 카드(`RecommendationItem`)와 **같은 이름·같은 모양**이다.
                # 지도와 추천이 다른 이름을 쓰면 프론트가 태그 판정을 두 벌 갖게 되고,
                # 두 벌은 반드시 어긋난다(임계값은 프론트 `lib/tags.ts` 한 곳에 있다).
                **_map_tag_facts(c),
            }
            for c in rows
        ],
        # ⚠️ 30일은 **신고기한**이지 API 공개 지연이 아니다(CR34-4). 계약 후 30일까지
        #    신고할 수 있고, 신고분이 공개 API 에 실리기까지는 그 위에 며칠이 더 걸린다
        #    — 우리는 그 며칠을 측정하지 않았으므로 숫자로 말하지 않는다.
        "note": ("실거래는 계약일로부터 30일 이내에 신고하게 되어 있고, 신고분이 공개되기까지 "
                 "시간이 더 걸립니다. 최근 거래가 아직 반영되지 않았을 수 있습니다."),
        # 예산 기준을 **적용했는지·무엇으로 했는지·못 했으면 왜인지**. 금액은 싣지 않는다.
        "budget": budget_info,
        # 항목마다 반복하지 않고 여기 한 번 — 500단지 × 같은 문장은 64KiB 다(MAP-2).
        "redevelopment_note": REDEV_MAP_UNKNOWN_NOTE,
        # 같은 단지가 추천 카드에서 다른 금액으로 보이는 이유를 **서버가 말한다**(CR34-3).
        "price_basis_note": MAP_PRICE_BASIS_NOTE,
    }


# ---------------------------------------------------------------------------
# 추천 (F1·F3·F6) — 비동기
# ---------------------------------------------------------------------------

@router.post("/recommendations", status_code=status.HTTP_202_ACCEPTED, tags=["analysis"])
def create_recommendation(body: schemas.RecommendationIn, user: CurrentUser,
                          response: Response, background_tasks: BackgroundTasks,
                          settings: SettingsDep,
                          repo=Depends(get_repo)) -> dict[str, Any]:
    """작업을 큐에 넣고 즉시 202. 분석은 **인프로세스 BackgroundTask** 로 돈다.

    배포 최소구성이 redis 없는 api+db 라 별도 워커/큐를 두지 않는다(개인용, 동시성 낮음).
    러너가 프로필 복호화·후보 조회·파이프라인·저장을 맡고, GET 으로 결과를 폴링한다.

    ⚠️ **LLM 을 여기서 주입한다.** 예전에는 `llm=` 을 넘기지 않아 파이프라인이 항상
    `None` 을 받았고, 그래서 "AI 추천"이 실제로는 언제나 규칙 기반 요약이었다.
    키가 없으면 `build_llm` 이 `None` 을 돌려주고 동작은 그대로다 —
    **다만 그 사실이 결과 `notes` 에 남는다**(조용히 규칙 기반으로 도는 상태를 없앤다).
    """
    # 면적 조건이 뒤집혀 있으면 여기서 거절한다 — 지도와 **같은 규칙**(400).
    # 접수한 뒤 러너가 조용히 무시하면, 사용자는 조건이 걸린 줄 알고 결과를 읽는다.
    _check_area_range(body.area_min_m2, body.area_max_m2)

    job_id = "rec_" + secrets.token_urlsafe(16)
    criteria = body.model_dump()
    criteria["requested_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    repo.create_job(job_id, user.id, criteria)

    # 세율/키 로드·복호화는 러너 안에서(BackgroundTask 는 Depends 를 못 받는다).
    # 실패해도 요청은 202 로 접수되고, 러너가 job 을 'error' 로 남긴다.
    background_tasks.add_task(
        run_recommendation_job, repo=repo, settings=settings,
        job_id=job_id, user_id=user.id, criteria=criteria,
        # 키가 없으면 None → 규칙 기반. 키 값은 로그·응답 어디에도 싣지 않는다.
        llm=build_llm(settings),
    )

    response.headers["Location"] = f"/api/v1/recommendations/{job_id}"
    return {
        "job_id": job_id,
        "status": "queued",
        "poll_url": f"/api/v1/recommendations/{job_id}",
        "note": "분석을 시작했습니다. 잠시 후 결과를 조회하세요.",
    }


@router.get("/recommendations/{job_id}", tags=["analysis"])
def get_recommendation(job_id: str, user: CurrentUser,
                       repo=Depends(get_repo)) -> dict[str, Any]:
    # 소유권 검증은 리포지토리가 강제한다 (IDOR — security.md §2.2).
    job = repo.get_job(job_id, user.id)
    if job is None:
        # 남의 작업이 존재한다는 사실조차 알려주지 않는다 → 404 로 통일
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "작업을 찾을 수 없습니다"},
        )
    return {
        "job_id": job.id,
        "status": job.status,
        "criteria_snapshot": job.criteria_snapshot,
        "items": job.items,
        # 추천 목록은 답의 절반이다. 나머지 절반이 **"왜 저건 없는가"** 다 —
        # 제외된 후보와 사유를 함께 준다(빈 목록과 "안 내려줌"은 다른 뜻이다).
        "excluded": job.excluded,
        "notes": job.notes,
        "disclaimer": "투자 권유가 아니며 개인 판단을 돕는 참고 자료입니다.",
    }


# ---------------------------------------------------------------------------
# 관리자 — 가입 승인 (migrations/009)
#
# 인가 규약
# ---------
# * 권한은 **요청 시점에 DB 의 `app_user.is_admin` 으로** 판정한다(`deps.admin_user`).
#   JWT 에 admin 클레임을 넣지 않는다 — 토큰에 실린 권한은 클라이언트의 주장이고,
#   서명이 유효해도 **강등된 뒤에도 유효**하다.
# * 관리자가 아닌 모든 접근(토큰 없음·만료·일반 사용자·승인 대기)은 **동일한 404** 다.
#   403 으로 답하면 "여기 관리 기능이 있다"를 알려주는 셈이라, 모르는 경로와
#   구분되지 않게 맞춘다(deps.admin_not_found).
# * 사용자 자원 접근이지만 IDOR 규약(security.md §2.2)의 예외가 아니다 —
#   여기서는 "관리자"라는 역할이 소유권을 대신하고, 그 역할을 서버가 검증한다.
# ---------------------------------------------------------------------------

def _admin_user_out(user) -> schemas.AdminUserOut:
    return schemas.AdminUserOut(
        id=user.id, email=user.email, status=user.status, is_admin=user.is_admin,
        created_at=user.created_at, status_changed_at=user.status_changed_at,
        status_changed_by=user.status_changed_by, status_reason=user.status_reason,
    )


def _set_status(repo, admin, user_id: int, new_status: str,
                reason: str | None = None) -> schemas.AdminUserOut:
    """승인·거부 공통. 실패는 전부 **존재를 숨기는 404** 로 통일한다."""
    try:
        updated = repo.set_user_status(
            user_id, new_status,
            actor="admin_api", actor_user_id=admin.id, reason=reason,
        )
    except LastAdminError as exc:
        # 마지막 관리자를 스스로 잠그는 것을 막는다. 이건 숨길 정보가 아니라
        # **왜 안 되는지 알려줘야 하는** 상황이라 404 로 덮지 않는다.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "LAST_ADMIN", "message": str(exc)},
        ) from exc
    if updated is None:
        raise admin_not_found()
    return _admin_user_out(updated)


@router.get("/admin/users", tags=["admin"])
def admin_list_users(admin: AdminUser, repo=Depends(get_repo),
                     user_status: str | None = Query(
                         default=None, alias="status",
                         pattern="^(pending|approved|rejected)$"),
                     limit: int = Query(default=100, ge=1, le=500),
                     ) -> schemas.AdminUserListOut:
    """가입 대기 목록. 기본은 전체이며 `?status=pending` 으로 좁힌다.

    응답에는 이메일·상태·감사 흔적만 담는다 — 비밀번호 해시도, 자산 금액도 넘기지 않는다
    (AdminUserOut 이 마지막 문이다).
    """
    users = repo.list_users(status=user_status, limit=limit)
    return schemas.AdminUserListOut(
        items=[_admin_user_out(u) for u in users],
        active_admins=repo.count_active_admins(),
    )


@router.post("/admin/users/{user_id}/approve", tags=["admin"])
def admin_approve_user(user_id: int, admin: AdminUser,
                       repo=Depends(get_repo)) -> schemas.AdminUserOut:
    return _set_status(repo, admin, user_id, STATUS_APPROVED)


@router.post("/admin/users/{user_id}/reject", tags=["admin"])
def admin_reject_user(user_id: int, body: schemas.RejectIn, admin: AdminUser,
                      repo=Depends(get_repo)) -> schemas.AdminUserOut:
    """거부. 이미 승인된 계정을 되돌리는 데도 쓴다(접근 회수).

    ⚠️ 마지막 관리자는 거부되지 않는다 — 관리자가 0명이 되면 어떤 가입도 승인할 수
    없고, 복구하려면 서버에 SSH 로 들어가야 한다(리포지토리가 `LastAdminError`).
    """
    return _set_status(repo, admin, user_id, STATUS_REJECTED, reason=body.reason)


#: ⚠️ **반드시 위 관리자 라우트들보다 뒤에 있어야 한다.**
#: Starlette 은 경로가 맞고 메서드가 다르면 405 를 주는데, 그 405 자체가
#: "여기 라우트가 있다"는 신호다(`PUT /admin/users` → 405 vs 없는 경로 → 404).
#: 이 포괄 라우트가 남은 메서드·하위경로를 전부 받아 **모르는 경로와 같은 404** 로 맞춘다.
#: (Starlette 은 완전 일치를 먼저 찾으므로 위의 정상 라우트를 가리지 않는다.)
@router.api_route("/admin/{rest:path}", include_in_schema=False,
                  methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def admin_catch_all(rest: str) -> None:
    raise admin_not_found()
