import { useState, useCallback } from 'react'
import { getRobotApiUrl } from '../lib/robotTransport'

export interface MediaItem {
  key: string
  url: string
  type: 'photo' | 'video'
  size: number
  timestamp: string
}

export interface UseMediaReturn {
  items: MediaItem[]
  isRecording: boolean
  isLoading: boolean
  error: string | null
  fetchMedia: () => Promise<void>
  takePhoto: () => Promise<void>
  startRecording: () => Promise<void>
  stopRecording: () => Promise<void>
  deleteItem: (key: string) => Promise<void>
}

export function useMedia(robotIp: string): UseMediaReturn {
  const [items, setItems] = useState<MediaItem[]>([])
  const [isRecording, setIsRecording] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const baseUrl = getRobotApiUrl(robotIp)

  const fetchMedia = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await fetch(`${baseUrl}/api/media`)
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error((body as { error?: string }).error ?? `HTTP ${res.status}`)
      }
      setItems(await res.json() as MediaItem[])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur réseau')
    } finally {
      setIsLoading(false)
    }
  }, [baseUrl])

  const takePhoto = useCallback(async () => {
    setError(null)
    try {
      const res = await fetch(`${baseUrl}/api/photo`, { method: 'POST' })
      const data = await res.json() as { ok: boolean; error?: string }
      if (!res.ok || !data.ok) throw new Error(data.error ?? `HTTP ${res.status}`)
      await fetchMedia()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur capture photo')
    }
  }, [baseUrl, fetchMedia])

  const startRecording = useCallback(async () => {
    setError(null)
    try {
      const res = await fetch(`${baseUrl}/api/video/start`, { method: 'POST' })
      const data = await res.json() as { ok: boolean; error?: string }
      if (!res.ok || !data.ok) throw new Error(data.error ?? `HTTP ${res.status}`)
      setIsRecording(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur démarrage enregistrement')
    }
  }, [baseUrl])

  const stopRecording = useCallback(async () => {
    setError(null)
    try {
      const res = await fetch(`${baseUrl}/api/video/stop`, { method: 'POST' })
      const data = await res.json() as { ok: boolean; error?: string }
      if (!res.ok || !data.ok) throw new Error(data.error ?? `HTTP ${res.status}`)
      setIsRecording(false)
      await fetchMedia()
    } catch (e) {
      setIsRecording(false)
      setError(e instanceof Error ? e.message : 'Erreur arrêt enregistrement')
    }
  }, [baseUrl, fetchMedia])

  const deleteItem = useCallback(async (key: string) => {
    setError(null)
    try {
      const encoded = key.split('/').map(encodeURIComponent).join('/')
      const res = await fetch(`${baseUrl}/api/media/${encoded}`, { method: 'DELETE' })
      const data = await res.json() as { ok: boolean; error?: string }
      if (!res.ok || !data.ok) throw new Error(data.error ?? `HTTP ${res.status}`)
      setItems(prev => prev.filter(item => item.key !== key))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur suppression')
    }
  }, [baseUrl])

  return {
    items,
    isRecording,
    isLoading,
    error,
    fetchMedia,
    takePhoto,
    startRecording,
    stopRecording,
    deleteItem,
  }
}
