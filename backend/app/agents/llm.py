"""LLM 클라이언트 추상화.

에이전트 로직을 실제 API 호출과 분리한다. 그래야
① 키 없이 테스트할 수 있고 ② 개발 중 비용이 안 나가고 ③ 응답 검증을 강제할 수 있다.

⚠️ 이 모듈이 **이 제품에서 유일하게 사용자 데이터를 외부로 내보내는 경로**다.
그래서 세 가지를 여기서 강제한다:

1. **키가 새지 않는다** — 예외·로그 문자열은 전부 `app.core.masking.mask_secrets` 를
   거친다. 응답 본문·요청 헤더는 어떤 경우에도 메시지에 싣지 않는다(본문에는 프롬프트가
   되비쳐 나올 수 있고, 헤더에는 키가 들어 있다).
2. **무한정 커지지 않는다** — 출력 토큰 상한(`MAX_OUTPUT_TOKENS`)과 입력 길이
   상한(`MAX_PROMPT_CHARS`)이 있다. 상한을 넘으면 **자르지 않고 폐기**한다 —
   근거를 잘라 요약하면 그 요약은 근거와 어긋난다(G2).
3. **영원히 기다리지 않는다** — 타임아웃 + 유한 재시도. 이 호출은 API 프로세스 안의
   BackgroundTask 에서 돌기 때문에, 여기서 오래 붙잡으면 추천 전체가 멈춘다.
"""
from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Protocol, runtime_checkable

from app.core.masking import mask_secrets

logger = logging.getLogger("agents.llm")

#: 요약 1건의 출력 토큰 상한. 요약은 몇 문장이면 되고, 길어질수록 비용만 는다.
DEFAULT_MAX_TOKENS = 900
#: 호출부가 뭘 넘기든 이 위로는 못 올린다(스키마를 우회하는 호출부가 비용을 키우지 못하게).
MAX_OUTPUT_TOKENS = 2048

#: 입력 프롬프트 길이 상한(문자). 한국어는 대략 1자 ≈ 1토큰 안팎이라
#: 2만 자면 입력 2만 토큰 수준이다. 이 위는 요약 1건에 쓸 값이 아니다.
#: **넘으면 자르지 않고 규칙 기반으로 폴백**한다(잘린 근거로 만든 요약은 근거가 아니다).
MAX_PROMPT_CHARS = 20_000

#: 재시도해도 되는 상태코드 — **일시적 장애만**. 400/401/403 은 다시 보내도 같고,
#: 키가 틀린 상태로 재시도하면 비용 없이 시간만 태운다.
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
#: 총 시도 횟수(최초 1 + 재시도 2). 늘리면 실패 경로의 지연이 그대로 늘어난다.
DEFAULT_MAX_ATTEMPTS = 3
#: 지수 백오프 기준(초)과 대기 상한. `retry-after` 가 이보다 길면 재시도를 포기한다 —
#: 사용자를 기다리게 하느니 규칙 기반 요약을 주는 게 낫다.
DEFAULT_BACKOFF_SEC = 0.5
MAX_RETRY_WAIT_SEC = 4.0
#: HTTP 타임아웃(초). BackgroundTask 안에서 도는 호출이라 짧게 잡는다.
DEFAULT_TIMEOUT_SEC = 30.0


class LLMError(RuntimeError):
    """LLM 호출이 실패했다. **메시지에 키·프롬프트·응답 본문을 담지 않는다.**"""


@runtime_checkable
class LLMClient(Protocol):
    def complete_json(self, *, system: str, user: str,
                      max_tokens: int = DEFAULT_MAX_TOKENS) -> dict[str, Any]:
        """JSON 객체를 반환한다. 스키마 검증은 호출부 책임."""
        ...


