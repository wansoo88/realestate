"""운영 스크립트 위생 검사 — 정적 검사로 재발을 막는다 (SR17-2 / SR17-3).

왜 정적 검사인가
----------------
두 결함 모두 "사람이 기억해야 안 나는" 종류였다:

- SR17-2: 검증 스크립트에 **운영 DB 에서 실제로 통하는 비밀번호**가 상수로 박혀 있었다.
  이 저장소의 origin 은 공개 저장소라, 커밋되는 순간 동작하는 자격증명 공개다(CWE-798).
- SR17-3: 로깅 억제를 스크립트가 **각자 부르게** 되어 있어서, 7개 중 2개만 불렀다.
  하필 MOLIT 인증키를 쿼리스트링으로 보내는 스크립트가 빠져 있었다.

둘 다 "다음에 잘하자"로는 못 닫는다. 그래서 구조를 강제하는 테스트를 둔다.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
SCRIPTS_DIR = BACKEND_DIR / "scripts"

#: 정적 검사 대상 — 운영·배치 코드. 테스트 픽스처는 제외한다(거기 상수는 의도된 더미다).
SOURCE_DIRS = (BACKEND_DIR / "app", SCRIPTS_DIR)

#: 값이 비밀이면 안 되는 변수 이름. `*_ENV`/`*_VAR`/`*_HEADER` 는 **이름을 담는 상수**라 제외.
_SECRET_NAME_RE = re.compile(
    r"(PASSWORD|PASSWD|_PWD|SECRET|APIKEY|API_KEY|ACCESS_KEY|SERVICE_KEY|"
    r"AUTH_TOKEN|ACCESS_TOKEN|REFRESH_TOKEN|PRIVATE_KEY|CREDENTIAL)",
    re.IGNORECASE,
)
_NAME_HOLDER_RE = re.compile(r"_(ENV|VAR|VARS|NAME|NAMES|HEADER|FIELD|FIELDS|KEYS|SUFFIX)$")

#: 환경변수 이름처럼 생긴 값(대문자+밑줄)은 비밀이 아니라 **가리키는 이름**이다.
_ENV_NAME_VALUE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _script_files() -> list[Path]:
    return sorted(p for p in SCRIPTS_DIR.glob("*.py")
                  if p.name not in ("_common.py", "__init__.py"))


# ---------------------------------------------------------------------------
# SR17-2 — 평문 비밀번호 리터럴이 남아 있지 않다
# ---------------------------------------------------------------------------

def test_no_hardcoded_secret_literals_in_app_and_scripts():
    """`NAME = "리터럴"` 형태로 비밀이 소스에 박히지 않았는지 AST 로 확인한다."""
    offenders: list[str] = []
    for root in SOURCE_DIRS:
        for path in _python_files(root):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                value = node.value
                if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    name = getattr(target, "id", None) or getattr(target, "attr", None)
                    if not name or not _SECRET_NAME_RE.search(name):
                        continue
                    if _NAME_HOLDER_RE.search(name):
                        continue                    # 환경변수 '이름'을 담는 상수
                    literal = value.value
                    if len(literal) < 8 or _ENV_NAME_VALUE_RE.match(literal):
                        continue
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno} {name}")
    assert not offenders, (
        "비밀이 소스에 리터럴로 박혀 있습니다(공개 저장소 — 커밋되면 영구 공개):\n  "
        + "\n  ".join(offenders))


def test_verify_recommendation_generates_password_at_runtime():
    """검증 스크립트는 비밀번호를 **실행 시점에** 만들거나 환경변수로 받는다."""
    source = (SCRIPTS_DIR / "verify_recommendation.py").read_text(encoding="utf-8")
    assert "secrets.token_urlsafe" in source
    assert "VERIFY_TEST_PASSWORD" in source
    # 예전 상수의 잔재가 없어야 한다.
    assert "TEST_PASSWORD = " not in source


#: 문서·설정에서 "비밀처럼 보이는 값"을 찾는 패턴.
#:
#: ⚠️ 여기에 **실제 비밀값을 적지 않는다.** 예전 버전은 유출된 비밀번호를
#:    `"앞조각" + "뒷조각"` 형태로 쪼개 적어 두고 그 조각을 찾았는데, 그러면
#:    ① 값이 저장소에 그대로 남고(조각은 이어붙이면 원본이다)
#:    ② 연결된 문자열은 통짜 검색에 안 걸려 **검사기가 자기 자신을 면제**한다.
#:    특정 값을 쫓는 대신 **형태**를 본다 — 새로 생길 비밀도 같이 잡힌다(SR18-3).
#: `TEST_PASSWORD` · `MOLIT_API_KEY` 처럼 **접두사가 붙은 이름**도 잡아야 한다.
#: `_` 는 단어문자라 `\bpassword\b` 로는 `TEST_PASSWORD` 안의 PASSWORD 가 매칭되지 않는다
#: (이 구멍을 변이 테스트로 발견했다 — 진짜 유출을 심었는데 검사기가 통과시켰다).
_SECRET_ASSIGN = re.compile(
    r"(?i)\b[a-z_]*(password|passwd|secret|api[_-]?key|token|servicekey)\b\s*[=:]\s*"
    r"[\"']?(?P<value>[^\s\"'`<>{}$|,;)\]]{8,})"
)

#: 값이 아니라 자리표시자인 것들 — 문서에 이렇게 적는 건 정상이다.
_PLACEHOLDER = re.compile(
    r"(?i)^(\*+|x+|\.{3,}|-+|_+|none|null|true|false|env|os\.environ.*|"
    r"your[_-].*|<.*>|\$\{.*\}|%\(.*\)s|:.*|\.env.*|secrets\..*|"
    r"[a-z_]*(password|secret|key|token)[a-z_]*)$"
)

#: 마스킹·생략 표기. 값 어디에 있어도 "이건 진짜 값이 아니다"는 신호다.
_MASKED = re.compile(r"(\*{2,}|\.{3}|<[^>]*>|\$\{|%\()")

#: 명백히 **설명용 가짜값**. 리뷰 로그는 취약점을 설명하려고 `serviceKey=SUPERSECRETKEY123`
#: 같은 예시를 적는데 그건 유출이 아니다.
#:
#: ⚠️ `search` 가 아니라 `fullmatch` 다. 부분 검색이면 진짜 비밀 안에 'test' 가 우연히
#:    들어가기만 해도 통째로 면제된다(SR-018 SEC-3 이 2케이스로 실증). 값 **전체**가
#:    "가짜 표식 + 단순 영숫자"로 이뤄졌을 때만 면제하고, 특수문자가 섞인 고엔트로피 값은
#:    가짜 표식이 있어도 잡는다 — 진짜 키는 `+`·`/`·`=` 같은 문자를 갖는다.
_SYNTHETIC = re.compile(
    r"(?i)^[a-z0-9_\-]*"
    r"(secret|dummy|example|sample|fake|test|placeholder|changeme|redacted|masked)"
    r"[a-z0-9_\-]*(&[a-z0-9_=\-]*)*=*$"      # 끝의 `=` 는 base64 패딩(가짜 예시가 흔히 붙인다)
)


def test_docs_and_config_do_not_contain_secret_values():
    """문서·설정에 비밀'값'이 적혀 있으면 안 된다 — 커밋되면 공개 저장소에 영구히 남는다.

    리뷰 로그도 커밋 대상이다. 결함을 지적하려고 값을 인용하면 그 자체가 같은 유출이 된다
    (실제로 SR17-2 때 리뷰 로그 2개에 평문 비밀번호가 인용돼 있었다).
    """
    targets: list[Path] = []
    for pattern in ("docs/**/*.md", "config/**/*.yaml", "config/**/*.yml", "*.md"):
        targets += [p for p in REPO_ROOT.glob(pattern) if p.is_file()]

    offenders: list[str] = []
    for path in targets:
        if ".env.example" in path.name:      # 예시 파일은 키 이름만 있고 값이 비어 있다
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(lines, start=1):
            m = _SECRET_ASSIGN.search(line)
            if not m:
                continue
            value = m.group("value")
            if (_PLACEHOLDER.match(value) or _MASKED.search(value)
                    or _SYNTHETIC.fullmatch(value)):
                continue
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}")

    assert not offenders, (
        "문서·설정에 비밀값으로 보이는 문자열이 있습니다(공개 저장소 — 커밋되면 영구 공개):\n  "
        + "\n  ".join(offenders))


def test_verify_recommendation_only_purges_disposable_addresses():
    """자동 정리는 `.invalid`(RFC 2606 예약) 주소만 — 실사용자 삭제 경로를 문법으로 막는다."""
    import importlib.util
    import sys

    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(
        "_test_verify_recommendation", SCRIPTS_DIR / "verify_recommendation.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    with pytest.raises(SystemExit):
        module.purge_user(object(), "real.user@example.com")   # engine 에 닿기 전에 막힌다

    # 무작위 비밀번호는 매번 달라야 한다(고정 시드·상수 회귀 방지).
    assert module.make_test_password() != module.make_test_password()
    assert len(module.make_test_password()) >= 16


# ---------------------------------------------------------------------------
# SR17-3 — 모든 스크립트가 공통 진입 경로(`_common`)를 탄다
# ---------------------------------------------------------------------------

def test_every_script_goes_through_common_entrypoint():
    """`_common` import 만으로 로깅 억제·비밀 마스킹이 걸린다. 빠뜨릴 수 있는 구멍을 막는다."""
    missing = [p.name for p in _script_files()
               if not re.search(r"^from _common import ", p.read_text(encoding="utf-8"),
                                re.MULTILINE)]
    assert not missing, (
        "다음 스크립트가 `_common` 을 거치지 않습니다 — 로깅 억제·마스킹이 안 걸립니다:\n  "
        + "\n  ".join(missing))


def test_common_installs_masking_on_import():
    """`configure_logging` 을 부르는 것을 잊어도 import 시점에 이미 설치돼 있어야 한다."""
    source = (SCRIPTS_DIR / "_common.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    module_level_calls = [
        node.value.func.id
        for node in tree.body
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
    ]
    assert "configure_logging" in module_level_calls, (
        "_common.py 가 import 시점에 configure_logging() 을 부르지 않습니다")
    assert "install_log_masking" in source


def test_no_script_configures_logging_without_common():
    """`basicConfig` 를 직접 부르는 스크립트가 없어야 한다(억제·마스킹 우회 경로)."""
    offenders = [p.name for p in _script_files()
                 if "basicConfig" in p.read_text(encoding="utf-8")]
    assert not offenders, (
        "logging.basicConfig 를 직접 부르면 마스킹을 건너뜁니다 — configure_logging 을 쓰세요: "
        f"{offenders}")


# ---------------------------------------------------------------------------
# SR17-5 → SR18-6 → SR22-2 → SR23-1 → SR24-2 — 다운로드 상한
#
# 같은 지적이 **다섯 번** 반복됐다. 원인은 코드가 아니라 구조였다 —
# 수집기마다 "상한을 걸어야 한다"를 사람이 기억해야 했다. 여섯 번째를 만들지 않으려면
# 기억이 아니라 검사가 막아야 한다.
# ---------------------------------------------------------------------------

#: 이 함수들을 거치면 상한이 걸린다(`scripts/_common.py` · `app/core/http.py`).
_CAPPED_HELPERS = ("capped_get", "capped_urlopen_read", "read_capped", "request_capped")

#: 응답 본문을 **통째로 메모리에 올리는** 접근자.
#: ⚠️ `.text`·`.json()` 이 `.content` 보다 안전하다고 믿는 것이 SR25-1 의 구멍이었다 —
#:    셋 다 본문을 전부 읽는다. `.json()` 은 파싱까지 해서 오히려 더 쓴다.
_BODY_ATTRS = ("content", "text")
_BODY_CALLS = ("json", "read")

#: 응답을 만들어내는 호출. 이 결과에 곧바로 붙는 본문 접근은 무조건 상한이 없다
#: (`client.get(u).text` — 상한을 걸 자리 자체가 없다).
_HTTP_CALL_ATTRS = ("get", "post", "put", "patch", "request", "send", "stream", "urlopen")
_HTTP_CALL_NAMES = ("urlopen", "urlretrieve")

#: 응답을 담는 관례적 이름. 대입 추적(`_response_names`)이 놓치는 경우의 그물이다.
_RESP_NAME_RE = re.compile(r"^(resp|response|res|reply|r)\d*$", re.IGNORECASE)


def _is_http_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in _HTTP_CALL_ATTRS:
        return True
    return isinstance(func, ast.Name) and func.id in _HTTP_CALL_NAMES


def _response_names(tree: ast.AST) -> set[str]:
    """`resp = client.get(...)` · `with client.stream(...) as resp:` 의 좌변 이름들.

    이름 규칙(`resp`·`r` …)만 믿으면 `payload = httpx.get(u)` 같은 작명에 뚫린다.
    반대로 대입 추적만 믿으면 함수 인자로 받은 응답을 놓친다. **둘 다** 쓴다.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_http_call(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.withitem) and _is_http_call(node.context_expr):
            if isinstance(node.optional_vars, ast.Name):
                names.add(node.optional_vars.id)
    return names


