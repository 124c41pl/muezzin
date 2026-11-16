"""The page the panel serves, as one string.

It lives here rather than in web.py because web.py is the part that answers
questions - the JSON API, the writes to the profile, the guards around both -
and this is the part that only has to look right. They do not change for the
same reasons, and one 2,500-line file holding both made each of them harder to
find things in.

There is still no build step and nothing to fetch at run time: the page remains
a single document with no external requests, and web.py imports this one name
and hands it over. What is here is exactly what a browser gets, which is why the
tests read the served HTML for the ids and rules they depend on instead of
trusting a second copy of it.
"""

PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>muezzin</title>
<style>
 /* Night green and gold, over a khatam (eight-point star) lattice drawn inline as
    an SVG: a LAN panel has no internet to fetch a tile from, and a prayer page
    that only works online is a bad prayer page. */
 :root {
  --bg:#0b1411; --card:#101d18; --card2:#0d1815; --line:#23453a; --fg:#ece7d9;
  --dim:#94a89c; --gold:#d9ab4e; --gold2:#f0cf8c; --turq:#5cb9a8;
  --mourn:#9fb2c0; --bad:#e8897a;
 }
 * { box-sizing:border-box }
 body { margin:0; color:var(--fg); font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;
  background:radial-gradient(1100px 560px at 50% -10%, rgba(31,74,58,.55), rgba(11,20,17,0) 70%),
   url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='64' height='64'%3E%3Cg fill='none' stroke='%231d3a30' stroke-width='1'%3E%3Cpath d='M32 4 60 32 32 60 4 32Z'/%3E%3Cpath d='M12 12h40v40H12z'/%3E%3Cpath d='M0 0 12 12M64 0 52 12M0 64 12 52M64 64 52 52'/%3E%3C/g%3E%3C/svg%3E");
  background-attachment:fixed; background-size:auto, 64px 64px;
   /* The longhand colour, not the shorthand: a gradient that fades to
      transparent needs something solid under it, or the page turns white
      below the fold and the dark tile starts looking like a mistake. */
   background-color:var(--bg) }
 header { padding:20px 22px 14px; border-bottom:1px solid var(--line);
  display:flex; flex-wrap:wrap; gap:14px; align-items:baseline;
  background:linear-gradient(180deg, rgba(20,48,37,.75), rgba(11,20,17,0)) }
 .star { width:34px; height:34px; stroke:var(--gold); stroke-width:1.3; fill:none; align-self:center }
 h1 { font-size:21px; margin:0; letter-spacing:.06em; color:var(--gold2) }
 .ar { font-family:"Segoe UI","Noto Naskh Arabic",Tahoma,serif; font-size:15px; color:var(--dim) }
 h2 { font-size:12.5px; text-transform:uppercase; letter-spacing:.09em; color:var(--dim); margin:0 }
 .meta { color:var(--dim); font-size:13.5px; flex:1 1 320px }
 #hijri { color:var(--gold); font-size:14px }
 #next { padding:12px 22px; border-bottom:1px solid var(--line); color:var(--dim);
  font-size:14px; background:rgba(13,24,21,.75) }
 #next b { color:var(--gold2); font-weight:600; font-size:16px }
 main { padding:22px; display:grid; gap:18px; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); max-width:1200px }
 section { background:rgba(16,29,24,.88); border:1px solid var(--line); border-radius:12px; padding:16px }
 table { width:100%; border-collapse:collapse; font-size:14px }
 th { text-align:left; color:var(--dim); font-weight:500; font-size:12.5px; padding:4px 8px 4px 0 }
 td { padding:5px 8px 5px 0; border-top:1px solid var(--line) }
 .day { border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin:0 0 14px;
  background:rgba(13,24,21,.6) }
 /* today gets the arch: two rounded top corners, which is already the shape of a
    mihrab and of a dome. No pictures, no figures - the geometry does the work. */
 .day.today { border-color:var(--gold2); border-top-left-radius:60px 44px;
  border-top-right-radius:60px 44px; background:rgba(20,44,34,.75) }
 .dayhead { display:flex; flex-wrap:wrap; gap:8px; align-items:baseline; margin-bottom:8px }
 .day .pl { color:var(--dim) }
 .day .ar { color:var(--dim); text-align:right }
 .day .t { text-align:right; font-variant-numeric:tabular-nums }
 .hij { color:var(--gold); font-size:13px }
 .mark { font-size:12px; border:1px solid var(--line); border-radius:20px; padding:1px 9px }
 .mark.mourn { color:var(--mourn); border-color:#39566b; background:rgba(60,90,115,.18) }
 .mark.celebrate { color:var(--gold2); border-color:#5c4a22; background:rgba(217,171,78,.14) }
 .mark.plain { color:var(--turq) }
  /* the Arabic name of the day, inside its own pill, in the pill's colour */
  .mark .ar { color:inherit; font-size:13px }
 .now td { color:var(--gold2) }
 .now .pl { color:var(--gold) }
 button:disabled { opacity:.45; cursor:default; border-color:var(--line) }
 button { background:#163026; color:var(--fg); border:1px solid var(--line);
  border-radius:6px; padding:5px 10px; cursor:pointer; font:inherit }
 button:hover { border-color:var(--gold) }
 .switch { width:38px; height:20px; border-radius:10px; background:#2b3f38; position:relative;
  cursor:pointer; border:0; padding:0 }
 .switch:after { content:""; position:absolute; top:3px; left:3px; width:14px; height:14px;
  border-radius:50%; background:var(--fg); transition:left .15s }
 .switch[aria-checked=true] { background:var(--gold) }
 .switch[aria-checked=true]:after { left:21px; background:#0b1411 }
 textarea { width:100%; min-height:340px; background:#08110e; color:#dbe6df;
  border:1px solid var(--line); border-radius:8px; padding:12px;
  font:13px/1.45 ui-monospace,Consolas,monospace; tab-size:2 }
 select, input[type=file], input[type=number], input[type=text] { background:#0d1815; color:var(--fg); border:1px solid var(--line);
  border-radius:6px; padding:5px 8px; font:inherit; max-width:100% }
 select:disabled, input:disabled { opacity:.45 }
 .row select { min-width:190px }
 /* The only slider on this page is a place inside a recording. It is gold like
    everything else you can press. Nothing here moves a level: the volume of a
    computer belongs to the person sitting in front of it. */
 input[type=range] { accent-color:var(--gold); width:200px; max-width:55vw; padding:0 }
 .members { color:var(--dim); font-size:13px }
 .known { color:var(--turq) }
 .unknown { color:var(--mourn) }
 .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:12px }
 #msg { white-space:pre-wrap; font-size:13.5px; margin-top:10px; min-height:1.2em }
 #msg.err { color:var(--bad) } #msg.ok { color:var(--turq) }
 .tag { font-size:12px; color:var(--dim); border:1px solid var(--line); border-radius:20px; padding:2px 9px }
 .wide { grid-column:1/-1 }
 a { color:var(--turq) }
 footer { padding:8px 22px 30px; max-width:1200px }
 #credit { color:var(--gold); font-size:13.5px }
 .fine { color:var(--dim); font-size:12.5px; margin-top:6px }
 .notice { color:var(--gold); background:#0d1815; border:1px solid var(--line);
  border-left:3px solid var(--gold); border-radius:8px; padding:9px 13px;
  margin:10px 0 0; font-size:13.5px; max-width:1200px }
 .fine.warn { color:var(--bad) }
 /* How a position gets shown: a diagram of bearings drawn here from the numbers,
    which works with the network unplugged, and squares of somebody else's map, which
    the daemon fetches and credits where they appear - on by default, and stopped by
    map_tiles: off. The dot is where the numbers are, not a picture of anything, and
    clicking the map moves it without writing anything down.
    A view is a fixed number of squares across and down, laid out as a grid whose cell
    size is one custom property, so the squares cover the box edge to edge. They used to
    be floats, which wrapped to whatever width the window happened to give them: a
    complete set of squares came out ragged with a hole in the corner, and the hole looked
    exactly like a square that had failed to arrive. */
 .mapbox { --sq:min(256px,29vw); position:relative; display:inline-grid; cursor:crosshair;
  margin-top:8px; border:1px solid var(--line) }
 /* The Outputs table is the one with a rename box you can type into and five columns
    of words in it. Left to itself the table grows to whatever its words need, the
    card around it does not grow with it, and the last column - the test button - ends
    up outside the edge of the card. A fixed layout with stated widths keeps every
    column under the header it belongs to. The widths follow what each column holds,
    and the last one is the width of a button: that is the column that must never be
    the one that falls off the edge. A word too long for its column is broken where it
    has to be, not at the first opportunity. */
 #outputstbl { table-layout:fixed }
 #outputstbl th:nth-child(1) { width:21% }
 #outputstbl th:nth-child(2) { width:15% }
 #outputstbl th:nth-child(3) { width:17% }
 #outputstbl th:nth-child(4) { width:7% }
 #outputstbl th:nth-child(5) { width:21% }
 #outputstbl th:nth-child(6) { width:19%; text-align:right }
 #outputstbl td { overflow-wrap:break-word }
 #outputstbl td:last-child { white-space:nowrap; text-align:right }
 #outputstbl input[type=range] { width:80px; vertical-align:middle }
 /* The same shape as the Outputs table, for the same reason: a recording is called
    whatever the person who put it in the folder called it, and a table that sizes
    itself lets a long name push the buttons clean out of the card. */
 #libtbl { table-layout:fixed }
 #libtbl th:nth-child(1) { width:24% }
 #libtbl th:nth-child(2) { width:9% }
 #libtbl th:nth-child(3) { width:21% }
 #libtbl th:nth-child(4) { width:11% }
 #libtbl th:nth-child(5) { width:35% }
 #libtbl td { overflow-wrap:break-word }
 #libtbl select { max-width:100% }
 /* The name is the box you type in, so it is as wide as the column it sits in rather
    than a fixed number of characters: a speaker called whole-house lost its last
    letters in a 12ch box, and a name you cannot read in full is a name you cannot
    rename without guessing. */
 .rename { width:100%; min-width:0; box-sizing:border-box; padding:3px 6px }
 .mapbox img { width:100%; height:100%; display:block }
 .spot { position:absolute; width:9px; height:9px; margin:-4px 0 0 -4px; border-radius:50%;
  background:var(--gold); box-shadow:0 0 0 3px rgba(11,20,17,.8) }
 .cities { display:inline-block; vertical-align:top; margin-left:14px }
 .cities div { margin-bottom:5px }
 #dial text { fill:var(--dim); font-size:9.5px }
 #dial line, #dial circle { stroke-width:1 }
</style></head><body>
<header>
 <svg class="star" viewBox="0 0 32 32" aria-hidden="true">
  <path d="M16 2 22 10 30 16 22 22 16 30 10 22 2 16 10 10Z"/><path d="M7 7h18v18H7z"/></svg>
 <h1>muezzin</h1>
 <span class="ar">أَوقات الصلاة</span>
 <div id="hijri"></div>
 <div class="meta" id="top">loading&hellip;</div>
 <button id="refresh">refresh</button>
</header>
<div id="next"></div>
<div id="notices"></div>
<main>
 <section><h2>Timetable</h2><div id="days"></div></section>
 <section><h2>Next events</h2><table><thead><tr><th>when</th><th>event</th><th>speakers</th><th>media</th></tr></thead><tbody id="upcoming"></tbody></table></section>
 <section class="wide"><h2>Outputs</h2><table id="outputstbl"><thead><tr><th>name</th><th>kind</th><th>target</th><th>on</th><th>level</th><th></th></tr></thead><tbody id="outputs"></tbody></table>
  <div class="fine">A speaker muezzin has to find on the network gets the recording a few seconds before the time it belongs to, so the first note is already in the air when that time arrives; the number in brackets is that head start. A profile sets it per speaker with lead_seconds, and 0 means exactly on the minute. Everywhere else on this page the times shown are the computed ones.</div>
  <div class="fine">The level is what muezzin asks a speaker for the moment it starts playing, so a test comes out at the same loudness as an adhan instead of at whatever the room happened to be left at. It is muezzin's to ask only of a speaker it casts to: the level of the computer running this program, or of a box on the LAN, belongs to whoever is sitting at that machine, and this page never touches it. A speaker with nothing written in the profile is asked for 50%.</div>
  <div class="row"><select id="media"></select><span class="tag" id="mediaurl"></span></div>
 </section>
 <section class="wide"><h2>Where</h2>
  <div class="row"><label>latitude <input id="lat" type="number" step="any" size="10"></label>
   <label>longitude <input id="lon" type="number" step="any" size="10"></label>
   <label>time zone <input id="zone" type="text" size="18"></label>
   <button id="check">check these numbers</button><button id="writewhere">write these</button></div>
  <div id="where"></div>
  <div class="row"><input id="place" type="text" size="26" placeholder="the street, and the number on it">
   <label>postal code <input id="zip" type="text" size="8"></label>
   <button id="findit">find it</button></div>
  <div id="found"></div>
  <div class="fine">Checking numbers happens on this machine, against the town centres
   muezzin carries, and asks nobody anything. Finding a place by its words sends what you
   typed to <span id="geocoder"></span> - once, and only because you pressed find-it; it is
   not kept, not written to the profile, not put in the log, and the times themselves never
   ask anyone. The map below is the one thing that asks for something on its own: its
   squares come from tile.openstreetmap.org, fetched by the daemon with this program's name
   on the request and credited where they show, never by your browser. Click the map to move
   the mark and the two boxes above follow it; write-it is what saves them. To keep every
   request inside this house, put <code>map_tiles: off</code> in the profile. The postal
   code answers better than the name of a town does, because the map files a street under
   the place it physically sits in rather than under the town name people put in a posting
   address: the street in one box and the code in the other is the ask that gets through,
   and the town is the word to leave out. A code on its own finds the whole code area, and
   one code can exist in two countries, so read the whole label before using anything. When
   the answer is a street rather than a door, press look there and then click the door you
   live at: the click is the house number, and a mark a kilometre off moves a prayer time
   by under a second.</div>
  <div id="map"></div>
 </section>
 <section><h2>Method</h2>
  <div class="row"><select id="preset"></select><select id="asr"></select><button id="applymethod">apply method</button></div>
  <div class="fine" id="overrides"></div>
  <div class="fine">That list is every method muezzin ships with, in two groups by where
   the night is taken to end. The Sunni methods end it at sunrise; the Ja'fari ones end
   it at Fajr, which is why the second group's midnight sits earlier in the evening. The
   page is not arguing about it, it is only telling you which numbers moved. If the
   figures you follow are not in the list, write them under <code>method:</code> in the
   profile - they stay put when you change the name here.</div>
  <div class="row"><span class="tag">Hijri date</span><button id="hijminus">&minus;1</button><span id="hijridays">0</span><button id="hijplus">+1</button></div>
  <div class="fine">Arithmetic cannot see the moon, so this is where you tell it what you saw.</div>
 </section>
 <section class="wide"><h2>Sound</h2>
  <table><thead><tr><th>time</th><th></th><th>every day</th><th>Friday</th></tr></thead><tbody id="sound"></tbody></table>
  <div class="row"><button id="applysound">apply these clips</button><span class="tag" id="soundsay">nothing changed</span></div>
  <div class="row"><input type="file" id="file" accept=".mp3,.m4a,.wav,.ogg,.oga,.flac,.aac,.opus,audio/*"><button id="upload">add this recording</button><span class="tag" id="uploadsay"></span></div>
  <div class="row"><select id="preview"></select><button id="hear">play it here</button><button id="hush" disabled>pause</button><button id="halt" disabled>stop</button><input id="seek" type="range" min="0" max="0" step="1" value="0" disabled aria-label="how far into it you are"><span class="tag" id="hearsay">nothing playing</span></div>
  <div class="fine">That plays in this browser, out of the computer this page is open on, at the level
   that computer is already set to. There is no volume control here on purpose: the level on a computer
   belongs to whoever is sitting at it. The bar is not a level either - it is a place inside the
   recording, and dragging it asks the daemon for the bytes from there, which is how you hear the middle
   of a recitation without sitting through the start of it. Nothing on the network hears it - the
   <b>test</b> button in the Outputs table is the one that sends a recording to a speaker, and the two are easy to tell apart when
   you are choosing what a prayer should sound like.</div>
  <div class="fine">A clip is picked from what is already in <code>media_dir</code>; the button above
   puts a new recording there. Nothing overwrites a recording that is playing, so two recordings of
   the same adhans need two names. These boxes choose what a prayer starts with; the Recordings card
   below adds a recording to the end of a prayer's list, which is where a dua after the adhan goes.</div>
 </section>
 <section class="wide"><h2>Recordings in the folder</h2>
  <div class="row"><span class="tag" id="libdir"></span></div>
  <table id="libtbl"><thead><tr><th>name</th><th>size</th><th>played by</th><th>in the drawing</th><th>put it on an event</th></tr></thead><tbody id="library"></tbody></table>
  <div class="fine">Every row is a file in <code>media_dir</code>, and that folder is the whole library:
   there is no second list of recordings to keep in step with it, so a recording that is not in this table
   is not in the profile either. The clip boxes in the Sound card choose which recording a prayer
   <i>starts</i> with; <b>add to</b> here puts one at the <i>end</i> of that event's playlist, which is how
   a prayer plays the adhan and then a dua. The <b>played by</b> column is also the reason a recording
   refuses to be deleted: an event still naming it would fire at its time into a file that is no longer
   there, which is the one failure this program exists to avoid.</div>
  <div class="fine">The switch in the <b>in the drawing</b> column is only about events that say
   <code>random: N</code>: off keeps the recording out of that pick and writes its name under
   <code>library: exclude:</code>, while every playlist that names it by hand goes on playing it. A name in
   the hold list whose file has gone still shows up here, with the absence said, so that it can be let go.
   Deleting is the one thing on this page with no undo, so that button asks twice before it does anything.</div>
 </section>
 <section class="wide"><h2>Speakers on the network</h2>
  <div class="row"><button id="scan">look again</button><span class="tag" id="scansay">not looked yet</span></div>
  <table><thead><tr><th>name</th><th>what</th><th>where</th><th>members</th><th></th></tr></thead><tbody id="found"></tbody></table>
  <div class="fine">A group's members are read back from the speakers themselves: the group record
   out on the network only names the one speaker in charge of it. A speaker that will not answer
   leaves the members unknown, which is not the same as nobody being in it.</div>
 </section>
 <section class="wide"><h2>Profile <span class="tag" id="cfgpath"></span></h2>
  <textarea id="yaml" spellcheck="false"></textarea>
  <div class="row"><button id="save">save &amp; reload</button><button id="reload">reload from disk</button>
   <span class="tag">saved edits restart nothing: the daemon picks up new speakers and times on the spot</span></div>
  <div id="msg"></div>
 </section>
</main>
<footer>
 <div id="credit"></div>
 <div class="fine">The Hijri date is tabular arithmetic, so it can sit a day either side of a
  moon sighting; <code>hijri_offset</code> in your profile lines it up with the calendar you
  follow. The day markers are decoration on the calendar, not a ruling about when anything is.</div>
</footer>
<script>
let st=null;
const $=s=>document.querySelector(s);
// Speaker names come from the network, so every one of them is escaped on its way
// into the page - apostrophes included, because "Sara's Nest" is a perfectly
// ordinary thing to call a speaker and a quote is exactly what closes an attribute.
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Bilingual, the way the prayer itself is: English labels, Arabic names. These two
// tables are fixed text in the page, not something downloaded and not translated
// at runtime.
const NAME={fajr:'Fajr',sunrise:'Sunrise',dhuhr:'Dhuhr',asr:'Asr',maghrib:'Maghrib',
 isha:'Isha',midnight:'Midnight',true_night:'True night',shurf:"Shaf'",sunset:'Sunset'};
const AR={fajr:'الفجر',sunrise:'الشروق',dhuhr:'الظهر',asr:'العصر',maghrib:'المغرب',
 isha:'العشاء',midnight:'نصف الليل',true_night:'نصف الليل الشرعي',shurf:'الشفع',sunset:'الغروب'};
// The table reads as a day, not as a dictionary: sunset sits immediately before
// maghrib because on a Ja'fari profile they are a few minutes apart and the whole
// point is to see the difference.
const ORDER=['fajr','sunrise','dhuhr','asr','sunset','maghrib','isha','midnight',
 'true_night','shurf'];
async function api(path,body){
 const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):null});
 const j=await r.json().catch(()=>({error:'bad response'}));
 if(!r.ok) throw new Error(j.error||('HTTP '+r.status));
 return j;
}
function say(t,kind){ const m=$('#msg'); m.textContent=t; m.className=kind||''; }
// The YAML box is the one place where you might be mid-edit, and a 60 second
// refresh must never throw your draft away - so the guard is "dirty", not
// "has focus": clicking test, or the phone keyboard closing, keeps your text.
function syncYaml(){
 const ta=$('#yaml');
 const path=st.config_path||'(no file)';
 if(ta.dataset.dirty==='1'){ $('#cfgpath').textContent=path+' · unsaved edits'; return; }
 ta.value=st.config_text;
 $('#cfgpath').textContent=path;
}
function render(){
 const nx=st.upcoming[0]||null;
 $('#top').textContent=`${st.method.label} · ${st.location.latitude.toFixed(2)}, ${st.location.longitude.toFixed(2)} · ${st.location.timezone} · asr ${st.method.asr} · ${st.method.midnight} midnight · ${st.now}`+(st.read_only?' · read-only':'');
 $('#hijri').innerHTML=`${esc(st.today.hijri)} AH <span class="ar">${esc(st.today.hijri_ar)}</span>`
  +(st.hijri_offset?` <span class="tag">hijri_offset ${st.hijri_offset>0?'+':''}${st.hijri_offset}</span>`:'');
 $('#next').innerHTML=nx
  ? `<b>${esc(nx.when)}</b> · ${esc(NAME[nx.at]||nx.at)} <span class="ar">${esc(AR[nx.at]||'')}</span> · ${esc(nx.name)} to ${esc(nx.targets.join(', ')||'(no speaker enabled)')}`
  : 'nothing scheduled in the next two days';
 // A brand new install sees this page long before it sees a log file, so the two
 // things that make a quiet muezzin are said here as well as in the daemon's log.
 $('#notices').innerHTML=(st.notices||[]).map(n=>`<div class="notice">${esc(n)}</div>`).join('');
 $('#days').innerHTML=st.days.map((d,i)=>
  `<div class="day${i===0?' today':''}"><div class="dayhead"><h2>${esc(d.weekday)} ${esc(d.date)}</h2>`
  +` <span class="hij">${esc(d.hijri)}</span> <span class="ar">${esc(d.hijri_ar)}</span>`
  +(d.marks||[]).map(m=>` <span class="mark ${esc(m.kind)}">${esc(m.name)}${m.ar?` <span class="ar">${esc(m.ar)}</span>`:''}</span>`).join('')
  +`</div><table>${ORDER.filter(k=>k in d.times).map(k=>[k,d.times[k]]).map(([k,v])=>
    `<tr class="${nx&&nx.at===k&&nx.date===d.date?'now':''}"><td class="pl">${esc(NAME[k]||k)}</td>`
    +`<td class="ar">${esc(AR[k]||'')}</td><td class="t">${esc(v)}</td></tr>`).join('')}</table></div>`).join('');
 $('#upcoming').innerHTML=st.upcoming.map(e=>`<tr><td>${esc(e.when)}</td><td>${esc(e.name)}<span class="tag">${esc(e.at)}${e.offset_min?` ${e.offset_min>0?'+':''}${e.offset_min}m`:''}</span></td><td>${esc(e.targets.join(', '))||'(none enabled)'}</td><td>${esc(e.media.concat(e.random?[e.random+' at random']:[]).join(' + '))}</td></tr>`).join('')||'<tr><td colspan=4>nothing scheduled in the next two days</td></tr>';
 // A test is a recording that is about to come out of a real speaker, so the row that
 // sent one grows a stop button while it is going: 40 seconds into a recitation
 // nobody wanted should not have to be listened to to the end, and a speaker left
 // holding a stream that will not end should be let go. The daemon takes one test at a
 // time, which is why one name is enough to remember.
 let testing=null;
 $('#outputs').innerHTML=st.outputs.map(o=>`<tr><td><input type="text" class="rename" data-was="${esc(o.name)}" value="${esc(o.name)}" aria-label="what this speaker is called by"></td><td>${esc(o.lead?o.kind+' ('+o.lead+'s early)':o.kind)}</td><td>${esc(o.target||o.host||'-')}</td><td><button class="switch" data-name="${esc(o.name)}" aria-checked="${o.enabled}"></button></td><td>${o.takes_volume?`<input type="range" min="0" max="1" step="0.05" data-level="${esc(o.name)}" value="${o.volume==null?0.5:o.volume}" aria-label="how loud to ask ${esc(o.name)} for"> <span class="tag">${o.volume==null?'not set':Math.round(o.volume*100)+'%'}</span>`:'<span class="unknown">not ours to ask</span>'}</td><td><button data-test="${esc(o.name)}">test</button><button data-stop="${esc(o.name)}"${o.name===testing?'':' hidden'}>stop</button></td></tr>`).join('');
 // A slider for a level exists only where the daemon said it may: the state's takes_volume
 // comes from the backend class, so a computer - the one running this page, or a box on the
 // LAN - has no level to move, only words saying whose it is.
 document.querySelectorAll('[data-level]').forEach(s=>s.onchange=()=>{ const out=s.dataset.level,
  level=Number(s.value), pct=Math.round(level*100); let vol=null;
  s.closest('td').querySelector('.tag').textContent=pct+'%';
  act(async()=>{ vol=await api('/api/output/volume',{name:out,volume:level}); },
   ()=>say(out+' will come out at '+pct+'% of its own scale, a test included','ok')); });
 // Only an output's switch carries data-name. A recording row uses data-hold for the
 // same look, because "let the random drawing pick this" is a different ask and needs
 // its own handler - one selector, one meaning.
 document.querySelectorAll('.switch[data-name]').forEach(b=>b.onclick=()=>act(()=>api('/api/output',{name:b.dataset.name,enabled:b.getAttribute('aria-checked')!=='true'})));
 document.querySelectorAll('[data-test]').forEach(b=>b.onclick=()=>{ const out=b.dataset.test;
  act(async()=>{ testing=out; b.nextElementSibling.hidden=false;
   // Whatever becomes of the request, this row has nothing to stop afterwards: a test
   // that failed part way is as finished as one that played all the way through.
   try{ return await api('/api/test',{output:out,media:$('#media').value?[$('#media').value]:[]}); }
   finally{ testing=null; } }); });
 // The ask goes to the output rather than to whatever is busy playing, because the
 // output is the thing making the sound. Nothing playing is not an error: it is the
 // honest answer to what was asked, and the schedule is untouched either way.
 document.querySelectorAll('[data-stop]').forEach(b=>b.onclick=()=>{ const out=b.dataset.stop; let sp=null;
  act(async()=>{ sp=await api('/api/test/stop',{output:out}); },
   ()=>say(sp.stopped.length?('asked '+out+' to stop'):out+' was not playing anything of ours','ok')); });
 // The name is the box you type in, not a label: events point at speakers by that word,
 // so a rename rewrites the events too and says which ones moved. Names are flattened to
 // one safe word, and the reply is the word that actually got written.
 document.querySelectorAll('.rename').forEach(i=>i.onchange=()=>{ const was=i.dataset.was,
  to=i.value.trim(); if(!to||to===was){ load(); return; } let rn=null;
  act(async()=>{ rn=await api('/api/output/rename',{from:was,to:to}); },
   ()=>say('now called '+rn.renamed+(rn.events_rewritten.length?', and '+rn.events_rewritten.join(', ')+' asks for it by the new name':', and no event named it yet'),'ok')); });
 const pick=$('#media'), want=pick.value;
 pick.innerHTML=st.media_files.map(f=>`<option>${esc(f)}</option>`).join('')||'<option value="">(no audio in media_dir)</option>';
 if(want&&[...pick.options].some(o=>o.value===want)) pick.value=want;
 const pv=$('#preview'), pvwant=pv.value;
 pv.innerHTML=st.media_files.map(f=>`<option>${esc(f)}</option>`).join('')||'<option value="">(no audio in media_dir)</option>';
 if(pvwant&&[...pv.options].some(o=>o.value===pvwant)) pv.value=pvwant;
 $('#mediaurl').textContent=st.media_url?('speakers fetch audio from '+st.media_url):'no media server needed by this profile';
  // A credit has to name a person, because a person is who answers questions about
  // the code. Say who you are with `attribution:` in the profile.
 $('#credit').innerHTML=`muezzin ${esc(st.version||'')} · MIT · `
  +(st.attribution?`written by ${esc(st.attribution)}, with an AI assistant`
                  :'written by whoever set this up, with an AI assistant');
 renderMethod();renderSound();renderLibrary();renderFound();renderWhere();
 syncYaml();
 $('#save').disabled=$('#reload').disabled=st.read_only;
 document.querySelectorAll('.switch,[data-test],[data-stop],.rename,[data-level],[data-hold],[data-put],[data-put-go],[data-rm]').forEach(b=>b.disabled=st.read_only);
 // Checking numbers and finding a place stay live on a read-only panel: looking
 // changes nothing. Only the buttons that write a line into the profile go dark.
 ['#preset','#asr','#applymethod','#hijminus','#hijplus','#applysound','#upload','#file','#writewhere'].forEach(s=>{ $(s).disabled=st.read_only; });
}
// ---- the three editors ----------------------------------------------------
//
// All of them write through the daemon, which validates the result before the
// file changes, so the page does not need to know what a legal profile is: it
// needs to know what it last showed you, and to send only what differs.
let note=[], SC=null, sent=0, up={};
function renderMethod(){
 const cur=st.method.preset||'', p=$('#preset');
 // The two groups are decided by where the night ends, which is arithmetic in the
 // preset, not by a label somebody wrote: so the grouping cannot drift out of step with
 // the numbers, and the first group is named for what it is rather than by what the
 // second one is not.
 const groups=[["Sunni (night ends at sunrise)",[]],["Ja'fari (night ends at Fajr)",[]]];
 (st.presets||[]).forEach(x=>groups[x.jafari?1:0][1].push(x));
 p.innerHTML=(cur?'':'<option value="" selected>(angles written by hand)</option>')
  +groups.map(g=>`<optgroup label="${esc(g[0])}">${g[1].map(x=>
    `<option value="${esc(x.name)}"${x.name===cur?' selected':''}>${esc(x.label)}</option>`).join('')}</optgroup>`).join('');
 $('#asr').innerHTML=['standard','hanafi'].map(v=>
  `<option value="${v}"${v===st.method.asr?' selected':''}>${v==='hanafi'?'asr: Hanafi (later)':'asr: standard'}</option>`).join('');
 const extra=st.overridden||[];
 $('#overrides').textContent=(cur?'in use: '+st.method.label:'no preset in the file: every angle is written by hand')
  +(extra.length?' · your own numbers still in force: '+extra.join(', '):'');
 $('#hijridays').textContent=(st.hijri_offset>0?'+':'')+st.hijri_offset;
}
function clipFor(at,friday){
 const rows=(st.events||[]).filter(e=>e.at===at&&!!(e.days&&e.days.length)===friday);
 return rows[0]||null;
}
function clipSelect(at,friday){
 const ev=clipFor(at,friday), cur=ev&&ev.media&&ev.media.length?ev.media[0]:'';
 const files=(st.media_files||[]).slice();
 if(cur&&files.indexOf(cur)<0) files.unshift(cur);
 return `<select data-at="${at}" data-friday="${friday?1:0}">`
  +[''].concat(files).map(f=>`<option value="${esc(f)}"${f===cur?' selected':''}>${esc(f||'(no clip)')}</option>`).join('')
  +`</select>`+((ev&&ev.media&&ev.media.length>1)?` <span class="tag">${ev.media.length} clips</span>`:'')
  +((ev&&ev.offset_min)?` <span class="tag">${ev.offset_min>0?'+':''}${ev.offset_min}m</span>`:'');
}
function renderSound(){
 const box=$('#sound');
 if(box.dataset.dirty==='1'){ $('#soundsay').textContent='your picks are waiting for apply'; return; }
 const times=(st.days&&st.days[0]&&st.days[0].times)||{};
 box.innerHTML=ORDER.filter(k=>k in times).map(k=>
  `<tr><td>${esc(NAME[k]||k)}</td><td class="ar">${esc(AR[k]||'')}</td>`
  +`<td>${clipSelect(k,false)}</td><td>${clipSelect(k,true)}</td></tr>`).join('')
  ||'<tr><td colspan=4>no times to put clips on</td></tr>';
 document.querySelectorAll('[data-at]').forEach(s=>s.onchange=()=>{
  box.dataset.dirty='1'; $('#soundsay').textContent='your picks are waiting for apply';
  if(st.read_only) s.disabled=true;
 });
 $('#soundsay').textContent='nothing changed';
}
function renderLibrary(){
 // The folder is the library, so this is a listing of what is on the disk rather than
 // a list of choices: each row says how big the recording is, which events hold its
 // name, and whether the random drawing may pick it. The names are what matters, not
 // the paths - the daemon only ever reads one level deep in media_dir - so a row is
 // addressed by its name and the profile is written by that name too. Sizes are
 // rounded up, because a recording that reads 0 KB is a recording nobody trusts.
 const box=$('#library');
 const lib=st.media_library||[];
 const size=b=>b==null?'?':b>=1048576?(b/1048576).toFixed(1)+' MB':Math.max(1,Math.round(b/1024))+' KB';
 const rows=lib.map(f=>{
  const who=f.named_by.length?f.named_by.map(esc).join(', '):'<span class="unknown">nothing plays it</span>';
  const on=`<button class="switch" data-hold="${esc(f.name)}" aria-checked="${f.excluded?'false':'true'}"`
   +` aria-label="let the drawing pick ${esc(f.name)}"></button>`;
  // A held-back name whose file has gone has nothing to play, add or delete: there is
  // only the hold to let go, and the switch beside it is how.
  const put=f.missing?'<span class="unknown">the file is gone from the folder</span>'
   :`<select data-put="${esc(f.name)}">${(st.events||[]).map(e=>`<option>${esc(e.name)}</option>`).join('')||'<option value="">(no events yet)</option>'}</select>`
   +`<button data-put-go="${esc(f.name)}">add to</button><button data-rm="${esc(f.name)}">delete</button>`;
  return `<tr><td>${esc(f.name)}</td><td>${size(f.bytes)}</td><td>${who}</td><td>${on}</td><td>${put}</td></tr>`;
 }).join('');
 box.innerHTML=rows||`<tr><td colspan=5>nothing in ${esc(st.media_dir)} yet</td></tr>`;
 $('#libdir').textContent=lib.length+(lib.length===1?' recording in ':' recordings in ')+st.media_dir;
 // aria-checked is "in the drawing", so a switch that is on and gets pressed is being
 // switched off: the ask is to hold it back.
 document.querySelectorAll('[data-hold]').forEach(b=>b.onclick=()=>{ const n=b.dataset.hold,
  hold=b.getAttribute('aria-checked')==='true'; let j=null;
  act(async()=>{ j=await api('/api/library/hold',{name:n,excluded:hold}); },
   ()=>say(j.unchanged?(hold?n+' was already held back':n+' was already in the drawing'):
    (hold?'the drawing will skip '+n:'the drawing can pick '+n+' again'),'ok')); });
 document.querySelectorAll('[data-put-go]').forEach(b=>b.onclick=()=>{ const n=b.dataset.putGo,
  ev=b.closest('td').querySelector('[data-put]').value; let j=null;
  act(async()=>{ j=await api('/api/library/insert',{name:n,event:ev}); },
   ()=>say(j.event+' now plays '+j.playlist.join(' then '),'ok')); });
 // Deletion has no undo, so the first press only changes the question, and the answer
 // is not stored anywhere: the next poll redraws the row and the button is a plain
 // delete again. A recording an event names is refused by the daemon, not here, so
 // the reason that comes back names the event that is in the way.
 document.querySelectorAll('[data-rm]').forEach(b=>b.onclick=()=>{ const n=b.dataset.rm;
  if(b.dataset.sure!=='1'){ b.dataset.sure='1'; b.textContent='sure? gone for good'; return; }
  act(()=>api('/api/library/delete',{name:n}),()=>say(n+' is gone from the folder','ok')); });
}
function renderFound(){
 const box=$('#found');
 const silent=(SC&&SC.found&&SC.found.silent)||[];
 $('#scansay').textContent=SC?('looked at '+SC.seen_at+(silent.length?' · '+silent.length+' would not say whose groups it is in':''))
  :'not looked yet';
 if(!SC){ box.innerHTML='<tr><td colspan=5>press look again to see what is on the LAN</td></tr>'; return; }
 const inuse=SC.in_profile||{};
 const act2=(target,name)=>inuse[target]
  ? `<span class="known">in use as ${esc(inuse[target])}</span> <button data-drop="${esc(inuse[target])}">stop using</button>`
  : `<button data-add="${esc(target)}">use</button>`;
 const rows=[];
 (SC.found.groups||[]).forEach(g=>rows.push(
  `<tr><td>${esc(g.name)}</td><td>group</td><td class="members">${esc(g.address||'')}:${esc(g.port||'')}</td>`
  +`<td class="members">${g.membership_known?((g.members||[]).map(esc).join(', ')||'<span class="unknown">nobody claimed it</span>'):'<span class="unknown">unknown: they did not answer</span>'}</td>`
  +`<td>${act2(g.name,'')}</td></tr>`));
 (SC.found.speakers||[]).forEach(d=>rows.push(
  `<tr><td>${esc(d.name)}</td><td>speaker${d.model?' · '+esc(d.model):''}</td><td class="members">${esc(d.address||'')}:${esc(d.port||'')}</td>`
  +`<td class="members">look at the groups above</td><td>${act2(d.name,'')}</td></tr>`));
 (SC.found.boxes||[]).forEach(b=>rows.push(
  `<tr><td>${esc(b.name)}</td><td>box${b.player?' · '+esc(b.player):''}</td><td class="members">${esc(b.address||'')}:${esc(b.port||'')}</td>`
  +`<td class="members">plays what this daemon tells it</td>`
  +`<td>${act2(b.address,b.name)}</td></tr>`));
 box.innerHTML=rows.join('')||'<tr><td colspan=5>nothing answered</td></tr>';
 document.querySelectorAll('[data-add]').forEach(b=>b.onclick=()=>{
  const boxes=(SC.found.boxes||[]).filter(x=>x.address===b.dataset.add);
  act2call(boxes.length?'/api/box/add':'/api/speaker/add',
   boxes.length?{name:b.closest('tr').cells[0].textContent,host:b.dataset.add,port:Number(boxes[0].port)}:{target:b.dataset.add});
 });
 document.querySelectorAll('[data-drop]').forEach(b=>b.onclick=()=>act2call('/api/output/remove',{name:b.dataset.drop}));
}
function act2call(path,body){ act(()=>api(path,body),async()=>{ SC=await api('/api/speakers'); renderFound(); }); }
async function applySound(){
 const picks=[...document.querySelectorAll('[data-at]')];
 let sent=0;
 for(const s of picks){
  const at=s.dataset.at, friday=s.dataset.friday==='1';
  const ev=clipFor(at,friday), all=(ev&&ev.media)||[], have=all[0]||'';
  if(s.value===have) continue;
  // The box decides what the prayer starts with. Whatever sits after it in the playlist
  // was put there underneath - by the Recordings card, or by hand in the profile - so
  // changing the head must not quietly drop the dua somebody placed after it: the tail
  // goes back with the new head. Choosing (no clip) takes the head away and leaves the
  // rest, which is what the box is saying.
  await api('/api/audio',{at,friday,media:s.value?[s.value].concat(all.slice(1)):all.slice(1)});
  sent++;
 }
 return sent;
}
async function applyMethod(){
 const j=await api('/api/method',{preset:$('#preset').value,asr_shadow:$('#asr').value});
 return j;
}
async function uploadFile(){
 const f=$('#file').files[0];
 if(!f) throw new Error('choose a recording first');
 // the bytes are the whole request: the panel looks at what they start with
 // before it lets them anywhere near media_dir
 // hand over the bytes, not the File object: a File body may be sent chunked,
 // and this server needs to know the size before it writes anything to disk
 const r=await fetch('/api/media/upload?name='+encodeURIComponent(f.name),
  {method:'POST',body:await f.arrayBuffer()});
 const j=await r.json().catch(()=>({error:'bad response'}));
 if(!r.ok) throw new Error(j.error||('HTTP '+r.status));
 return j;
}
async function act(fn,after){ try{ await fn(); say('',''); if(after)await after(); await load(); }catch(e){ say(e.message,'err'); } }
// The position, said three ways: the numbers themselves, the towns this machine
// knows with the way each of them lies, and - only if the profile asked for a map -
// squares of somebody else's map, credited where they appear. The diagram is drawn
// from bearings and distances and needs no network at all, which is the point of
// checking numbers before sending anything anywhere.
let W=null, FH=[], FQ='', TA='', MP=null, MQ=null, MZ=12, MAPTAG='', prefilled=false;
// FQ holds the words of the last look-up, so that the answer can be given in the place
// the person is looking at rather than only in the banner at the top of a long page. TA
// holds the shorter form of those words, offered but never sent until the page is pressed
// again, because an ask leaving this house has to be a thing somebody decided.
// How many squares a view is, across and down. One number, because the grid, the mark on
// it and the click that turns a pixel back into degrees all have to agree about it; when
// only the grid knew, the mark and the click were quietly a whole square off.
const MG=3;
function fillWhere(){
 if(prefilled) return;
 prefilled=true;
 $('#lat').value=st.location.latitude;
 $('#lon').value=st.location.longitude;
 $('#zone').value=st.location.timezone;
}
function renderWhere(){
 fillWhere();
 $('#geocoder').textContent=st.geocoder||'';
 showWhere(); showFound(); drawMap();
}
function dial(cities){
 const c=78, r=58, s=156;
 let g='<svg id="dial" viewBox="0 0 '+s+' '+s+'" width="'+s+'" height="'+s
  +'" role="img" aria-label="which way the nearby towns lie from these numbers">';
 g+='<circle cx="'+c+'" cy="'+c+'" r="'+r+'" fill="none" stroke="var(--line)"/>';
 g+='<text x="'+c+'" y="12" text-anchor="middle">N</text>';
 cities.forEach(t=>{
  const a=t.bearing*Math.PI/180, x=c+r*Math.sin(a), y=c-r*Math.cos(a);
  g+='<line x1="'+c+'" y1="'+c+'" x2="'+x.toFixed(1)+'" y2="'+y.toFixed(1)
   +'" stroke="var(--gold)"/>';
  g+='<text x="'+(c+(r+14)*Math.sin(a)).toFixed(1)+'" y="'+(c-(r+14)*Math.cos(a)+3)
   .toFixed(1)+'" text-anchor="middle">'+esc(t.name)+'</text>';
 });
 return g+'<circle cx="'+c+'" cy="'+c+'" r="3" fill="var(--gold)"/></svg>';
}
function showWhere(){
 const box=$('#where');
 if(!W){ box.innerHTML=''; return; }
 let h='<div class="row"><div>'+dial(W.near)+'</div><div class="cities">';
 W.near.forEach(t=>{ h+='<div>'+esc(t.name)+' <span class="tag">'+Math.round(t.km)
  +' km &middot; '+Math.round(t.bearing)+'&deg; true</span></div>'; });
 h+='</div></div><div class="fine">'+esc(W.zone_note)+'</div>';
 if(W.far_note) h+='<div class="fine warn">'+esc(W.far_note)+'</div>';
 box.innerHTML=h;
}
async function look(f){
 // A place that was found becomes the place being looked at, exactly as a click on the
 // map does: the mark moves, the map moves with it, the two boxes are refilled and the
 // nearby-towns dial is redrawn from arithmetic this daemon does for itself, with nobody
 // asked. What was typed at a geocoder does not come back as an address; only these
 // numbers do, and only if write-these is pressed afterwards.
 W=await api('/api/near?lat='+encodeURIComponent(f.latitude)+'&lon='
  +encodeURIComponent(f.longitude));
 MP={latitude:W.latitude,longitude:W.longitude};
 $('#lat').value=f.latitude; $('#lon').value=f.longitude;
 if(f.timezone) $('#zone').value=f.timezone;
 showWhere(); drawMap();
}
function showFound(){
 const box=$('#found');
 if(!FH.length){
  // The answer belongs under the box the words were typed into. A banner at the top of a
  // long page is easy to miss, and a list that stays empty reads as a page that did
  // nothing at all, which is why the reason and the way forward are said here.
  const offer=TA?('<div class="fine">Ask again with just <code>'+esc(TA)+'</code>, the'
   +' words before the town, when you are ready: <button id="tryagain">ask with those'
   +'</button> Read the labels when it answers, though - with fewer words a street of the'
   +' same name in another town answers just as happily, and that is not your street.'
   +'</div>')
   :'';
  box.innerHTML=FQ?('<div class="fine">Nothing came back for those words. A whole address'
   +' is one hard question for a lookup: the street, and the number on it, can both be in'
   +' the map while the answer is still empty, because a street is filed under the place it'
   +' sits in rather than the town name people put in a posting address. The house and the'
   +' street are the part the map knows best, so fewer words often answer where the whole'
   +' line did not. The postal code answers where the name of a town stops the answer, so'
   +' the code box beside it is the other way in.'+offer+'</div>')
   :'';
  if(TA)$('#tryagain').onclick=()=>{ $('#place').value=TA; $('#findit').click(); };
  return;
 }
 let h='<table><tbody>';
 FH.forEach((f,i)=>{
  h+='<tr><td>'+esc(f.label)+'</td><td class="members">'+f.latitude+', '+f.longitude
   +'</td><td class="members">'+esc(f.note)+'</td><td><button data-look="'+i
   +'">look there</button> '+(f.timezone
    ?(st.read_only?'<span class="unknown">read-only</span>'
                 :'<button data-use="'+i+'">use this</button>')
    :'<span class="unknown">no time zone came with it</span>')+'</td></tr>';
 });
 box.innerHTML=h+'</tbody></table>'
  +'<div class="fine">Looking costs nothing and writes nothing: look there moves the map,'
  +' the two boxes and the dial, and use this is the button that changes the profile. Read'
  +' the whole label before either: a street of the same name in another town answers just'
  +' as happily, and the words beside each line say where its clock comes from. When the'
  +' answer is a street rather than a door, look there and then click the door you live at:'
  +' the street writes a point on it, and a kilometre is worth under a second.'
  +'</div>';
 document.querySelectorAll('[data-use]').forEach(b=>b.onclick=()=>{
  const f=FH[Number(b.dataset.use)];
  act(()=>api('/api/location',{latitude:f.latitude,longitude:f.longitude,
                               timezone:f.timezone}),
   ()=>say('the location is written: the timetable above is the new one','ok'));
 });
 document.querySelectorAll('[data-look]').forEach(b=>b.onclick=()=>{
  const f=FH[Number(b.dataset.look)];
  act(async()=>{ await look(f); },
   ()=>say('the map is looking there and nothing has been written; write-these keeps it','ok'));
 });
}
function square(lat,lon,z){
 // Which square of the map a point falls in. Worked out here, in the page, because
 // the daemon serves one square at a time and has no notion of what anyone is
 // looking at.
 const n=Math.pow(2,z), fx=n*(lon+180)/360;
 const fy=n*(1-Math.log(Math.tan(Math.PI/4+lat*Math.PI/360))/Math.PI)/2;
 return {n:n, x:Math.floor(fx), y:Math.floor(fy), fx:fx, fy:fy};
}
function plant(ev){
 // Clicking the map is a way of pointing, not a way of writing. The mark moves, the two
 // boxes above are refilled, the nearby-towns dial follows - because that part is
 // arithmetic this daemon does for itself, with nobody asked - and the numbers still only
 // reach the profile when write-it is pressed. The maths is square() turned around: the
 // same squares at the same zoom, pixels back into degrees, measured against the width the
 // squares were really drawn at, since in a narrow window they come out smaller than the
 // 256 px they are served as. North here is the top of the map, which is not the same as
 // where a compass points.
 if(!MQ) return;
 const r=ev.currentTarget.getBoundingClientRect(), n=MQ.n;
 const u=MQ.x0+(ev.clientX-r.left)*MG/r.width, v=MQ.y0+(ev.clientY-r.top)*MG/r.height;
 const la=((360/Math.PI)*Math.atan(Math.exp(Math.PI*(1-2*v/n)))-90).toFixed(4);
 const lo=((u*360/n-180)).toFixed(4);
 $('#lat').value=la; $('#lon').value=lo;
 MP={latitude:Number(la),longitude:Number(lo)};
 act(async()=>{ W=await api('/api/near?lat='+la+'&lon='+lo); },
  ()=>say('the mark moved to '+la+', '+lo+': press write-it to keep those numbers. The time zone is still yours to set, and nothing has been saved yet.','ok'));
}
function drawMap(){
 const box=$('#map');
 if(st.map_tiles!=='osm'){ box.innerHTML=''; MAPTAG=''; MQ=null; return; }
 const p=MP||{latitude:st.location.latitude,longitude:st.location.longitude};
 const stamp=MZ+'|'+p.latitude+','+p.longitude;
 if(stamp===MAPTAG) return;      // the 60 second refresh must not fetch squares again
 MAPTAG=stamp;
 const q=square(p.latitude,p.longitude,MZ);
 const rad=Math.floor(MG/2);   // an odd MG puts the mark in the middle square of the view
 q.x0=q.x-rad; q.y0=q.y-rad;   // the square in the top-left of the view, which both the
 MQ=q;                         // mark and the click work their way out from
 let cells='';
 for(let dy=0;dy<MG;dy++)for(let dx=0;dx<MG;dx++){
  const x=Math.min(q.n-1,Math.max(0,q.x0+dx)), y=Math.min(q.n-1,Math.max(0,q.y0+dy));
  cells+='<img src="/api/tile?z='+MZ+'&x='+x+'&y='+y+'" alt="">';
 }
 // MG squares across and MG down, told to the stylesheet from here so the two cannot
 // disagree about the shape of a view. A grid of cells, not floats: the squares cover the
 // box edge to edge whatever width the window gives them, and a square that did not arrive
 // stays a dim cell in its own place instead of collapsing the layout into a hole. The box
 // itself is inline-grid, so it is exactly as wide as the squares in it: that is what the
 // mark's percentages and the click's fractions are measured against.
 box.innerHTML='<div class="row"><button id="zout">farther</button><span class="tag">zoom '
  +MZ+'</span><button id="zin">closer</button><span class="fine">map data '
  +esc(st.map_credit)+' &middot; click it to point</span><button id="zagain" hidden '
  +'title="a square that stayed dim did not arrive: this asks for the dim ones again">'
  +'try those again</button></div><div class="mapbox" role="img" '
  +'style="grid-template-columns:repeat('+MG+',var(--sq));grid-auto-rows:var(--sq)" '
  +'aria-label="the area around these numbers; click it to move the position boxes">'+cells
  +'<span class="spot" style="left:'+((q.fx-q.x0)*100/MG).toFixed(2)+'%;top:'
  +((q.fy-q.y0)*100/MG).toFixed(2)+'%"></span></div>';
 // A square that did not arrive stays dim and brings up the button next to it: the map
 // is the one part of this page that depends on somebody else being awake. Pressing it
 // redraws the view, and the squares the daemon already has come back from its own shelf
 // without anyone being asked again.
 document.querySelectorAll('#map img').forEach(i=>{
  i.onerror=()=>{ i.style.opacity=.15; const b=$('#zagain'); if(b){ b.hidden=false; } };
 });
 $('#zin').onclick=()=>{ if(MZ<18){ MZ++; drawMap(); } };
 $('#zout').onclick=()=>{ if(MZ>3){ MZ--; drawMap(); } };
 // Forcing a redraw is the whole retry: the memo that keeps the 60 second refresh from
 // fetching squares is cleared, so the view is built again, and the daemon answers the
 // squares it already kept from its own shelf.
 $('#zagain').onclick=()=>{ MAPTAG=''; drawMap(); };
 document.querySelector('.mapbox').onclick=plant;
}
// the scan is expensive and the daemon caches it, so arriving at the page shows
// what was last seen if there is a last-seen; the button is for when speakers
// have been added or moved rooms
async function load(){ st=await api('/api/state'); if(!SC&&st.scan_at) SC=await api('/api/speakers'); render(); }
$('#yaml').addEventListener('input',()=>{ $('#yaml').dataset.dirty='1'; });
$('#refresh').onclick=()=>act(load);
$('#save').onclick=()=>act(()=>api('/api/config',{text:$('#yaml').value}),()=>{ $('#yaml').dataset.dirty=''; say('saved and reloaded','ok'); });
$('#reload').onclick=()=>act(()=>api('/api/reload'),()=>{ $('#yaml').dataset.dirty=''; say('reloaded from disk','ok'); });
$('#applymethod').onclick=()=>act(async()=>{ const j=await applyMethod(); note=j.still_overridden||[]; },
 ()=>say(note.length?'method written, and your own numbers are still in force: '+note.join(', ')
                   :'method written; the timetable on this page is the new one','ok'));
