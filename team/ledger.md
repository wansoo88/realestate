# LEDGER — 작업 원장 (re-pm 전용 갱신)

> 규칙: `re-pm` 만 쓴다. 지시 즉시 1행 추가 → 상태만 갱신(**행 삭제 금지**).
> 상태: `dispatched`(하달) · `working` · `done` · `blocked` · `veto`(re-review 반려) · `escalated`(사람 결정 대기) · `cancelled`
> 게이트: `review-required`(re-review 통과 필수) · `human-approval`(사람 승인 필수) · `none`

| ID | 일시 | 대상 | 제목 | 게이트 | 상태 | 산출물 / 비고 |
|---|---|---|---|---|---|---|
| 2026-07-24-00-team | 2026-07-24 | (전원) | 팀 구성·킥오프(역할 숙지) | none | dispatched | `team/CHARTER.md`, `team/roles/*.md` — re-domain·re-arch·re-data·re-ux·re-review 5인 부팅 |
| 2026-07-24-01-stage1 | 2026-07-24 | re-pm | 1단계 인터뷰·골격 생성 | none | done | `docs/01-interview/*`, `CLAUDE.md`, `skill.md`. CR-001·SR-001(문서 한정) PASS. GitHub push 완료 |
