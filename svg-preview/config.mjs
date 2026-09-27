import upstreamConfig from './engine/upstream-config.mjs';
import {normalizeSettings,parseSettingsUrl,resolveSettingsSchema} from './settings.mjs';

// Each preset starts from one of the renderer's three looks, then changes the
// panel's settings. The looks keep their upstream geometry and exposure.
export const LOOK_IDS=['classic','operator','3d'];
const PRESET_DEFINITIONS=[
  {id:'classic',label:'Classic',look:'classic'},
  {id:'operator',label:'Operator',look:'operator'},
  {id:'3d',label:'3D',look:'3d'},
  {id:'downpour',label:'Downpour',look:'classic',values:{numColumns:150,fallSpeed:1.1,raindropLength:1.6,cycleSpeed:.06,bloomStrength:1,bloomSize:.5}},
  {id:'zen',label:'Zen garden',look:'classic',values:{palette:'sakura',cursorColor:'#ffe3f1',numColumns:44,fallSpeed:.12,cycleSpeed:.008,raindropLength:1.2,animationSpeed:.7,bloomStrength:.9,bloomSize:.7}},
  {id:'inferno',label:'Inferno',look:'classic',values:{palette:'fire',cursorColor:'#fff2b0',numColumns:100,fallSpeed:.8,cycleSpeed:.08,raindropLength:1.1,bloomStrength:1.4,bloomSize:.6}},
  {id:'synthwave',label:'Synthwave',look:'classic',values:{palette:'synthwave',cursorColor:'#c9fbff',numColumns:72,slant:12,fallSpeed:.45,bloomStrength:1.2,bloomSize:.6}},
  {id:'aurora',label:'Northern lights',look:'classic',values:{palette:'aurora',cursorColor:'#d9ffe9',numColumns:56,slant:-8,fallSpeed:.18,raindropLength:1.8,bloomStrength:1.3,bloomSize:.9}},
  {id:'terminal',label:'Amber terminal',look:'operator',values:{palette:'amber',cursorColor:'#ffe6a8',numColumns:72,resolution:.35,bloomStrength:.5,fps:30}},
  {id:'ghost',label:'Ghost',look:'classic',values:{palette:'monochrome',cursorColor:'#ffffff',originalMix:50,numColumns:90,fallSpeed:.45,raindropLength:.35,bloomStrength:1.6,bloomSize:.9}},
  {id:'spectrum',label:'Spectrum',look:'classic',values:{palette:'spectrum',cursorColor:'#ffffff',numColumns:96,bloomStrength:1.1}},
  {id:'hunter',label:'Hunter',look:'classic',values:{glyphFace:'yautja',palette:'crimson',cursorColor:'#ffd0c0',numColumns:48,fallSpeed:.4,cycleSpeed:.05,bloomStrength:1.1,bloomSize:.5}},
  {id:'warp',label:'Warp speed',look:'3d',values:{palette:'ice',cursorColor:'#ffffff',autoTravel:true,forwardSpeed:2.5,density:1.75,fallSpeed:.9,bloomStrength:1.2}},
  {id:'runestones',label:'Runestones',look:'classic',values:{glyphFace:'runic',palette:'amber',cursorColor:'#fff1c9',numColumns:56,fallSpeed:.2,cycleSpeed:.012,raindropLength:1.4,bloomStrength:1.1,bloomSize:.7}},
  {id:'arcade',label:'Arcade',look:'classic',values:{glyphFace:'press-start-2p',palette:'spectrum',cursorColor:'#ffffff',numColumns:64,resolution:.5,fallSpeed:.6,cycleSpeed:.06,bloomStrength:.9,fps:30}},
  {id:'mainframe',label:'Mainframe',look:'operator',values:{glyphFace:'share-tech-mono',palette:'matrix',numColumns:96,fallSpeed:.8,cycleSpeed:.05}}
];
const PRESET_BY_ID=new Map(PRESET_DEFINITIONS.map(preset=>[preset.id,preset]));
export const PRESET_IDS=PRESET_DEFINITIONS.map(preset=>preset.id);
export const lookOf=id=>PRESET_BY_ID.get(id)?.look??'classic';
export const is3dPreset=id=>lookOf(id)==='3d';
export const presetLabel=id=>PRESET_BY_ID.get(id)?.label??'Classic';

