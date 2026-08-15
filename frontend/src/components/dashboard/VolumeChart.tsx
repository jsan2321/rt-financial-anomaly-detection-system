import React, { useMemo } from 'react';
import { Activity } from 'lucide-react';
import { Alert } from '../../types';

interface DataPoint {
  time: string;
  volume: number;
  anomalies: number;
}

interface VolumeChartProps {
  alerts?: Alert[];
}

export const VolumeChart: React.FC<VolumeChartProps> = ({ alerts = [] }) => {
  // Aggregate real alerts into 5m continuous aggregation windows
  const data: DataPoint[] = useMemo(() => {
    const points: DataPoint[] = [];
    const now = new Date();
    // 24 buckets of 5 minutes = 2 hours trailing window
    for (let i = 24; i >= 0; i--) {
      const bucketEnd = new Date(now.getTime() - i * 5 * 60 * 1000);
      const bucketStart = new Date(bucketEnd.getTime() - 5 * 60 * 1000);
      const timeStr = bucketEnd.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

      // Count actual alerts occurring in this 5m window
      const matchedAlerts = alerts.filter((a) => {
        try {
          const alertTime = new Date(a.created_at).getTime();
          return alertTime >= bucketStart.getTime() && alertTime <= bucketEnd.getTime();
        } catch {
          return false;
        }
      }).length;

      // Deterministic synthetic baseline throughput curve
      const bucketIndex = 24 - i;
      const baseVol = 110 + Math.sin(bucketIndex / 3.5) * 40 + ((bucketIndex * 13) % 25);

      points.push({
        time: timeStr,
        volume: Math.round(baseVol + matchedAlerts * 15),
        anomalies: matchedAlerts,
      });
    }
    return points;
  }, [alerts]);

  const maxVolume = Math.max(...data.map((d) => d.volume), 200);
  const chartHeight = 160;
  const chartWidth = 700;
  const paddingX = 40;
  const paddingY = 20;

  const points = data.map((d, index) => {
    const x = paddingX + (index / (data.length - 1)) * (chartWidth - 2 * paddingX);
    const y = chartHeight - paddingY - (d.volume / maxVolume) * (chartHeight - 2 * paddingY);
    return { x, y, ...d };
  });

  const pathD = points.reduce((acc, curr, idx) => {
    return idx === 0 ? `M ${curr.x} ${curr.y}` : `${acc} L ${curr.x} ${curr.y}`;
  }, '');

  const areaD = `${pathD} L ${points[points.length - 1].x} ${chartHeight - paddingY} L ${points[0].x} ${chartHeight - paddingY} Z`;

  return (
    <div className="card" style={{ padding: 'var(--space-5)', marginBottom: 'var(--space-6)' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 'var(--space-4)',
        }}
      >
        <div>
          <h3 className="headline-sm" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Activity size={18} style={{ color: 'var(--color-primary)' }} />
            <span>Transaction Throughput & Anomaly Spikes</span>
          </h3>
          <p className="body-sm" style={{ color: 'var(--color-text-muted)', marginTop: '2px' }}>
            Continuous 5-minute aggregation window
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)', fontSize: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span
              style={{
                width: '10px',
                height: '10px',
                borderRadius: '2px',
                backgroundColor: 'var(--color-primary)',
              }}
            />
            <span style={{ color: 'var(--color-text-secondary)' }}>Throughput (tx/5m)</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span
              style={{
                width: '10px',
                height: '10px',
                borderRadius: '50%',
                backgroundColor: 'var(--color-risk-critical)',
              }}
            />
            <span style={{ color: 'var(--color-text-secondary)' }}>Anomaly Detected</span>
          </div>
        </div>
      </div>

      <div style={{ width: '100%', overflowX: 'auto' }}>
        <svg
          viewBox={`0 0 ${chartWidth} ${chartHeight}`}
          style={{ width: '100%', height: 'auto', minWidth: '500px' }}
        >
          <defs>
            <linearGradient id="volGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-primary)" stopOpacity="0.25" />
              <stop offset="100%" stopColor="var(--color-primary)" stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          <line
            x1={paddingX}
            y1={chartHeight - paddingY}
            x2={chartWidth - paddingX}
            y2={chartHeight - paddingY}
            stroke="var(--color-border)"
            strokeWidth="1"
          />
          <line
            x1={paddingX}
            y1={chartHeight / 2}
            x2={chartWidth - paddingX}
            y2={chartHeight / 2}
            stroke="var(--color-border-subtle)"
            strokeDasharray="4 4"
            strokeWidth="1"
          />

          {/* Area fill */}
          <path d={areaD} fill="url(#volGradient)" />

          {/* Line path */}
          <path
            d={pathD}
            fill="none"
            stroke="var(--color-primary)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Anomaly nodes & points */}
          {points.map((p, i) => (
            <g key={i}>
              {p.anomalies > 0 ? (
                <g>
                  <circle
                    cx={p.x}
                    cy={p.y}
                    r="5"
                    fill="var(--color-risk-critical)"
                    stroke="var(--color-surface)"
                    strokeWidth="2"
                  />
                  <circle
                    cx={p.x}
                    cy={p.y}
                    r="8"
                    fill="none"
                    stroke="var(--color-risk-critical)"
                    strokeWidth="1"
                    opacity="0.6"
                    className="animate-pulse-slow"
                  />
                </g>
              ) : (
                <circle
                  cx={p.x}
                  cy={p.y}
                  r="2.5"
                  fill="var(--color-primary)"
                  opacity="0.7"
                />
              )}
            </g>
          ))}

          {/* X Axis Time Labels */}
          {points.filter((_, idx) => idx % 6 === 0 || idx === points.length - 1).map((p, i) => (
            <text
              key={i}
              x={p.x}
              y={chartHeight - 4}
              textAnchor="middle"
              className="technical-data"
              fill="var(--color-text-muted)"
              fontSize="10"
            >
              {p.time}
            </text>
          ))}
        </svg>
      </div>
    </div>
  );
};
