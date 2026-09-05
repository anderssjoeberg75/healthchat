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

### [ ] P1-5: `extract_body_composition` ignorerar sitt `date_str`-argument → invägningar feldateras till idag
- **Fil:** [garmin_handler.py:1118-1123](garmin_handler.py) (`extract_body_composition`), [garmin_handler.py:1092-1095](garmin_handler.py) (`parse_body_composition_records`, `totalAverage`-grenen)
- **Problem:** `extract_body_composition(data, date_str)` tar emot ett `date_str` men skickar det aldrig vidare till `parse_body_composition_records`. När svaret bara har ett `totalAverage` (utan `date`/`startDate`) faller parsern tillbaka på `datetime.now()`, så mätningen får **dagens** datum i stället för det avsedda. En Withings/Garmin-invägning kan därmed hamna på fel dag i `body_composition`-tabellen och i vikt-trenden.
- **Bevis:** Det befintliga testet [tests/test_garmin_handler.py](tests/test_garmin_handler.py) `test_extract_body_composition` misslyckas idag: `assert res["date"] == "2026-08-25"` men får dagens datum.
- **Föreslagen lösning:** Ge `parse_body_composition_records(data, default_date=None)` en parameter och använd `default_date` i stället för `datetime.now()` i `totalAverage`-grenen; låt `extract_body_composition` skicka in `date_str`. Behåll `datetime.now()` endast som sista reserv om `default_date` saknas.
- **Acceptanskriterier:** `test_extract_body_composition` grönt; `dateWeightList`-formatet (som har egna datum) påverkas inte; hela sviten `python -m pytest` grön.

### [ ] P1-6: HTTP-anrop utan `timeout` i Fitbit/Strava → sync-tråden kan hänga för evigt
- **Fil:** [fitbit_handler.py:108](fitbit_handler.py), [fitbit_handler.py:162](fitbit_handler.py); [strava_handler.py:119](strava_handler.py), [strava_handler.py:148](strava_handler.py), [strava_handler.py:184](strava_handler.py), [strava_handler.py:189](strava_handler.py)
- **Problem:** Samtliga `requests.get/post` i Fitbit- och Strava-handlarna saknar `timeout`. Vid en stiltje i nätverket blockerar anropet tråden oändligt – Check-in/knappen fastnar på "Synkar…" och slutför aldrig. (Withings gör redan rätt: `requests.post(..., timeout=15)`.)
- **Föreslagen lösning:** Lägg `timeout=(5, 30)` (connect, read) på varje `requests`-anrop i båda filerna. Fånga `requests.exceptions.Timeout`/`RequestException` och logga + sätt `last_error` i stället för att låta tråden hänga.
- **Acceptanskriterier:** Inget `requests`-anrop i `fitbit_handler.py`/`strava_handler.py` saknar `timeout`; en simulerad timeout avbryter synken med ett loggat fel i stället för att hänga.

### [ ] P1-7: Fitbit uppdaterar aldrig sin OAuth-token → integrationen slutar tyst spara data efter att token gått ut
- **Fil:** [fitbit_handler.py:116-119](fitbit_handler.py) (`_get_headers`), synk-loopen [fitbit_handler.py:159-165](fitbit_handler.py); jämför [strava_handler.py:137-160](strava_handler.py) som gör rätt
- **Problem:** `FitbitHandler` har ingen `refresh_access_token`. `_get_headers` använder bara den lagrade `access_token` och synk-loopen hoppar tyst över dagar som ger `401`. Fitbits access-token går ut (~8 h), varefter synken "lyckas" men sparar inget – användaren måste logga in manuellt igen. Strava löser detta (uppdaterar token + gör en retry på 401 och persisterar via `save_tokens`).
- **Föreslagen lösning:** Implementera `refresh_access_token()` (grant_type=`refresh_token`, spara via `save_tokens`), anropa den i `_get_headers` när token är nära utgång (om `expires_at` finns), och gör en engångs-retry på `401` i synk-loopen – spegla Stravas mönster. Lägg `timeout` enligt P1-6.
- **Acceptanskriterier:** Efter att access-token gått ut hämtar och sparar en ny Check-in data utan manuell ominloggning; refreshade tokens skrivs till `fitbit_tokens.json`.

