#!/bin/bash
set -o errexit
set -o nounset

REL_HERE=$(dirname "${BASH_SOURCE}")
HERE=$(cd "${REL_HERE}"; pwd)
cd "$HERE"
. lib.sh

want_root

echo "Test new files are deleted"
cid="$(docker run -d alpine sh -c 'if test -f foo; then exit 1; else touch foo && sleep 100; fi')"
captain-comeback --restart-grace-period 1 --wipe-fs --restart "$cid"
sleep 2
docker top "$cid" # Container should NOT have exited by now
docker rm -f "$cid"

# File should have been backed up
find "/var/lib/docker/.captain-comeback-backup/${cid}/" | grep foo


echo "Test deleted files are restored"
cid="$(docker run -d alpine sh -c 'if test -d /var/log; then rm -r /var/log && sleep 100; else exit 1; fi')"
captain-comeback --restart-grace-period 1 --wipe-fs --restart "$cid"
sleep 2
docker top "$cid" # Container should NOT have exited by now
docker rm -f "$cid"
