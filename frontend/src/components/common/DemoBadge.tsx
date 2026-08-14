import React from 'react';
import { FlaskConical } from 'lucide-react';

interface DemoBadgeProps {
  size?: 'sm' | 'md';
}

export const DemoBadge: React.FC<DemoBadgeProps> = ({ size = 'md' }) => {
  const isSmall = size === 'sm';

  return (
    <span
      role="note"
      aria-label="Demo scenario alert"
      title="Generated via deterministic demonstration scenario"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        padding: isSmall ? '1px 5px' : '2px 7px',
        borderRadius: 'var(--radius-sm)',
        backgroundColor: 'rgba(126, 34, 206, 0.12)',
        border: '1px solid rgba(126, 34, 206, 0.35)',
        color: 'var(--color-escalation)',
        fontSize: isSmall ? '10px' : '11px',
        fontWeight: 700,
        fontFamily: 'var(--font-mono)',
        letterSpacing: '0.05em',
        lineHeight: 1,
        textTransform: 'uppercase',
      }}
    >
      <FlaskConical size={isSmall ? 10 : 12} />
      <span>DEMO</span>
    </span>
  );
};
