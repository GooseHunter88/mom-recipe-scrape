#!/bin/bash
# Deploy Mom's Home Cooking to Cloudflare Pages
# Site: https://moms-home-cooking.pages.dev

DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT="moms-home-cooking"
DEPLOY_DIR="$DIR/site"
SITE_URL="https://moms-home-cooking.pages.dev"

# Load Cloudflare token
CF_ENV="$DIR/../.cloudflare-env"
if [ -f "$CF_ENV" ]; then
    export $(grep -v '^#' "$CF_ENV" | xargs)
fi
: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN not set — check $CF_ENV}"

echo "[deploy] Deploying $PROJECT..."

if [ ! -f "$DEPLOY_DIR/index.html" ]; then
    echo "[deploy] FAIL: $DEPLOY_DIR/index.html not found" >&2
    exit 1
fi

OUTPUT=$(CLOUDFLARE_API_TOKEN="$CLOUDFLARE_API_TOKEN" wrangler pages deploy "$DEPLOY_DIR" \
    --project-name="$PROJECT" \
    --branch=main \
    --commit-dirty=true 2>&1)

if echo "$OUTPUT" | grep -q "Deployment complete"; then
    echo "[deploy] Success: $SITE_URL"
else
    echo "[deploy] FAIL: $OUTPUT" >&2
    exit 1
fi
