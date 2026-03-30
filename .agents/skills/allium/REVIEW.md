# Design review prompt

Use this prompt to convene the review panel on a specific proposed change or set of related changes. For new features or ambitious extensions, use `PROPOSE.md` instead.

---

You are reviewing a proposed change to Allium, a domain specification language. The spec lives in `references/language-reference.md`, with patterns in `references/patterns.md` and authoring guidance in `SKILL.md`.

Read the full language reference, patterns file and SKILL.md. Then review the proposed change against the language's two fundamental goals: **practical correctness** (specs that are unambiguous, sound and hard to get wrong) and **developer velocity through clarity** (specs that are fast to write, easy to read and cheap to change).

Simulate the design review panel described in `TEAM.md`. Follow the debate protocol in that file: present, respond, rebut, synthesise, verdict. Every panellist must weigh in on every item. Produce the report in the output format specified in `TEAM.md`.

The default disposition for a review is to fix the problem if a good fix exists. The burden of proof is on justifying inaction, not on justifying the change.

For each item under review, state: what the rough edge is, where it appears (file and line), why it matters (what confusion or future problem it invites), and a candidate fix. Be specific. Limit yourself to observations you are confident about. If you are uncertain whether something is a rough edge or a deliberate design choice, say so.

Do not propose new features or extensions. Do not flag stylistic preferences about prose. Focus on the language itself.
