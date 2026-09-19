const socket = io();
let publicState = null, selectedBoardId = null;
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
socket.on('connect',()=>{document.getElementById('connectionStatus').textContent='Live public boards';socket.emit('watch_public_boards');});
socket.on('disconnect',()=>{document.getElementById('connectionStatus').textContent='Connection lost. Reconnecting...';});
socket.on('public_boards_state',renderBoards);
