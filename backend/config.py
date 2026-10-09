import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Ollama 服务地址（模型名在每个角色的 character.json 里指定）
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # 后端服务
    BACKEND_HOST: str = "127.0.0.1"
    BACKEND_PORT: int = 8000

    # 允许跨域的前端来源
    CORS_ORIGINS: list = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8501",  # Streamlit 默认端口
    ]

    class Config:
        env_file = ".env"


settings = Settings()
