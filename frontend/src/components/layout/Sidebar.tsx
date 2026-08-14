import React from 'react';
import { LayoutDashboard, ShieldAlert, Settings, Shield } from 'lucide-react';
import { ConnectionPill } from '../common/ConnectionPill';
import { ConnectionState } from '../../types';

interface SidebarProps {
  currentTab: string;
  onSelectTab: (tab: string) => void;
  connectionState: ConnectionState;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentTab,
  onSelectTab,
  connectionState,
}) => {
  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard size={18} /> },
    { id: 'alerts', label: 'Alert Center', icon: <ShieldAlert size={18} /> },
    { id: 'settings', label: 'Settings', icon: <Settings size={18} /> },
  ];

  return (
    <aside
      style={{
        width: 'var(--sidebar-width)',
        backgroundColor: 'var(--color-nav-bg)',
        color: 'var(--color-nav-text)',
        display: 'flex',
        flexDirection: 'column',
        borderRight: '1px solid var(--color-nav-border)',
        flexShrink: 0,
        minHeight: '100vh',
      }}
    >
      {/* Brand Header */}
      <div
        style={{
          padding: 'var(--space-4) var(--space-5)',
          borderBottom: '1px solid var(--color-nav-border)',
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)',
        }}
      >
        <div
          style={{
            width: '28px',
            height: '28px',
            borderRadius: 'var(--radius-sm)',
            backgroundColor: 'var(--color-primary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--color-primary-text)',
          }}
        >
          <Shield size={16} />
        </div>
        <div>
          <h1
            style={{
              fontSize: '14px',
              fontWeight: 700,
              color: 'var(--color-nav-active)',
              letterSpacing: '0.02em',
            }}
          >
            RT-FADS
          </h1>
          <p style={{ fontSize: '10px', color: 'var(--color-nav-muted)', letterSpacing: '0.05em' }}>
            SURVEILLANCE SOC
          </p>
        </div>
      </div>

      {/* Navigation Links */}
      <nav style={{ padding: 'var(--space-3) var(--space-2)', flex: 1 }}>
        <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {navItems.map((item) => {
            const isActive = currentTab === item.id;
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => onSelectTab(item.id)}
                  style={{
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 'var(--space-3)',
                    padding: '8px 12px',
                    borderRadius: 'var(--radius-default)',
                    border: 'none',
                    backgroundColor: isActive ? 'var(--color-nav-surface)' : 'transparent',
                    color: isActive ? 'var(--color-nav-active)' : 'var(--color-nav-text)',
                    fontSize: '13px',
                    fontWeight: isActive ? 600 : 400,
                    cursor: 'pointer',
                    textAlign: 'left',
                    transition: 'all 0.15s ease',
                  }}
                >
                  <span style={{ color: isActive ? 'var(--color-primary)' : 'inherit' }}>
                    {item.icon}
                  </span>
                  <span>{item.label}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Persistent Connection Pill at Sidebar Footer */}
      <div
        style={{
          padding: 'var(--space-4)',
          borderTop: '1px solid var(--color-nav-border)',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
        }}
      >
        <span className="label-caps" style={{ color: 'var(--color-nav-muted)' }}>
          System Telemetry
        </span>
        <ConnectionPill state={connectionState} />
      </div>
    </aside>
  );
};
