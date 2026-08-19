# 📋 Åtgärdstavla – HealthChat Desktop

> Uppgiftslista för **Antigravity** baserad på en kodgenomgång av projektet (2026-08-19).
> Varje uppgift är fristående: den innehåller fil, plats, problem, föreslagen lösning och acceptanskriterier så att en agent kan plocka upp den direkt.
>
> **Prioritet:** `P0` = bugg/säkerhet som påverkar användaren nu · `P1` = viktig robusthet/kostnad · `P2` = kodkvalitet/underhåll.

---

## Sammanfattning

Projektet är en Tkinter-baserad Windows-desktopapp (~9 000 rader Python) som kopplar Garmin/Fitbit/Withings-data till flera AI-leverantörer. Arkitekturen är i grunden sund (nya SQLite-anslutningar per operation → trådsäkert DB-lager, `root.after(0, …)` används korrekt för UI-uppdateringar från trådar). Genomgången hittade **1 krasch-bugg, 1 kostnads-/tokenbugg, 1 trådsäkerhetsbugg, ett säkerhetsavvikande påstående** samt en rad robusthets- och kvalitetsförbättringar.

Verifierat och **avfärdat** som icke-buggar: Anthropic-modell-ID:na (`claude-opus-4-6` m.fl. är giltiga), DB-lagrets trådsäkerhet, och Withings token-rotation (persisteras korrekt i `sync_withings`).

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

---

## 🟡 P2 – Kodkvalitet & underhåll

### [ ] P2-1: Nakna `except:` som sväljer fel
- **Fil:** [ai_client.py](ai_client.py) och övriga filer.

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

---

## Förslag på ordning
1. **P0-1** (snabb, tydlig krasch) → **P0-3** (trådsäkerhet) → **P0-2** (säkerhet, större).
2. **P1-1** + **P1-2** + **P2-4** tillsammans (samma kontext-/minneskod).
3. Övriga P1/P2 löpande.
