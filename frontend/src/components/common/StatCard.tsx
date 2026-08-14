import React from 'react';

interface StatCardProps {
  title: string;
  value: string | number;
  subtext?: string;
  icon?: React.ReactNode;
  trend?: {
    value: string;
    isPositive?: boolean;
    isNeutral?: boolean;
  };
  accentColor?: string;
}

export const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  subtext,
  icon,
  trend,
  accentColor,
}) => {
  return (
    <div
      className="card"
      style={{
        padding: 'var(--space-4)',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-2)',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {accentColor && (
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: '3px',
            backgroundColor: accentColor,
          }}
        />
      )}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          color: 'var(--color-text-secondary)',
        }}
      >
        <span className="label-caps">{title}</span>
        {icon && <span style={{ color: 'var(--color-text-muted)' }}>{icon}</span>}
      </div>

      <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
        <span
          className="technical-data"
          style={{
            fontSize: '24px',
            fontWeight: 700,
            color: 'var(--color-text)',
            lineHeight: 1.1,
          }}
        >
          {value}
        </span>
        {trend && (
          <span
            style={{
              fontSize: '11px',
              fontWeight: 600,
              color: trend.isNeutral
                ? 'var(--color-text-muted)'
                : trend.isPositive
                ? 'var(--color-success)'
                : 'var(--color-danger)',
            }}
          >
            {trend.value}
          </span>
        )}
      </div>

      {subtext && (
        <p className="body-sm" style={{ color: 'var(--color-text-muted)' }}>
          {subtext}
        </p>
      )}
    </div>
  );
};
