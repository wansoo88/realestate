import { beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_CAMERA, forgetCamera, lastCamera, rememberCamera } from "./mapCamera";

beforeEach(() => forgetCamera());

describe("mapCamera", () => {
  it("기억이 없으면 첫 화면(서울시청)을 준다", () => {
    expect(lastCamera()).toEqual(DEFAULT_CAMERA);
  });

  it("조건 화면을 다녀와도 보던 자리로 돌아온다", () => {
    rememberCamera({ center: [127.0276, 37.4979], level: 4 });
    expect(lastCamera()).toEqual({ center: [127.0276, 37.4979], level: 4 });
  });

  it("깨진 좌표는 기억하지 않는다(다음 마운트를 통째로 망가뜨린다)", () => {
    rememberCamera({ center: [Number.NaN, 37.5], level: 4 });
    expect(lastCamera()).toEqual(DEFAULT_CAMERA);
  });

  it("보관한 배열을 밖에서 바꿔도 기억이 오염되지 않는다", () => {
    const center: [number, number] = [127, 37.5];
    rememberCamera({ center, level: 5 });
    center[0] = 0;
    expect(lastCamera().center[0]).toBe(127);
  });

  it("로그아웃 등으로 잊으면 첫 화면으로 되돌아간다", () => {
    rememberCamera({ center: [127, 37.5], level: 3 });
    forgetCamera();
    expect(lastCamera()).toEqual(DEFAULT_CAMERA);
  });
});
