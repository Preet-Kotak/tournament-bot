import bot.db.connection as connection
import logging

log = logging.getLogger(__name__)

async def setup_schema():
    """Create all necessary tables if they do not exist."""
    if not connection.pool:
        log.error("Cannot setup schema: database pool is not initialized.")
        return

    queries = [
        """
        CREATE TABLE IF NOT EXISTS teams (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            logo_url TEXT,
            is_approved BOOLEAN DEFAULT FALSE,
            team_role_id BIGINT,
            channel_id BIGINT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS team_members (
            id SERIAL PRIMARY KEY,
            team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL,
            role TEXT CHECK (role IN ('leader', 'sudo', 'member'))
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS matches (
            id SERIAL PRIMARY KEY,
            team1_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
            team2_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
            channel_id BIGINT,
            status TEXT CHECK (status IN ('scheduled', 'active', 'completed')) DEFAULT 'scheduled',
            scheduled_time TIMESTAMP,
            embed_message_id BIGINT,
            match_number INTEGER DEFAULT 1
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS district_scores (
            id SERIAL PRIMARY KEY,
            match_id INTEGER REFERENCES matches(id) ON DELETE CASCADE,
            team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
            district INTEGER CHECK (district BETWEEN 0 AND 8),
            current_stars INTEGER DEFAULT 0,
            current_percent INTEGER DEFAULT 0,
            attack1_done BOOLEAN DEFAULT FALSE,
            attack2_done BOOLEAN DEFAULT FALSE,
            is_overridden BOOLEAN DEFAULT FALSE,
            override_stars INTEGER,
            override_percent INTEGER,
            UNIQUE(match_id, team_id, district)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS attacks (
            id SERIAL PRIMARY KEY,
            match_id INTEGER REFERENCES matches(id) ON DELETE CASCADE,
            team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
            district INTEGER CHECK (district BETWEEN 0 AND 8),
            attack_num INTEGER CHECK (attack_num IN (1, 2)),
            attacker_id BIGINT NOT NULL,
            stars_before INTEGER,
            percent_before INTEGER,
            stars_after INTEGER,
            percent_after INTEGER,
            timestamp TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS bases (
            id SERIAL PRIMARY KEY,
            team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
            match_id INTEGER REFERENCES matches(id) ON DELETE CASCADE,
            district INTEGER CHECK (district BETWEEN 0 AND 8),
            link TEXT NOT NULL,
            screenshot_url TEXT NOT NULL,
            submitted_by BIGINT NOT NULL,
            UNIQUE(team_id, match_id, district)
        );
        """
    ]

    async with connection.pool.acquire() as conn:
        for q in queries:
            try:
                await conn.execute(q)
            except Exception as e:
                log.error(f"Error executing schema query: {e}")
                
    log.info("Database schema setup complete.")
