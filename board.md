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
> **ID-serier:** `B-` buggar/korrekthet · `S-` säkerhet (fortsätter efter `S-12`) · `TLS-` transportkryptering · `UI-` frontend · `PF-` prestanda (fortsätter efter `PF-6`) · `Q-` kodkvalitet · `LEG-` juridik & regelefterlevnad · `I18N-` flerspråkighet.

---

## Sammanfattning – genomgång 2026-09-11 (kodgenomgång)

Genomgången omfattar hela webbapplikationen efter migreringen till FastAPI + MariaDB: `server.py`, `auth.py`, `crypto.py`, `garmin_db.py`, `ai_client.py`, `calorie_calc.py`, `hr_zones_calc.py`, `profile_sync.py`, de fyra integrationshandlarna samt `static/app.js`.

Kryptomodulen (`crypto.py`) håller – AES-256-GCM + Argon2id, färska nonces, korrekt KEK/DEK-separation. Auth-lagret (`auth.py`) är i grunden sunt efter `S-1..S-12`. Problemen ligger **runt** kryptot och i webblagret:

- **3 kritiska:** AI-chatten är helt trasig i UI:t (`B-1`), DEK:en lagras i **klartext** i databasen bredvid chiffertexten (`S-13`), och all hälsodata delas mellan användare så fort MariaDB inte svarar (`S-14`).
- **6 allvarliga:** felaktig dedupliceringslogik som slår ihop olika träningspass (`B-2`), BMR som tyst blir 0 (`B-3`), omkastade argument som tömmer profilen mellan workers (`B-4`), påhittade hälsovärden i UI:t (`UI-1`), öppen CORS med credentials (`S-15`) och stored XSS i aktivitetstabellen (`UI-2`).
- Därtill tolv mindre fynd kring OAuth-tokenhantering, connection pooling och kodkvalitet.
- **Ingen transportkryptering:** webbläsare→app och app→MariaDB går båda i klartext (`TLS-1`, `TLS-3`). Klientkrypteringen skyddar data i vila – inte på tråden. Se avsnittet *Transportkryptering*.

**Verifieringsstatus:** `B-2`, `B-3` och `B-6` är reproducerade med körbara skript. Övriga fynd är verifierade genom kodläsning. Testsviten går att köra: `118 passed, 6 skipped` med ett **känt fel som fanns före genomgången** (`test_withings_handler.py::test_sync_profile_weight_from_db`) plus en testmodul som inte kan samlas in headless (`test_charts_view_tabs.py`) – se `Q-9` punkt 7. **Antigravity ska köra `pytest` före och efter varje åtgärd** för att fånga regressioner.

**Arbetsordning:** se avsnittet *Arbetskö för Antigravity* nedan – uppgifterna är grupperade i omgångar med en commit per omgång.

---

---

## Sammanfattning – genomgång 2026-09-19 (säkerhet & regelefterlevnad)

Andra genomgången, med fokus på säkerhetshål och efterlevnad av GDPR, MDR och ePrivacy. Omfattar
hela webbapplikationen plus de fem integrationshandlarna och `static/app.js`.

**Utgångsläget är bättre än vid förra genomgången.** Följande verifierades aktivt och höll:

- **`crypto.py`** – AES-256-GCM, Argon2id, färska nonces, korrekt KEK/DEK-separation. Inga fynd.
- **Ingen SQL-injektion.** Samtliga f-strängar i SQL interpolerar bara platshållare (`%s`/`?`) och
  tabellnamn från interna konstanter. Användardata binds alltid som parametrar.
- **Ingen IDOR i datalagret.** Alla MariaDB-frågor är scopade på `user_id`; de oskopade ligger enbart
  i SQLite-grenen (desktop, enanvändare).
- **XSS-skyddet håller.** `escapeHtml` används konsekvent, och `renderMarkdown` escapar **före**
  markdown-omvandlingen – rätt ordning. `UI-2` håller.
- **OAuth-flödet är korrekt byggt** – `state` jämförs i konstant tid, PKCE används, callbacken är
  sessionsbunden, och `public_status` läcker aldrig hemligheter.
- **`S-14` är verkligen åtgärdad.** `require_mariadb=True` kastar i konstruktorn och startkontrollen
  verifierar anslutningen; SQLite-fallbacken kan inte nås i webbläge.

**Nya fynd – 23 kodpunkter och 11 efterlevnadspunkter:**

- **4 kritiska (`P0`):** kontoradering utan lösenordskontroll (`S-18` – `Q-9` punkt 5 är **felaktigt
  avbockad**), Withings-tokens skrivna till det globala keyringet utanför kuvertkrypteringen (`S-19`),
  sessionstoken utlämnad till JavaScript så att `HttpOnly` blir verkningslöst (`S-20`), och en
  CORS-regex som släpper in alla localhost-portar med credentials (`S-21` – `S-15` är inte helt löst).
- **9 allvarliga (`P1`):** kvarlämnad chatthistorik i RAM (`S-22`) och i webbläsaren (`UI-3`),
  felmeddelanden som läcker undantagsdetaljer (`S-23`), återvinningsbart Garmin-lösenord (`S-24`),
  svag rate limiting (`S-25`), sessions-/lösenordspolicy (`S-26`), ohärdad systemd-enhet (`S-27`),
  CDN-fallback utan SRI (`UI-4` – `TLS-5` delvis regredierad), hårdkodad AI-backendadress (`TLS-7`)
  och ett tredjepartsanrop över klartext-HTTP (`TLS-8`).
- **3 kodkvalitet (`P2`):** indatavalidering (`Q-11`), opinnade beroenden och deprecated `garth`
  (`Q-12`), samt fyra mindre robusthetsfynd (`Q-13`).
- **11 efterlevnadspunkter (`LEG-1` … `LEG-11`):** appen behandlar känsliga uppgifter enligt art. 9
  helt utan rättslig grund, samtycke, integritetspolicy, registerförteckning, DPIA eller
  MDR-kvalificeringsbedömning. Se avsnittet *Regelefterlevnad* – **läs dess förbehåll först.**

**Fortfarande öppet sedan förra genomgången:** `TLS-1` (ingen TLS-terminering) är bekräftad och är nu
den enskilt tyngsta tekniska bristen – hälsodata, lösenord och sessionstoken går i klartext över
nätet, vilket `S-20` och `S-21` förvärrar.

**Verifieringsstatus:** samtliga fynd är verifierade genom kodläsning; `S-18`, `S-19`, `S-21`, `S-22`
och `UI-3` är dessutom spårade steg för steg genom anropskedjan. Testsviten kördes:
**210 passed, 9 failed, 8 skipped**. Alla nio fel beror på att MariaDB saknas i granskningsmiljön
(`503`) – inga är defekter. Se *Miljö* nedan.

---

## Sammanfattning – genomgång 2026-09-19 (flerspråkighet)

Separat genomgång av vad som krävs för att köra HealthChat på **svenska, engelska och polska**.
Detaljerna finns i avsnittet *Flerspråkighet*; uppgifterna är `I18N-1` … `I18N-10`.

**Uppmätt omfattning:** ~730 strängar / ~4 980 ord per språk, fördelat på `static/index.html` (327),
`static/app.js` (232), backend (171) och AI-systemprompten. Två nya språk ≈ 10 000 ord.

**Ingen i18n-infrastruktur finns** – noll träffar på `Accept-Language|gettext|i18n|babel|locale`,
och `<html lang="sv">` är hårdkodat.

**Tre saker är redan rätt och kräver ingen åtgärd:** datumen är ISO överallt (fungerar i alla tre
språken), `utf8mb4` hanterar polska tecken, och pluralformer används på så få ställen att polskans
tre former blir hanterbara.

**Tre saker är svårare än de ser ut:**

1. **Strängarna är dubblerade.** Väderbeskrivningarna finns parallellt i `server.py` och `app.js`,
   och felmeddelanden reser genom tre lager från `auth.py` till en `alert()`. Måste avdubblas
   **innan** översättning påbörjas (`I18N-1`) – det löser samtidigt `S-23`.
2. **Sifferformateringen är redan fel.** `toFixed()` ger punkt som decimaltecken på 24 ställen, så
   appen visar engelsk notation (`5.51`) i ett svenskt gränssnitt i dag. `I18N-5` är alltså en
   buggrättning, inte bara i18n-arbete.
3. **AI-prompten är den enda posten med osäker insats.** En tredjedel av dess 44 rader är empiriskt
   framtagna lappar för vad `gemma4:12b` gör fel *på svenska*. De går inte att översätta – för polska
   måste motsvarande fel upptäckas genom utvärdering. Se `I18N-10`, som också förklarar varför detta
   berör `LEG-9` och inte bara är en kvalitetsfråga.

**Rekommendation:** engelska först (validerar mekaniken, och AI-sidan är nära gratis – sektion 2 och 5
i systemprompten kan strykas helt), polska sist med ett eget utvärderingssteg.

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

### Omgång 8 – Åtkomstkontroll & sessioner (`P0`)
| Ordning | ID | Fil | Omfattning |
|---|---|---|---|
| 1 | `S-18` | `server.py`, `auth.py` | Kräv och verifiera alltid lösenord vid kontoradering |
| 2 | `S-20` | `server.py`, `static/app.js` | Sluta lämna ut sessionstoken till JavaScript |
| 3 | `S-21` | `server.py` | Snäva in CORS-regexen, inför CSRF-token |
| 4 | `S-19` | `withings_handler.py`, `datasource_store.py` | `is_default_dir`-skydd + `token_store_dir` för Withings |

Ta dem i den här ordningen: `S-18` är en enradsfix som stoppar irreversibel dataförstörelse, och
`S-20` minskar skadan av allt annat. `S-19` kräver **operatörsarbete efteråt** – se listan nedan.

### Omgång 9 – Dataläckage & kvarlämnade uppgifter (`P1`)
| Ordning | ID | Fil | Omfattning |
|---|---|---|---|
| 5 | `S-22` | `server.py`, `auth.py` | Rensa chatthistorik i RAM vid utloggning och radering |
| 6 | `UI-3` | `static/app.js` | Rensa chatthistorik i `localStorage` vid utloggning |
| 7 | `S-23` | `server.py` | Använd `datasource_errors`-mönstret på alla felsvar |
| 8 | `S-24` | `server.py`, `datasource_store.py` | Sluta lagra Garmin-lösenordet återvinningsbart |
| 9 | `UI-4` | `static/index.html`, `server.py` | Ta bort CDN-fallbacken, skärp CSP:n |

`S-22` och `UI-3` är förutsättningar för `LEG-4` – gör dem före efterlevnadsomgången.

### Omgång 10 – Härdning & drift (`P1`)
| Ordning | ID | Fil | Omfattning |
|---|---|---|---|
| 10 | `S-25` | `auth.py` | IP-baserad rate limiting + tak på `_failed_attempts` |
| 11 | `S-26` | `server.py`, `auth.py` | Kortare sessioner, inaktivitetsgräns, starkare lösenordspolicy |
| 12 | `TLS-7` | `server.py`, `garmin_db.py` | Ta bort hårdkodade IP-adresser som fallback |
| 13 | `TLS-8` | `server.py` | HTTPS mot tredjepart + intervallvalidering av `lat`/`lon` |
| 14 | `S-27` | `healthchat_web.service` | Systemd-härdning (kan göras av agent, kräver driftsättning) |

### Omgång 11 – Kodkvalitet (`P2`)
| Ordning | ID | Fil | Omfattning |
|---|---|---|---|
| 15 | `Q-11` | `server.py`, `auth.py` | `EmailStr`, maxlängder, tillåtlista för modellnamn |
| 16 | `Q-12` | `requirements.txt`, `garmin_handler.py` | Pinna beroenden, `pip-audit`, utred `garth` |
| 17 | `Q-13` | `server.py`, `garmin_db.py`, `init_mariadb_admin.sql` | Fyra mindre robusthetsfynd |

### Omgång 12 – Regelefterlevnad (`LEG-1` … `LEG-11`)
> ⚠️ **Läs förbehållet i avsnittet *Regelefterlevnad* innan du börjar.** Flera punkter kräver
> ägarbeslut och kan inte slutföras av en agent ensam. En agent kan skriva utkast och bygga mekanik.
>
> **Första steget är ett ägarbeslut:** drivs appen enbart privat för en enda person gäller
> hushållsundantaget och `LEG-1` … `LEG-8` bortfaller. Avgör det innan något annat görs.

