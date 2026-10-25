/* Chowdown — match recipe ingredients against pantry items.
   Exposes window.PantryMatch. Receipt names ("organic honeycrisp apple 3") and recipe
   lines ("2 tbsp finely chopped fresh cilantro, plus more") are both reduced to a
   short core name ("apple", "cilantro") so they can be compared. */
window.PantryMatch = (function () {

  var UNITS = 'cups?|c|tablespoons?|tbsps?|tbs|teaspoons?|tsps?|ounces?|oz|pounds?|lbs?|lb|grams?|g|kilograms?|kg|ml|milliliters?|liters?|l|cloves?|cans?|jars?|packages?|pkgs?|sticks?|slices?|pieces?|pinch(?:es)?|dash(?:es)?|handfuls?|bunch(?:es)?|heads?|sprigs?|stalks?|ribs?|bags?|boxes|box|bottles?|quarts?|pints?|gallons?|inch|inches|cm|thumbs?|knobs?|fl';

  var UNIT_ONLY_RE = new RegExp('^(?:' + UNITS + ')$', 'i');
  var UNIT_RE = new RegExp('^(?:' + UNITS + ')\\b\\.?', 'i');

  // Words that describe prep, quality or size, never the ingredient itself.
  var NOISE = {};
  ('organic fresh freshly large small medium extra firm soft ripe raw whole ground ' +
   'chopped diced minced sliced thinly finely roughly coarsely grated shredded crushed peeled ' +
   'cubed halved quartered trimmed drained rinsed melted softened cooked uncooked packed ' +
   'unsalted salted sweetened unsweetened low sodium reduced fat free lowfat nonfat full ' +
   'boneless skinless bone-in cold warm hot room temperature toasted dried frozen canned ' +
   'plain pure good quality natural all-natural premium kosher flaky coarse fine ' +
   'baby young tender leftover about approximately optional divided plus more needed taste ' +
   'serving garnish for to of and or the a an with into in on at from such as if desired ' +
   'ear mashed half light dark leaf leave block jumbo mini gourmet medley super crispy other neutral your favorite favourite homemade store-bought bought').split(' ').forEach(function (w) { NOISE[w] = true; });

  // Receipt-only noise: brands and marketing that survive on shopping lists.
  var BRANDS = ['cascadian farm', 'bonne maman', 'teddie', 'organicgirl', 'gotham greens', 'driscoll\'s',
    'driscolls', 'mary\'s gone crackers', 'marys gone crackers', 'nature\'s own', 'natures own',
    'mcconnells', 'mcconnell\'s', 'sweetest batch', 'honeycrisp', 'gala', 'fuji', 'granny smith', 'hass',
    'see\'s candies', 'sees candies', 'whole foods market', '365', 'kirkland', 'trader joe\'s', 'good & gather',
    'goya', 'barilla', 'heinz', 'hellmann\'s', 'hellmanns', 'land o lakes', 'kerrygold', 'horizon', 'chobani',
    'fage', 'siggi\'s', 'tillamook', 'daisy', 'pacific', 'imagine', 'swanson', 'amy\'s', 'annie\'s'];

  // Multi-word foods that must stay together, otherwise "butter" would match "peanut butter".
  var COMPOUNDS = ['peanut butter', 'almond butter', 'cashew butter', 'apple butter', 'butter bean', 'cream cheese',
    'ice cream', 'sour cream', 'heavy cream', 'whipping cream', 'coconut milk', 'coconut oil', 'coconut cream',
    'almond milk', 'oat milk', 'soy milk', 'soy sauce', 'fish sauce', 'hot sauce', 'tomato sauce', 'tomato paste',
    'curry paste', 'chili paste', 'chili sauce', 'chili powder', 'garlic powder', 'onion powder', 'baking powder',
    'baking soda', 'cocoa powder', 'brown sugar', 'powdered sugar', 'maple syrup', 'corn syrup', 'corn starch',
    'cornstarch', 'olive oil', 'sesame oil', 'vegetable oil', 'sesame seed', 'cumin seed', 'black pepper',
    'red pepper', 'bell pepper', 'green onion', 'red onion', 'sweet potato', 'chicken broth', 'chicken stock',
    'vegetable broth', 'vegetable stock', 'beef broth', 'beef stock', 'rice vinegar', 'cider vinegar',
    'balsamic vinegar', 'red wine', 'white wine', 'dijon mustard', 'ground beef', 'ground turkey', 'ground pork',
    'egg yolk', 'egg white', 'vanilla extract', 'red pepper flake', 'chocolate chip', 'bread crumb', 'breadcrumb',
    'string bean', 'green bean', 'black bean', 'kidney bean', 'white bean', 'chickpea', 'garam masala'];

  var ALIASES = {
    coriander: 'cilantro', scallion: 'green onion', 'spring onion': 'green onion', scallions: 'green onion',
    'garbanzo bean': 'chickpea', garbanzo: 'chickpea', 'bell pepper': 'pepper', capsicum: 'pepper',
    courgette: 'zucchini', aubergine: 'eggplant', 'caster sugar': 'sugar', 'granulated sugar': 'sugar',
    'white sugar': 'sugar', 'all purpose flour': 'flour', 'all-purpose flour': 'flour', 'plain flour': 'flour',
    'cider vinegar': 'apple cider vinegar', cornstarch: 'corn starch', breadcrumb: 'bread crumb',
    'red pepper flake': 'chili flake', 'chili flake': 'chili flake', 'extra virgin olive oil': 'olive oil',
    'vegetable oil': 'oil', 'canola oil': 'oil', 'neutral oil': 'oil', 'cooking oil': 'oil', 'cooking spray': 'oil'
  };

  // Always assumed on hand, never reported as missing.
  var ASSUMED = { water: true, ice: true, 'ice water': true };

  var DERIVED_HEADS = {};
  'oil extract powder sauce paste milk vinegar syrup butter flour broth stock cream cheese wine sugar seed starch'.split(' ').forEach(function (w) { DERIVED_HEADS[w] = true; });

  var VULGAR = { '¼': '.25', '½': '.5', '¾': '.75', '⅓': '.33', '⅔': '.66' };

  function singular(w) {
    if (w.length < 4) return w;
    if (/(ss|us|is)$/.test(w)) return w;
    if (/ies$/.test(w)) return w.slice(0, -3) + 'y';
    if (/(ches|shes|xes|oes)$/.test(w)) return w.slice(0, -2);
    if (/s$/.test(w)) return w.slice(0, -1);
    return w;
  }

  function stripBrands(s) {
    BRANDS.forEach(function (b) {
      s = s.replace(new RegExp('\\b' + b.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b', 'g'), ' ');
    });
    return s;
  }

  function baseClean(s) {
    s = String(s || '').toLowerCase();
    Object.keys(VULGAR).forEach(function (k) { s = s.split(k).join(VULGAR[k]); });
    s = s.replace(/\([^)]*\)/g, ' ');            // (14-ounce), (optional)
    s = s.split(/,|;| – | - | -- /)[0]; // "carrots, scrubbed" -> "carrots"
    s = s.replace(/\bplus\b.*$/, ' ');
    s = s.replace(/[^a-z\s'&.-]/g, ' ');
    return s;
  }

  function tokensOf(s) {
    return s.replace(/['.&]/g, '').replace(/-/g, ' ').split(/\s+/).filter(Boolean);
  }

  // Reduce any ingredient or receipt line to a canonical lower-case core name ('' if nothing food-like left).
  function normalize(raw) {
    var s = stripBrands(baseClean(raw));
    var words = tokensOf(s);

    // Drop leading quantity and unit tokens: "1 1/2 cups", "2 tbsp", "150g".
    var out = [];
    var leading = true;
    for (var i = 0; i < words.length; i++) {
      var w = words[i];
      if (leading && (NOISE[w] || /^\d+(\.\d+)?$/.test(w) || /^\d+(\.\d+)?(g|kg|ml|l|oz|lb|lbs|cm)$/.test(w) || UNIT_RE.test(w) || w === 'x')) continue;
      leading = false;
      if (/^\d/.test(w)) continue;
      if (UNIT_ONLY_RE.test(w)) continue;           // "garlic cloves", "2 tbsp / 30 g sugar"
      out.push(w);
    }
    var phrase = out.map(singular).join(' ');
    phrase = ' ' + phrase + ' ';

    // Glue compounds together so they behave as one token.
    COMPOUNDS.forEach(function (c) {
      var cs = c.split(' ').map(singular).join(' ');
      phrase = phrase.split(' ' + cs + ' ').join(' ' + cs.replace(/ /g, '_') + ' ');
    });

    var parts = phrase.trim().split(/\s+/);
    var food = parts.filter(function (w) { return w !== 'zest' && w !== 'juice'; });
    if (food.length) phrase = ' ' + food.join(' ') + ' ';
    var kept = phrase.trim().split(/\s+/).filter(function (w) { return w && !NOISE[w] && !NOISE[w.replace(/_/g, ' ')]; });
    if (!kept.length) return '';
    var joined = kept.join(' ').replace(/_/g, ' ');
    if (ALIASES[joined]) return ALIASES[joined];
    // Alias on a single token inside a longer phrase ("fresh coriander" -> cilantro)
    var swapped = kept.map(function (w) { return ALIASES[w.replace(/_/g, ' ')] || w; }).join(' ').replace(/_/g, ' ');
    return ALIASES[swapped] || swapped;
  }

  function isOptional(raw) {
    return /\b(optional|for serving|to serve|for garnish|garnish|for dusting|for greasing)\b/i.test(raw) ||
      /\bto taste\b/i.test(raw) && /\b(salt|pepper)\b/i.test(raw);
  }

  function coreSet(name) {
    return name.split(' ').filter(Boolean);
  }

  // Does a pantry core name satisfy a recipe core name?
  // Equal, or one fully contained in the other (so "baby spinach" ~ "spinach"). Compounds are
  // glued with '_' before normalize() returns, so "butter" never matches "peanut butter".
  function matches(ingredient, pantryItem) {
    if (!ingredient || !pantryItem) return false;
    if (ingredient === pantryItem) return true;
    var a = coreSet(ingredient), b = coreSet(pantryItem);
    var aInB = a.every(function (t) { return b.indexOf(t) !== -1; });
    var bInA = b.every(function (t) { return a.indexOf(t) !== -1; });
    var headA = a[a.length - 1], headB = b[b.length - 1];
    // Recipe line is a plain version of a fancier pantry item ("salt" vs "sea salt tortilla chip"): same head noun only.
    if (aInB && headA === headB) return true;
    // Pantry item is the base of the recipe line ("apple" vs "apple cider vinegar"): not for oils, sauces, etc.
    if (bInA && (headA === headB || !DERIVED_HEADS[headA])) return true;
    return false;
  }

  // normalize() flattens compounds back to spaces for display; for matching we keep them glued.
  function matchKey(raw) {
    var n = normalize(raw);
    if (!n) return '';
    COMPOUNDS.forEach(function (c) {
      var cs = c.split(' ').map(singular).join(' ');
      n = (' ' + n + ' ').split(' ' + cs + ' ').join(' ' + cs.replace(/ /g, '_') + ' ').trim();
    });
    return n;
  }

  function prettyName(raw) {
    var n = normalize(raw);
    return n || String(raw || '').trim().toLowerCase();
  }

  // pantry: [{ key, label, staple }], recipes: [{title, url, image, ingredients, rating}]
  function scoreRecipes(recipes, pantry) {
    return recipes.map(function (r) {
      var have = [], missing = [], used = {};
      (r.ingredients || []).forEach(function (line) {
        if (!line || /:\s*$/.test(line)) return;          // section headings like "For the sauce:"
        var key = matchKey(line);
        if (!key) return;
        if (ASSUMED[key]) return;
        var hit = null;
        for (var i = 0; i < pantry.length; i++) {
          if (matches(key, pantry[i].key)) { hit = pantry[i]; break; }
        }
        var label = prettyName(line);
        if (hit) { have.push(label); used[hit.key] = hit; }
        else if (!isOptional(line) && missing.indexOf(label) === -1) missing.push(label);
      });
      var total = have.length + missing.length;
      var usedOnHand = Object.keys(used).map(function (k) { return used[k]; }).filter(function (p) { return !p.staple; });
      return {
        recipe: r, have: have, missing: missing, total: total,
        pct: total ? have.length / total : 0,
        usesOnHand: usedOnHand
      };
    }).filter(function (s) { return s.total > 0; });
  }

  return { normalize: normalize, matchKey: matchKey, matches: matches, prettyName: prettyName, scoreRecipes: scoreRecipes };
})();
