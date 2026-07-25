# 대출·세율 규칙 확장 계약 (loader ↔ engine ↔ 설정값)

> 작성: `re-arch` · ORDER 2026-07-25-10-arch · 2026-07-25
> 대상: **re-domain**(engine 계산 적용) · **re-data**(값 채우기)
> 코드: `backend/app/domain/rules/loader.py` · 테스트: `backend/tests/test_rules_loader.py`

## 0. 왜 이 문서가 있나

re-data 가 세율을 채우다 **로더가 표현 못 하는 규칙 3건**을 에스컬레이션했다
(`config/tax_rules.yaml` 머리말 L1·L2).

| # | 규칙 | 지금 문제 |
|---|---|---|
| 1 | 수도권 주담대 **6억 절대한도** (6.27 대책, 2025) | 미반영 → **실구매 가능액 과대 산정**. 셋 중 오차가 가장 크다 |
| 2 | **스트레스 DSR** 가산금리 | 미반영 → DSR 한도 과대 |
| 3 | 6~9억 취득세 **연속 누진 산식** | 0.5억 서브밴드 근사 → 밴드 내 ±0.2%p |

로더를 확장해 **셋 다 데이터로 표현·로딩**되게 했다.
**계산 적용은 engine(re-domain) 몫이다** — 이 문서의 §3 이 그 인수인계다.

> **하위호환**: 세 필드 모두 **선택 사항**이다. 지금의 `config/tax_rules.yaml`
> (셋 다 없음)은 수정 없이 그대로 로딩되고, 결과도 이전과 같다
> (한도 없음 = `None`, 가산금리 = `0.0`, 고정요율 = 기존 그대로).

---

## 1. 사실(facts) 어휘 — 여기서 어긋나면 규칙이 조용히 미적용된다

`when` 조건은 **엔진이 넘겨준 사실**과 대조된다. 규칙이 참조한 사실을 엔진이 안 넘기면
**매칭 실패 = 규칙 미적용**이다(로더 원칙: 모르면 추정하지 않는다).
그래서 아래 어휘를 양쪽이 똑같이 써야 한다.

| fact | 타입 | 값 | 지금 공급되나 |
|---|---|---|---|
| `price` | int | 거래금액(원) | ✅ engine |
| `area` | float | 전용면적(㎡) | ✅ engine |
| `houses_owned` | int | **취득 후** 주택수 | ✅ engine |
| `regulated` | bool | 조정대상지역 여부 | ✅ engine (`PropertyFacts.is_regulated_area`) |
| `purpose` | str | `live` \| `invest` | ✅ `PropertyFacts.purpose` (대출 규칙엔 아직 미전달) |
| **`region_group`** | str | `수도권` \| `비수도권` | ❌ **없음 — re-domain 이 추가해야 한다** |

> ⚠️ **`region_group` 이 이 확장의 유일한 선행 작업이다.**
> 6억 한도가 수도권 조건부라 이 사실이 없으면 규칙이 있어도 매칭되지 않는다.
> `PropertyFacts` 에 `region_group` 을 추가하고(또는 `target_region_code` 앞 2자리로 파생),
> 대출 한도 조회 시 넘겨야 한다. 파생 규칙: 법정동코드 앞 2자리
> `11`(서울)·`41`(경기)·`28`(인천) → `수도권`, 그 외 → `비수도권`.

`when` 접미사 규약은 기존과 같다: `_max`(이하) · `_min`(이상) · 그 외 완전일치.

---

## 2. 설정 스키마 (re-data 가 채운다)

### 2.1 대출 절대한도 — `lending.absolute_cap`

```yaml
lending:
  ltv: { rate_pct: 70.0, source: ..., source_url: ..., as_of: ... }   # 기존 그대로
  dsr: { rate_pct: 40.0, ... }
  dti: { rate_pct: 60.0, ... }

  absolute_cap:                       # ← 신규. 목록 또는 단일 매핑
    - id: cap_capital_600m
      when: { region_group: "수도권" }
      absolute_cap_krw: 600000000     # 6억
      source: "금융위 6.27 가계부채 관리방안(2025) — 수도권 주담대 6억 한도"
      source_url: "https://www.fsc.go.kr/no010101/84824"
      as_of: "2026-07-25"
```

- 여러 한도가 동시에 맞으면 **가장 작은 것**이 적용된다.
  큰 쪽을 고르면 빌릴 수 없는 금액을 빌릴 수 있다고 말하게 된다.
- `when` 을 생략하면 무조건 적용된다(단일 매핑 형태도 허용).
- 검증: 값이 비었거나 0 이하거나 숫자가 아니면 **로딩 거부**. 출처 3종도 필수.

### 2.2 스트레스 DSR — `lending.stress_dsr`