| Ordning | ID | Kan agent göra? | Omfattning |
|---|---|---|---|
| 18 | `LEG-4` | ✅ Ja | Fullständig radering – bygger på `S-19`, `S-22`, `UI-3` |
| 19 | `LEG-3` | ✅ Ja | Registerutdrag / dataportabilitet |
| 20 | `LEG-10` | ✅ Ja | Ta bort `localStorage`-lagringen |
| 21 | `LEG-1` | ⚠️ Delvis | Samtyckesmekanism – rättslig grund kräver ägarbeslut |
| 22 | `LEG-2` | ⚠️ Delvis | Integritetspolicy – utkast av agent, uppgifter av ägare |
| 23 | `LEG-6` | ⚠️ Delvis | Registerförteckning + rätta README:s säkerhetspåståenden |
| 24 | `LEG-9` | ⚠️ Delvis | Disclaimer + systemprompt av agent, MDR-beslut av ägare |
| 25 | `LEG-11` | ⚠️ Delvis | Gallringsjobb av agent, frister av ägare |
| 26 | `LEG-5` | ❌ Nej | Biträdesavtal – ägaren tecknar |
| 27 | `LEG-7` | ❌ Nej | DPIA – ägaren äger bedömningen |
| 28 | `LEG-8` | ❌ Nej | Incidentrutin – ägaren utser ansvarig |

---

### Omgång 13 – Flerspråkighet (`I18N-1` … `I18N-10`)
> Ordningen är viktig: `I18N-1` måste vara klar innan något översätts, annars översätts samma sträng
> två gånger. `I18N-8` (engelska) före `I18N-9`/`I18N-10` (polska) – engelska validerar mekaniken
> billigt och är referensspråk för `t()`-fallbacken.

| Ordning | ID | Fil | Omfattning |
|---|---|---|---|
| 29 | `I18N-1` | `server.py`, `static/app.js`, `auth.py` | Avdubbla väderströmmar, inför felkoder (**gör först**, löser `S-23`) |
| 30 | `I18N-2` | `static/i18n/*.json`, `static/app.js` | Katalogformat, `t()`, dynamiskt `lang`-attribut |
| 31 | `I18N-5` | `static/app.js` | `Intl.NumberFormat` – rättar befintlig svensk decimalbugg |
| 32 | `I18N-3` | `static/index.html` | Extrahera 327 strängar, varav 49 popover-block |
| 33 | `I18N-4` | `static/app.js` | Extrahera 232 strängar, ersätt 18 `alert()` |
| 34 | `I18N-7` | `datasource_store.py` | Onboarding-texter ut ur `PROVIDERS` |
| 35 | `I18N-6` | `server.py`, `static/app.js` | Språkval: `Accept-Language` + cookie, sedan profilfält |
| 36 | `I18N-8` | `static/i18n/en.json`, `ai_client.py` | Engelsk katalog + språkparametriserad AI-prompt |
| 37 | `I18N-9` | `static/i18n/pl.json`, `static/styles.css` | Polsk katalog + layoutkontroll (10–20 % längre text) |
| 38 | `I18N-10` | `ai_client.py`, `server.py` | **Polsk AI-prompt – kräver utvärdering, osäker insats** |

`I18N-5` ligger tidigt trots låg ordning i analysen, eftersom den rättar en bugg som finns i dag och
är oberoende av resten.

---

### 🔧 Operatörsarbete – kan inte göras av en agent

Dessa kräver åtkomst till servern och databasen. De blockerar inte kodarbetet ovan.

- [ ] **Rotera databaslösenordet.** Kvarstår från `S-17`; värdet ligger i git-historiken sedan `7db86ef`. Se checklistan i `TLS-3`.
- [x] **Skapa `/etc/healthchat/db.env`** med rättigheterna `0600` och ägare `healthchat`. Klart.
- [ ] **`TLS-1`: reverse proxy med TLS** framför uvicorn, plus `--host 127.0.0.1` i unit-filen.
- [ ] **`TLS-3`: TLS mot MariaDB** – CA-certifikat på plats, `MARIADB_REQUIRE_TLS=1`, `require_secure_transport=ON` på servern.

**Tillkommer efter genomgången 2026-09-19:**

- [ ] **Rotera Withings-tokens och rensa serverns keyring.** Kvarstår från `S-19`: access- och
  refresh-tokens har skrivits okrypterat till serverkontots OS-keyring vid varje token-refresh.
  Återkalla dem i Withings utvecklarportal och rensa posterna (`withings_access_token`,
  `withings_refresh_token`) efter att koden är fixad – annars skrivs de bara tillbaka.
- [ ] **Driftsätt systemd-härdningen från `S-27`** och verifiera med `systemd-analyze security healthchat_web`.
- [ ] **Ägarbeslut: omfattas appen av hushållsundantaget?** Blockerar hela `LEG-1` … `LEG-8`.
  Se förbehållet i avsnittet *Regelefterlevnad*.
- [ ] **Teckna biträdesavtal** för de mottagare `LEG-5` listar, eller ta bort tjänsterna.
- [ ] **Genomför DPIA (`LEG-7`)** och utse ansvarig för incidentrutinen (`LEG-8`).
- [ ] **Skaffa en polsk modersmålstalare för korrekturläsning** av katalogen i `I18N-9`, särskilt
  popover-texterna om träningsfysiologi. Släpps polska AI-svar behövs samma granskning av de
  skadeanpassade rekommendationerna (`I18N-10`).

---

### Miljö – så här får du testsviten att köra

Repot saknar webbappens beroenden i `requirements.txt` (det är `TLS-6`). Tills den är fixad:

```bash
pip install pytest pymysql dbutils cryptography argon2-cffi keyring \
            fastapi "uvicorn[standard]" httpx email-validator requests garth garminconnect
pytest --ignore=tests/test_charts_view_tabs.py -q
```

Förväntat utfall vid genomgången 2026-09-19: **210 passed, 9 failed, 8 skipped** – där samtliga nio
fel beror på att MariaDB saknas i granskningsmiljön (endpointsen svarar `503`) och **inget** är en
defekt. Har du MariaDB uppe ska de gå igenom. Historiskt förväntat utfall utan databas var:
**118 passed, 6 skipped, 1 failed**. Det enda felet
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

### [ ] S-18: `delete_account` kräver fortfarande inget lösenord – `Q-9` punkt 5 är felaktigt avbockad
- **Fil:** [server.py](server.py) (`class DeleteAccountRequest`, `def delete_account`), [auth.py](auth.py) (`delete_user_account`)
- **Status:** 🔴 **Regression / falskt stängd.** `Q-9` punkt 5 i den här filen påstår med ✅ att "`auth.delete_user_account` och `/api/user/delete_account` kräver och verifierar `current_password`". Det gör de inte.
- **Problem:** Fältet är valfritt hela vägen ned:
  ```python
  class DeleteAccountRequest(BaseModel):
      current_password: Optional[str] = None   # ← valfritt
  ...
  pw = req.current_password if req else None
  auth.delete_user_account(conn, session.user_id, current_password=pw)
  ```
  och i `auth.delete_user_account` står kontrollen bakom `if current_password is not None:`. Skickas ingen body alls – eller `{}`, eller `{"current_password": null}` – hoppas verifieringen över och kontot raderas.
  Frontend *skickar* lösenordet (`handleDeleteAccount` i [static/app.js](static/app.js) postar `{ current_password: password }`), men det är ren klientsidekontroll som vem som helst kan gå förbi med `curl`. Enbart en giltig sessionstoken krävs för att permanent och oåterkalleligt radera kontot och all hälsodata. Tillsammans med `S-20` blir varje XSS till total dataförstörelse. OWASP A01 (Broken Access Control).
- **Åtgärd:**
  1. Gör fältet obligatoriskt: `current_password: str` i `DeleteAccountRequest`, och gör `req` till en obligatorisk parameter i `delete_account` (inte `Optional[...] = None`).
  2. Ta bort `if current_password is not None:` i `auth.delete_user_account` – verifiera alltid. Behåll `Optional` i signaturen endast om desktopläget kräver det, och kasta i så fall `ValueError` när den saknas i webbvägen.
  3. Samma genomgång för övriga tillståndsändrande endpoints: `change_password` och `rotate_recovery_key` verifierar redan korrekt – bekräfta att inget annat destruktivt anrop saknar kontroll.
- **Acceptanskriterier:**
  1. `POST /api/user/delete_account` **utan body** ger `400`/`422` och kontot finns kvar.
  2. `POST /api/user/delete_account` med `{"current_password": null}` respektive `{}` ger `400`/`422` och kontot finns kvar.
  3. Fel lösenord ger `400` med "Felaktigt lösenord." och kontot finns kvar.
  4. Rätt lösenord raderar kontot som tidigare.
  5. Test som täcker alla fyra fallen ovan. Bocka **inte** av `Q-9` punkt 5 förrän testet finns.

---

### [ ] S-19: Withings OAuth-tokens skrivs till det globala keyringet utanför kuvertkrypteringen
- **Fil:** [withings_handler.py](withings_handler.py) (`refresh_access_token`), [datasource_store.py](datasource_store.py) (`build_handler`, grenen `if provider == "withings"`)
- **Problem:** `refresh_access_token` kör **ovillkorligt**, vid varje token-refresh:
  ```python
  import secret_store
  secret_store.set_secret("withings_access_token", self.access_token)
  secret_store.set_secret("withings_refresh_token", self.refresh_token)
  ```
  Withings är den **enda** handlern utan `is_default_dir`-skydd. Räkna förekomsterna:
  ```
  whoop_handler.py:5    strava_handler.py:5    fitbit_handler.py:5    withings_handler.py:0
  ```
  De övriga tre gattar keyring-skrivningen bakom `is_default_dir` just för att webbläget (som får en slängbar katalog från `temp_token_dir()`) aldrig ska röra det globala keyringet. `build_handler` skickar dessutom **ingen `token_store_dir`** till `WithingsDataHandler` – till skillnad från alla andra providers – så det går inte ens att välja bort.
  Följd: en levande OAuth-token som ger läsåtkomst till användarens kroppssammansättningshistorik hamnar i klartext i serverkontots OS-keyring, i ett **globalt namnutrymme utan `user_id`**. Det kringgår hela S-13-modellen – ingen DEK behövs för att läsa den – och är exakt den klass av problem som `S-14` beskriver för `secret_store`. I flerandvändarläge skriver varje användares synk över föregående användares post.
- **Bonusfynd i samma funktion:** blocket direkt efter keyring-skrivningen försöker uppdatera `~/.healthchat/config.json` med `json.load` och `os.open`, men **varken `json` eller `os` är importerade på modulnivå** i `withings_handler.py` (endast lokalt i `import csv` / `import json` inne i en annan funktion). Blocket kastar därför `NameError` vid varje anrop och sväljs tyst av `except Exception as save_err: logger.debug(...)`. Koden har aldrig fungerat.
- **Åtgärd:**
  1. Lägg in samma `is_default_dir`-skydd som i `whoop_handler`/`strava_handler`/`fitbit_handler` runt **båda** persisteringsblocken, och ge `WithingsDataHandler` en `token_store_dir`-parameter.
  2. Låt `build_handler` skicka `token_dir` till `WithingsDataHandler` precis som för övriga providers, så att webbvägen alltid får en slängbar katalog.
  3. Ta bort eller reparera `config.json`-blocket. Ska det vara kvar: lägg `import json` och `import os` på modulnivå. Ska det bort (rekommenderas för webben): radera det – den auktoritativa kopian ligger krypterad i `user_datasources`.
  4. Rotera alla Withings-tokens som redan hunnit skrivas till serverns keyring, och rensa posterna (`secret_store.delete_secret("withings_access_token")` m.fl.). Se operatörslistan.
- **Acceptanskriterier:**
  1. En Withings-synk i webbläge skriver **inga** poster till OS-keyringet – test som monkeypatchar `secret_store.set_secret` och hävdar att den aldrig anropas när `token_store_dir` är en temporär katalog.
  2. `grep -c is_default_dir withings_handler.py` returnerar samma skyddsnivå som övriga handlare.
  3. `build_handler("withings", ...)` skickar vidare `token_dir`.
  4. Inga `NameError` längre – antingen är blocket borta eller så har det fungerande importer, bevisat med test.
  5. Inga Withings-tokens kvar i serverkontots keyring.

---

### [ ] S-20: Sessionstoken lämnas ut till JavaScript – `HttpOnly` blir verkningslöst
- **Fil:** [server.py](server.py) (`register`, `login` – fälten `"session_id": session_id` i svarskroppen), [static/app.js](static/app.js) (`sessionStorage.setItem('healthchat_session', data.session_id)`)
- **Problem:** Servern sätter en korrekt härdad cookie – `httponly=True`, `secure`, `samesite="lax"` – och returnerar sedan **samma token i JSON-svaret**, som frontend lägger i `sessionStorage`. `HttpOnly`-skyddet är därmed borta i praktiken: vilken XSS som helst läser `sessionStorage` och `get_current_session` accepterar värdet via `Authorization`-headern.
  Konsekvensen är större här än i en vanlig app: token låser upp en session vars **DEK redan ligger dekrypterad i serverns RAM** (`_active_sessions`, S-13 väg A). Stulen token = full läsåtkomst till all hälsodata utan lösenord, plus permanent kontoradering via `S-18`.
  `apiFetch` skickar redan cookien (`credentials`), så `Authorization`-vägen behövs inte för webbklienten.
