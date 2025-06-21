import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import math
import asyncio
import logging
import traceback
import shutil
from datetime import datetime, timezone
import io
import aiohttp
import time
import uuid
import random
import psutil
import sys

# Import custom modules
try:
    from database import db_manager
    from migration import migrate_json_to_database
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False

from utils.error_handling import handle_command_errors, handle_errors, safe_respond, DatabaseError
from utils.rate_limiting import rate_limiter, rate_limit_command, safe_api_call
from utils.logging_config import structured_logger, performance_monitor

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('discord_bot')

# --------- Config -----------
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    print("Error: DISCORD_BOT_TOKEN environment variable not set!")
    print("Please set your Discord bot token in the Secrets tab.")
    exit(1)

# Validate token format
if not TOKEN.startswith(('Bot ', 'Bearer ')) and len(TOKEN) < 50:
    print("Warning: Token format appears invalid. Make sure you're using the bot token, not client secret.")
    print("Bot tokens are typically 59+ characters long.")

GUILD_ID = 1362531923586453678  # Your guild ID here - only changeable in code

# Bot configuration that can be changed via commands
BOT_CONFIG = {
    "tier_channel_id": 1362836497060855959,
    "auction_forum_channel_id": 1362896002981433354,
    "premium_auction_forum_channel_id": 1377669568146833480,
    "bidder_role_id": 1362851306330652842,
    "buyer_role_id": 1362851277222056108,
    "staff_roles": [1362545929038594118, 1362546172429996323],
    "default_embed_color": 0x680da8,
    "tier_colors": {
        "s": 0xFFD700,
        "a": 0xC0C0C0,
        "b": 0xCD7F32,
        "c": 0x3498DB,
        "d": 0x95A5A6,
    },
    "slot_roles": {
        1334277888249303161: {"name": "2 boosts", "slots": 1},
        1334277824210800681: {"name": "3-5 boosts", "slots": 2},
        1334277764173271123: {"name": "6+ boosts", "slots": 4},
        1334276381969874995: {"name": "level30", "slots": 1},
        1344029633607372883: {"name": "level40", "slots": 2},
        1344029863845302272: {"name": "level50", "slots": 4},
    },
    "auto_slot_roles": {},  # Role ID -> slots to give automatically
    "currency_symbol": "$",
    "levelup_channel_id": None,
    "suggestions_channel_id": None,
    "reports_channel_id": None
}

# Intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# --------- Data loading & saving -----------

def load_json(file_name):
    if os.path.isfile(file_name):
        try:
            with open(file_name, "r") as f:
                data = json.load(f)
                # Return empty dict if file is empty or contains only whitespace
                return data if data else {}
        except (json.JSONDecodeError, ValueError):
            logger.warning(f"Invalid JSON in {file_name}, initializing as empty dict")
            return {}
    return {}

# Load bot configuration
bot_config = load_json("bot_config.json")
if bot_config:
    BOT_CONFIG.update(bot_config)

tier_data = load_json("tierlist.json")
member_stats = load_json("member_stats.json")
shops_data = load_json("shops.json")
user_balances = load_json("balances.json")
user_inventories = load_json("inventories.json")
reaction_roles = load_json("reaction_roles.json")
sticky_messages = load_json("sticky_messages.json")
server_settings = load_json("server_settings.json")
verification_data = load_json("verification.json")
user_profiles = load_json("user_profiles.json")
giveaways_data = load_json("giveaways.json")
auction_data = load_json("auctions.json")
premium_slots = load_json("premium_slots.json")
logging_settings = load_json("logging_settings.json")
member_warnings = load_json("member_warnings.json")
autoresponders = load_json("autoresponders.json")
profile_presets = load_json("profile_presets.json")
auction_cancellations = load_json("auction_cancellations.json")
cancellation_config = load_json("cancellation_config.json")
embed_presets = load_json("embed_presets.json")
saved_embeds = load_json("saved_embeds.json")
boost_roles = load_json("boost_roles.json")
invite_data = load_json("invite_data.json")
invite_roles = load_json("invite_roles.json")

def save_json(file_name, data):
    with open(file_name, "w") as f:
        json.dump(data, f, indent=2)

def save_all():
    save_json("bot_config.json", BOT_CONFIG)
    save_json("tierlist.json", tier_data)
    save_json("member_stats.json", member_stats)
    save_json("shops.json", shops_data)
    save_json("balances.json", user_balances)
    save_json("inventories.json", user_inventories)
    save_json("reaction_roles.json", reaction_roles)
    save_json("sticky_messages.json", sticky_messages)
    save_json("server_settings.json", server_settings)
    save_json("verification.json", verification_data)
    save_json("auctions.json", auction_data)
    save_json("user_profiles.json", user_profiles)
    save_json("giveaways.json", giveaways_data)
    save_json("premium_slots.json", premium_slots)
    save_json("logging_settings.json", logging_settings)
    save_json("member_warnings.json", member_warnings)
    save_json("autoresponders.json", autoresponders)
    save_json("profile_presets.json", profile_presets)
    save_json("auction_cancellations.json", auction_cancellations)
    save_json("cancellation_config.json", cancellation_config)
    save_json("embed_presets.json", embed_presets)
    save_json("saved_embeds.json", saved_embeds)
    save_json("auction_formats.json", auction_formats)
    save_json("boost_roles.json", boost_roles)
    save_json("invite_data.json", invite_data)
    save_json("invite_roles.json", invite_roles)

# --------- Helper Functions -----------

def has_staff_role(interaction: discord.Interaction):
    # Administrators always have staff permissions
    if interaction.user.guild_permissions.administrator or interaction.user.id == interaction.guild.owner_id:
        return True
    user_role_ids = [role.id for role in interaction.user.roles]
    return any(role_id in BOT_CONFIG["staff_roles"] for role_id in user_role_ids)

def has_admin_permissions(interaction: discord.Interaction):
    return interaction.user.guild_permissions.administrator or interaction.user.id == interaction.guild.owner_id

def get_currency_symbol():
    return BOT_CONFIG.get("currency_symbol", "$")

def get_color_for_tier(tier: str):
    return BOT_CONFIG["tier_colors"].get(tier.lower(), BOT_CONFIG["default_embed_color"])

def calculate_level(xp: int):
    return int(math.sqrt(xp / 100)) if xp >= 0 else 0

def calculate_xp_for_level(level: int):
    return level * level * 100

def calculate_user_slots(member: discord.Member):
    """Calculate total slots a user should have based on their roles"""
    total_slots = 0
    
    # Check slot roles (existing system)
    for role in member.roles:
        if role.id in BOT_CONFIG.get("slot_roles", {}):
            total_slots += BOT_CONFIG["slot_roles"][role.id]["slots"]
    
    # Check auto slot roles (new configurable system)
    for role in member.roles:
        if role.id in BOT_CONFIG.get("auto_slot_roles", {}):
            total_slots += BOT_CONFIG["auto_slot_roles"][role.id]
    
    return total_slots

def update_user_slots(member: discord.Member):
    """Update a user's slot count based on their current roles"""
    user_id = str(member.id)
    calculated_slots = calculate_user_slots(member)
    
    if user_id not in premium_slots:
        premium_slots[user_id] = {"total_slots": 0, "used_slots": 0, "manual_slots": 0}
    
    # Update total slots = calculated + manual
    manual_slots = premium_slots[user_id].get("manual_slots", 0)
    premium_slots[user_id]["total_slots"] = calculated_slots + manual_slots
    
    # Ensure used slots don't exceed total
    if premium_slots[user_id]["used_slots"] > premium_slots[user_id]["total_slots"]:
        premium_slots[user_id]["used_slots"] = premium_slots[user_id]["total_slots"]
    
    save_json("premium_slots.json", premium_slots)

def ensure_user_in_stats(user_id: str):
    if user_id not in member_stats:
        member_stats[user_id] = {
            "xp": 0,
            "daily_messages": 0,
            "weekly_messages": 0,
            "monthly_messages": 0,
            "all_time_messages": 0,
        }
    if user_id not in user_balances:
        user_balances[user_id] = 0
    if user_id not in user_inventories:
        user_inventories[user_id] = {}

# --------- Image Upload Function -----------

async def upload_image_to_thread(thread, image_source):
    """Download and upload an image to a Discord thread from URL or attachment"""
    try:
        if isinstance(image_source, str):
            # Handle URL
            async with aiohttp.ClientSession() as session:
                async with session.get(image_source) as response:
                    if response.status == 200:
                        image_data = await response.read()
                        file_extension = image_source.split('.')[-1].lower()
                        if file_extension not in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                            file_extension = 'png'

                        file = discord.File(
                            io.BytesIO(image_data),
                            filename=f"auction_image.{file_extension}"
                        )
                        await thread.send(file=file)
                        return True
        elif hasattr(image_source, 'url'):
            # Handle Discord attachment
            async with aiohttp.ClientSession() as session:
                async with session.get(image_source.url) as response:
                    if response.status == 200:
                        image_data = await response.read()
                        file_extension = image_source.filename.split('.')[-1].lower() if '.' in image_source.filename else 'png'
                        if file_extension not in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                            file_extension = 'png'

                        file = discord.File(
                            io.BytesIO(image_data),
                            filename=f"auction_{image_source.filename}"
                        )
                        await thread.send(file=file)
                        return True
    except Exception as e:
        logger.error(f"Failed to upload image {image_source}: {e}")
        return False
    return False

async def upload_file_attachment_to_thread(thread, attachment):
    """Upload a Discord attachment directly to thread"""
    try:
        file = await attachment.to_file()
        await thread.send(file=file)
        return True
    except Exception as e:
        logger.error(f"Failed to upload attachment {attachment.filename}: {e}")
        return False

# --------- Guild Restriction Check -----------

def guild_only():
    def predicate(interaction: discord.Interaction):
        return interaction.guild and interaction.guild.id == GUILD_ID
    return app_commands.check(predicate)

# --------- Enhanced Help System -----------

class HelpNavigationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.current_page = 0
        self.pages = self.create_help_pages()

    def create_help_pages(self):
        return [
            {
                "title": "🏠 Main Menu",
                "description": "Welcome to the comprehensive help system! Use the navigation buttons or select a category below to explore all available commands.",
                "fields": [
                    {"name": "🎮 Quick Start", "value": "• `/profile create` - Set up your profile\n• `/level` - Check your XP and level\n• `/balance` - View your currency\n• `/shop list` - Browse available items", "inline": False},
                    {"name": "👥 User Commands", "value": "Commands available to all members", "inline": True},
                    {"name": "⚡ Staff Commands", "value": "Commands for staff members only", "inline": True},
                    {"name": "🔧 Admin Commands", "value": "Commands for administrators", "inline": True}
                ]
            },
            {
                "title": "👥 User Commands - Social & Economy",
                "description": "Commands available to all server members",
                "fields": [
                    {"name": "💰 Economy Commands", "value": "`/balance` - Check your currency balance\n`/shop list [shop_name]` - Browse shops and items\n`/shop buy` - Purchase items\n`/inventory` - View your items\n`/gift` - Give items to others\n`/trade` - Trade items with others", "inline": False},
                    {"name": "📊 Level & Stats", "value": "`/level [user]` - View level and XP\n`/level leaderboard` - Server rankings\n`/messages` - View message statistics", "inline": False},
                    {"name": "👤 Profile System", "value": "`/profile create` - Create your profile\n`/profile view [user]` - View profiles\n`/profile edit` - Edit your profile\n`/profile list_presets` - Available presets", "inline": False}
                ]
            },
            {
                "title": "👥 User Commands - Utility & Fun",
                "description": "Additional commands for member interaction",
                "fields": [
                    {"name": "📝 Utility Commands", "value": "`/suggest` - Submit suggestions to staff\n`/report` - Report issues or users\n`/afk [reason]` - Set yourself as AFK\n`/remindme` - Set personal reminders", "inline": False},
                    {"name": "🎰 Premium Slots", "value": "`/viewslots` - Check your premium auction slots\n`/auction list` - View active auctions", "inline": False},
                    {"name": "🎉 Giveaways", "value": "`/giveaway_claim` - Mark prizes as claimed (if winner)\n`/giveaway_unclaimed` - View unclaimed prizes", "inline": False}
                ]
            },
            {
                "title": "⚡ Staff Commands - Content Management",
                "description": "Commands available to staff members only",
                "fields": [
                    {"name": "🏆 Tier List Management", "value": "`/tierlist` - Interactive tier list posting\n`/tierlist_move` - Move items between tiers", "inline": False},
                    {"name": "🛍️ Shop Management", "value": "`/shop` - Interactive shop management\n• Create, edit, and manage shops\n• Add/remove items and discounts\n• Full inventory control", "inline": False},
                    {"name": "🎭 Reaction Roles", "value": "`/reaction_role` - Set up reaction role systems\n• Role assignment on reactions\n• XP and currency rewards\n• Custom responses", "inline": False}
                ]
            },
            {
                "title": "⚡ Staff Commands - Events & Automation",
                "description": "Advanced staff management tools",
                "fields": [
                    {"name": "🎉 Giveaway System", "value": "`/giveaway` - Create interactive giveaways\n• Role restrictions and requirements\n• Extra entry systems\n• Automatic winner selection", "inline": False},
                    {"name": "🏺 Auction System", "value": "`/auction` - Create auction posts\n• Regular and premium auctions\n• Image upload support\n• Automatic thread creation", "inline": False},
                    {"name": "🤖 Automation Tools", "value": "`/autoresponder` - Set up auto-responses\n`/sticky` - Create sticky messages\n`/verification` - Set up verification systems", "inline": False}
                ]
            },
            {
                "title": "⚡ Staff Commands - Moderation",
                "description": "Tools for maintaining server order",
                "fields": [
                    {"name": "🔨 Basic Moderation", "value": "`/ban` - Ban members with logging\n`/kick` - Kick members\n`/warn` - Issue warnings\n`/quarantine` - Isolate members temporarily\n`/purge` - Mass delete messages", "inline": False},
                    {"name": "📋 Warning System", "value": "`/warnings` - View member warnings\n`/remove_warning` - Remove specific warnings\n• Full warning history tracking\n• Warning ID system", "inline": False},
                    {"name": "💰 Economy Management", "value": "`/balance_give` - Give currency to users\n`/balance_remove` - Remove currency\n`/addslots` / `/removeslots` - Manage premium slots", "inline": False}
                ]
            },
            {
                "title": "🔧 Admin Commands - Configuration",
                "description": "Commands for server administrators only",
                "fields": [
                    {"name": "⚙️ Bot Configuration", "value": "`/config` - Interactive configuration panel\n• Channel settings\n• Role management\n• Color customization\n• Currency setup", "inline": False},
                    {"name": "📊 Logging System", "value": "`/logging_setup` - Configure action logging\n`/logging_disable` - Disable specific logging\n• Moderation logs\n• Member activity\n• Message events", "inline": False},
                    {"name": "🎭 Profile Presets", "value": "`/profile create_preset` - Create new presets\n`/profile delete_preset` - Remove presets\n• Custom field creation\n• Template management", "inline": False}
                ]
            },
            {
                "title": "🔧 Admin Commands - Management",
                "description": "Advanced administrative tools",
                "fields": [
                    {"name": "🧹 Data Management", "value": "`/cleanup_data` - Remove old/invalid data\n`/export_data` - Backup data files\n• Automated cleanup systems\n• Data integrity maintenance", "inline": False},
                    {"name": "🔍 Debug Tools", "value": "`/debug_info` - Bot performance metrics\n`/debug_user` - User data inspection\n`/debug_performance` - System statistics", "inline": False},
                    {"name": "🏪 Role Menu System", "value": "`/role_menu` - Create self-role systems\n• Interactive role selection\n• Category organization\n• Automatic role management", "inline": False}
                ]
            },
            {
                "title": "📚 Command Usage Examples",
                "description": "Detailed examples of complex commands",
                "fields": [
                    {"name": "🏺 Auction Creation", "value": "Use `/auction` to open the interactive auction creator:\n1. Set item details (name, starting bid, payment methods)\n2. Add up to 5 images (URLs)\n3. Configure seller information\n4. Create the auction thread", "inline": False},
                    {"name": "🎉 Giveaway Setup", "value": "Use `/giveaway` for comprehensive giveaway creation:\n1. Set basic info (name, prizes, duration)\n2. Add requirements (roles, levels, messages)\n3. Configure extra entries and bypass roles\n4. Launch the giveaway", "inline": False},
                    {"name": "👤 Profile System", "value": "Complete profile workflow:\n1. Staff create presets with `/profile create_preset`\n2. Users create profiles with `/profile create`\n3. Edit anytime with `/profile edit`\n4. View with `/profile view`", "inline": False}
                ]
            }
        ]

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_page(interaction)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="🏠 Home", style=discord.ButtonStyle.primary)
    async def home_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        await self.update_page(interaction)

    @discord.ui.button(label="▶️ Next", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            await self.update_page(interaction)
        else:
            await interaction.response.defer()

    @discord.ui.select(
        placeholder="Jump to a specific section...",
        options=[
            discord.SelectOption(label="🏠 Main Menu", value="0", description="Overview and quick start"),
            discord.SelectOption(label="👥 User: Social & Economy", value="1", description="Profile, balance, trading"),
            discord.SelectOption(label="👥 User: Utility & Fun", value="2", description="AFK, reminders, reports"),
            discord.SelectOption(label="⚡ Staff: Content", value="3", description="Tier lists, shops, roles"),
            discord.SelectOption(label="⚡ Staff: Events", value="4", description="Giveaways, auctions, automation"),
            discord.SelectOption(label="⚡ Staff: Moderation", value="5", description="Bans, warnings, purges"),
            discord.SelectOption(label="🔧 Admin: Configuration", value="6", description="Bot setup, logging"),
            discord.SelectOption(label="🔧 Admin: Management", value="7", description="Data, debug, role menus"),
            discord.SelectOption(label="📚 Examples", value="8", description="Detailed usage examples"),
        ]
    )
    async def page_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.current_page = int(select.values[0])
        await self.update_page(interaction)

    async def update_page(self, interaction: discord.Interaction):
        page = self.pages[self.current_page]
        embed = discord.Embed(
            title=page["title"],
            description=page["description"],
            color=BOT_CONFIG["default_embed_color"]
        )

        for field in page["fields"]:
            embed.add_field(
                name=field["name"],
                value=field["value"],
                inline=field.get("inline", False)
            )

        embed.set_footer(text=f"Page {self.current_page + 1} of {len(self.pages)} • Use buttons or dropdown to navigate")
        await interaction.response.edit_message(embed=embed, view=self)

@tree.command(name="help", description="Comprehensive help system with all bot commands", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def help_command(interaction: discord.Interaction):
    view = HelpNavigationView()
    page = view.pages[0]

    embed = discord.Embed(
        title=page["title"],
        description=page["description"],
        color=BOT_CONFIG["default_embed_color"]
    )

    for field in page["fields"]:
        embed.add_field(
            name=field["name"],
            value=field["value"],
            inline=field.get("inline", False)
        )

    embed.set_footer(text=f"Page 1 of {len(view.pages)} • Use buttons or dropdown to navigate")
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@tree.command(name="test", description="Simple test command to verify bot functionality", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def test_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="✅ Bot Test Successful",
        description="The bot is working correctly!",
        color=0x00FF00
    )
    embed.add_field(name="User", value=interaction.user.mention, inline=True)
    embed.add_field(name="Channel", value=interaction.channel.mention, inline=True)
    embed.set_timestamp(datetime.now())
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --------- Enhanced Tier List System -----------

class TierListView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.current_tier = "s"

    @discord.ui.select(
        placeholder="Select tier to view/edit...",
        options=[
            discord.SelectOption(label="S Tier", value="s", emoji="🥇"),
            discord.SelectOption(label="A Tier", value="a", emoji="🥈"),
            discord.SelectOption(label="B Tier", value="b", emoji="🥉"),
            discord.SelectOption(label="C Tier", value="c", emoji="📘"),
            discord.SelectOption(label="D Tier", value="d", emoji="📗"),
        ]
    )
    async def tier_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.current_tier = select.values[0]
        await self.update_display(interaction)

    @discord.ui.button(label="Add Item", style=discord.ButtonStyle.green)
    async def add_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = TierListItemModal(self, "add")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Remove Item", style=discord.ButtonStyle.red)
    async def remove_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = TierListItemModal(self, "remove")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Post Tier List", style=discord.ButtonStyle.primary)
    async def post_tierlist(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.create_tierlist_post(interaction)

    async def update_display(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"Tier List Management - {self.current_tier.upper()} Tier",
            color=get_color_for_tier(self.current_tier)
        )

        items = tier_data.get(self.current_tier, [])
        if items:
            embed.description = "\n".join([f"• {item}" for item in items])
        else:
            embed.description = "No items in this tier"

        await interaction.response.edit_message(embed=embed, view=self)

    async def create_tierlist_post(self, interaction):
        channel = bot.get_channel(BOT_CONFIG["tier_channel_id"])
        if not channel:
            await interaction.response.send_message("Tier channel not configured!", ephemeral=True)
            return

        embed = discord.Embed(
            title="🏆 Server Tier List",
            color=BOT_CONFIG["default_embed_color"]
        )

        for tier in ["s", "a", "b", "c", "d"]:
            items = tier_data.get(tier, [])
            if items:
                embed.add_field(
                    name=f"{tier.upper()} Tier",
                    value="\n".join([f"• {item}" for item in items]),
                    inline=False
                )

        await channel.send(embed=embed)
        await interaction.response.send_message("✅ Tier list posted!", ephemeral=True)

class TierListItemModal(discord.ui.Modal):
    def __init__(self, view, action):
        super().__init__(title=f"{action.title()} Item")
        self.view = view
        self.action = action

        self.item_name = discord.ui.TextInput(
            label="Item Name",
            placeholder="Enter the item name",
            required=True,
            max_length=100
        )
        self.add_item(self.item_name)

    async def on_submit(self, interaction: discord.Interaction):
        tier = self.view.current_tier
        item = self.item_name.value.strip()

        if tier not in tier_data:
            tier_data[tier] = []

        if self.action == "add":
            if item not in tier_data[tier]:
                tier_data[tier].append(item)
                save_json("tierlist.json", tier_data)
                await interaction.response.send_message(f"✅ Added '{item}' to {tier.upper()} tier", ephemeral=True)
            else:
                await interaction.response.send_message(f"'{item}' is already in {tier.upper()} tier", ephemeral=True)
        else:  # remove
            if item in tier_data[tier]:
                tier_data[tier].remove(item)
                save_json("tierlist.json", tier_data)
                await interaction.response.send_message(f"✅ Removed '{item}' from {tier.upper()} tier", ephemeral=True)
            else:
                await interaction.response.send_message(f"'{item}' not found in {tier.upper()} tier", ephemeral=True)

@tree.command(name="tierlist", description="Interactive tier list management", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def tierlist(interaction: discord.Interaction):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to manage the tier list.", ephemeral=True)
        return

    view = TierListView()
    embed = discord.Embed(
        title="Tier List Management - S Tier",
        color=get_color_for_tier("s")
    )

    items = tier_data.get("s", [])
    if items:
        embed.description = "\n".join([f"• {item}" for item in items])
    else:
        embed.description = "No items in this tier"

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@tree.command(name="tierlist_move", description="Move an item between tiers", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(
    item="Item to move",
    from_tier="Current tier",
    to_tier="Target tier"
)
@app_commands.choices(
    from_tier=[
        app_commands.Choice(name="S", value="s"),
        app_commands.Choice(name="A", value="a"),
        app_commands.Choice(name="B", value="b"),
        app_commands.Choice(name="C", value="c"),
        app_commands.Choice(name="D", value="d"),
    ],
    to_tier=[
        app_commands.Choice(name="S", value="s"),
        app_commands.Choice(name="A", value="a"),
        app_commands.Choice(name="B", value="b"),
        app_commands.Choice(name="C", value="c"),
        app_commands.Choice(name="D", value="d"),
    ]
)
async def tierlist_move(interaction: discord.Interaction, item: str, from_tier: app_commands.Choice[str], to_tier: app_commands.Choice[str]):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to manage the tier list.", ephemeral=True)
        return

    from_t = from_tier.value
    to_t = to_tier.value

    if from_t not in tier_data:
        tier_data[from_t] = []
    if to_t not in tier_data:
        tier_data[to_t] = []

    if item in tier_data[from_t]:
        tier_data[from_t].remove(item)
        tier_data[to_t].append(item)
        save_json("tierlist.json", tier_data)
        await interaction.response.send_message(f"✅ Moved '{item}' from {from_t.upper()} to {to_t.upper()} tier")
    else:
        await interaction.response.send_message(f"'{item}' not found in {from_t.upper()} tier", ephemeral=True)

# --------- Enhanced Shop System -----------

class ShopManagementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.current_shop = None

    @discord.ui.select(placeholder="Select a shop to manage...")
    async def shop_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.current_shop = select.values[0]
        await self.update_shop_display(interaction)

    @discord.ui.button(label="Create Shop", style=discord.ButtonStyle.green)
    async def create_shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CreateShopModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Add Item", style=discord.ButtonStyle.primary)
    async def add_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.current_shop:
            await interaction.response.send_message("Please select a shop first.", ephemeral=True)
            return
        modal = ShopItemModal(self, "add")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Remove Item", style=discord.ButtonStyle.red)
    async def remove_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.current_shop:
            await interaction.response.send_message("Please select a shop first.", ephemeral=True)
            return
        modal = ShopItemModal(self, "remove")
        await interaction.response.send_modal(modal)

    async def update_shop_list(self):
        options = []
        for shop_name in shops_data.keys():
            options.append(discord.SelectOption(label=shop_name, value=shop_name))
        
        if not options:
            options.append(discord.SelectOption(label="No shops available", value="none"))
        
        self.children[0].options = options[:25]  # Discord limit

    async def update_shop_display(self, interaction):
        if self.current_shop not in shops_data:
            await interaction.response.send_message("Shop not found.", ephemeral=True)
            return

        shop = shops_data[self.current_shop]
        embed = discord.Embed(
            title=f"Managing Shop: {self.current_shop}",
            description=shop.get("description", "No description"),
            color=BOT_CONFIG["default_embed_color"]
        )

        items = shop.get("items", {})
        if items:
            item_list = []
            for item_name, item_data in items.items():
                price = item_data.get("price", 0)
                currency = get_currency_symbol()
                item_list.append(f"**{item_name}**: {currency}{price}")
            embed.add_field(name="Items", value="\n".join(item_list), inline=False)
        else:
            embed.add_field(name="Items", value="No items in this shop", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

class CreateShopModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Create New Shop")
        self.view = view

        self.name = discord.ui.TextInput(
            label="Shop Name",
            placeholder="Enter shop name",
            required=True,
            max_length=50
        )

        self.description = discord.ui.TextInput(
            label="Shop Description",
            placeholder="Enter shop description",
            required=False,
            max_length=200,
            style=discord.TextStyle.paragraph
        )

        self.add_item(self.name)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction):
        shop_name = self.name.value.strip()
        
        if shop_name in shops_data:
            await interaction.response.send_message("A shop with this name already exists.", ephemeral=True)
            return

        shops_data[shop_name] = {
            "description": self.description.value.strip(),
            "items": {},
            "created_by": interaction.user.id
        }
        save_json("shops.json", shops_data)

        await self.view.update_shop_list()
        await interaction.response.send_message(f"✅ Created shop '{shop_name}'", ephemeral=True)

class ShopItemModal(discord.ui.Modal):
    def __init__(self, view, action):
        super().__init__(title=f"{action.title()} Item")
        self.view = view
        self.action = action

        self.item_name = discord.ui.TextInput(
            label="Item Name",
            placeholder="Enter item name",
            required=True,
            max_length=50
        )

        if action == "add":
            self.price = discord.ui.TextInput(
                label="Price",
                placeholder="Enter item price",
                required=True,
                max_length=10
            )
            self.description = discord.ui.TextInput(
                label="Description",
                placeholder="Enter item description",
                required=False,
                max_length=200,
                style=discord.TextStyle.paragraph
            )
            self.add_item(self.price)
            self.add_item(self.description)

        self.add_item(self.item_name)

    async def on_submit(self, interaction: discord.Interaction):
        shop = shops_data[self.view.current_shop]
        item_name = self.item_name.value.strip()

        if self.action == "add":
            try:
                price = int(self.price.value)
                if price < 0:
                    await interaction.response.send_message("Price must be positive.", ephemeral=True)
                    return
            except ValueError:
                await interaction.response.send_message("Invalid price. Please enter a number.", ephemeral=True)
                return

            shop["items"][item_name] = {
                "price": price,
                "description": self.description.value.strip()
            }
            save_json("shops.json", shops_data)
            await interaction.response.send_message(f"✅ Added '{item_name}' to shop", ephemeral=True)

        else:  # remove
            if item_name in shop["items"]:
                del shop["items"][item_name]
                save_json("shops.json", shops_data)
                await interaction.response.send_message(f"✅ Removed '{item_name}' from shop", ephemeral=True)
            else:
                await interaction.response.send_message(f"'{item_name}' not found in shop", ephemeral=True)

@tree.command(name="shop", description="Interactive shop management", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(action="Shop action to perform")
@app_commands.choices(action=[
    app_commands.Choice(name="Manage Shops", value="manage"),
    app_commands.Choice(name="List Items", value="list"),
    app_commands.Choice(name="Buy Item", value="buy"),
])
async def shop(interaction: discord.Interaction, action: app_commands.Choice[str]):
    if action.value == "manage":
        if not has_staff_role(interaction):
            await interaction.response.send_message("You don't have permission to manage shops.", ephemeral=True)
            return

        view = ShopManagementView()
        await view.update_shop_list()
        
        embed = discord.Embed(
            title="Shop Management",
            description="Select a shop to manage or create a new one:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    elif action.value == "list":
        view = ShopListView()
        await view.update_shop_list()
        
        embed = discord.Embed(
            title="Available Shops",
            description="Select a shop to browse:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    elif action.value == "buy":
        view = ShopBuyView()
        await view.update_shop_list()
        
        embed = discord.Embed(
            title="Purchase Items",
            description="Select a shop to buy from:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class ShopListView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(placeholder="Select a shop to browse...")
    async def shop_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        shop_name = select.values[0]
        if shop_name == "none":
            return

        shop = shops_data[shop_name]
        embed = discord.Embed(
            title=f"🏪 {shop_name}",
            description=shop.get("description", "No description"),
            color=BOT_CONFIG["default_embed_color"]
        )

        items = shop.get("items", {})
        if items:
            item_list = []
            for item_name, item_data in items.items():
                price = item_data.get("price", 0)
                currency = get_currency_symbol()
                desc = item_data.get("description", "")
                item_list.append(f"**{item_name}**: {currency}{price}\n{desc}")
            embed.add_field(name="Available Items", value="\n\n".join(item_list), inline=False)
        else:
            embed.add_field(name="Items", value="No items available", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

    async def update_shop_list(self):
        options = []
        for shop_name in shops_data.keys():
            options.append(discord.SelectOption(label=shop_name, value=shop_name))
        
        if not options:
            options.append(discord.SelectOption(label="No shops available", value="none"))
        
        self.children[0].options = options[:25]

class ShopBuyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.current_shop = None

    @discord.ui.select(placeholder="Select a shop...")
    async def shop_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.current_shop = select.values[0]
        if self.current_shop == "none":
            return
        await self.update_items_display(interaction)

    @discord.ui.select(placeholder="Select an item to buy...", row=1)
    async def item_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not self.current_shop:
            await interaction.response.send_message("Please select a shop first.", ephemeral=True)
            return

        item_name = select.values[0]
        await self.buy_item(interaction, item_name)

    async def update_shop_list(self):
        options = []
        for shop_name in shops_data.keys():
            options.append(discord.SelectOption(label=shop_name, value=shop_name))
        
        if not options:
            options.append(discord.SelectOption(label="No shops available", value="none"))
        
        self.children[0].options = options[:25]

    async def update_items_display(self, interaction):
        shop = shops_data[self.current_shop]
        items = shop.get("items", {})
        
        options = []
        for item_name, item_data in items.items():
            price = item_data.get("price", 0)
            currency = get_currency_symbol()
            options.append(discord.SelectOption(
                label=item_name,
                value=item_name,
                description=f"{currency}{price}"
            ))
        
        if not options:
            options.append(discord.SelectOption(label="No items available", value="none"))
        
        self.children[1].options = options[:25]
        self.children[1].placeholder = f"Select an item from {self.current_shop}..."
        
        embed = discord.Embed(
            title=f"🛒 Shopping at {self.current_shop}",
            description="Select an item to purchase:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        await interaction.response.edit_message(embed=embed, view=self)

    async def buy_item(self, interaction, item_name):
        if item_name == "none":
            return

        user_id = str(interaction.user.id)
        ensure_user_in_stats(user_id)

        shop = shops_data[self.current_shop]
        item = shop["items"][item_name]
        price = item["price"]
        currency = get_currency_symbol()

        if user_balances.get(user_id, 0) < price:
            await interaction.response.send_message(f"You don't have enough currency! You need {currency}{price} but only have {currency}{user_balances.get(user_id, 0)}.", ephemeral=True)
            return

        # Process purchase
        user_balances[user_id] -= price
        
        if item_name not in user_inventories[user_id]:
            user_inventories[user_id][item_name] = 0
        user_inventories[user_id][item_name] += 1

        save_json("balances.json", user_balances)
        save_json("inventories.json", user_inventories)

        embed = discord.Embed(
            title="✅ Purchase Successful!",
            description=f"You bought **{item_name}** for {currency}{price}",
            color=0x00FF00
        )
        embed.add_field(name="New Balance", value=f"{currency}{user_balances[user_id]}", inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

# --------- Enhanced Reaction Role System -----------

class ReactionRoleSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.reaction_data = {
            "roles": {},
            "rewards": {},
            "message": ""
        }

    @discord.ui.button(label="Set Message", style=discord.ButtonStyle.primary)
    async def set_message(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ReactionRoleMessageModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Add Role Reaction", style=discord.ButtonStyle.green)
    async def add_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ReactionRoleAddModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Add Reward", style=discord.ButtonStyle.secondary)
    async def add_reward(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ReactionRoleRewardModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Create Reaction Role", style=discord.ButtonStyle.green)
    async def create_reaction_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.reaction_data["message"] or not self.reaction_data["roles"]:
            await interaction.response.send_message("Please set a message and add at least one role reaction.", ephemeral=True)
            return

        await self.create_reaction_message(interaction)

    async def update_display(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Reaction Role Setup",
            color=BOT_CONFIG["default_embed_color"]
        )

        if self.reaction_data["message"]:
            embed.add_field(name="Message", value=self.reaction_data["message"][:100] + "..." if len(self.reaction_data["message"]) > 100 else self.reaction_data["message"], inline=False)

        if self.reaction_data["roles"]:
            role_list = []
            for emoji, role_id in self.reaction_data["roles"].items():
                role = interaction.guild.get_role(role_id)
                role_name = role.name if role else "Unknown Role"
                role_list.append(f"{emoji} → {role_name}")
            embed.add_field(name="Role Reactions", value="\n".join(role_list), inline=False)

        if self.reaction_data["rewards"]:
            reward_list = []
            for emoji, reward in self.reaction_data["rewards"].items():
                reward_list.append(f"{emoji} → +{reward['xp']} XP, {get_currency_symbol()}{reward['currency']}")
            embed.add_field(name="Rewards", value="\n".join(reward_list), inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

    async def create_reaction_message(self, interaction):
        embed = discord.Embed(
            title="Role Selection",
            description=self.reaction_data["message"],
            color=BOT_CONFIG["default_embed_color"]
        )

        message = await interaction.channel.send(embed=embed)

        # Add reactions
        for emoji in self.reaction_data["roles"].keys():
            try:
                await message.add_reaction(emoji)
            except:
                pass

        # Save reaction role data
        message_id = str(message.id)
        reaction_roles[message_id] = {
            "channel_id": interaction.channel.id,
            "roles": self.reaction_data["roles"],
            "rewards": self.reaction_data["rewards"]
        }
        save_json("reaction_roles.json", reaction_roles)

        await interaction.response.send_message("✅ Reaction role message created!", ephemeral=True)

class ReactionRoleMessageModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Set Reaction Role Message")
        self.view = view

        self.message = discord.ui.TextInput(
            label="Message Content",
            placeholder="Enter the message for users to see",
            required=True,
            max_length=1000,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.message)

    async def on_submit(self, interaction: discord.Interaction):
        self.view.reaction_data["message"] = self.message.value
        await self.view.update_display(interaction)

class ReactionRoleAddModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Add Role Reaction")
        self.view = view

        self.emoji = discord.ui.TextInput(
            label="Emoji",
            placeholder="Enter emoji (e.g., 😀 or :custom_emoji:)",
            required=True,
            max_length=50
        )

        self.role_id = discord.ui.TextInput(
            label="Role ID",
            placeholder="Enter the role ID",
            required=True,
            max_length=20
        )

        self.add_item(self.emoji)
        self.add_item(self.role_id)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            role_id = int(self.role_id.value)
            role = interaction.guild.get_role(role_id)
            
            if not role:
                await interaction.response.send_message("Role not found.", ephemeral=True)
                return

            self.view.reaction_data["roles"][self.emoji.value] = role_id
            await interaction.response.send_message(f"✅ Added {self.emoji.value} → {role.name}", ephemeral=True)

        except ValueError:
            await interaction.response.send_message("Invalid role ID.", ephemeral=True)

class ReactionRoleRewardModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Add Reaction Reward")
        self.view = view

        self.emoji = discord.ui.TextInput(
            label="Emoji",
            placeholder="Enter emoji for reward",
            required=True,
            max_length=50
        )

        self.xp_reward = discord.ui.TextInput(
            label="XP Reward",
            placeholder="XP to give when reacted",
            required=True,
            max_length=5
        )

        self.currency_reward = discord.ui.TextInput(
            label="Currency Reward",
            placeholder="Currency to give when reacted",
            required=True,
            max_length=5
        )

        self.add_item(self.emoji)
        self.add_item(self.xp_reward)
        self.add_item(self.currency_reward)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            xp = int(self.xp_reward.value)
            currency = int(self.currency_reward.value)

            self.view.reaction_data["rewards"][self.emoji.value] = {
                "xp": xp,
                "currency": currency
            }

            await interaction.response.send_message(f"✅ Added reward for {self.emoji.value}", ephemeral=True)

        except ValueError:
            await interaction.response.send_message("Invalid XP or currency amount.", ephemeral=True)

@tree.command(name="reaction_role", description="Set up reaction role systems", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def reaction_role(interaction: discord.Interaction):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to create reaction roles.", ephemeral=True)
        return

    view = ReactionRoleSetupView()
    embed = discord.Embed(
        title="Reaction Role Setup",
        description="Configure your reaction role system:",
        color=BOT_CONFIG["default_embed_color"]
    )

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# --------- Item Trading Auction System -----------

class ItemAuctionSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.auction_data = {"images": [], "looking_for": [], "preferred_colors": []}

    @discord.ui.button(label="📝 Item Details", style=discord.ButtonStyle.primary)
    async def set_details(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ItemAuctionDetailsModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🔍 Looking For", style=discord.ButtonStyle.secondary)
    async def set_looking_for(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ItemAuctionLookingForModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🎨 Preferred Colors", style=discord.ButtonStyle.secondary)
    async def set_colors(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ItemAuctionColorsModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🖼️ Add Images", style=discord.ButtonStyle.secondary)
    async def add_images(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ItemAuctionImagesModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="👤 Set Seller", style=discord.ButtonStyle.secondary)
    async def set_seller(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ItemAuctionSellerModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="⚙️ Advanced Options", style=discord.ButtonStyle.secondary)
    async def advanced_options(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ItemAuctionAdvancedView(self)
        embed = discord.Embed(
            title="Advanced Item Auction Options",
            description="Configure additional auction settings:",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="✅ Create Item Auction", style=discord.ButtonStyle.green)
    async def create_auction(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not all(key in self.auction_data for key in ["title", "seller_id"]):
            await interaction.response.send_message("Please fill out title and seller first.", ephemeral=True)
            return

        await self.create_item_auction_thread(interaction)

    async def update_display(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Creating Item Trading Auction",
            color=BOT_CONFIG["default_embed_color"]
        )

        # Show current progress
        progress = []
        if "title" in self.auction_data:
            progress.append(f"✅ Item: {self.auction_data['title']}")
        else:
            progress.append("❌ Item details not set")

        if "seller_id" in self.auction_data:
            seller = interaction.guild.get_member(self.auction_data["seller_id"])
            progress.append(f"✅ Seller: {seller.mention if seller else 'Unknown'}")
        else:
            progress.append("❌ Seller not set")

        if self.auction_data.get("looking_for"):
            progress.append(f"✅ Looking for: {len(self.auction_data['looking_for'])} items")
        else:
            progress.append("❌ Looking for items not set")

        if self.auction_data.get("images"):
            progress.append(f"✅ Images: {len(self.auction_data['images'])} added")

        embed.description = "\n".join(progress)

        await interaction.response.edit_message(embed=embed, view=self)

    async def create_item_auction_thread(self, interaction):
        if not has_staff_role(interaction):
            await interaction.response.send_message("You don't have permission to create auctions.", ephemeral=True)
            return

        # Build auction text with new format
        auction_text = f"# {self.auction_data['title']}"

        if self.auction_data.get("server", "N/A") != "N/A":
            auction_text += f" ({self.auction_data['server']})"

        auction_text += " <:cutesy_star:1364222257349525506>\n"

        # Add rarity and type
        rarity_line = "ᯓ★ "
        if self.auction_data.get("rarity", "NA") != "NA":
            rarity_line += self.auction_data["rarity"]
        if self.auction_data.get("type_category", "NA") != "NA":
            if self.auction_data.get("rarity", "NA") != "NA":
                rarity_line += " ‧ "
            rarity_line += self.auction_data["type_category"]
        auction_text += rarity_line + "\n"

        seller = interaction.guild.get_member(self.auction_data["seller_id"])
        auction_text += f"<:neonstars:1364582630363758685> ── .✦ Seller: {seller.mention}\n\n"

        # Looking for section
        if self.auction_data.get("looking_for"):
            looking_for_formatted = " ‧ ".join(self.auction_data["looking_for"])
            # Split into multiple lines if too long
            looking_for_lines = []
            current_line = ""
            for item in self.auction_data["looking_for"]:
                if len(current_line + " ‧ " + item) > 50:  # Reasonable line length
                    looking_for_lines.append(current_line)
                    current_line = item
                else:
                    if current_line:
                        current_line += " ‧ " + item
                    else:
                        current_line = item
            if current_line:
                looking_for_lines.append(current_line)
            
            auction_text += f"      ✶⋆.˚ Looking For:\n"
            for line in looking_for_lines:
                auction_text += f"               {line}\n"

        # Preferred colors section
        if self.auction_data.get("preferred_colors"):
            colors_formatted = " ‧ ".join(self.auction_data["preferred_colors"])
            auction_text += f"      ✶⋆.˚ Preferred Colors:\n               {colors_formatted}\n\n"
        else:
            auction_text += "\n"

        # IA section
        auction_text += f"╰┈➤ IA: {self.auction_data.get('instant_accept', 'N/A')}\n\n"

        # Extra info
        if self.auction_data.get("extra_info"):
            auction_text += f"༘⋆ Extra info: {self.auction_data['extra_info']}\n"

        # Holds
        if self.auction_data.get("holds"):
            auction_text += f"𓂃 𓈒𓏸 Holds: {self.auction_data['holds']}"
            if self.auction_data.get("hold_days"):
                auction_text += f" ‧ {self.auction_data['hold_days']} Days"
            auction_text += "\n\n"

        # End timestamp
        if self.auction_data.get("end_timestamp"):
            auction_text += f"     Ends: {self.auction_data['end_timestamp']}\n\n"

        # Role mentions
        bidder_role = interaction.guild.get_role(BOT_CONFIG["bidder_role_id"])
        buyer_role = interaction.guild.get_role(BOT_CONFIG["buyer_role_id"])

        if bidder_role and buyer_role:
            auction_text += f"{bidder_role.mention}\n{buyer_role.mention}"

        # Get forum channel for item auctions
        forum_channel = bot.get_channel(BOT_CONFIG.get("item_auction_forum_channel_id") or BOT_CONFIG["auction_forum_channel_id"])

        if not forum_channel:
            await interaction.response.send_message("Auction forum channel not found.", ephemeral=True)
            return

        try:
            await interaction.response.send_message("Creating item auction thread...", ephemeral=True)

            # Create forum thread
            thread = await forum_channel.create_thread(
                name=f"[TRADE] {self.auction_data['title']}",
                content=auction_text
            )

            # Upload images
            images_uploaded = 0
            failed_uploads = 0
            
            if self.auction_data.get("use_attachments"):
                # Look for recent messages with attachments from the user
                async for message in interaction.channel.history(limit=10):
                    if (message.author.id == interaction.user.id and 
                        message.attachments and 
                        len(message.attachments) > 0):
                        
                        for attachment in message.attachments[:5]:
                            if attachment.content_type and attachment.content_type.startswith('image/'):
                                success = await upload_file_attachment_to_thread(thread, attachment)
                                if success:
                                    images_uploaded += 1
                                else:
                                    failed_uploads += 1
                        break
            else:
                for img_url in self.auction_data.get("images", []):
                    if img_url and img_url.strip():
                        success = await upload_image_to_thread(thread, img_url)
                        if success:
                            images_uploaded += 1
                        else:
                            failed_uploads += 1

            # Save auction data
            auction_id = str(thread.id)
            auction_data[auction_id] = {
                "title": self.auction_data["title"],
                "seller_id": self.auction_data["seller_id"],
                "thread_id": thread.id,
                "status": "active",
                "type": "item_trade"
            }
            save_all()

            embed = discord.Embed(
                title="✅ Item Auction Created!",
                description=f"Item trading auction for **{self.auction_data['title']}** has been posted in {thread.mention}!",
                color=0x00FF00
            )

            if images_uploaded > 0 or failed_uploads > 0:
                image_status = f"✅ {images_uploaded} uploaded"
                if failed_uploads > 0:
                    image_status += f", ❌ {failed_uploads} failed"
                embed.add_field(name="Images", value=image_status, inline=True)

            await interaction.edit_original_response(embed=embed)

        except Exception as e:
            await interaction.edit_original_response(content=f"Failed to create item auction: {str(e)}")

class ItemAuctionDetailsModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Item Auction Details")
        self.view = view

        self.title = discord.ui.TextInput(
            label="Item Title",
            placeholder="Enter the item name/title",
            required=True,
            max_length=100
        )

        self.rarity = discord.ui.TextInput(
            label="Rarity (NS/S/NA)",
            placeholder="Enter rarity (NS, S, or NA)",
            required=False,
            max_length=10
        )

        self.type_category = discord.ui.TextInput(
            label="Type (EXO/OG/BOTH/NA)",
            placeholder="Enter type (EXO, OG, BOTH, or NA)",
            required=False,
            max_length=10
        )

        self.server = discord.ui.TextInput(
            label="Server (Optional)",
            placeholder="Enter server name",
            required=False,
            max_length=20
        )

        self.add_item(self.title)
        self.add_item(self.rarity)
        self.add_item(self.type_category)
        self.add_item(self.server)

    async def on_submit(self, interaction: discord.Interaction):
        self.view.auction_data.update({
            "title": self.title.value,
            "rarity": self.rarity.value or "NA",
            "type_category": self.type_category.value or "NA",
            "server": self.server.value or "N/A"
        })

        await self.view.update_display(interaction)

class ItemAuctionLookingForModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Items Looking For")
        self.view = view

        self.looking_for = discord.ui.TextInput(
            label="Looking For Items",
            placeholder="Enter items you're looking for (one per line or separated by commas)",
            required=True,
            max_length=1000,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.looking_for)

    async def on_submit(self, interaction: discord.Interaction):
        # Parse items from text (handle both comma and newline separation)
        items_text = self.looking_for.value.replace('\n', ',')
        items = [item.strip() for item in items_text.split(',') if item.strip()]
        self.view.auction_data["looking_for"] = items[:12]  # Reasonable limit

        await self.view.update_display(interaction)

class ItemAuctionColorsModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Preferred Colors")
        self.view = view

        self.colors = discord.ui.TextInput(
            label="Preferred Colors",
            placeholder="Enter preferred colors (separated by commas)",
            required=False,
            max_length=200
        )
        self.add_item(self.colors)

    async def on_submit(self, interaction: discord.Interaction):
        if self.colors.value.strip():
            colors = [color.strip() for color in self.colors.value.split(',') if color.strip()]
            self.view.auction_data["preferred_colors"] = colors[:6]  # Reasonable limit

        await self.view.update_display(interaction)

class ItemAuctionImagesModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Add Item Images")
        self.view = view

        self.images = discord.ui.TextInput(
            label="Image URLs",
            placeholder="Enter image URLs (one per line, max 5)\nOr use 'attachment' to upload files directly",
            required=False,
            max_length=2000,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.images)

    async def on_submit(self, interaction: discord.Interaction):
        if self.images.value.strip().lower() == "attachment":
            # Signal that user wants to use attachments
            await interaction.response.send_message(
                "📎 **Attachment Mode Enabled**\n\n"
                "You can now attach up to 5 images to your next message in this channel. "
                "Send a message with your image attachments, then return to create the auction.",
                ephemeral=True
            )
            self.view.auction_data["use_attachments"] = True
            return
        
        image_urls = [url.strip() for url in self.images.value.split('\n') if url.strip()]
        self.view.auction_data["images"] = image_urls[:5]

        await self.view.update_display(interaction)

class ItemAuctionSellerModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Set Seller")
        self.view = view

        self.seller = discord.ui.TextInput(
            label="Seller User ID",
            placeholder="Enter the seller's Discord user ID",
            required=True,
            max_length=20
        )
        self.add_item(self.seller)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            seller_id = int(self.seller.value)
            seller = interaction.guild.get_member(seller_id)

            if not seller:
                await interaction.response.send_message("User not found in this server.", ephemeral=True)
                return

            self.view.auction_data["seller_id"] = seller_id
            await self.view.update_display(interaction)

        except ValueError:
            await interaction.response.send_message("Invalid user ID. Please enter numbers only.", ephemeral=True)

class ItemAuctionAdvancedView(discord.ui.View):
    def __init__(self, parent_view):
        super().__init__(timeout=300)
        self.parent_view = parent_view

    @discord.ui.button(label="Set IA", style=discord.ButtonStyle.secondary)
    async def set_ia(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ItemAuctionIAModal(self.parent_view)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Set Extra Info", style=discord.ButtonStyle.secondary)
    async def set_extra_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ItemAuctionExtraInfoModal(self.parent_view)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Back to Main", style=discord.ButtonStyle.primary)
    async def back_to_main(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.parent_view.update_display(interaction)

class ItemAuctionIAModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Set Instant Accept")
        self.view = view

        self.ia = discord.ui.TextInput(
            label="Instant Accept",
            placeholder="What would you instantly accept?",
            required=False,
            max_length=200
        )
        self.add_item(self.ia)

    async def on_submit(self, interaction: discord.Interaction):
        self.view.auction_data["instant_accept"] = self.ia.value or "N/A"
        await interaction.response.send_message("IA updated!", ephemeral=True)

class ItemAuctionExtraInfoModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Additional Info")
        self.view = view

        self.extra_info = discord.ui.TextInput(
            label="Extra Information",
            placeholder="Any additional details",
            required=False,
            max_length=500,
            style=discord.TextStyle.paragraph
        )

        self.holds = discord.ui.TextInput(
            label="Holds Accepted",
            placeholder="Yes, No, or Ask",
            required=False,
            max_length=10
        )

        self.hold_days = discord.ui.TextInput(
            label="Hold Days",
            placeholder="Number of days for holds",
            required=False,
            max_length=3
        )

        self.end_timestamp = discord.ui.TextInput(
            label="End Timestamp",
            placeholder="Discord timestamp for auction end",
            required=False,
            max_length=50
        )

        self.add_item(self.extra_info)
        self.add_item(self.holds)
        self.add_item(self.hold_days)
        self.add_item(self.end_timestamp)

    async def on_submit(self, interaction: discord.Interaction):
        if self.extra_info.value:
            self.view.auction_data["extra_info"] = self.extra_info.value
        if self.holds.value:
            self.view.auction_data["holds"] = self.holds.value
        if self.hold_days.value:
            try:
                self.view.auction_data["hold_days"] = int(self.hold_days.value)
            except ValueError:
                pass
        if self.end_timestamp.value:
            self.view.auction_data["end_timestamp"] = self.end_timestamp.value

        await interaction.response.send_message("Advanced settings updated!", ephemeral=True)

# --------- Enhanced Auction System with Image Upload -----------

class AuctionSetupView(discord.ui.View):
    def __init__(self, is_premium=False):
        super().__init__(timeout=600)
        self.is_premium = is_premium
        self.auction_data = {"is_premium": is_premium, "images": []}

    @discord.ui.button(label="📝 Item Details", style=discord.ButtonStyle.primary)
    async def set_details(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AuctionDetailsModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🖼️ Add Images", style=discord.ButtonStyle.secondary)
    async def add_images(self, interaction: discord.Interaction, button: discord.ui.Button):
        if "name" not in self.auction_data:
            await interaction.response.send_message("Please set item details first.", ephemeral=True)
            return
        modal = AuctionImagesModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="👤 Set Seller", style=discord.ButtonStyle.secondary)
    async def set_seller(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AuctionSellerModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="⚙️ Advanced Options", style=discord.ButtonStyle.secondary)
    async def advanced_options(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AuctionAdvancedView(self)
        embed = discord.Embed(
            title="Advanced Auction Options",
            description="Configure additional auction settings:",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="✅ Create Auction", style=discord.ButtonStyle.green)
    async def create_auction(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not all(key in self.auction_data for key in ["name", "seller_id", "starting_bid"]):
            await interaction.response.send_message("Please fill out all required fields first.", ephemeral=True)
            return

        await self.create_auction_thread(interaction)

    async def update_display(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"Creating {'Premium ' if self.is_premium else ''}Auction",
            color=BOT_CONFIG["default_embed_color"]
        )

        # Show current progress
        progress = []
        if "name" in self.auction_data:
            progress.append(f"✅ Item: {self.auction_data['name']}")
        else:
            progress.append("❌ Item details not set")

        if "seller_id" in self.auction_data:
            seller = interaction.guild.get_member(self.auction_data["seller_id"])
            progress.append(f"✅ Seller: {seller.mention if seller else 'Unknown'}")
        else:
            progress.append("❌ Seller not set")

        if self.auction_data.get("images"):
            progress.append(f"✅ Images: {len(self.auction_data['images'])} added")
        else:
            progress.append("❌ No images added")

        embed.description = "\n".join(progress)

        if "starting_bid" in self.auction_data:
            embed.add_field(
                name="Auction Details",
                value=f"Starting Bid: ${self.auction_data['starting_bid']}\n"
                      f"Payment Methods: {self.auction_data.get('payment_methods', 'Not set')}\n"
                      f"Instant Accept: {self.auction_data.get('instant_accept', 'N/A')}",
                inline=False
            )

        await interaction.response.edit_message(embed=embed, view=self)

    async def create_auction_thread(self, interaction):
        if not has_staff_role(interaction):
            await interaction.response.send_message("You don't have permission to create auctions.", ephemeral=True)
            return

        # Check premium slots if needed
        if self.auction_data.get("is_premium"):
            seller_id = str(self.auction_data["seller_id"])
            user_slots = premium_slots.get(seller_id, {"total_slots": 0, "used_slots": 0})
            if user_slots["used_slots"] >= user_slots["total_slots"]:
                await interaction.response.send_message("Seller doesn't have available premium slots.", ephemeral=True)
                return

        # Build auction text
        auction_text = f"# {self.auction_data['name']}"

        if self.auction_data.get("server", "N/A") != "N/A":
            auction_text += f" ({self.auction_data['server']})"

        auction_text += " <:cutesy_star:1364222257349525506>\n"

        # Add rarity and type
        rarity_line = "ᯓ★ "
        if self.auction_data.get("rarity", "NA") != "NA":
            rarity_line += self.auction_data["rarity"]
        if self.auction_data.get("type_category", "NA") != "NA":
            if self.auction_data.get("rarity", "NA") != "NA":
                rarity_line += " ‧ "
            rarity_line += self.auction_data["type_category"]
        auction_text += rarity_line + "\n"

        seller = interaction.guild.get_member(self.auction_data["seller_id"])
        auction_text += f"<:neonstars:1364582630363758685> ── .✦ Seller: {seller.mention}\n\n"

        # Payment methods
        if self.auction_data.get("payment_methods"):
            methods_formatted = " ‧ ".join([method.strip() for method in self.auction_data["payment_methods"].split(",")])
            auction_text += f"      ✶⋆.˚ Payment Methods:\n                 {methods_formatted}\n\n"

        # Bidding info
        auction_text += f"╰┈➤ Starting: ${self.auction_data['starting_bid']}\n"
        auction_text += f"╰┈➤ Increase: {self.auction_data.get('increase', '$1')}\n"
        auction_text += f"╰┈➤ IA: {self.auction_data.get('instant_accept', 'N/A')}\n\n"

        # Extra info
        if self.auction_data.get("extra_info"):
            auction_text += f"༘⋆ Extra Info: {self.auction_data['extra_info']}\n"

        # Holds
        if self.auction_data.get("holds"):
            auction_text += f"𓂃 𓈒𓏸 Holds: {self.auction_data['holds']}"
            if self.auction_data.get("hold_days"):
                auction_text += f"  ‧  {self.auction_data['hold_days']} Days"
            auction_text += "\n\n"

        # End timestamp
        if self.auction_data.get("end_timestamp"):
            auction_text += f"     Ends: {self.auction_data['end_timestamp']}\n\n"

        # Role mentions
        bidder_role = interaction.guild.get_role(BOT_CONFIG["bidder_role_id"])
        buyer_role = interaction.guild.get_role(BOT_CONFIG["buyer_role_id"])

        if bidder_role and buyer_role:
            auction_text += f"{bidder_role.mention} {buyer_role.mention}"

        # Get forum channel
        channel_key = "premium_auction_forum_channel_id" if self.auction_data.get("is_premium") else "auction_forum_channel_id"
        forum_channel = bot.get_channel(BOT_CONFIG[channel_key])

        if not forum_channel:
            await interaction.response.send_message("Auction forum channel not found.", ephemeral=True)
            return

        try:
            await interaction.response.send_message("Creating auction thread and uploading images...", ephemeral=True)

            # Create forum thread
            thread = await forum_channel.create_thread(
                name=self.auction_data["name"],
                content=auction_text
            )

            # Upload images - handle both URLs and attachments
            images_uploaded = 0
            failed_uploads = 0
            
            # Check if using attachments mode
            if self.auction_data.get("use_attachments"):
                # Look for recent messages with attachments from the user
                async for message in interaction.channel.history(limit=10):
                    if (message.author.id == interaction.user.id and 
                        message.attachments and 
                        len(message.attachments) > 0):
                        
                        for attachment in message.attachments[:5]:  # Max 5 attachments
                            if attachment.content_type and attachment.content_type.startswith('image/'):
                                success = await upload_file_attachment_to_thread(thread, attachment)
                                if success:
                                    images_uploaded += 1
                                else:
                                    failed_uploads += 1
                        break
            else:
                # Handle URL uploads with retry logic
                for img_url in self.auction_data.get("images", []):
                    if img_url and img_url.strip():
                        success = await upload_image_to_thread(thread, img_url)
                        if success:
                            images_uploaded += 1
                        else:
                            failed_uploads += 1
                            # Try one more time for failed URLs
                            await asyncio.sleep(1)
                            retry_success = await upload_image_to_thread(thread, img_url)
                            if retry_success:
                                images_uploaded += 1
                                failed_uploads -= 1

            # Use premium slot if needed
            if self.auction_data.get("is_premium"):
                seller_id = str(self.auction_data["seller_id"])
                if seller_id not in premium_slots:
                    premium_slots[seller_id] = {"total_slots": 0, "used_slots": 0}
                premium_slots[seller_id]["used_slots"] += 1

            # Save auction data
            auction_id = str(thread.id)
            auction_data[auction_id] = {
                "name": self.auction_data["name"],
                "seller_id": self.auction_data["seller_id"],
                "starting_bid": self.auction_data["starting_bid"],
                "thread_id": thread.id,
                "status": "active",
                "is_premium": self.auction_data.get("is_premium", False)
            }
            save_all()

            embed = discord.Embed(
                title="✅ Auction Created!",
                description=f"Auction for **{self.auction_data['name']}** has been posted in {thread.mention}!",
                color=0x00FF00
            )

            if images_uploaded > 0 or failed_uploads > 0:
                image_status = f"✅ {images_uploaded} uploaded"
                if failed_uploads > 0:
                    image_status += f", ❌ {failed_uploads} failed"
                embed.add_field(name="Images", value=image_status, inline=True)

            await interaction.edit_original_response(embed=embed)

        except Exception as e:
            await interaction.edit_original_response(content=f"Failed to create auction: {str(e)}")

class AuctionDetailsModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Auction Item Details")
        self.view = view

        self.name = discord.ui.TextInput(
            label="Item Name",
            placeholder="Enter the item name",
            required=True,
            max_length=100
        )

        self.starting_bid = discord.ui.TextInput(
            label="Starting Bid (1-10)",
            placeholder="Enter starting bid ($1-$10)",
            required=True,
            max_length=2
        )

        self.payment_methods = discord.ui.TextInput(
            label="Payment Methods",
            placeholder="Separate with commas (e.g., PayPal, Venmo, Cash)",
            required=True,
            max_length=200,
            style=discord.TextStyle.paragraph
        )

        self.instant_accept = discord.ui.TextInput(
            label="Instant Accept",
            placeholder="Enter instant accept amount (e.g., $50)",
            required=False,
            max_length=20
        )

        self.add_item(self.name)
        self.add_item(self.starting_bid)
        self.add_item(self.payment_methods)
        self.add_item(self.instant_accept)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            starting_bid = int(self.starting_bid.value)
            if starting_bid < 1 or starting_bid > 10:
                await interaction.response.send_message("Starting bid must be between $1 and $10.", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("Invalid starting bid. Please enter a number.", ephemeral=True)
            return

        self.view.auction_data.update({
            "name": self.name.value,
            "starting_bid": starting_bid,
            "payment_methods": self.payment_methods.value,
            "instant_accept": self.instant_accept.value or "N/A"
        })

        await self.view.update_display(interaction)

class AuctionImagesModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Add Auction Images")
        self.view = view

        self.images = discord.ui.TextInput(
            label="Image URLs",
            placeholder="Enter image URLs (one per line, max 5)\nOr use 'attachment' to upload files directly",
            required=False,
            max_length=2000,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.images)

    async def on_submit(self, interaction: discord.Interaction):
        if self.images.value.strip().lower() == "attachment":
            # Signal that user wants to use attachments
            await interaction.response.send_message(
                "📎 **Attachment Mode Enabled**\n\n"
                "You can now attach up to 5 images to your next message in this channel. "
                "Send a message with your image attachments, then return to create the auction.",
                ephemeral=True
            )
            self.view.auction_data["use_attachments"] = True
            return
        
        image_urls = [url.strip() for url in self.images.value.split('\n') if url.strip()]
        self.view.auction_data["images"] = image_urls[:5]  # Limit to 5 images

        await self.view.update_display(interaction)

class AuctionSellerModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Set Seller")
        self.view = view

        self.seller = discord.ui.TextInput(
            label="Seller User ID",
            placeholder="Enter the seller's Discord user ID",
            required=True,
            max_length=20
        )
        self.add_item(self.seller)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            seller_id = int(self.seller.value)
            seller = interaction.guild.get_member(seller_id)

            if not seller:
                await interaction.response.send_message("User not found in this server.", ephemeral=True)
                return

            self.view.auction_data["seller_id"] = seller_id
            await self.view.update_display(interaction)

        except ValueError:
            await interaction.response.send_message("Invalid user ID. Please enter numbers only.", ephemeral=True)

class AuctionAdvancedView(discord.ui.View):
    def __init__(self, parent_view):
        super().__init__(timeout=300)
        self.parent_view = parent_view

    @discord.ui.select(
        placeholder="Select server location...",
        options=[
            discord.SelectOption(label="US", value="US"),
            discord.SelectOption(label="UK", value="UK"),
            discord.SelectOption(label="CA", value="CA"),
            discord.SelectOption(label="TR", value="TR"),
            discord.SelectOption(label="N/A", value="N/A"),
        ]
    )
    async def server_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.parent_view.auction_data["server"] = select.values[0]
        await interaction.response.send_message(f"Set server location to: {select.values[0]}", ephemeral=True)

    @discord.ui.select(
        placeholder="Select item rarity...",
        options=[
            discord.SelectOption(label="S", value="S"),
            discord.SelectOption(label="NS", value="NS"),
            discord.SelectOption(label="NA", value="NA"),
        ]
    )
    async def rarity_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.parent_view.auction_data["rarity"] = select.values[0]
        await interaction.response.send_message(f"Set rarity to: {select.values[0]}", ephemeral=True)

    @discord.ui.select(
        placeholder="Select item type...",
        options=[
            discord.SelectOption(label="EXO", value="EXO"),
            discord.SelectOption(label="OG", value="OG"),
            discord.SelectOption(label="NA", value="NA"),
        ]
    )
    async def type_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.parent_view.auction_data["type_category"] = select.values[0]
        await interaction.response.send_message(f"Set type to: {select.values[0]}", ephemeral=True)

    @discord.ui.button(label="Set Extra Info", style=discord.ButtonStyle.secondary)
    async def set_extra_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AuctionExtraInfoModal(self.parent_view)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Back to Main", style=discord.ButtonStyle.primary)
    async def back_to_main(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.parent_view.update_display(interaction)

class AuctionExtraInfoModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Additional Auction Info")
        self.view = view

        self.extra_info = discord.ui.TextInput(
            label="Extra Information",
            placeholder="Any additional details about the item",
            required=False,
            max_length=500,
            style=discord.TextStyle.paragraph
        )

        self.holds = discord.ui.TextInput(
            label="Holds Accepted",
            placeholder="Yes, No, or Ask",
            required=False,
            max_length=10
        )

        self.hold_days = discord.ui.TextInput(
            label="Hold Days",
            placeholder="Number of days for holds",
            required=False,
            max_length=3
        )

        self.end_timestamp = discord.ui.TextInput(
            label="End Timestamp",
            placeholder="Discord timestamp for auction end",
            required=False,
            max_length=50
        )

        self.add_item(self.extra_info)
        self.add_item(self.holds)
        self.add_item(self.hold_days)
        self.add_item(self.end_timestamp)

    async def on_submit(self, interaction: discord.Interaction):
        if self.extra_info.value:
            self.view.auction_data["extra_info"] = self.extra_info.value
        if self.holds.value:
            self.view.auction_data["holds"] = self.holds.value
        if self.hold_days.value:
            try:
                self.view.auction_data["hold_days"] = int(self.hold_days.value)
            except ValueError:
                pass
        if self.end_timestamp.value:
            self.view.auction_data["end_timestamp"] = self.end_timestamp.value

        await interaction.response.send_message("Advanced settings updated!", ephemeral=True)

@tree.command(name="auction", description="Create auctions with interactive setup", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(
    auction_type="Type of auction to create"
)
@app_commands.choices(auction_type=[
    app_commands.Choice(name="Regular Auction", value="regular"),
    app_commands.Choice(name="Premium Auction", value="premium"),
])
async def auction(interaction: discord.Interaction, auction_type: app_commands.Choice[str]):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to create auctions.", ephemeral=True)
        return

    is_premium = auction_type.value == "premium"
    view = AuctionSetupView(is_premium)

    embed = discord.Embed(
        title=f"Creating {'Premium ' if is_premium else ''}Auction",
        description="❌ Item details not set\n❌ Seller not set\n❌ No images added",
        color=BOT_CONFIG["default_embed_color"]
    )

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@tree.command(name="auctionitems", description="Create item trading auctions", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def auctionitems(interaction: discord.Interaction):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to create auctions.", ephemeral=True)
        return

    view = ItemAuctionSetupView()

    embed = discord.Embed(
        title="Creating Item Trading Auction",
        description="❌ Item details not set\n❌ Seller not set\n❌ Looking for items not set",
        color=BOT_CONFIG["default_embed_color"]
    )

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# --------- Enhanced Giveaway System -----------

class GiveawaySetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.giveaway_data = {
            "participants": {},
            "status": "creating",
            "required_roles": [],
            "extra_entry_roles": [],
            "bypass_roles": []
        }

    @discord.ui.button(label="📝 Basic Info", style=discord.ButtonStyle.primary)
    async def set_basic_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = GiveawayBasicModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="⚙️ Requirements", style=discord.ButtonStyle.secondary)
    async def set_requirements(self, interaction: discord.Interaction, button: discord.ui.Button):
        if "name" not in self.giveaway_data:
            await interaction.response.send_message("Please set basic info first.", ephemeral=True)
            return
        view = GiveawayRequirementsView(self)
        embed = discord.Embed(
            title="Set Giveaway Requirements",
            description="Configure who can join your giveaway:",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="🎨 Appearance", style=discord.ButtonStyle.secondary)
    async def set_appearance(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = GiveawayAppearanceModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="✅ Create Giveaway", style=discord.ButtonStyle.green)
    async def create_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not all(key in self.giveaway_data for key in ["name", "prizes", "duration_hours", "winners", "host_id"]):
            await interaction.response.send_message("Please fill out all required fields first.", ephemeral=True)
            return

        await self.create_giveaway_message(interaction)

    async def update_display(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Creating Giveaway",
            color=BOT_CONFIG["default_embed_color"]
        )

        # Show current progress
        progress = []
        if "name" in self.giveaway_data:
            progress.append(f"✅ Name: {self.giveaway_data['name']}")
        else:
            progress.append("❌ Basic info not set")

        if self.giveaway_data.get("required_roles"):
            progress.append(f"✅ Role requirements: {len(self.giveaway_data['required_roles'])} roles")

        if self.giveaway_data.get("extra_entry_roles"):
            progress.append(f"✅ Extra entries: {len(self.giveaway_data['extra_entry_roles'])} configured")

        embed.description = "\n".join(progress) if progress else "No configuration set yet"

        if "duration_hours" in self.giveaway_data:
            embed.add_field(
                name="Giveaway Details",
                value=f"Duration: {self.giveaway_data['duration_hours']} hours\n"
                      f"Winners: {self.giveaway_data.get('winners', 'Not set')}\n"
                      f"Prizes: {self.giveaway_data.get('prizes', 'Not set')[:100]}...",
                inline=False
            )

        await interaction.response.edit_message(embed=embed, view=self)

    async def create_giveaway_message(self, interaction):
        giveaway_id = str(uuid.uuid4())
        end_time = int(time.time()) + (self.giveaway_data["duration_hours"] * 3600)

        self.giveaway_data.update({
            "id": giveaway_id,
            "end_time": end_time,
            "status": "active",
            "channel_id": interaction.channel.id
        })

        # Create giveaway embed
        embed = discord.Embed(
            title=f"🎉 {self.giveaway_data['name']}",
            description=f"**Prizes:** {self.giveaway_data['prizes']}",
            color=self.giveaway_data.get("embed_color", BOT_CONFIG["default_embed_color"])
        )

        host = interaction.guild.get_member(self.giveaway_data["host_id"])
        embed.add_field(name="Host", value=host.mention if host else "Unknown", inline=True)
        embed.add_field(name="Winners", value=str(self.giveaway_data["winners"]), inline=True)
        embed.add_field(name="Ends", value=f"<t:{end_time}:R>", inline=True)

        if self.giveaway_data.get("required_level"):
            embed.add_field(name="Required Level", value=str(self.giveaway_data["required_level"]), inline=True)

        if self.giveaway_data.get("thumbnail_url"):
            embed.set_thumbnail(url=self.giveaway_data["thumbnail_url"])
        if self.giveaway_data.get("image_url"):
            embed.set_image(url=self.giveaway_data["image_url"])

        embed.set_footer(text="Click the button below to join!")

        view = GiveawayJoinView(giveaway_id)
        giveaway_message = await interaction.followup.send(embed=embed, view=view)

        self.giveaway_data["message_id"] = giveaway_message.id
        giveaways_data[giveaway_id] = self.giveaway_data
        save_json("giveaways.json", giveaways_data)

        success_embed = discord.Embed(
            title="✅ Giveaway Created!",
            description=f"Giveaway '{self.giveaway_data['name']}' has been created!",
            color=0x00FF00
        )

        await interaction.edit_original_response(embed=success_embed)

class GiveawayBasicModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Giveaway Basic Information")
        self.view = view

        self.name = discord.ui.TextInput(
            label="Giveaway Name",
            placeholder="Enter the giveaway name",
            required=True,
            max_length=100
        )

        self.prizes = discord.ui.TextInput(
            label="Prizes",
            placeholder="What are you giving away?",
            required=True,
            max_length=500,
            style=discord.TextStyle.paragraph
        )

        self.duration = discord.ui.TextInput(
            label="Duration (hours)",
            placeholder="How long should the giveaway run?",
            required=True,
            max_length=3
        )

        self.winners = discord.ui.TextInput(
            label="Number of Winners",
            placeholder="How many winners?",
            required=True,
            max_length=2
        )

        self.add_item(self.name)
        self.add_item(self.prizes)
        self.add_item(self.duration)
        self.add_item(self.winners)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            duration_hours = int(self.duration.value)
            winners = int(self.winners.value)

            if duration_hours <= 0 or winners <= 0:
                await interaction.response.send_message("Duration and winners must be positive numbers.", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("Invalid duration or winners. Please enter numbers only.", ephemeral=True)
            return

        self.view.giveaway_data.update({
            "name": self.name.value,
            "prizes": self.prizes.value,
            "duration_hours": duration_hours,
            "winners": winners,
            "host_id": interaction.user.id
        })

        await self.view.update_display(interaction)

class GiveawayRequirementsView(discord.ui.View):
    def __init__(self, parent_view):
        super().__init__(timeout=300)
        self.parent_view = parent_view

    @discord.ui.button(label="Add Required Role", style=discord.ButtonStyle.secondary)
    async def add_required_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = GiveawayRoleModal(self.parent_view, "required")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Add Extra Entry Role", style=discord.ButtonStyle.secondary)
    async def add_extra_entry_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = GiveawayExtraEntryModal(self.parent_view)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Add Bypass Role", style=discord.ButtonStyle.secondary)
    async def add_bypass_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = GiveawayRoleModal(self.parent_view, "bypass")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Set Level Requirement", style=discord.ButtonStyle.secondary)
    async def set_level_requirement(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = GiveawayLevelModal(self.parent_view)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Back to Main", style=discord.ButtonStyle.primary)
    async def back_to_main(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.parent_view.update_display(interaction)

class GiveawayAppearanceModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Giveaway Appearance")
        self.view = view

        self.embed_color = discord.ui.TextInput(
            label="Embed Color (hex)",
            placeholder="e.g., #FF5733 or FF5733",
            required=False,
            max_length=7
        )

        self.thumbnail_url = discord.ui.TextInput(
            label="Thumbnail URL",
            placeholder="Image URL for thumbnail",
            required=False,
            max_length=500
        )

        self.image_url = discord.ui.TextInput(
            label="Main Image URL",
            placeholder="Image URL for main image",
            required=False,
            max_length=500
        )

        self.add_item(self.embed_color)
        self.add_item(self.thumbnail_url)
        self.add_item(self.image_url)

    async def on_submit(self, interaction: discord.Interaction):
        if self.embed_color.value:
            try:
                hex_color = self.embed_color.value.lstrip('#')
                color = int(hex_color, 16)
                self.view.giveaway_data["embed_color"] = color
            except ValueError:
                await interaction.response.send_message("Invalid hex color format.", ephemeral=True)
                return

        if self.thumbnail_url.value:
            self.view.giveaway_data["thumbnail_url"] = self.thumbnail_url.value
        if self.image_url.value:
            self.view.giveaway_data["image_url"] = self.image_url.value

        await interaction.response.send_message("Appearance settings updated!", ephemeral=True)

class GiveawayRoleModal(discord.ui.Modal):
    def __init__(self, view, role_type):
        super().__init__(title=f"Add {role_type.title()} Role")
        self.view = view
        self.role_type = role_type

        self.role_input = discord.ui.TextInput(
            label="Role ID",
            placeholder="Enter the role ID",
            required=True,
            max_length=20
        )
        self.add_item(self.role_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            role_id = int(self.role_input.value)
            role = interaction.guild.get_role(role_id)

            if not role:
                await interaction.response.send_message("Role not found.", ephemeral=True)
                return

            key = f"{self.role_type}_roles"
            if role_id not in self.view.giveaway_data[key]:
                self.view.giveaway_data[key].append(role_id)
                await interaction.response.send_message(f"✅ Added {role.name} as a {self.role_type} role", ephemeral=True)
            else:
                await interaction.response.send_message("Role already added.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Invalid role ID.", ephemeral=True)

class GiveawayExtraEntryModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Add Extra Entry Role")
        self.view = view

        self.role_input = discord.ui.TextInput(
            label="Role ID",
            placeholder="Enter the role ID",
            required=True,
            max_length=20
        )

        self.entries_input = discord.ui.TextInput(
            label="Number of Entries",
            placeholder="How many entries should this role get?",
            required=True,
            max_length=2
        )

        self.add_item(self.role_input)
        self.add_item(self.entries_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            role_id = int(self.role_input.value)
            entries = int(self.entries_input.value)

            if entries <= 0:
                await interaction.response.send_message("Entries must be positive.", ephemeral=True)
                return

            role = interaction.guild.get_role(role_id)
            if not role:
                await interaction.response.send_message("Role not found.", ephemeral=True)
                return

            # Remove existing entry for this role
            self.view.giveaway_data["extra_entry_roles"] = [
                r for r in self.view.giveaway_data["extra_entry_roles"] 
                if r["role_id"] != role_id
            ]

            self.view.giveaway_data["extra_entry_roles"].append({
                "role_id": role_id,
                "entries": entries
            })

            await interaction.response.send_message(f"✅ Added {role.name} for {entries} entries", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Invalid role ID or entries number.", ephemeral=True)

class GiveawayLevelModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Set Level Requirement")
        self.view = view

        self.level_input = discord.ui.TextInput(
            label="Required Level",
            placeholder="Enter minimum level required",
            required=True,
            max_length=3
        )
        self.add_item(self.level_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            level = int(self.level_input.value)
            if level < 0:
                await interaction.response.send_message("Level must be 0 or higher.", ephemeral=True)
                return

            self.view.giveaway_data["required_level"] = level
            await interaction.response.send_message(f"✅ Set required level to {level}", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Invalid level. Please enter a number.", ephemeral=True)

class GiveawayJoinView(discord.ui.View):
    def __init__(self, giveaway_id: str):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

    @discord.ui.button(label="🎉 Join Giveaway", style=discord.ButtonStyle.primary)
    async def join_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = giveaways_data.get(self.giveaway_id)
        if not giveaway or giveaway["status"] != "active":
            await interaction.response.send_message("This giveaway is no longer active.", ephemeral=True)
            return

        user_id = str(interaction.user.id)

        # Check role restrictions
        if giveaway.get("required_roles"):
            user_role_ids = [role.id for role in interaction.user.roles]
            if not any(role_id in user_role_ids for role_id in giveaway["required_roles"]):
                await interaction.response.send_message("You don't have the required roles to join this giveaway.", ephemeral=True)
                return

        # Check level requirement
        if giveaway.get("required_level", 0) > 0:
            ensure_user_in_stats(user_id)
            user_level = calculate_level(member_stats.get(user_id, {}).get("xp", 0))
            if user_level < giveaway["required_level"]:
                # Check bypass roles
                if giveaway.get("bypass_roles"):
                    user_role_ids = [role.id for role in interaction.user.roles]
                    has_bypass = any(role_id in user_role_ids for role_id in giveaway["bypass_roles"])
                    if not has_bypass:
                        await interaction.response.send_message(f"You need to be Level {giveaway['required_level']} or higher to join this giveaway.", ephemeral=True)
                        return
                else:
                    await interaction.response.send_message(f"You need to be Level {giveaway['required_level']} or higher to join this giveaway.", ephemeral=True)
                    return

        # Add user to participants
        if user_id not in giveaway["participants"]:
            giveaway["participants"][user_id] = {"entries": 1}

        # Check for extra entries
        if giveaway.get("extra_entry_roles"):
            user_role_ids = [role.id for role in interaction.user.roles]
            for role_config in giveaway["extra_entry_roles"]:
                if role_config["role_id"] in user_role_ids:
                    giveaway["participants"][user_id]["entries"] = role_config["entries"]
                    break

        save_json("giveaways.json", giveaways_data)

        entries = giveaway["participants"][user_id]["entries"]
        entry_text = "entry" if entries == 1 else "entries"
        await interaction.response.send_message(f"You've joined the giveaway with {entries} {entry_text}!", ephemeral=True)

    @discord.ui.button(label="📊 View Info", style=discord.ButtonStyle.secondary)
    async def view_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = giveaways_data.get(self.giveaway_id)
        if not giveaway:
            await interaction.response.send_message("Giveaway not found.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Giveaway Information",
            color=BOT_CONFIG["default_embed_color"]
        )

        embed.add_field(name="Participants", value=str(len(giveaway["participants"])), inline=True)
        total_entries = sum(data["entries"] for data in giveaway["participants"].values())
        embed.add_field(name="Total Entries", value=str(total_entries), inline=True)
        embed.add_field(name="Time Left", value=f"<t:{giveaway['end_time']}:R>", inline=True)

        if giveaway.get("required_level"):
            embed.add_field(name="Required Level", value=str(giveaway["required_level"]), inline=True)

        if giveaway.get("required_roles"):
            roles = [interaction.guild.get_role(rid).name for rid in giveaway["required_roles"] if interaction.guild.get_role(rid)]
            if roles:
                embed.add_field(name="Required Roles", value=", ".join(roles[:3]), inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="giveaway", description="Create giveaways with interactive setup", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def giveaway(interaction: discord.Interaction):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to create giveaways.", ephemeral=True)
        return

    view = GiveawaySetupView()
    embed = discord.Embed(
        title="Creating Giveaway",
        description="❌ Basic Info | ⚙️ Requirements | 🎨 Appearance",
        color=BOT_CONFIG["default_embed_color"]
    )

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# --------- Profile Management System -----------

class ProfileCreateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(placeholder="Select a profile preset...")
    async def preset_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        preset_name = select.values[0]
        if preset_name == "none":
            await interaction.response.send_message("No presets available.", ephemeral=True)
            return

        preset = profile_presets.get(preset_name)
        if not preset:
            await interaction.response.send_message("Preset not found.", ephemeral=True)
            return

        modal = ProfileCreateModal(preset)
        await interaction.response.send_modal(modal)

    async def update_preset_list(self):
        options = []
        for preset_name in profile_presets.keys():
            options.append(discord.SelectOption(label=preset_name, value=preset_name))
        
        if not options:
            options.append(discord.SelectOption(label="No presets available", value="none"))
        
        self.children[0].options = options[:25]

class ProfileCreateModal(discord.ui.Modal):
    def __init__(self, preset):
        super().__init__(title=f"Create Profile - {preset['name']}")
        self.preset = preset

        for field in preset["fields"][:5]:  # Discord modal limit
            field_type = field.get("field_type", "text")
            
            # Set appropriate placeholder based on field type
            placeholder = field.get("placeholder", "")
            if field_type == "image" and not placeholder:
                placeholder = "Enter image URL (e.g., https://example.com/image.png)"
            
            text_input = discord.ui.TextInput(
                label=field["label"],
                placeholder=placeholder,
                required=field.get("required", False),
                max_length=field.get("max_length", 100),
                style=discord.TextStyle.paragraph if field.get("multiline") else discord.TextStyle.short
            )
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        profile_data = {
            "preset": self.preset["name"],
            "fields": {},
            "images": {},  # Store image URLs separately for easier embed handling
            "created_at": int(time.time())
        }

        for i, field in enumerate(self.preset["fields"][:5]):
            if i < len(self.children):
                field_value = self.children[i].value
                field_type = field.get("field_type", "text")
                
                profile_data["fields"][field["label"]] = field_value
                
                # Store image URLs separately
                if field_type == "image" and field_value:
                    profile_data["images"][field["label"]] = field_value

        user_profiles[user_id] = profile_data
        save_json("user_profiles.json", user_profiles)

        embed = discord.Embed(
            title="✅ Profile Created!",
            description=f"Your profile has been created using the '{self.preset['name']}' preset.",
            color=0x00FF00
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="profile", description="Profile management commands", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(action="Profile action to perform")
@app_commands.choices(action=[
    app_commands.Choice(name="Create Profile", value="create"),
    app_commands.Choice(name="View Profile", value="view"),
    app_commands.Choice(name="Edit Profile", value="edit"),
    app_commands.Choice(name="List Presets", value="presets"),
    app_commands.Choice(name="Create Preset (Staff)", value="create_preset"),
])
async def profile_command(interaction: discord.Interaction, action: app_commands.Choice[str], user: discord.Member = None):
    if action.value == "create":
        view = ProfileCreateView()
        await view.update_preset_list()
        
        embed = discord.Embed(
            title="Create Your Profile",
            description="Select a preset to get started:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    elif action.value == "view":
        target_user = user or interaction.user
        user_id = str(target_user.id)
        
        if user_id not in user_profiles:
            await interaction.response.send_message(f"{target_user.display_name} doesn't have a profile yet.", ephemeral=True)
            return

        profile = user_profiles[user_id]
        preset = profile_presets.get(profile.get("preset"))
        
        embed = discord.Embed(
            title=f"{target_user.display_name}'s Profile",
            color=BOT_CONFIG["default_embed_color"]
        )
        embed.set_thumbnail(url=target_user.avatar.url if target_user.avatar else target_user.default_avatar.url)

        # Handle image fields for embed display
        profile_image_url = None
        banner_image_url = None
        
        for field_name, field_value in profile["fields"].items():
            if field_value:
                # Check if this is an image field
                field_config = None
                if preset:
                    field_config = next((f for f in preset["fields"] if f["label"] == field_name), None)
                
                if field_config and field_config.get("field_type") == "image":
                    # Handle image fields specially
                    if "profile" in field_name.lower() or "picture" in field_name.lower() or "avatar" in field_name.lower():
                        profile_image_url = field_value
                        embed.add_field(name=f"🖼️ {field_name}", value=f"[View Image]({field_value})", inline=True)
                    elif "banner" in field_name.lower() or "cover" in field_name.lower():
                        banner_image_url = field_value
                        embed.add_field(name=f"🖼️ {field_name}", value=f"[View Image]({field_value})", inline=True)
                    else:
                        embed.add_field(name=f"🖼️ {field_name}", value=f"[View Image]({field_value})", inline=True)
                else:
                    # Regular text fields
                    embed.add_field(name=field_name, value=field_value, inline=True)

        # Set embed images if available
        if profile_image_url:
            try:
                embed.set_thumbnail(url=profile_image_url)
            except:
                pass  # Invalid URL, use default thumbnail
        
        if banner_image_url:
            try:
                embed.set_image(url=banner_image_url)
            except:
                pass  # Invalid URL, skip banner

        embed.set_footer(text=f"Profile preset: {profile.get('preset', 'Unknown')}")
        
        await interaction.response.send_message(embed=embed)

    elif action.value == "presets":
        embed = discord.Embed(
            title="Available Profile Presets",
            color=BOT_CONFIG["default_embed_color"]
        )

        if not profile_presets:
            embed.description = "No presets available."
        else:
            for preset_name, preset in profile_presets.items():
                fields = ", ".join([field["label"] for field in preset["fields"]])
                embed.add_field(name=preset_name, value=f"Fields: {fields}", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    elif action.value == "create_preset":
        if not has_staff_role(interaction):
            await interaction.response.send_message("You don't have permission to create presets.", ephemeral=True)
            return

        modal = CreatePresetModal()
        await interaction.response.send_modal(modal)

    elif action.value == "edit":
        user_id = str(interaction.user.id)
        if user_id not in user_profiles:
            await interaction.response.send_message("You don't have a profile yet. Use `/profile create` first.", ephemeral=True)
            return

        profile = user_profiles[user_id]
        preset = profile_presets.get(profile["preset"])
        if not preset:
            await interaction.response.send_message("Your profile preset is no longer available.", ephemeral=True)
            return

        modal = ProfileEditModal(profile, preset)
        await interaction.response.send_modal(modal)

class CreatePresetModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Create Profile Preset - Basic Info")

        self.name = discord.ui.TextInput(
            label="Preset Name",
            placeholder="Enter preset name",
            required=True,
            max_length=50
        )

        self.description = discord.ui.TextInput(
            label="Description",
            placeholder="Enter preset description",
            required=False,
            max_length=200,
            style=discord.TextStyle.paragraph
        )

        self.add_item(self.name)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction):
        preset_name = self.name.value.strip()
        
        if preset_name in profile_presets:
            await interaction.response.send_message("A preset with this name already exists.", ephemeral=True)
            return
        
        # Show field configuration view
        view = PresetFieldConfigView(preset_name, self.description.value.strip(), interaction.user.id)
        await view.show_field_config(interaction)

class PresetFieldConfigView(discord.ui.View):
    def __init__(self, preset_name, description, creator_id):
        super().__init__(timeout=600)
        self.preset_name = preset_name
        self.description = description
        self.creator_id = creator_id
        self.fields = []

    @discord.ui.button(label="Add Text Field", style=discord.ButtonStyle.primary)
    async def add_text_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AddFieldModal(self, "text")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Add Image URL Field", style=discord.ButtonStyle.secondary)
    async def add_image_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AddFieldModal(self, "image")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Add Long Text Field", style=discord.ButtonStyle.secondary)
    async def add_long_text_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AddFieldModal(self, "longtext")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Remove Last Field", style=discord.ButtonStyle.red)
    async def remove_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.fields:
            self.fields.pop()
            await self.show_field_config(interaction)
        else:
            await interaction.response.send_message("No fields to remove.", ephemeral=True)

    @discord.ui.button(label="Save Preset", style=discord.ButtonStyle.green)
    async def save_preset(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.fields:
            await interaction.response.send_message("Please add at least one field before saving.", ephemeral=True)
            return

        profile_presets[self.preset_name] = {
            "name": self.preset_name,
            "description": self.description,
            "fields": self.fields,
            "created_by": self.creator_id
        }
        save_json("profile_presets.json", profile_presets)

        embed = discord.Embed(
            title="✅ Profile Preset Created!",
            description=f"Preset '{self.preset_name}' has been created with {len(self.fields)} fields.",
            color=0x00FF00
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def show_field_config(self, interaction):
        embed = discord.Embed(
            title=f"Creating Preset: {self.preset_name}",
            description=self.description or "No description",
            color=BOT_CONFIG["default_embed_color"]
        )

        if self.fields:
            field_list = []
            for i, field in enumerate(self.fields, 1):
                field_type = field.get("field_type", "text")
                required = "Required" if field.get("required", False) else "Optional"
                field_list.append(f"{i}. **{field['label']}** ({field_type.title()}) - {required}")
            
            embed.add_field(
                name=f"Fields ({len(self.fields)})",
                value="\n".join(field_list),
                inline=False
            )
        else:
            embed.add_field(
                name="Fields",
                value="No fields added yet. Use the buttons below to add fields.",
                inline=False
            )

        embed.add_field(
            name="Field Types",
            value="• **Text Field** - Short text input\n• **Image URL Field** - For profile pictures/banners\n• **Long Text Field** - Multi-line text input",
            inline=False
        )

        if hasattr(interaction, 'response') and not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

class AddFieldModal(discord.ui.Modal):
    def __init__(self, preset_view, field_type):
        self.preset_view = preset_view
        self.field_type = field_type
        
        title_map = {
            "text": "Add Text Field",
            "image": "Add Image URL Field", 
            "longtext": "Add Long Text Field"
        }
        super().__init__(title=title_map.get(field_type, "Add Field"))

        self.label = discord.ui.TextInput(
            label="Field Label",
            placeholder="Enter the field name (e.g., 'Profile Picture', 'About Me')",
            required=True,
            max_length=100
        )

        self.placeholder = discord.ui.TextInput(
            label="Placeholder Text",
            placeholder="Enter placeholder text for users to see",
            required=False,
            max_length=100
        )

        self.required = discord.ui.TextInput(
            label="Required Field?",
            placeholder="Enter 'yes' if required, 'no' if optional",
            default="no",
            required=True,
            max_length=3
        )

        if field_type == "image":
            self.max_length = discord.ui.TextInput(
                label="Max URL Length",
                placeholder="Maximum characters for image URL (default: 500)",
                default="500",
                required=False,
                max_length=4
            )
        elif field_type == "text":
            self.max_length = discord.ui.TextInput(
                label="Max Text Length",
                placeholder="Maximum characters (default: 100)",
                default="100",
                required=False,
                max_length=3
            )
        elif field_type == "longtext":
            self.max_length = discord.ui.TextInput(
                label="Max Text Length",
                placeholder="Maximum characters (default: 1000)",
                default="1000",
                required=False,
                max_length=4
            )

        self.add_item(self.label)
        self.add_item(self.placeholder)
        self.add_item(self.required)
        self.add_item(self.max_length)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            max_length = int(self.max_length.value) if self.max_length.value else (500 if self.field_type == "image" else 100)
            required = self.required.value.lower().strip() in ["yes", "y", "true", "1"]

            field_data = {
                "label": self.label.value,
                "placeholder": self.placeholder.value or f"Enter {self.label.value.lower()}",
                "required": required,
                "max_length": max_length,
                "field_type": self.field_type,
                "multiline": self.field_type == "longtext"
            }

            self.preset_view.fields.append(field_data)
            await self.preset_view.show_field_config(interaction)

        except ValueError:
            await interaction.response.send_message("Invalid max length. Please enter a number.", ephemeral=True)

class ProfileEditModal(discord.ui.Modal):
    def __init__(self, profile, preset):
        super().__init__(title="Edit Profile")
        self.profile = profile
        self.preset = preset

        for field in preset["fields"][:5]:
            current_value = profile["fields"].get(field["label"], "")
            field_type = field.get("field_type", "text")
            
            # Set appropriate placeholder based on field type
            placeholder = field.get("placeholder", "")
            if field_type == "image" and not placeholder:
                placeholder = "Enter image URL (e.g., https://example.com/image.png)"
            
            text_input = discord.ui.TextInput(
                label=field["label"],
                placeholder=placeholder,
                default=current_value,
                required=field.get("required", False),
                max_length=field.get("max_length", 100),
                style=discord.TextStyle.paragraph if field.get("multiline") else discord.TextStyle.short
            )
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        
        # Initialize images dict if it doesn't exist
        if "images" not in self.profile:
            self.profile["images"] = {}
        
        for i, field in enumerate(self.preset["fields"][:5]):
            if i < len(self.children):
                field_value = self.children[i].value
                field_type = field.get("field_type", "text")
                
                self.profile["fields"][field["label"]] = field_value
                
                # Update image URLs separately
                if field_type == "image":
                    if field_value:
                        self.profile["images"][field["label"]] = field_value
                    elif field["label"] in self.profile["images"]:
                        del self.profile["images"][field["label"]]

        user_profiles[user_id] = self.profile
        save_json("user_profiles.json", user_profiles)

        embed = discord.Embed(
            title="✅ Profile Updated!",
            description="Your profile has been successfully updated.",
            color=0x00FF00
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

# --------- Verification System -----------

class VerificationSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📝 Set Verification Word", style=discord.ButtonStyle.primary)
    async def set_word(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = VerificationWordModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🎭 Set Verification Role", style=discord.ButtonStyle.secondary)
    async def set_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = VerificationRoleModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🗑️ Toggle Delete Messages", style=discord.ButtonStyle.secondary)
    async def toggle_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_setting = verification_data.get("delete_messages", False)
        verification_data["delete_messages"] = not current_setting
        save_json("verification.json", verification_data)
        
        status = "enabled" if verification_data["delete_messages"] else "disabled"
        await interaction.response.send_message(f"✅ Message deletion is now **{status}**", ephemeral=True)

    @discord.ui.button(label="📋 View Settings", style=discord.ButtonStyle.secondary)
    async def view_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_display(interaction)

    @discord.ui.button(label="✅ Enable Verification", style=discord.ButtonStyle.green)
    async def enable_verification(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not verification_data.get("word") or not verification_data.get("role_id"):
            await interaction.response.send_message("Please set both verification word and role first.", ephemeral=True)
            return

        verification_data["enabled"] = True
        save_json("verification.json", verification_data)
        await interaction.response.send_message("✅ Verification system enabled!", ephemeral=True)

    @discord.ui.button(label="❌ Disable Verification", style=discord.ButtonStyle.red)
    async def disable_verification(self, interaction: discord.Interaction, button: discord.ui.Button):
        verification_data["enabled"] = False
        save_json("verification.json", verification_data)
        await interaction.response.send_message("❌ Verification system disabled!", ephemeral=True)

    async def update_display(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Verification System Settings",
            color=BOT_CONFIG["default_embed_color"]
        )

        # Status
        status = "🟢 Enabled" if verification_data.get("enabled", False) else "🔴 Disabled"
        embed.add_field(name="Status", value=status, inline=True)

        # Word
        word = verification_data.get("word", "Not set")
        embed.add_field(name="Verification Word", value=f"`{word}`" if word != "Not set" else word, inline=True)

        # Role
        role_id = verification_data.get("role_id")
        if role_id:
            role = interaction.guild.get_role(role_id)
            role_value = role.mention if role else f"Invalid Role ({role_id})"
        else:
            role_value = "Not set"
        embed.add_field(name="Verification Role", value=role_value, inline=True)

        # Delete setting
        delete_enabled = "🟢 Yes" if verification_data.get("delete_messages", False) else "🔴 No"
        embed.add_field(name="Delete Messages", value=delete_enabled, inline=True)

        # Channel restriction
        channel_id = verification_data.get("channel_id")
        if channel_id:
            channel = bot.get_channel(channel_id)
            channel_value = channel.mention if channel else f"Invalid Channel ({channel_id})"
        else:
            channel_value = "Any channel"
        embed.add_field(name="Restricted Channel", value=channel_value, inline=True)

        await interaction.response.edit_message(embed=embed, view=self)

class VerificationWordModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Set Verification Word")

        self.word = discord.ui.TextInput(
            label="Verification Word",
            placeholder="Enter the word users must say to get verified",
            required=True,
            max_length=50
        )
        self.add_item(self.word)

    async def on_submit(self, interaction: discord.Interaction):
        verification_data["word"] = self.word.value.lower().strip()
        save_json("verification.json", verification_data)
        await interaction.response.send_message(f"✅ Verification word set to: `{self.word.value}`", ephemeral=True)

class VerificationRoleModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Set Verification Role")

        self.role_id = discord.ui.TextInput(
            label="Role ID",
            placeholder="Enter the role ID to give verified users",
            required=True,
            max_length=20
        )
        self.add_item(self.role_id)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            role_id = int(self.role_id.value)
            role = interaction.guild.get_role(role_id)
            
            if not role:
                await interaction.response.send_message("Role not found in this server.", ephemeral=True)
                return

            verification_data["role_id"] = role_id
            save_json("verification.json", verification_data)
            await interaction.response.send_message(f"✅ Verification role set to: {role.mention}", ephemeral=True)

        except ValueError:
            await interaction.response.send_message("Invalid role ID. Please enter numbers only.", ephemeral=True)


class ChannelIDModal(discord.ui.Modal):
    def __init__(self, config_key, callback_view=None):
        super().__init__(title="Enter Channel ID")
        self.config_key = config_key
        self.callback_view = callback_view

        self.channel_id = discord.ui.TextInput(
            label="Channel ID",
            placeholder="Enter the channel ID (numbers only)",
            required=True,
            max_length=20
        )
        self.add_item(self.channel_id)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            channel_id = int(self.channel_id.value)
            channel = bot.get_channel(channel_id)
            
            if not channel:
                await interaction.response.send_message("Channel not found. Please check the ID and try again.", ephemeral=True)
                return
            
            BOT_CONFIG[self.config_key] = channel_id
            save_json("bot_config.json", BOT_CONFIG)
            
            config_name = self.config_key.replace('_', ' ').title()
            embed = discord.Embed(
                title="✅ Channel Updated",
                description=f"{config_name} has been set to {channel.mention}",
                color=0x00FF00
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message("Invalid channel ID. Please enter numbers only.", ephemeral=True)

class RoleIDModal(discord.ui.Modal):
    def __init__(self, config_key, callback_view=None, boost_level=None, invite_count=None):
        super().__init__(title="Enter Role ID")
        self.config_key = config_key
        self.callback_view = callback_view
        self.boost_level = boost_level
        self.invite_count = invite_count

        self.role_id = discord.ui.TextInput(
            label="Role ID",
            placeholder="Enter the role ID (numbers only)",
            required=True,
            max_length=20
        )
        self.add_item(self.role_id)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            role_id = int(self.role_id.value)
            role = interaction.guild.get_role(role_id)
            
            if not role:
                await interaction.response.send_message("Role not found. Please check the ID and try again.", ephemeral=True)
                return
            
            if self.boost_level:
                # Handle boost role configuration
                if "boost_roles" not in BOT_CONFIG:
                    BOT_CONFIG["boost_roles"] = {}
                BOT_CONFIG["boost_roles"][self.boost_level] = role_id
                save_json("bot_config.json", BOT_CONFIG)
                
                embed = discord.Embed(
                    title="✅ Boost Role Updated",
                    description=f"Boost level {self.boost_level} role has been set to {role.mention}",
                    color=0x00FF00
                )
            elif self.invite_count:
                # Handle invite role configuration
                if "invite_roles" not in BOT_CONFIG:
                    BOT_CONFIG["invite_roles"] = {}
                BOT_CONFIG["invite_roles"][str(self.invite_count)] = role_id
                save_json("bot_config.json", BOT_CONFIG)
                
                embed = discord.Embed(
                    title="✅ Invite Role Updated",
                    description=f"Role for {self.invite_count} invites has been set to {role.mention}",
                    color=0x00FF00
                )
            else:
                # Handle regular config
                BOT_CONFIG[self.config_key] = role_id
                save_json("bot_config.json", BOT_CONFIG)
                
                config_name = self.config_key.replace('_', ' ').title()
                embed = discord.Embed(
                    title="✅ Role Updated",
                    description=f"{config_name} has been set to {role.mention}",
                    color=0x00FF00
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message("Invalid role ID. Please enter numbers only.", ephemeral=True)

class BoostRoleConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Set 2x Boost Role", style=discord.ButtonStyle.primary)
    async def set_2x_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EnhancedRoleSelectionView("boost_roles", "2x", self, boost_level="2x")
        await view.show_role_selection(interaction)

    @discord.ui.button(label="Set 3-5x Boost Role", style=discord.ButtonStyle.primary)
    async def set_3_5x_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EnhancedRoleSelectionView("boost_roles", "3-5x", self, boost_level="3-5x")
        await view.show_role_selection(interaction)

    @discord.ui.button(label="Set 6+ Boost Role", style=discord.ButtonStyle.primary)
    async def set_6plus_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EnhancedRoleSelectionView("boost_roles", "6+", self, boost_level="6+")
        await view.show_role_selection(interaction)

    @discord.ui.button(label="Test Boost Detection", style=discord.ButtonStyle.secondary)
    async def test_boost_detection(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        # Force update boost roles for all members
        updated_count = 0
        for member in interaction.guild.members:
            if not member.bot and member.premium_since:
                await update_member_boost_roles(member)
                updated_count += 1
        
        embed = discord.Embed(
            title="✅ Boost Detection Test Complete",
            description=f"Updated boost roles for {updated_count} boosting members",
            color=0x00FF00
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="← Back to Config", style=discord.ButtonStyle.secondary)
    async def back_to_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ConfigurationView()
        embed = discord.Embed(
            title="Bot Configuration",
            description="Select a category to configure:",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_boost_config(self, interaction):
        embed = discord.Embed(
            title="Boost Role Configuration",
            description="Configure automatic roles for server boosters:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        boost_roles_config = BOT_CONFIG.get("boost_roles", {})
        
        for level, role_id in boost_roles_config.items():
            role = interaction.guild.get_role(role_id) if role_id else None
            role_value = role.mention if role else "Not set"
            embed.add_field(name=f"{level} Boosts", value=role_value, inline=True)
        
        # Show current boost stats
        boosters = [member for member in interaction.guild.members if member.premium_since]
        embed.add_field(
            name="Current Boosters",
            value=f"{len(boosters)} members are currently boosting",
            inline=False
        )
        
        embed.add_field(
            name="How It Works",
            value="• Bot automatically detects boost level changes\n• Removes old boost roles when upgrading\n• Roles are applied immediately when boost count changes",
            inline=False
        )
        
        if hasattr(interaction, 'response') and not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

class InviteTrackingConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Set Welcome Channel", style=discord.ButtonStyle.primary)
    async def set_welcome_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ChannelSelectionView("invite_welcome_channel_id", self)
        await view.show_channel_selection(interaction)

    @discord.ui.button(label="Configure Invite Roles", style=discord.ButtonStyle.secondary)
    async def configure_invite_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = InviteRoleConfigView(self)
        await view.show_invite_roles(interaction)

    @discord.ui.button(label="Toggle Invite Tracking", style=discord.ButtonStyle.secondary)
    async def toggle_invite_tracking(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_setting = BOT_CONFIG.get("invite_tracking_enabled", False)
        BOT_CONFIG["invite_tracking_enabled"] = not current_setting
        save_json("bot_config.json", BOT_CONFIG)
        
        status = "enabled" if BOT_CONFIG["invite_tracking_enabled"] else "disabled"
        embed = discord.Embed(
            title="✅ Invite Tracking Updated",
            description=f"Invite tracking is now **{status}**",
            color=0x00FF00
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await asyncio.sleep(2)
        await self.show_invite_config(interaction)

    @discord.ui.button(label="Sync Invites", style=discord.ButtonStyle.secondary)
    async def sync_invites(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        # Cache current invites
        await cache_guild_invites(interaction.guild)
        
        embed = discord.Embed(
            title="✅ Invites Synced",
            description="All current invites have been cached for tracking",
            color=0x00FF00
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="← Back to Config", style=discord.ButtonStyle.secondary)
    async def back_to_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ConfigurationView()
        embed = discord.Embed(
            title="Bot Configuration",
            description="Select a category to configure:",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_invite_config(self, interaction):
        embed = discord.Embed(
            title="Invite Tracking Configuration",
            description="Configure invite tracking and role rewards:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        # Welcome channel
        welcome_channel_id = BOT_CONFIG.get("invite_welcome_channel_id")
        if welcome_channel_id:
            welcome_channel = bot.get_channel(welcome_channel_id)
            welcome_value = welcome_channel.mention if welcome_channel else f"Invalid ({welcome_channel_id})"
        else:
            welcome_value = "Not set"
        embed.add_field(name="Welcome Channel", value=welcome_value, inline=True)
        
        # Tracking status
        tracking_enabled = BOT_CONFIG.get("invite_tracking_enabled", False)
        status = "🟢 Enabled" if tracking_enabled else "🔴 Disabled"
        embed.add_field(name="Tracking Status", value=status, inline=True)
        
        # Invite roles
        invite_roles_config = BOT_CONFIG.get("invite_roles", {})
        if invite_roles_config:
            roles_text = []
            for count, role_id in sorted(invite_roles_config.items(), key=lambda x: int(x[0])):
                role = interaction.guild.get_role(role_id)
                role_name = role.mention if role else f"Invalid ({role_id})"
                roles_text.append(f"{count} invites: {role_name}")
            embed.add_field(name="Invite Roles", value="\n".join(roles_text), inline=False)
        else:
            embed.add_field(name="Invite Roles", value="None configured", inline=False)
        
        # Current stats
        total_tracked = len(invite_data.get("members", {}))
        embed.add_field(
            name="Statistics",
            value=f"Tracking {total_tracked} members",
            inline=True
        )
        
        if hasattr(interaction, 'response') and not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

class InviteRoleConfigView(discord.ui.View):
    def __init__(self, parent_view):
        super().__init__(timeout=300)
        self.parent_view = parent_view

    @discord.ui.button(label="Add Invite Role", style=discord.ButtonStyle.green)
    async def add_invite_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = InviteRoleModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Remove Invite Role", style=discord.ButtonStyle.red)
    async def remove_invite_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RemoveInviteRoleModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="← Back to Invite Config", style=discord.ButtonStyle.secondary)
    async def back_to_invite_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.parent_view.show_invite_config(interaction)

    async def show_invite_roles(self, interaction):
        embed = discord.Embed(
            title="Invite Role Configuration",
            description="Manage roles awarded based on invite counts:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        invite_roles_config = BOT_CONFIG.get("invite_roles", {})
        if invite_roles_config:
            roles_text = []
            for count, role_id in sorted(invite_roles_config.items(), key=lambda x: int(x[0])):
                role = interaction.guild.get_role(role_id)
                role_name = role.mention if role else f"Invalid Role ({role_id})"
                roles_text.append(f"**{count} invites**: {role_name}")
            embed.add_field(name="Current Invite Roles", value="\n".join(roles_text), inline=False)
        else:
            embed.add_field(name="Current Invite Roles", value="None configured", inline=False)
        
        embed.add_field(
            name="How It Works",
            value="• Members automatically get roles when they reach invite milestones\n• Higher roles replace lower ones\n• Roles are updated when invite counts change",
            inline=False
        )
        
        await interaction.response.edit_message(embed=embed, view=self)

class InviteRoleModal(discord.ui.Modal):
    def __init__(self, parent_view):
        super().__init__(title="Add Invite Role")
        self.parent_view = parent_view

        self.invite_count = discord.ui.TextInput(
            label="Invite Count",
            placeholder="Number of invites required (e.g., 5, 10, 25)",
            required=True,
            max_length=5
        )

        self.role_id = discord.ui.TextInput(
            label="Role ID",
            placeholder="Enter the role ID",
            required=True,
            max_length=20
        )

        self.add_item(self.invite_count)
        self.add_item(self.role_id)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = int(self.invite_count.value)
            role_id = int(self.role_id.value)
            
            if count <= 0:
                await interaction.response.send_message("Invite count must be positive.", ephemeral=True)
                return
            
            role = interaction.guild.get_role(role_id)
            if not role:
                await interaction.response.send_message("Role not found.", ephemeral=True)
                return
            
            if "invite_roles" not in BOT_CONFIG:
                BOT_CONFIG["invite_roles"] = {}
            
            BOT_CONFIG["invite_roles"][str(count)] = role_id
            save_json("bot_config.json", BOT_CONFIG)
            
            embed = discord.Embed(
                title="✅ Invite Role Added",
                description=f"Role {role.mention} will be awarded at {count} invites",
                color=0x00FF00
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            await asyncio.sleep(2)
            await self.parent_view.show_invite_roles(interaction)
            
        except ValueError:
            await interaction.response.send_message("Invalid invite count or role ID. Please enter numbers only.", ephemeral=True)

class RemoveInviteRoleModal(discord.ui.Modal):
    def __init__(self, parent_view):
        super().__init__(title="Remove Invite Role")
        self.parent_view = parent_view

        self.invite_count = discord.ui.TextInput(
            label="Invite Count",
            placeholder="Enter the invite count to remove (e.g., 5, 10, 25)",
            required=True,
            max_length=5
        )
        self.add_item(self.invite_count)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = str(int(self.invite_count.value))
            
            invite_roles_config = BOT_CONFIG.get("invite_roles", {})
            if count in invite_roles_config:
                role_id = invite_roles_config[count]
                role = interaction.guild.get_role(role_id)
                role_name = role.mention if role else f"Role ({role_id})"
                
                del BOT_CONFIG["invite_roles"][count]
                save_json("bot_config.json", BOT_CONFIG)
                
                embed = discord.Embed(
                    title="✅ Invite Role Removed",
                    description=f"Removed {role_name} from {count} invites requirement",
                    color=0x00FF00
                )
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                await asyncio.sleep(2)
                await self.parent_view.show_invite_roles(interaction)
            else:
                await interaction.response.send_message("No role found for that invite count.", ephemeral=True)
                
        except ValueError:
            await interaction.response.send_message("Invalid invite count. Please enter a number.", ephemeral=True)

class EnhancedRoleSelectionView(discord.ui.View):
    def __init__(self, config_key, role_type, callback_view=None, boost_level=None, invite_count=None):
        super().__init__(timeout=300)
        self.config_key = config_key
        self.role_type = role_type
        self.callback_view = callback_view
        self.boost_level = boost_level
        self.invite_count = invite_count
        self.current_page = 0
        self.roles_per_page = 25

    @discord.ui.select(placeholder="Select a role...", min_values=1, max_values=1)
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if select.values[0] == "none":
            await interaction.response.send_message("No roles available.", ephemeral=True)
            return
            
        role_id = int(select.values[0])
        role = interaction.guild.get_role(role_id)
        
        if self.boost_level:
            if "boost_roles" not in BOT_CONFIG:
                BOT_CONFIG["boost_roles"] = {}
            BOT_CONFIG["boost_roles"][self.boost_level] = role_id
            save_json("bot_config.json", BOT_CONFIG)
            
            embed = discord.Embed(
                title="✅ Boost Role Updated",
                description=f"Boost level {self.boost_level} role has been set to {role.mention}",
                color=0x00FF00
            )
        elif self.invite_count:
            if "invite_roles" not in BOT_CONFIG:
                BOT_CONFIG["invite_roles"] = {}
            BOT_CONFIG["invite_roles"][str(self.invite_count)] = role_id
            save_json("bot_config.json", BOT_CONFIG)
            
            embed = discord.Embed(
                title="✅ Invite Role Updated",
                description=f"Role for {self.invite_count} invites has been set to {role.mention}",
                color=0x00FF00
            )
        else:
            BOT_CONFIG[self.config_key] = role_id
            save_json("bot_config.json", BOT_CONFIG)
            
            config_name = self.config_key.replace('_', ' ').title()
            embed = discord.Embed(
                title="✅ Role Updated",
                description=f"{config_name} has been set to {role.mention}",
                color=0x00FF00
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_role_page(interaction)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="▶️ Next", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        all_roles = self.get_available_roles(interaction.guild)
        max_pages = (len(all_roles) + self.roles_per_page - 1) // self.roles_per_page
        
        if self.current_page < max_pages - 1:
            self.current_page += 1
            await self.update_role_page(interaction)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="🆔 Enter Role ID", style=discord.ButtonStyle.primary)
    async def enter_role_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RoleIDModal(self.config_key, self.callback_view, self.boost_level, self.invite_count)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="← Back", style=discord.ButtonStyle.secondary)
    async def back_to_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.callback_view:
            if hasattr(self.callback_view, 'show_boost_config'):
                await self.callback_view.show_boost_config(interaction)
            elif hasattr(self.callback_view, 'show_invite_config'):
                await self.callback_view.show_invite_config(interaction)
            else:
                await interaction.response.edit_message(view=self.callback_view)
        else:
            view = RoleConfigView()
            await view.show_role_config(interaction)

    def get_available_roles(self, guild):
        roles = []
        for role in guild.roles:
            if not role.is_bot_managed() and role != guild.default_role:
                roles.append(role)
        return sorted(roles, key=lambda r: r.position, reverse=True)

    async def update_role_page(self, interaction):
        all_roles = self.get_available_roles(interaction.guild)
        
        start_idx = self.current_page * self.roles_per_page
        end_idx = min(start_idx + self.roles_per_page, len(all_roles))
        page_roles = all_roles[start_idx:end_idx]
        max_pages = (len(all_roles) + self.roles_per_page - 1) // self.roles_per_page
        
        options = []
        for role in page_roles:
            color_info = f"#{role.color.value:06x}" if role.color.value != 0 else "No Color"
            permissions_info = "Admin" if role.permissions.administrator else f"{len([p for p in role.permissions if p[1]])} perms"
            
            options.append(discord.SelectOption(
                label=role.name[:100],
                value=str(role.id),
                description=f"Members: {len(role.members)} • Pos: {role.position} • {color_info}"[:100]
            ))
        
        if not options:
            options.append(discord.SelectOption(label="No roles on this page", value="none"))
        
        self.children[0].options = options
        
        # Update navigation buttons
        self.children[1].disabled = self.current_page == 0
        self.children[2].disabled = self.current_page >= max_pages - 1
        
        role_type_name = self.role_type if self.role_type else "Role"
        embed = discord.Embed(
            title=f"Select {role_type_name}",
            description=f"Page {self.current_page + 1} of {max_pages}\nShowing {start_idx + 1}-{end_idx} of {len(all_roles)} roles",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        await interaction.response.edit_message(embed=embed, view=self)

    async def show_role_selection(self, interaction):
        await self.update_role_page(interaction)



@tree.command(name="verification", description="Set up verification system", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def verification_setup(interaction: discord.Interaction):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to configure verification.", ephemeral=True)
        return

    view = VerificationSetupView()
    embed = discord.Embed(
        title="Verification System Configuration",
        description="Configure the verification system for your server:",
        color=BOT_CONFIG["default_embed_color"]
    )

    # Show current status
    status = "🟢 Enabled" if verification_data.get("enabled", False) else "🔴 Disabled"
    embed.add_field(name="Current Status", value=status, inline=True)

    word = verification_data.get("word", "Not set")
    embed.add_field(name="Verification Word", value=f"`{word}`" if word != "Not set" else word, inline=True)

    delete_enabled = "🟢 Yes" if verification_data.get("delete_messages", False) else "🔴 No"
    embed.add_field(name="Delete Messages", value=delete_enabled, inline=True)

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@tree.command(name="verification_channel", description="Set verification to work only in specific channel", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(channel="Channel for verification (leave empty to allow any channel)")
async def verification_channel(interaction: discord.Interaction, channel: discord.TextChannel = None):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to configure verification.", ephemeral=True)
        return

    if channel:
        verification_data["channel_id"] = channel.id
        save_json("verification.json", verification_data)
        await interaction.response.send_message(f"✅ Verification restricted to {channel.mention}", ephemeral=True)
    else:
        verification_data.pop("channel_id", None)
        save_json("verification.json", verification_data)
        await interaction.response.send_message("✅ Verification can now work in any channel", ephemeral=True)

# --------- Missing Essential Commands Implementation -----------

@tree.command(name="trade", description="Trade items with another user", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(
    user="User to trade with",
    your_item="Item you want to give",
    their_item="Item you want to receive"
)
async def trade(interaction: discord.Interaction, user: discord.Member, your_item: str, their_item: str):
    if user.bot or user.id == interaction.user.id:
        await interaction.response.send_message("You cannot trade with bots or yourself.", ephemeral=True)
        return

    user_id = str(interaction.user.id)
    target_id = str(user.id)
    
    ensure_user_in_stats(user_id)
    ensure_user_in_stats(target_id)
    
    # Check if user has the item
    if your_item not in user_inventories.get(user_id, {}) or user_inventories[user_id][your_item] <= 0:
        await interaction.response.send_message(f"You don't have {your_item} to trade.", ephemeral=True)
        return
    
    # Check if target has their item
    if their_item not in user_inventories.get(target_id, {}) or user_inventories[target_id][their_item] <= 0:
        await interaction.response.send_message(f"{user.display_name} doesn't have {their_item} to trade.", ephemeral=True)
        return

    view = TradeConfirmView(interaction.user, user, your_item, their_item)
    embed = discord.Embed(
        title="Trade Proposal",
        description=f"{interaction.user.mention} wants to trade **{your_item}** for {user.mention}'s **{their_item}**",
        color=BOT_CONFIG["default_embed_color"]
    )
    
    await interaction.response.send_message(embed=embed, view=view)

class TradeConfirmView(discord.ui.View):
    def __init__(self, trader1, trader2, item1, item2):
        super().__init__(timeout=300)
        self.trader1 = trader1
        self.trader2 = trader2
        self.item1 = item1
        self.item2 = item2
        self.trader1_confirmed = False
        self.trader2_confirmed = False

    @discord.ui.button(label="Confirm Trade", style=discord.ButtonStyle.green)
    async def confirm_trade(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.trader1.id:
            self.trader1_confirmed = True
        elif interaction.user.id == self.trader2.id:
            self.trader2_confirmed = True
        else:
            await interaction.response.send_message("You're not part of this trade.", ephemeral=True)
            return

        if self.trader1_confirmed and self.trader2_confirmed:
            # Execute trade
            user1_id = str(self.trader1.id)
            user2_id = str(self.trader2.id)
            
            # Remove items from each user
            user_inventories[user1_id][self.item1] -= 1
            user_inventories[user2_id][self.item2] -= 1
            
            # Add items to each user
            if self.item2 not in user_inventories[user1_id]:
                user_inventories[user1_id][self.item2] = 0
            if self.item1 not in user_inventories[user2_id]:
                user_inventories[user2_id][self.item1] = 0
                
            user_inventories[user1_id][self.item2] += 1
            user_inventories[user2_id][self.item1] += 1
            
            save_json("inventories.json", user_inventories)
            
            embed = discord.Embed(
                title="✅ Trade Completed!",
                description=f"{self.trader1.mention} and {self.trader2.mention} have successfully traded items!",
                color=0x00FF00
            )
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            confirmed_users = []
            if self.trader1_confirmed:
                confirmed_users.append(self.trader1.display_name)
            if self.trader2_confirmed:
                confirmed_users.append(self.trader2.display_name)
            
            await interaction.response.send_message(f"Confirmed by: {', '.join(confirmed_users)}", ephemeral=True)

@tree.command(name="gift", description="Give an item to another user", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(user="User to give item to", item="Item to give", amount="Amount to give")
async def gift(interaction: discord.Interaction, user: discord.Member, item: str, amount: int = 1):
    if user.bot or user.id == interaction.user.id:
        await interaction.response.send_message("You cannot gift to bots or yourself.", ephemeral=True)
        return

    if amount <= 0:
        await interaction.response.send_message("Amount must be positive.", ephemeral=True)
        return

    user_id = str(interaction.user.id)
    target_id = str(user.id)
    
    ensure_user_in_stats(user_id)
    ensure_user_in_stats(target_id)
    
    # Check if user has enough of the item
    if item not in user_inventories.get(user_id, {}) or user_inventories[user_id][item] < amount:
        await interaction.response.send_message(f"You don't have {amount} {item}(s) to gift.", ephemeral=True)
        return
    
    # Transfer items
    user_inventories[user_id][item] -= amount
    
    if item not in user_inventories[target_id]:
        user_inventories[target_id][item] = 0
    user_inventories[target_id][item] += amount
    
    save_json("inventories.json", user_inventories)
    
    embed = discord.Embed(
        title="✅ Gift Sent!",
        description=f"{interaction.user.mention} gifted {amount} **{item}**(s) to {user.mention}!",
        color=0x00FF00
    )
    
    await interaction.response.send_message(embed=embed)

@tree.command(name="remindme", description="Set a personal reminder", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(time_minutes="Time in minutes", message="Reminder message")
async def remindme(interaction: discord.Interaction, time_minutes: int, message: str):
    if time_minutes <= 0 or time_minutes > 10080:  # Max 1 week
        await interaction.response.send_message("Time must be between 1 minute and 1 week (10080 minutes).", ephemeral=True)
        return

    await interaction.response.send_message(f"✅ I'll remind you in {time_minutes} minutes: {message}", ephemeral=True)
    
    # Schedule reminder
    await asyncio.sleep(time_minutes * 60)
    
    try:
        embed = discord.Embed(
            title="⏰ Reminder",
            description=message,
            color=BOT_CONFIG["default_embed_color"]
        )
        embed.set_footer(text=f"Reminder set {time_minutes} minutes ago")
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    except:
        pass  # User might have left or DMs disabled

class AuctionListView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.current_filter = "all"
        self.auctions = self.get_filtered_auctions()

    def get_filtered_auctions(self):
        """Get auctions filtered by current filter and sort by time remaining"""
        active_auctions = [auction for auction in auction_data.values() if auction.get("status") == "active"]
        
        if self.current_filter == "regular":
            active_auctions = [a for a in active_auctions if not a.get("is_premium") and a.get("type") != "item_trade"]
        elif self.current_filter == "premium":
            active_auctions = [a for a in active_auctions if a.get("is_premium")]
        elif self.current_filter == "item_trade":
            active_auctions = [a for a in active_auctions if a.get("type") == "item_trade"]
        
        # Sort by ending time if available, then by creation time
        def sort_key(auction):
            end_time = auction.get("end_time", float('inf'))
            return end_time
        
        return sorted(active_auctions, key=sort_key)

    @discord.ui.select(
        placeholder="Filter auctions...",
        options=[
            discord.SelectOption(label="All Active Auctions", value="all", emoji="📋"),
            discord.SelectOption(label="Regular Auctions", value="regular", emoji="💰"),
            discord.SelectOption(label="Premium Auctions", value="premium", emoji="⭐"),
            discord.SelectOption(label="Item Trade Auctions", value="item_trade", emoji="🔄"),
        ]
    )
    async def filter_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.current_filter = select.values[0]
        self.auctions = self.get_filtered_auctions()
        await self.update_display(interaction)

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary)
    async def refresh_auctions(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.auctions = self.get_filtered_auctions()
        await self.update_display(interaction)

    def get_auction_indicators(self, auction):
        """Get visual indicators for auction type and urgency"""
        indicators = []
        
        # Type indicators
        if auction.get("is_premium"):
            indicators.append("⭐")
        if auction.get("type") == "item_trade":
            indicators.append("🔄")
        
        # Urgency indicator
        end_time = auction.get("end_time")
        if end_time:
            time_remaining = end_time - int(time.time())
            if time_remaining <= 3600:  # Less than 1 hour
                indicators.append("🔥")
        
        return " ".join(indicators)

    def format_time_remaining(self, end_time):
        """Format time remaining as countdown"""
        if not end_time:
            return "No end time"
        
        time_remaining = end_time - int(time.time())
        if time_remaining <= 0:
            return "⏰ **ENDED**"
        
        days = time_remaining // 86400
        hours = (time_remaining % 86400) // 3600
        minutes = (time_remaining % 3600) // 60
        
        if days > 0:
            return f"⏱️ {days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"⏱️ {hours}h {minutes}m"
        else:
            return f"⏱️ {minutes}m"

    async def update_display(self, interaction: discord.Interaction):
        filter_names = {
            "all": "All Active Auctions",
            "regular": "Regular Auctions",
            "premium": "Premium Auctions ⭐",
            "item_trade": "Item Trade Auctions 🔄"
        }
        
        embed = discord.Embed(
            title=f"📋 {filter_names[self.current_filter]}",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        if not self.auctions:
            embed.description = f"No {filter_names[self.current_filter].lower()} found."
            embed.add_field(
                name="💡 Tip",
                value="Try a different filter or check back later for new auctions!",
                inline=False
            )
        else:
            # Summary statistics
            total_count = len(self.auctions)
            ending_soon = len([a for a in self.auctions if a.get("end_time") and (a["end_time"] - int(time.time())) <= 3600])
            
            embed.add_field(
                name="📊 Summary",
                value=f"**Total:** {total_count} auctions\n**Ending Soon:** {ending_soon} auctions",
                inline=True
            )
            
            # Show auctions (limit to 8 for readability)
            auction_list = []
            for i, auction in enumerate(self.auctions[:8]):
                seller = bot.get_user(auction["seller_id"])
                seller_name = seller.display_name if seller else "Unknown"
                
                indicators = self.get_auction_indicators(auction)
                
                # Format auction info
                auction_info = f"{indicators} **{auction['name']}**\n"
                auction_info += f"👤 Seller: {seller_name}\n"
                
                if auction.get("type") == "item_trade":
                    auction_info += f"🎯 IA: {auction.get('instant_accept', 'N/A')}\n"
                else:
                    starting_bid = auction.get("starting_bid", "N/A")
                    auction_info += f"💰 Starting: ${starting_bid}\n"
                
                # Time remaining
                if auction.get("end_time"):
                    time_display = self.format_time_remaining(auction["end_time"])
                    auction_info += f"{time_display}"
                else:
                    auction_info += "⏱️ No time limit"
                
                auction_list.append(auction_info)
            
            if auction_list:
                embed.add_field(
                    name="🏺 Active Auctions (Sorted by End Time)",
                    value="\n\n".join(auction_list),
                    inline=False
                )
            
            if len(self.auctions) > 8:
                embed.add_field(
                    name="📝 Note",
                    value=f"Showing first 8 of {len(self.auctions)} auctions. Use refresh to update countdown timers.",
                    inline=False
                )
        
        # Add legend
        embed.add_field(
            name="🏷️ Legend",
            value="⭐ Premium • 🔄 Item Trade • 🔥 Ending Soon (<1h) • ⏰ Ended",
            inline=False
        )
        
        embed.set_footer(text="Use the dropdown to filter • Click refresh to update timers")
        
        if hasattr(interaction, 'response') and not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

@tree.command(name="auctionlist", description="View active auctions with advanced filtering", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def auction_list(interaction: discord.Interaction):
    view = AuctionListView()
    await view.update_display(interaction)

@tree.command(name="quarantine", description="Temporarily isolate a member", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(member="Member to quarantine", duration_minutes="Duration in minutes", reason="Reason for quarantine")
async def quarantine(interaction: discord.Interaction, member: discord.Member, duration_minutes: int, reason: str = "No reason provided"):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    if duration_minutes <= 0 or duration_minutes > 10080:  # Max 1 week
        await interaction.response.send_message("Duration must be between 1 minute and 1 week.", ephemeral=True)
        return
        
        # Store original roles
        original_roles = [role.id for role in member.roles if role != interaction.guild.default_role]
        
        # Remove all roles except @everyone
        await member.edit(roles=[interaction.guild.default_role], reason=f"Quarantined by {interaction.user}: {reason}")
        
        # Store quarantine data
        quarantine_data = server_settings.get("quarantined_users", {})
        quarantine_data[str(member.id)] = {
            "original_roles": original_roles,
            "end_time": int(time.time()) + (duration_minutes * 60),
            "reason": reason,
            "staff_id": interaction.user.id
        }
        server_settings["quarantined_users"] = quarantine_data
        save_json("server_settings.json", server_settings)
        
        embed = discord.Embed(
            title="Member Quarantined",
            description=f"**Member:** {member.mention}\n**Duration:** {duration_minutes} minutes\n**Reason:** {reason}\n**Staff:** {interaction.user.mention}",
            color=0xFFA500
        )
        
        await interaction.response.send_message(embed=embed)
        
        # Schedule unquarantine
        await asyncio.sleep(duration_minutes * 60)
        await unquarantine_user(member, interaction.guild)
try:
    # Store quarantine data
    quarantine_data = server_settings.get("quarantined_users", {})
    quarantine_data[str(member.id)] = {
        "original_roles": original_roles,
        "end_time": int(time.time()) + (duration_minutes * 60),
        "reason": reason,
        "staff_id": interaction.user.id
    }
    server_settings["quarantined_users"] = quarantine_data
    save_json("server_settings.json", server_settings)

    embed = discord.Embed(
        title="Member Quarantined",
        description=f"**Member:** {member.mention}\n**Duration:** {duration_minutes} minutes\n**Reason:** {reason}\n**Staff:** {interaction.user.mention}",
        color=0xFFA500
    )

    await interaction.response.send_message(embed=embed)

    # Schedule unquarantine
    await asyncio.sleep(duration_minutes * 60)
    await unquarantine_user(member, interaction.guild)
        
except discord.Forbidden:
    await interaction.response.send_message("I don't have permission to modify this user's roles.", ephemeral=True)

async def unquarantine_user(member: discord.Member, guild: discord.Guild):
    try:
        quarantine_data = server_settings.get("quarantined_users", {})
        user_data = quarantine_data.get(str(member.id))
        
        if user_data:
            # Restore original roles
            roles_to_add = []
            for role_id in user_data["original_roles"]:
                role = guild.get_role(role_id)
                if role:
                    roles_to_add.append(role)
            
            await member.edit(roles=roles_to_add, reason="Quarantine period ended")
            
            # Remove from quarantine data
            del quarantine_data[str(member.id)]
            server_settings["quarantined_users"] = quarantine_data
            save_json("server_settings.json", server_settings)
            
    except Exception as e:
        logger.error(f"Failed to unquarantine {member}: {e}")

@tree.command(name="remove_warning", description="Remove a specific warning", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(member="Member to remove warning from", warning_id="Warning ID (first 8 characters)")
async def remove_warning(interaction: discord.Interaction, member: discord.Member, warning_id: str):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    user_id = str(member.id)
    warnings = member_warnings.get(user_id, [])
    
    # Find warning by partial ID
    warning_to_remove = None
    for warning in warnings:
        if warning["id"].startswith(warning_id):
            warning_to_remove = warning
            break
    
    if not warning_to_remove:
        await interaction.response.send_message("Warning not found.", ephemeral=True)
        return
    
    warnings.remove(warning_to_remove)
    member_warnings[user_id] = warnings
    save_json("member_warnings.json", member_warnings)
    
    embed = discord.Embed(
        title="Warning Removed",
        description=f"Removed warning from {member.mention}\n**Warning ID:** {warning_to_remove['id'][:8]}...\n**Reason:** {warning_to_remove['reason']}",
        color=0x00FF00
    )
    
    await interaction.response.send_message(embed=embed)

# --------- Comprehensive Embed Management System -----------

class EmbedManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.embed_data = {
            "title": "",
            "description": "",
            "color": BOT_CONFIG["default_embed_color"],
            "fields": [],
            "thumbnail": "",
            "image": "",
            "footer": "",
            "author": ""
        }

    @discord.ui.button(label="📝 Basic Info", style=discord.ButtonStyle.primary)
    async def set_basic_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EmbedBasicInfoModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🏷️ Add Field", style=discord.ButtonStyle.secondary)
    async def add_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.embed_data["fields"]) >= 25:
            await interaction.response.send_message("Maximum 25 fields allowed.", ephemeral=True)
            return
        modal = EmbedFieldModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🖼️ Images", style=discord.ButtonStyle.secondary)
    async def set_images(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EmbedImagesModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="⚙️ Advanced", style=discord.ButtonStyle.secondary)
    async def advanced_options(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EmbedAdvancedModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="👁️ Preview", style=discord.ButtonStyle.green)
    async def preview_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = self.create_embed()
        await interaction.response.send_message("**Preview:**", embed=embed, ephemeral=True)

    @discord.ui.button(label="📤 Post to Channel", style=discord.ButtonStyle.green)
    async def post_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any([self.embed_data["title"], self.embed_data["description"], self.embed_data["fields"]]):
            await interaction.response.send_message("Please add at least a title, description, or field before posting.", ephemeral=True)
            return
        
        view = ChannelSelectView(self)
        await view.show_channels(interaction)

    @discord.ui.button(label="💾 Save Embed", style=discord.ButtonStyle.blurple)
    async def save_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SaveEmbedModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="📋 Load Preset", style=discord.ButtonStyle.secondary)
    async def load_preset(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PresetSelectView(self, "load")
        await view.show_presets(interaction)

    @discord.ui.button(label="🗑️ Clear All", style=discord.ButtonStyle.red)
    async def clear_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.embed_data = {
            "title": "",
            "description": "",
            "color": BOT_CONFIG["default_embed_color"],
            "fields": [],
            "thumbnail": "",
            "image": "",
            "footer": "",
            "author": ""
        }
        await self.update_display(interaction)

    def create_embed(self):
        embed = discord.Embed(
            title=self.embed_data["title"] or None,
            description=self.embed_data["description"] or None,
            color=self.embed_data["color"]
        )
        
        for field in self.embed_data["fields"]:
            embed.add_field(
                name=field["name"],
                value=field["value"],
                inline=field.get("inline", False)
            )
        
        if self.embed_data["thumbnail"]:
            try:
                embed.set_thumbnail(url=self.embed_data["thumbnail"])
            except Exception:
                pass
        
        if self.embed_data["image"]:
            try:
                embed.set_image(url=self.embed_data["image"])
            except Exception:
                pass
        
        if self.embed_data["footer"]:
            embed.set_footer(text=self.embed_data["footer"])
        
        if self.embed_data["author"]:
            embed.set_author(name=self.embed_data["author"])
        
        return embed

# --------- Boost Role Management -----------

async def update_member_boost_roles(member: discord.Member):
    """Update a member's boost roles based on their current boost count"""
    if not member.premium_since:
        return
    
    boost_roles_config = BOT_CONFIG.get("boost_roles", {})
    if not boost_roles_config:
        return
    
    # Get current boost count (Discord doesn't provide direct API for this, so we estimate)
    # In a real implementation, you'd need to track this through events
    boost_count = 1  # Default to 1 if they're boosting
    
    # Determine which boost role they should have
    target_role_id = None
    roles_to_remove = []
    
    if boost_count >= 6 and "6+" in boost_roles_config:
        target_role_id = boost_roles_config["6+"]
        if "2x" in boost_roles_config:
            roles_to_remove.append(boost_roles_config["2x"])
        if "3-5x" in boost_roles_config:
            roles_to_remove.append(boost_roles_config["3-5x"])
    elif boost_count >= 3 and "3-5x" in boost_roles_config:
        target_role_id = boost_roles_config["3-5x"]
        if "2x" in boost_roles_config:
            roles_to_remove.append(boost_roles_config["2x"])
        if "6+" in boost_roles_config:
            roles_to_remove.append(boost_roles_config["6+"])
    elif boost_count >= 2 and "2x" in boost_roles_config:
        target_role_id = boost_roles_config["2x"]
        if "3-5x" in boost_roles_config:
            roles_to_remove.append(boost_roles_config["3-5x"])
        if "6+" in boost_roles_config:
            roles_to_remove.append(boost_roles_config["6+"])
    
    if target_role_id:
        target_role = member.guild.get_role(target_role_id)
        if target_role and target_role not in member.roles:
            try:
                await member.add_roles(target_role, reason="Automatic boost role assignment")
            except Exception:
                pass
    
    # Remove old boost roles
    for role_id in roles_to_remove:
        role = member.guild.get_role(role_id)
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason="Boost role upgrade")
            except Exception:
                pass

# --------- Invite Tracking System -----------

async def cache_guild_invites(guild: discord.Guild):
    """Cache all current invites for tracking"""
    try:
        invites = await guild.invites()
        
        if "invites" not in invite_data:
            invite_data["invites"] = {}
        
        for invite in invites:
            invite_data["invites"][invite.code] = {
                "uses": invite.uses or 0,
                "inviter_id": invite.inviter.id if invite.inviter else None,
                "channel_id": invite.channel.id if invite.channel else None,
                "created_at": invite.created_at.timestamp() if invite.created_at else None
            }
        
        save_json("invite_data.json", invite_data)
        
    except Exception as e:
        logger.error(f"Failed to cache guild invites: {e}")

async def update_member_invite_roles(member: discord.Member):
    """Update a member's roles based on their invite count"""
    user_id = str(member.id)
    member_data = invite_data.get("members", {}).get(user_id, {})
    invite_count = member_data.get("total_invites", 0)
    
    invite_roles_config = BOT_CONFIG.get("invite_roles", {})
    if not invite_roles_config:
        return
    
    # Find the highest role they qualify for
    target_role_id = None
    current_threshold = 0
    
    for threshold_str, role_id in invite_roles_config.items():
        threshold = int(threshold_str)
        if invite_count >= threshold and threshold > current_threshold:
            target_role_id = role_id
            current_threshold = threshold
    
    if target_role_id:
        target_role = member.guild.get_role(target_role_id)
        if target_role and target_role not in member.roles:
            # Add new role
            try:
                await member.add_roles(target_role, reason="Invite milestone reached")
            except:
                pass
            
            # Remove lower invite roles
            for threshold_str, role_id in invite_roles_config.items():
                if int(threshold_str) < current_threshold:
                    old_role = member.guild.get_role(role_id)
                    if old_role and old_role in member.roles:
                        try:
                            await member.remove_roles(old_role, reason="Invite role upgrade")
                        except:
                            pass

@tree.command(name="invites", description="View invite statistics", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(member="Member to check invites for (optional)")
async def invites(interaction: discord.Interaction, member: discord.Member = None):
    target_member = member or interaction.user
    user_id = str(target_member.id)
    
    member_data = invite_data.get("members", {}).get(user_id, {})
    
    embed = discord.Embed(
        title=f"{target_member.display_name}'s Invite Statistics",
        color=BOT_CONFIG["default_embed_color"]
    )
    embed.set_thumbnail(url=target_member.avatar.url if target_member.avatar else target_member.default_avatar.url)
    
    total_invites = member_data.get("total_invites", 0)
    left_invites = member_data.get("left_invites", 0)
    current_invites = total_invites - left_invites
    
    embed.add_field(name="Total Invites", value=str(total_invites), inline=True)
    embed.add_field(name="Left Members", value=str(left_invites), inline=True)
    embed.add_field(name="Current Invites", value=str(current_invites), inline=True)
    
    # Show recent invites
    recent_invites = member_data.get("recent_invites", [])
    if recent_invites:
        recent_text = []
        for invite_info in recent_invites[-5:]:  # Show last 5
            invited_member = interaction.guild.get_member(invite_info["member_id"])
            if invited_member:
                recent_text.append(f"• {invited_member.mention}")
        
        if recent_text:
            embed.add_field(name="Recent Invites", value="\n".join(recent_text), inline=False)
    
    # Show invite roles progress
    invite_roles_config = BOT_CONFIG.get("invite_roles", {})
    if invite_roles_config:
        next_milestone = None
        for threshold_str, role_id in sorted(invite_roles_config.items(), key=lambda x: int(x[0])):
            threshold = int(threshold_str)
            if current_invites < threshold:
                next_milestone = threshold
                break
        
        if next_milestone:
            needed = next_milestone - current_invites
            embed.add_field(
                name="Next Milestone",
                value=f"{needed} more invites to reach {next_milestone}",
                inline=False
            )
    
    await interaction.response.send_message(embed=embed)

@tree.command(name="inviteleaderboard", description="View server invite leaderboard", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def inviteleaderboard(interaction: discord.Interaction):
    members_data = invite_data.get("members", {})
    
    # Create leaderboard
    leaderboard = []
    for user_id, data in members_data.items():
        member = interaction.guild.get_member(int(user_id))
        if member:
            total_invites = data.get("total_invites", 0)
            left_invites = data.get("left_invites", 0)
            current_invites = total_invites - left_invites
            leaderboard.append((member, total_invites, current_invites))
    
    # Sort by current invites
    leaderboard.sort(key=lambda x: x[2], reverse=True)
    
    embed = discord.Embed(
        title="🏆 Invite Leaderboard",
        color=BOT_CONFIG["default_embed_color"]
    )
    
    if not leaderboard:
        embed.description = "No invite data available."
    else:
        leaderboard_text = []
        for i, (member, total, current) in enumerate(leaderboard[:10]):  # Top 10
            medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
            leaderboard_text.append(f"{medal} {member.mention}: {current} invites")
        
        embed.description = "\n".join(leaderboard_text)
    
    await interaction.response.send_message(embed=embed)

    try:
        embed.set_image(url=self.embed_data["image"])
    except Exception as e:
        pass
        
    if self.embed_data["footer"]:
            embed.set_footer(text=self.embed_data["footer"])
        
if self.embed_data["author"]:
    embed.set_author(name=self.embed_data["author"])

return embed

async def update_display(self, interaction: discord.Interaction):
    embed = discord.Embed(
        title="Embed Builder",
        description="Current embed configuration:",
        color=BOT_CONFIG["default_embed_color"]
    )
    
    # Initialize the status list
    status = []
    
    if self.embed_data["title"]:
        status.append(f"✅ Title: {self.embed_data['title'][:50]}...")
    else:
        status.append("❌ No title set")
    
    if self.embed_data["description"]:
        status.append(f"✅ Description: {len(self.embed_data['description'])} characters")
    else:
        status.append("❌ No description set")
    
    # Add the status information to the embed
    embed.add_field(
        name="Status",
        value="\n".join(status),
        inline=False
    )
    
    # Actually update the interaction (choose one based on your needs)
    if interaction.response.is_done():
        await interaction.edit_original_response(embed=embed)
    else:
        await interaction.response.edit_message(embed=embed)
        
        status.append(f"📝 Fields: {len(self.embed_data['fields'])}")
        
        if self.embed_data["thumbnail"]:
            status.append("✅ Thumbnail set")
        if self.embed_data["image"]:
            status.append("✅ Image set")
        
        embed.description = "\n".join(status)
        
        if hasattr(interaction, 'response') and not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

class EmbedBasicInfoModal(discord.ui.Modal):
    def __init__(self, embed_view):
        super().__init__(title="Embed Basic Information")
        self.embed_view = embed_view
        status = []

        self.title_input = discord.ui.TextInput(
            label="Title",
            placeholder="Enter embed title",
            default=embed_view.embed_data["title"],
            required=False,
            max_length=256
        )

        self.description_input = discord.ui.TextInput(
            label="Description",
            placeholder="Enter embed description",
            default=embed_view.embed_data["description"],
            required=False,
            max_length=4000,
            style=discord.TextStyle.paragraph
        )

        self.color_input = discord.ui.TextInput(
            label="Color (hex)",
            placeholder="e.g., #FF5733 or FF5733",
            default=f"#{embed_view.embed_data['color']:06x}",
            required=False,
            max_length=7
        )

        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.embed_view.embed_data["title"] = self.title_input.value
        self.embed_view.embed_data["description"] = self.description_input.value
        
        if self.color_input.value:
            try:
                hex_color = self.color_input.value.lstrip('#')
                color = int(hex_color, 16)
                self.embed_view.embed_data["color"] = color
            except ValueError:
                pass
        
        await self.embed_view.update_display(interaction)

class EmbedFieldModal(discord.ui.Modal):
    def __init__(self, embed_view, field_index=None):
        super().__init__(title="Add/Edit Field")
        self.embed_view = embed_view
        self.field_index = field_index

        existing_field = None
        if field_index is not None and field_index < len(embed_view.embed_data["fields"]):
            existing_field = embed_view.embed_data["fields"][field_index]

        self.name_input = discord.ui.TextInput(
            label="Field Name",
            placeholder="Enter field name",
            default=existing_field["name"] if existing_field else "",
            required=True,
            max_length=256
        )

        self.value_input = discord.ui.TextInput(
            label="Field Value",
            placeholder="Enter field value",
            default=existing_field["value"] if existing_field else "",
            required=True,
            max_length=1024,
            style=discord.TextStyle.paragraph
        )

        self.inline_input = discord.ui.TextInput(
            label="Inline (true/false)",
            placeholder="true or false",
            default=str(existing_field.get("inline", False)).lower() if existing_field else "false",
            required=False,
            max_length=5
        )

        self.add_item(self.name_input)
        self.add_item(self.value_input)
        self.add_item(self.inline_input)

    async def on_submit(self, interaction: discord.Interaction):
        inline = self.inline_input.value.lower() in ["true", "yes", "1"]
        
        field_data = {
            "name": self.name_input.value,
            "value": self.value_input.value,
            "inline": inline
        }
        
        if self.field_index is not None:
            self.embed_view.embed_data["fields"][self.field_index] = field_data
        else:
            self.embed_view.embed_data["fields"].append(field_data)
        
        await self.embed_view.update_display(interaction)

class EmbedImagesModal(discord.ui.Modal):
    def __init__(self, embed_view):
        super().__init__(title="Embed Images")
        self.embed_view = embed_view

        self.thumbnail_input = discord.ui.TextInput(
            label="Thumbnail URL",
            placeholder="Enter thumbnail image URL",
            default=embed_view.embed_data["thumbnail"],
            required=False,
            max_length=500
        )

        self.image_input = discord.ui.TextInput(
            label="Main Image URL",
            placeholder="Enter main image URL",
            default=embed_view.embed_data["image"],
            required=False,
            max_length=500
        )

        self.add_item(self.thumbnail_input)
        self.add_item(self.image_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.embed_view.embed_data["thumbnail"] = self.thumbnail_input.value
        self.embed_view.embed_data["image"] = self.image_input.value
        await self.embed_view.update_display(interaction)

class EmbedAdvancedModal(discord.ui.Modal):
    def __init__(self, embed_view):
        super().__init__(title="Advanced Options")
        self.embed_view = embed_view

        self.author_input = discord.ui.TextInput(
            label="Author Name",
            placeholder="Enter author name",
            default=embed_view.embed_data["author"],
            required=False,
            max_length=256
        )

        self.footer_input = discord.ui.TextInput(
            label="Footer Text",
            placeholder="Enter footer text",
            default=embed_view.embed_data["footer"],
            required=False,
            max_length=2048
        )

        self.add_item(self.author_input)
        self.add_item(self.footer_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.embed_view.embed_data["author"] = self.author_input.value
        self.embed_view.embed_data["footer"] = self.footer_input.value
        await self.embed_view.update_display(interaction)

class ChannelSelectView(discord.ui.View):
    def __init__(self, embed_view):
        super().__init__(timeout=300)
        self.embed_view = embed_view

    @discord.ui.select(placeholder="Select a channel to post to...")
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if select.values[0] == "none":
            await interaction.response.send_message("No channels available.", ephemeral=True)
            return
        
        channel_id = int(select.values[0])
        channel = bot.get_channel(channel_id)
        
        if not channel:
            await interaction.response.send_message("Channel not found.", ephemeral=True)
            return
        
        try:
            embed = self.embed_view.create_embed()
            await channel.send(embed=embed)
            
            success_embed = discord.Embed(
                title="✅ Embed Posted!",
                description=f"Embed has been posted to {channel.mention}",
                color=0x00FF00
            )
            await interaction.response.send_message(embed=success_embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed to post embed: {str(e)}", ephemeral=True)

    async def show_channels(self, interaction):
        """Show available channels for selection"""
        channels = []
        for channel in interaction.guild.text_channels:
            channels.append(discord.SelectOption(
                label=f"#{channel.name}",
                value=str(channel.id),
                description=f"Category: {channel.category.name if channel.category else 'None'}"
            ))
        
        channels = channels[:25]  # Discord limit
        
        if not channels:
            channels.append(discord.SelectOption(label="No channels available", value="none"))
        
        self.children[0].options = channels
        
        embed = discord.Embed(
            title="Select Channel",
            description="Choose where to post the embed:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        await interaction.response.edit_message(embed=embed, view=self)

    async def show_channels(self, interaction):
        channels = []
        for channel in interaction.guild.channels:
            if isinstance(channel, discord.TextChannel):
                channels.append(discord.SelectOption(
                    label=f"#{channel.name}",
                    value=str(channel.id),
                    description=f"Category: {channel.category.name if channel.category else 'None'}"
                ))
        
        channels = channels[:25]  # Discord limit
        
        if not channels:
            channels.append(discord.SelectOption(label="No channels available", value="none"))
        
        self.children[0].options = channels
        
        embed = discord.Embed(
            title="Select Channel",
            description="Choose where to post the embed:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        await interaction.response.edit_message(embed=embed, view=self)

class SaveEmbedModal(discord.ui.Modal):
    def __init__(self, embed_view):
        super().__init__(title="Save Embed")
        self.embed_view = embed_view
        self.name_input = discord.ui.TextInput(
            label="Save Name",
            placeholder="Enter a name for this embed",
            required=True,
            max_length=50
        )
        self.save_type = discord.ui.TextInput(
            label="Save Type",
            placeholder="'preset' for reusable template or 'embed' for complete embed",
            default="embed",
            required=True,
            max_length=10
        )
        self.add_item(self.name_input)
        self.add_item(self.save_type)
    
    async def on_submit(self, interaction: discord.Interaction):
        save_name = self.name_input.value
        save_type = self.save_type.value.lower()
        
        if save_type not in ["preset", "embed"]:
            await interaction.response.send_message(
                "❌ Invalid save type! Please use 'preset' or 'embed'.",
                ephemeral=True
            )
            return
        
        try:
            # Get user ID for saving
            user_id = str(interaction.user.id)
            
            # Initialize user data if it doesn't exist
            if user_id not in user_data:
                user_data[user_id] = {"saved_embeds": {}, "saved_presets": {}}
            
            if save_type == "preset":
                # Save as preset (template without specific content)
                preset_data = {
                    "color": self.embed_view.embed_data.get("color"),
                    "footer": self.embed_view.embed_data.get("footer"),
                    "author": self.embed_view.embed_data.get("author"),
                    "thumbnail": self.embed_view.embed_data.get("thumbnail"),
                    "image": self.embed_view.embed_data.get("image"),
                    "timestamp": self.embed_view.embed_data.get("timestamp", False)
                }
                user_data[user_id]["saved_presets"][save_name] = preset_data
                
                await interaction.response.send_message(
                    f"✅ Successfully saved preset '{save_name}'! You can now apply this preset to new embeds.",
                    ephemeral=True
                )
                
            elif save_type == "embed":
                # Save complete embed with all data
                user_data[user_id]["saved_embeds"][save_name] = self.embed_view.embed_data.copy()
                
                await interaction.response.send_message(
                    f"✅ Successfully saved embed '{save_name}'! You can now load this complete embed anytime.",
                    ephemeral=True
                )
            
            # Optional: Save to file/database here if needed
            # save_user_data()
            
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Error saving {save_type}: {str(e)}",
                ephemeral=True
            )
    
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        try:
            await interaction.response.send_message(
                "❌ An error occurred while saving. Please try again.",
                ephemeral=True
            )
        except:
            # If response already sent, try to follow up
            await interaction.followup.send(
                "❌ An error occurred while saving. Please try again.",
                ephemeral=True
            )

async def handle_member_join_invite_tracking(member: discord.Member):
    """Handle invite tracking when a member joins"""
    try:
        # Get current invites
        current_invites = await member.guild.invites()
        cached_invites = invite_data.get("invites", {})
        
        # Find which invite was used
        used_invite = None
        inviter = None
        
        for invite in current_invites:
            cached_uses = cached_invites.get(invite.code, {}).get("uses", 0)
            if invite.uses > cached_uses:
                used_invite = invite
                inviter = invite.inviter
                break
        
        if used_invite and inviter:
            # Update invite data
            invite_data["invites"][used_invite.code]["uses"] = used_invite.uses
            
            # Update inviter's stats
            if "members" not in invite_data:
                invite_data["members"] = {}
                inviter_id = str(inviter.id)
            if inviter_id not in invite_data["members"]:
                invite_data["members"][inviter_id] = {
                "total_invites": 0,
                "left_invites": 0,
                "recent_invites": []
            }

            invite_data["members"][inviter_id]["total_invites"] += 1
            invite_data["members"][inviter_id]["recent_invites"].append({
            "member_id": member.id,
            "timestamp": int(time.time())
            })

            # Keep only last 10 recent invites
            if len(invite_data["members"][inviter_id]["recent_invites"]) > 10:
                invite_data["members"][inviter_id]["recent_invites"] = invite_data["members"][inviter_id]["recent_invites"][-10:]

            # Record who invited this member
            member_id = str(member.id)
            # Check if member already exists and has inviter data to avoid overwriting
            if member_id not in invite_data["members"]:
                invite_data["members"][member_id] = {}

            # Only add member data if they don't already have inviter stats
            if "total_invites" not in invite_data["members"][member_id]:
                invite_data["members"][member_id] = {
                    "invited_by": inviter.id,
                    "invite_code": used_invite.code,
                    "join_timestamp": int(time.time())
                }
            
            save_json("invite_data.json", invite_data)
            
            # Update inviter's roles
            await update_member_invite_roles(inviter)
            
            # Send welcome message
            welcome_channel_id = BOT_CONFIG.get("invite_welcome_channel_id")
            if welcome_channel_id:
                welcome_channel = bot.get_channel(welcome_channel_id)
                if welcome_channel:
                    embed = discord.Embed(
                        title="Welcome!",
                        description=f"{member.mention} joined using {inviter.mention}'s invite link!",
                        color=BOT_CONFIG["default_embed_color"]
                    )
                    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
                    
                    # Show inviter's new stats
                    total_invites = invite_data["members"][inviter_id]["total_invites"]
                    left_invites = invite_data["members"][inviter_id].get("left_invites", 0)
                    current_invites = total_invites - left_invites
                    
                    embed.add_field(
                        name="Inviter Stats",
                        value=f"{inviter.mention} now has {current_invites} active invites ({total_invites} total)",
                        inline=False
                    )
                    
                    await welcome_channel.send(embed=embed)
        
        # Cache new invite states
        for invite in current_invites:
            invite_data["invites"][invite.code] = {
                "uses": invite.uses or 0,
                "inviter_id": invite.inviter.id if invite.inviter else None,
                "channel_id": invite.channel.id if invite.channel else None,
                "created_at": invite.created_at.timestamp() if invite.created_at else None
            }
        
        save_json("invite_data.json", invite_data)
        
    except Exception as e:
        logger.error(f"Error handling invite tracking for {member}: {e}")

@bot.event
async def on_member_remove(member: discord.Member):
    """Handle member leaving for invite tracking"""
    if member.guild.id != GUILD_ID:
        return
    
    if BOT_CONFIG.get("invite_tracking_enabled", False):
        await handle_member_leave_invite_tracking(member)

async def handle_member_leave_invite_tracking(member: discord.Member):
    """Handle invite tracking when a member leaves"""
    try:
        member_id = str(member.id)
        member_data = invite_data.get("members", {}).get(member_id, {})
        
        # Find who invited this member
        inviter_id = member_data.get("invited_by")
        if inviter_id:
            inviter_id_str = str(inviter_id)
            if inviter_id_str in invite_data.get("members", {}):
                # Increment left_invites for the inviter
                invite_data["members"][inviter_id_str]["left_invites"] = invite_data["members"][inviter_id_str].get("left_invites", 0) + 1
                
                # Update inviter's roles
                inviter = member.guild.get_member(inviter_id)
                if inviter:
                    await update_member_invite_roles(inviter)
                
                save_json("invite_data.json", invite_data)
        
    except Exception as e:
        logger.error(f"Error handling invite tracking for leaving member {member}: {e}")

@bot.event
async def on_ready():
    """Bot startup tasks"""
    logger.info(f'Bot is ready! Logged in as {bot.user}')
    
    try:
        # Initialize database if available
        if DATABASE_AVAILABLE:
            try:
                await db_manager.initialize()
                structured_logger.logger.info("Database initialized successfully")
                await migrate_json_to_database()
            except Exception as e:
                logger.warning(f"Database initialization failed, using JSON fallback: {e}")
        
        # Start background tasks
        try:
            if not reset_daily.is_running():
                reset_daily.start()
        except:
            pass
            
        try:
            if not check_giveaways.is_running():
                check_giveaways.start()
        except:
            pass
            
        try:
            if not automated_backup.is_running():
                automated_backup.start()
        except:
            pass
            
        try:
            if not performance_monitoring.is_running():
                performance_monitoring.start()
        except:
            pass
        
        # Cache invites for tracking if enabled
        if BOT_CONFIG.get("invite_tracking_enabled", False):
            guild = bot.get_guild(GUILD_ID)
            if guild:
                try:
                    await cache_guild_invites(guild)
                except Exception as e:
                    logger.error(f"Failed to cache invites: {e}")
        
        # Sync commands
        try:
            synced = await tree.sync(guild=discord.Object(id=GUILD_ID))
            structured_logger.logger.info(f"Synced {len(synced)} command(s)")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
        
        performance_monitor.log_performance_metrics()
        
    except Exception as e:
        structured_logger.logger.error(f"Critical error during bot initialization: {e}")
        logger.error(f"Bot initialization error: {e}")
        # Don't raise here to prevent bot crash

class SaveEmbedModal(discord.ui.Modal):
    def __init__(self, embed_view):
        super().__init__(title="Save Embed")
        self.embed_view = embed_view

        self.name_input = discord.ui.TextInput(
            label="Save Name",
            placeholder="Enter a name for this embed",
            required=True,
            max_length=50
        )

        self.save_type = discord.ui.TextInput(
            label="Save Type",
            placeholder="'preset' for reusable template or 'embed' for complete embed",
            default="embed",
            required=True,
            max_length=10
        )

        self.add_item(self.name_input)
        self.add_item(self.save_type)

    async def on_submit(self, interaction: discord.Interaction):
        save_name = self.name_input.value
        save_type = self.save_type.value.lower()
        
        if save_type not in ["preset", "embed"]:
            await interaction.response.send_message("Save type must be 'preset' or 'embed'.", ephemeral=True)
            return
            
        embed_data = self.embed_view.embed_data.copy()
        embed_data["created_by"] = interaction.user.id
        embed_data["created_at"] = int(time.time())
        
        if save_type == "preset":
            embed_presets[save_name] = embed_data
            save_json("embed_presets.json", embed_presets)
            await interaction.response.send_message(f"✅ Embed preset '{save_name}' saved!", ephemeral=True)
        else:
            saved_embeds[save_name] = embed_data
            save_json("saved_embeds.json", saved_embeds)
            await interaction.response.send_message(f"✅ Embed '{save_name}' saved!", ephemeral=True)

class PresetSelectView(discord.ui.View):
    def __init__(self, embed_view, action):
        super().__init__(timeout=300)
        self.embed_view = embed_view
        self.action = action

    @discord.ui.select(placeholder="Select a preset/embed...")
    async def preset_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if select.values[0] == "none":
            await interaction.response.send_message("No presets available.", ephemeral=True)
            return
        
        preset_name = select.values[0]
        preset_data = None
        
        if preset_name in embed_presets:
            preset_data = embed_presets[preset_name]
        elif preset_name in saved_embeds:
            preset_data = saved_embeds[preset_name]
        
        if not preset_data:
            await interaction.response.send_message("Preset not found.", ephemeral=True)
            return
        
        if self.action == "load":
            self.embed_view.embed_data = preset_data.copy()
            await self.embed_view.update_display(interaction)
        elif self.action == "delete":
            if preset_name in embed_presets:
                del embed_presets[preset_name]
                save_json("embed_presets.json", embed_presets)
            elif preset_name in saved_embeds:
                del saved_embeds[preset_name]
                save_json("saved_embeds.json", saved_embeds)
            
            await interaction.response.send_message(f"✅ Deleted '{preset_name}'", ephemeral=True)

    async def show_presets(self, interaction):
        options = []
        
        for name in embed_presets.keys():
            options.append(discord.SelectOption(
                label=name,
                value=name,
                description="Preset",
                emoji="📋"
            ))
        
        for name in saved_embeds.keys():
            options.append(discord.SelectOption(
                label=name,
                value=name,
                description="Saved Embed",
                emoji="💾"
            ))
        
        options = options[:25]  # Discord limit
        
        if not options:
            options.append(discord.SelectOption(label="No presets available", value="none"))
        
        self.children[0].options = options
        
        action_text = "load" if self.action == "load" else "delete"
        embed = discord.Embed(
            title=f"Select Preset to {action_text.title()}",
            description=f"Choose a preset or saved embed to {action_text}:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        if hasattr(interaction, 'response') and not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

class EmbedManagementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📝 Create New Embed", style=discord.ButtonStyle.primary)
    async def create_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EmbedManagerView()
        await view.update_display(interaction)

    @discord.ui.button(label="📋 Manage Presets", style=discord.ButtonStyle.secondary)
    async def manage_presets(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PresetManagementView()
        await view.show_presets(interaction)

    @discord.ui.button(label="💾 Manage Saved Embeds", style=discord.ButtonStyle.secondary)
    async def manage_saved(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = SavedEmbedManagementView()
        await view.show_saved_embeds(interaction)

class PresetManagementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(placeholder="Select a preset to edit...")
    async def preset_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if select.values[0] == "none":
            await interaction.response.send_message("No presets available.", ephemeral=True)
            return
        
        preset_name = select.values[0]
        preset_data = embed_presets.get(preset_name)
        
        if not preset_data:
            await interaction.response.send_message("Preset not found.", ephemeral=True)
            return
        
        view = EmbedManagerView()
        view.embed_data = preset_data.copy()
        await view.update_display(interaction)

    @discord.ui.button(label="🗑️ Delete Preset", style=discord.ButtonStyle.red)
    async def delete_preset(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PresetSelectView(None, "delete")
        await view.show_presets(interaction)

    @discord.ui.button(label="← Back to Main", style=discord.ButtonStyle.secondary)
    async def back_to_main(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EmbedManagementView()
        embed = discord.Embed(
            title="Embed Management",
            description="Choose an option:",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_presets(self, interaction):
        options = []
        for name in embed_presets.keys():
            options.append(discord.SelectOption(label=name, value=name))
        
        if not options:
            options.append(discord.SelectOption(label="No presets available", value="none"))
        
        self.children[0].options = options[:25]
        
        embed = discord.Embed(
            title="Manage Embed Presets",
            description="Select a preset to edit or use the delete button:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        if hasattr(interaction, 'response') and not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

class SavedEmbedManagementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(placeholder="Select a saved embed...")
    async def saved_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if select.values[0] == "none":
            await interaction.response.send_message("No saved embeds available.", ephemeral=True)
            return
        
        embed_name = select.values[0]
        embed_data = saved_embeds.get(embed_name)
        
        if not embed_data:
            await interaction.response.send_message("Saved embed not found.", ephemeral=True)
            return
        
        view = EmbedManagerView()
        view.embed_data = embed_data.copy()
        await view.update_display(interaction)

    @discord.ui.button(label="🗑️ Delete Saved Embed", style=discord.ButtonStyle.red)
    async def delete_saved(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PresetSelectView(None, "delete")
        await view.show_presets(interaction)

    @discord.ui.button(label="← Back to Main", style=discord.ButtonStyle.secondary)
    async def back_to_main(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EmbedManagementView()
        embed = discord.Embed(
            title="Embed Management",
            description="Choose an option:",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_saved_embeds(self, interaction):
        options = []
        for name in saved_embeds.keys():
            options.append(discord.SelectOption(label=name, value=name))
        
        if not options:
            options.append(discord.SelectOption(label="No saved embeds available", value="none"))
        
        self.children[0].options = options[:25]
        
        embed = discord.Embed(
            title="Manage Saved Embeds",
            description="Select an embed to edit or use the delete button:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        if hasattr(interaction, 'response') and not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

@tree.command(name="embed", description="Comprehensive embed creation and management", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(action="Embed management action")
@app_commands.choices(action=[
    app_commands.Choice(name="Create New Embed", value="create"),
    app_commands.Choice(name="Manage Presets", value="presets"),
    app_commands.Choice(name="Manage Saved Embeds", value="saved"),
])
async def embed_command(interaction: discord.Interaction, action: app_commands.Choice[str]):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    if action.value == "create":
        view = EmbedManagerView()
        await view.update_display(interaction)
    elif action.value == "presets":
        view = PresetManagementView()
        await view.show_presets(interaction)
    elif action.value == "saved":
        view = SavedEmbedManagementView()
        await view.show_saved_embeds(interaction)

# --------- Auction Format Management System -----------

# Load auction formats (moved to after load_json function definition)
auction_formats = load_json("auction_formats.json")

class AuctionFormatManagementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    @discord.ui.select(
        placeholder="Select auction category to manage...",
        options=[
            discord.SelectOption(label="Regular Auctions", value="regular", description="Format for standard auctions"),
            discord.SelectOption(label="Premium Auctions", value="premium", description="Format for premium auctions"),
            discord.SelectOption(label="Item Trade Auctions", value="item_trade", description="Format for item trading auctions"),
        ]
    )
    async def category_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        category = select.values[0]
        view = AuctionFormatEditorView(category)
        await view.show_format_editor(interaction)

    @discord.ui.button(label="View Current Formats", style=discord.ButtonStyle.secondary)
    async def view_formats(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="Current Auction Formats",
            description="Overview of all auction format templates:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        categories = {
            "regular": "Regular Auctions",
            "premium": "Premium Auctions", 
            "item_trade": "Item Trade Auctions"
        }
        
        for category, name in categories.items():
            format_data = auction_formats.get(category, {})
            if format_data:
                embed.add_field(
                    name=name,
                    value=f"Last updated: <t:{format_data.get('last_updated', 0)}:R>\nBy: <@{format_data.get('updated_by', 'Unknown')}>",
                    inline=True
                )
            else:
                embed.add_field(
                    name=name,
                    value="Using default format",
                    inline=True
                )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

class AuctionFormatEditorView(discord.ui.View):
    def __init__(self, category):
        super().__init__(timeout=600)
        self.category = category
        self.category_names = {
            "regular": "Regular Auctions",
            "premium": "Premium Auctions",
            "item_trade": "Item Trade Auctions"
        }

    @discord.ui.button(label="Edit Format Template", style=discord.ButtonStyle.primary)
    async def edit_format(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AuctionFormatEditModal(self.category)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Preview Format", style=discord.ButtonStyle.secondary)
    async def preview_format(self, interaction: discord.Interaction, button: discord.ui.Button):
        format_data = auction_formats.get(self.category, {})
        template = format_data.get("template", self.get_default_template())
        
        # Create a preview with sample data
        preview_text = self.generate_preview(template)
        
        embed = discord.Embed(
            title=f"Format Preview - {self.category_names[self.category]}",
            description=f"```\n{preview_text}\n```",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        embed.add_field(
            name="Available Variables",
            value=self.get_available_variables(),
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Reset to Default", style=discord.ButtonStyle.red)
    async def reset_format(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.category in auction_formats:
            del auction_formats[self.category]
            save_json("auction_formats.json", auction_formats)
        
        embed = discord.Embed(
            title="✅ Format Reset",
            description=f"{self.category_names[self.category]} format has been reset to default",
            color=0x00FF00
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="← Back to Categories", style=discord.ButtonStyle.secondary)
    async def back_to_categories(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AuctionFormatManagementView()
        embed = discord.Embed(
            title="Auction Format Management",
            description="Select a category to manage its auction format:",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_format_editor(self, interaction):
        embed = discord.Embed(
            title=f"Format Editor - {self.category_names[self.category]}",
            description="Manage the auction format template for this category:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        format_data = auction_formats.get(self.category, {})
        if format_data:
            embed.add_field(
                name="Current Status",
                value=f"Custom format active\nLast updated: <t:{format_data.get('last_updated', 0)}:R>\nBy: <@{format_data.get('updated_by', 'Unknown')}>",
                inline=False
            )
        else:
            embed.add_field(
                name="Current Status", 
                value="Using default format",
                inline=False
            )
        
        embed.add_field(
            name="Available Actions",
            value="• **Edit Format Template** - Customize the auction layout\n• **Preview Format** - See how it looks with sample data\n• **Reset to Default** - Restore original format",
            inline=False
        )
        
        await interaction.response.edit_message(embed=embed, view=self)

    def get_default_template(self):
        if self.category == "regular":
            return """# {title}{server_text} <:cutesy_star:1364222257349525506>
ᯓ★ {rarity_type_line}
<:neonstars:1364582630363758685> ── .✦ Seller: {seller}

      ✶⋆.˚ Payment Methods:
                 {payment_methods}

╰┈➤ Starting: ${starting_bid}
╰┈➤ Increase: {increase}
╰┈➤ IA: {instant_accept}

{extra_info_section}{holds_section}     Ends: {end_timestamp}

{role_mentions}"""
        elif self.category == "premium":
            return """# {title}{server_text} ⭐ <:cutesy_star:1364222257349525506>
ᯓ★ {rarity_type_line}
<:neonstars:1364582630363758685> ── .✦ Seller: {seller}

      ✶⋆.˚ Payment Methods:
                 {payment_methods}

╰┈➤ Starting: ${starting_bid}
╰┈➤ Increase: {increase}
╰┈➤ IA: {instant_accept}

{extra_info_section}{holds_section}     Ends: {end_timestamp}

{role_mentions}"""
        elif self.category == "item_trade":
            return """# {title}{server_text} <:cutesy_star:1364222257349525506>
ᯓ★ {rarity_type_line}
<:neonstars:1364582630363758685> ── .✦ Seller: {seller}

{looking_for_section}{preferred_colors_section}╰┈➤ IA: {instant_accept}

@tree.command(name="embed", description="Comprehensive embed creation and management", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(action="Embed management action")
@app_commands.choices(action=[
    app_commands.Choice(name="Create New Embed", value="create"),
    app_commands.Choice(name="Manage Presets", value="presets"),
    app_commands.Choice(name="Manage Saved Embeds", value="saved"),
])
async def embed_command(interaction: discord.Interaction, action: app_commands.Choice[str]):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    if action.value == "create":
        view = EmbedManagerView()
        await view.update_display(interaction)
    elif action.value == "presets":
        view = PresetManagementView()
        await view.show_presets(interaction)
    elif action.value == "saved":
        view = SavedEmbedManagementView()
        await view.show_saved_embeds(interaction)

# --------- Missing Channel Selection View -----------

class ChannelSelectionView(discord.ui.View):
    def __init__(self, config_key, callback_view=None):
        super().__init__(timeout=300)
        self.config_key = config_key
        self.callback_view = callback_view

    @discord.ui.select(placeholder="Select a channel...")
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if select.values[0] == "none":
            await interaction.response.send_message("No channels available.", ephemeral=True)
            return
        
        channel_id = int(select.values[0])
        channel = bot.get_channel(channel_id)
        
        if not channel:
            await interaction.response.send_message("Channel not found.", ephemeral=True)
            return
        
        BOT_CONFIG[self.config_key] = channel_id
        save_json("bot_config.json", BOT_CONFIG)
        
        config_name = self.config_key.replace('_', ' ').title()
        embed = discord.Embed(
            title="✅ Channel Updated",
            description=f"{config_name} has been set to {channel.mention}",
            color=0x00FF00
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def show_channel_selection(self, interaction):
        channels = []
        for channel in interaction.guild.text_channels:
            channels.append(discord.SelectOption(
                label=f"#{channel.name}",
                value=str(channel.id),
                description=f"Category: {channel.category.name if channel.category else 'None'}"
            ))
        
        channels = channels[:25]  # Discord limit
        
        if not channels:
            channels.append(discord.SelectOption(label="No channels available", value="none"))
        
        self.children[0].options = channels
        
        embed = discord.Embed(
            title="Select Channel",
            description="Choose a channel:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        await interaction.response.edit_message(embed=embed, view=self)

# --------- Missing Configuration Views -----------

class ConfigurationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="Select configuration category...",
        options=[
            discord.SelectOption(label="Channels", value="channels", description="Configure channel settings"),
            discord.SelectOption(label="Roles", value="roles", description="Configure role settings"),
            discord.SelectOption(label="Boost Roles", value="boost_roles", description="Configure boost role system"),
            discord.SelectOption(label="Invite Tracking", value="invite_tracking", description="Configure invite tracking"),
            discord.SelectOption(label="General Settings", value="general", description="General bot settings"),
        ]
    )
    async def config_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        category = select.values[0]
        
        if category == "channels":
            view = ChannelConfigView()
            await view.show_channel_config(interaction)
        elif category == "roles":
            view = RoleConfigView()
            await view.show_role_config(interaction)
        elif category == "boost_roles":
            view = BoostRoleConfigView()
            await view.show_boost_config(interaction)
        elif category == "invite_tracking":
            view = InviteTrackingConfigView()
            await view.show_invite_config(interaction)
        elif category == "general":
            view = GeneralConfigView()
            await view.show_general_config(interaction)

class ChannelConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Set Tier Channel", style=discord.ButtonStyle.secondary)
    async def set_tier_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ChannelSelectionView("tier_channel_id", self)
        await view.show_channel_selection(interaction)

    @discord.ui.button(label="Set Levelup Channel", style=discord.ButtonStyle.secondary)
    async def set_levelup_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ChannelSelectionView("levelup_channel_id", self)
        await view.show_channel_selection(interaction)

    @discord.ui.button(label="← Back to Config", style=discord.ButtonStyle.secondary)
    async def back_to_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ConfigurationView()
        embed = discord.Embed(
            title="Bot Configuration",
            description="Select a category to configure:",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_channel_config(self, interaction):
        embed = discord.Embed(
            title="Channel Configuration",
            description="Configure bot channels:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        # Show current channel settings
        for key, name in [
            ("tier_channel_id", "Tier Channel"),
            ("auction_forum_channel_id", "Auction Forum"),
            ("premium_auction_forum_channel_id", "Premium Auction Forum"),
            ("levelup_channel_id", "Level Up Channel"),
            ("suggestions_channel_id", "Suggestions Channel"),
            ("reports_channel_id", "Reports Channel")
        ]:
            channel_id = BOT_CONFIG.get(key)
            if channel_id:
                channel = bot.get_channel(channel_id)
                channel_value = channel.mention if channel else f"Invalid ({channel_id})"
            else:
                channel_value = "Not set"
            embed.add_field(name=name, value=channel_value, inline=True)
        
        await interaction.response.edit_message(embed=embed, view=self)

class RoleConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Set Bidder Role", style=discord.ButtonStyle.secondary)
    async def set_bidder_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EnhancedRoleSelectionView("bidder_role_id", "Bidder Role", self)
        await view.show_role_selection(interaction)

    @discord.ui.button(label="Set Buyer Role", style=discord.ButtonStyle.secondary)
    async def set_buyer_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EnhancedRoleSelectionView("buyer_role_id", "Buyer Role", self)
        await view.show_role_selection(interaction)

    @discord.ui.button(label="← Back to Config", style=discord.ButtonStyle.secondary)
    async def back_to_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ConfigurationView()
        embed = discord.Embed(
            title="Bot Configuration",
            description="Select a category to configure:",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_role_config(self, interaction):
        embed = discord.Embed(
            title="Role Configuration",
            description="Configure bot roles:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        # Show current role settings
        for key, name in [
            ("bidder_role_id", "Bidder Role"),
            ("buyer_role_id", "Buyer Role")
        ]:
            role_id = BOT_CONFIG.get(key)
            if role_id:
                role = interaction.guild.get_role(role_id)
                role_value = role.mention if role else f"Invalid ({role_id})"
            else:
                role_value = "Not set"
            embed.add_field(name=name, value=role_value, inline=True)
        
        await interaction.response.edit_message(embed=embed, view=self)

class GeneralConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Set Currency Symbol", style=discord.ButtonStyle.secondary)
    async def set_currency_symbol(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CurrencySymbolModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="← Back to Config", style=discord.ButtonStyle.secondary)
    async def back_to_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ConfigurationView()
        embed = discord.Embed(
            title="Bot Configuration",
            description="Select a category to configure:",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_general_config(self, interaction):
        embed = discord.Embed(
            title="General Configuration",
            description="Configure general bot settings:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        embed.add_field(name="Currency Symbol", value=get_currency_symbol(), inline=True)
        embed.add_field(name="Default Embed Color", value=f"#{BOT_CONFIG['default_embed_color']:06x}", inline=True)
        
        await interaction.response.edit_message(embed=embed, view=self)

class CurrencySymbolModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Set Currency Symbol")
        self.symbol = discord.ui.TextInput(
            label="Currency Symbol",
            placeholder="Enter currency symbol (e.g., $, €, ¥)",
            default=get_currency_symbol(),
            required=True,
            max_length=5
        )
        self.add_item(self.symbol)
    
    async def on_submit(self, interaction: discord.Interaction):
        BOT_CONFIG["currency_symbol"] = self.symbol.value
        save_json("bot_config.json", BOT_CONFIG)
        
        embed = discord.Embed(
            title="✅ Currency Symbol Updated",
            description=f"Currency symbol has been set to: {self.symbol.value}",
            color=0x00FF00
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="config", description="Bot configuration panel", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def config_command(interaction: discord.Interaction):
    if not has_admin_permissions(interaction):
        await interaction.response.send_message("You need administrator permissions to access bot configuration.", ephemeral=True)
        return
    view = ConfigurationView()
    embed = discord.Embed(
        title="Bot Configuration",
        description="Select a category to configure:",
        color=BOT_CONFIG["default_embed_color"]
    )
    
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# --------- Missing Background Tasks -----------
@tasks.loop(hours=24)
async def reset_daily():
    """Reset daily statistics"""
    try:
        for user_id in member_stats:
            member_stats[user_id]["daily_messages"] = 0
        save_json("member_stats.json", member_stats)
        logger.info("Daily stats reset completed")
    except Exception as e:
        logger.error(f"Error resetting daily stats: {e}")

@tasks.loop(minutes=1)
async def check_giveaways():
    """Check for ending giveaways"""
    try:
        current_time = int(time.time())
        for giveaway_id, giveaway in giveaways_data.items():
            if (giveaway.get("status") == "active" and 
                giveaway.get("end_time") and 
                current_time >= giveaway["end_time"]):
                await end_giveaway(giveaway_id)
    except Exception as e:
        logger.error(f"Error checking giveaways: {e}")

@tasks.loop(hours=6)
async def automated_backup():
    """Create automated backup of data"""
    try:
        backup_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = f"backup_{backup_time}"
        os.makedirs(backup_dir, exist_ok=True)
        
        # Backup all JSON files
        json_files = [f for f in os.listdir('.') if f.endswith('.json')]
        for file_name in json_files:
            shutil.copy2(file_name, backup_dir)
        
        logger.info(f"Automated backup created: {backup_dir}")
    except Exception as e:
        logger.error(f"Error creating backup: {e}")

@tasks.loop(minutes=30)
async def performance_monitoring():
    """Monitor bot performance"""
    try:
        memory_usage = psutil.Process().memory_info().rss / 1024 / 1024  # MB
        cpu_usage = psutil.Process().cpu_percent()
        
        if memory_usage > 500:  # Alert if over 500MB
            logger.warning(f"High memory usage: {memory_usage:.2f}MB")
        
        if cpu_usage > 80:  # Alert if over 80% CPU
            logger.warning(f"High CPU usage: {cpu_usage:.2f}%")
            
    except Exception as e:
        logger.error(f"Error monitoring performance: {e}")

async def end_giveaway(giveaway_id):
    """End a giveaway and select winners"""
    try:
        giveaway = giveaways_data.get(giveaway_id)
        if not giveaway:
            return

        participants = list(giveaway.get("participants", {}).keys())
        if not participants:
            giveaway["status"] = "ended"
            giveaway["winners_list"] = []
            save_json("giveaways.json", giveaways_data)
            return

        # Select winners based on entry weights
        winners = []
        weighted_participants = []
        
        for user_id, data in giveaway["participants"].items():
            entries = data.get("entries", 1)
            for _ in range(entries):
                weighted_participants.append(user_id)
        
        winner_count = min(giveaway.get("winners", 1), len(set(participants)))
        
        for _ in range(winner_count):
            if weighted_participants:
                winner = random.choice(weighted_participants)
                if winner not in winners:
                    winners.append(winner)
                # Remove all entries for this winner
                weighted_participants = [p for p in weighted_participants if p != winner]

        giveaway["status"] = "ended"
        giveaway["winners_list"] = winners
        save_json("giveaways.json", giveaways_data)

        # Send results message
        guild = bot.get_guild(GUILD_ID)
        if guild:
            channel = guild.get_channel(giveaway["channel_id"])
            if channel:
                embed = discord.Embed(
                    title=f"🎉 {giveaway['name']} - Results!",
                    description=f"**Prizes:** {giveaway['prizes']}",
                    color=0x00FF00
                )
                
                if winners:
                    winner_mentions = [f"<@{winner}>" for winner in winners]
                    embed.add_field(
                        name="🏆 Winners",
                        value="\n".join(winner_mentions),
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="No Winners",
                        value="No participants in this giveaway",
                        inline=False
                    )
                
                embed.add_field(
                    name="Participants",
                    value=str(len(participants)),
                    inline=True
                )
                
                await channel.send(embed=embed)

    except Exception as e:
        logger.error(f"Error ending giveaway {giveaway_id}: {e}")

# --------- Missing Event Handlers -----------

@bot.event
async def on_message(message):
    """Handle message events for XP and verification"""
    if message.author.bot or message.guild is None or message.guild.id != GUILD_ID:
        return

    # Handle AFK system
    user_id = str(message.author.id)
    afk_users = server_settings.get("afk_users", {})
    if user_id in afk_users:
        del afk_users[user_id]
        server_settings["afk_users"] = afk_users
        save_json("server_settings.json", server_settings)
        
        try:
            embed = discord.Embed(
                title="Welcome Back!",
                description=f"{message.author.mention} is no longer AFK",
                color=BOT_CONFIG["default_embed_color"]
            )
            await message.channel.send(embed=embed, delete_after=5)
        except:
            pass

    # Check for AFK mentions
    for mention in message.mentions:
        mention_id = str(mention.id)
        if mention_id in afk_users:
            afk_data = afk_users[mention_id]
            reason = afk_data.get("reason", "AFK")
            timestamp = afk_data.get("timestamp", int(time.time()))
            
            try:
                embed = discord.Embed(
                    title="User is AFK",
                    description=f"{mention.mention} is currently AFK: {reason}",
                    color=BOT_CONFIG["default_embed_color"]
                )
                embed.set_footer(text=f"Since {datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')}")
                await message.channel.send(embed=embed, delete_after=10)
            except:
                pass

    # Handle verification system
    verification_enabled = verification_data.get("enabled", False)
    if verification_enabled:
        verification_word = verification_data.get("word", "").lower()
        verification_channel = verification_data.get("channel_id")
        
        if verification_word and verification_word in message.content.lower():
            if not verification_channel or message.channel.id == verification_channel:
                role_id = verification_data.get("role_id")
                if role_id:
                    role = message.guild.get_role(role_id)
                    if role and role not in message.author.roles:
                        try:
                            await message.author.add_roles(role, reason="Verification completed")
                            await message.add_reaction("✅")
                        except:
                            pass

                if verification_data.get("delete_messages", False):
                    try:
                        await message.delete()
                    except:
                        pass

    # XP system
    ensure_user_in_stats(user_id)
    current_time = int(time.time())
    last_xp_time = member_stats[user_id].get("last_xp_time", 0)
    
    # XP cooldown of 60 seconds
    if current_time - last_xp_time >= 60:
        xp_gain = random.randint(15, 25)
        member_stats[user_id]["xp"] += xp_gain
        member_stats[user_id]["last_xp_time"] = current_time
        
        # Update message counts
        member_stats[user_id]["daily_messages"] += 1
        member_stats[user_id]["weekly_messages"] += 1
        member_stats[user_id]["monthly_messages"] += 1
        member_stats[user_id]["all_time_messages"] += 1
        
        # Check for level up
        old_level = calculate_level(member_stats[user_id]["xp"] - xp_gain)
        new_level = calculate_level(member_stats[user_id]["xp"])
        
        if new_level > old_level:
            levelup_channel_id = BOT_CONFIG.get("levelup_channel_id")
            if levelup_channel_id:
                levelup_channel = bot.get_channel(levelup_channel_id)
                if levelup_channel:
                    try:
                        embed = discord.Embed(
                            title="Level Up! 🎉",
                            description=f"{message.author.mention} reached **Level {new_level}**!",
                            color=BOT_CONFIG["default_embed_color"]
                        )
                        embed.set_thumbnail(url=message.author.avatar.url if message.author.avatar else message.author.default_avatar.url)
                        await levelup_channel.send(embed=embed)
                    except:
                        pass

        save_json("member_stats.json", member_stats)

@bot.event
async def on_member_join(member: discord.Member):
    """Handle member join events"""
    if member.guild.id != GUILD_ID:
        return
    
    # Initialize user stats
    ensure_user_in_stats(str(member.id))
    
    # Handle invite tracking if enabled
    if BOT_CONFIG.get("invite_tracking_enabled", False):
        await handle_member_join_invite_tracking(member)

@bot.event
async def on_reaction_add(reaction, user):
    """Handle reaction role events"""
    if user.bot or reaction.message.guild is None or reaction.message.guild.id != GUILD_ID:
        return

    message_id = str(reaction.message.id)
    emoji_str = str(reaction.emoji)
    
    # Check reaction roles
    reaction_role_data = reaction_roles.get(message_id, {})
    if "roles" in reaction_role_data and emoji_str in reaction_role_data["roles"]:
        role_id = reaction_role_data["roles"][emoji_str]
        role = reaction.message.guild.get_role(role_id)
        
        if role:
            try:
                await user.add_roles(role, reason="Reaction role")
                
                # Give rewards if configured
                if "rewards" in reaction_role_data and emoji_str in reaction_role_data["rewards"]:
                    reward = reaction_role_data["rewards"][emoji_str]
                    user_id = str(user.id)
                    ensure_user_in_stats(user_id)
                    
                    # Give XP
                    if reward.get("xp", 0) > 0:
                        member_stats[user_id]["xp"] += reward["xp"]
                    
                    # Give currency
                    if reward.get("currency", 0) > 0:
                        user_balances[user_id] = user_balances.get(user_id, 0) + reward["currency"]
                    
                    save_json("member_stats.json", member_stats)
                    save_json("balances.json", user_balances)
                    
            except discord.Forbidden:
                pass

@bot.event
async def on_reaction_remove(reaction, user):
    """Handle reaction role removal"""
    if user.bot or reaction.message.guild is None or reaction.message.guild.id != GUILD_ID:
        return

    message_id = str(reaction.message.id)
    emoji_str = str(reaction.emoji)
    
    # Check reaction roles
    reaction_role_data = reaction_roles.get(message_id, {})
    if "roles" in reaction_role_data and emoji_str in reaction_role_data["roles"]:
        role_id = reaction_role_data["roles"][emoji_str]
        role = reaction.message.guild.get_role(role_id)
        
        if role and role in user.roles:
            try:
                await user.remove_roles(role, reason="Reaction role removed")
            except discord.Forbidden:
                pass

# --------- Start the bot -----------

@bot.event
async def on_error(event, *args, **kwargs):
    """Global error handler"""
    logger.error(f"Error in event {event}: {args}, {kwargs}")

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Handle application command errors"""
    logger.error(f"Application command error: {error}")
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message("An error occurred while processing your command.", ephemeral=True)
        else:
            await interaction.followup.send("An error occurred while processing your command.", ephemeral=True)
    except Exception:
        pass

if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        print(f"Bot failed to start: {e}")


{extra_info_section}{holds_section}{end_timestamp_section}{role_mentions}"""
        return "Default format not available"

    def generate_preview(self, template):
        # Sample data for preview
        sample_data = {
            "title": "Sample Item Name",
            "server_text": " (US)",
            "rarity_type_line": "S ‧ EXO", 
            "seller": "@SampleUser",
            "payment_methods": "PayPal ‧ Venmo ‧ Cash",
            "starting_bid": "5",
            "increase": "$1",
            "instant_accept": "$50",
            "extra_info_section": "༘⋆ Extra info: This is sample extra information\n",
            "holds_section": "𓂃 𓈒𓏸 Holds: Yes  ‧  7 Days\n\n",
            "end_timestamp": "<t:1234567890:R>",
            "role_mentions": "@Bidder @Buyer",
            "looking_for_section": "      ✶⋆.˚ Looking For:\n               Item 1 ‧ Item 2 ‧ Item 3\n",
            "preferred_colors_section": "      ✶⋆.˚ Preferred Colors:\n               Red ‧ Blue ‧ Green\n\n",
            "end_timestamp_section": "     Ends: <t:1234567890:R>\n\n"
        }
        
        try:
            return template.format(**sample_data)
        except KeyError as e:
            return f"Error in template: Missing variable {e}"

    def get_available_variables(self):
        if self.category in ["regular", "premium"]:
            return """**Basic Variables:**
`{title}` - Item name
`{server_text}` - Server location (e.g., " (US)")
`{rarity_type_line}` - Rarity and type (e.g., "S ‧ EXO")
`{seller}` - Seller mention
`{payment_methods}` - Payment methods
`{starting_bid}` - Starting bid amount
`{increase}` - Bid increase amount
`{instant_accept}` - IA amount
`{end_timestamp}` - End time

**Optional Sections:**
`{extra_info_section}` - Extra info (if provided)
`{holds_section}` - Holds info (if provided)
`{role_mentions}` - @Bidder @Buyer mentions"""
        elif self.category == "item_trade":
            return """**Basic Variables:**
`{title}` - Item name
`{server_text}` - Server location (e.g., " (US)")
`{rarity_type_line}` - Rarity and type (e.g., "S ‧ EXO")
`{seller}` - Seller mention
`{instant_accept}` - IA amount

**Optional Sections:**
`{looking_for_section}` - Looking for items
`{preferred_colors_section}` - Preferred colors
`{extra_info_section}` - Extra info (if provided)
`{holds_section}` - Holds info (if provided)
`{end_timestamp_section}` - End time (if provided)
`{role_mentions}` - @Bidder @Buyer mentions"""
        return "No variables available"

class AuctionFormatEditModal(discord.ui.Modal):
    def __init__(self, category):
        super().__init__(title=f"Edit {category.title()} Auction Format")
        self.category = category

        # Get current template or default
        current_format = auction_formats.get(category, {}).get("template", "")
        if not current_format:
            current_format = self.get_default_template()

        self.template_input = discord.ui.TextInput(
            label="Auction Format Template",
            placeholder="Use variables like {title}, {seller}, {starting_bid}...",
            default=current_format,
            required=True,
            max_length=4000,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.template_input)

    async def on_submit(self, interaction: discord.Interaction):
        template = self.template_input.value
        
        # Save the format
        if self.category not in auction_formats:
            auction_formats[self.category] = {}
        
        auction_formats[self.category] = {
            "template": template,
            "last_updated": int(time.time()),
            "updated_by": interaction.user.id
        }
        save_json("auction_formats.json", auction_formats)
        
        embed = discord.Embed(
            title="✅ Auction Format Updated",
            description=f"Format template for {self.category.replace('_', ' ').title()} auctions has been updated successfully.",
            color=0x00FF00
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    def get_default_template(self):
        if self.category == "regular":
            return """# {title}{server_text} <:cutesy_star:1364222257349525506>
ᯓ★ {rarity_type_line}
<:neonstars:1364582630363758685> ── .✦ Seller: {seller}

      ✶⋆.˚ Payment Methods:
                 {payment_methods}

╰┈➤ Starting: ${starting_bid}
╰┈➤ Increase: {increase}
╰┈➤ IA: {instant_accept}

{extra_info_section}{holds_section}     Ends: {end_timestamp}

{role_mentions}"""
        elif self.category == "premium":
            return """# {title}{server_text} ⭐ <:cutesy_star:1364222257349525506>
ᯓ★ {rarity_type_line}
<:neonstars:1364582630363758685> ── .✦ Seller: {seller}

      ✶⋆.˚ Payment Methods:
                 {payment_methods}

╰┈➤ Starting: ${starting_bid}
╰┈➤ Increase: {increase}
╰┈➤ IA: {instant_accept}

{extra_info_section}{holds_section}     Ends: {end_timestamp}

{role_mentions}"""
        elif self.category == "item_trade":
            return """# {title}{server_text} <:cutesy_star:1364222257349525506>
ᯓ★ {rarity_type_line}
<:neonstars:1364582630363758685> ── .✦ Seller: {seller}

{looking_for_section}{preferred_colors_section}╰┈➤ IA: {instant_accept}

{extra_info_section}{holds_section}{end_timestamp_section}{role_mentions}"""
        return ""

@tree.command(name="auctionformat", description="Manage auction format templates", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def auctionformat(interaction: discord.Interaction):
    if not has_admin_permissions(interaction):
        await interaction.response.send_message("You need administrator permissions to manage auction formats.", ephemeral=True)
        return

    view = AuctionFormatManagementView()
    embed = discord.Embed(
        title="Auction Format Management",
        description="Customize the layout and formatting of auction posts by category.\n\nSelect a category below to manage its format template:",
        color=BOT_CONFIG["default_embed_color"]
    )
    
    embed.add_field(
        name="📋 Categories Available",
        value="• **Regular Auctions** - Standard auction format\n• **Premium Auctions** - Premium auction format\n• **Item Trade Auctions** - Item trading format",
        inline=False
    )
    
    embed.add_field(
        name="⚙️ Features",
        value="• Custom templates with variables\n• Live preview functionality\n• Reset to default options\n• Version tracking",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# --------- Additional Commands and Features -----------

# --------- User Commands Implementation -----------

@tree.command(name="balance", description="Check your currency balance", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def balance(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_user_in_stats(uid)
    bal = user_balances.get(uid, 0)
    currency_symbol = get_currency_symbol()

    embed = discord.Embed(
        title=f"{interaction.user.display_name}'s Balance",
        description=f"{currency_symbol}{bal}",
        color=BOT_CONFIG["default_embed_color"]
    )
    embed.set_thumbnail(url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)

    await interaction.response.send_message(embed=embed)

@tree.command(name="inventory", description="View your inventory", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def inventory(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_user_in_stats(uid)
    inventory = user_inventories.get(uid, {})

    embed = discord.Embed(
        title=f"{interaction.user.display_name}'s Inventory",
        color=BOT_CONFIG["default_embed_color"]
    )

    if not inventory:
        embed.description = "Your inventory is empty!"
    else:
        items_text = []
        for item, quantity in inventory.items():
            items_text.append(f"**{item}**: {quantity}")
        embed.description = "\n".join(items_text)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="messages", description="View your message statistics", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def messages(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    ensure_user_in_stats(uid)
    stats = member_stats.get(uid, {})

    embed = discord.Embed(
        title=f"{interaction.user.display_name}'s Message Stats",
        color=BOT_CONFIG["default_embed_color"]
    )
    embed.add_field(name="Daily", value=stats.get("daily_messages", 0), inline=True)
    embed.add_field(name="Weekly", value=stats.get("weekly_messages", 0), inline=True)
    embed.add_field(name="Monthly", value=stats.get("monthly_messages", 0), inline=True)
    embed.add_field(name="All Time", value=stats.get("all_time_messages", 0), inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="suggest", description="Submit a suggestion to staff", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(suggestion="Your suggestion")
async def suggest(interaction: discord.Interaction, suggestion: str):
    if not BOT_CONFIG.get("suggestions_channel_id"):
        await interaction.response.send_message("Suggestions channel not configured.", ephemeral=True)
        return

    channel = bot.get_channel(BOT_CONFIG["suggestions_channel_id"])
    if not channel:
        await interaction.response.send_message("Suggestions channel not found.", ephemeral=True)
        return

    embed = discord.Embed(
        title="New Suggestion",
        description=suggestion,
        color=BOT_CONFIG["default_embed_color"]
    )
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
    embed.set_footer(text=f"User ID: {interaction.user.id}")

    await channel.send(embed=embed)
    await interaction.response.send_message("✅ Your suggestion has been submitted!", ephemeral=True)

@tree.command(name="report", description="Report an issue or user to staff", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(report="Your report")
async def report(interaction: discord.Interaction, report: str):
    if not BOT_CONFIG.get("reports_channel_id"):
        await interaction.response.send_message("Reports channel not configured.", ephemeral=True)
        return

    channel = bot.get_channel(BOT_CONFIG["reports_channel_id"])
    if not channel:
        await interaction.response.send_message("Reports channel not found.", ephemeral=True)
        return

    embed = discord.Embed(
        title="New Report",
        description=report,
        color=0xFF0000
    )
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
    embed.set_footer(text=f"User ID: {interaction.user.id}")

    await channel.send(embed=embed)
    await interaction.response.send_message("✅ Your report has been submitted!", ephemeral=True)

@tree.command(name="afk", description="Set yourself as AFK", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(reason="Reason for being AFK (optional)")
async def afk(interaction: discord.Interaction, reason: str = None):
    uid = str(interaction.user.id)
    afk_data = server_settings.get("afk_users", {})
    
    afk_data[uid] = {
        "reason": reason or "AFK",
        "timestamp": int(time.time())
    }
    
    if "afk_users" not in server_settings:
        server_settings["afk_users"] = {}
    server_settings["afk_users"] = afk_data
    save_json("server_settings.json", server_settings)

    embed = discord.Embed(
        title="AFK Set",
        description=f"You are now AFK: {reason or 'No reason provided'}",
        color=BOT_CONFIG["default_embed_color"]
    )
    await interaction.response.send_message(embed=embed)

@tree.command(name="giveaway_claim", description="Mark giveaway prizes as claimed", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(member="Member to mark prizes as claimed for (staff only)")
async def giveaway_claim(interaction: discord.Interaction, member: discord.Member = None):
    # If member is specified, check for staff permissions
    if member and member != interaction.user:
        if not has_staff_role(interaction):
            await interaction.response.send_message("You don't have permission to mark prizes as claimed for other members.", ephemeral=True)
            return
        target_user = member
        is_staff_action = True
    else:
        target_user = interaction.user
        is_staff_action = False

    user_id = str(target_user.id)
    claimed_any = False
    claimed_giveaways = []

    for giveaway_id, giveaway in giveaways_data.items():
        if (giveaway.get("status") == "ended" and 
            giveaway.get("winners_list") and 
            user_id in giveaway["winners_list"]):
            
            if not giveaway.get("claimed_winners"):
                giveaway["claimed_winners"] = []
            
            if user_id not in giveaway["claimed_winners"]:
                giveaway["claimed_winners"].append(user_id)
                claimed_any = True
                claimed_giveaways.append(giveaway["name"])

    if claimed_any:
        save_json("giveaways.json", giveaways_data)
        
        if is_staff_action:
            embed = discord.Embed(
                title="✅ Prizes Marked as Claimed",
                description=f"Marked {len(claimed_giveaways)} prize(s) as claimed for {target_user.mention}",
                color=0x00FF00
            )
            if claimed_giveaways:
                embed.add_field(name="Giveaways", value="\n".join(claimed_giveaways[:10]), inline=False)
            embed.set_footer(text=f"Action performed by {interaction.user.display_name}")
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("✅ Your prizes have been marked as claimed!", ephemeral=True)
    else:
        if is_staff_action:
            await interaction.response.send_message(f"No unclaimed prizes found for {target_user.mention}.", ephemeral=True)
        else:
            await interaction.response.send_message("No unclaimed prizes found.", ephemeral=True)

@tree.command(name="giveaway_unclaimed", description="View unclaimed giveaway prizes", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def giveaway_unclaimed(interaction: discord.Interaction):
    unclaimed_giveaways = []

    for giveaway_id, giveaway in giveaways_data.items():
        if giveaway.get("status") == "ended" and giveaway.get("winners_list"):
            claimed_winners = giveaway.get("claimed_winners", [])
            unclaimed_winners = [w for w in giveaway["winners_list"] if w not in claimed_winners]
            
            if unclaimed_winners:
                unclaimed_giveaways.append({
                    "name": giveaway["name"],
                    "unclaimed_count": len(unclaimed_winners)
                })

    embed = discord.Embed(
        title="Unclaimed Giveaway Prizes",
        color=BOT_CONFIG["default_embed_color"]
    )

    if not unclaimed_giveaways:
        embed.description = "No unclaimed prizes found!"
    else:
        description = []
        for giveaway in unclaimed_giveaways[:10]:
            description.append(f"**{giveaway['name']}**: {giveaway['unclaimed_count']} unclaimed")
        embed.description = "\n".join(description)

    await interaction.response.send_message(embed=embed)

@tree.command(name="level", description="Check level and XP", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(user="User to check (optional)")
async def level(interaction: discord.Interaction, user: discord.Member = None):
    target_user = user or interaction.user
    uid = str(target_user.id)
    ensure_user_in_stats(uid)

    data = member_stats.get(uid, {})
    level = calculate_level(data.get("xp", 0))
    xp = data.get("xp", 0)

    current_level_xp = calculate_xp_for_level(level)
    next_level_xp = calculate_xp_for_level(level + 1)

    if level == 0:
        progress = xp / next_level_xp
        current_progress = xp
        needed_for_next = next_level_xp
    else:
        progress = (xp - current_level_xp) / (next_level_xp - current_level_xp)
        current_progress = xp - current_level_xp
        needed_for_next = next_level_xp - current_level_xp

    bar_length = 10
    filled_length = int(bar_length * progress)
    bar = "█" * filled_length + "░" * (bar_length - filled_length)

    embed = discord.Embed(
        title=f"{target_user.display_name}'s Level",
        color=BOT_CONFIG["default_embed_color"]
    )
    embed.set_thumbnail(url=target_user.avatar.url if target_user.avatar else target_user.default_avatar.url)
    embed.add_field(name="Level", value=f"Level {level}", inline=True)
    embed.add_field(name="XP", value=str(xp), inline=True)
    embed.add_field(name="Progress", value=f"{bar} {current_progress}/{needed_for_next} XP", inline=False)

    await interaction.response.send_message(embed=embed)

@tree.command(name="viewslots", description="View premium auction slots", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(member="Member to view slots for (staff only)")
async def viewslots(interaction: discord.Interaction, member: discord.Member = None):
    # If member is specified, check for staff permissions
    if member and member != interaction.user:
        if not has_staff_role(interaction):
            await interaction.response.send_message("You don't have permission to view other members' slots.", ephemeral=True)
            return
        target_user = member
        is_staff_view = True
    else:
        target_user = interaction.user
        is_staff_view = False

    user_id = str(target_user.id)
    
    # Update slots based on current roles
    update_user_slots(target_user)
    
    user_slots = premium_slots.get(user_id, {"total_slots": 0, "used_slots": 0, "manual_slots": 0})

    embed = discord.Embed(
        title=f"{target_user.display_name}'s Premium Slots",
        color=BOT_CONFIG["default_embed_color"]
    )
    embed.set_thumbnail(url=target_user.avatar.url if target_user.avatar else target_user.default_avatar.url)

    total_slots = user_slots["total_slots"]
    used_slots = user_slots["used_slots"]
    available_slots = total_slots - used_slots
    manual_slots = user_slots.get("manual_slots", 0)

    embed.add_field(name="Total Slots", value=str(total_slots), inline=True)
    embed.add_field(name="Used Slots", value=str(used_slots), inline=True)
    embed.add_field(name="Available Slots", value=str(available_slots), inline=True)

    if is_staff_view:
        # Show detailed breakdown for staff
        role_slots = calculate_user_slots(target_user) - manual_slots
        
        embed.add_field(name="Role-Based Slots", value=str(role_slots), inline=True)
        embed.add_field(name="Manual Slots", value=str(manual_slots), inline=True)
        embed.add_field(name="Member ID", value=str(target_user.id), inline=True)
        
        # Show which roles grant slots
        slot_roles = []
        for role in target_user.roles:
            if role.id in BOT_CONFIG.get("auto_slot_roles", {}):
                slots = BOT_CONFIG["auto_slot_roles"][role.id]
                slot_roles.append(f"{role.mention}: {slots}")
            elif role.id in BOT_CONFIG.get("slot_roles", {}):
                slots = BOT_CONFIG["slot_roles"][role.id]["slots"]
                slot_roles.append(f"{role.mention}: {slots} (legacy)")
        
        if slot_roles:
            embed.add_field(
                name="Slot-Granting Roles",
                value="\n".join(slot_roles),
                inline=False
            )

    await interaction.response.send_message(embed=embed, ephemeral=is_staff_view)

# --------- Staff Commands Implementation -----------

@tree.command(name="addslots", description="Add manual premium auction slots to a member", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(member="Member to add slots to", amount="Number of manual slots to add")
async def addslots(interaction:discord.Interaction, member: discord.Member, amount: int):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    if amount <= 0:
        await interaction.response.send_message("Amount must be positive.", ephemeral=True)
        return

    user_id = str(member.id)
    
    # Update role-based slots first
    update_user_slots(member)
    
    if user_id not in premium_slots:
        premium_slots[user_id] = {"total_slots": 0, "used_slots": 0, "manual_slots": 0}

    # Add manual slots
    premium_slots[user_id]["manual_slots"] = premium_slots[user_id].get("manual_slots", 0) + amount
    premium_slots[user_id]["total_slots"] += amount
    save_json("premium_slots.json", premium_slots)

    embed = discord.Embed(
        title="✅ Manual Slots Added",
        description=f"Added {amount} manual premium auction slots to {member.mention}",
        color=0x00FF00
    )
    
    total_slots = premium_slots[user_id]["total_slots"]
    manual_slots = premium_slots[user_id]["manual_slots"]
    role_slots = total_slots - manual_slots
    
    embed.add_field(name="Total Slots", value=str(total_slots), inline=True)
    embed.add_field(name="Role Slots", value=str(role_slots), inline=True)
    embed.add_field(name="Manual Slots", value=str(manual_slots), inline=True)

    await interaction.response.send_message(embed=embed)

@tree.command(name="removeslots", description="Remove manual premium auction slots from a member", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(member="Member to remove slots from", amount="Number of manual slots to remove")
async def removeslots(interaction: discord.Interaction, member: discord.Member, amount: int):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    if amount <= 0:
        await interaction.response.send_message("Amount must be positive.", ephemeral=True)
        return

    user_id = str(member.id)
    
    # Update role-based slots first
    update_user_slots(member)
    
    if user_id not in premium_slots:
        premium_slots[user_id] = {"total_slots": 0, "used_slots": 0, "manual_slots": 0}

    current_manual = premium_slots[user_id].get("manual_slots", 0)
    remove_amount = min(amount, current_manual)
    
    if remove_amount == 0:
        await interaction.response.send_message(f"{member.mention} has no manual slots to remove.", ephemeral=True)
        return
    
    premium_slots[user_id]["manual_slots"] -= remove_amount
    premium_slots[user_id]["total_slots"] -= remove_amount
    
    # Ensure used slots don't exceed total
    if premium_slots[user_id]["used_slots"] > premium_slots[user_id]["total_slots"]:
        premium_slots[user_id]["used_slots"] = premium_slots[user_id]["total_slots"]
    
    save_json("premium_slots.json", premium_slots)

    embed = discord.Embed(
        title="✅ Manual Slots Removed",
        description=f"Removed {remove_amount} manual premium auction slots from {member.mention}",
        color=0x00FF00
    )
    
    total_slots = premium_slots[user_id]["total_slots"]
    manual_slots = premium_slots[user_id]["manual_slots"]
    role_slots = total_slots - manual_slots
    
    embed.add_field(name="Total Slots", value=str(total_slots), inline=True)
    embed.add_field(name="Role Slots", value=str(role_slots), inline=True)
    embed.add_field(name="Manual Slots", value=str(manual_slots), inline=True)

    await interaction.response.send_message(embed=embed)

@tree.command(name="balance_give", description="Give currency to a user", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(member="Member to give currency to", amount="Amount to give")
async def balance_give(interaction: discord.Interaction, member: discord.Member, amount: int):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    if amount <= 0:
        await interaction.response.send_message("Amount must be positive.", ephemeral=True)
        return

    user_id = str(member.id)
    ensure_user_in_stats(user_id)
    user_balances[user_id] = user_balances.get(user_id, 0) + amount
    save_json("balances.json", user_balances)

    currency_symbol = get_currency_symbol()
    await interaction.response.send_message(f"✅ Gave {currency_symbol}{amount} to {member.mention}. Their new balance is {currency_symbol}{user_balances[user_id]}.")

@tree.command(name="balance_remove", description="Remove currency from a user", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(member="Member to remove currency from", amount="Amount to remove")
async def balance_remove(interaction: discord.Interaction, member: discord.Member, amount: int):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    if amount <= 0:
        await interaction.response.send_message("Amount must be positive.", ephemeral=True)
        return

    user_id = str(member.id)
    ensure_user_in_stats(user_id)
    current_balance = user_balances.get(user_id, 0)
    new_balance = max(0, current_balance - amount)
    user_balances[user_id] = new_balance
    save_json("balances.json", user_balances)

    currency_symbol = get_currency_symbol()
    await interaction.response.send_message(f"✅ Removed {currency_symbol}{amount} from {member.mention}. Their new balance is {currency_symbol}{new_balance}.")

@tree.command(name="ban", description="Ban a member with logging", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(member="Member to ban", reason="Reason for ban")
async def ban_member(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    try:
        await member.ban(reason=f"Banned by {interaction.user}: {reason}")
        
        embed = discord.Embed(
            title="Member Banned",
            description=f"**Member:** {member.mention} ({member.id})\n**Reason:** {reason}\n**Staff:** {interaction.user.mention}",
            color=0xFF0000
        )
        
        await interaction.response.send_message(embed=embed)
        
        # Log to moderation channel if configured
        if logging_settings.get("moderation_channel_id"):
            log_channel = bot.get_channel(logging_settings["moderation_channel_id"])
            if log_channel:
                await log_channel.send(embed=embed)
                
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to ban this user.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Failed to ban user: {str(e)}", ephemeral=True)

@tree.command(name="kick", description="Kick a member", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(member="Member to kick", reason="Reason for kick")
async def kick_member(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    try:
        await member.kick(reason=f"Kicked by {interaction.user}: {reason}")
        
        embed = discord.Embed(
            title="Member Kicked",
            description=f"**Member:** {member.mention} ({member.id})\n**Reason:** {reason}\n**Staff:** {interaction.user.mention}",
            color=0xFFA500
        )
        
        await interaction.response.send_message(embed=embed)
        
        # Log to moderation channel if configured
        if logging_settings.get("moderation_channel_id"):
            log_channel = bot.get_channel(logging_settings["moderation_channel_id"])
            if log_channel:
                await log_channel.send(embed=embed)
                
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to kick this user.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Failed to kick user: {str(e)}", ephemeral=True)

@tree.command(name="warn", description="Issue a warning to a member", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(member="Member to warn", reason="Reason for warning")
async def warn_member(interaction: discord.Interaction, member: discord.Member, reason: str):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    user_id = str(member.id)
    warning_id = str(uuid.uuid4())
    
    if user_id not in member_warnings:
        member_warnings[user_id] = []
    
    warning = {
        "id": warning_id,
        "reason": reason,
        "staff_id": interaction.user.id,
        "timestamp": int(time.time())
    }
    
    member_warnings[user_id].append(warning)
    save_json("member_warnings.json", member_warnings)
    
    embed = discord.Embed(
        title="Warning Issued",
        description=f"**Member:** {member.mention}\n**Reason:** {reason}\n**Warning ID:** {warning_id}\n**Staff:** {interaction.user.mention}",
        color=0xFFFF00
    )
    
    await interaction.response.send_message(embed=embed)

@tree.command(name="warnings", description="View warnings for a member", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(member="Member to check warnings for")
async def view_warnings(interaction: discord.Interaction, member: discord.Member):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    user_id = str(member.id)
    warnings = member_warnings.get(user_id, [])
    
    embed = discord.Embed(
        title=f"Warnings for {member.display_name}",
        color=BOT_CONFIG["default_embed_color"]
    )
    
    if not warnings:
        embed.description = "No warnings found."
    else:
        warning_list = []
        for warning in warnings[-10:]:  # Show last 10 warnings
            staff = bot.get_user(warning["staff_id"])
            staff_name = staff.display_name if staff else "Unknown"
            warning_list.append(f"**ID:** {warning['id'][:8]}...\n**Reason:** {warning['reason']}\n**Staff:** {staff_name}\n**Date:** <t:{warning['timestamp']}:d>\n")
        
        embed.description = "\n".join(warning_list)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="purge", description="Delete multiple messages", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(amount="Number of messages to delete (1-100)")
async def purge_messages(interaction: discord.Interaction, amount: int):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    if amount < 1 or amount > 100:
        await interaction.response.send_message("Amount must be between 1 and 100.", ephemeral=True)
        return

    try:
        deleted = await interaction.channel.purge(limit=amount)
        embed = discord.Embed(
            title="Messages Purged",
            description=f"Deleted {len(deleted)} messages in {interaction.channel.mention}",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to delete messages.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Failed to purge messages: {str(e)}", ephemeral=True)

# --------- Auction Cancellation System -----------

class AuctionCancelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Add Cancellation", style=discord.ButtonStyle.red)
    async def add_cancellation(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AuctionCancelAddModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="View Cancellations", style=discord.ButtonStyle.secondary)
    async def view_cancellations(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AuctionCancelViewModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Configure Ban Rules", style=discord.ButtonStyle.primary)
    async def configure_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_admin_permissions(interaction):
            await interaction.response.send_message("You need administrator permissions to configure ban rules.", ephemeral=True)
            return
        
        view = CancellationConfigView()
        await view.show_config(interaction)

class AuctionCancelAddModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Add Auction Cancellation")

        self.member_id = discord.ui.TextInput(
            label="Member ID",
            placeholder="Enter the member's user ID",
            required=True,
            max_length=20
        )

        self.reason = discord.ui.TextInput(
            label="Reason for Cancellation",
            placeholder="Enter the reason for this cancellation",
            required=True,
            max_length=500,
            style=discord.TextStyle.paragraph
        )

        self.fair_unfair = discord.ui.TextInput(
            label="Fair or Unfair",
            placeholder="Enter 'fair' or 'unfair'",
            required=True,
            max_length=10
        )

        self.add_item(self.member_id)
        self.add_item(self.reason)
        self.add_item(self.fair_unfair)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            member_id = int(self.member_id.value)
            member = interaction.guild.get_member(member_id)
            
            if not member:
                await interaction.response.send_message("Member not found in this server.", ephemeral=True)
                return

            fair_unfair = self.fair_unfair.value.lower().strip()
            if fair_unfair not in ['fair', 'unfair']:
                await interaction.response.send_message("Please enter either 'fair' or 'unfair'.", ephemeral=True)
                return

            # Add cancellation
            cancellation_id = str(uuid.uuid4())
            user_id = str(member_id)
            
            if user_id not in auction_cancellations:
                auction_cancellations[user_id] = []
            
            cancellation = {
                "id": cancellation_id,
                "reason": self.reason.value,
                "type": fair_unfair,
                "staff_id": interaction.user.id,
                "timestamp": int(time.time())
            }
            
            auction_cancellations[user_id].append(cancellation)
            save_json("auction_cancellations.json", auction_cancellations)

            # Check for automatic ban
            ban_message = await check_auto_ban(member, interaction.guild)

            embed = discord.Embed(
                title="Auction Cancellation Added",
                description=f"**Member:** {member.mention}\n**Reason:** {self.reason.value}\n**Type:** {fair_unfair.title()}\n**ID:** {cancellation_id[:8]}...\n**Staff:** {interaction.user.mention}",
                color=0xFF0000 if fair_unfair == 'unfair' else 0xFFA500
            )

            if ban_message:
                embed.add_field(name="Auto-Ban Applied", value=ban_message, inline=False)

            await interaction.response.send_message(embed=embed)

        except ValueError:
            await interaction.response.send_message("Invalid member ID. Please enter numbers only.", ephemeral=True)

class AuctionCancelViewModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="View Auction Cancellations")

        self.member_id = discord.ui.TextInput(
            label="Member ID",
            placeholder="Enter the member's user ID",
            required=True,
            max_length=20
        )
        self.add_item(self.member_id)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            member_id = int(self.member_id.value)
            member = interaction.guild.get_member(member_id)
            
            if not member:
                await interaction.response.send_message("Member not found in this server.", ephemeral=True)
                return

            user_id = str(member_id)
            cancellations = auction_cancellations.get(user_id, [])

            embed = discord.Embed(
                title=f"Auction Cancellations for {member.display_name}",
                color=BOT_CONFIG["default_embed_color"]
            )
            embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)

            if not cancellations:
                embed.description = "No cancellations found."
            else:
                # Count totals
                total_cancellations = len(cancellations)
                fair_count = len([c for c in cancellations if c.get("type") == "fair"])
                unfair_count = len([c for c in cancellations if c.get("type") == "unfair"])

                embed.add_field(
                    name="📊 Summary",
                    value=f"**Total:** {total_cancellations}\n**Fair:** {fair_count}\n**Unfair:** {unfair_count}",
                    inline=True
                )

                # Show recent cancellations
                cancellation_list = []
                for cancellation in cancellations[-10:]:  # Show last 10
                    staff = bot.get_user(cancellation["staff_id"])
                    staff_name = staff.display_name if staff else "Unknown"
                    type_icon = "✅" if cancellation.get("type") == "fair" else "❌"
                    
                    cancellation_list.append(
                        f"{type_icon} **{cancellation.get('type', 'unknown').title()}**\n"
                        f"**Reason:** {cancellation['reason']}\n"
                        f"**Staff:** {staff_name}\n"
                        f"**Date:** <t:{cancellation['timestamp']}:d>\n"
                        f"**ID:** {cancellation['id'][:8]}...\n"
                    )

                if cancellation_list:
                    embed.add_field(
                        name="📋 Recent Cancellations",
                        value="\n".join(cancellation_list),
                        inline=False
                    )

            await interaction.response.send_message(embed=embed)

        except ValueError:
            await interaction.response.send_message("Invalid member ID. Please enter numbers only.", ephemeral=True)

class CancellationConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Add Ban Rule", style=discord.ButtonStyle.green)
    async def add_ban_rule(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = BanRuleModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Remove Ban Rule", style=discord.ButtonStyle.red)
    async def remove_ban_rule(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RemoveBanRuleModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="View Current Rules", style=discord.ButtonStyle.secondary)
    async def view_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.show_config(interaction)

    async def show_config(self, interaction):
        embed = discord.Embed(
            title="Cancellation Ban Configuration",
            description="Configure automatic ban rules for auction cancellations:",
            color=BOT_CONFIG["default_embed_color"]
        )

        rules = cancellation_config.get("ban_rules", [])
        if not rules:
            embed.add_field(name="Current Rules", value="No ban rules configured", inline=False)
        else:
            rule_list = []
            for i, rule in enumerate(rules):
                role = interaction.guild.get_role(rule["role_id"]) if rule.get("role_id") else None
                role_name = role.name if role else "All Users"
                count_type = rule.get("count_type", "total")
                rule_list.append(
                    f"**Rule {i+1}:** {role_name}\n"
                    f"Ban after {rule['threshold']} {count_type} cancellations\n"
                    f"Ban duration: {rule['ban_duration_hours']} hours\n"
                )
            embed.add_field(name="Current Rules", value="\n".join(rule_list), inline=False)

        if hasattr(interaction, 'response') and not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

class BanRuleModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Add Ban Rule")

        self.role_id = discord.ui.TextInput(
            label="Role ID (optional)",
            placeholder="Leave empty for all users, or enter role ID",
            required=False,
            max_length=20
        )

        self.threshold = discord.ui.TextInput(
            label="Cancellation Threshold",
            placeholder="Number of cancellations before ban",
            required=True,
            max_length=3
        )

        self.count_type = discord.ui.TextInput(
            label="Count Type",
            placeholder="total, fair, or unfair",
            required=True,
            max_length=10
        )

        self.ban_duration = discord.ui.TextInput(
            label="Ban Duration (hours)",
            placeholder="Duration in hours (0 for permanent)",
            required=True,
            max_length=5
        )

        self.add_item(self.role_id)
        self.add_item(self.threshold)
        self.add_item(self.count_type)
        self.add_item(self.ban_duration)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            threshold = int(self.threshold.value)
            ban_duration_hours = int(self.ban_duration.value)
            count_type = self.count_type.value.lower().strip()

            if count_type not in ['total', 'fair', 'unfair']:
                await interaction.response.send_message("Count type must be 'total', 'fair', or 'unfair'.", ephemeral=True)
                return

            if threshold <= 0:
                await interaction.response.send_message("Threshold must be positive.", ephemeral=True)
                return

            if ban_duration_hours < 0:
                await interaction.response.send_message("Ban duration cannot be negative.", ephemeral=True)
                return

            role_id = None
            if self.role_id.value.strip():
                role_id = int(self.role_id.value)
                role = interaction.guild.get_role(role_id)
                if not role:
                    await interaction.response.send_message("Role not found.", ephemeral=True)
                    return

            # Add rule
            if "ban_rules" not in cancellation_config:
                cancellation_config["ban_rules"] = []

            rule = {
                "role_id": role_id,
                "threshold": threshold,
                "count_type": count_type,
                "ban_duration_hours": ban_duration_hours
            }

            cancellation_config["ban_rules"].append(rule)
            save_json("cancellation_config.json", cancellation_config)

            role_name = interaction.guild.get_role(role_id).name if role_id else "All Users"
            duration_text = f"{ban_duration_hours} hours" if ban_duration_hours > 0 else "permanent"

            await interaction.response.send_message(
                f"✅ Ban rule added: {role_name} will be banned for {duration_text} after {threshold} {count_type} cancellations.",
                ephemeral=True
            )

        except ValueError:
            await interaction.response.send_message("Invalid input. Please check your values.", ephemeral=True)

class RemoveBanRuleModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Remove Ban Rule")

        self.rule_number = discord.ui.TextInput(
            label="Rule Number",
            placeholder="Enter rule number to remove (1, 2, 3, etc.)",
            required=True,
            max_length=3
        )
        self.add_item(self.rule_number)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            rule_num = int(self.rule_number.value)
            rules = cancellation_config.get("ban_rules", [])

            if rule_num < 1 or rule_num > len(rules):
                await interaction.response.send_message("Invalid rule number.", ephemeral=True)
                return

            removed_rule = rules.pop(rule_num - 1)
            cancellation_config["ban_rules"] = rules
            save_json("cancellation_config.json", cancellation_config)

            await interaction.response.send_message(f"✅ Removed ban rule {rule_num}.", ephemeral=True)

        except ValueError:
            await interaction.response.send_message("Invalid rule number.", ephemeral=True)

async def check_auto_ban(member: discord.Member, guild: discord.Guild):
    """Check if member should be automatically banned based on cancellation rules"""
    user_id = str(member.id)
    cancellations = auction_cancellations.get(user_id, [])
    
    if not cancellations:
        return None

    rules = cancellation_config.get("ban_rules", [])
    if not rules:
        return None

    # Calculate counts
    total_count = len(cancellations)
    fair_count = len([c for c in cancellations if c.get("type") == "fair"])
    unfair_count = len([c for c in cancellations if c.get("type") == "unfair"])

    counts = {
        "total": total_count,
        "fair": fair_count,
        "unfair": unfair_count
    }

    # Check each rule
    for rule in rules:
        # Check if rule applies to this user
        if rule.get("role_id"):
            role = guild.get_role(rule["role_id"])
            if not role or role not in member.roles:
                continue

        count_type = rule.get("count_type", "total")
        threshold = rule["threshold"]
        current_count = counts.get(count_type, 0)

        if current_count >= threshold:
            # Apply ban
            try:
                ban_duration_hours = rule["ban_duration_hours"]
                reason = f"Automatic ban: {current_count} {count_type} auction cancellations"

                if ban_duration_hours == 0:
                    # Permanent ban
                    await member.ban(reason=reason)
                    return f"Permanently banned for {current_count} {count_type} cancellations"
                else:
                    # Temporary ban - ban then schedule unban
                    await member.ban(reason=reason)
                    
                    # Schedule unban
                    async def unban_after_delay():
                        await asyncio.sleep(ban_duration_hours * 3600)
                        try:
                            await guild.unban(member.id, reason="Automatic unban - ban duration expired")
                        except:
                            pass
                    
                    asyncio.create_task(unban_after_delay())
                    return f"Temporarily banned for {ban_duration_hours} hours ({current_count} {count_type} cancellations)"

            except discord.Forbidden:
                return f"Failed to ban user - insufficient permissions"
            except Exception as e:
                return f"Failed to ban user - {str(e)}"

    return None

@tree.command(name="auctioncancel", description="Manage auction cancellations", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(
    action="Action to perform",
    member="Member for cancellation actions",
    reason="Reason for cancellation",
    fair_unfair="Whether the cancellation is fair or unfair"
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="Add Cancellation", value="add"),
        app_commands.Choice(name="View Cancellations", value="view"),
        app_commands.Choice(name="Configure Rules", value="config")
    ],
    fair_unfair=[
        app_commands.Choice(name="Fair", value="fair"),
        app_commands.Choice(name="Unfair", value="unfair")
    ]
)
async def auctioncancel(interaction: discord.Interaction, action: app_commands.Choice[str], member: discord.Member = None, reason: str = None, fair_unfair: app_commands.Choice[str] = None):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    if action.value == "add":
        if not member or not reason or not fair_unfair:
            await interaction.response.send_message("Member, reason, and fair/unfair are required for adding cancellations.", ephemeral=True)
            return

        # Add cancellation directly
        cancellation_id = str(uuid.uuid4())
        user_id = str(member.id)
        
        if user_id not in auction_cancellations:
            auction_cancellations[user_id] = []
        
        cancellation = {
            "id": cancellation_id,
            "reason": reason,
            "type": fair_unfair.value,
            "staff_id": interaction.user.id,
            "timestamp": int(time.time())
        }
        
        auction_cancellations[user_id].append(cancellation)
        save_json("auction_cancellations.json", auction_cancellations)

        # Check for automatic ban
        ban_message = await check_auto_ban(member, interaction.guild)

        embed = discord.Embed(
            title="Auction Cancellation Added",
            description=f"**Member:** {member.mention}\n**Reason:** {reason}\n**Type:** {fair_unfair.value.title()}\n**ID:** {cancellation_id[:8]}...\n**Staff:** {interaction.user.mention}",
            color=0xFF0000 if fair_unfair.value == 'unfair' else 0xFFA500
        )

        if ban_message:
            embed.add_field(name="Auto-Ban Applied", value=ban_message, inline=False)

        await interaction.response.send_message(embed=embed)

    elif action.value == "view":
        if not member:
            await interaction.response.send_message("Member is required for viewing cancellations.", ephemeral=True)
            return

        user_id = str(member.id)
        cancellations = auction_cancellations.get(user_id, [])

        embed = discord.Embed(
            title=f"Auction Cancellations for {member.display_name}",
            color=BOT_CONFIG["default_embed_color"]
        )
        embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)

        if not cancellations:
            embed.description = "No cancellations found."
        else:
            # Count totals
            total_cancellations = len(cancellations)
            fair_count = len([c for c in cancellations if c.get("type") == "fair"])
            unfair_count = len([c for c in cancellations if c.get("type") == "unfair"])

            embed.add_field(
                name="📊 Summary",
                value=f"**Total:** {total_cancellations}\n**Fair:** {fair_count}\n**Unfair:** {unfair_count}",
                inline=True
            )

            # Show recent cancellations
            cancellation_list = []
            for cancellation in cancellations[-10:]:  # Show last 10
                staff = bot.get_user(cancellation["staff_id"])
                staff_name = staff.display_name if staff else "Unknown"
                type_icon = "✅" if cancellation.get("type") == "fair" else "❌"
                
                cancellation_list.append(
                    f"{type_icon} **{cancellation.get('type', 'unknown').title()}**\n"
                    f"**Reason:** {cancellation['reason']}\n"
                    f"**Staff:** {staff_name}\n"
                    f"**Date:** <t:{cancellation['timestamp']}:d>\n"
                    f"**ID:** {cancellation['id'][:8]}...\n"
                )

            if cancellation_list:
                embed.add_field(
                    name="📋 Recent Cancellations",
                    value="\n".join(cancellation_list),
                    inline=False
                )

        await interaction.response.send_message(embed=embed)

    elif action.value == "config":
        if not has_admin_permissions(interaction):
            await interaction.response.send_message("You need administrator permissions to configure ban rules.", ephemeral=True)
            return
        
        view = CancellationConfigView()
        await view.show_config(interaction)

# Background tasks and event handlers
@tasks.loop(hours=24)
async def reset_daily():
    for uid in member_stats:
        member_stats[uid]["daily_messages"] = 0
    save_json("member_stats.json", member_stats)

@tasks.loop(minutes=1)
async def check_giveaways():
    current_time = int(time.time())

    for giveaway_id, giveaway in list(giveaways_data.items()):
        if giveaway["status"] == "active" and current_time >= giveaway["end_time"]:
            guild = bot.get_guild(GUILD_ID)
            if guild:
                await end_giveaway(giveaway_id, guild)

async def end_giveaway(giveaway_id: str, guild: discord.Guild):
    giveaway = giveaways_data.get(giveaway_id)
    if not giveaway or giveaway["status"] != "active":
        return

    # Mark as ended immediately to prevent duplicate endings
    giveaway["status"] = "ended"
    save_json("giveaways.json", giveaways_data)

    channel = guild.get_channel(giveaway["channel_id"])
    if not channel:
        return

    # Handle no participants
    if not giveaway["participants"]:
        embed = discord.Embed(
            title="🎉 Giveaway Ended",
            description=f"**{giveaway['name']}**\n\nNo participants joined this giveaway!",
            color=0xFF0000
        )
        await channel.send(embed=embed)
        return

    # Select winners
    weighted_participants = []
    for user_id, data in giveaway["participants"].items():
        weighted_participants.extend([user_id] * data["entries"])

    winner_count = min(giveaway["winners"], len(giveaway["participants"]))
    winners = random.sample(weighted_participants, winner_count)

    # Remove duplicates
    unique_winners = []
    seen = set()
    for winner in winners:
        if winner not in seen:
            unique_winners.append(winner)
            seen.add(winner)

    giveaway["winners_list"] = unique_winners

    # Create winner announcement
    host = guild.get_member(giveaway["host_id"])
    embed = discord.Embed(
        title="🎉 Giveaway Ended!",
        description=f"**{giveaway['name']}**\n\n**Prizes:** {giveaway['prizes']}",
        color=0x00FF00
    )

    winner_mentions = [f"<@{winner_id}>" for winner_id in unique_winners]
    embed.add_field(name="Winners", value="\n".join(winner_mentions), inline=False)

    if host:
        embed.add_field(name="Host", value=host.mention, inline=True)

    winner_pings = " ".join(winner_mentions)
    if host:
        winner_pings += f" {host.mention}"

    await channel.send(content=winner_pings, embed=embed)
    save_json("giveaways.json", giveaways_data)

@tasks.loop(hours=6)
async def automated_backup():
    """Create automated backups every 6 hours"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = f"backups/backup_{timestamp}"
        os.makedirs(backup_dir, exist_ok=True)

        # Backup database
        import shutil
        shutil.copy2("bot_database.db", f"{backup_dir}/bot_database.db")

        # Backup remaining JSON files
        data_files = [
            "reaction_roles.json", "sticky_messages.json", "server_settings.json", 
            "verification.json", "logging_settings.json", "autoresponders.json", 
            "profile_presets.json", "auction_cancellations.json", "cancellation_config.json",
            "embed_presets.json", "saved_embeds.json", "auction_formats.json"
        ]

        for file in data_files:
            if os.path.exists(file):
                shutil.copy2(file, backup_dir)

        structured_logger.logger.info(f"Backup created: {backup_dir}")
        await db_manager.log_action("backup_created", None, f"Backup created at {backup_dir}")
        
    except Exception as e:
        structured_logger.logger.error(f"Backup failed: {e}")

@tasks.loop(minutes=15)
async def performance_monitoring():
    """Monitor bot performance every 15 minutes"""
    try:
        performance_monitor.log_performance_metrics()
    except Exception as e:
        structured_logger.logger.error(f"Performance monitoring failed: {e}")

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot or reaction.message.guild.id != GUILD_ID:
        return

    message_id = str(reaction.message.id)
    if message_id not in reaction_roles:
        return

    reaction_data = reaction_roles[message_id]
    emoji_str = str(reaction.emoji)

    # Handle role assignment
    if emoji_str in reaction_data.get("roles", {}):
        role_id = reaction_data["roles"][emoji_str]
        role = reaction.message.guild.get_role(role_id)
        if role and role not in user.roles:
            try:
                await user.add_roles(role)
            except:
                pass

    # Handle rewards
    if emoji_str in reaction_data.get("rewards", {}):
        reward = reaction_data["rewards"][emoji_str]
        user_id = str(user.id)
        ensure_user_in_stats(user_id)
        
        member_stats[user_id]["xp"] += reward.get("xp", 0)
        user_balances[user_id] = user_balances.get(user_id, 0) + reward.get("currency", 0)
        save_all()

@bot.event
async def on_reaction_remove(reaction, user):
    if user.bot or reaction.message.guild.id != GUILD_ID:
        return

    message_id = str(reaction.message.id)
    if message_id not in reaction_roles:
        return

    reaction_data = reaction_roles[message_id]
    emoji_str = str(reaction.emoji)

    # Handle role removal
    if emoji_str in reaction_data.get("roles", {}):
        role_id = reaction_data["roles"][emoji_str]
        role = reaction.message.guild.get_role(role_id)
        if role and role in user.roles:
            try:
                await user.remove_roles(role)
            except:
                pass

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    """Handle role changes to update premium slots automatically"""
    if before.guild.id != GUILD_ID:
        return
    
    # Check if roles changed
    before_roles = set(role.id for role in before.roles)
    after_roles = set(role.id for role in after.roles)
    
    if before_roles != after_roles:
        # Roles changed, update slot count
        update_user_slots(after)
    
    # Check for boost status changes
    if before.premium_since != after.premium_since:
        if after.premium_since:  # Started boosting
            await update_member_boost_roles(after)
        else:  # Stopped boosting
            # Remove all boost roles
            boost_roles_config = BOT_CONFIG.get("boost_roles", {})
            for role_id in boost_roles_config.values():
                role = after.guild.get_role(role_id)
                if role and role in after.roles:
                    try:
                        await after.remove_roles(role, reason="No longer boosting")
                    except:
                        pass

@bot.event
async def on_member_join(member: discord.Member):
    """Handle new members joining to set up initial slots"""
    if member.guild.id != GUILD_ID:
        return
    
    # Set up initial slot count based on roles
    update_user_slots(member)
    
    # Handle invite tracking
    if BOT_CONFIG.get("invite_tracking_enabled", False):
        await handle_member_join_invite_tracking(member)

@bot.event
async def on_message(message):
    if message.author.bot or message.guild is None or message.guild.id != GUILD_ID:
        return

    # Handle sticky messages
    channel_id = str(message.channel.id)
    if channel_id in sticky_messages:
        sticky_data = sticky_messages[channel_id]
        # If enough messages have been sent since last sticky, repost it
        try:
            last_msg = await message.channel.fetch_message(sticky_data["last_message_id"])
            # Count messages since last sticky
            messages_since = 0
            async for msg in message.channel.history(limit=10, after=last_msg):
                if not msg.author.bot:
                    messages_since += 1
            
            if messages_since >= 5:  # Repost sticky after 5 regular messages
                embed = discord.Embed(
                    title="📌 Sticky Message",
                    description=sticky_data["content"],
                    color=BOT_CONFIG["default_embed_color"]
                )
                new_sticky = await message.channel.send(embed=embed)
                
                # Delete old sticky
                try:
                    old_msg = await message.channel.fetch_message(sticky_data["message_id"])
                    await old_msg.delete()
                except:
                    pass
                
                # Update sticky data
                sticky_messages[channel_id]["message_id"] = new_sticky.id
                sticky_messages[channel_id]["last_message_id"] = new_sticky.id
                save_json("sticky_messages.json", sticky_messages)
        except:
            pass

    # Handle autoresponders
    message_content = message.content.lower()
    for trigger, data in autoresponders.items():
        if trigger in message_content:
            await message.channel.send(data["response"])
            break  # Only respond to first matching trigger

    # Check verification system
    if verification_data.get("enabled", False):
        verification_word = verification_data.get("word", "").lower()
        verification_role_id = verification_data.get("role_id")
        verification_channel_id = verification_data.get("channel_id")
        delete_messages = verification_data.get("delete_messages", False)
        
        # Check if verification should work in this channel
        if not verification_channel_id or message.channel.id == verification_channel_id:
            # Check if message contains verification word
            if verification_word and verification_word in message.content.lower():
                if verification_role_id:
                    role = message.guild.get_role(verification_role_id)
                    if role and role not in message.author.roles:
                        try:
                            await message.author.add_roles(role, reason="Verification system")
                            
                            # Send ephemeral-style response (delete after a few seconds)
                            embed = discord.Embed(
                                title="✅ Verification Successful",
                                description=f"{message.author.mention}, you are now verified!",
                                color=0x00FF00
                            )
                            verification_msg = await message.channel.send(embed=embed)
                            
                            # Delete both messages if setting is enabled
                            if delete_messages:
                                try:
                                    await message.delete()
                                    await verification_msg.delete(delay=3)  # Delete confirmation after 3 seconds
                                except discord.NotFound:
                                    pass  # Message already deleted
                                except discord.Forbidden:
                                    # If can't delete, just delete the confirmation after delay
                                    await verification_msg.delete(delay=5)
                            else:
                                # Just delete confirmation message after delay
                                await verification_msg.delete(delay=5)
                                
                        except discord.Forbidden:
                            error_embed = discord.Embed(
                                title="❌ Verification Failed",
                                description="I don't have permission to assign roles.",
                                color=0xFF0000
                            )
                            error_msg = await message.channel.send(embed=error_embed)
                            await error_msg.delete(delay=5)

    # Check AFK system
    uid = str(message.author.id)
    afk_users = server_settings.get("afk_users", {})
    if uid in afk_users:
        del afk_users[uid]
        server_settings["afk_users"] = afk_users
        save_json("server_settings.json", server_settings)
        
        embed = discord.Embed(
            title="Welcome Back!",
            description=f"{message.author.mention}, you are no longer AFK.",
            color=BOT_CONFIG["default_embed_color"]
        )
        await message.channel.send(embed=embed, delete_after=5)

    # Check mentions for AFK users
    for mention in message.mentions:
        mention_id = str(mention.id)
        if mention_id in afk_users:
            afk_info = afk_users[mention_id]
            embed = discord.Embed(
                title="User is AFK",
                description=f"{mention.display_name} is currently AFK: {afk_info['reason']}",
                color=BOT_CONFIG["default_embed_color"]
            )
            embed.set_footer(text=f"AFK since: {datetime.fromtimestamp(afk_info['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}")
            await message.channel.send(embed=embed, delete_after=10)

    # Track member stats
    ensure_user_in_stats(uid)

    # Check for level up
    old_level = calculate_level(member_stats[uid].get("xp", 0))

    member_stats[uid]["daily_messages"] += 1
    member_stats[uid]["weekly_messages"] += 1
    member_stats[uid]["monthly_messages"] += 1
    member_stats[uid]["all_time_messages"] += 1
    member_stats[uid]["xp"] += 5

    new_level = calculate_level(member_stats[uid]["xp"])

    # Send level up notification
    if new_level > old_level and BOT_CONFIG.get("levelup_channel_id"):
        levelup_channel = bot.get_channel(BOT_CONFIG["levelup_channel_id"])
        if levelup_channel:
            await levelup_channel.send(f"🎉 {message.author.mention} leveled up to Level {new_level}!")

    save_all()

# --------- Admin Commands Implementation -----------

class ConfigurationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="Select configuration category...",
        options=[
            discord.SelectOption(label="Channels", value="channels", description="Configure bot channels"),
            discord.SelectOption(label="Roles", value="roles", description="Configure bot roles"),
            discord.SelectOption(label="Colors", value="colors", description="Configure embed colors"),
            discord.SelectOption(label="Economy", value="economy", description="Configure economy settings"),
            discord.SelectOption(label="Premium Slots", value="slots", description="Configure automatic slot roles"),
            discord.SelectOption(label="Boost Roles", value="boost_roles", description="Configure server boost role rewards"),
            discord.SelectOption(label="Invite Tracking", value="invite_tracking", description="Configure invite tracking and roles"),
        ]
    )
    async def config_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        category = select.values[0]
        
        if category == "channels":
            view = ChannelConfigView()
            await view.show_channel_config(interaction)
        elif category == "roles":
            view = RoleConfigView()
            await view.show_role_config(interaction)
        elif category == "colors":
            view = ColorConfigView()
            await view.show_color_config(interaction)
        elif category == "economy":
            view = EconomyConfigView()
            await view.show_economy_config(interaction)
        elif category == "slots":
            view = SlotConfigView()
            await view.show_slot_config(interaction)
        elif category == "boost_roles":
            view = BoostRoleConfigView()
            await view.show_boost_config(interaction)
        elif category == "invite_tracking":
            view = InviteTrackingConfigView()
            await view.show_invite_config(interaction)

class ChannelConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="Select channel to configure...",
        options=[
            discord.SelectOption(label="Tier Channel", value="tier_channel_id", description="Channel for tier list posts"),
            discord.SelectOption(label="Auction Forum", value="auction_forum_channel_id", description="Forum for regular auctions"),
            discord.SelectOption(label="Premium Auction Forum", value="premium_auction_forum_channel_id", description="Forum for premium auctions"),
            discord.SelectOption(label="Item Auction Forum", value="item_auction_forum_channel_id", description="Forum for item trading auctions"),
            discord.SelectOption(label="Level Up Channel", value="levelup_channel_id", description="Channel for level up notifications"),
            discord.SelectOption(label="Suggestions Channel", value="suggestions_channel_id", description="Channel for user suggestions"),
            discord.SelectOption(label="Reports Channel", value="reports_channel_id", description="Channel for user reports"),
        ]
    )
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        config_key = select.values[0]
        view = ChannelSelectionView(config_key)
        await view.show_channel_selection(interaction)

    @discord.ui.button(label="← Back to Config", style=discord.ButtonStyle.secondary)
    async def back_to_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ConfigurationView()
        embed = discord.Embed(
            title="Bot Configuration",
            description="Select a category to configure:",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_channel_config(self, interaction):
        embed = discord.Embed(
            title="Channel Configuration",
            description="Current channel settings - Select a channel to configure:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        channels = {
            "Tier Channel": BOT_CONFIG.get("tier_channel_id"),
            "Auction Forum": BOT_CONFIG.get("auction_forum_channel_id"),
            "Premium Auction Forum": BOT_CONFIG.get("premium_auction_forum_channel_id"),
            "Item Auction Forum": BOT_CONFIG.get("item_auction_forum_channel_id"),
            "Level Up Channel": BOT_CONFIG.get("levelup_channel_id"),
            "Suggestions Channel": BOT_CONFIG.get("suggestions_channel_id"),
            "Reports Channel": BOT_CONFIG.get("reports_channel_id")
        }
        
        for name, channel_id in channels.items():
            if channel_id:
                channel = bot.get_channel(channel_id)
                value = channel.mention if channel else f"Invalid ({channel_id})"
            else:
                value = "Not set"
            embed.add_field(name=name, value=value, inline=True)
        
        await interaction.response.edit_message(embed=embed, view=self)

class ChannelSelectionView(discord.ui.View):
    def __init__(self, config_key, callback_view=None):
        super().__init__(timeout=300)
        self.config_key = config_key
        self.callback_view = callback_view
        self.current_page = 0
        self.channels_per_page = 25

    @discord.ui.select(placeholder="Select a channel...", min_values=1, max_values=1)
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if select.values[0] == "none":
            await interaction.response.send_message("No channels available.", ephemeral=True)
            return
            
        channel_id = int(select.values[0])
        BOT_CONFIG[self.config_key] = channel_id
        save_json("bot_config.json", BOT_CONFIG)
        
        channel = bot.get_channel(channel_id)
        config_name = self.config_key.replace('_', ' ').title()
        
        embed = discord.Embed(
            title="✅ Channel Updated",
            description=f"{config_name} has been set to {channel.mention}",
            color=0x00FF00
        )
        
        # Go back to appropriate config view
        if self.callback_view:
            await interaction.response.edit_message(embed=embed, view=self.callback_view)
            await asyncio.sleep(2)
            if hasattr(self.callback_view, 'show_boost_config'):
                await self.callback_view.show_boost_config(interaction)
            elif hasattr(self.callback_view, 'show_invite_config'):
                await self.callback_view.show_invite_config(interaction)
        else:
            view = ChannelConfigView()
            await interaction.response.edit_message(embed=embed, view=view)
            await asyncio.sleep(2)
            await view.show_channel_config(interaction)

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_channel_page(interaction)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="▶️ Next", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        all_channels = self.get_all_channels(interaction.guild)
        max_pages = (len(all_channels) + self.channels_per_page - 1) // self.channels_per_page
        
        if self.current_page < max_pages - 1:
            self.current_page += 1
            await self.update_channel_page(interaction)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="🆔 Enter Channel ID", style=discord.ButtonStyle.primary)
    async def enter_channel_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ChannelIDModal(self.config_key, self.callback_view)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="← Back", style=discord.ButtonStyle.secondary)
    async def back_to_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.callback_view:
            await interaction.response.edit_message(view=self.callback_view)
        else:
            view = ChannelConfigView()
            await view.show_channel_config(interaction)

    def get_all_channels(self, guild):
        channels = []
        for channel in guild.channels:
            if isinstance(channel, (discord.TextChannel, discord.ForumChannel, discord.VoiceChannel, discord.StageChannel)):
                channels.append(channel)
        
        # Add threads
        for channel in guild.channels:
            if isinstance(channel, discord.TextChannel):
                try:
                    for thread in channel.threads:
                        channels.append(thread)
                except:
                    pass
        
        return sorted(channels, key=lambda c: (c.category.name if hasattr(c, 'category') and c.category else 'zzz', c.name))

    async def update_channel_page(self, interaction):
        all_channels = self.get_all_channels(interaction.guild)
        
        start_idx = self.current_page * self.channels_per_page
        end_idx = min(start_idx + self.channels_per_page, len(all_channels))
        page_channels = all_channels[start_idx:end_idx]
        max_pages = (len(all_channels) + self.channels_per_page - 1) // self.channels_per_page
        
        options = []
        for channel in page_channels:
            channel_type = "Thread" if isinstance(channel, discord.Thread) else channel.type.name.title()
            category = channel.category.name if hasattr(channel, 'category') and channel.category else "No Category"
            
            options.append(discord.SelectOption(
                label=f"#{channel.name}"[:100],
                value=str(channel.id),
                description=f"{channel_type} in {category}"[:100]
            ))
        
        if not options:
            options.append(discord.SelectOption(label="No channels on this page", value="none"))
        
        self.children[0].options = options
        
        # Update navigation buttons
        self.children[1].disabled = self.current_page == 0
        self.children[2].disabled = self.current_page >= max_pages - 1
        
        config_name = self.config_key.replace('_', ' ').title()
        embed = discord.Embed(
            title=f"Select {config_name}",
            description=f"Page {self.current_page + 1} of {max_pages}\nShowing {start_idx + 1}-{end_idx} of {len(all_channels)} channels",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        await interaction.response.edit_message(embed=embed, view=self)

    async def show_channel_selection(self, interaction):
        await self.update_channel_page(interaction)

    async def show_channel_selection(self, interaction):
        # Get all channels in the guild including threads
        channels = []
        
        # Regular channels
        for channel in interaction.guild.channels:
            if isinstance(channel, (discord.TextChannel, discord.ForumChannel, discord.VoiceChannel, discord.StageChannel, discord.CategoryChannel)):
                channels.append(discord.SelectOption(
                    label=f"#{channel.name}" if not isinstance(channel, discord.CategoryChannel) else f"📁 {channel.name}",
                    value=str(channel.id),
                    description=f"{channel.type.name.title()} - {channel.category.name if hasattr(channel, 'category') and channel.category else 'No Category'}"
                ))
        
        # Add threads from text channels and forums
        for channel in interaction.guild.channels:
            if isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
                try:
                    threads = []
                    if isinstance(channel, discord.TextChannel):
                        # Get active threads
                        active_threads = await channel.active_threads()
                        threads.extend(active_threads.threads)
                        
                        # Get archived threads (limit to recent ones)
                        try:
                            archived_threads = channel.archived_threads(limit=10)
                            async for thread in archived_threads:
                                threads.append(thread)
                        except:
                            pass
                    elif isinstance(channel, discord.ForumChannel):
                        # Get forum threads
                        try:
                            active_threads = await channel.active_threads()
                            threads.extend(active_threads.threads)
                        except:
                            pass
                    
                    for thread in threads:
                        channels.append(discord.SelectOption(
                            label=f"🧵 {thread.name}",
                            value=str(thread.id),
                            description=f"Thread in #{channel.name}"
                        ))
                except Exception as e:
                    logger.warning(f"Could not fetch threads for {channel.name}: {e}")
        
        # Sort channels by type and name
        channels.sort(key=lambda x: (x.description or "", x.label))
        
        # Limit to 25 channels (Discord limit)
        channels = channels[:25]
        
        if not channels:
            embed = discord.Embed(
                title="No Channels Found",
                description="No suitable channels found in this server.",
                color=0xFF0000
            )
            await interaction.response.edit_message(embed=embed, view=self)
            return
        
        self.children[0].options = channels
        
        config_name = self.config_key.replace('_', ' ').title()
        embed = discord.Embed(
            title=f"Select {config_name}",
            description="Choose a channel from the dropdown below (includes threads and forums):",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        await interaction.response.edit_message(embed=embed, view=self)

class RoleConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="Select role setting to configure...",
        options=[
            discord.SelectOption(label="Staff Roles", value="staff_roles", description="Roles that can use staff commands"),
            discord.SelectOption(label="Bidder Role", value="bidder_role_id", description="Role for auction bidders"),
            discord.SelectOption(label="Buyer Role", value="buyer_role_id", description="Role for buyers"),
        ]
    )
    async def role_config_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        config_key = select.values[0]
        
        if config_key == "staff_roles":
            view = StaffRoleManagementView()
            await view.show_staff_roles(interaction)
        else:
            view = RoleSelectionView(config_key)
            await view.show_role_selection(interaction)

    @discord.ui.button(label="← Back to Config", style=discord.ButtonStyle.secondary)
    async def back_to_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ConfigurationView()
        embed = discord.Embed(
            title="Bot Configuration",
            description="Select a category to configure:",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_role_config(self, interaction):
        embed = discord.Embed(
            title="Role Configuration",
            description="Current role settings - Select a role setting to configure:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        # Staff roles
        staff_roles = []
        for role_id in BOT_CONFIG.get("staff_roles", []):
            role = interaction.guild.get_role(role_id)
            if role:
                staff_roles.append(role.mention)
        
        embed.add_field(
            name="Staff Roles",
            value="\n".join(staff_roles) if staff_roles else "None set",
            inline=False
        )
        
        # Bidder role
        bidder_role_id = BOT_CONFIG.get("bidder_role_id")
        if bidder_role_id:
            bidder_role = interaction.guild.get_role(bidder_role_id)
            bidder_value = bidder_role.mention if bidder_role else f"Invalid ({bidder_role_id})"
        else:
            bidder_value = "Not set"
        embed.add_field(name="Bidder Role", value=bidder_value, inline=True)
        
        # Buyer role
        buyer_role_id = BOT_CONFIG.get("buyer_role_id")
        if buyer_role_id:
            buyer_role = interaction.guild.get_role(buyer_role_id)
            buyer_value = buyer_role.mention if buyer_role else f"Invalid ({buyer_role_id})"
        else:
            buyer_value = "Not set"
        embed.add_field(name="Buyer Role", value=buyer_value, inline=True)
        
        await interaction.response.edit_message(embed=embed, view=self)

class StaffRoleManagementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(placeholder="Select a role to add as staff...", min_values=0, max_values=1)
    async def add_staff_role(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not select.values:
            return
        
        role_id = int(select.values[0])
        
        if "staff_roles" not in BOT_CONFIG:
            BOT_CONFIG["staff_roles"] = []
        
        if role_id not in BOT_CONFIG["staff_roles"]:
            BOT_CONFIG["staff_roles"].append(role_id)
            save_json("bot_config.json", BOT_CONFIG)
            
            role = interaction.guild.get_role(role_id)
            embed = discord.Embed(
                title="✅ Staff Role Added",
                description=f"{role.mention} has been added as a staff role",
                color=0x00FF00
            )
        else:
            embed = discord.Embed(
                title="⚠️ Role Already Added",
                description="This role is already a staff role",
                color=0xFFA500
            )
        
        await interaction.response.edit_message(embed=embed, view=self)
        await asyncio.sleep(2)
        await self.show_staff_roles(interaction)

    @discord.ui.select(placeholder="Select a staff role to remove...", row=1, min_values=0, max_values=1)
    async def remove_staff_role(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not select.values:
            return
        
        role_id = int(select.values[0])
        
        if role_id in BOT_CONFIG.get("staff_roles", []):
            BOT_CONFIG["staff_roles"].remove(role_id)
            save_json("bot_config.json", BOT_CONFIG)
            
            role = interaction.guild.get_role(role_id)
            embed = discord.Embed(
                title="✅ Staff Role Removed",
                description=f"{role.mention} has been removed from staff roles",
                color=0x00FF00
            )
        else:
            embed = discord.Embed(
                title="⚠️ Role Not Found",
                description="This role is not a staff role",
                color=0xFFA500
            )
        
        await interaction.response.edit_message(embed=embed, view=self)
        await asyncio.sleep(2)
        await self.show_staff_roles(interaction)

    @discord.ui.button(label="← Back to Roles", style=discord.ButtonStyle.secondary, row=2)
    async def back_to_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RoleConfigView()
        await view.show_role_config(interaction)

    async def show_staff_roles(self, interaction):
        # Ensure we have the latest role data
        try:
            await interaction.guild.chunk()
        except:
            pass
        
        # Get all roles for adding
        add_roles = []
        current_staff_roles = BOT_CONFIG.get("staff_roles", [])
        all_roles = sorted(interaction.guild.roles, key=lambda r: r.position, reverse=True)
        
        for role in all_roles:
            if role.id not in current_staff_roles and not role.is_bot_managed() and role != interaction.guild.default_role:
                color_info = f"#{role.color.value:06x}" if role.color.value != 0 else "No Color"
                add_roles.append(discord.SelectOption(
                    label=role.name[:100],
                    value=str(role.id),
                    description=f"Members: {len(role.members)} • Pos: {role.position} • {color_info}"[:100]
                ))
        
        add_roles = add_roles[:25]  # Discord limit
        
        # Get current staff roles for removing
        remove_roles = []
        for role_id in current_staff_roles:
            role = interaction.guild.get_role(role_id)
            if role:
                color_info = f"#{role.color.value:06x}" if role.color.value != 0 else "No Color"
                remove_roles.append(discord.SelectOption(
                    label=role.name[:100],
                    value=str(role.id),
                    description=f"Members: {len(role.members)} • Pos: {role.position} • {color_info}"[:100]
                ))
        
        # Update dropdowns
        if add_roles:
            self.children[0].options = add_roles
            self.children[0].placeholder = f"Select from {len(add_roles)} available roles..."
        else:
            self.children[0].options = [discord.SelectOption(label="No roles available", value="none")]
            self.children[0].placeholder = "No roles available to add"
        
        if remove_roles:
            self.children[1].options = remove_roles
            self.children[1].placeholder = f"Remove from {len(remove_roles)} staff roles..."
        else:
            self.children[1].options = [discord.SelectOption(label="No staff roles set", value="none")]
            self.children[1].placeholder = "No staff roles to remove"
        
        embed = discord.Embed(
            title="Staff Role Management",
            description=f"Add or remove staff roles from {len(all_roles)} total server roles:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        # Show current staff roles with more detail
        staff_roles = []
        for role_id in current_staff_roles:
            role = interaction.guild.get_role(role_id)
            if role:
                staff_roles.append(f"{role.mention} (Position: {role.position}, Members: {len(role.members)})")
        
        embed.add_field(
            name=f"Current Staff Roles ({len(current_staff_roles)})",
            value="\n".join(staff_roles) if staff_roles else "None set",
            inline=False
        )
        
        # Show role statistics
        embed.add_field(
            name="Server Role Statistics",
            value=f"Total Roles: {len(all_roles)}\nBot Managed: {len([r for r in all_roles if r.is_bot_managed()])}\nAvailable for Staff: {len(add_roles) + len(remove_roles)}",
            inline=True
        )
        
        if hasattr(interaction, 'response') and not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

class RoleSelectionView(discord.ui.View):
    def __init__(self, config_key):
        super().__init__(timeout=300)
        self.config_key = config_key

    @discord.ui.select(placeholder="Select a role...", min_values=1, max_values=1)
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if select.values[0] == "none":
            await interaction.response.send_message("No roles available.", ephemeral=True)
            return
            
        role_id = int(select.values[0])
        BOT_CONFIG[self.config_key] = role_id
        save_json("bot_config.json", BOT_CONFIG)
        
        role = interaction.guild.get_role(role_id)
        config_name = self.config_key.replace('_', ' ').title()
        
        embed = discord.Embed(
            title="✅ Role Updated",
            description=f"{config_name} has been set to {role.mention}",
            color=0x00FF00
        )
        
        # Go back to role config
        view = RoleConfigView()
        await interaction.response.edit_message(embed=embed, view=view)
        
        # Show updated config after a moment
        await asyncio.sleep(2)
        await view.show_role_config(interaction)

    @discord.ui.button(label="← Back to Roles", style=discord.ButtonStyle.secondary)
    async def back_to_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RoleConfigView()
        await view.show_role_config(interaction)

    async def show_role_selection(self, interaction):
        # Fetch all roles from the guild to ensure we have the latest data
        try:
            # Force fetch roles if needed
            await interaction.guild.chunk()
        except:
            pass
        
        # Get all roles in the guild
        roles = []
        all_roles = sorted(interaction.guild.roles, key=lambda r: r.position, reverse=True)
        
        for role in all_roles:
            if not role.is_bot_managed() and role != interaction.guild.default_role:
                # Show role with position info
                position_info = f"Pos: {role.position}"
                color_info = f"#{role.color.value:06x}" if role.color.value != 0 else "No Color"
                permissions_info = "Admin" if role.permissions.administrator else f"{len([p for p in role.permissions if p[1]])} perms"
                
                roles.append(discord.SelectOption(
                    label=role.name[:100],  # Discord label limit
                    value=str(role.id),
                    description=f"Members: {len(role.members)} • {position_info} • {color_info} • {permissions_info}"[:100]
                ))
        
        # Limit to 25 roles (Discord limit)
        roles = roles[:25]
        
        if not roles:
            embed = discord.Embed(
                title="No Roles Found",
                description="No suitable roles found in this server.",
                color=0xFF0000
            )
            await interaction.response.edit_message(embed=embed, view=self)
            return
        
        self.children[0].options = roles
        
        config_name = self.config_key.replace('_', ' ').title()
        embed = discord.Embed(
            title=f"Select {config_name}",
            description=f"Choose a role from the dropdown below:\nShowing {len(roles)} of {len(all_roles)-1} available roles",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        await interaction.response.edit_message(embed=embed, view=self)

class ColorConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Set Default Color", style=discord.ButtonStyle.primary)
    async def set_default_color(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ColorModal("default_embed_color", "Default Embed Color")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Set Tier Colors", style=discord.ButtonStyle.secondary)
    async def set_tier_colors(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = TierColorView()
        await view.show_tier_colors(interaction)

    @discord.ui.button(label="← Back to Config", style=discord.ButtonStyle.secondary)
    async def back_to_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ConfigurationView()
        embed = discord.Embed(
            title="Bot Configuration",
            description="Select a category to configure:",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_color_config(self, interaction):
        embed = discord.Embed(
            title="Color Configuration",
            description="Current color settings:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        embed.add_field(name="Default Color", value=f"#{BOT_CONFIG['default_embed_color']:06x}", inline=True)
        
        tier_colors = []
        for tier, color in BOT_CONFIG.get("tier_colors", {}).items():
            tier_colors.append(f"**{tier.upper()}**: #{color:06x}")
        
        embed.add_field(name="Tier Colors", value="\n".join(tier_colors), inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self)

class TierColorView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="Select tier to change color...",
        options=[
            discord.SelectOption(label="S Tier", value="s", emoji="🥇"),
            discord.SelectOption(label="A Tier", value="a", emoji="🥈"),
            discord.SelectOption(label="B Tier", value="b", emoji="🥉"),
            discord.SelectOption(label="C Tier", value="c", emoji="📘"),
            discord.SelectOption(label="D Tier", value="d", emoji="📗"),
        ]
    )
    async def tier_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        tier = select.values[0]
        modal = TierColorModal(tier)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="← Back to Colors", style=discord.ButtonStyle.secondary)
    async def back_to_colors(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ColorConfigView()
        await view.show_color_config(interaction)

    async def show_tier_colors(self, interaction):
        embed = discord.Embed(
            title="Tier Color Configuration",
            description="Select a tier to change its color:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        for tier in ["s", "a", "b", "c", "d"]:
            color = BOT_CONFIG.get("tier_colors", {}).get(tier, BOT_CONFIG["default_embed_color"])
            embed.add_field(
                name=f"{tier.upper()} Tier",
                value=f"#{color:06x}",
                inline=True
            )
        
        await interaction.response.edit_message(embed=embed, view=self)

class ColorModal(discord.ui.Modal):
    def __init__(self, config_key, title):
        super().__init__(title=f"Set {title}")
        self.config_key = config_key

        self.color_input = discord.ui.TextInput(
            label="Color (Hex)",
            placeholder="Enter hex color (e.g., #FF5733 or FF5733)",
            required=True,
            max_length=7
        )
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            hex_color = self.color_input.value.lstrip('#')
            color = int(hex_color, 16)
            
            BOT_CONFIG[self.config_key] = color
            save_json("bot_config.json", BOT_CONFIG)
            
            embed = discord.Embed(
                title="✅ Color Updated",
                description=f"Color has been set to #{color:06x}",
                color=color
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message("Invalid hex color format. Please use format like #FF5733 or FF5733", ephemeral=True)

class TierColorModal(discord.ui.Modal):
    def __init__(self, tier):
        super().__init__(title=f"Set {tier.upper()} Tier Color")
        self.tier = tier

        self.color_input = discord.ui.TextInput(
            label="Color (Hex)",
            placeholder="Enter hex color (e.g., #FF5733 or FF5733)",
            required=True,
            max_length=7
        )
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            hex_color = self.color_input.value.lstrip('#')
            color = int(hex_color, 16)
            
            if "tier_colors" not in BOT_CONFIG:
                BOT_CONFIG["tier_colors"] = {}
            
            BOT_CONFIG["tier_colors"][self.tier] = color
            save_json("bot_config.json", BOT_CONFIG)
            
            embed = discord.Embed(
                title="✅ Tier Color Updated",
                description=f"{self.tier.upper()} tier color has been set to #{color:06x}",
                color=color
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message("Invalid hex color format. Please use format like #FF5733 or FF5733", ephemeral=True)

class EconomyConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Set Currency Symbol", style=discord.ButtonStyle.primary)
    async def set_currency(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CurrencyModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Choose Server Emoji", style=discord.ButtonStyle.secondary)
    async def choose_emoji(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EmojiSelectionView()
        await view.show_emoji_selection(interaction)

    @discord.ui.button(label="← Back to Config", style=discord.ButtonStyle.secondary)
    async def back_to_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ConfigurationView()
        embed = discord.Embed(
            title="Bot Configuration",
            description="Select a category to configure:",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_economy_config(self, interaction):
        embed = discord.Embed(
            title="Economy Configuration",
            description="Current economy settings:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        current_symbol = BOT_CONFIG.get("currency_symbol", "$")
        embed.add_field(name="Currency Symbol", value=current_symbol, inline=True)
        
        # Show if it's a custom emoji
        if current_symbol.startswith('<:') or current_symbol.startswith('<a:'):
            embed.add_field(name="Type", value="Server Emoji", inline=True)
        else:
            embed.add_field(name="Type", value="Text/Unicode", inline=True)
        
        await interaction.response.edit_message(embed=embed, view=self)

class CurrencyModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Set Currency Symbol")

        self.currency_input = discord.ui.TextInput(
            label="Currency Symbol",
            placeholder="Enter symbol ($, €, ¥) or emoji (:emoji_name: or <:name:id>)",
            required=True,
            max_length=100
        )
        self.add_item(self.currency_input)

    async def on_submit(self, interaction: discord.Interaction):
        symbol = self.currency_input.value.strip()
        
        # Handle emoji names (convert :emoji_name: to actual emoji if possible)
        if symbol.startswith(':') and symbol.endswith(':') and len(symbol) > 2:
            emoji_name = symbol[1:-1]
            # Try to find the emoji in the server
            for emoji in interaction.guild.emojis:
                if emoji.name.lower() == emoji_name.lower():
                    symbol = str(emoji)
                    break
        
        BOT_CONFIG["currency_symbol"] = symbol
        save_json("bot_config.json", BOT_CONFIG)
        
        embed = discord.Embed(
            title="✅ Currency Symbol Updated",
            description=f"Currency symbol has been set to: {symbol}",
            color=0x00FF00
        )
        
        # Determine symbol type
        if symbol.startswith('<:') or symbol.startswith('<a:'):
            embed.add_field(name="Type", value="Server Emoji", inline=True)
        elif len(symbol) == 1 and ord(symbol) > 127:
            embed.add_field(name="Type", value="Unicode Emoji", inline=True)
        else:
            embed.add_field(name="Type", value="Text Symbol", inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="config", description="Configure bot settings", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def config(interaction: discord.Interaction):
    if not has_admin_permissions(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    view = ConfigurationView()
    embed = discord.Embed(
        title="Bot Configuration",
        description="Select a category to configure:",
        color=BOT_CONFIG["default_embed_color"]
    )
    
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@tree.command(name="debug_info", description="View bot performance metrics", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def debug_info(interaction: discord.Interaction):
    if not has_admin_permissions(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    # Get system info
    memory_usage = psutil.virtual_memory()
    cpu_usage = psutil.cpu_percent()
    
    embed = discord.Embed(
        title="Bot Debug Information",
        color=BOT_CONFIG["default_embed_color"]
    )
    
    embed.add_field(name="Bot Status", value="Online ✅", inline=True)
    embed.add_field(name="Latency", value=f"{round(bot.latency * 1000)}ms", inline=True)
    embed.add_field(name="Guild Count", value=str(len(bot.guilds)), inline=True)
    
    embed.add_field(name="Memory Usage", value=f"{memory_usage.percent}%", inline=True)
    embed.add_field(name="CPU Usage", value=f"{cpu_usage}%", inline=True)
    embed.add_field(name="Python Version", value=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}", inline=True)
    
    # Data counts
    embed.add_field(name="Users in Stats", value=str(len(member_stats)), inline=True)
    embed.add_field(name="Active Giveaways", value=str(len([g for g in giveaways_data.values() if g.get("status") == "active"])), inline=True)
    embed.add_field(name="Total Auctions", value=str(len(auction_data)), inline=True)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="sticky", description="Create or manage sticky messages", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(
    action="Sticky message action",
    message="Message content for creating sticky messages"
)
@app_commands.choices(action=[
    app_commands.Choice(name="Create", value="create"),
    app_commands.Choice(name="Remove", value="remove"),
    app_commands.Choice(name="List", value="list"),
])
async def sticky(interaction: discord.Interaction, action: app_commands.Choice[str], message: str = None):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    channel_id = str(interaction.channel.id)
    
    if action.value == "create":
        if not message:
            await interaction.response.send_message("Message content is required for creating sticky messages.", ephemeral=True)
            return
        
        # Send the sticky message
        embed = discord.Embed(
            title="📌 Sticky Message",
            description=message,
            color=BOT_CONFIG["default_embed_color"]
        )
        sticky_msg = await interaction.channel.send(embed=embed)
        
        # Store sticky message data
        sticky_messages[channel_id] = {
            "message_id": sticky_msg.id,
            "content": message,
            "last_message_id": sticky_msg.id
        }
        save_json("sticky_messages.json", sticky_messages)
        
        await interaction.response.send_message("✅ Sticky message created!", ephemeral=True)
    
    elif action.value == "remove":
        if channel_id in sticky_messages:
            try:
                # Try to delete the sticky message
                msg_id = sticky_messages[channel_id]["message_id"]
                msg = await interaction.channel.fetch_message(msg_id)
                await msg.delete()
            except:
                pass
            
            del sticky_messages[channel_id]
            save_json("sticky_messages.json", sticky_messages)
            await interaction.response.send_message("✅ Sticky message removed!", ephemeral=True)
        else:
            await interaction.response.send_message("No sticky message found in this channel.", ephemeral=True)
    
    elif action.value == "list":
        embed = discord.Embed(
            title="Sticky Messages",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        if not sticky_messages:
            embed.description = "No sticky messages found."
        else:
            sticky_list = []
            for ch_id, data in sticky_messages.items():
                channel = bot.get_channel(int(ch_id))
                channel_name = channel.mention if channel else f"Unknown ({ch_id})"
                sticky_list.append(f"{channel_name}: {data['content'][:50]}...")
            embed.description = "\n".join(sticky_list)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="autoresponder", description="Set up automatic responses", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(
    action="Autoresponder action",
    trigger="Trigger word/phrase",
    response="Response message"
)
@app_commands.choices(action=[
    app_commands.Choice(name="Add", value="add"),
    app_commands.Choice(name="Remove", value="remove"),
    app_commands.Choice(name="List", value="list"),
])
async def autoresponder(interaction: discord.Interaction, action: app_commands.Choice[str], trigger: str = None, response: str = None):
    if not has_staff_role(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    if action.value == "add":
        if not trigger or not response:
            await interaction.response.send_message("Both trigger and response are required.", ephemeral=True)
            return
        
        autoresponders[trigger.lower()] = {
            "response": response,
            "created_by": interaction.user.id,
            "created_at": int(time.time())
        }
        save_json("autoresponders.json", autoresponders)
        
        await interaction.response.send_message(f"✅ Autoresponder added for trigger: `{trigger}`", ephemeral=True)
    
    elif action.value == "remove":
        if not trigger:
            await interaction.response.send_message("Trigger is required for removal.", ephemeral=True)
            return
        
        if trigger.lower() in autoresponders:
            del autoresponders[trigger.lower()]
            save_json("autoresponders.json", autoresponders)
            await interaction.response.send_message(f"✅ Autoresponder removed for trigger: `{trigger}`", ephemeral=True)

class SlotConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Add Auto Slot Role", style=discord.ButtonStyle.green)
    async def add_slot_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AddSlotRoleModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Remove Auto Slot Role", style=discord.ButtonStyle.red)
    async def remove_slot_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RemoveSlotRoleView()
        await view.show_slot_roles(interaction)

    @discord.ui.button(label="Update All Members", style=discord.ButtonStyle.primary)
    async def update_all_members(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        updated_count = 0
        for member in interaction.guild.members:
            if not member.bot:
                update_user_slots(member)
                updated_count += 1
        
        embed = discord.Embed(
            title="✅ Slot Update Complete",
            description=f"Updated slot counts for {updated_count} members based on their current roles.",
            color=0x00FF00
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="← Back to Config", style=discord.ButtonStyle.secondary)
    async def back_to_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ConfigurationView()
        embed = discord.Embed(
            title="Bot Configuration",
            description="Select a category to configure:",
            color=BOT_CONFIG["default_embed_color"]
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_slot_config(self, interaction):
        embed = discord.Embed(
            title="Premium Slot Configuration",
            description="Configure which roles automatically grant premium auction slots:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        # Show existing slot roles
        slot_roles_info = []
        for role_id, slots in BOT_CONFIG.get("auto_slot_roles", {}).items():
            role = interaction.guild.get_role(role_id)
            role_name = role.mention if role else f"Deleted Role ({role_id})"
            slot_roles_info.append(f"{role_name}: {slots} slots")
        
        if slot_roles_info:
            embed.add_field(
                name="Automatic Slot Roles",
                value="\n".join(slot_roles_info),
                inline=False
            )
        else:
            embed.add_field(
                name="Automatic Slot Roles",
                value="No automatic slot roles configured",
                inline=False
            )
        
        # Show legacy slot roles (read-only)
        legacy_roles_info = []
        for role_id, role_data in BOT_CONFIG.get("slot_roles", {}).items():
            role = interaction.guild.get_role(role_id)
            role_name = role.mention if role else f"Deleted Role ({role_id})"
            legacy_roles_info.append(f"{role_name}: {role_data['slots']} slots ({role_data['name']})")
        
        if legacy_roles_info:
            embed.add_field(
                name="Legacy Slot Roles (Read-Only)",
                value="\n".join(legacy_roles_info),
                inline=False
            )
        
        embed.add_field(
            name="How It Works",
            value="• Members automatically get slots when they receive configured roles\n• Slot counts update when roles change\n• Manual slots are preserved when role slots change\n• Use 'Update All Members' to refresh everyone's slots",
            inline=False
        )
        
        await interaction.response.edit_message(embed=embed, view=self)

class AddSlotRoleModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Add Auto Slot Role")

        self.role_id = discord.ui.TextInput(
            label="Role ID",
            placeholder="Enter the role ID",
            required=True,
            max_length=20
        )

        self.slot_count = discord.ui.TextInput(
            label="Slot Count",
            placeholder="Number of slots this role grants",
            required=True,
            max_length=3
        )

        self.add_item(self.role_id)
        self.add_item(self.slot_count)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            role_id = int(self.role_id.value)
            slots = int(self.slot_count.value)
            
            if slots < 0:
                await interaction.response.send_message("Slot count must be 0 or higher.", ephemeral=True)
                return
            
            role = interaction.guild.get_role(role_id)
            if not role:
                await interaction.response.send_message("Role not found in this server.", ephemeral=True)
                return
            
            if "auto_slot_roles" not in BOT_CONFIG:
                BOT_CONFIG["auto_slot_roles"] = {}
            
            BOT_CONFIG["auto_slot_roles"][role_id] = slots
            save_json("bot_config.json", BOT_CONFIG)
            
            embed = discord.Embed(
                title="✅ Auto Slot Role Added",
                description=f"{role.mention} will now automatically grant {slots} premium auction slots to members.",
                color=0x00FF00
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message("Invalid role ID or slot count. Please enter numbers only.", ephemeral=True)

class RemoveSlotRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(placeholder="Select role to remove...")
    async def remove_role_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if select.values[0] == "none":
            await interaction.response.send_message("No roles available to remove.", ephemeral=True)
            return
        
        role_id = int(select.values[0])
        role = interaction.guild.get_role(role_id)
        
        # Remove from config
        if role_id in BOT_CONFIG.get("auto_slot_roles", {}):
            del BOT_CONFIG["auto_slot_roles"][role_id]
            save_json("bot_config.json", BOT_CONFIG)
            
            role_name = role.mention if role else f"Role ({role_id})"
            embed = discord.Embed(
                title="✅ Auto Slot Role Removed",
                description=f"{role_name} will no longer automatically grant slots to members.",
                color=0x00FF00
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("Role not found in auto slot configuration.", ephemeral=True)

    @discord.ui.button(label="← Back to Slot Config", style=discord.ButtonStyle.secondary)
    async def back_to_slots(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = SlotConfigView()
        await view.show_slot_config(interaction)

    async def show_slot_roles(self, interaction):
        options = []
        for role_id, slots in BOT_CONFIG.get("auto_slot_roles", {}).items():
            role = interaction.guild.get_role(role_id)
            if role:
                options.append(discord.SelectOption(
                    label=role.name,
                    value=str(role_id),
                    description=f"Grants {slots} slots"
                ))
        
        if not options:
            options.append(discord.SelectOption(label="No auto slot roles configured", value="none"))
        
        self.children[0].options = options[:25]
        
        embed = discord.Embed(
            title="Remove Auto Slot Role",
            description="Select a role to remove from automatic slot allocation:",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        await interaction.response.edit_message(embed=embed, view=self)

class EmojiSelectionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.current_page = 0
        self.emojis_per_page = 25

    @discord.ui.select(placeholder="Select an emoji for currency...")
    async def emoji_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        emoji_value = select.values[0]
        
        if emoji_value == "none":
            await interaction.response.send_message("No emojis available.", ephemeral=True)
            return
        
        # Set the currency symbol
        BOT_CONFIG["currency_symbol"] = emoji_value
        save_json("bot_config.json", BOT_CONFIG)
        
        embed = discord.Embed(
            title="✅ Currency Symbol Updated",
            description=f"Currency symbol has been set to: {emoji_value}",
            color=0x00FF00
        )
        
        # Go back to economy config
        view = EconomyConfigView()
        await interaction.response.edit_message(embed=embed, view=view)
        
        # Show updated config after a moment
        await asyncio.sleep(2)
        await view.show_economy_config(interaction)

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_emoji_page(interaction)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="▶️ Next", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_emojis = list(interaction.guild.emojis)
        max_pages = (len(guild_emojis) + self.emojis_per_page - 1) // self.emojis_per_page
        
        if self.current_page < max_pages - 1:
            self.current_page += 1
            await self.update_emoji_page(interaction)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="← Back to Economy", style=discord.ButtonStyle.secondary)
    async def back_to_economy(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = EconomyConfigView()
        await view.show_economy_config(interaction)

    async def show_emoji_selection(self, interaction):
        await self.update_emoji_page(interaction)

    async def update_emoji_page(self, interaction):
        guild_emojis = list(interaction.guild.emojis)
        
        if not guild_emojis:
            embed = discord.Embed(
                title="No Server Emojis",
                description="This server has no custom emojis available for currency.",
                color=0xFF0000
            )
            await interaction.response.edit_message(embed=embed, view=self)
            return
        
        # Calculate pagination
        start_idx = self.current_page * self.emojis_per_page
        end_idx = min(start_idx + self.emojis_per_page, len(guild_emojis))
        page_emojis = guild_emojis[start_idx:end_idx]
        max_pages = (len(guild_emojis) + self.emojis_per_page - 1) // self.emojis_per_page
        
        # Create emoji options
        emoji_options = []
        for emoji in page_emojis:
            # Use the full emoji string for animated emojis
            emoji_value = str(emoji)
            emoji_options.append(discord.SelectOption(
                label=emoji.name[:100],  # Discord label limit
                value=emoji_value,
                description=f"ID: {emoji.id} • Animated: {'Yes' if emoji.animated else 'No'}"[:100],
                emoji=emoji
            ))
        
        if not emoji_options:
            emoji_options.append(discord.SelectOption(label="No emojis on this page", value="none"))
        
        # Update select menu
        self.children[0].options = emoji_options
        self.children[0].placeholder = f"Select from {len(page_emojis)} emojis (Page {self.current_page + 1}/{max_pages})"
        
        # Update navigation buttons
        self.children[1].disabled = self.current_page == 0
        self.children[2].disabled = self.current_page >= max_pages - 1
        
        embed = discord.Embed(
            title="Choose Server Emoji for Currency",
            description=f"Browse server emojis to use as currency symbol\n\n**Page {self.current_page + 1} of {max_pages}**\nShowing emojis {start_idx + 1}-{end_idx} of {len(guild_emojis)}",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        # Show emoji preview
        if page_emojis:
            emoji_preview = " ".join([str(emoji) for emoji in page_emojis[:10]])  # Show first 10 emojis
            if len(page_emojis) > 10:
                emoji_preview += f" ... (+{len(page_emojis) - 10} more)"
            embed.add_field(name="Emojis on this page", value=emoji_preview, inline=False)
        
        # Show server emoji stats
        animated_count = len([e for e in guild_emojis if e.animated])
        static_count = len(guild_emojis) - animated_count
        embed.add_field(
            name="Server Emoji Statistics",
            value=f"Total: {len(guild_emojis)}\nStatic: {static_count}\nAnimated: {animated_count}",
            inline=True
        )
        
        if hasattr(interaction, 'response') and not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

    elif action.value == "list":
        embed = discord.Embed(
            title="Autoresponders",
            color=BOT_CONFIG["default_embed_color"]
        )
        
        if not autoresponders:
            embed.description = "No autoresponders configured."
        else:
            responder_list = []
            for trigger, data in list(autoresponders.items())[:10]:  # Show first 10
                responder_list.append(f"**{trigger}**: {data['response'][:50]}...")
            embed.description = "\n".join(responder_list)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="logging_setup", description="Configure action logging", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(
    log_type="Type of logging to configure",
    channel="Channel for logs"
)
@app_commands.choices(log_type=[
    app_commands.Choice(name="Moderation", value="moderation"),
    app_commands.Choice(name="Member Activity", value="member"),
    app_commands.Choice(name="Message Events", value="message"),
])
async def logging_setup(interaction: discord.Interaction, log_type: app_commands.Choice[str], channel: discord.TextChannel):
    if not has_admin_permissions(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    key = f"{log_type.value}_channel_id"
    logging_settings[key] = channel.id
    save_json("logging_settings.json", logging_settings)
    
    await interaction.response.send_message(f"✅ {log_type.name} logging set to {channel.mention}", ephemeral=True)

@tree.command(name="logging_disable", description="Disable specific logging", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(log_type="Type of logging to disable")
@app_commands.choices(log_type=[
    app_commands.Choice(name="Moderation", value="moderation"),
    app_commands.Choice(name="Member Activity", value="member"),
    app_commands.Choice(name="Message Events", value="message"),
])
async def logging_disable(interaction: discord.Interaction, log_type: app_commands.Choice[str]):
    if not has_admin_permissions(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    key = f"{log_type.value}_channel_id"
    logging_settings.pop(key, None)
    save_json("logging_settings.json", logging_settings)
    
    await interaction.response.send_message(f"✅ {log_type.name} logging disabled", ephemeral=True)

@tree.command(name="export_data", description="Export data files for backup", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def export_data(interaction: discord.Interaction):
    if not has_admin_permissions(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    
    try:
        # Create a backup
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = f"backup_{timestamp}"
        os.makedirs(backup_dir, exist_ok=True)
        
        data_files = [
            "bot_config.json", "tierlist.json", "member_stats.json", "shops.json", 
            "balances.json", "inventories.json", "reaction_roles.json", 
            "sticky_messages.json", "server_settings.json", "verification.json", 
            "auctions.json", "user_profiles.json", "giveaways.json", 
            "premium_slots.json", "logging_settings.json", "member_warnings.json", 
            "autoresponders.json", "profile_presets.json"
        ]
        
        for file in data_files:
            if os.path.exists(file):
                shutil.copy2(file, backup_dir)
        
        embed = discord.Embed(
            title="✅ Data Export Complete",
            description=f"Data exported to: {backup_dir}",
            color=0x00FF00
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"Export failed: {str(e)}", ephemeral=True)

@tree.command(name="cleanup_data", description="Clean up old and invalid data", guild=discord.Object(id=GUILD_ID))
@guild_only()
async def cleanup_data(interaction: discord.Interaction):
    if not has_admin_permissions(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    cleaned_count = 0
    
    # Remove ended giveaways older than 30 days
    current_time = int(time.time())
    thirty_days_ago = current_time - (30 * 24 * 60 * 60)
    
    for giveaway_id in list(giveaways_data.keys()):
        giveaway = giveaways_data[giveaway_id]
        if (giveaway.get("status") == "ended" and 
            giveaway.get("end_time", 0) < thirty_days_ago):
            del giveaways_data[giveaway_id]
            cleaned_count += 1
    
    # Clean up invalid premium slots
    for user_id in list(premium_slots.keys()):
        if premium_slots[user_id].get("total_slots", 0) < 0:
            premium_slots[user_id]["total_slots"] = 0
        if premium_slots[user_id].get("used_slots", 0) < 0:
            premium_slots[user_id]["used_slots"] = 0
    
    save_all()
    
    embed = discord.Embed(
        title="Data Cleanup Complete",
        description=f"Cleaned up {cleaned_count} old records",
        color=0x00FF00
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="role_menu", description="Create self-role selection menus", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(title="Title for the role menu", description="Description for the role menu")
async def role_menu(interaction: discord.Interaction, title: str, description: str = None):
    if not has_admin_permissions(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    view = RoleMenuSetupView(title, description)
    embed = discord.Embed(
        title="Role Menu Setup",
        description=f"Setting up role menu: **{title}**\n\nUse the buttons below to add roles to the menu.",
        color=BOT_CONFIG["default_embed_color"]
    )
    
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class RoleMenuSetupView(discord.ui.View):
    def __init__(self, title: str, description: str = None):
        super().__init__(timeout=600)
        self.title = title
        self.description = description
        self.roles = []

    @discord.ui.button(label="Add Role", style=discord.ButtonStyle.green)
    async def add_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RoleMenuAddModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Create Menu", style=discord.ButtonStyle.primary)
    async def create_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.roles:
            await interaction.response.send_message("Please add at least one role first.", ephemeral=True)
            return

        await self.create_role_menu(interaction)

    async def create_role_menu(self, interaction):
        embed = discord.Embed(
            title=self.title,
            description=self.description or "Select roles below:",
            color=BOT_CONFIG["default_embed_color"]
        )

        role_list = []
        for role_data in self.roles:
            role = interaction.guild.get_role(role_data["role_id"])
            if role:
                role_list.append(f"{role_data['emoji']} {role.name}")

        if role_list:
            embed.add_field(name="Available Roles", value="\n".join(role_list), inline=False)

        view = RoleMenuView(self.roles)
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Role menu created!", ephemeral=True)

class RoleMenuAddModal(discord.ui.Modal):
    def __init__(self, setup_view):
        super().__init__(title="Add Role to Menu")
        self.setup_view = setup_view

        self.role_id = discord.ui.TextInput(
            label="Role ID",
            placeholder="Enter the role ID",
            required=True,
            max_length=20
        )

        self.emoji = discord.ui.TextInput(
            label="Emoji",
            placeholder="Enter emoji for this role",
            required=True,
            max_length=10
        )

        self.add_item(self.role_id)
        self.add_item(self.emoji)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            role_id = int(self.role_id.value)
            role = interaction.guild.get_role(role_id)

            if not role:
                await interaction.response.send_message("Role not found.", ephemeral=True)
                return

            self.setup_view.roles.append({
                "role_id": role_id,
                "emoji": self.emoji.value
            })

            await interaction.response.send_message(f"✅ Added {role.name} with emoji {self.emoji.value}", ephemeral=True)

        except ValueError:
            await interaction.response.send_message("Invalid role ID.", ephemeral=True)

class RoleMenuView(discord.ui.View):
    def __init__(self, roles):
        super().__init__(timeout=None)
        self.roles = roles

        for role_data in roles[:5]:  # Discord button limit
            button = discord.ui.Button(
                label=f"Role",
                emoji=role_data["emoji"],
                style=discord.ButtonStyle.secondary,
                custom_id=f"role_{role_data['role_id']}"
            )
            button.callback = self.role_callback
            self.add_item(button)

    async def role_callback(self, interaction: discord.Interaction):
        custom_id = interaction.custom_id
        role_id = int(custom_id.split("_")[1])
        role = interaction.guild.get_role(role_id)

        if not role:
            await interaction.response.send_message("Role not found.", ephemeral=True)
            return

        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(f"✅ Removed {role.name}", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"✅ Added {role.name}", ephemeral=True)

@tree.command(name="debug_user", description="Debug user data", guild=discord.Object(id=GUILD_ID))
@guild_only()
@app_commands.describe(user="User to debug")
async def debug_user(interaction: discord.Interaction, user: discord.Member):
    if not has_admin_permissions(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    user_id = str(user.id)
    embed = discord.Embed(
        title=f"Debug Info for {user.display_name}",
        color=BOT_CONFIG["default_embed_color"]
    )

    # Stats
    stats = member_stats.get(user_id, {})
    embed.add_field(
        name="Stats",
        value=f"XP: {stats.get('xp', 0)}\nLevel: {calculate_level(stats.get('xp', 0))}\nMessages: {stats.get('all_time_messages', 0)}",
        inline=True
    )

    # Economy
    balance = user_balances.get(user_id, 0)
    inventory_count = len(user_inventories.get(user_id, {}))
    embed.add_field(
        name="Economy",
        value=f"Balance: {get_currency_symbol()}{balance}\nInventory Items: {inventory_count}",
        inline=True
    )

    # Premium slots
    slots = premium_slots.get(user_id, {"total_slots": 0, "used_slots": 0})
    embed.add_field(
        name="Premium Slots",
        value=f"Total: {slots['total_slots']}\nUsed: {slots['used_slots']}",
        inline=True
    )

    # Profile
    has_profile = "Yes" if user_id in user_profiles else "No"
    warnings_count = len(member_warnings.get(user_id, []))
    embed.add_field(
        name="Other",
        value=f"Profile: {has_profile}\nWarnings: {warnings_count}",
        inline=True
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Bot started successfully as {bot.user}")

    try:
        await tree.sync(guild=discord.Object(id=GUILD_ID))
        logger.info("Command tree synced successfully")
        print(f"Synced {len(tree.get_commands())} commands to guild {GUILD_ID}")
    except Exception as e:
        logger.error(f"Failed to sync command tree: {e}")
        print(f"Failed to sync commands: {e}")

    reset_daily.start()
    check_giveaways.start()
    automated_backup.start()

bot.run(TOKEN)
