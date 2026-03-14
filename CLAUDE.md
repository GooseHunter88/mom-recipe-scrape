# Mom's Home Cooking — Project Instructions

## What This Is
Recipe site at `moms-home-cooking.pages.dev`. Scraped and generated recipes from family collection.

## Deploy
`bash deploy.sh` from this directory → Cloudflare Pages.

## Structure
- `site/` — Generated static site output
- `output/` — Scraper output data
- `scrape.py`, `scrape_fast.py` — Recipe scrapers
- `generate_images.py` — AI image generation for recipes
- `fix_images*.py` — Image repair scripts

## Notes
- This is a personal/family project, separate from DFO
- Python scripts are for one-time generation, not ongoing operations
