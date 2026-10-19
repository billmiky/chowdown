#!/usr/bin/env python3
"""Validate front matter of every recipe in _recipes/.

Exits non-zero if any recipe has an error. Warnings are printed but do not fail.
Usage: python3 tools/validate_recipes.py [recipe.md ...]
"""
import re
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ["title", "layout", "image", "date_added", "ingredients", "directions"]
DIFFICULTIES = {"easy", "medium", "hard"}
SEASONS = {"all", "spring", "summer", "fall", "winter"}


def load_front_matter(path):
    """Return (front matter dict, body text), or (None, text) if there is none."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---[ \t]*(?:\n|$)", text, re.S)
    if not m:
        return None, text
    return yaml.safe_load(m.group(1)) or {}, text[m.end():]


def check(path):
    errors, warnings = [], []
    try:
        fm, body = load_front_matter(path)
    except yaml.YAMLError as e:
        return [f"invalid YAML: {e}"], []
    if fm is None:
        return ["missing front matter"], []

    for key in REQUIRED:
        if fm.get(key) in (None, "", []):
            # Component-based or prose recipes carry these elsewhere.
            if key in ("ingredients", "directions") and (
                fm.get("components") or re.search(rf"^#+\s*{key}\b", body, re.I | re.M)
            ):
                continue
            errors.append(f"missing '{key}'")

    image = fm.get("image")
    if image and not (ROOT / "images" / str(image)).is_file():
        warnings.append(f"image 'images/{image}' not found")

    for key in ("ingredients", "directions"):
        val = fm.get(key)
        if val is not None and not (isinstance(val, list) and all(isinstance(v, str) and v.strip() for v in val)):
            errors.append(f"'{key}' must be a list of non-empty strings")

    if not isinstance(fm.get("date_added"), (date, datetime)):
        errors.append("'date_added' must be a YYYY-MM-DD date")

    rating = fm.get("rating")
    if rating is not None and (not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5):
        errors.append("'rating' must be an integer 1-5 or null")

    difficulty = fm.get("difficulty")
    if difficulty is not None and difficulty not in DIFFICULTIES:
        errors.append(f"'difficulty' must be one of {sorted(DIFFICULTIES)}")

    season = fm.get("season")
    if season is not None:
        seasons = season if isinstance(season, list) else [season]
        bad = [s for s in seasons if s not in SEASONS]
        if bad:
            errors.append(f"unknown season(s) {bad}")

    last_made = fm.get("last_made")
    if last_made is not None and not isinstance(last_made, (date, datetime)):
        errors.append("'last_made' must be a YYYY-MM-DD date or null")

    if not fm.get("tags"):
        warnings.append("no 'tags'")
    if not (fm.get("yield") or fm.get("yields") or fm.get("servings")):
        warnings.append("no yield/servings")
    if "yields" in fm:
        warnings.append("'yields' is non-standard, use 'yield'")
    return errors, warnings


def main(argv):
    paths = [Path(a) for a in argv] or sorted((ROOT / "_recipes").glob("*.md"))
    failed = 0
    for path in paths:
        errors, warnings = check(path)
        for msg in errors:
            print(f"ERROR   {path.name}: {msg}")
        for msg in warnings:
            print(f"warning {path.name}: {msg}")
        failed += bool(errors)
    print(f"\n{len(paths)} recipes checked, {failed} with errors")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
