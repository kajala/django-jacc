from django.core.management.base import CommandParser
from jutil.command import SafeCommand
from jacc.models import AccountEntry, Account


class Command(SafeCommand):
    help = "Force refresh cached balances of accounts"

    def add_arguments(self, parser: CommandParser):
        parser.add_argument("--account-id", type=str)
        parser.add_argument("--account-type-code", type=str)

    def do(self, *args, **options):
        acc_qs = Account.objects.all()
        if options["account_type_code"]:
            acc_qs = acc_qs.filter(type__code=options["account_type_code"])
        if options["account_id"]:
            acc_qs = acc_qs.filter(id=options["account_id"])

        for acc in acc_qs:
            assert isinstance(acc, Account)
            acc.calculate_balances()
