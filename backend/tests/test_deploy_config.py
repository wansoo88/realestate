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
# ★ SR32-1 — nginx 접근 로그에 쿼리스트링이 남지 않는가
#
# 운영 로그에 `max_price_krw=1314310000`(암호화 보관하던 자산에서 계산한 최대
# 구매가능 금액)이 148줄 쌓여 있었고 회전본은 0644 였다. 근본 수정은 앱에서 했지만
# (금액을 URL 에 안 싣는다), 이 포맷이 마지막 그물이다 — **누가 무엇을 쿼리에
# 실어도** 로그에는 안 남는다. 그물이 조용히 풀리는 것을 여기서 막는다.
# ---------------------------------------------------------------------------

#: 쿼리를 포함하는 nginx 변수. `$request` = "메서드 경로?쿼리 프로토콜",
#: `$request_uri` = "경로?쿼리". 접근 로그 포맷에 있으면 그 자체가 결함이다.
QUERY_BEARING_VARS = ("$request_uri", "$request ", "$request'", '$request"', "$args",
                      "$query_string")


def _log_format_body() -> str:
    m = re.search(r"log_format\s+re_noquery\s+(.*?);", _conf(), re.DOTALL)
    assert m, "쿼리 제외 log_format(re_noquery)을 찾지 못했습니다 (SR32-1)"
    return m.group(1)


def test_전용_로그포맷이_쿼리를_담지_않는다():
    body = _log_format_body()
    assert "$uri" in body, "경로는 남겨야 한다(어느 엔드포인트가 불렸는지는 운영 정보다)"
    for var in QUERY_BEARING_VARS:
        assert var not in body, (
            f"log_format 에 {var.strip()} 이 있습니다 — 쿼리스트링이 그대로 로그에 남습니다")


def test_모든_access_log_가_쿼리_제외_포맷을_쓴다():
    """포맷을 정의만 하고 안 쓰면 아무것도 고친 게 아니다.

    변이: `access_log ... re_noquery;` 에서 포맷 이름을 지우면(= 기본 combined)
    여기서 깨진다.
    """
    lines = [ln.strip() for ln in _conf().splitlines()
             if ln.strip().startswith("access_log")]
    assert lines, "access_log 지시어가 없습니다"
    for line in lines:
        if line.startswith("access_log off"):
            continue
        assert line.rstrip(";").split()[-1] == "re_noquery", (
            f"이 access_log 가 기본(combined) 포맷을 씁니다 → 쿼리가 남습니다: {line}")


def test_로그포맷은_이_사이트에만_적용된다():
    """⚠️ 동거 서비스 3개가 같은 호스트에 있다(SR-027 이 gzip 에서 건 조건과 같다).

    `log_format` **정의**는 부작용이 없지만, 전역 기본 로그를 바꾸는 지시어
    (`http` 블록의 access_log 를 재정의하는 형태)가 이 파일에 있으면 안 된다.
    이 파일의 access_log 는 전부 우리 서버블록 안에 있고 우리 파일만 가리켜야 한다.
    """
    for line in _conf().splitlines():
        stripped = line.strip()
        if not stripped.startswith("access_log"):
            continue
        assert "/var/log/nginx/realestate." in stripped, (
            f"이 사이트 밖의 로그 파일을 건드립니다: {stripped}")
    # 정의는 한 번만 — 두 번 정의하면 나중 것이 이깁니다(조용히 다른 포맷이 됩니다).
    assert _conf().count("log_format re_noquery") == 1


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
# ★ SR33-4 — `<APP_ROOT>` 함정: `nginx -t` 는 **미치환·없는 경로를 전부 통과시킨다**
#
# 운영 실측(2026-07-29): `<APP_ROOT>` 를 그대로 두거나 `/nonexistent/...` 로 바꿔도
# `nginx -t` 는 `syntax is ok / test is successful` 이다 — 문법만 보기 때문이다.
# 그리고 이 함정으로 **운영 메인이 404 가 된 적이 있다**(realestate.error.log.2.gz 에
# `stat() "/tmp/tmp.BrOsTCkDTX/dist/" failed` 가 남아 있다).
# 예전 가드는 `grep … && echo "진행 금지"` 한 줄이라 **중단하지 않았다.**
# ---------------------------------------------------------------------------

