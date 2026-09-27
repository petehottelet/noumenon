// Optional controls for capabilities explicitly supplied by the renderer host.
export const SETTING_DEFINITIONS=Object.freeze({
  originalMix:{type:'range',label:'Original glyphs',group:'Look',min:0,max:100,step:1,default:10,unit:'%',help:'Share of cells drawn from Smythe’s original catalog.'},
  numColumns:{type:'range',label:'Columns',group:'Look',min:40,max:160,step:1,default:80},
  palette:{type:'select',label:'Palette',group:'Look',options:[]},
  backgroundColor:{type:'color',label:'Background',group:'Look',default:'#000000'},
  cursorColor:{type:'color',label:'Leading glyph',group:'Look',default:'#d8ffa8'},
  fallSpeed:{type:'range',label:'Fall speed',group:'Motion',min:.05,max:2,step:.05,default:.3},
  cycleSpeed:{type:'range',label:'Character changes',group:'Motion',min:0,max:.2,step:.005,default:.03},
  raindropLength:{type:'range',label:'Trail length',group:'Motion',min:.1,max:2,step:.05,default:.75},
  animationSpeed:{type:'range',label:'Animation speed',group:'Motion',min:.1,max:3,step:.1,default:1,unit:'×'},
  bloomStrength:{type:'range',label:'Glow amount',group:'Glow',min:0,max:2,step:.05,default:.7},
  bloomSize:{type:'range',label:'Glow spread',group:'Glow',min:.05,max:1,step:.05,default:.4},
  resolution:{type:'range',label:'Render scale',group:'View',min:.25,max:1,step:.05,default:.75,unit:'×',help:'Lower values reduce the render workload.'},
  flip:{type:'checkbox',label:'Mirror glyphs',group:'View',default:false},
  rotation:{type:'range',label:'Glyph rotation',group:'View',min:-180,max:180,step:1,default:0,unit:'°'},
  slant:{type:'range',label:'Column angle',group:'View',min:-60,max:60,step:1,default:0,unit:'°'},
  autoTravel:{type:'checkbox',label:'Travel automatically',group:'Travel',default:false},
  forwardSpeed:{type:'range',label:'Travel speed',group:'Travel',min:.05,max:3,step:.05,default:.2}
});

export function resolveSettingsSchema(schema){
  if(!Array.isArray(schema))throw new TypeError('Pass the settings supported by this engine as a schema array');
  const keys=new Set();
  return schema.map(entry=>{
    const key=typeof entry==='string'?entry:entry?.key;
    if(typeof key!=='string'||!/^\w+$/.test(key)||['__proto__','constructor','prototype','preset'].includes(key)||keys.has(key))throw new TypeError(`Invalid or duplicate setting key: ${key}`);
    keys.add(key);
    const field={...SETTING_DEFINITIONS[key],...(typeof entry==='object'?entry:{}),key};
    if(field.enabledWhen!==undefined&&typeof field.enabledWhen!=='function')throw new TypeError(`enabledWhen must be a function: ${key}`);
    if(!['range','checkbox','color','select'].includes(field.type)||!field.label)throw new TypeError(`Incomplete setting definition: ${key}`);
    if(field.type==='range'&&(!Number.isFinite(field.min)||!Number.isFinite(field.max)||field.min>=field.max||!Number.isFinite(field.step)||field.step<=0))throw new TypeError(`Invalid range: ${key}`);
    if(field.type==='select'){
      field.options=(field.options??[]).map(option=>typeof option==='string'?{value:option,label:option}:{...option});
      if(!field.options.length||field.options.some(option=>typeof option.value!=='string'||typeof option.label!=='string'))throw new TypeError(`Supply implemented choices for ${key}`);
      field.default??=field.options[0].value;
    }
    field.group??='Settings';
    return field;
  });
}

export const settingEnabled=(field,config)=>field.enabledWhen?Boolean(field.enabledWhen(config)):true;

