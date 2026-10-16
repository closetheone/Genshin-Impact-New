const DEFAULT_BACKEND = "http://127.0.0.1:4175";

export const backendUrl = process.env.PYTHON_API_URL || DEFAULT_BACKEND;

export function backendHeaders(contentType?: string) {
  const target = new URL(backendUrl);
  const headers = new Headers({ Host: target.host, Origin: backendUrl });
  if (contentType) headers.set("Content-Type", contentType);
  return headers;
}
