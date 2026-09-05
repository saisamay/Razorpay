import React from 'react';

export interface NavItem {
  id: string;
  label: string;
  path: string;
  badge?: string;
}

export interface SidebarProps {
  currentPath: string;
  onNavigate: (path: string) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ currentPath, onNavigate }) => {
  const navItems: NavItem[] = [
    { id: 'overview', label: 'Recovery Control Center', path: '/' },
    { id: 'cases', label: 'Recovery Cases', path: '/cases' },
    { id: 'experiments', label: 'Experiments & F4', path: '/experiments' },
    { id: 'operations', label: 'Recovery Operations', path: '/operations' },
    { id: 'governance', label: 'F5 Governance', path: '/governance' },
    { id: 'evidence', label: 'Evidence & Audit', path: '/evidence' },
  ];

  return (
    <aside
      style={{
        width: '240px',
        background: 'var(--bg-dark-800)',
        borderRight: '1px solid var(--border-subtle)',
        display: 'flex',
        flexDirection: 'column',
        padding: '1.25rem 0.75rem',
        gap: '0.35rem',
        flexShrink: 0,
      }}
    >
      <div style={{ padding: '0 0.75rem 0.75rem 0.75rem', fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        Navigation
      </div>
      {navItems.map((item) => {
        const isActive = currentPath === item.path;
        return (
          <button
            key={item.id}
            onClick={() => onNavigate(item.path)}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              width: '100%',
              padding: '0.65rem 0.85rem',
              borderRadius: 'var(--radius-md)',
              border: isActive ? '1px solid var(--border-accent)' : '1px solid transparent',
              background: isActive ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
              color: isActive ? '#fff' : 'var(--text-secondary)',
              fontWeight: isActive ? 600 : 400,
              fontSize: '0.875rem',
              cursor: 'pointer',
              textAlign: 'left',
              transition: 'background 0.15s ease, color 0.15s ease',
            }}
          >
            <span>{item.label}</span>
            {item.badge && (
              <span
                style={{
                  fontSize: '0.7rem',
                  padding: '0.1rem 0.4rem',
                  borderRadius: '9999px',
                  background: 'var(--bg-dark-700)',
                  color: 'var(--text-muted)',
                }}
              >
                {item.badge}
              </span>
            )}
          </button>
        );
      })}
    </aside>
  );
};
