# pylint: disable=protected-access
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Sequence, Any
from django.contrib import messages
from django.contrib.admin import SimpleListFilter
from django.contrib.messages import add_message, INFO
from django.db.models.functions import Coalesce
from django import forms
from django.urls import reverse, ResolverMatch
from django.utils.formats import date_format
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.text import format_lazy
from jacc.models import Account, AccountEntry, Invoice, AccountType, EntryType, AccountEntrySourceFile, INVOICE_STATE
from django.conf import settings
from django.conf.urls import url
from django.contrib import admin
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import QuerySet, Sum, Count
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from jacc.settle import settle_assigned_invoice
from jutil.admin import ModelAdminBase, admin_log
from jutil.dict import choices_label


def align_lines(lines: list, column_separator: str = '|') -> list:
    """
    Pads lines so that all rows in single column match. Columns separated by '|' in every line.
    :param lines: list of lines
    :param column_separator: column separator. default is '|'
    :return: list of lines
    """
    rows = []
    col_len: List[int] = []
    for line in lines:
        line = str(line)
        cols = []
        for col_index, col in enumerate(line.split(column_separator)):
            col = str(col).strip()
            cols.append(col)
            if col_index >= len(col_len):
                col_len.append(0)
            col_len[col_index] = max(col_len[col_index], len(col))
        rows.append(cols)

    lines_out: List[str] = []
    for row in rows:
        cols_out = []
        for col_index, col in enumerate(row):
            if col_index == 0:
                col = col.ljust(col_len[col_index])
            else:
                col = col.rjust(col_len[col_index])
            cols_out.append(col)
        lines_out.append(' '.join(cols_out))
    return lines_out


def refresh_cached_fields(modeladmin, request, qs):  # pylint: disable=unused-argument
    for e in qs:
        e.update_cached_fields()
    add_message(request, messages.SUCCESS, 'Cached fields refreshed ({})'.format(qs.count()))


def summarize_account_entries(modeladmin, request, qs):  # pylint: disable=unused-argument
    # {total_count} entries:
    # {amount1} {currency} x {count1} = {total1} {currency}
    # {amount2} {currency} x {count2} = {total2} {currency}
    # Total {total_amount} {currency}
    e_type_entries = list(qs.distinct('type').order_by('type'))
    total_debits = Decimal('0.00')
    total_credits = Decimal('0.00')
    lines = ['<pre>',
             _('({total_count} account entries)').format(total_count=qs.count())]
    for e_type_entry in e_type_entries:
        assert isinstance(e_type_entry, AccountEntry)
        e_type = e_type_entry.type
        assert isinstance(e_type, EntryType)

        qs2 = qs.filter(type=e_type)
        res_debit = qs2.filter(amount__gt=0).aggregate(total=Coalesce(Sum('amount'), 0), count=Count('amount'))
        res_credit = qs2.filter(amount__lt=0).aggregate(total=Coalesce(Sum('amount'), 0), count=Count('amount'))
        lines.append('{type_name} (debit) | x{count} | {total:.2f}'.format(type_name=e_type.name, **res_debit))
        lines.append('{type_name} (credit) | x{count} | {total:.2f}'.format(type_name=e_type.name, **res_credit))
        total_debits += res_debit['total']
        total_credits += res_credit['total']

    lines.append(_('Total debits {total_debits:.2f} | - total credits {total_credits:.2f} | = {total_amount:.2f}').format(
        total_debits=total_debits, total_credits=total_credits, total_amount=total_debits + total_credits))
    lines = align_lines(lines, '|')
    messages.add_message(request, INFO, format_html('<br>'.join(lines)), extra_tags='safe')


