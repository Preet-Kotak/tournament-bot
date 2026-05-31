import discord
from datetime import datetime

def success_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=discord.Color.green())
    embed.set_footer(text="AI-3 tournament")
    return embed

def error_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=discord.Color.red())
    embed.set_footer(text="AI-3 tournament")
    return embed

def admin_log_embed(title: str, description: str, color: discord.Color = discord.Color.blue()) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.utcnow())
    embed.set_footer(text="AI-3 tournament")
    return embed
