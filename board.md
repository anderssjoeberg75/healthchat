# 📋 Åtgärdstavla – HealthChat

> **Kvarvarande arbete.** Avklarade punkter är borttagna 2026-09-11; de finns i git-historiken
> (`git log -p board.md`) om du behöver se vad som gjordes och varför.
>
> HealthChat är en **webbapp** (`server.py` + `static/`) med MariaDB, kontoinloggning och
> klientkryptering. Skrivbordsappen (`HealthChatDesktop.py`) ligger kvar i trädet och kör mot
> samma moduler; `HealthChatDesktop-v4.0.4-legacy.zip` arkiverar v4.0.4.
>
> **Prioritet:** 🔴 = gör först · 🟠 = viktigt · 🟡 = bör göras · 🟢 = när tid finns

---

## 🧭 Beslut som behöver tas

Tre vägval blockerar eller formar arbetet nedan. De är billiga att ta och dyra att skjuta upp.

### [ ] D-1: 🔴 Kryptering **eller** autonom bakgrundssynk — de utesluter varandra
- **Problem:** Hälsodatan krypteras med en DEK som packas upp ur användarens lösenord vid inloggning. Servern kan alltså bara läsa och skriva data **medan användaren är inloggad**. Det var hela poängen med webbappen att servern är igång dygnet runt och kan synka när datorn är avstängd — men en schemalagd check-in kl. 05:00 har ingen DEK och kan varken dekryptera eller skriva.
- **Alternativ:**
  1. **Behåll krypteringen som den är.** Synk sker bara när någon är inloggad. Enklast, starkast skydd, men ingen autonomi.
  2. **Serverhållen nyckel för bakgrundsjobb.** En kopia av DEK:en packas in med en servernyckel så att schemaläggaren kommer åt den. Ger autonomi, men den som kommer åt servern kommer åt datan — krypteringen skyddar då bara mot stulen databasdump, inte mot en komprometterad server.
  3. **Hybrid:** endast *insamling* i bakgrunden till en krypteringsfri "inkorg" som dekrypteras och skrivs in vid nästa inloggning. Mer kod, men behåller både autonomi och skydd.
- **Att göra:** välj ett alternativ, skriv ner motiveringen här, och först därefter bygga schemaläggaren.
- **Acceptanskriterier:** beslutet dokumenterat i denna fil innan någon schemaläggare implementeras.

### [ ] D-2: 🟠 Ska skrivbordsappen leva vidare?
- **Problem:** Samma funktioner finns nu i två gränssnitt: `HealthChatDesktop.py` + `charts_view.py` (~8 200 rader Tk) och `server.py` + `static/` (webb). Varje ändring i domänlogiken måste testas i båda, och de har redan glidit isär en gång — webb-migreringen tappade funktioner som skrivbordsappen hade.
- **Alternativ:** (a) avveckla skrivbordsappen och låt zip-arkivet vara historiken, (b) behåll den som offline-läge och acceptera dubbelt underhåll, (c) behåll den men frys den — inga nya funktioner, bara säkerhetsfixar.
- **Att göra:** välj, och skriv in valet i README så att nästa ändring vet var den ska landa.
- **Påverkar:** S-4, S-10, S-12 och R-19, som helt eller delvis handlar om skrivbords-UI:t.

### [ ] D-3: 🟡 Var ska webbappen köras, och når den internet?
- **Problem:** Flera punkter nedan beror på svaret: R-13 (Chart.js från CDN) spelar roll bara om klienten saknar internet, DB-3 (brandvägg) beror på om servern är exponerad, och `HEALTHCHAT_BASE_URL` måste matcha en adress som Fitbit/Strava/Withings kan nå för OAuth-callbacken.
- **Att göra:** skriv ner: värd, nätverksposition, om TLS-terminering sker i en proxy, och vilken publik URL OAuth-callbackerna ska använda.

---

## 🔒 Säkerhet

