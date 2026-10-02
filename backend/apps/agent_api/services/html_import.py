"""Convert an uploaded, untrusted HTML page into reviewable Markdown blocks.

Parsing and conversion are deliberately local and deterministic: this module
never fetches a URL, executes script, or saves the original page.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, NavigableString, Tag
from markdownify import MarkdownConverter

MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_MARKUP_OPENERS = 80_000
MAX_TEXT_CHARS = 350_000
MAX_BLOCKS = 250
CONVERTER_VERSION = "html-md-v1"

_DROP_TAGS = {
    "script",
    "style",
    "template",
    "noscript",
    "iframe",
    "form",
    "object",
    "embed",
    "canvas",
    "video",
    "audio",
    "input",
    "button",
    "textarea",
    "select",
    "meta",
    "link",
    "base",
    "svg",
}
_SOFT_TAGS = {"nav", "aside", "footer", "header"}
_WRAPPERS = {"div", "section", "article", "main"}
_STRUCTURAL_TAGS = {"p", "pre", "table", "ul", "ol", "blockquote", "figure", "hr"}
_HEADINGS = {f"h{level}" for level in range(1, 7)}
_LANGUAGE = re.compile(r"(?:language|lang)-([a-zA-Z0-9_+.-]{1,30})")
_BACKTICKS = re.compile(r"`+")


class HtmlImportError(ValueError):
    def __init__(self, detail: str, *, http_status: int = 400):
        super().__init__(detail)
        self.http_status = http_status


@dataclass(frozen=True)
class _Section:
    nodes: list[Tag]
    region: str


def _safe_url(raw: str, base_url: str = "") -> str:
    raw = raw.strip()
    if not raw or len(raw) > 2048 or any(ord(char) < 32 for char in raw):
        return ""
    if raw.startswith("#"):
        return raw if re.fullmatch(r"#[\w.:~-]{1,160}", raw) else ""
    if raw.startswith("//"):
        if not base_url:
            return ""
        raw = f"{urlsplit(base_url).scheme}:{raw}"
    elif not urlsplit(raw).scheme:
        if not base_url:
            return ""
        raw = urljoin(base_url, raw)
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc or parts.username or parts.password:
        return ""
    if any(char.isspace() for char in parts.netloc):
        return ""
    return quote(urlunsplit(parts), safe=":/?#[]@!$&'*+,;=%-._~")


def validate_source_url(raw: str) -> str:
    if not raw:
        return ""
    clean = _safe_url(raw)
    if not clean or clean.startswith("#"):
        raise HtmlImportError("原网页地址必须是不含账号密码的 http/https 地址")
    return clean


def _code_language(el: Tag) -> str:
    elements = [el, *el.find_all("code", limit=1)]
    for item in elements:
        for css_class in item.get("class", []):
            match = _LANGUAGE.search(str(css_class))
            if match:
                return match.group(1).lower()
    return ""


class _SafeMarkdownConverter(MarkdownConverter):
    def convert_pre(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        code = el.get_text().strip("\n")
        if not code:
            return ""
        longest = max((len(run.group()) for run in _BACKTICKS.finditer(code)), default=0)
        fence = "`" * max(3, longest + 1)
        return f"\n\n{fence}{_code_language(el)}\n{code}\n{fence}\n\n"


def _candidate_root(soup: BeautifulSoup, mode: str) -> Tag:
    body = soup.body or soup
    if mode == "full":
        return body
    candidates = [
        node for node in body.find_all(["article", "main"], limit=80) if len(node.get_text(" ", strip=True)) >= 20
    ]
    candidates += [
        node
        for node in body.find_all(attrs={"itemprop": "articleBody"}, limit=30)
        if len(node.get_text(" ", strip=True)) >= 20
    ]
    if not candidates:
        return body
    return max(candidates, key=lambda node: len(node.get_text(" ", strip=True)) / (1 + len(node.find_all("a"))))


def _flatten(node: Tag, region: str = ""):
    """Expose content blocks without losing the page's original order."""
    for child in node.children:
        if isinstance(child, NavigableString):
            if child.strip():
                wrapper = BeautifulSoup("<p></p>", "html.parser").p
                wrapper.string = str(child).strip()
                yield wrapper, region
            continue
        if not isinstance(child, Tag):
            continue
        child_region = child.name if child.name in _SOFT_TAGS else region
        if child.name in _WRAPPERS and any(child.find_all(_STRUCTURAL_TAGS | _HEADINGS, limit=1)):
            yield from _flatten(child, child_region)
        else:
            yield child, child_region


