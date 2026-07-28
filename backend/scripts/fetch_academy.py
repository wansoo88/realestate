"""학원·교습소 원천 내려받기 — NEIS `acaInsTiInfo` (수도권 3개 시도교육청).

    python scripts/fetch_academy.py            # 원문 저장 + 산정 통계
    python scripts/fetch_academy.py --stats-only   # 저장된 원문으로 통계만 다시

무엇에 쓰나
-----------
**'학원가' 태그**(주변에 학원이 많다)의 원천이다. ⛔ '학군지'가 아니다 —
이 데이터는 *학원이 몇 개 있는가*만 말하고 *학교 수준이 높은가*는 말하지 않는다
(학업성취도는 확보 불가: `app/domain/location/school_quality.py`).

왜 별도 스크립트인가
--------------------
`fetch_poi.py` 는 OSM(Overpass) + NEIS 학교를 받는다. 학원은 **좌표가 없고 행 수가
학교의 16배**라 지오코딩 산정이 따로 필요하다. 원문 수집과 좌표 확보를 한 스크립트에
묶으면 "받는 김에 7만 건 지오코딩"이 되어 버린다 — 그건 사람 승인 사항이다.

⚠️ 행 = 학원이 아니다
---------------------
`acaInsTiInfo` 는 **교습과정(LE_CRSE_NM)마다 한 행**을 준다. 학원 하나가 국어·영어·
수학 과정을 등록했으면 3행이다. 그래서 밀도의 단위는 항상 `ACA_ASNUM`(등록번호,
자연키) 기준 **고유 학원 수**여야 한다. 행 수를 세면 종합학원이 있는 동네가 부풀어
보인다 — 이 통계가 태그 임계값의 모집단이 되므로 여기서 틀리면 전부 틀린다.

⛔ 2026-07-28 실측 — **인증키 없이는 전량 수집이 불가능하다**
-------------------------------------------------------------
NEIS 는 무키 요청에 `list_total_count`(총건수)는 정직하게 주지만 **행은 5건만** 주고,
`pSize` 도 `pIndex` 도 **무시한다**. pIndex 1·2·3·500 을 모두 호출해 확인했고 네 번 다
같은 5행(ACA_ASNUM 3000040501 …)이 돌아왔다.

그래서 이 스크립트는 페이지가 앞 페이지와 같으면 **즉시 멈추고 파일을 쓰지 않는다.**
예전 판은 그대로 저장했고, 그 결과 600페이지 3,000행이 실은 학원 15곳의 복사본이었다
(`ACA_ASNUM` 으로 접으면 15). 그런 파일은 밀도 통계를 **조용히** 0에 가깝게 만든다 —
이 저장소가 가장 경계하는 실패다. 잘린 목록을 성공으로 저장하지 않는다.

  → 선행조건: NEIS 인증키(open.neis.go.kr, 무료·사람 단계) → `.env` 의 `NEIS_API_KEY`.

합법성 (G4)
-----------
공개 API(NEIS 교육정보 개방 포털). 크롤링이 아니다.
rate limit 0.5초 + User-Agent 명시. `config/sources.yaml: academy_neis` 참조.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import _common  # noqa: F401  (import 부작용: 로깅 억제·마스킹 설치)
from _common import REPO_ROOT, capped_urlopen_read, load_env

from app.ingest.ratelimit import RateLimiter

logger = logging.getLogger("scripts.fetch_academy")

NEIS_URL = "https://open.neis.go.kr/hub/acaInsTiInfo"
USER_AGENT = "pjt13-realestate/0.1 (personal, non-commercial)"

#: 수도권 3개 시도교육청. 서비스 범위(CLAUDE.md)와 같다.
OFFICES = {"B10": "서울특별시교육청", "J10": "경기도교육청", "E10": "인천광역시교육청"}
PAGE_SIZE = 1000
INTERVAL_SEC = 0.5
PAGE_LIMIT = 200                      # 무한루프 방지(경기 40페이지 × 여유)

OUT_DIR = REPO_ROOT / "data" / "raw" / "poi"
OUT_NAME = "academy.json"

#: '학원가' 밀도에 셀 분야. **여기가 태그의 정의 일부**다 — 바꾸면 밀도가 바뀐다.
#: 음악·미술·무용·체육은 학원이지만 '학원가'가 뜻하는 바(입시·보습)가 아니다.
REALM_ACADEMIC = "입시.검정 및 보습"


class FetchError(RuntimeError):
    """수집 실패. 잘린 목록을 성공으로 저장하지 않는다."""


def _get(params: dict[str, str], *, limiter: RateLimiter,
         key: str = "") -> dict[str, Any]:
    """NEIS 한 페이지. 인증키는 **쿼리스트링**으로 가므로 URL 을 찍지 않는다.

    `_common` import 로 URL 로깅 억제·마스킹이 이미 걸려 있지만, 여기서도 예외
    메시지에 URL 을 싣지 않는다(masked_error 와 같은 규약).
    """
    query = dict(params)
    if key:
        query["KEY"] = key
    limiter.wait()
    url = NEIS_URL + "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:      # noqa: S310 - 고정 https
        body = capped_urlopen_read(resp, what="NEIS 학원")
    return json.loads(body.decode("utf-8", "replace"))


def page_signature(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    """페이지 식별용 자연키 나열. **같으면 같은 페이지를 또 받은 것**이다."""
    return tuple(str(r.get("ACA_ASNUM") or "") + "|" + str(r.get("LE_CRSE_NM") or "")
                 for r in rows)


def pagination_fault(rows: list[dict[str, Any]],
                     prev: tuple[str, ...] | None,
                     *, page: int, requested_size: int,
                     total: int | None) -> str | None:
    """페이지네이션이 실제로 동작하는지 판정한다. 고장이면 사유, 정상이면 None.

    무키 상태(또는 키가 거부된 상태)에서 NEIS 는 오류를 주지 않고 **1페이지를 계속
    되돌려준다.** 그걸 못 잡으면 같은 5행이 수천 번 저장되고, 학원 밀도는 조용히
    0에 수렴한다. 순수 함수라 테스트로 못박는다.
    """
    sig = page_signature(rows)
    if prev is not None and sig == prev:
        return (f"p{page}: 앞 페이지와 동일한 행이 돌아왔습니다 — NEIS 가 pIndex 를 "
                f"무시하고 있습니다(무키 상태의 알려진 동작). NEIS_API_KEY 가 필요합니다.")
    if (page == 1 and total is not None and total > len(rows)
            and requested_size > len(rows)):
        return (f"p1: pSize={requested_size} 를 요청했는데 {len(rows)}행만 왔습니다"
                f"(총 {total}행) — 무키 상한(5행)으로 보입니다. NEIS_API_KEY 가 필요합니다.")
    return None


def _block_rows(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for block in payload.get("acaInsTiInfo") or []:
            if isinstance(block, dict) and isinstance(block.get("row"), list):
                out.extend(r for r in block["row"] if isinstance(r, dict))
    return out


def result_fault(payload: Any) -> str | None:
    """데이터 블록이 아예 없는 응답인가. 있으면 사유(NEIS `RESULT` 문구), 정상이면 None.

    ⛔ 이게 없으면 **키가 틀린 경우가 성공으로 저장된다**(SR29-3, 실측).
    NEIS 는 인증 실패·결과 없음을 HTTP 200 + `RESULT` 블록으로 준다:

        {"RESULT": {"CODE": "INFO-300", "MESSAGE": "인증키가 유효하지 않습니다."}}

    이때 `_block_rows` 는 `[]`, `_total_count` 는 `None` 이라 `pagination_fault` 의
    두 검사가 **둘 다 통과한다** — 0행짜리 파일이 `failures: []` 로 저장되고 로그는
    "실패 0"을 찍는다. 무키(5행 반복)는 막으면서 오타 난 키는 통과시키는 셈이다.
    이 저장소가 가장 경계하는 실패(조용한 0행)이므로 여기서 fail-closed 로 막는다.

    ⚠️ `CODE`·`MESSAGE` 는 NEIS 가 준 **고정 문구**이고 우리 인증키가 아니다
    (키는 쿼리스트링으로만 나간다). 그래도 마스킹 계층이 한 번 더 훑는다.
    """
    if not isinstance(payload, dict) or payload.get("acaInsTiInfo"):
        return None
    result = payload.get("RESULT")
    if isinstance(result, dict):
        code = str(result.get("CODE") or "").strip()
        message = str(result.get("MESSAGE") or "").strip()
        return (f"응답에 데이터 블록(acaInsTiInfo)이 없습니다 — RESULT {code}: {message}"
                f" (NEIS_API_KEY 를 확인하세요)")
    return ("응답에 데이터 블록(acaInsTiInfo)이 없습니다 — NEIS_API_KEY 를 확인하세요")


def _total_count(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    for block in payload.get("acaInsTiInfo") or []:
        if not isinstance(block, dict):
            continue
        for head in block.get("head") or []:
            if isinstance(head, dict) and "list_total_count" in head:
                try:
                    return int(head["list_total_count"])
                except (TypeError, ValueError):
                    return None
    return None


def fetch(*, limiter: RateLimiter, key: str = "") -> Path:
    """3개 교육청 전량을 페이지네이션으로 받는다.

    총건수만큼 못 받으면 **failures 에 남긴다** — 잘린 목록은 "이 동네만 학원이 없다"는
    조용한 구멍이 되고, 밀도 태그에서는 그게 곧 오판정이다.
    페이지네이션 자체가 고장이면(무키) **파일을 쓰지 않고 즉시 멈춘다**(모듈 docstring).
    """
    pages: list[dict[str, Any]] = []
    failures: list[str] = []
    for office, office_name in OFFICES.items():
        collected = 0
        total: int | None = None
        page = 1
        prev_sig: tuple[str, ...] | None = None
        while True:
            params = {"Type": "json", "pIndex": str(page), "pSize": str(PAGE_SIZE),
                      "ATPT_OFCDC_SC_CODE": office}
            try:
                payload = _get(params, limiter=limiter, key=key)
            except Exception as exc:                            # noqa: BLE001
                failures.append(f"{office} p{page}: {type(exc).__name__} {exc}")
                logger.error("NEIS 학원 %s 페이지 %d 실패 — %s", office, page, exc)
                break
            # 데이터 블록이 없는 응답(인증 실패 등)은 **0행 성공**으로 저장하지 않는다.
            fault = result_fault(payload)
            if fault is not None:
                raise FetchError(f"{office}({office_name}) p{page}: {fault}")
            rows = _block_rows(payload)
            if page == 1:
                total = _total_count(payload)
            fault = pagination_fault(rows, prev_sig, page=page,
                                     requested_size=PAGE_SIZE, total=total)
            if fault is not None:
                # 저장하지 않는다 — 반쪽짜리 원문이 있으면 다음 사람이 그걸 믿는다.
                raise FetchError(f"{office}({office_name}) {fault}")
            prev_sig = page_signature(rows)
            pages.append(payload)
            collected += len(rows)
            logger.info("NEIS 학원 %s(%s) p%d → %d행 (누적 %d / 총 %s)",
                        office, office_name, page, len(rows), collected, total)
            if not rows or (total is not None and collected >= total):
                break
            page += 1
            if page > PAGE_LIMIT:
                failures.append(f"{office}: 페이지 상한 초과")
                break
        if total is not None and collected < total:
            failures.append(f"{office}: 총 {total}행 중 {collected}행만 수신")

    if not pages:
        raise FetchError("학원: 모든 요청 실패")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / OUT_NAME
    path.write_text(json.dumps({
        "dataset": "academy",
        "source": "neis_academy",
        "license": "교육부 NEIS 교육정보 개방 포털 (공공누리)",
        "offices": OFFICES,
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "failures": failures,
        "pages": pages,
    }, ensure_ascii=False), encoding="utf-8")
    logger.info("학원 저장 %s (응답 %d개, 실패 %d)", path.name, len(pages), len(failures))
    return path


# ---------------------------------------------------------------------------
# 산정 통계 — 지오코딩 규모를 **재기 위한** 집계 (사람 승인 전 단계)
# ---------------------------------------------------------------------------

def _norm_addr(row: dict[str, Any]) -> str:
    """지오코딩 질의 단위 = **도로명주소(건물번호까지)**.

    상세주소(FA_RDNDA: '3층 301호')는 좌표를 바꾸지 않으므로 뗀다 — 이게 곧
    '같은 건물의 학원 여럿이 호출 1회를 공유한다'는 뜻이고, 실제 호출 수의 근거다.
    """
    return " ".join(str(row.get("FA_RDNMA") or "").split())


def stats(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for page in payload.get("pages") or []:
        rows.extend(_block_rows(page))

    by_office_rows: collections.Counter[str] = collections.Counter()
    by_office_aca: dict[str, set[str]] = collections.defaultdict(set)
    by_realm_aca: dict[str, set[str]] = collections.defaultdict(set)
    by_status_aca: dict[str, set[str]] = collections.defaultdict(set)
    aca_all: set[str] = set()
    addr_all: set[str] = set()
    addr_academic: set[str] = set()
    aca_academic: set[str] = set()
    no_addr_aca: set[str] = set()
    #: 행정동별 입시·보습 **고유 학원**(ACA_ASNUM) 집합. ⚠️ 행을 세면 안 된다 —
    #: 행은 교습과정 단위라 종합학원이 있는 동네가 부풀어 보인다(모듈 docstring).
    #: 이 통계가 '학원가' 태그 임계값의 모집단이 되므로 여기서 틀리면 전부 틀린다(CR33-5).
    zone_academic: dict[str, set[str]] = collections.defaultdict(set)

    for row in rows:
        asnum = str(row.get("ACA_ASNUM") or "").strip()
        office = str(row.get("ATPT_OFCDC_SC_CODE") or "").strip()
        realm = str(row.get("REALM_SC_NM") or "").strip()
        status = str(row.get("REG_STTUS_NM") or "").strip()
        addr = _norm_addr(row)
        by_office_rows[office] += 1
        if not asnum:
            continue
        aca_all.add(asnum)
        by_office_aca[office].add(asnum)
        by_realm_aca[realm].add(asnum)
        by_status_aca[status].add(asnum)
        if addr:
            addr_all.add(addr)
        else:
            no_addr_aca.add(asnum)
        if realm == REALM_ACADEMIC:
            aca_academic.add(asnum)
            if addr:
                addr_academic.add(addr)
                zone_academic[f"{office}/{row.get('ADMST_ZONE_NM') or ''}"].add(asnum)

    return {
        "rows": len(rows),
        "academies": len(aca_all),
        "rows_by_office": dict(by_office_rows),
        "academies_by_office": {k: len(v) for k, v in by_office_aca.items()},
        "academies_by_realm": dict(sorted(
            ((k, len(v)) for k, v in by_realm_aca.items()),
            key=lambda kv: -kv[1])),
        "academies_by_status": {k: len(v) for k, v in by_status_aca.items()},
        "unique_addresses_all": len(addr_all),
        "academies_academic": len(aca_academic),
        "unique_addresses_academic": len(addr_academic),
        "academies_without_address": len(no_addr_aca),
        "admst_zones_academic": len(zone_academic),
        "failures": payload.get("failures") or [],
        "fetched_at": payload.get("fetched_at"),
    }


def print_stats(s: dict[str, Any]) -> None:
    logger.info("── NEIS 학원 산정 ──")
    logger.info("행 %s / 고유 학원(ACA_ASNUM) %s  ※ 행=교습과정이라 학원보다 많다",
                f"{s['rows']:,}", f"{s['academies']:,}")
    logger.info("교육청별 행: %s", s["rows_by_office"])
    logger.info("교육청별 고유 학원: %s", s["academies_by_office"])
    logger.info("등록상태별 고유 학원: %s", s["academies_by_status"])
    logger.info("분야별 고유 학원(상위): %s",
                dict(list(s["academies_by_realm"].items())[:8]))
    logger.info("고유 도로명주소 — 전체 %s / 입시·보습 %s",
                f"{s['unique_addresses_all']:,}", f"{s['unique_addresses_academic']:,}")
    logger.info("입시·보습 고유 학원 %s (주소 없는 학원 %s)",
                f"{s['academies_academic']:,}", f"{s['academies_without_address']:,}")
    if s["failures"]:
        logger.warning("수집 실패 %d건: %s", len(s["failures"]), s["failures"][:3])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="NEIS 학원·교습소 원천 내려받기 + 산정 통계")
    ap.add_argument("--stats-only", action="store_true",
                    help="저장된 원문으로 통계만 다시 낸다(네트워크 없음)")
    ap.add_argument("--json", action="store_true", help="통계를 JSON 으로 출력")
    args = ap.parse_args(argv)

    path = OUT_DIR / OUT_NAME
    if not args.stats_only:
        load_env()
        key = os.getenv("NEIS_API_KEY", "").strip()
        if not key:
            # 키 없이도 시도는 한다 — 실패는 pagination_fault 가 **이유를 대며** 낸다.
            # (예전처럼 조용히 5행짜리 파일을 남기지 않는다)
            logger.warning("NEIS_API_KEY 없음 — 무키 상태에서는 5행만 오고 pIndex 가 "
                           "무시됩니다. 전량 수집에는 인증키가 필요합니다.")
        try:
            path = fetch(
                limiter=RateLimiter(min_interval_sec=INTERVAL_SEC, jitter_sec=0.2),
                key=key)
        except FetchError as exc:
            # 스택트레이스 대신 **할 일**을 낸다. 원인이 대개 "키가 없다" 하나뿐이라
            # 운영자가 읽고 바로 조치할 수 있어야 한다.
            raise SystemExit(f"[FAIL] {exc}") from None
    if not path.exists():
        raise SystemExit(f"[FAIL] 원문이 없습니다: {path}")

    s = stats(path)
    if args.json:
        sys.stdout.write(json.dumps(s, ensure_ascii=False, indent=2) + "\n")
    else:
        print_stats(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
