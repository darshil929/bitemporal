import { cn } from "cn";

// Shaped like the content it replaces: the caller gives the width, and the height of a line of
// type unless the content is taller.
export function Skeleton({ className }: Readonly<{ className?: string }>) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "h-3 rounded-xs bg-border motion-safe:animate-pulse",
        className,
      )}
    />
  );
}
