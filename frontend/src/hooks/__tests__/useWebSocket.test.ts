import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useWebSocket } from '../useWebSocket';

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url: string;
  readyState: number = WebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => {
    this.readyState = WebSocket.CLOSED;
    if (this.onclose) this.onclose();
  });

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }
}

describe('useWebSocket Hook', () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    (global as any).WebSocket = MockWebSocket;
    (global as any).WebSocket.CONNECTING = 0;
    (global as any).WebSocket.OPEN = 1;
    (global as any).WebSocket.CLOSING = 2;
    (global as any).WebSocket.CLOSED = 3;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('initializes and transitions to CONNECTED state on socket open', () => {
    const { result } = renderHook(() =>
      useWebSocket({ url: 'ws://localhost:8000/ws/alerts?token=test', autoConnect: true })
    );

    expect(result.current.connectionState).toBe('RECONNECTING');

    const ws = MockWebSocket.instances[0];
    expect(ws).toBeDefined();

    act(() => {
      ws.readyState = WebSocket.OPEN;
      if (ws.onopen) ws.onopen();
    });

    expect(result.current.connectionState).toBe('CONNECTED');
  });

  it('responds with pong frame when ping is received', () => {
    const onMessage = vi.fn();
    renderHook(() =>
      useWebSocket({
        url: 'ws://localhost:8000/ws/alerts?token=test',
        autoConnect: true,
        onMessage,
      })
    );


    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.readyState = WebSocket.OPEN;
      if (ws.onopen) ws.onopen();
    });

    act(() => {
      if (ws.onmessage) {
        ws.onmessage({
          data: JSON.stringify({ type: 'ping', timestamp: '2026-08-14T00:00:00.000Z' }),
        });
      }
    });

    expect(ws.send).toHaveBeenCalled();
    const sentData = JSON.parse(ws.send.mock.calls[0][0]);
    expect(sentData.type).toBe('pong');
    expect(onMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'ping' })
    );
  });
});