#: DEPLOY.md 의 ```bash 펜스 블록들.
_BASH_BLOCK_RE = re.compile(r"```bash\n(.*?)```", re.DOTALL)

#: 설정 템플릿의 자리표시자. 이 파일이 검사 대상 이름을 조립해 쓰는 이유는,
#: 아래 "치환 누락" 검사가 이 테스트 파일 자신을 잡지 않게 하려는 게 아니라
#: (여기는 nginx conf 를 안 읽는다) **한 곳에서만 정의**하기 위해서다.
APP_ROOT_TOKEN = "<APP_ROOT>"


def _bash_blocks(text: str) -> list[str]:
    return _BASH_BLOCK_RE.findall(text)


def test_배포문서에_치환_경로_가드_함수가_있다():
    """`guard_site()` 가 **세 가지**를 본다: 치환 누락 · index.html 존재 · root 경로 존재.

    `nginx -t` 는 셋 다 안 본다. 하나라도 빠지면 '검사했다'는 착각만 남는다.
    변이: 함수 본문에서 `-f ...index.html` 검사를 지우면 여기서 깨진다.
    """
    doc = DEPLOY_DOC.read_text(encoding="utf-8")
    m = re.search(r"guard_site\(\) \{.*?\n\}", doc, re.DOTALL)
    assert m, "DEPLOY.md 에서 guard_site() 정의를 찾지 못했습니다 (SR33-4)"
    body = m.group(0)

    assert APP_ROOT_TOKEN in body, "치환 누락 검사가 없습니다"
    assert "index.html" in body and "-f " in body, (
        "root 경로의 index.html 존재 검사가 없습니다 — 없으면 메인이 404 인데 "
        "`nginx -t` 는 통과합니다")
    # 설정 파일에서 `root <경로>` 를 뽑아 **디렉터리 존재**를 확인하는 단계.
    # (certbot webroot 처럼 index.html 이 없는 root 도 있으므로 -f 와 별개로 필요하다.)
    assert re.search(r"grep[^\n]*root[^\n]*\"\$site\"", body), (
        "설정에 적힌 root 경로를 뽑는 단계가 없습니다")
    assert "-d " in body, "root 디렉터리 존재 검사(-d)가 없습니다"
    # 실패하면 **돌려주는** 함수여야 한다(echo 만 하고 넘어가면 예전 가드와 같다).
    assert body.count("return 1") >= 4, (
        "guard_site 가 실패를 return 1 로 알리지 않습니다 — 호출부의 `&&` 가 끊기지 않습니다")


def test_가드가_그_파일이_활성_사이트인지도_본다():
    """★ SR34-1. 가드는 파일의 **내용**만 봤다 — nginx 가 읽는 파일인지는 안 봤다.

    실측(2026-07-29, 운영): 활성은 `sites-enabled/realestate.utilverse.info` 인데
    §5-5(3)·(5) 는 `sites-available/realestate.conf` 에 썼다. 그대로 따르면
    **가드 통과 · `nginx -t` 통과 · reload 성공 · 새 설정은 안 걸림**이다.
    `<APP_ROOT>` 함정과 같은 종류다(전부 통과하는데 동작만 안 함).

    변이: `sites-enabled` 순회 블록을 지우면 여기서 깨진다.
    """
    doc = DEPLOY_DOC.read_text(encoding="utf-8")
    body = re.search(r"guard_site\(\) \{.*?\n\}", doc, re.DOTALL).group(0)

    assert "sites-enabled" in body, (
        "guard_site 가 '이 파일이 활성 사이트인가'를 보지 않습니다 (SR34-1)")
    # 링크를 **해석해서** 비교해야 한다 — 이름만 비교하면 심볼릭 링크에서 어긋난다.
    assert body.count("readlink -f") >= 2, (
        "링크를 해석하지 않고 이름만 비교하면 sites-enabled 의 심볼릭 링크를 못 따라갑니다")


