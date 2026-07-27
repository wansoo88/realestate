/**
 * 선호/기피 조건 관련 **순수 함수**.
 *
 * 가중치는 화면에서 0~100 슬라이더로 다루지만 서버 계약은 합이 1 인 비율이다.
 * 사용자에게 "합을 100 으로 맞추세요"라고 시키면 아무도 안 만진다 → **자동 정규화**한다
 * (components.md §5.4).
 */
import type { Preferences } from "../api/client";

export type Weights = NonNullable<Preferences["weights"]>;

/**
 * 사용자가 손대지 않으면 이 값이 나간다.
 *
 * `redevelopment` 15% 는 임의로 고른 값이 아니라 **서버가 이미 적용하고 있는 기본값**이다
 * (`scoring.py::DEFAULT_AXIS_WEIGHTS`). 나머지 넷은 api-spec §2 예시값의 비율을 그대로
 * 유지한 채 5 단위로 떨어지게 맞췄다(슬라이더 step 이 5 라 표시와 값이 어긋나지 않게).
 */
export const DEFAULT_WEIGHTS: Required<Weights> = {
  price: 0.25,
  location: 0.25,
  value: 0.2,
  risk: 0.15,
  redevelopment: 0.15,
};

export type WeightKey = keyof Required<Weights>;

export const WEIGHT_KEYS: WeightKey[] = [
  "price",
  "location",
  "value",
  "risk",
  "redevelopment",
];

export const WEIGHT_LABELS: Record<WeightKey, string> = {
  price: "가격",
  location: "입지",
  value: "가치",
  risk: "리스크",
  redevelopment: "재건축",
};

/**
 * 사용자가 **언급조차 하지 않은** 축에 서버가 넣는 기본 비중
 * (`scoring.py::DEFAULT_AXIS_WEIGHTS` 와 같은 값 · 같은 규칙).
 *
 * ⚠️ 이 상수의 존재 이유가 곧 FE-5 의 핵심이다: **"안 보냄"과 "0"이 다르다.**
 *    · 저장된 가중치에 `redevelopment` 키가 **없으면** 서버가 15% 를 넣는다.
 *    · 사용자가 슬라이더를 0 으로 내려 **0 을 명시하면** 서버가 존중한다.
 *    그래서 화면은 (a) 키가 없는 사용자에게 15% 를 **보여주고**(effectiveWeights),
 *    (b) 저장할 때는 0 도 값으로 **실어 보낸다**(normalizeWeights 가 전 축을 채운다).
 *    (a) 를 빼먹으면 화면은 0% 를 보여주는데 서버는 15% 로 순위를 매긴다.
 */
export const DEFAULT_AXIS_WEIGHTS: Partial<Record<WeightKey, number>> = {
  redevelopment: 0.15,
};

/* ─────────────────────────────────────────────────────────────────────────
 * 가중치 설명 · **무엇이 어디까지 반영되는가**
 *
 * 근거: `docs/02-design/api-spec.md` §5.3 · `backend/app/agents/scoring.py::AXIS_SPECS`(정본).
 * 서버는 이제 사용자 가중치를 총점에 **실제로** 반영한다(WEIGHT-1):
 *   total = Σ(wᵢ·scoreᵢ) / Σ(wᵢ) — **근거가 있는 축만**, 나머지 가중치는 재정규화.
 *   (confidence 를 곱하지 않는다 — 사용자가 준 30% 가 내부 신뢰도 때문에 조용히 21% 로
 *    줄면 슬라이더가 예측 불가능해진다.)
 *
 * 그래서 화면이 말해야 하는 것이 둘로 나뉜다.
 *   ① **구조적 한계**(여기 상수) — 그 축이 애초에 무엇까지만 보는가(coverage=partial).
 *      데이터가 다 들어와도 사라지지 않는다. 예: 리스크는 '매물 신뢰도'까지만이고
 *      권리관계·근저당·재건축 분담금(risk-auditor)은 2차라 들어가지 않는다.
 *   ② **지금 근거가 있는가**(동적) — 결과의 `score_axes[].status` 가 정본이다.
 *      운영 실측(2026-07-26): listing 0행 · poi/school_district/road_segment 0행 →
 *      가격·입지·리스크는 근거 0건이고 **살아 있는 축은 가치 하나뿐**이다.
 *      이건 데이터가 들어오면 바뀌므로 **하드코딩하지 않는다**(lib/scoreAxes 가 관측한다).
 *
 * 이 파일은 ①의 단일 판단 지점이다. 화면 곳곳에 `if (key === "risk")` 를 흩뿌리지 않는다.
 * ───────────────────────────────────────────────────────────────────────── */

