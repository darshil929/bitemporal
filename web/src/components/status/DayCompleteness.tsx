import { Check, TriangleAlert } from "lucide-react";

import { StatusPill } from "@/components/status/StatusPill";

type DayCompletenessProps = Readonly<{
  venue: string;
  /** The venue's day passed every check. */
  isComplete: boolean;
}>;

// A complete day is stated plainly, its check in the pill's own colour, since up and down mean
// price direction alone; a partial day carries the flag.
export function DayCompleteness({ venue, isComplete }: DayCompletenessProps) {
  return isComplete ? (
    <StatusPill icon={Check}>{venue} complete</StatusPill>
  ) : (
    <StatusPill tone="flag" icon={TriangleAlert}>
      {venue} partial
    </StatusPill>
  );
}
