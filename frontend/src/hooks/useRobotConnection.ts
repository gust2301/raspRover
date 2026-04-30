import { useCallback, useEffect, useRef, useState } from 'react'

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

export interface RobotStatus {
  battery?: number
  speed_l?: number
  speed_r?: number
  pan?: number
  tilt?: number
  [key: string]: unknown
}

export interface RobotConnection {
  status: ConnectionStatus
  robotIp: string
  setRobotIp: (ip: string) => void
  connect: () => void
  disconnect: () => void
  sendMove: (direction: string, speed: number) => void
  sendStop: () => void
  sendPanTilt: (pan: number, tilt: number) => void
  lastStatus: RobotStatus | null
  latencyMs: number | null
}

const STORAGE_KEY = 'sentryx_robot_ip'
const DEFAULT_IP = '192.168.1.121'
const WS_PORT = 8080

export function useRobotConnection(): RobotConnection {
  const [status, setStatus] = useState<ConnectionStatus>('disconnected')
  const [robotIp, setRobotIpState] = useState<string>(
    () => localStorage.getItem(STORAGE_KEY) ?? DEFAULT_IP
  )
  const [lastStatus, setLastStatus] = useState<RobotStatus | null>(null)
  const [latencyMs, setLatencyMs] = useState<number | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const pingTsRef = useRef<number | null>(null)

  const setRobotIp = useCallback((ip: string) => {
    setRobotIpState(ip)
    localStorage.setItem(STORAGE_KEY, ip)
  }, [])

  const disconnect = useCallback(() => {
    wsRef.current?.close()
    wsRef.current = null
    setStatus('disconnected')
  }, [])

  const connect = useCallback(() => {
    if (wsRef.current) disconnect()
    setStatus('connecting')

    const ws = new WebSocket(`ws://${robotIp}:${WS_PORT}/ws`)
    wsRef.current = ws

    ws.onopen = () => {
      setStatus('connected')
      // Demande un statut initial
      ws.send(JSON.stringify({ type: 'status' }))
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string) as Record<string, unknown>
        if (data.type === 'status') {
          setLastStatus(data as RobotStatus)
          if (pingTsRef.current !== null) {
            setLatencyMs(Date.now() - pingTsRef.current)
            pingTsRef.current = null
          }
        }
      } catch {
        // ignore malformed messages
      }
    }

    ws.onerror = () => setStatus('error')
    ws.onclose = () => {
      setStatus('disconnected')
      wsRef.current = null
    }
  }, [robotIp, disconnect])

  const send = useCallback((payload: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload))
    }
  }, [])

  const sendMove = useCallback((direction: string, speed: number) => {
    send({ type: 'move', direction, speed })
  }, [send])

  const sendStop = useCallback(() => {
    send({ type: 'stop' })
  }, [send])

  const sendPanTilt = useCallback((pan: number, tilt: number) => {
    send({ type: 'pantilt', pan, tilt })
  }, [send])

  // Ping toutes les 3s pour mesurer la latence et récupérer le statut
  useEffect(() => {
    if (status !== 'connected') return
    const id = setInterval(() => {
      pingTsRef.current = Date.now()
      send({ type: 'status' })
    }, 3000)
    return () => clearInterval(id)
  }, [status, send])

  // Cleanup on unmount
  useEffect(() => () => { wsRef.current?.close() }, [])

  return { status, robotIp, setRobotIp, connect, disconnect, sendMove, sendStop, sendPanTilt, lastStatus, latencyMs }
}
