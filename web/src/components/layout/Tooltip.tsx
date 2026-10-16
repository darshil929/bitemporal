import type { ReactElement } from "react";

import {
  TooltipContent,
  TooltipProvider,
  Tooltip as TooltipRoot,
  TooltipTrigger,
} from "@/components/ui/tooltip";

type TooltipProps = Readonly<{
  text: string;
  children: ReactElement;
}>;

// A short note on what the element it describes means, dark on the page in either theme.
export function Tooltip({ text, children }: TooltipProps) {
  return (
    <TooltipProvider>
      <TooltipRoot>
        <TooltipTrigger asChild>{children}</TooltipTrigger>
        <TooltipContent className="rounded-[3px] bg-text px-2 py-1.5 text-caption leading-[1.4] text-surface">
          {text}
        </TooltipContent>
      </TooltipRoot>
    </TooltipProvider>
  );
}
