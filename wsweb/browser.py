"""浏览器渲染兜底（可选模式，方针 4 扩展）：本机 Edge/Chrome 无头 --dump-dom 读取 JS 渲染页。

用途：静态抓取 + RSS 兜底都失败时（央视/环球/mcpcn 等 JS 站），用本机浏览器内核
渲染后再提取文本。仍守纪律：SSRF 防护、robots 尊重、不绕验证码/登录墙；被反爬拦则如实报。
调用方（模型）能力自感知：支持图像输入的模型可另走"截图→读图"；本模块是纯文本兜底。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from . import config
from .errors import SiteBlocked, WebError
from .safety import RobotsGate, check_public_http

_ENV_PATH = "WS_BROWSER_PATH"
_CANDIDATES = [
    # Windows
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    # Linux / 云部署常见路径（找不到只是少一个兜底通道，不会崩）
    "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
    "/usr/bin/microsoft-edge", "/usr/bin/microsoft-edge-stable",
]
_cached: str | None = None
_scanned = False


def find_browser() -> str | None:
    """定位可用浏览器（env 覆盖 > 常见路径 > PATH）。结果进程内缓存。"""
    global _cached, _scanned
    if _scanned:
        return _cached
    _scanned = True
    env = os.environ.get(_ENV_PATH, "").strip()
    if env and os.path.isfile(env):
        _cached = env
        return _cached
    for p in _CANDIDATES:
        if os.path.isfile(p):
            _cached = p
            return _cached
    for name in ("msedge", "chrome", "chromium", "google-chrome", "microsoft-edge"):
        p = shutil.which(name)
        if p:
            _cached = p
            return _cached
    return None


def browser_available() -> bool:
    return find_browser() is not None


def render_dom(url: str, budget_ms: int = 12000, timeout_s: float = 45.0) -> str:
    """用无头浏览器渲染 URL 并返回渲染后的 HTML 文本。失败抛 WebError（如实）。"""
    exe = find_browser()
    if not exe:
        raise WebError("BROWSER_UNAVAILABLE: 未找到 Edge/Chrome（可用 WS_BROWSER_PATH 指定）")
    check_public_http(url)  # SSRF 防护
    if config.robots_enabled():
        if not RobotsGate().allows(url, config.user_agent()):
            raise SiteBlocked("robots.txt 禁止抓取；浏览器渲染同样不绕过")
    workdir = tempfile.mkdtemp(prefix="wsb_")
    try:
        cmd = [
            exe, "--headless=new", "--disable-gpu", "--no-first-run",
            "--hide-scrollbars", "--disable-extensions",
            f"--user-data-dir={os.path.join(workdir, 'profile')}",
            f"--virtual-time-budget={budget_ms}",
            "--dump-dom", url,
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise SiteBlocked(f"浏览器渲染超时（>{timeout_s:.0f}s）：{url[:100]}")
    except OSError as e:
        raise SiteBlocked(f"浏览器启动失败：{e}")
    finally:
        import shutil as _sh

        _sh.rmtree(workdir, ignore_errors=True)
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace")[-400:]
        raise SiteBlocked(f"浏览器渲染失败（exit {proc.returncode}）：{err[:200]}")
    html = (proc.stdout or b"").decode("utf-8", "replace")
    if not html or "<html" not in html[:2000].lower():
        # 某些反爬返回空壳/验证页：如实报
        if "验证" in html[:4000] or "captcha" in html[:4000].lower():
            raise SiteBlocked("目标站点要求验证（验证码/人机校验），浏览器渲染不绕过")
        raise SiteBlocked(f"浏览器渲染未得到有效页面：{url[:100]}")
    return html
