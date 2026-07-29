/**
 * 테스트용 **목(mock) 응답을 한 곳에** 모은다.
 *
 * 왜 모으나 — 2026-07-29 사고: 서버가 반영 여부 필드를 `eligible_for_recommendation` 으로
 * 바꿨는데(옛 이름은 "추천에 사용됨"), 목이 파일마다 흩어져 있어서
 * **필드명이 틀려도 프론트 테스트는 전부 초록**이었다. 타입은 런타임 응답을 못 잡고,
 * 목이 곧 계약의 그림자라 그림자가 낡으면 아무도 모른다.
 *
 * 그래서 두 가지를 함께 둔다:
 *  ① 목은 여기서만 만든다(파일마다 따로 적지 않는다).
 *  ② `apiContract.test.ts` 가 이 목을 **`docs/02-design/api-spec.md` 의 예시와 대조**한다.
 *     계약이 바뀌면 화면 테스트가 아니라 **그 테스트가 먼저** 깨진다.
 *
 * ⚠️ 여기 값을 "테스트가 통과하도록" 고치지 마라. 계약이 바뀐 것이면 문서가 정본이고,
 *    문서와 맞춘 뒤 화면을 고치는 순서다.
 */
import type { UserListing, UserListingItem, UserListingList } from "../api/client";

/* ── 서버가 항상 싣는 고정 고지 (routes.py::LISTING_*_NOTE) ────────────────
 * 화면은 이 문장을 **만들지 않는다**. 목에 적어 두는 이유는 "서버가 준 것을 그대로
 * 렌더하는지"를 검사하기 위해서다(문구 자체를 프론트가 소유하지 않는다). */

export const LISTING_SOURCE_NOTE =
  "이 호가는 **사용자가 직접 보고 입력한 값**입니다(공공 데이터가 아닙니다). " +
  "실거래가와 다르며, 매물이 이미 팔렸거나 가격이 바뀌었을 수 있습니다.";

/** `eligible_for_recommendation` 이 답하지 **못하는** 절반. 서버가 조건 없이 항상 보낸다. */
export const LISTING_ELIGIBILITY_NOTE =
  "'추천 반영 가능'은 이 호가가 활성이고 낡지 않았다는 뜻입니다 — " +
  "**실제로 반영되려면 그 단지가 추천 요청의 지역·예산·평수 조건과 후보 조회 상한을 " +
  "통과해야 합니다.** 지역을 좁혀 요청하면 잡힐 가능성이 높아집니다.";

export const LISTING_NOTES = [LISTING_SOURCE_NOTE, LISTING_ELIGIBILITY_NOTE];

/** 오늘 기준 n일 전(YYYY-MM-DD). 고정 날짜를 쓰면 언젠가 365일을 넘겨 목이 썩는다. */
export function daysAgo(n: number, now: Date = new Date()): string {
  const d = new Date(now);
  d.setDate(d.getDate() - n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

/**
 * 호가 1건. **키 구성은 api-spec §2.5 의 201 예시와 같아야 한다**(대조 테스트가 본다).
 * 값은 예시와 같은 값을 쓰되 `as_of` 만 오늘 기준 상대 날짜다(위 주석).
 */
export function userListing(over: Partial<UserListing> = {}): UserListing {
  return {
    id: 7,
    complex_id: 1234,
    complex_name: "○○아파트",
    ask_price_krw: 1_480_000_000,
    area_m2: 84.97,
    floor: 9,
    apt_dong: "101동",
    as_of: daysAgo(1),
    note: "네이버 부동산 · ○○공인",
    status: "active",
    source: "user_entered",
    source_label: "사용자 입력",
    age_days: 1,
    staleness: "fresh",
    eligible_for_recommendation: true,
    price_per_m2_krw: 17_417_912,
    created_at: "2026-07-29T09:00:00Z",
    updated_at: "2026-07-29T09:00:00Z",
    ...over,
  };
}

/** 단건 응답(201·200). `problems` 는 비어도 키가 있고, `notes` 는 **항상** 온다. */
export function userListingItem(
  item: UserListing = userListing(),
  problems: string[] = [],
): UserListingItem {
  return { item, problems, notes: LISTING_NOTES };
}

/** 목록 응답. summary 는 서버가 세는 방식대로 항목에서 유도한다(손으로 적지 않는다). */
export function userListingList(
  items: UserListing[] = [userListing()],
  over: Partial<UserListingList> = {},
): UserListingList {
  const stale = items.filter((i) => i.staleness === "stale").length;
  return {
    items,
    summary: {
      total: items.length,
      fresh: items.filter((i) => i.staleness === "fresh").length,
      aging: items.filter((i) => i.staleness === "aging").length,
      stale,
      inactive: items.filter((i) => i.status !== "active").length,
      eligible_for_recommendation: items.filter((i) => i.eligible_for_recommendation).length,
    },
    notes: stale
      ? [...LISTING_NOTES, `${stale}건은 낡아서 추천에 반영되지 않습니다.`]
      : LISTING_NOTES,
    ...over,
  };
}

/** 빈 목록(첫 사용자). */
export function emptyUserListingList(): UserListingList {
  return userListingList([]);
}
