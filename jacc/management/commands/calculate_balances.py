import logging

from django.core.management.base import CommandParser
from django.utils.timezone import now
from jutil.command import SafeCommand
from jacc.models import Account

logger = logging.getLogger(__name__)


class Command(SafeCommand):
    help = "Force refresh cached balances of accounts"

    def add_arguments(self, parser: CommandParser):
        parser.add_argument("--account-id", type=str)
        parser.add_argument("--account-type-code", type=str)
        parser.add_argument("--verbose", action="store_true")

    def do(self, *args, **options):
        verbose = options["verbose"]
        time_begin = now()
        acc_qs = Account.objects.all()
        if options["account_type_code"]:
            acc_qs = acc_qs.filter(type__code=options["account_type_code"])
        if options["account_id"]:
            acc_qs = acc_qs.filter(id=options["account_id"])

        if verbose:
            logger.debug("Calculating balances of %s accounts", acc_qs.count())
        t1 = time_begin
        for acc in acc_qs.order_by("id"):
            assert isinstance(acc, Account)
            if verbose:
                logger.debug("Account %s calculate_balances() BEGIN", acc)
                t1 = now()
            acc.calculate_balances()
            if verbose:
                logger.debug("Account %s calculate_balances() END %s", acc, now() - t1)
        logger.info("update_balances DONE %s", now() - time_begin)
