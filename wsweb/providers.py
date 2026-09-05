"""搜索源：bing（免 Key 默认）/ tavily / bocha（可选，环境变量密钥）。

Bing 免 Key 实现（S2）：
1) 主路 RSS：https://www.bing.com/search?q=..&format=rss（地域重定向跟随）；
   解析 <item><title><link><description>(pubDate 有则取)；实测单查询约 10 条、无分页。
   注意 Bing RSS 授权条款限个人非商业展示、低流量。
2) 兜底 HTML：cn.bing.com/search?q=..&count=N，只取 li.b_algo 有机块
   （h2 a href / h2 标题 / p 摘要），解码 bing.com/ck/a 跳转；无 b_results 视为被拦。
tavily / bocha：S4 接入（结构已留）。
"""

from __future__ import annotations

import html as _html
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote

from . import config
from .errors import SearchFailed
from .models import SearchResult
from .safety import PoliteFetcher
from .urlutil import decode_bing_redirect

# 测试/自定义端点（保持与 RoleplayChat 相同手法：包级变量可换）
BING_BASE = os.environ.get("WS_BING_BASE", "https://www.bing.com/search")
BING_BASE_CN = os.environ.get("WS_BING_BASE_CN", "https://cn.bing.com/search")

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def _clean_text(raw: str | None, limit: int = 300) -> str:
    if not raw:
        return ""
    t = _html.unescape(_TAG_RE.sub(" ", raw))
    t = _SPACE_RE.sub(" ", t).strip()
    return t[:limit]


def _parse_rss(xml_text: str) -> list[SearchResult]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise SearchFailed(f"Bing RSS 解析失败：{e}")
    items = root.findall(".//item")
    out: list[SearchResult] = []
    for it in items:
        def _f(tag: str) -> str:
            el = it.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""
        title = _clean_text(_f("title"), 200)
        link = decode_bing_redirect(_f("link"))
        desc = _clean_text(_f("description"), 300)
        pub = ""
        raw_pub = _f("pubDate")
        if raw_pub:
            try:
                dt = datetime.strptime(raw_pub, "%a, %d %b %Y %H:%M:%S %z")
                pub = dt.astimezone().strftime("%Y-%m-%d")
            except ValueError:
                pub = raw_pub[:10]
        if not title or not link.startswith(("http://", "https://")):
            continue
        out.append(SearchResult(title=title, url=link, snippet=desc,
                                source="bing", site="", published=pub))
    return out


def _parse_html(html_text: str) -> list[SearchResult]:
    if "b_results" not in html_text:
        raise SearchFailed("Bing 未返回结果页（可能被风控/需验证），请稍后重试或换 tavily/bocha")
    out: list[SearchResult] = []
    # 只取有机结果块 li.b_algo
    for m in re.finditer(r'<li class="b_algo"[^>]*>(.*?)</li>', html_text, re.S | re.I):
        block = m.group(1)
        h2 = re.search(r"<h2[^>]*>\s*<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", block, re.S | re.I)
        if not h2:
            h2 = re.search(r"<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", block, re.S | re.I)
        if not h2:
            continue
        url = decode_bing_redirect(_html.unescape(h2.group(1)))
        if not url.startswith(("http://", "https://")):
            continue
        title = _clean_text(h2.group(2), 200)
        if not title:
            continue
        p = re.search(r"<p[^>]*>(.*?)</p>", block, re.S | re.I)
        snippet = _clean_text(p.group(1), 300) if p else ""
        if not snippet:  # 退化：摘要为空时给空串，不伪造
            snippet = ""
        out.append(SearchResult(title=title, url=url, snippet=snippet, source="bing"))
    return out


def _post_json(url: str, payload: dict, key: str, timeout: float = 25.0) -> tuple[int, object]:
    """POST JSON + Bearer；返回 (status_code, body)。网络异常抛 SearchFailed。"""
    import requests

    try:
        r = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            timeout=timeout,
            verify=True,
        )
    except requests.exceptions.RequestException as e:
        raise SearchFailed(f"API 请求失败：{type(e).__name__}")
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


class BaseProvider:
    name = "base"

    @classmethod
    def available(cls) -> bool:
        raise NotImplementedError

    @classmethod
    def describe(cls) -> str:
        return ""

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        raise NotImplementedError


