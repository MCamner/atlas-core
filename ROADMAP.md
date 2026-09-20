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
- [ ] Läs en konsekvent snapshot för en run; upptäck ändrad HEAD/fil under läsning och märk `stale` eller avbryt; blanda inte `main` och arbetsgren utan tydlig separation.
  - **Delvis.** [#16](https://github.com/MCamner/atlas-core/pull/16) ger `take_snapshot`, `verify_observation` (`fresh`/`stale`/`missing`/`unverifiable`) och `detect_drift`, som parar HEAD-kontroll med innehållskontroll per källa — `has_moved()` ensam ser inte en redan smutsig worktree ändras igen. Grenbyte ger ett annat snapshot.
  - **Återstår:** ingen körning *avbryts* vid drift, och inget av detta är inkopplat i `AtlasController`. Loopen tar fortfarande `list[str]`-observationer, så en route som får stale källor mitt i en körning märker det inte.
- [ ] Lagra begränsade, sanitiserade utdrag i observationsmanifest; koppla varje finding till `source_id` och exakt utdrag. Klipp inte bort just den kontext som behövs för att kontrollera påståendet.
  - **Delvis.** PR C ger `redacted_manifest()` med begränsade och maskerade utdrag, snapshot-proveniens och per-post verifieringsstatus. Manifestet utelämnar `snapshot.root`, som är en absolut sökväg med användarnamn. Maskeringen är smal och verifierad mot repots egna filer: 0 falska positiva.
  - **Återstår:** kopplingen finding → `source_id` finns inte. `Finding.v1` är P0.2, och inget i P0.1 kan därför knyta ett påstående till ett utdrag.
- [ ] Redigera tokens, privata paths och persondata före run-artifact/export; råa källor förblir lokala. Negativa tester för injicerade hemligheter och symlänkar/path traversal.
  - **Delvis.** PR C: `redact_text()` maskerar nyckelformat, hemkataloger och e-post vid export medan råa utdrag stannar lokalt. `resolve_within()` avvisar absoluta sökvägar, `..`-flykt, syskonkatalog med delat prefix och symlänkar som pekar ut ur snapshotet. Negativa tester finns för alla dessa samt för manipulerat innehåll av samma längd.
  - **Återstår:** maskeringen är best-effort. Persondata utöver e-post och hemkatalog upptäcks inte, det finns ingen klassificering av personuppgifter, och `confidentiality` sätts aldrig automatiskt — den är `unknown` om ingen anger den.
  - **Återstår:** containment gäller inte alla läsvägar. `verify_observation()` läser om `root / observation.path` utan egen kontroll, och `Observation.path` accepterar i dag `../` och absoluta former. En findingkontroll som läser om en källa måste göra sin egen säkra läsning. Resolve och open är två steg: `read_within()` öppnar med `O_NOFOLLOW`, så en fil som bytts mot en symlänk efter namnkontrollen vägras när deskriptorn skapas i stället för att serveras — ett test utför bytet inne i fönstret. Kvar öppet: en **katalogkomponent** i sökvägen kan fortfarande bytas i samma fönster, vilket skulle kräva en `openat`-vandring per komponent för att stänga. En fil kan dessutom alltid ändras mellan en kontroll och en senare läsning; integritet återetableras genom omverifiering, inte genom att lita på en tidigare kontroll.

### P0.2 Verifiering ≠ citering

> Två av fyra rutor kryssade efter att PR E ([#20](https://github.com/MCamner/atlas-core/pull/20)) mergats som `99770bc`, med `Ran 283 tests ... OK` i testworkflowen på `main` och beteendet observerat i en körning mot det här repot: ett sant typat påstående om README gav `verified`, ett falskt gav `contradicted`, och ett om text bortom det observerade utdraget gav `contradicted`.
>
> **Ruta tre står kvar öppen.** Den innehåller två krav. Förbudet mot att modellen tilldelar sitt eget verdikt är uppfyllt; uppdelningen fakta/hypotes/rekommendation är inte visad. Se rutans egen notering.
>
> **Ruta fyra** är åtgärdad i PR H men inte kryssad förrän den är mergad och resultatet observerat på `main`. Övriga fall i rutan (falskt fynd som citerar en verkligt läst README, fel SHA, fel radintervall, cherry-pickat utdrag, tomma källor, saknat resultat) hade redan tester.
>
> **Vad de kryssade rutorna betyder, och inte.** De gäller *verifierade literalpåståenden*, inte bredare slutsatser om ett repo. `verified` kan bara nås genom ett typat påstående där påståendet *är* predikatet — `source_contains_literal` eller `source_lacks_literal` över citerade, observerade rader — och den läsbara meningen härleds ur objektet, så prosan inte kan säga mer än det som prövades. Ett påstående som inte går att uttrycka så kan inte verifieras här alls: det blir `insufficient_evidence`, vilket är rätt svar och samtidigt gränsen för vad fasen räcker till. En grön körning betyder "varje fynd var formulerat så att det gick att avgöra, och avgjordes till sin fördel mot lästa rader" — inte att granskningen är fullständig.
>
> Kvar öppet i övrigt: fri text ger `insufficient_evidence`; ett producentdeklarerat `claim_check` är diagnostik (`condition_supported`/`condition_refuted`) och kan aldrig ge ett verdikt. Villkor matchar literal text, inte reguljära uttryck. En stale källa avgör ingenting i någon riktning. Prosakanalen `observations` exporteras fortfarande ordagrant — en egen säkerhetslucka, inte en del av P0.2.

- [x] Definiera `Finding.v1`: claim, scope, severity med motivering, evidence IDs, verifieringsmetod, verifieringsresultat (`verified`/`contradicted`/`insufficient_evidence`), begränsningar och reproducerbart kommando om relevant.
- [x] Låt evaluator kontrollera att refererade ID:n existerar i denna run, att utdrag och line range matchar snapshot och att påståendets kontrollerbara del stöds av källan/testet. Om semantisk verifiering inte kan göras: `insufficient_evidence`, aldrig `verified` på enbart filnamn.
  - Kontrollerbar del = det som går att uttrycka som literal närvaro eller frånvaro över observerade rader. Allt annat blir `insufficient_evidence`, aldrig `verified`.
- [ ] Separera fakta, hypotes och rekommendation. En modellbaserad verifierare måste kompletteras med deterministiska kontroller/tester; modellens eget självomdöme får inte ensamt ge PASS.
  - **Delvis:** det andra kravet är uppfyllt. Ingen modellbaserad verifierare finns; allt avgörs deterministiskt. `verdict`, `verification_method` och `finding_id` saknas i producentens indataschema, och ett insmugglat `verdict` avvisar hela blocket i stället för att tystas.
  - **Återstår:** själva uppdelningen, och den är inte bara otestad utan trasig. Körningsdokumentet skiljer kategorierna — `citation_checks` ger `verdict: verified` per fynd och `unverified_claims` listar resten — men `render_run_text` gör det inte. En körning med ett verifierat faktum och en hypotes ger denna text:

    ```text
    - README.md lines 1-5 contain "pip install"
    - README.md är förmodligen svår att följa för nybörjare.
    ---
    Status: provisional
    Evidence gaps: uncheckable_findings
    ```

    Två identiska punkter under samma rubrik. En läsare kan inte se vilken som avgjordes mot en källa, och trailern säger att det finns ett evidensgap men inte vilket påstående det gäller. Kräver att slutrapporten märker kategorin per påstående, och ett test som följer ett verifierat fynd, en hypotes och en rekommendation genom `render_run_text` och visar att de förblir åtskilda.
- [ ] Testa falskt fynd som citerar en verkligt läst README, fel SHA/linje, cherry-pickat utdrag, stale CI, tomma källor och saknat resultat. Alla ska bli FAIL/INSUFFICIENT_EVIDENCE.
  - **Åtgärdad i PR H, kryssas vid merge.** `atlas_core/ci.py` samlar in ett CI-resultat med proveniens — provider, workflow, run id, ref, commit, slutsats och tidpunkt — och hashar exakt de fälten, så digesten ändras när *resultatet* ändras och inte när ett API svarar i annan ordning. Källan läses om genom sin adapter, aldrig ur en cache: en cachad kopia skulle göra varje CI-citat permanent färskt, vilket är just felet rutan pekar på. Ett test citerar en grön körning, låter någon köra om workflowet rött, och visar `stale_source` och `passed=False` genom `AtlasController`. En omkörning som blir grön igen är också `stale_source` — identiteten är körningen, inte slutsatsen den råkade ge.
  - Läsningen är nu typbunden: `SourceReader` per källtyp, där `local_file` alltid finns och inte kan ersättas av en anropare — en som kunde det skulle äga containment och färskhet för varje lokalt citat i körningen. En källtyp utan läsare avvisas som `unsupported_source_type` i stället för att gissas.

### P0.3 Terminalsäkerhet och resurser

- [ ] Versionera explicit state machine och stopporsaker: `passed`, `insufficient_evidence`, `blocked`, `approval_required`, `budget_exhausted`, `max_iterations`, `no_progress`, `tool_error`, `cancelled`. Skilj runtime-fel från saklig evaluering.
- [ ] Inför max iterationer, wall-clock, modell-/verktygsanrop, tokenkostnad och outputstorlek. Alla gränser ska gälla även nested verktyg och retries.
- [ ] Fail-closed för skrivning: inga verktyg med sidoeffekter i read-only mode; mänskligt godkännande knyts senare till exakt diff/kommando/repo/ref och upphör när underlaget ändras.
- [ ] Testa prompt injection i README och verktygsoutput, nätverksfel, timeout, abort, oändlig förbättring utan progress, felaktigt JSON och samtidiga körningar. Output från repo är *data*, inte instruktion.

> Statusnoteringarna ovan följer regeln i huvudet: en ruta kryssas först när PR är mergad, tester körda och resultatet observerat. En delvis täckt ruta står kvar som öppen med vad som faktiskt återstår — inte som nästan klar.

**P0 exit gate:** en osann verifierbar claim kan inte få `passed`; varje beslut kan följas till snapshot/evidence; read-only-försök att skriva nekas på exekveringsgränsen, inte bara genom prompttext.

## P1 — v1.2 Första verkliga uppgiftsloopen

### P1.1 Repo-review som vertikal slice

- [ ] Inför en begränsad `repo_review`-plan: välj snapshot → identifiera konkret fråga → läs relevanta filer/tester/CI → samla fynd → verifiera → föreslå nästa *skrivskyddade* undersökning eller avsluta.
- [ ] Välj ett litet, fast fixture-repo med kända defekter och ett utan defekter. Mät precision mot facit, andel evidensbelagda findings, falskt positiva, iterationsantal, kostnad och stopporsak.
- [ ] Sätt explicit exit criteria per task i stället för generell textlängd/rubriker. Ingen finding med okänd täckning får tilldelas verifierad severity.
- [ ] Ge feedback som strukturerade gapkoder och `next_action`, inte bara fri prosa. Kräv ny observation, nytt test eller förändrad plan före retry; identisk körning stoppas `no_progress`.
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
