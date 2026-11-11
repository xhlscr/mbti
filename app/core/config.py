"""应用配置。所有环境变量以 `MBTI_` 前缀注入。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]          # backend/app


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MBTI_", extra="ignore")

    app_name: str = "mbti-api"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://mbti:mbti@localhost:5432/mbti"

    # 连接/建表超时：数据库没起时快速失败，不让 uvicorn 卡在 startup
    db_connect_timeout: int = 3
    db_init_timeout_seconds: float = 8.0

    # 业务参数
    session_ttl_minutes: int = 120
    per_dim: int = 10
    rate_limit_per_hour: int = 20

    # 开发期跨域；生产走同域反代，留空即可
    cors_origins: str = ""

    # 内容目录，默认 backend/app/data
    content_dir: Path = BASE_DIR / "data"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
