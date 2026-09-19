(() => {
  window.drawPlayerDots = (cell, players, ownSid) => {
    const unique = [...new Map(players.map(p => [p.sid, p])).values()];
    if (!unique.length) return;
    const group = document.createElement('div');
    group.className = 'occupants';
    group.title = unique.map(p => p.name).join(', ');
    unique.forEach(player => {
      const tag = document.createElement('div');
      tag.className = 'playerTag' + (player.sid === ownSid ? ' youTag' : '');
      tag.style.setProperty('--player-color', player.color || '#55e4ff');
      tag.textContent = player.name;
      tag.title = player.name;
      group.appendChild(tag);
    });
    cell.appendChild(group);
  };
  window.drawBirthLabel = (cell, names) => {
    if (!names.length) return;
    cell.classList.add('birthCell');
    const label = document.createElement('div');
    label.className = 'birthLabel';
    label.textContent = '⌂ ' + names.join(', ');
    cell.title += ' — ' + (window.translateGameText?.('Birth spot') || 'Birth spot') + ': ' + names.join(', ');
    cell.appendChild(label);
  };
  window.drawBirthLegend = (container, spots, relative = false) => {
    container.replaceChildren();
    Object.entries(spots).forEach(([key, owners]) => {
      const [x, y] = key.split(',').map(Number);
      const position = relative ? `(${x}, ${y})` : `${String.fromCharCode(65 + x)}${y + 1}`;
      const chip = document.createElement('span');
      chip.className = 'birthLegendItem';
      chip.textContent = `⌂ ${owners.map(p => p.name).join(', ')} · ${position}`;
      container.appendChild(chip);
    });
  };
  window.drawPlayerStats = (container, players) => {
    container.replaceChildren();
    const tr = text => window.translateGameText?.(text) || text;
    players.forEach(player => {
      const row = document.createElement('article');
      row.className = 'statsRow';
      const name = document.createElement('strong');
      name.textContent = player.name;
      name.style.borderInlineStart = `6px solid ${player.color}`;
      name.style.paddingInlineStart = '8px';
      row.appendChild(name);
      const details = document.createElement('div');
      details.textContent = `${tr('Injuries:')} ${player.injuries} · ${tr('Bullets:')} ${player.bullets} · ${tr('Bombs:')} ${player.bombs} · ${tr('Alive:')} ${tr(player.alive ? 'Yes' : 'No')} · ${tr('Lost:')} ${tr(player.lost ? 'Yes' : 'No')}`;
      row.appendChild(details);
      const status=document.createElement('div');status.textContent=`${tr('Spawned:')} ${tr(player.spawned?'Yes':'No')} · ${tr(player.connected?'Connected':'Disconnected')}`;row.appendChild(status);
      const items = document.createElement('div');
      items.textContent = tr('Items:') + ' ' + (Object.entries(player.items || {}).filter(([,value]) => value).map(([key]) => tr(key)).join(', ') || tr('No items yet.'));
      row.appendChild(items);
      container.appendChild(row);
    });
  };

  window.createMapView = (board, large = false) => {
    const wrap = document.createElement('div'); wrap.className = 'mapView' + (large ? ' mapLarge' : ' mapPreview');
    const grid = document.createElement('div'); grid.className = 'mapGrid'; wrap.appendChild(grid);
    const players = board.players || [];
    const points = [...Object.keys(board.tiles || {}).map(key => key.split(',').map(Number)), ...players.map(p => [p.x,p.y])];
    const focus = players.length ? players.map(p=>[p.x,p.y]) : points;
    const cx = focus.length ? Math.round(focus.reduce((s,p)=>s+p[0],0)/focus.length) : 0;
    const cy = focus.length ? Math.round(focus.reduce((s,p)=>s+p[1],0)/focus.length) : 0;
    const radius = Math.max(5,...points.map(p=>Math.max(Math.abs(p[0]-cx),Math.abs(p[1]-cy))));
    const size = board.manager_map ? 10 : radius * 2 + 1;
    const minX = board.manager_map ? 0 : cx-radius, minY = board.manager_map ? 0 : cy-radius;
    grid.style.gridTemplateColumns = `repeat(${size},minmax(0,1fr))`;
    grid.dataset.centerX = cx; grid.dataset.centerY = cy;
    const key = (a,b)=>[a.join(','),b.join(',')].sort().join('|');
    const edges = new Map();
    for (const [kind,list] of [['open',board.open_edges],['wall',board.wall_edges],['broken',board.broken_walls]]) {
      for(const edge of list||[]) edges.set(key(...edge),kind);
    }
    for(let dy=0;dy<size;dy++) for(let dx=0;dx<size;dx++) {
      const x=minX+dx,y=minY+dy,tile=board.tiles?.[`${x},${y}`];
      const cell=document.createElement('div');cell.className='cell';cell.dataset.x=x;cell.dataset.y=y;
      cell.title=`${board.absolute?'':'relative '}${x},${y}${tile?': '+tile:''}`;
      if(tile) {const img=document.createElement('img');img.src=`/static/pixel_tiles/${tile.replace(/^used_/,'')}.png`;img.alt=tile;cell.appendChild(img);}
      const sides=[['top',[x,y-1]],['left',[x-1,y]]];
      if(dx===size-1)sides.push(['right',[x+1,y]]);
      if(dy===size-1)sides.push(['bottom',[x,y+1]]);
      for(const [side,neighbor] of sides) {const kind=edges.get(key([x,y],neighbor));if(kind){const line=document.createElement('div');line.className=`mapEdge ${side} ${kind}`;cell.appendChild(line);}}
      drawBirthLabel(cell,(board.birth_spots?.[`${x},${y}`]||[]).map(p=>p.name));
      drawPlayerDots(cell,players.filter(p=>p.x===x&&p.y===y));grid.appendChild(cell);
    }
    if(players.length){const names=document.createElement('div');names.className='mapNames';players.forEach(p=>{const name=document.createElement('span');name.textContent=p.name;name.style.borderInlineStart=`8px solid ${p.color}`;names.appendChild(name);});wrap.appendChild(names);}
    if(large){const births=document.createElement('div');births.className='birthLegend';drawBirthLegend(births,board.birth_spots||{},!board.absolute);wrap.appendChild(births);}
    if(board.manager_map&&large){
      const axes=document.createElement('div');axes.className='mapAxes';
      const cols=document.createElement('div');cols.className='mapAxisColumns';
      const rows=document.createElement('div');rows.className='mapAxisRows';
      for(let n=0;n<10;n++){const c=document.createElement('span');c.textContent=String.fromCharCode(65+n);cols.appendChild(c);const r=document.createElement('span');r.textContent=n+1;rows.appendChild(r);}
      wrap.replaceChild(axes,grid);axes.append(cols,rows,grid);
    }
    return wrap;
  };

  window.updateTreasureReveal = (pending, ownSid, acknowledge) => {
    let dialog=document.getElementById('treasureReveal');
    if(!dialog){dialog=document.createElement('dialog');dialog.id='treasureReveal';dialog.className='treasureReveal';dialog.addEventListener('cancel',event=>event.preventDefault());document.body.appendChild(dialog);}
    if(!pending){if(dialog.open)dialog.close();delete dialog.dataset.dismissed;return;}
    const dismissKey=`${pending.player_sid}:${pending.phase}`;
    if(pending.player_sid!==ownSid&&dialog.dataset.dismissed===dismissKey)return;
    dialog.replaceChildren();
    const title=document.createElement('h2');title.textContent=pending.phase==='hype'?'TREASURE FOUND!':'Plot twist — fake treasure!';
    const text=document.createElement('p');text.textContent=pending.phase==='hype'?`${pending.name} found a treasure! The reveal is coming...`:`${pending.name} found fake treasure. The turn waits for confirmation.`;
    dialog.append(title,text);
    if(pending.phase==='revealed'&&pending.player_sid===ownSid&&acknowledge){const button=document.createElement('button');button.textContent='I saw the reveal — continue';button.onclick=()=>{button.disabled=true;acknowledge();};dialog.appendChild(button);}
    if(pending.player_sid!==ownSid){const close=document.createElement('button');close.textContent='Close';close.onclick=()=>{dialog.dataset.dismissed=dismissKey;dialog.close();};dialog.appendChild(close);}
    window.applyGameTranslations?.(dialog);
    if(!dialog.open)dialog.showModal();
  };

  function initWakeLock() {
    const control=document.createElement('button');control.id='wakeLockButton';control.type='button';
    document.body.appendChild(control);
    let wanted=true,lock=null,pending=false;
    const label=text=>{control.textContent=window.translateGameText?.(text)||text;};
    async function requestLock(){
      if(!('wakeLock' in navigator)||!window.isSecureContext){control.disabled=true;label('Keep awake unavailable');return;}
      if(!wanted||lock||pending||document.visibilityState!=='visible')return;
      pending=true;
      try {lock=await navigator.wakeLock.request('screen');if(!wanted){await lock.release();lock=null;return;}label('Screen kept awake · turn off');lock.addEventListener('release',()=>{lock=null;label(wanted?'Keep screen awake · retry':'Keep screen awake');});}
      catch(_){label('Keep screen awake · retry');}
      finally{pending=false;}
    }
    control.onclick=async()=>{if(lock){wanted=false;await lock.release();label('Keep screen awake');}else{wanted=true;await requestLock();}};
    document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')requestLock();});
    window.addEventListener('pagehide',()=>{if(lock)lock.release().catch(()=>{});});
    label('Keep screen awake');requestLock();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initWakeLock,{once:true});else initWakeLock();
})();
