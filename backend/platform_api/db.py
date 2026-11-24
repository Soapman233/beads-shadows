import os
from functools import lru_cache

from fastapi import Depends, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def enabled() -> bool:
    return bool(os.environ.get("BEAD_DATABASE_URL", "").strip())


def database_url():
    value = os.environ.get("BEAD_DATABASE_URL", "").strip()
    if not value:
        raise ValueError("BEAD_DATABASE_URL is required for multi-user mode")
    try:
        url = make_url(value)
    except Exception:
        raise ValueError("BEAD_DATABASE_URL must be a valid MySQL URL") from None
    if url.drivername != "mysql+pymysql" or not url.database:
        raise ValueError("BEAD_DATABASE_URL must specify mysql+pymysql and a database")
    return url.update_query_dict({"charset": "utf8mb4"})


@lru_cache(maxsize=1)
def session_factory():
    engine = create_engine(
        database_url(),
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=5,
        max_overflow=5,
        pool_timeout=10,
        connect_args={"connect_timeout": 5},
        hide_parameters=True,
    )
    return sessionmaker(engine, expire_on_commit=False)


def optional_db():
    if not enabled():
        yield None
        return
    try:
        factory = session_factory()
    except ValueError:
        raise HTTPException(503, "MySQL 配置无效，请检查启动配置") from None
    with factory() as database:
        try:
            yield database
        except OperationalError:
            raise HTTPException(503, "MySQL 暂不可用，请检查数据库状态") from None


def get_db(database=Depends(optional_db)):
    if database is None:
        raise HTTPException(503, "当前服务未配置 MySQL")
    return database
