"""
Standalone recipe scraper — called by GitHub Actions import-recipe workflow.
Usage:
  python tools/importer/scrape.py \
    --url "https://..." \
    --tags "chicken quick" \
    --season "fall winter" \
    --rating 4 \
    --difficulty medium \
    --kid_friendly false
Writes _recipes/<slug>.md and images/<slug>.<ext> relative to the repo root.

Fetching: many recipe sites (The Kitchn, Serious Eats, Allrecipes, …) answer
plain `requests` calls from datacenter IPs with 403/402, so pages are fetched
with curl_cffi, which presents a real browser's TLS fingerprint. Parsing uses
recipe-scrapers (works on any site that publishes schema.org Recipe data), with
a small JSON-LD reader as a fallback.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
import yaml

try:
    from recipe_scrapers import scrape_html
except ImportError:
    print("recipe-scrapers not installed", file=sys.stderr)
    sys.exit(1)

try:
    from curl_cffi import requests as browser_requests
except ImportError:  # still works for sites that don't block scripts
    browser_requests = None

REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # tools/importer/scrape.py → repo root

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
# Some sites reject one browser fingerprint but accept another, so try several
IMPERSONATIONS = ["chrome", "safari", "firefox"]


class ImportError_(Exception):
    """A problem worth showing the user as-is."""


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text


def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", str(text))
    text = text.replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def format_ingredients(ingredients) -> list:
    if isinstance(ingredients, str):
        ingredients = ingredients.split("\n")
    elif not isinstance(ingredients, list):
        ingredients = []
    return [clean_text(i) for i in ingredients if clean_text(i)]


def format_instructions(instructions) -> list:
    if isinstance(instructions, str):
        instructions = instructions.split("\n")
    elif not isinstance(instructions, list):
        instructions = []
    cleaned = []
    for step in instructions:
        step = clean_text(step)
        step = re.sub(r"^(\d+[\.\)]\s+|-\s+|\*\s+)", "", step)
        if step:
            cleaned.append(step)
    return cleaned


def guess_tags(title: str) -> list:
    title_lower = title.lower()
    tag_map = {
        "vegetarian": ["vegetarian"], "vegan": ["vegan"],
        "gluten-free": ["gluten-free"], "chicken": ["chicken"],
        "beef": ["beef"], "pork": ["pork"], "turkey": ["turkey"],
        "fish": ["fish", "seafood"], "salmon": ["fish", "seafood"],
        "shrimp": ["seafood"], "pasta": ["pasta"], "lasagna": ["pasta"],
        "soup": ["soup"], "stew": ["stew"], "salad": ["salad"],
        "dessert": ["dessert"], "cake": ["dessert", "baking"],
        "cookie": ["dessert", "baking"], "bread": ["bread", "baking"],
        "pizza": ["pizza"], "taco": ["mexican"], "curry": ["curry"],
    }
    tags: set = set()
    for keyword, tag_list in tag_map.items():
        if keyword in title_lower:
            tags.update(tag_list)
    return sorted(list(tags))


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def http_get(url: str, referer: str = ""):
    """GET with browser fingerprints. Returns (response, notes). Raises ImportError_."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    attempts = []

    if browser_requests is not None:
        for browser in IMPERSONATIONS:
            try:
                # curl_cffi sets matching browser headers itself; only add the referer
                resp = browser_requests.get(
                    url, impersonate=browser, timeout=30, allow_redirects=True,
                    headers={"Referer": referer} if referer else None,
                )
            except Exception as e:
                attempts.append(f"{browser}: {type(e).__name__}")
                continue
            if resp.status_code == 200:
                return resp
            attempts.append(f"{browser}: HTTP {resp.status_code}")

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp
        attempts.append(f"plain: HTTP {resp.status_code}")
    except Exception as e:
        attempts.append(f"plain: {type(e).__name__}")

    raise ImportError_(
        f"Could not download {url} ({'; '.join(attempts)}). "
        "The site may block automated requests or require a login."
    )


