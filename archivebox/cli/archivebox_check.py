"""Database diagnostics that must work without initializing or migrating Django."""

from pathlib import Path
import sqlite3

import rich_click as click


@click.command()
@click.option("--database", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Check a specific SQLite file")
def main(database: Path | None = None) -> None:
    """Check SQLite integrity, foreign keys, and every table row without changing data."""
    from archivebox.config.common import get_config
    from archivebox.misc.db import check_sqlite_database, is_postgres

    config = get_config()
    if database is None:
        if is_postgres(config):
            raise click.ClickException("This check is for SQLite collections; use PostgreSQL's database integrity tools for PostgreSQL.")
        database = Path(config.DATABASE_NAME)
    try:
        counts = check_sqlite_database(database)
    except (OSError, RuntimeError, sqlite3.Error) as err:
        raise click.ClickException(f"Database check failed: {err}") from err
    click.echo("integrity_check: ok; foreign_key_check: ok")
    for table, count in counts.items():
        click.echo(f"{table}: {count} rows readable")
