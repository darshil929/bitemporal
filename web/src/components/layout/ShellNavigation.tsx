"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "cn";

const PAGES = [
  { href: "/", label: "Dashboard" },
  { href: "/screener", label: "Screener" },
  { href: "/watchlist", label: "Watchlist" },
] as const;

function isOpen(href: string, pathname: string): boolean {
  return href === "/"
    ? pathname === "/"
    : pathname === href || pathname.startsWith(`${href}/`);
}

export function ShellNavigation() {
  const pathname = usePathname();

  return (
    <nav aria-label="Pages" className="flex items-center gap-6">
      {PAGES.map(({ href, label }) => {
        const open = isOpen(href, pathname);
        return (
          <Link
            key={href}
            href={href}
            aria-current={open ? "page" : undefined}
            className={cn(
              "flex h-14 items-center border-b-2 pt-0.5 text-body",
              open
                ? "border-accent font-semibold text-text"
                : "border-transparent font-medium text-text-muted",
            )}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
