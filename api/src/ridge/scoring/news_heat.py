"""News heat indicator — ported from v1 scorer.py lines 713-753.

Standalone indicator from GDELT volume data. NOT folded into
risk_sentiment scoring — this is a separate signal displayed in the
digest for situational awareness.

Returns a NewsHeat when GDELT article volume exceeds the configured
sigma threshold, or None if volume is normal.
"""

from __future__ import annotations

from collections.abc import Sequence

from ridge.domain.event import EventRecord
from ridge.domain.scoring import NewsHeat, ScoringConfig


def compute_news_heat(
    events: Sequence[EventRecord],
    config: ScoringConfig,
) -> NewsHeat | None:
    """Compute news heat indicator from GDELT volume EventRecords.

    Ported from v1 ``Scorer.compute_news_heat()`` (scorer.py lines 713-753).

    Parameters
    ----------
    events:
        EventRecords for a single country. This function filters to
        event_type="volume" internally.
    config:
        Scoring configuration (uses news_heat_sigma, min_observations).

    Returns
    -------
    NewsHeat or None
        NewsHeat if volume is elevated, None otherwise.
    """
    volume_values = [e.value for e in events if e.event_type == "volume" and e.value is not None]

    if len(volume_values) < config.min_observations:
        return None

    mean = sum(volume_values) / len(volume_values)
    if mean == 0:
        return None

    # Sample standard deviation (ddof=1 matches v1's pd.Series.std())
    variance = sum((v - mean) ** 2 for v in volume_values) / (len(volume_values) - 1)
    std = variance**0.5
    if std == 0:
        return None

    latest = volume_values[-1]
    sigma = (latest - mean) / std
    volume_ratio = latest / mean

    if sigma >= config.news_heat_sigma:
        return NewsHeat(
            sigma=round(sigma, 1),
            volume_ratio=round(volume_ratio, 1),
        )

    return None
