import { useEffect, useState } from 'react'
import { Camera, Trash2, Download, RefreshCw, Loader2, AlertCircle } from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { ConnectionBar } from '../components/ConnectionBar'
import { useMedia, type MediaItem } from '../hooks/useMedia'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatTimestamp(key: string): string {
  const ts = key.replace(/^.*\//, '').replace(/^(photo|video)_/, '').replace(/\.(jpg|mp4|h264)$/, '')
  return ts.replace('T', ' ').replace(/-(\d{2})-(\d{2})$/, ':$1:$2')
}

// ---------------------------------------------------------------------------
// Vignette média
// ---------------------------------------------------------------------------

function MediaCard({ item, onDelete }: { item: MediaItem; onDelete: (key: string) => void }) {
  const [confirmDelete, setConfirmDelete] = useState(false)

  return (
    <div className="relative rounded-xl border border-slate-800 overflow-hidden bg-slate-900/50">
      {item.type === 'photo' ? (
        <a href={item.url} target="_blank" rel="noopener noreferrer">
          <img
            src={item.url}
            alt={item.key}
            className="w-full aspect-video object-cover bg-slate-950"
            loading="lazy"
          />
        </a>
      ) : (
        <video src={item.url} controls className="w-full aspect-video bg-slate-950" preload="metadata" />
      )}

      <div className="px-3 py-2 flex items-center gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-xs text-slate-400 font-mono truncate">{formatTimestamp(item.key)}</p>
          <p className="text-xs text-slate-600">{formatBytes(item.size)}</p>
        </div>
        <a
          href={item.url}
          download={item.key.replace(/^.*\//, '')}
          className="p-1.5 rounded-lg text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          title="Télécharger"
        >
          <Download size={13} />
        </a>
        {confirmDelete ? (
          <div className="flex items-center gap-1">
            <button
              onClick={() => onDelete(item.key)}
              className="px-2 py-1 rounded text-xs text-red-400 hover:bg-red-500/10 border border-red-500/30 transition-colors"
            >
              Confirmer
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              className="px-2 py-1 rounded text-xs text-slate-400 hover:bg-slate-800 transition-colors"
            >
              ✕
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirmDelete(true)}
            className="p-1.5 rounded-lg text-slate-600 hover:text-red-400 hover:bg-red-500/10 transition-colors"
            title="Supprimer"
          >
            <Trash2 size={13} />
          </button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page galerie
// ---------------------------------------------------------------------------

export default function Cameras() {
  const conn = useSharedRobotConnection()
  const media = useMedia(conn.robotIp)
  const connected = conn.status === 'connected'

  useEffect(() => {
    if (connected) media.fetchMedia()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, conn.robotIp])

  const photos = media.items.filter(i => i.type === 'photo')
  const videos = media.items.filter(i => i.type === 'video')

  return (
    <div className="flex flex-col min-h-screen" style={{ background: '#070d1a' }}>
      <ConnectionBar
        status={conn.status}
        robotIp={conn.robotIp}
        setRobotIp={conn.setRobotIp}
        connect={conn.connect}
        disconnect={conn.disconnect}
        latencyMs={conn.latencyMs}
        errorMessage={conn.errorMessage}
      />

      <div className="flex-1 p-4 sm:p-6 max-w-7xl mx-auto w-full">
        <div className="rounded-xl border border-slate-800 overflow-hidden" style={{ background: '#0f1629' }}>
          <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
            <div className="flex items-center gap-2">
              <Camera size={16} className="text-emerald-400" />
              <h1 className="text-white font-semibold text-sm">Galerie</h1>
              {media.items.length > 0 && (
                <span className="text-xs text-slate-500 font-mono">
                  {photos.length} photo{photos.length !== 1 ? 's' : ''} · {videos.length} vidéo{videos.length !== 1 ? 's' : ''}
                </span>
              )}
            </div>
            <button
              onClick={media.fetchMedia}
              disabled={media.isLoading || !connected}
              className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-40 transition-colors px-2 py-1 rounded-lg hover:bg-slate-800"
            >
              <RefreshCw size={12} className={media.isLoading ? 'animate-spin' : ''} />
              Actualiser
            </button>
          </div>

          <div className="p-5">
            {media.error && (
              <div className="flex items-start gap-2 text-xs text-red-300 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 mb-4">
                <AlertCircle size={13} className="flex-shrink-0 mt-0.5" />
                <span>{media.error}</span>
              </div>
            )}

            {!connected && (
              <p className="text-center text-slate-600 text-sm py-12">
                Connectez-vous au robot pour accéder à la galerie.
              </p>
            )}

            {connected && media.isLoading && media.items.length === 0 && (
              <div className="flex justify-center py-12">
                <Loader2 size={24} className="text-slate-600 animate-spin" />
              </div>
            )}

            {connected && !media.isLoading && media.items.length === 0 && !media.error && (
              <div className="text-center py-12 space-y-2">
                <Camera size={32} className="mx-auto text-slate-700" />
                <p className="text-slate-600 text-sm">Aucun média. Prenez des photos ou vidéos depuis les pages Pilotage ou Patrouille.</p>
              </div>
            )}

            {media.items.length > 0 && (
              <div className="space-y-8">
                {photos.length > 0 && (
                  <div>
                    <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">
                      Photos ({photos.length})
                    </h2>
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
                      {photos.map(item => (
                        <MediaCard key={item.key} item={item} onDelete={media.deleteItem} />
                      ))}
                    </div>
                  </div>
                )}

                {videos.length > 0 && (
                  <div>
                    <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">
                      Vidéos ({videos.length})
                    </h2>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                      {videos.map(item => (
                        <MediaCard key={item.key} item={item} onDelete={media.deleteItem} />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
