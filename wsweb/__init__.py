"""wsweb —— Web 搜索与阅读 MCP 的实现包。

模块分工：
- config     环境变量配置（密钥只在此读取，绝不下沉/落盘）
- errors     结构化错误
- models     结果/页面数据模型
- urlutil    URL 规范化、去重、Bing 跳转解码
- safety     SSRF 防护 + robots/限速的礼貌抓取器
- filtering  去重 + 广告/SEO 毒站过滤
- providers  搜索源（bing 免Key 默认；tavily/bocha 可选）
- reader     正文提取 + 多页翻页阅读
- service    编排：ws_search / ws_read 的完整流程
"""

__version__ = "0.1.0"
