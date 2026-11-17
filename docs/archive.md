# Historický archiv ČEZ PND

Archiv ukládá odpovědi PND a čtvrthodinové profily do
`/share/cez_pnd/measurements.sqlite3`. Je nezávislý na retenci HA Recorderu.
Nepublikuje nové MQTT entity a nearchivuje HDO ani ceny elektřiny.

## Zapnutí a výběr elektroměrů

Nejprve ověřte běžný PND/MQTT provoz. V konfiguraci aplikace přidejte
například následující hodnoty. ID a EAN jsou zástupné; nahraďte je údaji ČEZ.

```yaml
archive_enabled: true
archive_start_date: "2026-01-01"
archive_days_per_cycle: 1
archive_meter_ids: '["12345678","87654321"]'
import_ean: "859000000000000001"
export_ean: "859000000000000002"
```

Tento příklad představuje původní a nástupnický elektroměr **stejného
předávacího místa**. Pro MQTT lze ponechat jen aktuální elektroměr.
Všechna ID v `archive_meter_ids` dostanou stejnou explicitní dvojici
`import_ean` / `export_ean`; nevkládejte sem různé předávací body
s odlišnými dvojicemi EAN. Seznam přijímá nejvýše 32 číselných řetězců.

Pro nový archiv nastavte samostatný neprázdný seznam a oba EAN.
Při `archive_meter_ids: "[]"` se použije seznam publikovaných elektroměrů,
ale bez předání globální dvojice EAN; v takovém případě runtime potřebuje
již vyplněná metadata těchto elektroměrů v databázi.
Obecné `ean` pro HDO není automaticky EAN odběru ani dodávky.

Jestliže databáze metadata již obsahuje, používají se uložené hodnoty.
Rozpor s explicitní konfigurací vede k přeskočení daného elektroměru,
nikoli k přepsání jeho dvojice EAN. Není-li dvojice známá, archivace
elektroměru se přeskočí. Nevymýšlejte chybějící EAN ani kopii druhého směru;
nejprve údaje ověřte na portálu.

## Plánování a zatížení portálu

- Počáteční datum musí být `YYYY-MM-DD`. Zpracovávají se ukončené
  kalendářní dny v Europe/Prague, nejvýše do včerejška.
- `archive_days_per_cycle` je společný limit pokusů o den elektroměru
  pro celou dávku, 1–62. Jeden den může zahrnovat několik sestav/API dotazů.
- Elektroměry a dny se zpracovávají postupně, od nejstarších potřebných
  dnů. Při malém rozpočtu mohou pozdější elektroměry čekat na další cykly.
- Neúspěšný den má prodlevu nejméně dvě hodiny. Poslední čtyři ukončené dny
  se obnovují nejvýše jednou za pražský kalendářní den; stejné denní
  omezení platí pro plánovanou opravu koncových intervalů.
- Starší prázdné sestavy se mohou znovu načítat po sedmi dnech.
  Záznam úspěšného dotazu není zárukou naměřených dat.
- Při HTTP 403/429 nebo rozpoznaném odmítnutí portálu se dávka přeruší
  a PND dotazy se odloží na 12 hodin. Pauza je pouze v paměti procesu;
  restart ji zruší.
- Archiv běží po běžném PND/HDO zpracování a před čekáním na další cyklus.
  Velká dávka oddálí další načtení. Pro začátek ponechte limit 1.

Vypnutí `archive_enabled` zabrání otevření archivu runtime a dalším
zápisům; existující soubor se nemaže.

## Uložené tabulky a pohled

| Objekt | Obsah |
|---|---|
| `assembly_responses` | Vrácené odpovědi sestav, datum načtení, příznak dat a původní JSON. |
| `profile_intervals` | Zdrojové profilové řádky, pořadí, místní čas, výkony, kvality a raw JSON. |
| `meter_metadata` | ID elektroměru a dvojice importního/exportního EAN. |
| `fetch_attempts` | Poslední pokus pro den elektroměru a příznak úspěchu. |
| `pnd_combined_15m` | Normalizovaný pohled kombinující elektroměry stejné dvojice EAN. |