---

## 🟡 P2 – Kodkvalitet & underhåll

### [ ] P2-1: Nakna `except:` som sväljer fel (inkl. `KeyboardInterrupt`/`SystemExit`)
- **Fil & platser:** [HealthChatDesktop.py](HealthChatDesktop.py) rad 4048, 4057, 4072, 4082, 4091, 4098, 5244, 5272, 5304, 5323, 5425; [ai_client.py](ai_client.py) rad 156, 361, 394.
- **Problem:** Ett naket `except:` fångar även `KeyboardInterrupt` och `SystemExit`, vilket kan göra appen svår att avbryta och döljer verkliga fel.
- **Föreslagen lösning:** Ersätt varje `except:` med `except Exception:` (eller en mer specifik typ) och logga på `debug`/`warning`-nivå där det är meningsfullt.
- **Acceptanskriterier:** Inga nakna `except:` kvar i kodbasen (`grep -rn "except:" *.py` tomt).

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

### [ ] P2-9: `requirements.txt` versions-header ligger efter (v4.0.4 vs släppt v4.0.5)
- **Fil:** [requirements.txt:1](requirements.txt) (`# HealthChat Desktop v4.0.4 Dependencies`), jämför [CHANGELOG.md](CHANGELOG.md) (`## [4.0.5] - 2026-08-20`)
- **Problem:** Kommentarshuvudet i `requirements.txt` säger fortfarande v4.0.4 trots att v4.0.5 är släppt – liten men förvirrande drift (samma sak som P2-7 avsåg).
- **Föreslagen lösning:** Uppdatera versionskommentaren till aktuell version och överväg en enda källa för versionsnumret (t.ex. `__version__`).
- **Acceptanskriterier:** Versionshuvudet matchar senaste släppta version i `CHANGELOG.md`.

---

## 🟢 Funktioner (önskemål)

### [ ] F-1: Daglig kaloriförbränning – ruta på dashboarden + spara för trend
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

### [ ] K-1: Byt databas-backend från SQLite till MariaDB (med connection pool)
- **Fil:** [garmin_db.py](garmin_db.py) (hela lagret), anropas från [HealthChatDesktop.py](HealthChatDesktop.py), [charts_view.py](charts_view.py), [garmin_handler.py](garmin_handler.py), [fitbit_handler.py](fitbit_handler.py), [strava_handler.py](strava_handler.py), [withings_handler.py](withings_handler.py)
- **Mål:** All lagring sker i MariaDB (`192.168.101.106`, port 3306, databas `healthchat`) i stället för `~/.healthchat/healthdata.db`.
- **Att göra:**
  - Lägg till driver `PyMySQL` (ren Python → enklast att paketera med PyInstaller) i `requirements.txt`.
  - **Prestandakritiskt:** dagens `get_connection()` öppnar en **ny anslutning per operation**. Mot SQLite är det gratis, men mot en nätverksdatabas kostar varje anrop en TCP- + auth-rundtur och gör appen märkbart trög. Inför en **connection pool** (t.ex. `dbutils.PooledDB` eller en egen enkel pool) och återanvänd anslutningar.
  - Översätt schemat: `INTEGER`→`INT`, `REAL`→`DOUBLE`, `TEXT`→`VARCHAR(n)`/`TEXT`, `ON CONFLICT(x) DO UPDATE`→`INSERT ... ON DUPLICATE KEY UPDATE`, `PRAGMA journal_mode=WAL` tas bort.
  - Lägg kolumnen **`user_id`** på *alla* datatabeller (`daily_summary`, `sleep_data`, `body_battery`, `stress_data`, `hrv_data`, `activities`, `body_composition`, `calorie_burn`, `sync_metadata`) med **sammansatt primärnyckel** `(user_id, date)` (för `activities`: `(user_id, activity_id)`) och FK mot `users(id)` med `ON DELETE CASCADE`.
  - **Varje** SELECT/INSERT/UPDATE/DELETE måste filtrera på `WHERE user_id = ?`. Ingen fråga får gå utan användarfilter.
  - Index på `(user_id, date)` för alla historiktabeller.
  - Anslutningen ska använda **TLS** mot MariaDB. DB-värd/port/databas/användare läses från `~/.healthchat/config.json`; **DB-lösenordet lagras i OS-nyckelringen** (`keyring`), inte i klartext i config.
  - Skapa DB-användaren med **minsta möjliga rättigheter** (SELECT/INSERT/UPDATE/DELETE på `healthchat`, inget GRANT/DROP).
