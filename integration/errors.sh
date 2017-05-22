#!/bin/bash
# This test checks error handling in the CLI.

echo "Checking status code on bogus restart"
captain-comeback --restart foo >/dev/null 2>&1
if [[ "$?" != 1 ]]; then
  echo "Restarting a bogus container did not exit with 1!"
  exit 1
fi
echo "Status OK"

echo "Checking error message on bogus restart"
captain-comeback --restart foo 2>&1 \
  | grep -qE "ERROR.+foo"
if [[ "$?" != 0 ]]; then
  echo "Restarting a bogus container did not print an error"
  exit 1
fi
echo "Error OK"

echo "Checking warning on timeout"
cid="$(docker run -d alpine sleep 100)"
trap 'docker rm -f "$cid" >/dev/null 2>&1' EXIT
captain-comeback --restart "$cid" --restart-grace-period 1 2>&1 \
  | grep -qE "WARN.+${cid}.+did not exit"
if [[ "$?" != 0 ]]; then
  echo "Timing out on restart did not print a warning"
  exit 1
fi
echo "Warning OK"
