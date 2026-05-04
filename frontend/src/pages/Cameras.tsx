import { useEffect, useState } from 'react'
import {
  Camera, CameraOff, Circle, Video, VideoOff, Trash2, Download,
  RefreshCw, Image, AlertCircle, Loader2,
} from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { getRobotStreamUrl } from '../lib/robotTransport'
import { ConnectionBar } from '../components/ConnectionBar'
import { useMedia, type MediaItem } from '../hooks/useMedia'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatTimestamp(ts: string): string {
  return ts.replace('T', ' ').replace(/-(\d{2})-(\d{2})$/, ':$1:$2')
}

// ---------------------------------------------------------------------------
// Vignette média (photo ou vidéo)
// ---------------------------------------------------------------------------

function MediaCard({
  item, onDelete,
}: {
  item: MediaItem
  onDelete: (key: string) => void
}) {
  const [confirmDelete, setConfirmDelete] = useState(false)

  return (
    <div className="relative rounded-xl border border-slate-800 overflow-hidden group bg-slate-900/50">
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
        <video
          src={item.url}
          controls
          className="w-full aspect-video bg-slate-950"
          preload="metadata"
        />
      )}

      <div className="px-3 py-2 flex items-center gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-xs text-slate-400 font-mono truncate">
            {formatTimestamp(item.key.replace(/^(photo|video)_/, '').replace(/\.(jpg|mp4|h264)$/, ''))}
          </p>
          <p className="text-xs text-slate-600">{formatBytes(item.size)}</p>
        </div>
        <a
          href={item.url}
          download={item.key}
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
// Page principale
// ---------------------------------------------------------------------------

