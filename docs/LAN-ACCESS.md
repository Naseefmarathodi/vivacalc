# Fixed LAN address for VivaCalc

**Goal:** open the app as `http://myserver.local` from any PC or phone on the
office Wi-Fi, and have it keep working when DHCP moves the server's lease
anywhere inside `192.168.1.50`–`192.168.1.150`.

Nothing here exposes the app to the internet: the listener is bound to a
private address behind NAT, and the firewall rule is scoped to the local
subnet only.

---

## Read this first: pick your resolution method

Two mechanisms can give you a fixed name. They are not equivalent, and the
difference matters most on Android.

| | mDNS (`myserver.local`) | Router DNS + DHCP reservation |
|---|---|---|
| Windows 10/11 clients | ✅ built in | ✅ |
| iPhone / iPad / Mac | ✅ built in (Bonjour) | ✅ |
| **Android** | ⚠️ **unreliable** — Chrome on Android has long not resolved `.local`, and system mDNS only became dependable around Android 12 | ✅ **works on every version** |
| Linux | ✅ via avahi | ✅ |
| Needs router admin access | No | Yes |
| Survives an IP change | ✅ automatically | ✅ (the IP stops changing) |

**Recommendation: do both.** Set up mDNS (Part C) because it is quick and
needs nobody's router password. Then add the DHCP reservation and router DNS
entry (Part H) because that is what makes Android work reliably and removes
the IP churn entirely.

If you only do one, and you have router access, do **Part H**. If you have no
router access, do **Part C** and accept that some Android phones will need the
IP address instead.

---

## Part A — Django `ALLOWED_HOSTS`

Already done, in `vivacalc/settings/lan.py`. Use that module for LAN serving —
**not** `vivacalc.settings.prod`.

`ALLOWED_HOSTS` is built from the hostname plus every address in the DHCP pool:

```python
ALLOWED_HOSTS = [
    "myserver.local",   # the fixed URL
    "myserver",         # bare Windows name
    "localhost", "127.0.0.1",
    "192.168.1.50", ... "192.168.1.150",   # generated, 101 addresses
]
```

Tune the pool in `.env` without touching code:

```ini
LAN_HOSTNAME=myserver.local
DHCP_SUBNET=192.168.1
DHCP_RANGE_START=50
DHCP_RANGE_END=150
```

### Why `prod` will not work over LAN HTTP

`vivacalc.settings.prod` assumes TLS in front. Pointed at a plain-HTTP LAN it
breaks the site three ways, two of them silently:

| Setting in `prod` | Effect on `http://myserver.local` |
|---|---|
| `SECURE_SSL_REDIRECT = True` | Every request 301s to `https://myserver.local`, where nothing listens |
| `SESSION_COOKIE_SECURE = True` | Browser will not send the session cookie over http — sign-in appears to work, then does nothing |
| `SECURE_HSTS_SECONDS = 31536000` | Every browser that loads the page refuses http for that hostname **for a year**, cached per device and awkward to clear on a phone |

`settings/lan.py` turns off exactly those three and keeps everything else
(`DEBUG=False`, HttpOnly/SameSite cookies, nosniff, `X-Frame-Options: DENY`).

---

## Part B — Waitress binding

Bind to `0.0.0.0`, **not** to a specific IP. A wildcard-bound socket accepts on
whatever address the machine currently holds, so a DHCP change needs no
restart and no config edit. That single choice is what makes the rest work.

```bat
set DJANGO_SETTINGS_MODULE=vivacalc.settings.lan
set WAITRESS_HOST=0.0.0.0
set WAITRESS_PORT=80
python serve_waitress.py
```

Port 80 gives you `http://myserver.local` with no `:8000` suffix. Check nothing
already holds it — IIS, "World Wide Web Publishing Service", and some Skype
builds are the usual culprits:

```powershell
netstat -ano | findstr ":80 "
Get-Service W3SVC -ErrorAction SilentlyContinue | Stop-Service -PassThru | Set-Service -StartupType Disabled
```

If port 80 must stay free, use 8000 and the URL becomes
`http://myserver.local:8000`.

### One-time app preparation on the server

```bat
pip install -r requirements-lan.txt
python manage.py migrate --noinput
python manage.py createcachetable
python manage.py collectstatic --noinput
```

`createcachetable` is not optional: the login throttle counts attempts in the
cache, and Waitress runs multiple threads. `collectstatic` is required because
`DEBUG=False` means Django stops serving static files — WhiteNoise takes over,
but only from `STATIC_ROOT`.

---

## Part C — Windows hostname and mDNS

### C1. Name the computer `myserver`