- **Åtgärd:**
  1. Ta bort `"session_id"` ur svarskroppen i `register` och `login`. Behåll `user_id`, `email` och `profile`.
  2. Ta bort `sessionStorage`-hanteringen i `static/app.js` och låt `apiFetch` enbart förlita sig på cookien. Kontrollera att inloggningstillståndet i UI:t härleds från `/api/auth/me` i stället för från förekomsten av en token.
  3. Behåll `Authorization`-stödet i `get_current_session` endast om ett icke-webbklientflöde faktiskt kräver det. Gör det i så fall till ett medvetet, dokumenterat undantag – annars ta bort det också.
- **Acceptanskriterier:**
  1. Inloggningssvaret innehåller inget sessionstoken-värde.
  2. `grep -c "sessionStorage" static/app.js` innehåller inga träffar för sessionstoken.
  3. Full inloggning → dashboard → utloggning fungerar enbart med cookien.
  4. Test som hävdar att `login`-svarets nycklar inte innehåller `session_id`.

---

### [ ] S-21: CORS-regexen tillåter alla localhost-portar med credentials – `S-15` är inte helt åtgärdad
- **Fil:** [server.py](server.py) (`app.add_middleware(CORSMiddleware, ...)`, parametern `allow_origin_regex`)
- **Status:** 🟠 **Ofullständig åtgärd av `S-15`.** Den explicita `allow_origins`-listan är korrekt låst via `ALLOWED_ORIGINS`, men regexen bredvid öppnar upp igen:
  ```python
  allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?"
  ```
- **Problem:** `allow_credentials` är `True` så länge `ALLOWED_ORIGINS` inte innehåller `*`. Regexen matchar då **varje port på localhost**. Det är den skarpa varianten: `http://localhost:3000` → `http://localhost:8000` räknas som *same-site* (samma registrerbara domän), så `SameSite=Lax` **blockerar inte** cookien. Vilken sida som helst på en annan lokal port – ett dev-serverprojekt, en lokalt installerad app, en npm-pakets postinstall-server – kan alltså göra autentiserade anrop, läsa ut hela hälsodatasvaret och trigga `S-18`.
  LAN-fallen (`192.168.*`, `10.*`) är mindre akuta eftersom skilda IP-adresser räknas som olika siter och `Lax` då stoppar cookien – men de öppnar fortfarande `Authorization`-vägen om en token läckt (`S-20`).
- **Åtgärd:**
  1. Ta bort `allow_origin_regex` helt och förlita dig på `ALLOWED_ORIGINS`. Behövs LAN-åtkomst i utveckling: lägg de faktiska adresserna i miljövariabeln i stället.
  2. Behålls regexen mot allas vilja: snäva in den till exakt de portar som används, och sätt `allow_credentials=False` för de regexmatchade origins.
  3. Genomför punkt 4 från `S-15` som lämnades som "överväg": inför CSRF-token för de tillståndsändrande endpointsen (`/api/user/delete_account`, `/api/profile/change_password`, `/api/user/rotate_recovery_key`, `/api/datasources/*`). `SameSite=Lax` räcker bevisligen inte när same-site-begreppet omfattar alla portar på localhost.
- **Acceptanskriterier:**
  1. Preflight från `http://localhost:31337` mot `/api/dashboard/summary` nekas.
  2. Preflight från en origin i `ALLOWED_ORIGINS` tillåts med credentials.
  3. Tillståndsändrande endpoints avvisar anrop utan giltig CSRF-token.
  4. Test som täcker punkt 1–3.

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
> ⚠️ **Delvis återöppnad 2026-09-19 – se `S-21`.** `allow_origins` är korrekt låst, men `allow_origin_regex` släpper fortfarande in **alla portar på localhost** med credentials, och punkt 4 nedan (CSRF-token) genomfördes aldrig.
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

### [ ] S-22: Chatthistoriken lever kvar i serverns RAM efter utloggning och kontoradering
- **Fil:** [server.py](server.py) (`_user_chat_histories`, `_session_chat_histories`, `remove_active_session`, `chat_stream`, `clear_chat_history`), [auth.py](auth.py) (`delete_user_account`)
- **Problem:** Två globala dictar håller hela AI-konversationen i klartext i processminnet. `remove_active_session` rensar bara den sessionsnycklade (`_session_chat_histories.pop(session_id, None)`) – den **användarnycklade** `_user_chat_histories` rensas enbart av den explicita endpointen `/api/ai/chat/clear`. Den rensas alltså **inte** vid utloggning och **inte** vid kontoradering.
  Innehållet är känsliga uppgifter enligt art. 9: hälsokontexten som `chat_stream` bygger innehåller ålder, vikt, BMI, midjemått, vilopuls, HRV, sömn och **kända skador**. Tre följder:
  1. **Radering blir ofullständig** – `delete_user_account` tömmer databasen korrekt via CASCADE, men konversationen ligger kvar i RAM. Se `LEG-4`.
  2. **Obegränsad minnestillväxt** – ingen TTL, ingen storleksgräns, ingen städning. En långkörande process samlar på sig varje användares konversation tills den startas om (minnes-DoS).
  3. **Utanför kuvertet** – innehållet är klartext och skyddas inte av DEK:en, till skillnad från all annan hälsodata. Det motsäger README:s säkerhetsavsnitt.
- **Åtgärd:**
  1. Rensa `_user_chat_histories[session.user_id]` i `remove_active_session` (eller i `logout`) och i `delete_account`.
  2. Ge båda dictarna en TTL och ett tak, med samma städmönster som `cleanup_expired_sessions`.
  3. Överväg att kryptera historiken med användarens DEK om den ska överleva en enskild session – annars låt den dö med sessionen och ta bort `_user_chat_histories` helt. Det senare är enklast och räcker för `Q-2`:s ursprungliga syfte.
  4. Skydda åtkomsten med `_sessions_lock` (se `Q-13`).
- **Acceptanskriterier:**
  1. Efter `POST /api/auth/logout` är användarens historik borta ur båda dictarna.
  2. Efter kontoradering är historiken borta ur båda dictarna.
  3. Test som hävdar punkt 1 och 2.
  4. En dict med TTL släpper poster efter utgången livslängd.

---

### [ ] S-23: Felmeddelanden läcker interna undantagsdetaljer till klienten
- **Fil:** [server.py](server.py) – `login` (`f"Serverfel vid inloggning: {e}"`), `get_weather` (`f"Kunde inte hämta väder: {ex}"`), `datasource_oauth_callback` (`f"Anslutningen misslyckades: {e}"`), `chat_stream` (`json.dumps({'error': str(e)})`), `_run_datasource_sync` (`f"Synkroniseringen misslyckades: {e}"`)
- **Problem:** Kodbasen har redan rätt mönster – `datasource_errors` returnerar bara undantagets **typnamn** plus en korrelations-id, med den uttryckliga motiveringen i sin egen docstring att "undantagsmeddelandet kan bära anslutningssträngar eller URL:er med tokens". Fem ställen kringgår det skyddet och skickar `str(e)` rakt till klienten.
  Allvarligast är `datasource_oauth_callback`: den ligger **i** tokenutbytesvägen, så ett `requests`-undantag där kan innehålla URL:en med `client_secret` eller `code`. `chat_stream` kan läcka Ollama-värdens interna adress (se `TLS-7`), och `login` kan läcka databasdetaljer.
- **Åtgärd:**
  1. Använd `datasource_errors`-mönstret på alla fem ställena: logga fullständigt på serversidan med ett korrelations-id, returnera typnamn + id till klienten.
  2. `datasource_oauth_callback` bör wrappa hela sin `try`-kropp i `datasource_errors` i stället för att ha ett eget `except Exception`.
  3. Gå igenom övriga `raise HTTPException(..., detail=f"...{e}")` i filen med samma måttstock.
- **Acceptanskriterier:**
  1. Inget svar från ett API innehåller `str(e)` från ett ofångat undantag.
  2. Serverloggen innehåller fortfarande fullständig `exc_info` plus korrelations-id.
  3. Test som framtvingar ett fel i tokenutbytet och hävdar att svaret inte innehåller `client_secret`.

---

### [ ] S-24: Garmin-lösenordet lagras återvinningsbart och ligger i klartext i serverminnet
- **Fil:** [server.py](server.py) (`connect_garmin`, `_pending_garmin`), [datasource_store.py](datasource_store.py) (`has_tokens`, grenen `provider == "garmin"`)
- **Problem:** Vid `save_credentials` sparas användarens **Garmin-lösenord** i nyttolasten (`payload["password"] = password`). Det är krypterat med DEK:en, men till skillnad från en lösenordshash är det **reversibelt** – syftet är just att kunna logga in igen. Under MFA-flödet ligger det dessutom i klartext i `_pending_garmin` i upp till `GARMIN_PENDING_TTL_SECONDS` (600 s), oskyddat av kuvertet.
  Att lagra ett tredjepartskontos lösenord återvinningsbart är svårt att försvara när flödet redan producerar återanvändbara sessionstokens (`garmin_tokens`, `oauth1_token`, `oauth2_token`), och står sannolikt i strid med Garmins användarvillkor.
- **Åtgärd:**
  1. Sluta spara lösenordet efter lyckad inloggning – behåll bara de tokens `collect_tokens` läser ut. Ta bort `payload["password"] = password`.
  2. Justera `has_tokens` så att Garmin räknas som ansluten på tokens, inte på `email + password`.
  3. Nolla lösenordssträngen i `_pending_garmin` så snart MFA-flödet är klart eller har gått ut, och korta ned TTL:en om 600 s inte behövs.
  4. Sätt `save_credentials` till `False` som default i `GarminConnectRequest` och förklara i UI:t att återanslutning kräver ny inloggning när tokens gått ut.
- **Acceptanskriterier:**
  1. Efter lyckad Garmin-anslutning innehåller den dekrypterade nyttolasten ingen `password`-nyckel.
  2. En synk fungerar enbart på lagrade tokens.
  3. `_pending_garmin` är tom efter genomfört MFA-flöde.
  4. Test som hävdar punkt 1.

---

### [ ] S-25: Rate limiting sker bara per e-postadress och växer obegränsat
- **Fil:** [auth.py](auth.py) (`_failed_attempts`, `check_rate_limit`, `record_failed_attempt`)
- **Problem:** Spärren är nyckelad **enbart** på e-postadress: max 5 misslyckade försök per minut per konto. Två luckor:
  1. **Ingen IP-dimension.** Lösenordsspridning – ett vanligt lösenord mot tusentals konton – bromsas inte alls, eftersom varje adress har sin egen kvot.
  2. **Obegränsad dict.** Varje ny e-postadress skapar en post, och städningen sker bara för adresser som råkar efterfrågas igen. En angripare som skickar inloggningsförsök för slumpmässiga adresser får dicten att växa tills processen tar slut på minne.
  Spärren är dessutom per process och försvinner vid omstart.
- **Åtgärd:**
  1. Lägg till en IP-baserad spärr vid sidan av den per konto (läs klientadressen med hänsyn till `--proxy-headers`/`X-Forwarded-For` bakom reverse proxy, så att den inte går att förfalska).
  2. Ge `_failed_attempts` ett tak och en periodisk städning av alla utgångna poster, inte bara den efterfrågade nyckeln.
  3. Överväg progressiv fördröjning i stället för hård spärr, så att ett konto inte kan låsas ute av någon annan (DoS mot legitim användare).
- **Acceptanskriterier:**
  1. 20 misslyckade försök från samma IP mot 20 olika adresser spärras.
  2. `_failed_attempts` växer inte obegränsat vid 10 000 unika adresser.
  3. Test som täcker punkt 1 och 2.

---

### [ ] S-26: 30 dagars sessioner, ingen MFA och lösenordspolicy på 8 tecken för art. 9-data
- **Fil:** [server.py](server.py) (`SESSION_MAX_AGE_SECONDS`), [auth.py](auth.py) (`register_user`, `change_user_password`, `recover_account`)
- **Problem:** Tre svaga inställningar som var för sig är försvarbara men tillsammans är för tunna för hälsodata:
  1. `SESSION_MAX_AGE_SECONDS` är `86400 * 30` – en stulen token (se `S-20`) gäller i en månad. Det finns ingen inaktivitetsbaserad utgång, bara absolut.
  2. **Ingen MFA** på HealthChat-kontot, trots att appen själv hanterar MFA mot Garmin.
  3. Lösenordspolicyn är `len(password) < 8` och inget annat – ingen kontroll mot kända läckta lösenord, ingen längdrekommendation. Argon2id-parametrarna (t=2, m=64 MB, p=1) ligger i underkant av OWASP:s rekommendation.
- **Åtgärd:**
  1. Korta absoluta livslängden väsentligt (förslag: 7 dygn) och inför en inaktivitetsgräns (förslag: 24 h) som förnyas vid aktivitet.
  2. Inför valfri TOTP-baserad MFA för inloggning. Är det för stort: lägg upp som egen uppgift och dokumentera beslutet.
  3. Höj minimilängden till 12 tecken, och kontrollera lösenordet mot en lista över vanliga/läckta lösenord (t.ex. `zxcvbn` eller HIBP:s k-anonymitets-API). Höj `ARGON2_MEMORY_COST` om svarstiden tillåter – mät först.
  4. Dokumentera de valda parametrarna i README och i DPIA:n (`LEG-7`).
