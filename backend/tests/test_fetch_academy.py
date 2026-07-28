"""학원(NEIS) 수집기 — **페이지네이션 고장 감지**와 산정 집계를 못박는다.

왜 이 테스트가 필요한가 (2026-07-28 실측)
------------------------------------------
NEIS `acaInsTiInfo` 는 인증키가 없으면 오류를 주지 않는다. 대신 `pIndex` 와 `pSize` 를
**조용히 무시하고** 1페이지 5행을 계속 되돌려준다(pIndex 1·2·3·500 실호출 확인).
첫 구현은 그걸 그대로 저장해서 600페이지 3,000행짜리 파일을 만들었는데, `ACA_ASNUM`
으로 접으면 학원 **15곳**이었다. 그런 파일로 밀도를 계산하면 수도권 대부분이
'학원 0개'가 되고, 화면은 그걸 사실로 말한다.

그래서 감지 규칙을 순수 함수로 떼어내고(`pagination_fault`) 여기서 고정한다.
네트워크 없이 도는 테스트라 원천이 죽어 있어도 규칙은 지켜진다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BACKEND_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

fetch_academy = pytest.importorskip("fetch_academy")


def _row(asnum: str, *, course: str = "국어", realm: str | None = None,
         addr: str = "서울특별시 강남구 테헤란로 1", office: str = "B10",
         zone: str = "강남구", status: str = "개원") -> dict:
    return {
        "ATPT_OFCDC_SC_CODE": office,
        "ADMST_ZONE_NM": zone,
        "ACA_ASNUM": asnum,
        "ACA_NM": f"테스트학원{asnum}",
        "REG_STTUS_NM": status,
        "REALM_SC_NM": realm or fetch_academy.REALM_ACADEMIC,
        "LE_CRSE_NM": course,
        "FA_RDNMA": addr,
        "FA_RDNDA": ", 3층 301호",
    }


# ---------------------------------------------------------------------------
# 페이지네이션 고장 감지
# ---------------------------------------------------------------------------

def test_같은_행이_또_오면_고장으로_본다():
    """무키 NEIS 의 실제 동작 — pIndex 를 무시하고 1페이지를 계속 준다."""
    rows = [_row("3000040501"), _row("3000051471")]
    prev = fetch_academy.page_signature(rows)

    fault = fetch_academy.pagination_fault(rows, prev, page=2,
                                           requested_size=1000, total=25522)

    assert fault is not None
    assert "pIndex" in fault
    assert "NEIS_API_KEY" in fault      # 사람이 무엇을 해야 하는지가 사유에 있어야 한다


def test_요청한_pSize_보다_적게_오면_1페이지에서_잡는다():
    """총 25,522행인데 5행만 왔다 = 무키 상한. 2페이지까지 갈 것도 없다."""
    rows = [_row(f"300000000{i}") for i in range(5)]

    fault = fetch_academy.pagination_fault(rows, None, page=1,
                                           requested_size=1000, total=25522)

    assert fault is not None
    assert "5행" in fault


def test_정상_페이지네이션은_통과한다():
    page1 = [_row(f"a{i}") for i in range(1000)]
    page2 = [_row(f"b{i}") for i in range(1000)]

    assert fetch_academy.pagination_fault(page1, None, page=1,
                                          requested_size=1000, total=25522) is None
    assert fetch_academy.pagination_fault(
        page2, fetch_academy.page_signature(page1), page=2,
        requested_size=1000, total=25522) is None


def test_마지막_페이지가_짧은_것은_고장이_아니다():
    """총 1,500행의 2페이지(500행)는 정상이다 — 여기서 오탐하면 수집이 못 끝난다."""
    last = [_row(f"z{i}") for i in range(500)]

    assert fetch_academy.pagination_fault(last, ("prev",), page=2,
                                          requested_size=1000, total=1500) is None


def test_같은_학원이라도_교습과정이_다르면_다른_행이다():
    """행 서명이 ACA_ASNUM 만이면 종합학원 페이지가 통째로 '중복'으로 오판된다."""
    rows_a = [_row("3000040501", course="국어")]
    rows_b = [_row("3000040501", course="수학")]

    assert fetch_academy.page_signature(rows_a) != fetch_academy.page_signature(rows_b)


# ---------------------------------------------------------------------------
# 산정 집계 — 지오코딩 규모의 근거가 되는 숫자들
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "academy.json"
    path.write_text(json.dumps({
        "dataset": "academy",
        "failures": [],
        "pages": [{"acaInsTiInfo": [{"head": [{"list_total_count": len(rows)}]},
                                    {"row": rows}]}],
    }, ensure_ascii=False), encoding="utf-8")
    return path


def test_행이_아니라_고유학원과_고유주소를_센다(tmp_path):
    """호출 수는 **주소** 수다 — 같은 건물의 학원 여럿이 호출 1회를 공유한다."""
    same_building = "서울특별시 강남구 테헤란로 1"
    rows = [
        _row("A", course="국어", addr=same_building),
        _row("A", course="수학", addr=same_building),   # 같은 학원의 다른 과정
        _row("B", course="영어", addr=same_building),   # 같은 건물의 다른 학원
        _row("C", course="영어", addr="서울특별시 강남구 테헤란로 2"),
    ]

    s = fetch_academy.stats(_write(tmp_path, rows))

    assert s["rows"] == 4
    assert s["academies"] == 3
    assert s["unique_addresses_all"] == 2          # ← 카카오 호출 수의 근거


def test_상세주소는_주소_단위에_영향을_주지_않는다(tmp_path):
    """'3층 301호'는 좌표를 바꾸지 않는다 — 넣으면 호출 수가 부풀어 산정이 틀린다."""
    rows = [_row("A", addr="서울특별시 강남구 테헤란로 1"),
            _row("B", addr="서울특별시 강남구  테헤란로 1")]     # 공백만 다름

    s = fetch_academy.stats(_write(tmp_path, rows))

    assert s["unique_addresses_all"] == 1


def test_입시보습만_따로_센다(tmp_path):
    """'학원가'가 뜻하는 것은 입시·보습이다. 예능·체육까지 세면 태그 의미가 흐려진다."""
    rows = [_row("A", realm=fetch_academy.REALM_ACADEMIC,
                 addr="서울특별시 강남구 테헤란로 1"),
            _row("B", realm="예능(대)", addr="서울특별시 강남구 테헤란로 2")]

    s = fetch_academy.stats(_write(tmp_path, rows))

    assert s["academies"] == 2
    assert s["academies_academic"] == 1
    assert s["unique_addresses_academic"] == 1


def test_주소_없는_학원은_버리지_않고_센다(tmp_path):
    """좌표를 못 만드는 건은 **조용히 사라지면 안 된다**(원칙: 유실은 보고 대상)."""
    rows = [_row("A", addr="서울특별시 강남구 테헤란로 1"), _row("B", addr="")]

    s = fetch_academy.stats(_write(tmp_path, rows))

    assert s["academies"] == 2
    assert s["academies_without_address"] == 1
    assert s["unique_addresses_all"] == 1


# ---------------------------------------------------------------------------
# 인증 실패 응답 — **0행 파일을 성공으로 저장하지 않는다** (SR29-3)
#
# NEIS 는 인증 실패·결과 없음을 HTTP 200 + `RESULT` 블록으로 준다. 그때
# `acaInsTiInfo` 가 통째로 없어서 `_block_rows`=[] · `_total_count`=None 이 되고,
# 페이지네이션 검사 두 개가 **둘 다 통과**했다 — 0행짜리 파일이 `failures: []` 로
# 저장되고 로그는 "실패 0"을 찍었다. 막으려던 실패(잘린 목록의 조용한 저장)의
# 한 변종이 '키가 틀린 경우'로 남아 있었다.
# ---------------------------------------------------------------------------

def test_인증키_오류_응답은_실패로_본다():
    """★ 변이: `fetch()` 의 `result_fault` 호출을 지우면 0행이 성공 저장돼 잡힌다."""
    payload = {"RESULT": {"CODE": "INFO-300", "MESSAGE": "인증키가 유효하지 않습니다."}}

    fault = fetch_academy.result_fault(payload)

    assert fault is not None
    assert "INFO-300" in fault
    assert "NEIS_API_KEY" in fault          # 운영자가 할 일이 사유에 있어야 한다


def test_데이터_블록이_없으면_RESULT_가_없어도_실패로_본다():
    assert fetch_academy.result_fault({}) is not None
    assert fetch_academy.result_fault({"other": []}) is not None


def test_정상_응답은_통과한다():
    ok = {"acaInsTiInfo": [{"head": [{"list_total_count": 2}]},
                           {"row": [_row("A"), _row("B")]}]}
    assert fetch_academy.result_fault(ok) is None


def test_인증키_오류가_오면_파일을_쓰지_않고_멈춘다(monkeypatch, tmp_path):
    """★ 경로 전체로 확인한다 — 순수 함수만 맞고 배선이 빠지는 실패를 막는다."""
    monkeypatch.setattr(fetch_academy, "OUT_DIR", tmp_path)
    monkeypatch.setattr(fetch_academy, "_get", lambda *a, **k: {
        "RESULT": {"CODE": "INFO-300", "MESSAGE": "인증키가 유효하지 않습니다."}})

    class _NoWait:
        def wait(self):
            return None

    with pytest.raises(fetch_academy.FetchError) as exc:
        fetch_academy.fetch(limiter=_NoWait(), key="wrong-key")

    assert "INFO-300" in str(exc.value)
    assert not list(tmp_path.glob("*.json")), "0행 파일이 남으면 안 된다"


def test_행정동_통계는_행이_아니라_고유학원_집합을_담는다(tmp_path):
    """CR33-5 — 행은 교습과정 단위라, 행을 세면 종합학원이 있는 동네가 부풀어 보인다.
    이 통계가 '학원가' 임계값의 모집단이 되므로 여기서 틀리면 전부 틀린다.

    ⚠️ 정직하게 적어 둔다: 지금 `stats()` 는 `len(zone_academic)`(=동 수)만 내보내므로
    행/고유 학원의 차이가 **출력으로는 보이지 않는다.** 그래서 여기서는 값이 아니라
    자료구조를 본다 — 행 카운터(`Counter[str]`)로 되돌리면 원소가 `int` 가 되어 잡힌다.
    (밀도 값을 실제로 내보내는 날 이 검사가 값 검사로 바뀌어야 한다.)
    """
    rows = [_row("A", course="국어", zone="대치동"),
            _row("A", course="수학", zone="대치동"),      # 같은 학원의 다른 과정
            _row("A", course="영어", zone="대치동"),
            _row("B", course="국어", zone="상계동")]

    s = fetch_academy.stats(_write(tmp_path, rows))
    assert s["admst_zones_academic"] == 2          # 동 수(행 4개·학원 2곳)

    src = (SCRIPTS_DIR / "fetch_academy.py").read_text(encoding="utf-8")
    assert "zone_academic[f\"{office}/{row.get('ADMST_ZONE_NM') or ''}\"].add(asnum)" in src, (
        "행정동 집계가 고유 학원(ACA_ASNUM) 집합이 아니라 행 카운터로 되돌아갔습니다")
