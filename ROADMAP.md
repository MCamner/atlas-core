# Atlas Core — roadmap för Atlas 2.0

> Status: plan, inte leveransbevis. Uppdaterad 2026-09-19. Ägare: Atlas Core. Prioritet: P0 blockerar säker/korrekt användning, P1 behövs för användbar end-to-end-loop, P2 för bredd och produktisering. Inga kalenderlöften. Varje ruta stängs endast med länkad PR, test och observerat resultat.

## Mål och gränser

Bygg en **fristående, evidensgrundad och begränsad agentloop**: observera → routa → planera → utföra → kontrollera mot verkliga källor/tester → omplanera eller stoppa. `atlas-one` är UI/intent och ska konsumera ett versionerat run-API; `atlas-core` äger tillstånd, beslutsflöde, evaluering, stopregler och adapterkontrakt. `mq-agent`, `mq-mcp`, `mqobsidian`, GitHub, lokala modeller och molnmodeller är *valfria adaptrar*; `atlas-loop` är en separat Instagram-produkt som får återanvända Core via adapter. Ingen koppling till MQ får behövas för att köra Core-tester.

**Icke-mål:** ersätta MQ:s governance/evidence-integritet, ge en LLM oinskränkt shell/Git-rättighet, låta en modell själv godkänna sina ändringar, automatpublicera eller påstå att en källhänvisning bevisar att ett påstående är sant. Första användningsfallet är **skrivskyddad repogranskning** med uppgiftsspecifik verifiering. Skrivande arbetsflöden får egen senare gate.

## Verifierad baslinje vid planering

- `v1.0.0` är dokumenterad som släppt i `CHANGELOG.md`/`README.md`: routing, plan, regelbaserad executor, bounded loop, versionerade run/route/evaluation/memory-scheman, stop reasons, model-adapterkontrakt, mqobsidian-adapterskelett, GitHub/lokala repoobservationer, Actions-runner och skill-generator. Modelladapter **betyder inte** att en live LLM-provider levereras som standard.
- `CHANGELOG.md` → `Unreleased`: första P1-evidensgaten för `repo_review` finns. Den kontrollerar att findings *nämner observerade källor*, inte att påståendena faktiskt överensstämmer med filinnehåll. `atlas_core/evaluator.py` säger uttryckligen detta. `controller.py` har redan feedback från förra iterationen och stop reasons.
- `CHANGELOG.md` → `Unreleased`: terminalstatus är åtskild från saklig evaluering. En modelladapter som kastar eller returnerar en trasig `ModelResult` avslutar körningen som `failed`/`failed` med `metadata.failure`, **utan** att falla tillbaka på den regelbaserade executorn — en mall serverad som modellsvar vore en falsk framgång. Ett runtime-fel producerar noll evaluations, så det kan inte förväxlas med ett underkänt resultat. `atlas run` returnerar numera exitkod per terminaltillstånd (0/1/2/3), dokumenterad i `docs/api-contract.md` och driftskyddad av test. Timeout är **inte** löst: `execute()` är synkron och kärnan kan inte avbryta ett pågående anrop, så deadline ligger hos adaptern. Se P0.3.
- Skilj `implemented`, `documented`, `tested locally`, `CI passed`, `released` och `validated against real repo`. Omarkerade rutor nedan är **framtida arbete**, inte ett påstående om att dagens kod saknar alla delkomponenter.

### Källor i detta repo

`README.md`, `CHANGELOG.md`, `atlas_core/controller.py`, `atlas_core/evaluator.py`, `docs/safety-model.md`, `schemas/`, `tests/`. Om baslinjen ändras: återgranska filer på aktuell `main`, skriv en changelogpost och justera checklistan; lita inte på versionsraden ensam.

## Prioritering och releaseordning

| Fas | Leverans | Varför före nästa fas | Definition of Done |
| --- | --- | --- | --- |
| P0 / v1.1 | Pålitlig observation + sanningsenlig evidens + säker terminalstatus | Annars kan loopen godkänna påhittade fynd | Negativa tester stoppar osanna, stale och okända bevis; run-logg kan granskas |
| P1 / v1.2 | Verklig read-only repo-review-loop med modelladapter | Första användbara end-to-end-fallet | Två varv förbättrar en mätbar brist; reproducerbara fixtures och verkligt repo |
| P1 / v1.3 | Adapterkontrakt, beständig state och begränsade verktyg | Gör loopen robust och integrerbar | Resume, timeout, budget och felklassning verifieras |
| P1 / v1.4 | Atlas One + MQ-adaptrar | Kopplar UI och befintlig stack utan omvänt beroende | Kontraktstester + separat integrationstest; Core kör ensam |
| P2 / v1.5 | Godkända skrivflöden, observerbarhet och feedback | Utökar nyttan utan att bryta säkerhetsmodellen | Human approval, diff och rollback före mutation |
| P2 / v2.0 | Stabil produktionsgräns | API/operativ driftsättning | Release-gates, migration, dokumenterad support och pilotresultat |