- **Acceptanskriterier:** Appen startar och synkar mot MariaDB utan SQLite; inga kvarvarande `sqlite3`-anrop i drift­vägen (endast i migreringen, K-6); ingen fråga saknar `user_id`-filter; en Check-in på 30 dagar är inte långsammare än tidigare (tack vare poolen).

### [ ] K-2: Användarkonton – registrering och inloggning
- **Fil:** ny `auth.py`; startflödet i [HealthChatDesktop.py](HealthChatDesktop.py) (`main()` / `HealthChatApp.__init__`)
- **Mål:** Appen kräver inloggning innan dashboarden visas, och nya användare kan registrera sig.
- **Att göra:**
  - Tabell `users`: `id` (PK), `email` (UNIQUE), `password_hash`, `kdf_salt` (BLOB), `wrapped_dek` (BLOB), `dek_nonce` (BLOB), `created_at`, `updated_at`.
  - **Lösenordshash:** `argon2-cffi` (Argon2id). Lösenordet lagras **aldrig** i klartext eller reversibelt.
  - Ny **inloggningsdialog** som visas före huvudfönstret: e-post, lösenord, kryssruta **"Spara inloggning"** (se K-4), knapp **"Registrera ny användare"**.
  - Registrering: validera e-postformat, kräv lösenordslängd (min 10 tecken), bekräfta lösenord, skapa användare + DEK (se K-3).
  - Fel vid inloggning ska ge ett generiskt meddelande ("Fel e-post eller lösenord") – avslöja inte om e-posten finns.
  - Enkel bromsning (t.ex. ökande fördröjning efter 5 misslyckade försök) mot lösenordsgissning.
  - 🔗 **Registreringen är inte klar utan K-10:** informationsrutan om att datan inte kan räddas vid glömt lösenord, och genereringen av återställningsnyckeln, hör till registreringssteget.
- **Acceptanskriterier:** Går inte att nå dashboarden utan giltig inloggning; ny användare kan registreras och loggar in; `users`-tabellen innehåller ingen läsbar lösenordsinformation.

### [ ] K-3: Kryptering av all hälsodata (envelope encryption, snabb)
- **Fil:** ny `crypto.py`; används av [garmin_db.py](garmin_db.py)
- **Mål:** Den som kommer åt MariaDB ska **inte** kunna läsa hälsodatan i klartext. Samtidigt ska appen inte bli långsam.
- **Design (nyckelkuvert – detta är kärnan):**
  1. Varje användare får en slumpad **DEK** (Data Encryption Key, 256 bit).
  2. En **KEK** (Key Encryption Key) härleds från användarens lösenord med **Argon2id** + per-användare-salt.
  3. I databasen sparas endast **`wrapped_dek = AES-256-GCM(KEK, DEK)`**. DEK finns aldrig i klartext i databasen.
  4. Vid inloggning: härled KEK ur lösenordet → packa upp DEK → håll DEK **endast i minnet** under sessionen.
  5. All hälsodata krypteras med DEK via **AES-256-GCM** (unik nonce per rad/fält, autentiserad kryptering).
