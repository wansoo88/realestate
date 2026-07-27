/**
 * 내 조건 레일 — **지금 무엇이 걸려 있는지**와 **언제든 고칠 수 있는 입구**.
 *
 * 왜 지도 위로 올라왔나
 * ---------------------
 * 예전에는 조건 칩이 바텀시트 **안**에 있었다. 시트를 내리면 사라지니, 지도를 보는 동안에는
 * "왜 이 단지들만 보이는지"를 알 수 없었고 조건을 고치려면 시트를 다시 올려야 했다.
 * (사용자 요청: "내 조건도 지도에서 언제든지 설정할 수 있게, 좌상단/좌하단에 설정 버튼")
 *
 * 자리 선택: **좌상단**. 좌하단은 카카오맵 로고·저작권이 그려지는 자리라 비워 둔다(가리면 약관 위반).
 * 우측은 확대/축소 컨트롤이 쓴다.
 *
 * 데스크톱(≥1200px)에서는 이 컴포넌트가 **좌측 고정 패널**이 된다. 부동산 서비스의 데스크톱
 * 표준이 좌(조건)–중(지도)–우(결과)이고, 조건은 지도를 덮지 않는 자리에 상주하는 편이 낫다.
 * DOM 은 하나이고 배치만 CSS 로 바뀐다 — 같은 버튼을 두 벌 렌더하면 접근성 이름이 중복되고
 * 상태가 두 곳으로 갈라진다.
 */
import { formatKrwShort } from "../lib/format";
import type { FilterChip } from "../lib/mapFilters";
import "./FilterRail.css";

interface Props {
  chips: FilterChip[];
  onToggle: (id: FilterChip["id"]) => void;
  onEdit: () => void;
  /**
   * "내 자금"(자금계획) 진입점. 우측 패널의 탭이 아니라 **여기**에 있는 이유:
   * 우측은 목록(주변 단지·AI 추천)을 보는 자리이고, 자금계획은 목록이 아니라
   * 내가 넣은 조건에서 나온 **계산 결과**다 — 조건 옆에 있어야 맥락이 맞는다.
   */
  onOpenMoney?: () => void;
  /** 지금 자금 화면이 열려 있는가(같은 버튼이 상태를 말한다). */
  moneyOpen?: boolean;
  /**
   * 실구매 가능 금액. 버튼에 **숫자를 함께** 보여준다 —
   * "내 자금"이라는 라벨만 있으면 눌러 보기 전엔 아무 정보도 주지 않는다.
   * 아직 계산 전이면 null 이고, 그때는 숫자를 지어내지 않고 라벨만 남긴다.
   */
  maxPurchaseKrw?: number | null;
}

export function FilterRail({
  chips,
  onToggle,
  onEdit,
  onOpenMoney,
  moneyOpen,
  maxPurchaseKrw,
}: Props) {
  return (
    <aside className="rail" aria-label="내 조건">
      <h2 className="rail__title">내 조건</h2>

      <div className="rail__row">
        {/* 상시 진입점 — 지도를 보다가 바로 조건을 고칠 수 있어야 한다 */}
        <button type="button" className="rail__edit" onClick={onEdit}>
          {/* 인라인 SVG(CSP: 아이콘 라이브러리 금지) — 슬라이더 모양이 '설정'을 가장 덜 모호하게 말한다 */}
          <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" focusable="false">
            <path
              d="M3 6h9M15 6h2M3 14h2M8 14h9"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              fill="none"
            />
            <circle cx="13.5" cy="6" r="2.1" fill="none" stroke="currentColor" strokeWidth="1.6" />
            <circle cx="6.5" cy="14" r="2.1" fill="none" stroke="currentColor" strokeWidth="1.6" />
          </svg>
          {chips.length > 0 ? "조건 수정" : "내 조건 입력"}
        </button>

        {/* 내 자금 — 조건과 같은 줄. 계산된 한도를 버튼 위에 그대로 적는다. */}
        {onOpenMoney && (
          <button
            type="button"
            className={`rail__money${moneyOpen ? " rail__money--on" : ""}`}
            aria-pressed={moneyOpen ?? false}
            onClick={onOpenMoney}
          >
            내 자금
            {maxPurchaseKrw ? (
              <span className="rail__money-amount num">{formatKrwShort(maxPurchaseKrw)}</span>
            ) : (
              // 아직 모르는 값을 0 으로 그리지 않는다 — 계산 전이라는 사실만 조용히 남긴다
              <span className="rail__money-amount rail__money-amount--none">계산 전</span>
            )}
          </button>
        )}

        {/* 조용히 걸린 필터는 "왜 안 보이지?"가 된다 — 그 자리에서 끌 수 있게 둔다 */}
        {chips.map((chip) => (
          <button
            key={chip.id}
            type="button"
            className={`rail__chip${chip.active ? " rail__chip--on" : ""}`}
            aria-pressed={chip.active}
            onClick={() => onToggle(chip.id)}
          >
            {chip.label}
          </button>
        ))}
      </div>

      <p className="rail__note">켜진 조건만 지도와 목록에 적용됩니다.</p>
    </aside>
  );
}
