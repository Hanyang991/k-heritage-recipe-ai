import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { Bell, Sparkles } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "./ui/popover";
import { api, NotificationItem } from "@/lib/api";
import { useAuth } from "../auth/AuthContext";

/**
 * In-app notification bell rendered in the sidebar's user row.
 *
 * Only mounted for authenticated users. On mount and when the popover opens
 * we re-fetch the list — there is no polling because the only producer of
 * notifications is the daily trend refresh job, so the freshest data the
 * user could see in one session is bounded by their click rate, not by
 * how aggressively we hit the API.
 */
export function NotificationBell() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    try {
      const res = await api.listNotifications();
      setItems(res.items);
      setUnreadCount(res.unread_count);
    } catch {
      // network blip — keep whatever we last had instead of clobbering the
      // unread badge to zero.
    }
  };

  useEffect(() => {
    if (!user) return;
    refresh();
  }, [user]);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    refresh().finally(() => setLoading(false));
  }, [open]);

  if (!user) return null;

  const handleClickItem = async (n: NotificationItem) => {
    if (!n.read_at) {
      // Optimistic
      setItems((curr) =>
        curr.map((item) =>
          item.id === n.id
            ? { ...item, read_at: new Date().toISOString() }
            : item,
        ),
      );
      setUnreadCount((c) => Math.max(0, c - 1));
      try {
        await api.markNotificationRead(n.id);
      } catch {
        // Roll back unread badge if it failed.
        await refresh();
      }
    }
    setOpen(false);
    if (n.type === "favorite_keyword_trending" && n.payload.keyword) {
      navigate("/dashboard");
    }
  };

  const handleMarkAll = async () => {
    const previous = { items, unreadCount };
    setItems((curr) =>
      curr.map((item) =>
        item.read_at ? item : { ...item, read_at: new Date().toISOString() },
      ),
    );
    setUnreadCount(0);
    try {
      await api.markAllNotificationsRead();
    } catch {
      setItems(previous.items);
      setUnreadCount(previous.unreadCount);
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={
            unreadCount > 0
              ? `알림 ${unreadCount}건 새로 도착`
              : "알림"
          }
          title="알림"
          className="relative text-[#4B5563] hover:text-[#3730A3]"
        >
          <Bell className="w-4 h-4" />
          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-[#DC2626] text-white text-[10px] font-semibold flex items-center justify-center">
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        side="top"
        className="w-80 p-0 max-h-[28rem] overflow-hidden"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#E5E7EB]">
          <div className="flex items-center gap-2">
            <Bell className="w-4 h-4 text-[#3730A3]" />
            <span className="font-semibold text-sm text-[#111827]">알림</span>
            {unreadCount > 0 && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#FEE2E2] text-[#DC2626] font-semibold">
                {unreadCount} 새 알림
              </span>
            )}
          </div>
          {unreadCount > 0 && (
            <button
              type="button"
              className="text-xs text-[#3730A3] hover:underline"
              onClick={handleMarkAll}
            >
              모두 읽음
            </button>
          )}
        </div>

        <div className="overflow-y-auto max-h-[24rem]">
          {loading && items.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-[#9CA3AF]">
              불러오는 중…
            </div>
          ) : items.length === 0 ? (
            <div className="px-4 py-10 text-center text-sm text-[#9CA3AF]">
              아직 알림이 없습니다.
              <div className="mt-2 text-xs text-[#9CA3AF]">
                즐겨찾기 키워드가 급상승하면 알려드려요.
              </div>
            </div>
          ) : (
            <ul className="divide-y divide-[#F3F4F6]">
              {items.map((n) => {
                const isUnread = !n.read_at;
                return (
                  <li key={n.id}>
                    <button
                      type="button"
                      onClick={() => handleClickItem(n)}
                      className={`w-full text-left px-4 py-3 hover:bg-[#F9FAFB] ${
                        isUnread ? "bg-[#FEF3C7]/40" : ""
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        <div
                          className={`mt-0.5 w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 ${
                            isUnread ? "bg-[#FEF3C7]" : "bg-[#F3F4F6]"
                          }`}
                        >
                          <Sparkles
                            className={`w-3.5 h-3.5 ${
                              isUnread ? "text-[#D97706]" : "text-[#9CA3AF]"
                            }`}
                          />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p
                            className={`text-sm ${
                              isUnread
                                ? "text-[#111827] font-medium"
                                : "text-[#4B5563]"
                            }`}
                          >
                            <span className="font-semibold">
                              {n.payload.keyword}
                            </span>{" "}
                            키워드가 이번 주 트렌드 상위로 진입했어요
                          </p>
                          <p className="text-xs text-[#9CA3AF] mt-0.5">
                            #{n.payload.rank}
                            {typeof n.payload.previous_rank === "number" &&
                            n.payload.previous_rank !== null
                              ? ` (지난주 #${n.payload.previous_rank})`
                              : " · 신규 진입"}
                            {typeof n.payload.change_percent === "number"
                              ? ` · ${
                                  n.payload.change_percent >= 0 ? "+" : ""
                                }${n.payload.change_percent.toFixed(1)}%`
                              : ""}
                          </p>
                          <p className="text-[10px] text-[#9CA3AF] mt-1">
                            {n.payload.week_of}
                          </p>
                        </div>
                        {isUnread && (
                          <span className="w-2 h-2 rounded-full bg-[#DC2626] flex-shrink-0 mt-2" />
                        )}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
