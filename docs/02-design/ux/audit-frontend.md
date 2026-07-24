# 기존 프론트 UX 감사 — BottomSheet · MapView · ComplexCard

> 지시서 `team/orders/2026-07-25-07-ux.md` 산출물 · 2026-07-25 · re-ux
> 대상: `frontend/src/**` (3단계에서 컴포넌트 명세 없이 선구현된 코드)
> 기준: `ux/README.md` §1 §4 §6 §7 §11 §12 · CHARTER §5 · WCAG 2.1 AA
> ⚠️ **코드는 수정하지 않았다.** 수정은 `re-fe` 몫이며, 이 문서는 무엇을 어떻게 고칠지의 명세다.

---

## 0. 요약

| 구분 | 건수 |
|---|---|
| 🔴 높음 (게이트 위협 · AA 위반) | **4** |
| 🟡 중간 (사용성·접근성 손실) | **6** |
| 🟢 낮음 (개선 권고) | **7** |
| ✅ PASS (잘 되어 있어 유지) | **17** |

**한 줄 결론**: 설계 원칙(추정치 표기·예산 초과 노출·다크패턴 회피)은 **성실히 지켜졌다.**
문제는 원칙이 아니라 **구현 수단**이다 — 불확실성과 고지를 **"흐린 회색"으로 표현**했는데,
그 회색이 라이트 모드에서 WCAG AA에 미달한다. 즉 **"모르는 걸 모른다고 보여준다"는 이 제품의 정체성이,
정작 그 문구가 안 읽히는 방식으로 구현돼 있다.** 이게 이 감사의 핵심이다.

> 감사 항목별 판정은 §1(불확실성) §2(다크패턴) §3(대비) §4(터치) §5(지도 대체경로) 순으로,
> 발견 사항 전체 목록은 §6에 F-번호로 정리했다.

---

## 1. 추정치 / 데이터없음 표기 — **부분 PASS**

### ✅ 잘 된 것
| 항목 | 근거 |
|---|---|
| 추정치를 3중으로 구분 | `~` 접두 + `.estimated` 회색 + `추정` **점선** 배지 (`ComplexCard.tsx:39-44`) — 색 하나에 기대지 않은 건 정확한 판단 |
| `~` 를 `aria-hidden` 처리 | 스크린리더는 배지 텍스트로 읽는다. 기호 낭독("물결표")을 피한 건 잘한 것 |
| 값이 `null` 일 때 `데이터 없음` 을 명시 (0원 아님) | `ComplexCard.tsx:35-36` |
| 기준일 결측 처리 | `formatAsOf(null)` → `"기준일 미상"` (`format.ts:56`) — 빈칸으로 두지 않았다 |
| 실거래 지연 고지 존재 | `App.tsx:124` `app__note` |
| 등폭 숫자 | `.num { tabular-nums }` — 세로 비교가 실제로 된다 |

### 🔴 문제

**F-01 · 추정치·고지 텍스트가 AA 미달 (높음)** — 아래 §3에서 상세.

**F-05 · `unknown` 인데 값이 있으면 모순된 표기 (중간)**
`ComplexCard.tsx:34-45` 는 가격이 있으면 `confidenceLabel(price_confidence)` 배지를 붙인다.
`price_confidence === "unknown"` 이면 라벨이 `"데이터 없음"`(`format.ts:71`)이므로 —

```
14억 [데이터 없음]      ← 값은 있는데 배지는 없다고 한다
```

- **수정안**: `confidenceLabel("unknown")` → **`"신뢰도 미상"`**.
  `데이터 없음`은 `krw === null` 인 경우에만 쓴다(`components.md` §2.2-1).

**F-15 · 마커/짧은 표기에서 반올림이 확정처럼 보임 (낮음)**
`formatKrwShort(1_475_000_000)` → `"14.8억"`. 소수점 반올림 자체는 맞지만,
지도 마커에 이 값만 뜨면 **추정치인지 실거래인지 구분이 사라진다.**
- **수정안**: 마커·짧은 표기도 `<Price short confidence=…>` 를 거치게 하고,
  `estimated` 면 `~14.8억` 로 접두를 유지한다.
- 덧붙여 `formatKrw(null)` · `formatKrwShort(null)` 은 **`"—"`** 를 반환한다(`format.ts:10,31`).
  카드는 null을 따로 잡아 `데이터 없음` 을 쓰지만(잘한 것), 이 함수를 다른 화면에서 그냥 쓰면
  **`—` 가 새어 나간다.** `<Price>` 로 창구를 하나로 묶을 때 이 분기도 함께 흡수할 것.

