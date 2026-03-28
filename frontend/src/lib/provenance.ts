/**
 * Compute a deterministic SHA-256 hash of a parameter dictionary.
 * Keys are sorted to ensure the same params always produce the same hash.
 */
export async function computeParamHash(params: Record<string, unknown>): Promise<string> {
  const sorted = Object.keys(params)
    .sort()
    .reduce<Record<string, unknown>>((acc, k) => {
      acc[k] = params[k];
      return acc;
    }, {});
  const data = new TextEncoder().encode(JSON.stringify(sorted));
  const buf = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 16);
}