- **Acceptanskriterier:**
  1. En session som varit inaktiv längre än inaktivitetsgränsen avvisas med 401.
  2. Ett lösenord på 8 tecken avvisas; ett känt läckt lösenord avvisas.
  3. Test som täcker punkt 1 och 2.

---

### [ ] S-27: Systemd-enheten saknar processhärdning trots att alla DEK:er ligger i processminnet
- **Fil:** [healthchat_web.service](healthchat_web.service)
- **Problem:** Enheten kör som `User=healthchat` – bra – men saknar samtliga härdningsdirektiv. Det väger tyngre här än i en vanlig tjänst: S-13 väg A innebär att **alla inloggade användares DEK:er ligger dekrypterade i processens RAM**. En core dump, en swappad sida eller en läsbar `/proc/<pid>/mem` exponerar då nycklarna till hela databasen på en gång.
- **Åtgärd:** Lägg till i `[Service]`:
  ```ini
  NoNewPrivileges=true
  PrivateTmp=true
  ProtectSystem=strict
  ProtectHome=true
  ProtectKernelTunables=true
  ProtectKernelModules=true
  ProtectControlGroups=true
  RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
  RestrictNamespaces=true
  MemoryDenyWriteExecute=true
  LimitCORE=0
  ReadWritePaths=/var/lib/healthchat
  ```
  `ProtectHome=true` kräver att inget skrivs till `~/.healthchat` i webbläge – kontrollera mot `S-19` och `temp_token_dir()` innan den sätts. `LimitCORE=0` stänger core dumps. Verifiera med `systemd-analyze security healthchat_web`.
- **Acceptanskriterier:**
  1. `systemd-analyze security healthchat_web` ger väsentligt lägre exponeringspoäng än i dag.
  2. Tjänsten startar och all funktionalitet fungerar med direktiven på plats.
  3. `LimitCORE=0` är satt och verifierad.

---

### [ ] UI-3: Chatthistoriken i `localStorage` rensas inte vid utloggning
- **Fil:** [static/app.js](static/app.js) (`handleLogout`, `getChatStorageKey`, `getStoredChatHistory`, `saveChatHistory`)
- **Problem:** `handleLogout` tar bort sessionstoken och nollar `currentUser` – men rör inte `localStorage`-nyckeln `healthchat_chat_history_<uid>`. Hela AI-konversationen, med skador, HRV, vikt och träningsråd, ligger kvar **på disk i webbläsaren** efter utloggning, utan utgångstid.
  På en delad eller publik dator kan nästa person läsa föregående användares hälsokonversation direkt i devtools. `sessionStorage` (sessionstoken) töms när fliken stängs; `localStorage` gör det aldrig.
  Notera också att `getChatStorageKey` faller tillbaka på `'default'` när `currentUser` saknas – konversationer kan då hamna i en delad nyckel.
- **Åtgärd:**
  1. Rensa `localStorage.removeItem(getChatStorageKey())` i `handleLogout`, **innan** `currentUser` nollställs (annars pekar nyckeln på `default`).
  2. Överväg att flytta historiken till `sessionStorage` – den överlever då inte att fliken stängs, vilket räcker för syftet.
  3. Ta bort `'default'`-fallbacken; spara ingenting när ingen användare är inloggad.
  4. Koppla ihop med `LEG-10`: lagringen är inte "strikt nödvändig" och kräver samtycke om den behålls.
- **Acceptanskriterier:**
  1. Efter utloggning finns ingen `healthchat_chat_history_*`-nyckel kvar i `localStorage`.
  2. Ingen historik skrivs under nyckeln `healthchat_chat_history_default`.
  3. Test i [tests/test_frontend_security_and_data.py](tests/test_frontend_security_and_data.py) som låser beteendet.

---

### [ ] UI-4: Chart.js-fallbacken laddas från CDN utan SRI – `TLS-5` är delvis regredierad
- **Fil:** [static/index.html](static/index.html) (raderna direkt efter `<script src="/static/chart.umd.min.js?v=4.4.8">`)
- **Status:** 🟠 **Delvis regression av `TLS-5`.** Den lokala kopian är korrekt pinnad, men fallbacken under den är det inte.
- **Problem:**
  ```html
  <script src="/static/chart.umd.min.js?v=4.4.8"></script>
  <script>
    if (typeof Chart === 'undefined') {
      const cdnScript = document.createElement('script');
      cdnScript.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.8/dist/chart.umd.min.js';
      document.head.appendChild(cdnScript);
    }
  </script>
  ```
  Versionen är pinnad, men `integrity` och `crossorigin` saknas – ett dynamiskt skapat `<script>`-element ärver inget SRI. `TLS-5`:s acceptanskriterium lyder "Ingen extern resurs laddas utan pinnad version **och SRI**"; det är inte uppfyllt. Fallbacken är också skälet till att CSP:n fortfarande måste tillåta `cdn.jsdelivr.net` i `script-src`, vilket försvagar `TLS-2`.
- **Åtgärd:**
  1. Ta bort CDN-fallbacken helt. Den lokala filen finns i `static/` och laddas först – misslyckas den är nätverket eller servern nere ändå.
  2. Skärp CSP:n i `add_security_headers` till `script-src 'self' 'unsafe-inline'` när fallbacken är borta. (`'unsafe-inline'` bör på sikt bort för sig – lägg upp som egen uppgift.)
  3. Behålls fallbacken mot allas vilja: sätt `cdnScript.integrity = 'sha384-…'` och `cdnScript.crossOrigin = 'anonymous'` med hashen för exakt 4.4.8.
- **Acceptanskriterier:**
  1. Ingen extern skriptkälla laddas utan SRI – alternativt inga externa skriptkällor alls.
  2. `cdn.jsdelivr.net` är borta ur `Content-Security-Policy` om fallbacken tagits bort.
  3. Diagrammen renderas korrekt utan nätverksåtkomst till jsdelivr.

---

### [ ] TLS-7: Hårdkodad intern IP som standard för AI-backend – hälsodata kan skickas okrypterat till fel värd
- **Fil:** [server.py](server.py) (`trigger_model_preload` och `chat_stream`, båda med `or "http://192.168.107.15:11436"`), [ai_client.py](ai_client.py) (`preload_ollama_model`), [garmin_db.py](garmin_db.py) (`DEFAULT_MARIADB_HOST = "192.168.101.106"`)
- **Problem:** `TLS-4` löste `normalize_ollama_url` så att HTTPS stöds och okrypterad fjärrtrafik loggar en varning. Kvar står själva **standardvärdet**: saknas både `ollama_base_url` i keyringet och `OLLAMA_BASE_URL` i miljön faller koden tyst tillbaka på en hårdkodad adress i ett privat nät, över `http://`.
  Nyttolasten är inte harmlös. `chat_stream` bygger en kontext med ålder, vikt, BMI, midjemått, vilopuls, maxpuls, HRV, sömn och **kända skador/fysiska begränsningar** och skickar den i klartext. I en annan driftmiljö där `192.168.107.15` är någon annans maskin går känsliga uppgifter enligt art. 9 till fel mottagare, utan att någon märker det. Samma mönster finns för `DEFAULT_MARIADB_HOST`.
- **Åtgärd:**
  1. Ta bort de hårdkodade IP-adresserna som fallback. Saknas konfiguration ska anropet **misslyckas med ett tydligt fel**, inte gissa en adress. Samma princip som `S-14` etablerade för MariaDB: hellre kasta än fortsätta tyst.
  2. Lägg `OLLAMA_BASE_URL` och `OLLAMA_MODEL` som obligatoriska i `.env.example` och i driftdokumentationen.
  3. Verifiera att varningen från `TLS-4` faktiskt loggas i webbvägen när adressen inte är loopback.
  4. Dokumentera AI-backendens placering i DPIA:n (`LEG-7`) – det är en mottagare av art. 9-uppgifter.
- **Acceptanskriterier:**
  1. `grep -rn "192.168.107.15\|192.168.101.106" --include=*.py .` ger inga träffar utanför tester.
  2. Start utan `OLLAMA_BASE_URL` ger ett begripligt fel i stället för ett anrop mot en gissad adress.
  3. Test som hävdar att ingen defaultadress används.

---

### [ ] TLS-8: Platsuppslag mot `ip-api.com` går över okrypterad HTTP
- **Fil:** [server.py](server.py) (`get_weather`, anropet `requests.get("http://ip-api.com/json", timeout=3)`)
- **Problem:** Anropet går över **`http://`**, inte HTTPS. Avsnittet *Avfärdat* i den här filen slår fast att "utgående trafik till tredjepart" är krypterad med Ollama som enda undantag – det stämmer inte längre. En MITM på sträckan kan både läsa och **styra** svaret, och svaret används som koordinater.
  Två ytterligare noteringar:
  1. Tjänsten returnerar **serverns** geografiska position, inte användarens, eftersom anropet görs från servern. Funktionellt fel, inte bara ett säkerhetsfel.
  2. `lat`/`lon` är typade som `float` så URL-injektion är utesluten, men det saknas intervallvalidering (`-90..90`, `-180..180`) och `inf`/`nan` accepteras av FastAPI:s float-parsning och hamnar i URL:en.
- **Åtgärd:**
  1. Byt till `https://` – `ip-api.com` kräver API-nyckel för HTTPS, så överväg en annan tjänst eller ta bort IP-fallbacken helt och förlita dig på webbläsarens GPS plus Stockholms-defaulten.
  2. Validera `lat`/`lon` mot giltiga intervall och avvisa icke-finita värden (`Query(..., ge=-90, le=90)`).
  3. Se `LEG-5` – varje vädertjänst som tar emot koordinater är en mottagare av personuppgifter och behöver dokumenteras.
- **Acceptanskriterier:**
  1. Inga `http://`-anrop till tredjepart kvar i kodbasen.
  2. `lat=999` respektive `lat=nan` avvisas med 422.
  3. Avsnittet *Avfärdat* uppdateras så att det stämmer.

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
  5. **`delete_account` kräver inget lösenord.** [server.py:736-751](server.py) – till skillnad från `change_password` och `rotate_recovery_key`. **Åtgärd:** ⚠️ **ÅTERÖPPNAD 2026-09-19 – se `S-18`.** Punkten bockades av, men koden verifierar fortfarande inte: `current_password` är `Optional[str] = None` och kontrollen i `auth.delete_user_account` står bakom `if current_password is not None:`. Ett anrop utan body raderar kontot. Bocka inte av igen utan test som täcker tom body.
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

### [ ] Q-11: Indatavalidering saknas på flera endpoints
- **Fil:** [server.py](server.py) (`RegisterRequest`, `LoginRequest`, `ChatRequest`), [auth.py](auth.py) (`validate_email`)
- **Problem:** Fyra fynd av samma klass:
  1. **`EmailStr` importeras men används aldrig.** `RegisterRequest.email` och `LoginRequest.email` är `str`. Valideringen faller tillbaka på `auth.validate_email`, som bara kräver att strängen innehåller `@` och `.` med icke-tomma delar – `a@b.` passerar. `email-validator` finns redan i `requirements.txt` just för `EmailStr`.
  2. **Ingen maxlängd på `ChatRequest.message`.** Obegränsad indata till AI-anropet.
  3. **Ingen maxlängd på lösenord.** Argon2id hanterar långa indata (till skillnad från bcrypts 72-bytegräns), men ett lösenord på flera megabyte bränner CPU per inloggningsförsök – kombinerat med `S-25` en billig DoS.
  4. **`ChatRequest.model` skickas ovaliderad vidare** till Ollama-servern. Fältet är användarstyrt och används som modellnamn utan kontroll mot en tillåtlista.
- **Åtgärd:**
  1. Byt till `EmailStr` i `RegisterRequest` och `LoginRequest`. Behåll `auth.validate_email` för desktopvägen men skärp den, eller låt den delegera.
  2. Sätt `max_length` på `message` (förslag: 4000) och på `password` (förslag: 1024) via `Field`.
  3. Validera `ChatRequest.model` mot en tillåtlista, eller ignorera fältet och använd serverns konfigurerade modell.
  4. `ProfileUpdateRequest` bör samtidigt få rimliga intervall på `height_cm`, `age`, `weight_kg` och `waist_cm`.
- **Acceptanskriterier:**
  1. `a@b.` avvisas vid registrering med 422.
  2. Ett meddelande över maxlängden avvisas med 422.
  3. Ett okänt modellnamn accepteras inte.
  4. Test som täcker punkt 1–3.

---

### [ ] Q-12: Beroenden är opinnade och Garmin-biblioteket är deprecated
- **Fil:** [requirements.txt](requirements.txt), [garmin_handler.py](garmin_handler.py) (`import garth`)
- **Problem:** Två separata leveranskedjerisker:
  1. **Inga pins.** Samtliga 18 rader använder `>=` utan övre gräns, och det finns varken lockfil eller hashar. En brytande eller komprometterad uppströmsutgåva installeras automatiskt vid nästa `pip install`. `TLS-6` löste att beroendena *finns* i filen – inte att de är reproducerbara. Filens egen rubrik hänvisar till `TLS-6`.
  2. **`garth` är deprecated.** Testsviten skriver ut `DeprecationWarning: Garth is deprecated and no longer maintained` (se `garth/discussions/222`). Det är biblioteket som sköter **Garmin-inloggningen** – alltså den kodväg som hanterar användarens tredjepartslösenord (`S-24`). Ett obevakat bibliotek i den positionen får inte säkerhetsfixar.
