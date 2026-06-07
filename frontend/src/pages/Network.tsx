import { useState, useCallback } from 'react'
import {
  Wifi, WifiOff, RefreshCw, Search, Lock, Unlock, Eye, EyeOff,
  AlertTriangle, CheckCircle, XCircle, Signal,
} from 'lucide-react'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'
import { fetchNetworkStatus, scanWifi, connectWifi } from '../services/networkApi'
import type { NetworkStatus, WifiNetwork, WifiConnectResult } from '../types'

function SignalBars({ signal }: { signal: number }) {
  const bars = [25, 50, 75, 100]
  return (
    <span className="flex items-end gap-0.5 h-4">
      {bars.map((threshold, i) => (
        <span
          key={i}
          className={`w-1 rounded-sm ${signal >= threshold ? 'bg-emerald-400' : 'bg-slate-700'}`}
          style={{ height: `${(i + 1) * 4}px` }}
        />
      ))}
    </span>
  )
}

function SecurityBadge({ security }: { security: string | null }) {
  const secured = security && security !== '--' && security !== 'none'
  return (
    <span className={`flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded font-medium ${
      secured ? 'bg-amber-500/15 text-amber-300 border border-amber-500/20' : 'bg-slate-800 text-slate-500 border border-slate-700'
    }`}>
      {secured ? <Lock size={9} /> : <Unlock size={9} />}
      {secured ? (security ?? 'Secured') : 'Ouvert'}
    </span>
  )
}

