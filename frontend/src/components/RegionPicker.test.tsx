// @vitest-environment jsdom
/**
 * 분석 지역 선택 — 사용자 요청("시군구, 역으로 검색 · 멀티 체크").
 *
 * 여기서 지키는 정직성:
 *  · 아무것도 안 고르면 **전체**라는 사실과 **조회 상한**을 화면이 말한다
 *  · 이 목록은 행정구역 목록이지 "데이터가 있는 지역" 목록이 아니라는 한계를 밝힌다
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { REGIONS } from "../lib/regions";
import { RegionPicker } from "./RegionPicker";

afterEach(cleanup);

describe("선택 전", () => {
  it("아무것도 안 고르면 전체에서 찾는다는 사실과 조회 상한을 말한다", () => {
    render(<RegionPicker value={[]} onChange={vi.fn()} />);

    const scope = screen.getByText(/수도권 전체에서 찾습니다/);
    expect(scope.textContent).toContain("50개");
    expect(scope.textContent).toContain("지역을 좁히면");
  });

  /**
   * "이 주변"(지도 범위)이 걸려 있으면 전체에서 찾지 **않는다**.
   * 이 분기가 없으면 화면이 "수도권 전체에서 찾습니다"라고 거짓말한다.
   */
  it("이 주변이 걸려 있으면 전체라고 말하지 않는다", () => {
    render(<RegionPicker value={[]} onChange={vi.fn()} areaScoped />);

    expect(screen.queryByText(/수도권 전체에서 찾습니다/)).toBeNull();
    const scope = screen.getByText(/이 주변/);
    expect(scope.textContent).toMatch(/지도 범위/);
    expect(scope.textContent).toMatch(/교집합/); // 시군구를 더하면 어떻게 되는지도 말한다
  });
});

describe("멀티 선택", () => {
  it("여러 시군구를 체크할 수 있다", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<RegionPicker value={["11680"]} onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: "지역 변경" }));
    await user.click(screen.getByRole("checkbox", { name: /서초구/ }));

    // 기존 선택을 지우지 않고 **더한다**
    expect(onChange).toHaveBeenCalledWith(["11680", "11650"]);
  });

  it("이미 고른 지역을 다시 누르면 뺀다", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<RegionPicker value={["11680", "11650"]} onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: "지역 변경" }));
    const checked = screen.getByRole("checkbox", { name: /강남구/ }) as HTMLInputElement;
    expect(checked.checked).toBe(true);
    await user.click(checked);

    expect(onChange).toHaveBeenCalledWith(["11650"]);
  });

  it("고른 지역이 칩으로 보이고, 칩을 눌러 지운다", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<RegionPicker value={["41135"]} onChange={onChange} />);

    const chips = screen.getByRole("list", { name: "선택한 지역" });
    // 시도까지 붙여야 '중구'가 서울인지 인천인지 구분된다
    const chip = within(chips).getByRole("button", { name: /경기 성남시 분당구/ });
    await user.click(chip);

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("모두 지우기로 전체 범위로 되돌린다", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<RegionPicker value={["11680", "11650"]} onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: "모두 지우기" }));

    expect(onChange).toHaveBeenCalledWith([]);
  });
});

describe("검색·필터", () => {
  it("이름으로 좁힌다 — '분당'으로 성남시 분당구를 찾는다", async () => {
    const user = userEvent.setup();
    render(<RegionPicker value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "지역 선택" }));

    await user.type(screen.getByLabelText("시군구 검색"), "분당");

    expect(screen.getByRole("checkbox", { name: /분당구/ })).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: /강남구/ })).toBeNull();
  });

  it("시도로도 좁힌다", async () => {
    const user = userEvent.setup();
    render(<RegionPicker value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "지역 선택" }));

    await user.click(screen.getByRole("button", { name: "인천", pressed: false }));

    expect(screen.getByRole("checkbox", { name: /인천 부평구/ })).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: /서울 중구/ })).toBeNull();
  });

  it("결과가 없으면 그렇게 말한다(빈 목록을 조용히 두지 않는다)", async () => {
    const user = userEvent.setup();
    render(<RegionPicker value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "지역 선택" }));

    await user.type(screen.getByLabelText("시군구 검색"), "없는동네");

    expect(screen.getByText("검색 결과가 없습니다.")).toBeTruthy();
  });

  it("수도권 91개 시군구를 모두 고를 수 있다", async () => {
    const user = userEvent.setup();
    render(<RegionPicker value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "지역 선택" }));

    expect(screen.getAllByRole("checkbox").length).toBe(REGIONS.length);
    expect(REGIONS.length).toBe(91);
  });
});

describe("목록의 한계를 숨기지 않는다", () => {
  it("행정구역 기준이며 데이터가 없는 지역이 있을 수 있다고 밝힌다", async () => {
    const user = userEvent.setup();
    render(<RegionPicker value={[]} onChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "지역 선택" }));

    const note = screen.getByText(/행정구역 목록입니다/);
    expect(note.textContent).toContain("실거래를 수집하지 못한 지역");
    expect(note.textContent).toContain("2026-07-25"); // 기준일도 함께
  });
});

describe("분석 중", () => {
  it("돌아가는 동안에는 지역을 못 바꾼다(요청과 화면이 어긋나지 않게)", () => {
    render(<RegionPicker value={["11680"]} onChange={vi.fn()} disabled />);

    expect((screen.getByRole("button", { name: "지역 변경" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect((screen.getByRole("button", { name: "모두 지우기" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });
});
