/**
 * 앱 셸 — **핵심 루프**를 화면으로 연결한다.
 *
 *   내 조건(자산·선호) → 실구매 가능 금액 → 그 예산으로 좁혀진 지도 → AI 추천 + 근거
 *
 * 이 순서가 이 제품의 존재 이유다. 지도만 있으면 지도 뷰어지 자문 도구가 아니다.
 * 그래서 프로필이 비어 있으면 지도가 아니라 **조건 화면**으로 먼저 보낸다.
 *
 * 필터는 **보이게** 건다(칩 + 스위치). 조용히 걸린 필터는 사용자에게 "왜 안 보이지?"가 된다.
 *
 * 레이아웃 (App.css 의 --rail-w / --list-w 가 단일 진실)
 * ------------------------------------------------------
 *   폰(~899px)      : 지도 전체 + 좌상단 조건 바 + 바텀시트 3단
 *   태블릿(900~)    : 지도 + **우측 결과 패널**(시트가 패널이 된다)
 *   데스크톱(1200~) : **좌(조건) · 중(지도) · 우(결과)** 3분할
 *
 * DOM 은 한 벌이고 배치만 CSS 가 바꾼다 — 화면 크기별로 컴포넌트를 두 번 렌더하면
 * 접근성 이름이 중복되고 상태가 갈라진다.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { logout, type Preferences, type Profile } from "./api/client";
import { AdminScreen } from "./components/AdminScreen";
import { AffordabilityPanel, type PlanBasis } from "./components/AffordabilityPanel";
import { AuthForm } from "./components/AuthForm";
import { BottomSheet, type SnapPoint } from "./components/BottomSheet";
import { ComplexCard } from "./components/ComplexCard";
import { ConditionsScreen } from "./components/ConditionsScreen";
import { FilterRail } from "./components/FilterRail";
import { MapView } from "./components/MapView";
import { RecommendPanel } from "./components/RecommendPanel";
import { useAdminUsers } from "./hooks/useAdminUsers";
import { useAffordability, type AffordabilityState, type Purpose } from "./hooks/useAffordability";
import { useAuth } from "./hooks/useAuth";
import { useMapArea } from "./hooks/useMapArea";
import { useProfile } from "./hooks/useProfile";
import { useRecommendation } from "./hooks/useRecommendation";
import { useTagFilter } from "./hooks/useTagFilter";
import { readTargetPrice } from "./lib/affordability";
import { SORT_OPTIONS, isSortKey, sortComplexes, type SortKey } from "./lib/complexSort";
import { formatKrwShort } from "./lib/format";
import { filterList } from "./lib/listFilter";
import { effectiveBudgetKrw, filterChips, type MapFilterState } from "./lib/mapFilters";
import { NOTICE_NOT_ADVICE, NOTICE_TRADE_DELAY } from "./lib/notices";
import { appliedScope, scopeFields, type SearchScope } from "./lib/searchScope";
import { complexTagFacts } from "./lib/tags";
import { ListFilterBar } from "./components/ListFilterBar";
import "./App.css";

/**
 * 우측 패널에 남는 것은 **목록 두 개뿐**이다(사용자 요청).
 * "내 자금"은 목록이 아니라 계산 결과라서 탭이 아니라 **내 조건 안의 버튼**으로 옮겼다 —
 * 탭은 "무엇을 볼까"를 고르는 자리인데, 자금계획은 조건을 고치러 가는 길에 가깝다.
 */
type Tab = "map" | "advice";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "map", label: "주변 단지" },
  { id: "advice", label: "AI 추천" },
];

/** 실거주 기준 고정. 투자 목적(`invest`)은 세율·한도가 달라 별도 화면이 필요하다(2차). */
const PURPOSE: Purpose = "live";

