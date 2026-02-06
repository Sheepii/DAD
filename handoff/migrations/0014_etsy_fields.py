from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("handoff", "0013_scheduleddesign_recurring_task"),
    ]

    operations = [
        migrations.AddField(
            model_name="tasktemplate",
            name="etsy_description_default",
            field=models.TextField(
                blank=True,
                help_text="Default Etsy description for this product type (template).",
            ),
        ),
        migrations.AddField(
            model_name="tasktemplate",
            name="etsy_title_suffix",
            field=models.CharField(
                blank=True,
                help_text="Appended to suggested Etsy titles, e.g. 'T-Shirt'.",
                max_length=50,
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="etsy_description",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="task",
            name="etsy_tags",
            field=models.JSONField(
                blank=True,
                help_text="List of 13 tags (strings). Each tag must be under 20 characters.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="etsy_title",
            field=models.CharField(blank=True, max_length=140),
        ),
    ]

