"""
Discord embed builders for the Rust SCMM bot.

This module is responsible for rendering:
- Weekly store cards (Store vs Steam, optional 3rd-party markets).
- Single-item overview cards (Store, Steam, Skinport, CS.Deals).
- Link-button views (Steam / Skinport / CS.Deals).
- “Insider” stats blocks based on SCMM item detail JSON.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import discord

from .scmm_client import (
    StoreItem,
    extract_market_urls,
    get_market_breakdown,
)

# ======================================================================
# Price / market text rendering
# ======================================================================


def _render_market_lines(
    details: Optional[Dict[str, Any]],
    include_third_party: bool,
) -> str:
    """
    Build the price block text based on the unified market breakdown.

    Always shows:
    - Store price (USD)
    - Steam vs Store

    Optionally shows (when include_third_party=True):
    - Skinport vs Steam
    - CS.Deals vs Steam
    """
    if not details:
        return "**Store:** Unknown\n**Steam Market:** No data"

    bd = get_market_breakdown(details)

    store = bd["store_price"]
    steam = bd["steam_price"]
    steam_pct = bd["steam_vs_store_pct"]
    skinport = bd["skinport_price"]
    skinport_pct = bd["skinport_vs_steam_pct"]
    csdeals = bd["csdeals_price"]
    csdeals_pct = bd["csdeals_vs_steam_pct"]

    lines: list[str] = []

    # Store
    if store is not None:
        lines.append(f"**Store:** ${store:.2f}")
    else:
        lines.append("**Store:** Unknown")

    # Steam vs Store
    if steam is not None:
        if steam_pct is not None:
            sign = "+" if steam_pct >= 0 else "-"
            emoji = "🟢" if steam_pct >= 0 else "🔴"
            lines.append(
                f"**Steam Market:** ${steam:.2f} "
                f"({emoji} {sign}{abs(steam_pct):.1f}% vs store)"
            )
        else:
            lines.append(f"**Steam Market:** ${steam:.2f}")
    else:
        lines.append("**Steam Market:** No data")

    # Skinport / CS.Deals vs Steam
    if include_third_party:
        if skinport is not None:
            if skinport_pct is not None:
                sign = "+" if skinport_pct >= 0 else "-"
                emoji = "🟢" if skinport_pct >= 0 else "🔴"
                lines.append(
                    f"**Skinport:** ${skinport:.2f} "
                    f"({emoji} {sign}{abs(skinport_pct):.1f}% vs Steam)"
                )
            else:
                lines.append(f"**Skinport:** ${skinport:.2f}")
        else:
            lines.append("**Skinport:** No listings")

        if csdeals is not None:
            if csdeals_pct is not None:
                sign = "+" if csdeals_pct >= 0 else "-"
                emoji = "🟢" if csdeals_pct >= 0 else "🔴"
                lines.append(
                    f"**CS.Deals:** ${csdeals:.2f} "
                    f"({emoji} {sign}{abs(csdeals_pct):.1f}% vs Steam)"
                )
            else:
                lines.append(f"**CS.Deals:** ${csdeals:.2f}")
        else:
            lines.append("**CS.Deals:** No listings")

    return "\n".join(lines)


# ======================================================================
# Link button view for /item_lookup
# ======================================================================


def build_iteminfo_view(details: Dict[str, Any]) -> Optional[discord.ui.View]:
    """
    Build a link-button row for `/item_lookup`:

    - 🟦 Steam Market
    - 🟣 CS.Deals
    - 🟢 Skinport

    Returns
    -------
    discord.ui.View | None
        View containing link buttons, or None if no URLs are available.
    """
    urls = extract_market_urls(details)

    view = discord.ui.View()
    buttons = 0

    steam_url = urls.get("steam")
    csdeals_url = urls.get("csdeals")
    skinport_url = urls.get("skinport")

    if steam_url:
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                url=steam_url,
                label="Steam Market",
                emoji="🟦",
            )
        )
        buttons += 1

    if csdeals_url:
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                url=csdeals_url,
                label="CS.Deals",
                emoji="🟣",
            )
        )
        buttons += 1

    if skinport_url:
        view.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                url=skinport_url,
                label="Skinport",
                emoji="🟢",
            )
        )
        buttons += 1

    if buttons == 0:
        return None

    return view


# ======================================================================
# Shared stats block
# ======================================================================


def _build_stats_block(details: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Build the multi-line insider stats block from item details JSON.

    Includes:
    - Released date + store price
    - Estimated supply
    - Workshop subscribers
    - Votes (with positive ratio)
    - Favourites
    - Views
    - Breaks-into components (if present)
    """
    if not details:
        return None

    lines: list[str] = []

    # Released date + store price
    released = details.get("timeAccepted")
    store_price = details.get("storePrice")
    if isinstance(store_price, (int, float)):
        store_price = float(store_price)
        store_price = store_price / 100.0 if store_price > 50 else store_price
    else:
        store_price = None

    date_txt = None
    if isinstance(released, str) and released:
        date_txt = released.split("T", 1)[0]

    if date_txt or store_price is not None:
        price_part = f"for **${store_price:.2f}**" if store_price is not None else ""
        if date_txt:
            lines.append(f"🛒 Released on **{date_txt}** {price_part}".strip())
        elif price_part:
            lines.append(f"🛒 Store price {price_part}")

    # Supply
    supply_est = (
        details.get("supplyTotalEstimated")
        or details.get("supplyTotalOwnersEstimated")
    )
    if isinstance(supply_est, (int, float)):
        lines.append(f"📦 Estimated supply: **{int(supply_est):,}**")

    # Subscribers
    subs = details.get("subscriptionsCurrent") or details.get("subscriptionsLifetime")
    if isinstance(subs, (int, float)):
        lines.append(f"👥 Workshop subscribers: **{int(subs):,}**")

    # Votes + rating
    votes_up = details.get("votesUp")
    votes_down = details.get("votesDown")
    if isinstance(votes_up, int) and isinstance(votes_down, int):
        total_votes = votes_up + votes_down
        if total_votes > 0:
            ratio = (votes_up / total_votes) * 100.0
            lines.append(f"👍 Votes: **{total_votes:,}** ({ratio:.0f}% positive)")

    # Favourites
    favs = details.get("favouritedCurrent") or details.get("favouritedLifetime")
    if isinstance(favs, (int, float)):
        lines.append(f"⭐ Favourited: **{int(favs):,}**")

    # Views
    views = details.get("views")
    if isinstance(views, (int, float)):
        lines.append(f"👀 Workshop views: **{int(views):,}**")

    # Breaks into components
    components = details.get("breaksIntoComponents")
    if isinstance(components, dict) and components:
        parts = [
            f"{int(v)}x {k}"
            for k, v in components.items()
            if isinstance(v, (int, float))
        ]
        if parts:
            lines.append("🪓 Breaks into " + ", ".join(parts))

    return "\n".join(lines) if lines else None


