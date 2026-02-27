#!/usr/bin/env bash
#
# Install or remove the cron job for Indus Feedback Collector.
#
#   ./setup_cron.sh install   — adds a cron entry (every 4 hours)
#   ./setup_cron.sh remove    — removes the cron entry
#   ./setup_cron.sh status    — shows if the job is installed
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${SCRIPT_DIR}/.venv/bin/python3"
COLLECTOR="${SCRIPT_DIR}/collector.py"
MARKER="# indus-feedback-collector"

CRON_LINE="0 */4 * * * cd ${SCRIPT_DIR} && ${PYTHON} ${COLLECTOR} >> ${SCRIPT_DIR}/data/cron.log 2>&1 ${MARKER}"

case "${1:-}" in
  install)
    (crontab -l 2>/dev/null | grep -v "${MARKER}"; echo "${CRON_LINE}") | crontab -
    echo "Cron job installed — runs every 4 hours."
    echo "  Logs: ${SCRIPT_DIR}/data/cron.log"
    echo ""
    echo "Verify with:  crontab -l"
    ;;
  remove)
    crontab -l 2>/dev/null | grep -v "${MARKER}" | crontab -
    echo "Cron job removed."
    ;;
  status)
    if crontab -l 2>/dev/null | grep -q "${MARKER}"; then
      echo "Cron job is INSTALLED:"
      crontab -l | grep "${MARKER}"
    else
      echo "Cron job is NOT installed."
    fi
    ;;
  *)
    echo "Usage: $0 {install|remove|status}"
    exit 1
    ;;
esac
