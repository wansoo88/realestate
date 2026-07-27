/**
 * 내부 식별자 제거 — **의미를 바꾸지 않는다**가 유일한 계약.
 * 서버가 문구를 바꾸면 치환이 안 걸릴 뿐, 문장을 잘못 재조립하는 일은 없어야 한다.
 */
import { describe, expect, it } from "vitest";
import { isInternalIdentifier, plainText, plainTexts } from "./plainTerms";

describe("내부 식별자 판별", () => {
  it("코드 구분자(_ . -)를 가진 ASCII 토큰만 내부 식별자다", () => {
    expect(isInternalIdentifier("liquidity.turnover_12m_pct")).toBe(true);
    expect(isInternalIdentifier("dong_valuation")).toBe(true);
    expect(isInternalIdentifier("risk-auditor")).toBe(true);
    expect(isInternalIdentifier("ask_gap_pct")).toBe(true);
  });

  it("사용자에게 의미 있는 약어는 건드리지 않는다", () => {
    // 이걸 지우면 "한도를 결정한 건 담보인정비율입니다" 처럼 근거가 흐려진다
    expect(isInternalIdentifier("LTV")).toBe(false);
    expect(isInternalIdentifier("DSR")).toBe(false);
    expect(isInternalIdentifier("API")).toBe(false);
    expect(isInternalIdentifier("84A")).toBe(false);
  });

  it("한국어·공백이 섞이면 설명 문구지 식별자가 아니다", () => {
    expect(isInternalIdentifier("공공 오픈API 에는 호가가 포함되지 않습니다")).toBe(false);
    expect(isInternalIdentifier("학구도 데이터 미확보")).toBe(false);
  });
});

describe("실제로 화면에 새어나온 문장들", () => {
  it("환금성 신호에서 내부 이름을 걷어낸다", () => {
    expect(plainText("12개월 거래회전율 기반 환금성(liquidity.turnover_12m_pct)")).toBe(
      "12개월 거래회전율 기반 환금성",
    );
  });

  it("동별 편차 문구", () => {
    expect(
      plainText(
        "동별 가격 편차(dong_valuation)는 '어느 동이 비싼가'를 재는 값이라 후보 점수로 환산하지 않고 참고 정보로만 제공합니다.",
      ),
    ).toBe(
      "동별 가격 편차는 '어느 동이 비싼가'를 재는 값이라 후보 점수로 환산하지 않고 참고 정보로만 제공합니다.",
    );
  });

  it("리스크 커버리지 문구", () => {
    expect(
      plainText("권리관계·근저당·재건축 추가분담금·깡통전세 분석(risk-auditor)은 2차 기능입니다."),
    ).toBe("권리관계·근저당·재건축 추가분담금·깡통전세 분석은 2차 기능입니다.");
  });

  it("설명이 든 괄호는 남긴다 — 사용자가 읽어야 할 근거다", () => {
    const s = "활성 호가가 없어 갭을 계산할 수 없습니다 (공공 오픈API 에는 호가가 포함되지 않습니다)";
    expect(plainText(s)).toBe(s);
  });

  it("아무것도 지울 게 없으면 원문 그대로다", () => {
    expect(plainText("학구도 데이터 미확보")).toBe("학구도 데이터 미확보");
    expect(plainText("")).toBe("");
  });

  it("서버가 문구를 바꿔도 문장이 깨지지 않는다(치환이 안 걸릴 뿐)", () => {
    const changed = "환금성 지표를 씁니다";
    expect(plainText(changed)).toBe(changed);
  });

  it("배열도 같은 규칙으로 처리한다", () => {
    expect(plainTexts(["매물 신뢰도(listing_trust) 점수", "학구도 미확보"])).toEqual([
      "매물 신뢰도 점수",
      "학구도 미확보",
    ]);
  });
});
