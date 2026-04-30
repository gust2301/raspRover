import { Shield, Camera, Route, Bot } from 'lucide-react'
import StatCard from '../components/StatCard'
import VideoFeedCard from '../components/VideoFeedCard'
import RobotStatusCard from '../components/RobotStatusCard'
import MapCard from '../components/MapCard'
import ManualControlCard from '../components/ManualControlCard'
import IncidentList from '../components/IncidentList'
import QuickActions from '../components/QuickActions'
import SystemLogs from '../components/SystemLogs'

const kpis = [
  {
    icon: <Shield size={20} className="text-blue-400" />,
    iconBg: 'bg-blue-500/10',
    value: '12',
    label: 'Alertes aujourd\'hui',
    sub: '20% vs hier',
    trend: { value: '20%', up: true },
  },
  {
    icon: <Camera size={20} className="text-emerald-400" />,
    iconBg: 'bg-emerald-500/10',
    value: '18',
    label: 'Caméras actives',
    sub: 'Tous systèmes OK',
    statusDot: 'green' as const,
  },
  {
    icon: <Route size={20} className="text-amber-400" />,
    iconBg: 'bg-amber-500/10',
    value: '2h 45m',
    label: 'Patrouille du jour',
    sub: '15% vs hier',
    trend: { value: '15%', up: true },
  },
  {
    icon: <Bot size={20} className="text-blue-400" />,
    iconBg: 'bg-blue-500/10',
    value: '100%',
    label: 'Disponibilité robot',
    sub: 'En ligne',
    statusDot: 'green' as const,
  },
]

export default function Dashboard() {
  return (
    <div className="space-y-5">
      {/* KPIs */}
      <div className="grid grid-cols-4 gap-4">
        {kpis.map((kpi, i) => <StatCard key={i} {...kpi} />)}
      </div>

      {/* Video + Robot status */}
      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2">
          <VideoFeedCard />
        </div>
        <RobotStatusCard />
      </div>

      {/* Map */}
      <MapCard />

      {/* Control + Incidents + Actions */}
      <div className="grid grid-cols-3 gap-4">
        <ManualControlCard />
        <IncidentList />
        <QuickActions />
      </div>

      {/* Logs */}
      <SystemLogs />
    </div>
  )
}
