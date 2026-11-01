/** Map backend progress/trace codes to user-facing stages without rendering private query text. */
export function displayStage(raw: string, complete = false): string {
  const step = raw.toLowerCase();
  if (step.includes("approval") || step.includes("审批")) return complete ? "已提交操作审批" : "等待操作审批";
  if (step.includes("不提供生成期正文增量")) return complete ? "回答已显示" : "正在处理请求，完成后显示回答";
  let label = "处理请求";
  if (step.includes("security_filter")) label = "检查内容安全";
  else if (step.includes("internet") || step.includes("web search")) label = "查找网页资料";
  else if (step.includes("retriev") || step.includes("knowledge") || step.includes("rag_") || step.includes("search") || step.includes("检索")) label = "检索相关资料";
  else if (step.includes("rewrite") || step.includes("analy") || step.includes("supervisor")) label = "分析问题";
  else if (step.includes("generat") || step.includes("writing") || step.includes("llm") || step.includes("生成")) label = "生成回答";
  else if (step.includes("review")) label = "核对回答";
  else if (step.includes("tool") || step.includes("mcp")) label = "使用已授权工具";
  return `${complete ? "已" : "正在"}${label}`;
}

export function displayRunFailure(status: string, code?: string): string {
  if (status === "cancelled") return "本次运行已取消，生成中的正文未保存。可以重新提问。";
  if (code === "TimeoutError") return "回答超时，生成中的正文未保存。请缩短问题后重试。";
  if (code === "interrupted") return "服务中断了本次回答。请刷新会话后重试。";
  return "回答未完成，生成中的正文未保存。请稍后重试。";
}
