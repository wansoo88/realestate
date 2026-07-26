"""시군구 코드 실호출 검증 — "0건"이 죽은 코드인지 진짜 무거래인지 가른다.

왜 이 단계가 필요한가
---------------------
`regions_capital.yaml` 은 공식 법정동코드에서 생성되므로 **코드 자체는 정확하다.**
그런데 국토부 실거래가 API 의 `LAWD_CD` 는 법정동코드와 규칙이 하나 다르다:

  · 일반구가 있는 시(수원·성남·고양…)는 **구 단위 코드**로만 데이터가 나온다.
    부모 시 코드(41110 수원시)로 부르면 **정상적으로 0건**이 온다.
  · 반대로, 갓 신설된 코드(2026-07 인천 개편: 제물포·영종·서해·검단구)는
    개편 이전 계약분이 **옛 코드에 남아 있어** 신설 코드로는 0건이 온다.

두 경우 모두 응답은 똑같이 "0건"이다. 그래서 코드 목록만 믿고 수집을 돌리면
**지역 하나가 통째로 비어도 아무도 모른다.** 이 스크립트는 전 코드를 실제로 호출해
0건을 **명시적으로 기록**하고, 이웃(같은 시의 구, 같은 시도)과 비교해 사유를 붙인다.

산출물
------
`config/region_code_verification.yaml` — 코드별 월별 건수 · 판정 · 사유.
수집 배치는 이 파일의 `status: has_data` 만 돌면 되고, `no_data` 는 사람이 본다.

사용
----
    export DATABASE_URL=...            # 불필요 (이 스크립트는 DB 를 쓰지 않는다)
    python scripts/verify_region_codes.py --months 3
    python scripts/verify_region_codes.py --months 3 --extra-codes 28110,28140,28260
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# ⚠️ `_common` import 자체가 로깅 억제·마스킹을 설치한다(SR17-3). 지우지 말 것.
from _common import REPO_ROOT, load_env, mask_secrets, require  # noqa: E402

from app.core.regions import CAPITAL_SIDO, load_capital_sigungu  # noqa: E402
from app.ingest import molit  # noqa: E402
from app.ingest.ratelimit import RateLimiter  # noqa: E402
from app.ingest.run_molit import MOLIT_ENDPOINT, make_http_fetch  # noqa: E402

OUT_PATH = REPO_ROOT / "config" / "region_code_verification.yaml"


def recent_months(today: dt.date, n: int) -> list[str]:
    """검증에 쓸 최근 n개월(YYYYMM). 당월은 신고지연으로 비어 보일 수 있어 **제외**한다."""
    y, m = today.year, today.month
    out: list[str] = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y:04d}{m:02d}")
    return sorted(out)


def parent_of(code5: str) -> str | None:
    """일반구 코드 → 부모 시 코드. 41111(수원 장안구) → 41110(수원시)."""
    if code5.endswith("0"):
        return None
    return code5[:4] + "0"


def children_of(code5: str, all_codes: list[str]) -> list[str]:
    """시 코드 → 그 시의 일반구 코드들. 41110 → [41111, 41113, 41115, 41117]."""
    if not code5.endswith("0"):
        return []
    return [c for c in all_codes if c != code5 and c.startswith(code5[:4]) and not c.endswith("0")]


def probe(service_key: str, code5: str, months: list[str], fetch, limiter: RateLimiter
          ) -> tuple[dict[str, int], str | None]:
    """(월별 건수, 오류메시지). 오류는 삼키지 않고 **키를 지운 뒤** 그대로 돌려준다.

    ⚠️ SR17-1 — 여기서 만든 오류 문자열은 `classify()` → `verdict` → **`render()` 가
    쓰는 `config/region_code_verification.yaml`** 로 간다. 그 파일은 **커밋 대상**이고
    저장소 origin 은 공개 저장소다. API 오류가 한 번이라도 나면 인증키가 git 이력에
    영구히 박힌다. fetch 계층이 이미 마스킹하지만, `service_key` 를 손에 쥔 이 함수도
    같은 책임을 진다 — 주입된 fetch 가 무엇이든 키가 이 경계를 넘지 못한다.
    """
    counts: dict[str, int] = {}
    for ym in months:
        limiter.wait()
        params = molit.build_params(service_key=service_key, region_code5=code5, ym=ym, rows=1000)
        try:
            trades = molit.parse_response(fetch(params))
        except Exception as exc:                              # noqa: BLE001
            return counts, mask_secrets(f"{ym}: {type(exc).__name__}: {exc}",
                                        extra_secrets=(service_key,))
        counts[ym] = len(trades)
    return counts, None


def classify(code5: str, counts: dict[str, int], err: str | None,
             totals: dict[str, int], all_codes: list[str]) -> tuple[str, str]:
    """(status, verdict). 0건을 조용히 넘기지 않고 **왜 0인지**를 남긴다."""
    if err is not None:
        return "error", f"API 오류 — {err}"
    total = sum(counts.values())
    if total > 0:
        return "has_data", ""

    kids = children_of(code5, all_codes)
    if kids:
        kid_total = sum(totals.get(k, 0) for k in kids)
        if kid_total > 0:
            return ("parent_of_gu",
                    f"일반구가 있는 시 — LAWD_CD 는 구 단위를 쓴다(구 합계 {kid_total}건). "
                    "수집 대상에서 제외해도 손실 없음.")
    sido_peers = [c for c in all_codes if c[:2] == code5[:2] and c != code5]
    peer_with_data = sum(1 for c in sido_peers if totals.get(c, 0) > 0)
    return ("no_data",
            f"검증 기간 0건. 같은 시도의 다른 코드 {peer_with_data}/{len(sido_peers)}개는 데이터 있음 "
            "→ 신설/폐지 코드이거나 실제 무거래. 사람이 확인해야 한다.")


def render(rows: list[dict], months: list[str], as_of: dt.date) -> str:
    import json

    counts_by_status: dict[str, int] = {}
    for r in rows:
        counts_by_status[r["status"]] = counts_by_status.get(r["status"], 0) + 1

    lines = [
        "# region_code_verification.yaml — 시군구 코드 실호출 검증 결과 (자동 생성)",
        "#",
        "# 국토부 실거래가 API 를 코드마다 실제로 호출해 응답 건수를 센 기록이다.",
        "# 0건은 두 가지 뜻이 될 수 있어(죽은 코드 / 진짜 무거래) 반드시 사유를 함께 남긴다.",
        "#   has_data     : 데이터 확인 — 수집 대상",
        "#   parent_of_gu : 일반구가 있는 시의 부모 코드 — 구 코드로 수집하므로 정상 0건",
        "#   no_data      : 0건인데 사유 불명 — **사람이 확인해야 한다**",
        "#   error        : API 오류 — 재검증 필요",
        "#",
        f"# 생성: {as_of.isoformat()} · 검증 월: {', '.join(months)}",
        "",
        f'version: "{as_of.isoformat()}"',
        "status: verified",
        f'endpoint: "{MOLIT_ENDPOINT}"',
        "months: [" + ", ".join(f'"{m}"' for m in months) + "]",
        "",
        "summary:",
        f"  total: {len(rows)}",
    ]
    for status in ("has_data", "parent_of_gu", "no_data", "error"):
        lines.append(f"  {status}: {counts_by_status.get(status, 0)}")
    lines += ["", "codes:"]
    for r in rows:
        by_month = json.dumps(r["by_month"], ensure_ascii=False)
        label = f"{r['sido']} {r['name']}".strip()
        lines.append(f'  - code: "{r["code"]}"')
        lines.append(f'    name: "{label}"')
        lines.append(f"    status: {r['status']}")
        lines.append(f"    total: {r['total']}")
        lines.append(f"    by_month: {by_month}")
        if r["verdict"]:
            lines.append(f'    verdict: "{r["verdict"]}"')
    # 파일로 나가기 직전 한 번 더 지운다. 이 산출물은 **커밋 대상**이라 여기서 새면
    # 되돌릴 수 없다(공개 저장소 · git 이력 영구 보존). 중복 방어를 감수한다.
    return mask_secrets("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="시군구 코드 실호출 검증")
    ap.add_argument("--months", type=int, default=3, help="검증할 최근 개월 수(당월 제외)")
    ap.add_argument("--extra-codes", default="", help="추가로 찔러볼 코드(쉼표) — 예: 폐지된 옛 코드")
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--today", help="기준일(YYYY-MM-DD). 기본: 오늘")
    args = ap.parse_args(argv)

    load_env()
    service_key = require("MOLIT_API_KEY")

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    months = recent_months(today, args.months)

    sigungu = load_capital_sigungu()
    entries = [{"code": s.code, "sido": s.sido, "name": s.name} for s in sigungu]
    for extra in [c.strip() for c in args.extra_codes.split(",") if c.strip()]:
        entries.append({"code": extra, "sido": CAPITAL_SIDO.get(extra[:2], "?"),
                        "name": "(추가 검증)"})

    all_codes = [e["code"] for e in entries]
    limiter = RateLimiter(min_interval_sec=0.4, jitter_sec=0.3)
    fetch = make_http_fetch()

    print(f"[INFO] {len(entries)}개 코드 × {len(months)}개월 = {len(entries) * len(months)}회 호출")
    print(f"[INFO] 검증 월: {', '.join(months)}")

    rows: list[dict] = []
    totals: dict[str, int] = {}
    for i, e in enumerate(entries, 1):
        counts, err = probe(service_key, e["code"], months, fetch, limiter)
        total = sum(counts.values())
        totals[e["code"]] = total
        rows.append({**e, "by_month": counts, "total": total, "_err": err})
        flag = "ERR" if err else ("  0" if total == 0 else f"{total:5d}")
        print(f"  [{i:3d}/{len(entries)}] {e['code']} {e['name']:<14} {flag}"
              + (f"  {err}" if err else ""))

    for r in rows:
        r["status"], r["verdict"] = classify(r["code"], r["by_month"],
                                             r["_err"], totals, all_codes)
        r.pop("_err")

    by_status: dict[str, list[str]] = {}
    for r in rows:
        by_status.setdefault(r["status"], []).append(f'{r["code"]} {r["name"]}')
    print("\n[결과]")
    for status in ("has_data", "parent_of_gu", "no_data", "error"):
        items = by_status.get(status, [])
        print(f"  {status}: {len(items)}건" + (f" — {', '.join(items)}" if status != "has_data" else ""))

    out = Path(args.out)
    out.write_text(render(rows, months, today), encoding="utf-8")
    print(f"\n[DONE] 생성: {out}")
    if by_status.get("no_data") or by_status.get("error"):
        print("⚠️ no_data/error 코드가 있습니다 — 조용히 비는 지역이 없는지 사람이 확인하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
