./venv/bin/python manage.py makemessages -l en -l fi -i '*venv*' -i '*web/static*' -i '*/data/*' -i '*.txt' -i '*uploads/*' -i '*downloads/*'
cd jacc/locale
../../venv/bin/python ../../manage.py compilemessages
