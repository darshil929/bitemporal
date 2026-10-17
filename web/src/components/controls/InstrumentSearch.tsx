"use client";

import { keepPreviousData } from "@tanstack/react-query";
import { Command as CommandPrimitive } from "cmdk";
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { cn } from "cn";

import { Refetch } from "@/components/layout/Refetch";
import { VenueBadge } from "@/components/status/VenueBadge";
import { Command, CommandItem, CommandList } from "@/components/ui/command";
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from "@/components/ui/popover";
import { apiQueries } from "@/lib/api-client";

// The API searches from two characters to 64, neither end a space.
const SHORTEST_QUERY = 2;
const LONGEST_QUERY = 64;
// A query is sent once typing pauses, not on every key.
const SETTLE_MS = 200;

type InstrumentSearchProps = Readonly<{
  label?: string;
  placeholder?: string;
  /** A key that moves focus here from anywhere on the page, shown at the field's end. */
  shortcutKey?: string;
  className?: string;
}>;

function useSettled(value: string): string {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), SETTLE_MS);
    return () => clearTimeout(timer);
  }, [value]);
  return settled;
}

function isTyping(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable ||
      ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

// Matches by name, symbol, scrip code or ISIN, open listings first; choosing one opens its page.
export function InstrumentSearch({
  label = "Search instruments",
  placeholder = "Search name, symbol or ISIN",
  shortcutKey,
  className,
}: InstrumentSearchProps) {
  const router = useRouter();
  const field = useRef<HTMLSpanElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [isOpen, setOpen] = useState(false);
  const asked = useSettled(query.trim());
  const isAsking = asked.length >= SHORTEST_QUERY;
  const { data, isError, isFetching, isPlaceholderData } = apiQueries.useQuery(
    "get",
    "/instruments",
    { params: { query: { q: asked } } },
    { enabled: isAsking, placeholderData: keepPreviousData },
  );

  useEffect(() => {
    if (!shortcutKey) {
      return;
    }
    function focusOnShortcut(event: KeyboardEvent) {
      if (event.key !== shortcutKey || isTyping(event.target)) {
        return;
      }
      event.preventDefault();
      input.current?.focus();
    }
    window.addEventListener("keydown", focusOnShortcut);
    return () => window.removeEventListener("keydown", focusOnShortcut);
  }, [shortcutKey]);

  function open(isin: string) {
    setOpen(false);
    setQuery("");
    router.push(`/instrument/${isin}`);
  }

  return (
    <Command shouldFilter={false} loop label={label} className="contents">
      <Popover
        open={isOpen && isAsking && (data !== undefined || isError)}
        onOpenChange={setOpen}
      >
        <PopoverAnchor asChild>
          <span
            ref={field}
            className={cn(
              "flex h-control items-center gap-2 rounded-sm border border-border bg-surface px-2.5 focus-within:border-accent",
              className,
            )}
          >
            <Search
              aria-hidden="true"
              className="size-3.5 shrink-0 text-text-subtle"
            />
            <CommandPrimitive.Input
              ref={input}
              value={query}
              maxLength={LONGEST_QUERY}
              placeholder={placeholder}
              onValueChange={(value) => {
                setQuery(value);
                setOpen(true);
              }}
              onFocus={() => setOpen(true)}
              className="min-w-0 grow bg-transparent text-cell text-text outline-none placeholder:text-text-subtle"
            />
            {shortcutKey ? (
              <kbd className="rounded-[3px] border border-border px-[5px] font-mono text-caption leading-4 text-text-subtle">
                {shortcutKey}
              </kbd>
            ) : null}
          </span>
        </PopoverAnchor>
        <PopoverContent
          align="end"
          onOpenAutoFocus={(event) => event.preventDefault()}
          onInteractOutside={(event) => {
            // The field is outside the list but belongs with it.
            if (field.current?.contains(event.target as Node)) {
              event.preventDefault();
            }
          }}
          className="flex w-[460px] flex-col gap-2 rounded-sm border-border-strong bg-surface-raised p-3 text-text shadow-none"
        >
          {isError ? (
            <p className="px-2 text-cell text-text-muted">
              Search is unavailable
            </p>
          ) : data?.length === 0 && !isPlaceholderData ? (
            <p className="px-2 text-cell text-text-muted">
              No instrument matches “{asked}”
            </p>
          ) : (
            <Refetch isRefetching={isFetching && isPlaceholderData}>
              <CommandList className="flex max-h-none flex-col gap-0.5">
                {data?.map((match) => (
                  <CommandItem
                    key={match.isin}
                    value={match.isin}
                    onSelect={() => open(match.isin)}
                    className="gap-2.5 rounded-[3px] p-2 text-text data-[selected=true]:bg-surface-sunken data-[selected=true]:text-text"
                  >
                    <span className="flex min-w-0 grow flex-col gap-px">
                      <span className="truncate text-cell font-medium">
                        {match.display_name}
                      </span>
                      <span className="font-mono text-caption text-text-subtle">
                        {match.symbol ?? match.isin}
                      </span>
                    </span>
                    <span className="flex gap-1">
                      {match.venues.map((venue) => (
                        <VenueBadge key={venue} venue={venue} />
                      ))}
                    </span>
                  </CommandItem>
                ))}
              </CommandList>
            </Refetch>
          )}
        </PopoverContent>
      </Popover>
    </Command>
  );
}
