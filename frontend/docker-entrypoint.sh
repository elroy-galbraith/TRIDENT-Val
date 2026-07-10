#!/bin/sh
# Renders nginx.conf.template at container start rather than baking it in at build
# time, since neither the listen port nor the backend's URL are known until the
# container actually runs: Cloud Run assigns $PORT and passes the backend Cloud Run
# service's URL in $BACKEND_URL (see terraform/cloud_run.tf), while docker-compose
# runs the two containers on a fixed port with the backend reachable by service name.
set -e

export PORT="${PORT:-80}"
export BACKEND_URL="${BACKEND_URL:-http://backend:8000}"

envsubst '${PORT} ${BACKEND_URL}' < /etc/nginx/templates/nginx.conf.template > /etc/nginx/conf.d/default.conf

exec nginx -g 'daemon off;'
