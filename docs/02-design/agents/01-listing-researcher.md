# 01. `listing-researcher` — 매물 리서처 (MVP)

> 공통 규약: [`README.md`](README.md)
> 담당 요구사항: **F1**(정보 통합), **F5**(선호/기피 필터)

## 목적
수천 건의 단지·매물에서 **분석할 가치가 있는 후보 20~50건**을 골라낸다.
이 단계에서 후보를 못 줄이면 뒤의 LLM 분석 비용이 폭발한다. **깔때기의 입구**다.

## 입력
| 항목 | 출처 |
|---|---|
| `max_purchase_krw` | `finance-tax-advisor` 결과 (선행 필수) |
| 지역 코드 목록 | 사용자 조건 |
| 면적 범위, 준공년도 | 사용자 조건 |
| `prefer` / `avoid` | `user_preference` |

## 판단 로직

### A. 규칙 (SQL — LLM 없음)
```sql
-- 1) 예산·지역·면적·연식 하드 필터
-- 2) 기피 조건 제외 (avoid)
--    · first_floor        → listing.floor > 1
--    · main_road_noise    → 간선도로 POI 로부터 50m 이내 동 제외
--    · small_complex      → complex.total_households >= N
-- 3) 선호 조건 가점 (prefer) — 제외가 아니라 정렬 가중치
```

### B. 중복 제거
`erd.md` §4 규칙: `complex_id + area_m2 + floor + ask_price(±1%) + 활성기간 겹침`
→ 대표건 1개만 후보로. **나머지는 삭제하지 않고 `duplicate_count`로 집계**한다.

### C. 허위·미끼 매물 의심도 (`trust_score`)
| 신호 | 방향 |
|---|---|
| 동일 단지·타입 중위 실거래 대비 **-15% 이하 호가** | 의심 ↑ (미끼 가능) |
| 등록 후 90일 이상 활성 | 의심 ↑ (실재하지 않거나 안 팔리는 물건) |
| 중복 등록 중개사 수 과다 | 의심 ↑ |
| 최근 갱신 이력 있음 | 의심 ↓ |

> ⚠️ 이건 **의심도이지 판정이 아니다.** "허위매물입니다"라고 단정하지 않는다.
> 급매(진짜 싼 물건)와 미끼는 데이터만으로 구분되지 않는다 → `verdict`는 "확인 필요"까지만.

### D. 급매·장기 미거래 식별
- **급매 후보**: 중위 대비 저가 + `trust_score` 양호 + 최근 등록
- **장기 미거래**: `days_on_market` 상위 + 반복 가격 인하 → 협상 여지 신호

## 출력
```json
{
  "agent_id": "listing-researcher",
  "candidates": [
    { "complex_id": 1024, "unit_type_id": 5, "building_id": 88,
      "ask_price_krw": 1480000000, "floor": 9,
      "days_on_market": 23, "duplicate_count": 4,
      "trust_score": 0.82,
      "flags": ["price_reduced_twice"],
      "prefer_hits": ["subway_within_500m"], "avoid_hits": [] } ],
  "filtered_out": { "over_budget": 812, "avoid_first_floor": 96, "duplicate": 240 },
  "evidence": [ { "claim": "후보 34건", "source": "listing+complex", "as_of": "2026-07-24T09:00Z" } ],
  "confidence": 0.9
}
```
> `filtered_out`을 반드시 반환한다. "왜 이 매물은 안 보이나"에 답할 수 있어야 사용자가 신뢰한다.

## 데이터 의존
`listing`, `complex`, `building`, `unit_type`, `trade`(중위가 비교용), `poi`(기피 조건 판정)

## 데이터가 없을 때
- 호가 수집이 막혔거나 0건 → **실거래 기반 후보로 대체**(공공API 이중화, G4).
  이때 `note: "현재 매물 정보 없음 — 실거래 이력 기준 단지 추천"`을 반드시 표기.
- 지역 내 후보 0건 → `INSUFFICIENT_DATA` + 완화 제안(예산·면적·지역 중 무엇을 풀면 되는지)

## 검증 포인트 (re-review)
- [ ] 기피 조건이 실제로 제외되는가 (가중치로만 처리하고 넘어가지 않는가)
- [ ] 중복 매물이 대표건 1개로 접히는가
- [ ] `trust_score`가 "허위 확정"으로 표현되지 않는가
- [ ] 호가 없을 때 폴백이 동작하는가
