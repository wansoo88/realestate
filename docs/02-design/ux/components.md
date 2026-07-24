# 컴포넌트 명세 — re-fe 구현 입력

> 지시서 `team/orders/2026-07-25-07-ux.md` 산출물 · 2026-07-25 · re-ux
> 근거: `ux/README.md` · `docs/02-design/api-spec.md` · 와이어프레임 `ux/wireframes/*.html`
> 대상: `frontend/src/**` 를 구현하는 `re-fe`. **이 문서는 명세이지 코드가 아니다** — 코드 수정은 re-fe 몫.

---

## 0. 이 문서를 읽는 법

각 컴포넌트는 네 가지를 정의한다.

| 항목 | 뜻 |
|---|---|
| **props** | 타입과 필수 여부. `api/client.ts` 타입을 그대로 쓰는 곳은 그렇게 적었다 |
| **상태** | 컴포넌트 내부에 두는 것 / 위에서 받는 것의 경계 |
| **불확실성 표기** | 추정치·데이터없음을 어떻게 보이게 하는가 (이 제품의 핵심) |
| **접근성** | 반드시 만족해야 하는 것. **하향 금지** |

> ⚠️ 기존 3종(BottomSheet · MapView · ComplexCard)은 이미 구현돼 있다.
> **"현행"** 과 **"변경 요구"** 를 나눠 적었다. 변경 요구의 근거는 `audit-frontend.md` 의 F-번호다.

---

## 1. 계층 규칙 — RN 이식 경계

React Native 확장이 확정이므로 **지금 경계를 지킨다**(`ux/README.md` §10).

```
components/   ← 뷰. RN에서 다시 쓴다 (div → View). 여기에 계산 로직 금지
hooks/        ← 상태·부수효과. RN 100% 재사용
lib/          ← 순수 함수(포맷·계산). RN 100% 재사용
api/          ← 통신. RN 100% 재사용
```

**규칙 세 가지**
1. 컴포넌트 안에서 `fetch`를 직접 부르지 않는다 → `hooks/`
2. 컴포넌트 안에서 금액·비율을 계산하지 않는다 → `lib/format.ts`, `lib/score.ts`
3. `window` / `document` 를 참조하는 코드는 `components/` 안에서도 **한 파일에 격리**한다
   (RN에는 없다). 현재는 `BottomSheet`(드래그)·`MapView`(SDK)가 해당.

---

## 2. 불확실성 표기 규칙 — **단일 진실**

> 이 절이 이 문서에서 가장 중요하다. 여기 어긋난 표기가 하나라도 있으면 G2 위반이다.

### 2.1 상태 정의

| 상태 | 언제 | 표기 | 예 |
|---|---|---|---|
| `confirmed` | 실거래 신고 데이터가 직접 있음 | 일반 텍스트 + `실거래 N건` 배지 | `14.0억` `실거래 37건` |
| `estimated` | 보간·모델 추정 | **`~` 접두 + `--text-estimated` + `추정` 점선 배지** | `~13.95억` `추정` |
| `unknown` | 신뢰도를 판단할 수 없음 | 값 + `신뢰도 미상` 배지 | `14.0억` `신뢰도 미상` |
| 값 없음 | `null` | **`데이터 없음`** (0원·`—` 아님) | `데이터 없음` |

### 2.2 절대 규칙

1. **`데이터 없음`은 값이 `null`일 때만 쓴다.**
   현재 `ComplexCard`는 `price_confidence === "unknown"` 이면 값이 있어도 `데이터 없음` 배지를 붙인다 →
   `14억 [데이터 없음]` 이라는 모순된 표기가 나온다. **F-05로 수정 요구.**
2. **`0원`을 표시하지 않는다.** 금액이 0인 경우는 실무상 없다. 0이 보이면 그건 버그거나 결측이다.
3. **`~` 는 시각 기호이므로 `aria-hidden`**, 대신 배지 텍스트("추정")가 스크린리더용 진실이다.
4. **기준일(`as_of`)이 없으면 `기준일 미상`을 표시한다.** 비워두지 않는다.
5. **추정치를 회색으로만 구분하지 않는다.** 색 + `~` + 배지 = 3중. 색만 쓰면 색각 이상·야외 화면에서 사라진다.
6. **시세가 나오는 모든 화면에 실거래 지연 고지를 붙인다.**
   > 실거래는 신고까지 최대 30일 걸립니다. 최근 거래는 반영되지 않았을 수 있습니다.