class SettlementAccountEntryFilter(SimpleListFilter):
    title = _('settlement')
    parameter_name = 'is_settlement'

    def lookups(self, request, model_admin):
        return [
            ('1', _('settlement')),
            ('0', _('not settlement')),
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            if val == '1':
                queryset = queryset.filter(parent=None, type__is_settlement=True)
            elif val == '0':
                queryset = queryset.exclude(type__is_settlement=True)
        return queryset


class EntryTypeAccountEntryFilter(SimpleListFilter):
    title = _('account entry type')
    parameter_name = 'type'

    def lookups(self, request, model_admin):
        a = []
        for e in EntryType.objects.all().filter(is_settlement=True).order_by('name'):
            a.append((e.code, e.name))
        return a

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            queryset = queryset.filter(type__code=val)
        return queryset


class AccountTypeAccountEntryFilter(SimpleListFilter):
    title = _('account type')
    parameter_name = 'atype'

    def lookups(self, request, model_admin):
        a = []
        for e in AccountType.objects.all().order_by('name'):
            a.append((e.code, e.name))
        return a

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            queryset = queryset.filter(account__type__code=val)
        return queryset


class AccountEntryAdminForm(forms.ModelForm):
    def clean(self):
        if self.instance.archived:
            raise ValidationError(_('cannot.modify.archived.account.entry'))
        return super().clean()


class AccountEntryAdmin(ModelAdminBase):
    form = AccountEntryAdminForm
    date_hierarchy = 'timestamp'
    list_per_page = 50
    actions = [
        summarize_account_entries,
    ]
    list_display: Sequence[str] = [
        'id',
        'timestamp',
        'type',
        'amount',
        'account_link',
        'source_invoice_link',
        'settled_invoice_link',
        'settled_item_link',
        'source_file_link',
        'parent',
    ]
    raw_id_fields: Sequence[str] = [
        'account',
        'source_file',
        'type',
        'parent',
        'source_invoice',
        'settled_invoice',
        'settled_item',
        'parent',
    ]
    ordering: Sequence[str] = [
        '-id',
    ]
    search_fields: Sequence[str] = [
        'description',
        '=amount',
    ]
    fields: Sequence[str] = [
        'id',
        'account',
        'timestamp',
        'created',
        'last_modified',
        'type',
        'description',
        'amount',
        'source_file',
        'source_invoice',
        'settled_invoice',
        'settled_item',
        'parent',
        'archived',
    ]
    readonly_fields: Sequence[str] = [
        'id',
        'created',
        'last_modified',
        'balance',
        'source_invoice_link',
        'settled_invoice_link',
        'settled_item_link',
        'archived',
    ]
    list_filter: Sequence[Any] = [
        SettlementAccountEntryFilter,
        EntryTypeAccountEntryFilter,
        AccountTypeAccountEntryFilter,
        'archived',
    ]
    account_admin_change_view_name = 'admin:jacc_account_change'
    invoice_admin_change_view_name = 'admin:jacc_invoice_change'
    accountentrysourcefile_admin_change_view_name = 'admin:jacc_accountentrysourcefile_change'
    accountentry_admin_change_view_name = 'admin:jacc_accountentry_change'
    allow_add = False
    allow_delete = False
    allow_change = False

    def source_file_link(self, obj):
        assert isinstance(obj, AccountEntry)
        if not obj.source_file:
            return ''
        admin_url = reverse(self.accountentrysourcefile_admin_change_view_name, args=(obj.source_file.id, ))
        return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.source_file)
    source_file_link.admin_order_field = 'source_file'  # type: ignore
    source_file_link.short_description = _('account entry source file')  # type: ignore

    def account_link(self, obj):
        admin_url = reverse(self.account_admin_change_view_name, args=(obj.account.id, ))
        return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.account)
    account_link.admin_order_field = 'account'  # type: ignore
    account_link.short_description = _('account')  # type: ignore

    def source_invoice_link(self, obj):
        if not obj.source_invoice:
            return ''
        admin_url = reverse(self.invoice_admin_change_view_name, args=(obj.source_invoice.id, ))
        return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.source_invoice)
    source_invoice_link.admin_order_field = 'source_invoice'  # type: ignore
    source_invoice_link.short_description = _('source invoice')  # type: ignore

    def settled_invoice_link(self, obj):
        if not obj.settled_invoice:
            return ''
        admin_url = reverse(self.invoice_admin_change_view_name, args=(obj.settled_invoice.id, ))
        return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.settled_invoice)
    settled_invoice_link.admin_order_field = 'settled_invoice'  # type: ignore
    settled_invoice_link.short_description = _('settled invoice')  # type: ignore

    def settled_item_link(self, obj):
        if not obj.settled_item:
            return ''
        admin_url = reverse(self.accountentry_admin_change_view_name, args=(obj.settled_item.id, ))
        return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.settled_item)
    settled_item_link.admin_order_field = 'settled_item'  # type: ignore
    settled_item_link.short_description = _('settled item')  # type: ignore

    def get_urls(self):
        info = self.model._meta.app_label, self.model._meta.model_name
        return [
            url(r'^by-account/(?P<pk>\d+)/$', self.admin_site.admin_view(self.kw_changelist_view), name='%s_%s_account_changelist' % info),
            url(r'^by-source-invoice/(?P<pk>\d+)/$', self.admin_site.admin_view(self.kw_changelist_view), name='%s_%s_source_invoice_changelist' % info),
            url(r'^by-settled-invoice/(?P<pk>\d+)/$', self.admin_site.admin_view(self.kw_changelist_view), name='%s_%s_settled_invoice_changelist' % info),
            url(r'^by-source-file/(?P<pk>\d+)/$', self.admin_site.admin_view(self.kw_changelist_view), name='%s_%s_sourcefile_changelist' % info),
        ] + super().get_urls()

    def get_queryset(self, request: HttpRequest):
        qs = super().get_queryset(request)
        rm = request.resolver_match
        assert isinstance(rm, ResolverMatch)
        pk = rm.kwargs.get('pk', None)
        if rm.url_name == 'jacc_accountentry_account_changelist' and pk:
            return qs.filter(account=pk)
        if rm.url_name == 'jacc_accountentry_sourcefile_invoice_changelist' and pk:
            return qs.filter(source_invoice=pk)
        if rm.url_name == 'jacc_accountentry_settled_invoice_changelist' and pk:
            return qs.filter(settled_invoice=pk)
        if rm.url_name == 'jacc_accountentry_sourcefile_changelist' and pk:
            return qs.filter(source_file=pk)
        return qs


