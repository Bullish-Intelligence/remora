# Feature proposal prompt

Use this prompt to convene the review panel on a proposed feature, extension or ambitious change. For fixes to rough edges in the existing language, use `REVIEW.md` instead.

---

You are evaluating a proposed feature or extension to Allium, a domain specification language. The spec lives in `references/language-reference.md`, with patterns in `references/patterns.md` and authoring guidance in `SKILL.md`.

Read the full language reference, patterns file and SKILL.md. Then evaluate the proposal against the language's two fundamental goals: **practical correctness** (specs that are unambiguous, sound and hard to get wrong) and **developer velocity through clarity** (specs that are fast to write, easy to read and cheap to change).

Simulate the design review panel described in `TEAM.md`. Follow the debate protocol in that file: present, respond, rebut, synthesise, verdict. Every panellist must weigh in. Produce the report in the output format specified in `TEAM.md`.

The default disposition for a proposal is to leave the language alone. The burden of proof is on the proposal, not on the status quo. Every addition makes the language larger, and that cost is permanent. A proposal must clear a high bar.

For each proposal, the panel should address:

1. **The problem.** What limitation, gap or pain point does this proposal address? Is it real and recurring, or hypothetical? Can the panel find concrete examples where the current language forces an awkward workaround?
2. **The design space.** What are the plausible approaches? The proposer may have a preferred solution, but the panel should consider alternatives, including doing nothing. A proposal that solves a real problem badly is worse than leaving the problem unsolved.
3. **Interactions.** How does the proposal interact with existing constructs? Does it compose cleanly or require special cases? Does it consume syntactic space that future features might need? Does it change the meaning of any existing valid specification?
4. **The cost.** What is the learning cost for new users? The cognitive cost for experienced users? The implementation cost for tooling? Is the benefit proportionate?
5. **Reversibility.** How hard is it to undo this change if it turns out to be wrong? Features that are easy to add and hard to remove deserve extra scrutiny.
