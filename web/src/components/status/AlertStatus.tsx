import { Bell, Clock, type LucideIcon, Pause } from "lucide-react";

import { type StatusTone, StatusPill } from "@/components/status/StatusPill";

type Status = "triggered" | "watching" | "paused";

const SHOWN: Record<
  Status,
  { label: string; tone: StatusTone; icon: LucideIcon }
> = {
  triggered: { label: "Triggered", tone: "flag", icon: Bell },
  watching: { label: "Watching", tone: "neutral", icon: Clock },
  paused: { label: "Paused", tone: "neutral", icon: Pause },
};

// A watchlist alert: met on the latest complete day, waiting, or paused while its entry trades no
// more.
export function AlertStatus({ status }: Readonly<{ status: Status }>) {
  const { label, tone, icon } = SHOWN[status];
  return (
    <StatusPill tone={tone} icon={icon}>
      {label}
    </StatusPill>
  );
}
