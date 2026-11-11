"""ORM 模型。`import app.models` 即可拿到全部表。"""

from app.models.celebrity import Celebrity, ResultCelebrity
from app.models.question import BankVersion, Question, QuestionBank
from app.models.result import Result
from app.models.session import Answer, TestSession

__all__ = [
    "Answer",
    "BankVersion",
    "Celebrity",
    "Question",
    "QuestionBank",
    "Result",
    "ResultCelebrity",
    "TestSession",
]