- **Åtgärd:**
  1. Pinna alla beroenden till exakta versioner (`==`) och generera en lockfil med hashar (`pip-compile --generate-hashes` eller `uv pip compile`). Behåll `>=` endast i en separat `requirements.in`.
  2. Lägg in `pip-audit` (eller motsvarande) i testflödet så att kända CVE:er fångas.
  3. Utred migrering bort från `garth` – antingen till `garminconnect` direkt om den inte bygger på garth, eller till Garmins officiella API. Dokumentera beslutet här även om slutsatsen blir "behåll tills vidare".
- **Acceptanskriterier:**
  1. `pip install -r requirements.txt` i en ren venv ger identiska versioner två gånger i rad.
  2. `pip-audit` körs i testflödet och är grön.
  3. Ett dokumenterat beslut om `garth` finns i den här filen.

---

### [ ] Q-13: Mindre robusthetsfynd i server- och databaslagret
- **Fil:** [server.py](server.py), [garmin_db.py](garmin_db.py), [init_mariadb_admin.sql](init_mariadb_admin.sql)
- **Problem:** Fyra fristående småfynd, samlade i en uppgift eftersom de var för sig är triviala:
  1. **`uuid.uuid4()` används för sessions-ID** i `register` och `login`, trots att `secrets` redan importeras i filen. CPython:s `uuid4` bygger på `os.urandom`, så det är inte en sårbarhet – men `secrets.token_urlsafe(32)` är konventionen för säkerhetstokens och ger mer entropi (256 vs 122 bitar).
  2. **`GRANT` saknar `CREATE`.** `init_mariadb_admin.sql` ger bara `SELECT, INSERT, UPDATE, DELETE`, men koden kör `CREATE TABLE IF NOT EXISTS` vid runtime i `init_sessions_table` och `datasource_store.ensure_table`. Anropen misslyckas och sväljs av `except Exception` → `logger.warning`. Antingen ska schemat enbart komma från `init_mariadb.sql` (rekommenderas – runtime-DDL i en app med begränsade rättigheter är en lukt), eller så ska rättigheten finnas.
  3. **Kapplöpning på chatthistorik-dictarna.** `chat_stream` läser och skriver `_session_chat_histories` / `_user_chat_histories` **utanför** `_sessions_lock`, medan `remove_active_session` muterar den förra *under* låset. CPython:s GIL gör att dicten inte korrumperas, men läs-modifiera-skriv-sekvenserna är inte atomära. Åtgärdas naturligt tillsammans med `S-22`.
  4. **`get_db_conn` försöker SQLite även i webbläge.** `if db.is_mariadb and db.pool: ... return db.get_connection()` – fallbacken är i praktiken ofarlig i dag eftersom `db_path` är `None` när `require_mariadb=True`, så `sqlite3.connect(None)` kastar `TypeError` som fångas och ger `None`. Men den förlitar sig på en slump. Gör den explicit: kasta direkt när `require_mariadb` är satt och poolen saknas.
- **Åtgärd:** Ta punkterna i ordning; var och en är en rad eller några få.
- **Acceptanskriterier:**
  1. Sessions-ID genereras med `secrets`.
  2. Antingen är runtime-DDL borttagen ur webbvägen, eller så speglar `GRANT` det koden faktiskt gör – och `init_mariadb.sql` innehåller `user_datasources` (det gör den redan).
  3. All åtkomst till chatthistorik-dictarna sker under `_sessions_lock`.
  4. `get_db_conn` kastar eller returnerar `None` explicit i webbläge i stället för att gå via ett `TypeError`.

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
> ⚠️ **Delvis regredierad 2026-09-19 – se `UI-4`.** Den lokala kopian är pinnad, men CDN-**fallbacken** som lagts till under den saknar `integrity`/`crossorigin`. Acceptanskriteriet nedan är därmed inte uppfyllt.
- **Fil:** [static/index.html:12](static/index.html)
- **Problem:** `<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>` – transporten är krypterad, men versionen är **opinnad** (senaste vid varje sidladdning) och saknar `integrity`-attribut. En komprometterad eller utbytt CDN-resurs kör godtycklig kod i en sida som visar hälsodata och håller en inloggad session. Det gör också `Content-Security-Policy` i `TLS-2` svagare, eftersom `cdn.jsdelivr.net` måste tillåtas.
- **Åtgärd:** Antingen (a) lägg Chart.js lokalt under `static/` – då kan CSP:n bli `default-src 'self'` – eller (b) pinna en exakt version och lägg till `integrity="sha384-…" crossorigin="anonymous"`.
- **Acceptanskriterier:** Ingen extern resurs laddas utan pinnad version och SRI, alternativt inga externa resurser alls.

---

### [x] TLS-6: `requirements.txt` saknar webbapplikationens beroenden (åtgärdad: delad i webb och desktop)
- **Fil:** [requirements.txt](requirements.txt)
- **Problem:** Filen listar `garth`, `tk`, `pyinstaller` och desktopberoenden – men **varken `fastapi`, `uvicorn`, `pydantic` eller `email-validator`**, trots att [server.py:17-21](server.py) importerar alla fyra (`EmailStr` kräver `email-validator`). Webbappen går alltså inte att installera reproducerbart från repot, och man kan inte pinna den uvicorn-version som TLS-/proxy-uppsättningen i `TLS-1` förutsätter. Filens rubrik säger dessutom fortfarande "HealthChat **Desktop** v4.1.0".
- **Åtgärd:**
  1. Lägg till `fastapi`, `uvicorn[standard]`, `pydantic` och `email-validator` med pinnade versioner.
  2. Dela upp i `requirements.txt` (webb) och `requirements-desktop.txt`, eller markera desktopberoendena tydligt. `tk`, `ttkthemes` och `pyinstaller` hör inte hemma på en webbserver.
  3. Uppdatera rubriken så att den beskriver webbapplikationen.
- **Acceptanskriterier:** `pip install -r requirements.txt` i en ren venv räcker för att `uvicorn server:app` ska starta.

---

## ⚖️ Regelefterlevnad – GDPR, MDR och ePrivacy

> Genomgång 2026-09-19. Sökning på `gdpr|dataskydd|personuppgift|samtycke|consent|integritetspolicy|DPIA|MDR|medicinteknik|disclaimer`
> i all `.py`, `.html`, `.js` och `.md` utanför den här filen ger **noll träffar**. Appen behandlar
> **känsliga uppgifter enligt art. 9** (sömn, HRV, stress, vikt, fett%, kroppssammansättning och **kända skador**)
> helt utan dataskyddsdokumentation.
>
> ⚠️ **Detta är inte juridisk rådgivning.** Uppgifterna nedan beskriver vad som saknas och vad en agent
> kan förbereda. Den rättsliga bedömningen – särskilt `LEG-1`, `LEG-7` och `LEG-9` – måste göras eller
> godkännas av ägaren, vid behov med jurist. En agent ska **skriva utkast och bygga mekanik**, inte
> fastställa rättslig grund på egen hand.
>
> **Förutsättning:** flera punkter nedan antar att appen faktiskt får användare utanför utvecklarens egen
> krets. Drivs den enbart som ett privat verktyg för en enda person gäller GDPR:s hushållsundantag
> (art. 2.2 c) och `LEG-1` … `LEG-8` bortfaller. **Ta det beslutet först och skriv ned det här** – det
> avgör om resten av avsnittet är skarpt eller inte.

---

### [ ] LEG-1: Ingen rättslig grund och ingen samtyckesmekanism för art. 9-uppgifter
- **Fil:** [server.py](server.py) (`register`), [static/index.html](static/index.html) (registreringsmodalen), [static/app.js](static/app.js)
- **Kräver ägarbeslut:** ja – vilken rättslig grund som väljs.
- **Problem:** Registreringen samlar in `sex`, `height_cm`, `age`, `weight_kg` och kopplar därefter datakällor som levererar sömn, HRV, stress och kroppssammansättning. Inget i flödet ber om samtycke, informerar om behandlingen eller dokumenterar en rättslig grund. För art. 9-uppgifter räcker inte berättigat intresse – normalt krävs **uttryckligt** samtycke enligt art. 9.2 a.
- **Åtgärd:**
  1. Ägaren fastställer rättslig grund och dokumenterar den här.
  2. Bygg ett samtyckessteg i registreringen: separata, ofärdigkryssade kryssrutor för (a) behandling av hälsouppgifter, (b) överföring av hälsokontext till AI-backend. Samtycket ska vara lika lätt att ta tillbaka som att ge.
  3. Lagra samtyckesversion och tidsstämpel per användare så att det går att visa **vad** användaren samtyckte till och **när** (art. 7.1 – bevisbörda).
  4. Bygg en återkallningsfunktion i profilvyn som stänger av AI-funktionen och erbjuder radering.
- **Acceptanskriterier:**
  1. Registrering utan ikryssat samtycke går inte att slutföra.
  2. Samtyckesversion och tidsstämpel finns lagrade och går att läsa ut per användare.
  3. Återkallat samtycke stoppar behandlingen och loggas.
  4. Test som täcker punkt 1–3.

---

### [ ] LEG-2: Ingen integritetspolicy och ingen information enligt art. 13/14
- **Fil:** saknas helt – ny `PRIVACY.md` plus en vy i [static/index.html](static/index.html)
- **Kräver ägarbeslut:** delvis – en agent kan skriva utkastet, ägaren fyller i identitetsuppgifter.
- **Problem:** Den registrerade får ingen information om vem som är personuppgiftsansvarig, vilka uppgifter som behandlas, varför, hur länge, vilka mottagarna är eller vilka rättigheter som finns. Art. 13 kräver att informationen lämnas **vid insamlingen**.
- **Åtgärd:**
  1. Skriv `PRIVACY.md` som täcker: ansvarig och kontaktuppgifter, kategorier av uppgifter, ändamål, rättslig grund, mottagare (AI-backend, Garmin, Strava, Withings, Fitbit, Whoop, väder- och geotjänster – se `LEG-5`), lagringstider (`LEG-11`), rättigheter enligt art. 15–22, och rätten att klaga till IMY.
  2. Gör den läsbar i appen – egen vy eller modal, länkad från registreringen och från footern.
  3. Uppdatera README:s avsnitt *Privacy & Data Security*, som i dag innehåller påståenden som inte stämmer för webbläget (se `LEG-6` punkt 3).
- **Acceptanskriterier:**
  1. `PRIVACY.md` finns och täcker samtliga punkter i art. 13.
  2. Policyn är åtkomlig från registreringsflödet innan kontot skapas.
  3. Inga påståenden i README eller policy som motsägs av koden.

---

### [ ] LEG-3: Ingen registerutdrags- eller dataportabilitetsfunktion (art. 15 och 20)
- **Fil:** [server.py](server.py) – ny endpoint, [static/app.js](static/app.js) – knapp i profilvyn
- **Kräver ägarbeslut:** nej – ren implementation.
- **Problem:** Användaren kan radera sitt konto men inte **få ut** sina uppgifter. Art. 15 ger rätt till en kopia, art. 20 rätt till ett maskinläsbart, allmänt använt format.
- **Åtgärd:**
  1. Bygg `GET /api/user/export` som dekrypterar användarens samtliga tabeller med sessionens DEK och returnerar en JSON-fil: profil, `daily_summary`, `sleep_data`, `body_battery`, `stress_data`, `hrv_data`, `activities`, `body_composition`, `calorie_burn`, kopplade datakällor (**utan** tokens och hemligheter – återanvänd `SECRET_FIELDS`-filtret från `datasource_store`) samt samtyckeshistorik från `LEG-1`.
  2. Lägg en "Ladda ner mina uppgifter"-knapp i profilvyn.
  3. Endpointen ska vara scopad på `session.user_id` – aldrig ta ett `user_id` från klienten.
- **Acceptanskriterier:**
  1. Exporten innehåller alla användarens hälsodatatabeller i dekrypterad, läsbar JSON.
  2. Exporten innehåller **inga** tokens, klienthemligheter eller lösenord.
  3. Användare A kan inte exportera användare B:s uppgifter.
  4. Test som täcker punkt 1–3.

---

