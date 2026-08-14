import React from 'react';
import { ShieldAlert, AlertTriangle, Activity, CheckCircle2 } from 'lucide-react';
import { StatCard } from '../common/StatCard';
import { Alert } from '../../types';

interface StatCardsGridProps {
  alerts: Alert[];
  totalTransactions?: number;
}

export const StatCardsGrid: React.FC<StatCardsGridProps> = ({
  alerts,
  totalTransactions = 12450,
}) => {
  const pendingCount = alerts.filter(
    (a) => a.status === 'PENDING' || a.status === 'ESCALATED_EMAIL' || a.status === 'ESCALATED_SLACK'
  ).length;

  const criticalCount = alerts.filter(
    (a) => a.severity === 'CRITICAL' && a.status !== 'APPROVED' && a.status !== 'FALSE_POSITIVE'
  ).length;

  const falsePositiveCount = alerts.filter((a) => a.status === 'FALSE_POSITIVE').length;
  const resolvedCount = alerts.filter(
    (a) => a.status === 'APPROVED' || a.status === 'BLOCKED' || a.status === 'FALSE_POSITIVE'
  ).length;

  const fpRate = resolvedCount > 0 ? ((falsePositiveCount / resolvedCount) * 100).toFixed(1) : '0.0';

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
        gap: 'var(--space-4)',
        marginBottom: 'var(--space-6)',
      }}
    >
      <StatCard
        title="Pending Triage"
        value={pendingCount}
        subtext="Requires analyst review"
        icon={<ShieldAlert size={18} />}
        accentColor="var(--color-primary)"
        trend={{ value: `${pendingCount} active`, isPositive: pendingCount === 0, isNeutral: pendingCount > 0 }}
      />
      <StatCard
        title="Critical Threats"
        value={criticalCount}
        subtext="High anomaly / rule breaches"
        icon={<AlertTriangle size={18} />}
        accentColor="var(--color-risk-critical)"
        trend={{ value: criticalCount > 0 ? 'Urgent Action' : 'Clear', isPositive: criticalCount === 0 }}
      />
      <StatCard
        title="Transactions Monitored"
        value={totalTransactions.toLocaleString()}
        subtext="Continuous 5m aggregate stream"
        icon={<Activity size={18} />}
        accentColor="var(--color-info)"
        trend={{ value: '+4.2% vol', isPositive: true }}
      />
      <StatCard
        title="False Positive Rate"
        value={`${fpRate}%`}
        subtext="Compensating feedback loop"
        icon={<CheckCircle2 size={18} />}
        accentColor="var(--color-success)"
        trend={{ value: 'Target < 5%', isPositive: parseFloat(fpRate) < 5 }}
      />
    </div>
  );
};
