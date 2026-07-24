"""LLM 클라이언트 추상화.

에이전트 로직을 실제 API 호출과 분리한다. 그래야
① 키 없이 테스트할 수 있고 ② 개발 중 비용이 안 나가고 ③ 응답 검증을 강제할 수 있다.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger("agents.llm")


class LLMError(RuntimeError):
    pass


@runtime_checkable
class LLMClient(Protocol):
    def complete_json(self, *, system: str, user: str,
                      max_tokens: int = 1024) -> dict[str, Any]:
        """JSON 객체를 반환한다. 스키마 검증은 호출부 책임."""
        ...


class FakeLLM:
    """테스트·개발용. 미리 정한 응답을 순서대로 돌려주고 호출 내역을 남긴다."""

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[dict[str, str]] = []

    def complete_json(self, *, system: str, user: str,
                      max_tokens: int = 1024) -> dict[str, Any]:
        self.calls.append({"system": system, "user": user})
        if not self._responses:
            # 응답을 안 정해놨으면 조용히 빈 값을 주지 않고 실패한다.
            raise LLMError("FakeLLM 에 준비된 응답이 없습니다")
        return self._responses.pop(0)


class AnthropicLLM:
    """실제 Claude API 클라이언트 (얇은 래퍼).

    ⚠️ 이 클래스는 **실호출 검증이 되지 않았다** — 개발 환경에 API 키가 없다.
       배포 전 실호출 스모크 테스트가 필요하다.
    """

    def __init__(self, api_key: str, model: str, *, timeout: float = 60.0) -> None:
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY 가 없습니다")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def complete_json(self, *, system: str, user: str,
                      max_tokens: int = 1024) -> dict[str, Any]:
        import httpx

        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
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
        if resp.status_code >= 400:
            # 응답 본문에 프롬프트가 되비쳐 나올 수 있으므로 로그에 싣지 않는다.
            raise LLMError(f"Claude API 오류 status={resp.status_code}")

        try:
            blocks = resp.json()["content"]
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (KeyError, ValueError) as exc:
            raise LLMError("Claude API 응답 형식을 해석할 수 없습니다") from exc

        return parse_json_object(text)


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
