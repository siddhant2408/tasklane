import { useEffect, useState } from 'react'
import { useStore } from './store'
import { Header } from './components/Header'
import { Board } from './components/Board'
import { CreateTicketDrawer } from './components/CreateTicketDrawer'

export default function App() {
  const { loadBoard, loadCatalogs, personas, tools, loading, error } = useStore()
  const [showCreate, setShowCreate] = useState(false)

  useEffect(() => {
    loadBoard()
    loadCatalogs()

    // Poll for board updates every 3 seconds to catch auto-advances and run completions
    const interval = setInterval(loadBoard, 3000)
    return () => clearInterval(interval)
  }, [])

  return (
    <>
      <Header onNewTicket={() => setShowCreate(true)} />

      {loading && (
        <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
          Loading…
        </div>
      )}

      {error && (
        <div style={{ padding: '12px 20px', background: '#fff0f0', color: 'var(--danger)', fontSize: 13 }}>
          Failed to load: {error}
        </div>
      )}

      <Board />

      {showCreate && (
        <CreateTicketDrawer
          personas={personas}
          tools={tools}
          onCreated={loadBoard}
          onClose={() => setShowCreate(false)}
        />
      )}
    </>
  )
}
