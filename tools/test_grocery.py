#!/usr/bin/env python3
"""Checks for tools/grocery.py. Run: python3 tools/test_grocery.py"""
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grocery  # noqa: E402

SECTIONS = {
    "Meat & Fish": ["1 1/2 pounds boneless, skinless chicken thighs", "1 pound ground beef (round or chuck)"],
    "Dairy & Eggs": ["4 large eggs", "1/3 cup grated Parmesan", "½ cup plain whole-milk Greek yogurt or mayonnaise"],
    "Produce": ["1 pound (about ½ small) butternut squash, peeled", "1 red bell pepper, sliced", "1 jalapeño, chopped",
                "1 eggplant", "2 tablespoons fresh lemon juice", "1 handful fresh coriander (cilantro)", "1 (14-ounce) block tofu"],
    "Canned & Jarred": ["2 (15-ounce) cans full-fat coconut milk", "2 cups vegetable or chicken stock",
                        "2 tablespoons peanut butter", "1 (24-ounce) jar marinara sauce"],
    "Pantry & Staples": ["1/3 cup fish sauce", "1/4 cup rice vinegar", "1 tablespoon red-pepper flakes", "Salt and pepper",
                         "1 teaspoon ground coriander", "1 tablespoon cornstarch", "Chile oil or chile crisp, for serving",
                         "1 teaspoon dried thyme"],
    "Grains & Bread": ["6 cups/6 ounces cornflakes", "4 hamburger buns", "18 fresh or frozen rice cakes"],
    "Freezer": ["1 pound frozen, unthawed dumplings", "1 cup frozen peas"],
}

SAME = [
    ("1 teaspoon kosher salt, plus additional as needed", "1 teaspoon kosher salt (such as Diamond Crystal)"),
    ("3 garlic cloves, minced", "4 cloves garlic"),
    ("2 (15-ounce) cans chickpeas, drained and rinsed", "1 can (400g) chickpeas, drained and rinsed"),
    ("1 cup blueberries", "1 pint blueberry"),
]
DIFFERENT = [
    ("1 1/2 pounds boneless, skinless chicken thighs", "4 boneless, skinless chicken breasts"),
    ("3 tablespoons hot sauce", "1 tablespoon soy sauce"),
    ("Kosher salt and black pepper", "1 teaspoon kosher salt"),
]


def recipe(title, ingredients):
    fm = {"layout": "recipe", "title": title, "ingredients": ingredients, "directions": ["Cook."]}
    return "---\n" + yaml.dump(fm, allow_unicode=True) + "---\n"


def check_build():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "_recipes").mkdir()
        (root / "_data").mkdir()
        (root / "_recipes/a.md").write_text(recipe("Soup", ["3 garlic cloves, minced", "1 onion", "1 cup water"]), encoding="utf-8")
        (root / "_recipes/b.md").write_text(recipe("Stew", ["4 cloves garlic", "2 tablespoons olive oil"]), encoding="utf-8")
        (root / "_data/meal_plan.yml").write_text("week_of: '2026-10-26'\nmonday: a\ntuesday: b\nwednesday: ''\nfriday: missing\n")
        (root / "_data/pantry.yml").write_text("staples:\n- olive oil\n")
        (root / "_data/grocery_list.yml").write_text(yaml.dump({"categories": [
            {"name": "Produce", "items": ["old item"]},
            {"name": "Extras", "items": ["paper towels"]},
        ]}))
        data = grocery.build(root, today="2026-10-30")

    sections = {c["name"]: c for c in data["categories"]}
    assert data["week_of"] == "2026-10-30"
    produce = sections["Produce"]["items"]
    garlic = next(i for i in produce if i["name"].lower().startswith("garlic"))
    assert [u["recipe"] for u in garlic["uses"]] == ["Soup", "Stew"], garlic
    assert "old item" not in produce, "rebuild should replace generated sections"
    assert not any("water" in i["name"] for i in produce), "water is never on the list"
    assert sections["Pantry & Staples"]["have"][0]["name"] == "olive oil"
    assert "items" not in sections["Pantry & Staples"]
    assert sections["Extras"]["items"] == ["paper towels"], "hand-added items survive a rebuild"


def main():
    failures = []
    for expected, lines in SECTIONS.items():
        for line in lines:
            got = grocery.categorize(line)
            if got != expected:
                failures.append(f"categorize({line!r}) = {got!r}, expected {expected!r}")
    for a, b in SAME:
        if grocery.merge_key(a) != grocery.merge_key(b):
            failures.append(f"should merge: {a!r} ({grocery.merge_key(a)!r}) / {b!r} ({grocery.merge_key(b)!r})")
    for a, b in DIFFERENT:
        if grocery.merge_key(a) == grocery.merge_key(b):
            failures.append(f"should not merge: {a!r} / {b!r} (both {grocery.merge_key(a)!r})")
    try:
        check_build()
    except Exception as e:  # a missing section shows up as a KeyError
        failures.append(f"build: {type(e).__name__}: {e}")

    for f in failures:
        print("FAIL", f)
    print(f"{'FAILED' if failures else 'OK'}: grocery checks")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
