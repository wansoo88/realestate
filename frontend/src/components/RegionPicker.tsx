/**
 * 분석 지역 선택 — **AI 추천을 어디에서 찾을지**.
 *
 * 왜 필요한가 (확인한 동작)
 * -------------------------
 * 서버 `POST /recommendations` 는 `region_codes` 를 받아 후보 조회를 그 지역으로 좁힌다.
 * 그런데 화면이 이 값을 **한 번도 보낸 적이 없어서**, 지금까지는 수도권 전체(단지 1.6만 개)에서
 * 조회 상한(50개)만 보고 그중 10건을 추천했다. 사용자가 "평촌·분당을 보고 싶다"고 해도
 * 지정할 방법이 없었고, 그래서 추천이 엉뚱하게 느껴졌다.
 *
 * 정직성 규칙 두 가지
 *  ① 아무것도 안 고르면 **전체**다. 그 사실과 **조회 상한**을 화면에 적는다 —
 *     "왜 우리 동네가 안 나오지?"의 답이 여기 있다.
 *  ② 이 목록은 **행정구역 목록**이지 "데이터가 있는 지역" 목록이 아니다(lib/regions 주석).
 *     고른 지역에 아직 수집된 실거래가 없으면 결과가 빌 수 있다 — 그 가능성을 미리 말한다.
 *
 * ⚠️ 이 선택은 **지도 필터가 아니다.** 지도는 화면 범위(bbox)로 조회되므로 지역을 골라도
 *    지도 마커는 그대로다. 그래서 지도 조건 칩(FilterRail)이 아니라 추천 패널 안에 둔다 —
 *    같은 자리에 두면 "지도도 걸러진다"는 거짓 인상을 준다.
 */
import { useMemo, useState } from "react";
import {
  REGIONS,
  REGIONS_AS_OF,
  SIDO_ORDER,
  regionByCode,
  regionLabel,
  searchRegions,
  type Region,
} from "../lib/regions";
import "./RegionPicker.css";

interface Props {
  /** 선택된 5자리 시군구 코드들. 빈 배열 = 전체. */
  value: string[];
  onChange: (codes: string[]) => void;
  /** 분석 후보 조회 상한(서버 기본값). "전체에서 찾는다"는 말이 오해되지 않게 함께 적는다. */
  candidateLimit?: number;
  /**
   * "이 주변"(지도 범위)이 함께 걸려 있는가.
   * ⚠️ 켜져 있는데 이 값을 안 받으면 아래 문구가 **"수도권 전체에서 찾습니다"라고 거짓말**을 한다.
   */
  areaScoped?: boolean;
  disabled?: boolean;
}

export function RegionPicker({
  value,
  onChange,
  candidateLimit = 50,
  areaScoped = false,
  disabled,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [sido, setSido] = useState<Region["sido"] | "전체">("전체");

  const shown = useMemo(() => {
    const base = sido === "전체" ? REGIONS : REGIONS.filter((r) => r.sido === sido);
    return searchRegions(query, base);
  }, [query, sido]);

  const selected = value.map(regionByCode).filter((r): r is Region => r !== undefined);

  const toggle = (code: string) => {
    onChange(value.includes(code) ? value.filter((c) => c !== code) : [...value, code]);
  };

  return (
    <section className="regions" aria-labelledby="regions-title">
      <div className="regions__head">
        <h3 className="regions__title" id="regions-title">
          분석 지역
        </h3>
        <button
          type="button"
          className="regions__toggle"
          aria-expanded={open}
          aria-controls="regions-body"
          onClick={() => setOpen((v) => !v)}
          disabled={disabled}
        >
          {open ? "닫기" : value.length > 0 ? "지역 변경" : "지역 선택"}
        </button>
      </div>

      {/* 지금 무엇으로 찾는지 — 선택이 없을 때도 **반드시** 말한다 */}
      {value.length === 0 ? (
        <p className="regions__scope">
          {areaScoped
            ? `시군구는 고르지 않았습니다 — 지금은 "이 주변"(지도 범위)으로만 찾습니다. 시군구를 고르면 두 조건을 모두 만족하는 단지만 남습니다(교집합).`
            : `수도권 전체에서 찾습니다. 후보는 조건에 맞는 단지 중 최대 ${candidateLimit}개까지만 분석하므로, 지역을 좁히면 원하는 동네가 후보에 들어갈 가능성이 높아집니다.`}
        </p>
      ) : (
        <ul className="regions__chips" aria-label="선택한 지역">
          {selected.map((r) => (
            <li key={r.code}>
              <button
                type="button"
                className="regions__chip"
                onClick={() => toggle(r.code)}
                disabled={disabled}
              >
                {regionLabel(r)}
                <span className="regions__chip-x" aria-hidden="true">
                  ×
                </span>
                <span className="sr-only">빼기</span>
              </button>
            </li>
          ))}
          <li>
            <button
              type="button"
              className="regions__clear"
              onClick={() => onChange([])}
              disabled={disabled}
            >
              모두 지우기
            </button>
          </li>
        </ul>
      )}

      {open && (
        <div className="regions__body" id="regions-body">
          <label className="regions__search">
            <span className="sr-only">시군구 검색</span>
            <input
              type="search"
              className="regions__search-input"
              placeholder="시군구 검색 (예: 분당, 강남)"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              disabled={disabled}
            />
          </label>

          <div className="regions__sido" role="group" aria-label="시도 선택">
            {(["전체", ...SIDO_ORDER] as const).map((s) => (
              <button
                key={s}
                type="button"
                className={`regions__sidobtn${sido === s ? " regions__sidobtn--on" : ""}`}
                aria-pressed={sido === s}
                onClick={() => setSido(s)}
                disabled={disabled}
              >
                {s}
              </button>
            ))}
          </div>

          {/* 체크박스 = 멀티 선택. 네이티브 입력이라 키보드·스크린리더가 공짜로 따라온다. */}
          <fieldset className="regions__list">
            <legend className="sr-only">분석할 시군구 (여러 개 선택 가능)</legend>
            {shown.length === 0 && <p className="regions__empty">검색 결과가 없습니다.</p>}
            {shown.map((r) => (
              <label key={r.code} className="regions__item">
                <input
                  type="checkbox"
                  checked={value.includes(r.code)}
                  onChange={() => toggle(r.code)}
                  disabled={disabled}
                />
                <span className="regions__item-name">{regionLabel(r)}</span>
              </label>
            ))}
          </fieldset>

          {/* 이 목록의 한계 — 숨기면 "고른 지역인데 왜 결과가 없지"가 된다 */}
          <p className="regions__note">
            {REGIONS_AS_OF} 기준 행정구역 목록입니다. 아직 실거래를 수집하지 못한 지역을 고르면
            후보가 없을 수 있습니다.
          </p>
        </div>
      )}
    </section>
  );
}
