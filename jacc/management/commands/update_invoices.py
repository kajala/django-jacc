from jacc.models import Invoice
from django.core.management.base import CommandParser
from jutil.command import SafeCommand


class Command(SafeCommand):
    help = "Updates cached values of invoices"

    def add_arguments(self, parser: CommandParser):
        parser.add_argument("--invoice", type=int)
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--verbose", action="store_true")

    def do(self, *args, **options):
        invoices = Invoice.objects.all()
        if options["invoice"]:
            invoices = invoices.filter(id=options["invoice"])
        if not options["force"]:
            invoices = invoices.filter(close_date=None)

        count = 0
        for invoice in invoices.order_by("id"):
            assert isinstance(invoice, Invoice)
            if options["verbose"]:
                print("Updating", invoice)
            invoice.update_cached_fields()
            count += 1

        print("Updated", count, "invoices")
