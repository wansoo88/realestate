/**
 * 관리자 — 가입 승인 화면 (ADM-1).
 *
 * 이 화면은 **관리자에게만 존재한다.** 진입점은 `useAdminUsers` 가 서버에서 200 을
 * 실제로 받았을 때만 켜지고(App.tsx), 아니면 아예 렌더되지 않는다 — 서버가 404 로
 * 숨긴 기능을 화면이 도로 알려주지 않기 위해서다(api-spec §6.2).
 *
 * 보여주는 것: 이메일 · 상태 · 신청일 · 감사 흔적. **그게 전부다.**
 * 자산·소득·해시는 서버가 주지 않고, 혹시 오더라도 lib/adminUsers 의 허용 목록이 버린다.
 * 관리자는 "이 사람을 들일지"만 정한다 — 남의 금융정보를 볼 권한은 아무에게도 없다.
 */
import { useState } from "react";
import {
  REJECT_REASON_MAX,
  STATUS_LABEL,
  formatDay,
  type AdminUserSummary,
  type StatusFilter,
} from "../lib/adminUsers";
import type { UseAdminUsers } from "../hooks/useAdminUsers";
import "./AdminScreen.css";

const FILTERS: Array<{ id: StatusFilter; label: string }> = [
  { id: "pending", label: "승인 대기" },
  { id: "approved", label: "승인됨" },
  { id: "rejected", label: "거부됨" },
  { id: "all", label: "전체" },
];

interface Props {
  admin: UseAdminUsers;
  onClose: () => void;
}

export function AdminScreen({ admin, onClose }: Props) {
  // 거부는 되돌리기 번거로우니 한 단계 확인을 둔다. 모달 대신 **인라인 폼**(ux §5.1).
  const [rejectingId, setRejectingId] = useState<number | null>(null);
  const [reason, setReason] = useState("");

  function openReject(userId: number) {
    setRejectingId(userId);
    setReason("");
  }

  async function confirmReject(userId: number) {
    await admin.reject(userId, reason.trim() === "" ? null : reason.trim());
    setRejectingId(null);
    setReason("");
  }

  return (
    <main className="admin">
      <header className="admin__header">
        <div className="admin__bar">
          <h1 className="admin__title">가입 승인</h1>
          <button type="button" className="admin__close" onClick={onClose}>
            닫기
          </button>
        </div>
        <p className="admin__lede">
          승인해야 로그인할 수 있습니다. 이 목록에는 이메일과 상태만 표시되며, 자산·소득
          정보는 관리자에게도 보이지 않습니다.
        </p>
        {admin.activeAdmins !== null && (
          <p className="admin__meta">
            승인된 관리자 <span className="num">{admin.activeAdmins}</span>명
            {admin.activeAdmins <= 1 && " · 마지막 관리자는 거부·강등할 수 없습니다"}
          </p>
        )}
      </header>

      <div className="admin__filters" role="group" aria-label="상태 필터">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            className={`admin__filter${admin.filter === f.id ? " admin__filter--on" : ""}`}
            aria-pressed={admin.filter === f.id}
            onClick={() => admin.setFilter(f.id)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* 민감 필드가 섞여 왔다면 조용히 버리지 않고 알린다 — 백엔드 회귀 신호다 */}
      {admin.droppedSensitive && (
        <p className="admin__alert" role="alert">
          서버 응답에 표시하면 안 되는 항목이 포함되어 있어 무시했습니다. 백엔드 응답
          스키마를 확인해 주세요.
        </p>
      )}

      {admin.error && (
        <p className="admin__alert" role="alert">
          {admin.error}{" "}
          <button type="button" className="admin__link" onClick={() => void admin.reload()}>
            다시 시도
          </button>
        </p>
      )}

      {admin.actionError && (
        <p className="admin__alert" role="alert">
          {admin.actionError}
        </p>
      )}

      {admin.actionDone && (
        <p className="admin__done" role="status">
          {admin.actionDone}
        </p>
      )}

      {admin.loading && (
        <p className="admin__status" role="status">
          불러오는 중…
        </p>
      )}

      {!admin.loading && admin.users.length === 0 && !admin.error && (
        <p className="admin__status">
          {admin.filter === "pending"
            ? "승인 대기 중인 신청이 없습니다."
            : "해당하는 사용자가 없습니다."}
        </p>
      )}

      <ul className="admin__list">
        {admin.users.map((user) => (
          <UserRow
            key={user.id}
            user={user}
            busy={admin.busyUserId === user.id}
            rejecting={rejectingId === user.id}
            reason={reason}
            onReasonChange={setReason}
            onApprove={() => void admin.approve(user.id)}
            onOpenReject={() => openReject(user.id)}
            onCancelReject={() => setRejectingId(null)}
            onConfirmReject={() => void confirmReject(user.id)}
          />
        ))}
      </ul>
    </main>
  );
}

