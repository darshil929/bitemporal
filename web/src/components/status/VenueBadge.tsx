import { cn } from "cn";

type VenueBadgeProps = Readonly<{
  venue: string;
  /** The venue an instrument's pages open on. */
  isPrimary?: boolean;
}>;

export function VenueBadge({ venue, isPrimary = false }: VenueBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex h-[22px] items-center gap-[5px] rounded-[3px] border px-2 text-caption font-medium",
        isPrimary
          ? "border-border-strong text-text"
          : "border-border text-text-muted",
      )}
    >
      {isPrimary ? (
        <span aria-hidden="true" className="size-1.5 rounded-full bg-text" />
      ) : null}
      {venue}
      {isPrimary ? (
        <span className="font-normal text-text-subtle">Primary</span>
      ) : null}
    </span>
  );
}
