// @vitest-environment jsdom
/**
 * 내 조건 — **가중치 설명과 정직성** 테스트.
 *
 * 사용자가 "가격·입지·가치·리스크가 무슨 뜻인지 모르겠다"고 했다. 설명을 붙이는 건 쉬운데,
 * 그 설명이 **실제 작동 범위를 넘겨 말하면** 더 그럴듯한 거짓이 된다.
 * 계약: `docs/02-design/api-spec.md` §5.3 · `backend/app/agents/scoring.py::AXIS_SPECS`.
 *   - 서버는 이제 사용자 가중치를 총점에 **실제로** 반영한다(WEIGHT-1).
 *   - 다만 근거 없는 축은 재정규화로 빠지고, `value`·`risk` 는 coverage=partial 이다.
 *   - 리스크 점수는 **매물 신뢰도까지만**이다 — risk-auditor 는 아직 없다.
 * 아래 테스트는 화면이 이 경계를 **정확히** 말하는지 본다.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Preferences, Profile } from "../api/client";
import { forgetAxisGaps, rememberAxisGaps } from "../lib/scoreAxes";
import { ConditionsScreen } from "./ConditionsScreen";

const PROFILE: Profile = {
  cash_krw: 300_000_000,
  income_krw: 90_000_000,
  existing_loan_krw: 0,
  owned_houses: 0,
  household_size: 3,
};

const PREFS: Preferences = {
  prefer: {},
  avoid: {},
  weights: { price: 0.3, location: 0.3, value: 0.25, risk: 0.15 },
};

/** 최대 실구매 가능 금액 — 희망가 슬라이더 범위의 기준. */
const MAX_PURCHASE = 850_000_000;

function renderScreen(
  onSave = vi.fn().mockResolvedValue(undefined),
  opts: { preferences?: Preferences; maxPurchaseKrw?: number | null } = {},
) {
  render(
    <ConditionsScreen
      profile={PROFILE}
      preferences={opts.preferences ?? PREFS}
      onSave={onSave}
      onClose={vi.fn()}
      maxPurchaseKrw={opts.maxPurchaseKrw === undefined ? MAX_PURCHASE : opts.maxPurchaseKrw}
    />,
  );
  return onSave;
}

afterEach(() => {
  cleanup();
  forgetAxisGaps(); // 관측 기억이 테스트 사이에 새지 않게
});

describe("가중치 설명", () => {
  it("각 항목에 한 줄 설명이 **항상 보인다**(열어야만 뜻을 알 수 있으면 설명이 아니다)", () => {
    renderScreen();

    expect(screen.getByText(/최근 실거래 적정가보다 싼지 비싼지/)).toBeTruthy();
    expect(screen.getByText(/12개월 거래회전율/)).toBeTruthy();
  });

  it("'가격'과 '가치'가 서로 다른 질문임이 라벨에서 갈린다 — 사용자가 헷갈린 지점", () => {
    renderScreen();

    // 가격 = 지금 이 호가가 적정가 대비 싼가 / 가치 = 잘 팔리는가(환금성)
    expect(screen.getByRole("slider", { name: /가격/ }).id).toBe("cond-w-price");
    expect(screen.getByRole("slider", { name: /가치/ }).id).toBe("cond-w-value");
    expect(screen.getByText("지금 싸게 사는가")).toBeTruthy();
    expect(screen.getByText("잘 팔리는가(환금성)")).toBeTruthy();
  });

  it("자세한 설명은 눌러서 연다(hover 툴팁은 폰에서 뜨지 않는다)", async () => {
    const user = userEvent.setup();
    renderScreen();

    const tip = screen.getByRole("button", { name: "가격 설명 보기" });
    expect(tip.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(/밴드보다 싸게 나왔으면/)).toBeNull();

    await user.click(tip);

    expect(tip.getAttribute("aria-expanded")).toBe("true");
    const note = screen.getByRole("note");
    expect(note.textContent).toContain("적정가 밴드");
    // 예산이 이 축에 없다는 사실 — "예산 = 가격 축"이라는 오해를 막는다
    expect(note.textContent).toContain("예산 자체는 이 축에 없습니다");
    // 어느 전문가 판단에 실리는지도 함께 — 근거 추적(ux §6)
    expect(note.textContent).toContain("담당");
    // aria-controls 가 실제로 그 설명을 가리켜야 보조기기가 따라간다
    expect(tip.getAttribute("aria-controls")).toBe(note.id);
  });

  it("설명 토글은 키보드로 조작된다", async () => {
    const user = userEvent.setup();
    renderScreen();
    const tip = screen.getByRole("button", { name: "리스크 설명 보기" });

    tip.focus();
    await user.keyboard("{Enter}");

    expect(screen.getByRole("note").textContent).toContain("매물 정보의 신뢰도");
  });
});

