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
  /**
   * 어느 입력이 틀렸는가(pydantic 422 의 `loc` 마지막 조각). `problems[i]` 와 짝이다.
   * 화면은 이걸로 오류를 **해당 입력 옆에** 붙인다 — 폼 위에 한 줄로 뭉뚱그리면
   * 어느 칸을 고쳐야 하는지 알 수 없다.
   */
  fields?: string[];
  /** 서버가 사유를 함께 줄 때만 채워진다(현재 로그인 403 에는 오지 않는다). */
  reason?: string | null;
}

export class ApiException extends Error {
  constructor(public status: number, public error: ApiError) {
    super(error.message);
    this.name = "ApiException";
  }
}

/**
 * 한도 산정 가정 — **실거주냐 투자냐** (api-spec §3·§4·§5).
 *
 * 세 엔드포인트(`/affordability` · `/map/complexes` · `/recommendations`)가 **같은 값
 * 집합**을 쓴다. 목적에 따라 대출 절대한도·스트레스 가산이 **달라질 수 있어** 한도가
 * 갈릴 수 있고, 그러면 한 화면에서 "지도는 초과, 자금계획은 가능"이 동시에 뜬다.
 *
 * ⚠️ **오늘은 두 값의 한도가 같다** (CR38-4): 운영 데이터에 `purpose` 를 조건으로 쓰는
 *    규칙이 0개다(백엔드 `test_tax_rules_real.py` 가 못박고, 규칙이 생기면 깨진다).
 * 화면의 기본값·단일 출처는 `lib/purpose.ts` 에 있다.
 */
export type Purpose = "live" | "invest";

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

/**
 * 최근접 역. `distance_m` 은 **직선거리**(basis="straight_line")지 도보 거리가 아니다.
 * 값이 없으면 블록 자체가 `null` 로 온다 — "역이 없다"가 아니라 **모른다**는 뜻이다.
 */
export interface NearestStation {
  name?: string | null;
  distance_m: number;
  line_count?: number | null;
  lines?: string[];
  basis?: string;
}

/**
 * 정비사업(재건축·재개발) 블록.
 *
 * ⚠️ `available === false` 는 **"정비사업이 없다"가 아니라 "확인되지 않았다"** 이다
 *    (수집 범위: 서울·인천. 경기도는 미수집 — 서버 `NO_PROJECT_REASON`).
 *    그래서 false 를 "재건축 아님"으로 접으면 안 된다(lib/tags.ts).
 */
export interface RedevelopmentInfo {
  available: boolean;
  stage?: string;
  raw_stage?: string;
  score?: number | null;
  confidence?: number;
  verdict?: string;
  /** 초기 단계인가(기피 조건 판정에 쓰인다). */
  early_stage?: boolean;
  years_since_milestone?: number | null;
  supply_ratio?: number | null;
  upsides?: string[];
  risks?: RiskNote[];
  must_verify?: string[];
  missing?: string[];
}

/**
 * 내가 직접 보고 옮겨 적은 호가 1건 (`/me/listings` · api-spec §2.5).
 *
 * ⚠️ 이 값은 **공공 데이터가 아니다.** 서버가 `source`·`source_label` 을 항상 실어 주는
 *    이유가 그것이다 — 프론트가 라벨을 자체 생성하면 어느 화면에선가 빠지고, 빠진 화면에서
 *    이 숫자는 국토교통부 실거래가처럼 보인다. 그래서 화면은 **서버가 준 문자열만** 쓴다
 *    (`lib/userListings.ts::sourceLabel`).
 *
 * ⚠️ `staleness`·`eligible_for_recommendation` 은 **서버만 아는 사실**이다. 90일 임계는
 *    서버의 계산 경로와 같은 판정이라 화면이 `age_days` 로 되짚어 만들면 언젠가 어긋난다.
 */
