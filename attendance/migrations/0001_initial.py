from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="Device",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("ip_address", models.CharField(max_length=255)),
                ("port", models.PositiveIntegerField(default=4370)),
                ("comm_key", models.PositiveIntegerField(default=0)),
                ("timeout", models.PositiveSmallIntegerField(default=15)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"]},
        ),
    ]
