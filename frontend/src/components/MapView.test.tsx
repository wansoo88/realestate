// @vitest-environment jsdom
/**
 * 지도 통합 테스트 — 사용자 지적("가격 동그라미가 화면을 덮는다")에 대한 **회귀 방지**.
 *
 * 순수 함수(markerTiers)는 따로 테스트하지만, 실제로 중요한 건 그 판단이 **마커까지 도달하는가**다.
 * 그래서 여기서는 SDK 스텁을 물려 MapView → MarkerLayer → 오버레이 DOM 까지 한 줄로 검증한다.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ComplexItem } from "../api/client";
import { DENSITY_LIMIT } from "../lib/markerTiers";
import { forgetCamera, lastCamera } from "../lib/mapCamera";
import { applyScreenBudget, type ScreenComplexItem } from "../lib/screenBudget";
import { installKakaoStub, type KakaoStubHandle } from "../test/kakaoStub";
import { MapView } from "./MapView";

let kakao: KakaoStubHandle;

beforeEach(() => {
  vi.stubEnv("VITE_KAKAO_JS_APP_KEY", "test-key");
  forgetCamera();
  kakao = installKakaoStub({ level: 6 }); // level 6 → 우리 zoom 14 (가격 단계)
});

afterEach(() => {
  cleanup();
  kakao.restore();
  vi.unstubAllEnvs();
});

/**
 * ⚠️ 목도 **화면이 쓰는 길로** 만든다(`applyScreenBudget`). 지도는 서버 항목을 그대로
 *    받지 않기 때문이다 — 예산 칩 상태를 반영한 값만 들어온다(CR37-2 · CR38-1).
 *    여기서는 표시를 꺼 둔다(전부 `null`)—이 파일의 관심사(표현 단계)와 섞이지 않게.
 */
function complex(id: number, over: Partial<ComplexItem> = {}): ScreenComplexItem {
  return applyScreenBudget(
    [
      {
        id,
        name: `단지${id}`,
        point: [127 + id * 0.001, 37.5],
        households: 500,
        built_year: 2005,
        recent_price_krw: 840_000_000,
        price_as_of: "2026-06-30",
        price_confidence: "estimated",
        active_listings: 1,
        over_budget: null,
        ...over,
      },
    ],
    false,
  )[0];
}

const range = (n: number) => Array.from({ length: n }, (_, i) => complex(i + 1));

/** 오버레이 content 요소들(= 실제로 지도에 붙은 마커 DOM) */
const markers = () => kakao.overlays.map((o) => o.opts.content as HTMLElement);

describe("마커 표현 단계", () => {
  it("임계 이하에서는 가격을 보여준다", async () => {
    render(<MapView onBoundsChange={vi.fn()} items={range(10)} />);

    await waitFor(() => expect(kakao.overlays.length).toBe(10));
    expect(markers()[0].textContent).toBe("8.4억");
    // '추정'은 마커마다 반복하지 않는다 — 범례가 한 곳에서 고지한다
    expect(markers().every((el) => !el.textContent?.includes("추정"))).toBe(true);
  });

  it("밀집하면 점으로 강등하고, 무엇을 줄였는지 화면에 밝힌다", async () => {
    render(<MapView onBoundsChange={vi.fn()} items={range(DENSITY_LIMIT + 5)} />);

    await waitFor(() => expect(kakao.overlays.length).toBe(DENSITY_LIMIT + 5));
    expect(markers().every((el) => el.className.includes("map-pill--dot"))).toBe(true);
    expect(markers().every((el) => el.textContent === "")).toBe(true);

    const notice = screen.getByRole("status");
    expect(notice.textContent).toContain(`${DENSITY_LIMIT + 5}곳`);
    expect(notice.textContent).toContain("확대");
  });

  it("강등 상태에서 '확대'를 누르면 지도가 실제로 확대된다(되찾는 경로)", async () => {
    const user = userEvent.setup();
    render(<MapView onBoundsChange={vi.fn()} items={range(DENSITY_LIMIT + 1)} />);
    await waitFor(() => expect(kakao.overlays.length).toBe(DENSITY_LIMIT + 1));

    await user.click(screen.getByRole("button", { name: "확대해서 보기" }));

    expect(kakao.level()).toBe(5); // 카카오 level 은 작을수록 확대
  });

  it("밀집 안내와 확대 컨트롤의 접근명이 겹치지 않는다", async () => {
    render(<MapView onBoundsChange={vi.fn()} items={range(DENSITY_LIMIT + 1)} />);
    await waitFor(() => expect(kakao.overlays.length).toBe(DENSITY_LIMIT + 1));

    // 같은 이름의 버튼이 둘이면 스크린리더 사용자는 어느 쪽인지 구분할 수 없다
    expect(screen.getAllByRole("button", { name: "확대" }).length).toBe(1);
  });

  it("선택한 단지는 밀집 중에도 혼자 상세로 열린다", async () => {
    render(<MapView onBoundsChange={vi.fn()} items={range(DENSITY_LIMIT + 5)} selectedId={3} />);

    await waitFor(() => expect(kakao.overlays.length).toBe(DENSITY_LIMIT + 5));
    const selected = markers()[2];
    expect(selected.className).toContain("map-pill--selected");
    expect(selected.textContent).toContain("8.4억");
    expect(selected.textContent).toContain("단지3");
  });

  it("목록 hover 는 그 마커만 되살린다 — 지도는 움직이지 않는다", async () => {
    const { rerender } = render(
      <MapView onBoundsChange={vi.fn()} items={range(DENSITY_LIMIT + 5)} />,
    );
    await waitFor(() => expect(kakao.overlays.length).toBe(DENSITY_LIMIT + 5));

    rerender(<MapView onBoundsChange={vi.fn()} items={range(DENSITY_LIMIT + 5)} hoveredId={2} />);

    expect(markers()[1].textContent).toBe("8.4억");
    expect(markers()[0].textContent).toBe("");
    // 오버레이가 재생성되지 않았다(= diff 재사용이 살아 있다)
    expect(kakao.overlays.length).toBe(DENSITY_LIMIT + 5);
  });
});

