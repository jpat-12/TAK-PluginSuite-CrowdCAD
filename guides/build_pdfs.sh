#!/usr/bin/env bash
# Rebuild the PDF guides from the Markdown. Needs pandoc and Node with Playwright + Chromium.
#   bash guides/build_pdfs.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
version="$(cat "$here/../VERSION")"
for doc in SETUP_GUIDE USER_GUIDE; do
  title="$(head -1 "$here/$doc.md" | sed 's/^# //')"
  pandoc "$here/$doc.md" -f gfm -t html5 -s --embed-resources \
    --resource-path="$here" --css "$here/pdf-build/print.css" \
    --lua-filter "$here/pdf-build/links.lua" \
    --metadata pagetitle="$title" -o "$tmp/$doc.html"
  node "$here/pdf-build/print.mjs" "$tmp/$doc.html" "$here/$doc.pdf" "$title · v$version"
  echo "wrote guides/$doc.pdf"
done
