﻿from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
import os
from dotenv import load_dotenv

# Alembic Config
config = context.config
fileConfig(config.config_file_name)

load_dotenv()
section = config.get_section(config.config_ini_section)
section["sqlalchemy.url"] = os.getenv("DATABASE_URL")

# модели
from app.db import Base  # noqa
from app import models  # noqa  # ensures models are imported

target_metadata = Base.metadata

def run_migrations_offline():
    url = section["sqlalchemy.url"]
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
