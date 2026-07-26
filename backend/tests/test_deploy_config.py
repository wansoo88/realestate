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
    # connect-src 는 **정확 집합**으로 못박는다(SR19-2 권고 · SR-021 반영).
    #   · 'self'            — 우리 API 는 같은 오리진(`/api/...`)
    #   · dapi.kakao.com    — 역·장소 검색(SDK `services`)이 순수 XHR + Authorization 헤더라
    #                         이게 없으면 기능이 100% 안 된다(services.js 원본으로 확인)
    # "포함"이 아니라 "일치"로 단언하는 이유: XSS 반출 경로는 **조용히 하나씩 늘어난다.**
    # 새 출처를 넣으려면 이 테스트를 고쳐야 하고, 그때 리뷰가 강제된다.
    # 추가 기준(SR-021): **이미 script-src 에 있는 출처만** 여기 넣는다 — 임의 코드 실행을
    # 허용한 상대에게 XHR 을 더 주는 건 약한 권한이지만, 그렇지 않은 출처는 순수한 표면 확대다.
    assert _directive("connect-src") == ["'self'", "https://dapi.kakao.com"]
    assert set(_directive("connect-src")) - {"'self'"} <= set(_directive("script-src")), (
        "connect-src 에 script-src 에 없는 출처가 있습니다 — 대가 없이 반출 표면만 넓힙니다(SR-021)"
    )


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


# ---------------------------------------------------------------------------
# ★ DEPLOY-1 회귀: 절차서가 새 마이그레이션을 빠뜨리면 배포가 로그인 장애를 낸다
# ---------------------------------------------------------------------------

def _deploy_md() -> str:
    return (REPO_ROOT / "deploy" / "DEPLOY.md").read_text(encoding="utf-8")


def test_절차서가_모든_마이그레이션을_언급한다():
    """`migrations/*.sql` 이 늘어나면 DEPLOY.md 도 따라와야 한다.

    initdb.d 자동 적용은 **빈 볼륨 첫 기동에만** 돈다. 실데이터가 든 운영 볼륨에서는
    영원히 실행되지 않으므로, 새 마이그레이션은 손수 적용해야 한다. 절차서가 그걸
    안 적으면 배포자가 코드만 올리고 → `app_user.status` 부재 → **인증 전 경로 500**
    (CR-024 DEPLOY-1: 실제로 009·010 언급이 0건이었다).

    검사 대상은 **가장 최근 마이그레이션**이다. 초기분(001~)은 빈 볼륨 첫 기동에 자동 적용돼
    문서가 개별로 적을 이유가 없고, 실제 사고는 언제나 "새로 추가하고 절차서를 안 고침"에서 난다.
    파일 목록에서 자동으로 뽑으므로 011 이 생기면 이 테스트가 먼저 알려준다.
    """
    md = _deploy_md()
    migrations = sorted((REPO_ROOT / "backend" / "migrations").glob("[0-9]*.sql"))
    assert migrations, "마이그레이션 파일을 찾지 못했습니다"

    latest = migrations[-1]
    number = latest.stem.split("_")[0]
    assert number in md, (
        f"최신 마이그레이션 {latest.name} 이 DEPLOY.md 에 없습니다. "
        "initdb.d 자동 적용은 빈 볼륨에만 도므로, 손수 적용 절차(5-3b)에 추가해야 합니다 — "
        "빠뜨리면 코드만 올라가 인증 경로가 500 이 됩니다."
    )


def test_절차서가_마이그레이션이_코드보다_먼저임을_명시한다():
    """순서가 뒤바뀌면 서비스가 통째로 멈춘다. 그 사실이 문서에 있어야 한다."""
    md = _deploy_md()
    assert "코드보다 먼저" in md or "마이그레이션 → 코드" in md, \
        "DEPLOY.md 에 '마이그레이션이 코드보다 먼저'라는 순서 경고가 없습니다"
    assert "ON_ERROR_STOP" in md, \
        "psql 적용 시 ON_ERROR_STOP=1 안내가 없습니다 — 실패가 성공으로 보입니다"


def test_절차서가_관리자_부트스트랩_경로를_적는다():
    """009 적용 즉시 모든 계정이 pending 이 된다. 관리자가 0명이면 웹으로는 복구 불가다.

    CLI 는 **호스트에서** 돌아야 한다(API 컨테이너에 scripts/ 도 DATABASE_URL 도 없다).
    그 사실이 문서에 없으면 소유자가 자기 서비스에서 영구히 잠긴다.
    """
    md = _deploy_md()
    assert "manage_users.py" in md, "DEPLOY.md 에 관리자 부트스트랩 CLI 안내가 없습니다"
    assert "--grant-admin" in md and "--approve" in md, "부트스트랩 명령이 불완전합니다"
    assert "호스트" in md and "DATABASE_URL" in md, \
        "CLI 를 어디서 어떻게 실행하는지(호스트 · DATABASE_URL)가 문서에 없습니다"
