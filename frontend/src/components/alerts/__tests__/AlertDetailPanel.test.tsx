import { act } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { AlertDetailPanel } from '../AlertDetailPanel';
import { Alert } from '../../../types';

const mockAlert: Alert = {
  id: 'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d',
  transaction_id: 't1u2v3w4-x5y6-7z8a-9b0c-1d2e3f4a5b6c',
  status: 'PENDING',
  severity: 'CRITICAL',
  composite_risk_score: 0.92,
  rule_severity_score: 0.85,
  ml_anomaly_score: 0.95,
  user_risk_score: 0.40,
  matched_rules: [
    {
      rule_id: 'r-101',
      rule_name: 'High Value Transaction',
      severity: 'CRITICAL',
      explanation: 'Amount exceeds $5,000 threshold',
    },
  ],
  is_demo: false,
  correlation_id: 'c1d2e3f4-5678-90ab-cdef-1234567890ab',
  created_at: '2026-08-14T12:00:00Z',
  updated_at: '2026-08-14T12:00:00Z',
};

describe('AlertDetailPanel Component', () => {
  it('renders nothing when alert is null', () => {
    const { container } = render(
      <AlertDetailPanel
        alert={null}
        onClose={vi.fn()}
        onApprove={vi.fn()}
        onBlock={vi.fn()}
        onFalsePositive={vi.fn()}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders alert details and metadata when alert is provided', () => {
    render(
      <AlertDetailPanel
        alert={mockAlert}
        onClose={vi.fn()}
        onApprove={vi.fn()}
        onBlock={vi.fn()}
        onFalsePositive={vi.fn()}
      />
    );

    expect(screen.getByText('a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d')).toBeInTheDocument();
    expect(screen.getByText('0.92 / 1.00')).toBeInTheDocument();
    expect(screen.getByText('High Value Transaction')).toBeInTheDocument();
    expect(screen.getByText('Amount exceeds $5,000 threshold')).toBeInTheDocument();
  });

  it('triggers onApprove action handler when Approve button is clicked', async () => {
    const onApprove = vi.fn().mockResolvedValue(undefined);
    render(
      <AlertDetailPanel
        alert={mockAlert}
        onClose={vi.fn()}
        onApprove={onApprove}
        onBlock={vi.fn()}
        onFalsePositive={vi.fn()}
      />
    );

    const reasonInput = screen.getByPlaceholderText('Resolution reason (optional)...');
    await act(async () => {
      fireEvent.change(reasonInput, { target: { value: 'Customer verified transaction' } });
    });

    const approveBtn = screen.getByRole('button', { name: /approve/i });
    await act(async () => {
      fireEvent.click(approveBtn);
    });

    expect(onApprove).toHaveBeenCalledWith(
      'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d',
      'Customer verified transaction'
    );
  });

  it('triggers onBlock action handler when Block button is clicked', async () => {
    const onBlock = vi.fn().mockResolvedValue(undefined);
    render(
      <AlertDetailPanel
        alert={mockAlert}
        onClose={vi.fn()}
        onApprove={vi.fn()}
        onBlock={onBlock}
        onFalsePositive={vi.fn()}
      />
    );

    const blockBtn = screen.getByRole('button', { name: /block fraud/i });
    await act(async () => {
      fireEvent.click(blockBtn);
    });

    expect(onBlock).toHaveBeenCalledWith(
      'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d',
      undefined
    );
  });

  it('triggers onClose when close button is clicked', () => {
    const onClose = vi.fn();
    render(
      <AlertDetailPanel
        alert={mockAlert}
        onClose={onClose}
        onApprove={vi.fn()}
        onBlock={vi.fn()}
        onFalsePositive={vi.fn()}
      />
    );

    const closeBtn = screen.getByRole('button', { name: /close detail panel/i });
    fireEvent.click(closeBtn);

    expect(onClose).toHaveBeenCalledOnce();
  });
});
