"""环境变量配置。所有密钥/上限只在此读取；值每次调用现读，便于运行期改环境。"""

from __future__ import annotations

import os

VERSION = "0.1.0"
PROJECT_NAME = "Web搜索与阅读MCP"

# ---- 密钥（缺失返回 None，调用方做降级）----
def tavily_key() -> str | None:
    v = os.environ.get("TAVILY_API_KEY", "").strip()
    return v or None


def bocha_key() -> str | None:
    v = os.environ.get("BOCHA_API_KEY", "").strip()
    return v or None


def bocha_base_url() -> str:
    return os.environ.get("BOCHA_BASE_URL", "https://api.bochaai.com").rstrip("/")


# ---- 抓取纪律 ----
def user_agent() -> str:
    return os.environ.get(
        "WS_USER_AGENT",
        "WebSearchMCP/0.1 (personal research assistant; no tracking; low volume)",
    )


def robots_enabled() -> bool:
    return os.environ.get("WS_ROBOTS", "1").strip() not in ("0", "false", "no")


def min_interval() -> float:
    try:
        return max(0.0, float(os.environ.get("WS_MIN_INTERVAL", "1.0")))
    except ValueError:
        return 1.0


def max_response_bytes() -> int:
    try:
        return max(64 * 1024, int(os.environ.get("WS_MAX_RESP_BYTES", str(2 * 1024 * 1024))))
    except ValueError:
        return 2 * 1024 * 1024


def max_page_chars() -> int:
    try:
        return max(2000, int(os.environ.get("WS_MAX_PAGE_CHARS", "60000")))
    except ValueError:
        return 60000


def max_pages() -> int:
    try:
        return min(20, max(1, int(os.environ.get("WS_MAX_PAGES", "5"))))
    except ValueError:
        return 5


def paging_mode() -> str:
    """多页续读策略：'page'=只信数字页码分页（?page=N、/N.html，最稳，默认）；
    'any'=额外跟随 rel=next 与"下一页/下一条"锚点（会把相邻文章也连读，慎用）。"""
    v = os.environ.get("WS_PAGING_MODE", "page").strip().lower()
    return "any" if v == "any" else "page"


def browser_mode() -> str:
    """浏览器渲染兜底：'auto'（默认，静态+RSS 都失败时才用）/ 'on' / 'off'。"""
    v = os.environ.get("WS_BROWSER_MODE", "auto").strip().lower()
    return "on" if v in ("1", "on", "true", "yes") else ("off" if v in ("0", "off", "false", "no") else "auto")


def browser_used_for_read() -> bool:
    """ws_read 是否启用浏览器兜底（auto 语义=失败时兜底，恒允许尝试）。"""
    return browser_mode() != "off"


def verify_top_n() -> int:
    try:
        return max(0, int(os.environ.get("WS_VERIFY", "1")))
    except ValueError:
        return 1


def timeout_seconds() -> float:
    try:
        return max(3.0, float(os.environ.get("WS_TIMEOUT", "15.0")))
    except ValueError:
        return 15.0