class AccountAdmin(ModelAdminBase):
    list_display: Sequence[str] = [
        'id',
        'type',
        'name',
        'balance',
        'currency',
        'is_asset',
    ]
    fields: Sequence[str] = [
        'id',
        'type',
        'name',
        'balance',
        'currency',
    ]
    readonly_fields: Sequence[str] = [
        'id',
        'balance',
        'is_asset',
    ]
    raw_id_fields: Sequence[str] = [
        'type',
    ]
    ordering: Sequence[str] = [
        '-id',
    ]
    list_filter: Sequence[Any] = [
        'type',
        'type__is_asset',
    ]
    allow_add = True
    allow_delete = True
    list_per_page = 20


class AccountEntryInlineFormSet(forms.BaseInlineFormSet):
    def clean_entries(self, source_invoice: Optional[Invoice], settled_invoice: Optional[Invoice], account: Optional[Account], **kw):
        """
        This needs to be called from a derived class clean().
        :param source_invoice:
        :param settled_invoice:
        :param account:
        :return: None
        """
        for form in self.forms:
            obj = form.instance
            assert isinstance(obj, AccountEntry)
            if account is not None:
                obj.account = account
            obj.source_invoice = source_invoice
            obj.settled_invoice = settled_invoice
            if obj.parent:
                if obj.amount is None:
                    obj.amount = obj.parent.amount
                if obj.type is None:
                    obj.type = obj.parent.type
                if obj.amount is not None and obj.parent.amount is not None:
                    if obj.amount > obj.parent.amount > Decimal(0) or obj.amount < obj.parent.amount < Decimal(0):
                        raise ValidationError(_('Derived account entry amount cannot be larger than original'))
            for k, v in kw.items():
                setattr(obj, k, v)