interface HomeProps {
  preferences: Preferences;
  onEditConditions: () => void;
  /** 관리자 전용 진입점. 관리자가 아니면 **null** 이라 DOM 에 존재하지 않는다. */
  adminEntry?: React.ReactNode;
  /**
   * 실구매 가능 금액 + 자금계획. **Authenticated 가 들고 있다** —
   * 조건 화면(희망가 슬라이더 범위)과 지도 화면(자금계획)이 같은 한도를 봐야 하는데,
   * 두 화면은 서로 형제라 여기서 계산하면 조건 화면이 한도를 알 수 없다.
   */
  afford: AffordabilityState;
  /** 조건에 저장된 희망 매매가(원). null = 정하지 않음 — **0 과 다르다**. */
  targetPriceKrw: number | null;
  /**
   * 지금 고른 단지의 가격을 위로 올린다(자금계획의 what-if 기준).
   * 숫자만 올리는 이유: 훅의 의존성이 객체 정체성이면 지도 재조회마다 요청이 새로 나간다.
   */
  onPlanTargetChange: (krw: number | null) => void;
}

export function Home({
  preferences,
  onEditConditions,
  adminEntry,
  afford,
  targetPriceKrw,
  onPlanTargetChange,
}: HomeProps) {
  const [tab, setTab] = useState<Tab>("map");
  /** 자금계획 화면을 띄웠는가. 탭이 아니라 **내 조건에서 열고 닫는 화면**이다. */
  const [moneyOpen, setMoneyOpen] = useState(false);
  const [snap, setSnap] = useState<SnapPoint>("peek");
  const [selected, setSelected] = useState<number | null>(null);
  /** 목록에서 가리키는 중인 단지 — 지도 마커를 들어올린다(선택과 다르다: 지도를 움직이지 않는다). */
  const [hovered, setHovered] = useState<number | null>(null);
  const [sort, setSort] = useState<SortKey>("default");
  /** AI 추천을 돌릴 시군구(5자리). 빈 배열 = 수도권 전체 — 그 사실은 RegionPicker 가 화면에 적는다. */
  const [regionCodes, setRegionCodes] = useState<string[]>([]);
  /**
   * "이 주변" — 사용자가 버튼을 누른 **그 순간의** 지도 범위를 고정해 둔다.
   * 실행 시점에 다시 읽지 않는 이유는 AreaScope 주석 참고(조용히 바뀌는 조건 금지).
   */
  const [areaBbox, setAreaBbox] = useState<string | null>(null);
  /** 이번 분석이 실제로 돌아간 범위. 결과가 나온 뒤 조건을 바꿔도 결과 옆 표기는 남아야 한다. */
  const [appliedScopeState, setAppliedScope] = useState<SearchScope | null>(null);

  // 필터 스위치 — 기본은 켜짐. 끌 수 있어야 "왜 안 보이지?"에 사용자가 스스로 답한다.
  const [budgetApplied, setBudgetApplied] = useState(true);
  const [preferApplied, setPreferApplied] = useState(true);

  /**
   * "예산 내만 보기" — **기본은 꺼짐**.
   *
   * 켠 채로 시작하면 처음 보는 화면에서 이미 몇 건이 사라져 있고, 사용자는 그게 전부인 줄
   * 안다. 예산을 넘는 집을 **보는 것** 자체가 이 도구의 기능이다(살 수 있는지는 자금계획이
   * 숫자로 답한다). 대신 켜고 끈 상태와 숨긴 건수를 목록 위에 항상 적는다.
   */
  const [budgetOnly, setBudgetOnly] = useState(false);
  const mapTags = useTagFilter();

  const budgetKrw = afford.data?.max_purchase_krw ?? null;

  const filters: MapFilterState = useMemo(
    () => ({
      budgetKrw,
      budgetApplied,
      // 희망가를 정했으면 지도 상한도 그 값이다 — 추천(budget_override_krw)과 같은 숫자를
      // 써야 "추천에는 뜨는데 지도엔 없는 단지"가 생기지 않는다(lib/mapFilters 주석).
      targetPriceKrw,
      prefer: preferences.prefer ?? null,
      preferApplied,
    }),
    [budgetKrw, budgetApplied, targetPriceKrw, preferences.prefer, preferApplied],
  );

  const map = useMapArea(filters);
  const rec = useRecommendation();

  // 추천 순위를 지도 마커에 얹는다 — 리스트와 지도가 같은 사실을 말하게.
  const rankById = useMemo(() => {
    const out: Record<number, number> = {};
    for (const item of rec.job?.items ?? []) {
      if (item.rank !== undefined) out[item.complex.id] = item.rank;
    }
    return out;
  }, [rec.job]);

  /** 목록에 실제로 그릴 순서. 지도 범위 안에서만 도는 클라이언트 정렬이다(서버 계약에 정렬이 없다). */
  const listItems = useMemo(
    () => sortComplexes(map.items, sort, rankById),
    [map.items, sort, rankById],
  );

  /**
   * 예산·특성 필터를 적용한 결과. **정렬 뒤에** 건다 — 순서를 바꾸지 않고 걸러내기만 한다.
   * 예산 기준은 지도 조회에 쓴 값과 **같은 숫자**(희망가 우선, 없으면 한도)여야
   * "지도엔 있는데 목록엔 없는 단지"가 생기지 않는다.
   */
  const listBudgetKrw = effectiveBudgetKrw(filters);
  const mapOutcome = useMemo(
    () =>
      filterList(
        listItems.map((item) => ({
          item,
          priceKrw: item.recent_price_krw,
          facts: complexTagFacts(item),
        })),
        {
          budgetOnly,
          budgetKrw: listBudgetKrw,
          tags: mapTags.tags,
          includeUnknownTag: mapTags.includeUnknown,
        },
      ),
    [listItems, budgetOnly, listBudgetKrw, mapTags.tags, mapTags.includeUnknown],
  );

  const onBoundsChange = useCallback(
    (bbox: string, zoom: number) => {
      // 지도를 움직이면 시트를 내려 지도가 가려지지 않게 한다(ux §3).
      setSnap((s) => (s === "full" ? "half" : s));
      map.onBoundsChange(bbox, zoom);
    },
    [map],
  );

  const handleSelect = useCallback((id: number) => {
    setSelected(id);
    setSnap((s) => (s === "peek" ? "half" : s));
  }, []);

  const showOnMap = useCallback((id: number) => {
    setTab("map");
    setMoneyOpen(false); // 지도를 보러 가는데 자금 화면이 덮고 있으면 안 된다
    setSelected(id);
    setSnap("half");
  }, []);

  const openMoney = useCallback(() => {
    setMoneyOpen(true);
    // 폰에서는 시트가 접혀 있을 수 있다 — 열었는데 안 보이면 아무 일도 안 일어난 것처럼 읽힌다.
    setSnap((s) => (s === "peek" ? "half" : s));
  }, []);

  const startRecommendation = useCallback(() => {
    // 예산은 서버가 /affordability 로 다시 계산한다 — 화면이 계산한 값을 보내면 진실이 두 개가 된다.
    // **다만 희망 매매가는 사용자가 정한 입력**이라 그대로 실어 보낸다(budget_override_krw).
    // 이게 없으면 슬라이더는 "저장만 되고 아무 데도 안 쓰이는 값"이 된다(PREF-1).
    // 지역은 **사용자가 고른 것을 그대로** 보낸다. 빈 배열이면 서버가 전체에서 찾는다
    // (예전엔 아예 보내지 않아 항상 수도권 전체였고, 그래서 추천이 엉뚱하게 느껴졌다).
    // "이 주변"(bbox)이 함께 있으면 서버가 **교집합**으로 좁힌다(api-spec).
    const scope: SearchScope = { regionCodes, bbox: areaBbox };
    // 화면에 적는 범위는 **실제로 보낸 것**과 같아야 한다 — 그래서 같은 함수로 되돌려 만든다.
    setAppliedScope(appliedScope(scope));
    void rec.start({
      purpose: PURPOSE,
      top_n: 10,
      budget_override_krw: targetPriceKrw,
      ...scopeFields(scope),
    });
  }, [areaBbox, rec, regionCodes, targetPriceKrw]);

  const clearArea = useCallback(() => setAreaBbox(null), []);

  const chips = filterChips(filters);
  const toggleChip = useCallback((id: "budget" | "area" | "built") => {
    if (id === "budget") setBudgetApplied((v) => !v);
    else setPreferApplied((v) => !v);
  }, []);

  /* ── 단지 기준 자금계획 ─────────────────────────────────────────────────
     지도·목록에서 고른 단지의 가격으로 "이 집을 사려면 뭐가 필요한가"를 계산한다.
     그 값은 `recent_price_krw` = **최근 실거래 기반 추정치**지 호가가 아니다 —
     `price_confidence` 를 그대로 물려 화면이 추정임을 말한다. */
  const planComplex = useMemo(
    () => map.items.find((c) => c.id === selected) ?? null,
    [map.items, selected],
  );
  const planComplexPrice = planComplex?.recent_price_krw ?? null;

  // 숫자만 위로 올린다. 지도를 다시 조회하면 같은 단지라도 객체가 새로 오는데,
  // 객체를 올리면 가격이 그대로여도 요청이 한 번 더 나간다.
  useEffect(() => {
    onPlanTargetChange(planComplexPrice);
    return () => onPlanTargetChange(null);
  }, [planComplexPrice, onPlanTargetChange]);

  const planBasis: PlanBasis | null =
    planComplex && planComplexPrice !== null
      ? {
          kind: "complex",
          name: planComplex.name,
          // `/map/complexes` 는 확정가를 주지 않는다 — `price_confidence` 는 `estimated`
          // 아니면 `unknown` 뿐이다(api-spec §4). 둘 다 "지금 살 수 있는 호가"가 아니므로
          // 추정으로 표기한다. 모르는 쪽을 확정으로 올리는 일은 하지 않는다.
          estimated: true,
          asOf: planComplex.price_as_of,
        }
      : targetPriceKrw !== null
        ? { kind: "manual" }
        : null;

  /** 고른 단지에 시세 근거가 없으면 그 사실을 말한다(내 희망가 계획으로 조용히 되돌아가지 않게). */
  const planComplexNoPrice =
    planComplex && planComplexPrice === null ? planComplex.name : null;

  const clearPlanComplex = useCallback(() => setSelected(null), []);

  const title = moneyOpen
    ? "내 자금"
    : tab === "map"
      ? map.level === "cluster"
        ? `지역 ${map.clusters.length}곳`
        : `단지 ${map.items.length}건`
      : "AI 추천";

  /* 정렬은 목록 바로 위에 둔다. 네이티브 select 를 쓰는 이유: 키보드·스크린리더·모바일
     기본 피커가 전부 공짜로 따라오고, 직접 만든 드롭다운은 그 셋을 대개 못 만든다. */
  const sortControl =
    !moneyOpen && tab === "map" && map.level === "complex" && listItems.length > 0 ? (
      <label className="app__sort">
        <span className="sr-only">목록 정렬</span>
        <select
          className="app__sort-select"
          value={sort}
          onChange={(e) => isSortKey(e.target.value) && setSort(e.target.value)}
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
    ) : null;

  return (
    <main className="app">
      <h1 className="sr-only">부동산 AI 자문</h1>

      {/* 좌상단(폰) · 좌측 패널(데스크톱) — 조건은 지도를 보는 내내 보이고 고칠 수 있어야 한다.
          "내 자금"도 여기서 연다: 목록 탭이 아니라 **내 조건에 딸린 계산 결과**이기 때문. */}
      <FilterRail
        chips={chips}
        onToggle={toggleChip}
        onEdit={onEditConditions}
        onOpenMoney={openMoney}
        moneyOpen={moneyOpen}
        maxPurchaseKrw={afford.data?.max_purchase_krw ?? null}
      />

      <MapView
        onBoundsChange={onBoundsChange}
        items={map.items}
        clusters={map.clusters}
        selectedId={selected}
        hoveredId={hovered}
        onSelect={handleSelect}
        rankById={rankById}
      />

      <BottomSheet snap={snap} onSnapChange={setSnap} title={title} actions={sortControl}>
        {/* 자금 화면일 때는 탭을 감춘다 — 지금 어디에 있는지가 분명해야 돌아갈 길도 분명하다 */}
        {moneyOpen ? (
          <div className="app__money">
            <button
              type="button"
              className="app__moneyback"
              onClick={() => setMoneyOpen(false)}
            >
              ← 목록으로
            </button>
            <AffordabilityPanel
              data={afford.data}
              loading={afford.loading}
              error={afford.error}
              needsProfile={afford.needsProfile}
              onEditConditions={onEditConditions}
              planBasis={planBasis}
              noPriceComplexName={planComplexNoPrice}
              onClearComplex={clearPlanComplex}
              targetPriceKrw={targetPriceKrw}
            />
          </div>
        ) : (
          <>
            <div className="app__tabs" role="tablist" aria-label="화면 전환">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  id={`tab-${t.id}`}
                  aria-selected={tab === t.id}
                  // 패널은 하나만 렌더링한다 → 모든 탭이 같은 패널을 가리킨다.
                  // 존재하지 않는 id 를 가리키면 보조기기에서 깨진 참조가 된다.
                  aria-controls="app-panel"
                  className={`app__tab${tab === t.id ? " app__tab--on" : ""}`}
                  onClick={() => setTab(t.id)}
                >
                  {t.label}
                </button>
              ))}
            </div>

            <div id="app-panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
              {tab === "map" && (
                <>
                  {map.error && (
                    <p className="app__error" role="alert">
                      {map.error}
                    </p>
                  )}
                  {map.loading && <p className="app__status">불러오는 중…</p>}

                  {!map.loading && map.level === "cluster" && (
                    <>
                      <p className="app__hint">지도를 확대하면 개별 단지가 표시됩니다.</p>
                      <ul className="app__clusters">
                        {map.clusters.map((c) => (
                          <li key={c.region_code} className="app__cluster">
                            <span className="app__cluster-count num">{c.count}</span>
                            <span className="app__cluster-region">{c.region_code}</span>
                            <span className="app__cluster-price num estimated">
                              {c.median_price_krw ? `중위 ${formatKrwShort(c.median_price_krw)}` : "—"}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}

                  {!map.loading && map.level === "complex" && (
                    <>
                      {listItems.length === 0 && (
                        <p className="app__status">
                          이 범위에 조건에 맞는 단지가 없습니다. 지도를 옮기거나 조건 스위치를
                          꺼 보세요.
                        </p>
                      )}
                      {listItems.length > 0 && (
                        // 전국 순위처럼 읽히지 않게 정렬 범위를 밝힌다
                        <p className="app__scope">지금 보이는 지도 범위 기준</p>
                      )}
                      {/* 예산 토글 + 특성 칩. 목록이 있을 때만 — 거를 게 없으면 조작도 없다. */}
                      {listItems.length > 0 && (
                        <ListFilterBar
                          listLabel="주변 단지"
                          outcome={mapOutcome}
                          budgetOnly={budgetOnly}
                          onBudgetOnlyChange={setBudgetOnly}
                          onToggleTag={mapTags.toggle}
                          onClearTags={mapTags.clear}
                          includeUnknownTag={mapTags.includeUnknown}
                          onIncludeUnknownChange={mapTags.setIncludeUnknown}
                        />
                      )}
                      {/* 필터로 0건이 됐으면 "없다"가 아니라 "걸러졌다"고 말한다 */}
                      {listItems.length > 0 && mapOutcome.entries.length === 0 && (
                        <p className="app__status">
                          필터에 걸려 {listItems.length}건이 모두 가려졌습니다. 예산 토글이나
                          특성 칩을 꺼 보세요.
                        </p>
                      )}
                      {/* 고른 단지의 자금계획으로 바로 건너뛴다 — 계산은 이미 돌고 있고,
                          이 버튼은 그 결과가 어디 있는지 알려 주는 길이다. */}
                      {planComplex && (
                        <button type="button" className="app__planjump" onClick={openMoney}>
                          {planComplex.name} 자금계획 보기
                        </button>
                      )}
                      {mapOutcome.entries.map((entry) => (
                        <ComplexCard
                          key={entry.item.id}
                          item={entry.item}
                          selected={selected === entry.item.id}
                          rank={rankById[entry.item.id]}
                          tags={entry.tags}
                          unknownTags={entry.unknownTags}
                          budget={entry.budget}
                          onSelect={handleSelect}
                          onHover={setHovered}
                        />
                      ))}
                    </>
                  )}
                </>
              )}

              {tab === "advice" && (
                <RecommendPanel
                  phase={rec.phase}
                  job={rec.job}
                  error={rec.error}
                  budgetKrw={budgetKrw}
                  // 목록 필터가 쓰는 예산은 지도와 **같은 숫자**여야 한다(희망가 우선).
                  listBudgetKrw={listBudgetKrw}
                  budgetOnly={budgetOnly}
                  onBudgetOnlyChange={setBudgetOnly}
                  regionCodes={regionCodes}
                  onRegionsChange={setRegionCodes}
                  // 지도가 들고 있는 범위를 **그대로** 넘긴다(화면이 bbox 를 새로 계산하지 않는다).
                  currentBbox={map.bbox}
                  areaBbox={areaBbox}
                  onCaptureArea={setAreaBbox}
                  onClearArea={clearArea}
                  appliedScope={appliedScopeState}
                  onStart={startRecommendation}
                  onCancel={rec.cancel}
                  onShowOnMap={showOnMap}
                  onEditConditions={onEditConditions}
                />
              )}
            </div>
          </>
        )}

        {/* 고지는 조용하지만 사라지지 않게 상시 노출한다(lib/notices) */}
        <footer className="app__foot">
          <p className="app__note">{NOTICE_TRADE_DELAY}</p>
          <p className="app__disclaimer">{NOTICE_NOT_ADVICE}</p>
          <div className="app__footactions">
            <button type="button" className="app__logout" onClick={() => void logout()}>
              로그아웃
            </button>
            {adminEntry}
          </div>
        </footer>
      </BottomSheet>
    </main>
  );
}

/**
 * 로그인 이후의 분기. **프로필이 비어 있으면 조건 화면으로 유도한다** —
 * 자산 없이는 예산도 추천도 존재할 수 없으므로 지도를 먼저 보여주는 건 순서가 틀렸다.
 */
export function Authenticated() {
  const { status, profile, preferences, error, reload, save } = useProfile();
  const [editing, setEditing] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);

  /**
   * 희망 매매가 — **저장된 선호가 정본**이다(`prefer.target_price_krw`).
   * 이 한 값이 세 곳으로 동시에 나간다:
   *   ① `/affordability` 의 `target_price_krw` (자금계획)
   *   ② `/recommendations` 의 `budget_override_krw` (AI 추천 예산)
   *   ③ `/map/complexes` 의 `max_price_krw` (지도 상한)
   * 셋 중 하나라도 빠지면 "화면에만 있는 조건"이 된다 — App.test 가 ①②를 고정한다.
   */
  const targetPriceKrw = readTargetPrice(preferences.prefer);

  /** 지도에서 고른 단지의 가격(what-if). 있으면 자금계획은 이쪽을 기준으로 선다. */
  const [complexTargetKrw, setComplexTargetKrw] = useState<number | null>(null);

  /**
   * 자산이 없으면 계산 자체가 성립하지 않으므로 요청하지 않는다(422 를 일부러 받지 않는다).
   * 조건 화면(희망가 슬라이더 범위)도 이 결과의 `max_purchase_krw` 를 쓰기 때문에
   * 훅이 여기 있어야 한다 — Home 안에 있으면 조건 화면이 한도를 볼 수 없다.
   */
  const afford = useAffordability(
    status === "ready",
    PURPOSE,
    complexTargetKrw ?? targetPriceKrw,
  );
  const maxPurchaseKrw = afford.data?.max_purchase_krw ?? null;

  // 관리자인지는 **서버만 안다** — 이 훅이 /admin/users 를 한 번 물어보고,
  // 200 을 받았을 때에만 availability 가 "available" 이 된다(useAdminUsers 주석 참고).
  // 일반 사용자에게는 아래 진입점이 아예 렌더되지 않으므로 404 를 볼 일도 없다.
  const admin = useAdminUsers(true);
  const adminAvailable = admin.availability === "available";

  const closeAdmin = useCallback(() => {
    setAdminOpen(false);
    admin.setFilter("pending"); // 다음에 열 때 대기자부터 보이게 되돌린다
  }, [admin]);

  const handleSave = useCallback(
    async (p: Profile, prefs: Preferences) => {
      await save(p, prefs);
      setEditing(false);
    },
    [save],
  );

  // 권한이 사라지면(강등) availability 가 unavailable 로 바뀌며 화면이 함께 닫힌다.
  if (adminOpen && adminAvailable) {
    return <AdminScreen admin={admin} onClose={closeAdmin} />;
  }

  /** 관리자 전용 진입점. 관리자가 아니면 이 요소 자체가 없다(숨김 처리가 아니다). */
  const adminEntry = adminAvailable ? (
    <button type="button" className="app__adminbtn" onClick={() => setAdminOpen(true)}>
      가입 승인
      {admin.pending > 0 && (
        <span className="app__adminbtn-count num">
          {admin.pending}
          <span className="sr-only">건 대기</span>
        </span>
      )}
    </button>
  ) : null;

  if (status === "loading") {
    return (
      <main className="app app--boot" aria-busy="true">
        <p className="app__boot" role="status">
          내 조건을 불러오는 중…
        </p>
      </main>
    );
  }

  if (status === "error") {
    return (
      <main className="app app--boot">
        <p className="app__error" role="alert">
          {error}
        </p>
        <button type="button" className="app__logout" onClick={() => void reload()}>
          다시 시도
        </button>
      </main>
    );
  }

  if (status === "missing" || editing) {
    return (
      <>
        {/* 자산을 아직 안 넣은 관리자도 승인은 할 수 있어야 한다 — 첫 관리자는
            아무도 승인해 주지 않으므로 여기서 막히면 서비스가 시작되지 않는다. */}
        {adminEntry && <div className="app__adminbar">{adminEntry}</div>}
        <ConditionsScreen
          profile={profile}
          preferences={preferences}
          onSave={handleSave}
          // 최초 입력(프로필 없음)에는 취소가 없다 — 되돌아갈 화면이 아직 없다.
          onClose={status === "missing" ? undefined : () => setEditing(false)}
          // 희망가 슬라이더의 범위 기준. 아직 계산 전이면 null 이고, 그때 화면은
          // 한도를 그리지 않는다(모르는 값을 눈금으로 만들지 않는다).
          maxPurchaseKrw={maxPurchaseKrw}
        />
      </>
    );
  }

  return (
    <Home
      preferences={preferences}
      onEditConditions={() => setEditing(true)}
      adminEntry={adminEntry}
      afford={afford}
      targetPriceKrw={targetPriceKrw}
      onPlanTargetChange={setComplexTargetKrw}
    />
  );
}

export default function App() {
  const { authenticated, checked } = useAuth();

  // 세션 복원(POST /auth/refresh) 결과가 오기 전엔 판단을 보류한다.
  // 안 그러면 새로고침할 때마다 로그인 폼이 번쩍였다 사라진다.
  if (!checked) {
    return (
      <main className="app app--boot" aria-busy="true">
        <p className="app__boot" role="status">
          세션을 확인하는 중…
        </p>
      </main>
    );
  }

  // 미로그인 → 로그인 게이트. 로그인 성공/토큰만료는 useAuth 구독으로 자동 전환된다.
  if (!authenticated) return <AuthForm />;
  return <Authenticated />;
}
