"""结构化错误：每个错误带机器可读 code 与中文说明，工具层据此返回不崩溃。"""

from __future__ import annotations


class WebError(Exception):
    code = "WEB_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def to_text(self) -> str:
        return f"[{self.code}] {self.message}"


class ConfigError(WebError):
    code = "CONFIG_ERROR"


class ProviderError(WebError):
    code = "PROVIDER_ERROR"


class SearchFailed(ProviderError):
    code = "SEARCH_FAILED"


class NotReady(WebError):
    """骨架阶段占位：某能力尚未实现到该步骤。"""

    code = "NOT_READY"


class UnsupportedScheme(WebError):
    code = "UNSUPPORTED_SCHEME"


class SSRFBlocked(WebError):
    code = "SSRF_BLOCKED"


class RobotsDenied(WebError):
    code = "ROBOTS_DENIED"


class SiteBlocked(WebError):
    """403/验证码墙等站点主动拒绝：如实报告，绝不绕过。"""

    code = "SITE_BLOCKED"


class ContentTooLarge(WebError):
    code = "CONTENT_TOO_LARGE"


class ExtractionFailed(WebError):
    code = "EXTRACTION_FAILED"
