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
import { MyListingsScreen } from "./components/MyListingsScreen";
import { useAdminUsers } from "./hooks/useAdminUsers";
import {
  useAffordability,
  type AffordabilityState,
  type PlanTarget,
} from "./hooks/useAffordability";
import { useAuth } from "./hooks/useAuth";
import { useMapArea } from "./hooks/useMapArea";
import { useMyListings } from "./hooks/useMyListings";
import { useProfile } from "./hooks/useProfile";
import { useRecommendation } from "./hooks/useRecommendation";
import { useTagFilter } from "./hooks/useTagFilter";
import { planArea, readTargetPrice, type PlanArea } from "./lib/affordability";
import { budgetStatusView } from "./lib/budgetStatus";
import { SORT_OPTIONS, isSortKey, sortComplexes, type SortKey } from "./lib/complexSort";
import { formatKrwShort } from "./lib/format";
import { filterList } from "./lib/listFilter";
import {
  budgetRequested,
  displayBudget,
  filterChips,
  type MapFilterState,
} from "./lib/mapFilters";
import { applyScreenBudget, serverBudgetVerdict } from "./lib/screenBudget";
import { NOTICE_NOT_ADVICE, NOTICE_TRADE_DELAY } from "./lib/notices";
import { DEFAULT_PURPOSE } from "./lib/purpose";
import { conditionFields, conditionPlan, type ConditionPlan } from "./lib/recommendConditions";
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

/**
 * 이 화면이 쓰는 한도 산정 가정. **정의는 `lib/purpose.ts` 한 곳**에 있다.
 *
 * 여기서 다시 `"live"` 라고 적지 않는 이유: 이 값은 `/affordability`(자금계획),
 * `/recommendations`(추천), `/map/complexes`(지도 배지) **세 곳으로 동시에** 나가는데,
 * 목적에 따라 대출 절대한도·스트레스 가산이 **달라질 수 있다.** 리터럴을 여러 번 적으면
 * 투자 모드를 켜는 날 한 곳이 남고, 그 화면만 다른 한도로 조용히 계산한다.
 *
 * ⚠️ 오늘은 두 목적의 한도가 **같다** (CR38-4) — 운영 데이터에 `purpose` 조건 규칙이
 *    0개다. 그래도 배선을 지금 갖춰 두는 이유는 `lib/purpose.ts` 머리말에 있다.
 */
const PURPOSE = DEFAULT_PURPOSE;

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
   * 지금 고른 단지를 위로 올린다(자금계획의 what-if 기준).
   *
   * ⚠️ **금액이 아니라 단지 id 를 올린다**(CR35-4). 지도의 `recent_price_krw` 는 "최근 체결
   *    1건"이고 추천 카드는 "창 중위를 기준월로 환산한 추정가"다 — 화면이 지도 값을 실어
   *    보내면 같은 단지의 자금계획과 추천 카드가 다른 금액으로 선다(부족액 최대 −3.19억).
   *    금액은 서버가 **추천과 같은 함수**로 정한다.
   */
  onPlanComplexChange: (basis: PlanComplex | null) => void;
}

/** 자금계획을 세울 단지. 금액은 없다 — 서버가 정한다. */
export interface PlanComplex {
  id: number;
  name: string;
  /** 어느 면적으로 물어볼 것인가 + 그 면적을 **왜 골랐는지**(화면이 말해야 한다). */
  area: PlanArea;
  /** 지도가 말한 기준일(추정 표기용). */
  asOf: string | null;
  /** 지도에 시세가 아예 없었는가 — 서버가 기준가를 못 만들 때 문장이 갈린다. */
  noMapPrice: boolean;
}

