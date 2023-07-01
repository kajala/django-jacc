# pylint: disable=protected-access
import logging
import traceback
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence, Any, Dict
from django.contrib import messages
from django.contrib.admin import SimpleListFilter
from django.contrib.messages import add_message, INFO
from django.db import models
from django.db.models.functions import Coalesce
from django import forms
from django.shortcuts import render
from django.urls import reverse, ResolverMatch, path
from django.utils.formats import date_format
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.contrib.admin import widgets
from django.utils.text import format_lazy, capfirst
from django.utils.timezone import now
from jacc.format import align_lines
from jacc.forms import ReverseChargeForm
from jacc.models import (
    Account,
    AccountEntry,
    Invoice,
    AccountType,
    EntryType,
    AccountEntrySourceFile,
    INVOICE_STATE,
    AccountEntryNote,
    INVOICE_NOT_DUE_YET,
    INVOICE_DUE,
    INVOICE_LATE,
)
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import QuerySet, Sum, Count
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from jacc.settle import settle_assigned_invoice
from jutil.admin import ModelAdminBase, admin_log
from jutil.format import choices_label, dec2
from jutil.model import clone_model

logger = logging.getLogger(__name__)


def refresh_cached_fields(modeladmin, request, qs):  # pylint: disable=unused-argument
    n_count = 0
    for obj in qs.order_by("id").distinct():
        try:
            obj.update_cached_fields()
            n_count += 1
        except Exception as exc:
            add_message(request, messages.ERROR, f"{obj}: {exc}")
    add_message(request, messages.SUCCESS, _("Cached fields refreshed ({})").format(n_count))


def summarize_account_entries(modeladmin, request, qs):  # pylint: disable=unused-argument
    # {total_count} entries:
    # {amount1} {currency} x {count1} = {total1} {currency}
    # {amount2} {currency} x {count2} = {total2} {currency}
    # Total {total_amount} {currency}
    e_type_entries = list(qs.distinct("type").order_by("type"))
    total_debits = Decimal("0.00")
    total_credits = Decimal("0.00")
    lines = [
        "<pre>",
        _("({total_count} account entries)").format(total_count=qs.count()),
        "",
        "|".join([str(_("entry type")), str(_("count")), str(_("credit")), str(_("debit"))]),
    ]

    for e_type_entry in e_type_entries:
        assert isinstance(e_type_entry, AccountEntry)
        e_type = e_type_entry.type
        assert isinstance(e_type, EntryType)

        qs2 = qs.filter(type=e_type)
        res_debit = qs2.filter(amount__gt=0).aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")), n=Count("amount"))
        res_credit = qs2.filter(amount__lt=0).aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")), n=Count("amount"))
        lines.append(
            "{name}|{n}|{cr:.2f}|{dr:.2f}".format(name=e_type.name, n=res_credit["n"] + res_debit["n"], cr=-res_credit["total"], dr=res_debit["total"])
        )
        total_debits += res_debit["total"]
        total_credits += res_credit["total"]

    lines.append("")
    lines.append(
        _("Total debits {total_debits:.2f} | - total credits {total_credits:.2f} | = {total_amount:.2f}").format(
            total_debits=total_debits, total_credits=-total_credits, total_amount=total_debits + total_credits
        )
    )
    lines = align_lines(lines, "|")
    messages.add_message(request, INFO, format_html("<br>".join(lines)), extra_tags="safe")


