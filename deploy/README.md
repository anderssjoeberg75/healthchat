# Driftsättning med HTTPS

Uppsättning av TLS framför HealthChat-webappen. Motsvarar `TLS-1` i [board.md](../board.md).

**Domän:** `healthchat.andrix.se` (publik) · **Certifikat:** Let's Encrypt via Caddy

---

## Portlayout

Före:

```
Webbläsare ──http──> uvicorn 0.0.0.0:8000          ← okrypterat, öppet mot hela nätet
```

Efter:

```
Webbläsare ──https──> Caddy :443 ──http──> uvicorn 127.0.0.1:8001
                      Caddy :80  ──redirect──> :443
```

Uvicorn flyttar till **port 8001 på loopback**. Två skäl: proxyn tar över 443, och
appen får inte längre gå att nå direkt — annars kan vem som helst kringgå TLS:en
genom att prata med port 8000.

---

## Ordningen spelar roll

> ⚠️ **Flytta inte uvicorn till loopback förrän proxyn är verifierad.** Gör du stegen
> i fel ordning är appen onåbar däremellan: proxyn pekar på en port ingen lyssnar på,
> samtidigt som den gamla porten är stängd.

### 1. Öppna port 80 och 443 i brandväggen

Let's Encrypt validerar via port 80. Den måste vara nåbar **både vid utfärdandet och
var 60:e dag när Caddy förnyar** — stänger du 80 efteråt slutar certifikatet fungera
om tre månader, tyst.

```bash
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
dig +short healthchat.andrix.se        # ska peka på serverns publika IP
```

### 2. Installera Caddy och konfigurationen

```bash
sudo apt install -y caddy
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo editor /etc/caddy/Caddyfile        # fyll i `email` högst upp
sudo caddy validate --config /etc/caddy/Caddyfile
```

### 3. Starta uvicorn på den nya porten — men behåll den gamla igång

Kör tillfälligt en andra instans på 8001, så att proxyn kan testas medan den
nuvarande tjänsten på 8000 fortfarande betjänar användarna:

```bash
sudo -u healthchat /opt/healthchat/venv/bin/uvicorn server:app \
     --host 127.0.0.1 --port 8001 --app-dir /opt/healthchat
```

### 4. Starta Caddy och verifiera

```bash
sudo systemctl reload caddy
curl -I https://healthchat.andrix.se/          # 200 + Strict-Transport-Security
curl -I http://healthchat.andrix.se/           # 301 till https
```

Öppna sidan i en webbläsare och **logga in** — inte bara ladda startsidan. Testa
också AI-chatten: den använder Server-Sent Events och är det enda som kan gå sönder
av proxybuffring.

### 5. Först nu: flytta den riktiga tjänsten

Avbryt den tillfälliga instansen från steg 3, installera den uppdaterade unit-filen
och starta om:

```bash
sudo cp healthchat_web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart healthchat_web
sudo systemctl status healthchat_web --no-pager
```

### 6. Stäng port 8000 utifrån

```bash
sudo ufw deny 8000/tcp
curl --max-time 5 http://<serverns-publika-ip>:8000/    # ska ge timeout/refused
```

Det sista steget är inte kosmetiskt: så länge 8000 svarar utifrån finns en väg förbi
TLS:en, och all den kryptering du just satt upp går att kringgå genom att skriva
portnumret.

---

## Efteråt

- **`TLS-2`** i board.md sätter `COOKIE_SECURE` och resterande säkerhetsheaders i
  appen. Kan göras först nu — med HTTP kvar hade `Secure`-flaggan stoppat inloggningen.
- **HSTS sätts i Caddy**, inte i appen. Sätt den inte på båda ställena.
- **Bevaka förnyelsen.** Caddy förnyar automatiskt, men tyst. Lägg upp en påminnelse
  eller en enkel kontroll:
  ```bash
  echo | openssl s_client -connect healthchat.andrix.se:443 2>/dev/null \
    | openssl x509 -noout -enddate
  ```
- **Kvarstår från `TLS-3`:** trafiken mellan appen och MariaDB går fortfarande
  okrypterad. Den här uppsättningen skyddar bara sträckan webbläsare→app.

---

## nginx i stället för Caddy

Kör servern redan nginx finns [nginx-healthchat.conf](nginx-healthchat.conf) som
alternativ. Två saker skiljer den från en vanlig proxykonfiguration, och båda är
lätta att missa:

- **`proxy_buffering off` för `/api/ai/chat`.** Utan det buffrar nginx SSE-strömmen
  och chatten ser ut att hänga tills hela svaret är klart.
- **`proxy_read_timeout 300s`.** AI-svaret genereras i sin helhet innan första byten
  skickas. nginx default är 60 sekunder, vilket klipper långsamma svar.

Certifikatförnyelsen sköts då av certbot, inte av nginx självt — kontrollera att
`certbot.timer` är aktiv.
