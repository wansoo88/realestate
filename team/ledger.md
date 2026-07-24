# LEDGER — 작업 원장 (re-pm 전용 갱신)

> 규칙: `re-pm` 만 쓴다. 지시 즉시 1행 추가 → 상태만 갱신(**행 삭제 금지**).
> 상태: `dispatched`(하달) · `working` · `done` · `blocked` · `veto`(re-review 반려) · `escalated`(사람 결정 대기) · `cancelled`
> 게이트: `review-required`(re-review 통과 필수) · `human-approval`(사람 승인 필수) · `none`

| ID | 일시 | 대상 | 제목 | 게이트 | 상태 | 산출물 / 비고 |
|---|---|---|---|---|---|---|
| 2026-07-24-00-team | 2026-07-24 | (전원) | 팀 구성·킥오프(역할 숙지) | none | dispatched | `team/CHARTER.md`, `team/roles/*.md` — re-domain·re-arch·re-data·re-ux·re-review 5인 부팅 |
| 2026-07-24-01-stage1 | 2026-07-24 | re-pm | 1단계 인터뷰·골격 생성 | none | done | `docs/01-interview/*`, `CLAUDE.md`, `skill.md`. CR-001·SR-001(문서 한정) PASS. GitHub push 완료 |
| 2026-07-24-02-design | 2026-07-24 | re-pm | 2단계 설계 전체 (워커 부재로 PM 직접 수행) | review-required | done | `docs/02-design/**` 11개 문서. herdr API 리스너 다운으로 워커 위임 불가 → PM 직접 작성. **re-review 복구 시 G2 근거감사 재수행 필요** |
| 2026-07-24-03-team | 2026-07-24 | (전원) | herdr 팀 복구 | none | blocked | herdr 서버는 살아있으나 API 소켓(named pipe) 소실 → CLI 제어 불가. 서버 재시작 필요(타 워크스페이스 11개 에이전트 영향) — 사람 결정으로 **보류** |
| 2026-07-25-01-build | 2026-07-25 | re-pm | 3단계 구현 1차 (워커 부재로 PM 직접 수행) | review-required | done | `backend/**` `frontend/**` `config/` `deploy/`. 테스트 백엔드 170·프론트 15 통과. CR-004~006 / SR-004~005. **미검증: PostGIS 실행·실API·세율 실제값** |
| 2026-07-25-02-next | 2026-07-25 | (분해됨) | 3단계 잔여 작업 | — | done | 아래 03~06 으로 분해 |
| 2026-07-25-03-arch | 2026-07-25 | re-arch | PostGIS 리포지토리 구현 + 마이그레이션 실검증 | review-required | 하달대기 | herdr 복구 후 tell.py 로 하달. 지시서 작성 완료 |
| 2026-07-25-04-data | 2026-07-25 | re-data | 세율 채우기(출처 필수) + 수집 실행 준비 | review-required | 하달대기 | 자금계산 503 해소가 최우선. 지시서 작성 완료 |
| 2026-07-25-05-review | 2026-07-25 | re-review | CR-004~006/SR-004~005 독립 재감사 (SR4-2 우회 시도) | none | 하달대기 | PM 자체검토 확정/반려. 지시서 작성 완료 |
| 2026-07-25-06-domain | 2026-07-25 | re-domain | 입지 분석 로직 + 동별 추정 구체화 | review-required | 하달대기 | location_finding 스텁 대체. 지시서 작성 완료 |
