const API = '';
let TOKEN = '';
const PAGES = ['Dashboard','Calendar','Assets','Transfers','Bookings','Customers','Email Inbox',
  'Revenue Overview','Upcoming Reservations',
  "Today's Reservations",'Recent Conversations'];
const SUBS = {
  'Dashboard':'Live operational overview',
  'Assets':'Fleet — boats & jet skis',
  'Transfers':'Pickup / drop-off zones & prices',
  'Bookings':'All reservations across channels',
  'Customers':'Customer profiles & history',
  'Email Inbox':'Mail threads & detected intent',
  'Calendar':'Visual schedule — bookings per vessel',
  'Revenue Overview':'Earnings & deposits held',
  'Upcoming Reservations':'Forward booking pipeline',
  "Today's Reservations":'Departures & returns today',
  'Recent Conversations':'Unified email + WhatsApp'
};

async function api(path, opts={}){
  opts.headers = Object.assign({'Content-Type':'application/json'}, opts.headers||{});
  if(TOKEN) opts.headers['Authorization'] = 'Bearer '+TOKEN;
  const r = await fetch(API+path, opts);
  if(r.status===401){ logout(); throw new Error('unauthorized'); }
  if(!r.ok){ const e = await r.json().catch(()=>({detail:r.statusText})); throw new Error(e.detail||'error'); }
  return r.status===204?null:r.json();
}

async function login(){
  const u=document.getElementById('lu').value, p=document.getElementById('lp').value;
  const body = new URLSearchParams({username:u,password:p});
  try{
    const r = await fetch(API+'/api/auth/login',{method:'POST',
      headers:{'Content-Type':'application/x-www-form-urlencoded'},body});
    if(!r.ok) throw new Error('Invalid credentials');
    const d = await r.json();
    TOKEN = d.access_token;
    sessionStorage.setItem('tok',TOKEN);
    boot();
  }catch(e){ document.getElementById('lerr').textContent = e.message; }
}
function logout(){ TOKEN=''; sessionStorage.removeItem('tok');
  document.getElementById('shell').style.display='none';
  document.getElementById('login').style.display='flex'; }

function boot(){
  document.getElementById('login').style.display='none';
  document.getElementById('shell').style.display='grid';
  const nav = document.getElementById('nav');
  nav.innerHTML = PAGES.map(p=>`<a onclick="go('${p}')" data-p="${p}"><span class="dot"></span>${p}</a>`).join('');
  go('Dashboard');
}
function setActive(p){ document.querySelectorAll('#nav a').forEach(a=>
  a.classList.toggle('active', a.dataset.p===p)); }

async function go(page){
  setActive(page);
  document.getElementById('ptitle').textContent = page;
  document.getElementById('psub').textContent = SUBS[page]||'';
  const v = document.getElementById('view');
  v.innerHTML = '<div class="empty">Loading…</div>';
  try{ await RENDER[page](v); }
  catch(e){ v.innerHTML = `<div class="panel"><div class="err">${e.message}</div></div>`; }
}

function statusTag(s){ return `<span class="tag t-${s}">${s}</span>`; }
function money(n){ return '€'+Number(n||0).toLocaleString(undefined,{minimumFractionDigits:2}); }
function fmt(dt){ if(!dt) return '—'; const d=new Date(dt);
  return d.toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}); }

