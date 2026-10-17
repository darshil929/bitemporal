// Where the figures come from, and the chart library's attribution its licence requires.
export function PageFooter() {
  return (
    <footer className="flex justify-between gap-6 border-t border-border pt-4 text-caption text-text-subtle">
      <p>
        Prices from BSE and NSE bhavcopies. Adjusted series derived from
        corporate actions reported by BSE.
      </p>
      <p>
        Charts by TradingView Lightweight Charts,{" "}
        <a href="https://www.tradingview.com" className="text-accent">
          tradingview.com
        </a>
      </p>
    </footer>
  );
}
