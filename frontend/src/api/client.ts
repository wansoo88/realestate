/**
 * API 클라이언트.
 *
 * RN 앱으로 이식할 것을 전제로 **뷰에 의존하지 않게** 짠다(ux/README.md §10).
 * 토큰 수명·갱신·로그아웃 방송을 이 모듈이 전부 책임진다 — 화면은 subscribeAuth 로 듣기만 한다.
 *
 * 🔐 토큰 취급 원칙 (docs/02-design/security.md §2.1 — 어기면 보안 게이트 FAIL)
 *  - access token 은 **이 모듈의 메모리 변수에만** 둔다. localStorage/sessionStorage 금지.
 *    XSS 가 나도 피해가 "그 탭이 살아있는 동안"으로 한정되고, 새로고침하면 사라진다.
 *  - refresh token 은 **프론트가 아예 만지지 않는다.** 서버가 HttpOnly·Secure·SameSite=Strict
 *    쿠키로 내려주고 브라우저가 자동으로 실어 보낸다 → JS 로 읽을 수 없어 XSS 로 못 훔친다.
 *    그래서 이 파일에는 refresh 토큰을 담는 변수 자체가 없다.
 *  - 쿠키로 인증하는 요청(refresh·logout)에는 CSRF 2차 방어로 `X-Requested-With` 를 붙인다.
 *    커스텀 헤더가 붙은 요청은 단순요청이 아니라 크로스사이트 <form> 전송으로는 위조할 수 없다.
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

/** 로그인·갱신 공통 응답. refresh_token 은 **body 에 오지 않는다**(쿠키로 내려온다). */
export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
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

/** CSRF 2차 방어 — 쿠키로 인증하는 요청에 서버가 요구하는 헤더. */
const CSRF_HEADER = "X-Requested-With";
const CSRF_VALUE = "XMLHttpRequest";

/** refresh 쿠키가 오가야 하는 요청 옵션. 동일 오리진이지만 의도를 드러내려고 명시한다. */
const COOKIE_HEADERS: Record<string, string> = { [CSRF_HEADER]: CSRF_VALUE };

/* ─────────────────────────────────────────────────────────────────────────
 * 인증 상태 — 메모리 전용
 * ───────────────────────────────────────────────────────────────────────── */

/** ⚠️ 이 변수 밖으로 access token 을 내보내지 않는다(저장소·URL·로그 금지). */
let accessToken: string | null = null;

/** 앱 시작 세션 복원(restoreSession)이 끝났는지. 끝나기 전엔 화면이 판단을 보류한다. */
let sessionChecked = false;

export interface AuthState {
  /** access token 을 들고 있는가 */
  authenticated: boolean;
  /** 세션 복원 시도가 끝났는가 — false 면 "아직 모름"(로그인 화면을 띄우면 안 된다) */
  checked: boolean;
}

type AuthListener = (state: AuthState) => void;
const listeners = new Set<AuthListener>();

export function getAuthState(): AuthState {
  return { authenticated: accessToken !== null, checked: sessionChecked };
}

export function isAuthenticated(): boolean {
  return accessToken !== null;
}

/** 로그아웃·토큰만료를 화면이 알아채도록 한 곳에서 방송한다(401 처리를 화면마다 흩뿌리면 반드시 어긋난다). */
export function subscribeAuth(fn: AuthListener): () => void {
  listeners.add(fn);
  return () => void listeners.delete(fn);
}

/**
 * 상태 변화는 반드시 이 한 곳을 지난다(CR18-3: 인증 상태와 화면이 어긋나지 않게).
 * 구독자 하나가 예외를 던져도 나머지에게는 반드시 도달해야 한다.
 */
function emitAuth(): void {
  const state = getAuthState();
  for (const fn of [...listeners]) {
    try {
      fn(state);
    } catch {
      /* 구독자 오류가 방송 자체를 막지 않게 삼킨다 */
    }
  }
}

/**
 * access token 교체 — **메모리에만** 쓴다.
 * 외부 공개 이유: RN 이식(동일 흐름 재사용)과 테스트에서 초기 상태를 만들기 위함.
 */
export function setAccessToken(token: string | null): void {
  accessToken = token;
  emitAuth();
}

/** 서버 호출 없이 이 기기의 세션만 폐기(refresh 실패처럼 이미 서버 세션이 없는 경우). */
function clearSession(): void {
  // 진행 중인 refresh 가 나중에 성공해 세션을 되살리지 못하게 끊는다.
  refreshInFlight = null;
  setAccessToken(null);
}

/* ─────────────────────────────────────────────────────────────────────────
 * 전송
 * ───────────────────────────────────────────────────────────────────────── */

