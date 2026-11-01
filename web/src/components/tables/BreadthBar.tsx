type BreadthBarProps = Readonly<{
  advancing: number;
  declining: number;
  unchanged: number;
}>;

const PARTS = [
  ["advancing", "bg-up"],
  ["declining", "bg-down"],
  ["unchanged", "bg-border-strong"],
] as const;

// The day's advancing, declining and unchanged counts as one bar across its container, each part as
// wide as its share of the three; a count of none draws no part.
export function BreadthBar(counts: BreadthBarProps) {
  return (
    <div aria-hidden="true" className="flex h-2 w-full gap-0.5">
      {PARTS.filter(([name]) => counts[name] > 0).map(([name, colour]) => (
        <span
          key={name}
          data-part={name}
          className={colour}
          style={{ flexBasis: 0, flexGrow: counts[name] }}
        />
      ))}
    </div>
  );
}