### [ ] LEG-4: Raderingen är ofullständig (art. 17)
- **Fil:** [auth.py](auth.py) (`delete_user_account`), [server.py](server.py) (`delete_account`), [withings_handler.py](withings_handler.py)
- **Kräver ägarbeslut:** nej.
- **Problem:** Databasdelen är välbyggd – `ON DELETE CASCADE` på samtliga hälsotabeller plus explicit rensning av `user_sessions` och `user_datasources`. Tre saker överlever ändå raderingen:
  1. **Chatthistoriken i serverns RAM** – `_user_chat_histories` rensas inte (`S-22`).
  2. **Chatthistoriken i webbläsarens `localStorage`** – rensas inte (`UI-3`).
  3. **Withings-tokens i serverns globala keyring** – skrivs utanför kuvertet och rensas inte (`S-19`). `S-16` löste motsvarande problem för `KEYRING_SERVICE_NAME`, men inte för datakällornas poster.
  Dessutom: raderingen av `user_datasources` i `delete_user_account` ligger i ett `try/except: pass`-block. Misslyckas den fortsätter koden tyst, och OAuth-tokens till tredjepartskonton blir kvar.
- **Åtgärd:**
  1. Åtgärda `S-19`, `S-22` och `UI-3` – de är förutsättningar för den här punkten.
  2. Rensa datakällornas keyring-poster i `delete_user_account`, på samma sätt som `S-16` gör för sessionsposten.
  3. Ta bort `except: pass` runt raderingen av `user_datasources`; låt den fela högt, eller logga på `error`-nivå och rulla tillbaka transaktionen.
  4. Dokumentera i `PRIVACY.md` vad radering faktiskt omfattar och inom vilken tid.
- **Acceptanskriterier:**
  1. Efter kontoradering finns inga spår i databasen, i processminnet, i webbläsaren eller i serverns keyring.
  2. Ett integrationstest som skapar konto, synkar, chattar, raderar och därefter hävdar punkt 1 för varje lagringsplats.
  3. Ett fel vid radering av `user_datasources` går inte obemärkt förbi.

---

### [ ] LEG-5: Inga biträdesavtal och odokumenterad tredjelandsöverföring (art. 28 och kap. V)
- **Fil:** [server.py](server.py) (`get_weather`, `chat_stream`), [datasource_store.py](datasource_store.py) (`PROVIDERS`)
- **Kräver ägarbeslut:** ja – avtal måste tecknas av ägaren.
- **Problem:** Appen skickar personuppgifter till minst åtta externa mottagare utan dokumenterade biträdesavtal eller överföringsbedömning:
  - **AI-backend** (`chat_stream`) – tar emot ålder, vikt, BMI, midjemått, vilopuls, HRV, sömn och **kända skador**. Detta är den känsligaste överföringen i hela appen. Körs backenden lokalt (Ollama på egen hårdvara) är det ingen tredjepartsöverföring alls – men det måste **dokumenteras**, och `TLS-7` visar att adressen i dag kan bli fel.
  - **`ip-api.com`** (över HTTP, se `TLS-8`), **`api.bigdatacloud.net`**, **`api.open-meteo.com`** – tar emot koordinater, vilket är personuppgifter.
  - **Garmin, Strava, Withings, Fitbit, Whoop** – här är användaren normalt själv avtalspart, men rollfördelningen behöver beskrivas.
- **Åtgärd:**
  1. Kartlägg varje utgående anrop och vilken uppgiftskategori det bär. Använd tabellen i avsnittet *Transportkryptering* som mall.
  2. Fastställ för varje mottagare: biträde eller självständigt ansvarig, var behandlingen sker geografiskt, och vilken överföringsmekanism som gäller vid tredjelandsöverföring.
  3. Teckna biträdesavtal där det behövs. Går det inte – byt eller ta bort tjänsten. Väderfunktionen är inte affärskritisk och kan tas bort om avtalen blir en börda.
  4. Dokumentera AI-backendens placering och ägarskap uttryckligen.
- **Acceptanskriterier:**
  1. En fullständig mottagartabell finns i `PRIVACY.md` och i registerförteckningen (`LEG-6`).
  2. Varje mottagare har antingen ett avtal eller ett dokumenterat beslut om varför inget behövs.
  3. Inga odokumenterade utgående anrop kvar – verifierat genom kodgenomgång.

---

### [ ] LEG-6: Ingen registerförteckning (art. 30) och README beskriver säkerheten för starkt
- **Fil:** ny `COMPLIANCE.md`, [README.md](README.md)
- **Kräver ägarbeslut:** delvis.
- **Problem:**
  1. Ingen registerförteckning finns. Art. 30 kräver den i praktiken så fort art. 9-uppgifter behandlas, oavsett organisationens storlek (undantaget i art. 30.5 gäller inte).
  2. README:s avsnitt *Privacy & Data Security* påstår saker som inte stämmer för webbläget: "Zero-Knowledge Architecture", "No Telemetry", "All data processing happens locally on your machine". Verkligheten: **e-postadresser lagras i klartext**, och metadata är okrypterad – vilka datum det finns hälsodata, vilka tjänster som kopplats (`connected`), när senaste synk skedde och hur många poster den gav. Det är ett rimligt designval, men "zero-knowledge" är för starkt och måste nyanseras. Chatthistoriken ligger dessutom i klartext i RAM (`S-22`) och i webbläsaren (`UI-3`).
- **Åtgärd:**
  1. Skapa `COMPLIANCE.md` med registerförteckning enligt art. 30.1: ändamål, kategorier av registrerade och uppgifter, mottagare, tredjelandsöverföringar, gallringsfrister, och en allmän beskrivning av säkerhetsåtgärderna.
  2. Skriv om README:s säkerhetsavsnitt så att det stämmer med koden. Beskriv exakt vad som är krypterat och vad som **inte** är det.
  3. Skilj tydligt på desktopläget (allt lokalt) och webbläget (server med flera användare) – README blandar i dag ihop dem.
- **Acceptanskriterier:**
  1. `COMPLIANCE.md` täcker samtliga punkter i art. 30.1.
  2. Inget påstående i README motsägs av koden – särskilt inte om kryptering, telemetri eller var data behandlas.
  3. Metadatan som ligger okrypterad är uttryckligen uppräknad.

---

### [ ] LEG-7: Ingen konsekvensbedömning (DPIA) trots att den är obligatorisk
- **Fil:** ny `DPIA.md`
- **Kräver ägarbeslut:** ja – ägaren äger bedömningen och slutsatsen.
- **Problem:** Art. 35.3 b utlöser DPIA-krav vid behandling i stor omfattning av art. 9-uppgifter. Appen behandlar hälsodata kontinuerligt från flera källor och kör automatiserad profilering genom AI-analysen. IMY:s förteckning över behandlingar som kräver DPIA omfattar uttryckligen storskalig behandling av hälsouppgifter. Ingen bedömning finns.
- **Åtgärd:**
  1. Skriv `DPIA.md` med: systematisk beskrivning av behandlingen, nödvändighet och proportionalitet, riskbedömning för den registrerade, och de skyddsåtgärder som finns.
  2. Riskavsnittet ska bygga på de konkreta fynden i den här filen – `S-18` … `S-27`, `TLS-1`, `TLS-7`, `TLS-8`, `UI-3`, `UI-4` – med restrisk efter åtgärd.
  3. Dokumentera kryptoarkitekturen som skyddsåtgärd (envelope-modellen är genuint stark och hör hemma här), tillsammans med dess **gränser**: nycklarna i RAM, metadata i klartext, e-post i klartext.
  4. Nå tröskeln för förhandssamråd med IMY (art. 36)? Bedöm och dokumentera slutsatsen.
- **Acceptanskriterier:**
  1. `DPIA.md` finns och täcker alla fyra delarna i art. 35.7.
  2. Varje öppen säkerhetspunkt i den här filen är representerad i riskavsnittet.
  3. DPIA:n är daterad, versionshanterad och har en namngiven ansvarig.

---

### [ ] LEG-8: Ingen incidenthanteringsrutin (art. 33/34)
- **Fil:** ny `INCIDENT_RESPONSE.md`
- **Kräver ägarbeslut:** ja – kontaktvägar och ansvar.
- **Problem:** Vid en personuppgiftsincident gäller 72 timmars anmälningsplikt till IMY, och vid hög risk även information till de registrerade. Det finns ingen rutin, ingen kontaktväg och inga loggar som är dimensionerade för att utreda omfattningen av ett intrång.
- **Åtgärd:**
  1. Skriv `INCIDENT_RESPONSE.md`: vem som larmas, hur omfattningen utreds, mall för anmälan till IMY, kriterier för att informera registrerade.
  2. Inför säkerhetsloggning som faktiskt går att utreda: lyckade och misslyckade inloggningar, sessionsskapande, datakällskopplingar, exporter och raderingar – **utan** att logga personuppgifter i klartext. `mask_email` finns redan och används korrekt; använd samma mönster genomgående.
  3. Sätt en gallringsfrist på säkerhetsloggarna och skriv in den i `LEG-11`.
- **Acceptanskriterier:**
  1. Rutinen finns och namnger en ansvarig.
  2. Säkerhetshändelserna ovan loggas med tillräcklig detalj för att avgränsa ett intrång.
  3. Inga personuppgifter i klartext i loggarna – verifierat med test.

---

### [ ] LEG-9: Ingen MDR-kvalificeringsbedömning och ingen medicinsk ansvarsfriskrivning
- **Fil:** [ai_client.py](ai_client.py) (`get_default_system_prompt`), [server.py](server.py) (`chat_stream`, skade- och målblocken), [static/index.html](static/index.html), ny `MDR_ASSESSMENT.md`
- **Kräver ägarbeslut:** ja – kvalificeringsbeslutet.
- **Problem:** Systemprompten positionerar AI:n som "professionell personlig tränare och hälsocoach" som ger "tränings- och hälsoråd". `chat_stream` injicerar dessutom:
  > "VIKTIGT OM SKADOR & TRÄNINGSPASS: ... Du MÅSTE ta särskild hänsyn till detta vid ALLA tränings-, pass- och övningsrekommendationer! Föreslå skonsamma alternativ, anpassa intensitet/volym och varna uttryckligen för övningar eller rörelser som kan belasta det skadade området negativt."
  Ren fitness och wellness faller normalt **utanför** MDR 2017/745. Men rådgivning som uttryckligen anpassas efter användarens **skador och fysiska begränsningar** ligger i gränslandet mot art. 2.1 och Regel 11 i bilaga VIII (se MDCG 2019-11). Appen beräknar dessutom egna härledda hälsomått – sleep score och HRV-status.
  Detta är **inte** ett påstående om att appen är en medicinteknisk produkt. Bristen är att **ingen bedömning är gjord och dokumenterad**, och att det saknas ansvarsfriskrivning helt: noll träffar på `läkare|vårdcentral|medicinsk|ersätter inte|sjukvård` i `static/index.html` och `static/app.js`. Systemprompten säger heller aldrig åt modellen att avstå från diagnos eller hänvisa till vården.
- **Åtgärd:**
  1. Ägaren gör och dokumenterar en kvalificeringsbedömning i `MDR_ASSESSMENT.md`, med MDCG 2019-11 som stöd. Slutsatsen "inte en medicinteknisk produkt" är fullt rimlig – men den ska vara skriven, motiverad och daterad.
  2. Lägg en tydlig ansvarsfriskrivning i gränssnittet: synlig i chattvyn, inte bara i en policy. "Råden är av allmän träningskaraktär och ersätter inte medicinsk bedömning. Kontakta vården vid symtom, smärta eller skada."
  3. Utöka systemprompten med en instruktion om att inte ställa diagnos, inte tolka symtom och att hänvisa till vårdpersonal vid tecken på skada eller sjukdom.
  4. Väger bedömningen åt medicinteknik: pausa skadeanpassningsfunktionen tills CE-frågan är utredd. Det är den enskilda funktion som driver gränsdragningen.
- **Acceptanskriterier:**
  1. `MDR_ASSESSMENT.md` finns, är daterad och har en motiverad slutsats.
  2. Ansvarsfriskrivningen är synlig i chattvyn vid varje session.
  3. Systemprompten innehåller instruktionen om diagnos och hänvisning – verifierat med test mot `get_default_system_prompt`.

---

### [ ] LEG-10: `localStorage`-lagringen av chatthistorik kräver samtycke (ePrivacy / LEK 9 kap. 28 §)
- **Fil:** [static/app.js](static/app.js) (`getChatStorageKey`, `saveChatHistory`)
- **Kräver ägarbeslut:** nej.
- **Problem:** Lagring av uppgifter i användarens terminalutrustning kräver samtycke om den inte är **strikt nödvändig** för den begärda tjänsten. Sessionstoken är undantagen – den är nödvändig. Chatthistoriken i `localStorage` är det inte: den är en bekvämlighet, och konversationen finns redan på servern (`_user_chat_histories`). Den innehåller dessutom art. 9-uppgifter och överlever utloggning (`UI-3`).
- **Åtgärd:**
  1. Enklast och bäst: ta bort `localStorage`-lagringen helt och läs historiken från `/api/ai/chat/history`. Löser `UI-3` och den här punkten på en gång.
  2. Behålls den: koppla den till samtyckessteget i `LEG-1` och rensa vid utloggning.
- **Acceptanskriterier:**
  1. Ingen lagring i `localStorage` utan samtycke, eller ingen `localStorage`-lagring alls.
  2. Sessionstoken-hanteringen påverkas inte (den är undantagen) – men se `S-20`, den ska ändå bort ur `sessionStorage`.

