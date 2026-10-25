"use server";

import { createServerApiClient } from "@/lib/api/server";
import type { InboxItem, InboxPage } from "@/lib/inbox";

export type InboxResult = { kind: "ok"; page: InboxPage } | { kind: "error" };
export type UnreadResult = { kind: "ok"; unread: number } | { kind: "error" };
export type MarkReadResult = { kind: "ok"; item: InboxItem } | { kind: "not-found" | "error" };
export type MarkAllResult = { kind: "ok"; unread: number } | { kind: "error" };

function isPage(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 1_000_000;
}

function failed(what: string, thrown: unknown): { kind: "error" } {
  console.error(`${what} failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
  return { kind: "error" };
}

/** `GET /api/v1/inbox?page=`: the caller's own items, 25 a page. */
export async function getInbox(page: unknown = 1): Promise<InboxResult> {
  if (!isPage(page)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/inbox", { params: { query: { page } } });
    if (data) return { kind: "ok", page: data };
    console.error(`inbox failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    return failed("inbox", thrown);
  }
}

/** `GET /api/v1/inbox/unread-count`, for the sidebar badge. */
export async function getInboxUnreadCount(): Promise<UnreadResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/inbox/unread-count");
    if (data) return { kind: "ok", unread: data.unread };
    console.error(`inbox unread count failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    return failed("inbox unread count", thrown);
  }
}

/** `POST /api/v1/inbox/{id}/read`. Someone else's item is 404, like an unknown one. */
export async function markInboxItemRead(id: unknown): Promise<MarkReadResult> {
  if (typeof id !== "string" || !id) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.POST("/api/v1/inbox/{notification_id}/read", {
      params: { path: { notification_id: id } },
    });
    if (data) return { kind: "ok", item: data };
    if (response.status === 404) return { kind: "not-found" };
    console.error(`inbox mark read failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    return failed("inbox mark read", thrown);
  }
}

/** `POST /api/v1/inbox/read-all`. */
export async function markAllInboxRead(): Promise<MarkAllResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.POST("/api/v1/inbox/read-all");
    if (data) return { kind: "ok", unread: data.unread };
    console.error(`inbox mark all read failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    return failed("inbox mark all read", thrown);
  }
}