class SettlementAccountEntryFilter(SimpleListFilter):
    title = _("settlement")
    parameter_name = "settlement"

    def lookups(self, request, model_admin):
        return [
            ("S", _("settlement")),
            ("P", _("payment")),
            ("N", _("non-payment settlement")),
            ("0", _("not settlement")),
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            if val == "S":
                queryset = queryset.filter(parent=None, type__is_settlement=True)
            if val == "P":
                queryset = queryset.filter(parent=None, type__is_settlement=True, type__is_payment=True)
            if val == "N":
                queryset = queryset.filter(parent=None, type__is_settlement=True, type__is_payment=False)
            elif val == "0":
                queryset = queryset.exclude(type__is_settlement=True)
        return queryset


class EntryTypeAccountEntryFilter(SimpleListFilter):
    title = _("account entry type")
    parameter_name = "type"

    def lookups(self, request, model_admin):
        a = []
        for e in EntryType.objects.all().filter(is_settlement=True).order_by("name"):
            a.append((e.code, e.name))
        return a

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            queryset = queryset.filter(type__code=val)
        return queryset


class AccountTypeAccountEntryFilter(SimpleListFilter):
    title = _("account type")
    parameter_name = "atype"

    def lookups(self, request, model_admin):
        a = []
        for e in AccountType.objects.all().order_by("name"):
            a.append((e.code, e.name))
        return a

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            queryset = queryset.filter(account__type__code=val)
        return queryset


def add_reverse_charge(modeladmin, request, qs):
    assert hasattr(modeladmin, "reverse_charge_form")
    assert hasattr(modeladmin, "reverse_charge_template")

    cx: Dict[str, Any] = {}
    try:
        if qs.count() != 1:
            raise ValidationError(_("Exactly one account entry must be selected"))
        e = qs.first()
        assert isinstance(e, AccountEntry)
        if e.amount is None or dec2(e.amount) == Decimal("0.00"):
            raise ValidationError(_("Exactly one account entry must be selected"))

        form_cls = modeladmin.reverse_charge_form  # Type: ignore
        initial = {
            "amount": -e.amount,
            "description": form_cls().fields["description"].initial,
        }
        if e.description:
            initial["description"] += " / {}".format(e.description)
        cx = {
            "qs": qs,
            "original": e,
        }

        if "save" in request.POST:
            cx["form"] = form = form_cls(request.POST, initial=initial)
            if not form.is_valid():
                raise ValidationError(form.errors)
            timestamp = form.cleaned_data["timestamp"]
            amount = form.cleaned_data["amount"]
            description = form.cleaned_data["description"]
            reverse_e = clone_model(
                e,
                parent=e.parent,
                amount=amount,
                description=description,
                timestamp=timestamp,
                commit=False,
                created=now(),
            )
            reverse_e.full_clean()
            reverse_e.save()
            messages.info(request, "{} {}".format(reverse_e, _("created")))
        else:
            cx["form"] = form = form_cls(initial=initial)
            return render(request, modeladmin.reverse_charge_template, context=cx)
    except ValidationError as e:
        if cx:
            return render(request, modeladmin.reverse_charge_template, context=cx)
        messages.error(request, "{}\n".join(e.messages))
    except Exception as e:
        logger.error("add_reverse_charge: %s", traceback.format_exc())
        messages.error(request, "{}".format(e))
    return None


class AccountEntryAdminForm(forms.ModelForm):
    def clean(self):
        if self.instance.archived:
            raise ValidationError(_("cannot.modify.archived.account.entry"))
        return super().clean()


class AccountEntryNoteInline(admin.TabularInline):
    model = AccountEntryNote
    fk_name = "account_entry"
    verbose_name = _("account entry note")
    verbose_name_plural = _("account entry notes")
    extra = 1
    can_delete = True
    fields = [
        "created",
        "note",
        "created_by",
    ]
    readonly_fields = [
        "created",
        "created_by",
    ]
    formfield_overrides = {
        models.TextField: {"widget": widgets.AdminTextareaWidget(attrs={"rows": 3})},
    }


class AccountEntryAdmin(ModelAdminBase):
    form = AccountEntryAdminForm
    date_hierarchy = "timestamp"
    list_per_page = 50
    reverse_charge_form = ReverseChargeForm
    reverse_charge_template = "admin/jacc/accountentry/reverse_entry.html"
    actions = [
        summarize_account_entries,
        add_reverse_charge,
    ]
    list_display = [
        "id",
        "timestamp",
        "account_link",
        "type",
        "amount",
        "parent",
    ]
    raw_id_fields = [
        "account",
        "source_file",
        "type",
        "parent",
        "source_invoice",
        "settled_invoice",
        "settled_item",
        "parent",
    ]
    ordering = [
        "-id",
    ]
    search_fields = [
        "=id",
        "=amount",
        "description",
    ]
    fields = [
        "id",
        "account",
        "timestamp",
        "created",
        "last_modified",
        "type",
        "description",
        "amount",
        "source_file",
        "source_invoice",
        "settled_invoice",
        "settled_item",
        "parent",
        "archived",
    ]
    readonly_fields = [
        "id",
        "created",
        "last_modified",
        "balance",
        "source_invoice_link",
        "settled_invoice_link",
        "settled_item_link",
        "archived",
    ]
    list_filter = [
        SettlementAccountEntryFilter,
        EntryTypeAccountEntryFilter,
        AccountTypeAccountEntryFilter,
        "archived",
    ]
    inlines = [
        AccountEntryNoteInline,
    ]
    account_admin_change_view_name = "admin:jacc_account_change"
    invoice_admin_change_view_name = "admin:jacc_invoice_change"
    accountentrysourcefile_admin_change_view_name = "admin:jacc_accountentrysourcefile_change"
    accountentry_admin_change_view_name = "admin:jacc_accountentry_change"
    allow_add = False
    allow_delete = False
    allow_change = False

    def fill_extra_context(self, request: HttpRequest, extra_context: Optional[Dict[str, Any]]):
        extra_context = extra_context or {}
        rm = request.resolver_match
        assert isinstance(rm, ResolverMatch)
        pk = rm.kwargs.get("account_id") or request.GET.get("account")
        if pk:
            extra_context["account"] = Account.objects.filter(id=pk).first()
        return extra_context

    def add_view(self, request: HttpRequest, form_url="", extra_context=None):
        return super().add_view(request, form_url, self.fill_extra_context(request, extra_context))

    def change_view(self, request: HttpRequest, object_id, form_url="", extra_context=None):
        return super().change_view(request, object_id, form_url, self.fill_extra_context(request, extra_context))

    def custom_changelist_view(self, request: HttpRequest, extra_context=None, **kwargs):  # pylint: disable=unused-argument
        return self.changelist_view(request, self.fill_extra_context(request, extra_context))

    def source_file_link(self, obj):
        assert isinstance(obj, AccountEntry)
        if not obj.source_file:
            return ""
        admin_url = reverse(self.accountentrysourcefile_admin_change_view_name, args=(obj.source_file.id,))
        return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.source_file)

    source_file_link.admin_order_field = "source_file"  # type: ignore
    source_file_link.short_description = _("account entry source file")  # type: ignore

    def account_link(self, obj):
        admin_url = reverse(self.account_admin_change_view_name, args=(obj.account.id,))
        return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.account)

    account_link.admin_order_field = "account"  # type: ignore
    account_link.short_description = _("account")  # type: ignore

    def source_invoice_link(self, obj):
        if not obj.source_invoice:
            return ""
        admin_url = reverse(self.invoice_admin_change_view_name, args=(obj.source_invoice.id,))
        return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.source_invoice)

    source_invoice_link.admin_order_field = "source_invoice"  # type: ignore
    source_invoice_link.short_description = _("source invoice")  # type: ignore

    def settled_invoice_link(self, obj):
        if not obj.settled_invoice:
            return ""
        admin_url = reverse(self.invoice_admin_change_view_name, args=(obj.settled_invoice.id,))
        return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.settled_invoice)

    settled_invoice_link.admin_order_field = "settled_invoice"  # type: ignore
    settled_invoice_link.short_description = _("settled invoice")  # type: ignore

    def settled_item_link(self, obj):
        if not obj.settled_item:
            return ""
        admin_url = reverse(self.accountentry_admin_change_view_name, args=(obj.settled_item.id,))
        return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.settled_item)

    settled_item_link.admin_order_field = "settled_item"  # type: ignore
    settled_item_link.short_description = _("settled item")  # type: ignore

    def parent_link(self, obj):
        if obj.parent is None:
            return ""
        admin_url = reverse(self.accountentry_admin_change_view_name, args=(obj.parent.id,))
        return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.parent)

    parent_link.admin_order_field = "parent"  # type: ignore
    parent_link.short_description = _("account.entry.parent")  # type: ignore

    def get_urls(self):
        info = self.model._meta.app_label, self.model._meta.model_name  # noqa
        return [
            path(
                "by-account/<int:account_id>/",
                self.admin_site.admin_view(self.custom_changelist_view),
                name="%s_%s_account_changelist" % info,
            ),
            path(
                "by-source-invoice/<int:source_invoice_id>/",
                self.admin_site.admin_view(self.custom_changelist_view),
                name="%s_%s_source_invoice_changelist" % info,
            ),
            path(
                "by-settled-invoice/<int:settled_invoice_id>/",
                self.admin_site.admin_view(self.custom_changelist_view),
                name="%s_%s_settled_invoice_changelist" % info,
            ),
            path(
                "by-source-file/<int:source_file_id>/",
                self.admin_site.admin_view(self.custom_changelist_view),
                name="%s_%s_sourcefile_changelist" % info,
            ),
        ] + super().get_urls()

    def get_queryset(self, request: HttpRequest):
        qs = super().get_queryset(request)
        rm = request.resolver_match
        assert isinstance(rm, ResolverMatch)
        info = self.model._meta.app_label, self.model._meta.model_name  # noqa
        account_id = rm.kwargs.get("account_id")
        if account_id:
            return qs.filter(account=account_id)
        source_file_id = rm.kwargs.get("source_file_id")
        if source_file_id:
            return qs.filter(source_file=source_file_id)
        source_invoice_id = rm.kwargs.get("source_invoice_id")
        if source_invoice_id:
            return qs.filter(source_invoice=source_invoice_id)
        settled_invoice_id = rm.kwargs.get("settled_invoice_id")
        if settled_invoice_id:
            return qs.filter(settled_invoice=settled_invoice_id)
        return qs

    def save_formset(self, request, form, formset, change):
        if formset.model == AccountEntryNote:
            AccountEntryNoteAdmin.save_account_entry_note_formset(request, form, formset, change)
        else:
            formset.save()


