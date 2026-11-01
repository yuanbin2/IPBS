/** Shared matching of image references inside imported notes to local files. */

export function cleanImagePath(value: string): string {
  const path = value.split(/[?#]/, 1)[0].replace(/\\/g, "/").replace(/^\.\//, "");
  try {
    return decodeURIComponent(path);
  } catch {
    return path;
  }
}

/**
 * Match one image reference from imported content to a user-provided local
 * file, first by path, then by unique basename.
 */
export function matchImageFile(original: string, files: File[]): File | null {
  const path = cleanImagePath(original);
  const exactPath = files.filter((file) => {
    const selectedPath = cleanImagePath(file.webkitRelativePath || file.name);
    return selectedPath === path || selectedPath.endsWith(`/${path}`);
  });
  if (exactPath.length === 1) return exactPath[0];
  if (exactPath.length > 1) return null;
  const basename = path.split("/").pop();
  const sameName = files.filter((file) => file.name === basename);
  return sameName.length === 1 ? sameName[0] : null;
}

/** Image references inside a Markdown note: !\[alt\](src "title") */
export interface MarkdownImageRef {
  reference: string;
  remote: boolean;
  alt: string;
  /** 原始完整 Markdown 片段（如 `![](a.png)`、`![t](u "x")`），改写时精确整段替换，
   * 避免用重构的 `![alt](ref)` 匹配（空 alt/标题变体会失配）。 */
  token: string;
}

export function findMarkdownImages(markdown: string): MarkdownImageRef[] {
  const seen = new Set<string>();
  const refs: MarkdownImageRef[] = [];
  const pattern = /!\[([^\]\n]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(markdown)) !== null) {
    const [, alt, source] = match;
    if (seen.has(source) || seen.has(match[0])) continue;
    seen.add(source);
    seen.add(match[0]);
    const remote = /^https?:\/\//i.test(source);
    refs.push({ reference: source, remote, alt: alt || "图片", token: match[0] });
  }
  return refs;
}

/** 导入前的图片规划结果：三类互不重叠，覆盖全部引用。 */
export interface MarkdownImportMatch {
  reference: string;
  remote: boolean;
  alt: string;
  token: string;
  file: File;
}

export interface MarkdownImportPlan {
  /** 已匹配到本地文件的引用（含远程引用被本地文件顶替的情况），上传后改写。 */
  matched: MarkdownImportMatch[];
  /** 未被本地文件顶替、且允许服务器抓取的远程引用。 */
  remoteUnmatched: Array<{ reference: string; alt: string; token: string }>;
  /** 既没有本地文件、又不满足抓取条件的引用，正文保留原地址。 */
  unmatched: Array<{ reference: string; alt: string }>;
}

/** 把导入文档里的图片引用按“本地文件匹配 → 远程抓取 → 保留原地址”分派。 */
export function planMarkdownImageImport(
  refs: MarkdownImageRef[],
  files: File[],
  options: { fetchRemote: boolean; maxRemote?: number },
): MarkdownImportPlan {
  const maxRemote = Math.max(0, options.maxRemote ?? 20);
  const plan: MarkdownImportPlan = { matched: [], remoteUnmatched: [], unmatched: [] };
  let remoteBudget = maxRemote;
  for (const ref of refs) {
    const file = files.length ? matchImageFile(ref.reference, files) : null;
    if (file) {
      plan.matched.push({ reference: ref.reference, remote: ref.remote, alt: ref.alt, token: ref.token, file });
      continue;
    }
    if (ref.remote && options.fetchRemote && remoteBudget > 0) {
      remoteBudget -= 1;
      plan.remoteUnmatched.push({ reference: ref.reference, alt: ref.alt, token: ref.token });
      continue;
    }
    plan.unmatched.push({ reference: ref.reference, alt: ref.alt });
  }
  return plan;
}
