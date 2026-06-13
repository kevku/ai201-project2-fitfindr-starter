"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import json
import os

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

_CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "tops":       {"shirt", "tee", "top", "blouse", "sweater", "hoodie", "crop", "tank", "polo", "henley", "button"},
    "bottoms":    {"jeans", "pants", "shorts", "skirt", "trousers", "denim", "leggings", "chinos", "slacks"},
    "outerwear":  {"jacket", "coat", "blazer", "vest", "windbreaker", "parka", "bomber", "trench"},
    "shoes":      {"sneakers", "boots", "heels", "shoes", "loafers", "sandals", "trainers", "flats", "oxfords"},
    "accessories":{"hat", "bag", "belt", "scarf", "sunglasses", "glasses", "jewelry", "necklace", "ring",
                   "bracelet", "watch", "purse", "backpack", "cap", "beanie"},
}

_COLORS = {
    "black", "white", "red", "blue", "green", "yellow", "orange", "purple",
    "pink", "brown", "grey", "gray", "navy", "beige", "cream", "tan",
    "indigo", "teal", "maroon", "gold", "silver", "ivory", "khaki",
}

_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "for", "with", "in", "on",
    "at", "to", "of", "by", "from", "is", "are", "was", "has", "have",
    "had", "not", "this", "that", "my", "me", "i", "it", "its",
}


_SIZE_ALIASES: dict[str, str] = {
    "extra small": "xs",
    "small":       "s",
    "medium":      "m",
    "large":       "l",
    "extra large": "xl",
}


def _size_parts(listing_size: str) -> set[str]:
    """Split a listing size into normalized parts, stripping parenthetical notes.

    "XL (fits oversized)" → {"xl"}
    "S/M"                 → {"s", "m"}
    "One Size / Oversized"→ {"one size", "oversized"}
    """
    parts = set()
    for part in listing_size.split("/"):
        clean = part.split("(")[0].strip().lower()
        if clean:
            parts.add(clean)
    return parts


def _size_matches(listing_size: str, requested_size: str) -> bool:
    """Return True if requested_size matches any part of a listing's size field.

    Handles multi-size strings ("S/M", "M/L", "L/XL"), parenthetical notes
    ("XL (fits oversized)"), and full-word aliases ("medium" → "m").
    """
    normalized = _SIZE_ALIASES.get(requested_size.strip().lower(), requested_size.strip().lower())
    return normalized in _size_parts(listing_size)


def _matches_description(listing: dict, desc_words: set[str]) -> bool:
    """Return True if any meaningful description word appears in the listing's text."""
    meaningful = {w for w in desc_words if len(w) >= 3 and w not in _STOP_WORDS}
    if not meaningful:
        return True  # no meaningful words to filter on — don't exclude
    listing_text = " ".join([
        listing.get("title", ""),
        listing.get("description", ""),
        listing.get("category", ""),
        " ".join(listing.get("style_tags", [])),
    ]).lower()
    return any(word in listing_text for word in meaningful)


def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Free-text description of the item (category, color, style).
        size:        Size string for exact case-insensitive match, or None to
                     skip size filtering (e.g. "M", "W30 L30", "US 9.5").
        max_price:   Upper price limit (inclusive), or None to skip price filtering.

    Returns:
        A list of up to 3 matching listing dicts on success.
        An empty list [] when nothing matches.
        Callers should check for an empty list and generate a user-facing message.
    """
    listings = load_listings()

    desc_lower = description.lower()
    desc_words = set(desc_lower.split())

    # Infer category from description keywords (used for scoring only)
    inferred_category: str | None = None
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if keywords & desc_words:
            inferred_category = category
            break

    desc_colors = _COLORS & desc_words

    candidates: list[tuple[int, dict]] = []
    for listing in listings:
        # Hard filter: at least one description keyword must appear in the listing
        if not _matches_description(listing, desc_words):
            continue
        # Hard filters: size and price (only when provided)
        if size is not None and not _size_matches(listing["size"], size):
            continue
        if max_price is not None and listing["price"] > max_price:
            continue

        score = 0
        if inferred_category and listing["category"] == inferred_category:
            score += 2
        listing_colors = {c.lower() for c in listing.get("colors", [])}
        score += len(desc_colors & listing_colors)
        listing_tags = {t.lower() for t in listing.get("style_tags", [])}
        score += len(listing_tags & desc_words)

        candidates.append((score, listing))

    if not candidates:
        return []

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [listing for _, listing in candidates[:3]]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

_REQUIRED_CATEGORIES = {"tops", "bottoms", "shoes"}

_OUTFIT_PROMPT = """\
You are a fashion stylist helping someone style a new thrifted item.

