#!/bin/bash
set -e
# Process templates with envsubst
for tmpl in /etc/asterisk/templates/*.tmpl; do
    envsubst < "$tmpl" > "/etc/asterisk/$(basename ${tmpl%.tmpl})"
done
# extensions.conf: nur BRIDGE_PORT und AUDIOSOCKET_PORT substituieren,
# alle anderen Asterisk-Variablen (${EXTEN}, ${CALLERID}, ...) bleiben erhalten
if [ -f /etc/asterisk/templates/extensions.conf ]; then
    envsubst '${BRIDGE_PORT} ${AUDIOSOCKET_PORT}' \
        < /etc/asterisk/templates/extensions.conf \
        > /etc/asterisk/extensions.conf
fi
mkdir -p /var/lib/asterisk/sounds/custom
exec "$@"
