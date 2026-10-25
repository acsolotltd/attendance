import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("attendance", "0003_adms")]
    operations = [
        migrations.CreateModel(
            name="Shift",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=60, unique=True)),
                ("start_time", models.TimeField()),
                ("end_time", models.TimeField()),
                ("work_days", models.CharField(default="0,1,2,3,4", max_length=20)),
                ("grace_minutes", models.PositiveSmallIntegerField(default=10)),
                ("overtime_after_minutes", models.PositiveSmallIntegerField(default=30)),
                ("window_before_minutes", models.PositiveSmallIntegerField(default=120)),
                ("window_after_minutes", models.PositiveSmallIntegerField(default=180)),
                ("is_default", models.BooleanField(default=False)),
            ],
            options={"ordering": ["start_time", "name"]},
        ),
        migrations.CreateModel(
            name="ShiftAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("user_id", models.CharField(db_index=True, max_length=32)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField(blank=True, null=True)),
                ("shift", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assignments", to="attendance.shift")),
            ],
            options={"ordering": ["-id"]},
        ),
    ]
