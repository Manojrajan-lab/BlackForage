export const cn = (...c: Array<string | false | null | undefined>): string => c.filter(Boolean).join(" ");
