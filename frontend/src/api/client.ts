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
  /** 서버가 사유를 함께 줄 때만 채워진다(현재 로그인 403 에는 오지 않는다). */
  reason?: string | null;
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

/**
 * 가입 **접수** 응답 (201). 계정은 만들어지지만 `pending` 이라 아직 로그인할 수 없다.
 * 그래서 가입 성공 후 자동 로그인을 이어 붙이면 안 된다 — 바로 403 을 받는다.
 */
export interface RegisterResponse {
  user_id: number;
  status: string;
  message: string;
}

/** 승인되지 않은 계정에 서버가 주는 403 코드 (api-spec §1.5). */
export type ApprovalCode = "PENDING_APPROVAL" | "ACCOUNT_REJECTED";

export function isApprovalCode(code: string | undefined): code is ApprovalCode {
  return code === "PENDING_APPROVAL" || code === "ACCOUNT_REJECTED";
}

/* ── 관리자 (가입 승인) ───────────────────────────────────────────────────
 * ⚠️ 목록 항목을 `unknown` 으로 둔 것은 실수가 아니다.
 * 서버가 실수로 자산·소득·해시를 흘리더라도 화면이 그걸 그대로 렌더할 수 없게,
 * **반드시 `lib/adminUsers.sanitizeAdminUsers`(허용 목록)를 거치도록** 타입으로 강제한다. */

