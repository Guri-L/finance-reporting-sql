# Running on a server, and switching on Google sign-in

## Same SQL, different connection

Nothing in the SQL or migrations names a host. Locally, Docker Compose points
`DATABASE_URL` at its own PostgreSQL. On a server, point it at the company
database instead:

```bash
pip install -r requirements.txt
export DATABASE_URL=postgresql://finance_owner:<password>@db.internal.yourcompany.com:5432/finance
export REPORTING_DB_PASSWORD=<password for the app login>
python -m scripts.setup          # migrate, load, create read-only login, run controls
```

In a real deployment the load step would read the ledger extract instead of
generated data: `python -m scripts.load_data /path/to/extract` with the same
CSV layout, then `python -m scripts.run_checks`. A DBA who prefers to create
logins themselves can skip `create_app_login` and simply run
`GRANT finance_reporting_reader TO <their login>`.

Run the app with the read-only login:

```bash
export REPORTING_DATABASE_URL=postgresql://reporting_app:<password>@db.internal.yourcompany.com:5432/finance
docker build -t finance-reporting . && docker run -p 8000:8000 --env-file .env finance-reporting
```

Put it behind the company's HTTPS reverse proxy and set `COOKIE_SECURE=true`.

## Google Workspace sign-in

1. In Google Cloud Console, create an OAuth client (type: Web application)
   in a project owned by your Workspace. Set the OAuth consent screen to
   **Internal**, so only accounts in your Workspace can use it.
2. Add the redirect URI `https://<your host>/auth/google/callback`.
3. Set, in the server's environment (never in the repository):

   ```
   AUTH_MODE=google
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_ALLOWED_DOMAIN=yourcompany.com
   SESSION_SECRET=<48+ random characters>
   COOKIE_SECURE=true
   ```

4. Add people to `app.users` with their Workspace email (see
   [permissions](permissions.md)).

With `AUTH_MODE=google` the demo page and demo route are switched off and
demo users can no longer sign in. The domain is checked three times: Google
is asked for that domain, the ID token's `hd` claim must match it, and the
email must end with it. The person must then also be an active user in
`app.users`.
