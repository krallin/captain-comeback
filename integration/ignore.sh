#!/bin/bash
set -o errexit
set -o nounset

REL_HERE=$(dirname "${BASH_SOURCE}")
HERE=$(cd "${REL_HERE}"; pwd)
cd "$HERE"
. lib.sh

# This test ensures that the captain comeback does not restart a process that's
# not OOM.
HOG_MEMORY_LIMIT="$((1024 * 1024 * 128))"
HOG_ALLOC_LIMIT="$((HOG_MEMORY_LIMIT / 2))"

want_noswap
want_root
want_hog
clean_hog

run_captain_bg
run_hog_bg

sleep 15
terminate_captain

HOG_STARTS="$(hog_log | grep "hog up to" | wc -l)"

if [[ "$HOG_STARTS" -gt 1 ]]; then
  echo "FAIL: Hog was restarted"
  hog_log
  exit 1
fi

echo "SUCCESS"
exit 0
