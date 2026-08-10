# RaspRover — Connexion SSH et déploiement

Ce guide décrit la connexion à la Raspberry Pi et le déploiement de SENTRYX.

## Informations de référence

| Élément | Valeur |
|---|---|
| Utilisateur Raspberry Pi | `ws` |
| Adresse IP locale | `192.168.1.24` |
| Connexion SSH | `ssh ws@192.168.1.24` |
| Dépôt sur la Pi | `/home/ws/raspRover` |
| Backend | `/home/ws/raspRover/raspberry` |
| API locale | `http://192.168.1.24:8080` |
| Branche déployée | `master` |

Le Mac et la Pi doivent être connectés au même réseau local. Si l'adresse IP
change, consulter le routeur ou essayer `ping ugvrpi.local`.

## 1. Première connexion SSH

Depuis le Terminal du Mac :

```bash
ssh ws@192.168.1.24
```

À la première connexion, SSH affiche l'empreinte de la Pi. Vérifier que la cible
est bien la Raspberry Pi, saisir `yes`, puis entrer le mot de passe de `ws`.

Une connexion réussie affiche une invite similaire à :

```text
ws@ugvrpi:~ $
```

Pour quitter la Pi :

```bash
exit
```

## 2. Connexion avec une clé SSH

Cette étape évite de saisir le mot de passe à chaque connexion.

### Créer une clé sur le Mac

Vérifier d'abord si une clé existe :

```bash
ls -l ~/.ssh/*.pub
```

Si nécessaire, créer une clé dédiée à la Pi :

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_rasprover -C "rasprover-pi"
```

### Installer la clé publique sur la Pi

```bash
ssh-copy-id -i ~/.ssh/id_ed25519_rasprover.pub ws@192.168.1.24
```

Si `ssh-copy-id` n'est pas disponible sur le Mac :

```bash
cat ~/.ssh/id_ed25519_rasprover.pub | \
  ssh ws@192.168.1.24 'umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys'
```

Ajouter ensuite ce bloc dans `~/.ssh/config` sur le Mac :

```sshconfig
Host rasprover
  HostName 192.168.1.24
  User ws
  IdentityFile ~/.ssh/id_ed25519_rasprover
  IdentitiesOnly yes
```

La connexion devient alors :

```bash
ssh rasprover
```

Tester sans mot de passe interactif :

```bash
ssh -o BatchMode=yes rasprover 'hostname && whoami'
```

## 3. Installation initiale du projet

Cette procédure est destinée à une Pi neuve. Elle installe Docker, les
dépendances Python, OpenCV, l'image ROS 2 et les services systemd.

```bash
ssh ws@192.168.1.24
cd /home/ws/raspRover
sudo bash raspberry/scripts/install_all.sh
```

Installer les alias pratiques :

```bash
bash ~/raspRover/raspberry/scripts/setup_alias.sh
source ~/.bashrc
```

Les alias disponibles sont :

| Alias | Fonction |
|---|---|
| `deploy` | Pull Git, dépendances, reconstruction ROS si nécessaire et redémarrage |
| `rover-logs` | Logs temps réel du backend |
| `lidar-logs` | Logs temps réel du service LIDAR |

## 4. Déploiement quotidien

Après avoir poussé du code sur la branche à tester, se connecter à la Pi :

```bash
ssh ws@192.168.1.24
```

Puis lancer :

```bash
deploy
```

Par défaut, `deploy` met à jour la branche déjà active. Lors du premier passage
depuis une ancienne version du script, récupérer et activer manuellement la
branche :

```bash
cd ~/raspRover
git fetch origin codex/nav2-persistent-maps
git switch --track -c codex/nav2-persistent-maps origin/codex/nav2-persistent-maps
deploy
```

Pour les déploiements suivants, préciser directement la branche :

```bash
deploy codex/nav2-persistent-maps
```

Le script refuse de changer de branche si le dépôt contient des modifications
locales. Pour revenir à la version stable : `deploy master`.

Sans alias :

```bash
bash ~/raspRover/raspberry/scripts/deploy.sh
```

Le script effectue automatiquement :

1. récupération et mise à jour en avance rapide de la branche demandée ;
2. la mise à jour des dépendances Python ;
3. l'installation d'OpenCV système si nécessaire ;
4. la reconstruction de `ros2-lidar` si Docker, ROS ou SLAM ont changé ;
5. le redémarrage de `rasprover-control` ;
6. le redémarrage de `ros2-lidar` lorsque nécessaire.

Ne pas interrompre le script pendant un build Docker ou un redémarrage systemd.

## 5. Vérifications après déploiement

### Services

```bash
sudo systemctl is-active rasprover-control ros2-lidar
sudo systemctl status rasprover-control ros2-lidar --no-pager -l
```

Résultat attendu pour les deux services : `active`.

### API

```bash
curl http://localhost:8080/health
curl http://localhost:8080/api/status
```

### LIDAR

```bash
docker inspect -f '{{.State.Running}}' ros2-lidar

docker exec ros2-lidar bash -c \
  'source /opt/ros/jazzy/setup.bash && timeout 8 ros2 topic echo /scan --once'
