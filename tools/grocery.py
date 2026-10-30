#!/usr/bin/env python3
"""Build _data/grocery_list.yml from this week's meal plan.

Usage: python3 tools/grocery.py

Ingredients are sorted into store sections, duplicates across recipes are merged
(each keeps the line and the recipe it came from), and anything the pantry says
you already have goes under `have`. Sections people add to by hand (EXTRA_SECTIONS)
are carried over from the existing list so a rebuild doesn't wipe them.

List format:
  week_of: '2026-10-26'
  categories:
  - name: Produce
    items:                      # to buy
    - name: garlic
      uses:
      - {text: 3 garlic cloves, minced, recipe: Dakgalbi}
    have: [...]                 # same shape, already on hand
Items in the extra sections may also be plain strings.
"""
import re
import unicodedata
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
EXTRA_SECTIONS = ["Extras", "Pantry Needs"]
CATCHALL = "Other"

HERBS = ["basil", "thyme", "rosemary", "sage", "dill", "oregano", "mint", "parsley",
         "tarragon", "chive", "marjoram", "cilantro"]

# Each keyword matches whole words (an "s"/"es" plural is allowed). When several
# keywords match, the longest wins, so "fish sauce" beats "fish" and
# "coconut milk" beats "milk". Ties go to the section listed first.
CATEGORIES = [
    ("Freezer", ["frozen"]),
    ("Meat & Fish", [
        "chicken", "beef", "pork", "lamb", "turkey", "sausage", "bacon", "ham",
        "shrimp", "prawn", "salmon", "tuna", "cod", "fish", "seafood", "anchovy", "anchovies",
        "crab", "lobster", "mussel", "scallop", "prosciutto", "pancetta", "chorizo",
        "steak", "thigh", "breast", "wing", "drumstick", "tenderloin", "brisket",
        "loin", "cutlet", "fillet", "filet", "halibut", "tilapia", "flounder",
        "trout", "sardine", "mackerel", "duck", "meatball", "ground meat",
    ]),
    ("Dairy & Eggs", [
        "milk", "heavy cream", "whipping cream", "half-and-half", "half and half",
        "butter", "cheese", "yogurt", "egg", "sour cream", "cream cheese",
        "parmesan", "parmigiano", "mozzarella", "cheddar", "feta", "ricotta", "mascarpone",
        "brie", "gouda", "gruyere", "goat cheese", "cottage cheese", "ghee",
        "creme fraiche", "cream", "buttermilk", "paneer", "halloumi", "pecorino",
        "greek yogurt",
    ]),
    ("Grains & Bread", [
        "pasta", "rice", "noodle", "bread", "flour", "oats", "rolled oats",
        "quinoa", "tortilla", "pita", "farro", "barley", "bulgur", "couscous",
        "cracker", "panko", "bread crumb", "breadcrumb", "cornmeal", "polenta",
        "linguine", "spaghetti", "fettuccine", "rigatoni", "penne", "fusilli",
        "orzo", "udon", "ramen", "soba", "vermicelli", "lasagna", "lasagna noodle",
        "dumpling", "cornflakes", "lavash", "flatbread", "bun", "baguette", "naan",
        "filo", "phyllo", "puff pastry", "rice cake", "tteok", "wonton wrapper", "gnocchi",
    ]),
    ("Canned & Jarred", [
        "canned", "chickpea", "lentil", "black bean", "kidney bean", "white bean",
        "navy bean", "pinto bean", "cannellini", "coconut milk", "coconut cream",
        "tomato paste", "diced tomatoes", "crushed tomatoes", "whole tomatoes",
        "tomato sauce", "passata", "marinara",
        "stock", "broth", "chicken stock", "chicken broth", "beef stock", "beef broth",
        "vegetable stock", "vegetable broth", "bouillon",
        "olives", "capers", "tahini", "miso", "sun-dried tomatoes", "chutney", "salsa",
        "chipotles in adobo", "chipotle in adobo", "adobo sauce", "kimchi", "pickle",
        "artichoke hearts", "roasted red peppers", "jam", "peanut butter",
        "curry paste", "doenjang", "ssamjang", "nutella",
    ]),
    ("Pantry & Staples", [
        "garlic powder", "onion powder", "chili powder", "chile powder", "curry powder",
        "red pepper flakes", "red-pepper flakes", "black pepper", "white pepper",
        "peppercorn", "kosher salt", "sea salt", "flaky salt", "cream of tartar",
        "olive oil", "sesame oil", "vegetable oil", "canola oil", "coconut oil", "neutral oil",
        "peanut oil", "avocado oil", "baking powder", "baking soda", "vanilla extract", "vanilla",
        "soy sauce", "fish sauce", "hot sauce", "oyster sauce", "hoisin sauce", "hoisin",
        "sriracha", "gochujang", "gochugaru", "worcestershire", "sambal", "harissa",
        "rice vinegar", "apple cider vinegar", "balsamic vinegar", "wine vinegar",
        "maple syrup", "corn syrup", "oil", "vinegar", "salt", "pepper", "sugar", "honey",
        "mustard", "dijon", "ketchup", "mayonnaise", "mayo", "cumin", "turmeric",
        "paprika", "coriander", "cinnamon", "cayenne", "bay leaf", "bay leaves", "nutmeg",
        "cardamom", "clove", "allspice", "garam masala", "za'atar", "sumac", "oregano",
        "yeast", "cornstarch", "molasses", "tamari", "mirin", "sake", "cooking wine",
        "extract", "seasoning", "spice", "powder", "flakes", "chocolate", "cocoa",
        "sesame seeds", "nuts", "almonds", "walnuts", "pecans", "peanuts", "pistachios",
        "cashews", "raisins", "breadcrumbs", "ground ginger", "coriander seeds",
        "chile oil", "chili oil", "chile crisp", "chili crisp", "caraway seeds", "kombu",
        "cumin seeds", "fennel seeds", "mustard seeds",
    ] + [f"dried {h}" for h in HERBS]),
    ("Produce", [
        "apple", "banana", "strawberry", "strawberries", "blueberry", "blueberries",
        "raspberry", "raspberries", "blackberry", "blackberries", "berry", "berries",
        "lemon", "lime", "orange", "mango", "avocado", "lemon juice", "lime juice",
        "lemon zest", "lime zest", "tomato", "tomatoes", "onion", "garlic", "ginger",
        "carrot", "celery", "potato", "potatoes", "kale", "spinach", "lettuce", "arugula",
        "cucumber", "zucchini", "bell pepper", "chile", "chili", "chiles", "jalapeno",
        "serrano", "poblano", "habanero", "thai chile", "broccoli", "broccolini",
        "broccoli rabe", "cauliflower", "mushroom", "corn", "shallot", "scallion",
        "green onion", "leek", "chard", "collard", "cabbage", "beet", "parsnip",
        "squash", "butternut", "butternut squash", "eggplant", "fennel", "asparagus",
        "fresh coriander", "greens", "bok choy", "peach", "plum", "pear", "grape",
        "cherry", "cherries", "pineapple", "melon", "watermelon", "fig", "radish",
        "turnip", "artichoke", "watercress", "endive", "sweet potato", "sweet potatoes",
        "snap pea", "snow pea", "peas", "edamame", "tomatillo", "bean sprout",
        "green beans", "brussels sprouts", "lemongrass", "tofu", "fresh ginger", "curry leaves",
    ] + HERBS),
]

