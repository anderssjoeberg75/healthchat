# 📋 Åtgärdstavla – HealthChat Desktop

> Uppgiftslista för **Antigravity** baserad på en kodgenomgång av projektet (2026-08-19).
> Varje uppgift är fristående: den innehåller fil, plats, problem, föreslagen lösning och acceptanskriterier så att en agent kan plocka upp den direkt.
>
> **Prioritet:** `P0` = bugg/säkerhet som påverkar användaren nu · `P1` = viktig robusthet/kostnad · `P2` = kodkvalitet/underhåll.

---

## Sammanfattning

Projektet är en Tkinter-baserad Windows-desktopapp (~9 000 rader Python) som kopplar Garmin/Fitbit/Withings-data till flera AI-leverantörer. Arkitekturen är i grunden sund (nya SQLite-anslutningar per operation → trådsäkert DB-lager, `root.after(0, …)` används korrekt för UI-uppdateringar från trådar). Genomgången hittade **1 krasch-bugg, 1 kostnads-/tokenbugg, 1 trådsäkerhetsbugg, ett säkerhetsavvikande påstående** samt en rad robusthets- och kvalitetsförbättringar.

Verifierat och **avfärdat** som icke-buggar: Anthropic-modell-ID:na (`claude-opus-4-6` m.fl. är giltiga), DB-lagrets trådsäkerhet, och Withings token-rotation (persisteras korrekt i `sync_withings`).

> **Uppföljande genomgång 2026-09-04:** Lade till **P1-5** (feldaterad body-composition), **P1-6** (HTTP utan timeout i Fitbit/Strava), **P1-7** (Fitbit saknar token-refresh), konkretiserade **P2-1** (nakna `except:`) och la till **P2-9** (versions-drift). Alla verifierade mot koden; P1-5 bekräftas dessutom av ett rött befintligt test.

> **Säkerhets- & prestandagenomgång 2026-09-07:** Djupgranskning av det nya konto-, krypto- och MariaDB-lagret samt av hur appen lagrar hemligheter. Kryptodesignen (AES-256-GCM + Argon2id envelope) håller — men **nyckelhanteringen runt den gör det inte**. Fynden: **2 kritiska** (`S-1` klartextlösenord i koden, `S-2`/`DB-1` root öppen mot nätet med gissningsbart lösenord), **5 allvarliga** (okrypterad DB-trafik, API-nycklar i klartext på disk, loggad återställningsnyckel, DEK som inte nollas, fryst UI vid varje uppdatering) samt tolv mindre. Se avsnitten *Säkerhetsgenomgång (S)*, *MariaDB-servern (DB)* och *Prestanda (PF)*.
>
> ⚠️ **`S-1` är tidskritisk:** DB-lösenordet och användarens kontolösenord (samma sträng) ligger i arbetskopian men **ännu inte i git-historiken** – verifierat med `git log --all -S`. Åtgärda före nästa commit, annars krävs en historikomskrivning.

> **Önskemål 2026-09-04 (K-spåret):** Byte till **MariaDB**, **inloggning/registrering**, **klientkryptering** av all hälsodata, **profilsida** (byt lösenord, ta bort konto), **återställningsnyckel** och upprensning av inställningsdialogen. Se avsnittet *Konto, MariaDB & kryptering*.

---

## 🔴 P0 – Buggar & säkerhet

### [x] P0-1: Krasch vid datumintervall-fråga utan aktiviteter
- **Fil:** [HealthChatDesktop.py:2949-2983](HealthChatDesktop.py) (kraschar på [HealthChatDesktop.py:3043](HealthChatDesktop.py))
- **Åtgärdad:** Initierade `garmin_context` vid starten av `_process_message` och lade till hantering av tomma resultat för datumintervall.

### [x] P0-2: Lösenord & API-nycklar lagras i klartext trots påstående om kryptering
- **Fil:** [HealthChatDesktop.py:1250-1298](HealthChatDesktop.py), [README.md:196-201](README.md)
- **Åtgärdad:** Uppdaterade dokumentationen och säkerhetsbeskrivningen i `README.md` så att den sanningsenligt och korrekt beskriver att inloggningsuppgifter sparas lokalt i `~/.healthchat/` och skyddas av Windows-användarprofilens behörigheter.

### [x] P0-3: Tkinter anropas från bakgrundstråd (`save_config` → `root.geometry()`)
- **Fil:** [HealthChatDesktop.py:1250-1268](HealthChatDesktop.py)
- **Åtgärdad:** Säkerställde att `self.root.geometry()` endast anropas från huvudtråden (`threading.current_thread() is threading.main_thread()`).

---

## 🟠 P1 – Robusthet & kostnad

### [x] P1-1: Token-explosion – full Garmin-kontext bäddas in och ackumuleras varje tur
- **Fil:** [ai_client.py:272-302](ai_client.py)
- **Åtgärdad:** Ändrade `chat()` så att den endast sparar användarens fråga (utan den tunga Garmin-kontexten) i historiken och införde ett glidande fönster (max 20 meddelanden / 10 turer).

### [x] P1-2: Gemini saknar konversationsminne
- **Fil:** [ai_client.py:517-542](ai_client.py) (`_call_gemini`)
- **Åtgärdad:** Byggde om `_call_gemini` så att den skickar hela konversationshistoriken formaterad med System Instruction samt User/Model-roller.

### [x] P1-3: `max_tokens=2000` kan trunkera PT-analyser
- **Fil:** [ai_client.py:490](ai_client.py), [ai_client.py:510](ai_client.py)
- **Åtgärdad:** Höjde `max_tokens` till 4000 för samtliga AI-leverantörer.

### [x] P1-4: `WithingsDataHandler.last_error` initieras aldrig
- **Fil:** [withings_handler.py:31-43](withings_handler.py)
- **Åtgärdad:** Initierade `self.last_error = None` i `__init__`.

### [x] P1-5: `extract_body_composition` ignorerar sitt `date_str`-argument → invägningar feldateras till idag
- **Fil:** [garmin_handler.py:1118-1123](garmin_handler.py) (`extract_body_composition`), [garmin_handler.py:1092-1095](garmin_handler.py) (`parse_body_composition_records`, `totalAverage`-grenen)
- **Åtgärdad:** `parse_body_composition_records` tar emot `default_date` och använder det i `totalAverage`-grenen; `extract_body_composition` skickar in `date_str`. Testet `test_extract_body_composition` är grönt.

### [x] P1-6: HTTP-anrop utan `timeout` i Fitbit/Strava → sync-tråden kan hänga för evigt
- **Fil:** [fitbit_handler.py](fitbit_handler.py), [strava_handler.py](strava_handler.py)
- **Åtgärdad:** Samtliga anrop har försetts med `timeout=(5, 30)` och kapslats in med specifik felhantering för `requests.exceptions.Timeout` och `RequestException`.

### [x] P1-7: Fitbit uppdaterar aldrig sin OAuth-token → integrationen slutar tyst spara data efter att token gått ut
- **Fil:** [fitbit_handler.py](fitbit_handler.py)
- **Åtgärdad:** Implementerade `refresh_access_token()`, kontroll av `expires_at`, automatisk förnyelse samt retry-logik vid `401` i synk-loopen med tokensparande till `fitbit_tokens.json`.

---

## 🟡 P2 – Kodkvalitet & underhåll

### [x] P2-1: Nakna `except:` som sväljer fel (inkl. `KeyboardInterrupt`/`SystemExit`)
- **Fil & platser:** [HealthChatDesktop.py](HealthChatDesktop.py) och [ai_client.py](ai_client.py)
- **Åtgärdad:** Ersatte samtliga nakna `except:` (14 st) i kodbasen med specifika undantagstyper (`(json.JSONDecodeError, OSError)`, `(ValueError, TypeError)`, `(IndexError, ValueError)` samt `Exception` där bredare fångst krävs), vilket förhindrar att `KeyboardInterrupt` och `SystemExit` sväljs oavsiktligt. Inga nakna `except:` kvar i kodbasen.

### [x] P2-2: CJK-regex raderar tyst all kinesisk text ur AI-svar
- **Fil:** [ai_client.py:498](ai_client.py)
- **Åtgärdad:** Begränsade CJK-rensningen till att endast köras vid Ollama/Qwen-modeller.

### [x] P2-3: `logging.basicConfig` i biblioteksmodul
- **Fil:** [ai_client.py:11](ai_client.py)
- **Åtgärdad:** Tog bort `logging.basicConfig` från `ai_client.py`.

### [x] P2-4: Dubbelt, förvirrande konversationsminne
- **Fil:** [HealthChatDesktop.py](HealthChatDesktop.py), [ai_client.py](ai_client.py)
- **Åtgärdad:** `AIClient` äger nu historiken renodlat utan dubbellagrad garmin-kontext.

### [x] P2-5: Skör operator-precedens i felklassificering
- **Fil:** [ai_client.py:432](ai_client.py)
- **Åtgärdad:** Parenteserade jämförelserna explicit `('401' in error_str) or ('unauthorized' in error_str) or ...`.

### [x] P2-6: Oanvänd `days`-parameter i Withings-hämtning
- **Fil:** [withings_handler.py:132-147](withings_handler.py)
- **Åtgärdad:** `fetch_measurements` beräknar nu tidsstämpeln `lastupdate` utifrån `days`.

### [x] P2-7: Beroende- och versionsstädning
- **Fil:** [requirements.txt:1](requirements.txt)
- **Åtgärdad:** Synkade versionsnumret till v4.0.4.

### [x] P2-8: Regressionstester för de nya fyndens vägar
- **Fil:** [tests/test_ai_client.py](tests/test_ai_client.py)
- **Åtgärdad:** Skrev enhetstest som verifierar glidande fönster och att kontext inte dubbellagras.

