"""结果过滤：去重 + 广告/SEO 毒站启发式剔除。

策略：宁可保留并标注，也不静默漏掉好结果；只对“高置信广告/跳转包装/垃圾站”动手。
"""

from __future__ import annotations

import re

from . import urlutil
from .models import SearchResult

# 广告/追踪/统计域名后缀（命中即剔）
AD_HOST_SUFFIXES = {
    "doubleclick.net", "googlesyndication.com", "googleadservices.com",
    "taboola.com", "outbrain.com", "criteo.com", "quantserve.com",
    "scorecardresearch.com", "amazon-adsystem.com", "rubiconproject.com",
    "pubmatic.com", "openx.net", "smartadserver.com", "adnxs.com",
}

# 跳转包装/聚合壳（不是内容本体）：命中剔
WRAPPER_PATTERNS = [
    (r"^https?://[^/]*google\.[^/]*/url\?", "Google 搜索跳转壳"),
    (r"^https?://[^/]*bing\.[^/]*/(ck/a|redirect)", "Bing 跳转壳"),
    (r"^https?://[^/]*baidu\.com/(link|s)\?", "百度跳转壳"),
    (r"^https?://[^/]*zhihu\.com/link\?", "知乎跳转壳"),
    (r"^https?://link\.[^/]+/\?", "通用跳转壳"),
    (r"/redirect\?", "redirect 参数跳转"),
    (r"/go\.php\?", "go.php 跳转"),
]

# 域名子串级别的广告暗示（subdomain 含 ad/ads/sponsored 等）
_AD_SUBDOMAIN = re.compile(r"(^|\.)(ads?|adserver|sponsored|adservice)(\.|$)", re.I)

# 标题/摘要里的强广告信号（命中给分，多信号才剔）
_STRONG_AD_TITLE = re.compile(
    r"(广告|推广|Sponsored|Advertisement|Advertorial|竞价|点击下载|立即领取|免费领取|注册即送)", re.I
)

# 参考类站点（百科/词典/音乐歌词/游戏wiki）：新闻类查询的典型"高置信度污染源"——
# 打标 kind=reference 并默认置底/可剔除，不静默混在主结果里。
REF_SUFFIX_NEWS_LIKE = set()  # 占位（暂无）
REF_DOMAINS = {
    # 百科
    "baike.baidu.com", "wikipedia.org", "wiktionary.org",
    # 词典/释义
    "zdic.net", "hanyu.baidu.com", "dict.youdao.com", "dictionary.cambridge.org",
    "merriam-webster.com", "thefreedictionary.com", "collinsdictionary.com",
    "dict.cn", "iciba.com", "cidian.baidu.com",
    # 音乐/歌词/娱乐内容库
    "music.163.com", "y.qq.com", "kugou.com", "kuwo.cn", "genius.com",
    "lyrics.com", "qqmusic.com",
    # 游戏/主题 wiki（fandom 系、minecraft wiki 等）
    "fandom.com", "minecraft.wiki", "bilibili.com/wiki",
}
_REF_URL_HINT = re.compile(r"/(dic|dictionary|cidian|cihai|baike)/?", re.I)


def classify_result(r: SearchResult) -> str:
    """按域名/URL 把百科/词典/音乐等归为 reference，其余保持 other/news 原样。"""
    host = ""
    if r.url.startswith(("http://", "https://")):
        try:
            host = urlutil.host_of(r.url)
        except Exception:
            host = ""
    if any(urlutil.domain_suffix_match(host, d) for d in REF_DOMAINS):
        return "reference"
    if host and _REF_URL_HINT.search(r.url):
        return "reference"
    return r.kind if r.kind in ("news", "reference") else "other"


def tag_kinds(results: list[SearchResult]) -> None:
    for r in results:
        r.kind = classify_result(r)


def drop_kind(results: list[SearchResult], kinds: set[str]) -> tuple[list[SearchResult], list[dict]]:
    """按类型剔除（如 exclude reference 词条）；返回 (保留, 剔除明细)。"""
    if not kinds:
        return results, []
    kept: list[SearchResult] = []
    dropped: list[dict] = []
    for r in results:
        if r.kind in kinds:
            dropped.append({"reason": f"参考类剔除({r.kind})", "title": r.title, "url": r.url})
        else:
            kept.append(r)
    return kept, dropped


def dedupe(results: list[SearchResult]) -> tuple[list[SearchResult], list[dict]]:
    """URL+标题双重去重；重复者丢弃，保留摘要更长的一条。"""
    seen: dict[str, SearchResult] = {}
    dropped: list[dict] = []
    for r in results:
        key = urlutil.dedupe_key(r.url, r.title)
        if key in seen:
            old = seen[key]
            if len(r.snippet) > len(old.snippet):
                dropped.append({"reason": "重复", "title": old.title, "url": old.url})
                seen[key] = r
            else:
                dropped.append({"reason": "重复", "title": r.title, "url": r.url})
            continue
        seen[key] = r
    return list(seen.values()), dropped


def filter_poison(results: list[SearchResult]) -> tuple[list[SearchResult], list[dict]]:
    """启发式剔除广告与跳转壳；保留结果不做误伤。"""
    kept: list[SearchResult] = []
    dropped: list[dict] = []
    for r in results:
        url = r.url
        host = urlutil.host_of(url) if url.startswith(("http://", "https://")) else ""
        reason = None
        if any(urlutil.domain_suffix_match(host, s) for s in AD_HOST_SUFFIXES):
            reason = "广告/统计域名"
        elif _AD_SUBDOMAIN.search(host):
            reason = "疑似广告子域"
        elif not url.startswith(("http://", "https://")):
            reason = "非 http(s) 链接"
        else:
            for pat, why in WRAPPER_PATTERNS:
                if re.match(pat, url, re.I):
                    reason = why
                    break
        if reason:
            dropped.append({"reason": reason, "title": r.title, "url": url})
            continue
        # 标题强广告信号：仅当标题本身像广告且摘要空洞时剔（保守）
        if _STRONG_AD_TITLE.search(r.title) and len((r.snippet or "").strip()) < 40:
            dropped.append({"reason": "疑似广告标题", "title": r.title, "url": url})
            continue
        kept.append(r)
    return kept, dropped


def pipeline(results: list[SearchResult], drop_kinds: set[str] | None = None) -> tuple[list[SearchResult], list[dict]]:
    """完整管线：类型打标 → 去重 → 去毒 → 按需剔除参考类。返回 (保留, 丢弃明细)。"""
    tag_kinds(results)
    uniq, d1 = dedupe(results)
    clean, d2 = filter_poison(uniq)
    if drop_kinds:
        clean, d3 = drop_kind(clean, drop_kinds)
    else:
        d3 = []
    return clean, d1 + d2 + d3
