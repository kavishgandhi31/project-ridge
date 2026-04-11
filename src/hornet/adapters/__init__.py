"""Data source adapters.

Each source (FRED, yfinance, WorldBank, IMF, BIS, OECD, GDELT, GoogleNews)
is implemented as a class satisfying the SourceAdapter protocol. Adapters
are the ONLY code that knows about source-specific formats, quirks, and
authentication. Everything downstream consumes canonical Observations.
"""

from hornet.adapters.base import HealthReport, SourceAdapter

__all__ = ["HealthReport", "SourceAdapter"]
