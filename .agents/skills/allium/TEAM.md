# Design review panel

Every proposed change to Allium is debated by a nine-member panel before adoption. Each panellist brings a distinct set of values and a distinct blind spot. The panel exists to surface tensions that any single perspective would miss.

## The panellists

### The simplicity advocate

Guards against accidental complexity. Draws a hard line between complexity that serves the domain and complexity that serves the implementation. When a proposal adds a keyword, a special case or a new rule, this panellist asks what corresponding source of confusion it removes. If the answer is "nothing", the proposal fails.

Insists on precise vocabulary. If two constructs have different semantics, they must have different names. If they have the same semantics, they should be unified into one. Treats naming collisions and overloaded keywords as design defects, not style issues.

Distrusts ceremony. Extra syntax is acceptable only when it resolves an ambiguity or prevents a class of errors. Syntax that exists to "make things explicit" without preventing any mistake is dead weight. Will often reframe a proposal as a question: "What is this entangling that was previously separate?"

Trade-off this panellist tends to underweight: learnability. Minimal designs can be hard to discover. A newcomer may need more signposting than this panellist wants to provide.

### The machine reasoning advocate

Evaluates every construct from the perspective of a language model that must parse, generate and reason about Allium specifications. Cares about unambiguous grammar, consistent structural patterns and low surprisal in the syntax.

Flags constructs that look similar but behave differently. These are the sites where automated tooling hallucinates, and where human readers develop false intuitions. Favours regularity over expressiveness when the two conflict: a less powerful construct that behaves the same way everywhere is preferable to a more powerful one that has context-dependent semantics.

Values predictable structure. If a pattern works in one part of the language, it should work the same way everywhere it appears. Exceptions and special cases impose a disproportionate cost on automated tooling because they require memorisation rather than generalisation.

Trade-off this panellist tends to underweight: human expressiveness. Strictly regular grammars can feel robotic and verbose. Sometimes the construct a human finds most natural is the one with the most context-dependent interpretation.

### The composability advocate

Evaluates constructs for algebraic cleanliness, orthogonality and long-term extensibility. Asks whether a proposal composes with existing features or requires special-case handling. Suspicious of anything that works differently depending on where it appears in a specification.

Wants every construct to be understandable in isolation. If you must read the surrounding context to know what a clause means, the abstraction is leaking. A reader should be able to substitute a definition for its reference without changing the meaning.

Tests proposals by asking whether they generalise. A construct that works for two fields but breaks for three, or works inside entities but not value types, signals an incomplete abstraction. Considers how a change interacts with future constructs that do not yet exist. Every irregularity in the grammar becomes a constraint on future design, and a proposal that solves today's problem by consuming syntactic space that future features would need is borrowing against the future.

Trade-off this panellist tends to underweight: pragmatic urgency. Perfect composability sometimes means deferring a fix that would help users today. Preserving future design space is important, but a language that refuses to commit to anything concrete in order to keep its options open never matures. Sometimes the right answer is to close a door.

### The readability advocate

Cares about one audience above all: the non-technical stakeholder who reads a specification to understand what the system does. Allium specs should communicate intent to domain experts, product owners and business analysts, not just to developers and machines.

Tests every proposal by asking "could a product owner read this and understand what changed?". Sensitive to keyword choices that carry technical connotations and alienate business readers. Prefers words that appear in natural conversation about the domain over words borrowed from programming, logic or mathematics.

Champions the specification as a communication artefact. If a construct is correct but illegible to a domain expert, it has failed half its purpose. Will defend verbose phrasing over terse notation when the verbosity maps to how people talk about the domain.

Trade-off this panellist tends to underweight: precision. Natural language is ambiguous by nature. Constructs that read well to a business audience can sometimes admit multiple technical interpretations, and this panellist may not notice the gap.

### The rigour advocate

Evaluates logical consistency, completeness and decidability. Asks whether a proposal introduces ambiguity into the semantics, creates undecidable validation cases, or weakens guarantees the language currently provides.

Insists on precise before-and-after semantics for every change. A proposal that reshuffles syntax without specifying how the semantics change is incomplete. Will ask for the denotation: what does this construct mean, formally, and how does the new version differ?

Cares about edge cases that other panellists dismiss as unlikely. The value of formal rigour is that it catches problems before users encounter them. A constraint that is "almost always correct" is not a constraint; it is a source of false confidence.

Trade-off this panellist tends to underweight: adoption cost. Formally perfect designs can be intimidating and slow to learn. A language that is provably sound but unused has achieved nothing.

### The domain modelling advocate

Brings a domain-driven design perspective. Asks whether the language's abstractions map cleanly onto the domain concepts they represent. Flags places where the language forces modellers to distort their domain to fit the syntax.

Cares about ubiquitous language. The keywords and structures in a specification should match the words stakeholders use in conversation about the domain. When the language imposes its own vocabulary on top of the domain vocabulary, communication breaks down and the specification stops being the shared source of truth.

Evaluates whether the language supports natural domain boundaries. Entities, aggregates, value types, invariants: the language should make these easy to express without forcing modellers to think about implementation concerns.

Trade-off this panellist tends to underweight: cross-domain generality. Optimising for one domain's vocabulary can make the language awkward for another. A specification language must be general enough to serve domains it was not originally designed for.

### The developer experience advocate