# Lines that never need buying
SKIP = {"water", "ice", "warm water", "cold water", "hot water", "boiling water", "ice water"}

STOP_WORDS = {"the", "and", "for", "with", "from", "est", "org", "organic",
              "per", "each", "pack", "count", "size", "box", "bag", "can"}

# Words dropped when working out whether two ingredient lines are the same thing
UNITS = {"teaspoon", "teaspoons", "tsp", "tablespoon", "tablespoons", "tbsp", "cup", "cups",
         "ounce", "ounces", "oz", "pound", "pounds", "lb", "lbs", "gram", "grams", "g", "kg",
         "ml", "l", "liter", "liters", "quart", "quarts", "pint", "pints", "pinch", "dash",
         "clove", "cloves", "can", "cans", "jar", "jars", "package", "packages", "bunch",
         "bunches", "handful", "head", "heads", "stalk", "stalks", "sprig", "sprigs",
         "slice", "slices", "piece", "pieces", "stick", "sticks", "thumb", "knob", "inch",
         "tin", "tins", "block", "blocks", "container", "containers", "bottle", "bottles"}
DESCRIPTORS = {"large", "small", "medium", "fresh", "freshly", "packed", "heaping", "level",
               "about", "plus", "more", "to", "taste", "of", "a", "an", "whole", "extra",
               "finely", "roughly", "coarsely", "thinly", "chopped", "minced", "diced",
               "sliced", "grated", "divided", "optional", "or", "and", "good", "quality",
               "tightly", "loosely", "lightly", "very", "room",
               "temperature", "softened", "melted", "peeled", "trimmed", "rinsed", "drained",
               "as", "needed", "such", "serving", "garnish", "unsalted", "toasted", "raw",
               "boneless", "skinless", "bone-in", "skin-on", "x"}


def plain(text):
    """Lowercase ASCII (jalapeño -> jalapeno) with single spaces."""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.lower()).strip()


def _pattern(keyword):
    return re.compile(r"(?<![a-z])" + re.escape(keyword) + r"(?:s|es)?(?![a-z])")


_KEYWORDS = [(len(kw), -order, name, _pattern(kw))
             for order, (name, kws) in enumerate(CATEGORIES) for kw in kws]