function valueFor(field,value){
  if(field.type==='range'){
    if(value===null||value===undefined||typeof value==='boolean'||(typeof value==='string'&&!value.trim()))return undefined;
    const number=Number(value);if(!Number.isFinite(number))return undefined;
    const clamped=Math.max(field.min,Math.min(field.max,number));
    return Number(Math.max(field.min,Math.min(field.max,field.min+Math.round((clamped-field.min)/field.step)*field.step)).toFixed(8));
  }
  if(field.type==='checkbox'){
    if(value===true||value===1||value==='true'||value==='1')return true;
    if(value===false||value===0||value==='false'||value==='0')return false;
    return undefined;
  }
  if(field.type==='color')return typeof value==='string'&&/^#[0-9a-f]{6}$/i.test(value)?value.toLowerCase():undefined;
  return field.options.some(option=>option.value===value)?value:undefined;
}

export function normalizeSettings(schema,values={},base={}){
  const fields=resolveSettingsSchema(schema),result={...base,...values};
  for(const field of fields){
    result[field.key]=valueFor(field,values[field.key])??valueFor(field,base[field.key])??valueFor(field,field.default);
    if(result[field.key]===undefined)throw new TypeError(`No valid value or default for ${field.key}`);
  }
  return result;
}

export function parseSettingsUrl(url,schema,base={}, {presets=[]}={}){
  const address=new URL(url),preset=presets.find(item=>item.id===address.searchParams.get('preset'));
  const initial={...base,...preset?.values},values={};
  for(const field of resolveSettingsSchema(schema)){
    if(address.searchParams.has(field.key)){
      const value=valueFor(field,address.searchParams.get(field.key));
      if(value!==undefined)values[field.key]=value;
    }
  }
  return normalizeSettings(schema,values,initial);
}

export function serializeSettingsUrl(url,values,schema,{presetId=null}={}){
  const address=new URL(url),config=normalizeSettings(schema,values);
  for(const field of resolveSettingsSchema(schema))address.searchParams.set(field.key,String(config[field.key]));
  if(presetId)address.searchParams.set('preset',presetId);else address.searchParams.delete('preset');
  return address;
}

