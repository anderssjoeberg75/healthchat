# 📋 Åtgärdstavla – HealthChat Web

> Uppgiftslista för **Antigravity** baserad på en kodgenomgång av webbapplikationen (2026-09-11).
> Varje uppgift är fristående: den innehåller fil, plats, problem, föreslagen lösning och acceptanskriterier så att en agent kan plocka upp den direkt.
>
> **Prioritet:** `P0` = bugg/säkerhet som påverkar användaren nu · `P1` = viktig robusthet/korrekthet · `P2` = kodkvalitet/underhåll.
>
> ⚠️ **Radnumren är ögonblicksbilder.** De stämde när uppgiften skrevs, men förskjuts så fort någon
> ändrar filen ovanför. Uppgifterna citerar därför alltid den berörda koden eller funktionsnamnet –
> **sök på citatet, lita inte på radnumret**. Hittar du inte koden på angiven rad: kontrollera om en
> tidigare omgång redan åtgärdat uppgiften innan du gör något annat.
>
> **ID-serier:** `B-` buggar/korrekthet · `S-` säkerhet (fortsätter efter `S-12`) · `TLS-` transportkryptering · `UI-` frontend · `PF-` prestanda (fortsätter efter `PF-6`) · `Q-` kodkvalitet.

---

## Sammanfattning

Genomgången omfattar hela webbapplikationen efter migreringen till FastAPI + MariaDB: `server.py`, `auth.py`, `crypto.py`, `garmin_db.py`, `ai_client.py`, `calorie_calc.py`, `hr_zones_calc.py`, `profile_sync.py`, de fyra integrationshandlarna samt `static/app.js`.

Kryptomodulen (`crypto.py`) håller – AES-256-GCM + Argon2id, färska nonces, korrekt KEK/DEK-separation. Auth-lagret (`auth.py`) är i grunden sunt efter `S-1..S-12`. Problemen ligger **runt** kryptot och i webblagret:

- **3 kritiska:** AI-chatten är helt trasig i UI:t (`B-1`), DEK:en lagras i **klartext** i databasen bredvid chiffertexten (`S-13`), och all hälsodata delas mellan användare så fort MariaDB inte svarar (`S-14`).
- **6 allvarliga:** felaktig dedupliceringslogik som slår ihop olika träningspass (`B-2`), BMR som tyst blir 0 (`B-3`), omkastade argument som tömmer profilen mellan workers (`B-4`), påhittade hälsovärden i UI:t (`UI-1`), öppen CORS med credentials (`S-15`) och stored XSS i aktivitetstabellen (`UI-2`).
- Därtill tolv mindre fynd kring OAuth-tokenhantering, connection pooling och kodkvalitet.
- **Ingen transportkryptering:** webbläsare→app och app→MariaDB går båda i klartext (`TLS-1`, `TLS-3`). Klientkrypteringen skyddar data i vila – inte på tråden. Se avsnittet *Transportkryptering*.

**Verifieringsstatus:** `B-2`, `B-3` och `B-6` är reproducerade med körbara skript. Övriga fynd är verifierade genom kodläsning. Testsviten går att köra: `118 passed, 6 skipped` med ett **känt fel som fanns före genomgången** (`test_withings_handler.py::test_sync_profile_weight_from_db`) plus en testmodul som inte kan samlas in headless (`test_charts_view_tabs.py`) – se `Q-9` punkt 7. **Antigravity ska köra `pytest` före och efter varje åtgärd** för att fånga regressioner.

**Arbetsordning:** se avsnittet *Arbetskö för Antigravity* nedan – uppgifterna är grupperade i omgångar med en commit per omgång.

---

## ▶️ Arbetskö för Antigravity

> Uppgifterna nedan är grupperade i **omgångar**. Varje omgång rör i stort sett samma filer och bör bli
> **en commit / en PR**. Ta dem uppifrån och ned – ordningen är vald så att senare omgångar inte river
> upp tidigare arbete. Detaljerna för varje ID står längre ned i dokumentet.
>
> **Före varje omgång:** `pytest` ska vara grönt (se *Miljö* nedan för vad som måste installeras).
> **Efter varje omgång:** `pytest` igen, plus de acceptanskriterier som står under respektive uppgift.
> Bocka av `[ ]` → `[x]` i den här filen som en del av commiten.

### Omgång 1 – Trasig funktionalitet (✅ Klart)
| Ordning | ID | Fil | Omfattning |
|---|---|---|---|
| 1 | `B-1` | `server.py`, `static/app.js` | ✅ Åtgärdad: SSE stream chunk/done, UTF-8 buffer, felmeddelande i UI |
| 2 | `B-4` | `server.py:218` | ✅ Åtgärdad: Rätt argumentordning i decrypt_payload |
| 3 | `B-3` | `server.py:539`, `calorie_calc.py` | ✅ Åtgärdad: Robust viktupplösning & bmr_source none med varning |
| 4 | `B-2` | `garmin_db.py:904` | ✅ Åtgärdad: Robust deduplicering som bevarar distanslösa pass & olika starttider |

Ingen av dessa kräver designbeslut. Alla fyra har reproducerbara felfall beskrivna i sina uppgifter.

### Omgång 2 – Frontend (✅ Klart)
| Ordning | ID | Fil | Omfattning |
|---|---|---|---|
| 5 | `UI-1` | `static/app.js` | ✅ Åtgärdad: Påhittade värden och generateMockSeries borttagna, tomma serier/-- vid saknad data |
| 6 | `UI-2` | `static/app.js` | ✅ Åtgärdad: XSS-escapning via escapeHtml() i aktivitetstabeller och pulszoner |

Gör dem tillsammans – de rör samma renderingsfunktioner. `UI-2` blir enklare efter `UI-1`, eftersom
flera `innerHTML`-block försvinner helt när fallbackvärdena tas bort.

### Omgång 3 – Webbsäkerhet i appen (✅ Klart)
| Ordning | ID | Fil | Omfattning |
|---|---|---|---|
| 7 | `S-15` | `server.py:44-51` | ✅ Åtgärdad: CORS-lista ur ALLOWED_ORIGINS + credentials-skydd |
| 8 | `TLS-2` | `server.py` | ✅ Åtgärdad: secure=True på cookien via COOKIE_SECURE + säkerhetsheaders som middleware |

Samma fil och samma uppstartsblock – gör dem i en omgång. **`TLS-2` punkt 1 (`COOKIE_SECURE`) får inte
slås på i produktion förrän `TLS-1` är klar**, annars slutar inloggningen fungera över HTTP. Låt
default vara `1` men dokumentera flaggan.

### Omgång 4 – Databaslagret (✅ Klart)
| Ordning | ID | Fil | Omfattning |
|---|---|---|---|
| 9 | `TLS-3` (kod) | `garmin_db.py:117-138` | ✅ Åtgärdad: ssl-stöd och värdnamnsvalidering i get_mariadb_connection & pool |
| 10 | `PF-7` | `garmin_db.py`, `server.py` | ✅ Åtgärdad: Delad connection pool (singleton) + engångsinitiering av SQLite DDL |
| 11 | `S-14` | `garmin_db.py`, `server.py` | ✅ Åtgärdad: Kräv MariaDB i webbläget (require_mariadb), startup-kontroll & 503-fel |

`S-14` ändrar hur appen beter sig vid databasfel och bör tas efter `PF-7`, eftersom båda rör
`GarminDatabase.__init__`. `TLS-3`:s serverdel (certifikat, `require_secure_transport`) är
operatörsarbete, se nedan.

### Omgång 5 – Sessionshantering (✅ Klart)
| Ordning | ID | Fil | Omfattning |
|---|---|---|---|
| 12 | `S-13` | `server.py`, `init_mariadb.sql` | ✅ Åtgärdad (Väg A): DEK ur DB, endast i RAM med TTL och minnes-nollställning, expires_at & städjobb, 1 worker i service, säkerhetsbeskrivning i README |

Största enskilda ändringen i tavlan. Ta den separat, inte ihop med något annat.

### Omgång 6 – Integrationer och robusthet
`B-5` (Garmin-MFA) · `B-6` (Withings felmeddelande) · `B-7` (OAuth-tokens) · `S-16` (keyring vid kontoradering)

Fristående från varandra; kan tas i valfri ordning eller delas upp.

### Omgång 7 – Kodkvalitet
`Q-1` … `Q-10` samt `TLS-4`, `TLS-5`, `TLS-6`.

Börja med **`Q-10`** (agentregeln pekar på filer i den gitignorerade `temp/`) och **`TLS-6`**
(`requirements.txt` saknar webbappens beroenden) – båda hindrar nästa agent från att komma igång
på en ren klon. `Q-9` punkt 7 (två testmoduler som importerar från `temp/`) hör ihop med dem.

---

### 🔧 Operatörsarbete – kan inte göras av en agent

Dessa kräver åtkomst till servern och databasen. De blockerar inte kodarbetet ovan.

- [ ] **Rotera databaslösenordet.** Kvarstår från `S-17`; värdet ligger i git-historiken sedan `7db86ef`. Se checklistan i `TLS-3`.
- [x] **Skapa `/etc/healthchat/db.env`** med rättigheterna `0600` och ägare `healthchat`. Klart.
- [ ] **`TLS-1`: reverse proxy med TLS** framför uvicorn, plus `--host 127.0.0.1` i unit-filen.
- [ ] **`TLS-3`: TLS mot MariaDB** – CA-certifikat på plats, `MARIADB_REQUIRE_TLS=1`, `require_secure_transport=ON` på servern.

