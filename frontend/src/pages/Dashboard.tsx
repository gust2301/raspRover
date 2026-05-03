import { Shield, Camera, Route, BatteryMedium } from 'lucide-react'
import StatCard from '../components/StatCard'
import VideoFeedCard from '../components/VideoFeedCard'
import RobotStatusCard from '../components/RobotStatusCard'
import MapCard from '../components/MapCard'
import ManualControlCard from '../components/ManualControlCard'
import IncidentList from '../components/IncidentList'
import QuickActions from '../components/QuickActions'
import SystemLogs from '../components/SystemLogs'
import { useSharedRobotConnection } from '../context/RobotConnectionContext'

export default function Dashboard() {
  const conn = useSharedRobotConnection()
  const s    = conn.lastStatus
  const isOnline     = conn.status === 'connected'
  const patrolActive = s?.patrol_active ?? false
  const patrolState  = s?.patrol_state ?? 'idle'
  const obstacle     = s?.obstacle ?? false
  const frontCm      = s?.front_cm as number | null | undefined

  const batteryPct = s?.battery
  const batteryLow = batteryPct != null && batteryPct < 20

  const kpis = [
    {
      icon: <Shield size={20} className={obstacle ? 'text-red-400' : 'text-blue-400'} />,
      iconBg: obstacle ? 'bg-red-500/10' : 'bg-blue-500/10',
      value: obstacle ? '⚠' : '—',
      label: 'Obstacle détecté',
      sub: frontCm != null ? `${(frontCm).toFixed(0)} cm en avant` : 'Aucun obstacle',
      statusDot: (obstacle ? 'red' : 'green') as 'red' | 'green',
    },
    {
      icon: <Camera size={20} className={isOnline ? 'text-emerald-400' : 'text-slate-500'} />,
      iconBg: isOnline ? 'bg-emerald-500/10' : 'bg-slate-500/10',
      value: isOnline ? '1' : '0',
      label: 'Caméra active',
      sub: isOnline ? `${conn.latencyMs ?? '—'} ms latence` : 'Robot déconnecté',
      statusDot: (isOnline ? 'green' : 'red') as 'green' | 'red',
    },
    {
      icon: <Route size={20} className={patrolActive ? 'text-blue-400' : 'text-slate-500'} />,
      iconBg: patrolActive ? 'bg-blue-500/10' : 'bg-slate-500/10',
      value: patrolActive ? (patrolState === 'avoiding' ? '↩' : '▶') : '■',
      label: 'Patrouille',
      sub: patrolActive
        ? (patrolState === 'avoiding' ? 'Évitement en cours' : 'Patrouille en cours')
        : 'Patrouille inactive',
      statusDot: (patrolActive ? 'green' : 'red') as 'green' | 'red',
    },
    {
      icon: <BatteryMedium size={20} className={!isOnline ? 'text-slate-500' : batteryLow ? 'text-red-400' : 'text-emerald-400'} />,
      iconBg: !isOnline ? 'bg-slate-500/10' : batteryLow ? 'bg-red-500/10' : 'bg-emerald-500/10',
      value: batteryPct != null ? `${batteryPct}%` : isOnline ? '—' : '—',
      label: 'Batterie',
      sub: s?.voltage != null
        ? `${(s.voltage as number).toFixed(1)} V`
        : isOnline ? 'En attente…' : 'Robot hors ligne',
      statusDot: (!isOnline || batteryPct == null ? 'red' : batteryLow ? 'red' : 'green') as 'red' | 'green',
    },
  ]

  return (
    <div className="space-y-5">
      {/* KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {kpis.map((kpi, i) => <StatCard key={i} {...kpi} />)}
      </div>

      {/* Video + Robot status */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2">
          <VideoFeedCard />
        </div>
        <RobotStatusCard />
      </div>

      {/* Map */}
      <MapCard />

      {/* Control + Incidents + Actions */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ManualControlCard />
        <IncidentList />
        <QuickActions />
      </div>

      {/* Logs */}
      <SystemLogs />
    </div>
  )
}