def test_가드의_root_경로_순회가_공백을_견딘다():
    """CR38-5. `for d in $(…)` 는 공백이 든 경로를 단어로 쪼갠다.

    실측: root 가 `/srv/web root/dist` 면 옛 방식은 `/srv/web` 을 '없는 경로'라고
    보고해 **정상 설정에서 배포를 막는다**(fail-closed 라 위험하진 않지만 틀린 판정이다).
    """
    doc = DEPLOY_DOC.read_text(encoding="utf-8")
    body = re.search(r"guard_site\(\) \{.*?\n\}", doc, re.DOTALL).group(0)

    assert "while IFS= read -r" in body, (
        "root 경로를 줄 단위로 읽지 않습니다 — 공백이 든 경로가 쪼개집니다 (CR38-5)")
    # 주석은 뺀다 — 가드 안에 *옛 방식을 쓰지 말라*는 설명이 그 모양으로 적혀 있다.
    code = "\n".join(ln for ln in body.split("\n") if not ln.lstrip().startswith("#"))
    assert not re.search(r"for\s+\w+\s+in\s+\$\(", code), (
        "명령 치환을 `for … in $(…)` 로 순회하면 단어 분리가 일어납니다 (CR38-5)")


#: nginx 가 실제로 읽는 사이트 파일 이름(운영 실측). 문서 전체가 이 하나만 쓴다.
ACTIVE_SITE_NAME = "realestate.utilverse.info"


def test_배포문서가_한_사이트_파일만_가리킨다():
    """★ SR34-1 의 본체. 이름이 갈리면 가드가 **옳은 검사를 틀린 파일에** 한다.

    `/etc/nginx/sites-{available,enabled}/` 아래를 가리키는 모든 경로가 같은 이름이어야
    한다. (저장소 원본 `deploy/nginx-realestate.conf` 나 §5-5(0) 의 임시 사본
    `$T/realestate.conf` 는 `/etc/nginx` 밑이 아니므로 대상이 아니다.)

    변이: 어느 한 블록의 `SITE=` 를 `realestate.conf` 로 되돌리면 여기서 깨진다.
    """
    doc = DEPLOY_DOC.read_text(encoding="utf-8")
    refs = re.findall(r"/etc/nginx/sites-(?:available|enabled)/([A-Za-z0-9._-]+)", doc)
    assert refs, "배포 문서에서 사이트 파일 경로를 찾지 못했습니다(검사가 비면 늘 통과합니다)"

    wrong = sorted({r for r in refs if r != ACTIVE_SITE_NAME})
    assert not wrong, (
        f"활성 사이트가 아닌 이름이 문서에 남아 있습니다: {wrong} — "
        f"운영에서 nginx 가 읽는 파일은 `{ACTIVE_SITE_NAME}` 하나입니다 (SR34-1). "
        "그 이름이 아니면 가드·nginx -t·reload 가 전부 성공하고 설정만 안 걸립니다.")
    # 설치·활성화·롤백이 모두 그 이름을 쓰는지(한 곳만 남고 나머지가 사라지지 않았는지).
    assert refs.count(ACTIVE_SITE_NAME) >= 5, refs


