# 📋 Åtgärdstavla – HealthChat Web

> Uppgiftslista för **Antigravity** baserad på kodgenomgångar av webbapplikationen
> (**genomgång 1:** 2026-09-11, omgång 1–7, samtliga stängda · **genomgång 2:** 2026-09-17, omgång 8–11).
> Varje uppgift är fristående: den innehåller fil, plats, problem, föreslagen lösning och acceptanskriterier så att en agent kan plocka upp den direkt.
>
> **Prioritet:** `P0` = bugg/säkerhet som påverkar användaren nu · `P1` = viktig robusthet/korrekthet · `P2` = kodkvalitet/underhåll.
>
> ⚠️ **Radnumren är ögonblicksbilder.** De stämde när uppgiften skrevs, men förskjuts så fort någon
> ändrar filen ovanför. Uppgifterna citerar därför alltid den berörda koden eller funktionsnamnet –
> **sök på citatet, lita inte på radnumret**. Hittar du inte koden på angiven rad: kontrollera om en
> tidigare omgång redan åtgärdat uppgiften innan du gör något annat.
>
> **ID-serier:** `B-` buggar/korrekthet (nästa lediga: `B-9`) · `S-` säkerhet (nästa lediga: `S-25`) ·
> `TLS-` transportkryptering (nästa lediga: `TLS-8`) · `UI-` frontend (nästa lediga: `UI-3`) ·
> `PF-` prestanda (nästa lediga: `PF-11`) · `Q-` kodkvalitet (nästa lediga: `Q-21`).
> Återanvänd aldrig ett ID – även stängda uppgifter refereras från commit-meddelanden.

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

## Sammanfattning – genomgång 2 (2026-09-17)

> Andra kodgenomgången, gjord efter att omgång 1–7 stängts. Den utgår från den kod som finns i dag,
> inte från den som granskades 2026-09-11. Uppgifterna nedan har **nya ID:n** (`S-18`+, `B-8`+, `PF-8`+,
> `Q-11`+, `TLS-7`) och ligger i samma prioritetsavsnitt som tidigare fynd.

Det som åtgärdats i omgång 1–7 håller. Stickprov bekräftar att `crypto.py` är oförändrat korrekt, att
`_ALLOWED_TABLES`-valideringen och parametriseringen i `garmin_db.py` sitter, att `escapeHtml` används
konsekvent i renderingsfunktionerna (`UI-2`), att `datasource_errors` med korrelations-ID är ett bra
mönster, och att `S-13`:s DEK-hantering är genomförd som beskriven. Chart.js ligger lokalt (`TLS-5`).

De nya fynden ligger i tre kluster:

- **Sessionen och hälsodatan tar sig ut ur de skydd som byggts.** Sessionstoken returneras i JSON och
  sparas i `sessionStorage` trots `HttpOnly`-cookien (`S-18`), hela AI-chatten – inklusive skador och
  träningsmål – sparas okrypterat i `localStorage` och rensas aldrig (`S-19`), serverns
  `_user_chat_histories` städas varken vid utloggning eller kontoradering (`S-20`), och CORS-regexen
  släpper in hela 10/8 och 192.168/16 med credentials (`S-21`). Var för sig är de avgränsade; tillsammans
  urholkar de `S-13`:s och `S-15`:s löften.
- **Testsviten kan inte bli grön.** Sex API-tester failar på varje maskin utan MariaDB därför att
  `get_db()` inte går att stubba (`Q-11`), och ett Garmin-test mockar fel beroende och gör riktiga
  nätverksanrop (`Q-12`). Utan CI (`Q-13`) finns inget som fångar att skyddsnätet slutat fungera.
  **Det här blocket bör tas först** – resten av arbetet blir riskabelt utan det.
- **Underhållsskuld som börjar kosta.** README beskriver fortfarande en Windows-desktopapp (`Q-14`),
  tre nästan identiska OAuth-hanterare (`Q-16`), fyra filer över 1 200 rader (`Q-17`), obundna
  beroendeversioner (`Q-18`) och inget migrationsverktyg för schemat (`Q-19`).

Därtill fem robusthetsfynd: obegränsade minnescacher (`PF-8`), två trådar per AI-chatt ur en delad pool
(`PF-9`), läckta undantagsmeddelanden från oautentiserad endpoint (`S-22`), en 502 som skrivs om till 500
(`B-8`), poolutmattning under samtidig synk (`PF-10`) och användaruppräkning vid registrering (`S-23`).

**Verifieringsstatus:** `Q-11` och `Q-12` är reproducerade genom att köra sviten
(`7 failed, 194 passed, 8 skipped` med `pip install -r requirements.txt` i ren miljö). Övriga fynd är
verifierade genom kodläsning med citat.

**Ingen kod är ändrad i samband med den här genomgången** – tavlan är uppdaterad, inget annat.

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

### Omgång 6 – Integrationer och robusthet (✅ Klart)
`B-5` (Garmin-MFA) · `B-6` (Withings felmeddelande) · `B-7` (OAuth-tokens) · `S-16` (keyring vid kontoradering)

✅ Samtliga åtgärdade och verifierade med automatiserade tester.

### Omgång 7 – Kodkvalitet & standardisering (✅ Klart)
`Q-1` … `Q-10` samt `TLS-4`, `TLS-5`, `TLS-6`.

✅ Samtliga punkter genomförda:
- `Q-1`: `/api/user/profile/refresh` endpoint med fallback & databas-aggregering, uppdaterad UI-text och docstrings.
- `Q-2`: Session-chatthistorik bevaras per aktiv session, hälsokontext skickas via `garmin_context` utan att förorena historiken.
- `Q-3` & `Q-4`: Azure OpenAI validerar `model`/`azure_deployment` med begripligt felmeddelande, `azure_deployment` skickas som model-parameter.
- `Q-5`: Kodblocksindentering och tabellformatering bevaras via `_clean_response`.
- `Q-6`: Vid AI-anropsfel rullas användarmeddelandet tillbaka så alternerande roller bibehålls.
- `Q-7`: Konfigurerad `ollama_base_url` visas i Ollama-felsökningsmeddelandet.
- `Q-8`: Dubblett-e-post ger `ValueError("E-postadressen är redan registrerad.")` och HTTP 400 utan råa databasdetaljer.
- `Q-9`: Återställningsnyckelns entropi (200 bitar) dokumenterad sanningsenligt, Mojibake-symboler fixade, `get_db_conn` returnerar None säkert vid fel, `session.dek` kopieras via bytearray för att förhindra aliasing, `delete_account` kräver och validerar `current_password`, testisolering för desktop-moduler via `pytest.importorskip`.
- `Q-10`: `.agents/rules/compile.md` uppdaterad för webbapplikation med pytest och git-flöde.
- `TLS-4`: HTTPS stöds i `normalize_ollama_url` med default port 443; varning loggas vid okrypterad HTTP till icke-loopback.
- `TLS-5`: Chart.js pinnad till `4.4.8` med SRI sha384-hash och `crossorigin="anonymous"`.
- `TLS-6`: `requirements.txt` uppdaterad med alla webbberoenden; desktopberoenden flyttade till `requirements-desktop.txt`.


---

### Omgång 8 – Testbarhet och CI (gör denna först)
| Ordning | ID | Fil | Omfattning |
|---|---|---|---|
| 13 | `Q-11` | `server.py`, `tests/conftest.py` | `get_db` som `Depends`, `dependency_overrides` i testerna |
| 14 | `Q-12` | `tests/test_round6_integrations.py`, `pytest.ini` | Patcha `Garmin` i stället för `garth`, `--disable-socket` |
| 15 | `Q-13` | `.github/workflows/ci.yml`, `pyproject.toml` | CI med `pytest` + `ruff` |

Den här omgången ändrar ingen produktionslogik men gör alla följande omgångar verifierbara. Utan den
körs resten blint: sviten kan i dag inte bli grön lokalt, så en äkta regression går inte att skilja från
de sex kända felen. Ta den före allt annat.

### Omgång 9 – Sessionen och hälsodatan i webbläsaren
| Ordning | ID | Fil | Omfattning |
|---|---|---|---|
| 16 | `S-18` | `server.py`, `static/app.js` | Ta bort `session_id` ur svarskroppen och `sessionStorage` |
| 17 | `S-19` | `static/app.js` | Chatthistoriken ur `localStorage`, rensa vid utloggning |
| 18 | `S-20` | `server.py` | Städa `_user_chat_histories` vid utloggning, TTL och kontoradering |
| 19 | `S-21` | `server.py` | Snäva `allow_origin_regex` bakom en dev-flagga |

Alla fyra rör samma förtroendemodell och bör läsas ihop. `S-18` och `S-19` ändrar båda
`static/app.js`:s auth- och chattdelar – gör dem i samma svep för att slippa två omgångar av
manuell UI-testning. `S-21` är en isolerad rad men hör tematiskt hemma här.

### Omgång 10 – Robusthet i webblagret
| Ordning | ID | Fil | Omfattning |
|---|---|---|---|
| 20 | `B-8` | `server.py` | `except HTTPException: raise` före den generella grenen |
| 21 | `S-22` | `server.py` | Anonymisera interna fel i `login` och `get_weather` |
| 22 | `PF-8` | `server.py`, `auth.py` | Tak och städning för `_weather_cache` och `_failed_attempts` |
| 23 | `PF-9` | `server.py` | `asyncio.Queue` + `get_running_loop`, en tråd per chatt |
| 24 | `S-23` | `server.py`, `auth.py` | IP-baserad rate limiting, beslut om uppräkningsskydd |
| 25 | `PF-10` | `garmin_db.py`, `server.py` | Återanvänd poolanslutning per request |

`B-8` och `S-22` rör samma `except`-block i `get_weather` – gör dem tillsammans. `PF-10` är den
största enskilda posten här och kan brytas ut till en egen commit.

### Omgång 11 – Underhållsskuld
| Ordning | ID | Fil | Omfattning |
|---|---|---|---|
| 26 | `Q-20` | `server.py`, diverse | Dubblerad import, `lifespan`, modell-allowlist, lås på vädercachen |
| 27 | `S-24` | `garmin_handler.py` | Ta bort `garth.client`-fallbacken |
| 28 | `Q-15` | `xai_client.py` | Ta bort död kod |
| 29 | `Q-18` | `requirements*.txt` | Pinna versioner med `pip-compile --generate-hashes` |
| 30 | `Q-14` | `README.md` | Skriv om för webbapplikationen, red ut licensfrågan |
| 31 | `TLS-7` | `server.py`, `static/index.html` | Ta bort `unsafe-inline` och jsdelivr ur CSP |
| 32 | `Q-19` | `migrations/`, `server.py` | Alembic eller motsvarande, DDL ur request-vägen |
| 33 | `Q-16` | `*_handler.py` | `OAuth2Handler`-basklass |
| 34 | `Q-17` | `server.py`, `static/app.js` | Dela upp i routers och ES-moduler |

Ordningen är vald så att de billiga och isolerade posterna kommer först. `Q-16` och `Q-17` är
refaktoreringar som förutsätter grön CI från omgång 8 – ta dem sist, en delmängd per commit, och
**flytta kod utan att ändra logik** i första steget. `TLS-7` punkt 2 (inline-handlare) och `Q-17`
punkt 4 (uppdelning av `app.js`) rör samma fil och kan slås ihop.


---

### 🔧 Operatörsarbete – kan inte göras av en agent

Dessa kräver åtkomst till servern och databasen. De blockerar inte kodarbetet ovan.

- [ ] **Rotera databaslösenordet.** Kvarstår från `S-17`; värdet ligger i git-historiken sedan `7db86ef`. Se checklistan i `TLS-3`.
- [x] **Skapa `/etc/healthchat/db.env`** med rättigheterna `0600` och ägare `healthchat`. Klart.
- [ ] **`TLS-1`: reverse proxy med TLS** framför uvicorn, plus `--host 127.0.0.1` i unit-filen.
- [ ] **`TLS-3`: TLS mot MariaDB** – CA-certifikat på plats, `MARIADB_REQUIRE_TLS=1`, `require_secure_transport=ON` på servern.

---

### Miljö – så här får du testsviten att köra

Sedan `TLS-6` räcker filen i repot:

```bash
pip install -r requirements.txt
pytest -q
```

**Förväntat utfall 2026-09-17: `7 failed, 194 passed, 8 skipped`.** De sju felen är *inte* regressioner
och *inte* något du orsakat – de är två kända, öppna uppgifter:

| Test | Orsak | Uppgift |
|---|---|---|
| `test_server_api.py::test_register_login_and_me_flow` | 503 – `get_db()` går inte att stubba utan MariaDB | `Q-11` |
| `test_server_api.py::test_auth_me_with_bearer_token` | samma | `Q-11` |
| `test_server_api.py::test_preload_ai_endpoint_and_login_trigger` | samma | `Q-11` |
| `test_server_api.py::test_get_weather_endpoint` | samma | `Q-11` |
| `test_web_security.py::test_cookie_secure_flag_enabled_by_default` | samma | `Q-11` |
| `test_web_security.py::test_cookie_secure_flag_disabled_when_cookie_secure_zero` | samma | `Q-11` |
| `test_round6_integrations.py::test_b5_garmin_mfa_wait_succeeds_when_prompt_delayed` | mockar `garth` i stället för `Garmin`, går ut på riktigt nätverk | `Q-12` |

