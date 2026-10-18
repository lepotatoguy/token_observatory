#!/bin/zsh
set -eu
umask 077
resources="${0:A:h:h}/Resources/dashboard"
runtime="$HOME/Library/Application Support/Token Observatory"
url='http://127.0.0.1:8765'
mkdir -p "$runtime"

healthy() {
  /usr/bin/curl --silent --fail --max-time 1 "$url/api/health" 2>/dev/null |
    /usr/bin/grep -q '"app":"token-observatory","version":2'
}

if ! healthy; then
  /usr/bin/nohup /usr/bin/python3 "$resources/server.py" --data-dir "$runtime/history" >>"$runtime/service.log" 2>&1 </dev/null &
fi
for attempt in {1..50}; do
  if healthy; then
    /usr/bin/open "$url"
    exit 0
  fi
  /bin/sleep 0.1
done
/usr/bin/open -a TextEdit "$runtime/service.log"
exit 1
