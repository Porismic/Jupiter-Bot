
import discord
from typing import Optional

class InputValidator:
    """Utility class for input validation"""
    
    @staticmethod
    def validate_user_id(user_id_str: str) -> Optional[int]:
        """Validate and convert user ID string to int"""
        try:
            user_id = int(user_id_str)
            if user_id > 0:
                return user_id
        except ValueError:
            pass
        return None
    
    @staticmethod
    def validate_amount(amount_str: str, min_val: int = 1, max_val: int = None) -> Optional[int]:
        """Validate amount input"""
        try:
            amount = int(amount_str)
            if amount >= min_val and (max_val is None or amount <= max_val):
                return amount
        except ValueError:
            pass
        return None

def validate_guild_member(guild: discord.Guild, user_id: int) -> Optional[discord.Member]:
    """Validate that a user is a member of the guild"""
    return guild.get_member(user_id)

def validate_guild_channel(guild: discord.Guild, channel_id: int) -> Optional[discord.TextChannel]:
    """Validate that a channel exists in the guild"""
    channel = guild.get_channel(channel_id)
    if isinstance(channel, discord.TextChannel):
        return channel
    return None

def validate_guild_role(guild: discord.Guild, role_id: int) -> Optional[discord.Role]:
    """Validate that a role exists in the guild"""
    return guild.get_role(role_id)
import discord
from typing import Optional, Union

class InputValidator:
    @staticmethod
    def validate_user_id(user_id: str) -> bool:
        """Validate Discord user ID format"""
        try:
            int(user_id)
            return len(user_id) >= 17 and len(user_id) <= 19
        except ValueError:
            return False
    
    @staticmethod
    def validate_channel_id(channel_id: str) -> bool:
        """Validate Discord channel ID format"""
        try:
            int(channel_id)
            return len(channel_id) >= 17 and len(channel_id) <= 19
        except ValueError:
            return False

def validate_guild_member(guild: discord.Guild, user_id: int) -> Optional[discord.Member]:
    """Validate and return guild member"""
    return guild.get_member(user_id)

def validate_guild_channel(guild: discord.Guild, channel_id: int) -> Optional[discord.abc.GuildChannel]:
    """Validate and return guild channel"""
    return guild.get_channel(channel_id)

def validate_guild_role(guild: discord.Guild, role_id: int) -> Optional[discord.Role]:
    """Validate and return guild role"""
    return guild.get_role(role_id)
