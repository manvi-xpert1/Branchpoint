"""Alembic environment.

Two ways in:
* the app passes an open connection in ``config.attributes["connection"]``
  (see app/database/migrate.py), which also works for in-memory SQLite;
* the ``alembic`` command line, which connects using DATABASE_URL.

``render_as_batch`` lets SQLite apply ALTER TABLE changes (it copies the
table behind the scenes); PostgreSQL alters in place.
"""

from alembic import context

from app.database.session import make_engine
from app.database.tables import Base

target_metadata = Base.metadata


def run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    with make_engine().connect() as conn:
        run(conn)
