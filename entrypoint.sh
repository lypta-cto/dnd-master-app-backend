#!/bin/sh
# The persistent disk is attached after the image is built, so it isn't part of
# the image's ownership and arrives belonging to root. The app runs as appuser
# and has to write uploaded and generated images into it, so the container
# starts as root, hands the mount over, and immediately drops privileges.
set -e

mkdir -p "${UPLOAD_DIR:-uploads}"
chown -R appuser:appuser "${UPLOAD_DIR:-uploads}"

exec gosu appuser "$@"
