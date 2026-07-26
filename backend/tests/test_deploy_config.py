"""배포 설정 정적 검사 — 보안헤더가 **경로마다** 붙어 있는지 저장소에서 못박는다.

왜 이 파일이 있나
-----------------
nginx 의 `add_header` 는 **상속되지 않는다.** 하위 location 에 `add_header` 가 하나라도
있으면 상위의 add_header 는 **전부** 끊긴다. 그래서 이 프로젝트는 Cache-Control 을 붙이는
location 마다 보안헤더를 다시 적는데, 사람이 손으로 반복하는 구조라 **한 곳만 빠뜨리면
그 경로가 조용히 무방비**가 된다. 실제로 DEP-1 이 그 결함이었다.

운영 쪽 방어선은 `deploy/DEPLOY.md` §5-6 의 `check_headers()` 가 4개 경로를 실제 curl 로
확인하는 것이고, 여기는 **커밋 시점 방어선**이다 — 서버에 올라가기 전에 걸린다.

SR15-4 (CSP)
------------
토큰을 httpOnly 쿠키로 옮기면 토큰 '반출'은 막히지만, XSS 가 그 탭 안에서 fetch 를
가로채거나 `/auth/refresh` 를 직접 부르는 **세션 라이딩**은 남는다. CSP 가 마지막 층이라
`Content-Security-Policy` 는 보안헤더 4종과 **똑같은 취급**을 받아야 한다.
빠뜨릴 수 없게 하려고 여기에 넣는다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONF = REPO_ROOT / "deploy" / "nginx-realestate.conf"
DEPLOY_DOC = REPO_ROOT / "deploy" / "DEPLOY.md"

#: 경로마다 함께 붙어야 하는 헤더. 하나라도 빠지면 그 경로만 방어가 사라진다.
REQUIRED_HEADERS = (
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Content-Security-Policy",
)


def _conf() -> str:
    return NGINX_CONF.read_text(encoding="utf-8")


def _direct_lines_per_block(text: str) -> list[list[str]]:
    """중괄호 블록별로 **그 블록이 직접 가진 줄**을 모은다(중첩 블록의 줄은 제외).

    add_header 상속 규칙이 '블록 단위'로 동작하므로 검사도 블록 단위여야 한다.
    이 설정 파일은 `{`/`}` 가 줄 끝·줄 단독으로만 오는 단순한 형태라 이 정도면 충분하다
    (완전한 nginx 파서를 여기서 만들 이유는 없다 — 만들면 그게 또 검증 대상이 된다).
    """
    stack: list[list[str]] = [[]]
    blocks: list[list[str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("{"):
            stack.append([])
            continue
        if line == "}":
            assert len(stack) > 1, "닫는 중괄호가 더 많습니다 — 설정이 깨졌습니다"
            blocks.append(stack.pop())
            continue
        stack[-1].append(line)
    assert len(stack) == 1, "열린 중괄호가 닫히지 않았습니다 — 설정이 깨졌습니다"
    blocks.append(stack.pop())
    return blocks


def _policy() -> str:
    """`map` 에 한 번만 정의된 CSP 값."""
    m = re.search(r'map \$host \$re_csp \{\s*\n\s*default\s+"([^"]+)"\s*;', _conf())
    assert m, "CSP 를 정의하는 `map $host $re_csp` 블록을 찾지 못했습니다"
    return m.group(1)


def _directive(name: str) -> list[str]:
    """CSP 에서 지시어 하나의 소스 목록."""
    for part in _policy().split(";"):
        tokens = part.split()
        if tokens and tokens[0] == name:
            return tokens[1:]
    return []


# ---------------------------------------------------------------------------
# DEP-1 — 보안헤더는 경로마다 **함께** 붙는다
# ---------------------------------------------------------------------------

def test_보안헤더는_블록마다_전부_함께_적혀_있다():
    """한 블록에 보안헤더가 하나라도 있으면 5종이 전부 있어야 한다.

    상속이 없으므로 '일부만 적힌 블록'은 **적지 않은 것보다 위험하다** —
    헤더가 보이니 지켜지고 있다고 착각하게 된다.
    """
    offenders: list[str] = []
    for block in _direct_lines_per_block(_conf()):
        present = {h for h in REQUIRED_HEADERS
                   if any(re.match(rf"add_header\s+{h}\b", line, re.IGNORECASE)
                          for line in block)}
        if not present:
            continue                       # 보안헤더를 안 쓰는 블록(상위를 상속) — 정상
        missing = [h for h in REQUIRED_HEADERS if h not in present]
        if missing:
            head = next((line for line in block if line.startswith("add_header")), "?")
            offenders.append(f"{head!r} 이 있는 블록에 없음: {', '.join(missing)}")
    assert not offenders, (
        "add_header 는 상속되지 않습니다 — 그 블록만 무방비가 됩니다:\n  "
        + "\n  ".join(offenders))


def test_보안헤더를_쓰는_블록이_충분히_있다():
    """server · 정적자산 · /index.html 세 곳. 개수가 줄면 어딘가 빠진 것이다."""
    blocks = [b for b in _direct_lines_per_block(_conf())
              if any(line.startswith("add_header Strict-Transport-Security") for line in b)]
    assert len(blocks) == 3, (
        f"보안헤더 블록이 3개가 아니라 {len(blocks)}개입니다 — "
        "location 을 추가했다면 거기에도 5종을 다시 적어야 합니다(DEP-1)")


def test_모든_보안헤더는_always_로_붙는다():
    """`always` 가 없으면 4xx/5xx 응답에 헤더가 빠진다 — 오류 화면도 공격 표면이다."""
    bad = [line for block in _direct_lines_per_block(_conf()) for line in block
           if line.startswith("add_header ")
           and any(h.lower() in line.lower() for h in REQUIRED_HEADERS)
           and not line.rstrip().endswith("always;")]
    assert not bad, "always 가 빠진 보안헤더가 있습니다:\n  " + "\n  ".join(bad)


# ---------------------------------------------------------------------------
# SR15-4 — CSP 값
# ---------------------------------------------------------------------------

def test_csp_값은_한_곳에서만_정의된다():
    """세 블록은 `$re_csp` 만 참조한다 — 값을 세 번 적으면 언젠가 하나만 고쳐진다."""
    conf = _conf()
    # 주석은 세지 않는다(근거를 길게 적어 뒀고 거기에도 지시어 이름이 나온다).
    code = "\n".join(line for line in conf.splitlines() if not line.strip().startswith("#"))
    assert code.count("default-src") == 1, "CSP 값이 두 곳 이상에 적혀 있습니다(map 하나만)"
    refs = re.findall(r"add_header\s+Content-Security-Policy\s+(\S+)\s+always;", conf)
    assert refs == ["$re_csp"] * 3, f"CSP 헤더가 변수를 참조하지 않습니다: {refs}"


@pytest.mark.parametrize(
    ("directive", "source", "why"),
    [
        # 카카오맵 SDK v4.5.13 실물 확인(2026-07-26). 하나라도 빠지면 지도가 죽는다.
        ("script-src", "https://dapi.kakao.com", "SDK 로더 sdk.js"),
        ("script-src", "https://t1.daumcdn.net", "로더가 붙이는 kakao.js·clusterer.js"),
        ("img-src", "https://mts.daumcdn.net", "지도 타일 /api/v1/tile/"),
        ("img-src", "https://t1.daumcdn.net", "마커·컨트롤 스프라이트 /mapjsapi/images/"),
        ("img-src", "https://s1.daumcdn.net", "범위 밖 빈 타일 /dmaps/apis/white.png"),
        # SDK 가 style.cssText / setAttribute("style") 로 지도 판을 배치한다 — 빼면 무너진다.
        ("style-src", "'unsafe-inline'", "SDK 의 cssText·setAttribute('style')"),
    ],
)
def test_csp_는_지도가_사는_최소_출처를_담는다(directive: str, source: str, why: str):
    assert source in _directive(directive), (
        f"{directive} 에 {source} 가 없습니다 — {why} 가 차단돼 지도가 죽습니다")


def test_csp_에_와일드카드가_없다():
    """`*` 를 넣으면 CSP 가 있는 척만 하는 헤더가 된다."""
    assert "*" not in _policy(), "CSP 에 와일드카드가 있습니다 — 출처를 실제로 조사해 적으세요"


def test_스크립트는_인라인도_eval_도_허용하지_않는다():
    """세션 라이딩 방어의 핵심. 둘 중 하나만 열려도 주입 스크립트가 그대로 돈다.

    카카오 SDK 에 `try{eval("document.namespaces")}catch{}` 가 있어 Report-Only 단계에서
    위반 1건이 보이지만, try/catch 안이라 **지도는 정상 동작한다.** 그걸 보고
    'unsafe-eval' 을 넣는 순간 이 방어가 통째로 사라진다 — 그래서 테스트로 막는다.
    """
    script = _directive("script-src")
    assert "'unsafe-inline'" not in script
    assert "'unsafe-eval'" not in script


def test_기본_차단과_프레임_방어가_들어_있다():
    assert _directive("default-src") == ["'self'"]
    assert _directive("object-src") == ["'none'"]
    assert _directive("base-uri") == ["'none'"]
    assert _directive("frame-ancestors") == ["'none'"]   # X-Frame-Options DENY 의 CSP 판
    # 우리 API 는 같은 오리진이고, 기본 지도+clusterer 는 XHR 을 하지 않는다.
    assert _directive("connect-src") == ["'self'"]


# ---------------------------------------------------------------------------
# 절차 — 문서가 실제로 검증하게 되어 있는가
# ---------------------------------------------------------------------------

def test_배포문서가_csp_를_경로마다_실검증한다():
    """`check_headers()` 에 CSP 가 없으면 누락을 아무도 못 잡는다(SR15-4 통과조건 3)."""
    doc = DEPLOY_DOC.read_text(encoding="utf-8")
    m = re.search(r"check_headers\(\) \{.*?\n\}", doc, re.DOTALL)
    assert m, "DEPLOY.md 에서 check_headers() 를 찾지 못했습니다"
    assert "content-security-policy" in m.group(0), (
        "check_headers() 가 CSP 를 확인하지 않습니다 — 4경로 실검증에 넣어야 합니다")


def test_배포문서에_report_only_선행_절차가_있다():
    """잘못 좁히면 지도가 죽는다. 강제 전에 Report-Only 로 확인하는 경로가 있어야 한다."""
    doc = DEPLOY_DOC.read_text(encoding="utf-8")
    assert "Content-Security-Policy-Report-Only" in doc
    assert "강제 전환" in doc