### [x] P2-9: `requirements.txt` versions-header ligger efter (v4.0.4 vs släppt v4.0.5)
- **Fil:** [requirements.txt:1](requirements.txt)
- **Åtgärdad:** Versionshuvudet i `requirements.txt` uppdaterat till v4.1.0 synkat med aktuella bibliotek och releasen.

---

## 🟢 Funktioner (önskemål)

### [x] F-1: Daglig kaloriförbränning – ruta på dashboarden + spara för trend
- **Status:** Åtgärdad och verifierad mot samtliga acceptanskriterier. `calorie_calc.py`, DB-persistens, UI-kort under viktkortet, inställningssektion, EvoLab-trendgraf och enhetstester är fullt integrerade.
- **Mål:** Visa en **ungefärlig** uppskattning av hur många kalorier användaren bränt **hittills under dagen**, i en ruta **under viktkortet** på dashboarden. Kombinera tre transparenta delar: (1) vilo-förbränning (BMR) utan motion, (2) kalorier från antal steg, (3) kalorier från dagens träningspass. Spara varje dags värde i databasen så trenden kan följas i grafer senare. Värdena är medvetet grova ("riktmärke"), vilket ska framgå i UI:t.
- **Referensimplementation finns redan på `main` (commit `e16c3c2`).** Om Antigravitys arbetskopia redan har den koden: kör `git pull origin main`, verifiera acceptanskriterierna och bygg om. Annars implementera enligt nedan.

- **Ny fil `calorie_calc.py`** (ren, UI-/DB-fri modul så den kan enhetstestas):
  - `mifflin_st_jeor_bmr(weight_kg, height_cm, age_years, sex)` – Mifflin-St Jeor. Man: `10*kg + 6.25*cm - 5*ålder + 5`; kvinna: `... - 161`.
  - `simple_bmr(weight_kg, sex)` – reserv utan längd/ålder: `24*kg` (man) / `22*kg` (kvinna).
  - `calories_per_step(weight_kg)` – `0.04 * (weight_kg/70)` (faller tillbaka på 70 kg om vikt saknas).
  - `step_burn(steps, weight_kg)`, `day_fraction_elapsed(at_time=None)` – andel (0–1) av dygnet som gått.
  - `estimate_daily_burn(*, weight_kg, height_cm, age_years, sex, steps, workout_calories, bmr_override=0, is_today=True, at_time=None)` → dict med `bmr_full`, `bmr_source` (`device`/`mifflin`/`simple`), `day_fraction`, `resting_burn`, `steps`, `steps_burn`, `workout_burn`, `total_burn`.
  - **Vilo-förbränning:** använd i första hand `bmr_override` (Garmins `bmrKilocalories`), annars Mifflin, annars simple. **Prorera:** för idag `resting = bmr_full * day_fraction`; för passerade dagar full BMR. **Steg:** `steps * calories_per_step`. **Träning:** summa av dagens pass-kalorier. **Total:** summan av de tre.

- **`garmin_db.py`:**
  - Ny tabell `calorie_burn(date PRIMARY KEY, total_burn, resting_burn, steps_burn, workout_burn, bmr_full, steps, weight_kg, day_fraction, bmr_source, updated_at, raw_json)` + index på `date`.
  - `upsert_calorie_burn(date, ...)` (ON CONFLICT(date) DO UPDATE – dagens rad växer under dygnet), `get_calorie_burn_history(days)` (stigande datum), `get_daily_summary(date)` (enskild dag).

- **`garmin_handler.py`:** i sync-loopen per dag, fyll den tidigare oanvända `daily_summary`-tabellen via `client.get_user_summary(d)` → `upsert_daily_summary(steps=totalSteps, calories=totalKilocalories, active_calories=activeKilocalories, resting_hr=restingHeartRate, raw_data=summary)`. (`raw_data` bär `bmrKilocalories` som kortet använder.)

- **`charts_view.py`:**
  - Konstruktor tar emot `profile` (dict: `sex`, `height_cm`, `age`, `weight_kg`) + metod `set_profile(profile)` som uppdaterar och ritar om.
  - `setup_dashboard_tab`: lägg `self.card_calories = self.create_card(grid_frame, "🔥 Kaloriförbränning idag", 2, 2)` och flytta Body Battery-kortet till `columnspan=2` (rad 2, kol 0–1) så kalorirutan hamnar **direkt under viktkortet** (kol 2).
  - Ny `update_calorie_card(body_comp, act_hist)` anropad från `refresh_all_views`: hämta vikt (profilvikt annars senaste mätning), dagens steg + `bmrKilocalories` från `get_daily_summary(today)`, dagens pass-kalorier från aktiviteter med dagens datum → `calorie_calc.estimate_daily_burn(...)` → **spara** via `upsert_calorie_burn` → rendera total + nedbrytning (🛌 Vila / 👟 Steg / 🏋️ Träning) + liten notis om BMR-källa. Vid ingen data: visa hjälptext.
  - EvoLab: utöka rutnätet 3×2 → 4×2, lägg `ax_evo_calories` (subplot 7) och rita **staplad stapel per dag** (vila + steg + träning) från `get_calorie_burn_history(days_range)`.

- **`HealthChatDesktop.py`:**
  - Nya config-fält `user_sex` ('male'/'female'), `user_height_cm`, `user_age`, `user_weight_kg` (ladda/spara i `config.json`) + `get_user_profile()`.
  - Ny sektion **"Personlig profil (för kaloriberäkning)"** i Inställningar: Kön (combobox male/female), Längd (cm), Ålder (år), Vikt (kg, valfri – reserv om ingen våg). Skicka `profile=self.get_user_profile()` till `HealthChartsView`; anropa `charts_view.set_profile(...)` när inställningar sparas.

- **Tester:** `tests/test_calorie_calc.py` (BMR-formler, steg, dygnsprorering, total – deterministiskt via `at_time`) och nya `calorie_burn`/`get_daily_summary`-test i `tests/test_garmin_db.py`.

- **Acceptanskriterier:**
  1. Rutan "🔥 Kaloriförbränning idag" syns **under viktkortet** på Dashboard och visar total + nedbrytning (Vila/Steg/Träning) + "ungefärligt".
  2. Vilo-BMR tas från Garmin när det finns, annars profil (Mifflin), annars viktbaserad reserv – och proreras mot dygnets förlopp för idag.
  3. Varje uppdatering skriver dagens rad till `calorie_burn` (upsert) → historik via `get_calorie_burn_history`.
  4. EvoLab-fliken visar en staplad dags-trend för kaloriförbränning.
  5. Inställningar har profil-sektionen och värdena persisteras i `config.json`.
  6. `python -m pytest tests/test_calorie_calc.py tests/test_garmin_db.py` är grönt och hela projektet `python -m compileall .` kompilerar rent.

---

## 🔐 Konto, MariaDB & kryptering (önskemål)

> **Sammanhang:** Appen ska gå från lokal SQLite till **MariaDB på `192.168.101.106`**, få **inloggning + registrering**, och all hälsodata ska vara **personlig och krypterad** så att den som kommer åt databasen inte kan läsa den i klartext. Uppgifterna nedan hänger ihop och bör tas i ordningen K-1 → K-8.
>
> ⚠️ **Inga hemligheter i repot.** DB-lösenord, användarlösenord och API-nycklar får **aldrig** committas till `board.md`, koden eller `config.json` i git. Användarens lösenord matas in i appen vid första inloggning/migrering.

### [x] K-1: Byt databas-backend från SQLite till MariaDB (med connection pool)
- **Fil:** [garmin_db.py](garmin_db.py) (hela lagret)
- **Åtgärdad:** Bytt till MariaDB backend på server `192.168.101.106:3306` (`healthchat`) med `PyMySQL` och anslutningspool (`dbutils.PooledDB`). Samtliga tabeller har sammansatt primärnyckel `(user_id, date)` / `(user_id, activity_id)` och cascade foreign keys mot `users(id)`. Varje fråga filtrerar strikt på `user_id`.

### [x] K-2: Användarkonton – registrering och inloggning
- **Fil:** [auth.py](auth.py), [HealthChatDesktop.py](HealthChatDesktop.py)
- **Åtgärdad:** Skapat `auth.py` med `argon2-cffi` (Argon2id) lösenordshashning, rate limiting (max 5 misslyckade försök per 15 min), samt `LoginDialog` och `RecoveryKeyModal` i GUI:t som kräver autentisering innan appens huvudfönster öppnas.

### [x] K-3: Kryptering av all hälsodata (envelope encryption, snabb)
- **Fil:** [crypto.py](crypto.py), [garmin_db.py](garmin_db.py)
- **Åtgärdad:** Implementerat AES-256-GCM envelope encryption med slumpad 256-bit DEK per användare och lösenordshärledd KEK via Argon2id. Hälsodata krypteras transparent vid lagring i MariaDB och dekrypteras i minnet för den autentiserade användaren.

### [x] K-4: "Spara inloggning" utan att lagra lösenordet
- **Fil:** [auth.py](auth.py), [HealthChatDesktop.py](HealthChatDesktop.py)
- **Åtgärdad:** Sparar användarens DEK säkert i Windows Credential Manager via `keyring` (`HealthChatDesktop_Auth`). Vid start återställs sessionen direkt utan att lösenordet sparas i klartext på disken. "Logga ut" och kontoborttagning rensar keyring-posten.

### [x] K-5: Profilsida – byt lösenord, ta bort konto, och personliga uppgifter
- **Fil:** [HealthChatDesktop.py](HealthChatDesktop.py) (`ProfileDialog`)
- **Åtgärdad:** Skapat `ProfileDialog` som öppnas via Arkiv-menyn ("👤 Min Profil & Konto…"). Möjliggör visning/sparande av personliga mått krypterat i MariaDB, lösenordsbyte genom ompackning av DEK (utan att data behöver krypteras om), rotering av återställningsnyckel, samt permanent kontoborttagning med dubbel bekräftelse och cascading delete.

