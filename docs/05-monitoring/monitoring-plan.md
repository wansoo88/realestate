# monitoring-plan.md — 5. 모니터링

> 실제 설치된 감시의 절차·임계값·근거는 **`monitoring.md`** 에 있다.
> 이 파일은 골격 스텁이며, 내용은 그쪽으로 옮겼다.

- 감시 스크립트: `deploy/monitor.sh` · `deploy/monitor-lib.sh` · `deploy/job-run.sh` · `deploy/market-index.sh`
- 감시의 회귀 검사: `deploy/monitor-selftest.sh` (알림 0통 · 운영 상태 미접촉)
- 서버 배치: `/opt/realestate/scripts/`
- 알림: 텔레그램 (pjt12-adsense 봇 재사용 · 읽기만)
- 설치일: 2026-07-30 · 1차 수정: 2026-08-01(CR-040 차단 2건 · SR-036R 조건)
