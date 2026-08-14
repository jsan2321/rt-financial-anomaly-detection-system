import React, { useMemo } from 'react';
import { Activity } from 'lucide-react';

interface DataPoint {
  time: string;
  volume: number;
  anomalies: number;
}

export const VolumeChart: React.FC = () => {
  // Generate sample 5m continuous aggregate time-series
  const data: DataPoint[] = useMemo(() => {
    const points: DataPoint[] = [];
    const now = new Date();
    for (let i = 24; i >= 0; i--) {
      const d = new Date(now.getTime() - i * 5 * 60 * 1000);
      const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      // Pseudo-random volume with periodic bursts
      const baseVol = 120 + Math.sin(i / 3) * 45 + ((i * 7) % 35);
      const isSpike = i === 4 || i === 12;
      const anomalies = isSpike ? Math.floor(Math.random() * 4) + 2 : Math.random() > 0.7 ? 1 : 0;
      points.push({
        time: timeStr,
        volume: Math.round(baseVol),
        anomalies,
      });
    }
    return points;
  }, []);

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
