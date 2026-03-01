#!/usr/bin/env python3
"""
Re-scrape broken recipes (missing ingredients/instructions) from mymomshomecooking.com.
Uses Jina Reader to render JS-heavy Wix pages.
Updates JSON files in output/recipes/ and patches site/index.html.
"""

import requests
import json
import time
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
RECIPES_DIR = OUTPUT_DIR / "recipes"
JINA_PREFIX = "https://r.jina.ai/"
DELAY = 4  # longer delay to avoid rate limiting

JINA_HEADERS = {
    "Accept": "text/markdown",
    "X-Return-Format": "markdown",
}


def load_broken_list():
    # Use remaining list if it exists, otherwise full broken list
    remaining = OUTPUT_DIR / "remaining_recipes.json"
    if remaining.exists():
        with open(remaining) as f:
            return json.load(f)
    with open(OUTPUT_DIR / "broken_recipes.json") as f:
        return json.load(f)


def fetch_via_jina(url, retries=3):
    jina_url = f"{JINA_PREFIX}{url}"
    for attempt in range(retries):
        resp = requests.get(jina_url, headers=JINA_HEADERS, timeout=60)
        if resp.status_code == 429:
            wait = 10 * (attempt + 1)
            print(f"(rate limited, waiting {wait}s)", end=" ", flush=True)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.text
    resp.raise_for_status()  # will raise 429 on final failure


def parse_recipe_content(markdown_text):
    """Parse ingredients and instructions from Jina markdown.

    Two page formats exist:
    Format A: min read → ingredients → instructions → ![Image]
    Format B: min read → ![Image 1] → ingredients → instructions → [Category]
    """
    lines = markdown_text.strip().split("\n")

    # Find the "min read" anchor
    min_read_idx = None
    for i, line in enumerate(lines):
        if "min read" in line.lower():
            min_read_idx = i
            break

    if min_read_idx is None:
        return [], ""

    # Check if an image appears immediately after min_read (Format B)
    # Look within the next few lines for ![Image
    first_content_idx = min_read_idx + 1

    # Skip blanks and "Updated:" lines
    while first_content_idx < len(lines) and (
        not lines[first_content_idx].strip() or
        lines[first_content_idx].strip().lower().startswith("updated:")
    ):
        first_content_idx += 1

    # Grab ALL content between min_read and "Recent Posts"/category link,
    # skipping image lines (images can appear anywhere in the content)
    body_lines = []
    for i in range(first_content_idx, len(lines)):
        l = lines[i].strip()
        if "Recent Posts" in l or "recipes-1/categories" in l:
            break
        # Stop at category links like "* [Desserts](...)"
        if re.match(r"^\*\s*\[", l):
            break
        # Skip images and blank lines
        if not l or l.startswith("![") or l.startswith("[!["):
            continue
        body_lines.append(l)

    # Separate ingredients from instructions
    ingredient_pattern = re.compile(
        r"^(\d|½|¼|¾|⅓|⅔|⅛|one|two|three|four|pinch|dash|zest|juice of)",
        re.IGNORECASE
    )

    ingredients = []
    instructions = []
    switched = False

    for line in body_lines:
        if not switched:
            is_instruction = (
                len(line) > 80 or
                line.endswith(".") or
                line.endswith("!") or
                (line.endswith(")") and len(line) > 60) or
                re.match(
                    r"^(Preheat|Heat|Mix|Combine|Add|Place|Pour|Stir|Cook|Bake|Let|Remove|Set|In a|Using|Once|Bring|Melt|Whisk|Season|Serve|Cover|Reduce|Line|Spray|Cut|Drain|Top|Toss|Roll|Fold|Brush|Arrange|Transfer|Refrigerate|Garnish|Return|Spread|Layer|Saute|Sauté|Grill|Roast|Simmer|Boil|Beat|Cream|Blend|Slice|Chop|Note|Tip|Make|Prepare|Allow|Wrap|Fill|Drop|Dip|Break)",
                    line
                )
            )
            if is_instruction and len(ingredients) > 0:
                switched = True
                instructions.append(line)
            else:
                ingredients.append(line)
        else:
            instructions.append(line)

    return ingredients, "\n".join(instructions)


def rescrape_recipe(slug, url):
    """Re-scrape a single recipe and update its JSON."""
    try:
        md = fetch_via_jina(url)
        ingredients, instructions = parse_recipe_content(md)

        # Load existing JSON
        recipe_file = RECIPES_DIR / f"{slug}.json"
        if recipe_file.exists():
            with open(recipe_file) as f:
                recipe = json.load(f)
        else:
            recipe = {"slug": slug, "url": url}

        # Update with new data
        if ingredients:
            recipe["ingredients"] = ingredients
        if instructions:
            recipe["instructions"] = instructions

        # Save
        with open(recipe_file, "w") as f:
            json.dump(recipe, f, indent=2)

        return {
            "slug": slug,
            "status": "ok",
            "ingredients_count": len(ingredients),
            "instructions_length": len(instructions),
        }

    except Exception as e:
        return {"slug": slug, "status": "error", "error": str(e)}


def main():
    broken = load_broken_list()
    print(f"Re-scraping {len(broken)} broken recipes...\n", flush=True)

    results = {"ok": [], "still_broken": [], "errors": []}

    for i, recipe in enumerate(broken):
        slug = recipe["slug"]
        url = recipe["url"]
        print(f"[{i+1}/{len(broken)}] {slug}...", end=" ", flush=True)

        result = rescrape_recipe(slug, url)

        if result["status"] == "ok":
            if result["ingredients_count"] > 0 and result["instructions_length"] > 0:
                print(f"OK ({result['ingredients_count']} ingredients)", flush=True)
                results["ok"].append(result)
            else:
                print(f"STILL EMPTY (ing={result['ingredients_count']}, inst={result['instructions_length']} chars)", flush=True)
                results["still_broken"].append(result)
        else:
            print(f"ERROR: {result['error']}", flush=True)
            results["errors"].append(result)

        time.sleep(DELAY)

        # Checkpoint
        if (i + 1) % 20 == 0:
            print(f"\n--- {i+1}/{len(broken)} done: {len(results['ok'])} fixed, {len(results['still_broken'])} still broken, {len(results['errors'])} errors ---\n", flush=True)

    # Summary
    print(f"\n=== RESCRAPE COMPLETE ===", flush=True)
    print(f"Fixed:        {len(results['ok'])}", flush=True)
    print(f"Still broken: {len(results['still_broken'])}", flush=True)
    print(f"Errors:       {len(results['errors'])}", flush=True)

    with open(OUTPUT_DIR / "rescrape_results.json", "w") as f:
        json.dump(results, f, indent=2)

    if results["still_broken"]:
        print("\nStill broken:", flush=True)
        for r in results["still_broken"]:
            print(f"  {r['slug']}", flush=True)

    if results["errors"]:
        print("\nErrors:", flush=True)
        for r in results["errors"]:
            print(f"  {r['slug']}: {r['error']}", flush=True)


if __name__ == "__main__":
    main()
