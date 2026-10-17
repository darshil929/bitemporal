// What the application's output is and is not, read before anything else is reachable and in every
// page's footer.
export const DISCLAIMER =
  "This system is a research and analysis tool for an individual or an organisation on its internal network. " +
  "It produces evidence and component scores, not investment advice. Nothing it outputs constitutes a " +
  "recommendation to buy or sell any security. Serving its outputs to others may bring it within the scope of " +
  "SEBI's Investment Adviser and Research Analyst regulations, which the owner reviews before the deployment " +
  "serves anyone beyond themselves.";

export function Disclaimer() {
  return (
    <aside className="flex flex-col gap-1.5 rounded-sm border border-border bg-surface-sunken px-card py-3.5">
      <h2 className="text-header font-semibold text-text-muted">Disclaimer</h2>
      <p className="text-cell leading-[1.55] text-text-muted">{DISCLAIMER}</p>
    </aside>
  );
}
