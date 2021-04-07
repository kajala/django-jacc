from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class JaccConfig(AppConfig):
    name = "jacc"
    verbose_name = _("Accounting")
    default_auto_field = "django.db.models.AutoField"