$('#hijminus').onclick=()=>act(()=>api('/api/hijri',{days:st.hijri_offset-1}),()=>say('the Hijri date on this page moved','ok'));
$('#hijplus').onclick=()=>act(()=>api('/api/hijri',{days:st.hijri_offset+1}),()=>say('the Hijri date on this page moved','ok'));
$('#applysound').onclick=()=>act(async()=>{ sent=await applySound(); },
 ()=>{ $('#sound').dataset.dirty=''; say(sent?('wrote '+sent+' clip'+(sent>1?'s':'')+': the daemon reloaded with them')
                                       :'nothing needed writing','ok'); });
// Where the house is. The three buttons are deliberately separate: checking the
// numbers is a look, finding a place is a question to somebody further away, and
// writing them is the only one that changes the profile.
$('#check').onclick=()=>act(async()=>{
 const lat=$('#lat').value.trim(), lon=$('#lon').value.trim();
 if(!lat||!lon) throw new Error('type the latitude and the longitude first');
 W=await api('/api/near?lat='+encodeURIComponent(lat)+'&lon='+encodeURIComponent(lon));
 MP={latitude:W.latitude,longitude:W.longitude}; FH=[]; showWhere(); showFound();
},()=>say('these are the numbers the timetable above would use','ok'));
$('#writewhere').onclick=()=>act(()=>api('/api/location',{latitude:$('#lat').value,
 longitude:$('#lon').value,timezone:$('#zone').value}),
 ()=>say('the location is written; the timetable above is the new one','ok'));
