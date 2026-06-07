import { getRobotApiUrl } from '../lib/robotTransport'
import type { NetworkStatus, WifiNetwork, WifiConnectResult } from '../types'

export async function fetchNetworkStatus(robotIp: string): Promise<NetworkStatus> {
  const res = await fetch(`${getRobotApiUrl(robotIp)}/api/network/status`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() as Promise<NetworkStatus>
}

export async function scanWifi(robotIp: string): Promise<WifiNetwork[]> {
  const res = await fetch(`${getRobotApiUrl(robotIp)}/api/network/wifi/scan`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() as Promise<WifiNetwork[]>
}

export async function connectWifi(
  robotIp: string,
  ssid: string,
  password: string,
): Promise<WifiConnectResult> {
  const res = await fetch(`${getRobotApiUrl(robotIp)}/api/network/wifi/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ssid, password }),
  })
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { message?: string }
    throw new Error(err.message ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<WifiConnectResult>
}
