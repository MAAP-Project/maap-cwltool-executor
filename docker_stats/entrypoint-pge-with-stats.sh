#!/bin/bash
# set HOME explicitly
export HOME=/root

exec /docker-stats-on-exit-shim _docker_stats.json "$@"
echo "Finished running entrypoint-pge-with-stats."