export function Home({
  preferences,
  onEditConditions,
  adminEntry,
  afford,
  targetPriceKrw,
  onPlanComplexChange,
}: HomeProps) {
  const [tab, setTab] = useState<Tab>("map");
  /** 자금계획 화면을 띄웠는가. 탭이 아니라 **내 조건에서 열고 닫는 화면**이다. */
  const [moneyOpen, setMoneyOpen] = useState(false);
  /**
   * 내 매물(직접 입력한 호가) 화면. 자금 화면과 같은 규칙으로 열고 닫는다.
   * `listingComplex` 가 있으면 그 단지로 좁혀서 열린다 — 단지 없이 열면 목록만 본다
   * (단지를 모르는 호가는 어디에도 붙일 수 없어 입력 폼을 열지 않는다).
   */
  const [listingsOpen, setListingsOpen] = useState(false);
  const [listingComplex, setListingComplex] = useState<{ id: number; name: string } | null>(
    null,
  );
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
  /** 이번 분석이 실제로 쓴 "내 조건". 범위와 같은 이유로 **실행 시점에 고정**한다. */
  const [appliedPlan, setAppliedPlan] = useState<ConditionPlan | null>(null);

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
      // 지도도 자금계획과 **같은 가정**으로 물어본다. 안 보내면 서버가 live 로 계산하는데
      // 자금 패널이 invest 로 계산하고 있으면 같은 단지가 "지도: 초과 / 자금: 가능"이 된다.
      purpose: PURPOSE,
    }),
    [budgetKrw, budgetApplied, targetPriceKrw, preferences.prefer, preferApplied],
  );

  const map = useMapArea(filters);
  const rec = useRecommendation();
  /** 화면을 열었을 때만 조회한다 — 지도만 보는 사용자에게 매 로딩마다 요청을 하나 더 얹지 않는다. */
  const listings = useMyListings(listingsOpen, listingComplex?.id ?? null);

  // 추천 순위를 지도 마커에 얹는다 — 리스트와 지도가 같은 사실을 말하게.
  const rankById = useMemo(() => {
    const out: Record<number, number> = {};
    for (const item of rec.job?.items ?? []) {
      if (item.rank !== undefined) out[item.complex.id] = item.rank;
    }
    return out;
  }, [rec.job]);

  /**
   * 화면이 "지금 무엇을 기준으로 삼고 있다고 말하는가". **판정에는 쓰지 않는다**(CR38-1).
   *
   * ⚠️ `displayBudget` 이다(`effectiveBudget` 이 아니다). **예산 칩을 끄면 `null`** 이 되어
   *    칩 문구·추천 목록의 초과 집계가 함께 사라진다(CR37-7: 예전엔 켜도 꺼도 똑같았다).
   *
   * 이 값의 쓰임은 셋뿐이다:
   *   ① `basis` — 서버가 말한 기준과 대조(`budgetStatusView.basisMismatch`).
   *   ② `krw`   — **AI 추천 목록**의 예산 판정. 그쪽은 서버가 항목별 판정을 주지 않는다.
   *   ③ 칩이 꺼졌는지(`budgetDisplayOff`) — "모른다"와 "껐다"를 구분해 말하려고.
   * 지도·목록 배지는 여기서 오지 않는다 — 서버가 항목마다 그 면적의 한도로 판정한다.
   */
  const listBudget = useMemo(() => displayBudget(filters), [filters]);
  const listBudgetKrw = listBudget.krw;
  /** 초과 표시가 지금 꺼져 있는가 — "예산을 모른다"와 **다른 사실**이라 따로 들고 다닌다. */
  const budgetDisplayOff = !budgetApplied;

  /**
   * 지도·목록이 **함께 쓰는** 항목. 예산 판정은 서버가 항목마다 그 항목 면적의 한도로
   * 내린 값(`over_budget`)이고, 화면은 예산 칩이 꺼져 있으면 그걸 비우기만 한다.
   *
   * 왜 화면이 다시 판정하지 않나 (CR38-1)
   * -------------------------------------
   * 실구매 한도는 취득세 구간(85㎡) 때문에 **면적별로 다른 숫자**다. 화면이 아는 숫자는
   * `/affordability` 가 준 하나뿐이고(선택 단지 면적, 없으면 84㎡), 그 하나로 지도 전체를
   * 판정하면 120㎡ 단지의 배지가 84㎡ 한도로 선다. 리뷰가 세 상태(단지 미선택 · 85㎡
   * 이하 선택 · 85㎡ 초과 선택) 전부에서 서버와 2건씩 갈리는 것을 재현했다.
   *
   * ⚠️ 판정 불가는 **`null` 로 남긴다**(false 로 접지 않는다). 그 접힘은 화면에 흔적이
   *    남지 않으므로(배지는 `=== true` 일 때만 붙는다) 여기서 손으로 만들지 않고
   *    `applyScreenBudget` 하나만 쓴다 — `MapView` 는 그 함수가 만든 브랜드 타입
   *    (`ScreenComplexItem`)만 받으므로 인라인으로 우회하면 tsc 가 죽는다.
   */
  const mapItems = useMemo(
    () => applyScreenBudget(map.items, budgetApplied),
    [map.items, budgetApplied],
  );

  /** 목록에 실제로 그릴 순서. 지도 범위 안에서만 도는 클라이언트 정렬이다(서버 계약에 정렬이 없다). */
  const listItems = useMemo(
    () => sortComplexes(mapItems, sort, rankById),
    [mapItems, sort, rankById],
  );

  /**
   * 예산·특성 필터를 적용한 결과. **정렬 뒤에** 건다 — 순서를 바꾸지 않고 걸러내기만 한다.
   *
   * 판정은 마커와 **같은 값**을 쓴다(`over_budget` → `serverBudgetVerdict`). 목록과 지도는
   * 같은 응답을 그리는 두 화면이라, 여기서 다른 규칙을 쓰면 같은 단지가 카드에서는
   * "예산 초과", 마커에서는 아무 표시 없이 서게 된다.
   */
  const mapOutcome = useMemo(
    () =>
      filterList(
        listItems.map((item) => ({
          item,
          budget: serverBudgetVerdict(item.over_budget),
          facts: complexTagFacts(item),
        })),
        {
          budgetOnly,
          tags: mapTags.tags,
          includeUnknownTag: mapTags.includeUnknown,
        },
      ),
    [listItems, budgetOnly, mapTags.tags, mapTags.includeUnknown],
  );

  /**
   * 서버가 말한 예산 기준(`budget` 블록) → 화면 문장.
   * 켰는데 `applied:false` 로 오면 **사유를 그대로 보여준다** — 아무 일도 안 일어난 것처럼
   * 보이면 사용자는 조건이 걸린 줄 알고 예산 밖 단지를 본다.
   */
  const budgetStatus = useMemo(
    () =>
      budgetStatusView({
        budget: map.budget,
        requested: budgetRequested(filters),
        screenBasis: listBudget.basis,
      }),
    [map.budget, filters, listBudget.basis],
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
    setListingsOpen(false);
    setSelected(id);
    setSnap("half");
  }, []);

  const openMoney = useCallback(() => {
    setMoneyOpen(true);
    setListingsOpen(false);
    // 폰에서는 시트가 접혀 있을 수 있다 — 열었는데 안 보이면 아무 일도 안 일어난 것처럼 읽힌다.
    setSnap((s) => (s === "peek" ? "half" : s));
  }, []);

  /**
   * 내 매물 열기. **단지를 함께 받으면** 그 단지의 호가 입력 폼이 바로 열린다 —
   * 추천 결과가 "'내 매물'에서 직접 입력하시면 가격 축이 반영됩니다"라고 말하는 그 자리로
   * 곧장 데려가는 길이다(CR35-2: 예전에는 그 안내만 있고 화면이 없었다).
   */
  const openListings = useCallback((complex: { id: number; name: string } | null) => {
    setListingComplex(complex);
    setListingsOpen(true);
    setMoneyOpen(false);
    setSnap((s) => (s === "peek" ? "full" : s));
  }, []);

  const startRecommendation = useCallback(() => {
    // 예산은 서버가 /affordability 로 다시 계산한다 — 화면이 계산한 값을 보내면 진실이 두 개가 된다.
    // **다만 희망 매매가는 사용자가 정한 입력**이라 그대로 실어 보낸다(budget_override_krw).
    // 이게 없으면 슬라이더는 "저장만 되고 아무 데도 안 쓰이는 값"이 된다(PREF-1).
    // 지역은 **사용자가 고른 것을 그대로** 보낸다. 빈 배열이면 서버가 전체에서 찾는다
    // (예전엔 아예 보내지 않아 항상 수도권 전체였고, 그래서 추천이 엉뚱하게 느껴졌다).
    // "이 주변"(bbox)이 함께 있으면 서버가 **교집합**으로 좁힌다(api-spec).
    const scope: SearchScope = { regionCodes, bbox: areaBbox };
    // 화면에 적는 범위·조건은 **실제로 보낸 것**과 같아야 한다 — 그래서 같은 상태에서
    // 같은 함수로 되돌려 만든다(추측해서 다시 쓰지 않는다).
    setAppliedScope(appliedScope(scope));
    setAppliedPlan(conditionPlan(filters));
    void rec.start({
      purpose: PURPOSE,
      top_n: 10,
      // 칩이 꺼져 있으면 `use_saved_conditions:false` 가 함께 나간다(FE-4).
      // **안 보내는 것과 끄는 것은 다르다** — 안 보내면 서버가 저장된 조건으로 계속 거른다.
      ...conditionFields(filters),
      ...scopeFields(scope),
    });
  }, [areaBbox, filters, rec, regionCodes]);

  const clearArea = useCallback(() => setAreaBbox(null), []);

  const chips = filterChips(filters);
  /** 지금 누르면 어떤 조건으로 돌지(실행 전 표시). 결과가 나온 뒤에는 `appliedPlan` 이 이긴다. */
  const livePlan = useMemo(() => conditionPlan(filters), [filters]);
  const toggleChip = useCallback((id: "budget" | "area" | "built") => {
    if (id === "budget") setBudgetApplied((v) => !v);
    else setPreferApplied((v) => !v);
  }, []);

  /* ── 단지 기준 자금계획 (CR35-4) ────────────────────────────────────────
     지도·목록에서 고른 단지로 "이 집을 사려면 뭐가 필요한가"를 계산한다.

     ⚠️ **금액을 보내지 않는다.** 예전에는 지도의 `recent_price_krw`(최근 체결 1건)를
        그대로 `/affordability` 에 실어 보냈는데, 추천 카드는 같은 단지를 "창 중위를
        기준월로 환산한 추정가"로 말한다. 두 화면이 다른 금액으로 서면 사용자는 어느 쪽이
        맞는지 알 길이 없다(실측 부족액 차이 최대 3.19억). 이제 `complex_id`+`area_m2` 만
        보내고 **금액은 서버가 추천과 같은 함수로** 정한다. */
  const planComplex = useMemo(
    () => map.items.find((c) => c.id === selected) ?? null,
    [map.items, selected],
  );

  /** 어느 면적으로 물어볼 것인가 — 그리고 그 면적을 왜 골랐는지(화면이 말한다). */
  const planAreaChoice = useMemo(
    () =>
      planComplex
        ? planArea({
            priceAreaM2: planComplex.price_area_m2,
            areaMinM2: preferences.prefer?.area_min_m2,
            areaMaxM2: preferences.prefer?.area_max_m2,
          })
        : null,
    [planComplex, preferences.prefer?.area_min_m2, preferences.prefer?.area_max_m2],
  );

  /**
   * 위로 올릴 값은 **원시값으로 만든 키**로 비교한다. 지도를 다시 조회하면 같은 단지라도
   * 객체가 새로 오는데, 객체 정체성으로 비교하면 조회 때마다 자금계산이 한 번 더 나간다.
   */
  const planKey =
    planComplex && planAreaChoice
      ? `${planComplex.id}|${planAreaChoice.m2}|${planAreaChoice.basis}|${planComplex.name}|${planComplex.price_as_of ?? ""}|${planComplex.recent_price_krw === null ? "nomap" : "map"}`
      : null;

  useEffect(() => {
    if (!planKey || !planComplex || !planAreaChoice) {
      onPlanComplexChange(null);
      return;
    }
    onPlanComplexChange({
      id: planComplex.id,
      name: planComplex.name,
      area: planAreaChoice,
      asOf: planComplex.price_as_of,
      noMapPrice: planComplex.recent_price_krw === null,
    });
    return () => onPlanComplexChange(null);
    // planComplex·planAreaChoice 는 키가 같으면 내용도 같다(위 주석).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planKey, onPlanComplexChange]);

  const planBasis: PlanBasis | null = planComplex
    ? {
        kind: "complex",
        name: planComplex.name,
        // `/map/complexes` 도 `/affordability` 도 확정가를 주지 않는다 — 실거래에서
        // 유도한 값이다. 모르는 쪽을 확정으로 올리는 일은 하지 않는다.
        estimated: true,
        asOf: planComplex.price_as_of,
      }
    : targetPriceKrw !== null
      ? { kind: "manual" }
      : null;

  /**
   * 지도에 시세가 없는 단지 — **그래도 서버에는 물어본다**(실거래는 있는데 최근 1건이
   * 조건 밖일 수 있다). 서버까지 기준가를 못 만들면 그 사유는 자금계획 화면이 말한다.
   * 여기서는 서버가 계획을 만들어 주지 못했을 때만(구버전 응답 포함) 안내를 남긴다.
   */
  const planComplexNoPrice =
    planComplex &&
    planComplex.recent_price_krw === null &&
    !afford.data?.target_price &&
    !afford.data?.plan
      ? planComplex.name
      : null;

  const clearPlanComplex = useCallback(() => setSelected(null), []);

  const title = moneyOpen
    ? "내 자금"
    : listingsOpen
      ? "내 매물"
      : tab === "map"
        ? map.level === "cluster"
          ? `지역 ${map.clusters.length}곳`
          : `단지 ${map.items.length}건`
        : "AI 추천";

  /* 정렬은 목록 바로 위에 둔다. 네이티브 select 를 쓰는 이유: 키보드·스크린리더·모바일
     기본 피커가 전부 공짜로 따라오고, 직접 만든 드롭다운은 그 셋을 대개 못 만든다. */
  const sortControl =
    !moneyOpen && !listingsOpen && tab === "map" && map.level === "complex" && listItems.length > 0 ? (
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
        // 내 매물도 여기서 연다 — 조건과 같은 성격(내가 넣는 값)이고, 지도를 보는 내내
        // 접근할 수 있어야 낡은 호가를 갱신하러 돌아올 수 있다.
        onOpenListings={() => openListings(null)}
        listingsOpen={listingsOpen}
      />

      <MapView
        onBoundsChange={onBoundsChange}
        // 마커의 예산 판정은 서버가 항목별로 내린 값이다(위 mapItems 주석) — 목록 카드와 같은 값.
        items={mapItems}
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
              // 기준가는 면적별 값이다 — 어느 면적으로 물었는지 화면이 말한다(CR35-4).
              planArea={planBasis?.kind === "complex" ? planAreaChoice : null}
            />
          </div>
        ) : listingsOpen ? (
          <MyListingsScreen
            listings={listings}
            complex={listingComplex}
            onClearComplex={listingComplex ? () => setListingComplex(null) : undefined}
            onClose={() => setListingsOpen(false)}
          />
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

                  {/* 예산 기준이 **걸리지 않았거나 다른 기준으로 걸렸을 때** 말한다.
                      군집·단지 어느 단계에서도 보이도록 분기 위에 둔다(줌아웃했다고
                      조건이 사라진 것처럼 보이면 안 된다 — 서버도 군집 응답에 이 블록을
                      싣는 이유가 그것이다). 문자열은 서버가 준 사유를 손질만 해서 쓴다. */}
                  {budgetStatus.notice && (
                    <p className="app__budgetnote" role="status">
                      {budgetStatus.notice}
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
                          // 칩을 껐을 때 "예산을 못 구했다"가 아니라 "표시를 껐다"고 말한다
                          budgetDisplayOff={budgetDisplayOff}
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
                      {/* 호가는 공공 데이터에 없다 — 사용자가 직접 본 값을 넣는 유일한 입구.
                          자금계획 바로 옆에 두는 이유: 단지를 고른 그 순간이 호가를 봤을 때다. */}
                      {planComplex && (
                        <button
                          type="button"
                          className="app__planjump"
                          onClick={() =>
                            openListings({ id: planComplex.id, name: planComplex.name })
                          }
                        >
                          {planComplex.name} 호가 입력
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
                  // 예산 칩을 끄면 여기도 null 이 되어 추천 목록의 초과 표시도 함께 꺼진다 —
                  // 한 화면에서 지도는 안 붙는데 추천만 배지가 붙으면 그게 더 헷갈린다.
                  listBudgetKrw={listBudgetKrw}
                  budgetDisplayOff={budgetDisplayOff}
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
                  // 조건도 범위와 똑같이 다룬다: 실행 전엔 "지금 조건", 실행 후엔 "그때 조건".
                  conditions={livePlan}
                  appliedConditions={appliedPlan}
                  onStart={startRecommendation}
                  onCancel={rec.cancel}
                  onShowOnMap={showOnMap}
                  onEditConditions={onEditConditions}
                  // 결과가 "'내 매물'에서 직접 입력하시면 가격 축이 반영됩니다"라고 말하는
                  // 바로 그 자리에서 그 화면으로 간다(CR35-2).
                  onAddListing={openListings}
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

  /**
   * 지도에서 고른 단지(what-if). 있으면 자금계획은 이쪽을 기준으로 선다.
   * **금액이 아니라 단지**다 — 금액은 서버가 추천과 같은 함수로 정한다(CR35-4).
   */
  const [planComplex, setPlanComplex] = useState<PlanComplex | null>(null);

  /** 이번 요청의 기준. 단지가 이기고, 없으면 내가 정한 희망가, 그것도 없으면 한도만 본다. */
  const planTarget: PlanTarget | null = useMemo(
    () =>
      planComplex
        ? { kind: "complex", complexId: planComplex.id, areaM2: planComplex.area.m2 }
        : targetPriceKrw !== null
          ? { kind: "target", krw: targetPriceKrw }
          : null,
    [planComplex, targetPriceKrw],
  );

  /**
   * 자산이 없으면 계산 자체가 성립하지 않으므로 요청하지 않는다(422 를 일부러 받지 않는다).
   * 조건 화면(희망가 슬라이더 범위)도 이 결과의 `max_purchase_krw` 를 쓰기 때문에
   * 훅이 여기 있어야 한다 — Home 안에 있으면 조건 화면이 한도를 볼 수 없다.
   */
  const afford = useAffordability(status === "ready", PURPOSE, planTarget);
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
      onPlanComplexChange={setPlanComplex}
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