export interface UserListing {
  id: number;
  complex_id: number;
  complex_name?: string | null;
  ask_price_krw: number;
  area_m2: number;
  floor?: number | null;
  apt_dong?: string | null;
  /** **이 호가를 직접 확인한 날짜**(YYYY-MM-DD). 저장 시각(`created_at`)과 다르다. */
  as_of: string;
  note?: string | null;
  status: string; // active | traded | withdrawn
  source: string; // user_entered
  /** 화면에 그대로 노출한다. 프론트가 만들지 않는다. */
  source_label: string;
  age_days: number;
  /** fresh(≤30일) | aging(≤90일) | stale(>90일) */
  staleness: string;
  /**
   * 이 호가가 추천 계산에 들어갈 **자격**이 있는가(활성 + 안 낡음). (CR35-7 · SR31-2)
   *
   * ⚠️ **"반영됐다"가 아니다.** 예전 이름("추천에 사용됨")은 낙관적 거짓이었다 —
   *    서버가 재는 것은 이 호가 한 건의 상태뿐이고, 실제로 반영되려면 그 **단지**가
   *    추천 요청의 지역·예산·평수 조건과 후보 조회 상한(120단지)까지 통과해야 한다.
   *    실측: 인천 단지에 넣은 호가가 `true` 인데 서울만 요청한 추천은 그 호가를 0회 본다.
   *    → `false` = 확실히 반영 안 됨 / `true` = **이 호가 때문에 빠지지는 않음**.
   *    남은 조건은 응답 `notes` 가 상시로 말한다.
   *
   * ⚠️ **옵셔널로 두지 않는다.** 옵셔널이면 서버가 이름을 또 바꿔도 타입이 통과하고,
   *    화면은 `undefined === true` → 전부 false 로 **조용히 거짓**을 말한다.
   *    실제 누락은 `lib/userListings.ts::eligibility` 가 런타임에 "모름"으로 잡는다.
   */
  eligible_for_recommendation: boolean;
  price_per_m2_krw: number;
  created_at?: string | null;
  updated_at?: string | null;
}

/**
 * 단건 응답(201·200).
 *
 * ⚠️ **성공해도 `problems` 가 비어 있지 않을 수 있다.** 서버는 "불가능한 값"만 422 로 막고
 *    "가능하지만 이상한 값"(단가 이상·낡음·중복)은 저장하되 말한다. 이걸 안 보여주면
 *    검증의 절반이 사라진다 — 단위 실수(1.48억↔14.8억)가 그대로 추천 점수를 바꾼다.
 */
export interface UserListingItem {
  item: UserListing;
  problems: string[];
  /**
   * **항상** 실리는 고정 고지(출처 · `eligible_for_recommendation` 의 한계).
   * `problems` 와 나눈 이유: 저쪽은 *이 건에만 해당하는 사실*이고 이쪽은 항상 참인 성질이다.
   *
   * ⚠️ POST 201 에도 온다 — 사용자가 `eligible_for_recommendation: true` 를 **처음 보는
   *    자리가 저장 직후**라서, 거기서 조건을 말하지 않으면 목록을 보기도 전에
   *    "반영됐다"고 믿는다. 그래서 화면은 저장 결과에서도 이걸 렌더한다.
   */
  notes: string[];
}

export interface UserListingList {
  items: UserListing[];
  /**
   * `eligible_for_recommendation` 이 "다 넣었는데 왜 추천이 안 바뀌지"의 **절반**에 답한다.
   * 나머지 절반(그 단지가 후보 조회에 잡혔는가)은 이 화면이 알 수 없어 `notes` 가 말한다.
   */
  summary: {
    total: number;
    fresh: number;
    aging: number;
    stale: number;
    inactive: number;
    eligible_for_recommendation: number;
  };
  notes: string[];
}

/** 신규 등록(POST). `as_of` 는 **필수**다 — 기본값(오늘)을 넣지 않는다. */
export interface UserListingCreate {
  complex_id: number;
  ask_price_krw: number;
  area_m2: number;
  floor?: number | null;
  apt_dong?: string | null;
  as_of: string;
  note?: string | null;
}

/**
 * 부분 수정(PATCH). **키 생략 = 안 건드림 · `null` = 비우기.**
 *
 * `null` 을 보낼 수 있는 것은 `floor`·`apt_dong`·`note` 뿐이다(나머지는 422).
 * 그래서 타입에서도 그 셋에만 `| null` 을 준다 — 규칙을 주석이 아니라 타입이 지킨다.
 *
 * ⚠️ `ask_price_krw` 를 보낼 때는 `as_of` 도 **반드시** 함께 보낸다(서버 422).
 *    조립은 `lib/userListings.ts::buildPatch` 한 곳에서만 한다.
 */