- **Varför det är snabbt:** Argon2id körs **en gång per inloggning** (sikta på ~200–500 ms), inte per fråga. AES-GCM använder hårdvaruacceleration (AES-NI) och ligger på GB/s – krypteringen är försumbar för den här datamängden. **Byte av lösenord kräver ingen omkryptering av data** – bara att DEK packas om med en ny KEK (K-5).
- **Vad som krypteras vs. inte (medvetet avvägande – dokumentera i README):**
  - **Krypterat:** alla mätvärden/nyttolast (steg, kalorier, puls, sömn, vikt, aktivitetsnamn, `raw_json` osv.). Lagra helst hela radens värden som **en krypterad blob** per rad i stället för kolumn-för-kolumn – färre nonces och snabbare.
  - **Klartext (behövs som index för att frågor ska vara snabba):** `user_id`, `date` och `activity_id`.
  - **Konsekvens:** en DB-administratör kan se *att* du har data ett visst datum, men inte *vad* den innehåller. Vill man dölja även datum kan de ersättas med ett **HMAC-blindat index** (valfri härdning, gör intervallfrågor svårare).
- **Att göra:** använd `cryptography` (AESGCM) och `argon2-cffi`. Nyckelmaterial får aldrig loggas. Rensa DEK ur minnet vid utloggning/avslut.
- **Acceptanskriterier:** `SELECT * FROM daily_summary` i en MariaDB-klient visar **oläsbar** data för alla mätvärden; appen visar dem korrekt efter inloggning; enhetstest för kryptera→dekryptera-rundgång och för wrap/unwrap av DEK; manipulerad ciphertext ger fel (GCM-autentisering).

### [ ] K-4: "Spara inloggning" utan att lagra lösenordet
- **Fil:** `auth.py`, inloggningsdialogen i [HealthChatDesktop.py](HealthChatDesktop.py)
- **Problem att undvika:** Kryssrutan får **inte** lösas genom att spara lösenordet i klartext i `config.json` – det skulle rasera hela K-3.
- **Föreslagen lösning:** Spara en **enhetsskyddad kopia av DEK** i OS-nyckelringen via `keyring` (på Windows = Credential Manager, skyddad av DPAPI och bunden till Windows-kontot), tillsammans med e-postadressen. Vid start: finns posten → packa upp DEK därifrån och hoppa över lösenordsprompten. Lösenordet i sig sparas aldrig.
- **Att göra:** "Logga ut"-funktion som raderar nyckelringsposten och DEK ur minnet; posten raderas även vid kontoborttagning (K-5) och vid lösenordsbyte om användaren väljer det.
- **Acceptanskriterier:** Med "Spara inloggning" ikryssad startar appen direkt utan lösenord; ingen fil i `~/.healthchat/` innehåller lösenordet eller DEK i klartext; "Logga ut" gör att lösenord krävs igen.

### [ ] K-5: Profilsida – byt lösenord, ta bort konto, och personliga uppgifter
- **Fil:** ny profilvy (t.ex. flik i [charts_view.py](charts_view.py) eller egen dialog), [HealthChatDesktop.py](HealthChatDesktop.py)
- **Mål:** En samlad **Profil**-sida med kontoinformation och kontoåtgärder.
- **Innehåll:**
  1. **Kontoinfo:** inloggad e-post, konto skapat, senaste inloggning.
  2. **Byt lösenord:** kräver *nuvarande* lösenord + nytt lösenord (två gånger). Implementation: verifiera nuvarande lösenord → packa upp DEK med gammal KEK → härled ny KEK ur nya lösenordet → spara ny `wrapped_dek` + nytt salt + ny `password_hash`. **Ingen data behöver krypteras om** → operationen tar bråkdelar av en sekund.
  3. **Ta bort konto och all data:** raderar alla rader för användaren i samtliga tabeller (`ON DELETE CASCADE`) + `users`-raden + nyckelringsposten (K-4).
     - **Måste ha en tydlig bekräftelsefråga innan borttagning:** en dialog som varnar att åtgärden är **permanent och inte går att ångra**, och som kräver aktiv bekräftelse – låt användaren skriva sin e-postadress (eller ordet `RADERA`) för att knappen ska aktiveras. Avbryt ska vara förvalt.
  4. **Personliga uppgifter:** flytta hit sektionen **"Personlig profil (för kaloriberäkning)"** (kön, längd, ålder, vikt) från inställningsdialogen – se K-7.
