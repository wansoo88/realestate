/**
 * 로그인 · 회원가입 (FE-1)
 *
 * 컨셉 "확신의 농도" + 애플 톤: iOS 설정앱식 inset grouped list.
 * 필드마다 박스를 두르지 않고 하나의 카드에 모아 헤어라인으로만 구분한다.
 * 라지 타이틀(좌측 정렬) · 폭 100% 파란 CTA(하단, 엄지 범위) · 보조 동작은 텍스트 버튼.
 * 에러는 필드 아래 작은 빨강 텍스트(모달·alert 금지, ux components.md §5.1).
 *
 * 검증 규칙은 lib/validation.ts(순수 함수, 서버 계약 복사)를 재사용한다 — 뷰에서 규칙을 새로 만들지 않는다.
 */
import { useState } from "react";
import { ApiException, api } from "../api/client";
import { NOTICE_TRUST } from "../lib/notices";
import { canSubmitPassword, isEmailShaped, passwordRules } from "../lib/validation";
import "./AuthForm.css";

type Mode = "login" | "signup";

interface Props {
  onSuccess?: () => void;
}

export function AuthForm({ onSuccess }: Props) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const rules = passwordRules(password);
  const emailOk = isEmailShaped(email);
  const pwOk = mode === "login" ? password.length > 0 : canSubmitPassword(password);
  const canSubmit = emailOk && pwOk && !busy;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "signup") {
        await api.register(email.trim(), password);
      }
      // 가입 성공 → 바로 로그인까지 이어 붙인다(components.md §5.1: 가입→자동 로그인).
      await api.login(email.trim(), password);
      onSuccess?.();
      // 성공 시엔 상위(App)가 지도로 전환하므로 busy 를 되돌릴 필요가 없다.
    } catch (err) {
      setError(messageFor(err, mode));
      setBusy(false);
    }
  }

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
  }

  const isSignup = mode === "signup";

  return (
    <main className="auth">
      <form className="auth__form" onSubmit={submit} noValidate>
        <header className="auth__header">
          <h1 className="auth__title">부동산 AI 자문</h1>
          <p className="auth__lede">
            {isSignup ? "계정을 만들고 시작하세요." : "다시 오셨네요. 로그인하세요."}
          </p>
        </header>

        {/* inset grouped list — 카드 하나에 필드를 모으고 헤어라인으로만 구분 */}
        <div className="auth__group">
          <div className="auth__row">
            <label className="auth__label" htmlFor="auth-email">
              이메일
            </label>
            <input
              id="auth-email"
              className="auth__input"
              type="email"
              inputMode="email"
              enterKeyHint="next"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-invalid={email.length > 0 && !emailOk}
              required
            />
          </div>

          <div className="auth__row">
            <label className="auth__label" htmlFor="auth-password">
              비밀번호
            </label>
            <div className="auth__pw">
              <input
                id="auth-password"
                className="auth__input"
                type={showPw ? "text" : "password"}
                enterKeyHint={isSignup ? "next" : "go"}
                autoComplete={isSignup ? "new-password" : "current-password"}
                placeholder={isSignup ? "12자 이상" : "비밀번호"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                aria-invalid={isSignup && password.length > 0 && !pwOk}
                required
              />
              <button
                type="button"
                className="auth__pw-toggle"
                aria-pressed={showPw}
                aria-label={showPw ? "비밀번호 숨기기" : "비밀번호 표시"}
                onClick={() => setShowPw((s) => !s)}
              >
                {showPw ? "숨김" : "표시"}
              </button>
            </div>
          </div>
        </div>

        {/* 가입 시에만 비밀번호 규칙을 입력 전부터 노출(색만이 아니라 텍스트로) */}
        {isSignup && (
          <ul className="auth__rules" aria-label="비밀번호 조건">
            {rules.map((r) => (
              <li
                key={r.id}
                className={`auth__rule${r.ok ? " auth__rule--ok" : ""}`}
              >
                <span className="auth__rule-mark" aria-hidden="true">
                  {r.ok ? "✓" : "○"}
                </span>
                <span>{r.label}</span>
                {r.ok && <span className="sr-only"> 충족됨</span>}
              </li>
            ))}
          </ul>
        )}

        {error && (
          <p className="auth__error" role="alert">
            {error}
          </p>
        )}

        <div className="auth__actions">
          <button type="submit" className="auth__submit" disabled={!canSubmit}>
            {busy ? "처리 중…" : isSignup ? "가입하고 시작" : "로그인"}
          </button>

          <button
            type="button"
            className="auth__switch"
            onClick={() => switchMode(isSignup ? "login" : "signup")}
          >
            {isSignup ? "이미 계정이 있어요 · 로그인" : "계정이 없어요 · 회원가입"}
          </button>

          {/* 민감정보 입력 전에 신뢰 문구를 미리 보인다(lib/notices, 규칙 5: 조용하지만 상시) */}
          <p className="auth__trust">{NOTICE_TRUST}</p>
        </div>
      </form>
    </main>
  );
}

/** 서버 오류를 사용자 문구로. 계정 존재가 새어나가지 않게 로그인 실패는 하나로 합친다. */
function messageFor(err: unknown, mode: Mode): string {
  if (err instanceof ApiException) {
    if (err.error.code === "EMAIL_TAKEN") return "이미 가입된 이메일입니다. 로그인해 주세요.";
    if (err.status === 401) return "이메일 또는 비밀번호가 올바르지 않습니다.";
    if (err.status === 422 || err.error.code === "INVALID_PARAM")
      return "입력값을 확인해 주세요. 비밀번호는 12자 이상이어야 합니다.";
    return err.error.message || "요청을 처리하지 못했습니다.";
  }
  return mode === "login"
    ? "로그인에 실패했습니다. 네트워크를 확인해 주세요."
    : "가입에 실패했습니다. 네트워크를 확인해 주세요.";
}