class FakeLLM:
    """테스트·개발용. 미리 정한 응답을 순서대로 돌려주고 호출 내역을 남긴다.

    `calls` 에 **실제로 나간 프롬프트**가 그대로 남는다 — SR4-2 회귀 테스트는
    이걸 읽어 자산 원본이 나갔는지 검사한다. 그러니 여기서 프롬프트를 가공하지 말 것.
    """

    def __init__(self, responses: list[dict[str, Any]] | None = None, *,
                 repeat: dict[str, Any] | None = None) -> None:
        self._responses = list(responses or [])
        #: 소진 후에도 계속 돌려줄 응답. 여러 후보를 도는 파이프라인 테스트용.
        self._repeat = repeat
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, *, system: str, user: str,
                      max_tokens: int = DEFAULT_MAX_TOKENS) -> dict[str, Any]:
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        if self._responses:
            return self._responses.pop(0)
        if self._repeat is not None:
            return dict(self._repeat)
        # 응답을 안 정해놨으면 조용히 빈 값을 주지 않고 실패한다.
        raise LLMError("FakeLLM 에 준비된 응답이 없습니다")


class RetryableLLMError(LLMError):
    """일시적 장애(타임아웃·429·5xx). 유한 횟수 재시도 후에도 실패하면 폴백한다."""


