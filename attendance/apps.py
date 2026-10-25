from django.apps import AppConfig


class AttendanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "attendance"

    def ready(self):
        from django.db.backends.signals import connection_created

        def sqlite_pragmas(sender, connection, **kwargs):
            if connection.vendor == "sqlite":  # WAL: readers don't block the device uploads writing punches
                cursor = connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA busy_timeout=20000;")

        connection_created.connect(sqlite_pragmas, dispatch_uid="attendance_sqlite_pragmas")
