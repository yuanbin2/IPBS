import type { StreamEvent } from "../types";

/** Parse complete SSE events across arbitrary network and UTF-8 decoder chunks. */
export class SseEventParser {
  private pending = "";
  private dataLines: string[] = [];

  push(chunk: string): StreamEvent[] {
    this.pending += chunk;
    const events: StreamEvent[] = [];
    let newline = this.pending.indexOf("\n");
    while (newline >= 0) {
      const line = this.pending.slice(0, newline).replace(/\r$/, "");
      this.pending = this.pending.slice(newline + 1);
      if (line === "") {
        if (this.dataLines.length) {
          events.push(JSON.parse(this.dataLines.join("\n")) as StreamEvent);
          this.dataLines = [];
        }
      } else if (line.startsWith("data:")) {
        this.dataLines.push(line.slice(5).replace(/^ /, ""));
      }
      newline = this.pending.indexOf("\n");
    }
    return events;
  }

  finish(): StreamEvent[] {
    const events = this.push("\n\n");
    this.pending = "";
    return events;
  }
}

export function applyAnswerEvent(current: string, event: StreamEvent): string {
  if (event.type === "answer_delta") return current + (event.text ?? "");
  if (event.type === "answer_snapshot") return event.text ?? "";
  if (event.type === "response") return event.answer ?? current;
  return current;
}
