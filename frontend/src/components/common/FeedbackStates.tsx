import React from 'react';
import { AlertCircle, Inbox } from 'lucide-react';

export const LoadingSkeleton: React.FC<{ rows?: number; height?: string }> = ({
  rows = 5,
  height = '36px',
}) => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', width: '100%' }}>
      {Array.from({ length: rows }).map((_, idx) => (
        <div
          key={idx}
          className="animate-pulse-slow"
          style={{
            height,
            backgroundColor: 'var(--color-surface-subtle)',
            borderRadius: 'var(--radius-default)',
            border: '1px solid var(--color-border-subtle)',
          }}
        />
      ))}
    </div>
  );
};

export const EmptyState: React.FC<{
  title: string;
  description?: string;
  action?: React.ReactNode;
}> = ({ title, description, action }) => {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 'var(--space-10) var(--space-4)',
        textAlign: 'center',
        color: 'var(--color-text-muted)',
      }}
    >
      <Inbox size={36} style={{ marginBottom: 'var(--space-3)', opacity: 0.6 }} />
      <h3 className="headline-sm" style={{ color: 'var(--color-text)', marginBottom: 'var(--space-1)' }}>
        {title}
      </h3>
      {description && (
        <p className="body-sm" style={{ maxWidth: '400px', marginBottom: 'var(--space-4)' }}>
          {description}
        </p>
      )}
      {action}
    </div>
  );
};

export const ErrorBanner: React.FC<{
  message: string;
  onRetry?: () => void;
}> = ({ message, onRetry }) => {
  return (
    <div
      role="alert"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: 'var(--space-3) var(--space-4)',
        backgroundColor: 'rgba(185, 28, 28, 0.08)',
        border: '1px solid rgba(185, 28, 28, 0.25)',
        borderRadius: 'var(--radius-default)',
        color: 'var(--color-danger)',
        fontSize: '13px',
        margin: 'var(--space-3) 0',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <AlertCircle size={16} />
        <span>{message}</span>
      </div>
      {onRetry && (
        <button
          type="button"
          className="btn btn-secondary"
          onClick={onRetry}
          style={{ fontSize: '11px', padding: '2px 8px' }}
        >
          Retry
        </button>
      )}
    </div>
  );
};
