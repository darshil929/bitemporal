import { Layers } from "lucide-react";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { AsOfStamp } from "@/components/values/AsOfStamp";
import { formatDate } from "@/lib/format";

type Source = Readonly<{
  source_id: string;
  tier: number;
  /** The row of SEBI's curated list naming the file; an exchange web endpoint has none. */
  sebi_curation_ref: string | null;
}>;

type ProvenanceChipProps = Readonly<{
  sources: readonly Source[];
  /** The day the figures were published. */
  isoDate: string;
}>;

const SOURCE_NAMES: Partial<Record<string, string>> = {
  bse_bhavcopy_equity: "BSE bhavcopy",
  nse_bhavcopy_equity: "NSE bhavcopy",
  bse_delivery: "BSE delivery file",
  nse_delivery: "NSE delivery file",
  bse_corporate_actions: "BSE corporate actions",
  nse_corporate_actions: "NSE corporate actions",
  bse_scrip_list: "BSE list of scrips",
  nse_equity_list: "NSE list of equities",
};

const TIER_NAMES: Partial<Record<number, string>> = {
  1: "exchange bulk file",
  2: "exchange web endpoint",
  3: "community library",
  4: "third-party site",
};

// A source the names do not cover yet reads as its identifier.
function sourceName({ source_id }: Source): string {
  return SOURCE_NAMES[source_id] ?? source_id;
}

function standing({ tier, sebi_curation_ref }: Source): string {
  const named = TIER_NAMES[tier];
  const tierText = named ? `Tier ${tier}, ${named}.` : `Tier ${tier}.`;
  return sebi_curation_ref
    ? `${tierText} SEBI curation: ${sebi_curation_ref}`
    : tierText;
}

// The sources behind the figures beside it, their lowest tier and the day published; the detail
// opens on it and states each source's standing.
export function ProvenanceChip({ sources, isoDate }: ProvenanceChipProps) {
  if (sources.length === 0) {
    return null;
  }
  const tier = Math.min(...sources.map((source) => source.tier));
  return (
    <Popover>
      <PopoverTrigger className="inline-flex h-[22px] items-center gap-1.5 rounded-[3px] border border-border bg-surface-sunken px-2 text-caption whitespace-nowrap text-text-muted">
        <Layers aria-hidden="true" className="size-3 text-text-subtle" />
        {sources.map(sourceName).join(", ")}{" "}
        <span className="text-text-subtle">Tier {tier}</span>{" "}
        <span className="text-text-subtle tabular-nums">
          {formatDate(isoDate)}
        </span>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="flex w-[400px] flex-col gap-1.5 rounded-sm border-border-strong bg-surface-raised p-3 text-text shadow-none"
      >
        <div className="flex items-baseline justify-between gap-3">
          <h3 className="text-cell font-semibold">
            Where these figures come from
          </h3>
          <AsOfStamp isoDate={isoDate} lead="Published" />
        </div>
        <ul>
          {sources.map((source) => (
            <li
              key={source.source_id}
              className="flex flex-col gap-0.5 border-t border-border py-2"
            >
              <div className="flex justify-between gap-3 text-header font-normal">
                <span>{sourceName(source)}</span>
                <span className="font-mono text-caption text-text-subtle">
                  {source.source_id}
                </span>
              </div>
              <span className="text-caption text-text-muted">
                {standing(source)}
              </span>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