class BingProvider(BaseProvider):
    """免 Key Bing：RSS 主 → HTML 兜底。"""

    name = "bing"

    @classmethod
    def available(cls) -> bool:
        return True

    @classmethod
    def describe(cls) -> str:
        return "免 Key（Bing RSS/HTML 有机结果）；授权条款限个人非商业、低流量"

    def _fetch(self, url: str) -> str:
        fetcher = PoliteFetcher()  # 复用 SSRF 防护/限速/体积上限（robots 不适用于搜索端点）
        return fetcher.fetch(url, respect_robots=False).text

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        q = query.strip()
        if not q:
            raise SearchFailed("搜索词为空")
        max_results = max(1, min(20, int(max_results)))
        errs: list[str] = []

        # 主路：RSS
        try:
            xml_text = self._fetch(f"{BING_BASE}?q={quote(q)}&format=rss")
            results = _parse_rss(xml_text)
            if results:
                return results[:max_results]
            errs.append("RSS 空结果")
        except SearchFailed as e:
            errs.append(str(e))
        except Exception as e:  # 网络层异常统一降级
            errs.append(f"RSS 请求异常：{type(e).__name__}")

        # 兜底：HTML 有机块
        try:
            html_text = self._fetch(f"{BING_BASE_CN}?q={quote(q)}&count={max_results}")
            results = _parse_html(html_text)
            if results:
                return results[:max_results]
            errs.append("HTML 空结果")
        except SearchFailed as e:
            errs.append(str(e))
        except Exception as e:
            errs.append(f"HTML 请求异常：{type(e).__name__}")

        raise SearchFailed("Bing 不可用：" + "；".join(errs))


class TavilyProvider(BaseProvider):
    name = "tavily"
    endpoint = os.environ.get("WS_TAVILY_ENDPOINT", "https://api.tavily.com/search")

    @classmethod
    def available(cls) -> bool:
        return bool(config.tavily_key())

    @classmethod
    def describe(cls) -> str:
        return "API（Bearer，月免费 1000 credits，basic=1/advanced=2）" if cls.available() else "未配置 TAVILY_API_KEY"

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        key = config.tavily_key()
        if not key:
            raise SearchFailed("Tavily 未配置 TAVILY_API_KEY")
        payload = {"query": query.strip(), "max_results": max(1, min(10, int(max_results))),
                   "search_depth": "basic"}
        code, body = _post_json(self.endpoint, payload, key)
        if code != 200:
            raise SearchFailed(f"Tavily HTTP {code}: {body[:300]}")
        try:
            data = body["results"]
        except (KeyError, TypeError):
            raise SearchFailed("Tavily 响应格式异常")
        out = []
        for it in data:
            url = decode_bing_redirect((it.get("url") or "").strip())
            if not url.startswith(("http://", "https://")):
                continue
            title = _clean_text(it.get("title"), 200)
            content = _clean_text(it.get("content"), 300)
            if not title and not content:
                continue
            out.append(SearchResult(title=title or url[:80], url=url, snippet=content,
                                    source="tavily", site=it.get("url", "").split("/")[2] if "//" in (it.get("url") or "") else ""))
        if not out:
            raise SearchFailed("Tavily 无结果")
        return out


class BochaProvider(BaseProvider):
    name = "bocha"

    @classmethod
    def available(cls) -> bool:
        return bool(config.bocha_key())

    @classmethod
    def describe(cls) -> str:
        return f"API（Bearer，基址 {config.bocha_base_url()}）" if cls.available() else "未配置 BOCHA_API_KEY"

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        key = config.bocha_key()
        if not key:
            raise SearchFailed("博查未配置 BOCHA_API_KEY")
        payload = {"query": query.strip(), "count": max(1, min(20, int(max_results))),
                   "freshness": "noLimit"}
        code, body = _post_json(config.bocha_base_url() + "/v1/web-search", payload, key)
        if code != 200:
            raise SearchFailed(f"博查 HTTP {code}: {str(body)[:300]}")
        pages = (((body or {}).get("data") or {}).get("webPages") or {}).get("value") or []
        out = []
        for it in pages:
            url = (it.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            title = _clean_text(it.get("name"), 200)
            sn = _clean_text(it.get("snippet") or it.get("summary"), 300)
            pub = (it.get("datePublished") or it.get("dateLastCrawled") or "")[:10]
            if not title and not sn:
                continue
            out.append(SearchResult(title=title or url[:80], url=url, snippet=sn,
                                    source="bocha", site=(it.get("siteName") or ""), published=pub))
        if not out:
            raise SearchFailed("博查无结果")
        return out


PROVIDERS: dict[str, type[BaseProvider]] = {
    "bing": BingProvider,
    "tavily": TavilyProvider,
    "bocha": BochaProvider,
}


def resolve_provider(name: str) -> type[BaseProvider]:
    n = (name or "bing").strip().lower()
    if n == "auto":
        return BingProvider  # auto 策略：默认 bing（免 Key、零依赖）
    if n in PROVIDERS:
        return PROVIDERS[n]
    raise SearchFailed(f"未知搜索源：{name}（可选 bing/tavily/bocha/auto）")


def list_provider_status() -> list[dict]:
    out = []
    for name, cls in PROVIDERS.items():
        ok = cls.available()
        out.append({"name": name, "available": ok, "note": cls.describe()})
    return out
