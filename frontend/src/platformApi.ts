export type Account = {
  id: string;
  username: string;
  nickname: string;
  preferredPalette: string | null;
  role: "user" | "admin";
};

export type AccountSession = { user: Account | null; csrfToken: string | null };

export async function fetchPlatformResource(url: string, options: RequestInit): Promise<Response> {
  try {
    return await fetch(url, options);
  } catch (error) {
    if (error instanceof TypeError || (error instanceof DOMException && error.name === "TimeoutError")) {
      throw Error("无法连接本机服务，请检查连接后重试");
    }
    throw error;
  }
}

export async function platformApi<T>(path: string, options: RequestInit = {}, session?: AccountSession): Promise<T> {
  const headers = new Headers(options.headers);
  if (session?.user) {
    headers.set("X-Bead-Account", session.user.id);
    if (session.csrfToken) headers.set("X-CSRF-Token", session.csrfToken);
  }
  const response = await fetchPlatformResource("/api" + path, { ...options, headers, cache: "no-store" });
  if (response.status === 204) return undefined as T;
  const result = await response.json().catch(() => null);
  if (!response.ok) {
    throw Object.assign(Error(typeof result?.detail === "string" ? result.detail : "服务暂不可用"),
      { status: response.status, code: result?.code });
  }
  return result as T;
}

export function jsonRequest(method: string, value: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(value) };
}

export async function readAsset(id: string | null, session: AccountSession): Promise<string | undefined> {
  if (!id) return undefined;
  const response = await fetchPlatformResource("/api/assets/" + encodeURIComponent(id) + "/content", {
    cache: "no-store",
    headers: { "X-Bead-Account": session.user!.id },
  });
  if (!response.ok) throw Error("无法读取项目图片");
  const blob = await response.blob();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(Error("无法读取项目图片"));
    reader.readAsDataURL(blob);
  });
}
