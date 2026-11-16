import test from 'node:test';
import assert from 'node:assert/strict';
import {parseProject,validateProject} from '../frontend/src/project.ts';

const pattern={width:2,height:2,palette:[{code:'W',hex:'#FFFFFF'},{code:'B',hex:'#000000'}],cells:['W','B',null,'W'],colorLimit:2,paletteName:'测试色板'};
test('project v2 roundtrip retains editable grid and ignores external statistics',()=>{
 const p=validateProject({schemaVersion:2,pattern,locked:['W'],points:[],step:3,pitch:5,selectionMode:'whole',statistics:{total:999}});
 assert.deepEqual(parseProject(JSON.stringify(p)),p);
 assert.deepEqual(p.pattern?.cells,pattern.cells);assert.deepEqual(p.locked,['W']);
 assert.equal((p as any).statistics,undefined);
});
test('legacy project opens as grid-only and rejects invalid resources/codes/version',()=>{
 const legacy=parseProject(JSON.stringify({schemaVersion:1,...pattern,statistics:{total:999}}));
 assert.equal(legacy.schemaVersion,2);assert.equal(legacy.source,undefined);assert.deepEqual(legacy.pattern?.cells,pattern.cells);
 assert.throws(()=>validateProject({schemaVersion:9,...pattern}));
 assert.throws(()=>validateProject({schemaVersion:2,pattern:{...pattern,cells:['bad','B',null,'W']}}));
 assert.throws(()=>validateProject({schemaVersion:2,pattern,source:'https://example.com/a.png'}));
 assert.throws(()=>validateProject({schemaVersion:2,pattern:{...pattern,colorLimit:1}}));
 assert.throws(()=>validateProject({schemaVersion:2,pattern,locked:['missing']}));
});
