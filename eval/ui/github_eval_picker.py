#!/usr/bin/env python3
"""
GitHub org/repo picker + run evaluations from the browser.

Uses GITHUB_TOKEN or GH_TOKEN from the environment by default (via .env).
Optional UI override is never written to disk.

Run from the eval-kit repository root:

    pip install streamlit
    streamlit run eval_kit/ui/github_eval_picker.py

Or:

    python -m streamlit run eval_kit/ui/github_eval_picker.py
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import requests
import streamlit as st
from dotenv import load_dotenv

# eval-kit repo root (parent of the eval_kit/ package, two levels above ui/)
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

load_dotenv(dotenv_path=PACKAGE_ROOT / ".env", override=False)

from eval.run_all_repos import GitHubAPI  # noqa: E402

PERSONAL_KEY = "__personal__"


def _effective_token(ui_token: str) -> str:
    ui_token = (ui_token or "").strip()
    if ui_token:
        return ui_token
    return (
        os.getenv("GITHUB_TOKEN", "").strip()
        or os.getenv("GH_TOKEN", "").strip()
        or ""
    )


def _safe_slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", s).strip("_") or "run"


def _truncate_log(s: str, max_chars: int = 200_000) -> str:
    if len(s) <= max_chars:
        return s
    return "... [earlier output truncated for UI performance]\n\n" + s[-max_chars:]


def _insert_python_u_flag(cmd: List[str]) -> List[str]:
    """Force unbuffered stdio when invoking a Python script (helps live logs in pipes)."""
    if len(cmd) < 2:
        return cmd
    exe = Path(cmd[0]).name.lower()
    if "python" not in exe:
        return cmd
    if cmd[1] == "-u":
        return cmd
    return [cmd[0], "-u", *cmd[1:]]


def _run_cmd_stream_logs(
    cmd: List[str],
    cwd: str,
    env: dict,
    *,
    headline: str,
    status_holder,
    log_holder,
    throttle_s: float = 0.25,
) -> Tuple[int, str]:
    """Stream merged stdout/stderr. Uses a background reader + UI poll loop so Streamlit can redraw.

    Blocking on ``proc.stdout`` in the main thread often prevents Streamlit from sending any
    intermediate updates to the browser; reading in a thread fixes that.
    """
    cmd = _insert_python_u_flag(cmd)
    run_env = {**env, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=run_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    chunks: List[str] = []
    buf_lock = threading.Lock()

    def read_stdout() -> None:
        try:
            assert proc.stdout is not None
            for line in iter(proc.stdout.readline, ""):
                with buf_lock:
                    chunks.append(line)
        finally:
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()

    placeholder = headline + "\n⏳ Subprocess started — output will stream here…\n"
    log_holder.code(_truncate_log(placeholder), language="text")
    last_paint = time.monotonic()

    try:
        while True:
            exit_code = proc.poll()
            with buf_lock:
                body_so_far = "".join(chunks)
            block = headline + body_so_far
            n_lines = body_so_far.count("\n")
            status_holder.info(
                f"**{'Running' if exit_code is None else 'Finished'}** — "
                f"**{n_lines}** log line(s) in buffer (stdout + stderr merged)"
            )
            now = time.monotonic()
            if now - last_paint >= throttle_s or exit_code is not None:
                log_holder.code(_truncate_log(block), language="text")
                last_paint = now
            if exit_code is not None:
                break
            time.sleep(0.1)
    finally:
        reader.join(timeout=300)

    code = proc.wait()
    with buf_lock:
        body = "".join(chunks)
    footer = f"\n── exit code **{code}** ──\n"
    full = headline + body + footer
    status_holder.markdown(
        f"**`{'OK' if code == 0 else 'FAILED'}`** — exit code **{code}**"
    )
    log_holder.code(_truncate_log(full), language="text")
    return code, full


def _run_cmd_capture_logs(
    cmd: List[str],
    cwd: str,
    env: dict,
    *,
    headline: str,
    status_holder,
    log_holder,
) -> Tuple[int, str]:
    cmd = _insert_python_u_flag(cmd)
    run_env = {**env, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        env=run_env,
        capture_output=True,
        text=True,
    )
    out = proc.stdout or ""
    err = proc.stderr or ""
    block = headline + out + (("\n" + err) if err.strip() else "") + f"\n── exit code **{proc.returncode}** ──\n"
    status_holder.markdown(
        f"{headline.strip()} — **`{'OK' if proc.returncode == 0 else 'FAILED'}`** (exit {proc.returncode})"
    )
    log_holder.code(_truncate_log(block), language="text")
    return proc.returncode, block


def main() -> None:
    st.set_page_config(page_title="GitHub eval picker", layout="wide")
    st.title("GitHub repo picker")
    st.caption("Load organizations and repositories using your GitHub token, select repos, then run the eval kit.")

    if "loaded_repos" not in st.session_state:
        st.session_state.loaded_repos = []
    if "load_source" not in st.session_state:
        st.session_state.load_source = None
    if "gh_api" not in st.session_state:
        st.session_state.gh_api = None
    if "gh_user_login" not in st.session_state:
        st.session_state.gh_user_login = None

    with st.sidebar:
        st.subheader("Authentication")
        st.markdown("Token priority: sidebar field → **`GITHUB_TOKEN` / `GH_TOKEN`** → `.env`")
        ui_token = st.text_input(
            "Override token (optional)",
            type="password",
            value="",
            help="Leave empty to use environment variables.",
        )
        token = _effective_token(ui_token)
        connect = st.button("Connect / verify token", type="primary")

        if connect or st.session_state.gh_api is None:
            if connect:
                if not token:
                    st.error("No token found. Set GITHUB_TOKEN or enter an override.")
                    st.session_state.gh_api = None
                else:
                    try:
                        api = GitHubAPI(token)
                        user = api.authenticated_user()
                        st.session_state.gh_api = api
                        st.session_state.gh_user_login = user.get("login", "")
                        st.success(f"Signed in as **{st.session_state.gh_user_login}**")
                    except requests.HTTPError as e:
                        st.session_state.gh_api = None
                        st.error(f"GitHub rejected the token: {e}")

        st.divider()
        st.subheader("Outputs")
        output_base = st.text_input(
            "Output base folder",
            value="eval_results",
            help="Relative to repository root unless absolute.",
        )
        resolve_path = PACKAGE_ROOT / output_base if not Path(output_base).is_absolute() else Path(output_base)

        st.divider()
        mode = st.radio(
            "What to run",
            (
                "Full repo evaluator (`repo_evaluator.py`)",
                "Cybersecurity PR scanner (`cybersecurity_pr_scanner.py`)",
            ),
        )
        stream_logs = st.checkbox(
            "Stream live script logs",
            value=True,
            help="Show merged stdout/stderr while each script runs (sets PYTHONUNBUFFERED=1). "
            "Uncheck to show output only after each repo finishes.",
        )

    api: Optional[GitHubAPI] = st.session_state.gh_api
    if not token:
        st.warning("Configure **`GITHUB_TOKEN`** (or **`GH_TOKEN`**) or use the sidebar override, then click **Connect**.")
        return

    if api is None and not connect:
        st.info("Click **Connect / verify token** in the sidebar to continue.")
        return

    if api is None:
        return

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("1. Choose source")
        org_list = []
        try:
            org_list = api.list_orgs()
        except requests.HTTPError as e:
            st.warning(f"Could not list organizations (token may lack `read:org`): {e}")

        org_logins = [o.get("login", "") for o in org_list if o.get("login")]
        source_options = [PERSONAL_KEY] + sorted(org_logins)
        labels = ["My repositories (owner + collaborator)"] + sorted(org_logins)

        choice_idx = st.selectbox(
            "Organization or personal repos",
            range(len(source_options)),
            format_func=lambda i: labels[i],
        )
        selected_key = source_options[choice_idx]

        load_repos = st.button("Load repository list", type="primary")

    with col_b:
        st.subheader("2. Filter & select")
        filter_q = st.text_input("Filter by name (substring)", value="")

    if load_repos:
        with st.spinner("Fetching repositories from GitHub…"):
            try:
                if selected_key == PERSONAL_KEY:
                    st.session_state.loaded_repos = api.list_user_repos()
                    st.session_state.load_source = f"user:{st.session_state.gh_user_login}"
                else:
                    st.session_state.loaded_repos = api.list_org_repos(selected_key)
                    st.session_state.load_source = f"org:{selected_key}"
            except requests.HTTPError as e:
                st.error(f"Failed to list repositories: {e}")
                st.session_state.loaded_repos = []

    repos = st.session_state.loaded_repos or []
    if st.session_state.load_source:
        st.caption(f"Loaded **{len(repos)}** repositories from **{st.session_state.load_source}**")

    if not repos:
        st.stop()

    rows = []
    for r in repos:
        fn = r.get("full_name") or ""
        if not fn:
            continue
        if filter_q and filter_q.lower() not in fn.lower():
            continue
        vis = "private" if r.get("private") else "public"
        arch = "archived" if r.get("archived") else ""
        lang = r.get("language") or "—"
        hint = f"{fn}  [{vis}]  {lang}"
        if arch:
            hint += f"  ({arch})"
        rows.append((hint, fn))

    options = [fn for _, fn in rows]
    labels_map = {fn: lab for lab, fn in rows}
    chosen = st.multiselect(
        "Repositories to evaluate",
        options=options,
        format_func=lambda fn: labels_map.get(fn, fn),
        help="Pick one or more `owner/name` entries.",
    )

    st.subheader("3. Run options")

    if mode.startswith("Full"):
        c1, c2, c3, c4 = st.columns(4)
        skip_f2p = c1.checkbox("Skip F2P tests", value=True)
        skip_qc = c2.checkbox("Skip quality checks", value=True)
        skip_tax = c3.checkbox("Skip taxonomy", value=True)
        skip_rub = c4.checkbox("Skip PR rubrics", value=True)
        extra = st.text_area(
            "Extra CLI args for repo_evaluator.py",
            value="",
            help="Example: `--max-prs 30` or `--start-date 2025-01-01`",
        )
    else:
        c1, c2 = st.columns(2)
        skip_l2 = c1.checkbox("Layer 2: skip LLM (heuristics only)", value=False)
        max_prs = c2.number_input("Max PRs per repo (0 = all)", min_value=0, value=0)
        l1_thr = st.number_input("Layer 1 threshold", min_value=1, max_value=30, value=6)
        no_files = st.checkbox("Do not fetch per-PR file lists (faster)", value=False)

    run_btn = st.button("Run on selected repositories", type="primary", disabled=len(chosen) == 0)

    if not run_btn:
        st.stop()

    st.divider()
    st.subheader("Run output")
    if stream_logs:
        st.caption(
            "Logs update while the subprocess runs (main thread must not block on the pipe — "
            "reader thread + **`python -u`**). You should see a “Subprocess started” line immediately."
        )

    out_root = resolve_path.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["GITHUB_TOKEN"] = token
    env["GH_TOKEN"] = token

    transcript_parts: List[str] = []
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    session_tag = "ui_runs" if mode.startswith("Full") else "ui_security_scans"
    session_dir = out_root / session_tag / ts
    session_dir.mkdir(parents=True, exist_ok=True)

    for full_name in chosen:
        owner, repo = full_name.split("/", 1)
        safe = _safe_slug(full_name)
        if mode.startswith("Full"):
            parts = [
                sys.executable,
                "-m",
                "eval.repo_evaluator",
                full_name,
                "--token",
                token,
                "--json",
            ]
            if skip_f2p:
                parts.append("--skip-f2p")
            if skip_qc:
                parts.append("--skip-quality-checks")
            if skip_tax:
                parts.append("--skip-taxonomy")
            if skip_rub:
                parts.append("--skip-pr-rubrics")
            try:
                parts.extend(shlex.split(extra.strip()) if extra.strip() else [])
            except ValueError as e:
                st.error(f"Invalid extra args: {e}")
                st.stop()
            batch_dir = out_root / "ui_runs" / ts / safe
            batch_dir.mkdir(parents=True, exist_ok=True)
            out_json = batch_dir / f"{repo}.json"
            parts.extend(["--output", str(out_json)])
            cmd = parts
        else:
            batch_dir = out_root / "ui_security_scans" / ts / safe
            batch_dir.mkdir(parents=True, exist_ok=True)
            out_json = batch_dir / f"{repo}_security_prs.json"
            cmd = [
                sys.executable,
                "-m",
                "eval.cybersecurity_pr_scanner",
                "--repo",
                full_name,
                "--token",
                token,
                "--json-out",
                str(out_json),
                "--layer1-threshold",
                str(int(l1_thr)),
            ]
            if skip_l2:
                cmd.append("--skip-layer2")
            if no_files:
                cmd.append("--no-fetch-files")
            if max_prs and max_prs > 0:
                cmd.extend(["--max-prs", str(int(max_prs))])

        headline = (
            "\n\n"
            + "=" * 80
            + f"\n## {full_name}\n\n```\n"
            + " ".join(cmd)
            + "\n```\n\n"
        )

        status_slot = st.empty()
        log_slot = st.empty()
        if stream_logs:
            _, block = _run_cmd_stream_logs(
                cmd,
                cwd=str(PACKAGE_ROOT),
                env=env,
                headline=headline,
                status_holder=status_slot,
                log_holder=log_slot,
            )
        else:
            _, block = _run_cmd_capture_logs(
                cmd,
                cwd=str(PACKAGE_ROOT),
                env=env,
                headline=headline,
                status_holder=status_slot,
                log_holder=log_slot,
            )
        transcript_parts.append(block)

    full_transcript = "".join(transcript_parts)
    transcript_path = session_dir / "session_transcript.log"
    try:
        transcript_path.write_text(full_transcript, encoding="utf-8")
    except OSError as e:
        st.warning(f"Could not save transcript file: {e}")

    with st.expander("Full transcript (session)", expanded=False):
        st.code(_truncate_log(full_transcript, max_chars=80_000), language="text")
        st.download_button(
            label="Download full transcript (.log)",
            data=full_transcript,
            file_name=f"eval_ui_{ts}.log",
            mime="text/plain",
        )

    st.success(f"Finished. JSON under `{session_dir}`, transcript: `{transcript_path}`.")


if __name__ == "__main__":
    main()