$('#findit').onclick=()=>act(async()=>{
 const q=$('#place').value.trim(), zp=$('#zip').value.trim();
 if(!q&&!zp) throw new Error('type a street or a postal code first');
 const j=await api('/api/geocode',{q:q,postcode:zp});
 TA=j.try_again||'';
 FQ=q; FH=j.hits||[]; showFound();   // FQ only records a look-up that was answered, so a
                                     // failed question never leaves an empty-looking answer
},()=>say(FH.length?('found '+FH.length+', from '+st.geocoder+'; nothing of it is kept,'
                   +' and nothing has been written yet')
                 :'nothing matched those words; asking again with fewer of them is'
                  +' offered under the box','ok'));
$('#scan').onclick=()=>act(async()=>{ SC=await api('/api/speakers?refresh=1'); },
 ()=>say(((SC.found.speakers||[]).length)+' speakers, '+((SC.found.groups||[]).length)+' groups, '
   +((SC.found.boxes||[]).length)+' boxes','ok'));
$('#upload').onclick=()=>act(async()=>{ up=await uploadFile(); },
 ()=>{ $('#uploadsay').textContent=up.uploaded+' in media_dir';
       say('added '+up.uploaded+(up.url?' · a speaker can reach it at '+up.url:''),'ok'); });
