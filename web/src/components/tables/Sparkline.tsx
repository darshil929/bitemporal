type SparklineProps = Readonly<{
  /** Closes in time order, adjusted, so a bonus or split reads as no move. */
  closes: readonly number[];
  width?: number;
  height?: number;
}>;

const INSET = 2;

// The shape of a run of closes with the last one marked; the figures beside it carry the values.
export function Sparkline({ closes, width = 96, height = 24 }: SparklineProps) {
  if (closes.length < 2) {
    return null;
  }
  const low = Math.min(...closes);
  const high = Math.max(...closes);
  const span = high - low || 1;
  const step = (width - 2 * INSET) / (closes.length - 1);
  const points = closes.map(
    (close, index) =>
      [
        INSET + index * step,
        INSET + ((high - close) / span) * (height - 2 * INSET),
      ] as const,
  );
  const [endX, endY] = points[points.length - 1];
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      className="block"
    >
      <polyline
        points={points
          .map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
          .join(" ")}
        fill="none"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        className="stroke-text-muted"
      />
      <circle
        cx={endX.toFixed(1)}
        cy={endY.toFixed(1)}
        r={2}
        className="fill-text"
      />
    </svg>
  );
}
