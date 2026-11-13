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
        CREATE TABLE IF NOT EXISTS tournaments (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            initials TEXT UNIQUE NOT NULL,
            status TEXT CHECK (status IN ('setup', 'registration', 'active', 'completed')) DEFAULT 'setup',
            enabled_districts INTEGER[] DEFAULT ARRAY[0,1,2,3,4,5,6,7,8],
            has_qualifiers BOOLEAN DEFAULT TRUE,
            qualifier_districts TEXT[] DEFAULT ARRAY['Barbarian Camp', 'Wizard Valley', 'Balloon Lagoon', 'Builder''s Workshop', 'Dragon Cliffs', 'Golem Quarry'],
            participant_role_id BIGINT,
            admin_role_id BIGINT,
            team_channel_category_id BIGINT,
            created_by BIGINT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            started_at TIMESTAMP,
            ended_at TIMESTAMP,
            description TEXT,
            logo_url TEXT,
            host_accounts TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS super_admins (
            user_id BIGINT PRIMARY KEY,
            added_at TIMESTAMP DEFAULT NOW(),
            added_by BIGINT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS tournament_admins (
            id SERIAL PRIMARY KEY,
            tournament_id INTEGER REFERENCES tournaments(id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL,
            assigned_at TIMESTAMP DEFAULT NOW(),
            assigned_by BIGINT,
            UNIQUE(tournament_id, user_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS tournament_settings (
            id SERIAL PRIMARY KEY,
            tournament_id INTEGER REFERENCES tournaments(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            UNIQUE(tournament_id, key)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS teams (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            logo_url TEXT,
            is_approved BOOLEAN DEFAULT FALSE,
            team_role_id BIGINT,
            channel_id BIGINT,
            tournament_id INTEGER REFERENCES tournaments(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS team_members (
            id SERIAL PRIMARY KEY,
            team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL,
            role TEXT CHECK (role IN ('leader', 'sudo', 'member')),
            timezone_offset TEXT NOT NULL DEFAULT '+00:00'
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS matches (
            id SERIAL PRIMARY KEY,
            team1_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
            team2_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
            channel_id BIGINT,
            status TEXT CHECK (status IN ('pending', 'scheduled', 'active', 'completed')) DEFAULT 'pending',
            scheduled_time TIMESTAMP,
            embed_message_id BIGINT,
            match_number INTEGER DEFAULT 1,
            tournament_id INTEGER REFERENCES tournaments(id) ON DELETE CASCADE
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
        """,
        """
        CREATE TABLE IF NOT EXISTS player_district_stats (
            id SERIAL PRIMARY KEY,
            player_id BIGINT NOT NULL,
            match_id INTEGER REFERENCES matches(id) ON DELETE CASCADE,
            district INTEGER CHECK (district BETWEEN 0 AND 8),
            completed BOOLEAN DEFAULT FALSE,
            final_stars INTEGER DEFAULT 0,
            final_percent INTEGER DEFAULT 0,
            UNIQUE(player_id, match_id, district)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS qualifier_scores (
            id SERIAL PRIMARY KEY,
            team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
            district TEXT NOT NULL,
            stars INTEGER NOT NULL CHECK (stars BETWEEN 0 AND 3),
            percent INTEGER NOT NULL CHECK (percent BETWEEN 0 AND 100),
            submitted_by BIGINT NOT NULL,
            submitted_at TIMESTAMP DEFAULT NOW(),
            tournament_id INTEGER REFERENCES tournaments(id) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS honeypot_channels (
            channel_id BIGINT PRIMARY KEY
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    ]

    async with connection.pool.acquire() as conn:
        for q in queries:
            try:
                await conn.execute(q)
            except Exception as e:
                log.error(f"Error executing schema query: {e}")

        migrations = [
            "ALTER TABLE matches DROP CONSTRAINT IF EXISTS matches_status_check",
            "ALTER TABLE matches ADD CONSTRAINT matches_status_check CHECK (status IN ('pending', 'scheduled', 'active', 'completed'))",
            "ALTER TABLE matches ALTER COLUMN status SET DEFAULT 'pending'",
            "ALTER TABLE team_members ADD COLUMN IF NOT EXISTS timezone_offset TEXT DEFAULT '+00:00'",
            "UPDATE team_members SET timezone_offset = '+00:00' WHERE timezone_offset IS NULL",
            "ALTER TABLE team_members ALTER COLUMN timezone_offset SET DEFAULT '+00:00'",
            "ALTER TABLE team_members ALTER COLUMN timezone_offset SET NOT NULL",
            # Multi-tournament migrations
            "ALTER TABLE teams ADD COLUMN IF NOT EXISTS tournament_id INTEGER REFERENCES tournaments(id) ON DELETE CASCADE",
            "ALTER TABLE matches ADD COLUMN IF NOT EXISTS tournament_id INTEGER REFERENCES tournaments(id) ON DELETE CASCADE",
            "ALTER TABLE qualifier_scores ADD COLUMN IF NOT EXISTS tournament_id INTEGER REFERENCES tournaments(id) ON DELETE CASCADE",
            # Create indexes for performance
            "CREATE INDEX IF NOT EXISTS idx_teams_tournament ON teams(tournament_id)",
            "CREATE INDEX IF NOT EXISTS idx_matches_tournament ON matches(tournament_id)",
            "CREATE INDEX IF NOT EXISTS idx_qualifier_tournament ON qualifier_scores(tournament_id)",
            "CREATE INDEX IF NOT EXISTS idx_tournaments_status ON tournaments(status)",
            "CREATE INDEX IF NOT EXISTS idx_tournament_admins_user ON tournament_admins(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_tournament_admins_tournament ON tournament_admins(tournament_id)",
        ]
        for m in migrations:
            try:
                await conn.execute(m)
            except Exception as e:
                log.error(f"Error running migration: {e}")

        # Create views for cross-tournament statistics
        views = [
            """
            CREATE OR REPLACE VIEW player_overall_stats AS
            SELECT 
                a.attacker_id,
                COUNT(DISTINCT m.tournament_id) as tournaments_played,
                COUNT(DISTINCT m.id) as matches_played,
                COUNT(a.id) as total_attacks,
                AVG(a.stars_after) as avg_stars,
                AVG(a.percent_after) as avg_percent,
                SUM(CASE WHEN a.stars_after = 3 THEN 1 ELSE 0 END) as three_stars,
                SUM(CASE WHEN a.stars_after = 1 THEN 1 ELSE 0 END) as one_stars
            FROM attacks a
            JOIN matches m ON a.match_id = m.id
            JOIN tournaments t ON m.tournament_id = t.id
            WHERE t.status IN ('active', 'completed')
            GROUP BY a.attacker_id;
            """,
            """
            CREATE OR REPLACE VIEW team_tournament_summary AS
            SELECT 
                t.id as team_id,
                t.name as team_name,
                t.tournament_id,
                tn.name as tournament_name,
                tn.initials as tournament_initials,
                COUNT(DISTINCT m.id) as matches_played,
                SUM(CASE WHEN m.status = 'completed' THEN 1 ELSE 0 END) as matches_completed
            FROM teams t
            JOIN tournaments tn ON t.tournament_id = tn.id
            LEFT JOIN matches m ON (m.team1_id = t.id OR m.team2_id = t.id)
            GROUP BY t.id, t.name, t.tournament_id, tn.name, tn.initials;
            """
        ]
        
        for v in views:
            try:
                await conn.execute(v)
            except Exception as e:
                log.error(f"Error creating view: {e}")

    log.info("Database schema setup complete.")