def _sections(root: Tag) -> list[_Section]:
    sections: list[_Section] = []
    active: list[Tag] = []
    active_region = ""
    for node, region in _flatten(root):
        if len(sections) >= MAX_BLOCKS:
            raise HtmlImportError("网页结构过于复杂，请选择较小的 HTML 文件", http_status=413)
        starts_new = node.name in _HEADINGS or region != active_region or node.name in _SOFT_TAGS
        if active and starts_new:
            sections.append(_Section(active, active_region))
            active = []
        active.append(node)
        active_region = region
        if node.name in _SOFT_TAGS:
            sections.append(_Section(active, active_region))
            active = []
            active_region = ""
    if active:
        sections.append(_Section(active, active_region))
    if len(sections) > MAX_BLOCKS:
        raise HtmlImportError("网页结构过于复杂，请选择较小的 HTML 文件", http_status=413)
    return sections


def _make_markdown(nodes: list[Tag], *, title_heading: Tag | None) -> str:
    fragment = BeautifulSoup("<div></div>", "html.parser")
    container = fragment.div
    for node in nodes:
        copy = BeautifulSoup(str(node), "html.parser")
        piece = copy.find()
        if piece is None:
            continue
        if title_heading is node:
            continue
        container.append(piece)
    converter = _SafeMarkdownConverter(heading_style="ATX", table_infer_header=True, strip_pre=None)
    return converter.convert_soup(container).strip()