export default function Cameras() {
  const conn = useSharedRobotConnection()
  const [streamUnavailable, setStreamUnavailable] = useState(false)
  const [photoLoading, setPhotoLoading] = useState(false)
  const [videoLoading, setVideoLoading] = useState(false)
  const streamUrl = getRobotStreamUrl(conn.robotIp)
  const media = useMedia(conn.robotIp)
  const connected = conn.status === 'connected'

  useEffect(() => {
    if (connected) media.fetchMedia()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, conn.robotIp])

  useEffect(() => {
    setStreamUnavailable(false)
  }, [conn.robotIp, conn.status])

  const handlePhoto = async () => {
    setPhotoLoading(true)
    await media.takePhoto()
    setPhotoLoading(false)
  }

  const handleVideoToggle = async () => {
    setVideoLoading(true)
    if (media.isRecording) {
      await media.stopRecording()
    } else {
      await media.startRecording()
    }
    setVideoLoading(false)
  }

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

      <div className="flex-1 p-4 sm:p-6 space-y-6 max-w-7xl mx-auto w-full">

        {/* Flux + contrôles */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

          {/* Stream */}
          <div className="lg:col-span-2 rounded-xl border border-slate-800 overflow-hidden" style={{ background: '#0f1629' }}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
              <h2 className="text-white font-semibold text-sm">Flux vidéo en direct</h2>
              <div className="flex items-center gap-1.5">
                <div className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-500 animate-pulse' : 'bg-slate-600'}`} />
                <span className={`text-xs font-medium ${connected ? 'text-emerald-400' : 'text-slate-500'}`}>
                  {connected ? 'En direct' : 'Hors ligne'}
                </span>
              </div>
            </div>

            <div className="relative aspect-video bg-slate-950">
              {connected && !streamUnavailable && (
                <img
                  key={streamUrl}
                  src={streamUrl}
                  alt="Camera feed"
                  className="absolute inset-0 w-full h-full object-contain z-10"
                  onLoad={() => setStreamUnavailable(false)}
                  onError={() => setStreamUnavailable(true)}
                />
              )}

              {(!connected || streamUnavailable) && (
                <div className="absolute inset-0 flex items-center justify-center text-slate-700">
                  {streamUnavailable
                    ? <CameraOff size={48} className="opacity-40" />
                    : <Camera size={48} className="opacity-30" />
                  }
                </div>
              )}

              {media.isRecording && (
                <div className="absolute top-3 left-3 flex items-center gap-1.5 bg-black/60 backdrop-blur-sm rounded px-2 py-1 z-20">
                  <Circle size={8} className="text-red-500 fill-red-500 animate-pulse" />
                  <span className="text-white text-xs font-bold">REC</span>
                </div>
              )}
            </div>
          </div>

          {/* Contrôles capture */}
          <div className="rounded-xl border border-slate-800 p-5 space-y-4 flex flex-col" style={{ background: '#0f1629' }}>
            <h2 className="text-white font-semibold text-sm">Capture</h2>

            <button
              onClick={handlePhoto}
              disabled={!connected || photoLoading || media.isRecording}
              className="flex items-center justify-center gap-2.5 w-full px-4 py-3 rounded-xl text-sm font-medium
                bg-blue-600/15 text-blue-300 border border-blue-500/30
                hover:bg-blue-600/25 hover:border-blue-400/50
                disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              {photoLoading
                ? <Loader2 size={16} className="animate-spin" />
                : <Image size={16} />
              }
              Prendre une photo
            </button>

            <button
              onClick={handleVideoToggle}
              disabled={!connected || videoLoading}
              className={`flex items-center justify-center gap-2.5 w-full px-4 py-3 rounded-xl text-sm font-medium
                border transition-all disabled:opacity-40 disabled:cursor-not-allowed
                ${media.isRecording
                  ? 'bg-red-600/20 text-red-300 border-red-500/40 hover:bg-red-600/30 hover:border-red-400/60'
                  : 'bg-emerald-600/15 text-emerald-300 border-emerald-500/30 hover:bg-emerald-600/25 hover:border-emerald-400/50'
                }`}
            >
              {videoLoading
                ? <Loader2 size={16} className="animate-spin" />
                : media.isRecording
                  ? <VideoOff size={16} />
                  : <Video size={16} />
              }
              {media.isRecording ? 'Arrêter l\'enregistrement' : 'Démarrer l\'enregistrement'}
            </button>

            {media.error && (
              <div className="flex items-start gap-2 text-xs text-red-300 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
                <AlertCircle size={13} className="flex-shrink-0 mt-0.5" />
                <span>{media.error}</span>
              </div>
            )}

            <div className="mt-auto pt-2 border-t border-slate-800 space-y-1 text-xs text-slate-500">
              <p>Photos : <span className="text-slate-300 font-mono">{photos.length}</span></p>
              <p>Vidéos : <span className="text-slate-300 font-mono">{videos.length}</span></p>
            </div>
          </div>
        </div>

        {/* Galerie */}
        <div className="rounded-xl border border-slate-800 overflow-hidden" style={{ background: '#0f1629' }}>
          <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
            <h2 className="text-white font-semibold text-sm">Galerie</h2>
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
            {!connected && (
              <p className="text-center text-slate-600 text-sm py-8">
                Connectez-vous au robot pour accéder à la galerie.
              </p>
            )}

            {connected && media.isLoading && media.items.length === 0 && (
              <div className="flex justify-center py-8">
                <Loader2 size={24} className="text-slate-600 animate-spin" />
              </div>
            )}

            {connected && !media.isLoading && media.items.length === 0 && (
              <div className="text-center py-8 space-y-2">
                <Camera size={32} className="mx-auto text-slate-700" />
                <p className="text-slate-600 text-sm">Aucun média. Prenez votre première photo !</p>
              </div>
            )}

            {media.items.length > 0 && (
              <div className="space-y-6">
                {photos.length > 0 && (
                  <div>
                    <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">
                      Photos ({photos.length})
                    </h3>
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
                      {photos.map(item => (
                        <MediaCard key={item.key} item={item} onDelete={media.deleteItem} />
                      ))}
                    </div>
                  </div>
                )}

                {videos.length > 0 && (
                  <div>
                    <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">
                      Vidéos ({videos.length})
                    </h3>
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
