"""refresh 토큰 쿠키 — 발급·회전·삭제를 **한 곳**에서 만든다.

설계 근거: `docs/02-design/security.md` §2.1, 보안리뷰 `SR15-1`

왜 쿠키인가
-----------
refresh 를 응답 본문으로 주면 클라이언트는 그것을 어딘가에 **저장해야 한다.** 웹에서
그 어딘가는 결국 `localStorage`(또는 JS 가 읽는 어떤 것)가 되고, XSS 한 번에 통째로 털린다.
`httpOnly` 쿠키는 JS 가 값을 읽을 수 없어 같은 사고에서도 refresh 가 살아남는다.

속성이 각각 막는 것
-------------------
| 속성 | 없으면 생기는 일 |
|---|---|
| `HttpOnly` | XSS 스크립트가 `document.cookie` 로 refresh 를 읽어간다 |
| `Secure` | 평문 HTTP 요청에 쿠키가 실려 중간자에게 노출된다 |
| `SameSite=Strict` | 다른 사이트에서 온 요청에 브라우저가 쿠키를 자동 첨부한다(= CSRF 성립) |
| `Path=/api/v1/auth` | 지도·추천 등 **모든** 요청에 refresh 가 따라다닌다(불필요한 노출면 확대) |

CSRF 는 `SameSite=Strict` 가 1차 방어이고, `deps.require_ajax_header` 의 커스텀 헤더
요구가 2차 방어다(HTML 폼으로는 커스텀 헤더를 붙일 수 없다).
"""
from __future__ import annotations

from fastapi import Response

from app.core.config import Settings
from app.core.security import REFRESH_TTL_SECONDS

#: 쿠키 이름. 프론트는 이 값을 읽지 못한다(httpOnly) — 계약상 이름만 고정한다.
REFRESH_COOKIE_NAME = "refresh_token"

#: 쿠키가 전송되는 유일한 경로. `/api/v1/auth/*` 밖에서는 브라우저가 보내지 않는다.
REFRESH_COOKIE_PATH = "/api/v1/auth"

#: 대소문자를 브라우저는 가리지 않지만, API 계약서에 적힌 표기와 응답을 맞춘다.
_SAMESITE = "Strict"


def set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    """refresh 쿠키를 심는다(로그인·회전 공통)."""
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        token,
        max_age=REFRESH_TTL_SECONDS,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=_SAMESITE,
    )


def delete_refresh_cookie(response: Response, settings: Settings) -> None:
    """쿠키를 즉시 만료시킨다(`Max-Age=0`).

    ⚠️ 삭제도 **발급과 똑같은 이름·Path·속성**이어야 한다. 하나라도 다르면 브라우저는
    다른 쿠키로 보고 원본을 그대로 남긴다 — 로그아웃이 연출로 끝난다.
    """
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=_SAMESITE,
    )


def expired_refresh_cookie_header(settings: Settings) -> dict[str, str]:
    """401 처럼 **예외로 빠져나가는 응답**에 붙일 삭제 헤더.

    `HTTPException` 은 라우터가 주입받은 `Response` 의 헤더를 물려받지 않는다.
    그래서 헤더 문자열을 직접 만들어 넘기는데, 손으로 조립하지 않고
    `delete_refresh_cookie` 를 그대로 태워서 **속성이 어긋날 여지를 없앤다.**
    """
    probe = Response()
    delete_refresh_cookie(probe, settings)
    return {"set-cookie": probe.headers["set-cookie"]}