def test_배포_직후_활성_파일에_새_로그포맷이_들어갔는지_센다():
    """SR34-1 통과 조건의 '한 줄'. 링크를 되짚어 **그 파일**에서 `re_noquery` 를 센다.

    변이: 이 확인을 지우면 파일을 잘못 써도 §5-6(5) 의 grep 0건을 "방어가 걸렸다"로
    오독할 여지가 남는다(실제 SR-034 의 우려가 그것이었다).
    """
    doc = DEPLOY_DOC.read_text(encoding="utf-8")
    assert re.search(
        r"grep -c 're_noquery'[^\n]*\n?[^\n]*readlink -f /etc/nginx/sites-enabled/", doc), (
        "배포 후 **활성 파일**에서 re_noquery 개수를 세는 확인이 없습니다 (SR34-1)")
    conf_count = NGINX_CONF.read_text(encoding="utf-8").count("re_noquery")
    assert f"→ {conf_count} 기대" in doc, (
        f"기대 개수가 저장소 설정({conf_count}개)과 다릅니다 — 문서를 갱신하세요")


def test_설정을_설치하는_모든_블록이_가드를_거쳐_reload_한다():
    """★ 핵심. 치환하는 블록마다 **가드 → nginx -t → reload 가 `&&` 로 묶여** 있어야 한다.

    예전 문서는 `grep … && echo "진행 금지"` 뒤에 곧바로 `nginx -t && reload` 가 왔다.
    grep 이 무엇을 찍든 다음 줄은 그대로 실행된다 — **중단하지 않는 가드**다.

    변이: 어느 한 블록에서 `guard_site` 호출을 지우거나 `&&` 를 `;` 로 바꾸면 깨진다.
    """
    doc = DEPLOY_DOC.read_text(encoding="utf-8")
    # "설치하는 블록" = `<APP_ROOT>` 를 **sed 로 치환해서** /etc/nginx 에 까는 블록.
    # ⚠️ `APP_ROOT_TOKEN in b and "sed" in b` 만으로 고르면 **가드 정의 블록 자신**이
    #    걸린다(가드도 `<APP_ROOT>` 를 grep 하고 root 경로를 sed 로 다듬으며
    #    sites-enabled 를 본다) — 가드가 자기를 호출하지 않는다고 실패하게 된다.
    #    치환하는 sed 인지로 가른다: 그것이 '설치'의 정의다.
    installing = [b for b in _bash_blocks(doc)
                  if re.search(rf"sed[^\n]*{re.escape(APP_ROOT_TOKEN)}", b)
                  and "/etc/nginx" in b]
    assert len(installing) >= 3, (
        f"`<APP_ROOT>` 를 치환해 /etc/nginx 에 까는 블록을 {len(installing)}개만 찾았습니다 — "
        "§5-5(3)·§5-5(5)·§5-5c 세 곳이 있어야 합니다(검사가 비면 늘 통과합니다)")

    for block in installing:
        assert "guard_site " in block, (
            "치환 후 가드 없이 설치하는 블록이 있습니다 (SR33-4):\n" + block)
        # 가드가 실패하면 reload 가 **실행되지 않아야** 한다.
        assert re.search(r"guard_site [^\n]*&&[^\n]*nginx -t[^\n]*&&[^\n]*reload", block), (
            "가드·문법검사·reload 가 `&&` 로 묶여 있지 않습니다 — 가드가 실패해도 "
            "reload 가 그대로 돕니다:\n" + block)


def test_배포_후_메인_상태코드를_실제로_잰다():
    """`curl -sI` 는 200 과 404 를 구분하지 않는다 — 404 여도 헤더는 다 붙는다.

    `<APP_ROOT>` 오치환의 증상이 정확히 그것이었다(헤더 검사 전부 [OK], 화면은 404).
    """
    doc = DEPLOY_DOC.read_text(encoding="utf-8")
    assert re.search(r"curl[^\n]*-w\s*'%\{http_code\}'[^\n]*\"\$BASE/\"", doc), (
        "배포 후 메인(`$BASE/`)의 상태코드를 재는 단계가 없습니다 (SR33-4)")
    assert '[ "$MAIN_CODE" = "200" ]' in doc, "상태코드를 재고 200 인지 판정해야 합니다"


