/**
 * "어디에서 찾을까" — 추천의 **검색 범위**를 한 곳에서 만든다.
 *
 * 범위를 정하는 길이 두 개가 됐다.
 *  ① `region_codes` — 시군구를 골라서 (RegionPicker)
 *  ② `bbox` — **지금 지도에서 보고 있는 자리**로 (AreaScope, "이 주변에서 찾기")
 *
 * 서버 계약(api-spec `POST /recommendations`)
 *  - `bbox` 만 → 그 범위에서
 *  - 둘 다 → **교집합**(두 조건을 모두 만족하는 단지)
 *  - 둘 다 없으면 전체
 *
 * 왜 순수 모듈인가: 요청에 실리는 필드와 화면에 적히는 문구가 **같은 상태에서** 나와야 한다.
 * 둘이 갈라지면 화면이 "강남구에서 찾는 중"이라고 말하는 동안 서버는 전체를 뒤진다
 * (mapFilters.ts 가 같은 이유로 쿼리와 칩을 한 함수에서 만든다).
 */
import { bboxSizeText, isBbox } from "./bbox";
import { regionByCode, regionLabel } from "./regions";

export interface SearchScope {
  /** 5자리 시군구. 빈 배열 = 지역 제한 없음. */
  regionCodes: string[];
  /** "이 주변"으로 잡아 둔 지도 범위. null = 쓰지 않음. */
  bbox: string | null;
}

/** 서버로 나갈 필드. 이름은 **계약 그대로**(snake_case) 쓴다. */
export interface ScopeFields {
  region_codes: string[];
  bbox?: string;
}

/**
 * 요청에 실을 필드.
 *
 * ⚠️ 형식이 유효한 bbox 만 싣는다. 깨진 값을 보내면 서버는 422 이고, 사용자에겐
 * "분석에 필요한 조건이 부족합니다"로만 보인다 — 원인을 알 길이 없는 실패가 된다.
 */
export function scopeFields(scope: SearchScope): ScopeFields {
  const fields: ScopeFields = { region_codes: scope.regionCodes };
  if (scope.bbox !== null && isBbox(scope.bbox)) fields.bbox = scope.bbox;
  return fields;
}

/** 실제로 보낸 것만 남긴 범위 — 화면 문구가 요청과 어긋나지 않게 여기서 되돌려 만든다. */
export function appliedScope(scope: SearchScope): SearchScope {
  const fields = scopeFields(scope);
  return { regionCodes: fields.region_codes, bbox: fields.bbox ?? null };
}

/** 코드 → 이름. 모르는 코드는 지어내지 않고 코드를 그대로 보여준다. */
function nameOf(code: string): string {
  const region = regionByCode(code);
  return region ? regionLabel(region) : code;
}

/** 지역 이름 나열. 셋 이상은 "외 N곳"으로 줄인다(칩 줄바꿈이 문장을 삼키지 않게). */
export function regionNames(codes: string[]): string {
  if (codes.length === 0) return "";
  if (codes.length <= 2) return codes.map(nameOf).join(" · ");
  return `${nameOf(codes[0])} 외 ${codes.length - 1}곳`;
}

/** bbox 부분의 표기: `이 주변(약 4.2 × 3.1km)`. 크기를 못 재면 크기만 뺀다. */
function areaText(bbox: string): string {
  const size = bboxSizeText(bbox);
  return size ? `이 주변(${size})` : "이 주변";
}

/**
 * 지금 범위를 한 줄로. 교집합 기호(∩)를 쓰는 이유: "이 주변 **그리고** 강남구"라는
 * 뜻이 한눈에 보여야 한다. 나열(·)로 쓰면 합집합으로 읽힌다.
 */
export function scopeText(scope: SearchScope): string {
  const hasBbox = scope.bbox !== null && isBbox(scope.bbox);
  const names = regionNames(scope.regionCodes);
  if (hasBbox && names) return `${areaText(scope.bbox as string)} ∩ ${names}`;
  if (hasBbox) return areaText(scope.bbox as string);
  if (names) return names;
  return "수도권 전체";
}

/** 둘 다 걸렸을 때만 나오는 안내. 교집합은 설명 없이는 오해된다. */
export function intersectionNote(scope: SearchScope): string | null {
  const hasBbox = scope.bbox !== null && isBbox(scope.bbox);
  if (!hasBbox || scope.regionCodes.length === 0) return null;
  return "두 조건을 모두 만족하는 단지만 찾습니다(교집합).";
}
