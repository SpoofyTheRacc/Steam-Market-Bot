"""
Main entrypoint for the Rust SCMM Discord bot.
This bot was intended for profit under the spoof.gg domain.
If used or partially used please credit my github.

Features:
- /week_lookup  – Weekly Rust store view (Store vs Steam only).
- /item_lookup  – Single-skin deep dive (Store, Steam, Skinport, CS.Deals + buttons).
- /store_current_debug – Raw structure preview of the current store.
- /store_list_debug    – Latest store IDs from SCMM.

Messages sent by bot commands auto-delete after a configurable delay.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date as Date

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from . import embeds, scmm_client

# ======================================================================
# Configuration
# ======================================================================

#: Guild ID where slash commands will be synced.
GUILD_ID: int = 1425205255976783956

#: Maximum number of items to show for a weekly store lookup.
MAX_WEEK_ITEMS: int = 20

#: Default auto-delete delay for command responses (seconds).
DEFAULT_DELETE_DELAY: int = 300

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("rust-scmm-bot")


def get_token() -> str:
    """
    Resolve the Discord bot token from environment variables.

    Expects DISCORD_TOKEN to be set (typically via `.env`).
    """
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN is not set. Create a .env file from .env.example and add your bot token."
        )
    return token


# ======================================================================
# Bot bootstrap
# ======================================================================


class RustSCMMBot(commands.Bot):
    """Discord bot wrapper for Rust SCMM utilities."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(
            command_prefix="/",
            intents=intents,
        )

    async def setup_hook(self) -> None:
        """
        Called by discord.py after login.

        Here we sync the app commands to the configured guild to ensure
        fast propagation and avoid global registration delays.
        """
        guild = discord.Object(id=GUILD_ID)

        # Sync all global commands into the target guild
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        logger.info("Synced %d commands to guild %s", len(synced), GUILD_ID)


bot = RustSCMMBot()

# ======================================================================
# Utility: send follow-up + auto-delete
# ======================================================================


async def send_followup_autodelete(
    interaction: discord.Interaction,
    *,
    embed: discord.Embed,
    view: discord.ui.View | None = None,
    delay: int = DEFAULT_DELETE_DELAY,
) -> None:
    """
    Send a normal follow-up message (non-ephemeral) and schedule auto-delete.

    Parameters
    ----------
    interaction:
        The interaction this follow-up belongs to.
    embed:
        The embed to send as the main content.
    view:
        Optional Discord UI view (e.g., buttons) to attach.
    delay:
        Number of seconds to wait before deleting the message.
    """
    log = logging.getLogger(__name__)

    try:
        if view is not None:
            msg = await interaction.followup.send(embed=embed, view=view, wait=True)
        else:
            msg = await interaction.followup.send(embed=embed, wait=True)
    except discord.NotFound:
        # Interaction token is already invalid (Unknown interaction / timeout)
        log.warning("Interaction expired before followup could be sent.")
        return

    async def _delete_later(message: discord.Message) -> None:
        try:
            await asyncio.sleep(delay)
            await message.delete()
            log.info("Auto-deleted message %s in #%s", message.id, message.channel)
        except discord.NotFound:
            log.info("Message %s already deleted.", message.id)
        except discord.Forbidden:
            log.warning("No permission to delete message %s in %s", message.id, message.channel)
        except Exception as exc:  # noqa: BLE001
            log.exception("Failed to auto-delete message %s: %s", message.id, exc)

    interaction.client.loop.create_task(_delete_later(msg))


# ======================================================================
# Debug / support commands
# ======================================================================


@bot.tree.command(
    name="store_current_debug",
    description="Debug: show raw structure for the current Rust store from SCMM.",
)
async def store_current_debug(interaction: discord.Interaction) -> None:
    """Display a structural preview of `/api/store/current` from SCMM."""
    try:
        await interaction.response.defer(thinking=True)
    except discord.NotFound:
        logger.warning("store_current_debug: interaction expired before defer.")
        return

    try:
        data = await scmm_client.fetch_store_current_raw()
    except RuntimeError as exc:
        embed = discord.Embed(
            title="🧪 Store Debug – Error",
            description=str(exc),
            color=discord.Color.red(),
        )
        embed.set_footer(text="SCMM • Store Debug")
        await interaction.followup.send(embed=embed)
        return

    # Top-level keys
    top_keys = ", ".join(list(data.keys())[:20]) or "(no keys)"

    # Try to locate a list of items; common patterns: 'items', 'store', etc.
    items = None
    items_key = None
    for candidate in ("items", "store", "skins", "entries"):
        value = data.get(candidate)
        if isinstance(value, list) and value:
            items = value
            items_key = candidate
            break

    if items is None:
        sample_block = "No obvious item list found (keys only)."
    else:
        first_item = items[0]
        pretty = json.dumps(first_item, indent=2, ensure_ascii=False)
        if len(pretty) > 900:
            pretty = pretty[:900] + "\n... (truncated)"
        sample_block = f"Key: `{items_key}`\n```json\n{pretty}\n```"

    embed = discord.Embed(
        title="🧪 SCMM Store – Current (Debug)",
        description="Raw structure preview from `/api/store/current`.",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="🧱 Top-level keys",
        value=f"`{top_keys}`",
        inline=False,
    )
    embed.add_field(
        name="📦 Sample item (first in list)",
        value=sample_block,
        inline=False,
    )
    embed.set_footer(text="SCMM • Store Debug")

    await interaction.followup.send(embed=embed)