let player=null, track='', drag=null;
// The preview is the browser asking for the bytes and making the sound itself: no
// speaker on the network is involved, and no level is set anywhere, because the
// level on this computer belongs to whoever is using it. Play, pause and stop are
// three buttons because they are three different asks: pause keeps the place you
// got to, stop goes back to the front and lets go of the file, and the bar between
// them is a position you can drag. Dragging it asks the daemon for the bytes from
// there, which is how the middle of a two-minute recitation costs a browser the
// middle of it rather than the whole of it.
function mmss(n){ const m=Math.floor(n/60), s=Math.floor(n%60);
  return m+':'+(s<10?'0':'')+s; }
// What the controls may do, said in one place, so the page never offers an answer
// to a question that has no meaning yet: you cannot pause what is not going, and
// nobody should be offered a bar that has nothing on it.
function pstate(){ const going=!!player&&!player.paused;
 $('#hear').disabled=going; $('#hush').disabled=!going;
 $('#halt').disabled=!player; $('#seek').disabled=!player; }
function pread(){
 if(!player) return;
 if(drag===null) $('#seek').value=Math.floor(player.currentTime||0);
 const left=Number.isFinite(player.duration)?' of '+mmss(player.duration):'';
 $('#hearsay').textContent=(player.paused?'paused at ':'playing ')+mmss(player.currentTime||0)
  +left+' · out of this computer, not a speaker'; }