class SingleReceivablesAccountInvoiceItemInlineFormSet(AccountEntryInlineFormSet):
    def clean(self):
        instance = self.instance
        assert isinstance(instance, Invoice)
        receivables_account = Account.objects.get(type__code=settings.ACCOUNT_RECEIVABLES)
        self.clean_entries(instance, None, receivables_account)


class SingleSettlementsAccountSettlementInlineFormSet(AccountEntryInlineFormSet):
    def clean(self):
        instance = self.instance
        assert isinstance(instance, Invoice)
        settlement_account = Account.objects.get(type__code=settings.ACCOUNT_SETTLEMENTS)
        self.clean_entries(None, instance, settlement_account)

    def save(self, commit=True):
        instance = self.instance
        assert isinstance(instance, Invoice)
        entries = super().save(commit)
        settlement_account = Account.objects.get(type__code=settings.ACCOUNT_SETTLEMENTS)
        assert isinstance(settlement_account, Account)
        for e in entries:
            if settlement_account.needs_settling(e):
                settle_assigned_invoice(instance.receivables_account, e, AccountEntry)
        return entries


class InvoiceItemInline(admin.TabularInline):  # TODO: override in app
    model = AccountEntry
    formset = SingleReceivablesAccountInvoiceItemInlineFormSet  # TODO: override in app
    fk_name = 'source_invoice'
    verbose_name = _('invoice items')
    verbose_name_plural = _('invoices items')
    extra = 0
    can_delete = True
    account_entry_change_view_name = 'admin:jacc_accountentry_change'
    fields = [
        'id_link',
        'timestamp',
        'type',
        'description',
        'amount',
    ]
    raw_id_fields = [
        'account',
        'type',
        'source_invoice',
        'settled_invoice',
        'settled_item',
        'source_file',
        'parent',
    ]
    readonly_fields = [
        'id_link',
    ]

    def id_link(self, obj):
        if obj and obj.id:
            assert isinstance(obj, AccountEntry)
            admin_url = reverse(self.account_entry_change_view_name, args=(obj.id, ))
            return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.id)
        return ''
    id_link.admin_order_field = 'id'  # type: ignore
    id_link.short_description = _('id')  # type: ignore

    def get_queryset(self, request):
        queryset = self.model._default_manager.get_queryset().filter(type__is_settlement=False)
        if not self.has_change_permission(request):
            queryset = queryset.none()
        return queryset

    def get_field_queryset(self, db, db_field, request):
        related_admin = self.admin_site._registry.get(db_field.remote_field.model)
        if related_admin and db_field.name == 'type':
            return related_admin.get_queryset(request).filter(is_settlement=False).order_by('name')
        return super().get_field_queryset(db, db_field, request)