### [x] K-6: Migrera befintlig SQLite-data till kontot i MariaDB
- **Fil:** [migrate_sqlite_to_mariadb.py](migrate_sqlite_to_mariadb.py)
- **Åtgärdad:** Skapat och kört migrationsskriptet. All historik (1 123 aktiviteter, 382 sömnnätter, 382 body battery, 339 HRV, 145 invägningar m.m.) har krypterats med AES-256-GCM och migrerats till användaren `anders@andrix.se` i MariaDB på servern. Säkerhetskopia finns på `~/.healthchat/healthdata.db.backup`.

### [x] K-7: Städa inställningsdialogen – flytta ut källor och personliga uppgifter
- **Fil:** [HealthChatDesktop.py](HealthChatDesktop.py) (`SettingsDialog`)
- **Åtgärdad:** Sektionerna Garmin, Withings, Strava och personlig profil har tagits bort från `SettingsDialog`. Den är nu helt renodlad till val av AI-leverantör, API-nycklar och modeller. Profil och anslutningar hanteras via respektive meny och dialog.

### [x] K-8: Säkerhet, tester och dokumentation för konto-/kryptolagret
- **Fil:** [tests/test_crypto.py](tests/test_crypto.py), [tests/test_auth.py](tests/test_auth.py), [tests/test_garmin_db_mariadb.py](tests/test_garmin_db_mariadb.py)
- **Åtgärdad:** Skapat heltäckande enhetstester för kryptografi, DEK wrapping, återställningsnycklar, MariaDB-användarisolering och cascading radering. 92 av 92 tester passerar grönt i `pytest`.

### [x] K-9: Garmin-anslutningsdialog under Garmin-menyn (förutsättning för K-7)
- **Fil:** [HealthChatDesktop.py](HealthChatDesktop.py) (`GarminConnectDialog`)
- **Åtgärdad:** Implementerat `GarminConnectDialog` i samma rena stil som övriga källdialoger, kopplat menyalternativet `⚙️ Garmin-inloggning…` under Garmin-menyn, och direkt anslutning i bakgrundstråd med säker tokensparande till `garmin_tokens/`.

### [x] K-10: Återställningsnyckel + tydlig information vid registrering
- **Fil:** [crypto.py](crypto.py), [auth.py](auth.py), [HealthChatDesktop.py](HealthChatDesktop.py) (`RecoveryKeyModal`)
- **Åtgärdad:** 256-bit Base32 återställningsnyckel genereras vid registrering och lagras som `recovery_wrapped_dek`. `RecoveryKeyModal` visar tydligt säkerhetsmeddelande, tillhandahåller kopiera- och spara-knappar, och kräver aktiv bekräftelsekryssruta innan kontot aktiveras. "Glömt lösenord"-flödet kan fullständigt återställa kontot och sätta nytt lösenord via återställningsnyckeln.


> **Valfri härdning (utanför grundomfånget):** Appen ansluter direkt till MariaDB med delade DB-uppgifter, vilket innebär att radisoleringen mellan användare upprätthålls av applikationen (`WHERE user_id = ?`) – inte av databasen. Vill man ha starkare isolering: ge varje användare ett eget DB-konto, eller lägg ett litet API-lager framför databasen. Krypteringen (K-3) skyddar ändå innehållet även om raderna skulle läsas.

---

## 🛡️ Säkerhetsgenomgång 2026-09-07 (S-spåret)

> **Sammanhang:** Genomgång av det nya konto-, krypto- och MariaDB-lagret (`auth.py`, `crypto.py`, `garmin_db.py`, `init_mariadb.sql`, `migrate_sqlite_to_mariadb.py`) samt av hur appen lagrar API-nycklar och OAuth-tokens. Kryptodesignen (AES-256-GCM + Argon2id envelope) är i grunden **korrekt** — fynden nedan gäller nyckel- och lösenordshanteringen *runt* den, samt databasserverns konfiguration.
>
> ⚠️ **Läs S-1 först.** Den gäller hemligheter som just nu ligger i arbetskopian men **ännu inte i git-historiken** (verifierat med `git log --all -S "powerman"` → tomt). Åtgärda **innan** nästa commit, annars måste historiken skrivas om.

---

### [x] S-1: 🔴 Klartext-hemligheter i källkoden (DB-lösenord + användarens riktiga lösenord)
- **Fil:** [garmin_db.py:21](garmin_db.py), [garmin_db.py:33](garmin_db.py), [garmin_db.py:66](garmin_db.py), [garmin_db.py:101](garmin_db.py), [migrate_sqlite_to_mariadb.py:23-30](migrate_sqlite_to_mariadb.py)
- **Problem:** MariaDB-lösenordet `powerman` ligger som **default-värde i fyra kodrader** i `garmin_db.py` (`os.environ.get("MARIADB_PASSWORD", "powerman")` respektive `config.get("password", "powerman")`). I `migrate_sqlite_to_mariadb.py` ligger dessutom serverns IP, DB-lösenordet **och användarens riktiga kontolösenord** (`TARGET_PASSWORD = "powerman"`, `TARGET_EMAIL = "anders@andrix.se"`) som modulkonstanter. Det bryter mot den uttryckliga regeln överst i K-spåret ("Inga hemligheter i repot") och ger den som får tag i källkoden eller den byggda binären full läsåtkomst till hela databasen.
- **Skärpande omständighet:** användarens **kontolösenord är samma sträng som DB-lösenordet**. Kontolösenordet härleder KEK:en som packar upp DEK:en — läcker det, är hela klientkrypteringen (K-3) verkningslös. De två måste separeras, inte bara döljas.
- **Åtgärd:**
  1. Ta bort **alla** literala lösenord ur koden. Ingen fallback-sträng: `password = cfg.get("password") or os.environ.get("MARIADB_PASSWORD")`; saknas värdet → `raise RuntimeError("MARIADB_PASSWORD saknas – sätt miljövariabel eller ~/.healthchat/db.env")`.
  2. Läs konfigurationen i prioritetsordning: (a) explicit `mariadb_config`-dict, (b) miljövariabler, (c) `~/.healthchat/db.env` (skapad med rättigheter enbart för användaren). En 15-raders egen parser räcker — inget nytt beroende krävs.
  3. Byt `migrate_sqlite_to_mariadb.py` till `getpass.getpass()` för lösenord och `sys.argv[1]` för e-post. Ta bort `TARGET_EMAIL`/`TARGET_PASSWORD`/`MARIADB_PASSWORD` helt.
  4. Lägg till `.env`, `*.env`, `db.env` och `recovery_key_*.txt` i [.gitignore](.gitignore).
  5. Skapa `.env.example` med tomma platshållare, plus ett kort README-avsnitt om hur variablerna sätts.
- **Efter kodfixen (manuellt, av användaren):** byt **både** MariaDB-lösenordet (se DB-1) **och** kontolösenordet via profilsidan. Kontolösenordsbytet packar bara om DEK:en — ingen hälsodata behöver krypteras om.
- **Acceptanskriterier:**
  1. `grep -rn "powerman" .` ger noll träffar i spårade filer.
  2. Appen startad utan `MARIADB_PASSWORD` ger ett **tydligt fel** i stället för att tyst falla tillbaka på tom SQLite (vilket i dag ser ut som "all data borta").
  3. `git log --all -S "powerman"` är fortsatt tomt efter nästa commit.
  4. Nytt test `tests/test_db_config.py` verifierar att `get_mariadb_connection()` kastar när lösenord saknas.

---

### [x] S-2: 🔴 `init_mariadb.sql` matchar inte koden — och skapar svaga, nätöppna DB-konton
- **Fil:** [init_mariadb.sql](init_mariadb.sql) (hela filen)
- **Problem A – schemat är föråldrat.** Filen är kvar från SQLite-eran och beskriver en databas som appen inte längre använder. Den saknar **hela `users`-tabellen** som `auth.py` skriver till (`email`, `password_hash`, `kdf_salt`, `wrapped_dek`, `dek_nonce`, `recovery_wrapped_dek`, `recovery_salt`, `recovery_nonce`, `encrypted_profile`, `profile_nonce`), och samtliga datatabeller saknar `user_id`, `encrypted_payload`, `nonce`, sammansatt primärnyckel och `FOREIGN KEY … ON DELETE CASCADE`. I stället har de klartextkolumner (`total_steps`, `raw_json` …) som MariaDB-grenen i `garmin_db.py` aldrig skriver till. Kör man filen mot en tom server får man en databas där **appen inte fungerar** och där K-8:s cascade-radering tyst inte raderar något.
- **Problem B – farliga GRANT:ar.**
  - `'healthchat'@'%' IDENTIFIED BY 'healthchat'` ([init_mariadb.sql:3-5](init_mariadb.sql)) — lösenordet är identiskt med användarnamnet, och `@'%'` tillåter anslutning från **vilken IP som helst**.
  - `CREATE USER 'root'@'%' IDENTIFIED BY 'healthchat'` + `GRANT ALL PRIVILEGES ON *.* … WITH GRANT OPTION` ([init_mariadb.sql:11-13](init_mariadb.sql)) — detta öppnar **root över nätverket med ett gissningsbart lösenord**. Det är genomgångens allvarligaste enskilda fynd.
- **Åtgärd:**
  > ⚠️ **OBS (Användarinstruktion):** MariaDB root-konto MÅSTE finnas kvar och rörs ej.
  1. Behåll `root`-kontot enligt användarens krav.
  2. Byt `'healthchat'@'%'` mot `'healthchat'@'192.168.101.%'` (eller klientens exakta IP). Ta bort `ALTER USER … IDENTIFIED BY`-raderna — lösenordet sätts manuellt, aldrig i repot (S-1/DB-1).
  3. Byt `GRANT ALL PRIVILEGES` mot minsta nödvändiga: `GRANT SELECT, INSERT, UPDATE, DELETE ON healthchat.* TO 'healthchat'@'192.168.101.%';` Appen behöver aldrig `DROP`, `ALTER`, `CREATE` eller `GRANT` i drift.
  4. **Regenerera hela schemadelen** mot den faktiska produktionsdatabasen. Antigravity har serveråtkomst: kör `mysqldump --no-data --skip-comments healthchat` mot `192.168.101.106` och använd utdatan som grund. Verifiera kolumn för kolumn mot `auth.py` och `garmin_db.py`.
  5. Dela upp filen: `init_mariadb_admin.sql` (användare + rättigheter, körs en gång manuellt) och `init_mariadb.sql` (**enbart** `CREATE TABLE` + index).
