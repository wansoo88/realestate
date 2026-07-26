/**
 * 로그인 문구 규약 테스트.
 *
 * 여기서 지키는 건 UX 가 아니라 **계정 열거 방지**(SR10-1)다.
 * 서버가 401 의 본문·상태·응답시간까지 동일하게 맞춰 놓았는데 화면이 문구를 갈라 놓으면
 * 로그인 폼이 "이 이메일 가입돼 있나요?" 조회기가 된다.
 */
import { describe, expect, it } from "vitest";
import { ApiException } from "../api/client";
import {
  LOGIN_FAILED_MESSAGE,
  approvalBanner,
  bannerFromNotice,
  loginFeedback,
  registerErrorMessage,
  registerSubmittedBanner,
} from "./authMessages";

describe("401 — 상태별로 문구가 갈리지 않는다", () => {
  it("서버가 어떤 code·message 를 보내도 401 이면 문구가 같다", () => {
    const payloads = [
      { code: "UNAUTHORIZED", message: "이메일 또는 비밀번호가 올바르지 않습니다" },
      // ↓ 백엔드가 실수로 친절해진 경우까지 화면에서 막는다
      { code: "USER_NOT_FOUND", message: "가입되지 않은 이메일입니다" },
      { code: "BAD_PASSWORD", message: "비밀번호가 틀렸습니다" },
      { code: "PENDING_APPROVAL", message: "승인 대기 중" }, // 401 이면 코드도 무시한다
      { code: "", message: "" },
    ];

    const rendered = payloads.map((p) => loginFeedback(new ApiException(401, p)));

    for (const feedback of rendered) {
      expect(feedback).toEqual({ kind: "error", message: LOGIN_FAILED_MESSAGE });
    }
    // 서로 다른 응답이 화면에서는 **구분되지 않는다**
    expect(new Set(rendered.map((f) => JSON.stringify(f))).size).toBe(1);
  });

  it("401 은 승인 배너로 승격되지 않는다(상태를 알려주지 않는다)", () => {
    const feedback = loginFeedback(
      new ApiException(401, { code: "ACCOUNT_REJECTED", message: "거부됨" }),
    );
    expect(feedback.kind).toBe("error");
  });
});

describe("403 — 승인 상태만 알려준다", () => {
  it("PENDING_APPROVAL 은 승인 대기 안내가 된다", () => {
    const feedback = loginFeedback(
      new ApiException(403, { code: "PENDING_APPROVAL", message: "관리자 승인 대기 중입니다" }),
    );
    expect(feedback.kind).toBe("banner");
    if (feedback.kind !== "banner") return;
    expect(feedback.banner.tone).toBe("pending");
    expect(feedback.banner.title).toContain("승인 대기");
  });

  it("ACCOUNT_REJECTED 는 거부 안내가 되고, 사유가 오면 함께 보인다", () => {
    const feedback = loginFeedback(
      new ApiException(403, {
        code: "ACCOUNT_REJECTED",
        message: "가입이 승인되지 않았습니다",
        reason: "본인 확인 불가",
      }),
    );
    expect(feedback.kind).toBe("banner");
    if (feedback.kind !== "banner") return;
    expect(feedback.banner.tone).toBe("rejected");
    expect(feedback.banner.title).toContain("거부");
    expect(feedback.banner.body).toContain("본인 확인 불가");
  });

  it("승인과 무관한 403(CSRF)은 배너가 아니라 일반 오류다", () => {
    const feedback = loginFeedback(
      new ApiException(403, { code: "CSRF_HEADER_REQUIRED", message: "헤더가 필요합니다" }),
    );
    expect(feedback.kind).toBe("error");
  });

  it("서버 사유가 지나치게 길면 잘라서 싣는다(레이아웃·과다 노출 방지)", () => {
    const banner = approvalBanner("ACCOUNT_REJECTED", "가".repeat(500));
    expect(banner.body.length).toBeLessThan(300);
    expect(banner.body).toContain("…");
  });
});

describe("세션 도중 회수", () => {
  it("client 가 남긴 안내를 그대로 배너로 잇는다", () => {
    const banner = bannerFromNotice({ code: "PENDING_APPROVAL", message: "…", reason: null });
    expect(banner?.title).toContain("승인 대기");
    expect(bannerFromNotice(null)).toBeNull();
  });
});

describe("가입", () => {
  it("EMAIL_TAKEN 은 재신청을 막기 위해 알려주되 승인 여부는 말하지 않는다", () => {
    const msg = registerErrorMessage(
      new ApiException(409, { code: "EMAIL_TAKEN", message: "이미 있음" }),
    );
    expect(msg).toContain("이미");
    expect(msg).not.toContain("승인됨");
  });

  it("접수 배너는 서버 문구를 그대로 쓰고, 없으면 기본 문구로 채운다", () => {
    expect(registerSubmittedBanner("관리자 승인 후 로그인할 수 있습니다.").body).toBe(
      "관리자 승인 후 로그인할 수 있습니다.",
    );
    expect(registerSubmittedBanner(null).body).toContain("관리자 승인");
  });

  it("네트워크 오류는 서버 응답과 구분되는 문구를 준다", () => {
    expect(registerErrorMessage(new Error("boom"))).toContain("네트워크");
  });
});
