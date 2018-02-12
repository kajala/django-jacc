python manage.py makemessages -i venv -i data
cd jacc/locale
python ../../manage.py compilemessages
cd ..
