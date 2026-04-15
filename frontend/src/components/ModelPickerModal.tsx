import { useState } from 'react'

const MODELS = [
  { id: 'claude-haiku-4-5-20251001',  label: 'claude-haiku-4-5',  note: 'cheap, fast' },
  { id: 'claude-sonnet-4-5',          label: 'claude-sonnet-4-5', note: 'default' },
  { id: 'claude-opus-4-6',            label: 'claude-opus-4-6',   note: 'strongest' },
]

interface ModelPickerModalProps {
  ticketTitle: string
  targetLane: string
  onConfirm: (model: string) => void
  onCancel: () => void
}

export function ModelPickerModal({ ticketTitle, targetLane, onConfirm, onCancel }: ModelPickerModalProps) {
  const [selected, setSelected] = useState('claude-sonnet-4-5')

  const laneLabel = targetLane.replace(/_/g, ' ')

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.4)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={onCancel}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 12,
          padding: 24,
          width: 360,
          boxShadow: '0 8px 32px rgba(0,0,0,0.15)',
        }}
      >
        <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>
          Moving to {laneLabel}
        </div>
        <div style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 20 }}>
          {ticketTitle}
        </div>

        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Pick model for this phase
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 24 }}>
          {MODELS.map(m => (
            <label
              key={m.id}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '10px 12px',
                border: `1px solid ${selected === m.id ? 'var(--accent)' : 'var(--border)'}`,
                background: selected === m.id ? 'var(--accent-soft)' : 'transparent',
                borderRadius: 8,
                cursor: 'pointer',
                transition: 'all 0.1s',
              }}
            >
              <input
                type="radio"
                name="model"
                value={m.id}
                checked={selected === m.id}
                onChange={() => setSelected(m.id)}
                style={{ accentColor: 'var(--accent)' }}
              />
              <span style={{ flex: 1, fontFamily: 'monospace', fontSize: 12, fontWeight: 500 }}>{m.label}</span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{m.note}</span>
            </label>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button
            onClick={onCancel}
            style={{
              padding: '8px 16px', borderRadius: 6, fontSize: 13,
              border: '1px solid var(--border)', background: 'transparent',
              color: 'var(--text-muted)', cursor: 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm(selected)}
            style={{
              padding: '8px 16px', borderRadius: 6, fontSize: 13,
              border: 'none', background: 'var(--accent)',
              color: '#fff', cursor: 'pointer', fontWeight: 500,
            }}
          >
            Spawn agent
          </button>
        </div>
      </div>
    </div>
  )
}