- **Acceptanskriterier:** Lösenordsbyte fungerar och all befintlig data går fortfarande att läsa efteråt; borttagning kräver aktiv bekräftelse och lämnar **noll** rader kvar för användaren i alla tabeller; appen loggar ut och återgår till inloggningsvyn efter borttagning.

### [ ] K-6: Migrera befintlig SQLite-data till kontot i MariaDB
- **Fil:** ny `migrate_sqlite_to_mariadb.py` (eller ett engångsflöde i appen)
- **Mål:** All historik som redan finns i `~/.healthchat/healthdata.db` ska tillhöra ägarens konto med e-post **`anders@andrix.se`** och bli krypterad på vägen in.
- **Att göra:**
  - **Ta en backup** av `healthdata.db` innan något skrivs.
  - Skapa (eller använd) kontot `anders@andrix.se`. **Lösenordet matas in interaktivt vid migreringen – det får inte stå i kod, config eller board.md.**
  - Läs alla tabeller ur SQLite och skriv in dem i MariaDB med rätt `user_id`, krypterade enligt K-3. Använd **batch-insert** (`executemany`) – inte rad för rad.
  - Migreringen ska vara **idempotent** (går att köra om utan dubbletter, tack vare upsert på `(user_id, date)`).
  - Skriv ut en sammanfattning: antal rader per tabell före/efter.
- **Acceptanskriterier:** Antal rader per tabell matchar källan; dashboarden och graferna visar samma historik som före bytet; SQLite-filen är orörd (backup finns) och används inte längre i drift.

### [ ] K-7: Städa inställningsdialogen – flytta ut källor och personliga uppgifter
- **Fil:** [HealthChatDesktop.py:312-434](HealthChatDesktop.py) (`SettingsDialog.create_widgets`), menyn [HealthChatDesktop.py:1834-1890](HealthChatDesktop.py)
- **Problem:** Inställningar (Arkiv → ⚙️ Inställningar) innehåller idag sektionerna *AI Provider* → *Garmin Connect Credentials* → *Withings API* → *Strava API* → *Personlig profil*. Garmin/Withings/Strava dubblerar det som redan finns under respektive meny (`Garmin`, `Fitbit`, `Withings`, `Strava` har egna "▶ Anslut till …"-poster), och den personliga profilen hör hemma på profilsidan.
- **Att göra:**
  - **Ta bort** sektionerna *Garmin Connect Credentials*, *Withings Health Mate API Credentials* och *Strava API Credentials* ur inställningsdialogen.
  - ⚠️ **Beroende – gör K-9 först:** Garmins e-post/lösenord går idag **bara** att mata in via Inställningar. Tas sektionen bort innan **K-9** (Garmin-anslutningsdialog) är på plats går det inte längre att logga in på Garmin.
  - **Flytta** sektionen *Personlig profil (för kaloriberäkning)* till profilsidan (K-5).
  - Kvar i Inställningar: **endast AI-leverantör och API-nycklar** (samt ev. tema/allmänt).
- **Acceptanskriterier:** Inställningar innehåller inga källspecifika uppgifter; varje källa (Garmin/Fitbit/Withings/Strava) kan anslutas helt från sin egen meny; profilfälten finns på profilsidan och sparas fortfarande; ingen befintlig funktion tappas bort.

