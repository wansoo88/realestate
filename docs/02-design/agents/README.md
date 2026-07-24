# 런타임 전문가 에이전트 명세

> 2단계 설계 산출물 · 2026-07-24
> 이 문서는 **웹앱 안에서 실제로 분석을 수행하는 에이전트**의 계약이다.
> (개발을 돕는 herdr 팀 에이전트는 `team/roles/` — 서로 다른 것이니 혼동 주의)

---

## 0. 설계 대원칙 — 이걸 어기면 제품이 죽는다

### 원칙 1. 숫자는 코드가, 설명은 LLM이
세금·대출한도·가격 통계는 **결정론적 계산**으로 구한다. LLM에 계산을 시키지 않는다.
LLM은 계산된 숫자를 **사람이 읽을 근거 문장으로 바꾸는 역할**만 한다.

> 왜: 취득세를 LLM이 "대략 1.1%쯤"이라고 답하면 수천만 원이 틀어진다.
> 그리고 그 오류는 그럴듯한 문장에 숨어서 발견되지 않는다.

### 원칙 2. 출처 없는 주장은 출력하지 않는다
모든 `evidence` 항목은 `{claim, source, as_of}`를 갖는다. 특히 **세율·대출규제·정책**은
출처와 기준일자가 없으면 **아예 반환하지 않는다**(`INSUFFICIENT_DATA`).

### 원칙 3. 모르면 "모른다"고 한다
데이터가 없을 때 추정으로 메우지 않는다. `confidence`를 낮추거나 `verdict: "판단 보류"`를 반환한다.
빈칸이 틀린 답보다 낫다.

### 원칙 4. 반대 근거를 함께 낸다
`risks[]`가 비어 있는 finding은 의심스럽다. 장점만 나열하는 추천은 G2에서 반려된다.

### 원칙 5. 동(棟) 판단은 추정임을 항상 표기
국토부 실거래에 동 정보가 없다(`erd.md` §0). 동별 판단은 좌표 기반 추정이므로
`confidence ≤ 0.6`, `basis: "estimated_from_location"`을 반드시 붙인다.

---

## 1. 로스터

| # | ID | 역할 | MVP |
|---|---|---|---|
| 1 | `listing-researcher` | 매물 리서처 | ✅ |
| 2 | `finance-tax-advisor` | 세금·대출 전문가 | ✅ |
| 3 | `valuation-trader` | 매매 전문가 | ✅ |
| 4 | `location-analyst` | 지역 전문가 | ✅ |
| 5 | `portfolio-advisor` | 종합 자문가 | ✅ |
| 6 | `market-timing-analyst` | 타이밍 분석가 | 2차 |
| 7 | `policy-researcher` | 정책 연구가 | 2차 |
| 8 | `risk-auditor` | 리스크 검증가 | 2차 |

> MVP 5종만으로도 **F1·F2·F4·F5·F6**이 성립한다. **F3(타이밍)** 은 2차에서 완성된다.
> 2차 3종은 "있으면 좋은 것"이 아니라 **요구사항 ③(언제 사야 하는지)의 본체**다. 빼먹지 말 것.

---

## 2. 오케스트레이션 흐름

```
[1] finance-tax-advisor  (규칙 계산 · LLM 없음)
        └→ max_purchase_krw 산출          ← 후보를 걸러낼 예산 상한

[2] listing-researcher   (DB 쿼리 중심)
        └→ 예산·지역·면적·기피조건 필터 → 후보 20~50건

[3] ── 병렬 ──────────────────────────────
    valuation-trader     (통계 계산 + LLM 설명)
    location-analyst     (공간쿼리 + LLM 설명)
    market-timing-analyst (지표 계산 + LLM 설명)   [2차]
    policy-researcher    (문서 검색 + LLM 요약)    [2차]
    risk-auditor         (규칙 + LLM)              [2차]

[4] portfolio-advisor    (가중 종합 + LLM 리포트)
        └→ 순위 top_n + "언제·어느 단지·어느 동·왜"
```

