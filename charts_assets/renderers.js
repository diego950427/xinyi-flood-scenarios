/* Adapted from Lieflat Charts Basics Gallery F3, F2 and F9.
 * See LICENSE-LIEFLAT.txt and CHART_DESIGN.md. No remote scripts or fonts.
 */
(() => {
  'use strict';
  const CUSTOM = Object.freeze({BG:'#081f5c',CARD:'#142f60',TXT:'#edeff1',MUT:'#bdcde5',
    GRID:'#647ea9',DATA:'#9ebfe9',HERO:'#edeff1'});
  const P = JSON.parse(document.getElementById('chart-data').textContent);
  const {el,txt,tip} = MONO;
  const svg=document.getElementById('chart'), slider=document.getElementById('inspect');
  const readout=document.getElementById('readout');
  let inspect=()=>{}, visible=false, lastWidth=0;
  const format=(v,d=2)=>Number(v).toLocaleString('zh-TW',{maximumFractionDigits:d});
  const hours=s=>format(s/3600);
  const nice=(v)=>{if(!(v>0))return 1; const k=10**Math.floor(Math.log10(v)); return Math.ceil(v/k)*k;};
  function furniture(s,W,ymax,unit,xmax){
    const X0=52,X1=W-18,base=194,top=29;
    const x=v=>X0+(X1-X0)*v/Math.max(xmax,1e-9),y=v=>base-(base-top)*v/ymax;
    for(let i=0;i<=4;i++){
      const v=ymax*i/4;
      el(s,'line',{x1:X0,y1:y(v),x2:X1,y2:y(v),stroke:CUSTOM.GRID,'stroke-width':.7});
      txt(s,{x:X0-7,y:y(v)+4,'font-size':11,'font-weight':600,fill:CUSTOM.MUT,'text-anchor':'end'},format(v,ymax<1?3:1));
    }
    txt(s,{x:X0,y:15,'font-size':12,'font-weight':600,fill:CUSTOM.MUT},unit);
    const count=W<500?2:4;
    for(let i=0;i<=count;i++)txt(s,{x:x(xmax*i/count),y:base+20,'font-size':11,'font-weight':600,fill:CUSTOM.MUT,
      'text-anchor':i===0?'start':i===count?'end':'middle'},hours(xmax*i/count)+' h');
    return {X0,X1,base,top,x,y};
  }
  function hitArea(s,W,indices,fn){
    // Transparent interaction area changes no data encoding; pointer maps to a real record.
    const hit=el(s,'rect',{x:52,y:20,width:W-70,height:190,fill:'transparent'});
    hit.addEventListener('pointermove',e=>{
      const b=svg.getBoundingClientRect(),pos=(e.clientX-b.left)*W/b.width;
      let best=0,dist=Infinity;
      indices.forEach((x,i)=>{if(Math.abs(x-pos)<dist){dist=Math.abs(x-pos);best=i;}});
      slider.value=best;fn(best);
    });
  }
  // F3 Hairline Area: one vertical hairline per real interval; bounded peak marker.
  function rain(s,W){
    const D=P.data, vs=D.values,N=vs.length, edges=D.edges_s;
    const F=furniture(s,W,nice(Math.max(...vs)*1.16),'雨強 mm/h',edges.at(-1));
    const {x,y,base}=F,peak=vs.indexOf(Math.max(...vs));
    const centers=vs.map((v,i)=>(edges[i]+edges[i+1])/2);
    vs.forEach((v,i)=>{
      el(s,'line',{x1:x(centers[i]),y1:base,x2:x(centers[i]),y2:y(v),
        stroke:i===peak?CUSTOM.HERO:CUSTOM.DATA,'stroke-width':i===peak?2:1.1,
        class:'fade',style:`animation-delay:${Math.min(i*.014,.8)}s`});
    });
    // Interval inputs are piecewise constant. Do not interpolate rainfall between records.
    const pts=vs.flatMap((v,i)=>[[x(edges[i]),y(v)],[x(edges[i+1]),y(v)]]);
    el(s,'path',{d:'M'+pts.map(p=>p.join(' ')).join(' L '),fill:'none',stroke:CUSTOM.DATA,
      'stroke-width':1.8,pathLength:1,class:'draw'});
    const pd=el(s,'circle',{cx:x(centers[peak]),cy:y(vs[peak]),r:4.2,fill:CUSTOM.HERO,class:'pop'});
    tip(pd,`最大區間雨強 ${format(vs[peak])} mm/h`);
    txt(s,{x:Math.max(90,Math.min(W-60,x(centers[peak]))),y:y(vs[peak])-11,'font-size':13,'font-weight':800,
      fill:CUSTOM.HERO,'text-anchor':'middle',style:`paint-order:stroke;stroke:${CUSTOM.CARD};stroke-width:4px`,class:'fade'},format(vs[peak],1));
    if(D.rain_end_s<edges.at(-1)){
      el(s,'line',{x1:x(D.rain_end_s),x2:x(D.rain_end_s),y1:24,y2:base,stroke:CUSTOM.MUT,'stroke-dasharray':'3 4'});
    }
    const cursor=el(s,'line',{y1:24,y2:base,stroke:CUSTOM.HERO,'stroke-width':1,'stroke-dasharray':'2 3'});
    inspect=i=>{i=Math.max(0,Math.min(N-1,i));cursor.setAttribute('x1',x(centers[i]));cursor.setAttribute('x2',x(centers[i]));
      readout.textContent=`${hours(edges[i])}–${hours(edges[i+1])} h：${format(vs[i])} mm/h；這一段 ${format(vs[i]*(edges[i+1]-edges[i])/3600)} mm`;};
    slider.max=N-1;slider.value=Math.min(Number(slider.value),N-1);
    hitArea(s,W,centers.map(x),inspect);inspect(Number(slider.value));
  }
  // F2 Hairline Line: calendar floor, a real timestamped dot for each saved output.
  function history(s,W){
    const vs=P.data.values,ts=P.data.times_s,N=vs.length;
    const F=furniture(s,W,nice(Math.max(...vs)*1.18),'面積 km²',ts.at(-1));
    const {x,y,base}=F,peak=vs.indexOf(Math.max(...vs));
    ts.forEach((t,i)=>el(s,'line',{x1:x(t),y1:base,x2:x(t),y2:base-5,stroke:CUSTOM.GRID,'stroke-width':.7}));
    el(s,'path',{d:'M'+vs.map((v,i)=>`${x(ts[i])} ${y(v)}`).join(' L '),fill:'none',stroke:CUSTOM.DATA,
      'stroke-width':1.8,pathLength:1,class:'draw',style:'animation-duration:1.2s'});
    vs.forEach((v,i)=>{
      const dot=el(s,'circle',{cx:x(ts[i]),cy:y(v),r:i===peak?4.2:N>100?1.2:2.1,
        fill:i===peak?CUSTOM.HERO:CUSTOM.DATA,class:'fade'});
      tip(dot,`${hours(ts[i])} h：${format(v)} km²`);
    });
    txt(s,{x:Math.max(90,Math.min(W-60,x(ts[peak]))),y:y(vs[peak])-11,'font-size':13,'font-weight':800,
      fill:CUSTOM.HERO,'text-anchor':'middle',style:`paint-order:stroke;stroke:${CUSTOM.CARD};stroke-width:4px`},format(vs[peak]));
    const cursor=el(s,'circle',{r:4,fill:CUSTOM.CARD,stroke:CUSTOM.HERO,'stroke-width':2});
    inspect=i=>{i=Math.max(0,Math.min(N-1,i));cursor.setAttribute('cx',x(ts[i]));cursor.setAttribute('cy',y(vs[i]));
      readout.textContent=`開始後 ${hours(ts[i])} h：當時超過 10 cm 的面積 ${format(vs[i],4)} km²`;};
    slider.max=N-1;slider.value=Math.min(Number(slider.value),N-1);
    hitArea(s,W,ts.map(x),inspect);inspect(Number(slider.value));
  }
  // F9 Rung Waterfall: separate rungs, dashed deductions and step hand-off lines.
  function budget(s,W){
    const D=P.data.rows,N=D.length,X0=30,X1=W-14,base=194,top=30;
    const max=nice(Math.max(...D.map(d=>Math.abs(d.value)))*1.1);
    const y=v=>base-(base-top)*v/max, x=i=>X0+(X1-X0)*(i+.5)/N;
    const rung=nice(max/24), HW=Math.min(20,(X1-X0)/N/3);
    let level=0;const rows=[];
    D.forEach((d,i)=>{
      if(d.kind==='total'){rows.push({...d,lo:0,hi:d.value}); if(i===0)level=d.value;}
      else{rows.push({...d,lo:level+d.value,hi:level});level+=d.value;}
    });
    rows.forEach((d,i)=>{
      const neg=d.kind==='change';
      for(let v=d.lo;v<d.hi;v+=rung)el(s,'line',{x1:x(i)-HW,y1:y(v),x2:x(i)+HW,y2:y(v),
        stroke:neg?CUSTOM.DATA:CUSTOM.HERO,'stroke-width':1.8,'stroke-dasharray':neg?'3 3':'none',
        class:'fade',style:`animation-delay:${i*.1}s`});
      // Exact top cap and zero markers keep partial rungs and true zero visible.
      el(s,'line',{x1:x(i)-HW,y1:y(d.hi),x2:x(i)+HW,y2:y(d.hi),stroke:neg?CUSTOM.DATA:CUSTOM.HERO,
        'stroke-width':1.8,'stroke-dasharray':neg?'3 3':'none'});
      const out=d.kind==='total'?d.hi:d.lo;
      if(i<N-1)el(s,'line',{x1:x(i)+HW+3,y1:y(out),x2:x(i+1)-HW-3,y2:y(out),stroke:CUSTOM.GRID,'stroke-dasharray':'2 3'});
      txt(s,{x:x(i),y:y(d.hi)-9,'font-size':W<430?11:13,'font-weight':800,fill:CUSTOM.HERO,'text-anchor':'middle'},format(Math.abs(d.value)/1000,1));
      const labels=d.name==='SWMM 排出'?['SWMM','排出']:d.name.length>4?[d.name.slice(0,3),d.name.slice(3)]:[d.name];
      labels.forEach((t,j)=>txt(s,{x:x(i),y:base+18+j*13,'font-size':11,'font-weight':600,fill:CUSTOM.MUT,'text-anchor':'middle'},t));
      const hit=el(s,'rect',{x:x(i)-(X1-X0)/N/2,y:20,width:(X1-X0)/N,height:210,fill:'transparent'});
      hit.addEventListener('pointermove',()=>{slider.value=i;inspect(i);});
    });
    txt(s,{x:X0,y:15,'font-size':12,'font-weight':600,fill:CUSTOM.MUT},'標示單位：千 m³');
    el(s,'line',{x1:X0,y1:base,x2:X1,y2:base,stroke:CUSTOM.GRID,'stroke-width':.8});
    inspect=i=>{const d=D[i];readout.textContent=`${d.name}：${format(Math.abs(d.value),2)} m³；一階刻線間距 ${format(rung)} m³（末階可能不足）`;};
    slider.max=N-1;slider.value=Math.min(Number(slider.value),N-1);inspect(Number(slider.value));
  }
  function render(){
    const W=Math.max(280,Math.round(svg.clientWidth));lastWidth=W;
    svg.setAttribute('viewBox',`0 0 ${W} 240`);svg.replaceChildren();
    ({rain,history,budget}[P.kind])(svg,W);
  }
  const observer=new IntersectionObserver(entries=>{
    const now=entries.some(e=>e.isIntersecting);
    if(now&&!visible)render(); visible=now;
  },{threshold:.3});observer.observe(svg);
  new ResizeObserver(()=>{if(visible&&Math.abs(svg.clientWidth-lastWidth)>2)render();}).observe(svg);
  slider.addEventListener('input',()=>inspect(Number(slider.value)));
  document.getElementById('replay').addEventListener('click',render);
})();
