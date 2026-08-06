#!/usr/bin/env bash
# Full install from scratch on a fresh Raspberry Pi OS Bookworm.
# Run with:  sudo bash raspberry/scripts/install_all.sh
set -euo pipefail

CURRENT_USER="$(logname)"
REPO_DIR="/home/${CURRENT_USER}/raspRover"
RASPBERRY_DIR="${REPO_DIR}/raspberry"

echo "==> Installation RaspRover pour l'utilisateur : ${CURRENT_USER}"
echo "    Répertoire repo : ${REPO_DIR}"
echo ""

# ── 1. Docker ────────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo "==> Installation de Docker..."
  curl -fsSL https://get.docker.com | sh
  usermod -aG docker "${CURRENT_USER}"
  systemctl enable --now docker
  echo "    Docker installé. L'utilisateur ${CURRENT_USER} ajouté au groupe docker."
  echo "    IMPORTANT : reconnecte-toi pour activer les droits docker sans sudo."
else
  echo "==> Docker déjà installé : $(docker --version)"
fi

# ── 2. Build image ROS2 + SLAM ───────────────────────────────────────────────
echo ""
echo "==> Build image Docker ros2-lidar (RPLIDAR + SLAM toolbox)..."
docker build -t ros2-lidar "${RASPBERRY_DIR}" -f "${RASPBERRY_DIR}/Dockerfile.lidar"
echo "    Image ros2-lidar construite."

# ── 3. udev rule for /dev/rplidar symlink ────────────────────────────────────
UDEV_RULE="/etc/udev/rules.d/99-rplidar.rules"
if [[ ! -f "${UDEV_RULE}" ]]; then
  echo ""
  echo "==> Création règle udev /dev/rplidar..."
  cat <<'EOF' > "${UDEV_RULE}"
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", SYMLINK+="rplidar"
EOF
  udevadm control --reload-rules
  udevadm trigger
  echo "    Règle udev créée : ${UDEV_RULE}"
fi

# ── 4. Python venv + dépendances ─────────────────────────────────────────────
echo ""
echo "==> Installation des dépendances Python..."
apt-get update
apt-get install -y python3-opencv python3-numpy
VENV="${RASPBERRY_DIR}/.venv"
if [[ ! -d "${VENV}" ]]; then
  sudo -u "${CURRENT_USER}" python3 -m venv "${VENV}"
fi
sudo -u "${CURRENT_USER}" "${VENV}/bin/pip" install --upgrade pip -q
sudo -u "${CURRENT_USER}" "${VENV}/bin/pip" install -r "${RASPBERRY_DIR}/requirements.txt" -q
echo "    Dépendances Python installées."

# ── 5. Systemd services ──────────────────────────────────────────────────────
echo ""
echo "==> Installation des services systemd..."
bash "${RASPBERRY_DIR}/install_systemd_service.sh"
echo "    Services rasprover-control et ros2-lidar installés."

echo ""
echo "================================================================"
echo " Installation terminée !"
echo " → API      : http://\$(hostname -I | awk '{print \$1}'):8080/health"
echo " → LIDAR    : sudo systemctl status ros2-lidar"
echo " → Déployer : bash ${RASPBERRY_DIR}/scripts/deploy.sh"
echo "================================================================"