⚠️ **Att sex av sju fel är "kända" är i sig problemet.** Så länge baslinjen är röd går en äkta
regression inte att skilja från bruset. `Q-11` och `Q-12` ligger därför först i arbetskön (omgång 8),
och efter dem ska baslinjen vara **0 failed**. Uppdatera den här tabellen när det skett.

Notera också att `test_charts_view_tabs.py` inte längre behöver `--ignore` – `Q-9` punkt 7 löste
insamlingen med `pytest.importorskip`, och de 8 skippade testerna är desktop-moduler som saknas.

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

### [ ] S-18: Sessionstoken lagras i `sessionStorage` – `HttpOnly`-cookien blir verkningslös
- **Fil:** [static/app.js:18-30](static/app.js) (`getAuthHeaders`, `apiFetch`), [static/app.js:111](static/app.js) och [static/app.js:144](static/app.js) (inloggning/registrering), [server.py:515-560](server.py) (`register`), [server.py:562-600](server.py) (`login`)
- **Problem:** `TLS-2` gjorde rätt sak på serversidan: sessionscookien sätts med `httponly=True`, `secure=...` och `samesite="lax"` ([server.py:532-539](server.py)). Men **samma token returneras också i JSON-kroppen** som `session_id` ([server.py:544](server.py), [server.py:584](server.py)), och frontend sparar den direkt i webbläsarens `sessionStorage`:
  ```js
  sessionStorage.setItem('healthchat_session', data.session_id);   // app.js:111, 144
  ```
  Varje efterföljande anrop skickar den sedan som `Authorization: Bearer` via `getAuthHeaders()` ([static/app.js:18-25](static/app.js)).

  Hela poängen med `HttpOnly` är att JavaScript **inte** ska kunna läsa sessionen. Med den här uppsättningen finns token i två kanaler, varav den ena är fullt läsbar från sidans egen JS-kontext. En enda XSS – eller ett komprometterat tredjepartsskript – ger angriparen en giltig session utan att `HttpOnly` någonsin är i vägen. Att `sessionStorage` töms när fliken stängs mildrar exponeringstiden men inte själva sårbarheten.

  Angreppsytan är inte teoretisk: `Content-Security-Policy` tillåter fortfarande `script-src 'unsafe-inline'` ([server.py:92](server.py)) eftersom [static/index.html](static/index.html) har 72 `onclick`-attribut och två inline-`<script>`-block. Se `TLS-7`.

  Noterbart: serverns `get_current_session` ([server.py:468-498](server.py)) läser cookien **först** och faller tillbaka på `Authorization`-headern. Cookien fungerar alltså redan på egen hand – Bearer-vägen i webb-UI:t tillför ingenting utöver risken.
- **Åtgärd:**
  1. Ta bort `"session_id": session_id` ur svarskropparna för `/api/auth/register` ([server.py:544](server.py)) och `/api/auth/login` ([server.py:584](server.py)). Cookien räcker för webbklienten.
  2. Ta bort `getAuthHeaders()` och låt `apiFetch` skicka cookien explicit:
     ```js
     function apiFetch(url, options = {}) {
       return fetch(url, { ...options, credentials: 'same-origin' });
     }
     ```
  3. Ta bort `sessionStorage.setItem('healthchat_session', ...)` på [static/app.js:111](static/app.js) och [static/app.js:144](static/app.js), samt `removeItem`-anropen på [static/app.js:181](static/app.js) och [static/app.js:480](static/app.js) när de blivit meningslösa.
  4. **Behåll** Bearer-stödet i `get_current_session` – det är rimligt för framtida API-klienter och skript – men dokumentera att webbgränssnittet inte använder det.
  5. Kontrollera att SSE-anropet mot `/api/ai/chat` också går med cookie (`fetch` skickar same-origin-cookies som standard, men anropet måste sluta sätta en egen `Authorization`-header).
- **Acceptanskriterier:**
  1. `sessionStorage.getItem('healthchat_session')` är `null` efter en lyckad inloggning i webbläsaren.
  2. Inloggning, dashboard, chatt, profil och datakällor fungerar samtliga enbart på cookien.
  3. Svaret från `POST /api/auth/login` innehåller inte längre någon sessionsidentifierare i kroppen.
  4. Test som asserterar att `login`-svarets JSON saknar nyckeln `session_id` men att `Set-Cookie` finns.

---

### [ ] S-19: Chatthistoriken – hälsodata i klartext – sparas i `localStorage` och rensas aldrig
- **Fil:** [static/app.js:1733-1736](static/app.js) (`getChatStorageKey`), [static/app.js:1738-1745](static/app.js) (`getStoredChatHistory`), [static/app.js:1747-1753](static/app.js) (`saveStoredChatHistory`), [static/app.js:177-183](static/app.js) (`handleLogout`)
- **Problem:** Hela konversationen med AI-coachen sparas okrypterad i `localStorage`:
  ```js
  function getChatStorageKey() {
    const uid = (currentUser && (currentUser.user_id || currentUser.id || currentUser.email)) || 'default';
    return `healthchat_chat_history_${uid}`;
  }
  ```
  Innehållet är inte harmlöst: svaren bygger på `garmin_context` som servern fyller med sömn, HRV, vilopuls, maxpuls, BMI, vikt, fett%, **kända skador/fysiska begränsningar** och träningsmål ([server.py:841-886](server.py)). Det är känsliga hälsouppgifter.

  `localStorage` är – till skillnad från `sessionStorage` – **beständigt**. Datan överlever:
  - utloggning (`handleLogout` på [static/app.js:177-183](static/app.js) rensar bara `sessionStorage`),
  - webbläsarstängning och omstart av datorn,
  - och till och med `POST /api/user/delete_account` – kontot raderas på servern men historiken ligger kvar i webbläsarprofilen.

  Det står i direkt konflikt med README:s säkerhetsavsnitt, som beskriver en zero-knowledge-arkitektur där hälsodata är envelope-krypterad och DEK:en aldrig lämnar processminnet. Nyckeln är dessutom bara `user_id` – på en delad dator ser nästa användare av samma webbläsarprofil hela historiken.

  Värt att notera: servern har **redan** historiken (`_session_chat_histories` / `_user_chat_histories`, exponerad via `GET /api/ai/chat/history` på [server.py:959-972](server.py)). Klientkopian är alltså en andra sanningskälla som inte behövs, och de två kan dessutom glida isär – servern trunkerar till 20 meddelanden ([ai_client.py:312-313](ai_client.py)), klienten till 50 ([static/app.js:1759-1760](static/app.js)).
- **Åtgärd:**
  1. **Förstahandsval:** ta bort klientlagringen helt och läs historiken från `GET /api/ai/chat/history` vid inladdning av chattfliken. En sanningskälla, ingen hälsodata på disk i webbläsaren.
  2. **Om lokal cache ändå önskas** (t.ex. för att överleva en omladdning utan serveranrop): byt `localStorage` → `sessionStorage`, som töms när fliken stängs.
  3. Rensa nyckeln explicit i `handleLogout()` oavsett vilket alternativ som väljs:
     ```js
     localStorage.removeItem(getChatStorageKey());
     sessionStorage.removeItem('healthchat_weather');
     ```
     Gör det **innan** `currentUser = null`, annars pekar `getChatStorageKey()` redan på `_default`.
  4. Rensa även vid kontoradering i samma flöde.
  5. Synka trunkeringsgränsen mellan klient och server så att de visar samma sak.
- **Acceptanskriterier:**
  1. Efter utloggning finns ingen `healthchat_chat_history_*`-nyckel kvar i `localStorage`.
  2. Efter kontoradering finns ingen rest av användarens chatt i webbläsaren.
  3. Chattfliken visar fortfarande tidigare konversation efter en sidomladdning med aktiv session.
  4. README:s säkerhetsavsnitt beskriver sanningsenligt vad som lagras i webbläsaren.

---

### [ ] S-20: `_user_chat_histories` rensas aldrig – hälsodata överlever utloggning och kontoradering i RAM
- **Fil:** [server.py:107-108](server.py) (deklarationerna), [server.py:153-161](server.py) (`remove_active_session`), [server.py:947-949](server.py) (skrivningen), [server.py:973-983](server.py) (`clear_chat_history`), [server.py:1269-1305](server.py) (`delete_account`)
- **Problem:** Serverns chatthistorik finns i **två** dictar:
  ```python
  _session_chat_histories: Dict[str, List[Dict[str, str]]] = {}   # nyckel: session_id
  _user_chat_histories: Dict[int, List[Dict[str, str]]] = {}      # nyckel: user_id
  ```
  `remove_active_session()` – som körs vid utloggning, vid TTL-utgång och från `cleanup_expired_sessions()` – poppar **bara** den första:
  ```python
  _session_expirations.pop(session_id, None)
  _session_chat_histories.pop(session_id, None)      # server.py:157
  sess = _active_sessions.pop(session_id, None)
  ```
  `_user_chat_histories[user_id]` lämnas orörd. Efter utloggning ligger alltså användarens hälsokonversation kvar i processminnet, och eftersom `chat_stream` läser den som fallback ([server.py:912-913](server.py)) återuppstår historiken vid nästa inloggning – även om användaren trodde att utloggningen städade.

  Samma sak gäller `delete_account` ([server.py:1269](server.py)): kontot, nycklarna och alla krypterade rader raderas ur MariaDB, men `_user_chat_histories[user_id]` finns kvar tills processen startas om. `S-13`:s löfte – "DEK:en nollställs i minnet vid utloggning, kontoradering och TTL-utgång" – gäller nyckeln men inte den klartextdata som redan dekrypterats och lagts i den här dicten.

  Utöver dataläckan är det en ren minnesläcka: dicten har varken TTL eller storleksgräns och växer linjärt med antalet användare som någonsin chattat sedan senaste omstart. Med `--workers 1` ([healthchat_web.service](healthchat_web.service)) betyder det att en långlivad process ackumulerar allt.

  Notera att `clear_chat_history` ([server.py:981](server.py)) gör rätt – den poppar båda. Mönstret finns alltså redan i filen, det saknas bara på utloggnings- och raderingsvägarna.
- **Åtgärd:**
  1. Ge `remove_active_session()` tillgång till `user_id` (sessionsobjektet finns redan i funktionen) och poppa båda:
     ```python
     sess = _active_sessions.pop(session_id, None)
     if sess:
         _user_chat_histories.pop(sess.user_id, None)
         sess.clear()
     ```
  2. Gör samma sak i `cleanup_expired_sessions()` ([server.py:179-196](server.py)), som poppar `_active_sessions` direkt utan att gå via `remove_active_session`.
  3. Lägg till `_user_chat_histories.pop(session.user_id, None)` i `delete_account` innan svaret returneras.
  4. Sätt ett tak på `_user_chat_histories` (t.ex. `OrderedDict` med LRU-vräkning vid 500 poster) så att dicten inte kan växa obegränsat även om någon väg missas i framtiden.
  5. Överväg att ta bort `_user_chat_histories` helt. Den är en fallback för när `healthchat_session`-cookien saknas – men eftersom `get_current_session` kräver en giltig token för att alls nå endpointen, är `_session_chat_histories` i praktiken alltid tillgänglig. Färre kopior av hälsodata i minnet är en vinst i sig.
- **Acceptanskriterier:**
  1. Test: logga in, chatta, logga ut → `server._user_chat_histories` innehåller inte längre användarens `user_id`.
  2. Test: logga in, chatta, radera kontot → varken `_session_chat_histories` eller `_user_chat_histories` innehåller något spår av användaren.
  3. Test: en session som passerat TTL städas ur båda dictarna av `cleanup_expired_sessions()`.
  4. Dicten har ett dokumenterat övre tak.

---

### [ ] S-21: CORS-regexen litar på hela det privata adressrymden – med credentials
- **Fil:** [server.py:72-79](server.py) (`app.add_middleware(CORSMiddleware, ...)`), särskilt [server.py:76](server.py)
- **Problem:** `S-15` löste den öppna `allow_origins=["*"]`-listan. Men raden under återöppnar den:
  ```python
  allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?",
  allow_credentials=_allow_credentials,
  ```
  `allow_origin_regex` är ett **komplement** till `allow_origins` i Starlette, inte ett filter på den. Effekten är att **varje origin** i 192.168.0.0/16 och 10.0.0.0/8, samt `localhost`/`127.0.0.1` på **valfri port**, får göra credentialed cross-origin-anrop och **läsa svaren**.

  Konkreta konsekvenser:
  - En godtycklig annan tjänst på samma LAN (en router, en NAS, en skrivare med webbgränssnitt, en kollegas utvecklingsserver) blir en förtroendegräns som ni inte medvetet valt. Får någon av dem en XSS kan den tömma hälsodatan hos varje HealthChat-användare som besöker den.
  - `localhost` på valfri port betyder att **vilken lokalt installerad applikation som helst** som exponerar en webbserver kan läsa API:et med användarens session.
  - `_allow_credentials` beräknas från `_allowed_origins` ([server.py:70](server.py)) och tar **inte** hänsyn till regexen. Skyddet mot kombinationen wildcard + credentials gäller alltså bara den explicita listan.

  Att `SameSite=Lax` sitter på cookien hjälper delvis mot enkla `<form>`-POST:ar, men CORS-preflight med `credentials: 'include'` från en tillåten origin är en annan väg – och `S-18` gör dessutom att token kan skickas som `Authorization`-header, vilket `SameSite` inte berör alls.
