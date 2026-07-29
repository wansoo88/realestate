/**
 * **목(mock)이 계약과 맞는가.**
 *
 * 2026-07-29 사고: 서버가 반영 여부 필드를 `eligible_for_recommendation` 으로 바꿨는데
 * (옛 이름은 "반영됐다"고 단정하던 이름이다) 프론트 테스트는 **전부 통과**했다. 이유는 단순하다 —
 * 테스트가 보는 것은 서버가 아니라 우리가 손으로 적은 목이고, 목이 낡으면
 * 화면이 `undefined === true` → 전부 false 로 조용히 거짓을 말해도 아무도 모른다.
 * TS 도 못 잡는다(런타임 JSON 이라 컴파일 시점에 존재하지 않는다).
 *
 * 그래서 목을 **문서(`docs/02-design/api-spec.md` §2.5)의 예시와 대조**한다.
 * 계약이 바뀌면 화면 테스트가 아니라 이 테스트가 **먼저** 깨지고, 그때 문서 → 목 →
 * 화면 순으로 고치면 된다.
 *
 * ⚠️ 이 파일은 목을 문서에 맞추라고 있는 것이지, 문서를 목에 맞추라고 있는 게 아니다.
 */
import { describe, expect, it } from "vitest";
import { userListing, userListingItem, userListingList } from "./fixtures";
// 계약 원문. **문서가 정본이다**(`?raw` 라 파싱 없이 그대로 읽는다).
// Node API(fs) 를 쓰지 않는 이유: 이 프로젝트는 `@types/node` 를 두지 않는다(브라우저 코드).
import spec from "../../../docs/02-design/api-spec.md?raw";
// 예시를 꺼내는 파서는 **따로 산다**(`specParser.ts`). 파서가 범위를 지키는지는
// `specParser.test.ts` 가 문서를 변이시켜 확인한다 — 검사를 검사하기 위해서다(CR37-2).
import {
  firstJsonObjectAfter as objectAfter,
  jsonBlockAfter as blockAfter,
} from "./specParser";