let nextDeck=0;
// Render the renderer's supported settings as live control groups. Each apply
// rebuilds the WebGL scene, so sliders and colour pickers apply once they settle.
export function mountSettings({container,schema,presets=[],presetContainer=null,initialConfig={},initialPresetId=null,onApply,onStatus=()=>{},syncUrl=true,settleMs=350}){
  if(!container?.ownerDocument)throw new TypeError('Pass a DOM container for the settings controls');
  if(typeof onApply!=='function')throw new TypeError('Pass an onApply callback for the supported renderer settings');
  const fields=resolveSettingsSchema(schema),document=container.ownerDocument,window=document.defaultView;
  if(new Set(presets.map(preset=>preset.id)).size!==presets.length||presets.some(preset=>!preset.id||!preset.label||!preset.values))throw new TypeError('Presets require unique ids, labels, and implemented configuration values');
  const id=`rain-settings-${++nextDeck}`,controls=new Map(),nodes=[];
  let applied=normalizeSettings(fields,initialConfig),draft={...applied},busy=false,queued=false,timer=0,destroyed=false;
  let appliedPreset=initialPresetId??presets.find(preset=>preset.id===new URL(window.location.href).searchParams.get('preset'))?.id??'';
  if(appliedPreset&&!presets.some(preset=>preset.id===appliedPreset))throw new TypeError('Unknown initial preset');
  const element=(tag,className,text)=>{const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node;};
  let presetSelect=null;
  if(presets.length){
    const picker=element('span','preset-picker'),label=element('label','','Preset');
    presetSelect=element('select');presetSelect.id=`${id}-preset`;label.htmlFor=presetSelect.id;
    const custom=element('option','','Current settings');custom.value='';presetSelect.append(custom);
    for(const preset of presets){const option=element('option','',preset.label);option.value=preset.id;presetSelect.append(option);}
    presetSelect.value=appliedPreset;picker.append(label,presetSelect);(presetContainer??container).append(picker);nodes.push(picker);
    presetSelect.addEventListener('change',()=>{
      const preset=presets.find(item=>item.id===presetSelect.value);if(preset){setValues(preset.values);schedule(0);}
    });
  }
  const groups=new Map();
  for(const field of fields){
    if(!groups.has(field.group)){
      const section=element('section','group');section.setAttribute('aria-label',field.group);section.append(element('h2','',field.group));
      groups.set(field.group,section);container.append(section);nodes.push(section);
    }
    const row=element('div',`row row--${field.type}`),label=element('label','',field.label);
    const input=element(field.type==='select'?'select':'input');input.id=`${id}-${field.key}`;input.name=field.key;label.htmlFor=input.id;
    if(field.type==='select')for(const item of field.options){const option=element('option','',item.label);option.value=item.value;input.append(option);}
    else input.type=field.type;
    if(field.type==='range'){input.min=String(field.min);input.max=String(field.max);input.step=String(field.step);}
    const output=field.type==='range'?element('output'):null;
    if(output){output.htmlFor=input.id;output.setAttribute('aria-hidden','true');}
    row.append(label,input);if(output)row.append(output);
    if(field.help){row.title=field.help;const help=element('span','visually-hidden',field.help);help.id=`${input.id}-help`;input.setAttribute('aria-describedby',help.id);row.append(help);}
    controls.set(field.key,{field,input,output,row});groups.get(field.group).append(row);
    const settle=field.type==='range'||field.type==='color'?settleMs:0;
    const update=()=>{
      draft[field.key]=field.type==='checkbox'?input.checked:input.value;
      if(output)output.textContent=`${valueFor(field,input.value)}${field.unit??''}`;
      refreshEnabled();schedule(settle);
    };
    input.addEventListener('input',update);input.addEventListener('change',update);
  }

  function read(){return normalizeSettings(fields,draft,applied);}
  function refreshEnabled(){
    const config=read();
    for(const {field,input,row} of controls.values()){
      const enabled=settingEnabled(field,config);input.disabled=!enabled;row.classList.toggle('off',!enabled);
    }
  }
  function setValues(values){
    draft=normalizeSettings(fields,values,read());
    for(const {field,input,output} of controls.values()){
      if(field.type==='checkbox')input.checked=draft[field.key];else input.value=String(draft[field.key]);
      if(output)output.textContent=`${draft[field.key]}${field.unit??''}`;
    }
    refreshEnabled();return read();
  }
  function schedule(delay=settleMs){if(destroyed)return;window.clearTimeout(timer);timer=window.setTimeout(commit,delay);}
  async function commit(){
    timer=0;if(destroyed)return;
    if(busy){queued=true;return;}
    const config=read(),presetId=presetSelect?.value||null,changed=fields.filter(field=>config[field.key]!==applied[field.key]).map(field=>field.key);
    if(!changed.length&&(presetId??'')===appliedPreset)return;
    busy=true;container.setAttribute('aria-busy','true');onStatus('Applying…');
    try{
      await onApply({...config},{changed,presetId});
      applied={...config};appliedPreset=presetId??'';
      if(syncUrl){const address=serializeSettingsUrl(window.location.href,applied,fields,{presetId});window.history.replaceState(window.history.state,'',address);}
      onStatus('');
    }catch(failure){
      onStatus(failure?.message||'These settings could not be applied. Try again.');
      draft={...applied};setValues(applied);if(presetSelect)presetSelect.value=appliedPreset;
    }finally{
      busy=false;container.removeAttribute('aria-busy');
      if(queued){queued=false;schedule(0);}
    }
  }
  setValues(applied);
  return Object.freeze({element:container,read,setValues,
    pending:()=>busy||Boolean(timer),
    flush:()=>{if(!timer)return Promise.resolve();window.clearTimeout(timer);return commit();},
    destroy:()=>{window.clearTimeout(timer);destroyed=true;for(const node of nodes)node.remove();}
  });
}
