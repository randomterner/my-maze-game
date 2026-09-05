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
      const items = document.createElement('div');
      items.textContent = tr('Items:') + ' ' + (Object.entries(player.items || {}).filter(([,value]) => value).map(([key]) => tr(key)).join(', ') || tr('No items yet.'));
      row.appendChild(items);
      container.appendChild(row);
    });
  };
})();
