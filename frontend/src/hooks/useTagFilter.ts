/**
 * 특성 칩 선택 상태 — 목록마다 하나씩 갖는다.
 *
 * 왜 목록마다 따로인가: "주변 단지"와 "AI 추천"은 **다른 모집단**이다. 추천 결과에는
 * 대단지가 1건인데 주변 단지에는 12건일 수 있고, 한쪽에서 고른 칩이 다른 쪽으로
 * 따라가면 사용자는 자기가 누르지 않은 필터가 걸린 화면을 보게 된다.
 *
 * 전역 스토어를 쓰지 않는 이유도 같다 — 이 상태는 그 목록 밖에서 아무 의미가 없다.
 */
import { useCallback, useState } from "react";
import type { TagId } from "../lib/tags";

export interface TagFilter {
  tags: TagId[];
  /** 판정 불가 항목을 함께 볼 것인가. 기본 false — 확실한 것만 보여준다. */
  includeUnknown: boolean;
  toggle: (id: TagId) => void;
  clear: () => void;
  setIncludeUnknown: (on: boolean) => void;
}

export function useTagFilter(): TagFilter {
  const [tags, setTags] = useState<TagId[]>([]);
  const [includeUnknown, setIncludeUnknown] = useState(false);

  const toggle = useCallback((id: TagId) => {
    setTags((prev) => (prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]));
  }, []);

  const clear = useCallback(() => setTags([]), []);

  return { tags, includeUnknown, toggle, clear, setIncludeUnknown };
}
