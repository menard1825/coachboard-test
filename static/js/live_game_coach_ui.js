(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  let enhanced = false;
  let defenseView = 'list';

  function addStyles() {
    if ($('coach-live-polish-styles')) return;
    const style = document.createElement('style');
    style.id = 'coach-live-polish-styles';
    style.textContent = `
      #live-game-overlay.coach-live-polished { background:#f4f6f8 !important; padding:12px !important; }
      #live-game-overlay.coach-live-polished > :not(.coach-live-shell):not(.modal) { display:none !important; }
      .coach-live-shell  { max-width:980px; margin:0 auto; }
      .coach-live-head { display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:10px; }
      .coach-inning-pill { background:#111827; color:#fff; border-radius:14px; min-width:92px; padding:8px 12px; text-align:center; }
      .coach-inning-pill small { display:block; font-size:.68rem; opacity:.75; font-weight:800; letter-spacing:.05em; }
      .coach-inning-pill strong { display:block; font-size:1.6rem; line-height:1; }
      .coach-card { background:#fff; border:1px solid #e5e7eb; border-radius:16px; box-shadow:0 2px 8px rgba(15,23,42,.06); padding:12px; margin-bottom:10px; }
      .coach-label { font-size:.73rem; color:#6b7280; text-transform:uppercase; letter-spacing:.05em; font-weight:800; }
      .coach-actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px; }
      .coach-actions .btn { min-height:72px; border-radius:14px !important; font-weight:800; }
      .coach-actions .btn i { display:block; font-size:1.3rem; margin-bottom:2px; }
      .coach-defense-row { display:grid; grid-template-columns:46px 1fr; gap:10px; align-items:center; padding:9px 0; border-bottom:1px solid #eef0f2; }
      .coach-pos { display:flex; align-items:center; justify-content:center; width:42px; height:32px; border-radius:8px; background:#111827; color:#fff; font-weight:800; font-size:.76rem; }
      .coach-player-name { font-weight:750; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
      .coach-player-name.empty { color:#9ca3af; font-weight:600; }
      .coach-bench { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
      .coach-bench span { border:1px solid #d1d5db; background:#fff; border-radius:999px; padding:6px 10px; font-size:.78rem; font-weight:700; }
      .coach-view-toggle .btn { font-size:.75rem; font-weight:700; }
      .coach-field-grid { background:linear-gradient(#e9f7e8,#f7f4df); border:1px solid #d9e4d5; border-radius:14px; padding:10px 6px; margin-top:9px; }
      .coach-field-row { display:flex; justify-content:center; gap:6px; margin:7px 0; }
      .coach-field-spot { flex:1; min-width:0; max-width:145px; text-align:center; background:rgba(255,255,255,.93); border:1px solid rgba(0,0,0,.08); border-radius:9px; padding:6px 4px; }
      .coach-field-spot strong { display:block; color:#6b7280; font-size:.65rem; }
      .coach-field-spot span { display:block; font-weight:800; font-size:.74rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      #rotation-board.coach-live-board-hidden { display:none !important; }
      #live-defense-v2 .modal-dialog, #live-pitcher-picker-v2 .modal-dialog, #live-defense-destination-v2 .modal-dialog, #live-pitcher-destination-v2 .modal-dialog { margin:.55rem; }
      #live-defense-v2 .list-group-item, #live-pitcher-picker-v2 .pitcher-choice-v2 { border:1px solid #e1e5ea !important; border-radius:12px !important; margin-bottom:8px; padding:13px !important; }
      #live-defense-destination-v2 .btn, #live-pitcher-destination-v2 .btn { min-height:68px; border-radius:12px; font-weight:800; }
      #live-defense-v2 .modal-title::after { content:' - Pick a player, then a destination'; font-size:.72rem; font-weight:400; color:#6b7280; }
      @media (min-width:768px) { .coach-actions { grid-template-columns:repeat(4,1fr); } }
    `;
    document.head.appendChild(style);
  }

  function posName(pos, mode) {
    const zone = $(`pos-${mode}-${pos}`);
    const tag = zone?.querySelector('.player-tag');
    return tag?.dataset?.playerName || tag?.textContent?.trim() || '';
  }

  function currentMode() {
    return window.matchMedia('(min-width: 992px)').matches ? 'desktop' : 'mobile';
  }

  function positions() {
    return $('pos-mobile-LCF') || $('pos-desktop-LCF')
      ? ['P','C','1B','2B','3B','SS','LF','LCF','RCF','RF']
      : ['P','C','1B','2B','3B','SS','LF','CF','RF'];
  }

  function currentDefense() {
    const mode = currentMode();
    const result = {};
    positions().forEach(pos => result[pos] = posName(pos, mode));
    return result;
  }

  function benchNames() {
    const mode = currentMoe();
    const host = mode === 'desktop' ? $('bench-list-desktop') : $('bench-list-mobile');
    if (!host) return [];
    const tags = host.querySelectorAll('.player-tag, .badge');
    return [...tags].map(el => el.dataset?.playerName || el.textContent.trim()).filter(Boolean);
  }

  function listMarkup() {
    const defense = currentDefense();
    const rows = positions().map(pos => `
      <div class="coach-defense-row">
        <div class="coach-pos">${pos}</div>
        <div class="coach-player-name ${defense[pos] ? '' : 'empty'}">${defense[pos] || 'Open'}</div>
      </div>`).join('');
    const bench = benchNames();
    return `${rows}<div class="coach-label mt-3">Bench</div><div class="coach-bench">${
      bench.length ? bench.map(name => `<span>${name}</span>`).join('') : '<span>No players on bench</span>'
    }</div>`;
  }

  function spot(pos, defense) {
    return `<div class="coach-field-spot"><strong>${pos}</strong><span>${defense[pos] || 'Open'}</span></div>`;
  }

  function fieldMarkup() {
    const defense = currentDefense();
    const out = positions().includes('LCF') ? ['LF','LCF','RCF','RF'] : ['LF','CF','RF'];
    return `<div class="coach-field-grid">
      <div class="coach-field-row">${out.map(pos => spot(pos, defense)).join('')}</div>
      <div class="coach-field-row">${['3B','SS','2B','1B'].map(pos => spot(pos, defense)).join('')}</div>
      <div class="coach-field-row">${spot('P', defense)}</div>
      <div class="coach-field-row">${spot('C', defense)}</div>
    </div><div class="small text-muted text-center mt-2">Display only - use Defensive Change to move players.</div>`;
  }

  function refreshDefense() {
    const host = $('coach-current-defense');
    if (!host) return;
    host.innerHTML = defenseView === 'list' ? listMarkup() : fieldMarkup();
    document.querySelectorAll('[data-coach-defense-view]').forEach(btn => {
      const active = btn.dataset.coachDefenseView === defenseView;
      btn.classList.toggle('btn-dark', active);
      btn.classList.toggle('btn-outline-dark', !active);
    });
  }

  function enhance() {
    const overlay = $('live-game-overlay');
    if (!overlay || overlay.classList.contains('d-none') || enhanced) return;
    addStyles();
    overlay.classList.add('coach-live-polished');

    const inning = $('live-inning-display');
    const pitcherCard = $('live-current-pitcher')?.closest('.card');
    const endGame = $('liveEndGameBtn')?.closest('.d-grid') || $('liveEndGameBtn');

    const actionIds = ['liveChangePitcherBtn','liveDefensiveChangeBtn','liveEndInningBtn','liveUndoBtn'];
    const actionButtons = actionIds.map(id => $(id)).filter(Boolean);

    const shell = document.createElement('div');
    shell.className = 'coach-live-shell';
    shell.innerHTML = `<div class="coach-live-head">
        <div>
          <div class="coach-label">Live Dugout</div>
          <div class="small text-muted">Actual game state - Saved for every coach</div>
        </div>
        <div class="coach-inning-pill"><small>INNING</small><strong id="coach-inning-copy">${inning?.textContent || '1'}</strong></div>
      </div>
      <div id="coach-pitcher-slot"></div>
      <div class="coach-actions" id="coach-action-slot"></div>
      <div class="coach-card">
        <div class="d-flex align-items-center justify-content-between gap-2">
          <div><div class="coach-label">Current Defense</div><div class="small text-muted">List view is fastest in the dugout</div></div>
          <div class="btn-group coach-view-toggle">
            <button class="btn btn-dark" data-coach-defense-view="list"><i class="bi bi-list-ul"></i> List</button>
            <button class="btn btn-outline-dark" data-coach-defense-view="field"><i class="bi bi-diamond"></i> Field</button>
          </div>
        </div>
        <div id="coach-current-defense" class="mt-2"></div>
      </div>
      <div id="coach-existing-extra"></div>
    `;

    overlay.appendChild(shell);
    const sync = $('live-sync-status-v2');
    if (sync) shell.querySelector('.coach-live-head > div:first-child').prepend(sync);
    if (pitcherCard) {
      pitcherCard.classList.add('coach-card');
      pitcherCard.classList.remove('border-primary');
      shell.querySelector('#coach-pitcher-slot').appendChild(pitcherCard);
    }
    actionButtons.forEach(btn => shell.querySelector('#coach-action-slot').appendChild(btn));
    const extra = shell.querySelector('#coach-existing-extra');
    const uptext = $('live-up-next-v2');
    if (uptext) extr.appendChild(uptext);
    if (endGame) extra.appendChild(endGame);

    const board = $('rotation-board');
    if (board) board.classList.add('coach-live-board-hidden');
    const title = $('rotation-editor-title');
    if (title) title.textContent = 'Live$Dugout';

    shell.addEventListener('click', event => {
      const view = event.target.closest('[data-coach-defense-view]');
      if (!view) return;
      defenseView = view.dataset.coachDefenseView;
      refreshDefense();
    });

    enhanced = true;
    refreshDefense();
  }

  function polishLiveModals() {
    // Pitcher changes should always go through the dedicated Change Pitcher flow,
    // where workload/eligibility is ¾+"nW‹ˆY™[œÚ]™HÚ[™ÙH\È›ÜˆÜÚ][Ûˆ[İ™\Ë‚ˆØİ[Y[œ]Y\TÙ[XİÜ[
	ÈÛ]™KYY™[œÙK]Œˆ›\İYÜ›İ\Z][IÊK™›Ü‘XXÚ
][HOˆÂˆÛÛœİÜÈH][Kœ]Y\TÙ[XİÜŠ	Üİ›Û™ÉÊOË^ÛÛ[Ëš[J
NÂˆYˆ
ÜÈOOH	Ô	ÊHÂˆ][KœÙ]]šX]J	Ù\ØX›Y	Ë	Ù\ØX›Y	ÊNÂˆ][K˜Û\ÜÓ\İ˜Y
	ÛÜXÚ]KML	ÊNÂˆ][K]HH	Õ\ÙHÚ[™ÙH]Ú\ˆÈ™\XÙHH]Ú\‹‰ÎÂˆBˆJNÂ‚ˆØİ[Y[œ]Y\TÙ[XİÜ[
	ÈÛ]™KYY™[œÙKY\İ[˜][Û‹]ŒˆÙ]KY\İ[˜][ÛH”—IÊK™›Ü‘XXÚ
ˆOˆÂˆ‹œÙ]]šX]J	Ù\ØX›Y	Ë	Ù\ØX›Y	ÊNÂˆ‹˜Û\ÜÓ\İ˜Y
	ÛÜXÚ]KML	ÊNÂˆÛÛœİ›İHH‹œ]Y\TÙ[XİÜŠ	ËœÛX[	ÊNÂˆYˆ
›İJH›İK^ÛÛ[H	Õ\ÙHÚ[™ÙH]Ú\‰ÎÂˆ[ÙH‹š[œÙ\Y˜XÙ[S
	Ø™Y›Ü™Y[™	Ë	Ï]ˆÛ\ÜÏHœÛX[•\ÙHÚ[™ÙH]Ú\Ù]‰ÊNÂˆJNÂ‚ˆËÈHZ\ÜÚ[™È]ÚÛİ[]\İ™]™\ˆÛÚÈZÙH\›Z\ÜÚ[ÛˆÈ]Ú‚ˆØİ[Y[œ]Y\TÙ[XİÜ[
	ÈÛ]™K\]Ú\‹\XÚÙ\‹]Œˆœ]Ú\‹XÚÚXÙK]Œ‰ÊK™›Ü‘XXÚ
ˆOˆÂˆÛÛœİ^H‹^ÛÛ[	ÉÎÂˆYˆ
Ô]ÚÛİ[[˜ÛÛ\]_[YÚXš[]H[šÛ›İÛ‹ÚK\İ
^
JHÂˆ‹œÙ]]šX]J	Ù\ØX›Y	Ë	Ù\ØX›Y	ÊNÂˆ‹˜Û\ÜÓ\İ˜Y
	ÛÜXÚ]KML	ÊNÂˆBˆJNÂˆB‚ˆ[˜İ[ÛˆXÚÊ
HÂˆÛÛœİİ™\›^HH	
	Û]™KYØ[YK[İ™\›^IÊNÂˆYˆ
İ™\›^H	‰ˆ[İ™\›^K˜Û\ÜÓ\İ˜ÛÛZ[œÊ	Ù[›Û™IÊJHÂˆ[š[˜ÙJ
NÂˆYˆ
[š[˜ÙY
HÂˆÛÛœİÛÜHH	
	ØÛØXÚZ[›š[™ËXÛÜIÊNÂˆYˆ
ÛÜH	‰ˆ	
	Û]™KZ[›š[™ËY\Ü^IÊJHÛÜK^ÛÛ[H	
	Û]™KZ[›š[™ËY\Ü^IÊK^ÛÛ[Âˆ™Yœ™\ÚY™[œÙJ
NÂˆÛÛœİ^˜HH	
	ØÛØXÚY^\İ[™ËY^˜IÊNÂˆÛÛœİ\^H	
	Û]™K]\[™^]Œ‰ÊNÂˆYˆ
^˜H	‰ˆ\^	‰ˆY^˜K˜ÛÛZ[œÊ\^
JH^˜Kœ™\[™
\^
NÂˆÛ\Ú]™S[Ù[Ê
NÂˆBˆH[ÙHYˆ
[š[˜ÙY
HÂˆÛÛœİ›Ø\™H	
	Ü›İ][Û‹X›Ø\™	ÊNÂˆYˆ
›Ø\™
H›Ø\™˜Û\ÜÓ\İœ™[[İ™J	ØÛØXÚ[]™KX›Ø\™ZY[‰ÊNÂˆÛÛœİ]HH	
	Ü›İ][Û‹YY]Ü‹]]IÊNÂˆYˆ
]JH]K^ÛÛ[H	ÑY™[œÚ]™H›İ][Û‰ÎÂˆBˆB‚ˆØİ[Y[˜Y]™[\İ[™\Š	ÑÓPÛÛ[ØYY	Ë

HOˆÂˆYİ[\Ê
NÂˆÙ][\˜[
XÚËÌ
NÂˆXÚÊ
NÂˆJNÂŸJJ
N