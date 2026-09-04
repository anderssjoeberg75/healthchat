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

## Förslag på ordning
1. **P0-1** (snabb, tydlig krasch) → **P0-3** (trådsäkerhet) → **P0-2** (säkerhet, större).
2. **P1-1** + **P1-2** + **P2-4** tillsammans (samma kontext-/minneskod).
3. **Nya (2026-09-04):** **P1-5** (feldaterad vikt – liten & tydlig, un-breakar ett test) → **P1-6** (timeouts) → **P1-7** (Fitbit token-refresh, bygger på P1-6).
4. Övriga P1/P2 löpande (**P2-1** nakna except, **P2-9** version).
5. **F-1** (daglig kaloriförbränning) – fristående, kan tas när som helst.
