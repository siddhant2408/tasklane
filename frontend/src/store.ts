import { create } from 'zustand'
import type { BoardState, PersonaInfo, Status, Ticket, ToolInfo } from './types'
import { ALL_LANES } from './types'
import { fetchBoard, listPersonas, listTools } from './api'

interface AppState {
  board: BoardState
  personas: PersonaInfo[]
  tools: ToolInfo[]
  loading: boolean
  error: string | null

  loadBoard: () => Promise<void>
  loadCatalogs: () => Promise<void>
  upsertTicket: (ticket: Ticket) => void
  removeTicket: (id: number) => void
}

const emptyBoard = (): BoardState => ({
  lanes: Object.fromEntries(ALL_LANES.map(l => [l, []])) as unknown as BoardState['lanes'],
})

export const useStore = create<AppState>((set) => ({
  board: emptyBoard(),
  personas: [],
  tools: [],
  loading: false,
  error: null,

  loadBoard: async () => {
    set({ loading: true, error: null })
    try {
      const board = await fetchBoard()
      set({ board, loading: false })
    } catch (e) {
      set({ error: String(e), loading: false })
    }
  },

  loadCatalogs: async () => {
    const [personas, tools] = await Promise.all([listPersonas(), listTools()])
    set({ personas, tools })
  },

  upsertTicket: (ticket: Ticket) => {
    set(state => {
      const lanes = { ...state.board.lanes }

      // Remove from all lanes first
      for (const lane of ALL_LANES) {
        if (lanes[lane]) {
          lanes[lane] = lanes[lane].filter(t => t.id !== ticket.id)
        }
      }

      // Add to correct lane
      const lane = ticket.status as Status
      if (!lanes[lane]) lanes[lane] = []
      lanes[lane] = [...lanes[lane], ticket]

      return { board: { lanes } }
    })
  },

  removeTicket: (id: number) => {
    set(state => {
      const lanes = { ...state.board.lanes }
      for (const lane of ALL_LANES) {
        if (lanes[lane]) {
          lanes[lane] = lanes[lane].filter(t => t.id !== id)
        }
      }
      return { board: { lanes } }
    })
  },
}))
