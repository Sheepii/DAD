# DAD - Design A Day

Small Django app for daily handoff tasks.

## Run

```powershell
.\.venv\Scripts\python manage.py runserver 0.0.0.0:8080
```

On first run, `manage.py` auto-installs `requirements.txt` if anything is missing.
Set `DAD_SKIP_PIP=1` to disable auto-install.

Open:
- `http://127.0.0.1:8080/` for the Dad view
- `http://127.0.0.1:8080/admin/` for Admin
- `http://127.0.0.1:8080/create/` for quick task creation
- `http://127.0.0.1:8080/task/<id>/etsy/` for an Etsy listing preview (copy/paste + tag tools)

## Production server (IIS/ARR or Linux)

If IIS/ARR is terminating TLS, stop using `manage.py runserver`; instead host Django behind a WSGI/ASGI server that IIS can reverse-proxy to.

1. Install dependencies once more to pull the production server. `gunicorn` is already listed for Linux deployments, and Windows installations can use Waitress:
   ```powershell
   .\.venv\Scripts\python -m pip install -r requirements.txt
   ```
2. IIS/ARR should forward `X-Forwarded-Proto`/`X-Forwarded-Host` to the backend and point to `127.0.0.1:8000` (or another port you choose).
3. On Windows, run the new helper that launches Waitress, which is production-ready and happily serves behind ARR:
   ```powershell
   .\.venv\Scripts\python run_prod_server.py
   ```
   Override `PROD_HOST`/`PROD_PORT` if ARR targets a different address/port.
4. On Linux or containers you can run Gunicorn directly:
   ```bash
   gunicorn dad.wsgi:application --bind 127.0.0.1:8000 --workers 3
   ```
5. Because `SECURE_PROXY_SSL_HEADER` is set, Django trusts the proxy headers and will generate HTTPS redirects and `request.is_secure()` correctly.

Watch the console for `Proxy headers: ...` logs if you need to confirm which scheme and host Django reports while the proxy is active.

## Deploy on Koyeb (with Postgres)

Koyeb’s filesystem is ephemeral, so SQLite will be wiped on restarts. Use Postgres.

1. Create a Postgres database in Koyeb and copy the `DATABASE_URL`.
2. In your Koyeb app, set environment variables:
   - `DATABASE_URL`
   - `SECRET_KEY` (random long string)
   - `DEBUG=false`
   - `DJANGO_ALLOWED_HOSTS` = your Koyeb domain (ex: `your-app.koyeb.app`)
   - `GOOGLE_DRIVE_ROOT_FOLDER_ID`
   - `GOOGLE_DRIVE_CREDENTIALS_JSON` (paste full OAuth client JSON)
   - `GOOGLE_DRIVE_TOKEN_JSON` (paste full token JSON)
3. Build command:
   ```
   pip install -r requirements.txt
   python manage.py collectstatic --noinput
   python manage.py migrate
   ```
4. Run command:
   ```
   gunicorn dad.wsgi:application --bind 0.0.0.0:$PORT
   ```

Admin login (local dev):
- Username: `admin`
- Password: `dad12345`

## Create your first task

1. Go to Admin -> Tasks -> Add.
2. Add a due date (today), title, notes, Drive file ID, and video URL if needed.
3. Add Task Steps inline (order + text) or choose a template to auto-create steps.

The Today page shows tasks where `due_date = today` and `assigned_to = Dad`.
If you assign a different name, open `http://127.0.0.1:8000/today/?assignee=Name`.

## Daily repeating tasks

Use Admin -> Recurring Tasks to create tasks that repeat every day.
Each time the Today page is opened, it auto-creates today's task for any
active recurring items (once per day).

For default steps in Admin, you can enter one step per line (no JSON needed).

## Mockup folder workflow

Paste a Google Drive folder link/ID into the Task's "mockup folder" field.
Images inside the folder are pulled in by name order (1, 2, 3, etc.) and shown
in the mockup slots. Dad can drag new files onto slots to replace them.

