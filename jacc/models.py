"""
Double entry accounting system:

A debit is an accounting entry that either increases an asset or expense account,
or decreases a liability or equity account. It is positioned to the left in an accounting entry.
Debit means "left", dividends/expenses/assets/losses increased with debit.

A credit is an accounting entry that either increases a liability or equity account,
or decreases an asset or expense account.
Credit means "right", gains/income/revenues/liabilities/equity increased with credit.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from math import floor

from jacc.helpers import sum_queryset
from django.conf import settings
from django.db import models, transaction
from django.db.models import QuerySet, Q
from django.utils.timezone import now
from jutil.cache import CachedFieldsMixin
from jutil.dict import choices_label
from django.utils.translation import ugettext_lazy as _


CATEGORY_ANY = ''
CATEGORY_DEBIT = 'D'  # "left", dividends/expenses/assets/losses increased with debit
CATEGORY_CREDIT = 'C'  # "right", gains/income/revenues/liabilities/equity increased with credit

CATEGORY_TYPE = (
    (CATEGORY_ANY, ''),
    (CATEGORY_DEBIT, _('Debit')),
    (CATEGORY_CREDIT, _('Credit')),
)

CURRENCY_TYPE = (
    ('EUR', 'EUR'),
    ('USD', 'USD'),
)

INVOICE_NOT_DUE_YET = 'N'
INVOICE_DUE = 'D'
INVOICE_LATE = 'L'
INVOICE_PAID = 'P'

INVOICE_STATE = (
    (INVOICE_NOT_DUE_YET, _('Not due yet')),
    (INVOICE_DUE, _('Due')),
    (INVOICE_LATE, _('Late')),
    (INVOICE_PAID, _('Paid')),
)

INVOICE_DEFAULT = 'I1'
INVOICE_CREDIT_NOTE = 'I2'

INVOICE_TYPE = (
    (INVOICE_DEFAULT, _('Invoice')),
    (INVOICE_CREDIT_NOTE, _('Credit Note')),
)


class AccountEntrySourceFile(models.Model):
    """
    Account entry source is set for entries based on some event like payment file import
    """
    name = models.CharField(verbose_name=_('name'), max_length=255, db_index=True, blank=True, default='')
    created = models.DateTimeField(verbose_name=_('created'), default=now, db_index=True, editable=False, blank=True)
    last_modified = models.DateTimeField(verbose_name=_('last modified'), auto_now=True, db_index=True, editable=False, blank=True)

    class Meta:
        verbose_name = _('account entry source file')
        verbose_name_plural = _('account entry source files')

    def __str__(self):
        return '[{}] {}'.format(self.id, self.name)


class EntryType(models.Model):
    code = models.CharField(verbose_name=_('code'), max_length=32, db_index=True, unique=True)
    name = models.CharField(verbose_name=_('name'), max_length=64, db_index=True, unique=True)
    created = models.DateTimeField(verbose_name=_('created'), default=now, db_index=True, editable=False, blank=True)
    last_modified = models.DateTimeField(verbose_name=_('last modified'), auto_now=True, db_index=True, editable=False, blank=True)
    payback_priority = models.SmallIntegerField(verbose_name=_('payback priority'), default=0, blank=True, db_index=True)
    is_settlement = models.BooleanField(verbose_name=_('is settlement'), default=False, blank=True, db_index=True)
    is_payment = models.BooleanField(verbose_name=_('is payment'), default=False, blank=True, db_index=True)

    class Meta:
        verbose_name = _('entry type')
        verbose_name_plural = _('entry types')

    def __str__(self):
        return str(self.name)


class AccountEntryManager(models.Manager):
    pass


class AccountEntry(models.Model):
    """
    Single mutation in account state.
    """
    objects = AccountEntryManager()
    account = models.ForeignKey('Account', verbose_name=_('record account'), related_name='accountentry_set', db_index=True, on_delete=models.PROTECT)
    created = models.DateTimeField(verbose_name=_('created'), default=now, db_index=True, editable=False, blank=True)
    last_modified = models.DateTimeField(verbose_name=_('last modified'), auto_now=True, editable=False, blank=True)
    timestamp = models.DateTimeField(verbose_name=_('timestamp'), default=now, db_index=True, blank=True)
    type = models.ForeignKey(EntryType, verbose_name=_('type'), related_name='+', on_delete=models.PROTECT, null=True, default=None, blank=True)
    description = models.CharField(verbose_name=_('description'), max_length=256, default='', blank=True)
    amount = models.DecimalField(verbose_name=_('amount'), max_digits=10, decimal_places=2, blank=True, default=None, null=True, db_index=True)
    source_file = models.ForeignKey(AccountEntrySourceFile, verbose_name=_('account entry source file'), related_name='+', null=True, default=None, blank=True, on_delete=models.CASCADE, help_text='Source for account entry, e.g. received payment (if any)')
    source_invoice = models.ForeignKey('Invoice', verbose_name=_('source invoice'), null=True, related_name='+', default=None, blank=True, on_delete=models.CASCADE, help_text='For invoice items')
    settled_invoice = models.ForeignKey('Invoice', verbose_name=_('settled invoice'), null=True, related_name='+', default=None, blank=True, on_delete=models.PROTECT, help_text='For incoming settlements')
    settled_item = models.ForeignKey('AccountEntry', verbose_name=_('settled item'), null=True, related_name='settlement_set', default=None, blank=True, on_delete=models.PROTECT, help_text='For matched settlements')
    parent = models.ForeignKey('AccountEntry', verbose_name=_('account.entry.parent'), related_name='child_set', db_index=True, on_delete=models.CASCADE, null=True, default=None, blank=True)
    archived = models.BooleanField(_('archived'), default=False, blank=True)

    class Meta:
        verbose_name = _('account entry')
        verbose_name_plural = _('account entries')

    def __str__(self):
        return '[{}] {} {} {}'.format(self.id, self.timestamp.date().isoformat() if self.timestamp else None, self.type, self.amount)

    @property
    def balance(self) -> Decimal:
        """
        Returns account balance after this entry.
        :return: Decimal
        """
        return sum_queryset(AccountEntry.objects.filter(account=self.account, timestamp__lte=self.timestamp).exclude(timestamp=self.timestamp, id__gt=self.id))
    balance.fget.short_description = _('balance')


class AccountType(models.Model):
    code = models.CharField(verbose_name=_('code'), max_length=32, db_index=True, unique=True)
    name = models.CharField(verbose_name=_('name'), max_length=64, db_index=True, unique=True)
    is_asset = models.BooleanField(verbose_name=_('asset'))
    created = models.DateTimeField(verbose_name=_('created'), default=now, db_index=True, editable=False, blank=True)
    last_modified = models.DateTimeField(verbose_name=_('last modified'), auto_now=True, db_index=True, editable=False, blank=True)

    class Meta:
        verbose_name = _('account type')
        verbose_name_plural = _('account types')

    def __str__(self):
        return self.name

    @property
    def is_liability(self) -> bool:
        return not self.is_asset
    is_liability.fget.short_description = _('liability')


class Account(models.Model):
    """
    Collects together accounting entries and provides summarizing functionality.
    """
    type = models.ForeignKey(AccountType, verbose_name=_('type'), related_name='+', on_delete=models.PROTECT)
    name = models.CharField(verbose_name=_('name'), max_length=32, blank=True, default='', db_index=True)
    currency = models.CharField(verbose_name=_('currency'), max_length=3, default='EUR', choices=CURRENCY_TYPE, blank=True)
    created = models.DateTimeField(verbose_name=_('created'), default=now, db_index=True, editable=False, blank=True)
    last_modified = models.DateTimeField(verbose_name=_('last modified'), auto_now=True, db_index=True, editable=False, blank=True)

    class Meta:
        verbose_name = _('account')
        verbose_name_plural = _('accounts')

    def __str__(self):
        return '[{}] {}'.format(self.id, self.name if self.name else self.type)

    def is_asset(self) -> bool:
        return self.type.is_asset
    is_asset.boolean = True
    is_asset.short_description = _('asset')

    def is_liability(self) -> bool:
        return self.type.is_liability
    is_liability.boolean = True
    is_liability.short_description = _('liability')

    @property
    def balance(self) -> Decimal:
        return sum_queryset(self.accountentry_set.all())
    balance.fget.short_description = _('balance')

    def get_balance(self, t: datetime):
        """
        Returns account balance before specified datetime (excluding entries on the datetime).
        :param t: datetime
        :return: Decimal
        """
        return sum_queryset(self.accountentry_set.all().filter(timestamp__lt=t))

    def needs_settling(self, e: AccountEntry) -> bool:
        """
        Returns True if all of following conditions are True:
        a) entry type is settlement
        b) entry has been recorded to this account
        c) invoice to be settled has been set
        d) entry has not been settled (=child set empty)
        :param e: AccountEntry (settlement)
        :return: bool
        """
        return e.type and e.type.is_settlement and e.account.id == self.id and e.settled_invoice and AccountEntry.objects.filter(parent=e).count() == 0


class InvoiceManager(models.Manager):
    @transaction.atomic
    def update_cached_fields(self, **kw):
        for obj in self.filter(**kw):
            obj.update_cached_fields()


def get_default_due_date():
    return now() + timedelta(days=settings.DEFAULT_DUE_DATE_DAYS) if hasattr(settings, 'DEFAULT_DUE_DATE_DAYS') else None


class Invoice(models.Model, CachedFieldsMixin):
    """
    Invoice model. Typically used as base model for actual app-specific invoice model.

    Convention for naming date/time variables:
    1) date fields are suffixed with _date if they are either plain date fields or interpreted as such (due_date)
    2) natural datetime fields are in past tense, e.g. created, sent (instead of create_date, send_date)

    Note: It is useful sometimes to have full datetime with timezone even for plain dates like due_date,
    because this to be processing to be independent of server, client and invoice time zones.
    """
    objects = InvoiceManager()
    type = models.CharField(verbose_name=_('type'), max_length=2, db_index=True, default=INVOICE_DEFAULT, blank=True, choices=INVOICE_TYPE)
    number = models.IntegerField(verbose_name=_('invoice number'), default=None, null=True, blank=True, db_index=True)
    created = models.DateTimeField(verbose_name=_('created'), default=now, db_index=True, editable=False, blank=True)
    last_modified = models.DateTimeField(verbose_name=_('last modified'), auto_now=True, db_index=True, editable=False, blank=True)
    sent = models.DateTimeField(verbose_name=_('sent'), db_index=True, default=None, blank=True, null=True)
    due_date = models.DateTimeField(verbose_name=_('due date'), db_index=True, default=get_default_due_date)
    notes = models.TextField(verbose_name=_('notes'), blank=True, default='')
    filename = models.CharField(verbose_name=_('filename'), max_length=255, blank=True, default='', db_index=True)
    amount = models.DecimalField(verbose_name=_('amount'), max_digits=10, decimal_places=2, default=0, blank=True)
    paid_amount = models.DecimalField(verbose_name=_('paid amount'), max_digits=10, decimal_places=2, editable=False, blank=True, null=True, default=None, db_index=True)
    unpaid_amount = models.DecimalField(verbose_name=_('unpaid amount'), max_digits=10, decimal_places=2, editable=False, blank=True, null=True, default=None, db_index=True)
    overpaid_amount = models.DecimalField(verbose_name=_('overpaid amount'), max_digits=10, decimal_places=2, editable=False, blank=True, null=True, default=None, db_index=True)
    close_date = models.DateTimeField(verbose_name=_('close date'), default=None, null=True, blank=True, db_index=True)
    late_days = models.SmallIntegerField(verbose_name=_('late days'), default=None, null=True, blank=True, db_index=True)
    state = models.CharField(verbose_name=_('state'), max_length=1, blank=True, default='', db_index=True, choices=INVOICE_STATE)
    cached_fields = [
        'amount',
        'paid_amount',
        'unpaid_amount',
        'overpaid_amount',
        'close_date',
        'late_days',
        'state',
    ]

    class Meta:
        verbose_name = _('invoice')
        verbose_name_plural = _('invoices')

    def __str__(self):
        return '[{}] {} {}'.format(self.id, self.due_date.date().isoformat() if self.due_date else '', self.amount)

    @property
    def receivables_account(self) -> Account:
        """
        Returns receivables account. Receivables account is assumed to be the one were invoice rows were recorded.
        :return: Account or None
        """
        row = AccountEntry.objects.filter(source_invoice=self).order_by('id').first()
        return row.account if row else None

    @property
    def currency(self) -> str:
        recv = self.receivables_account
        return recv.currency if recv else ''

    def get_entries(self, acc: Account, cls=AccountEntry) -> QuerySet:
        """
        Returns entries related to this invoice on specified account.
        :param acc: Account
        :param cls: AccountEntry class
        :return: QuerySet
        """
        return cls.objects.filter(Q(account=acc) & (Q(source_invoice=self) | Q(settled_invoice=self))) if acc else cls.objects.none()

    def get_balance(self, acc: Account) -> Decimal:
        """
        Returns balance of this invoice on specified account.
        :param acc: Account
        :return:
        """
        return sum_queryset(self.get_entries(acc))

    def get_item_balances(self, acc: Account) -> list:
        """
        Returns balances of items of the invoice.
        :param acc: Account
        :return: list (AccountEntry, Decimal) in item id order
        """
        items = []
        entries = self.get_entries(acc)
        for item in entries.filter(source_invoice=self).order_by('id'):
            assert isinstance(item, AccountEntry)
            settlements = sum_queryset(entries.filter(settled_item=item))
            bal = item.amount + settlements if item.amount is not None else settlements
            items.append((item, bal))
        return items

    def get_unpaid_items(self, acc: Account) -> list:
        """
        Returns unpaid items of the invoice in payback priority order.
        :param acc: Account
        :return: list (AccountEntry, Decimal) in payback priority order
        """
        unpaid_items = []
        for item, bal in self.get_item_balances(acc):
            assert isinstance(item, AccountEntry)
            if self.type == INVOICE_DEFAULT:
                if bal > Decimal(0):
                    unpaid_items.append((item.type.payback_priority, item, bal))
            elif self.type == INVOICE_CREDIT_NOTE:
                if bal < Decimal(0):
                    unpaid_items.append((item.type.payback_priority, item, bal))
            else:
                raise Exception('jacc.models.Invoice.get_unpaid_items() unimplemented for invoice type {}'.format(self.type))
        return [i[1:] for i in sorted(unpaid_items, key=lambda x: x[0])]

    def get_amount(self) -> Decimal:
        return sum_queryset(self.items, 'amount')

    @property
    def receivables(self) -> QuerySet:
        return self.get_entries(self.receivables_account)

    @property
    def items(self) -> QuerySet:
        return self.receivables.filter(source_invoice=self)

    def get_paid_amount(self) -> Decimal:
        return self.get_amount() - self.get_unpaid_amount()

    def get_unpaid_amount(self) -> Decimal:
        return sum_queryset(self.receivables)

    def get_overpaid_amount(self) -> Decimal:
        if self.type == INVOICE_CREDIT_NOTE:
            return max(Decimal('0.00'), sum_queryset(self.receivables))
        else:
            return max(Decimal('0.00'), -sum_queryset(self.receivables))

    @property
    def is_paid(self) -> bool:
        if self.type == INVOICE_CREDIT_NOTE:
            return self.unpaid_amount >= Decimal('0.00')
        else:
            return self.unpaid_amount <= Decimal('0.00')
    is_paid.fget.short_description = _('is paid')

    @property
    def is_due(self) -> bool:
        return not self.is_paid and now() >= self.due_date
    is_due.fget.short_description = _('is due')

    def get_close_date(self) -> datetime:
        recv = self.receivables.order_by('-timestamp', '-id')
        first = recv.first()
        if first is None:
            return None
        total = sum_queryset(recv)
        if self.type == INVOICE_CREDIT_NOTE:
            if total >= Decimal('0.00'):
                return first.timestamp
        else:
            if total <= Decimal('0.00'):
                return first.timestamp
        return None

    def get_late_days(self) -> int:
        t = self.close_date
        if not t:
            t = now()
        return int(floor((t - self.due_date).total_seconds() / 86400.0))

    @property
    def is_late(self) -> bool:
        return not self.is_paid and self.late_days >= settings.LATE_LIMIT_DAYS

    def get_state(self) -> str:
        if self.is_paid:
            return INVOICE_PAID
        t = now()
        if t - self.due_date >= timedelta(days=settings.LATE_LIMIT_DAYS):
            return INVOICE_LATE
        if t >= self.due_date:
            return INVOICE_DUE
        return INVOICE_NOT_DUE_YET

    def get_state_name(self) -> str:
        return choices_label(INVOICE_STATE, self.get_state())

    @property
    def state_name(self) -> str:
        return choices_label(INVOICE_STATE, self.state)
    state_name.fget.short_description = _('state')


class Contract(models.Model):
    """
    Base class for contracts (e.g. rent contracts, loans, etc.)
    """
    created = models.DateTimeField(verbose_name=_('created'), default=now, db_index=True, editable=False, blank=True)
    last_modified = models.DateTimeField(verbose_name=_('last modified'), auto_now=True, db_index=True, editable=False, blank=True)
    name = models.CharField(verbose_name=_('name'), max_length=128, default='', blank=True, db_index=True)

    class Meta:
        verbose_name = _('contract')
        verbose_name_plural = _('contracts')

    def __str__(self):
        return '[{}]'.format(self.id)
