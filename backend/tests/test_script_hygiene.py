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
