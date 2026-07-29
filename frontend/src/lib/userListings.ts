/**
 * 내 매물(호가 직접 입력) — **순수 함수**. 뷰·DOM 에 의존하지 않으므로 RN 에서 그대로 쓴다.
 *
 * 왜 이 모듈이 따로 있나
 * ----------------------
 * 이 화면은 사람이 **손으로 치는 금액**을 다룬다. 단위 실수(1.48억 ↔ 14.8억)와 날짜 누락이
 * 일상적으로 들어오고, 그 값은 그대로 추천 가격 축(가중치 31%)의 점수가 된다. 그래서
 * 규칙을 컴포넌트에 흩뿌리지 않고 여기 한 곳에 모은다 — 흩뿌리면 어느 화면에선가 빠진다.
 *
 * 지키는 규칙 (서버 계약 `api-spec §2.5` 와 **같은 값**을 쓴다)
 *  ① 서버보다 엄격하게 막지 않는다. 여기 상수는 `backend/app/api/schemas.py` 를 복사한 것이지
 *     새로 만든 것이 아니다 — 더 엄격하면 서버가 받아 주는 값을 화면이 거부한다.
 *  ② **`as_of` 에 기본값을 넣지 않는다.** 오늘 날짜를 미리 채우면 3주 전에 본 호가가
 *     오늘 값이 되고, 낡음 판정이 통째로 거짓이 된다.
 *  ③ **가격을 바꾸면 날짜도 함께** 보낸다(서버 422). 그 조립은 `buildPatch` 만 한다.
 *  ④ 출처 라벨을 **만들지 않는다**. 서버가 준 `source_label` 만 쓴다 — 프론트가 만들면
 *     어느 화면에선가 빠지고, 빠진 화면에서 이 숫자는 공공 데이터처럼 보인다.
 *
 * 🔐 값은 개인 자산 판단에 쓰이는 정보다. 로그·저장소·URL 에 쓰지 않는다.
 */
import type { UserListing, UserListingCreate, UserListingPatch } from "../api/client";

/* ── 서버와 같은 한계값 (schemas.py) ────────────────────────────────────── */

/** 호가 하한(원). '15'(억)·'150000'(만원) 같은 단위 실수를 잡는다. */
export const LISTING_MIN_KRW = 10_000_000;
/** 호가 상한(원). `target_price_krw` 와 같은 값 — 같은 성격의 금액을 두 기준으로 재지 않는다. */
export const LISTING_MAX_KRW = 100_000_000_000;
export const LISTING_MAX_AREA_M2 = 1000;
export const LISTING_MIN_FLOOR = -5;
export const LISTING_MAX_FLOOR = 200;
export const LISTING_MAX_DONG_LEN = 20;
export const LISTING_MAX_NOTE_LEN = 200;
/** 이보다 오래된 호가는 **등록 자체가 거절**된다(서울 기준 1년이면 시세가 10%대로 움직인다). */
export const LISTING_MAX_AGE_DAYS = 365;

/* ── 날짜 (UTC 기준으로만 다룬다) ────────────────────────────────────────
 * 로컬 타임존으로 `new Date("2026-07-28")` 을 비교하면 KST 에서 하루가 밀려
 * "오늘 본 호가"가 미래로 판정된다. 날짜만 있는 값은 날짜로만 비교한다. */

const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** "YYYY-MM-DD" → UTC epoch(ms). 형식·실재하지 않는 날짜(2월 30일)면 null. */
export function parseIsoDate(value: string): number | null {
  const m = ISO_DATE_RE.exec(value.trim());
  if (!m) return null;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const ms = Date.UTC(y, mo - 1, d);
  const back = new Date(ms);
  // 존재하지 않는 날짜는 Date 가 조용히 굴려 버린다(2026-02-30 → 3-02). 되돌려 확인한다.
  if (back.getUTCFullYear() !== y || back.getUTCMonth() !== mo - 1 || back.getUTCDate() !== d) {
    return null;
  }
  return ms;
}

/**
 * 오늘(로컬 달력 기준) "YYYY-MM-DD".
 *
 * ⚠️ **폼 기본값으로 쓰지 마라.** 여기 있는 이유는 검증(미래 날짜 거절)과 `max` 속성 때문이다.
 *    사용자는 며칠 전 캡처를 옮겨 적는 일이 많고, 기본값이 있으면 그게 오늘 값으로 둔갑한다.
 */
