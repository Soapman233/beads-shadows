import test from 'node:test';import assert from 'node:assert/strict';import {createRequire} from 'node:module';
createRequire(new URL('../frontend/package.json',import.meta.url))('fake-indexeddb/auto');
import {storeDraft,readDraft,migrateDraft,listProjects,loadProject,saveProject} from '../frontend/src/storage';import type {Project} from '../frontend/src/project';
test('legacy draft migrates by copy once; independent project resources and recoverable deletion survive',async()=>{
 const p:Project={schemaVersion:2,pattern:{width:1,height:1,cells:['H2'],palette:[{code:'H2',hex:'#FFFFFF'}],colorLimit:1,paletteName:'fixture'},points:[],locked:[],step:3,pitch:2.6,selectionMode:'whole',selectionDirty:false};
 await storeDraft(p);await migrateDraft();await migrateDraft();assert.equal((await listProjects()).length,1);assert.deepEqual(await readDraft(),p);assert.deepEqual((await loadProject('legacy-draft')).project.pattern?.cells,['H2']);
 const row={id:'second',name:'two',createdAt:1,updatedAt:2,project:{...p,source:'data:image/png;base64,AAAA'}};await saveProject(row);assert.equal((await loadProject('second')).project.source,row.project.source);assert.equal((await loadProject('legacy-draft')).project.source,undefined);
 await saveProject({...row,deleted:3});assert.equal((await loadProject('second')).deleted,3);await saveProject(row);assert.equal((await loadProject('second')).deleted,undefined);
 await assert.rejects(()=>saveProject({...row,project:{...p,pattern:{...p.pattern!,cells:['unknown']}}}));assert.deepEqual((await loadProject('second')).project.pattern?.cells,['H2']);
});
