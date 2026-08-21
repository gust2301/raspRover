# RaspRover — Guide opérationnel

## 1. Connexion SSH

Depuis n'importe quel terminal sur le même réseau WiFi :

```bash
ssh ws@192.168.1.24
```

> Si l'IP change (redémarrage box), retrouve-la avec : `ping robotpi.local` ou regarde dans ton routeur.

---

## 2. Lancer le backend manuellement

```bash
cd /home/ws/raspRover/raspberry
/home/ws/raspRover/raspberry/.venv/bin/python run_api_server.py
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
cd /home/ws/raspRover
git pull origin master
```

Si nouvelles dépendances Python (requirements.txt modifié) :

```bash
/home/ws/raspRover/raspberry/.venv/bin/pip install -r raspberry/requirements.txt
```

Puis relancer le serveur ou redémarrer le service systemd.

---

## 4. Service systemd (démarrage automatique au boot)

### Installer le service (une seule fois)

```bash
cd /home/ws/raspRover/raspberry
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
ssh ws@192.168.1.24

# 2. Mettre à jour le code
cd /home/ws/raspRover && git pull origin master

# 3. Mettre à jour les dépendances si besoin
/home/ws/raspRover/raspberry/.venv/bin/pip install -r raspberry/requirements.txt

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
nano /home/ws/raspRover/raspberry/config.yaml
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
cd /home/ws/raspRover
docker build -t ros2-lidar raspberry/ -f raspberry/Dockerfile.lidar
```

### Service ROS2 LIDAR (ros2-lidar.service)

```bash
sudo systemctl start ros2-lidar     # démarrer
sudo systemctl status ros2-lidar    # vérifier
journalctl -u ros2-lidar -f         # logs
```

### Cartographie SLAM (slam_toolbox)

Après chaque mise à jour des fichiers ROS, reconstruire l'image :

```bash
docker build -t ros2-lidar raspberry/ -f raspberry/Dockerfile.lidar
sudo systemctl restart ros2-lidar rasprover-control
```

```bash
# Lancer le SLAM (foreground — terminal dédié)
bash /home/ws/raspRover/raspberry/scripts/start_slam.sh

# Ou via l'interface web : Dashboard → Carte SLAM → Démarrer SLAM
```

Le SLAM utilise une odométrie différentielle estimée depuis les commandes moteurs,
puis corrigée par le scan matching. Les paramètres physiques sont dans la section
`slam` de `config.yaml`. Pour calibrer :

1. ajuster `max_linear_speed_m_s` après un trajet rectiligne mesuré ;
2. ajuster `wheel_separation_m` après une rotation complète sur place ;
3. renseigner la position et l'orientation réelles du LIDAR avec `laser_x_m`,
   `laser_y_m`, `laser_z_m` et `laser_yaw_deg`. Le montage supérieur actuel
   utilise `laser_x_m: 0.0`, `laser_y_m: 0.0` et `laser_z_m: 0.30` ; l'angle
   `laser_yaw_deg` doit correspondre à l'orientation réelle du scanner.

Le statut doit indiquer `ready: true` et les trois topics `scan`, `odom` et `map`.

### Endpoints API ROS2 / SLAM

| Endpoint | Méthode | Description |
|---|---|---|
| `/api/lidar/scan` | GET | Scan 360° ROS2 (JSON) |
| `/api/slam/status` | GET | État cartographie/navigation, pose et topics ROS |
| `/api/slam/start` | POST | Démarre slam_toolbox |
| `/api/slam/stop` | POST | Arrête slam_toolbox |
| `/api/slam/map` | GET | Carte courante en PNG base64 |
| `/api/slam/maps` | GET | Liste les cartes persistantes |
| `/api/slam/save` | POST | Sauvegarde dans le volume `rasprover-maps` |
| `/api/slam/load` | POST | Charge une carte et démarre AMCL + Nav2 |
| `/api/slam/pose` | GET | Position `x`, `y`, `yaw` du rover dans la carte |
| `/api/nav2/patrol/start` | POST | Lance une patrouille par points de passage |
| `/api/nav2/patrol/stop` | POST | Annule la patrouille et arrête les moteurs |
| `/api/nav2/patrol/status` | GET | Progression de la patrouille Nav2 |

Les fichiers YAML/PGM sont conservés dans le volume Docker nommé
`rasprover-maps`. Le conteneur peut donc être reconstruit ou supprimé sans
perdre les cartes. Ne supprimez pas ce volume lors d'un nettoyage Docker.

### Validation d'une feature Nav2 sur la Pi

Lors du tout premier essai (la version actuelle de `deploy` sur `master` ne
connaît pas encore les branches) :

```bash
ssh ws@192.168.1.24
cd ~/raspRover
git fetch origin codex/nav2-persistent-maps
git switch --track -c codex/nav2-persistent-maps origin/codex/nav2-persistent-maps
deploy
```

Pour les essais suivants, `deploy codex/nav2-persistent-maps` suffit.

Le dépôt de la Pi doit être propre. Pour revenir à la version stable :

```bash
deploy master
```

Après le premier déploiement, vérifier sans faire bouger le rover :

```bash
curl http://localhost:8080/api/slam/maps
curl http://localhost:8080/api/slam/status
docker volume inspect rasprover-maps
```

Depuis l'écran Carte, enregistrer une carte, redémarrer le conteneur et confirmer
qu'elle reste listée. Charger ensuite la carte avec le rover placé à l'origine
connue. Tester d'abord un seul point proche, roues levées ou dans une zone très
dégagée, puis valider l'arrêt avant une séquence de plusieurs points.

Le pont moteur Nav2 ignore les commandes tant qu'une mission n'a pas été lancée
par l'API. Il arrête aussi les moteurs si les commandes ROS cessent plus de 0,6 s.

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
ssh ws@192.168.1.24
cd /home/ws/raspRover
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
| Code source | `/home/ws/raspRover/raspberry/` |
| Configuration | `/home/ws/raspRover/raspberry/config.yaml` |
| Logs applicatifs | `/home/ws/raspRover/raspberry/logs/rasprover.log` |
| Logs systemd | `journalctl -u rasprover-control` |
| Logs ROS2 LIDAR | `journalctl -u ros2-lidar` |
| API health | `http://192.168.1.24:8080/health` |
| API health HTTPS | `https://192.168.1.24:8443/health` |
| API scan ROS2 | `http://192.168.1.24:8080/api/lidar/scan` |
| API carte SLAM | `http://192.168.1.24:8080/api/slam/map` |
| WebSocket | `ws://192.168.1.24:8080/ws` |
| WebSocket sécurisé | `wss://192.168.1.24:8443/ws` |
| Jupyter Waveshare | `http://192.168.1.24:8888` |
