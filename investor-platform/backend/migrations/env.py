from alembic import context
from sqlalchemy import create_engine, pool

from investor_platform.db import database_url
from investor_platform.models import Base

config = context.config
# Tests provide a connection with an isolated search_path.
connection = config.attributes.get("connection")
if connection is not None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