New item being considered:
- Title: {title}
- Category: {category}
- Colors: {colors}
- Style tags: {tags}
- Description: {description}

User's wardrobe:
{wardrobe_lines}

Task: Suggest 1–2 complete outfits pairing the new item with pieces from the wardrobe above.
Rules:
- Each outfit must include at least one top, one bottom, and shoes (if available)
- Prioritize pieces with matching or complementary colors and overlapping style tags
- Outerwear and accessories are optional additions
- Only reference items from the wardrobe list by their exact ID

Return ONLY valid JSON — no markdown, no explanation. Format:
[
  {{
    "outfit_id": 1,
    "piece_ids": ["id1", "id2"],
    "notes": "One or two sentences on why these pieces work together."
  }}
]"""


def suggest_outfit(new_item: dict, wardrobe: dict) -> dict:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty.

    Returns:
        {"results": [{"outfit_id": int, "pieces": [dict], "notes": str}, ...]}
        {"results": [...], "message": str}  when outfit is incomplete
        {"results": [], "message": str}     when wardrobe is empty
        {"duplicate": True, "message": str} when new_item already in wardrobe
    """
    if wardrobe is None:
        wardrobe = {"items": []}
    items = wardrobe.get("items", [])

    if not items:
        title = new_item.get("title", new_item.get("name", "This item"))
        category = new_item.get("category", "")
        _PAIRINGS = {
            "tops":       "baggy jeans, wide-leg trousers, or cargo pants",
            "bottoms":    "a graphic tee, an oversized sweater, or a fitted blouse",
            "outerwear":  "straight-leg jeans and a simple tee, or a monochrome base layer",
            "shoes":      "jeans and a casual top, or a matching set",
            "accessories":"a top, bottoms, and shoes — any combination you like",
        }
        pairing = _PAIRINGS.get(category, "a variety of pieces")
        return {
            "results": [],
            "message": (
                f"Your wardrobe is empty! {title} pairs well with {pairing}. "
                "Add some pieces to your wardrobe and I can suggest a complete outfit."
            ),
        }

    # Duplicate check — can't style something the user already owns the same way
    wardrobe_ids = {item["id"] for item in items}
    if new_item.get("id") in wardrobe_ids:
        return {
            "duplicate": True,
            "message": (
                "It looks like you already own this item! Would you like me to:\n"
                "1. Style it using pieces you already own\n"
                "2. Find new pieces from listings that pair well with it"
            ),
        }

    # Determine which required categories are missing from the wardrobe
    # (new_item covers its own category)
    new_category = new_item.get("category", "")
    covered = {item["category"] for item in items} | {new_category}
    missing_categories = _REQUIRED_CATEGORIES - covered

    # Build a scored, human-readable wardrobe list for the prompt
    new_colors = {c.lower() for c in new_item.get("colors", [])}
    new_tags   = {t.lower() for t in new_item.get("style_tags", [])}

    def _score(item: dict) -> int:
        color_overlap = len(new_colors & {c.lower() for c in item.get("colors", [])})
        tag_overlap   = len(new_tags   & {t.lower() for t in item.get("style_tags", [])})
        return color_overlap * 2 + tag_overlap

    sorted_items = sorted(items, key=_score, reverse=True)
    wardrobe_lines = "\n".join(
        f"  - ID: {it['id']} | {it['name']} | category: {it['category']} "
        f"| colors: {', '.join(it.get('colors', []))} "
        f"| tags: {', '.join(it.get('style_tags', []))}"
        for it in sorted_items
    )

    prompt = _OUTFIT_PROMPT.format(
        title=new_item.get("title", new_item.get("name", "Unknown")),
        category=new_category,
        colors=", ".join(new_item.get("colors", [])),
        tags=", ".join(new_item.get("style_tags", [])),
        description=new_item.get("description", ""),
        wardrobe_lines=wardrobe_lines,
    )

    client = _get_groq_client()
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences if the model included them
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw

    try:
        outfit_list = json.loads(raw)
    except json.JSONDecodeError:
        return {"results": [], "message": f"Could not parse outfit suggestions from LLM: {raw}"}

    # Resolve piece IDs to actual wardrobe item dicts
    id_to_item = {item["id"]: item for item in items}
    results = []
    for outfit in outfit_list:
        pieces = [id_to_item[pid] for pid in outfit.get("piece_ids", []) if pid in id_to_item]
        results.append({
            "outfit_id": outfit.get("outfit_id", len(results) + 1),
            "pieces": pieces,
            "notes": outfit.get("notes", ""),
        })

    if missing_categories:
        missing_str = " and ".join(sorted(missing_categories))
        return {
            "results": results,
            "message": f"No {missing_str} found in wardrobe to complete this outfit.",
        }

    return {"results": results}


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

