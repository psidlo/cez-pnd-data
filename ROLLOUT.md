# Ověření instalace a aktualizace CEZ PND

## Příprava

- Ověřte verzi/revizi, sestavení obrazu a výsledky příslušného CI.
- Projděte [nastavení](README.md), zejména ID elektroměru, EAN a MQTT účet.
- Připravte konzistentní zálohu a vyzkoušený návrat podle
  [migračního návodu](docs/pnd-consolidated-migration.md).
- Zaznamenejte existující identity a konzumenty; provozujte jeden publisher.

## První spuštění

1. Nejprve ověřte PND a MQTT s vypnutým archivem.
2. Zkontrolujte vytvořené zařízení a 17 definic senzorů na elektroměr.
   Chybějící hodnoty portálu mohou být neznámé; nejsou důvodem k doplnění nul.
3. Při nastaveném EAN ověřte dnešní HDO rozvrh, typ sensor/ON/OFF
   a timestamp v HA.
4. Sledujte MQTT déle než tři minuty a přes další běžné cykly.
   Změřte délku cyklu: 900 sekund čekání začíná až po jeho dokončení.
5. Ověřte korektní zastavení a opětovný start samotné aplikace.

## Volitelná archivace

Zapněte ji až po předchozím ověření a s limitem jednoho dne za cyklus.
Zkontrolujte skutečný zápis, integritu, zachování metadat a předchozích
měření, kvalitu a časové pokrytí. Postup a SQL jsou v
[návodu k archivu](docs/archive.md). Při vysokém zatížení dávku nezvětšujte.

## Vyhodnocení

Použijte [kontrolní seznam provozu](docs/pnd-open-items.md).
Při regresi uchovejte diagnostiku bez zveřejnění soukromých údajů
a vraťte konkrétní aplikaci podle migračního návodu.
Při odmítnutí ČEZ respektujte cooldown a neprovádějte restartovací smyčky.

Syntetické testy, kontrolovaný restart a skutečný výpadek brokeru jsou
různé zkoušky. Uvádějte, které opravdu proběhly. Testy externího portálu
vyžadují vlastní oprávněný účet a nenáleží do běžného offline CI.

Tento postup neslibuje termíny budoucích vydání ani automatické nasazení.
Historie změn je v [changelogu](addon/CHANGELOG.md).