/**
 * WEIGHT-1(2026-07-26) 이후: 서버가 가중치를 **실제로** 반영한다.
 * 그래서 이제 지켜야 할 정직성은 "작동 안 함"이 아니라 **"어디까지 작동하는가"** 다.
 */
describe("가중치 정직성 — 작동 범위를 넘겨 말하지 않는다", () => {
  it("리스크는 '매물 신뢰도까지만'이라고 못박는다 — 호가가 들어와도 그대로다", () => {
    renderScreen();

    // 이 문장이 없으면 사용자는 "호가만 들어오면 리스크가 다 반영된다"고 읽는다
    const gap = screen.getByText(/권리관계·근저당·재건축 추가분담금·깡통전세/);
    expect(gap.textContent).toContain("호가가 들어와도");
    expect(gap.textContent).toContain("일부만 반영");
  });

  it("가치도 동별 편차는 점수에 안 들어간다고 밝힌다", () => {
    renderScreen();

    expect(screen.getByText(/동별 가격 편차는/)).toBeTruthy();
  });

  it("부분 반영 고지는 **반영 여부와 무관하게** 항상 보인다(계약 §5.3)", () => {
    renderScreen();

    // partial 축은 셋(가치·리스크·재건축) — 반영되고 있어도 한계는 말한다
    expect(screen.getAllByText("일부만 반영").length).toBe(3);
  });

  it("모든 항목을 조작할 수 있다 — 근거가 없다고 잠그면 이번엔 반대로 거짓말이 된다", () => {
    renderScreen();

    for (const name of [/가격/, /입지/, /가치/, /리스크/, /재건축/]) {
      const slider = screen.getByRole("slider", { name }) as HTMLInputElement;
      expect(slider.disabled).toBe(false);
    }
  });

  it("서버가 가중치를 쓰므로 '아직 미반영' 경고는 뜨지 않는다", () => {
    renderScreen();

    expect(screen.queryByText(/추천 순위 계산에는 아직 반영되지 않습니다/)).toBeNull();
  });

  it("직전 분석에서 근거가 없던 축은 그 사실을 슬라이더 옆에 적는다", () => {
    // 관측값(lib/scoreAxes)을 쓰므로, 데이터가 들어오면 이 문구는 저절로 사라진다.
    rememberAxisGaps([
      {
        complex: { id: 1, name: "단지" },
        unit_type: null,
        building: null,
        dong_valuation: null,
        price_basis: "trade",
        ask_price_krw: null,
        est_price_krw: 1_000_000_000,
        price_estimated: true,
        price_note: null,
        ask_gap_pct: null,
        price_band: null,
        total_score: 62.8,
        score_basis: "user_weighted",
        score_coverage_pct: 25,
        score_axes: [
          {
            axis: "location",
            label: "입지",
            agent_ids: ["location-analyst"],
            signal: "학군·역세권",
            coverage: "full",
            coverage_gap: null,
            weight: 0.3,
            applied_weight: null,
            score: null,
            status: "no_signal",
            missing: ["학구도 데이터 미확보"],
          },
          {
            axis: "value",
            label: "가치(시세)",
            agent_ids: ["valuation-trader"],
            signal: "12개월 거래회전율",
            coverage: "partial",
            coverage_gap: "동별 편차는 제외",
            weight: 0.25,
            applied_weight: 1,
            score: 62.8,
            status: "applied",
            missing: [],
          },
        ],
        score_notes: [],
        timing_signal: "",
        headline: "",
        why: [],
        why_not: [],
        next_actions: [],
        findings: [],
      },
    ]);

    renderScreen();

    const note = screen.getByText(/직전 분석에서는 입지 근거가 없어/);
    expect(note).toBeTruthy();
    // 근거가 있던 축(가치)에는 같은 문구가 붙지 않는다
    expect(screen.queryByText(/직전 분석에서는 가치 근거가 없어/)).toBeNull();

    // 사유는 슬라이더에 aria-describedby 로 연결된다(보조기기도 이유를 듣는다)
    const slider = screen.getByRole("slider", { name: /입지/ });
    const ids = (slider.getAttribute("aria-describedby") ?? "").split(" ");
    const texts = ids.map((id) => document.getElementById(id)?.textContent ?? "").join(" ");
    expect(texts).toContain("반영되지 않았습니다");
  });

  it("분석을 돌린 적이 없으면 근거 유무를 단정하지 않는다", () => {
    renderScreen();

    expect(screen.queryByText(/직전 분석에서는/)).toBeNull();
  });
});

