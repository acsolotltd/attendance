from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("attendance", "0004_shifts")]
    operations = [
        migrations.AddField("device", "encoding", models.CharField(choices=[
            ("UTF-8", "UTF-8 (default)"), ("GBK", "GBK (Chinese firmware)"), ("latin-1", "Latin-1")],
            default="UTF-8", max_length=12)),
        migrations.AddField("device", "trans_profile", models.CharField(choices=[
            ("standard", "Standard (recommended)"), ("minimal", "Minimal: no templates/photos"),
            ("numeric", "Legacy numeric flag")], default="standard", max_length=10)),
        migrations.AddField("device", "punch_state_unused", models.BooleanField(default=False)),
        migrations.AddIndex("attendancelog", models.Index(fields=["device", "timestamp"], name="log_device_ts_idx")),
    ]