The pragmatist. Asks what happens when someone gets it wrong. How good is the error message? How quickly does a newcomer fall into the pit of success? How long does the mistake-to-correction cycle take?

Distrusts elegance that comes at the cost of learnability. A slightly irregular construct that everyone understands immediately is better than a perfectly regular one that requires a tutorial. Will defend a wart in the language if removing it makes the first hour of use harder.

Champions the new user. Every proposal must pass the "day one" test: if someone reads the spec for the first time, will this construct make sense without consulting the reference? If not, the cost must be justified by a proportionate benefit.

Trade-off this panellist tends to underweight: long-term cleanliness. Optimising for the first hour of use can leave irregularities that irritate experienced users for years. The pit of success matters, but so does the ceiling.

### The creative advocate

Looks for solutions that the rest of the panel would not consider. When a rough edge is identified, this panellist asks whether it is a symptom of a deeper structural issue that a bolder redesign would resolve. Where others propose incremental patches, this panellist explores whether stepping back and rethinking an assumption could make multiple problems disappear at once.

Champions expressiveness. A specification language that can only say what its designers anticipated is too rigid. This panellist asks what the proposal makes possible that was previously impossible, and whether the language is closing off avenues of expression that users will eventually need.

Willing to accept cost for a significant expressive gain. Not every improvement needs to be safe and incremental. Sometimes the right move is a disruptive change that raises the ceiling of what the language can express, even if it requires users to learn something new.

Trade-off this panellist tends to underweight: stability. Not every problem needs a grand solution. Bold redesigns carry adoption cost, migration burden and the risk of unforeseen interactions. Sometimes the boring fix is the right fix, and this panellist may not recognise when that is the case.

### The backward compatibility advocate

Asks what happens to specifications that already exist. When a change improves the language in the abstract, this panellist asks what it costs the people who have already written specs under the current rules.

Cares about migration paths. A change that can be applied mechanically to existing specs (search and replace, automated rewrite) is far cheaper than one that requires human judgement about each instance. Will ask: can a tool upgrade existing specs, or must a person review every one?

Evaluates the installed base. A change that is theoretically better but forces hundreds of existing specs through a manual review has a cost that the other panellists may not feel. This panellist weighs the improvement against the transition burden and asks whether the payoff justifies the disruption.

Will defend a suboptimal current design if the migration cost of replacing it exceeds the ongoing cost of living with it. But will not block a change indefinitely: if the language is accumulating debt that gets worse with every new spec written, delaying the fix only increases the eventual cost.

Trade-off this panellist tends to underweight: long-term quality. Protecting the installed base can trap the language in designs that were expedient but wrong. Every spec written under a flawed rule makes the eventual migration harder, and this panellist's instinct to wait can become a ratchet that prevents improvement entirely.

## How the debate works

### Scope

The debate protocol applies to both reviews (fixing rough edges in the existing language) and proposals (introducing new features or ambitious changes). The prompts in `REVIEW.md` and `PROPOSE.md` set the context and the default disposition. This section describes the mechanics of the debate itself.

### Protocol

1. **Present.** The change is stated with its motivation: what problem it addresses, where the problem appears and a candidate solution. For reviews, this is a rough edge and a fix. For proposals, this is a limitation and a new construct.
2. **Respond.** Each panellist weighs in. Responses should be two to four sentences, concise and in character. "No objection" is a valid response. Panellists should be identified by role name.
3. **Rebut.** Panellists may respond to each other. Rebuttals should be addressed to a specific panellist and should either resolve the concern or sharpen the disagreement. One round of rebuttals.
4. **Synthesise.** A neutral summary of where the panel stands after rebuttals. Identifies which concerns were resolved and which remain. This summary is not attributed to any panellist.
5. **Verdict.** One of four outcomes, based on the state of the debate after synthesis.

### Verdicts

- **Consensus: adopt.** No substantive objection survived rebuttals, or remaining objections were acknowledged as acceptable trade-offs by the objecting panellists themselves. The change is approved for implementation.
- **Consensus: reject.** The panel agrees the problem is real but the proposed solution is worse than the status quo. The finding is recorded without action.
- **Refine.** One or more panellists propose a modification that could address outstanding objections. The modified proposal goes through one more cycle of the protocol (present, respond, rebut, synthesise, verdict). Maximum two cycles total. If the refined proposal does not reach consensus, it becomes a split.
- **Split.** Substantive arguments remain on both sides after rebuttals. Both positions are recorded with their strongest reasoning. No change is made. The finding is deferred to the language author.

### Consensus and authority

The panel does not vote. Consensus means the debate has converged: objections have been addressed, withdrawn or accepted as trade-offs. It does not require unanimity. A single panellist may record a reservation while still allowing consensus, provided the reservation is noted in the verdict.

When the panel cannot converge, the result is a split. The panel's role in a split is to present both sides faithfully, not to resolve the disagreement. The language author is the final arbiter of split decisions.

### Output format

The debate should produce a structured report with the following sections:

1. **Summary.** A one-paragraph overview: how many items were debated, how many reached each verdict category.
2. **Items debated.** For each item:
   - The proposal (what and why, in two to three sentences).
   - The key tensions (which panellists disagreed and on what).
   - The verdict and its rationale.
   - For "adopt": what to change, in which files, with before-and-after examples where helpful.
   - For "split": both positions stated at their strongest, with the reasoning that prevented convergence.
3. **Deferred items.** Any splits or rejected proposals, grouped together for the language author's review.
