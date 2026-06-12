const API = '';
let TOKEN = '';
const PAGES = ['Dashboard','Calendar','Assets','Transfers','Bookings','Customers','Email Inbox','Mail Settings',
  'Settings',
  'Revenue Overview','Upcoming Reservations',
  "Today's Reservations",'Recent Conversations'];
const SUBS = {
  'Dashboard':'Live operational overview',
  'Assets':'Fleet — boats & jet skis',
  'Transfers':'Pickup / drop-off zones & prices',
  'Bookings':'All reservations across channels',
  'Customers':'Customer profiles & history',
  'Email Inbox':'Mail threads & detected intent',
  'Mail Settings':'Email accounts the AI watches & replies from',
  'Settings':'Pravila rezervacije (vrijeme unaprijed)',
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
  nav.innerHTML = PAGES.map(p=>`<a data-p="${p.replace(/"/g,'&quot;')}"><span class="dot"></span>${p}</a>`).join('');
  nav.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>go(a.dataset.p)));
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
      <tbody>${a.map(x=>`<tr><td><b>${x.name}</b>${x.is_external?` <span class="pill" style="background:var(--warn);color:#fff" title="Partnerski brod — ${x.owner_name||'vlasnik'}, ${x.commission_percent||0}% provizija">partner</span>`:''}</td><td><span class="pill">${x.asset_type}</span></td>
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
  'Mail Settings': async (v)=>{
    const boxes = await api('/api/mailboxes');
    v.innerHTML = `<div class="toolbar"><button class="btn btn-sm" onclick="mailboxModal()">+ Add email account</button>
      <span style="color:var(--mut);font-size:12px">The AI watches these inboxes and replies from the SAME address that received the message.</span></div>
      <div class="panel"><table><thead><tr><th>Address</th><th>IMAP host</th><th>SMTP host</th><th>Password</th><th>Status</th><th></th></tr></thead>
      <tbody>${boxes.map(m=>`<tr><td><b>${m.address}</b></td><td class="mono" style="font-size:11px">${m.imap_host}:${m.imap_port}</td>
      <td class="mono" style="font-size:11px">${m.smtp_host}:${m.smtp_port}</td>
      <td>${m.has_password?'<span class="badge-live">● set</span>':'<span class="badge-off">○ none</span>'}</td>
      <td>${m.active?'<span class="badge-live">● active</span>':'<span class="badge-off">○ off</span>'}</td>
      <td class="row-actions"><button class="btn btn-sm btn-ghost" onclick="testMailbox(${m.id})">Test</button>
      <button class="btn btn-sm btn-ghost" onclick="mailboxModal(${m.id})">Edit</button>
      <button class="btn btn-sm btn-ghost" onclick="delMailbox(${m.id})">Delete</button></td></tr>`).join('')
      ||'<tr><td colspan=6 class="empty">No email accounts yet — add one so the AI can answer mail</td></tr>'}</tbody></table></div>`;
  },
  'Bookings': async (v)=>{
    const b = await api('/api/bookings');
    v.innerHTML = `<div class="toolbar"><button class="btn btn-sm" onclick="bookingModal()">+ New booking</button></div>
      <div class="panel">${bookingTable(b,true)}</div>`;
  },
  'Settings': async (v)=>{
    const [lt, biz] = await Promise.all([api('/api/settings/lead-times'), api('/api/settings/business')]);
    v.innerHTML = `<div class="panel" style="max-width:520px">
      <h3 style="margin-top:0">Brendovi (što gosti vide)</h3>
      <p style="color:var(--mut);font-size:13px">Ime koje gost vidi na potvrdi/vaučeru ovisi o tome što je bukirao.</p>
      <label>Brodovi</label><input id="set_brand_boat" value="${biz.brand_boat||''}" placeholder="Seagull Dubrovnik">
      <label>Jet ski</label><input id="set_brand_jetski" value="${biz.brand_jetski||''}" placeholder="Jetski Dubrovnik">
      <label>Transferi</label><input id="set_brand_transfer" value="${biz.brand_transfer||''}" placeholder="Ragusa Transfer">
      <label>Zadani depozit (%)</label><input id="set_dep" type="number" min="0" max="100" value="${biz.default_deposit_percent||30}">
      <div style="margin:12px 0 20px"><button class="btn" onclick="saveBusiness()">Spremi brendove</button>
      <span id="biz_msg" style="margin-left:12px;color:var(--good);font-size:13px"></span></div>
      <h3>Minimalno vrijeme rezervacije unaprijed</h3>
      <p style="color:var(--mut);font-size:13px">Koliko sati prije početka gost može najkasnije rezervirati. (Tvoje admin rezervacije nisu ograničene.)</p>
      <label>Jet ski (sati)</label><input id="lt_jetski" type="number" min="0" value="${lt.jetski}">
      <label>Gliseri / brodovi (sati)</label><input id="lt_boat" type="number" min="0" value="${lt.boat}">
      <label>Transferi (sati)</label><input id="lt_transfer" type="number" min="0" value="${lt.transfer}">
      <div style="margin-top:16px"><button class="btn" onclick="saveLeadTimes()">Spremi</button>
      <span id="lt_msg" style="margin-left:12px;color:var(--good);font-size:13px"></span></div>
    </div>`;
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
    <th>Total</th><th>Status</th><th>Plaćanje</th><th>Src</th>${full?'<th></th>':''}</tr></thead><tbody>
    ${b.map(x=>`<tr><td class="mono">${x.id}</td><td>#${x.asset_id}</td>
    <td>${x.package_name||'—'}</td><td>${fmt(x.start_datetime)}</td>
    <td>${fmt(x.end_datetime)}</td><td>${money(x.total_price)}</td><td>${statusTag(x.status)}</td>
    <td>${payTag(x.payment_status)}</td>
    <td><span class="pill">${x.source}</span></td>
    ${full?`<td class="row-actions">${x.status==='pending'?`<button class="btn btn-sm" onclick="confirmB(${x.id})">Confirm</button>`:''}
    ${(x.payment_status!=='deposit_paid')?`<button class="btn btn-sm" onclick="chargeDeposit(${x.id})">Naplati depozit</button>`:''}
    ${(x.payment_status!=='deposit_paid')?`<button class="btn btn-sm btn-ghost" onclick="editDeposit(${x.id},${x.deposit_amount||0})">Uredi depozit</button>`:''}
    ${(x.payment_status==='deposit_paid')?`<button class="btn btn-sm btn-ghost" onclick="sendConfirm(${x.id})">Pošalji potvrdu</button>`:''}
    ${(x.payment_status==='deposit_paid')?`<button class="btn btn-sm btn-ghost" onclick="refundB(${x.id})">Povrat</button>`:''}
    <button class="btn btn-sm btn-ghost" onclick="openVoucher(${x.id})">Voucher</button>
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
    <label>Link stranice (slike i opis broda)</label><input id="m_page" value="${a.page_url||''}" placeholder="https://...">
    <label>Zadana pickup lokacija (partner)</label><input id="m_pickup" value="${a.default_pickup||''}" placeholder="Lapadska obala 4, Dubrovnik">
    <label>Grupa modela <span style="color:var(--mut);font-size:11px">(isti brodovi dijele istu grupu, npr. "barracuda-545")</span></label>
    <input id="m_group" value="${a.model_group||''}" placeholder="barracuda-545">
    <label>Prioritet <span style="color:var(--mut);font-size:11px">(manji = prvo se nudi; tvoj brod = 1)</span></label>
    <input id="m_prio" type="number" min="1" value="${a.booking_priority||100}">
    <div style="margin-top:14px;padding:12px;border:1px dashed var(--line);border-radius:6px;background:rgba(15,106,125,.04)">
      <label style="display:flex;align-items:center;gap:8px;font-weight:600;cursor:pointer">
        <input type="checkbox" id="m_ext" ${a.is_external?'checked':''} onchange="document.getElementById('extfields').style.display=this.checked?'block':'none'">
        Vanjski brod (partnerski — nije moj)</label>
      <div id="extfields" style="display:${a.is_external?'block':'none'};margin-top:10px">
        <p style="color:var(--mut);font-size:12px;margin-bottom:8px">AI će prije potvrde pitati vlasnika je li slobodno. Gost ovo ne vidi.</p>
        <label>Ime vlasnika</label><input id="m_oname" value="${a.owner_name||''}">
        <label>Email vlasnika</label><input id="m_oemail" value="${a.owner_email||''}">
        <label>WhatsApp/telefon vlasnika</label><input id="m_ophone" value="${a.owner_phone||''}" placeholder="+385...">
        <label>Moja provizija (%)</label><input id="m_comm" type="number" value="${a.commission_percent||15}">
        <label>Tko naplaćuje gosta?</label>
        <select id="m_paydir">
          <option value="you" ${(a.payment_direction||'you')==='you'?'selected':''}>Ja naplaćujem (partneru dugujem njegov dio)</option>
          <option value="partner" ${a.payment_direction==='partner'?'selected':''}>Partner naplaćuje (meni duguje proviziju)</option>
        </select>
      </div>
    </div>
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
    deposit_percent:+val('m_deppct'),calendar_id:val('m_cal'),location:val('m_loc'),
    page_url:val('m_page'),default_pickup:val('m_pickup'),
    model_group:val('m_group'),booking_priority:+val('m_prio')||100,
    is_external:document.getElementById('m_ext').checked,
    owner_name:val('m_oname'),owner_email:val('m_oemail'),
    owner_phone:val('m_ophone'),commission_percent:+val('m_comm'),
    payment_direction:val('m_paydir')};
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
    <label>Postojeći gost (ili upiši novog dolje)</label><select id="b_cust">
      <option value="">— novi gost —</option>
      ${customers.map(c=>`<option value="${c.id}">${c.full_name}${c.phone?(' · '+c.phone):''}</option>`).join('')}</select>
    <div style="background:var(--light,#eef3f3);padding:10px;border-radius:8px;margin:8px 0">
      <div style="font-size:12px;color:var(--mut);margin-bottom:6px">Novi gost (ako nije gore odabran):</div>
      <label>Ime i prezime gosta</label><input id="b_gname" placeholder="Mauro Mehic">
      <label>Telefon gosta</label><input id="b_gphone" placeholder="+385...">
      <label>Email gosta</label><input id="b_gemail" placeholder="gost@email.com">
    </div>
    <label>Asset</label><select id="b_asset" onchange="onAssetPick()">${assets.map(a=>
      `<option value="${a.id}">${a.name} (${a.asset_type}, cap ${a.capacity})</option>`).join('')}</select>
    <label>Package</label><select id="b_pkg" onchange="onPkgPick()"></select>
    <label>Start</label><input id="b_start" type="datetime-local" onchange="onPkgPick()">
    <label>End <span style="color:var(--mut);font-size:11px">(auto iz paketa)</span></label>
    <input id="b_end" type="datetime-local">
    <label>Broj osoba</label><input id="b_pax" type="number" min="1" value="2">
    <label>Pickup lokacija</label><input id="b_pickup" placeholder="Lapadska obala 4, Dubrovnik">
    <label>Plaćanje</label>
    <select id="b_paymode" onchange="onPayModePick()">
      <option value="paid_to_us">Gost plaća nama (depozit/online)</option>
      <option value="on_boat">Gost plaća na brodu (partner naplati, mi kasnije ispostavimo račun)</option>
    </select>
    <label>Depozit (EUR) <span style="color:var(--mut);font-size:11px">(prazno = auto)</span></label>
    <input id="b_deposit" type="number" step="0.01" placeholder="auto">
    <div id="b_price" style="font-size:13px;color:var(--deep);margin-top:8px"></div>
    <div class="err" id="merr"></div>
    <div style="display:flex;gap:8px;margin-top:14px">
    <button class="btn" onclick="saveBooking()">Create</button>
    <button class="btn btn-ghost" onclick="closeModal()">Cancel</button></div>`);
  onAssetPick();
}
async function onAssetPick(){
  const a = window._assets.find(x=>x.id===+val('b_asset'));
  const sel = document.getElementById('b_pkg');
  // fetch this asset's real packages (the assets list doesn't include them)
  let pkgs = [];
  try{ pkgs = await api('/api/packages/by-asset/'+a.id); }catch(e){ pkgs = []; }
  window._pkgCache = pkgs;
  sel.innerHTML = (pkgs||[]).map(p=>
    `<option value="${p.id}" data-dur="${p.duration_minutes}" data-price="${p.price}">
     ${p.name} — ${money(p.price)}</option>`).join('') || '<option value="">(nema paketa)</option>';
  onPkgPick();
}
function onPkgPick(){
  const opt = document.getElementById('b_pkg').selectedOptions[0];
  if(!opt||!opt.value){ document.getElementById('b_price').textContent=''; return; }
  const price = +opt.dataset.price, dur = +opt.dataset.dur;
  // auto-fill end from start + duration, in LOCAL time (no UTC shift)
  const s = val('b_start');
  if(s){
    const end = new Date(new Date(s).getTime()+dur*60000);
    // build a local 'YYYY-MM-DDTHH:MM' string so the field shows the right clock time
    const pad=n=>String(n).padStart(2,'0');
    const local = end.getFullYear()+'-'+pad(end.getMonth()+1)+'-'+pad(end.getDate())+
                  'T'+pad(end.getHours())+':'+pad(end.getMinutes());
    document.getElementById('b_end').value = local;
  }
  const a = window._assets.find(x=>x.id===+val('b_asset'));
  const dep = a.deposit_percent ? price*a.deposit_percent/100 : 0;
  document.getElementById('b_price').textContent =
    `Total ${money(price)} · deposit ${money(dep)} (${a.deposit_percent||0}%)`;
}
async function saveBooking(){
  // ensure end is computed from package if user set start after picking
  onPkgPick();
  const sv = val('b_start'), ev = val('b_end');
  if(!sv){ document.getElementById('merr').textContent='Upiši vrijeme početka.'; return; }
  if(!val('b_pkg')){ document.getElementById('merr').textContent='Odaberi paket (da se cijena i depozit izračunaju).'; return; }
  if(!ev || new Date(ev) <= new Date(sv)){
    document.getElementById('merr').textContent='Odaberi paket (kraj se računa sam) ili upiši kraj nakon početka.';
    return;
  }
  // upozori ako je brod već zauzet u tom terminu (admin ipak može nastaviti)
  try{
    const aid=+val('b_asset');
    const chk=await api('/api/availability/check?asset_id='+aid+'&start='+encodeURIComponent(new Date(sv).toISOString())+'&end='+encodeURIComponent(new Date(ev).toISOString())).catch(()=>null);
    if(chk && chk.available===false){
      if(!confirm('PAŽNJA: ovaj resurs je u tom terminu već zauzet. Svejedno upisati rezervaciju?')) return;
    }
  }catch(e){ /* ako provjera ne uspije, ne blokiraj */ }
  try{
    let custId = +val('b_cust') || 0;
    // create a new guest on the fly if no existing customer was picked
    if(!custId){
      const gname = val('b_gname').trim();
      if(!gname){ document.getElementById('merr').textContent='Odaberi gosta ili upiši ime novog gosta.'; return; }
      const nc = await api('/api/customers',{method:'POST',body:JSON.stringify({
        full_name:gname, phone:val('b_gphone'), email:val('b_gemail'), language:'en'})});
      custId = nc.id;
    }
    const pm = val('b_paymode');
    const dep = val('b_deposit');
    await api('/api/bookings',{method:'POST',body:JSON.stringify({
      customer_id:custId, asset_id:+val('b_asset'),
      package_id:+val('b_pkg')||null,
      passengers:+val('b_pax')||0,
      pickup_location:val('b_pickup'),
      deposit_amount: dep!=='' ? +dep : null,
      payment_status: pm==='on_boat' ? 'pay_on_boat' : 'unpaid',
      start_datetime:new Date(val('b_start')).toISOString(),
      end_datetime:new Date(val('b_end')).toISOString(),source:'admin'})});
    closeModal(); go('Bookings'); }
  catch(e){ document.getElementById('merr').textContent=e.message; }
}
function onPayModePick(){ /* reserved for future UI hints */ }
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
function val(id){ const el=document.getElementById(id); return el?el.value:''; }


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



async function mailboxModal(id){
  let m = {imap_port:993,smtp_port:465,use_ssl:true,active:true,
           imap_host:'mail.kljucevidubrovnik.com',smtp_host:'mail.kljucevidubrovnik.com'};
  if(id){ const all = await api('/api/mailboxes'); m = all.find(x=>x.id===id)||m; }
  openModal(`<h3>${id?'Edit':'Add'} email account</h3>
    <label>Email address (e.g. info@seagulldubrovnik.com)</label><input id="mb_addr" value="${m.address||''}">
    <label>Username (usually same as address)</label><input id="mb_user" value="${m.username||m.address||''}">
    <label>Password ${id?'(leave blank to keep current)':''}</label><input id="mb_pass" type="password" value="">
    <label>IMAP host</label><input id="mb_imap" value="${m.imap_host||''}">
    <label>SMTP host</label><input id="mb_smtp" value="${m.smtp_host||''}">
    <div style="display:flex;gap:8px">
      <div style="flex:1"><label>IMAP port</label><input id="mb_iport" type="number" value="${m.imap_port||993}"></div>
      <div style="flex:1"><label>SMTP port</label><input id="mb_sport" type="number" value="${m.smtp_port||465}"></div>
    </div>
    <label>Za koji tip posla? (podsjetnici/odgovori idu s ovog maila)</label>
    <select id="mb_type">
      <option value="" ${!m.handles_type?'selected':''}>Sve / nije bitno</option>
      <option value="boat" ${m.handles_type==='boat'?'selected':''}>Brodovi</option>
      <option value="jetski" ${m.handles_type==='jetski'?'selected':''}>Jet ski</option>
      <option value="transfer" ${m.handles_type==='transfer'?'selected':''}>Transferi</option>
    </select>
    <div class="err" id="merr"></div>
    <div style="display:flex;gap:8px;margin-top:14px">
    <button class="btn" onclick="saveMailbox(${id||0})">Save</button>
    <button class="btn btn-ghost" onclick="closeModal()">Cancel</button></div>`);
}
async function saveMailbox(id){
  const p = {address:val('mb_addr'),username:val('mb_user')||val('mb_addr'),
    password:val('mb_pass'),imap_host:val('mb_imap'),smtp_host:val('mb_smtp'),
    imap_port:+val('mb_iport'),smtp_port:+val('mb_sport'),use_ssl:true,active:true,
    handles_type:val('mb_type')};
  // on create, password required; on edit, blank means keep
  if(!id && !p.password){ document.getElementById('merr').textContent='Password is required'; return; }
  try{ await api(id?'/api/mailboxes/'+id:'/api/mailboxes',
    {method:id?'PATCH':'POST',body:JSON.stringify(p)});
    closeModal(); go('Mail Settings'); }
  catch(e){ document.getElementById('merr').textContent=e.message; }
}
async function delMailbox(id){ if(!confirm('Delete this email account?'))return;
  await api('/api/mailboxes/'+id,{method:'DELETE'}); go('Mail Settings'); }
async function testMailbox(id){
  try{ const r = await api('/api/mailboxes/'+id+'/test',{method:'POST'});
    alert(r.ok ? '✓ Connection successful' : '✗ Failed: '+r.message); }
  catch(e){ alert('Error: '+e.message); }
}



function payTag(ps){
  const map={unpaid:['Neplaćeno','#999'],awaiting_payment:['Čeka uplatu','var(--warn)'],
    deposit_paid:['Depozit plaćen','var(--good)'],refunded:['Vraćeno','var(--deep)']};
  const [label,color]=map[ps||'unpaid']||map.unpaid;
  return `<span style="font-size:11px;color:${color};font-weight:600">${label}</span>`;
}

async function sendConfirm(id){
  try{ const r=await api('/api/payments/send-confirmation/'+id,{method:'POST'});
    alert(r.sent?'Potvrda poslana gostu.':'Greška: '+(r.error||'nepoznato'));
  }catch(e){ alert(e.message); }
}
async function refundB(id){
  if(!confirm('Sigurno napraviti povrat depozita? Rezervacija će biti otkazana.'))return;
  try{ const r=await api('/api/payments/refund/'+id,{method:'POST'});
    alert('Povrat napravljen: '+(r.amount||'')+' EUR'); go('Bookings');
  }catch(e){ alert('Greška pri povratu: '+e.message); }
}


async function saveLeadTimes(){
  const body={jetski:+val('lt_jetski'),boat:+val('lt_boat'),transfer:+val('lt_transfer')};
  try{ await api('/api/settings/lead-times',{method:'PUT',body:JSON.stringify(body)});
    document.getElementById('lt_msg').textContent='Spremljeno ✓';
    setTimeout(()=>{const m=document.getElementById('lt_msg');if(m)m.textContent='';},2500);
  }catch(e){ alert('Greška: '+e.message); }
}

async function chargeDeposit(id){
  try{
    const r=await api('/api/payments/checkout/'+id,{method:'POST'});
    if(r.url){
      // otvori Stripe stranicu za plaćanje u novom tabu
      window.open(r.url,'_blank');
    } else if((r.error||'')==='no_deposit'){
      // depozit je 0 — ponudi unos pa pokušaj ponovno
      const v=prompt('Iznos depozita je 0. Upiši iznos depozita (EUR) koji je gost platio/treba platiti:');
      if(v && +v>0){ await editDeposit(id,+v,true); chargeDeposit(id); }
    } else {
      alert('Greška: '+(r.message||r.error||'nepoznato'));
    }
  }catch(e){ alert(e.message); }
}

async function editDeposit(id, current, silent){
  let v=current;
  if(!silent){
    const inp=prompt('Iznos depozita (EUR):', current||'');
    if(inp===null) return;
    v=+inp;
    if(!(v>0)){ alert('Upiši ispravan iznos.'); return; }
  }
  try{
    await api('/api/bookings/'+id,{method:'PATCH',body:JSON.stringify({deposit_amount:v})});
    if(!silent) go('Bookings');
  }catch(e){ alert(e.message); }
}

// auto-login if token cached
const cached = sessionStorage.getItem('tok');
if(cached){ TOKEN=cached; boot(); }

function openVoucher(id){
  // open the partner voucher PDF in a new tab (auth via token in query)
  const t = sessionStorage.getItem('tok') || '';
  window.open('/api/bookings/'+id+'/voucher?token='+encodeURIComponent(t), '_blank');
}

async function saveBusiness(){
  try{
    await api('/api/settings/business',{method:'PUT',body:JSON.stringify({
      brand_boat:val('set_brand_boat'),
      brand_jetski:val('set_brand_jetski'),
      brand_transfer:val('set_brand_transfer'),
      default_deposit_percent:+val('set_dep')||30})});
    const m=document.getElementById('biz_msg'); if(m) m.textContent='Spremljeno ✓';
  }catch(e){ alert(e.message); }
}