class AccountAdmin(ModelAdminBase):
    list_display = [
        "id",
        "type",
        "name",
        "balance",
        "currency",
        "is_asset",
    ]
    fields: Sequence[str] = ["id", "type", "name", "balance", "currency", "notes"]
    search_fields = [
        "name",
    ]
    readonly_fields = [
        "id",
        "balance",
        "is_asset",
    ]
    raw_id_fields = [
        "type",
    ]
    ordering = [
        "-id",
    ]
    list_filter = [
        "type",
        "type__is_asset",
    ]
    allow_add = True
    allow_delete = True
    list_per_page = 20


class AccountEntryInlineFormSet(forms.BaseInlineFormSet):
    def clean_entries(self, source_invoice: Optional[Invoice], settled_invoice: Optional[Invoice], account: Optional[Account], **kw):
        """This needs to be called from a derived class clean().

        Args:
            source_invoice
            settled_invoice
            account

        Returns:
            None
        """
        for form in self.forms:
            obj = form.instance
            assert isinstance(obj, AccountEntry)
            if account is not None:
                obj.account = account
            obj.source_invoice = source_invoice
            obj.settled_invoice = settled_invoice
            if obj.parent is not None:
                if obj.amount is None:
                    obj.amount = obj.parent.amount
                if obj.type is None:
                    obj.type = obj.parent.type
                if obj.amount is not None and obj.parent.amount is not None:
                    if obj.amount > obj.parent.amount > Decimal(0) or obj.amount < obj.parent.amount < Decimal(0):
                        raise ValidationError(_("Derived account entry amount cannot be larger than original"))
            elif obj.type is not None:
                if obj.type.is_payment:
                    raise ValidationError(_("Payment settlements must have originating account entry which is also payment"))
            if obj.type is not None and obj.parent is not None and obj.parent.type is not None:
                if obj.type.is_payment != obj.parent.type.is_payment:
                    raise ValidationError(_("Payment settlements must have originating account entry which is also payment"))
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
    formset = SingleReceivablesAccountInvoiceItemInlineFormSet  # type: ignore  # TODO: override in app
    fk_name = "source_invoice"
    verbose_name = _("invoice items")
    verbose_name_plural = _("invoices items")
    extra = 0
    can_delete = True
    account_entry_change_view_name = "admin:jacc_accountentry_change"
    fields = [
        "id_link",
        "timestamp",
        "type",
        "description",
        "amount",
    ]
    raw_id_fields = [
        "account",
        "type",
        "source_invoice",
        "settled_invoice",
        "settled_item",
        "source_file",
        "parent",
    ]
    readonly_fields = [
        "id_link",
    ]

    def id_link(self, obj):
        if obj and obj.id:
            assert isinstance(obj, AccountEntry)
            admin_url = reverse(self.account_entry_change_view_name, args=(obj.id,))
            return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.id)
        return ""

    id_link.admin_order_field = "id"  # type: ignore
    id_link.short_description = _("id")  # type: ignore

    def get_queryset(self, request):
        queryset = self.model._default_manager.get_queryset().filter(type__is_settlement=False)
        if not self.has_change_permission(request):
            queryset = queryset.none()
        return queryset

    def get_field_queryset(self, db, db_field, request):
        related_admin = self.admin_site._registry.get(db_field.remote_field.model)
        if related_admin and db_field.name == "type":
            return related_admin.get_queryset(request).filter(is_settlement=False).order_by("name")
        return super().get_field_queryset(db, db_field, request)