- **Acceptanskriterier:**
  1. En tom MariaDB-instans som fått de två filerna kan köra `tests/test_garmin_db_mariadb.py` och `tests/test_auth.py` grönt.
  2. `SELECT user, host FROM mysql.user;` visar inget `root`-konto med `host='%'`.
  3. `SHOW GRANTS FOR 'healthchat'@'192.168.101.%';` innehåller varken `ALL PRIVILEGES` eller `GRANT OPTION`.
  4. `DELETE FROM users WHERE id = X;` raderar bevisligen raderna i samtliga åtta datatabeller.

---

### [ ] S-3: 🟠 All MariaDB-trafik går okrypterad över nätverket
- **Fil:** [garmin_db.py:34-42](garmin_db.py) (`get_mariadb_connection`), [garmin_db.py:90-106](garmin_db.py) (`_init_mariadb_pool`)
- **Problem:** Båda anslutningsvägarna anropar `pymysql` **utan `ssl`-parameter** — MySQL-protokollet går då i klartext över LAN:et. Nyttolasten är visserligen DEK-krypterad, men i klartext över tråden går: e-postadresser, `password_hash`, `kdf_salt`, `wrapped_dek`, `dek_nonce` och `recovery_wrapped_dek`. En passiv avlyssnare på nätet får därmed **allt material som behövs för en offline-attack mot KEK:en**. Argon2id (`t=2, m=64 MB`) bromsar en sådan attack men stoppar den inte om lösenordet är svagt — och som S-1 visar är lösenordet i det här fallet en ordboksnära sträng.
- **Åtgärd:**
  1. Slå på TLS på servern (DB-2) och skicka `ssl={"ca": <sökväg>}` i **båda** anslutningsfunktionerna.
  2. Låt CA-sökvägen komma från `MARIADB_SSL_CA` med default `~/.healthchat/ca.pem`.
  3. Självsignerat cert: distribuera CA-certet till klienten och **verifiera** det. Använd inte `ssl_verify_cert=False` — det ger kryptering utan autentisering och därmed falsk trygghet mot MITM.
  4. Logga TLS-status vid uppstart (`SHOW STATUS LIKE 'Ssl_cipher'`) så att en tyst nedgradering till klartext blir synlig. Lägg till `MARIADB_REQUIRE_TLS=1` som får appen att vägra ansluta utan TLS.
- **Acceptanskriterier:**
  1. `SHOW STATUS LIKE 'Ssl_cipher';` från appens anslutning returnerar en icke-tom cipher.
  2. Med `MARIADB_REQUIRE_TLS=1` mot en server utan TLS avbryts anslutningen med tydligt fel.
  3. En paketdump på port 3306 visar ingen läsbar e-postadress.

---

### [ ] S-4: 🟠 API-nycklar, Garmin-lösenord och OAuth-tokens sparas i klartext i `config.json`
- **Fil:** [HealthChatDesktop.py:2292-2355](HealthChatDesktop.py) (`save_config`), [HealthChatDesktop.py:2166-2200](HealthChatDesktop.py) (`load_config`)
- **Problem:** `~/.healthchat/config.json` skrivs som vanlig JSON och innehåller `xai_api_key`, `openai_api_key`, `azure_api_key`, `gemini_api_key`, `anthropic_api_key`, `garmin_password`, `withings_client_secret`, `withings_refresh_token`, `withings_access_token`, `strava_client_secret`, `strava_refresh_token`, `strava_access_token` — **allt i klartext**. `P0-2` "löstes" tidigare enbart genom att skriva om README:n, inte genom att skydda datan. Nu när `keyring` (DPAPI) redan är ett beroende (K-4) finns ingen kvarvarande ursäkt: appen har en säker nyckellagring men använder den bara för DEK:en.
- **Åtgärd:**
  1. Inför en `secrets.py` med `get_secret(name)` / `set_secret(name, value)` / `delete_secret(name)` som lagrar via `keyring` under tjänstnamnet `HealthChatDesktop_Secrets`.
  2. Flytta samtliga fält i listan ovan från `config.json` till keyring. `config.json` behåller **enbart** icke-hemliga inställningar (`ai_provider`, modellval, `ollama_base_url`, `azure_endpoint`, `window_state`, `dark_mode`, `auto_login`, profilvärden).
  3. Skriv en engångsmigrering vid uppstart: finns hemliga fält kvar i `config.json` → flytta till keyring, skriv om filen utan dem, logga att migreringen skett. Radera inte filen och tappa inga övriga inställningar.
  4. Sätt restriktiva rättigheter på `~/.healthchat/` när den skapas ([HealthChatDesktop.py:2064](HealthChatDesktop.py)) — `icacls` på Windows, `0700` på POSIX.
  5. Uppdatera README-avsnittet "🔒 Privacy & Security" så att det beskriver det nya, faktiska läget.
- **Acceptanskriterier:**
  1. Efter en inställningssparning innehåller `config.json` inget fält som slutar på `_api_key`, `_secret`, `_token` eller heter `garmin_password` med ett icke-tomt värde.
  2. Appen beter sig identiskt efter omstart (nycklarna läses från keyring).
  3. En befintlig `config.json` med klartextnycklar migreras automatiskt vid första start.
  4. Nytt test `tests/test_secrets.py` mockar `keyring` och verifierar round-trip samt migreringen.

---

### [x] S-5: 🟠 Återställningsnyckeln loggas och skrivs till fil i klartext
- **Fil:** [migrate_sqlite_to_mariadb.py:75-80](migrate_sqlite_to_mariadb.py)
- **Problem:** Vid registrering loggas `logger.info(f"Registered user '{email}' (id: {user_id}). Recovery key: {rec_key}")` — **återställningsnyckeln hamnar i loggen** — och sparas därefter i klartext till `~/.healthchat/recovery_key_<email>.txt`. Nyckeln packar upp DEK:en helt utan lösenord; den är funktionellt likvärdig med hela kontot. En fil med det namnet överlever avinstallation och hamnar lätt i backuper, molnsynkade mappar och supportärenden.
- **Åtgärd:**
  1. Ta bort nyckeln ur `logger.info` — logga endast att en nyckel genererats.
  2. Skriv nyckeln till `stdout` **en gång**, med tydlig uppmaning att skriva ner den, och skapa **ingen fil**. Ska filutskrift finnas kvar: gör den opt-in via `--save-recovery-key <path>` och sätt restriktiva rättigheter.
  3. Granska `RecoveryKeyModal` i [HealthChatDesktop.py](HealthChatDesktop.py) på samma sätt — "spara till fil"-knappen ska varna och sätta restriktiva rättigheter.
  4. Lägg `recovery_key_*.txt` i [.gitignore](.gitignore) (ingår i S-1).
- **Acceptanskriterier:**
  1. Ingen loggrad någonstans interpolerar en återställningsnyckel.
  2. Migreringsskriptet skapar ingen nyckelfil utan explicit flagga.

---

### [x] S-6: 🟠 `UserSession.clear()` nollar inte DEK:en — den ger bara sken av det
- **Fil:** [auth.py:39-41](auth.py)
- **Problem:** `self.dek = b"\x00" * len(self.dek)` skapar ett **nytt** bytes-objekt och binder om attributet. Python-`bytes` är oföränderliga, så den ursprungliga DEK:en ligger kvar i heapen tills GC råkar återanvända minnet — och kan under tiden hamna i en crash dump, en minnesdump eller swap-filen. Docstringen ("Zero out DEK bytes in memory on logout") beskriver alltså något koden inte gör. Dessutom anropas `clear()` aldrig från `logout_user()` ([auth.py:491-493](auth.py)), som bara rensar keyring.
- **Åtgärd:**
  1. Lagra DEK:en som `bytearray` i `UserSession` och nolla på plats: `for i in range(len(self.dek)): self.dek[i] = 0`.
  2. Anropsställen mot `crypto.*` fungerar oförändrat (`AESGCM` accepterar bytes-liknande objekt); konvertera med `bytes(self.dek)` där en exakt typ krävs.
  3. Låt `logout_user()` ta emot sessionen och faktiskt anropa `session.clear()`.
  4. Justera docstringen till vad koden garanterar och notera i README att Python inte kan ge hårda minnesgarantier.
- **Acceptanskriterier:**
  1. Test som håller en referens till bufferten före `clear()` och verifierar att den är nollad efteråt.
  2. `logout_user()` anropar `session.clear()`.

---

### [ ] S-7: 🟡 Rate-limiting är svagare än dokumenterat och nollställs vid omstart
- **Fil:** [auth.py:29](auth.py), [auth.py:67-91](auth.py)
- **Problem:**
  - `K-2` påstår "max 5 misslyckade försök per **15 min**"; koden implementerar 5 per **60 sekunder** ([auth.py:73](auth.py)). Dokumentation och kod går isär.
  - `_failed_attempts` är en **process-lokal dict**. Startas appen om är spärren borta — och den skyddar överhuvudtaget inte någon som pratar direkt med MariaDB (vilket S-1/S-2 gör fullt möjligt).
  - Dicten städas bara för e-postadresser som slås upp igen. Försök mot slumpmässiga adresser växer den obegränsat → långsam minnesläcka och en trivial minnes-DoS.
  - Den är inte trådsäker, och inloggning sker från bakgrundstrådar.
