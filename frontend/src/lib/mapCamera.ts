/**
 * 지도가 마지막으로 보고 있던 자리 — **모듈 메모리**에만 둔다.
 *
 * 왜 필요한가: "내 조건"을 고치면 조건 화면이 지도를 덮고, 저장하면 지도가 다시 마운트된다
 * (이 재마운트는 의도적이다 — 예산·선호가 바뀌었으니 실구매 가능 금액부터 다시 계산해야 한다).
 * 그런데 그때마다 지도가 서울시청으로 되돌아가면, **강남을 보다가 조건 하나 고쳤더니 시청**이다.
 * 사용자가 "지도에서 언제든지 조건을 바꾸고 싶다"고 했으니 그 왕복이 잦아진다 — 자리를 기억한다.
 *
 * 🔐 저장소(localStorage 등)에 쓰지 않는다. 지도 위치는 "내가 어디 집을 보고 있는지"라
 * 그 자체로 사생활이다. 탭을 닫으면 사라지는 편이 맞고, 저장소 금지 원칙과도 어긋나지 않는다.
 */

export interface MapCamera {
  /** [경도, 위도] — 우리 좌표 규약(api-spec) 그대로. 카카오 LatLng 순서와 반대다. */
  center: [number, number];
  /** 카카오 level (작을수록 확대). SDK 값을 그대로 보관해 변환 실수를 줄인다. */
  level: number;
}

/** 서울시청 · level 6 — 기억이 없을 때의 첫 화면. */
export const DEFAULT_CAMERA: MapCamera = { center: [126.978, 37.5665], level: 6 };

let last: MapCamera | null = null;

export function rememberCamera(camera: MapCamera): void {
  // 값이 깨졌으면(SDK 가 NaN 을 주는 경우) 기억하지 않는다 — 다음 마운트가 통째로 망가진다.
  const [lng, lat] = camera.center;
  if (!Number.isFinite(lng) || !Number.isFinite(lat) || !Number.isFinite(camera.level)) return;
  last = { center: [lng, lat], level: camera.level };
}

export function lastCamera(): MapCamera {
  return last ?? DEFAULT_CAMERA;
}

/** 테스트·로그아웃용. 다른 계정이 내가 보던 자리를 이어받지 않게 한다. */
export function forgetCamera(): void {
  last = null;
}