- **Åtgärd:**
  1. Ta bort `allow_origin_regex` ur produktionskonfigurationen. `ALLOWED_ORIGINS` i [.env.example](.env.example) är redan rätt mekanism.
  2. Behövs LAN-åtkomst under utveckling – gör den till ett medvetet opt-in:
     ```python
     _dev_lan = os.getenv("DEV_ALLOW_LAN_ORIGINS", "0").strip().lower() in ("1", "true", "yes")
     cors_kwargs = {"allow_origins": _allowed_origins, "allow_credentials": _allow_credentials, ...}
     if _dev_lan:
         cors_kwargs["allow_origin_regex"] = r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?"
     app.add_middleware(CORSMiddleware, **cors_kwargs)
     ```
     Logga en varning vid uppstart när flaggan är på.
  3. Låt `_allow_credentials` bli `False` så fort en regex är aktiv **och** listan inte är explicit – eller dokumentera uttryckligen varför kombinationen är acceptabel i utvecklingsläge.
  4. Dokumentera i [.env.example](.env.example) att `ALLOWED_ORIGINS` måste sättas i drift, och att tom lista betyder "bara localhost:8000".
- **Acceptanskriterier:**
  1. Test: `OPTIONS`/`GET` mot `/api/auth/me` med `Origin: http://192.168.1.50:3000` får **inget** `Access-Control-Allow-Origin` i svaret när `DEV_ALLOW_LAN_ORIGINS` är osatt.
  2. Test: samma anrop med `Origin` ur `ALLOWED_ORIGINS` får `Access-Control-Allow-Origin` och `Access-Control-Allow-Credentials: true`.
  3. Med `DEV_ALLOW_LAN_ORIGINS=1` loggas en varning vid uppstart.
  4. `.env.example` beskriver flaggan och dess risk.

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

### [x] B-5: Garmin-MFA kapplöpning – inloggning misslyckas när prompten dröjer (åtgärdad med mfa_requested och konfigurerbar timeout)
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

### [ ] Q-11: `get_db()` går inte att stubba – sex API-tester failar utan levande MariaDB
- **Fil:** [server.py:267-270](server.py) (`get_db`), anropsställena i [server.py:515](server.py), [server.py:562](server.py), [server.py:658](server.py), [server.py:700](server.py), [server.py:1047](server.py) m.fl., [tests/test_server_api.py](tests/test_server_api.py), [tests/test_web_security.py](tests/test_web_security.py)
- **Status:** ✅ Reproducerat – `pytest -q` i ren miljö ger `7 failed, 194 passed, 8 skipped`.
- **Problem:** `get_db()` är deklarerad som en vanlig funktion och **anropas direkt inne i route-kropparna**:
  ```python
  @app.post("/api/auth/register")
  def register(req, response, request, background_tasks):
      db = get_db()                  # server.py:517 – inte en dependency
      conn = get_db_conn(db)
  ```
  Eftersom den inte går via `Depends()` kan den inte ersättas med `app.dependency_overrides`. Testerna försöker i stället stubba lagret under (`monkeypatch.setattr("server.get_db_conn", lambda db: None)`), men `get_db()` hinner konstruera `GarminDatabase(require_mariadb=True)` och kasta `RuntimeError` **innan** stubben blir relevant. `runtime_database_error_handler` ([server.py:312-325](server.py)) fångar den och returnerar 503.

  Följden är att sex tester failar på varje maskin som saknar en konfigurerad MariaDB:
  ```
  FAILED tests/test_server_api.py::test_register_login_and_me_flow
  FAILED tests/test_server_api.py::test_auth_me_with_bearer_token
  FAILED tests/test_server_api.py::test_preload_ai_endpoint_and_login_trigger
  FAILED tests/test_server_api.py::test_get_weather_endpoint
  FAILED tests/test_web_security.py::test_cookie_secure_flag_enabled_by_default
  FAILED tests/test_web_security.py::test_cookie_secure_flag_disabled_when_cookie_secure_zero
  ```
  Samtliga med `assert 503 == 200` och `{"detail":"Databasen är inte tillgänglig för tillfället (MariaDB krävs)."}`.

  Det här är inte ett testfel utan ett designfel som *yttrar sig* i testerna: `.agents/rules/` föreskriver "kör alltid `pytest -v`", men regeln är omöjlig att följa meningsfullt när sviten aldrig kan bli grön lokalt. En agent eller utvecklare som ser sex röda tester som "normalt" kommer att missa den sjunde som är en äkta regression. Det blockerar också `Q-13` (CI), eftersom en CI-körare inte har någon MariaDB.

  Notera att `S-14`:s beteende är **korrekt och ska behållas** – webben ska vägra köra utan MariaDB. Problemet är enbart att testerna inte kan komma förbi konstruktionen.
- **Åtgärd:**
  1. Gör `get_db` till en riktig FastAPI-dependency och injicera den i alla routes:
     ```python
     def get_db(require_mariadb: bool = True) -> GarminDatabase:
         return GarminDatabase(require_mariadb=require_mariadb)

     @app.post("/api/auth/register")
     def register(..., db: GarminDatabase = Depends(get_db)):
     ```
     Behåll signaturen så att `bind_user_db` och bakgrundstrådarna (`build_worker_db`, [server.py:1741-1745](server.py)) kan fortsätta anropa den direkt – de ligger utanför request-scope och ska inte överridas.
  2. Gör samma sak för `bind_user_db` där den används i en route, alternativt låt den ta `db` som argument i stället för att konstruera ett eget.
  3. Lägg en delad fixture i [tests/conftest.py](tests/conftest.py) som sätter `app.dependency_overrides[get_db]` till en SQLite-backad `GarminDatabase(require_mariadb=False)` i en `tmp_path`, och river ner den efteråt.
  4. Skriv om de sex testerna att använda fixturen i stället för `monkeypatch.setattr("server.get_db_conn", ...)`.
  5. Uppdatera avsnittet *Miljö – så här får du testsviten att köra* i den här filen: det är inaktuellt sedan `TLS-6` (beroendena ligger numera i `requirements.txt`) och anger fel förväntat utfall.
- **Acceptanskriterier:**
  1. `pip install -r requirements.txt && pytest -q` ger **0 failed** på en maskin utan MariaDB.
  2. Inget test kräver en miljövariabel eller en extern databas för att passera.
  3. `app.dependency_overrides` används i stället för `monkeypatch` på interna funktionsnamn i API-testerna.
  4. `S-14`-beteendet är oförändrat: utan override och utan MariaDB svarar endpointen fortfarande 503.

---

### [ ] Q-12: `test_b5_garmin_mfa_wait_succeeds_when_prompt_delayed` mockar fel beroende och ringer Garmin på riktigt
- **Fil:** [tests/test_round6_integrations.py:20-40](tests/test_round6_integrations.py), [garmin_handler.py:279-353](garmin_handler.py) (`authenticate`)
- **Status:** ✅ Reproducerat – testet failar med `ProxyError`/`Max retries exceeded with url: sso.garmin.com`.
- **Problem:** Testet patchar `garmin_handler.garth`:
  ```python
  with patch("garmin_handler.garth") as mock_garth:
      mock_garth.login.side_effect = mock_login
      res = handler.authenticate()
      assert res == {"mfa_required": True}
  ```
  Men `authenticate()` går sedan länge via `garminconnect.Garmin`, inte via `garth.login`. Modulen `garth` importeras fortfarande ([garmin_handler.py:5](garmin_handler.py)) men används numera bara i en fallback i `_resolve_display_name` ([garmin_handler.py:391](garmin_handler.py), se `S-24`). Mocken träffar alltså ingenting – anropet går ut på riktigt nätverk mot `sso.garmin.com` och failar på proxyn:
  ```
  assert {'error': 'Inloggningen misslyckades: Login failed: All login strategies exhausted: ...'}
      == {'mfa_required': True}
  ```
  Två problem i ett:
  1. `B-5` är markerad `[x]` men dess regressionstest testar i praktiken ingenting sedan Garmin-klienten byttes ut. Skulle MFA-kapplöpningen återuppstå fångas den inte.
  2. Testsviten gör **utgående nätverksanrop** mot en tredjepartstjänst. Det gör körningar långsamma, flakiga och beroende av omvärlden – och i värsta fall skickas riktiga inloggningsförsök mot Garmin från en CI-miljö.
- **Åtgärd:**
  1. Patcha rätt symbol: `patch("garmin_handler.Garmin")` och låt mocken returnera ett objekt vars `login()` beter sig som det fördröjda MFA-flödet. Verifiera mot den faktiska koden i `authenticate()` innan mocken skrivs – citera koden, lita inte på minnet.
  2. Gå igenom övriga tester i [tests/test_round6_integrations.py](tests/test_round6_integrations.py) och [tests/test_garmin_handler.py](tests/test_garmin_handler.py) efter samma fel.
  3. Lägg till `pytest-socket` i testberoendena och sätt `addopts = -v --disable-socket --allow-unix-socket` i [pytest.ini](pytest.ini). Då **kan** ingen test smyga ut på nätet igen – ett felaktigt mockat test failar med `SocketBlockedError` i stället för att tyst göra riktiga anrop.
  4. Där ett test avsiktligt behöver nätverk (finns inget sådant i dag): markera det med `@pytest.mark.enable_socket` och `@pytest.mark.integration`, och exkludera markeringen i standardkörningen.
- **Acceptanskriterier:**
  1. Testet passerar utan nätverksåtkomst och verifierar faktiskt MFA-vägen i `authenticate()`.
  2. `pytest -q` med nätverket avstängt ger samma resultat som med nätverket på.
  3. `--disable-socket` är aktivt som standard i `pytest.ini`.
  4. Inget test tar mer än någon sekund på grund av nätverkstimeouts.

---

### [ ] Q-13: Ingen CI – regressionsskyddet vilar helt på disciplin
- **Fil:** saknas – ingen `.github/`-katalog finns i repot. Regeln som ska ersätta CI: [.agents/rules/compile.md](.agents/rules/compile.md)
- **Problem:** `.agents/rules/` och den här tavlan säger båda "kör alltid `pytest -v`" före och efter varje ändring. Det är rätt instruktion, men den är **oframtvingad**: inget hindrar att en commit med röda tester hamnar på `main`. Historiken visar också att det händer – `Q-12` beskriver ett test som slutat testa det det påstår, utan att någon märkt det.

  Projektet har 27 testfiler och 202 testfall. Det är ett värdefullt skyddsnät som i dag bara används när någon kommer ihåg att dra i det. Med `Q-11` åtgärdad kan hela sviten köras utan extern infrastruktur, och då är CI en halvtimmes arbete som permanent tar bort en hel kategori av misstag.
- **Åtgärd:**
  1. Lägg till `.github/workflows/ci.yml` som kör på `push` och `pull_request`:
     ```yaml
     name: CI
     on: [push, pull_request]
     jobs:
       test:
         runs-on: ubuntu-latest
         steps:
           - uses: actions/checkout@v4
           - uses: actions/setup-python@v5
             with:
               python-version: "3.11"
           - run: pip install -r requirements.txt
           - run: python -c "import server; print('server imports OK')"
           - run: pytest -q
     ```
     Stegen speglar exakt det som `.agents/rules/compile.md` redan föreskriver manuellt.
  2. Lägg till ett `ruff`-steg (`ruff check .`) med en `pyproject.toml`-konfiguration. Börja med en smal regeluppsättning (`E`, `F`, `W`, `I`) så att den går grön direkt, och skärp över tid.
  3. Överväg `ruff format --check` i stället för `black` – ett verktyg, en konfiguration.
  4. Uppdatera [.agents/rules/compile.md](.agents/rules/compile.md) så att den hänvisar till CI som den auktoritativa kontrollen, med lokal `pytest` som snabb förkontroll.
  5. Lägg gärna till ett schemalagt veckojobb (`schedule: cron`) som kör sviten mot senaste beroendeversionerna – fångar att `garth`/`garminconnect` har brutit något innan användarna gör det.
- **Acceptanskriterier:**
  1. En PR med ett medvetet trasigt test blockeras av CI.
  2. `python -c "import server"` ingår som eget steg (fångar import- och syntaxfel utan att hela sviten behöver köras).
  3. CI kräver ingen MariaDB, inga hemligheter och ingen nätverksåtkomst till tredjepart.
  4. Badge eller länk till CI-status i README.

---

