# Agentic Sales + Support Console (Enterprise Starter)

This is a local Flask + LangGraph app that:
- Provides a chat-like UI for a sales rep to paste customer emails and attach files
- Classifies the email as **Sales** or **Support** + identifies intent
- Streams backend status updates to the UI
- Creates **Sales tickets (SR-...)** or **Support tickets (SUP-...)** automatically
- Stores tickets in SQLite (`runtime.db`) along with **original email**, **intent**, and **confidence**

## Prerequisites
- Python 3.10+ recommended
- An OpenAI API key

## Setup
1) Install dependencies:
```bash
pip install -r requirements.txt
```

2) Set env var:
- Windows PowerShell:
```powershell
setx OPENAI_API_KEY "YOUR_KEY"
```
- Mac/Linux:
```bash
export OPENAI_API_KEY="YOUR_KEY"
```

3) Run:
```bash
python app.py
```

Open: http://127.0.0.1:5000

## Ticket lookup (search afterwards)
Once you get a Ticket ID like `SUP-XXXXXXXXXX` or `SR-XXXXXXXXXX`, retrieve it:

- Browser:
  - http://127.0.0.1:5000/api/tickets/SUP-XXXXXXXXXX

- Curl:
```bash
curl http://127.0.0.1:5000/api/tickets/SUP-XXXXXXXXXX
```

## What gets stored for support tickets
`support_requests` stores:
- ticket_id, created_at
- original email (subject + body)
- attachments metadata
- intent and confidence
- full classification JSON for auditing


## Python 3.12 / 3.13 note (Windows)
This project is tested to work on **Python 3.12 and 3.13** provided you install from wheels (default).
If you see build errors mentioning `meson`/`cl.exe`, you're accidentally compiling a native package from source.
Fix: create a clean venv and upgrade pip:

```powershell
Remove-Item -Recurse -Force .venv
py -3.13 -m venv .venv   # or py -3.12
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

This project does **not** require NumPy explicitly. If NumPy appears during install, it is coming from another
package already present in your environment — use a clean venv as shown above.
