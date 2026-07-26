/**
 * 장소·역 검색 — **지도를 옮기기 위한 것**. 그 이상이 아니다.
 *
 * 왜 REST API 를 안 쓰나 (중요)
 * ----------------------------
 * 카카오 로컬 REST API 를 브라우저에서 직접 부르면 두 가지가 동시에 깨진다.
 *   ① `KAKAO_REST_API_KEY` 는 **서버 전용 비밀키**다. 프론트 번들에 넣는 순간 공개된다.
 *   ② CSP 가 `connect-src 'self'` 라 브라우저가 요청 자체를 막는다.
 * 그래서 **JS SDK 의 `services` 라이브러리**만 쓴다. SDK 는 이미 허용된 출처
 * (`script-src https://dapi.kakao.com`)에서 로드되고, JS 앱키로 동작한다.
 *
 * ⚠️ 운영 확인 필요(보고 항목): `services.Places` 가 내부적으로 XHR 을 쓰면
 *    `connect-src 'self'` 에 막힌다(JSONP 면 `script-src` 로 통과). 실브라우저 검증 전까지는
 *    **실패를 조용히 삼키지 않고** 사용자에게 상태를 알린다(아래 `PlaceSearchError`).
 *
 * ⚠️ 이것은 "역세권 분석"이 아니다. 우리 `poi` 테이블은 0행이라 역 기반 필터·분석은
 *    존재하지 않는다. 이 기능은 **지도 이동**만 한다 — UI 문구도 그렇게 적는다.
 */

export interface Place {
  id: string;
  name: string;
  /** 지번/도로명 등 보조 설명. 같은 이름의 역이 여러 개일 때 구분용. */
  detail: string;
  /** [경도, 위도] — 우리 좌표 규약(api-spec)과 같은 순서로 정규화해서 내보낸다. */
  point: [number, number];
}

export type PlaceSearchError =
  /** SDK 의 services 라이브러리가 없다(로드 실패·차단) */
  | "unavailable"
  /** 검색은 됐는데 결과가 0건 */
  | "empty"
  /** 그 외 실패(네트워크·CSP 차단 등) */
  | "failed";

/** 카카오 services 를 느슨하게 타입핑한다(전용 타입 패키지를 쓰지 않는다). */
interface PlacesLike {
  keywordSearch(
    keyword: string,
    cb: (data: unknown[], status: string) => void,
    opts?: Record<string, unknown>,
  ): void;
}

interface ServicesLike {
  Places: new () => PlacesLike;
  Status: { OK: string; ZERO_RESULT: string; ERROR: string };
}

export function getServices(): ServicesLike | null {
  const s = (window as { kakao?: { maps?: { services?: ServicesLike } } }).kakao?.maps?.services;
  return s && typeof s.Places === "function" ? s : null;
}

/**
 * 문자열 좌표 → 숫자. **빈 문자열을 0 으로 받지 않는다.**
 * `Number("")` 는 0 이고 `Number.isFinite(0)` 은 true 라, 그냥 넘기면 좌표가 빈 결과를
 * "위도 0, 경도 0"(기니만 앞바다)으로 읽어 지도가 통째로 날아간다. 테스트가 이걸 잡았다.
 */
function coord(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v !== "string" || v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** SDK 응답 1건 → 우리 타입. 좌표는 문자열로 오므로 숫자로 바꾸고 순서를 뒤집지 않는다. */
export function toPlace(row: Record<string, unknown>): Place | null {
  const lng = coord(row.x);
  const lat = coord(row.y);
  if (lng === null || lat === null) return null;
  const name = typeof row.place_name === "string" ? row.place_name : "";
  if (name === "") return null;
  const detail =
    (typeof row.road_address_name === "string" && row.road_address_name) ||
    (typeof row.address_name === "string" && row.address_name) ||
    "";
  return {
    id: String(row.id ?? `${name}-${lng},${lat}`),
    name,
    detail,
    // 카카오는 x=경도, y=위도. 우리 규약도 [경도, 위도] — 여기서 뒤집으면 태평양으로 간다(CR18-5).
    point: [lng, lat],
  };
}

export interface PlaceSearchResult {
  places: Place[];
  error: PlaceSearchError | null;
}

/**
 * 키워드로 장소를 찾는다(역·건물·동 이름 등).
 *
 * 콜백 API 를 Promise 로 감싼다 — 화면에서 콜백 중첩을 만들지 않기 위해서다.
 * **절대 throw 하지 않는다.** 검색 실패는 예외가 아니라 화면에 보여줄 상태다.
 */
export function searchPlaces(keyword: string, limit = 8): Promise<PlaceSearchResult> {
  const q = keyword.trim();
  if (q === "") return Promise.resolve({ places: [], error: null });

  const services = getServices();
  if (!services) return Promise.resolve({ places: [], error: "unavailable" });

  return new Promise((resolve) => {
    try {
      new services.Places().keywordSearch(q, (data, status) => {
        if (status === services.Status.OK) {
          const places = (data as Record<string, unknown>[])
            .map(toPlace)
            .filter((p): p is Place => p !== null)
            .slice(0, limit);
          resolve({ places, error: places.length === 0 ? "empty" : null });
          return;
        }
        resolve({ places: [], error: status === services.Status.ZERO_RESULT ? "empty" : "failed" });
      });
    } catch {
      // SDK 가 예외를 던지는 경우(차단·버전 차이)에도 화면은 살아 있어야 한다.
      resolve({ places: [], error: "failed" });
    }
  });
}

/** 사용자에게 보여줄 문구. 실패를 조용히 삼키지 않는다. */
export function placeErrorText(error: PlaceSearchError): string {
  switch (error) {
    case "unavailable":
      return "장소 검색을 사용할 수 없습니다(지도 SDK 미로드).";
    case "empty":
      return "검색 결과가 없습니다.";
    default:
      return "장소 검색에 실패했습니다. 잠시 후 다시 시도해 주세요.";
  }
}
