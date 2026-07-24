"""team_up.py — pjt13-realestate 에이전트 팀 부팅/복구.

    python scripts/team_up.py            # 없는 워커만 띄운다 (기존 pane 보존)
    python scripts/team_up.py --dry-run  # 무엇을 할지만 출력
    python scripts/team_up.py --rebuild  # 워커 pane 전부 닫고 레이아웃부터 재구성

레이아웃 (workspace w4, 한 탭):

    ┌────────┬──────────┬──────────┐
    │        │ re-domain│ re-data  │
    │ re-pm  ├──────────┼──────────┤
    │        │ re-arch  │ re-ux    │
    │        ├──────────┴──────────┤
    │        │      re-review      │
    └────────┴─────────────────────┘

주의사항 (실측으로 확인한 herdr 동작):
- `pane split --ratio R` 의 R 은 **원본 pane 이 유지하는 비율**이다(새 pane 이 1-R).
- `agent start` 는 항상 **포커스된 pane** 에서 분할하므로 여러 개를 연속 실행하면
  한쪽으로 쏠려 pane 이 3줄까지 줄어든다. 그래서 여기서는
  `pane split`(대상 명시) → `pane rename` → `pane run claude` 로 분해해서 만든다.
- 지시는 항상 이름(`re-*`)으로. 재부팅으로 pane id 가 바뀌어도 이름은 유지된다.

역할 정의: team/roles/<name>.md · 팀 규칙: team/CHARTER.md
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERDR = shutil.which("herdr") or "herdr"
ROOT = Path(__file__).resolve().parent.parent
PM = "re-pm"

# (이름, 분할 기준(이름), 방향, 원본 유지 비율)
LAYOUT = [
    ("re-domain", PM, "right", 0.34),   # re-pm 은 좌측 34% 유지
    ("re-review", "re-domain", "down", 0.68),
    ("re-arch", "re-domain", "down", 0.5),
    ("re-data", "re-domain", "right", 0.5),
    ("re-ux", "re-arch", "right", 0.5),
]
WORKERS = [name for name, *_ in LAYOUT]


def _run(args: list[str], quiet: bool = False) -> str:
    p = subprocess.run([HERDR] + args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        if quiet:
            return ""
        raise SystemExit(f"herdr {' '.join(args)} 실패(rc={p.returncode}): {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout


def panes() -> list[dict]:
    d = json.loads(_run(["pane", "list"]))["result"]
    rows = d.get("panes") or d.get("items") or []
    return [p for p in rows if str(p.get("workspace_id")) == "w4"]


def pane_id_of(name: str) -> str | None:
    for p in panes():
        if p.get("label") == name:
            return p["pane_id"]
    return None


def main() -> int:
    dry = "--dry-run" in sys.argv
    rebuild = "--rebuild" in sys.argv

    if pane_id_of(PM) is None:
        raise SystemExit(f"'{PM}' pane 을 못 찾음. 현재 pane 에서 `herdr agent rename <pane_id> {PM}` 먼저 실행.")

    if rebuild and not dry:
        for name in WORKERS:
            pid = pane_id_of(name)
            if pid:
                _run(["pane", "close", pid], quiet=True)
                print(f"close {name} ({pid})")
        time.sleep(1)

    for name, src_name, direction, ratio in LAYOUT:
        if pane_id_of(name):
            print(f"skip  {name} (이미 있음)")
            continue
        src = pane_id_of(src_name)
        if src is None:
            print(f"WARN  {name}: 기준 pane '{src_name}' 없음 — 건너뜀")
            continue
        if dry:
            print(f"dry   {name} <- split {src} {direction} ratio={ratio}")
            continue
        out = _run(["pane", "split", "--pane", src, "--direction", direction,
                    "--ratio", str(ratio), "--no-focus"])
        pid = json.loads(out)["result"]["pane"]["pane_id"]
        _run(["pane", "rename", pid, name])
        _run(["pane", "run", pid, "claude"])
        print(f"start {name} <- {pid}")

    print("\n완료. 확인: herdr agent list")
    print("온보딩: python scripts/tell.py <name> \"너는 <name> 이다. team/CHARTER.md 와 "
          "team/roles/<name>.md 를 읽고 역할을 숙지한 뒤 READY 를 re-pm 에 보고해라.\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
