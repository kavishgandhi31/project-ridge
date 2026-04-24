#!/usr/bin/env zsh
# Ridge evening run (7PM) -- data only, skip LLM
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
cd "$(dirname "$0")/.." || exit 1
source .env 2>/dev/null
.venv/bin/python -m ridge.cli --skip-llm >> "logs/pipeline_evening_$(date +%Y-%m-%d).log" 2>&1
