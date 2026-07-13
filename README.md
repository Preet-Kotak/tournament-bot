# 🏆 Clash of Clans Clan Capital Tournament Bot

> A Discord bot for managing Clash of Clans Clan Capital tournaments with automated team management, match scheduling, real-time attack tracking, and comprehensive statistics.

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Discord.py](https://img.shields.io/badge/discord.py-2.3+-blue.svg)](https://github.com/Rapptz/discord.py)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-336791.svg)](https://www.postgresql.org/)

## 📋 Table of Contents
- [Overview](#overview)
- [Key Features](#key-features)
- [Technical Stack](#technical-stack)
- [Command Overview](#command-overview)
- [Installation](#installation)
- [Project Highlights](#project-highlights)

---

## 🎯 Overview

A Discord bot built for managing competitive Clash of Clans Clan Capital tournaments. Automates team registration, match scheduling, district-based attack tracking, and provides real-time statistics for tournament organizers and participants.

**Game Mode:** Clash of Clans Clan Capital (9 districts per match)  
**Tournament Type:** Multi-round tournament with qualifier and elimination stages

---

## ✨ Key Features

### 🎮 **Team Management**
- Self-service team registration with validation (3-5 members)
- Role-based permissions (Leader, Co-Leader, Member)
- One-click admin approval with automatic private channel creation
- Team logo upload and announcement system
- Member timezone tracking for match scheduling

### ⚔️ **Match Management**
- Automated match channel creation with team-specific permissions
- Match scheduling with timezone visualization
- Real-time district-by-district score tracking (9 districts)
- Auto-updating scoreboards in dedicated channels
- Match result image generation with team logos

### 📊 **Statistics & Analytics**
- Per-district team and player rankings
- Individual player attack logs with stars/percentage tracking
- Team performance reports with 3-star/1-star counts
- Tournament-wide aggregate statistics
- Paginated leaderboards with custom UI

### 🗺️ **Base Submission System**
- Automatic district detection from Clash of Clans base links
- Screenshot storage with permanent URLs
- Submission progress tracking per match
- Automated reminders for missing bases
- Admin tools for base review and sharing

### 🎯 **Attack Tracking**
- Dual-attack logging per district with before/after states
- Input validation and attack progression checks
- Live scoreboard updates after each attack
- Attacker assignment and edit capabilities
- Admin override system for special cases

### 🏅 **Qualifier Round**
- Multi-district scoring (6 qualifier districts)
- Bulk score submission via modals
- Overall and per-district leaderboards
- Team profiles with roster and qualifier scores

### 🛡️ **Security Features**
- Honeypot channels for automatic scam bot detection
- Permission-based command access control
- Comprehensive admin action logging
- Input validation and SQL injection prevention

---

## 🛠️ Technical Stack

### **Core Technologies**
- **Python 3.10+** with asyncio for asynchronous operations
- **discord.py 2.3+** for Discord API integration with slash commands
- **PostgreSQL** for relational database with ACID compliance
- **asyncpg** for high-performance async database connections
- **Pillow (PIL)** for dynamic image generation

### **Architecture**
```
bot/
├── cogs/              # Modular command groups (8 cogs)
│   ├── teams.py      # Team management
│   ├── matches.py    # Match lifecycle
│   ├── attacks.py    # Attack logging
│   ├── bases.py      # Base submissions
│   ├── stats.py      # Statistics engine
│   └── ...
├── db/               # Database layer
│   ├── connection.py # Connection pooling
│   └── models.py     # Schema definitions
└── utils/            # Reusable utilities
    ├── checks.py     # Permission decorators
    ├── embeds.py     # Embed templates
    └── ...
```

### **Database Schema**
9 tables with relational design:
- `teams`, `team_members` - Team data and rosters
- `matches`, `district_scores`, `attacks` - Match tracking
- `bases` - Base submissions per district
- `player_district_stats` - Player performance aggregation
- `qualifier_scores` - Qualifier round data
- `honeypot_channels` - Security system

### **Key Design Patterns**
- **Cog Architecture** - Modular command organization
- **Decorator Pattern** - Permission checks
- **State Machine** - Match lifecycle (pending → scheduled → active → completed)
- **Connection Pooling** - Database optimization

---

## 📖 Command Overview

**36 Slash Commands** organized into 8 categories:

### **Team Management** (12 commands)
`/create-team`, `/approve-team`, `/announce-team`, `/add-logo`, `/edit-team`, `/delete-team`, `/set-coleader`, `/set-player-timezone`, `/teams-list`, `/team-info`, and more

### **Match Management** (7 commands)
`/set-match`, `/schedule-match`, `/start-match`, `/end-match`, `/delete-match`, `/matches`, `/match-timezones`

### **Base Submissions** (5 commands)
`/submit-base`, `/view-bases`, `/send-bases`, `/base-status`, `/remind-bases`

### **Attack Logging** (3 commands)
`/log-attack`, `/edit-attack`, `/edit-attacker`

### **Statistics** (9 commands)
`/district-stat-team`, `/district-stat-player`, `/tournament-stat`, `/player-stat-log`, `/player-stat`, `/team-stat-log`, `/team-stat`, `/match-stat`, `/relative-lb-player`

### **Qualifier** (4 commands)
`/qualifier-submit`, `/qualifier-lb`, `/qualifier-team-info`, `/qualifier-district-lb`

### **Moderation** (2 commands)
`/create-anti-bot-channel`, `/help`

All commands feature:
- Smart autocomplete for teams, matches, and districts
- Role-based access control
- Input validation
- Rich embed responses

---

## 🚀 Installation

### **Requirements**
- Python 3.10+
- PostgreSQL database
- Discord Bot Token

### **Setup**
```bash
# Install dependencies
pip install -r requirements.txt

# Configure .env file
DISCORD_TOKEN=your_token
DATABASE_URL=postgresql://user:pass@host/db
ADMIN_IDS=your_admin_ids
GUILD_ID=your_guild_id
# ... (channel and role IDs)

# Run bot
python bot/main.py
```

Database tables are created automatically on first run.

---

## 🎯 Project Highlights

### **Technical Features**
- **5,000+ lines** of Python code with modular cog architecture
- **9-table PostgreSQL schema** with full relational integrity
- **36 slash commands** with role-based access control
- **Async architecture** using asyncio/asyncpg for concurrent operations
- **Real-time scoreboard updates** via event-driven design
- **Dynamic image generation** with PIL for match result cards
- **Smart autocomplete** for teams, matches, and districts
- **Comprehensive statistics engine** with multi-table JOINs and aggregations

### **Core Capabilities**
✅ Automated team registration and approval workflows  
✅ Real-time match tracking across 9 Clan Capital districts  
✅ Base submission system with district detection  
✅ Attack logging with validation and live updates  
✅ Advanced statistics and leaderboards  
✅ Dynamic PNG generation for match results  
✅ Permission-based command access  
✅ Honeypot system for automated bot detection
