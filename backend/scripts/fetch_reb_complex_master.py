"""한국부동산원 **공동주택 단지 식별정보** 내려받기 (공공데이터포털 파일데이터).

왜 자동화하는가
---------------
`fetch_legal_dong_codes.py` 와 같은 이유다. 부동산원 단지 마스터는 주기적으로 갱신되고
(2026-07-26 기준 기본정보는 2025-09-18자, 동정보는 2025-11-11자), 사람이 브라우저로 받아
옮기는 절차는 **갱신을 미루게 만든다**. 낡은 마스터로 매칭하면 신축 단지가 조용히
'매칭 실패'로 남고, 그게 "부동산원에 없다"인지 "우리가 안 받았다"인지 구분되지 않는다.

받는 방법 (2026-07-26 실측)
---------------------------
포털의 '다운로드' 버튼이 하는 일과 동일하다(로그인 불필요):
  1) `GET /tcs/dss/selectFileDataDownload.do?publicDataPk=..&publicDataDetailPk=uddi:..`
     → JSON. `status:true` 와 함께 그 시점의 `atchFileId` 를 준다.
  2) `GET /cmm/cmm/fileDownload.do?atchFileId=..&fileDetailSn=..&dataNm=..`
     → CSV 본문.

⚠️ `atchFileId` 는 **갱신될 때마다 바뀐다.** 그래서 1단계를 건너뛰고 파일 ID 를 코드에
   박아두면 안 된다 — 어느 날 조용히 옛날 파일을 받게 된다.

⚠️ 실패를 성공처럼 저장하지 않는다. 포털은 오류일 때도 200 에 HTML/JSON 을 준다.
   헤더 첫 줄에 기대한 컬럼이 없으면 **저장하지 않고 멈춘다**.

인코딩
------
2026-07-26 배포본은 UTF-8 BOM 이다. 공공데이터포털 파일은 CP949 인 경우도 흔해서
파서(app/ingest/reb.py `decode_csv`)가 둘 다 받는다. 여기서는 **원본 바이트 그대로** 저장한다.

사용
----
    python scripts/fetch_reb_complex_master.py                 # 기본정보+동정보 둘 다
    python scripts/fetch_reb_complex_master.py --dataset basic
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# ⚠️ `_common` import 자체가 sys.path·로깅 억제·비밀 마스킹을 설치한다(SR17-3).
from _common import REPO_ROOT  # noqa: E402

PORTAL = "https://www.data.go.kr"
META_URL = f"{PORTAL}/tcs/dss/selectFileDataDownload.do"
FILE_URL = f"{PORTAL}/cmm/cmm/fileDownload.do"
UA = "Mozilla/5.0 (compatible; realestate-ingest/1.0)"

OUT_DIR = REPO_ROOT / "data" / "reference"


@dataclass(frozen=True)
class Dataset:
    key: str
    title: str
    public_data_pk: str
    detail_pk: str
    filename: str
    #: 헤더 첫 줄에 반드시 있어야 하는 컬럼들. 하나라도 없으면 배포 형식이 바뀐 것이다.
    required_columns: tuple[str, ...]

    @property
    def page(self) -> str:
        return f"{PORTAL}/data/{self.public_data_pk}/fileData.do"


DATASETS = {
    d.key: d for d in (
        Dataset(
            key="basic",
            title="한국부동산원_공동주택 단지 식별정보_기본정보",
            public_data_pk="15106861",
            detail_pk="uddi:46a20910-19aa-462e-ba09-e897b77d0e76",
            filename="reb_complex_basic.csv",
            required_columns=("단지고유번호", "필지고유번호", "주소", "단지종류",
                              "동수", "세대수", "사용승인일"),
        ),
        Dataset(
            key="dong",
            title="한국부동산원_공동주택 단지 식별정보_동정보",
            public_data_pk="15106866",
            detail_pk="uddi:4a122813-024e-40ea-8f01-b9f916f5878f",
            filename="reb_complex_dong.csv",
            required_columns=("단지고유번호", "지상층수"),
        ),
    )
}


def _client(timeout: float):
    import httpx

    return httpx.Client(timeout=timeout, follow_redirects=True,
                        headers={"User-Agent": UA})


def resolve_file_id(client, ds: Dataset) -> tuple[str, str]:
    """(atchFileId, fileDetailSn). 실패하면 사람이 할 일을 알려주고 멈춘다."""
    resp = client.get(META_URL,
                      params={"publicDataPk": ds.public_data_pk,
                              "publicDataDetailPk": ds.detail_pk},
                      headers={"Referer": ds.page})
    resp.raise_for_status()
    try:
        meta = json.loads(resp.text)
    except json.JSONDecodeError:
        raise SystemExit(
            f"[FAIL] {ds.title}: 파일정보 응답이 JSON 이 아닙니다 — 포털 구조가 바뀌었을 수 "
            f"있습니다.\n       수동 경로: {ds.page}") from None
    if not meta.get("status") or not meta.get("atchFileId"):
        raise SystemExit(
            f"[FAIL] {ds.title}: 파일정보를 받지 못했습니다(status={meta.get('status')!r}).\n"
            f"       수동 경로: {ds.page} → '다운로드'")
    return str(meta["atchFileId"]), str(meta.get("fileDetailSn") or "1")


def download(client, ds: Dataset, atch_file_id: str, detail_sn: str) -> bytes:
    resp = client.get(FILE_URL,
                      params={"atchFileId": atch_file_id, "fileDetailSn": detail_sn,
                              "dataNm": ds.key},
                      headers={"Referer": ds.page})
    resp.raise_for_status()
    return resp.content


def check_header(ds: Dataset, payload: bytes) -> str:
    """헤더 첫 줄을 확인한다. 기대한 컬럼이 없으면 **저장하지 않는다.**"""
    from app.ingest.reb import decode_csv

    head = payload[:4096]
    try:
        text = decode_csv(head)
    except ValueError:
        preview = head[:200].decode("utf-8", "replace")
        raise SystemExit(
            f"[FAIL] {ds.title}: CSV 가 아닌 응답을 받았습니다(로그인 페이지·오류 HTML?).\n"
            f"       응답 앞부분: {preview!r}\n       수동 경로: {ds.page}") from None
    header = text.splitlines()[0] if text.splitlines() else ""
    missing = [c for c in ds.required_columns if c not in header]
    if missing:
        raise SystemExit(
            f"[FAIL] {ds.title}: 헤더에 기대한 컬럼이 없습니다: {missing}\n"
            f"       실제 헤더: {header[:200]!r}\n       수동 경로: {ds.page}")
    return header


def fetch(ds: Dataset, out_dir: Path, *, timeout: float) -> Path:
    print(f"[INFO] {ds.title}")
    with _client(timeout) as client:
        client.get(ds.page)                       # 세션 쿠키(있으면) 확보
        atch, sn = resolve_file_id(client, ds)
        print(f"       파일 ID 확인 완료(atchFileId={atch}) — 내려받는 중…")
        payload = download(client, ds, atch, sn)

    header = check_header(ds, payload)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / ds.filename
    out.write_bytes(payload)
    lines = payload.count(b"\n")
    print(f"[DONE] {out} ({len(payload):,} bytes · {lines:,} 줄)")
    print(f"       헤더: {header[:120]}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="부동산원 공동주택 단지 식별정보 내려받기")
    ap.add_argument("--dataset", choices=(*DATASETS, "all"), default="all")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--timeout", type=float, default=300.0)
    args = ap.parse_args(argv)

    keys = list(DATASETS) if args.dataset == "all" else [args.dataset]
    out_dir = Path(args.out_dir)
    paths = [fetch(DATASETS[k], out_dir, timeout=args.timeout) for k in keys]

    print("\n       다음: python scripts/load_reb_complexes.py --basic "
          f"{paths[0]}" + (f" --dong {paths[1]}" if len(paths) > 1 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
