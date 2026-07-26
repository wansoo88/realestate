/**
 * bbox 문자열 — 지도 범위를 다루는 **단 하나의 형식**.
 *
 * 형식은 `minLon,minLat,maxLon,maxLat` 로 `/map/complexes` 와 동일하다
 * (api-spec: 추천의 `bbox` 도 같은 형식). 같은 문자열을 두 엔드포인트가 나눠 쓰므로
 * **여기서 만들지 않는다** — 지도가 준 값을 그대로 옮긴다. 화면이 자체 계산으로
 * bbox 를 다시 만들면 지도가 보는 범위와 서버가 찾는 범위가 조용히 어긋난다.
 *
 * 이 모듈이 하는 일은 셋뿐이다.
 *  ① **검증** — 형식이 깨진 값을 보내면 서버는 422 다. 보내기 전에 걸러낸다.
 *  ② **사람 말로 크기 설명** — "126.9,37.4,127.0,37.6" 은 사용자에게 아무 뜻이 없다.
 *  ③ **같은 범위인지 비교** — 지도를 옮겼는지(= 잡아둔 범위가 낡았는지) 판단하는 근거.
 */

export interface Bbox {
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
}

/** 순수 십진수만 허용한다. `Number()` 는 ""·"0x10"·"Infinity" 를 조용히 통과시킨다. */
const DECIMAL_RE = /^-?\d+(\.\d+)?([eE][-+]?\d+)?$/;

/**
 * 지도 이동으로 보기엔 너무 작은 차이(약 0.1m). 카카오 SDK 가 같은 자리에서
 * 부동소수 끝자리를 흔들어도 "옮겼다"고 말하지 않기 위한 여유값이다.
 */
const SAME_EPS = 1e-6;

/** 위경도 1도당 거리(km). 위도는 상수, 경도는 위도에 따라 줄어든다(cos 보정). */
const KM_PER_LAT_DEG = 110.574;
const KM_PER_LON_DEG_AT_EQUATOR = 111.32;

/**
 * 한 변의 상한(도) — **서버 계약의 복제본이고 정본은 서버다**
 * (api-spec `POST /recommendations` 입력 검증: 한 변 2.0도 이하. `/map/complexes` 도 같다).
 *
 * 왜 `parseBbox` 안에 넣지 않았나 — 이게 이 값에서 가장 중요한 판단이다.
 * `parseBbox` 가 null 을 주면 `isBbox` 가 false 가 되고, 그러면 `searchScope.scopeFields` 는
 * **bbox 를 빼고** 요청을 보낸다. 즉 "너무 넓다"가 조용히 **"범위 제한 없음(전국)"** 으로
 * 바뀐다 — 좁히려고 누른 버튼이 범위를 최대로 넓히는, 이 프로젝트가 가장 경계하는 실패다.
 * 그래서 크기 초과는 **형식 오류가 아니라 별도의 보이는 상태**로 다룬다:
 *   ① 화면이 미리 막고 사유를 적는다(AreaScope) → 사용자가 확대해서 스스로 고친다.
 *   ② 그래도 서버가 거절하면(상한이 서로 어긋난 배포) 422/400 을 이 사유로 번역한다.
 * 값이 어긋나도 ②가 남으므로 프론트 상수는 **안내용**이지 판정의 최종 근거가 아니다.
 */
export const MAX_BBOX_SIDE_DEG = 2.0;

/**
 * bbox 문자열 → 숫자 4개. 형식·범위가 조금이라도 어긋나면 **null**(예외를 던지지 않는다 —
 * 호출부가 대부분 "쓸 수 있나?"만 묻기 때문).
 */
