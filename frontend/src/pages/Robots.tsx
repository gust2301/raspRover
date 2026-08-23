import { Bot } from 'lucide-react'

export default function Robots() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center space-y-4">
      <div className="w-16 h-16 rounded-2xl bg-blue-50 border border-blue-200 dark:bg-blue-500/10 dark:border-blue-500/20 flex items-center justify-center mb-2">
        <Bot size={32} className="text-blue-600 dark:text-blue-400" />
      </div>
      <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Robots</h1>
      <p className="text-slate-500 dark:text-slate-400 max-w-sm">
        Vue d'ensemble de la flotte robotique, diagnostics en temps réel, mises à jour firmware et gestion de la recharge.
      </p>
      <span className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200 dark:bg-blue-500/10 dark:text-blue-400 dark:border-blue-500/20">
        Bientôt disponible
      </span>
    </div>
  )
}
