/**
 * 判断某个路由是否应当「脱离应用外壳（AppShell）」单独渲染。
 *
 * 背景：标记了 `meta.public` 的页面默认不套 AppShell，目的是让未登录访客看到
 * 一个干净的公开展示页（无侧边导航、无后台入口）。
 *
 * 但 `/blog` 系列（博客首页、领域目录、领域详情）对**已登录**用户来说是站内页面。
 * 一旦它们脱离外壳，左侧「概览 / 博客 / 知识库 / 对话…」导航会整体消失，而页面
 * 内部又没有回博客的入口，用户会被困住（B-058）。
 *
 * 因此规则收紧为：已登录用户访问 `/blog` 系列时始终保留外壳；未登录访客的行为
 * 保持不变。
 */

/** `/blog` 系列路径前缀。 */
export const BLOG_PATH_PREFIX = "/blog";

export interface ShellVisibilityInput {
  /** 路由 meta 中是否标记为公开页面 */
  isPublic: boolean;
  /** 当前完整路径，例如 `/blog/collections` */
  path: string;
  /** 当前是否已登录 */
  isAuthenticated: boolean;
}

/**
 * 是否属于 `/blog` 系列路径。
 *
 * 用「相等或以 `/` 结尾前缀开头」判断，避免 `/blogger` 这类同前缀路径被误判。
 */
export function isBlogPath(path: string): boolean {
  return path === BLOG_PATH_PREFIX || path.startsWith(`${BLOG_PATH_PREFIX}/`);
}

/**
 * 返回 `true` 表示该路由应当**不带** AppShell 渲染（裸页面）。
 */
export function shouldRenderWithoutShell({
  isPublic,
  path,
  isAuthenticated,
}: ShellVisibilityInput): boolean {
  // 非公开路由一律走外壳（外壳本身会处理未登录跳转）。
  if (!isPublic) return false;
  // 已登录访问 /blog 系列：保留外壳，保证左侧导航可用。
  return !(isAuthenticated && isBlogPath(path));
}
