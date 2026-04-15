import { useDroppable } from '@dnd-kit/core'
import type { Status, Ticket } from '../types'
import { LANE_LABELS } from '../types'
import { TicketCard } from './TicketCard'

const LANE_HEADER_COLOR: Partial<Record<Status, string>> = {
  done:  'var(--success)',
  error: 'var(--danger)',
  plan:  'var(--warning)',
}

interface LaneProps {
  status: Status
  tickets: Ticket[]
  onRefresh: () => void
}

export function Lane({ status, tickets, onRefresh }: LaneProps) {
  const { setNodeRef, isOver } = useDroppable({ id: status })

  const activeRuns = tickets.filter(t => t.locked).length
  const label = LANE_LABELS[status]
  const headerColor = LANE_HEADER_COLOR[status] || 'var(--text-muted)'

  return (
    <div
      style={{
        minWidth: 200,
        flex: '0 0 220px',
        display: 'flex',
        flexDirection: 'column',
        gap: 0,
      }}
    >
      {/* Lane header */}
      <div style={{
        padding: '8px 12px',
        background: isOver ? 'var(--accent-soft)' : 'var(--surface-alt)',
        borderRadius: '8px 8px 0 0',
        border: '1px solid var(--border)',
        borderBottom: 'none',
        display: 'flex',
        alignItems: 'center',
        gap: 6,
      }}>
        <span style={{ fontWeight: 600, fontSize: 12, color: headerColor, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          {label}
        </span>
        <span style={{
          marginLeft: 'auto',
          background: activeRuns > 0 ? 'var(--running)' : 'var(--border)',
          color: activeRuns > 0 ? '#fff' : 'var(--text-muted)',
          borderRadius: 10,
          fontSize: 10,
          fontWeight: 600,
          padding: '1px 7px',
          minWidth: 18,
          textAlign: 'center',
        }}>
          {tickets.length}
          {activeRuns > 0 && <span style={{ marginLeft: 3 }}>●</span>}
        </span>
      </div>

      {/* Drop zone */}
      <div
        ref={setNodeRef}
        style={{
          flex: 1,
          minHeight: 120,
          padding: '8px 8px 16px',
          background: isOver ? 'var(--accent-soft)' : 'transparent',
          border: `1px solid ${isOver ? 'var(--accent)' : 'var(--border)'}`,
          borderTop: 'none',
          borderRadius: '0 0 8px 8px',
          transition: 'background 0.15s, border-color 0.15s',
        }}
      >
        {tickets.length === 0 && !isOver && (
          <div style={{ textAlign: 'center', padding: '20px 0', color: 'var(--border)', fontSize: 12, fontStyle: 'italic', userSelect: 'none' }}>
            empty
          </div>
        )}
        {tickets.map(ticket => (
          <TicketCard key={ticket.id} ticket={ticket} onRefresh={onRefresh} />
        ))}
      </div>
    </div>
  )
}
