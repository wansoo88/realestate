/**
 * 장소·역 검색 상자 — **지도를 그 자리로 옮긴다.**
 *
 * 사용자 요청: "역으로 검색하게 해줘". 여기서 하는 일과 하지 않는 일을 분명히 나눈다.
 *   하는 일   : '강남역'을 찾아 **지도를 이동**한다. 그러면 그 주변 단지가 조회된다.
 *   안 하는 일: 역 반경으로 추천 후보를 제한하지 않는다. 그건 서버(PostGIS)가 해야 하고
 *               아직 없다. 우리 `poi` 테이블도 0행이라 **역세권 분석은 존재하지 않는다.**
 *               그래서 이 상자는 "역세권 필터"처럼 보이지 않게 문구를 고른다.
 *
 * 접근성: 결과는 목록 + 버튼이다. 키보드로 탭해서 고를 수 있고, 상태는 `role="status"` 로 알린다.
 * (콤보박스 aria 패턴은 직접 구현하면 대개 더 나쁘다 — 단순한 목록으로 둔다.)
 */
import { useCallback, useRef, useState } from "react";
import { placeErrorText, searchPlaces, type Place, type PlaceSearchError } from "../lib/placeSearch";
import "./PlaceSearch.css";

interface Props {
  /** 고른 장소로 지도를 옮긴다. [경도, 위도]. */
  onPick: (place: Place) => void;
}

export function PlaceSearch({ onPick }: Props) {
  const [keyword, setKeyword] = useState("");
  const [places, setPlaces] = useState<Place[]>([]);
  const [error, setError] = useState<PlaceSearchError | null>(null);
  const [busy, setBusy] = useState(false);
  /** 늦게 온 응답이 최신 검색을 덮지 않게(빠르게 두 번 검색하면 순서가 뒤집힌다). */
  const reqId = useRef(0);

  const run = useCallback(async (q: string) => {
    const id = (reqId.current += 1);
    setBusy(true);
    const res = await searchPlaces(q);
    if (id !== reqId.current) return;
    setBusy(false);
    setPlaces(res.places);
    setError(res.error);
  }, []);

  return (
    <div className="psearch">
      <form
        className="psearch__form"
        onSubmit={(e) => {
          e.preventDefault();
          void run(keyword);
        }}
        role="search"
      >
        <label className="psearch__label" htmlFor="psearch-input">
          장소·역 검색
        </label>
        <input
          id="psearch-input"
          className="psearch__input"
          type="search"
          // 무엇을 하는 상자인지 문구에서 드러낸다 — 필터가 아니라 이동이다
          placeholder="예: 강남역, 평촌 (지도 이동)"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          aria-describedby="psearch-hint"
        />
        <button type="submit" className="psearch__btn" disabled={busy || keyword.trim() === ""}>
          {busy ? "찾는 중…" : "찾기"}
        </button>
      </form>

      <p id="psearch-hint" className="psearch__hint">
        검색한 위치로 지도를 옮깁니다. 추천 지역은 <strong>분석 지역</strong>에서 따로 고릅니다.
      </p>

      {error && (
        <p className="psearch__error" role="status">
          {placeErrorText(error)}
        </p>
      )}

      {places.length > 0 && (
        <ul className="psearch__list" aria-label="검색 결과">
          {places.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                className="psearch__item"
                onClick={() => {
                  onPick(p);
                  setPlaces([]); // 고르면 목록을 닫는다(지도가 가려지지 않게)
                }}
              >
                <span className="psearch__name">{p.name}</span>
                {p.detail && <span className="psearch__detail">{p.detail}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
