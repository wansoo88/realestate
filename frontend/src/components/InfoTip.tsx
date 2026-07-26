/**
 * 설명 토글 — 직접 만든 "툴팁".
 *
 * 왜 진짜 tooltip 이 아닌가
 * -------------------------
 * `role="tooltip"` + hover 는 **터치 기기에서 아예 뜨지 않는다.** 이 앱은 모바일 퍼스트다.
 * 그래서 hover 가 아니라 **누르면 열리는 disclosure**(aria-expanded/aria-controls)로 만든다 —
 * 마우스·터치·키보드가 전부 같은 방식으로 열고, 스크린리더도 "확장 가능"으로 읽는다.
 *
 * ⚠️ 열어야만 보이는 곳에 **꼭 필요한 정보를 두지 않는다.** 한 줄 요약은 항상 화면에 있고
 *    (호출부가 렌더한다), 여기에는 더 긴 배경 설명만 넣는다. 열지 않아도 뜻을 알 수 있어야 한다.
 *
 * CSP: 외부 툴팁 라이브러리·아이콘 폰트를 쓸 수 없다(default-src 'self'). 아이콘은 인라인 SVG.
 */
import { useId, useState } from "react";
import "./InfoTip.css";

interface Props {
  /** 무엇에 대한 설명인지 — 버튼 접근명에 들어간다("가격 설명 보기"). */
  label: string;
  children: React.ReactNode;
}

export function InfoTip({ label, children }: Props) {
  const [open, setOpen] = useState(false);
  const id = useId();

  return (
    <span className="tip">
      <button
        type="button"
        className="tip__btn"
        aria-expanded={open}
        aria-controls={id}
        // 아이콘만 있는 버튼이라 접근명을 직접 준다(SVG 는 aria-hidden).
        aria-label={`${label} 설명 ${open ? "닫기" : "보기"}`}
        onClick={() => setOpen((v) => !v)}
      >
        {/* 인라인 SVG — 아이콘 라이브러리를 쓸 수 없다(CSP). 원 + i */}
        <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
          <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.3" />
          <circle cx="8" cy="4.6" r="0.95" fill="currentColor" />
          <path
            d="M8 7.2v4.6"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            fill="none"
          />
        </svg>
      </button>
      {/* hidden 이 아니라 조건부 렌더 — 닫힌 설명이 접근성 트리에 유령으로 남지 않게. */}
      {open && (
        <span className="tip__body" id={id} role="note">
          {children}
        </span>
      )}
    </span>
  );
}
