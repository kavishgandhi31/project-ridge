"""Quality layer -- data quality checks ported from v1's 13 monitoring modules.

Each check is a pure function: (data, config) -> list[QualityIssue].
No DB dependency in the check functions themselves. A runner fetches
data from repos, runs checks, and persists QualityIssue records.

Controls:
    #1  outlier         Statistical outlier detection (4-sigma gate)
    #2  series_audit    Registry vs actual observation coverage
    #3  cross_source    Cross-source value divergence
    #4  score_stability Composite score jump between runs
    #5  revision        Vintage-based revision detection
    #6  flatline        Stuck-value detection
    #7  structural_break Regime shift detection
    #8  date_consistency Cross-source date alignment
    #9  backfill        Sudden coverage gain detection
    #10 source_staleness Per-indicator staleness check
"""
