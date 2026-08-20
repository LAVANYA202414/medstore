from logging.config import fileConfig
import os
from sqlalchemy import pool, create_engine
from alembic import context
from dotenv import load_dotenv

load_dotenv()

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from models import Base
target_metadata = Base.metadata

def get_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        # Fallback to ini if .env missing
        url = config.get_main_option("sqlalchemy.url")
    return url

def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    url = get_url()
    if not url or url.strip() == "":
        raise ValueError("DATABASE_URL is empty! Check your .env file")

    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