export function todayIso(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** a(과거) → b(오늘) 사이 일수. 형식이 깨졌으면 null. */
export function daysBetween(fromIso: string, toIso: string): number | null {
  const a = parseIsoDate(fromIso);
  const b = parseIsoDate(toIso);
  if (a === null || b === null) return null;
  return Math.round((b - a) / 86_400_000);
}

/* ── 출처 ────────────────────────────────────────────────────────────────
 * 여기에 "사용자 입력" 이라는 문자열을 **적지 않는다**. 적는 순간 서버가 라벨을 바꿔도
 * 화면은 옛 라벨을 말하고, 서버가 라벨을 빼면 화면은 없는 근거를 지어낸다. */

/** 서버가 준 출처 라벨. 없으면 **null**(지어내지 않는다). */
export function sourceLabel(item: Pick<UserListing, "source_label">): string | null {
  const raw = item.source_label;
  if (typeof raw !== "string") return null;
  const text = raw.trim();
  return text === "" ? null : text;
}

/* ── 낡음 · 반영 자격 ────────────────────────────────────────────────────
 * 판정은 **서버가 한다**(`staleness` · `eligible_for_recommendation`). 화면이 `age_days` 로
 * 되짚어 만들면 임계값이 바뀌는 날 계산 경로와 조용히 어긋난다.
 *
 * ⚠️ 그리고 이 값은 **"반영됐다"가 아니라 "자격이 있다"** 이다(CR35-7 · SR31-2).
 *    서버는 호가 한 건의 상태만 알고, 실제 반영은 그 단지가 추천 요청의 지역·예산·평수
 *    조건과 후보 조회 상한을 통과하는지에 달려 있다. 화면 문구가 "반영됐습니다"라고
 *    단정하면 이름만 바꾸고 거짓은 그대로 남는다. */

export type Staleness = "fresh" | "aging" | "stale" | "unknown";

/**
 * 서버가 말한 **반영 자격**. `null` 은 "서버가 말하지 않았다"이며 **false 가 아니다**.
 *
 * 왜 이 함수가 따로 있나: 필드 이름이 바뀌면(실제로 2026-07-29 에 한 번 바뀌었다 —
 * "추천에 사용됨" → `eligible_for_recommendation`) `item.foo === true` 식 접근은
 * `undefined === true` → **전부 false** 가 되어 "모든 호가가 반영 안 됨"으로
 * 조용히 거짓을 말한다. TS 는 런타임 응답을 못 잡고, 목(mock)을 쓰는 테스트는 전부 통과한다.
 * 그래서 **모르면 모른다고** 말할 수 있는 3상태로 받는다.
 */
export function eligibility(item: Partial<UserListing>): boolean | null {
  const raw = item.eligible_for_recommendation;
  return typeof raw === "boolean" ? raw : null;
}

export interface StalenessView {
  grade: Staleness;
  /** "3일 전 확인" — 값(age_days)은 서버가 준 것을 그대로 쓴다. */
  ageText: string;
  /**
   * 추천에 들어갈 **자격**이 있는가. `null` = 서버가 말하지 않음(모름).
   * `true` 는 "반영됐다"가 아니라 "이 호가 때문에 빠지지는 않는다"는 뜻이다.
   */
  eligible: boolean | null;
  /** 짧은 배지 문구. */
  badgeText: string;
  /** 자격 문장. `eligible=false`·`null` 을 반영된 것처럼 쓰지 않는다. */
  usageText: string;
  /** 갱신 동선을 띄워야 하는가(낡았는데 아직 판매 중). */
  needsRefresh: boolean;
}

export function statusLabel(status: string): string {
  switch (status) {
    case "active":
      return "판매 중";
    case "traded":
      return "거래됨";
    case "withdrawn":
      return "내림";
    default:
      return status;
  }
}

function grade(value: string): Staleness {
  return value === "fresh" || value === "aging" || value === "stale" ? value : "unknown";
}

export function stalenessView(item: UserListing): StalenessView {
  const g = grade(item.staleness);
  const age = Number.isFinite(item.age_days) ? item.age_days : null;
  const ageText =
    age === null ? "확인 날짜 미상" : age <= 0 ? "오늘 확인" : `${age}일 전 확인`;
  const eligible = eligibility(item);

  // 모름은 아님으로 접지 않는다 — 서버가 말하지 않았다는 사실 자체를 말한다.
  if (eligible === null) {
    return {
      grade: g,
      ageText,
      eligible: null,
      badgeText: "반영 여부 미상",
      usageText: "이 호가가 추천에 쓰일 수 있는지 서버가 알려 주지 않았습니다.",
      needsRefresh: false,
    };
  }

  let usageText: string;
  if (eligible) {
    // ⚠️ "반영됐다"고 쓰지 않는다. 서버가 아는 것은 자격뿐이다(모듈 상단 주석).
    usageText =
      g === "aging"
        ? "추천에 반영될 수 있습니다 — 다만 그 사이 시세가 움직였을 수 있습니다"
        : "추천에 반영될 수 있습니다 — 실제 반영은 추천 조건(지역·예산·평수)에 달려 있습니다";
  } else if (item.status !== "active") {
    usageText = `${statusLabel(item.status)} — 추천에서 제외됨`;
  } else if (g === "stale") {
    usageText = "낡아서 추천에서 제외됨";
  } else {
    usageText = "추천에 반영되지 않습니다";
  }

  return {
    grade: g,
    ageText,
    eligible,
    badgeText: eligible ? "반영 가능" : "반영 제외",
    usageText,
    needsRefresh: !eligible && item.status === "active",
  };
}

/** "총 7건 · 반영 가능 5건 · 낡음 2건" — 없는 항목은 적지 않는다. */
export function summaryText(summary: {
  total: number;
  stale?: number;
  inactive?: number;
  eligible_for_recommendation?: number;
}): string {
  const parts = [`총 ${summary.total}건`];
  if (typeof summary.eligible_for_recommendation === "number") {
    // "반영 5건"이라고 쓰지 않는다 — 서버가 아는 것은 자격이지 결과가 아니다.
    parts.push(`반영 가능 ${summary.eligible_for_recommendation}건`);
  }
  if (summary.stale) parts.push(`낡음 ${summary.stale}건`);
  if (summary.inactive) parts.push(`거래됨·내림 ${summary.inactive}건`);
  return parts.join(" · ");
}

/* ── 폼 ───────────────────────────────────────────────────────────────── */

export interface ListingFormValues {
  /** 원 단위. MoneyField 가 만원 입력을 원으로 바꿔 준다. null = 미입력. */
  askPriceKrw: number | null;
  areaM2: string;
  floor: string;
  aptDong: string;
  /** **빈 문자열로 시작한다.** 오늘 날짜를 미리 채우지 않는다(모듈 상단 규칙 ②). */
  asOf: string;
  note: string;
}

export const EMPTY_FORM: ListingFormValues = {
  askPriceKrw: null,
  areaM2: "",
  floor: "",
  aptDong: "",
  asOf: "",
  note: "",
};

/** 수정 폼의 초기값 — 저장된 값을 그대로 되돌린다(날짜도 그대로: 안 바꾸면 안 건드린다). */
export function formFromListing(item: UserListing): ListingFormValues {
  return {
    askPriceKrw: item.ask_price_krw,
    areaM2: String(item.area_m2),
    floor: item.floor === null || item.floor === undefined ? "" : String(item.floor),
    aptDong: item.apt_dong ?? "",
    asOf: item.as_of,
    note: item.note ?? "",
  };
}

export type ListingField = keyof ListingFormValues;
export type ListingErrors = Partial<Record<ListingField, string>>;

/** 소수 실수(`Infinity`·`1e5`·`NaN` 제외). `Number()` 는 "Infinity" 를 통과시킨다. */
const DECIMAL_RE = /^\d+(\.\d+)?$/;
const INT_RE = /^-?\d+$/;

/**
 * 폼 검증. 서버 규칙의 **복사본**이다(더 엄격하지 않다).
 *
 * 최종 판정은 서버가 한다 — 여기서 막는 것은 "왕복하지 않아도 확실히 틀린 값"뿐이고,
 * 이상하지만 가능한 값(₩/㎡ 이상·중복)은 **막지 않는다**. 그건 서버가 `problems` 로 말한다.
 */
export function validateForm(
  values: ListingFormValues,
  opts: { today?: string } = {},
): ListingErrors {
  const today = opts.today ?? todayIso();
  const errors: ListingErrors = {};

  if (values.askPriceKrw === null) {
    errors.askPriceKrw = "호가를 입력해 주세요.";
  } else if (values.askPriceKrw < LISTING_MIN_KRW) {
    errors.askPriceKrw = "1,000만원 미만은 등록할 수 없습니다 — 단위(억·만원)를 확인해 주세요.";
  } else if (values.askPriceKrw > LISTING_MAX_KRW) {
    errors.askPriceKrw = "1,000억을 넘는 금액은 등록할 수 없습니다.";
  }

  const area = values.areaM2.trim();
  if (area === "") {
    errors.areaM2 = "전용면적을 입력해 주세요.";
  } else if (!DECIMAL_RE.test(area)) {
    errors.areaM2 = "숫자로 입력해 주세요 (예: 84.97).";
  } else {
    const n = Number(area);
    if (!(n > 0)) errors.areaM2 = "0보다 커야 합니다.";
    else if (n > LISTING_MAX_AREA_M2) errors.areaM2 = "1,000㎡ 이하로 입력해 주세요.";
  }

  const floor = values.floor.trim();
  if (floor !== "") {
    if (!INT_RE.test(floor)) {
      errors.floor = "정수로 입력해 주세요 (모르면 비워 두세요).";
    } else {
      const n = Number(floor);
      if (n < LISTING_MIN_FLOOR || n > LISTING_MAX_FLOOR) {
        errors.floor = `${LISTING_MIN_FLOOR}층 ~ ${LISTING_MAX_FLOOR}층 범위로 입력해 주세요.`;
      }
    }
  }

  if (values.aptDong.trim().length > LISTING_MAX_DONG_LEN) {
    errors.aptDong = `${LISTING_MAX_DONG_LEN}자 이하로 입력해 주세요.`;
  }
  if (values.note.trim().length > LISTING_MAX_NOTE_LEN) {
    errors.note = `${LISTING_MAX_NOTE_LEN}자 이하로 입력해 주세요.`;
  }

  const asOf = values.asOf.trim();
  if (asOf === "") {
    // 기본값을 넣지 않기로 한 대가는 "한 번 더 묻는 것"이다. 그 대신 왜 묻는지 말한다.
    errors.asOf = "이 호가를 **직접 확인한 날짜**를 골라 주세요. 오늘 날짜를 미리 채우지 않습니다.";
  } else {
    const ms = parseIsoDate(asOf);
    if (ms === null) {
      errors.asOf = "날짜 형식이 올바르지 않습니다 (YYYY-MM-DD).";
    } else {
      const age = daysBetween(asOf, today);
      if (age === null) errors.asOf = "날짜를 확인해 주세요.";
      else if (age < 0) errors.asOf = "미래 날짜는 넣을 수 없습니다 — 오늘 이전이어야 합니다.";
      else if (age > LISTING_MAX_AGE_DAYS) {
        errors.asOf =
          "1년이 넘은 호가는 등록할 수 없습니다 — 다시 확인한 뒤 그 날짜로 등록하세요.";
      }
    }
  }

  return errors;
}

export function hasErrors(errors: ListingErrors): boolean {
  return Object.keys(errors).length > 0;
}

/** 등록 본문. 비어 있는 선택 항목은 **키를 싣지 않는다**(null 과 미입력을 섞지 않는다). */
export function buildCreate(complexId: number, values: ListingFormValues): UserListingCreate {
  const body: UserListingCreate = {
    complex_id: complexId,
    ask_price_krw: values.askPriceKrw as number,
    area_m2: Number(values.areaM2.trim()),
    as_of: values.asOf.trim(),
  };
  const floor = values.floor.trim();
  if (floor !== "") body.floor = Number(floor);
  const dong = values.aptDong.trim();
  if (dong !== "") body.apt_dong = dong;
  const note = values.note.trim();
  if (note !== "") body.note = note;
  return body;
}

export type PatchResult = { body: UserListingPatch } | { error: string };

/**
 * 수정 본문. **바뀐 것만** 싣는다(키 생략 = 안 건드림).
 *
 * ⚠️ 이 함수의 존재 이유는 한 줄이다: **가격을 바꾸면 날짜도 함께 보낸다.**
 *    가격만 갱신하면 석 달 전 날짜에 오늘 가격이 붙어 낡음 판정이 통째로 거짓이 되고,
 *    그 상태는 화면 어디에도 드러나지 않는다(서버도 422 로 같은 규칙을 건다).
 *
 * 비우기는 `floor`·`apt_dong`·`note` 만 — 빈칸으로 두면 `null` 을 싣는다.
 * 나머지에 `null` 을 보내면 서버가 422 를 준다(조용히 무시하면 사용자는 지웠다고 믿는다).
 */
export function buildPatch(before: UserListing, values: ListingFormValues): PatchResult {
  const body: UserListingPatch = {};

  const price = values.askPriceKrw;
  const priceChanged = price !== null && price !== before.ask_price_krw;
  const asOf = values.asOf.trim();

  if (priceChanged) {
    if (asOf === "") {
      return {
        error:
          "가격을 바꾸셨습니다 — 그 가격을 확인한 날짜도 함께 골라 주세요. " +
          "가격만 갱신하면 옛 날짜에 새 가격이 붙어 '언제 본 값인지'가 거짓이 됩니다.",
      };
    }
    body.ask_price_krw = price;
    // 날짜가 그대로여도 **반드시 함께** 보낸다(서버 계약: 두 필드는 분리될 수 없다).
    body.as_of = asOf;
  } else if (asOf !== "" && asOf !== before.as_of) {
    body.as_of = asOf;
  }

  const area = values.areaM2.trim();
  if (area !== "" && Number(area) !== before.area_m2) body.area_m2 = Number(area);

  const floor = values.floor.trim();
  const beforeFloor = before.floor ?? null;
  if (floor === "") {
    if (beforeFloor !== null) body.floor = null; // 비우기
  } else if (Number(floor) !== beforeFloor) {
    body.floor = Number(floor);
  }

  const dong = values.aptDong.trim();
  const beforeDong = before.apt_dong ?? null;
  if (dong === "") {
    if (beforeDong !== null) body.apt_dong = null;
  } else if (dong !== beforeDong) {
    body.apt_dong = dong;
  }

  const note = values.note.trim();
  const beforeNote = before.note ?? null;
  if (note === "") {
    if (beforeNote !== null) body.note = null;
  } else if (note !== beforeNote) {
    body.note = note;
  }

  if (Object.keys(body).length === 0) {
    return { error: "바뀐 내용이 없습니다." };
  }
  return { body };
}

/** '거래됨/내림'으로 옮기기 — 지우지 않고 추천에서만 뺀다. */
export function statusPatch(status: "active" | "traded" | "withdrawn"): UserListingPatch {
  return { status };
}

/* ── 서버 422 → 어느 칸이 틀렸나 ──────────────────────────────────────── */

/** 서버 `loc` 이름 → 폼 필드. 모르는 이름은 버린다(내부 식별자를 화면에 내지 않는다). */
const SERVER_FIELD_MAP: Record<string, ListingField> = {
  ask_price_krw: "askPriceKrw",
  area_m2: "areaM2",
  floor: "floor",
  apt_dong: "aptDong",
  as_of: "asOf",
  note: "note",
};

/**
 * pydantic 422 의 `fields`·`problems` 를 **해당 입력 옆에** 붙일 수 있게 짝지어 준다.
 * 폼 위에 한 줄로 뭉뚱그리면 어느 칸을 고쳐야 하는지 알 수 없다.
 * 모르는 필드 이름은 조용히 버린다 — 화면에는 이미 전체 메시지가 따로 떠 있다.
 */
export function serverFieldErrors(
  fields: string[] | undefined,
  problems: string[] | undefined,
): ListingErrors {
  const out: ListingErrors = {};
  if (!fields || !problems) return out;
  fields.forEach((name, i) => {
    const key = SERVER_FIELD_MAP[name];
    const msg = problems[i];
    if (key && msg && !out[key]) out[key] = msg;
  });
  return out;
}
