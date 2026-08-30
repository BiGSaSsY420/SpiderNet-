# Running SpiderNet

## One command

```bash
git clone https://github.com/BiGSaSsY420/SpiderNet-.git
cd SpiderNet-
python backend/scripts/demo.py
```

That installs what it needs, seeds a customer and two crowds, starts a stub
model, and serves the app. It prints an access key and an admin token when it
is ready.

**No API keys required.** You should be able to test the product before you pay
anyone.

| | |
|---|---|
| App | http://localhost:3000 |
| Operator console | http://localhost:3000/admin |
| API | http://localhost:5001 |

First run takes a minute or two while dependencies install; after that it is
seconds. `Ctrl-C` stops everything.

Useful flags:

```bash
python backend/scripts/demo.py --reset        # wipe demo data, new key
python backend/scripts/demo.py --skip-build   # reuse the frontend build
python backend/scripts/demo.py --with-keys    # use your real LLM_API_KEY
```

## What to try

1. Open the app, paste the access key, press **Continue**.
2. **Ask a crowd** → pick one → ask it something. Answers come back in a
   second or two and the credit balance drops by 3.
3. **Track record** → write down a prediction, then settle it. The Brier score
   appears next to the 0.25 a coin flip earns.
4. **Credits** → the two balances, the plan table, and every credit movement.
5. **/admin** with the printed token → MRR, customers, and what is owed.

## What is real, and what is not

| | |
|---|---|
| **Real** | The API, access keys, credit metering, subscriptions and top-ups, tenant isolation, the crowd poll path, calibration scoring, the operator console, the Stripe webhook verification. |
| **Stubbed** | The model answering the crowd. Replies are canned, so this proves the plumbing and says **nothing** about answer quality. |
| **Off** | Graph building and full simulations. Those need a Zep key and the OASIS packages. |

The stub matters: it is why this runs with no accounts. It is also why you
should not judge the output until you have run it `--with-keys`.

## Running the tests

```bash
cd backend && .venv/bin/python -m pytest        # 364 tests
cd frontend && npm test                          # 33 tests
```

## Turning it into a real deployment

```bash
cp .env.example .env      # then fill it in
python backend/scripts/preflight.py
```

Preflight tells you what would break if this took real money right now, and
exits non-zero on anything blocking. Against a fresh checkout it will flag the
default `SECRET_KEY` and `FLASK_DEBUG` — both need fixing before you serve
anyone.

You will need:

- `LLM_API_KEY` — any OpenAI-compatible endpoint
- `ZEP_API_KEY` — https://app.getzep.com/
- `SECRET_KEY` — `python -c "import secrets; print(secrets.token_hex(24))"`
- `SPIDERNET_ADMIN_TOKEN` — 32+ chars, or `/admin` stays off
- `SOURCE_URL` — your repository, see Licence below

### Taking payments

```bash
stripe listen --forward-to localhost:5001/api/account/stripe/webhook
```

Put the printed `whsec_…` into `STRIPE_WEBHOOK_SECRET` and your `sk_test_…`
into `STRIPE_SECRET_KEY`. Fulfilment happens on the webhook, not the browser
redirect, so a customer who closes the tab still gets their credits.

### Issuing keys

```bash
python backend/scripts/keys.py issue --label "Acme Corp" --plan pro --subscribe
python backend/scripts/keys.py list
python backend/scripts/keys.py topup <public_id> --credits 500
```

The plaintext key is shown once and cannot be recovered.

## Licence

SpiderNet is a modified version of
[MiroFish](https://github.com/666ghj/MiroFish), under the **AGPL-3.0**.

If you run it over a network you must offer your users its source. The app does
this at `/api/legal/source` and links to it from every page — **set `SOURCE_URL`
to your own repository**, or that offer points at code you are not running.

See [NOTICE](./NOTICE) for what this fork changed. Renaming the product does not
change its licence: selling this as a closed product needs either a clean-room
build on [OASIS](https://github.com/camel-ai/oasis) or an agreement with the
upstream authors.
