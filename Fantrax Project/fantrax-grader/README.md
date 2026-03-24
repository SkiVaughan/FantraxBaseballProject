# Fantrax Fantasy Baseball Grader

## Setup

```bash
cd fantrax-grader
pip install -r requirements.txt
```

## Auth

Copy `.env.example` to `.env` and fill in your Fantrax credentials:

```
FANTRAX_USER=you@email.com
FANTRAX_PASS=yourpassword
```

Then load them before running:

```bash
# Windows (PowerShell)
$env:FANTRAX_USER=
$env:FANTRAX_PASS=
# Or use a .env loader
```

On first run, Selenium will open a headless Chrome, log in, and save
`fantraxloggedin.cookie`. Subsequent runs reuse the cookie.

## Run

```bash
streamlit run app.py
```

## Features

- Standings — live league standings
- Player Grades — z-score based A–F grades per position
- Trade Recommender — suggests trades that improve your weak spots
- Trade Block — shows who's available with their grades attached