def fetch_html(url: str) -> str:
    resp = http_get(url)
    if "text/html" not in resp.headers.get("content-type", "text/html") and not resp.text.lstrip().startswith("<"):
        raise ImportError_(f"{url} did not return a web page")
    return resp.text


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_duration_minutes(value):
    """'PT1H20M' → 80, 45 → 45, '45 minutes' → 45."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value) or None
    s = str(value).strip()
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:\d+S)?", s, re.I)
    if m and any(m.groups()):
        d, h, mi = (int(g) if g else 0 for g in m.groups())
        return (d * 24 + h) * 60 + mi or None
    m = re.match(r"\s*(\d+)", s)
    return int(m.group(1)) if m else None


def _flatten_ld(node):
    if isinstance(node, list):
        for item in node:
            yield from _flatten_ld(item)
    elif isinstance(node, dict):
        yield node
        yield from _flatten_ld(node.get("@graph", []))


def _ld_steps(instr) -> list:
    steps = []
    if isinstance(instr, str):
        return [s for s in re.split(r"\n+", instr) if s.strip()]
    if isinstance(instr, dict):
        instr = [instr]
    for item in instr or []:
        if isinstance(item, str):
            steps.append(item)
        elif isinstance(item, dict):
            if "itemListElement" in item:
                steps.extend(_ld_steps(item["itemListElement"]))
            elif item.get("text") or item.get("name"):
                steps.append(item.get("text") or item.get("name"))
    return steps


def _ld_image(img) -> str:
    if isinstance(img, list):
        img = img[0] if img else ""
    if isinstance(img, dict):
        img = img.get("url", "")
    return img if isinstance(img, str) else ""


def parse_json_ld(html: str):
    """Minimal schema.org Recipe reader for pages recipe-scrapers rejects."""
    for block in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I
    ):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for node in _flatten_ld(data):
            types = node.get("@type")
            types = [types] if isinstance(types, str) else (types or [])
            if "Recipe" not in types:
                continue
            yield_ = node.get("recipeYield")
            if isinstance(yield_, list):
                yield_ = yield_[0] if yield_ else ""
            category = node.get("recipeCategory")
            cuisine = node.get("recipeCuisine")
            return {
                "title": clean_text(node.get("name", "")),
                "ingredients": node.get("recipeIngredient") or [],
                "instructions": _ld_steps(node.get("recipeInstructions")),
                "image_url": _ld_image(node.get("image")),
                "yield": str(yield_ or ""),
                "prep_time": parse_duration_minutes(node.get("prepTime")),
                "cook_time": parse_duration_minutes(node.get("cookTime")),
                "total_time": parse_duration_minutes(node.get("totalTime")),
                "category": ", ".join(category) if isinstance(category, list) else (category or ""),
                "cuisine": ", ".join(cuisine) if isinstance(cuisine, list) else (cuisine or ""),
            }
    return None


def parse_with_scrapers(html: str, url: str):
    scraper = scrape_html(html, url, supported_only=False)
    data: dict = {
        "title": scraper.title(),
        "ingredients": scraper.ingredients(),
        "instructions": "",
        "image_url": "",
    }
    try:
        data["instructions"] = scraper.instructions_list()
    except Exception:
        data["instructions"] = scraper.instructions()
    for method_name, key_name in [
        ("yields", "yield"), ("total_time", "total_time"),
        ("prep_time", "prep_time"), ("cook_time", "cook_time"),
        ("category", "category"), ("cuisine", "cuisine"),
    ]:
        try:
            val = getattr(scraper, method_name)()
            if val:
                data[key_name] = str(val)
        except Exception:
            pass
    try:
        data["image_url"] = scraper.image()
    except Exception:
        pass
    return data


def fetch_recipe(url: str) -> dict:
    html = fetch_html(url)
    data, errors = None, []

    try:
        data = parse_with_scrapers(html, url)
    except Exception as e:
        errors.append(f"recipe-scrapers: {type(e).__name__}: {e}")

    def usable(d):
        return d and d.get("title") and format_ingredients(d.get("ingredients")) \
            and format_instructions(d.get("instructions"))

    if not usable(data):
        fallback = parse_json_ld(html)
        if usable(fallback):
            data = fallback
        elif fallback and not data:
            data = fallback

    if not data or not data.get("title"):
        raise ImportError_(
            "No recipe found on that page"
            + (f" ({'; '.join(errors)})" if errors else "")
            + ". It may not publish structured recipe data, or it may be behind a paywall."
        )
    if not format_ingredients(data.get("ingredients")):
        raise ImportError_(f"Found “{data['title']}” but no ingredients — the page is probably paywalled or not a recipe.")
    if not format_instructions(data.get("instructions")):
        raise ImportError_(f"Found “{data['title']}” but no directions — the page is probably paywalled or not a recipe.")

    for key in ("prep_time", "cook_time", "total_time"):
        if data.get(key):
            data[key] = str(parse_duration_minutes(data[key]) or data[key])
    if not data.get("total_time") and data.get("prep_time") and data.get("cook_time"):
        try:
            data["total_time"] = str(int(data["prep_time"]) + int(data["cook_time"]))
        except ValueError:
            pass
    return data


# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------

def sniff_extension(content: bytes) -> str:
    if content[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    if content[:4] == b"GIF8":
        return ".gif"
    return ""


def download_image(image_url: str, source_url: str, images_dir: Path, slug: str) -> str:
    """Save the image as images/<slug>.<real ext>. Returns the filename, or '' on failure."""
    if not image_url:
        return ""
    if image_url.startswith("//"):
        image_url = f"{urlparse(source_url).scheme}:{image_url}"
    elif not image_url.startswith("http"):
        image_url = urljoin(source_url, image_url)
    try:
        resp = http_get(image_url, referer=source_url)
        content = resp.content
        ext = sniff_extension(content)
        if not ext or len(content) < 1024:
            print("Image download failed: response was not an image", file=sys.stderr)
            return ""
        images_dir.mkdir(parents=True, exist_ok=True)
        name = f"{slug}{ext}"
        (images_dir / name).write_bytes(content)
        return name
    except Exception as e:
        print(f"Image download failed: {e}", file=sys.stderr)
        return ""


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def build_markdown(data: dict, image_ref: str, user_tags: list,
                   season: str, rating, difficulty: str, kid_friendly: bool,
                   source_url: str = "") -> str:
    auto_tags = guess_tags(data["title"])
    all_tags = sorted(list(set(auto_tags + (user_tags or []))))
    season_list = (
        [s.strip() for s in season.replace(",", " ").split() if s.strip()]
        if season and season.strip().lower() != "all"
        else ["all"]
    )
    fm = {
        "layout": "recipe",
        "title": data.get("title", "Untitled Recipe"),
        "image": image_ref,
        "tags": all_tags,
        "ingredients": format_ingredients(data.get("ingredients", [])),
        "directions": format_instructions(data.get("instructions", [])),
        "date_added": date.today(),
        "season": season_list,
        "last_made": None,
        "rating": rating,
        "difficulty": difficulty,
        "kid_friendly": kid_friendly,
    }
    for key in ["yield", "prep_time", "cook_time", "total_time", "category", "cuisine"]:
        if key in data and data[key]:
            fm[key] = data[key]
    if source_url:
        fm["source"] = source_url
    yaml_content = yaml.dump(fm, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120)
    return f"---\n{yaml_content}---\n"


def unique_slug(recipes_dir: Path, slug: str) -> str:
    candidate, n = slug, 2
    while (recipes_dir / f"{candidate}.md").exists():
        candidate = f"{slug}-{n}"
        n += 1
    return candidate


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scrape a recipe URL and write markdown")
    parser.add_argument("--url", required=True)
    parser.add_argument("--tags", default="")
    parser.add_argument("--season", default="all")
    parser.add_argument("--rating", default="")
    parser.add_argument("--difficulty", default="easy")
    parser.add_argument("--kid_friendly", default="false")
    args = parser.parse_args()

    url = args.url.strip()
    if not re.match(r"^https?://", url):
        print("ERROR: URL must start with http:// or https://", file=sys.stderr)
        sys.exit(1)

    user_tags = [t.strip() for t in args.tags.split() if t.strip()]
    rating_int = (
        int(args.rating)
        if args.rating.strip().isdigit() and 1 <= int(args.rating.strip()) <= 5
        else None
    )
    kid_bool = args.kid_friendly.lower() in ("true", "1", "yes", "on")
    difficulty_clean = (
        args.difficulty.strip().lower()
        if args.difficulty.strip().lower() in ("easy", "medium", "hard")
        else "easy"
    )

    print(f"Fetching recipe from {url}…")
    try:
        data = fetch_recipe(url)
    except ImportError_ as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to import recipe: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

    title = clean_text(data["title"])
    data["title"] = title
    print(f"Scraped: {title} — {len(format_ingredients(data['ingredients']))} ingredients, "
          f"{len(format_instructions(data['instructions']))} steps")

    recipes_dir = REPO_ROOT / "_recipes"
    recipes_dir.mkdir(exist_ok=True)
    slug = unique_slug(recipes_dir, slugify(title) or "recipe")
    if slug != slugify(title):
        print(f"A recipe called “{title}” already exists — saving as {slug}")

    image_ref = download_image(data.get("image_url", ""), url, REPO_ROOT / "images", slug)
    print(f"Image saved: {image_ref}" if image_ref else "No image — recipe will have no image")

    md_content = build_markdown(
        data, image_ref, user_tags,
        season=args.season, rating=rating_int,
        difficulty=difficulty_clean, kid_friendly=kid_bool,
        source_url=url,
    )
    out_path = recipes_dir / f"{slug}.md"
    out_path.write_text(md_content, encoding="utf-8")
    print(f"Written: _recipes/{slug}.md")


if __name__ == "__main__":
    main()