export interface UserListingPatch {
  ask_price_krw?: number;
  area_m2?: number;
  floor?: number | null;
  apt_dong?: string | null;
  as_of?: string;
  note?: string | null;
  status?: "active" | "traded" | "withdrawn";
}

export interface ComplexItem {
  id: number;
  name: string;
  point: [number, number];
  households: number | null;
  /**
   * 특성 태그(역세권·재건축)용 사실값. `GET /map/complexes` 응답에도 **실제로 실린다**
   * (CR32-5 — 이전 라운드까지는 지도 응답에 없었다). 없으면(단지별로 값이 없거나
   * 서버가 구버전이면) 모름으로 다뤄 태그를 달지 않는다(lib/tags.ts).
   * ⚠️ 지도 응답의 `redevelopment` 에는 `verdict`·`score` 가 오지 않는다(의도됨) —
   *    `available` 로만 판정한다(그리고 `available: false` 는 "미확인"이지 "없음"이 아니다).
   */
  nearest_station?: NearestStation | null;
  redevelopment?: RedevelopmentInfo | null;
  built_year: number | null;
  recent_price_krw: number | null;
  price_as_of: string | null;
  /**
   * 이 금액이 **어느 면적**의 체결가인가 (CR35-4).
   *
   * 없으면(구버전 서버) **모름**이다 — 사용자가 보는 평형의 값이라고 말하면 안 된다.
   * 서울 단지 절반이 조건 밖 면적을 보여주고 있었고 평균 22.2% 어긋났다. 서버가 이제
   * 조건 안에서 고르지만, **어느 면적인지는 화면이 말해야** 같은 실수가 반복되지 않는다.
   */
  price_area_m2?: number | null;
  /** 값의 근거. `latest_trade` = 실제로 체결된 최근 1건(추천 카드의 추정가와 다른 양이다). */
  price_basis?: string | null;
  price_confidence: "estimated" | "unknown";
  active_listings: number;
  /**
   * 예산 초과인가 — **3값이다**(api-spec §4, 2026-07-29).
   *
   *   `true`  초과   ·  `false` 예산 내  ·  **`null` 판정 못 함**
   *   (예산 기준이 없거나 이 단지의 가격을 모른다)
   *
   * ⚠️ **`null` 을 `false` 로 접지 않는다.** 접는 순간 "예산 안"과 "모른다"가 같은 값이
   *    되어 화면이 그 둘을 구분할 수 없다(G2). 12억짜리일 수도 있는 단지가 "예산 내"로
   *    보이던 게 정확히 그 증상이었다.
   *    그래서 이 값을 읽는 곳은 전부 **`=== true`** 로 비교한다(falsy 검사 금지).
   */
  over_budget: boolean | null;
}

export interface ClusterItem {
  region_code: string;
  count: number;
  center: [number, number];
  median_price_krw: number | null;
  price_basis?: string | null;
}

/**
 * 서버가 예산 상한을 **무엇으로** 세웠는가 (api-spec §4).
 *  · `target_price` — 저장된 희망 매매가(`user_preference.prefer.target_price_krw`)
 *  · `max_purchase` — 자산·소득으로 계산한 최대 실구매 가능 금액
 *
 * 프론트의 `lib/mapFilters.effectiveBudget` 과 **같은 우선순위·같은 어휘**다.
 * 같은 말을 써야 서버 기준과 화면 기준을 대조할 수 있다.
 */
export type BudgetBasis = "target_price" | "max_purchase";

/**
 * 예산 기준을 **적용했는가 · 무엇으로 했는가 · 못 했으면 왜인가**.
 *
 * ⚠️ **금액은 실리지 않는다**(최소 노출). 화면은 그 숫자를 `/affordability` 로 이미
 *    알고 있고, 여기 또 실으면 같은 값이 흐르는 길이 하나 더 늘어난다(SR32-1).
 *
 * 군집(cluster) 응답에도 온다 — 줌아웃했다고 조건이 사라진 것처럼 보이면 안 되기 때문.
 */
export interface MapBudget {
  /** 서버가 실제로 예산 기준을 세웠는가. false 면 `over_budget` 은 전부 `null` 이다. */
  applied: boolean;
  /** 무엇을 기준으로 했는가. 못 세웠으면 null. */
  basis: BudgetBasis | null;
  /** 못 세운 사유(사람이 읽는 문장). 세웠으면 null. */
  reason: string | null;
}

