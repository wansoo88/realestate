// @vitest-environment jsdom
/**
 * 범례 테스트 — 여기서 지키는 건 디자인이 아니라 **고지의 존재**다.
 *
 * 마커에서 '추정' 글자를 뺐다(모든 마커에 붙어 노이즈였다). 그 대신 고지를 이 한 곳으로
 * 모았으므로, 이 요약 줄이 사라지면 화면 어디에도 "추정치"라는 말이 남지 않는다.
 * 그래서 **접힌 상태에서도 보이는지**를 못박는다.
 */
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { NOTICE_TRADE_DELAY } from "../lib/notices";
import { MapLegend } from "./MapLegend";

afterEach(cleanup);

describe("MapLegend", () => {
  it("접혀 있어도 '추정치'라는 고지는 화면에 남는다", () => {
    render(<MapLegend />);

    expect(screen.getByText("지도 가격은 추정치")).toBeTruthy();
    expect(screen.getByRole("button", { name: /표시 안내/ }).getAttribute("aria-expanded")).toBe(
      "false",
    );
  });

  it("펼치면 무엇이 추정인지와 마커 색의 뜻을 설명한다", async () => {
    const user = userEvent.setup();
    render(<MapLegend />);

    await user.click(screen.getByRole("button", { name: /표시 안내/ }));

    expect(screen.getByText(/실거래 기반 추정치/)).toBeTruthy();
    // 호가가 아니라는 점을 분명히 한다(price_basis 계약: trade 는 호가가 아니다)
    expect(screen.getByText(/현재 나와 있는 호가가 아닙니다/)).toBeTruthy();
    expect(screen.getByText(/예산 초과/)).toBeTruthy();
    expect(screen.getByText(/밀집 구간이라 가격을 줄인 상태/)).toBeTruthy();
  });

  it("실거래 30일 지연 고지는 lib/notices 문구를 그대로 쓴다", async () => {
    // 화면마다 다르게 쓰면 고지가 아니라 장식이 된다(components.md §3.4)
    const user = userEvent.setup();
    render(<MapLegend />);
    await user.click(screen.getByRole("button", { name: /표시 안내/ }));

    expect(screen.getByText(NOTICE_TRADE_DELAY)).toBeTruthy();
  });

  it("키보드로 열고 닫을 수 있다", async () => {
    const user = userEvent.setup();
    render(<MapLegend />);
    const toggle = screen.getByRole("button", { name: /표시 안내/ });

    toggle.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: /닫기/ }).getAttribute("aria-expanded")).toBe("true");

    await user.keyboard("{Enter}");
    expect(screen.queryByText(/실거래 기반 추정치/)).toBeNull();
  });
});