def _is_response_like(node: ast.AST, resp_names: set[str]) -> bool:
    if _is_http_call(node):
        return True
    return isinstance(node, ast.Name) and (
        node.id in resp_names or bool(_RESP_NAME_RE.match(node.id)))


def _uncapped_reads(source: str) -> list[tuple[int, str]]:
    """상한 없이 응답 본문을 통째로 올리는 표현을 **AST 로** 찾는다.

    ⚠️ 정규식으로 소스 문자열을 훑으면 독스트링·주석에 적힌 `resp.content` 까지
       잡아서(실제로 밟았다) 검사기가 자기 설명 때문에 빨개진다. 코드만 본다.

    ⚠️ **수신자를 본다**(CR30-2 / SR25-1). 예전에는 `.content` 와 인자 없는 `.read()` 만
       봤는데, ① `.text`·`.json()` 이 그대로 통과했고(그 형태가 저장소에 8곳 있었다)
       ② 반대로 로컬 파일의 `open(p).read()` 를 오탐했다(`_LOCAL_READ_OK` 는
       `attr == "read"` 조건 안에 있어 **닿을 수 없는 죽은 코드**였다).
       지금은 "응답처럼 보이는 것"의 본문 접근만 잡으므로 둘 다 해결된다 —
       `zf.read(name)`(zip) · `el.text`(XML 엘리먼트) · `fh.read()`(로컬 파일)는 통과한다.
    """
    hits: list[tuple[int, str]] = []
    tree = ast.parse(source)
    resp_names = _response_names(tree)
    for node in ast.walk(tree):
        # `resp.content` · `resp.text` · `client.get(u).text`
        if (isinstance(node, ast.Attribute) and node.attr in _BODY_ATTRS
                and _is_response_like(node.value, resp_names)):
            hits.append((node.lineno, f"<응답>.{node.attr}"))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            # `resp.json()` · `resp.read()` · `resp.read(-1)`(인자가 있어도 전량이다)
            if (node.func.attr in _BODY_CALLS
                    and _is_response_like(node.func.value, resp_names)):
                hits.append((node.lineno, f"<응답>.{node.func.attr}()"))
            # `getattr(resp, "content")` — 속성 접근을 문자열로 우회하는 형태
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "getattr" and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in (*_BODY_ATTRS, *_BODY_CALLS)
                and _is_response_like(node.args[0], resp_names)):
            hits.append((node.lineno, f"getattr(<응답>, {node.args[1].value!r})"))
    return hits


