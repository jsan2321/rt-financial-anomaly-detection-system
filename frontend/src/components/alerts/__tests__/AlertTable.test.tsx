import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { AlertTable } from '../AlertTable';
import { Alert } from '../../../types';

const mockAlerts: Alert[] = [
  {
    id: '11111111-2222-3333-4444-555555555555',
    transaction_id: 'tx-alpha-001',
    status: 'PENDING',
    severity: 'CRITICAL',
    composite_risk_score: 0.95,
    rule_severity_score: 1.0,
    ml_anomaly_score: 0.9,
    user_risk_score: 0.8,
    matched_rules: [],
    is_demo: true,
    correlation_id: 'corr-1',
    created_at: '2026-08-14T00:00:00.000Z',
    updated_at: '2026-08-14T00:00:00.000Z',
  },
  {
    id: '22222222-3333-4444-5555-666666666666',
    transaction_id: 'tx-bravo-002',
    status: 'APPROVED',
    severity: 'LOW',
    composite_risk_score: 0.15,
    rule_severity_score: 0.0,
    ml_anomaly_score: 0.2,
    user_risk_score: 0.1,
    matched_rules: [],
    is_demo: false,
    correlation_id: 'corr-2',
    created_at: '2026-08-14T00:05:00.000Z',
    updated_at: '2026-08-14T00:05:00.000Z',
  },
];


describe('AlertTable Component', () => {
  it('renders alert rows with truncated monospaced IDs and risk chips', () => {
    const handleSelect = vi.fn();
    render(
      <AlertTable
        alerts={mockAlerts}
        onSelectAlert={handleSelect}
      />
    );

    expect(screen.getByText('11111111...')).toBeInTheDocument();
    expect(screen.getByText('tx-alpha...')).toBeInTheDocument();
    expect(screen.getByText('0.95')).toBeInTheDocument();
    expect(screen.getByText('DEMO')).toBeInTheDocument();
    expect(screen.getByText('Organic')).toBeInTheDocument();


  });

  it('triggers onSelectAlert when a row is clicked', () => {
    const handleSelect = vi.fn();
    render(
      <AlertTable
        alerts={mockAlerts}
        onSelectAlert={handleSelect}
      />
    );

    const firstRow = screen.getByText('11111111...').closest('tr');
    expect(firstRow).not.toBeNull();
    if (firstRow) {
      fireEvent.click(firstRow);
      expect(handleSelect).toHaveBeenCalledWith(mockAlerts[0]);
    }
  });
});
