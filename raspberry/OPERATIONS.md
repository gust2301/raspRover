# RaspRover — Guide opérationnel

## 1. Connexion SSH

Depuis n'importe quel terminal sur le même réseau WiFi :

```bash
ssh ws@192.168.1.121
# mot de passe : ws
```

> Si l'IP change (redémarrage box), retrouve-la avec : `ping ugvrpi.local` ou regarde dans ton routeur.

---

## 2. Lancer le backend manuellement

```bash
cd /home/ws/raspRover/raspberry
/home/ws/raspRover/.venv/bin/python run_api_server.py
```

Le serveur tourne sur `http://192.168.1.121:8080` et expose aussi `https://192.168.1.121:8443`
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
/home/ws/raspRover/.venv/bin/pip install -r raspberry/requirements.txt
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
ssh ws@192.168.1.121

# 2. Mettre à jour le code
cd /home/ws/raspRover && git pull origin master

# 3. Mettre à jour les dépendances si besoin
/home/ws/raspRover/.venv/bin/pip install -r raspberry/requirements.txt

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

Ports disponibles sur la Pi 5 :
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

L'interface Waveshare est accessible sur `http://192.168.1.121:5000` ou `:8000`.

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

## 8. Référence rapide

| Quoi | Où |
|---|---|
| Code source | `/home/ws/raspRover/raspberry/` |
| Configuration | `/home/ws/raspRover/raspberry/config.yaml` |
| Logs applicatifs | `/home/ws/raspRover/raspberry/logs/rasprover.log` |
| Logs systemd | `journalctl -u rasprover-control` |
| API health | `http://192.168.1.121:8080/health` |
| API health HTTPS | `https://192.168.1.121:8443/health` |
| WebSocket | `ws://192.168.1.121:8080/ws` |
| WebSocket sécurisé | `wss://192.168.1.121:8443/ws` |
| Jupyter Waveshare | `http://192.168.1.121:8888` |
