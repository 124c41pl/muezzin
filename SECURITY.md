# Security

muezzin drives speakers in a house. That is the shape of its security story, so
this page starts with the model rather than a list of CVEs.

## The model, stated plainly

**There is no authentication, on purpose.** A prayer-time daemon that needs an
account, a token and a password reset flow is a daemon nobody runs. The port the
page listens on is one more open port on your LAN, in the same company as your
printer's admin page and your router's. What that means:

* **Anyone who can reach the port can run the app.** They can change the Fajr
  method, queue a clip through your speakers at 3 a.m., delete an output and
  upload a file. The panel is not a hostile-witnessing interface; it is a control
  panel for a household.
* **The profile file is the credential.** Whoever can write `muezzin.yaml` can
  point the daemon at any speaker on the network, name any directory under
  `out_dir`, and set any media file. Protect the file the way you would protect a
  config with a password in it.
* **The trust boundary is the network segment.** Run it on a network you already
  trust for printers, smart bulbs and Chromecasts. If you do not trust that
  network — a shared flat, a workplace — do not run it there, or firewall the
  ports to a single address.

## What is defended against, even inside that model

Not because the threats are exotic, but because a bug here can write files or
play audio, so the boring attacks are worth closing:

* **DNS rebinding against the panel.** The page refuses requests whose `Host`
  header is not an address it is actually answering on — 403, with a sentence
  saying so. That is what stops a web page on your laptop from pointing you at
  `http://192.168.0.5:8020/…` through a DNS name that expires mid-request.
  A `--allow-host` list exists for the reverse case: a name you do want it to
  answer.
* **Cross-site requests and non-browser clients.** `Origin` and `Sec-Fetch-Site`
  are checked, and writes require the JSON content type the page sends. This is a
  *browser* guard: it stops another web page from quietly driving your panel. It
  is not access control, and it is not presented as such.
* **Reading outside the media folder, writing outside the output folder.** Paths
  are contained after resolution, case-insensitively on Windows. A `kind: file`
  output may only write inside `out_dir`. The media server refuses to list its
  directory.
* **Uploads that are not what they claim to be.** The first bytes decide, not the
  suffix; a file that would overwrite an existing one is refused; a body over the
  cap is drained and answered with 413 rather than left half-read.
* **YAML that is hostile rather than wrong.** Aliases and merge keys (`*name`,
  `<<:`) are refused before parsing, and a request body is capped at 64 KB — an
  anchor-expansion bomb cannot become a 4 GB string or eat the whole disk. Only
  `safe_load` is ever used.
* **The page corrupting its own config.** The YAML on disk is the source of truth.
  Every write goes through a temp file, a full `load_profile` validation of that
  temp file, and only then `os.replace`, all under one lock, so a saved file is
  never a half-applied edit and two people saving at once cannot lose each
  other's change.
* **A box that will fetch audio from anywhere.** `muezzin box` refuses URLs whose
  host is not on its `--allow-host` list (a leading dot means subdomains), refuses
  chunked bodies, caps size and count per play, and never runs a shell command
  with a filename in it.
* **A speaker that is lying about being a group.** Group membership is measured by
  asking each physical speaker over its Dial endpoint, not by trusting the group
  record; "no answer" is kept distinct from "no members".
* **Docker defaults.** The image starts `muezzin daemon --web 8020 --read-only`.
  Writing from the page inside a container takes an explicit `command:` override.

## What is *not* defended against

Saying this out loud is part of the design:

* an attacker who is already on your LAN and can spoof mDNS — a rogue
  `_googlecast._tcp` announcement can send your adhan to a speaker they chose;
* a profile file someone else wrote (see above: the file is the credential);
* content you choose to play, from URLs you choose to put in the profile;
* anyone on the LAN who can hear the speakers, or who can put their own Chromecast
  into a group you discovered;
* the media server's limits as a defence — it serves whatever is in `media_dir` to
  anything that can reach the port, and it does not support `Range`, TLS or
  authentication.

## Hardening, if your network is not one you trust

* `--read-only` for a panel that should never write;
* `--allow-host` on a box, so it only ever fetches from the daemon you named;
* a firewall rule scoping `8020` and the media port to the daemon's own address;
* a separate VLAN for speakers is the usual fix, and it costs nothing here.

## Reporting a problem

Report something exploitable as a **private security advisory**: open
`https://github.com/124c41pl/muezzin/security/advisories/new` (Security tab →
*Report a vulnerability*). That reaches the maintainers without showing the
problem to the world, and the thread can be published as an advisory once there
is a fix in a release.

Please do not open a plain public issue for anything that is exploitable: a bug
in a daemon that opens a port and writes files is easier to fix before it is
advertised. A bug that cannot be used against anyone — a wrong prayer time, a
speaker that misbehaves, a crash — is worth a public issue at
`https://github.com/124c41pl/muezzin/issues`, because the fix and the discussion
then help the next person who hits it.

Either way, say what version (`muezzin --version`), what you ran, and what you
expected instead. There is no bug bounty and no signed advisory process — just a
person who will fix it and put the fix in a release.