/** 그 축이 설계상 어디까지 보는가 (서버 AXIS_SPECS.coverage 와 같은 말). */
export type WeightCoverage =
  /** 설계한 신호를 다 본다 */
  | "full"
  /** 일부만 본다 — 무엇이 빠졌는지 `coverageGap` 에 반드시 적는다 */
  | "partial";

export interface WeightMeta {
  key: WeightKey;
  /** 라벨 옆 한 마디 — 항목 간 차이를 **여기서** 가른다. */
  tagline: string;
  /** 항상 보이는 한 줄 설명(툴팁을 못 여는 상황에서도 읽혀야 한다). */
  summary: string;
  /** 펼쳤을 때 보이는 자세한 설명. */
  detail: string;
  /** 점수로 쓰는 신호(서버 AXIS_SPECS.signal 과 같은 내용). */
  signal: string;
  /** 어느 전문가 판단에 실리는가(근거 추적 — ux/README §6). */
  agent: string;
  coverage: WeightCoverage;
  /** partial 이면 **무엇이 빠졌는지**. 반영 여부와 무관하게 늘 보여준다(계약 §5.3). */
  coverageGap: string | null;
}

/**
 * 항목 정의 — 서버 `AXIS_SPECS` 와 같은 매핑.
 *
 * `price` 와 `value` 의 차이가 사용자 지적의 핵심이다. 확정된 신호로 다시 갈랐다:
 *   가격 = **지금 이 호가가 적정가 대비 싼가**(호가 − 적정가 밴드 갭)
 *   가치 = **잘 팔리는가**(12개월 거래회전율 = 환금성)
 * 완전히 다른 질문이다 — 싸게 나온 물건이 안 팔리는 물건일 수도 있다.
 */