### [ ] K-8: Säkerhet, tester och dokumentation för konto-/kryptolagret
- **Fil:** `tests/test_crypto.py`, `tests/test_auth.py` (nya), [README.md](README.md)
- **Att göra:**
  - Enhetstester: kryptera→dekryptera-rundgång; DEK wrap/unwrap; fel lösenord ger fel; **lösenordsbyte bevarar läsbarheten** för redan sparad data; kontoborttagning lämnar noll rader; `user_id`-filter finns i alla frågor.
  - Verifiera manuellt att en `SELECT` direkt mot MariaDB inte visar läsbara hälsovärden.
  - Uppdatera README: hur MariaDB konfigureras, att data är klientkrypterad, vad som är krypterat vs. index i klartext, och att **glömt lösenord innebär att datan inte går att återskapa** (ingen nyckelåterställning finns – överväg en nedladdningsbar återställningsnyckel om det önskas).
  - Inga hemligheter i repot; `keyring` används för DB-lösenord och sparad inloggning.
- **Acceptanskriterier:** `python -m pytest` grönt; README beskriver säkerhetsmodellen korrekt; inga nycklar/lösenord i git-historiken.

### [ ] K-9: Garmin-anslutningsdialog under Garmin-menyn (förutsättning för K-7)
- **Fil:** [HealthChatDesktop.py](HealthChatDesktop.py) – ny dialogklass i stil med [`FitbitConnectDialog`:715](HealthChatDesktop.py), [`StravaConnectDialog`:899](HealthChatDesktop.py), [`WithingsConnectDialog`:1093](HealthChatDesktop.py); menyn [`garmin_menu`:1850-1854](HealthChatDesktop.py); [`connect_to_garmin`:3184](HealthChatDesktop.py); [`prompt_for_credentials`:1644](HealthChatDesktop.py)
- **Problem (fallgropen):** Garmins e-post och lösenord går **bara** att mata in via Arkiv → Inställningar. `prompt_for_credentials()` öppnar inställningsdialogen, och `connect_to_garmin()` visar felmeddelandet *"Please configure your Garmin credentials in Settings"*. Så fort K-7 tar bort Garmin-sektionen ur Inställningar finns **ingen väg alls** att mata in uppgifterna → Garmin-inloggningen slutar fungera. Garmin är dessutom den enda källan utan egen anslutningsdialog (Fitbit, Strava och Withings har redan var sin).
- **Att göra:**
  - Skapa **`GarminConnectDialog`** (en `tk.Toplevel` som speglar de tre befintliga dialogerna: samma tema/färger, `transient` + `grab_set`, `self.result`-mönster, Spara/Avbryt).
  - Fält: **E-post** och **Lösenord** (maskerat), kort hjälptext om att uppgifterna sparas lokalt, samt en **"Anslut"-knapp** som sparar och direkt kör anslutningen.
  - Koppla dialogen till menyn: `Garmin → ▶ Anslut till Garmin Connect` ska öppna den när uppgifter saknas, och lägg till en egen post **`⚙️ Garmin-inloggning…`** så att uppgifterna alltid går att ändra utan att först koppla ner.
  - Uppdatera `connect_to_garmin()` så att felmeddelandet öppnar **den nya dialogen** i stället för att hänvisa till Inställningar; dela upp kontrollen så att *saknad AI-nyckel* och *saknade Garmin-uppgifter* ger olika, korrekta meddelanden (AI-nyckel → Inställningar, Garmin → Garmin-dialogen).
  - Uppdatera `prompt_for_credentials()` (första start) så att den hänvisar till rätt ställen: AI-nyckel under Inställningar, Garmin under Garmin-menyn.
  - ⚠️ **Rör inte MFA-flödet:** MFA-rutan (`mfa_frame`, `submit_mfa`) sitter i **huvudfönstret**, inte i en dialog. Dialogen ska stänga sig och låta det befintliga MFA-flödet ta vid – MFA-koden ska alltså fortsatt matas in i huvudfönstret.
  - Efter K-2/K-3: spara Garmin-uppgifterna i den **krypterade** användarprofilen i stället för `config.json`.
- **Acceptanskriterier:** Garmin går att ansluta **helt från Garmin-menyn** utan att öppna Inställningar; befintliga sparade uppgifter fungerar precis som förut; MFA-inloggning fungerar oförändrat; inget felmeddelande hänvisar längre till Garmin-uppgifter i Inställningar.

