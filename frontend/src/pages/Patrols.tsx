import { Route } from 'lucide-react'

export default function Patrols() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center space-y-4">
      <div className="w-16 h-16 rounded-2xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center mb-2">
        <Route size={32} className="text-amber-400" />
      </div>
      <h1 className="text-2xl font-bold text-white">Patrouilles</h1>
      <p className="text-slate-400 max-w-sm">
        Planification et suivi des itinéraires de patrouille, historique des rondes effectuées et programmation des missions automatiques.
      </p>
      <span className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
        Bientôt disponible
      </span>
    </div>
  )
}