export const WEIGHT_META: Record<WeightKey, WeightMeta> = {
  price: {
    key: "price",
    tagline: "지금 싸게 사는가",
    summary: "지금 나온 호가가 최근 실거래 적정가보다 싼지 비싼지.",
    detail:
      "호가와 적정가 밴드(같은 면적 최근 실거래의 중위값)의 차이를 점수로 씁니다. " +
      "밴드보다 싸게 나왔으면 높은 점수입니다. " +
      "'이 집이 좋은 집인가'가 아니라 '지금 이 값이 싼가'만 봅니다. " +
      "예산 자체는 이 축에 없습니다 — 못 사는 집은 취향이 아니라 후보에서 빠집니다.",
    signal: "호가 − 적정가 밴드 중위 갭",
    agent: "매매 전문가(valuation-trader)",
    coverage: "full",
    coverageGap: null,
  },
  location: {
    key: "location",
    tagline: "학군·교통·생활",
    summary: "학구도·역세권·생활 인프라를 종합한 입지 점수.",
    detail:
      "학구도와 학업성취도, 지하철 도보거리, 생활 인프라 근접성을 종합해 점수를 냅니다. " +
      "설계상 입지 신호를 모두 보지만, 그 원천 데이터(학구도·지하철·도로)가 수집되어 있어야 " +
      "점수가 만들어집니다.",
    signal: "학군·역세권·생활 인프라 근접 종합",
    agent: "지역 전문가(location-analyst)",
    coverage: "full",
    coverageGap: null,
  },
  value: {
    key: "value",
    tagline: "잘 팔리는가(환금성)",
    summary: "12개월 거래회전율 — 팔고 싶을 때 팔리는 단지인지.",
    detail:
      "최근 12개월 거래회전율로 환금성을 점수화합니다(5% 이상이면 만점). " +
      "싸게 사는 것과 다른 질문입니다 — 싸도 안 팔리면 자산으로서 위험합니다.",
    signal: "12개월 거래회전율(환금성)",
    agent: "매매 전문가(valuation-trader)",
    coverage: "partial",
    coverageGap:
      "같은 단지 안 동별 가격 편차는 '어느 동이 비싼가'를 재는 값이라 " +
      "후보 점수로 환산하지 않고 참고 정보로만 보여줍니다.",
  },
  risk: {
    key: "risk",
    tagline: "매물을 믿을 수 있는가",
    summary: "허위·미끼·중복 등록을 걸러낸 매물 신뢰도.",
    detail:
      "지금 이 축이 재는 것은 **매물 정보의 신뢰도**입니다(허위·미끼·중복 등록 탐지).",
    signal: "매물 신뢰도(허위·미끼·중복 탐지)",
    agent: "매물 리서처(listing-researcher)",
    coverage: "partial",
    coverageGap:
      "권리관계·근저당·재건축 추가분담금·깡통전세 분석(리스크 검증가)은 2차 기능이라 " +
      "이 점수에 들어가지 않습니다. 호가가 들어와도 이 부분은 여전히 반영되지 않습니다.",
  },
  /**
   * 재건축 — **다른 축과 성질이 다르다.**
   *
   * 나머지 넷은 "높을수록 좋다"가 성립하는 값(싼가·가깝나·잘 팔리나·믿을 만한가)이다.
   * 이 축은 아니다. 서버는 정비사업 **진행 단계**를 목적별 리스크-수익 프로파일로
   * 환산하는데(`redevelopment/analysis.py::STAGE_PROFILE`), 실거주와 투자에서
   * 같은 단계가 **정반대 점수**를 받는다:
   *   · 사업시행인가 — 투자 85점(사업 내용이 확정돼 불확실성이 가장 낮은 정점)
   *                    / 실거주 35점(이주가 가시권이다)
   *   · 관리처분·이주 — 투자 65·55점 / 실거주 25·15점(그 집에서 살 수 없다)
   *   · 준공        — 투자 30점(프리미엄 소멸) / 실거주 60점(새 아파트)
   * 지금 화면은 **실거주 기준 고정**(App.tsx `PURPOSE = "live"`)이라 실거주 프로파일이
   * 쓰인다. 이 설명이 없으면 사용자는 비중을 올리는 것이 "재건축 단지를 더 위로"라는
   * 뜻이라고 읽는데, 실거주 기준에서는 오히려 **초기 단계·준공 단지가 위로 온다**.
   */
  redevelopment: {
    key: "redevelopment",
    tagline: "정비사업 단계가 내 계획과 맞는가",
    summary: "재건축·재개발 진행 단계를 실거주 기준으로 점수화합니다(단계가 뒤일수록 높은 점수가 아닙니다).",
    detail:
      "고시된 정비사업 진행 단계(구역지정 → 조합설립 → 사업시행인가 → 관리처분 → 이주·착공 → 준공)를 " +
      "점수로 씁니다. **단계가 앞서 있을수록 좋다는 뜻이 아닙니다** — 같은 단계가 실거주와 투자에서 " +
      "정반대로 읽히기 때문입니다. 투자에서는 사업시행인가가 불확실성이 가장 낮은 정점이지만, " +
      "실거주에서는 그 시점이 이주가 가시권에 든 때라 낮은 점수입니다. 관리처분·이주 단계는 " +
      "그 집에서 살 수 없어 실거주에는 사실상 부적합하고, 준공된 새 아파트는 반대로 높습니다. " +
      "지금 이 화면은 실거주 기준으로 계산합니다. " +
      "이 비중을 0 으로 내리면 정비사업 단계를 순위에 아예 넣지 않습니다.",
    signal: "정비사업 진행 단계 → 목적(실거주)별 리스크-수익 프로파일",
    agent: "정비사업 분석(redevelopment-analyst)",
    coverage: "partial",
    coverageGap:
      "추가분담금·조합 사업성 자료는 공개 데이터에 없어 반영하지 않습니다(금액은 조합에 직접 확인하세요). " +
      "수집 범위도 서울·인천뿐이라 경기도 단지의 '정보 없음'은 **'정비사업이 없다'는 뜻이 아닙니다** — " +
      "확인되지 않았다는 뜻입니다.",
  },
};

