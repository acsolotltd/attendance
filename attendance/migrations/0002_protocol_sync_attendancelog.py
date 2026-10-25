import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("attendance", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="device",
            name="protocol",
            field=models.CharField(choices=[("tcp", "TCP (default)"), ("udp", "UDP")], default="tcp", max_length=3),
        ),
        migrations.AddField(
            model_name="device",
            name="last_sync_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="AttendanceLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("user_id", models.CharField(db_index=True, max_length=32)),
                ("name", models.CharField(blank=True, default="", max_length=100)),
                ("timestamp", models.DateTimeField(db_index=True)),
                ("punch", models.SmallIntegerField(default=0)),
                ("verify", models.SmallIntegerField(default=0)),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="logs", to="attendance.device")),
            ],
            options={"ordering": ["timestamp", "user_id"], "unique_together": {("device", "user_id", "timestamp")}},
        ),
    ]
