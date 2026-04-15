import { useEffect, useState } from 'react'
import type { PersonaInfo, ToolInfo } from '../types'
import { createTicket } from '../api'

const URGENCIES = ['low', 'normal', 'high', 'critical'] as const

interface Props {
  personas: PersonaInfo[]
  tools: ToolInfo[]
  onCreated: () => void
  onClose: () => void
}

export function CreateTicketDrawer({ personas, tools, onCreated, onClose }: Props) {
  const [title, setTitle] = useState('')
  const [persona, setPersona] = useState('software_engineer')
  const [description, setDescription] = useState('')
  const [workspacePath, setWorkspacePath] = useState('')
  const [urgency, setUrgency] = useState<'low' | 'normal' | 'high' | 'critical'>('normal')
  const [selectedTools, setSelectedTools] = useState<string[]>([])
  const [_activeLanes, setActiveLanes] = useState<string[]>([])
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [maxIterations, setMaxIterations] = useState<string>('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // When persona changes, pre-fill fields
  useEffect(() => {
    const p = personas.find(p => p.name === persona)
    if (p) {
      setDescription(p.description_template)
      setSelectedTools([...p.default_tools])
      setActiveLanes([...p.active_lanes])
    }
  }, [persona, personas])

  const toggleTool = (name: string) => {
    setSelectedTools(prev =>
      prev.includes(name) ? prev.filter(t => t !== name) : [...prev, name]
    )
  }

  const toolGroups = ['filesystem', 'execution', 'web']

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      await createTicket({
        title,
        description,
        persona,
        urgency,
        tools_json: selectedTools,
        workspace_path: workspacePath,
        max_iterations: maxIterations ? parseInt(maxIterations) : undefined,
      } as any)
      onCreated()
      onClose()
    } catch (e: any) {
      setError(String(e?.message || e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 900,
        background: 'rgba(0,0,0,0.4)',
        display: 'flex', justifyContent: 'flex-end',
      }}
      onClick={onClose}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 480,
          height: '100%',
          background: 'var(--surface)',
          borderLeft: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          overflowY: 'auto',
        }}
      >
        {/* Header */}
        <div style={{
          padding: '16px 20px',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <span style={{ fontWeight: 600, fontSize: 15 }}>New ticket</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 18, color: 'var(--text-muted)' }}>✕</button>
        </div>

        <form onSubmit={handleSubmit} style={{ flex: 1, padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* Title */}
          <Field label="Title">
            <input
              required
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="Short description of the task"
              style={inputStyle}
            />
          </Field>

          {/* Persona */}
          <Field label="Persona">
            <select value={persona} onChange={e => setPersona(e.target.value)} style={inputStyle}>
              {personas.map(p => (
                <option key={p.name} value={p.name}>{p.label}</option>
              ))}
            </select>
            {personas.find(p => p.name === persona) && (
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                {personas.find(p => p.name === persona)!.description}
              </div>
            )}
          </Field>

          {/* Description = system prompt */}
          <Field label="Description (system prompt)">
            <textarea
              required
              value={description}
              onChange={e => setDescription(e.target.value)}
              rows={10}
              placeholder="Describe what the agent should do. This is sent as the system prompt."
              style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit' }}
            />
          </Field>

          {/* Workspace */}
          <Field label="Workspace path">
            <input
              required
              value={workspacePath}
              onChange={e => setWorkspacePath(e.target.value)}
              placeholder="/absolute/path/to/your/project"
              style={inputStyle}
            />
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
              Must be an existing directory on this machine.
            </div>
          </Field>

          {/* Urgency */}
          <Field label="Urgency">
            <div style={{ display: 'flex', gap: 8 }}>
              {URGENCIES.map(u => (
                <button
                  key={u}
                  type="button"
                  onClick={() => setUrgency(u)}
                  style={{
                    flex: 1,
                    padding: '6px 0',
                    borderRadius: 6,
                    fontSize: 12,
                    border: `1px solid ${urgency === u ? 'var(--accent)' : 'var(--border)'}`,
                    background: urgency === u ? 'var(--accent-soft)' : 'transparent',
                    color: urgency === u ? 'var(--accent)' : 'var(--text-muted)',
                    cursor: 'pointer',
                    fontWeight: urgency === u ? 600 : 400,
                  }}
                >
                  {u}
                </button>
              ))}
            </div>
          </Field>

          {/* Tools */}
          <Field label="Tools">
            {toolGroups.map(group => {
              const groupTools = tools.filter(t => t.group === group)
              if (!groupTools.length) return null
              return (
                <div key={group} style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>{group}</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {groupTools.map(t => (
                      <label key={t.name} style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer', fontSize: 12 }}>
                        <input
                          type="checkbox"
                          checked={selectedTools.includes(t.name)}
                          onChange={() => toggleTool(t.name)}
                          style={{ accentColor: 'var(--accent)' }}
                        />
                        <span style={{ color: t.dangerous ? 'var(--warning)' : 'var(--text)' }}>
                          {t.name}{t.dangerous ? ' ⚠' : ''}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              )
            })}
          </Field>

          {/* Advanced toggle */}
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 12, textAlign: 'left', padding: 0 }}
          >
            {showAdvanced ? '▾' : '▸'} Advanced
          </button>

          {showAdvanced && (
            <Field label="Max iterations (overrides urgency default)">
              <input
                type="number"
                value={maxIterations}
                onChange={e => setMaxIterations(e.target.value)}
                placeholder="e.g. 15"
                min={1}
                max={100}
                style={{ ...inputStyle, width: 100 }}
              />
            </Field>
          )}

          {error && (
            <div style={{ color: 'var(--danger)', fontSize: 12, background: '#fff0f0', padding: '8px 12px', borderRadius: 6 }}>
              {error}
            </div>
          )}

          <div style={{ display: 'flex', gap: 8, marginTop: 'auto', paddingTop: 8 }}>
            <button type="button" onClick={onClose} style={{ flex: 1, padding: '10px 0', borderRadius: 8, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 13 }}>
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              style={{ flex: 2, padding: '10px 0', borderRadius: 8, border: 'none', background: 'var(--accent)', color: '#fff', cursor: 'pointer', fontSize: 13, fontWeight: 500 }}
            >
              {saving ? 'Creating…' : 'Create ticket'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {label}
      </label>
      {children}
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  background: 'var(--surface-alt)',
  border: '1px solid var(--border)',
  borderRadius: 6,
  padding: '8px 10px',
  fontSize: 13,
  color: 'var(--text)',
  outline: 'none',
  width: '100%',
}
