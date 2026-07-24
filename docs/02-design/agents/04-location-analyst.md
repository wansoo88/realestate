# 04. `location-analyst` — 지역 전문가 (MVP)

> 공통 규약: [`README.md`](README.md)
> 담당 요구사항: **F1**(입지 정보 통합), **F5**(선호/기피)

## 목적
"이 자리가 살기 좋은가, 그리고 그게 값을 지탱하는가"를 판정한다.
학군·교통·인프라·유해요소를 **공간쿼리로 실측**하고, 그 결과를 사람이 읽을 문장으로 만든다.

## 판단 로직 — 전부 PostGIS 공간쿼리 (LLM은 설명만)

### A. 학군
| 지표 | 계산 |
|---|---|
| 배정 초등학교 | `ST_Contains(school_district.geom, complex.geom)` — **학구도 내부 여부** |
| 통학 거리 | 단지→학교 최단거리(도보 추정). **횡단보도·대로 횡단 여부**를 별도 표기 |
| 학업성취도 | `poi.attrs` (학교알리미) — **출처·기준연도 필수** |
| 학원가 접근성 | 반경 내 학원 POI 밀도 |

> ⚠️ 학군은 **배정이 바뀔 수 있다.** "○○초 배정"은 현재 기준임을 명시하고 `as_of`를 붙인다.

### B. 교통
| 지표 | 계산 |
|---|---|
| 역세권 | 최근접 지하철역 직선거리 + 노선 수 (환승 가치) |
| 주요 업무지구 소요시간 | 노선 기반 추정 (강남·광화문·여의도) |
| **신설 노선 호재** | `transit_plan` — GTX·신안산선 등, 개통예정일·현재 단계 |
| 간선도로 접근 | IC·주요도로 거리 |

> ⚠️ **교통 호재는 지연이 흔하다.** 착공 전 계획은 `confidence ≤ 0.4`.
> "GTX 개통 예정"을 확정 호재로 쓰면 안 된다. `status`(계획/착공/개통)를 반드시 함께 낸다.

### C. 생활 인프라
대형마트·병원(응급실 보유 여부 구분)·공원·도서관 반경 내 개수와 최단거리.

### D. 유해·감점 요소 (F5 기피 조건)
| 요소 | 판정 |
|---|---|
| 간선도로 소음 | 도로 POI 50m 이내 동 |
| 철도 인접 | 선로 100m 이내 |
| 유해시설 | 유흥·공장·변전소·쓰레기처리 POI 반경 |
| 고압선·송전탑 | POI 존재 시 |

> 감점 요소는 **가점보다 먼저** 계산한다. 사용자가 "피하고 싶다"고 한 건 가중치가 아니라 **제외**다.

## 출력
```json
{
  "agent_id": "location-analyst",
  "score": 78.5,
  "school": { "assigned_elementary": "○○초", "distance_m": 340,
              "crosses_main_road": false, "achievement_pct": 91.2,
              "as_of": "2025", "source": "학교알리미" },
  "transit": {
    "nearest_station": { "name": "○○역", "distance_m": 420, "lines": ["2호선","신분당선"] },
    "commute_min": { "강남": 18, "광화문": 34 },
    "planned": [ { "name": "GTX-C", "status": "착공", "open_expected": "2028-12",
                   "confidence": 0.4 } ]
  },
  "amenities": { "mart_m": 610, "hospital_er_m": 1200, "park_m": 250 },
  "penalties": [ { "type": "main_road_noise", "distance_m": 45, "severity": "medium" } ],
  "verdict": "학군·역세권 양호, 도로 소음 확인 필요",
  "rationale": "○○초 학구도 내부이며 대로 횡단 없이 340m입니다. 2호선·신분당선 환승역 420m로 강남 18분권입니다. 다만 단지 동측이 간선도로 45m로 소음 확인이 필요합니다.",
  "evidence": [
    { "claim": "학구도 내부", "source": "학교알리미 학구도", "as_of": "2026" },
    { "claim": "역까지 420m", "source": "PostGIS 최단거리", "as_of": "2026-07-24" }
  ],
  "confidence": 0.88,
  "risks": [ { "severity": "low", "detail": "학군 배정은 변경될 수 있습니다(현재 기준)" },
             { "severity": "medium", "detail": "GTX-C 개통 시기는 지연 가능성이 있습니다" } ]
}
```

## 데이터 의존
`poi`, `school_district`, `transit_plan`, `complex`, `building`

## 데이터가 없을 때
- 학구도 미확보 지역 → 학군 항목을 **비우고** `missing`에 기록. 최근접 학교 거리로 대체하지 않는다
  (배정과 거리는 다른 개념이다).
- 신설노선 정보 없음 → 호재 없음으로 처리하되 "확인된 계획 없음"으로 명시.

## 검증 포인트 (re-review)
- [ ] 학군이 **거리**가 아니라 **학구도 포함 여부**로 판정되는가
- [ ] 교통 호재에 `status`와 `confidence`가 붙는가
- [ ] 기피 조건이 가점 상쇄가 아니라 제외/경고로 처리되는가
- [ ] 학업성취도에 기준연도·출처가 있는가
- [ ] 직선거리를 도보 시간으로 단정하지 않는가

## 구현 상태 (2026-07-25 · ORDER 2026-07-25-06-domain)
- 순수 계산 로직: `backend/app/domain/location/{models,analysis}.py`
- 테스트: `backend/tests/test_location.py` (22건 — 위 검증 포인트를 그대로 고정)
- 파이프라인 연결: `orchestrator.py::location_finding` — `Candidate.location`(=`LocationFacts`)이
  있으면 실제 근거를, 없으면 판단 보류를 낸다. 기피 해당 후보는 예산 초과와 동일하게 하드 제외.
- 스코어링·신뢰도 정책 근거: `docs/domain/location-scoring.md`
- ⚠️ **미결**: `LocationRepository`(학구도 포함 판정·역/POI/유해요소 최단거리 → `LocationFacts` 조립)가
  아직 없어 실데이터로는 아직 동작하지 않는다(항상 판단 보류). re-arch 요청 대상 — PM 경유.
