import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import { RiskChip } from '../RiskChip';

describe('RiskChip Component', () => {
  it('renders CRITICAL severity with correct text and role', () => {
    render(<RiskChip severity="CRITICAL" />);
    const chip = screen.getByRole('status');
    expect(chip).toHaveTextContent('CRITICAL');
    expect(chip).toHaveAttribute('aria-label', 'Severity: CRITICAL');
  });

  it('renders HIGH, MEDIUM, and LOW severities', () => {
    const { rerender } = render(<RiskChip severity="HIGH" />);
    expect(screen.getByRole('status')).toHaveTextContent('HIGH');

    rerender(<RiskChip severity="MEDIUM" />);
    expect(screen.getByRole('status')).toHaveTextContent('MEDIUM');

    rerender(<RiskChip severity="LOW" />);
    expect(screen.getByRole('status')).toHaveTextContent('LOW');
  });

  it('renders ESCALATION label for escalated alerts', () => {
    render(<RiskChip severity="ESCALATION" />);
    expect(screen.getByRole('status')).toHaveTextContent('ESCALATED');
  });

  it('renders with numerical score when provided', () => {
    render(<RiskChip severity="CRITICAL" score={0.924} />);
    expect(screen.getByRole('status')).toHaveTextContent('(0.92)');
  });
});
