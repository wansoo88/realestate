/**
 * "내 조건이 지도에 반영되는가" — 이 제품이 지도 뷰어가 아니라는 증거.
 *
 * 그리고 **그 조건이 어떻게 나가는가**(SR32-1): 예산은 금액이 아니라 플래그로 나간다.
 * 금액(실구매 가능 금액·희망가)은 메모리에만 살고 화면 문구에만 쓰인다.
 */
import { describe, expect, it } from "vitest";
import {
  BUDGET_SCOPE_MINE,
  budgetRequested,
  buildMapQuery,
  displayBudget,
  effectiveBudget,
  effectiveBudgetKrw,
  filterChips,
  mapFilterKey,
  type MapFilterState,
} from "./mapFilters";

const BASE: MapFilterState = {
  budgetKrw: 850_000_000,
  budgetApplied: true,
  prefer: { area_min_m2: 59, area_max_m2: 85, built_after: 2010 },
  preferApplied: true,
  purpose: "live",
};

describe("buildMapQuery", () => {
  it("예산은 **플래그**로, 선호는 값으로 나간다 (금액은 URL 에 없다 — SR32-1)", () => {
    expect(buildMapQuery("126.9,37.5,127.1,37.6", 15, BASE)).toEqual({
      bbox: "126.9,37.5,127.1,37.6",
      zoom: 15,
      // 8.5억이 아니라 "mine". 상한은 서버가 저장된 프로필로 만든다.
      budget: BUDGET_SCOPE_MINE,
      // 한도 산정 가정. 자금계획(/affordability)과 **같은 값**이어야 한다.
      purpose: "live",
      area_min_m2: 59,
      area_max_m2: 85,
      built_after: 2010,
    });
  });

  it("예산 스위치를 끄면 예산이 **빠진다**(끄는 게 실제로 동작해야 한다)", () => {
    const q = buildMapQuery("1,2,3,4", 15, { ...BASE, budgetApplied: false });
    expect(q.budget).toBeUndefined();
    expect(q.area_min_m2).toBe(59); // 다른 필터는 그대로
  });

  it("선호 스위치를 끄면 면적·연식이 빠진다", () => {
    const q = buildMapQuery("1,2,3,4", 15, { ...BASE, preferApplied: false });
    expect(q.budget).toBe(BUDGET_SCOPE_MINE);
    expect(q.area_min_m2).toBeUndefined();
    expect(q.built_after).toBeUndefined();
  });

  it("예산을 모르면(null) 플래그도 안 보낸다 — 칩이 없는데 서버만 조용히 거르면 안 된다", () => {
    const q = buildMapQuery("1,2,3,4", 15, { ...BASE, budgetKrw: null });
    expect(q.budget).toBeUndefined();
  });

  /**
   * `purpose` — **끄는 스위치가 없다.** 예산·선호와 달리 이건 사용자가 켜고 끄는 조건이
   * 아니라 계산의 **가정**이고, 빠지면 서버 기본값(live)이 조용히 쓰인다.
   */
  it("목적은 어떤 상태에서도 빠지지 않는다(기본값에 기대지 않는다)", () => {
    for (const f of [
      BASE,
      { ...BASE, budgetApplied: false },
      { ...BASE, preferApplied: false },
      { ...BASE, budgetKrw: null, targetPriceKrw: null },
    ]) {
      expect(buildMapQuery("1,2,3,4", 15, f).purpose).toBe("live");
    }
  });

  it("투자 목적이면 그대로 실어 보낸다 — 한도가 다른 계산이기 때문", () => {
    expect(buildMapQuery("1,2,3,4", 15, { ...BASE, purpose: "invest" }).purpose).toBe("invest");
  });

  it("목적이 바뀌면 지도를 다시 조회한다(한도가 달라지므로 결과도 달라진다)", () => {
    expect(mapFilterKey({ ...BASE, purpose: "invest" })).not.toBe(mapFilterKey(BASE));
  });
});