---

### [ ] LEG-11: Ingen gallringsfrist och Strava hämtar tio år som standard (art. 5.1 c och 5.1 e)
- **Fil:** [datasource_store.py](datasource_store.py) (`PROVIDERS["strava"]["sync_days"] = 3650`), [withings_handler.py](withings_handler.py) (`fetch_measurements`, grenen `days >= 3650 → lastupdate = 0`), [garmin_db.py](garmin_db.py)
- **Kräver ägarbeslut:** delvis – fristerna ska fastställas av ägaren.
- **Problem:** Två sidor av samma sak:
  1. **Ingen lagringstid alls.** Hälsodata sparas tills användaren raderar kontot. Art. 5.1 e kräver att uppgifter inte sparas längre än nödvändigt, och art. 13.2 a att lagringstiden **anges** för den registrerade.
  2. **Strava hämtar 3650 dagar** (tio år) som standard, och Withings hämtar hela livstidshistoriken när `days >= 3650`. Det kan vara motiverat för trendanalys – men det ska vara ett **medvetet, dokumenterat** val, inte en default.
- **Åtgärd:**
  1. Ägaren fastställer gallringsfrister per datakategori och skriver in dem i `PRIVACY.md` och `COMPLIANCE.md`.
  2. Bygg ett gallringsjobb som raderar hälsodata äldre än fristen. Det kan köras vid inloggning, på samma sätt som `cleanup_expired_sessions`.
  3. Motivera tioårshämtningen, eller sänk den. Gör den i så fall till ett val användaren gör medvetet vid första synken.
  4. Sätt en frist även för säkerhetsloggarna från `LEG-8`.
- **Acceptanskriterier:**
  1. Lagringstiderna är dokumenterade och synliga för användaren.
  2. Ett gallringsjobb finns och raderar data äldre än fristen – med test.
  3. Historikdjupet vid första synk är antingen sänkt eller dokumenterat motiverat.

---

## 🌍 Flerspråkighet – svenska, engelska och polska

> Genomgång 2026-09-19. Kartlägger vad som krävs för att köra HealthChat på **svenska (`sv`),
> engelska (`en`) och polska (`pl`)**.
>
> **Nuläget:** ingen i18n-infrastruktur finns. Sökning på `Accept-Language|gettext|i18n|babel|locale`
> i `server.py`, `auth.py` och `static/app.js` ger noll träffar, och `<html lang="sv">` är hårdkodat.
> Allt byggs från grunden – men det finns heller inget halvfärdigt som står i vägen.
>
> **Uppmätt omfattning:**
>
> | Lager | Strängar | Ord |
> |---|---|---|
> | `static/index.html` | 327 | ~1 769 |
> | `static/app.js` | 232 | ~1 597 |
> | Backend (6 filer) | 171 | ~1 164 |
> | AI-systemprompt | 1 block | ~450 |
> | **Totalt per språk** | **~730** | **~4 980** |
>
> Två nya språk ≈ **10 000 ord översättning** plus mekanik.
>
> **Tyngdpunkten ligger inte i UI:t utan i AI-prompten** – se `I18N-10`, som är den enda uppgiften
> med genuint osäker insats. Läs den innan ni utlovar polskt stöd.

---

### [ ] I18N-1: Avdubblera strängarna och inför felkoder innan något översätts
- **Fil:** [server.py](server.py) (`_get_wmo_code_info`, `_evaluate_weather_advice`, samtliga `HTTPException(detail=...)`), [static/app.js](static/app.js) (`getWeatherCodeDescription`), [auth.py](auth.py) (`raise ValueError("...")`)
- **Förutsättning för:** `I18N-3`, `I18N-4`, `I18N-8`, `I18N-9`. **Gör den först.**
- **Problem:** Två mönster gör att en naiv översättning ger dubbelarbete och drift:
  1. **Väderbeskrivningarna är implementerade parallellt** i backend och frontend. Samma sträng, två ställen:
     ```python
     # server.py – _get_wmo_code_info()
     if c == 0: return "Klart & soligt", "☀️"
     ```
     ```javascript
     // static/app.js – getWeatherCodeDescription()  (24 case-grenar)
     case 0: return { desc: "Klart & soligt", icon: "☀️" };
     ```
     Översätts de var för sig får man två kataloger som glider isär.
  2. **Felmeddelanden reser genom tre lager.** `auth.py` kastar `ValueError("Fel e-postadress eller lösenord.")`, `server.py` skickar vidare texten som `detail`, `app.js` visar den rått i en `alert()`. Backend äger alltså formuleringar som bara frontend kan lokalisera.
- **Åtgärd:**
  1. Ta bort väderbeskrivningarna ur **backend**. Låt `/api/weather` returnera `weather_code` (WMO-koden finns redan) och låt frontend äga texten. `summaryText` som skickas till AI-kontexten byggs då också i frontend, eller genereras på det språk användaren valt (se `I18N-6`).
  2. Inför **felkoder** i backend: `HTTPException(detail={"code": "AUTH_INVALID_CREDENTIALS"})` i stället för svensk text. Frontend slår upp koden i sin katalog.
  3. Samma för `auth.py`: låt undantagen bära en kod, inte en formulering.
  4. Bevara bakåtkompatibilitet under övergången genom att skicka både `code` och en engelsk `detail` som fallback.
- **Synergi:** Detta löser samtidigt `S-23` – en felkod kan inte läcka anslutningssträngar eller tokens, till skillnad från `str(e)`. Gör uppgifterna tillsammans.
- **Acceptanskriterier:**
  1. Väderbeskrivningar finns på exakt ett ställe i kodbasen.
  2. Inget API-svar innehåller en svensk mening avsedd att visas för användaren.
  3. Frontend renderar korrekt svensk text för alla tidigare felfall.
  4. Test som hävdar att `/api/weather` returnerar `weather_code` och ingen `weatherDesc`-sträng.

---

### [ ] I18N-2: Bygg i18n-mekaniken – katalogformat, `t()` och `lang`-attribut
- **Fil:** nya `static/i18n/sv.json`, `static/i18n/en.json`, `static/i18n/pl.json`, [static/app.js](static/app.js), [static/index.html](static/index.html)
- **Problem:** Det finns ingen uppslagsmekanism och ingen katalog. `<html lang="sv">` är hårdkodat.
- **Åtgärd:**
  1. Välj **enkla JSON-kataloger + en `t(key, params)`-funktion i `app.js`**. Motivering: ingen byggkedja, inget nytt beroende, läsbara git-diffar. Backend behöver inga kataloger alls efter `I18N-1` – bara felkoder.
  2. Nyckelschema: `omrade.underomrade.nyckel`, t.ex. `dashboard.recovery.title`, `error.auth.invalid_credentials`, `datasource.strava.step.1`. Platt struktur med punktnotation, inte djup nästling.
  3. `t()` ska stödja interpolation (`t('sleep.hours', {h: 7.5})`) och falla tillbaka på `en` vid saknad nyckel, med en `console.warn` i utvecklingsläge.
  4. Välj ett format som stöder **pluralregler** från start, även om behovet i dag är litet (se `I18N-4` punkt 3) – det är dyrt att byta format senare.
  5. Sätt `<html lang>` dynamiskt från det valda språket.
  6. Lägg till ett testskript som verifierar att alla tre katalogerna har **identiska nyckeluppsättningar**.
- **Acceptanskriterier:**
  1. `t('nagon.nyckel')` returnerar rätt sträng för aktuellt språk.
  2. En saknad nyckel faller tillbaka på engelska och varnar, i stället för att rendera `undefined`.
  3. Katalogerna har identiska nyckeluppsättningar – verifierat av test.
  4. `<html lang>` speglar valt språk.

---

### [ ] I18N-3: Extrahera strängarna ur `index.html` (~327 strängar, ~1 769 ord)
- **Fil:** [static/index.html](static/index.html)
- **Problem:** All UI-text ligger som markup. Fördelningen: **135 textnoder**, **71 attribut** (`placeholder`, `title`, `alt`, `aria-label`) och **49 `chart-info-popover`-block** med förklarande brödtext. Popoverna är den stora volymen – varje innehåller två stycken domäntung prosa:
  > "Din återhämtningsnivå och dagsform (0–100 %) baserad på Garmin Body Battery, vilopuls, HRV och sömnkvalitet."
  > "75–100 % = Mycket god återhämtning, redo för tuffa pass; 45–74 % = God form för distansträning …"
- **Åtgärd:**
  1. Märk textnoder med `data-i18n="nyckel"` och attribut med `data-i18n-attr="placeholder:nyckel"`.
  2. Kör en genomgång vid sidladdning som fyller i alla märkta element.
  3. Popover-texterna är **facktext, inte UI-chrome**. De ska översättas av någon som förstår träningsfysiologi – markera dem i katalogen (t.ex. nyckelprefixet `info.`) så att de kan hanteras separat från knappar och etiketter.
  4. Behåll emoji och enheter (`%`, `kg`, `bpm`, `kcal`) utanför de översatta strängarna där det går, så att de inte förvanskas.
- **Acceptanskriterier:**
  1. `grep -c "[åäöÅÄÖ]" static/index.html` ger 0 träffar utanför den svenska katalogen.
  2. Alla 49 popovers renderar korrekt på valt språk.
  3. Inga tomma eller `undefined`-element vid språkbyte.

---

### [ ] I18N-4: Extrahera strängarna ur `app.js` (~232 strängar, ~1 597 ord)
- **Fil:** [static/app.js](static/app.js)
- **Problem:** Strängarna sitter i mallsträngar, `alert()`-anrop (**18 stycken**) och statusmeddelanden (`'🔄 Uppdatera'`, `'⏳ Synkar datakällor...'`, `'⚠️ Fel vid uppdatering'`).
- **Åtgärd:**
  1. Ersätt varje användarvänd sträng med `t()`.
  2. Byt ut `alert()`/`confirm()` mot en egen dialogkomponent i samma veva – 18 råa `alert()` är ändå ett UX-problem, och de visar i dag `detail`-texten rakt från servern (se `I18N-1`).
  3. **Pluralformer:** i dag används hårdkodade former på bara en handfull ställen (`} steg`, `} st`, `8 timmar`). Polska har tre pluralformer (`1 dzień` / `2–4 dni` / `5+ dni`), så skriv om dessa med katalogens pluralstöd i stället för strängkonkatenering. Antalet är litet – utnyttja det nu, innan det växer.
  4. Chatthistoriken lagras per användare och kan innehålla svar på ett tidigare valt språk. Bestäm om språkbyte ska rensa historiken eller bara påverka nya svar, och dokumentera valet. Se `S-22` och `UI-3`.
- **Acceptanskriterier:**
  1. Inga svenska strängliteraler kvar i `app.js` utanför katalogen.
  2. Räkneord med enheter renderar grammatiskt korrekt på polska för 1, 2, 5 och 22.
  3. Inga `alert()` som visar serverns `detail` ordagrant.

---

### [ ] I18N-5: Lokalisera siffror – rättar en befintlig bugg i den svenska versionen
- **Fil:** [static/app.js](static/app.js) (`formatNumber`, samt 24 anrop till `toFixed()`)
- **Status:** 🐛 **Detta är en befintlig bugg, inte bara i18n-arbete.**
- **Problem:** Tusentalsavgränsaren är mellanslag, vilket är korrekt för svenska och polska men fel för engelska:
  ```javascript
  function formatNumber(num) {
    return Math.round(num).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }
  ```
  Värre: `toFixed()` används på **24 ställen** och ger alltid punkt som decimaltecken. **Appen visar alltså engelsk decimalnotation i ett svenskt gränssnitt redan i dag:**

  | | Visas nu | Korrekt `sv` | Korrekt `pl` | Korrekt `en` |
  |---|---|---|---|---|
  | Tempo | `5.51` | `5,51` | `5,51` | `5.51` |
  | Vikt | `78.4 kg` | `78,4 kg` | `78,4 kg` | `78.4 kg` |
- **Åtgärd:**
  1. Ersätt `formatNumber` med `Intl.NumberFormat(locale)`.
  2. Gå igenom alla 24 `toFixed()`-anrop och formatera via `Intl.NumberFormat(locale, { minimumFractionDigits, maximumFractionDigits })`.
  3. **Rör inte** datumformateringen. Alla datum är ISO (`YYYY-MM-DD` via `.slice(0, 10)`, och `MM-DD` / `YYYY-MM` i graferna). ISO är entydigt och fungerar i alla tre språken – det här är en av få saker som redan är rätt.
  4. Kontrollera att Chart.js axeletiketter följer med.
- **Acceptanskriterier:**
  1. Svensk och polsk vy visar `5,51`; engelsk visar `5.51`.
  2. Tusentalsavgränsare följer valt språk.
  3. Datumvisningen är oförändrad.
  4. Test som låser formateringen per språk.

---