## Mockup generator (no Figma)

You can configure mockup templates and generate images automatically from the
uploaded design:

1. Admin -> Task Templates -> open your template.
2. Add a **sample design** Drive ID to the template (for previews).
3. Add Mockup Templates (background, overlay, optional mask), order them.
4. On the task page, click **Generate Mockups From Design**.

All design and layer images are normalized to **4000x4000** if needed.

Admin previews:
- Each mockup template shows a preview image in Admin (uses the sample design).

Layer order:
- Set `overlay_position` to place overlay above or below the design.
- Use the Mockup Template list actions "Move up/down" to reorder slides.

Auto-generation:
- By default, when a design is uploaded (or changed), mockups auto-generate the
  next time the task page is opened.
- Toggle in Admin -> App Settings -> auto_generate_mockups.

Requires Pillow:
```powershell
.\.venv\Scripts\python -m pip install Pillow
```

SVG support (auto-convert to PNG for rendering):
```powershell
.\.venv\Scripts\python -m pip install cairosvg
```

## Google Drive setup (optional but enabled)

1. Create a dedicated Drive folder and copy its ID.
2. In Admin -> App Settings, paste the Drive folder ID.
3. In Admin -> App Settings, set `drive_credentials_file_path` and `drive_token_file_path`
   (or leave blank to use `credentials.json` and `token.json` in the project root).
4. Place your OAuth client file at `credentials.json` in the project root (or
   whatever path you set in App Settings).
5. Run:

```powershell
.\.venv\Scripts\python manage.py drive_auth
```

This writes `token.json`. After that, uploading a design file in the New Task page
will place it in `Designs/YYYY-MM-DD/` under your root folder.

If you previously pasted full Drive links into fields, run:

```powershell
.\.venv\Scripts\python manage.py fix_drive_ids
```

## AI tag generation (optional)

The Etsy preview page can generate tags via OpenAI.

Set env vars:
- `OPENAI_API_KEY` (required)
- `OPENAI_MODEL` (optional, default `gpt-4o-mini`)
- `OPENAI_BASE_URL` (optional, default `https://api.openai.com`)

Tags must validate as: exactly 13 tags, each under 20 characters, letters/numbers/spaces only.

## Stores + per-store listing status

Add stores in Admin -> Stores. Each task auto-creates a publication row per active store.
In the Etsy preview screen you can set per-store status + listing URL and save it back into DAD.

## Design Automation Roadmap (Planned)

This will use the existing Django database configuration (local `db.sqlite3` or
`DATABASE_URL` on Koyeb). No external alert channel; warnings will be shown in
the Admin/Dad UI. Scheduling is every day (no skips).

Data (Django DB):
- `DesignFile`: filename, date_assigned, status, drive_file_id, size_mb, ext, source_folder, created_at, updated_at.
- `DesignHistory`: design_file, posted_date, original_drive_file_id, notes.
- `SOPGuide`: name, scribe_id_or_url, context_route, active, updated_at.
- `SOPReplyTemplate`: name, trigger_keywords, reply_text, active, updated_at.

Workflow:
- Intake Engine: scan `/Dump_Zone`, validate PNG/JPG <= 20MB, find next available
  date from `/Scheduled`, rename to `YYYY-MM-DD`, move to `/Scheduled`, insert/update
  `DesignFile`. Invalid files go to `/Error` with reason logged.
- Inventory Guard: compute runway from `/Scheduled` count and last date, return JSON
  for Admin; show a warning banner when runway is low. No outbound alerts.
- Daily Publish: load today’s file by date and feed Dad view (already done), mark `status=active`.
- Cleanup & Archive: after posted, move from `/Scheduled` to `/Done`, update `status=posted`,
  append to `DesignHistory`, avoid overwrite by timestamping duplicates.
- Emergency Recycling (optional): if today’s file is missing, copy a random `/Done`
  file into the active slot and mark `status=recycled`, plus a UI warning banner.
