# RaspRover — Guide opérationnel

## 1. Connexion SSH

Depuis n'importe quel terminal sur le même réseau WiFi :

```bash
ssh gust@192.168.1.24
# mot de passe : gust
```

> Si l'IP change (redémarrage box), retrouve-la avec : `ping robotpi.local` ou regarde dans ton routeur.

---

## 2. Lancer le backend manuellement

```bash
cd /home/gust/raspRover/raspberry
/home/gust/raspRover/raspberry/.venv/bin/python run_api_server.py
```

Le serveur tourne sur `http://192.168.1.24:8080` et expose aussi `https://192.168.1.24:8443`
si `api.https.enabled: true` dans `config.yaml`. Pour vérifier :

```bash
curl http://localhost:8080/health
curl -k https://localhost:8443/health
```

Arrêter : `Ctrl+C`

---

## 3. Mettre à jour le code

```bash
cd /home/gust/raspRover
git pull origin master
```

Si nouvelles dépendances Python (requirements.txt modifié) :

```bash
/home/gust/raspRover/raspberry/.venv/bin/pip install -r raspberry/requirements.txt
```

Puis relancer le serveur ou redémarrer le service systemd.

---

## 4. Service systemd (démarrage automatique au boot)

### Installer le service (une seule fois)

```bash
cd /home/gust/raspRover/raspberry
sudo bash install_systemd_service.sh
```

### Commandes du quotidien

```bash
# Statut
sudo systemctl status rasprover-control

# Démarrer
sudo systemctl start rasprover-control

# Arrêter
sudo systemctl stop rasprover-control

# Redémarrer (après mise à jour du code)
sudo systemctl restart rasprover-control

# Logs en direct
journalctl -u rasprover-control -f

# 50 dernières lignes de logs
journalctl -u rasprover-control -n 50
```

### Activer / désactiver le démarrage automatique

```bash
sudo systemctl enable rasprover-control   # démarre au boot
sudo systemctl disable rasprover-control  # ne démarre plus au boot
```

---

## 5. Workflow complet — mise à jour + redémarrage

```bash
# 1. Se connecter
ssh gust@192.168.1.24

# 2. Mettre à jour le code
cd /home/gust/raspRover && git pull origin master

# 3. Mettre à jour les dépendances si besoin
/home/gust/raspRover/raspberry/.venv/bin/pip install -r raspberry/requirements.txt

# 4. Redémarrer le service
sudo systemctl restart rasprover-control

# 5. Vérifier que tout va bien
sudo systemctl status rasprover-control
curl http://localhost:8080/health
```

---

## 6. Dépannage

### Le service ne démarre pas

```bash
journalctl -u rasprover-control -n 30
```

Causes fréquentes :
- Port série occupé → vérifier : `sudo fuser /dev/ttyAMA0`
- Mauvais port série → éditer `raspberry/config.yaml`, changer `serial_port`
- Dépendances manquantes → relancer `pip install -r requirements.txt`

### Changer le port série

```bash
nano /home/gust/raspRover/raspberry/config.yaml
# Modifier serial_port : /dev/ttyAMA0
```

Ports disponibles sur la Pi :
- `/dev/ttyAMA0` — UART principal (ESP32 Waveshare)
- `/dev/ttyAMA10` — UART secondaire

### Tuer un processus qui bloque le port série

```bash
sudo fuser -k /dev/ttyAMA0
```

---

## 7. Switcher entre notre service et l'interface Waveshare

Les deux systèmes ne peuvent pas tourner en même temps — ils se disputent `/dev/ttyAMA0`.

### Passer à l'interface Waveshare (port 5000/8000)

```bash
# 1. Arrêter notre service
sudo systemctl stop rasprover-control

# 2. Lancer app.py Waveshare
cd ~/ugv_rpi && ugv-env/bin/python app.py
```

L'interface Waveshare est accessible sur `http://192.168.1.24:5000` ou `:8000`.

