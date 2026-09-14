# MySQL on Windows for VivaCalc

Run these on the Windows PC, from `C:\apps\vivacalc`, with the venv active
(`venv\Scripts\activate.bat` — your prompt should read `(venv)`).

> **Version requirement: MySQL 8.0.16 or newer.**
> VivaCalc has a database CHECK constraint that stops a booking being saved
> with a negative buy or sell price. MySQL only *enforces* CHECK constraints
> from 8.0.16; earlier versions parse and silently ignore them. On an older
> server the migration still succeeds, so you get no warning — the guarantee
> just isn't there. Confirm your version in Part 3.

---

## Part 1 — Install the MySQL server

```bat
winget install --id Oracle.MySQL --accept-package-agreements
```

If `winget` is unavailable, download the **MySQL Installer for Windows** from
<https://dev.mysql.com/downloads/installer/> and choose *Server only* (or
*Custom* → MySQL Server + MySQL Workbench if you want a GUI).

During setup:

| Prompt | Choose |
|---|---|
| Config Type | **Development Computer** |
| Port | **3306** (the default) |
| Authentication Method | **Use Strong Password Encryption** |
| Root password | Pick a strong one and record it — you cannot recover it |
| Windows Service | **Yes**, name `MySQL80`, start automatically |

Verify the service is running:

```bat
sc query MySQL80
```

Add the MySQL tools to this session's PATH (adjust the version folder if
different):

```bat
set PATH=%PATH%;C:\Program Files\MySQL\MySQL Server 8.0\bin
mysql --version
```

To make that permanent: System Properties → Environment Variables → edit
**Path** → add `C:\Program Files\MySQL\MySQL Server 8.0\bin`.

---

## Part 2 — Create the database and user

```bat
mysql -u root -p
```

Enter the root password, then at the `mysql>` prompt:

```sql
CREATE DATABASE vivacalc
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'vivacalc'@'localhost' IDENTIFIED BY 'choose-a-strong-password';

GRANT ALL PRIVILEGES ON vivacalc.* TO 'vivacalc'@'localhost';

FLUSH PRIVILEGES;
EXIT;
```

**`utf8mb4` is not optional.** MySQL's older `utf8` is a 3-byte encoding that
cannot store 4-byte characters. Without `utf8mb4` the rupee sign (₹) used
throughout the UI, and any non-Latin passenger name, will be corrupted or
rejected. Django also needs `utf8mb4` to grant the test runner the right
collation.

The app user deliberately has rights on `vivacalc.*` only — never use `root`
as the application account.

Django's test suite creates and drops a `test_vivacalc` database, so if you
want `manage.py test` to work here, also grant:

```sql
GRANT ALL PRIVILEGES ON `test_vivacalc`.* TO 'vivacalc'@'localhost';
FLUSH PRIVILEGES;
```

---

## Part 3 — Check the server version

```bat
mysql -u vivacalc -p -e "SELECT VERSION();"
```

- **8.0.16 or newer** → the price constraint is enforced. Good.
- **Older than 8.0.16** → the constraint is accepted but ignored. The
  application still rejects negative prices (the form validates, and
  `TravelBooking.save()` computes the margin), but the database will not be a
  second line of defence. Upgrading is the fix.

---

## Part 4 — Install the Python driver

```bat
pip install mysqlclient==2.2.7
```

This has prebuilt wheels for Python 3.12 on 64-bit Windows, so it installs
without a compiler. If it tries to build from source and fails with
*"Microsoft Visual C++ 14.0 or greater is required"*, you are on a Python
version with no wheel — use Python 3.12.

Also edit `requirements-lan.txt`: comment out the `psycopg[binary]` line and
uncomment the `mysqlclient` line, so future installs on other machines match.

---

## Part 5 — Point VivaCalc at MySQL

Add to `C:\apps\vivacalc\.env`:

```ini
DATABASE_URL=mysql://vivacalc:choose-a-strong-password@localhost:3306/vivacalc
```

If the password contains `@ : / ? # & %` or a space, **percent-encode it** or
the URL will be misparsed. Common ones:

| Character | Write as |
|---|---|
| `@` | `%40` |
| `:` | `%3A` |
| `/` | `%2F` |
| `#` | `%23` |
| `%` | `%25` |
| space | `%20` |

So `p@ss!word` becomes `p%40ss%21word`. Confirm it decoded correctly:

```bat
python -c "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','vivacalc.settings.lan');django.setup();from django.conf import settings;d=settings.DATABASES['default'];print(d['ENGINE']);print(d['NAME'],d['USER'],d['HOST'],d['PORT']);print(d['OPTIONS'])"
```

Expected:

