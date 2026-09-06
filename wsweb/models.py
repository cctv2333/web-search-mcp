"""数据模型：搜索结果 / 阅读结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def now_str() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = "bing"          # bing / tavily / bocha
    site: str = ""                # 站点显示名或域名
    published: str = ""           # 发布时间（源提供时）
    note: str = ""                # 核验备注（非空时显示给调用方，不静默隐藏）
    kind: str = "other"           # news / reference(百科·词典·音乐等) / other

    def as_text(self, idx: int) -> str:
        head = self.title.strip()
        lines = [f"{idx}. {head}"]
        if self.kind == "reference":
            lines.append("   类型: 参考（百科/词典/音乐类，通常不是新闻资讯）")
        if self.published:
            lines.append(f"   时间: {self.published}")
        if self.site:
            lines.append(f"   站点: {self.site}")
        if self.note:
            lines.append(f"   ⚠ {self.note}")
        lines.append(f"   URL : {self.url}")
        if self.snippet:
            sn = self.snippet.strip().replace("\n", " ")
            lines.append(f"   摘要: {sn[:300]}")
        return "\n".join(lines)


@dataclass
class ReadResult:
    title: str
    url: str                      # 最终地址（可能经重定向）
    text: str
    chars: int = 0
    pages: int = 1
    fetched: list[str] = field(default_factory=list)
    truncated: bool = False
    source: str = "web"
    time: str = field(default_factory=now_str)

    def as_text(self) -> str:
        from . import config
        from .guard import injection_warning, scan_injection

        out = []
        if config.mark_untrusted():
            from .guard import boundary_header

            out.append(boundary_header(f"页面 {self.url}"))
        out += [
            f"标题: {self.title or '(未识别)'}",
            f"URL : {self.url}",
            f"来源: {self.source} | 读取时间: {self.time}",
            f"页数: {self.pages} | 正文约 {self.chars} 字符" + ("（已截断）" if self.truncated else ""),
        ]
        if len(self.fetched) > 1:
            out.append("已拼页码: " + ", ".join(self.fetched))
        out.append("")
        out.append(self.text)
        hits = scan_injection(self.text)
        if hits:
            out.append(injection_warning(hits))
        return "\n".join(out)