---

### Miljö – så här får du testsviten att köra

Repot saknar webbappens beroenden i `requirements.txt` (det är `TLS-6`). Tills den är fixad:

```bash
pip install pytest pymysql dbutils cryptography argon2-cffi keyring \
            fastapi "uvicorn[standard]" httpx email-validator requests garth garminconnect
pytest --ignore=tests/test_charts_view_tabs.py -q
```

Förväntat utfall i dagsläget: **118 passed, 6 skipped, 1 failed**. Det enda felet
(`test_withings_handler.py::test_sync_profile_weight_from_db`) är **känt sedan tidigare** och beror på
att `HealthChatDesktop.py` ligger i den gitignorerade `temp/` – inte på något du gjort. `pytest` utan
`--ignore` avbryter vid insamling eftersom `test_charts_view_tabs.py` kräver `tkinter`. Båda hanteras
av `Q-9` punkt 7.

---

## 🔴 P0 – Buggar & säkerhet

### [x] B-1: AI-chatten visar aldrig något svar – fel nyckelnamn i SSE-strömmen
- **Fil:** [server.py:614-629](server.py) (`event_generator`), [static/app.js:1125-1145](static/app.js) (`handleSendChatMessage`)
- **Problem:** Servern streamar `data: {"chunk": "..."}` ([server.py:624](server.py)) men klienten läser `parsed.content` ([static/app.js:1139-1140](static/app.js)). Bubblan nollställs med `botBubble.innerText = ''` och fylls därefter aldrig – **hela chattfunktionen är död i webbgränssnittet**. Ytterligare tre fel i samma loop:
  1. `parsed.error` hanteras inte alls; serverns `{"error": ...}` ([server.py:629](server.py)) sväljs tyst av `catch (e) {}`.
  2. Klienten letar efter sentinelvärdet `[DONE]` som servern aldrig skickar – servern skickar `{"done": true}` ([server.py:625](server.py)).
  3. `decoder.decode(value)` anropas utan `{ stream: true }` och utan buffert över chunk-gränser. Ett SSE-event som delas mitt itu mellan två `reader.read()` tappas, och multibyte-tecken (å/ä/ö) blir sönderhackade.
- **Åtgärd:**
  1. Läs `parsed.chunk` i klienten. Enas om **ett** kontrakt och dokumentera det i en kommentar på båda sidor.
  2. Hantera `parsed.error` → visa felet i bubblan i stället för att svälja det. Hantera `parsed.done` → avsluta läsningen.
  3. Skapa dekodern som `new TextDecoder('utf-8')` och anropa `decoder.decode(value, { stream: true })`. Håll en `buffer`-sträng, splitta på `\n\n`, och behåll sista ofullständiga fragmentet till nästa iteration.
  4. Överväg att byta till `EventSource`-semantik eller en liten hjälpfunktion `async function* readSSE(res)` så att ramhanteringen finns på ett ställe.
- **Acceptanskriterier:**
  1. Ett chattmeddelande i webbläsaren ger synligt, växande svar i bubblan.
  2. Ett framtvingat serverfel (t.ex. ogiltig API-nyckel) visas som feltext för användaren, inte som tom bubbla.
  3. Svar som innehåller å/ä/ö renderas korrekt även när de delas över chunk-gränser.
  4. Enhetstest som matar `event_generator`-utdata genom klientens parsningslogik (eller minst ett test som låser serverns nyckelnamn).

---

### [x] S-13: DEK:en lagras i klartext i databasen – envelope-krypteringen blir verkningslös (Väg A genomförd)
- **Fil:** [server.py:156-180](server.py) (`save_session_to_db`), [server.py:121-150](server.py) (`init_sessions_table`), [init_mariadb.sql:22-29](init_mariadb.sql)
- **Problem:** `save_session_to_db` skriver sessionens **råa DEK** till kolumnen `user_sessions.dek` ([server.py:167](server.py)). Nyckeln som dekrypterar användarens samtliga hälsotabeller ligger därmed i klartext i **samma databas** som chiffertexten. Hela poängen med envelope-designen (lösenord → Argon2id → KEK → wrapped DEK) försvinner: den som får läsrättigheter på databasen – backup, dump, SQL-injektion, en DBA – kan dekryptera allt utan att någonsin se ett lösenord. Argon2, rate-limiting och återställningsnyckeln kringgås fullständigt.
  Dessutom: tabellen har en `created_at`-kolumn men **ingen kod läser den**. `load_session_from_db` ([server.py:182-228](server.py)) kontrollerar ingen ålder, det finns inget städjobb, och rader tas bara bort vid explicit utloggning ([server.py:232](server.py)). Sessioner gäller i praktiken för evigt på serversidan, medan cookien sätts med `max_age=86400 * 30`.
- **Åtgärd:**
  1. **Lagra aldrig DEK:en i beständig lagring.** Välj en av två vägar och dokumentera valet i README:
     - **A (rekommenderad):** håll DEK:en enbart i processminnet (`_active_sessions`) och kör Uvicorn med **en** worker, alternativt med sticky sessions. Sessionstabellen behövs då inte.
       ⚠️ Observera att [healthchat_web.service](healthchat_web.service) i dag kör `--workers 4`. Väljer du A **måste** unit-filen ändras i samma ändring, annars loggas användare ut slumpmässigt när requests landar på olika workers. Det är en kapacitetsminskning – stäm av med ägaren först.
     - **B:** om DEK:en måste delas mellan workers – kryptera den med en server-side nyckel som **inte** ligger i databasen (miljövariabel/KMS/keyring) innan den skrivs, och lagra i Redis eller motsvarande med TTL i stället för i MariaDB.
  2. Lägg till `expires_at DATETIME NOT NULL` och avvisa utgångna sessioner i `load_session_from_db`. Synka livslängden med cookiens `max_age`.
  3. Lägg till ett städanrop (`DELETE FROM user_sessions WHERE expires_at < NOW()`) vid inloggning eller som periodiskt jobb.
  4. Uppdatera [init_mariadb.sql](init_mariadb.sql) och `init_sessions_table` i takt med schemaändringen.
- **Acceptanskriterier:**
  1. `SELECT dek FROM user_sessions` ger inte en nyckel som kan dekryptera `daily_summary` utan ytterligare hemlighet.
  2. En session som är äldre än livslängden avvisas med 401 och raderas.
  3. Test som verifierar att utgången session inte kan återanvändas.
  4. README:s säkerhetsavsnitt beskriver sanningsenligt var DEK:en befinner sig under en aktiv session.

---

### [x] S-14: All hälsodata delas mellan användare när MariaDB inte är tillgänglig (webbkod: require_mariadb tvingat, startkontroll och 503-fel aktivt)
- **Fil:** [garmin_db.py:167-185](garmin_db.py) (`__init__`), samtliga getters [garmin_db.py:784-1036](garmin_db.py), [secret_store.py:18-37](secret_store.py)
- **Problem:** Varje läs- och skrivmetod i `GarminDatabase` har mönstret:
  ```python
  if self.is_mariadb and self.user_id and self.dek:
      ...krypterat, per user_id...
  else:
      ...SQLite utan user_id...
  ```
  SQLite-tabellerna saknar helt `user_id`-kolumn. Misslyckas MariaDB-anslutningen sätts `is_mariadb = False` och **applikationen fortsätter utan att klaga** ([garmin_db.py:174-176](garmin_db.py)) – men då läser och skriver *alla* inloggade användare mot samma globala `~/.healthchat/healthdata.db`. Användare A ser användare B:s sömn, vikt och träningspass. Samma sak gäller om `MARIADB_PASSWORD` saknas i miljön.
  Samma klass av problem finns i [secret_store.py](secret_store.py): API-nycklar, Garmin-inloggning och OAuth-tokens ligger i **en global** OS-keyring utan `user_id`-dimension, och `chat_stream` hämtar dem globalt ([server.py:604](server.py)). I en flerandvändarapplikation delas alltså även integrationer och AI-nycklar.
- **Åtgärd:**
  1. Inför ett explicit läge. När `server.py` kör ska MariaDB vara **obligatoriskt**: låt `GarminDatabase` ta en flagga `require_mariadb: bool` (eller läs `HEALTHCHAT_MULTIUSER=1`) och **kasta** i stället för att falla tillbaka. SQLite-fallbacken är rimlig för desktop-läget, aldrig för webben.
  2. Lägg till en startkontroll i `server.py` som vägrar starta utan fungerande MariaDB-anslutning, med tydligt felmeddelande.
  3. Om SQLite-fallbacken ska behållas för webben: lägg till `user_id` i samtliga SQLite-tabeller ([garmin_db.py:244-370](garmin_db.py)) och filtrera på den i alla getters – annars ta bort fallbacken helt ur webbvägen.
  4. Gör hemligheter per användare: nyckla keyring-posterna på `user_id` (`f"{user_id}:openai_api_key"`) eller flytta dem till en krypterad kolumn på `users`, krypterad med användarens DEK.
