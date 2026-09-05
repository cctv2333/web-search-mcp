# Web 搜索与阅读 MCP（`web-search-mcp`）

自定义本地 MCP 服务器：**搜得准、筛得净、读得动**——为 DeepSeek Harness（或任意 MCP
客户端）提供"网页搜索 + 广告/SEO 毒站过滤 + 网页全文阅读（含多页翻页）"。

- 技术：Python 3.10+ + **FastMCP v1**（`mcp>=1.2,<2`，与官方示例同一稳定写法）
- 搜索源：**Bing 免 Key**（RSS 主 → HTML 有机块兜底）；可选 **Tavily / 博查**（环境变量密钥，缺失自动不可用）
- 返回：全中文、带 `来源/时间/过滤说明/核验备注`，可点击原文核实
- 纪律：robots 尊重、限速、如实 UA、无 Cookie/JS、SSRF 防护、绝不绕过验证码/登录墙/付费墙

## 工具

| 工具 | 说明 |
|---|---|
| `ws_search` | 搜索（默认 bing；可选 tavily/bocha/auto）；结果经**类型打标**（百科/词典/音乐=参考类，默认标注并置底，`exclude_kind=reference` 可剔除）→ 去重 → 广告/毒站剔除 → TopN 存活核验 |
| `ws_read` | 抓取并阅读网页正文；多页文章自动翻页拼接（`WS_PAGING_MODE`：page=只信数字页码 / any=连 rel=next）；兜底链：静态提取 → 同站 RSS/Atom → **本机浏览器无头渲染**（`WS_BROWSER_MODE=auto`，JS 页也能读） |
| `ws_providers` | 查看当前可用搜索源与抓取配置 |
| `ws_ping` | 连通自检 |

接入后工具名形如 `mcp__<serverName>__ws_*`（以实际桥接命名规则为准）。

## 目录结构

```
web-search-mcp/
├─ server.py            入口（FastMCP，stdio）
├─ wsweb/               实现包（config/errors/models/urlutil/safety/filtering/providers/reader/service）
├─ requirements.txt     依赖（mcp<2 / requests / trafilatura；纯 ASCII，勿加非 ASCII 注释）
├─ .env.example         环境变量说明（密钥只走环境变量）
├─ test_self.py         自测（离线单测 + stdio 冒烟；不依赖外部客户端）
├─ demo_live.py         真机演示（需联网：真实搜索 + 阅读）
├─ setup.bat            一键：建 .venv + 装依赖 + 自测
├─ dsh-patch.example.yml   DeepSeek Harness 接入补丁示例（<REPO_DIR> 需替换为本机路径）
└─ README.md            本文件
```

## 安装与自测

```bat
setup.bat
:: 或手动：
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python test_self.py
```

## 搜索与过滤管线（实事求是，不静默丢好结果）

1. **搜索**：Bing RSS（免 Key，条款限个人非商业、低流量）→ 空/失败自动走 HTML
   有机块（只取 `li.b_algo`，跳过广告与 AI 摘要容器），解析 `bing.com/ck/a` 跳转得真实 URL。
2. **去重**：规范化 URL（去跟踪参数 `utm_*`/`gclid` 等 + 去 fragment）+ 标题双重去重。
3. **去毒**：广告/统计域名后缀黑名单、广告子域、跳转包装壳（google/bing/baidu/zhihu 跳转）
   → 剔除并列出原因；标题强广告信号且摘要空洞也剔除。**其余一律保留**。
4. **核验**（默认只核验前 1 条，`WS_VERIFY` 可调）：404/410 剔除；403/robots 拒绝→保留并加
   ⚠ 备注；源站标题与搜索标题严重不符→加 ⚠ 备注提醒，不误杀。

## 配置（环境变量，密钥绝不落盘）

