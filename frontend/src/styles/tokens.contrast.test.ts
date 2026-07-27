/**
 * 디자인 토큰 **대비 회귀** 테스트.
 *
 * 왜 이 파일이 존재하나 —
 *   `--text-estimated` 는 2026-07-25 감사(docs/02-design/ux/audit-frontend.md F-01)에서
 *   "라이트 2.58:1, AA 미달"로 지적돼 고치기로 한 항목이다. 그런데 그 수정은
 *   **와이어프레임 CSS(docs/.../wireframes/wireframe.css)에만 반영되고 실제 앱 토큰에는
 *   들어오지 않았고**, 이후 팔레트를 애플 시스템 그레이로 다시 칠하면서(#8E8E93)
 *   같은 결함이 3.26:1 로 되살아났다. 즉 "문서에 고쳤다고 적힌 것"이 코드를 지켜주지 못했다.
 *
 *   색은 눈으로 보면 "좀 흐리네" 정도라 리뷰에서 통과해 버린다. 그래서 사람 눈이 아니라
 *   **계산**으로 막는다. 팔레트를 다시 칠하면 화면을 열기 전에 이 테스트가 먼저 깨진다.
 *
 * 무엇을 검사하나 — tokens.css 를 문자열로 읽어 실제 토큰 값을 파싱하고,
 *   화면에 실제로 존재하는 **표면(배경) 조합**에 대해 WCAG 2.1 대비를 계산한다.
 *   반투명 토큰(rgba)은 얹히는 배경에 합성한 뒤 계산한다 — 합성을 빼먹으면 수치가 거짓말을 한다.
 *
 * 기준: WCAG 2.1 — 본문 텍스트 4.5:1(1.4.3) · 비텍스트 UI 3:1(1.4.11).
 */
import { describe, expect, it } from "vitest";
import tokensCss from "./tokens.css?raw";

// ── 색 파싱 · 합성 · 대비 ────────────────────────────────────────────────
type Rgba = readonly [number, number, number, number];

function parseColor(raw: string): Rgba {
  const c = raw.trim();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(c);
  if (hex) {
    const h = hex[1].length === 3 ? hex[1].replace(/./g, (d) => d + d) : hex[1];
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16), 1];
  }
  const rgb = /^rgba?\(([^)]+)\)$/i.exec(c);
  if (rgb) {
    const p = rgb[1].split(",").map((s) => Number(s.trim()));
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  }
  throw new Error(`색을 해석할 수 없다: ${raw}`);
}

/** 반투명 src 를 불투명 dst 위에 얹은 결과(알파 합성). 대비 계산 전에 반드시 거쳐야 한다. */
function over(src: Rgba, dst: Rgba): Rgba {
  const a = src[3];
  return [
    src[0] * a + dst[0] * (1 - a),
    src[1] * a + dst[1] * (1 - a),
    src[2] * a + dst[2] * (1 - a),
    1,
  ];
}

function luminance(c: Rgba): number {
  const f = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
}

/** 전경이 반투명이면 배경에 합성한 뒤 계산한다. 배경은 반드시 불투명이어야 한다. */
function contrast(fg: Rgba, bg: Rgba): number {
  if (bg[3] < 1) throw new Error("배경은 불투명이어야 한다 — 먼저 합성할 것");
  const f = fg[3] < 1 ? over(fg, bg) : fg;
  const [hi, lo] = [luminance(f), luminance(bg)].sort((a, b) => b - a);
  return (hi + 0.05) / (lo + 0.05);
}

const round2 = (n: number) => Math.round(n * 100) / 100;

// ── tokens.css 파싱 ──────────────────────────────────────────────────────
/** 주석을 먼저 지운다 — 주석 안의 설명 문구가 토큰처럼 잡히면 안 된다. */
const withoutComments = tokensCss.replace(/\/\*[\s\S]*?\*\//g, "");
const rootBlocks = [...withoutComments.matchAll(/:root\s*\{([^}]*)\}/g)].map((m) => m[1]);

function readTokens(block: string): Map<string, string> {
  const map = new Map<string, string>();
  for (const m of block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) map.set(m[1], m[2].trim());
  return map;
}

