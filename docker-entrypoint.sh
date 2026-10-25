#!/bin/sh
set -e
python manage.py migrate --noinput
exec gunicorn config.wsgi:application -c gunicorn.conf.py
