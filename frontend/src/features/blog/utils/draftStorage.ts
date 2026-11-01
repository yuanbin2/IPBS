import type { BlogDraft } from "../types";
import { normalizeTagList } from "./tagInput";

const DRAFT_PREFIX = "blogWriterDraft:v2:";
const SESSION_PREFIX = "blogWriterSession:v2:";
const DRAFT_VERSION = 2;
export const BLOG_DRAFT_TTL_MS = 30 * 24 * 60 * 60 * 1000;

export interface DraftOwner {
  actor: string;
  workspace: string;
}

export interface WriterContext {
  kind: "new" | "article";
  id: string;
  slug?: string;
  open: boolean;
}

interface StoredDraft {
  version: number;
  updatedAt: number;
  writerTabId: string;
  draft: BlogDraft;
}

function encode(value: string): string {
  return encodeURIComponent(value.trim());
}

export function getDraftOwner(actor: string | undefined, workspace: string | undefined): DraftOwner | null {
  if (!actor || actor === "anonymous" || !workspace) return null;
  return { actor, workspace };
}

function ownerKey(owner: DraftOwner): string {
  return `${encode(owner.actor)}:${encode(owner.workspace)}`;
}

export function getWriterContextStorageKey(owner: DraftOwner, context: WriterContext): string {
  const resource = context.kind === "article" ? `article:${context.id}` : `draft:${context.id}`;
  return `${DRAFT_PREFIX}${ownerKey(owner)}:${encode(resource)}`;
}

export function getWriterSessionStorageKey(owner: DraftOwner): string {
  return `${SESSION_PREFIX}${ownerKey(owner)}`;
}

export function getVditorCacheId(owner: DraftOwner, context: WriterContext): string {
  // Vditor expects a compact id. The full key stays in our cache record; hash the
  // owner/resource tuple so the editor's own cache is isolated by the same scope.
  const input = getWriterContextStorageKey(owner, context);
  let hash = 2166136261;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `blog-v2-${(hash >>> 0).toString(16)}`;
}

export function saveWriterContext(owner: DraftOwner, context: WriterContext): void {
  sessionStorage.setItem(getWriterSessionStorageKey(owner), JSON.stringify(context));
}

export function readWriterContext(owner: DraftOwner): WriterContext | null {
  const raw = sessionStorage.getItem(getWriterSessionStorageKey(owner));
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as WriterContext;
    if (
      (parsed.kind !== "new" && parsed.kind !== "article") ||
      typeof parsed.id !== "string" ||
      !parsed.id ||
      typeof parsed.open !== "boolean" ||
      (parsed.kind === "article" && typeof parsed.slug !== "string")
    ) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function saveWriterDraft(
  owner: DraftOwner,
  context: WriterContext,
  draft: BlogDraft,
  writerTabId: string,
  now = Date.now(),
): void {
  const value: StoredDraft = { version: DRAFT_VERSION, updatedAt: now, writerTabId, draft: { ...draft } };
  localStorage.setItem(getWriterContextStorageKey(owner, context), JSON.stringify(value));
}

export function readWriterDraft(
  owner: DraftOwner,
  context: WriterContext,
  now = Date.now(),
): StoredDraft | null {
  const key = getWriterContextStorageKey(owner, context);
  const raw = localStorage.getItem(key);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as StoredDraft;
    if (parsed.version !== DRAFT_VERSION || !parsed.draft || typeof parsed.updatedAt !== "number") {
      return null;
    }
    if (now - parsed.updatedAt > BLOG_DRAFT_TTL_MS) {
      localStorage.removeItem(key);
      return null;
    }
    // 旧版草稿把 tags 存成逗号分隔字符串；这里统一规整成数组，
    // 让「中文逗号被整串当成一个标签」的历史数据在下次恢复时自动修正。
    parsed.draft.tags = normalizeTagList(parsed.draft.tags);
    return parsed;
  } catch {
    localStorage.removeItem(key);
    return null;
  }
}

export function removeWriterDraft(owner: DraftOwner, context: WriterContext): void {
  localStorage.removeItem(getWriterContextStorageKey(owner, context));
}

export function getDraftCacheStatus(error: unknown): string {
  return error instanceof DOMException && error.name === "QuotaExceededError"
    ? "本地空间不足，草稿未能自动保存；请复制正文后再继续。"
    : "浏览器禁止本地存储，草稿未能自动保存；请复制正文后再继续。";
}