function over(name){
 player=null; track=''; drag=null; $('#seek').value=0; pstate();
 $('#hearsay').textContent='finished '+name; }
function unusable(name){
 player=null; track=''; drag=null; $('#seek').value=0; pstate();
 $('#hearsay').textContent=name+' is not a sound this browser can play'; }
function hearIt(name){
 if(player&&!player.paused) return;        // one thing at a time out of this box
 if(!name){ say('pick a recording to listen to first','err'); return; }
 if(!player){
  const a=new Audio('/api/clip?name='+encodeURIComponent(name));
  a.onended=()=>{ if(player===a) over(name); };
  a.onerror=()=>{ if(player===a) unusable(name); };
  a.onloadedmetadata=()=>{ $('#seek').max=Math.floor(a.duration||0); pread(); };
  a.ontimeupdate=pread;
  player=a; track=name; $('#seek').max=0; $('#seek').value=0;
 }
 try{ player.play().then(pread,e=>{ $('#hearsay').textContent='this browser would not start it: '+e.message; }); }
 catch(err){ $('#hearsay').textContent='this browser would not start it: '+err.message; return; }
 pstate(); pread();
}
function stopIt(){
 if(!player) return;
 const name=track;
 player.pause();
 // Going back to the front is the ask. A browser still reading the header of a file
 // has no front to go back to, and dropping the element a few lines below is the
 // same answer by other means, so a failure here is not worth a message.
 try{ player.currentTime=0; }catch(err){ }
 player=null; track=''; drag=null; $('#seek').value=0; pstate();
 $('#hearsay').textContent='stopped '+name; }
$('#hear').onclick=()=>hearIt($('#preview').value);
$('#hush').onclick=()=>{ if(player&&!player.paused){ player.pause(); pstate(); pread(); } };
$('#halt').onclick=stopIt;
// While a finger is still on the bar the sound does not move: a browser asked for a
// new piece of the recording at every step of a drag would spend the drag fetching.
$('#seek').oninput=()=>{ drag=Number($('#seek').value)||0;
 const left=player&&Number.isFinite(player.duration)?' of '+mmss(player.duration):'';
 $('#hearsay').textContent='to '+mmss(drag)+left+' · '+track; };
$('#seek').onchange=()=>{ if(player&&drag!==null){ try{ player.currentTime=drag; }catch(err){ } }
 drag=null; pread(); };
load().catch(e=>{$('#top').textContent=e.message;});
setInterval(()=>load().catch(()=>{}),60000);
</script></body></html>
"""