**F-12 · 실거래 지연 고지가 조건부·하단 노출 (중간)**
`App.tsx:124` 의 `app__note` 는 **`level === "complex"` 이고 서버가 `note` 를 보냈을 때만** 나온다.
그런데 클러스터 화면(`App.tsx:100-102`)도 **중위가를 표시한다** — 시세가 나오는데 고지는 없다.
README §7은 "시세가 나오는 **모든** 화면에 상시"다.
- **수정안**: 고지 문구를 서버 응답에 의존하지 말고 **클라이언트 상수**(`lib/notices.ts`)로 두고,
  가격이 하나라도 렌더되는 화면이면 항상 출력. 위치는 목록 하단이 아니라 **시트 헤더의 ⓘ 버튼 + 목록 하단** 양쪽.

---

## 2. 다크패턴 — ✅ PASS (구조적 개선 1건)

| 점검 항목 | 판정 | 근거 |
|---|---|---|
| 긴급성 문구(`지금 아니면 놓칩니다`) | ✅ 없음 | 전체 코드에서 확인 |
| 리스크를 읽기 어렵게 배치 | ✅ 해당 없음 | 리포트 화면 자체가 미구현 |
| 예산 초과 매물을 몰래 제거 | ✅ **원칙 준수** | `card--over` 로 남겨둠 (`ComplexCard.css:11-12`) — README §4 그대로 |
| 조건 입력 강제 | ✅ 해당 없음 | 온보딩 미구현 |
| 면책 고지 존재 | ⚠️ 존재하나 사실상 잘 안 보임 → **F-13** |

**F-13 · 면책 고지가 사실상 안 보이는 위치 (중간)**
`App.tsx:128-130` 의 면책은 **시트 본문 맨 아래**에 있다. 기본 스냅은 `peek`(높이 25%)이므로,
사용자가 시트를 `full` 로 올리고 목록 끝까지 스크롤해야 보인다. 게다가 색이 `--text-estimated`(F-01).
README §12는 "면책 고지를 사실상 안 보이게 처리" 금지다. **의도는 없지만 결과는 그렇게 됐다.**
- **수정안**: 목록 하단 고지는 유지하되, **시트 헤더 우측에 ⓘ 버튼**(44px)을 두고 탭하면 고지 전문을 시트로.
  리포트 화면에서는 하단 고정(와이어프레임 `report-detail.html` 참고).

---

## 3. 대비 (WCAG AA) — 🔴 **FAIL 3건**

직접 계산했다(sRGB 상대휘도 → 대비비). **라이트 모드에서만 실패**하고 다크는 전부 통과한다.

### 3.1 라이트 모드

| 전경 | 배경 | 대비 | 기준 4.5:1 | 사용처 |
|---|---|---|---|---|
| `--text` `#101828` | `#ffffff` | **17.7:1** | ✅ | 본문 |
| `--text-muted` `#667085` | `#ffffff` | **4.97:1** | ✅ | 캡션 |
| `--text-muted` `#667085` | `--bg-elev` `#f9fafb` | **4.76:1** | ✅ | 카드 내 캡션·배지 |
| `--text-estimated` `#98a2b3` | `#ffffff` | **2.58:1** | 🔴 **FAIL** | 추정 가격·기준일·**실거래 지연 고지**·**면책 고지** |
| `--text-estimated` `#98a2b3` | `#f9fafb` | **2.46:1** | 🔴 **FAIL** | 카드 내 기준일 |
| `--warn` `#f79009` | `#f9fafb` | **2.25:1** | 🔴 **FAIL** | `예산 초과` 배지 텍스트 |
| `--danger` `#d92d20` | `#ffffff` | 4.83:1 | ✅ | 오류 메시지 |
| `--accent` `#175cd3` | `#ffffff` | 5.99:1 | ✅ | 링크·포커스 링 |
| `--price-down` `#1570ef` | `#ffffff` | 4.57:1 | ✅ (여유 없음) | 하락 표기 |

### 3.2 다크 모드 — ✅ 전부 통과

| 전경 | 배경 | 대비 |
|---|---|---|
| `--text-estimated` `#85888e` | `--bg` `#0c111d` | **5.26:1** ✅ |
| `--text-muted` `#94969c` | `--bg` `#0c111d` | **6.32:1** ✅ |
| `--warn` `#f79009` | `--bg-elev` `#161b26` | **7.34:1** ✅ |

