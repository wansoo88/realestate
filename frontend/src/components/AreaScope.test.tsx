// @vitest-environment jsdom
/**
 * "이 주변에서 찾기" — 이 컴포넌트가 지켜야 할 것은 넷이다.
 *  ① 누르면 **지금 지도 범위**를 그대로 넘긴다(새로 계산하지 않는다)
 *  ② 지도가 없으면 **비활성 + 이유**. 조용히 죽은 버튼은 고장으로 보인다
 *  ③ 잡아 둔 범위가 낡으면(지도를 옮기면) 숨기지 않고 **보여주고 고치게** 한다
 *  ④ 칩 해제로 언제든 뺄 수 있다
 */
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AreaScope } from "./AreaScope";

afterEach(cleanup);

const HERE = "126.90,37.40,127.00,37.60";
const MOVED = "127.10,37.40,127.20,37.60";

const noop = () => {};

function props(over: Partial<React.ComponentProps<typeof AreaScope>> = {}) {
  return {
    currentBbox: HERE as string | null,
    bbox: null as string | null,
    onCapture: noop as (bbox: string) => void,
    onClear: noop,
    regionCodes: [] as string[],
    ...over,
  };
}

describe("범위 잡기", () => {
  it("누른 순간의 지도 범위를 그대로 넘긴다", async () => {
    const onCapture = vi.fn();
    const user = userEvent.setup();
    render(<AreaScope {...props({ onCapture })} />);

    await user.click(screen.getByRole("button", { name: "이 주변에서 찾기" }));

    expect(onCapture).toHaveBeenCalledWith(HERE);
  });

  it("지도가 준비되지 않았으면 비활성 + **이유**를 함께 보인다", () => {
    render(<AreaScope {...props({ currentBbox: null })} />);

    const btn = screen.getByRole("button", { name: /이 주변에서 찾기/ });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
    // 이유는 버튼과 연결돼 보조기기에서도 함께 읽힌다
    const describedBy = btn.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy!)?.textContent).toMatch(
      /지도가 아직 준비되지 않았습니다/,
    );
  });

  /**
   * 서버는 한 변 2.0도 초과를 422 로 막는다. 그냥 잡게 두면 실행 버튼까지 가서야
   * "분석에 필요한 조건이 부족합니다"로 실패한다 — 무엇을 고쳐야 하는지 알 수 없는 실패다.
   */
  it("지도를 너무 많이 축소했으면 비활성 + **고칠 방법**을 보인다", async () => {
    const onCapture = vi.fn();
    const user = userEvent.setup();
    // 한 변 3도 — 서버 상한(2.0도) 초과
    render(<AreaScope {...props({ currentBbox: "125.0,36.0,128.0,38.0", onCapture })} />);

    const btn = screen.getByRole("button", { name: /이 주변에서 찾기/ });
    expect((btn as HTMLButtonElement).disabled).toBe(true);

    const describedBy = btn.getAttribute("aria-describedby");
    const why = document.getElementById(describedBy!)?.textContent ?? "";
    expect(why).toMatch(/너무 넓어/);
    expect(why).toMatch(/확대/); // 무엇을 하면 되는지
    expect(why).toMatch(/km/); // 도(度)로만 말하면 아무도 못 읽는다

    // 프로그램적으로 눌러도 잡히지 않는다(비활성은 시각적 장치일 뿐이다)
    await user.click(btn);
    expect(onCapture).not.toHaveBeenCalled();
  });

  it("상한 안이면 예전 그대로 잡힌다", async () => {
    const onCapture = vi.fn();
    const user = userEvent.setup();
    render(<AreaScope {...props({ currentBbox: "126.0,37.0,127.9,38.9", onCapture })} />);

    await user.click(screen.getByRole("button", { name: "이 주변에서 찾기" }));
    expect(onCapture).toHaveBeenCalled();
  });

  it("분석 중에는 못 바꾸고 그 사유를 말한다", () => {
    render(<AreaScope {...props({ disabled: true })} />);
    const btn = screen.getByRole("button", { name: /이 주변에서 찾기/ });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/분석 중에는 범위를 바꿀 수 없습니다/)).toBeTruthy();
  });
});

describe("적용 표시", () => {
  it("잡아 두면 칩으로 보이고, 크기를 사람 말로 적는다", () => {
    render(<AreaScope {...props({ bbox: HERE })} />);

    expect(screen.getByRole("button", { name: /이 주변 · 지금 지도 범위/ })).toBeTruthy();
    expect(screen.getByText(/찾는 범위: 이 주변\(약 8\.8 × 22km\)/)).toBeTruthy();
  });

  it("칩을 누르면 해제된다", async () => {
    const onClear = vi.fn();
    const user = userEvent.setup();
    render(<AreaScope {...props({ bbox: HERE, onClear })} />);

    await user.click(screen.getByRole("button", { name: /이 주변 · 지금 지도 범위/ }));

    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("시군구와 함께면 교집합이라는 사실을 말한다", () => {
    render(<AreaScope {...props({ bbox: HERE, regionCodes: ["11680"] })} />);

    expect(screen.getByText(/이 주변\(약 8\.8 × 22km\) ∩ 서울 강남구/)).toBeTruthy();
    expect(screen.getByText(/두 조건을 모두 만족하는 단지만 찾습니다\(교집합\)/)).toBeTruthy();
  });

  it("좌표 없는 단지가 빠진다는 사실을 고르는 자리에서 미리 말한다", () => {
    render(<AreaScope {...props({ bbox: HERE })} />);
    expect(screen.getByText(/좌표가 없는 단지는 지도 범위로 찾을 수 없어/)).toBeTruthy();
  });

  it("잡기 전에는 지도 마커가 바뀌지 않는다는 점을 밝힌다(지도 필터로 오해 금지)", () => {
    render(<AreaScope {...props()} />);
    expect(screen.getByText(/지도 표시는 그대로이고, 분석 범위만/)).toBeTruthy();
  });
});

describe("낡은 범위", () => {
  it("지도를 옮기면 낡았다고 말하고 다시 잡을 길을 준다", async () => {
    const onCapture = vi.fn();
    const user = userEvent.setup();
    render(<AreaScope {...props({ bbox: HERE, currentBbox: MOVED, onCapture })} />);

    expect(screen.getByRole("status").textContent).toMatch(/지도를 옮겼습니다/);
    // 칩도 "지금 지도 범위"라고 우기지 않는다
    expect(screen.queryByRole("button", { name: /지금 지도 범위/ })).toBeNull();
    expect(screen.getByRole("button", { name: /잡아 둔 지도 범위/ })).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "지금 지도로 다시 잡기" }));
    expect(onCapture).toHaveBeenCalledWith(MOVED);
  });

  it("같은 자리의 부동소수 잔떨림은 '옮겼다'로 보지 않는다", () => {
    render(
      <AreaScope {...props({ bbox: HERE, currentBbox: "126.90000000001,37.40,127.00,37.60" })} />,
    );
    expect(screen.queryByText(/지도를 옮겼습니다/)).toBeNull();
    expect(screen.getByRole("button", { name: /이 주변 · 지금 지도 범위/ })).toBeTruthy();
  });

  it("최신이면 다시 잡을 버튼을 두지 않는다(누를 게 없는 조작 금지)", () => {
    render(<AreaScope {...props({ bbox: HERE })} />);
    expect(screen.queryByRole("button", { name: /다시 잡기/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "이 주변에서 찾기" })).toBeNull();
  });
});
