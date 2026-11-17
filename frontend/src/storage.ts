import { validateProject, type Project } from "./project";
export type SavedProject = {
  id: string;
  name: string;
  createdAt: number;
  updatedAt: number;
  deleted?: number;
  thumbnail?: string;
  project: Project;
};
function db(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    let blocked = false;
    const r = indexedDB.open("bead-lab", 2);
    r.onupgradeneeded = () => {
      for (const name of ["draft", "projects", "resources"])
        if (!r.result.objectStoreNames.contains(name))
          r.result.createObjectStore(name);
    };
    r.onblocked = () => {
      blocked = true;
      reject(Error("请关闭其他豆影标签页后重试"));
    };
    r.onsuccess = () => {
      if (blocked) {
        r.result.close();
        return;
      }
      r.result.onversionchange = () => r.result.close();
      resolve(r.result);
    };
    r.onerror = () => reject(r.error ?? Error("无法打开项目库"));
  });
}
async function transaction<T>(
  stores: string[],
  mode: IDBTransactionMode,
  action: (t: IDBTransaction, set: (v: T) => void) => void,
): Promise<T> {
  const d = await db();
  try {
    return await new Promise<T>((resolve, reject) => {
      const t = d.transaction(stores, mode);
      let value: T;
      t.oncomplete = () => resolve(value);
      t.onerror = () => reject(t.error ?? Error("项目读写失败"));
      t.onabort = () => reject(t.error ?? Error("项目事务已取消"));
      try {
        action(t, (v) => (value = v));
      } catch (e) {
        t.abort();
        reject(e);
      }
    });
  } finally {
    d.close();
  }
}
let writes = Promise.resolve();
function enqueue(action: () => Promise<void>) {
  const result = writes.catch(() => {}).then(action);
  writes = result;
  return result;
}
export async function storeDraft(project: Project) {
  await transaction<void>(["draft"], "readwrite", (t) => {
    t.objectStore("draft").put(project, "current");
  });
}
export async function readDraft(): Promise<unknown> {
  return transaction(["draft"], "readonly", (t, set) => {
    const r = t.objectStore("draft").get("current");
    r.onsuccess = () => set(r.result);
  });
}
// Project-owned resources; direct equality skips unchanged payload writes without hashes.
export async function saveProject(row: SavedProject) {
  const p = validateProject(row.project);
  if (
    typeof row.id !== "string" ||
    !row.id ||
    !Number.isFinite(row.createdAt) ||
    !Number.isFinite(row.updatedAt)
  )
    return Promise.reject(Error("项目身份无效"));
  const snapshot = structuredClone({
    ...row,
    name: row.name.trim().slice(0, 80) || "未命名",
    project: p,
  });
  return enqueue(() =>
    transaction<void>(["projects", "resources"], "readwrite", (t) => {
      const projects = t.objectStore("projects"),
        resources = t.objectStore("resources"),
        old = projects.get(row.id);
      old.onsuccess = () =>
        projects.put(
          {
            ...snapshot,
            thumbnail: snapshot.thumbnail ?? old.result?.thumbnail,
            project: { ...p, source: undefined, mask: undefined },
            hasSource: !!p.source,
            hasMask: !!p.mask,
          },
          row.id,
        );
      for (const key of ["source", "mask"] as const) {
        const id = row.id + ":" + key,
          r = resources.get(id);
        r.onsuccess = () => {
          if (p[key] !== r.result) {
            if (p[key]) resources.put(p[key], id);
            else resources.delete(id);
          }
        };
      }
    }),
  );
}
export async function listProjects(): Promise<SavedProject[]> {
  await writes.catch(() => {});
  return transaction(["projects"], "readonly", (t, set) => {
    const r = t.objectStore("projects").getAll();
    r.onsuccess = () =>
      set(
        r.result.sort(
          (a: SavedProject, b: SavedProject) => b.updatedAt - a.updatedAt,
        ),
      );
  });
}
export async function loadProject(id: string): Promise<SavedProject> {
  await writes.catch(() => {});
  return transaction(["projects", "resources"], "readonly", (t, set) => {
    const r = t.objectStore("projects").get(id);
    r.onsuccess = () => {
      if (!r.result) {
        t.abort();
        return;
      }
      const row = r.result,
        a = t.objectStore("resources").get(id + ":source"),
        b = t.objectStore("resources").get(id + ":mask");
      b.onsuccess = () => {
        try {
          if ((row.hasSource && !a.result) || (row.hasMask && !b.result))
            throw Error("图片资源缺失");
          set({
            ...row,
            project: validateProject({
              ...row.project,
              source: a.result,
              mask: b.result,
            }),
          });
        } catch {
          t.abort();
        }
      };
    };
  });
}
export function migrateDraft() {
  return enqueue(() =>
    transaction<void>(["draft", "projects", "resources"], "readwrite", (t) => {
      const projects = t.objectStore("projects"),
        r = projects.get("legacy-draft");
      r.onsuccess = () => {
        if (r.result) return;
        const old = t.objectStore("draft").get("current");
        old.onsuccess = () => {
          if (!old.result) return;
          try {
            const p = validateProject(old.result),
              now = Date.now();
            for (const key of ["source", "mask"] as const)
              if (p[key])
                t.objectStore("resources").put(p[key], "legacy-draft:" + key);
            projects.put(
              {
                id: "legacy-draft",
                name: "旧草稿备份",
                createdAt: now,
                updatedAt: now,
                hasSource: !!p.source,
                hasMask: !!p.mask,
                project: { ...p, source: undefined, mask: undefined },
              },
              "legacy-draft",
            );
          } catch {
            t.abort();
          }
        };
      };
    }),
  );
}
export function getActiveProject() {
  try {
    return localStorage.getItem("bead-active-project");
  } catch {
    return null;
  }
}
export function setActiveProject(id: string) {
  try {
    localStorage.setItem("bead-active-project", id);
  } catch {}
}
