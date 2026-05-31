#!/usr/bin/env bash
# Adds a 'deploy' shell alias to ~/.bashrc for quick deployments.
# Usage: bash ~/raspRover/raspberry/scripts/setup_alias.sh
set -euo pipefail

CURRENT_USER="$(logname)"
REPO_DIR="/home/${CURRENT_USER}/raspRover"
MARKER="# raspRover aliases"
BASHRC="/home/${CURRENT_USER}/.bashrc"

if grep -q "${MARKER}" "${BASHRC}" 2>/dev/null; then
  echo "Alias déjà présent dans ${BASHRC} — rien à faire."
  exit 0
fi

cat >> "${BASHRC}" <<EOF

${MARKER}
alias deploy="bash ${REPO_DIR}/raspberry/scripts/deploy.sh"
alias rover-logs="journalctl -u rasprover-control -f"
alias lidar-logs="journalctl -u ros2-lidar -f"
EOF

echo "Alias ajoutés à ${BASHRC} :"
echo "  deploy       → pull + restart services"
echo "  rover-logs   → logs rasprover-control en direct"
echo "  lidar-logs   → logs ros2-lidar en direct"
echo ""
echo "Recharge ta session : source ~/.bashrc"
