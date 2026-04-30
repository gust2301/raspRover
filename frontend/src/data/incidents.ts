import type { Incident, SystemLog } from '../types'

export const mockIncidents: Incident[] = [
  { id: '1', type: 'Mouvement détecté', zone: 'Zone A1', description: 'Allée 3', time: '14:32', level: 'warning', resolved: false },
  { id: '2', type: 'Présence humaine', zone: 'Zone B2', description: 'Entrée principale', time: '14:28', level: 'critical', resolved: false },
  { id: '3', type: 'Véhicule détecté', zone: 'Zone Parking', description: 'Entrée Est', time: '14:15', level: 'warning', resolved: false },
  { id: '4', type: 'Batterie faible', zone: 'Robot SX-002', description: 'Niveau 15%', time: '13:47', level: 'warning', resolved: false },
  { id: '5', type: 'Patrouille terminée', zone: 'Entrepôt Nord', description: 'Itinéraire complet', time: '13:30', level: 'success', resolved: true },
]

export const mockLogs: SystemLog[] = [
  { id: '1', message: 'Connexion ESP32 établie', time: '14:35', type: 'success' },
  { id: '2', message: 'Caméra principale active', time: '14:35', type: 'info' },
  { id: '3', message: 'Patrouille Zone A démarrée', time: '14:20', type: 'info' },
  { id: '4', message: 'Signal WiFi stable — 98%', time: '14:15', type: 'success' },
  { id: '5', message: 'Commande reçue : avance', time: '14:10', type: 'info' },
  { id: '6', message: 'Batterie SX-002 faible', time: '13:47', type: 'warning' },
]
