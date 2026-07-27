/**
 * 내 조건 — 이 제품의 **입력 쪽 절반** (F2·F5).
 *
 * 왜 이 화면이 지도보다 먼저인가
 * ------------------------------
 * 자산이 없으면 예산이 없고, 예산이 없으면 "내 조건에 맞는 매물"이라는 말 자체가 성립하지 않는다.
 * 매물만 쭉 뜨는 화면은 지도 뷰어지 자문 도구가 아니다. 그래서 프로필이 비어 있으면
 * 앱은 지도가 아니라 이 화면을 먼저 보여준다(App.tsx).
 *
 * 🔐 입력값은 개인 금융정보다. 메모리 상태로만 다루고 로그·저장소에 남기지 않는다(G3).
 */
import { useState } from "react";
import { ApiException, type Preferences, type Profile } from "../api/client";
import { readTargetPrice, withTargetPrice } from "../lib/affordability";
import { NOTICE_TRUST } from "../lib/notices";
import {
  WEIGHT_KEYS,
  WEIGHT_LABELS,
  WEIGHT_META,
  effectiveWeights,
  normalizeWeights,
  weightStatus,
  weightStatusNote,
  weightsApplied,
  type Weights,
} from "../lib/preferences";
import { observedNoSignal } from "../lib/scoreAxes";
import { InfoTip } from "./InfoTip";
import { MoneyField } from "./MoneyField";
import { TargetPriceField } from "./TargetPriceField";
import "./ConditionsScreen.css";

interface Props {
  profile: Profile | null;
  preferences: Preferences;
  onSave: (profile: Profile, preferences: Preferences) => Promise<void>;
  /** 이미 저장된 조건을 고치는 경우에만 닫기가 있다(최초 입력은 되돌아갈 곳이 없다). */
  onClose?: () => void;
  /**
   * 최대 실구매 가능 금액(`/affordability`). 희망가 슬라이더의 **범위 기준**이다.
   * 최초 입력처럼 아직 계산이 없으면 null — 그때도 슬라이더는 동작하되 한도 비교를
   * 하지 않는다(모르는 한도를 그리지 않는다).
   */
  maxPurchaseKrw?: number | null;
}

/** 역세권 거리 선택지 — 자유 입력보다 낫다. 300m·500m 는 걸어서 4~7분이라는 감각이 있다. */
const SUBWAY_OPTIONS: Array<{ value: number | null; label: string }> = [
  { value: null, label: "상관없음" },
  { value: 300, label: "300m 이내" },
  { value: 500, label: "500m 이내" },
  { value: 1000, label: "1km 이내" },
];

const AVOID_ITEMS: Array<{ key: keyof Preferences["avoid"]; label: string; hint: string }> = [
  { key: "first_floor", label: "1층", hint: "사생활·채광 문제로 환금성이 낮습니다" },
  { key: "main_road_noise", label: "대로변 소음", hint: "간선도로 인접 동" },
  {
    key: "redevelopment_early_stage",
    label: "재건축 초기 단계",
    hint: "사업 기간·추가분담금 불확실성이 큽니다",
  },
];

