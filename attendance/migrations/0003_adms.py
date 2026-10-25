import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("attendance", "0002_protocol_sync_attendancelog")]
    operations = [
        migrations.AddField("device", "mode", models.CharField(choices=[
            ("pull", "Pull — this server connects to the device (TCP 4370)"),
            ("adms", "ADMS / push — the device connects to this server")], default="pull", max_length=4)),
        migrations.AddField("device", "serial_number", models.CharField(blank=True, default="", max_length=64)),
        migrations.AddField("device", "last_seen", models.DateTimeField(blank=True, null=True)),
        migrations.AddField("device", "last_ip", models.CharField(blank=True, default="", max_length=45)),
        migrations.AddField("device", "att_stamp", models.CharField(default="None", max_length=32)),
        migrations.AddField("device", "oper_stamp", models.CharField(default="None", max_length=32)),
        migrations.AddField("device", "device_info", models.JSONField(blank=True, default=dict)),
        migrations.AlterField("device", "ip_address", models.CharField(blank=True, default="", max_length=255)),
        migrations.AddConstraint("device", models.UniqueConstraint(
            fields=["serial_number"], condition=~models.Q(serial_number=""), name="uniq_device_serial",
            violation_error_message="That serial number is already registered.")),
        migrations.CreateModel(
            name="DeviceUser",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("pin", models.CharField(max_length=32)),
                ("name", models.CharField(blank=True, default="", max_length=100)),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="users", to="attendance.device")),
            ],
            options={"unique_together": {("device", "pin")}},
        ),
        migrations.CreateModel(
            name="DeviceCommand",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("command", models.CharField(max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("result_code", models.IntegerField(blank=True, null=True)),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="commands", to="attendance.device")),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="DeviceRequestLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("serial", models.CharField(blank=True, default="", max_length=64)),
                ("method", models.CharField(max_length=8)),
                ("path", models.CharField(max_length=500)),
                ("body_preview", models.TextField(blank=True, default="")),
                ("response_preview", models.CharField(blank=True, default="", max_length=300)),
                ("status", models.PositiveSmallIntegerField(default=200)),
                ("remote_ip", models.CharField(blank=True, default="", max_length=45)),
            ],
            options={"ordering": ["-id"]},
        ),
    ]
