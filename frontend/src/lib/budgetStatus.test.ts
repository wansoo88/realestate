/**
 * 예산 기준 — **서버가 말한 것**과 **화면이 판정한 것**을 다루는 규칙.
 *
 * 이 파일이 지키는 두 가지
 *  ① **모름을 아님으로 접지 않는다.** `over_budget: null` 은 "예산 내"가 아니고,
 *     `budget` 블록이 없는 것은 "적용 안 됨"이 아니다.
 *  ② **켰는데 아무 일도 안 일어났으면 말한다.** `applied:false` 로 왔는데 화면이
 *     침묵하면, 사용자는 조건이 걸린 줄 알고 예산 밖 단지를 본다.
 */
import { describe, expect, it } from "vitest";
import type { MapBudget } from "../api/client";
import { basisLabel, budgetStatusView } from "./budgetStatus";

function block(over: Partial<MapBudget> = {}): MapBudget {
  return { applied: true, basis: "target_price", reason: null, ...over };
}

/** 서버 사유 원문(백엔드 `_BUDGET_NO_PROFILE`). 화면은 이 문장을 그대로 전한다. */
const NO_PROFILE =
  "자산 정보가 없어 예산 기준을 세우지 못했습니다 — 내 정보에서 보유 현금·연소득을 " +
  "입력하거나 희망 매매가를 정하면 예산 초과 여부를 표시합니다.";

describe("budgetStatusView — 서버가 예산을 걸었는가", () => {
  it("블록이 없으면 **아무 주장도 하지 않는다** (구버전 ≠ 적용 안 됨)", () => {
    for (const budget of [undefined, null]) {
      const v = budgetStatusView({ budget, requested: true, screenBasis: "target_price" });
      // applied:false 가 아니라 null 이다 — "안 걸렸다"고 말할 근거가 없다.
      expect(v.applied).toBeNull();
      expect(v.notice).toBeNull();
    }
  });

  it("기준이 같으면 조용하다 — 할 말 없을 때 말하지 않는 것도 규칙이다", () => {
    const v = budgetStatusView({
      budget: block({ basis: "target_price" }),
      requested: true,
      screenBasis: "target_price",
    });
    expect(v).toEqual({ applied: true, notice: null, basisMismatch: false });
  });

  it("**applied:false 면 서버가 준 사유를 그대로 말한다**", () => {
    const v = budgetStatusView({
      budget: block({ applied: false, basis: null, reason: NO_PROFILE }),
      requested: true,
      screenBasis: null,
    });
    expect(v.applied).toBe(false);
    expect(v.notice).toContain("적용되지 않았습니다");
    // 사유를 요약하거나 지어내지 않는다 — 서버 문장이 살아 있어야 한다.
    expect(v.notice).toContain("자산 정보가 없어");
    expect(v.notice).toContain("보유 현금·연소득");
  });

  /**
   * 서버가 못 세웠는데 화면은 한도를 알고 있는 조합(서버 키·세율 설정 오류 +
   * `/affordability` 는 성공). **판정은 서버가 하므로 이때 배지는 아예 안 뜬다** —
   * 그 사실을 말하지 않으면 사용자는 "예산 안이라서 안 뜨는구나"로 읽는다(CR38-1).
   */
  it("서버가 못 세웠으면 **표시가 안 뜬다는 사실**까지 말한다", () => {
    const v = budgetStatusView({
      budget: block({ applied: false, basis: null, reason: "예산 계산에 필요한 설정을 읽지 못했습니다." }),
      requested: true,
      screenBasis: "max_purchase",
    });
    expect(v.notice).toContain("자산으로 계산한 한도");
    expect(v.notice).toContain("예산 초과 표시가 뜨지 않습니다");
    // 예전 문장("화면이 판정한 값입니다")은 이제 거짓이다 — 화면은 판정하지 않는다.
    expect(v.notice).not.toContain("화면이 판정한 값");
  });

  it("화면 기준을 모를 때도 '표시가 안 뜬다'는 사실은 말한다", () => {
    const v = budgetStatusView({
      budget: block({ applied: false, basis: null, reason: NO_PROFILE }),
      requested: true,
      screenBasis: null,
    });
    expect(v.notice).toContain("예산 초과 표시가 뜨지 않습니다");
  });

  it("사유가 없거나 코드 모양이면 **지어내지 않고** 그 사실을 말한다", () => {
    for (const reason of [null, "", "BUDGET_ERR_42"]) {
      const v = budgetStatusView({
        budget: block({ applied: false, basis: null, reason }),
        requested: true,
        screenBasis: null,
      });
      expect(v.notice).toContain("사유를 알려주지 않았습니다");
      expect(v.notice).not.toContain("BUDGET_ERR_42"); // 내부 코드는 화면에 내지 않는다
    }
  });

  /**
   * 🔔 **진짜 신호는 여기서 잡는다** (CR38-1).
   *
   * 예전 카나리아(`checkVerdicts`)가 잡으려던 사실 — "저장한 희망 매매가가 서버에
   * 반영되지 않았다" — 을 이 분기가 **사유 문장까지 붙여** 잡는다. 카나리아는 같은
   * 사실을 건수로만 말하면서, 사용자가 손댈 수 없는 이유(면적 구간 차이)로도 울었다.
   */
  it("**희망가를 정했는데 서버가 한도로 걸렀으면** 알려준다 (basis 불일치)", () => {
    const v = budgetStatusView({
      budget: block({ basis: "max_purchase" }),
      requested: true,
      screenBasis: "target_price",
    });
    expect(v.basisMismatch).toBe(true);
    expect(v.notice).toContain("자산으로 계산한 한도");
    expect(v.notice).toContain("저장한 희망 매매가");
    // 사용자가 할 수 있는 일까지 말한다(원인이 대개 '저장이 안 닿았다'이므로)
    expect(v.notice).toContain("다시 저장");
  });

  it("반대 방향 불일치도 사실만 말한다(원인을 단정하지 않는다)", () => {
    const v = budgetStatusView({
      budget: block({ basis: "target_price" }),
      requested: true,
      screenBasis: "max_purchase",
    });
    expect(v.basisMismatch).toBe(true);
    expect(v.notice).not.toContain("다시 저장");
    expect(v.notice).toContain("다르게 보일 수 있습니다");
  });

  it("basis:null 인데 applied:true 면 '무엇으로 걸렀는지 모른다'고 말한다", () => {
    const v = budgetStatusView({
      budget: block({ applied: true, basis: null }),
      requested: true,
      screenBasis: "target_price",
    });
    expect(v.applied).toBe(true);
    expect(v.basisMismatch).toBe(false); // 다른 게 아니라 **모르는** 것이다
    expect(v.notice).toContain("무엇을 기준으로 했는지 알려주지 않았습니다");
  });

  it("안 켰는데 서버가 걸렀으면 그것도 말한다(조건을 끈 줄 알면 안 된다)", () => {
    const on = budgetStatusView({
      budget: block(),
      requested: false,
      screenBasis: "target_price",
    });
    expect(on.notice).toContain("예산 조건을 껐는데");

    // 끈 상태에서 서버도 안 걸렀으면 정상이다 → 조용하다
    const off = budgetStatusView({
      budget: block({ applied: false, basis: null }),
      requested: false,
      screenBasis: null,
    });
    expect(off.notice).toBeNull();
  });

  it("서버 문장은 길이를 자르되 **내용을 바꾸지 않는다**", () => {
    const long = `예산 기준을 세우지 못했습니다. ${"가".repeat(400)}`;
    const v = budgetStatusView({
      budget: block({ applied: false, basis: null, reason: long }),
      requested: true,
      screenBasis: null,
    });
    expect(v.notice).toContain("예산 기준을 세우지 못했습니다");
    expect(v.notice).toContain("…"); // 잘렸다는 사실이 보인다
    expect(v.notice!.length).toBeLessThan(300);
  });

  it("줄바꿈·제어문자가 섞여 와도 한 줄로 눕힌다(레이아웃을 깨지 않는다)", () => {
    const v = budgetStatusView({
      budget: block({ applied: false, basis: null, reason: "예산 기준\n\n실패\t사유" }),
      requested: true,
      screenBasis: null,
    });
    expect(v.notice).toContain("예산 기준 실패 사유");
    expect(v.notice).not.toContain("\n");
  });
});

