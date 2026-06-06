import asyncpg
import logging
from bot.config import DATABASE_URL

log = logging.getLogger(__name__)
pool = None

async def init_db():
    global pool
    if not DATABASE_URL:
        log.error("DATABASE_URL is not set in environment variables.")
        return
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, statement_cache_size=0)
        log.info("Successfully connected to PostgreSQL (Supabase).")
    except Exception as e:
        log.error(f"Failed to connect to database: {e}")

async def close_db():
    global pool
    if pool:
        await pool.close()
        log.info("Database connection closed.")