export type MapResponse =
  | {
      level: "complex";
      items: ComplexItem[];
      note: string;
      /**
       * 예산 기준의 적용 여부·근거. **없으면 "적용 안 됨"이 아니라 "서버가 말하지
       * 않았다"** 이다(구버전 응답) — 어느 쪽도 주장하지 않는다(lib/budgetStatus).
       */
      budget?: MapBudget | null;
      /** 지도 금액과 추천 카드 금액이 **왜 다른지**를 서버가 한 번만 말한다. */
      price_basis_note?: string;
      redevelopment_note?: string;
    }
  | {
      level: "cluster";
      items: ClusterItem[];
      /** 군집에는 초과 판정이 없다. 그래도 **기준이 걸렸는지는** 말한다. */
      budget?: MapBudget | null;
      price_basis_note?: string;
    };

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
  purpose?: Purpose;
  /** 희망 매매가. 주면 응답에 `plan` 이 함께 온다. */
  target_price_krw?: number;
  /**
   * 단지 기준 계획 (CR35-4). **`target_price_krw` 없이** 보내면 서버가 그 단지·면적의
   * 기준가를 **추천 카드와 같은 함수**로 산출해 계획을 세운다.
   *
   * 왜 금액이 아니라 id 를 보내나: 지도의 `recent_price_krw` 는 **최근 체결 1건**이고
   * 추천 카드는 **창 중위를 기준월로 환산한 추정가**다. 화면이 지도 값을 그대로 실어
   * 보내면 같은 단지의 자금계획과 추천 카드가 다른 금액으로 선다(실측 부족액 최대 −3.19억).
   * 둘 다 보내면 `target_price_krw` 가 이긴다 — 사용자가 직접 넣은 숫자를 서버가 조용히
   * 갈아치우면 슬라이더가 말을 안 듣는 화면이 된다.
   */
  complex_id?: number;
  /**
   * 전용면적(㎡). 기준가는 **면적별** 값이라(한 단지가 34~120㎡) 이걸 안 보내면 서버
   * 기본값(84㎡)이 쓰이고, 화면은 그 사실을 모른 채 "이 집" 계획이라고 말하게 된다.
   * 그래서 화면은 항상 명시해 보내고 **무슨 면적을 썼는지 함께 적는다**(`lib/affordability.planArea`).
   */
  area_m2?: number;
}

/**
 * 자금계획이 **무엇을 기준가로 썼는가** (CR35-4).
 *
 * 계획을 못 세웠으면 `krw: null` + `reason` 이 온다 — **0 으로 채우지 않는다.**
 * 이 값은 사용자 자산으로 나눗셈을 하는 숫자라, 지어내면 "얼마나 더 필요한가"가 통째로 틀린다.
 */
export interface TargetPriceRef {
  krw: number | null;
  /** `time_adjusted_band` | `trade_band` | `client_supplied` */
  basis?: string | null;
  /** 시점 보정을 했으면 환산 기준월("2026-06"). 안 했으면 null. */
  as_of_ym?: string | null;
  sample_size?: number | null;
  period_months?: number | null;
  /** 보정을 못 했거나 계획을 못 세운 사유. 내부 코드일 수 있다 → `plainReason` 을 거친다. */
  reason?: string | null;
}

