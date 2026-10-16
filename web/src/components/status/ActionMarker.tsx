import { cn } from "cn";

type ActionType =
  "dividend" | "bonus" | "split" | "consolidation" | "rights" | "unhandled";

// Each action takes a letter, so its marker does not depend on colour; an unhandled one, whose
// terms are unknown, carries the flag.
const MARKS: Record<ActionType, { letter: string; label: string }> = {
  dividend: { letter: "D", label: "Dividend" },
  bonus: { letter: "B", label: "Bonus" },
  split: { letter: "S", label: "Split" },
  consolidation: { letter: "C", label: "Consolidation" },
  rights: { letter: "R", label: "Rights" },
  unhandled: { letter: "!", label: "Unhandled action" },
};

export function ActionMarker({
  actionType,
}: Readonly<{ actionType: ActionType }>) {
  const { letter, label } = MARKS[actionType];
  return (
    <span
      role="img"
      aria-label={label}
      className={cn(
        "inline-flex size-4 items-center justify-center rounded-full border text-[9px] font-semibold",
        actionType === "unhandled"
          ? "border-flag bg-flag-surface text-flag"
          : "border-border-strong bg-surface-sunken text-text",
      )}
    >
      {letter}
    </span>
  );
}
