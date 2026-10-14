import type { ReactNode } from "react";

type PageHeaderProps = Readonly<{
  title: string;
  leading?: ReactNode;
  trailing?: ReactNode;
}>;

export function PageHeader({ title, leading, trailing }: PageHeaderProps) {
  return (
    <div className="flex min-h-control items-center justify-between gap-4">
      <div className="flex items-center gap-4">
        <h1 className="text-title text-text">{title}</h1>
        {leading}
      </div>
      {trailing ? (
        <div className="flex items-center gap-2.5">{trailing}</div>
      ) : null}
    </div>
  );
}
