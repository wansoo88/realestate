# 추천 실행 경로 (worker 없는 BackgroundTask 오케스트레이션)

> 작성: re-domain · 2026-07-25 · ORDER 2026-07-25-24-domain
> 코드: `app/agents/recommend.py`, `app/api/routes.py::create_recommendation`,
>       `app/repositories/memory.py`
> ⚠️ 정확성/근거 판정(G2)은 re-review 소관. 여기서 자기 PASS 선언하지 않는다.

## 왜 redis/워커가 아니라 BackgroundTask 인가
배포 최소구성이 **redis 없는 api+db** 다(개인용, 동시성 낮음). 별도 worker/redis 는 VPS
자원을 초과한다. FastAPI `BackgroundTasks` 로 응답 직후 인프로세스에서 돌린다. 추천 1건당
후보 수십 건, 사용자 사실상 1명이라 직렬 실행으로 충분하다. **redis 의존을 넣지 않는다.**

## 흐름
```
POST /recommendations
  → repo.create_job(job_id, user_id, criteria)  (status 'queued')
  → 202 즉시 반환 (job_id, poll_url)
  → BackgroundTask: run_recommendation_job(repo, settings, job_id, user_id, criteria)
       (1) 프로필 복호화 → Borrower → compute_affordability → 예산
       (2) repo 후보 조회 → group_duplicates → Candidate 조립
       (3) run_mvp_pipeline (llm=None → 규칙 기반 폴백; 키 없이도 동작)
       (4) repo.save_job_result(status='done', items)   (실패 시 'error')
GET /recommendations/{job_id}  → status/items
```
- **예외는 밖으로 던지지 않는다.** 실패하면 job 을 `'error'` 로 남긴다 —
  `'queued'` 로 영영 멈춰 있는 게 최악(worker.py 참조).
- 세율/키는 러너 **안에서** 로드한다(BackgroundTask 는 Depends 를 못 받는다).
- 자산 원본은 `forbidden_amounts` 로만 넘기고 프롬프트엔 싣지 않는다(SR4-2 구조 유지).

## 데이터가 없으면 빈 결과가 정상
수집 전에는 매물·실거래가 없어 후보가 0건 → `status 'done'`, `items []`. 지어내지 않는다.
프로필 미입력도 크래시 없이 `'done'` + 빈 결과.

## repo 인터페이스 — 러너가 duck-typing 으로 호출 (★ re-arch 핸드오프)
인메모리 구현(memory.py)은 이번에 추가했다. **PostgisRepository(re-arch)가 아래를 같은
시그니처로 제공해야 프로덕션에서 동작한다.** 없으면 러너가 경고 로그 + **빈 결과**로
degrade 하고 크래시하지 않는다(있으면 실동작, 없으면 조용히 빈 결과 아님 — 로그 남김).

| 메서드 | 시그니처 | 하는 일 |
|---|---|---|
| `recommendation_candidates` | `(*, region_codes: list[str], max_price_krw: int\|None, limit: int) -> list[ComplexSummary]` | region 조건 후보 단지. **예산으로 거르지 않음**(파이프라인이 사유와 함께 제외) |
| `listings_for_complex` | `(complex_id) -> list[ListingRow]` | 활성 호가(중복 포함, 러너가 group_duplicates) |
| `trades_for_complex` | `(complex_id) -> list[TradeRow]` | 실거래(해제 포함 — 통계 계층이 제외) |
| `save_job_result` | `(job_id, user_id, *, status: str, items: list[dict]) -> None` | 결과 저장 + status 갱신. **user_id 로 소유권 재확인(IDOR)** |
| (기존) `location_facts` | `(complex_id) -> LocationFacts\|None` | 이미 postgis.py 에 있음 — 그대로 사용 |

### `save_job_result` 의 PostGIS 저장 매핑 (re-arch)
pipeline `items[]` 각 항목 → `recommendation_item` 행, 그 안의 `findings[]` → `agent_finding`
행으로 풀어 저장하고 `recommendation_job.status='done'`. 현재 `get_job` 이 읽는
`recommendation_item` 컬럼(rank·total_score·est_price_krw·timing_signal 등)과 매핑을 맞춘다.
(인메모리는 pipeline item 을 그대로 `JobRecord.items` 에 싣는다 — 계약 검증용.)

## 남은 배선 (PM 경유)
- **re-arch**: 위 4개 메서드를 `postgis.py` + `base.py` Protocol 에 추가.
- **re-data**: `listing`·`trade` 적재(수집). 적재 전엔 빈 결과가 정상.
- (선택) LLM: 지금은 `llm=None`(규칙 기반 폴백, 키·비용 없음). 실호출은 배포 시 결정.
