#!/usr/bin/env python3
"""
Patch site/recipes.js with fixed recipe data from output/recipes/.
Updates ingredients and instructions for all previously-broken recipes.
"""

import json
import re
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
RECIPES_JS = BASE_DIR / "site" / "recipes.js"
RECIPES_DIR = BASE_DIR / "output" / "recipes"
BROKEN_LIST = BASE_DIR / "output" / "broken_recipes.json"


def clean_ingredient(text):
    """Clean up ingredient text (remove markdown links, bold markers)."""
    # Convert markdown links [text](url) to just text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # Remove bold markers
    text = text.replace('**', '')
    return text.strip()


def main():
    # Load the current recipes.js
    with open(RECIPES_JS, 'r') as f:
        content = f.read()

    # Extract the JSON array
    match = re.match(r'const RECIPES = (.+);?\s*$', content, re.DOTALL)
    if not match:
        print("ERROR: Could not parse recipes.js format")
        return

    recipes = json.loads(match.group(1).rstrip(';'))
    print(f"Loaded {len(recipes)} recipes from recipes.js")

    # Load broken recipe list
    with open(BROKEN_LIST) as f:
        broken = json.load(f)
    broken_slugs = {b['slug'] for b in broken}

    # Build slug->recipe map for the JS data
    recipe_map = {r['slug']: r for r in recipes}

    fixed_count = 0
    still_broken = []

    for slug in sorted(broken_slugs):
        # Load the updated JSON
        json_file = RECIPES_DIR / f"{slug}.json"
        if not json_file.exists():
            print(f"  SKIP {slug} — no JSON file")
            still_broken.append(slug)
            continue

        with open(json_file) as f:
            updated = json.load(f)

        new_ingredients = [clean_ingredient(i) for i in updated.get('ingredients', []) if i.strip()]
        new_instructions = updated.get('instructions', '').strip()

        if not new_ingredients or not new_instructions:
            print(f"  SKIP {slug} — still missing data (ing={len(new_ingredients)}, inst={len(new_instructions)} chars)")
            still_broken.append(slug)
            continue

        # Find and update in the recipes array
        if slug in recipe_map:
            recipe_map[slug]['ingredients'] = new_ingredients
            recipe_map[slug]['instructions'] = new_instructions
            fixed_count += 1
            print(f"  FIXED {slug} — {len(new_ingredients)} ingredients, {len(new_instructions)} chars instructions")
        else:
            print(f"  WARN {slug} — not found in recipes.js")
            still_broken.append(slug)

    # Also fix the 4 malformed recipes (single-string ingredients)
    malformed_count = 0
    for r in recipes:
        if r.get('ingredients') and len(r['ingredients']) == 1 and len(r['ingredients'][0]) > 100:
            # This is a blob — try to re-parse from JSON
            json_file = RECIPES_DIR / f"{r['slug']}.json"
            if json_file.exists():
                with open(json_file) as f:
                    updated = json.load(f)
                if len(updated.get('ingredients', [])) > 1:
                    r['ingredients'] = [clean_ingredient(i) for i in updated['ingredients']]
                    malformed_count += 1
                    print(f"  FIXED-MALFORMED {r['slug']} — {len(r['ingredients'])} ingredients")

    # Write back
    recipes_json = json.dumps(recipes, ensure_ascii=False)
    with open(RECIPES_JS, 'w') as f:
        f.write(f"const RECIPES = {recipes_json};")

    print(f"\n=== PATCH COMPLETE ===")
    print(f"Fixed:          {fixed_count}")
    print(f"Fixed malformed: {malformed_count}")
    print(f"Still broken:   {len(still_broken)}")

    if still_broken:
        print("\nStill broken:")
        for s in still_broken:
            print(f"  {s}")


if __name__ == "__main__":
    main()
