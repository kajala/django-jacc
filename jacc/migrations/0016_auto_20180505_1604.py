# Generated by Django 2.0.4 on 2018-05-05 16:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("jacc", "0015_auto_20180505_1512"),
    ]

    operations = [
        migrations.AlterField(
            model_name="entrytype",
            name="code",
            field=models.CharField(db_index=True, max_length=64, unique=True, verbose_name="code"),
        ),
        migrations.AlterField(
            model_name="entrytype",
            name="name",
            field=models.CharField(blank=True, db_index=True, default="", max_length=128, verbose_name="name"),
        ),
    ]
