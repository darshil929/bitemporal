import { Clock } from "lucide-react";

import { formatDate } from "@/lib/format";

type AsOfStampProps = Readonly<{
  isoDate: string;
  /** The day a figure is from, or the day a change is measured against. */
  lead?: "As of" | "Changes against";
}>;

export function AsOfStamp({ isoDate, lead = "As of" }: AsOfStampProps) {
  return (
    <span className="inline-flex items-center gap-[5px] text-header font-normal whitespace-nowrap text-text-subtle">
      <Clock aria-hidden="true" className="size-3" />
      {lead}{" "}
      <span className="font-medium text-text-muted tabular-nums">
        {formatDate(isoDate)}
      </span>
    </span>
  );
}