describe("조정 가능한 항목은 그대로 동작한다", () => {
  it("가격 비중을 바꾸면 정규화된 값으로 저장된다", async () => {
    const user = userEvent.setup();
    const onSave = renderScreen();

    // range 입력은 fireEvent.change 로 움직인다 — jsdom 은 슬라이더의 키보드 기본동작을
    // 구현하지 않아 user.keyboard 로는 값이 바뀌지 않는다(테스트가 조용히 통과할 뻔했다).
    const price = screen.getByRole("slider", { name: /가격/ }) as HTMLInputElement;
    fireEvent.change(price, { target: { value: "50" } });
    expect(price.value).toBe("50");

    await user.click(screen.getByRole("button", { name: "저장하고 다시 계산" }));

    const [, prefs] = onSave.mock.calls[0] as [Profile, Preferences];
    const sum = Object.values(prefs.weights).reduce((a, b) => a + (b ?? 0), 0);
    expect(sum).toBeCloseTo(1, 3);
    expect(prefs.weights.price).toBeGreaterThan(0.3); // 올린 만큼 비중이 커졌다
  });

  /**
   * 손대지 않은 항목의 **상대 비율**은 그대로다.
   *
   * ⚠️ 절대값은 그대로가 아니다 — 그리고 그게 맞다. 저장값에 `redevelopment` 키가 없으면
   *    서버가 기본 15% 를 넣어 순위를 매기고 있고(scoring.py DEFAULT_AXIS_WEIGHTS),
   *    화면은 **지금 적용 중인 값**을 보여줘야 한다(effectiveWeights). 그래서 30:30:25:15 가
   *    25.5:25.5:21.25:12.75 로 눌리며 재건축 15% 가 들어온다. 비율은 한 치도 안 변한다.
   *    지켜야 할 것은 "화면이 서버 값을 몰래 0 으로 만들지 않는다"이고, 그건 그대로다.
   */
  it("손대지 않은 항목은 서로의 비율이 보존된다 — 몰래 0 으로 만들지 않는다", async () => {
    const user = userEvent.setup();
    const onSave = renderScreen();

    await user.click(screen.getByRole("button", { name: "저장하고 다시 계산" }));

    const [, prefs] = onSave.mock.calls[0] as [Profile, Preferences];
    const w = prefs.weights;
    expect(w.location).toBeGreaterThan(0); // 입지 데이터가 들어오면 살아나야 할 값이다
    expect(w.risk).toBeGreaterThan(0);
    // 저장값 30:30:25:15 의 비율이 그대로 유지된다
    expect(w.location! / w.price!).toBeCloseTo(1, 3);
    expect(w.value! / w.price!).toBeCloseTo(25 / 30, 3);
    expect(w.risk! / w.price!).toBeCloseTo(15 / 30, 3);
  });

  /**
   * FE-5 — **"안 보냄"과 "0"이 다르다.**
   * 저장된 조건에 재건축 키가 없으면 서버는 기본 15% 를 적용한다. 화면이 그 사실을
   * 0% 로 그리면, 사용자는 "안 보고 있다"고 읽는데 실제로는 15% 가 순위를 바꾸고 있다.
   */
  it("저장값에 재건축 키가 없어도 화면은 서버가 적용 중인 15% 를 보여준다", () => {
    renderScreen(vi.fn(), {
      preferences: { ...PREFS, weights: { price: 0.3, location: 0.3, value: 0.25, risk: 0.15 } },
    });

    const slider = screen.getByRole("slider", { name: /재건축/ }) as HTMLInputElement;
    expect(Number(slider.value)).toBe(15);
  });

  it("사용자가 명시한 0 은 존중한다 — 기본값으로 되살리지 않는다", () => {
    renderScreen(vi.fn(), {
      preferences: {
        ...PREFS,
        weights: { price: 0.4, location: 0.3, value: 0.2, risk: 0.1, redevelopment: 0 },
      },
    });

    const slider = screen.getByRole("slider", { name: /재건축/ }) as HTMLInputElement;
    expect(Number(slider.value)).toBe(0);
  });

  /**
   * ⚠️ 이 테스트가 FE-5 의 **실제 계약**이다. 슬라이더를 0 으로 내렸는데 키가 빠져서
   *    나가면, 서버는 그것을 "언급 안 함"으로 읽고 기본 15% 를 되살린다 —
   *    사용자가 끈 축이 조용히 켜지는 형태의 실패다.
   */
  it("재건축을 0 으로 내리면 **명시적 0** 이 저장된다(키가 빠지면 서버가 15% 로 되살린다)", async () => {
    const user = userEvent.setup();
    const onSave = renderScreen();

    const slider = screen.getByRole("slider", { name: /재건축/ });
    fireEvent.change(slider, { target: { value: "0" } });
    await user.click(screen.getByRole("button", { name: "저장하고 다시 계산" }));

    const [, prefs] = onSave.mock.calls[0] as [Profile, Preferences];
    expect("redevelopment" in prefs.weights).toBe(true); // 키가 있어야 한다
    expect(prefs.weights.redevelopment).toBe(0);
    // 나머지 축은 살아 있고 합은 여전히 1 이다
    expect(Object.values(prefs.weights).reduce((a, b) => a + (b ?? 0), 0)).toBeCloseTo(1, 3);
  });

  it("재건축 설명은 '단계가 높을수록 좋다'가 아님을 말한다(실거주와 투자가 반대로 움직인다)", async () => {
    const user = userEvent.setup();
    renderScreen();

    // 한 줄 요약은 열지 않아도 보인다
    expect(screen.getByText(/단계가 뒤일수록 높은 점수가 아닙니다/)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "재건축 설명 보기" }));
    const note = screen.getByRole("note");
    expect(note.textContent).toContain("사업시행인가");
    expect(note.textContent).toContain("실거주");
    expect(note.textContent).toContain("이주");
    // 무엇을 못 보는지도 함께 — 경기도 '정보 없음'을 '정비사업 없음'으로 읽으면 안 된다
    expect(screen.getByText(/'정비사업이 없다'는 뜻이 아닙니다/)).toBeTruthy();
  });
});

