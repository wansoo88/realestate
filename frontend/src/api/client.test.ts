/**
 * 인증 흐름 테스트 (FE-1 재작업) — **새 계약** 기준.
 *
 * 계약 요약:
 *  - access token 은 응답 body 로 오고 **메모리에만** 산다.
 *  - refresh token 은 프론트가 만지지 않는다(HttpOnly 쿠키) → 요청 body 에 실리지 않는다.
 *  - refresh·logout 은 `X-Requested-With` + `credentials: "include"`.
 *
 * 네트워크는 fetch 목으로만 다룬다(실제 서버·브라우저 전역 비의존).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiException,
  api,
  getAuthState,
  isAuthenticated,
  logout,
  restoreSession,
  setAccessToken,
  subscribeAuth,
} from "./client";

function res(status: number, body: unknown) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => body,
  } as unknown as Response;
}

const UNAUTHORIZED = { detail: { code: "UNAUTHORIZED", message: "만료" } };
const TOKENS = (access: string) => ({
  access_token: access,
  token_type: "bearer",
  expires_in: 1800,
});

function initOf(call: unknown[]): RequestInit {
  return (call[1] ?? {}) as RequestInit;
}
function headerOf(call: unknown[], name: string): string | null {
  return (initOf(call).headers as Headers | undefined)?.get(name) ?? null;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  setAccessToken(null); // 매 테스트 미인증에서 시작
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals(); // 테스트가 중간에 실패해도 저장소 스텁이 새지 않게
});

describe("토큰 자동 첨부", () => {
  it("인증 상태면 모든 요청에 Authorization: Bearer 를 붙인다", async () => {
    setAccessToken("a1");
    fetchMock.mockResolvedValueOnce(res(200, { level: "complex", items: [], note: "" }));

    await api.mapComplexes({ bbox: "1,2,3,4", zoom: 15 });

    expect(headerOf(fetchMock.mock.calls[0], "Authorization")).toBe("Bearer a1");
  });
});

describe("SR15-1 회귀 — 토큰은 저장소에 절대 쓰지 않는다", () => {
  it("로그인·갱신·로그아웃 어느 단계에서도 localStorage/sessionStorage 를 건드리지 않는다", async () => {
    // 실제 브라우저 저장소를 흉내 낸 스파이를 심어 두고, 단 한 번도 호출되지 않음을 단언한다.
    const spy = () => ({ getItem: vi.fn(), setItem: vi.fn(), removeItem: vi.fn(), clear: vi.fn() });
    const local = spy();
    const session = spy();
    vi.stubGlobal("localStorage", local);
    vi.stubGlobal("sessionStorage", session);

    fetchMock
      .mockResolvedValueOnce(res(200, TOKENS("a1"))) // login
      .mockResolvedValueOnce(res(200, TOKENS("a2"))) // refresh
      .mockResolvedValueOnce(res(204, null)); // logout

    await api.login("me@example.com", "password12345");
    await restoreSession();
    await logout();

    for (const store of [local, session]) {
      expect(store.setItem).not.toHaveBeenCalled();
      expect(store.getItem).not.toHaveBeenCalled();
    }
  });
});

describe("login", () => {
  it("access 를 메모리에 넣고 인증 상태를 방송한다", async () => {
    let authed = false;
    const unsub = subscribeAuth((s) => (authed = s.authenticated));
    fetchMock.mockResolvedValueOnce(res(200, TOKENS("a9")));

    await api.login("me@example.com", "password12345");

    expect(isAuthenticated()).toBe(true);
    expect(authed).toBe(true);
    unsub();
  });

  it("쿠키(refresh)를 받아야 하므로 credentials: include 로 보낸다", async () => {
    fetchMock.mockResolvedValueOnce(res(200, TOKENS("a9")));

    await api.login("me@example.com", "password12345");

    expect(initOf(fetchMock.mock.calls[0]).credentials).toBe("include");
  });
});

describe("refresh 요청 형태", () => {
  it("body 없이 쿠키로만 인증하고, CSRF 헤더와 credentials 를 붙인다", async () => {
    fetchMock.mockResolvedValueOnce(res(200, TOKENS("a2")));

    await restoreSession();

    const call = fetchMock.mock.calls[0];
    expect(String(call[0])).toContain("/auth/refresh");
    expect(initOf(call).method).toBe("POST");
    expect(initOf(call).body).toBeUndefined(); // refresh_token 을 실어 보내지 않는다
    expect(initOf(call).credentials).toBe("include");
    expect(headerOf(call, "X-Requested-With")).toBe("XMLHttpRequest");
  });
});

describe("세션 복원 (restoreSession)", () => {
  it("refresh 쿠키가 살아 있으면 access 를 되찾고 인증 상태가 된다", async () => {
    fetchMock.mockResolvedValueOnce(res(200, TOKENS("fresh")));

    await expect(restoreSession()).resolves.toBe(true);
    expect(getAuthState()).toEqual({ authenticated: true, checked: true });
  });

  it("401 이면 미인증으로 확정하고, 확인이 끝났음을 알린다(로그인 화면 전환용)", async () => {
    const seen: Array<{ authenticated: boolean; checked: boolean }> = [];
    const unsub = subscribeAuth((s) => seen.push(s));
    fetchMock.mockResolvedValueOnce(res(401, UNAUTHORIZED));

    await expect(restoreSession()).resolves.toBe(false);

    expect(getAuthState()).toEqual({ authenticated: false, checked: true });
    expect(seen.at(-1)).toEqual({ authenticated: false, checked: true });
    unsub();
  });
});

describe("401 처리", () => {
  it("refresh 로 한 번 재시도하고, 새 토큰으로 원 요청을 다시 보낸다", async () => {
    setAccessToken("a1");
    fetchMock
      .mockResolvedValueOnce(res(401, UNAUTHORIZED))
      .mockResolvedValueOnce(res(200, TOKENS("a2")))
      .mockResolvedValueOnce(res(200, { level: "complex", items: [], note: "" }));

    const out = await api.mapComplexes({ bbox: "1,2,3,4", zoom: 15 });

    expect(out.level).toBe("complex");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(String(fetchMock.mock.calls[1][0])).toContain("/auth/refresh");
    expect(headerOf(fetchMock.mock.calls[2], "Authorization")).toBe("Bearer a2");
  });

  it("refresh 가 실패하면 세션을 폐기하고 로그아웃을 방송한다", async () => {
    setAccessToken("a1");
    let authed = true;
    const unsub = subscribeAuth((s) => (authed = s.authenticated));

    fetchMock
      .mockResolvedValueOnce(res(401, UNAUTHORIZED))
      .mockResolvedValueOnce(res(401, UNAUTHORIZED));

    await expect(api.mapComplexes({ bbox: "1,2,3,4", zoom: 15 })).rejects.toBeInstanceOf(
      ApiException,
    );
    expect(authed).toBe(false);
    expect(isAuthenticated()).toBe(false);
    unsub();
  });

  it("재시도까지 401 이면 로그아웃한다(무한 재시도 없음)", async () => {
    setAccessToken("a1");
    fetchMock
      .mockResolvedValueOnce(res(401, UNAUTHORIZED)) // 원 요청
      .mockResolvedValueOnce(res(200, TOKENS("a2"))) // refresh 성공
      .mockResolvedValueOnce(res(401, UNAUTHORIZED)); // 재시도도 401

    await expect(api.mapComplexes({ bbox: "1,2,3,4", zoom: 15 })).rejects.toBeInstanceOf(
      ApiException,
    );
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(isAuthenticated()).toBe(false);
  });

  it("CR18-2 회귀 — 동시 401 이 N 개여도 refresh 는 1회만 나간다(single-flight)", async () => {
    setAccessToken("stale");
    let refreshCalls = 0;

    fetchMock.mockImplementation(async (url: unknown, init: RequestInit = {}) => {
      if (String(url).includes("/auth/refresh")) {
        refreshCalls += 1;
        // 실제 네트워크처럼 지연을 준다 — 지연이 없으면 직렬 실행으로도 통과해버린다.
        await new Promise((r) => setTimeout(r, 10));
        return res(200, TOKENS("fresh"));
      }
      const bearer = (init.headers as Headers | undefined)?.get("Authorization");
      return bearer === "Bearer fresh"
        ? res(200, { level: "complex", items: [], note: "" })
        : res(401, UNAUTHORIZED);
    });

    const out = await Promise.all([
      api.mapComplexes({ bbox: "1,2,3,4", zoom: 15 }),
      api.mapComplexes({ bbox: "2,3,4,5", zoom: 15 }),
      api.mapComplexes({ bbox: "3,4,5,6", zoom: 15 }),
    ]);

    expect(refreshCalls).toBe(1); // ← 3회가 나가면 서버 쿠키 회전과 충돌한다
    expect(out.every((r) => r.level === "complex")).toBe(true);
    expect(isAuthenticated()).toBe(true);
  });
});

describe("logout", () => {
  it("서버에 쿠키 삭제를 요청하고(CSRF 헤더 포함) 메모리를 비운다", async () => {
    setAccessToken("a1");
    let authed = true;
    const unsub = subscribeAuth((s) => (authed = s.authenticated));
    fetchMock.mockResolvedValueOnce(res(204, null));

    await logout();

    const call = fetchMock.mock.calls[0];
    expect(String(call[0])).toContain("/auth/logout");
    expect(initOf(call).credentials).toBe("include");
    expect(headerOf(call, "X-Requested-With")).toBe("XMLHttpRequest");
    expect(isAuthenticated()).toBe(false);
    expect(authed).toBe(false);
    unsub();
  });

  it("서버 호출이 실패해도 이 기기에서는 반드시 로그아웃된다", async () => {
    setAccessToken("a1");
    fetchMock.mockRejectedValueOnce(new Error("network down"));

    await expect(logout()).resolves.toBeUndefined();
    expect(isAuthenticated()).toBe(false);
  });
});