### [ ] S-3: 🟠 All MariaDB-trafik går okrypterad över nätverket
- **Fil:** [garmin_db.py:34-42](garmin_db.py) (`get_mariadb_connection`), [garmin_db.py:90-106](garmin_db.py) (`_init_mariadb_pool`)
- **Problem:** Båda anslutningsvägarna anropar `pymysql` **utan `ssl`-parameter** — MySQL-protokollet går då i klartext över LAN:et. Nyttolasten är visserligen DEK-krypterad, men i klartext över tråden går: e-postadresser, `password_hash`, `kdf_salt`, `wrapped_dek`, `dek_nonce` och `recovery_wrapped_dek`. En passiv avlyssnare på nätet får därmed **allt material som behövs för en offline-attack mot KEK:en**. Argon2id (`t=2, m=64 MB`) bromsar en sådan attack men stoppar den inte om lösenordet är svagt — och lösenordet som användes fram till 2026-09-11 var en ordboksnära sträng (se R-14).
- **Åtgärd:**
  1. Slå på TLS på servern (DB-2) och skicka `ssl={"ca": <sökväg>}` i **båda** anslutningsfunktionerna.
  2. Låt CA-sökvägen komma från `MARIADB_SSL_CA` med default `~/.healthchat/ca.pem`.
  3. Självsignerat cert: distribuera CA-certet till klienten och **verifiera** det. Använd inte `ssl_verify_cert=False` — det ger kryptering utan autentisering och därmed falsk trygghet mot MITM.
  4. Logga TLS-status vid uppstart (`SHOW STATUS LIKE 'Ssl_cipher'`) så att en tyst nedgradering till klartext blir synlig. Lägg till `MARIADB_REQUIRE_TLS=1` som får appen att vägra ansluta utan TLS.
- **Acceptanskriterier:**
  1. `SHOW STATUS LIKE 'Ssl_cipher';` från appens anslutning returnerar en icke-tom cipher.
  2. Med `MARIADB_REQUIRE_TLS=1` mot en server utan TLS avbryts anslutningen med tydligt fel.
  3. En paketdump på port 3306 visar ingen läsbar e-postadress.

### [ ] S-4: 🟠 API-nycklar, Garmin-lösenord och OAuth-tokens sparas i klartext i `config.json` (skrivbordsappen)
- **Omfattning:** Webbappen lagrar numera alla dessa fält **krypterade per användare** (AES-256-GCM med kontots DEK, `web_store.py`). Punkten gäller därför bara kvarvarande `config.json` i skrivbordsappen — och blir inaktuell om R-19 landar i att skrivbordsappen avvecklas.
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

### [ ] S-7: 🟡 Rate-limiting är svagare än dokumenterat och nollställs vid omstart
- **Fil:** [auth.py:29](auth.py), [auth.py:67-91](auth.py)
- **Problem:**
  - `K-2` påstår "max 5 misslyckade försök per **15 min**"; koden implementerar 5 per **60 sekunder** ([auth.py:73](auth.py)). Dokumentation och kod går isär.
  - `_failed_attempts` är en **process-lokal dict**. Startas appen om är spärren borta — och den skyddar överhuvudtaget inte någon som pratar direkt med MariaDB — vilket ett nätöppet DB-konto gör fullt möjligt (se R-14, DB-3).
  - Dicten städas bara för e-postadresser som slås upp igen. Försök mot slumpmässiga adresser växer den obegränsat → långsam minnesläcka och en trivial minnes-DoS.
  - Den är inte trådsäker, och inloggning sker från bakgrundstrådar.
