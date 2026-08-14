import React, { useMemo, useState } from 'react';
import { AlertFilters } from '../components/alerts/AlertFilters';
import { AlertTable } from '../components/alerts/AlertTable';
import { AlertDetailPanel } from '../components/alerts/AlertDetailPanel';
import { EmptyState } from '../components/common/FeedbackStates';
import { Alert, AlertSeverity, AlertStatus } from '../types';

interface AlertsPageProps {
  alerts: Alert[];
  selectedAlert: Alert | null;
  onSelectAlert: (alert: Alert | null) => void;
  onApproveAlert: (alertId: string, reason?: string) => Promise<void>;
  onBlockAlert: (alertId: string, reason?: string) => Promise<void>;
  onFalsePositiveAlert: (alertId: string, reason?: string) => Promise<void>;
}

export const AlertsPage: React.FC<AlertsPageProps> = ({
  alerts,
  selectedAlert,
  onSelectAlert,
  onApproveAlert,
  onBlockAlert,
  onFalsePositiveAlert,
}) => {
  const [statusFilter, setStatusFilter] = useState<AlertStatus | 'ALL'>('ALL');
  const [severityFilter, setSeverityFilter] = useState<AlertSeverity | 'ALL'>('ALL');
  const [searchQuery, setSearchQuery] = useState('');

  const filteredAlerts = useMemo(() => {
    return alerts.filter((alert) => {
      if (statusFilter !== 'ALL' && alert.status !== statusFilter) {
        return false;
      }
      if (severityFilter !== 'ALL' && alert.severity !== severityFilter) {
        return false;
      }
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase();
        const matchId = alert.id.toLowerCase().includes(query);
        const matchTxn = alert.transaction_id.toLowerCase().includes(query);
        if (!matchId && !matchTxn) return false;
      }
      return true;
    });
  }, [alerts, statusFilter, severityFilter, searchQuery]);

  return (
    <div>
      <AlertFilters
        status={statusFilter}
        severity={severityFilter}
        search={searchQuery}
        onStatusChange={setStatusFilter}
        onSeverityChange={setSeverityFilter}
        onSearchChange={setSearchQuery}
      />

      {filteredAlerts.length > 0 ? (
        <AlertTable
          alerts={filteredAlerts}
          selectedAlertId={selectedAlert?.id}
          onSelectAlert={(a) => onSelectAlert(a)}
        />
      ) : (
        <div className="card">
          <EmptyState
            title="No Alerts Found"
            description="No anomaly alerts match your current status or severity filters."
            action={
              (statusFilter !== 'ALL' || severityFilter !== 'ALL' || searchQuery) ? (
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    setStatusFilter('ALL');
                    setSeverityFilter('ALL');
                    setSearchQuery('');
                  }}
                >
                  Reset Filters
                </button>
              ) : undefined
            }
          />
        </div>
      )}

      {/* Slide-over Alert Inspector */}
      {selectedAlert && (
        <AlertDetailPanel
          alert={selectedAlert}
          onClose={() => onSelectAlert(null)}
          onApprove={onApproveAlert}
          onBlock={onBlockAlert}
          onFalsePositive={onFalsePositiveAlert}
        />
      )}
    </div>
  );
};
