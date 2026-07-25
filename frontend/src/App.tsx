/**
 * 지도 홈 — 이 앱의 메인 화면. 컨셉 "확신의 농도": 지도가 주인공, UI 는 양보한다.
 *
 * 미로그인이면 로그인 게이트(AuthForm)로 막는다 — 개인 자산 기반 서비스라 공개 화면이 없다.
 * 401 로 토큰이 폐기되면 useAuth 가 이를 듣고 자동으로 게이트로 되돌린다(FE-1 §3).
 * 지도 위에 바텀시트가 얹히고, 사용자가 드래그로 비율을 정한다(docs/02-design/ux/README.md §3).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiException, api, logout, type ClusterItem, type ComplexItem } from "./api/client";
import { AuthForm } from "./components/AuthForm";
import { BottomSheet, type SnapPoint } from "./components/BottomSheet";
import { ComplexCard } from "./components/ComplexCard";
import { MapView } from "./components/MapView";
import { useAuth } from "./hooks/useAuth";
import { formatKrwShort } from "./lib/format";
import { NOTICE_NOT_ADVICE, NOTICE_TRADE_DELAY } from "./lib/notices";
import "./App.css";

type Level = "complex" | "cluster" | null;

function MapHome() {
  const [items, setItems] = useState<ComplexItem[]>([]);
  const [clusters, setClusters] = useState<ClusterItem[]>([]);
  const [level, setLevel] = useState<Level>(null);
  const [snap, setSnap] = useState<SnapPoint>("peek");
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  //  지도를 움직일 때마다 요청이 나가면 서버가 죽는다. 마지막 이동만 보낸다.
  const timer = useRef<number | null>(null);

  const fetchArea = useCallback((bbox: string, zoom: number) => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await api.mapComplexes({ bbox, zoom });
        setLevel(res.level);
        if (res.level === "complex") {
          setItems(res.items);
          setClusters([]);
        } else {
          setClusters(res.items);
          setItems([]);
        }
      } catch (e) {
        // 401 은 client.ts 가 로그아웃으로 방송하므로 여기선 게이트 전환을 신경 쓸 필요가 없다.
        const msg =
          e instanceof ApiException
            ? e.error.code === "UNAUTHORIZED"
              ? "세션이 만료되었습니다. 다시 로그인해 주세요."
              : e.error.message
            : "네트워크 오류가 발생했습니다.";
        setError(msg);
      } finally {
        setLoading(false);
      }
    }, 350);
  }, []);

  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );

  //  지도를 움직이면 시트를 내려 지도가 가려지지 않게 한다 (ux §3)
  const onBoundsChange = useCallback(
    (bbox: string, zoom: number) => {
      setSnap((s) => (s === "full" ? "half" : s));
      fetchArea(bbox, zoom);
    },
    [fetchArea],
  );

  //  마커/카드 선택 시 서로 동기화한다. 접혀 있으면(peek) 카드가 보이도록 시트를 반쯤 올린다.
  const handleSelect = useCallback((id: number) => {
    setSelected(id);
    setSnap((s) => (s === "peek" ? "half" : s));
  }, []);

  const title = level === "cluster" ? `지역 ${clusters.length}곳` : `매물 ${items.length}건`;

  return (
    <main className="app">
      <MapView
        onBoundsChange={onBoundsChange}
        items={items}
        clusters={clusters}
        selectedId={selected}
        onSelect={handleSelect}
      />

      <BottomSheet snap={snap} onSnapChange={setSnap} title={title}>
        {error && (
          <p className="app__error" role="alert">
            {error}
          </p>
        )}

        {loading && <p className="app__status">불러오는 중…</p>}

        {!loading && level === "cluster" && (
          <>
            <p className="app__hint">지도를 확대하면 개별 단지가 표시됩니다.</p>
            <ul className="app__clusters">
              {clusters.map((c) => (
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

        {!loading && level === "complex" && (
          <>
            {items.length === 0 && (
              <p className="app__status">
                이 범위에 조건에 맞는 단지가 없습니다. 지도를 옮기거나 조건을 넓혀보세요.
              </p>
            )}
            {items.map((item) => (
              <ComplexCard
                key={item.id}
                item={item}
                selected={selected === item.id}
                onSelect={handleSelect}
              />
            ))}
          </>
        )}

        {/* 고지는 조용하지만 사라지지 않게 상시 노출한다(규칙 5, lib/notices) */}
        <footer className="app__foot">
          {level && <p className="app__note">{NOTICE_TRADE_DELAY}</p>}
          <p className="app__disclaimer">{NOTICE_NOT_ADVICE}</p>
          {/* 로그아웃은 서버 호출(쿠키 삭제)까지 하므로 비동기다. 실패해도 client 가 로컬 세션은 비운다. */}
          <button type="button" className="app__logout" onClick={() => void logout()}>
            로그아웃
          </button>
        </footer>
      </BottomSheet>
    </main>
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
  return <MapHome />;
}