// Hue follows the user's reference screenshot; the original preset is retained.
export const MATRIX_GREEN={hue:137/360,saturation:.8,cursor:'#a2ffd8'};
// Body palettes recolor a look's exposure ramp. A number holds one hue or
// saturation; a pair blends from the dimmest glyphs to the brightest.
export const PALETTES=Object.freeze([
  {value:'matrix',label:'Matrix green',hue:MATRIX_GREEN.hue,saturation:MATRIX_GREEN.saturation},
  {value:'reference',label:'Reference colors'},
  {value:'monochrome',label:'White',hue:0,saturation:0},
  {value:'amber',label:'Amber',hue:.12,saturation:.9},
  {value:'crimson',label:'Crimson',hue:.985,saturation:.9},
  {value:'toxic',label:'Toxic',hue:.21,saturation:1},
  {value:'ultraviolet',label:'Ultraviolet',hue:.76,saturation:.85},
  {value:'sakura',label:'Sakura',hue:.93,saturation:[.8,.45]},
  {value:'ice',label:'Ice',hue:[.61,.52],saturation:[.9,.4]},
  {value:'fire',label:'Fire',hue:[0,.14],saturation:[1,.95]},
  {value:'synthwave',label:'Synthwave',hue:[.92,.5],saturation:.9},
  {value:'aurora',label:'Aurora',hue:[.8,.38],saturation:.85},
  {value:'spectrum',label:'Spectrum',hue:[0,.8],saturation:.9}
]);
// Glyph faces fill the renderer's second atlas. The Smythe face mixes its 192
// originals with the 56 classic reference glyphs; other faces draw every cell.
// Cyber is the Yautja project's name for the same 192 originals, shown alone.
export const GLYPH_FACES=Object.freeze([
  {value:'smythe',label:'Smythe + classic',atlas:'./generated-sdf.png',grid:[16,12],count:192,pxRange:16,mixesReference:true,summary:'192 + 56'},
  {value:'cyber',label:'Cyber',atlas:'./generated-sdf.png',grid:[16,12],count:192,pxRange:16,mixesReference:false,summary:'192 Cyber'},
  {value:'yautja',label:'Yautja',atlas:'./faces/yautja-sdf.png',grid:[13,4],count:52,pxRange:16,mixesReference:false,summary:'52 Yautja'},
  {value:'ogham',label:'Ogham',atlas:'./faces/ogham-sdf.png',grid:[16,2],count:26,pxRange:16,mixesReference:false,summary:'26 Ogham'},
  {value:'runic',label:'Runic',atlas:'./faces/runic-sdf.png',grid:[16,5],count:75,pxRange:16,mixesReference:false,summary:'75 Runic'},
  {value:'tifinagh',label:'Tifinagh',atlas:'./faces/tifinagh-sdf.png',grid:[16,4],count:56,pxRange:16,mixesReference:false,summary:'56 Tifinagh'},
  {value:'braille',label:'Braille',atlas:'./faces/braille-sdf.png',grid:[16,16],count:255,pxRange:16,mixesReference:false,summary:'255 Braille'},
  {value:'share-tech-mono',label:'Share Tech Mono',atlas:'./faces/share-tech-mono-sdf.png',grid:[16,4],count:50,pxRange:16,mixesReference:false,summary:'50 Share Tech Mono'},
  {value:'press-start-2p',label:'Press Start 2P',atlas:'./faces/press-start-2p-sdf.png',grid:[16,4],count:50,pxRange:16,mixesReference:false,summary:'50 Press Start 2P'}
]);
export const faceOf=value=>GLYPH_FACES.find(face=>face.value===value)??GLYPH_FACES[0];

const hslToRgb=({space,values})=>{
  if(space==='rgb')return values;
  const [h,s,l]=values,a=s*Math.min(l,1-l);
  return [0,8,4].map(n=>{const k=(n+h*12)%12;return l-a*Math.max(-1,Math.min(k-3,9-k,1));});
};
const hex=color=>'#'+hslToRgb(color).map(value=>Math.round(value*255).toString(16).padStart(2,'0')).join('');
const rgb=value=>({space:'rgb',values:[1,3,5].map(at=>parseInt(value.slice(at,at+2),16)/255)});
const lightness=color=>color.space==='hsl'?color.values[2]:(Math.max(...color.values)+Math.min(...color.values))/2;
const blend=(value,t)=>Array.isArray(value)?value[0]+(value[1]-value[0])*t:value;

