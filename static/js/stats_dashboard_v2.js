(() => {
  'use strict';
  if (window.location.pathname !== '/') return;

  const state={scope:'season',start:'',end:'',data:null,loading:false,error:'',requestKey:''};
  let observer=null;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const container=()=>document.getElementById('stats-content-container');
  const active=()=>document.getElementById('stats')?.classList.contains('active')||location.hash==='#stats';
  const renderer=()=>window.CoachStatsV2Renderer;

  function query(){
    const p=new URLSearchParams({scope:state.scope});
    if(state.scope==='range'){
      if(state.start)p.set('start',state.start);
      if(state.end)p.set('end',state.end);
    }
    return p.toString();
  }

  function renderLoading(){
    const c=container();
    if(c)c.innerHTML='<div data-stats-dashboard-v2 class="sv2-loading"><span class="spinner-border spinner-border-sm"></span> Building season usage dashboard…</div>';
  }

  function render(){
    const c=container(); if(!c)return;
    if(state.loading){renderLoading();return;}
    if(state.error){c.innerHTML=`<div data-stats-dashboard-v2 class="alert alert-danger">${esc(state.error)}</div>`;return;}
    if(!state.data)return;
    if(!renderer()){
      setTimeout(render,40);
      return;
    }
    c.innerHTML=renderer().render(state.data,state);
  }

  async function load(force=false){
    if(!active()&&!force)return;
    const key=query();
    if(state.loading)return;
    if(!force&&state.data&&state.requestKey===key){render();return;}
    state.loading=true;state.error='';state.requestKey=key;renderLoading();
    try{
      const response=await fetch(`/api/stats-dashboard?${key}&_=${Date.now()}`,{cache:'no-store'});
      const data=await response.json().catch(()=>({}));
      if(!response.ok||data.status==='error')throw new Error(data.message||'Unable to load team stats.');
      state.data=data;
    }catch(error){state.error=error.message||'Unable to load team stats.';}
    finally{state.loading=false;render();}
  }

  function handleClick(event){
    const scope=event.target.closest('[data-sv2-scope]');
    if(scope){state.scope=scope.dataset.sv2Scope;load(true);return;}
    if(event.target.closest('#sv2ApplyRange')){
      state.start=document.getElementById('sv2Start')?.value||'';
      state.end=document.getElementById('sv2End')?.value||'';
      state.scope='range';
      load(true);return;
    }
    const player=event.target.closest('[data-sv2-player]');
    if(player&&state.data&&renderer())renderer().openPlayer(state.data,player.dataset.sv2Player);
  }

  function start(){
    document.addEventListener('click',handleClick);
    document.addEventListener('shown.bs.tab',event=>{
      const target=event.target?.getAttribute?.('href')||event.target?.dataset?.bsTarget||'';
      if(target==='#stats')load();
    });
    window.addEventListener('hashchange',()=>{if(location.hash==='#stats')load();});
    window.addEventListener('focus',()=>{if(active()&&state.data)load(true);});

    const c=container();
    if(c){
      observer=new MutationObserver(()=>{
        if(active()&&state.data&&!c.querySelector(':scope > [data-stats-dashboard-v2]'))queueMicrotask(render);
      });
      observer.observe(c,{childList:true});
    }
    setTimeout(()=>{if(active())load();},0);
  }

  document.readyState==='loading'?document.addEventListener('DOMContentLoaded',start,{once:true}):start();
})();
