# Kontrola provozu a známá omezení

Použijte po instalaci, aktualizaci nebo změně elektroměru.
Kritéria jsou postupem ověření, nikoli tvrzením, že automaticky prošla
v každém prostředí.

| Oblast | Co ověřit |
|---|---|
| Konfigurace | Účet, explicitní ID, platné JSON seznamy, potřebné EAN, broker a správná revize zdrojů. |
| Identita | Stejný slug aplikace a stejné MQTT unique ID, stavová i availability témata; jen jeden publisher. |
| PND | Skutečná odpověď portálu a její datum; známé hodnoty, registry, nuly a mezery zkontrolovat odděleně. |
| HDO | EAN, dnešní pražský rozvrh, přijetí timestampu v HA a rozdíl mezi výpočtem tarifu a fyzickým HDO kontaktem. |
| MQTT | Dostupnost alespoň tři minuty a v dalších cyklech; návrat online/discovery po restartu aplikace. To není samostatný test výpadku brokeru. |
| Archiv | Konzistentní záloha, ověřená migrace na kopii, integrita, zachování řádků a EAN a skutečný archivní cyklus s malým rozpočtem. |
| Ukončení | Korektní zastavení a ukončení MQTT, browseru a databáze; žádný druhý proces. |
| Čerstvost | Kontrola intervalů proti portálu; online nebo poslední zveřejněná hodnota není zárukou čerstvosti všech veličin. |

## Omezení důležitá pro uživatele

- **PND není živé lokální měření.** Nezveřejněné nebo chybějící intervaly
  nelze dopočítat nulou.
- **MQTT displej může ponechat poslední hodnotu.** Jednotlivé metriky
  mohou mít různé stáří a souhrnný čas je neodlišuje.
- **LWT patří prvnímu publikovanému elektroměru.** Při nečekaném odpojení
  není offline stav ostatních elektroměrů zaručený.
- **Více měřidel není automatická agregace.** Publikované ID i EAN musí
  být v seznamu jedinečné. Archiv má samostatný výběr a pravidla metadat.
- **Archiv je sériový.** Rozpočet je společný pro všechny elektroměry;
  velké dávky oddálí další běžný cyklus.
- **Pauza po odmítnutí je v paměti.** Restart zruší dvanáctihodinový cooldown.
- **HDO je odvozené z rozvrhu.** Hodnoty se aktualizují při cyklu;
  odhad zítřejší hranice nevychází z ověřeného zítřejšího rozvrhu.
- **Jednotky je nutné správně interpretovat.** Rv zůstává v kW bez
  potvrzeného fyzikálního významu; Ri/Rc jsou v discovery této implementace
  var bez konverze. Před výpočty ověřte sestavu ČEZ.
- **Zelené CI není bezpečnostní certifikace.** Některé bezpečnostní úlohy
  jsou advisory a syntetické testy nenahrazují provozní kontrolu.

Návody: [README](../README.md), [archiv](archive.md),
[aktualizace a návrat](pnd-consolidated-migration.md).