```yaml
  stress_dsr:
    - id: stress_capital
      when: { region_group: "수도권" }
      stress_rate_pct: 1.5            # %p — 실제 금리에 **더한다**
      source: "금융위 스트레스 DSR 3단계(2025.7 시행) — 수도권 1.5%p"
      source_url: "https://www.fsc.go.kr/no010101/84824"
      as_of: "2026-07-25"
    - id: stress_non_capital
      when: { region_group: "비수도권" }
      stress_rate_pct: 0.75
      source: ...
      source_url: ...
      as_of: ...
```

- 겹치면 **가장 높은 것**이 적용된다(가산금리가 높을수록 한도가 줄어 보수적).
- **음수는 로딩 거부** — 음수면 한도가 늘어난다. 오타 하나로 예산이 과대 산정된다.
- 없으면 `stress_rate_pct(...) == 0.0` → 지금과 동일한 계산.

### 2.3 연속 누진 산식 밴드 — `acquisition_tax[].progressive`

지방세법 §11①8 (6~9억 주택 유상거래): **세율% = 취득가액(억) × 2/3 − 3**

```yaml
acquisition_tax:
  - id: std_le6_small                 # 기존 고정요율 구간 — 그대로 둔다
    when: { houses_owned_max: 2, price_max: 600000000, area_max: 85 }
    rate_pct: 1.0
    extras: { local_education_pct: 0.1, rural_special_pct: 0.0 }
    source: ...; source_url: ...; as_of: ...

  - id: std_6_9_small                 # ← 신규: 0.5억 서브밴드 7개를 이 하나가 대체
    when: { houses_owned_max: 2, price_min: 600000001, price_max: 900000000, area_max: 85 }
    rate_pct: 2.0                     # 폴백 대표값 (§3.3 참조 — 필수)
    progressive:
      basis: price                    # 어떤 사실을 산식에 넣는가 (기본값 price)
      unit_krw: 100000000             # '억' 단위로 환산
      coefficient: 0.6666666666666666 # × 2/3
      constant: -3.0                  # − 3
      min_rate_pct: 1.0               # 클램프 (6억 경계값)
      max_rate_pct: 3.0               # 클램프 (9억 경계값)
    extras_ratio:
      local_education_ratio: 0.1      # 지방교육세 = **본세율 × 1/10** (자동 연동)
    extras:
      rural_special_pct: 0.0          # 85㎡ 이하 농특세 비과세 (금액 대비 고정 %)
    source: "지방세법 §11①8 (6~9억 누진산식) + §151 지방교육세"
    source_url: "https://www.law.go.kr/법령/지방세법/제11조"
    as_of: "2026-07-25"
```

**`extras` 와 `extras_ratio` 의 단위가 다르다 — 여기서 틀리기 쉽다.**

| 필드 | 의미 | 예 |
|---|---|---|
| `extras.*_pct` | **거래금액 대비 %** (고정) | 농특세 0.2% |
| `extras_ratio.*` | **본세율 대비 배율** (연동) | 지방교육세 = 본세×0.1 |

누진 밴드에서 지방교육세를 `extras.local_education_pct` 로 적으면 본세가 변해도 고정돼
틀린다. 반드시 `extras_ratio` 를 쓴다.

**클램프(`min_rate_pct`/`max_rate_pct`)는 필수다.** 계수를 잘못 적으면 음수 세율이나
터무니없는 값이 조용히 나가는데, 그 오류는 수천만 원 단위다. 구간 경계에서는
클램프 값이 곧 정답이기도 하다(6억 → 1.0%, 9억 → 3.0%).

---

## 3. 엔진 연동 (re-domain 이 구현한다)

로더가 제공하는 API는 아래가 전부다. **계산은 하지 않는다.**

### 3.1 절대한도 — `_limits_at` 에 후보 하나 추가

```python
cap_rule = rules.absolute_cap(region_group=..., regulated=..., purpose=...)

candidates = [("LTV", ltv), ("DSR", dsr)]
if dti is not None:
    candidates.append(("DTI", dti))
if cap_rule is not None:
    candidates.append(("CAP", cap_rule.cap_krw))     # ← 절대한도도 경합 후보
binding, effective = min(candidates, key=lambda kv: kv[1])
```

- `LoanLimits` 에 `cap_krw` 필드를, `binding` 에 `"CAP"` 값을 더해야 한다.
- 사용자에게 "무엇이 한도를 결정했는지" 보여주는 게 이 제품의 핵심이라
  **CAP 이 binding 일 때 그 사실이 UI 까지 가야 한다**("수도권 6억 한도에 걸렸습니다").
- 근거(G2): `cap_rule.provenance.to_evidence(f"주담대 절대한도 {cap_rule.cap_krw:,}원")`

### 3.2 스트레스 DSR — **한도 산정 금리에만** 더한다

```python
stress = rules.stress_rate_pct(region_group=...)          # %p, 없으면 0.0
stress_terms = replace(terms, annual_rate=terms.annual_rate + stress / 100.0)
dsr = dsr_limit(borrower, stress_terms, dsr_pct)          # 한도는 가산금리로
```