/**
 * 서버가 사용자 가중치를 **점수에 실제로 반영하는가**.
 *
 * WEIGHT-1(2026-07-26) 로 true 가 됐다 — `scoring.py` 가 Σ(w·score)/Σ(w) 로 총점을 만든다.
 * 배포 순서가 어긋나도 화면이 거짓말하지 않도록, 결과가 있으면 **서버의 `score_basis` 를
 * 상수보다 우선**한다(아래 `weightsApplied`).
 */
export const SERVER_APPLIES_WEIGHTS = true;

/**
 * 이번 결과가 사용자 가중치로 매겨졌는지.
 *
 * ⚠️ `score_basis === "agent_scores"` 는 **가중치가 반영된 점수가 아니다**(계약 §5.3).
 *    가중치가 없거나 전부 0 이라 예전 방식(신뢰도 가중 평균)으로 폴백한 경우다.
 */
export function weightsApplied(scoreBasis?: string | null): boolean {
  if (scoreBasis === "agent_scores") return false;
  if (scoreBasis && /user[_-]?weight/i.test(scoreBasis)) return true;
  return SERVER_APPLIES_WEIGHTS;
}

export type WeightStatus =
  /** 가중치도 반영되고 근거도 있다 */
  | "applied"
  /** 가중치는 반영되지만 이 축의 **근거가 지금 0건**이다(관측값) */
  | "no_signal"
  /** 서버가 아직 가중치를 쓰지 않는다(구버전 배포) */
  | "not_scored_yet";

/**
 * 이 항목이 지금 어떤 상태인가. 화면은 이 값만 보고 표시를 정한다.
 *
 * @param observedNoSignal 직전 분석에서 이 축에 근거가 없었는가(lib/scoreAxes 관측값).
 *        `undefined` 면 아직 분석을 돌린 적이 없다는 뜻이라 단정하지 않는다.
 */
export function weightStatus(
  key: WeightKey,
  opts: { scoreBasis?: string | null; observedNoSignal?: boolean } = {},
): WeightStatus {
  void key; // 축별 구조 차이는 coverage 로 말한다 — 상태는 관측값으로만 정한다
  if (!weightsApplied(opts.scoreBasis)) return "not_scored_yet";
  return opts.observedNoSignal ? "no_signal" : "applied";
}

/** 상태 문구 — 사용자에게 그대로 보여줄 말. 정상 반영이면 null(할 말이 없다). */
export function weightStatusNote(status: WeightStatus, key?: WeightKey): string | null {
  switch (status) {
    case "no_signal":
      return key
        ? `직전 분석에서는 ${WEIGHT_LABELS[key]} 근거가 없어 이 비중이 반영되지 않았습니다.`
        : "직전 분석에서는 근거가 없어 이 비중이 반영되지 않았습니다.";
    case "not_scored_yet":
      return "설정은 저장되지만 아직 추천 순위 계산에 반영되지 않습니다.";
    default:
      return null;
  }
}

/**
 * 슬라이더를 조작하게 둘 것인가 — **이제 넷 다 조작할 수 있다.**
 *
 * WEIGHT-1 이전에는 근거가 구조적으로 없는 축을 잠갔다. 지금은 서버가 가중치를 실제로
 * 반영하고, 근거가 없는 축은 **재정규화로 빠지면서 사유가 고지된다.** 잠그는 대신
 * "지금 근거가 없다"를 옆에 적는 편이 정확하다 — 데이터가 들어오면 즉시 살아나는 값이므로,
 * 잠가 버리면 이번엔 화면이 반대 방향으로 거짓말을 하게 된다.
 */
