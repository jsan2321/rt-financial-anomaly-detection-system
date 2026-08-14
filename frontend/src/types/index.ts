/**
 * Core domain types and interfaces for RT-FADS frontend.
 */

export type AlertStatus =
  | 'PENDING'
  | 'ESCALATED_EMAIL'
  | 'ESCALATED_SLACK'
  | 'APPROVED'
  | 'BLOCKED'
  | 'FALSE_POSITIVE';

export type AlertSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';

export interface RuleMatch {
  rule_id: string;
  rule_name: string;
  severity: AlertSeverity;
  explanation: string;
}

export interface Alert {
  id: string;
  transaction_id: string;
  status: AlertStatus;
  severity: AlertSeverity;
  composite_risk_score: number;
  rule_severity_score: number;
  ml_anomaly_score: number;
  user_risk_score: number;
  matched_rules: RuleMatch[];
  is_demo: boolean;
  resolved_by?: string | null;
  resolved_at?: string | null;
  resolution_reason?: string | null;
  escalated_email_at?: string | null;
  escalated_slack_at?: string | null;
  correlation_id: string;
  created_at: string;
  updated_at: string;
}

export interface AlertListResponse {
  items: Alert[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface Transaction {
  id: string;
  user_id: string;
  amount: number;
  currency: string;
  country: string;
  merchant_category: string;
  status: 'SUBMITTED' | 'PROCESSING' | 'PROCESSED' | 'PROCESSING_FAILED';
  idempotency_key: string;
  correlation_id: string;
  created_at: string;
  updated_at: string;
}

export interface RiskProfile {
  user_id: string;
  risk_score: number;
  total_transactions: number;
  alert_count: number;
  false_positive_count: number;
  last_evaluated_at: string;
  created_at: string;
  updated_at: string;
}

export interface AuditLog {
  id: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  before?: Record<string, any> | null;
  after?: Record<string, any> | null;
  correlation_id?: string | null;
  created_at: string;
}

export type WebSocketMessage =
  | {
      type: 'alert.created';
      alert: {
        id: string;
        transaction_id: string;
        status: AlertStatus;
        severity: AlertSeverity;
        composite_risk_score: number;
        created_at: string;
      };
    }
  | {
      type: 'alert.updated';
      alert: {
        id: string;
        status: AlertStatus;
        resolved_at?: string;
      };
    }
  | {
      type: 'escalation';
      alert_id: string;
      escalation_level: 'email' | 'slack';
    }
  | {
      type: 'ping';
      timestamp: string;
    };

export type ConnectionState = 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED';

export type ThemeMode = 'light' | 'dark' | 'system';

export interface AlertFilterState {
  status?: AlertStatus | 'ALL';
  severity?: AlertSeverity | 'ALL';
  search?: string;
  page: number;
  pageSize: number;
}
