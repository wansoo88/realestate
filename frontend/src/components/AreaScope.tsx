/**
 * "이 주변에서 찾기" — **지도에서 보고 있는 그 자리**를 추천 범위로 잡는다.
 *
 * 왜 필요한가
 * -----------
 * 지금까지 범위를 정하는 길은 시군구 선택(RegionPicker)뿐이었다. 그런데 사용자는
 * 지도를 움직여 평촌을 보고 있을 때 "여기서 찾아줘"라고 말하고 싶어 한다 —
 * 그게 시군구 코드로 뭔지는 몰라도 된다.
 *
 * 캡처 시점 — **누른 순간을 고정한다** (② 실행 시점 캡처를 쓰지 않은 이유)
 * ---------------------------------------------------------------------
 * 실행 시점에 범위를 읽으면 칩이 "이 주변"이라고 떠 있는 동안 그 뜻이 지도를 끌 때마다
 * **말없이** 바뀐다. 사용자가 후보를 둘러보려고 지도를 움직인 것뿐인데 검색 범위가 따라
 * 움직이고, 그 사실은 결과가 나온 뒤에야 드러난다. 이 앱의 규칙은 그 반대다 —
 * 조용히 바뀌는 조건은 거짓말이다(mapFilters.ts 주석).
 *
 * 그래서 누른 순간의 범위를 **얼려 두고**, 지도가 그 범위를 벗어나면
 * "지도를 옮겼습니다 · 지금 지도로 다시 잡기"를 띄운다. 낡음을 감추지 않고 **보여주고 고치게** 한다.
 * (결과가 나온 뒤 "그때 그 범위"는 RecommendPanel 이 실행 당시 범위를 따로 적어 둔다)
 *
 * ⚠️ 이 선택은 **지도 필터가 아니다.** RegionPicker 와 같은 이유로, 범위를 잡아도
 *    지도 마커는 그대로다. 문구가 그렇게 말한다("지도 표시는 그대로입니다").
 */
import { bboxSizeText, bboxTooLarge, bboxTooLargeReason, sameBbox } from "../lib/bbox";
import { intersectionNote, scopeText } from "../lib/searchScope";
import "./AreaScope.css";

interface Props {
  /** 지도가 지금 보고 있는 범위. **null = 지도가 아직 준비되지 않음**(버튼을 못 누른다). */
  currentBbox: string | null;
  /** 잡아 둔 범위. null = 이 주변을 쓰지 않는 중. */
  bbox: string | null;
  onCapture: (bbox: string) => void;
  onClear: () => void;
  /** 함께 걸린 시군구 — 교집합이라는 사실을 문장으로 말하기 위해 받는다. */
  regionCodes: string[];
  /** 분석 중에는 범위를 바꿀 수 없다. */
  disabled?: boolean;
}

const WHY_ID = "areascope-why";

export function AreaScope({
  currentBbox,
  bbox,
  onCapture,
  onClear,
  regionCodes,
  disabled = false,
}: Props) {
  const mapReady = currentBbox !== null;
  /** 잡아 둔 범위가 지금 지도와 다른가 = 낡았는가. */
  const stale = bbox !== null && mapReady && !sameBbox(bbox, currentBbox);

  /**
   * 지금 지도가 서버 상한(한 변 2도)을 넘는가.
   *
   * 줌아웃 상태에서 그냥 잡게 두면 서버가 422 를 주고, 화면에는 "분석에 필요한 조건이
   * 부족합니다"만 뜬다 — 무엇이 잘못됐는지 알 수 없는 실패다. **누르기 전에** 막고
   * 사유를 적는다. (상한값은 서버가 정본이라 넘어가도 실패 메시지로 한 번 더 번역한다 —
   * lib/bbox.ts MAX_BBOX_SIDE_DEG 주석)
   */
  const tooWide = mapReady && bboxTooLarge(currentBbox);

  // 못 누르는 버튼에는 **이유를 붙인다**. 조용히 죽은 버튼은 고장으로 보인다.
  const why = disabled
    ? "분석 중에는 범위를 바꿀 수 없습니다."
    : !mapReady
      ? "지도가 아직 준비되지 않았습니다 — 지도가 보이면 그 범위로 찾을 수 있습니다."
      : tooWide
        ? bboxTooLargeReason(currentBbox)
        : null;

  const capture = () => {
    // 상한을 넘는 범위는 잡지 않는다 — 잡히면 실행 버튼까지 가서야 실패한다.
    if (currentBbox && !bboxTooLarge(currentBbox)) onCapture(currentBbox);
  };

  return (
    <section className="scope" aria-labelledby="scope-title">
      <div className="scope__head">
        <h3 className="scope__title" id="scope-title">
          이 주변
        </h3>

        {/* 잡기 전 · 낡았을 때만 버튼을 둔다. 이미 최신이면 누를 일이 없다. */}
        {(bbox === null || stale) && (
          <button
            type="button"
            className="scope__catch"
            onClick={capture}
            disabled={disabled || !mapReady || tooWide}
            aria-describedby={why ? WHY_ID : undefined}
          >
            {stale ? "지금 지도로 다시 잡기" : "이 주변에서 찾기"}
          </button>
        )}
      </div>

      {why && (
        <p className="scope__why" id={WHY_ID}>
          {why}
        </p>
      )}

      {bbox === null ? (
        <p className="scope__hint">
          지도에서 보고 있는 범위로 추천을 좁힙니다. 지도 표시는 그대로이고, 분석 범위만
          바뀝니다.
        </p>
      ) : (
        <>
          <ul className="scope__chips" aria-label="적용된 범위">
            <li>
              {/* 칩 전체가 해제 버튼 — RegionPicker 칩과 같은 문법이다. */}
              <button
                type="button"
                className={`scope__chip${stale ? " scope__chip--stale" : ""}`}
                onClick={onClear}
                disabled={disabled}
              >
                {stale ? "이 주변 · 잡아 둔 지도 범위" : "이 주변 · 지금 지도 범위"}
                <span className="scope__chip-x" aria-hidden="true">
                  ×
                </span>
                <span className="sr-only">해제</span>
              </button>
            </li>
          </ul>

          {stale && (
            <p className="scope__stale" role="status">
              지도를 옮겼습니다 — 지금 화면이 아니라 <strong>잡아 둔 범위</strong>
              {bboxSizeText(bbox) ? `(${bboxSizeText(bbox)})` : ""}로 찾습니다.
            </p>
          )}

          {/* 무엇이 걸렸는지 한 줄로. 교집합은 설명 없이 기호만 두면 합집합으로 읽힌다. */}
          <p className="scope__detail">
            찾는 범위: {scopeText({ regionCodes, bbox })}
          </p>
          {intersectionNote({ regionCodes, bbox }) && (
            <p className="scope__note">{intersectionNote({ regionCodes, bbox })}</p>
          )}

          {/* 좌표 없는 단지는 지도 범위로 찾을 수 없다 — 서버 notes 와 별개로 **고르기 전에** 말한다. */}
          <p className="scope__note scope__note--weak">
            좌표가 없는 단지는 지도 범위로 찾을 수 없어 후보에서 빠집니다.
          </p>
        </>
      )}
    </section>
  );
}