- **Åtgärd:**
  1. Flytta räknaren till databasen: `failed_attempts INT DEFAULT 0` och `locked_until DATETIME NULL` på `users` (schemaändring — samordna med DB-4). Läs och uppdatera i samma transaktion som inloggningen.
  2. Inför progressiv backoff: 5 misslyckade → 1 min, 10 → 15 min, 20 → 1 h. Nollställ vid lyckad inloggning.
  3. Behåll processminnes-räknaren som komplement, men skydda den med `threading.Lock` och rensa **alla** poster äldre än fönstret vid varje anrop, inte bara den aktuella adressens.
  4. Uppdatera K-2-texten i denna fil så att den matchar implementationen.
- **Acceptanskriterier:**
  1. Spärren överlever omstart av appen.
  2. 10 000 försök mot unika adresser får inte `_failed_attempts` att växa obegränsat.
  3. Test som verifierar backoff-trappan och att lyckad inloggning nollställer.

### [ ] S-10: 🟡 OAuth-flödena saknar `state`/PKCE → CSRF på auktoriseringssvaret
- **Omfattning:** Webbappen genererar ett engångs-`state` per auktorisering och binder svaret till rätt användare (`server.py`, `_oauth_states`). Kvar: handlarna själva (`get_auth_url`) skickar fortfarande inget eget `state` — Withings har kvar den hårdkodade `state=withings_state` — så skrivbordsappens flöden är oskyddade, och **PKCE saknas i båda**.
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

### [ ] S-12: 🟢 DEK:en ligger i Windows Credential Manager utan förfallotid
- **Fil:** [auth.py:420-445](auth.py)
- **Problem:** "Spara inloggning" (K-4) lagrar den **oskyddade DEK:en** base64-kodad i Credential Manager. Det är ett medvetet designval och skyddas av DPAPI, men konsekvensen bör vara uttalad: **varje process som kör som samma Windows-användare kan läsa ut DEK:en** och dekryptera all hälsodata utan att någonsin se lösenordet. Rate-limiting, Argon2 och återställningsnyckeln kringgås helt. Nyckeln ligger dessutom kvar för alltid.
- **Åtgärd:**
  1. Gör "Spara inloggning" till **opt-in med tydlig varningstext** i inloggningsdialogen — inte förvald.
  2. Lagra en förfallotid tillsammans med nyckeln (`{"dek": …, "expires": …}`) och kräv lösenord igen efter t.ex. 30 dagar.
  3. Dokumentera avvägningen i README under "🔒 Privacy & Security".
- **Acceptanskriterier:** kryssrutan är omarkerad som standard; en utgången keyring-post ger lösenordsprompt i stället för automatisk inloggning.

---

## 🗄️ MariaDB-servern på `192.168.101.106`

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
  4. Rapportera avvikelser och uppdatera [init_mariadb.sql](init_mariadb.sql) så att den matchar.
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

## ⚡ Prestanda

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

### [ ] PF-5: 🟡 Ingen radbegränsning i `_mariadb_get_history` — allt dekrypteras oavsett vad som visas
- **Fil:** [garmin_db.py:289-313](garmin_db.py), [garmin_db.py:775-802](garmin_db.py), [garmin_db.py:853-864](garmin_db.py)
- **Problem:** `_mariadb_get_history` hämtar alla rader i intervallet och dekrypterar var och en. `get_latest_body_composition` gör rätt (`LIMIT 1`), men `get_activities_history` och `get_calorie_burn_history` laddar hela historiken när `days >= 3650`. "Allt"-knappen i dashboarden sätter just `days_range >= 3650` ([charts_view.py:211](charts_view.py)) — ett klick betyder alltså full nedladdning och dekryptering av samtliga tabeller, på UI-tråden i skrivbordsappen.
- **Åtgärd:**
  1. Lägg till en valfri `limit`-parameter på `_mariadb_get_history` och skicka `LIMIT %s` vidare till SQL:en.
  2. Inför en enkel per-instans cache med nyckeln `(table, days)` och kort TTL (t.ex. 60 s), invaliderad av motsvarande `upsert_*`. Dashboardens upprepade omritningar delar då en enda hämtning.
  3. Sätt ett tak i UI:t för "Allt": aggregera grafdata per vecka bortom 1 år i stället för per dag — bortom ett år är dagsupplösning ändå inte läsbar i graferna.
