django-jacc
===========

Simple double entry accounting system (debits/credits) for Django projects. Django 3.0 support and unit test coverage 75%.

A debit is an accounting entry that either increases an asset or expense account,
or decreases a liability or equity account. Dividends/expenses/assets/losses increased with debit.
Debits are recorded on left in classic T format presentation of account entries.

A credit is an accounting entry that either increases a liability or equity account, or decreases an asset or expense account. 
Gains/income/revenues/liabilities/equity increased with credit.
Credits are recorded on right in classic T format presentation of account entries.

In the libary, debits are recorded as account entry objects with positive amount, and credits are recorded as objects with negative amount. 
Every entry is associated with an account, and account objects have always account type associated with them. 
Account type can have code, name and category (asset/liability account). Account entries also have entry types associated with them. 
Entry types can specify product code, name and entry classification (payment/settlement).

In addition to accounts and account entries, the library has models for basic invoices.



Install
=======

pip install django-jacc


Test Code Coverage
==================

* `coverage run manage.py; coverage report`


Changes
=======

3.2.0:
+ Django 3.0 support, prospector fixes

