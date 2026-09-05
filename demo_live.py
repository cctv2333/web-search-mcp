#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S8 实测演示：走 stdio 起 server.py，真实调用 ws_search / ws_read。
用法：.venv\\Scripts\\python.exe demo_live.py ["查询词"] ["阅读URL"]
输出 UTF-8；需联网。
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

SERVER = pathlib.Path(__file__).resolve().parent / "server.py"
Q = sys.argv[1] if len(sys.argv) > 1 else "贵州茅台 2026 最新财报 股价"
READ_URL = sys.argv[2] if len(sys.argv) > 2 else ""


def _txt(content) -> str:
    parts = []
    for c in content:
        t = getattr(c, "text", None)
        parts.append(t if isinstance(t, str) else str(c))
    return "\n".join(parts)


async def call(sess, name: str, args: dict) -> str:
    r = await sess.call_tool(name, args)
    return _txt(r.content)


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=None)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as sess:
            await sess.initialize()

            print("=" * 70)
            print(f"[ws_providers] 搜索源与抓取配置")
            print("=" * 70)
            print(await call(sess, "ws_providers", {}))

            print("\n" + "=" * 70)
            print(f"[ws_search] 真实查询：{Q}（Bing 免Key + 过滤/核验）")
            print("=" * 70)
            out = await call(sess, "ws_search", {"query": Q, "max_results": 8})
            print(out)

            target = READ_URL
            if not target:
                # 从上面的搜索里挑第一条有效结果的 URL（粗略找 https 行）
                for line in out.splitlines():
                    line = line.strip()
                    if line.startswith("URL : http"):
                        target = line[5:].strip()
                        break
            if target:
                print("\n" + "=" * 70)
                print(f"[ws_read] 阅读搜索结果链接（演示正文提取，多页自动拼接）：{target[:100]}")
                print("=" * 70)
                try:
                    print(await call(sess, "ws_read", {"url": target}))
                except Exception as e:  # noqa: BLE001
                    print(f"阅读失败：{e}")
            return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
