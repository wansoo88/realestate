/**
 * 금액 입력 (components.md §3.5) — G3 대상 필드.
 *
 * 화면은 **만원**, 전송은 **원 단위 정수**(api-spec §0). 변환은 `lib/money.ts` 순수 함수가 한다.
 * 입력한 금액을 바로 아래에 "3억"처럼 되읽어 준다 — 0 하나 더 친 걸 그 자리에서 알아채야 한다.
 *
 * ⛔ 이 컴포넌트는 값을 **로그·저장소·URL 어디에도 쓰지 않는다.** 개인 금융정보다.
 *    `autoComplete="off"` 인 이유도 같다(공용 기기에서 자동완성으로 남지 않게).
 */
import { useEffect, useRef } from "react";
import { formatKrw } from "../lib/format";
import {
  caretForDigitCount,
  countDigitsBefore,
  groupDigits,
  krwToManwonDigits,
  manwonDigitsToKrw,
  normalizeDigits,
} from "../lib/money";
import "./MoneyField.css";

interface Props {
  id: string;
  label: string;
  valueKrw: number | null;
  onChange: (krw: number | null) => void;
  hint?: string;
  error?: string;
  required?: boolean;
}

export function MoneyField({ id, label, valueKrw, onChange, hint, error, required }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  /** 콤마 삽입 후 커서가 튀지 않게, 다음 렌더에서 되돌릴 위치. */
  const caretRef = useRef<number | null>(null);

  useEffect(() => {
    if (caretRef.current !== null && inputRef.current) {
      inputRef.current.setSelectionRange(caretRef.current, caretRef.current);
      caretRef.current = null;
    }
  });

  const display = groupDigits(krwToManwonDigits(valueKrw));
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId, `${id}-readback`].filter(Boolean).join(" ");

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const el = e.target;
    const digitsBefore = countDigitsBefore(el.value, el.selectionStart ?? el.value.length);
    const digits = normalizeDigits(el.value);
    caretRef.current = caretForDigitCount(groupDigits(digits), digitsBefore);
    onChange(manwonDigitsToKrw(digits));
  }

  return (
    <div className="money">
      <label className="money__label" htmlFor={id}>
        {label}
      </label>
      <div className="money__row">
        <input
          ref={inputRef}
          id={id}
          className="money__input num"
          // 숫자 키패드를 띄우되 type=number 는 쓰지 않는다(콤마를 못 넣고 스피너가 생긴다).
          inputMode="numeric"
          type="text"
          autoComplete="off"
          enterKeyHint="next"
          placeholder="0"
          value={display}
          onChange={handleChange}
          aria-describedby={describedBy || undefined}
          aria-invalid={Boolean(error)}
          required={required}
        />
        <span className="money__unit" aria-hidden="true">
          만원
        </span>
        <span className="sr-only">단위: 만원</span>
      </div>

      {/* 되읽기 — "30,000만원"이 3억이라는 걸 그 자리에서 확인시킨다. */}
      <p id={`${id}-readback`} className="money__readback">
        {valueKrw === null ? "미입력" : formatKrw(valueKrw)}
      </p>

      {hint && (
        <p id={hintId} className="money__hint">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="money__error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