#: 상한 검사 대상. **`scripts/` 만 보던 것을 운영 컨테이너 안까지 넓혔다**(SR25-1).
#: 오히려 컨테이너 안(`mem_limit 192m`)이 더 중요하다 — 호스트는 메모리가 더 넉넉하다.
#: `_common.py` 는 헬퍼 자신이라 제외한다(`_script_files()` 가 이미 뺀다).
#: `app/core/http.py` 는 **일부러 포함**한다 — 헬퍼가 스트리밍을 그만두고 `.text` 로
#: 돌아가는 것이 가장 조용한 회귀 경로다(그러면 모든 호출부가 같이 무장 해제된다).
def _capped_scope_files() -> list[Path]:
    files = list(_script_files())
    files += _python_files(BACKEND_DIR / "app" / "ingest")
    files += [BACKEND_DIR / "app" / "agents" / "llm.py",
              BACKEND_DIR / "app" / "core" / "http.py"]
    return sorted({p for p in files if p.exists()})


def test_capped_scope_covers_the_containers_not_just_scripts():
    """★ 범위 자체를 고정한다.

    탐지식을 아무리 고쳐도 **보는 파일이 좁으면** 소용이 없다 — SR25-1 의 구멍이
    정확히 그것이었다(검사가 `scripts/*.py` 만 봤고, 정작 위반 3곳은 컨테이너 안에 있었다).
    위 테스트만 있으면 누가 범위를 `scripts/` 로 되돌려도 **전부 초록**이다
    (지금은 위반이 0건이라 아무것도 실패하지 않으므로). 그래서 범위를 따로 못박는다.
    """
    names = {p.relative_to(BACKEND_DIR).as_posix() for p in _capped_scope_files()}
    for required in ("app/ingest/run_molit.py", "app/ingest/geocode.py",
                     "app/agents/llm.py", "app/core/http.py"):
        assert required in names, f"상한 검사 범위에 {required} 가 빠졌습니다: {sorted(names)}"
    assert any(n.startswith("scripts/") for n in names)