### [ ] PF-8: `_weather_cache` och `_failed_attempts` växer obegränsat på klientkontrollerade nycklar
- **Fil:** [server.py:997](server.py) (`_weather_cache`), [server.py:1081-1083](server.py) och [server.py:1147](server.py) (användningen), [auth.py:43](auth.py) (`_failed_attempts`), [auth.py:98-115](auth.py) (`check_rate_limit`, `record_failed_attempt`)
- **Problem:** **Vädercachen** nycklas på klientens egna koordinater:
  ```python
  cache_key = f"{round(resolved_lat, 2)}_{round(resolved_lon, 2)}"   # server.py:1081
  ...
  _weather_cache[cache_key] = {"time": now, "data": data}            # server.py:1147
  ```
  `lat`/`lon` kommer från query-parametrar ([server.py:1049-1050](server.py)). De valideras som `float` av Pydantic men har varken intervallkontroll eller antalsbegränsning. Två decimaler ger ~648 miljoner distinkta nycklar inom giltigt intervall – och inget vräks någonsin ut. Tidsstämpeln på [server.py:1082](server.py) används bara för att avgöra om en post är *färsk*, aldrig för att ta bort en gammal.

  En inloggad användare (eller ett trasigt frontend som råkar skicka ofiltrerade GPS-värden) kan alltså få processen att växa obegränsat. Varje miss innebär dessutom ett utgående anrop till Open-Meteo, så samma parameter är en förstärkare för utgående trafik.

  **Rate-limit-dicten** har samma form av problem:
  ```python
  _failed_attempts: Dict[str, list] = {}

  def check_rate_limit(email):
      if clean_email in _failed_attempts:
          _failed_attempts[clean_email] = [t for t in _failed_attempts[clean_email] if now - t < 60]
  ```
  Filtreringen sker **bara för den e-post som just slås upp**. Alla andra nycklar blir kvar för evigt. Eftersom vem som helst kan posta godtyckliga e-postadresser till `/api/auth/login` är det en direkt väg att fylla minnet med en post per försök. Tomma listor rensas heller aldrig bort.

  Ingen av dem är kritisk i ett litet installerat system, men båda är onödiga och triviala att täppa till.
- **Åtgärd:**
  1. Ge vädercachen ett tak och LRU-vräkning:
     ```python
     from collections import OrderedDict
     _WEATHER_CACHE_MAX = 500
     _weather_cache: "OrderedDict[str, Any]" = OrderedDict()
     ...
     _weather_cache[cache_key] = {"time": now, "data": data}
     _weather_cache.move_to_end(cache_key)
     while len(_weather_cache) > _WEATHER_CACHE_MAX:
         _weather_cache.popitem(last=False)
     ```
     Skydda den med ett lås – endpointen körs i Starlettes trådpool och dicten delas mellan trådar.
  2. Validera koordinaterna: `lat: Optional[float] = Query(None, ge=-90, le=90)`, `lon: Optional[float] = Query(None, ge=-180, le=180)`. Ogiltiga värden ska ge 422, inte ett utgående anrop.
  3. Rensa hela `_failed_attempts` periodiskt – enklast i samma sväng som `cleanup_expired_sessions()` ([server.py:175](server.py)): ta bort nycklar vars lista är tom efter filtrering, och nycklar vars senaste försök är äldre än fönstret.
  4. Ta bort nyckeln i `clear_failed_attempts()` – det görs redan ([auth.py:119-122](auth.py)), men det hjälper bara vid lyckad inloggning.
- **Acceptanskriterier:**
  1. Test: 1 000 anrop till `/api/weather` med olika koordinater lämnar högst `_WEATHER_CACHE_MAX` poster i cachen.
  2. Test: `lat=999` ger 422 utan utgående HTTP-anrop.
  3. Test: 1 000 misslyckade inloggningar mot olika e-postadresser följt av ett städanrop lämnar inga tomma listor kvar i `_failed_attempts`.
  4. Båda strukturerna har ett dokumenterat övre tak i en kommentar vid deklarationen.

---

### [ ] PF-9: AI-chatten binder två trådar per samtal ur samma exekutor
- **Fil:** [server.py:920-956](server.py) (`event_generator` i `chat_stream`), särskilt [server.py:934-940](server.py)
- **Problem:** Strömningen bygger en brygga mellan den synkrona `client.chat_stream()`-generatorn och den asynkrona SSE-responsen via en `queue.Queue`:
  ```python
  loop = asyncio.get_event_loop()
  loop.run_in_executor(None, producer)              # tråd 1: kör AI-anropet
  while True:
      item = await loop.run_in_executor(None, q.get)  # tråd 2: blockerar på kön
  ```
  Tre problem:
  1. **Två trådar per pågående chatt.** Båda tas ur eventloopens default-`ThreadPoolExecutor`, som har `min(32, os.cpu_count() + 4)` trådar. På en typisk liten server (2–4 kärnor) är det 6–8 trådar, alltså **3–4 samtidiga chattar** innan poolen är slut. Efter det blockerar nya chattar tills en tidigare är klar – och eftersom Ollama-timeouten är 300 sekunder ([ai_client.py:233](ai_client.py)) kan väntan bli lång. Symptomet blir "chatten hänger", inte ett felmeddelande.
  2. **`await loop.run_in_executor(None, q.get)` per chunk.** Varje token innebär en tur och retur till trådpoolen. Det är ett omfattande overhead per tecken för något som kan göras utan trådväxling.
  3. **`asyncio.get_event_loop()` är deprecated** när den anropas inuti en coroutine. Den ger `DeprecationWarning` i Python 3.12 och kommer att sluta fungera. Rätt anrop är `asyncio.get_running_loop()`.

  Dessutom: `loop.run_in_executor(None, producer)` returnerar en `Future` som aldrig awaitas. Undantag fångas visserligen av producenten själv ([server.py:928-931](server.py)), men om något kastas *utanför* den `try`-satsen försvinner det tyst.
- **Åtgärd:**
  1. Byt `queue.Queue` mot `asyncio.Queue` och låt producenttråden mata den trådsäkert:
     ```python
     loop = asyncio.get_running_loop()
     q: asyncio.Queue = asyncio.Queue()

     def producer():
         try:
             for chunk in client.chat_stream(req.message, garmin_context=garmin_context):
                 loop.call_soon_threadsafe(q.put_nowait, chunk)
         except Exception as ex:
             loop.call_soon_threadsafe(q.put_nowait, ex)
         finally:
             loop.call_soon_threadsafe(q.put_nowait, SENTINEL)

     task = loop.run_in_executor(None, producer)
     while True:
         item = await q.get()     # äkta asynkron väntan, ingen tråd
         ...
     ```
     Då går åtgången från två trådar till en per chatt, och konsumtionen kostar inget.
  2. Behåll referensen till `task` och `await` den i ett `finally`-block så att undantag inte tappas och tråden inte blir hängande om klienten kopplar ner.
  3. Hantera klientavbrott: om webbläsaren stänger strömmen mitt i ska producenten avslutas, inte fortsätta mala mot Ollama. `await request.is_disconnected()` eller en `asyncio.CancelledError`-hanterare i generatorn.
  4. Överväg en dedikerad `ThreadPoolExecutor` för AI-anropen med ett explicit, konfigurerbart tak, så att de inte konkurrerar med annan `run_in_executor`-användning.
- **Acceptanskriterier:**
  1. Inga `DeprecationWarning` från `asyncio.get_event_loop()` i testkörningen.
  2. Test: N samtidiga strömmande chattar (N > antalet trådar i default-poolen) startar alla utan att blockera varandra.
  3. En avbruten klientanslutning avslutar producenttråden inom rimlig tid.
  4. Ett undantag i producenten når fortfarande klienten som `{"error": ...}`.

---

### [ ] S-22: `/api/auth/login` och `/api/weather` läcker råa undantagsmeddelanden till klienten
- **Fil:** [server.py:593](server.py) (`login`), [server.py:1151](server.py) (`get_weather`), att jämföra med [server.py:551-553](server.py) (`register`) och [server.py:1362-1385](server.py) (`datasource_errors`)
- **Problem:** Projektet har redan **rätt mönster** på två ställen. `register` döljer detaljerna:
  ```python
  except Exception as e:
      logger.error(f"Registreringsfel: {e}", exc_info=True)
      raise HTTPException(status_code=500, detail="Serverfel vid registrering. Försök igen senare.")
  ```
  och `datasource_errors` är än bättre – den ger ett korrelations-ID och skriver detaljerna enbart i loggen, med en uttrycklig motivering i docstringen om att felmeddelanden kan bära anslutningssträngar och URL:er med tokens.

  Men två endpoints följer inte mönstret:
  ```python
  raise HTTPException(status_code=500, detail=f"Serverfel vid inloggning: {e}")     # server.py:593
  raise HTTPException(status_code=500, detail=f"Kunde inte hämta väder: {ex}")      # server.py:1151
  ```
  `login`-vägen är den känsligaste i hela applikationen. Ett `pymysql`-undantag därifrån kan innehålla värdnamn, portar, databasnamn, användarnamn och sökvägar – information som en angripare annars måste gissa sig till. Endpointen är dessutom **oautentiserad**, så vem som helst kan provocera fram den.

  `/api/weather` är autentiserad men läcker på samma sätt detaljer om utgående anrop och intern infrastruktur.
- **Åtgärd:**
  1. Använd `datasource_errors`-mönstret konsekvent. Lyft ut det till en generell hjälpare, t.ex. `internal_error(context: str, exc: Exception) -> HTTPException`, som loggar med `exc_info=True` och returnerar `f"{context} misslyckades ({type(exc).__name__}). Felkod {error_id}."`.
  2. Applicera den på `login` och `get_weather`, och gå igenom övriga `except Exception`-block i [server.py](server.py) efter samma mönster (`grep -n 'detail=f"' server.py`).
  3. Behåll `ValueError` → 400/401 med användarvänlig text som i dag – det är avsiktligt och rätt. Det är bara de oväntade felen som ska anonymiseras.
  4. Se även `B-8` nedan, som rör samma `except`-block i `get_weather`.
- **Acceptanskriterier:**
  1. Ett framtvingat databasfel under `/api/auth/login` ger ett svar utan värdnamn, portar, sökvägar eller undantagstext.
  2. Samma fel går att hitta i serverloggen via korrelations-ID:t i svaret.
  3. Test som asserterar att svarskroppen vid internt fel inte innehåller strängen `pymysql` eller något av konfigurationsvärdena.

---

### [ ] B-8: `HTTPException(502)` i väderendpointen skrivs om till 500 av det egna `except`-blocket
- **Fil:** [server.py:1100-1151](server.py) (`get_weather`), specifikt [server.py:1109](server.py) och [server.py:1149-1151](server.py)
- **Problem:** Endpointen kastar medvetet en 502 när Open-Meteo svarar med fel statuskod:
  ```python
  m_resp = requests.get(meteo_url, timeout=5)
  if m_resp.status_code != 200:
      raise HTTPException(status_code=502, detail="Kunde inte hämta data från Open-Meteo")   # server.py:1109
  ```
  Men den raden ligger inuti ett `try` vars `except` fångar **allt**:
  ```python
  except Exception as ex:
      logger.error(f"Väderfel: {ex}", exc_info=True)
      raise HTTPException(status_code=500, detail=f"Kunde inte hämta väder: {ex}")           # server.py:1151
  ```
  `HTTPException` ärver från `Exception`, så den medvetna 502:an fångas och skrivs om till en 500. Klienten kan därmed inte skilja "uppströmstjänsten svarar inte" (502, övergående, meningsfullt att försöka igen) från "något gick sönder hos oss" (500). Felkoden som utvecklaren skrev blir aldrig observerbar.

  Samma mönster finns i `datasource_errors` – men där är det **korrekt hanterat** med ett explicit `except HTTPException: raise` ([server.py:1372-1373](server.py)) före den generella grenen. Rättningen finns alltså redan i kodbasen, den saknas bara här.
- **Åtgärd:**
  1. Lägg till en tidigare gren i `get_weather`:
     ```python
     except HTTPException:
         raise
     except Exception as ex:
         ...
     ```
  2. Gör samma genomgång i övriga endpoints som både kastar `HTTPException` och har ett brett `except Exception` i samma `try` – sök på `except Exception` i [server.py](server.py) och kontrollera varje förekomst.
  3. Kombinera med `S-22` så att den generella grenen samtidigt slutar läcka `ex`.
- **Acceptanskriterier:**
  1. Test: `requests.get` mockad att returnera status 503 från Open-Meteo ger **502** från `/api/weather`, inte 500.
  2. Test: `requests.get` mockad att kasta `ConnectionError` ger 500 med anonymiserat meddelande.
  3. Ingen endpoint i `server.py` har ett `except Exception` som kan svälja en egen `HTTPException`.

---

### [ ] PF-10: Dashboarden tar ~10 poolanslutningar per anrop mot en pool på 10
- **Fil:** [garmin_db.py:180-200](garmin_db.py) (`_create_mariadb_pool`), [garmin_db.py:499-524](garmin_db.py) (`_mariadb_get_history`), [server.py:700-766](server.py) (`get_dashboard_summary`), [server.py:1741-1745](server.py) (`build_worker_db`)
- **Problem:** Varje getter i `GarminDatabase` hämtar och stänger en **egen** poolanslutning:
  ```python
  conn = self.get_mariadb_conn()
  try:
      ...
  finally:
      conn.close()
  ```
  `/api/dashboard/summary` anropar nio sådana i följd – `get_daily_summary_history`, `get_sleep_history`, `get_body_battery_history`, `get_stress_history`, `get_hrv_history`, `get_activities_history`, `get_latest_body_composition`, `get_body_composition_history`, `get_calorie_burn_history` ([server.py:706-715](server.py)) – plus `get_daily_summary` och `auto_sync_user_profile`, som i sin tur läser ytterligare tabeller via `profile_sync`.

  Poolen är konfigurerad så här:
  ```python
  maxconnections=int(os.environ.get("MARIADB_MAX_CONNECTIONS", "10")),
  blocking=True,
  ```
  Anslutningarna tas och lämnas tillbaka sekventiellt, så ett ensamt request klarar sig. Men bakgrundstrådarna för datakällesynk ([server.py:1748-1812](server.py), `_run_datasource_sync`) håller en anslutning under **hela** synkroniseringen, som kan ta minuter. Kör tre användare synk samtidigt medan några laddar dashboarden är poolen snabbt slut – och med `blocking=True` blir resultatet att requests **hänger** i stället för att faila. Det är betydligt svårare att felsöka än ett tydligt fel.

  Därtill: `auto_sync_user_profile` ([server.py:635-656](server.py)) körs på **både** `/api/auth/me` och `/api/dashboard/summary`, alltså på varje sidladdning. Den läser hela profilhistoriken och skriver tillbaka en om-krypterad `users`-rad så fort något värde ändrats – en skrivning på vad som borde vara en ren läsväg.
