// Live glyph atlas: it starts with the 192 approved originals and fills with new
// glyphs streamed by `python -m live`, then replaces the oldest slots in turn,
// so the rain keeps receiving new glyphs for as long as the stream runs.
export const LIVE_GRID=Object.freeze([16,16]);
export const LIVE_CELL=128;
export const APPROVED=192;
const SLOTS=LIVE_GRID[0]*LIVE_GRID[1],SIZE=LIVE_GRID[0]*LIVE_CELL;

// The slot for the nth live glyph: the empty slots first, then every slot in turn.
export function slotFor(n){
  if(!Number.isInteger(n)||n<0)throw new RangeError('Live glyph numbers start at 0');
  return n<SLOTS-APPROVED?APPROVED+n:(n-(SLOTS-APPROVED))%SLOTS;
}
export const liveCount=received=>Math.min(SLOTS,APPROVED+received);
// `python -m live` serves the explorer on this machine only, so a public page never asks for it.
export const liveHost=hostname=>['127.0.0.1','localhost','[::1]'].includes(hostname);

export function createLiveAtlas({document,fetch,baseAtlasURL,loadImage,pollMs=1500,onChange=()=>{}}){
  const canvas=document.createElement('canvas');canvas.width=SIZE;canvas.height=SIZE;
  const context=canvas.getContext('2d');context.fillStyle='#000';context.fillRect(0,0,SIZE,SIZE);
  const textures=new Set();
  let received=0,latest=0,timer=0,running=false,busy=false;
  const ready=loadImage(baseAtlasURL).then(image=>{context.drawImage(image,0,0);});

  // A loader-shaped source for the rain pass: the texture follows the canvas.
  function source(regl){
    let texture=regl.texture([[0]]);
    const loaded=ready.then(()=>{texture=regl.texture({data:canvas,mag:'linear',min:'linear',flipY:true});textures.add(texture);});
    return {texture:()=>texture,width:()=>SIZE,height:()=>SIZE,loaded};
  }
  async function place(glyph){
    const image=await loadImage(glyph.tile),slot=slotFor(received);
    const x=(slot%LIVE_GRID[0])*LIVE_CELL,y=Math.floor(slot/LIVE_GRID[0])*LIVE_CELL;
    context.clearRect(x,y,LIVE_CELL,LIVE_CELL);context.drawImage(image,x,y,LIVE_CELL,LIVE_CELL);
    for(const texture of textures){
      // A destroyed scene's texture throws; it is simply forgotten.
      try{texture.subimage({data:image,flipY:true},x,SIZE-y-LIVE_CELL);}catch{textures.delete(texture);}
    }
    received++;latest=Math.max(latest,glyph.seq);
    onChange({count:liveCount(received),received,latest});
  }
  async function poll(){
    if(!running||busy)return;
    busy=true;
    try{
      await ready;
      const response=await fetch(`/live/glyphs?after=${latest}`,{cache:'no-store'});
      if(response.ok){const {glyphs}=await response.json();for(const glyph of glyphs)await place(glyph);}
    }catch{/* the stream may pause or stop; the next poll tries again */}
    finally{busy=false;if(running)timer=setTimeout(poll,pollMs);}
  }
  return Object.freeze({
    source,canvas,
    get count(){return liveCount(received);},
    received:()=>received,
    async probe(){
      try{const response=await fetch('/live/status',{cache:'no-store'});return response.ok&&(await response.json()).session!==undefined;}
      catch{return false;}
    },
    start(){if(!running){running=true;poll();}},
    stop(){running=false;clearTimeout(timer);}
  });
}
