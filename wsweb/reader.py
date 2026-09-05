"""网页正文阅读：礼貌抓取（safety.PoliteFetcher）+ trafilatura 提取 + 多页翻页拼接。

纪律（方针 4/5/6）：robots 尊重、限速、无 JS、不绕验证码/登录墙；403/验证码墙如实报错；
PDF/图片/纯 JS 渲染页无法提取时如实说明，不伪造正文；翻页上限与输出截断可配。
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from . import config
from .errors import ExtractionFailed, SiteBlocked, WebError
from .models import ReadResult
from .safety import PoliteFetcher
from .urlutil import host_of, normalize_url

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_REL_NEXT_LINK = re.compile(r"<link[^>]+rel=[\"']?next[\"']?[^>]*href=[\"']([^\"']+)", re.I)
_REL_NEXT_ANCHOR = re.compile(r"<a[^>]+rel=[\"']?next[\"']?[^>]*href=[\"']([^\"']+)", re.I)
_NEXT_TEXT_ANCHOR = re.compile(
    r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(?:\s*<[^>]+>\s*)*(?:下一页|下页|下一篇|Next|next\s*[›»])",
    re.I,
)
_NUM_PARAM = re.compile(r"^(\d+)$")
_PATH_NUM = re.compile(r"/(\d+)(?:\.html?)?(?:[/?#]|$)")


def _extract(fr_text: str, ctype: str) -> str:
    """提取正文；纯 JS/PDF/图片页返回 ''。"""
    if not fr_text:
        return ""
    if ctype in ("text/plain", "application/xml", "text/xml", "application/rss+xml"):
        return fr_text
    try:
        import trafilatura
    except ImportError:
        raise ExtractionFailed("缺少 trafilatura，请先安装依赖")
    # html/xhtml 等走 trafilatura
    out = trafilatura.extract(
        fr_text,
        output_format="txt",
        include_comments=False,
        include_tables=False,
        favor_precision=True,
        include_links=False,
    )
    return (out or "").strip()


def _html_title(fr_text: str) -> str:
    m = _TITLE_RE.search(fr_text[:131072])
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()[:160]


_SKIP_BLOCKS = re.compile(
    r"<(script|style|noscript|svg|template|iframe|object|embed|canvas|form|select)[^>]*>.*?</\1>",
    re.S | re.I,
)


def _visible_text(html: str, budget: int = 60000) -> str:
    """轻量可见文本提取（浏览器渲染结果的第二通道）：
    trafilatura 对"内容藏在模块/网格里"的页面会整页过滤，这里剥壳后按行收拢可见文字。
    输出为纯文本；超预算截断。"""
    if not html:
        return ""
    import html as _h

    body = _SKIP_BLOCKS.sub(" ", html)
    # 把块级标签当换行，其余标签去掉
    body = re.sub(r"<(br|/p|/div|/li|/h[1-6]|/tr|/section|/article|/header|/footer)[^>]*>", "\n", body, flags=re.I)
    body = re.sub(r"<[^>]+>", "", body)
    body = _h.unescape(body)
    seen: set[str] = set()
    out: list[str] = []
    used = 0
    for ln in body.splitlines():
        s = re.sub(r"[ \t\u3000]+", " ", ln).strip()
        if len(s) < 2 or s in seen:  # 去导航类重复行
            continue
        seen.add(s)
        if used + len(s) + 1 > budget:
            out.append("…（正文已截断，超过配置上限）")
            break
        out.append(s)
        used += len(s) + 1
    return "\n".join(out)


# ---- RSS 兜底（B 项改进）：正文提取失败时找同站 feed 读标题/摘要 ----
_RSS_ALT = re.compile(
    r'<link[^>]+(?:rel=["\']alternate["\'][^>]+type=["\']application/(rss|atom)\+xml["\']'
    r'|type=["\']application/(rss|atom)\+xml["\'][^>]+rel=["\']alternate["\'])[^>]*href=["\']([^"\']+)',
    re.I,
)
_TAG_STRIP = re.compile(r"<[^>]+>")


def _feed_links(html: str) -> list[str]:
    out: list[str] = []
    for m in _RSS_ALT.finditer(html):
        href = m.group(3)
        if href and not href.startswith(("javascript:", "#")):
            out.append(href)
    return out


def _feed_to_lines(xml_text: str, max_items: int = 20, max_chars_total: int = 40000) -> str:
    """把 RSS/Atom 转成“标题 - 链接 + 摘要”文本（兜底阅读用）。"""
    import html as _h
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""
    entries: list[tuple[str, str, str]] = []  # (title, link, snippet)
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = _TAG_STRIP.sub(" ", item.findtext("description") or "").strip()
        entries.append((title, link, desc))
    if not entries:  # Atom
        for e in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            title = ((e.findtext("{http://www.w3.org/2005/Atom}title")) or "").strip()
            link_el = e.find("{http://www.w3.org/2005/Atom}link")
            link = (link_el.get("href") if link_el is not None else "") or ""
            summ = _TAG_STRIP.sub(" ", (e.findtext("{http://www.w3.org/2005/Atom}summary") or "")).strip()
            entries.append((title, link, summ))
    if not entries:
        return ""
    lines: list[str] = []
    budget = max_chars_total
    for t, u, s in entries[:max_items]:
        line = f"- {_h.unescape(t) or '(无标题)'}"
        if u.startswith(("http://", "https://")):
            line += f"\n  {u}"
        if s:
            line += f"\n  {_h.unescape(s)[:400]}"
        if len(line) > budget:
            break
        budget -= len(line)
        lines.append(line)
    return "\n".join(lines)


def _rss_fallback(fetcher: PoliteFetcher, page_url: str, page_html: str, char_limit: int) -> ReadResult | None:
    """尽力找同站 RSS/Atom feed 兜底；失败返回 None（交由上层如实报错）。"""
    base_host = ""
    try:
        base_host = host_of(page_url)
    except WebError:
        return None
    for href in _feed_links(page_html or ""):
        feed_url = urljoin(page_url, href)
        try:
            if host_of(feed_url) != base_host:
                continue
            fr = fetcher.fetch(feed_url, respect_robots=True, max_bytes=1_500_000)
        except WebError:
            continue
        text = _feed_to_lines(fr.text, max_items=20, max_chars_total=char_limit)
        if text:
            return ReadResult(
                title=f"RSS 兜底（{page_url[:100]}）",
                url=feed_url,
                text=text,
                chars=len(text),
                pages=1,
                fetched=[f"RSS: {feed_url}"],
                truncated=len(text) >= char_limit,
                source="rss",
            )
    return None


def _with_page_param(base: str, param: str, value: int) -> str:
    """把 URL 里的 page/p/num 参数换成 value（无则追加）。"""
    u = urlparse(base)
    q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k.lower() != param.lower()]
    q.append((param, str(value)))
    return urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode(q), ""))


def _numeric_next(url: str) -> str | None:
    """数字页码兜底：?page=N → N+1；/path/N(.html) → N+1。"""
    u = urlparse(url)
    q = parse_qsl(u.query, keep_blank_values=True)
    for idx, (k, v) in enumerate(q):
        if k.lower() in ("page", "p", "pg", "num", "no") and _NUM_PARAM.match(v):
            return _with_page_param(url, k, int(v) + 1)
    m = _PATH_NUM.search(u.path)
    if m:
        new_path = u.path[: m.start(1)] + str(int(m.group(1)) + 1) + u.path[m.end(1):]
        return urlunparse((u.scheme, u.netloc, new_path, u.params, u.query, u.fragment))
    return None


def _next_candidates(url: str, html: str, mode: str = "page") -> list[str]:
    """找"续页"候选。
    mode='page'（默认）：只认数字页码分页形态（?page=N / p=N / /N(.html)），避免把
    相邻文章当续页；mode='any'：额外跟随 rel=next 与"下一页/下一条"锚点（会把
    站内"下一篇"也连读，适合公告流等场景，慎用）。"""
    cands: list[str] = []
    if mode == "any":
        for pat in (_REL_NEXT_LINK, _REL_NEXT_ANCHOR, _NEXT_TEXT_ANCHOR):
            for m in pat.finditer(html):
                href = m.group(1).strip()
                if href and not href.startswith(("javascript:", "#", "mailto:")):
                    cands.append(urljoin(url, href))
    num = _numeric_next(url)
    if num:
        cands.append(num)
    out, seen = [], set()
    base_host = host_of(url)
    for c in cands:
        try:
            if host_of(c) != base_host:
                continue
            key = normalize_url(c)
        except WebError:
            continue
        if key in seen or key == normalize_url(url):
            continue
        seen.add(key)
        out.append(c)
    return out


def read_page(url: str, max_pages: int = 0, max_chars: int = 0) -> ReadResult:
    max_pages = max(1, min(20, int(max_pages) or config.max_pages()))
    char_limit = int(max_chars) or config.max_page_chars()
    mode = config.paging_mode()

    fetcher = PoliteFetcher()
    cur = url.strip()
    seen: set[str] = set()
    texts: list[str] = []
    fetched: list[str] = []
    title = ""
    last_text = ""
    stop_reason = ""
    first_url = ""
    first_html = ""

    for page_i in range(max_pages):
        try:
            key = normalize_url(cur)
        except WebError:
            break
        if key in seen:
            break
        seen.add(key)
        try:
            fr = fetcher.fetch(cur, respect_robots=True)
        except SiteBlocked as e:
            if not fetched:
                raise  # 首页就被拒/不存在：如实上报，不让“提取失败”掩盖真实原因
            if "HTTP 404" in e.message or "HTTP 410" in e.message:
                stop_reason = "（下一页不存在，正文已到最后一页）"
            else:
                stop_reason = "（翻页被站点拒绝，保留已读内容）"
            break

        text = _extract(fr.text, fr.ctype)
        if not first_html:
            first_html = fr.text
            first_url = cur
        if not title:
            title = _html_title(fr.text)
        fetched.append(cur)
        if text:
            if text == last_text:  # 循环保护
                stop_reason = "（检测到重复内容，停止翻页）"
                texts.append(text)
                break
            texts.append(text)
            last_text = text
        if page_i + 1 >= max_pages:
            break
        # 找下一页
        nxt = None
        for c in _next_candidates(cur, fr.text, mode=mode):
            try:
                ck = normalize_url(c)
            except WebError:
                continue
            if ck not in seen:
                nxt = c
                break
        if nxt is None:
            break
        cur = nxt

    body = "\n\n".join(t for t in texts if t.strip())
    if not body.strip():
        # 兜底①：同站 RSS/Atom（很多新闻站 RSS 是静态可读的）
        if first_html:
            fb = _rss_fallback(fetcher, first_url or url, first_html, char_limit)
            if fb is not None:
                return fb
        # 兜底②（可选模式，能力自感知）：静态提取 + RSS 都失败 → 本机浏览器无头渲染重试。
        # 支持图像的调用模型也可走"截图→读图"；这里是纯文本渲染路径。
        if config.browser_used_for_read():
            from . import browser as _browser

            if _browser.browser_available():
                try:
                    rendered = _browser.render_dom(first_url or url)
                    btext = _extract(rendered, "text/html")
                    if not btext.strip():
                        # 第二通道：trafilatura 对模块化布局常整页过滤 → 轻量可见文本兜底
                        btext = _visible_text(rendered, char_limit)
                    if btext.strip():
                        if len(btext) > char_limit:
                            btext = btext[:char_limit] + "\n…（正文已截断，超过配置上限）"
                        btitle = title or _html_title(rendered) or "（浏览器渲染页）"
                        return ReadResult(
                            title=btitle,
                            url=first_url or url,
                            text=btext,
                            chars=len(btext),
                            pages=1,
                            fetched=[f"浏览器渲染: {first_url or url}"],
                            truncated=len(btext) >= char_limit,
                            source="web(browser)",
                        )
                except WebError:
                    pass  # 失败并入最终报错，如实说明
        raise ExtractionFailed(
            "未能从页面提取到正文，RSS 兜底与浏览器渲染兜底均不可用。可能原因：JS 渲染页（央视/环球/"
            "新华等首页）/ PDF / 图片页 / 付费墙 / 纯列表页 / 站点反爬。请换可阅读的具体文章页、其官方 RSS，"
            "或（若你是支持图像的模型）对页面截图后直接读图；本项目不绕过站点限制。"
        )
    truncated = len(body) > char_limit
    if truncated:
        body = body[:char_limit] + "\n…（正文已截断，超过配置上限）"
    return ReadResult(
        title=title,
        url=fetched[0] if fetched else url,
        text=body,
        chars=len(body),
        pages=len(fetched),
        fetched=[f"第{i+1}页: {u}" for i, u in enumerate(fetched)],
        truncated=truncated,
        source="web",
    )