async function raw<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  // access token 은 매 요청에 자동 첨부. 값은 어떤 경로로도 로그에 남기지 않는다.
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

/** refresh 요청은 동시에 1개만 — 공유되는 Promise. */
let refreshInFlight: Promise<string> | null = null;

/**
 * refresh **쿠키**로 access 를 재발급받는다. 요청 body 는 없다.
 *
 * **single-flight**(CR18-2): 동시 요청 N 개가 한꺼번에 401 을 받아도 refresh 는 1회만 나간다.
 * 서버가 refresh 쿠키를 회전시키므로, 병렬로 쏘면 뒤늦은 요청이 이미 회전된 쿠키를 들고 가
 * 401 → 멀쩡한 세션이 끊긴다.
 */
function refreshAccess(): Promise<string> {
  if (refreshInFlight) return refreshInFlight;

  const p: Promise<string> = raw<TokenResponse>("/auth/refresh", {
    method: "POST", // body 없음 — 자격증명은 쿠키뿐이다
    credentials: "include",
    headers: COOKIE_HEADERS,
  })
    .then((t) => {
      // 기다리는 사이 로그아웃/세션폐기가 있었으면 결과를 버린다(끝난 세션 부활 방지).
      if (refreshInFlight !== p) {
        throw new ApiException(401, { code: "UNAUTHORIZED", message: "세션이 종료되었습니다." });
      }
      setAccessToken(t.access_token);
      return t.access_token;
    })
    .finally(() => {
      // 내가 건 것만 푼다(이미 다음 refresh 가 시작됐을 수 있다).
      if (refreshInFlight === p) refreshInFlight = null;
    });

  refreshInFlight = p;
  return p;
}

/**
 * 401 이면 refresh 로 **한 번만** 재시도한다.
 * refresh 가 실패하거나 재시도도 401 이면 로그아웃 상태로 방송한다(FE-1 §3).
 * 화면은 subscribeAuth 로 이를 듣고 로그인 게이트로 전환한다.
 */
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  try {
    return await raw<T>(path, init);
  } catch (e) {
    if (!(e instanceof ApiException) || e.status !== 401) throw e;

    try {
      await refreshAccess();
    } catch {
      clearSession(); // refresh 쿠키가 없거나 만료 = 세션 종료
      throw e;
    }

    try {
      return await raw<T>(path, init);
    } catch (e2) {
      if (e2 instanceof ApiException && e2.status === 401) clearSession();
      throw e2;
    }
  }
}

/* ─────────────────────────────────────────────────────────────────────────
 * 세션 수명주기
 * ───────────────────────────────────────────────────────────────────────── */

/**
 * 앱 시작 시 1회 — 새로고침 세션 복원.
 *
 * 프론트는 refresh 토큰을 볼 수 없으므로 "저장된 토큰을 읽어 복원"이 존재하지 않는다.
 * 대신 refresh 쿠키가 아직 살아 있는지 서버에 물어본다. 401 이면 미인증으로 확정 → 로그인 화면.
 */
export async function restoreSession(): Promise<boolean> {
  try {
    await refreshAccess();
    return true;
  } catch {
    accessToken = null;
    return false;
  } finally {
    sessionChecked = true;
    emitAuth(); // 성공/실패 무관하게 "판단 끝"을 반드시 방송한다
  }
}

/**
 * 명시적 로그아웃 — 서버가 refresh 쿠키를 지우고(우리는 못 지운다), 우리는 메모리를 비운다.
 * 서버 호출이 실패해도 이 기기에서는 반드시 로그아웃 상태가 된다.
 *
 * 크로스탭: 쿠키는 탭끼리 공유되므로 다른 탭도 다음 refresh 에서 401 → 자동 로그아웃된다.
 */
export async function logout(): Promise<void> {
  try {
    await raw<void>("/auth/logout", {
      method: "POST",
      credentials: "include",
      headers: COOKIE_HEADERS,
    });
  } catch {
    /* 네트워크·서버 오류여도 로컬 폐기는 진행한다 */
  } finally {
    clearSession();
  }
}

/* ─────────────────────────────────────────────────────────────────────────
 * 엔드포인트
 * ───────────────────────────────────────────────────────────────────────── */

export const api = {
  /** 로그인 — access 는 메모리로, refresh 는 서버가 HttpOnly 쿠키로 심는다(body 에 없다). */
  async login(email: string, password: string): Promise<TokenResponse> {
    const t = await raw<TokenResponse>("/auth/login", {
      method: "POST",
      credentials: "include", // Set-Cookie(refresh) 수신
      body: JSON.stringify({ email, password }),
    });
    setAccessToken(t.access_token);
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
