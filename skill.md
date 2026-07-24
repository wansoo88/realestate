# skill.md — 부동산 AI 자문 시스템 (pjt13-realestate) 활성 스킬

> 이 프로젝트에서 켜진 data-product-studio 스킬과 상태. 단계 진행 시 갱신됩니다.
> **운영 모델**: 사람은 **PM/PMO 오케스트레이터**(`orchestrator` 스킬)에게만 질의. 오케스트레이터가 아래 스킬/역할을 지휘하고 subagent에 위임.

| 스킬 | 단계 | 상태 |
|---|---|---|
| **orchestrator (PM/PMO)** | 총괄 | ▶ 상시 |
| project-interview | 1 인터뷰 | ✅ 완료 |
| architecture-design | 2 설계 | ⬜ 대기 |
| db-modeling | 2 설계 | ⬜ 대기 |
| security-design | 2 설계 | ⬜ 대기 |
| implementation-plan | 3 구현 | ⬜ 대기 |
| code-review | 3 구현 | ⬜ 필수 게이트 |
| security-review | 3 구현 | ⬜ 필수 게이트 |
| testing-unit-e2e | 4 테스트 | ⬜ 대기 |
| monitoring-setup | 5 모니터링 | ⬜ 대기 |
| handover-check | 6 최종점검 | ⬜ 대기 |

## 프로젝트 설정
- 문서 허브: confluence
- 대상 스택: React 반응형 웹 (모바일 퍼스트) → React Native 앱 확장 / Python/FastAPI / PostgreSQL + PostGIS (공간쿼리) @ 자체 서버 (iwinv VPS, `<DEPLOY_HOST>`) — Docker 기반 배포

*생성일: 2026-07-24*
