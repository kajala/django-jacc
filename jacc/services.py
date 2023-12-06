from decimal import Decimal
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from jacc.models import Invoice, INVOICE_CREDIT_NOTE, INVOICE_DEFAULT


def validate_invoice_settlement_amount(inv: Invoice, amt: Decimal, field_name: str = "amount"):
    """
    Validates that settlement amount is suitable to be used to settle specific invoice.
    Args:
        inv: Invoice
        amt: Decimal, amount
        field_name: Settlement account entry amount field, default "amount"

    Returns:
        None
    """
    if amt is None:
        raise ValidationError({field_name: _("Field value missing")})
    if amt == Decimal("0.00"):
        raise ValidationError({field_name: _("Amount cannot be zero")})
    if inv.type == INVOICE_DEFAULT and amt < Decimal("0.00"):
        raise ValidationError({field_name: _("Debit note settlement amount cannot be negative")})
    if inv.type == INVOICE_CREDIT_NOTE and amt > Decimal("0.00"):
        raise ValidationError({field_name: _("Credit note settlement amount cannot be positive")})
    unpaid_amt = inv.unpaid_amount or Decimal("0.00")
    if abs(amt) > abs(unpaid_amt):
        raise ValidationError({field_name: _("Settlement amount exceeds invoice unpaid amount")})
