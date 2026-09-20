const socket = typeof io === 'function' ? io() : null;
let publicState = null, selectedBoardId = null;
let lastUpdate = 0, lastRealtime = 0, snapshotPending = false;
const detail = document.getElementById('boardDetail');

function fitBoards() {
  const root=document.getElementById('boardsList');
  const count=Math.max(1,publicState?.boards.length||1);
  const available=Math.max(420,innerHeight-document.getElementById('boardsDashboard').getBoundingClientRect().top-24);
  const width=root.clientWidth;
  const columns=innerWidth<800?Math.max(1,Math.min(2,Math.floor(width/160))):Math.max(1,Math.min(Math.floor(width/190),Math.ceil(Math.sqrt(count*width/available))));
  const rows=Math.ceil(count/columns);
  const size=innerWidth<800?Math.min(300,width/columns-25):Math.max(90,Math.min(360,(width/columns)-30,(available/rows)-150));
  root.style.setProperty('--columns',columns);
  root.style.setProperty('--preview-size',`${size}px`);
  document.getElementById('boardsDashboard').style.setProperty('--log-height',`${Math.max(280,available-65)}px`);
}

function showBoardDetail(id) {
  selectedBoardId=id;
  updateBoardDetail();
  if(!detail.open) detail.showModal();
}

function updateBoardDetail() {
  const board=publicState?.boards.find(b=>b.id===selectedBoardId);
  if(!board){if(detail.open)detail.close();return;}
  document.getElementById('detailTitle').textContent=board.name;
  document.getElementById('detailMap').replaceChildren(createMapView(board,true));
  drawPlayerStats(document.getElementById('detailStats'),publicState.players.filter(p=>(board.member_sids||[]).includes(p.sid)));
  window.applyGameTranslations?.(detail);
}

function renderBoards(data) {
  publicState=data;
  const root=document.getElementById('boardsList');root.replaceChildren();
  document.getElementById('gameOverNotice').hidden=!data.game_over;
  if(!data.boards.length)root.textContent='No public boards yet.';
  for(const board of data.boards){
    const card=document.createElement('section');card.className='publicBoardCard'+(board.manager_map?' managerMapCard':'');
    card.tabIndex=0;card.setAttribute('role','button');card.setAttribute('aria-label',board.name);
    const title=document.createElement('h2');title.textContent=board.name;card.appendChild(title);
    card.appendChild(createMapView(board));
    const caption=document.createElement('div');caption.className='boardCaption';caption.textContent=board.archived?'Saved discoveries — position hidden':board.absolute?'Public coordinates':'Relative map';card.appendChild(caption);
    card.onclick=()=>showBoardDetail(board.id);
    card.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();showBoardDetail(board.id);}};
    root.appendChild(card);
  }
  const logs=document.getElementById('publicLogs');
  const follow=logs.scrollHeight-logs.scrollTop-logs.clientHeight<35,oldScroll=logs.scrollTop;
  logs.replaceChildren(...(data.logs||[]).map(line=>{const row=document.createElement('div');row.textContent=line;return row;}));
  fitBoards();
  logs.scrollTop=follow?logs.scrollHeight:oldScroll;
  if(detail.open)updateBoardDetail();
  updateTreasureReveal(data.treasure_reveal);
  window.applyGameTranslations?.();
}

document.getElementById('closeBoardDetail').onclick=()=>detail.close();
window.addEventListener('resize',fitBoards);
function receiveBoards(data) {
  try {
    if(!Array.isArray(data?.boards))throw new Error('Invalid public boards snapshot');
    renderBoards(data);
    lastUpdate=Date.now();
    document.getElementById('connectionStatus').textContent='Live public boards';
  } catch(error) {
    console.error(error);
    document.getElementById('connectionStatus').textContent='Could not display boards. Retrying...';
  }
}

async function refreshSnapshot() {
  if(snapshotPending || document.visibilityState==='hidden')return;
  snapshotPending=true;
  const started=Date.now();
  try {
    const response=await fetch('/api/public-boards',{cache:'no-store',signal:AbortSignal.timeout(8000)});
    if(!response.ok)throw new Error('Public board request failed');
    const data=await response.json();
    if(lastRealtime<=started)receiveBoards(data);
  } catch(error) {
    if(!publicState)document.getElementById('connectionStatus').textContent='Cannot reach the game. Retrying...';
  } finally {snapshotPending=false;}
}
socket?.on('connect',()=>{socket.emit('watch_public_boards');});
socket?.on('disconnect',()=>{document.getElementById('connectionStatus').textContent='Connection lost. Reconnecting...';refreshSnapshot();});
socket?.on('connect_error',refreshSnapshot);
socket?.on('public_boards_state',data=>{lastRealtime=Date.now();receiveBoards(data);});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'){socket?.emit('watch_public_boards');refreshSnapshot();}});
setInterval(()=>{if(Date.now()-lastUpdate>10000)refreshSnapshot();},5000);
refreshSnapshot();
