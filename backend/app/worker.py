"""큐 워커 진입점 (worker-ingest).

배포 최소구성은 **redis 없는 api+db** 다. 그래서 별도 큐/워커를 두지 않는다.

- **analyze(추천 분석)**: API 인프로세스 `BackgroundTasks` 로 돈다
  (`app/agents/recommend.py::run_recommendation_job`). 이 워커가 필요 없다 —
  개인용이라 동시성이 낮아 충분하다.
- **ingest(수집)**: 아직 미구현이다(T6 수집기 실행 루프 미확정).
  **조용히 도는 척하지 않고 명시적으로 실패한다.** 컨테이너가 살아 있는데 아무 일도
  안 하는 상태가 가장 위험하다 — 수집이 멈춘 걸 몇 주 동안 모를 수 있다.
"""
from __future__ import annotations

import argparse
import logging
import sys

from app.core.masking import install_log_masking

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
# ⚠️ httpx/httpcore 는 INFO 에서 **요청 URL 을 통째로** 찍는다. 공공데이터포털은 인증키를
#    쿼리스트링(`serviceKey=...`)으로 받으므로, 이걸 켠 채 수집을 돌리면 컨테이너 로그에
#    API 키가 평문으로 남는다(security.md §6 민감정보 로그 금지). 반드시 낮춰 둔다.
for _noisy in ("httpx", "httpcore", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
# 레벨 억제는 **보조** 방어다. 라이브러리 하나가 WARNING 으로 URL 을 찍거나, 예외
# 메시지가 로그로 흘러들면 레벨로는 못 막는다. 그래서 여기서도 마스킹을 설치한다(SR17-3).
install_log_masking()
logger = logging.getLogger("worker")

QUEUES = ("analyze", "ingest")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="큐 워커")
    parser.add_argument("--queue", required=True, choices=QUEUES)
    args = parser.parse_args(argv)

    if args.queue == "analyze":
        logger.error(
            "'analyze' 는 별도 워커가 아니라 API 의 BackgroundTask 로 실행됩니다"
            "(app/agents/recommend.py). 이 프로세스를 띄우지 마세요 — "
            "redis 없는 최소구성이라 큐 워커가 없습니다.")
        return 2

    logger.error(
        "'ingest' 큐 워커는 아직 구현되지 않았습니다. "
        "docs/03-build/implementation-plan.md T6(수집기 실행 루프) 완료 후 기동하세요. "
        "구현 전까지 컨테이너를 띄우지 마세요 — 도는 것처럼 보이면 "
        "수집이 멈춘 걸 눈치채지 못합니다.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