class InvoiceSettlementInline(admin.TabularInline):  # TODO: override in app
    model = AccountEntry
    formset = SingleSettlementsAccountSettlementInlineFormSet  # TODO: override in app
    fk_name = 'settled_invoice'
    verbose_name = _('settlements')
    verbose_name_plural = _('settlements')
    show_non_settlements = False
    extra = 0
    can_delete = True
    account_entry_change_view_name = 'admin:jacc_accountentry_change'  # TODO: override in app
    account_change_view_name = 'admin:jacc_account_change'  # TODO: override in app
    fields = [
        'id_link',
        'account_link',
        'timestamp',
        'type',
        'description',
        'amount',
        'parent',
        'settled_item',
    ]
    raw_id_fields = [
        'account',
        'type',
        'source_invoice',
        'settled_invoice',
        'source_file',
        'parent',
        'settled_item',
    ]
    readonly_fields = [
        'id_link',
        'account_link',
        'settled_item',
    ]

    def get_queryset(self, request):
        queryset = self.model._default_manager.get_queryset()
        if not self.show_non_settlements:
            queryset = queryset.filter(type__is_settlement=True)
        if not self.has_change_permission(request):
            queryset = queryset.none()
        return queryset

    def get_field_queryset(self, db, db_field, request):
        related_admin = self.admin_site._registry.get(db_field.remote_field.model)
        if related_admin and db_field.name == 'type' and not self.show_non_settlements:
            return related_admin.get_queryset(request).filter(is_settlement=True).order_by('name')
        return super().get_field_queryset(db, db_field, request)

    def id_link(self, obj):
        if obj and obj.id:
            assert isinstance(obj, AccountEntry)
            admin_url = reverse(self.account_entry_change_view_name, args=(obj.id, ))
            return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.id)
        return ''
    id_link.admin_order_field = 'id'  # type: ignore
    id_link.short_description = _('id')  # type: ignore

    def account_link(self, obj):
        if obj and obj.id:
            assert isinstance(obj, AccountEntry)
            admin_url = reverse(self.account_change_view_name, args=(obj.account.id, ))
            return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.account)
        return ''
    account_link.admin_order_field = 'account'  # type: ignore
    account_link.short_description = _('account')  # type: ignore


def resend_invoices(modeladmin, request: HttpRequest, queryset: QuerySet):  # pylint: disable=unused-argument
    """
    Marks invoices with as un-sent.
    :param modeladmin:
    :param request:
    :param queryset:
    :return:
    """
    user = request.user
    assert isinstance(user, User)
    for obj in queryset:
        assert isinstance(obj, Invoice)
        admin_log([obj, user], 'Invoice id={invoice} marked for re-sending'.format(invoice=obj.id), who=user)
    queryset.update(sent=None)


