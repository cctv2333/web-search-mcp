#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Web 搜索与阅读 MCP —— 入口（stdio 传输，FastMCP v1）。

工具：ws_ping / ws_providers / ws_search / ws_read
接入 DeepSeek Harness：见 README.md「接入」；工具将以 mcp__<serverName>__ws_* 出现。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from wsweb import config, service  # noqa: E402
from wsweb.errors import WebError  # noqa: E402

INSTRUCTIONS = (
    "Web 搜索与阅读工具集（ws_*）。用法建议：\n"
    "1. ws_search 搜网页：默认 Bing 免Key；结果已做去重、广告/SEO毒站过滤与参考类标注（剔除项会列出原因）。\n"
    "2. 对需要深读的链接用 ws_read 抓正文：静态抓取 → 同站RSS兜底 → 本机浏览器无头渲染兜底（JS 页）。\n"
    "3. ws_read 支持多页文章自动翻页拼接（默认最多 5 页，WS_PAGING_MODE 可调）。\n"
    "4. ws_providers 查看可用搜索源与阅读能力（含浏览器渲染可用性）。\n"
    "5. 能力自感知：本工具给的是纯文本。若调用方（模型）支持图像输入（GUI 已启用视觉模型），"
    "JS 渲染页也可对页面截图后由模型直接读图；否则依赖 ws_read 的浏览器渲染兜底。\n"
    "6. 抓取纪律：尊重 robots、限速、不绕验证码/登录墙；被站点拒绝时如实报错并说明替代路径。\n"
    "所有返回均为中文，标注来源与时间；内容以源站为准，重要信息请点击原文核实。"
)

mcp = FastMCP("Web搜索与阅读", instructions=INSTRUCTIONS)


def _ok(data: dict) -> str:
    return data["text"]


@mcp.tool()
def ws_ping() -> str:
    """连通性自检：返回服务名、版本、当前时间。"""
    return (
        f"pong | {config.PROJECT_NAME} v{config.VERSION} | "
        f"时间 {__import__('wsweb.models', fromlist=['now_str']).now_str()} | "
        f"Python {sys.version.split()[0]}"
    )


@mcp.tool()
def ws_providers() -> str:
    """查看当前可用的搜索源（bing 免Key 恒可用；tavily/bocha 需环境变量密钥）与抓取/阅读能力。"""
    from wsweb import browser as _browser

    rows = []
    for p in service.providers.list_provider_status():
        rows.append(f"- {p['name']}: {'可用' if p['available'] else '不可用'} — {p['note']}")
    bmode = config.browser_mode()
    brow = _browser.find_browser()
    cap = [
        "- 浏览器渲染兜底: " + ("可用" if brow else "不可用（未找到 Edge/Chrome，可设 WS_BROWSER_PATH）")
        + f" | 模式 {bmode}（auto=静态+RSS失败才用；WS_BROWSER_MODE=off 可关）",
        "- 视觉读图: 由调用模型能力决定（本工具输出纯文本；支持图像的模型可截图后读图）",
    ]
    cfg = [
        f"- robots.txt 尊重: {'开' if config.robots_enabled() else '关'}",
        f"- 限速间隔: {config.min_interval()}s | 单响应上限: {config.max_response_bytes() // 1024}KB",
        f"- 单页输出上限: {config.max_page_chars()} 字符 | 多页上限: {config.max_pages()} 页 | 翻页模式: {config.paging_mode()}",
        f"- UA: {config.user_agent()}",
    ]
    return (
        "可用搜索源：\n" + "\n".join(rows) + "\n阅读能力：\n" + "\n".join(cap)
        + "\n抓取配置：\n" + "\n".join(cfg)
    )


@mcp.tool()
def ws_search(query: str, provider: str = "bing", max_results: int = 8, verify: bool = True,
              exclude_kind: str = "") -> str:
    """网页搜索（默认免 Key Bing）。query 必填；provider 可选 bing/tavily/bocha/auto；
    max_results 1-20；verify 是否对前几条做存活核验；exclude_kind 传 reference 可把
    词典/百科/音乐类词条剔除（不传则标注「参考」并置底显示）。返回已过滤结果与剔除明细。"""
    try:
        data = service.run_search(query, provider_name=provider, max_results=max_results,
                                  verify=verify, exclude_kind=exclude_kind)
        return _ok(data)
    except WebError as e:
        return f"搜索未完成：{e.to_text()}"
    except Exception as e:  # 兜底：如实报告，不崩溃
        return f"搜索未完成：内部错误 {type(e).__name__}: {e}"


@mcp.tool()
def ws_read(url: str, max_pages: int = 0, max_chars: int = 0) -> str:
    """抓取并阅读网页正文。url 必填；max_pages/max_chars 为 0 时用环境默认（5 页 / 60000 字符）。
    多页文章自动翻页拼接；403/验证码墙等如实报错，绝不绕过。"""
    try:
        return service.run_read(url, max_pages=max_pages, max_chars=max_chars).as_text()
    except WebError as e:
        return f"阅读未完成：{e.to_text()}"
    except Exception as e:
        return f"阅读未完成：内部错误 {type(e).__name__}: {e}"


if __name__ == "__main__":
    mcp.run()
