# Run a second frontend locally

To use the API from another worktree, add `http://localhost:3001` to the
comma-separated `GRAFY_CORS_ORIGINS` in the API checkout's `.env`. Restart the
API to load the updated list.

From the second worktree, run:

```sh
npm --prefix apps/web run dev -- --port 3001
```

The Next.js rewrite uses the existing API on port 8000 by default. Sign in
through the frontend at `GRAFY_PUBLIC_ORIGIN` (normally
`http://localhost:3000`), where OIDC sends its callback. Both frontends share
the session and CSRF cookies when you use `localhost` for both ports.
