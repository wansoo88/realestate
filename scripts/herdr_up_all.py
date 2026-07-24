"""herdr_up_all.py — herdr 재시작 후 **모든 워크스페이스**의 에이전트 팀을 한 번에 복구.

    python D:/cashflow/pjt13-realestate/scripts/herdr_up_all.py            # 전체 복구
    python .../herdr_up_all.py --dry-run                                   # 계획만 출력
    python .../herdr_up_all.py --workspace w4                              # 한 워크스페이스만
    python .../herdr_up_all.py --no-onboard                                # pane 만 띄우고 지시는 생략

왜 필요한가
-----------
herdr pane 은 서버와 함께 사라진다. 서버를 재시작하면 워크스페이스·탭은 session.json 으로
복원되지만 **각 pane 안에서 돌던 claude 프로세스는 되살아나지 않는다.**
이 스크립트가 pane 생성 → 이름 등록 → claude 기동 → 역할 온보딩까지 한 번에 처리한다.

실측으로 확인한 herdr 동작 (그냥 agent start 를 쓰면 안 되는 이유)
------------------------------------------------------------------
1. `pane split --ratio R` 의 R 은 **원본 pane 이 유지하는 비율**이다(새 pane 이 1-R).
2. `agent start` 는 항상 **포커스된 pane** 에서 분할한다 → 연속 호출하면 한쪽으로 쏠려
   pane 이 3줄까지 찌그러진다. 그래서 `pane split`(대상 명시)로 분해해서 만든다.
3. `pane rename`(label)과 `agent rename`(name)은 **별개**다. 메시지 전송은 name 으로
   조회하므로 **둘 다** 설정해야 한다.
4. `agent send` 는 텍스트만 넣고 Enter 를 누르지 않는다 → `pane send-keys <id> Enter` 필요.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time

HERDR = shutil.which("herdr") or "herdr"

# ---------------------------------------------------------------------------
# 워크스페이스 정의 — 각 프로젝트의 기존 규약을 그대로 따른다(내 규약을 강요하지 않는다)
# ---------------------------------------------------------------------------
WORKSPACES = [
    {
        "id": "w2",
        "label": "pjt12-adsense",
        "cwd": r"D:\cashflow\pjt12-adsense",
        "pm": "pm",
        "workers": ["content", "review", "ops", "growth"],
        "pm_prompt": (
            "복구 완료. 너는 이 프로젝트의 PM 이다. team/CHARTER.md · team/roles/pm.md · "
            "team/ledger.md 를 읽고 진행 중이던 작업과 미결 항목을 파악한 뒤, 사람에게 "
            "현재 상태를 한국어 3~5줄로 보고하고 대기하라."
        ),
        "worker_prompt": (
            "복구 완료. 너는 '{name}' 에이전트다. team/CHARTER.md 와 team/roles/{name}.md 를 "
            "읽고 역할·소유영역·경계를 다시 숙지하라. 아무 파일도 수정하지 말고, 완료되면 "
            'python scripts/tell.py pm "READY {name} | 복구 완료 | 대기 중" 로 보고한 뒤 대기하라. '
            "사람과 직접 대화하지 말고 모든 보고는 pm 에게만 하라."
        ),
    },
    {
        "id": "w3",
        "label": "pjt5-autobtc",
        "cwd": r"D:\cashflow\pjt5-autobtc",
        "pm": "btc-pm",
        "workers": ["btc-quant", "btc-risk", "btc-ops", "btc-ui", "btc-qa"],
        "pm_prompt": (
            "복구 완료. 너는 이 프로젝트의 PM 이다. .claude/orchestration/README.md · "
            ".claude/orchestration/pm.md · .claude/orchestration/BOARD.md 를 읽고 진행 중이던 "
            "작업과 미결 항목을 파악한 뒤, 사람에게 현재 상태를 한국어 3~5줄로 보고하고 대기하라."
        ),
        # btc-<role> → .claude/orchestration/agents/<role>.md
        "worker_prompt": (
            "복구 완료. 너는 '{name}' 워커다. .claude/orchestration/README.md 와 "
            ".claude/orchestration/agents/{role}.md 를 읽고 역할·경계·보고 방식을 다시 숙지하라. "
            "아무 파일도 수정하지 말고, 숙지가 끝나면 그 프로젝트의 보고 규약대로 btc-pm 에게 "
            "READY 를 보고한 뒤 대기하라. 사람과 직접 대화하지 마라."
        ),
        "role_from_name": lambda n: n.replace("btc-", ""),
    },
    {
        "id": "w4",
        "label": "pjt13-realestate",
        "cwd": r"D:\cashflow\pjt13-realestate",
        "pm": "re-pm",
        "workers": ["re-domain", "re-arch", "re-data", "re-ux", "re-review"],
        "pm_prompt": (
            "복구 완료. 너는 이 프로젝트의 PM/PMO 다. team/CHARTER.md · team/roles/re-pm.md · "
            "team/ledger.md · CLAUDE.md 를 읽고 진행 상황(2단계 설계 완료, 3단계 대기)을 파악한 뒤, "
            "사람에게 현재 상태를 한국어 3~5줄로 보고하고 대기하라."
        ),
        "worker_prompt": (
            "복구 완료. 너는 '{name}' 에이전트다. 순서대로 하라. (1) team/CHARTER.md 를 읽고 팀 "
            "운영 규칙과 게이트 G1~G5 를 숙지한다. (2) team/roles/{name}.md 를 읽고 역할·소유영역·"
            "경계를 숙지한다. (3) docs/01-interview/requirements.md 와 docs/02-design/ 산출물을 "
            "훑어 2단계 설계 결과를 파악한다. (4) 아무 파일도 수정하지 말고 대기한다. 완료되면 "
            'python scripts/tell.py re-pm "READY {name} | 소유영역 한줄 | 첫작업 제안 한줄 | 우려사항 한줄" '
            "로 보고하라. 사람과 직접 대화하지 말고 모든 보고는 re-pm 에게만 하라."
        ),
    },
]

# 워커 수별 레이아웃 레시피 — (대상 워커, 분할 기준, 방향, 원본 유지 비율)
# 기준이 PM 이면 왼쪽 34% 를 PM 이 차지하고 나머지를 워커들이 격자로 나눈다.
PM = "__PM__"


def layout_plan(workers: list[str]) -> list[tuple[str, str, str, float]]:
    n = len(workers)
    w = workers
    if n == 0:
        return []
    if n == 1:
        return [(w[0], PM, "right", 0.34)]
    if n == 2:
        return [(w[0], PM, "right", 0.34), (w[1], w[0], "down", 0.5)]
    if n == 3:
        return [(w[0], PM, "right", 0.34), (w[1], w[0], "down", 0.5),
                (w[2], w[0], "right", 0.5)]
    if n == 4:  # 2x2
        return [(w[0], PM, "right", 0.34), (w[1], w[0], "down", 0.5),
                (w[2], w[0], "right", 0.5), (w[3], w[1], "right", 0.5)]
    if n == 5:  # 2x2 + 하단 스트립
        return [(w[0], PM, "right", 0.34), (w[4], w[0], "down", 0.68),
                (w[1], w[0], "down", 0.5), (w[2], w[0], "right", 0.5),
                (w[3], w[1], "right", 0.5)]
    # 6개 이상 — 3x2 격자 + 나머지는 세로 스택
    plan = [(w[0], PM, "right", 0.34), (w[1], w[0], "down", 0.5),
            (w[2], w[0], "right", 0.5), (w[3], w[1], "right", 0.5)]
    prev = w[3]
    for extra in w[4:]:
        plan.append((extra, prev, "down", 0.5))
        prev = extra
    return plan


# ---------------------------------------------------------------------------

def run(args: list[str], quiet: bool = False) -> str:
    p = subprocess.run([HERDR] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        msg = (p.stderr or p.stdout).strip()
        if quiet:
            return ""
        raise RuntimeError(f"herdr {' '.join(args)} 실패: {msg}")
    return p.stdout


def all_panes() -> list[dict]:
    d = json.loads(run(["pane", "list"]))["result"]
    return d.get("panes") or d.get("items") or []


def ws_panes(ws_id: str) -> list[dict]:
    return [p for p in all_panes() if str(p.get("workspace_id")) == ws_id]


def find_pane(ws_id: str, label: str) -> dict | None:
    for p in ws_panes(ws_id):
        if p.get("label") == label:
            return p
    return None


def has_agent(pane: dict) -> bool:
    return bool(pane.get("agent")) and pane.get("agent_status") not in (None, "unknown")


def tell(name: str, pane_id: str, text: str) -> None:
    run(["agent", "send", name, text], quiet=True)
    run(["pane", "send-keys", pane_id, "Enter"], quiet=True)


def ensure_pane(ws: dict, name: str, src_pane_id: str | None,
                direction: str, ratio: float, dry: bool) -> str | None:
    """이름이 name 인 pane 을 보장하고 pane_id 를 반환."""
    existing = find_pane(ws["id"], name)
    if existing:
        pid = existing["pane_id"]
        if not has_agent(existing):
            if dry:
                print(f"    dry  {name}: 기존 pane {pid} 에 claude 기동")
            else:
                run(["pane", "run", pid, "claude"], quiet=True)
                print(f"    run  {name} <- {pid} (기존 pane 재사용)")
        else:
            print(f"    skip {name} <- {pid} (이미 동작 중)")
        run(["agent", "rename", pid, name], quiet=True)
        return pid

    if src_pane_id is None:
        print(f"    WARN {name}: 분할 기준 pane 없음 — 건너뜀")
        return None
    if dry:
        print(f"    dry  {name}: split {src_pane_id} {direction} ratio={ratio}")
        return None

    out = run(["pane", "split", "--pane", src_pane_id, "--direction", direction,
               "--ratio", str(ratio), "--no-focus"])
    pid = json.loads(out)["result"]["pane"]["pane_id"]
    run(["pane", "rename", pid, name], quiet=True)
    run(["pane", "run", pid, "claude"], quiet=True)
    run(["agent", "rename", pid, name], quiet=True)
    print(f"    new  {name} <- {pid}")
    return pid


def recover(ws: dict, dry: bool, onboard: bool, self_pane: str | None) -> None:
    print(f"\n[{ws['id']}] {ws['label']}  ({ws['cwd']})")
    panes = ws_panes(ws["id"])
    if not panes:
        print("    ⚠️  워크스페이스에 pane 이 없습니다 — herdr UI 에서 워크스페이스를 "
              "연 뒤 다시 실행하세요.")
        return

    # PM pane 확보: 라벨이 있으면 그것, 없으면 첫 pane 을 PM 으로 승격
    pm_pane = find_pane(ws["id"], ws["pm"])
    if pm_pane is None:
        pm_pane = panes[0]
        if not dry:
            run(["pane", "rename", pm_pane["pane_id"], ws["pm"]], quiet=True)
            run(["agent", "rename", pm_pane["pane_id"], ws["pm"]], quiet=True)
        print(f"    pm   {ws['pm']} <- {pm_pane['pane_id']} (첫 pane 승격)")
    else:
        print(f"    pm   {ws['pm']} <- {pm_pane['pane_id']}")
    pm_id = pm_pane["pane_id"]

    if not has_agent(pm_pane) and pm_id != self_pane and not dry:
        run(["pane", "run", pm_id, "claude"], quiet=True)
        print(f"         claude 기동")

    ids: dict[str, str] = {PM: pm_id}
    for name, src_name, direction, ratio in layout_plan(ws["workers"]):
        src_id = ids.get(src_name) or (find_pane(ws["id"], src_name) or {}).get("pane_id")
        pid = ensure_pane(ws, name, src_id, direction, ratio, dry)
        if pid:
            ids[name] = pid

    if not onboard or dry:
        return

    print("    ── 기동 대기 후 온보딩 하달 ──")
    for name in ws["workers"]:
        if name in ids:
            run(["agent", "wait", name, "--status", "idle", "--timeout", "180000"], quiet=True)

    role_of = ws.get("role_from_name", lambda n: n)
    for name in ws["workers"]:
        pid = ids.get(name)
        if not pid:
            continue
        text = ws["worker_prompt"].format(name=name, role=role_of(name))
        tell(name, pid, text)
        print(f"    send -> {name}")

    if pm_id != self_pane:
        run(["agent", "wait", ws["pm"], "--status", "idle", "--timeout", "180000"], quiet=True)
        tell(ws["pm"], pm_id, ws["pm_prompt"])
        print(f"    send -> {ws['pm']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workspace", help="w2 / w3 / w4 중 하나만")
    ap.add_argument("--no-onboard", action="store_true", help="pane 만 띄우고 지시는 생략")
    a = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    try:
        run(["pane", "list"])
    except RuntimeError as e:
        print("herdr API 에 연결할 수 없습니다. herdr 를 먼저 실행하세요.")
        print(f"  {e}")
        return 1

    import os
    self_pane = os.environ.get("HERDR_PANE_ID")

    targets = [w for w in WORKSPACES if not a.workspace or w["id"] == a.workspace]
    for ws in targets:
        try:
            recover(ws, a.dry_run, not a.no_onboard, self_pane)
        except RuntimeError as e:
            print(f"    ERROR {ws['id']}: {e}")

    print("\n완료. 확인: herdr agent list")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
