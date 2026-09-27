// Floating control panel after hottelet.com's HUD, opened from a corner that
// shows no gear until a mouse hovers it. A tooltip names the corner once and
// shows the gear beside it; both fade out together.
const TEXT_ENTRY='textarea,[contenteditable],input:not([type]),input[type=text],input[type=search],input[type=number],input[type=email],input[type=url]';

export function mountHud({panel,corner,tip,dismissTargets=[],reducedMotion=false,tipDelayMs=900,tipMs=5000,onChange=()=>{}}){
  if(!panel?.ownerDocument||!corner||!tip)throw new TypeError('Pass the panel, corner button and tooltip elements');
  const document=panel.ownerDocument,window=document.defaultView;
  let open=false,animation=0,tipTimer=0;

  function hideTip(){
    window.clearTimeout(tipTimer);
    corner.classList.remove('hinting');
    if(tip.hidden)return;
    if(reducedMotion){tip.hidden=true;return;}
    tip.classList.add('leaving');
    tipTimer=window.setTimeout(()=>{tip.hidden=true;tip.classList.remove('leaving');},420);
  }
  function showTip(){
    if(open)return;
    window.clearTimeout(tipTimer);tip.classList.remove('leaving');tip.hidden=false;corner.classList.add('hinting');
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
  mountFolder(panel);
  panel.inert=true;panel.setAttribute('aria-hidden','true');panel.classList.add('hidden');
  corner.setAttribute('aria-expanded','false');corner.setAttribute('aria-label','Open settings');
  if(tipDelayMs>=0)tipTimer=window.setTimeout(showTip,tipDelayMs);
  return Object.freeze({open:()=>setOpen(true),close:()=>setOpen(false),toggle:()=>setOpen(!open),isOpen:()=>open,showTip,hideTip});
}

// Outline of a folder: a rounded body with a raised tab on its top edge, joined
// by concave fillets. Coordinates are CSS pixels with the origin at the top left;
// inset moves every edge inward so a stroke of twice that width stays inside.
export function folderPath(width,height,{tabLeft,tabWidth,tabHeight,radius=18,tabRadius=12,fillet=10},inset=0){
  const values=[width,height,tabLeft,tabWidth,tabHeight,radius,tabRadius,fillet,inset];
  if(!values.every(Number.isFinite)||values.some(value=>value<0))throw new RangeError('Folder dimensions must be finite and non-negative');
  const W=width,H=height,T=tabHeight,a=tabLeft,b=tabLeft+tabWidth,i=inset;
  const r=Math.min(radius,(H-T)/2,W/2),f=Math.min(fillet,a-r,W-r-b),t=Math.min(tabRadius,tabWidth/2,T-f);
  if(r<i||f<0||t<i||T<t+f)throw new RangeError('The tab does not fit on the folder body');
  const n=value=>Number(value.toFixed(2)),arc=(radius,sweep,x,y)=>`A${n(radius)} ${n(radius)} 0 0 ${sweep} ${n(x)} ${n(y)}`;
  return [`M${n(i)} ${n(T+r)}`,arc(r-i,1,r,T+i),`L${n(a-f)} ${n(T+i)}`,arc(f+i,0,a+i,T-f),
    `L${n(a+i)} ${n(t)}`,arc(t-i,1,a+t,i),`L${n(b-t)} ${n(i)}`,arc(t-i,1,b-i,t),
    `L${n(b-i)} ${n(T-f)}`,arc(f+i,0,b+f,T+i),`L${n(W-r)} ${n(T+i)}`,arc(r-i,1,W-i,T+r),
    `L${n(W-i)} ${n(H-r)}`,arc(r-i,1,W-r,H-i),`L${n(r)} ${n(H-i)}`,arc(r-i,1,i,H-r),'Z'].join('');
}

// Clip the panel to the folder outline and draw that outline, following the
// panel and tab sizes. Panels without a tab or outline element keep their box.
function mountFolder(panel){
  const window=panel.ownerDocument.defaultView,tab=panel.querySelector?.('.hud-tab'),body=panel.querySelector?.('.hud-body');
  const stroke=panel.querySelector?.('.hud-outline path');
  if(!tab||!body||!stroke||typeof window.ResizeObserver!=='function')return;
  const draw=()=>{
    const geometry={tabLeft:tab.offsetLeft,tabWidth:tab.offsetWidth,tabHeight:body.offsetTop};
    try{
      panel.style.clipPath=`path('${folderPath(panel.offsetWidth,panel.offsetHeight,geometry)}')`;
      stroke.setAttribute('d',folderPath(panel.offsetWidth,panel.offsetHeight,geometry,.5));
    }catch{panel.style.clipPath='';stroke.removeAttribute('d');}
  };
  new window.ResizeObserver(draw).observe(panel);draw();
}