export default function Network() {
  const conn = useSharedRobotConnection()
  const robotIp = conn.robotIp

  const [status, setStatus] = useState<NetworkStatus | null>(null)
  const [statusLoading, setStatusLoading] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)

  const [networks, setNetworks] = useState<WifiNetwork[]>([])
  const [scanLoading, setScanLoading] = useState(false)
  const [scanError, setScanError] = useState<string | null>(null)
  const [scanned, setScanned] = useState(false)

  const [selected, setSelected] = useState<WifiNetwork | null>(null)
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [confirming, setConfirming] = useState(false)

  const [connectLoading, setConnectLoading] = useState(false)
  const [connectResult, setConnectResult] = useState<WifiConnectResult | null>(null)
  const [connectError, setConnectError] = useState<string | null>(null)

  const refreshStatus = useCallback(async () => {
    setStatusLoading(true)
    setStatusError(null)
    try {
      const s = await fetchNetworkStatus(robotIp)
      setStatus(s)
    } catch {
      setStatusError('Impossible de récupérer le statut réseau.')
    } finally {
      setStatusLoading(false)
    }
  }, [robotIp])

  const handleScan = async () => {
    setScanLoading(true)
    setScanError(null)
    setNetworks([])
    setScanned(false)
    setSelected(null)
    setPassword('')
    setConfirming(false)
    setConnectResult(null)
    setConnectError(null)
    try {
      const nets = await scanWifi(robotIp)
      setNetworks(nets)
      setScanned(true)
    } catch {
      setScanError('Scan Wi-Fi échoué. Le robot est-il en ligne ?')
    } finally {
      setScanLoading(false)
    }
  }

  const handleSelectNetwork = (net: WifiNetwork) => {
    setSelected(net)
    setPassword('')
    setShowPassword(false)
    setConfirming(false)
    setConnectResult(null)
    setConnectError(null)
  }

  const handleConnectClick = () => {
    setConfirming(true)
  }

  const handleConfirmConnect = async () => {
    if (!selected) return
    setConnectLoading(true)
    setConfirming(false)
    setConnectError(null)
    setConnectResult(null)
    try {
      const result = await connectWifi(robotIp, selected.ssid, password)
      setConnectResult(result)
      if (result.success) {
        setPassword('')
        await refreshStatus()
      }
    } catch (err) {
      setConnectError(err instanceof Error ? err.message : 'Erreur inconnue.')
    } finally {
      setConnectLoading(false)
    }
  }

  const hasRobot = !!robotIp

  return (
    <div className="max-w-3xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-11 h-11 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
          <Wifi size={22} className="text-blue-300" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">Réseau / Wi-Fi</h1>
          <p className="text-sm text-slate-500">Connecter le robot à un nouveau réseau Wi-Fi.</p>
        </div>
      </div>

      {!hasRobot && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          <WifiOff size={14} />
          Aucun robot configuré — entre l'IP du robot sur l'écran de connexion.
        </div>
      )}

      {/* Network Status */}
      <section className="rounded-xl border border-slate-800 bg-[#0f1629] p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Signal size={16} className="text-blue-300" />
            <h2 className="text-white font-semibold text-sm">Statut réseau actuel</h2>
          </div>
          <button
            onClick={refreshStatus}
            disabled={!hasRobot || statusLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-300 border border-slate-700 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 transition-colors"
          >
            <RefreshCw size={12} className={statusLoading ? 'animate-spin' : ''} />
            Actualiser
          </button>
        </div>

        {statusError && (
          <div className="mb-3 text-xs text-red-400 flex items-center gap-1.5">
            <XCircle size={13} /> {statusError}
          </div>
        )}

        {status ? (
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2">
              <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">État</div>
              <div className={`flex items-center gap-1.5 text-sm font-medium ${status.connected ? 'text-emerald-400' : 'text-slate-500'}`}>
                <div className={`w-2 h-2 rounded-full ${status.connected ? 'bg-emerald-500 animate-pulse' : 'bg-slate-600'}`} />
                {status.connected ? 'Connecté' : 'Déconnecté'}
              </div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2">
              <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">SSID</div>
              <div className="text-sm font-mono text-white truncate">{status.ssid ?? '—'}</div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2">
              <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Adresse IP</div>
              <div className="text-sm font-mono text-cyan-300">{status.ipAddress ?? '—'}</div>
            </div>
          </div>
        ) : (
          <div className="text-xs text-slate-600 py-2">
            Clique sur "Actualiser" pour voir le statut réseau du robot.
          </div>
        )}
      </section>

      {/* Wi-Fi Scan */}
      <section className="rounded-xl border border-slate-800 bg-[#0f1629] p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Search size={16} className="text-blue-300" />
            <h2 className="text-white font-semibold text-sm">Réseaux disponibles</h2>
          </div>
          <button
            onClick={handleScan}
            disabled={!hasRobot || scanLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-blue-300 border border-blue-600/40 bg-blue-600/15 hover:bg-blue-600/25 disabled:opacity-40 transition-colors"
          >
            <Search size={12} className={scanLoading ? 'animate-pulse' : ''} />
            {scanLoading ? 'Scan en cours…' : 'Scanner'}
          </button>
        </div>

        {scanError && (
          <div className="mb-3 text-xs text-red-400 flex items-center gap-1.5">
            <XCircle size={13} /> {scanError}
          </div>
        )}

        {scanLoading && (
          <div className="flex items-center gap-2 py-6 justify-center text-xs text-slate-500">
            <Search size={14} className="animate-pulse" />
            Scan des réseaux Wi-Fi…
          </div>
        )}

        {scanned && !scanLoading && networks.length === 0 && (
          <div className="text-xs text-slate-600 py-4 text-center">Aucun réseau détecté.</div>
        )}

        {networks.length > 0 && (
          <div className="space-y-1.5">
            {networks.map((net) => (
              <button
                key={net.ssid}
                onClick={() => handleSelectNetwork(net)}
                className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg border text-left transition-colors ${
                  selected?.ssid === net.ssid
                    ? 'border-blue-500/50 bg-blue-600/15 text-white'
                    : 'border-slate-800 bg-slate-950/40 text-slate-300 hover:border-slate-700 hover:bg-slate-900/60'
                }`}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <Wifi size={15} className={selected?.ssid === net.ssid ? 'text-blue-400' : 'text-slate-500'} />
                  <span className="text-sm font-medium truncate">{net.ssid}</span>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <SecurityBadge security={net.security} />
                  <SignalBars signal={net.signal} />
                  <span className="text-[10px] font-mono text-slate-500 w-7 text-right">{net.signal}%</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      {/* Connect Form */}
      {selected && (
        <section className="rounded-xl border border-slate-800 bg-[#0f1629] p-5 space-y-4">
          <div className="flex items-center gap-2">
            <Lock size={16} className="text-blue-300" />
            <h2 className="text-white font-semibold text-sm">Connexion</h2>
          </div>

          {/* Warning */}
          <div className="flex items-start gap-2.5 rounded-lg border border-amber-500/30 bg-amber-500/8 px-3 py-3 text-xs text-amber-300">
            <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
            <span>
              Le robot peut changer d'adresse IP après connexion au nouveau réseau.
              Assurez-vous d'avoir un moyen de le retrouver (mDNS, écran OLED, réseau connu…).
            </span>
          </div>

          {/* SSID */}
          <div>
            <label className="block text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">Réseau sélectionné</label>
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-700 bg-slate-950/60 text-sm text-white">
              <Wifi size={13} className="text-blue-400 flex-shrink-0" />
              <span className="font-medium">{selected.ssid}</span>
              <span className="ml-auto">
                <SecurityBadge security={selected.security} />
              </span>
            </div>
          </div>

          {/* Password */}
          <div>
            <label className="block text-[11px] uppercase tracking-wide text-slate-500 mb-1.5">Mot de passe</label>
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="Entrez le mot de passe Wi-Fi"
                autoComplete="new-password"
                className="w-full px-3 py-2 pr-10 rounded-lg border border-slate-700 bg-slate-950/60 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-blue-500/60 focus:ring-1 focus:ring-blue-500/30"
              />
              <button
                type="button"
                onClick={() => setShowPassword(v => !v)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                tabIndex={-1}
              >
                {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          </div>

          {/* Connect Result */}
          {connectResult && (
            <div className={`flex items-start gap-2 rounded-lg border px-3 py-2.5 text-xs ${
              connectResult.success
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                : 'border-red-500/30 bg-red-500/10 text-red-400'
            }`}>
              {connectResult.success ? <CheckCircle size={14} className="mt-0.5 flex-shrink-0" /> : <XCircle size={14} className="mt-0.5 flex-shrink-0" />}
              <div>
                <div>{connectResult.message}</div>
                {connectResult.newIpAddress && (
                  <div className="mt-1 font-mono text-emerald-200">
                    Nouvelle IP : {connectResult.newIpAddress}
                  </div>
                )}
              </div>
            </div>
          )}

          {connectError && (
            <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
              <XCircle size={13} /> {connectError}
            </div>
          )}

          {/* Confirmation step */}
          {confirming ? (
            <div className="space-y-3 rounded-lg border border-amber-500/40 bg-amber-500/8 p-4">
              <div className="flex items-center gap-2 text-xs font-medium text-amber-300">
                <AlertTriangle size={14} />
                Confirmer la connexion à <span className="font-mono">"{selected.ssid}"</span> ?
              </div>
              <div className="flex gap-2">
                <button
                  onClick={handleConfirmConnect}
                  className="flex-1 py-2 rounded-lg bg-blue-600 text-sm font-semibold text-white hover:bg-blue-500 transition-colors"
                >
                  Confirmer
                </button>
                <button
                  onClick={() => setConfirming(false)}
                  className="flex-1 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm text-slate-300 hover:bg-slate-700 transition-colors"
                >
                  Annuler
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={handleConnectClick}
              disabled={!hasRobot || connectLoading || password.length === 0}
              className="w-full py-2.5 rounded-lg bg-blue-600 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
            >
              {connectLoading ? (
                <>
                  <RefreshCw size={14} className="animate-spin" />
                  Connexion en cours…
                </>
              ) : (
                <>
                  <Wifi size={14} />
                  Se connecter à "{selected.ssid}"
                </>
              )}
            </button>
          )}
        </section>
      )}
    </div>
  )
}
