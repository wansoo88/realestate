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
import { useCallback, useMemo, useState } from "react";
import { logout, type Preferences, type Profile } from "./api/client";
import { AdminScreen } from "./components/AdminScreen";
import { AffordabilityPanel } from "./components/AffordabilityPanel";
import { AuthForm } from "./components/AuthForm";
import { BottomSheet, type SnapPoint } from "./components/BottomSheet";
import { ComplexCard } from "./components/ComplexCard";
import { ConditionsScreen } from "./components/ConditionsScreen";
import { FilterRail } from "./components/FilterRail";
import { MapView } from "./components/MapView";
import { RecommendPanel } from "./components/RecommendPanel";
import { useAdminUsers } from "./hooks/useAdminUsers";
import { useAffordability, type Purpose } from "./hooks/useAffordability";
import { useAuth } from "./hooks/useAuth";
import { useMapArea } from "./hooks/useMapArea";
import { useProfile } from "./hooks/useProfile";
import { useRecommendation } from "./hooks/useRecommendation";
import { SORT_OPTIONS, isSortKey, sortComplexes, type SortKey } from "./lib/complexSort";
import { formatKrwShort } from "./lib/format";
import { filterChips, type MapFilterState } from "./lib/mapFilters";
import { NOTICE_NOT_ADVICE, NOTICE_TRADE_DELAY } from "./lib/notices";
import "./App.css";

type Tab = "map" | "money" | "advice";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "map", label: "주변 단지" },
  { id: "money", label: "내 자금" },
  { id: "advice", label: "AI 추천" },
];

interface HomeProps {
  preferences: Preferences;
  onEditConditions: () => void;
  /** 관리자 전용 진입점. 관리자가 아니면 **null** 이라 DOM 에 존재하지 않는다. */
  adminEntry?: React.ReactNode;
}

export function Home({ preferences, onEditConditions, adminEntry }: HomeProps) {
  const [tab, setTab] = useState<Tab>("map");
  const [snap, setSnap] = useState<SnapPoint>("peek");
  const [selected, setSelected] = useState<number | null>(null);
  /** 목록에서 가리키는 중인 단지 — 지도 마커를 들어올린다(선택과 다르다: 지도를 움직이지 않는다). */
  const [hovered, setHovered] = useState<number | null>(null);
  const [sort, setSort] = useState<SortKey>("default");
  /** AI 추천을 돌릴 시군구(5자리). 빈 배열 = 수도권 전체 — 그 사실은 RegionPicker 가 화면에 적는다. */
  const [regionCodes, setRegionCodes] = useState<string[]>([]);
  const [purpose] = useState<Purpose>("live");

  // 필터 스위치 — 기본은 켜짐. 끌 수 있어야 "왜 안 보이지?"에 사용자가 스스로 답한다.
  const [budgetApplied, setBudgetApplied] = useState(true);
  const [preferApplied, setPreferApplied] = useState(true);

  const afford = useAffordability(true, purpose);
  const budgetKrw = afford.data?.max_purchase_krw ?? null;

  const filters: MapFilterState = useMemo(
    () => ({ budgetKrw, budgetApplied, prefer: preferences.prefer ?? null, preferApplied }),
    [budgetKrw, budgetApplied, preferences.prefer, preferApplied],
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
    setSelected(id);
    setSnap("half");
  }, []);

  const startRecommendation = useCallback(() => {
    // 예산은 서버가 /affordability 로 다시 계산한다 — 화면이 계산한 값을 보내면 진실이 두 개가 된다.
    // 지역은 **사용자가 고른 것을 그대로** 보낸다. 빈 배열이면 서버가 전체에서 찾는다
    // (예전엔 아예 보내지 않아 항상 수도권 전체였고, 그래서 추천이 엉뚱하게 느껴졌다).
    void rec.start({ purpose, top_n: 10, region_codes: regionCodes });
  }, [purpose, rec, regionCodes]);

  const chips = filterChips(filters);
  const toggleChip = useCallback((id: "budget" | "area" | "built") => {
    if (id === "budget") setBudgetApplied((v) => !v);
    else setPreferApplied((v) => !v);
  }, []);

  const title =
    tab === "map"
      ? map.level === "cluster"
        ? `지역 ${map.clusters.length}곳`
        : `단지 ${map.items.length}건`
      : tab === "money"
        ? "내 자금"
        : "AI 추천";

  /* 정렬은 목록 바로 위에 둔다. 네이티브 select 를 쓰는 이유: 키보드·스크린리더·모바일
     기본 피커가 전부 공짜로 따라오고, 직접 만든 드롭다운은 그 셋을 대개 못 만든다. */
  const sortControl =
    tab === "map" && map.level === "complex" && listItems.length > 0 ? (
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

      {/* 좌상단(폰) · 좌측 패널(데스크톱) — 조건은 지도를 보는 내내 보이고 고칠 수 있어야 한다 */}
      <FilterRail chips={chips} onToggle={toggleChip} onEdit={onEditConditions} />

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
                  {listItems.map((item) => (
                    <ComplexCard
                      key={item.id}
                      item={item}
                      selected={selected === item.id}
                      rank={rankById[item.id]}
                      onSelect={handleSelect}
                      onHover={setHovered}
                    />
                  ))}
                </>
              )}
            </>
          )}

          {tab === "money" && (
            <AffordabilityPanel
              data={afford.data}
              loading={afford.loading}
              error={afford.error}
              needsProfile={afford.needsProfile}
              onEditConditions={onEditConditions}
            />
          )}

          {tab === "advice" && (
            <RecommendPanel
              phase={rec.phase}
              job={rec.job}
              error={rec.error}
              budgetKrw={budgetKrw}
              regionCodes={regionCodes}
              onRegionsChange={setRegionCodes}
              onStart={startRecommendation}
              onCancel={rec.cancel}
              onShowOnMap={showOnMap}
              onEditConditions={onEditConditions}
            />
          )}
        </div>

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
        />
      </>
    );
  }

  return (
    <Home
      preferences={preferences}
      onEditConditions={() => setEditing(true)}
      adminEntry={adminEntry}
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
