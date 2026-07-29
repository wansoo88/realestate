/**
 * 내 매물 순수 로직.
 *
 * 여기서 고정하는 것은 **거짓말이 만들어지는 지점** 셋이다.
 *  ① `as_of` 기본값 없음 — 오늘 날짜를 미리 채우면 3주 전 호가가 오늘 값이 된다.
 *  ② 가격을 바꾸면 날짜도 함께 — 안 그러면 옛 날짜에 새 가격이 붙는다(서버도 422).
 *  ③ 출처 라벨을 프론트가 만들지 않는다 — 만들면 어느 화면에선가 빠지고,
 *     빠진 화면에서 이 숫자는 공공 데이터처럼 보인다.
 */
import { describe, expect, it } from "vitest";
import type { UserListing } from "../api/client";
// 목은 한 곳에서만 만든다 — 파일마다 손으로 적으면 계약이 바뀌어도 전부 초록이 된다
// (`src/test/apiContract.test.ts` 가 이 목을 문서와 대조한다).
import { userListing } from "../test/fixtures";
import {
  EMPTY_FORM,
  buildCreate,
  buildPatch,
  daysBetween,
  eligibility,
  formFromListing,
  hasErrors,
  parseIsoDate,
  sourceLabel,
  stalenessView,
  summaryText,
  todayIso,
  validateForm,
  type ListingFormValues,
} from "./userListings";

const TODAY = "2026-07-29";

/** 이 파일은 날짜 규칙을 고정하므로 `as_of` 만 고정값으로 덮는다(TODAY 기준 1일 전). */
function listing(over: Partial<UserListing> = {}): UserListing {
  return userListing({ as_of: "2026-07-28", ...over });
}

function form(over: Partial<ListingFormValues> = {}): ListingFormValues {
  return {
    askPriceKrw: 1_480_000_000,
    areaM2: "84.97",
    floor: "9",
    aptDong: "101동",
    asOf: "2026-07-28",
    // 저장된 값과 **같게** 둔다 — 다르면 "안 건드림"이 아니라 수정으로 잡힌다(그게 정상이다)
    note: "네이버 부동산 · ○○공인",
    ...over,
  };
}

describe("날짜 — 로컬 타임존이 하루를 밀지 않게", () => {
  it("존재하지 않는 날짜는 거절한다(Date 는 조용히 굴려 버린다)", () => {
    expect(parseIsoDate("2026-02-30")).toBeNull();
    expect(parseIsoDate("2026-7-1")).toBeNull();
    expect(parseIsoDate("")).toBeNull();
    expect(parseIsoDate("2026-07-01")).not.toBeNull();
  });

  it("일수는 UTC 로만 센다", () => {
    expect(daysBetween("2026-07-28", TODAY)).toBe(1);
    expect(daysBetween(TODAY, TODAY)).toBe(0);
    expect(daysBetween("2026-07-30", TODAY)).toBe(-1); // 미래
  });

  it("todayIso 는 로컬 달력 날짜를 그대로 쓴다", () => {
    expect(todayIso(new Date(2026, 6, 29, 23, 30))).toBe("2026-07-29");
  });
});

describe("확인 날짜(as_of) 는 기본값이 없다", () => {
  it("빈 폼의 as_of 는 빈 문자열이다 — 오늘로 미리 채우지 않는다", () => {
    expect(EMPTY_FORM.asOf).toBe("");
    // 오늘 날짜가 새어 들어오지 않았는지도 함께 본다
    expect(EMPTY_FORM.asOf).not.toBe(todayIso());
  });

  it("비워 두면 저장을 막고 왜 묻는지 말한다", () => {
    const errors = validateForm(form({ asOf: "" }), { today: TODAY });
    expect(errors.asOf).toContain("직접 확인한 날짜");
  });

  it("미래 날짜와 1년 초과는 거절한다(서버와 같은 규칙)", () => {
    expect(validateForm(form({ asOf: "2026-07-30" }), { today: TODAY }).asOf).toContain("미래");
    expect(validateForm(form({ asOf: "2025-07-28" }), { today: TODAY }).asOf).toContain("1년");
    // 경계: 정확히 365일 전은 통과한다(서버가 받아 주는 값을 화면이 거부하지 않는다)
    expect(validateForm(form({ asOf: "2025-07-29" }), { today: TODAY }).asOf).toBeUndefined();
  });
});

