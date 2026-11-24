import { validateProject, type Project } from "./project";
export type SavedProject = {
  id: string;
  name: string;
  createdAt: number;
  updatedAt: number;
  revision?: number;
  deleted?: number;
  thumbnail?: string;
  cloud?: { id: string; revision: number; pending?: boolean };
  project: Project;
};
export class ProjectConflictError extends Error {
  constructor() { super("此项目已在其他页面更新，请另存副本以保留当前修改"); this.name = "ProjectConflictError"; }
}
export function createProjectStorage(suffix = "") {
  const activeKey = suffix ? "bead-active-project:" + suffix : "bead-active-project";
  function db(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
      let blocked = false;
      const r = indexedDB.open(suffix ? "bead-lab:" + suffix : "bead-lab", 2);
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
    action: (t: IDBTransaction, set: (v: T) => void, fail: (e: Error) => void) => void,
  ): Promise<T> {
    const d = await db();
    try {
      return await new Promise<T>((resolve, reject) => {
        const t = d.transaction(stores, mode);
        let value: T;
        let reason: Error | undefined;
        t.oncomplete = () => resolve(value);
        t.onerror = () => reject(reason ?? t.error ?? Error("项目读写失败"));
        t.onabort = () => reject(reason ?? t.error ?? Error("项目事务已取消"));
        try {
          action(t, (v) => (value = v), e => { reason = e; t.abort(); });
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
  function enqueue<T>(action: () => Promise<T>) {
    const result = writes.catch(() => {}).then(action);
    writes = result.then(() => {}, () => {});
    return result;
  }
  async function storeDraft(project: Project) {
    await transaction<void>(["draft"], "readwrite", (t) => {
      t.objectStore("draft").put(project, "current");
    });
  }
  async function readDraft(): Promise<unknown> {
    return transaction(["draft"], "readonly", (t, set) => {
      const r = t.objectStore("draft").get("current");
      r.onsuccess = () => set(r.result);
    });
  }
  // Project-owned resources; direct equality skips unchanged payload writes without hashes.
  async function saveProject(row: SavedProject, expectedRevision = row.revision ?? 0) {
    const p = validateProject(row.project);
    if (
      typeof row.id !== "string" ||
      !row.id ||
      !Number.isFinite(row.createdAt) ||
      !Number.isFinite(row.updatedAt) ||
      !Number.isInteger(expectedRevision) || expectedRevision < 0 ||
      typeof row.name !== "string"
    )
      return Promise.reject(Error("项目身份无效"));
    const snapshot = structuredClone({
      ...row,
      name: row.name.trim().slice(0, 80) || "未命名",
      project: p,
    });
    return enqueue(() =>
      transaction<number>(["projects", "resources"], "readwrite", (t, set, fail) => {
        const projects = t.objectStore("projects"),
          resources = t.objectStore("resources"),
          old = projects.get(snapshot.id);
        old.onsuccess = () => {
          if ((old.result?.revision ?? 0) !== expectedRevision || (!old.result && expectedRevision !== 0)) {
            fail(new ProjectConflictError());
            return;
          }
          projects.put(
            {
              ...snapshot,
              revision: expectedRevision + 1,
              thumbnail: snapshot.thumbnail ?? old.result?.thumbnail,
              project: { ...snapshot.project, source: undefined, mask: undefined },
              hasSource: !!snapshot.project.source,
              hasMask: !!snapshot.project.mask,
            },
            snapshot.id,
          );
          set(expectedRevision + 1);
        };
        for (const key of ["source", "mask"] as const) {
          const id = snapshot.id + ":" + key,
            r = resources.get(id);
          r.onsuccess = () => {
            if (snapshot.project[key] !== r.result) {
              if (snapshot.project[key]) resources.put(snapshot.project[key], id);
              else resources.delete(id);
            }
          };
        }
      }),
    );
  }
  async function listProjects(): Promise<SavedProject[]> {
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
  async function loadProject(id: string): Promise<SavedProject> {
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
  function migrateDraft() {
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
  function getActiveProject() {
    try {
      return localStorage.getItem(activeKey);
    } catch {
      return null;
    }
  }
  function setActiveProject(id: string) {
    try {
      localStorage.setItem(activeKey, id);
    } catch {}
  }
  return { storeDraft, readDraft, saveProject, listProjects, loadProject, migrateDraft, getActiveProject, setActiveProject };
}
export type ProjectStorage = ReturnType<typeof createProjectStorage>;
export const { storeDraft, readDraft, saveProject, listProjects, loadProject, migrateDraft, getActiveProject, setActiveProject } = createProjectStorage();
