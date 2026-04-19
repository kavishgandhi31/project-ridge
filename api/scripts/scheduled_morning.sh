#!/usr/bin/env zsh
# Hornet morning run (6AM) -- full pipeline with LLM
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
cd "$(dirname "$0")/.." || exit 1
source .env 2>/dev/null
.venv/bin/python -m hornet.cli >> "logs/pipeline_morning_$(date +%Y-%m-%d).log" 2>&1
