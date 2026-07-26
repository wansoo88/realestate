/**
 * bbox 검증·비교 — **서버로 나가기 전 마지막 관문**이다.
 * 여기가 느슨하면 깨진 값이 그대로 나가 422 가 되고, 사용자는 이유를 알 수 없다.
 */
import { describe, expect, it } from "vitest";
import {
  MAX_BBOX_SIDE_DEG,
  bboxSideDeg,
  bboxSizeText,
  bboxTooLarge,
  bboxTooLargeReason,
  isBbox,
  parseBbox,
  sameBbox,
} from "./bbox";

const SEOUL = "126.9,37.4,127.0,37.6";
/** 한 변 3도 — 서버 상한(2.0도)을 넘는다. 줌아웃 상태의 지도가 이렇게 된다. */
const HUGE = "125.0,36.0,128.0,38.0";

describe("parseBbox", () => {
  it("정상 값을 minLon,minLat,maxLon,maxLat 순서로 읽는다", () => {
    expect(parseBbox(SEOUL)).toEqual({
      minLon: 126.9,
      minLat: 37.4,
      maxLon: 127.0,
      maxLat: 37.6,
    });
  });

  it("조각 수가 4개가 아니면 거부한다", () => {
    expect(parseBbox("126.9,37.4,127.0")).toBeNull();
    expect(parseBbox("126.9,37.4,127.0,37.6,1")).toBeNull();
  });

  it("빈 조각을 0 으로 통과시키지 않는다 (Number('') === 0 함정)", () => {
    expect(parseBbox("126.9,,127.0,37.6")).toBeNull();
    expect(parseBbox(",,,")).toBeNull();
  });

  it("숫자가 아닌 값을 거부한다 (Number 가 조용히 받아주는 형태 포함)", () => {
    expect(parseBbox("bad")).toBeNull();
    expect(parseBbox("0x10,37.4,127.0,37.6")).toBeNull();
    expect(parseBbox("Infinity,37.4,127.0,37.6")).toBeNull();
    expect(parseBbox("126.9,NaN,127.0,37.6")).toBeNull();
  });

  it("뒤집힌 범위(min ≥ max)는 형식 오류로 본다 — 결과가 항상 0건이 된다", () => {
    expect(parseBbox("127.0,37.4,126.9,37.6")).toBeNull();
    expect(parseBbox("126.9,37.6,127.0,37.4")).toBeNull();
    expect(parseBbox("126.9,37.4,126.9,37.6")).toBeNull();
  });

  it("지구 밖 좌표를 거부한다", () => {
    expect(parseBbox("-181,37.4,127.0,37.6")).toBeNull();
    expect(parseBbox("126.9,37.4,127.0,91")).toBeNull();
  });

  it("문자열이 아니면 null", () => {
    expect(parseBbox(null)).toBeNull();
    expect(parseBbox(undefined)).toBeNull();
  });

  it("음수 좌표와 지수 표기도 정상으로 받는다", () => {
    expect(parseBbox("-1.5,-2.5,1e0,2.5")).toEqual({
      minLon: -1.5,
      minLat: -2.5,
      maxLon: 1,
      maxLat: 2.5,
    });
  });
});

describe("isBbox", () => {
  it("parseBbox 와 같은 판단을 준다", () => {
    expect(isBbox(SEOUL)).toBe(true);
    expect(isBbox("bad")).toBe(false);
    expect(isBbox(null)).toBe(false);
  });
});

describe("bboxSizeText", () => {
  it("좌표 대신 사람이 읽는 크기를 준다", () => {
    // 위도 37.5 부근: 경도 0.1도 ≈ 8.8km, 위도 0.2도 ≈ 22.1km
    expect(bboxSizeText(SEOUL)).toBe("약 8.8 × 22km");
  });

  it("동네 크기는 소수 한 자리로 남긴다(0km 로 뭉개지 않는다)", () => {
    const text = bboxSizeText("126.98,37.56,127.0,37.57");
    expect(text).toMatch(/^약 1\.8 × 1\.1km$/);
  });

  it("읽을 수 없는 값에는 크기를 지어내지 않는다", () => {
    expect(bboxSizeText("bad")).toBeNull();
    expect(bboxSizeText(null)).toBeNull();
  });
});

/**
 * 면적 상한 — 서버는 한 변 2.0도 초과를 422(지도는 400)로 막는다.
 *
 * ⚠️ 이 검사를 `parseBbox` 안에 넣으면 안 된다. null 이 되는 순간 `searchScope.scopeFields`
 * 가 bbox 를 **빼고** 보내므로, "너무 넓다"가 조용히 "범위 제한 없음(전국)"이 된다.
 * 아래 첫 테스트가 그 성질을 고정한다.
 */
describe("bbox 면적 상한", () => {
  it("상한을 넘어도 **형식으로는 유효하다** — 조용히 버려져 전국 검색이 되면 안 된다", () => {
    expect(parseBbox(HUGE)).not.toBeNull();
    expect(isBbox(HUGE)).toBe(true);
  });

  it("한 변 크기를 도 단위로 준다", () => {
    expect(bboxSideDeg(HUGE)).toEqual({ lon: 3, lat: 2 });
    expect(bboxSideDeg("bad")).toBeNull();
  });

  it("경도·위도 어느 한 변이라도 넘으면 '너무 넓다'", () => {
    expect(bboxTooLarge(HUGE)).toBe(true); // 경도 3도
    expect(bboxTooLarge("126,36,127,38.5")).toBe(true); // 위도 2.5도
    expect(bboxTooLarge(SEOUL)).toBe(false);
  });

  it("정확히 상한(2.0도)은 통과한다 — 서버 계약이 '이하'다", () => {
    expect(bboxTooLarge(`126,36,${126 + MAX_BBOX_SIDE_DEG},${36 + MAX_BBOX_SIDE_DEG}`)).toBe(false);
  });

  it("읽을 수 없는 값은 '너무 넓다'가 아니다(형식 오류와 다른 사실이다)", () => {
    expect(bboxTooLarge("bad")).toBe(false);
    expect(bboxTooLarge(null)).toBe(false);
    expect(bboxTooLargeReason(null)).toBeNull();
  });

  it("사유 문장에는 **고칠 방법**과 지금 크기가 함께 들어간다", () => {
    const reason = bboxTooLargeReason(HUGE)!;
    expect(reason).toContain("확대");
    expect(reason).toContain("km"); // 도(度)로만 말하면 아무도 못 읽는다
    expect(bboxTooLargeReason(SEOUL)).toBeNull();
  });
});

describe("sameBbox", () => {
  it("같은 자리의 부동소수 잔떨림은 '옮겼다'로 보지 않는다", () => {
    expect(sameBbox(SEOUL, "126.90000000001,37.4,127.0,37.6")).toBe(true);
  });

  it("실제로 옮기면 다르다고 말한다", () => {
    expect(sameBbox(SEOUL, "126.95,37.4,127.05,37.6")).toBe(false);
    // 약 11m 이동도 다른 범위다(문턱은 0.1m 수준)
    expect(sameBbox(SEOUL, "126.9001,37.4,127.0,37.6")).toBe(false);
  });

  it("둘 다 없으면 같다(호출부가 null 을 따로 다루지 않게)", () => {
    expect(sameBbox(null, null)).toBe(true);
  });

  it("한쪽만 없으면 다르다", () => {
    expect(sameBbox(SEOUL, null)).toBe(false);
    expect(sameBbox(null, SEOUL)).toBe(false);
  });
});
