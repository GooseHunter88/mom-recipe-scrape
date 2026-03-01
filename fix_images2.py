#!/usr/bin/env python3
"""
Fix recipe images by scraping category pages.
Category pages show recipe thumbnails alongside links, giving us
a reliable slug->image mapping.
"""

import requests
import json
import re
import time
from pathlib import Path

JINA_PREFIX = "https://r.jina.ai/"
BASE = "https://www.mymomshomecooking.com"
RECIPES_DIR = Path("/Users/remibarton/Documents/mom-recipe-scrape/output/recipes")
SITE_DIR = Path("/Users/remibarton/Documents/mom-recipe-scrape/site")

JINA_HEADERS = {
    "Accept": "text/markdown",
    "X-Return-Format": "markdown",
}

CATEGORIES = [
    "appetizers", "beef", "beverage", "breads", "breakfast",
    "casserole", "crockpot", "desserts", "eggs", "fruit",
    "gravy-sauce-dressing", "lamb", "main-dish", "pasta-rice",
    "pork", "potato", "poultry", "salads", "seafood",
    "side-dishes", "soup", "vegetable"
]


def scrape_category_for_images(cat_slug):
    """Scrape a category page and extract slug->image mappings."""
    url = f"{BASE}/recipes-1/categories/{cat_slug}"
    jina_url = f"{JINA_PREFIX}{url}"

    try:
        resp = requests.get(jina_url, headers=JINA_HEADERS, timeout=60)
        resp.raise_for_status()
        md = resp.text
    except Exception as e:
        print(f"  ERROR fetching {cat_slug}: {e}", flush=True)
        return {}

    mappings = {}

    # Pattern: image line followed by link line
    # ![Image N: Recipe Title](https://static.wixstatic.com/...)
    # [Recipe Title](https://www.mymomshomecooking.com/post/slug)
    lines = md.split('\n')
    for i, line in enumerate(lines):
        # Look for wix image URLs
        img_match = re.search(r'\((https://static\.wixstatic\.com/media/[^\)]+)\)', line)
        if img_match:
            img_url = img_match.group(1)
            # Look in nearby lines (next 1-3 lines) for a recipe link
            for j in range(i, min(i + 4, len(lines))):
                link_match = re.search(r'\(https://www\.mymomshomecooking\.com/post/([^\)\s]+)\)', lines[j])
                if link_match:
                    slug = link_match.group(1)
                    # Upsize the image URL if it's small
                    w_match = re.search(r'w_(\d+)', img_url)
                    if w_match and int(w_match.group(1)) < 500:
                        # Extract the media ID and build a proper sized URL
                        media_id_match = re.search(r'media/(75d545_[a-f0-9]+~mv2\.[a-z]+)', img_url)
                        if media_id_match:
                            media_id = media_id_match.group(1)
                            img_url = f"https://static.wixstatic.com/media/{media_id}/v1/fill/w_800,h_600,al_c,q_85,enc_avif,quality_auto/{media_id}"
                    mappings[slug] = img_url
                    break

    return mappings


def main():
    print("Scraping category pages for image mappings...\n", flush=True)

    all_mappings = {}
    for cat in CATEGORIES:
        print(f"  Category: {cat}", flush=True)
        maps = scrape_category_for_images(cat)
        print(f"    Found {len(maps)} image mappings", flush=True)
        all_mappings.update(maps)
        time.sleep(1.5)

    print(f"\nTotal mappings: {len(all_mappings)}", flush=True)

    # Save mapping
    with open(RECIPES_DIR.parent / "image_map.json", "w") as f:
        json.dump(all_mappings, f, indent=2)

    # Update recipe JSONs
    updated = 0
    for f in sorted(RECIPES_DIR.glob("*.json")):
        slug = f.stem
        if slug in all_mappings:
            with open(f) as fh:
                recipe = json.load(fh)

            old_imgs = recipe.get('images', [])
            old_url = old_imgs[0] if old_imgs else ''

            # Check if current image is tiny/wrong
            w_match = re.search(r'w_(\d+)', old_url) if old_url else None
            needs_fix = not old_url or (w_match and int(w_match.group(1)) < 400)

            # Also check if image ID is shared with many recipes (wrong image)
            if not needs_fix:
                old_id = re.search(r'media/(75d545_[a-f0-9]+)', old_url)
                new_id = re.search(r'media/(75d545_[a-f0-9]+)', all_mappings[slug])
                if old_id and new_id and old_id.group(1) != new_id.group(1):
                    needs_fix = True  # Different image - category page is more reliable

            if needs_fix:
                recipe['images'] = [all_mappings[slug]]
                with open(f, 'w') as fh:
                    json.dump(recipe, fh, indent=2)
                updated += 1

    print(f"Updated {updated} recipe images", flush=True)

    # Rebuild recipes.js
    print("Rebuilding recipes.js...", flush=True)
    recipes = []
    for f in sorted(RECIPES_DIR.glob('*.json')):
        with open(f) as fh:
            r = json.load(fh)
        images = r.get('images', [])
        img_url = images[0] if images else ''
        recipes.append({
            'slug': r.get('slug', f.stem),
            'title': r.get('title', ''),
            'serves': r.get('serves', ''),
            'category': r.get('category', ''),
            'date': r.get('date', ''),
            'ingredients': r.get('ingredients', []),
            'instructions': r.get('instructions', ''),
            'image': img_url,
        })

    with open(SITE_DIR / 'recipes.js', 'w') as f:
        f.write('const RECIPES = ')
        json.dump(recipes, f)
        f.write(';')

    has_img = sum(1 for r in recipes if r['image'])
    print(f"\nrecipes.js rebuilt: {has_img}/{len(recipes)} have images", flush=True)
    print("Done! Redeploy to update the site.", flush=True)


if __name__ == "__main__":
    main()