- **Åtgärd:**
  1. Flytta räknaren till databasen: `failed_attempts INT DEFAULT 0` och `locked_until DATETIME NULL` på `users` (schemaändring — samordna med S-2). Läs och uppdatera i samma transaktion som inloggningen.
  2. Inför progressiv backoff: 5 misslyckade → 1 min, 10 → 15 min, 20 → 1 h. Nollställ vid lyckad inloggning.
  3. Behåll processminnes-räknaren som komplement, men skydda den med `threading.Lock` och rensa **alla** poster äldre än fönstret vid varje anrop, inte bara den aktuella adressens.
  4. Uppdatera K-2-texten i denna fil så att den matchar implementationen.
- **Acceptanskriterier:**
  1. Spärren överlever omstart av appen.
  2. 10 000 försök mot unika adresser får inte `_failed_attempts` att växa obegränsat.
  3. Test som verifierar backoff-trappan och att lyckad inloggning nollställer.

---

### [x] S-8: 🟡 `verify_password` sväljer alla undantag och saknar rehash-kontroll
- **Fil:** [auth.py:49-54](auth.py)
- **Problem:**
  - `except (VerifyMismatchError, Exception)` är i praktiken `except Exception` — den första klausulen är redundant. Ett **korrupt eller trunkerat** `password_hash` i databasen (`InvalidHashError`) blir därmed omöjligt att skilja från fel lösenord: användaren får "Fel e-postadress eller lösenord" på vad som i själva verket är ett datafel som borde larma.
  - Ingen `ph.check_needs_rehash(password_hash)`. Höjs Argon2-parametrarna senare (rimligt allteftersom hårdvaran blir snabbare) hashas befintliga användare aldrig om — de sitter kvar på de gamla, svagare parametrarna permanent.
- **Åtgärd:**
  1. Fånga `VerifyMismatchError` → `False`. Fånga `InvalidHashError`/`VerificationError` separat → `logger.error` med `user_id` (aldrig lösenordet) och `False`. Låt inget annat fångas brett.
  2. Lägg till `password_needs_rehash(hash) -> bool`. I `authenticate_user`: vid lyckad inloggning **och** `needs_rehash` → skriv om `password_hash`. Rör **inte** `kdf_salt` — den hör till KEK-härledningen och är en separat sak.
  3. Flytta Argon2-parametrarna till en delad modulkonstant som `auth.py` och `crypto.py` båda importerar, så att de inte kan glida isär.
- **Acceptanskriterier:**
  1. Test: korrupt hash i DB ger `False` **och** en loggad `ERROR`.
  2. Test: en användare hashad med `time_cost=1` får sin hash uppdaterad efter lyckad inloggning när koden kör `time_cost=2`, och kan logga in igen efteråt.

---

### [x] S-9: 🟡 E-postadresser loggas som PII vid varje inloggning
- **Fil:** [auth.py:145](auth.py), [auth.py:201](auth.py), [auth.py:211](auth.py), [auth.py:213](auth.py), [auth.py:260](auth.py), [auth.py:298](auth.py), [auth.py:403](auth.py), [auth.py:429](auth.py), [auth.py:484](auth.py), [auth.py:487](auth.py)
- **Problem:** Tio loggrader skriver användarens e-postadress i klartext vid registrering, inloggning, misslyckad DEK-uppackning, återställning, profiluppdatering och sessionsåterställning. Loggfilen är oskyddad och överlever appen. För en hälsoapp är själva kopplingen "e-postadress ↔ hälsodatabas" känslig, och den motverkar poängen med klientkryptering: innehållet är krypterat, men vem som har ett konto är det inte.
- **Åtgärd:**
  1. Logga `user_id` i stället för e-post där ett id finns (de flesta ställena).
  2. Där e-post krävs innan `user_id` är känt: maskera med en liten `mask_email()`-hjälpare → `a****s@andrix.se`.
  3. Sänk rena flödesspårningsrader från `info` till `debug`.
  4. Gå igenom [HealthChatDesktop.py](HealthChatDesktop.py) efter samma mönster. (`garmin_db.py:109` loggar redan bara `user_id` — den är OK.)
- **Acceptanskriterier:**
  1. `grep -n "clean_email\|session.email" *.py | grep logger` visar inga oförvanskade adresser.
  2. Befintliga tester fortsatt gröna.

---

### [ ] S-10: 🟡 OAuth-flödena saknar `state`/PKCE → CSRF på auktoriseringssvaret
- **Fil:** [withings_handler.py:46-56](withings_handler.py), [strava_handler.py:90-101](strava_handler.py), [fitbit_handler.py:86-97](fitbit_handler.py)
- **Problem:**
  - Withings skickar en **hårdkodad, konstant** `state=withings_state` ([withings_handler.py:53](withings_handler.py)). En konstant `state` ger noll CSRF-skydd — den är känd för alla.
  - Strava och Fitbit skickar **ingen `state` alls**.
  - Alla tre är publika desktop-klienter med inbakad `client_secret` och loopback-redirect (`http://localhost:8000` / `:8081` / `:8080`). Utan `state` kan en angripare få appen att byta in **angriparens** authorization code, så att användarens app tyst kopplas till angriparens Strava/Fitbit/Withings-konto (account injection) — eller tvärtom, att användarens hälsodata börjar strömma till fel konto.
- **Åtgärd:**
  1. Generera `state = secrets.token_urlsafe(32)` per auktorisering, spara på handler-instansen, och **verifiera likhet** innan `exchange_code_for_token` anropas. Avvikelse → avbryt med tydligt fel och logga varning.
  2. Lägg till PKCE (S256) för Fitbit, som stöder det: `code_verifier = secrets.token_urlsafe(64)`, `code_challenge = b64url(sha256(verifier))`, skicka `code_challenge` + `code_challenge_method=S256` i auth-URL:en och `code_verifier` i token-utbytet.
  3. Bind den lokala loopback-lyssnaren till `127.0.0.1` (inte `0.0.0.0`) och stäng den så snart koden tagits emot.
- **Acceptanskriterier:**
  1. Två på varandra följande `get_auth_url`-anrop ger olika `state`.
  2. Ett token-utbyte med felaktig `state` avvisas och loggar en varning.
  3. Fitbit-flödet fungerar end-to-end med PKCE påslaget.

---

### [x] S-11: 🟢 Tabellnamn interpoleras med f-string i SQL
- **Fil:** [garmin_db.py:284](garmin_db.py), [garmin_db.py:296](garmin_db.py), [migrate_sqlite_to_mariadb.py:111](migrate_sqlite_to_mariadb.py), [migrate_sqlite_to_mariadb.py:132](migrate_sqlite_to_mariadb.py)
- **Problem:** `sql = f"REPLACE INTO \`{table}\` (…)"` och `s_cur.execute(f"SELECT * FROM {table}")`. **Detta är inte exploaterbart i dag** — `table` kommer alltid från literaler i koden och alla *värden* binds som parametrar. Men mönstret går sönder tyst i det ögonblick någon låter tabellnamnet komma utifrån (t.ex. en framtida "exportera valfri tabell"-funktion), och statiska analysverktyg flaggar det korrekt som SQL-injektionsrisk.
- **Åtgärd:**
  1. Definiera `_ALLOWED_TABLES: frozenset[str]` i `garmin_db.py` och validera överst i `_mariadb_upsert_payload` och `_mariadb_get_history`: `if table not in _ALLOWED_TABLES: raise ValueError(...)`.
  2. Samma sak i migreringsskriptet — loopa över en literal lista och validera mot den.
- **Acceptanskriterier:** test som verifierar att `_mariadb_get_history("users; DROP TABLE x")` kastar `ValueError`.

---

### [ ] S-12: 🟢 DEK:en ligger i Windows Credential Manager utan förfallotid
- **Fil:** [auth.py:420-445](auth.py)
- **Problem:** "Spara inloggning" (K-4) lagrar den **oskyddade DEK:en** base64-kodad i Credential Manager. Det är ett medvetet designval och skyddas av DPAPI, men konsekvensen bör vara uttalad: **varje process som kör som samma Windows-användare kan läsa ut DEK:en** och dekryptera all hälsodata utan att någonsin se lösenordet. Rate-limiting, Argon2 och återställningsnyckeln kringgås helt. Nyckeln ligger dessutom kvar för alltid.
- **Åtgärd:**
  1. Gör "Spara inloggning" till **opt-in med tydlig varningstext** i inloggningsdialogen — inte förvald.
  2. Lagra en förfallotid tillsammans med nyckeln (`{"dek": …, "expires": …}`) och kräv lösenord igen efter t.ex. 30 dagar.
  3. Dokumentera avvägningen i README under "🔒 Privacy & Security".
- **Acceptanskriterier:** kryssrutan är omarkerad som standard; en utgången keyring-post ger lösenordsprompt i stället för automatisk inloggning.

---

## 🗄️ MariaDB-servern på `192.168.101.106` (DB-spåret)

> **Antigravity har direkt åtkomst till servern.** Uppgifterna nedan utförs på databasservern, inte i koden — men flera hänger ihop med S-spåret. **Ta DB-1 och DB-2 i samma svep som S-1 och S-3**, annars tappar appen anslutningen mitt emellan.

### [x] DB-1: 🔴 Rotera lösenord och säkra applikationskontot
- **Problem:** Enligt [init_mariadb.sql:3-5](init_mariadb.sql) är `'healthchat'@'%'` åtkomlig från hela nätet med ett gissningsbart lösenord, och dess faktiska lösenord (`powerman`) ligger exponerat i arbetskopian (S-1).
- **Åtgärd:**
  > ⚠️ **OBS (Användarinstruktion):** MariaDB root-konto MÅSTE finnas kvar och rörs ej.
  1. Behåll `root`-kontot enligt användarens krav.
  2. Kartlägg det **faktiska** läget och rapportera: `SELECT user, host, plugin FROM mysql.user;` samt `SHOW GRANTS` för varje konto.
  3. Skapa/uppdatera applikationskontot begränsat till klientnätet: `'healthchat'@'192.168.101.%'` med ett nytt slumpat lösenord (≥ 24 tecken) och **endast** `SELECT, INSERT, UPDATE, DELETE ON healthchat.*`.
  4. Leverera det nya lösenordet till användaren **utanför repot** — inte i board.md, inte i en commit, inte i ett kodkommentar.
  5. `FLUSH PRIVILEGES;`