class InvoiceLateDaysFilter(SimpleListFilter):
    title = _('late days')
    parameter_name = 'late_days_range'

    def lookups(self, request, model_admin):
        if hasattr(settings, 'INVOICE_LATE_DAYS_LIST_FILTER'):
            return settings.INVOICE_LATE_DAYS_LIST_FILTER
        return [
            ('<0', _('late.days.filter.not.due')),
            ('0<7', format_lazy(_('late.days.filter.late.range'), 1, 7)),
            ('7<14', format_lazy(_('late.days.filter.late.range'), 7, 14)),
            ('14<21', format_lazy(_('late.days.filter.late.range'), 14, 21)),
            ('21<28', format_lazy(_('late.days.filter.late.range'), 21, 28)),
            ('28<', format_lazy(_('late.days.filter.late.over.days'), 28)),
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            begin, end = str(val).split('<')
            if begin:
                queryset = queryset.filter(late_days__gte=int(begin))
            if end:
                queryset = queryset.filter(late_days__lt=int(end))
        return queryset


def summarize_invoice_statistics(modeladmin, request: HttpRequest, qs: QuerySet):  # pylint: disable=unused-argument
    invoice_states = list([state for state, name in INVOICE_STATE])

    invoiced_total_amount = Decimal('0.00')
    invoiced_total_count = 0

    lines = [
        '<pre>',
        _('({total_count} invoices)').format(total_count=qs.count()),
    ]
    for state in invoice_states:
        state_name = choices_label(INVOICE_STATE, state)
        qs2 = qs.filter(state=state)

        invoiced = qs2.filter(state=state).aggregate(amount=Coalesce(Sum('amount'), 0), count=Count('*'))
        invoiced_amount = Decimal(invoiced['amount'])
        invoiced_count = int(invoiced['count'])
        invoiced_total_amount += invoiced_amount
        invoiced_total_count += invoiced_count

        lines.append('{state_name} | x{count} | {amount:.2f}'.format(
            state_name=state_name, amount=invoiced_amount, count=invoiced_count))

    lines.append(_('Total') + ' {label} | x{count} | {amount:.2f}'.format(
        label=_('amount'), amount=invoiced_total_amount, count=invoiced_total_count))
    lines.append('</pre>')

    lines = align_lines(lines, '|')
    messages.add_message(request, INFO, format_html('<br>'.join(lines)), extra_tags='safe')


class InvoiceAdmin(ModelAdminBase):
    """
    Invoice admin. Override following in derived classes:
    - InvoiceSettlementInline with formset derived from AccountEntryInlineFormSet, override clean and call clean_entries()
    - InvoiceItemsInline with formset derived from AccountEntryInlineFormSet, override clean and call clean_entries()
    - inlines = [] set with above mentioned derived classes
    """
    date_hierarchy = 'created'
    actions = [
        summarize_invoice_statistics,
        refresh_cached_fields,
        # resend_invoices,
    ]
    # override in derived class
    inlines = [
        InvoiceItemInline,  # TODO: override in app
        InvoiceSettlementInline,  # TODO: override in app
    ]
    list_display: Sequence[str] = [
        'number',
        'created_brief',
        'sent_brief',
        'due_date_brief',
        'close_date_brief',
        'late_days',
        'amount',
        'paid_amount',
        'unpaid_amount',
    ]
    fields: Sequence[str] = [
        'type',
        'number',
        'due_date',
        'notes',
        'filename',
        'amount',
        'paid_amount',
        'unpaid_amount',
        'state',
        'overpaid_amount',
        'close_date',
        'late_days',
        'created',
        'last_modified',
        'sent',
    ]
    readonly_fields: Sequence[str] = [
        'created',
        'last_modified',
        'sent',
        'close_date',
        'created_brief',
        'sent_brief',
        'due_date_brief',
        'close_date_brief',
        'filename',
        'amount',
        'paid_amount',
        'unpaid_amount',
        'state',
        'overpaid_amount',
        'late_days',
    ]
    raw_id_fields: Sequence[str] = [
    ]
    search_fields: Sequence[str] = [
        '=amount',
        '=filename',
        '=number',
    ]
    list_filter: Sequence[Any] = [
        'state',
        InvoiceLateDaysFilter,
    ]
    allow_add = True
    allow_delete = True
    ordering = ('-id', )

    def construct_change_message(self, request, form, formsets, add=False):
        instance = form.instance
        assert isinstance(instance, Invoice)
        instance.update_cached_fields()
        return super().construct_change_message(request, form, formsets, add)

    def _format_date(self, obj) -> str:
        """
        Short date format.
        :param obj: date or datetime or None
        :return: str
        """
        if obj is None:
            return ''
        if isinstance(obj, datetime):
            obj = obj.date()
        return date_format(obj, 'SHORT_DATE_FORMAT')

    def created_brief(self, obj):
        assert isinstance(obj, Invoice)
        return self._format_date(obj.created)
    created_brief.admin_order_field = 'created'  # type: ignore
    created_brief.short_description = _('created')  # type: ignore

    def sent_brief(self, obj):
        assert isinstance(obj, Invoice)
        return self._format_date(obj.sent)
    sent_brief.admin_order_field = 'sent'  # type: ignore
    sent_brief.short_description = _('sent')  # type: ignore

    def due_date_brief(self, obj):
        assert isinstance(obj, Invoice)
        return self._format_date(obj.due_date)
    due_date_brief.admin_order_field = 'due_date'  # type: ignore
    due_date_brief.short_description = _('due date')  # type: ignore

    def close_date_brief(self, obj):
        assert isinstance(obj, Invoice)
        return self._format_date(obj.close_date)
    close_date_brief.admin_order_field = 'close_date'  # type: ignore
    close_date_brief.short_description = _('close date')  # type: ignore


def set_as_asset(modeladmin, request, qs):  # pylint: disable=unused-argument
    qs.update(is_asset=True)


def set_as_liability(modeladmin, request, qs):  # pylint: disable=unused-argument
    qs.update(is_asset=False)


class AccountTypeAdmin(ModelAdminBase):
    list_display = [
        'code',
        'name',
        'is_asset',
        'is_liability',
    ]
    actions = [
        set_as_asset,
        set_as_liability,
    ]
    ordering = ('name', )
    allow_add = True
    allow_delete = True

    def is_liability(self, obj):
        return obj.is_liability
    is_liability.short_description = _('is liability')  # type: ignore
    is_liability.boolean = True  # type: ignore


class ContractAdmin(ModelAdminBase):
    list_display = [
        'id',
        'name',
    ]
    ordering = ['-id', ]
    allow_add = True
    allow_delete = True


def toggle_settlement(modeladmin, request: HttpRequest, queryset: QuerySet):  # pylint: disable=unused-argument
    for e in queryset:
        assert isinstance(e, EntryType)
        e.is_settlement = not e.is_settlement
        e.save()
        admin_log([e], 'Toggled settlement flag {}'.format('on' if e.is_settlement else 'off'), who=request.user)


def toggle_payment(modeladmin, request: HttpRequest, queryset: QuerySet):  # pylint: disable=unused-argument
    for e in queryset:
        assert isinstance(e, EntryType)
        e.is_payment = not e.is_payment
        e.save()
        admin_log([e], 'Toggled payment flag {}'.format('on' if e.is_settlement else 'off'), who=request.user)


class EntryTypeAdmin(ModelAdminBase):
    list_display = [
        'id',
        'identifier',
        'name',
        'is_settlement',
        'is_payment',
        'payback_priority',
    ]
    list_filter: Sequence[Any] = (
        'is_settlement',
        'is_payment',
    )
    search_fields: Sequence[str] = (
        'name',
        'code',
    )
    actions = [
        toggle_settlement,
        toggle_payment,
    ]
    exclude: Sequence[str] = ()
    ordering: Sequence[str] = ['name', ]
    allow_add = True
    allow_delete = True


class AccountEntrySourceFileAdmin(ModelAdminBase):
    list_display: Sequence[str] = [
        'id',
        'created',
        'entries_link',
    ]
    date_hierarchy = 'created'
    ordering: Sequence[str] = [
        '-id',
    ]
    fields: Sequence[str] = [
        'id',
        'name',
        'created',
        'last_modified',
    ]
    search_fields: Sequence[str] = [
        '=name',
    ]
    readonly_fields: Sequence[str] = [
        'id',
        'created',
        'name',
        'last_modified',
        'entries_link',
    ]
    allow_add = True
    allow_delete = True

    def entries_link(self, obj):
        if obj and obj.id:
            assert isinstance(obj, AccountEntrySourceFile)
            admin_url = reverse('admin:jacc_accountentry_sourcefile_changelist', args=(obj.id, ))
            return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.name)
        return ''
    entries_link.admin_order_field = 'name'  # type: ignore
    entries_link.short_description = _('account entry source file')  # type: ignore


resend_invoices.short_description = _('Re-send invoices')  # type: ignore
refresh_cached_fields.short_description = _('Refresh cached fields')  # type: ignore
summarize_account_entries.short_description = _('Summmarize account entries')  # type: ignore
summarize_invoice_statistics.short_description = _('Summarize invoice statistics')  # type: ignore
set_as_asset.short_description = _('set_as_asset')  # type: ignore
set_as_liability.short_description = _('set_as_liability')  # type: ignore

admin.site.register(Account, AccountAdmin)
admin.site.register(Invoice, InvoiceAdmin)  # TODO: override in app
admin.site.register(AccountEntry, AccountEntryAdmin)  # TODO: override in app
admin.site.register(AccountType, AccountTypeAdmin)
admin.site.register(EntryType, EntryTypeAdmin)
admin.site.register(AccountEntrySourceFile, AccountEntrySourceFileAdmin)
