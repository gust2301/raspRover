const HTTP_PORT = 8080
const HTTPS_PORT = 8443

export function getRobotHttpProtocol(): 'http' | 'https' {
  return window.location.protocol === 'https:' ? 'https' : 'http'
}

export function getRobotWsProtocol(): 'ws' | 'wss' {
  return window.location.protocol === 'https:' ? 'wss' : 'ws'
}

export function getRobotPort(): number {
  return window.location.protocol === 'https:' ? HTTPS_PORT : HTTP_PORT
}

export function getRobotStreamUrl(robotIp: string): string {
  return `${getRobotHttpProtocol()}://${robotIp}:${getRobotPort()}/stream`
}

export function getRobotWsUrl(robotIp: string): string {
  return `${getRobotWsProtocol()}://${robotIp}:${getRobotPort()}/ws`
}

export function getRobotTransportWarning(): string | null {
  if (window.location.protocol !== 'https:') {
    return null
  }

  return 'Cette app est ouverte en HTTPS. Le robot doit exposer HTTPS/WSS sur le port 8443, avec un certificat approuve par le telephone.'
}