def test_로그_권한_글롭이_error_로그까지_덮는다():
    """★ SR33-2. `realestate.access.log*` 만 잡으면 `error.log.2.gz` 가 0644 로 남는다.

    실측(2026-07-29): 그 파일이 월드 리더블이었고 `/var/log/nginx/` 는 0755 다.
    """
    doc = DEPLOY_DOC.read_text(encoding="utf-8")
    chmods = re.findall(r"chmod\s+640\s+(\S+)", doc)
    assert chmods, "로그 권한을 잠그는 chmod 640 명령이 없습니다"
    assert any(g.endswith("/realestate.*") for g in chmods), (
        f"chmod 글롭이 error 로그를 덮지 않습니다: {chmods} — "
        "`/var/log/nginx/realestate.*` 로 access·error 를 함께 잠가야 합니다")


def test_error_log_가_쿼리_제외_밖이라는_사실이_적혀_있다():
    """`error_log` 는 `log_format` 대상이 아니다(구조적). **모르면 다음 사람이 착각한다.**

    "3싱크를 다 막았다"고 적어 두고 error_log 가 그 밖에 있으면, 그 문장이 곧 거짓이다.
    """
    conf = _conf()
    block = conf[conf.index("error_log"):] if "error_log" in conf else ""
    assert "error_log" in conf, "error_log 지시어가 없습니다"
    around = conf[max(0, conf.index("error_log") - 1200):conf.index("error_log") + 200]
    assert "log_format" in around and "밖" in around, (
        "error_log 가 re_noquery 밖이라는 사실이 설정에 적혀 있지 않습니다 (SR33-2)")
    assert block  # 위 슬라이스가 비지 않았다(검사가 비면 늘 통과한다)


# ---------------------------------------------------------------------------
# ★ DEPLOY-1 회귀: 절차서가 새 마이그레이션을 빠뜨리면 배포가 로그인 장애를 낸다
# ---------------------------------------------------------------------------

def _deploy_md() -> str:
    return (REPO_ROOT / "deploy" / "DEPLOY.md").read_text(encoding="utf-8")


#: DEPLOY.md 5-3b 의 손수 적용 목록에서 **실제 파일 경로**를 뽑는다.
#: ⚠️ "번호가 문서 어딘가에 있는가"로 검사하면 안 된다 — 주석 한 줄이나 다른 문맥의
#:    숫자로도 통과한다. 실제로 그 형태로 두 번 뚫렸다(CR-024 의 '010', SR24-5 의 '013').
_MIGRATION_REF = re.compile(r"backend/migrations/(\d+)_([A-Za-z0-9_]+)\.sql")

#: **손수 적용이 필요한 첫 마이그레이션 번호.** 기준선을 여기 고정한다(CR30-3).
#:
#: ⚠️ 예전에는 기준선을 `min(문서에 적힌 번호)` 로 잡았다 — 즉 **검사 대상이 검사
#:    기준을 정했다.** 그래서 목록 아래쪽(009·010)을 지우면 요구도 같이 사라져
#:    "이미 적용된 건 지우자"는 흔한 런북 정리가 그대로 통과했다. 결과는 DEPLOY-1 과
#:    동일하다 — 빈 볼륨에서 재구축하면 `app_user.status` 가 없어 인증 경로가 전부 500.
#:
#: 왜 9 인가: 운영 볼륨은 008 까지 적용된 상태로 만들어졌고(`initdb.d` 자동 적용은
#: **빈 볼륨 첫 기동에만** 돈다), 009 부터는 실데이터가 든 볼륨에 손수 적용해야 한다.
#: 001~008 은 런북대로 재구축할 때 자동 적용되므로 목록에 없어도 된다.
_MANUAL_FROM = 9


