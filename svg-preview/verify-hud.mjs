import assert from 'node:assert/strict';
import {mountHud,folderPath} from './hud.mjs';
import {mountSettings} from './settings.mjs';

// Just enough DOM, and a manual clock, to drive the control panel in Node.
function createWorld(){
  let now=0,lastTimer=0;
  const timers=new Map(),windowListeners=[];
  const fire=(listeners,init)=>{
    const event={defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},stopPropagation(){},...init};
    for(const listener of listeners)listener(event);
    return event;
  };
  class Node{
    constructor(tag){
      this.tagName=tag.toUpperCase();this.ownerDocument=document;this.parent=null;this.children=[];
      this.attributes=new Map();this.listeners=new Map();this.names=new Set();
      this.hidden=false;this.inert=false;this.disabled=false;this.checked=false;this.value='';this.textContent='';
      this.offsetWidth=0;
      const names=this.names;
      this.classList={add:(...items)=>items.forEach(item=>names.add(item)),remove:(...items)=>items.forEach(item=>names.delete(item)),
        toggle:(item,force=!names.has(item))=>{if(force)names.add(item);else names.delete(item);return force;},contains:item=>names.has(item)};
    }
    set className(value){this.names.clear();for(const item of value.split(/\s+/).filter(Boolean))this.names.add(item);}
    get className(){return [...this.names].join(' ');}
    append(...nodes){for(const node of nodes){node.parent=this;this.children.push(node);}}
    remove(){if(this.parent)this.parent.children.splice(this.parent.children.indexOf(this),1);this.parent=null;}
    contains(node){for(let current=node;current;current=current.parent)if(current===this)return true;return false;}
    setAttribute(name,value){this.attributes.set(name,String(value));}
    getAttribute(name){return this.attributes.get(name)??null;}
    removeAttribute(name){this.attributes.delete(name);}
    addEventListener(type,listener){if(!this.listeners.has(type))this.listeners.set(type,[]);this.listeners.get(type).push(listener);}
    dispatch(type,init={}){return fire(this.listeners.get(type)??[],{target:this,...init});}
    focus(){document.activeElement=this;}
    closest(){return null;}
    find(predicate){for(const child of this.children){if(predicate(child))return child;const found=child.find(predicate);if(found)return found;}return null;}
  }
  const window={
    location:{href:'https://example.test/svg-preview/'},
    history:{state:null,replaceState(state,title,url){window.location.href=String(url);}},
    setTimeout(callback,ms=0){timers.set(++lastTimer,{callback,at:now+ms});return lastTimer;},
    clearTimeout(id){timers.delete(id);},
    addEventListener(type,listener){windowListeners.push({type,listener});}
  };
  const document={defaultView:window,createElement:tag=>new Node(tag)};
  document.body=new Node('body');document.activeElement=document.body;
  const settle=()=>new Promise(resolve=>setImmediate(resolve));
  // Run due timers in order, letting each apply's promise chain settle first.
  async function advance(ms){
    const end=now+ms;
    for(;;){
      await settle();
      const due=[...timers].filter(([,timer])=>timer.at<=end).sort((a,b)=>a[1].at-b[1].at||a[0]-b[0])[0];
      if(!due)break;
      timers.delete(due[0]);now=due[1].at;due[1].callback();
    }
    now=end;
  }
  const windowEvent=(type,init)=>fire(windowListeners.filter(item=>item.type===type).map(item=>item.listener),init);
  return {window,document,element:tag=>new Node(tag),advance,
    key:(code,init={})=>windowEvent('keydown',{code,target:document.body,...init})};
}
function panelWorld(){
  const world=createWorld(),panel=world.element('section'),corner=world.element('button'),tip=world.element('div');
  const canvas=world.element('canvas'),slider=world.element('input');
  tip.hidden=true;panel.append(slider);world.document.body.append(panel,corner,tip,canvas);
  return {...world,panel,corner,tip,canvas,slider};
}