Versionsnummer är **mål**, inte publicerade releaser. En säkerhets- eller kontraktsbrist blockerar promotion oavsett antal ikryssade uppgifter.

## P0 — v1.1 Evidensintegritet och säker kärna

### P0.1 Observationer med proveniens

- [x] Definiera `Observation.v1`: `source_id`, typ (local-file/GitHub/CI/memory), repo/ref/commit eller lokal snapshot-id, sökväg, insamlad tid, content hash, läst utdrag + line range och sekretessklass. Använd explicit `unknown` där fält inte kan verifieras.
  - Stängd av [#15](https://github.com/MCamner/atlas-core/pull/15). `atlas_core/observation.py`, `schemas/atlas-observation.v1.json`, `tests/test_observation.py` (24 tester). Overifierade fält blir `unknown`; tomt och blanksteg avvisas, liksom trasig digest och okänd enum. Validering ligger i `__post_init__`, så `dataclasses.replace` inte kan skriva förbi den, och `source_id` omderiveras så en observation inte kan riktas om till en annan sökväg.
- [x] Läs en konsekvent snapshot för en run; upptäck ändrad HEAD/fil under läsning och märk `stale` eller avbryt; blanda inte `main` och arbetsgren utan tydlig separation.
  - **Verifierad i #32 (`07d45a2`), med grön test-CI på PR:en och beteendet observerat i en körning mot det här repot.** [#16](https://github.com/MCamner/atlas-core/pull/16) gav `take_snapshot`, `verify_observation` och `detect_drift`, och ingenting i en körning anropade dem. Halvan som var täckt var täckt av en slump: en citatkontroll läser om det den pekar på, så en *citerad* källa som flyttat fastnade där. En källa inget fynd råkade citera, eller ett HEAD som flyttade medan modellen tänkte, fastnade ingenstans.
  - `AtlasController` kör nu en driftgrind **efter** gradering. En körning vars snapshot inte längre håller stoppar `blocked` — kontrollstopp, marken flyttade sig i stället för att svaret var fel — och `metadata.drift` bär `head_moved`, verifieringsresultat per källa och sökvägarna bakom de id:na.
  - Efter gradering, inte före: en tidigare vägran sparar ett modellanrop och kostar posten per fynd som säger *vilket* påstående som vilade på det som flyttade. Den skulle dessutom slå till olika beroende på om roten råkar vara ett git-checkout, eftersom en redigering där också vänder clean till dirty. Utvärderingen står kvar som historik; körningen slutar ändå `blocked`.
  - Det avslöjade en ny fälla: ett fynd kan hålla mot en orörd README medan en annan källa flyttat, så slutraden kunde läsa "Status: passed" bredvid "Stop reason: blocked". Den namnger nu vad som flyttade och säger att betyget beskriver det tillstånd som lästes.
  - **Gränsen är prövad, inte antagen:** en grenetikett på samma commit är *inte* drift — ingen byte körningen vilar på ändrades. Separationen hålls av att ref:en redovisas och av att `EvidenceBase` vägrar observationer från mer än ett snapshot. Kvar som känd gräns: grinden är inte separat mätt mot budgeten, eftersom den läser om exakt de observationer anroparen lämnade in — en mängd som är fast innan körningen börjar och som varken modell eller verktyg kan växa. Deadline och cancel gäller fortfarande.
- [x] Lagra begränsade, sanitiserade utdrag i observationsmanifest; koppla varje finding till `source_id` och exakt utdrag. Klipp inte bort just den kontext som behövs för att kontrollera påståendet.
  - Manifestdelen stängdes av PR C: `redacted_manifest()` med begränsade och maskerade utdrag, snapshot-proveniens och per-post verifieringsstatus, utan `snapshot.root`.
  - **Kopplingen verifierad i #32 (`07d45a2`).** `Finding.v1` (#18) gav varje citat ett `source_id`, och id:t går att slå upp i samma körnings manifest. Det som saknades var *utdraget*: en läsare med ett id visste vilken fil som citerades och inte vilka rader påståendet vilade på, utan att läsa om filen och gissa vilken del som avsågs. `citation_checks[].statuses` bär nu `line_start`, `line_end` och `quoted` bredvid statusen.
  - Spannen kommer från fyndets egna citat, aldrig kopierade från observationen — en kopia skulle göra varje citat trivialt korrekt — och en längdavvikelse *kastar* i stället för att fästa ett citats spann på ett annats utslag. `schemas/atlas-evaluation.v1.json` deklarerar fälten, och ett test jämför det emitterade citatet mot schemat: de befintliga schematesterna kör utan evidensbas, så det objektet var aldrig kontrollerat.
- [x] Redigera tokens, privata paths och persondata före run-artifact/export; råa källor förblir lokala. Negativa tester för injicerade hemligheter och symlänkar/path traversal.
  - Maskering och vägrade sökvägar kom med PR C. **#32 (`07d45a2`) stänger de tre resterande delarna.**
  - **Containment gäller nu varje läsning.** `Observation.path` vägrar absolut form och `..`-komponent redan vid konstruktion, i både POSIX- och Windows-stavning, så en post som namnger en fil utanför sitt snapshot inte kan finnas. `verify_observation` läser genom `read_within` som allt annat och rapporterar det nya resultatet `refused` när en komponent blivit en länk efter att namnet skrevs. Den slutar också gissa för en källa den inte kan läsa om: en `ci`-sökväg är en identifierare, inte ett filnamn, och att foga den till en lokal rot kunde träffa en orelaterad fil och rapportera om den.
  - **`confidentiality` härleds ur innehållet** vid insamling: `secret` för en nyckelform, `internal` för persondata, annars `unknown`. Aldrig `public` automatiskt — detektionen är smal, så ingen träff säger något om mönstren och inget om källan. En anropare som anger en klass överrides inte.
  - **Maskeringen täcker hela det exporterade run-dokumentet**, inte bara manifestet. Prosakanalen `observations` och outputen som upprepar den lämnade tidigare ordagrant, så en körning med rent manifest kunde publicera samma nyckel ett fält bort. Två tester påstod den läckan som känt beteende; de påstår nu maskeringen.
  - Två lövmoduler gör det möjligt utan importcykel: `redaction` (vad som är känsligt) och `containment` (var en läsning får gå). Båda behövs under insamlingslagret såväl som över det, vilket är exakt varför verifieringsläsningen var oskyddad medan exporten inte var det. `integrity` återexporterar namnen.
  - **Kvar som känd gräns, inte som öppen ruta:** detektionen är smal och godtyckliga personuppgifter känns inte igen — därför svarar klassificeringen aldrig `public`. En **katalogkomponent** i en sökväg kan fortfarande bytas mellan resolve och open, vilket skulle kräva en `openat`-vandring per komponent (eller Linux `openat2(RESOLVE_BENEATH)`, som Python inte exponerar). Innehåll kan alltid ändras mellan en kontroll och en senare läsning; integritet återetableras genom omverifiering, aldrig genom att lita på en tidigare kontroll.

**P0.1 stängd.** Observationer bär proveniens eller säger `unknown`, varje läsning är inhägnad, varje fynd går att följa till källa och rader, exporten är maskerad i sin helhet, och en körning vars underlag flyttar sig stoppar i stället för att svara om ett tillstånd som inte längre finns. Gränserna ovan är redovisade som gränser, inte som uppfyllda garantier.

### P0.2 Verifiering ≠ citering

> Fyra av fyra rutor verifierade på `main` efter #20, #22 och #23. #22 mergad som `733588e`; #23 som `a4e1ef2`, med grön test-CI efter varje merge. PR E ([#20](https://github.com/MCamner/atlas-core/pull/20)) mergats som `99770bc`, med `Ran 283 tests ... OK` i testworkflowen på `main` och beteendet observerat i en körning mot det här repot: ett sant typat påstående om README gav `verified`, ett falskt gav `contradicted`, och ett om text bortom det observerade utdraget gav `contradicted`.
>
> **Ruta tre:** #22 är mergad, och slutrapportens fakta/hypotes/rekommendation testas i `tests/test_claim_ledger.py`.
>
> **Ruta fyra:** #23 är mergad. `tests/test_ci_observations.py` visar att även en grön omkörning är en ny, inaktuell källa för det tidigare citatet. Övriga fall i rutan (falskt fynd som citerar en verkligt läst README, fel SHA, fel radintervall, cherry-pickat utdrag, tomma källor, saknat resultat) hade redan tester.
>
> **Vad de kryssade rutorna betyder, och inte.** De gäller *verifierade literalpåståenden*, inte bredare slutsatser om ett repo. `verified` kan bara nås genom ett typat påstående där påståendet *är* predikatet — `source_contains_literal` eller `source_lacks_literal` över citerade, observerade rader — och den läsbara meningen härleds ur objektet, så prosan inte kan säga mer än det som prövades. Ett påstående som inte går att uttrycka så kan inte verifieras här alls: det blir `insufficient_evidence`, vilket är rätt svar och samtidigt gränsen för vad fasen räcker till. En grön körning betyder "varje fynd var formulerat så att det gick att avgöra, och avgjordes till sin fördel mot lästa rader" — inte att granskningen är fullständig.
>
> Kvar öppet i övrigt: fri text ger `insufficient_evidence`; ett producentdeklarerat `claim_check` är diagnostik (`condition_supported`/`condition_refuted`) och kan aldrig ge ett verdikt. Villkor matchar literal text, inte reguljära uttryck. En stale källa avgör ingenting i någon riktning. Prosakanalen `observations` exporteras fortfarande ordagrant — en egen säkerhetslucka, inte en del av P0.2.

- [x] Definiera `Finding.v1`: claim, scope, severity med motivering, evidence IDs, verifieringsmetod, verifieringsresultat (`verified`/`contradicted`/`insufficient_evidence`), begränsningar och reproducerbart kommando om relevant.
- [x] Låt evaluator kontrollera att refererade ID:n existerar i denna run, att utdrag och line range matchar snapshot och att påståendets kontrollerbara del stöds av källan/testet. Om semantisk verifiering inte kan göras: `insufficient_evidence`, aldrig `verified` på enbart filnamn.
  - Kontrollerbar del = det som går att uttrycka som literal närvaro eller frånvaro över observerade rader. Allt annat blir `insufficient_evidence`, aldrig `verified`.
- [x] Separera fakta, hypotes och rekommendation. En modellbaserad verifierare måste kompletteras med deterministiska kontroller/tester; modellens eget självomdöme får inte ensamt ge PASS.
  - **Verifierad i #22 (`733588e`) och på `main`.** Slutrapporten bär en **claim ledger**, härledd ur körningsdokumentet och inte ur texten ovanför: `FACT` för ett påstående avgjort mot observerade rader, `REFUTED` när källan säger emot, `HYPOTHESIS` för allt annat — inklusive prosafynd kontrollen aldrig såg. Rekommendationer listas inte alls där, med en rad som säger varför. Producentens brödtext lämnas orörd; ledgern är en separat, auktoritativ vy.
  - `## Findings` accepteras nu före `## Verified findings`. En rubrik är ingen verifiering, och en som kallar sitt innehåll verifierat hävdar precis det körningen ska fastställa. Den äldre rubriken fungerar fortfarande.

- [x] Testa falskt fynd som citerar en verkligt läst README, fel SHA/linje, cherry-pickat utdrag, stale CI, tomma källor och saknat resultat. Alla ska bli FAIL/INSUFFICIENT_EVIDENCE.
  - **Verifierad i #23 (`a4e1ef2`) och på `main`.** `atlas_core/ci.py` samlar in ett CI-resultat med proveniens — provider, workflow, run id, ref, commit, slutsats och tidpunkt — och hashar exakt de fälten, så digesten ändras när *resultatet* ändras och inte när ett API svarar i annan ordning. Källan läses om genom sin adapter, aldrig ur en cache: en cachad kopia skulle göra varje CI-citat permanent färskt, vilket är just felet rutan pekar på. Ett test citerar en grön körning, låter någon köra om workflowet rött, och visar `stale_source` och `passed=False` genom `AtlasController`. En omkörning som blir grön igen är också `stale_source` — identiteten är körningen, inte slutsatsen den råkade ge.
  - Läsningen är nu typbunden: `SourceReader` per källtyp, där `local_file` alltid finns och inte kan ersättas av en anropare — en som kunde det skulle äga containment och färskhet för varje lokalt citat i körningen. En källtyp utan läsare avvisas som `unsupported_source_type` i stället för att gissas.

### P0.3 Terminalsäkerhet och resurser

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

## P1 — v1.2 Första verkliga uppgiftsloopen

### P1.1 Repo-review som vertikal slice

- [ ] Inför en begränsad `repo_review`-plan: välj snapshot → identifiera konkret fråga → läs relevanta filer/tester/CI → samla fynd → verifiera → föreslå nästa *skrivskyddade* undersökning eller avsluta.
  - **Delvis: observationsflödet finns, planformen inte.** Stegen "läs relevanta filer", "verifiera" och "föreslå nästa skrivskyddade undersökning eller avsluta" är nu en faktisk loop. `AtlasController.run(observer=...)` låter hosten läsa om mitt i körningen när marken flyttat sig eller när nästa åtgärd är `observe_again`, och nästa varv graderas mot det som kom tillbaka.
  - Fyra regler håller, och de är vad som gör en mittlöpande läsning till *evidens* i stället för indata: ett snapshot per körning — en observation bunden till ett annat avvisas och körningen slutar `tool_error`; en ändrad källa byts aldrig in tyst — omläsningen registreras som supersession med *båda* digesterna, raderna ett tidigare påstående vilade på står kvar i den iterationens `citation_checks`, och ett nytt fynd som citerar den gamla digesten faller på `digest_mismatch`; inget nytt är ingen retry — en runda som ger noll eller samma bytes köper inget varv, körningen stoppar `blocked` med rundan på pränt; fail-closed — timeout, onåbar källa eller bruten snapshot-koppling avslutar körningen som `tool_error`, en runtime-klass som redan är definierad som *inte* ett utslag om ett svar, och en misslyckad runda producerar ingen observation och kan därför inte bli ett fynd.
  - Observatören kräver `RunLimits` av samma skäl som Atlas-hanterade läsare: det finns ingen omätt läsväg. Det hosten returnerar belastar samma outputbudget som allt annat. `run_isolated` bär observatören in i den föräldrastyrda hårda deadlinen; in-process är kontrollen kooperativ, precis som för en modelladapter.
  - `evaluating → observing → replanning` är nya kanter i tillståndsmaskinen. `observing` betyder redan "körningen läser", så det är kanter snarare än betydelser som tillkommer och den publicerade versionen står kvar.
  - **Planformen finns nu också.** `plan.review` bär den snapshot granskningen gäller, frågan i en mening, och de glob-mönster frågan behöver. Planen *binder* till en snapshot i stället för att ta en — att ta en är att läsa, och läsning är hostens. Källor är mönster, inte sökvägar, eftersom Core inte listar kataloger; hosten löser upp mönstret och läser det den hittar, vilket är samma arbetsdelning som observationsloopen redan använder och skälet till att detta återanvänder den loopen i stället för att odla en andra.
  - En uppgift som inte matchar något ämne rapporteras som *inte avgränsad*: frågan blir uppgiften själv och inga källor namnges. Att hitta på en rimlig fråga skulle skicka hosten att läsa filer ingen bett om och sedan gradera svaret mot en fråga ingen ställt. Nytt kriterium `plan_targets_read`, gapkod `plan_targets_unread`, och en nästa åtgärd som är **hostens** — ett fynd kan inte förbättras till en källa ingen läst.
  - Ett mönster räknas som besvarat när en observation ligger under det *eller* när en host ombetts lösa upp det och kommit tillbaka — med noll träffar, om repot saknar sådan fil. Core kan inte skilja "finns inte" från "inte läst än" utan att lista kataloger; hosten kan, och en genomförd runda är det svaret.
  - **Verklig omfattning:** ämnesvalet är nyckelordsmatchning mot en deklarerad vokabulär om fem ämnen. En verklig mekanism och en smal: ingen modell ingår, och en uppgift formulerad med ord vokabulären inte bär rapporteras som `unknown` i stället för att gissas. Planen väljer inte heller *tester och CI-körningar* som separata källslag — den namnger sökvägsmönster, och ett CI-resultat kommer in som `ci`-observation via sin egen adapter.
  - **Kryssas vid merge**, enligt stängningsregeln: koden mergad, negativa tester gröna på `main`, och det här stycket beskriver den verkliga omfattningen. End-to-end-testet finns i `tests/test_review_plan.py` och visar båda grenarna — evidensgap → relevant läsning → verifierat fynd, och samma gap utan host → motiverat stopp.
- [ ] Välj ett litet, fast fixture-repo med kända defekter och ett utan defekter. Mät precision mot facit, andel evidensbelagda findings, falskt positiva, iterationsantal, kostnad och stopporsak.
- [ ] Sätt explicit exit criteria per task i stället för generell textlängd/rubriker. Ingen finding med okänd täckning får tilldelas verifierad severity.
  - **Andra kravet är uppfyllt.** En producent deklarerar `P1` innan något kontrollerats. Siffran överlever kontrollen bara på verdict `verified` och blir annars `unknown` — även på `contradicted`, eftersom en vederläggning väger en påverkan för något som inte är fallet. Det producenten sa bevaras i `Finding.declared_severity` bredvid sin motivering: att tappa den vore att kasta en bedömning, att presentera den som fastställd är det som inte får ske.
  - **Den generella poängen som grind är borta.** Varje route deklarerar namngivna kriterier i `EXIT_CRITERIA` och *alla* måste vara uppfyllda — ingen viktning, eftersom ett krav som kan röstas ner av andra krav inte är ett krav. `passed` är exakt `unmet_criteria == [] and not requires_user_approval`. `quality_score` är andelen uppfyllda och *rapporterar*; inget jämför den mot en tröskel. `PASS_THRESHOLD`, `SECTION_WEIGHTS` och evidensfaktorn är borttagna, inte deprecierade.
  - Det rättade samtidigt en konkret orimlighet: under den viktade poängen kunde ett svar passera med en sektion som routen själv krävt saknad. `repo_review` deklarerar inte heller `substance` — en kort granskning vars fynd avgjorts mot observerade rader är klar, och ord är inte det som gör den klar.
  - **Rättat i efterhand:** den första versionen lät `repo_review` uppfylla `claims_are_settled` på den äldre citation-only-vägen, där ett fynd bara behöver *nämna* en läst källa. Kriteriet markerades som ej uppfyllt enbart när en explicit gapkod kom, och den vägen ger ingen — så tre kriterier rapporterades uppfyllda bredvid ett tomt `citation_checks`. Själva PASS:et var äldre än ändringen och stod dokumenterat som känd brist; det som tillkom var påståendet om *varför*. Båda stängs av samma regel: utan en faktisk deterministisk kontroll uppfyller ett citerat fynd ingenting. En granskning som redovisar sina källor och påstår *inget* passerar fortfarande — det finns inget att avgöra.
  - `score_method` finns nu på varje utvärdering. `quality_score` bytte innebörd under oförändrat fältnamn, vilket en konsument skriven mot 1.0 annars aldrig hade upptäckt.
  - **Återstår:** kriterierna är per *route*, inte per *task*. En route är en uppgiftstyp; ett kriterium per uppgift skulle härledas ur den konkreta frågan körningen ställer, och den frågan formuleras inte av planen ännu — se ruta ett. En route utan evidenskontrakt har dessutom fortfarande textlängd som kriterium, namngivet som den proxy det är, eftersom det inte finns något bättre för en route som inte prövar något mot en källa.
- [ ] Ge feedback som strukturerade gapkoder och `next_action`, inte bara fri prosa. Kräv ny observation, nytt test eller förändrad plan före retry; identisk körning stoppas `no_progress`.
  - **Delvis.** `next_action` finns på varje utvärdering med något utestående: ett `kind` ur en sluten vokabulär, gapkoderna det adresserar, vilken `actor` som kan utföra det, och de detaljer den aktören behöver. Ett `kind` väljs på **företräde, inte allvarlighet** — ett oläsbart findings-block gör varje fråga om ett enskilt citat meningslös, och en källa som flyttat går inte att omcitera alls. `observe_again` bär `actor: "host"`: det är den enda åtgärd en producent inte kan ta. Prosan står kvar bredvid, för människor.
  - `identisk körning stoppas no_progress` är uppfyllt **för begränsade körningar**, där #29 redan la byte-regeln. Den är nu också formulerad på *felet*: samma nästa åtgärd, samma gap, samma ostödda påståenden betyder att återkopplingen producenten skulle få är den den redan fått, hur olika den än formulerats. `metadata.no_progress.reason` säger vilken regel som slog till. Obudgeterade körningar behåller sin 1.0-semantik med avsikt, och ett test håller den gränsen synlig.
  - **Uppdaterat efter observationsrundan (ruta ett):** loopen *kan* nu skaffa en ny observation mitt i en körning, och på `observe_again`-vägen är kravet bokstavligt uppfyllt — ett varv till ges bara om hosten faktiskt returnerade nytt underlag, annars stoppar körningen `blocked`.
  - **Återstår:** för övriga gap är det inte det. Ett omciterbart citatfel (fel digest, fel radintervall, saknat citatblock) ger fortfarande ett nytt varv utan ny observation, nytt test eller förändrad plan — bara ändrad återkoppling. Det är rimligt i sak, men det är inte vad rutan säger, så rutan står kvar tills kravet antingen uppfylls eller skrivs om till det som faktiskt ska gälla per gaptyp.
- [ ] Verifiera med ett aktuellt publikt repo vid pinad commit och jämför med fixture; dokumentera manuellt kontrollerade fynd och kända missar.

### P1.2 Live modellprovider som valfri adapter

- [ ] Implementera minst en riktig provider bakom befintlig `ModelAdapter`; stöd lokal Ollama eller extern leverantör som separat konfiguration. Saknad nyckel får inte bryta deterministic fallback.
- [ ] Schemalägg och validera strukturerad modelloutput; begränsa prompt/context, logga provider/model/config och versions-ID utan hemligheter; hantera rate limits, timeout och okänt svar.
- [ ] Kör kontraktstester med fake provider i CI och opt-in live smoke test utanför obligatorisk CI. Resultat från nätverksmodell markeras icke-deterministiskt.
- [ ] Förhindra att modelladaptern direkt exekverar godtycklig kod eller godkänner sin egen output. Endast verktyg via capability-lista.

**P1.2 exit gate:** dokumenterad körning där iteration 1 hittar ett verifierbart gap och iteration 2 tillför *nytt bevis* och förbättrar resultatet; separat test visar att stopp sker vid utebliven progress.

## P1 — v1.3 Runtime, kontrakt och återupptagning

- [ ] Definiera versionerade `Run.v2`, `Observation.v1`, `Action.v1`, `Finding.v1`, `Evaluation.v2` och `Approval.v1` med schema, bakåtkompatibilitetsregel och migrering från `atlas-run.v1` utan tyst dataförlust.
- [ ] Beständig append-only eventlogg med run ID, iteration, plan, verktygsanrop, beslut, stop reason och hashad input. Historiska observationer får inte skrivas över; ny körning skapar ny snapshot.
- [ ] Resume säkert efter krasch: idempotenta read-operations, inga dubbla sidoeffekter, låsning per run och explicit `interrupted`/`resumed` event.
- [ ] Verktygsadapter: deklarerade capabilities (`read`, `write`, `network`), allowlist per route, input/output-schema, timeout, budget, sandbox, retries bara för idempotenta anrop.
- [ ] Kör unit-, schema-, kontrakts-, integration-, property-/fuzz- och regressionstester för state transitions, malformed events och flera parallella runs.
- [ ] Lägg maskinläsbar `atlas inspect <run-id>`/export och en kort, mänskligt läsbar slutrapport med källor, osäkerheter och varför loopen stoppade.

**v1.3 exit gate:** kan starta om en avbruten read-only run utan att duplicera actions; samma snapshot + fake provider ger samma beslut; schema-change och budgetöverskridande ger tydligt fel.

## P1 — v1.4 Integration utan tight coupling

### Atlas One (äger UI-arbetet i `MCamner/atlas-one`)

- [ ] Publicera Core API/CLI-kontrakt för create/run/status/cancel/inspect, inklusive schema-version och streaming av progress-events. Anpassning i Atlas One görs i *dess* repo med separat PR.
- [ ] Visa observerade källor, faktiska iterationer, budget, verifieringsstatus och `approval_required` i UI. Märk prompt-preview separat från exekverad/verifierad run.
- [ ] Kontraktstest med mock Core och lokal smoke-test från Atlas One till Core; frontend får inte bli en alternativ evaluator.

### MQ (adaptrar, inte Core-importer)

- [ ] `mq-agent`: adapter för tillåtna read-only operations och eventuell orchestration handoff; undvik två konkurrerande ägare av samma loop/state.
- [ ] `mq-mcp`: adapter för explicit utvalda tools; respektera receiver-gates och befintliga evidence/memory-kontrakt. Ingen direkt write-around från Core.
- [ ] `mqobsidian`: mappa memory candidates till befintligt inbox-/scoringflöde; historiskt minne är inte aktuell repo-/runtime-sanning. Deduplicering, provenance och fail-closed vid felaktigt schema.
- [ ] Local Ollama / extern modell: provider-adaptrar med samma tester; inget provider-specifikt villkor i kärnan.
- [ ] Håll integrationstester i separata adapters/integrations och kör standalone Core CI utan MQ, Ollama, API-nycklar eller lokala paths.

**v1.4 exit gate:** UI → Core → read-only repo observation → evidensgranskad resultatrad → UI fungerar; koppla ur MQ/Ollama och bekräfta att Core fortfarande fungerar.

## P2 — v1.5 Skrivflöden, insikter och operativ kvalitet

- [ ] Separat write-capability med explicit mänskligt godkännande av exakt diff/kommando/ref; tidsbegränsat approval-token, återvalidering av HEAD/snapshot, minst privilegium och audit event.
- [ ] Första write-use-case: skapa föreslagen patch på ny branch, kör lokala tester, visa diff, begär godkännande; aldrig auto-merge/auto-push mot `main` som default. Förhindra shell injection och godtyckliga filpaths.
- [ ] Post-action verifiering (test/CI + diffkontroll), kompensations-/rollbackplan där den är möjlig; märk icke-återställbara externa sidoeffekter.
- [ ] Strukturerad telemetri: per-run latens, antal iterationer, tokens/kostnad, verktygsfel, falskt positiva, verifieringsgrad, användaravslag; inga hemligheter eller rå persondata i metrics.
- [ ] Feedback-loop: användarbekräftat utfall → separat kandidatinlärning → schema- och proveniensgate → opt-in promotion; ingen automatisk omskrivning av historisk evidens.
- [ ] `atlas-loop` kan konsumera API:t för *analys* av Instagram-experiment; publicering förblir separat, med egna rättigheter och mätdefinitioner.

**v1.5 exit gate:** nekad/utgången approval ger noll mutationer; ändrad HEAD invaliderar approval; verifierad patch går att granska och avbryta.

## P2 — v2.0 Stabil produktionsgräns

- [ ] Dokumentera API-stabilitet, semver, schema-migrationer, avvecklingspolicy, adapterkompatibilitet och supportmatris (Python, OS, provider-läge).
- [ ] Säkerhetsgranska threat model (prompt injection, supply chain, secrets, path traversal, SSRF, exfiltration, privileged write); dependency pinning, SBOM, secret scanning och CI-gates.
- [ ] Benchmarka deterministiska fixtures och opt-in live-repo-pilot; publicera metod, datamängd, kostnad, misslyckanden och begränsningar i stället för ett påhittat quality score.
- [ ] Release checklist: ren branch, tester, typkontroll/lint, schema compatibility, dokumentation, changelog, versionsverifiering, reproducible build, tag och återställningsplan.
- [ ] Operations-runbook för provider down, rate limits, memory unavailable, partial observations, approval timeout, resume failure och felaktig release.
- [ ] Migrera användare av äldre `atlas-one` promptflöde utan att automatiskt köra deras prompts eller förlora existerande innehåll; opt-in till loop.

**v2.0 exit gate:** två dokumenterade användningsfall (read-only review och godkänt patchförslag), uppmätta resultat, oberoende säkerhetsgranskning och godkända release-gates. Ingen autonom mutation utan tillstånd.

## Exekveringsordning — första 6 PR:er

1. **PR-A / P0.1:** `Observation.v1`, snapshot-ID, evidensmanifest, negativa provenance-tester. Enbart Core.
2. **PR-B / P0.2:** `Finding.v1` + evaluator som *avvisar* felaktig claim trots citerad verklig fil; falska fynd-fixtures. Enbart Core.
3. **PR-C / P0.3:** state/stop reasons/budget/capabilities, injektions- och read-only-tester. Enbart Core.
4. **PR-D / P1.1:** read-only `repo_review` fixture + evidence-driven replan och `no_progress`-gate. Enbart Core.
5. **PR-E / P1.2:** provideradapter med fake CI och opt-in live smoke; inga credentials i logg. Enbart Core.
6. **PR-F / P1.3:** beständig eventlogg, inspect/resume och schema migration. Därefter separata integrations-PR:er i `atlas-one` och MQ-repon.

Varje PR ska ange: problem/kontrakt, ändrade filer, negativa tester, migreringspåverkan, faktiska testkommandon/resultat, risk, rollback och nästa blockerare. Kör lokala CI-motsvarigheter före push. Små vertikala förändringar före bred refaktorering.

## Definition of Done för varje checkbox

1. Kod eller dokumentation finns i rätt repo; acceptance-testet är körbart och länkat i PR.
2. Fel- och adversarialfall testas, inte bara happy path; för evidence-arbete ingår minst ett medvetet falskt fynd.
3. Run-artifact visar `source_id`/commit, exakt observation, verifieringsresultat, iterationer och stop reason utan hemligheter.
4. Ingen ändring kringgår read-only eller approval-gräns; schema och docs är synkade.
5. Status ändras till `[x]` först när PR är mergad, CI har passerat och påstådd end-to-end-funktion faktiskt har observerats. Annars dokumentera `BLOCKED` med orsak.

## Riskregister / beslut att låsa tidigt

| Risk / öppet beslut | Föreslagen kontroll | Lås senast |
| --- | --- | --- |
| Citerad källa misstolkas | semantisk kontroll + deterministiska tester + explicit insufficient evidence | PR-B |
| Två loopägare (Core och mq-agent) | Core äger run state; MQ adapter äger sina lokala verktyg, inte Core state | före v1.4 |
| Kostnad/evig retry | hårda budgets + progress detection + cancel | PR-C |
| Stale repo eller CI-data | pinna commit/snapshot/tidsstämplar och redovisa stale | PR-A |
| Prompt injection från repo | data/instruction-separation, allowlist och negativa attacker | PR-C |
| Oavsiktlig dataexport | redaktion, sekretessklass, lokalt default och opt-in provider | före live provider |
| Modell bedömer sig själv | evaluator frikopplad från producerande modell och verifierbar evidens | PR-B |
| Approval återanvänds | bind till hashad exakt operation + revalidate HEAD | före write use-case |
| Minnesförgiftning / gammal sanning | candidates + receiver/schema gate, ingen tyst promotion | före v1.4 |

## Arbetsregel

Detta dokument beskriver **planerat arbete**, inte en order till en agent att exekvera något. Börja med PR-A och PR-B; mät en verklig vertikal slice innan bred integration. Om kod på `main` redan har implementerat ett steg, länka verifieringen och markera bara den delen färdig i stället för att bygga den igen.
