import { FileText } from 'lucide-react'

export default function Reports() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center space-y-4">
      <div className="w-16 h-16 rounded-2xl bg-slate-500/10 border border-slate-500/20 flex items-center justify-center mb-2">
        <FileText size={32} className="text-slate-400" />
      </div>
      <h1 className="text-2xl font-bold text-white">Rapports</h1>
      <p className="text-slate-400 max-w-sm">
        Génération de rapports d'activité, statistiques de surveillance, exports PDF et tableaux de bord analytiques.
      </p>
      <span className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full text-xs font-semibold bg-slate-500/10 text-slate-400 border border-slate-500/20">
        Bientôt disponible
      </span>
    </div>
  )
}