def test_절차서가_모든_마이그레이션을_언급한다():
    """`migrations/*.sql` 이 늘어나면 DEPLOY.md 의 **손수 적용 목록**도 따라와야 한다.

    initdb.d 자동 적용은 **빈 볼륨 첫 기동에만** 돈다. 실데이터가 든 운영 볼륨에서는
    영원히 실행되지 않으므로, 새 마이그레이션은 손수 적용해야 한다. 절차서가 그걸
    안 적으면 배포자가 코드만 올리고 → `app_user.status` 부재 → **인증 전 경로 500**
    (CR-024 DEPLOY-1: 실제로 009·010 언급이 0건이었다).

    ★ 왜 '최신 하나'가 아니라 '전부'인가 (SR24-5, 2026-07-27)
    ---------------------------------------------------------
    예전 이 테스트는 **가장 최근 파일 번호가 문서 문자열에 있는지**만 봤다. 그래서
    013 과 014 가 같은 라운드에 추가됐을 때 014 만 목록에 들어가고 013 이 빠졌는데도
    통과했다(최신은 014 였으므로). 그런데 `postgis.py` 의 `_SCHOOL_SQL` 이 013 이
    만드는 `school_district.school_level`·`school_district_member` 를 하드 참조하므로,
    이 런북대로 DB 를 재구축하면 **모든 입지 조회가 UndefinedColumn 으로 죽는다.**
    런북이 곧 재현 절차다 — 하나라도 빠지면 안 된다.

    ★ 왜 기준선이 문서가 아니라 **디렉터리**인가 (CR30-3, 2026-07-28)
    ---------------------------------------------------------------
    바로 위 수정에서 기준선을 `min(문서에 적힌 번호)` 로 잡았다. 검사 대상이 검사
    기준을 정하는 형태라, **목록 아래쪽(009·010)을 지우면 요구도 함께 사라졌다** —
    중간(013) 삭제는 잡히는데 최저번호 삭제는 통과했다. "이미 적용됐으니 지우자"는
    런북 정리는 흔하고, 그 결과는 DEPLOY-1 그대로다(인증 전 경로 500).
    지금은 기준선이 `_MANUAL_FROM` 상수이고, 요구 목록은 **파일 시스템**에서 온다.

    그래서 지금은 ① 문서에서 `backend/migrations/NNN_*.sql` **경로**를 뽑고
    ② `_MANUAL_FROM` 이후의 **모든 실제 파일**이 그 안에 있는지 본다.
    """
    md = _deploy_md()
    migrations = sorted((REPO_ROOT / "backend" / "migrations").glob("[0-9]*.sql"))
    assert migrations, "마이그레이션 파일을 찾지 못했습니다"

    referenced = {f"{num}_{name}.sql" for num, name in _MIGRATION_REF.findall(md)}
    assert referenced, (
        "DEPLOY.md 에서 `backend/migrations/NNN_*.sql` 형태의 적용 명령을 찾지 못했습니다 — "
        "손수 적용 절차(5-3b)가 사라졌거나 형식이 바뀌었습니다.")

    # 기준선이 실재하는지부터 확인한다 — 파일이 재번호되면 상수가 조용히 무의미해진다.
    assert any(int(p.stem.split("_")[0]) == _MANUAL_FROM for p in migrations), (
        f"{_MANUAL_FROM:03d}번 마이그레이션이 없습니다 — `_MANUAL_FROM` 기준선을 "
        "실제 파일 구성에 맞춰 다시 정하세요(주석의 근거도 함께 갱신할 것).")

    required = [p.name for p in migrations
                if int(p.stem.split("_")[0]) >= _MANUAL_FROM]
    missing = [name for name in required if name not in referenced]
    assert not missing, (
        f"DEPLOY.md 손수 적용 목록에 없는 마이그레이션: {missing}. "
        f"({_MANUAL_FROM:03d} 번부터는 initdb.d 가 돌지 않으므로 하나도 빠지면 안 됩니다.) "
        "initdb.d 자동 적용은 빈 볼륨에만 도므로, 빠뜨리면 런북대로 재구축한 DB 에서 "
        "코드가 없는 컬럼·테이블을 참조해 전면 장애가 납니다."
    )

    latest = migrations[-1]
    assert latest.name in referenced, (
        f"최신 마이그레이션 {latest.name} 이 DEPLOY.md 손수 적용 목록에 없습니다.")


