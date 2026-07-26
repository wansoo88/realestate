/**
 * 금액 입력 변환 — 화면(만원) ↔ 서버(원) 경계 테스트.
 * 여기서 10,000 배가 어긋나면 세금·대출 한도가 전부 틀린다.
 */
import { describe, expect, it } from "vitest";
import {
  caretForDigitCount,
  countDigitsBefore,
  groupDigits,
  krwToManwonDigits,
  manwonDigitsToKrw,
  normalizeDigits,
} from "./money";

describe("normalizeDigits", () => {
  it("숫자가 아닌 문자는 전부 버린다", () => {
    expect(normalizeDigits("3,0 0 0만원")).toBe("3000");
    expect(normalizeDigits("-500")).toBe("500"); // 음수 금액은 존재하지 않는다
    expect(normalizeDigits("1.5")).toBe("15");
  });

  it("선행 0 을 지운다", () => {
    expect(normalizeDigits("007")).toBe("7");
    expect(normalizeDigits("0")).toBe("0");
  });

  it("자릿수 상한을 넘기지 않는다", () => {
    expect(normalizeDigits("1".repeat(30)).length).toBe(12);
  });
});

describe("만원 ↔ 원", () => {
  it("만원 입력은 10,000 을 곱해 보낸다", () => {
    expect(manwonDigitsToKrw("30000")).toBe(300_000_000); // 3억
  });

  it("빈 입력은 0 이 아니라 null(미입력)", () => {
    expect(manwonDigitsToKrw("")).toBeNull();
  });

  it("원 → 만원 표시로 되돌린다", () => {
    expect(krwToManwonDigits(300_000_000)).toBe("30000");
    expect(krwToManwonDigits(null)).toBe("");
  });

  it("왕복해도 값이 변하지 않는다", () => {
    for (const krw of [0, 10_000, 850_000_000, 1_480_000_000]) {
      expect(manwonDigitsToKrw(krwToManwonDigits(krw))).toBe(krw === 0 ? 0 : krw);
    }
  });
});

describe("groupDigits", () => {
  it("3자리마다 콤마", () => {
    expect(groupDigits("1234567")).toBe("1,234,567");
    expect(groupDigits("100")).toBe("100");
    expect(groupDigits("")).toBe("");
  });
});

describe("캐럿 보존", () => {
  it("앞쪽 숫자 개수를 세어 콤마 삽입 후 위치를 되찾는다", () => {
    // "1,234" 에서 캐럿이 3(=1,2 뒤) → 앞 숫자 2개
    expect(countDigitsBefore("1,234", 3)).toBe(2);
    // 숫자 2개 뒤 = "12" 다음 → "12,345" 에서 인덱스 2
    expect(caretForDigitCount("12,345", 2)).toBe(2);
    expect(caretForDigitCount("12,345", 3)).toBe(4); // 콤마를 건너뛴다
  });

  it("빈 입력이면 맨 앞", () => {
    expect(caretForDigitCount("", 0)).toBe(0);
  });
});