@bot.tree.command(
    name="store_list_debug",
    description="Debug: list the latest 10 store IDs from SCMM.",
)
async def store_list_debug(interaction: discord.Interaction) -> None:
    """Display the latest 10 store IDs known to SCMM from `/api/store`."""
    try:
        await interaction.response.defer(thinking=True)
    except discord.NotFound:
        logger.warning("store_list_debug: interaction expired before defer.")
        return

    try:
        stores = await scmm_client.fetch_store_list_raw()
    except RuntimeError as exc:
        embed = discord.Embed(
            title="🧾 Store List – Error",
            description=str(exc),
            color=discord.Color.red(),
        )
        embed.set_footer(text="SCMM • Store List Debug")
        await interaction.followup.send(embed=embed)
        return

    if not stores:
        embed = discord.Embed(
            title="🧾 Store List – Empty",
            description="SCMM /api/store returned no store instances.",
            color=discord.Color.orange(),
        )
        embed.set_footer(text="SCMM • Store List Debug")
        await interaction.followup.send(embed=embed)
        return

    # Show up to 10 stores: newest first
    def start_key(store: dict) -> str:
        val = store.get("start")
        return str(val) if val is not None else ""

    stores_sorted = sorted(stores, key=start_key, reverse=True)
    top = stores_sorted[:10]

    lines: list[str] = []
    for store in top:
        sid = store.get("id")
        start = store.get("start")
        name = store.get("name") or store.get("label") or ""
        lines.append(f"ID `{sid}` • start `{start}` • {name}")

    body = "\n".join(lines)
    if len(body) > 1900:
        body = body[:1900] + "\n... (truncated)"

    embed = discord.Embed(
        title="🧾 Store List – Latest 10",
        description=body,
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="SCMM • Store List Debug")
    await interaction.followup.send(embed=embed)


# ======================================================================
# /week_lookup – weekly store view (Store vs Steam only)
# ======================================================================


@bot.tree.command(
    name="week_lookup",
    description="Show the Rust item shop for a specific date with Steam Market change.",
)
@app_commands.describe(
    year="Year (e.g. 2025)",
    month="Month (1-12)",
    day="Day (1-31, the store start date)",
)
async def week_lookup(
    interaction: discord.Interaction,
    year: int,
    month: int,
    day: int,
) -> None:
    """
    Render the Rust item store for a given week, comparing Store vs Steam.

    Third-party markets (Skinport / CS.Deals) are intentionally excluded
    here to keep the weekly view focused and readable.
    """
    # Defer, but don't crash if Discord reports the interaction as unknown
    try:
        await interaction.response.defer(thinking=True)
    except discord.NotFound:
        logger.warning("week_lookup: interaction expired or unknown before defer; aborting command.")
        return

    # 1) Validate date
    try:
        target_date = Date(year, month, day)
    except ValueError as exc:
        embed = discord.Embed(
            title="🛒 Weekly Store – Invalid Date",
            description=f"That date is not valid: `{exc}`",
            color=discord.Color.red(),
        )
        embed.set_footer(text="SCMM • Weekly Store by Date • Auto-deletes in 5 minutes")
        await send_followup_autodelete(interaction, embed=embed)
        return

    # 2) Fetch that week’s store from SCMM
    try:
        items, store_id = await scmm_client.fetch_store_items_for_date(target_date)
    except RuntimeError as exc:
        embed = discord.Embed(
            title="🛒 Weekly Store – Error",
            description=str(exc),
            color=discord.Color.red(),
        )
        embed.set_footer(text="SCMM • Weekly Store by Date • Auto-deletes in 5 minutes")
        await send_followup_autodelete(interaction, embed=embed)
        return

    if not items:
        embed = discord.Embed(
            title="🛒 Weekly Store – No Store for That Date",
            description=(
                f"No store was found with start date `{target_date.isoformat()}`.\n"
                "Use `/store_list_debug` to see available store dates."
            ),
            color=discord.Color.orange(),
        )
        embed.set_footer(text="SCMM • Weekly Store by Date • Auto-deletes in 5 minutes")
        await send_followup_autodelete(interaction, embed=embed)
        return

    total_items = len(items)
    truncated = False
    if total_items > MAX_WEEK_ITEMS:
        truncated = True
        items = items[:MAX_WEEK_ITEMS]

    # 3) For each item, pull details and build a card
    #    week_lookup = Store vs Steam ONLY (include_third_party=False)
    for item in items:
        details = None

        try:
            details = await scmm_client.fetch_item_details_for_store_item(item)
        except RuntimeError as exc:
            logger.info(
                "Failed to enrich item %s for %s: %s",
                item.name,
                target_date.isoformat(),
                exc,
            )

        embed = embeds.build_store_item_embed(
            item,
            details,
            include_third_party=False,  # no Skinport / CS.Deals here
        )

        footer_label = (
            f"SCMM • Store {target_date.isoformat()}"
            + (f" • ID {store_id}" if store_id else "")
            + " • Auto-deletes in 5 minutes"
        )
        embed.set_footer(text=footer_label)

        await send_followup_autodelete(interaction, embed=embed)

    # If we truncated a huge store, tell the user
    if truncated:
        note_embed = discord.Embed(
            title="⚠️ Store truncated",
            description=(
                f"This store has **{total_items}** items.\n"
                f"Showing the first **{MAX_WEEK_ITEMS}** to avoid spamming the channel."
            ),
            color=discord.Color.orange(),
        )
        note_embed.set_footer(text="SCMM • Weekly Store by Date • Auto-deletes in 5 minutes")
        await send_followup_autodelete(interaction, embed=note_embed)


