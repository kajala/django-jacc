from decimal import Decimal
from datetime import timedelta, datetime, date
import pytz
from jacc.interests import calculate_simple_interest
from jacc.models import AccountEntry, Account, Invoice, EntryType, AccountType, INVOICE_CREDIT_NOTE
from django.test import TestCase
from django.utils.timezone import now
from jacc.settle import settle_assigned_invoice, settle_credit_note
from jutil.dates import add_month
from jutil.format import dec2
from jutil.parse import parse_datetime
from jutil.testing import DefaultTestSetupMixin


ACCOUNT_RECEIVABLES = 'RE'
ACCOUNT_SETTLEMENTS = 'SE'
E_SETTLEMENT = 'SE'
E_MANUAL_SETTLEMENT = 'MS'
E_RENT = 'IR'
E_FEE = 'FE'
E_CAPITAL = 'CA'
E_INTEREST = 'IN'
E_OVERPAYMENT = 'OP'
E_CREDIT_NOTE_RECONCILIATION = '33'

INTEREST_ACCUMULATING_TYPE_CODES = [E_CAPITAL]
INTEREST_TYPE_CODES = [E_INTEREST]


def create_account_by_type(type_id: str):
    """
    Create account by AccountType id.
    :param type_id:
    :return: Account
    """
    return Account.objects.create(type=AccountType.objects.get(code=type_id))


def make_datetime(year, month, day) -> datetime:
    return pytz.utc.localize(datetime(year=year, month=month, day=day))