const RENDER = {
  'Dashboard': async (v)=>{
    const [sum,rev,today,up] = await Promise.all([
      api('/api/reports/bookings'), api('/api/reports/revenue'),
      api('/api/reports/today'), api('/api/reports/upcoming')]);
    v.innerHTML = `
      <div class="grid g4" style="margin-bottom:20px">
        <div class="stat"><div class="k">Bookings · 24h</div><div class="v">${sum.daily}</div></div>
        <div class="stat"><div class="k">Bookings · 7d</div><div class="v">${sum.weekly}</div></div>
        <div class="stat"><div class="k">Revenue</div><div class="v">${money(rev.revenue)}</div></div>
        <div class="stat"><div class="k">Deposits held</div><div class="v">${money(rev.deposits_held)}</div></div>
      </div>
      <div class="grid g2">
        <div class="panel"><h3>Today's Reservations</h3>${bookingTable(today)}</div>
        <div class="panel"><h3>Upcoming</h3>${bookingTable(up.slice(0,8))}</div>
      </div>`;
  },
  'Assets': async (v)=>{
    const a = await api('/api/assets');
    v.innerHTML = `<div class="toolbar"><button class="btn btn-sm" onclick="assetModal()">+ New asset</button></div>
      <div class="panel"><table><thead><tr><th>Name</th><th>Type</th><th>Cap.</th>
      <th>Packages</th><th>Deposit</th><th>Calendar</th><th>Status</th><th></th></tr></thead>
      <tbody>${a.map(x=>`<tr><td><b>${x.name}</b></td><td><span class="pill">${x.asset_type}</span></td>
      <td>${x.capacity}</td>
      <td style="font-size:12px">${(x.packages||[]).map(p=>`${p.name} ${money(p.price)}`).join(' · ')||'—'}</td>
      <td>${x.deposit_percent?x.deposit_percent+'%':money(x.deposit)}</td>
      <td class="mono" style="font-size:11px">${x.calendar_id||'—'}</td>
      <td>${x.active?'<span class="badge-live">● active</span>':'<span class="badge-off">○ off</span>'}</td>
      <td><button class="btn btn-sm btn-ghost" onclick="assetModal(${x.id})">Edit</button></td></tr>`).join('')
      ||'<tr><td colspan=8 class="empty">No assets yet</td></tr>'}</tbody></table></div>`;
  },
  'Transfers': async (v)=>{
    const z = await api('/api/transfers/zones');
    v.innerHTML = `<div class="toolbar"><button class="btn btn-sm" onclick="zoneModal()">+ New zone</button>
      <span style="color:var(--mut);font-size:12px">Car ≤3 people · Van 4-8 · Van+Car for 9+ · prices are one-way</span></div>
      <div class="panel"><table><thead><tr><th>Zone</th><th>Car (≤3)</th><th>Van (4-8)</th><th>Status</th><th></th></tr></thead>
      <tbody>${z.map(x=>`<tr><td><b>${x.name}</b></td><td>${money(x.car_price)}</td>
      <td>${money(x.van_price)}</td>
      <td>${x.active?'<span class="badge-live">● active</span>':'<span class="badge-off">○ off</span>'}</td>
      <td class="row-actions"><button class="btn btn-sm btn-ghost" onclick="zoneModal(${x.id})">Edit</button>
      <button class="btn btn-sm btn-ghost" onclick="delZone(${x.id})">Delete</button></td></tr>`).join('')
      ||'<tr><td colspan=5 class="empty">No transfer zones yet</td></tr>'}</tbody></table></div>`;
  },
  'Bookings': async (v)=>{
    const b = await api('/api/bookings');
    v.innerHTML = `<div class="toolbar"><button class="btn btn-sm" onclick="bookingModal()">+ New booking</button>
      <select id="bfilter" onchange="go('Bookings')"></select></div>
      <div class="panel">${bookingTable(b,true)}</div>`;
  },
  'Customers': async (v)=>{
    const c = await api('/api/customers');
    v.innerHTML = `<div class="toolbar"><button class="btn btn-sm" onclick="customerModal()">+ New customer</button></div>
      <div class="panel"><table><thead><tr><th>Name</th><th>Email</th><th>Phone</th>
      <th>Country</th><th>Lang</th><th></th></tr></thead><tbody>
      ${c.map(x=>`<tr><td><b>${x.full_name}</b></td><td>${x.email||'—'}</td><td>${x.phone||'—'}</td>
      <td>${x.country||'—'}</td><td><span class="pill">${x.language}</span></td>
      <td><button class="btn btn-sm btn-ghost" onclick="showConvo(${x.id},'${x.full_name}')">History</button></td></tr>`).join('')
      ||'<tr><td colspan=6 class="empty">No customers yet</td></tr>'}</tbody></table></div>`;
  },
  'Email Inbox': async (v)=>{
    const t = await api('/api/emails/threads');
    v.innerHTML = `<div class="toolbar"><button class="btn btn-sm" onclick="processInbox()">⟳ Process unread</button></div>
      <div class="panel"><table><thead><tr><th>Subject</th><th>Intent</th><th>Messages</th></tr></thead><tbody>
      ${t.map(x=>`<tr><td>${x.subject||'(no subject)'}</td><td><span class="pill">${x.intent||'—'}</span></td>
      <td>${x.messages}</td></tr>`).join('')||'<tr><td colspan=3 class="empty">Inbox empty — connect Gmail credentials to ingest mail</td></tr>'}
      </tbody></table></div>`;
  },
  'Calendar': async (v)=>{
    await renderCalendar(v, window._calStart);
  },
  'Revenue Overview': async (v)=>{
    const [rev,util] = await Promise.all([api('/api/reports/revenue'),api('/api/reports/utilization')]);
    const byS = rev.bookings_by_status||{};
    v.innerHTML = `<div class="grid g3" style="margin-bottom:20px">
      <div class="stat"><div class="k">Total revenue</div><div class="v">${money(rev.revenue)}</div></div>
      <div class="stat"><div class="k">Deposits held</div><div class="v">${money(rev.deposits_held)}</div></div>
      <div class="stat"><div class="k">Confirmed</div><div class="v">${byS.confirmed||0}</div></div></div>
      <div class="panel"><h3>Asset Utilization</h3><table><thead><tr><th>Asset</th><th>Type</th>
      <th>Bookings</th><th>Revenue</th></tr></thead><tbody>
      ${util.map(u=>`<tr><td>${u.name}</td><td><span class="pill">${u.type}</span></td>
      <td>${u.bookings}</td><td>${money(u.revenue)}</td></tr>`).join('')}</tbody></table></div>`;
  },
  'Upcoming Reservations': async (v)=>{
    const b = await api('/api/reports/upcoming'); v.innerHTML = `<div class="panel">${bookingTable(b,true)}</div>`;
  },
  "Today's Reservations": async (v)=>{
    const b = await api('/api/reports/today'); v.innerHTML = `<div class="panel">${bookingTable(b,true)}</div>`;
  },
  'Recent Conversations': async (v)=>{
    const c = await api('/api/customers');
    v.innerHTML = `<div class="panel"><h3>Customers — open a unified thread</h3>
      <table><thead><tr><th>Customer</th><th>Email</th><th>Phone</th><th></th></tr></thead><tbody>
      ${c.map(x=>`<tr><td><b>${x.full_name}</b></td><td>${x.email||'—'}</td><td>${x.phone||'—'}</td>
      <td><button class="btn btn-sm btn-ghost" onclick="showConvo(${x.id},'${x.full_name}')">Open</button></td></tr>`).join('')
      ||'<tr><td colspan=4 class="empty">No conversations yet</td></tr>'}</tbody></table></div>`;
  },
};

