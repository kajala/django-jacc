from decimal import Decimal
from django.db.models import QuerySet, Sum


def sum_queryset(qs: QuerySet, key: str = 'amount', default: Decimal = Decimal(0)) -> Decimal:
    """
    Returns aggregate sum of queryset 'amount' field.
    :param qs: QuerySet
    :param key: Field to sum (default: 'amount')
    :param default: Default value if no results
    :return: Sum of 'amount' field values (coalesced 0 if None)
    """
    res = qs.aggregate(b=Sum(key))['b']
    return default if res is None else res
