/**
 * 폼 검증 — **순수 함수**. 뷰에 의존하지 않으므로 RN 에서 그대로 쓴다(components.md §1).
 *
 * 서버가 진실이다. 여기 규칙은 서버 계약(`backend/app/api/schemas.py::RegisterIn`)을
 * **그대로 복사**한 것이지 새로 만든 것이 아니다. 서버보다 엄격하게 막으면
 * 서버는 받아주는 비밀번호를 화면이 거부하는 상태가 된다.
 */

/** 서버 `Field(min_length=12, max_length=256)` 와 같은 값. */
export const PASSWORD_MIN = 12;
export const PASSWORD_MAX = 256;

export interface PasswordRule {
  id: string;
  label: string;
  ok: boolean;
  /** false 면 권장 사항 — 충족하지 않아도 가입을 막지 않는다. */
  required: boolean;
}

/** 문자 종류(영문·숫자·기호) 가짓수. */
function charClassCount(pw: string): number {
  let n = 0;
  if (/[A-Za-z]/.test(pw)) n += 1;
  if (/\d/.test(pw)) n += 1;
  if (/[^A-Za-z0-9]/.test(pw)) n += 1;
  return n;
}

/**
 * 비밀번호 규칙과 충족 여부.
 *
 * 입력 **전부터** 보여주기 위해 빈 문자열도 정상 입력으로 받는다 —
 * 제출 후 빨간 글씨로 알려주는 건 최악의 순서다(wireframes/login.html).
 */
export function passwordRules(pw: string): PasswordRule[] {
  return [
    {
      id: "length",
      label: `${PASSWORD_MIN}자 이상`,
      ok: pw.length >= PASSWORD_MIN && pw.length <= PASSWORD_MAX,
      required: true,
    },
    {
      id: "classes",
      label: "영문·숫자·기호 중 2종 이상 (권장)",
      ok: charClassCount(pw) >= 2,
      required: false,
    },
  ];
}

/** 가입 버튼을 눌러도 되는가 — **필수 규칙만** 본다. */
export function canSubmitPassword(pw: string): boolean {
  return passwordRules(pw).every((r) => !r.required || r.ok);
}

/**
 * 이메일 형식 — 최소한만 본다.
 *
 * 정규식으로 RFC 5322 를 흉내 내면 멀쩡한 주소를 거부한다.
 * 최종 판정은 서버(`EmailStr`)가 한다.
 */
export function isEmailShaped(email: string): boolean {
  const v = email.trim();
  return v.length >= 3 && v.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
}
