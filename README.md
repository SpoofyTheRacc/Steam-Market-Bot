made by spoofy.racc on discord. 

# Rust SCMM Discord Bot

Discord bot that surfaces Rust item store and market intel directly into your server, powered by the public [`rust.scmm.app`](https://rust.scmm.app/) API.

The bot is designed for investors, traders, and community managers who want a clean, automated view of weekly store rotations and cross-market pricing (Steam, Skinport, CS.Deals) without manually tabbing through sites.

---

## Key Features

- **Weekly Store Lookup (`/week_lookup`)**
  - Pulls the Rust item store for a specific date (by year, month, day).
  - Compares **Store price vs Steam Market**.
  - Auto-builds an embed per item with:
    - Name, type, collection
    - Store price
    - Steam market price and `% vs store`
    - IDs (store ID, app ID, workshop ID)
    - “Insider” stats (subs, views, favourites, votes, etc.)
  - Messages auto-delete after 5 minutes to keep channels clean.

- **Single Item Deep Dive (`/item_lookup`)**
  - Looks up one skin by name using SCMM item details.
  - Shows:
    - Store price
    - Steam price (% vs store)
    - Skinport price (% vs Steam)
    - CS.Deals price (% vs Steam)
    - Insider stats (supply, subs, views, votes, favourites, components).
  - Includes link buttons:
    - 🟦 **Steam Market**
    - 🟣 **CS.Deals**
    - 🟢 **Skinport**
  - Messages auto-delete after 5 minutes.

- **SCMM Store Debug Utilities**
  - `/store_current_debug`  
    Preview raw structure of the current store from `/api/store/current`.
  - `/store_list_debug`  
    Show the latest 10 store IDs from `/api/store`.

- **Operational Quality-of-Life**
  - Auto-delete wrapper for responses to avoid clutter.
  - Resilient to Discord “Unknown interaction (10062)” issues.
  - Safe handling of SCMM timeouts / invalid JSON / 404s with clear error messaging.

---

## Tech Stack

- **Language:** Python 3.10+
- **Discord Library:** `discord.py` (app commands / slash commands)
- **HTTP Client:** `httpx`
- **Config:** `.env` via `python-dotenv`
- **API:** [`rust.scmm.app`](https://rust.scmm.app/) public endpoints

---

## Requirements

- Python **3.10 or higher**
- A Discord bot application and bot token
- A Discord server (guild) where you can manage slash commands

---

## Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/<your-username>/<your-repo>.git
   cd <your-repo>
