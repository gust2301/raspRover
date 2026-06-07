export type RobotStatus = 'online' | 'offline' | 'maintenance'
export type MissionStatus = 'idle' | 'patrolling' | 'returning' | 'charging'
export type AlertLevel = 'info' | 'warning' | 'critical' | 'success'

export interface Robot {
  id: string
  name: string
  status: RobotStatus
  battery: number
  speed: number
  temperature: number
  connectivity: 'excellent' | 'good' | 'poor'
  mission: MissionStatus
  location: string
}

export interface Site {
  id: string
  name: string
  location: string
  robotCount: number
  cameraCount: number
  status: 'operational' | 'degraded' | 'offline'
}

export interface Incident {
  id: string
  type: string
  zone: string
  description: string
  time: string
  level: AlertLevel
  resolved: boolean
}

export interface SystemLog {
  id: string
  message: string
  time: string
  type: 'info' | 'success' | 'warning' | 'error'
}

export interface NetworkStatus {
  connected: boolean
  ssid: string | null
  ipAddress: string | null
}

export interface WifiNetwork {
  ssid: string
  signal: number
  security: string | null
}

export interface WifiConnectResult {
  success: boolean
  message: string
  newIpAddress: string | null
}
