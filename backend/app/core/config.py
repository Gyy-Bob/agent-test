from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"

    # 数据库
    database_url: str = "sqlite:///./data/app.db"

    # 存储
    storage_backend: str = "local"
    max_upload_mb: int = 50

    # 服务
    host: str = "0.0.0.0"
    port: int = 8000

    @property
    def uploads_dir(self) -> Path:
        d = BASE_DIR / "data" / "uploads"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def outputs_dir(self) -> Path:
        d = BASE_DIR / "data" / "outputs"
        d.mkdir(parents=True, exist_ok=True)
        return d


settings = Settings()
