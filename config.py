import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
VERSION = "1.0.0"

class Config:
    """Конфигурация проекта VK Chrono"""
    VERSION: str = VERSION
    
    # VK настройки
    VK_TOKEN: str = os.getenv("VK_TOKEN", "")
    VK_GROUP_ID: int = int(os.getenv("VK_GROUP_ID", "0"))
    TARGET_PEER_ID: int = int(os.getenv("TARGET_PEER_ID", "0"))
    
    # Gemini настройки
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY") or None
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    SUMMARY_LANGUAGE: str = os.getenv("SUMMARY_LANGUAGE", "ru")
    
    # GitHub настройки (автоматическая синхронизация)
    GITHUB_ENABLED: bool = os.getenv("GITHUB_ENABLED", "false").lower() in ["true", "1", "yes"]
    GITHUB_TOKEN: Optional[str] = os.getenv("GITHUB_TOKEN") or None
    GITHUB_REPO: Optional[str] = os.getenv("GITHUB_REPO") or None  # например, "username/repo"
    GITHUB_BRANCH: str = os.getenv("GITHUB_BRANCH", "main")
    GITHUB_PATH_PREFIX: str = os.getenv("GITHUB_PATH_PREFIX", "reports")
    GITHUB_REPO_PRIVATE: bool = os.getenv("GITHUB_REPO_PRIVATE", "true").lower() in ["true", "1", "yes"]

    # Уведомления в чат VK
    NOTIFY_CHAT_ON_DAILY_REPORT: bool = os.getenv("NOTIFY_CHAT_ON_DAILY_REPORT", "true").lower() in ["true", "1", "yes"]
    NOTIFY_CHAT_ON_MONTHLY_REPORT: bool = os.getenv("NOTIFY_CHAT_ON_MONTHLY_REPORT", "true").lower() in ["true", "1", "yes"]

    # Сохранение медиа
    DOWNLOAD_PHOTOS: bool = os.getenv("DOWNLOAD_PHOTOS", "true").lower() in ["true", "1", "yes"]

    # Агрегация и пути
    AUTO_AGGREGATE_DAYS: int = int(os.getenv("AUTO_AGGREGATE_DAYS", "7"))
    
    DATA_DIR: Path = BASE_DIR / os.getenv("DATA_DIR", "data")
    DB_PATH: Path = DATA_DIR / "chat_logger.db"
    AVATARS_DIR: Path = DATA_DIR / "avatars"
    PHOTOS_DIR: Path = DATA_DIR / "photos"
    REPORTS_DIR: Path = DATA_DIR / "reports"
    
    DAILY_REPORTS_DIR: Path = REPORTS_DIR / "daily"
    WEEKLY_REPORTS_DIR: Path = REPORTS_DIR / "weekly"
    MONTHLY_REPORTS_DIR: Path = REPORTS_DIR / "monthly"
    
    TEMPLATES_DIR: Path = BASE_DIR / "templates"

    @classmethod
    def ensure_directories(cls):
        """Создает необходимые директории для данных, аватарок, фото и отчетов."""
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.AVATARS_DIR.mkdir(parents=True, exist_ok=True)
        cls.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
        cls.DAILY_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        cls.WEEKLY_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        cls.MONTHLY_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

config = Config()
config.ensure_directories()