### 2.3 `Confidence` 타입 정합성 (⚠️ 백엔드 협의 필요)

| 위치 | 현재 값 | 문제 |
|---|---|---|
| `lib/format.ts` | `"confirmed" \| "estimated" \| "unknown"` | |
| `api/client.ts` `ComplexItem` | `"estimated" \| "unknown"` | **`confirmed` 가 없다** |

→ 프론트에는 "실거래 기준(확정)"을 표시할 경로가 아예 없다. **모든 가격이 추정으로 보인다.**
`re-arch`/`re-be`에 `price_confidence` 에 `confirmed` 포함 여부를 확인 요청해야 한다(PM 경유).
확정 전까지 프론트는 **세 값 모두를 처리할 수 있게** 짠다(모르는 값이 오면 `unknown` 취급).

---

## 3. 원시 컴포넌트 (신규 — 먼저 만든다)

이것들을 먼저 만들고 화면이 이걸 쓰게 한다. **화면마다 가격을 따로 그리면 표기가 갈라진다.**

### 3.1 `<Price>` — 금액 표기의 단일 창구

```ts
interface PriceProps {
  krw: number | null;
  confidence: Confidence;          // "confirmed" | "estimated" | "unknown"
  asOf?: string | null;            // ISO date
  size?: "lg" | "md" | "sm";       // lg=리포트 결론, md=카드, sm=본문 내
  short?: boolean;                 // true → "14.8억" (마커·좁은 자리)
  sampleCount?: number | null;     // 실거래 건수 → confirmed 일 때 배지로
}
```

| 규칙 | 내용 |
|---|---|
| 렌더 | `krw === null` → `<span class="estimated">데이터 없음</span>` 만 출력. 배지 없음 |
| 추정 | `estimated` → `~` (aria-hidden) + `.estimated` + `<ConfidenceBadge>` |
| 폰트 | 항상 `.num` (등폭·`tabular-nums`) — 세로 비교 시 자릿수가 맞아야 읽힌다 |
| 기준일 | `asOf` 가 주어지면 **같은 블록 안에** `formatAsOf()` 로 함께. 멀리 떨어뜨리지 않는다 |
| 접근성 | 금액 전체가 하나의 읽기 단위가 되게 — 숫자와 단위 사이에 요소 경계를 넣지 않는다 |

### 3.2 `<ConfidenceBadge>`

```ts
interface ConfidenceBadgeProps { confidence: Confidence; sampleCount?: number | null }
```

| confidence | 라벨 | 스타일 |
|---|---|---|
| `confirmed` | `실거래 N건` (N 없으면 `실거래 기준`) | 실선 테두리, `--text-muted` |
| `estimated` | `추정` | **점선** 테두리 (`.badge--estimated`) |
| `unknown` | `신뢰도 미상` | 점선 테두리 |

> 점선/실선으로도 구분하는 이유: 색과 무관하게 형태로 읽히게. 흑백 인쇄·저조도에서도 살아남는다.

### 3.3 `<ConfidenceDots>` — 동(棟) 추정 신뢰도

```ts
interface ConfidenceDotsProps { value: number }   // 0.0 ~ 1.0
```
- `●●○○○` 5단계. `Math.round(value * 5)`
- `aria-label="신뢰도 5단계 중 2단계"` — 점 문자는 `aria-hidden`
- **0.5 미만이면 반드시 `추정` 배지를 함께** 붙인다. 점만 보고는 낮은 줄 모른다.

### 3.4 `<Disclaimer>`

```ts
interface DisclaimerProps { variant: "trade-delay" | "not-advice" | "both" }
```
- 문구는 **하드코딩 상수**로 한 곳에서 관리(`lib/notices.ts`). 화면마다 다르게 쓰면 고지가 아니라 장식이 된다.
- 최소 14px. `--text-estimated` (수정 후 값) 이상 대비.
- **접히거나 잘리는 위치에 두지 않는다.** 리포트에서는 하단 고정, 지도에서는 시트 헤더의 ⓘ 버튼.

### 3.5 `<MoneyField>` — 금액 입력 (G3 대상)

```ts
interface MoneyFieldProps {
  label: string; valueKrw: number | null;
  onChange: (krw: number | null) => void;
  unit?: "만원" | "원";     // 기본 "만원"
  hint?: string; error?: string;
}
```