describe("지도 컨트롤", () => {
  it("확대/축소 버튼이 있고 접근명이 붙어 있다", async () => {
    render(<MapView onBoundsChange={vi.fn()} items={[]} />);

    await waitFor(() => expect(screen.getByRole("button", { name: "축소" })).toBeTruthy());
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "축소" }));
    expect(kakao.level()).toBe(7);
  });

  it("범례가 지도 위에 있고 추정 고지를 달고 있다", async () => {
    render(<MapView onBoundsChange={vi.fn()} items={[]} />);

    await waitFor(() => expect(screen.getByText("지도 가격은 추정치")).toBeTruthy());
  });

  it("지도를 스크린리더로 못 읽는다는 전제 아래 대체 경로를 안내한다", async () => {
    render(<MapView onBoundsChange={vi.fn()} items={[]} />);

    const region = await screen.findByRole("region", { name: "단지 지도" });
    const describedBy = region.getAttribute("aria-describedby") ?? "";
    expect(document.getElementById(describedBy)?.textContent).toContain("목록");
  });
});

/**
 * 역·장소 검색 — **지도 이동만** 한다.
 * 역 반경으로 추천을 제한하는 기능(서버 PostGIS 필요)은 아직 없다. 그래서 이 화면은
 * "역세권 필터"처럼 보이면 안 된다 — 문구로 그 경계를 긋는다.
 */
describe("역·장소 검색", () => {
  it("검색한 곳으로 지도를 옮긴다 — 좌표 순서(CR18-5)를 지킨다", async () => {
    kakao.restore();
    kakao = installKakaoStub({
      level: 8,
      places: {
        status: "OK",
        rows: [{ id: "1", place_name: "강남역 2호선", address_name: "역삼동", x: "127.0279", y: "37.4971" }],
      },
    });
    const user = userEvent.setup();
    render(<MapView onBoundsChange={vi.fn()} items={[]} />);
    await waitFor(() => expect(screen.getByLabelText("장소·역 검색")).toBeTruthy());

    await user.type(screen.getByLabelText("장소·역 검색"), "강남역");
    await user.click(screen.getByRole("button", { name: "찾기" }));
    await user.click(await screen.findByRole("button", { name: /강남역 2호선/ }));

    const [lng, lat] = kakao.center();
    expect(lng).toBeCloseTo(127.0279, 3); // 경도가 먼저다(뒤집히면 태평양)
    expect(lat).toBeCloseTo(37.4971, 3);
    expect(kakao.level()).toBe(5); // 동네가 보이는 줌으로
  });

  it("이 상자가 추천 지역 필터가 아니라는 걸 화면이 말한다", async () => {
    render(<MapView onBoundsChange={vi.fn()} items={[]} />);

    const hint = await screen.findByText(/검색한 위치로 지도를 옮깁니다/);
    expect(hint.textContent).toContain("분석 지역");
    // 안내는 **보여야** 의미가 있다(숨겨 두면 없는 것과 같다)
    expect(hint.hidden).toBe(false);
    expect(document.getElementById("psearch-input")?.getAttribute("aria-describedby")).toBe(
      hint.id,
    );
  });

  it("SDK 장소검색을 못 쓰면 조용히 죽지 않고 그 사실을 알린다(CSP 차단 포함)", async () => {
    // services 없이 띄운 기본 스텁 상태 그대로 — 실제 CSP 차단 시와 같은 경로다.
    const user = userEvent.setup();
    render(<MapView onBoundsChange={vi.fn()} items={[]} />);
    await waitFor(() => expect(screen.getByLabelText("장소·역 검색")).toBeTruthy());

    await user.type(screen.getByLabelText("장소·역 검색"), "강남역");
    await user.click(screen.getByRole("button", { name: "찾기" }));

    expect(await screen.findByText(/장소 검색을 사용할 수 없습니다/)).toBeTruthy();
  });
});

