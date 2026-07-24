"""큐 워커 진입점 (worker-agent / worker-ingest).

⚠️ **아직 미구현이다.** 큐 구현(Celery vs RQ vs 자체)이 3단계 구현계획에서
   확정되지 않았고(implementation-plan.md T7), 확정 전에 아무거나 붙이면
   나중에 통째로 다시 짜야 한다.

지금은 **조용히 도는 척하지 않고 명시적으로 실패한다.**
컨테이너가 살아 있는데 아무 일도 안 하는 상태가 가장 위험하다 —
수집이 안 되는 걸 몇 주 동안 모를 수 있다.
"""
from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("worker")

QUEUES = ("analyze", "ingest")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="큐 워커")
    parser.add_argument("--queue", required=True, choices=QUEUES)
    args = parser.parse_args(argv)

    logger.error(
        "'%s' 큐 워커는 아직 구현되지 않았습니다. "
        "docs/03-build/implementation-plan.md T7(에이전트 오케스트레이션) / "
        "T6(수집기 실행 루프) 완료 후 기동하세요. "
        "구현 전까지 컨테이너를 띄우지 마세요 — 도는 것처럼 보이면 "
        "수집·분석이 멈춘 걸 눈치채지 못합니다.",
        args.queue,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
