import { Tooltip } from "@/components/layout/Tooltip";

// An absent figure reads as a dash, never as zero or a blank, and says why it is absent.
export function NullValue({ reason }: Readonly<{ reason: string }>) {
  return (
    <Tooltip text={reason}>
      <span tabIndex={0} aria-label={reason} className="text-text-subtle">
        —
      </span>
    </Tooltip>
  );
}
