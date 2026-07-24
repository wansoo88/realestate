/**
 * API 클라이언트.
 *
 * RN 앱으로 이식할 것을 전제로 **뷰에 의존하지 않게** 짠다(ux/README.md §10).
 * 토큰은 메모리에 두고, 갱신은 이 모듈이 책임진다.
 */

export interface ApiError {
  code: string;
  message: string;
  problems?: string[];
}

export class ApiException extends Error {
  constructor(public status: number, public error: ApiError) {
    super(error.message);
    this.name = "ApiException";
  }
}

export interface ComplexItem {
  id: number;
  name: string;
  point: [number, number];
  households: number | null;
  built_year: number | null;
  recent_price_krw: number | null;
  price_as_of: string | null;
  price_confidence: "estimated" | "unknown";
  active_listings: number;
  over_budget: boolean;
}

export interface ClusterItem {
  region_code: string;
  count: number;
  center: [number, number];
  median_price_krw: number | null;
}

export type MapResponse =
  | { level: "complex"; items: ComplexItem[]; note: string }
  | { level: "cluster"; items: ClusterItem[] };

export interface AffordabilityResponse {
  max_purchase_krw: number;
  breakdown: {
    own_cash_krw: number;
    max_loan_krw: number;
    binding_constraint: "LTV" | "DSR" | "DTI" | "CASH";
  };
  acquisition_cost_krw: { tax: number; brokerage: number; registration: number; total: number };
  assumptions: string[];
  evidence: Array<{ claim: string; source: string; as_of?: string }>;
  warnings: string[];
  disclaimer: string;
}

const BASE = "/api/v1";

let accessToken: string | null = null;
let refreshToken: string | null = null;

export function setTokens(access: string | null, refresh: string | null): void {
  accessToken = access;
  refreshToken = refresh;
}

export function isAuthenticated(): boolean {
  return accessToken !== null;
}

async function raw<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (res.status === 204) return undefined as T;

  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (body as Record<string, unknown>).detail ?? body;
    const err: ApiError =
      typeof detail === "object" && detail !== null && "code" in detail
        ? (detail as unknown as ApiError)
        : { code: "UNKNOWN", message: `요청이 실패했습니다 (${res.status})` };
    throw new ApiException(res.status, err);
  }
  return body as T;
}

/** 401 이면 refresh 로 한 번 재시도한다. 그래도 실패하면 로그아웃 상태로 만든다. */
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  try {
    return await raw<T>(path, init);
  } catch (e) {
    if (!(e instanceof ApiException) || e.status !== 401 || !refreshToken) throw e;

    try {
      const tokens = await raw<{ access_token: string; refresh_token: string }>(
        "/auth/refresh",
        { method: "POST", body: JSON.stringify({ refresh_token: refreshToken }) },
      );
      setTokens(tokens.access_token, tokens.refresh_token);
    } catch {
      setTokens(null, null);
      throw e;
    }
    return raw<T>(path, init);
  }
}

export const api = {
  async login(email: string, password: string) {
    const t = await raw<{ access_token: string; refresh_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setTokens(t.access_token, t.refresh_token);
    return t;
  },

  register(email: string, password: string) {
    return raw<{ user_id: number }>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  mapComplexes(params: {
    bbox: string;
    zoom: number;
    max_price_krw?: number;
    built_after?: number;
  }) {
    const q = new URLSearchParams({ bbox: params.bbox, zoom: String(params.zoom) });
    if (params.max_price_krw) q.set("max_price_krw", String(params.max_price_krw));
    if (params.built_after) q.set("built_after", String(params.built_after));
    return request<MapResponse>(`/map/complexes?${q}`);
  },

  affordability(body: Record<string, unknown> = {}) {
    return request<AffordabilityResponse>("/affordability", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  putProfile(body: Record<string, number>) {
    return request<Record<string, number>>("/me/profile", {
      method: "PUT",
      body: JSON.stringify(body),
    });
  },
};
