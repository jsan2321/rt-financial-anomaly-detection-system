import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { StatCardsGrid } from '../StatCardsGrid';
import { Alert } from '../../../types';

const mockAlerts: Alert[] = [
  {
    id: '1',
    transaction_id: 't-1',
    status: 'PENDING',
    severity: 'CRITICAL',
    composite_risk_score: 0.95,
    rule_severity_score: 0.9,
    ml_anomaly_score: 0.8,
    user_risk_score: 0.1,
    matched_rules: [],
    is_demo: false,
    correlation_id: 'c-1',
    created_at: '2026-08-14T10:00:00Z',
    updated_at: '2026-08-14T10:00:00Z',
  },
  {
    id: '2',
    transaction_id: 't-2',
    status: 'FALSE_POSITIVE',
    severity: 'MEDIUM',
    composite_risk_score: 0.55,
    rule_severity_score: 0.4,
    ml_anomaly_score: 0.6,
    user_risk_score: 0.2,
    matched_rules: [],
    is_demo: false,
    correlation_id: 'c-2',
    created_at: '2026-08-14T11:00:00Z',
    updated_at: '2026-08-14T11:00:00Z',
  },
  {
    id: '3',
    transaction_id: 't-3',
    status: 'APPROVED',
    severity: 'LOW',
    composite_risk_score: 0.25,
    rule_severity_score: 0.1,
    ml_anomaly_score: 0.2,
    user_risk_score: 0.1,
    matched_rules: [],
    is_demo: false,
    correlation_id: 'c-3',
    created_at: '2026-08-14T11:30:00Z',
    updated_at: '2026-08-14T11:30:00Z',
  },
];

describe('StatCardsGrid Component', () => {
  it('renders all four key metric tiles with calculated statistics', () => {
    render(<StatCardsGrid alerts={mockAlerts} totalTransactions={50000} />);

    // 1. Pending Triage & Critical Threats titles
    expect(screen.getByText('Pending Triage')).toBeInTheDocument();
    expect(screen.getByText('Critical Threats')).toBeInTheDocument();

    // 2. Counts
    const ones = screen.getAllByText('1');
    expect(ones.length).toBeGreaterThanOrEqual(2);

    // 3. Transactions Monitored (50,000)
    expect(screen.getByText('Transactions Monitored')).toBeInTheDocument();
    expect(screen.getByText('50,000')).toBeInTheDocument();

    // 4. False Positive Rate (1 FP out of 2 resolved = 50.0%)
    expect(screen.getByText('False Positive Rate')).toBeInTheDocument();
    expect(screen.getByText('50.0%')).toBeInTheDocument();
  });

  it('handles empty alerts array gracefully with 0.0% FP rate and 0 counts', () => {
    render(<StatCardsGrid alerts={[]} totalTransactions={100} />);

    expect(screen.getByText('0.0%')).toBeInTheDocument();
    expect(screen.getByText('100')).toBeInTheDocument();
  });
});
