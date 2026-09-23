"""网页搜索实现：查询构造、多 provider 降级、结果去重排序与天气快捷通道。

网络出口只有 :func:`open_url` 一处（测试通过 patch 本模块的 ``urlopen`` 注入）；
provider 顺序、超时与结果数都由环境变量控制，端点固定不接受外部配置，
避免管理员误把该工具变成 SSRF 代理。
"""

from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from .web_search_parsers import (
    _BaiduHTMLParser,
    _BingHTMLParser,
    _DuckDuckGoHTMLParser,
    normalize_duckduckgo_url,
)


def bounded_int(raw_value: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def open_url(request: Request, *, timeout: int):
    proxy = os.getenv("WEB_SEARCH_PROXY", "").strip()
    if not proxy:
        return urlopen(request, timeout=timeout)
    opener = build_opener(ProxyHandler({"http": proxy, "https": proxy}))
    return opener.open(request, timeout=timeout)


def network_error_message(provider: str, exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"{provider} HTTP {exc.code}"
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", exc)
        return f"{provider} 网络错误：{reason}"
    if isinstance(exc, TimeoutError):
        return f"{provider} 请求超时"
    return f"{provider} {type(exc).__name__}: {exc}"


def provider_order(provider: str) -> list[str]:
    # Auto mode tries Baidu first (accessible in mainland China),
    # then falls back to DuckDuckGo and Bing (may require proxy).
    if provider == "auto":
        return ["baidu", "duckduckgo", "bing"]
    if provider == "duckduckgo":
        return ["duckduckgo", "bing", "baidu"]
    if provider == "bing":
        return ["bing", "baidu"]
    if provider == "baidu":
        return ["baidu"]
    return [provider]


def duckduckgo_instant_answer(query: str, *, limit: int, timeout: int) -> tuple[list[tuple[str, str]], str]:
    url = "https://api.duckduckgo.com/?" + urlencode(
        {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
    )
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "KnowledgeAgent/1.0"})
    try:
        with open_url(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return [], network_error_message("DuckDuckGo instant answer", exc)

    results: list[tuple[str, str]] = []
    if payload.get("AbstractText") and payload.get("AbstractURL"):
        results.append((str(payload["AbstractText"]), str(payload["AbstractURL"])))
    for item in payload.get("RelatedTopics", []):
        candidates = item.get("Topics", []) if isinstance(item, dict) and "Topics" in item else [item]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            text = str(candidate.get("Text", "")).strip()
            target_url = normalize_duckduckgo_url(str(candidate.get("FirstURL", "")).strip())
            if text and target_url:
                results.append((text, target_url))
            if len(results) >= limit:
                return results, ""
    return results, ""


def build_search_queries(query: str) -> list[str]:
    # Strip English search prefixes
    cleaned = re.sub(
        r"(please\s+)?(help\s+me\s+)?(use\s+)?(web|internet|online)?\s*(search|find|look\s+up)\s+",
        "",
        query.strip(),
        count=1,
        flags=re.IGNORECASE,
    )
    # Strip Chinese search prefixes - comprehensive pattern that handles:
    # - Politeness: 请/帮我/能否/可以
    # - Tool/method: 用/使用 + 网页/网络/网上/联网/互联网
    # - "在...中" pattern: 在网络中/在网上
    # - Action verbs: 搜索/检索/查找/查询/搜/查/找
    # - Suffixes: 一下/看看/查查
    # Note: no ^ anchor — the prefix may appear after history context text
    cleaned = re.sub(
        r"(请|请你|麻烦|帮我|请帮我|能否|可以)\s*"
        r"(用|使用)?\s*"
        r"(在?\s*(网页|网络|网上|联网|互联网)\s*中?\s*)?"
        r"(搜索|检索|查找|查询|搜一下|查一下|搜|查|找)\s*(一下|看看|查查)?",
        "",
        cleaned,
        count=1,
        flags=re.IGNORECASE,
    )
    # Also strip standalone search intent patterns (no politeness words)
    cleaned = re.sub(
        r"(网页|网络|网上|联网|互联网)\s*(搜索|检索|查找|查询|搜一下|查一下|搜|查|找)\s*(一下|看看|查查)?",
        "",
        cleaned,
        count=1,
        flags=re.IGNORECASE,
    )
    cleaned = cleaned.strip(" ，。？！,.!?:：")
    cleaned = re.sub(r"\s+", " ", cleaned) or query.strip()
    focused = re.sub(r"(请问|是什么|怎么样|有哪些|告诉我|介绍一下|相关信息)", " ", cleaned)
    focused = re.sub(r"\s+", " ", focused).strip(" ，。？！,.!?:：")

    # For weather queries, add specific site targeting for better results
    weather_keywords = ["天气", "天气预报", "气温", "温度", "weather"]
    is_weather = any(kw in cleaned.lower() for kw in weather_keywords)
    if is_weather:
        # Try to extract location from the query
        location_match = re.search(r"([一-鿿]{2,4})(?:的|市|省|区|县)?(?:天气|气温|温度)", cleaned)
        location = location_match.group(1) if location_match else ""
        if location:
            focused = f"{location} 明日天气预报 详细"
        else:
            focused = f"{cleaned} site:weather.com.cn OR site:tianqi.com"

    queries = [focused or cleaned]
    if cleaned != queries[0] and len(cleaned) <= 100:
        queries.append(cleaned)
    return list(dict.fromkeys(queries))[:2]


def deduplicate_and_rerank(
    query: str,
    results: list[tuple[str, str]],
    *,
    limit: int,
) -> list[tuple[str, str]]:
    unique: dict[str, tuple[str, str, int]] = {}
    for position, (text, target_url) in enumerate(results):
        normalized_url = target_url.rstrip("/")
        if not normalized_url or normalized_url in unique:
            continue
        unique[normalized_url] = (text, target_url, position)

    ranked = sorted(
        unique.values(),
        key=lambda item: web_result_score(query, item[0], item[1], item[2]),
        reverse=True,
    )
    return [(text, target_url) for text, target_url, _ in ranked[:limit]]


def web_result_score(query: str, text: str, target_url: str, position: int) -> float:
    query_lower = query.lower()
    haystack = f"{text} {target_url}".lower()
    ascii_terms = re.findall(r"[a-z0-9][a-z0-9.+#_-]{1,}", query_lower)
    chinese_segments = re.findall(r"[\u4e00-\u9fff]{2,}", query_lower)
    chinese_terms = [
        segment
        for value in chinese_segments
        for segment in ([value] + [value[i : i + 2] for i in range(len(value) - 1)])
    ]
    terms = list(dict.fromkeys([*ascii_terms, *chinese_terms]))
    overlap = sum(1 for term in terms if term in haystack)
    score = overlap * 3.0 - position * 0.08
    hostname = (urlparse(target_url).hostname or "").lower()
    if any(marker in query_lower for marker in ["官方", "官网", "official", "文档", "documentation"]):
        if hostname.endswith(".org"):
            score += 15.0
        elif hostname.startswith("docs.") or hostname.startswith("developer."):
            score += 4.0
        elif "readthedocs" in hostname:
            score -= 1.0
        stopwords = {"official", "documentation", "docs", "web", "search", "please", "framework"}
        core_terms = [term for term in ascii_terms if term not in stopwords and len(term) >= 3]
        compact_hostname = re.sub(r"[^a-z0-9]", "", hostname)
        score += sum(2.0 for term in core_terms if re.sub(r"[^a-z0-9]", "", term) in compact_hostname)
    if "github.com" in hostname and "github" in query_lower:
        score += 3.0
    return score


def duckduckgo_html_search(query: str, *, limit: int, timeout: int) -> tuple[list[tuple[str, str]], str]:
    request = Request(
        "https://html.duckduckgo.com/html/",
        data=urlencode({"q": query}).encode("utf-8"),
        headers={
            "Accept": "text/html",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 KnowledgeAgent/1.0",
        },
    )
    try:
        with open_url(request, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return [], network_error_message("DuckDuckGo HTML", exc)

    parser = _DuckDuckGoHTMLParser()
    parser.feed(html)
    results: list[tuple[str, str]] = []
    for item in parser.results:
        target_url = normalize_duckduckgo_url(item["url"])
        if not target_url:
            continue
        description = item["title"]
        if item["snippet"]:
            description = f"{description} — {item['snippet']}"
        results.append((description, target_url))
        if len(results) >= limit:
            break
    return results, ""


def bing_html_search(query: str, *, limit: int, timeout: int) -> tuple[list[tuple[str, str]], str]:
    request = Request(
        "https://www.bing.com/search?" + urlencode({"q": query}),
        headers={
            "Accept": "text/html",
            "User-Agent": "Mozilla/5.0 KnowledgeAgent/1.0",
        },
    )
    try:
        with open_url(request, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return [], network_error_message("Bing HTML", exc)

    parser = _BingHTMLParser()
    parser.feed(html)
    results: list[tuple[str, str]] = []
    for item in parser.results:
        target_url = normalize_duckduckgo_url(item["url"])
        if not target_url:
            continue
        description = item["title"]
        if item["snippet"]:
            description = f"{description} — {item['snippet']}"
        results.append((description, target_url))
        if len(results) >= limit:
            break
    return results, ""


def baidu_html_search(query: str, *, limit: int, timeout: int) -> tuple[list[tuple[str, str]], str]:
    """Search through Baidu for users in mainland China."""
    request = Request(
        "https://www.baidu.com/s?" + urlencode({"wd": query, "rn": limit + 4}),
        headers={
            "Accept": "text/html",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        },
    )
    try:
        with open_url(request, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return [], network_error_message("Baidu HTML", exc)

    parser = _BaiduHTMLParser()
    parser.feed(html)
    results: list[tuple[str, str]] = []
    for item in parser.results:
        target_url = item["url"]
        if not target_url or target_url.startswith("#"):
            continue
        description = item["title"]
        if item["snippet"]:
            description = f"{description} — {item['snippet']}"
        results.append((description, target_url))
        if len(results) >= limit:
            break
    return results, ""


def try_weather_query(query: str) -> str | None:
    """Detect weather queries and use wttr.in for reliable, structured results.

    Returns a formatted weather string if the query is weather-related,
    or None to fall through to the general web search path.
    """
    weather_keywords = ["天气", "天气预报", "气温", "温度", "weather", "forecast", "下雨", "晴天", "阴天"]
    lowered = query.lower()
    if not any(kw in lowered for kw in weather_keywords):
        return None

    # Try to extract a city/location name from the query
    # Common patterns: "北京天气", "明天北京的天气", "上海天气预报"
    location_match = re.search(r"([一-鿿]{2,4})(?:的|市|省|区|县)?(?:天气|气温|温度)", query)
    location = location_match.group(1) if location_match else ""

    # Also try English city names
    if not location:
        en_match = re.search(r"(?:weather|forecast|temperature)\s+(?:in|for)\s+([A-Za-z\s]+)", query, re.IGNORECASE)
        location = en_match.group(1).strip() if en_match else ""

    # If no explicit location, use empty string (wttr.in will use IP geolocation)
    # This handles cases like "明天的天气预报" where no city is mentioned

    timeout = bounded_int(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "10"), default=10, minimum=2, maximum=30)

    # Try wttr.in - a free weather service that returns plain text
    # When location is empty, wttr.in uses IP geolocation
    try:
        location_path = location if location else ""
        url = f"https://wttr.in/{location_path}?format=j1&lang=zh"
        request = Request(url, headers={"User-Agent": "curl/7.68.0", "Accept": "application/json"})
        with open_url(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))

        current = data.get("current_condition", [{}])[0]
        forecasts = data.get("weather", [])

        location_label = location if location else "您的位置（IP定位）"
        lines = [f"🌤 {location_label}天气实况（数据来源：wttr.in）："]
        if current:
            temp = current.get("temp_C", "?")
            feels = current.get("FeelsLikeC", "?")
            humidity = current.get("humidity", "?")
            wind = current.get("windspeedKmph", "?")
            desc_cn = current.get("lang_zh", [{}])
            desc = desc_cn[0].get("value", "") if desc_cn else current.get("weatherDesc", [{}])[0].get("value", "")
            lines.append(f"  当前温度：{temp}°C（体感 {feels}°C）")
            lines.append(f"  天气状况：{desc}")
            lines.append(f"  湿度：{humidity}%，风速：{wind} km/h")

        if forecasts:
            lines.append("\n📅 未来天气预报：")
            for day in forecasts[:3]:
                date = day.get("date", "")
                max_temp = day.get("maxtempC", "?")
                min_temp = day.get("mintempC", "?")
                hourly = day.get("hourly", [])
                day_desc = ""
                if hourly:
                    noon = hourly[4] if len(hourly) > 4 else hourly[0]
                    desc_cn = noon.get("lang_zh", [{}])
                    day_desc = (
                        desc_cn[0].get("value", "") if desc_cn else noon.get("weatherDesc", [{}])[0].get("value", "")
                    )
                lines.append(f"  {date}：{min_temp}°C ~ {max_temp}°C，{day_desc}")

        return "\n".join(lines)
    except Exception:
        pass

    # Fallback: search Chinese weather sites directly
    try:
        search_url = "https://www.baidu.com/s?" + urlencode({"wd": f"{location} 天气预报 明日"})
        request = Request(
            search_url,
            headers={
                "Accept": "text/html",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
        )
        with open_url(request, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="replace")
        # Extract weather data from Baidu's inline weather widget (if present)
        # Baidu embeds weather in a <div class="op_weather4_t498"> or similar
        temp_match = re.search(r"(\-?\d+)\s*°", html)
        if temp_match:
            return f"🌤 {location}天气：从百度搜索结果获取到温度 {temp_match.group(1)}°C（建议访问 weather.com.cn 获取详细预报）"
    except Exception:
        pass

    return None


def web_search(query: str) -> str:
    """Search the public web through keyless providers with ordered fallback.

    The endpoints are intentionally fixed instead of accepting URLs from the
    database, so an administrator cannot accidentally turn this tool into
    an SSRF proxy. Only the result title, URL and snippet are returned.
    """
    query = query.strip()
    if not query:
        return "网页搜索失败：query 不能为空。"

    # For weather queries, use wttr.in directly for reliable results
    weather_result = try_weather_query(query)
    if weather_result:
        return weather_result

    provider = os.getenv("WEB_SEARCH_PROVIDER", "auto").strip().lower()
    if provider not in {"auto", "duckduckgo", "bing", "baidu"}:
        return f"网页搜索配置错误：不支持 provider={provider}。"

    limit = bounded_int(os.getenv("WEB_SEARCH_MAX_RESULTS", "8"), default=8, minimum=3, maximum=12)
    timeout = bounded_int(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "10"), default=10, minimum=2, maximum=30)
    results: list[tuple[str, str]] = []
    errors: list[str] = []
    search_queries = build_search_queries(query)
    used_provider = provider
    for candidate_provider in provider_order(provider):
        provider_results: list[tuple[str, str]] = []
        for search_query in search_queries:
            if candidate_provider == "duckduckgo":
                search_results, error = duckduckgo_html_search(search_query, limit=limit + 4, timeout=timeout)
            elif candidate_provider == "bing":
                search_results, error = bing_html_search(search_query, limit=limit + 4, timeout=timeout)
            else:
                search_results, error = baidu_html_search(search_query, limit=limit + 4, timeout=timeout)
            provider_results.extend(search_results)
            if error:
                errors.append(error)
        provider_results = deduplicate_and_rerank(search_queries[0], provider_results, limit=limit)
        if not provider_results and candidate_provider == "duckduckgo":
            provider_results, error = duckduckgo_instant_answer(
                search_queries[0],
                limit=limit,
                timeout=timeout,
            )
            if error:
                errors.append(error)
        if provider_results:
            results = provider_results
            used_provider = candidate_provider
            break
    if not results:
        if errors:
            diagnostics = "；".join(dict.fromkeys(errors))
            return (
                f"网页搜索失败：所有搜索服务均不可用（{diagnostics}）。\n\n"
                "可能的原因：\n"
                "1. 服务器无法访问外部网络（DuckDuckGo/Bing 在中国大陆被墙）\n"
                "2. 未配置代理（可在环境变量 WEB_SEARCH_PROXY 中设置 HTTP 代理）\n"
                "3. 百度搜索页面结构变更导致解析失败\n\n"
                "建议：\n"
                "- 在 .env 中设置 WEB_SEARCH_PROXY=http://127.0.0.1:7890（你的代理地址）\n"
                "- 或设置 WEB_SEARCH_PROVIDER=baidu 优先使用百度搜索"
            )
        return "网页搜索没有返回可用结果。请换用更明确的关键词。"

    lines = [
        f"网页搜索结果（provider={used_provider}，原始问题={query}，检索式={' | '.join(search_queries)}，结果数={len(results)}）："
    ]
    for index, (text, target_url) in enumerate(results[:limit], start=1):
        lines.append(f"[{index}] {text}\n{target_url}")
    return "\n\n".join(lines)
