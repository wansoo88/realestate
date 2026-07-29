// @vitest-environment jsdom
/**
 * 🔐 SR32-1 — **민감값이 URL 로 나가면 실패한다.**
 *
 * 무슨 일이 있었나
 * ----------------
 * 지도 조회가 이렇게 나갔다:
 *
 *     GET /api/v1/map/complexes?bbox=…&zoom=15&max_price_krw=1314310000
 *
 * `1314310000` 은 사용자가 화면에 친 숫자가 아니라 **AES-256-GCM 으로 암호화해 저장한
 * 자산·소득·대출을 복호화해 서버가 계산한 실구매 가능 금액**이다. URL 은 nginx·uvicorn
 * 접근 로그에 평문으로 쌓였고, 로테이션된 `realestate.access.log.2.gz` 가 0644(월드
 * 리더블)라 같은 서버의 다른 서비스 계정이 실제로 읽었다.
 *
 * 왜 아무도 못 봤나 — **파생값이라서.** 이름에 `cash`·`income` 이 없다. 코드 리뷰에서
 * "예산으로 지도를 좁힌다"는 지극히 정상적인 문장으로 읽힌다. 같은 일이 또 난다.
 *
 * 그래서 이 파일이 막는 것
 * ------------------------
 *  ① **실물 요청**을 본다. `api.*` 를 목으로 바꾸지 않고 `fetch` 를 가로채, 앱이 실제로
 *     만들어 낸 URL 문자열에서 단언한다(목을 보는 테스트는 목이 낡으면 같이 눈이 먼다).
 *  ② **이름이 아니라 값**으로 판정한다. `cap_krw`·`max_won`·`limit2` 어떤 이름으로 다시
 *     넣어도 걸린다 — 이 앱의 정상 쿼리 값은 전부 1천만 미만이기 때문이다.
 *  ③ **앱이 그 값을 실제로 알고 있는 상태**에서 검사한다. 화면에 "13.14억"이 떠 있는데도
 *     URL 엔 없다는 것까지 확인한다. 그러지 않으면 "아무 데이터도 없어서 통과"가 된다.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Authenticated } from "../App";
import { api, buildQuery, setAccessToken } from "../api/client";
import { forgetCamera } from "../lib/mapCamera";
import { installKakaoStub, type KakaoStubHandle } from "./kakaoStub";

/* ── 이 사용자의 민감값 (사고 당시 실제 값을 그대로 쓴다) ───────────────────── */

const CASH_KRW = 300_000_000;
const INCOME_KRW = 90_000_000;
const EXISTING_LOAN_KRW = 120_000_000;
/** ★ 실제로 URL 로 샜던 값. 자산·소득·대출을 복호화해 계산한 파생값이다. */
const MAX_PURCHASE_KRW = 1_314_310_000;
/** 사용자가 슬라이더로 정한 값. 파생값은 아니지만 **이것도 URL 에 싣지 않는다**. */
const TARGET_PRICE_KRW = 900_000_000;
const COMPLEX_PRICE_KRW = 1_420_000_000;

const SECRETS: Array<[string, number]> = [
  ["보유 현금", CASH_KRW],
  ["연 소득", INCOME_KRW],
  ["기존 대출", EXISTING_LOAN_KRW],
  ["실구매 가능 금액(파생값)", MAX_PURCHASE_KRW],
  ["희망 매매가", TARGET_PRICE_KRW],
  ["단지 시세", COMPLEX_PRICE_KRW],
];

/** 쿼리에 실릴 수 있는 정상 숫자(좌표·줌·㎡·연도·id·상한)는 전부 이보다 작다. */
const MONEYISH = 10_000_000;

/** 금액성 파라미터 이름. `budget=mine` 같은 플래그는 금액이 아니므로 여기 없다. */
const MONEY_KEY = /krw|price|cash|income|loan|asset|salary|deposit|net_?worth|budget_/i;

/* ── fetch 스텁 — **여기가 유일한 경계**. api.* 는 목으로 바꾸지 않는다 ────────── */

function jsonResponse(status: number, body: unknown): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => body,
  } as unknown as Response;
}

interface Sent {
  url: string;
  method: string;
  body: string | null;
}