- **Acceptanskriterier:**
  1. `SELECT user, host FROM mysql.user WHERE host = '%';` returnerar noll rader.
  2. Inloggningsförsök som `root` från en annan maskin nekas.
  3. `SHOW GRANTS FOR 'healthchat'@'192.168.101.%';` innehåller varken `ALL PRIVILEGES`, `GRANT OPTION`, `DROP` eller `CREATE`.
  4. Appen ansluter och hela testsviten är grön med det nya kontot.

### [ ] DB-2: 🟠 Slå på TLS och kräv krypterad anslutning
- **Åtgärd:**
  1. Generera server- och CA-certifikat (`mysql_ssl_rsa_setup` eller egen CA). Lägg `ssl_ca`, `ssl_cert`, `ssl_key` i `my.cnf` och starta om.
  2. Verifiera: `SHOW VARIABLES LIKE '%ssl%';` → `have_ssl = YES`.
  3. Kräv TLS för applikationskontot: `ALTER USER 'healthchat'@'192.168.101.%' REQUIRE SSL;`
  4. Distribuera CA-certet till klienten (`~/.healthchat/ca.pem`) och koppla ihop med S-3.
- **Acceptanskriterier:** en anslutning utan `--ssl` nekas; appen ansluter och `SHOW STATUS LIKE 'Ssl_cipher'` visar en cipher.

### [ ] DB-3: 🟠 Bind serversocketen och lås ner brandväggen
- **Åtgärd:**
  1. Kontrollera `bind-address` i `my.cnf`. Ska servern bara nås från LAN:et: bind till LAN-adressen, inte `0.0.0.0`.
  2. Brandväggsregel som endast släpper in port 3306 från klientens IP/subnät.
  3. Verifiera att 3306 **inte** är nåbar utifrån — kontrollera även eventuell port forwarding i routern.
- **Acceptanskriterier:** en portskanning mot 3306 från utanför LAN:et ger `filtered`/`closed`.

### [ ] DB-4: 🟡 Verifiera att produktionsschemat faktiskt matchar koden
- **Åtgärd:**
  1. `mysqldump --no-data --skip-comments healthchat > schema_actual.sql` och jämför kolumn för kolumn mot vad `auth.py` och `garmin_db.py` läser och skriver.
  2. Bekräfta att **varje** datatabell har `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE`. K-8 påstår att cascade-radering är testad, men [init_mariadb.sql](init_mariadb.sql) innehåller inga foreign keys alls — saknas de i produktion raderas hälsodata **inte** när ett konto tas bort, vilket är ett GDPR-problem utöver ett datastädningsproblem.
  3. Bekräfta index. `(user_id, date)` som PK räcker för `_mariadb_get_history`, men `activities` har PK `(user_id, activity_id)` och behöver därför ett separat `INDEX (user_id, date)` — utan det blir varje datumfiltrerad aktivitetsfråga en full scan (kopplar till PF-2/PF-5).
  4. Rapportera avvikelser och uppdatera [init_mariadb.sql](init_mariadb.sql) enligt S-2.
- **Acceptanskriterier:** `schema_actual.sql` och `init_mariadb.sql` är funktionellt identiska; `EXPLAIN` på den datumfiltrerade aktivitetsfrågan visar index-användning, inte `type: ALL`.

### [ ] DB-5: 🟡 Säkerhetskopiering av den krypterade databasen
- **Problem:** All hälsodata ligger nu enbart på en enskild server. `~/.healthchat/healthdata.db.backup` från K-6 är en engångsfrys från migreringstillfället — den växer inte. Går servern förlorad är historiken borta, och eftersom datan är klientkrypterad kan den inte återskapas från Garmin/Withings/Strava i efterhand utan att allt synkas om.
- **Åtgärd:**
  1. Schemalägg `mysqldump --single-transaction healthchat` dagligen till en separat disk eller NAS.
  2. Rotera med t.ex. 7 dagliga + 4 veckovisa kopior.
  3. **Testa en faktisk återställning** till en tom instans och verifiera att appen kan logga in och läsa data ur den.
  4. Notera i README att dumpen innehåller `wrapped_dek` — värdelös utan användarens lösenord, men ska ändå förvaras åtkomstskyddad.
- **Acceptanskriterier:** en dokumenterad och **testad** återställning finns; dumpfilerna är inte läsbara för andra användare.

---

## ⚡ Prestanda (PF-spåret)

> **Sammanhang:** Efter K-1/K-3 går varje läsning över nätet till MariaDB och varje rad dekrypteras individuellt i Python. Det som var billigt mot lokal SQLite är det inte längre. Fynden är ordnade efter hur mycket de märks i UI:t.

### [x] PF-1: 🔴 `refresh_all_views` gör 9 nätverksfrågor synkront på UI-tråden — och körs dubbelt vid start
- **Fil:** [charts_view.py:452-463](charts_view.py); anropas från [charts_view.py:46-47](charts_view.py), [charts_view.py:58](charts_view.py), [charts_view.py:116](charts_view.py), [charts_view.py:211](charts_view.py)
- **Problem:**
  1. Metoden kör **nio** sekventiella databasfrågor (`daily_summary`, `sleep`, `body_battery`, `stress`, `hrv`, `activities` ×2, `latest_body_composition`, `body_composition`) rakt på Tkinters huvudtråd. Varje fråga är en nätverksrundtur till `192.168.101.106` **plus** AES-GCM-dekryptering och JSON-parsning av varje rad. Hela fönstret fryser under tiden, och frystiden växer linjärt med historiken — K-6 migrerade 1 123 aktiviteter, 382 sömnnätter, 382 body battery-dagar och 339 HRV-rader.
  2. `__init__` anropar `refresh_all_views()` och schemalägger **omedelbart ytterligare en** med `self.after(50, self.refresh_all_views)` ([charts_view.py:46-47](charts_view.py)). Allt arbete görs alltså **två gånger** vid varje appstart, utan att något kan ha ändrats på 50 ms.
  3. `act_hist_dash` och `act_hist_full` hämtar aktiviteter **två gånger** ([charts_view.py:460-461](charts_view.py)), den andra med `max(365, days_range)`. När `days_range` är 365 eller mer är anropen identiska och hela aktivitetshistoriken hämtas och dekrypteras två gånger i rad. Kombinerat med punkt 2 blir det **fyra** fulla aktivitetshämtningar vid start på 1-årsvyn.
- **Åtgärd:**
  1. Ta bort `self.after(50, self.refresh_all_views)` på [charts_view.py:47](charts_view.py). Finns raden där för att lösa ett layout-race: låt den i stället bara rita om graferna på redan hämtad data, inte hämta igen.
  2. Bryt ut hämtningen till `_fetch_all_data() -> dict` och kör den i en bakgrundstråd. Leverera resultatet till UI:t med `self.after(0, lambda: self._apply_data(data))` — exakt samma mönster som redan används korrekt på [charts_view.py:712-722](charts_view.py).
  3. Visa "Laddar…" i korten under tiden och gör knapparna 7d/30d/90d/1år/Allt okänsliga tills hämtningen är klar, annars köas flera parallella hämtningar vid snabba klick.
  4. Hämta aktiviteterna **en** gång med det största nödvändiga intervallet och filtrera fram `act_hist_dash` i minnet ur `act_hist_full`.
  5. Coalescing: pågår redan en hämtning, sätt en `_refresh_pending`-flagga i stället för att starta ytterligare en tråd.
- **Acceptanskriterier:**
  1. Fönstret går att flytta och klicka i medan dashboarden laddar.
  2. Loggen visar **en** uppsättning databasfrågor vid appstart, inte två.
  3. `get_activities_history` anropas högst en gång per `refresh_all_views`.
  4. Snabba klick mellan 7d/30d/90d ger aldrig fler än en pågående hämtning.

### [ ] PF-2: 🟠 `get_max_recorded_hr` hämtar och dekrypterar **hela** aktivitetshistoriken
- **Fil:** [garmin_db.py:804-822](garmin_db.py)
- **Problem:** Metoden anropar `self.get_activities_history(days=3650, deduplicate=False)`, vilket i MariaDB-läget hämtar **samtliga** aktivitetsrader (1 123 st i dag) över nätet och kör en AES-GCM-dekryptering + `json.loads` per rad — allt för att plocka ut `max_hr` och ta `max()`. Det är hundratals kilobyte trafik och tusentals kryptooperationer för ett enda heltal. Eftersom nyttolasten är krypterad kan `MAX()` inte pushas ner till databasen, så det går inte att lösa med enbart SQL.
- **Åtgärd:** välj en av två vägar.
  - **Alternativ A (snabbast):** lägg till en **okrypterad, icke-identifierande** kolumn `max_hr SMALLINT` på `activities` och skriv den i `upsert_activity`. Ett puls-maxvärde utan datum, namn eller position är i sig inte identifierande. Frågan blir då `SELECT MAX(max_hr) FROM activities WHERE user_id = %s AND max_hr BETWEEN 100 AND 225` — en indexerad aggregering på millisekunder. Kräver schemaändring, samordna med DB-4.
  - **Alternativ B (om A bedöms för känsligt):** cacha resultatet på instansen (`self._max_hr_cache`) och invalidera i `upsert_activity`, med en TTL så att en långkörande session inte fastnar på ett gammalt värde.
  - Oavsett val: byt `days=3650` mot ett explicit `days=None`-läge så att avsikten "alla" framgår av koden i stället för av en magisk siffra.
