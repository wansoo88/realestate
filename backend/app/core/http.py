"""응답 본문을 **상한을 걸어** 읽는다 — 컨테이너 안에서 도는 경로용 (SR25-1).

왜 `scripts/_common.py` 와 따로 있는가
--------------------------------------
`scripts/_common.py` 의 `capped_get` 은 **호스트에서 사람이 손으로 돌리는 수집기**용이고
컨테이너 이미지에 들어가지 않는다(`Dockerfile` 은 `app/` 만 복사한다). 그런데 실제로
응답을 통째로 메모리에 올리던 세 곳은 **api·worker 컨테이너 안**에 있었다:

    app/ingest/run_molit.py   MOLIT 실거래 XML     (worker · mem_limit 192m)
    app/ingest/geocode.py     카카오 로컬 JSON     (api · worker)
    app/agents/llm.py         Claude API 응답      (worker)

세 경로 모두 `resp.text` / `resp.json()` 이었고, 그건 `.content` 와 똑같이 본문을
**전부 읽은 뒤** 문자열로 바꾸는 것이다. 상한이 없으면 원천이 바뀌거나 중간 프록시가
오류 스트림을 내보낼 때 컨테이너가 OOM 으로 죽는다(그리고 그 죽음은 추천 job 이
말없이 사라지는 형태로 나타난다 — 이 프로젝트가 가장 경계하는 조용한 실패다).

핵심은 **스트리밍**이다. `httpx.get(...)` 은 돌아온 시점에 이미 본문을 다 읽었으므로
그 뒤에 무엇을 검사해도 늦다. `client.stream(...)` + `iter_bytes()` 로 받으면서 센다.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

#: 한 응답에서 받아들이는 본문 상한(바이트).
#: 이 세 경로의 정상 응답은 실측 수백 KB 이하다(MOLIT 는 `numOfRows` 상한, 카카오 로컬은
#: 최대 15건, Claude 는 `max_tokens` 상한). 16MB 는 정상 수집을 막지 않으면서
#: "원천이 바뀌었다"를 잡는 선이다. 수집 스크립트(96MB, 학구도 shp)와는 성격이 다르다.
MAX_RESPONSE_BYTES = 16 * 1024 * 1024

#: 한 번에 읽는 덩어리. 초과분은 이 크기 안으로 한정된다.
_CHUNK = 256 * 1024


class ResponseTooLarge(RuntimeError):
    """응답 본문이 상한을 넘었다. **끝까지 읽지 않고** 중단한다."""


def read_capped(chunks: Iterable[bytes], *, max_bytes: int | None = None,
                what: str = "응답", declared: Any = None) -> bytes:
    """바이트 덩어리 이터러블을 **상한까지만** 모은다.

    `max_bytes=None` 이면 **호출 시점에** `MAX_RESPONSE_BYTES` 를 읽는다(기본값으로
    박아 두면 테스트가 상한을 낮춰 실제 중단을 확인할 방법이 없다 — 그러면 "상한이
    있다"만 검증하고 "상한이 듣는다"는 검증하지 못한다).

    `declared` 는 Content-Length 헤더값(있으면). 있으면 한 바이트도 읽기 전에 막는다.
    상한을 넘으면 `ResponseTooLarge` — 잘린 본문을 정상인 척 돌려주지 않는다
    (잘린 XML·JSON 은 파싱 오류로 드러나기라도 하지만, 잘린 CSV 는 '행만 적은 정상'으로
     위장한다. 어느 쪽이든 자르지 않는 편이 낫다).
    """
    max_bytes = MAX_RESPONSE_BYTES if max_bytes is None else max_bytes
    if declared is not None:
        text = str(declared).strip()
        if text.isdigit() and int(text) > max_bytes:
            raise ResponseTooLarge(
                f"{what}: 응답 크기 {int(text):,}바이트가 상한 {max_bytes:,}바이트를 "
                "넘습니다 — 원천이 바뀌었는지 확인하세요.")
    buf = bytearray()
    for chunk in chunks:
        if not chunk:
            continue
        buf += chunk
        if len(buf) > max_bytes:
            raise ResponseTooLarge(
                f"{what}: 응답이 상한 {max_bytes:,}바이트를 넘어 중단했습니다 "
                "— 원천이 바뀌었는지 확인하세요(잘린 본문을 쓰지 않습니다).")
    return bytes(buf)


def request_capped(client: Any, method: str, url: str, *, what: str = "응답",
                   max_bytes: int | None = None,
                   raise_for_status: bool = True,
                   read_error_body: bool = False,
                   **kwargs: Any) -> tuple[Any, bytes]:
    """스트리밍 요청 → (응답 객체, 상한까지 읽은 본문 바이트).

    `client` 는 `httpx` 모듈 자체여도 되고 `httpx.Client` 여도 된다 — 둘 다 `stream()` 을
    같은 모양으로 갖는다(테스트 대역도 이 한 가지만 흉내 내면 된다).

    ``raise_for_status=False`` 는 호출부가 상태코드를 **직접** 다루는 경우다
    (`llm.py` 는 4xx/5xx 를 재시도 정책으로 나눈다). 그때 오류 응답의 본문은 기본적으로
    **읽지 않는다** — 오류 본문에는 우리가 보낸 프롬프트가 되비쳐 나올 수 있고,
    읽어서 로그·예외에 실으면 그게 유출 경로가 된다(`read_error_body` 로만 켠다).

    반환하는 응답 객체는 컨텍스트를 벗어난 뒤에도 `status_code`·`headers` 를 갖는다
    (본문은 이미 여기서 다 읽었으므로 다시 읽지 않는다).
    """
    with client.stream(method, url, **kwargs) as resp:
        if raise_for_status:
            resp.raise_for_status()
        elif resp.status_code >= 400 and not read_error_body:
            return resp, b""
        declared = None
        headers = getattr(resp, "headers", None)
        if headers is not None:
            declared = headers.get("content-length")
        body = read_capped(resp.iter_bytes(_CHUNK), max_bytes=max_bytes,
                           what=what, declared=declared)
    return resp, body
