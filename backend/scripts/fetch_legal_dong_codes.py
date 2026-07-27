"""법정동코드 전체자료 자동 내려받기 (행정안전부 행정표준코드관리시스템).

왜 자동화하는가
---------------
법정동은 신설·폐지·통합이 계속 일어난다(실제로 2026-07 인천 행정구역 개편으로
중구·동구·서구가 제물포구·영종구·서해구·검단구로 바뀌었다). 사람이 브라우저로
받아 옮기는 절차는 **갱신을 미루게 만들고**, 낡은 코드로 수집하면 0건이 돌아오는데
그게 "거래가 없었다"와 구분되지 않는다.

받는 방법 (2026-07-25 실측)
---------------------------
코드검색 화면의 `법정동 코드 전체자료` 버튼이 하는 일과 동일하다:
  1) `GET /stdcode/regCodeL.do` 로 세션 쿠키를 받고
  2) `POST /etc/codeFullDown.do` (form: codeseId=법정동코드) 로 ZIP 을 받는다.
ZIP 안의 파일명은 CP949 로 인코딩돼 있고(`법정동코드 전체자료.txt`),
내용도 CP949 탭 구분이다: `법정동코드 \t 법정동명 \t 폐지여부`.

세션 쿠키 없이 GET 만 하면 `alert('파일이 삭제되었거나 없습니다.')` HTML 이 온다 —
이걸 파일로 저장하면 조용히 깨진 데이터가 되므로 **ZIP 인지 반드시 확인**한다.

사용
----
    python scripts/fetch_legal_dong_codes.py --out data/reference/legal_dong_code_full.txt
"""
from __future__ import annotations

import argparse
import io
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import REPO_ROOT, capped_get  # noqa: E402

LIST_URL = "https://www.code.go.kr/stdcode/regCodeL.do"
DOWNLOAD_URL = "https://www.code.go.kr/etc/codeFullDown.do"
DEFAULT_OUT = REPO_ROOT / "data" / "reference" / "legal_dong_code_full.txt"

#: 브라우저 폼이 보내는 값. 서버가 이 이름으로 코드체계를 고른다.
FORM = {"codeseId": "법정동코드", "cPage": "1", "pageSize": "10", "disuseAt": "0"}


def download(timeout: float = 180.0) -> bytes:
    import httpx

    with httpx.Client(timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (compatible; realestate-ingest/1.0)"}) as c:
        # 세션 쿠키 확보. 본문은 쓰지 않지만 `c.get()` 은 그래도 전량 버퍼링하므로
        # 여기도 상한을 통과시킨다(SR25-1) — '안 쓰는 응답'이 예외가 되지 않게.
        capped_get(c, LIST_URL, what="법정동코드 목록 페이지")
        # 상한이 걸린 읽기(SR17-5→SR24-2). `resp.content` 는 상한 검사 전에 이미
        # 본문 전체를 메모리에 올리므로 쓰지 않는다.
        return capped_get(c, DOWNLOAD_URL, method="POST", data=FORM,
                          headers={"Referer": LIST_URL}, what="법정동코드 전체자료")


def extract(payload: bytes) -> tuple[str, bytes]:
    """ZIP → (원본 파일명, 내용). ZIP 이 아니면 명시적으로 실패한다."""
    if not payload[:2] == b"PK":
        preview = payload[:200].decode("utf-8", "replace")
        raise SystemExit(
            "[FAIL] ZIP 이 아닌 응답을 받았습니다 — 사이트 구조가 바뀌었을 수 있습니다.\n"
            f"       응답 앞부분: {preview!r}\n"
            f"       수동 경로: {LIST_URL} → '법정동 코드 전체자료'"
        )
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        info = z.infolist()[0]
        try:
            name = info.filename.encode("cp437").decode("cp949")   # ZIP 이 CP949 파일명
        except Exception:                                          # noqa: BLE001
            name = info.filename
        with z.open(info) as src:
            buf = io.BytesIO()
            shutil.copyfileobj(src, buf)
        return name, buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="법정동코드 전체자료 내려받기")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    print(f"[INFO] 내려받는 중: {DOWNLOAD_URL}")
    payload = download()
    name, content = extract(payload)

    header = content[:120].decode("cp949", "replace").splitlines()[:1]
    if not header or "법정동코드" not in header[0]:
        raise SystemExit(f"[FAIL] 예상한 헤더가 아닙니다: {header!r}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(content)
    lines = content.count(b"\n")
    print(f"[DONE] {out} ({len(content):,} bytes · {lines:,} 줄 · 원본명 {name!r})")
    print("       다음: python scripts/load_regions.py --file " + str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
