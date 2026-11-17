# Aktualizace a návrat

Tento postup platí pro aplikaci CEZ PND a její volitelný SQLite archiv.
Všechna [nastavení a význam senzorů](../README.md) ověřte před změnou
zdrojů nebo konfigurace.

## Před aktualizací

1. Zaznamenejte přesnou revizi zdrojů nebo obrazu, slug aplikace, boot režim,
   watchdog, výběr elektroměrů a nastavení brokeru. Soukromé hodnoty
   uchovávejte mimo veřejný repozitář.
2. Ověřte dostupné PND a HDO hodnoty, MQTT témata/unique ID a konzumenty
   (dashboardy, automatizace, SQL dotazy). Online stav neprokazuje čerstvost.
3. Pořiďte zálohu zdrojů, konfigurace a aplikačních dat. Je-li archiv
   používán, zahrňte jeho skutečný obsah v `/share/cez_pnd/`; samotná
   záloha aplikace nemusí sdílený adresář zahrnovat.
4. Pro SQLite použijte backup API nebo konzistentní kopii se zastavenými
   všemi zapisovači. Při studené kopii uchovejte související WAL/SHM soubory.
   Zálohu ponechte nedotčenou a obnovu/migraci vyzkoušejte na pracovní kopii.

## Identita instalace a MQTT

Manifest v `addon/config.yaml` používá slug `cez-pnd`. Místní instalace
může mít jinou identitu, například `cez-pnd-external`. Pro takovou instalaci
zachovejte její manifestovou identitu a soukromé nastavení; veřejný manifest
nekopírujte bez úpravy přes místní identitu.

Aktualizujte jednu existující instanci. Druhý publisher se stejnými ID
vytváří kolidující discovery a stavy. Stejné ID elektroměru používá stejné
MQTT identity v režimu jednoho měřidla i v seznamu `electrometers`.
Změna ID je změna identity senzoru, nikoli automatická migrace historie.

Stávající HDO ON/OFF entita je `sensor`. Témata dostupnosti jsou
`cez_pnd/{meter_id}/availability`; neupravujte je na společné téma.
Před změnou jednotek Ri/Rc nebo významu Rv ověřte skutečnou zdrojovou
sestavu a návazné statistiky; nepoužívejte neověřený přepočet.

## Aktualizace a ověření

1. Zastavte pouze aplikaci CEZ PND a ověřte, že neběží jiný zapisovač
   její databáze. Aktualizujte zdroje nebo obraz se zachováním identity.
2. Pro první ověření ponechte `archive_enabled: false`. Zkontrolujte
   připojení MQTT, discovery, běžný PND cyklus a HDO (pokud je nastavena EAN).
3. Sledujte dostupnost alespoň tři minuty i další běžné cykly. Ověřte
   korektní restart aplikace, návrat online a zachování entit.
   Sdílený MQTT broker kvůli tomuto testu nerestartujte.
4. Pro archiv ověřte výběr měřidel, datum a metadata import/export.
   Zapněte archiv s `archive_days_per_cycle: 1`.
5. Po skutečném archivním cyklu ověřte integritu, zachování původních
   řádků a metadat, kvality, nejnovější pokusy a délku celého cyklu.
   Nezaměňujte úspěšný dotaz s úplností profilu.

Archiv přijme jen známou definici pohledu `pnd_combined_15m`; neznámé
schéma nebo rozpor EAN vyžaduje kontrolu, nikoli vynucené přepsání.
Podrobnosti jsou v [návodu k archivu](archive.md).

## Kdy a jak se vrátit

Při ztrátě identity, chybě MQTT, nesouladu metadat, poškození databáze
nebo zhoršení načítání zastavte CEZ PND a nejprve uchovejte stav po změně
pro diagnostiku. Vraťte původní obraz/zdroje a konfiguraci stejné aplikace.

Databázi obnovujte jen tehdy, pokud je to potřebné. Zjistěte, která nová
měření by obnova odstranila, a uchovejte je předem. Obnovujte konzistentní
celek do čistého cíle se zastavenými zapisovači; nekombinujte starou DB
s novým WAL. Neobnovujte plošně HA ani sdílené soubory kvůli jedné aplikaci.

Po návratu ověřte boot/watchdog, MQTT a další cykly. Při odmítnutí ČEZ
respektujte dvanáctihodinovou pauzu: restart ji resetuje a není prostředkem,
jak opakovat blokované dotazy.

Úplný [kontrolní seznam](pnd-open-items.md) platí pro každou instalaci.
