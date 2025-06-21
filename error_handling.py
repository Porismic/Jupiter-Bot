
import logging
import discord
from typing import Any, Optional

logger = logging.getLogger('discord_bot.error_handling')

class DatabaseError(Exception):
    """Custom exception for database errors"""
    pass

async def handle_command_errors(interaction: discord.Interaction, error: Exception):
    """Handle command errors gracefully"""
    logger.error(f"Command error in {interaction.command.name if interaction.command else 'unknown'}: {error}")
    
    if not interaction.response.is_done():
        await interaction.response.send_message("An error occurred while processing your command.", ephemeral=True)
    else:
        await interaction.followup.send("An error occurred while processing your command.", ephemeral=True)

async def handle_errors(error: Exception, context: str = ""):
    """Generic error handler"""
    logger.error(f"Error in {context}: {error}")

async def safe_respond(interaction: discord.Interaction, content: str = None, embed: discord.Embed = None, ephemeral: bool = False):
    """Safely respond to an interaction"""
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
        else:
            await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
    except Exception as e:
        logger.error(f"Failed to respond to interaction: {e}")