class AnthropicLLM:
    """실제 Claude API 클라이언트 (얇은 래퍼).

    ⚠️ 이 클래스는 **실호출 검증이 되지 않았다** — 개발 환경에 API 키가 없다.
       배포 전 실호출 스모크 테스트가 필요하다.

    실패 정책
    ---------
    타임아웃·429·5xx 는 `RETRYABLE_STATUS` 기준으로 최대 `max_attempts` 번까지
    지수 백오프 + 지터로 다시 보낸다. 그래도 안 되면 `LLMError` 로 올리고,
    **호출부(`portfolio_summary`)가 규칙 기반으로 폴백**한다 — LLM 장애가 추천 전체를
    죽이지 않는다. 4xx(키 오류 등)는 재시도하지 않는다: 다시 보내도 같은 답이고,
    사용자를 기다리게 할 뿐이다.
    """

    ENDPOINT = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str, *,
                 timeout: float = DEFAULT_TIMEOUT_SEC,
                 max_attempts: int = DEFAULT_MAX_ATTEMPTS,
                 backoff_sec: float = DEFAULT_BACKOFF_SEC) -> None:
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY 가 없습니다")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._max_attempts = max(1, int(max_attempts))
        self._backoff_sec = max(0.0, float(backoff_sec))

    # -- 키가 문자열로 새지 않게 --------------------------------------------
    #
    # repr/str 은 예외 메시지·로그·디버거에 그대로 찍힌다. 기본 구현이면
    # `<AnthropicLLM object at 0x...>` 라 안전하지만, 누군가 dataclass 로 바꾸거나
    # `vars()` 를 찍는 순간 키가 나온다. 명시적으로 막아 둔다.
    def __repr__(self) -> str:                      # pragma: no cover - 표현용
        return f"AnthropicLLM(model={self._model!r}, api_key=***)"

    __str__ = __repr__

    def complete_json(self, *, system: str, user: str,
                      max_tokens: int = DEFAULT_MAX_TOKENS) -> dict[str, Any]:
        # 호출부가 뭘 넘기든 상한을 넘기지 않는다(비용 방어의 마지막 문).
        capped = max(1, min(int(max_tokens), MAX_OUTPUT_TOKENS))
        if len(user) + len(system) > MAX_PROMPT_CHARS:
            # 자르지 않는다 — 잘린 근거로 만든 요약은 근거와 어긋난다.
            raise LLMError(
                f"프롬프트가 상한({MAX_PROMPT_CHARS}자)을 넘어 호출하지 않았습니다")

        last: LLMError | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return self._once(system=system, user=user, max_tokens=capped)
            except RetryableLLMError as exc:
                last = exc
                if attempt >= self._max_attempts:
                    break
                wait = self._wait_for(attempt, exc)
                if wait is None:
                    break                       # 너무 오래 기다려야 한다 → 폴백이 낫다
                # ⚠️ 예외 메시지는 이미 마스킹된 것만 남긴다(상태코드 수준).
                logger.warning("LLM 호출 재시도 %d/%d (%s)",
                               attempt, self._max_attempts, exc)
                time.sleep(wait)
        raise last or LLMError("LLM 호출에 실패했습니다")

    # -- 내부 --------------------------------------------------------------

    def _wait_for(self, attempt: int, exc: RetryableLLMError) -> float | None:
        """다음 재시도까지 대기(초). 상한을 넘겨야 하면 None(=포기)."""
        hinted = getattr(exc, "retry_after", None)
        if hinted is not None:
            return None if hinted > MAX_RETRY_WAIT_SEC else float(hinted)
        # 지수 백오프 + 지터(동시 재시도가 겹치지 않게).
        base = self._backoff_sec * (2 ** (attempt - 1))
        return min(MAX_RETRY_WAIT_SEC, base) * (1.0 + random.random() * 0.25)

    def _once(self, *, system: str, user: str, max_tokens: int) -> dict[str, Any]:
        import httpx

        try:
            resp = httpx.post(
                self.ENDPOINT,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001 - httpx 예외 계층에 의존하지 않는다
            # 네트워크 예외 문자열에는 URL 이 들어간다. 키는 헤더라 안 들어가지만,
            # 라이브러리가 바뀌어도 새지 않도록 **무조건** 마스킹을 거친다.
            raise RetryableLLMError(
                "Claude API 연결 실패: " + mask_secrets(type(exc).__name__)) from None

        if resp.status_code >= 400:
            # 응답 본문에 프롬프트가 되비쳐 나올 수 있으므로 **본문을 싣지 않는다.**
            # 남기는 것은 상태코드뿐이다.
            if resp.status_code in RETRYABLE_STATUS:
                err = RetryableLLMError(f"Claude API 일시 오류 status={resp.status_code}")
                err.retry_after = _retry_after_sec(resp)   # type: ignore[attr-defined]
                raise err
            raise LLMError(f"Claude API 오류 status={resp.status_code}")

        try:
            blocks = resp.json()["content"]
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (KeyError, ValueError, TypeError) as exc:
            raise LLMError("Claude API 응답 형식을 해석할 수 없습니다") from exc

        return parse_json_object(text)


def _retry_after_sec(resp: Any) -> float | None:
    """`retry-after` 헤더(초). 없거나 해석 불가면 None(=백오프 사용)."""
    try:
        raw = resp.headers.get("retry-after")
    except Exception:  # noqa: BLE001
        return None
    if not raw:
        return None
    try:
        return max(0.0, float(str(raw).strip()))
    except ValueError:
        # HTTP-date 형식은 해석하지 않는다 — 보통 매우 긴 값이라 폴백이 낫다.
        return MAX_RETRY_WAIT_SEC + 1.0


def build_llm(settings: Any) -> LLMClient | None:
    """설정에서 LLM 클라이언트를 만든다. **키가 없으면 None** (예외가 아니다).

    키가 없다고 추천이 죽으면 안 된다 — 순위·근거는 규칙과 통계로 계산되고,
    LLM 은 그 위에 **요약 문장만** 얹는다. 그래서 키가 없으면 조용히 규칙 기반으로
    돌되, 그 사실은 결과 `notes` 로 사용자에게 말한다(`orchestrator.NOTE_LLM_DISABLED`).

    ⚠️ 키 값을 로그에 찍지 않는다. 남기는 것은 **있다/없다와 모델명**뿐이다.
    """
    key = str(getattr(settings, "anthropic_api_key", "") or "").strip()
    if not key:
        logger.info("ANTHROPIC_API_KEY 미설정 — 요약은 규칙 기반으로 동작합니다")
        return None

    model = str(getattr(settings, "claude_model", "") or "").strip()
    if not model:
        logger.warning("CLAUDE_MODEL 이 비어 LLM 을 연결하지 않습니다(규칙 기반으로 동작)")
        return None

    try:
        client = AnthropicLLM(key, model)
    except LLMError as exc:
        logger.warning("LLM 클라이언트 생성 실패 — 규칙 기반으로 동작합니다: %s", exc)
        return None
    logger.info("LLM 연결: model=%s (키는 로그에 남기지 않습니다)", model)
    return client


def parse_json_object(text: str) -> dict[str, Any]:
    """모델 출력에서 JSON 객체를 꺼낸다. 실패하면 조용히 넘어가지 않는다."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise LLMError("응답에서 JSON 객체를 찾지 못했습니다")
    try:
        obj = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"JSON 파싱 실패: {exc}") from exc
    if not isinstance(obj, dict):
        raise LLMError("최상위가 JSON 객체가 아닙니다")
    return obj