| 규칙 | 내용 |
|---|---|
| 입력 | `inputMode="numeric"`, 3자리 콤마 자동. **커서 위치 보존**(콤마 삽입 후 캐럿 튐 금지) |
| 변환 | 화면=만원 / 전송=**원 단위 정수**(`api-spec` §0). 변환은 `lib/money.ts` 순수 함수로 |
| 정렬 | `text-align: right` + 등폭 |
| ⛔ 금지 | `console.log`·에러 리포팅·`localStorage`/`sessionStorage`에 값 기록 **금지**. 폼 상태는 메모리만 |
| 접근성 | `<label for>` 필수. 오류는 `aria-describedby` + `role="alert"` |
| 신뢰 | 이 필드가 처음 등장하는 화면에는 `<TrustNote>` 를 **반드시** 동반 |

### 3.6 `<TrustNote>`

민감 정보를 요구하는 화면 전용. **왜 필요한지 + 어떻게 보관하는지** 두 문장 고정.

> 대출 한도와 세금을 정확히 계산하기 위해 필요합니다.
> 암호화해 저장하며 외부 AI에는 금액이 전송되지 않습니다.

- 문구는 `security.md` 와 **실제 구현이 일치할 때만** 쓴다. 사실이 아니면 그냥 거짓말이다.
- 위치: 입력 필드 **위**. 아래에 두면 이미 입력을 포기한 뒤다.

### 3.7 `<Section>` — 접기 (details 래퍼)

```ts
interface SectionProps {
  icon?: string; title: string;
  count?: number;                 // 배지로 표시. 0이면 "없음" 텍스트
  tone?: "neutral" | "warn";
  defaultOpen?: boolean;
  children: React.ReactNode;
}
```
- **네이티브 `<details>/<summary>` 로 구현한다.** 키보드·스크린리더·`Ctrl+F` 검색이 전부 따라온다.
- `summary` 최소 높이 **44px**, 줄 전체가 터치 타깃.
- `count === 0` 이어도 **섹션을 감추지 않는다** → `확인할 점 없음` 을 표시.
- RN 이식 시 `<details>` 가 없으므로 **이 컴포넌트만 갈아끼우면 되게** 경계를 여기서 끊는다.

---

## 4. 기존 컴포넌트 — 현행 + 변경 요구

### 4.1 `<BottomSheet>` (구현됨)

**현행 props** — 유지
```ts
{ snap: "peek"|"half"|"full"; onSnapChange: (s)=>void; title: string; children: ReactNode }
```

| 항목 | 현행 | 변경 요구 |
|---|---|---|
| 스냅 비율 | peek .25 / half .55 / full .92 | 유지 (README §3 일치) |
| 드래그 | pointer 이벤트 + 최근접 스냅 | 유지 |
| 키보드 | ↑/↓ 로 단계 이동 | **Home/End 추가**(최소/최대로 점프) |
| 제목 | `<h2>` 가 `role="slider"` **안에** 있음 | ⚠️ **F-04: 밖으로 뺀다.** slider는 자식이 접근성 트리에서 무시되는 role이라 **제목이 스크린리더에 안 읽힌다** |
| 랜드마크 이름 | `aria-label={title}` (건수라 계속 바뀜) | ⚠️ **F-06: `aria-label="매물 목록"` 고정**, 건수는 내부 heading으로 |
| 방향 | 미지정 | `aria-orientation="vertical"` 추가 (slider 기본값은 horizontal) |
| 데스크톱(≥900px) | 우측 고정 패널인데 slider role·tabIndex가 남음 | ⚠️ **F-08: `matchMedia`로 데스크톱에서는 slider 속성 제거.** 조절되지 않는데 포커스만 잡히면 혼란 |
| safe-area | `env(safe-area-inset-bottom)` 적용 | ✅ 유지 (좋음) |
| 스크롤 | `overscroll-behavior: contain` | ✅ 유지 (좋음) |

**추가 요구 — 지도 대체 경로**
시트 최상단에 `건너뛰기` 앵커(`<a href="#sheet-list">지도 건너뛰고 목록으로</a>`)를 둔다.
지도는 스크린리더로 읽히지 않으므로 **목록이 유일한 대체 경로**다(README §11).

### 4.2 `<MapView>` (구현됨 — 마커 미구현)

**현행 props**
```ts
{ onBoundsChange: (bbox: string, zoom: number) => void }
```

**변경 요구 props** — 마커를 그리려면 데이터가 필요하다
```ts
{
  onBoundsChange: (bbox: string, zoom: number) => void;
  items?: ComplexItem[];           // zoom>=13
  clusters?: ClusterItem[];        // zoom<13
  selectedId?: number | null;      // 리스트 카드 ↔ 마커 양방향 동기화
  onSelect?: (id: number) => void;
  rankById?: Record<number, number>;   // 추천 순위 배지 ①②③
}
```

