# Generated by Django 2.2 on 2019-12-02 23:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jacc', '0019_entrytype_identifier'),
    ]

    operations = [
        migrations.AlterField(
            model_name='account',
            name='name',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64, verbose_name='name'),
        ),
    ]
