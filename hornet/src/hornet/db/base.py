"""SQLAlchemy Declarative Base shared by every ORM model in Hornet.

Every model subclasses ``Base``. Importing the ``hornet.db.models``
package is required before running migrations or any schema operation —
that import triggers the side-effect of each model registering itself
on ``Base.metadata``, which is what Alembic introspects when it compares
the declared schema against the database.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base. All ORM models inherit from this."""
