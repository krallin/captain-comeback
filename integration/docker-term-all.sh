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

echo "Checking port ${TEST_PORT} is listening"
wait_for curl -s "http://127.0.0.1:${TEST_PORT}" >/dev/null

echo "Killing everything with SIGTERM"
kill -TERM $(cat "/sys/fs/cgroup/memory/docker/${cid}/tasks")

echo "Waiting for container to exit"
container_exited() {
  [[ "$(docker inspect -f "{{.State.Running}}" "$cid")" = "false" ]]
}
wait_for container_exited

echo "Restarting"
docker restart "$cid"

echo "Checking port ${TEST_PORT} is listening"
curl -s "http://127.0.0.1:${TEST_PORT}" >/dev/null

docker rm -f "$cid" 2>/dev/null
echo "SUCCESS"