/**
 * 실효 예산은 **금액과 근거가 한 쌍**이다. 서버 응답(`budget.basis`)과 대조하려면
 * 화면도 자기 기준을 이름으로 말할 수 있어야 한다(lib/budgetStatus).
 */
describe("effectiveBudget — 금액과 그 금액의 정체", () => {
  it("희망가가 있으면 target_price, 없으면 max_purchase", () => {
    expect(effectiveBudget({ ...BASE, targetPriceKrw: 700_000_000 })).toEqual({
      krw: 700_000_000,
      basis: "target_price",
    });
    expect(effectiveBudget(BASE)).toEqual({ krw: 850_000_000, basis: "max_purchase" });
  });

  it("둘 다 없으면 **기준 자체가 없다**(0 이 아니라 null)", () => {
    expect(effectiveBudget({ ...BASE, budgetKrw: null, targetPriceKrw: 0 })).toEqual({
      krw: null,
      basis: null,
    });
  });

  it("`budgetRequested` 는 buildMapQuery 가 플래그를 싣는 조건과 **같다**", () => {
    // 두 벌로 적으면 한쪽만 바뀌어 "안 켰는데 켰다고 말하는" 화면이 된다.
    for (const f of [
      BASE,
      { ...BASE, budgetApplied: false },
      { ...BASE, budgetKrw: null },
      { ...BASE, budgetKrw: null, targetPriceKrw: 700_000_000 },
    ]) {
      expect(budgetRequested(f)).toBe(buildMapQuery("1,2,3,4", 15, f).budget !== undefined);
    }
  });
});

/**
 * 🔐 SR32-1 — **지도 쿼리에 금액이 없다.**
 *
 * 사고: `max_price_krw=1314310000` 이 URL 로 나갔고 nginx·uvicorn 접근 로그에 평문으로
 * 쌓였다(로테이션 파일이 0644 였다). 그 숫자는 사용자가 친 값이 아니라 **암호화 저장된
 * 자산·소득·대출을 복호화해 계산한 실구매 가능 금액**이었다 — 파생값이라 이름만 봐서는
 * 민감해 보이지 않았고, 그래서 아무도 못 봤다.
 *
 * 아래 검사는 **이름이 아니라 값의 크기**로 판정한다. 다음 사람이 `cap_krw`·`max_won`
 * 어떤 이름으로 다시 넣어도 걸린다.
 */
describe("지도 쿼리에는 금액이 실리지 않는다", () => {
  /** 쿼리에 실릴 수 있는 정상 숫자(좌표·줌·㎡·연도)는 전부 1천만 미만이다. */
  const MONEYISH = 10_000_000;

  const STATES: Array<[string, MapFilterState]> = [
    ["한도만 있는 기본 상태", BASE],
    ["희망가를 정한 상태", { ...BASE, targetPriceKrw: 700_000_000 }],
    ["희망가가 한도를 넘긴 상태", { ...BASE, targetPriceKrw: 1_200_000_000 }],
    ["예산 스위치를 끈 상태", { ...BASE, budgetApplied: false }],
    ["자산 미입력(한도 미상)", { ...BASE, budgetKrw: null }],
  ];

  it.each(STATES)("%s — 금액처럼 보이는 값이 하나도 없다", (_label, state) => {
    const q: object = buildMapQuery("126.9,37.5,127.1,37.6", 15, state);
    for (const [key, value] of Object.entries(q)) {
      const n = Number(value);
      expect(
        Number.isFinite(n) && Math.abs(n) >= MONEYISH,
        `쿼리 파라미터 "${key}" 가 금액으로 보인다 — URL 은 접근 로그에 평문으로 남는다`,
      ).toBe(false);
    }
  });

  it("희망가를 바꿔도 쿼리 글자는 그대로다(= 금액이 안 실렸다는 뜻)", () => {
    const a = buildMapQuery("1,2,3,4", 15, { ...BASE, targetPriceKrw: 700_000_000 });
    const b = buildMapQuery("1,2,3,4", 15, { ...BASE, targetPriceKrw: 1_200_000_000 });
    expect(a).toEqual(b);
  });

  /**
   * 위 성질의 **대가**: 쿼리가 같으니 재조회 트리거도 같아진다. 그래서 조건 변경 감지는
   * 쿼리가 아니라 `mapFilterKey`(비교 전용, URL 로 안 나감)로 한다. 이게 없으면
   * 희망가를 9억 → 7억으로 바꿔도 지도가 옛 결과 그대로 남는다.
   */
  it("그래서 재조회 키는 금액까지 본다 — 희망가를 바꾸면 지도가 다시 조회된다", () => {
    const a = mapFilterKey({ ...BASE, targetPriceKrw: 900_000_000 });
    const b = mapFilterKey({ ...BASE, targetPriceKrw: 700_000_000 });
    expect(a).not.toBe(b);
    // 예산을 끈 상태에서는 금액이 바뀌어도 지도 결과가 같다 → 재조회하지 않는다
    expect(mapFilterKey({ ...BASE, budgetApplied: false, targetPriceKrw: 900_000_000 })).toBe(
      mapFilterKey({ ...BASE, budgetApplied: false, targetPriceKrw: 700_000_000 }),
    );
  });
});

