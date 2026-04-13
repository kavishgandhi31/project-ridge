#!/bin/bash
# Hornet v2 scheduled pipeline run.
# Called by launchd twice daily: 6AM (morning) and 7PM (evening).
#
# Logs to hornet/logs/ with timestamped filenames.
# Checks that Postgres is reachable before running.
# LLM stage runs on the morning job only (evening is data-only).

set -euo pipefail

HORNET_DIR="/Users/shantanumenawat/Documents/Project Hornet/hornet"
VENV="$HORNET_DIR/.venv/bin"
LOG_DIR="$HORNET_DIR/logs"
TIMESTAMP=$(date +%Y-%m-%d_%H%M)
RUN_TYPE="${1:-morning}"  # "morning" or "evening"

mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/pipeline_${RUN_TYPE}_${TIMESTAMP}.log"

echo "=== Hornet v2 scheduled run: $RUN_TYPE ===" >> "$LOG_FILE"
echo "Started: $(date)" >> "$LOG_FILE"

# Source the .env file for API keys
if [ -f "$HORNET_DIR/.env" ]; then
    set -a
    source "$HORNET_DIR/.env"
    set +a
fi

# Check Postgres is reachable
if ! "$VENV/python" -c "
import asyncio
from hornet.db.session import get_engine
async def check():
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(__import__('sqlalchemy').text('SELECT 1'))
    await engine.dispose()
asyncio.run(check())
" >> "$LOG_FILE" 2>&1; then
    echo "ERROR: Postgres not reachable. Aborting." >> "$LOG_FILE"
    exit 1
fi

# Run the pipeline
cd "$HORNET_DIR"

if [ "$RUN_TYPE" = "morning" ]; then
    # Morning: full pipeline with LLM narratives
    echo "Running full pipeline (with LLM)..." >> "$LOG_FILE"
    "$VENV/python" -m hornet.cli run >> "$LOG_FILE" 2>&1
else
    # Evening: data refresh only (no LLM, saves 10 min)
    echo "Running data pipeline (skip LLM)..." >> "$LOG_FILE"
    "$VENV/python" -m hornet.cli run --skip-llm >> "$LOG_FILE" 2>&1
fi

echo "Completed: $(date)" >> "$LOG_FILE"
echo "=== Done ===" >> "$LOG_FILE"
