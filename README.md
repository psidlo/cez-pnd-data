# CEZ PND pro Home Assistant

Aplikace načítá elektroměrová data z [ČEZ PND](https://pnd.cezdistribuce.cz)
a rozvrh HDO z [Distribučního portálu ČEZ](https://dip.cezdistribuce.cz).
Přes MQTT Discovery vytváří senzory v Home Assistantu. Volitelně ukládá
historické odpovědi a čtvrthodinové profily do SQLite.

## Funkce a význam dat

- Samostatné MQTT zařízení pro každý nastavený elektroměr: 13 PND a 4 HDO senzorů.
- Připojení k místnímu nebo externímu MQTT brokeru, obnovení discovery
  a dostupnosti po opětovném připojení a korektní ukončení aplikace.
- Přihlášení přes Playwright/Chromium, obnova relace a inicializace
  autorizace DIP pro HDO ve stejném přihlášeném kontextu.
- HDO rozvrh pro aktuální datum v Europe/Prague a čas dalšího přepnutí
  s údajem o časovém pásmu.
- Volitelný archiv se samostatným výběrem elektroměrů, omezeným zpětným
  doplňováním a zachováním chybějících hodnot a kvality měření.

PND jsou data zveřejněná distribučním portálem se zpožděním. Aplikace
nenahrazuje průběžné místní měření. MQTT zobrazuje poslední dostupné
hodnoty jednotlivých veličin z načtených odpovědí; nemusí pocházet ze stejného
okamžiku. Dostupnost MQTT potvrzuje spojení, nikoli čerstvost každé hodnoty.

Historická data, pokrytí a časové přiřazení jsou popsány v
[návodu k archivu](docs/archive.md).

## Instalace

Potřebujete Home Assistant OS nebo Supervised, přístup k účtu ČEZ
a MQTT broker přístupný aplikaci i MQTT integraci Home Assistantu.
Obraz podporuje amd64, aarch64 a armv7.

1. Připravte broker, například Mosquitto, a nastavte integraci MQTT
   v **Nastavení → Zařízení a služby**.
2. V **Nastavení → Aplikace → Obchod s aplikacemi** přidejte URL repozitáře,
   ze kterého instalujete aplikaci. Ve starších verzích HA se tato nabídka
   nazývá Doplňky.
3. Nainstalujte CEZ PND, vyplňte přihlašovací údaje ČEZ, elektroměr
   a připojení MQTT a aplikaci spusťte.
4. V logu zkontrolujte dokončení cyklu a v integraci MQTT vytvořené zařízení.
   Některé veličiny mohou zůstat neznámé, pokud je portál neposkytuje.

Obchod HA čte výchozí větev repozitáře. Dokumentace v jiné větvi popisuje
zdroje této větve; samotné přidání repozitáře nevybere její obsah.
Pro testování konkrétní větve nebo commitu zkopírujte její adresář
`addon/` jako místní aplikaci do `/addons/cez-pnd/`, obnovte seznam
místních aplikací a sestavte obraz. Pro aktualizaci existující instalace
nejprve použijte [postup aktualizace a návratu](docs/pnd-consolidated-migration.md).

## Nastavení

Hodnoty ID a EAN zadávejte jako řetězce. **ID elektroměru a EAN jsou různé
identifikátory**; použijte údaje příslušného elektroměru a odběrného místa
z portálu ČEZ.

### Účet a publikované elektroměry

| Volba | Výchozí hodnota | Význam |
|---|---|---|
| `email` | prázdná | Povinný přihlašovací e-mail účtu ČEZ. |
| `password` | prázdná | Povinné heslo účtu ČEZ. |
| `electrometer_id` | prázdná | ID jednoho elektroměru; použije se, když je `electrometers` prázdné. Pro běžný provoz ID výslovně zadejte. |
| `ean` | prázdná | EAN odběrného místa pro jeden elektroměr, potřebný k načtení HDO. |
| `electrometers` | `"[]"` | JSON pole objektů s neprázdnými řetězci `electrometer_id` a `ean`. Neprázdný seznam má přednost před oběma samostatnými volbami. |

Minimální příklad pro jeden elektroměr (všechny údaje jsou zástupné):

```yaml
email: "vas-ucet@example.invalid"
password: "DOPLNTE_HESLO"
electrometer_id: "12345678"
ean: "859000000000000001"
electrometers: "[]"
mqtt_host: "core-mosquitto"
mqtt_port: 1883
mqtt_user: "vas-mqtt-uzivatel"
mqtt_password: "DOPLNTE_MQTT_HESLO"
archive_enabled: false
```

Prázdné `ean` v režimu jednoho elektroměru umožňuje PND, ale bez HDO.
Nespoléhejte na automatické vyhledání elektroměru: aktuální runtime
potřebuje nakonfigurovaný seznam nebo výslovné `electrometer_id`.
Detekce ID z názvů sloupců parserem nevyhledává elektroměry v účtu.

Více publikovaných elektroměrů:

```yaml
electrometers: '[{"electrometer_id":"12345678","ean":"859000000000000001"},{"electrometer_id":"87654321","ean":"859000000000000002"}]'
```

Seznam nesmí obsahovat duplicitní ID ani duplicitní EAN. Každý elektroměr
má vlastní zařízení a témata; hodnoty se automaticky nesčítají do souhrnu
odběrného místa. Pro původní a nástupnický elektroměr stejného místa
použijte samostatný [výběr pro archiv](docs/archive.md).
Při více publikovaných elektroměrech zohledněte omezení LWT níže.

### MQTT broker

| Volba | Výchozí hodnota | Význam |
|---|---|---|
| `mqtt_host` | prázdná | Adresa brokeru. Neprázdná hodnota má přednost před prostředím; jinak `MQTT_HOST`, případně `core-mosquitto`. |
| `mqtt_port` | `1883` | Port brokeru. Neprázdná hodnota má přednost před `MQTT_PORT`. |
| `mqtt_user` | prázdná | MQTT uživatel; jinak hodnota `MQTT_USER`, je-li v prostředí. |
| `mqtt_password` | prázdná | MQTT heslo; jinak hodnota `MQTT_PASSWORD`, je-li v prostředí. |

Použijte účet, kterému broker dovoluje publikovat discovery a stavová témata.
Pro externí broker vyplňte jeho adresu, port a přihlašovací údaje přímo
v konfiguraci. Home Assistant musí být připojen ke stejnému brokeru.

Manifest deklaruje `mqtt:want`; broker nemusí být místní aplikace.
Startovací skript čeká na dostupnost nastaveného brokeru a runtime potvrdí
přijetí připojení. Samotná deklarace služby nezajišťuje automatické získání
přihlašovacích údajů ze Supervisor API. Je-li broker vyžaduje, vyplňte je.
Konfigurace zde nenabízí volbu MQTT TLS.

### Volitelný archiv

| Volba | Výchozí hodnota | Význam |
|---|---|---|
| `archive_enabled` | `false` | Povolit archivaci. Při vypnutí runtime archivní databázi neotevírá; existující soubor nemaže. |
| `archive_start_date` | prázdná | Při zapnutí povinné počáteční datum `YYYY-MM-DD`. |
| `archive_days_per_cycle` | `1` | Společný limit pokusů o den elektroměru za cyklus, 1–62; není to počet API požadavků ani limit pro každý elektroměr zvlášť. |
| `archive_meter_ids` | `"[]"` | JSON pole číselných ID jako řetězců, nejvýše 32 položek. Prázdný seznam použije publikované elektroměry. |
| `import_ean` | prázdná | Výslovný EAN odběru pro samostatný seznam archivních elektroměrů. |
| `export_ean` | prázdná | Výslovný EAN dodávky pro samostatný seznam archivních elektroměrů. |

Pro nový archiv nastavte **neprázdné** `archive_meter_ids` a oba EAN.
Jedna dvojice EAN se přiřazuje všem ID v tomto samostatném seznamu; je určena
například pro výměnu elektroměru na jednom předávacím místě. Při prázdném
seznamu runtime vyžaduje již existující archivní metadata; obecné `ean`
nenahrazuje dvojici import/export. Další příklady, SQL a pravidla času jsou
v [návodu k archivu](docs/archive.md).

## Senzory a jednotky

Následující klíče jsou použity v MQTT tématech a unique ID. Konkrétní
`entity_id` přiděluje Home Assistant a uživatel je může přejmenovat.
Názvy zařízení a senzorů obsahují ID elektroměru a český i anglický název.

| Klíč | Význam | Publikovaná jednotka |
|---|---|---|
| `consumption` | Odběr (+A) | kW |
| `production` | Dodávka (−A) | kW |
| `reactive` | Legacy sloupec Rv, beze změny číselné hodnoty | kW |
| `reactive_import_inductive` | Ri+, import induktivní | var |
| `reactive_export_capacitive` | Rc−, export kapacitivní | var |
| `reactive_export_inductive` | Ri−, export induktivní | var |
| `reactive_import_capacitive` | Rc+, import kapacitivní | var |
| `daily_consumption` | Denní odběr | kWh |
| `daily_production` | Denní dodávka | kWh |
| `register_consumption` | Registr odběru (+E) | kWh |
| `register_production` | Registr dodávky (−E) | kWh |
| `register_low_tariff` | Registr nízkého tarifu | kWh |
| `register_high_tariff` | Registr vysokého tarifu | kWh |
| `hdo_low_tariff_active` | Vypočtený stav nízkého tarifu | `ON` / `OFF` |
| `hdo_next_switch` | Vypočtený čas dalšího přepnutí | ISO 8601 s časovým pásmem |
| `hdo_schedule_today` | Dnešní okna nízkého tarifu | text |
| `hdo_signal` | Název signálu | text |

Všech 17 entit je v doméně **sensor**; stav HDO není `binary_sensor`.
Definice se vytvářejí i pro hodnoty, které portál aktuálně neposkytuje.
Ty mohou zůstat `unknown` nebo ponechat dřívější hodnotu.

Tabulka popisuje publikovaná metadata, nikoli nezávislé ověření jednotek
portálu. U Rv se zachovává kW a není nastavena třída `reactive_power`;
jeho fyzikální význam zde není potvrzený. Čtyři Ri/Rc kanály jsou v této
implementaci označeny `var` bez jednotkové konverze. Před použitím
jalových veličin pro výpočty ověřte jednotku zdrojové sestavy ČEZ.

### HDO a čas

Tarif je výpočet podle rozvrhu z DIP, nikoli čtení kontaktu HDO.
U datovaného týdenního rozvrhu se vybírá první záznam pro dnešní datum
v Europe/Prague; pokud pro dnešek není záznam, HDO se nepublikuje.
U nedatované odpovědi se použije první signál. Různé kanály se neslučují.

HDO hodnoty se přepočítávají při polling cyklu, nikoli přesně v okamžiku
přepnutí tarifu. Po poslední dnešní hranici parser odhaduje další přepnutí
z dnešních časů pro následující den; neověřuje tím zítřejší rozvrh.
Nejde o náhradu fyzického blokování spotřebiče ani o záruku přesného přepnutí.

## MQTT témata a dostupnost

| Účel | Téma |
|---|---|
| Discovery | `homeassistant/sensor/cez_pnd_{meter_id}/{key}/config` |
| Stav | `cez_pnd/{meter_id}/{key}/state` |
| Dostupnost | `cez_pnd/{meter_id}/availability` |
| Unique ID | `cez_pnd_{meter_id}_{key}` |
| ID zařízení | `cez_pnd_{meter_id}` |

Zprávy používají QoS 1 a retain. Po opětovném připojení se obnoví discovery
a online stav. Při korektním ukončení se offline publikuje všem elektroměrům.
**Při nečekaném přerušení spojení má LWT pouze první publikovaný elektroměr**;
ostatní mohou mít ponechaný online stav. Online proto není kontrolou
čerstvosti měření a pro více elektroměrů není poskytován společný atomický LWT.

Při převodu mezi konfigurací jednoho elektroměru a seznamem zůstávají
identity stejné, pokud zůstane stejné ID elektroměru. Změna tohoto ID
nebo instalace druhého publisheru může ovlivnit entity; před aktualizací
zkontrolujte návazné dashboardy a automatizace.

## Provoz a odstraňování problémů

Po dokončení celého cyklu aplikace čeká 900 sekund. Cyklus zahrnuje načtení
PND, HDO a případně archivaci. Nejde o dotazy zarovnané na čtvrthodiny;
větší archivní dávka další cyklus oddálí.

Běžné dotazy této větve používají aktuální kalendářní den; chybějící denní
registry se zkoušejí ještě za včerejšek. Archiv samostatně zpracovává
ukončené dny do včerejška. Dostupnost dat závisí na jejich zveřejnění ČEZ.

| Projev | Co zkontrolovat |
|---|---|
| Start skončí na konfiguraci | Účet, výslovné ID elektroměru, JSON seznamy, platné datum a limit archivu. |
| MQTT se nepřipojí | Dostupnost hostu/portu z aplikace, účet a oprávnění brokeru, připojení HA ke stejnému brokeru. |
| Senzory nejsou vidět | Integraci MQTT a témata `homeassistant/sensor/cez_pnd_{meter_id}/+/config`; mohou mít uživatelsky změněná entity ID. |
| Některé hodnoty chybí | Odpovídající sestavu a datum na portálu. Chybějící registry nejsou automaticky nula. |
| `SESSION_EXPIRED` | Relace nebo přihlášení selhalo; aplikace zkouší obnovu podle typu chyby. Ověřte přihlášení na portálu. |
| `PORTAL_MAINTENANCE` | Přihlášení označilo údržbu; celý cyklus se vynechá. |
| `HDO_TOKEN_ERROR`, `HDO_FETCH_ERROR` nebo `DIP_MAINTENANCE` | Přístup k DIP, EAN a dostupnost rozvrhu. PND může pokračovat. HTTP 400 s aplikačním 401 při získávání tokenu znamená problém autorizace, nikoli důkaz údržby. |
| Odmítnutí PND / `PND request rejected` | Aplikace odloží PND dotazy na 12 hodin. Vyčkejte; opakované restarty ruší tuto ochrannou pauzu. |
| Archiv nic nedoplňuje | Povolení, datum, archivní ID, metadata EAN, prodlevy opakování a integritu databáze; viz [archiv](docs/archive.md). |

Čerstvost ověřujte vůči datům portálu a uloženým intervalům. MQTT ponechává
poslední ne-null hodnotu každé veličiny v odpovědi; skutečná nula je platná.
Souhrnný čas posledního řádku nevypovídá o stáří každé dílčí hodnoty.

Relace se ukládá do `/data/session_state.json`; při startu může být
kvůli HDO potřeba nové přihlášení i při platných uložených cookies.
Pauza po odmítnutí je pouze v paměti procesu a restart ji resetuje.

## Aktualizace, zálohy a soukromí

Použijte [návod k aktualizaci a návratu](docs/pnd-consolidated-migration.md)
a [kontrolní seznam provozu](docs/pnd-open-items.md).
Zachovejte identitu aplikace, připojení brokeru a existující MQTT identity.
Databáze v `/share` vyžaduje vlastní ověřenou zálohu; neodvozujte její
zahrnutí jen z existence zálohy aplikace.

Přihlašovací údaje, cookies, databáze, EAN, ID měřidel a odpovědi portálu
obsahují soukromá data. Při hlášení chyby posílejte verzi, bezpečné chybové
kategorie a anonymizovaný popis; nepřikládejte nezpracované options,
session ani produkční databázi. Logování podrobnosti potlačuje, ale není
náhradou kontroly příloh před zveřejněním.

## Vývoj a přispívání

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements_test.txt pytest-socket
pytest --disable-socket --allow-unix-socket
```

CI testuje Python 3.9–3.13, pokrytí alespoň 80 %, formátování,
lint a typy. Zahrnuje také kontroly tajných údajů, SAST, závislostí,
kontejneru a SBOM. Některé bezpečnostní úlohy jsou advisory;
zelené CI není zárukou nepřítomnosti zranitelností.

Kód je v `addon/src/`, testy v `tests/`, konfigurace v
`addon/config.yaml`. [ROLLOUT.md](ROLLOUT.md) popisuje ověření aktualizace.
Adresář `evidence/` uchovává historické podklady; není aktuálním návodem
k nastavení. Nové testovací podklady používejte syntetické nebo
anonymizované. Produkční odpovědi, přihlašovací údaje a session necommitujte.

Historie změn je v [changelogu](addon/CHANGELOG.md).
Projekt je dostupný pod [licencí MIT](LICENSE).
