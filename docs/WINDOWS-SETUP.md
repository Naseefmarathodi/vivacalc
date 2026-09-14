# Installing VivaCalc on a Windows PC

Target: the Windows machine at `192.168.1.66`, serving the app to the office
LAN. Source: <https://github.com/Naseefmarathodi/vivacalc>

Everything below is run **on the Windows PC** unless it says *(on the Mac)*.

> **Before you start:** the GitHub repository is **public**. Never commit
> `.env`, `db.sqlite3`, or anything containing a password — `.gitignore`
> already excludes them, and the checks below confirm it.

---

## Part 1 — Install Python

Open **PowerShell as Administrator** (Start → type `powershell` → right-click →
*Run as administrator*).

```powershell
winget install --id Python.Python.3.12 --source winget --accept-package-agreements
```

If `winget` is unavailable (older Windows 10), download from
<https://www.python.org/downloads/windows/> and **tick "Add python.exe to
PATH"** on the first installer screen — that checkbox causes more setup
failures than anything else here.

Close and reopen PowerShell, then verify:

```powershell
python --version      # Python 3.12.x
pip --version
```

If `python` opens the Microsoft Store instead, the App Execution Alias is
intercepting it: Settings → Apps → Advanced app settings → App execution
aliases → turn **off** both `python.exe` and `python3.exe`.

> Python 3.12 is recommended over 3.13/3.14 on Windows: every dependency here
> ships prebuilt wheels for it, so nothing needs a C compiler.

---

## Part 2 — Install Git

```powershell
winget install --id Git.Git --source winget --accept-package-agreements
```

Reopen PowerShell and check:

```powershell
git --version
```

Set your identity (used if you ever commit from this machine):

```powershell
git config --global user.name "Mohammed Naseef"
git config --global user.email "naseefmarathodi@gmail.com"
```

---

## Part 3 — Get the code

```powershell
mkdir C:\apps -Force
cd C:\apps
git clone https://github.com/Naseefmarathodi/vivacalc.git
cd C:\apps\vivacalc
```

`C:\apps\vivacalc` is now the project root. Avoid `C:\Program Files` (needs
admin rights for every write) and avoid OneDrive-synced folders (file locking
breaks the dev server).

---

## Part 4 — Create the virtual environment

```powershell
cd C:\apps\vivacalc
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If activation fails with *"running scripts is disabled on this system"*:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\venv\Scripts\Activate.ps1
```

Your prompt should now start with `(venv)`. Confirm it is the *project's*
Python, not the system one:

```powershell
where.exe python        # first line must be C:\apps\vivacalc\venv\Scripts\python.exe
```

Install the dependencies:

```powershell
python -m pip install --upgrade pip
pip install -r requirements-lan.txt
```

That pulls Django, openpyxl, reportlab, Pillow, waitress, whitenoise and the
PostgreSQL driver. Verify:

```powershell
python -c "import django, waitress, whitenoise, openpyxl, reportlab; print(django.get_version())"
```

---

## Part 5 — Create the `.env` file