// Corner, tooltip, keyboard and dismissal.
{
  const {document,advance,key,panel,corner,tip,canvas,slider}=panelWorld(),changes=[];
  assert.throws(()=>mountHud({panel,corner}),/Pass the panel/);
  const hud=mountHud({panel,corner,tip,dismissTargets:[canvas],onChange:open=>changes.push(open)});
  assert.equal(hud.isOpen(),false);assert.equal(panel.inert,true);assert.equal(panel.getAttribute('aria-hidden'),'true');
  assert.ok(panel.classList.contains('hidden'));assert.equal(corner.getAttribute('aria-expanded'),'false');
  assert.equal(corner.getAttribute('aria-label'),'Open settings');
  // The tooltip names the corner after a beat with the gear showing, stays five
  // seconds, then both leave together.
  await advance(899);assert.equal(tip.hidden,true);assert.equal(corner.classList.contains('hinting'),false);
  await advance(1);assert.equal(tip.hidden,false);assert.ok(corner.classList.contains('hinting'));
  await advance(4999);assert.equal(tip.hidden,false);assert.equal(tip.classList.contains('leaving'),false);assert.ok(corner.classList.contains('hinting'));
  await advance(1);assert.equal(tip.classList.contains('leaving'),true);assert.equal(corner.classList.contains('hinting'),false);
  await advance(420);assert.equal(tip.hidden,true);assert.equal(tip.classList.contains('leaving'),false);
  // A click or tap on the corner opens the panel with the pixel resolve.
  corner.dispatch('click');
  assert.equal(hud.isOpen(),true);assert.equal(panel.inert,false);assert.equal(panel.getAttribute('aria-hidden'),'false');
  assert.ok(corner.classList.contains('active'));assert.equal(corner.getAttribute('aria-expanded'),'true');
  assert.equal(corner.getAttribute('aria-label'),'Close settings');assert.ok(document.body.classList.contains('hud-open'));
  assert.ok(panel.classList.contains('opening'));assert.equal(panel.classList.contains('hidden'),false);
  await advance(360);assert.equal(panel.classList.contains('opening'),false);
  // The tooltip never appears over an open panel.
  hud.showTip();assert.equal(tip.hidden,true);
  // Closing with focus inside the panel returns focus to the corner, then hides the panel.
  slider.focus();corner.dispatch('click');
  assert.equal(document.activeElement,corner);assert.equal(panel.inert,true);assert.ok(panel.classList.contains('closing'));
  assert.equal(document.body.classList.contains('hud-open'),false);
  await advance(300);assert.ok(panel.classList.contains('hidden'));assert.equal(panel.classList.contains('closing'),false);
  // Opening hides a visible tooltip and its gear.
  hud.showTip();assert.equal(tip.hidden,false);assert.ok(corner.classList.contains('hinting'));
  hud.open();assert.ok(tip.classList.contains('leaving'));assert.equal(corner.classList.contains('hinting'),false);
  await advance(420);assert.equal(tip.hidden,true);hud.close();await advance(300);
  // S toggles from anywhere except text entry; held keys and modified shortcuts do not.
  document.body.focus();
  assert.equal(key('KeyS').defaultPrevented,true);assert.equal(hud.isOpen(),true);
  key('KeyS',{repeat:true});key('KeyS',{ctrlKey:true});key('KeyS',{metaKey:true});
  key('KeyS',{target:{closest:selector=>selector.includes('input[type=text]')?{}:null}});
  assert.equal(hud.isOpen(),true);
  // Escape closes without pulling focus to the corner, which would reveal the gear.
  assert.equal(key('Escape').defaultPrevented,true);assert.equal(hud.isOpen(),false);assert.equal(document.activeElement,document.body);
  assert.equal(key('Escape').defaultPrevented,false);
  // Clicking the rain dismisses the panel.
  key('KeyS');canvas.dispatch('click');assert.equal(hud.isOpen(),false);
  assert.deepEqual(changes,[true,false,true,false,true,false,true,false]);
}

// Reduced motion skips the pixel resolve, dissolve and tooltip slide.
{
  const {advance,panel,corner,tip}=panelWorld();
  const hud=mountHud({panel,corner,tip,reducedMotion:true,tipDelayMs:0,tipMs:3000});
  await advance(0);assert.equal(tip.hidden,false);assert.ok(corner.classList.contains('hinting'));
  hud.open();assert.equal(tip.hidden,true);assert.equal(corner.classList.contains('hinting'),false);assert.equal(panel.classList.contains('opening'),false);
  hud.close();assert.ok(panel.classList.contains('hidden'));assert.equal(panel.classList.contains('closing'),false);
  hud.showTip();await advance(3000);assert.equal(tip.hidden,true);assert.equal(tip.classList.contains('leaving'),false);
}

// The folder outline: a raised tab on the body's top edge, inside the panel box.
{
  const geometry={tabLeft:30,tabWidth:228,tabHeight:52};
  const outline=folderPath(900,420,geometry);
  assert.ok(outline.startsWith('M0 70'));assert.ok(outline.endsWith('Z'));
  assert.ok(outline.includes('L20 52'),'the body edge runs to the left fillet');
  assert.ok(outline.includes('L246 0'),'the tab top runs to its right corner');
  assert.ok(outline.includes('L882 52'),'the body edge runs to its top-right corner');
  const numbers=path=>path.match(/-?\d+(?:\.\d+)?/g).map(Number);
  const points=path=>{const values=numbers(path);return path.replace(/[^MLAZ]/g,'').split('').flatMap(command=>command==='Z'?[]:command==='A'?[values.splice(0,7).slice(5)]:[values.splice(0,2)]);};
  for(const [x,y] of points(outline)){assert.ok(x>=0&&x<=900&&y>=0&&y<=420);}
  const inset=folderPath(900,420,geometry,.5);
  assert.ok(inset.startsWith('M0.5 70'));
  for(const [x,y] of points(inset)){assert.ok(x>=.5&&x<=899.5&&y>=.5&&y<=419.5);}
  assert.throws(()=>folderPath(900,420,{...geometry,tabLeft:5}),/does not fit/);
  assert.throws(()=>folderPath(NaN,420,geometry),/finite/);
}

