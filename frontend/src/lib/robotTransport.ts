const DEFAULT_PORT = 8080

function isFullUrl(input: string): boolean {
  return input.startsWith('http://') || input.startsWith('https://')
}

function parseRobotUrl(robotIp: string): { httpBase: string; wsBase: string } {
  if (isFullUrl(robotIp)) {
    const url = new URL(robotIp)
    const wsProto = url.protocol === 'https:' ? 'wss:' : 'ws:'
    return {
      httpBase: robotIp.replace(/\/$/, ''),
      wsBase: `${wsProto}//${url.host}`,
    }
  }
  return {
    httpBase: `http://${robotIp}:${DEFAULT_PORT}`,
    wsBase: `ws://${robotIp}:${DEFAULT_PORT}`,
  }
}

export function getRobotStreamUrl(robotIp: string): string {
  return `${parseRobotUrl(robotIp).httpBase}/stream`
}

export function getRobotWsUrl(robotIp: string): string {
  return `${parseRobotUrl(robotIp).wsBase}/ws`
}

export function getRobotTransportWarning(robotIp: string = ''): string | null {
  if (window.location.protocol !== 'https:') return null
  if (isFullUrl(robotIp) && robotIp.startsWith('https://')) return null
  return "App ouverte en HTTPS : entre une URL de tunnel (ex: https://xxx.trycloudflare.com) à la place de l'IP."
}
