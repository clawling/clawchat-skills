import type { Language } from "$lib/types";

export function currencyDecimals(currency: string): number {
  return currency.toUpperCase() === "JPY" ? 0 : 2;
}

export function formatMoney(
  amountMinor: number,
  currency: string,
  language: Language = "en",
): string {
  const code = currency.toUpperCase();
  const amount = amountMinor / (10 ** currencyDecimals(code));
  const locale = language === "zh" ? "zh-CN" : "en-US";
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency: code,
      currencyDisplay: "narrowSymbol",
      minimumFractionDigits: currencyDecimals(code),
      maximumFractionDigits: currencyDecimals(code),
    }).format(amount);
  } catch {
    return `${code} ${amount.toFixed(currencyDecimals(code))}`;
  }
}

export function formatMoneyWithCode(
  amountMinor: number,
  currency: string,
  language: Language = "en",
): string {
  const code = currency.toUpperCase();
  return `${formatMoney(amountMinor, code, language)} ${code}`;
}

export function formatMonth(month: string, language: Language = "en"): string {
  const match = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(month);
  if (!match) return month;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1));
  return new Intl.DateTimeFormat(language === "zh" ? "zh-CN" : "en-US", {
    month: "long",
    timeZone: "UTC",
    year: "numeric",
  }).format(date);
}

export function formatDate(value: string, language: Language = "en"): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return new Intl.DateTimeFormat(language === "zh" ? "zh-CN" : "en-US", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
    year: "numeric",
  }).format(date);
}

export function formatPercent(value: number, language: Language = "en"): string {
  return new Intl.NumberFormat(language === "zh" ? "zh-CN" : "en-US", {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
    style: "percent",
  }).format(value / 100);
}

export function formatWeekRange(
  startDate: string,
  endDate: string,
  language: Language = "en",
): string {
  const locale = language === "zh" ? "zh-CN" : "en-US";
  const parse = (value: string) => {
    const [year, month, day] = value.split("-").map(Number);
    return new Date(Date.UTC(year, month - 1, day));
  };
  const formatter = new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
  if (startDate === endDate) return formatter.format(parse(startDate));
  return `${formatter.format(parse(startDate))}–${formatter.format(parse(endDate))}`;
}

export function formatInteger(value: number, language: Language = "en"): string {
  return new Intl.NumberFormat(language === "zh" ? "zh-CN" : "en-US", {
    maximumFractionDigits: 0,
  }).format(value);
}
