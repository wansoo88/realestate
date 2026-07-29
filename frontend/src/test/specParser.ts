/**
 * 계약 문서(`docs/02-design/api-spec.md`)에서 **예시 JSON 을 꺼내는 파서**.
 *
 * 왜 테스트 파일에서 떼어냈나 (CR37-2)
 * ------------------------------------
 * 옛 파서(`firstJsonObjectAfter`)는 마커 뒤부터 **문서 끝까지** 훑어 첫 `{` 를 찾았다.
 * 그래서 §4 처럼 한 펜스에 예시가 둘 있을 때 **앞 예시를 통째로 지워도 뒤 예시를 대신
 * 읽고 17 passed 로 조용히 통과**했다(리뷰 실측). 계약을 지키는 척만 하는 검사였다.
 *
 * 고친 방향은 "단언을 한 줄 더 넣기"가 아니라 **파서가 범위를 지키게** 하는 것이다.
 * 그리고 그 범위가 실제로 지켜지는지를 **문서를 변이시켜** 확인할 수 있도록 순수 함수로
 * 뺐다 — `specParser.test.ts` 가 진짜 `api-spec.md` 를 훼손한 사본으로 이 파서를 때린다.
 * (문서 파일을 손으로 지웠다 되돌리는 검증은 한 번뿐이고 기록도 안 남는다.)
 *
 * 이 파서가 구조로 지키는 것 세 가지
 *  ① **마커는 문서에 딱 한 번.** 두 번이면 `indexOf` 가 조용히 앞엣것을 고르고,
 *     어느 예시를 읽었는지 아무도 모른다.
 *  ② **범위에 상한이 있다.** 펜스 끝(또는 다음 제목) 밖으로는 한 글자도 넘어가지 않는다.
 *  ③ **객체는 마커 바로 다음 줄에서 시작해야 한다.** 예시가 지워지면 옆 예시를 읽는 게
 *     아니라 **죽는다**. ②만으로는 같은 펜스 안의 옆 예시를 막지 못해 ③이 필요하다.
 *
 * ⚠️ `expect` 가 아니라 **throw** 한다. 그래야 "이 변이에서 정말 죽는가"를 다시 테스트로
 *    확인할 수 있다(`expect(() => …).toThrow()`). 검사를 검사할 수 없으면 그 검사는
 *    있다는 사실 말고는 아무것도 보장하지 않는다.
 */

const FENCE = "```json";

/** 파싱 실패는 전부 이 오류다 — 테스트가 "죽었다"를 타입으로 구분할 수 있게. */
export class SpecParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SpecParseError";
  }
}

function fail(message: string): never {
  throw new SpecParseError(message);
}

/** 마커 위치. 없거나 **둘 이상**이면 죽는다(어느 예시인지 정해지지 않는다). */
function markerAt(spec: string, marker: string): number {
  const at = spec.indexOf(marker);
  if (at < 0) {
    fail(`문서에서 '${marker}' 를 찾지 못했다 — 계약 위치가 바뀌었는지 확인할 것`);
  }
  if (spec.indexOf(marker, at + marker.length) >= 0) {
    fail(`'${marker}' 가 문서에 두 번 이상 있다 — 어느 예시를 읽는지 정해지지 않는다`);
  }
  return at;
}

/**
 * `//` 주석 줄을 **줄 수를 유지한 채** 비운다.
 * 지워 버리면 줄 위치가 밀려서 "마커 바로 다음 줄" 판정이 어긋난다 — 그리고 그 어긋남이
 * 바로 CR37-2 의 구멍이다(주석을 먼저 걷어내면 옆 예시의 `{` 가 바로 다음 줄로 올라온다).
 */
function blankCommentLines(lines: string[]): string[] {
  return lines.map((line) => (line.trim().startsWith("//") ? "" : line));
}

/** `/* UserListingOut *\/` 같은 블록 주석. JSON 이 아니므로 파싱 전에 걷어낸다. */
function stripBlockComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "");
}

function parse(json: string, marker: string): Record<string, unknown> {
  try {
    return JSON.parse(json) as Record<string, unknown>;
  } catch (e) {
    fail(`'${marker}' 예시가 JSON 이 아니다: ${(e as Error).message}`);
  }
}

/**
 * `{` 부터 짝이 맞는 `}` 까지. **범위 안에서 닫히지 않으면 죽는다**(밖으로 안 나간다).
 * 문자열 안의 중괄호·이스케이프를 세지 않도록 상태를 들고 훑는다.
 */
function balancedObject(body: string, start: number): string | null {
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < body.length; i += 1) {
    const ch = body[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') inString = true;
    else if (ch === "{") depth += 1;
    else if (ch === "}") {
      depth -= 1;
      if (depth === 0) return body.slice(start, i + 1);
    }
  }
  return null;
}