| 变量 | 含义 | 默认 |
|---|---|---|
| `TAVILY_API_KEY` | 启用 Tavily（月免费 1000 credits） | 空=不可用 |
| `BOCHA_API_KEY` / `BOCHA_BASE_URL` | 启用博查（基址可切 `api.bocha.cn`） | 空=不可用 |
| `WS_ROBOTS` | 是否尊重 robots.txt | 1 |
| `WS_MIN_INTERVAL` | 同主机限速间隔秒 | 1.0 |
| `WS_TIMEOUT` | 单请求超时秒 | 15.0 |
| `WS_MAX_RESP_BYTES` | 单响应上限 | 2MB |
| `WS_MAX_PAGE_CHARS` / `WS_MAX_PAGES` | 单页输出/翻页上限 | 60000 / 5 |
| `WS_USER_AGENT` | 如实标识的 UA | 内置 |
| `WS_VERIFY` | TopN 核验条数 | 1 |
| `WS_PAGING_MODE` | 多页续读：`page`=只信数字页码分页（默认）；`any`=还跟 rel=next/下一页锚点（会把相邻文章连读，慎用） | page |
| `WS_BROWSER_MODE` | 浏览器渲染兜底：`auto`=静态+RSS失败才调本机 Edge/Chrome 无头渲染（默认）；`off`=关；`on`=遇 JS 页即用。`WS_BROWSER_PATH` 可指定浏览器路径 | auto |

## 接入 DeepSeek Harness

> 下方 `<REPO_DIR>` 一律替换为**克隆/放置本仓库的绝对路径**（如 `D:\tools\web-search-mcp`）；
> `<DSH_HOME>` 为 dsh 数据目录（默认 `%USERPROFILE%\.dsh`）。

### 方式 A：并入 profile 热生效（推荐）
编辑 `<DSH_HOME>\profiles\<profile>\cordis.patch.yml`（初始为 `[]`），追加：

```yaml
- insert:
    - id: local-websearch-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: websearch
        transport: stdio
        command: '<REPO_DIR>\.venv\Scripts\python.exe'
        args:
          - '<REPO_DIR>\server.py'
        cwd: !!js process.cwd()
        env:
          TAVILY_API_KEY: !!js '`${process.env.TAVILY_API_KEY ?? ""}`'
          BOCHA_API_KEY: !!js '`${process.env.BOCHA_API_KEY ?? ""}`'
```

profile 若为 `patchReload: live`：保存即热应用，无需重启 harness（增删 bundle 除外）。
启用 Tavily/博查需在**启动 dsh 前**把 Key 导出到 shell 环境。

### 方式 B：一次性 `--patch`
```bat
dsh web --patch <REPO_DIR>\dsh-patch.example.yml
```

### 方式 C：其它客户端（Claude Desktop / Chatbox / RoleplayChat 等）
`mcpServers` 下配（路径同上替换）：

```json
{
  "websearch": {
    "command": "<REPO_DIR>\\.venv\\Scripts\\python.exe",
    "args": ["<REPO_DIR>\\server.py"]
  }
}
```

## 边界与合规（如实声明）

- Bing RSS 输出带版权声明：仅限个人非商业低流量使用；其它用途需微软书面许可（本工具不提供
  商业化分发）。必要时可只保留 HTML 有机块或改用 Tavily/博查。
- 抓取尊重站点 robots 与风控：遇到 403/验证码/登录墙**如实报告，绝不绕过**；只抓登录前公开页。
- **能力自感知**：本工具输出纯文本。浏览器渲染兜底仅对静态+RSS 都读不到的 JS 页启用且同样尊重
  robots；若调用方模型支持图像输入，JS 页也可走"截图 → 模型读图"。
- 免费接口（Tavily 月 1000 credits、博查资源包）条款与额度可能变动，以官方为准。
- 本项目不构成投资/交易建议，也不产出任何观点，只做数据检索与整理。

## 进度

- [x] S1 骨架 / S2 Bing 免Key / S3 过滤核验管线 / S4 Tavily·博查 / S5 单页正文 / S6 多页翻页
- [x] S7 接入 dsh profile（热生效）
- [x] S8 功能实测（demo_live.py：真实 Bing 搜索 + 文档页正文提取）
- [ ] 模型工具注入最终确认：客户端重启/新开会话后调用 `mcp__websearch__ws_*`