class InvoiceSettlementInline(admin.TabularInline):  # TODO: override in app
    model = AccountEntry
    formset = SingleSettlementsAccountSettlementInlineFormSet  # type: ignore  # TODO: override in app
    fk_name = "settled_invoice"
    verbose_name = _("settlements")
    verbose_name_plural = _("settlements")
    show_non_settlements = False
    extra = 0
    can_delete = True
    account_entry_change_view_name = "admin:jacc_accountentry_change"  # TODO: override in app
    account_change_view_name = "admin:jacc_account_change"  # TODO: override in app
    fields = [
        "id_link",
        "account_link",
        "timestamp",
        "type",
        "description",
        "amount",
        "parent",
        "settled_item",
    ]
    raw_id_fields = [
        "account",
        "type",
        "source_invoice",
        "settled_invoice",
        "source_file",
        "parent",
        "settled_item",
    ]
    readonly_fields = [
        "id_link",
        "account_link",
        "settled_item",
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
        if related_admin and db_field.name == "type" and not self.show_non_settlements:
            return related_admin.get_queryset(request).filter(is_settlement=True).order_by("name")
        return super().get_field_queryset(db, db_field, request)

    def id_link(self, obj):
        if obj and obj.id:
            assert isinstance(obj, AccountEntry)
            admin_url = reverse(self.account_entry_change_view_name, args=(obj.id,))
            return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.id)
        return ""

    id_link.admin_order_field = "id"  # type: ignore
    id_link.short_description = _("id")  # type: ignore

    def account_link(self, obj):
        if obj and obj.id:
            assert isinstance(obj, AccountEntry)
            admin_url = reverse(self.account_change_view_name, args=(obj.account.id,))
            return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.account)
        return ""

    account_link.admin_order_field = "account"  # type: ignore
    account_link.short_description = _("account")  # type: ignore


