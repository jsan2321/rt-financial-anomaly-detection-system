import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';

import { ThemeToggle } from '../ThemeToggle';
import { ThemeProvider } from '../../../context/ThemeContext';

describe('ThemeToggle Component', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  it('renders theme options with default light selection', () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );

    expect(screen.getByRole('radio', { name: /light theme/i })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('radio', { name: /dark theme/i })).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByRole('radio', { name: /system theme/i })).toHaveAttribute('aria-checked', 'false');
  });

  it('switches to dark mode and updates document data-theme', () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );

    const darkBtn = screen.getByRole('radio', { name: /dark theme/i });
    fireEvent.click(darkBtn);

    expect(darkBtn).toHaveAttribute('aria-checked', 'true');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(localStorage.getItem('rt_fads_theme')).toBe('dark');
  });

  it('switches back to light mode and clears data-theme', () => {
    localStorage.setItem('rt_fads_theme', 'dark');

    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );

    const lightBtn = screen.getByRole('radio', { name: /light theme/i });
    fireEvent.click(lightBtn);

    expect(lightBtn).toHaveAttribute('aria-checked', 'true');
    expect(document.documentElement.getAttribute('data-theme')).toBeNull();
    expect(localStorage.getItem('rt_fads_theme')).toBe('light');
  });
});