| 항목 | 현행 | 변경 요구 |
|---|---|---|
| 키 없음 처리 | 에러 화면 + "목록으로 확인 가능" 안내 | ✅ 유지 (매우 좋음) |
| role | `role="application"` | ⚠️ **F-03: `role="region"` 으로.** `application` 은 스크린리더 브라우즈 모드를 꺼서, 키보드 조작이 안 되는 현재 구현에서는 **사용자를 가둔다** |
| 마커 | 없음 | 줌별 3단계(군집/단지/단지+동, README §4). 마커 라벨은 `<Price short>` 규칙을 따른다 |
| 예산 초과 | — | **지우지 않고 회색**(README §4) |
| 대체 경로 | 시트 리스트가 사실상 담당 | `aria-describedby` 로 "지도 내용은 아래 목록에서 확인할 수 있습니다" 명시 |
| 줌 변환 | `zoom = 20 - level` | ✅ 유지. 단 API `zoom` 규약과 경계값 13은 실데이터로 튜닝(api-spec §9 A4) |

### 4.3 `<ComplexCard>` (구현됨)

**현행 props** — 유지
```ts
{ item: ComplexItem; selected?: boolean; onSelect?: (id:number)=>void }
```

| 항목 | 현행 | 변경 요구 |
|---|---|---|
| 가격 표기 | 카드가 직접 `~`·배지를 조립 | ⚠️ **`<Price>` 컴포넌트로 교체**(§3.1). 표기 로직이 화면마다 흩어지면 반드시 갈라진다 |
| `unknown` 처리 | 값이 있어도 `데이터 없음` 배지 | ⚠️ **F-05: `신뢰도 미상` 으로.** 값과 배지가 모순되면 안 된다 |
| 예산 초과 | `.card--over { opacity:.55 }` | ⚠️ **F-03(대비): opacity 금지.** 텍스트 대비가 3.96:1로 떨어진다. 점선 테두리 + 배지로 |
| 초과 배지 | `--warn` 텍스트 (2.25:1) | ⚠️ **F-02: `--warn-text: #b54708`** (5.19:1) |
| 기준일 | `.card__asof` = `--text-estimated` (2.58:1) | ⚠️ **F-01: 토큰 값 수정** |
| 탭 영역 | 카드 전체가 `<button>` | ✅ 유지. `aria-pressed` 도 적절 |
| 다음 단계 | `onSelect` 가 선택 상태만 바꿈 | 단지 상세로 가는 경로 필요(현재 **막다른 길**) |

---

## 5. 신규 컴포넌트 — 화면별

와이어프레임: `wireframes/login.html` · `onboarding.html` · `report-detail.html`

### 5.1 로그인 `<LoginForm>` / `<SignupForm>`

```ts
interface LoginFormProps { onSuccess: () => void }
```

| 항목 | 요건 |
|---|---|
| 레이아웃 | 입력은 위, **제출 버튼은 하단 고정**(엄지 범위). `100dvh` 기반 플렉스 — iOS 키보드가 `position:fixed`를 밀어올린다 |
| autocomplete | `username` / `current-password` / (가입) `new-password`. 없으면 사용자가 짧은 비밀번호를 쓴다 |
| 오류 문구 | **"이메일 또는 비밀번호가 올바르지 않습니다"** 로 합친다 — 어느 쪽이 틀렸는지 알리면 계정 존재가 새어나간다 |
| 오류 위치 | 필드 아래 + `role="alert"` |
| 비밀번호 표시 | 44×44 토글, `aria-pressed` |
| 가입 규칙 | 입력 **전부터** 규칙 노출, 충족 여부를 **텍스트 배지**로(색만 금지) |
| 신뢰 | `<TrustNote>` 축약본을 로그인 화면에도. 자산 입력 때 처음 보면 늦다 |
| 성공 후 | 가입 → 자동 로그인 → **온보딩 1단계 직행** |

### 5.2 온보딩 1 `<OnboardingRegionBudget>`

```ts
interface Props {
  onDone: (v: { regionCodes: string[]; budgetMinKrw: number; budgetMaxKrw: number }) => void;
  onSkip: () => void;        // ⛔ 제거 금지 — 강제 입력은 다크패턴
}
```
- 예산은 **범위(min~max)**. 상한만 받으면 저가 매물이 섞인다.
- 슬라이더 + **숫자 직접 입력 대안**을 함께. 슬라이더만으로는 정밀 조작이 안 된다.
- 지역 칩은 `<button aria-pressed>`.
- 이 단계 값만으로 `GET /map/complexes?max_price_krw=` 가 동작해야 한다.

