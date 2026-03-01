#!/usr/bin/env python3
"""
Re-scrape recipe images with better detection.
Strategy: fetch each recipe via Jina, find the LARGEST image
that appears BEFORE "Recent Posts" section.
Only re-scrapes recipes that have tiny/wrong images.
"""

import requests
import json
import re
import time
import sys
from pathlib import Path

JINA_PREFIX = "https://r.jina.ai/"
RECIPES_DIR = Path("/Users/remibarton/Documents/mom-recipe-scrape/output/recipes")

JINA_HEADERS = {
    "Accept": "text/markdown",
    "X-Return-Format": "markdown",
}


def get_best_image(markdown_text):
    """Find the best recipe image from the markdown."""
    # Split at "Recent Posts" to only look at recipe content
    parts = markdown_text.split("Recent Posts")
    recipe_content = parts[0] if parts else markdown_text

    # Find all images in the recipe content area
    all_imgs = re.findall(r'!\[([^\]]*)\]\((https://static\.wixstatic\.com/media/[^\)]+)\)', recipe_content)

    if not all_imgs:
        return None

    # Score each image: prefer larger width, prefer "Image 1", avoid sidebar images
    best_url = None
    best_score = -1

    for alt, url in all_imgs:
        score = 0
        w_match = re.search(r'w_(\d+)', url)
        w = int(w_match.group(1)) if w_match else 0
        score += w  # Larger = better

        # Bonus for being Image 1
        if "Image 1" in alt and ":" not in alt:
            score += 1000

        # Penalty for being a named sidebar image like "Image 2: Recipe Name"
        if re.match(r'Image \d+:', alt):
            score -= 2000

        if score > best_score:
            best_score = score
            best_url = url

    if best_url:
        # Ensure we're requesting a decent size
        w_match = re.search(r'w_(\d+)', best_url)
        if w_match and int(w_match.group(1)) < 400:
            # Try to upsize the URL
            best_url = re.sub(r'/v1/fill/[^/]+/', '/v1/fill/w_800,h_600,al_c,q_85,enc_avif,quality_auto/', best_url)

    return best_url


def needs_fix(recipe_path):
    """Check if a recipe needs its image fixed."""
    with open(recipe_path) as f:
        r = json.load(f)
    images = r.get('images', [])
    if not images:
        return True
    url = images[0]
    w_match = re.search(r'w_(\d+)', url)
    if w_match and int(w_match.group(1)) < 400:
        return True
    return False


def main():
    # Find recipes needing fixes
    to_fix = []
    for f in sorted(RECIPES_DIR.glob("*.json")):
        if needs_fix(f):
            to_fix.append(f)

    print(f"Recipes needing image fix: {len(to_fix)}", flush=True)

    fixed = 0
    failed = 0

    for i, f in enumerate(to_fix):
        slug = f.stem
        with open(f) as fh:
            recipe = json.load(fh)

        url = recipe.get('url', '')
        if not url:
            print(f"[{i+1}/{len(to_fix)}] SKIP {slug}: no URL", flush=True)
            continue

        try:
            jina_url = f"{JINA_PREFIX}{url}"
            resp = requests.get(jina_url, headers=JINA_HEADERS, timeout=60)
            resp.raise_for_status()

            best_img = get_best_image(resp.text)

            if best_img:
                recipe['images'] = [best_img]
                with open(f, 'w') as fh:
                    json.dump(recipe, fh, indent=2)
                fixed += 1
                print(f"[{i+1}/{len(to_fix)}] FIXED {slug}", flush=True)
            else:
                failed += 1
                print(f"[{i+1}/{len(to_fix)}] NO IMAGE FOUND {slug}", flush=True)

        except Exception as e:
            failed += 1
            print(f"[{i+1}/{len(to_fix)}] ERROR {slug}: {e}", flush=True)

        time.sleep(1.0)

    print(f"\nDone: Fixed {fixed}, Failed {failed}", flush=True)


if __name__ == "__main__":
    main()