# ======================================================================
# /item_lookup – single-skin deep dive (Store, Steam, Skinport, CS.Deals)
# ======================================================================


@bot.tree.command(
    name="item_lookup",
    description="Deep-dive a Rust skin across Steam and 3rd-party markets.",
)
@app_commands.describe(
    name="Exact skin name as it appears on SCMM / Steam.",
)
async def item_lookup(interaction: discord.Interaction, name: str) -> None:
    """
    Show a cross-market view for a single Rust skin.

    Includes:
    - Store price (USD)
    - Steam Market price (vs store)
    - Skinport price (vs Steam)
    - CS.Deals price (vs Steam)
    - Workshop stats (subs, views, favourites, etc.)
    - Link buttons for Steam, CS.Deals, Skinport
    """
    # Defer with guard against unknown/expired interaction
    try:
        await interaction.response.defer(thinking=True)
    except discord.NotFound:
        logger.warning("item_lookup: interaction expired or unknown before defer; aborting command.")
        return

    try:
        details = await scmm_client.fetch_item_details_by_name(name)
    except RuntimeError as exc:
        msg = str(exc)

        # Friendlier UX: distinguish “not found / bad input” vs real errors
        if "No item found on SCMM" in msg or "Item name is required" in msg:
            title = "🔍 Item Not Found"
            color = discord.Color.orange()
        else:
            title = "🔍 Item Lookup – Error"
            color = discord.Color.red()

        embed = discord.Embed(
            title=title,
            description=msg,
            color=color,
        )
        embed.set_footer(text="SCMM • Item Market Overview • Auto-deletes in 5 minutes")
        await send_followup_autodelete(interaction, embed=embed)
        return

    # /item_lookup shows full breakdown (Store vs Steam vs Skinport vs CS.Deals)
    embed = embeds.build_item_overview_embed(details)
    view = embeds.build_iteminfo_view(details)

    await send_followup_autodelete(
        interaction,
        embed=embed,
        view=view,
    )


# ======================================================================
# /item_lookup autocomplete – NO network I/O (avoid 10062 spam)
# ======================================================================


@item_lookup.autocomplete("name")
async def item_lookup_name_autocomplete(
    interaction: discord.Interaction,  # noqa: ARG001
    current: str,
) -> list[app_commands.Choice[str]]:
    """
    Lightweight autocomplete for /item_lookup name.

    To avoid Unknown interaction (timeout) errors, we DO NOT call SCMM here.
    We just offer a few quick variants of what the user is typing.
    """
    query = (current or "").strip()
    if len(query) < 2:
        return []

    variants = {query, query.title(), query.lower()}
    choices: list[app_commands.Choice[str]] = []

    for value in variants:
        if not value:
            continue
        choices.append(app_commands.Choice(name=value[:100], value=value))
        if len(choices) >= 5:
            break

    return choices


# ======================================================================
# Entrypoint
# ======================================================================


def main() -> None:
    """Entrypoint used by `python -m bot.main`."""
    token = get_token()
    bot.run(token)


if __name__ == "__main__":
    main()
