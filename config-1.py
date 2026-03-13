from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    SMSBOWER_API_KEY: str = ""
    SMSBOWER_BASE_URL: str = "https://smsbower.page/stubs/handler_api.php"
    ADMIN_MASTER_KEY: str = "change_me"
    DATABASE_URL: str = "sqlite+aiosqlite:///./reseller.db"
    COMMISSION_RATE: float = 0.10
    RATE_LIMIT_PER_MINUTE: int = 60
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
