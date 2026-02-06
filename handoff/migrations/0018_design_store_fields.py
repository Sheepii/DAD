from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("handoff", "0017_designfiles_sops"),
    ]

    operations = [
        migrations.AddField(
            model_name="designfile",
            name="store",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="design_files", to="handoff.store"),
        ),
        migrations.AddField(
            model_name="designhistory",
            name="store",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="design_history", to="handoff.store"),
        ),
    ]
