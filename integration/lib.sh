#!/bin/bash
HOG_CONTAINER_NAME="captain-comeback-hog"
CAPTAIN_PID="0"
CAPTAIN_TERMINATED="1"

HOG_ALLOC_LIMIT=0


want_root() {
  if [ "$(id -u)" != "0" ]; then
    echo "You need to be root to run this test"
    exit 1
  fi
}

want_noswap() {
  true
}

want_hog() {
  test -f hog
}


_run_hog_internal() {
  docker rm "$HOG_CONTAINER_NAME" >/dev/null 2>&1 || true

  local opts=("--memory" "$HOG_MEMORY_LIMIT"
        "--name" "$HOG_CONTAINER_NAME"
        "-v" "$(pwd):/hog"
        "tianon/true" "/hog/hog")

  if [[ "$HOG_ALLOC_LIMIT" -gt 0 ]]; then
    opts+=("$HOG_ALLOC_LIMIT")
  fi

  docker run "$@" "${opts[@]}"
}

run_hog_fg() {
  _run_hog_internal
}

run_hog_bg() {
  _run_hog_internal "-d"
}

hog_log() {
  docker logs "$HOG_CONTAINER_NAME"
}

clean_hog() {
  docker rm -f "$HOG_CONTAINER_NAME" >/dev/null 2>&1 || true
}


terminate_captain() {
  if [[ "$CAPTAIN_TERMINATED" -eq 1 ]]; then
    return
  fi
  kill -TERM "$CAPTAIN_PID"
  CAPTAIN_TERMINATED=1

  rm -rf "$CAPTAIN_ACTIVITY_DIR"
  unset CAPTAIN_ACTIVITY_DIR
}

terminate_captain_at_exit() {
  trap terminate_captain EXIT
}

run_captain_bg() {
  CAPTAIN_ACTIVITY_DIR="$(mktemp -d)"
  captain-comeback "$@" --activity "$CAPTAIN_ACTIVITY_DIR" &
  CAPTAIN_PID="$!"
  CAPTAIN_TERMINATED=0
  terminate_captain_at_exit
}

wait_for() {
  for i in $(seq 0 50); do
    if "$@" ; then
      return 0
    fi
    sleep 0.1
  done

  return 1
}
