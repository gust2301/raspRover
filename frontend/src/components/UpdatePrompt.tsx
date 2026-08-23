import { useSwUpdate } from '../hooks/useSwUpdate'

export default function UpdatePrompt() {
  const { updateAvailable, applyUpdate } = useSwUpdate()

  if (!updateAvailable) return null

  return (
    <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 rounded-xl border border-blue-200 dark:border-blue-500/40 bg-white/95 dark:bg-[#0d1526]/90 px-4 py-3 shadow-xl backdrop-blur-sm">
      <span className="text-sm text-slate-700 dark:text-slate-200">Nouvelle version disponible</span>
      <button
        onClick={applyUpdate}
        className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-500 active:scale-95 transition-all"
      >
        Mettre à jour
      </button>
    </div>
  )
}
