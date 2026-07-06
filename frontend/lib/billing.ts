export const DOLLARS_PER_HOUR = 1;

export const TOPUP_PRESETS_CENTS = [1000, 2500, 5000];
export const MIN_TOPUP_CENTS = 500;
export const MAX_TOPUP_CENTS = 100_000;

export function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}
