import React, { useState } from 'react';
import { X, Check, Ban, RotateCcw, Shield } from 'lucide-react';

import { Alert } from '../../types';
import { RiskChip } from '../common/RiskChip';
import { DemoBadge } from '../common/DemoBadge';

interface AlertDetailPanelProps {
  alert: Alert | null;
  onClose: () => void;
  onApprove: (alertId: string, reason?: string) => Promise<void>;
  onBlock: (alertId: string, reason?: string) => Promise<void>;
  onFalsePositive: (alertId: string, reason?: string) => Promise<void>;
}

export const AlertDetailPanel: React.FC<AlertDetailPanelProps> = ({
  alert,
  onClose,
  onApprove,
  onBlock,
  onFalsePositive,
}) => {
  const [resolutionReason, setResolutionReason] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  if (!alert) return null;

  const isTerminal =
    alert.status === 'APPROVED' ||
    alert.status === 'BLOCKED' ||
    alert.status === 'FALSE_POSITIVE';

  const handleAction = async (actionFn: (id: string, reason?: string) => Promise<void>) => {
    setIsSubmitting(true);
    setActionError(null);
    try {
      await actionFn(alert.id, resolutionReason.trim() || undefined);
      setResolutionReason('');
    } catch (err: any) {
      setActionError(err.message || 'Action failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        right: 0,
        bottom: 0,
        width: 'var(--inspector-width)',
        backgroundColor: 'var(--color-surface)',
        borderLeft: '1px solid var(--color-border)',
        boxShadow: 'var(--shadow-lg)',
        zIndex: 50,
        display: 'flex',
        flexDirection: 'column',
        overflowY: 'auto',
      }}
    >
      {/* Inspector Header */}
      <div
        style={{
          padding: 'var(--space-4)',
          borderBottom: '1px solid var(--color-border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <RiskChip severity={alert.severity} />
          {alert.is_demo && <DemoBadge />}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close detail panel"
          style={{
            border: 'none',
            background: 'transparent',
            color: 'var(--color-text-muted)',
            cursor: 'pointer',
            padding: '4px',
          }}
        >
          <X size={18} />
        </button>
      </div>

      <div style={{ padding: 'var(--space-5)', flex: 1, display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
        {/* IDs & Core Metadata */}
        <div>
          <span className="label-caps">Alert Identifier</span>
          <p className="technical-data" style={{ fontSize: '13px', color: 'var(--color-primary)', marginTop: '2px' }}>
            {alert.id}
          </p>
          <div style={{ display: 'flex', gap: '12px', marginTop: '6px' }}>
            <div>
              <span className="label-caps">Txn ID:</span>{' '}
              <span className="technical-data" style={{ color: 'var(--color-text-secondary)' }}>
                {alert.transaction_id.substring(0, 8)}...
              </span>
            </div>
            <div>
              <span className="label-caps">Status:</span>{' '}
              <span className="technical-data" style={{ fontWeight: 600 }}>
                {alert.status}
              </span>
            </div>
          </div>
        </div>

        {/* Composite Score Breakdown */}
        <div className="card" style={{ padding: 'var(--space-4)', backgroundColor: 'var(--color-surface-subtle)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span className="label-caps" style={{ color: 'var(--color-text)' }}>
              Composite Risk Score
            </span>
            <span className="technical-data" style={{ fontSize: '18px', fontWeight: 700, color: 'var(--color-risk-critical)' }}>
              {alert.composite_risk_score.toFixed(2)} / 1.00
            </span>
          </div>

          {/* Component Score Progress Bars */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '11px' }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--color-text-muted)' }}>
                <span>Deterministic Rules (w=0.5)</span>
                <span className="technical-data">{(alert.rule_severity_score || 0).toFixed(2)}</span>
              </div>
              <div style={{ height: '4px', backgroundColor: 'var(--color-border)', borderRadius: '2px', overflow: 'hidden', marginTop: '2px' }}>
                <div style={{ width: `${(alert.rule_severity_score || 0) * 100}%`, height: '100%', backgroundColor: 'var(--color-risk-high)' }} />
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--color-text-muted)' }}>
                <span>ML Isolation Forest (w=0.3)</span>
                <span className="technical-data">{(alert.ml_anomaly_score || 0).toFixed(2)}</span>
              </div>
              <div style={{ height: '4px', backgroundColor: 'var(--color-border)', borderRadius: '2px', overflow: 'hidden', marginTop: '2px' }}>
                <div style={{ width: `${(alert.ml_anomaly_score || 0) * 100}%`, height: '100%', backgroundColor: 'var(--color-primary)' }} />
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--color-text-muted)' }}>
                <span>User Profile Risk (w=0.2)</span>
                <span className="technical-data">{(alert.user_risk_score || 0).toFixed(2)}</span>
              </div>
              <div style={{ height: '4px', backgroundColor: 'var(--color-border)', borderRadius: '2px', overflow: 'hidden', marginTop: '2px' }}>
                <div style={{ width: `${(alert.user_risk_score || 0) * 100}%`, height: '100%', backgroundColor: 'var(--color-info)' }} />
              </div>
            </div>
          </div>
        </div>

        {/* Matched Fraud Rules */}
        <div>
          <h4 className="headline-sm" style={{ fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
            <Shield size={14} style={{ color: 'var(--color-risk-high)' }} />
            <span>Matched Fraud Rules ({alert.matched_rules?.length || 0})</span>
          </h4>

          {alert.matched_rules && alert.matched_rules.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {alert.matched_rules.map((rule, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: '8px 10px',
                    backgroundColor: 'var(--color-surface-subtle)',
                    borderRadius: 'var(--radius-default)',
                    border: '1px solid var(--color-border)',
                    fontSize: '12px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '2px' }}>
                    <span style={{ fontWeight: 600 }}>{rule.rule_name}</span>
                    <RiskChip severity={rule.severity} size="sm" />
                  </div>
                  <p className="body-sm" style={{ color: 'var(--color-text-secondary)', fontSize: '11px' }}>
                    {rule.explanation}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <p className="body-sm" style={{ color: 'var(--color-text-muted)' }}>
              No deterministic rules triggered. Detected via ML anomaly scoring threshold.
            </p>
          )}
        </div>

        {/* Action Controls or Resolution Summary */}
        <div style={{ marginTop: 'auto', paddingTop: 'var(--space-4)', borderTop: '1px solid var(--color-border)' }}>
          {actionError && (
            <div style={{ color: 'var(--color-danger)', fontSize: '12px', marginBottom: '8px' }}>
              {actionError}
            </div>
          )}

          {isTerminal ? (
            <div
              style={{
                padding: 'var(--space-3)',
                backgroundColor: 'var(--color-surface-subtle)',
                borderRadius: 'var(--radius-default)',
                fontSize: '12px',
              }}
            >
              <span className="label-caps">Resolution Status</span>
              <p style={{ fontWeight: 600, marginTop: '2px' }}>
                Resolved as {alert.status}
              </p>
              {alert.resolved_by && (
                <p className="body-sm" style={{ color: 'var(--color-text-muted)', marginTop: '2px' }}>
                  By: {alert.resolved_by} {alert.resolved_at && `at ${new Date(alert.resolved_at).toLocaleTimeString()}`}
                </p>
              )}
              {alert.resolution_reason && (
                <p className="body-sm" style={{ fontStyle: 'italic', marginTop: '4px' }}>
                  "{alert.resolution_reason}"
                </p>
              )}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <input
                type="text"
                value={resolutionReason}
                onChange={(e) => setResolutionReason(e.target.value)}
                placeholder="Resolution reason (optional)..."
                className="input-control"
                style={{ fontSize: '12px', width: '100%' }}
                disabled={isSubmitting}
              />

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => handleAction(onApprove)}
                  disabled={isSubmitting}
                  style={{ backgroundColor: 'var(--color-success)', borderColor: 'var(--color-success)' }}
                >
                  <Check size={14} />
                  <span>Approve</span>
                </button>
                <button
                  type="button"
                  className="btn btn-danger"
                  onClick={() => handleAction(onBlock)}
                  disabled={isSubmitting}
                >
                  <Ban size={14} />
                  <span>Block Fraud</span>
                </button>
              </div>

              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => handleAction(onFalsePositive)}
                disabled={isSubmitting}
                style={{ width: '100%' }}
              >
                <RotateCcw size={14} />
                <span>Mark False Positive</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