- **Acceptanskriterier:**
  1. Med MariaDB nedstängd startar inte webbservern / returnerar 503 – den serverar inte delad SQLite-data.
  2. Test som verifierar att användare A:s `get_activities_history()` inte returnerar användare B:s rader oavsett backend.
  3. Två användare med olika AI-nycklar får sina egna nycklar använda i `/api/ai/chat`.

---

## 🟠 P1 – Robusthet & korrekthet

### [x] B-2: Deduplicering slår ihop olika träningspass samma dag
- **Fil:** [garmin_db.py:855-927](garmin_db.py) (`deduplicate_activities`), villkoret på [garmin_db.py:904](garmin_db.py)
- **Status:** ✅ Reproducerat.
- **Problem:** Villkoret
  ```python
  if is_dist_match and (is_hr_match or is_dur_match or dist_diff <= 0.1):
  ```
  låter `dist_diff <= 0.1` **kortsluta både puls- och tidskontrollen**. För distanslösa pass (styrka, yoga, simning) är `act_dist == ex_dist == 0`, vilket ger `is_dist_match = True` (else-grenen på [garmin_db.py:900](garmin_db.py)) **och** `dist_diff == 0`. Resultatet blir att varje par av distanslösa pass samma dag klassas som dubbletter. Reproduktion:
  ```
  Styrketräning 45 min / 110 bpm + Yoga 20 min / 75 bpm + Simning 60 min / 140 bpm
      (samma datum, 0 km)                           ->  1 pass kvar ("Styrketräning")
  Morgonlöpning 5,00 km / 30 min + Kvällslöpning 5,05 km / 28 min
      (samma datum)                                 ->  1 pass kvar ("Morgonlöpning")
  ```
  Konsekvenser: aktivitetstabellen tappar pass, `workout_cal`-summan i dashboarden underskattar dagens träningskalorier ([server.py:519-543](server.py)), och AI:n får ett ofullständigt underlag.
- **Åtgärd:**
  1. Ta bort `or dist_diff <= 0.1` ur villkoret – den klausulen gör `is_hr_match`/`is_dur_match` meningslösa. Kräv `is_dist_match and (is_hr_match or is_dur_match)`.
  2. Behandla "båda saknar distans" som **otillräckligt** för matchning: när `act_dist == 0 and ex_dist == 0` ska duration och/eller puls avgöra ensamma, med rimliga toleranser (t.ex. duration inom 2 min *och* starttid inom 10 min).
  3. Utnyttja starttid när den finns (`start_time`) – två pass som startar timmar isär är aldrig samma pass, oavsett distans.
  4. Använd `activity_id` som primär dubblettnyckel när båda posterna kommer från samma källa.
- **Acceptanskriterier:**
  1. Test: tre distanslösa pass samma dag med olika duration/puls ger tre pass tillbaka.
  2. Test: två separata 5 km-löprundor samma dag med olika starttid ger två pass tillbaka.
  3. Test: samma pass importerat från både Garmin och Strava (samma distans, duration och puls) slås fortfarande ihop, och `source` blir `"Garmin / Strava"`.

---

### [x] B-3: BMR blir tyst 0 när vikten saknas – dagsförbrukningen visas som ~400 kcal
- **Fil:** [server.py:539](server.py), [calorie_calc.py:24-33](calorie_calc.py) (`mifflin_st_jeor_bmr`), [calorie_calc.py:103-111](calorie_calc.py)
- **Status:** ✅ Reproducerat.
- **Problem:** Två fel som förstärker varandra:
  1. `weight = profile.get("weight_kg") or (body_comp_latest.get("weight_kg") if body_comp_latest else 70.0)` – finns det en `body_composition`-rad **utan** `weight_kg` returnerar uttrycket `None`, och 70-defaulten nås aldrig eftersom den sitter i fel gren av villkoret.
  2. `mifflin_st_jeor_bmr` returnerar `0.0` vid saknad vikt ([calorie_calc.py:30-31](calorie_calc.py)), men `estimate_daily_burn` rapporterar ändå `"bmr_source": "mifflin"` ([calorie_calc.py:106-108](calorie_calc.py)) – felet maskeras alltså som ett giltigt beräknat värde.

  Reproduktion (`weight_kg=None, height_cm=180, age_years=40, steps=10000`):
  ```
  {'bmr_full': 0, 'bmr_source': 'mifflin', 'resting_burn': 0, 'total_burn': 400}
  ```
  Användaren ser 400 kcal i stället för ~1 800.
- **Åtgärd:**
  1. Skriv om viktupplösningen så att defaulten alltid gäller:
     ```python
     weight = (profile.get("weight_kg")
               or (body_comp_latest or {}).get("weight_kg")
               or 70.0)
     ```
  2. Låt `estimate_daily_burn` falla tillbaka på `simple_bmr` när Mifflin returnerar 0, och sätt `bmr_source` till något som speglar verkligheten (`"none"` eller `"simple"`) – aldrig `"mifflin"` för ett nollvärde.
  3. Överväg att returnera ett `warnings`-fält så att UI:t kan visa "ange vikt för korrekt beräkning" i stället för ett tyst felvärde.
- **Acceptanskriterier:**
  1. Test: `estimate_daily_burn(weight_kg=None, height_cm=180, age_years=40)` ger `bmr_full > 0` **eller** `bmr_source != "mifflin"`.
  2. Test: `/api/dashboard/summary` med en viktlös `body_composition`-rad ger ett rimligt `total_burn` (> 1 000 kcal mitt på dagen).

---

### [x] B-4: Omkastade argument i `decrypt_payload` – profilen tappas mellan Uvicorn-workers
- **Fil:** [server.py:218](server.py) (i `load_session_from_db`)
- **Problem:** `crypto.decrypt_payload(dek_bytes, p_n, enc_p)` skickar nonce och chiffertext i fel ordning. Signaturen är `decrypt_payload(dek, ciphertext, nonce)` ([crypto.py:79](crypto.py)), och alla andra anropsställen har rätt ordning ([auth.py:251](auth.py), [auth.py:336](auth.py), [auth.py:541](auth.py)). Fallbacken – som ska hämta profilen från `users`-tabellen när sessionsraden saknar den – kastar därför **alltid** `InvalidTag`. Felet fångas och loggas på `debug`-nivå ([server.py:219-220](server.py)), så det syns aldrig. Konsekvens: en session som återläses i en annan worker än den som skapade den får tom profil → dashboarden ramlar tillbaka på defaultvärden (se `UI-1`) och `hr_zones`/`calorie_burn` beräknas på fel underlag.
- **Åtgärd:**
  1. Rätta anropet till `crypto.decrypt_payload(dek_bytes, enc_p, p_n)`.
  2. Höj loggnivån från `debug` till `warning` – en misslyckad dekryptering av egen data är aldrig normalt.
  3. Överväg att göra `decrypt_payload`/`encrypt_payload` mindre lätta att kalla fel, t.ex. genom att returnera och ta emot en liten `EncryptedBlob(ciphertext, nonce)`-dataclass.
- **Acceptanskriterier:**
  1. Test som sparar en session utan `encrypted_profile` i sessionstabellen och verifierar att `load_session_from_db` returnerar den dekrypterade profilen från `users`.
  2. `grep -n "decrypt_payload(" *.py` visar samma argumentordning överallt.

---

### [x] UI-1: Dashboarden fyller i påhittade hälsovärden när data saknas
- **Fil:** [static/app.js:365](static/app.js), [static/app.js:381-385](static/app.js), [static/app.js:394-402](static/app.js), [static/app.js:410-414](static/app.js), [static/app.js:516-522](static/app.js) (`generateMockSeries`), [static/app.js:572](static/app.js), [static/app.js:634-636](static/app.js), [static/app.js:669](static/app.js), [static/app.js:695](static/app.js), [static/app.js:716](static/app.js), [static/app.js:750](static/app.js), [static/app.js:774](static/app.js)
- **Problem:** Saknas data visas hårdkodade värden som om de vore användarens egna mätvärden:
  - vikt `98.3` kg, fett `21.4` %, muskelmassa `72.1` kg, återhämtning `72` %, kaloriförbränning `1195` kcal, vilo-BMR `1123` kcal
  - `"BMI: … (📉 -0.3 under 30 d)"` – trenddeltat är en konstant sträng, aldrig beräknat
  - `"Källa: Withings (2026-09-11)"` – källa och datum hårdkodade som fallback
  - **samtliga åtta grafer** fylls med `generateMockSeries()` – sinuskurvor kring 98,5 kg, 2 150 kcal, 51 bpm vilopuls, 7,5 h sömn, 83 i sömnpoäng, 86 i Body Battery.

  En ny användare, eller en användare som drabbats av `B-4`/`S-14`, ser fabricerade mätvärden som inte går att skilja från riktiga. I en hälsoapp är det allvarligare än ett vanligt UI-fel – någon kan fatta träningsbeslut på påhittade siffror.
  Därtill: BMI-kortet ([static/app.js:396-398](static/app.js)) räknar alltid om BMI från `wKg`/`heightCm` och ignorerar det `bmi`-värde som backend faktiskt sparar ([server.py:669-677](server.py)), vilket kan ge två olika BMI i samma gränssnitt.
