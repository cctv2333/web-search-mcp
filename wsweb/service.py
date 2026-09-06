"""服务编排：ws_search / ws_read 完整流程（结果报告为易读文本，全中文）。"""

from __future__ import annotations

import re

from . import config, filtering, providers, reader
from .errors import ContentTooLarge, RobotsDenied, SearchFailed, SiteBlocked, WebError
from .models import SearchResult, now_str
from .safety import PoliteFetcher

_NORM_RE = re.compile(r"[^\w\u4e00-\u9fff]+")


def _norm(s: str) -> str:
    return _NORM_RE.sub("", (s or "").lower())


def _title_match(expected: str, got: str) -> bool:
    if not expected or not got:
        return False
    if expected in got or got in expected:
        return len(expected) >= 6 or len(got) >= 6
    a, b = set(expected), set(got)
    inter = len(a & b)
    return inter / max(1, min(len(a), len(b))) >= 0.4


def _verify_top(kept: list[SearchResult], top_n: int) -> tuple[list[SearchResult], list[dict]]:
    """回访 TopN：404/410 剔除；403 注明未验证；标题严重不符加备注。全 best-effort，绝不因核验误杀。"""
    if top_n <= 0 or not kept:
        return kept, []
    fetcher = PoliteFetcher()
    out: list[SearchResult] = []
    dropped: list[dict] = []
    for i, r in enumerate(kept):
        if i >= top_n:
            out.append(r)
            continue
        try:
            fr = fetcher.fetch(r.url, respect_robots=True, max_bytes=96 * 1024)
            mt = re.search(r"<title[^>]*>(.*?)</title>", fr.text[:65536], re.S | re.I)
            got_title = re.sub(r"\s+", " ", mt.group(1)).strip()[:120] if mt else ""
            if got_title and not _title_match(_norm(r.title), _norm(got_title)):
                r.note = f"核验：源站标题与搜索标题不一致（源站: {got_title[:60]}），内容请以源站为准"
            out.append(r)
        except (RobotsDenied,) as e:
            r.note = "核验：站点 robots 拒绝抓取（结果保留，未核验正文）"
            out.append(r)
        except ContentTooLarge:
            out.append(r)
        except SiteBlocked as e:
            if "HTTP 404" in e.message or "HTTP 410" in e.message:
                dropped.append({"reason": "核验: 页面已不存在", "title": r.title, "url": r.url})
            else:
                r.note = "核验：站点拒绝直接抓取（结果保留，未核验正文）"
                out.append(r)
        except WebError:
            out.append(r)
        except Exception:
            out.append(r)
    return out, dropped


def run_search(query: str, provider_name: str = "bing", max_results: int = 8,
               verify: bool = True, exclude_kind: str = "") -> dict:
    q = (query or "").strip()
    if not q or len(q) > 512:
        raise SearchFailed("搜索词缺失或过长")
    max_results = max(1, min(20, int(max_results)))

    cls = providers.resolve_provider(provider_name)
    if not cls.available():
        raise SearchFailed(f"搜索源 {cls.name} 不可用：{cls.describe()}")
    raw = cls().search(q, max_results)
    if not raw:
        raise SearchFailed("该搜索源无返回结果")

    drop_kinds = set()
    for k in (exclude_kind or "").replace("，", ",").split(","):
        k = k.strip().lower()
        if k in ("reference", "ref", "参考", "百科"):
            drop_kinds.add("reference")
    kept, dropped = filtering.pipeline(raw, drop_kinds=drop_kinds or None)
    # 参考类默认置底展示（不剔除时仍清晰可见）
    kept.sort(key=lambda r: (r.kind == "reference", 0))
    kept = kept[:max_results]
    if verify:
        kept, drop_v = _verify_top(kept, config.verify_top_n())
        dropped += drop_v

    n_ref = sum(1 for r in kept if r.kind == "reference")
    lines = [
        f"搜索: {q}",
        f"来源: {cls.name}（{cls.describe()}）| 时间: {now_str()}",
        f"结果: {len(kept)} 条有效（原始 {len(raw)}，过滤剔除 {len(dropped)}）"
        + (f"，其中参考类 {n_ref} 条（已置底，可用 exclude_kind=reference 剔除）" if n_ref else ""),
        "=" * 46,
    ]
    if dropped:
        lines.append(f"已剔除 {len(dropped)} 条：")
        for d in dropped[:12]:
            lines.append(f"  · [{d['reason']}] {(d.get('title') or '')[:60]} {(d.get('url') or '')[:90]}")
        lines.append("=" * 46)
    for i, r in enumerate(kept, 1):
        lines.append(r.as_text(i))
    lines.append("=" * 46)
    lines.append("说明：结果经去重、广告/SEO 毒站过滤与 TopN 存活核验；词典/百科/音乐类已标注「参考」并置底；内容以源站为准，请点击原文核实，不构成任何建议。")
    report = "\n".join(lines)
    from .guard import boundary_header, injection_warning, scan_injection

    if config.mark_untrusted():
        report = boundary_header(f"搜索结果（{cls.name}）") + "\n" + report
    hits = scan_injection(report)
    if hits:
        report += "\n" + injection_warning(hits)
    return {"text": report, "count": len(kept), "dropped": len(dropped),
            "source": cls.name, "time": now_str()}


def run_read(url: str, max_pages: int = 0, max_chars: int = 0) -> object:
    return reader.read_page(url, max_pages=max_pages, max_chars=max_chars)  # S5/S6 前抛 NotReady