_FIT_CARD_PROMPT = """\
You write short, casual Instagram captions for thrift-store outfit posts.

The star of the outfit is a thrifted item:
- Title: {title}
- Price: {price}
- Platform: {platform}
- Colors: {colors}
- Style: {tags}
- Description: {description}

The full outfit also includes:
{pieces_lines}

Outfit vibe (from the stylist): {notes}

Write ONE caption for this OOTD post. Rules:
- Casual, first-person, like a real person posting — not a product description
- Mention the item name (or a natural shorthand), price, and platform once each
- Capture the specific vibe of this outfit in concrete terms
- 2–4 sentences max, no hashtags
- Vary your phrasing — do not start with "just" or "found"
"""

_INCOMPLETE_OUTFIT_MSG = (
    "Outfit is incomplete — missing at least one of: top, bottom, or shoes. "
    "Caption generation skipped."
)


def create_fit_card(outfit: dict, new_item: dict) -> str:
    """
    Generate a short, shareable Instagram-style caption for a completed outfit.

    Args:
        outfit:   A single outfit dict from suggest_outfit() with 'pieces' and 'notes'.
                  Must be a non-empty dict — if an empty string or non-dict is passed,
                  returns an error message string without crashing.
        new_item: The listing dict for the thrifted item the outfit is built around.

    Returns:
        A casual 2–4 sentence caption string.
        An error message string if outfit is incomplete or invalid — does NOT raise.
    """
    if not outfit or not isinstance(outfit, dict):
        return (
            "Unable to generate a fit card — the outfit is incomplete or missing "
            "required pieces. Please complete the outfit first."
        )

    pieces = outfit.get("pieces", [])

    # Guard: outfit must cover the three required categories
    piece_categories = {p.get("category", "") for p in pieces}
    # new_item fills its own category
    piece_categories.add(new_item.get("category", ""))
    missing = _REQUIRED_CATEGORIES - piece_categories
    if missing:
        return _INCOMPLETE_OUTFIT_MSG

    # Format the supporting pieces (everything except new_item)
    new_item_id = new_item.get("id", "")
    supporting = [p for p in pieces if p.get("id") != new_item_id]
    if supporting:
        pieces_lines = "\n".join(
            f"  - {p.get('name', p.get('title', 'Unknown'))} "
            f"({p.get('category', '')}, {', '.join(p.get('colors', []))})"
            for p in supporting
        )
    else:
        pieces_lines = "  (no additional pieces listed)"

    price = new_item.get("price")
    price_str = f"${price:.0f}" if price is not None else "unknown price"

    prompt = _FIT_CARD_PROMPT.format(
        title=new_item.get("title", new_item.get("name", "Unknown item")),
        price=price_str,
        platform=new_item.get("platform", "an online thrift store"),
        colors=", ".join(new_item.get("colors", [])) or "unknown",
        tags=", ".join(new_item.get("style_tags", [])) or "unknown",
        description=new_item.get("description", ""),
        pieces_lines=pieces_lines,
        notes=outfit.get("notes", ""),
    )

    client = _get_groq_client()
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=1.1,
    )
    return response.choices[0].message.content.strip()
