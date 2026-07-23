import asyncpg
import ssl
import logging
from bot.config import DATABASE_URL

log = logging.getLogger(__name__)
pool = None

async def init_db():
    global pool
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set in environment variables.")
    try:
        log.info(f"Attempting to connect to database...")
        # Supabase requires SSL, create SSL context
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        pool = await asyncpg.create_pool(
            DATABASE_URL, 
            statement_cache_size=0, 
            min_size=1, 
            max_size=10,
            ssl=ssl_context
        )
        log.info("Successfully connected to PostgreSQL (Supabase).")
    except Exception as e:
        log.error(f"Failed to connect to database: {e}")
        raise RuntimeError(f"Database connection failed: {e}") from e

async def close_db():
    global pool
    if pool:
        await pool.close()
        log.info("Database connection closed.")
