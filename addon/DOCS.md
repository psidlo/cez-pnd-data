# CEZ PND — nastavení a používání

Aplikace načítá PND z portálu ČEZ a HDO rozvrh z DIP. Přes MQTT Discovery
vytváří 13 PND a 4 HDO senzorů pro každý publikovaný elektroměr.
Historická čtvrthodinová data lze volitelně uchovávat v SQLite.

## Základní nastavení

1. Vyplňte `email` a `password` účtu ČEZ.
2. Zadejte `electrometer_id` z portálu. Pro HDO doplňte `ean` odběrného
   místa. Tyto identifikátory nejsou zaměnitelné; automatické vyhledání ID
   není zajištěno.
3. Nastavte `mqtt_host`, `mqtt_port`, `mqtt_user` a `mqtt_password`.
   Broker musí být dostupný aplikaci i MQTT integraci HA. Pro Mosquitto
   v HA lze použít host `core-mosquitto` a účet povolený brokerem.
4. Pro první spuštění ponechte `archive_enabled: false`.
5. Spusťte aplikaci a zkontrolujte log a zařízení v integraci MQTT.

Port brokeru má výchozí hodnotu 1883. Neprázdné MQTT volby mají přednost
před odpovídajícími proměnnými prostředí; prázdný host používá prostředí,
případně `core-mosquitto`. Aplikace nezískává přihlašovací údaje automaticky
ze Supervisor API a konfigurace neobsahuje volbu MQTT TLS.

## Více publikovaných elektroměrů

Místo jednotlivého ID/EAN použijte JSON text:

```yaml
electrometers: '[{"electrometer_id":"12345678","ean":"859000000000000001"},{"electrometer_id":"87654321","ean":"859000000000000002"}]'
```

Jde o zástupné hodnoty. Seznam má přednost před samostatnými
`electrometer_id` a `ean`; vyžaduje jedinečné ID i EAN.
Každý elektroměr má vlastní zařízení, bez automatického sčítání.

## Volitelný archiv

```yaml
archive_enabled: true
archive_start_date: "2026-01-01"
archive_days_per_cycle: 1
archive_meter_ids: '["12345678"]'
import_ean: "859000000000000001"
export_ean: "859000000000000002"
```

Nahraďte zástupné hodnoty. Počáteční datum je při zapnutí povinné.
Neprázdný archivní seznam přijímá nejvýše 32 číselných ID jako řetězce;
obě EAN se přiřadí všem jeho měřidlům. Použijte jej například pro původní
a nástupnický elektroměr téhož místa, nikoli pro různé dvojice EAN.

Prázdný `archive_meter_ids: "[]"` použije publikované elektroměry,
ale vyžaduje jejich již uloženou importní/exportní dvojici v databázi.
Obecné `ean` tuto dvojici nenahrazuje; pro nový archiv použijte výslovný
seznam a obě ověřené EAN.

Archiv je v `/share/cez_pnd/measurements.sqlite3`.
Limit `archive_days_per_cycle` je 1–62 pokusů o den elektroměru,
společně pro všechny archivní elektroměry v cyklu; jeden den má více sestav.
Začněte hodnotou 1. Zpracovávají se ukončené dny do včerejška.
Při vypnutí se databáze neotevírá ani nemaže.

## Co znamenají senzory

PND poskytuje data se zpožděním. MQTT může pro každou veličinu zachovat
poslední hodnotu z odpovědi; online proto neznamená čerstvá měření.
Chybějící registry mohou být `unknown`; chybějící intervaly nejsou nuly.

Všechny entity jsou typu **sensor**, včetně HDO ON/OFF. HDO je výpočet
z denního rozvrhu, aktualizovaný při polling cyklu, nikoli fyzický HDO
kontakt. Další přepnutí po skončení dnešních hranic je odhad z dnešního
rozvrhu pro další den. Není náhradou fyzického blokování.

Odběr/dodávka jsou kW; denní energie a registry kWh.
Rv zůstává v kW bez potvrzeného fyzikálního významu; Ri/Rc se publikují
jako var bez jednotkové konverze. Před použitím těchto veličin ověřte
jednotky zdrojové sestavy.

Po skončení cyklu včetně archivu následuje čekání 900 sekund.
Při odmítnutí ČEZ se PND dotazy odloží na 12 hodin; restart tuto
pauzu resetuje. Výpadek HDO nemusí přerušit načítání PND.

Po opětovném připojení MQTT se obnoví discovery a online stav.
Při nečekaném odpojení pokrývá LWT jen první publikovaný elektroměr;
ostatní mohou ponechat online stav.

## Aktualizace a podpora

Zachovejte identitu aplikace a MQTT ID, provozujte pouze jeden publisher.
Před aktualizací zálohujte zdroje, privátní nastavení a konzistentní SQLite
včetně WAL dat. Samotná záloha aplikace nemusí obsahovat sdílený archiv.
Neznámé archivní schéma nebo konfliktní EAN vyžaduje kontrolu.

Při potížích ověřte broker, ID/EAN a dostupnost sestav na portálu.
Do veřejných hlášení nepřikládejte hesla, cookies, options, databáze ani
nezpracované odpovědi. Úplná konfigurace, SQL a postup návratu jsou v README
a adresáři docs ve stejné revizi zdrojového repozitáře.