Při otevření se vytvoří chybějící schéma nebo upraví přesně rozpoznaná
starší definice pohledu. Neznámá definice stejnojmenného pohledu se odmítne.
Obnova profilu, která by ztratila existující platná měření, je neodstraní.

## Čas a kvalita

`import_kw` a `export_kw` jsou výkony v kW. Pro standardní 15minutový
interval je energie v kWh rovna výkonu × 0,25. `timestamp_local` a
`end_local_iso` označují **konec intervalu**; pro párování s cenou začátku
intervalu odečtěte 15 minut po správném převedení do časového pásma.

`end_local_iso` neobsahuje UTC offset. Interpretujte jej v Europe/Prague
a při opakované podzimní hodině zachovejte `occurrence`, pořadí a vazbu
na zdroj. Nejednoznačný čas nepřiřazujte svévolně k UTC.
Běžný den má 96 intervalů; při změně času může mít 92 nebo 100.

Profilový dotaz zahrnuje následující půlnoc. Zástupný koncový řádek
23:59 není platné půlnoční měření; pokud chybí skutečný koncový interval,
zůstane viditelná mezera.

| `quality` | Význam a zacházení |
|---|---|
| `OK` | Právě jedno měření obou směrů s uznanou kvalitou. |
| `VOLTAGE_OUTAGE` | Jedno měření označené výpadkem napětí; při analýze vykázat zvlášť. |
| `AMBIGUOUS` | Více naměřených kandidátů na stejný interval; výsledné výkony nejsou zvoleny. |
| `INVALID` | Bez použitelného měření a se známkou neplatnosti. |
| `UNDEFINED` | Bez použitelného měření, například nevyplněný nebo zástupný interval. |

Kontrolujte také `measured_count`. Chybějící, neplatné a nejednoznačné
intervaly se nesmějí nahrazovat nulou. MQTT zachování poslední hodnoty
nevyplňuje raw archiv.

## Příklady čtení SQL

Dotazy spouštějte nad databází otevřenou pro čtení. Tento souhrn odděluje
kvality a uvádí počet intervalů s oběma číselnými směry:

```sql
SELECT import_ean, export_ean, day, quality,
       COUNT(*) AS intervals,
       COUNT(import_kw) AS import_values,
       COUNT(export_kw) AS export_values
FROM pnd_combined_15m
GROUP BY import_ean, export_ean, day, quality
ORDER BY import_ean, export_ean, day, quality;
```

Součet pouze měření `OK` (může představovat neúplný den):

```sql
SELECT import_ean, export_ean, day, COUNT(*) AS ok_intervals,
       SUM(import_kw * 0.25) AS import_kwh,
       SUM(export_kw * 0.25) AS export_kwh
FROM pnd_combined_15m
WHERE quality = 'OK' AND measured_count = 1
GROUP BY import_ean, export_ean, day
ORDER BY import_ean, export_ean, day;
```

Počet platných řádků porovnejte s očekávaným počtem intervalů pro daný den
a předávací bod. Pohled může obsahovat více dvojic EAN; při jejich analýze
filtrujte nebo seskupujte i podle `import_ean` a `export_ean`.
Pokud SQL klient žádný den nevrátí, neznamená to nulovou spotřebu.

## Zálohy

Databáze používá WAL. Samotné kopírování živého souboru `.sqlite3` nemusí
obsahovat poslední změny. Použijte SQLite backup API nebo konzistentní kopii
při zastavených všech zapisovačích, včetně existujících WAL/SHM souborů.
Obnovu a migraci nejprve ověřte na kopii. Databázi ani její odpovědi
nezveřejňujte; obsahují soukromé identifikátory a měření.

Další postup je v [aktualizaci a návratu](pnd-consolidated-migration.md);
všechna nastavení popisuje [README](../README.md).