Pour arrêter : `Ctrl+C` dans le terminal SSH.

### Repasser à notre service (SENTRYX)

```bash
# 1. Tuer app.py si encore actif
sudo fuser -k /dev/ttyAMA0

# 2. Redémarrer notre service
sudo systemctl start rasprover-control
sudo systemctl status rasprover-control
```

### État actuel du démarrage automatique

- **Notre service** démarre automatiquement au boot (`systemctl enable rasprover-control`)
- **app.py Waveshare** est désactivé au boot (ligne commentée dans `crontab -e`)

Pour réactiver app.py au boot : `crontab -e` → décommenter la ligne `@reboot`.
Pour désactiver notre service au boot : `sudo systemctl disable rasprover-control`.

---

## 8. ROS2 LIDAR & SLAM

### Build de l'image Docker

```bash
cd /home/gust/raspRover
docker build -t ros2-lidar raspberry/ -f raspberry/Dockerfile.lidar
```

### Service ROS2 LIDAR (ros2-lidar.service)

```bash
sudo systemctl start ros2-lidar     # démarrer
sudo systemctl status ros2-lidar    # vérifier
journalctl -u ros2-lidar -f         # logs
```

### Cartographie SLAM (slam_toolbox)

```bash
# Lancer le SLAM (foreground — terminal dédié)
bash /home/gust/raspRover/raspberry/scripts/start_slam.sh

# Ou via l'interface web : Dashboard → Carte SLAM → Démarrer SLAM
```

### Endpoints API ROS2 / SLAM

| Endpoint | Méthode | Description |
|---|---|---|
| `/api/lidar/scan` | GET | Scan 360° ROS2 (JSON) |
| `/api/slam/status` | GET | État du container ros2-slam |
| `/api/slam/start` | POST | Démarre slam_toolbox |
| `/api/slam/stop` | POST | Arrête slam_toolbox |
| `/api/slam/map` | GET | Carte courante en PNG base64 |
| `/api/slam/save` | POST | Sauvegarde la carte sur le Pi |

---

## 9. Scripts d'automatisation

| Script | Description |
|---|---|
| `raspberry/scripts/install_all.sh` | Installation complète depuis zéro (Docker, image, pip, services) |
| `raspberry/scripts/deploy.sh` | `git pull` + redémarrage des deux services |
| `raspberry/scripts/setup_alias.sh` | Ajoute `deploy`, `rover-logs`, `lidar-logs` à `~/.bashrc` |
| `raspberry/scripts/start_slam.sh` | Démarre le SLAM en foreground |

### Installation initiale

```bash
ssh gust@192.168.1.24
cd /home/gust/raspRover
sudo bash raspberry/scripts/install_all.sh
```

### Déploiement rapide (mise à jour code)

```bash
bash ~/raspRover/raspberry/scripts/deploy.sh
# ou, après setup_alias.sh :
deploy
```

### Configurer les alias shell

```bash
bash ~/raspRover/raspberry/scripts/setup_alias.sh
source ~/.bashrc
```

---

## 10. Référence rapide

| Quoi | Où |
|---|---|
| Code source | `/home/gust/raspRover/raspberry/` |
| Configuration | `/home/gust/raspRover/raspberry/config.yaml` |
| Logs applicatifs | `/home/gust/raspRover/raspberry/logs/rasprover.log` |
| Logs systemd | `journalctl -u rasprover-control` |
| Logs ROS2 LIDAR | `journalctl -u ros2-lidar` |
| API health | `http://192.168.1.24:8080/health` |
| API health HTTPS | `https://192.168.1.24:8443/health` |
| API scan ROS2 | `http://192.168.1.24:8080/api/lidar/scan` |
| API carte SLAM | `http://192.168.1.24:8080/api/slam/map` |
| WebSocket | `ws://192.168.1.24:8080/ws` |
| WebSocket sécurisé | `wss://192.168.1.24:8443/ws` |
| Jupyter Waveshare | `http://192.168.1.24:8888` |
