import { useEffect, useState, useMemo } from 'react'
import {
  Camera, Trash2, Download, RefreshCw, Loader2,
  AlertCircle, Video, Image, X,
} from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { useMedia, type MediaItem } from '../hooks/useMedia'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function extractDate(key: string): string {
  // "rasprover/2026-05-07/photos/photo_xxx.jpg" → "2026-05-07"
  return key.split('/')[1] ?? ''
}

function formatTimestamp(key: string): string {
  const name = key.replace(/^.*\//, '')
  const ts   = name.replace(/^(photo|video|auto|human)_/, '').replace(/\.(jpg|mp4|h264)$/, '')
  return ts.replace('T', ' ').replace(/-(\d{2})-(\d{2})$/, ':$1:$2')
}

function todayStr(): string {
  return new Date().toISOString().slice(0, 10)
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
// Types
// ---------------------------------------------------------------------------

type TypeFilter = 'all' | 'photo' | 'video'

const TYPE_OPTIONS: { value: TypeFilter; label: string; icon: React.ReactNode }[] = [
  { value: 'all',   label: 'Tous',    icon: null },
  { value: 'photo', label: 'Photos',  icon: <Image size={11} /> },
  { value: 'video', label: 'Vidéos',  icon: <Video size={11} /> },
]

// ---------------------------------------------------------------------------
// Page galerie
// ---------------------------------------------------------------------------

export default function Cameras() {
  const conn      = useSharedRobotConnection()
  const media     = useMedia(conn.robotIp)
  const connected = conn.status === 'connected'

  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [dateFrom, setDateFrom]     = useState<string>('')
  const [dateTo, setDateTo]         = useState<string>('')

  useEffect(() => {
    if (connected) media.fetchMedia()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, conn.robotIp])

  // ── Items filtrés ──────────────────────────────────────────────────────────
  const filtered = useMemo(() => {
    let result = media.items
    if (typeFilter !== 'all') result = result.filter(i => i.type === typeFilter)
    if (dateFrom) result = result.filter(i => extractDate(i.key) >= dateFrom)
    if (dateTo)   result = result.filter(i => extractDate(i.key) <= dateTo)
    return result
  }, [media.items, typeFilter, dateFrom, dateTo])

  const photos = filtered.filter(i => i.type === 'photo')
  const videos = filtered.filter(i => i.type === 'video')

  const totalPhotos = media.items.filter(i => i.type === 'photo').length
  const totalVideos = media.items.filter(i => i.type === 'video').length

  const hasDateFilter = dateFrom !== '' || dateTo !== ''

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="max-w-7xl mx-auto w-full">
      <div className="rounded-xl border border-slate-800 overflow-hidden" style={{ background: '#0f1629' }}>

        {/* ── Barre titre ──────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <Camera size={16} className="text-emerald-400" />
            <h1 className="text-white font-semibold text-sm">Galerie</h1>
            {media.items.length > 0 && (
              <span className="text-xs text-slate-500 font-mono">
                {totalPhotos} photo{totalPhotos !== 1 ? 's' : ''} · {totalVideos} vidéo{totalVideos !== 1 ? 's' : ''}
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

        {/* ── Filtres (visibles seulement si des items existent) ───────────── */}
        {media.items.length > 0 && (
          <div className="px-4 py-3 border-b border-slate-800 space-y-2.5">

            {/* Type */}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-slate-500 w-14 flex-shrink-0">Type</span>
              <div className="flex gap-1">
                {TYPE_OPTIONS.map(o => {
                  const count = o.value === 'all' ? media.items.length
                    : o.value === 'photo' ? totalPhotos : totalVideos
                  return (
                    <button
                      key={o.value}
                      onClick={() => setTypeFilter(o.value)}
                      className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                        typeFilter === o.value
                          ? 'bg-slate-600 text-white'
                          : 'bg-slate-800 text-slate-400 hover:text-slate-200 hover:bg-slate-700'
                      }`}
                    >
                      {o.icon}
                      {o.label} ({count})
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Date range */}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-slate-500 w-14 flex-shrink-0">Date</span>
              <div className="flex items-center gap-1.5">
                <input
                  type="date"
                  value={dateFrom}
                  max={dateTo || todayStr()}
                  onChange={e => setDateFrom(e.target.value)}
                  className="bg-slate-800 border border-slate-700 text-slate-300 text-xs px-2 py-1 rounded-lg focus:outline-none focus:border-slate-500 transition-colors"
                  style={{ colorScheme: 'dark' }}
                  placeholder="Du"
                />
                <span className="text-slate-600 text-xs">→</span>
                <input
                  type="date"
                  value={dateTo}
                  min={dateFrom || undefined}
                  max={todayStr()}
                  onChange={e => setDateTo(e.target.value)}
                  className="bg-slate-800 border border-slate-700 text-slate-300 text-xs px-2 py-1 rounded-lg focus:outline-none focus:border-slate-500 transition-colors"
                  style={{ colorScheme: 'dark' }}
                  placeholder="Au"
                />
                {hasDateFilter && (
                  <button
                    onClick={() => { setDateFrom(''); setDateTo('') }}
                    className="text-slate-500 hover:text-slate-300 transition-colors"
                    title="Effacer les dates"
                  >
                    <X size={13} />
                  </button>
                )}
              </div>
            </div>

            {/* Résumé de la sélection active */}
            {(hasDateFilter || typeFilter !== 'all') && (
              <p className="text-xs text-slate-500">
                {filtered.length} résultat{filtered.length !== 1 ? 's' : ''}
                {typeFilter !== 'all' && <> · <span className="text-slate-300">{typeFilter === 'photo' ? 'photos' : 'vidéos'}</span></>}
              </p>
            )}
          </div>
        )}

        {/* ── Contenu ──────────────────────────────────────────────────────── */}
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

          {connected && media.items.length > 0 && filtered.length === 0 && (
            <div className="text-center py-12 space-y-2">
              <Camera size={32} className="mx-auto text-slate-700" />
              <p className="text-slate-600 text-sm">Aucun média pour cette sélection.</p>
              <button
                onClick={() => { setTypeFilter('all'); setDateFrom(''); setDateTo('') }}
                className="text-xs text-slate-500 hover:text-slate-300 underline transition-colors"
              >
                Réinitialiser les filtres
              </button>
            </div>
          )}

          {filtered.length > 0 && (
            <div className="space-y-8">
              {/* Photos */}
              {(typeFilter === 'all' || typeFilter === 'photo') && photos.length > 0 && (
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

              {/* Vidéos */}
              {(typeFilter === 'all' || typeFilter === 'video') && videos.length > 0 && (
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
  )
}