def test_downloaders_read_through_capped_helper():
    """★ 수집·외부호출 코드는 응답을 **상한이 걸린 헬퍼**로 읽는다.

    상한 없이 읽으면 원천이 바뀌거나 포털이 오류 스트림을 내보낼 때 응답 전체가
    메모리에 올라간다. 검사 범위는 두 곳이다:
      · `scripts/*.py` — 호스트에서 사람이 손으로 돌리는 수집기
      · `app/ingest/**` · `app/agents/llm.py` — **api·worker 컨테이너 안**(mem_limit 192m)
    SR23-1 의 통과 조건이었던 "헬퍼 하나로 일괄"을 여기서 강제한다 —
    새 수집기를 만들면서 잊으면 이 테스트가 먼저 넘어진다.
    """
    offenders: list[str] = []
    for path in _capped_scope_files():
        for lineno, what in _uncapped_reads(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(BACKEND_DIR)}:{lineno} {what}")
    assert not offenders, (
        "응답 본문을 상한 없이 읽는 곳이 있습니다 — "
        f"{'/'.join(_CAPPED_HELPERS)} 를 쓰세요:\n  " + "\n  ".join(offenders))


@pytest.mark.parametrize("snippet, expected", [
    # --- 잡아야 하는 것 (SR25-1 이 '통과(우회)' 로 기록한 형태들) ---------------
    ("def f(client, u):\n    return client.get(u).text\n", True),
    ("def f(client, u):\n    return client.get(u).json()\n", True),
    ("def f(client, u):\n    resp = client.get(u)\n    return resp.content\n", True),
    ("def f(client, u):\n    resp = client.get(u)\n    return resp.read(-1)\n", True),
    ("def f(client, u):\n    resp = client.get(u)\n"
     "    return getattr(resp, 'content')\n", True),
    ("import httpx\ndef f(u):\n    payload = httpx.get(u)\n"
     "    return payload.text\n", True),          # 이름이 resp 가 아니어도 잡는다
    # --- 잡으면 안 되는 것 (오탐이 나면 사람이 검사를 꺼 버린다) ---------------
    ("def f(p):\n    with open(p) as fh:\n        return fh.read()\n", False),
    ("def f(p):\n    return p.read_text(encoding='utf-8')\n", False),
    ("def f(zf, name):\n    return zf.read(name)\n", False),
    ("def f(el):\n    return (el.text or '').strip()\n", False),
    ("def f(client, u):\n    return capped_get(client, u)\n", False),
])
def test_uncapped_read_detector_catches_the_known_bypasses(snippet, expected):
    """★ 검사기 자체의 회귀. **탐지식을 반례로 때려 본 결과**를 여기 고정한다.

    SR-025 가 남긴 교훈: "검사가 걸려 있다"와 "검사가 잡는다"는 다른 문장이다.
    위 목록의 앞쪽 6개는 SR25-1 이 실제로 검사기에 넣어 **통과하는 것을 확인한** 형태다.
    """
    assert bool(_uncapped_reads(snippet)) is expected, snippet


