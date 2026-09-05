# Web 搜索与阅读 MCP —— 方案 v1.0（已批准，实施中）

> 流程：设想 → 实事求是 → 方针 → 计划 → 实施。本文档随实施进展更新。
> 落点：`F:\DeepSeek-Harness\config\examples\web-search-mcp`（用户 2026-09-05 选定）。
> 本目录文档只存本地；除非用户明示，不进入任何 git 仓库/不提交。

## 一、设想（已批准）

一个**自定义本地 MCP 服务器**，提供能搜、会筛、读得动的 Web 能力：
- `ws_search`：默认免 Key Bing；可选 Tavily/博查；结果去重 + 广告/SEO 毒站剔除 + TopN 存活核验。
- `ws_read`：礼貌抓取 + trafilatura 正文提取 + 多页文章自动翻页拼接。
- `ws_providers` / `ws_ping`：源状态与连通自检。
- 痛点对应：广告毒化→过滤管线；网站限制爬取→不"绕"而"礼"（robots/限速/如实UA/不破验证码）；
  自带 Key 复用→可插拔 Tavily/博查；多界面读完→多页阅读；反爬追踪→无痕无JS+SSRF防护。

## 二、实事求是（已核实结论）

- 本机只有一个 Harness 源码浅克隆 `F:\DeepSeek-Harness`（= `F:\deepseek-harness`，大小写不敏感同一目录；
  HEAD d347e70 0.1.3-alpha.1，仅供查阅）；**实际运行的 harness** = 全局 npm
  `@deepseek-ai/dsh v0.1.2-rc.1`（DSH_HOME=`C:\Users\cctv2\.dsh`，web profile `patchReload:live`）。
- **接入点**：编辑 `C:\Users\cctv2\.dsh\profiles\web\cordis.patch.yml`（现为 `[]`）→ 保存即热生效，
  无需重启。官方写法见 `apps/cli/config/examples/mcp-memory/*.cordis.yml`（`- insert:` + id/name/config）。
- `dsh-mcp-client` 已随运行版闭包安装（含 0.1.2-rc.1）；stdio spawn 子进程前会**清洗父环境**
  （剥 `/KEY|PASSWORD|SECRET|TOKEN/i` 与 `DSH_*`），故密钥需经补丁 env 用
  `!!js process.env.X` 显式传入，且须在**启动 dsh 前**导出。
- Bing 免 Key：`?format=rss` 实测可用（~10 条/无分页/地域重定向/个人非商业授权条款）；
  HTML 有机块取 `li.b_algo`（跳过广告）；`bing.com/ck/a?u=` 为 base64url 跳转需解码；
  TLS 指纹被拦时可加 `curl_cffi`（可选依赖）。Bing RSS 版权声明：个人非商业展示，其余需书面许可。
- Tavily：`POST api.tavily.com/search`，Bearer；免费 1000 credits/月（basic=1、advanced=2），超出
  $0.008/credit（官方 Credits&Pricing 页）。
- 博查：`POST <base>/v1/web-search`，Bearer；响应 Bing 兼容 `data.webPages.value[]`；
  RoleplayChat 在用基址 `api.bochaai.com`（本工具默认同源，`BOCHA_BASE_URL` 可切 `api.bocha.cn`）；
  免费额度在官方飞书文档（登录墙，未核实）。
- RoleplayChat（用户既有实现，本工具互补）：
  - 内置"必应搜索"为进程内预设（search_web→Bing+360 双源）；**无广告过滤、结果仅
    {Title,URL,Snippet}** → 本工具补过滤 + source/time/核验元数据。
  - SSRF/防盗链/GBK 解码/5min 缓存可借鉴；无速率限制（本工具已内置限速）。
- Python：base conda 3.12.9 无 mcp；金融例子钉 `mcp>=1.2,<2`（FastMCP v1 稳定写法，暂不跟进 v2）
  → 本项目沿用 v1 保持一致。官方 mcp SDK 已出 v2（FastMCP 改名 MCPServer），本项目不迁移。
- 磁盘：F 盘空闲 ~136GB；C 盘仅 ~3.6GB → 项目与 .venv 全部放 F 盘。

## 三、方针（已批准，9 条照单全收）

1. Python 3.12 + FastMCP v1（mcp>=1.2,<2），stdlib 传输，独立 .venv 于项目内。
2. 搜索源抽象：bing（默认免Key）/ tavily / bocha（env 密钥存在才可用）；auto→bing。
3. 过滤管线：规范化去重 → 广告/毒站启发式（黑名单+特征，保守）→ TopN 存活核验（404剔/403注/标题不符注）。
4. 抓取纪律：只 http/https；如实 UA；robots 尊重（可关）；限速；无 Cookie/JS；不绕 403/验证码/登录墙。
5. SSRF 防护：内网/回环/保留地址 + DNS 复查；重定向逐跳复查 ≤5；体积上限（默认 2MB）。
6. 多页阅读：trafilatura 正文；rel=next / 下一页锚点 / 数字页码 探测拼接；默认 ≤5 页；循环/重复保护。
7. 密钥只走环境变量（TAVILY_API_KEY/BOCHA_API_KEY/BOCHA_BASE_URL/WS_*）；绝不落盘；状态页只回显是否配置。
8. 接入当前 DSH 会话：cordis.patch.yml 追加 `- insert:` 条目（stdio，.venv python + server.py 绝对路径），
   保存热生效 → 本会话以 `mcp__websearch__ws_*` 调用实测。