/**
 * 희망 매매가 — 사용자가 정한 상한. 추천(`budget_override_krw`)과 **같은 숫자**를 지도도
 * 써야 "추천에는 뜨는데 지도엔 없는 단지"가 생기지 않는다.
 *
 * ⚠️ 다만 그 숫자는 **URL 로 나가지 않는다**(위 describe). 화면은 이 값으로 칩 문구와
 *    목록 필터를 만들고, 서버는 저장된 희망가로 같은 상한을 만든다 — 우선순위가 같아야
 *    화면과 결과가 갈라지지 않는다(api-spec 계약).
 */
describe("희망 매매가가 지도 상한이 된다", () => {
  it("희망가가 있으면 한도 대신 희망가가 실효 상한이다", () => {
    expect(effectiveBudgetKrw({ ...BASE, targetPriceKrw: 700_000_000 })).toBe(700_000_000);
  });

  it("한도를 **넘겨 잡아도 그대로 쓴다** — 못 사는 집을 보는 게 이 기능의 목적이다", () => {
    expect(effectiveBudgetKrw({ ...BASE, targetPriceKrw: 1_200_000_000 })).toBe(1_200_000_000);
  });

  it("희망가가 없으면 예전대로 한도를 쓴다", () => {
    expect(effectiveBudgetKrw(BASE)).toBe(850_000_000);
    expect(effectiveBudgetKrw({ ...BASE, targetPriceKrw: null })).toBe(850_000_000);
    expect(effectiveBudgetKrw({ ...BASE, targetPriceKrw: 0 })).toBe(850_000_000);
  });

  it("예산 스위치를 끄면 희망가도 함께 빠진다(끄는 게 실제로 동작한다)", () => {
    const q = buildMapQuery("1,2,3,4", 15, {
      ...BASE,
      targetPriceKrw: 700_000_000,
      budgetApplied: false,
    });
    expect(q.budget).toBeUndefined();
  });

  it("칩이 '내 예산'이 아니라 '희망가'라고 말한다 — 둘은 다른 숫자다", () => {
    const chips = filterChips({ ...BASE, targetPriceKrw: 700_000_000 });
    const budget = chips.filter((c) => c.id === "budget");
    expect(budget).toHaveLength(1); // 예산 칩이 두 개로 늘지 않는다
    expect(budget[0].label).toBe("희망가 7.00억 초과 표시");
  });
});

