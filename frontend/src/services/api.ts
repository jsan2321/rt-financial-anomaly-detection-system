import { Alert, AlertListResponse, Transaction } from '../types';


const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
    public details?: any
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function fetchJson<T>(url: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('rt_fads_token') || 'dev-token-analyst';
  const headers = new Headers(options.headers);
  headers.set('Content-Type', 'application/json');
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  headers.set('X-Correlation-ID', crypto.randomUUID());
  headers.set('X-Actor', 'analyst_ui');

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorData: any = {};
    try {
      errorData = await response.json();
    } catch {
      // Body not JSON
    }

    const message =
      errorData?.error?.message ||
      errorData?.detail ||
      `Request failed with status ${response.status}`;
    const code = errorData?.error?.code;
    const details = errorData?.error?.details || errorData;

    throw new ApiError(message, response.status, code, details);
  }

  return response.json();
}

export const api = {
  /**
   * Fetches paginated and filtered alerts.
   */
  async getAlerts(params: {
    status?: string;
    severity?: string;
    from?: string;
    to?: string;
    page?: number;
    pageSize?: number;
  }): Promise<AlertListResponse> {
    const query = new URLSearchParams();
    if (params.status && params.status !== 'ALL') query.set('status', params.status);
    if (params.severity && params.severity !== 'ALL') query.set('severity', params.severity);
    if (params.from) query.set('from', params.from);
    if (params.to) query.set('to', params.to);
    if (params.page) query.set('page', params.page.toString());
    if (params.pageSize) query.set('page_size', params.pageSize.toString());

    return fetchJson<AlertListResponse>(`${API_BASE_URL}/alerts?${query.toString()}`);
  },

  /**
   * Fetches full alert detail including explanation breakdown and audit logs.
   */
  async getAlertDetail(alertId: string): Promise<Alert> {
    return fetchJson<Alert>(`${API_BASE_URL}/alerts/${alertId}`);
  },

  /**
   * Resolves an alert as APPROVED.
   */
  async approveAlert(alertId: string, resolutionReason?: string): Promise<Alert> {
    return fetchJson<Alert>(`${API_BASE_URL}/alerts/${alertId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ resolution_reason: resolutionReason }),
    });
  },

  /**
   * Resolves an alert as BLOCKED.
   */
  async blockAlert(alertId: string, resolutionReason?: string): Promise<Alert> {
    return fetchJson<Alert>(`${API_BASE_URL}/alerts/${alertId}/block`, {
      method: 'POST',
      body: JSON.stringify({ resolution_reason: resolutionReason }),
    });
  },

  /**
   * Resolves an alert as FALSE_POSITIVE.
   */
  async markFalsePositive(alertId: string, resolutionReason?: string): Promise<Alert> {
    return fetchJson<Alert>(`${API_BASE_URL}/alerts/${alertId}/false-positive`, {
      method: 'POST',
      body: JSON.stringify({ resolution_reason: resolutionReason }),
    });
  },

  /**
   * Fetches transaction status and summary.
   */
  async getTransaction(transactionId: string): Promise<Transaction> {
    return fetchJson<Transaction>(`${API_BASE_URL}/transactions/${transactionId}`);
  },
};
