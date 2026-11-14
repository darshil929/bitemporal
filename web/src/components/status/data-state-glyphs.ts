import {
  Check,
  Clock,
  Info,
  type LucideIcon,
  TriangleAlert,
} from "lucide-react";

import type { DataState } from "@/lib/data-status";

// Each state of the data status beside its word: alert for stale and failed alone.
export const STATE_GLYPHS: Record<DataState, LucideIcon> = {
  fresh: Check,
  updating: Clock,
  stale: TriangleAlert,
  failed: TriangleAlert,
  unknown: Info,
};
