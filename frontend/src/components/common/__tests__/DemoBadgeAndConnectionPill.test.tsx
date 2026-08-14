import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import { DemoBadge } from '../DemoBadge';
import { ConnectionPill } from '../ConnectionPill';

describe('DemoBadge Component', () => {
  it('renders visible DEMO badge with proper accessibility role', () => {
    render(<DemoBadge />);
    const badge = screen.getByRole('note');
    expect(badge).toHaveTextContent('DEMO');
    expect(badge).toHaveAttribute('aria-label', 'Demo scenario alert');
  });
});

describe('ConnectionPill Component', () => {
  it('renders CONNECTED state with Live Stream text', () => {
    render(<ConnectionPill state="CONNECTED" />);
    const pill = screen.getByRole('status');
    expect(pill).toHaveTextContent('Live Stream');
    expect(pill).toHaveAttribute('aria-label', 'Connection status: CONNECTED');
  });

  it('renders RECONNECTING state', () => {
    render(<ConnectionPill state="RECONNECTING" />);
    const pill = screen.getByRole('status');
    expect(pill).toHaveTextContent('Reconnecting...');
  });

  it('renders DISCONNECTED state', () => {
    render(<ConnectionPill state="DISCONNECTED" />);
    const pill = screen.getByRole('status');
    expect(pill).toHaveTextContent('Feed Offline');
  });
});
