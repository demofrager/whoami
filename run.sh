#!/bin/bash
set -eu

# Note: These commands assume access to the local LAN registry at registry.plsdontspam.me.

IMAGE="registry.plsdontspam.me/myapp"
TAG="latest"

usage() {
  cat <<'USAGE'
Usage: ./run.sh <command>

Commands:
  build        Build the Docker image
  push         Push the Docker image to the registry
  run_homelab  Run the container on proxynet (host port 5001 -> container 5000)
  run_local    Run the Flask app locally
USAGE
}

cmd="${1:-}"
case "$cmd" in
  build)
    docker build -t "$IMAGE:$TAG" .
    ;;
  push)
    docker push "$IMAGE"
    ;;
  run_homelab)
    docker run --network proxynet -p 5001:5000 "$IMAGE"
    ;;
  run_local)
    FLASK_APP=app.py python -m flask run
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    usage
    exit 1
    ;;
esac