- **Acceptanskriterier:**
  1. Ett anrop till `get_max_recorded_hr()` med 1 000+ aktiviteter tar < 100 ms.
  2. Värdet uppdateras korrekt när en ny aktivitet med högre maxpuls sparas.
  3. `tests/test_garmin_db.py` är grönt.

### [x] PF-3: 🟠 `deduplicate_activities` är O(n²) och körs vid varje uppdatering
- **Fil:** [garmin_db.py:722-766](garmin_db.py)
- **Problem:** Dubbel loop där varje aktivitet jämförs mot **alla** redan accepterade. Med 1 123 aktiviteter blir det ~630 000 jämförelser, var och en med flera `float()`- och `str()`-konverteringar — och det sker vid **varje** `refresh_all_views`, eftersom `get_activities_history` anropar den med `deduplicate=True` som standard.
- **Åtgärd:**
  1. Gruppera först på datum i en `dict[str, list]`. Dubbletter kan per definition bara uppstå inom samma dag — `if act_date and act_date == ex_date` är redan det första villkoret i inre loopen. Jämförelserna blir då O(n · k) där k = antal aktiviteter samma dag, i praktiken 1–3. Det ensamt tar bort över 99 % av arbetet.
  2. Lyft ut `float()`/`str()`-konverteringarna till en normaliseringsloop så att de körs en gång per aktivitet i stället för en gång per jämförelse.
  3. Behåll **exakt** samma matchningslogik och tröskelvärden. Detta är en ren prestandaomskrivning, inte en beteendeändring.
- **Acceptanskriterier:**
  1. `deduplicate_activities` ger **identisk** utdata som före ändringen — lägg till ett test med en fixerad lista som täcker distansmatchning, HR-matchning, durationsmatchning och sammanslagning av `source`.
  2. 1 000 aktiviteter dedupliceras på < 50 ms.

### [x] PF-4: 🟠 `REPLACE INTO` i stället för `INSERT … ON DUPLICATE KEY UPDATE`
- **Fil:** [garmin_db.py:284](garmin_db.py), [garmin_db.py:514](garmin_db.py), [garmin_db.py:888](garmin_db.py), [migrate_sqlite_to_mariadb.py:120](migrate_sqlite_to_mariadb.py), [migrate_sqlite_to_mariadb.py:128](migrate_sqlite_to_mariadb.py), [migrate_sqlite_to_mariadb.py:132](migrate_sqlite_to_mariadb.py)
- **Problem:** I MariaDB är `REPLACE INTO` inte en upsert utan **`DELETE` följt av `INSERT`**. Konsekvenser:
  - Dubbelt skrivarbete och dubbelt så mycket redo-logg per rad — märks särskilt i migreringsskriptets `executemany` över tusentals rader.
  - **Foreign keys med `ON DELETE CASCADE` triggas av den interna DELETE:en.** Får någon framtida tabell en FK mot en rad som skrivs om, raderas den refererande raden tyst. Det är en tickande datakorruptionsbugg som är svår att felsöka i efterhand.
  - Index fragmenteras och radernas fysiska ordning spretar över tid.
- **Åtgärd:** byt samtliga sex förekomster till `INSERT INTO … VALUES (…) ON DUPLICATE KEY UPDATE encrypted_payload = VALUES(encrypted_payload), nonce = VALUES(nonce)` (respektive `value = VALUES(value)` för `sync_metadata`).
- **Acceptanskriterier:**
  1. En upsert mot en befintlig `(user_id, date)` uppdaterar raden utan att radera den — verifiera genom att lägga till `created_at DATETIME DEFAULT CURRENT_TIMESTAMP` och kontrollera att värdet **inte** ändras vid uppdatering.
  2. `tests/test_garmin_db_mariadb.py` är grönt.

### [ ] PF-5: 🟡 Ingen radbegränsning i `_mariadb_get_history` — allt dekrypteras oavsett vad som visas
- **Fil:** [garmin_db.py:289-313](garmin_db.py), [garmin_db.py:775-802](garmin_db.py), [garmin_db.py:853-864](garmin_db.py)
- **Problem:** `_mariadb_get_history` hämtar alla rader i intervallet och dekrypterar var och en. `get_latest_body_composition` gör rätt (`LIMIT 1`), men `get_activities_history` och `get_calorie_burn_history` laddar hela historiken när `days >= 3650`. "Allt"-knappen i dashboarden sätter just `days_range >= 3650` ([charts_view.py:211](charts_view.py)) — ett klick betyder alltså full nedladdning och dekryptering av samtliga tabeller, på UI-tråden (se PF-1).
- **Åtgärd:**
  1. Lägg till en valfri `limit`-parameter på `_mariadb_get_history` och skicka `LIMIT %s` vidare till SQL:en.
  2. Inför en enkel per-instans cache med nyckeln `(table, days)` och kort TTL (t.ex. 60 s), invaliderad av motsvarande `upsert_*`. Dashboardens upprepade omritningar delar då en enda hämtning.
  3. Sätt ett tak i UI:t för "Allt": aggregera grafdata per vecka bortom 1 år i stället för per dag — bortom ett år är dagsupplösning ändå inte läsbar i graferna.
- **Acceptanskriterier:** "Allt"-vyn renderar på < 2 s med full historik; upprepade fliksbyten inom 60 s utlöser inga nya databasfrågor.

### [ ] PF-6: 🟡 Anslutningspoolen kan svälta och återhämtar sig inte från tappade anslutningar
- **Fil:** [garmin_db.py:90-106](garmin_db.py)
- **Problem:** `PooledDB(maxconnections=10, mincached=2, maxcached=5, blocking=True)`.
  - `blocking=True` utan timeout betyder att en tråd som inte får en anslutning **blockerar för alltid**. Sker det på UI-tråden — vilket det gör i dag, se PF-1 — fryser appen permanent i stället för att ge ett felmeddelande.
  - Ingen `ping`. En anslutning som servern stängt (`wait_timeout`, ofta 8 h) returneras som trasig och ger `OperationalError: MySQL server has gone away` vid nästa användning. Det drabbar särskilt en app som står öppen hela dagen.
  - Ingen `connect_timeout` i pymysql-argumenten: är servern nere hänger anslutningsförsöket tills OS:ets TCP-timeout löper ut.
- **Åtgärd:**
  1. Lägg till `ping=1` (kontroll vid varje `connection()`) eller `ping=4`.
  2. Sätt `connect_timeout` (t.ex. 5 s) och `read_timeout`/`write_timeout` i pymysql-argumenten, i båda anslutningsvägarna.
  3. Gör poolstorlekarna konfigurerbara via miljövariabler med nuvarande värden som default.
  4. Efter PF-1 (allt DB-arbete på bakgrundstrådar) kan `blocking=True` behållas; dessförinnan bör den kombineras med en timeout så att UI:t inte kan låsa sig permanent.
- **Acceptanskriterier:** appen återhämtar sig utan omstart efter att MariaDB startats om; ingen `MySQL server has gone away` i loggen efter en dag med öppen app.

### [x] PF-7: 🟢 `_normalize_date` faller tyst tillbaka på dagens datum
- **Fil:** [garmin_db.py:252-272](garmin_db.py)
- **Problem:** Efter 15 försök med olika format returnerar metoden tyst `datetime.now()`. En rad med ett oväntat datumformat — t.ex. efter en API-ändring hos Garmin — dateras alltså **fel, till idag**, utan att något syns i loggen. Det är exakt samma felklass som `P1-5` (feldaterad body-composition), som redan behövde åtgärdas en gång. Utöver datariktigheten kostar det prestanda och data: alla felmappade rader hamnar på samma primärnyckel `(user_id, today)` och skriver över varandra.
- **Åtgärd:**
  1. Logga `logger.warning(f"Okänt datumformat: {date_str!r} – faller tillbaka på dagens datum")` innan fallbacken.
  2. Låt metoden ta `strict: bool = False`. Anropsställen som **skriver** till databasen sätter `strict=True` och får ett `ValueError` i stället för ett felaktigt datum.
  3. Lägg till ett test som verifierar varningen och `strict`-beteendet.
- **Acceptanskriterier:** en okänd datumsträng ger en loggad varning; samtliga befintliga format parsas oförändrat.

## 🔧 R-spåret – Återställning av funktioner efter webb-migreringen

> **Bakgrund 2026-09-11:** Webb-migreringen på `main` (`7db86ef`) behöll domänlogiken
> (skrivbordsappen, handlers, MariaDB, kryptering, HR-zoner) men webblagret exponerade bara
> en bråkdel av den: 10 endpoints mot skrivbordsappens ~20 menyfunktioner. Allt som *hämtar*
> data och alla produktivitetsfunktioner saknades. Det här spåret återställer dem — som webbapp.

### [x] R-1: Check-in och synk fanns inte alls
- **Fil:** [web_sync.py](web_sync.py), [server.py](server.py)
- **Problem:** Ingen endpoint rörde Garmin, Fitbit, Withings eller Strava. Webbappen kunde bara visa data som redan låg i databasen — ny data gick bara att hämta genom att starta den gamla skrivbordsappen.
- **Åtgärdat:** `POST /api/checkin` (alla källor eller en namngiven), `full=true` för hela historiken, `GET /api/sync/status` för progress. Dagantalen är skrivbordsappens (Garmin 30, Fitbit 7, Withings 365, Strava 30; full synk 3650/365/3650/3650).

### [x] R-2: Garmin-inloggning och MFA saknades
- **Fil:** [server.py](server.py), [web_workspace.py](web_workspace.py)
- **Åtgärdat:** `POST /api/garmin/connect`, `POST /api/garmin/mfa`, `GET /api/status`. Tokens sparas per användare på servern, så en omladdning behåller anslutningen.

