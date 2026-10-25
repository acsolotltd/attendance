"""Online-safe SQLite backup: python manage.py backup_db --to /backups --keep 14   (use pg_dump for PostgreSQL)."""
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Write a consistent copy of the SQLite database and prune old copies."

    def add_arguments(self, parser):
        parser.add_argument("--to", default="backups")
        parser.add_argument("--keep", type=int, default=14)

    def handle(self, *args, **opts):
        if connection.vendor != "sqlite":
            raise CommandError("backup_db only handles SQLite; use pg_dump for PostgreSQL.")
        dest_dir = Path(opts["to"])
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"attendance-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
        with closing(sqlite3.connect(connection.settings_dict["NAME"])) as src, closing(sqlite3.connect(dest)) as dst:
            src.backup(dst)
        for old in sorted(dest_dir.glob("attendance-*.sqlite3"))[:-max(opts["keep"], 1)]:
            old.unlink()
        self.stdout.write(self.style.SUCCESS(f"backup written: {dest}"))
