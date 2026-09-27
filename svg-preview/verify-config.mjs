import assert from 'node:assert/strict';
import upstream from './engine/upstream-config.mjs';
import {MATRIX_GREEN,LOOK_IDS,PRESET_IDS,PRESETS,PALETTES,GLYPH_FACES,SCHEMA,THEME_PROPERTIES,CARRIED_ACROSS_LOOKS,presetValues,readConfig,engineConfig,recolor,interfaceTheme,toggleThreeD,is3dPreset,lookOf} from './config.mjs';
import {normalizeSettings} from './settings.mjs';
for(const id of LOOK_IDS){
  const base=upstream({version:id}),values=readConfig(`https://example.test/?preset=${id}&palette=reference`),result=engineConfig(values);
  for(const key of ['numColumns','fallSpeed','cycleSpeed','raindropLength','animationSpeed','bloomSize','bloomStrength','resolution','forwardSpeed','volumetric','palette','cursorColor'])assert.deepEqual(result[key],key==='forwardSpeed'&&id!=='3d'?0:base[key],`${id}: ${key}`);
  assert.equal(result.glyphMix,.1);assert.equal(result.generatedCount,192);
  const green=engineConfig(presetValues(id));
  assert.deepEqual(green.palette.map(entry=>entry.at),base.palette.map(entry=>entry.at));
  assert.deepEqual(green.palette.map(entry=>entry.color.values[2]),base.palette.map(entry=>entry.color.values[2]));
  assert.ok(green.palette.every(entry=>entry.color.values[0]===MATRIX_GREEN.hue&&entry.color.values[1]===.8));
  assert.deepEqual(green.cursorColor,{space:'rgb',values:[162/255,1,216/255]});
}
for(const value of [0,10,100])assert.equal(engineConfig(readConfig(`https://example.test/?originalMix=${value}`)).glyphMix,value/100);
const malformed=readConfig('https://example.test/?originalMix=NaN&resolution=0&fps=0&numColumns=Infinity');
assert.equal(malformed.originalMix,10);assert.equal(malformed.resolution,.25);assert.equal(malformed.fps,15);assert.equal(malformed.numColumns,80);
const alias=readConfig('https://example.test/?version=1999&width=120&glyphFlip=true&angle=30');
assert.equal(alias.preset,'operator');assert.equal(alias.numColumns,120);assert.equal(alias.flip,true);assert.equal(alias.slant,30);
const applied=readConfig('https://example.test/?preset=3d&originalMix=37&autoTravel=false');
assert.equal(engineConfig(applied).volumetric,true);assert.equal(engineConfig(applied).forwardSpeed,0);
assert.equal(readConfig('https://example.test/?preset=classic&volumetric=true').preset,'classic');

// Every preset is a complete, in-range configuration on one of the three looks.
assert.equal(new Set(PRESET_IDS).size,PRESET_IDS.length);assert.ok(PRESET_IDS.length>=12);
assert.deepEqual(PRESETS.map(preset=>preset.id),PRESET_IDS);
for(const preset of PRESETS){
  assert.ok(LOOK_IDS.includes(lookOf(preset.id)),preset.id);
  assert.deepEqual(normalizeSettings(SCHEMA,preset.values),preset.values,`${preset.id} stays within the panel's ranges`);
  const values=readConfig(`https://example.test/?preset=${preset.id}`),config=engineConfig(values);
  assert.equal(values.preset,preset.id);assert.equal(config.volumetric,is3dPreset(preset.id));
  assert.ok(config.palette.length>=3&&config.palette.every(entry=>entry.at>=0&&entry.at<=1));
}
assert.equal(is3dPreset('warp'),true);assert.equal(is3dPreset('downpour'),false);assert.equal(lookOf('unknown'),'classic');
const warp=engineConfig(readConfig('https://example.test/?preset=warp'));
assert.equal(warp.volumetric,true);assert.equal(warp.forwardSpeed,2.5);assert.equal(warp.density,1.75);
assert.equal(readConfig('https://example.test/?preset=inferno&numColumns=60').numColumns,60);

// Palettes: every choice is offered, single-hue palettes keep a look's stops,
// and blends span their hues from dim to bright over the same exposure.
assert.deepEqual(SCHEMA.find(field=>field.key==='palette').options.map(option=>option.value),PALETTES.map(palette=>palette.value));
assert.ok(PALETTES.length>=12);
const ramp=upstream({version:'classic'}).palette;
const amber=recolor(ramp,PALETTES.find(palette=>palette.value==='amber'));
assert.deepEqual(amber.map(entry=>entry.at),ramp.map(entry=>entry.at));
assert.ok(amber.every(entry=>entry.color.values[0]===.12));
const fire=recolor(ramp,PALETTES.find(palette=>palette.value==='fire'));
assert.equal(fire.length,17);assert.equal(fire[0].at,0);assert.equal(fire.at(-1).at,1);
assert.equal(fire[0].color.values[0],0);assert.equal(fire.at(-1).color.values[0],.14);
assert.equal(fire.at(-1).color.values[2],ramp.at(-1).color.values[2]);
for(let index=1;index<fire.length;index++)assert.ok(fire[index].color.values[2]>=fire[index-1].color.values[2]);
const ghost=engineConfig(readConfig('https://example.test/?palette=monochrome'));
assert.ok(ghost.palette.every(entry=>entry.color.values[1]===0));

