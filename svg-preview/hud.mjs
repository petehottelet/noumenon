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

// Outline of a folder whose tab sits flush with the body's left edge and slopes
// down to the body's top edge at 45 degrees. Each corner is rounded; the slope's
// two ends take small joins. Coordinates are CSS pixels with the origin at the
// top left; inset moves every edge inward so a stroke of twice that width stays
// inside the clipped panel.
export function folderPath(width,height,{tabWidth,tabHeight,radius=18,tabRadius=14,join=8},inset=0){
  const values=[width,height,tabWidth,tabHeight,radius,tabRadius,join,inset];
  if(!values.every(Number.isFinite)||values.some(value=>value<0))throw new RangeError('Folder dimensions must be finite and non-negative');
  const W=width,H=height,T=tabHeight,b=tabWidth;
  if(b<tabRadius+join||T<tabRadius+join||b+T>W-radius-join||H-T<2*radius)throw new RangeError('The tab does not fit on the folder body');
  // Clockwise corners and their radii: the tab's top left, both ends of the slope, then the body.
  const corners=[[0,0,tabRadius],[b,0,join],[b+T,T,join],[W,T,radius],[W,H,radius],[0,H,radius]];
  // Move each edge inward along its normal, then intersect neighbouring edges.
  const edges=corners.map(([x,y],k)=>{
    const [nextX,nextY]=corners[(k+1)%corners.length],length=Math.hypot(nextX-x,nextY-y),dx=(nextX-x)/length,dy=(nextY-y)/length;
    return {x:x-dy*inset,y:y+dx*inset,dx,dy};
  });
  const cross=(ax,ay,bx,by)=>ax*by-ay*bx,n=value=>Number(value.toFixed(2));
  const turns=edges.map((edge,k)=>{
    const prev=edges[(k+edges.length-1)%edges.length];
    const t=cross(edge.x-prev.x,edge.y-prev.y,edge.dx,edge.dy)/cross(prev.dx,prev.dy,edge.dx,edge.dy);
    const x=prev.x+prev.dx*t,y=prev.y+prev.dy*t,convex=cross(prev.dx,prev.dy,edge.dx,edge.dy)>0;
    const angle=Math.acos(Math.max(-1,Math.min(1,prev.dx*edge.dx+prev.dy*edge.dy)));
    const round=Math.max(0,corners[k][2]+(convex?-inset:inset)),reach=round*Math.tan(angle/2);
    return {round,sweep:convex?1:0,from:[x-prev.dx*reach,y-prev.dy*reach],to:[x+edge.dx*reach,y+edge.dy*reach]};
  });
  const path=[`M${n(turns[0].to[0])} ${n(turns[0].to[1])}`];
  for(let k=1;k<=turns.length;k++){
    const turn=turns[k%turns.length];
    path.push(`L${n(turn.from[0])} ${n(turn.from[1])}`,`A${n(turn.round)} ${n(turn.round)} 0 0 ${turn.sweep} ${n(turn.to[0])} ${n(turn.to[1])}`);
  }
  return path.join('')+'Z';
}

// Clip the panel to the folder outline and draw that outline, following the
// panel and tab sizes. Panels without a tab or outline element keep their box.
function mountFolder(panel){
  const window=panel.ownerDocument.defaultView,tab=panel.querySelector?.('.hud-tab'),body=panel.querySelector?.('.hud-body');
  const stroke=panel.querySelector?.('.hud-outline path');
  if(!tab||!body||!stroke||typeof window.ResizeObserver!=='function')return;
  const draw=()=>{
    const geometry={tabWidth:tab.offsetWidth,tabHeight:body.offsetTop};
    try{
      panel.style.clipPath=`path('${folderPath(panel.offsetWidth,panel.offsetHeight,geometry)}')`;
      stroke.setAttribute('d',folderPath(panel.offsetWidth,panel.offsetHeight,geometry,.5));
    }catch{panel.style.clipPath='';stroke.removeAttribute('d');}
  };
  new window.ResizeObserver(draw).observe(panel);draw();
}
