# prompts/

Systemprompterna för HealthChats AI ligger som vanliga Markdown-filer här, i stället för
hårdkodade i Python. Du kan redigera dem direkt, utan att röra koden och utan att starta
om servern.

## Filer

| Fil | Används av | Vad den styr |
|---|---|---|
| `coach_system.md` | `AIClient.get_default_system_prompt()` → `/api/ai/chat` | COACH AI, PT-funktionen i fliken *Fråga Coachen* |
| `archive/` | ingenting | Tidigare versioner, sparade för referens |

## Så fungerar det

`prompt_store.get_prompt("coach_system")` läser `prompts/coach_system.md` och skickar
innehållet som systemprompt till modellen.

- **Ändringar slår igenom direkt.** Filens `mtime` kontrolleras vid varje anrop.
  Spara filen, ställ en ny fråga i chatten - klart. Ingen omstart, ingen deploy.
- **Kommentarer syns inte för modellen.** Allt mellan `<!--` och `-->` tas bort innan
  prompten skickas. Skriv gärna anteckningar till dig själv i filen.
- **Filen kan inte krascha chatten.** Saknas den, eller är den tom, loggas ett tydligt
  fel och `AIClient.FALLBACK_COACH_PROMPT` i `ai_client.py` används i stället.

Vill du lägga prompterna utanför git i drift (t.ex. för lokala justeringar som inte ska
committas), peka om katalogen:

```bash
HEALTHCHAT_PROMPTS_DIR=/etc/healthchat/prompts
```

## Redigera `coach_system.md`

Filen är indelad i numrerade avsnitt. De flesta går att ändra fritt:

| Avsnitt | Innehåll | Ändra fritt? |
|---|---|---|
| 0 | Absolut regel: inga medicinska diagnoser | **Nej** - se nedan |
| 1 | Säkerhet och gränser (röda flaggor, kaloriminimum) | Endast för att skärpa |
| 2 | Träningsprinciper och återhämtningströsklar | Ja |
| 3 | Hur data används, vad coachen inte kan göra | Ja |
| 4 | Samtalsmönster | Ja |
| 5 | Svarsformat | Ja |
| 6 | Språk, ton och terminologi | Ja |

### ⚠️ Avsnitt 0 och 1 är inte vanliga promptavsnitt

Avsnitt 0 slår fast att AI:n **aldrig** får ställa, antyda, bekräfta eller utesluta en
medicinsk diagnos - och att den inte heller får friskförklara. Det är det som håller
HealthChat på rätt sida om gränsen mellan livsstilsapp och medicinteknisk produkt.

Ta inte bort avsnittet, och luckra inte upp det. Samma regel finns dessutom i
`FALLBACK_COACH_PROMPT` i `ai_client.py`, och `tests/test_prompt_store.py` failar om den
försvinner från någon av dem. Det är avsiktligt.

Behöver reglerna ändras i sak - gör det som ett medvetet beslut, uppdatera testet i samma
ändring, och skriv ned varför i `CHANGELOG.md`.

## Lägga till en ny prompt

1. Skapa `prompts/<namn>.md`.
2. Läs den med `prompt_store.get_prompt("<namn>", fallback=...)`.
3. Ange alltid en `fallback` - en prompt som inte går att läsa ska aldrig stoppa ett svar.

## Arkivera innan du skriver om

Innan en större omskrivning, kopiera nuvarande version till
`prompts/archive/coach_system_v<N>_<datum>.md`. Arkivet laddas aldrig av appen - det finns
bara för att kunna gå tillbaka och för att se hur prompten utvecklats.
