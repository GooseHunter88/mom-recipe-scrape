#!/usr/bin/env python3
"""
Fast scraper for mymomshomecooking.com
- Skips category pages (gets category from each recipe page instead)
- Parallel image downloads
- Resume-capable
"""

import requests
import json
import time
import os
import re
import sys
from xml.etree import ElementTree
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

# --- Config ---
BASE_URL = "https://www.mymomshomecooking.com"
JINA_PREFIX = "https://r.jina.ai/"
OUTPUT_DIR = Path("/Users/remibarton/Documents/mom-recipe-scrape/output")
RECIPES_DIR = OUTPUT_DIR / "recipes"
IMAGES_DIR = OUTPUT_DIR / "images"
DELAY = 1.0  # seconds between Jina requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

JINA_HEADERS = {
    "Accept": "text/markdown",
    "X-Return-Format": "markdown",
}


def setup_dirs():
    RECIPES_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def get_recipe_urls():
    """Get all recipe URLs from sitemap (cached)."""
    cache = OUTPUT_DIR / "url_inventory.json"
    if cache.exists():
        with open(cache) as f:
            return json.load(f)["recipes"]

    print("Fetching sitemap...", flush=True)
    resp = requests.get(f"{BASE_URL}/sitemap.xml", headers=HEADERS, timeout=30)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ElementTree.fromstring(resp.content)

    recipes = []
    for sitemap in root.findall("sm:sitemap", ns):
        loc = sitemap.find("sm:loc", ns).text
        if "blog-posts" in loc:
            resp2 = requests.get(loc, headers=HEADERS, timeout=30)
            sm_root = ElementTree.fromstring(resp2.content)
            for url_elem in sm_root.findall("sm:url", ns):
                url = url_elem.find("sm:loc", ns).text
                if "/post/" in url:
                    recipes.append(url)

    print(f"Found {len(recipes)} recipe URLs", flush=True)

    # Cache
    with open(cache, "w") as f:
        json.dump({"recipes": recipes}, f, indent=2)

    return recipes


def fetch_via_jina(url):
    """Fetch rendered content via Jina Reader."""
    jina_url = f"{JINA_PREFIX}{url}"
    resp = requests.get(jina_url, headers=JINA_HEADERS, timeout=60)
    resp.raise_for_status()
    return resp.text


def parse_recipe(markdown_text, url):
    """Parse recipe from Jina markdown."""
    recipe = {
        "url": url,
        "slug": url.split("/post/")[-1] if "/post/" in url else "",
        "title": "",
        "serves": "",
        "category": "",
        "date": "",
        "ingredients": [],
        "instructions": "",
        "images": [],
    }

    lines = markdown_text.strip().split("\n")

    # Date
    date_match = re.search(r"Published Time:\s*(\d{4}-\d{2}-\d{2})", markdown_text)
    if date_match:
        recipe["date"] = date_match.group(1)

    # Title from H1 (=== underline style)
    h1_positions = []
    for i, line in enumerate(lines):
        if i + 1 < len(lines) and lines[i + 1].strip().startswith("======"):
            h1_positions.append(i)

    if len(h1_positions) >= 2:
        recipe["title"] = lines[h1_positions[1]].strip()
    elif len(h1_positions) == 1:
        recipe["title"] = lines[h1_positions[0]].strip()

    # Extract serves/makes from title
    title_serves = re.search(r"(Serves?\s*\d+[-\s]*\d*|Makes?\s*\d+.*?)$", recipe["title"], re.IGNORECASE)
    if title_serves:
        recipe["serves"] = title_serves.group(1).strip()
        recipe["title"] = recipe["title"][:title_serves.start()].strip()
    else:
        serves_match = re.search(r"serves?[- ](\d+)", recipe["slug"], re.IGNORECASE)
        if serves_match:
            recipe["serves"] = f"Serves {serves_match.group(1)}"

    # Category from link
    cat_match = re.search(r"\*\s*\[([^\]]+)\]\(https://www\.mymomshomecooking\.com/recipes-1/categories/", markdown_text)
    if cat_match:
        recipe["category"] = cat_match.group(1).strip()

    # Main recipe image (Image 1 only)
    main_img = re.search(r"!\[Image 1[^\]]*\]\((https://static\.wixstatic\.com/media/[^\)]+)\)", markdown_text)
    if main_img:
        recipe["images"].append(main_img.group(1))
    else:
        first_img = re.search(r"!\[[^\]]*\]\((https://static\.wixstatic\.com/media/[^\)]+)\)", markdown_text)
        if first_img:
            recipe["images"].append(first_img.group(1))

    # Extract body content between "min read" and first image
    content_start = None
    content_end = None

    for i, line in enumerate(lines):
        if content_start is None:
            if "min read" in line.lower():
                content_start = i + 1
        if content_start is not None and content_end is None:
            if line.strip().startswith("!["):
                content_end = i
                break

    if content_start is not None:
        while content_start < len(lines) and (
            lines[content_start].strip().lower().startswith("updated:") or
            not lines[content_start].strip()
        ):
            content_start += 1

    end = content_end or len(lines)
    body_lines = []
    if content_start is not None:
        for i in range(content_start, end):
            l = lines[i].strip()
            if "Recent Posts" in l or "recipes-1/categories" in l:
                break
            if l and not l.startswith("!["):
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
                line.endswith(")") and len(line) > 60 or
                re.match(r"^(Preheat|Heat|Mix|Combine|Add|Place|Pour|Stir|Cook|Bake|Let|Remove|Set|In a|Using|Once|Bring|Melt|Whisk|Season|Serve|Cover|Reduce|Line|Spray|Cut|Drain|Top|Toss|Roll|Fold|Brush|Arrange|Transfer|Refrigerate|Garnish|Return|Spread|Layer|Saute|Sauté|Grill|Roast|Simmer|Boil|Beat|Cream|Blend|Slice|Chop|Note|Tip)", line)
            )
            if is_instruction and len(ingredients) > 0:
                switched = True
                instructions.append(line)
            else:
                ingredients.append(line)
        else:
            instructions.append(line)

    recipe["ingredients"] = ingredients
    recipe["instructions"] = "\n".join(instructions)

    return recipe