**왜 이 순서인가**
- `finance-tax-advisor`를 **맨 먼저** 돌린다. 예산 상한이 없으면 살 수 없는 매물까지 분석해 API 비용을 태운다.
- `listing-researcher`가 후보를 줄인 뒤에 비싼 분석을 붙인다. 수천 건에 LLM을 돌리면 비용이 폭발한다.
- [3]은 서로 독립이므로 **병렬**. 순차로 하면 응답이 몇 배 느려진다.

---

## 3. 공통 출력 계약

모든 에이전트는 아래 스키마로 반환한다(→ `agent_finding` 테이블).

```json
{
  "agent_id": "valuation-trader",
  "target": { "complex_id": 1024, "unit_type_id": 5, "building_id": null },
  "score": 76.0,
  "verdict": "적정가 상단",
  "rationale": "최근 6개월 동일 타입 37건 중위값 14.0억 대비 현재 호가 14.8억은 5.7% 높습니다.",
  "evidence": [
    { "claim": "중위 실거래가 14.0억", "source": "국토부 실거래가",
      "as_of": "2026-06-30", "data_rows": 37, "period": "2026-01~2026-06" }
  ],
  "confidence": 0.80,
  "risks": [
    { "severity": "medium", "detail": "신고 지연 최대 30일 — 최근 1개월 거래는 미반영 가능" }
  ]
}
```

| 필드 | 규칙 |
|---|---|
| `score` | 0~100. 없으면 `null` (0과 다르다) |
| `verdict` | 짧은 한국어 판정 |
| `rationale` | **숫자를 포함한** 한국어 한두 문장. "좋습니다" 금지 |
| `evidence` | 배열. **비어 있으면 반려** |
| `confidence` | 0~1. 추정 기반이면 0.6 이하 |
| `risks` | 반대 근거. 비었으면 "확인된 하방 리스크 없음"을 명시적으로 |

### 실패 반환
```json
{ "agent_id": "...", "verdict": "판단 보류",
  "reason": "INSUFFICIENT_DATA",
  "missing": ["해당 단지 최근 24개월 실거래 0건"],
  "confidence": 0.0 }
```

---

## 4. 프롬프트 보안 (필수)

수집한 매물 설명·정책 문서에는 **악의적 지시가 섞여 들어올 수 있다**(프롬프트 인젝션).

1. 외부 텍스트는 **시스템 지시와 분리**해 데이터 블록으로만 전달한다.
2. 에이전트 출력은 **스키마 검증**을 거친다. 스키마를 벗어나면 폐기하고 재시도.
3. **자산 원본 금액을 프롬프트에 넣지 않는다.** 규칙 계산 결과(한도·적합 여부)만 전달한다
   (`security.md` §6).

---

## 5. 비용 통제

| 장치 | 내용 |
|---|---|
| 결과 캐시 | `(complex_id, unit_type_id, criteria_hash, 데이터 버전)` 키로 redis 캐시 |
| 후보 축소 | LLM 호출은 [3] 단계 후보(20~50건)에만 |
| 규칙 우선 | 계산 가능한 것은 LLM에 보내지 않음 |
| MVP 5종 | 8종 전체 호출은 2차 |

> 추천 1건당 실제 토큰 사용량은 구현 후 실측해 이 문서를 갱신한다.

---

## 6. 개별 명세
- [`01-listing-researcher.md`](01-listing-researcher.md)
- [`02-finance-tax-advisor.md`](02-finance-tax-advisor.md)
- [`03-valuation-trader.md`](03-valuation-trader.md)
- [`04-location-analyst.md`](04-location-analyst.md)
- [`05-portfolio-advisor.md`](05-portfolio-advisor.md)
- [`06-market-timing-analyst.md`](06-market-timing-analyst.md) (2차)
- [`07-policy-researcher.md`](07-policy-researcher.md) (2차)
- [`08-risk-auditor.md`](08-risk-auditor.md) (2차)
