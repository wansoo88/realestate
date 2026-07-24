/**
 * 지도 홈 — 이 앱의 메인 화면.
 *
 * 모바일 퍼스트: 지도 위에 바텀시트가 얹히고, 사용자가 드래그로 비율을 정한다.
 * (docs/02-design/ux/README.md §3)
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiException, api, type ClusterItem, type ComplexItem } from "./api/client";
import { BottomSheet, type SnapPoint } from "./components/BottomSheet";
import { ComplexCard } from "./components/ComplexCard";
import { MapView } from "./components/MapView";
import { formatKrwShort } from "./lib/format";
import "./App.css";

type Level = "complex" | "cluster" | null;

export default function App() {
  const [items, setItems] = useState<ComplexItem[]>([]);
  const [clusters, setClusters] = useState<ClusterItem[]>([]);
  const [level, setLevel] = useState<Level>(null);
  const [note, setNote] = useState<string>("");
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
          setNote(res.note);
        } else {
          setClusters(res.items);
          setItems([]);
          setNote("");
        }
      } catch (e) {
        const msg =
          e instanceof ApiException
            ? e.error.code === "UNAUTHORIZED"
              ? "로그인이 필요합니다."
              : e.error.message
            : "네트워크 오류가 발생했습니다.";
        setError(msg);
      } finally {
        setLoading(false);
      }
    }, 350);
  }, []);

  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);

  //  지도를 움직이면 시트를 내려 지도가 가려지지 않게 한다 (ux §3)
  const onBoundsChange = useCallback(
    (bbox: string, zoom: number) => {
      setSnap((s) => (s === "full" ? "half" : s));
      fetchArea(bbox, zoom);
    },
    [fetchArea],
  );

  const title =
    level === "cluster"
      ? `지역 ${clusters.length}곳`
      : `매물 ${items.length}건`;

  return (
    <main className="app">
      <MapView onBoundsChange={onBoundsChange} />

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
                  <span>{c.region_code}</span>
                  <span className="num">{c.count}개 단지</span>
                  <span className="num estimated">
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
                onSelect={setSelected}
              />
            ))}
            {note && <p className="app__note">{note}</p>}
          </>
        )}

        <footer className="app__disclaimer">
          투자 권유가 아니며 개인 판단을 돕는 참고 자료입니다.
        </footer>
      </BottomSheet>
    </main>
  );
}
