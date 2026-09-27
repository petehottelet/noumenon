// Floating control panel after hottelet.com's HUD, opened from a corner that
// shows no gear until a mouse hovers it. A tooltip names the corner once.
const TEXT_ENTRY='textarea,[contenteditable],input:not([type]),input[type=text],input[type=search],input[type=number],input[type=email],input[type=url]';

export function mountHud({panel,corner,tip,dismissTargets=[],reducedMotion=false,tipDelayMs=900,tipMs=5000,onChange=()=>{}}){
  if(!panel?.ownerDocument||!corner||!tip)throw new TypeError('Pass the panel, corner button and tooltip elements');
  const document=panel.ownerDocument,window=document.defaultView;
  let open=false,animation=0,tipTimer=0;

  function hideTip(){
    window.clearTimeout(tipTimer);
    if(tip.hidden)return;
    if(reducedMotion){tip.hidden=true;return;}
    tip.classList.add('leaving');
    tipTimer=window.setTimeout(()=>{tip.hidden=true;tip.classList.remove('leaving');},420);
  }
  function showTip(){
    if(open)return;
    window.clearTimeout(tipTimer);tip.classList.remove('leaving');tip.hidden=false;
    tipTimer=window.setTimeout(hideTip,tipMs);
  }
  function setOpen(next){
    if(next===open)return;
    open=next;window.clearTimeout(animation);
    if(!open&&panel.contains(document.activeElement))corner.focus({preventScroll:true});
    panel.inert=!open;panel.setAttribute('aria-hidden',String(!open));
    corner.classList.toggle('active',open);corner.setAttribute('aria-expanded',String(open));
    corner.setAttribute('aria-label',open?'Close settings':'Open settings');
    document.body.classList.toggle('hud-open',open);
    if(open){
      hideTip();panel.classList.remove('hidden','closing');
      if(!reducedMotion){
        panel.classList.remove('opening');void panel.offsetWidth;panel.classList.add('opening');
        animation=window.setTimeout(()=>panel.classList.remove('opening'),360);
      }
    }else if(!reducedMotion){
      panel.classList.remove('opening');panel.classList.add('closing');void panel.offsetWidth;
      animation=window.setTimeout(()=>{panel.classList.remove('closing');panel.classList.add('hidden');},300);
    }else panel.classList.add('hidden');
    onChange(open);
  }

  corner.addEventListener('click',()=>setOpen(!open));
  for(const target of dismissTargets)target.addEventListener('click',()=>setOpen(false));
  // S toggles the panel from anywhere except text entry; Escape closes it.
  window.addEventListener('keydown',event=>{
    if(event.ctrlKey||event.metaKey||event.altKey||event.target?.closest?.(TEXT_ENTRY))return;
    if(event.code==='KeyS'){
      event.preventDefault();event.stopPropagation();
      if(!event.repeat)setOpen(!open);
    }else if(event.code==='Escape'&&open){event.preventDefault();setOpen(false);}
  },true);

  // Start closed, without the dissolve animation.
  panel.inert=true;panel.setAttribute('aria-hidden','true');panel.classList.add('hidden');
  corner.setAttribute('aria-expanded','false');corner.setAttribute('aria-label','Open settings');
  if(tipDelayMs>=0)tipTimer=window.setTimeout(showTip,tipDelayMs);
  return Object.freeze({open:()=>setOpen(true),close:()=>setOpen(false),toggle:()=>setOpen(!open),isOpen:()=>open,showTip,hideTip});
}