function installFetchStub(): Sent[] {
  const sent: Sent[] = [];

  const handler = async (input: unknown, init: RequestInit = {}): Promise<Response> => {
    const url = String(input);
    const method = (init.method ?? "GET").toUpperCase();
    sent.push({ url, method, body: typeof init.body === "string" ? init.body : null });

    const path = url.split("?")[0];

    if (path.endsWith("/me/profile")) {
      return jsonResponse(200, {
        cash_krw: CASH_KRW,
        income_krw: INCOME_KRW,
        existing_loan_krw: EXISTING_LOAN_KRW,
        owned_houses: 0,
        household_size: 3,
      });
    }
    if (path.endsWith("/me/preferences")) {
      return jsonResponse(200, {
        prefer: { built_after: 2010, target_price_krw: TARGET_PRICE_KRW },
        avoid: {},
        weights: {},
      });
    }
    if (path.endsWith("/affordability")) {
      return jsonResponse(200, {
        max_purchase_krw: MAX_PURCHASE_KRW,
        breakdown: {
          own_cash_krw: CASH_KRW,
          max_loan_krw: 1_014_310_000,
          binding_constraint: "DSR",
        },
        acquisition_cost_krw: { tax: 0, brokerage: 0, registration: 0, total: 0 },
        assumptions: [],
        evidence: [],
        warnings: [],
        disclaimer: "실제 한도는 금융기관 심사에 따라 달라집니다.",
      });
    }
    if (path.endsWith("/map/complexes")) {
      return jsonResponse(200, {
        level: "complex",
        note: "",
        items: [
          {
            id: 7,
            name: "가나아파트",
            point: [126.978, 37.5665],
            households: 500,
            built_year: 2005,
            recent_price_krw: COMPLEX_PRICE_KRW,
            price_as_of: "2026-06-30",
            price_area_m2: 84.97,
            price_confidence: "estimated",
            active_listings: 0,
            over_budget: false,
          },
        ],
      });
    }
    if (path.endsWith("/me/listings")) {
      return jsonResponse(200, {
        items: [],
        summary: {
          total: 0,
          fresh: 0,
          aging: 0,
          stale: 0,
          inactive: 0,
          eligible_for_recommendation: 0,
        },
        notes: [],
      });
    }
    if (path.includes("/recommendations")) {
      return method === "POST"
        ? jsonResponse(202, { job_id: "rec_01J", status: "queued" })
        : jsonResponse(200, { job_id: "rec_01J", status: "done", items: [] });
    }
    if (path.endsWith("/admin/users")) {
      // 관리자가 아님 — 서버는 403 이 아니라 404 를 준다(api-spec §6.2)
      return jsonResponse(404, { detail: { code: "UNKNOWN", message: "요청이 실패했습니다" } });
    }
    return jsonResponse(404, { detail: { code: "NOT_FOUND", message: "없음" } });
  };

  vi.stubGlobal("fetch", vi.fn(handler));
  return sent;
}

/* ── 단언 ────────────────────────────────────────────────────────────────── */

/** 이 URL 의 **쿼리 문자열**에 금액이 있는가. 본문(body)은 검사하지 않는다 — 접근 로그에 남는 건 URL 이다. */
function expectNoMoneyInQuery(url: string): void {
  const parsed = new URL(url, "http://localhost");

  for (const [name, secret] of SECRETS) {
    expect(
      parsed.search.includes(String(secret)),
      `URL 쿼리에 ${name}(${secret}) 이 그대로 실렸다: ${parsed.pathname}`,
    ).toBe(false);
  }

  for (const [key, value] of parsed.searchParams) {
    expect(MONEY_KEY.test(key), `금액성 파라미터 이름 "${key}" (${parsed.pathname})`).toBe(false);

    const n = Number(value);
    if (!Number.isFinite(n)) continue;

    expect(
      Math.abs(n) >= MONEYISH,
      `쿼리 "${key}" 값이 금액으로 보인다 (${parsed.pathname}) — 접근 로그에 평문으로 남는다`,
    ).toBe(false);

    // 단위를 바꿔 우회하는 경우(화면 입력은 **만원** 단위다) — 1.31억을 13143.1 로 보내도 잡는다.
    for (const [name, secret] of SECRETS) {
      for (const [unit, divisor] of [["만원", 10_000], ["억", 100_000_000]] as const) {
        expect(
          n === secret / divisor,
          `쿼리 "${key}" 가 ${name}을 ${unit} 단위로 실었다 (${parsed.pathname})`,
        ).toBe(false);
      }
    }
  }
}

/* ── 시나리오 ────────────────────────────────────────────────────────────── */

// jsdom 은 `scrollIntoView` 를 구현하지 않는다(App.test.tsx 와 같은 이유로 채워 준다).
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}

let kakao: KakaoStubHandle | null = null;

beforeEach(() => {
  setAccessToken("test-access-token");
  kakao = installKakaoStub();
});

