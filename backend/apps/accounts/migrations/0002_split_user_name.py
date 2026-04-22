"""Split User.name into first_name / last_name.

Pre-launch schema change: no production users exist yet, but the data-migration
step below is written to be safe even if a few rows have been created locally.
The split strategy is simple: first space becomes the boundary; rows with no
space put the entire string in first_name and leave last_name empty.
"""
from django.db import migrations, models


def forward_split(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for user in User.objects.all():
        raw = (user.name or "").strip()
        if not raw:
            user.first_name = ""
            user.last_name = ""
        elif " " in raw:
            first, rest = raw.split(" ", 1)
            user.first_name = first[:75]
            user.last_name = rest.strip()[:75]
        else:
            user.first_name = raw[:75]
            user.last_name = ""
        user.save(update_fields=["first_name", "last_name"])


def backward_join(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for user in User.objects.all():
        joined = f"{user.first_name} {user.last_name}".strip()
        user.name = joined[:150]
        user.save(update_fields=["name"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="first_name",
            field=models.CharField(default="", max_length=75),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="user",
            name="last_name",
            field=models.CharField(blank=True, default="", max_length=75),
            preserve_default=False,
        ),
        migrations.RunPython(forward_split, backward_join),
        migrations.RemoveField(
            model_name="user",
            name="name",
        ),
    ]
