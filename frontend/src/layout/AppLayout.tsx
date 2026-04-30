import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import Sidebar from './Sidebar'
import Header from './Header'

export default function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [isMobileLandscapePilotage, setIsMobileLandscapePilotage] = useState(false)
  const location = useLocation()

  useEffect(() => {
    const updateViewportMode = () => {
      setIsMobileLandscapePilotage(
        location.pathname === '/pilotage'
          && window.innerWidth < 1024
          && window.innerWidth > window.innerHeight
      )
    }

    updateViewportMode()
    window.addEventListener('resize', updateViewportMode)
    return () => window.removeEventListener('resize', updateViewportMode)
  }, [location.pathname])

  return (
    <div className="flex min-h-screen" style={{ background: '#0a0f1e' }}>
      {!isMobileLandscapePilotage && (
        <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      )}
      <div className="flex-1 flex flex-col min-w-0">
        {!isMobileLandscapePilotage && (
          <Header onOpenSidebar={() => setSidebarOpen(true)} />
        )}
        <main className={`flex-1 overflow-auto ${isMobileLandscapePilotage ? 'p-0' : 'p-3 sm:p-4 lg:p-6'}`}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
