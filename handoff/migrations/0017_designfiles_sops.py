from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("handoff", "0016_task_manual_done"),
    ]

    operations = [
        migrations.CreateModel(
            name="DesignFile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("filename", models.CharField(max_length=255)),
                ("date_assigned", models.DateField(blank=True, null=True)),
                ("status", models.CharField(choices=[("DUMPED", "Dumped"), ("SCHEDULED", "Scheduled"), ("ACTIVE", "Active"), ("POSTED", "Posted"), ("ERROR", "Error"), ("RECYCLED", "Recycled")], max_length=20)),
                ("drive_file_id", models.CharField(blank=True, max_length=200)),
                ("size_mb", models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ("ext", models.CharField(blank=True, max_length=10)),
                ("source_folder", models.CharField(blank=True, max_length=50)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="DesignHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("posted_date", models.DateField()),
                ("original_drive_file_id", models.CharField(blank=True, max_length=200)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("design_file", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="history", to="handoff.designfile")),
            ],
        ),
        migrations.CreateModel(
            name="SOPGuide",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("scribe_id_or_url", models.CharField(max_length=300)),
                ("context_route", models.CharField(blank=True, max_length=200)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="SOPReplyTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("trigger_keywords", models.JSONField(blank=True, help_text="List of keywords/phrases that match a customer message.", null=True)),
                ("reply_text", models.TextField()),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
