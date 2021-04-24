from decimal import Decimal
from django.core.management.base import CommandParser
from jacc.models import AccountEntry, Invoice
from jutil.command import SafeCommand


class Command(SafeCommand):
    help = "Invoice balance"

    def add_arguments(self, parser: CommandParser):
        parser.add_argument("invoice", type=int)
        parser.add_argument("--tx", action="store_true")

    def do(self, *args, **options):
        inv = Invoice.objects.get(id=options["invoice"])
        assert isinstance(inv, Invoice)
        inv.update_cached_fields()

        print("Invoice id={} balances:".format(inv.id))
        for item, bal in inv.get_item_balances(inv.receivables_account):
            assert isinstance(item, AccountEntry)
            assert isinstance(bal, Decimal)
            print("  {} balance {}".format(item, bal))

        if options["tx"]:
            bal = Decimal("0.00")
            for tx in inv.receivables.order_by("timestamp", "id"):
                assert isinstance(tx, AccountEntry)
                bal += tx.amount
                print(
                    "  [{}] {} {} {}{} {}".format(
                        tx.id,
                        tx.timestamp.date().isoformat(),
                        tx.type,
                        "+" if tx.amount >= Decimal("0.00") else "",
                        tx.amount,
                        bal,
                    )
                )