### 5.3 온보딩 2 `<AffordabilityPrompt>` (G3 대상)

```ts
interface Props {
  onSubmit: (p: { incomeKrw: number; existingLoanKrw: number; ownedHouses: number }) => void;
  onLater: () => void;
  submitting?: boolean;
}
```
- 모바일=시트 / 데스크톱=모달. **지도를 배경에 유지**해 맥락을 끊지 않는다.
- `<TrustNote>` 를 필드 **위**에 필수 배치.
- `<MoneyField>` 사용. **`autocomplete="off"`** (공용 기기 대비).
- `[나중에]` 는 고스트 버튼으로 **명확히 보이게**. 숨기면 다크패턴, 같은 비중이면 안내 실패 — 그 사이가 정답.
- 결과 표시 `<AffordabilityResult>`:
  - `max_purchase_krw` 를 `<Price confidence="confirmed">` 로 (규칙 계산이라 추정 아님)
  - **`binding_constraint` 를 반드시 문장으로**: "한도를 결정한 건 **DSR**입니다"
  - `assumptions[]`/`evidence[]` 를 **출처+기준일과 함께** 나열. 출처 없는 항목은 렌더링하지 않는다(CHARTER §5-2)
  - `disclaimer` 는 응답 값을 그대로 출력

### 5.4 온보딩 3 `<PreferenceEditor>`

```ts
interface Props {
  value: Preferences;                 // prefer / avoid / weights
  excludedReason?: { complexName: string; reasons: string[] };   // "왜 빠졌죠?" 진입 시
  onSave: (v: Preferences) => void;
}
```
- **제외 사유를 먼저 보여주고 그 자리에서 조건을 푼다.** 추상적으로 물으면 사용자는 못 답한다.
- 가중치 합계는 **자동 정규화**. 100 맞추기를 시키면 아무도 안 만진다.
- `<input type="range">` 유지 — 커스텀 슬라이더는 키보드 조작을 잃는다.
- ⚠️ **재추천은 명시적 버튼으로만.** 슬라이더 조작마다 Claude API가 도는 건 비용 사고(architecture.md §6).
- 변동 예고 배지는 **규칙으로 계산 가능한 것만**(예산·기피 필터). 점수 변동은 예고하지 않는다.

### 5.5 `<AnalysisProgress>`

```ts
interface Props {
  jobId: string;
  progress: { done: number; total: number; currentAgent: string | null };
  partialItems: RecommendationItem[];      // 먼저 도착한 결과
}
```
- SSE 우선 + **폴링 폴백 필수**(모바일 백그라운드에서 SSE는 끊긴다).
- 진행 텍스트에 `role="status" aria-live="polite"`, 진행 바는 `aria-hidden`(중복 낭독 방지).
- 단계 이름은 **사용자 언어**로: `valuation-trader` → "시세 분석". 매핑 테이블은 `lib/agentLabels.ts`.
- 완료 단계에 **산출값을 즉시 붙인다**("자금 한도 8.5억") — 체감 대기가 크게 줄어든다.
- 빈 스피너 금지.

### 5.6 `<ReportCard>` — 리포트 상세 (G2 대상)

```ts
interface Props {
  item: RecommendationItem;       // api-spec §5 응답 항목
  criteriaSnapshot: unknown;      // 재현성
}
```

**렌더 순서 — 이 순서를 바꾸지 않는다**
1. 순위 배지 + 단지·타입 + 총점
2. `<Price>` (추정 표기) + 호가/실거래 중위 + 기준일
3. 동·층 + `<ConfidenceDots>` + `동 추정` 배지
4. `summary` (headline 한 줄)
5. `<Section icon="✅" title="좋은 점" defaultOpen>` — `findings[]`
6. `<Section icon="⚠️" title="확인할 점" tone="warn">` — `risks[]` **(접힘 + 개수 배지)**
7. `<Section icon="📋" title="다음에 할 일">`
8. `<Section icon="🧾" title="이 판단의 조건">` — `criteria_snapshot`
9. `<Disclaimer variant="both">`
10. 하단 액션 `[지도에서 보기] [단지 상세]` (엄지 범위)

