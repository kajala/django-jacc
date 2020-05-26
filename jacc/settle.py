from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.timezone import now
from django.utils.translation import gettext as _
from jacc.models import AccountEntry, Invoice, EntryType, Account, INVOICE_CREDIT_NOTE, INVOICE_DEFAULT


@transaction.atomic
def settle_invoice(receivables_account: Account, settlement: AccountEntry, invoice: Invoice, cls, **kwargs) -> list:
    """
    Finds unpaid items in the invoice and generates entries to receivables account.
    Settlement is matched to invoice items based on entry types payback order.
    Generated payment entries have 'parent' field pointing to settlement, so that
    if settlement is (ever) deleted the payment entries will get deleted as well.
    In case of overpayment method generates entry to receivables account without matching invoice settled_item
    (only matching settled_invoice).
    :param receivables_account: Account which receives settled entries of the invoice
    :param settlement: Settlement to target to unpaid invoice items
    :param invoice: Invoice to be settled
    :param cls: Class for generated account entries, e.g. AccountEntry
    :param kwargs: Extra attributes for created for generated account entries
    :return: list (generated receivables account entries)
    """
    assert isinstance(invoice, Invoice)
    if not invoice:
        raise ValidationError('Cannot target settlement {} without settled invoice'.format(settlement))
    if not receivables_account:
        raise ValidationError('Receivables account missing. Invoice with no rows?')
    if settlement.amount is None:  # nothing to do
        return list()
    if settlement.amount < Decimal(0) and invoice.type != INVOICE_CREDIT_NOTE:
        raise ValidationError('Cannot target negative settlement {} to invoice {}'.format(settlement, invoice))
    if settlement.amount > Decimal(0) and invoice.type == INVOICE_CREDIT_NOTE:
        raise ValidationError('Cannot target positive settlement {} to credit note {}'.format(settlement, invoice))
    if settlement.type is None or not settlement.type.is_settlement:
        raise ValidationError('Cannot settle account entry {} which is not settlement'.format(settlement))

    new_payments = []
    remaining = Decimal(settlement.amount)
    timestamp = kwargs.pop('timestamp', settlement.timestamp)
    assert isinstance(invoice, Invoice)
    for item, bal in invoice.get_unpaid_items(receivables_account):
        if invoice.type == INVOICE_DEFAULT:
            if bal > Decimal(0):
                amt = min(remaining, bal)
                ae = cls.objects.create(account=receivables_account, amount=-amt, type=item.type, settled_item=item, settled_invoice=invoice,
                                        timestamp=timestamp, description=settlement.description, parent=settlement, **kwargs)
                new_payments.append(ae)
                remaining -= amt
                if remaining <= Decimal(0):
                    break
        elif invoice.type == INVOICE_CREDIT_NOTE:
            if bal < Decimal(0):
                amt = max(remaining, bal)
                ae = cls.objects.create(account=receivables_account, amount=-amt, type=item.type, settled_item=item, settled_invoice=invoice,
                                        timestamp=timestamp, description=settlement.description, parent=settlement, **kwargs)
                new_payments.append(ae)
                remaining -= amt
                if remaining >= Decimal(0):
                    break
        else:
            raise Exception('jacc.settle.settle_assigned_invoice() unimplemented for invoice type {}'.format(invoice.type))

    invoice.update_cached_fields()
    return new_payments


@transaction.atomic
def settle_assigned_invoice(receivables_account: Account, settlement: AccountEntry, cls, **kwargs) -> list:
    """
    Finds unpaid items in the invoice and generates entries to receivables account.
    Settlement is matched to invoice items based on entry types payback order.
    Generated payment entries have 'parent' field pointing to settlement, so that
    if settlement is (ever) deleted the payment entries will get deleted as well.
    In case of overpayment method generates entry to receivables account without matching invoice settled_item
    (only matching settled_invoice).
    :param receivables_account: Account which receives settled entries of the invoice
    :param settlement: Settlement to target to unpaid invoice items
    :param cls: Class for generated account entries, e.g. AccountEntry
    :param kwargs: Extra attributes for created for generated account entries
    :return: list (generated receivables account entries)
    """
    if settlement.settled_invoice is None:
        raise ValidationError('Cannot target settlement {} without settled invoice'.format(settlement))
    return settle_invoice(receivables_account, settlement, settlement.settled_invoice, cls, **kwargs)


@transaction.atomic
def settle_credit_note(credit_note: Invoice, debit_note: Invoice, cls, account: Account, **kwargs) -> list:
    """
    Settles credit note. Records settling account entries for both original invoice and the credit note
    (negative entries for the credit note).
    Default timestamp for account entries is 'created' time of the credit note, can be overriden by kwargs.
    :param credit_note: Credit note to settle
    :param debit_note: Invoice to settle
    :param cls: AccountEntry (derived) class to use for new entries
    :param account: Settlement account
    :param kwargs: Variable arguments to cls() instance creation
    :return: list of new payments
    """
    assert isinstance(credit_note, Invoice)
    assert credit_note.type == INVOICE_CREDIT_NOTE
    assert debit_note
    assert debit_note.type == INVOICE_DEFAULT

    credit = -credit_note.get_unpaid_amount()
    balance = debit_note.get_unpaid_amount()

    amt = min(balance, credit)
    amount = kwargs.pop('amount', None)
    if amount is not None:
        if amount > amt:
            raise ValidationError(_('Cannot settle credit note amount which is larger than remaining unpaid balance'))
        amt = amount

    entry_type = kwargs.pop('entry_type', None)
    if entry_type is None:
        if not hasattr(settings, 'E_CREDIT_NOTE_RECONCILIATION'):
            raise Exception('settle_credit_note() requires settings.E_CREDIT_NOTE_RECONCILIATION (account entry type code) '
                            'or entry_type to be pass in kwargs')
        entry_type = EntryType.objects.get(code=settings.E_CREDIT_NOTE_RECONCILIATION)
    description = kwargs.pop('description', _('credit.note.reconciliation'))

    pmts = []
    if amt > Decimal(0):
        timestamp = kwargs.pop('timestamp', credit_note.created or now())
        # record entry to debit note settlement account
        pmt1 = cls.objects.create(account=account, amount=amt, type=entry_type, settled_invoice=debit_note,
                                  description=description + ' #{}'.format(credit_note.number), timestamp=timestamp, **kwargs)
        pmts.append(pmt1)
        # record entry to credit note settlement account
        pmt2 = cls.objects.create(account=account, parent=pmt1, amount=-amt, type=entry_type, settled_invoice=credit_note,
                                  description=description + ' #{}'.format(debit_note.number), timestamp=timestamp, **kwargs)
        pmts.append(pmt2)

    return pmts
