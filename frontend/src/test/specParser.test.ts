/**
 * **검사를 검사한다** — 계약 파서가 정말 범위를 지키는가 (CR37-2).
 *
 * `apiContract.test.ts` 는 "문서와 목이 같은가"를 본다. 그런데 그 검사는 **파서가 옳다는
 * 가정** 위에 서 있고, 리뷰가 확인한 대로 옛 파서는 그 가정을 배신했다:
 * `api-spec §4` 의 군집 예시를 통째로 지워도 **옆 예시를 대신 읽고 17 passed** 였다.
 *
 * 그래서 여기서는 **진짜 `api-spec.md` 를 훼손한 사본**을 만들어 파서를 때린다.
 * 문서를 손으로 지웠다 되돌리는 검증은 한 번뿐이고 기록도 안 남지만, 이건 매 실행마다
 * 다시 돈다 — 다음 사람이 파서를 "간단히" 되돌리면 여기서 걸린다.
 *
 * ⚠️ 이 파일은 원본 문서를 **읽기만** 한다. 변이는 전부 메모리 안의 문자열이다.
 */
import { describe, expect, it } from "vitest";
import spec from "../../../docs/02-design/api-spec.md?raw";
import { firstJsonObjectAfter, jsonBlockAfter, SpecParseError } from "./specParser";

const CLUSTER = "// res 200 — zoom < 13 : 군집(클러스터)";
const COMPLEX = "// res 200 — zoom >= 13 : 단지 단위";
const LIST = "#### `GET /me/listings?complex_id=`";

/**
 * "사람이 예시를 지웠다"와 같은 변이 — 마커 **다음 줄부터 빈 줄(또는 펜스) 직전까지** 지운다.
 * 마커는 남긴다: 리뷰가 실측한 그 형태(마커만 남고 예시가 사라진 상태)를 그대로 재현한다.
 */
function dropExampleAfter(text: string, marker: string): string {
  const lines = text.split("\n");
  const i = lines.findIndex((l) => l.includes(marker));
  expect(i, `변이 대상 '${marker}' 를 문서에서 못 찾았다`).toBeGreaterThan(-1);

  let j = i + 1;
  while (j < lines.length && lines[j].trim() !== "" && !lines[j].startsWith("```")) j += 1;
  return [...lines.slice(0, i + 1), ...lines.slice(j)].join("\n");
}

/** 절 하나의 ```json 블록을 통째로 지운다(절 안에 예시가 0개인 상태). */
function dropFenceAfter(text: string, marker: string): string {
  const lines = text.split("\n");
  const i = lines.findIndex((l) => l.includes(marker));
  expect(i, `변이 대상 '${marker}' 를 문서에서 못 찾았다`).toBeGreaterThan(-1);

  let s = i + 1;
  while (s < lines.length && !lines[s].startsWith("```json")) s += 1;
  let e = s + 1;
  while (e < lines.length && !lines[e].startsWith("```")) e += 1;
  return [...lines.slice(0, s), ...lines.slice(e + 1)].join("\n");
}

describe("원본 문서는 그대로 읽힌다 (변이 검사의 기준선)", () => {
  it("§4 의 두 예시를 **각각 제 것으로** 읽는다", () => {
    // 판별자까지 못박는다: 파서가 옆 예시를 읽으면 여기서도 드러난다.
    expect(firstJsonObjectAfter(spec, CLUSTER).level).toBe("cluster");
    expect(firstJsonObjectAfter(spec, COMPLEX).level).toBe("complex");
  });

  it("§2.5 목록 예시도 읽힌다", () => {
    expect(Object.keys(jsonBlockAfter(spec, LIST))).toContain("summary");
  });
});

describe("변이 — 예시를 지우면 **죽어야 한다** (CR37-2 재현)", () => {
  it("군집 예시만 지우면 죽는다 — 옆(단지) 예시를 대신 읽지 않는다", () => {
    const mutant = dropExampleAfter(spec, CLUSTER);
    // 변이가 실제로 예시를 없앴는지부터 확인한다(안 지웠는데 통과하면 검사가 무의미하다).
    expect(mutant).not.toContain('"level": "cluster"');
    expect(mutant).toContain('"level": "complex"'); // 옆 예시는 멀쩡히 남아 있다

    expect(() => firstJsonObjectAfter(mutant, CLUSTER)).toThrow(SpecParseError);
    // **왜** 죽었는지까지 본다 — 우연히 죽는 것과 범위를 지켜서 죽는 것은 다르다.
    expect(() => firstJsonObjectAfter(mutant, CLUSTER)).toThrow(/시작하지 않는다/);
  });

  it("단지 예시만 지우면 죽는다 — 펜스 밖(§4 다음 절)까지 넘어가지 않는다", () => {
    const mutant = dropExampleAfter(spec, COMPLEX);
    expect(mutant).not.toContain('"level": "complex"');

    expect(() => firstJsonObjectAfter(mutant, COMPLEX)).toThrow(/시작하지 않는다/);
    // 군집 예시는 그대로이므로 그쪽은 계속 읽혀야 한다(과잉 살상이 아니다).
    expect(firstJsonObjectAfter(mutant, CLUSTER).level).toBe("cluster");
  });

  it("두 예시를 다 지우면 둘 다 죽는다 — 다음 절의 `{ \"id\": 1024 …}` 를 읽지 않는다", () => {
    const mutant = dropExampleAfter(dropExampleAfter(spec, CLUSTER), COMPLEX);
    expect(mutant).toContain('"id": 1024'); // 다음 절 예시는 살아 있다(읽으면 안 될 뿐)

    expect(() => firstJsonObjectAfter(mutant, CLUSTER)).toThrow(SpecParseError);
    expect(() => firstJsonObjectAfter(mutant, COMPLEX)).toThrow(SpecParseError);
  });

  it("절의 ```json 블록을 지우면 죽는다 — 다음 절의 예시를 대신 읽지 않는다", () => {
    const mutant = dropFenceAfter(spec, LIST);
    expect(mutant).not.toContain('"aging"'); // 그 절 예시가 실제로 사라졌다

    expect(() => jsonBlockAfter(mutant, LIST)).toThrow(/예시가 없다/);
  });
});

describe("변이 — 마커 자체가 흔들릴 때", () => {
  it("마커가 사라지면 죽는다", () => {
    const mutant = spec.replace(CLUSTER, "// (설명 삭제)");
    expect(() => firstJsonObjectAfter(mutant, CLUSTER)).toThrow(/찾지 못했다/);
  });

  it("마커가 두 번 나오면 죽는다 — 어느 예시를 읽었는지 모르는 채 통과시키지 않는다", () => {
    // 복붙으로 예시가 하나 더 생기는 상황. 옛 파서는 조용히 앞엣것을 읽었다.
    const mutant = `${spec}\n\n\`\`\`json\n${CLUSTER}\n{ "level": "cluster" }\n\`\`\`\n`;
    expect(() => firstJsonObjectAfter(mutant, CLUSTER)).toThrow(/두 번 이상/);
  });

  it("마커가 펜스 밖으로 나가면 죽는다", () => {
    // 예시를 지우고 마커만 산문으로 옮겨 적은 상태.
    const mutant = `${spec}\n\n설명 문단: ${CLUSTER} 는 군집 응답이다.\n`.replace(CLUSTER, "// (설명 삭제)");
    expect(() => firstJsonObjectAfter(mutant, CLUSTER)).toThrow(SpecParseError);
  });
});
