import React from 'react';
import { AlertSeverity } from '../../types';

interface RiskChipProps {
  severity: AlertSeverity | 'ESCALATION';
  score?: number;
  size?: 'sm' | 'md';
}

export const RiskChip: React.FC<RiskChipProps> = ({
  severity,
  score,
  size = 'md',
}) => {
  const styles = {
    CRITICAL: {
      color: 'var(--color-risk-critical)',
      bg: 'var(--color-risk-critical-bg)',
      border: 'var(--color-risk-critical-border)',
      label: 'CRITICAL',
    },
    HIGH: {
      color: 'var(--color-risk-high)',
      bg: 'var(--color-risk-high-bg)',
      border: 'var(--color-risk-high-border)',
      label: 'HIGH',
    },
    MEDIUM: {
      color: 'var(--color-risk-medium)',
      bg: 'var(--color-risk-medium-bg)',
      border: 'var(--color-risk-medium-border)',
      label: 'MEDIUM',
    },
    LOW: {
      color: 'var(--color-risk-low)',
      bg: 'var(--color-risk-low-bg)',
      border: 'var(--color-risk-low-border)',
      label: 'LOW',
    },
    ESCALATION: {
      color: 'var(--color-escalation)',
      bg: 'var(--color-escalation-bg)',
      border: 'var(--color-escalation-border)',
      label: 'ESCALATED',
    },
  }[severity] || {
    color: 'var(--color-text-muted)',
    bg: 'var(--color-surface-subtle)',
    border: 'var(--color-border)',
    label: severity,
  };

  const isSmall = size === 'sm';

  return (
    <span
      role="status"
      aria-label={`Severity: ${styles.label}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        padding: isSmall ? '2px 6px' : '3px 8px',
        borderRadius: 'var(--radius-sm)',
        backgroundColor: styles.bg,
        border: `1px solid ${styles.border}`,
        color: styles.color,
        fontSize: isSmall ? '10px' : '11px',
        fontWeight: 700,
        fontFamily: 'var(--font-mono)',
        letterSpacing: '0.04em',
        lineHeight: 1,
        whiteSpace: 'nowrap',
      }}
    >
      <span
        style={{
          width: '5px',
          height: '5px',
          borderRadius: '50%',
          backgroundColor: styles.color,
        }}
      />
      <span>{styles.label}</span>
      {score !== undefined && !isNaN(Number(score)) && (
        <span style={{ opacity: 0.85, fontWeight: 500 }}>
          ({Number(score).toFixed(2)})
        </span>
      )}
    </span>
  );
};
