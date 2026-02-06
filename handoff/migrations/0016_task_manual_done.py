from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("handoff", "0015_stores_and_publications"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="manual_done",
            field=models.BooleanField(
                default=False,
                help_text="Manual override for marking the task done (used for Dad view).",
            ),
        ),
    ]