> 다크가 통과하고 라이트가 떨어지는 건 흔한 패턴이다. **다크에서만 확인하고 넘어갔을 가능성이 높다.**

### 3.3 🔴 F-01 · `--text-estimated` (높음)

`tokens.css:16`. 적용 대상이 하필 **이 제품에서 가장 안 놓쳐야 할 텍스트들**이다 —
추정 가격(`.estimated`), 기준일(`.card__asof`), 실거래 지연 고지(`.app__note`), 면책 고지(`.app__disclaimer`).

```css
/* 수정안 — tokens.css:16 */
--text-estimated: #667085;   /* 2.58:1 → 4.97:1 (흰 배경), 4.76:1 (elev) */
/* 다크 모드 값 #85888e 는 5.26:1 로 통과 — 그대로 둔다 */
```

**"그러면 `--text-muted` 와 같아져서 추정치 구분이 사라지지 않나?"** — 아니다.
구분해야 할 상대는 캡션이 아니라 **확정 가격(`--text` #101828, 17.7:1)** 이다.
`#667085` 는 여전히 확연히 흐리다. 그리고 애초에 추정치 구분은 **색 하나가 아니라 `~` + 점선 배지 + 색의 3중**이므로(§1),
색의 대비를 올려도 구분은 유지된다. **명도차로만 정보를 전달하는 설계가 아니었던 게 여기서 도움이 된다.**

### 3.4 🔴 F-02 · `예산 초과` 배지 텍스트 (중간)

`ComplexCard.css:37` — `--warn`(#f79009)은 **면·테두리용 색이지 텍스트용이 아니다**(밝은 주황).

```css
/* 수정안 — tokens.css 에 텍스트 전용 warn 신설 */
--warn:      #f79009;   /* 테두리·아이콘용 (유지) */
--warn-text: #b54708;   /* 텍스트용 — #f9fafb 위 5.19:1 */
@media (prefers-color-scheme: dark) { --warn-text: #fdb022; }

/* ComplexCard.css:37 */
.card__over-badge { border-color: var(--warn); color: var(--warn-text); }
```

### 3.5 🔴 F-03 · `opacity: .55` 가 대비를 통째로 깎는다 (높음)

`ComplexCard.css:12`
```css
.card--over { opacity: .55; }   /* 예산 초과 카드를 흐리게 */
```
**의도는 옳다**(지우지 않고 남긴다 — README §4). 그러나 `opacity` 는 **자식 전체의 대비를 곱셈으로 깎는다.**

| 카드 내 텍스트 | 원래 대비 | opacity .55 적용 후 |
|---|---|---|
| 단지명 `--text` | 17.7:1 | **3.96:1** 🔴 |
| 기준일 `--text-estimated` | 2.46:1 | **1.58:1** 🔴🔴 |

즉 **"왜 이 매물이 후보에서 빠졌는지"를 보여주려고 남긴 카드가, 정작 읽을 수 없는 상태**가 된다.

```css
/* 수정안 — ComplexCard.css:11-12 : opacity 를 쓰지 않고 "다름"을 표현한다 */
.card--over {
  background: var(--bg);          /* 일반 카드(bg-elev)와 톤을 다르게 */
  border-style: dashed;           /* 형태로 구분 — 색·투명도에 기대지 않는다 */
}
.card--over .card__price { text-decoration: none; }  /* 취소선 금지: 가격은 여전히 사실이다 */
```
`예산 초과` 배지(F-02 수정 적용)가 이미 상태를 텍스트로 알려주므로, 시각 처리는 약하게만 있으면 된다.

### 3.6 🟢 F-07 · 캡션 13px (낮음)

`tokens.css:29` `--fs-caption: 13px`. 본문 16px 기준(README §1)은 지켜졌지만,
**면책·지연 고지처럼 반드시 읽혀야 하는 문구가 13px + 저대비**로 이중으로 약해져 있다.
- **수정안**: `--fs-caption: 14px`. 고지문에는 최소 14px 적용.

---

## 4. 터치 타깃 44px — ✅ PASS

| 항목 | 판정 | 근거 |
|---|---|---|
| 전역 `button` | ✅ | `tokens.css:74-83` `min-height/min-width: 44px` — **전역에서 보장한 건 좋은 결정** |
| 카드 전체 탭 | ✅ | `.card__main` 이 `<button>`, 패딩 포함 44px 초과 |
| 시트 손잡이 | ✅ | `.sheet__handle { min-height: 48px }` + `touch-action: none` |
| 포커스 링 | ✅ | `:focus-visible` 2px outline + offset |
| 지도 위 컨트롤 | — | 아직 없음. 구현 시 44px + **하단 배치**(엄지 범위) |

**🟢 F-16 (낮음)**: 시트 손잡이는 ↑/↓만 지원(`BottomSheet.tsx:75-87`).
`role="slider"` 관례상 **Home/End(최소/최대)** 도 지원해야 하고, `aria-orientation="vertical"` 이 없다
(slider 기본값은 horizontal이라 스크린리더가 좌우로 안내한다).

---

## 5. 지도의 리스트 대체 경로 — 🟡 부분 PASS

### ✅ 잘 된 것
- **SDK 키가 없을 때 빈 화면 대신 설명 + "지도 없이도 아래 목록으로 확인할 수 있습니다"** (`MapView.tsx:82-92`).
  이건 접근성과 디버깅을 동시에 잡은 좋은 처리다.
- 시트 목록이 사실상 대체 경로 역할을 한다.

### 🔴 F-10 · `role="application"` 이 오히려 해롭다 (중간)

`MapView.tsx:94`
```tsx
<div ref={ref} className="map" role="application" aria-label="지도" />
```
`role="application"` 은 스크린리더의 **브라우즈 모드를 끄고 모든 키 입력을 앱에 넘긴다.**
이건 **자체 키보드 조작을 완전히 구현한 위젯에만** 정당하다.
현재 지도는 키보드 조작이 없으므로, 사용자는 **아무것도 못 하는 영역에 갇힌다.**

```tsx
/* 수정안 */
<div ref={ref} className="map" role="region" aria-label="지도"
     aria-describedby="map-alt-hint" />
<p id="map-alt-hint" className="sr-only">
  지도는 시각 정보입니다. 같은 내용을 아래 목록에서 확인할 수 있습니다.
</p>
```
(`.sr-only` 유틸리티 클래스가 아직 없으므로 `tokens.css` 에 추가 필요)

### 🟡 F-11 · 대체 경로가 "동등"하지 않다 (중간)

| 지도에서 가능한 것 | 목록에서 가능한가 |
|---|---|
| 단지 선택 | ✅ (`ComplexCard`) |
| **군집(구/시) 선택 → 확대** | 🔴 **불가.** `App.tsx:96-105` 의 클러스터는 `<li>` 정적 표시라 **누를 수 없다** |
| 지역 이름 확인 | 🔴 `region_code`(`1168000000`) 원문 그대로 노출 — 사람이 읽을 수 없다 |
| 마커 ↔ 카드 동기화 | 🔴 마커 자체가 미구현. `MapView` 는 `items` 를 받지도 않는다 |

- **수정안 3가지**
  1. 클러스터 항목을 `<button>` 으로 → 누르면 해당 중심으로 지도 이동·확대. 지도 없이도 탐색이 이어진다.
  2. `region_code` → **지역명**으로 표시(서버가 `name` 을 이미 준다 — `api-spec` §4 클러스터 응답).
     `App.tsx:98` 이 `c.region_code` 를 쓰고 있는데 `client.ts:35-39` `ClusterItem` 에 `name` 이 없다 →
     **타입 누락. `re-arch`/`re-be` 확인 필요.**
  3. 시트 최상단에 스킵 링크 `지도 건너뛰고 목록으로`.

### 🟢 F-14 · 목록 갱신이 조용히 일어난다 (낮음)

지도를 움직이면 목록이 통째로 바뀌는데(`App.tsx:66-72`) 알림이 없다.
`불러오는 중…`(`App.tsx:90`)에도 `aria-live` 가 없어 스크린리더 사용자는 변화를 모른다.
- **수정안**: 상태 문단에 `role="status" aria-live="polite"`, 갱신 완료 시 `"매물 34건"` 을 읽히게.

---

## 6. 발견 사항 전체 — 수정 요구 목록

| # | 심각도 | 위치 | 내용 | 수정안 |
|---|---|---|---|---|
| **F-01** | 🔴 높음 | `tokens.css:16` | `--text-estimated` 라이트 2.58:1 — 추정치·**면책/지연 고지**가 AA 미달 | `#98a2b3` → `#667085` (§3.3) |
| **F-02** | 🔴 높음 | `ComplexCard.css:37` | `예산 초과` 배지 텍스트 2.25:1 | `--warn-text: #b54708` 신설 (§3.4) |
| **F-03** | 🔴 높음 | `ComplexCard.css:12` | `opacity:.55` 로 카드 전체 대비 3.96:1 / 1.58:1 붕괴 | opacity 제거, 점선 테두리+배경 (§3.5) |
| **F-04** | 🔴 높음 | `BottomSheet.tsx:103-120` | `<h2>` 가 `role="slider"` 자식 → **접근성 트리에서 제거**(ARIA Presentational Children) → 목록 제목이 안 읽힘 | 제목을 slider 밖 형제로 (§7) |
| **F-05** | 🟡 중간 | `format.ts:71`, `ComplexCard.tsx:41` | `unknown` + 값 존재 → `14억 [데이터 없음]` 모순 | 라벨 `신뢰도 미상` (§1) |
| **F-10** | 🟡 중간 | `MapView.tsx:94` | `role="application"` — 키보드 조작 없는데 브라우즈 모드 차단 | `role="region"` + `aria-describedby` (§5) |
| **F-11** | 🟡 중간 | `App.tsx:96-105` | 클러스터가 선택 불가 + `region_code` 원문 노출 → 대체 경로 불완전 | `<button>` 화, 지역명 표시, 스킵 링크 (§5) |
| **F-12** | 🟡 중간 | `App.tsx:124` | 실거래 지연 고지가 서버 `note` 의존·클러스터 화면엔 없음 | 클라이언트 상수화 + 상시 노출 (§1) |
| **F-13** | 🟡 중간 | `App.tsx:128` | 면책 고지가 시트 최하단 → peek 상태에서 사실상 안 보임 | 헤더 ⓘ 버튼 병행 (§2) |
| **F-08** | 🟡 중간 | `BottomSheet.css:52-65` | 데스크톱(≥900px)에서 시트가 고정인데 `role="slider"`·`tabIndex` 잔존 → 조작 안 되는데 포커스만 잡힘 | `matchMedia` 로 데스크톱에선 slider 속성 제거 |
| **F-06** | 🟢 낮음 | `BottomSheet.tsx:101` | `aria-label={title}` 이 `"매물 34건"` → 랜드마크 이름이 계속 바뀜 | `aria-label="매물 목록"` 고정, 건수는 heading으로 |
| **F-07** | 🟢 낮음 | `tokens.css:29` | 캡션 13px — 고지문에 사용 | 14px (§3.6) |
| **F-09** | 🟢 낮음 | `App.tsx:80` | 문서에 `<h1>` 없음 (시트 제목이 `<h2>`) | 화면 제목 `<h1>` 추가(시각적으로 숨겨도 됨) |
| **F-14** | 🟢 낮음 | `App.tsx:90` | 목록 갱신·로딩에 `aria-live` 없음 | `role="status" aria-live="polite"` (§5) |
| **F-15** | 🟢 낮음 | `format.ts:29` | `formatKrwShort` 결과가 확정치처럼 보임 | `<Price short>` 경유, `~` 유지 (§1) |
| **F-16** | 🟢 낮음 | `BottomSheet.tsx:75-87` | Home/End 미지원, `aria-orientation` 없음 | 둘 다 추가 (§4) |
| **F-17** | 🟢 낮음 | `ComplexCard.tsx:26` | `onSelect` 가 선택 상태만 바꿈 — **막다른 길** | 단지 상세 경로 필요(범위 결정은 `re-pm`) |

### 7. F-04 상세 — 시트 제목이 읽히지 않는 이유

```tsx
// BottomSheet.tsx:103-120  (현행)
<div role="slider" tabIndex={0} aria-label="목록 크기 조절" …>
  <div className="sheet__grip" aria-hidden="true" />
  <h2 className="sheet__title">{title}</h2>     {/* ← slider 의 자식 */}
</div>
```

WAI-ARIA 명세에서 `slider` 는 **"Presentational Children"** role이다 —
`button`·`checkbox`·`progressbar` 등과 함께, **자식 요소의 의미가 접근성 트리에서 제거되고
접근 가능한 이름 계산에만 쓰인다.** 따라서 `<h2>매물 34건</h2>` 은:
- 제목(heading)으로 탐색되지 않고
- 여기서는 `aria-label="목록 크기 조절"` 이 이름을 이미 덮으므로 **어디에도 노출되지 않는다.**

결과적으로 스크린리더 사용자는 **"이 목록에 몇 건이 있는지"를 알 방법이 없다.**

```tsx
// 수정안 — 손잡이(slider)와 제목을 형제로 분리
<section className="sheet" aria-labelledby="sheet-title">
  <div className="sheet__handle" role="slider" tabIndex={0}
       aria-label="목록 크기 조절" aria-orientation="vertical"
       aria-valuemin={0} aria-valuemax={2} aria-valuenow={ORDER.indexOf(snap)}
       aria-valuetext={{peek:"작게",half:"중간",full:"크게"}[snap]} …>
    <div className="sheet__grip" aria-hidden="true" />
  </div>
  <h2 id="sheet-title" className="sheet__title">{title}</h2>
  <div className="sheet__body">{children}</div>
</section>
```
> CSS 조정 필요: 손잡이 높이 48px 유지 + 제목이 손잡이 아래로. 터치 영역은 줄이지 말 것.
> **검증 방법**: NVDA/VoiceOver로 시트 진입 시 "매물 34건" 이 낭독되는지 확인.

---

## 8. ✅ PASS — 유지할 것 (건드리지 말 것)

| # | 항목 | 위치 |
|---|---|---|
| P-01 | 확대 허용 — `maximum-scale` 안 씀, `viewport-fit=cover` | `index.html:6` |
| P-02 | `prefers-reduced-motion` 전역 무력화 | `tokens.css:107-109` |
| P-03 | 전역 `button` 44×44px 보장 | `tokens.css:74-83` |
| P-04 | `env(safe-area-inset-bottom)` — iOS 홈 인디케이터 회피 | `BottomSheet.css:14` |
| P-05 | `overscroll-behavior: contain/none` — 시트 스크롤이 지도로 안 샘 | `BottomSheet.css:46`, `tokens.css:71` |
| P-06 | `color-scheme: light dark` + 다크 토큰 완비 | `tokens.css:5,43-55` |
| P-07 | **다크 모드 대비 전부 AA 통과** | §3.2 |
| P-08 | 등폭 + `tabular-nums` 금액 | `tokens.css:91` |
| P-09 | 지도 실패 시 대체 안내 문구 | `MapView.tsx:82-92` |
| P-10 | 예산 초과 매물을 지우지 않고 노출(원칙) | `ComplexCard.css:11` |
| P-11 | 다크패턴 없음 — 긴급성 문구·리스크 은폐 0건 | 전체 |
| P-12 | 오류에 `role="alert"` | `App.tsx:85` |
| P-13 | 지도 이동 350ms 디바운스 | `App.tsx:30-58` |
| P-14 | `formatAsOf(null)` → `기준일 미상` | `format.ts:56` |
| P-15 | `formatPct` 부호 병기 — 색 없이 상승/하락 구분 | `format.ts:49-52` |
| P-16 | `:focus-visible` 포커스 링 | `tokens.css:85-89` |
| P-17 | 지도 이동 시 시트 자동 축소(full→half) | `App.tsx:66-72` |
| P-18 | 결과 0건일 때 다음 행동 안내 | `App.tsx:112-114` |

---

## 9. 권장 처리 순서 (re-fe 전달용)

1. **토큰 3줄** — F-01 · F-02 · F-07. 파일 한 개, 영향 범위 전체. 가장 싸고 효과가 크다.
2. **F-03** `opacity` 제거 — CSS 3줄.
3. **F-04** 시트 제목 분리 — 구조 변경이라 신중히. 스크린리더로 검증.
4. **F-05 · F-10 · F-12 · F-13** — 표기·고지·role 수정.
5. **F-11** 클러스터 상호작용 — `ClusterItem.name` 타입 확인 후(백엔드 협의) 진행.
6. 나머지 🟢 항목.

## 10. 다른 역할에 확인이 필요한 사항

| # | 내용 | 대상 |
|---|---|---|
| Q1 | `ComplexItem.price_confidence` 에 `confirmed` 가 없다 → **프론트에 "실거래 기준(확정)" 표시 경로가 없음** | `re-arch` / `re-be` |
| Q2 | `ClusterItem` 에 지역명(`name`)이 없다 — `api-spec` §4 응답 예시에는 있는데 `client.ts` 타입에는 빠짐 | `re-arch` / `re-be` |
| Q3 | 단지 상세 화면을 3단계 범위에 넣을지(현재 카드 선택이 막다른 길) | `re-pm` |
| Q4 | 리프레시 토큰이 메모리에만 있어 **새로고침하면 로그아웃** — 의도인지 확인 | `re-arch` (api-spec §9 A3) |

---

*작성 2026-07-25 · re-ux · 지시서 2026-07-25-07-ux · 코드 미수정(제안만)*
