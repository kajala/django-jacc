from collections import OrderedDict
import django_filters
from django.db import transaction
from jacc.models import AccountEntry, Account, Invoice, INVOICE_STATE
from jacc.serializers import AccountEntrySerializer, AccountSerializer, InvoiceSerializer
from django_filters.rest_framework import FilterSet
from rest_framework import mixins
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK
from rest_framework.viewsets import GenericViewSet, ViewSet
from jutil.auth import AuthUserMixin


class AccountEntryFilter(FilterSet):
    timestamp_gte = django_filters.DateTimeFilter(name='timestamp', lookup_expr='gte')
    timestamp_lt = django_filters.DateTimeFilter(name='timestamp', lookup_expr='lt')
    amount_gte = django_filters.NumberFilter(name='amount', lookup_expr='gte')
    amount_lte = django_filters.NumberFilter(name='amount', lookup_expr='lte')
    settled_invoice_isnull = django_filters.BooleanFilter(name='settled_invoice', lookup_expr='isnull')
    source_invoice_isnull = django_filters.BooleanFilter(name='source_invoice', lookup_expr='isnull')
    is_settlement = django_filters.BooleanFilter(name='type', lookup_expr='is_settlement')

    class Meta:
        model = AccountEntry
        fields = [
            'amount',
            'account',
            'source_file',
            'source_invoice',
            'settled_invoice',
            'parent',
            'type',
            'timestamp',
            'amount_gte',
            'amount_lte',
            'timestamp_gte',
            'timestamp_lt',
            'settled_invoice_isnull',
            'source_invoice_isnull',
            'is_settlement',
        ]


class AccountEntryViewSet(mixins.RetrieveModelMixin,
                          mixins.ListModelMixin,
                          mixins.CreateModelMixin,
                          AuthUserMixin,
                          GenericViewSet):
    """
    Account entry view set. Mutation to account state, allocation of sum of money.
    """
    queryset = AccountEntry.objects.all()
    serializer_class = AccountEntrySerializer
    filter_class = AccountEntryFilter
    permission_classes = []
    ordering_fields = '__all__'
    ordering = ('-id', )

    def get_queryset(self):
        return AccountEntry.objects.none()

    def options(self, request, *args, **kwargs):
        data = self.metadata_class().determine_metadata(request, self)
        return Response(data, status=HTTP_200_OK)


class AccountViewSet(mixins.RetrieveModelMixin,
                     mixins.ListModelMixin,
                     AuthUserMixin,
                     GenericViewSet):
    """
    Account view set.
    """

    queryset = Account.objects.all()
    serializer_class = AccountSerializer
    permission_classes = []

    def get_queryset(self):
        return Account.objects.none()

    def options(self, request, *args, **kwargs):
        data = self.metadata_class().determine_metadata(request, self)
        return Response(data, status=HTTP_200_OK)


class InvoiceFilter(FilterSet):
    due_date_gte = django_filters.IsoDateTimeFilter(name="due_date", lookup_expr='gte')
    due_date_lt = django_filters.IsoDateTimeFilter(name="due_date", lookup_expr='lt')
    close_date_gte = django_filters.IsoDateTimeFilter(name="close_date", lookup_expr='gte')
    close_date_lt = django_filters.IsoDateTimeFilter(name="close_date", lookup_expr='lt')
    due_amount_gt = django_filters.NumberFilter(name='amount', lookup_expr='gt')
    due_amount_gte = django_filters.NumberFilter(name='amount', lookup_expr='gte')
    due_amount_lt = django_filters.NumberFilter(name='amount', lookup_expr='lt')
    due_amount_lte = django_filters.NumberFilter(name='amount', lookup_expr='lte')
    late_days_gt = django_filters.NumberFilter(name='late_days', lookup_expr='gt')
    late_days_gte = django_filters.NumberFilter(name='late_days', lookup_expr='gte')
    late_days_lt = django_filters.NumberFilter(name='late_days', lookup_expr='lt')
    late_days_lte = django_filters.NumberFilter(name='late_days', lookup_expr='lte')
    overpaid_amount_gt = django_filters.NumberFilter(name='overpaid_amount', lookup_expr='gt')
    overpaid_amount_gte = django_filters.NumberFilter(name='overpaid_amount', lookup_expr='gte')
    overpaid_amount_lt = django_filters.NumberFilter(name='overpaid_amount', lookup_expr='lt')
    overpaid_amount_lte = django_filters.NumberFilter(name='overpaid_amount', lookup_expr='lte')
    paid_amount_gt = django_filters.NumberFilter(name='paid_amount', lookup_expr='gt')
    paid_amount_gte = django_filters.NumberFilter(name='paid_amount', lookup_expr='gte')
    paid_amount_lt = django_filters.NumberFilter(name='paid_amount', lookup_expr='lt')
    paid_amount_lte = django_filters.NumberFilter(name='paid_amount', lookup_expr='lte')
    unpaid_amount_gt = django_filters.NumberFilter(name='unpaid_amount', lookup_expr='gt')
    unpaid_amount_gte = django_filters.NumberFilter(name='unpaid_amount', lookup_expr='gte')
    unpaid_amount_lt = django_filters.NumberFilter(name='unpaid_amount', lookup_expr='lt')
    unpaid_amount_lte = django_filters.NumberFilter(name='unpaid_amount', lookup_expr='lte')

    class Meta:
        model = Invoice
        fields = [
            'late_days',
            'amount',
            'due_date',
            'close_date',
            'paid_amount',
            'unpaid_amount',
            'state',
            'due_date_gte',
            'due_date_lt',
            'close_date_gte',
            'close_date_lt',
            'due_amount_gt',
            'due_amount_gte',
            'due_amount_lt',
            'due_amount_lte',
            'late_days_gt',
            'late_days_gte',
            'late_days_lt',
            'late_days_lte',
            'overpaid_amount_gt',
            'overpaid_amount_gte',
            'overpaid_amount_lt',
            'overpaid_amount_lte',
            'paid_amount_gt',
            'paid_amount_gte',
            'paid_amount_lt',
            'paid_amount_lte',
            'unpaid_amount_gt',
            'unpaid_amount_gte',
            'unpaid_amount_lt',
            'unpaid_amount_lte',
        ]


class InvoiceViewSet(mixins.RetrieveModelMixin,
                     mixins.CreateModelMixin,
                     mixins.UpdateModelMixin,
                     mixins.ListModelMixin,
                     mixins.DestroyModelMixin,
                     AuthUserMixin,
                     GenericViewSet):
    """
    Invoice view set.
    """
    queryset = Invoice.objects.all()
    serializer_class = InvoiceSerializer
    filter_class = InvoiceFilter
    ordering_fields = '__all__'
    ordering = ('-id', )
    permission_classes = []

    def get_queryset(self):
        return Invoice.objects.none()

    def options(self, request, *args, **kwargs):
        data = self.metadata_class().determine_metadata(request, self)
        data['filters'] = InvoiceFilter.Meta.fields
        return Response(data, status=HTTP_200_OK)