- **Acceptanskriterier:** "Allt"-vyn renderar på < 2 s med full historik; upprepade fliksbyten inom 60 s utlöser inga nya databasfrågor.

### [ ] PF-6: 🟡 Anslutningspoolen kan svälta och återhämtar sig inte från tappade anslutningar
- **Delvis åtgärdat 2026-09-11:** `connect_timeout`, `read_timeout` och `write_timeout` är satta (konfigurerbara via `MARIADB_*_TIMEOUT`), så en onåbar server faller tillbaka på SQLite i stället för att hänga. **Kvar:** `ping`, konfigurerbara poolstorlekar och timeout på `blocking=True`.
- **Fil:** [garmin_db.py:90-106](garmin_db.py)
- **Problem:** `PooledDB(maxconnections=10, mincached=2, maxcached=5, blocking=True)`.
  - `blocking=True` utan timeout betyder att en tråd som inte får en anslutning **blockerar för alltid**. Sker det på skrivbordsappens UI-tråd fryser appen permanent i stället för att ge ett felmeddelande.
  - Ingen `ping`. En anslutning som servern stängt (`wait_timeout`, ofta 8 h) returneras som trasig och ger `OperationalError: MySQL server has gone away` vid nästa användning. Det drabbar särskilt en app som står öppen hela dagen.
  - Ingen `connect_timeout` i pymysql-argumenten: är servern nere hänger anslutningsförsöket tills OS:ets TCP-timeout löper ut.
- **Åtgärd:**
  1. Lägg till `ping=1` (kontroll vid varje `connection()`) eller `ping=4`.
  2. Sätt `connect_timeout` (t.ex. 5 s) och `read_timeout`/`write_timeout` i pymysql-argumenten, i båda anslutningsvägarna.
  3. Gör poolstorlekarna konfigurerbara via miljövariabler med nuvarande värden som default.
  4. Med allt DB-arbete på bakgrundstrådar kan `blocking=True` behållas; annars bör den kombineras med en timeout så att UI:t inte kan låsa sig permanent.
- **Acceptanskriterier:** appen återhämtar sig utan omstart efter att MariaDB startats om; ingen `MySQL server has gone away` i loggen efter en dag med öppen app.


---

## 🌐 Webbappen

### [ ] R-13: 🟡 Vendora Chart.js lokalt
- **Fil:** [static/index.html](static/index.html)
- **Problem:** Graferna laddas från `cdn.jsdelivr.net`. Utan internet på klienten ritas inga grafer — vilket krockar med poängen att servern och databasen ska kunna stå isolerade.
- **Att göra:** Lägg `chart.umd.min.js` i `static/vendor/` och peka dit. (Graferna faller nu mjukt tillbaka med ett meddelande i stället för att krascha hela dashboard-uppdateringen, men beroendet finns kvar.)

### [ ] R-14: 🔴 Rotera MariaDB-lösenordet — det har legat i git-historiken
- **Fil:** [garmin_db.py](garmin_db.py) (åtgärdat), historiken (kvarstår)
- **Problem:** Lösenordet till `'healthchat'@'%'` låg i klartext i källkoden (`password or "powerman"`) och skrevs dessutom automatiskt in i en ny `~/.healthchat/db.env`. Koden läser det numera bara från miljön eller `db.env`, men **strängen finns kvar i git-historiken och i varje klon av repot**. Punkten var tidigare avbockad som "roterad" — den bedömningen stämde inte, lösenordet låg kvar i koden så sent som 2026-09-11.
- **Att göra:**
  1. Sätt ett nytt slumpat lösenord (≥ 24 tecken) på applikationskontot i MariaDB.
  2. Lägg det i `~/.healthchat/db.env` (`chmod 600`) på varje maskin som kör appen — aldrig i repot.
  3. Begränsa kontot till klientnätet (`'healthchat'@'192.168.101.%'`) med enbart `SELECT, INSERT, UPDATE, DELETE ON healthchat.*`, och `FLUSH PRIVILEGES`.
  4. Överväg om historiken behöver skrivas om (`git filter-repo`) eller om rotation räcker — rotation räcker så länge repot är privat.