function bookingTable(b, full){
  if(!b||!b.length) return '<div class="empty">No reservations</div>';
  return `<table><thead><tr><th>#</th><th>Asset</th><th>Package</th><th>Start</th><th>End</th>
    <th>Total</th><th>Status</th><th>Src</th>${full?'<th></th>':''}</tr></thead><tbody>
    ${b.map(x=>`<tr><td class="mono">${x.id}</td><td>#${x.asset_id}</td>
    <td>${x.package_name||'—'}</td><td>${fmt(x.start_datetime)}</td>
    <td>${fmt(x.end_datetime)}</td><td>${money(x.total_price)}</td><td>${statusTag(x.status)}</td>
    <td><span class="pill">${x.source}</span></td>
    ${full?`<td class="row-actions">${x.status==='pending'?`<button class="btn btn-sm" onclick="confirmB(${x.id})">Confirm</button>`:''}
    ${x.status!=='cancelled'&&x.status!=='completed'?`<button class="btn btn-sm btn-ghost" onclick="cancelB(${x.id})">Cancel</button>`:''}</td>`:''}</tr>`).join('')}
    </tbody></table>`;
}

// ---- modals & actions ----
function openModal(html){ document.getElementById('modal').innerHTML=html;
  document.getElementById('modalbg').style.display='flex'; }
function closeModal(){ document.getElementById('modalbg').style.display='none'; }

