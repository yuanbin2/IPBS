/** 博客页面与博客智能体共用的 JSON/非 JSON 错误响应解析。 */
export async function requestJson<T = any>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") ?? "";
  const text = await response.text();
  let payload: any = null;

  if (contentType.includes("application/json") && text) {
    payload = JSON.parse(text);
  } else if (text) {
    const plainText = text.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    payload = { detail: plainText.slice(0, 220) || "服务返回了非 JSON 响应。" };
  }

  if (!response.ok) throw new Error(payload?.detail ?? `请求失败：HTTP ${response.status}`);
  return payload as T;
}
