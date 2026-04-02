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
  const payload = JSON.stringify(sorted);
  const data = new TextEncoder().encode(payload);
  const subtle = globalThis.crypto?.subtle;
  if (subtle?.digest) {
    const buf = await subtle.digest("SHA-256", data);
    return Array.from(new Uint8Array(buf))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("")
      .slice(0, 16);
  }
  let hash = 0xcbf29ce484222325n;
  const prime = 0x100000001b3n;
  for (const b of data) {
    hash ^= BigInt(b);
    hash = (hash * prime) & 0xffffffffffffffffn;
  }
  return hash.toString(16).padStart(16, "0");
}