- **Acceptanskriterier:** det gamla lösenordet ger `Access denied`; appen och testsviten fungerar med det nya; `git grep -i powerman` i arbetskopian ger noll träffar.

### [ ] R-15: 🟠 Sessioner ligger bara i minnet och går aldrig ut
- **Fil:** [server.py:66](server.py) (`_active_sessions`), [server.py:166-172](server.py) (`set_cookie`)
- **Problem:** Tre saker hänger ihop:
  - `_active_sessions` är en process-lokal dict. **En omstart av servern loggar ut alla** — och eftersom cookien har `max_age=30 dagar` fortsätter webbläsaren skicka en token som servern inte känner igen, vilket ser ut som ett fel snarare än en utloggning.
  - Sessionen har ingen serversidig förfallotid. DEK:en ligger kvar i minnet så länge processen lever, oavsett hur länge användaren varit borta.
  - Cookien sätts utan `secure=True`, så den skickas i klartext om appen nås över HTTP.
- **Att göra:**
  1. Ge sessionen en förfallotid (t.ex. 12 h inaktivitet, 30 dagar absolut) och rensa utgångna poster.
  2. Sätt `secure=True` när `HEALTHCHAT_BASE_URL` börjar med `https://` (eller via en `HEALTHCHAT_COOKIE_SECURE`-flagga).
  3. Bestäm om sessioner ska överleva omstart. Att spara dem kräver att DEK:en lagras någonstans — vilket är samma avvägning som **D-1**. Gör inget förrän D-1 är beslutad; rensa i stället cookien snyggt när token är okänd, så att användaren får inloggningsrutan i stället för ett fel.
- **Acceptanskriterier:** en okänd session-cookie ger inloggningsrutan utan felmeddelande; en session som stått orörd över förfallotiden kräver nytt lösenord; cookien är `Secure` vid HTTPS-drift.

### [ ] R-16: 🟠 Bromsning mot lösenordsgissning saknas i webblagret
- **Fil:** [server.py](server.py) (`/api/auth/login`), [auth.py](auth.py)
- **Problem:** `auth.check_rate_limit` finns (se **S-7**), men webbappen exponerar inloggningen mot nätverket i stället för mot en lokal Tk-dialog. Utan bromsning per **IP** — inte bara per e-postadress — kan en angripare gissa lösenord i den takt servern orkar svara, och Argon2id-kostnaden gör varje försök dyrt för *servern*, vilket också gör det till en billig DoS.
- **Att göra:** räknare per IP och per e-post med progressiv fördröjning, och ett tak för samtidiga inloggningsförsök. Samordna med S-7 så att det blir en implementation, inte två.
- **Acceptanskriterier:** det sjätte felaktiga försöket från samma IP bromsas mätbart; en lyckad inloggning nollställer räknaren.

### [ ] R-17: 🟡 Säkerhetsheaders och uppladdningstak saknas
- **Fil:** [server.py](server.py)
- **Problem:** Appen sätter inga `Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy` eller `X-Frame-Options`. CORS är dessutom `allow_origins=["*"]` **med** `allow_credentials=True` — en kombination webbläsare vägrar honorera, men som signalerar att avsikten är otydlig; sätt den till appens egen origin. `POST /api/import/*` tar emot filer utan storleksgräns, så en stor uppladdning kan fylla disken.
- **Att göra:** lägg headers i en middleware, begränsa CORS till `HEALTHCHAT_BASE_URL`, och sätt ett tak (t.ex. 50 MB) på uppladdningar med ett tydligt fel när det överskrids.
- **Acceptanskriterier:** headers syns i svaret; en uppladdning över taket avvisas i stället för att skrivas till disk.

