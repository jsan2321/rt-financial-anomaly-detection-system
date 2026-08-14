import React from 'react';
import { Alert } from '../../types';
import { RiskChip } from '../common/RiskChip';
import { DemoBadge } from '../common/DemoBadge';

interface AlertTableProps {
  alerts: Alert[];
  selectedAlertId?: string | null;
  onSelectAlert: (alert: Alert) => void;
}

export const AlertTable: React.FC<AlertTableProps> = ({
  alerts,
  selectedAlertId,
  onSelectAlert,
}) => {
  const formatTime = (isoString: string) => {
    try {
      const date = new Date(isoString);
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return isoString;
    }
  };

  const getStatusBadge = (status: string) => {
    const isPending = status === 'PENDING';
    const isEscalated = status.startsWith('ESCALATED');
    const isApproved = status === 'APPROVED';
    const isBlocked = status === 'BLOCKED';
    const isFP = status === 'FALSE_POSITIVE';

    let color = 'var(--color-text-secondary)';
    let bg = 'var(--color-surface-subtle)';

    if (isPending) {
      color = 'var(--color-warning)';
      bg = 'rgba(245, 158, 11, 0.1)';
    } else if (isEscalated) {
      color = 'var(--color-escalation)';
      bg = 'var(--color-escalation-bg)';
    } else if (isApproved) {
      color = 'var(--color-success)';
      bg = 'rgba(34, 197, 94, 0.1)';
    } else if (isBlocked) {
      color = 'var(--color-danger)';
      bg = 'var(--color-risk-critical-bg)';
    } else if (isFP) {
      color = 'var(--color-info)';
      bg = 'rgba(56, 189, 248, 0.1)';
    }

    return (
      <span
        style={{
          display: 'inline-block',
          padding: '2px 6px',
          borderRadius: 'var(--radius-sm)',
          fontSize: '11px',
          fontWeight: 600,
          color,
          backgroundColor: bg,
          textTransform: 'capitalize',
        }}
      >
        {status.replace('_', ' ').toLowerCase()}
      </span>
    );
  };

  return (
    <div
      className="card"
      style={{
        overflowX: 'auto',
        width: '100%',
      }}
    >
      <table
        style={{
          width: '100%',
          borderCollapse: 'collapse',
          textAlign: 'left',
          fontSize: '12px',
        }}
      >
        <thead>
          <tr
            style={{
              borderBottom: '1px solid var(--color-border)',
              backgroundColor: 'var(--color-surface-subtle)',
            }}
          >
            <th className="label-caps" style={{ padding: '8px 12px' }}>
              Severity
            </th>
            <th className="label-caps" style={{ padding: '8px 12px' }}>
              Alert ID
            </th>
            <th className="label-caps" style={{ padding: '8px 12px' }}>
              Transaction ID
            </th>
            <th className="label-caps" style={{ padding: '8px 12px' }}>
              Risk Score
            </th>
            <th className="label-caps" style={{ padding: '8px 12px' }}>
              Status
            </th>
            <th className="label-caps" style={{ padding: '8px 12px' }}>
              Mode
            </th>
            <th className="label-caps" style={{ padding: '8px 12px', textAlign: 'right' }}>
              Time (UTC)
            </th>
          </tr>
        </thead>
        <tbody>
          {alerts.map((alert) => {
            const isSelected = selectedAlertId === alert.id;
            return (
              <tr
                key={alert.id}
                onClick={() => onSelectAlert(alert)}
                style={{
                  height: '38px',
                  borderBottom: '1px solid var(--color-border-subtle)',
                  cursor: 'pointer',
                  backgroundColor: isSelected
                    ? 'var(--color-surface-subtle)'
                    : 'transparent',
                  transition: 'background-color 0.1s ease',
                }}
                onMouseEnter={(e) => {
                  if (!isSelected) {
                    e.currentTarget.style.backgroundColor = 'var(--color-surface-subtle)';
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isSelected) {
                    e.currentTarget.style.backgroundColor = 'transparent';
                  }
                }}
              >
                <td style={{ padding: '6px 12px' }}>
                  <RiskChip severity={alert.severity} size="sm" />
                </td>
                <td className="technical-data" style={{ padding: '6px 12px', color: 'var(--color-primary)' }}>
                  {alert.id.substring(0, 8)}...
                </td>
                <td className="technical-data" style={{ padding: '6px 12px', color: 'var(--color-text-secondary)' }}>
                  {alert.transaction_id.substring(0, 8)}...
                </td>
                <td className="technical-data" style={{ padding: '6px 12px', fontWeight: 600 }}>
                  {alert.composite_risk_score.toFixed(2)}
                </td>
                <td style={{ padding: '6px 12px' }}>{getStatusBadge(alert.status)}</td>
                <td style={{ padding: '6px 12px' }}>
                  {alert.is_demo ? <DemoBadge size="sm" /> : <span style={{ color: 'var(--color-text-muted)', fontSize: '11px' }}>Organic</span>}
                </td>
                <td
                  className="technical-data"
                  style={{
                    padding: '6px 12px',
                    textAlign: 'right',
                    color: 'var(--color-text-muted)',
                  }}
                >
                  {formatTime(alert.created_at)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