# ======================================================================
# Weekly store embed
# ======================================================================


def build_store_item_embed(
    item: StoreItem,
    details: Optional[Dict[str, Any]] = None,
    *,
    include_third_party: bool = True,
) -> discord.Embed:
    """
    Weekly-style card with pricing + stats.

    For `/week_lookup` you typically pass `include_third_party=False`
    so it shows only Store vs Steam. For other contexts, you can enable
    full Store / Steam / Skinport / CS.Deals breakdown.
    """
    subtitle_parts: list[str] = []
    if item.item_type:
        subtitle_parts.append(item.item_type)
    if item.collection:
        subtitle_parts.append(f"{item.collection} collection")
    subtitle = " • ".join(subtitle_parts) if subtitle_parts else "Rust store item"

    embed = discord.Embed(
        title=item.name,
        description=subtitle,
        color=discord.Color.dark_orange(),
    )

    if item.icon_url:
        embed.set_image(url=item.icon_url)

    # Prices: Store vs Steam vs 3rd party
    price_block = _render_market_lines(details, include_third_party=include_third_party)
    embed.add_field(
        name="🛒 Prices",
        value=price_block,
        inline=False,
    )

    # IDs / meta
    id_lines: list[str] = []
    if item.workshop_file_id:
        id_lines.append(f"Workshop: `{item.workshop_file_id}`")
    if item.id is not None:
        id_lines.append(f"Store ID: `{item.id}`")
    if item.app_id:
        id_lines.append(f"App ID: `{item.app_id}`")

    if id_lines:
        embed.add_field(
            name="🧾 Details",
            value="\n".join(id_lines),
            inline=False,
        )

    stats_block = _build_stats_block(details)
    if stats_block:
        embed.add_field(
            name="📊 Item stats",
            value=stats_block,
            inline=False,
        )

    embed.set_footer(text="SCMM • Weekly Rust Store • Auto-deletes in 5 minutes")
    return embed


