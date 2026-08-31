(() => {
  'use strict';

  const match = window.location.pathname.match(/^\/game\/(\d+)\/?$/);
  if (!match) return;

  const STYLE_ID = 'cb-live-dugout-workflow-style';
  let rootObserver = null;
  let started = false;

  const setText = (el, value) => {
    if (el && el.textContent !== value) el.textContent = value;
  };
  const setHtml = (el, value) => {
    if (el && el.innerHTML !== value) el.innerHTML = value;
  };

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      body.cb-dugout #liveSetDefenseBtnCoach,
      body.cb-dugout [data-cb-full-defense] {
        display:none!important;
      }
      body.cb-dugout #cbQuickDefense .cb-qd-actions {
        display:none!important;
      }
      body.cb-dugout #cbQuickDefense .cb-bench-note {
        display:none!important;
      }
      body.cb-dugout #coach-action-slot.coach-actions {
        grid-template-columns:repeat(2,minmax(0,1fr))!important;
        gap:9px!important;
      }
      body.cb-dugout #liveChangePitcherBtn,
      body.cb-dugout #liveEndInningBtn {
        min-height:62px!important;
      }
      body.cb-dugout #liveUndoBtn {
        grid-column:1/-1!important;
        width:auto!important;
        min-height:28px!important;
        justify-self:center!important;
        border:0!important;
        background:transparent!important;
        color:#667085!important;
        padding:3px 10px!important;
        box-shadow:none!important;
      }
      body.cb-dugout #liveUndoBtn .coach-action-title {
        font-size:.74rem!important;
        text-decoration:underline;
        text-underline-offset:2px;
      }
      body.cb-dugout #liveUndoBtn .coach-action-note {
        display:none!important;
      }
      body.cb-dugout #liveChangePitcherBtn .coach-action-note,
      body.cb-dugout #liveEndInningBtn .coach-action-note {
        font-size:0!important;
        opacity:.78!important;
      }
      body.cb-dugout #liveChangePitcherBtn .coach-action-note::after {
        content:'This inning';
        font-size:.67rem;
      }
      body.cb-dugout #liveEndInningBtn .coach-action-note::after {
        content:'Send next defense out';
        font-size:.67rem;
      }
      body.cb-dugout #cbQuickDefense .cb-qd-bench {
        display:flex!important;
        visibility:visible!important;
      }
      @media(max-width:575.98px){
        html body.cb-dugout #cbQuickDefense .cb-qd-head{padding:8px 9px 7px!important}
        html body.cb-dugout #cbQuickDefense .cb-qd-title{font-size:.9rem!important}
        html body.cb-dugout #cbQuickDefense .cb-qd-help{font-size:.64rem!important}
        html body.cb-dugout #cbQuickDefense .cb-qd-body{padding:6px 7px 8px!important}
        html body.cb-dugout #cbQuickDefense .cb-qd-field{min-height:0!important;max-height:228px!important;aspect-ratio:1.58/1!important}
        html body.cb-dugout #cbQuickDefense .cb-qd-spot{width:61px!important}
        html body.cb-dugout #cbQuickDefense .cb-qd-name{font-size:.55rem!important;padding:3px 4px!important}
        html body.cb-dugout #cbQuickDefense .cb-qd-bench-wrap{margin-top:6px!important;padding:7px!important}
        html body.cb-dugout #cbQuickDefense .cb-qd-bench-player{padding:6px 7px!important;font-size:.66rem!important}
        body.cb-dugout #coach-action-slot.coach-actions{position:sticky;bottom:0;z-index:1030;background:#eef1f4;padding:7px 0 calc(7px + env(safe-area-inset-bottom));margin-bottom:8px!important}
        body.cb-dugout #liveChangePitcherBtn,
        body.cb-dugout #liveEndInningBtn{min-height:56px!important}
      }
      @media(orientation:landscape) and (max-height:599.98px){
        html body.cb-dugout #cbQuickDefense .cb-qd-field{max-height:205px!important;width:min(62vw,480px)!important}
      }
    `;
    document.head.appendChild(style);
  }

  function removeBulkDefense() {
    document.getElementById('liveSetDefenseBtnCoach')?.remove();
    document.getElementById('live-bulk-defense-coach')?.remove();
    document.querySelectorAll('[data-cb-full-defense]').forEach(button => button.remove());
  }

  function patchStaticCopy() {
    removeBulkDefense();
    const card = document.getElementById('cbQuickDefense');
    if (card) {
      setText(card.querySelector('.cb-qd-kicker'), 'ON THE FIELD');
      setText(card.querySelector('.cb-qd-title'), 'Defense Now');
      setText(card.querySelector('.cb-qd-help'), 'Tap a fielder or bench player to make one sub.');
      const benchTitle = card.querySelector('.cb-qd-bench-head strong');
      if (benchTitle && /^Bench now/i.test(benchTitle.textContent || '')) {
        setText(benchTitle, benchTitle.textContent.replace(/^Bench now/i, 'On the Bench'));
      }
    }
    setText(document.querySelector('.cb-end-zone small'), 'After the last out');
  }

  function patchMenu() {
    const modal = document.getElementById('cbCoachBoardNavModal');
    if (!modal) return;
    setText(modal.querySelector('.modal-header .small.text-muted'), 'Game stays live.');
    setHtml(modal.querySelector('.cb-nav-safe'), '<strong>Game stays live.</strong> Clock stays as-is.');
  }

  function retrySuppressedEditorSave(event) {
    const save = event.target.closest?.('#cb-live-field-editor [data-cb-editor-save]');
    if (!save || save.disabled) return;

    // The field editor suppresses the synthetic click immediately following a
    // drag so a dropped player is not accidentally selected. A coach can,
    // however, intentionally press Save immediately after that drag. If that
    // first click is swallowed, retry once after the drag guard expires.
    window.setTimeout(() => {
      const modal = document.getElementById('cb-live-field-editor');
      const currentSave = modal?.querySelector('[data-cb-editor-save]');
      if (!modal?.classList.contains('show') || !currentSave || currentSave.disabled) return;
      currentSave.click();
    }, 400);
  }

  function start() {
    if (started) return;
    if (!document.body) {
      document.addEventListener('DOMContentLoaded', start, {once:true});
      return;
    }
    started = true;
    installStyles();
    document.getElementById('cbCurrentInningStrip')?.remove();
    patchStaticCopy();

    // The newer live_game_feedback_pass owns Defense Change, Change Pitcher,
    // Bench Report and End Inning. Do not intercept End Inning here; two
    // capture-phase owners caused the legacy sheet to win before the unified
    // field editor could open.
    document.addEventListener('click', retrySuppressedEditorSave, true);
    document.addEventListener('click', event => {
      if (event.target.closest?.('[data-cb-menu], #cbCoachBoardNavBtn')) window.setTimeout(patchMenu, 0);
    }, true);

    // Only watch for creation of the live card. Do not observe and rewrite its
    // children: live state rendering owns those nodes, and competing observers
    // previously detached bench buttons while a coach was tapping them.
    if (!document.getElementById('cbQuickDefense')) {
      rootObserver = new MutationObserver(() => {
        if (!document.getElementById('cbQuickDefense')) return;
        patchStaticCopy();
        rootObserver?.disconnect();
        rootObserver = null;
      });
      rootObserver.observe(document.body, {childList:true, subtree:true});
    }
  }

  start();
})();
