import { useCallback, useEffect, useRef, useState } from 'react';
import { ConnectionState, WebSocketMessage } from '../types';

interface UseWebSocketOptions {
  url?: string;
  token?: string;
  onMessage?: (message: WebSocketMessage) => void;
  onReconnected?: () => void;
  autoConnect?: boolean;
}

export function useWebSocket({
  url,
  token = 'dev-token-analyst',
  onMessage,
  onReconnected,
  autoConnect = true,
}: UseWebSocketOptions = {}) {
  const [connectionState, setConnectionState] = useState<ConnectionState>('DISCONNECTED');
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const reconnectTimeoutRef = useRef<any>(null);
  const wasConnectedRef = useRef<boolean>(false);
  const isUnmountingRef = useRef<boolean>(false);

  // Store latest callbacks in refs to avoid reconnection cycles
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;
  const onReconnectedRef = useRef(onReconnected);
  onReconnectedRef.current = onReconnected;

  const getWsUrl = useCallback(() => {
    if (url) return url;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    return `${protocol}//${host}/ws/alerts?token=${encodeURIComponent(token)}`;
  }, [url, token]);

  const connect = useCallback(() => {
    if (isUnmountingRef.current) return;

    if (
      socketRef.current &&
      (socketRef.current.readyState === WebSocket.OPEN ||
        socketRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    try {
      setConnectionState((prev) => (prev === 'CONNECTED' ? 'RECONNECTING' : 'RECONNECTING'));
      const wsUrl = getWsUrl();
      const ws = new WebSocket(wsUrl);
      socketRef.current = ws;

      ws.onopen = () => {
        if (isUnmountingRef.current) {
          ws.close();
          return;
        }

        setConnectionState('CONNECTED');
        reconnectAttemptsRef.current = 0;

        // If reconnecting after a drop, trigger REST reconciliation
        if (wasConnectedRef.current && onReconnectedRef.current) {
          onReconnectedRef.current();
        }
        wasConnectedRef.current = true;
      };

      ws.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data) as WebSocketMessage;
          setLastMessage(parsed);

          // Heartbeat handling: respond to server ping
          if (parsed.type === 'ping') {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'pong', timestamp: new Date().toISOString() }));
            }
          }

          if (onMessageRef.current) {
            onMessageRef.current(parsed);
          }
        } catch {
          // Non-JSON frames
        }
      };

      ws.onerror = () => {
        // Handled in onclose
      };

      ws.onclose = () => {
        if (isUnmountingRef.current) return;

        setConnectionState('DISCONNECTED');
        socketRef.current = null;

        // Exponential backoff capped at 30 seconds
        const delay = Math.min(1000 * Math.pow(1.5, reconnectAttemptsRef.current), 30000);
        reconnectAttemptsRef.current += 1;

        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
        }

        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, delay);
      };
    } catch {
      setConnectionState('DISCONNECTED');
    }
  }, [getWsUrl]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
    if (socketRef.current) {
      socketRef.current.close();
      socketRef.current = null;
    }
    setConnectionState('DISCONNECTED');
  }, []);

  const sendMessage = useCallback((message: any) => {
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        typeof message === 'string' ? message : JSON.stringify(message)
      );
      return true;
    }
    return false;
  }, []);

  useEffect(() => {
    isUnmountingRef.current = false;
    if (autoConnect) {
      connect();
    }

    return () => {
      isUnmountingRef.current = true;
      disconnect();
    };
  }, [autoConnect, connect, disconnect]);

  return {
    connectionState,
    lastMessage,
    connect,
    disconnect,
    sendMessage,
  };
}