async function assetModal(id){
  let a = {asset_type:'boat',capacity:1,fuel_policy:'full-to-full',active:true,deposit_percent:30};
  if(id) a = await api('/api/assets/'+id);
  openModal(`<h3>${id?'Edit':'New'} asset</h3>
    <label>Name</label><input id="m_name" value="${a.name||''}">
    <label>Type</label><select id="m_type">${['boat','jetski','car','van'].map(t=>
      `<option ${a.asset_type===t?'selected':''}>${t}</option>`).join('')}</select>
    <label>Capacity</label><input id="m_cap" type="number" value="${a.capacity||1}">
    <label>Deposit %</label><input id="m_deppct" type="number" value="${a.deposit_percent||0}">
    <label>Calendar ID</label><input id="m_cal" value="${a.calendar_id||''}">
    <label>Location</label><input id="m_loc" value="${a.location||''}">
    ${id?`<div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--line)">
      <label style="font-weight:600">Packages</label>
      <div id="m_pkgs" style="font-size:13px;margin:6px 0">loading…</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:end;margin-top:6px">
        <div><label>Name</label><input id="np_name" style="width:110px" placeholder="4h"></div>
        <div><label>Min</label><input id="np_dur" type="number" style="width:70px" placeholder="240"></div>
        <div><label>€</label><input id="np_price" type="number" style="width:80px" placeholder="350"></div>
        <button class="btn btn-sm" onclick="addPkg(${id})">+ Add</button>
      </div></div>`:'<div style="color:var(--mut);font-size:12px;margin-top:8px">Save first, then add packages.</div>'}
    <div class="err" id="merr"></div>
    <div style="display:flex;gap:8px;margin-top:14px">
    <button class="btn" onclick="saveAsset(${id||0})">Save</button>
    <button class="btn btn-ghost" onclick="closeModal()">Cancel</button></div>`);
  if(id) loadPkgs(id);
}
async function loadPkgs(assetId){
  const pkgs = await api('/api/packages/by-asset/'+assetId);
  document.getElementById('m_pkgs').innerHTML = pkgs.length
    ? pkgs.map(p=>`<div style="display:flex;justify-content:space-between;padding:3px 0">
        <span>${p.name} · ${p.duration_minutes}min · ${money(p.price)}${p.guided?' · guided':''}</span>
        <span style="cursor:pointer;color:var(--bad)" onclick="delPkg(${p.id},${assetId})">✕</span></div>`).join('')
    : '<span style="color:var(--mut)">No packages yet</span>';
}
async function addPkg(assetId){
  try{ await api('/api/packages',{method:'POST',body:JSON.stringify({
    asset_id:assetId,name:val('np_name'),duration_minutes:+val('np_dur'),
    price:+val('np_price'),guided:/safari|guid/i.test(val('np_name'))})});
    document.getElementById('np_name').value='';document.getElementById('np_dur').value='';
    document.getElementById('np_price').value=''; loadPkgs(assetId); }
  catch(e){ document.getElementById('merr').textContent=e.message; }
}
async function delPkg(pid,assetId){ await api('/api/packages/'+pid,{method:'DELETE'}); loadPkgs(assetId); }
async function saveAsset(id){
  const p = {name:val('m_name'),asset_type:val('m_type'),capacity:+val('m_cap'),
    deposit_percent:+val('m_deppct'),calendar_id:val('m_cal'),location:val('m_loc')};
  try{ await api(id?'/api/assets/'+id:'/api/assets',
    {method:id?'PATCH':'POST',body:JSON.stringify(p)});
    closeModal(); go('Assets'); }
  catch(e){ document.getElementById('merr').textContent=e.message; }
}
async function customerModal(){
  openModal(`<h3>New customer</h3>
    <label>Full name</label><input id="c_name">
    <label>Email</label><input id="c_email">
    <label>Phone</label><input id="c_phone">
    <label>Country</label><input id="c_country">
    <label>Language</label><input id="c_lang" value="en">
    <div class="err" id="merr"></div>
    <div style="display:flex;gap:8px;margin-top:14px">
    <button class="btn" onclick="saveCustomer()">Save</button>
    <button class="btn btn-ghost" onclick="closeModal()">Cancel</button></div>`);
}
async function saveCustomer(){
  try{ await api('/api/customers',{method:'POST',body:JSON.stringify({
    full_name:val('c_name'),email:val('c_email'),phone:val('c_phone'),
    country:val('c_country'),language:val('c_lang')||'en'})});
    closeModal(); go('Customers'); }
  catch(e){ document.getElementById('merr').textContent=e.message; }
}
async function bookingModal(){
  const [assets,customers] = await Promise.all([api('/api/assets'),api('/api/customers')]);
  window._assets = assets;
  openModal(`<h3>New booking</h3>
    <label>Customer</label><select id="b_cust">${customers.map(c=>
      `<option value="${c.id}">${c.full_name}</option>`).join('')}</select>
    <label>Asset</label><select id="b_asset" onchange="onAssetPick()">${assets.map(a=>
      `<option value="${a.id}">${a.name} (${a.asset_type}, cap ${a.capacity})</option>`).join('')}</select>
    <label>Package</label><select id="b_pkg" onchange="onPkgPick()"></select>
    <label>Start</label><input id="b_start" type="datetime-local">
    <label>End <span style="color:var(--mut);font-size:11px">(auto from package)</span></label>
    <input id="b_end" type="datetime-local">
    <div id="b_price" style="font-size:13px;color:var(--deep);margin-top:8px"></div>
    <div class="err" id="merr"></div>
    <div style="display:flex;gap:8px;margin-top:14px">
    <button class="btn" onclick="saveBooking()">Create</button>
    <button class="btn btn-ghost" onclick="closeModal()">Cancel</button></div>`);
  onAssetPick();
}
function onAssetPick(){
  const a = window._assets.find(x=>x.id===+val('b_asset'));
  const sel = document.getElementById('b_pkg');
  sel.innerHTML = (a.packages||[]).map(p=>
    `<option value="${p.package_id}" data-dur="${p.duration_minutes}" data-price="${p.price}">
     ${p.name} — ${money(p.price)}</option>`).join('') || '<option value="">(no packages)</option>';
  onPkgPick();
}
function onPkgPick(){
  const opt = document.getElementById('b_pkg').selectedOptions[0];
  if(!opt||!opt.value){ document.getElementById('b_price').textContent=''; return; }
  const price = +opt.dataset.price, dur = +opt.dataset.dur;
  // auto-fill end from start + duration
  const s = val('b_start');
  if(s){ const end = new Date(new Date(s).getTime()+dur*60000);
    document.getElementById('b_end').value = end.toISOString().slice(0,16); }
  const a = window._assets.find(x=>x.id===+val('b_asset'));
  const dep = a.deposit_percent ? price*a.deposit_percent/100 : 0;
  document.getElementById('b_price').textContent =
    `Total ${money(price)} · deposit ${money(dep)} (${a.deposit_percent||0}%)`;
}
async function saveBooking(){
  // ensure end is computed from package if user set start after picking
  onPkgPick();
  try{ await api('/api/bookings',{method:'POST',body:JSON.stringify({
    customer_id:+val('b_cust'),asset_id:+val('b_asset'),
    package_id:+val('b_pkg')||null,
    start_datetime:new Date(val('b_start')).toISOString(),
    end_datetime:new Date(val('b_end')).toISOString(),source:'admin'})});
    closeModal(); go('Bookings'); }
  catch(e){ document.getElementById('merr').textContent=e.message; }
}
async function confirmB(id){ try{ await api('/api/bookings/'+id+'/confirm',{method:'POST'}); go('Bookings'); }
  catch(e){ alert(e.message); } }