### [ ] R-18: 🟡 MariaDB-vägen är overifierad av testsviten
- **Fil:** [tests/test_auth.py](tests/test_auth.py), [tests/test_garmin_db_mariadb.py](tests/test_garmin_db_mariadb.py), [tests/test_security_and_perf.py](tests/test_security_and_perf.py)
- **Problem:** Sex tester hoppas över när MariaDB inte går att nå, vilket den inte gör i någon automatiserad miljö. Det betyder att **kryptering, kontohantering och radisolering mot den riktiga backenden aldrig testas** — bara SQLite-vägen körs. Det är den vägen som håller produktionsdatan.
- **Att göra:** starta en MariaDB i CI (container eller tjänst), peka `MARIADB_*` dit och kör sviten utan skip. Ladda `init_mariadb.sql` som schema så att DB-4 verifieras på köpet.
- **Acceptanskriterier:** `python -m pytest` rapporterar noll överhoppade tester i CI; ett schemafel i `init_mariadb.sql` gör sviten röd.

### [ ] R-19: 🟡 Två testfiler kan inte köras utan Tkinter
- **Fil:** [tests/test_charts_view_tabs.py](tests/test_charts_view_tabs.py), [tests/test_withings_handler.py](tests/test_withings_handler.py)
- **Problem:** Båda importerar skrivbordsappen (`import tkinter`, `from HealthChatDesktop import HealthChatApp`). På en server utan Tk **kraschar hela insamlingsfasen** — `pytest` avbryter med collection error i stället för att hoppa över filen, så en enda saknad systemmodul gör hela sviten okörbar.
- **Att göra:** lägg `pytest.importorskip("tkinter")` överst i båda filerna, och flytta `test_sync_profile_weight_from_db` till en modul som inte behöver UI:t (den testar viktsynk, inte Tk). Hänger ihop med **D-2**.
- **Acceptanskriterier:** `python -m pytest` går att köra rent på en maskin utan Tkinter; de UI-beroende testerna rapporteras som skipped, inte som error.

### [ ] R-20: 🟢 AI-SDK:ernas versionsnålning är overifierad
- **Fil:** [requirements.txt](requirements.txt)
- **Problem:** `anthropic==0.39.0` gick inte att verifiera vid återställningen — i en miljö med en nyare `anthropic` kraschar `AIClient` med `Invalid http_client argument … this SDK uses httpx2`. `openai`, `xai` och `ollama` konstrueras rent. Det är alltså inte känt om Anthropic-vägen fungerar med det pinnade paketet i din miljö, eller bara i teorin.
- **Att göra:** kör en verklig fråga mot varje leverantör du faktiskt använder, en gång, och notera resultatet här. Uppdatera pinningen om SDK:n behöver flyttas.
- **Acceptanskriterier:** varje leverantör i `AIClient.PROVIDERS` som ni tänker använda har testats mot en riktig nyckel minst en gång efter pinningen.

---

## Förslag på ordning

1. **D-1** och **D-2** först — de avgör hur R-15 och S-4/S-10 ska lösas, och de tar en kvart var.
2. **R-14** (rotera lösenordet) omedelbart, oavsett allt annat.
3. **R-15** → **R-16** → **R-17** innan appen når fler användare än dig själv.
4. **DB-2** + **S-3** tillsammans (TLS på servern och i klienten är samma arbete), sedan **DB-3**.
5. **R-18** — när MariaDB testas i CI blir **DB-4** nästan gratis.
6. **DB-5** (backup) — billig försäkring, ta den innan datamängden växer.
7. **PF-2** → **PF-5** → **PF-6** när databasen börjar kännas trög.
8. Resten (**S-7**, **S-12**, **R-13**, **R-19**, **R-20**) löpande.
