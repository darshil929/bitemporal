"use client";

import { ChevronDown, Lock, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  type FocusEvent,
  type KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/controls/DropdownMenu";
import {
  COMPARISON_ORDER,
  COMPARISONS,
  type Criterion,
  FIGURES,
  isComparison,
  thresholdFromTyped,
  thresholdText,
  thresholdUnit,
  typedThreshold,
} from "@/lib/screener-criteria";

import { cn } from "cn";

type CriterionChipProps = Readonly<{
  criterion: Criterion;
  /** The liquidity gate, a criterion the screen starts with, on the sunken surface. */
  isGate?: boolean;
  /** The screen's address without this criterion. */
  removeHref: string;
  /** The screen's address with this criterion as edited. */
  hrefFor: (criterion: Criterion) => string;
}>;

const CHIP =
  "inline-flex h-7 items-center gap-1.5 rounded-sm border pl-2.5 text-header font-normal whitespace-nowrap";

/** How a criterion reads aloud: `Return 3M above 0.00%`. */
export function describeCriterion(criterion: Criterion): string {
  const { label } = FIGURES[criterion.figure];
  const { words } = COMPARISONS[criterion.comparison];
  return `${label} ${words} ${thresholdText(criterion)}`;
}

function GateMark() {
  return <Lock aria-hidden="true" className="size-3 text-text-muted" />;
}

function Remove({ href, label }: Readonly<{ href: string; label: string }>) {
  return (
    <Link
      href={href}
      scroll={false}
      aria-label={label}
      className="inline-flex size-[18px] items-center justify-center text-text-subtle"
    >
      <X aria-hidden="true" className="size-3" />
    </Link>
  );
}

type EditorProps = CriterionChipProps &
  Readonly<{ name: string; remove: string; onDone: () => void }>;

// The criterion in place: its comparison chosen from a menu and its threshold typed in the figure's
// unit. Enter or leaving the chip opens the screen with the change; Escape keeps it as it was.
function CriterionEditor({
  criterion,
  isGate,
  hrefFor,
  name,
  remove,
  removeHref,
  onDone,
}: EditorProps) {
  const router = useRouter();
  const [comparison, setComparison] = useState(criterion.comparison);
  const [typed, setTyped] = useState(() => typedThreshold(criterion));
  const [isInvalid, setIsInvalid] = useState(false);
  const isChoosing = useRef(false);
  const field = useRef<HTMLInputElement>(null);
  const { label } = FIGURES[criterion.figure];
  const unit = thresholdUnit(criterion.figure);

  useEffect(() => {
    field.current?.focus();
    field.current?.select();
  }, []);

  function apply() {
    const value = thresholdFromTyped(criterion.figure, typed);
    if (value === null) {
      setIsInvalid(true);
      return;
    }
    onDone();
    if (value !== criterion.value || comparison !== criterion.comparison) {
      router.push(hrefFor({ figure: criterion.figure, comparison, value }), {
        scroll: false,
      });
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      apply();
    } else if (event.key === "Escape") {
      event.preventDefault();
      onDone();
    }
  }

  // Focus moving into the comparison menu, or between the chip's own parts, is still editing.
  function onBlur(event: FocusEvent<HTMLSpanElement>) {
    const next = event.relatedTarget;
    if (
      isChoosing.current ||
      (next instanceof Node && event.currentTarget.contains(next))
    ) {
      return;
    }
    apply();
  }

  return (
    <span
      role="group"
      aria-label={name}
      onBlur={onBlur}
      className={cn(CHIP, "border-accent bg-surface-raised pr-1")}
    >
      {isGate ? <GateMark /> : null}
      <span className="text-text-muted">{label}</span>
      <DropdownMenu
        onOpenChange={(isOpen) => {
          isChoosing.current = isOpen;
        }}
      >
        <DropdownMenuTrigger
          aria-label={`Comparison, ${COMPARISONS[comparison].words}`}
          className="inline-flex h-5 items-center gap-0.5 rounded-[3px] border border-border px-1 text-text"
        >
          {COMPARISONS[comparison].sign}
          <ChevronDown
            aria-hidden="true"
            className="size-2.5 text-text-subtle"
          />
        </DropdownMenuTrigger>
        <DropdownMenuContent className="min-w-[160px]">
          <DropdownMenuRadioGroup
            value={comparison}
            onValueChange={(chosen) => {
              if (isComparison(chosen)) setComparison(chosen);
            }}
          >
            {COMPARISON_ORDER.map((option) => (
              <DropdownMenuRadioItem key={option} value={option}>
                {`${COMPARISONS[option].sign} ${COMPARISONS[option].words}`}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
      <span
        className={cn(
          "inline-flex h-5 items-center gap-1 rounded-[3px] border px-1.5 tabular-nums",
          isInvalid ? "border-flag" : "border-accent",
        )}
      >
        <input
          ref={field}
          aria-label={`${label} threshold`}
          aria-invalid={isInvalid || undefined}
          inputMode="decimal"
          value={typed}
          size={Math.max(typed.length, 2)}
          onChange={(event) => {
            setTyped(event.target.value);
            setIsInvalid(false);
          }}
          onKeyDown={onKeyDown}
          className="bg-transparent text-text outline-none"
        />
        {unit ? <span className="text-text-subtle">{unit}</span> : null}
      </span>
      <Remove href={removeHref} label={remove} />
    </span>
  );
}

// A filter that is also a column: the figure, the comparison's sign and the threshold. Choosing it
// edits it in place; the cross is a link to the screen without it, so the address stays the view.
export function CriterionChip({
  criterion,
  isGate = false,
  removeHref,
  hrefFor,
}: CriterionChipProps) {
  const [isEditing, setIsEditing] = useState(false);
  const described = describeCriterion(criterion);
  const name = isGate ? `Liquidity gate, ${described}` : described;
  const remove = isGate ? "Remove the liquidity gate" : `Remove ${described}`;
  if (isEditing) {
    return (
      <CriterionEditor
        criterion={criterion}
        isGate={isGate}
        hrefFor={hrefFor}
        name={name}
        remove={remove}
        removeHref={removeHref}
        onDone={() => setIsEditing(false)}
      />
    );
  }
  return (
    <span
      role="group"
      aria-label={name}
      className={cn(
        CHIP,
        "pr-1.5",
        isGate
          ? "border-border bg-surface-sunken"
          : "border-border-strong bg-surface-raised",
      )}
    >
      <button
        type="button"
        aria-label={`Edit ${described}`}
        onClick={() => setIsEditing(true)}
        className="inline-flex items-center gap-1.5"
      >
        {isGate ? <GateMark /> : null}
        <span className="text-text-muted">
          {FIGURES[criterion.figure].label}
        </span>
        <span className="text-text-subtle">
          {COMPARISONS[criterion.comparison].sign}
        </span>
        <span className="font-medium text-text tabular-nums">
          {thresholdText(criterion)}
        </span>
      </button>
      <Remove href={removeHref} label={remove} />
    </span>
  );
}