afterEach(() => {
  cleanup();
  kakao?.restore();
  kakao = null;
  forgetCamera();
  setAccessToken(null);
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("실물 요청 URL 에 민감값이 없다 (SR32-1)", () => {
  it("지도·자금·내 매물·추천을 한 바퀴 도는 동안 어떤 URL 에도 금액이 없다", async () => {
    const sent = installFetchStub();
    const user = userEvent.setup();
    render(<Authenticated />);

    // ① 지도 — 예전에 max_price_krw 가 실려 나가던 바로 그 요청
    await screen.findByText("가나아파트");

    // ② 단지를 골라 자금계획을 돌린다(= 서버가 한도를 다시 계산해 화면에 온다)
    await user.click(screen.getByText("가나아파트"));

    // ③ 그 단지의 "내 매물"(complex_id 쿼리를 만드는 경로)
    await user.click(await screen.findByRole("button", { name: "가나아파트 호가 입력" }));
    await screen.findByRole("form", { name: "이 단지에서 본 호가 적기" });

    // ④ AI 추천(POST 본문 + 폴링 경로)
    await user.click(screen.getByRole("button", { name: "← 목록으로" }));
    await user.click(await screen.findByRole("tab", { name: "AI 추천" }));
    await user.click(screen.getByRole("button", { name: "AI 추천 실행" }));
    await waitFor(() => expect(sent.some((s) => s.method === "POST")).toBe(true));

    /* ── 이 테스트가 헛돌지 않는다는 증거 ────────────────────────────────
       ⓐ 실제로 요청이 여러 건 나갔고 지도 조회가 그중에 있다.
       ⓑ 앱은 민감값을 **알고 있다**(화면에 희망가 9억 칩이 떠 있다).
       둘을 확인하지 않으면 "아무 일도 안 일어나서 통과"를 통과라고 부르게 된다. */
    const mapCalls = sent.filter((s) => s.url.includes("/map/complexes"));
    expect(mapCalls.length).toBeGreaterThan(0);
    expect(sent.some((s) => s.url.includes("/affordability") && s.method === "POST")).toBe(true);
    expect(screen.getByRole("button", { name: "희망가 9.00억 초과 표시" })).toBeTruthy();

    // ⓒ 그리고 **모든** URL 에 금액이 없다.
    for (const { url } of sent) expectNoMoneyInQuery(url);
  });

  it("예산 조건은 **플래그**로 나간다 — 서버가 저장된 프로필로 상한을 만든다", async () => {
    const sent = installFetchStub();
    render(<Authenticated />);
    await screen.findByText("가나아파트");

    const last = sent.filter((s) => s.url.includes("/map/complexes")).at(-1)!;
    const q = new URL(last.url, "http://localhost").searchParams;

    // 조건이 사라진 게 아니다 — 금액 대신 "내 예산 기준"이라는 사실만 보낸다.
    expect(q.get("budget")).toBe("mine");
    expect(q.get("bbox")).toMatch(/^-?[\d.]+,-?[\d.]+,-?[\d.]+,-?[\d.]+$/);
    expect(q.get("zoom")).toBeTruthy();
    // 예전 이름이 되살아나면 여기서 잡힌다(값 검사와 별개로 이름도 못박는다).
    expect(q.has("max_price_krw")).toBe(false);
  });

  /**
   * `purpose` 는 **URL 로 나가도 되는 값**이다 — 그리고 나가야 한다.
   *
   * 금액도, 자산으로 되짚을 수 있는 파생값도 아닌 열거값(`live`|`invest`)이라 SR32-1
   * 규칙의 대상이 아니다. 반대로 **안 보내면** 서버는 live 로 한도를 계산하는데 자금
   * 패널이 invest 로 계산하고 있을 수 있고, 그러면 같은 단지가 지도에서는 "예산 초과",
   * 자금계획에서는 "가능"이 된다(목적에 따라 대출 절대한도·스트레스 가산이 **달라질 수
   * 있다** — 다만 오늘 운영 데이터에는 목적별 규칙이 0개라 두 한도가 같다, CR38-4).
   */
  it("`purpose` 는 열거값이라 URL 로 나간다 — 금액 관문을 그대로 통과한다", async () => {
    const sent = installFetchStub();
    render(<Authenticated />);
    await screen.findByText("가나아파트");

    const last = sent.filter((s) => s.url.includes("/map/complexes")).at(-1)!;
    const q = new URL(last.url, "http://localhost").searchParams;

    expect(q.get("purpose")).toBe("live");
    // 값 자체가 금액 검사를 자극하지 않는다(숫자가 아니다)
    expect(Number.isFinite(Number(q.get("purpose")))).toBe(false);
    // 그리고 이 요청 전체는 여전히 금액이 없다
    expectNoMoneyInQuery(last.url);
  });

  it("자금계획은 **본문**으로 보낸다 — 본문은 접근 로그에 남지 않는다", async () => {
    const sent = installFetchStub();
    const user = userEvent.setup();
    render(<Authenticated />);
    await screen.findByText("가나아파트");
    await user.click(screen.getByText("가나아파트"));

    await waitFor(() =>
      expect(
        sent.some((s) => s.url.includes("/affordability") && (s.body ?? "").includes("complex_id")),
      ).toBe(true),
    );
    // 금액이 아니라 단지 id 를 보낸다(CR35-4). 그마저도 URL 이 아니라 본문이다.
    const call = sent.filter((s) => s.url.includes("/affordability")).at(-1)!;
    expect(call.method).toBe("POST");
    expect(call.url).not.toContain("?");
  });
});

/* ─────────────────────────────────────────────────────────────────────────
 * 조립부 자체 — 화면을 거치지 않고 **문(gate)** 을 직접 두드린다.
 * 위 시나리오는 "지금 코드가 안 샌다"를 보고, 여기는 "새려고 하면 막힌다"를 본다.
 * ───────────────────────────────────────────────────────────────────────── */

describe("쿼리 조립부가 금액을 거부한다", () => {
  it("이름으로 걸린다 — 옛 파라미터를 되살리면 던진다", () => {
    expect(() => buildQuery({ bbox: "1,2,3,4", max_price_krw: MAX_PURCHASE_KRW })).toThrow(
      /max_price_krw/,
    );
  });

  it("이름을 바꿔도 값의 크기로 걸린다 — 이번 사고가 '이름이 안 수상해서' 났다", () => {
    expect(() => buildQuery({ cap: MAX_PURCHASE_KRW })).toThrow(/금액/);
    expect(() => buildQuery({ x: String(MAX_PURCHASE_KRW) })).toThrow(/금액/);
  });

  it("오류 메시지에 값을 담지 않는다 — 콘솔·오류수집기로 옮겨 심으면 같은 사고다", () => {
    try {
      buildQuery({ cap: MAX_PURCHASE_KRW });
      expect.unreachable("던졌어야 한다");
    } catch (e) {
      expect(String((e as Error).message)).not.toContain(String(MAX_PURCHASE_KRW));
    }
  });

  it("정상 파라미터는 그대로 통과한다(과잉 차단으로 기능을 죽이지 않는다)", () => {
    expect(
      buildQuery({
        bbox: "126.9,37.5,127.1,37.6",
        zoom: 15,
        budget: "mine",
        area_min_m2: 59,
        built_after: 2010,
        complex_id: 1234,
        limit: 100,
      }),
    ).toBe(
      "?bbox=126.9%2C37.5%2C127.1%2C37.6&zoom=15&budget=mine&area_min_m2=59&built_after=2010&complex_id=1234&limit=100",
    );
    // 보낼 게 없으면 물음표도 없다
    expect(buildQuery({ complex_id: null })).toBe("");
  });

  it("손으로 조립한 URL 도 나가기 직전에 걸린다(조립부를 우회해도 소용없다)", async () => {
    installFetchStub();
    // `api.recommendation` 은 경로를 그대로 받는다 — 여기로 새는 길을 막아 둔다.
    await expect(
      api.recommendation(`/recommendations/rec_1?max_price_krw=${MAX_PURCHASE_KRW}`),
    ).rejects.toThrow(/max_price_krw/);
    expect(fetch).not.toHaveBeenCalled();
  });
});

/* ─────────────────────────────────────────────────────────────────────────
 * 구조 — 쿼리를 만드는 곳이 늘어나면 위 검사가 닿지 않는 길이 생긴다.
 * ───────────────────────────────────────────────────────────────────────── */

describe("쿼리 조립은 한 곳에서만 한다", () => {
  /** 이 파일 자체가 아래 검사에 걸리지 않도록 조각으로 만든다(apiContract.test.ts 와 같은 이유). */
  const NEEDLE = ["URL", "Search", "Params"].join("");

  const SOURCES = import.meta.glob("../**/*.{ts,tsx}", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;

  it("api/client.ts 밖에서는 쿼리 문자열을 조립하지 않는다", () => {
    const offenders = Object.entries(SOURCES)
      .filter(([file]) => !file.includes(".test."))
      .filter(([, text]) => text.includes(NEEDLE))
      .map(([file]) => file);
    expect(offenders).toEqual(["../api/client.ts"]);
  });

  it("훑을 파일을 실제로 찾았다(glob 이 비면 위 검사는 늘 통과한다)", () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(50);
    expect(SOURCES["../api/client.ts"]).toContain("buildQuery");
  });
});
