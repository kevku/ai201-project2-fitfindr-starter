# tests/test_tools.py
import pytest
from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import load_listings, get_example_wardrobe, get_empty_wardrobe


# ── Shared fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def listings():
    return load_listings()

@pytest.fixture(scope="module")
def wardrobe():
    return get_example_wardrobe()

@pytest.fixture(scope="module")
def new_item(listings):
    return listings[0]  # Vintage Levi's 501 Jeans — W30 L30, bottoms

@pytest.fixture(scope="module")
def outfit(new_item, wardrobe):
    return suggest_outfit(new_item, wardrobe)["results"][0]


# ── search_listings ────────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0

def test_search_empty_results():
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []

def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)

def test_search_return_is_bare_list():
    results = search_listings("vintage tee", "S/M", 50.0)
    assert isinstance(results, list)

def test_search_size_none_skips_filter():
    results = search_listings("vintage tee", None, 50.0)
    assert len(results) > 0

def test_search_at_most_three_results():
    results = search_listings("top shirt tee blouse", "S/M", 200.0)
    assert len(results) <= 3

def test_search_size_is_hard_filter():
    results = search_listings("vintage top", "M", 200.0)
    assert all(item["size"].lower() == "m" for item in results)

def test_search_price_ceiling():
    results = search_listings("vintage shirt", "M", 20.0)
    assert all(item["price"] <= 20.0 for item in results)

def test_search_category_boost():
    # "shirt" keyword should infer tops — tops should rank first
    results = search_listings("green vintage shirt", "M", 200.0)
    assert len(results) > 0
    assert results[0]["category"] == "tops"

def test_search_color_boost():
    results = search_listings("green shirt", "M", 200.0)
    colors_in_results = [c.lower() for item in results for c in item.get("colors", [])]
    assert "green" in colors_in_results

def test_search_style_tag_boost():
    # "vintage" and "preppy" are tags on the Polo Shirt (size M)
    results = search_listings("vintage preppy polo shirt", "M", 200.0)
    titles = [item["title"] for item in results]
    assert any("Polo" in t for t in titles)

def test_search_required_fields():
    required = {"id", "title", "description", "category", "style_tags",
                "size", "condition", "price", "colors", "brand", "platform"}
    results = search_listings("boots shoes", "US 8.5", 200.0)
    for item in results:
        assert required <= item.keys()

def test_search_size_case_insensitive():
    upper = {item["id"] for item in search_listings("shirt", "M",   200.0)}
    lower = {item["id"] for item in search_listings("shirt", "m",   200.0)}
    assert upper == lower


# ── suggest_outfit ─────────────────────────────────────────────────────────────

def test_suggest_empty_wardrobe():
    results = suggest_outfit(load_listings()[0], get_empty_wardrobe())
    assert results["results"] == []
    assert "message" in results

def test_suggest_empty_wardrobe_message():
    r = suggest_outfit(load_listings()[0], get_empty_wardrobe())
    msg = r["message"].lower()
    assert "wardrobe" in msg or "search" in msg or "empty" in msg

def test_suggest_duplicate_item(wardrobe):
    # Use a wardrobe item as the new_item so it matches by id
    dupe = wardrobe["items"][0]
    r = suggest_outfit(dupe, wardrobe)
    assert r.get("duplicate") is True
    assert "1." in r["message"] and "2." in r["message"]
    assert "results" not in r

def test_suggest_normal_return_shape(new_item, wardrobe):
    r = suggest_outfit(new_item, wardrobe)
    assert isinstance(r, dict)
    assert "results" in r
    assert len(r["results"]) >= 1

def test_suggest_outfit_fields(new_item, wardrobe):
    r = suggest_outfit(new_item, wardrobe)
    for outfit in r["results"]:
        assert "outfit_id" in outfit
        assert isinstance(outfit["pieces"], list)
        assert isinstance(outfit["notes"], str)

def test_suggest_pieces_are_dicts(new_item, wardrobe):
    wardrobe_ids = {it["id"] for it in wardrobe["items"]}
    r = suggest_outfit(new_item, wardrobe)
    for outfit in r["results"]:
        for piece in outfit["pieces"]:
            assert isinstance(piece, dict)
            assert piece["id"] in wardrobe_ids

def test_suggest_missing_shoes_message(new_item, wardrobe):
    no_shoes = {"items": [it for it in wardrobe["items"] if it["category"] != "shoes"]}
    r = suggest_outfit(new_item, no_shoes)
    assert "results" in r
    assert "message" in r
    assert "shoes" in r["message"].lower()

def test_suggest_notes_nonempty(new_item, wardrobe):
    r = suggest_outfit(new_item, wardrobe)
    for outfit in r["results"]:
        assert outfit["notes"].strip() != ""


# ── create_fit_card ────────────────────────────────────────────────────────────

def test_fit_card_returns_string(outfit, new_item):
    caption = create_fit_card(outfit, new_item)
    assert isinstance(caption, str)
    assert len(caption.strip()) > 0

def test_fit_card_not_error_message(outfit, new_item):
    caption = create_fit_card(outfit, new_item)
    assert "incomplete" not in caption.lower()
    assert "skipped" not in caption.lower()

def test_fit_card_mentions_platform(outfit, new_item):
    caption = create_fit_card(outfit, new_item)
    assert new_item["platform"].lower() in caption.lower()

def test_fit_card_mentions_price(outfit, new_item):
    caption = create_fit_card(outfit, new_item)
    assert str(int(new_item["price"])) in caption

def test_fit_card_incomplete_outfit(new_item, outfit):
    # Remove shoes from pieces and make new_item a top so shoes are truly absent
    no_shoe_pieces = [p for p in outfit["pieces"] if p["category"] != "shoes"]
    incomplete = {"pieces": no_shoe_pieces, "notes": outfit["notes"]}
    top_item = {**new_item, "category": "tops"}
    result = create_fit_card(incomplete, top_item)
    assert isinstance(result, str)
    assert any(w in result.lower() for w in ("incomplete", "missing", "skipped"))

def test_fit_card_sparse_new_item(outfit):
    sparse = {
        "id": "lst_sparse",
        "title": "Vintage Denim Jacket",
        "category": "outerwear",
        "colors": ["blue"],
        "style_tags": ["vintage", "denim"],
        "description": "",
        # no price, no platform
    }
    result = create_fit_card(outfit, sparse)
    assert isinstance(result, str)
    assert len(result.strip()) > 0

def test_fit_card_varies_on_same_input(outfit, new_item):
    caption_a = create_fit_card(outfit, new_item)
    caption_b = create_fit_card(outfit, new_item)
    assert caption_a != caption_b
