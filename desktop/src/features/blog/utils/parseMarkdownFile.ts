export interface ParsedMarkdown {
  title: string;
  summary: string;
  category: string;
  tags: string;
  content: string;
}

/**
 * Parse a markdown file string into structured blog fields.
 * Supports YAML frontmatter (--- delimited) commonly used by Hugo/Jekyll/Hexo.
 */
export function parseMarkdownFile(raw: string, filename: string): ParsedMarkdown {
  const result: ParsedMarkdown = {
    title: "",
    summary: "",
    category: "",
    tags: "",
    content: ""
  };

  let body = raw;

  // Step 1: Extract YAML frontmatter if present
  const frontmatterMatch = raw.match(/^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$/);
  if (frontmatterMatch) {
    const frontmatter = frontmatterMatch[1];
    body = frontmatterMatch[2];
    parseFrontmatter(frontmatter, result);
  }

  // Step 2: Extract title — frontmatter > first H1 > filename
  if (!result.title) {
    const h1Match = body.match(/^#\s+(.+)\s*\n?/);
    if (h1Match) {
      result.title = h1Match[1].trim();
      body = body.slice(h1Match[0].length);
    }
  }
  if (!result.title) {
    result.title = filename.replace(/\.(md|markdown|txt)$/i, "").trim();
  }

  // Step 3: Extract summary — frontmatter > first non-heading paragraph
  if (!result.summary) {
    const paragraphs = body.split(/\n\s*\n/);
    for (const para of paragraphs) {
      const trimmed = para.trim();
      if (trimmed && !trimmed.startsWith("#")) {
        result.summary = trimmed.replace(/[*_`~\[\]()]/g, "").slice(0, 200);
        break;
      }
    }
  }

  result.content = body.trim();
  return result;
}

/** Parse YAML frontmatter lines into the result object. */
function parseFrontmatter(yaml: string, result: ParsedMarkdown): void {
  const lines = yaml.split("\n");

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const kvMatch = line.match(/^(\w+):\s*(.+)$/);
    if (!kvMatch) continue;

    const key = kvMatch[1].toLowerCase();
    const value = kvMatch[2].trim();

    switch (key) {
      case "title":
        result.title = stripQuotes(value);
        break;
      case "summary":
      case "description":
      case "excerpt":
        result.summary = stripQuotes(value);
        break;
      case "category":
        result.category = stripQuotes(value);
        break;
      case "categories":
        // Could be a YAML array on next lines or inline
        result.category = parseFirstArrayItem(lines, i, value);
        break;
      case "tags":
        result.tags = parseTags(lines, i, value);
        break;
    }
  }
}

/** Parse tags as either YAML array or comma-separated string. */
function parseTags(lines: string[], currentIndex: number, inlineValue: string): string {
  // Check if next lines are YAML array items (e.g. "- tag1")
  const arrayItems: string[] = [];
  for (let j = currentIndex + 1; j < lines.length; j++) {
    const arrayMatch = lines[j].match(/^\s+-\s+(.+)$/);
    if (arrayMatch) {
      arrayItems.push(stripQuotes(arrayMatch[1].trim()));
    } else {
      break;
    }
  }

  if (arrayItems.length > 0) {
    return arrayItems.join(",");
  }

  // Inline value: could be "[tag1, tag2]" or "tag1, tag2"
  const cleaned = inlineValue.replace(/^\[|\]$/g, "").trim();
  return cleaned
    .split(",")
    .map((t) => stripQuotes(t.trim()))
    .filter(Boolean)
    .join(",");
}

/** Parse first item from a YAML array (for categories). */
function parseFirstArrayItem(lines: string[], currentIndex: number, inlineValue: string): string {
  for (let j = currentIndex + 1; j < lines.length; j++) {
    const arrayMatch = lines[j].match(/^\s+-\s+(.+)$/);
    if (arrayMatch) {
      return stripQuotes(arrayMatch[1].trim());
    }
    break;
  }
  return stripQuotes(inlineValue.replace(/^\[|\]$/g, "").split(",")[0]?.trim() ?? "");
}

/** Strip surrounding quotes from a YAML value. */
function stripQuotes(value: string): string {
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
    return value.slice(1, -1);
  }
  return value;
}