export function recolor(ramp,palette){
  const top=Math.max(...ramp.map(entry=>lightness(entry.color)))||1;
  const color=l=>({space:'hsl',values:[blend(palette.hue,l/top),blend(palette.saturation,l/top),l]});
  if(!Array.isArray(palette.hue)&&!Array.isArray(palette.saturation))return ramp.map(entry=>({color:color(lightness(entry.color)),at:entry.at}));
  // A blend needs more stops than a ramp has, so sample the ramp's lightness evenly.
  const stops=[...ramp].sort((a,b)=>a.at-b.at).map(entry=>({at:entry.at,l:lightness(entry.color)}));
  const sample=at=>{
    if(at<=stops[0].at)return stops[0].l;
    const next=stops.findIndex(stop=>stop.at>=at);
    if(next<0)return stops.at(-1).l;
    const from=stops[next-1],to=stops[next];
    return from.l+(to.l-from.l)*(at-from.at)/(to.at-from.at);
  };
  return Array.from({length:17},(_,index)=>({color:color(sample(index/16)),at:index/16}));
}

// The interface takes its colors from the body palette: the dim-trail hue for
// text, outlines and glass, the head hue for highlights. Matrix green keeps the
// panel's designed colors; from its hue this recipe gives a near match.
export const THEME_PROPERTIES=['--phos-rgb','--phos-bright-rgb','--ink-rgb','--phos','--phos-bright','--phos-dim','--phos-faint',
  '--bar','--panel','--control','--ink','--rain-green','--rain-bright','--rain-dim','--rain-rule','--rain-faint','--rain-field','--rain-inverse'];
export function interfaceTheme(values){
  if(values.palette==='matrix')return null;
  let palette=PALETTES.find(item=>item.value===values.palette&&item.hue!==undefined);
  if(!palette){
    const top=upstreamConfig({version:lookOf(values.preset)}).palette.filter(entry=>entry.color.space==='hsl').at(-1);
    palette=top?{hue:top.color.values[0],saturation:top.color.values[1]}:{hue:MATRIX_GREEN.hue,saturation:MATRIX_GREEN.saturation};
  }
  const tone=t=>{const saturation=Math.min(1,blend(palette.saturation,t)*1.25);return {hue:blend(palette.hue,t),saturation,lift:1-saturation};};
  const trail=tone(.35),head=tone(1);
  const color=({hue},saturation,l)=>hslToRgb({space:'hsl',values:[hue,saturation,l]}).map(value=>Math.round(value*255));
  const phos=color(trail,trail.saturation,.61+.2*trail.lift),bright=color(head,head.saturation,.81+.1*head.lift);
  const ink=color(trail,.82*trail.saturation,.043),control=color(trail,.69*trail.saturation,.05);
  const rgbText=channels=>`rgb(${channels.join(', ')})`,rgbaText=(channels,alpha)=>`rgba(${channels.join(', ')}, ${alpha})`;
  return {
    '--phos-rgb':phos.join(', '),'--phos-bright-rgb':bright.join(', '),'--ink-rgb':ink.join(', '),
    '--phos':rgbText(phos),'--phos-bright':rgbText(bright),
    '--phos-dim':rgbText(color(trail,.62*trail.saturation,.48+.2*trail.lift)),
    '--phos-faint':rgbText(color(trail,.61*trail.saturation,.41+.15*trail.lift)),
    '--bar':rgbaText(color(trail,.6*trail.saturation,.029),.84),'--panel':rgbaText(color(trail,.64*trail.saturation,.043),.5),
    '--control':rgbText(control),'--ink':rgbText(ink),
    '--rain-green':rgbText(phos),'--rain-bright':rgbText(bright),'--rain-dim':rgbaText(phos,.62),'--rain-rule':rgbaText(phos,.62),
    '--rain-faint':rgbaText(phos,.26),'--rain-field':rgbText(control),'--rain-inverse':rgbText(ink)
  };
}

export const SCHEMA=resolveSettingsSchema([
  {key:'glyphFace',type:'select',label:'Glyph face',group:'Look',options:GLYPH_FACES.map(({value,label})=>({value,label})),default:'smythe'},
  {key:'originalMix',enabledWhen:v=>faceOf(v.glyphFace).mixesReference},'numColumns',
  {key:'palette',label:'Body palette',options:PALETTES.map(({value,label})=>({value,label}))},
  'backgroundColor','cursorColor','fallSpeed','cycleSpeed','raindropLength','animationSpeed',
  'bloomStrength',{key:'bloomSize',min:0},
  {key:'cursorIntensity',type:'range',label:'Leading glyph brightness',group:'Glow',min:0,max:4,step:.1,default:2},
  'resolution','flip',{key:'rotation',step:90},'slant',
  {key:'skipIntro',type:'checkbox',label:'Start with a full rain field',group:'Motion',default:true},
  {key:'autoTravel',group:'3D travel',help:'Applies in 3D presets.',enabledWhen:v=>is3dPreset(v.preset)},
  {key:'forwardSpeed',group:'3D travel',min:0,default:.25,enabledWhen:v=>is3dPreset(v.preset)},
  {key:'density',type:'range',label:'3D density',group:'3D travel',min:.25,max:2,step:.25,default:1,enabledWhen:v=>is3dPreset(v.preset)},
  {key:'fps',type:'range',label:'Frame rate limit',group:'View',min:15,max:60,step:15,default:60}
]);

