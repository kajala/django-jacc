import logging
from datetime import date, timedelta
from decimal import Decimal
from django.utils.timezone import now
from jacc.models import AccountEntry


logger = logging.getLogger(__name__)


def calculate_simple_interest(entries, rate_pct: Decimal, interest_date: date or None=None) -> Decimal:
    """
    Calculates simple interest of specified entries over time.
    Does not accumulate interest to interest.
    :param entries: AccountEntry iterable (e.g. list/QuerySet)
    :param rate_pct: Interest rate %, e.g. 8.00 for 8%
    :param interest_date: Interest end date. Default is current date.
    :return: Decimal accumulated interest
    """
    if interest_date is None:
        interest_date = now().date()

    bal = None
    cur_date = None
    daily_rate = rate_pct / Decimal(36500)
    accum_interest = Decimal('0.00')
    done = False
    logger.info('calculate_simple_interest: {} entries'.format(len(entries)))

    for e in entries:
        assert isinstance(e, AccountEntry)
        if bal is None:
            bal = e.amount
            cur_date = e.timestamp.date()
            logger.info('calculate_simple_interest: begin {} end {} bal={}'.format(cur_date, interest_date, bal))
        else:
            next_date = e.timestamp.date()
            if next_date > interest_date:
                next_date = interest_date
                done = True
            time_days = (next_date - cur_date).days
            if time_days > 0:
                day_interest = bal * daily_rate
                interval_interest = day_interest * Decimal(time_days)
                logger.info('calculate_simple_interest: days {} interest {}'.format(time_days, interval_interest))
                accum_interest += interval_interest
                cur_date = next_date
            bal += e.amount
            if done:
                break

    logger.info('calculate_simple_interest: accumulated interest {}'.format(accum_interest))
    return accum_interest
