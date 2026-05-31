interface LidarPoint {
  angle_deg: number
  distance_m: number
}

interface Props {
  points?: LidarPoint[]
  rangeMaxM?: number
  size?: number
  connected?: boolean
  error?: string | null
}

function pointColor(distM: number): string {
  if (distM < 2) return '#ef4444'   // red
  if (distM < 4) return '#f97316'   // orange
  return '#22c55e'                   // green
}

export default function LidarRadar360({
  points = [],
  rangeMaxM = 6,
  size = 300,
  connected = false,
  error = null,
}: Props) {
  const R = size / 2
  const cx = R
  const cy = R
  const plotR = R - 18  // leave margin for labels

  function toXY(angleDeg: number, distM: number) {
    const r = Math.min(distM / rangeMaxM, 1.0) * plotR
    // angle 0° = forward = top; SVG y-axis is inverted
    const rad = ((angleDeg - 90) * Math.PI) / 180
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) }
  }

  // Down-sample to max 720 visual points
  const displayed =
    points.length > 720
      ? points.filter((_, i) => i % Math.ceil(points.length / 720) === 0)
      : points

  const rings = [1, 2, 3, 4, 5, 6].filter((r) => r <= rangeMaxM)

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="select-none"
      aria-label="Radar LIDAR 360°"
    >
      {/* dark background */}
      <circle cx={cx} cy={cy} r={R - 1} fill="#0a0f1e" stroke="#1e293b" strokeWidth="1" />

      {/* range rings */}
      {rings.map((r) => {
        const pr = (r / rangeMaxM) * plotR
        return (
          <g key={r}>
            <circle cx={cx} cy={cy} r={pr} fill="none" stroke="#1e293b" strokeWidth="0.5" strokeDasharray="3 3" />
            <text
              x={cx + 3}
              y={cy - pr + 8}
              fill="#334155"
              fontSize="7"
              fontFamily="monospace"
            >
              {r}m
            </text>
          </g>
        )
      })}

      {/* cross-hairs */}
      <line x1={cx} y1={cy - plotR} x2={cx} y2={cy + plotR} stroke="#1e293b" strokeWidth="0.5" />
      <line x1={cx - plotR} y1={cy} x2={cx + plotR} y2={cy} stroke="#1e293b" strokeWidth="0.5" />

      {/* cardinal labels */}
      <text x={cx} y={10} textAnchor="middle" fill="#475569" fontSize="9" fontFamily="monospace" fontWeight="bold">N</text>
      <text x={size - 9} y={cy + 4} textAnchor="middle" fill="#475569" fontSize="9" fontFamily="monospace">E</text>
      <text x={cx} y={size - 4} textAnchor="middle" fill="#475569" fontSize="9" fontFamily="monospace">S</text>
      <text x={9} y={cy + 4} textAnchor="middle" fill="#475569" fontSize="9" fontFamily="monospace">O</text>

      {/* scan points */}
      {connected &&
        displayed.map((p, i) => {
          const { x, y } = toXY(p.angle_deg, p.distance_m)
          return (
            <circle
              key={i}
              cx={x}
              cy={y}
              r={1.5}
              fill={pointColor(p.distance_m)}
              opacity={0.85}
            />
          )
        })}

      {/* robot body */}
      <circle cx={cx} cy={cy} r={5} fill="#3b82f6" />
      {/* forward indicator triangle */}
      <polygon
        points={`${cx},${cy - 10} ${cx - 4},${cy - 2} ${cx + 4},${cy - 2}`}
        fill="#60a5fa"
      />

      {/* offline / error overlay */}
      {!connected && (
        <text
          x={cx}
          y={cy + plotR - 12}
          textAnchor="middle"
          fill="#64748b"
          fontSize="10"
          fontFamily="monospace"
        >
          {error ?? 'ROS2 hors ligne'}
        </text>
      )}
    </svg>
  )
}
