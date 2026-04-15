import { useState } from 'react'
import { useDraggable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import type { Run, Ticket } from '../types'
import { killRun, listRunsForTicket } from '../api'
import { LogTail } from './LogTail'

const URGENCY_COLOR: Record<string, string> = {
  low:      'var(--text-muted)',
  normal:   'var(--accent)',
  high:     'var(--warning)',
  critical: 'var(--danger)',
}

const PERSONA_EMOJI: Record<string, string> = {
  software_engineer:   '💻',
  software_architect:  '🏗️',
  data_analyst:        '📊',
  research_assistant:  '🔍',
  qa_engineer:         '🧪',
  code_reviewer:       '👀',
  custom:              '⚙️',
}

const STATUS_LABEL: Record<string, { color: string; label: string }> = {
  running:            { color: 'var(--running)',  label: '⟳ running' },
  completed:          { color: 'var(--success)',  label: '✓ done' },
  crashed:            { color: 'var(--danger)',   label: '✗ crashed' },
  iteration_exceeded: { color: 'var(--warning)',  label: '⚠ max iters' },
  killed:             { color: 'var(--danger)',   label: '✗ killed' },
  budget_exceeded:    { color: 'var(--warning)',  label: '⚠ budget' },
  api_error:          { color: 'var(--danger)',   label: '✗ api error' },
}

interface TicketCardProps {
  ticket: Ticket
  onRefresh: () => void
}

export function TicketCard({ ticket, onRefresh }: TicketCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [runs, setRuns] = useState<Run[]>([])
  const [killing, setKilling] = useState(false)

  const isRunning = ticket.locked && !!ticket.active_run_id

  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `ticket-${ticket.id}`,
    data: { ticket },
    disabled: ticket.locked, // locked = active run — drag disabled
  })

  const style = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.5 : 1,
    cursor: ticket.locked ? 'not-allowed' : 'grab',
  }

  const handleExpand = async () => {
    if (!expanded) {
      const r = await listRunsForTicket(ticket.id).catch(() => [])
      setRuns(r)
    }
    setExpanded(!expanded)
  }

  const handleKill = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!ticket.active_run_id) return
    setKilling(true)
    try {
      await killRun(ticket.active_run_id)
      setTimeout(onRefresh, 1500) // give the run a moment to stop
    } catch {
      // ignore
    } finally {
      setKilling(false)
    }
  }

  const urgencyColor = URGENCY_COLOR[ticket.urgency] || 'var(--text-muted)'
  const emoji = PERSONA_EMOJI[ticket.persona] || '⚙️'

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={isRunning ? 'running-pulse' : ''}
      {...(ticket.locked ? {} : { ...listeners, ...attributes })}
    >
      <div
        onClick={handleExpand}
        title={ticket.locked ? 'A run is active — kill it to drag' : undefined}
        style={{
          background: 'var(--surface)',
          border: `1px solid var(--border)`,
          borderLeft: isRunning ? undefined : `3px solid ${ticket.status === 'error' ? 'var(--danger)' : 'transparent'}`,
          borderRadius: 8,
          padding: '10px 12px',
          marginBottom: 6,
          cursor: 'pointer',
          boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
          transition: 'box-shadow 0.15s',
        }}
        onMouseEnter={e => { if (!ticket.locked) (e.currentTarget as HTMLDivElement).style.boxShadow = '0 2px 8px rgba(0,0,0,0.1)' }}
        onMouseLeave={e => (e.currentTarget as HTMLDivElement).style.boxShadow = '0 1px 3px rgba(0,0,0,0.05)'}
      >
        {/* Header row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: urgencyColor, flexShrink: 0 }} />
          <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 500 }}>#{ticket.id}</span>
        </div>

        {/* Title */}
        <div style={{
          fontWeight: 500,
          fontSize: 13,
          lineHeight: 1.4,
          marginBottom: 8,
          display: '-webkit-box',
          WebkitLineClamp: expanded ? undefined : 2,
          WebkitBoxOrient: 'vertical',
          overflow: expanded ? undefined : 'hidden',
        }}>
          {ticket.status === 'error' && <span style={{ color: 'var(--danger)', marginRight: 4 }}>⚠</span>}
          {ticket.title}
        </div>

        {/* Persona + run status */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{emoji} {ticket.persona.replace(/_/g, ' ')}</span>
          {isRunning && (
            <span style={{ fontSize: 11, color: 'var(--running)' }}>
              <span className="spin">⟳</span> running
            </span>
          )}
        </div>

        {/* Expanded content */}
        {expanded && (
          <div style={{ marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
            {/* Description preview */}
            <div style={{
              fontSize: 12,
              color: 'var(--text-muted)',
              marginBottom: 10,
              maxHeight: 80,
              overflow: 'hidden',
              lineHeight: 1.5,
            }}>
              {ticket.description.slice(0, 300)}{ticket.description.length > 300 ? '…' : ''}
            </div>

            {/* Log tail for active run */}
            {ticket.active_run_id && (
              <div style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Live Log</div>
                <LogTail runId={ticket.active_run_id} isRunning={isRunning} />
              </div>
            )}

            {/* Run history */}
            {runs.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Run History</div>
                {runs.slice(0, 5).map(run => {
                  const s = STATUS_LABEL[run.status] || { color: 'var(--text-muted)', label: run.status }
                  return (
                    <div key={run.id} style={{ display: 'flex', gap: 8, fontSize: 11, marginBottom: 2, color: 'var(--text-muted)' }}>
                      <span style={{ color: s.color }}>{s.label}</span>
                      <span>{run.lane.replace(/_/g, ' ')}</span>
                      <span>{run.model.split('-').slice(-2).join('-')}</span>
                      <span>{run.iterations} iters</span>
                      <span>{(run.input_tokens / 1000).toFixed(1)}k tok</span>
                    </div>
                  )
                })}
              </div>
            )}

            {/* Actions */}
            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
              {ticket.active_run_id && (
                <button
                  onClick={handleKill}
                  disabled={killing}
                  style={{
                    fontSize: 11,
                    padding: '4px 10px',
                    borderRadius: 5,
                    border: `1px solid var(--danger)`,
                    background: 'transparent',
                    color: 'var(--danger)',
                    cursor: 'pointer',
                    fontWeight: 500,
                  }}
                >
                  {killing ? 'Killing…' : 'Kill run'}
                </button>
              )}
              <a
                href={`file://${ticket.workspace_path}`}
                target="_blank"
                rel="noreferrer"
                onClick={e => e.stopPropagation()}
                style={{
                  fontSize: 11,
                  padding: '4px 10px',
                  borderRadius: 5,
                  border: `1px solid var(--border)`,
                  color: 'var(--text-muted)',
                  textDecoration: 'none',
                  cursor: 'pointer',
                }}
              >
                Workspace ↗
              </a>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
