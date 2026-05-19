import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from app.config import settings
import logging

logger = logging.getLogger(__name__)

# NullPool: never reuse connections across requests — avoids PgBouncer
# "duplicate prepared statement" errors entirely.
engine = create_async_engine(
    settings.postgres_url,
    echo=False,  # set True if you want SQL logs
    poolclass=NullPool,
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db_session():
    async with AsyncSessionLocal() as session:
        yield session

async def init_db():
    """
    Uses raw asyncpg with statement_cache_size=0 for ALL startup work.
    This completely bypasses SQLAlchemy's prepared-statement machinery,
    which is incompatible with Supabase's PgBouncer in transaction mode.
    """
    dsn = settings.postgres_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id BIGINT PRIMARY KEY,
                username    VARCHAR,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id   SERIAL PRIMARY KEY,
                name VARCHAR(50) UNIQUE NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT REFERENCES users(telegram_id),
                category_id INTEGER REFERENCES categories(id),
                item        TEXT NOT NULL,
                amount      NUMERIC(12,2) NOT NULL,
                currency    VARCHAR(10) DEFAULT 'EGP',
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        for cat in ["Food","Transport","Utilities","Entertainment",
                    "Electronics","Health","Education","Shopping","Housing","Other"]:
            await conn.execute(
                "INSERT INTO categories (name) VALUES ($1) ON CONFLICT (name) DO NOTHING", cat
            )
        logger.info("Database initialized and categories seeded.")
    finally:
        await conn.close()
