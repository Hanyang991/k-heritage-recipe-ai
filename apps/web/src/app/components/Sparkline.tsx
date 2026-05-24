/**
 * Inline mini sparkline rendered as raw SVG (no recharts dependency).
 *
 * The full ``LineChart`` lives in ``TrendSeriesDialog`` — this component is
 * only meant for grid / table cells where we want a sub-100px-wide preview
 * of the same series. Returns a placeholder when the series is missing or
 * has fewer than 2 points so the layout doesn't jump while data loads.
 */

interface Props {
  /** ratios in [0, 100], oldest first */
  points: number[];
  width?: number;
  height?: number;
  /** override the auto-derived stroke colour (green when rising, red when falling) */
  color?: string;
  /** show the last data point as a filled dot */
  showLastDot?: boolean;
  className?: string;
}

const PLACEHOLDER_COLOR = "#D1D5DB";

export function Sparkline({
  points,
  width = 80,
  height = 24,
  color,
  showLastDot = true,
  className,
}: Props) {
  if (!points || points.length < 2) {
    return (
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        className={className}
        aria-hidden
      >
        <line
          x1={2}
          y1={height / 2}
          x2={width - 2}
          y2={height / 2}
          stroke={PLACEHOLDER_COLOR}
          strokeWidth={1}
          strokeDasharray="2 2"
        />
      </svg>
    );
  }

  const max = Math.max(...points);
  const min = Math.min(...points);
  const range = max - min || 1;

  // 1px breathing room so the stroke doesn't clip on top/bottom
  const pad = 1.5;
  const innerH = height - pad * 2;

  const pad_x = 1.5;
  const innerW = width - pad_x * 2;

  const coords = points.map((p, i) => {
    const x = pad_x + (i * innerW) / (points.length - 1);
    const y = pad + innerH - ((p - min) / range) * innerH;
    return [x, y] as const;
  });

  const stroke = color ?? (points[points.length - 1] >= points[0] ? "#059669" : "#DC2626");

  const polyline = coords.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const [lastX, lastY] = coords[coords.length - 1];

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={className}
      aria-hidden
    >
      <polyline
        points={polyline}
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {showLastDot ? <circle cx={lastX} cy={lastY} r={1.8} fill={stroke} /> : null}
    </svg>
  );
}
