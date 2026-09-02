# -*- coding: utf-8 -*-
"""统一业务异常（对标项目书 11.1：service 层抛业务异常，API 层统一转 HTTP）。"""


class BizError(Exception):
    """业务异常：code 为机器可读错误码，message 为面向用户的中文提示。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class DomainError(BizError):
    """domain 过滤表达式解析错误。"""

    def __init__(self, message: str):
        super().__init__("domain_error", f"筛选条件错误：{message}")
