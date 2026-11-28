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

from .favicon import FAVICON_DATA_URL

# The mark the browser tab wears. Same drawing as packaging/windows-service/muezzin.ico,
# which is what the exe, the installer and the Start Menu entry wear, so the four surfaces
# a person meets are one mark rather than four - and the reason they had none of it is
# boring and true: an icon is a file, and until this build there was no file.
#
# It rides inside the page as a data: URL instead of arriving from a route, for the same
# reason the lattice below is inline: the page stays one document that asks its own address
# for nothing else, and the icon then works in a checkout, in a container and in a frozen
# exe without anyone having to know where the exe put its temp folder.
_TAB_ICON = '<link rel="icon" type="image/png" href="' + FAVICON_DATA_URL + '">'

PAGE = ("""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
""" + _TAB_ICON + """
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
 /* The occasions of a day - a fast, a mourning, a feast - are pills, and they ride along
    with the day they belong to wherever that day is named on the page. */
 .mark { font-size:12px; border:1px solid var(--line); border-radius:20px; padding:1px 9px }
 .mark.mourn { color:var(--mourn); border-color:#39566b; background:rgba(60,90,115,.18) }
 .mark.celebrate { color:var(--gold2); border-color:#5c4a22; background:rgba(217,171,78,.14) }
 .mark.plain { color:var(--turq) }
 /* the Arabic name of the day, inside its own pill, in the pill's colour */
 .mark .ar { color:inherit; font-size:13px }
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
 /* Every slider on this page is something you can press, and every one of them is about a
    speaker: a place inside a recording, or the level muezzin asks a speaker to come out at.
    Nothing here moves the volume of a computer, which belongs to the person sitting in front
    of it. */
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
 /* The long fine print under a card folds under one line on a phone-width window,
    where the explanations - not the tables - are most of the scrolling. The fold is
    written open in the markup, so the words stand on the page before any script has
    a say and a wide window keeps reading them the way it always did; the rules under
    the phone width, further down, are what shut it and show the summary line, and
    the script carries the fold across a rotation or a resize. */
 details.finefold { margin:0; color:var(--dim); font-size:12.5px }
 details.finefold > summary { display:none }
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
    column under the header it belongs to. The widths are weighed against the narrowest
    window this set serves, which is the one just above the phone rules: there the card is
    the whole page, six columns share it, and every column holding a control has to be wider
    than that control at its own size. Two of them were not. A seven percent sliver for the
    on column is less than the 38px switch standing in it, so the switch ran over the edge of
    its column and on top of the slider beside it; and the last column asked its two buttons
    to keep to one line, which made them one unbreakable line about as wide as the column, so
    test and stop ran sideways over the level column. A word can be broken where it has to be
    and this card says so; a control cannot, so a column with a control in it is given a width
    the control fits, and two buttons in one cell are allowed to stand on two lines. */
 #outputstbl { table-layout:fixed }
 #outputstbl th:nth-child(1) { width:21% }
 #outputstbl th:nth-child(2) { width:13% }
 #outputstbl th:nth-child(3) { width:15% }
 #outputstbl th:nth-child(4) { width:9% }
 #outputstbl th:nth-child(5) { width:22% }
 #outputstbl th:nth-child(6) { width:20%; text-align:right }
 #outputstbl td { overflow-wrap:break-word }
 #outputstbl td:last-child { text-align:right }
 #outputstbl input[type=range] { width:80px; vertical-align:middle }
 /* The rooms inside a group are not speakers in the list, so they get rows of their own
    under the group's row, in the same columns as the row above - a room's slider under
    the group's own slider, because it is the same kind of number. They used to be one long
    line of names and sliders inside one cell, and the last cell of a row is the one that
    must never end up outside the card: four rooms asked to be, and ran past its edge. A
    room row carries no rule above it, and the rooms are marked off from the outputs by a
    left edge, so a room reads as belonging to the group above it rather than as an output
    of its own. The names are what those speakers call themselves on the network, and each
    one has a slider because the whole reason for naming the rooms is that the kitchen and
    the study are not the same room at the same loudness. */
 #outputstbl tr.roomrow td { border-top:0; padding:2px 8px 2px 0 }
 #outputstbl tr.roomrow td.roomname { padding-left:13px; border-left:2px solid var(--line) }
 #outputstbl tr.roomrow .tag { font-size:11.5px }
 /* A prayer's levels are not a column. Most prayers are happy with the numbers the house
    already asks its speakers for and say nothing of their own, so a column of sliders per
    room would hang four sliders off every row of this table and bury the two things the
    card is for. The row carries a short summary instead - `levels: as usual`, or the rooms
    that were moved - and pressing it opens a row of its own under the prayer, holding only
    the rooms this prayer plays through. The left edge is the same mark a room inside a
    group is marked off by, because it is the same kind of thing: lines that belong to the
    row above them, in that row's columns. */
 /* The Sound card is a table of what the day will play, and its cells hold a select each:
    a select's own width is the width of the longest recording name in it, which on this page
    is a name somebody gave a file. So the columns are told, as the other cards' are, and the
    select fills the column it was given instead of asking the table for a name's width. The
    levels row spans the whole row already, so that row is untouched by this. */
 #soundtbl { table-layout:fixed }
 #soundtbl th:nth-child(1) { width:20% }
 #soundtbl th:nth-child(2) { width:12% }
 #soundtbl th:nth-child(3) { width:34% }
 #soundtbl th:nth-child(4) { width:34% }
 #soundtbl td { overflow-wrap:break-word }
 #soundtbl select { width:100% }
 #soundtbl tr.lvrow td { border-top:0; padding:4px 8px 4px 0 }
 #soundtbl tr.lvrow .lvline { padding-left:13px; border-left:2px solid var(--line) }
 #soundtbl tr.lvrow input[type=range] { width:80px; vertical-align:middle }
 #soundtbl tr.lvrow .tag { font-size:11.5px }
 #soundtbl tr.lvrow .lvname { display:inline-block; min-width:16ch }
 #soundtbl button.lv { display:block; margin-top:5px; font-size:11.5px }
 /* The same shape as the Outputs table, for the same reason: a recording is called
    whatever the person who put it in the folder called it, and a table that sizes
    itself lets a long name push the buttons clean out of the card. It has four columns
    now rather than five. Which events hold a recording's name used to be said twice: once
    as words of their own, and once by the Event column, whose dropdown names the event to
    put the recording on and whose button takes it off again - and the second of those is
    where the first is changed, so the words column could only ever agree with it or be
    out of date. The two columns a person presses are lined up down the page instead of
    starting wherever the longest word in the column leaves them: a switch is one small
    thing standing in a column far wider than itself, and buttons that begin at a different
    place in every row look like a list that has lost its edge. */
 #libtbl { table-layout:fixed }
 #libtbl th:nth-child(1) { width:26% }
 #libtbl th:nth-child(2) { width:9% }
 #libtbl th:nth-child(3) { width:11% }
 #libtbl th:nth-child(4) { width:54% }
 #libtbl td { overflow-wrap:break-word }
 #libtbl select { max-width:100% }
 #libtbl th:nth-child(3), #libtbl td:nth-child(3) { text-align:center }
 #libtbl th:last-child, #libtbl td:last-child { text-align:center }
 /* The name is the box you type in, so it is as wide as the column it sits in rather
    than a fixed number of characters: a speaker called whole-house lost its last
    letters in a 12ch box, and a name you cannot read in full is a name you cannot
    rename without guessing. */
 .rename { width:100%; min-width:0; box-sizing:border-box; padding:3px 6px }
 /* The Speakers card is the third table on this page that takes its rows from words it did
    not choose, and it is the worst of the three: a name the person typed into the speaker
    itself, an address that is one unbroken word, and the speaker maker's own words for what
    the thing is. It was the one table left to size itself, because on a desk its rows are
    short. Its columns are told here for the same reason as the other two - and the last one,
    the column holding use and stop using, is the one that sat outside the card. */
 #foundtbl { table-layout:fixed }
 #foundtbl th:nth-child(1) { width:24% }
 #foundtbl th:nth-child(2) { width:16% }
 #foundtbl th:nth-child(3) { width:20% }
 #foundtbl th:nth-child(4) { width:22% }
 #foundtbl th:nth-child(5) { width:18%; text-align:right }
 #foundtbl td { overflow-wrap:break-word }
 /* The Events card is the last table on the page whose words are not its own: an event
    is called whatever the person who wrote the profile called it, and the last column of the
    row is the list of recordings that call will play, which is longer still. Told columns,
    same as the rest, so the list of clips wraps inside its cell instead of leaning the table
    out of the card. */
 #uptbl { table-layout:fixed }
 #uptbl th:nth-child(1) { width:14% }
 #uptbl th:nth-child(2) { width:32% }
 #uptbl th:nth-child(3) { width:27% }
 #uptbl th:nth-child(4) { width:27% }
 #uptbl td { overflow-wrap:break-word }
 /* The card below this comment shows one day of the list at a time, and the day it is
    showing is said once, in the strip above the table. So the first column of a row carries
    a clock and nothing else: five characters, near enough 38px at this page's own 14px, and
    a cell keeps 8px of its column for itself, which an eighth of a wide card covers with
    room to spare. What came off that column went to the two lists, which were the columns
    running out. The strip wraps, because a narrow card is narrower than the name of a day
    beside four controls, and the last thing anybody should lose on a small screen is the
    arrow that goes back. */
 .daynav { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:8px }
 #upday { color:var(--gold2); font-variant-numeric:tabular-nums }
 #upprev, #upnext { min-width:38px }
 /* The list of places that answered a search is a table the page builds out of somebody
    else's map: a label that runs the length of a line, then the numbers, then the two buttons
    at the end of the row. It has no header row to be told, so its cells are told instead, and
    the same rule keeps the far end of an answer inside the card it was drawn in. */
 #hitstbl { table-layout:fixed }
 #hitstbl td:nth-child(1) { width:34% }
 #hitstbl td:nth-child(2) { width:18% }
 #hitstbl td:nth-child(3) { width:20% }
 #hitstbl td:nth-child(4) { width:28% }
 #hitstbl td { overflow-wrap:break-word }
 .mapbox img { width:100%; height:100%; display:block }
 .spot { position:absolute; width:9px; height:9px; margin:-4px 0 0 -4px; border-radius:50%;
  background:var(--gold); box-shadow:0 0 0 3px rgba(11,20,17,.8) }
 .cities { display:inline-block; vertical-align:top; margin-left:14px }
 .cities div { margin-bottom:5px }
 #dial text { fill:var(--dim); font-size:9.5px }
 #dial line, #dial circle { stroke-width:1 }
 /* One lamp for every promise this page makes to the daemon - a level written to the
    profile, a look at what is on the LAN, a recording handed to a speaker across the room.
    It is fixed to the bottom of the window rather than in the middle of it, because the
    page is worth reading while the daemon is busy, and it takes no clicks: a person who
    wants to move the next slider while the last one is still travelling may do so. It is
    shown by a timer rather than by the request, so the asks that answer in a twentieth of a
    second never show anything at all, and only a wait long enough to wonder about gets a
    light. The ring turns because a still mark next to a slow ask reads like a broken one. */
 #busy { position:fixed; left:50%; bottom:26px; transform:translateX(-50%); z-index:5;
  display:flex; gap:9px; align-items:center; pointer-events:none; background:#0d1815;
  border:1px solid var(--line); border-radius:20px; padding:8px 15px; font-size:13px;
  color:var(--dim); box-shadow:0 6px 22px rgba(0,0,0,.45) }
 #busy[hidden] { display:none }
 .spin { width:13px; height:13px; box-sizing:border-box; border:2px solid var(--line);
  border-top-color:var(--gold); border-radius:50%; animation:turn 1s linear infinite }
 @keyframes turn { to { transform:rotate(360deg) } }
 @media (prefers-reduced-motion: reduce) { .spin { animation-duration:3s } }
 /* A phone is the machine this page most often gets opened on - the level of a speaker is
    a thing you fix while the speaker is making the noise - and on a phone the switches and
    the sliders were in the way of each other, for two different reasons.
    The switch was 38px by 20px, smaller than the pad of a thumb. A switch that answers a
    press half an inch either side of where it was made is worse than one that is hard to
    hit, because what it sends rewrites the profile. So the target grows and the drawing
    does not: the box becomes 44px square with nothing in it but the track and the knob,
    and the track is the same 38px by 20px it was drawn at, held in the middle of the box.
    The crowding was the other thing, and it belongs to the tables. Six columns told their
    widths in percentages leave a fifth of a phone to the level column, about four
    centimetres: an 80px slider, a chip beside it and the sentence about what a group's
    number does, all in that space, each pushing at the others - which is how the test
    button of a row once ended up outside the card. Under this width the slider fills its
    own column instead of a fixed number of pixels and is taller, so a thumb has something
    to hold; the chip drops onto a line under it rather than beside it; the sentence about
    a group gives the row up, being said again in full in the lines under the card; and the
    columns are retold so that each control has the width the control needs. A prayer's
    levels line is told the same way, because it is the same kind of line, just as narrow,
    with a name and two chips in front of its bar. */
 @media (max-width:620px) {
  /* The grid asks for columns of at least 320px, which is fair on a desk and a promise the
     page cannot keep on a narrow phone: below that width every card insists on being wider
     than the window it was opened in, and the card's own right edge - where the buttons are -
     falls off the screen. Under this width the column is allowed to shrink to the window, and
     the cards inside it, their tables and their buttons follow it down to whatever is left. */
  main { padding:12px; grid-template-columns:minmax(0,1fr) }
  section { padding:12px }
  .switch { width:44px; height:44px; border-radius:8px; background:none }
  .switch:before { content:""; position:absolute; left:3px; right:3px; top:12px; height:20px;
   border-radius:10px; background:#2b3f38 }
  .switch[aria-checked=true] { background:none }
  .switch[aria-checked=true]:before { background:var(--gold) }
  .switch:after { top:15px; left:6px }
  .switch[aria-checked=true]:after { left:24px }
  input[type=range] { height:34px }
  /* The columns are retold here, not merely narrowed. At this width the on column has to
     be at least as wide as the 44px switch, the last column at least as wide as the longest
     one-word thing a button there can say - same as the group, for a room inside a group -
     and the level column wide enough for a bar a thumb can hold; the names and the addresses
     give that room, because a long word in a column breaks across lines here already and
     never pushes a neighbour out of the card the way a control does. And the
     two buttons of a row - test, and stop while a test is playing - stand one under the
     other rather than side by side, which is the same accident the card was fenced
     against once already. */
  #outputstbl th:nth-child(1) { width:17% }
  #outputstbl th:nth-child(2) { width:10% }
  #outputstbl th:nth-child(3) { width:14% }
  #outputstbl th:nth-child(4) { width:19% }
  #outputstbl th:nth-child(5) { width:20% }
  #outputstbl th:nth-child(6) { width:20% }
  #outputstbl input[type=range] { width:100%; min-width:0 }
  #outputstbl td > .tag, #outputstbl td > .why, #outputstbl tr.roomrow td > .tag {
   display:block; margin-top:3px }
  #outputstbl .why { font-size:11.5px }
  #outputstbl .roomnote { display:none }
  /* The Sound card's two selects were the widest thing in the card, because a select is as
     wide as the longest name it offers. Here they are told to share the card between them,
     with the day's name and the levels button given only what those words need: a name that
     is cut short in a box is still a name you can open the box and read. */
  #soundtbl th:nth-child(1) { width:16% }
  #soundtbl th:nth-child(2) { width:14% }
  #soundtbl th:nth-child(3) { width:35% }
  #soundtbl th:nth-child(4) { width:35% }
  #soundtbl tr.lvrow .lvline { display:flex; flex-wrap:wrap; align-items:center; gap:3px 8px }
  #soundtbl tr.lvrow input[type=range] { width:auto; flex:1 1 90px; min-width:90px }
  #soundtbl tr.lvrow .lvname { min-width:0 }
  #soundtbl tr.lvrow .tag, #soundtbl tr.lvrow button { flex:0 0 auto }
  /* The recordings card holds the page's other switches, and its drawing column was told
     an eleventh of the card: room enough for the 38px switch it was drawn around, not for
     the 44px target. The name column and the Event column give a little to it, because a
     name breaks across lines and a button has an honest width, and both are already told to
     stay inside this card. The Event column is the widest thing in the row now that the
     words column is gone: a dropdown, and two buttons standing one under the other. The
     size is given room of its own as well. A size is two words with a space between them,
     and the only other place it can break is inside the number: three digits at this page's
     own 14px are about 24px across, and a cell keeps 8px of its column for itself, so below
     a thirteenth of a phone the reading comes out 84 / 2 KB, which is nobody's size. */
  #libtbl th:nth-child(1) { width:24% }
  #libtbl th:nth-child(2) { width:13% }
  #libtbl th:nth-child(3) { width:19% }
  #libtbl th:nth-child(4) { width:44% }
  /* The eighth of a column a cell keeps for itself on the right is what puts a 44px switch
     over the edge of a narrow column: the switch is that column's whole content, so on a
     phone the edge is given back and the switch stands in the middle of the column it
     belongs to. The outputs' on column is wide enough already, and is lined up the same
     way, so the switches down a column of rows read as a column. */
  #outputstbl td:nth-child(4), #libtbl td:nth-child(3) { padding-right:0; text-align:center }
  #outputstbl th:nth-child(4), #libtbl th:nth-child(3) { text-align:center }
  /* The Speakers card on a phone is three columns of somebody else's words - the name on the
     speaker, one unbroken address, the maker's own phrase for the thing - in front of one
     column of buttons, and on a phone that is one column too many. The address gives most of
     its width away to the buttons, because an address read across three lines still says which
     box it is, while a button that fell off the card says nothing at all. */
  #foundtbl th:nth-child(1) { width:18% }
  #foundtbl th:nth-child(2) { width:18% }
  #foundtbl th:nth-child(3) { width:16% }
  #foundtbl th:nth-child(4) { width:17% }
  #foundtbl th:nth-child(5) { width:31%; text-align:left }
  /* A call's playlist is the longest words in the Events card, and on a phone the card
     is one column of the page: the name of the day is in the strip above the table and not in
     a column at all, so the first column only has to be wide enough for a clock and the eight
     pixels a cell keeps back - which is why a fifth of the card is what it gets. The event
     keeps its name, and the two lists break where they have to rather than leaning the table
     over the border they are drawn inside. The two arrows are 44px wide here like every other
     thing a finger aims at. */
  #uptbl th:nth-child(1) { width:18% }
  #uptbl th:nth-child(2) { width:38% }
  #uptbl th:nth-child(3) { width:22% }
  #uptbl th:nth-child(4) { width:22% }
  #upprev, #upnext { min-width:44px; padding:8px 7px }
  /* The answers to a search are words off somebody else's map, and a place name has no
     opinion about where it ends: the label keeps the biggest share of the card because it is
     the only part that says which place this is, and the numbers and the note break where
     they have to. */
  #hitstbl td:nth-child(1) { width:32% }
  #hitstbl td:nth-child(2) { width:16% }
  #hitstbl td:nth-child(3) { width:13% }
  #hitstbl td:nth-child(4) { width:39% }
  /* The last promise is the one that holds however narrow the window gets, and it is about
     buttons rather than columns: a control has a width it cannot go under, where a word can be
     broken somewhere, so buttons standing side by side in one cell are what push a table out
     of the card around it. Under this width the buttons in a row stand one under the other and
     fill the column they are in, and a button therefore cannot be wider than a column that was
     told its width - which is the whole shape of the accident this card keeps having. The
     switches are left out of it: they were just told their own 44px, and the columns holding
     them were told to be wider than that on purpose. */
  #outputstbl td > button:not(.switch), #libtbl td > button:not(.switch),
  #foundtbl td > button, #hitstbl td > button { display:block; width:100%; margin-top:4px;
   padding:8px 7px }
  /* And here the fine print folds: one gold line to tap, with every word of the
     explanation still underneath it, just out of the scroll until asked for. */
  details.finefold > summary { display:block; color:var(--gold); cursor:pointer;
   list-style:none; margin-top:8px }
  details.finefold > summary:before { content:"▸ " }
  details.finefold[open] > summary:before { content:"▾ " }
 }
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
 <section><h2>Events</h2>
  <div class="daynav"><button id="upprev" aria-label="the day before">&larr;</button><span id="upday"></span><button id="upnext" aria-label="the day after">&rarr;</button><button id="upalldays">all the days</button></div>
  <table id="uptbl"><thead><tr><th>when</th><th>event</th><th>speakers</th><th>media</th></tr></thead><tbody id="upcoming"></tbody></table>
  <details class="finefold" open><summary>more info</summary>
 <div class="fine">This is the timetable, one day at a time, and it opens on today. The arrows, or the left and right keys of a keyboard as long as nothing is being typed, walk through the days that have been planned; every day is the same list with nothing taken out of it, and a day's own occasions ride beside its name.</div>
 </details>
 </section>
 <section class="wide"><h2>Outputs</h2><table id="outputstbl"><thead><tr><th>name</th><th>kind</th><th>target</th><th>on</th><th>level</th><th></th></tr></thead><tbody id="outputs"></tbody></table>
  <details class="finefold" open><summary>more info</summary>
  <div class="fine">A speaker muezzin has to find on the network gets the recording a few seconds before the time it belongs to, so the first note is already in the air when that time arrives; the number in brackets is that head start. A profile sets it per speaker with lead_seconds, and 0 means exactly on the minute. Everywhere else on this page the times shown are the computed ones.</div>
  <div class="fine">The level is what muezzin asks a speaker for the moment it starts playing, so a test comes out at the same loudness as an adhan instead of at whatever the room happened to be left at. It is muezzin's to ask only of a speaker it casts to: the level of the computer running this program, or of a box on the LAN, belongs to whoever is sitting at that machine, and this page never touches it. A speaker with nothing written in the profile is asked for 50%. A row whose target is a speaker group is several rooms wearing one name, and a group has no level of its own that anybody hears: the number written there is what every room inside it is asked for while a call is playing, and each room goes back to wherever its owner had left it the moment the call ends. Rooms at levels of their own - the kitchen at 50% while the study stays at 40% - get a slider of their own on the line under the group's row, which writes one members: line per room into the profile; a room with no line of its own is asked for the group's number. One prayer can want different numbers from the rest of the day, and that goes under the prayer rather than here: see the levels line in the Sound card.</div>
  </details>
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
  <!-- This answer list has to be named for itself. The Speakers card further down the
   page is #found, and a page asks for a name by taking the first element carrying it:
   two things wearing one name meant the scan ran, the tag beside it said a newer time,
   and the table of speakers never changed. -->
  <div id="hits"></div>
  <details class="finefold" open><summary>more info</summary>
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
  </details>
  <div id="map"></div>
 </section>
 <section><h2>Method</h2>
  <div class="row"><select id="preset"></select><select id="asr"></select><button id="applymethod">apply method</button></div>
  <div class="fine" id="overrides"></div>
  <details class="finefold" open><summary>more info</summary>
  <div class="fine">That list is every method muezzin ships with, in two groups by where
   the night is taken to end. The Sunni methods end it at sunrise; the Ja'fari ones end
   it at Fajr, which is why the second group's midnight sits earlier in the evening. The
   page is not arguing about it, it is only telling you which numbers moved. If the
   figures you follow are not in the list, write them under <code>method:</code> in the
   profile - they stay put when you change the name here.</div>
  </details>
  <div class="row"><span class="tag">Hijri date</span><button id="hijminus">&minus;1</button><span id="hijridays">0</span><button id="hijplus">+1</button></div>
  <div class="fine">Arithmetic cannot see the moon, so this is where you tell it what you saw.</div>
 </section>
 <section class="wide"><h2>Sound</h2>
  <table id="soundtbl"><thead><tr><th>time</th><th></th><th>every day</th><th>Friday</th></tr></thead><tbody id="sound"></tbody></table>
  <div class="row"><button id="applysound">apply these clips</button><span class="tag" id="soundsay">nothing changed</span></div>
  <div class="row"><input type="file" id="file" multiple accept=".mp3,.m4a,.wav,.ogg,.oga,.flac,.aac,.opus,audio/*"><button id="upload">add this recording</button><span class="tag" id="uploadsay"></span></div>
  <div class="row"><select id="preview"></select><button id="hear">play it here</button><button id="hush" disabled>pause</button><button id="halt" disabled>stop</button><input id="seek" type="range" min="0" max="0" step="1" value="0" disabled aria-label="how far into it you are"><span class="tag" id="hearsay">nothing playing</span></div>
  <details class="finefold" open><summary>more info</summary>
  <div class="fine">That plays in this browser, out of the computer this page is open on, at the level
   that computer is already set to. There is no volume control here on purpose: the level on a computer
   belongs to whoever is sitting at it. The bar is not a level either - it is a place inside the
   recording, and dragging it asks the daemon for the bytes from there, which is how you hear the middle
   of a recitation without sitting through the start of it. Nothing on the network hears it - the
   <b>test</b> button in the Outputs table is the one that sends a recording to a speaker, and the two are easy to tell apart when
   you are choosing what a prayer should sound like.</div>
  <div class="fine">A clip is picked from what is already in <code>media_dir</code>; the button above
   puts a new recording there. The box takes several at once, and each one goes in on its own: one that the daemon refuses says which and why, and the rest still arrive. Nothing overwrites a recording that is playing, so two recordings of
   the same adhans need two names. These boxes choose what a prayer starts with; the Recordings card
   below adds a recording to the end of a prayer's list, which is where a dua after the adhan goes.
   One of the choices is <b>(random from the library)</b>: the prayer names nothing and asks the
   folder for a recording at the moment it fires, which writes <code>random: 1</code> under the
   event, and the pool is the whole folder except what the Recordings card's <b>Random</b> switch
   holds back. Picking a named clip instead takes the drawing out; wanting several drawings at
   once is the one thing still written in the profile by hand - <code>random: 2</code> and so on.</div>
  <div class="fine">The line under each clip says what that prayer asks its speakers for. Most prayers
    have nothing of their own to say and read <b>levels: as usual</b>, which is the number in the Outputs
    card. Press it and the rooms this prayer plays through open in a line of their own underneath, one
    slider each, and only the rooms you move are written into the profile: a prayer that leaves a room
    alone leaves that room's line out, so waking the kitchen for Fajr and nothing else is one line under
    Fajr and none under the rest. A room inside a group is asked for its number over a connection of its
    own while the call plays, and handed back to wherever its owner left it the moment the call ends; a
    number written here outranks the one the Outputs card holds, which is the reason the line is here and
    not there.</div>
  </details>
 </section>
 <section class="wide"><h2>Recordings in the folder</h2>
  <div class="row"><span class="tag" id="libdir"></span></div>
  <table id="libtbl"><thead><tr><th>name</th><th>size</th><th>Random</th><th>Event</th></tr></thead><tbody id="library"></tbody></table>
  <details class="finefold" open><summary>more info</summary>
  <div class="fine">Every row is a file in <code>media_dir</code>, and that folder is the whole library:
   there is no second list of recordings to keep in step with it. <b>Event</b> puts the recording at the
   <i>end</i> of an event's playlist, after the clip the Sound card chose to start that event with, which is
   how a prayer plays the adhan and then a dua; taking it back off an event is a line in the profile, in
   the card below. <b>delete</b> refuses while an event still names the file and says which one was in
   the way, because the call would fire at its minute into a file that is no longer there. <b>Random</b> is whether the drawing may pick this recording for an event that
   says <code>random: N</code>: off writes its name under <code>library: exclude:</code>, and every playlist
   that names it by hand goes on playing it. A name that is held back but whose file has gone still shows up
   here, with the absence said, so the hold can be let go. Deleting has no undo, so that button asks twice.
   The README says how each of these lands in the profile.</div>
  </details>
 </section>
 <section class="wide"><h2>Speakers on the network</h2>
  <div class="row"><button id="scan">look again</button><span class="tag" id="scansay">not looked yet</span></div>
  <table id="foundtbl"><thead><tr><th>name</th><th>what</th><th>where</th><th>members</th><th></th></tr></thead><tbody id="found"></tbody></table>
  <details class="finefold" open><summary>more info</summary>
  <div class="fine">A group's members are read back from the speakers themselves: the group record
   out on the network only names the one speaker in charge of it. A speaker that will not answer
   leaves the members unknown, which is not the same as nobody being in it.</div>
  </details>
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
 <details class="finefold" open><summary>more info</summary>
 <div class="fine">The Hijri date is tabular arithmetic, so it can sit a day either side of a
  moon sighting; <code>hijri_offset</code> in your profile lines it up with the calendar you
  follow. The day markers are decoration on the calendar, not a ruling about when anything is.</div>
 </details>
</footer>
<!-- The lamp the script turns on when an ask has been in the air long enough to wonder
     about. It never says which ask it is, because the page says that in the message line
     once the ask is answered; its whole job is answering "is anything happening?". -->
<div id="busy" role="status" hidden><span class="spin" aria-hidden="true"></span><span>still working</span></div>
<script>
let st=null;
// Which row of the outputs table is under a test right now, as far as this window knows.
// Kept out here rather than inside render, and this is the bug that cost it: the table is
// rebuilt from scratch every time anything on it answers - a level moved, "same as the
// group" pressed, a rename, the state that comes back after any ask, the minute refresh -
// and a note kept inside that function went away with the last drawing of it, which took
// the stop button off a speaker that was still playing a recitation nobody wanted. The
// daemon names the speaker it is busy with as well (st.testing), so the button is on the
// right row after a reload, in a second window, and in the moment between pressing test
// and the daemon getting the file.
let testing=null;
// What the outputs table was last drawn from. A refresh that changes nothing on this
// table now leaves it standing, which is worth the one comparison: replacing the rows
// throws away whatever the pointer was in the middle of, and a press of stop that lands
// in the moment the rows are being swapped out never reaches a button at all. A slider
// being dragged also stops jumping back to where it was drawn.
let outHTML='';
const $=s=>document.querySelector(s);
// The explanations under each card are written open in the markup and fold under one
// gold line where the window is phone-width: under that width it is the words, not the
// tables, that make a thumb scroll the page. A rotation or a resize refolds all of
// them at once, and a wide window shows the summary line nowhere at all.
const MQN=matchMedia('(max-width:620px)');
function foldFines(){ for(const d of document.querySelectorAll('details.finefold')) d.open=!MQN.matches; }
foldFines();
MQN.addEventListener('change',foldFines);
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
let waiting=0, lamp=null;
// Every promise this page makes to the daemon goes through the one door below, so one
// counter knows how many are still out there. The lamp is lit by a timer rather than by
// the request itself: most asks come back in tens of milliseconds and never show it at all,
// and only a wait long enough to wonder about - a look at the LAN, a profile being
// rewritten, a recording handed to a speaker - does. It goes out when the last one is
// answered, not the first, because two asks in the air are one wait to a person watching.
function begun(){ if(waiting++||lamp) return;
 lamp=setTimeout(()=>{ lamp=null; const b=$('#busy'); if(b) b.hidden=false; },350); }
function ended(){ if(--waiting>0) return; waiting=0;
 if(lamp){ clearTimeout(lamp); lamp=null; } const b=$('#busy'); if(b) b.hidden=true; }
async function api(path,body){
 begun();
 try{
  const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):null});
  const j=await r.json().catch(()=>({error:'bad response'}));
  if(!r.ok) throw new Error(j.error||('HTTP '+r.status));
  return j;
 } finally { ended(); }
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
// This card is the timetable: two days of every prayer is fourteen lines, and the two questions anybody asks of this
// card are "what happens next" and "what about tomorrow". So the list the daemon sends stays
// whole and the card shows one day of it: the strip above the table says which day, the two
// arrows walk it forwards and back, and every day is the same rows with nothing taken out.
// The day's name is said once in that strip instead of once on every line, which is what
// makes the first column a clock, and the occasions of a day ride beside its name there.
// The card opens on the day the household is standing in. Which day is showing then lives in
// a variable rather than coming from the clock on the wall, because this page redraws itself
// every few seconds and a card that jumped back to today in the middle of somebody reading
// tomorrow is worse than the wall it replaced; the refresh button is what starts over.
let upday=null, upall=false;
function upDays(){
 const order=[], by={};
 st.upcoming.forEach(e=>{ if(!by[e.date]){ by[e.date]=[]; order.push(e.date); } by[e.date].push(e); });
 return {order, by};
}
// The day the daemon calls today comes from the day list and not from the browser: the calls
// are made in the profile's timezone, and a browser reports whatever the phone was set to.
function upNow(){ return (st.days&&st.days[0]&&st.days[0].date)||''; }
function upToday(order){
 // Open on today, not on the first line of the list: the list can start a day back, because a
 // call that runs past midnight belongs to the evening that started it. And at eleven at night
 // today has nothing left in it, so the answer is the next day that has anything at all.
 const d=upNow();
 for(const day of order) if(day>=d) return day;
 return order[order.length-1];
}
function upMarks(date){
 const day=(st.days||[]).filter(x=>x.date===date)[0]||{};
 return (day.marks||[]).map(m=>` <span class="mark ${esc(m.kind)}">${esc(m.name)}${m.ar?` <span class="ar">${esc(m.ar)}</span>`:''}</span>`).join('');
}
function upGo(n){
 if(upall) return;                 // every day is on the page already; the arrows, and the keys, rest
 const order=upDays().order;
 if(!order.length) return;
 let i=order.indexOf(upday);
 if(i<0) i=order.indexOf(upToday(order)); // the day being shown has gone away: start from today
 i+=n;
 if(i<0 || i>=order.length) return; // the first day and the last day are the ends; nothing wraps
 upday=order[i];
 renderUp();
}
function renderUp(){
 const {order, by}=upDays();
 const prev=$('#upprev'), next=$('#upnext'), word=$('#upday'), all=$('#upalldays');
 if(!order.length){ prev.disabled=next.disabled=true; word.textContent='';
  $('#upcoming').innerHTML='<tr><td colspan=4>nothing scheduled in the next two days</td></tr>'; return; }
 if(upday===null || !by[upday]) upday=upToday(order);  // opening on today, or a reload that moved the shown day out of the list
 const i=order.indexOf(upday), rows=by[upday];
 // Every day at once is the whole list, so there is no day left to walk to: the arrows sit
 // out that view rather than moving a word nobody is looking at.
 prev.disabled=upall||i===0; next.disabled=upall||i===order.length-1;
 all.textContent=upall?'just this day':'all the days';
 // "%a %d %b %H:%M" is the shape the daemon puts in `when`: the last five characters are the
 // clock, and everything before them is the day, which the strip above the table says once,
 // with that day's occasions after it - the same pills the day headers used to carry.
 word.innerHTML=upall
  ? esc('all of it, from '+st.upcoming[0].when.slice(0,-6)+' to '+st.upcoming[st.upcoming.length-1].when.slice(0,-6))
  : esc(rows[0].when.slice(0,-6))+(upday===upNow()?' (today)':'')+upMarks(upday);
 const shown=upall?st.upcoming:rows;
 $('#upcoming').innerHTML=shown.map(e=>`<tr><td>${esc(upall?e.when:e.when.slice(-5))}</td><td>${esc(e.name)}<span class="tag">${esc(e.at)}${e.offset_min?` ${e.offset_min>0?'+':''}${e.offset_min}m`:''}</span></td><td>${esc(e.targets.join(', '))||'(none enabled)'}</td><td>${esc(e.media.concat(e.random?[e.random+' at random']:[]).join(' + '))}</td></tr>`).join('');
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
 renderUp();
 // A test is a recording that is about to come out of a real speaker, so the row that
 // sent one grows a stop button while it is going: 40 seconds into a recitation
 // nobody wanted should not have to be listened to to the end, and a speaker left
 // holding a stream that will not end should be let go. The daemon takes one test at a
 // time, which is why one name is enough to remember, and why that name comes from the
 // state rather than from a word kept inside this function: the table is redrawn from
 // scratch by every ask made from it, and a stop button that had to remember being
 // pressed used to vanish from a speaker that was still playing, the moment a level moved.
 // Under a group's row, one row per room inside it, in the same columns as the group's own
 // row: a room's slider lands under the group's slider, because it is the same kind of
 // number, and the button that takes that room's line out of the profile sits in the last
 // column with a row's other buttons. They used to be one long line, which ran past the
 // edge of the card: a name, a slider and a number is a row, and a row is what a table is
 // for. A room with a level of its own shows that number; a room without one shows the
 // group's number, because that is what it will be asked for. What each room goes back to
 // is not shown, and not because it is secret: it is nowhere written, because the daemon
 // reads it off the speaker when the call starts and hands it back when the call ends.
 const roomrow=o=>(o.rooms||[]).map(r=>`<tr class="roomrow"><td class="roomname">${esc(r.name)}</td><td class="why">${r.seen?'':'<span class="unknown">no speaker by that name out there</span>'}</td><td></td><td></td><td><input type="range" min="0" max="1" step="0.05" data-room="${esc(o.name)}" data-room-name="${esc(r.name)}" value="${r.volume==null?(o.volume==null?0.5:o.volume):r.volume}" aria-label="how loud to ask ${esc(r.name)}, inside ${esc(o.name)}, to come out at"> <span class="tag">${r.volume==null?'same as the group':Math.round(r.volume*100)+'%'}</span></td><td>${r.volume==null?'':`<button data-room-clear="${esc(o.name)}" data-room-name="${esc(r.name)}">same as the group</button>`}</td></tr>`).join('');
 const rows=st.outputs.map(o=>`<tr><td><input type="text" class="rename" data-was="${esc(o.name)}" value="${esc(o.name)}" aria-label="what this speaker is called by"></td><td>${esc(o.lead?o.kind+' ('+o.lead+'s early)':o.kind)}</td><td>${esc(o.target||o.host||'-')}</td><td><button class="switch" data-name="${esc(o.name)}" aria-checked="${o.enabled}"></button></td><td>${o.takes_volume?`<input type="range" min="0" max="1" step="0.05" data-level="${esc(o.name)}" value="${o.volume==null?0.5:o.volume}" aria-label="how loud to ask ${esc(o.name)} for"> <span class="tag">${o.volume==null?'not set':Math.round(o.volume*100)+'%'}</span>${o.target_kind=='group'?' <span class="unknown roomnote">every room inside, each back after</span>'+(o.rooms_known?'':' <span class="unknown why">no speaker would say which rooms are inside</span>'):''}`:'<span class="unknown why">not ours to ask</span>'}</td><td><button data-test="${esc(o.name)}">test</button><button data-stop="${esc(o.name)}"${(o.name===st.testing||o.name===testing)?'':' hidden'}>stop</button></td></tr>${o.target_kind=='group'?roomrow(o):''}`).join('');
 // Only redraw the table when there is something new in it. Every ask on this page ends
 // with a fresh state, and the minute refresh arrives on its own, so most drawings of it
 // are the same rows again - and each one that is not needed costs the page a table it
 // was in the middle of: a stop pressed a breath before the swap, a slider part way along
 // a drag, a name part way typed.
 if(rows!==outHTML){ outHTML=rows; $('#outputs').innerHTML=rows; }
 // A slider for a level exists only where the daemon said it may: the state's takes_volume
 // comes from the backend class, so a computer - the one running this page, or a box on the
 // LAN - has no level to move, only words saying whose it is. target_kind is what the last
 // scan of the network called that name, and a group's row spells out what its number does.
 // Measured on a real LAN, a level aimed at a group's own receiver moves a number inside it
 // that the speakers behind it ignore, so muezzin asks every room inside over a connection of
 // that room's own and hands each one back to its own level when the call ends.
 document.querySelectorAll('[data-level]').forEach(s=>s.onchange=()=>{ const out=s.dataset.level,
  level=Number(s.value), pct=Math.round(level*100); let vol=null;
  s.closest('td').querySelector('.tag').textContent=pct+'%';
  act(async()=>{ vol=await api('/api/output/volume',{name:out,volume:level}); },
   ()=>say(out+' will come out at '+pct+'% of its own scale, a test included','ok')); });
 // A room's slider writes one members: line under the group's output: that room is asked for
 // that number while a call plays, over a connection of its own, and goes back to wherever its
 // owner had left it the moment the call ends. Leaving the room - taking its line out - is the
 // only way it follows the group's number again, because there is no level that means "as it
 // was": what it was at is a fact about the room, not a choice the profile can make in advance.
 document.querySelectorAll('[data-room]').forEach(s=>s.onchange=()=>{ const out=s.dataset.room,
  room=s.dataset.roomName, level=Number(s.value), pct=Math.round(level*100);
  s.parentNode.querySelector('.tag').textContent=pct+'%';
  act(async()=>{ await api('/api/output/room',{name:out,speaker:room,volume:level}); },
   ()=>say(room+' inside '+out+' will come out at '+pct+'% while a call plays, and back to its own level afterwards','ok')); });
 document.querySelectorAll('[data-room-clear]').forEach(b=>b.onclick=()=>{ const out=b.dataset.roomClear,
  room=b.dataset.roomName;
  act(async()=>{ await api('/api/output/room',{name:out,speaker:room,volume:''}); },
   ()=>say(room+' has no level of its own again, so it is asked for what '+out+' is asked for','ok')); });
 // Only an output's switch carries data-name. A recording row uses data-hold for the
 // same look, because "let the random drawing pick this" is a different ask and needs
 // its own handler - one selector, one meaning.
 document.querySelectorAll('.switch[data-name]').forEach(b=>b.onclick=()=>act(()=>api('/api/output',{name:b.dataset.name,enabled:b.getAttribute('aria-checked')!=='true'})));
 document.querySelectorAll('[data-test]').forEach(b=>b.onclick=()=>{ const out=b.dataset.test;
  act(async()=>{ testing=out; b.nextElementSibling.hidden=false;
   // The button goes up in the same beat as the click, because the daemon has not had a
   // turn to say it yet; from the next redraw on, the row takes it from st.testing, which
   // survives the table being rebuilt underneath it. And whatever becomes of the ask,
   // this row has nothing left to stop: a test that failed part way is as finished as one
   // that played all the way through.
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
 $('#mediaurl').textContent=st.media_url?('speakers fetch audio from '+st.media_url+'; a speaker is given the address of this machine that reaches its own network'):'no media server needed by this profile';
  // A credit has to name a person, because a person is who answers questions about
  // the code. Say who you are with `attribution:` in the profile.
 $('#credit').innerHTML=`muezzin ${esc(st.version||'')} · MIT · `
  +(st.attribution?`written by ${esc(st.attribution)}, with an AI assistant`
                  :'written by whoever set this up, with an AI assistant');
 renderMethod();renderSound();renderLibrary();renderFound();renderWhere();
 syncYaml();
 $('#save').disabled=$('#reload').disabled=st.read_only;
 // The drawer's own button is not in this list, because opening it asks for nothing: a page
// that cannot write should still be able to say what a prayer will be asked for, and the
// sliders inside it are disabled the moment it is open.
document.querySelectorAll('.switch,[data-test],[data-stop],.rename,[data-level],[data-room],[data-room-clear],[data-lv-set],[data-lv-clear],[data-hold],[data-put],[data-put-go],[data-rm]').forEach(b=>b.disabled=st.read_only);
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
// Picks waiting for apply live here, not only in the boxes: a redraw puts them back where
// they were, so the levels drawer can open over a box that is dirty instead of the whole
// card refusing to change until the picks are applied. The profile does not know them yet,
// which is why renderSound alone would show the old picks.
let pend={};
// The clip box offers three kinds of thing, and one of them is the drawing: no
// named recording at all, and the prayer asks the folder for one as it fires,
// which writes `random: 1` under the event. The pool is the whole media_dir,
// holding back only what the Recordings card says not to touch, so there is
// nothing else to choose - which is why this is one more option in the box
// rather than a second box of counts beside it. Picking a named clip instead
// takes the drawing out; a prayer that wants several drawings keeps the count
// as a line to write in the profile by hand, and a row already sitting on such
// a number is shown as drawing and keeps its number when the draw is picked
// again.
function clipSelect(at,friday){
 const ev=clipFor(at,friday), pk=at+':'+(friday?1:0),
  cur=pk in pend?pend[pk]:((ev&&ev.media&&ev.media.length)?ev.media[0]:((ev&&ev.random>0)?'random':''));
 const files=(st.media_files||[]).slice();
 if(cur&&cur!=='random'&&files.indexOf(cur)<0) files.unshift(cur);
 return `<select data-at="${at}" data-friday="${friday?1:0}">`
  +[''].concat(files).concat(['random']).map(f=>`<option value="${esc(f)}"${f===cur?' selected':''}>${esc(f===''?'(no clip)':f==='random'?'(random from the library)':f)}</option>`).join('')
  +`</select>`+((ev&&ev.media&&ev.media.length>1)?` <span class="tag">${ev.media.length} clips</span>`:'')
  +((ev&&ev.offset_min)?` <span class="tag">${ev.offset_min>0?'+':''}${ev.offset_min}m</span>`:'');
}
 // What a prayer asks its speakers for lives in a drawer rather than a column, because most
 // prayers have nothing of their own to say: the summary on the row is one line however many
 // rooms the house has, and the sliders appear only for the prayer somebody is looking at.
 // The rooms come from the panel, which knows which outputs this prayer reaches and what the
 // last scan said was inside them, so no speaker name is ever typed into a box here.
function lvKey(at,friday){ return at+':'+(friday?1:0); }
function lvSum(ev){
 const moved=(ev.levels||[]).filter(r=>r.written!=null);
 if(moved.length>2) return moved.length+' rooms tuned';
 // The word "speaker" is in these names because it is what the speaker calls itself on the
 // network, and a summary is the one place on this page where that word is only in the way.
 return moved.map(r=>esc(r.name.replace(/ speaker$/i,'')+' '+Math.round(r.written*100)+'%')).join(' ');
}
function lvChip(ev,at,friday,open){
 if(!ev) return '';
 // A prayer with no rooms of its own still has a number of its own if somebody wrote one
 // under it by hand, and the summary says which of the two it is running on.
 const said=lvSum(ev)||(ev.volume==null?'as usual':'every room '+Math.round(ev.volume*100)+'%');
 return `<button class="lv" data-lv="${lvKey(at,friday)}" aria-expanded="${open===lvKey(at,friday)}"`
  +`>levels: ${said}</button>`;
}
// The figure beside a slider is what the speaker will be asked for at this prayer, and the
// figure in the second chip is what it would be asked for with nothing written here: the
// panel works both out with the same rules the backend plays by, so a person moves a slider
// knowing which of the house's numbers it covers. A name the scan cannot see stays on the
// line rather than vanishing, because a line nobody can undo has to be edited out of the
// file, and the file has no refusals in it.
function lvRow(ev,at,friday){
 const lv=ev.levels||[], lvk=lvKey(at,friday);
 if(!lv.length) return `<tr class="lvrow"><td colspan=4><div class="lvline"><span class="unknown">`
  +`nothing this prayer plays through is a speaker muezzin casts to, so there is no level for it to ask: `
  +`the level of a computer belongs to whoever is sitting at it</span></div></td></tr>`;
 return `<tr class="lvrow"><td colspan=4>`+lv.map(r=>
  `<div class="lvline"><span class="lvname">${esc(r.name)}</span>`
  +(r.output?'':' <span class="unknown">not a speaker this prayer plays through</span>')
  +(r.seen?'':' <span class="unknown">no speaker by that name out there</span>')
  +`<input type="range" min="0" max="1" step="0.05" data-lv-set="${lvk}" data-lv-name="${esc(r.name)}"`
  +` data-lv-group="${r.group?1:0}"`
  +` value="${r.written==null?r.tonight:r.written}" aria-label="how loud to ask ${esc(r.name)} for at ${esc(at)}">`
  +` <span class="tag">${r.written==null?'as usual':Math.round(r.written*100)+'%'}</span>`
  +` <span class="tag asked">${Math.round(r.tonight*100)+'% at this call'}</span>`
  +(r.written==null?'':` <button data-lv-clear="${lvk}" data-lv-name="${esc(r.name)}">same as usual</button>`)
  +`</div>`).join('')+`</td></tr>`;
}
function renderSound(){
 const box=$('#sound');
 // A box with picks waiting for apply is rebuilt like any other: the picks come back out
 // of pend above, and a levels drawer that opened on an old drawing is a drawer that lies.
 const times=(st.days&&st.days[0]&&st.days[0].times)||{};
 const open=box.dataset.open||'';
 box.innerHTML=ORDER.filter(k=>k in times).map(k=>{
  const day=clipFor(k,false), fri=clipFor(k,true);
  let row=`<tr><td>${esc(NAME[k]||k)}</td><td class="ar">${esc(AR[k]||'')}</td>`
   +`<td>${clipSelect(k,false)}${lvChip(day,k,false,open)}</td>`
   +`<td>${clipSelect(k,true)}${lvChip(fri,k,true,open)}</td></tr>`;
  if(open===lvKey(k,false)&&day) row+=lvRow(day,k,false);
  else if(open===lvKey(k,true)&&fri) row+=lvRow(fri,k,true);
  return row; }).join('')
  ||'<tr><td colspan=4>no times to put clips on</td></tr>';
 document.querySelectorAll('[data-at]').forEach(s=>s.onchange=()=>{
  box.dataset.dirty='1'; pend[s.dataset.at+':'+(s.dataset.friday==='1'?1:0)]=s.value;
  $('#soundsay').textContent='your picks are waiting for apply';
  if(st.read_only) s.disabled=true;
 });
  // A prayer's own levels are a drawer: pressed open under the prayer they belong to, holding
  // only the rooms that prayer plays through. Which one is open is kept on the table element
  // itself, because that element outlives every redraw of its rows and a drawer that closed
  // itself on the next poll would shut in someone's face while their hand was on a slider.
  document.querySelectorAll('[data-lv]').forEach(b=>b.onclick=()=>{
   const k=b.dataset.lv;
   box.dataset.open=box.dataset.open===k?'':k;
   renderSound(); });
  // One slider writes one line under this prayer, and only for the rooms touched: the rest go
  // on following the Outputs card, which is why tuning one prayer adds one line to the
  // profile rather than a paragraph. What happens afterwards is not the same two ways round,
  // and the sentence says which way: a room of a group is borrowed for the length of the call
  // and handed back over a connection of its own, while a speaker the profile points at
  // directly keeps the level it was asked for, the way its own number on the Outputs card
  // always has.
  document.querySelectorAll('[data-lv-set]').forEach(s=>s.onchange=()=>{
   const at=s.dataset.lvSet.split(':')[0], fri=s.dataset.lvSet.split(':')[1]==='1',
    room=s.dataset.lvName, level=Number(s.value), pct=Math.round(level*100);
   const ends=s.dataset.lvGroup==='1' ? ' and back to its own level when the call ends'
    : ' and it keeps that level after the call, the way a speaker of its own always does';
   s.parentNode.querySelector('.tag').textContent=pct+'%';
   s.parentNode.querySelector('.tag.asked').textContent=pct+'% at this call';
   act(async()=>{ await api('/api/event/room',{at,friday:fri,speaker:room,volume:level}); },
    ()=>say(room+' will come out at '+pct+'% for '+at+' alone,'+ends,'ok')); });
  // Taking the line out is the only way back, for the same reason it is with a room on the
  // Outputs card: where a speaker was left is a fact about the speaker, not a number this
  // profile could write down in advance.
  document.querySelectorAll('[data-lv-clear]').forEach(b=>b.onclick=()=>{
   const at=b.dataset.lvClear.split(':')[0], fri=b.dataset.lvClear.split(':')[1]==='1',
    room=b.dataset.lvName;
   act(async()=>{ await api('/api/event/room',{at,friday:fri,speaker:room,volume:''}); },
    ()=>say(room+' has no level for '+at+' of its own again, so it is asked for what the Outputs card asks','ok')); });
 $('#soundsay').textContent=box.dataset.dirty==='1'?'your picks are waiting for apply':'nothing changed';
}
function renderLibrary(){
 // The folder is the library, so this is a listing of what is on the disk rather than
 // a list of choices: each row says how big the recording is, whether the random drawing
 // may pick it, and which event it can be put on. Which events already hold its name is not said
 // over again in a column of its own: putting a recording on an event happens in this row and
 // taking it back off is a line in the profile, in the card below this one, and a delete that
 // would leave one behind is refused by the daemon,
 // which answers with the event that was in the way. The names are what matters, not
 // the paths - the daemon only ever reads one level deep in media_dir - so a row is
 // addressed by its name and the profile is written by that name too. Sizes are
 // rounded up, because a recording that reads 0 KB is a recording nobody trusts.
 const box=$('#library');
 const lib=st.media_library||[];
 const size=b=>b==null?'?':b>=1048576?(b/1048576).toFixed(1)+' MB':Math.max(1,Math.round(b/1024))+' KB';
 const rows=lib.map(f=>{
  const on=`<button class="switch" data-hold="${esc(f.name)}" aria-checked="${f.excluded?'false':'true'}"`
   +` aria-label="let the drawing pick ${esc(f.name)}"></button>`;
  // A held-back name whose file has gone has nothing to play, add or delete: there is
  // only the hold to let go, and the switch beside it is how.
  const put=f.missing?'<span class="unknown">the file is gone from the folder</span>'
   :`<select data-put="${esc(f.name)}">${(st.events||[]).map(e=>`<option>${esc(e.name)}</option>`).join('')||'<option value="">(no events yet)</option>'}</select>`
   +`<button data-put-go="${esc(f.name)}">add to</button><button data-rm="${esc(f.name)}">delete</button>`;
  return `<tr><td>${esc(f.name)}</td><td>${size(f.bytes)}</td><td>${on}</td><td>${put}</td></tr>`;
 }).join('');
 box.innerHTML=rows||`<tr><td colspan=4>nothing in ${esc(st.media_dir)} yet</td></tr>`;
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
 // One box per row now, so one row is one save; and the box says which of the
 // three things the prayer starts with, so moving between them can touch both
 // lines of the entry: picking the draw speaks about media and about drawing,
 // picking a clip usually speaks only about media.
 const picks=[...document.querySelectorAll('[data-at]')];
 let sent=0;
 for(const s of picks){
  const at=s.dataset.at, friday=s.dataset.friday==='1';
  const ev=clipFor(at,friday), all=(ev&&ev.media)||[],
   have=all[0]||((ev&&ev.random>0)?'random':'');
  if(s.value===have) continue;
  const body={at,friday};
  if(s.value==='random'){
   // The draw takes the named head away and leaves whatever sits after it: the
   // tail was put there underneath, by the Recordings card or by hand, and the
   // box only ever spoke about the front. A row already drawing keeps its own
   // number - the count is a line for the profile by hand, and visiting the
   // drawing from the box is no business of ours.
   body.media=all.slice(1);
   if(!(ev&&ev.random>0)) body.random=1;
  } else {
   // The box decides what the prayer starts with, so changing the head keeps the
   // tail: dropping the adhan for another recording must not quietly delete the
   // dua somebody placed after it. Picking a name where the row was drawing is
   // the box saying which recording, so the drawing goes with the old choice;
   // a named clip chosen in a row that hand-wrote both leaves the count alone.
   body.media=s.value?[s.value].concat(all.slice(1)):all.slice(1);
   if(have==='random') body.random=0;
  }
  await api('/api/audio',body);
  sent++;
 }
 return sent;
}
async function applyMethod(){
 const j=await api('/api/method',{preset:$('#preset').value,asr_shadow:$('#asr').value});
 return j;
}
async function uploadFile(){
 const list=[...$('#file').files];
 if(!list.length) throw new Error('choose a recording first');
 // one request per recording, in the order they were picked: the bytes are the
 // whole request, the daemon looks at what they start with before it lets them
 // anywhere near media_dir, and it needs the size before it writes anything to
 // disk, which a chunked File body does not give it. So the bytes are handed
 // over per recording rather than as one multipart body this server would only
 // refuse. A recording that is refused - a suffix that lies about its own
 // header, a name already in the folder - stands aside and the rest go on
 // coming, because nothing about one file's name says anything about the next,
 // and a household building its library out of a folder of recitations should
 // not lose eleven of them to a twelfth that turned out to be a picture.
 const added=[], refused=[];
 for(const [i,f] of list.entries()){
  // the row says where the batch got to, because a folder of recitations across
  // the wifi is a wait long enough to wonder whether anything is happening
  $('#uploadsay').textContent='adding '+(i+1)+' of '+list.length;
  try{ added.push(await uploadOne(f)); }
  catch(e){ refused.push({name:f.name, why:e.message||'the daemon said no'}); }
 }
 return {added:added, refused:refused};
}
async function uploadOne(f){
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
 // #hits, not #found: that name belongs to the speaker table below the map, and the
 // first element carrying a name is the one a page hands the write to. Sharing it drew
 // these rows over the geocoder's own box and left the speaker card alone.
 const box=$('#hits');
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
 let h='<table id="hitstbl"><tbody>';
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
// have been added or moved rooms. One exception: an output that may be asked for a
// level is only honest once the page knows whether the name behind it is one speaker
// or a group, and the network is the only thing that says which - so a page with such
// an output and no scan yet goes and looks. In the background, because a scan is ten
// seconds of broadcasts and the rest of the page has no business waiting for one, and
// only while nothing has been seen, since a target the scan did not find is a
// different answer from a group and is not chased a second time.
async function load(){ st=await api('/api/state'); if(!SC&&st.scan_at) SC=await api('/api/speakers');
 else if(!SC&&st.outputs.some(o=>o.takes_volume)) api('/api/speakers').then(r=>{ if(!r.scanning){ SC=r; renderFound(); render(); } });
 render(); }
$('#yaml').addEventListener('input',()=>{ $('#yaml').dataset.dirty='1'; });
$('#refresh').onclick=()=>act(()=>{ upday=null; });
$('#save').onclick=()=>act(()=>api('/api/config',{text:$('#yaml').value}),()=>{ $('#yaml').dataset.dirty=''; say('saved and reloaded','ok'); });
$('#reload').onclick=()=>act(()=>api('/api/reload'),()=>{ $('#yaml').dataset.dirty=''; say('reloaded from disk','ok'); });
$('#applymethod').onclick=()=>act(async()=>{ const j=await applyMethod(); note=j.still_overridden||[]; },
 ()=>say(note.length?'method written, and your own numbers are still in force: '+note.join(', ')
                   :'method written; the timetable on this page is the new one','ok'));
$('#hijminus').onclick=()=>act(()=>api('/api/hijri',{days:st.hijri_offset-1}),()=>say('the Hijri date on this page moved','ok'));
$('#hijplus').onclick=()=>act(()=>api('/api/hijri',{days:st.hijri_offset+1}),()=>say('the Hijri date on this page moved','ok'));
// The day the Events card is showing is local to this page: nothing is fetched and
// nothing is written, so these three stay live when the panel is read-only. The keyboard's
// own left and right walk the same way, but not while the cursor is inside something you
// type into - the YAML box, a speaker's name, a dropdown of an event - because an arrow key
// in one of those belongs to that control and not to this card.
$('#upprev').onclick=()=>upGo(-1);
$('#upnext').onclick=()=>upGo(1);
$('#upalldays').onclick=()=>{ upall=!upall; renderUp(); };
document.addEventListener('keydown',e=>{
 if(e.altKey||e.ctrlKey||e.metaKey) return;
 const tag=e.target&&e.target.tagName;
 if(tag==='INPUT'||tag==='SELECT'||tag==='TEXTAREA') return;
 const k=e.key;
 if(k==='ArrowLeft') upGo(-1);
 else if(k==='ArrowRight') upGo(1);
});
$('#applysound').onclick=()=>act(async()=>{ sent=await applySound(); },
 ()=>{ $('#sound').dataset.dirty=''; pend={}; say(sent?('wrote '+sent+' clip'+(sent>1?'s':'')+': the daemon reloaded with them')
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
 ()=>{ const a=up.added, bad=up.refused;
      $('#uploadsay').textContent=a.length?(a.length==1?a[0].uploaded+' in media_dir'
       :a.length+' recordings in media_dir'):'nothing in media_dir';
      say((a.length?'added '+a.map(u=>u.uploaded).join(', ')
        +(a.some(u=>u.url)?' · a speaker can reach them at the media server':''):'')
       +(bad.length?(a.length?' · not added: ':'not added: ')
        +bad.map(b=>b.name+': '+b.why).join(' · '):''), bad.length?'err':'ok');
      // the box lets go of what it was holding, so the number beside the button
      // counts what is still waiting and a second press cannot quietly offer the
      // daemon the recordings that are already in the folder
      $('#file').value=''; $('#upload').textContent='add this recording'; });
$('#file').onchange=()=>{ const n=$('#file').files.length;
 $('#upload').textContent=n>1?'add all '+n+' recordings':'add this recording'; };
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
""")
