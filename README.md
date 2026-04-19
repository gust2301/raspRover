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
# Script interactif pour tester moteurs + Pan-Tilt :
python3 -m tests.test_control
```

Commandes disponibles : `f` (avance), `b` (recul), `l` (gauche), `r` (droite), `s` (stop), `p <pan> <tilt>` (orienter caméra), `q` (quitter).

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
