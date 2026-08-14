import React from 'react';
import { UserCheck } from 'lucide-react';
import { ThemeToggle } from '../common/ThemeToggle';

interface HeaderProps {
  title: string;
  subtitle?: string;
}

export const Header: React.FC<HeaderProps> = ({ title, subtitle }) => {
  return (
    <header
      style={{
        height: 'var(--header-height)',
        borderBottom: '1px solid var(--color-border)',
        backgroundColor: 'var(--color-surface)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 var(--space-6)',
        flexShrink: 0,
      }}
    >
      <div>
        <h2 className="headline-sm" style={{ margin: 0 }}>
          {title}
        </h2>
        {subtitle && (
          <p className="body-sm" style={{ color: 'var(--color-text-muted)', marginTop: '1px' }}>
            {subtitle}
          </p>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)' }}>
        <ThemeToggle />

        {/* Analyst Identity Pill */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '4px 10px',
            backgroundColor: 'var(--color-surface-subtle)',
            borderRadius: 'var(--radius-default)',
            border: '1px solid var(--color-border)',
            fontSize: '12px',
            color: 'var(--color-text-secondary)',
          }}
        >
          <UserCheck size={14} style={{ color: 'var(--color-primary)' }} />
          <span style={{ fontWeight: 600 }}>Analyst Console</span>
        </div>
      </div>
    </header>
  );
};