export interface AdminUserListResponse {
  items: unknown[];
  /** 승인된 관리자 수 — 화면이 "마지막 관리자" 상황을 미리 설명할 수 있게 온다. */
  active_admins?: number;
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

/**
 * 자금계획 — **희망 매매가(`target_price_krw`)를 보냈을 때만** 응답에 실린다.
 *
 * "최대 얼마까지 살 수 있나"(max_purchase_krw)와 "이 집을 사려면 무엇이 필요한가"는
 * 다른 질문이다. 후자에만 답이 있는 값들이 여기 모인다: 부족한 현금·필요 대출·월 원리금.
 *
 * ⚠️ 계산은 **전부 서버**가 한다. 프론트는 표시만 — 여기서 다시 계산하면 진실이 두 개가 되고,
 *    금리·기간·세율이 바뀌는 날 둘이 조용히 어긋난다(useAffordability 주석과 같은 이유).
 */
export interface AffordabilityPlan {
  /** 이 계획이 어느 가격을 전제로 하는가 */
  target_price_krw: number;
  /** 매매가 + 부대비용 */
  total_needed_krw: number;
  cost_breakdown: { tax: number; brokerage: number; etc: number };
  own_cash_krw: number;
  /** 지금 현금으로 모자란 돈 */
  shortfall_krw: number;
  required_loan_krw: number;
  /** false 면 필요 대출이 한도를 넘는다. **그래도 숫자는 보여준다**(얼마가 더 필요한지가 답이다). */
  loan_feasible: boolean;
  loan_limit_krw: number;
  /** 한도 초과분. 불가능할 때만 온다. */
  over_limit_krw?: number | null;
  /** 무엇이 한도를 묶었나("DSR" 등) */
  binding_constraint?: string | null;
  monthly_payment_krw: number;
  total_interest_krw?: number | null;
  /** 월 상환액은 가정에 따라 크게 달라진다 — **숫자 옆에 반드시 함께 보여준다**(G2). */
  terms: { annual_rate_pct: number; years: number };
}

/** `/affordability` 요청. 지역은 보내지 않는다(CR10-1 — 서버가 판정한다). */
export interface AffordabilityRequest {
  purpose?: "live" | "invest";
  /** 희망 매매가. 주면 응답에 `plan` 이 함께 온다. */
  target_price_krw?: number;
}

export interface AffordabilityResponse {
  max_purchase_krw: number;
  /** 희망가를 보냈을 때만. 서버가 아직 이 계약을 배포하지 않았으면 없다. */
  plan?: AffordabilityPlan | null;
  breakdown: {
    own_cash_krw: number;
    max_loan_krw: number;
    /** 서버가 실제로 내려주는 키(원 단위 한도). api-spec 초안의 `*_pct` 가 아니다. */
    ltv_limit_krw?: number | null;
    dsr_limit_krw?: number | null;
    dti_limit_krw?: number | null;
    absolute_cap_krw?: number | null;
    binding_constraint: string;
  };
  acquisition_cost_krw: { tax: number; brokerage: number; registration: number; total: number };
  assumptions: string[];
  evidence: Array<{ claim: string; source: string; as_of?: string }>;
  warnings: string[];
  disclaimer: string;
}

/* ── 내 조건 (F2·F5) ─────────────────────────────────────────────────────
 * 🔐 이 두 타입의 값은 **메모리에만** 산다. 저장소·URL·로그 어디에도 쓰지 않는다.
 * (client.ts 상단 토큰 원칙과 같은 이유 — 개인 금융정보다) */

export interface Profile {
  cash_krw: number;
  income_krw: number;
  existing_loan_krw: number;
  owned_houses: number;
  household_size: number;
  /** 서버가 돌려주지만 아직 저장하지 않는 값(0 고정). 화면은 읽기만 한다. */
  existing_annual_repayment_krw?: number;
  existing_annual_interest_krw?: number;
}

/** 서버 `PreferencesIn` 은 열린 dict 다. 우리가 실제로 쓰는 키만 타입으로 못박는다. */
export interface Preferences {
  prefer: {
    school_district?: number | null;
    subway_within_m?: number | null;
    built_after?: number | null;
    min_households?: number | null;
    /** 지도 면적 필터. api-spec 예시엔 없지만 `prefer` 는 열린 dict 라 함께 보관한다. */
    area_min_m2?: number | null;
    area_max_m2?: number | null;
    /**
     * 희망 매매가(원). `prefer` 에 두는 이유: 서버 `PreferencesIn` 이 열린 dict 라
     * 마이그레이션 없이 저장되고, 자산(`/me/profile`)이 아니라 **취향**이기 때문이다
     * (현금·소득처럼 서버가 암호화해 다루는 사실 값이 아니다).
     * ⚠️ 저장만 되는 값이 되면 안 된다 — `/affordability` 의 `target_price_krw` 와
     *    추천의 `budget_override_krw` 로 **실제로 나간다**(App.tsx, 테스트가 고정).
     */
    target_price_krw?: number | null;
  };
  avoid: {
    first_floor?: boolean;
    main_road_noise?: boolean;
    redevelopment_early_stage?: boolean;
  };
  weights: { price?: number; location?: number; value?: number; risk?: number };
}

/* ── 추천 (F1·F3·F6) ─────────────────────────────────────────────────── */

export interface Evidence {
  claim?: string;
  source?: string;
  as_of?: string | null;
  source_url?: string | null;
  data_rows?: number | null;
}

export interface RiskNote {
  severity: string; // low | medium | high
  detail: string;
}

export interface Finding {
  agent_id: string;
  verdict: string;
  rationale: string;
  evidence: Evidence[];
  risks: RiskNote[];
  /** 점수를 매길 근거가 없으면 null. **0 과 다르다.** */
  score: number | null;
  confidence: number;
  basis: string | null;
  /** 판단 보류 사유(데이터 부족). 비어 있지 않으면 이 finding 은 "모른다"는 뜻이다. */
  missing: string[];
}

export interface PriceBand {
  p25_krw: number;
  median_krw: number;
  p75_krw: number;
  sample_size: number;
  period_months: number;
  expanded: boolean;
  source: string;
}

export interface DongValuation {
  available: boolean;
  method: string;
  basis?: string; // "trade_measured" 면 실측
  confidence: number;
  coverage_pct?: number | null;
  period_months?: number | null;
  reason?: string | null;
  note?: string | null;
  dongs?: Array<{
    dong: string;
    vs_complex_pct: number;
    sample: number;
    median_ppm_krw: number;
  }>;
}

/**
 * 축별 점수 반영 결과 (api-spec §5.3 · 서버 `scoring.py::AXIS_SPECS` 가 정본).
 *
 * 왜 이 구조가 통째로 오는가: 서버가 **근거 있는 축만** 총점에 넣고 나머지 가중치를
 * 재정규화하기 때문이다. 그 사실을 화면이 말하지 않으면 재정규화 자체가 거짓말이 된다 —
 * 사용자는 자기가 준 30%가 반영된 줄 안다.
 */
export interface ScoreAxis {
  axis: "price" | "location" | "value" | "risk" | string;
  label: string;
  agent_ids: string[];
  /** 무엇을 점수로 썼는지(사람이 읽는 설명) */
  signal: string;
  coverage: "full" | "partial" | string;
  /** partial 이면 **무엇이 빠졌는지**. 반영 여부와 무관하게 보여줘야 한다(계약). */
  coverage_gap: string | null;
  /** 사용자가 준 비중(정규화 후) */
  weight: number;
  /** 재정규화 후 실효 비중. 반영되지 않았으면 null. */
  applied_weight: number | null;
  /** 이 축의 점수. null = 근거 없음(0 이 아니다). */
  score: number | null;
  confidence?: number | null;
  detail?: string | null;
  status: "applied" | "no_signal" | "zero_weight" | "no_weights" | string;
  /** 근거가 없을 때 무엇이 없는지 */
  missing: string[];
}

export interface RecommendationItem {
  rank?: number;
  complex: { id: number; name: string };
  unit_type: { area_m2: number; type_name?: string | null } | null;
  building: { id?: number | null; name?: string | null; confidence?: number; basis?: string } | null;
  dong_valuation: DongValuation | null;
  /** 이 후보의 가격이 **호가**인지 **실거래 추정**인지. 화면은 반드시 구분해 표시한다. */
  price_basis: "listing" | "trade";
  /** 호가. `price_basis === "trade"` 면 **null** — est 로 대체 표시 금지. */
  ask_price_krw: number | null;
  est_price_krw: number | null;
  price_estimated: boolean;
  price_note: string | null;
  ask_gap_pct: number | null;
  price_band: PriceBand | null;
  /** null = "모른다". 0 으로 렌더링 금지. */
  total_score: number | null;
  /** `user_weighted`(사용자 가중치) | `agent_scores`(가중치 없어 폴백) | null.
   *  ⚠️ `agent_scores` 는 "가중치가 반영된 점수"가 **아니다** — 그렇게 표시하면 계약 위반. */
  score_basis: string | null;
  /** 사용자 가중치 중 실제로 반영된 비율(%). 100 미만이면 **부분 반영 표기 필수**(계약). */
  score_coverage_pct?: number | null;
  /** 축별 반영 결과. 서버가 안 줄 수도 있다(구버전) — 없으면 표시하지 않는다. */
  score_axes?: ScoreAxis[] | null;
  /** 이 후보에서 반영되지 못한 가중치 고지. 결과 전체 notes 와 **양쪽 다** 보여준다. */
  score_notes?: string[] | null;
  timing_signal: string;
  headline: string;
  why: string[];
  why_not: string[];
  next_actions: string[];
  findings: Finding[];
}

/** 왜 이 후보가 결과에 없는지. "왜 안 나왔지"에 답하는 자리다. */
export interface ExcludedCandidate {
  complex_id: number;
  complex_name?: string | null;
  price_basis?: string;
  price_estimated?: boolean;
  reason: string;
}

export interface RecommendationJob {
  job_id: string;
  status: string; // queued | running | done | error
  criteria_snapshot?: Record<string, unknown> | null;
  items: RecommendationItem[];
  /** 서버가 아직 안 내려줄 수 있다(러너는 계산하지만 저장 경로가 없음). 없으면 표시하지 않는다. */
  excluded?: ExcludedCandidate[] | null;
  notes?: string[] | null;
  progress?: { done: number; total: number; current_agent?: string | null } | null;
  disclaimer?: string;
}

export interface RecommendationAccepted {
  job_id: string;
  status: string;
  poll_url?: string;
  note?: string;
}

export interface RecommendationRequest {
  region_codes?: string[];
  /**
   * "이 주변" — 지도 범위 `minLon,minLat,maxLon,maxLat` (`/map/complexes` 와 **같은 형식**).
   * `region_codes` 와 함께 보내면 **교집합**이다. 형식이 깨지면 서버는 422 를 준다
   * (그래서 lib/searchScope 가 유효한 값만 싣는다).
   * ⚠️ 좌표가 없는 단지는 bbox 로 찾을 수 없어 후보에서 빠진다 — 서버가 `notes` 로 알린다.
   */
  bbox?: string;
  purpose?: "live" | "invest";
  budget_override_krw?: number | null;
  top_n?: number;
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
 * 승인 상태 회수 알림
 *
 * 서버는 **매 요청** 승인 상태를 DB 에서 다시 본다(api-spec §1.5). 즉 세션 도중에도
 * 승인이 회수되면 403 이 날아온다. 이걸 각 화면이 "요청 실패"로 뭉뚱그리면 사용자는
 * 왜 갑자기 안 되는지 알 수 없다 — 여기서 한 번만 붙잡아 로그인 화면으로 넘긴다.
 * ───────────────────────────────────────────────────────────────────────── */

export interface AuthNotice {
  code: ApprovalCode;
  message: string;
  /** 서버가 사유를 함께 줄 때만. 계약상 로그인 403 에는 오지 않는다(감사 기록 전용). */
  reason?: string | null;
}

let authNotice: AuthNotice | null = null;

/**
 * 남아 있는 안내를 **읽기만** 한다(여러 번 읽어도 같은 값).
 *
 * ⚠️ "읽으면 비운다"로 만들지 마라. StrictMode 는 `useState` 초기화 함수를 두 번
 * 호출하므로, 읽는 쪽이 소비까지 하면 **개발 모드에서만 안내가 사라진다**.
 * 비우는 시점은 명시적으로 정한다: 로그인 성공 · 로그아웃 · 새 로그인 시도.
 */
export function getAuthNotice(): AuthNotice | null {
  return authNotice;
}

export function setAuthNotice(notice: AuthNotice | null): void {
  authNotice = notice;
}

export function clearAuthNotice(): void {
  authNotice = null;
}

/**
 * 승인 회수(403)면 세션을 정리하고 안내를 남긴다.
 * @returns 이 예외를 승인 회수로 처리했는지
 */
function handleApprovalRevoked(e: unknown): boolean {
  if (!(e instanceof ApiException) || e.status !== 403 || !isApprovalCode(e.error.code)) {
    return false;
  }
  authNotice = { code: e.error.code, message: e.error.message, reason: e.error.reason ?? null };
  clearSession(); // 남은 access 로 계속 두드려봐야 전부 403 이다
  return true;
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
    // 승인 회수는 재시도해도 결과가 같다 — refresh 도 401 이다. 그 자리에서 끝낸다.
    if (handleApprovalRevoked(e)) throw e;
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
      if (handleApprovalRevoked(e2)) throw e2;
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
  authNotice = null; // 스스로 나가는 것이므로 승인 안내를 남기지 않는다
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
    authNotice = null; // 들어왔으면 옛 승인 안내는 지운다
    setAccessToken(t.access_token);
    return t;
  },

