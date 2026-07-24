"""워커 감시 — 개입이 필요한 상태 변화만 한 줄로 출력.

Monitor 도구가 이 스크립트를 호출한다(stdout 한 줄 = 알림 하나).

무엇을 감시하나
---------------
- **blocked / unknown** 으로 새로 바뀐 워커: 권한 프롬프트로 멈췄거나 claude 가 꺼진 상태.
  이때만 PM(사람 세션)이 개입해야 한다.
- herdr 응답 불가: 서버가 다시 죽은 경우.

무엇을 감시하지 않나
--------------------
- **완료**: 워커가 `tell.py` 로 re-pm 에게 직접 보고하면 자동으로 도착하므로 여기서 안 본다.
  (idle 은 중간 대기와 구분되지 않아 완료 신호로 못 쓴다.)

상태가 '변할 때만' 출력한다 — 같은 blocked 를 매 폴링마다 반복 알리지 않는다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERDR = shutil.which("herdr") or "herdr"
WS = "w4"
SELF = "re-pm"
POLL_SEC = 20


def snapshot() -> dict[str, str] | None:
    p = subprocess.run([HERDR, "agent", "list"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        return None
    try:
        agents = json.loads(p.stdout)["result"]["agents"]
    except (json.JSONDecodeError, KeyError):
        return None
    return {a["name"]: a["agent_status"] for a in agents
            if a.get("workspace_id") == WS and a.get("name") and a.get("name") != SELF}


def main() -> int:
    prev_attn: set[str] = set()
    alive = True
    while True:
        snap = snapshot()
        if snap is None:
            if alive:
                print("herdr 응답 없음 — 서버가 다시 죽었을 수 있습니다", flush=True)
                alive = False
            time.sleep(POLL_SEC)
            continue
        alive = True

        # 개입이 필요한 상태(권한 프롬프트로 멈춤 / claude 꺼짐)
        attn = {n for n, s in snap.items() if s in ("blocked", "unknown")}
        newly = attn - prev_attn
        if newly:
            detail = ", ".join(f"{n}({snap[n]})" for n in sorted(newly))
            print(f"개입 필요: {detail}", flush=True)
        prev_attn = attn
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    raise SystemExit(main())