- **Åtgärd:**
  1. Ta bort samtliga numeriska fallbackvärden. Saknas data → visa `--` respektive ett tomt diagram med texten "Ingen data för perioden".
  2. Ta bort `generateMockSeries` helt, alternativt lås den bakom en explicit `?demo=1`-flagga som tydligt märker gränssnittet som demoläge.
  3. Låt BMI-kortet använda `data.profile.bmi` när det finns och bara räkna om som sista utväg.
  4. Ersätt `"Källa: Withings"` och det hårdkodade datumet med faktiska värden eller `--`.
- **Acceptanskriterier:**
  1. Ett nyregistrerat konto utan synkad data visar `--`/tomma grafer – inga siffror alls.
  2. `grep -n "generateMockSeries\|98.3\|21.4\|72.1\|1195" static/app.js` ger inga träffar i produktionsvägen.
  3. BMI som visas i kortet är identiskt med det som `/api/dashboard/summary` returnerar.

---

### [x] S-15: CORS tillåter alla origins tillsammans med credentials
- **Fil:** [server.py:44-51](server.py), cookie-sättningen på [server.py:315-321](server.py) och [server.py:353-359](server.py)
- **Problem:** `allow_origins=["*"]` i kombination med `allow_credentials=True`. Starlettes `CORSMiddleware` **speglar tillbaka anropande origin** när begäran bär cookie, så skyddet blir i praktiken obefintligt mot en webbplats som lyckas få cookien medskickad. `SameSite=Lax` mildrar det mot vanliga cross-site-XHR, men kombinationen är fel och gör skyddet beroende av en enda inställning.
  Cookien saknar dessutom `secure=True` – sessions-ID:t skickas i klartext över HTTP. `healthchat_web.service` kör bakom reverse proxy, så flaggan bör vara på i produktion.
- **Åtgärd:**
  1. Ersätt `["*"]` med en explicit lista läst ur miljövariabel, t.ex. `ALLOWED_ORIGINS=https://healthchat.example.se`. Tillåt `["*"]` **bara** när `allow_credentials=False`.
  2. Sätt `secure=True` på sessionscookien, styrt av en miljövariabel så att lokal HTTP-utveckling fortsatt fungerar (`COOKIE_SECURE=0`).
  3. Begränsa `allow_methods` och `allow_headers` till det som faktiskt används.
  4. Överväg CSRF-token för de tillståndsändrande endpointsen (`/api/user/delete_account`, `/api/profile/change_password`) – `SameSite=Lax` skyddar inte mot alla vektorer.
- **Acceptanskriterier:**
  1. Ett `Origin`-huvud som inte finns i listan får inget `Access-Control-Allow-Origin` i svaret.
  2. Cookien sätts med `Secure` när `COOKIE_SECURE=1`.
  3. Befintliga tester i [tests/test_security_and_perf.py](tests/test_security_and_perf.py) är gröna.

---

### [x] UI-2: Stored XSS i aktivitetstabellerna
- **Fil:** [static/app.js:454-472](static/app.js) (`renderActivitiesTable`), [static/app.js:1052-1070](static/app.js) (träningsfliken)
- **Problem:** `act.activity_name`, `act.activity_type` och `act.source` interpoleras rått i `innerHTML`. Passnamn är användarsatta i Garmin och Strava, så en användare kan namnge ett pass `<img src=x onerror=...>` och få kod exekverad i sitt eget gränssnitt – och i alla gränssnitt som visar delad data (se `S-14`, där SQLite-fallbacken faktiskt delar rader mellan konton). Samma mönster finns i `renderHrZonesTable` ([static/app.js:949](static/app.js)) och MAF-boxen ([static/app.js:968](static/app.js)), där innehållet i dag är serverstyrt men mönstret är lika skört.
- **Åtgärd:**
  1. Bygg raderna med `document.createElement` + `textContent` i stället för `innerHTML`, alternativt inför en `escapeHtml()`-hjälpare och kör **alla** datafält genom den.
  2. Gå igenom samtliga `innerHTML`-anrop i [static/app.js](static/app.js) och avgör för varje om innehållet är statisk markup (OK) eller data (måste escapas).
  3. Lägg till en `Content-Security-Policy`-header i [server.py](server.py) som förbjuder inline-event-handlers.
- **Acceptanskriterier:**
  1. Ett pass med namnet `<img src=x onerror=alert(1)>` renderas som text, inte som HTML.
  2. Inga `innerHTML`-anrop kvar som interpolerar data från API:t utan escaping.

---

### [ ] B-5: Garmin-MFA kapplöpning – inloggning misslyckas när prompten dröjer
- **Fil:** [garmin_handler.py:391-455](garmin_handler.py), specifikt [garmin_handler.py:433](garmin_handler.py)
- **Problem:** `login_done.wait(timeout=3)` ger garth exakt 3 sekunder på sig att antingen bli klar eller nå fram till MFA-prompten. Vid långsam uppkoppling hinner `_prompt_mfa` inte köra inom fönstret, så `mfa_needed[0]` är fortfarande `False` och koden faller igenom till `login_thread.join(timeout=30)` ([garmin_handler.py:447](garmin_handler.py)). `self.client_state` sätts aldrig, så inget UI kan leverera koden – tråden blir hängande i `mfa_event.wait(timeout=300)`. Efter 30 sekunder är `login_error[0]` `None` och `login_success[0]` `False`, vilket ger `RuntimeError("Login did not complete successfully")` ([garmin_handler.py:453](garmin_handler.py)) i stället för MFA-dialogen. Användaren ser ett obegripligt fel och en tråd ligger kvar och väntar i fem minuter.
- **Åtgärd:**
  1. Låt `_prompt_mfa` sätta ett eget `mfa_requested = threading.Event()` **innan** den börjar vänta, och vänta på `mfa_requested` eller `login_done` med en gemensam timeout – inte på en fast 3-sekundersgräns.
  2. Höj väntetiden och gör den konfigurerbar (t.ex. 20 s), och kontrollera `mfa_needed[0]` igen efter `join(timeout=...)` innan felet kastas.
  3. Om tråden fortfarande lever efter join: sätt `mfa_event` så att `_prompt_mfa` returnerar tom sträng och tråden avslutas i stället för att blockera i 300 s.
  4. Skilj på felen: "MFA krävs men kunde inte startas" ska inte se ut som "fel lösenord".
- **Acceptanskriterier:**
  1. Test som simulerar en garth-login där MFA-prompten dröjer 10 s och verifierar att `{'mfa_required': True}` returneras.
  2. Ingen kvarlämnad tråd efter misslyckad inloggning.

---

## 🟡 P2 – Kodkvalitet & underhåll

### [ ] B-6: Operator-precedens sväljer Withings riktiga felmeddelande
- **Fil:** [withings_handler.py:115](withings_handler.py)
- **Status:** ✅ Reproducerat.
- **Problem:**
  ```python
  err_msg = err_detail or f"Withings API-status {status_code}" if status_code else "Ogiltig kod"
  ```
  binder som `(err_detail or f"...") if status_code else "Ogiltig kod"`. Eftersom Withings **framgångsstatus är `0`** (falsy) och `status_code` blir `None` vid nätverksfel, hamnar man nästan alltid i else-grenen:
  ```
  err_detail='invalid_grant', status_code=None  ->  "Ogiltig kod"   ← fel
  err_detail='invalid_grant', status_code=503   ->  "invalid_grant" ← rätt
  err_detail=None,            status_code=0     ->  "Ogiltig kod"
  ```
  Det faktiska API-felet försvinner, och användaren får alltid samma intetsägande text. Samma klass av bugg som redan åtgärdats i `P2-5`.
- **Åtgärd:** Parentesera explicit:
  ```python
  err_msg = err_detail or (f"Withings API-status {status_code}" if status_code is not None else "Ogiltig kod")
  ```
  Notera `is not None` – status `0` ska inte behandlas som frånvarande.
- **Acceptanskriterier:** Test som verifierar att `err_detail` bevaras när `status_code` är `None` respektive `0`.

---

### [ ] B-7: OAuth-tokens roteras bort och lagras i klartext på disk
- **Fil:** [withings_handler.py:140-151](withings_handler.py), [strava_handler.py:70-83](strava_handler.py), [fitbit_handler.py:73-88](fitbit_handler.py), [secret_store.py:28-36](secret_store.py)
- **Problem:**
  1. **Withings tappar sin refresh-token.** Uppdaterade tokens skrivs bara till `~/.healthchat/config.json`, och bara **om filen redan finns** ([withings_handler.py:143](withings_handler.py)). `secret_store.py` har redan nycklarna `withings_refresh_token` och `withings_access_token` definierade – de används aldrig. Withings **roterar refresh-token vid varje användning**, så när config.json saknas går integrationen sönder vid nästa körning utan att någon får veta varför (felet loggas på `debug`).
  2. **Klartextlagring.** `strava_tokens.json` och `fitbit_tokens.json` skrivs med standardrättigheter och innehåller både `client_secret` och `refresh_token` ([strava_handler.py:72-76](strava_handler.py)). Det motverkar hela poängen med `secret_store` och står i strid med `S-3`/`S-4` som redan är åtgärdade för AI-nycklarna.
  3. **Utgången token används ändå.** `_get_headers` anropar `refresh_access_token()` men ignorerar returvärdet ([strava_handler.py:179-186](strava_handler.py), [fitbit_handler.py:188-195](fitbit_handler.py)). Misslyckas förnyelsen skickas den utgångna token ändå, vilket ger en 401 som användaren aldrig får en begriplig förklaring till.