mDNS advertises `<computer name>.local`, so the name must match the URL.

```powershell
# Run as Administrator
Rename-Computer -NewName "myserver" -Restart
```

Verify after reboot:

```powershell
hostname          # -> myserver
```

### C2. Give Windows an mDNS responder

Windows resolves `.local` names as a *client*, but does not reliably
*advertise* its own hostname. Check whether yours already does — from a Mac or
another machine on the LAN:

```bash
ping myserver.local
```

If that fails, install Apple's **Bonjour Print Services for Windows**
(`BonjourPSSetup.exe`, free from Apple's support downloads). It installs the
`Bonjour Service` (`mDNSResponder.exe`), which advertises `myserver.local` and
re-announces automatically whenever the IP changes.

Download it once on any machine with internet and copy it across — the server
itself never needs internet.

```powershell
Get-Service "Bonjour Service"          # should be Running / Automatic
```

---

## Part D — Windows Firewall

Two rules, both scoped to the private profile and the local subnet so nothing
is reachable from outside the LAN.

```powershell
# Run as Administrator

# The app itself
New-NetFirewallRule -DisplayName "VivaCalc LAN (HTTP 80)" `
  -Direction Inbound -Protocol TCP -LocalPort 80 `
  -Action Allow -Profile Private -RemoteAddress 192.168.1.0/24

# mDNS, so myserver.local resolves
New-NetFirewallRule -DisplayName "mDNS (Bonjour) inbound" `
  -Direction Inbound -Protocol UDP -LocalPort 5353 `
  -Action Allow -Profile Private -RemoteAddress 192.168.1.0/24
```

Confirm the network is classified **Private**, or Private-profile rules never
apply:

```powershell
Get-NetConnectionProfile
Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private
```

Check the rules took:

```powershell
Get-NetFirewallRule -DisplayName "VivaCalc LAN (HTTP 80)" |
  Format-List DisplayName, Enabled, Profile, Action
```

---

## Part E — Windows Service (NSSM)

If you already run VivaCalc as a service, only the environment and the start
dependency need changing — skip to E2.

### E1. Install the service

```bat
nssm install VivaCalc "C:\vivacalc\venv\Scripts\python.exe" "C:\vivacalc\serve_waitress.py"
nssm set VivaCalc AppDirectory C:\vivacalc
nssm set VivaCalc DisplayName "VivaCalc (LAN)"
nssm set VivaCalc Description "Travel booking margin ledger, served on the local network"
nssm set VivaCalc Start SERVICE_AUTO_START
```

### E2. Environment and start order

```bat
nssm set VivaCalc AppEnvironmentExtra ^
  DJANGO_SETTINGS_MODULE=vivacalc.settings.lan ^
  DJANGO_SECRET_KEY=<your-generated-key> ^
  LAN_HOSTNAME=myserver.local ^
  DHCP_SUBNET=192.168.1 ^
  DHCP_RANGE_START=50 ^
  DHCP_RANGE_END=150 ^
  WAITRESS_HOST=0.0.0.0 ^
  WAITRESS_PORT=80 ^
  DATABASE_URL=postgres://vivacalc:PASSWORD@localhost:5432/vivacalc

REM Don't start before networking and Postgres are up
nssm set VivaCalc DependOnService Tcpip Dnscache postgresql-x64-16

nssm restart VivaCalc
nssm status VivaCalc
```

Service stdout goes nowhere, so `settings/lan.py` also writes a rotating JSON
log to `C:\vivacalc\logs\vivacalc.log`. Check it first when something is wrong:

```powershell
Get-Content C:\vivacalc\logs\vivacalc.log -Tail 40 -Wait
```

---

## Part F — Testing

### On the server

```powershell
hostname                                   # myserver
ipconfig | findstr IPv4                    # note the current lease
curl http://localhost/healthz/             # ok
curl -H "Host: myserver.local" http://localhost/healthz/   # ok
```

### From another Windows PC

```powershell
ping myserver.local
nslookup myserver.local
Invoke-WebRequest http://myserver.local/healthz/ | Select-Object StatusCode
```

Then open `http://myserver.local` in a browser.

### From a Mac or iPhone/iPad

Open `http://myserver.local`. iOS resolves `.local` natively — nothing to
install.

### From Android

Try `http://myserver.local` first. If it fails to resolve — which is common on
Android 11 and earlier, and on some Chrome builds regardless of version — that
is the known mDNS gap, not a misconfiguration. Use Part H, which makes the name
resolve through the router's DNS and works on every Android version.

### Confirm you are *not* reachable from outside

From a device on mobile data (not the Wi-Fi), the address must fail. It will,
because `192.168.1.x` is not routable from the internet and no port is
forwarded — but check your router has no port-forward or UPnP mapping on 80:

```powershell
Get-NetFirewallRule -DisplayName "VivaCalc LAN (HTTP 80)" |
  Get-NetFirewallAddressFilter        # RemoteAddress must be 192.168.1.0/24
```

---

## Part G — What happens when the IP changes (`192.168.1.52` → `192.168.1.117`)

**Nothing. No action required.** Here is each layer:

| Layer | Behaviour on the change |
|---|---|
| **Waitress** | Bound to `0.0.0.0`, a wildcard socket. It accepts on any local address, including one assigned after the socket was opened. No restart, no rebind. |
| **Django `ALLOWED_HOSTS`** | Already contains every address from `.50` to `.150`. `.117` was accepted before the change happened. |
| **Bonjour / mDNS** | The responder watches for address changes and re-announces `myserver.local → 192.168.1.117` immediately. Records carry a ~120 s TTL, so stale clients correct themselves within about two minutes. |
| **Clients** | Nothing to do. A device that cached the old address recovers on its own; to force it, toggle Wi-Fi off/on, or on Windows `ipconfig /flushdns`. |
| **The URL** | `http://myserver.local` — unchanged, which was the point. |

Verified behaviour of the Django layer, by sending each `Host` header directly
at the app:

```
Host: myserver.local   -> 200    the fixed URL
Host: 192.168.1.52     -> 200    lease before
Host: 192.168.1.117    -> 200    lease after
Host: 192.168.1.50     -> 200    bottom of pool
Host: 192.168.1.150    -> 200    top of pool
Host: 192.168.1.49     -> 400    outside the pool, refused
Host: evil.example.com -> 400    host-header attack, refused
```

If the lease ever lands **outside** `.50`–`.150`, Django returns
`400 Bad Request` — deliberately. Widen `DHCP_RANGE_START` / `DHCP_RANGE_END`
in `.env` and restart the service.

---

## Part H — The robust addition: DHCP reservation + router DNS

This is what makes Android work and removes the IP churn. Ten minutes, once.

1. **Get the server's MAC address:**

   ```powershell
   Get-NetAdapter | Where-Object Status -eq Up |
     Select-Object Name, MacAddress, @{n='IPv4';e={
       (Get-NetIPAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4).IPAddress}}
   ```

2. **In the router admin page** (usually `http://192.168.1.1`), find
   *DHCP reservation* / *static lease* / *address reservation*. Bind that MAC
   to an address **outside** the dynamic pool — e.g. `192.168.1.10` — so it can
   never collide with a handed-out lease.

3. **Add a local DNS entry** if the router supports it (*Static DNS*,
   *Host entries*, *Local DNS*; OpenWrt, pfSense, ASUS, OpenWrt-based and most
   mid-range consumer routers do):

   ```
   myserver.lan  ->  192.168.1.10
   ```

4. **Tell Django about the new name and address:**

   ```ini
   # .env
   EXTRA_ALLOWED_HOSTS=myserver.lan
   EXTRA_CSRF_TRUSTED_ORIGINS=http://myserver.lan
   DHCP_RANGE_START=10      # or just widen the pool to include .10
   ```

   Restart the service.

5. Every device on the LAN now resolves `http://myserver.lan` through the
   router's DNS — no mDNS, no per-device setup, Android included. Keep
   `myserver.local` working alongside it; both names are in `ALLOWED_HOSTS`.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `DisallowedHost` / 400 | Lease is outside the configured pool | Widen `DHCP_RANGE_*` in `.env`, restart |
| Browser jumps to `https://` and fails | `settings.prod` is loaded, or HSTS was cached from an earlier `prod` run | Switch to `settings.lan`; clear HSTS (Chrome: `chrome://net-internals/#hsts` → Delete domain) |
| Sign-in never sticks | `SESSION_COOKIE_SECURE=True` over http | Use `settings.lan` |
| Page loads unstyled | `collectstatic` not run, or WhiteNoise missing | `pip install -r requirements-lan.txt` then `collectstatic --noinput` |
| Works on server, not from other PCs | Firewall rule missing, or network is Public | Part D, including `Set-NetConnectionProfile ... Private` |
| `myserver.local` fails from Android | Known Android mDNS gap | Part H |
| `myserver.local` fails from everything | Bonjour not running | `Get-Service "Bonjour Service"` |
| Works, then fails after reboot | Service started before the network | `nssm set VivaCalc DependOnService Tcpip Dnscache` |
| Throttle locks out too fast | Per-process cache instead of shared | `python manage.py createcachetable` |