def download_image(img_url, slug):
    """Download recipe image."""
    try:
        ext = ".jpg"
        path_part = urlparse(img_url).path
        if ".png" in path_part:
            ext = ".png"
        elif ".jpeg" in path_part:
            ext = ".jpeg"

        filepath = IMAGES_DIR / f"{slug}{ext}"
        if filepath.exists():
            return str(filepath)

        resp = requests.get(img_url, headers=HEADERS, timeout=30, stream=True)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return str(filepath)
    except Exception as e:
        return None


def scrape_one(url):
    """Scrape a single recipe."""
    slug = url.split("/post/")[-1]
    recipe_file = RECIPES_DIR / f"{slug}.json"

    # Skip if already scraped
    if recipe_file.exists():
        return {"slug": slug, "status": "cached"}

    try:
        md = fetch_via_jina(url)
        recipe = parse_recipe(md, url)

        # Download image
        if recipe["images"]:
            local = download_image(recipe["images"][0], slug)
            if local:
                recipe["local_image"] = local

        # Save
        with open(recipe_file, "w") as f:
            json.dump(recipe, f, indent=2)

        return {"slug": slug, "status": "ok", "title": recipe["title"], "category": recipe["category"]}

    except Exception as e:
        return {"slug": slug, "status": "error", "error": str(e)}


def main():
    setup_dirs()
    urls = get_recipe_urls()

    # Check what's already done
    done = {f.stem for f in RECIPES_DIR.glob("*.json")}
    remaining = [u for u in urls if u.split("/post/")[-1] not in done]

    print(f"\nTotal: {len(urls)} | Done: {len(done)} | Remaining: {len(remaining)}", flush=True)
    print(f"Starting scrape...\n", flush=True)

    errors = []
    for i, url in enumerate(remaining):
        result = scrape_one(url)
        status = result["status"]
        slug = result["slug"]

        if status == "ok":
            title = result.get("title", "?")
            cat = result.get("category", "?")
            print(f"[{i+1}/{len(remaining)}] {title} ({cat})", flush=True)
        elif status == "error":
            print(f"[{i+1}/{len(remaining)}] ERROR {slug}: {result['error']}", flush=True)
            errors.append(result)

        time.sleep(DELAY)

        # Checkpoint
        if (i + 1) % 50 == 0:
            print(f"\n--- Checkpoint: {i+1}/{len(remaining)} done, {len(errors)} errors ---\n", flush=True)

    # Build manifest
    print("\nBuilding manifest...", flush=True)
    manifest = {"total": 0, "categories": {}, "recipes": []}

    for f in sorted(RECIPES_DIR.glob("*.json")):
        with open(f) as fh:
            r = json.load(fh)
        cat = r.get("category", "Uncategorized")
        manifest["recipes"].append({
            "slug": r.get("slug", f.stem),
            "title": r.get("title", ""),
            "serves": r.get("serves", ""),
            "category": cat,
            "has_image": bool(r.get("images")),
            "has_ingredients": bool(r.get("ingredients")),
            "has_instructions": bool(r.get("instructions")),
        })
        manifest["categories"][cat] = manifest["categories"].get(cat, 0) + 1

    manifest["total"] = len(manifest["recipes"])

    with open(OUTPUT_DIR / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    if errors:
        with open(OUTPUT_DIR / "errors.json", "w") as f:
            json.dump(errors, f, indent=2)

    print(f"\n=== COMPLETE ===", flush=True)
    print(f"Recipes: {manifest['total']}", flush=True)
    print(f"Categories: {len(manifest['categories'])}", flush=True)
    print(f"Errors: {len(errors)}", flush=True)
    for cat, count in sorted(manifest["categories"].items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}", flush=True)


if __name__ == "__main__":
    main()