export function isWeightAdjustable(): boolean {
  return true;
}

/**
 * 합이 1 이 되게 맞춘다. 전부 0 이면(사용자가 다 내렸으면) 기본값으로 되돌린다 —
 * 합 0 을 그대로 보내면 서버에서 0 나눗셈이거나 "아무것도 중요하지 않다"는 뜻이 된다.
 */
export function normalizeWeights(w: Weights | null | undefined): Required<Weights> {
  const raw = WEIGHT_KEYS.map((k) => {
    const v = w?.[k];
    return typeof v === "number" && Number.isFinite(v) && v > 0 ? v : 0;
  });
  const sum = raw.reduce((a, b) => a + b, 0);
  if (sum <= 0) return { ...DEFAULT_WEIGHTS };

  const out = {} as Required<Weights>;
  WEIGHT_KEYS.forEach((k, i) => {
    // 소수 4자리로 끊는다 — 화면에 8.333333%가 뜨는 것보다 낫고, 서버는 비율만 본다.
    out[k] = Math.round((raw[i] / sum) * 10_000) / 10_000;
  });
  return out;
}

/**
 * 저장된 가중치 → **서버가 지금 실제로 적용하는** 비율. 조건 화면의 초기값이다.
 *
 * 왜 저장값을 그대로 쓰면 안 되나
 * -------------------------------
 * 기존 사용자의 저장값에는 `redevelopment` 키가 없다. 그대로 슬라이더에 꽂으면 화면은
 * **0%** 를 보여주는데 서버는 **15%** 로 순위를 매긴다 — 화면이 거짓말을 한다.
 * 게다가 그 상태로 저장 버튼을 누르면 (모든 축을 실어 보내므로) 사용자가 의도한 적 없는
 * **명시적 0** 이 저장되어, 보고 있던 화면이 원인이 되어 설정이 조용히 바뀐다.
 *
 * 그래서 서버 `normalize_weights` 와 **같은 규칙**으로 되살린다:
 * 언급되지 않은 축에만 기본 비중을 넣고, 나머지 축의 **상대 비율은 그대로** 둔다.
 * (30:30:25:15 → 25.5:25.5:21.25:12.75 — 비율이 보존된다. 사용자 설정을 바꾸는 게 아니라
 *  지금 적용 중인 값을 그대로 보여주는 것이다.)
 */
export function effectiveWeights(saved: Weights | null | undefined): Required<Weights> {
  const raw: Partial<Record<WeightKey, number>> = {};
  let sum = 0;
  for (const k of WEIGHT_KEYS) {
    const v = saved?.[k];
    if (typeof v === "number" && Number.isFinite(v) && v > 0) {
      raw[k] = v;
      sum += v;
    }
  }
  // 쓸 수 있는 값이 하나도 없다 = 아직 정한 적이 없다 → 기본값(서버도 폴백한다).
  if (sum <= 0) return { ...DEFAULT_WEIGHTS };

  // ⚠️ **키의 존재 여부**로 판단한다. 값이 0 이어도 "언급했다"이므로 되살리지 않는다.
  const mentioned = new Set(Object.keys(saved ?? {}));
  for (const [axis, share] of Object.entries(DEFAULT_AXIS_WEIGHTS)) {
    if (mentioned.has(axis) || !(share > 0 && share < 1)) continue;
    raw[axis as WeightKey] = (share / (1 - share)) * sum;
  }
  return normalizeWeights(raw);
}

/** 슬라이더 표시용 정수 퍼센트(합 100 이 아닐 수 있음 — 반올림 오차는 표시에만 영향). */
export function weightPercent(w: Weights, key: keyof Required<Weights>): number {
  return Math.round((normalizeWeights(w)[key] ?? 0) * 100);
}