/**
 * 희망 매매가 — 사용자가 직접 요청한 입력.
 *
 * 핵심 성질: **한도를 넘겨서도 고를 수 있어야 한다.** 못 사는 가격을 막으면
 * "얼마를 더 모아야 하나"라는 질문 자체가 사라진다 — 이 기능이 답하려는 바로 그 질문이다.
 */
describe("희망 매매가", () => {
  it("슬라이더와 직접 입력이 **둘 다** 있다(억 단위는 엄지로 못 맞춘다)", () => {
    renderScreen();

    expect(screen.getByRole("slider", { name: "희망 매매가" })).toBeTruthy();
    expect(screen.getByLabelText("희망 매매가 직접 입력")).toBeTruthy();
  });

  it("슬라이더 상한이 최대 실구매 가능 금액보다 **높다** — 한도 넘는 집도 볼 수 있다", () => {
    renderScreen();

    const slider = screen.getByRole("slider", { name: "희망 매매가" }) as HTMLInputElement;
    expect(Number(slider.max)).toBeGreaterThan(MAX_PURCHASE);
    expect(Number(slider.min)).toBeLessThan(MAX_PURCHASE);
    // 한도가 어디인지 눈금에 적는다(넘었는지 아닌지를 슬라이더만 보고 알 수 있게)
    expect(screen.getByText(/내 한도 8\.50억/)).toBeTruthy();
  });

  it("스크린리더에는 자릿수가 아니라 사람 말로 읽힌다", () => {
    renderScreen(vi.fn(), {
      preferences: { ...PREFS, prefer: { target_price_krw: 900_000_000 } },
    });

    const slider = screen.getByRole("slider", { name: "희망 매매가" });
    expect(slider.getAttribute("aria-valuetext")).toBe("9억");
  });

  it("슬라이더를 움직이면 그 값이 **선호에 저장된다**", async () => {
    const user = userEvent.setup();
    const onSave = renderScreen();

    const slider = screen.getByRole("slider", { name: "희망 매매가" });
    fireEvent.change(slider, { target: { value: "900000000" } });

    await user.click(screen.getByRole("button", { name: "저장하고 다시 계산" }));

    const [, prefs] = onSave.mock.calls[0] as [Profile, Preferences];
    expect(prefs.prefer.target_price_krw).toBe(900_000_000);
  });

  it("직접 입력(만원)도 원 단위로 저장된다 — 1만분의 1이 되면 한도가 무너진다", async () => {
    const user = userEvent.setup();
    const onSave = renderScreen();

    await user.type(screen.getByLabelText("희망 매매가 직접 입력"), "123456");
    await user.click(screen.getByRole("button", { name: "저장하고 다시 계산" }));

    const [, prefs] = onSave.mock.calls[0] as [Profile, Preferences];
    expect(prefs.prefer.target_price_krw).toBe(1_234_560_000); // 12.3456억
  });

  it("한도를 넘기면 막지 않고 **얼마나 넘는지** 말한다", () => {
    renderScreen(vi.fn(), {
      preferences: { ...PREFS, prefer: { target_price_krw: 1_000_000_000 } },
    });

    const note = screen.getByText(/최대 실구매 가능 금액 8\.50억보다/);
    expect(note.textContent).toContain("1.50억 높습니다");
    expect(note.textContent).toContain("내 자금"); // 어디서 확인하는지까지
  });

  it("한도 안이면 여유를 말한다", () => {
    renderScreen(vi.fn(), {
      preferences: { ...PREFS, prefer: { target_price_krw: 700_000_000 } },
    });
    expect(screen.getByText(/안입니다 \(여유 1\.50억\)/)).toBeTruthy();
  });

  it("한도를 아직 모르면 아는 척하지 않는다", () => {
    renderScreen(vi.fn(), {
      preferences: { ...PREFS, prefer: { target_price_krw: 700_000_000 } },
      maxPurchaseKrw: null,
    });

    expect(screen.queryByText(/내 한도/)).toBeNull();
    expect(screen.getByText(/아직 계산되지 않아 한도와 비교할 수 없습니다/)).toBeTruthy();
    // 그래도 슬라이더는 살아 있다(값을 못 정하게 막지 않는다)
    expect((screen.getByRole("slider", { name: "희망 매매가" }) as HTMLInputElement).disabled).toBe(
      false,
    );
  });

  it("지우면 **키 자체가 빠진다** — 0 원을 원한다는 뜻이 되면 안 된다", async () => {
    const user = userEvent.setup();
    const onSave = renderScreen(vi.fn(), {
      preferences: { ...PREFS, prefer: { target_price_krw: 900_000_000 } },
    });

    await user.click(screen.getByRole("button", { name: "희망가 지우기" }));
    await user.click(screen.getByRole("button", { name: "저장하고 다시 계산" }));

    const [, prefs] = onSave.mock.calls[0] as [Profile, Preferences];
    expect("target_price_krw" in prefs.prefer).toBe(false);
  });

  it("정하지 않았으면 무엇이 예산이 되는지 알려준다", () => {
    renderScreen();
    expect(screen.getByText(/정하지 않으면 최대 실구매 가능 금액을 예산으로 씁니다/)).toBeTruthy();
  });

  it("이 값이 어디에 쓰이는지 화면이 먼저 말한다(저장만 되는 값이 아님)", () => {
    renderScreen();
    const note = screen.getByText(/지도 필터 · AI 추천 예산 · 자금계획/);
    expect(note).toBeTruthy();
  });
});

describe("기존 화면 동작 회귀", () => {
  it("자산·선호 입력과 저장 흐름은 그대로다", async () => {
    const user = userEvent.setup();
    const onSave = renderScreen();

    const subway = screen.getByLabelText("역세권");
    await user.selectOptions(subway, "500");
    await user.click(screen.getByRole("button", { name: "저장하고 다시 계산" }));

    const [profile, prefs] = onSave.mock.calls[0] as [Profile, Preferences];
    expect(profile.cash_krw).toBe(300_000_000);
    expect(prefs.prefer.subway_within_m).toBe(500);
  });

  it("기피 조건은 여전히 체크할 수 있다", async () => {
    const user = userEvent.setup();
    const onSave = renderScreen();

    // aria-labelledby 가 붙은 <section> 의 역할은 region 이다(group 이 아니다)
    const group = screen.getByRole("region", { name: /기피/ });
    await user.click(within(group).getByLabelText(/1층/));
    await user.click(screen.getByRole("button", { name: "저장하고 다시 계산" }));

    const [, prefs] = onSave.mock.calls[0] as [Profile, Preferences];
    expect(prefs.avoid.first_floor).toBe(true);
  });
});
