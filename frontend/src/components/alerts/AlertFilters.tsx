import React from 'react';
import { Filter, Search } from 'lucide-react';
import { AlertSeverity, AlertStatus } from '../../types';

interface AlertFiltersProps {
  status: AlertStatus | 'ALL';
  severity: AlertSeverity | 'ALL';
  search: string;
  onStatusChange: (status: AlertStatus | 'ALL') => void;
  onSeverityChange: (severity: AlertSeverity | 'ALL') => void;
  onSearchChange: (search: string) => void;
}

export const AlertFilters: React.FC<AlertFiltersProps> = ({
  status,
  severity,
  search,
  onStatusChange,
  onSeverityChange,
  onSearchChange,
}) => {
  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 'var(--space-3)',
        marginBottom: 'var(--space-4)',
        padding: 'var(--space-3) var(--space-4)',
        backgroundColor: 'var(--color-surface)',
        borderRadius: 'var(--radius-default)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 'var(--space-3)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-text-muted)' }}>
          <Filter size={14} />
          <span className="label-caps">Filters:</span>
        </div>

        {/* Status Filter */}
        <select
          value={status}
          onChange={(e) => onStatusChange(e.target.value as AlertStatus | 'ALL')}
          className="input-control"
          style={{ fontSize: '12px', padding: '4px 8px', fontWeight: 500 }}
          aria-label="Filter by alert status"
        >
          <option value="ALL">All Statuses</option>
          <option value="PENDING">Pending Triage</option>
          <option value="ESCALATED_EMAIL">Escalated (Email)</option>
          <option value="ESCALATED_SLACK">Escalated (Slack)</option>
          <option value="APPROVED">Approved (Legitimate)</option>
          <option value="BLOCKED">Blocked (Fraud)</option>
          <option value="FALSE_POSITIVE">False Positive</option>
        </select>

        {/* Severity Filter */}
        <select
          value={severity}
          onChange={(e) => onSeverityChange(e.target.value as AlertSeverity | 'ALL')}
          className="input-control"
          style={{ fontSize: '12px', padding: '4px 8px', fontWeight: 500 }}
          aria-label="Filter by alert severity"
        >
          <option value="ALL">All Severities</option>
          <option value="CRITICAL">Critical</option>
          <option value="HIGH">High</option>
          <option value="MEDIUM">Medium</option>
          <option value="LOW">Low</option>
        </select>
      </div>

      {/* Search Filter */}
      <div style={{ position: 'relative', minWidth: '220px' }}>
        <Search
          size={14}
          style={{
            position: 'absolute',
            left: '8px',
            top: '50%',
            transform: 'translateY(-50%)',
            color: 'var(--color-text-muted)',
          }}
        />
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search by ID, User, Txn..."
          className="input-control"
          style={{
            width: '100%',
            paddingLeft: '28px',
            fontSize: '12px',
            height: '30px',
          }}
          aria-label="Search alerts"
        />
      </div>
    </div>
  );
};