- **Åtgärd:**
  1. Låt `GarminDatabase` kunna hålla **en** anslutning öppen över flera anrop, t.ex. via en context manager:
     ```python
     with db.connection():          # tar en anslutning ur poolen
         daily = db.get_daily_summary_history(days)
         sleep = db.get_sleep_history(days)
         ...
     ```
     Gettarna använder den befintliga anslutningen när en sådan är bunden, annars dagens beteende. Det tar dashboarden från ~10 anslutningar till 1.
  2. Höj `MARIADB_MAX_CONNECTIONS` i drift och dokumentera relationen till MariaDB:s `max_connections`.
  3. Sätt en gräns för hur länge `blocking=True` väntar (`maxusage`/timeout) så att utmattning ger ett tydligt 503 i stället för en hängning.
  4. Låt bakgrundssynken **inte** hålla en anslutning under hela jobbet – hämta och släpp per skrivbatch i `_run_datasource_sync`.
  5. Gör `auto_sync_user_profile` billigare: kör den inte på varje `/api/dashboard/summary`, utan på `/api/auth/me` och efter en genomförd datakällesynk. Alternativt lägg en kort TTL per användare.
- **Acceptanskriterier:**
  1. Ett anrop till `/api/dashboard/summary` tar högst 2 poolanslutningar (mätt med en räknare runt `get_mariadb_conn`).
  2. Test: en pågående bakgrundssynk hindrar inte dashboarden från att svara.
  3. Poolutmattning ger 503 med begripligt meddelande, inte en hängning.
  4. `auto_sync_user_profile` skriver inte till `users` vid två identiska dashboardanrop i följd.

---

### [ ] S-23: Registrering avslöjar vilka e-postadresser som har konto, och saknar IP-baserad rate limiting
- **Fil:** [auth.py:153-157](auth.py) (dubblettkontrollen i `register_user`), [auth.py:43](auth.py) och [auth.py:98-120](auth.py) (rate limiting), [server.py:515-560](server.py) (`register`), [server.py:562-600](server.py) (`login`), [server.py:679-698](server.py) (`recover_account`)
- **Problem:** Två separata svagheter i samma yta.

  **1. Användaruppräkning.** `Q-8` gjorde helt rätt i att byta ut HTTP 500 mot 400 – men meddelandet är specifikt:
  ```python
  raise ValueError("E-postadressen är redan registrerad.")     # auth.py:157
  ```
  Det gör `/api/auth/register` till ett orakel: den som vill veta om `person@exempel.se` har ett HealthChat-konto behöver bara posta adressen. För en hälsoapplikation är själva *medlemskapet* en uppgift värd att skydda – att någon använder en tränings- och hälsotjänst är i sig personlig information.

  Inloggningen gör däremot rätt: `"Fel e-postadress eller lösenord."` oavsett om användaren finns ([auth.py:217](auth.py), [auth.py:232](auth.py)), med `time.sleep(0.3)` för att jämna ut tidsskillnaden. Samma omsorg saknas i registreringen.

  **2. Rate limiting bara per e-post, bara på inloggning.** `check_rate_limit` ([auth.py:98](auth.py)) nycklar enbart på e-postadress, och anropas enbart från `authenticate_user`. Det betyder att:
  - `/api/auth/register` har **ingen** begränsning alls – uppräkningsangreppet ovan kan köras i full hastighet.
  - `/api/auth/recover` ([server.py:679](server.py)) har **ingen** begränsning – återställningsnyckeln kan gissas utan broms. 200 bitars entropi gör det praktiskt omöjligt, men avsaknaden av broms är ändå fel.
  - Ett lösenordsspray-angrepp (ett vanligt lösenord mot många konton) träffar aldrig taket, eftersom taket är fem försök **per e-post**.
  - Räknaren är per process och nollställs vid omstart.
- **Åtgärd:**
  1. Gör registreringssvaret generiskt. Antingen samma svar oavsett om adressen finns ("Om adressen kan registreras har ett konto skapats"), eller – enklare och ärligare för en självhostad app – behåll det tydliga felet men skydda det med rate limiting enligt punkt 2 och dokumentera avvägningen här i tavlan.
  2. Inför IP-baserad rate limiting på `/api/auth/*`. `slowapi` integrerar direkt med FastAPI:
     ```python
     from slowapi import Limiter
     limiter = Limiter(key_func=get_remote_address)

     @app.post("/api/auth/register")
     @limiter.limit("5/minute")
     def register(...):
     ```
     Kom ihåg `--proxy-headers` och `--forwarded-allow-ips` i [healthchat_web.service](healthchat_web.service) när `TLS-1` är på plats, annars ser alla requests ut att komma från proxyn.
  3. Lägg på rate limiting även på `/api/auth/recover`.
  4. Behåll den e-postbaserade räknaren som komplement – den skyddar ett enskilt konto, IP-räknaren skyddar mot bredd.
  5. Överväg att flytta räknarna till databasen eller Redis så att de överlever omstart.
- **Acceptanskriterier:**
  1. Test: 10 snabba registreringsförsök från samma IP ger 429 på de sista.
  2. Test: `/api/auth/recover` är begränsad på samma sätt.
  3. Beslutet om uppräkningsskydd (generiskt svar eller enbart rate limiting) är dokumenterat här med motivering.
  4. Rate limiting läser klientens IP korrekt bakom reverse proxy.

---

## 🟡 P2 – Kodkvalitet & underhåll

### [x] B-6: Operator-precedens sväljer Withings riktiga felmeddelande (åtgärdad med explicit parenteser)
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

### [x] B-7: OAuth-tokens roteras bort och lagras i klartext på disk (åtgärdad med secret_store, 0o600 och refresh-validering)
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

### [x] S-16: Keyring-posten överlever kontoradering (åtgärdad: email slås upp och keyring rensas)
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

### [x] Q-1: `/api/user/profile/fetch_external` hämtar inget externt (åtgärdad med /api/user/profile/refresh & databasaggregering)
- **Fil:** [server.py:692-701](server.py), [profile_sync.py:14-20](profile_sync.py), [static/app.js:1232](static/app.js)
- **Problem:** `fetch_external_profile_metrics` anropas alltid som `fetch_external_profile_metrics(db=db)` – parametrarna `garmin_handler`, `fitbit_handler`, `strava_handler` och `withings_handler` skickas **aldrig** in från någon plats i repot (`grep` bekräftar att ingen av handlarna instansieras i webbvägen). Hela Garmin/Fitbit/Strava/Withings-logiken i [profile_sync.py:77-192](profile_sync.py) är död kod, och endpointen läser i praktiken bara den lokala databasen – trots att namnet, docstringen och knappen i UI:t lovar något annat. `sources`-listan i svaret innehåller bara `"Databas"`.
- **Åtgärd:** Välj en linje och genomför den fullt ut:
  - **A:** Koppla in handlarna på riktigt – instansiera dem per användare från `secret_store` (kräver `S-14` punkt 4) och skicka in dem.
  - **B:** Ta bort den döda koden ur `profile_sync.py`, döp om endpointen till `/api/user/profile/refresh` och uppdatera knapptexten i UI:t så att den beskriver vad som faktiskt händer.
- **Acceptanskriterier:** Endpointens namn, docstring, UI-text och faktiska beteende är samstämmiga; ingen död parametergren kvar.

---

### [x] Q-2: Webbchatten har inget konversationsminne och saknar hälsokontext (åtgärdad: chatthistorik per session & garmin_context)
- **Fil:** [server.py:590-631](server.py)
- **Problem:** `AIClient` skapas på nytt i varje request ([server.py:607](server.py)), så `conversation_history` är alltid tom – hela det glidande fönstret från `P1-1` är verkningslöst i webbläget och AI:n minns ingenting mellan frågor. Dessutom anropas `client.chat(prompt)` utan `garmin_context`-argumentet; kontexten klistras i stället in i `prompt` ([server.py:601](server.py)), vilket betyder att den **sparas i historiken** – precis det `P1-1` löste. Kontexten som byggs är dessutom mycket tunnare än desktopversionens: tre rader med antal aktiviteter och senaste sömn ([server.py:594-599](server.py)).
- **Åtgärd:**
  1. Persistera konversationshistoriken per session (i `_active_sessions` eller en tabell) och mata in den i `AIClient` mellan requests.
  2. Skicka hälsodata via `garmin_context`-parametern, inte via `user_message`.
  3. Bygg en rikare kontext – återanvänd formateringslogiken från desktopversionen (finns i `temp/`) i stället för de tre raderna.
- **Acceptanskriterier:** En följdfråga ("och förra veckan då?") besvaras med kontext från föregående fråga.

---

### [x] Q-3: `self.model.lower()` kraschar för Azure utan explicit modell (åtgärdad med modellvalidering och (self.model or '').lower())
- **Fil:** [ai_client.py:457](ai_client.py), [ai_client.py:91-95](ai_client.py)
- **Problem:** `PROVIDERS['azure']['default_model']` är `None` ([ai_client.py:38](ai_client.py)). Skapas klienten utan `model` blir `self.model = None`, och `'qwen' in self.model.lower()` kastar `AttributeError`. Felet fångas visserligen av det breda `except` i `chat()` ([ai_client.py:307](ai_client.py)) men presenteras då som ett AI-fel i stället för ett konfigurationsfel.
- **Åtgärd:** Validera i `__init__` att `self.model` är satt (kasta `ValueError` med tydlig text för Azure), och använd `(self.model or '').lower()` som skydd.
- **Acceptanskriterier:** `AIClient(provider='azure', azure_endpoint=...)` utan modell ger ett begripligt `ValueError` vid konstruktion.

---

### [x] Q-4: `self.azure_deployment` sätts men används aldrig (åtgärdad: azure_deployment kopplad till model)
- **Fil:** [ai_client.py:125-141](ai_client.py) (`_init_azure`), [ai_client.py:442](ai_client.py)
- **Problem:** `_init_azure` sparar `self.azure_deployment = azure_deployment` ([ai_client.py:133](ai_client.py)), men `_call_openai_compatible` skickar `model=self.model`. För Azure är deployment-namnet det som ska skickas. I dag råkar det fungera eftersom `azure_deployment` defaultar till `self.model`, men skickar anroparen ett avvikande deployment-namn ignoreras det tyst.
- **Åtgärd:** Använd `getattr(self, 'azure_deployment', None) or self.model` i `_call_openai_compatible`, eller ta bort attributet helt.
- **Acceptanskriterier:** Test som verifierar att ett explicit `azure_deployment` hamnar i `model`-parametern.

---

### [x] Q-5: `re.sub(r' +', ' ', content)` plattar ut AI-svarens formatering (åtgärdad: _clean_response bevarar kodblock & indentering)
- **Fil:** [ai_client.py:460-461](ai_client.py)
- **Problem:** Efterbehandlingen kollapsar **all** upprepad blanksteg i svaret – inte bara dubbla mellanslag i löptext, utan också indentering i kodblock, punktlistor och tabeller. Systemprompten ber uttryckligen om strukturerade svar med rubriker och listor ([ai_client.py:265-274](ai_client.py)), vilket den här raden delvis förstör.
- **Åtgärd:** Begränsa normaliseringen till rader som inte är kod/listor, eller ta bort den. Behåll `re.sub(r'=\s*\\?"\$[\d.]+\\?"', ...)` om den löser ett känt problem – men dokumentera vilket.
- **Acceptanskriterier:** Ett AI-svar med ett indenterat kodblock behåller sin indentering.

---

### [x] Q-6: Misslyckat AI-anrop lämnar historiken i ogiltigt tillstånd (åtgärdad: rollback av användarmeddelande vid fel)
- **Fil:** [ai_client.py:274-310](ai_client.py)
- **Problem:** Användarmeddelandet läggs till i `conversation_history` ([ai_client.py:274-277](ai_client.py)) **innan** anropet görs. Kastar anropet returneras ett felmeddelande utan att något assistentsvar läggs till ([ai_client.py:307](ai_client.py) och framåt) – historiken innehåller då två `user`-meddelanden i rad. Anthropics API kräver alternerande roller och avvisar det i nästa tur, så ett övergående fel blir permanent tills `reset_conversation()` körs.
- **Åtgärd:** Ta bort det senaste användarmeddelandet ur historiken i felgrenen, alternativt lägg till felmeddelandet som assistentsvar.
- **Acceptanskriterier:** Test: ett misslyckat anrop följt av ett lyckat ger en historik med alternerande roller.

---

