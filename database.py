
import sqlite3
import json
import logging
import asyncio
from typing import Dict, List, Any, Optional
import aiosqlite
from contextlib import asynccontextmanager

logger = logging.getLogger('discord_bot.database')

class DatabaseManager:
    def __init__(self, db_path: str = "bot_database.db"):
        self.db_path = db_path
        self.connection_pool = {}
        
    async def initialize(self):
        """Initialize database with all required tables"""
        async with aiosqlite.connect(self.db_path) as db:
            await self._create_tables(db)
            await db.commit()
            logger.info("Database initialized successfully")
    
    async def _create_tables(self, db):
        """Create all necessary tables"""
        tables = [
            # Configuration table
            """CREATE TABLE IF NOT EXISTS bot_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            
            # Member statistics
            """CREATE TABLE IF NOT EXISTS member_stats (
                user_id TEXT PRIMARY KEY,
                xp INTEGER DEFAULT 0,
                daily_messages INTEGER DEFAULT 0,
                weekly_messages INTEGER DEFAULT 0,
                monthly_messages INTEGER DEFAULT 0,
                all_time_messages INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            
            # User balances
            """CREATE TABLE IF NOT EXISTS user_balances (
                user_id TEXT PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            
            # User inventories
            """CREATE TABLE IF NOT EXISTS user_inventories (
                user_id TEXT NOT NULL,
                item_name TEXT NOT NULL,
                quantity INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, item_name),
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            
            # Tier list data
            """CREATE TABLE IF NOT EXISTS tier_list (
                tier TEXT NOT NULL,
                item_name TEXT NOT NULL,
                PRIMARY KEY (tier, item_name),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            
            # Shops
            """CREATE TABLE IF NOT EXISTS shops (
                shop_name TEXT NOT NULL,
                item_name TEXT NOT NULL,
                price INTEGER NOT NULL,
                description TEXT,
                created_by INTEGER,
                PRIMARY KEY (shop_name, item_name),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            
            # Auctions
            """CREATE TABLE IF NOT EXISTS auctions (
                auction_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                seller_id TEXT NOT NULL,
                starting_bid INTEGER NOT NULL,
                current_bid INTEGER,
                thread_id TEXT,
                status TEXT DEFAULT 'active',
                is_premium BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                end_time TIMESTAMP
            )""",
            
            # Giveaways
            """CREATE TABLE IF NOT EXISTS giveaways (
                giveaway_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                prizes TEXT NOT NULL,
                host_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                message_id TEXT,
                winners_count INTEGER DEFAULT 1,
                status TEXT DEFAULT 'active',
                end_time TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            
            # Giveaway participants
            """CREATE TABLE IF NOT EXISTS giveaway_participants (
                giveaway_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                entries INTEGER DEFAULT 1,
                PRIMARY KEY (giveaway_id, user_id),
                FOREIGN KEY (giveaway_id) REFERENCES giveaways(giveaway_id)
            )""",
            
            # Premium slots
            """CREATE TABLE IF NOT EXISTS premium_slots (
                user_id TEXT PRIMARY KEY,
                total_slots INTEGER DEFAULT 0,
                used_slots INTEGER DEFAULT 0,
                manual_slots INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            
            # Member warnings
            """CREATE TABLE IF NOT EXISTS member_warnings (
                warning_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                staff_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            
            # User profiles
            """CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                preset_name TEXT,
                profile_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            
            # Reaction roles
            """CREATE TABLE IF NOT EXISTS reaction_roles (
                message_id TEXT NOT NULL,
                emoji TEXT NOT NULL,
                role_id TEXT NOT NULL,
                PRIMARY KEY (message_id, emoji)
            )""",
            
            # Server settings
            """CREATE TABLE IF NOT EXISTS server_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            
            # Logging for audit trail
            """CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                user_id TEXT,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        ]
        
        for table_sql in tables:
            await db.execute(table_sql)
    
    @asynccontextmanager
    async def get_connection(self):
        """Get database connection with proper error handling"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                yield db
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            raise
    
    # Member Stats Operations
    async def get_member_stats(self, user_id: str) -> Dict[str, Any]:
        """Get member statistics"""
        try:
            async with self.get_connection() as db:
                async with db.execute(
                    "SELECT * FROM member_stats WHERE user_id = ?", (user_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return dict(row)
                    else:
                        # Create default stats
                        await self.update_member_stats(user_id, {})
                        return {
                            "user_id": user_id,
                            "xp": 0,
                            "daily_messages": 0,
                            "weekly_messages": 0,
                            "monthly_messages": 0,
                            "all_time_messages": 0
                        }
        except Exception as e:
            logger.error(f"Error getting member stats for {user_id}: {e}")
            raise
    
    async def update_member_stats(self, user_id: str, stats: Dict[str, Any]):
        """Update member statistics"""
        try:
            async with self.get_connection() as db:
                await db.execute("""
                    INSERT OR REPLACE INTO member_stats 
                    (user_id, xp, daily_messages, weekly_messages, monthly_messages, all_time_messages)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    stats.get("xp", 0),
                    stats.get("daily_messages", 0),
                    stats.get("weekly_messages", 0),
                    stats.get("monthly_messages", 0),
                    stats.get("all_time_messages", 0)
                ))
                await db.commit()
        except Exception as e:
            logger.error(f"Error updating member stats for {user_id}: {e}")
            raise
    
    # Balance Operations
    async def get_user_balance(self, user_id: str) -> int:
        """Get user balance"""
        try:
            async with self.get_connection() as db:
                async with db.execute(
                    "SELECT balance FROM user_balances WHERE user_id = ?", (user_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    return row["balance"] if row else 0
        except Exception as e:
            logger.error(f"Error getting balance for {user_id}: {e}")
            return 0
    
    async def update_user_balance(self, user_id: str, balance: int):
        """Update user balance"""
        try:
            async with self.get_connection() as db:
                await db.execute("""
                    INSERT OR REPLACE INTO user_balances (user_id, balance)
                    VALUES (?, ?)
                """, (user_id, balance))
                await db.commit()
        except Exception as e:
            logger.error(f"Error updating balance for {user_id}: {e}")
            raise
    
    # Inventory Operations
    async def get_user_inventory(self, user_id: str) -> Dict[str, int]:
        """Get user inventory"""
        try:
            async with self.get_connection() as db:
                async with db.execute(
                    "SELECT item_name, quantity FROM user_inventories WHERE user_id = ?", (user_id,)
                ) as cursor:
                    rows = await cursor.fetchall()
                    return {row["item_name"]: row["quantity"] for row in rows}
        except Exception as e:
            logger.error(f"Error getting inventory for {user_id}: {e}")
            return {}
    
    async def update_user_inventory(self, user_id: str, item_name: str, quantity: int):
        """Update user inventory item"""
        try:
            async with self.get_connection() as db:
                if quantity <= 0:
                    await db.execute(
                        "DELETE FROM user_inventories WHERE user_id = ? AND item_name = ?",
                        (user_id, item_name)
                    )
                else:
                    await db.execute("""
                        INSERT OR REPLACE INTO user_inventories (user_id, item_name, quantity)
                        VALUES (?, ?, ?)
                    """, (user_id, item_name, quantity))
                await db.commit()
        except Exception as e:
            logger.error(f"Error updating inventory for {user_id}: {e}")
            raise
    
    # Tier List Operations
    async def get_tier_data(self) -> Dict[str, List[str]]:
        """Get tier list data"""
        try:
            async with self.get_connection() as db:
                async with db.execute("SELECT tier, item_name FROM tier_list") as cursor:
                    rows = await cursor.fetchall()
                    tier_data = {}
                    for row in rows:
                        tier = row["tier"]
                        if tier not in tier_data:
                            tier_data[tier] = []
                        tier_data[tier].append(row["item_name"])
                    return tier_data
        except Exception as e:
            logger.error(f"Error getting tier data: {e}")
            return {}
    
    async def add_tier_item(self, tier: str, item_name: str):
        """Add item to tier"""
        try:
            async with self.get_connection() as db:
                await db.execute(
                    "INSERT OR IGNORE INTO tier_list (tier, item_name) VALUES (?, ?)",
                    (tier, item_name)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Error adding tier item: {e}")
            raise
    
    async def remove_tier_item(self, tier: str, item_name: str):
        """Remove item from tier"""
        try:
            async with self.get_connection() as db:
                await db.execute(
                    "DELETE FROM tier_list WHERE tier = ? AND item_name = ?",
                    (tier, item_name)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Error removing tier item: {e}")
            raise
    
    # Configuration Operations
    async def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        try:
            async with self.get_connection() as db:
                async with db.execute(
                    "SELECT value FROM bot_config WHERE key = ?", (key,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return json.loads(row["value"])
                    return default
        except Exception as e:
            logger.error(f"Error getting config {key}: {e}")
            return default
    
    async def set_config(self, key: str, value: Any):
        """Set configuration value"""
        try:
            async with self.get_connection() as db:
                await db.execute("""
                    INSERT OR REPLACE INTO bot_config (key, value)
                    VALUES (?, ?)
                """, (key, json.dumps(value)))
                await db.commit()
        except Exception as e:
            logger.error(f"Error setting config {key}: {e}")
            raise
    
    # Audit logging
    async def log_action(self, action: str, user_id: str = None, details: str = None):
        """Log an action for audit trail"""
        try:
            async with self.get_connection() as db:
                await db.execute("""
                    INSERT INTO audit_log (action, user_id, details)
                    VALUES (?, ?, ?)
                """, (action, user_id, details))
                await db.commit()
        except Exception as e:
            logger.error(f"Error logging action: {e}")

# Global database instance
db_manager = DatabaseManager()
import aiosqlite
import logging
import json
from typing import Dict, Any, Optional

logger = logging.getLogger('discord_bot.database')

class DatabaseManager:
    def __init__(self, db_path: str = "bot_database.db"):
        self.db_path = db_path
        self.connection = None
    
    async def initialize(self):
        """Initialize database connection and create tables"""
        try:
            self.connection = await aiosqlite.connect(self.db_path)
            await self._create_tables()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    async def _create_tables(self):
        """Create necessary database tables"""
        tables = [
            """CREATE TABLE IF NOT EXISTS user_stats (
                user_id TEXT PRIMARY KEY,
                xp INTEGER DEFAULT 0,
                daily_messages INTEGER DEFAULT 0,
                weekly_messages INTEGER DEFAULT 0,
                monthly_messages INTEGER DEFAULT 0,
                all_time_messages INTEGER DEFAULT 0,
                last_xp_time INTEGER DEFAULT 0
            )""",
            """CREATE TABLE IF NOT EXISTS user_balances (
                user_id TEXT PRIMARY KEY,
                balance INTEGER DEFAULT 0
            )""",
            """CREATE TABLE IF NOT EXISTS user_inventories (
                user_id TEXT PRIMARY KEY,
                items TEXT DEFAULT '{}'
            )"""
        ]
        
        for table_sql in tables:
            await self.connection.execute(table_sql)
        await self.connection.commit()
    
    async def close(self):
        """Close database connection"""
        if self.connection:
            await self.connection.close()

# Global database manager instance
db_manager = DatabaseManager()