export interface AffordabilityResponse {
  max_purchase_krw: number;
  /** 희망가를 보냈을 때만. 서버가 아직 이 계약을 배포하지 않았으면 없다. */
  plan?: AffordabilityPlan | null;
  /** 계획의 기준가 근거. `target_price_krw`·`complex_id` 중 하나를 보냈을 때만 온다. */
  target_price?: TargetPriceRef | null;
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
  /**
   * 순위 가중치. 축 이름은 서버 `scoring.py::AXIS_SPECS` 와 **같은 문자열**이어야 한다.
   *
   * ⚠️ `redevelopment`(재건축)는 나중에 추가된 축이라 특별한 규칙이 있다:
   *    **키를 아예 안 보내면** 서버가 기본 15% 를 넣고 그 사실을 notes 로 고지한다.
   *    **0 을 명시해서 보내면** 서버가 존중한다(그 축을 안 본다).
   *    즉 "안 보냄"과 "0"은 다른 뜻이다 — 그래서 화면은 `normalizeWeights` 로
   *    **모든 축을 항상 실어 보낸다**(0 도 값이다).
   */
  weights: {
    price?: number;
    location?: number;
    value?: number;
    risk?: number;
    redevelopment?: number;
  };
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

/**
 * 적정가 밴드의 **시점 보정** 결과 (서버 `domain/valuation/timeadjust.py::TimeAdjustment`).
 *
 * 6~36개월 창의 거래를 시점 구분 없이 섞으면 밴드 중위는 "창의 중간 시점" 가격이 된다.
 * 그래서 서버가 각 거래를 **기준월**로 환산한 뒤 분위수를 낸다.
 *
 * ⚠️ `applied === false` 도 정상 응답이다 — 지수가 없거나 커버리지가 모자라면
 *    서버는 **보정을 포기하고 사유를 남긴다**. 값의 유무가 아니라 `applied` 로 판단한다.
 */
export interface TimeAdjustment {
  /** 실제로 환산했는가. 이 값이 표시 문구를 가른다. */
  applied: boolean;
  /** 환산 기준월("2026-06"). "오늘"이 아니라 **완결된 가장 최근 달**이다. */
  reference_ym?: string | null;
  /** 지수 층위("sigungu" | "sido") — 내부 코드다. 화면에 그대로 내지 않는다. */
  scope?: string | null;
  region_code?: string | null;
  /** 보정으로 중위가 몇 % 움직였는가(음수 가능). */
  shift_pct?: number | null;
  /** 창 안 거래 중 지수를 가진 비율(%). */
  coverage_pct?: number | null;
  sample_size?: number | null;
  basis?: string | null;
  /** 보정하지 않은 사유. **내부 코드일 수 있다** → `lib/plainTerms.plainReason` 을 거친다. */
  reason?: string | null;
  /** 사람이 읽는 한 줄(서버 생성). 있으면 그대로 쓴다 — 재조립하지 않는다. */
  note?: string | null;
}

/**
 * 적정가 밴드.
 *
 * 🕒 시점 계약 (CR33-3 — 이 세 필드가 없으면 화면이 보정값을 원본 실거래가라 부르게 된다)
 *  · `as_of_ym`        보정했으면 기준월("2026-06"), 아니면 **null**.
 *                      null 은 "지금 시세"가 아니라 **"시점을 말할 수 없다"** 이다.
 *  · `time_adjusted`   이 밴드가 실제로 환산된 값인가.
 *  · `time_adjustment` 시도했으면 결과(성공/실패+사유), 시도조차 안 했으면 null.
 *
 * ⚠️ 셋 다 **선택 필드**다. 구버전 서버나 다른 엔드포인트에서는 오지 않는다.
 *    없으면 "보정 안 됨"이 아니라 **모름**이다 — 어느 쪽도 주장하지 않는다
 *    (판단은 `lib/recommendation.ts::bandTimeView` 한 곳에서만 한다).
 */
export interface PriceBand {
  p25_krw: number;
  median_krw: number;
  p75_krw: number;
  sample_size: number;
  period_months: number;
  expanded: boolean;
  source: string;
  as_of_ym?: string | null;
  time_adjusted?: boolean;
  time_adjustment?: TimeAdjustment | null;
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
  /* ── 특성 태그(대단지·역세권·재건축) 판정용 사실값 ──────────────────────
   * 서버는 **판정이 아니라 값**을 준다(임계값은 표시 관례라 바뀌므로 화면이 정한다).
   * 없으면(`undefined`·`null`) **모름**이고, 모르면 태그를 달지 않는다 — lib/tags.ts. */

  /** 총 세대수. null = 모름(**대단지 아님이 아니다** — 미확보가 16.2%다). */
  total_households?: number | null;
  nearest_station?: NearestStation | null;
  redevelopment?: RedevelopmentInfo | null;
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
  /**
   * 이 카드의 요약 문장(headline/why/why_not)을 **누가 썼는가**.
   *   `"llm"`      — AI 요약
   *   `"fallback"` — 규칙 기반. LLM 미연결·호출 실패·상한 초과일 수도 있고,
   *                  **AI 요약이 분담금 표현을 써서 폐기당한 경우**일 수도 있다.
   *
   * ⚠️ 이 값이 화면에 닿지 않으면 강등 사실이 사용자에게 전달되지 않는다(CR31-2).
   *    다만 LLM 미연결 상태에서는 **모든 카드가 fallback** 이라 카드마다 경고를 띄우면
   *    소음이 된다 — 그건 job 단위 notes 가 이미 말한다. 판단은 `lib/recommendation.ts`
   *    의 `summaryBasisView` 한 곳에서 한다.
   */
  summary_basis?: string | null;
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
  purpose?: Purpose;
  budget_override_krw?: number | null;
  top_n?: number;

