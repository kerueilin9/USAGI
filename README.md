# USAGI

This is a small demo LLM-driven GUI crawler.

Quick start (Poetry):

1. Install Poetry (if not installed):

   - Windows (PowerShell):

     ```powershell
     (Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python -
     ```

2. Create environment and install dependencies:

   ```powershell
   cd path\to\USAGI
   poetry install
   poetry run playwright install
   ```

3. Copy `.env.example` to `.env` and set `GOOGLE_API_KEY` (recommended) or `OPENAI_API_KEY` as fallback.

4. Run the crawler (example):

   ```powershell
   poetry run python main.py https://example.com
   ```

Notes:

Quick start (Poetry):

1. Install Poetry (if not installed):

   - Windows (PowerShell):

     ```powershell
     (Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python -
     ```

2. Create environment and install dependencies:

   ```powershell
   cd path\to\USAGI
   poetry install
   poetry run playwright install
   ```

3. Copy `.env.example` to `.env` and set `GOOGLE_API_KEY` (recommended) or `OPENAI_API_KEY` as fallback.

4. Run the crawler (example):

   ```powershell
   poetry run python main.py https://example.com
   ```

Notes:

- The code will prefer `GOOGLE_API_KEY` and Google Generative API, falling back to OpenAI chat completions when only `OPENAI_API_KEY` is present.
- Keep your API keys secret; do not commit `.env` to source control.