```

Le premier résultat doit être `true` et le second doit afficher un message
`sensor_msgs/msg/LaserScan`.

### SLAM

Démarrer le SLAM depuis la page **Carte SLAM** de l'application, patienter
quelques secondes, puis vérifier :

```bash
curl http://localhost:8080/api/slam/status
curl http://localhost:8080/api/slam/map
```

Un SLAM opérationnel retourne notamment :

```json
{
  "running": true,
  "ready": true,
  "topics": {
    "map": true,
    "odom": true,
    "scan": true
  }
}
```

`curl -I /api/slam/map` n'est pas un test valide : `-I` envoie une requête
`HEAD`, tandis que cet endpoint accepte `GET`.

## 6. Commandes d'exploitation

### Backend

```bash
sudo systemctl start rasprover-control
sudo systemctl stop rasprover-control
sudo systemctl restart rasprover-control
journalctl -u rasprover-control -f
journalctl -u rasprover-control -n 100 --no-pager -l
```

### LIDAR

```bash
sudo systemctl start ros2-lidar
sudo systemctl stop ros2-lidar
sudo systemctl restart ros2-lidar
journalctl -u ros2-lidar -f
journalctl -u ros2-lidar -n 100 --no-pager -l
```

### Conteneur ROS 2

```bash
docker ps --filter name=ros2-lidar
docker logs --tail 100 ros2-lidar

docker exec ros2-lidar bash -c \
  'source /opt/ros/jazzy/setup.bash && ros2 node list && ros2 topic list'
```

### Logs SLAM

```bash
docker exec ros2-lidar tail -n 100 /tmp/rasprover_slam.log
```

## 7. Reconstruction manuelle de ROS/SLAM

Le script `deploy` le fait normalement lorsqu'il détecte un changement. Pour
forcer une reconstruction :

```bash
cd ~/raspRover
docker build -t ros2-lidar raspberry/ -f raspberry/Dockerfile.lidar
sudo systemctl restart ros2-lidar rasprover-control
```

## 8. Dépannage SSH

### L'adresse de la Pi a changé

```bash
ping ugvrpi.local
ssh ws@ugvrpi.local
```

On peut aussi retrouver l'adresse dans l'interface du routeur.

### Avertissement « REMOTE HOST IDENTIFICATION HAS CHANGED »

Vérifier d'abord qu'il s'agit bien de la Pi réinstallée ou dont la clé hôte a
changé. Supprimer ensuite uniquement l'ancienne entrée concernée :

```bash
ssh-keygen -R 192.168.1.24
ssh ws@192.168.1.24
```

### Permission denied (publickey)

```bash
ssh -vvv ws@192.168.1.24
ls -ld ~/.ssh
ls -l ~/.ssh/authorized_keys
```

Sur la Pi, les permissions attendues sont :

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

## 9. Dépannage du déploiement

### Modifications locales empêchant le pull

```bash
cd ~/raspRover
git status
```

Ne pas supprimer les modifications sans les examiner. Les sauvegarder dans un
commit ou demander de l'aide avant d'utiliser une commande destructive.

### L'API ne répond pas

```bash
sudo systemctl status rasprover-control --no-pager -l
journalctl -u rasprover-control -n 100 --no-pager -l
curl http://localhost:8080/health
```

### Le conteneur LIDAR n'est pas actif

```bash
sudo systemctl reset-failed ros2-lidar
sudo systemctl restart ros2-lidar
sleep 8
docker inspect -f '{{.State.Running}}' ros2-lidar
journalctl -u ros2-lidar -n 100 --no-pager -l
```

### Le LIDAR ne publie plus `/scan`

```bash
ls -l /dev/rplidar /dev/ttyUSB0
sudo fuser -v /dev/rplidar /dev/ttyUSB0
journalctl -u ros2-lidar -n 100 --no-pager -l
```

Si le pilote reste bloqué, arrêter `ros2-lidar`, débrancher le LIDAR pendant
10 secondes, le rebrancher, puis redémarrer le service.

### Le SLAM tourne mais aucune carte n'apparaît

```bash
curl http://localhost:8080/api/slam/status
curl http://localhost:8080/api/slam/map

docker exec ros2-lidar bash -c '
source /opt/ros/jazzy/setup.bash
ros2 lifecycle get /slam_toolbox
ros2 topic info /map -v
tail -n 100 /tmp/rasprover_slam.log
'
```

L'état lifecycle attendu est `active [3]` et `/map` doit avoir un publisher.

## 10. Séquence de récupération sûre

En cas de problème après un déploiement, rétablir les composants dans cet ordre :

```bash
# 1. Arrêter le backend et le SLAM
sudo systemctl stop rasprover-control

# 2. Rétablir le LIDAR
sudo systemctl restart ros2-lidar
sleep 8

# 3. Vérifier /scan
docker exec ros2-lidar bash -c \
  'source /opt/ros/jazzy/setup.bash && timeout 8 ros2 topic echo /scan --once'

# 4. Redémarrer le backend
sudo systemctl start rasprover-control

# 5. Démarrer ensuite le SLAM depuis l'application
```

Toujours valider `/scan` avant de diagnostiquer `/odom` ou `/map`.
