# bapu-findings: review claims checked against their evidence

A review finding is a claim. `bapu-findings` checks that each claim rests on evidence the
reviewer actually pasted, before anyone spends time acting on it.

```
bapu-findings FILE [--allow-unquoted] [--out FILE] [--json]
bapu-findings FILE --online [--model ID] [--allow-unquoted] [--out FILE] [--json]
bapu-findings --self-test [--online]
```

## The input file

```json
{
  "findings": [
    {
      "id": "F1",
      "claimed_severity": "P1",
      "claim": "A second export without --force replaces the first file instead of refusing.",
      "evidence": "$ export --out out\nwrote out/export.json\n$ export --out out\nwrote out/export.json\nexit status 0",
      "subclaims": [
        {"text": "The second export exits 0 instead of 3.", "quote": "exit status 0"}
      ]
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `id` | unique string or integer |
| `claim` | what the reviewer says is wrong |
| `evidence` | the commands that were run and their output, pasted verbatim |
| `subclaims` | the claim split into single observations; each `quote` must appear verbatim in `evidence` |
| `claimed_severity` | optional: `P0`, `P1` or `P2` (see below) |

A sub-claim may also be a bare string, which is a sub-claim without a quote.

## Offline: quotes

Offline is the default. It needs no key and makes no network call.

| Verdict | When |
|---|---|
| QUOTED | every sub-claim has a quote, and every quote appears verbatim in the evidence |
| NEEDS-EVIDENCE | a quote is not in the evidence, a sub-claim has no quote, or there are no sub-claims |
| UNCHECKED | only with `--allow-unquoted`: unquoted sub-claims leave nothing to check offline |

Verbatim means character for character: a paraphrased quote, a changed number or an extra
space is not in the evidence. A claim that cites output its author did not paste goes back to
its author.

Quoting is necessary, not sufficient. A verbatim quote can still be misread.

## Online: support

`--online` needs `TYPESAFE_API_KEY`; without it the tool exits 2 and sends nothing. A claim that
fails the quote check is never sent.

For each claim, TypeSafe's System One model (Jev) is asked, over a state holding only the claim
and the evidence:

- for each sub-claim: does the evidence show this single observation? (`shown_i`)
- does the evidence, read on its own, show the behaviour the claim describes? (`supported`)
- was the input in the evidence produced by a production path, rather than built by hand or
  patched? (`reachable`)
- assuming the claim is true, how severe is it, on the levels below? (`severity`)

Support is not the complement of refutation. "The evidence does not show it" can mean the
evidence shows the opposite, or that it is silent. So each sub-claim below 0.3 gets a second
question, whether the evidence shows it to be false:

| Sub-claim status | When |
|---|---|
| SHOWN | P(shown) is at least 0.3 |
| CONTRADICTED | P(shown) is below 0.3 and P(false) is above 0.75 |
| ABSENT | P(shown) is below 0.3 and the evidence is silent |

The whole claim counts as well: every sub-claim can be shown while the claim still says more
than they do.

| Verdict | When (checked in this order) |
|---|---|
| REFUTED | a sub-claim is CONTRADICTED |
| NEEDS-EVIDENCE | a sub-claim is ABSENT (a true observation that was not pasted looks, by score alone, exactly like a false one), or every sub-claim is SHOWN but the whole claim scores below 0.3 |
| ESCALATE | the lowest of the SHOWN probabilities and the whole claim is between 0.3 and 0.75, both ends included: a stronger reviewer decides |
| CONFIRMED | that lowest probability is above 0.75 |

With no sub-claims (allowed only with `--allow-unquoted`), the whole-claim `supported`
probability decides alone: below 0.3 REFUTED, 0.3 to 0.75 ESCALATE, above 0.75 CONFIRMED.

Severity levels:

| Level | Meaning |
|---|---|
| P0 | a silent wrong result on a production path: a verdict overwritten, a failure reported as ok, a wrong identity acted on, a control that admits what it exists to refuse |
| P1 | a guard narrower than the property it protects, a test that asserts a label instead of the property, two checks sharing one refusal code, a spec or docstring that contradicts the code; the wrong case is reachable but announced or bounded |
| P2 | a wording, naming or documentation gap; behaviour is correct or the wrong case cannot be reached from a production caller |

Severity and reachability never change a verdict. They are reported, with the flags
`severity_disputed` (the judge's level differs from `claimed_severity`), `reachability_unclear`
(`reachable` below 0.6) and `unquoted_subclaims`.

**CONFIRMED means the quoted evidence shows what the claim says. It does not mean the claim is
true.** A premise that fails elsewhere, or a code path production never reaches, sits outside
the quotes, where support scoring cannot see it. Reproduce a claim before acting on it.

## Exit codes

- 0: the evidence settled every claim: QUOTED offline; CONFIRMED or REFUTED online;
- 1: at least one claim is left with a person: NEEDS-EVIDENCE, UNCHECKED or ESCALATE;
- 2: a usage or input error, or (online) no usable answer from the API for at least one claim,
  which is then reported as ESCALATE with the error attached.
