import type { BlogArticle } from "../types";

const defaultTitle = "智能个人博客系统";

function addMeta(attribute: "name" | "property", key: string, content: string) {
  const node = document.createElement("meta");
  node.dataset.blogSeo = "";
  node.setAttribute(attribute, key);
  node.content = content;
  document.head.append(node);
}

export function updateArticleHead(article: BlogArticle | null) {
  document.head.querySelectorAll("[data-blog-seo]").forEach((node) => node.remove());
  document.title = article?.status === "published" ? article.title : defaultTitle;
  if (!article || article.status !== "published") {
    if (article) addMeta("name", "robots", "noindex, nofollow");
    return;
  }

  const description = (article.summary || article.content || "")
    .replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim().slice(0, 240);
  const canonical = new URL(`/blog/${encodeURIComponent(article.slug)}/`, window.location.origin).href;
  const cover = article.cover_image?.trim() || "";
  const localCover = /^\/media\/blog\/[0-9a-f]{32}\.(?:png|jpg|gif|webp)$/.test(cover);
  const remoteCover = cover.startsWith("https://");
  const link = document.createElement("link");
  link.dataset.blogSeo = "";
  link.rel = "canonical";
  link.href = canonical;
  document.head.append(link);
  addMeta("name", "description", description);
  addMeta("property", "og:type", "article");
  addMeta("property", "og:title", article.title);
  addMeta("property", "og:description", description);
  addMeta("property", "og:url", canonical);
  addMeta("name", "twitter:card", localCover || remoteCover ? "summary_large_image" : "summary");
  addMeta("name", "twitter:title", article.title);
  addMeta("name", "twitter:description", description);
  if (localCover) {
    const image = new URL(cover, window.location.origin).href;
    addMeta("property", "og:image", image);
    addMeta("name", "twitter:image", image);
  } else if (remoteCover) {
    addMeta("property", "og:image", cover);
    addMeta("name", "twitter:image", cover);
  }
}
