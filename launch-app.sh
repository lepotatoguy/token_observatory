#!/bin/zsh
set -eu
umask 077
resources="${0:A:h:h}/Resources/dashboard"
exec "$resources/.venv/bin/python" "$resources/launcher.py" "$@"
