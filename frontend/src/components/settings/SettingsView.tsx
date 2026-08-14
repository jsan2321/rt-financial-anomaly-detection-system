import React from 'react';
import { Moon, Sun, Monitor, Server } from 'lucide-react';

import { useTheme } from '../../context/ThemeContext';

export const SettingsView: React.FC = () => {
  const { theme, setTheme } = useTheme();

  return (
    <div style={{ maxWidth: '800px', display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
      {/* Theme Settings Card */}
      <div className="card" style={{ padding: 'var(--space-5)' }}>
        <h3 className="headline-sm" style={{ marginBottom: '4px' }}>
          Appearance & Theme
        </h3>
        <p className="body-sm" style={{ color: 'var(--color-text-muted)', marginBottom: 'var(--space-4)' }}>
          Customize your surveillance console interface. Supports Light-First and Dark modes.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 'var(--space-3)' }}>
          {[
            { mode: 'light' as const, label: 'Light Mode (Default)', icon: <Sun size={18} /> },
            { mode: 'dark' as const, label: 'Dark Mode (SOC)', icon: <Moon size={18} /> },
            { mode: 'system' as const, label: 'System Sync', icon: <Monitor size={18} /> },
          ].map((item) => {
            const isActive = theme === item.mode;
            return (
              <button
                key={item.mode}
                type="button"
                onClick={() => setTheme(item.mode)}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '8px',
                  padding: 'var(--space-4)',
                  borderRadius: 'var(--radius-default)',
                  backgroundColor: isActive ? 'var(--color-surface-subtle)' : 'transparent',
                  border: `2px solid ${isActive ? 'var(--color-primary)' : 'var(--color-border)'}`,
                  color: isActive ? 'var(--color-primary)' : 'var(--color-text-secondary)',
                  cursor: 'pointer',
                  fontWeight: 600,
                  fontSize: '12px',
                  transition: 'all 0.15s ease',
                }}
              >
                {item.icon}
                <span>{item.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Gateway & Environment Config Card */}
      <div className="card" style={{ padding: 'var(--space-5)' }}>
        <h3 className="headline-sm" style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
          <Server size={18} style={{ color: 'var(--color-info)' }} />
          <span>Gateway Endpoints & Telemetry</span>
        </h3>
        <p className="body-sm" style={{ color: 'var(--color-text-muted)', marginBottom: 'var(--space-4)' }}>
          Active connection parameters for ingestion and notification feeds.
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--color-border-subtle)' }}>
            <span style={{ color: 'var(--color-text-secondary)' }}>FastAPI Gateway REST API:</span>
            <span className="technical-data" style={{ color: 'var(--color-primary)' }}>
              http://localhost:8000/api/v1
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--color-border-subtle)' }}>
            <span style={{ color: 'var(--color-text-secondary)' }}>WebSocket Notification Channel:</span>
            <span className="technical-data" style={{ color: 'var(--color-primary)' }}>
              ws://localhost:8000/ws/alerts
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0' }}>
            <span style={{ color: 'var(--color-text-secondary)' }}>Django Admin Control Plane:</span>
            <span className="technical-data" style={{ color: 'var(--color-escalation)' }}>
              http://localhost:8001/admin/
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
