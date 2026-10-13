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

    # PartsAPI: отдельный key на метод (имя метода как в URL, см. docs/partsapi-setup.md)
    partsapi_key_vindecode: str = ""
    partsapi_key_vindecodeoe: str = ""
    partsapi_key_getsearchtree: str = ""
    partsapi_key_getarticles: str = ""
    partsapi_key_getarticle: str = ""
    partsapi_key_getarticlecrosses: str = ""
    partsapi_key_toparts: str = ""
    partsapi_key_tooils: str = ""

    @property
    def partsapi_keys(self) -> dict[str, str]:
        pairs = {
            "VINdecode": self.partsapi_key_vindecode.strip(),
            "VINdecodeOE": self.partsapi_key_vindecodeoe.strip(),
            "getSearchTree": self.partsapi_key_getsearchtree.strip(),
            "getArticles": self.partsapi_key_getarticles.strip(),
            "getArticle": self.partsapi_key_getarticle.strip(),
            "getArticleCrosses": self.partsapi_key_getarticlecrosses.strip(),
            "toParts": self.partsapi_key_toparts.strip(),
            "toOils": self.partsapi_key_tooils.strip(),
        }
        return {name: key for name, key in pairs.items() if key}

    @property
    def admins(self) -> frozenset[int]:
        return frozenset(int(part.strip()) for part in self.admin_ids.split(",") if part.strip())


def get_settings() -> Settings:
    return Settings()


def is_admin(telegram_id: int, settings: Settings | None = None) -> bool:
    current = settings or get_settings()
    return telegram_id in current.admins