describe("filterChips — 무엇이 걸렸는지 보이게", () => {
  it("예산 칩에 실제 금액이 들어간다", () => {
    const chips = filterChips(BASE);
    const budget = chips.find((c) => c.id === "budget");
    // 표기는 lib/format 의 짧은 금액 규칙을 그대로 따른다(10억 미만은 소수 둘째자리).
    expect(budget?.label).toBe("내 예산 8.50억 초과 표시");
    expect(budget?.active).toBe(true);
  });

  it("스위치를 끄면 칩은 남고 active 만 false — 사라지면 되켤 수 없다", () => {
    const chips = filterChips({ ...BASE, budgetApplied: false });
    expect(chips.find((c) => c.id === "budget")?.active).toBe(false);
  });

  it("값이 없는 조건은 칩을 만들지 않는다(끌 게 없는 스위치 금지)", () => {
    const chips = filterChips({
      budgetKrw: null,
      budgetApplied: true,
      prefer: {},
      preferApplied: true,
      purpose: "live",
    });
    expect(chips).toEqual([]);
  });

  it("한쪽만 있는 면적 범위도 문장으로 말한다", () => {
    const chips = filterChips({ ...BASE, prefer: { area_min_m2: 59 } });
    expect(chips.find((c) => c.id === "area")?.label).toBe("면적 59㎡ 이상");
  });

  /**
   * CR37-7 — 라벨이 **하는 일과 다른 말**을 하고 있었다.
   * "희망가 9.00억 이하"는 걸러진다는 뜻인데 지도·목록은 거르지 않는다(의도된 설계).
   * 거짓말을 없애는 방법은 두 가지뿐이다: 실제로 거르거나, 하는 일을 그대로 적거나.
   * 후자를 골랐으므로 **그 단어가 다시 기어들어오지 않게** 못박는다.
   */
  it("예산 칩은 '이하'·'이내'라고 **말하지 않는다** — 거르지 않기 때문이다", () => {
    for (const f of [BASE, { ...BASE, targetPriceKrw: 900_000_000 }]) {
      const label = filterChips(f).find((c) => c.id === "budget")?.label ?? "";
      expect(label, `거르지 않는데 '${label}' 이라고 말한다`).not.toMatch(/이하|이내|까지/);
      expect(label).toContain("초과 표시");
    }
  });
});

/**
 * 예산 칩이 **실제로 무언가를 한다** (CR37-7).
 *
 * 예전 칩은 켜도 꺼도 화면이 똑같았다 — 배지도 목록도 그대로였고(서버·리포지토리가
 * 예산으로 거르지 않으므로) 남는 변화가 없었다. "눌러도 무반응인 스위치"의 정확한 형태다.
 * 이제 칩은 **초과 표시**를 켜고 끈다: `displayBudget` 이 그 게이트다.
 */
describe("displayBudget — 칩이 초과 표시를 켜고 끈다", () => {
  it("켜져 있으면 실효 예산 그대로다", () => {
    expect(displayBudget(BASE)).toEqual({ krw: 850_000_000, basis: "max_purchase" });
    expect(displayBudget({ ...BASE, targetPriceKrw: 900_000_000 })).toEqual({
      krw: 900_000_000,
      basis: "target_price",
    });
  });

  it("끄면 **null** 이다 — 이 한 줄이 배지·마커·초과 집계를 함께 끈다", () => {
    expect(displayBudget({ ...BASE, budgetApplied: false })).toEqual({ krw: null, basis: null });
    expect(
      displayBudget({ ...BASE, budgetApplied: false, targetPriceKrw: 900_000_000 }),
    ).toEqual({ krw: null, basis: null });
  });

  it("`effectiveBudget` 은 **그대로 둔다** — 표시 여부와 '무엇이 기준인가'는 다른 질문이다", () => {
    // AI 추천 조건 문구·서버 요청 판정은 칩을 꺼도 기준 자체는 알고 있어야 한다.
    const off = { ...BASE, budgetApplied: false, targetPriceKrw: 900_000_000 };
    expect(effectiveBudgetKrw(off)).toBe(900_000_000);
    expect(displayBudget(off).krw).toBeNull();
  });
});
