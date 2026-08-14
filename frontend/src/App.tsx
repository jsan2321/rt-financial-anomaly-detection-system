import React, { useCallback, useEffect, useState } from 'react';
import { Layout } from './components/layout/Layout';
import { DashboardPage } from './pages/DashboardPage';
import { AlertsPage } from './pages/AlertsPage';
import { SettingsPage } from './pages/SettingsPage';
import { useWebSocket } from './hooks/useWebSocket';
import { api } from './services/api';
import { Alert, WebSocketMessage } from './types';

// Seed initial synthetic alerts for immediate visualization in dev mode
const INITIAL_DEMO_ALERTS: Alert[] = [
  {
    id: 'a1b2c3d4-e5f6-7890-abcd-1234567890ab',
    transaction_id: 'tx-high-risk-country-001',
    status: 'PENDING',
    severity: 'CRITICAL',
    composite_risk_score: 0.92,
    rule_severity_score: 1.0,
    ml_anomaly_score: 0.88,
    user_risk_score: 0.75,
    matched_rules: [
      {
        rule_id: 'rule-high-risk-country',
        rule_name: 'High Risk Jurisdiction',
        severity: 'CRITICAL',
        explanation: 'Transaction originating from high-risk OFAC embargoed jurisdiction (RU).',
      },
      {
        rule_id: 'rule-amount-threshold',
        rule_name: 'Large Transfer Velocity',
        severity: 'HIGH',
        explanation: 'Amount $48,500.00 exceeds standard user velocity by 480%.',
      },
    ],
    is_demo: true,
    correlation_id: 'corr-001',
    created_at: new Date(Date.now() - 4 * 60 * 1000).toISOString(),
    updated_at: new Date(Date.now() - 4 * 60 * 1000).toISOString(),
  },
  {
    id: 'f8e7d6c5-b4a3-2109-8765-43210fedcba9',
    transaction_id: 'tx-velocity-spike-002',
    status: 'ESCALATED_EMAIL',
    severity: 'HIGH',
    composite_risk_score: 0.78,
    rule_severity_score: 0.8,
    ml_anomaly_score: 0.74,
    user_risk_score: 0.60,
    matched_rules: [
      {
        rule_id: 'rule-velocity-threshold',
        rule_name: 'Rapid Transaction Burst',
        severity: 'HIGH',
        explanation: '5 distinct transactions completed within a 60-second window.',
      },
    ],
    is_demo: false,
    escalated_email_at: new Date(Date.now() - 10 * 60 * 1000).toISOString(),
    correlation_id: 'corr-002',
    created_at: new Date(Date.now() - 15 * 60 * 1000).toISOString(),
    updated_at: new Date(Date.now() - 10 * 60 * 1000).toISOString(),
  },
  {
    id: 'c9d8e7f6-a5b4-3210-9876-543210abcdef',
    transaction_id: 'tx-anomaly-ml-003',
    status: 'PENDING',
    severity: 'MEDIUM',
    composite_risk_score: 0.58,
    rule_severity_score: 0.0,
    ml_anomaly_score: 0.72,
    user_risk_score: 0.35,
    matched_rules: [],
    is_demo: false,
    correlation_id: 'corr-003',
    created_at: new Date(Date.now() - 25 * 60 * 1000).toISOString(),
    updated_at: new Date(Date.now() - 25 * 60 * 1000).toISOString(),
  },
  {
    id: 'e4d3c2b1-a098-7654-3210-fedcba987654',
    transaction_id: 'tx-resolved-approved-004',
    status: 'APPROVED',
    severity: 'LOW',
    composite_risk_score: 0.24,
    rule_severity_score: 0.0,
    ml_anomaly_score: 0.31,
    user_risk_score: 0.10,
    matched_rules: [],
    is_demo: false,
    resolved_by: 'lead_analyst',
    resolved_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
    resolution_reason: 'Verified with cardholder over telephone',
    correlation_id: 'corr-004',
    created_at: new Date(Date.now() - 65 * 60 * 1000).toISOString(),
    updated_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
  },
];

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState('dashboard');
  const [alerts, setAlerts] = useState<Alert[]>(INITIAL_DEMO_ALERTS);
  const [selectedAlert, setSelectedAlert] = useState<Alert | null>(null);

  // REST Reconciliation function
  const reconcileAlerts = useCallback(async () => {
    try {
      const response = await api.getAlerts({ pageSize: 50 });
      if (response && response.items && response.items.length > 0) {
        setAlerts((prev) => {
          const map = new Map(prev.map((a) => [a.id, a]));
          for (const item of response.items) {
            map.set(item.id, item);
          }
          return Array.from(map.values()).sort(
            (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
          );
        });
      }
    } catch {
      // Backend not running yet; continue with local cached state
    }
  }, []);

  // Initial load sync
  useEffect(() => {
    reconcileAlerts();
  }, [reconcileAlerts]);

  // WebSocket Message Handler
  const handleWsMessage = useCallback((msg: WebSocketMessage) => {
    if (msg.type === 'alert.created' && msg.alert) {
      const newAlert: Alert = {
        id: msg.alert.id,
        transaction_id: msg.alert.transaction_id,
        status: msg.alert.status,
        severity: msg.alert.severity,
        composite_risk_score: msg.alert.composite_risk_score,
        rule_severity_score: 0.5,
        ml_anomaly_score: 0.5,
        user_risk_score: 0.2,
        matched_rules: [],
        is_demo: false,
        correlation_id: 'ws-stream',
        created_at: msg.alert.created_at || new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };

      setAlerts((prev) => [newAlert, ...prev.filter((a) => a.id !== newAlert.id)]);
    } else if (msg.type === 'alert.updated' && msg.alert) {
      setAlerts((prev) =>
        prev.map((a) =>
          a.id === msg.alert?.id
            ? { ...a, status: msg.alert.status, resolved_at: msg.alert.resolved_at || new Date().toISOString() }
            : a
        )
      );
      setSelectedAlert((prev) =>
        prev && prev.id === msg.alert?.id
          ? { ...prev, status: msg.alert.status, resolved_at: msg.alert.resolved_at || new Date().toISOString() }
          : prev
      );
    } else if (msg.type === 'escalation' && msg.alert_id) {
      setAlerts((prev) =>
        prev.map((a) =>
          a.id === msg.alert_id
            ? {
                ...a,
                status: msg.escalation_level === 'email' ? 'ESCALATED_EMAIL' : 'ESCALATED_SLACK',
                [msg.escalation_level === 'email' ? 'escalated_email_at' : 'escalated_slack_at']: new Date().toISOString(),
              }
            : a
        )
      );
    }
  }, []);

  const { connectionState } = useWebSocket({
    onMessage: handleWsMessage,
    onReconnected: reconcileAlerts,
  });

  // Action Handlers
  const handleApproveAlert = async (alertId: string, reason?: string) => {
    try {
      await api.approveAlert(alertId, reason);
    } catch {
      // Local fallback for offline mode
    }

    setAlerts((prev) =>
      prev.map((a) =>
        a.id === alertId
          ? {
              ...a,
              status: 'APPROVED',
              resolved_by: 'analyst_ui',
              resolved_at: new Date().toISOString(),
              resolution_reason: reason || 'Approved as legitimate',
            }
          : a
      )
    );

    setSelectedAlert((prev) =>
      prev && prev.id === alertId
        ? {
            ...prev,
            status: 'APPROVED',
            resolved_by: 'analyst_ui',
            resolved_at: new Date().toISOString(),
            resolution_reason: reason || 'Approved as legitimate',
          }
        : prev
    );
  };

  const handleBlockAlert = async (alertId: string, reason?: string) => {
    try {
      await api.blockAlert(alertId, reason);
    } catch {
      // Local fallback for offline mode
    }

    setAlerts((prev) =>
      prev.map((a) =>
        a.id === alertId
          ? {
              ...a,
              status: 'BLOCKED',
              resolved_by: 'analyst_ui',
              resolved_at: new Date().toISOString(),
              resolution_reason: reason || 'Confirmed fraudulent transaction',
            }
          : a
      )
    );

    setSelectedAlert((prev) =>
      prev && prev.id === alertId
        ? {
            ...prev,
            status: 'BLOCKED',
            resolved_by: 'analyst_ui',
            resolved_at: new Date().toISOString(),
            resolution_reason: reason || 'Confirmed fraudulent transaction',
          }
        : prev
    );
  };

  const handleFalsePositiveAlert = async (alertId: string, reason?: string) => {
    try {
      await api.markFalsePositive(alertId, reason);
    } catch {
      // Local fallback for offline mode
    }

    setAlerts((prev) =>
      prev.map((a) =>
        a.id === alertId
          ? {
              ...a,
              status: 'FALSE_POSITIVE',
              resolved_by: 'analyst_ui',
              resolved_at: new Date().toISOString(),
              resolution_reason: reason || 'Compensated false positive alert',
            }
          : a
      )
    );

    setSelectedAlert((prev) =>
      prev && prev.id === alertId
        ? {
            ...prev,
            status: 'FALSE_POSITIVE',
            resolved_by: 'analyst_ui',
            resolved_at: new Date().toISOString(),
            resolution_reason: reason || 'Compensated false positive alert',
          }
        : prev
    );
  };

  const getPageTitle = () => {
    switch (currentTab) {
      case 'dashboard':
        return { title: 'Surveillance Operations', subtitle: 'Real-time financial telemetry & threat monitoring' };
      case 'alerts':
        return { title: 'Alert Center', subtitle: 'Analyst triage workspace and anomaly investigations' };
      case 'settings':
        return { title: 'Console Settings', subtitle: 'Interface appearance & telemetry parameters' };
      default:
        return { title: 'Surveillance Operations' };
    }
  };

  const headerInfo = getPageTitle();

  return (
    <Layout
      currentTab={currentTab}
      onSelectTab={(tab) => {
        setCurrentTab(tab);
        if (tab !== 'alerts') setSelectedAlert(null);
      }}
      connectionState={connectionState}
      title={headerInfo.title}
      subtitle={headerInfo.subtitle}
    >
      {currentTab === 'dashboard' && (
        <DashboardPage
          alerts={alerts}
          onSelectAlert={(a) => {
            setSelectedAlert(a);
            setCurrentTab('alerts');
          }}
          onNavigateToAlerts={() => setCurrentTab('alerts')}
        />
      )}
      {currentTab === 'alerts' && (
        <AlertsPage
          alerts={alerts}
          selectedAlert={selectedAlert}
          onSelectAlert={setSelectedAlert}
          onApproveAlert={handleApproveAlert}
          onBlockAlert={handleBlockAlert}
          onFalsePositiveAlert={handleFalsePositiveAlert}
        />
      )}
      {currentTab === 'settings' && <SettingsPage />}
    </Layout>
  );
};
