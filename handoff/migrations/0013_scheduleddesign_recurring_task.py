from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("handoff", "0012_mockupdesignbox_rotation"),
    ]

    operations = [
        migrations.AlterField(
            model_name="scheduleddesign",
            name="due_date",
            field=models.DateField(),
        ),
        migrations.AddField(
            model_name="scheduleddesign",
            name="recurring_task",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="handoff.recurringtask",
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleddesign",
            constraint=models.UniqueConstraint(
                fields=("due_date", "recurring_task"),
                name="unique_scheduled_design_per_day_task",
            ),
        ),
    ]
