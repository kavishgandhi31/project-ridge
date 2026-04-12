"""ORM models package.

Importing this package triggers the side effect of every model
registering itself on ``Base.metadata``. Alembic imports this
package from ``alembic/env.py`` to discover the declared schema
for autogeneration and validation. If you add a new model file
in this package, import it here so it is picked up.
"""

from hornet.db.models.alert_record import AlertRecordRow
from hornet.db.models.country import CountryRow
from hornet.db.models.event_record import EventRecordRow
from hornet.db.models.observation import ObservationRow
from hornet.db.models.pipeline_run import PipelineRunRow
from hornet.db.models.quality_issue import QualityIssueRow
from hornet.db.models.score_result import ScoreResultRow
from hornet.db.models.source_indicator import SourceIndicatorRow

__all__ = [
    "AlertRecordRow",
    "CountryRow",
    "EventRecordRow",
    "ObservationRow",
    "PipelineRunRow",
    "QualityIssueRow",
    "ScoreResultRow",
    "SourceIndicatorRow",
]
