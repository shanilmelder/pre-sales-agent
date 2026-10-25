// `?page=` parsing for the paginated lists. Safe on server and client.

/** `?page=` as a positive integer (1 for anything else). */
export function parsePage(value: string | string[] | undefined): number {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw || !/^[1-9]\d{0,5}$/.test(raw)) return 1;
  return Number(raw);
}
