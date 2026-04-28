# RaspRover Surveillance System

Robot mobile de surveillance basé sur **Waveshare RaspRover PT** (ref. 26832) + **Raspberry Pi 5**.

## Matériel

| Composant | Détail |
|---|---|
| Plateforme | Waveshare RaspRover PT 4WD (châssis alu 2mm) |
| Calculateur principal | Raspberry Pi 5 (4-8 GB) |
| Sous-contrôleur | **ESP32** embarqué (firmware Waveshare UGV pré-flashé) |
| Pan-Tilt | 2× servos bus série **ST3215** (20 kg.cm) |
| Caméra | 5 MP, FOV 160° |
| Alimentation | Module UPS 3S + 3× batteries Li-Ion 18650 |
| Vitesse max | 0,65 m/s — rotation sur place (R=0) |

> Note : Le document technique d'origine mentionnait SG90/L298N, mais le kit Waveshare embarque en réalité un ESP32 + servos ST3215. Le code de ce projet est adapté à la réalité matérielle.

## Architecture logicielle

```
┌────────────────────────────────────────────┐
│  Navigateur (utilisateur)                  │
└──────────────┬─────────────────────────────┘
               │ HTTP/WebSocket (WiFi)
┌──────────────▼─────────────────────────────┐
│  Raspberry Pi 5  (Python 3.11+)            │
│  ├── modules/api         (Flask + WS)      │
│  ├── modules/video       (PiCamera2/MJPEG) │
│  ├── modules/surveillance (logique/alerte) │
│  ├── modules/perception  (OpenCV, HC-SR04) │
│  ├── modules/storage     (SSD NVMe)        │
│  └── modules/control     ◄── Développé ici │
└──────────────┬─────────────────────────────┘
               │ UART /dev/ttyS0 @ 115200 bauds
               │ Protocole : JSON line-delimited
┌──────────────▼─────────────────────────────┐
│  ESP32 (firmware Waveshare UGV)            │
│  ├── Pilotage moteurs 4WD (PWM)            │
│  ├── Contrôle servos ST3215 bus série      │
│  ├── Lecture IMU / batterie                │
│  └── Boucle temps-réel < 10 ms             │
└────────────────────────────────────────────┘
```

## Phase 1 livrée

- [x] **Module Contrôle** : liaison ESP32 + API haut niveau moteurs + Pan-Tilt
- [ ] Module Vidéo (à venir)
- [ ] Module Perception (à venir)
- [ ] Module Surveillance (à venir)
- [ ] Module Stockage (à venir)
- [ ] Module API / Interface Web (à venir)

## Installation

```bash
# Sur la Raspberry Pi 5, depuis le dossier du projet :
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Activer l'UART matériel sur la Pi 5 :
#   sudo raspi-config → Interface Options → Serial Port
#   - Login shell over serial : NO
#   - Serial hardware enabled : YES
# Puis redémarrer.

# Donner les droits série à l'utilisateur :
sudo usermod -aG dialout $USER
```

## Test rapide du Module Contrôle

```bash
# Script interactif pour tester moteurs + Pan-Tilt sur vrai matériel :
python3 -m tests.test_control --port /dev/ttyAMA0
```

Commandes disponibles : `f` (avance), `b` (recul), `l` (gauche), `r` (droite), `s` (stop), `p <pan> <tilt>` (orienter caméra), `c` (recentre caméra), `fb` / `fb126` / `fb130` (diagnostic feedback), `echo on|off`, `stream on|off`, `raw <json>`, `rx`, `?` (état), `q` (quitter).

Notes protocole Waveshare :

- Vitesse châssis : `{"T":1,"L":0.5,"R":0.5}`
- Pan-Tilt : `{"T":133,"X":45,"Y":10,"SPD":600,"ACC":50}`
- Feedback châssis : `{"T":130}`
- IMU / statut : `{"T":126}`

## Tester SANS le matériel (émulateur)

En attendant le RaspRover physique, un émulateur ESP32 livré avec le projet reproduit le protocole JSON-UART Waveshare UGV sur un socket TCP local. Il maintient un état robot virtuel (position 2D intégrée, angles Pan-Tilt, batterie qui se décharge) et répond aux commandes comme le ferait le firmware réel. Pas besoin de driver virtuel : ça marche sous Windows, macOS et Linux.

Terminal 1 — lancer l'émulateur :

```bash
python3 -m tools.fake_esp32                # par défaut localhost:9999
python3 -m tools.fake_esp32 --viz          # avec mini ASCII map temps-réel
python3 -m tools.fake_esp32 --port 9999
```

Terminal 2 — pointer le code sur l'émulateur (URL `socket://` au lieu d'un port série) :

```bash
# REPL interactif :
python3 -m tests.test_control --port socket://localhost:9999

# Ou édition de config.yaml :
#   serial_port: socket://localhost:9999
# puis : python3 main.py

# Ou directement en Python :
from modules.control import ESP32Link, MotorController, PanTiltController
link = ESP32Link(port="socket://localhost:9999")
link.open()
motors = MotorController(link)
motors.forward(0.4)
```

Pour basculer vers le vrai matériel, remplacer `socket://localhost:9999` par `/dev/ttyAMA0` (UART hardware Pi 5) ou `/dev/ttyUSB0` (ESP32 en USB) — le reste du code ne change pas.

### Limites de l'émulateur et alternatives plus poussées

L'émulateur livré simule : le protocole JSON, la physique 2D différentielle, la batterie, et le feedback (T=126). Il ne simule pas la vidéo, le capteur ultrasonique, ni les collisions.

Pour aller plus loin quand vous aurez besoin de tester la détection visuelle et la navigation :

- **Webots** (gratuit, officiellement recommandé pour robots Waveshare) — simulation 3D complète avec caméras, capteurs ultrasoniques, physique réaliste
- **Gazebo + ROS 2 Humble** (le kit supporte ROS 2) — écosystème standard en robotique, nodes caméra et lidar disponibles
- **Photos/vidéos en playback** : pour la Phase 4 (détection IA), on peut rejouer un fichier MP4 au lieu de la caméra réelle via OpenCV — pas besoin de matériel du tout

## Structure du dépôt

```
raspRover/
├── README.md
├── requirements.txt
├── config.yaml                     # Ports série, vitesses max, limites angulaires
├── main.py                         # Point d'entrée (stub)
├── modules/
│   ├── __init__.py
│   └── control/
│       ├── __init__.py
│       ├── esp32_link.py           # Couche basse : JSON-UART vers ESP32
│       ├── motor_controller.py     # API haut niveau : move / stop / rotate
│       ├── pantilt_controller.py   # API Pan-Tilt ST3215
│       └── exceptions.py
└── tests/
    ├── __init__.py
    └── test_control.py             # REPL interactif pour essais réels
```
