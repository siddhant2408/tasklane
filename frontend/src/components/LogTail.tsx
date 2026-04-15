import { useEffect, useRef, useState } from 'react'
import { openLogStream } from '../api'
import type { LogEntry } from '../types'

const LEVEL_COLOR: Record<string, string> = {
  tool_use:       '#B76E00',
  tool_result:    '#0A7D3E',
  assistant_text: 'var(--accent)',
  warn:           '#E8A040',
  error:          'var(--danger)',
  info:           'var(--text-muted)',
}

function LogLine({ entry }: { entry: LogEntry }) {
  const color = LEVEL_COLOR[entry.level] || 'var(--text)'
  const time = entry.ts.slice(11, 19) // HH:MM:SS
  return (
    <div>
      <span style={{ color: 'var(--text-muted)', marginRight: 8 }}>{time}</span>
      <span style={{ color, marginRight: 8 }}>[{entry.level}]</span>
      <span>{entry.message}</span>
    </div>
  )
}

interface LogTailProps {
  runId: number
  isRunning: boolean
}

export function LogTail({ runId, isRunning }: LogTailProps) {
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [done, setDone] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setEntries([])
    setDone(false)

    const close = openLogStream(
      runId,
      0,
      (entry) => setEntries(prev => {
        // Deduplicate by seq
        if (prev.some(e => e.seq === entry.seq)) return prev
        return [...prev, entry]
      }),
      () => setDone(true),
    )

    return close
  }, [runId])

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries])

  if (entries.length === 0 && !isRunning) {
    return (
      <div className="log-tail" style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
        No logs yet.
      </div>
    )
  }

  return (
    <div className="log-tail">
      {entries.map(e => <LogLine key={e.seq} entry={e} />)}
      {isRunning && !done && (
        <div style={{ color: 'var(--running)' }}>
          <span className="spin">⟳</span> Agent running...
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  )
}
