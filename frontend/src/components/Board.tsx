import { useState } from 'react'
import { DndContext, type DragEndEvent, DragOverlay, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import type { Status, Ticket } from '../types'
import { ALL_LANES } from '../types'
import { changeStatus } from '../api'
import { useStore } from '../store'
import { Lane } from './Lane'
import { ModelPickerModal } from './ModelPickerModal'

interface PendingDrop {
  ticket: Ticket
  targetLane: Status
}

export function Board() {
  const { board, upsertTicket, loadBoard } = useStore()
  const [pendingDrop, setPendingDrop] = useState<PendingDrop | null>(null)
  const [activeTicket, setActiveTicket] = useState<Ticket | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  )

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveTicket(null)
    const { active, over } = event
    if (!over) return

    const ticket: Ticket = active.data.current?.ticket
    if (!ticket) return

    const targetLane = over.id as Status
    if (ticket.status === targetLane) return
    if (ticket.locked) return // shouldn't happen (drag disabled on locked), but guard anyway

    setPendingDrop({ ticket, targetLane })
  }

  const handleConfirmMove = async (model: string) => {
    if (!pendingDrop) return
    const { ticket, targetLane } = pendingDrop
    setPendingDrop(null)

    try {
      const updated = await changeStatus(ticket.id, targetLane, model)
      upsertTicket(updated)
    } catch (e) {
      alert(`Failed to move ticket: ${e}`)
      loadBoard() // re-sync
    }
  }

  const handleCancelMove = () => setPendingDrop(null)

  return (
    <>
      <DndContext
        sensors={sensors}
        onDragStart={e => setActiveTicket(e.active.data.current?.ticket ?? null)}
        onDragEnd={handleDragEnd}
      >
        <div style={{
          display: 'flex',
          gap: 12,
          padding: '16px 20px',
          overflowX: 'auto',
          flex: 1,
          alignItems: 'flex-start',
        }}>
          {ALL_LANES.map(lane => (
            <Lane
              key={lane}
              status={lane}
              tickets={board.lanes[lane] ?? []}
              onRefresh={loadBoard}
            />
          ))}
        </div>

        <DragOverlay>
          {activeTicket && (
            <div style={{
              background: 'var(--surface)',
              border: '2px solid var(--accent)',
              borderRadius: 8,
              padding: '10px 12px',
              width: 200,
              boxShadow: '0 8px 24px rgba(0,0,0,0.2)',
              fontSize: 13,
              fontWeight: 500,
              opacity: 0.9,
            }}>
              {activeTicket.title}
            </div>
          )}
        </DragOverlay>
      </DndContext>

      {pendingDrop && (
        <ModelPickerModal
          ticketTitle={pendingDrop.ticket.title}
          targetLane={pendingDrop.targetLane}
          onConfirm={handleConfirmMove}
          onCancel={handleCancelMove}
        />
      )}
    </>
  )
}
