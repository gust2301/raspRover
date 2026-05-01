import { useCallback, useEffect, useRef, useState } from 'react'
import { getRobotTransportWarning, getRobotWsUrl } from '../lib/robotTransport'

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

export interface RobotStatus {
  battery?: number
  speed_l?: number
  speed_r?: number
  pan?: number
  tilt?: number
  camera_light?: boolean
  [key: string]: unknown
}

export interface RobotConnection {
  status: ConnectionStatus
  robotIp: string
  setRobotIp: (ip: string) => void
  connect: () => void
  disconnect: () => void
  sendMove: (direction: string, speed: number) => void
  sendMoveXY: (x: number, y: number) => void
  sendStop: () => void
  sendPanTilt: (pan: number, tilt: number) => void
  sendLight: (enabled: boolean) => void
  sendAlert: (onError?: (err: string) => void) => void
  stopAlert: () => void
  lastStatus: RobotStatus | null
  latencyMs: number | null
  errorMessage: string | null
}

const STORAGE_KEY = 'sentryx_robot_ip'
const DEFAULT_IP = 'https://rover.sopikeur.sn'

export function useRobotConnection(): RobotConnection {
  const [status, setStatus] = useState<ConnectionStatus>('disconnected')
  const [robotIp, setRobotIpState] = useState<string>(
    () => localStorage.getItem(STORAGE_KEY) ?? DEFAULT_IP
  )
  const [lastStatus, setLastStatus] = useState<RobotStatus | null>(null)
  const [latencyMs, setLatencyMs] = useState<number | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const pingTsRef = useRef<number | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectAttemptRef = useRef(0)
  const shouldStayConnectedRef = useRef(false)
  const onAlertErrorRef = useRef<((err: string) => void) | null>(null)

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
  }, [])

  const setRobotIp = useCallback((ip: string) => {
    setRobotIpState(ip)
    localStorage.setItem(STORAGE_KEY, ip)
  }, [])

  const disconnect = useCallback(() => {
    shouldStayConnectedRef.current = false
    clearReconnectTimer()
    pingTsRef.current = null
    reconnectAttemptRef.current = 0
    wsRef.current?.close()
    wsRef.current = null
    setStatus('disconnected')
    setErrorMessage(null)
  }, [clearReconnectTimer])

  const connect = useCallback(() => {
    shouldStayConnectedRef.current = true
    clearReconnectTimer()
    pingTsRef.current = null
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setStatus('connecting')
    setErrorMessage(getRobotTransportWarning(robotIp))

    const ws = new WebSocket(getRobotWsUrl(robotIp))
    wsRef.current = ws

    ws.onopen = () => {
      if (wsRef.current !== ws) return
      reconnectAttemptRef.current = 0
      setStatus('connected')
      setErrorMessage(null)
      // Demande un statut initial
      ws.send(JSON.stringify({ type: 'status' }))
    }

    ws.onmessage = (event) => {
      if (wsRef.current !== ws) return
      try {
        const data = JSON.parse(event.data as string) as Record<string, unknown>
        if (data.type === 'status') {
          setLastStatus(data as RobotStatus)
          if (pingTsRef.current !== null) {
            setLatencyMs(Date.now() - pingTsRef.current)
            pingTsRef.current = null
          }
        } else if (data.type === 'alert_ack') {
          if (!data.ok && data.error) {
            console.warn('[SENTRYX] Audio error:', data.error)
            onAlertErrorRef.current?.(data.error as string)
          }
        }
      } catch {
        // ignore malformed messages
      }
    }

    ws.onerror = () => {
      if (wsRef.current !== ws) return
      setStatus('error')
      setErrorMessage(
        getRobotTransportWarning(robotIp) ?? 'Connexion WebSocket au robot impossible.'
      )
    }

    ws.onclose = () => {
      if (wsRef.current !== ws && wsRef.current !== null) return

      if (wsRef.current === ws) {
        wsRef.current = null
      }
      pingTsRef.current = null

      if (!shouldStayConnectedRef.current) {
        setStatus('disconnected')
        return
      }

      setStatus('connecting')
      setErrorMessage(
        getRobotTransportWarning(robotIp) ?? 'Connexion perdue, reconnexion automatique...'
      )

      const attempt = reconnectAttemptRef.current + 1
      reconnectAttemptRef.current = attempt
      const delayMs = Math.min(1000 * 2 ** Math.min(attempt - 1, 3), 8000)
      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null
        if (shouldStayConnectedRef.current) {
          connect()
        }
      }, delayMs)
    }
  }, [clearReconnectTimer, robotIp])

  const send = useCallback((payload: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload))
    }
  }, [])

  const sendMove = useCallback((direction: string, speed: number) => {
    send({ type: 'move', direction, speed })
  }, [send])

  const sendMoveXY = useCallback((x: number, y: number) => {
    send({ type: 'move', x, y })
  }, [send])

  const sendStop = useCallback(() => {
    send({ type: 'stop' })
  }, [send])

  const sendPanTilt = useCallback((pan: number, tilt: number) => {
    send({ type: 'pantilt', pan, tilt })
  }, [send])

  const sendLight = useCallback((enabled: boolean) => {
    send({ type: 'light', enabled })
  }, [send])

  const sendAlert = useCallback((onError?: (err: string) => void) => {
    onAlertErrorRef.current = onError ?? null
    const wsReady = wsRef.current?.readyState === WebSocket.OPEN
    if (!wsReady) {
      onError?.('WebSocket non connecté — reconnecte-toi au robot')
      return
    }
    send({ type: 'alert', action: 'play' })
  }, [send])

  const stopAlert = useCallback(() => {
    send({ type: 'alert', action: 'stop' })
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
  useEffect(() => () => {
    shouldStayConnectedRef.current = false
    clearReconnectTimer()
    wsRef.current?.close()
  }, [clearReconnectTimer])

  return {
    status,
    robotIp,
    setRobotIp,
    connect,
    disconnect,
    sendMove,
    sendMoveXY,
    sendStop,
    sendPanTilt,
    sendLight,
    sendAlert,
    stopAlert,
    lastStatus,
    latencyMs,
    errorMessage,
  }
}
