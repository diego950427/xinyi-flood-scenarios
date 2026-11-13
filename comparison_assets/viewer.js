/* Actual grid viewer. Render-on-demand; one shared view state, no animation loop.
   EPSG:3826 east/north maps to Three.js X/Y; Z is actual terrain-relative metres.
   Each native cell stays a constant-height 20 m square. No water surface exists. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const BG = '#081f5c', MISSING = '#647ea9';
  const DEPTH = ['#102744', '#255f88', '#2998bb', '#73cae1', '#efb94d', '#e5654b'];
  const DELTA = ['#2998bb', '#edeff1', '#e5654b'];
  let payload, grid, arrays, count, columns, rows, transform, origin;
  let view = {mode:'2d', display:'compare', extent:'district', panX:0, panY:0, span:1, azimuth:-0.7, tilt:0.85};
  let panels = [], state = {ready:false, renderer:'initializing', renders:0, lastPick:null, errors:[]};
  let pending = false, baseSpan = 1, threeAvailable = false, cellIndices = [], positionAttribute, scaleChoice='focus';
  let gridGeometry, boundaryGeometry, selected = null, autoFit=true, districtBounds=null;
  const scratch = new THREE.Vector3(), raycaster = new THREE.Raycaster();

  function readArray(spec, name) {
    if (!spec || spec.encoding !== 'base64' || !Array.isArray(spec.shape) ||
        spec.shape[0] !== rows || spec.shape[1] !== columns) throw Error(name + ' 的格網尺寸不符。');
    const bytes = Uint8Array.from(atob(spec.data), c => c.charCodeAt(0));
    if (spec.dtype === 'uint8' && bytes.length === count) return bytes;
    if (spec.dtype !== 'float32-le' || bytes.byteLength !== count * 4) throw Error(name + ' 的資料格式不符。');
    const data = new DataView(bytes.buffer), output = new Float32Array(count);
    for (let i=0; i<count; i++) output[i] = data.getFloat32(i*4, true);
    return output;
  }
  function decode() {
    payload = JSON.parse($('comparison-data').textContent);
    grid = payload.grid; rows = grid.rows; columns = grid.cols; count = rows*columns;
    if (payload.version !== 1 || !Number.isInteger(rows) || !Number.isInteger(columns) ||
        rows < 1 || columns < 1 || count > 1000000) throw Error('比較格網格式不支援。');
    transform = grid.transform; origin = grid.origin;
    if (transform.length !== 6 || transform.some(x=>!Number.isFinite(x)) || transform[0]<=0 ||
        transform[4]>=0 || transform[1]!==0 || transform[3]!==0) throw Error('比較圖需要向北的規則格網。');
    arrays = {};
    for (const key of ['terrain_m','terrain_relative_m','valid_mask','a','b','difference','a_valid_mask','b_valid_mask','difference_valid_mask']) arrays[key] = readArray(payload.arrays[key],key);
    if (payload.arrays.reporting_mask) arrays.reporting_mask = readArray(payload.arrays.reporting_mask,'reporting_mask');
    for(const key of ['a_never_mask','b_never_mask'])if(payload.arrays[key])arrays[key]=readArray(payload.arrays[key],key);
    for (const scale of ['absolute','difference']) if (!Array.isArray(payload.scales[scale]) || payload.scales[scale].length!==2 || payload.scales[scale].some(v=>!Number.isFinite(v))) throw Error('比較色階不完整。');
    for(let i=0;i<count;i++) if(arrays.valid_mask[i] && Number.isFinite(arrays.terrain_relative_m[i])) cellIndices.push(i);
    if (!cellIndices.length) throw Error('沒有可以顯示的共同地形格網。');
    let r0=rows,r1=-1,c0=columns,c1=-1;
    for(const i of cellIndices)if(arrays.reporting_mask?.[i]){const r=Math.floor(i/columns),c=i%columns;r0=Math.min(r0,r);r1=Math.max(r1,r);c0=Math.min(c0,c);c1=Math.max(c1,c);}
    if(r1>=r0)districtBounds={west:transform[2]+c0*transform[0],east:transform[2]+(c1+1)*transform[0],north:transform[5]+r0*transform[4],south:transform[5]+(r1+1)*transform[4]};
    baseSpan = Math.max(rows*Math.abs(transform[4]),columns*transform[0]);
    view.span = baseSpan * 1.12;
    $('label-a').textContent = 'A · ' + payload.scenarios[0].label;
    $('label-b').textContent = 'B · ' + payload.scenarios[1].label;
    $('row').max = rows; $('col').max = columns;
    if(payload.field.unit!=='m'){$('scale-control').hidden=true;scaleChoice='full';}
    $('grid-label').textContent = grid.crs + ' · ' + grid.cell_size_m + ' × ' + grid.cell_size_m + ' m · 高程比例 1:1';
    conditions();
  }
  function conditions(){
    const box=$('conditions-content'),table=document.createElement('table'),head=document.createElement('thead'),tr=document.createElement('tr');
    for(const text of ['條件','A','B']){const cell=document.createElement('th');cell.scope='col';cell.textContent=text;tr.append(cell);}head.append(tr);table.append(head);
    const body=document.createElement('tbody');
    const value=(v,unit)=>Number.isFinite(v)?v.toLocaleString('zh-TW',{maximumFractionDigits:2})+' '+unit:'未提供';
    const fields=[
      ['結果名稱',s=>s.label],
      ['實際雨型',s=>s.rainfall?.label||s.rain_label||s.label],
      ['降雨時間',s=>value(s.metrics.rain_duration_s/3600,'小時')],
      ['完整計算',s=>value(s.metrics.simulation_duration_s/3600,'小時')],
      ['雨後觀察',s=>value((s.metrics.simulation_duration_s-s.metrics.rain_duration_s)/3600,'小時')],
      ['排出能力假設',s=>value(s.request.drain_mm_h,'mm/h')],
      ['暫存假設',s=>value(s.request.storage_mm,'mm')],
      ['入滲假設',s=>value(s.request.infiltration_mm_h,'mm/h')],
      ['自訂總雨量',s=>s.request.mode==='custom'?value(s.request.total_mm,'mm'):'使用歷史雨型'],
    ];
    for(const [label,get]of fields){const row=document.createElement('tr'),th=document.createElement('th');th.scope='row';th.textContent=label;row.append(th);for(const scenario of payload.scenarios){const td=document.createElement('td');td.textContent=get(scenario);row.append(td);}body.append(row);}table.append(body);box.append(table);
    const warnings=[...(payload.warnings||[])],notes=[...(payload.notes||[])];
    if(payload.field.id==='time_of_max_s')notes.push('最大值出現時間不是開始淹水時間；從未有水的格子也可能記為 0 小時。');
    const list=document.createElement('ul');
    for(const text of [...new Set([...warnings,...notes])]){const li=document.createElement('li');li.textContent=String(text);list.append(li);}box.append(list);
    const license=document.createElement('details'),summary=document.createElement('summary'),text=document.createElement('pre');summary.textContent='Three.js 0.180.0 · MIT 授權';text.textContent=$('three-license').content.textContent;license.append(summary,text);box.append(license);
    const rainKey=s=>s.request.mode==='historical'?JSON.stringify([s.request.mode,s.request.event_id]):JSON.stringify([s.request.mode,s.request.total_mm,s.request.duration_min,s.request.rain_shape]);
    const rainDifferent=rainKey(payload.scenarios[0])!==rainKey(payload.scenarios[1]);
    const timeDifferent=payload.scenarios[0].metrics.simulation_duration_s!==payload.scenarios[1].metrics.simulation_duration_s;
    if(rainDifferent||timeDifferent){$('condition-warning').textContent='兩筆'+(rainDifferent&&timeDifferent?'降雨與計算時長':rainDifferent?'降雨條件':'計算時長')+'不同；請按「兩筆條件」查看，不能把差異只歸因於排水。';$('condition-warning').hidden=false;}
  }
  function rgb(hex) { return [1,3,5].map(k=>parseInt(hex.slice(k,k+2),16)); }
  const palettes = {absolute:DEPTH.map(rgb), difference:DELTA.map(rgb)};
  const noDataRGB = rgb(MISSING);
  function effectiveScale(diff){return payload.field.unit==='m'&&scaleChoice==='focus'?(diff?[-1,1]:[0,1]):payload.scales[diff?'difference':'absolute'];}
  function colorRGB(value, diff) {
    if (!Number.isFinite(value)) return noDataRGB;
    const scale = effectiveScale(diff);
    const palette = palettes[diff?'difference':'absolute'];
    const range = scale[1]-scale[0];
    let fraction = range > 0 ? Math.max(0,Math.min(1,(value-scale[0])/range)) : (diff?0.5:0);
    let pos=fraction*(palette.length-1), lo=Math.min(palette.length-2,Math.floor(pos)), part=pos-lo;
    return palette[lo].map((v,i)=>Math.round(v+(palette[lo+1][i]-v)*part));
  }
  function displayArray(panel) {return view.display==='difference'?'difference':panel.id;}
  function atXY(row,col) { return [transform[2]+(col+0.5)*transform[0],transform[5]+(row+0.5)*transform[4]]; }
  function cellXY(row,col) {const q=atXY(row,col); return [q[0]-origin.x,q[1]-origin.y];}
  function indexFromWorld(x,y) {
    const col=Math.floor((x+origin.x-transform[2])/transform[0]);
    const row=Math.floor((y+origin.y-transform[5])/transform[4]);
    return row>=0&&row<rows&&col>=0&&col<columns ? row*columns+col : -1;
  }
  function relativeHeight(x,y) {const i=indexFromWorld(x,y);return i>=0&&arrays.valid_mask[i]&&Number.isFinite(arrays.terrain_relative_m[i]) ? arrays.terrain_relative_m[i] : 0;}
  function corners(i) {
    const r=Math.floor(i/columns),c=i%columns,xy=cellXY(r,c),dx=transform[0]/2,dy=Math.abs(transform[4])/2,z=arrays.terrain_relative_m[i];
    return [[xy[0]-dx,xy[1]-dy,z],[xy[0]+dx,xy[1]-dy,z],[xy[0]+dx,xy[1]+dy,z],[xy[0]-dx,xy[1]+dy,z]];
  }
  function geometry() {
    const vertices=new Float32Array(cellIndices.length*18);
    cellIndices.forEach((i,j)=>{const c=corners(i);[0,1,2,0,2,3].forEach((k,t)=>vertices.set(c[k],j*18+t*3));});
    positionAttribute=new THREE.BufferAttribute(vertices,3);
    gridGeometry=new THREE.BufferGeometry();
    const edges=new Float32Array(cellIndices.length*24);
    cellIndices.forEach((i,j)=>{const c=corners(i);[0,1,1,2,2,3,3,0].forEach((k,t)=>{const p=c[k];edges.set([p[0],p[1],p[2]+.08],j*24+t*3);});});
    gridGeometry.setAttribute('position',new THREE.BufferAttribute(edges,3));
    const boundary=[];
    for(const ring of payload.boundary_rings||[]) for(let i=1;i<ring.length;i++) {
      const a=ring[i-1],b=ring[i];
      const length=Math.hypot(b[0]-a[0],b[1]-a[1]),steps=Math.max(1,Math.ceil(length/10));
      for(let s=0;s<steps;s++) for(const q of [s/steps,(s+1)/steps]) {
        const x=a[0]+(b[0]-a[0])*q-origin.x,y=a[1]+(b[1]-a[1])*q-origin.y;
        boundary.push(x,y,relativeHeight(x,y)+.3);
      }
    }
    boundaryGeometry=new THREE.BufferGeometry();
    boundaryGeometry.setAttribute('position',new THREE.Float32BufferAttribute(boundary,3));
  }
  function makePanel(id) {
    const panel={id,element:$('map-'+id),pane:$('pane-'+id),renderer:null,canvas:null,scene:null,camera:null,mesh:null,gridLines:null,selection:null,imageCache:{}};
    panels.push(panel);
    return panel;
  }
  function setupThree(panel) {
    const renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'low-power'});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
    renderer.setClearColor(BG);renderer.outputColorSpace=THREE.SRGBColorSpace;
    panel.renderer=renderer; panel.canvas=renderer.domElement; panel.element.appendChild(panel.canvas);
    panel.scene=new THREE.Scene(); panel.camera=new THREE.OrthographicCamera(-1,1,1,-1,0.1,baseSpan*20);
    const g=new THREE.BufferGeometry();g.setAttribute('position',positionAttribute);
    g.setAttribute('color',new THREE.BufferAttribute(new Float32Array(cellIndices.length*18),3));
    panel.mesh=new THREE.Mesh(g,new THREE.MeshBasicMaterial({vertexColors:true,side:THREE.DoubleSide,toneMapped:false}));
    panel.scene.add(panel.mesh);
    panel.gridLines=new THREE.LineSegments(gridGeometry,new THREE.LineBasicMaterial({color:'#102744',transparent:true,opacity:.65,depthTest:false}));
    panel.gridLines.visible=false;panel.gridLines.renderOrder=1;panel.scene.add(panel.gridLines);
    const boundary=new THREE.LineSegments(boundaryGeometry,new THREE.LineBasicMaterial({color:'#edeff1',depthTest:false}));
    boundary.renderOrder=2;panel.scene.add(boundary);
    panel.selection=new THREE.LineLoop(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:'#efb94d',depthTest:false}));
    panel.selection.renderOrder=3;panel.selection.visible=false;panel.scene.add(panel.selection);
    panel.canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();forceFallback('繪圖連線中斷，已改用 2D 相容模式。');},{once:true});
    updateColors(panel);
  }
  function updateColors(panel) {
    const key=displayArray(panel),diff=key==='difference',values=arrays[key],mask=arrays[key+'_valid_mask'];
    if(panel.mesh) {
      const out=panel.mesh.geometry.attributes.color.array,c=new THREE.Color();
      cellIndices.forEach((i,j)=>{const rgb=colorRGB(mask[i]?values[i]:NaN,diff);c.setRGB(rgb[0]/255,rgb[1]/255,rgb[2]/255,THREE.SRGBColorSpace);for(let k=0;k<6;k++)out.set([c.r,c.g,c.b],j*18+k*3);});
      panel.mesh.geometry.attributes.color.needsUpdate=true;
    }
  }
  function setCamera(panel) {
    const width=Math.max(1,panel.element.clientWidth),height=Math.max(1,panel.element.clientHeight),aspect=width/height;
    panel.width=width;panel.height=height;panel.aspect=aspect;
    if(!panel.camera)return;
    const camera=panel.camera;camera.left=-view.span*aspect/2;camera.right=view.span*aspect/2;camera.top=view.span/2;camera.bottom=-view.span/2;
    const target=new THREE.Vector3(view.panX,view.panY,0),distance=baseSpan*4;
    if(view.mode==='2d'){camera.up.set(0,1,0);camera.position.set(target.x,target.y,distance);}
    else {camera.up.set(0,0,1);camera.position.set(target.x+distance*Math.sin(view.tilt)*Math.sin(view.azimuth),target.y-distance*Math.sin(view.tilt)*Math.cos(view.azimuth),distance*Math.cos(view.tilt));}
    camera.lookAt(target);camera.updateProjectionMatrix();camera.updateMatrixWorld(true);
    panel.renderer.setSize(width,height,false);
  }
  function getImage(panel) {
    const key=displayArray(panel);if(panel.imageCache[key])return panel.imageCache[key];
    const canvas=document.createElement('canvas');canvas.width=columns;canvas.height=rows;
    const ctx=canvas.getContext('2d'),image=ctx.createImageData(columns,rows),v=arrays[key],mask=arrays[key+'_valid_mask'];
    for(let i=0;i<count;i++)if(arrays.valid_mask[i]){const c=colorRGB(mask[i]?v[i]:NaN,key==='difference');image.data.set([...c,255],i*4);}
    ctx.putImageData(image,0,0);panel.imageCache[key]=canvas;return canvas;
  }
  function toCanvas(panel,x,y) {return [(x-view.panX)*panel.height/view.span+panel.width/2,(view.panY-y)*panel.height/view.span+panel.height/2];}
  function renderCanvas(panel) {
    const ratio=Math.min(window.devicePixelRatio||1,2),canvas=panel.canvas;
    canvas.width=Math.round(panel.width*ratio);canvas.height=Math.round(panel.height*ratio);
    const c=canvas.getContext('2d');c.setTransform(ratio,0,0,ratio,0,0);c.fillStyle=BG;c.fillRect(0,0,panel.width,panel.height);c.imageSmoothingEnabled=false;
    const top=toCanvas(panel,transform[2]-origin.x,transform[5]-origin.y),scale=panel.height/view.span;
    c.drawImage(getImage(panel),top[0],top[1],columns*transform[0]*scale,rows*Math.abs(transform[4])*scale);
    c.save();c.beginPath();c.rect(0,0,panel.width,panel.height);c.clip();
    if($('grid').checked&&transform[0]*scale>=5){c.strokeStyle='#102744';c.lineWidth=.6;c.beginPath();cellIndices.forEach(i=>{const xy=toCanvas(panel,...cellXY(Math.floor(i/columns),i%columns));const w=transform[0]*scale,h=Math.abs(transform[4])*scale;if(xy[0]+w<0||xy[0]-w>panel.width||xy[1]+h<0||xy[1]-h>panel.height)return;c.rect(xy[0]-w/2,xy[1]-h/2,w,h);});c.stroke();}
    c.strokeStyle='#edeff1';c.lineWidth=1.2;
    for(const ring of payload.boundary_rings||[]){c.beginPath();ring.forEach((p,i)=>{const xy=toCanvas(panel,p[0]-origin.x,p[1]-origin.y);i?c.lineTo(...xy):c.moveTo(...xy);});c.stroke();}
    if(selected!==null&&arrays.valid_mask[selected]){const xy=toCanvas(panel,...cellXY(Math.floor(selected/columns),selected%columns));c.strokeStyle='#efb94d';c.lineWidth=2;c.strokeRect(xy[0]-transform[0]*scale/2,xy[1]-Math.abs(transform[4])*scale/2,transform[0]*scale,Math.abs(transform[4])*scale);}
    c.restore();
  }
  function render() {
    pending=false;
    for(const panel of panels){if(panel.pane.hidden||getComputedStyle(panel.pane).display==='none')continue;setCamera(panel);if(threeAvailable){panel.gridLines.visible=$('grid').checked;panel.renderer.render(panel.scene,panel.camera);}else renderCanvas(panel);}
    state.renders++;
    document.querySelectorAll('.north').forEach(n=>{n.hidden=view.mode==='3d';});
  }
  function schedule(){if(!pending){pending=true;requestAnimationFrame(render);}}
  function forceFallback(message) {
    if(!state.ready&&panels.length===0)return;
    threeAvailable=false;view.mode='2d';state.renderer='canvas2d';
    for(const panel of panels){if(panel.renderer){panel.renderer.dispose();panel.renderer=null;}panel.element.replaceChildren();panel.mesh=null;panel.camera=null;panel.canvas=document.createElement('canvas');panel.element.appendChild(panel.canvas);}
    $('three').disabled=true;$('three').setAttribute('aria-pressed','false');$('top').setAttribute('aria-pressed','true');
    $('status').textContent=typeof message==='string'?message:'已使用 2D 相容模式；同一格查值與情境差值仍可使用。';$('status').hidden=false;schedule();
  }
  function number(v,unit,sign=false,terrain=false){if(!Number.isFinite(v))return '無資料';let value=v,shownUnit=unit,digits=2;if(unit==='m'&&!terrain){value*=100;shownUnit='cm';digits=1;}else if(unit==='s'){value/=3600;shownUnit='小時';digits=2;}return (sign&&value>0?'+':'')+value.toLocaleString('zh-TW',{maximumFractionDigits:digits})+' '+shownUnit;}
  function pickCell(row,col) {
    if(!Number.isInteger(row)||!Number.isInteger(col)||row<0||row>=rows||col<0||col>=columns)return null;
    const i=row*columns+col,xy=atXY(row,col),valid=Boolean(arrays.valid_mask[i]),unit=payload.field.unit;
    const result={row:row,col:col,index:i,x:xy[0],y:xy[1],terrain_m:valid?arrays.terrain_m[i]:null,a:arrays.a_valid_mask[i]&&Number.isFinite(arrays.a[i])?arrays.a[i]:null,b:arrays.b_valid_mask[i]&&Number.isFinite(arrays.b[i])?arrays.b[i]:null,difference:arrays.difference_valid_mask[i]&&Number.isFinite(arrays.difference[i])?arrays.difference[i]:null,a_never:Boolean(arrays.a_never_mask?.[i]),b_never:Boolean(arrays.b_never_mask?.[i]),unit,in_reporting_area:arrays.reporting_mask?Boolean(arrays.reporting_mask[i]):null,valid};
    selected=i;state.lastPick=result;$('row').value=row+1;$('col').value=col+1;
    const container=$('readout');container.replaceChildren();
    for(const [label,value,sign,never] of [['A',result.a,false,result.a_never],['B',result.b,false,result.b_never],['B − A',result.difference,true,false]]){const span=document.createElement('span'),strong=document.createElement('strong');span.append(label+'  ');strong.textContent=never?'未超過 10 cm':value===null?'無資料':number(value,unit,sign);span.append(strong);container.append(span);}
    const location=document.createElement('span');location.className='location';
    location.textContent=`第 ${row+1} 列 / ${col+1} 欄 · X ${xy[0].toFixed(1)} / Y ${xy[1].toFixed(1)} m · 地形 ${result.terrain_m===null?'無資料':number(result.terrain_m,'m',false,true)}`+(result.in_reporting_area===false?' · 信義區外':'');container.append(location);
    if(threeAvailable)for(const panel of panels){if(valid){panel.selection.geometry.dispose();panel.selection.geometry=new THREE.BufferGeometry().setFromPoints(corners(i).map(p=>new THREE.Vector3(p[0],p[1],p[2]+.4)));panel.selection.visible=true;}else panel.selection.visible=false;}
    schedule();return result;
  }
  function pickAt(panelId,clientX,clientY) {
    const panel=panels.find(p=>p.id===panelId);if(!panel)return null;
    const rect=panel.element.getBoundingClientRect(),x=clientX-rect.left,y=clientY-rect.top;let i=-1;
    if(threeAvailable){raycaster.setFromCamera({x:x/rect.width*2-1,y:1-y/rect.height*2},panel.camera);const hit=raycaster.intersectObject(panel.mesh,false)[0];if(hit)i=cellIndices[Math.floor(hit.faceIndex/2)];}
    else{i=indexFromWorld(view.panX+(x-rect.width/2)*view.span/rect.height,view.panY-(y-rect.height/2)*view.span/rect.height);}
    if(i<0){$('readout').textContent='這個位置沒有計算格網。';return null;}
    return pickCell(Math.floor(i/columns),i%columns);
  }
  function legend(){const diff=view.display==='difference',scale=effectiveScale(diff),clipped=scaleChoice==='focus'&&payload.field.unit==='m';const fieldLabel=payload.field.label+(payload.field.id==='max_depth_m'?'（各格最大，非同時）':'');$('legend-title').textContent=diff?'B − A · '+fieldLabel:fieldLabel+' · A / B 共用色階';$('legend-bar').style.background='linear-gradient(to right,'+(diff?DELTA:DEPTH).join(',')+')';$('legend-min').textContent=(clipped&&diff?'≤ ':'')+number(scale[0],payload.field.unit,diff);$('legend-mid').textContent=number((scale[0]+scale[1])/2,payload.field.unit,diff);$('legend-max').textContent=(clipped?'≥ ':'')+number(scale[1],payload.field.unit,diff);$('scale').options[0].textContent=diff?'−100～+100 cm':'0–100 cm';document.querySelector('.missing').lastChild.textContent=payload.field.id==='first_gt10_s'?'未達門檻／無資料':'無資料';}
  function setScale(value){scaleChoice=value==='full'?'full':'focus';$('scale').value=scaleChoice;panels.forEach(p=>{p.imageCache={};updateColors(p);});legend();schedule();}
  function setMode(mode){view.mode=mode==='3d'&&threeAvailable?'3d':'2d';$('top').setAttribute('aria-pressed',String(view.mode==='2d'));$('three').setAttribute('aria-pressed',String(view.mode==='3d'));schedule();}
  function setDisplay(display){view.display=display==='difference'?'difference':'compare';$('maps').classList.toggle('difference',view.display==='difference');$('compare').setAttribute('aria-pressed',String(view.display==='compare'));$('difference').setAttribute('aria-pressed',String(view.display==='difference'));$('label-a').textContent=view.display==='difference'?'B − A · '+payload.field.label:'A · '+payload.scenarios[0].label;panels.forEach(updateColors);legend();schedule();}
  function fitExtent(){const b=view.extent==='district'&&districtBounds?districtBounds:grid.bounds;const aspects=panels.filter(p=>getComputedStyle(p.pane).display!=='none').map(p=>Math.max(.1,p.element.clientWidth/Math.max(1,p.element.clientHeight)));const aspect=aspects.length?Math.min(...aspects):1;view.panX=(b.west+b.east)/2-origin.x;view.panY=(b.south+b.north)/2-origin.y;view.span=Math.max(b.north-b.south,(b.east-b.west)/aspect)*1.1;}
  function setExtent(value){view.extent=value==='domain'?'domain':'district';$('extent').value=view.extent;autoFit=true;fitExtent();schedule();}
  function zoom(factor){autoFit=false;view.span=Math.max(grid.cell_size_m*5,Math.min(baseSpan*4,view.span*factor));schedule();}
  function reset(){autoFit=true;view.azimuth=-.7;view.tilt=.85;fitExtent();schedule();}
  function pan(dx,dy,panel){autoFit=false;const m=view.span/Math.max(1,panel.element.clientHeight);if(view.mode==='2d'){view.panX-=dx*m;view.panY+=dy*m;}else{const angle=view.azimuth;view.panX-=dx*m*Math.cos(angle);view.panY-=dx*m*Math.sin(angle);view.panX-=dy*m*Math.sin(angle);view.panY+=dy*m*Math.cos(angle);}schedule();}
  function installControls(panel){
    const pointers=new Map();let first=null,moved=false,oldGesture=null;
    const gesture=()=>{const p=[...pointers.values()];return p.length<2?null:{x:(p[0].x+p[1].x)/2,y:(p[0].y+p[1].y)/2,d:Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y)};};
    panel.element.addEventListener('pointerdown',e=>{if(e.button!==0&&e.pointerType==='mouse')return;panel.element.focus({preventScroll:true});panel.element.setPointerCapture(e.pointerId);pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});if(pointers.size===1){first={x:e.clientX,y:e.clientY};moved=false;}else moved=true;oldGesture=gesture();});
    panel.element.addEventListener('pointermove',e=>{const old=pointers.get(e.pointerId);if(!old)return;const dx=e.clientX-old.x,dy=e.clientY-old.y;pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});if(first&&Math.hypot(e.clientX-first.x,e.clientY-first.y)>4)moved=true;if(pointers.size>1){const next=gesture();if(oldGesture&&next){pan(next.x-oldGesture.x,next.y-oldGesture.y,panel);if(next.d>0)zoom(oldGesture.d/next.d);}oldGesture=next;}else if(view.mode==='3d'&&!e.shiftKey){view.azimuth-=dx*.008;view.tilt=Math.max(.05,Math.min(1.4,view.tilt+dy*.006));schedule();}else pan(dx,dy,panel);});
    const finish=e=>{const click=pointers.size===1&&!moved;pointers.delete(e.pointerId);oldGesture=gesture();if(click&&e.type!=='pointercancel')pickAt(panel.id,e.clientX,e.clientY);};
    panel.element.addEventListener('pointerup',finish);panel.element.addEventListener('pointercancel',finish);
    panel.element.addEventListener('keydown',e=>{let handled=true;const step=35;if(e.shiftKey&&view.mode==='3d'&&e.key.startsWith('Arrow')){if(e.key==='ArrowLeft')view.azimuth-=.12;if(e.key==='ArrowRight')view.azimuth+=.12;if(e.key==='ArrowUp')view.tilt=Math.max(.05,view.tilt-.1);if(e.key==='ArrowDown')view.tilt=Math.min(1.4,view.tilt+.1);schedule();}else switch(e.key){case'ArrowLeft':pan(step,0,panel);break;case'ArrowRight':pan(-step,0,panel);break;case'ArrowUp':pan(0,step,panel);break;case'ArrowDown':pan(0,-step,panel);break;case'+':case'=':zoom(.8);break;case'-':zoom(1.25);break;case'r':case'R':reset();break;default:handled=false;}if(handled)e.preventDefault();});
    // Ordinary wheel scrolling remains page scrolling. Explicit buttons/pinch zoom.
  }
  function diagnostics(){return {ready:state.ready,renderer:state.renderer,threeVersion:THREE.REVISION,view:{...view},renders:state.renders,cellCount:cellIndices.length,rows,columns,lastPick:state.lastPick,scales:payload.scales,effectiveScales:{absolute:effectiveScale(false),difference:effectiveScale(true),selection:scaleChoice,unit:payload.field.unit,displayUnit:payload.field.unit==='m'?'cm':payload.field.unit==='s'?'小時':payload.field.unit},field:payload.field,errors:[...state.errors],cameras:panels.map(p=>({id:p.id,position:p.camera?p.camera.position.toArray():[view.panX,view.panY],quaternion:p.camera?p.camera.quaternion.toArray():null,left:p.camera?.left,right:p.camera?.right,top:p.camera?.top,bottom:p.camera?.bottom,width:p.element.clientWidth,height:p.element.clientHeight})),framePending:pending};}
  function projectCell(panelId,row,col){const panel=panels.find(p=>p.id===panelId),i=row*columns+col;if(!panel||i<0||i>=count)return null;const xy=cellXY(row,col),rect=panel.element.getBoundingClientRect();let point;if(threeAvailable){scratch.set(xy[0],xy[1],arrays.terrain_relative_m[i]).project(panel.camera);point=[(scratch.x+1)/2*rect.width,(1-scratch.y)/2*rect.height];}else point=toCanvas(panel,...xy);return {clientX:rect.left+point[0],clientY:rect.top+point[1],x:point[0],y:point[1]};}
  try {
    decode();makePanel('a');makePanel('b');
    try {geometry();for(const p of panels)setupThree(p);threeAvailable=true;state.renderer='webgl';}
    catch(error){state.errors.push('WebGL unavailable: '+error.message);forceFallback('此裝置無法使用 WebGL，已顯示 2D 相容圖。');}
    panels.forEach(installControls);
    $('top').onclick=()=>setMode('2d');$('three').onclick=()=>setMode('3d');$('compare').onclick=()=>setDisplay('compare');$('difference').onclick=()=>setDisplay('difference');$('zoom-in').onclick=()=>zoom(.8);$('zoom-out').onclick=()=>zoom(1.25);$('reset').onclick=reset;$('grid').onchange=schedule;$('fallback').onclick=()=>forceFallback();$('scale').onchange=()=>setScale($('scale').value);$('extent').onchange=()=>setExtent($('extent').value);
    $('inspect').onclick=()=>{const row=Number($('row').value)-1,col=Number($('col').value)-1;if(!pickCell(row,col))$('readout').textContent='請輸入範圍內的整數列與欄。';};
    for(const id of ['row','col'])$(id).addEventListener('keydown',e=>{if(e.key==='Enter')$('inspect').click();});
    new ResizeObserver(()=>{if(autoFit)fitExtent();schedule();}).observe($('maps'));
    window.__xinyiComparison={version:1,getState:diagnostics,pickCell,pickAt,projectCell,forceFallback,reset,setScale,setExtent,setView(next){if(next.mode)setMode(next.mode);if(next.display)setDisplay(next.display);if(next.extent)setExtent(next.extent);for(const key of ['panX','panY','span','azimuth','tilt'])if(Number.isFinite(next[key])){autoFit=false;view[key]=next[key];}view.span=Math.max(grid.cell_size_m*5,Math.min(baseSpan*4,view.span));view.tilt=Math.max(.05,Math.min(1.4,view.tilt));schedule();return diagnostics();}};
    legend();fitExtent();state.ready=true;render();
  } catch(error) {
    state.errors.push(error.message);$('viewer').replaceChildren();const p=document.createElement('p');p.className='fatal';p.textContent='比較圖無法開啟：'+error.message+' 請重新選取兩筆已完成結果。';$('viewer').append(p);window.__xinyiComparison={version:1,getState:()=>({...state})};
  }
})();
