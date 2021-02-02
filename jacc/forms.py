from django import forms
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _


class ReverseChargeForm(forms.Form):
    timestamp = forms.DateTimeField(label=_("timestamp"), required=True, initial=now)
    amount = forms.DecimalField(label=_("amount"), required=True, decimal_places=2, max_digits=10)
    description = forms.CharField(
        label=_("description"),
        max_length=128,
        required=True,
        widget=forms.Textarea,
        initial=_("reverse.charge.form.default.description"),
    )
