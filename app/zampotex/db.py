from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from zampotex.config import DATA_DIR, get_settings
from zampotex.models import Base

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("База ещё не инициализирована")
    return _session_factory


async def init_db() -> None:
    global _engine, _session_factory
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    url = get_settings().database_url
    connect_args = {"timeout": 30} if url.startswith("sqlite") else {}
    _engine = create_async_engine(url, connect_args=connect_args)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as connection:
        if url.startswith("sqlite"):
            await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(Base.metadata.create_all)