describe("검증은 서버 규칙의 복사본이다 — 더 엄격하지 않다", () => {
  it("단위 실수(억·만원)를 잡는다", () => {
    expect(validateForm(form({ askPriceKrw: 15 }), { today: TODAY }).askPriceKrw).toContain("단위");
    expect(validateForm(form({ askPriceKrw: null }), { today: TODAY }).askPriceKrw).toBeTruthy();
  });

  it("면적의 Infinity·NaN 을 통과시키지 않는다(gt=0 을 그냥 지나간다)", () => {
    expect(validateForm(form({ areaM2: "Infinity" }), { today: TODAY }).areaM2).toBeTruthy();
    expect(validateForm(form({ areaM2: "1e5" }), { today: TODAY }).areaM2).toBeTruthy();
    expect(validateForm(form({ areaM2: "0" }), { today: TODAY }).areaM2).toBeTruthy();
    expect(validateForm(form({ areaM2: "1001" }), { today: TODAY }).areaM2).toBeTruthy();
  });

  it("층은 비워 둘 수 있다 — 0 으로 채우지 않는다(1층 기피 판정이 망가진다)", () => {
    expect(validateForm(form({ floor: "" }), { today: TODAY }).floor).toBeUndefined();
    expect(validateForm(form({ floor: "9999" }), { today: TODAY }).floor).toBeTruthy();
    expect(validateForm(form({ floor: "-1" }), { today: TODAY }).floor).toBeUndefined();
  });

  it("이상하지만 가능한 값은 **막지 않는다**(₩/㎡ 이상은 서버가 problems 로 말한다)", () => {
    // 1㎡ 당 1억이 넘는 값이지만 저장은 된다 — 화면이 막으면 강남 초고가를 못 넣는다
    const errors = validateForm(form({ askPriceKrw: 90_000_000_000, areaM2: "84.97" }), {
      today: TODAY,
    });
    expect(hasErrors(errors)).toBe(false);
  });
});

describe("등록 본문", () => {
  it("비어 있는 선택 항목은 키를 싣지 않는다(null 과 미입력을 섞지 않는다)", () => {
    const body = buildCreate(1234, form({ floor: "", aptDong: "", note: "" }));
    expect(body).toEqual({
      complex_id: 1234,
      ask_price_krw: 1_480_000_000,
      area_m2: 84.97,
      as_of: "2026-07-28",
    });
    expect("floor" in body).toBe(false);
  });

  it("적은 값은 그대로 실린다", () => {
    const body = buildCreate(1234, form({ note: " 메모 " }));
    expect(body.floor).toBe(9);
    expect(body.apt_dong).toBe("101동");
    expect(body.note).toBe("메모");
  });
});

describe("수정 — 가격과 날짜는 분리될 수 없다", () => {
  it("가격만 바꾸고 날짜를 비우면 **요청을 만들지 않는다**", () => {
    const r = buildPatch(listing(), form({ askPriceKrw: 1_500_000_000, asOf: "" }));
    expect("error" in r).toBe(true);
    if ("error" in r) expect(r.error).toContain("확인한 날짜");
  });

  it("가격을 바꾸면 날짜가 그대로여도 as_of 를 함께 싣는다", () => {
    const r = buildPatch(listing(), form({ askPriceKrw: 1_500_000_000, asOf: "2026-07-29" }));
    expect(r).toEqual({ body: { ask_price_krw: 1_500_000_000, as_of: "2026-07-29" } });
  });

  it("날짜만 갱신하는 것은 허용된다(같은 가격을 오늘 다시 확인했다)", () => {
    const r = buildPatch(listing(), form({ asOf: "2026-07-29" }));
    expect(r).toEqual({ body: { as_of: "2026-07-29" } });
  });

  it("비울 수 있는 항목만 null 로 보낸다 — 안 건드린 키는 아예 없다", () => {
    const r = buildPatch(listing(), form({ floor: "", aptDong: "", asOf: "2026-07-28" }));
    expect(r).toEqual({ body: { floor: null, apt_dong: null } });
    if ("body" in r) {
      expect("as_of" in r.body).toBe(false);
      expect("ask_price_krw" in r.body).toBe(false);
    }
  });

  it("바뀐 게 없으면 요청 자체를 만들지 않는다(서버 422 를 일부러 받지 않는다)", () => {
    const r = buildPatch(listing(), formFromListing(listing()));
    expect("error" in r).toBe(true);
  });
});

