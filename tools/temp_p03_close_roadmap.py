"""ONE-TIME guarded migration; remove with its workflow before merging."""
from pathlib import Path

roadmap = Path('ROADMAP.md')
source = roadmap.read_text(encoding='utf-8')
start_tag = '### P0.3 Terminalsäkerhet och resurser\n'
end_tag = '## P1 — v1.2 Första verkliga uppgiftsloopen\n'
assert source.count(start_tag) == 1 and source.count(end_tag) == 1
begin = source.index(start_tag)
end = source.index(end_tag, begin)
previous = source[begin:end]
assert previous.count('- [ ] Inför max iterationer') == 1
assert previous.count('- [ ] Fail-closed för skrivning') == 1
assert previous.count('- [ ] Testa prompt injection') == 1
replacement = '''### P0.3 Terminalsäkerhet och resurser

- [x] Versionera explicit state machine och stopporsaker: `passed`, `insufficient_evidence`, `blocked`, `approval_required`, `budget_exhausted`, `max_iterations`, `no_progress`, `tool_error`, `cancelled`. Skilj runtime-fel från saklig evaluering.
  - **Verifierad i #24:** `atlas_core/machine.py` och `schemas/atlas-state-machine.v1.json` håller tillstånd, övergångar, nio stopporsaker, klasser och exitkoder i synk. `state.stop()` härleder terminalstatus ur samma tabell. #27–#31 producerar även `budget_exhausted`, `cancelled` och identisk-output-varianten av `no_progress`; den tidigare noteringen att dessa var onåbara gäller inte längre.
- [x] Inför max iterationer, wall-clock, modell-/verktygsanrop, tokenkostnad och outputstorlek. Alla gränser ska gälla även nested verktyg och retries.
  - **Verifierad på stödda begränsade gränssnitt i #26–#28, #30–#31.** En `RunBudget` delas av modellanrop, nästlade verktyg och retries; läsningar och output belastar samma kvoter. Publikt `atlas run` på POSIX har överordnad process, hård monoton deadline och terminering av processgruppen. Anropare av Python-API:t som behöver hård deadline använder uttryckligen `run_isolated(..., limits=RunLimits(...))` med serialiserbara, betrodda adaptrar. In-process `AtlasController.run(...)` har bara kooperativ tidskontroll, och `limits=None` är obegränsat legacyläge. Windows stöds inte av den hårt begränsade CLI-vägen förrän processgrupps-/Job-Object-motsvarighet finns; den vägen vägrar hellre körning än låtsas ha en hård gräns.
- [x] Fail-closed för skrivning: inga verktyg med sidoeffekter i read-only mode; mänskligt godkännande knyts senare till exakt diff/kommando/repo/ref och upphör när underlaget ändras.
  - **Verifierad för Atlas-hanterad verktygsdispatch i #27.** Oregistrerade verktyg samt `write`/`network` nekas före handler-anrop; prompttext, README och ett påstått godkännande ger ingen behörighet. Inget godkännandetoken eller skrivläge finns i P0.3. Godtycklig betrodd Python-kod kör med användarens OS-behörigheter och kan gå förbi gatewayn: varken workerprocessen eller `run_isolated` är en OS-sandbox. Ogranskade adapters kräver separat minimerade OS-rättigheter, read-only mounts och nätverkspolicy innan de får köras.
- [x] Testa prompt injection i README och verktygsoutput, nätverksfel, timeout, abort, oändlig förbättring utan progress, felaktigt JSON och samtidiga körningar. Output från repo är *data*, inte instruktion.
  - **Negativa regressioner verifierade i #27–#31:** injicerad README/verktygsoutput kan inte starta skrivhandler; nätverks- och JSON-fel ger aldrig tyst fallback till PASS; nästlade/samtidiga kvoter delas korrekt; abort och hängande worker dödas via processgränsen; upprepad oförändrad modelloutput stoppas `no_progress`. CI kör enhetstester, mypy och pyright på varje PR samt `main`.

**P0.3 klar för stödda, explicit begränsade gränssnitt.** Säkerhetskontraktet gäller publikt POSIX-CLI och `run_isolated` med betrodda, serialiserbara adaptrar. Det omfattar inte `--unsafe-legacy-unbounded`, obudgeterad Python-API, godtycklig icke-isolerad callback, Windows hårda CLI eller ett OS-sandboxat skrivskydd. Se `docs/safety-model.md` för exakt tillitsgräns; framtida utvidgningar är separata arbetsposter, inte redan uppfyllda garantier.

**P0 exit gate prövas separat:** en osann verifierbar claim får inte `passed`, besluten ska kunna följas till snapshot/evidence, och Atlas-hanterade read-only-skrivförsök nekas vid dispatch. Denna P0.3-ändring ensam stänger inte eventuella återstående P0.1/P0.2- eller OS-sandboxkrav.

'''
roadmap.write_text(source[:begin] + replacement + source[end:], encoding='utf-8')

safety = Path('docs/safety-model.md')
text = safety.read_text(encoding='utf-8')
anchor = '## Boundaries not provided by this implementation\n'
assert text.count(anchor) == 1
isolated = '''## Hard-isolated Python API (explicit opt-in)

`from atlas_core import run_isolated` exposes
`run_isolated(controller, task, limits=RunLimits(...))` for hosts supplying
**trusted and spawn-picklable** model, reader and tool handlers. The process
uses Python `spawn`, starts a new POSIX session before callbacks execute, and
returns one versioned run document over capped JSON IPC. The parent applies a
hard monotonic deadline including startup, polls cancellation, kills the whole
worker process group on timeout/abort and rejects malformed or absent output
rather than promoting a partial answer. The child uses the same RunBudget for
all nested tool calls, retries and observations. Unpicklable callbacks fail
closed as `tool_error`. See `tests/test_p03_isolation.py` for non-cooperating
Python adapter, cancellation, nested quota and provider-failure regressions.

This boundary does **not** modify the compatible in-process `run()` API and
does **not** restrict the worker's OS privileges. A malicious installed adapter
can access filesystem/network APIs directly and may perform irreversible
side effects before the parent kills it. Only trusted adapters are in scope;
untrusted code needs a separately configured low-privilege sandbox with
read-only mounts/network policy. Windows currently fails closed for this API.

'''
text = text.replace(anchor, isolated + anchor)
text = text.replace('using custom adapters MUST enforce a separate worker-process deadline and\n  terminate its descendants, as the public POSIX CLI does, or supply an\n  equivalent external isolation contract.',
                    'using custom adapters MUST use `run_isolated` with trusted,\n  spawn-picklable callbacks or provide an equivalent external process deadline\n  and descendant termination contract.')
text = text.replace('`tests/test_p03_hard_cli.py` exercise denied mutations,',
                    '`tests/test_p03_hard_cli.py` and `tests/test_p03_isolation.py`\nexercise denied mutations,')
text = text.replace('The supported POSIX *public CLI* has a demonstrable hard worker deadline.\nThis does **not** make arbitrary in-process `AtlasController.run(...)` or\nexternally installed adapters sandboxed. P0.3 roadmap completion must state\nwhich interface is covered and must not silently count the legacy API as\nbounded.',
                    'The supported POSIX public CLI and explicit `run_isolated` API have\ndemonstrable parent-enforced deadlines. The in-process/legacy APIs remain\ncooperative or unbounded. Neither process boundary is a filesystem/network\nsandbox for arbitrary external Python; P0.3 completion is scoped accordingly.')
safety.write_text(text, encoding='utf-8')
print('guarded P0.3 roadmap/safety update applied')
