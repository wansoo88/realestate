/**
 * 지도 범례 — **추정 고지를 모아 두는 한 곳**.
 *
 * 왜 이게 필요해졌나: 예전에는 마커마다 "추정 8.4억"이라고 적었다. 그런데 이 API 의 가격은
 * 전부 추정치라(서버에 `confirmed` 등급이 없다) 모든 마커에 같은 단어가 붙었고, 결국
 * 지도는 '추정'이라는 글자로 덮였다. 모든 것에 붙는 표시는 구분이 아니다.
 *
 * 그래서 **마커에서 글자를 빼고 고지를 여기로 옮겼다.** 다만 규칙은 그대로다 —
 * "추정임을 어딘가에서는 반드시 알 수 있어야 한다". 그래서 요약 줄(`지도 가격은 추정치`)은
 * 접힌 상태에서도 **항상 화면에 보인다.** 접히는 건 마커 색의 의미 같은 부가 설명뿐이다.
 */
import { useState } from "react";
import { NOTICE_TRADE_DELAY } from "../lib/notices";
import "./MapLegend.css";

export function MapLegend() {
  const [open, setOpen] = useState(false);

  return (
    <div className={`legend${open ? " legend--open" : ""}`}>
      <button
        type="button"
        className="legend__toggle"
        aria-expanded={open}
        aria-controls="map-legend-body"
        onClick={() => setOpen((v) => !v)}
      >
        {/* 이 한 줄은 접혀 있어도 보인다 — 고지가 클릭 뒤에 숨으면 고지가 아니다. */}
        <span className="legend__lede">지도 가격은 추정치</span>
        <span className="legend__more">{open ? "닫기" : "표시 안내"}</span>
      </button>

      {open && (
        <div className="legend__body" id="map-legend-body">
          <p className="legend__note">
            지도에 뜨는 값은 최근 <strong>실거래 기반 추정치</strong>이며 확정 시세가 아닙니다.
            현재 나와 있는 호가가 아닙니다.
          </p>

          <ul className="legend__list">
            <li className="legend__row">
              <span className="legend__swatch legend__swatch--price" aria-hidden="true">
                8.4억
              </span>
              <span className="legend__desc">추정 시세</span>
            </li>
            <li className="legend__row">
              <span className="legend__swatch legend__swatch--over" aria-hidden="true">
                8.4억
              </span>
              <span className="legend__desc">내 예산 초과 — 지우지 않고 흐리게 둡니다</span>
            </li>
            <li className="legend__row">
              <span className="legend__swatch legend__swatch--rank" aria-hidden="true">
                8.4억
              </span>
              <span className="legend__desc">AI 추천 후보 (근거 리포트 있음)</span>
            </li>
            <li className="legend__row">
              <span className="legend__swatch legend__swatch--dot" aria-hidden="true" />
              <span className="legend__desc">
                시세 데이터 없음, 또는 <strong>밀집 구간이라 가격을 줄인 상태</strong> — 확대하거나
                목록에서 값을 볼 수 있습니다
              </span>
            </li>
          </ul>

          <p className="legend__note legend__note--weak">{NOTICE_TRADE_DELAY}</p>
        </div>
      )}
    </div>
  );
}
