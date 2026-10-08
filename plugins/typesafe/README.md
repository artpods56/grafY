# Grafy TypeSafe Plugin

System plugin for [TypeSafe](https://docs.typesafe.ai) System One judgments.
The published identity is `external.typesafe`. Calls go through `typesafe-sdk`
(`AsyncTypeSafeClient`), not a hand-rolled HTTP client.

Jev answers narrow questions. It does not write the workflow. Ask every
question about the same state in one **Evaluate** node, then decide locally.

## The four nodes

1. **Question** builds one noul, choice, or score question. Everything is set in
   its form: the question id, the kind, the instructions, and the answers it can
   give. Choice options are entries such as `refund` or
   `refund: The customer wants money back`, so labels cannot contain colons.
   Score levels are listed lowest first. Fields for another kind must stay
   empty. The question id is for the graph and is not sent to the model.
2. **Evaluate** sends a state and a sequence of questions to
   `POST /v1/systemone` in one request. Select the Question outputs on the
   canvas and collect them into a stack, then connect the stack to
   `questions`. The state is a text value. Set `state_form` to `json` to parse
   it as a JSON object or array first. The API key is a node secret named
   `api_key`, bound to `base_url`. The default root is `https://api.typesafe.ai`
   and the default model is `jev-latest`.
3. **Decide** reads answers from the evaluation by question id and returns
   act or review with an outcome. It runs in the workbench, so changing a
   threshold does not call TypeSafe again.
4. **Combine scores** scales each score to 0–1 and averages them with
   relative weights, also locally. Write entries such as `urgency: 3`. An id
   without a weight counts 1.

## How the judgments behave

- A noul is the probability of yes. Near 0.5 means the model finds yes and no
  similarly likely. It is not a medium score. **Decide** says yes at or above
  `yes_at` (0.8 by default), no at or below `no_at` (0.2), and review in
  between.
- With several noul ids, `require: any` lets the highest noul decide. That is
  the "any serious violation" guard. `require: all` lets the lowest decide, so
  the outcome is yes only when every noul is yes.
- A choice returns the selected label, a probability for every option, and a
  confidence derived from that distribution. **Decide** sends one choice to
  review when its confidence is below `minimum_confidence`, or when the label
  is outside a non-empty `allow` list.
- A score is a position on the levels you wrote, and it can fall between two
  levels. **Combine scores** divides each score by its top level index, then
  applies the weights. Weights are relative, so 4 and 1 mean the same as 0.8
  and 0.2.

Choice options are capped at 255 and score levels at 2–10, matching the API.
One request holds at most 128 questions, and each needs its own id.

## Credentials and network

The node never stores the API key. Set `base_url` to an HTTPS origin; plain
HTTP is only accepted for localhost. The deployment still has to assign
`external.typesafe` a network profile that allows that origin. This repo's
`network-policy.toml` uses the same `configured-public` profile as the LLM
plugin.

## Develop and verify

Install the optional plugin in the host workspace with `uv sync --extra typesafe`.
To test the publishable project independently, run these commands from the repository root:

```sh
uv sync --directory plugins/typesafe --locked --find-links wheels
uv run --directory plugins/typesafe --locked --find-links wheels pytest -q
```

The project carries its own lockfile and Grafy SDK wheel. The system inventory
publishes it as an isolated plugin; installing the optional host extra alone
does not promote a release into a deployment. Follow the repository's
[plugin publication instructions](../../docs/design/plugin-development.md).

The adapter uses typed SDK questions and the SDK's response validation, retries,
and asynchronous resource cleanup. SDK 0.7.2 declares recursive JSON types using
string aliases that Pyright cannot fully resolve. Local JSON types remain checked;
one suppression applies only to the SDK method's unknown-member diagnostic.
Transport tests exercise the real SDK's wire encoding and response decoding.
