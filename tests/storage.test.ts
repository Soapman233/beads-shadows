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
  let revision = await saveProject(row,0);
  assert.equal(
    (await loadProject("second")).project.source,
    row.project.source,
  );
  assert.equal((await loadProject("legacy-draft")).project.source, undefined);
  revision = await saveProject({ ...row, deleted: 3 },revision);
  assert.equal((await loadProject("second")).deleted, 3);
  revision = await saveProject(row,revision);
  assert.equal((await loadProject("second")).deleted, undefined);
  await assert.rejects(() =>
    saveProject({
      ...row,
      project: { ...p, pattern: { ...p.pattern!, cells: ["unknown"] } },
    },revision),
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
  const revision = await saveProject(row,0);
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
      },revision),
    );
  } finally {
    IDBObjectStore.prototype.put = put;
  }
  const after = await loadProject(row.id);
  assert.equal(after.name, "safe");
  assert.equal(after.project.source, row.project.source);
  await saveProject({ ...row, name: "recovered" },revision);
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
    let revision = await saveProject(row,0);
    assert.equal(resourcePuts, 2);
    assert.equal(characters, source.length + mask.length);
    resourcePuts = 0;
    characters = 0;
    revision = await saveProject({ ...row, name: "renamed", updatedAt: 3 },revision);
    revision = await saveProject({
      ...row,
      updatedAt: 4,
      project: {
        ...row.project,
        pattern: { ...row.project.pattern!, cells: [null] },
      },
    },revision);
    assert.equal(resourcePuts, 0);
    assert.equal(characters, 0);
    t.diagnostic(
      `initial resource puts=2, payload characters=${source.length + mask.length}; two metadata saves resource puts=0, characters=0`,
    );
    revision = await saveProject({
      ...row,
      project: { ...row.project, mask: "data:image/png;base64,CCCC" },
    },revision);
    assert.equal(resourcePuts, 1);
    await saveProject({ ...row, id: "write-copy",revision:0 });
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

test("two snapshots with the same revision cannot overwrite the winning cells or resources",async()=>{
  const row={id:'cas-race',name:'base',createdAt:1,updatedAt:2,project:{...fixture(),source:'data:image/png;base64,AAAA',mask:'data:image/png;base64,BBBB'}};
  const revision=await saveProject(row,0);
  assert.equal(revision,1);
  const left={...structuredClone(row),revision,name:'winner',project:{...structuredClone(row.project),source:'data:image/png;base64,CCCC',mask:'data:image/png;base64,DDDD',pattern:{...row.project.pattern!,cells:[null]}}};
  const right={...structuredClone(row),revision,name:'stale',project:{...structuredClone(row.project),source:'data:image/png;base64,EEEE',mask:'data:image/png;base64,FFFF'}};
  const [first,second]=await Promise.allSettled([saveProject(left),saveProject(right)]);
  assert.equal(first.status,'fulfilled');
  assert.equal(second.status,'rejected');
  if(second.status==='rejected')assert.equal(second.reason.name,'ProjectConflictError');
  const after=await loadProject(row.id);
  assert.equal(after.revision,2);assert.equal(after.name,'winner');
  assert.deepEqual(after.project.pattern!.cells,[null]);
  assert.equal(after.project.source,'data:image/png;base64,CCCC');
  assert.equal(after.project.mask,'data:image/png;base64,DDDD');
  await assert.rejects(()=>saveProject({...right,name:'omitted revision',revision:undefined}),{name:'ProjectConflictError'});
  assert.deepEqual((await loadProject(row.id)).project,after.project);
});

test("copying a saved project to a new id starts revision zero and keeps the original independent",async()=>{
  const original={id:'cas-original',name:'original',createdAt:1,updatedAt:2,project:{...fixture(),source:'data:image/png;base64,AAAA',mask:'data:image/png;base64,BBBB'}};
  const revision=await saveProject(original,0);
  const loaded=await loadProject(original.id);
  const copy={...loaded,id:'cas-copy',name:'copy',revision:0};
  assert.equal(await saveProject(copy),1);
  assert.equal(await saveProject({...copy,revision:1,project:{...copy.project,pattern:{...copy.project.pattern!,cells:[null]},mask:'data:image/png;base64,CCCC'}}),2);
  const after=await loadProject(original.id),savedCopy=await loadProject(copy.id);
  assert.equal(after.revision,revision);assert.deepEqual(after.project.pattern!.cells,['H2']);
  assert.equal(after.project.mask,original.project.mask);
  assert.equal(savedCopy.revision,2);assert.deepEqual(savedCopy.project.pattern!.cells,[null]);
  assert.equal(savedCopy.project.mask,'data:image/png;base64,CCCC');
});
