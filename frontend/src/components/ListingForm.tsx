/**
 * 호가 입력 폼 (신규 등록 · 수정 공용).
 *
 * 이 폼이 다루는 값은 **사람이 네이버 부동산 화면을 보고 옮겨 적는 숫자**다.
 * 공공 API 에는 호가가 없고 포털 자동수집은 약관·판례상 하지 않기로 했으므로, 이게
 * 가격 축(가중치 31%)에 값이 들어오는 유일한 경로다. 그래서 두 가지를 특히 조심한다.
 *
 *  ① **확인 날짜에 기본값을 넣지 않는다.** 오늘로 미리 채우면 3주 전에 캡처해 둔 호가가
 *     오늘 값이 되고, 그 순간 낡음 판정(30/90일)이 통째로 거짓이 된다. 한 번 더 묻는 편이 낫다.
 *  ② **가격을 바꾸면 날짜를 다시 묻는다.** 서버도 같은 규칙을 422 로 걸지만(가격만 보내면
 *     거절), 화면이 먼저 물어야 사용자가 "왜 또 날짜냐"를 이해한다.
 *
 * 한 손 조작: 세로 한 줄 배치 · 44px 이상 터치 타깃 · 제출 버튼은 **맨 아래 고정**(엄지 범위).
 * 숫자 입력은 `inputMode="numeric"` 으로 숫자 키패드를 띄운다.
 */
import { useEffect, useMemo, useState } from "react";
import type { UserListing } from "../api/client";
import { formatKrw } from "../lib/format";
import {
  EMPTY_FORM,
  LISTING_MAX_DONG_LEN,
  LISTING_MAX_NOTE_LEN,
  formFromListing,
  hasErrors,
  todayIso,
  validateForm,
  type ListingErrors,
  type ListingFormValues,
} from "../lib/userListings";
import { MoneyField } from "./MoneyField";
import "./ListingForm.css";

interface Props {
  /** 어느 단지의 호가인가. 단지를 모르면 이 폼은 열리지 않는다(단지 없는 호가는 쓸 데가 없다). */
  complexName: string;
  /** 수정 대상. 없으면 신규 등록. */
  editing?: UserListing | null;
  busy?: boolean;
  /** 서버가 특정 입력을 지목한 오류(pydantic `loc` → 메시지). */
  serverFieldErrors?: ListingErrors;
  onSubmit: (values: ListingFormValues) => void;
  onCancel?: () => void;
}

