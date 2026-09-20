"""One-time documentation update; remove after checked."""
from pathlib import Path

p=Path('ROADMAP.md')
s=p.read_text(encoding='utf-8')
a='''  - **Ej producerade ännu:** `budget_exhausted` och `cancelled` är deklarerade men inte nåbara — de hör till fortfarande öppna ruta två respektive ruta fyra. De är med nu för att kontraktet inte ska växa varje gång en gräns landar; ett test går igenom beslutstabellens hela indatadomän och visar att ingen kombination når dem. `no_progress` är här a priori-formen: evaluatorn fann inget en ny omgång kunde ändra. Att upptäcka att två varv gav *samma* output är en starkare kontroll som P1.1 äger.
'''
b='''  - **Senare täckning:** `budget_exhausted` produceras nu i budgeterade körningar efter #26 (`22e0990`). `cancelled` är alltjämt deklarerad men inte nåbar; avbrott hör till ruta fyra. `no_progress` är här a priori-formen: evaluatorn fann inget en ny omgång kunde ändra. Att upptäcka att två varv gav *samma* output hör fortfarande till P1.1.
'''
assert s.count(a)==1,s.count(a)
s=s.replace(a,b)
a='''- [ ] Inför max iterationer, wall-clock, modell-/verktygsanrop, tokenkostnad och outputstorlek. Alla gränser ska gälla även nested verktyg och retries.
'''
b='''- [ ] Inför max iterationer, wall-clock, modell-/verktygsanrop, tokenkostnad och outputstorlek. Alla gränser ska gälla även nested verktyg och retries.
  - **Delvis i #26 (`22e0990`), verifierat i testworkflow `35532804065` på `main`:** opt-in `RunLimits`/`RunBudget` räknar modell- och explicita verktygsanrop, rapporterad faktisk tokenanvändning och ackumulerade UTF-8-outputbytes över retries. Begränsning ger `budget_exhausted`; okänd tokenanvändning ger `tool_error`, inte en gissning. Minnesadapter utan budgetkontrakt läses eller skrivs inte i begränsad körning. Även `mypy` och `pyright` har verifierats gröna på integrationsgrenen (`35532737474`).
  - **Återstår innan kryss:** aktivera och testa gränser i det faktiska CLI-standardflödet och alla nästlade verktyg; en obligatorisk capability/tool-gateway som delar budgeten, inklusive läsningar och memory; faktisk tokenkostnad/valuta när relevant. Core kan endast kontrollera en monoton tidsgräns *mellan* synkrona steg. Adaptern måste själv avbryta ett pågående anrop vid deadline; utan det finns ingen hård wall-clock-timeout. Detta är uttryckligen inte en sådan garanti.
'''
assert s.count(a)==1,s.count(a)
s=s.replace(a,b)
p.write_text(s,encoding='utf-8')
print('Roadmap P0.3 updated with merge references, partial boundaries and open boxes.')
