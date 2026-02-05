# DAD - Design A Day

Small Django app for daily handoff tasks.

## Run

```powershell
.\.venv\Scripts\python manage.py runserver
```

On first run, `manage.py` auto-installs `requirements.txt` if anything is missing.
Set `DAD_SKIP_PIP=1` to disable auto-install.

Open:
- `http://127.0.0.1:8000/` for the Dad view
- `http://127.0.0.1:8000/admin/` for Admin
- `http://127.0.0.1:8000/create/` for quick task creation

## Deploy on Koyeb (with Postgres)

Koyeb’s filesystem is ephemeral, so SQLite will be wiped on restarts. Use Postgres.

1. Create a Postgres database in Koyeb and copy the `DATABASE_URL`.
2. In your Koyeb app, set environment variables:
   - `DATABASE_URL`
   - `SECRET_KEY` (random long string)
   - `DEBUG=false`
   - `DJANGO_ALLOWED_HOSTS` = your Koyeb domain (ex: `your-app.koyeb.app`)
   - `GOOGLE_DRIVE_ROOT_FOLDER_ID`
   - `GOOGLE_DRIVE_CREDENTIALS_FILE` / `GOOGLE_DRIVE_TOKEN_FILE` if you store them on disk
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
