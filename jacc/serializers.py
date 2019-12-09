from jacc.models import AccountEntry, Account, Invoice, EntryType
from django.utils.translation import gettext as _
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import ModelSerializer


class EntryTypeSerializer(ModelSerializer):
    class Meta:
        model = EntryType
        fields = [
            'id',
            'code',
            'identifier',
            'name',
            'created',
            'last_modified',
            'payback_priority',
            'is_settlement',
            'is_payment',
        ]
        read_only_fields = [
            'id',
            'created',
            'last_modified',
        ]


class AccountEntrySerializer(ModelSerializer):
    class Meta:
        model = AccountEntry
        fields = [
            'id',
            'account',
            'created',
            'last_modified',
            'timestamp',
            'type',
            'description',
            'amount',
            'source_file',
            'source_invoice',
            'settled_invoice',
            'settled_item',
            'parent',
        ]
        read_only_fields = [
            'id',
            'created',
            'last_modified',
        ]

    def to_internal_value(self, data: dict):
        # convert type.code -> type.id
        if 'type' in data and data['type']:
            types = list(EntryType.objects.filter(code=data['type']))
            if len(types) == 1:
                data['type'] = types[0].id
        return super().to_internal_value(data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.type:
            data['type'] = instance.type.code
        return data

    def validate(self, attrs):
        if 'type' not in attrs or not attrs['type']:
            raise ValidationError({'type': _('entry.type.missing')})
        return attrs


class AccountSerializer(ModelSerializer):
    class Meta:
        model = Account
        fields = [
            'id',
            'type',
            'name',
            'currency',
            'created',
            'last_modified',
        ]
        read_only_fields = [
            'id',
            'created',
            'last_modified',
        ]


class InvoiceSerializer(ModelSerializer):
    receivables = AccountEntrySerializer(many=True, read_only=True)

    class Meta:
        model = Invoice
        fields = [
            'id',
            'type',
            'created',
            'last_modified',
            'sent',
            'due_date',
            'notes',
            'filename',
            'amount',
            'paid_amount',
            'unpaid_amount',
            'overpaid_amount',
            'close_date',
            'late_days',
            'state',
            'receivables',
        ]
        read_only_fields = [
            'id',
            'created',
            'last_modified',
            'sent',
            'filename',
            'amount',
            'paid_amount',
            'unpaid_amount',
            'overpaid_amount',
            'close_date',
            'late_days',
            'state',
            'receivables',
        ]