9. 交付形态：项目含 server.py+wsweb 包+依赖+安装自测脚本+README（DSH/Claude/RoleplayChat 三种接法）+PLAN。

## 四、计划与进度

| 步骤 | 内容 | 状态 |
|---|---|---|
| S1 | 骨架：目录/依赖/server.py/ws_ping 自测 | ✅ 通过（自测全绿） |
| S2 | Bing 免 Key（RSS 主 + HTML li.b_algo 兜底 + ck/a 解码） | ✅ 通过（真机 RSS 200 + 8 条有机结果实测） |
| S3 | 过滤管线（去重/毒站/核验+⚠备注） | ✅ 通过（单测并入；实测 404/403/robots 分支均验证） |
| S4 | Tavily/博查可插拔（env 密钥、缺失优雅不可用） | ✅ 代码完成（无 Key 环境走不可用分支，等用户补 Key 实测） |
| S5 | ws_read：礼貌抓取+SSRF+trafilatura 正文+体积限制 | ✅ 通过（api-docs 页 1066 字符提取；JS 页如实报错） |
| S6 | 多页翻页拼接（rel=next/锚点/数字页码，循环保护） | ✅ 通过（单测覆盖；真机待多页站点验证） |
| S7 | 接入 cordis.patch.yml → 热生效 | ✅ 生效：dump-config EXIT=0；harness 常驻拉起 server 子进程；改配置值即热重载（多次验证 PID 轮换） |
| S8 | 本会话实测（ws_search/ws_read 演示） | ✅ 会话内真实调用：`mcp__websearch__ws_search` 搜"国际新闻信息"返回 8 条有机结果；`ws_read` 文档页中文正常——page 模式 1 页 695 字符、any 模式 5 页 7444 字符连读实测 |

**实施期修复记录**
- SSRF 首版 bug：`_is_public_ip` 对"非 IP 的域名"也返回 False，导致域名全被当字面 IP 拦截；
  修正为"先判字面 IP，域名走 DNS 复查"（127.0.0.1 仍拦截，bing/example.com 放行）——2026-09-05。
- 页面解码乱码：requests 对无 charset 的响应默认按 ISO-8859-1 解码，UTF-8 中文变乱码；
  新增 `_smart_decode`（头 charset → meta charset → utf-8 严格 → gb18030 → 兜底）——2026-09-05。
- 多页语义收紧：Docusaurus 等站的 rel=next 指向"下一篇"而非本页续页；新增 `WS_PAGING_MODE`
  （默认 page=只信数字页码分页；any 才跟随 rel=next/下一页锚点）——2026-09-05。
- 搜索污染治理（外部压测发现，A 项）：百科/词典/音乐词条在通用索引里权重高、常污染"新闻类"查询；
  新增结果**类型打标**：词典/百科/音乐/游戏wiki 域 → kind=reference，默认标注「参考」并置底展示，
  `ws_search(exclude_kind=reference)` 可显式剔除（实测：搜"最近国际新闻"6/8 条参考类被正确标注/剔除）——2026-09-05。
- 抓取降级（外部压测发现，B 项）：正文提取失败时自动探测同站 RSS/Atom（rel=alternate feed）读标题摘要
  兜底；无 feed 时错误信息明确提示 JS 渲染/付费墙等成因与出路，不假装成功——2026-09-05。
- 浏览器渲染兜底（用户提出，可选模式）：静态 + RSS 都失败时调本机 Edge/Chrome 无头 --dump-dom
  渲染 JS 页再提取（WS_BROWSER_MODE: auto/on/off，WS_BROWSER_PATH 可指定）；仍尊重 robots、
  不绕验证码。修一个真 bug：trafilatura 对模块化布局整页过滤 → 新增 _visible_text 轻量可见文本
  第二通道。能力自感知：ws_providers/instructions 明示"支持图像的模型可截图读图"——2026-09-05。
- 外部审计（另一位 AI 云/Linux/安全审）：复现 **Bing RSS 链接污染**（zhihu 等 link 被追加
  `%20标题%20lang:zh` 尾）→ 新增 `_clean_link` 净化（仅在带 lang: 签名时截断，不误伤）；云部署适配：
  browser.py 候选路径加 Linux、新增 setup.sh、README 加"云/Linux 部署"节（venv bin/python、TZ、
  chromium 可选、stdio 仅同机）；全量回归通过——2026-09-05。
- SSRF 域名策略补丁：aljazeera 等站点 v4 公网 + Teredo 前缀 v6 混合解析被旧"任一非公网即拦"误杀；
  改为"全部非公网才拦，混合即放行"，含单测（全私网拦/混合放行/公网v6放行/字面IP拦）——2026-09-05。
- requirements.txt 中文注释导致 pip 在 Windows 按 GBK 读取失败 → 改纯 ASCII。
- pip 默认源二进制下载近乎停滞 → 换清华镜像安装成功。
- mcp v1 list_tools 返回形态兼容（tools/cursor 元组）已处理。test_self 输出强制 UTF-8。

**风险与边界**：免 Key Bing 可能被风控（429/验证）→ 已备 HTML 兜底与 curl_cffi 可选项、tavily/bocha
替代；Bing RSS 授权限个人非商业低流量（README 已声明）；付费墙/JS 渲染页如实报"提取失败"，不绕过。

## 五、评审记录

- 2026-09-05 用户拍板：落点 F:\DeepSeek-Harness\config\examples\web-search-mcp；Python+FastMCP；
  五项功能全选；先接当前 DSH 会话验证。方针 1-9 照单全收，按 S1→S8 实施。