/** src 전체를 문자열로 — 옛 필드명이 한 군데라도 남았는지 훑는다. */
const SOURCES = import.meta.glob("../**/*.{ts,tsx,css}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/**
 * 폐기된 옛 필드명. **조각으로 조립한다** — 이 파일 자체에 literal 이 있으면
 * 아래 전수 검사가 자기 자신을 잡아 예외 목록이 필요해지고, 예외가 있는 검사는
 * 다음 사람이 예외를 하나 더 늘리면서 무력화된다.
 */
const RETIRED_FIELD = ["used", "in", "recommendation"].join("_");

/** 이 파일이 보는 문서는 항상 원본 한 벌이다 — 파서에 매번 넘기지 않게 감싼다. */
const jsonBlockAfter = (marker: string, opts: { after?: string } = {}) =>
  blockAfter(spec, marker, opts);
const firstJsonObjectAfter = (marker: string) => objectAfter(spec, marker);

const keys = (o: unknown) => Object.keys(o as object).sort();

describe("목 ↔ 계약 대조 — /me/listings (api-spec §2.5)", () => {
  const spec201 = jsonBlockAfter("#### `POST /me/listings`", { after: "// res 201" });
  const specList = jsonBlockAfter("#### `GET /me/listings?complex_id=`");

  it("단건 응답의 최상위 키가 같다 (item · problems · **notes**)", () => {
    // notes 를 빠뜨린 채 목을 만들면, 저장 직후 "반영됐다"는 오해를 막는 고지가
    // 화면에 없어도 테스트가 통과한다 — 그게 이번에 잡힌 구멍이다.
    expect(keys(userListingItem())).toEqual(keys(spec201));
  });

  it("호가 1건의 키가 같다 (이름이 하나라도 다르면 화면이 조용히 거짓을 말한다)", () => {
    expect(keys(userListing())).toEqual(keys(spec201.item));
  });

  it("`eligible_for_recommendation` 은 boolean 이다 — 옛 이름은 계약에 없다", () => {
    const item = spec201.item as Record<string, unknown>;
    expect(typeof item.eligible_for_recommendation).toBe("boolean");
    expect(RETIRED_FIELD in item).toBe(false);
  });

  it("목록 응답의 키와 summary 항목이 같다", () => {
    expect(keys(userListingList())).toEqual(keys(specList));
    expect(keys(userListingList().summary)).toEqual(keys(specList.summary));
  });

  it("목록 summary 도 '반영됨'이 아니라 '자격'을 센다", () => {
    const summary = specList.summary as Record<string, unknown>;
    expect("eligible_for_recommendation" in summary).toBe(true);
    expect(RETIRED_FIELD in summary).toBe(false);
  });
});

/* ─────────────────────────────────────────────────────────────────────────
 * 지도 계약 (api-spec §4) — 2026-07-29 변경 3건.
 *
 * 이 세 가지는 **목만 보면 절대 안 깨진다.** 우리가 손으로 적은 목에는 지금도
 * `over_budget: false` 가 들어 있고(3값이 되기 전 모양), `budget` 블록은 아예 없다.
 * 그래서 문서를 파싱해 대조한다 — 서버가 계약을 바꾸면 여기가 **먼저** 깨진다.
 * ───────────────────────────────────────────────────────────────────────── */

describe("목 ↔ 계약 대조 — /map/complexes (api-spec §4)", () => {
  const cluster = firstJsonObjectAfter("// res 200 — zoom < 13 : 군집(클러스터)");
  const complex = firstJsonObjectAfter("// res 200 — zoom >= 13 : 단지 단위");

  it("각 마커가 **제 예시**를 읽었다 (판별자 `level`)", () => {
    // 파서가 옆 예시를 읽으면 나머지 단언이 전부 엉뚱한 객체 위에 선다.
    // 범위 자체는 `specParser.test.ts` 가 문서를 변이시켜 확인한다 — 여기는 결과 확인.
    expect(cluster.level).toBe("cluster");
    expect(complex.level).toBe("complex");
  });

  it("① `over_budget` 은 **3값**이다 — 계약 예시가 `null` 이다", () => {
    const item = (complex.items as Record<string, unknown>[])[0];
    expect("over_budget" in item).toBe(true);
    // 예시가 null 이라는 사실 자체가 계약이다: boolean 두 값으로는 표현할 수 없는
    // 세 번째 상태("판정 못 함")가 존재한다는 뜻.
    expect(item.over_budget).toBeNull();
    expect(typeof item.over_budget).not.toBe("boolean");
  });

  it("① 타입이 `null` 을 허용한다 — 안 그러면 화면이 모름을 못 받는다", () => {
    expect(SOURCES["../api/client.ts"]).toContain("over_budget: boolean | null");
  });

  it("① **falsy 검사로 접지 않는다** — 읽는 곳은 전부 `=== true` 로 비교한다", () => {
    // null 을 falsy 로 흘려보내면 "모른다"가 "예산 내"와 같은 취급이 된다.
    // 지금은 배지가 초과에만 붙어 증상이 없지만, '예산 내' 표시를 붙이는 날 곧바로
    // 거짓이 된다. 구조로 막아 둔다(대조 자체는 lib/budgetStatus.test 가 본다).
    for (const file of ["../lib/mapMarkers.ts", "../components/ComplexCard.tsx"]) {
      expect(SOURCES[file], `${file} 가 over_budget 을 falsy 로 읽는다`).toContain(
        "over_budget === true",
      );
    }
  });

  it("② `budget` 블록의 키가 같다 (applied · basis · reason)", () => {
    expect(keys(complex.budget)).toEqual(["applied", "basis", "reason"]);
    expect(SOURCES["../api/client.ts"]).toContain("export interface MapBudget");
  });

  it("② **군집 응답에도** `budget` 이 온다 — 줌아웃해도 조건은 사라지지 않는다", () => {
    expect(keys(cluster.budget)).toEqual(["applied", "basis", "reason"]);
  });

  it("② `applied:false` 예시에는 **사유가 실려 있다**(빈 실패 금지)", () => {
    const budget = complex.budget as Record<string, unknown>;
    expect(budget.applied).toBe(false);
    expect(budget.basis).toBeNull();
    expect(typeof budget.reason).toBe("string");
    expect((budget.reason as string).length).toBeGreaterThan(0);
  });

  it("② `basis` 어휘가 프론트와 같다 (target_price · max_purchase)", () => {
    // 같은 말을 써야 서버 기준과 화면 기준을 대조할 수 있다(lib/budgetStatus).
    expect(spec).toContain('"target_price"');
    expect(spec).toContain('"max_purchase"');
    expect(SOURCES["../api/client.ts"]).toContain(
      'export type BudgetBasis = "target_price" | "max_purchase"',
    );
  });

  it("③ 요청에 `purpose` 를 싣는다 — 문서·클라이언트·쿼리 조립 세 곳 모두", () => {
    // 문서: 파라미터 표에 live/invest 행이 있다(칸 구분자가 `\|` 로 이스케이프돼 있어
    // 칸 단위가 아니라 **줄 단위**로 본다)
    expect(spec).toMatch(/^\|\s*`purpose`\s*\|[^\n]*live[^\n]*invest/m);
    // 클라이언트: 지도 요청 파라미터에 있다
    expect(SOURCES["../api/client.ts"]).toContain("purpose?: Purpose;");
    // 조립부: 실제로 넣는다(타입만 있고 안 넣으면 서버 기본값이 조용히 쓰인다)
    expect(SOURCES["../lib/mapFilters.ts"]).toContain("purpose: f.purpose");
  });

  it("③ 목적은 **한 곳에서만** 정의한다 — 화면마다 리터럴을 적지 않는다", () => {
    // 지도·자금계획·추천이 다른 값을 쓰면 한도 자체가 달라진다(백엔드 지적).
    expect(SOURCES["../lib/purpose.ts"]).toContain("export const DEFAULT_PURPOSE");
    expect(SOURCES["../App.tsx"]).toContain("const PURPOSE = DEFAULT_PURPOSE");
  });

  it("폐기된 `max_price_krw` 는 400 이다 — 받아서 무시하지 않는다", () => {
    expect(spec).toContain("PARAM_REMOVED");
    // 화면이 되살리면 조립부가 던진다(urlPrivacy.test 가 실물로 확인).
    expect(SOURCES["../api/client.ts"]).toContain("SENSITIVE_QUERY_KEY");
  });
});

/* ─────────────────────────────────────────────────────────────────────────
 * `over_budget` 을 **화면이 싣는 자리** — 전수 검사 (CR37-2 · CR38-1 / 관문 우회 차단)
 *
 * 배경: 마커도 카드도 배지를 **"초과"에만** 단다. 그래서 `null`(모름)과 `false`(예산 안)는
 * 화면상 **완전히 동일**하고, 화면 테스트로는 접힘을 절대 못 잡는다. 순수 함수 관문만
 * 두면 **호출부에서 인라인으로 우회하면 그만**이었다(리뷰 실측: tsc exit 0 · 918 passed).
 *
 * CR38-1 이후 관문이 지키는 명제가 하나 늘었다:
 *   ㉠ **`null`(모름)은 `false`(예산 안)가 되지 않는다** — 원래 명제.
 *   ㉡ **화면은 예산 판정을 만들지 않는다** — 서버 값을 옮기거나 비울 뿐이다.
 *      화면이 아는 한도는 **하나**인데 실제 상한은 면적별로 다르다(취득세 85㎡ 구간).
 *
 * 방어는 셋으로 쌓는다. 이 파일은 그중 ③이다.
 *   ① **타입** — 지도에 넘기는 항목은 `ScreenComplexItem`(브랜드)이라 손으로 못 만든다.
 *   ② **호출부 축소** — 싣는 자리는 `lib/screenBudget.applyScreenBudget` 하나뿐.
 *   ③ **전수 검사(여기)** — src 전체에서 `over_budget:` 을 **쓰는** 자리를 세어,
 *      한 곳뿐이고 그 값이 `relayServerVerdict(` 로만 만들어지는지 본다.
 * ───────────────────────────────────────────────────────────────────────── */

/** 주석 줄은 코드가 아니다 — 설명문의 `over_budget: null` 까지 잡으면 검사가 소음이 된다. */
function codeLines(text: string): Array<{ no: number; line: string }> {
  return text
    .split("\n")
    .map((line, i) => ({ no: i + 1, line }))
    .filter(({ line }) => {
      const t = line.trim();
      return !(t.startsWith("//") || t.startsWith("*") || t.startsWith("/*"));
    });
}

describe("`over_budget` 을 만드는 자리는 하나뿐이다 (관문 우회 차단)", () => {
  /**
   * 목·픽스처(테스트)는 **서버 응답을 흉내내는** 자리라 제외한다 — 거기서 `false` 를
   * 쓰는 건 "서버가 false 라고 했다"는 뜻이고, 화면이 모름을 접는 것과 다른 일이다.
   */
  const PRODUCTION = Object.entries(SOURCES).filter(
    ([f]) => !/\.test\.tsx?$/.test(f) && !f.startsWith("../test/"),
  );

  /** `over_budget:` 을 **값으로 쓰는** 줄. 타입 선언(`: boolean | null`)은 만드는 게 아니다. */
  const writes = PRODUCTION.flatMap(([file, text]) =>
    codeLines(text)
      .map(({ no, line }) => ({ no, m: /over_budget:\s*(.*)$/.exec(line) }))
      .filter((r): r is { no: number; m: RegExpExecArray } => r.m !== null)
      .map(({ no, m }) => ({ file, no, rhs: m[1].trim() }))
      .filter((w) => !/^(boolean|string|number|null)\b/.test(w.rhs)),
  );

  it("훑을 파일을 실제로 찾았다 (빈 검사는 늘 통과한다)", () => {
    expect(PRODUCTION.length).toBeGreaterThan(40);
    expect(PRODUCTION.some(([f]) => f.endsWith("lib/screenBudget.ts"))).toBe(true);
  });

  it("싣는 파일은 `lib/screenBudget.ts` **하나뿐**이다", () => {
    // 호출부가 늘어나면(App 에서 다시 인라인으로 만들면) 여기서 잡힌다.
    expect([...new Set(writes.map((w) => w.file))]).toEqual(["../lib/screenBudget.ts"]);
    expect(writes.length).toBe(1);
  });

  it("그 값은 **`relayServerVerdict(` 로만** 만든다 — 접거나 지어내지 않는다", () => {
    for (const w of writes) {
      expect(
        w.rhs.startsWith("relayServerVerdict("),
        `${w.file}:${w.no} 가 관문을 우회한다 — over_budget: ${w.rhs}`,
      ).toBe(true);
    }
  });

  /**
   * ㉡ **화면은 예산 판정을 만들지 않는다** (CR38-1).
   *
   * 이 검사가 잡는 변이는 하나뿐이지만 그게 이번 결함 그 자체다 — 지도 항목의
   * `over_budget` 을 `budgetVerdict(가격, 한도 하나)` 로 되돌리는 것. 화면이 아는
   * 한도는 하나인데 실제 상한은 면적별로 다르므로, 되돌리면 120㎡ 단지의 배지가
   * 84㎡ 한도로 선다. 화면 끝 회귀는 `App.test.tsx` 의 3상태가 본다.
   */
  it("㉡ 지도 항목의 판정을 **금액으로 만들지 않는다** — 판정은 서버 것이다", () => {
    const gate = SOURCES["../lib/screenBudget.ts"];
    for (const banned of ["budgetVerdict(", "recent_price_krw", "budgetKrw"]) {
      expect(
        codeLines(gate).some(({ line }) => line.includes(banned)),
        `lib/screenBudget.ts 가 ${banned} 로 판정을 다시 만든다 — 상한은 면적별로 다르다`,
      ).toBe(false);
    }
    // 그리고 실제로 서버 값을 읽는다(빈 검사 금지 — 아무것도 안 하면 위 단언은 늘 통과한다)
    expect(gate).toContain("item.over_budget ?? null");
  });

  it("타입 관문도 살아 있다 — 지도에 넘기는 항목은 브랜드 타입이다", () => {
    // 전수 검사만 있으면 "검사를 지우면 끝"이다. 타입은 tsc 가 따로 막는다.
    expect(SOURCES["../lib/screenBudget.ts"]).toContain("unique symbol");
    expect(SOURCES["../lib/screenBudget.ts"]).toContain("export type ScreenComplexItem");
    expect(SOURCES["../components/MapView.tsx"]).toContain("items?: ScreenComplexItem[]");
    expect(SOURCES["../App.tsx"]).toContain("applyScreenBudget(");
  });
});

describe("옛 필드명이 코드에 남아 있지 않다", () => {
  it("src 전체에 폐기된 필드명이 없다 (주석·목 포함)", () => {
    // 한 곳만 남아도 그 화면은 항상 false(= '반영 안 됨')를 말한다.
    // 주석도 예외로 두지 않는다 — 다음 사람이 주석을 보고 그 이름을 다시 쓴다.
    const offenders = Object.entries(SOURCES)
      .filter(([, text]) => text.includes(RETIRED_FIELD))
      .map(([file]) => file);
    expect(offenders).toEqual([]);
  });

  it("훑을 파일을 실제로 찾았다 (glob 이 비면 위 검사는 늘 통과한다)", () => {
    // 빈 검사는 통과하는 검사보다 나쁘다 — 지키는 척만 한다.
    expect(Object.keys(SOURCES).length).toBeGreaterThan(50);
    expect(Object.keys(SOURCES).some((f) => f.endsWith("api/client.ts"))).toBe(true);
  });
});
