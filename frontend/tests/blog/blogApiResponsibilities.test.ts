import assert from "node:assert/strict";
import { test } from "node:test";
import { fetchBlogAgentHistory, postBlogAgentMessage } from "../../src/features/blog/api/blogAgentApi.ts";
import { fetchCollectionArchive, uploadCollectionArchive } from "../../src/features/blog/api/archiveApi.ts";
import { requestJson } from "../../src/features/blog/api/requestJson.ts";

test("shared blog response parser preserves non-JSON error text and empty success", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return calls === 1
      ? new Response("<p>临时错误</p>", { status: 503, headers: { "content-type": "text/html" } })
      : new Response(null, { status: 204 });
  };
  try {
    await assert.rejects(requestJson("/example"), /临时错误/);
    assert.equal(await requestJson("/empty"), null);
  } finally { globalThis.fetch = originalFetch; }
});

test("blog agent API keeps history cursor and chat payload on their original endpoints", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ url: string; options?: RequestInit }> = [];
  globalThis.fetch = async (input, options) => {
    calls.push({ url: String(input), options });
    return Response.json(calls.length === 1
      ? { messages: [{ id: 4, role: "user", content: "旧问题" }], has_more_before: true }
      : { session_key: "s1", answer: "答复", sources: [] });
  };
  try {
    const history = await fetchBlogAgentHistory("s1", 8);
    const answer = await postBlogAgentMessage("问题", "s1", "ragagent");
    assert.equal(history.messages?.[0]?.id, 4);
    assert.equal(answer.answer, "答复");
    assert.equal(calls[0].url, "/api/agent/blog/agent/chat/?session_key=s1&limit=8&before=8");
    assert.equal(calls[1].url, "/api/agent/blog/agent/chat/");
    assert.deepEqual(JSON.parse(String(calls[1].options?.body)), {
      message: "问题", session_key: "s1", rag_source: "ragagent",
    });
  } finally { globalThis.fetch = originalFetch; }
});

test("collection archive API preserves credentials and preview/apply modes", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ url: string; options?: RequestInit }> = [];
  globalThis.fetch = async (input, options) => {
    calls.push({ url: String(input), options });
    if (calls.length === 1) return new Response("zip", {
      headers: { "content-disposition": 'attachment; filename="export.zip"' },
    });
    return Response.json({ collections: [], totals: { articles: 0 } });
  };
  try {
    const archive = await fetchCollectionArchive(["first", "second"]);
    const file = new File(["zip"], "import.zip", { type: "application/zip" });
    await uploadCollectionArchive(file, "preview");
    await uploadCollectionArchive(file, "apply", "replace");
    assert.equal(archive.filename, "export.zip");
    assert.equal(await archive.blob.text(), "zip");
    assert.equal(calls[0].url, "/api/agent/blog/collections/export/?ids=first%2Csecond");
    assert.equal(calls[0].options?.credentials, "include");
    assert.equal(calls[1].options?.credentials, "include");
    assert.equal((calls[1].options?.body as FormData).get("mode"), "preview");
    assert.equal((calls[2].options?.body as FormData).get("mode"), "apply");
    assert.equal((calls[2].options?.body as FormData).get("conflict"), "replace");
  } finally { globalThis.fetch = originalFetch; }
});

test("collection archive API keeps server error detail", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ detail: "归档无效" }, { status: 400 });
  try {
    await assert.rejects(uploadCollectionArchive(new File(["x"], "bad.zip"), "preview"), /归档无效/);
    await assert.rejects(fetchCollectionArchive(["id"]), /归档无效/);
  } finally { globalThis.fetch = originalFetch; }
});
