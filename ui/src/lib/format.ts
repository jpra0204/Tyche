// Formatting shared by every page. Amounts arrive as exact decimal strings.

export function money(amount: string, currency: string): string {
  const value = Number(amount);
  if (!Number.isFinite(value)) return `${amount} ${currency}`;
  return `${value.toLocaleString("en-CA", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

export function percent(fraction: string): string {
  const value = Number(fraction);
  if (!Number.isFinite(value)) return fraction;
  return `${(value * 100).toLocaleString("en-CA", { maximumFractionDigits: 2 })}%`;
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-CA", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
