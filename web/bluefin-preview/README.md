Bluefin GM — the main application interface, using real league data.

From the repository root, with the existing backend on 127.0.0.1:8000:

```powershell
.venv/Scripts/python.exe web/bluefin-preview/serve.py
```

The regular Vite application on http://localhost:5173 and the production build use these same assets.
The optional server above also serves them on http://localhost:4175 and proxies the backend on loopback.
ESPN credentials remain on the backend.

`app.js` contains data views; `app-shell.js` contains settings, comparison and rendering.
`bootstrap.js` manages interactions, `i18n.js` handles localization, and `analytics.js` renders statistical charts.
NBA health and game logs are fetched server-side and cached in `routers/bluefin.py`.

The frontend Docker image is built from the repository root: `docker build -f web/frontend/Dockerfile .`.