interface RowProps {
  user: AdminUserSummary;
  busy: boolean;
  rejecting: boolean;
  reason: string;
  onReasonChange: (v: string) => void;
  onApprove: () => void;
  onOpenReject: () => void;
  onCancelReject: () => void;
  onConfirmReject: () => void;
}

function UserRow({
  user,
  busy,
  rejecting,
  reason,
  onReasonChange,
  onApprove,
  onOpenReject,
  onCancelReject,
  onConfirmReject,
}: RowProps) {
  // 이미 그 상태인 동작은 숨긴다. 거부는 **승인 회수**로도 쓰이므로 라벨이 달라진다(§6.4).
  const canApprove = user.status !== "approved";
  const canReject = user.status !== "rejected";
  const rejectLabel = user.status === "approved" ? "승인 회수" : "거부";
  const reasonId = `admin-reason-${user.id}`;

  return (
    <li className="admin__row">
      <div className="admin__who">
        <span className="admin__email">{user.email}</span>
        <span className={`badge admin__badge admin__badge--${user.status}`}>
          {STATUS_LABEL[user.status]}
        </span>
        {user.is_admin && <span className="badge admin__badge">관리자</span>}
      </div>

      <p className="admin__when">
        신청 {formatDay(user.created_at)}
        {user.status_changed_at && ` · 변경 ${formatDay(user.status_changed_at)}`}
      </p>
      {user.status_reason && <p className="admin__reason">사유: {user.status_reason}</p>}

      {!rejecting && (
        <div className="admin__actions">
          {canApprove && (
            <button
              type="button"
              className="admin__approve"
              aria-label={`${user.email} 승인`}
              disabled={busy}
              onClick={onApprove}
            >
              {busy ? "처리 중…" : "승인"}
            </button>
          )}
          {canReject && (
            <button
              type="button"
              className="admin__reject"
              aria-label={`${user.email} ${rejectLabel}`}
              disabled={busy}
              onClick={onOpenReject}
            >
              {rejectLabel}
            </button>
          )}
        </div>
      )}

      {rejecting && (
        <div className="admin__confirm">
          <label className="admin__label" htmlFor={reasonId}>
            {rejectLabel} 사유 (선택 · 감사 기록에만 남습니다)
          </label>
          <textarea
            id={reasonId}
            className="admin__textarea"
            rows={2}
            maxLength={REJECT_REASON_MAX}
            value={reason}
            onChange={(e) => onReasonChange(e.target.value)}
            placeholder="예: 본인 확인 불가"
          />
          <div className="admin__actions">
            <button
              type="button"
              className="admin__reject admin__reject--confirm"
              aria-label={`${user.email} ${rejectLabel} 확정`}
              disabled={busy}
              onClick={onConfirmReject}
            >
              {busy ? "처리 중…" : `${rejectLabel} 확정`}
            </button>
            <button type="button" className="admin__cancel" disabled={busy} onClick={onCancelReject}>
              취소
            </button>
          </div>
        </div>
      )}
    </li>
  );
}
