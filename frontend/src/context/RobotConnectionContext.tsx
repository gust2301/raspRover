import { createContext, useContext } from 'react'
import { useRobotConnection, type RobotConnection } from '../hooks/useRobotConnection'

const RobotConnectionContext = createContext<RobotConnection | null>(null)

export function RobotConnectionProvider({ children }: { children: React.ReactNode }) {
  const connection = useRobotConnection()
  return (
    <RobotConnectionContext.Provider value={connection}>
      {children}
    </RobotConnectionContext.Provider>
  )
}

export function useSharedRobotConnection(): RobotConnection {
  const context = useContext(RobotConnectionContext)
  if (context === null) {
    throw new Error('useSharedRobotConnection must be used within RobotConnectionProvider')
  }
  return context
}