def resend_invoices(modeladmin, request: HttpRequest, queryset: QuerySet):  # pylint: disable=unused-argument
    """Marks invoices with as un-sent.

    Args:
        modeladmin
        request
        queryset

    Returns:

    """
    user = request.user
    assert isinstance(user, User)
    for obj in queryset:
        assert isinstance(obj, Invoice)
        admin_log([obj, user], "Invoice id={invoice} marked for re-sending".format(invoice=obj.id), who=user)
    queryset.update(sent=None)


class InvoiceLateDaysFilter(SimpleListFilter):
    title = _("late days")
    parameter_name = "late_days_range"

    def lookups(self, request, model_admin):
        if hasattr(settings, "INVOICE_LATE_DAYS_LIST_FILTER"):
            return settings.INVOICE_LATE_DAYS_LIST_FILTER
        return [
            ("<0", _("late.days.filter.not.due")),
            ("0<7", format_lazy(_("late.days.filter.late.range"), 1, 7)),
            ("7<14", format_lazy(_("late.days.filter.late.range"), 7, 14)),
            ("14<21", format_lazy(_("late.days.filter.late.range"), 14, 21)),
            ("21<28", format_lazy(_("late.days.filter.late.range"), 21, 28)),
            ("28<", format_lazy(_("late.days.filter.late.over.days"), 28)),
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            begin, end = str(val).split("<")
            if begin:
                queryset = queryset.filter(late_days__gte=int(begin))
            if end:
                queryset = queryset.filter(late_days__lt=int(end))
        return queryset


def summarize_invoice_statistics(modeladmin, request: HttpRequest, qs: QuerySet):  # pylint: disable=unused-argument
    invoice_states = list(state for (state, name) in INVOICE_STATE)

    invoiced_total_amount = Decimal("0.00")
    invoiced_total_count = 0

    lines = [
        "<pre>",
        _("({total_count} invoices)").format(total_count=qs.count()),
    ]
    for state in invoice_states:
        state_name = choices_label(INVOICE_STATE, state)
        qs2 = qs.filter(state=state)

        invoiced = qs2.filter(state=state).aggregate(amount=Coalesce(Sum("amount"), Decimal("0.00")), count=Count("*"))
        invoiced_amount = Decimal(invoiced["amount"])
        invoiced_count = int(invoiced["count"])
        invoiced_total_amount += invoiced_amount
        invoiced_total_count += invoiced_count

        lines.append("{state_name} | x{count} | {amount:.2f}".format(state_name=state_name, amount=invoiced_amount, count=invoiced_count))

    lines.append(_("Total") + " {label} | x{count} | {amount:.2f}".format(label=_("amount"), amount=invoiced_total_amount, count=invoiced_total_count))
    lines.append("</pre>")

    lines = align_lines(lines, "|")
    messages.add_message(request, INFO, format_html("<br>".join(lines)), extra_tags="safe")


class InvoiceStateFilter(SimpleListFilter):
    title = _("state")
    parameter_name = "invoice-state"

    def lookups(self, request, model_admin):
        late_limit_days = settings.LATE_LIMIT_DAYS
        day_abbr = _("day.abbr")
        return [
            ("O", capfirst(_("outstanding.invoice"))),
            (INVOICE_NOT_DUE_YET, mark_safe("&nbsp;" * 4 + _("Not due yet"))),
            ("DL", mark_safe("&nbsp;" * 4 + _("Due") + "&nbsp;/&nbsp;" + _("late"))),
            (INVOICE_DUE, mark_safe("&nbsp;" * 8 + _("Due") + f"&nbsp;({late_limit_days}{day_abbr})")),
            (INVOICE_LATE, mark_safe("&nbsp;" * 8 + _("Late"))),
            ("C", capfirst(_("closed.invoice"))),
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            if val == "O":
                queryset = queryset.filter(close_date=None)
            elif val == "C":
                queryset = queryset.exclude(close_date=None)
            elif val == "DL":
                queryset = queryset.filter(state__in=[INVOICE_DUE, INVOICE_LATE])
            else:
                queryset = queryset.filter(state=val)
        return queryset


class InvoiceAdmin(ModelAdminBase):
    """Invoice admin. Override following in derived classes:
    - InvoiceSettlementInline with formset derived from AccountEntryInlineFormSet, override clean and call clean_entries()
    - InvoiceItemsInline with formset derived from AccountEntryInlineFormSet, override clean and call clean_entries()
    - inlines = [] set with above mentioned derived classes
    """

    date_hierarchy = "created"
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
    list_display = [
        "number",
        "created_brief",
        "sent_brief",
        "due_date_brief",
        "close_date_brief",
        "late_days",
        "amount",
        "paid_amount",
        "unpaid_amount",
    ]
    fields = [
        "type",
        "number",
        "due_date",
        "notes",
        "filename",
        "amount",
        "paid_amount",
        "unpaid_amount",
        "state",
        "overpaid_amount",
        "close_date",
        "late_days",
        "created",
        "last_modified",
        "sent",
    ]
    readonly_fields = [
        "created",
        "last_modified",
        "sent",
        "close_date",
        "created_brief",
        "sent_brief",
        "due_date_brief",
        "close_date_brief",
        "filename",
        "amount",
        "paid_amount",
        "unpaid_amount",
        "state",
        "overpaid_amount",
        "late_days",
    ]
    raw_id_fields = []
    search_fields = [
        "=amount",
        "=filename",
        "=number",
    ]
    list_filter = [
        InvoiceStateFilter,
        InvoiceLateDaysFilter,
    ]
    allow_add = True
    allow_delete = True
    ordering = ("-id",)

    def construct_change_message(self, request, form, formsets, add=False):
        instance = form.instance
        assert isinstance(instance, Invoice)
        instance.update_cached_fields()
        return super().construct_change_message(request, form, formsets, add)

    def _format_date(self, obj) -> str:
        """Short date format.

        Args:
            obj: date or datetime or None

        Returns:
            str
        """
        if obj is None:
            return ""
        if isinstance(obj, datetime):
            obj = obj.date()
        return date_format(obj, "SHORT_DATE_FORMAT")

    def created_brief(self, obj):
        assert isinstance(obj, Invoice)
        return self._format_date(obj.created)

    created_brief.admin_order_field = "created"  # type: ignore
    created_brief.short_description = _("created")  # type: ignore

    def sent_brief(self, obj):
        assert isinstance(obj, Invoice)
        return self._format_date(obj.sent)

    sent_brief.admin_order_field = "sent"  # type: ignore
    sent_brief.short_description = _("sent")  # type: ignore

    def due_date_brief(self, obj):
        assert isinstance(obj, Invoice)
        return self._format_date(obj.due_date)

    due_date_brief.admin_order_field = "due_date"  # type: ignore
    due_date_brief.short_description = _("due date")  # type: ignore

    def close_date_brief(self, obj):
        assert isinstance(obj, Invoice)
        return self._format_date(obj.close_date)

    close_date_brief.admin_order_field = "close_date"  # type: ignore
    close_date_brief.short_description = _("close date")  # type: ignore


def set_as_asset(modeladmin, request, qs):  # pylint: disable=unused-argument
    qs.update(is_asset=True)


def set_as_liability(modeladmin, request, qs):  # pylint: disable=unused-argument
    qs.update(is_asset=False)


class AccountTypeAdmin(ModelAdminBase):
    list_display = [
        "code",
        "name",
        "is_asset",
        "is_liability",
    ]
    actions = [
        set_as_asset,
        set_as_liability,
    ]
    ordering = ("name",)
    allow_add = True
    allow_delete = True

    def is_liability(self, obj):
        return obj.is_liability

    is_liability.short_description = _("is liability")  # type: ignore
    is_liability.boolean = True  # type: ignore


class ContractAdmin(ModelAdminBase):
    list_display = [
        "id",
        "name",
    ]
    ordering = [
        "-id",
    ]
    allow_add = True
    allow_delete = True


def toggle_settlement(modeladmin, request: HttpRequest, queryset: QuerySet):  # pylint: disable=unused-argument
    for e in queryset:
        assert isinstance(e, EntryType)
        e.is_settlement = not e.is_settlement
        e.save()
        admin_log([e], "Toggled settlement flag {}".format("on" if e.is_settlement else "off"), who=request.user)  # type: ignore


def toggle_payment(modeladmin, request: HttpRequest, queryset: QuerySet):  # pylint: disable=unused-argument
    for e in queryset:
        assert isinstance(e, EntryType)
        e.is_payment = not e.is_payment
        e.save()
        admin_log([e], "Toggled payment flag {}".format("on" if e.is_settlement else "off"), who=request.user)  # type: ignore


class EntryTypeAdmin(ModelAdminBase):
    list_display = [
        "id",
        "identifier",
        "name",
        "is_settlement",
        "is_payment",
        "payback_priority",
    ]
    list_filter = (
        "is_settlement",
        "is_payment",
    )
    search_fields = (
        "=code",
        "name",
    )
    actions = [
        toggle_settlement,
        toggle_payment,
    ]
    exclude = ()
    ordering = [
        "name",
    ]
    allow_add = True
    allow_delete = True


class AccountEntrySourceFileAdmin(ModelAdminBase):
    list_display = [
        "id",
        "created",
        "entries_link",
    ]
    date_hierarchy = "created"
    ordering = [
        "-id",
    ]
    fields = [
        "id",
        "name",
        "created",
        "last_modified",
    ]
    search_fields = [
        "=name",
    ]
    readonly_fields = [
        "id",
        "created",
        "name",
        "last_modified",
        "entries_link",
    ]
    allow_add = True
    allow_delete = True

    def entries_link(self, obj):
        if obj and obj.id:
            assert isinstance(obj, AccountEntrySourceFile)
            admin_url = reverse("admin:jacc_accountentry_sourcefile_changelist", args=(obj.id,))
            return format_html("<a href='{}'>{}</a>", mark_safe(admin_url), obj.name)
        return ""

    entries_link.admin_order_field = "name"  # type: ignore
    entries_link.short_description = _("account entry source file")  # type: ignore


class AccountEntryNoteAdmin(ModelAdminBase):
    date_hierarchy = "created"
    fields = [
        "id",
        "account_entry",
        "created",
        "created_by",
        "last_modified",
        "note",
    ]
    raw_id_fields = [
        "account_entry",
        "created_by",
    ]
    readonly_fields = [
        "id",
        "created",
        "created_by",
        "last_modified",
    ]
    write_once_fields = [
        "account_entry",
    ]
    search_fields = [
        "note",
    ]
    list_display = [
        "created",
        "account_entry",
        "note",
        "created_by",
    ]
    list_filter = [
        "created_by",
    ]

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and hasattr(obj, "id") and obj.id:
            return list(self.readonly_fields) + list(self.write_once_fields)
        return self.readonly_fields

    def save_form(self, request, form, change):
        obj = form.instance
        if not change:
            obj.created_by = request.user
        else:
            self.save_account_entry_note(request, obj)
        return form.save(commit=False)

    @staticmethod
    def save_account_entry_note(request, obj: AccountEntryNote):
        if not hasattr(obj, "created_by") or obj.created_by is None:
            obj.created_by = request.user
        else:
            old = AccountEntryNote.objects.all().filter(id=obj.id).first()
            if old is not None:
                assert isinstance(old, AccountEntryNote)
                if old.note != obj.note:
                    obj.created_by = request.user
                    admin_log(
                        [obj, obj.account_entry],
                        "Note id={} modified, previously: {}".format(old.id, old.note),
                        who=request.user,
                    )
        obj.save()

    @staticmethod
    def save_account_entry_note_formset(request, form, formset, change):  # noqa
        assert formset.model == AccountEntryNote
        if formset.model == AccountEntryNote:
            instances = formset.save(commit=False)
            for instance in instances:
                assert isinstance(instance, AccountEntryNote)
                AccountEntryNoteAdmin.save_account_entry_note(request, instance)


add_reverse_charge.short_description = _("Add reverse charge")  # type: ignore
resend_invoices.short_description = _("Re-send invoices")  # type: ignore
refresh_cached_fields.short_description = _("Refresh cached fields")  # type: ignore
summarize_account_entries.short_description = _("Summarize account entries")  # type: ignore
summarize_invoice_statistics.short_description = _("Summarize invoice statistics")  # type: ignore
set_as_asset.short_description = _("set_as_asset")  # type: ignore
set_as_liability.short_description = _("set_as_liability")  # type: ignore

admin.site.register(AccountEntryNote, AccountEntryNoteAdmin)
admin.site.register(Account, AccountAdmin)
admin.site.register(Invoice, InvoiceAdmin)  # TODO: override in app
admin.site.register(AccountEntry, AccountEntryAdmin)  # TODO: override in app
admin.site.register(AccountType, AccountTypeAdmin)
admin.site.register(EntryType, EntryTypeAdmin)
admin.site.register(AccountEntrySourceFile, AccountEntrySourceFileAdmin)