/** `var(--x)` 로 다른 토큰을 가리키는 값(예: --tag-unknown-fg)을 실제 색까지 따라간다. */
function color(tokens: Map<string, string>, name: string, depth = 0): Rgba {
  const raw = tokens.get(name);
  if (raw === undefined) throw new Error(`토큰이 없다: ${name}`);
  const ref = /^var\((--[\w-]+)\)$/.exec(raw);
  if (ref) {
    if (depth > 4) throw new Error(`var() 참조가 너무 깊다: ${name}`);
    return color(tokens, ref[1], depth + 1);
  }
  return parseColor(raw);
}

describe("디자인 토큰 — 대비(WCAG 2.1 AA)", () => {
  it("tokens.css 에서 라이트/다크 :root 두 벌을 읽는다", () => {
    expect(rootBlocks.length).toBe(2);
  });

  const light = readTokens(rootBlocks[0]);
  // 다크는 바뀌는 토큰만 재정의하므로 라이트 위에 덮어써야 실제 렌더 값이 된다.
  const dark = new Map([...readTokens(rootBlocks[0]), ...readTokens(rootBlocks[1])]);

  /**
   * 표면(배경) 목록 — **화면에 실제로 존재하는 조합만** 넣는다.
   * 상상 속 조합까지 넣으면 통과 못 할 색을 강요하게 되고, 반대로 빼먹으면 결함을 놓친다.
   * 근거: App.css(시트/그룹 배경) · BottomSheet.css · ConditionsScreen/AdminScreen/AuthForm(grouped)
   *       · ComplexCard/MapLegend/RegionPicker(badge-bg · accent-weak 채움)
   */
  function surfaces(t: Map<string, string>) {
    const bg = color(t, "--bg");
    const elev = color(t, "--bg-elev");
    const grouped = color(t, "--bg-grouped");
    return {
      bg,
      elev,
      grouped,
      "badge-bg 위(기본 배경)": over(color(t, "--badge-bg"), bg),
      "badge-bg 위(카드)": over(color(t, "--badge-bg"), elev),
      "accent-weak 채움(기본 배경)": over(color(t, "--accent-weak"), bg),
      "accent-weak 채움(그룹 배경)": over(color(t, "--accent-weak"), grouped),
      "accent-weak 채움(카드)": over(color(t, "--accent-weak"), elev),
    };
  }

  /**
   * 텍스트 토큰 → 그 색이 실제로 얹히는 표면들.
   * ⚠️ 여기서 표면을 지우면 테스트는 통과하지만 화면은 안 고쳐진다. 지울 땐 근거를 남길 것.
   */
  const TEXT_PAIRS: Array<{ fg: string; on: string[]; why: string }> = [
    {
      fg: "--text-secondary",
      on: ["bg", "grouped", "badge-bg 위(기본 배경)"],
      why: "캡션(연식·세대수·기준일)",
    },
    {
      fg: "--text-estimated",
      // ⚠️ 회귀 지점. `.estimated` `.badge--estimated` `.card__asof` `.tag--unknown` 등 28곳.
      on: ["bg", "grouped", "badge-bg 위(기본 배경)"],
      why: "추정치 — '모른다'는 정보 자체라 장식이 아니다(F-01)",
    },
    {
      fg: "--accent-text",
      on: [
        "bg",
        "grouped",
        "badge-bg 위(기본 배경)",
        "accent-weak 채움(기본 배경)",
        "accent-weak 채움(그룹 배경)",
        "accent-weak 채움(카드)",
      ],
      why: "강조색 **글자** — 선택된 칩·링크·보조 버튼",
    },
    { fg: "--warn-text", on: ["bg", "badge-bg 위(기본 배경)"], why: "경고 문구" },
    { fg: "--danger-text", on: ["bg", "badge-bg 위(기본 배경)"], why: "오류 문구" },
  ];

  for (const [mode, tokens] of [
    ["라이트", light],
    ["다크", dark],
  ] as const) {
    describe(`${mode} 모드`, () => {
      const surf = surfaces(tokens);

      for (const pair of TEXT_PAIRS) {
        for (const surfaceName of pair.on) {
          it(`${pair.fg} on ${surfaceName} ≥ 4.5:1 (${pair.why})`, () => {
            const bg = surf[surfaceName as keyof typeof surf];
            expect(round2(contrast(color(tokens, pair.fg), bg))).toBeGreaterThanOrEqual(4.5);
          });
        }
      }

      it("--on-accent 흰 글자 on --accent 채움 ≥ 4.5:1 (기본 CTA 5종)", () => {
        // 라이트·다크를 한 값으로 맞추는 건 수학적으로 불가능하다 —
        // 그래서 --accent(채움)와 --accent-text(글자)를 분리했다. 여기서 그 분리를 고정한다.
        const r = contrast(color(tokens, "--on-accent"), color(tokens, "--accent"));
        expect(round2(r)).toBeGreaterThanOrEqual(4.5);
      });

      it("--accent 테두리·포커스링 ≥ 3:1 (비텍스트 1.4.11)", () => {
        expect(round2(contrast(color(tokens, "--accent"), surf.bg))).toBeGreaterThanOrEqual(3);
        expect(round2(contrast(color(tokens, "--accent"), surf.elev))).toBeGreaterThanOrEqual(3);
      });

      it("특성 태그 3색이 옅은 채움 위에서 ≥ 4.5:1", () => {
        for (const tag of ["large", "station", "redev"]) {
          const fill = over(color(tokens, `--tag-${tag}-bg`), surf.bg);
          const r = contrast(color(tokens, `--tag-${tag}-fg`), fill);
          expect(round2(r), `--tag-${tag}-fg`).toBeGreaterThanOrEqual(4.5);
        }
      });

      it("예산 토글 OFF 손잡이 링이 트랙 채움과 ≥ 3:1 (비텍스트 1.4.11)", () => {
        // ListFilterBar.css `.lfb__thumb` 의 border 색 = --text-estimated.
        // 흰 손잡이가 흰 트랙 위에 있어 채움끼리는 1.15:1 밖에 안 된다 — 경계선이 유일한 단서다.
        const track = over(color(tokens, "--badge-bg"), color(tokens, "--bg-elev"));
        expect(round2(contrast(color(tokens, "--text-estimated"), track))).toBeGreaterThanOrEqual(3);
      });

      it('"확신의 농도" — 추정치는 캡션보다 **약하게** 유지된다', () => {
        // 대비를 올린다고 추정치가 확정값만큼 강해지면 이 앱의 컨셉이 깨진다.
        // 확정(--text) > 캡션(--text-secondary) > 추정(--text-estimated) 순서를 고정한다.
        const strength = (name: string) => contrast(color(tokens, name), surf.bg);
        expect(strength("--text")).toBeGreaterThan(strength("--text-secondary"));
        expect(strength("--text-secondary")).toBeGreaterThan(strength("--text-estimated"));
      });
    });
  }
});

describe("디자인 토큰 — 폰트 스택", () => {
  it("호스팅하지 않는 웹폰트를 스택에 넣지 않는다", () => {
    // @font-face 도 <link> 도 없으므로, 사용자 PC 설치 여부에 따라 렌더가 갈린다(비결정적).
    // CSP 가 font-src 'self' 라 외부 CDN 도 못 쓴다 — 시스템 폰트만 쓰는 게 이 앱의 결정이다.
    const ff = readTokens(rootBlocks[0]).get("--ff") ?? "";
    expect(ff).not.toMatch(/Pretendard|Noto Sans KR/i);
  });

  it("금액에 등폭 패밀리를 쓰지 않는다 (자릿수 정렬은 tabular-nums 로)", () => {
    // "14.8억" 은 숫자 + 한글이라 등폭을 걸면 Windows/Android 에서 폰트가 갈린다.
    expect(withoutComments).not.toMatch(/--ff-num/);
    const numRule = /\.num\s*\{([^}]*)\}/.exec(withoutComments);
    expect(numRule, ".num 규칙이 있어야 한다").not.toBeNull();
    expect(numRule![1]).not.toMatch(/font-family/);
    expect(numRule![1]).toMatch(/font-variant-numeric:\s*tabular-nums/);
  });
});