describe("basisLabel — 계약에 없는 값을 지어내지 않는다", () => {
  it("아는 값은 사람 말로, 모르는 값은 '알 수 없는 기준'", () => {
    expect(basisLabel("target_price")).toBe("저장한 희망 매매가");
    expect(basisLabel("max_purchase")).toBe("자산으로 계산한 한도");
    expect(basisLabel(null)).toBe("알 수 없는 기준");
  });
});

/* ────────────────────────────────────────────────────────────────────────
 * 카나리아(`checkVerdicts` · `verdictConflictNotice`)는 **삭제됐다** (CR38-1).
 *
 * 그것이 세던 것은 "서버 판정 ≠ 화면 판정"이었는데, 화면이 판정을 그만두면서
 * 비교할 두 벌 자체가 사라졌다. 그리고 지워도 되는 이유가 하나 더 있다 —
 * 남아 있던 마지막 라운드에 그것이 울린 **체계적인 사유는 오탐 하나뿐**이었다:
 * 면적 구간(85㎡) 때문에 서버 상한과 화면의 한 숫자가 갈리는 것. 사용자가 손댈 수
 * 없는 이유로 우는 경보는 다음번 진짜 경보를 못 듣게 만든다.
 *
 * 진짜 신호("저장한 희망 매매가가 서버에 안 닿았다")는 위 `basisMismatch` 분기가
 * 계속 잡는다 — 건수가 아니라 **사유 문장까지** 붙여서. 아래가 그 자리를 못박는다.
 * ──────────────────────────────────────────────────────────────────────── */

describe("카나리아가 잡던 진짜 신호는 basisMismatch 가 계속 잡는다", () => {
  it("희망가를 정했는데 서버가 한도로 판정하면 **반드시** 말한다", () => {
    const v = budgetStatusView({
      budget: block({ applied: true, basis: "max_purchase", reason: null }),
      requested: true,
      screenBasis: "target_price",
    });
    expect(v.basisMismatch).toBe(true);
    expect(v.notice).not.toBeNull();
    // 카나리아는 건수만 말했다. 이쪽은 무엇을 하면 되는지까지 말한다.
    expect(v.notice).toContain("다시 저장");
  });

  it("기준이 같으면 조용하다 — 면적 구간 차이로는 더 이상 울지 않는다", () => {
    // 예전 카나리아는 이 상태(기준 동일 · 서버가 항목별로 정확히 판정)에서도
    // 면적이 섞였다는 이유만으로 울었다. 그게 유일하게 남은 발화 사유였다.
    const v = budgetStatusView({
      budget: block({ applied: true, basis: "max_purchase", reason: null }),
      requested: true,
      screenBasis: "max_purchase",
    });
    expect(v.basisMismatch).toBe(false);
    expect(v.notice).toBeNull();
  });
});