/**
 * 한 펜스 안에 예시가 **둘 이상** 들어 있는 경우(§4 지도 응답: 군집 + 단지)를 위해
 * 마커 **바로 뒤에 붙은** JSON 객체 하나만 꺼낸다.
 *
 * 범위는 두 겹으로 묶인다.
 *  · 바깥: 마커를 감싸는 ```` ```json ```` 펜스의 끝. 다른 절의 예시로 넘어갈 수 없다.
 *  · 안쪽: 마커 **바로 다음 줄**. 같은 펜스 안의 옆 예시로도 넘어갈 수 없다.
 */
export function firstJsonObjectAfter(spec: string, marker: string): Record<string, unknown> {
  const at = markerAt(spec, marker);

  // ① 마커를 감싸는 펜스를 찾는다 — 마커가 예시 안에 있다는 사실부터 확인한다.
  const fenceStart = spec.lastIndexOf(FENCE, at);
  if (fenceStart < 0) {
    fail(`'${marker}' 앞에 \`\`\`json 펜스가 없다 — 마커가 예시 블록 밖에 있다`);
  }
  const fenceEnd = spec.indexOf("```", fenceStart + FENCE.length);
  if (fenceEnd < 0) fail(`'${marker}' 가 든 \`\`\`json 펜스가 닫히지 않았다`);
  if (fenceEnd < at) {
    fail(`'${marker}' 가 \`\`\`json 펜스 **밖**에 있다 — 예시가 아닌 자리를 읽으려 한다`);
  }

  // ② 객체는 마커 바로 다음 줄(빈 줄은 건너뛴다)에서 시작해야 한다.
  //    **주석을 걷어내기 전의 원문**으로 본다 — 걷어낸 뒤에 보면 옆 예시의 마커 줄이
  //    사라져 그 예시의 `{` 가 바로 다음 줄로 올라온다(그게 CR37-2 의 구멍이었다).
  const rawLines = spec.slice(at + marker.length, fenceEnd).split("\n");
  let i = rawLines[0].trim() === "" ? 1 : 0;
  while (i < rawLines.length && rawLines[i].trim() === "") i += 1;
  const head = (rawLines[i] ?? "").trim();
  if (!head.startsWith("{")) {
    fail(
      `'${marker}' 바로 뒤에서 JSON 객체가 시작하지 않는다 ` +
        `(만난 줄: ${JSON.stringify(head.slice(0, 60))}) — ` +
        `예시가 지워졌거나 옆 예시를 대신 읽으려 하고 있다`,
    );
  }

  const body = stripBlockComments(blankCommentLines(rawLines.slice(i)).join("\n"));
  const object = balancedObject(body, body.indexOf("{"));
  if (object === null) fail(`'${marker}' 뒤 JSON 객체가 펜스 안에서 닫히지 않았다`);
  return parse(object, marker);
}

/**
 * 마커가 붙은 **절(section)의 ```json 블록 전체**를 파싱한다.
 *
 * 범위 상한은 **다음 마크다운 제목**이다. 그 절의 예시를 지웠을 때 다음 절의 예시를
 * 대신 읽으면 `firstJsonObjectAfter` 와 똑같은 사고가 난다 — 여기도 같은 규칙으로 묶는다.
 *
 * `opts.after` 는 한 펜스에 요청·응답이 함께 있을 때 뒤쪽만 자르기 위한 것이다.
 */
export function jsonBlockAfter(
  spec: string,
  marker: string,
  opts: { after?: string } = {},
): Record<string, unknown> {
  const at = markerAt(spec, marker);

  const rest = spec.slice(at + marker.length);
  const nextHeading = rest.search(/\n#{1,6} /);
  const bound = at + marker.length + (nextHeading < 0 ? rest.length : nextHeading);

  const fenceStart = spec.indexOf(FENCE, at);
  if (fenceStart < 0 || fenceStart >= bound) {
    fail(`'${marker}' 절 안에 \`\`\`json 예시가 없다 — 예시가 지워졌는지 확인할 것`);
  }
  const fenceEnd = spec.indexOf("```", fenceStart + FENCE.length);
  if (fenceEnd < 0 || fenceEnd > bound) {
    fail(`'${marker}' 절의 \`\`\`json 펜스가 절 안에서 닫히지 않았다`);
  }

  let body = spec.slice(fenceStart + FENCE.length, fenceEnd);

  if (opts.after) {
    const cut = body.indexOf(opts.after);
    if (cut < 0) fail(`'${marker}' 예시에서 '${opts.after}' 를 찾지 못했다`);
    body = body.slice(cut + opts.after.length);
  }

  const cleaned = stripBlockComments(body)
    .split("\n")
    .filter((line) => !line.trim().startsWith("//"))
    .join("\n")
    .trim();

  if (cleaned === "") fail(`'${marker}' 예시가 비어 있다 — 예시가 지워졌다`);
  return parse(cleaned, marker);
}