### [ ] I18N-6: Språkval – två mekanismer krävs, profilen räcker inte
- **Fil:** [server.py](server.py) (`ProfileUpdateRequest`, `_callback_page`, auth-endpoints), [static/app.js](static/app.js), [static/index.html](static/index.html)
- **Problem:** Profilen är en krypterad JSON-blob, så att lägga till `language` kräver **ingen schemamigrering** – arkitektoniskt gratis. Men profilen kan bara läsas **efter** inloggning, när DEK:en finns i minnet. Följande sker före eller utanför det:
  - inloggnings- och registreringsvyn
  - felmeddelanden vid misslyckad inloggning (`auth.py`)
  - OAuth-callbacksidan (`_callback_page` renderar svensk HTML direkt)
  - kontoåterställningsflödet
  Ett språkval som bara bor i profilen ger alltså svenska inloggningsskärmar för en polsk användare.
- **Åtgärd:**
  1. **Före inloggning:** läs `Accept-Language`, och låt ett explicit val skrivas till en `lang`-cookie (`SameSite=Lax`, ingen känslig data – den behöver inte `HttpOnly` eftersom frontend måste läsa den).
  2. **Efter inloggning:** `language` i `encrypted_profile` är auktoritativ och skriver över cookien. Lägg till fältet i `ProfileUpdateRequest`.
  3. Lägg en språkväljare i både auth-vyn och profilvyn.
  4. `_callback_page` måste rendera på valt språk – den har ingen session att läsa från, så den får använda cookien.
  5. Validera `language` mot `{"sv", "en", "pl"}`; avvisa okända värden (se `Q-11`).
- **Acceptanskriterier:**
  1. En webbläsare med `Accept-Language: pl` får polsk inloggningsskärm utan att vara inloggad.
  2. Ett sparat profilspråk vinner över `Accept-Language` efter inloggning.
  3. OAuth-callbacksidan renderar på valt språk.
  4. Ett ogiltigt språkvärde avvisas med 422.

---

### [ ] I18N-7: Översätt datakällornas onboarding-instruktioner – utan att översätta portaltermerna
- **Fil:** [datasource_store.py](datasource_store.py) (`PROVIDERS` – fälten `description`, `portal_label`, `steps`, `sync_label`)
- **Problem:** Fem leverantörer × beskrivning + portaletikett + 4–5 `steps` = ~45 svenska strängar som hänvisar till engelska begrepp i respektive utvecklarportal:
  > `"Skapa (eller öppna) din API-applikation under \"My API Application\"."`
  > `"Application Type: Personal och Default Access Type: Read-Only räcker."`
  De citerade engelska termerna är **vad användaren faktiskt ser på Stravas respektive Fitbits sajt** och får inte översättas – bara den omgivande meningen. Maskinöversättning kommer att översätta dem och göra instruktionerna obrukbara.
- **Åtgärd:**
  1. Flytta `description`, `portal_label`, `steps` och `sync_label` ur `PROVIDERS` till i18n-katalogen, med nycklar som `datasource.strava.step.2`. `PROVIDERS` behåller enbart teknisk metadata (`auth_kind`, `portal_url`, `sync_days`, färg, ikon).
  2. Markera i katalogen vilka termer som ska stå kvar oöversatta, t.ex. genom att hålla dem utanför den översättbara strängen: `"…under {term}"` med `term: "My API Application"`.
  3. Låt `public_status` returnera nycklar i stället för text, så att frontend slår upp dem.
- **Acceptanskriterier:**
  1. Instruktionerna renderar på valt språk med bevarade engelska portaltermer.
  2. `PROVIDERS` innehåller ingen användarvänd text.
  3. En polsk användare kan följa stegen och faktiskt hitta rätt fält i Stravas portal.

---

### [ ] I18N-8: Engelsk katalog och engelsk AI-prompt – gör detta språk först
- **Fil:** `static/i18n/en.json`, [ai_client.py](ai_client.py) (`get_default_system_prompt`)
- **Problem / möjlighet:** Engelska validerar hela mekaniken från `I18N-2` … `I18N-7` till låg kostnad, och **AI-sidan är nästan gratis**. Systemprompten är 3 396 tecken / 44 rader, varav ungefär **en tredjedel är ren svensk språkreparation**:
  > `2. Förbjudna felöversättningar och påhittade ord (använd ALDRIG dessa):`
  > `   - Skriv "Sömnpoäng" (ALDRIG "sömnskore" eller "sovvakt").`
  > `   - Skriv "Dricka ordentligt" (ALDRIG "hålla dig hyddrad" eller "dricka tillflöde").`
  > `5. SVENSKA SAMMANSATTA ORD (UNDVIK SÄRSKRIVNINGAR)`
  Dessa regler finns bara för att `gemma4:12b` producerar dålig svenska. På engelska – modellens starkaste språk – behövs de inte alls och kan **strykas helt**.
- **Åtgärd:**
  1. Översätt katalogen till engelska (~4 980 ord). Detta är referensspråket som `t()` faller tillbaka på.
  2. Gör `get_default_system_prompt` språkparametriserad: `get_default_system_prompt(lang)`. Skicka användarens språk från `chat_stream`.
  3. Skriv den engelska prompten som en **ren** variant – behåll de språkneutrala reglerna (struktur, rubriker, skadehänsyn, målhänsyn, väderhänsyn) och stryk sektion 2 och 5.
  4. Rubrikerna i sektion 6 (`### Analys & Bedömning` osv.) syns i AI-svaret och måste översättas konsekvent med katalogen.
- **Acceptanskriterier:**
  1. Hela gränssnittet renderar på engelska utan saknade nycklar.
  2. `get_default_system_prompt("en")` innehåller inga svenska språkregler.
  3. AI-svar på engelska följer den begärda rubrikstrukturen.
  4. Test som hävdar att prompten byts med språkvalet.

---

### [ ] I18N-9: Polsk katalog
- **Fil:** `static/i18n/pl.json`
- **Problem:** ~4 980 ord, varav de 49 popover-texterna från `I18N-3` är facktext om träningsfysiologi.
- **Vad som redan är löst:**
  - **Teckenkodning.** `utf8mb4_unicode_ci` hanterar ł, ż, ź, ć, ń, ś, ą, ę. Hälsodata är dessutom krypterad, så kollationen spelar bara roll för e-postadresser.
  - **Datumformat.** ISO överallt – ingen åtgärd (se `I18N-5` punkt 3).
  - **Enheter.** Metriskt, gemensamt för alla tre språken.
  - **Pluralformer.** Få förekomster, hanteras i `I18N-4`.
- **Åtgärd:**
  1. Översätt katalogen. Popover-texterna kräver någon som förstår domänen – inte enbart maskinöversättning.
  2. **Låt en polsk modersmålstalare korrekturläsa**, särskilt facktexterna.
  3. **Kontrollera layouten.** Polska blir typiskt 10–20 % längre än engelska. Granska knappar och kortrubriker i [static/styles.css](static/styles.css), särskilt de fyra korten som enligt commit-historiken tvingats ligga "strikt på samma rad" – de har ingen marginal.
- **Acceptanskriterier:**
  1. Hela gränssnittet renderar på polska utan saknade nycklar.
  2. Ingen text som bryter layouten vid 1280 px och vid mobilbredd.
  3. Korrekturläsning av modersmålstalare genomförd och noterad här.

---

### [ ] I18N-10: Polsk AI-prompt – den enda uppgiften med osäker insats
- **Fil:** [ai_client.py](ai_client.py) (`get_default_system_prompt`), [server.py](server.py) (`chat_stream`)
- **⚠️ Läs denna innan ni utlovar polskt stöd.**
- **Problem:** De svenska språkreparationsreglerna i prompten går **inte att översätta**. De är empiriskt framtagna lappar för vad `gemma4:12b` råkar hitta på just på svenska – "sömnskore", "sovvakt", "hålla dig hyddrad". Inget av det betyder något på polska. För polska måste man köra modellen, samla in vad den faktiskt gör fel, och skriva nya regler. Det är ett **iterativt utvärderingsarbete, inte en översättning**.
  Polska är dessutom morfologiskt betydligt svårare än svenska – sju kasus, tre genus, aspektsystem. Sannolikheten att en 12B-modell producerar godtagbar polska i en tränings- och hälsokontext är påtagligt lägre än för svenska, och långt lägre än för engelska.
  **Detta är inte enbart ett kvalitetsproblem.** `chat_stream` injicerar användarens `injuries` och instruerar modellen att varna för rörelser som kan belasta det skadade området. Dålig polska i en skadeanpassad träningsrekommendation är ett säkerhetsproblem, inte ett kosmetiskt. Se `LEG-9`.
- **Åtgärd:**
  1. **Utvärdera först.** Kör ett tjugotal verkliga frågor på polska mot den konfigurerade modellen, med realistisk hälsokontext inklusive skador. Dokumentera resultatet här.
  2. Skriv den polska prompten utifrån vad utvärderingen visar – inte utifrån den svenska.
  3. **Blir kvaliteten otillräcklig, släpp inte polska AI-svar.** Alternativ, i fallande ordning: (a) använd en större modell enbart för polska, (b) behåll polskt gränssnitt men engelska AI-svar och var uttrycklig om det i UI:t, (c) skjut upp polskt AI-stöd.
  4. Beslutet dokumenteras här oavsett utfall.
- **Acceptanskriterier:**
  1. En dokumenterad utvärdering finns med konkreta exempel på modellens polska utdata.
  2. Ett medvetet beslut om (a), (b) eller (c) är fattat och nedskrivet.
  3. Väljs (b): gränssnittet säger tydligt att AI-svaren är på engelska.
  4. Släpps polska AI-svar: skadeanpassade rekommendationer är granskade av en polsktalande person.

---

## Avfärdat (verifierat som icke-buggar)

### Verifierat i genomgången 2026-09-19

- **XSS i renderad AI-text** – `renderMarkdown` anropar `escapeHtml` **före** markdown-omvandlingen och
  bygger först därefter `<strong>`/`<em>`/`<h3>`. Ordningen är rätt; ingen injektionsväg. `UI-2` håller
  även i aktivitets- och pulszonstabellerna.
- **SQL-injektion (omprövat)** – f-strängarna i `datasource_store.py`, `auth.py` och `server.py`
  interpolerar enbart platshållartecknet (`%s`/`?`) och tabellnamn från modulkonstanter. Alla värden
  binds som parametrar.
- **IDOR i datalagret** – samtliga MariaDB-frågor i `garmin_db.py` filtrerar på `user_id`. De frågor
  som saknar det ligger uteslutande i SQLite-grenen, som inte kan nås i webbläge efter `S-14`.
- **`public_status` läcker inga hemligheter** – returnerar `secret_set`/`has_credentials` som
  booleaner och exponerar aldrig `client_secret`, `password` eller tokens. `SECRET_FIELDS` är korrekt
  definierad.
- **OAuth-`state`** – jämförs med `secrets.compare_digest` i `compare_oauth_state`, PKCE-verifieraren
  lagras per användare och rensas efter utbytet. Callbacken kräver en giltig session.
- **`get_db_conn`:s SQLite-fallback är inte exploaterbar** – med `require_mariadb=True` sätts aldrig
  `db_path`, så `sqlite3.connect(None)` kastar och fångas. Den är däremot bräcklig och städas i `Q-13`.
- **Testsvitens 9 fel är miljöberoende** – samtliga beror på att MariaDB saknas (`503`), inklusive
  `test_web_security.py::test_cookie_secure_flag_*`. Inga defekter.

- **`crypto.py`** – AES-256-GCM med färsk nonce per operation, korrekt KEK/DEK-separation, `low_level.Type.ID` överallt. Inga fynd.
- **SQL-injektion** – alla värden binds som parametrar; tabellnamn valideras mot `_ALLOWED_TABLES` ([garmin_db.py:397-401](garmin_db.py), [garmin_db.py:415-419](garmin_db.py)) sedan `S-11`.
- **Sorteringsordning i dashboarden** – `sleep_hist[-1]`, `hrv_hist[-1]` (ASC → senaste sist) och `activities_hist[:10]` (DESC → senaste först) är alla korrekta för sina respektive frågor.
- **Staplade route-dekoratorer** – `@app.post` / `@app.put` på samma funktion ([server.py:636-638](server.py)) fungerar som avsett i FastAPI; varje dekorator registrerar en route och returnerar funktionen oförändrad.
- **Nakna `except:`** – inga kvar i kodbasen (`P2-1` håller).
- **`hr_zones_calc.py`** – hanterar `None` och nollvärden korrekt i samtliga ingångar. Inga fynd.
- **Utgående trafik till tredjepart** – Garmin (via `garth`), Strava, Fitbit, Withings, Whoop och samtliga AI-leverantörer anropas över `https://` ([strava_handler.py:25-27](strava_handler.py), [fitbit_handler.py:26-28](fitbit_handler.py), [withings_handler.py:21-23](withings_handler.py)). Inga `verify=False` någonstans i kodbasen.
  ⚠️ **Rättelse 2026-09-19:** påståendet stämmer inte fullt ut. Utöver Ollama (`TLS-4`, `TLS-7`) anropas **`ip-api.com` över okrypterad `http://`** i `get_weather` – se `TLS-8`. Uppdatera den här punkten när `TLS-8` är åtgärdad.