#: `ALTER TABLE listing ADD CONSTRAINT listing_user_*` 에서 제약 이름을 뽑는다.
_USER_CHECK_RE = re.compile(r"ADD CONSTRAINT\s+(listing_user_[A-Za-z0-9_]+)")

#: DEPLOY.md 의 **기대 목록 블록**. 본문 아무 데나 이름이 있으면 통과하는 형태로
#: 만들면 안 된다 — 설명 문단에 이름을 한 번 언급했다는 이유로 목록에서 빠진 것이
#: 통과한다(이 테스트를 처음 썼을 때 실제로 그 변이가 살아남았다).
#: 그래서 `# 기대 …:` 바로 뒤에 **한 줄에 하나씩** 적힌 이름만 목록으로 본다.
_EXPECT_BLOCK_RE = re.compile(
    r"^# 기대 [^\n]*?\*\*(?P<count>\d+)건\*\*[^\n]*:\n"
    r"(?P<body>(?:^#\s+listing_user_[A-Za-z0-9_]+\s*\n)+)", re.M)


def test_절차서의_제약_확인_목록이_마이그레이션과_일치한다():
    """★ CR35-5. 확인 목록이 **실제로 생기는 제약**과 같아야 한다.

    §5-3b (4)는 016 적용 후 `pg_constraint` 를 조회해 눈으로 대조하라고 시킨다.
    그 기대 목록에 `listing_user_floor_range` 가 빠져 "6건"이라 적혀 있었는데
    실제로는 **7건**이 생긴다(2026-07-29 운영 실측). 운영자는 두 갈래로 실패한다 —
    "7건이 나왔는데 6건이라니 뭐가 잘못됐나"로 멈추거나, 세어 보지 않고 넘어간다.
    어느 쪽이든 **확인 절차가 확인이 아니게 된다.**

    그래서 기대 목록을 문서에 손으로 적힌 숫자가 아니라 **마이그레이션 파일**에서
    끌어온다. 제약이 늘거나 이름이 바뀌면 이 테스트가 먼저 깨진다.
    """
    md = _deploy_md()
    sql_files = sorted((REPO_ROOT / "backend" / "migrations").glob("[0-9]*.sql"))
    names: set[str] = set()
    for p in sql_files:
        names |= set(_USER_CHECK_RE.findall(p.read_text(encoding="utf-8")))
    assert names, "마이그레이션에서 listing_user_* CHECK 제약을 찾지 못했습니다"

    m = _EXPECT_BLOCK_RE.search(md)
    assert m, ("DEPLOY.md §5-3b (4) 에서 제약 기대 목록 블록을 찾지 못했습니다 — "
               "`# 기대 … **N건** …:` 다음에 한 줄에 하나씩 적어야 합니다.")
    listed = set(re.findall(r"listing_user_[A-Za-z0-9_]+", m.group("body")))

    assert listed == names, (
        f"DEPLOY.md 확인 목록이 마이그레이션과 다릅니다. "
        f"목록에 없음: {sorted(names - listed)} · 실재하지 않음: {sorted(listed - names)}. "
        "목록대로 대조하면 실제 결과와 어긋나 확인이 무의미해집니다.")
    # 개수도 함께 적는다 — 사람은 목록보다 숫자로 먼저 대조한다.
    assert int(m.group("count")) == len(names), (
        f"DEPLOY.md 가 제약을 {m.group('count')}건이라 적었지만 마이그레이션 기준은 "
        f"{len(names)}건입니다: {sorted(names)}.")


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
