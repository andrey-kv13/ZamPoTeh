from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PHOTOS_DIR = DATA_DIR / "photos"
PDF_DIR = DATA_DIR / "pdf"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = ""
    bot_id: int = 8893240032
    admin_ids: str = "170051092,311684774,206146757,635342790"
    database_url: str = f"sqlite+aiosqlite:///{(DATA_DIR / 'zampotex.db').as_posix()}"

    @property
    def admins(self) -> frozenset[int]:
        return frozenset(int(part.strip()) for part in self.admin_ids.split(",") if part.strip())


def get_settings() -> Settings:
    return Settings()


def is_admin(telegram_id: int, settings: Settings | None = None) -> bool:
    current = settings or get_settings()
    return telegram_id in current.admins
