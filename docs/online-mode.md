# Online mode

Everything in Bapu works offline. `bapu-gate --online` and `bapu-findings --online` add
bounded judgments from TypeSafe's System One model, Jev
([documentation](https://docs.typesafe.ai)). `bapu-seedred` never goes online.

## When a request is sent

Only when both hold:

1. the command was given `--online`, and
2. the environment variable `TYPESAFE_API_KEY` is set.

With `--online` and no key, the command exits 2 before anything is sent. Without `--online`,
nothing is sent even when the key is set. The key is read from the environment only; it is
never written to a receipt, a log or the terminal. A key containing whitespace or a control
character is refused before any request, with a message that does not repeat it.

## What is sent

One `POST https://api.typesafe.ai/v1/systemone` per ask, carrying a `state`, the pinned model
id and the questions:

- `bapu-gate`: per requirement, the requirement's name and text and its scenarios' steps; two
  requests per requirement (the original wording and the paraphrase);
- `bapu-findings`: per finding, the claim and the evidence; a second request only when some
  sub-claim scores below 0.3.

The content leaves your machine. Do not send specifications or evidence that contain secrets.

## How answers are used

- **Pinned model.** Requests name an exact model id, `jev-1.13.0` by default (`--model` to
  change it). An answer from any other model is an error, because thresholds belong to one
  model version.
- **No silent zeros.** A missing, non-numeric, boolean or out-of-range answer is an error that
  exits 2, never a score of 0.0.
- **Retries.** HTTP 429 and 529 are retried three times with exponential backoff; other errors
  fail at once.
- **No redirects.** A redirect is treated as an error. Following it would resend the key and
  the content to another host.
- **Edge compatibility.** The API's edge firewall has been observed to refuse, with HTTP 403,
  urllib's default User-Agent and request bodies in which a quote, backtick, pipe or semicolon
  directly precedes `python -m` or `python -c`. The client sends its own User-Agent and replaces
  those four characters with full-width look-alikes, which read the same to the model. Offline
  quote checks always run on the original text.

## What a score is

A probability from a judgment model ranks cases for a person to look at. It authorises nothing
on its own, and a well-formed answer can still be wrong. The thresholds in this project are
hand-set defaults: before relying on them, run each tool's `--self-test --online`, which plants
cases whose right verdict is known, and measure the scores on examples from your own project.
