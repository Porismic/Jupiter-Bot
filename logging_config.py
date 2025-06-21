
import logging
import time
import psutil
from typing import Dict, Any

class StructuredLogger:
    def __init__(self):
        self.logger = logging.getLogger('discord_bot.structured')
    
    def log_command_usage(self, command: str, user_id: int, guild_id: int):
        """Log command usage"""
        self.logger.info(f"Command used: {command} by {user_id} in {guild_id}")
    
    def log_error(self, error: str, context: str = ""):
        """Log errors with context"""
        self.logger.error(f"Error in {context}: {error}")

class PerformanceMonitor:
    def __init__(self):
        self.start_time = time.time()
        self.command_times: Dict[str, list] = {}
    
    def log_performance_metrics(self):
        """Log current performance metrics"""
        memory_usage = psutil.Process().memory_info().rss / 1024 / 1024  # MB
        cpu_usage = psutil.Process().cpu_percent()
        uptime = time.time() - self.start_time
        
        logging.info(f"Performance - Memory: {memory_usage:.2f}MB, CPU: {cpu_usage:.2f}%, Uptime: {uptime:.2f}s")

structured_logger = StructuredLogger()
performance_monitor = PerformanceMonitor()