**절대 규칙**
- `risks` 가 0건이어도 **섹션을 감추지 않는다** → `확인할 점 없음`.
- 모바일은 리스크 접힘 / **데스크톱은 펼침**. 자리가 있는데 접는 건 숨기는 것에 가깝다.
- 순위 ①은 "최고의 매물"이 아니라 **"입력한 조건에서의 1순위"** — 조건 스냅샷을 항상 열람 가능하게.
- ⛔ 긴급성 문구·카운트다운·"오늘의 추천" 배너 금지.

### 5.7 `<EvidenceItem>` / `<RiskItem>`

```ts
interface EvidenceItemProps {
  agentId: string; verdict?: string; rationale: string;
  evidence?: { claim?: string; source?: string; as_of?: string; data_rows?: number; period?: string };
  confidence?: number;
  tone?: "good" | "risk";
}
```
- **한 줄 주장 + 한 줄 출처** 구조. 출처 줄에는 `source` · `as_of` · 에이전트 라벨 · 신뢰도.
- ⚠️ **`source`(또는 `data_rows`)가 없으면 그 항목을 렌더링하지 않는다.** 출처 없는 근거는 근거가 아니다(CHARTER §5-2, G2).
- 에이전트 라벨은 한국어로(`lib/agentLabels.ts`), `agent_id` 원문은 `title` 속성에.
- `tone="risk"` 는 왼쪽 보더 `--warn` + `<RiskItem>` 이 `severity` 를 텍스트로 병기(`심각도 중`) — 색만으로 전달 금지.

---

## 6. 접근성 공통 요건 (하향 금지)

| # | 요건 | 검증 방법 |
|---|---|---|
| A1 | 터치 타깃 ≥ 44×44px | DevTools에서 실제 렌더 박스 측정 |
| A2 | 본문 대비 ≥ 4.5:1, **라이트·다크 양쪽** | 토큰 조합별 계산 (audit-frontend.md §3에 계산값) |
| A3 | 색만으로 정보 전달 금지 | 부호(`+/-`)·텍스트 배지·점선 병기 |
| A4 | 지도 정보에 **리스트 대체 경로** | 스크린리더로 지도 화면 순회 |
| A5 | 포커스 순서 = 시각 순서, 포커스 링 보임 | Tab 순회 |
| A6 | `prefers-reduced-motion` 존중 | ✅ 전역 적용됨 |
| A7 | 동적 콘텐츠 변경 시 `aria-live` | 지도 이동 후 목록 갱신 알림 |
| A8 | 문서에 `<h1>` 1개 + 논리적 heading 계층 | 현재 App에 `<h1>` 없음 — F-09 |
| A9 | 확대 허용(`maximum-scale` 금지) | ✅ `index.html` 준수 중 |
| A10 | 폼 오류는 `role="alert"` + `aria-describedby` | |

---

## 7. 상태·데이터 흐름

```
App
├── useAuth()          ← 토큰. 401 → 로그인 화면 (api/client.ts 가 refresh 처리)
├── useProfile()       ← /me/profile, /me/preferences   ⚠️ 값 로깅 금지
├── useAffordability() ← POST /affordability (동기·규칙 계산)
├── useMapArea()       ← /map/complexes  (350ms 디바운스 — 현행 유지)
└── useRecommendation()← POST → SSE 구독 → 폴링 폴백
```

- **금액 계산은 서버가 한다.** 프론트는 표시만 — 세금·한도를 클라이언트에서 다시 계산하면 두 개의 진실이 생긴다.
- 추천 결과는 `job_id` 로 캐시. 같은 조건 재요청은 서버 캐시에 맡긴다(비용).

---

## 8. 미확정 — 결정 필요 (PM 경유)

| # | 쟁점 | 필요한 결정자 |
|---|---|---|
| U1 | `price_confidence` 에 `confirmed` 포함 여부 (§2.3) | `re-arch` / `re-be` |
| U2 | 리프레시 토큰 저장 위치 — httpOnly 쿠키 vs 메모리 (현재 메모리, 새로고침 시 로그아웃) | `re-arch` (api-spec §9 A3) |
| U3 | 단지 상세 화면 — 현재 `onSelect` 가 막다른 길. 3단계 범위에 포함할지 | `re-pm` |
| U4 | 군집 경계 줌 13 — 실데이터 튜닝 필요 | `re-data` 수집 후 |
| U5 | 다크모드 토글 제공 여부 (현재 OS 설정만 따름) | `re-pm` |

---

*작성 2026-07-25 · re-ux · 지시서 2026-07-25-07-ux*
