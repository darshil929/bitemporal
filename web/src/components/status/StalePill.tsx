import { Clock } from "lucide-react";

import { StatusPill } from "@/components/status/StatusPill";
import { formatDate } from "@/lib/format";

type StalePillProps = Readonly<{
  /** The day the figures are from, older than the latest complete day. */
  isoDate: string;
  /** How many complete trading days have passed since, as the API counts them. */
  tradingDaysBehind?: number;
}>;

function behind(days: number): string {
  return days === 1 ? "one trading day behind" : `${days} trading days behind`;
}

export function StalePill({ isoDate, tradingDaysBehind }: StalePillProps) {
  const day = formatDate(isoDate);
  return (
    <StatusPill icon={Clock}>
      {tradingDaysBehind === undefined
        ? day
        : `${day}, ${behind(tradingDaysBehind)}`}
    </StatusPill>
  );
}