  /* ── 내 조건(선호) — **끄는 방법이 있어야 한다** ─────────────────────────
   * 서버는 이 필드들을 안 보내면 저장된 `user_preference.prefer` 를 **폴백**으로 쓴다
   * (`app/domain/conditions.py`). 프론트가 한 줄 빠뜨려도 조건이 증발하지 않게 한
   * 안전장치다. 그런데 그 폴백 때문에 **조건을 끄는 방법이 사라졌다** —
   * 지도에서 면적 칩을 꺼도 추천은 저장된 면적으로 계속 걸렀다(FE-4).
   *
   * ⚠️ 그래서 `null`(안 보냄)과 "끔"은 **다른 뜻**이다:
   *      · 키 없음        → 저장된 내 조건을 그대로 쓴다
   *      · use_saved_conditions=false → 이번 요청에서는 저장된 조건을 쓰지 않는다
   *    화면이 이 둘을 구분해 보내는 곳은 `lib/recommendConditions.ts` 한 곳뿐이다. */
  area_min_m2?: number;
  area_max_m2?: number;
  built_after?: number;
  min_households?: number;
  /** false = 이번 요청에 저장된 "내 조건"을 쓰지 않는다(칩 OFF). 생략 = 예전대로 폴백. */
  use_saved_conditions?: boolean;
}

const BASE = "/api/v1";

/* ─────────────────────────────────────────────────────────────────────────
 * 🔐 쿼리 조립 — **여기 한 곳에서만** 한다 (SR32-1)
 *
 * 무슨 일이 있었나
 * ----------------
 * 지도 조회가 `?...&max_price_krw=1314310000` 으로 나갔다. 그 숫자는 사용자가 화면에
 * 입력한 값이 아니라 **AES-256-GCM 으로 암호화해 저장한 자산·소득·대출을 복호화해
 * 서버가 계산한 실구매 가능 금액**이다. URL 은 nginx·uvicorn 접근 로그에 평문으로
 * 쌓이고, 로테이션된 로그 파일이 월드 리더블(0644)이라 다른 서비스 계정이 실제로 읽었다.
 *
 * 왜 "파생값"이 더 위험한가: 원본(현금·연소득)을 안 보냈으니 괜찮다고 읽히지만, 한도는
 * 자산의 단조 함수라 몇 건만 모여도 원본이 좁혀진다. 그리고 눈에 안 띈다 — 이름에
 * `cash`·`income` 이 없기 때문이다.
 *
 * 규칙
 * ----
 *  ① **개인·민감정보를 URL 쿼리에 넣지 않는다.** 금액은 본문(POST body)으로 보내거나,
 *     아예 보내지 않고 서버가 저장된 프로필에서 만든다. 본문은 접근 로그에 남지 않는다.
 *  ② 조립은 `buildQuery` 한 곳을 지난다. 손으로 만든 쿼리도 `raw()` 가 마지막에 한 번 더 본다.
 *  ③ 걸리면 **던진다**(조용히 지우지 않는다). 요청 하나가 실패하는 편이 새는 것보다 낫다.
 *  ④ 오류 메시지에 **값을 담지 않는다** — 콘솔·오류수집기로 옮겨 심으면 같은 사고다.
 * ───────────────────────────────────────────────────────────────────────── */

/**
 * 금액성 파라미터 이름. 이름만으로 거절한다 — 값이 "만원 단위"(1.3억 → 13140)라
 * 숫자 크기 검사를 빠져나가는 경우를 이름이 잡는다.
 * ⚠️ `budget` 은 **일부러 빠져 있다**: 금액이 아니라 "내 예산 기준으로 걸러 달라"는
 *    비민감 플래그(`budget=mine`)로 쓰기 때문이다. 금액이면 `_krw` 가 붙는다.
 */
const SENSITIVE_QUERY_KEY = /krw|price|cash|income|loan|asset|salary|deposit|net_?worth|budget_/i;

/**
 * 쿼리에 실릴 수 있는 숫자의 상한(1천만).
 *
 * 이 앱의 정상 쿼리 값은 전부 이보다 작다: 좌표(bbox, 문자열)·줌(1~22)·전용면적(㎡)·
 * 준공연도(1900~2100)·목록 상한(100)·단지 id(수만). 그래서 1천만 이상인 숫자는
 * **원화 금액일 가능성이 압도적**이다. 이름을 바꿔 우회해도 값이 걸린다.
 */
const MAX_QUERY_NUMBER = 10_000_000;

/** 쿼리 파라미터 하나가 금액처럼 보이는가. 보이면 던진다(값은 메시지에 남기지 않는다). */
function assertNotSensitive(key: string, value: string): void {
  if (SENSITIVE_QUERY_KEY.test(key)) {
    throw new Error(
      `URL 쿼리에 금액성 파라미터를 실을 수 없습니다: "${key}" — ` +
        "본문으로 보내거나 서버가 저장된 프로필에서 만들게 하세요 (SR32-1)",
    );
  }
  const n = Number(value);
  if (Number.isFinite(n) && Math.abs(n) >= MAX_QUERY_NUMBER) {
    throw new Error(
      `URL 쿼리 값이 금액으로 보입니다: "${key}" (${MAX_QUERY_NUMBER.toLocaleString("ko-KR")} 이상) — ` +
        "접근 로그에 평문으로 남습니다 (SR32-1)",
    );
  }
}

/**
 * 객체 → `?a=1&b=2`. 비어 있으면 **빈 문자열**(물음표만 남은 URL 을 만들지 않는다).
 *
 * `undefined`·`null` 은 "안 보냄"이다 — 서버 쪽에서 "안 보냄"과 "0"은 다른 뜻이라
 * (조건 없음 vs 0원 상한) 여기서 0 을 조용히 지우지 않는다. 값이 0 이면 그대로 보낸다.
 *
 * @throws 금액성 파라미터가 섞여 있으면 (SR32-1)
 */
export function buildQuery(params: object): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params as Record<string, unknown>)) {
    if (value === undefined || value === null) continue;
    if (typeof value === "object") {
      // 객체를 넣으면 "[object Object]" 가 조용히 실린다. 그건 버그다.
      throw new Error(`쿼리 파라미터 "${key}" 는 문자열·숫자여야 합니다`);
    }
    const s = String(value);
    assertNotSensitive(key, s);
    q.set(key, s);
  }
  const s = q.toString();
  return s === "" ? "" : `?${s}`;
}

