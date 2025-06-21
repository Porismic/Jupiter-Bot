
import json
import os
import logging
from database import db_manager

logger = logging.getLogger('discord_bot.migration')

async def migrate_json_to_database():
    """Migrate existing JSON data to database"""
    try:
        # Check if migration has already been done
        migration_done = await db_manager.get_config("migration_completed", False)
        if migration_done:
            logger.info("Migration already completed, skipping...")
            return
        
        logger.info("Starting data migration from JSON to database...")
        
        # Migrate member stats
        if os.path.exists("member_stats.json"):
            with open("member_stats.json", "r") as f:
                member_stats = json.load(f)
            
            for user_id, stats in member_stats.items():
                await db_manager.update_member_stats(user_id, stats)
            
            logger.info(f"Migrated {len(member_stats)} member stats")
        
        # Migrate balances
        if os.path.exists("balances.json"):
            with open("balances.json", "r") as f:
                balances = json.load(f)
            
            for user_id, balance in balances.items():
                await db_manager.update_user_balance(user_id, balance)
            
            logger.info(f"Migrated {len(balances)} user balances")
        
        # Migrate inventories
        if os.path.exists("inventories.json"):
            with open("inventories.json", "r") as f:
                inventories = json.load(f)
            
            for user_id, inventory in inventories.items():
                for item_name, quantity in inventory.items():
                    await db_manager.update_user_inventory(user_id, item_name, quantity)
            
            logger.info(f"Migrated inventories for {len(inventories)} users")
        
        # Migrate tier list
        if os.path.exists("tierlist.json"):
            with open("tierlist.json", "r") as f:
                tier_data = json.load(f)
            
            for tier, items in tier_data.items():
                for item in items:
                    await db_manager.add_tier_item(tier, item)
            
            logger.info(f"Migrated tier list with {sum(len(items) for items in tier_data.values())} items")
        
        # Migrate bot configuration
        if os.path.exists("bot_config.json"):
            with open("bot_config.json", "r") as f:
                config = json.load(f)
            
            for key, value in config.items():
                await db_manager.set_config(key, value)
            
            logger.info(f"Migrated {len(config)} configuration items")
        
        # Mark migration as completed
        await db_manager.set_config("migration_completed", True)
        await db_manager.log_action("migration_completed", None, "JSON to database migration completed")
        
        logger.info("Data migration completed successfully!")
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise

async def backup_json_files():
    """Create backup of JSON files before migration"""
    import shutil
    from datetime import datetime
    
    backup_dir = f"json_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(backup_dir, exist_ok=True)
    
    json_files = [
        "member_stats.json", "balances.json", "inventories.json",
        "tierlist.json", "bot_config.json", "shops.json",
        "auctions.json", "giveaways.json", "premium_slots.json"
    ]
    
    for file_name in json_files:
        if os.path.exists(file_name):
            shutil.copy2(file_name, backup_dir)
    
    logger.info(f"JSON files backed up to {backup_dir}")
import os
import json
import logging
from database import db_manager

logger = logging.getLogger('discord_bot.migration')

async def migrate_json_to_database():
    """Migrate JSON data to database if needed"""
    try:
        # Check if migration has already been done
        migration_status = await db_manager.get_config("migration_completed", False)
        if migration_status:
            logger.info("Migration already completed, skipping")
            return
        
        logger.info("Starting JSON to database migration")
        
        # Migrate configuration
        if os.path.exists("bot_config.json"):
            with open("bot_config.json", "r") as f:
                config_data = json.load(f)
                for key, value in config_data.items():
                    await db_manager.set_config(key, value)
        
        # Migrate member stats
        if os.path.exists("member_stats.json"):
            with open("member_stats.json", "r") as f:
                stats_data = json.load(f)
                for user_id, stats in stats_data.items():
                    await db_manager.update_member_stats(user_id, stats)
        
        # Migrate balances
        if os.path.exists("balances.json"):
            with open("balances.json", "r") as f:
                balance_data = json.load(f)
                for user_id, balance in balance_data.items():
                    await db_manager.update_user_balance(user_id, balance)
        
        # Migrate inventories
        if os.path.exists("inventories.json"):
            with open("inventories.json", "r") as f:
                inventory_data = json.load(f)
                for user_id, inventory in inventory_data.items():
                    for item_name, quantity in inventory.items():
                        await db_manager.update_user_inventory(user_id, item_name, quantity)
        
        # Migrate tier list
        if os.path.exists("tierlist.json"):
            with open("tierlist.json", "r") as f:
                tier_data = json.load(f)
                for tier, items in tier_data.items():
                    for item in items:
                        await db_manager.add_tier_item(tier, item)
        
        # Mark migration as completed
        await db_manager.set_config("migration_completed", True)
        logger.info("Migration completed successfully")
        
        # Create backup of JSON files
        await backup_json_files()
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise

async def backup_json_files():
    """Create backup of JSON files before migration"""
    import shutil
    from datetime import datetime
    
    backup_dir = f"json_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(backup_dir, exist_ok=True)
    
    json_files = [
        "member_stats.json", "balances.json", "inventories.json",
        "tierlist.json", "bot_config.json", "shops.json",
        "auctions.json", "giveaways.json", "premium_slots.json"
    ]
    
    for file_name in json_files:
        if os.path.exists(file_name):
            shutil.copy2(file_name, backup_dir)
    
    logger.info(f"JSON files backed up to {backup_dir}")
    
import json
import logging
from database import db_manager

logger = logging.getLogger('discord_bot.migration')

async def migrate_json_to_database():
    """Migrate JSON data to database if needed"""
    try:
        # This is a placeholder for future migrations
        # For now, just log that migration check is complete
        logger.info("Migration check completed - no migrations needed")
        return True
    except Exception as e:
        logger.error(f"Migration error: {e}")
        return False

async def migrate_member_stats():
    """Migrate member stats from JSON to database"""
    try:
        # Load existing JSON data
        with open("member_stats.json", "r") as f:
            stats_data = json.load(f)

        # Migrate to database
        for user_id, stats in stats_data.items():
            await db_manager.update_member_stats(user_id, stats)

        logger.info(f"Migrated {len(stats_data)} member stats to database")
        return True
    except Exception as e:
        logger.error(f"Error migrating member stats: {e}")
        return False

async def migrate_user_balances():
    """Migrate user balances from JSON to database"""
    try:
        with open("balances.json", "r") as f:
            balance_data = json.load(f)

        for user_id, balance in balance_data.items():
            await db_manager.update_user_balance(user_id, balance)

        logger.info(f"Migrated {len(balance_data)} user balances to database")
        return True
    except Exception as e:
        logger.error(f"Error migrating balances: {e}")
        return False
import logging
import json
import os

logger = logging.getLogger('discord_bot.migration')

async def migrate_json_to_database():
    """Migrate JSON data to database if needed"""
    try:
        logger.info("Migration check completed - using JSON files")
        return True
    except Exception as e:
        logger.error(f"Migration error: {e}")
        return False