### [x] Q-7: Ollama-felmeddelandet visar fel adress (åtgärdad: self.ollama_base_url sparas och visas)
- **Fil:** [ai_client.py:331-338](ai_client.py)
- **Problem:** Felmeddelandet vid anslutningsfel skriver `self.PROVIDERS['ollama']['base_url']` – den **hårdkodade** `http://localhost:11434/v1` – i stället för den URL klienten faktiskt konfigurerats med via `normalize_ollama_url` ([ai_client.py:213-222](ai_client.py)). En användare med Ollama på `192.168.1.50` får felsökningsråd för fel maskin.
- **Åtgärd:** Spara den normaliserade URL:en på instansen (`self.ollama_base_url`) i `_init_ollama` och använd den i felmeddelandet.
- **Acceptanskriterier:** Felmeddelandet innehåller den konfigurerade adressen.

---

### [x] Q-8: Dubblett-e-post ger HTTP 500 i stället för 400 (åtgärdad: kontroll och ValueError med 400-svar)
- **Fil:** [auth.py:160-178](auth.py) (`register_user`), [server.py:329-333](server.py)
- **Problem:** `users.email` har `UNIQUE`-constraint ([init_mariadb.sql:10](init_mariadb.sql)), men `register_user` kontrollerar inte om adressen redan finns. `IntegrityError` är inget `ValueError`, så den fångas av det breda `except Exception` ([server.py:332](server.py)) och blir ett 500-svar med rå databastext i `detail` – både ett dåligt användarmeddelande och ett litet informationsläckage.
- **Åtgärd:**
  1. Slå upp adressen först och kasta `ValueError("E-postadressen är redan registrerad.")`, alternativt fånga `pymysql.err.IntegrityError` och översätt.
  2. Sluta skicka `str(e)` till klienten i 500-grenen – logga det och returnera en generisk text.
- **Acceptanskriterier:** Registrering med befintlig e-post ger 400 med ett begripligt svenskt meddelande, utan databasdetaljer.

---

### [x] Q-9: Diverse mindre fynd (samtliga delpunkter åtgärdade eller motiverade)
- **Fil:** flera
- **Problem & åtgärd:**
  1. **Återställningsnyckeln är 200 bitar, inte 256.** [crypto.py:92-104](crypto.py) – funktionen heter `generate_recovery_key`, docstringen säger 256 bitar, men `b32[:40]` kapar till 40 Base32-tecken = 200 bitar. Fortfarande säkert, men dokumentationen stämmer inte. **Åtgärd:** ✅ docstring rättad till 200 bitar (40 Base32-tecken).
  2. **Mojibake i loggsträngar.** [garmin_handler.py](garmin_handler.py) innehåller 6 strängar med `âœ…`/`ðŸ` – UTF-8 som avkodats som latin-1. **Åtgärd:** ✅ ersatt med korrekta emojis (`✅`, `❌`).
  3. **`get_db_conn` returnerar aldrig `None`.** [server.py:118-123](server.py) – ändå testar anroparna `if conn:` ([server.py:679](server.py), [server.py:713](server.py), [server.py:741](server.py)) och har else-grenar som är död kod. **Åtgärd:** ✅ `get_db_conn` fångar anslutningsfel och returnerar `None` säkert; `if conn:` fyller nu sin funktion vid fel/mockning.
  4. **Aliasing av DEK vid samtidig utloggning.** [server.py:386](server.py) – `session.clear()` nollar den `bytearray` som `bind_user_db` redan delat ut till en pågående request i en annan tråd. Osannolikt men reellt. **Åtgärd:** ✅ `bind_user_db` kopierar DEK:en (`bytearray(session.dek)`) så att referenser inte delas.
  5. **`delete_account` kräver inget lösenord.** [server.py:736-751](server.py) – till skillnad från `change_password` och `rotate_recovery_key`. **Åtgärd:** ✅ `auth.delete_user_account` och `/api/user/delete_account` kräver och verifierar `current_password`.
  6. **Rate-limiting är process-lokal.** [auth.py:98-122](auth.py) – med flera Uvicorn-workers multipliceras gränsen med antalet workers. **Åtgärd:** I enlighet med S-13 kör HealthChat med 1 Uvicorn-worker (`--workers 1`), vilket gör process-lokal rate limiting fulltäckande per nod.
  7. **Två testmoduler refererar till `temp/`.** [tests/test_withings_handler.py:108-112](tests/test_withings_handler.py) importerar `HealthChatDesktop` och [tests/test_charts_view_tabs.py:4-9](tests/test_charts_view_tabs.py) importerar `charts_view` + `tkinter` – båda modulerna flyttades till den gitignorerade `temp/` i `33ae88d`. **Åtgärd:** ✅ markerade med `pytest.importorskip` så hela testsviten kör och passerar på rena kloner utan `--ignore`.
- **Acceptanskriterier:** Varje delpunkt åtgärdad eller uttryckligen avfärdad med motivering i denna fil.

---

### [x] Q-10: `.agents/rules/compile.md` refererar till filer som inte längre finns (uppdaterad till webb-arbetsflöde)
- **Fil:** [.agents/rules/compile.md](.agents/rules/compile.md)
- **Problem:** Regeln kräver `pyinstaller --noconfirm HealthChatDesktop_optimized.spec` och `sign_executable.ps1` efter varje kodändring. Båda filerna flyttades till `temp/` i commit `33ae88d` och `temp/` är gitignorerad – stegen går alltså inte att utföra i repot längre. En agent som följer regeln bokstavligt fastnar.
- **Åtgärd:** Uppdatera regeln till webbapplikationens verklighet: kör `pytest`, verifiera att `uvicorn server:app` startar, och beskriv desktop-bygget som valfritt/historiskt.
- **Se även:** [.agents/rules/github.md](.agents/rules/github.md) säger `git push origin main`. Arbetar agenten i stället på en feature-gren med pull request blir de två reglerna motstridiga. Bestäm vilket som gäller och skriv det i en av filerna, så att nästa agent inte behöver gissa.
- **Acceptanskriterier:** Regeln går att följa från en ren klon av repot, och det finns exakt ett svar på frågan vart arbetet ska pushas.

---

### [ ] Q-14: README beskriver en Windows-desktopapp som inte längre är projektet
- **Fil:** [README.md](README.md) (hela filen), att jämföra med [server.py:45-49](server.py) (`FastAPI(title=..., version="4.1.0")`) och [healthchat_web.service](healthchat_web.service)
- **Problem:** README:s rubrik är `# HealthChat Desktop v4.0.4` och texten beskriver genomgående **"a Windows application"**: installation via `HealthChatSetup.exe`, bygge med `pyinstaller HealthChatDesktop.spec`, installer med `iscc installer_script.iss`, systemkrav "OS: Windows 10 eller Windows 11". Verkligheten är en FastAPI-webbapplikation som körs som en systemd-tjänst mot MariaDB, och `.agents/rules/compile.md` slår redan fast att desktopbygget är arkiverat och att "det primära målet är nu webbapplikationen".

  Konkreta felaktigheter utöver inriktningen:
  1. **Versionen.** README säger v4.0.4, `server.py` säger 4.1.0.
  2. **AI-leverantörerna.** README listar sex valbara leverantörer med en jämförelsetabell och API-nyckelinstruktioner för fyra av dem. Webbchatten är **hårdkodad till Ollama** – `chat_stream` konstruerar alltid `AIClient(provider="ollama", ...)` ([server.py:901-906](server.py)) och ignorerar allt utom `req.model`. `ai_client.py` stödjer fortfarande de andra, men de går inte att nå från webbgränssnittet.
  3. **Trasig länk.** README hänvisar på fyra ställen till `OLLAMA_SETUP_GUIDE.md`. Filen finns inte i repot.
  4. **Platshållare kvar.** `## License` säger `[Your chosen license]` och `## Support` säger `[Your contact email]`.
  5. **Licensoklarhet.** [LICENSE.txt](LICENSE.txt) är `MIT License, Copyright (c) 2025 Rod Trent` – en annan upphovsperson än repots ägare, rimligen ursprunget till en fork. README säger samtidigt att licensen inte är vald. Det bör redas ut och skrivas rätt: behålls MIT-licensen ska ursprunglig upphovsrättsnotis stå kvar, och eventuella egna tillägg anges separat.
  6. **Installationsinstruktionerna** nämner varken MariaDB, `init_mariadb.sql`, `/etc/healthchat/db.env` eller `healthchat_web.service` – allt det som faktiskt krävs för att köra applikationen.

  Säkerhetsavsnittet är däremot uppdaterat och korrekt (S-13-beskrivningen stämmer) – det visar att filen underhålls punktvis men inte som helhet. Se även `S-19`, som gör en del av det avsnittet osant i praktiken.
- **Åtgärd:**
  1. Skriv om README med webbapplikationen som utgångspunkt: vad den är, arkitekturöversikt (FastAPI + MariaDB + Ollama + fyra datakällor), och en installationssektion som speglar den faktiska driftsättningen.
  2. Ersätt desktop-specifika avsnitt (PyInstaller, Inno Setup, Windows-systemkrav) med en kort not om att desktopklienten är arkiverad, och hänvisa till `.agents/rules/compile.md`.
  3. Rätta versionsnumret och gör det till **en** källa – läs gärna `app.version` från `server.py` i stället för att underhålla två.
  4. Beskriv AI-stödet sanningsenligt: Ollama är det som webbappen använder; `ai_client.py` har kvar stöd för fler leverantörer men de är inte exponerade i webb-UI:t. Ta bort kostnadsjämförelsetabellen eller flytta den till ett historiskt appendix.
  5. Skriv `OLLAMA_SETUP_GUIDE.md` eller ta bort länkarna till den.
  6. Fyll i `## License` (med korrekt hänvisning till `LICENSE.txt` och Rod Trents upphovsrätt) och `## Support`, eller ta bort avsnitten.
  7. Lägg till ett kort avsnitt om vad som lagras var: MariaDB (krypterat), processminne (DEK), webbläsaren (efter `S-19`).
- **Acceptanskriterier:**
  1. README beskriver webbapplikationen, inte en Windows-app.
  2. Ingen länk i README pekar på en fil som saknas.
  3. Inga `[Your ...]`-platshållare kvar.
  4. Licensfrågan är besvarad i README och konsekvent med `LICENSE.txt`.
  5. En ny användare kan följa README och få applikationen att starta mot MariaDB.

---

### [ ] Q-15: `xai_client.py` är död kod
- **Fil:** [xai_client.py](xai_client.py) (159 rader)
- **Problem:** Ingenting i kodbasen importerar modulen – `grep -rn "xai_client" --include="*.py" .` ger noll träffar, inklusive i `tests/`. Den är en kvarleva från tiden före `ai_client.AIClient`, som numera hanterar xAI via den OpenAI-kompatibla vägen (`_init_xai`, [ai_client.py:117-123](ai_client.py)).

  Kostnaden är inte prestanda utan förvirring: en utvecklare eller agent som söker efter xAI-hantering hittar två implementationer och måste lista ut vilken som gäller. Den saknar dessutom testtäckning helt, så om någon *skulle* börja använda den är den oprövad. Samma sak gäller potentiellt [migrate_sqlite_to_mariadb.py](migrate_sqlite_to_mariadb.py), som bara refereras från `board.md` – men den är ett avsiktligt engångsverktyg och bör behållas, eventuellt flyttad till en `scripts/`-katalog.
- **Åtgärd:**
  1. Ta bort [xai_client.py](xai_client.py).
  2. Kontrollera först att inget desktop-arkiv eller externt skript importerar den (`grep -rn "xai_client" .` över hela repot, inte bara `*.py`).
  3. Flytta `migrate_sqlite_to_mariadb.py` till `scripts/` och notera i dess docstring att den är ett engångsverktyg, så att den inte förväxlas med applikationskod.
  4. Passa på att köra `ruff check --select F401` för att hitta oanvända importer i övriga moduler (t.ex. `import garth` i `garmin_handler.py` efter att `S-24` är åtgärdad).
- **Acceptanskriterier:**
  1. `xai_client.py` finns inte kvar.
  2. `pytest -q` och `python -c "import server"` är oförändrat gröna.
  3. Inga oanvända toppnivåimporter kvar enligt `ruff --select F401`.

---

### [ ] Q-16: Tre nästan identiska OAuth-hanterare – samma fix måste göras på tre ställen
- **Fil:** [strava_handler.py](strava_handler.py) (630 rader), [fitbit_handler.py](fitbit_handler.py) (422 rader), [withings_handler.py](withings_handler.py) (431 rader)
- **Problem:** De tre OAuth-hanterarna implementerar var för sig samma metoduppsättning med i huvudsak samma logik:

  | Metod | Strava | Fitbit | Withings |
  |---|---|---|---|
  | `load_stored_tokens` | :51 | :53 | – |
  | `save_tokens` | :97 | :99 | – |
  | `get_auth_url` | :141 | :140 | :49 |
  | `verify_state` | :156 | :163 | :61 |
  | `exchange_code_for_token` | :162 | :169 | :67 |
  | `refresh_access_token` | :204 | :206 | :118 |
  | `_get_headers` | :229 | :235 | – |

  Skillnaderna är i praktiken bara auktoriserings-URL, token-URL, scope-strängar, PKCE (bara Fitbit) och svarsformatet vid tokenutbyte. Resten – state-generering, jämförelse, tokenlagring, utgångskontroll, `Authorization: Bearer`-header – är kopior.

  Det är inte ett estetiskt problem utan ett underhållsproblem med säkerhetskonsekvenser. `B-7` handlade om att OAuth-tokens roterades bort och lagrades i klartext på disk. En sådan fix måste appliceras identiskt på tre ställen, och nästa gång är det lätt att en av dem missas. Samma sak gäller `compare_oauth_state` ([server.py:1356-1358](server.py)), som är konstanttidsjämförelse på serversidan – medan handlarnas egna `verify_state` är tre separata implementationer som behöver granskas var för sig.