async function cancelB(id){ if(!confirm('Cancel booking #'+id+'?'))return;
  await api('/api/bookings/'+id+'/cancel',{method:'POST'}); go('Bookings'); }
async function processInbox(){ try{ const r=await api('/api/emails/process',{method:'POST'});
  alert('Processed '+r.processed.length+' message(s)'); go('Email Inbox'); }catch(e){ alert(e.message); } }
async function showConvo(id,name){
  const msgs = await api('/api/messages/'+id);
  openModal(`<h3>${name} — conversation</h3>
    <div class="convo">${msgs.length?msgs.map(m=>`<div class="msg ${m.direction}">${m.body}
      <div class="meta">${m.channel} · ${m.direction}</div></div>`).join('')
      :'<div class="empty">No messages yet</div>'}</div>
    <div style="margin-top:14px"><button class="btn btn-ghost" onclick="closeModal()">Close</button></div>`);
}
function val(id){ return document.getElementById(id).value; }


async function zoneModal(id){
  let z = {car_price:0,van_price:0,active:true,sort_order:0};
  if(id){ const all = await api('/api/transfers/zones'); z = all.find(x=>x.id===id)||z; }
  openModal(`<h3>${id?'Edit':'New'} transfer zone</h3>
    <label>Name (location)</label><input id="z_name" value="${z.name||''}">
    <label>Car price (≤3 people, one-way €)</label><input id="z_car" type="number" value="${z.car_price||0}">
    <label>Van price (4-8 people, one-way €)</label><input id="z_van" type="number" value="${z.van_price||0}">
    <div class="err" id="merr"></div>
    <div style="display:flex;gap:8px;margin-top:14px">
    <button class="btn" onclick="saveZone(${id||0})">Save</button>
    <button class="btn btn-ghost" onclick="closeModal()">Cancel</button></div>`);
}
async function saveZone(id){
  const p = {name:val('z_name'),car_price:+val('z_car'),van_price:+val('z_van'),
    active:true,sort_order:0};
  try{ await api(id?'/api/transfers/zones/'+id:'/api/transfers/zones',
    {method:id?'PATCH':'POST',body:JSON.stringify(p)});
    closeModal(); go('Transfers'); }
  catch(e){ document.getElementById('merr').textContent=e.message; }
}
async function delZone(id){ if(!confirm('Delete this zone?'))return;
  await api('/api/transfers/zones/'+id,{method:'DELETE'}); go('Transfers'); }


