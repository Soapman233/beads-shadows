import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
createRequire(new URL("../frontend/package.json", import.meta.url))(
  "fake-indexeddb/auto",
);
import {
  storeDraft,
  readDraft,
  migrateDraft,
  listProjects,
  loadProject,
  saveProject,
} from "../frontend/src/storage";
import type { Project } from "../frontend/src/project";
test("legacy draft migrates by copy once; independent project resources and recoverable deletion survive", async () => {
  const p: Project = {
    schemaVersion: 2,
    pattern: {
      width: 1,
      height: 1,
      cells: ["H2"],
      palette: [{ code: "H2", hex: "#FFFFFF" }],
      colorLimit: 1,
      paletteName: "fixture",
    },
    points: [],
    locked: [],
    step: 3,
    pitch: 2.6,
    selectionMode: "whole",
    selectionDirty: false,
  };
  await storeDraft(p);
  await Promise.all([migrateDraft(), migrateDraft()]);
  assert.equal((await listProjects()).length, 1);
  assert.deepEqual(await readDraft(), p);
  assert.deepEqual((await loadProject("legacy-draft")).project.pattern?.cells, [
    "H2",
  ]);
  const row = {
    id: "second",
    name: "two",
    createdAt: 1,
    updatedAt: 2,
    project: { ...p, source: "data:image/png;base64,AAAA" },
  };
  await saveProject(row);
  assert.equal(
    (await loadProject("second")).project.source,
    row.project.source,
  );
  assert.equal((await loadProject("legacy-draft")).project.source, undefined);
  await saveProject({ ...row, deleted: 3 });
  assert.equal((await loadProject("second")).deleted, 3);
  await saveProject(row);
  assert.equal((await loadProject("second")).deleted, undefined);
  await assert.rejects(() =>
    saveProject({
      ...row,
      project: { ...p, pattern: { ...p.pattern!, cells: ["unknown"] } },
    }),
  );
  assert.deepEqual((await loadProject("second")).project.pattern?.cells, [
    "H2",
  ]);
});

const fixture = (): Project => ({
  schemaVersion: 2,
  pattern: {
    width: 1,
    height: 1,
    cells: ["H2"],
    palette: [{ code: "H2", hex: "#FFFFFF" }],
    colorLimit: 1,
    paletteName: "fixture",
  },
  points: [],
  locked: [],
  step: 3,
  pitch: 2.6,
  selectionMode: "whole",
  selectionDirty: false,
});

test("queued writes capture caller state and retain thumbnail on metadata updates", async () => {
  const row = {
    id: "snapshot",
    name: "first",
    createdAt: 1,
    updatedAt: 2,
    thumbnail: "preview",
    project: {...fixture(),box:[0,0,10,10]},
  };
  const pending = saveProject(row);
  row.id = "snapshot-mutated";
  row.name = "mutated after enqueue";
  row.project.pattern!.cells[0] = null;
  row.project.box[2] = 99;
  await pending;
  let saved = await loadProject("snapshot");
  assert.equal(saved.id,"snapshot");
  assert.equal(saved.name, "first");
  assert.deepEqual(saved.project.pattern!.cells, ["H2"]);
  assert.deepEqual(saved.project.box,[0,0,10,10]);
  await assert.rejects(()=>loadProject("snapshot-mutated"));
  await saveProject({
    ...saved,
    name: "renamed",
    thumbnail: undefined,
    updatedAt: 3,
  });
  saved = await loadProject("snapshot");
  assert.equal(saved.thumbnail, "preview");
  assert.equal(saved.name, "renamed");
});

test("resource failure rolls back metadata and resources; subsequent save remains possible", async () => {
  const row = {
    id: "failure",
    name: "safe",
    createdAt: 1,
    updatedAt: 2,
    project: { ...fixture(), source: "data:image/png;base64,AAAA" },
  };
  await saveProject(row);
  const put = IDBObjectStore.prototype.put;
  IDBObjectStore.prototype.put = function (value: any, key?: IDBValidKey) {
    if (this.name === "resources" && key === "failure:source")
      throw new DOMException("Injected quota failure", "QuotaExceededError");
    return put.call(this, value, key!);
  };
  try {
    await assert.rejects(async () =>
      saveProject({
        ...row,
        name: "must roll back",
        project: { ...row.project, source: "data:image/png;base64,BBBB" },
      }),
    );
  } finally {
    IDBObjectStore.prototype.put = put;
  }
  const after = await loadProject(row.id);
  assert.equal(after.name, "safe");
  assert.equal(after.project.source, row.project.source);
  await saveProject({ ...row, name: "recovered" });
  assert.equal((await loadProject(row.id)).name, "recovered");
});

test("missing declared resource rejects instead of restoring a partial project", async () => {
  const row = {
    id: "missing",
    name: "missing",
    createdAt: 1,
    updatedAt: 2,
    project: { ...fixture(), source: "data:image/png;base64,AAAA" },
  };
  await saveProject(row);
  await new Promise<void>((resolve, reject) => {
    const request = indexedDB.open("bead-lab", 2);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const db = request.result,
        t = db.transaction(["resources"], "readwrite");
      t.objectStore("resources").delete("missing:source");
      t.oncomplete = () => {
        db.close();
        resolve();
      };
      t.onabort = () => {
        db.close();
        reject(t.error);
      };
    };
  });
  await assert.rejects(() => loadProject(row.id));
});

test("metadata saves skip unchanged resource payload writes; changed mask and copies retain independent resources", async (t) => {
  const source = "data:image/png;base64," + "A".repeat(4096),
    mask = "data:image/png;base64," + "B".repeat(1024);
  const row = {
    id: "write-count",
    name: "before",
    createdAt: 1,
    updatedAt: 2,
    project: { ...fixture(), source, mask },
  };
  const put = IDBObjectStore.prototype.put;
  let resourcePuts = 0,
    characters = 0;
  IDBObjectStore.prototype.put = function (value: any, key?: IDBValidKey) {
    if (this.name === "resources") {
      resourcePuts++;
      characters += typeof value === "string" ? value.length : 0;
    }
    return put.call(this, value, key!);
  };
  try {
    await saveProject(row);
    assert.equal(resourcePuts, 2);
    assert.equal(characters, source.length + mask.length);
    resourcePuts = 0;
    characters = 0;
    await saveProject({ ...row, name: "renamed", updatedAt: 3 });
    await saveProject({
      ...row,
      updatedAt: 4,
      project: {
        ...row.project,
        pattern: { ...row.project.pattern!, cells: [null] },
      },
    });
    assert.equal(resourcePuts, 0);
    assert.equal(characters, 0);
    t.diagnostic(
      `initial resource puts=2, payload characters=${source.length + mask.length}; two metadata saves resource puts=0, characters=0`,
    );
    await saveProject({
      ...row,
      project: { ...row.project, mask: "data:image/png;base64,CCCC" },
    });
    assert.equal(resourcePuts, 1);
    await saveProject({ ...row, id: "write-copy" });
    assert.equal(resourcePuts, 3);
    assert.equal((await loadProject("write-copy")).project.mask, mask);
    assert.equal(
      (await loadProject(row.id)).project.mask,
      "data:image/png;base64,CCCC",
    );
  } finally {
    IDBObjectStore.prototype.put = put;
  }
});
