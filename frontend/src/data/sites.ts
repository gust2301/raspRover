import type { Site } from '../types'

export const mockSites: Site[] = [
  { id: '1', name: 'Entrepôt Principal', location: 'Paris', robotCount: 2, cameraCount: 18, status: 'operational' },
  { id: '2', name: 'Chantier Nord', location: 'Lille', robotCount: 1, cameraCount: 6, status: 'operational' },
  { id: '3', name: 'Parking véhicules', location: 'Lyon', robotCount: 1, cameraCount: 12, status: 'degraded' },
  { id: '4', name: 'Résidence privée', location: 'Bordeaux', robotCount: 1, cameraCount: 8, status: 'operational' },
]
