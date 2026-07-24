"""robots.txt 준수 게이트 (골격).

설계 근거: docs/02-design/security.md §1(수집 데이터) · SR-004 SR4-3 · CHARTER §4(G4)

왜 필요한가
-----------
포털(호가) 수집에 착수하기 **전에** robots.txt 로 해당 경로가 허용되는지 확인한다.
금지 경로를 긁으면 이용약관 위반이자 차단 사유이고, 프로젝트 전체가 법적 리스크에 놓인다.
"애매하면 안 하는 쪽"(re-data.md)이 원칙이므로, 이 게이트는 **불확실하면 거부**한다.

경계
----
- 이 모듈은 '허용 여부 판정'만 한다. 실제 포털 수집기는 PM 승인(requires_review) 전까지 없다.
- 표준 라이브러리 `urllib.robotparser` 를 쓰되, 네트워크 fetch 는 주입 가능하게 해
  테스트에서 실제 요청 없이 검증한다.
"""
from __future__ import annotations

import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


def robots_url_for(url: str) -> str:
    """주어진 URL 의 스킴·호스트에서 robots.txt 위치를 만든다."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"절대 URL 이 필요합니다: {url!r}")
    return urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))


@dataclass
class RobotsDecision:
    allowed: bool
    reason: str
    crawl_delay_sec: float | None = None


class RobotsGate:
    """robots.txt 를 읽어 경로 허용 여부와 crawl-delay 를 판정한다.

    `fetcher` 는 (robots_url) -> 본문 텍스트. 실패(None/예외)하면 **불확실 → 거부**.
    """

    def __init__(
        self,
        user_agent: str,
        *,
        fetcher: Callable[[str], str | None],
        fail_closed: bool = True,
    ) -> None:
        self.user_agent = user_agent
        self._fetch = fetcher
        self._fail_closed = fail_closed
        self._cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _load(self, robots_url: str) -> urllib.robotparser.RobotFileParser | None:
        if robots_url in self._cache:
            return self._cache[robots_url]
        parser: urllib.robotparser.RobotFileParser | None = None
        try:
            body = self._fetch(robots_url)
            if body is not None:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(body.splitlines())
        except Exception:
            parser = None  # 조용히 통과시키지 않는다 — fail-closed 로 이어진다
        self._cache[robots_url] = parser
        return parser

    def check(self, url: str) -> RobotsDecision:
        """이 URL 을 우리 User-Agent 로 수집해도 되는지."""
        try:
            robots_url = robots_url_for(url)
        except ValueError as exc:
            return RobotsDecision(False, f"URL 오류: {exc}")

        parser = self._load(robots_url)
        if parser is None:
            # robots 를 못 읽었다 → 허용 여부 불확실 → 기본 거부(fail-closed)
            allowed = not self._fail_closed
            return RobotsDecision(
                allowed,
                "robots.txt 를 읽지 못함 — " + ("보수적으로 거부" if not allowed else "개방 설정"),
            )

        allowed = parser.can_fetch(self.user_agent, url)
        delay = parser.crawl_delay(self.user_agent)
        return RobotsDecision(
            allowed,
            "robots.txt 허용" if allowed else "robots.txt 금지 경로",
            crawl_delay_sec=float(delay) if delay is not None else None,
        )
