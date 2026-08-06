# SENTRYX RaspRover

Robot mobile de surveillance construit autour d'un **Waveshare RaspRover PT 4WD** et d'une **Raspberry Pi 5**. Le projet regroupe une interface web type poste de contrôle, une API embarquée, le pilotage moteur/pan-tilt, le streaming caméra, la détection d'obstacles, les patrouilles autonomes et la journalisation d'incidents.

> Projet personnel réalisé pour explorer l'intégration robotique complète : contrôle temps réel, backend embarqué, vision, stockage média et interface opérateur.

## Aperçu

SENTRYX permet de piloter un rover de surveillance depuis un navigateur, de consulter son flux caméra, de déclencher des patrouilles et de récupérer les événements détectés pendant l'exécution. Le système peut tourner sur le robot réel ou en mode simulation grâce à un émulateur ESP32 fourni dans le dépôt.

Fonctionnalités principales :

- Pilotage manuel du rover : avance, recul, rotation, arrêt d'urgence.
- Contrôle de la caméra pan-tilt via servos ST3215.
- Flux vidéo MJPEG depuis la caméra Raspberry Pi.
- Détection d'obstacles par capteur ultrasonique et analyse d'image OpenCV.
- Détection humaine et suivi pan-tilt.
- Mode patrouille autonome avec évitement simple et création d'incidents.
- Capture photo, enregistrement vidéo et stockage optionnel Cloudflare R2.
- Interface web responsive installable comme PWA.
- API REST et WebSocket pour le contrôle et la télémétrie temps réel.
- Émulateur ESP32 pour développer sans le matériel.

## Stack technique

| Couche | Technologies |
|---|---|
| Frontend | React, TypeScript, Vite, Tailwind CSS, PWA |
| Backend embarqué | Python 3.11+, FastAPI, Uvicorn, WebSocket |
| Robotique | Raspberry Pi 5, ESP32 Waveshare, UART JSON line-delimited |
| Vision / capteurs | PiCamera2, OpenCV, HC-SR04 via Arduino |
| Stockage média | SQLite local, Cloudflare R2 optionnel |
| Qualité | Pytest, Ruff, émulateur matériel local |

## Matériel ciblé

| Composant | Détail |
|---|---|
| Plateforme | Waveshare RaspRover PT 4WD |
| Calculateur principal | Raspberry Pi 5 |
| Sous-contrôleur | ESP32 embarqué avec firmware Waveshare UGV |
| Caméra | Module caméra Raspberry Pi, flux MJPEG |
| Pan-tilt | 2 servos bus série ST3215 |
| Distance | HC-SR04 branché sur Arduino en USB série |
| Alimentation | Module UPS 3S + batteries Li-Ion 18650 |

## Architecture

```text
Navigateur / PWA React
        |
        | HTTP REST + WebSocket + MJPEG
        v
Raspberry Pi 5
  - FastAPI
  - contrôle moteur et pan-tilt
  - caméra, capture photo, vidéo
  - détection obstacle / humain
  - patrouilles et incidents
        |
        | UART /dev/ttyAMA0 ou socket://localhost:9999
        | protocole JSON line-delimited Waveshare
        v
ESP32 Waveshare
  - moteurs 4WD
  - servos ST3215
  - feedback batterie / IMU
```

## Structure du dépôt

```text
raspRover/
├── frontend/                 # Interface opérateur React/Vite
│   ├── src/pages/            # Dashboard, pilotage, caméras, patrouilles, incidents
│   ├── src/components/       # Cartes et contrôles UI
│   └── public/               # PWA, manifest, icônes
├── raspberry/                # Backend embarqué Python
│   ├── modules/api/          # API FastAPI, caméra, médias, SQLite
│   ├── modules/control/      # ESP32Link, moteurs, pan-tilt, lumières, patrouille
│   ├── modules/sensors/      # Ultrason, vision, détection humaine
│   ├── modules/audio/        # Alertes audio
│   ├── tools/fake_esp32.py   # Émulateur du firmware Waveshare
│   └── tests/                # Tests unitaires et tests de contrôle
└── arduino/                  # Sketch HC-SR04 pour Arduino
```

## Démarrage rapide en simulation

La simulation permet de tester le contrôle du rover sans Raspberry Pi ni ESP32 réel.

### Backend

```bash
cd raspberry
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.yaml.example config.yaml
```

Dans `config.yaml`, garder le port de simulation :

```yaml
control:
  serial_port: socket://localhost:9999
```

Terminal 1, lancer l'émulateur ESP32 :

```bash
python3 -m tools.fake_esp32 --viz
```

Terminal 2, lancer l'API :

```bash
python3 run_api_server.py --disable-https
```

L'API est disponible sur :

- `http://localhost:8080/health`
- `http://localhost:8080/stream`
- `ws://localhost:8080/ws`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Ouvrir l'URL Vite affichée dans le terminal, puis entrer `localhost` ou `http://localhost:8080` sur l'écran de connexion.

## Déploiement sur le RaspRover

Sur la Raspberry Pi :

```bash
cd raspberry
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.yaml.example config.yaml
```

Configurer ensuite le port série réel dans `raspberry/config.yaml` :

```yaml
control:
  serial_port: /dev/ttyAMA0
  baudrate: 115200
```

Activer l'UART matériel avec `raspi-config`, puis ajouter l'utilisateur au groupe série :

```bash
sudo usermod -aG dialout $USER
```

Un service systemd est fourni pour le démarrage automatique :

```bash
cd raspberry
sudo bash install_systemd_service.sh
sudo systemctl status rasprover-control
```

Documentation d'exploitation :

- [Connexion SSH et déploiement](raspberry/SSH_DEPLOYMENT.md)
- [Commandes opérationnelles](raspberry/OPERATIONS.md)

## API principale

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/health` | Vérifier que le backend répond |
| `GET` | `/stream` | Flux caméra MJPEG |
| `GET` | `/api/status` | Télémétrie robot |
| `POST` | `/api/motors/move` | Commander les moteurs |
| `POST` | `/api/motors/stop` | Arrêter le rover |
| `POST` | `/api/pantilt` | Orienter la caméra |
| `POST` | `/api/patrol/start` | Démarrer une patrouille |
| `POST` | `/api/patrol/stop` | Arrêter une patrouille |
| `GET` | `/api/incidents` | Lister les incidents |
| `WS` | `/ws` | Télémétrie et commandes temps réel |

## Tests

Backend :

```bash
cd raspberry
source .venv/bin/activate
pytest
ruff check .
```

Frontend :

```bash
cd frontend
npm run build
```

Test interactif du module de contrôle :

```bash
cd raspberry
python3 -m tests.test_control --port socket://localhost:9999
```

Remplacer `socket://localhost:9999` par `/dev/ttyAMA0` pour tester sur le robot réel.

## État du projet

Ce dépôt contient un prototype fonctionnel avec interface web, API embarquée, contrôle robot, vidéo, capteurs, patrouille et simulation locale. Les prochaines améliorations naturelles seraient la navigation cartographiée, une détection IA plus robuste, une gestion multi-robots complète et un tableau de bord d'observabilité plus détaillé.

## Auteur

Augustin Jr Varore  
Projet personnel, 2026.
