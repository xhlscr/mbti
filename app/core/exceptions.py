"""领域异常与 HTTP 映射。

业务代码只抛 `DomainError` 的子类，不直接抛 HTTPException——
这样 service 层不依赖 FastAPI，能脱离 Web 框架测试。
"""

from __future__ import annotations


class DomainError(Exception):
    """所有业务异常的基类。"""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str = "") -> None:
        self.message = message or self.code
        super().__init__(self.message)


class InvalidBank(DomainError):
    status_code = 404
    code = "bank_not_found"


class InvalidType(DomainError):
    status_code = 400
    code = "invalid_type"


class SessionNotFound(DomainError):
    status_code = 404
    code = "session_not_found"


class SessionExpired(DomainError):
    status_code = 410
    code = "session_expired"


class ResultNotFound(DomainError):
    status_code = 404
    code = "result_not_found"


class CelebrityNotFound(DomainError):
    status_code = 404
    code = "celebrity_not_found"


class VersionFrozen(DomainError):
    status_code = 409
    code = "version_frozen"


class RateLimited(DomainError):
    status_code = 429
    code = "rate_limited"


class UnsupportedQuestionType(DomainError):
    status_code = 500
    code = "unsupported_question_type"
