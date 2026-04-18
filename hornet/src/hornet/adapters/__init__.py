"""Data source adapters.

Each source (FRED, yfinance, WorldBank, IMF, BIS, OECD, GDELT, GoogleNews)
is implemented as a class satisfying the SourceAdapter protocol. Adapters
are the ONLY code that knows about source-specific formats, quirks, and
authentication. Everything downstream consumes canonical Observations.
"""

from hornet.adapters.base import EventSourceAdapter, HealthReport, SourceAdapter
from hornet.adapters.base_client import BaseClient
from hornet.adapters.bis import BISAdapter
from hornet.adapters.fred import FredAdapter
from hornet.adapters.gdelt import GDELTAdapter
from hornet.adapters.googlenews import GoogleNewsAdapter
from hornet.adapters.imf import IMFAdapter
from hornet.adapters.oecd import OECDAdapter
from hornet.adapters.worldbank import WorldBankAdapter
from hornet.adapters.yfinance_adapter import YFinanceAdapter

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