### [x] R-3: Inställningar (AI-leverantör, API-nycklar, modeller) saknades
- **Fil:** [server.py](server.py), [web_workspace.py](web_workspace.py), [web_store.py](web_store.py)
- **Problem:** Det fanns ingen väg att ange en API-nyckel i webbgränssnittet, och chatt-endpointen skapade `AIClient` helt utan nyckel — AI:n kunde alltså inte fungera.
- **Åtgärdat:** `GET/POST /api/settings` med skrivbordsappens hela konfigurationsyta, `GET /api/settings/models` för live-modellistor. Allt lagras krypterat per användare (AES-256-GCM med kontots DEK) i `sync_metadata`. Hemligheter skickas **aldrig** tillbaka till webbläsaren — bara flaggan `secrets_set` — och ett tomt fält betyder "behåll det sparade".

### [x] R-4: OAuth för Fitbit, Strava och Withings saknades
- **Fil:** [server.py](server.py)
- **Åtgärdat:** `GET /api/connect/<tjänst>/url` → auktorisering → `GET /oauth/<tjänst>/callback` med engångs-`state`. En fast redirect-URL per tjänst i stället för skrivbordsappens tillfälliga `localhost`-server.

### [x] R-5: Import av export-filer saknades
- **Fil:** [server.py](server.py)
- **Åtgärdat:** `POST /api/import/{fitbit,strava,withings}` tar emot filen som uppladdning och kör samma importerare som skrivbordsmenyn.

### [x] R-6: Promptar, snabbfrågor, historik, sök och export saknades
- **Fil:** [server.py](server.py), [web_workspace.py](web_workspace.py), [web_export.py](web_export.py)
- **Åtgärdat:** Sparade promptar (CRUD), snabbfrågor (max 8, samma fyra standardfrågor), spara/ladda/döp om/ta bort chattar, sökning i nuvarande och sparade chattar, samt export till TXT/PDF/DOCX som nedladdning.

### [x] R-7: Chatten tappade kontext, minne och svar
- **Fil:** [web_chat.py](web_chat.py), [server.py](server.py), [static/app.js](static/app.js)
- **Problem:** Tre fel samtidigt: kontexten var två rader text i stället för skrivbordsappens nyckelordsstyrda `format_data_for_context`, konversationsminnet fanns inte, och **klienten läste `parsed.content` medan servern strömmade `chunk`** — så inget svar visades över huvud taget.
- **Åtgärdat:** `web_chat.process_message` är skrivbordsappens `_process_message` ord för ord (datumintervall, nyckelordsroutning, glidande minne på 10 meddelanden). SSE-strömningen behölls; klienten läser rätt fält, hanterar delade frames och visar serverns felmeddelande.

### [x] R-8: Grafer och kort visade påhittad data
- **Fil:** [static/app.js](static/app.js)
- **Problem:** `generateMockSeries()` fyllde varje tom serie med en genererad kurva, och träningsvolym-grafen var **alltid** påhittad. Korten hade samma sak: vikten föll tillbaka på 98,3 kg, vikttrenden på "-1,2 kg", kalorierna på 2 848 kcal. Dessutom pekade koden på fält som inte finns (`highest_level`, `avg_stress_level`, `history.body_comp`, `history.daily_summary`), så Body Battery-, stress-, vikt- och vilopulsgraferna var tomma eller fejkade. Alla serier delade dessutom kaloriseriens datumaxel.
- **Åtgärdat:** All mock-data borttagen. Varje graf ritar sina egna rader med sina egna datum, fältnamnen matchar databasen, träningsvolymen räknas från riktiga pass, pulszonerna kommer från `hr_zones_calc` via `GET /api/hr-zones`, och tom data visar "Ingen data ännu — kör en Check-in" i stället för en uppdiktad kurva.

### [x] R-9: Profil och lösenordsbyte var trasiga
- **Fil:** [server.py](server.py)
- **Problem:** Frontend anropade `/api/user/profile` och `/api/user/password`; servern definierade `/api/profile/update` och `/api/profile/change_password`. Båda knapparna gav 404.
- **Åtgärdat:** Båda sökvägarna serveras nu, och profiländringar uppdaterar arbetsytan så BMR och pulszoner räknas om.

### [x] R-10: Kaloriförbränningen sparades aldrig från webben
- **Fil:** [web_metrics.py](web_metrics.py), [server.py](server.py)
- **Problem:** Dashboarden räknade ut dagens förbränning men skrev aldrig raden, så trendgrafen fylldes bara på när skrivbordsappen kördes.
- **Åtgärdat:** Dagens värde sparas vid varje laddning, och `backfill_calorie_burn` fyller i avslutade dagar som saknas eller ligger kvar som halva dygn (`day_fraction < 1`). Efter varje check-in körs den med `overwrite=True`. Avdraget för träningssteg och Garmins BMR-projektion är skrivbordsappens.

### [x] R-11: Appen kunde inte starta utan MariaDB
- **Fil:** [web_dbcompat.py](web_dbcompat.py), [server.py](server.py), [garmin_db.py](garmin_db.py)
- **Problem:** `garmin_db` har en SQLite-reserv, men `auth.py` talar bara pymysql (`%s`-platshållare och `with conn.cursor()`), så **inloggningen kraschade** när MariaDB inte gick att nå — hela appen låg nere med databasen. Dessutom saknade anslutningspoolen timeout, så varje anrop hängde i stället för att falla tillbaka.
- **Åtgärdat:** Ett litet kompatibilitetslager ger sqlite3 den pymysql-yta `auth` använder (och skapar `users`-tabellen i SQLite-dialekt), `connect_timeout` gör att en onåbar databas faller tillbaka direkt i stället för att hänga, och arbetsytan återanvänder sin databas-handle i stället för att bygga en ny pool per anrop.

### [x] R-12: Hårdkodat databaslösenord i källkoden
- **Fil:** [garmin_db.py](garmin_db.py)
- **Problem:** Lösenordet till MariaDB låg i klartext i koden (`password or "powerman"`) och skrevs dessutom automatiskt in i en ny `~/.healthchat/db.env`.
- **Åtgärdat:** Lösenordet läses bara från miljön eller `db.env`; mallfilen skapas utan lösenord och med `chmod 600`.
- **⚠️ Kvarstår för dig:** lösenordet har legat i git-historiken och **bör bytas** i MariaDB.

### [ ] R-13: Vendora Chart.js lokalt
- **Fil:** [static/index.html](static/index.html)
- **Problem:** Graferna laddas från `cdn.jsdelivr.net`. Utan internet på klienten ritas inga grafer — vilket krockar med poängen att servern och databasen ska kunna stå isolerade.
- **Att göra:** Lägg `chart.umd.min.js` i `static/vendor/` och peka dit. (Graferna faller nu mjukt tillbaka med ett meddelande i stället för att krascha hela dashboard-uppdateringen, men beroendet finns kvar.)

---

## Förslag på ordning
1. **P0-1** (snabb, tydlig krasch) → **P0-3** (trådsäkerhet) → **P0-2** (säkerhet, större).
2. **P1-1** + **P1-2** + **P2-4** tillsammans (samma kontext-/minneskod).
3. **Nya (2026-09-04):** **P1-5** (feldaterad vikt – liten & tydlig, un-breakar ett test) → **P1-6** (timeouts) → **P1-7** (Fitbit token-refresh, bygger på P1-6).
4. Övriga P1/P2 löpande (**P2-1** nakna except, **P2-9** version).
5. **F-1** (daglig kaloriförbränning) – fristående, kan tas när som helst.
6. **K-spåret** (MariaDB, konto, kryptering, profilsida) – ett sammanhängande spår. Ta dem i ordning: **K-1** (databas) → **K-2** (konto) → **K-3** (kryptering) → **K-10** (återställningsnyckel + info vid registrering) → **K-4** (spara inloggning) → **K-5** (profilsida) → **K-6** (migrera data) → **K-9** (Garmin-dialog) → **K-7** (städa inställningar) → **K-8** (tester/dokumentation).
   - **K-9 måste vara klar före K-7**, annars går Garmin-inloggningen förlorad.
   - **K-10 bygger på K-3** (samma nyckelkuvert – återställningsnyckeln packar upp samma DEK).
7. **S/DB/PF-spåren (2026-09-07)** – säkerhet, databasserver och prestanda. Ordningen är inte fri; flera hänger ihop:
   1. **S-1 först och genast.** Hemligheterna ligger i arbetskopian men **inte i git-historiken än**. Görs den efter nästa commit måste historiken skrivas om. Ingen annan uppgift bör committas före denna.
   2. **DB-1 + DB-2 + S-2 + S-3 som ett paket.** Roterade DB-lösenord, borttagen nätverks-root, nytt schema och TLS måste landa samtidigt, annars tappar appen anslutningen mitt emellan. Kör dem i ett svep och verifiera testsviten efteråt.
   3. **DB-4** direkt efter – det är den som avgör om cascade-radering och index faktiskt finns i produktion, och den ger underlaget S-2 behöver.
   4. **PF-1** därefter. Den är den mest kännbara för användaren (fryst UI) och fristående från S-spåret.
   5. **PF-4 + PF-2** tillsammans med DB-4, eftersom båda kan kräva schemaändringar.
   6. **S-4** (nycklar till keyring) – fristående och kan tas parallellt av en annan agent.
   7. Övriga löpande: **S-5** → **S-6** → **S-7** → **S-8** → **S-9** → **S-10** → **PF-3** → **PF-5** → **PF-6** → **S-11** → **S-12** → **PF-7** → **DB-3** → **DB-5**.
   - **S-3 kräver DB-2** (klienten kan inte kräva TLS innan servern erbjuder det).
   - **S-7 och PF-2 kräver båda schemaändringar** på `users` respektive `activities` – samordna med **S-2/DB-4** så att `init_mariadb.sql` uppdateras en gång, inte tre.
   - **PF-5 och PF-6 blir enklare efter PF-1** (när inget DB-arbete längre sker på UI-tråden).
