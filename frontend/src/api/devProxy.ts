export const DEV_API_TARGET = "http://127.0.0.1:8766";

export function devProxyOrigin(
  origin: string | undefined,
  host: string | undefined,
) {
  return host && origin === `http://${host}` ? DEV_API_TARGET : origin;
}
