import type { ReactNode } from "react";

import { Figure } from "@/components/values/Figure";
import { NullValue } from "@/components/values/NullValue";
import type { components } from "@/lib/api";
import {
  formatBps,
  formatDate,
  formatFactor,
  formatPrice,
  formatVolume,
} from "@/lib/format";

type PriceDay = components["schemas"]["PriceDayResponse"];
type CorporateAction = components["schemas"]["CorporateActionResponse"];
type Venue = components["schemas"]["PriceHistoryResponse"]["venue"];

export const CARD_WIDTH = 248;

// The actions dated after a day whose factors the series applies, which bring its prices to the
// scale of the newest ones.
export function actionsAdjusting(
  day: PriceDay,
  actions: readonly CorporateAction[],
): string {
  return actions
    .filter(
      (action) =>
        action.is_applied &&
        action.adjustment_factor !== null &&
        action.ex_date > day.trade_date,
    )
    .map(
      (action) =>
        `the ${[action.terms, action.action_type].filter(Boolean).join(" ")} with ex-date ${formatDate(action.ex_date)}`,
    )
    .join(" and ");
}

function Row({
  mark,
  value,
  label,
}: Readonly<{ mark?: ReactNode; value: ReactNode; label: string }>) {
  return (
    <div className="flex items-center gap-2">
      <span className="flex w-[18px] justify-center">{mark}</span>
      <span className="text-cell font-semibold text-text tabular-nums">
        {value}
      </span>
      <span className="text-header font-normal text-text-muted">{label}</span>
    </div>
  );
}

const Divider = () => <div className="h-px bg-border" />;

type CrosshairCardProps = Readonly<{
  day: PriceDay;
  venue: Venue;
  hasSpread: boolean;
  actions: readonly CorporateAction[];
  left: number;
}>;

// The day under the crosshair: the adjusted close and volume, the other venue's close and the
// spread, and the close as traded where an action adjusts it.
export function CrosshairCard({
  day,
  venue,
  hasSpread,
  actions,
  left,
}: CrosshairCardProps) {
  const other = venue === "NSE" ? "BSE" : "NSE";
  const adjusting = actionsAdjusting(day, actions);
  return (
    <div
      className="pointer-events-none absolute top-[18px] z-20 flex flex-col gap-1.5 rounded-sm border border-border-strong bg-surface-raised px-3 py-2.5"
      style={{ left, width: CARD_WIDTH }}
    >
      <span className="text-caption text-text-subtle">
        {formatDate(day.trade_date)}
      </span>
      <Row
        mark={
          <svg aria-hidden="true" width="18" height="12" viewBox="0 0 18 12">
            <rect x="2" y="2" width="6" height="8" className="fill-up" />
            <rect x="10" y="3" width="6" height="7" className="fill-down" />
          </svg>
        }
        value={
          day.close === null ? (
            <NullValue reason="No price for this day" />
          ) : (
            formatPrice(day.close).text
          )
        }
        label={`${venue} close, adjusted`}
      />
      <Row
        mark={
          <svg aria-hidden="true" width="10" height="12" viewBox="0 0 10 12">
            <rect
              x="2"
              y="1"
              width="6"
              height="10"
              className="fill-text-subtle"
            />
          </svg>
        }
        value={<Figure formatted={formatVolume(day.volume)} />}
        label="Volume, adjusted"
      />
      {hasSpread ? (
        <>
          <Divider />
          <Row
            value={
              day.other_venue_close === null ? (
                <NullValue reason={`No trade at ${other} this day`} />
              ) : (
                formatPrice(day.other_venue_close).text
              )
            }
            label={`${other} close, adjusted`}
          />
          <Row
            value={
              day.venue_spread_bps === null ? (
                <NullValue reason="No spread without a trade at both venues" />
              ) : (
                <Figure formatted={formatBps(day.venue_spread_bps)} />
              )
            }
            label="Venue spread"
          />
        </>
      ) : null}
      {day.adjustment_factor !== 1 && day.close_as_traded !== null ? (
        <>
          <Divider />
          <Row
            value={formatPrice(day.close_as_traded).text}
            label={`${venue} close as traded`}
          />
          <p className="text-caption leading-[1.45] text-text-subtle">
            Factor {formatFactor(day.adjustment_factor)}
            {adjusting ? ` for ${adjusting}` : ""}
          </p>
        </>
      ) : null}
    </div>
  );
}