`.env` is **not** in the repository — it holds secrets, so each machine gets
its own. Generate a fresh secret key (do **not** reuse the Mac's):

```powershell
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Create `C:\apps\vivacalc\.env` with Notepad:

```powershell
notepad .env
```

Paste this, substituting the key you just generated and your Gmail app
password:

```ini
DJANGO_SECRET_KEY=<paste the generated key here>
DJANGO_SETTINGS_MODULE=vivacalc.settings.lan
DEBUG=False
TIME_ZONE=Asia/Kolkata
LOG_LEVEL=INFO

# Fixed LAN hostname and the DHCP pool this server's lease moves inside
LAN_HOSTNAME=myserver.local
DHCP_SUBNET=192.168.1
DHCP_RANGE_START=50
DHCP_RANGE_END=150

# Waitress
WAITRESS_HOST=0.0.0.0
WAITRESS_PORT=80
WAITRESS_THREADS=8

# Sign-in / sign-out notifications
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=visa.vivaholidaysvga@gmail.com
DEFAULT_FROM_EMAIL=visa.vivaholidaysvga@gmail.com
EMAIL_HOST_PASSWORD=<gmail app password>

AUTH_NOTIFY_ENABLED=True
AUTH_NOTIFY_RECIPIENTS=vivaholidaysvga@gmail.com,noorunv@gmail.com
AUTH_NOTIFY_ON_LOGIN=True
AUTH_NOTIFY_ON_LOGOUT=True
AUTH_NOTIFY_USER_TOO=False
```

Notepad saves as `.env.txt` by default. In the Save dialog set **Save as
type: All Files** and the name to `.env`. Check it landed correctly:

```powershell
Get-ChildItem -Force .env      # must be exactly ".env", not ".env.txt"
```

---

## Part 6 — Database

### Option A: SQLite (simplest — start here)

Nothing to install. Leave `DATABASE_URL` unset and skip to Part 7.

Fine for a handful of staff. Its limit is concurrent *writes*: SQLite takes a
database-wide lock, so two people saving a booking at the same instant can
produce *"database is locked"*.

### Option B: PostgreSQL (recommended once more than 2–3 people use it)

```powershell
winget install --id PostgreSQL.PostgreSQL.16 --accept-package-agreements
```

Note the superuser password you set during installation. Then create the
database and role:

```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE DATABASE vivacalc;"
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE USER vivacalc WITH PASSWORD 'choose-a-strong-password';"
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE vivacalc TO vivacalc;"
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -d vivacalc -c "GRANT ALL ON SCHEMA public TO vivacalc;"
```

Add to `.env`:

```ini
DATABASE_URL=postgres://vivacalc:choose-a-strong-password@localhost:5432/vivacalc
```

---

## Part 7 — Initialise the application

```powershell
cd C:\apps\vivacalc
.\venv\Scripts\Activate.ps1

python manage.py migrate --noinput
python manage.py createcachetable
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

All four matter:

| Command | Why it is not optional |
|---|---|
| `migrate` | Creates the tables |
| `createcachetable` | The login throttle counts attempts in the cache; Waitress runs many threads, so it must be shared |
| `collectstatic` | `DEBUG=False` stops Django serving static files; WhiteNoise serves them from `STATIC_ROOT` |
| `createsuperuser` | Otherwise nobody can sign in |

Confirm the configuration is sane:

```powershell
python manage.py check
python manage.py test
```

---

## Part 8 — Bring your existing data across (optional)

The database is deliberately **not** in git, so the Windows PC starts empty.
To carry over the 5 users, 2 portals and 9 bookings from the Mac:

*(on the Mac)* the export already exists at `transfer/vivacalc-data.json`. To
regenerate it:

```bash
./venv/bin/python manage.py dumpdata \
  adminpanel.CustomUser adminpanel.Portal adminpanel.TravelBooking \
  --indent 2 --output transfer/vivacalc-data.json
```

Copy that file to `C:\apps\vivacalc\transfer\` — over the network share, a USB
stick, or email. **Do not commit it**: it contains password hashes, and
`transfer/` is gitignored for that reason.

Then on Windows:

```powershell
python manage.py loaddata transfer\vivacalc-data.json
```

Passwords come across intact, so everyone signs in with their existing one.

---

## Part 9 — Run it

### First, a quick check

```powershell
python manage.py runserver 8000
```

Open <http://127.0.0.1:8000/> on the Windows PC itself. Sign in. Then stop it
with `Ctrl+C` — `runserver` is a development server and must not serve real
traffic.

### Then the real server

```powershell
python serve_waitress.py
```

This binds `0.0.0.0:80`, so the app answers on whatever IP the machine holds —
which is what keeps the address stable when DHCP moves the lease.

If port 80 is taken (IIS, "World Wide Web Publishing Service", some Skype
builds):

```powershell
netstat -ano | findstr ":80 "
Get-Service W3SVC -ErrorAction SilentlyContinue | Stop-Service -PassThru | Set-Service -StartupType Disabled
```

Or set `WAITRESS_PORT=8000` in `.env` and use `http://myserver.local:8000`.

---

## Part 10 — Firewall

```powershell
# Run as Administrator
New-NetFirewallRule -DisplayName "VivaCalc LAN (HTTP 80)" `
  -Direction Inbound -Protocol TCP -LocalPort 80 `
  -Action Allow -Profile Private -RemoteAddress 192.168.1.0/24

New-NetFirewallRule -DisplayName "mDNS (Bonjour) inbound" `
  -Direction Inbound -Protocol UDP -LocalPort 5353 `
  -Action Allow -Profile Private -RemoteAddress 192.168.1.0/24
```

Both rules are scoped to the local subnet and the Private profile, so nothing
is reachable from outside the LAN. Make sure the network *is* classified
Private, or Private-profile rules never apply:

```powershell
Get-NetConnectionProfile
Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private
```

Test from another device: `http://192.168.1.66`

---

## Part 11 — Fixed hostname and running as a service

For `http://myserver.local` instead of the IP, and for starting automatically
at boot, follow **[LAN-ACCESS.md](LAN-ACCESS.md)** — Parts C (hostname and
mDNS) and E (NSSM Windows Service).

Summary of the service setup:

```bat
winget install --id NSSM.NSSM
nssm install VivaCalc "C:\apps\vivacalc\venv\Scripts\python.exe" "C:\apps\vivacalc\serve_waitress.py"
nssm set VivaCalc AppDirectory C:\apps\vivacalc
nssm set VivaCalc Start SERVICE_AUTO_START
nssm set VivaCalc DependOnService Tcpip Dnscache
nssm start VivaCalc
```

---

## Part 12 — Updating later

On the Mac, after making changes:

```bash
git add -A
git commit -m "describe the change"
git push
```

On the Windows PC:

```powershell
cd C:\apps\vivacalc
.\venv\Scripts\Activate.ps1

git pull
pip install -r requirements-lan.txt      # only if dependencies changed
python manage.py migrate --noinput
python manage.py collectstatic --noinput
nssm restart VivaCalc                    # or restart serve_waitress.py
```

`git pull` never touches `.env`, `db.sqlite3` or `logs/` — they are gitignored,
so local configuration and data survive every update.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `'python' is not recognized` | PATH checkbox missed at install | Reinstall with "Add python.exe to PATH", or use the full path |
| `python` opens Microsoft Store | App execution alias | Settings → Apps → Advanced → App execution aliases → turn off `python.exe` |
| `Activate.ps1 cannot be loaded` | PowerShell execution policy | `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| `ImproperlyConfigured: DJANGO_SECRET_KEY` | `.env` missing, or saved as `.env.txt` | `Get-ChildItem -Force .env` and rename |
| `DisallowedHost` / 400 | Lease outside the configured pool | Widen `DHCP_RANGE_*` in `.env`, restart |
| Page loads with no styling | `collectstatic` not run | `python manage.py collectstatic --noinput` |
| Browser forces `https://` | `settings.prod` loaded instead of `lan` | Check `DJANGO_SETTINGS_MODULE=vivacalc.settings.lan` |
| Sign-in never sticks | Same cause as above | Same fix |
| Works locally, not from other PCs | Firewall rule missing, or network is Public | Part 10 |
| No notification emails | `EMAIL_BACKEND` or `EMAIL_HOST_PASSWORD` missing from `.env` | `python manage.py test_auth_email` prints exactly what is wrong |
| `database is locked` | Concurrent writes on SQLite | Move to PostgreSQL (Part 6B) |
| Service won't start after reboot | Started before the network | `nssm set VivaCalc DependOnService Tcpip Dnscache` |
