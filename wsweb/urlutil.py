"""URL 工具：跟踪参数清洗、规范化、去重键、Bing 跳转解码。"""

from __future__ import annotations

import base64
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .errors import UnsupportedScheme

# 常见跟踪/统计参数（只清确定无内容的，避免误伤）
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "yclid", "igshid", "mc_cid", "mc_eid",
    "ref", "referrer", "spm", "scm", "share_token", "wt_mc", "from", "from_id",
    "cmpid", "tpcc", "mod", "mkt_tok", "vero_id",
}


def parse_http_url(url: str):
    """解析并校验 http/https，返回 urlparse 结果；否则抛 UnsupportedScheme。"""
    if not url or len(url) > 8192:
        raise UnsupportedScheme("URL 缺失或过长")
    u = urlparse(url.strip())
    if u.scheme.lower() not in ("http", "https") or not u.netloc:
        raise UnsupportedScheme(f"仅支持 http/https：{url[:80]}")
    return u


def strip_tracking(url: str) -> str:
    u = parse_http_url(url)
    q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k.lower() not in _TRACKING_PARAMS]
    return urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode(q), ""))  # 去 fragment


def normalize_url(url: str) -> str:
    """小写 host、去默认端口、去 fragment、去跟踪参数；保留路径与大小写。"""
    u = parse_http_url(url)
    netloc = u.netloc.lower()
    if u.scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif u.scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]
    netloc = netloc.rstrip(".")
    q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k.lower() not in _TRACKING_PARAMS]
    if not q:
        return urlunparse((u.scheme, netloc, u.path or "/", u.params, "", ""))
    return urlunparse((u.scheme, netloc, u.path or "/", u.params, urlencode(q), ""))


def dedupe_key(url: str, title: str = "") -> str:
    n = normalize_url(url)
    t = re.sub(r"\s+", " ", title or "").strip().lower()[:80]
    return n if not t else f"{n}|{t}"


def host_of(url: str) -> str:
    return parse_http_url(url).netloc.split("@")[-1].split(":")[0].lower()


def domain_suffix_match(host: str, suffix: str) -> bool:
    host = host.lower()
    suffix = suffix.lower().lstrip(".")
    return host == suffix or host.endswith("." + suffix)


def decode_bing_redirect(url: str) -> str:
    """解码 bing.com/ck/a?u=<base64url> 之类的跳转包装，返回真实 URL。"""
    u = urlparse(url)
    host = (u.netloc or "").lower()
    if not (host.endswith("bing.com") or host.endswith("bing.net")):
        return url
    if u.path.startswith("/ck/a"):
        q = dict(parse_qsl(u.query))
        enc = q.get("u", "")
        if enc:
            try:
                pad = "=" * (-len(enc) % 4)
                raw = base64.urlsafe_b64decode(enc + pad)
                dec = raw.decode("utf-8", "ignore")
                if dec.startswith(("http://", "https://")):
                    return dec
            except Exception:
                pass
    return url
