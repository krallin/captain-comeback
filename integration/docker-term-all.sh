#!/bin/bash
# This test just checks that sending SIGTERM to all the PIDS in a container and
# restarting it at a later time (once it has exited) still brings the container
# back up with ports.
set -o errexit
set -o nounset

REL_HERE=$(dirname "${BASH_SOURCE}")
HERE=$(cd "${REL_HERE}"; pwd)
cd "$HERE"
. lib.sh

TEST_PORT=4628

echo "Running container"
cid="$(docker run -d --publish "$TEST_PORT":80 alpine sh -c 'httpd -f')"
cleanup() {
  docker rm -f "$cid" >/dev/null 2>&1
}
trap cleanup EXIT

echo "Checking port ${TEST_PORT} is listening"
wait_for curl -s "http://127.0.0.1:${TEST_PORT}" >/dev/null

echo "Restarting container"
captain-comeback --restart "$cid"

echo "Checking port ${TEST_PORT} is listening"
curl -s "http://127.0.0.1:${TEST_PORT}" >/dev/null

echo "SUCCESS"
