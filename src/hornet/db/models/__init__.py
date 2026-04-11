"""ORM models package.

Importing this package triggers the side effect of every model
registering itself on ``Base.metadata``. Alembic imports this
package from ``alembic/env.py`` to discover the declared schema
for autogeneration and validation. If you add a new model file
in this package, import it here so it is picked up.
"""

from hornet.db.models.observation import ObservationRow

__all__ = ["ObservationRow"]
