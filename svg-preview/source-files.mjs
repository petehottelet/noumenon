import {readFileSync} from 'node:fs';
import {join} from 'node:path';
export function rendererSources(directory){
  const engine=JSON.parse(readFileSync(join(directory,'engine/manifest.json'),'utf8'));
  return [...new Set(['rain.js','config.mjs','timing.mjs','glyphs.js','base-glyphs.js','index.html','style.css','settings.mjs','settings.css','hud.mjs',
    'generated-sdf.png','generated-sdf.json','faces/yautja-sdf.png','faces/yautja-sdf.json','reference/matrixcode_msdf.png',
    'wordmark.svg','fonts/provenance.json',
    'lib/regl.min.js','lib/gl-matrix.js','engine/upstream-config.mjs','engine/manifest.json',
    ...engine.files.map(file=>'engine/'+file.path)])].sort();
}