function toInt(v: string, min: number, max: number, fallback: number): number {
  const n = Number.parseInt(v, 10);
  if (Number.isNaN(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

/** 빈 문자열 = 미입력(null). 0 과 구분한다. */
function toNullableInt(v: string): number | null {
  if (v.trim() === "") return null;
  const n = Number.parseInt(v, 10);
  return Number.isNaN(n) ? null : n;
}

export function ConditionsScreen({
  profile,
  preferences,
  onSave,
  onClose,
  maxPurchaseKrw = null,
}: Props) {
  // 자산 — null 은 "아직 안 씀"이다. 0 으로 초기화하면 안 쓴 것과 0원이 구분되지 않는다.
  const [cash, setCash] = useState<number | null>(profile?.cash_krw ?? null);
  const [income, setIncome] = useState<number | null>(profile?.income_krw ?? null);
  const [loan, setLoan] = useState<number | null>(profile?.existing_loan_krw ?? null);
  const [ownedHouses, setOwnedHouses] = useState(profile?.owned_houses ?? 0);
  const [householdSize, setHouseholdSize] = useState(profile?.household_size ?? 1);

  const [prefer, setPrefer] = useState<Preferences["prefer"]>(preferences.prefer ?? {});
  /**
   * 희망 매매가는 `prefer.target_price_krw` 에 산다(서버 `PreferencesIn` 이 열린 dict).
   * 별도 state 를 두지 않고 `prefer` 에서 읽고 `prefer` 에 쓴다 — 상태를 둘로 나누면
   * 저장 직전에 둘 중 하나를 빠뜨리는 순간 "슬라이더는 움직였는데 저장은 안 된" 값이 된다.
   */
  const targetPrice = readTargetPrice(prefer);
  const [avoid, setAvoid] = useState<Preferences["avoid"]>(preferences.avoid ?? {});
  /**
   * 가중치 초기값은 저장값이 아니라 **지금 서버가 적용 중인 값**이다(effectiveWeights).
   * 저장값에 `redevelopment` 가 없는 기존 사용자에게 0% 를 보여주면, 화면은 0 이라고 하고
   * 서버는 15% 로 순위를 매기는 상태가 된다 — 그리고 그대로 저장하면 의도한 적 없는
   * 명시적 0 이 저장된다(FE-5).
   */
  const [weights, setWeights] = useState<Weights>(effectiveWeights(preferences.weights));

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cashOk = cash !== null;
  const incomeOk = income !== null;
  const canSubmit = cashOk && incomeOk && !busy;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit || cash === null || income === null) return;
    setBusy(true);
    setError(null);
    try {
      await onSave(
        {
          cash_krw: cash,
          income_krw: income,
          existing_loan_krw: loan ?? 0,
          owned_houses: ownedHouses,
          household_size: householdSize,
        },
        { prefer, avoid, weights: normalizeWeights(weights) },
      );
    } catch (err) {
      setError(
        err instanceof ApiException
          ? err.error.message || "저장하지 못했습니다."
          : "네트워크 오류로 저장하지 못했습니다.",
      );
    } finally {
      setBusy(false);
    }
  }

  const normalized = normalizeWeights(weights);

  return (
    <main className="cond">
      <form className="cond__form" onSubmit={submit} noValidate>
        <header className="cond__header">
          <h1 className="cond__title">내 조건</h1>
          <p className="cond__lede">
            {profile
              ? "조건을 바꾸면 지도와 추천이 함께 바뀝니다."
              : "자산을 입력해야 최대 실구매 가능 금액과 추천을 계산할 수 있습니다."}
          </p>
        </header>

        {/* 민감정보를 요구하기 **전에** 왜/어떻게 보관하는지 말한다(components.md §3.6) */}
        <p className="cond__trust">{NOTICE_TRUST}</p>

        <section className="cond__group" aria-labelledby="cond-assets">
          <h2 className="cond__group-title" id="cond-assets">
            자산
          </h2>
          <MoneyField
            id="cond-cash"
            label="보유 현금"
            valueKrw={cash}
            onChange={setCash}
            hint="예금·주식 등 매수에 쓸 수 있는 돈"
            error={!cashOk && busy ? "보유 현금을 입력해 주세요." : undefined}
            required
          />
          <MoneyField
            id="cond-income"
            label="연 소득 (세전)"
            valueKrw={income}
            onChange={setIncome}
            hint="DSR·DTI 한도 계산에 쓰입니다"
            required
          />
          <MoneyField
            id="cond-loan"
            label="기존 대출 잔액"
            valueKrw={loan}
            onChange={setLoan}
            hint="없으면 비워 두세요"
          />

          <div className="cond__row">
            <label className="cond__label" htmlFor="cond-houses">
              보유 주택 수
            </label>
            <input
              id="cond-houses"
              className="cond__number num"
              type="number"
              inputMode="numeric"
              min={0}
              max={100}
              value={ownedHouses}
              onChange={(e) => setOwnedHouses(toInt(e.target.value, 0, 100, 0))}
            />
          </div>

          <div className="cond__row">
            <label className="cond__label" htmlFor="cond-household">
              가구원 수
            </label>
            <input
              id="cond-household"
              className="cond__number num"
              type="number"
              inputMode="numeric"
              min={1}
              max={20}
              value={householdSize}
              onChange={(e) => setHouseholdSize(toInt(e.target.value, 1, 20, 1))}
            />
          </div>
        </section>

        {/* ── 희망 매매가 ───────────────────────────────────────────────────
            자산 바로 다음에 둔다. "얼마 있나" 다음 질문은 "얼마짜리를 볼까"이고,
            이 값이 지도·추천·자금계획 셋을 동시에 움직이기 때문이다(선호보다 앞선다). */}
        <section className="cond__group" aria-labelledby="cond-target">
          <h2 className="cond__group-title" id="cond-target">
            희망 매매가
          </h2>
          <TargetPriceField
            id="cond-target-price"
            valueKrw={targetPrice}
            onChange={(krw) => setPrefer((p) => withTargetPrice(p, krw))}
            maxPurchaseKrw={maxPurchaseKrw}
          />
        </section>

        <section className="cond__group" aria-labelledby="cond-prefer">
          <h2 className="cond__group-title" id="cond-prefer">
            선호
          </h2>

          <div className="cond__row">
            <label className="cond__label" htmlFor="cond-subway">
              역세권
            </label>
            <select
              id="cond-subway"
              className="cond__select"
              value={prefer.subway_within_m ?? ""}
              onChange={(e) =>
                setPrefer({ ...prefer, subway_within_m: toNullableInt(e.target.value) })
              }
            >
              {SUBWAY_OPTIONS.map((o) => (
                <option key={o.label} value={o.value ?? ""}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

          <div className="cond__row">
            <label className="cond__label" htmlFor="cond-built">
              준공 연도 (이후)
            </label>
            <input
              id="cond-built"
              className="cond__number num"
              type="number"
              inputMode="numeric"
              min={1900}
              max={2100}
              placeholder="상관없음"
              value={prefer.built_after ?? ""}
              onChange={(e) => setPrefer({ ...prefer, built_after: toNullableInt(e.target.value) })}
            />
          </div>

          <div className="cond__row">
            <label className="cond__label" htmlFor="cond-area-min">
              전용면적 (㎡)
            </label>
            <div className="cond__range">
              <input
                id="cond-area-min"
                className="cond__number num"
                type="number"
                inputMode="numeric"
                min={0}
                placeholder="최소"
                value={prefer.area_min_m2 ?? ""}
                onChange={(e) =>
                  setPrefer({ ...prefer, area_min_m2: toNullableInt(e.target.value) })
                }
              />
              <span aria-hidden="true">~</span>
              <input
                className="cond__number num"
                type="number"
                inputMode="numeric"
                min={0}
                placeholder="최대"
                aria-label="전용면적 최대 (㎡)"
                value={prefer.area_max_m2 ?? ""}
                onChange={(e) =>
                  setPrefer({ ...prefer, area_max_m2: toNullableInt(e.target.value) })
                }
              />
            </div>
          </div>

          <div className="cond__row">
            <label className="cond__label" htmlFor="cond-households">
              최소 세대수
            </label>
            <input
              id="cond-households"
              className="cond__number num"
              type="number"
              inputMode="numeric"
              min={0}
              placeholder="상관없음"
              value={prefer.min_households ?? ""}
              onChange={(e) =>
                setPrefer({ ...prefer, min_households: toNullableInt(e.target.value) })
              }
            />
          </div>

          <div className="cond__row">
            <label className="cond__label" htmlFor="cond-school">
              학군 중요도
            </label>
            <div className="cond__range">
              <input
                id="cond-school"
                type="range"
                min={0}
                max={5}
                step={1}
                value={prefer.school_district ?? 0}
                onChange={(e) =>
                  setPrefer({ ...prefer, school_district: Number(e.target.value) })
                }
                aria-describedby="cond-school-value"
              />
              <span id="cond-school-value" className="cond__value num">
                {prefer.school_district ?? 0} / 5
              </span>
            </div>
          </div>
        </section>

        <section className="cond__group" aria-labelledby="cond-avoid">
          <h2 className="cond__group-title" id="cond-avoid">
            기피 (해당하면 추천에서 제외)
          </h2>
          {AVOID_ITEMS.map((item) => (
            <div className="cond__check" key={item.key}>
              <input
                id={`cond-avoid-${item.key}`}
                type="checkbox"
                checked={Boolean(avoid[item.key])}
                onChange={(e) => setAvoid({ ...avoid, [item.key]: e.target.checked })}
              />
              <label htmlFor={`cond-avoid-${item.key}`}>
                <span className="cond__check-label">{item.label}</span>
                <span className="cond__check-hint">{item.hint}</span>
              </label>
            </div>
          ))}
        </section>

        {/* ── 가중치 ────────────────────────────────────────────────────────
            사용자가 "가격·입지·가치·리스크가 무슨 말인지 모르겠다"고 했다. 설명을 붙이되,
            **작동하는 범위를 넘겨 말하지 않는다.** 서버는 이제 가중치를 실제로 반영하지만
            (api-spec §5.3), 근거가 없는 축은 재정규화로 빠지고 partial 축은 일부만 본다.
            그 판단은 전부 lib/preferences · lib/scoreAxes 에서 내린다. */}
        <section className="cond__group" aria-labelledby="cond-weights">
          <h2 className="cond__group-title" id="cond-weights">
            무엇을 더 중요하게 볼까요
          </h2>
          <p className="cond__note">
            추천 순위를 매길 때 어디에 비중을 둘지 정합니다. 합계는 자동으로 맞춰집니다.
            근거가 없는 항목은 순위 계산에서 빠지고, 빠진 사실은 결과에 함께 표시됩니다.
          </p>

          {/* 서버가 아직 가중치를 안 쓰는 배포라면 그것부터 밝힌다(항목마다 반복하지 않는다) */}
          {!weightsApplied() && (
            <p className="cond__warn">
              현재 이 비중은 <strong>저장만 되고 추천 순위 계산에는 아직 반영되지 않습니다.</strong>{" "}
              반영되기 시작하면 이 안내가 사라집니다.
            </p>
          )}

          {WEIGHT_KEYS.map((key) => {
            const meta = WEIGHT_META[key];
            // "지금 근거가 있는가"는 **직전 분석에서 관측한 값**으로 판단한다(하드코딩 금지).
            const status = weightStatus(key, { observedNoSignal: observedNoSignal(key) });
            const note = weightStatusNote(status, key);
            const descId = `cond-w-${key}-desc`;
            const noteId = `cond-w-${key}-note`;
            const gapId = `cond-w-${key}-gap`;
            const describedBy = [descId, meta.coverageGap ? gapId : "", note ? noteId : ""]
              .filter(Boolean)
              .join(" ");

            return (
              <div className="cond__weight" key={key}>
                <div className="cond__weight-head">
                  <label className="cond__label" htmlFor={`cond-w-${key}`}>
                    {WEIGHT_LABELS[key]}
                    <span className="cond__weight-tag">{meta.tagline}</span>
                  </label>
                  {/* 자세한 설명은 눌러서 연다 — hover 툴팁은 폰에서 뜨지 않는다 */}
                  <InfoTip label={WEIGHT_LABELS[key]}>
                    {meta.detail}
                    <span className="cond__weight-agent">
                      점수 근거: {meta.signal} · 담당 {meta.agent}
                    </span>
                  </InfoTip>
                </div>

                {/* 한 줄 요약은 **항상 보인다.** 열어야만 뜻을 알 수 있으면 설명이 아니다. */}
                <p className="cond__weight-sum" id={descId}>
                  {meta.summary}
                </p>

                <div className="cond__range">
                  <input
                    id={`cond-w-${key}`}
                    type="range"
                    min={0}
                    max={100}
                    step={5}
                    value={Math.round((weights[key] ?? 0) * 100)}
                    onChange={(e) =>
                      setWeights({ ...weights, [key]: Number(e.target.value) / 100 })
                    }
                    aria-describedby={describedBy}
                  />
                  <span className="cond__value num">
                    {Math.round((normalized[key] ?? 0) * 100)}%
                  </span>
                </div>

                {/* 부분 커버리지는 **반영 여부와 무관하게** 늘 말한다 —
                    "호가만 들어오면 리스크가 다 반영된다"는 오해를 막는다(api-spec §5.3). */}
                {meta.coverageGap && (
                  <p className="cond__weight-gap" id={gapId}>
                    <span className="badge cond__weight-badge">일부만 반영</span>
                    {meta.coverageGap}
                  </p>
                )}

                {note && (
                  <p className="cond__weight-note" id={noteId}>
                    {note}
                  </p>
                )}
              </div>
            );
          })}
        </section>

        {error && (
          <p className="cond__error" role="alert">
            {error}
          </p>
        )}

        {/* 저장은 엄지 범위(하단 고정). safe-area 는 CSS 에서 처리. */}
        <div className="cond__actions">
          <button type="submit" className="cond__submit" disabled={!canSubmit}>
            {busy ? "저장 중…" : profile ? "저장하고 다시 계산" : "저장하고 시작"}
          </button>
          {onClose && (
            <button type="button" className="cond__cancel" onClick={onClose} disabled={busy}>
              취소
            </button>
          )}
        </div>
      </form>
    </main>
  );
}
