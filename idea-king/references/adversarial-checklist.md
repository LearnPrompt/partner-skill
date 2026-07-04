# Adversarial Review Checklist

Work through these attack surfaces in order; stop collecting after the 3
strongest. Depth beats coverage.

## Premises (wrong step zero)

- Is the problem statement itself inherited rather than verified? Who
  actually has this problem, and how do we know?
- Does the plan assume a capability, API, or behavior that nobody has
  confirmed on this machine / this version?
- Is there a number in the plan (cost, latency, volume) that is a guess
  dressed as a fact?

## Hidden Coupling

- Which two parts are "independent" in the plan but share state, schema,
  config, or timing in reality?
- What breaks in module A when module B is done by a different agent with
  different assumptions?
- Are there implicit ordering dependencies the parallel plan ignores?

## Integration Cost

- Sum the boundary costs: handoff writing, context rebuilding, review,
  rework rounds. Does the total still beat doing it in one place?
- Who merges conflicting outputs, and with what authority?
- Is the review gate actually cheaper than doing the work? If reviewing
  the delegated output costs as much as producing it, the split is theater.
- Diff-blind acceptance: does the acceptance step read the diff *and* the
  original task brief, or only the diff? A reviewer given only the diff
  confidently redefines the spec as "consistent with what changed" and
  passes work where the task was never done (Superpowers 6: 0 of 5 missing
  briefs caught). Falsification: hand the reviewer a diff that deliberately
  does half the task, and see if it passes on internal consistency alone.

## Failure Amplifiers

- What is the single point whose failure invalidates everything after it?
- Where would a silent failure (wrong but plausible output) pass the
  current acceptance criteria?
- What happens on partial completion — is the intermediate state safe to
  stop in, or does it strand the repo?

## Incentive & Scope Drift

- Which agent benefits from marking this "done"? What would it cut to get
  there?
- Where can scope quietly grow ("while I'm here...") and who stops it?

## Falsification Experiment Quality

A good experiment is: cheap (minutes, not hours), decisive (a clear
pass/fail), and early (runnable before the plan commits). "Run the full
pipeline and see" is not a falsification experiment; it is the failure you
were trying to avoid.