/**
 * 마지막 관문 — **모든** 요청이 여기를 지난다(`buildQuery` 를 안 쓰고 손으로 만든 URL 도).
 *
 * 경로(path segment)는 검사하지 않는다: 거기 오는 것은 id 뿐이고, id 는 언젠가 1천만을
 * 넘을 수 있어 오탐이 서비스를 멈출 수 있다. 쿼리에는 id 도 금액도 필요 없다.
 */
function assertPathSafe(path: string): void {
  const at = path.indexOf("?");
  if (at === -1) return;
  for (const [key, value] of new URLSearchParams(path.slice(at + 1))) {
    assertNotSensitive(key, value);
  }
}

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

/**
 * pydantic 검증 실패(422) → 화면이 쓸 수 있는 오류.
 *
 * 서버는 두 가지 모양의 422 를 낸다: 라우터가 던지는 `{code, message}` 와, 스키마 검증이
 * 만드는 **배열**(`[{type, loc, msg}]`, main.py 의 핸들러가 `input` 을 지운 형태)이다.
 * 배열 쪽을 예전에는 "요청이 실패했습니다 (422)" 한 줄로 뭉갰다 — 어느 칸이 왜 틀렸는지가
 * 통째로 사라져서, 사용자는 고칠 수가 없었다.
 *
 * ⚠️ `msg` 는 서버가 이미 길이를 자른 문장이다. 여기서 다시 가공하지 않는다(지어내지 않는다).
 */
