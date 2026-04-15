interface HeaderProps {
  onNewTicket: () => void
}

export function Header({ onNewTicket }: HeaderProps) {
  return (
    <header style={{
      height: 56,
      borderBottom: '1px solid var(--border)',
      background: 'var(--surface)',
      display: 'flex',
      alignItems: 'center',
      padding: '0 20px',
      gap: 16,
      flexShrink: 0,
    }}>
      <span style={{ fontWeight: 600, fontSize: 15, letterSpacing: '-0.3px', color: 'var(--text)' }}>
        tasklane
      </span>
      <span style={{ flex: 1 }} />
      <button
        onClick={onNewTicket}
        style={{
          background: 'var(--accent)',
          color: '#fff',
          border: 'none',
          borderRadius: 6,
          padding: '6px 14px',
          fontSize: 13,
          fontWeight: 500,
          cursor: 'pointer',
        }}
      >
        + New ticket
      </button>
    </header>
  )
}