- **Åtgärd:**
  1. Flytta all tokenlagring till `secret_store` (`set_secret`/`get_secret`) för alla tre integrationerna. Behåll JSON-filerna enbart som engångsmigrering: läs in, skriv till keyring, radera filen.
  2. Där filer måste användas som fallback: skapa dem med `0o600` (`os.open(..., 0o600)`).
  3. Låt `_get_headers` kontrollera returvärdet från `refresh_access_token()` och kasta ett tydligt fel (`"Strava-anslutningen har gått ut – koppla om i inställningarna"`) i stället för att skicka en död token.
- **Acceptanskriterier:**
  1. En Withings-tokenförnyelse persisteras och överlever en omstart utan `config.json`.
  2. `ls -l ~/.healthchat/*_tokens.json` visar `-rw-------` om filerna alls finns kvar.
  3. Test: misslyckad refresh ger ett tydligt undantag, inte ett 401-svar.

---

### [x] PF-7: Ny connection pool skapas per HTTP-request (delad singleton-pool och engångsinitiering av SQLite DDL aktiv)
- **Fil:** [server.py:113-116](server.py) (`get_db`), [server.py:289-293](server.py) (`bind_user_db`), [garmin_db.py:167-185](garmin_db.py), [garmin_db.py:187-224](garmin_db.py) (`_init_mariadb_pool`)
- **Problem:** `get_db()` och `bind_user_db()` instansierar `GarminDatabase()` vid **varje** anrop. Konstruktorn bygger en helt ny `PooledDB` med `mincached=2` ([garmin_db.py:207-209](garmin_db.py)) – alltså två nya TCP-anslutningar och handskakningar mot MariaDB per request – och kör dessutom `init_sqlite_db()` ([garmin_db.py:185](garmin_db.py)) som öppnar SQLite-filen och kör `CREATE TABLE IF NOT EXISTS` för samtliga tabeller, varje gång.
  `/api/dashboard/summary` anropar `bind_user_db` en gång och `get_db_conn` flera gånger; `get_current_session` kan skapa ytterligare en instans i samma request. Under last äter det upp MariaDB:s `max_connections`, och eftersom `blocking=True` ([garmin_db.py:210](garmin_db.py)) börjar requests hänga i stället för att fela snabbt.
- **Åtgärd:**
  1. Gör poolen modulglobal i `garmin_db.py` – skapa den **en gång** (lazy, med lås) och låt alla `GarminDatabase`-instanser dela den.
  2. Flytta `init_sqlite_db()` till en engångsinitiering (modulnivå eller FastAPI `startup`-event), inte till konstruktorn.
  3. Gör `GarminDatabase` billig att instansiera: den ska bara hålla `user_id` + `dek` och referera den delade poolen.
  4. Skapa poolen i ett `@app.on_event("startup")`-anrop så att felkonfiguration upptäcks vid start (samordna med `S-14`).
- **Acceptanskriterier:**
  1. 100 sekventiella anrop mot `/api/dashboard/summary` ger inte fler än poolens maxantal anslutningar mot MariaDB (`SHOW STATUS LIKE 'Threads_connected'`).
  2. `init_sqlite_db` körs högst en gång per process.
  3. Befintliga prestandatester i [tests/test_security_and_perf.py](tests/test_security_and_perf.py) är gröna.

---

### [ ] S-16: Keyring-posten överlever kontoradering
- **Fil:** [auth.py:466-475](auth.py) (`delete_user_account`), [auth.py:506-517](auth.py) (`clear_remembered_session`)
- **Problem:** `delete_user_account` anropar `clear_remembered_session()` **utan argument** ([auth.py:474](auth.py)). Med `email=None` gör funktionen ingenting alls utom loggar `"Cleared keyring session."` ([auth.py:510-515](auth.py)) – loggraden ljuger. Användarens DEK ligger kvar i OS-keyringen efter att kontot raderats. Databasraden är visserligen borta (så `get_remembered_user_session` returnerar `None`), men en hemlighet som användaren uttryckligen bett att få raderad finns kvar på disken.
- **Åtgärd:**
  1. Hämta e-postadressen innan `DELETE FROM users` och skicka in den: `SELECT email FROM users WHERE id = %s` → `clear_remembered_session(email)`.
  2. Låt `clear_remembered_session()` utan e-post logga en varning i stället för att påstå att något rensats – eller kräv argumentet.
  3. Radera även sessionsrader (`user_sessions`) explicit; i dag förlitar sig koden på `ON DELETE CASCADE`, vilket inte gäller SQLite-fallbacken.
- **Acceptanskriterier:**
  1. Test: efter `delete_user_account` returnerar `load_remembered_session(email)` `None`.
  2. Inga loggrader som påstår att något rensats när inget gjordes.

---

### [x] S-17: Hårdkodade databasuppgifter borta ur repot
- **Fil:** [garmin_db.py:41-114](garmin_db.py) (`_DB_ENV_TEMPLATE`, `_write_db_env_template`, `_warn_if_world_readable`, `load_db_env`), [healthchat_web.service](healthchat_web.service), [.env.example](.env.example), [tests/test_no_hardcoded_secrets.py](tests/test_no_hardcoded_secrets.py), [tests/test_db_config.py](tests/test_db_config.py)
- **Problem:** Databaslösenordet låg hårdkodat på två ställen: som `Environment=` i systemd-enheten och som värde i mallen `load_db_env()` skrev till `~/.healthchat/db.env` vid första körningen. Den senare innebar att **varje installation fick samma lösenord**. Tre följdproblem hittades i samma kod:
  - Mallfilen skapades med processens umask, alltså typiskt `0644` – läsbar för alla användare på systemet.
  - `load_db_env()` gjorde `os.environ[k] = v` trots att docstringen sa "if missing". En fil i användarens hemkatalog kunde därmed **skriva över** det driftmiljön satt via `EnvironmentFile`.
  - Tomma värden (`MARIADB_PASSWORD=`) sattes som tom sträng i miljön i stället för att hoppas över.
- **Åtgärdat:**
  1. `_DB_ENV_TEMPLATE` innehåller inga värden alls – varje rad är utkommenterad. Operatören fyller i själv, och appen felar med `"MARIADB_PASSWORD saknas"` tills dess.
  2. Mallen skapas med `os.open(..., O_EXCL, 0o600)` så att den aldrig ens kortvarigt är läsbar för andra.
  3. `_warn_if_world_readable()` loggar en varning med `chmod`-kommandot när en env-fil har för vida rättigheter.
  4. `os.environ.setdefault()` i stället för direkt tilldelning – miljön vinner alltid över filer.
  5. Tomma värden hoppas över.
  6. Systemd-enheten läser `EnvironmentFile=/etc/healthchat/db.env` med en kommentar om varför `Environment=` är olämpligt (unit-filen ligger i git, och `systemctl show` exponerar `Environment=` för alla användare på systemet).
  7. `.env.example` har tom platshållare för lösenordet, dokumenterar `chmod 600` och de tre platser filen kan ligga på.
- **Regressionsskydd:** [tests/test_no_hardcoded_secrets.py](tests/test_no_hardcoded_secrets.py) skannar alla källfiler efter hemlighetsliknande nycklar som tilldelas literaler, och kontrollerar särskilt systemd-enheten, `.env.example` och `_DB_ENV_TEMPLATE`. Testet är verifierat genom att lösenordsmönstren återinfördes tillfälligt – då fallerar 3 av 4 tester. Det rapporterar **plats och nyckelnamn, aldrig värdet**. Testfixturer under `tests/` skannas inte, eftersom de medvetet använder påhittade uppgifter.
- **Kvarstår:** lösenordet ligger kvar i git-historiken sedan `7db86ef` och **måste roteras** – se `TLS-3` punkt 2.

---

### [ ] Q-1: `/api/user/profile/fetch_external` hämtar inget externt
- **Fil:** [server.py:692-701](server.py), [profile_sync.py:14-20](profile_sync.py), [static/app.js:1232](static/app.js)
- **Problem:** `fetch_external_profile_metrics` anropas alltid som `fetch_external_profile_metrics(db=db)` – parametrarna `garmin_handler`, `fitbit_handler`, `strava_handler` och `withings_handler` skickas **aldrig** in från någon plats i repot (`grep` bekräftar att ingen av handlarna instansieras i webbvägen). Hela Garmin/Fitbit/Strava/Withings-logiken i [profile_sync.py:77-192](profile_sync.py) är död kod, och endpointen läser i praktiken bara den lokala databasen – trots att namnet, docstringen och knappen i UI:t lovar något annat. `sources`-listan i svaret innehåller bara `"Databas"`.
- **Åtgärd:** Välj en linje och genomför den fullt ut:
  - **A:** Koppla in handlarna på riktigt – instansiera dem per användare från `secret_store` (kräver `S-14` punkt 4) och skicka in dem.
  - **B:** Ta bort den döda koden ur `profile_sync.py`, döp om endpointen till `/api/user/profile/refresh` och uppdatera knapptexten i UI:t så att den beskriver vad som faktiskt händer.
