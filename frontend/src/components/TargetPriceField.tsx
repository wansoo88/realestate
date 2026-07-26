/**
 * 희망 매매가 — **"얼마까지 살 수 있나"에서 "이걸 사려면 뭐가 필요한가"로 질문을 바꾸는 입력**.
 *
 * 왜 슬라이더 + 직접 입력을 **둘 다** 두는가
 * -----------------------------------------
 * 슬라이더 한 칸은 500만원이고 범위는 십수억이다. 폰에서 엄지로 9억 정확히 맞추기는 어렵다
 * (한 칸이 손가락보다 좁다). 그래서 대략 잡는 건 슬라이더, 확정은 숫자 입력이 맡는다.
 * 반대로 숫자만 두면 "내 한도 대비 어디쯤인가"라는 감각이 사라진다 — 그건 슬라이더가 준다.
 *
 * 한도를 **넘겨서도 고를 수 있다**(범위 상한 = 한도 × 1.5, 직접 입력은 그 위도 가능).
 * 못 사는 가격을 막아 버리면 "얼마를 더 모아야 하는가"라는 질문 자체가 화면에서 사라진다 —
 * 이 기능이 답하려는 바로 그 질문이다.
 *
 * 🔐 금액은 개인 금융정보에 준해 다룬다(로그·저장소·URL 금지, `autoComplete="off"`).
 */
import { formatKrw, formatKrwShort } from "../lib/format";
import {
  clampToRange,
  normalizeTargetPrice,
  targetPriceRange,
  type TargetPriceRange,
} from "../lib/affordability";
import { MoneyField } from "./MoneyField";
import "./TargetPriceField.css";

interface Props {
  id: string;
  /** 현재 값(원). null = 아직 정하지 않음 — **0 과 다르다**. */
  valueKrw: number | null;
  onChange: (krw: number | null) => void;
  /** 최대 실구매 가능 금액. 범위·눈금의 기준이자 "여기까지가 내 한도" 표시의 근거. */
  maxPurchaseKrw: number | null;
}

/** 한도 대비 어디에 있는지 한 문장으로. 한도를 모르면 아는 척하지 않는다. */
function limitSentence(krw: number | null, range: TargetPriceRange): string | null {
  if (krw === null) return null;
  if (range.limitKrw === null) {
    return "최대 실구매 가능 금액이 아직 계산되지 않아 한도와 비교할 수 없습니다.";
  }
  const gap = krw - range.limitKrw;
  if (gap > 0) {
    return `최대 실구매 가능 금액 ${formatKrwShort(range.limitKrw)}보다 ${formatKrwShort(
      gap,
    )} 높습니다 — 부족분은 아래 '내 자금'에서 계산합니다.`;
  }
  return `최대 실구매 가능 금액 ${formatKrwShort(range.limitKrw)} 안입니다 (여유 ${formatKrwShort(
    -gap,
  )}).`;
}

export function TargetPriceField({ id, valueKrw, onChange, maxPurchaseKrw }: Props) {
  const range = targetPriceRange(maxPurchaseKrw);
  // 값이 없을 때 슬라이더가 가리킬 자리. 한도가 있으면 한도, 없으면 범위 중간.
  const sliderValue =
    valueKrw !== null
      ? clampToRange(valueKrw, range)
      : clampToRange(range.limitKrw ?? (range.min + range.max) / 2, range);

  const noteId = `${id}-note`;
  const stateId = `${id}-state`;
  const overLimit = range.limitKrw !== null && valueKrw !== null && valueKrw > range.limitKrw;
  const beyondSlider = valueKrw !== null && valueKrw > range.max;

  return (
    <div className="target">
      <div className="target__head">
        <label className="target__label" htmlFor={id}>
          희망 매매가
        </label>
        {/* 되읽기가 주인공이다(규칙 2: 숫자가 가장 크다) */}
        <output className="target__value num" htmlFor={id} aria-live="off">
          {valueKrw === null ? "정하지 않음" : formatKrw(valueKrw)}
        </output>
      </div>

      <p className="target__note" id={noteId}>
        정한 값이 지도 필터 · AI 추천 예산 · 자금계획에 함께 쓰입니다. 한도를 넘겨도 고를 수
        있습니다 — 얼마가 더 필요한지 보여드립니다.
      </p>

      <div className="target__slider">
        <input
          id={id}
          type="range"
          min={range.min}
          max={range.max}
          step={range.step}
          value={sliderValue}
          // 스크린리더는 "500000000" 을 읽으면 자릿수를 셀 수 없다 → 사람 말로 바꿔 준다.
          aria-valuetext={formatKrw(sliderValue)}
          aria-describedby={`${noteId} ${stateId}`}
          onChange={(e) => onChange(clampToRange(Number(e.target.value), range))}
        />
        <div className="target__scale" aria-hidden="true">
          <span className="num">{formatKrwShort(range.min)}</span>
          {range.limitKrw !== null && (
            <span className="target__limit num">내 한도 {formatKrwShort(range.limitKrw)}</span>
          )}
          <span className="num">{formatKrwShort(range.max)}</span>
        </div>
      </div>

      {/* 억 단위 미세조정 — 슬라이더로는 안 되는 자리. 만원 단위 입력은 MoneyField 규약 그대로. */}
      <MoneyField
        id={`${id}-exact`}
        label="희망 매매가 직접 입력"
        valueKrw={valueKrw}
        onChange={(krw) => onChange(normalizeTargetPrice(krw))}
        hint="슬라이더로 맞추기 어려운 금액은 여기에 적으세요 (만원 단위)"
      />

      <p className={`target__state${overLimit ? " target__state--over" : ""}`} id={stateId}>
        {limitSentence(valueKrw, range) ??
          "정하지 않으면 최대 실구매 가능 금액을 예산으로 씁니다."}
      </p>

      {beyondSlider && (
        <p className="target__state target__state--weak">
          슬라이더 범위({formatKrwShort(range.max)})를 넘는 금액이라 슬라이더는 끝에
          머무릅니다 — 저장되는 값은 입력한 {formatKrw(valueKrw)}입니다.
        </p>
      )}

      {valueKrw !== null && (
        <button type="button" className="target__clear" onClick={() => onChange(null)}>
          희망가 지우기
        </button>
      )}
    </div>
  );
}