function validationError(detail: unknown[], status: number): ApiError {
  const rows = detail.filter(
    (d): d is { loc?: unknown[]; msg?: unknown } => typeof d === "object" && d !== null,
  );
  const problems = rows.map((d) => String(d.msg ?? "")).filter((m) => m !== "");
  const fields = rows.map((d) => {
    const loc = Array.isArray(d.loc) ? d.loc : [];
    return String(loc[loc.length - 1] ?? "");
  });
  return {
    code: "INVALID_PARAM",
    message: problems[0] ?? `요청이 실패했습니다 (${status})`,
    problems,
    fields,
  };
}

async function raw<T>(path: string, init: RequestInit = {}): Promise<T> {
  // 🔐 SR32-1 — 나가기 직전에 한 번 더 본다. `buildQuery` 를 우회해 손으로 조립한
  //    URL(폴링 경로·복사해 붙인 코드)도 이 문을 지나야 한다.
  assertPathSafe(path);
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
        : Array.isArray(detail)
          ? validationError(detail, res.status)
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

  /**
   * 화면 범위 안의 단지.
   *
   * 🔐 **금액 파라미터가 없다**(SR32-1). 예전에는 `max_price_krw` 에 실구매 가능 금액
   *    (= 암호화 저장된 자산·소득·대출로 계산한 값)을 실어 보냈고, 그 URL 이 접근 로그에
   *    평문으로 쌓였다. 이 경로는 **인증된 경로**이고 서버는 이미 그 사용자의 프로필과
   *    저장된 희망 매매가를 갖고 있다 — 클라이언트가 금액을 계산해 보낼 이유가 없다.
   *    지금은 `budget=mine` **플래그만** 보내고 상한은 서버가 만든다(lib/mapFilters).
   */
  mapComplexes(params: {
    bbox: string;
    zoom: number;
    /** "내 예산 기준으로 걸러 달라"는 **비민감 플래그**. 금액이 아니다. */
    budget?: "mine";
    /**
     * 한도 산정 가정(`live` | `invest`). **보내야 한다.**
     *
     * 왜: 목적에 따라 대출 절대한도·스트레스 가산이 **달라질 수 있다.** 안 보내면
     * 서버는 `live` 로 계산하는데 자금계획 패널이 `invest` 로 계산하고 있으면, 같은
     * 단지가 지도에서는 "예산 초과", 자금 패널에서는 "가능"이 된다(백엔드 지적).
     * ⚠️ 오늘은 운영 데이터에 목적별 규칙이 0개라 두 값의 한도가 같다(CR38-4).
     * **비민감 열거값**이라 URL 쿼리에 실어도 SR32-1 규칙에 걸리지 않는다(금액이 아니다).
     */
    purpose?: Purpose;
    area_min_m2?: number;
    area_max_m2?: number;
    built_after?: number;
  }) {
    return request<MapResponse>(`/map/complexes${buildQuery(params)}`);
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

  /* ── 내 매물(호가 직접 입력) ────────────────────────────────────────────
   * 소유자 스코프 자원이다. **남의 것과 없는 것이 같은 404** 로 오므로(IDOR 규약)
   * 프론트도 404 를 "권한 없음"으로 번역하지 않는다 — 그냥 "찾을 수 없습니다"다. */

  listMyListings(complexId?: number | null) {
    return request<UserListingList>(
      `/me/listings${buildQuery({ complex_id: typeof complexId === "number" ? complexId : null })}`,
    );
  },

  createMyListing(body: UserListingCreate) {
    return request<UserListingItem>("/me/listings", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  /**
   * 부분 수정. **`JSON.stringify` 가 `undefined` 키를 지운다** — 그래서 "생략"과
   * "명시적 null"이 그대로 서버 규칙(안 건드림 / 비우기)에 대응한다.
   * 본문 조립은 `lib/userListings.ts::buildPatch` 만 한다(가격↔날짜 규칙이 거기 있다).
   */
  updateMyListing(id: number, patch: UserListingPatch) {
    return request<UserListingItem>(`/me/listings/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
  },

  /** 되돌릴 수 없다. 화면이 반드시 한 번 더 묻는다(MyListingsScreen). */
  deleteMyListing(id: number) {
    return request<void>(`/me/listings/${encodeURIComponent(id)}`, { method: "DELETE" });
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
    return request<AdminUserListResponse>(
      `/admin/users${buildQuery({ status: params.status || null, limit: params.limit ?? 100 })}`,
    );
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
