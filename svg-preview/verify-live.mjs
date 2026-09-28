import assert from 'node:assert/strict';
import {APPROVED,LIVE_CELL,LIVE_GRID,createLiveAtlas,liveCount,liveHost,slotFor} from './live.mjs';

// New glyphs fill the 64 empty slots after the approved 192, then replace every slot in turn.
assert.deepEqual(LIVE_GRID,[16,16]);assert.equal(LIVE_CELL,128);assert.equal(APPROVED,192);
assert.equal(slotFor(0),192);assert.equal(slotFor(63),255);
assert.equal(slotFor(64),0);assert.equal(slotFor(64+191),191);assert.equal(slotFor(64+255),255);assert.equal(slotFor(64+256),0);
const firstRound=Array.from({length:256},(_,n)=>slotFor(64+n));
assert.deepEqual([...firstRound].sort((a,b)=>a-b),Array.from({length:256},(_,n)=>n));
for(const bad of [-1,1.5,NaN,'3'])assert.throws(()=>slotFor(bad),RangeError);
assert.equal(liveCount(0),192);assert.equal(liveCount(10),202);assert.equal(liveCount(64),256);assert.equal(liveCount(10000),256);

// Only this machine serves live glyphs; a public page never asks for them.
for(const host of ['127.0.0.1','localhost','[::1]'])assert.equal(liveHost(host),true,host);
for(const host of ['noumenon.cc','example.test','192.168.1.2','',undefined])assert.equal(liveHost(host),false,String(host));

// The atlas starts from the approved atlas, places each streamed tile in its slot,
// and updates every live texture in place.
const drawn=[],cleared=[],uploads=[],requests=[];
const context={fillStyle:'',fillRect(){},drawImage:(image,x=0,y=0)=>drawn.push([image.url,x,y]),clearRect:(x,y)=>cleared.push([x,y])};
const document={createElement:()=>({width:0,height:0,getContext:()=>context})};
let pending=[{seq:1,tile:'/live/tiles/1.png'},{seq:2,tile:'/live/tiles/2.png'}];
const fetch=async url=>{
  requests.push(url);
  if(url==='/live/status')return {ok:true,json:async()=>({session:'test'})};
  const glyphs=pending;pending=[];return {ok:true,json:async()=>({latest:2,glyphs})};
};
const changes=[];
const atlas=createLiveAtlas({document,fetch,baseAtlasURL:'generated-sdf.png',pollMs:1,
  loadImage:async url=>({url}),onChange:change=>changes.push(change)});
const regl={texture:options=>({options,subimage:(data,x,y)=>uploads.push([data.data.url,x,y])})};
const source=atlas.source(regl);await source.loaded;
assert.equal(source.width(),2048);assert.equal(source.texture().options.flipY,true);
assert.equal(await atlas.probe(),true);
atlas.start();
for(let i=0;i<50&&atlas.received()<2;i++)await new Promise(resolve=>setTimeout(resolve,5));
atlas.stop();
assert.equal(atlas.received(),2);assert.equal(atlas.count,194);
assert.deepEqual(drawn[0],['generated-sdf.png',0,0]);
// Slot 192 is column 0 of row 12; the texture is flipped, so its rows count from the bottom.
assert.deepEqual(drawn.slice(1),[['/live/tiles/1.png',0,1536],['/live/tiles/2.png',128,1536]]);
assert.deepEqual(uploads,[['/live/tiles/1.png',0,2048-1536-128],['/live/tiles/2.png',128,2048-1536-128]]);
assert.deepEqual(changes.at(-1),{count:194,received:2,latest:2});
assert.ok(requests.includes('/live/glyphs?after=0'));
console.log('live atlas: slots, host gate and streaming verified');
