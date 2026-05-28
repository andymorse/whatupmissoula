# Watchlist — items to flag when they're on sale

Two lists. `my_picks` is what the site owner is personally watching for;
`ai_picks` is a default set of household staples worth tracking weekly. When a
deal matches anything here, the AI sets `watchlist_hit: true` and
`watchlist_source` ("mine" or "ai") on that Deal so we can badge it on the page.

Matching rules (the AI follows these):

- Match liberally on item identity, not exact wording. "kombucha" matches a
  16oz GT's Synergy bottle; "eggs" matches "Grade A large, 1 dozen"; "ground
  beef" matches "80/20 lean ground chuck."
- Parenthetical hints are *narrowing* signals, not requirements. `Apples
  (honeycrisp, gala)` will still match plain "apples on sale," but prefer the
  named varieties when both are present.
- If a deal would match both lists, prefer `mine` — the owner's pick wins.
- Do not flag obvious non-matches just because a word overlaps (e.g. "milk
  chocolate" is not a milk match).

Edit either list freely — changes here change what the page highlights next run.

## my_picks
<!-- Add one item per bullet. Synonyms / brands / sizes in parentheses are hints
     that help match but don't have to all be present. Leave the list empty if
     you want to rely only on ai_picks this week. -->

- Annie's Homegrown Mac and Cheese (boxed, single-box size — any flavor:
  classic cheddar, shells & white cheddar, etc.)
- Goodles mac and cheese (classic cheddar — that's the flavor we want called
  out; other Goodles flavors are fine to flag too but the cheddar is the one)
- Wilcoxson's ice cream (Montana-made, Livingston MT — any flavor / any size:
  pints, quarts, half-gallons)
- Tillamook ice cream (any flavor — typically the 1.5 qt / 48 oz cartons, but
  pints/scoops count too)
- Tillamook cheese — blocks only (loaf / brick / chunk; any variety: medium
  cheddar, sharp cheddar, pepper jack, etc.). Do NOT flag shredded, sliced,
  or string cheese — those are different products even though the brand matches.
- Epic Meat Strips - All kinds or varieties but would like the price to be close to 1.50 per strip.


## ai_picks
<!-- Default staples. Trim or extend as the household's actual shopping changes. -->
- Eggs (Grade A large, 1 dozen)
- Milk (gallon, 2% or whole)
- Butter (1 lb)
- Block cheese (cheddar, mozzarella)
- Greek yogurt (32 oz tub)
- Boneless skinless chicken breast
- Ground beef (80/20 or leaner)
- Bacon
- Sandwich bread (whole-wheat or white loaf)
- Bananas
- Apples (honeycrisp, gala, fuji)
- Yellow onions
- Russet potatoes
- Pasta (dry, 1 lb box)
- Olive oil
- Coffee (12 oz bag, whole bean or ground)