### [ ] K-10: Återställningsnyckel + tydlig information vid registrering
- **Fil:** `auth.py`, `crypto.py`, registrerings-/inloggningsdialogen och profilsidan i [HealthChatDesktop.py](HealthChatDesktop.py)
- **Bakgrund:** Krypteringen i K-3 innebär att nyckeln härleds ur användarens lösenord och aldrig finns i databasen. Det är själva poängen – men konsekvensen är att **ett glömt lösenord betyder att all data är förlorad**. Användaren måste få veta det *innan* kontot skapas, och erbjudas en väg tillbaka.
- **Att göra:**
  1. **Informera vid registrering.** Visa en tydlig, svårmissad ruta i registreringssteget som förklarar:
     - att all hälsodata krypteras med användarens lösenord,
     - att **ingen annan – inte ens den som har åtkomst till databasen – kan läsa den**,
     - att **lösenordet inte kan återställas**: glöms det bort går datan inte att rädda utan återställningsnyckeln.
     Texten ska vara på svenska och läsas *före* att kontot skapas – inte gömd i en hjälpfil.
  2. **Generera en återställningsnyckel** vid registrering: 256 bitar slumpdata, visad som lättläst **Base32 i grupper** (t.ex. `K7QF2-9MXTE-…`, 8 grupper om 5 tecken).
  3. **Lagra en andra inpackad kopia av DEK:** `recovery_wrapped_dek = AES-256-GCM(KEK_recovery, DEK)`, där `KEK_recovery` härleds ur återställningsnyckeln med Argon2id + eget salt. Kolumner i `users`: `recovery_wrapped_dek`, `recovery_salt`, `recovery_nonce`. **Själva återställningsnyckeln lagras aldrig** – bara det den kan packa upp.
  4. **Tvinga fram en bekräftelse:** nyckeln visas **en enda gång**, med knapparna **"Kopiera"** och **"Spara som fil…"**, och en kryssruta *"Jag har sparat min återställningsnyckel på ett säkert ställe"* som måste kryssas för att registreringen ska kunna slutföras.
  5. **Återställningsflöde:** länken **"Glömt lösenord?"** i inloggningsdialogen → mata in e-post + återställningsnyckel → packa upp DEK → **tvinga fram ett nytt lösenord** → packa om DEK med den nya KEK:en → **generera en ny återställningsnyckel** (den gamla slutar gälla). Ingen data behöver krypteras om.
  6. **På profilsidan (K-5):** knappen **"Generera ny återställningsnyckel"** (kräver nuvarande lösenord). Den ersätter `recovery_wrapped_dek` så att den gamla nyckeln omedelbart blir ogiltig.
- **Säkerhetskrav:** Återställningsnyckeln är **lika kraftfull som lösenordet** – det ska stå i texten, och användaren ska uppmanas att förvara den offline (utskrift/lösenordshanterare). Nyckeln får **aldrig** loggas, sparas i `config.json`, skickas med e-post eller hamna i git. Samma bromsning mot gissning som för lösenord (K-2) ska gälla återställningsförsök.
- **Acceptanskriterier:** Registrering går inte att slutföra utan att informationen visats och kryssrutan bockats; en användare som "glömt" sitt lösenord kan med enbart återställningsnyckeln sätta ett nytt lösenord och **läsa all sin gamla data**; efter att en ny nyckel genererats slutar den gamla att fungera; enhetstest som täcker återställnings-rundgången (registrera → packa upp med återställningsnyckel → nytt lösenord → data läsbar) och att fel nyckel avvisas.

> **Valfri härdning (utanför grundomfånget):** Appen ansluter direkt till MariaDB med delade DB-uppgifter, vilket innebär att radisoleringen mellan användare upprätthålls av applikationen (`WHERE user_id = ?`) – inte av databasen. Vill man ha starkare isolering: ge varje användare ett eget DB-konto, eller lägg ett litet API-lager framför databasen. Krypteringen (K-3) skyddar ändå innehållet även om raderna skulle läsas.

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