export function parseBbox(value: string | null | undefined): Bbox | null {
  if (typeof value !== "string") return null;
  const parts = value.split(",");
  if (parts.length !== 4) return null;

  const nums: number[] = [];
  for (const raw of parts) {
    const t = raw.trim();
    if (!DECIMAL_RE.test(t)) return null;
    const n = Number(t);
    if (!Number.isFinite(n)) return null;
    nums.push(n);
  }

  const [minLon, minLat, maxLon, maxLat] = nums;
  if (minLon < -180 || maxLon > 180 || minLat < -90 || maxLat > 90) return null;
  // 뒤집힌 범위(min ≥ max)는 "빈 영역"이라 조회 결과가 항상 0건이 된다 — 형식 오류로 본다.
  if (minLon >= maxLon || minLat >= maxLat) return null;

  return { minLon, minLat, maxLon, maxLat };
}

export function isBbox(value: string | null | undefined): boolean {
  return parseBbox(value) !== null;
}

/** 한 변의 크기(도). 읽을 수 없는 값이면 null. */
export function bboxSideDeg(value: string | null | undefined): { lon: number; lat: number } | null {
  const b = parseBbox(value);
  if (!b) return null;
  return { lon: b.maxLon - b.minLon, lat: b.maxLat - b.minLat };
}

/**
 * 서버가 거절할 만큼 넓은가.
 *
 * ⚠️ **읽을 수 없는 값은 false 다.** "형식이 깨졌다"와 "너무 넓다"는 다른 사실이고,
 * 전자는 `isBbox` 가 말한다. 여기서 뭉뚱그리면 호출부가 엉뚱한 사유를 보여준다.
 */
export function bboxTooLarge(value: string | null | undefined): boolean {
  const side = bboxSideDeg(value);
  if (!side) return false;
  return side.lon > MAX_BBOX_SIDE_DEG || side.lat > MAX_BBOX_SIDE_DEG;
}

/**
 * 왜 못 쓰는지 사람 말로. 넓지 않으면 null(할 말이 없다).
 * 상한을 도(度)로만 말하면 아무도 못 읽으므로 **km 로 환산한 크기**를 함께 적는다.
 */
export function bboxTooLargeReason(value: string | null | undefined): string | null {
  if (!bboxTooLarge(value)) return null;
  const size = bboxSizeText(value);
  return `지금 지도 범위${size ? `(${size})` : ""}가 너무 넓어 검색할 수 없습니다 — 지도를 확대한 뒤 다시 잡아 주세요.`;
}

/** 소수 한 자리까지, 10 이상이면 정수로(0.4km · 4.2km · 27km). */
function km(n: number): string {
  return n >= 10 ? String(Math.round(n)) : (Math.round(n * 10) / 10).toFixed(1);
}

/**
 * 범위 크기를 사람 말로: `약 4.2 × 3.1km`.
 * 좌표를 그대로 보여주면 아무도 못 읽는다. 크기만이라도 있어야 "내가 잡은 게 동네인지 시 전체인지"를 안다.
 */
export function bboxSizeText(value: string | null | undefined): string | null {
  const b = parseBbox(value);
  if (!b) return null;
  const midLat = ((b.minLat + b.maxLat) / 2) * (Math.PI / 180);
  const widthKm = (b.maxLon - b.minLon) * KM_PER_LON_DEG_AT_EQUATOR * Math.cos(midLat);
  const heightKm = (b.maxLat - b.minLat) * KM_PER_LAT_DEG;
  return `약 ${km(Math.abs(widthKm))} × ${km(heightKm)}km`;
}

/**
 * 두 범위가 사실상 같은가. 파싱되지 않는 값은 **문자열이 완전히 같을 때만** 같다고 본다
 * (둘 다 null 인 경우를 "같다"로 처리해야 호출부가 조건을 두 번 쓰지 않는다).
 */
export function sameBbox(a: string | null | undefined, b: string | null | undefined): boolean {
  if (a === b) return true;
  const pa = parseBbox(a);
  const pb = parseBbox(b);
  if (!pa || !pb) return false;
  return (
    Math.abs(pa.minLon - pb.minLon) < SAME_EPS &&
    Math.abs(pa.minLat - pb.minLat) < SAME_EPS &&
    Math.abs(pa.maxLon - pb.maxLon) < SAME_EPS &&
    Math.abs(pa.maxLat - pb.maxLat) < SAME_EPS
  );
}
