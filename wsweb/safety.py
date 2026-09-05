"""安全与礼貌抓取：SSRF 防护、robots.txt 尊重、限速、体积上限。

设计原则（方针 4/5）：绝不绕过站点风控；对可疑目标先拦后问；如实 UA、无 Cookie、
无 JS；只抓登录前公开内容。
"""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from . import config
from .errors import ContentTooLarge, RobotsDenied, SSRFBlocked, SiteBlocked, UnsupportedScheme
from .urlutil import parse_http_url

_BLOCK_HINTS = {"localhost", ".local", ".internal", ".lan", ".home.arpa"}


def _is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
        or addr.is_multicast or addr.is_unspecified or addr.is_global is False
    )


def _smart_decode(raw: bytes, content_type: str = "") -> str:
    """可靠解码：先按头里 charset，再 meta charset，再 utf-8 严格，再 gb18030，最后替换。
    requests 对无 charset 的响应默认按 ISO-8859-1 解码，会把 UTF-8 中文搞成乱码——这里绕开它。"""
    import re as _re

    candidates: list[str] = []
    m = _re.search(r"charset\s*=\s*[\"']?([\w-]+)", content_type, _re.I)
    if m:
        candidates.append(m.group(1))
    head = raw[:4096].decode("latin-1", errors="ignore")
    m = _re.search(r'<meta[^>]+charset\s*=\s*["\']?([\w-]+)', head, _re.I)
    if m:
        candidates.append(m.group(1))
    candidates += ["utf-8", "gb18030"]
    seen: set[str] = set()
    for enc in candidates:
        enc = (enc or "").strip()
        if not enc or enc in seen:
            continue
        seen.add(enc)
        try:
            return raw.decode(enc)  # 严格解码：成功即认为正确
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def check_public_http(url: str) -> str:
    """校验 URL 为 http/https 且解析结果均为公网地址；返回规范化 host。返回解析 IP 列表失败即拦。"""
    u = parse_http_url(url)
    host = u.hostname or ""
    if not host:
        raise UnsupportedScheme("URL 缺少主机名")
    hl = host.lower()
    if any(hl.endswith(s) for s in _BLOCK_HINTS):
        raise SSRFBlocked(f"疑似内网/保留主机名：{host}")
    # 字面 IP 直接判
    try:
        ipaddress.ip_address(host)  # 抛 ValueError 说明是域名，不是字面 IP
    except ValueError:
        pass
    else:
        if not _is_public_ip(host):
            raise SSRFBlocked(f"目标地址非公网：{host}")
        return host
    # 域名：DNS 复查（防 DNS 重绑定）。策略：全部解析结果都非公网才拦截；
    # 只要存在公网地址就放行——许多 CDN/站点同时公布 v4 与特殊前缀 v6
    # （如 Teredo 2001::/32），"任一非公网即拦"会误杀这类站点（实测 aljazeera）。
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise SSRFBlocked(f"域名解析失败：{host}")
    ips = sorted({i[4][0] for i in infos})
    if not ips:
        raise SSRFBlocked(f"域名无解析结果：{host}")
    if not any(_is_public_ip(ip) for ip in ips):
        raise SSRFBlocked(f"目标解析结果全部非公网（{host} → {ips[:3]}），已拦截")
    return host


@dataclass
class FetchResult:
    final_url: str
    status: int
    ctype: str
    text: str
    headers: dict = field(default_factory=dict)


class RobotsGate:
    """robots.txt 缓存与裁决（每主机一次抓取）。"""

    def __init__(self) -> None:
        self._parsers: dict[str, RobotFileParser | None] = {}

    def allows(self, url: str, ua: str) -> bool:
        host = check_public_http(url)  # 复用 SSRF 校验，顺带拿规范 host
        u = urlparse(url)
        if u.scheme == "https" and u.port == 443:
            pass
        key = f"{u.scheme}://{host}"
        if key not in self._parsers:
            self._parsers[key] = self._load(key, ua)
        rp = self._parsers[key]
        if rp is None:
            return True  # 拿不到 robots.txt（404/超时）视为允许，但会走限速
        return rp.can_fetch(ua, url)

    @staticmethod
    def _load(key: str, ua: str) -> RobotFileParser | None:
        try:
            resp = requests.get(key + "/robots.txt", headers={"User-Agent": ua}, timeout=8)
            if resp.status_code >= 400:
                return None
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            return rp
        except Exception:
            return None


class PoliteFetcher:
    """无状态、限速、防 SSRF 的抓取器（手动重定向逐跳校验）。"""

    def __init__(self) -> None:
        self._robots = RobotsGate()
        self._last: dict[str, float] = {}

    def _throttle(self, host: str) -> None:
        gap = config.min_interval()
        if gap <= 0:
            return
        t = self._last.get(host, 0.0)
        wait = t + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.time()

    def fetch(self, url: str, *, respect_robots: bool = True,
              max_bytes: int | None = None, timeout: float | None = None) -> FetchResult:
        max_bytes = max_bytes or config.max_response_bytes()
        timeout = timeout or config.timeout_seconds()
        ua = config.user_agent()
        current = url
        for hop in range(6):  # 最多 5 次重定向
            host = check_public_http(current)
            if respect_robots and config.robots_enabled():
                if not self._robots.allows(current, ua):
                    raise RobotsDenied(f"站点 robots.txt 禁止抓取：{current[:120]}")
            self._throttle(host)
            try:
                resp = requests.get(
                    current,
                    headers={
                        "User-Agent": ua,
                        "Accept": "text/html,application/xhtml+xml,text/plain,application/xml;q=0.9,*/*;q=0.5",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
                    },
                    stream=True,
                    allow_redirects=False,
                    timeout=timeout,
                    verify=True,
                )
            except requests.exceptions.SSLError:
                raise SiteBlocked(f"TLS 校验失败，已拒绝：{current[:120]}")
            except requests.exceptions.RequestException as e:
                raise SiteBlocked(f"请求失败：{type(e).__name__}: {current[:120]}")

            loc = resp.headers.get("Location")
            if resp.status_code in (301, 302, 303, 307, 308) and loc:
                from urllib.parse import urljoin
                current = urljoin(current, loc)
                resp.close()
                if hop == 5:
                    raise SiteBlocked("重定向次数超限")
                continue

            if resp.status_code in (401, 403):
                resp.close()
                raise SiteBlocked(f"站点拒绝访问（HTTP {resp.status_code}，可能为风控/登录墙）：{current[:120]}")
            if resp.status_code in (404, 410):
                resp.close()
                raise SiteBlocked(f"页面不存在（HTTP {resp.status_code}）：{current[:120]}")
            if resp.status_code >= 400:
                resp.close()
                raise SiteBlocked(f"站点返回 HTTP {resp.status_code}：{current[:120]}")

            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            chunks: list[bytes] = []
            total = 0
            too_large = False
            for chunk in resp.iter_content(65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    too_large = True
                    break
                chunks.append(chunk)
            resp.close()
            if too_large:
                raise ContentTooLarge(
                    f"响应超过 {max_bytes // 1024}KB 上限（如需更大请调 WS_MAX_RESP_BYTES）：{current[:120]}"
                )
            raw = b"".join(chunks)
            text = _smart_decode(raw, resp.headers.get("Content-Type") or "")
            return FetchResult(final_url=current, status=resp.status_code,
                               ctype=ctype, text=text, headers=dict(resp.headers))
        raise SiteBlocked("重定向次数超限")