export function ListingForm({
  complexName,
  editing = null,
  busy = false,
  serverFieldErrors,
  onSubmit,
  onCancel,
}: Props) {
  const initial = useMemo(
    () => (editing ? formFromListing(editing) : EMPTY_FORM),
    [editing],
  );
  const [values, setValues] = useState<ListingFormValues>(initial);
  /** 제출을 눌렀는가 — 누르기 전에는 빨간 글씨를 뿌리지 않는다(입력 중 방해 금지). */
  const [submitted, setSubmitted] = useState(false);
  /**
   * 수정 중 **가격을 건드렸는가**. 건드렸으면 날짜를 다시 받는다 —
   * 그러지 않으면 석 달 전 날짜에 오늘 가격이 붙는다(모듈 상단 규칙 ②).
   */
  const [priceChanged, setPriceChanged] = useState(false);

  useEffect(() => {
    setValues(initial);
    setSubmitted(false);
    setPriceChanged(false);
  }, [initial]);

  const today = todayIso();
  const errors = validateForm(values, { today });
  const shown: ListingErrors = submitted ? { ...errors, ...serverFieldErrors } : { ...serverFieldErrors };

  function set<K extends keyof ListingFormValues>(key: K, value: ListingFormValues[K]) {
    setValues((v) => ({ ...v, [key]: value }));
  }

  function onPriceChange(krw: number | null) {
    // 수정 중 가격이 원래 값과 달라지면 **날짜를 비운다.** 값을 유지한 채 저장하게 두면
    // "언제 본 값인지"가 조용히 거짓이 된다.
    if (editing && krw !== editing.ask_price_krw) {
      setPriceChanged(true);
      setValues((v) => ({ ...v, askPriceKrw: krw, asOf: "" }));
      return;
    }
    if (editing && krw === editing.ask_price_krw && priceChanged) {
      setPriceChanged(false);
      setValues((v) => ({ ...v, askPriceKrw: krw, asOf: editing.as_of }));
      return;
    }
    set("askPriceKrw", krw);
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    if (hasErrors(errors)) return;
    onSubmit(values);
  }

  const title = editing ? "호가 수정" : "이 단지에서 본 호가 적기";

  return (
    <form className="lform" onSubmit={submit} noValidate aria-label={title}>
      <h3 className="lform__title">{title}</h3>
      <p className="lform__complex">
        <span className="lform__complex-name">{complexName}</span>
        {/* 이 값이 무엇인지 한 줄로 못박는다 — 실거래가가 아니라 '내가 본 호가'다 */}
        <span className="lform__complex-what">
          네이버 부동산·중개사 등에서 <strong>직접 보신 매도 희망가</strong>를 적습니다.
          실거래가가 아닙니다.
        </span>
      </p>

      <MoneyField
        id="lf-price"
        label="호가"
        valueKrw={values.askPriceKrw}
        onChange={onPriceChange}
        hint="매물에 적힌 금액 그대로"
        error={shown.askPriceKrw}
        required
      />

      <div className="lform__row">
        <label className="lform__label" htmlFor="lf-area">
          전용면적 (㎡)
        </label>
        <input
          id="lf-area"
          className="lform__input num"
          type="text"
          inputMode="decimal"
          autoComplete="off"
          placeholder="84.97"
          value={values.areaM2}
          onChange={(e) => set("areaM2", e.target.value)}
          aria-describedby="lf-area-hint"
          aria-invalid={Boolean(shown.areaM2)}
          required
        />
        <p id="lf-area-hint" className="lform__hint">
          공급면적이 아니라 <strong>전용면적</strong>입니다(84.97㎡ = 34평형).
        </p>
        {shown.areaM2 && (
          <p className="lform__error" role="alert">
            {shown.areaM2}
          </p>
        )}
      </div>

      <div className="lform__row lform__row--split">
        <div className="lform__col">
          <label className="lform__label" htmlFor="lf-floor">
            층 <span className="lform__opt">(선택)</span>
          </label>
          <input
            id="lf-floor"
            className="lform__input num"
            type="text"
            inputMode="numeric"
            autoComplete="off"
            placeholder="모르면 비워 두세요"
            value={values.floor}
            onChange={(e) => set("floor", e.target.value)}
            aria-invalid={Boolean(shown.floor)}
          />
          {shown.floor && (
            <p className="lform__error" role="alert">
              {shown.floor}
            </p>
          )}
        </div>
        <div className="lform__col">
          <label className="lform__label" htmlFor="lf-dong">
            동 <span className="lform__opt">(선택)</span>
          </label>
          <input
            id="lf-dong"
            className="lform__input"
            type="text"
            autoComplete="off"
            maxLength={LISTING_MAX_DONG_LEN}
            placeholder="101동"
            value={values.aptDong}
            onChange={(e) => set("aptDong", e.target.value)}
            aria-invalid={Boolean(shown.aptDong)}
          />
          {shown.aptDong && (
            <p className="lform__error" role="alert">
              {shown.aptDong}
            </p>
          )}
        </div>
      </div>

      {/* ── 확인 날짜 — 이 폼에서 가장 중요한 칸 ───────────────────────────
          값이 아니라 **값의 시점**이 없으면 이 데이터는 계산에 못 들어간다. */}
      <div className="lform__row">
        <label className="lform__label" htmlFor="lf-asof">
          이 호가를 확인한 날짜
        </label>
        <input
          id="lf-asof"
          className="lform__input num"
          type="date"
          max={today}
          // ⚠️ value 는 사용자가 고른 값뿐이다. 오늘 날짜를 기본값으로 넣지 않는다.
          value={values.asOf}
          onChange={(e) => set("asOf", e.target.value)}
          aria-describedby="lf-asof-hint"
          aria-invalid={Boolean(shown.asOf)}
          required
        />
        <p id="lf-asof-hint" className="lform__hint">
          {priceChanged
            ? "가격을 바꾸셨습니다 — 그 가격을 확인한 날짜를 다시 골라 주세요. 가격만 갱신하면 옛 날짜에 새 가격이 붙습니다."
            : "오늘 날짜를 미리 채우지 않습니다. 며칠 전에 본 값이면 그날을 고르세요 — 30일이 지나면 '오래된 호가'로, 90일이 지나면 추천 계산에서 빠집니다."}
        </p>
        {shown.asOf && (
          <p className="lform__error" role="alert">
            {shown.asOf}
          </p>
        )}
      </div>

      <div className="lform__row">
        <label className="lform__label" htmlFor="lf-note">
          메모 <span className="lform__opt">(선택)</span>
        </label>
        <input
          id="lf-note"
          className="lform__input"
          type="text"
          autoComplete="off"
          maxLength={LISTING_MAX_NOTE_LEN}
          placeholder="예: 네이버 부동산 · ○○공인 · 즉시 입주"
          value={values.note}
          onChange={(e) => set("note", e.target.value)}
          aria-invalid={Boolean(shown.note)}
        />
        {shown.note && (
          <p className="lform__error" role="alert">
            {shown.note}
          </p>
        )}
      </div>

      {/* 되읽기 — 단위 실수(0 하나)를 저장 전에 스스로 잡게 한다 */}
      {values.askPriceKrw !== null && values.areaM2.trim() !== "" && (
        <p className="lform__readback">
          {formatKrw(values.askPriceKrw)} · {values.areaM2}㎡
        </p>
      )}

      <div className="lform__actions">
        <button type="submit" className="lform__submit" disabled={busy}>
          {busy ? "저장 중…" : editing ? "수정 저장" : "호가 추가"}
        </button>
        {onCancel && (
          <button type="button" className="lform__cancel" onClick={onCancel} disabled={busy}>
            취소
          </button>
        )}
      </div>
    </form>
  );
}
