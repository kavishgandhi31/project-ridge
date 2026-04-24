"""Data source adapters.

Each source (FRED, yfinance, WorldBank, IMF, BIS, OECD, GDELT, GoogleNews)
is implemented as a class satisfying the SourceAdapter protocol. Adapters
are the ONLY code that knows about source-specific formats, quirks, and
authentication. Everything downstream consumes canonical Observations.
"""

from ridge.adapters.base import EventSourceAdapter, HealthReport, SourceAdapter
from ridge.adapters.base_client import BaseClient
from ridge.adapters.bis import BISAdapter
from ridge.adapters.fred import FredAdapter
from ridge.adapters.gdelt import GDELTAdapter
from ridge.adapters.googlenews import GoogleNewsAdapter
from ridge.adapters.imf import IMFAdapter
from ridge.adapters.oecd import OECDAdapter
from ridge.adapters.worldbank import WorldBankAdapter
from ridge.adapters.yfinance_adapter import YFinanceAdapter

__all__ = [
    "BISAdapter",
    "BaseClient",
    "EventSourceAdapter",
    "FredAdapter",
    "GDELTAdapter",
    "GoogleNewsAdapter",
    "HealthReport",
    "IMFAdapter",
    "OECDAdapter",
    "SourceAdapter",
    "WorldBankAdapter",
    "YFinanceAdapter",
]