export function presetValues(id='classic'){
  const preset=PRESET_BY_ID.get(id)??PRESET_BY_ID.get('classic'),config=upstreamConfig({version:preset.look});
  return normalizeSettings(SCHEMA,{
    preset:preset.id,glyphFace:'smythe',originalMix:10,numColumns:config.numColumns,palette:'matrix',
    backgroundColor:hex(config.backgroundColor),cursorColor:MATRIX_GREEN.cursor,
    fallSpeed:config.fallSpeed,cycleSpeed:config.cycleSpeed,raindropLength:config.raindropLength,
    animationSpeed:config.animationSpeed,bloomStrength:config.bloomStrength,bloomSize:config.bloomSize,
    cursorIntensity:config.cursorIntensity,resolution:config.resolution,flip:config.glyphFlip,
    rotation:config.glyphRotation,slant:config.slant*180/Math.PI,autoTravel:config.volumetric,
    forwardSpeed:config.forwardSpeed,density:config.density,skipIntro:config.skipIntro,fps:config.fps,
    ...preset.values
  });
}
export const PRESETS=PRESET_DEFINITIONS.map(({id,label})=>({id,label,values:presetValues(id)}));

// Entering or leaving 3D swaps the look but keeps what the rain is made of and
// how it is colored, so a preset's glyphs and palette carry across.
export const CARRIED_ACROSS_LOOKS=['glyphFace','originalMix','palette','backgroundColor','cursorColor'];
export function toggleThreeD(values){
  const next=presetValues(is3dPreset(values.preset)?'classic':'3d');
  for(const key of CARRIED_ACROSS_LOOKS)if(values[key]!==undefined)next[key]=values[key];
  return normalizeSettings(SCHEMA,next);
}

export function readConfig(url){
  const address=new URL(url),q=address.searchParams;
  const alias={'1999':'operator','2003':'classic',throwback:'operator'};
  let id=q.get('preset')??q.get('version')??'classic';id=alias[id]??id;
  if(!q.has('preset')&&q.get('volumetric')==='true')id='3d';
  if(!PRESET_IDS.includes(id))id='classic';
  for(const [oldKey,newKey] of Object.entries({width:'numColumns',dropLength:'raindropLength',angle:'slant',glyphFlip:'flip',glyphRotation:'rotation'})){
    if(q.has(oldKey)&&!q.has(newKey))q.set(newKey,q.get(oldKey));
  }
  const values=parseSettingsUrl(address.href,SCHEMA,presetValues(id),{presets:PRESETS});
  if(values.palette==='reference'&&!q.has('cursorColor'))values.cursorColor=hex(upstreamConfig({version:lookOf(id)}).cursorColor);
  values.preset=id;
  return values;
}

export function engineConfig(values){
  const id=PRESET_IDS.includes(values.preset)?values.preset:'classic',look=lookOf(id);
  const config=upstreamConfig({version:look}),base=presetValues(id),v=normalizeSettings(SCHEMA,values,base),face=faceOf(v.glyphFace);
  for(const key of ['numColumns','fallSpeed','cycleSpeed','raindropLength','animationSpeed','bloomStrength','bloomSize','cursorIntensity','resolution','forwardSpeed','density','skipIntro','fps'])config[key]=v[key];
  Object.assign(config,{
    glyphMSDFURL:new URL('./reference/matrixcode_msdf.png',import.meta.url).href,
    generatedAtlasURL:new URL(face.atlas,import.meta.url).href,
    generatedGrid:face.grid,generatedCount:face.count,generatedPxRange:face.pxRange,
    glyphMix:face.mixesReference?v.originalMix/100:1,
    glyphFlip:v.flip,glyphRotation:v.rotation,slant:v.slant*Math.PI/180,
    volumetric:look==='3d',forwardSpeed:v.autoTravel?v.forwardSpeed:0,
    backgroundColor:v.backgroundColor===hex(config.backgroundColor)?config.backgroundColor:rgb(v.backgroundColor),
    cursorColor:v.cursorColor===hex(config.cursorColor)?config.cursorColor:rgb(v.cursorColor)
  });
  // Preserve each look's exposure ramp; only its chromatic grade changes.
  if(v.palette!=='reference')config.palette=recolor(config.palette,PALETTES.find(palette=>palette.value===v.palette));
  return config;
}
