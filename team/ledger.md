# LEDGER — 작업 원장 (re-pm 전용 갱신)

> 규칙: `re-pm` 만 쓴다. 지시 즉시 1행 추가 → 상태만 갱신(**행 삭제 금지**).
> 상태: `dispatched`(하달) · `working` · `done` · `blocked` · `veto`(re-review 반려) · `escalated`(사람 결정 대기) · `cancelled`
> 게이트: `review-required`(re-review 통과 필수) · `human-approval`(사람 승인 필수) · `none`

| ID | 일시 | 대상 | 제목 | 게이트 | 상태 | 산출물 / 비고 |
|---|---|---|---|---|---|---|
| 2026-07-24-00-team | 2026-07-24 | (전원) | 팀 구성·킥오프(역할 숙지) | none | dispatched | `team/CHARTER.md`, `team/roles/*.md` — re-domain·re-arch·re-data·re-ux·re-review 5인 부팅 |
| 2026-07-24-01-stage1 | 2026-07-24 | re-pm | 1단계 인터뷰·골격 생성 | none | done | `docs/01-interview/*`, `CLAUDE.md`, `skill.md`. CR-001·SR-001(문서 한정) PASS. GitHub push 완료 |
| 2026-07-24-02-design | 2026-07-24 | re-pm | 2단계 설계 전체 (워커 부재로 PM 직접 수행) | review-required | done | `docs/02-design/**` 11개 문서. herdr API 리스너 다운으로 워커 위임 불가 → PM 직접 작성. **re-review 복구 시 G2 근거감사 재수행 필요** |
| 2026-07-24-03-team | 2026-07-24 | (전원) | herdr 팀 복구 | none | done | 2026-07-25 사람이 herdr 재시작 → `herdr_up_all.py` 로 3개 워크스페이스 17개 에이전트 전원 복구. w4 5명 READY 보고 수신(우려사항 정확) |
| 2026-07-25-01-build | 2026-07-25 | re-pm | 3단계 구현 1차 (워커 부재로 PM 직접 수행) | review-required | done | `backend/**` `frontend/**` `config/` `deploy/`. 테스트 백엔드 170·프론트 15 통과. CR-004~006 / SR-004~005. **미검증: PostGIS 실행·실API·세율 실제값** |
| 2026-07-25-02-next | 2026-07-25 | (분해됨) | 3단계 잔여 작업 | — | done | 아래 03~06 으로 분해 |
| 2026-07-25-03-arch | 2026-07-25 | re-arch | PostGIS 리포지토리 + UNIQUE + LocationRepository | review-required | escalated | **코드 전부 완료**(postgis·factory·lifespan·002 UNIQUE·LocationRepo Protocol+PostGIS+스텁). 239 passed 회귀0. **남은 블로커=실행할 DB뿐**(needs_db 29 skip). 사람이 WSL2+Docker 설치키로 결정 → 설치 후 검증 | herdr 복구 후 tell.py 로 하달. 지시서 작성 완료 |
| 2026-07-25-04-data | 2026-07-25 | re-data | 세율 채우기(출처 필수) + 수집 실행 준비 | review-required | done | 세율 verified(지방세법·공인중개사법·6.27대책 출처). **위택스 4/4 일치**. /affordability 503 해소. sources.yaml·robots(fail-closed)·runner. 109 passed. **BLOCKED: MOLIT_API_KEY 사람 발급 필요**. 한계 L1(6~9억 누진 근사)·L2(6억캡·스트레스DSR 미반영) → re-arch 로더확장 | 자금계산 503 해소가 최우선. 지시서 작성 완료 |
| 2026-07-25-05-review | 2026-07-25 | re-review | CR-004~006/SR-004~005 독립 재감사 | none | done | **CR-007/SR-006**: G1·G2·G3·G4·IDOR 전부 CONFIRM PASS. **SR-005의 SR4-2 '해소' 주장 반려(FAIL)** — 가드 5/5 우회·기본값 no-op. 활성유출 없음(구조적방어 유효)이라 커밋 게이트는 통과, T7 배선 전 해소 필수 | PM 자체검토 확정/반려. 지시서 작성 완료 |
| 2026-07-25-06-domain | 2026-07-25 | re-domain | 입지 분석 로직 + 동별 추정 구체화 | review-required | done | 입지 5축(학군=학구도포함·교통 미착공 conf≤0.4·응급실구분·기피 제외·동별 상대점수 conf 0.5 금액환산없음). 192 passed(+22). LocationRepository 부재로 실데이터는 판단보류 → re-arch에 인터페이스 지시함. re-review 재감사 대기 | location_finding 스텁 대체. 지시서 작성 완료 |
| 2026-07-25-07-ux | 2026-07-25 | re-ux | 미완 화면 와이어프레임+명세 + 기존 프론트 UX 감사 | review-required | working | re-ux 제안 반영. 로그인·조건입력·리포트 상세 |
| 2026-07-25-08-domain | 2026-07-25 | re-domain | SR4-2 가드 강화 + G2 basis 라벨 상수화 | review-required | done | 5통과조건 충족: tripwire격하+구조방어 문서화·fail-loud(_derive_forbidden)·단위정규화 매칭·회귀11건·라벨상수화. 239 passed 회귀0. **자기 PASS 선언 안함** → re-review 재검증 대기 |
| 2026-07-25-09-review | 2026-07-25 | re-review | 08-domain SR4-2 수정 재검증 (반려 당사자 확인) | none | working | 5가지 우회 재실측 + open finding 닫기 판정 |
| 2026-07-25-10-arch | 2026-07-25 | re-arch | (다음) 로더 스키마 확장: 6~9억 누진밴드(L1)·수도권6억캡·스트레스DSR(L2) + 003(학구도 기준연도·도로선형) | review-required | 대기 | re-data 에스컬레이션. 자금계산 정확도 |
| 2026-07-25-11-data | 2026-07-25 | re-data | (다음) MOLIT 키 발급 후 실수집 + poi.category/attrs 데이터계약 | review-required | 대기(키 발급 후) | re-arch 요청. 실호출 검증 |