def categorize(ingredient):
    s = plain(ingredient)
    # "fresh or frozen" means either works, so it says nothing about the aisle;
    # otherwise "frozen" (frozen dumplings, frozen peas) means the freezer.
    s = re.sub(r"fresh or frozen|frozen or fresh|or frozen", " ", s)
    if re.search(r"(?<![a-z])frozen(?![a-z])", s):
        return "Freezer"
    best = None
    for length, rank, name, pattern in _KEYWORDS:
        if pattern.search(s) and (best is None or (length, rank) > best[:2]):
            best = (length, rank, name)
    return best[2] if best else CATCHALL


def _words(ingredient):
    """The words that name an ingredient, without amounts, units or prep notes.

    Takes the first comma-separated part that names something, so
    '1 1/2 pounds boneless, skinless chicken thighs' gives ['chicken', 'thighs']
    rather than stopping at 'boneless'.
    """
    text = re.sub(r"\([^)]*\)", " ", str(ingredient))
    for part in re.split(r",|;| – | - | for serving| to serve", text):
        words = part.split()
        # Drop leading amounts, units and descriptors ("6 cups/6 ounces", "about 2")
        while words and all(not re.search(r"[a-z]", plain(piece))
                            or re.sub(r"[^a-z'-]", "", plain(piece)) in UNITS | DESCRIPTORS
                            for piece in words[0].split("/")):
            words.pop(0)
        if words:
            return words
    return [str(ingredient).strip()]


def merge_key(ingredient):
    """'1 teaspoon kosher salt (such as Diamond Crystal)' -> 'kosher salt'."""
    words = re.findall(r"[a-z']+", plain(" ".join(_words(ingredient))))
    words = [w for w in words if w not in UNITS and w not in DESCRIPTORS] or words
    return " ".join(_singular(w) for w in words)


def _singular(word):
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def display_name(ingredient):
    """Readable name for an item, e.g. '6 cups/6 ounces cornflakes' -> 'cornflakes'."""
    return " ".join(_words(ingredient))


def pantry_terms(pantry):
    terms = []
    for s in pantry.get("staples") or []:
        term = plain(s)
        if term:
            terms.append(term)
    # on_hand comes from receipts, so take the first meaningful words of each line
    for entry in pantry.get("on_hand") or []:
        text = entry.get("item", "") if isinstance(entry, dict) else str(entry)
        clean = re.split(r"\s+\d", text)[0]
        clean = re.sub(r"[^a-z\s'-]", " ", plain(clean)).strip()
        words = [w for w in clean.split() if len(w) > 2 and w not in STOP_WORDS]
        if len(words) >= 3:
            terms.append(" ".join(words[:3]))
        if len(words) >= 2:
            terms.append(" ".join(words[:2]))
        if words:
            terms.append(words[0])
    return terms


def is_on_hand(ingredient, terms):
    s = " " + plain(ingredient) + " "
    for term in terms:
        if " " in term:
            if term in s:
                return True
        elif re.search(r"\b" + re.escape(term) + r"\b", s):
            return True
    return False


def read_front_matter(path):
    m = re.match(r"^---\n(.*?)\n---", path.read_text(encoding="utf-8"), re.S)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}


def load_yaml(path):
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def build(root=ROOT, today=None):
    plan = load_yaml(root / "_data/meal_plan.yml")
    terms = pantry_terms(load_yaml(root / "_data/pantry.yml"))
    existing = load_yaml(root / "_data/grocery_list.yml")

    merged = {}                                    # merge key -> item, in first-seen order
    for day in DAYS:
        slug = plan.get(day)
        if not slug:
            continue
        path = root / "_recipes" / f"{slug}.md"
        if not path.is_file():
            continue
        fm = read_front_matter(path)
        recipe = str(fm.get("title") or slug)
        for line in fm.get("ingredients") or []:
            text = str(line).strip()
            if not text:
                continue
            key = merge_key(text)
            if key in SKIP:
                continue
            item = merged.setdefault(key, {"name": display_name(text), "uses": [],
                                           "category": categorize(text)})
            if not any(u["text"] == text and u["recipe"] == recipe for u in item["uses"]):
                item["uses"].append({"text": text, "recipe": recipe})

    order = [name for name, _ in CATEGORIES] + [CATCHALL]
    sections = {name: {"name": name} for name in order}
    for item in merged.values():
        cat = item.pop("category")
        have = all(is_on_hand(u["text"], terms) for u in item["uses"])
        sections[cat].setdefault("have" if have else "items", []).append(item)
    categories = [s for s in sections.values() if s.get("items") or s.get("have")]

    # Keep what people added by hand
    for section in existing.get("categories") or []:
        if section.get("name") in EXTRA_SECTIONS and (section.get("items") or section.get("have")):
            categories.append(section)

    return {"week_of": str(today or date.today()), "categories": categories}


def main():
    data = build()
    out = ROOT / "_data/grocery_list.yml"
    out.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False, width=10_000),
                   encoding="utf-8")
    buy = sum(len(c.get("items") or []) for c in data["categories"])
    have = sum(len(c.get("have") or []) for c in data["categories"])
    print(f"Wrote {buy} items to buy, {have} on hand, in {len(data['categories'])} sections")


if __name__ == "__main__":
    main()
