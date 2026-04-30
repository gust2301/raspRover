import { AlertTriangle } from 'lucide-react'

export default function Incidents() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center space-y-4">
      <div className="w-16 h-16 rounded-2xl bg-red-500/10 border border-red-500/20 flex items-center justify-center mb-2">
        <AlertTriangle size={32} className="text-red-400" />
      </div>
      <h1 className="text-2xl font-bold text-white">Incidents</h1>
      <p className="text-slate-400 max-w-sm">
        Gestion complète des incidents détectés, système de priorités, suivi de résolution et notifications en temps réel.
      </p>
      <span className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full text-xs font-semibold bg-red-500/10 text-red-400 border border-red-500/20">
        Bientôt disponible
      </span>
    </div>
  )
}
