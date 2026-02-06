from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("handoff", "0014_etsy_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="Store",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200, unique=True)),
                ("order", models.PositiveIntegerField(default=1)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["order", "name", "id"],
            },
        ),
        migrations.CreateModel(
            name="TaskPublication",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("QUEUED", "Queued"), ("LISTED", "Listed")], default="QUEUED", max_length=20)),
                ("listing_url", models.URLField(blank=True)),
                ("listed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("store", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="publications", to="handoff.store")),
                ("task", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="publications", to="handoff.task")),
            ],
            options={
                "ordering": ["store__order", "store__name", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="taskpublication",
            constraint=models.UniqueConstraint(fields=("task", "store"), name="unique_task_store_publication"),
        ),
    ]