def test_common_defines_download_cap():
    """헬퍼 자체가 상한을 갖고, 넘으면 **잘린 본문을 돌려주지 않고** 예외로 멈춘다."""
    from _common import MAX_DOWNLOAD_BYTES, DownloadTooLarge, read_capped

    assert MAX_DOWNLOAD_BYTES > 0
    # 상한을 넘으면 조용히 자르지 않는다(잘린 CSV 는 파싱은 되고 행만 줄어든다).
    with pytest.raises(DownloadTooLarge):
        read_capped([b"x" * 10, b"y" * 10], max_bytes=15, what="테스트")
    # Content-Length 가 이미 상한을 넘으면 한 바이트도 읽지 않는다.
    with pytest.raises(DownloadTooLarge):
        read_capped(iter(()), max_bytes=10, declared="999", what="테스트")
    # 상한 안이면 그대로 이어 붙인다.
    assert read_capped([b"ab", b"cd"], max_bytes=10, what="테스트") == b"abcd"


def test_capped_get_streams_and_stops_at_the_cap():
    """헬퍼가 **실제로** 스트리밍으로 받고 상한에서 멈추는지 (존재만 검사하지 않는다)."""
    import httpx

    from _common import DownloadTooLarge, capped_get

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"z" * 1000)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert capped_get(client, "https://x.test/f", max_bytes=2000) == b"z" * 1000
        with pytest.raises(DownloadTooLarge):
            capped_get(client, "https://x.test/f", max_bytes=100)

    # non-2xx 는 그대로 실패한다(상한 도입이 오류 처리를 삼키지 않는다).
    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"boom")

    with httpx.Client(transport=httpx.MockTransport(failing)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            capped_get(client, "https://x.test/f")


def test_redevelopment_loader_has_no_api_key_path():
    """★ SR24-1 회귀: 서울 정비사업 수집에 **인증키 경로가 다시 생기면** 여기서 잡는다.

    지운 이유는 마스킹으로 덮을 수 없는 형태였기 때문이다 — 키가 쿼리스트링이 아니라
    URL **경로 세그먼트**라 `masking.py` 의 `key=value` 매칭이 구조적으로 못 잡고,
    평문 HTTP 이며, `raise_for_status()` 예외 문자열이 URL 을 통째로 뱉는다.
    무키 CSV(https)로 같은 데이터셋을 받으므로 잃는 기능이 없다.
    """
    source = (SCRIPTS_DIR / "load_redevelopment.py").read_text(encoding="utf-8")
    code = "\n".join(line.split("#", 1)[0] for line in source.splitlines())
    assert "openapi.seoul.go.kr" not in code, (
        "서울 OpenAPI(인증키 경로)가 되살아났습니다 — 무키 CSV 경로만 씁니다(SR24-1).")
    assert "SEOUL_OPENAPI_KEY" not in code
    assert "https://" in code and "http://" not in code, (
        "정비사업 수집은 평문 HTTP 로 나가면 안 됩니다.")
    # `.env.example` 에도 그 칸이 없어야 한다 — 칸이 있으면 언젠가 누군가 채운다.
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "SEOUL_OPENAPI_KEY=" not in env_example


def _load_script(name: str):
    import importlib.util
    import sys

    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(f"_t_{name}", SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_redevelopment_loader_rejects_html_error_pages():
    """★ SR24-2 회귀: 오류 HTML 이 **행 0건 가드를 통과해** 쓰레기 1행으로 적재되던 자리.

    HTML 은 유효한 UTF-8 이라 `decode_csv` 가 성공하고 `csv.DictReader` 가 각 줄을
    행으로 만든다. 그러면 `if not records` 가드에 걸리지 않고, 모든 필드가 빈 문자열인
    행 하나가 `redev_project` 에 UPSERT 된다. 실패가 실패로 보이지 않는 형태다.
    """
    mod = _load_script("load_redevelopment")
    html = b"<html><body><h1>500 Internal Server Error</h1></body></html>"

    with pytest.raises(SystemExit) as exc:
        mod.check_payload(html, required_columns=mod.SEOUL_REQUIRED_COLUMNS,
                          what="서울 정비사업 CSV", page=mod.SEOUL_PAGE)
    assert "헤더" in str(exc.value) or "CSV" in str(exc.value)

    # 정상 CSV 는 그대로 통과하고 헤더를 돌려준다(검사가 정상 수집을 막지 않는다).
    good = "자치구,구역명,지번주소,사업추진단계\n강남구,개포1,개포동1,조합설립\n"
    assert "자치구" in mod.check_payload(
        good.encode("utf-8"), required_columns=mod.SEOUL_REQUIRED_COLUMNS,
        what="서울 정비사업 CSV", page=mod.SEOUL_PAGE)

    # 인천 CSV 는 헤더에 공백이 섞여 있다('구 역 명') — 공백을 지운 뒤 대조해야 한다.
    incheon = "구명,구 역 명,위치,진행단계\n동구,송림1,송림동 2,조합설립\n"
    assert mod.check_payload(
        incheon.encode("cp949"), required_columns=mod.INCHEON_REQUIRED_COLUMNS,
        what="인천 정비사업 CSV", page="x")
