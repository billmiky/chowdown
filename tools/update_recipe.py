#!/usr/bin/env python3
"""Apply edits from the recipe page's Edit form to a recipe's front matter.

Usage: python3 tools/update_recipe.py <slug> '<json of changed fields>'

Only the fields listed in FIELDS can be changed, and only the ones present in the
JSON are touched. The recipe body (anything after the front matter) is left alone.
Exits non-zero, without writing anything, if a value is invalid.
"""
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DIFFICULTIES = {"easy", "medium", "hard"}
SEASONS = {"all", "spring", "summer", "fall", "winter"}
FRONT_MATTER = re.compile(r"^---\n(.*?)\n---[ \t]*(?:\n|$)", re.S)

# kind: text | minutes | choice | bool | lines | seasons
# Optional fields are removed from the front matter when saved empty.
FIELDS = {
    "title": ("text", False),
    "ingredients": ("lines", False),
    "directions": ("lines", False),
    "prep_time": ("minutes", True),
    "cook_time": ("minutes", True),
    "total_time": ("minutes", True),
    "yield": ("text", True),
    "difficulty": ("choice", True),
    "kid_friendly": ("bool", False),
    "season": ("seasons", False),
    "tags": ("lines", True),
    "category": ("text", True),
    "cuisine": ("text", True),
}


class Invalid(Exception):
    pass


def clean(key, kind, optional, value):
    """Return the cleaned value, or None to drop an optional key."""
    if kind == "bool":
        if not isinstance(value, bool):
            raise Invalid(f"'{key}' must be true or false")
        return value

    if kind in ("lines", "seasons"):
        if isinstance(value, str):
            value = value.splitlines()
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise Invalid(f"'{key}' must be a list of text")
        items = [v.strip() for v in value if v.strip()]
        if kind == "seasons":
            bad = [s for s in items if s not in SEASONS]
            if bad:
                raise Invalid(f"unknown season(s) {bad}")
            return items or ["all"]
        if not items:
            if optional:
                return None
            raise Invalid(f"'{key}' can't be empty")
        return items

    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise Invalid(f"'{key}' must be text")
    text = str(value).strip()
    if not text:
        if optional:
            return None
        raise Invalid(f"'{key}' can't be empty")
    if kind == "minutes":
        if not re.fullmatch(r"\d{1,4}", text):
            raise Invalid(f"'{key}' must be a whole number of minutes")
        return str(int(text))
    if kind == "choice":
        text = text.lower()
        if text not in DIFFICULTIES:
            raise Invalid(f"'{key}' must be one of {sorted(DIFFICULTIES)}")
    return text


def apply(slug, changes):
    if not slug or "/" in slug or "\\" in slug or slug.startswith("."):
        raise Invalid(f"invalid recipe name '{slug}'")
    path = ROOT / "_recipes" / f"{slug}.md"
    if not path.is_file():
        raise Invalid(f"{path.relative_to(ROOT)} not found")
    if not isinstance(changes, dict) or not changes:
        raise Invalid("no changes given")
    unknown = sorted(set(changes) - set(FIELDS))
    if unknown:
        raise Invalid(f"can't edit field(s) {unknown}")

    text = path.read_text(encoding="utf-8")
    m = FRONT_MATTER.match(text)
    if not m:
        raise Invalid("could not parse front matter")
    fm = yaml.safe_load(m.group(1)) or {}
    body = text[m.end():]
    before = dict(fm)

    for key, value in changes.items():
        kind, optional = FIELDS[key]
        cleaned = clean(key, kind, optional, value)
        if cleaned is None:
            fm.pop(key, None)
        else:
            fm[key] = cleaned

    if fm == before:
        print("No changes to save")
        return path, False

    dumped = yaml.dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False, width=10_000)
    path.write_text(f"---\n{dumped}---\n{body}", encoding="utf-8")
    print(f"Updated {', '.join(sorted(changes))} in {path.relative_to(ROOT)}")
    return path, True


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    try:
        apply(argv[1], json.loads(argv[2]))
    except json.JSONDecodeError as e:
        print(f"ERROR: changes are not valid JSON: {e}")
        return 1
    except Invalid as e:
        print(f"ERROR: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