describe("출처 — 서버가 준 라벨만 쓴다", () => {
  it("서버 문자열을 그대로 돌려준다", () => {
    expect(sourceLabel(listing())).toBe("사용자 입력");
    expect(sourceLabel(listing({ source_label: "직접 입력" }))).toBe("직접 입력");
  });

  it("서버가 안 주면 null — 지어내지 않는다", () => {
    expect(sourceLabel({ source_label: "" })).toBeNull();
    expect(sourceLabel({ source_label: undefined as unknown as string })).toBeNull();
  });
});

/**
 * 낡음·자격 — 판정은 서버 값이 정본이고, **"자격"과 "반영됨"은 다른 말**이다(CR35-7).
 * 서버는 이 호가 한 건의 상태만 안다. 실제 반영은 그 단지가 추천 요청의 지역·예산·평수
 * 조건과 후보 조회 상한을 통과해야 하며, 그건 이 화면이 알 수 없다.
 */
describe("낡음 · 반영 자격", () => {
  it("fresh 는 '반영될 수 있다'까지만 말한다 — '반영됐다'가 아니다", () => {
    const v = stalenessView(listing());
    expect(v.eligible).toBe(true);
    expect(v.badgeText).toBe("반영 가능");
    expect(v.usageText).toContain("반영될 수 있습니다");
    expect(v.usageText).toContain("추천 조건");
    expect(v.usageText).not.toContain("반영됐");
    expect(v.ageText).toBe("1일 전 확인");
    expect(v.needsRefresh).toBe(false);
  });

  it("aging 은 쓰이되 그 사이 움직였을 수 있다고 말한다", () => {
    const v = stalenessView(listing({ staleness: "aging", age_days: 45 }));
    expect(v.eligible).toBe(true);
    expect(v.usageText).toContain("반영될 수 있습니다");
    expect(v.usageText).toContain("시세가 움직였");
  });

  it("stale 은 **제외됨**이라고 말하고 갱신 동선을 띄운다", () => {
    const v = stalenessView(
      listing({ staleness: "stale", age_days: 120, eligible_for_recommendation: false }),
    );
    expect(v.badgeText).toBe("반영 제외");
    expect(v.usageText).toBe("낡아서 추천에서 제외됨");
    expect(v.needsRefresh).toBe(true);
  });

  it("거래됨·내림은 낡음과 다른 이유로 빠진다", () => {
    const v = stalenessView(listing({ status: "traded", eligible_for_recommendation: false }));
    expect(v.usageText).toBe("거래됨 — 추천에서 제외됨");
    expect(v.needsRefresh).toBe(false);
  });

  it("서버가 자격 false 라면 fresh 여도 쓰인다고 하지 않는다", () => {
    const v = stalenessView(listing({ eligible_for_recommendation: false }));
    expect(v.eligible).toBe(false);
    expect(v.usageText).toBe("추천에 반영되지 않습니다");
  });

  /**
   * ★ 이번 사고의 핵심. 서버가 필드 이름을 바꾸면 `item.x === true` 는
   * `undefined === true` → **전부 false** 가 되어 "모든 호가가 반영 안 됨"으로 보인다.
   * 모름은 아님이 아니다 — 모른다고 말해야 한다.
   */
  it("서버가 자격을 아예 안 주면 **모른다고** 말한다(false 로 접지 않는다)", () => {
    const noField = { ...listing() } as Partial<UserListing>;
    delete noField.eligible_for_recommendation;

    expect(eligibility(noField)).toBeNull();
    const v = stalenessView(noField as UserListing);
    expect(v.eligible).toBeNull();
    expect(v.badgeText).toBe("반영 여부 미상");
    expect(v.usageText).toContain("서버가 알려 주지 않았습니다");
    // 모르는데 "제외됐다"고 단정하지 않는다
    expect(v.usageText).not.toContain("제외");
    // 모르는 상태를 "고치라"고 재촉하지도 않는다(고칠 것이 없다)
    expect(v.needsRefresh).toBe(false);
  });

  it("boolean 이 아닌 값(문자열·null)도 모름으로 본다", () => {
    expect(eligibility({ eligible_for_recommendation: "true" as never })).toBeNull();
    expect(eligibility({ eligible_for_recommendation: null as never })).toBeNull();
  });
});

describe("요약", () => {
  it("'반영 5건'이 아니라 '반영 가능 5건'이다", () => {
    expect(
      summaryText({ total: 7, eligible_for_recommendation: 5, stale: 2, inactive: 0 }),
    ).toBe("총 7건 · 반영 가능 5건 · 낡음 2건");
    expect(summaryText({ total: 0, eligible_for_recommendation: 0 })).toBe(
      "총 0건 · 반영 가능 0건",
    );
  });
});
