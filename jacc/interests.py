from datetime import date, timedelta, time, datetime
from decimal import Decimal
import pytz
from django.utils.timezone import now
from jacc.models import AccountEntry


def calculate_simple_interest(entries, rate_pct: Decimal, interest_date: date or None=None, begin: date or None=None) -> Decimal:
    """
    Calculates simple interest of specified entries over time.
    Does not accumulate interest to interest.
    :param entries: AccountEntry iterable (e.g. list/QuerySet) ordered by timestamp (ascending)
    :param rate_pct: Interest rate %, e.g. 8.00 for 8%
    :param interest_date: Interest end date. Default is current date.
    :param begin: Optional begin date for the interest. Default is whole range from the timestamp of account entries.
    :return: Decimal accumulated interest
    """
    if interest_date is None:
        interest_date = now().date()

    bal = None
    cur_date = None
    daily_rate = rate_pct / Decimal(36500)
    accum_interest = Decimal('0.00')
    done = False

    entries_list = list(entries)
    nentries = len(entries_list)
    if nentries > 0:
        # make sure we calculate interest over whole range until interest_date
        last = entries_list[nentries-1]
        assert isinstance(last, AccountEntry)
        if last.timestamp.date() < interest_date:
            timestamp = pytz.utc.localize(datetime.combine(interest_date, time(0, 0)))
            e = AccountEntry(timestamp=timestamp, amount=Decimal('0.00'), type=last.type)
            entries_list.append(e)

        # initial values from the first account entry
        e = entries_list[0]
        bal = e.amount
        cur_date = e.timestamp.date()
        if begin and begin > cur_date:
            cur_date = begin

    for e in entries_list[1:]:
        assert isinstance(e, AccountEntry)
        next_date = e.timestamp.date()
        if begin and begin > next_date:
            next_date = begin
        if next_date > interest_date:
            next_date = interest_date
            done = True
        time_days = (next_date - cur_date).days
        if time_days > 0:
            day_interest = bal * daily_rate
            interval_interest = day_interest * Decimal(time_days)
            accum_interest += interval_interest
            cur_date = next_date
        bal += e.amount
        if done:
            break

    return accum_interest
