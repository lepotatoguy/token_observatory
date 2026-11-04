import type { Session, UsageEvent } from "../types/session";
import type { Pricing } from "../types/snapshot";
import { eventTotal } from "./tokens";
export const money = (n: number) =>
  n >= 100 ? `$${Math.round(n).toLocaleString()}` : `$${n.toFixed(2)}`;
export function eventPricing(
  e: UsageEvent,
  model: string,
  provider: string,
  pricing?: Pricing,
) {
  const entry = pricing?.models?.find((p) => {
      try {
        return new RegExp(p.match).test((e.model || model || "").toLowerCase());
      } catch {
        return false;
      }
    }),
    total = eventTotal(e),
    local =
      ["ollama", "lmstudio", "llamacpp"].includes(provider) || !!entry?.local;
  if (local)
    return { cost: 0, unreported: false, local: true, pricedTokens: total };
  if (!entry)
    return { cost: 0, unreported: total > 0, local: false, pricedTokens: 0 };
  const prompt = (e.input || 0) + (e.cached || 0) + (e.write || 0),
    rates =
      entry.long_rates && prompt > (entry.long_prompt ?? 100000)
        ? entry.long_rates
        : entry.rates,
    write1h = Math.min(Number(e.write_1h) || 0, e.write || 0),
    tokens = [
      e.input || 0,
      (e.write || 0) - write1h,
      write1h,
      e.cached || 0,
      e.output || 0,
    ];
  let cost = 0,
    pricedTokens = 0,
    unreported = false;
  tokens.forEach((count, i) => {
    if (!count) return;
    const rate = rates[i];
    if (rate == null || !Number.isFinite(rate)) {
      unreported = true;
      return;
    }
    cost += (count * rate) / 1e6;
    pricedTokens += count;
  });
  return { cost, unreported, local: false, pricedTokens };
}
export function eventCost(
  e: UsageEvent,
  model: string,
  pricing?: Pricing,
  provider = "",
) {
  return eventPricing(e, model, provider, pricing).cost;
}
export function costOf(sessions: Session[], pricing?: Pricing) {
  let cost = 0,
    pricedTokens = 0,
    pricedUpdates = 0,
    localTokens = 0;
  const unpriced = new Set<string>();
  for (const s of sessions)
    for (const e of s.events) {
      const p = eventPricing(e, s.model, s.provider, pricing);
      cost += p.cost;
      pricedTokens += p.pricedTokens;
      if (p.unreported) unpriced.add(e.model || s.model || "Unreported");
      else pricedUpdates++;
      if (p.local) localTokens += eventTotal(e);
    }
  return {
    cost,
    unpriced: [...unpriced],
    pricedTokens,
    pricedUpdates,
    localTokens,
  };
}