def convert_html_to_markdown(html_bytes: bytes, *, filename: str, source_url: str = "", mode: str = "article") -> dict:
    if mode not in {"article", "full"}:
        raise HtmlImportError("导入模式无效")
    if Path(filename).suffix.lower() not in {".html", ".htm"}:
        raise HtmlImportError("仅支持 .html 或 .htm 文件")
    if not html_bytes or len(html_bytes) > MAX_HTML_BYTES:
        raise HtmlImportError("HTML 文件为空或超过 5 MiB", http_status=413 if html_bytes else 400)
    if b"\x00" in html_bytes or html_bytes.count(b"<") > MAX_MARKUP_OPENERS:
        raise HtmlImportError("文件不是可处理的 HTML 或结构过于复杂", http_status=413)
    source_url = validate_source_url(source_url)
    soup = BeautifulSoup(html_bytes, "html.parser")
    if not soup.find() or not soup.find(["body", "article", "main", "p", "h1", "h2", "div"]):
        raise HtmlImportError("没有找到可导入的 HTML 正文", http_status=422)
    if soup.contains_replacement_characters and soup.get_text().count("\ufffd") > 8:
        raise HtmlImportError("网页文字解码失败，请另存为 UTF-8 后重试", http_status=422)
    meta_description = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    description = str(meta_description.get("content", "")).strip() if meta_description else ""
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    unsupported_count = len(soup.find_all(["svg", "math", "iframe", "canvas", "video", "audio"]))
    for node in list(soup.find_all(_DROP_TAGS)):
        node.decompose()
    root = _candidate_root(soup, mode)
    if len(root.get_text(" ", strip=True)) > MAX_TEXT_CHARS:
        raise HtmlImportError("正文过长，请选择较小的 HTML 文件", http_status=413)
    heading = root.find("h1")
    title = (heading.get_text(" ", strip=True) if heading else page_title) or Path(filename).stem
    title = title[:180]
    if not description:
        first_paragraph = root.find("p")
        description = first_paragraph.get_text(" ", strip=True) if first_paragraph else ""
    summary = description[:200]

    assets = []
    warning_counts: Counter[str] = Counter()
    if unsupported_count or root.find(attrs={"rowspan": True}) or root.find(attrs={"colspan": True}):
        warning_counts["UNSUPPORTED_BLOCK"] += max(1, unsupported_count)
    for image in list(root.find_all("img")):
        alt = str(image.get("alt", "")).strip()[:120] or "未命名图片"
        raw_src = str(image.get("src", ""))[:2048]
        safe_src = _safe_url(raw_src, source_url)
        if safe_src and not safe_src.startswith("#"):
            link = soup.new_tag("a", href=safe_src)
            link.string = f"图片：{alt}（外部链接）"
            image.replace_with(link)
            assets.append({"kind": "image", "original": safe_src, "status": "external_link_only"})
            warning_counts["EXTERNAL_IMAGE_LINK"] += 1
        else:
            image.replace_with(f"图片：{alt}（需手动上传）")
            original = raw_src[:160] if not urlsplit(raw_src).scheme else "(blocked)"
            assets.append({"kind": "image", "original": original, "status": "missing_local_file"})
            warning_counts["LOCAL_IMAGE_MISSING"] += 1
    for link in list(root.find_all("a")):
        safe_href = _safe_url(str(link.get("href", "")), source_url)
        if safe_href:
            link.attrs = {"href": safe_href}
        else:
            link.unwrap()
            warning_counts["UNSAFE_OR_RELATIVE_LINK"] += 1
    for node in root.find_all(True):
        if node.name == "a":
            continue
        if node.name in {"pre", "code"}:
            node.attrs = {"class": [value for value in node.get("class", []) if _LANGUAGE.fullmatch(str(value))][:1]}
        else:
            node.attrs = {}
    sections = _sections(root)
    blocks = []
    for section in sections:
        markdown = _make_markdown(section.nodes, title_heading=heading if heading in section.nodes else None)
        if not markdown:
            continue
        plain = " ".join(node.get_text(" ", strip=True) for node in section.nodes)
        link_chars = sum(len(link.get_text(" ", strip=True)) for node in section.nodes for link in node.find_all("a"))
        has_structure = any(
            node.find(_STRUCTURAL_TAGS | _HEADINGS) or node.name in _STRUCTURAL_TAGS | _HEADINGS
            for node in section.nodes
        )
        is_navigation = section.region in _SOFT_TAGS or link_chars > len(plain) * 0.65
        recommended = not is_navigation and (len(plain) >= 35 or has_structure)
        reason = (
            "可能是导航、广告或页脚"
            if is_navigation
            else "连续正文、标题或结构化内容" if recommended else "内容较短，请检查"
        )
        first_heading = next((node for node in section.nodes if node.name in _HEADINGS), None)
        blocks.append(
            {
                "id": f"b{len(blocks) + 1}",
                "heading": first_heading.get_text(" ", strip=True)[:120] if first_heading else "",
                "excerpt": plain[:120],
                "markdown": markdown,
                "recommended": recommended,
                "reason": reason,
            }
        )
    chosen = [block["markdown"] for block in blocks if block["recommended"]]
    if not chosen and blocks:
        warning_counts["REVIEW_SELECTION"] += 1
    if not blocks:
        raise HtmlImportError("没有找到可导入的正文，请检查网页是否由脚本动态生成", http_status=422)
    content = "\n\n".join(chosen).strip()
    if len(content) < 80 or sum(not block["recommended"] for block in blocks) > len(blocks) // 2:
        warning_counts["REVIEW_SELECTION"] += 1
    if root.name not in {"article", "main"} and mode == "article":
        warning_counts["NO_SEMANTIC_ARTICLE"] += 1
    return {
        "title": title,
        "summary": summary,
        "content_markdown": content,
        "source_url": source_url,
        "mode": mode,
        "stats": {
            "text_chars": len(root.get_text(" ", strip=True)),
            "headings": len(root.find_all(_HEADINGS)),
            "tables": len(root.find_all("table")),
            "code_blocks": len(root.find_all("pre")),
        },
        "blocks": blocks,
        "assets": assets[:100],
        "warnings": [{"code": code, "count": count} for code, count in sorted(warning_counts.items())],
        "converter_version": CONVERTER_VERSION,
    }