- **Åtgärd:**
  1. Inför en `OAuth2Handler`-basklass, förslagsvis i en ny `oauth_base.py`, med:
     - `AUTH_URL`, `TOKEN_URL`, `SCOPES`, `USES_PKCE` som klassattribut,
     - generisk `get_auth_url`, `verify_state` (via `secrets.compare_digest`), `exchange_code_for_token`, `refresh_access_token`, `_get_headers`, `load_stored_tokens`, `save_tokens`,
     - abstrakta krokar för det som verkligen skiljer: `_parse_token_response(resp_json) -> dict` och `_provider_headers()`.
  2. Låt de tre handlarna ärva och bara definiera sina konstanter, sin tokenparsning och sina data-hämtande metoder (`fetch_activities`, `fetch_measurements`, `sync_*`), som är genuint provider-specifika.
  3. Skriv testerna mot basklassen en gång, och behåll per-provider-tester enbart för parsningen och synklogiken.
  4. Gör det **efter** `Q-11`/`Q-13`, så att CI fångar eventuella regressioner i refaktoreringen. Befintliga tester i [tests/test_datasources.py](tests/test_datasources.py) (22 kB) är ett bra skyddsnät.
- **Acceptanskriterier:**
  1. State-verifiering, tokenlagring och tokenförnyelse finns på **ett** ställe.
  2. Samtliga befintliga tester i `test_datasources.py`, `test_strava_handler.py`, `test_withings_handler.py`, `test_oauth_state_pkce.py` passerar oförändrade.
  3. Ett nytt OAuth-provider kan läggas till genom att ärva basklassen och sätta fyra konstanter.
  4. Radantalet i de tre handlarna minskar mätbart utan att någon funktionalitet försvinner.

---

### [ ] Q-17: Filstorlekarna har passerat gränsen för vad som går att överblicka
- **Fil:** [server.py](server.py) (1 956 rader), [garmin_handler.py](garmin_handler.py) (1 805), [static/app.js](static/app.js) (2 607), [garmin_db.py](garmin_db.py) (1 218) – samtliga i repots rot
- **Problem:** All applikationskod ligger platt i rotkatalogen utan paketstruktur, och fyra filer har passerat 1 200 rader. `server.py` innehåller CORS-konfiguration, säkerhetsheaders, sessionshantering, Pydantic-scheman, autentisering, dashboard, AI-chatt, väder, profil, fyra datakällor med OAuth-callbacks och bakgrundssynk, samt statisk filservering.

  Praktiska konsekvenser som redan syns i kodbasen:
  - `import secret_store` förekommer två gånger ([server.py:36](server.py) och [server.py:827](server.py)) – ett symptom på att filen är för lång för att överblickas.
  - Den här tavlans varning "radnumren är ögonblicksbilder, sök på citatet" är nödvändig just för att filerna är så stora att allt förskjuts vid varje ändring.
  - Sammanflätningen gör det svårt att testa en del isolerat, vilket bidrar till `Q-11`.
  - I `static/app.js` ligger rendering, API-anrop, diagram, chatt, datakällor och autentisering i samma globala scope med delade `let`-variabler på toppnivå ([static/app.js:7-9](static/app.js)).
- **Åtgärd:**
  1. Dela `server.py` i `APIRouter`-moduler under `routers/`:
     - `routers/auth.py` – register, login, logout, me, recover, lösenord, kontoradering
     - `routers/dashboard.py` – dashboard summary, väder
     - `routers/ai.py` – chat, history, clear, preload
     - `routers/profile.py` – profil, extern profilhämtning
     - `routers/datasources.py` – hela datakälleblocket
     Kvar i `server.py`: app-konstruktion, middleware, startup, felhanterare, `include_router`-anrop.
  2. Flytta delade beroenden (`get_db`, `bind_user_db`, `get_current_session`, `_db_cursor`) till `dependencies.py`, och sessionslagret (`_active_sessions` m.fl.) till `session_store.py`. Det gör `Q-11` och `S-20` enklare att genomföra korrekt.
  3. Lägg domänmodulerna under ett `healthchat/`-paket så att importerna blir entydiga. `pytest.ini`:s `pythonpath = .` kan behöva justeras.
  4. Dela `static/app.js` i ES-moduler utan byggsteg: `<script type="module" src="/static/main.js">` som importerar `api.js`, `auth.js`, `dashboard.js`, `charts.js`, `chat.js`, `datasources.js`. Det tvingar också bort de globala `let`-variablerna.
  5. Gör det stegvis, en router per commit, med `pytest` mellan varje. Refaktorera **inte** logiken samtidigt – flytta först, ändra sedan.
  6. Ta bort dubbletten `import secret_store` på [server.py:827](server.py) direkt, oberoende av resten.
- **Acceptanskriterier:**
  1. Ingen Python-fil i applikationskoden överstiger ~600 rader.
  2. `python -c "import server"` och `pytest -q` är gröna efter varje delsteg.
  3. Samtliga API-vägar svarar identiskt före och efter (jämför `app.routes` före/efter).
  4. `static/app.js` är uppdelad och ingen funktion är beroende av implicita globala variabler.

---

### [ ] Q-18: Beroenden är inte pinnade – `TLS-6`:s acceptanskriterium är inte uppfyllt
- **Fil:** [requirements.txt](requirements.txt), [requirements-desktop.txt](requirements-desktop.txt)
- **Problem:** `TLS-6` markerades som klar med motiveringen "requirements.txt uppdaterad med alla webbberoenden" och åtgärdspunkten löd "Lägg till `fastapi`, `uvicorn[standard]`, `pydantic` och `email-validator` **med pinnade versioner**". Beroendena finns numera – men inget är pinnat:
  ```
  fastapi>=0.115.0
  uvicorn[standard]>=0.32.0
  cryptography>=43.0.0
  openai>=1.50.0
  garth>=0.4.40
  ```
  `>=` betyder att `pip install -r requirements.txt` i dag och om tre månader ger olika applikationer. För ett projekt vars säkerhetsmodell vilar på `cryptography` och `argon2-cffi` är det en reproducerbarhetsbrist som spelar roll: det går inte att i efterhand säga vilken kryptoimplementation en given driftsättning faktiskt körde.

  Två närliggande observationer från samma fil:
  1. **`garth` är avvecklad.** Importen ger numera `DeprecationWarning: Garth is deprecated and no longer maintained. See https://github.com/matin/garth/discussions/222`. `garminconnect` bär huvudansvaret för inloggningen i dag, och `garth` används bara i en fallback (se `S-24`). En avvecklad transitiv beroendekedja mot en tjänst som aktivt ändrar sitt inloggningsflöde är en driftrisk värd att planera för.
  2. **Testberoenden ligger i produktionsfilen.** `pytest`, `pytest-asyncio` och `httpx` installeras på webbservern utan att behövas där.
- **Åtgärd:**
  1. Inför `pip-tools`: skriv de direkta beroendena i `requirements.in` och generera `requirements.txt` med `pip-compile --generate-hashes`. Då blir varje version exakt och varje artefakt hashverifierad.
  2. Dela ut testberoendena i `requirements-dev.txt` (eller `requirements-dev.in`), och låt CI (`Q-13`) installera båda medan driftsättningen bara installerar produktionsfilen.
  3. Lägg till Dependabot eller `pip-compile --upgrade` som schemalagt jobb, så att pinningen inte blir en ursäkt för att aldrig uppdatera.
  4. Öppna en separat uppgift för att utvärdera `garth`-beroendet: går det att ta bort helt när `S-24` är åtgärdad, eller behövs det transitivt via `garminconnect`?
  5. Uppdatera `TLS-6`:s status i den här filen – dess punkt 1 är inte genomförd.
- **Acceptanskriterier:**
  1. `requirements.txt` innehåller exakta versioner (`==`) med hashar.
  2. `pytest` och `httpx` finns inte i produktionsberoendena.
  3. En ren `pip install -r requirements.txt` ger samma versioner två gånger i rad, verifierat med `pip freeze`.
  4. Det är dokumenterat hur beroendena uppdateras.

---

### [ ] Q-19: Ingen schemamigrering – DDL körs ad hoc vid varje request
- **Fil:** [init_mariadb.sql](init_mariadb.sql), [server.py:341-371](server.py) (`init_sessions_table`), [datasource_store.py:190-240](datasource_store.py) (`ensure_table`), anropen på [server.py:1396](server.py) och [server.py:1759](server.py), [garmin_db.py:317-452](garmin_db.py) (`init_sqlite_db`)
- **Problem:** Databasschemat definieras på tre olika sätt samtidigt:
  1. `init_mariadb.sql` – körs manuellt en gång vid installation.
  2. `init_sessions_table(conn)` – `CREATE TABLE IF NOT EXISTS user_sessions ...` som anropas från `save_session_to_db` ([server.py:381](server.py)), alltså **vid varje inloggning**.
  3. `datasource_store.ensure_table(conn)` – anropas från `datasource_session` ([server.py:1396](server.py)), alltså vid **varje** datakälle-request, och från bakgrundssynken ([server.py:1759](server.py)).

  Mönstret fungerar så länge schemat bara växer med nya tabeller. Det fungerar **inte** den dag en kolumn ska läggas till, byta typ eller få ett index: `CREATE TABLE IF NOT EXISTS` är en no-op mot en befintlig tabell, så ändringen slår aldrig igenom på en installation som redan kört. Det finns ingen `schema_version`, ingen migrationshistorik och inget sätt att veta vilket schema en given databas faktiskt har.

  `S-13` visade problemet i praktiken: `user_sessions` behövde tappa en kolumn (`dek`) och få en ny (`expires_at`). Med dagens upplägg måste det göras manuellt på varje installation, utan spårbarhet.

  Därtill är det onödigt arbete i den varma vägen – en DDL-sats per request mot MariaDB, vilket också bidrar till `PF-10`.
- **Åtgärd:**
  1. Inför Alembic (eller en minimal egen migrationslösning med en `schema_version`-tabell och numrerade SQL-filer i `migrations/`).
  2. Flytta all DDL till migrationer. Låt `init_mariadb.sql` bli migration `0001`.
  3. Kör migreringarna **vid uppstart** i `startup_db_check` ([server.py:292](server.py)) – eller, säkrare i drift, som ett explicit kommando (`python -m healthchat.migrate`) som körs före tjänststart. Dokumentera valet.
  4. Ta bort `init_sessions_table` och `ensure_table` ur request-vägarna när migreringarna är på plats.
  5. Behåll SQLite-DDL:en i `init_sqlite_db` för testerna – den är engångscachad sedan `PF-7` och är inte problemet.
- **Acceptanskriterier:**
  1. Ingen `CREATE TABLE`-sats körs under ett vanligt API-anrop.
  2. En kolumnändring kan levereras som en migration och appliceras på en befintlig databas.
  3. `SELECT * FROM schema_version` visar vilka migreringar som körts.
  4. Installationsinstruktionerna i README beskriver migreringssteget.

---

### [ ] S-24: `garth.client` som global fallback kan i teorin returnera fel användares profil
- **Fil:** [garmin_handler.py:380-402](garmin_handler.py) (`_resolve_display_name`), särskilt [garmin_handler.py:391-392](garmin_handler.py), [garmin_handler.py:5](garmin_handler.py) (importen)
- **Problem:** `_resolve_display_name` har en fallback till modulglobalen `garth.client`:
  ```python
  if hasattr(self, 'client') and self.client and hasattr(self.client, 'connectapi'):
      profile = self.client.connectapi('/userprofile-service/socialProfile')
  elif hasattr(garth, 'client') and hasattr(garth.client, 'connectapi'):
      profile = garth.client.connectapi('/userprofile-service/socialProfile')     # garmin_handler.py:392
  ```
  `garth` håller sin autentiserade klient i **modulstate** – det är exakt den egenskap som [datasource_store.py](datasource_store.py) redan varnar för i sin kommentar kring `GARMIN_AUTH_LOCK`: *"garth keeps its authenticated client in module state, so every Garmin login is serialized through this lock. Data fetching afterwards still goes through that shared client, which is why the web layer runs with a single worker process."*

  I en fleranvändarwebb betyder det att `garth.client` pekar på **den senaste användare som loggade in**. Faller koden ner i `elif`-grenen medan en annan användares synk pågår, hämtas fel persons `displayName` – och det värdet används sedan för att bygga API-anrop åt den första användaren (`_ensure_display_name` sätter `self.client.display_name`, [garmin_handler.py:404-409](garmin_handler.py)).

  Vägen är osannolik: den kräver att `self.client` saknas eller saknar `connectapi`, vilket inte borde inträffa efter en lyckad autentisering. Men konsekvensen om den ändå inträffar är kors-användarläckage av Garmin-data, och `GARMIN_AUTH_LOCK` skyddar bara **inloggningen**, inte efterföljande hämtningar. Kostnaden för att ta bort grenen är noll.

  Samma modulglobal är också skälet till att `--workers 1` är hårt krav i [healthchat_web.service](healthchat_web.service) – tillsammans med `S-13`. Det bör stå uttryckligen i README:s driftavsnitt.