- **Acceptanskriterier:** Endpointens namn, docstring, UI-text och faktiska beteende är samstämmiga; ingen död parametergren kvar.

---

### [ ] Q-2: Webbchatten har inget konversationsminne och saknar hälsokontext
- **Fil:** [server.py:590-631](server.py)
- **Problem:** `AIClient` skapas på nytt i varje request ([server.py:607](server.py)), så `conversation_history` är alltid tom – hela det glidande fönstret från `P1-1` är verkningslöst i webbläget och AI:n minns ingenting mellan frågor. Dessutom anropas `client.chat(prompt)` utan `garmin_context`-argumentet; kontexten klistras i stället in i `prompt` ([server.py:601](server.py)), vilket betyder att den **sparas i historiken** – precis det `P1-1` löste. Kontexten som byggs är dessutom mycket tunnare än desktopversionens: tre rader med antal aktiviteter och senaste sömn ([server.py:594-599](server.py)).
- **Åtgärd:**
  1. Persistera konversationshistoriken per session (i `_active_sessions` eller en tabell) och mata in den i `AIClient` mellan requests.
  2. Skicka hälsodata via `garmin_context`-parametern, inte via `user_message`.
  3. Bygg en rikare kontext – återanvänd formateringslogiken från desktopversionen (finns i `temp/`) i stället för de tre raderna.
- **Acceptanskriterier:** En följdfråga ("och förra veckan då?") besvaras med kontext från föregående fråga.

---

### [ ] Q-3: `self.model.lower()` kraschar för Azure utan explicit modell
- **Fil:** [ai_client.py:457](ai_client.py), [ai_client.py:91-95](ai_client.py)
- **Problem:** `PROVIDERS['azure']['default_model']` är `None` ([ai_client.py:38](ai_client.py)). Skapas klienten utan `model` blir `self.model = None`, och `'qwen' in self.model.lower()` kastar `AttributeError`. Felet fångas visserligen av det breda `except` i `chat()` ([ai_client.py:307](ai_client.py)) men presenteras då som ett AI-fel i stället för ett konfigurationsfel.
- **Åtgärd:** Validera i `__init__` att `self.model` är satt (kasta `ValueError` med tydlig text för Azure), och använd `(self.model or '').lower()` som skydd.
- **Acceptanskriterier:** `AIClient(provider='azure', azure_endpoint=...)` utan modell ger ett begripligt `ValueError` vid konstruktion.

---

### [ ] Q-4: `self.azure_deployment` sätts men används aldrig
- **Fil:** [ai_client.py:125-141](ai_client.py) (`_init_azure`), [ai_client.py:442](ai_client.py)
- **Problem:** `_init_azure` sparar `self.azure_deployment = azure_deployment` ([ai_client.py:133](ai_client.py)), men `_call_openai_compatible` skickar `model=self.model`. För Azure är deployment-namnet det som ska skickas. I dag råkar det fungera eftersom `azure_deployment` defaultar till `self.model`, men skickar anroparen ett avvikande deployment-namn ignoreras det tyst.
- **Åtgärd:** Använd `getattr(self, 'azure_deployment', None) or self.model` i `_call_openai_compatible`, eller ta bort attributet helt.
- **Acceptanskriterier:** Test som verifierar att ett explicit `azure_deployment` hamnar i `model`-parametern.

---

### [ ] Q-5: `re.sub(r' +', ' ', content)` plattar ut AI-svarens formatering
- **Fil:** [ai_client.py:460-461](ai_client.py)
- **Problem:** Efterbehandlingen kollapsar **all** upprepad blanksteg i svaret – inte bara dubbla mellanslag i löptext, utan också indentering i kodblock, punktlistor och tabeller. Systemprompten ber uttryckligen om strukturerade svar med rubriker och listor ([ai_client.py:265-274](ai_client.py)), vilket den här raden delvis förstör.
- **Åtgärd:** Begränsa normaliseringen till rader som inte är kod/listor, eller ta bort den. Behåll `re.sub(r'=\s*\\?"\$[\d.]+\\?"', ...)` om den löser ett känt problem – men dokumentera vilket.
- **Acceptanskriterier:** Ett AI-svar med ett indenterat kodblock behåller sin indentering.

---

### [ ] Q-6: Misslyckat AI-anrop lämnar historiken i ogiltigt tillstånd
- **Fil:** [ai_client.py:274-310](ai_client.py)
- **Problem:** Användarmeddelandet läggs till i `conversation_history` ([ai_client.py:274-277](ai_client.py)) **innan** anropet görs. Kastar anropet returneras ett felmeddelande utan att något assistentsvar läggs till ([ai_client.py:307](ai_client.py) och framåt) – historiken innehåller då två `user`-meddelanden i rad. Anthropics API kräver alternerande roller och avvisar det i nästa tur, så ett övergående fel blir permanent tills `reset_conversation()` körs.
- **Åtgärd:** Ta bort det senaste användarmeddelandet ur historiken i felgrenen, alternativt lägg till felmeddelandet som assistentsvar.
- **Acceptanskriterier:** Test: ett misslyckat anrop följt av ett lyckat ger en historik med alternerande roller.

---

### [ ] Q-7: Ollama-felmeddelandet visar fel adress
- **Fil:** [ai_client.py:331-338](ai_client.py)
- **Problem:** Felmeddelandet vid anslutningsfel skriver `self.PROVIDERS['ollama']['base_url']` – den **hårdkodade** `http://localhost:11434/v1` – i stället för den URL klienten faktiskt konfigurerats med via `normalize_ollama_url` ([ai_client.py:213-222](ai_client.py)). En användare med Ollama på `192.168.1.50` får felsökningsråd för fel maskin.
- **Åtgärd:** Spara den normaliserade URL:en på instansen (`self.ollama_base_url`) i `_init_ollama` och använd den i felmeddelandet.
- **Acceptanskriterier:** Felmeddelandet innehåller den konfigurerade adressen.

---

### [ ] Q-8: Dubblett-e-post ger HTTP 500 i stället för 400
- **Fil:** [auth.py:160-178](auth.py) (`register_user`), [server.py:329-333](server.py)
- **Problem:** `users.email` har `UNIQUE`-constraint ([init_mariadb.sql:10](init_mariadb.sql)), men `register_user` kontrollerar inte om adressen redan finns. `IntegrityError` är inget `ValueError`, så den fångas av det breda `except Exception` ([server.py:332](server.py)) och blir ett 500-svar med rå databastext i `detail` – både ett dåligt användarmeddelande och ett litet informationsläckage.
- **Åtgärd:**
  1. Slå upp adressen först och kasta `ValueError("E-postadressen är redan registrerad.")`, alternativt fånga `pymysql.err.IntegrityError` och översätt.
  2. Sluta skicka `str(e)` till klienten i 500-grenen – logga det och returnera en generisk text.
- **Acceptanskriterier:** Registrering med befintlig e-post ger 400 med ett begripligt svenskt meddelande, utan databasdetaljer.

---

### [ ] Q-9: Diverse mindre fynd
- **Fil:** flera
- **Problem & åtgärd:**
  1. **Återställningsnyckeln är 200 bitar, inte 256.** [crypto.py:92-104](crypto.py) – funktionen heter `generate_recovery_key`, docstringen säger 256 bitar, men `b32[:40]` kapar till 40 Base32-tecken = 200 bitar. Fortfarande säkert, men dokumentationen stämmer inte. **Åtgärd:** rätta docstringen (eller använd 52 tecken).
  2. **Mojibake i loggsträngar.** [garmin_handler.py](garmin_handler.py) innehåller 6 strängar med `âœ…`/`ðŸ` – UTF-8 som avkodats som latin-1. **Åtgärd:** ersätt med korrekta tecken.
  3. **`get_db_conn` returnerar aldrig `None`.** [server.py:118-123](server.py) – ändå testar anroparna `if conn:` ([server.py:679](server.py), [server.py:713](server.py), [server.py:741](server.py)) och har else-grenar som är död kod. **Åtgärd:** ta bort de meningslösa kontrollerna, eller låt funktionen faktiskt kunna returnera `None` och hantera det.
  4. **Aliasing av DEK vid samtidig utloggning.** [server.py:386](server.py) – `session.clear()` nollar den `bytearray` som `bind_user_db` redan delat ut till en pågående request i en annan tråd. Osannolikt men reellt. **Åtgärd:** kopiera DEK:en in i `GarminDatabase` i stället för att dela referensen.
  5. **`delete_account` kräver inget lösenord.** [server.py:736-751](server.py) – till skillnad från `change_password` och `rotate_recovery_key`. **Åtgärd:** kräv `current_password` för en irreversibel operation.
  6. **Rate-limiting är process-lokal.** [auth.py:98-122](auth.py) – med flera Uvicorn-workers multipliceras gränsen med antalet workers. **Åtgärd:** samordna med `S-7`-lösningen (räknare i databasen).
  7. **Två testmoduler refererar till `temp/`.** [tests/test_withings_handler.py:108-112](tests/test_withings_handler.py) importerar `HealthChatDesktop` och [tests/test_charts_view_tabs.py:4-9](tests/test_charts_view_tabs.py) importerar `charts_view` + `tkinter` – båda modulerna flyttades till den gitignorerade `temp/` i `33ae88d`. Det första testet **fallerar** på en ren klon, det andra kan inte ens samlas in utan `tkinter`. Felet fanns före denna genomgång (verifierat mot `HEAD`). **Åtgärd:** flytta de desktopberoende testerna till samma plats som koden, eller markera dem med `pytest.importorskip` så att sviten är grön på en ren klon.
