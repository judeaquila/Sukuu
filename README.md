# Sukuu — The African Online School 🇬🇭

A Skool-style online school platform where **creators** publish course content and
market it for a fee, and **students** learn with access to a private community
per course. Built for Ghana first, with cedis (GHS) pricing and payments through
**Paystack** (card, MTN MoMo, Telecel Cash, AirtelTigo Money) — ready to scale
across Africa (NGN supported).

## Stack

- **Django 6** (Python 3.13) — server-rendered templates + Tailwind (CDN) UI
- **SQLite** in development → switch to PostgreSQL in production
- **Paystack** hosted checkout + webhook (HMAC SHA512 verified)

## Apps

| App         | Purpose |
|-------------|---------|
| `accounts`  | Email-first users, Student/Creator roles, creator profiles |
| `courses`   | Courses → modules → lessons (YouTube/Vimeo/MP4), pricing in GHS, enrollment, lesson progress |
| `community` | Private community per course: posts, replies, likes, creator pins |
| `payments`  | Paystack init/verify/webhook, `Transaction` ledger, platform commission split, withdrawals |

## Business model

Platform takes a commission (`PLATFORM_COMMISSION_PERCENT`, default **10%**) of every
paid course sale. The creator's earnings and the platform's fee are recorded on each
`Transaction` and visible in the creator studio dashboard.

## Quick start

```powershell
# 1. Environment (once)
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. Add your Paystack TEST keys to .env
#    PAYSTACK_SECRET_KEY=sk_test_...
#    PAYSTACK_PUBLIC_KEY=pk_test_...

# 3. Database + demo content
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py seed_demo          # optional sample data

# 4. Run
.venv\Scripts\python manage.py runserver
# Local port already busy? use: runserver 127.0.0.1:8001
```

Demo logins (password `pass1234`):

- Creator: `kojo@creator.gh`, `ama@creator.gh`
- Student: `kwame@student.gh`
- Admin (`/admin`): `admin@sukuu.gh` / `admin123`

## Payment flow (how it works)

1. Student clicks **Enroll** on a paid course.
2. A pending `Transaction` (reference `OLTSCH-XXXXXXXX`) is created and the student
   is redirected to Paystack's hosted checkout — **card or Mobile Money**.
3. Paystack redirects back to `/payments/callback/?reference=…`
   → we **verify with the API** (never trust the redirect alone) → grant enrollment.
4. The redundant path: Paystack's **webhook** (`/payments/webhook/`) delivers
   `charge.success`; signatures are verified with HMAC-SHA512 and unknown
   references are ignored — so access is granted exactly once, idempotently.

### Configure the webhook in Paystack

Dashboard → Settings → API Keys & Webhooks → add
`https://your-domain.com/payments/webhook/` (use the live URL when deploying;
locally you can expose it with a tunnel if you want end-to-end webhook tests).

## Test the payment loop

With **test keys** in `.env`, use any Paystack test card
(e.g. `4084 0840 8408 4081`, any future expiry, CVV 100) or the test MoMo flow.
Enrollment unlocks automatically on success; the transaction lands in
`/admin` (Payments → Transactions) with the amount, channel and commission split.

## Environment variables (`.env`)

| Variable | Meaning |
|---|---|
| `DJANGO_SECRET_KEY` | Generate a long random string for production |
| `DJANGO_DEBUG` | `False` in production |
| `PAYSTACK_SECRET_KEY` | `sk_test_…` / `sk_live_…` |
| `PAYSTACK_PUBLIC_KEY` | `pk_test_…` / `pk_live_…` |
| `PLATFORM_CURRENCY` | `GHS` (default) or `NGN` |
| `PLATFORM_COMMISSION_PERCENT` | Default `10` |

## Production checklist

- [ ] PostgreSQL (`DATABASES`), `DEBUG=False`, real `SECRET_KEY`, set `ALLOWED_HOSTS`
- [ ] `python manage.py collectstatic` + serve `staticfiles/` and `media/`
- [ ] HTTPS everywhere (Paystack requires it for callbacks)
- [ ] Configure live webhook URL (as above)
- [ ] Creator payout policy (withdrawals model is in place; connect Paystack
      Transfers for automatic disbursement)
- [ ] Set up e-mail backend (password reset etc.)

## Roadmap ideas (after MVP)

- Subscriptions & drip content, quiz/assignment module, certificates,
  referral/affiliate links, mobile app (React Native), USSD MoMo Direct Pay,
  Francophone support (French UI → Côte d'Ivoire / Senegal), auto payouts via Paystack Transfers.
