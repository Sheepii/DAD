from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("handoff", "0018_design_store_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="scheduleddesign",
            name="store",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="scheduled_designs", to="handoff.store"),
        ),
        migrations.RemoveConstraint(
            model_name="scheduleddesign",
            name="unique_scheduled_design_per_day_task",
        ),
        migrations.AddConstraint(
            model_name="scheduleddesign",
            constraint=models.UniqueConstraint(fields=("due_date", "recurring_task", "store"), name="unique_scheduled_design_per_day_task_store"),
        ),
    ]
