import type { BoardState, LogEntry, PersonaInfo, Run, Ticket, ToolInfo } from './types'

const BASE = ''

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${text}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

// Board
export const fetchBoard = (): Promise<BoardState> => req('/board')

// Tickets
export const listTickets = (): Promise<Ticket[]> => req('/tickets')
export const getTicket = (id: number): Promise<Ticket> => req(`/tickets/${id}`)
export const createTicket = (body: Partial<Ticket> & { title: string; description: string; workspace_path: string }): Promise<Ticket> =>
  req('/tickets', { method: 'POST', body: JSON.stringify(body) })
export const updateTicket = (id: number, body: Partial<Ticket>): Promise<Ticket> =>
  req(`/tickets/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
export const changeStatus = (id: number, to: string, model: string, force = false): Promise<Ticket> =>
  req(`/tickets/${id}/status?force=${force}`, { method: 'PATCH', body: JSON.stringify({ to, model }) })
export const deleteTicket = (id: number): Promise<void> =>
  req(`/tickets/${id}`, { method: 'DELETE' })
export const listRunsForTicket = (id: number): Promise<Run[]> => req(`/tickets/${id}/runs`)

// Runs
export const getRun = (id: number): Promise<Run> => req(`/runs/${id}`)
export const getLogs = (runId: number, afterSeq = 0): Promise<LogEntry[]> =>
  req(`/runs/${runId}/logs?after_seq=${afterSeq}`)
export const killRun = (id: number): Promise<void> => req(`/runs/${id}/kill`, { method: 'POST' })

// Catalogs
export const listTools = (): Promise<ToolInfo[]> => req('/tools')
export const listPersonas = (): Promise<PersonaInfo[]> => req('/personas')
export const getPersona = (name: string): Promise<PersonaInfo> => req(`/personas/${name}`)

// SSE
export function openLogStream(runId: number, afterSeq: number, onEntry: (e: LogEntry) => void, onDone: () => void): () => void {
  const es = new EventSource(`/runs/${runId}/stream?after_seq=${afterSeq}`)

  es.onmessage = (ev) => {
    try {
      onEntry(JSON.parse(ev.data))
    } catch {
      // ignore parse errors
    }
  }

  es.addEventListener('done', () => {
    es.close()
    onDone()
  })

  es.onerror = () => {
    es.close()
    onDone()
  }

  return () => es.close()
}
