from datetime import timedelta

from jacc.models import AccountEntry, Invoice
from django.core.management.base import CommandParser
from django.utils.timezone import now
from jutil.command import SafeCommand


class Command(SafeCommand):
    help = 'Updates cached values of invoices with due dates +- 60d of current date'

    def add_arguments(self, parser: CommandParser):
        parser.add_argument('--invoice', type=int)
        parser.add_argument('--force', action='store_true')

    def do(self, *args, **options):
        invoices = Invoice.objects.all()
        if options['invoice']:
            invoices = invoices.filter(id=options['invoice'])
        if not options['force']:
            invoices = invoices.filter(close_date=None)

        for invoice in invoices.order_by('id'):
            assert isinstance(invoice, Invoice)
            print('updating', invoice)
            invoice.update_cached_fields()