- **Åtgärd:**
  1. Ta bort `elif`-grenen. Saknas `self.client.connectapi` är rätt beteende att logga och falla tillbaka på e-postprefixet (det gör redan `except`-grenen på [garmin_handler.py:400-402](garmin_handler.py)), inte att fråga en delad global.
  2. Ta bort `import garth` på [garmin_handler.py:5](garmin_handler.py) om inget annat använder den. `from garth.exc import GarthHTTPError` ([garmin_handler.py:6](garmin_handler.py)) behövs sannolikt kvar – kontrollera.
  3. Dokumentera i [healthchat_web.service](healthchat_web.service) och README att `--workers 1` krävs av **två** skäl: DEK i processminne (`S-13`) och garth/garminconnect-modulstate.
  4. Se `Q-18` punkt 4 om att avveckla `garth`-beroendet helt.
- **Acceptanskriterier:**
  1. `grep -n "garth\." garmin_handler.py` ger inga träffar på `garth.client`.
  2. `pytest -q` är grönt, inklusive `test_garmin_handler.py`.
  3. Motiveringen till `--workers 1` är dokumenterad på båda ställena.

---

### [ ] Q-20: Samlade mindre fynd
- **Fil:** flera
- **Problem & åtgärd:**
  1. **Dubblerad import.** `import secret_store` står både på [server.py:36](server.py) och [server.py:827](server.py). Ta bort den senare. (Fångas framöver av `ruff --select F811`, se `Q-13`.)
  2. **`@app.on_event("startup")` är deprecated.** [server.py:292](server.py) ger `DeprecationWarning` från FastAPI: *"on_event is deprecated, use lifespan event handlers instead"*. Byt till en `lifespan`-context manager som skickas till `FastAPI(lifespan=...)`. Passa på att flytta migreringskörningen dit (`Q-19`).
  3. **`req.model` saknar allowlist.** `/api/ai/chat` tar modellnamnet rakt från klienten ([server.py:894-900](server.py)) och skickar det vidare till Ollama. Det är ingen injektionsrisk, men en användare kan begära en modell som inte finns (otydligt fel) eller en som är mycket dyrare att köra. Validera mot en lista – hämta den från `/api/tags` på Ollama-servern eller konfigurera den i miljön.
  4. **45 `except Exception: pass`.** Flera är berättigade (städning i `finally`-liknande lägen), men mönstret gör det omöjligt att på syn skilja "medvetet ignorerad" från "bortglömd". Gå igenom dem och lägg minst en `logger.debug(...)` med kontext i varje, eller en kommentar som motiverar tystnaden. Börja med [garmin_handler.py](garmin_handler.py), som har 57 `except Exception` totalt.
  5. **Sessionslivslängden lovar mer än den håller.** `SESSION_MAX_AGE_SECONDS` är 30 dagar ([server.py:112](server.py)) och sätts på cookien, men DEK:en lever bara i processminnet (`S-13`). Vid varje omstart av tjänsten har användaren en giltig cookie och en död session → 401. Frontend hanterar det ([static/app.js:478-482](static/app.js)), men upplevelsen blir "jag loggades ut utan förklaring". Överväg en kortare, ärligare livslängd (t.ex. 7 dagar) och ett tydligt meddelande i UI:t när sessionen försvunnit på grund av omstart.
  6. **Staplade route-dekoratorer.** `/api/profile/update` + `/api/user/profile` (POST och PUT) pekar på samma funktion ([server.py:1156-1158](server.py)), liksom fyra varianter av profiluppdatering ([server.py:1219-1222](server.py)). Tavlan har redan avfärdat detta som "fungerar som avsett", vilket stämmer – men sex vägar till samma funktion är en dokumentationsskuld. Välj en kanonisk väg, behåll de övriga som `deprecated=True` i OpenAPI-schemat, och ta bort dem i nästa större version.
  7. **`_weather_cache` saknar lås.** Utöver storleksproblemet i `PF-8`: dicten läses och skrivs från Starlettes trådpool utan synkronisering. Risken för korruption är låg i CPython, men ett `threading.Lock` är gratis och gör avsikten tydlig – resten av modulen använder redan det mönstret (`_sessions_lock`, `_sync_jobs_lock`, `_pending_garmin_lock`).
- **Acceptanskriterier:**
  1. Punkt 1, 2 och 7 är åtgärdade och `pytest -q` är grönt.
  2. Punkt 3 har en allowlist med test för avvisad okänd modell.
  3. Punkt 5 har ett medvetet beslut dokumenterat här (kortare TTL eller behållen 30-dagarscookie med motivering).
  4. Inga `DeprecationWarning` från egen kod i testkörningen.

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

### [x] TLS-4: Ollama-trafiken går alltid över `http://` (åtgärdad: HTTPS-stöd & varning vid okrypterad fjärrtrafik)
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

### [x] TLS-5: Chart.js laddas opinnat från CDN utan SRI (åtgärdad: 4.4.8 med sha384 SRI)
- **Fil:** [static/index.html:12](static/index.html)
- **Problem:** `<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>` – transporten är krypterad, men versionen är **opinnad** (senaste vid varje sidladdning) och saknar `integrity`-attribut. En komprometterad eller utbytt CDN-resurs kör godtycklig kod i en sida som visar hälsodata och håller en inloggad session. Det gör också `Content-Security-Policy` i `TLS-2` svagare, eftersom `cdn.jsdelivr.net` måste tillåtas.
- **Åtgärd:** Antingen (a) lägg Chart.js lokalt under `static/` – då kan CSP:n bli `default-src 'self'` – eller (b) pinna en exakt version och lägg till `integrity="sha384-…" crossorigin="anonymous"`.
- **Acceptanskriterier:** Ingen extern resurs laddas utan pinnad version och SRI, alternativt inga externa resurser alls.

---

### [x] TLS-6: `requirements.txt` saknar webbapplikationens beroenden (åtgärdad: delad i webb och desktop)
> ⚠️ **Delvis.** Beroendena finns numera i filen, men åtgärdspunkt 1 sade *pinnade versioner* och
> filen använder genomgående `>=`. Den kvarvarande delen är utbruten till `Q-18`.
- **Fil:** [requirements.txt](requirements.txt)
- **Problem:** Filen listar `garth`, `tk`, `pyinstaller` och desktopberoenden – men **varken `fastapi`, `uvicorn`, `pydantic` eller `email-validator`**, trots att [server.py:17-21](server.py) importerar alla fyra (`EmailStr` kräver `email-validator`). Webbappen går alltså inte att installera reproducerbart från repot, och man kan inte pinna den uvicorn-version som TLS-/proxy-uppsättningen i `TLS-1` förutsätter. Filens rubrik säger dessutom fortfarande "HealthChat **Desktop** v4.1.0".
- **Åtgärd:**
  1. Lägg till `fastapi`, `uvicorn[standard]`, `pydantic` och `email-validator` med pinnade versioner.
  2. Dela upp i `requirements.txt` (webb) och `requirements-desktop.txt`, eller markera desktopberoendena tydligt. `tk`, `ttkthemes` och `pyinstaller` hör inte hemma på en webbserver.
  3. Uppdatera rubriken så att den beskriver webbapplikationen.
- **Acceptanskriterier:** `pip install -r requirements.txt` i en ren venv räcker för att `uvicorn server:app` ska starta.

---

### [ ] TLS-7: CSP:n tillåter fortfarande `unsafe-inline` och en CDN som inte längre används
- **Fil:** [server.py:82-101](server.py) (`add_security_headers`), särskilt [server.py:92](server.py), [static/index.html](static/index.html) (72 `onclick`-attribut samt inline-`<script>` på rad 13 och 852)
- **Problem:** Säkerhetsheadern från `TLS-2` sätter:
  ```python
  "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
  ```
  Två saker i den raden är inaktuella eller onödigt tillåtande:

  1. **`https://cdn.jsdelivr.net` behövs inte längre.** `TLS-5` löstes genom att lägga Chart.js lokalt – [static/chart.umd.min.js](static/chart.umd.min.js) finns i repot och [static/index.html:12](static/index.html) laddar `/static/chart.umd.min.js?v=4.4.8`. Ingen extern resurs laddas alltså längre, men CSP:n tillåter fortfarande att en gör det. Det är precis vad `TLS-5`:s acceptanskriterium ville undvika ("alternativt inga externa resurser alls" – vilket ni valde, utan att strama åt CSP:n därefter).

  2. **`'unsafe-inline'` upphäver i praktiken CSP:ns XSS-skydd.** Direktivet finns där för att `index.html` har 72 `onclick="..."`-attribut och två inline-`<script>`-block. Så länge det står kvar kan en injicerad `<script>`-tagg köra fritt, och CSP:n skyddar bara mot externa källor.

  Kopplingen till `S-18` och `S-19` är direkt: båda de fynden handlar om att känslig data (sessionstoken, hälsochatt) ligger åtkomlig för JavaScript i sidans kontext. Deras allvarlighetsgrad bestäms av hur lätt det är att få in kod i den kontexten – och det är `'unsafe-inline'` som håller den dörren öppen. `UI-2` täppte till den kända XSS-vektorn i aktivitetstabellerna, men `escapeHtml` är ett punktskydd; CSP är djupförsvaret bakom det.
- **Åtgärd:**
  1. Ta bort `https://cdn.jsdelivr.net` ur `script-src` **direkt** – ingenting använder det. Verifiera med `grep -n "jsdelivr\|cdn\." static/index.html static/app.js`.
  2. Flytta de 72 inline-handlarna till `addEventListener` i [static/app.js](static/app.js). Mönstret blir `data-action`-attribut plus en delegerad lyssnare:
     ```html
     <button data-action="switch-auth-tab" data-arg="login">Logga in</button>
     ```
     ```js
     document.addEventListener('click', (e) => {
       const el = e.target.closest('[data-action]');
       if (!el) return;
       const fn = ACTIONS[el.dataset.action];
       if (fn) fn(el.dataset.arg, e);
     });
     ```
     Gör det gärna i samma omgång som `Q-17` punkt 4 (uppdelningen av `app.js`), eftersom båda rör samma filer.
  3. Flytta de två inline-`<script>`-blocken ([static/index.html:13](static/index.html), [static/index.html:852](static/index.html)) till egna filer under `static/`.
  4. Ta bort `'unsafe-inline'` ur `script-src` när steg 2 och 3 är klara. Behåll det tills vidare i `style-src` – de 103 `style="..."`-attributen är en separat och betydligt mindre farlig fråga, men notera den som eftersläpande arbete.
  5. Överväg att lägga till `object-src 'none'` och `base-uri 'self'`, som båda är billiga och stänger kända kringgåenden.
  6. Testa i webbläsarens konsol att inga CSP-överträdelser loggas efter ändringen – alla flikar, alla dialoger, alla diagram.
- **Acceptanskriterier:**
  1. `script-src` är `'self'` – utan `'unsafe-inline'` och utan externa domäner.
  2. Inga `onclick`/`onchange`/`onsubmit`-attribut kvar i [static/index.html](static/index.html) (`grep -c 'on[a-z]*="' static/index.html` ger 0 för händelseattribut).
  3. Hela gränssnittet fungerar utan CSP-varningar i webbläsarkonsolen.
  4. Befintligt test i [tests/test_frontend_security_and_data.py](tests/test_frontend_security_and_data.py) utökas med en assertion på att `'unsafe-inline'` inte finns i `script-src`.

---

## Avfärdat (verifierat som icke-buggar)

- **`crypto.py`** – AES-256-GCM med färsk nonce per operation, korrekt KEK/DEK-separation, `low_level.Type.ID` överallt. Inga fynd.
- **SQL-injektion** – alla värden binds som parametrar; tabellnamn valideras mot `_ALLOWED_TABLES` ([garmin_db.py:397-401](garmin_db.py), [garmin_db.py:415-419](garmin_db.py)) sedan `S-11`.
- **Sorteringsordning i dashboarden** – `sleep_hist[-1]`, `hrv_hist[-1]` (ASC → senaste sist) och `activities_hist[:10]` (DESC → senaste först) är alla korrekta för sina respektive frågor.
- **Staplade route-dekoratorer** – `@app.post` / `@app.put` på samma funktion ([server.py:636-638](server.py)) fungerar som avsett i FastAPI; varje dekorator registrerar en route och returnerar funktionen oförändrad.
- **Nakna `except:`** – inga kvar i kodbasen (`P2-1` håller).
- **`hr_zones_calc.py`** – hanterar `None` och nollvärden korrekt i samtliga ingångar. Inga fynd.
- **Utgående trafik till tredjepart** – Garmin (via `garth`), Strava, Fitbit, Withings och samtliga AI-leverantörer anropas över `https://` ([strava_handler.py:25-27](strava_handler.py), [fitbit_handler.py:26-28](fitbit_handler.py), [withings_handler.py:21-23](withings_handler.py)). Inga `verify=False` någonstans i kodbasen. Undantaget är Ollama, se `TLS-4`.