class Tests(TestCase, DefaultTestSetupMixin):
    def setUp(self):
        self.add_test_user()
        AccountType.objects.create(code=ACCOUNT_RECEIVABLES, name='Receivables', is_asset=True)
        AccountType.objects.create(code=ACCOUNT_SETTLEMENTS, name='Settlements', is_asset=True)
        ae_types = [
            {
                "code": "CA",
                "name": "pääoma",
                "payback_priority": 3,
            },
            {
                "code": "OP",
                "name": "liikasuoritus",
                "payback_priority": 3,
            },
            {
                "code": "CN",
                "name": "peruutus"
            },
            {
                "code": "CO",
                "name": "korjaus"
            },
            {
                "code": "FE",
                "name": "nostopalkkio",
                "payback_priority": 2,
            },
            {
                "code": "FP",
                "name": "loppusuoritus"
            },
            {
                "code": "IN",
                "name": "korko",
                "payback_priority": 1,
            },
            {
                "code": "MS",
                "name": "ohisuoritus",
                "is_settlement": True,
            },
            {
                "code": "SE",
                "name": "suoritus",
                "is_settlement": True,
            },
            {
                "code": "IR",
                "name": "vuokra"
            },
            {
                "code": E_CREDIT_NOTE_RECONCILIATION,
                "name": 'hyvityslaskun kohdistus',
                "is_settlement": True,
            }
        ]
        for ae_type in ae_types:
            EntryType.objects.create(**ae_type)

    def tearDown(self):
        pass

    def test_account(self):
        print('test_account')
        settlements = create_account_by_type(ACCOUNT_SETTLEMENTS)
        assert isinstance(settlements, Account)
        amounts = [12, '13.12', '-1.23', '20.00']
        balances = [Decimal('12.00'), Decimal('25.12'), Decimal('23.89'), Decimal('43.89')]
        t = parse_datetime('2016-06-13T01:00:00')
        dt = timedelta(minutes=5)
        times = [t+dt*i for i in range(len(amounts))]
        for i in range(len(times)):
            amount = amounts[i]
            t = times[i]
            e = AccountEntry(account=settlements, amount=Decimal(amount), type=EntryType.objects.get(code=E_SETTLEMENT), timestamp=t)
            e.full_clean()
            e.save()
            self.assertEqual(settlements.balance, balances[i])
            self.assertEqual(settlements.balance, e.balance)
        for i in range(len(times)):
            t = times[i]
            self.assertEqual(settlements.get_balance(t+timedelta(seconds=1)), balances[i])

    def test_invoice(self):
        print('test_invoice')
        settlements = create_account_by_type(ACCOUNT_SETTLEMENTS)
        receivables_acc = create_account_by_type(ACCOUNT_RECEIVABLES)
        assert isinstance(settlements, Account)

        # create invoices
        t = parse_datetime('2016-05-05')
        amounts = [
            Decimal('120.00'),
            Decimal('100.00'),
            Decimal('50.00'),
            Decimal('40.00'),
        ]
        n = len(amounts)
        times = [add_month(t, i) for i in range(n)]
        invoices = []
        for t, amount in zip(times, amounts):
            invoice = Invoice(due_date=t)
            invoice.full_clean()
            invoice.save()
            AccountEntry.objects.create(account=receivables_acc, source_invoice=invoice, type=EntryType.objects.get(code=E_RENT), amount=amount)
            invoice.update_cached_fields()
            self.assertEqual(invoice.unpaid_amount, amount)
            invoices.append(invoice)
            # print(invoice)
        unpaid_invoices = [i for i in invoices]

        # create payments
        payment_ops = [
            (None,              [Decimal('120.00'), Decimal('100.00'), Decimal('50.00'), Decimal('40.00')]),
            (Decimal('50.00'),  [Decimal('70.00'), Decimal('100.00'), Decimal('50.00'), Decimal('40.00')]),
            (Decimal('70.50'),  [Decimal('00.00'), Decimal('100.00'), Decimal('50.00'), Decimal('40.00')]),
            (Decimal('100.00'), [Decimal('00.00'), Decimal('00.00'), Decimal('50.00'), Decimal('40.00')]),
            (Decimal('100.00'), [Decimal('00.00'), Decimal('00.00'), Decimal('00.00'), Decimal('40.00')]),
        ]
        for j in range(len(payment_ops)):
            print('test_invoice: Payment op test', j)
            for i in range(n):
                inv = invoices[i]
                assert isinstance(inv, Invoice)
            paid_amount, unpaid_amounts = payment_ops[j]
            if paid_amount is not None:
                p = AccountEntry.objects.create(account=settlements, settled_invoice=unpaid_invoices[0], amount=paid_amount, type=EntryType.objects.get(code=E_MANUAL_SETTLEMENT))
                settle_assigned_invoice(receivables_acc, p, AccountEntry)
                if unpaid_invoices[0].is_paid:
                    unpaid_invoices = unpaid_invoices[1:]
            for i in range(n):
                inv = invoices[i]
                assert isinstance(inv, Invoice)
            for i in range(n):
                paid_amount_real = invoices[i]
                unpaid_amount_real = invoices[i].get_unpaid_amount()
                unpaid_amount_ref = unpaid_amounts[i]
                print('checking invoice {} payment status after payment op {} (real {}, expected {})'.format(i, j, unpaid_amount_real, unpaid_amount_ref))
                self.assertEqual(unpaid_amount_real, unpaid_amount_ref, '[{}][{}]'.format(j, i))

        # create another acc set
        settlements = create_account_by_type(ACCOUNT_SETTLEMENTS)
        assert isinstance(settlements, Account)
        receivables_acc = create_account_by_type(ACCOUNT_RECEIVABLES)
        assert isinstance(receivables_acc, Account)

        # create invoices
        t = parse_datetime('2016-05-05')
        amounts = [Decimal('120.00'), Decimal('100.00'), Decimal('50.00'), Decimal('40.00')]
        n = len(amounts)
        times = [add_month(t, i) for i in range(n)]
        invoices = []
        for t, amount in zip(times, amounts):
            invoice = Invoice(due_date=t)
            invoice.full_clean()
            invoice.save()
            AccountEntry.objects.create(account=receivables_acc, source_invoice=invoice, type=EntryType.objects.get(code=E_RENT), amount=amount)
            invoice.update_cached_fields()
            self.assertEqual(invoice.unpaid_amount, amount)
            invoices.append(invoice)
            print('invoice created', invoice)
        unpaid_invoices = [i for i in invoices]

        # create payments:
        # paid_amount, unpaid_amounts (after payment)
        payment_ops = [
            (None,              [Decimal('120.00'), Decimal('100.00'), Decimal('50.00'), Decimal('40.00')]),
            (Decimal('250.00'), [Decimal('0.00'), Decimal('100.00'), Decimal('50.00'), Decimal('40.00')]),
        ]
        for j in range(len(payment_ops)):
            paid_amount, unpaid_amounts = payment_ops[j]
            if paid_amount is not None and paid_amount > Decimal('0.00'):
                invoice = unpaid_invoices[0]
                print('Targeting settlement amount', paid_amount, 'to invoice', invoice, 'invoice.amount', invoice.amount)
                p = AccountEntry.objects.create(account=settlements, amount=paid_amount, settled_invoice=invoice, type=EntryType.objects.get(code=E_MANUAL_SETTLEMENT))
                settle_assigned_invoice(receivables_acc, p, AccountEntry)
                if invoice.is_paid:
                    unpaid_invoices = unpaid_invoices[1:]
                    print('invoice paid, now left', unpaid_invoices)
            for i in range(n):
                unpaid_amount_real = invoices[i].get_unpaid_amount()
                unpaid_amount_ref = unpaid_amounts[i]
                self.assertEqual(unpaid_amount_real, unpaid_amount_ref, '[{}][{}]'.format(j, i))

        # check that the first payment has E_RENT 120
        inv = invoices[0]
        assert isinstance(inv, Invoice)
        es = inv.receivables.order_by('id')
        self.assertEqual(es[0].amount, Decimal('120.00'))
        self.assertEqual(es[1].amount, Decimal('-120.00'))
        self.assertIsNotNone(es[1].parent)
        self.assertTrue(es[1].parent.type.is_settlement)
        self.assertEqual(es[1].parent.amount, Decimal('250.00'))

    def test_settlements_with_assigned_invoices(self):
        print('test_settlements_with_assigned_invoices')

        e_capital = EntryType.objects.get(code=E_CAPITAL)
        e_fee = EntryType.objects.get(code=E_FEE)
        e_interest = EntryType.objects.get(code=E_INTEREST)
        e_settlement = EntryType.objects.get(code=E_SETTLEMENT)
        e_overpayment = EntryType.objects.get(code=E_OVERPAYMENT)

        # invoice: cap 100, fee 10, interest 5
        invoice_components = [
            (e_capital, 100),
            (e_fee, 10),
            (e_interest, 5),
        ]
        settlement_acc = Account.objects.create(type=AccountType.objects.get(code=ACCOUNT_SETTLEMENTS))
        receivables_acc = Account.objects.create(type=AccountType.objects.get(code=ACCOUNT_RECEIVABLES))
        invoice = Invoice.objects.create(due_date=now())
        assert isinstance(receivables_acc, Account)
        assert isinstance(settlement_acc, Account)
        assert isinstance(invoice, Invoice)
        for ae_type, amt in invoice_components:
            AccountEntry.objects.create(account=receivables_acc, source_invoice=invoice, type=ae_type, amount=Decimal(amt))

        # paybacks
        # order (see setUp): cap, fee, interest
        paybacks_and_unpaid_components = [
            (None, 115),
            (20, 95),
            (80, 15),
            (10, 5),
            (5, 0),
        ]
        AccountEntry.objects.distinct('type').order_by('type__payback_order')
        for payback, unpaid in paybacks_and_unpaid_components:
            if payback:
                payback = AccountEntry.objects.create(account=settlement_acc, settled_invoice=invoice, type=e_settlement, amount=Decimal(payback))
                settle_assigned_invoice(receivables_acc, payback, AccountEntry)
            bal = invoice.get_balance(invoice.receivables_account)
            self.assertEqual(bal, unpaid)

    def test_calculate_simple_interest(self):
        print('test_calculate_simple_interest')
        apr = Decimal('48.74')
        capital = Decimal('500.00')
        et_capital = EntryType.objects.get(code=E_CAPITAL)
        entries = [
            AccountEntry(type=et_capital, amount=capital, timestamp=make_datetime(2017, 1, 1)),
            AccountEntry(type=et_capital, amount=Decimal(-50), timestamp=make_datetime(2017, 3, 1)),
            AccountEntry(type=et_capital, amount=Decimal(-50), timestamp=make_datetime(2017, 5, 1)),
            AccountEntry(type=et_capital, amount=Decimal(-50), timestamp=make_datetime(2017, 7, 1)),
            AccountEntry(type=et_capital, amount=Decimal(-50), timestamp=make_datetime(2017, 9, 1)),
            AccountEntry(type=et_capital, amount=Decimal(-50), timestamp=make_datetime(2017, 11, 1)),
            AccountEntry(type=et_capital, amount=Decimal('-437.50'), timestamp=make_datetime(2018, 1, 1)),
        ]
        timestamp = make_datetime(2018, 1, 1)
        interest = calculate_simple_interest(entries, apr, timestamp.date())
        print('interest =', dec2(interest))
        self.assertEqual(interest.quantize(Decimal('1.00')), Decimal('182.41'))

    def test_calculate_simple_interest2(self):
        print('test_calculate_simple_interest2')
        apr = Decimal('48.74')
        capital = Decimal('500.00')
        et_capital = EntryType.objects.get(code=E_CAPITAL)
        entries = [
            AccountEntry(type=et_capital, amount=capital, timestamp=make_datetime(2017, 1, 1)),
            AccountEntry(type=et_capital, amount=Decimal(-50), timestamp=make_datetime(2017, 3, 1)),
            AccountEntry(type=et_capital, amount=Decimal(-50), timestamp=make_datetime(2017, 5, 1)),
            AccountEntry(type=et_capital, amount=Decimal(-50), timestamp=make_datetime(2017, 7, 1)),
            AccountEntry(type=et_capital, amount=Decimal(-50), timestamp=make_datetime(2017, 9, 1)),
            AccountEntry(type=et_capital, amount=Decimal(-50), timestamp=make_datetime(2017, 11, 1)),
        ]
        timestamp = make_datetime(2020, 1, 1)
        interest = calculate_simple_interest(entries, apr, timestamp.date())
        print('interest =', dec2(interest))
        self.assertEqual(interest.quantize(Decimal('1.00')), Decimal('426.11'))

    def test_calculate_simple_interest3(self):
        print('test_calculate_simple_interest3')
        apr = Decimal('3.00')
        capital = Decimal('500.00')
        et_capital = EntryType.objects.get(code=E_CAPITAL)
        entries = [
            AccountEntry(type=et_capital, amount=capital, timestamp=make_datetime(2018, 1, 10)),
        ]
        interest = calculate_simple_interest(entries, apr, date(2018, 3, 1), begin=date(2018, 2, 10))
        print('interest =', dec2(interest))
        self.assertEqual(interest.quantize(Decimal('1.00')), Decimal('0.78'))

    def test_credit_note(self):
        print('test_credit_note')

        # create invoice
        e_capital = EntryType.objects.get(code=E_CAPITAL)
        e_fee = EntryType.objects.get(code=E_FEE)
        invoice_components = [
            (e_capital, Decimal(100)),
            (e_fee, Decimal(10)),
        ]
        settlement_acc = Account.objects.create(type=AccountType.objects.get(code=ACCOUNT_SETTLEMENTS))
        receivables_acc = Account.objects.create(type=AccountType.objects.get(code=ACCOUNT_RECEIVABLES))
        invoice = Invoice.objects.create(due_date=now())
        assert isinstance(receivables_acc, Account)
        assert isinstance(settlement_acc, Account)
        assert isinstance(invoice, Invoice)
        for ae_type, amt in invoice_components:
            AccountEntry.objects.create(account=receivables_acc, source_invoice=invoice, type=ae_type, amount=amt)

        invoice.update_cached_fields()

        # ensure balances
        self.assertEqual(invoice.get_unpaid_amount(), Decimal('110.00'))
        self.assertEqual(invoice.get_paid_amount(), Decimal('0.00'))
        self.assertEqual(invoice.get_amount(), Decimal('110.00'))
        self.assertEqual(invoice.get_overpaid_amount(), Decimal('0.00'))

        # create credit note
        e_capital = EntryType.objects.get(code=E_CAPITAL)
        invoice_components = [
            (e_capital, Decimal(-110)),
        ]
        credit_note = Invoice.objects.create(due_date=now(), type=INVOICE_CREDIT_NOTE)
        assert isinstance(credit_note, Invoice)
        for ae_type, amt in invoice_components:
            AccountEntry.objects.create(account=receivables_acc, source_invoice=credit_note, type=ae_type, amount=amt)

        credit_note.update_cached_fields()

        # ensure balances
        self.assertEqual(credit_note.get_unpaid_amount(), Decimal('-110.00'))
        self.assertEqual(credit_note.get_paid_amount(), Decimal('0.00'))
        self.assertEqual(credit_note.get_amount(), Decimal('-110.00'))
        self.assertEqual(credit_note.get_overpaid_amount(), Decimal('0.00'))

        # settle credit note
        e_credit_note = EntryType.objects.get(code=E_CREDIT_NOTE_RECONCILIATION)
        pmts = settle_credit_note(credit_note, invoice, AccountEntry, settlement_acc, entry_type=e_credit_note)
        for pmt in pmts:
            settle_assigned_invoice(receivables_acc, pmt, AccountEntry)

        # ensure balances
        self.assertEqual(credit_note.get_unpaid_amount(), Decimal('0.00'))
        self.assertEqual(credit_note.get_paid_amount(), Decimal('-110.00'))
        self.assertEqual(credit_note.get_amount(), Decimal('-110.00'))
        self.assertEqual(credit_note.get_overpaid_amount(), Decimal('0.00'))
        self.assertEqual(invoice.get_unpaid_amount(), Decimal('0.00'))
        self.assertEqual(invoice.get_paid_amount(), Decimal('110.00'))
        self.assertEqual(invoice.get_amount(), Decimal('110.00'))
        self.assertEqual(invoice.get_overpaid_amount(), Decimal('0.00'))
