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
Account entries can have parent entry defined, which can be used to represent combined account entries.

In addition to accounts and account entries, the library has models for basic invoices.

[![codecov](https://codecov.io/gh/kajala/django-jacc/branch/master/graph/badge.svg)](https://codecov.io/gh/kajala/django-jacc)
[![Build Status](https://travis-ci.org/kajala/django-jacc.svg?branch=master)](https://travis-ci.org/kajala/django-jacc)



Install
=======

pip install django-jacc


Static Code Analysis
====================

The library passes both prospector and mypy checking. To install:

pip install prospector
pip install mypy

To analyze:

prospector
mypy .


Test Code Coverage
==================

* `coverage run manage.py; coverage report`


Changes
=======

* Upgraded to django-jutil 3.7.1

3.5.2:
* Updated README
* Upgraded dependencies

3.5.1:
* Squashed migrations 1-14
* Deploy process tweaks

3.4.8:
* Input sanitized fields

3.4.7:
* Upgrade
* Pre-release script tweaks
* Release process tweaks

3.4.6:
* Py typing tweaks

3.4.5:
* Test coverage update
* Cleanup, pytype integration

3.4.4:
* Float/dec2 fix

3.4.3:
* Typing tweaks

3.4.2:
* Mypy fixes
* MANIFEST tweaks
* Updated test coverage

3.4.1:
* Code QA related cleanup

3.3.4:
* Test coverage update

3.3.3:
* Test coverage update
* Test coverage script tweaks
* Added coverage.xml

3.3.2:
* Added travis config
* Updated LICENSE.txt
* Pytype config
* Pre-release script tweaks

3.3.1:
* Test coverage update
* Pytype integration to build process
* Pytype -V3.6 passes

3.2.3:
* Debug cleanup

3.2.2:
* Admin static fix

3.2.1:
* Django 3.0 compatibility
* Prospector fixes
* Docs

3.1.5:
* Amount None handling for settlements

3.1.4:
* Upgrade dependencies

3.1.3:
* Separated settle invoice / settle assigned invoice

3.1.2:
* Pre-release process
* Prospector usage in release
* Code QA / Prospector cleanup

3.1.1:
* Cleanup
* Optional timestamp to get late days

3.0.5:
* Upgrade dependencies

3.0.4:
* Longer account names
* gettext

3.0.3:
* Reverted migrations

3.0.2:
* Fixed squashed migration

3.0.1:
* Release 3.0.1
* Squashed migrations
* Deploy cleanup

2.1.18:
* More robust invoice summary
* License update

2.1.17:
* Upgrade dependencies

2.1.16:
* Variable amount credit note settling

2.1.15:
* Upgrade dependencies

2.1.14:
* Credit note description tweaks

2.1.13:
* Upgrade dependencies

2.1.12:
* l10n
* Entry cleanup

2.1.11:
* Dropped auto-invoice numbering

2.1.10:
* EntryType(s) as raw fields

2.1.9:
* Unit test fix

2.1.8:
* Separated EntryType identifier/code

2.1.7:
* Invoice numbering helper

2.1.6:
* Char field as invoice number to support non-numeric invoice numbers

2.1.5:
* Update invoices tweaks

2.1.4:
* Default parameter fix

2.1.3:
* Default credit note account entry timestamps
* Removed extra #

2.1.2:
* Dependency upgrade

2.1.1:
* Upgrade requirements

1.0.16:
* Optimized entry type get unique

1.0.15:
* Doc fixes

1.0.14:
* Admin tweaks

1.0.13:
* Admin tweaks

1.0.12:
* Extra validation

1.0.11:
* Entry type as str  

1.0.10:
* Entry code as str

1.0.9:
* EntryType.objects.get unique

1.0.8:
* Constraints

1.0.7:
* Replaced parse requirements

1.0.6:
* Upgraded dependencies

1.0.5:
* Bigger invoice number

1.0.3:
* Unit tests
* Calculate simple interest fix

1.0.2:
* Db indexing tweaks
* Parent entry editable by default

1.0.1:
* Upgraded dependencies

1.0.0:
* Docs
