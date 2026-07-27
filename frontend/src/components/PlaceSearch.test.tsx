// @vitest-environment jsdom
/**
 * 장소·역 검색 상자.
 *
 * 여기서 못박는 것은 하나다: **누른 결과가 조용히 사라지지 않는다.**
 * 검색이 실패했으면 실패했다고, 골랐는데 못 옮겼으면 못 옮겼다고 화면이 말해야 한다.
 * (좌표 정규화·상태 판정은 lib/placeSearch.test 가 맡는다 — 여기서 겹쳐 보지 않는다.)
 */
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { installKakaoStub, type KakaoStubHandle } from "../test/kakaoStub";
import { PlaceSearch } from "./PlaceSearch";

let kakao: KakaoStubHandle | null = null;

afterEach(() => {
  cleanup();
  kakao?.restore();
  kakao = null;
});

const GANGNAM = {
  id: "1",
  place_name: "강남역 2호선",
  address_name: "서울 강남구 역삼동 858",
  x: "127.0279",
  y: "37.4971",
};

describe("고른 결과를 부모에게 넘긴다", () => {
  it("검색 → 결과 클릭 → 좌표를 [경도, 위도] 로 올린다", async () => {
    kakao = installKakaoStub({ places: { status: "OK", rows: [GANGNAM] } });
    const onPick = vi.fn();
    const user = userEvent.setup();
    render(<PlaceSearch onPick={onPick} />);

    await user.type(screen.getByLabelText("장소·역 검색"), "강남역");
    await user.click(screen.getByRole("button", { name: "찾기" }));
    await user.click(await screen.findByRole("button", { name: /강남역 2호선/ }));

    expect(onPick).toHaveBeenCalledTimes(1);
    const [lng, lat] = onPick.mock.calls[0][0].point;
    expect(lng).toBeCloseTo(127.0279, 3); // 경도가 먼저다(뒤집히면 태평양)
    expect(lat).toBeCloseTo(37.4971, 3);
  });

  it("고르면 목록을 닫는다 — 지도가 가려지지 않게", async () => {
    kakao = installKakaoStub({ places: { status: "OK", rows: [GANGNAM] } });
    const user = userEvent.setup();
    render(<PlaceSearch onPick={vi.fn()} />);

    await user.type(screen.getByLabelText("장소·역 검색"), "강남역");
    await user.click(screen.getByRole("button", { name: "찾기" }));
    await user.click(await screen.findByRole("button", { name: /강남역 2호선/ }));

    expect(screen.queryByRole("button", { name: /강남역 2호선/ })).toBeNull();
  });
});

describe("실패를 조용히 삼키지 않는다", () => {
  /**
   * 운영에서 실제로 도는 경로다(2026-07-28 진단): 카카오 콘솔에 웹 도메인이 등록돼 있지
   * 않으면 검색 XHR 이 401 로 돌아오고, SDK 는 `cb("ERROR", null, null)` 로 콜백한다.
   */
  it("검색이 거부되면 그 사실과 고칠 곳을 화면에 적는다", async () => {
    kakao = installKakaoStub({ places: { status: "ERROR", rows: [] } });
    const user = userEvent.setup();
    render(<PlaceSearch onPick={vi.fn()} />);

    await user.type(screen.getByLabelText("장소·역 검색"), "강남역");
    await user.click(screen.getByRole("button", { name: "찾기" }));

    expect(await screen.findByText(/도메인이 등록됐는지/)).toBeTruthy();
    // 버튼이 "찾는 중…" 에 갇히지 않는다(실패해도 되돌아온다)
    expect(screen.getByRole("button", { name: "찾기" })).toBeTruthy();
  });

  /**
   * 부모(MapView)가 "못 옮겼다"고 알려 주면 그대로 보인다.
   * 예전에는 지도가 준비되기 전에 결과를 누르면 **아무 일도 일어나지 않았다** —
   * 사용자는 자기가 잘못 눌렀다고 생각한다.
   */
  it("옮기지 못했다는 안내를 받으면 화면에 보인다", () => {
    render(<PlaceSearch onPick={vi.fn()} notice="지도를 아직 불러오지 못해 이동할 수 없습니다." />);

    const notice = screen.getByRole("status");
    expect(notice.textContent).toContain("이동할 수 없습니다");
  });

  it("안내가 없으면 빈 자리를 만들지 않는다", () => {
    render(<PlaceSearch onPick={vi.fn()} />);
    expect(screen.queryByRole("status")).toBeNull();
  });
});