# ======================================================================
# Optional single-item lookup embed (Store vs Steam only)
# ======================================================================


def build_lookup_embed(details: Dict[str, Any]) -> discord.Embed:
    """
    Single-item lookup card: Store vs Steam only (no Skinport / CS.Deals).

    Not currently used by `/week_lookup` or `/item_lookup`, but kept as a
    generic helper for “just check store vs Steam for this one item”.
    """
    name = details.get("name") or "Unknown item"

    icon_url = (
        details.get("iconUrl")
        or details.get("iconURL")
        or details.get("imageUrl")
    )

    embed = discord.Embed(
        title=name,
        description="Lookup: Store vs Steam Market",
        color=discord.Color.blurple(),
    )

    if icon_url:
        embed.set_thumbnail(url=icon_url)
        embed.set_image(url=icon_url)

    price_block = _render_market_lines(details, include_third_party=False)
    embed.add_field(
        name="🛒 Prices",
        value=price_block,
        inline=False,
    )

    stats_block = _build_stats_block(details)
    if stats_block:
        embed.add_field(
            name="📊 Item stats",
            value=stats_block,
            inline=False,
        )

    embed.set_footer(text="SCMM • Lookup • Auto-deletes in 5 minutes")
    return embed


# ======================================================================
# /item_lookup overview embed
# ======================================================================


def build_item_overview_embed(details: Dict[str, Any]) -> discord.Embed:
    """
    Full market overview card for a single Rust skin.

    Includes:
    - Store price
    - Steam Market price (vs store)
    - Skinport / CS.Deals (vs Steam)
    - Insider stats (subs, views, votes, favourites, etc.)

    This is what `/item_lookup` uses.
    """
    name = details.get("name") or "Unknown item"

    icon_url = (
        details.get("iconUrl")
        or details.get("iconURL")
        or details.get("imageUrl")
    )

    embed = discord.Embed(
        title=name,
        description="Cross-market overview (Store, Steam, Skinport, CS.Deals)",
        color=discord.Color.blurple(),
    )

    if icon_url:
        embed.set_image(url=icon_url)

    # Prices: Store vs Steam vs 3rd party (Skinport / CS.Deals)
    price_block = _render_market_lines(details, include_third_party=True)
    embed.add_field(
        name="🛒 Prices",
        value=price_block,
        inline=False,
    )

    stats_block = _build_stats_block(details)
    if stats_block:
        embed.add_field(
            name="📊 Item stats",
            value=stats_block,
            inline=False,
        )

    embed.set_footer(text="SCMM • Item Market Overview • Auto-deletes in 5 minutes")
    return embed


__all__ = [
    "build_iteminfo_view",
    "build_store_item_embed",
    "build_lookup_embed",
    "build_item_overview_embed",
]
