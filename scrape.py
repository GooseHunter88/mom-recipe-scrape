#!/usr/bin/env python3
"""
Scraper for mymomshomecooking.com
- Fetches sitemap to get all recipe URLs
- Uses Jina Reader (r.jina.ai) to render JS and extract content
- Parses recipes into structured JSON
- Downloads all images
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

# --- Config ---
BASE_URL = "https://www.mymomshomecooking.com"
JINA_PREFIX = "https://r.jina.ai/"
OUTPUT_DIR = Path("/Users/remibarton/Documents/mom-recipe-scrape/output")
RECIPES_DIR = OUTPUT_DIR / "recipes"
IMAGES_DIR = OUTPUT_DIR / "images"
DELAY = 1.5  # seconds between requests to be polite

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

JINA_HEADERS = {
    "Accept": "text/markdown",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "X-Return-Format": "markdown",
}


def setup_dirs():
    """Create output directories."""
    RECIPES_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def fetch_sitemap_urls():
    """Fetch all recipe URLs from the sitemap."""
    print("Fetching sitemap index...")
    resp = requests.get(f"{BASE_URL}/sitemap.xml", headers=HEADERS, timeout=30)
    resp.raise_for_status()

    # Parse sitemap index to find sub-sitemaps
    root = ElementTree.fromstring(resp.content)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    sub_sitemaps = []
    for sitemap in root.findall("sm:sitemap", ns):
        loc = sitemap.find("sm:loc", ns)
        if loc is not None:
            sub_sitemaps.append(loc.text)

    print(f"Found {len(sub_sitemaps)} sub-sitemaps")

    # Fetch each sub-sitemap and collect URLs
    all_urls = {"recipes": [], "categories": [], "pages": []}

    for sm_url in sub_sitemaps:
        print(f"  Fetching {sm_url}...")
        resp = requests.get(sm_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        sm_root = ElementTree.fromstring(resp.content)

        for url_elem in sm_root.findall("sm:url", ns):
            loc = url_elem.find("sm:loc", ns)
            if loc is None:
                continue
            url = loc.text

            if "/post/" in url:
                all_urls["recipes"].append(url)
            elif "/categories/" in url:
                all_urls["categories"].append(url)
            else:
                all_urls["pages"].append(url)

    print(f"\nInventory:")
    print(f"  Recipes:    {len(all_urls['recipes'])}")
    print(f"  Categories: {len(all_urls['categories'])}")
    print(f"  Pages:      {len(all_urls['pages'])}")

    # Save URL inventory
    with open(OUTPUT_DIR / "url_inventory.json", "w") as f:
        json.dump(all_urls, f, indent=2)

    return all_urls


def fetch_via_jina(url):
    """Fetch a page via Jina Reader to get rendered markdown content."""
    jina_url = f"{JINA_PREFIX}{url}"
    resp = requests.get(jina_url, headers=JINA_HEADERS, timeout=60)
    resp.raise_for_status()
    return resp.text


def parse_recipe(markdown_text, url):
    """Parse recipe data from Jina markdown output.

    The Wix site format is:
    - Title as H1 heading (repeated twice usually)
    - Date + read time line
    - Optional "Updated:" line
    - Then ingredients as plain text lines (measurements + items)
    - Then instructions as plain text paragraphs
    - Then image(s)
    - Then category link like [Desserts](url)
    - Then "Recent Posts" footer section
    """
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
        "raw_markdown": markdown_text,
    }

    lines = markdown_text.strip().split("\n")

    # Extract published date from metadata
    date_match = re.search(r"Published Time:\s*(\d{4}-\d{2}-\d{2})", markdown_text)
    if date_match:
        recipe["date"] = date_match.group(1)

    # Find the main H1 title (the second one, after nav repeat)
    h1_lines = [i for i, l in enumerate(lines) if l.strip().startswith("=====") or (l.startswith("# ") and "top of page" not in l.lower())]

    # Look for the title pattern: line followed by ====
    title_line = None
    for i, line in enumerate(lines):
        if line.strip().startswith("======") and i > 0:
            candidate = lines[i-1].strip()
            if candidate and "top of page" not in candidate.lower() and len(candidate) > 3:
                title_line = i - 1
                # Use the SECOND occurrence (after nav) as that's the main heading

    # Get the main content title (second H1 or the big === heading)
    h1_positions = []
    for i, line in enumerate(lines):
        if i + 1 < len(lines) and lines[i + 1].strip().startswith("======"):
            h1_positions.append(i)

    if len(h1_positions) >= 2:
        recipe["title"] = lines[h1_positions[1]].strip()
    elif len(h1_positions) == 1:
        recipe["title"] = lines[h1_positions[0]].strip()

    # Clean "Serves X" / "Makes X" from title, keep it as metadata
    title_serves = re.search(r"(Serves?\s*\d+[-\s]*\d*|Makes?\s*\d+.*?)$", recipe["title"], re.IGNORECASE)
    if title_serves:
        recipe["serves"] = title_serves.group(1).strip()
        recipe["title"] = recipe["title"][:title_serves.start()].strip()
    else:
        serves_match = re.search(r"serves?[- ](\d+)", recipe["slug"], re.IGNORECASE)
        if serves_match:
            recipe["serves"] = f"Serves {serves_match.group(1)}"

    # Extract category from the link pattern: * [CategoryName](url/categories/...)
    cat_match = re.search(r"\*\s*\[([^\]]+)\]\(https://www\.mymomshomecooking\.com/recipes-1/categories/", markdown_text)
    if cat_match:
        recipe["category"] = cat_match.group(1).strip()

    # Extract the MAIN recipe image (Image 1, before "Recent Posts")
    # Only grab the first image which is the actual recipe photo
    main_img_match = re.search(r"!\[Image 1[^\]]*\]\((https://static\.wixstatic\.com/media/[^\)]+)\)", markdown_text)
    if main_img_match:
        recipe["images"].append(main_img_match.group(1))
    else:
        # Fallback: grab first wix image
        first_img = re.search(r"!\[[^\]]*\]\((https://static\.wixstatic\.com/media/[^\)]+)\)", markdown_text)
        if first_img:
            recipe["images"].append(first_img.group(1))

    # --- Extract recipe body (ingredients + instructions) ---
    # Find the content zone: after "min read" / "Updated:" line, before "![Image"
    content_start = None
    content_end = None

    for i, line in enumerate(lines):
        # Content starts after the "X min read" line or "Updated:" line
        if content_start is None:
            if "min read" in line.lower():
                content_start = i + 1
            elif line.strip().lower().startswith("updated:"):
                content_start = i + 1
        # Content ends at the first image
        if content_start is not None and content_end is None:
            if line.strip().startswith("!["):
                content_end = i
                break

    # Skip any "Updated:" line right after content_start
    if content_start is not None:
        while content_start < len(lines) and (
            lines[content_start].strip().lower().startswith("updated:") or
            not lines[content_start].strip()
        ):
            content_start += 1

    if content_start is not None and content_end is not None:
        body_lines = [l.strip() for l in lines[content_start:content_end] if l.strip()]
    elif content_start is not None:
        # No image found, go until "Recent Posts" or category link
        body_lines = []
        for i in range(content_start, len(lines)):
            if "Recent Posts" in lines[i] or "recipes-1/categories" in lines[i]:
                break
            if lines[i].strip():
                body_lines.append(lines[i].strip())
    else:
        body_lines = []

    # Now separate ingredients from instructions
    # Ingredients are typically short lines with measurements
    # Instructions are longer sentences/paragraphs
    ingredient_pattern = re.compile(
        r"^(\d|½|¼|¾|⅓|⅔|⅛|one|two|three|four|pinch|dash|zest|juice|salt|pepper|"
        r"\d+\s*(cup|tbsp|tsp|oz|lb|can|pkg|package|bottle|clove|bunch|head|stick|slice|piece))",
        re.IGNORECASE
    )

    ingredients = []
    instructions = []
    switched_to_instructions = False

    for line in body_lines:
        # Once we hit a long sentence or instruction-like text, switch modes
        if not switched_to_instructions:
            # Check if this looks like an ingredient
            is_ingredient = (
                ingredient_pattern.match(line) or
                (len(line) < 80 and not line.endswith(".") and not switched_to_instructions) or
                (len(line) < 60 and re.match(r"^[A-Z][a-z]", line) and not line.endswith("."))
            )
            # Check if it looks like an instruction (sentence, starts with verb, ends with period, or is long)
            is_instruction = (
                len(line) > 80 or
                line.endswith(".") or
                line.endswith("!") or
                re.match(r"^(Preheat|Heat|Mix|Combine|Add|Place|Pour|Stir|Cook|Bake|Let|Remove|Set|In a|Using|Once|Bring|Melt|Whisk|Season|Serve|Cover|Reduce|Line|Spray|Cut|Drain|Top|Toss|Roll|Fold|Brush|Arrange|Transfer|Refrigerate|Garnish|Return)", line)
            )

            if is_instruction and len(ingredients) > 0:
                switched_to_instructions = True
                instructions.append(line)
            elif is_ingredient and not is_instruction:
                ingredients.append(line)
            elif len(line) < 60 and not switched_to_instructions:
                # Short line, probably still ingredient
                ingredients.append(line)
            else:
                switched_to_instructions = True
                instructions.append(line)
        else:
            instructions.append(line)

    recipe["ingredients"] = ingredients
    recipe["instructions"] = "\n".join(instructions)

    # Fallback: if no structured content, store full body
    if not ingredients and not instructions and body_lines:
        recipe["body_text"] = "\n".join(body_lines)

    return recipe


def download_image(img_url, recipe_slug, index):
    """Download an image and save it locally."""
    try:
        # Determine file extension
        parsed = urlparse(img_url)
        path = parsed.path
        ext = os.path.splitext(path)[1]
        if not ext or ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
            ext = ".jpg"

        filename = f"{recipe_slug}_{index}{ext}"
        filepath = IMAGES_DIR / filename

        if filepath.exists():
            return str(filepath)

        resp = requests.get(img_url, headers=HEADERS, timeout=30, stream=True)
        resp.raise_for_status()

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        return str(filepath)
    except Exception as e:
        print(f"    Failed to download image: {e}")
        return None


def scrape_recipe(url, download_images=True):
    """Scrape a single recipe URL."""
    slug = url.split("/post/")[-1] if "/post/" in url else "unknown"
    print(f"  Scraping: {slug}")

    try:
        markdown = fetch_via_jina(url)
        recipe = parse_recipe(markdown, url)

        # Download images
        if download_images and recipe["images"]:
            local_images = []
            for i, img_url in enumerate(recipe["images"]):
                local_path = download_image(img_url, slug, i)
                if local_path:
                    local_images.append(local_path)
            recipe["local_images"] = local_images

        # Save individual recipe JSON
        recipe_file = RECIPES_DIR / f"{slug}.json"
        # Don't save raw markdown in the individual file (too large)
        save_recipe = {k: v for k, v in recipe.items() if k != "raw_markdown"}
        with open(recipe_file, "w") as f:
            json.dump(save_recipe, f, indent=2)

        return recipe

    except Exception as e:
        print(f"    ERROR: {e}")
        return {"url": url, "slug": slug, "error": str(e)}


def scrape_category_page(url):
    """Scrape a category page to map recipes to categories."""
    cat_name = url.split("/categories/")[-1] if "/categories/" in url else "unknown"
    print(f"  Scraping category: {cat_name}")

    try:
        markdown = fetch_via_jina(url)
        # Look for recipe links in the category page
        recipe_urls = re.findall(r"https://www\.mymomshomecooking\.com/post/[^\s\)\]\"]+", markdown)
        recipe_slugs = [u.split("/post/")[-1] for u in recipe_urls]
        return {"category": cat_name, "recipe_slugs": list(set(recipe_slugs))}
    except Exception as e:
        print(f"    ERROR: {e}")
        return {"category": cat_name, "error": str(e)}


def run_test(n=3):
    """Test scraping on a small number of recipes."""
    setup_dirs()
    urls = fetch_sitemap_urls()

    print(f"\n--- TEST MODE: Scraping {n} recipes ---\n")
    test_urls = urls["recipes"][:n]
    results = []

    for url in test_urls:
        recipe = scrape_recipe(url)
        results.append(recipe)
        time.sleep(DELAY)

    # Save test results
    with open(OUTPUT_DIR / "test_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n--- TEST COMPLETE ---")
    for r in results:
        title = r.get("title", "?")
        n_ing = len(r.get("ingredients", []))
        n_img = len(r.get("images", []))
        has_inst = bool(r.get("instructions"))
        print(f"  {title}: {n_ing} ingredients, {n_img} images, instructions={'yes' if has_inst else 'no'}")

    return results


def run_full():
    """Full scrape of all recipes."""
    setup_dirs()

    # Load or fetch URLs
    inventory_file = OUTPUT_DIR / "url_inventory.json"
    if inventory_file.exists():
        with open(inventory_file) as f:
            urls = json.load(f)
        print(f"Loaded {len(urls['recipes'])} recipe URLs from cache")
    else:
        urls = fetch_sitemap_urls()

    # Scrape categories first (to build category mapping)
    print(f"\n--- Scraping {len(urls['categories'])} category pages ---\n")
    category_map = {}
    for cat_url in urls["categories"]:
        result = scrape_category_page(cat_url)
        if "recipe_slugs" in result:
            for slug in result["recipe_slugs"]:
                category_map.setdefault(slug, []).append(result["category"])
        time.sleep(DELAY)

    with open(OUTPUT_DIR / "category_map.json", "w") as f:
        json.dump(category_map, f, indent=2)

    # Check which recipes we've already scraped (for resume capability)
    already_scraped = set()
    for f in RECIPES_DIR.glob("*.json"):
        already_scraped.add(f.stem)

    remaining = [u for u in urls["recipes"] if u.split("/post/")[-1] not in already_scraped]
    print(f"\n--- Scraping {len(remaining)} recipes ({len(already_scraped)} already done) ---\n")

    errors = []
    for i, url in enumerate(remaining):
        slug = url.split("/post/")[-1]
        print(f"[{i+1}/{len(remaining)}]", end="")
        recipe = scrape_recipe(url)

        # Add category from our map
        if slug in category_map:
            recipe["categories"] = category_map[slug]
            # Update the saved file with category
            recipe_file = RECIPES_DIR / f"{slug}.json"
            if recipe_file.exists():
                with open(recipe_file) as f:
                    saved = json.load(f)
                saved["categories"] = category_map[slug]
                with open(recipe_file, "w") as f:
                    json.dump(saved, f, indent=2)

        if "error" in recipe:
            errors.append(recipe)

        time.sleep(DELAY)

        # Progress checkpoint every 50
        if (i + 1) % 50 == 0:
            print(f"\n  --- Checkpoint: {i+1}/{len(remaining)} done, {len(errors)} errors ---\n")

    # Build master manifest
    print("\nBuilding master manifest...")
    manifest = {"total_recipes": 0, "categories": {}, "recipes": []}

    for f in sorted(RECIPES_DIR.glob("*.json")):
        with open(f) as fh:
            recipe = json.load(fh)
        summary = {
            "slug": recipe.get("slug", f.stem),
            "title": recipe.get("title", ""),
            "serves": recipe.get("serves", ""),
            "categories": recipe.get("categories", []),
            "image_count": len(recipe.get("images", [])),
            "has_ingredients": bool(recipe.get("ingredients")),
            "has_instructions": bool(recipe.get("instructions")),
        }
        manifest["recipes"].append(summary)
        for cat in summary["categories"]:
            manifest["categories"].setdefault(cat, 0)
            manifest["categories"][cat] += 1

    manifest["total_recipes"] = len(manifest["recipes"])

    with open(OUTPUT_DIR / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n=== SCRAPE COMPLETE ===")
    print(f"Total recipes: {manifest['total_recipes']}")
    print(f"Categories: {len(manifest['categories'])}")
    print(f"Errors: {len(errors)}")
    if errors:
        with open(OUTPUT_DIR / "errors.json", "w") as f:
            json.dump(errors, f, indent=2)
        print(f"Error details saved to errors.json")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    if mode == "test":
        run_test(3)
    elif mode == "full":
        run_full()
    else:
        print(f"Usage: {sys.argv[0]} [test|full]")
