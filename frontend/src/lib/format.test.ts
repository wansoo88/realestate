import { describe, expect, it } from "vitest";
import {
  confidenceLabel,
  formatArea,
  formatAsOf,
  formatKrw,
  formatKrwCompact,
  formatKrwShort,
  formatPct,
} from "./format";

describe("formatKrw", () => {
  it("억과 만을 함께 표기한다", () => {
    expect(formatKrw(1_480_000_000)).toBe("14억 8,000만");
  });

  it("만 단위가 0이면 억만 표기한다", () => {
    expect(formatKrw(1_400_000_000)).toBe("14억");
  });

  it("억 미만은 만으로 표기한다", () => {
    expect(formatKrw(85_000_000)).toBe("8,500만");
  });

  it("만 미만은 원으로 표기한다", () => {
    expect(formatKrw(5_000)).toBe("5,000원");
  });

  it("0과 null을 구분한다", () => {
    // "데이터 없음"과 "0원"은 완전히 다른 의미다
    expect(formatKrw(0)).toBe("0원");
    expect(formatKrw(null)).toBe("—");
    expect(formatKrw(undefined)).toBe("—");
  });

  it("음수도 처리한다", () => {
    expect(formatKrw(-1_400_000_000)).toBe("-14억");
  });
});

describe("formatKrwShort", () => {
  it("10억 이상은 소수 첫째자리", () => {
    expect(formatKrwShort(1_480_000_000)).toBe("14.8억");
  });

  it("10억 미만은 소수 둘째자리", () => {
    expect(formatKrwShort(850_000_000)).toBe("8.50억");
  });

  it("억 미만은 만 단위", () => {
    expect(formatKrwShort(85_000_000)).toBe("8,500만");
  });
});

/**
 * 지도 마커용 압축 표기. 한 화면에 수십 개가 동시에 뜨므로 **자릿수를 고정**해야
 * pill 폭이 예측 가능해지고 서로 덜 겹친다.
 */
describe("formatKrwCompact", () => {
  it("억 단위 소수 1자리로 고정한다 — 10억 미만도 2자리로 늘리지 않는다", () => {
    expect(formatKrwCompact(840_000_000)).toBe("8.4억");
    expect(formatKrwCompact(1_480_000_000)).toBe("14.8억");
    // formatKrwShort 는 같은 값을 "8.50억"으로 준다(칩·리스트용). 마커는 더 짧아야 한다.
    expect(formatKrwShort(850_000_000)).toBe("8.50억");
    expect(formatKrwCompact(850_000_000)).toBe("8.5억");
  });

  it("100억 이상은 소수점을 버린다(그 구간에서 1,000만원 자리는 판단을 바꾸지 않는다)", () => {
    expect(formatKrwCompact(12_000_000_000)).toBe("120억");
  });

  it("억 미만은 만 단위", () => {
    expect(formatKrwCompact(85_000_000)).toBe("8,500만");
  });

  it("모르는 값은 0 이 아니라 대시", () => {
    expect(formatKrwCompact(null)).toBe("—");
    expect(formatKrwCompact(undefined)).toBe("—");
  });
});

describe("formatArea", () => {
  it("제곱미터와 평을 함께 보여준다", () => {
    expect(formatArea(84.97)).toBe("84.97㎡ (25.7평)");
  });

  it("값이 없으면 대시", () => {
    expect(formatArea(null)).toBe("—");
  });
});

describe("formatPct", () => {
  it("부호를 항상 붙인다", () => {
    // 색만으로 상승/하락을 표시하면 색각 이상 사용자가 구분 못 한다
    expect(formatPct(5.7)).toBe("+5.7%");
    expect(formatPct(-3.2)).toBe("-3.2%");
    expect(formatPct(0)).toBe("+0.0%");
  });
});

describe("formatAsOf", () => {
  it("한국어 기준일로 바꾼다", () => {
    expect(formatAsOf("2026-06-30")).toBe("2026년 6월 30일 기준");
  });

  it("값이 없으면 미상으로 표기한다", () => {
    expect(formatAsOf(null)).toBe("기준일 미상");
  });
});

describe("confidenceLabel", () => {
  it("추정치를 확정치처럼 보이게 하지 않는다", () => {
    expect(confidenceLabel("confirmed")).toBe("실거래 기준");
    expect(confidenceLabel("estimated")).toBe("추정");
    expect(confidenceLabel("unknown")).toBe("데이터 없음");
  });
});
