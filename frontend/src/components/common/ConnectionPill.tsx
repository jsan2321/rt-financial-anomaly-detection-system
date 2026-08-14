import React from 'react';
import { ConnectionState } from '../../types';

interface ConnectionPillProps {
  state: ConnectionState;
}

export const ConnectionPill: React.FC<ConnectionPillProps> = ({ state }) => {
  const config = {
    CONNECTED: {
      label: 'Live Stream',
      dotColor: 'var(--color-success)',
      textColor: 'var(--color-text)',
      bgColor: 'var(--color-surface)',
      borderColor: 'var(--color-border)',
      isPulsing: false,
    },
    RECONNECTING: {
      label: 'Reconnecting...',
      dotColor: 'var(--color-warning)',
      textColor: 'var(--color-warning)',
      bgColor: 'var(--color-surface)',
      borderColor: 'var(--color-warning)',
      isPulsing: true,
    },
    DISCONNECTED: {
      label: 'Feed Offline',
      dotColor: 'var(--color-danger)',
      textColor: 'var(--color-danger)',
      bgColor: 'var(--color-surface)',
      borderColor: 'var(--color-danger)',
      isPulsing: false,
    },
  }[state];

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={`Connection status: ${state}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        padding: '4px 10px',
        borderRadius: 'var(--radius-full)',
        backgroundColor: config.bgColor,
        border: `1px solid ${config.borderColor}`,
        fontSize: '11px',
        fontWeight: 600,
        color: config.textColor,
        letterSpacing: '0.02em',
        boxShadow: 'var(--shadow-sm)',
        transition: 'all 0.2s ease',
      }}
    >
      <span
        style={{
          width: '7px',
          height: '7px',
          borderRadius: '50%',
          backgroundColor: config.dotColor,
          display: 'inline-block',
          boxShadow: `0 0 6px ${config.dotColor}`,
        }}
        className={config.isPulsing ? 'animate-pulse-slow' : undefined}
      />
      <span>{config.label}</span>
    </div>
  );
};
