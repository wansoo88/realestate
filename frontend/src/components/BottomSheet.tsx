/**
 * 바텀시트 — 3단 스냅 (peek / half / full)
 *
 * 왜 이렇게 하나: 폰에서 지도와 리스트를 나란히 놓을 공간이 없다.
 * 탭으로 전환하면 맥락이 끊긴다. 드래그로 비율을 바꾸는 게 한 화면에서 둘 다 보는 유일한 방법이다.
 * (docs/02-design/ux/README.md §3)
 */
import { useCallback, useEffect, useRef, useState } from "react";
import "./BottomSheet.css";

export type SnapPoint = "peek" | "half" | "full";

const SNAP_RATIO: Record<SnapPoint, number> = {
  peek: 0.25,
  half: 0.55,
  full: 0.92,
};

const ORDER: SnapPoint[] = ["peek", "half", "full"];

interface Props {
  snap: SnapPoint;
  onSnapChange: (s: SnapPoint) => void;
  title: string;
  /** 제목 줄 우측(정렬 선택 등). 목록의 성격을 바꾸는 조작은 목록 **바로 위**에 있어야 한다. */
  actions?: React.ReactNode;
  children: React.ReactNode;
}

function nearestSnap(ratio: number): SnapPoint {
  let best: SnapPoint = "peek";
  let bestDist = Infinity;
  for (const s of ORDER) {
    const d = Math.abs(SNAP_RATIO[s] - ratio);
    if (d < bestDist) {
      bestDist = d;
      best = s;
    }
  }
  return best;
}

export function BottomSheet({ snap, onSnapChange, title, actions, children }: Props) {
  const [dragRatio, setDragRatio] = useState<number | null>(null);
  const startY = useRef(0);
  const startRatio = useRef(0);

  const ratio = dragRatio ?? SNAP_RATIO[snap];

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      startY.current = e.clientY;
      startRatio.current = SNAP_RATIO[snap];
      setDragRatio(SNAP_RATIO[snap]);
    },
    [snap],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (dragRatio === null) return;
      const dy = startY.current - e.clientY;
      const next = startRatio.current + dy / window.innerHeight;
      setDragRatio(Math.min(0.95, Math.max(0.12, next)));
    },
    [dragRatio],
  );

  const onPointerUp = useCallback(() => {
    if (dragRatio === null) return;
    onSnapChange(nearestSnap(dragRatio));
    setDragRatio(null);
  }, [dragRatio, onSnapChange]);

  // 키보드로도 조작 가능해야 한다(접근성). 드래그만 되면 스크린리더 사용자가 못 쓴다.
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const idx = ORDER.indexOf(snap);
      if (e.key === "ArrowUp" && idx < ORDER.length - 1) {
        e.preventDefault();
        onSnapChange(ORDER[idx + 1]);
      } else if (e.key === "ArrowDown" && idx > 0) {
        e.preventDefault();
        onSnapChange(ORDER[idx - 1]);
      }
    },
    [snap, onSnapChange],
  );

  useEffect(() => {
    // 드래그 중 텍스트 선택 방지
    document.body.style.userSelect = dragRatio === null ? "" : "none";
    return () => {
      document.body.style.userSelect = "";
    };
  }, [dragRatio]);

  return (
    <section
      className="sheet"
      style={{
        height: `${ratio * 100}%`,
        // 스냅은 스프링 느낌. 드래그 중엔 손가락을 그대로 따라오도록 transition 을 끈다.
        transition: dragRatio === null ? "height 0.36s cubic-bezier(0.32, 0.72, 0, 1)" : "none",
      }}
      aria-label="매물 목록"
    >
      <div
        className="sheet__handle"
        role="slider"
        tabIndex={0}
        aria-label="목록 크기 조절"
        aria-orientation="vertical"
        aria-valuemin={0}
        aria-valuemax={2}
        aria-valuenow={ORDER.indexOf(snap)}
        aria-valuetext={{ peek: "작게", half: "중간", full: "크게" }[snap]}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onKeyDown={onKeyDown}
      >
        <div className="sheet__grip" aria-hidden="true" />
      </div>
      {/* 제목은 slider 밖에 둔다 — slider 자식은 접근성 트리에서 무시돼 스크린리더에 안 읽힌다(F-04) */}
      <div className="sheet__head">
        <h2 className="sheet__title">{title}</h2>
        {actions && <div className="sheet__actions">{actions}</div>}
      </div>
      <div className="sheet__body">{children}</div>
    </section>
  );
}
