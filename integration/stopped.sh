#!/bin/bash
set -o errexit
set -o nounset

REL_HERE=$(dirname "${BASH_SOURCE}")
HERE=$(cd "${REL_HERE}"; pwd)
cd "$HERE"
. lib.sh

CANARY="foobar"

# This test ensures that we can restart a stopped container.
want_root

echo "Test stopped restart"
cid="$(docker create alpine sh -c "echo ${CANARY}")"
captain-comeback --restart "$cid"
docker wait "$cid"
docker logs "$cid" | grep "$CANARY"
docker rm "$cid"

echo "Test stopped restart with wipe"
cid="$(docker create alpine sh -c "echo ${CANARY}")"
captain-comeback --wipe-fs --restart "$cid"
docker wait "$cid"
docker logs "$cid" | grep "$CANARY"
docker rm "$cid"