describe("지도 상태 보존", () => {
  it("보던 자리를 기억한다 — 조건을 고치고 돌아와도 서울시청으로 되돌아가지 않는다", async () => {
    const { unmount } = render(<MapView onBoundsChange={vi.fn()} items={[]} />);
    await waitFor(() => expect(screen.getByRole("region", { name: "단지 지도" })).toBeTruthy());

    kakao.restore();
    unmount();

    // 조건 화면을 다녀오는 사이에도 마지막 카메라가 남아 있다
    expect(lastCamera().level).toBe(6);
    expect(lastCamera().center[0]).toBeCloseTo(126.978, 3);
  });

  it("bbox 와 zoom 을 우리 규약(경도,위도 / 클수록 확대)으로 올린다", async () => {
    const onBounds = vi.fn();
    render(<MapView onBoundsChange={onBounds} items={[]} />);

    await waitFor(() => expect(onBounds).toHaveBeenCalled());
    const [bbox, zoom] = onBounds.mock.calls[0];
    const [minLon, minLat, maxLon, maxLat] = bbox.split(",").map(Number);
    expect(minLon).toBeLessThan(maxLon);
    expect(minLat).toBeLessThan(maxLat);
    expect(minLon).toBeGreaterThan(120); // 경도가 먼저다(위도 37.x 가 아니다)
    expect(zoom).toBe(14); // 20 - level 6
  });
});

describe("키가 없을 때", () => {
  it("빈 화면 대신 상황을 설명하고 목록 대체 경로를 알린다", async () => {
    vi.stubEnv("VITE_KAKAO_JS_APP_KEY", "");
    render(<MapView onBoundsChange={vi.fn()} items={[]} />);

    expect(await screen.findByText("지도를 표시할 수 없습니다")).toBeTruthy();
    expect(screen.getByText(/목록으로 단지를 확인할 수 있습니다/)).toBeTruthy();
  });
});

/**
 * SDK 로드 실패 — **조용히 삼키지 않는다.**
 *
 * 배경(2026-07-28 진단): 카카오 JS 키에 웹 도메인이 등록돼 있지 않으면 카카오는
 * `sdk.js` 를 **HTTP 401 + JSON 본문**으로 돌려준다. jsdom 은 외부 스크립트를 받지 않으므로
 * 여기서는 붙은 <script> 를 가로채 브라우저가 하는 일(onerror / onload)을 직접 재현한다.
 */