⚠️ **실제 상환액·이자 계산에는 가산금리를 쓰지 않는다.** 스트레스 금리는 한도를 보수적으로
잡기 위한 심사용 가정이지, 차주가 실제로 내는 금리가 아니다. 둘을 섞으면 월 상환액이
실제보다 크게 표시된다.
- `assumptions` 에 명시: `"스트레스 DSR {stress}%p 가산 적용(한도 산정용 가정 금리)"`
- 근거: `rules.stress_rule(...).provenance.to_evidence(...)`

### 3.3 누진 산식 — `_pct_total(bracket)` → `bracket.total_rate_pct(**facts)`

```python
# 기존
tax = int(price_krw * _pct_total(acq) / 100.0)

# 변경
tax = int(price_krw * acq.total_rate_pct(
    price=price_krw, area=prop.area_m2,
    houses_owned=houses_after, regulated=prop.is_regulated_area) / 100.0)
```

`total_rate_pct` 는 고정요율 구간에서도 **기존과 같은 값**을 낸다
(`rate_pct + extras.*_pct`). 그래서 한 줄 교체로 끝나고, 기존 구간의 회귀도 없다.

> **`rate_pct`(폴백 대표값)를 왜 두었나**
> 엔진이 아직 `total_rate_pct` 로 바꾸지 않았어도 **터지지 않고** 지금의 근사 결과를 내라고
> 남긴 값이다. 즉 §3.3 을 적용하기 전까지 6~9억 구간은 **여전히 근사치**다 —
> 로더만 확장했다고 정확해지지 않는다. 이 전환이 끝나야 L1 이 닫힌다.
> 이분탐색 안에서 `total_rate_pct` 는 P 에 대해 단조 비감소이므로 탐색 전제도 유지된다.

### 3.4 검증 체크리스트 (re-domain 착수 시)

- [ ] `PropertyFacts.region_group` 추가 + 법정동코드 앞 2자리 파생 (§1)
- [ ] `LoanLimits.cap_krw` 추가, `binding` 에 `"CAP"` 허용 (§3.1)
- [ ] DSR 한도만 스트레스 금리 적용, 상환액은 실제 금리 (§3.2)
- [ ] `_pct_total` → `total_rate_pct` 교체 (§3.3)
- [ ] 6억/7.5억/9억 경계 계산 회귀 테스트 (§4 표와 대조)

---

## 4. 검산 표 (구현 후 이 값이 나와야 한다)

누진 산식 `세율% = 가액(억)×2/3 − 3`, 지방교육세 = 본세×1/10, 85㎡ 이하(농특세 0):

| 취득가 | 본세율 | 지방교육세 | 합계 | 취득세액 |
|---|---|---|---|---|
| 6.0억 | 1.000% | 0.100% | **1.100%** | 6,600,000원 |
| 6.5억 | 1.333% | 0.133% | **1.467%** | 9,533,333원 |
| 7.5억 | 2.000% | 0.200% | **2.200%** | 16,500,000원 |
| 8.5억 | 2.667% | 0.267% | **2.933%** | 24,933,333원 |
| 9.0억 | 3.000% | 0.300% | **3.300%** | 29,700,000원 |

경계 연속성: 6억에서 아래 구간(1.1%)과, 9억에서 위 구간(3.3%)과 정확히 이어진다.
현재의 0.5억 서브밴드 근사와 비교하면 밴드 중앙에서는 같고 **경계 근처에서 최대 ±0.2%p**
(7억 매수 시 약 ±140만원) 차이가 난다.

---

## 5. re-data 작업 목록

- [ ] `lending.absolute_cap` — 6.27 대책 수도권 6억 한도. **적용 대상·예외(생애최초 등)
      확인 필요.** 조건이 갈리면 `when` 을 나눠 여러 규칙으로 적는다.
- [ ] `lending.stress_dsr` — 스트레스 DSR 단계별 가산금리(수도권/비수도권, 대출유형별).
      시행 단계와 기준일자를 반드시 함께.
- [ ] `acquisition_tax` — 6~9억 서브밴드 7개(`std_6_0_6_5_*` ~ `std_8_5_9_0_*`)를
      `progressive` 밴드 **하나**로 교체(85㎡ 이하/초과 각 1개). 교체 후 §4 표로 검산.
- [ ] `config/tax_rules.yaml` 머리말의 **L1·L2 한계 문구를 갱신**한다
      (해소됐는지 / 엔진 적용 대기인지 구분해서).

> 값을 채우기 전까지는 셋 다 **없는 상태 그대로 두는 게 맞다.** 빈 껍데기를 넣으면
> 로딩이 거부되고(출처 필수), 틀린 값을 넣으면 조용히 잘못된 예산이 나간다.
