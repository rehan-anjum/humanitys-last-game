#!/usr/bin/env bash
# Set up humanitys-last-game GitHub org + org Pages at humanitys-last-game.github.io
#
# Prerequisites: gh CLI authenticated as vats98754 (gh auth login)
#
# This script cannot create the org for you (GitHub requires the web UI once).
# After the org exists, it transfers the repo and renames it for org-root Pages.

set -euo pipefail

ORG=humanitys-last-game
PAGES_REPO=humanitys-last-game.github.io
SOURCE=vats98754/humanitys-last-game
SITE_URL="https://${PAGES_REPO}"

echo "==> Step 1: Create the org (browser — one-time)"
echo "    Open: https://github.com/account/organizations/new"
echo "    Organization name: ${ORG}"
echo "    Contact email: your personal email"
echo ""
read -r -p "Press Enter after the org ${ORG} exists on GitHub..."

if ! gh api "orgs/${ORG}" -q .login >/dev/null 2>&1; then
  echo "error: org ${ORG} not found. Create it at the URL above first." >&2
  exit 1
fi
echo "    OK: org ${ORG} exists."

echo ""
echo "==> Step 2: Transfer ${SOURCE} -> ${ORG}/humanitys-last-game"
read -r -p "Transfer repo now? [y/N] " ans
if [[ "${ans,,}" == "y" ]]; then
  gh api -X POST "repos/${SOURCE}/transfer" \
    -f new_owner="${ORG}" \
    -f new_name=humanitys-last-game
  echo "    Transfer initiated (accept any email prompt from GitHub)."
  read -r -p "Press Enter after transfer completes..."
  SOURCE="${ORG}/humanitys-last-game"
fi

echo ""
echo "==> Step 3: Rename to ${PAGES_REPO} (enables org-root Pages URL)"
read -r -p "Rename repo now? [y/N] " ans
if [[ "${ans,,}" == "y" ]]; then
  gh repo rename "${PAGES_REPO}" --repo "${SOURCE}" --yes
  SOURCE="${ORG}/${PAGES_REPO}"
  echo "    Site will be: ${SITE_URL}"
fi

echo ""
echo "==> Step 4: Enable GitHub Pages (GitHub Actions source)"
echo "    Open: https://github.com/${SOURCE}/settings/pages"
echo "    Build and deployment -> Source: GitHub Actions"
read -r -p "Press Enter after Pages source is set to GitHub Actions..."

echo ""
echo "==> Step 5: Push main (triggers deploy-docs workflow)"
echo "    git push origin main"
echo ""
echo "Done. Docs URL: ${SITE_URL}"
echo "Code + docs live in: https://github.com/${ORG}/${PAGES_REPO}"