```
django.db.backends.mysql
vivacalc vivacalc localhost 3306
{'charset': 'utf8mb4', 'init_command': "SET sql_mode='STRICT_TRANS_TABLES'"}
```

`STRICT_TRANS_TABLES` is set by VivaCalc on every connection. Without it MySQL
silently truncates over-long values and coerces bad numbers to `0` instead of
raising — the last behaviour you want in a ledger that stores money.

---

## Part 6 — Create the schema

```bat
python manage.py migrate
python manage.py createcachetable
python manage.py createsuperuser
python manage.py collectstatic --noinput
```

Confirm the tables exist:

```bat
mysql -u vivacalc -p vivacalc -e "SHOW TABLES;"
```

You should see `adminpanel_customuser`, `adminpanel_portal`,
`adminpanel_travelbooking`, `vivacalc_cache`, plus Django's own tables.

---

## Part 7 — Load your existing data

Copy `transfer\vivacalc-data.json` from the Mac to `C:\apps\vivacalc\transfer\`
(by hand — it holds password hashes and is deliberately not in git), then:

```bat
python manage.py loaddata transfer\vivacalc-data.json
```

Check it arrived:

```bat
mysql -u vivacalc -p vivacalc -e "SELECT COUNT(*) AS users FROM adminpanel_customuser; SELECT COUNT(*) AS bookings FROM adminpanel_travelbooking;"
```

Expect 5 users and 9 bookings. Everyone's existing password still works.

---

## Part 8 — Verify money survives the round trip

Decimal handling is the thing most worth checking after a database change:

```bat
python manage.py shell -c "from decimal import Decimal; from adminpanel.models import TravelBooking; from django.db.models import Sum; print('rows:', TravelBooking.objects.count()); print('margin total:', TravelBooking.objects.aggregate(t=Sum('margin'))['t']); b=TravelBooking.objects.first(); print('exact:', b.margin == b.sell_price - b.buy_price, type(b.margin).__name__)"
```

`exact: True` and `Decimal` are what you want. MySQL's `DECIMAL` is exact, so
the totals on screen, in Excel and in the PDF continue to agree.

Then run the suite against MySQL:

```bat
python manage.py test
```

This needs the `test_vivacalc` grant from Part 2.

---

## Part 9 — Back it up

SQLite was one file you could copy. MySQL is not, so set up a dump. Create
`C:\apps\vivacalc\backup.bat`:

```bat
@echo off
set STAMP=%DATE:~-4%%DATE:~3,2%%DATE:~0,2%
"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe" ^
  -u vivacalc -pchoose-a-strong-password ^
  --single-transaction --routines --triggers ^
  vivacalc > C:\apps\vivacalc\backups\vivacalc-%STAMP%.sql
```

```bat
mkdir C:\apps\vivacalc\backups
```

Schedule it daily:

```powershell
schtasks /create /tn "VivaCalc backup" /tr "C:\apps\vivacalc\backup.bat" /sc daily /st 22:00
```

The password is in that file, so restrict it:

```powershell
icacls C:\apps\vivacalc\backup.bat /inheritance:r /grant:r "Administrators:F" "SYSTEM:F"
```

Restore with:

```bat
mysql -u vivacalc -p vivacalc < C:\apps\vivacalc\backups\vivacalc-20260914.sql
```

---

## Part 10 — Service start order

If VivaCalc runs as a Windows Service, it must not start before MySQL:

```bat
nssm set VivaCalc DependOnService Tcpip Dnscache MySQL80
nssm restart VivaCalc
```

Without this, a reboot can start the app first, and it fails to connect.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Error loading MySQLdb module` | Driver not installed, or venv not active | `venv\Scripts\activate.bat` then `pip install mysqlclient==2.2.7` |
| `Access denied for user 'vivacalc'@'localhost'` | Wrong password, or user not created | Re-run the `CREATE USER` / `GRANT` from Part 2 |
| `Can't connect to MySQL server on 'localhost'` | Service stopped | `sc query MySQL80`, then `net start MySQL80` |
| `Unknown database 'vivacalc'` | Database not created | Part 2 `CREATE DATABASE` |
| `Incorrect string value: '\xE2\x82\xB9'` | Database is not utf8mb4 (that byte sequence is ₹) | `ALTER DATABASE vivacalc CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;` |
| `Data truncated for column` | Good — strict mode caught bad data | Fix the input; do not disable strict mode |
| Negative prices accepted | MySQL older than 8.0.16 ignores CHECK constraints | Upgrade MySQL; app-level validation still applies |
| `manage.py test` fails on permissions | No grant on `test_vivacalc` | Part 2, second grant block |
| Migration fails on index length | Very old MySQL with `utf8` not `utf8mb4` | Recreate the database per Part 2 |