// ---- Visual calendar (vessels x days) ----
async function renderCalendar(v, startISO){
  const DAYS = 14;
  let start = startISO ? new Date(startISO) : new Date();
  start.setHours(0,0,0,0);
  start.setDate(start.getDate() - start.getDay() + (start.getDay()===0?-6:1)); // Monday
  window._calStart = start.toISOString();
  const end = new Date(start); end.setDate(end.getDate()+DAYS);

  let data;
  try{ data = await api(`/api/calendar?start=${start.toISOString()}&end=${end.toISOString()}`); }
  catch(e){ v.innerHTML = `<div class="panel"><div class="err">${e.message}</div></div>`; return; }

  const days = [];
  for(let i=0;i<DAYS;i++){ const d=new Date(start); d.setDate(d.getDate()+i); days.push(d); }
  const dayLabel = d => d.toLocaleDateString(undefined,{weekday:'short',day:'numeric',month:'numeric'});
  const isWeekend = d => d.getDay()===0||d.getDay()===6;

  // group events by asset
  const byAsset = {};
  data.events.forEach(e=>{ (byAsset[e.asset_id]=byAsset[e.asset_id]||[]).push(e); });

  const colW = 78, rowH = 44, labelW = 150;
  const fmtRange = `${days[0].toLocaleDateString(undefined,{day:'numeric',month:'short'})} – ${days[DAYS-1].toLocaleDateString(undefined,{day:'numeric',month:'short'})}`;

  let header = `<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
    <button class="btn btn-sm btn-ghost" onclick="calNav(-7)">‹ Prev</button>
    <button class="btn btn-sm btn-ghost" onclick="calNav(0)">Today</button>
    <button class="btn btn-sm btn-ghost" onclick="calNav(7)">Next ›</button>
    <span style="font-family:'Fraunces',serif;font-size:18px;margin-left:8px">${fmtRange}</span></div>`;

  // column headers
  let colHead = `<div style="display:grid;grid-template-columns:${labelW}px repeat(${DAYS},${colW}px);position:sticky;top:0;z-index:2">
    <div style="background:var(--ink);color:var(--sand);padding:8px;font-size:11px;text-transform:uppercase;letter-spacing:1px;border-radius:3px 0 0 0">Vessel</div>
    ${days.map(d=>`<div style="background:${isWeekend(d)?'var(--deep)':'var(--ink)'};color:var(--sand);padding:8px 4px;text-align:center;font-size:11px;border-left:1px solid rgba(255,255,255,.1)">${dayLabel(d)}</div>`).join('')}</div>`;

  // rows
  let rows = data.assets.map((a,ri)=>{
    const evs = byAsset[a.id]||[];
    let bars = evs.map(e=>{
      const s = new Date(e.start), en = new Date(e.end);
      let offDays = (s - start)/(1000*60*60*24);
      let durDays = Math.max((en - s)/(1000*60*60*24), 0.25);
      if(offDays<0){ durDays += offDays; offDays=0; }
      if(offDays>=DAYS) return '';
      if(offDays+durDays>DAYS) durDays = DAYS-offDays;
      const left = labelW + offDays*colW;
      const width = Math.max(durDays*colW - 4, 18);
      const colorMap = {confirmed:'var(--good)',pending:'var(--warn)',completed:'var(--deep)'};
      const bg = colorMap[e.status]||'var(--teal)';
      const tip = `${e.title} · ${e.package||''} · ${money(e.total_price)} · ${e.status}`;
      return `<div title="${tip.replace(/"/g,'&quot;')}" onclick="openBookingFromCal(${e.id})"
        style="position:absolute;top:6px;left:${left}px;width:${width}px;height:${rowH-12}px;
        background:${bg};color:#fff;border-radius:4px;padding:0 6px;font-size:11px;line-height:${rowH-12}px;
        white-space:nowrap;overflow:hidden;cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.2)">
        ${e.title}${e.package?' · '+e.package:''}</div>`;
    }).join('');
    const dayCells = days.map(d=>`<div style="border-left:1px solid var(--line);background:${isWeekend(d)?'rgba(15,106,125,.05)':'transparent'}"></div>`).join('');
    return `<div style="position:relative;display:grid;grid-template-columns:${labelW}px repeat(${DAYS},${colW}px);height:${rowH}px;border-bottom:1px solid var(--line);background:${ri%2?'rgba(244,239,230,.4)':'#fff'}">
      <div style="padding:8px;font-size:12px;font-weight:600;display:flex;align-items:center;gap:6px;border-right:2px solid var(--line)">
        <span class="pill" style="font-size:9px">${a.type}</span>${a.name}</div>
      ${dayCells}${bars}</div>`;
  }).join('');

  let legend = `<div style="display:flex;gap:16px;margin-top:14px;font-size:12px;color:var(--mut)">
    <span><span style="display:inline-block;width:12px;height:12px;background:var(--good);border-radius:2px;vertical-align:middle"></span> confirmed</span>
    <span><span style="display:inline-block;width:12px;height:12px;background:var(--warn);border-radius:2px;vertical-align:middle"></span> pending</span>
    <span><span style="display:inline-block;width:12px;height:12px;background:var(--deep);border-radius:2px;vertical-align:middle"></span> completed</span>
    <span style="margin-left:auto">Tip: click a booking to open it</span></div>`;

  v.innerHTML = header + `<div class="panel" style="padding:0;overflow-x:auto">
    <div style="min-width:${labelW+DAYS*colW}px">${colHead}${rows||'<div class="empty">No vessels</div>'}</div></div>` + legend;
}
function calNav(deltaDays){
  if(deltaDays===0){ window._calStart=null; }
  else { const d = new Date(window._calStart||new Date()); d.setDate(d.getDate()+deltaDays); window._calStart=d.toISOString(); }
  go('Calendar');
}
async function openBookingFromCal(id){
  try{ const b = await api('/api/bookings/'+id);
    openModal(`<h3>Booking #${b.id}</h3>
      <div style="font-size:13px;line-height:1.8">
      <div><b>Package:</b> ${b.package_name||'—'}</div>
      <div><b>Start:</b> ${fmt(b.start_datetime)}</div>
      <div><b>End:</b> ${fmt(b.end_datetime)}</div>
      <div><b>Total:</b> ${money(b.total_price)} · <b>Deposit:</b> ${money(b.deposit_amount)}</div>
      <div><b>Status:</b> ${statusTag(b.status)}</div></div>
      <div style="display:flex;gap:8px;margin-top:14px">
      ${b.status==='pending'?`<button class="btn btn-sm" onclick="confirmB(${b.id});closeModal()">Confirm</button>`:''}
      ${b.status!=='cancelled'&&b.status!=='completed'?`<button class="btn btn-sm btn-ghost" onclick="cancelB(${b.id});closeModal()">Cancel</button>`:''}
      <button class="btn btn-sm btn-ghost" onclick="closeModal()">Close</button></div>`);
  }catch(e){ alert(e.message); }
}


// auto-login if token cached
const cached = sessionStorage.getItem('tok');
if(cached){ TOKEN=cached; boot(); }
