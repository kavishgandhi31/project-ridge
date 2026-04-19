#!/bin/bash
# Hornet v2 scheduled pipeline run.
# Called by launchd twice daily: 6AM (morning) and 7PM (evening).
#
# Logs to logs/ with timestamped filenames.
# Checks that Postgres is reachable before running.
# LLM stage runs on the morning job only (evening is data-only).

set -euo pipefail

HORNET_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$HORNET_DIR/.venv/bin"
LOG_DIR="$HORNET_DIR/logs"
TIMESTAMP=$(date +%Y-%m-%d_%H%M)
RUN_TYPE="${1:-morning}"  # "morning", "evening", or "imf_weekly"

# Daily runs exclude IMF -- it publishes monthly, so running it 2x daily wastes
# bandwidth and clutters logs. Weekly IMF refresh runs via com.hornet.imf_weekly.
DAILY_SOURCES="fred,worldbank,yfinance,oecd,bis,gdelt,googlenews"

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
    # Morning: full pipeline with LLM narratives, no IMF
    echo "Running full pipeline (with LLM, no IMF)..." >> "$LOG_FILE"
    "$VENV/python" -m hornet.cli --sources "$DAILY_SOURCES" >> "$LOG_FILE" 2>&1
elif [ "$RUN_TYPE" = "evening" ]; then
    # Evening: data refresh only, no IMF
    echo "Running data pipeline (skip LLM, no IMF)..." >> "$LOG_FILE"
    "$VENV/python" -m hornet.cli --sources "$DAILY_SOURCES" --skip-llm >> "$LOG_FILE" 2>&1
elif [ "$RUN_TYPE" = "imf_weekly" ]; then
    # Weekly: IMF data only (monthly publication cadence)
    echo "Running IMF-only weekly refresh..." >> "$LOG_FILE"
    "$VENV/python" -m hornet.cli --sources imf --skip-llm >> "$LOG_FILE" 2>&1
else
    echo "ERROR: Unknown RUN_TYPE '$RUN_TYPE'. Expected morning, evening, or imf_weekly." >> "$LOG_FILE"
    exit 1
fi

echo "Completed: $(date)" >> "$LOG_FILE"
echo "=== Done ===" >> "$LOG_FILE"