describe("SDK 로드가 실패할 때", () => {
  /** 붙은 <script> 를 가로채서 로드 결과를 우리가 정한다. */
  function interceptScript() {
    const appended: HTMLScriptElement[] = [];
    const spy = vi
      .spyOn(document.head, "appendChild")
      .mockImplementation(((node: Node) => {
        appended.push(node as HTMLScriptElement);
        return node;
      }) as typeof document.head.appendChild);
    return { appended, restore: () => spy.mockRestore() };
  }

  it("401(도메인 미등록)로 스크립트가 실패하면 **어디를 고쳐야 하는지**까지 말한다", async () => {
    kakao.restore(); // window.kakao 를 지워 실제 로드 경로를 타게 한다
    const s = interceptScript();
    render(<MapView onBoundsChange={vi.fn()} items={[]} />);

    await waitFor(() => expect(s.appended.length).toBe(1));
    expect(s.appended[0].src).toContain("dapi.kakao.com/v2/maps/sdk.js");
    s.appended[0].onerror?.(new Event("error"));

    expect(await screen.findByText("지도를 표시할 수 없습니다")).toBeTruthy();
    // "로드 실패"만 적으면 고칠 곳을 알 수 없다 — 콘솔 도메인 등록을 가리켜야 한다.
    expect(screen.getByText(/도메인이 등록됐는지/)).toBeTruthy();
    s.restore();
  });

  /**
   * 200 으로 왔지만 SDK 가 아닌 경우. 예전 코드는 onload 에서 곧장
   * `window.kakao.maps.load(...)` 를 불러 TypeError 를 던졌고, 그 예외는 Promise 를
   * 이행도 거부도 하지 못했다 — `ready` 도 `error` 도 영원히 그대로라 지도는 **빈 회색
   * 화면**으로 남고 아무 메시지도 뜨지 않았다. 그 무한 대기를 여기서 막는다.
   */
  it("SDK 가 아닌 응답이 200 으로 와도 영원히 기다리지 않고 상황을 말한다", async () => {
    kakao.restore();
    const s = interceptScript();
    render(<MapView onBoundsChange={vi.fn()} items={[]} />);

    await waitFor(() => expect(s.appended.length).toBe(1));
    // window.kakao 가 정의되지 않은 채 load 이벤트만 온 상태 = 오류 본문을 받은 경우
    s.appended[0].onload?.(new Event("load"));

    expect(await screen.findByText("지도를 표시할 수 없습니다")).toBeTruthy();
    expect(screen.getByText(/올바르지 않습니다/)).toBeTruthy();
    s.restore();
  });

  /**
   * 로더는 첫 줄에서 `window.kakao.maps = {}` 를 만들고 본체는 나중에 채운다.
   * 그 사이에 재마운트되면(조건 화면 ↔ 지도 왕복) 예전 코드는 `window.kakao?.maps` 가
   * 참이라는 이유로 곧장 `new kakao.maps.Map(...)` 을 불러 터졌다.
   */
  /**
   * 사용자 제보의 모호한 절반 — "결과는 뜨는데 지도가 안 움직인다".
   *
   * 지도가 아직 안 만들어진 동안에도 검색 상자는 이미 화면에 있다. 그때 결과를 누르면
   * 예전 `moveTo` 는 `if (!map) return;` 으로 **아무 일도 하지 않았다.** 무반응은
   * 사용자에게 "내가 잘못 눌렀나"로 읽힌다 — 못 옮기면 못 옮긴다고 말해야 한다.
   */
  it("지도가 준비되기 전에 결과를 고르면, 무반응 대신 못 옮겼다고 말한다", async () => {
    kakao.restore();
    const s = interceptScript();
    render(<MapView onBoundsChange={vi.fn()} items={[]} />);
    await waitFor(() => expect(s.appended.length).toBe(1));

    // 지도 본체는 아직 안 왔지만(스크립트 미완료 → mapRef 는 null) 검색은 쓸 수 있는 상태.
    (window as unknown as { kakao: unknown }).kakao = {
      maps: {
        services: {
          Places: class {
            keywordSearch(_kw: string, cb: (d: unknown, st: string, p: unknown) => void) {
              cb([{ id: "1", place_name: "강남역", address_name: "역삼동", x: "127.0279", y: "37.4971" }], "OK", {});
            }
          },
          Status: { OK: "OK", ZERO_RESULT: "ZERO_RESULT", ERROR: "ERROR" },
        },
      },
    };

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("장소·역 검색"), "강남역");
    await user.click(screen.getByRole("button", { name: "찾기" }));
    await user.click(await screen.findByRole("button", { name: /강남역/ }));

    expect(await screen.findByText(/이동할 수 없습니다/)).toBeTruthy();

    s.restore();
    delete (window as unknown as { kakao?: unknown }).kakao;
  });

  it("로더만 실행된 상태(본체 로드 중)에서는 스크립트를 또 붙이지 않고 그 로드를 기다린다", async () => {
    kakao.restore();
    const s = interceptScript();
    const pending: Array<() => void> = [];
    // 로더가 막 실행된 모습 — maps 는 있지만 Map 은 아직 없다.
    (window as unknown as { kakao: unknown }).kakao = {
      maps: { load: (cb: () => void) => pending.push(cb) },
    };

    render(<MapView onBoundsChange={vi.fn()} items={[]} />);

    await waitFor(() => expect(pending.length).toBe(1));
    expect(s.appended.length).toBe(0); // 두 번째 <script> 를 붙이지 않았다
    s.restore();
    delete (window as unknown as { kakao?: unknown }).kakao;
  });
});
