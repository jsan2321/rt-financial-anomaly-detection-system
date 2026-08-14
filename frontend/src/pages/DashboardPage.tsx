import React from 'react';
import { StatCardsGrid } from '../components/dashboard/StatCardsGrid';
import { VolumeChart } from '../components/dashboard/VolumeChart';
import { AlertTable } from '../components/alerts/AlertTable';
import { Alert } from '../types';
import { ArrowRight, ShieldAlert } from 'lucide-react';

interface DashboardPageProps {
  alerts: Alert[];
  onSelectAlert: (alert: Alert) => void;
  onNavigateToAlerts: () => void;
}

export const DashboardPage: React.FC<DashboardPageProps> = ({
  alerts,
  onSelectAlert,
  onNavigateToAlerts,
}) => {
  const recentAlerts = alerts.slice(0, 5);

  return (
    <div>
      {/* Real-time Summary Cards */}
      <StatCardsGrid alerts={alerts} />

      {/* Volume & Anomaly Throughput Chart */}
      <VolumeChart />

      {/* Recent Alerts Feed */}
      <div className="card" style={{ padding: 'var(--space-5)' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 'var(--space-4)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ShieldAlert size={18} style={{ color: 'var(--color-primary)' }} />
            <h3 className="headline-sm">Live Anomaly Stream</h3>
          </div>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onNavigateToAlerts}
            style={{ fontSize: '12px' }}
          >
            <span>View All in Alert Center</span>
            <ArrowRight size={14} />
          </button>
        </div>

        {recentAlerts.length > 0 ? (
          <AlertTable
            alerts={recentAlerts}
            onSelectAlert={onSelectAlert}
          />
        ) : (
          <p className="body-sm" style={{ color: 'var(--color-text-muted)', textAlign: 'center', padding: 'var(--space-4)' }}>
            No anomaly alerts recorded. Feed is awaiting transaction stream activity.
          </p>
        )}
      </div>
    </div>
  );
};
