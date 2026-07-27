"""학구도 원천 내려받기 (공공데이터포털 파일데이터 · 인증키 불필요).

받는 것 5종 — 한국교육시설안전원 2026-03-20 판
-----------------------------------------------
  zone     초등학교통학구역 SHP(zip)   15159265   ~35 MB
  middle   중학교학교군 SHP(zip)       15159264   ~23 MB
  high     고등학교학교군 SHP(zip)     15159263   ~3.8 MB
  link     학교학구도연계정보 CSV      15159266   ~2 MB
  location 초중등학교위치 CSV          15159184   ~3.7 MB

⚠️ **초등과 중·고는 데이터셋 이름부터 다르다.**
   초등은 「통학구역」, 중·고는 「학교군」이다. 이건 우리가 붙인 해석이 아니라
   원천 데이터셋의 제목이다(15159265 vs 15159264/15159263). 두 낱말의 뜻이 어떻게
   다른지(단일배정/추첨)는 **원천 어디에도 적혀 있지 않다** — 데이터셋 설명문에도
   배정 방식 필드가 없다. 그래서 우리는 '학교군'이라는 원천의 낱말을 그대로 옮기고
   배정 방식은 '미확인'으로 둔다. ingest/school_zone.py `ZONE_KIND` 참조.

받는 방법
---------
`fetch_reb_complex_master.py` 와 **완전히 같은 2단계**다(로그인·인증키 불필요):
  1) `GET /tcs/dss/selectFileDataDownload.do?publicDataPk=..&publicDataDetailPk=uddi:..`
     → JSON. `status:true` 와 함께 그 시점의 `atchFileId` 를 준다.
  2) `GET /cmm/cmm/fileDownload.do?atchFileId=..&fileDetailSn=..&dataNm=..` → 본문.

⚠️ `atchFileId` 는 갱신될 때마다 바뀐다. 1단계를 건너뛰고 파일 ID 를 박아두면
   어느 날 조용히 옛날 판을 받는다.

⚠️ **구판을 받지 않도록 주의.** 운영주체가 한국지방교육행정연구재단 →
   한국교육시설안전원으로 이관되면서 같은 데이터가 두 벌 올라와 있다.
   구판(15099520/15099521, 2025-09-22)을 받으면 반년 낡은 배정으로 판정하게 된다.

⚠️ 실패를 성공처럼 저장하지 않는다. 포털은 오류일 때도 200 에 HTML/JSON 을 준다.
   기대한 시그니처(zip 매직 · CSV 헤더)가 아니면 **저장하지 않고 멈춘다.**

사용
----
    python scripts/fetch_school_zone.py                # 3종 전부
    python scripts/fetch_school_zone.py --dataset link
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# ⚠️ `_common` import 자체가 sys.path·로깅 억제·비밀 마스킹을 설치한다(SR17-3).
from _common import REPO_ROOT, capped_get  # noqa: E402

PORTAL = "https://www.data.go.kr"
META_URL = f"{PORTAL}/tcs/dss/selectFileDataDownload.do"
FILE_URL = f"{PORTAL}/cmm/cmm/fileDownload.do"
UA = "Mozilla/5.0 (compatible; realestate-ingest/1.0)"

OUT_DIR = REPO_ROOT / "data" / "raw" / "school_zone"


@dataclass(frozen=True)
class Dataset:
    key: str
    title: str
    public_data_pk: str
    detail_pk: str
    filename: str
    kind: str                                  # 'zip' | 'csv'
    #: CSV 헤더 첫 줄에 반드시 있어야 하는 컬럼(zip 은 빈 튜플).
    required_columns: tuple[str, ...] = ()

    @property
    def page(self) -> str:
        return f"{PORTAL}/data/{self.public_data_pk}/fileData.do"


DATASETS = {
    d.key: d for d in (
        Dataset(
            key="zone",
            title="한국교육시설안전원_초등학교통학구역(SHP)",
            public_data_pk="15159265",
            detail_pk="uddi:d01b4591-6f35-4952-8e11-f76dcdbeb765",
            filename="elementary_zone.zip",
            kind="zip",
        ),
        # ⚠️ detail_pk 는 각 데이터셋 페이지의 <input id="publicDataDetailPk"> 값이다.
        #    같은 페이지에 '관련 데이터' 링크로 **다른 데이터셋의 uddi 도 섞여 있으므로**
        #    페이지에서 아무 uddi 나 긁어 쓰면 엉뚱한 파일을 받는다.
        Dataset(
            key="middle",
            title="한국교육시설안전원_중학교학교군(SHP)",
            public_data_pk="15159264",
            detail_pk="uddi:fff72326-2b58-46cf-bc5a-d8fdaf67d532",
            filename="middle_zone.zip",
            kind="zip",
        ),
        Dataset(
            key="high",
            title="한국교육시설안전원_고등학교학교군(SHP)",
            public_data_pk="15159263",
            detail_pk="uddi:45c7539e-a2bc-4b65-8c93-8f92472d9ede",
            filename="high_zone.zip",
            kind="zip",
        ),
        Dataset(
            key="link",
            title="한국교육시설안전원_학교학구도연계정보",
            public_data_pk="15159266",
            detail_pk="uddi:051f35fc-5e03-4e77-a49f-e3577dbb8e03",
            filename="school_zone_link.csv",
            kind="csv",
            required_columns=("학구ID", "학교ID", "학교명", "학교급구분"),
        ),
        Dataset(
            key="location",
            title="한국교육시설안전원_초중등학교위치",
            public_data_pk="15159184",
            detail_pk="uddi:bc02d293-e10a-4733-8a30-dcd6e2b5bfa0",
            filename="school_location.csv",
            kind="csv",
            required_columns=("학교ID", "학교명", "학교급구분", "위도", "경도"),
        ),
    )
}


def _client(timeout: float):
    import httpx

    return httpx.Client(timeout=timeout, follow_redirects=True,
                        headers={"User-Agent": UA})


def resolve_file_id(client, ds: Dataset) -> tuple[str, str, str]:
    """(atchFileId, fileDetailSn, dataNm). 실패하면 사람이 할 일을 알려주고 멈춘다.

    ⚠️ 메타 조회도 `capped_get` 으로 읽는다(SR25-1) — 예외를 만들면 그 예외가 관행이 된다.
    """
    body = capped_get(client, META_URL,
                      params={"publicDataPk": ds.public_data_pk,
                              "publicDataDetailPk": ds.detail_pk},
                      headers={"Referer": ds.page},
                      what=f"{ds.title} 파일정보")
    try:
        meta = json.loads(body)
    except json.JSONDecodeError:
        raise SystemExit(
            f"[FAIL] {ds.title}: 파일정보 응답이 JSON 이 아닙니다 — 포털 구조가 바뀌었을 수 "
            f"있습니다.\n       수동 경로: {ds.page}") from None
    if not meta.get("status") or not meta.get("atchFileId"):
        raise SystemExit(
            f"[FAIL] {ds.title}: 파일정보를 받지 못했습니다(status={meta.get('status')!r}).\n"
            f"       수동 경로: {ds.page} → '다운로드'")
    detail = meta.get("dataSetFileDetailInfo") or {}
    return (str(meta["atchFileId"]), str(meta.get("fileDetailSn") or "1"),
            str(detail.get("dataNm") or ds.key))


def download(client, ds: Dataset, atch_file_id: str, detail_sn: str,
             data_nm: str) -> bytes:
    # 상한이 걸린 읽기(SR23-1→SR24-2) — `resp.content` 는 상한 검사 전에 전부 올린다.
    return capped_get(client, FILE_URL,
                      params={"atchFileId": atch_file_id, "fileDetailSn": detail_sn,
                              "dataNm": data_nm},
                      headers={"Referer": ds.page}, what=ds.title)


def check_payload(ds: Dataset, payload: bytes) -> str:
    """받은 게 진짜 그 파일인지 확인한다. 아니면 **저장하지 않는다.**"""
    if ds.kind == "zip":
        if not payload.startswith(b"PK\x03\x04"):
            preview = payload[:200].decode("utf-8", "replace")
            raise SystemExit(
                f"[FAIL] {ds.title}: zip 이 아닌 응답을 받았습니다(오류 HTML?).\n"
                f"       응답 앞부분: {preview!r}\n       수동 경로: {ds.page}")
        # 묶음 안에 shp/shx/dbf 가 다 있어야 파싱이 된다.
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            suffixes = {n.rsplit(".", 1)[-1].lower() for n in zf.namelist() if "." in n}
        missing = [s for s in ("shp", "shx", "dbf") if s not in suffixes]
        if missing:
            raise SystemExit(
                f"[FAIL] {ds.title}: 묶음에 {missing} 가 없습니다 — 배포 형식이 바뀌었습니다.\n"
                f"       수동 경로: {ds.page}")
        return f"zip({','.join(sorted(suffixes))})"

    from app.ingest.school_zone import _decode

    # ⚠️ 앞부분만 잘라 디코딩하면 안 된다. CP949 는 가변길이라 자른 지점이 한 글자
    #    중간이면 디코딩이 실패하고, 정상 파일을 '오류 HTML' 로 오판해 버린다
    #    (실제로 밟았다 — 연계정보 CSV 가 CP949 다). 원본이 4MB 이하라 통째로 읽는다.
    try:
        text = _decode(payload)
    except ValueError:
        preview = payload[:200].decode("utf-8", "replace")
        raise SystemExit(
            f"[FAIL] {ds.title}: CSV 가 아닌 응답을 받았습니다(로그인 페이지·오류 HTML?).\n"
            f"       응답 앞부분: {preview!r}\n       수동 경로: {ds.page}") from None
    header = text.splitlines()[0] if text.splitlines() else ""
    absent = [c for c in ds.required_columns if c not in header]
    if absent:
        raise SystemExit(
            f"[FAIL] {ds.title}: 헤더에 기대한 컬럼이 없습니다: {absent}\n"
            f"       실제 헤더: {header[:200]!r}\n       수동 경로: {ds.page}")
    return header[:160]


def fetch(ds: Dataset, out_dir: Path, *, timeout: float) -> Path:
    print(f"[INFO] {ds.title}")
    with _client(timeout) as client:
        # 세션 쿠키(있으면) 확보 — 본문을 안 써도 상한은 통과시킨다(SR25-1).
        capped_get(client, ds.page, what=f"{ds.title} 페이지")
        atch, sn, data_nm = resolve_file_id(client, ds)
        # 콘솔 인코딩이 CP949 인 개발기에서도 죽지 않게 프린트에는 ASCII 구분자만 쓴다.
        print(f"       파일 ID 확인 완료(atchFileId={atch}) - 내려받는 중")
        payload = download(client, ds, atch, sn, data_nm)

    signature = check_payload(ds, payload)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / ds.filename
    out.write_bytes(payload)
    print(f"[DONE] {out} ({len(payload):,} bytes)")
    print(f"       확인: {signature}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="학구도 원천 내려받기(초·중·고)")
    ap.add_argument("--dataset", choices=(*DATASETS, "all"), default="all")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--timeout", type=float, default=600.0)
    args = ap.parse_args(argv)

    keys = list(DATASETS) if args.dataset == "all" else [args.dataset]
    out_dir = Path(args.out_dir)
    for key in keys:
        fetch(DATASETS[key], out_dir, timeout=args.timeout)

    print("\n       다음: python scripts/load_school_zone.py "
          f"--src {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
