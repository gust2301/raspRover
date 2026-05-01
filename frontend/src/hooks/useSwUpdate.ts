import { useEffect, useState } from 'react'

export function useSwUpdate() {
  const [waitingWorker, setWaitingWorker] = useState<ServiceWorker | null>(null)

  useEffect(() => {
    if (!('serviceWorker' in navigator)) return

    navigator.serviceWorker.getRegistration().then((reg) => {
      if (!reg) return

      if (reg.waiting) {
        setWaitingWorker(reg.waiting)
        return
      }

      reg.addEventListener('updatefound', () => {
        const newWorker = reg.installing
        if (!newWorker) return
        newWorker.addEventListener('statechange', () => {
          if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
            setWaitingWorker(newWorker)
          }
        })
      })
    })
  }, [])

  const applyUpdate = () => {
    if (!waitingWorker) return
    waitingWorker.postMessage('SKIP_WAITING')
    waitingWorker.addEventListener('statechange', () => {
      if (waitingWorker.state === 'activated') {
        window.location.reload()
      }
    })
    setWaitingWorker(null)
  }

  return { updateAvailable: waitingWorker !== null, applyUpdate }
}
