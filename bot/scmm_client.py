"""
SCMM client utilities for the Rust store Discord bot.

This module provides:
- A light abstraction over the rust.scmm.app HTTP API.
- Store fetching by:
  - current store (/api/store/current)
  - store list (/api/store)
  - specific store ID (/api/store/{id})
  - store by start date (YYYY-MM-DD)
- Per-item detail lookups (/api/item/{name}).
- Normalized price and market breakdown helpers.
- Marketplace URL construction for Steam, Skinport, and CS.Deals.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, quote_plus

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://rust.scmm.app"
API_BASE = f"{BASE_URL}/api"


# ======================================================================
# Data models
# ======================================================================


@dataclass
class StoreItem:
    """Normalized minimal view of a Rust store item from SCMM."""

    id: Optional[int]
    name: str
    store_price: Optional[float]
    icon_url: Optional[str]
    workshop_file_id: Optional[int]
    app_id: Optional[int]
    item_type: Optional[str] = None
    collection: Optional[str] = None


# ======================================================================
# Low-level HTTP helpers
# ======================================================================


async def ping_scmm() -> Tuple[bool, str]:
    """
    Perform a lightweight connectivity check against rust.scmm.app.

    Returns
    -------
    (ok, message)
        ok:
            True if the request succeeded, False if it failed.
        message:
            Human-readable status information.
    """
    url = f"{BASE_URL}/docs/index.html"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url)
        resp.raise_for_status()
    except httpx.ReadTimeout as exc:
        logger.warning("SCMM ping timed out: %s", exc, exc_info=True)
        return (
            False,
            "SCMM timed out while responding. The bot is fine; SCMM is just slow or unreachable right now.",
        )
    except httpx.RequestError as exc:
        logger.warning("Network error talking to SCMM: %s", exc, exc_info=True)
        return False, f"Network error talking to SCMM: {exc}"
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.warning("SCMM returned bad status: %s", exc, exc_info=True)
        return False, f"SCMM responded with HTTP {status} for {exc.request.url}"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error pinging SCMM")
        return False, f"Unexpected error: {type(exc).__name__}: {exc}"

    size = len(resp.content or b"")
    return True, f"OK — HTTP {resp.status_code}, docs payload size ≈ {size} bytes."


async def _http_get_json(url: str) -> Any:
    """
    Perform an HTTP GET request and decode the JSON body.

    Raises
    ------
    RuntimeError
        If the request fails or the response is not valid JSON.
    """
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url)
        resp.raise_for_status()
    except httpx.RequestError as exc:
        logger.warning("Network error calling %s: %s", url, exc, exc_info=True)
        raise RuntimeError(f"Network error talking to SCMM: {exc}") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.warning("SCMM returned bad status for %s: %s", url, exc, exc_info=True)
        raise RuntimeError(
            f"SCMM responded with HTTP {status} for {exc.request.url}"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error calling %s", url)
        raise RuntimeError(
            f"Unexpected error calling SCMM: {type(exc).__name__}: {exc}"
        ) from exc

    try:
        return resp.json()
    except ValueError as exc:
        logger.warning("Failed to decode JSON from %s: %s", url, exc, exc_info=True)
        raise RuntimeError("SCMM returned invalid JSON") from exc


# ======================================================================
# Store: current + by date
# ======================================================================


async def fetch_store_current_raw() -> Dict[str, Any]:
    """
    Fetch the *current* Rust item store from SCMM as raw JSON.

    Returns
    -------
    dict
        The raw JSON object (or a wrapper dict if SCMM returns a non-object).
    """
    url = f"{API_BASE}/store/current"
    data = await _http_get_json(url)
    if not isinstance(data, dict):
        return {"_root": data}
    return data


def _normalize_store_item(raw: Dict[str, Any]) -> StoreItem:
    """
    Normalize a raw store item payload into a StoreItem instance.

    SCMM commonly uses integer cents for prices; this function normalizes
    them into USD floats where possible.
    """
    id_ = raw.get("id")
    name = raw.get("name") or "Unknown"

    # Store price: SCMM commonly uses integer cents.
    store_price: Optional[float] = None
    raw_price: Optional[float] = None
    for key in ("storePrice", "price", "usdPrice", "finalPrice"):
        val = raw.get(key)
        if isinstance(val, (int, float)):
            raw_price = float(val)
            break

    if raw_price is not None:
        store_price = raw_price / 100.0 if raw_price > 50 else raw_price

    icon_url = (
        raw.get("iconUrl")
        or raw.get("iconURL")
        or raw.get("imageUrl")
        or None
    )

    workshop_file_id = raw.get("workshopFileId")
    app_id = raw.get("appId")
    item_type = raw.get("itemType") or None
    item_collection = raw.get("itemCollection") or None

    return StoreItem(
        id=id_,
        name=name,
        store_price=store_price,
        icon_url=icon_url,
        workshop_file_id=workshop_file_id,
        app_id=app_id,
        item_type=item_type,
        collection=item_collection,
    )


async def fetch_store_current_items() -> List[StoreItem]:
    """
    Return the current store as a list of normalized StoreItem objects.
    """
    data = await fetch_store_current_raw()
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return []

    items: List[StoreItem] = []
    for raw in raw_items:
        if isinstance(raw, dict):
            items.append(_normalize_store_item(raw))
    return items


async def fetch_store_list_raw() -> List[Dict[str, Any]]:
    """
    List all known store instances from `/api/store`.

    Returns
    -------
    list[dict]
        Raw store entries as returned by SCMM.
    """
    url = f"{API_BASE}/store"
    data = await _http_get_json(url)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return items
    return []


async def fetch_store_items_by_id(store_id: str) -> List[StoreItem]:
    """
    Fetch store items for a specific historical store ID.

    Parameters
    ----------
    store_id:
        Store ID string, e.g. "2025-11-13-2054".

    Returns
    -------
    list[StoreItem]
        Normalized items for that store, if found.
    """
    url = f"{API_BASE}/store/{store_id}"
    data = await _http_get_json(url)
    if not isinstance(data, dict):
        return []

    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return []

    return [
        _normalize_store_item(raw)
        for raw in raw_items
        if isinstance(raw, dict)
    ]


async def fetch_store_items_for_date(
    target_date: date,
) -> Tuple[List[StoreItem], Optional[str]]:
    """
    Return items for the store whose `start` date == target_date (UTC date).

    SCMM's `/api/store` entries use IDs like "2025-11-06-1819" and
    ISO timestamps like "2025-11-06T18:18:07.818429+00:00".

    We match on the `YYYY-MM-DD` part of `start`. If multiple stores
    exist on that date, we take the one with the latest `start` timestamp.

    Returns
    -------
    (items, store_id)
        items:
            List of normalized StoreItem objects.
        store_id:
            The SCMM store ID string for the chosen store, or None.
    """
    stores = await fetch_store_list_raw()
    if not stores:
        return [], None

    target_str = target_date.isoformat()  # 'YYYY-MM-DD'

    matches: List[Dict[str, Any]] = []
    for store in stores:
        start = store.get("start")
        if not isinstance(start, str):
            continue
        start_date_str = start.split("T", 1)[0]
        if start_date_str == target_str:
            matches.append(store)

    if not matches:
        return [], None

    # Choose the latest start time on that day
    chosen = sorted(matches, key=lambda s: str(s.get("start") or ""))[-1]
    store_id = chosen.get("id")
    if not store_id:
        return [], None

    items = await fetch_store_items_by_id(str(store_id))
    return items, str(store_id)


# ======================================================================
# Per-item detail + market breakdown
# ======================================================================


async def fetch_item_details_for_store_item(item: StoreItem) -> Dict[str, Any]:
    """
    Fetch full detail JSON for a store item using `/api/item/{name}`.

    This powers all the “insider data”:
    supply, subscribers, votes, favourites, views, breakdown, markets, etc.
    """
    if not item.name:
        raise RuntimeError("Item has no name for detail lookup")

    safe = quote(item.name, safe="")
    url = f"{API_BASE}/item/{safe}"
    details = await _http_get_json(url)
    if not isinstance(details, dict):
        raise RuntimeError("SCMM item details response was not an object")
    return details


def extract_store_price_from_details(details: Dict[str, Any]) -> Optional[float]:
    """
    Extract the store price (USD) from item details, normalized.

    SCMM may store the price as integer cents; this function normalizes it
    to a float in USD where possible.
    """
    val = details.get("storePrice")
    if not isinstance(val, (int, float)):
        return None
    v = float(val)
    return v / 100.0 if v > 50 else v


async def fetch_item_details_by_name(name: str) -> Dict[str, Any]:
    """
    Fetch full SCMM item details for an arbitrary Rust skin name.

    This powers the `/item_lookup` command: deep-dive on a single skin
    without going through a specific store.

    Raises
    ------
    RuntimeError
        If the item name is empty, unavailable, or SCMM returns an error.
    """
    clean = (name or "").strip()
    if not clean:
        raise RuntimeError("Item name is required")

    safe = quote(clean, safe="")
    url = f"{API_BASE}/item/{safe}"

    try:
        details = await _http_get_json(url)
    except RuntimeError as exc:
        msg = str(exc)
        # _http_get_json reports: "SCMM responded with HTTP 404 ..." on 404s
        if "HTTP 404" in msg:
            raise RuntimeError(
                f"No item found on SCMM matching '{clean}'. "
                "Check the spelling or try a different name."
            ) from exc
        # Anything else: bubble up as a generic error
        raise

    if not isinstance(details, dict):
        raise RuntimeError("SCMM item details response was not an object")

    return details


def get_market_breakdown(details: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """
    Build a unified pricing model for one skin.

    Returns a dict with:
      - store_price (USD)
      - steam_price (USD)
      - steam_vs_store_pct     (Steam vs store, +x% or -x%)
      - skinport_price (USD)
      - skinport_vs_steam_pct  (Skinport vs Steam)
      - csdeals_price (USD)
      - csdeals_vs_steam_pct   (CS.Deals vs Steam)
    """

    def _norm_price(val: Any) -> Optional[float]:
        if not isinstance(val, (int, float)):
            return None
        v = float(val)
        # Heuristic: values > 50 are probably cents
        return v / 100.0 if v > 50 else v

    store_price = extract_store_price_from_details(details)

    steam_price: Optional[float] = None
    skinport_price: Optional[float] = None
    csdeals_price: Optional[float] = None

    def scan(seq: List[Dict[str, Any]]) -> None:
        nonlocal steam_price, skinport_price, csdeals_price

        for entry in seq:
            if not isinstance(entry, dict):
                continue
            if entry.get("isAvailable") is False:
                continue

            mtype = entry.get("marketType")
            p = _norm_price(entry.get("price"))
            if p is None:
                continue

            if mtype in ("SteamCommunityMarket", "SteamMarket"):
                if steam_price is None or p < steam_price:
                    steam_price = p
            elif mtype == "Skinport":
                if skinport_price is None or p < skinport_price:
                    skinport_price = p
            elif mtype == "CSDealsMarketplace":
                if csdeals_price is None or p < csdeals_price:
                    csdeals_price = p

    for key in ("buyPrices", "sellPrices"):
        seq = details.get(key)
        if isinstance(seq, list):
            scan(seq)

    # %: Steam vs Store
    steam_vs_store_pct: Optional[float] = None
    if store_price is not None and steam_price is not None and store_price != 0:
        steam_vs_store_pct = (steam_price - store_price) / store_price * 100.0

    # %: Skinport / CS.Deals vs Steam
    def _pct_vs_steam(price: Optional[float]) -> Optional[float]:
        if steam_price is None or price is None or steam_price == 0:
            return None
        return (price - steam_price) / steam_price * 100.0

    skinport_vs_steam_pct = _pct_vs_steam(skinport_price)
    csdeals_vs_steam_pct = _pct_vs_steam(csdeals_price)

    return {
        "store_price": store_price,
        "steam_price": steam_price,
        "steam_vs_store_pct": steam_vs_store_pct,
        "skinport_price": skinport_price,
        "skinport_vs_steam_pct": skinport_vs_steam_pct,
        "csdeals_price": csdeals_price,
        "csdeals_vs_steam_pct": csdeals_vs_steam_pct,
    }


# ======================================================================
# Marketplace URLs
# ======================================================================


def extract_market_urls(details: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """
    Extract external marketplace URLs (Steam, Skinport, CS.Deals) for an item.

    Strategy
    --------
    - Steam + Skinport:
        Trust URLs in SCMM data if present; fallback to deterministic
        listing/search URLs.
    - CS.Deals:
        Ignore any SCMM URL and always build the precise Rust-market
        search URL pattern:

        https://cs.deals/new/market
            ?game=rust
            &sort=newest
            &sort_desc=1
            &exact_match=0
            &name=...
    """
    urls: Dict[str, Optional[str]] = {
        "steam": None,
        "skinport": None,
        "csdeals": None,
    }

    # 1) Scan price entries for URLs for Steam/Skinport ONLY
    for key in ("buyPrices", "sellPrices"):
        seq = details.get(key)
        if not isinstance(seq, list):
            continue

        for entry in seq:
            if not isinstance(entry, dict):
                continue

            mtype = entry.get("marketType")
            url = entry.get("url") or entry.get("link") or entry.get("href")
            if not isinstance(url, str) or not url:
                continue

            # Steam / SteamCommunityMarket
            if mtype in ("SteamCommunityMarket", "SteamMarket"):
                if urls["steam"] is None:
                    urls["steam"] = url

            # Skinport
            elif mtype == "Skinport":
                if urls["skinport"] is None:
                    urls["skinport"] = url

            # CS.Deals URLs from SCMM are ignored on purpose –
            # we want our own pattern.
            # elif mtype == "CSDealsMarketplace":
            #     pass

    # 2) Top-level fallback keys for Steam + Skinport only
    top_map: Dict[str, List[str]] = {
        "steam": ["steamMarketUrl", "steamMarketURL", "steamUrl"],
        "skinport": ["skinportUrl", "skinPortUrl"],
        # csdeals is intentionally excluded here
    }

    for market_key, candidates in top_map.items():
        if urls[market_key] is not None:
            continue
        for field in candidates:
            val = details.get(field)
            if isinstance(val, str) and val:
                urls[market_key] = val
                break

    # 3) Final fallback: construct URLs from the item name
    name = details.get("name")
    if isinstance(name, str) and name:
        safe_name = quote(name, safe="")

        # Steam listing for Rust (appId 252490)
        if urls["steam"] is None:
            urls["steam"] = f"https://steamcommunity.com/market/listings/252490/{safe_name}"

        # Skinport Rust search
        if urls["skinport"] is None:
            urls["skinport"] = f"https://skinport.com/rust?search={safe_name}"

        # CS.Deals: ALWAYS our custom Rust-market search URL
        name_for_query = quote_plus(name)
        urls["csdeals"] = (
            "https://cs.deals/new/market"
            f"?game=rust&sort=newest&sort_desc=1&exact_match=0&name={name_for_query}"
        )

    return urls


# ======================================================================
# Misc
# ======================================================================


def calculate_tradable_datetime(released_at: str) -> str:
    """
    Placeholder for future logic around tradable/marketable dates.

    Parameters
    ----------
    released_at:
        ISO timestamp string when the item was accepted / released.

    Returns
    -------
    str
        Currently returns a placeholder string; implement as needed.
    """
    return "TBD"


__all__ = [
    "StoreItem",
    "ping_scmm",
    "fetch_store_current_raw",
    "fetch_store_current_items",
    "fetch_store_list_raw",
    "fetch_store_items_by_id",
    "fetch_store_items_for_date",
    "fetch_item_details_for_store_item",
    "extract_store_price_from_details",
    "fetch_item_details_by_name",
    "get_market_breakdown",
    "extract_market_urls",
    "calculate_tradable_datetime",
]