// Glyph faces: the Smythe face mixes with the reference glyphs; every other
// face fills each cell from its own atlas and ignores the mix.
assert.deepEqual(GLYPH_FACES.map(face=>face.value),['smythe','cyber','yautja','ogham','runic','tifinagh','braille','share-tech-mono','press-start-2p']);
assert.deepEqual(SCHEMA.find(field=>field.key==='glyphFace').options.map(option=>option.value),GLYPH_FACES.map(face=>face.value));
for(const face of GLYPH_FACES){
  const config=engineConfig(readConfig(`https://example.test/?glyphFace=${face.value}&originalMix=25`));
  assert.equal(config.generatedCount,face.count,face.value);assert.deepEqual(config.generatedGrid,face.grid,face.value);
  assert.equal(config.glyphMix,face.value==='smythe'?.25:1,face.value);
  assert.ok(face.count<=face.grid[0]*face.grid[1]&&face.count>face.grid[0]*(face.grid[1]-1),`${face.value} grid holds exactly its rows`);
  assert.ok(config.generatedAtlasURL.endsWith(face.atlas.slice(1)),face.value);
}
// Cyber is the same 192 originals as the Smythe face, drawn without the reference mix.
const cyber=engineConfig(readConfig('https://example.test/?glyphFace=cyber'));
assert.ok(cyber.generatedAtlasURL.endsWith('/generated-sdf.png'));assert.equal(cyber.glyphMix,1);assert.equal(cyber.generatedCount,192);
for(const [id,face] of [['runestones','runic'],['arcade','press-start-2p'],['mainframe','share-tech-mono']])assert.equal(readConfig(`https://example.test/?preset=${id}`).glyphFace,face,id);
const yautja=engineConfig(readConfig('https://example.test/?glyphFace=yautja&originalMix=10'));
assert.equal(yautja.glyphMix,1);assert.equal(yautja.generatedCount,52);assert.deepEqual(yautja.generatedGrid,[13,4]);
assert.ok(yautja.generatedAtlasURL.endsWith('/faces/yautja-sdf.png'));
assert.equal(engineConfig(readConfig('https://example.test/?glyphFace=unknown')).generatedCount,192);
const mix=SCHEMA.find(field=>field.key==='originalMix');
assert.equal(mix.enabledWhen({glyphFace:'smythe'}),true);assert.equal(mix.enabledWhen({glyphFace:'yautja'}),false);
const hunter=readConfig('https://example.test/?preset=hunter');
assert.equal(hunter.glyphFace,'yautja');assert.equal(hunter.palette,'crimson');
// Interface colors follow the body palette; Matrix green keeps the designed panel colors.
assert.equal(interfaceTheme(readConfig('https://example.test/')),null);
const channels=text=>text.match(/\d+/g).slice(0,3).map(Number);
const hueOf=([r,g,b])=>{const max=Math.max(r,g,b),min=Math.min(r,g,b),d=max-min;if(!d)return null;const h=max===r?((g-b)/d)%6:max===g?(b-r)/d+2:(r-g)/d+4;return (h*60+360)%360;};
// The classic look's own palette gives a green interface.
const derived=interfaceTheme({palette:'reference',preset:'classic'});
for(const palette of PALETTES){
  const theme=interfaceTheme({palette:palette.value,preset:'classic'});
  if(palette.value==='matrix'){assert.equal(theme,null);continue;}
  assert.deepEqual(Object.keys(theme),THEME_PROPERTIES,palette.value);
  assert.ok(Object.values(theme).every(value=>typeof value==='string'&&value.length),palette.value);
  assert.match(theme['--phos-rgb'],/^\d{1,3}, \d{1,3}, \d{1,3}$/);
  assert.ok(channels(theme['--bar']).every(value=>value<24),`${palette.value} glass stays dark`);
}
assert.ok(derived&&hueOf(channels(derived['--phos']))>80&&hueOf(channels(derived['--phos']))<140);
const white=interfaceTheme({palette:'monochrome',preset:'classic'});
assert.equal(hueOf(channels(white['--phos'])),null);assert.ok(channels(white['--phos'])[0]>190);
const fireTheme=interfaceTheme({palette:'fire',preset:'classic'});
assert.ok(hueOf(channels(fireTheme['--phos']))<25);assert.ok(hueOf(channels(fireTheme['--phos-bright']))>35&&hueOf(channels(fireTheme['--phos-bright']))<60);
const crimsonTheme=interfaceTheme({palette:'crimson',preset:'classic'});
assert.ok(hueOf(channels(crimsonTheme['--phos']))>340||hueOf(channels(crimsonTheme['--phos']))<10);
// Entering 3D from a colored preset keeps its glyphs and colors (Runestones
// used to turn Matrix green), and leaving 3D keeps them too.
const runestones=readConfig('https://example.test/?preset=runestones');
const entered=toggleThreeD(runestones);
assert.equal(entered.preset,'3d');assert.equal(engineConfig(entered).volumetric,true);
for(const key of CARRIED_ACROSS_LOOKS)assert.equal(entered[key],runestones[key],`3D keeps ${key}`);
assert.equal(entered.palette,'amber');assert.equal(entered.glyphFace,'runic');
assert.equal(entered.numColumns,presetValues('3d').numColumns,'the 3D look keeps its own geometry');
assert.ok(interfaceTheme(entered)['--phos'].startsWith('rgb(255'),'the interface stays amber');
const left=toggleThreeD(entered);
assert.equal(left.preset,'classic');assert.equal(engineConfig(left).volumetric,false);
for(const key of CARRIED_ACROSS_LOOKS)assert.equal(left[key],runestones[key],`leaving 3D keeps ${key}`);
const custom=toggleThreeD(readConfig('https://example.test/?palette=reference&cursorColor=%23123456&backgroundColor=%23010203&originalMix=40'));
assert.deepEqual([custom.palette,custom.cursorColor,custom.backgroundColor,custom.originalMix],['reference','#123456','#010203',40]);
console.log('Configuration: reference looks, mix endpoints, aliases, URL validation, paused automatic travel, presets, palettes, glyph faces, interface themes and 3D toggling passed.');
