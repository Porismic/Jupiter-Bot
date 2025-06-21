
import asyncio
import time
from typing import Dict, Callable
import discord

class RateLimiter:
    def __init__(self):
        self.user_cooldowns: Dict[int, float] = {}
        self.command_cooldowns: Dict[str, Dict[int, float]] = {}
    
    def is_on_cooldown(self, user_id: int, command: str, cooldown: int) -> bool:
        """Check if user is on cooldown for a command"""
        current_time = time.time()
        
        if command not in self.command_cooldowns:
            self.command_cooldowns[command] = {}
        
        if user_id in self.command_cooldowns[command]:
            time_passed = current_time - self.command_cooldowns[command][user_id]
            if time_passed < cooldown:
                return True
        
        self.command_cooldowns[command][user_id] = current_time
        return False

rate_limiter = RateLimiter()

def rate_limit_command(cooldown: int = 5):
    """Decorator for rate limiting commands"""
    def decorator(func: Callable):
        async def wrapper(interaction: discord.Interaction, *args, **kwargs):
            if rate_limiter.is_on_cooldown(interaction.user.id, func.__name__, cooldown):
                await interaction.response.send_message(f"Command on cooldown. Try again in a few seconds.", ephemeral=True)
                return
            return await func(interaction, *args, **kwargs)
        return wrapper
    return decorator

async def safe_api_call(coro, max_retries: int = 3):
    """Safely make API calls with retry logic"""
    for attempt in range(max_retries):
        try:
            return await coro
        except discord.HTTPException as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)
    return None
