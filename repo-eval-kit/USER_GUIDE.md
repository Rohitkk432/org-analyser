# 🔍 Repository Evaluation Kit — User Guide

A simple, step-by-step guide to evaluate your **GitHub**, **GitLab**, **Subversion (SVN)**, or **local directory** projects. No programming experience required.

---

## What Does This Tool Do?

This tool scans your code projects and generates a **quality report** for each one — covering things like:

- How many files, tests, and lines of code exist
- How healthy the development process is (commits, pull requests where available, contributors)
- Whether CI/CD pipelines and test frameworks are set up
- Whether the code may be AI-generated
- Whether the project is likely open-source

You can scan **one project at a time**, **a local folder on your machine**, **many SVN URLs from a list**, or **all GitHub/GitLab projects you have access to** in one go.

> **SVN note:** There is no pull-request API for SVN like on GitHub/GitLab. Reports still include file metrics, tests, CI files, commit history from `svn log`, and optional quality checks — but **pull-request counts and PR-based scores will be empty or zero**.

> **Local directory note:** You can point the evaluator at any folder on your machine — a Git checkout, an SVN working copy, or a plain directory. No clone or remote access is needed. PR metrics will be empty, but file analysis, commit history (if Git/SVN), tests, and CI detection all work normally.

---

## 📋 One-Time Setup (Do This First)

You only need to follow these steps **once** on your computer.

### Step 1 — Check that Python and Git are installed (and SVN, if you use it)

Open your **Terminal** app:
- **Mac**: Press `Cmd + Space`, type `Terminal`, hit Enter
- **Windows**: Press `Win`, type `cmd`, hit Enter

Then type these two commands (one at a time, pressing Enter after each):

```
python3 --version
```
```
git --version
```

✅ If you see version numbers (e.g. `Python 3.12.0` and `git version 2.39.0`), you're good — skip to Step 2.

❌ If either says "not found":
- Install Python from https://www.python.org/downloads/ (pick 3.10 or higher)
- Install Git from https://git-scm.com/downloads

**If you will evaluate Subversion (SVN) repositories**, also run:

```
svn --version
```

