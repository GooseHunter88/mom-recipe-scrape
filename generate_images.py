#!/usr/bin/env python3
"""Generate food photos for recipes missing images using GPT-4o."""

import openai
import json
import base64
import time
import sys
from pathlib import Path

API_KEY = "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"

RECIPES_DIR = Path("/Users/remibarton/Documents/mom-recipe-scrape/output/recipes")
IMAGES_DIR = Path("/Users/remibarton/Documents/mom-recipe-scrape/output/generated_images")
SITE_DIR = Path("/Users/remibarton/Documents/mom-recipe-scrape/site")

client = openai.OpenAI(api_key=API_KEY)


def build_prompt(recipe):
    """Build a food photography prompt from recipe data."""
    title = recipe['title']
    category = recipe.get('category', '')

    # Extract key ingredient names (strip quantities/instructions)
    clean_ingredients = []
    for ing in recipe.get('ingredients', [])[:6]:
        # Skip "Serves X" lines
        if ing.strip().lower().startswith(('serves', 'makes', 'yield')):
            continue
        clean_ingredients.append(ing.split(',')[0])

    key_ing = ', '.join(clean_ingredients[:5])

    # Choose dishware/presentation based on category
    presentation = "on a white ceramic plate"
    if any(w in category.lower() for w in ['soup', 'chili', 'stew']):
        presentation = "in a deep ceramic bowl"
    elif any(w in category.lower() for w in ['beverage', 'drink', 'cocktail']):
        presentation = "in an elegant glass"
    elif any(w in category.lower() for w in ['dessert', 'cake', 'cookie', 'pie']):
        presentation = "on a white dessert plate"
    elif any(w in category.lower() for w in ['bread']):
        presentation = "on a wooden cutting board"
    elif any(w in category.lower() for w in ['appetizer', 'dip']):
        presentation = "on a serving platter"
    elif any(w in category.lower() for w in ['salad']):
        presentation = "in a wide shallow bowl"
    elif any(w in title.lower() for w in ['soup', 'chowder', 'chili', 'stew', 'bisque']):
        presentation = "in a deep ceramic bowl"
    elif any(w in title.lower() for w in ['cocktail', 'martini', 'sangria', 'punch', 'smoothie']):
        presentation = "in an elegant glass"
    elif any(w in title.lower() for w in ['cake', 'pie', 'brownie', 'cookie', 'tart', 'crisp']):
        presentation = "on a white dessert plate"
    elif any(w in title.lower() for w in ['casserole', 'bake', 'gratin']):
        presentation = "in a baking dish"

    prompt = (
        f"Professional overhead food photograph of {title}. "
        f"Key ingredients visible: {key_ing}. "
        f"Beautifully plated {presentation} on a rustic wooden table. "
        f"Soft natural window light from the left, shallow depth of field. "
        f"Warm, inviting home-cooked feel. Editorial food photography style. "
        f"No text, no labels, no watermarks, no hands."
    )
    return prompt


def main():
    IMAGES_DIR.mkdir(exist_ok=True)

    # Load all recipes and find ones needing images
    with open(SITE_DIR / 'recipes.js') as f:
        raw = f.read()
        all_recipes = json.loads(raw.replace('const RECIPES = ', '').rstrip().rstrip(';'))

    needs_image = [r for r in all_recipes if not r['image']]
    print(f"Recipes needing images: {len(needs_image)}", flush=True)

    # Check which are already generated (for resume)
    already_done = {f.stem for f in IMAGES_DIR.glob('*.png')}
    to_generate = [r for r in needs_image if r['slug'] not in already_done]
    print(f"Already generated: {len(already_done)}", flush=True)
    print(f"Remaining: {len(to_generate)}\n", flush=True)

    generated = 0
    errors = 0

    for i, recipe in enumerate(to_generate):
        slug = recipe['slug']
        title = recipe['title']
        prompt = build_prompt(recipe)

        try:
            print(f"[{i+1}/{len(to_generate)}] {title[:50]}...", end=' ', flush=True)

            result = client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                n=1,
                size="1024x1024",
                quality="medium"
            )

            img_data = base64.b64decode(result.data[0].b64_json)
            img_path = IMAGES_DIR / f"{slug}.png"
            with open(img_path, 'wb') as f:
                f.write(img_data)

            generated += 1
            print(f"OK ({len(img_data)//1024}KB)", flush=True)

        except openai.RateLimitError as e:
            print(f"RATE LIMITED - waiting 30s...", flush=True)
            time.sleep(30)
            # Retry once
            try:
                result = client.images.generate(
                    model="gpt-image-1",
                    prompt=prompt,
                    n=1,
                    size="1024x1024",
                    quality="medium"
                )
                img_data = base64.b64decode(result.data[0].b64_json)
                with open(IMAGES_DIR / f"{slug}.png", 'wb') as f:
                    f.write(img_data)
                generated += 1
                print(f"  RETRY OK", flush=True)
            except Exception as e2:
                errors += 1
                print(f"  RETRY FAILED: {e2}", flush=True)

        except Exception as e:
            errors += 1
            print(f"ERROR: {e}", flush=True)

        # Small delay to stay under rate limits
        if i < len(to_generate) - 1:
            time.sleep(1)

    print(f"\nDone: {generated} generated, {errors} errors", flush=True)
    print(f"Total in folder: {len(list(IMAGES_DIR.glob('*.png')))}", flush=True)


if __name__ == "__main__":
    main()
