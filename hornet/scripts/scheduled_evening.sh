#!/usr/bin/env zsh
# Hornet evening run (7PM) -- data only, skip LLM
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
cd "/Users/shantanumenawat/Documents/Project Hornet/hornet" || exit 1
source .env 2>/dev/null
.venv/bin/python -m hornet.cli --skip-llm >> "logs/pipeline_evening_$(date +%Y-%m-%d).log" 2>&1