- **Acceptanskriterier:** Varje delpunkt åtgärdad eller uttryckligen avfärdad med motivering i denna fil.

---

### [ ] Q-10: `.agents/rules/compile.md` refererar till filer som inte längre finns
- **Fil:** [.agents/rules/compile.md](.agents/rules/compile.md)
- **Problem:** Regeln kräver `pyinstaller --noconfirm HealthChatDesktop_optimized.spec` och `sign_executable.ps1` efter varje kodändring. Båda filerna flyttades till `temp/` i commit `33ae88d` och `temp/` är gitignorerad – stegen går alltså inte att utföra i repot längre. En agent som följer regeln bokstavligt fastnar.
- **Åtgärd:** Uppdatera regeln till webbapplikationens verklighet: kör `pytest`, verifiera att `uvicorn server:app` startar, och beskriv desktop-bygget som valfritt/historiskt.
- **Se även:** [.agents/rules/github.md](.agents/rules/github.md) säger `git push origin main`. Arbetar agenten i stället på en feature-gren med pull request blir de två reglerna motstridiga. Bestäm vilket som gäller och skriv det i en av filerna, så att nästa agent inte behöver gissa.
- **Acceptanskriterier:** Regeln går att följa från en ren klon av repot, och det finns exakt ett svar på frågan vart arbetet ska pushas.

---

## 🔐 Transportkryptering – vad som krävs för att all trafik ska gå över HTTPS/TLS

> Genomgång 2026-09-11. Kartlägger varje nätverkssträcka appen har och vad som saknas för att ingen av dem ska gå i klartext.
> **Nuläget:** trafiken *ut* till tredjepartstjänster är redan krypterad. De två sträckor som bär användarens hälsodata och inloggningsuppgifter – webbläsare→app och app→MariaDB – går båda **helt okrypterade**.

| # | Sträcka | Status i dag | Uppgift |
|---|---|---|---|
| 1 | Webbläsare → app | ❌ Klartext HTTP på `0.0.0.0:8000` | `TLS-1`, `TLS-2` |
| 2 | App → MariaDB | ❌ Klartext över LAN till `192.168.101.106` | `TLS-3` |
| 3 | App → Garmin/Strava/Fitbit/Withings | ✅ HTTPS | – |
| 4 | App → OpenAI/Anthropic/Gemini/xAI | ✅ HTTPS | – |
| 5 | App → Ollama | ❌ Alltid `http://`, även mot fjärrvärd | `TLS-4` |
| 6 | Webbläsare → cdn.jsdelivr.net | ⚠️ HTTPS men opinnat och utan SRI | `TLS-5` |

---

### [ ] TLS-1: Ingen TLS-terminering – all webbtrafik går i klartext
- **Fil:** [healthchat_web.service:15](healthchat_web.service), [server.py:779-781](server.py)
- **Problem:** Tjänsten startar `uvicorn server:app --host 0.0.0.0 --port 8000` **utan TLS och utan reverse proxy**. Det finns ingen nginx-, Caddy- eller Traefik-konfiguration i repot. Allt som passerar går alltså i klartext över nätet:
  - **Lösenordet** vid `/api/auth/login` och `/api/auth/register` ([server.py:342](server.py), [server.py:300](server.py)).
  - **Återställningsnyckeln**, som returneras i klartext i registreringssvaret ([server.py:326](server.py)) och vid rotation ([server.py:730](server.py)). Den nyckeln kan ensam låsa upp kontots DEK.
  - **Sessionscookien** ([server.py:315-321](server.py)) – den som snappar upp den får full tillgång till kontot i 30 dagar.
  - **All hälsodata** – `/api/dashboard/summary` returnerar sömn, vikt, puls, HRV och träningspass i klartext-JSON.

  `--host 0.0.0.0` gör dessutom att porten är öppen mot hela nätverket, inte bara mot en lokal proxy. Klientkrypteringen i `crypto.py` skyddar data *i vila* i databasen – den skyddar ingenting på tråden, eftersom servern dekrypterar innan svaret skickas.
