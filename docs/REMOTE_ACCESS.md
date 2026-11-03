# Remote access threat review

CareerOS holds your resume facts, work-authorization answers, application history and private documents. It has **no login**. By default it listens only on `127.0.0.1`, and `careeros serve` refuses any other address unless `ALLOW_REMOTE=true`.

## Threats if exposed
- Anyone who can reach the port can read and change everything, including work-authorization data.
- Approval and "record it" buttons could be clicked by someone else, corrupting your history.
- Job descriptions are untrusted HTML-free text, but a network attacker could still probe the app.
- Plain HTTP on a shared network leaks everything in transit.

## If you really need remote access
1. Prefer not to: the dashboard is meant to run on your Mac.
2. If you must, use a private mesh VPN you control (devices you own only), keep the app bound to the VPN interface, and set `ALLOW_REMOTE=true`.
3. Never port-forward from your router or deploy to a public host without first adding real authentication, HTTPS and secure cookies. CSRF protection is already in place for state-changing requests.
4. Keep backups (`careeros backup`) before trying anything.

## Docker
`docker-compose.yml` publishes the port as `127.0.0.1:8000:8000`, so only this Mac can reach it. Inside the container the app listens on `0.0.0.0`, which `CONTAINER=true` allows only for that wildcard address. Changing the mapping to `8000:8000` would expose CareerOS to your whole network.
