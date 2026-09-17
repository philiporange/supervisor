#!/usr/bin/env bash
# Compile the dashboard's Tailwind classes into supervisor/static/tailwind.css.
# The output is committed so the running service needs no node toolchain.
set -euo pipefail
cd "$(dirname "$0")/.."
npx -y tailwindcss@3.4.17 -c tailwind.config.js -i supervisor/static/tailwind.src.css -o supervisor/static/tailwind.css --minify
