# 05. `portfolio-advisor` — 종합 자문가 (MVP)

> 공통 규약: [`README.md`](README.md)
> 담당 요구사항: **F1·F6** — "**언제 · 어느 단지 · 어느 동 · 왜**"의 최종 답을 만든다

## 목적
다른 에이전트들의 의견을 사용자의 자산·선호·기피로 **가중 종합**해 순위를 매기고,
**사람이 읽고 납득할 근거 리포트**를 만든다. 이 에이전트의 출력이 곧 제품이다.

## ⛔ 가장 위험한 에이전트다
여기서 나온 문장이 사용자의 수억 원 결정을 움직인다. 그래서 제약이 가장 많다.

| 금지 | 이유 |
|---|---|
| 하위 에이전트가 내지 않은 **새로운 사실 창작** | 환각의 주 발생 지점 |
| 리스크 생략·축소 | 장점만 나열하면 G2 반려 |
| "오를 겁니다" 류 단정 | 미래 가격은 아무도 모른다 |
| 투자 권유 표현 | 판단 보조 도구다 |

**규칙: `rationale`의 모든 문장은 하위 `finding`의 `evidence`로 역추적 가능해야 한다.**

## 종합 로직

### A. 점수 집계 (규칙 계산) — 2026-07-26 구현 반영

> ⚠️ **설계 정정.** 초안은 축을 `가격/입지/자금 적합/리스크` 로 잡고
> `Σ(score × weight × confidence)` 를 썼다. 구현·API 계약(`api-spec.md` §2·§5.3)과
> 프론트 슬라이더(`lib/preferences.ts`)의 실제 축은 **`price/location/value/risk`** 이고,
> `자금 적합`은 축이 아니라 **하드 제외**다(아래 B). 정본은 `app/agents/scoring.py::AXIS_SPECS`.
>
> 그리고 초안 시점에는 이 가중치가 **어디에도 연결되지 않았다** — 슬라이더가 DB 에 저장만
> 되고 순위는 신뢰도 가중 평균으로 나왔다. 2026-07-26 에 실제로 연결했다.

```
total_score = Σ(wᵢ × scoreᵢ) / Σ(wᵢ)      (i ∈ 근거가 있는 축)
```
| 축 | 기본값 | 담당 | 점수 신호 |
|---|---|---|---|
| `price` 가격 | 0.30 | `valuation-trader` | 호가−적정가 밴드 갭 |
| `location` 입지 | 0.30 | `location-analyst` | 학군·역세권·인프라 근접 |
| `value` 가치(시세) | 0.25 | `valuation-trader` | 12개월 거래회전율(환금성) |
| `risk` 리스크 | 0.15 | `listing-researcher` (**`risk-auditor` 는 2차**) | 매물 신뢰도 |

**근거가 없는 축은 빼고 재정규화한다.** 0점 처리는 "나쁘다"는 없는 판정을 만들고,
조용한 제외는 사용자가 자기 가중치가 반영된 줄 알게 만든다. 둘 다 금지 —
빠진 비율과 사유를 `score_axes`·`score_notes`·`notes` 로 함께 내보낸다.

**`confidence` 를 가중치에 곱하지 않는다** (초안에서 바뀐 점).
사용자가 30% 라고 한 것이 내부 신뢰도 때문에 21% 로 조용히 바뀌면 슬라이더가 예측
불가능해진다. 대신 confidence 는 ① 근거 유무 판정(점수 `null` → 축 제외)과
② `score_axes[].confidence` 노출로 쓰고, 추정 기반 판단은 애초에 `≤0.6` 으로 캡된다
(`base.py::ESTIMATE_CONFIDENCE_CAP`). 가중치가 아예 없을 때의 폴백만 **기존
신뢰도 가중 평균**을 그대로 쓴다.

### B. 하드 제외 (점수와 무관하게 탈락)
1. `finance-tax-advisor`가 **예산 초과** 판정 → 제외
2. 사용자 `avoid` 조건 위반 → 제외
3. `risk-auditor` severity `high` → 제외 후보로 강등 + **제외 사유 노출**

> 아무리 점수가 높아도 못 사는 집은 추천이 아니다.