If that fails, install the **Apache Subversion command-line client** (on Mac with Homebrew: `brew install subversion`; on Windows, see [Apache Subversion packages](https://subversion.apache.org/packages.html) or ask your IT team).

### Step 2 — Download this tool

Run this in your Terminal:

```
git clone <repo-url>
```

> 📌 Replace `<repo-url>` with the actual link you were given for this tool.

Then go into the downloaded folder:

```
cd repo-eval-kit
```

### Step 3 — Install the required software

Run these three commands one at a time:

```
python3 -m venv .venv
```
```
source .venv/bin/activate
```
```
pip install -r requirements.txt
```

> **Windows users**: Replace the second command with `.venv\Scripts\activate`

### Step 4 — Get your access token

A token is like a special password that lets this tool read your projects.

#### If your projects are on **GitHub**:

1. Open https://github.com/settings/tokens in your browser
2. Click **"Generate new token"** → pick **"Classic"**
3. Give it a name (e.g. `eval-kit`)
4. Tick these checkboxes:
   - ☑️ **repo**
   - ☑️ **read:org**
5. Click **"Generate token"** at the bottom
6. **Copy the token right away** (starts with `ghp_`) — you won't see it again!

#### If your projects are on **GitLab**:

1. Open https://gitlab.com/-/user_settings/personal_access_tokens in your browser
   *(Self-hosted? Use `https://your-company-gitlab/-/user_settings/personal_access_tokens`)*
2. Give it a name (e.g. `eval-kit`)
3. Tick these checkboxes:
   - ☑️ **read_api**
   - ☑️ **read_repository**
   - ☑️ **read_user**
4. Click **"Create personal access token"**
5. **Copy the token right away** (starts with `glpat-`)

#### If your projects are in **Subversion (SVN)**:

SVN servers usually ask for a **username and password** (not a Git-style API token). The evaluator uses:

- **`--svn-username`** (or the `SVN_USERNAME` environment variable) for your login name
- **`--token`** for your password *(yes, the same flag name as other platforms)*, or set `SVN_PASSWORD` / `TOKEN` when using the bulk script

Your server administrator can tell you the correct repository URL (often ends in `/trunk` or another branch path).

### Step 5 — Save your token

This way you won't have to paste it every time you run the tool.

In your Terminal (make sure you're still inside the `repo-eval-kit` folder), run **one** of these:

**GitHub users:**
```
echo "GITHUB_TOKEN=ghp_PASTE_YOUR_TOKEN_HERE" > .env
```

**GitLab users:**
```
echo "GITLAB_TOKEN=glpat-PASTE_YOUR_TOKEN_HERE" > .env
```



**SVN users** (optional — you can pass username and password on the command line instead):

Open or create the `.env` file in a text editor and add:

```
SVN_USERNAME=my_username
SVN_PASSWORD=my_password
```

The bulk SVN script also accepts the `TOKEN` environment variable as the password. Do **not** commit or share your `.env` file.

> ⚠️ Replace `ghp_PASTE_YOUR_TOKEN_HERE` (or `glpat-...`) with the actual token you copied.

✅ **Setup is complete!** You only had to do this once.

---

## ⚠️ Every Time You Open a New Terminal

Before running any evaluation commands, you must first navigate to the tool folder and activate it:

```
cd repo-eval-kit
source .venv/bin/activate
```

You'll know it's active when you see `(.venv)` at the start of your Terminal line.

---

## 🚀 Evaluate ONE Project

Use this when you know which project you want to check.

> 📌 Your project name is the `owner/repo` you see in the URL of your project. For example, if the URL is `github.com/acme-corp/billing-service`, the project name is `acme-corp/billing-service`.

### GitHub project

```
python repo_evaluator.py acme-corp/billing-service --json --output results.json
```

### GitLab project

```
python repo_evaluator.py gitlab:acme-corp/billing-service --platform gitlab --json --output results.json
```

### Faster version (skips slower AI-powered checks)

```
python repo_evaluator.py acme-corp/billing-service --json --output results.json --skip-f2p --skip-quality-checks --skip-taxonomy --skip-pr-rubrics
```

### Subversion (SVN) project

Use the **full repository URL** your team uses for `svn checkout`, and set **`--platform svn`**.

**Example** (replace with your real URL):

```
python repo_evaluator.py https://svn.example.com/myproject/trunk --platform svn --json --output results.json --svn-username YOUR_USER --token YOUR_PASSWORD
```

You can prefix the URL with `svn:` if you like — both styles work:

```
python repo_evaluator.py svn:https://svn.example.com/myproject/trunk --platform svn --json --output results.json --svn-username YOUR_USER --token YOUR_PASSWORD
```

**Check out a specific revision** (optional):

```
python repo_evaluator.py https://svn.example.com/myproject/trunk --platform svn --svn-revision 12345 --json --output results.json --svn-username YOUR_USER --token YOUR_PASSWORD
```

**If your company uses a self-signed HTTPS certificate**, add:

```
--svn-trust-cert
```

**Already have a local working copy?** Point to it and still pass the URL (used for naming and for the report):

```
python repo_evaluator.py https://svn.example.com/myproject/trunk --platform svn --repo-path /path/to/your/checkout --json --output results.json
```

**Faster SVN run** (skips slow / PR-oriented steps):

```
python repo_evaluator.py https://svn.example.com/myproject/trunk --platform svn --json --output results.json --skip-f2p --skip-quality-checks --skip-taxonomy --skip-pr-rubrics --svn-username YOUR_USER --token YOUR_PASSWORD
```

### Local directory (any folder on your machine)

No remote URL or token needed — just pass the **path** to the folder you want to evaluate. The tool auto-detects paths that start with `/`, `~`, `./`, or `.`.

**Current directory:**

```
python repo_evaluator.py . --json --output results.json
```

**Absolute path:**

```
python repo_evaluator.py /Users/you/projects/my-app --json --output results.json
```

**Home-relative path:**

```
python repo_evaluator.py ~/projects/my-app --json --output results.json
```

**Explicit platform flag** (handy if auto-detection is ambiguous):

```
python repo_evaluator.py some-folder --platform local --json --output results.json
```

**Faster local run** (skips slow / PR-oriented steps):

```
python repo_evaluator.py /path/to/project --json --output results.json --skip-f2p --skip-quality-checks --skip-taxonomy --skip-pr-rubrics
```

> If the folder is a Git repo the evaluator will pick up commit history automatically. If it's an SVN working copy it will read `svn log` from the working copy. Plain folders still get full file analysis.

### Where are my results?

After it finishes, you'll have:

| File | What it is |
|------|------------|
| `results.json` | The full detailed report |
| `billing-service.csv` | A spreadsheet-friendly version you can open in Excel or Google Sheets |

---

## 🚀 Evaluate ALL Your Projects at Once

Use this when you want to scan **every project** across all your organizations.

### Step 1 — Preview (see what will be scanned, nothing is changed)

**GitHub:**
```
python run_all_repos.py --dry-run
```

**GitLab:**
```
python run_all_repos.py --platform gitlab --dry-run
```

You'll see a list like this:

```
======================================================================
  📋  REPOSITORY INVENTORY [GITHUB] — 47 repo(s) across 3 org(s)
======================================================================

  🏢 acme-corp  (25 repos)
  ────────────────────────────────────────
    • acme-corp/billing-service  [🔒 private, Python]
    • acme-corp/web-app          [🔒 private, TypeScript]
    • acme-corp/mobile-app       [🔒 private, Kotlin]
    ...

  🏢 acme-labs  (12 repos)
  ────────────────────────────────────────
    • acme-labs/ml-pipeline  [🔒 private, Python]
    ...
```

👀 **Look through the list.** If it looks right, continue to Step 2.

### Step 2 — Run the evaluation

**GitHub:**
```
python run_all_repos.py --run
```

**GitLab:**
```
python run_all_repos.py --platform gitlab --run
```

**Faster version (recommended for large organizations):**
```
python run_all_repos.py --run --evaluator-args "--skip-f2p --skip-quality-checks --skip-taxonomy --skip-pr-rubrics"
```

This will take a while — the tool evaluates each project one by one (up to 4 in parallel).

### Step 3 — Find your results

Everything is saved in a folder called `eval_results/`:

```
eval_results/
├── _summary.json                ← overview of the entire run
├── acme-corp/
│   ├── billing-service/
│   │   ├── billing-service.json ← detailed report
│   │   └── billing-service.csv  ← spreadsheet version
│   ├── web-app/
│   │   ├── web-app.json
│   │   └── web-app.csv
│   └── ...
└── acme-labs/
    └── ...
```

### Step 4 (Optional) — Combine all results into one spreadsheet

```
python consolidate_output.py
```

This creates a single `output/combined.csv` file you can open in **Excel** or **Google Sheets**.

---

## 🚀 Evaluate Many SVN URLs at Once

Use this when you have a **text file** with one SVN URL per line. (To discover all repos under a GitHub org or GitLab group, use **`run_all_repos.py`** instead.)

### Step 1 — Create a URLs file

Create a file such as `svn_urls.txt` in the `repo-eval-kit` folder. Each non-empty line is one repository. Lines starting with `#` are ignored.

**Examples:**

```
# Team libraries
https://svn.example.com/lib/widget/trunk
https://svn.example.com/lib/parser/trunk|10420
https://svn.example.com/tools/build 50000
```

You can add a **revision** using a pipe (`URL|12345` or `URL|r12345`), a **tab** between URL and number, or a **space** before the final number.

Use **`--default-revision`** in the next step to apply one revision to every line that does not specify its own.

### Step 2 — Run the bulk SVN script

```
python bulk_svn_evaluator.py --urls-file svn_urls.txt --workers 4 --output-dir eval_results/svn_bulk --svn-username YOUR_USER --token YOUR_PASSWORD
```

**Faster run** (skips heavy steps for each repo):

```
python bulk_svn_evaluator.py --urls-file svn_urls.txt --workers 4 --output-dir eval_results/svn_bulk --svn-username YOUR_USER --token YOUR_PASSWORD --evaluator-args "--skip-f2p --skip-quality-checks --skip-taxonomy --skip-pr-rubrics"
```

**Optional:** same revision for all lines that omit one:

```
python bulk_svn_evaluator.py --urls-file svn_urls.txt --default-revision 9000 --svn-username YOUR_USER --token YOUR_PASSWORD
```

**SSL issues:** add `--svn-trust-cert`.

You can also set **`SVN_EVALUATOR_ARGS`** in the environment for extra flags (shell-style splitting).

### Step 3 — Find your results

Under `eval_results/svn_bulk/` (or your `--output-dir`):

- Each URL gets a subfolder with **`eval.json`** and **`_run.json`**
- **`_summary.json`** lists every run, timings, and errors


---

## 🎯 Common Scenarios — Just Copy and Paste

### "I want to evaluate just one specific organization"

```
python run_all_repos.py --run --org acme-corp
```

### "I also want to include my personal repos"

```
python run_all_repos.py --run --include-user-repos
```

### "I only care about private repos"

```
python run_all_repos.py --run --visibility private
```

### "I want to skip a specific project"

```
python run_all_repos.py --run --exclude-repo acme-corp/old-project
```

### "I use self-hosted GitLab (not gitlab.com)"

```
python run_all_repos.py --platform gitlab --run --gitlab-url https://gitlab.mycompany.com
```

### "I have a project on my machine and just want to scan it"

```
python repo_evaluator.py /path/to/my/project --json --output results.json
```

or from inside the project folder:

```
python repo_evaluator.py . --json --output results.json
```

### "I need to evaluate several SVN URLs"

Create `svn_urls.txt` and follow [Evaluate Many SVN URLs at Once](#evaluate-many-svn-urls-at-once).

### "SVN history in the report looks truncated"

The tool may cap how many revisions it reads from `svn log` (see **README.md** for **`SVN_LOG_LIMIT`**). To load **all** revisions (can be slow on huge repositories), run:

```
export SVN_LOG_LIMIT=0
```

before `repo_evaluator.py` or `bulk_svn_evaluator.py`.


---

## 📊 What's In The Report?

Each project's report tells you:

| Item | What it means |
|------|---------------|
| **Primary language** | The main programming language (e.g. Python, Java, TypeScript) |
| **Source files / Test files** | How many code files and test files the project has |
| **Lines of code** | Total size of the project |
| **CI/CD detected** | Whether automated build/deploy pipelines are set up |
| **Test frameworks** | What testing tools are used (e.g. pytest, jest, junit) |
| **Total commits** | How many code changes have been made over the project's lifetime |
| **Contributors** | How many people have worked on the project |
| **PR acceptance rate** | What percentage of pull requests passed quality checks *(not applicable to pure SVN — usually 0% or empty)* |
| **Open source likelihood** | Low / Medium / High — whether the project appears to be open source |
| **AI risk level** | Low / Medium / High — whether the code shows signs of being AI-generated |

---

## ❓ Something Not Working?

| Problem | Solution |
|---------|----------|
| **"No GitHub token provided"** | Your `.env` file is missing or has the wrong token. Redo [Step 5](#step-5--save-your-token) of the setup. |
| **"API rate limit exceeded"** | Your token isn't being picked up. Make sure the `.env` file is in the `repo-eval-kit` folder. |
| **"No repos found"** | Your token may not have the right permissions. Re-create it and make sure you tick `repo` + `read:org` (GitHub) or `read_api` (GitLab). Try adding `--include-user-repos` as well. |
| **"command not found: python"** | Try `python3` instead of `python` in all the commands above. |
| **It's running very slowly** | Use the "faster version" commands shown above — they skip the time-consuming AI analysis steps. |
| **Commands don't work after I re-open Terminal** | You need to re-activate the tool every time: run `cd repo-eval-kit` then `source .venv/bin/activate` |
| **GitLab: "insufficient_granular_scope"** | Your token is missing scopes. Re-create it with `read_api`, `read_repository`, and `read_user` checked. |
| **Local: "Local path is not a directory"** | The path you gave doesn't exist or isn't a folder. Double-check it with `ls /your/path`. |
| **SVN: "svn checkout failed"** | Check the URL, username, and password. Try `--svn-trust-cert` if HTTPS uses an internal certificate. Confirm `svn --version` works. |
| **SVN: SSL or certificate errors** | Add `--svn-trust-cert` to `repo_evaluator.py`. For bulk runs, add `--svn-trust-cert` to `bulk_svn_evaluator.py`. |
| **SVN: authentication failed** | Use `--svn-username` and `--token` (password). For bulk runs, `--token` or `SVN_PASSWORD` / `TOKEN` env vars. |

---

## 🧾 All Commands at a Glance

| What you want to do | Command to run |
|---|---|
| See all your GitHub repos (preview) | `python run_all_repos.py --dry-run` |
| See all your GitLab repos (preview) | `python run_all_repos.py --platform gitlab --dry-run` |
| Evaluate **all** GitHub repos | `python run_all_repos.py --run` |
| Evaluate **all** GitLab repos | `python run_all_repos.py --platform gitlab --run` |
| Evaluate all repos **(fast mode)** | `python run_all_repos.py --run --evaluator-args "--skip-f2p --skip-quality-checks --skip-taxonomy --skip-pr-rubrics"` |
| Evaluate only one organization | `python run_all_repos.py --run --org my-org-name` |
| Evaluate **one** GitHub project | `python repo_evaluator.py owner/repo --json --output results.json` |
| Evaluate **one** GitLab project | `python repo_evaluator.py gitlab:group/repo --platform gitlab --json --output results.json` |
| Evaluate a **local folder** | `python repo_evaluator.py /path/to/project --json --output results.json` |
| Evaluate **current directory** | `python repo_evaluator.py . --json --output results.json` |
| Evaluate **one** SVN project | `python repo_evaluator.py https://svn.example.com/proj/trunk --platform svn --json --output results.json --svn-username USER --token PASS` |
| Evaluate **one** SVN project at revision *N* | `python repo_evaluator.py URL --platform svn --svn-revision N --json --output results.json --svn-username USER --token PASS` |
| Evaluate **many** SVN URLs from a file | `python bulk_svn_evaluator.py --urls-file svn_urls.txt --workers 4 --svn-username USER --token PASS` |
| Evaluate one project **(fast)** | `python repo_evaluator.py owner/repo --json --output results.json --skip-f2p --skip-quality-checks --skip-taxonomy --skip-pr-rubrics` |
| Combine all CSVs into one spreadsheet | `python consolidate_output.py` |

---

## 🖥️ Streamlit UI (repo picker)

The eval kit ships with a browser UI to browse GitHub orgs/repos and run **`repo_evaluator.py`** or **`cybersecurity_pr_scanner.py`** without copying long commands manually.

### What you need installed

| Requirement | Why |
|---|---|
| **Python 3** + **[virtual env](README.md)** | Same setup as the rest of the toolkit. |
| **Dependencies**: `pip install -r requirements.txt` | Pulls **`streamlit`**, **`requests`**, **`python-dotenv`**, **`openai`**, etc. (`requirements.txt` is in the repo root.) |
| **`.env`** in **`repo-eval-kit/`** | Same file as CLI: **`GITHUB_TOKEN`** or **`GH_TOKEN`** for GitHub API. |
| **`OPENAI_API_KEY`** (optional but recommended for security scans) | Only needed if you use the **Cybersecurity PR scanner** with **Layer 2** (LLM classification). Leave Layer 2 off or use **`--skip-layer2`** if you do not want OpenAI. |

### Run the Streamlit UI

From the **`repo-eval-kit`** folder (same place as **`repo_evaluator.py`**):

```bash
cd repo-eval-kit
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run ui/github_eval_picker.py
```

Alternative:

```bash
python -m streamlit run ui/github_eval_picker.py
```

1. Enter or confirm your token in the sidebar (or rely on **`GITHUB_TOKEN` / `GH_TOKEN`**).
2. Click **Connect / verify token**.
3. Load org or personal repos, select repositories.
4. Under **What to run**, choose **Full repo evaluator** or **Cybersecurity PR scanner**.
5. Adjust options and click **Run on selected repositories**.

**Outputs:**

- The sidebar **Output base folder** defaults to **`eval_results`**. Full evaluator runs appear under **`eval_results/ui_runs/<UTC-timestamp>/`**. Cybersecurity scans appear under **`eval_results/ui_security_scans/<UTC-timestamp>/`** (nested per repo slug).
- Each security scan writes JSON such as **`{repo_slug}/{repo}_security_prs.json`**, plus a **`session_transcript.log`** for that UI session at the **`ui_runs`** or **`ui_security_scans`** timestamp folder root.

Optional: enable **Stream live script logs** to watch subprocess output live (the UI uses **`python -u`** and **`PYTHONUNBUFFERED`** for smoother streaming).

---

## 🔒 Cybersecurity PR scanner (`cybersecurity_pr_scanner.py`)

You can run this from the Terminal **or** from the Streamlit UI (same script).

### Prerequisites

| Item | Detail |
|---|---|
| **GitHub token** | **`GITHUB_TOKEN`**, **`GH_TOKEN`**, or **`--token`** on the CLI. Needs enough scope to **list pulls** on the repos you scan (typically **`repo`** for private repos; public repos vary). |
| **Layer 1 only** (`--skip-layer2`) | No OpenAI; heuristic score + signals only in the JSON. |
| **Layer 2 (LLM)** | **`OPENAI_API_KEY`** in the environment; **`openai`** package (included via **`requirements.txt`**). Layer 2 runs only when layer 1 score ≥ **`--layer1-threshold`** (default **6** in the CLI). |

### Example CLI commands

Scan one repo, full JSON output (layers 1 + 2 when above threshold):

```bash
python cybersecurity_pr_scanner.py --repo owner/name --token "$GITHUB_TOKEN" --json-out ./code_security_prs.json --layer1-threshold 6
```

Heuristics only (no OpenAI):

```bash
python cybersecurity_pr_scanner.py --repo owner/name --token "$GITHUB_TOKEN" --json-out ./code_security_l1.json --skip-layer2
```

Useful flags (also mirrored in the UI): **`--max-prs N`**, **`--no-fetch-files`** (faster, skips per-PR file lists), **`--layer2-model gpt-4o-mini`**.

The JSON schema includes **`layer1`** (score/signals) and **`layer2`** when run (`null` when not scored or skipped). **`layer2.is_security_related: true`** is the LLM’s “cybersecurity-relevant” classification.

---

*For advanced options and developer reference, see [README.md](README.md).*

