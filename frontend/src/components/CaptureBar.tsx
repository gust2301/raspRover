import { useState } from 'react'
import { Image, Video, VideoOff, Loader2, Circle, AlertCircle } from 'lucide-react'
import { useMedia } from '../hooks/useMedia'

export function CaptureBar({ robotIp, connected }: { robotIp: string; connected: boolean }) {
  const media = useMedia(robotIp)
  const [photoLoading, setPhotoLoading] = useState(false)
  const [videoLoading, setVideoLoading] = useState(false)

  const handlePhoto = async () => {
    setPhotoLoading(true)
    await media.takePhoto()
    setPhotoLoading(false)
  }

  const handleVideo = async () => {
    setVideoLoading(true)
    if (media.isRecording) {
      await media.stopRecording()
    } else {
      await media.startRecording()
    }
    setVideoLoading(false)
  }

  return (
    <div className="px-5 py-4 border-b border-slate-800 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wide">Capture</span>
        {media.isRecording && (
          <div className="flex items-center gap-1.5">
            <Circle size={7} className="text-red-500 fill-red-500 animate-pulse" />
            <span className="text-xs text-red-400 font-bold">REC</span>
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <button
          onClick={handlePhoto}
          disabled={!connected || photoLoading || media.isRecording}
          className="flex items-center justify-center gap-1.5 py-2.5 rounded-xl text-xs font-medium
            bg-blue-600/15 text-blue-300 border border-blue-500/30
            hover:bg-blue-600/25 hover:border-blue-400/50
            disabled:opacity-40 disabled:cursor-not-allowed transition-all"
        >
          {photoLoading ? <Loader2 size={13} className="animate-spin" /> : <Image size={13} />}
          Photo
        </button>

        <button
          onClick={handleVideo}
          disabled={!connected || videoLoading}
          className={`flex items-center justify-center gap-1.5 py-2.5 rounded-xl text-xs font-medium
            border transition-all disabled:opacity-40 disabled:cursor-not-allowed
            ${media.isRecording
              ? 'bg-red-600/20 text-red-300 border-red-500/40 hover:bg-red-600/30'
              : 'bg-emerald-600/15 text-emerald-300 border-emerald-500/30 hover:bg-emerald-600/25'
            }`}
        >
          {videoLoading
            ? <Loader2 size={13} className="animate-spin" />
            : media.isRecording
              ? <VideoOff size={13} />
              : <Video size={13} />
          }
          {media.isRecording ? 'Stop' : 'Vidéo'}
        </button>
      </div>

      {media.error && (
        <div className="flex items-start gap-1.5 text-xs text-red-300 bg-red-500/10 border border-red-500/20 rounded-lg px-2.5 py-1.5">
          <AlertCircle size={11} className="flex-shrink-0 mt-0.5" />
          <span>{media.error}</span>
        </div>
      )}
    </div>
  )
}