- **Åtgärd:**
  1. Sätt upp en reverse proxy framför uvicorn som terminerar TLS. **Caddy** är enklast (automatisk Let's Encrypt, automatisk förnyelse, HTTP→HTTPS-redirect out of the box); **nginx + certbot** om det redan finns nginx i miljön. Lägg konfigurationen i repot (`deploy/Caddyfile` eller `deploy/nginx.conf`) så att den versionshanteras.
  2. Ändra `ExecStart` till `--host 127.0.0.1` så att appen **bara** går att nå via proxyn. Detta är halva säkerhetsvinsten – utan det kan vem som helst kringgå TLS genom att prata direkt med port 8000.
  3. Lägg till `--proxy-headers --forwarded-allow-ips=127.0.0.1` i uvicorn-kommandot. Utan det ser appen varje request som `http` och loggar proxyns IP i stället för klientens, vilket bryter både rate-limiting per IP och eventuella absoluta URL:er.
  4. Tvinga HTTP→HTTPS-redirect i proxyn och sätt **HSTS**: `Strict-Transport-Security: max-age=31536000; includeSubDomains`. Vänta med `preload` tills uppsättningen är verifierad – den är svår att backa ur.
  5. Kräv TLS 1.2 som minimum, helst 1.3.
- **Acceptanskriterier:**
  1. `curl -I http://<domän>/` svarar `301` till `https://`.
  2. `curl -I https://<domän>/` svarar `200` med `Strict-Transport-Security`-huvudet satt.
  3. `curl http://<serverns-IP>:8000/` från en annan maskin får **connection refused**.
  4. `ssllabs.com`/`testssl.sh` ger minst betyg A.

---

### [x] TLS-2: Cookie utan `Secure`, och inga säkerhetsheaders
- **Fil:** [server.py:315-321](server.py), [server.py:353-359](server.py), [server.py:760-773](server.py)
- **Problem:** Sessionscookien sätts utan `secure=True`, så webbläsaren skickar den även över ren HTTP. Så länge `TLS-1` inte är på plats spelar det ingen roll, men efteråt är det den enda kvarvarande vägen för att läcka cookien (t.ex. via en felaktig `http://`-länk). Appen sätter heller inga av de headers som gör HTTPS meningsfullt i praktiken: `Strict-Transport-Security`, `Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`.
  Detta överlappar med `S-15` (CORS) – ta gärna båda i samma pass.
- **Åtgärd:**
  1. Sätt `secure=True` på cookien, styrt av en miljövariabel (`COOKIE_SECURE`, default `1`) så att lokal HTTP-utveckling fortsatt fungerar.
     ⚠️ **Beroende:** med default `1` slutar inloggningen fungera i en driftmiljö som fortfarande kör ren HTTP. Sätt `COOKIE_SECURE=0` i driften tills `TLS-1` är klar, och ta bort den raden när proxyn är på plats. Skriv in det i driftdokumentationen i samma ändring.
  2. Överväg att byta `samesite="lax"` till `"strict"` – appen har inga inkommande cross-site-flöden som behöver `lax`.
  3. Lägg till en middleware i [server.py](server.py) som sätter säkerhetsheaders på alla svar. Sätt `Strict-Transport-Security` **antingen** i proxyn eller i appen, inte båda.
  4. `Content-Security-Policy` behöver tillåta `cdn.jsdelivr.net` för Chart.js (se `TLS-5`) – eller så flyttas Chart.js lokalt och policyn kan bli `default-src 'self'`.
- **Acceptanskriterier:**
  1. `Set-Cookie`-huvudet innehåller `Secure; HttpOnly; SameSite=…`.
  2. Samtliga fem headers ovan finns i svaret från `/`.
  3. Sidan fungerar fortfarande – ingen resurs blockeras av CSP:n.

---

### [x] TLS-3: Databastrafiken går okrypterad över LAN (kodåtgärd klar: TLS-stöd i get_mariadb_connection & pool; drift/serverkonfig kvarstår)
- **Fil:** [healthchat_web.service:13](healthchat_web.service), [garmin_db.py:84-114](garmin_db.py) (`load_db_env`), [garmin_db.py:192-199](garmin_db.py) (`_init_mariadb_pool`), [garmin_db.py:117-138](garmin_db.py) (`get_mariadb_connection`)
- **Problem:** Tre saker som förstärker varandra:
  1. **Ingen TLS mot databasen.** `_init_mariadb_pool` har stöd för TLS, men aktiverar det **bara om filen `~/.healthchat/ca.pem` råkar finnas** ([garmin_db.py:196-197](garmin_db.py)). Service-filen sätter varken `MARIADB_SSL_CA` eller `MARIADB_REQUIRE_TLS=1`, så `ssl_config` blir `None` och anslutningen går i klartext. Databasen ligger på `192.168.101.106` – en **annan maskin** – så all trafik passerar nätverket. Innehållet är visserligen envelope-krypterat, men **DEK:en skickas också** över samma anslutning (se `S-13`), liksom e-postadresser, lösenordshashar och hela sessionstabellen.
  2. **`get_mariadb_connection()` har inget TLS-stöd alls** ([garmin_db.py:130-138](garmin_db.py)) – ingen `ssl`-parameter. Migreringsskriptet [migrate_sqlite_to_mariadb.py](migrate_sqlite_to_mariadb.py) använder den och skickar alltså hela databasen i klartext över nätet.
  3. ~~**Databaslösenordet är committat i klartext.**~~ ✅ **Åtgärdat i koden** – se `S-17`. Värdet ligger dock kvar i git-historiken sedan `7db86ef`, så **lösenordet måste fortfarande roteras**.
- **Åtgärd:**
  1. ✅ Klart – lösenordet är borta ur arbetskopian (`S-17`).
  2. ⚠️ **Kvarstår: rotera lösenordet.** Det ligger kvar i git-historiken och ska betraktas som läckt. Operatörschecklista:

     ```sql
     -- På MariaDB-servern. Samma nya värde som i /etc/healthchat/db.env.
     ALTER USER 'healthchat'@'192.168.101.%' IDENTIFIED BY '<nytt lösenord>';
     ALTER USER 'healthchat'@'localhost'     IDENTIFIED BY '<nytt lösenord>';
     FLUSH PRIVILEGES;
     ```

     ```bash
     # På applikationsservern, efter att db.env uppdaterats:
     sudo systemctl daemon-reload && sudo systemctl restart healthchat_web
     sudo journalctl -u healthchat_web -n 50 --no-pager | grep -iE "mariadb|saknas|sqlite"
     ```

     Leta efter `Connected to MariaDB at …`. Står det i stället `Failed to connect to MariaDB pool,
     falling back to SQLite` gick lösenordet **inte** fram – och appen serverar då delad SQLite-data
     i stället för att stanna (det är `S-14`). Kontrollera detta uttryckligen; felet är annars tyst.

     **Formatet i `db.env`:** innehåller lösenordet `$`, mellanslag eller citattecken ska hela värdet
     omges av enkla citattecken (`MARIADB_PASSWORD='mitt$lösen'`). Både systemd och parsern i
     `load_db_env()` strippar citattecken. Kommentarer måste stå på egen rad, inte efter ett värde.

     Historikomskrivning (`git filter-repo`) krävs för att få bort värdet ur gamla commits; är repot
     privat och lösenordet roterat kan det vara acceptabelt att bara rotera – ta ett medvetet beslut
     och skriv ned det här.
  3. Sätt `MARIADB_REQUIRE_TLS=1` och `MARIADB_SSL_CA=/etc/healthchat/ca.pem` i driftmiljön. Koden kastar då redan i dag om certifikatet saknas ([garmin_db.py:198-199](garmin_db.py)) – bra beteende, se till att det används.
  4. Lägg till `ssl`-stöd i `get_mariadb_connection()` med samma logik som poolen, så att migreringsskriptet inte blir en bakdörr.
  5. Konfigurera MariaDB-servern med `require_secure_transport=ON` och ge användaren `REQUIRE SSL` (`ALTER USER 'healthchat'@'%' REQUIRE SSL`), så att en felkonfigurerad klient **inte kan** ansluta i klartext.
  6. Verifiera att `pymysql` faktiskt validerar certifikatet – enbart `{"ca": path}` ger kryptering men inte nödvändigtvis värdnamnsvalidering. Sätt `check_hostname` explicit och testa mot ett felaktigt certifikat.
- **Acceptanskriterier:**
  1. `SHOW STATUS LIKE 'Ssl_cipher';` i en session öppnad av appen returnerar en chiffersvit, inte tom sträng.
  2. En anslutning utan TLS avvisas av servern.
  3. ✅ Inget hårdkodat lösenord kvar i arbetskopian – bevakas av [tests/test_no_hardcoded_secrets.py](tests/test_no_hardcoded_secrets.py).
  4. Migreringsskriptet ansluter med TLS.
  5. Lösenordet är roterat på MariaDB-servern.

---

### [ ] TLS-4: Ollama-trafiken går alltid över `http://`
- **Fil:** [ai_client.py:196-211](ai_client.py) (`normalize_ollama_url`), [ai_client.py:61](ai_client.py)
- **Problem:** `normalize_ollama_url` tvingar `http://` på allt som saknar schema ([ai_client.py:203-204](ai_client.py)), och bygger alltid om URL:en till `{scheme}://{host}:{port}/v1`. Pekar användaren Ollama mot en maskin i nätverket – vilket docstringens egna exempel (`192.168.107.15`) uppmuntrar till – går **hela hälsokontexten och AI-svaret** i klartext över LAN. Mot `localhost` är det oproblematiskt.
- **Åtgärd:**
  1. Behåll `http://` som default för loopback (`localhost`, `127.0.0.1`, `::1`) men **behåll `https://`** när användaren angett det – det gör funktionen redan, men den kan inte *uppgradera*.
  2. Logga en varning när schemat är `http` och värden inte är loopback: `"Ollama-trafik till <host> går okrypterad"`.
  3. Dokumentera i README hur man sätter en TLS-proxy framför Ollama för fjärranvändning.
- **Acceptanskriterier:**
  1. `normalize_ollama_url("https://ollama.example.se")` ger `https://ollama.example.se:443/v1`.
  2. En icke-loopback `http://`-adress ger en loggad varning.
  3. Befintliga tester i [tests/test_ai_client.py:16-31](tests/test_ai_client.py) uppdateras och är gröna.

---

### [ ] TLS-5: Chart.js laddas opinnat från CDN utan SRI
- **Fil:** [static/index.html:12](static/index.html)
- **Problem:** `<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>` – transporten är krypterad, men versionen är **opinnad** (senaste vid varje sidladdning) och saknar `integrity`-attribut. En komprometterad eller utbytt CDN-resurs kör godtycklig kod i en sida som visar hälsodata och håller en inloggad session. Det gör också `Content-Security-Policy` i `TLS-2` svagare, eftersom `cdn.jsdelivr.net` måste tillåtas.
- **Åtgärd:** Antingen (a) lägg Chart.js lokalt under `static/` – då kan CSP:n bli `default-src 'self'` – eller (b) pinna en exakt version och lägg till `integrity="sha384-…" crossorigin="anonymous"`.
- **Acceptanskriterier:** Ingen extern resurs laddas utan pinnad version och SRI, alternativt inga externa resurser alls.

---

### [ ] TLS-6: `requirements.txt` saknar webbapplikationens beroenden
- **Fil:** [requirements.txt](requirements.txt)
- **Problem:** Filen listar `garth`, `tk`, `pyinstaller` och desktopberoenden – men **varken `fastapi`, `uvicorn`, `pydantic` eller `email-validator`**, trots att [server.py:17-21](server.py) importerar alla fyra (`EmailStr` kräver `email-validator`). Webbappen går alltså inte att installera reproducerbart från repot, och man kan inte pinna den uvicorn-version som TLS-/proxy-uppsättningen i `TLS-1` förutsätter. Filens rubrik säger dessutom fortfarande "HealthChat **Desktop** v4.1.0".
- **Åtgärd:**
  1. Lägg till `fastapi`, `uvicorn[standard]`, `pydantic` och `email-validator` med pinnade versioner.
  2. Dela upp i `requirements.txt` (webb) och `requirements-desktop.txt`, eller markera desktopberoendena tydligt. `tk`, `ttkthemes` och `pyinstaller` hör inte hemma på en webbserver.
  3. Uppdatera rubriken så att den beskriver webbapplikationen.
- **Acceptanskriterier:** `pip install -r requirements.txt` i en ren venv räcker för att `uvicorn server:app` ska starta.

---

## Avfärdat (verifierat som icke-buggar)

- **`crypto.py`** – AES-256-GCM med färsk nonce per operation, korrekt KEK/DEK-separation, `low_level.Type.ID` överallt. Inga fynd.
- **SQL-injektion** – alla värden binds som parametrar; tabellnamn valideras mot `_ALLOWED_TABLES` ([garmin_db.py:397-401](garmin_db.py), [garmin_db.py:415-419](garmin_db.py)) sedan `S-11`.
- **Sorteringsordning i dashboarden** – `sleep_hist[-1]`, `hrv_hist[-1]` (ASC → senaste sist) och `activities_hist[:10]` (DESC → senaste först) är alla korrekta för sina respektive frågor.
- **Staplade route-dekoratorer** – `@app.post` / `@app.put` på samma funktion ([server.py:636-638](server.py)) fungerar som avsett i FastAPI; varje dekorator registrerar en route och returnerar funktionen oförändrad.
- **Nakna `except:`** – inga kvar i kodbasen (`P2-1` håller).
- **`hr_zones_calc.py`** – hanterar `None` och nollvärden korrekt i samtliga ingångar. Inga fynd.
- **Utgående trafik till tredjepart** – Garmin (via `garth`), Strava, Fitbit, Withings och samtliga AI-leverantörer anropas över `https://` ([strava_handler.py:25-27](strava_handler.py), [fitbit_handler.py:26-28](fitbit_handler.py), [withings_handler.py:21-23](withings_handler.py)). Inga `verify=False` någonstans i kodbasen. Undantaget är Ollama, se `TLS-4`.