  /**
   * 가입 **신청**. 201 이어도 로그인은 아직 안 된다(`status: "pending"`).
   * 여기에 자동 로그인을 이어 붙이지 마라 — 곧바로 403 을 받고 "가입은 됐는데 실패"로 보인다.
   */
  register(email: string, password: string) {
    return raw<RegisterResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  mapComplexes(params: {
    bbox: string;
    zoom: number;
    max_price_krw?: number;
    area_min_m2?: number;
    area_max_m2?: number;
    built_after?: number;
  }) {
    const q = new URLSearchParams({ bbox: params.bbox, zoom: String(params.zoom) });
    if (params.max_price_krw) q.set("max_price_krw", String(params.max_price_krw));
    if (params.area_min_m2) q.set("area_min_m2", String(params.area_min_m2));
    if (params.area_max_m2) q.set("area_max_m2", String(params.area_max_m2));
    if (params.built_after) q.set("built_after", String(params.built_after));
    return request<MapResponse>(`/map/complexes?${q}`);
  },

  affordability(body: AffordabilityRequest = {}) {
    return request<AffordabilityResponse>("/affordability", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  /** 자산 미입력이면 404 `NOT_FOUND` 로 온다 — 이게 "조건 화면으로 유도" 신호다. */
  getProfile() {
    return request<Profile>("/me/profile");
  },

  putProfile(body: Profile) {
    return request<Profile>("/me/profile", {
      method: "PUT",
      body: JSON.stringify(body),
    });
  },

  /** 미저장이어도 200 + 빈 구조({prefer:{},avoid:{},weights:{}}) 로 온다. */
  getPreferences() {
    return request<Preferences>("/me/preferences");
  },

  putPreferences(body: Preferences) {
    return request<Preferences>("/me/preferences", {
      method: "PUT",
      body: JSON.stringify(body),
    });
  },

  createRecommendation(body: RecommendationRequest) {
    return request<RecommendationAccepted>("/recommendations", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  /**
   * 추천 결과 폴링.
   *
   * `path` 는 **BASE(`/api/v1`) 이후의 경로**다. 서버가 준 `poll_url` 을 그대로 fetch 하지 않고
   * `lib/recommendation.ts::resolvePollPath` 로 형식을 검증해 넘긴다 —
   * 응답에 실린 URL 을 무검증으로 따라가면 그 순간 서버 응답이 요청 목적지를 정하게 된다.
   */
  recommendation(path: string) {
    return request<RecommendationJob>(path);
  },

  /* ── 관리자 (가입 승인) ────────────────────────────────────────────────
   * ⚠️ 관리자가 아니면 서버는 **403 이 아니라 404** 를 준다(api-spec §6.2).
   * 관리 기능의 존재 자체를 숨기려는 의도적 설계다. 그러니 프론트도 404 를
   * "권한 없음"이 아니라 **"그런 기능 없음"** 으로 조용히 처리해야 한다
   * (useAdminUsers 가 그렇게 한다). 여기서는 그냥 통과시킨다. */

  adminListUsers(params: { status?: string; limit?: number } = {}) {
    const q = new URLSearchParams();
    if (params.status) q.set("status", params.status);
    q.set("limit", String(params.limit ?? 100));
    return request<AdminUserListResponse>(`/admin/users?${q}`);
  },

  /** 승인/거부 응답은 **정제 전** 원본이다 — sanitizeAdminUser 를 반드시 통과시킨다. */
  adminApproveUser(userId: number) {
    return request<unknown>(`/admin/users/${encodeURIComponent(userId)}/approve`, {
      method: "POST",
    });
  },

  adminRejectUser(userId: number, reason: string | null) {
    return request<unknown>(`/admin/users/${encodeURIComponent(userId)}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason: reason && reason.trim() !== "" ? reason.trim() : null }),
    });
  },
};