// Live settings: controls settle, apply one rebuild at a time, and revert on failure.
{
  const {window,document,advance,element}=createWorld();
  const container=element('div'),transport=element('div');document.body.append(transport,container);
  const applies=[],statuses=[];let gate=null,failNext=false;
  assert.throws(()=>mountSettings({container,schema:['numColumns']}),/onApply/);
  const deck=mountSettings({container,presetContainer:transport,schema:['originalMix','numColumns','flip',
    {key:'forwardSpeed',enabledWhen:config=>config.flip}],presets:[{id:'dense',label:'Dense',values:{numColumns:140}}],
    initialConfig:{numColumns:100},onStatus:message=>statuses.push(message),
    onApply:(config,details)=>{applies.push({config,details});if(failNext){failNext=false;throw new Error('WebGL is unavailable.');}return gate??Promise.resolve();}});
  const control=name=>container.find(node=>node.name===name),rowOf=name=>control(name).parent;
  const columns=control('numColumns'),flip=control('flip'),picker=transport.find(node=>node.tagName==='SELECT');
  assert.deepEqual(container.children.map(node=>node.getAttribute('aria-label')),['Look','View','Travel']);
  assert.deepEqual(picker.children.map(node=>node.value),['','dense']);assert.equal(picker.value,'');
  assert.equal(columns.value,'100');assert.equal(rowOf('numColumns').find(node=>node.tagName==='OUTPUT').textContent,'100');
  assert.ok(rowOf('originalMix').title.includes('original catalog'));assert.ok(control('originalMix').getAttribute('aria-describedby'));
  // Conditional controls stay disabled until the setting they depend on allows them.
  assert.equal(control('forwardSpeed').disabled,true);assert.ok(rowOf('forwardSpeed').classList.contains('off'));
  // A dragged slider applies once, after it settles.
  columns.value='120';columns.dispatch('input');await advance(200);
  columns.value='130';columns.dispatch('input');await advance(349);
  assert.equal(applies.length,0);assert.equal(deck.pending(),true);
  await advance(1);
  assert.equal(applies.length,1);assert.equal(applies[0].config.numColumns,130);
  assert.deepEqual(applies[0].details,{changed:['numColumns'],presetId:null});
  assert.deepEqual(statuses,['Applying…','']);assert.equal(deck.pending(),false);
  assert.equal(new URL(window.location.href).searchParams.get('numColumns'),'130');
  // A change undone before it settles rebuilds nothing.
  columns.value='90';columns.dispatch('input');columns.value='130';columns.dispatch('input');await advance(400);
  assert.equal(applies.length,1);
  // A checkbox applies at once; changes made during that rebuild wait and then apply together.
  let release;gate=new Promise(resolve=>{release=resolve;});
  flip.checked=true;flip.dispatch('change');await advance(0);
  assert.equal(applies.length,2);assert.equal(applies[1].config.flip,true);assert.equal(container.getAttribute('aria-busy'),'true');
  assert.equal(control('forwardSpeed').disabled,false);assert.equal(rowOf('forwardSpeed').classList.contains('off'),false);
  columns.value='60';columns.dispatch('input');await advance(350);
  columns.value='70';columns.dispatch('input');await advance(350);
  assert.equal(applies.length,2);
  gate=null;release();await advance(0);
  assert.equal(applies.length,3);assert.equal(applies[2].config.numColumns,70);assert.deepEqual(applies[2].details.changed,['numColumns']);
  assert.equal(container.getAttribute('aria-busy'),null);
  // A failed rebuild reports why and puts the controls and address back.
  const address=window.location.href;failNext=true;
  columns.value='150';columns.dispatch('input');await advance(350);
  assert.equal(applies.length,4);assert.equal(statuses.at(-1),'WebGL is unavailable.');
  assert.equal(columns.value,'70');assert.equal(deck.read().numColumns,70);assert.equal(window.location.href,address);
  // Presets apply immediately and are kept in the address.
  picker.value='dense';picker.dispatch('change');await advance(0);
  assert.equal(applies.length,5);assert.equal(applies[4].config.numColumns,140);assert.equal(applies[4].details.presetId,'dense');
  assert.equal(columns.value,'140');assert.equal(new URL(window.location.href).searchParams.get('preset'),'dense');
  // Destroying the deck removes its controls and cancels pending changes.
  columns.value='41';columns.dispatch('input');deck.destroy();await advance(1000);
  assert.equal(applies.length,5);assert.equal(container.children.length,0);assert.equal(transport.children.length,0);
}
console.log('Passed: hidden corner, timed tooltip, keyboard and rain dismissal, reduced motion, and live settings that settle, queue, revert, and apply presets.');