### C. 타이밍 판정 (`timing_signal`)
`market-timing-analyst`(2차) + `policy-researcher`(2차) 결과를 합산.
**MVP에서는 이 둘이 없으므로 `timing_signal: "unknown"`을 반환하고,
리포트에 "타이밍 분석은 2차 기능"임을 명시한다.**
없는 기능을 있는 척하지 않는다.

### D. 리포트 생성 (LLM)
입력은 **하위 finding들뿐**. DB 원본이나 추가 지식을 넣지 않는다.
```
당신은 부동산 분석 결과를 요약하는 역할입니다.
아래 분석 결과에 **없는 사실을 추가하지 마세요**.
각 문장은 제공된 evidence 중 하나에 대응해야 합니다.
확신할 수 없으면 "확인 필요"라고 쓰세요.
투자를 권유하는 표현을 쓰지 마세요.

[분석 결과]
{findings_json}
```

## 출력
```json
{
  "agent_id": "portfolio-advisor",
  "items": [
    { "rank": 1, "total_score": 82.4,
      "score_basis": "user_weighted",        // 가중치 없으면 "agent_scores"
      "score_coverage_pct": 70.0,            // 가중치 중 실제로 반영된 비율
      "score_axes": [ /* 축별 weight·applied_weight·score·status·missing (§5.3) */ ],
      "score_notes": ["입지 가중치 30%가 반영되지 않았습니다 — 학구도 데이터 미확보"],
      "complex": { "id": 1024, "name": "○○아파트" },
      "unit_type": { "area_m2": 84.97, "type_name": "84A" },
      "building": { "id": 88, "name": "101동", "confidence": 0.45,
                    "basis": "estimated_from_location" },
      "est_price_krw": 1395000000,
      "timing_signal": "unknown",
      "headline": "예산 내에서 학군·역세권을 모두 만족하는 후보입니다.",
      "why": [
        "○○초 학구도 내부이며 대로 횡단 없이 340m (location-analyst)",
        "동일 타입 37건 중위 14.0억 — 호가 14.8억은 5.7% 높아 협상 여지 (valuation-trader)",
        "취득비용 포함 8.42억으로 한도 8.5억 내 (finance-tax-advisor)"
      ],
      "why_not": [
        "간선도로 45m — 동측 세대 소음 확인 필요 (location-analyst)",
        "용적률 249%로 재건축 사업성 낮음 (valuation-trader)",
        "실거래 신고 지연 최대 30일 — 최근 시세 미반영 가능"
      ],
      "next_actions": [
        "101동·105동 소음 차이 현장 확인",
        "호가 14.8억 → 14.2억 협상 여지 타진"
      ] } ],
  "excluded": [ { "complex_id": 2048, "reason": "예산 초과 (필요자금 9.1억 > 한도 8.5억)" } ],
  "disclaimer": "투자 권유가 아니며 개인 판단을 돕는 참고 자료입니다. 실제 계약 전 현장 확인과 전문가 상담을 권합니다."
}
```

### `why_not`은 선택이 아니라 필수
비어 있으면 그 자체가 결함이다. 확인된 리스크가 없다면
`"확인된 하방 리스크 없음 — 단, 데이터 부족일 수 있음"`을 명시한다.

### `next_actions`가 실사용을 가른다
"좋습니다"로 끝나면 사용자는 다음에 뭘 할지 모른다. **현장에서 확인할 것**을 준다.

## 검증 포인트 (re-review) — G2 근거 감사 핵심 대상
- [ ] `why`의 각 항목이 하위 finding으로 역추적되는가
- [ ] `why_not`이 비어 있지 않은가
- [ ] 하위 에이전트에 없던 **새 사실**이 등장하지 않는가
- [ ] 미래 가격 상승을 단정하는 표현이 없는가
- [ ] MVP에서 `timing_signal`을 억지로 채우지 않는가
- [ ] `excluded` 사유가 사용자에게 노출되는가
- [ ] `disclaimer`가 항상 포함되는가
- [ ] 동 추천의 `confidence`가 그대로 전달되는가 (반올림해서 확신처럼 만들지 않는가)
