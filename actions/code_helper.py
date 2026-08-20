import subprocess
import sys
import json
import re
import tempfile
import time
from pathlib import Path

from core.gemini_models import get_flash_model


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR           = get_base_dir()
API_CONFIG_PATH    = BASE_DIR / "config" / "api_keys.json"
DESKTOP            = Path.home() / "Desktop"
MAX_BUILD_ATTEMPTS = 3

# Last generated snippet — used when user says "save that SQL" with only output_path
_LAST: dict[str, str] = {"code": "", "lang": "python", "title": ""}


def _remember(code: str, lang: str = "python", title: str = "") -> None:
    _LAST["code"] = code or ""
    _LAST["lang"] = lang or "python"
    _LAST["title"] = title or ""


def _is_quota_err(exc: BaseException) -> bool:
    s = str(exc).lower()
    return any(
        x in s
        for x in (
            "429", "quota", "resource exhausted", "rate limit",
            "high demand", "resource_exhausted", "too many requests",
        )
    )


def _gemini_text(prompt: str, retries: int = 3) -> str:
    """Call Flash with short retries on quota / 429."""
    last: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = _get_gemini().generate_content(prompt)
            return (getattr(resp, "text", None) or "").strip()
        except Exception as e:
            last = e
            if not _is_quota_err(e) or attempt >= retries - 1:
                raise
            wait = 12 * (attempt + 1)
            print(f"[Code] Quota/rate limit — retry in {wait}s ({attempt + 1}/{retries})")
            time.sleep(wait)
    raise last or RuntimeError("Gemini generate failed")


def _quota_message(exc: BaseException) -> str:
    return (
        f"QUOTA: Code generation is rate-limited ({exc}). "
        "Do not invent code. Tell the user the service is busy and you will retry shortly."
    )


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _get_gemini(model: str | None = None):
    from google import genai
    model = model or get_flash_model()
    _c = genai.Client(api_key=_get_api_key())

    class _W:
        def generate_content(self, contents):
            return _c.models.generate_content(model=model, contents=contents)

    return _W()


def _clean_code(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


_EXT_MAP = {
    "python": ".py", "py": ".py",
    "javascript": ".js", "js": ".js",
    "typescript": ".ts", "ts": ".ts",
    "html": ".html", "css": ".css",
    "java": ".java", "cpp": ".cpp", "c": ".c",
    "bash": ".sh", "shell": ".sh", "powershell": ".ps1",
    "sql": ".sql", "json": ".json", "rust": ".rs", "go": ".go",
}


def _lang_ext(language: str) -> str:
    return _EXT_MAP.get((language or "python").lower(), ".py")


def _panel_on() -> bool:
    try:
        from memory.config_manager import get_content_panel_enabled
        return bool(get_content_panel_enabled())
    except Exception:
        return True


def _display(player, title: str, body: str) -> None:
    if not player or not body:
        return
    fn = getattr(player, "show_content", None)
    if callable(fn):
        try:
            fn(title, body, html=False, nowrap=True)
        except TypeError:
            try:
                fn(title, body)
            except Exception:
                pass
        except Exception:
            pass
    lang = "python"
    t = (title or "").lower()
    if "sql" in t:
        lang = "sql"
    _remember(body, lang, title)


def _resolve_save_path(output_path: str, language: str, *, temp: bool = False) -> Path:
    if output_path:
        p = Path(output_path)
        return p if p.is_absolute() else DESKTOP / p
    name = f"athena_code{_lang_ext(language)}"
    if temp:
        d = Path(tempfile.gettempdir()) / "athena_code"
        d.mkdir(parents=True, exist_ok=True)
        return d / name
    return DESKTOP / name


def _read_file(file_path: str) -> tuple[str, str]:
    if not file_path:
        return "", "No file path provided."
    p = Path(file_path)
    if not p.exists():
        return "", f"File not found: {file_path}"
    try:
        return p.read_text(encoding="utf-8"), ""
    except Exception as e:
        return "", f"Could not read file: {e}"


def _save_file(path: Path, content: str) -> str:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Saved to: {path}"
    except Exception as e:
        return f"Could not save: {e}"


def _preview(code: str, lines: int = 10) -> str:
    all_lines = code.splitlines()
    preview   = "\n".join(all_lines[:lines])
    suffix    = f"\n... ({len(all_lines) - lines} more lines)" if len(all_lines) > lines else ""
    return preview + suffix


def _has_error(output: str) -> bool:
    error_signals = ["error", "exception", "traceback", "syntaxerror",
                     "nameerror", "typeerror", "stderr", "failed", "crash"]
    return any(s in output.lower() for s in error_signals)


def _take_screenshot() -> Path | None:
    try:
        import pyautogui
        screenshot_path = Path.home() / "Desktop" / f"Athena_debug_{int(time.time())}.png"
        screenshot = pyautogui.screenshot()
        screenshot.save(str(screenshot_path))
        print(f"[Code] 📸 Screenshot: {screenshot_path}")
        return screenshot_path
    except Exception as e:
        print(f"[Code] ⚠️ Screenshot failed: {e}")
        return None


def _image_to_base64(path: Path) -> str:
    import base64
    return base64.b64encode(path.read_bytes()).decode("utf-8")


_VALID_INTENTS = {"write", "edit", "explain", "run", "build", "screen_debug", "optimize", "show"}


def _detect_intent(description: str, file_path: str, code: str) -> str:
    """
    Dil bağımsız niyet tespiti — sabit anahtar kelime listesi YOK.
    Kullanıcı hangi dilde konuşursa konuşsun, açıklama Gemini'ye
    sınıflandırtılır. API'ye ulaşılamazsa dile bakmayan yapısal
    ipuçlarına (dosya diskte var mı, kod verilmiş mi) düşülür.
    """
    desc        = (description or "").strip()
    desc_l      = desc.lower()
    file_exists = bool(file_path) and Path(file_path).exists()

    # Show file in the HUD panel — do not regenerate or "explain"
    if file_exists and any(
        w in desc_l
        for w in (
            "show", "display", "content panel", "content window",
            "extract the content", "extract the contents",
        )
    ):
        return "show"
    if code and not file_path and any(w in desc_l for w in ("run", "execute", "count", "how many")):
        return "run"

    if desc:
        try:
            ctx = []
            if file_path:
                ctx.append(f"a file path is provided (exists on disk: {file_exists})")
            if code:
                ctx.append("an inline code snippet is provided")
            prompt = (
                "Classify a coding assistant request into exactly ONE intent word.\n"
                "The request may be written in ANY language.\n\n"
                f"Request: {desc}\n"
                + (f"Context: {'; '.join(ctx)}\n" if ctx else "")
                + "\nIntents:\n"
                "  write        = create new code from scratch\n"
                "  edit         = modify an existing file\n"
                "  explain      = describe what given code/file does\n"
                "  show         = display an existing file in the content panel (no regenerate)\n"
                "  run          = execute a file OR an inline code snippet\n"
                "  build        = write code, run it, and iterate until it works\n"
                "  screen_debug = analyze an error currently visible on the user's screen\n"
                "  optimize     = refactor / clean up / speed up existing code\n\n"
                "Reply with ONLY the intent word, nothing else."
            )
            ans = _gemini_text(prompt).strip().lower()
            ans = ans.strip("`'\". \n")
            if ans in _VALID_INTENTS:
                return ans
        except Exception as e:
            print(f"[Code] Intent classification failed ({e}) — structural fallback")

    # Yapısal geri dönüş — hiçbir dile bağlı değil
    if file_exists:
        return "show" if not desc else "edit"
    if code:
        return "run"
    return "write"

def _write(description: str, language: str, output_path: str, player=None) -> tuple[str, Path | None]:
    lang  = language or "python"
    prompt = f"""You are an expert {lang} developer.
Write clean, working, well-commented {lang} code for the description below.

Rules:
- Output ONLY the code. No explanation, no markdown, no backticks.
- Add helpful inline comments.
- Handle errors and edge cases properly.
- Use modern best practices.

Description: {description}

Code:"""

    response_text = _gemini_text(prompt)
    code     = _clean_code(response_text)
    _remember(code, lang)
    # Save to disk only when the user gave a path, or the content panel is off
    # (so the code is not lost). Otherwise it is shown in the HUD panel.
    if output_path or not _panel_on():
        path = _resolve_save_path(output_path, lang)
        _save_file(path, code)
        return code, path
    return code, None


def _fix_code(code: str, error_output: str, description: str) -> str:
    prompt = f"""You are an expert debugger.
The code below failed with the following error. Fix it.
Return ONLY the corrected code — no explanation, no markdown, no backticks.

Original goal: {description}

Error:
{error_output[:2000]}

Broken code:
{code}

Fixed code:"""

    return _clean_code(_gemini_text(prompt))


def _run_file(path: Path, args: list, timeout: int) -> str:
    interpreters = {
        ".py":  [sys.executable],
        ".js":  ["node"],
        ".ts":  ["ts-node"],
        ".sh":  ["bash"],
        ".ps1": ["powershell", "-File"],
        ".rb":  ["ruby"],
        ".php": ["php"],
    }
    interp = interpreters.get(path.suffix.lower())
    if not interp:
        return f"No interpreter for {path.suffix}."

    try:
        result = subprocess.run(
            interp + [str(path)] + (args or []),
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout, cwd=str(path.parent)
        )
        output = result.stdout.strip()
        error  = result.stderr.strip()
        parts  = []
        if output: parts.append(f"Output:\n{output}")
        if error:  parts.append(f"Stderr:\n{error}")
        return "\n\n".join(parts) if parts else "Executed with no output."

    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except FileNotFoundError:
        return f"Interpreter not found: {interp[0]}."
    except Exception as e:
        return f"Execution error: {e}"


def _build(description, language, output_path, args, timeout, speak=None, player=None) -> str:
    if not description:
        return "Please describe what you want me to build, sir."

    if player:
        player.write_log("[Code] Build started...")

    lang = language or "python"

    try:
        code, path = _write(description, lang, output_path, player)
        if path is None:
            path = _resolve_save_path("", lang, temp=True)
            _save_file(path, code)
        print(f"[Code] ✅ Written: {path}")
        _display(player, f"{lang.upper()} — generated", code)
    except Exception as e:
        msg = f"Could not write initial code: {e}"
        if speak: speak(msg)
        return msg

    last_output = ""
    for attempt in range(1, MAX_BUILD_ATTEMPTS + 1):
        print(f"[Code] 🔄 Attempt {attempt}/{MAX_BUILD_ATTEMPTS}")
        if player:
            player.write_log(f"[Code] Attempt {attempt}...")

        last_output = _run_file(path, args, timeout)

        if not _has_error(last_output):
            _display(player, f"{lang.upper()} — generated", code)
            loc = f"Saved to {path}." if output_path or not _panel_on() else "Shown in the content panel."
            msg = (
                f"Build complete, sir. "
                f"The code is working after {attempt} attempt{'s' if attempt > 1 else ''}. "
                f"{loc}"
            )
            if speak: speak(msg)
            return f"{msg}\n\nOutput:\n{last_output}"

        print(f"[Code] ⚠️ Error on attempt {attempt}, fixing...")
        if player:
            player.write_log(f"[Code] Fixing (attempt {attempt})...")

        try:
            code = _fix_code(code, last_output, description)
            _save_file(path, code)
            _display(player, f"{lang.upper()} — generated", code)
        except Exception as e:
            msg = f"Could not fix code on attempt {attempt}: {e}"
            if speak: speak(msg)
            return msg

    msg = (
        f"I was unable to build a working version after {MAX_BUILD_ATTEMPTS} attempts, sir. "
        f"The last error was: {last_output[:200]}"
    )
    if speak: speak(msg)
    loc = f"Last code saved to: {path}" if output_path or not _panel_on() else "Last code is in the content panel."
    return f"{msg}\n\n{loc}"

def _looks_like_save_only(description: str, output_path: str) -> bool:
    if not output_path:
        return False
    d = (description or "").lower().strip()
    if not d:
        return True
    if re.search(r"\b(save|store|write to|as an sql|as a file|to disk|root directory)\b", d):
        if re.search(r"\b(generate|create|design|write a |write an )\b", d):
            return False
        return True
    return False


def _write_action(description, language, output_path, player, code="") -> str:
    lang = language or "python"
    # Save the last generated snippet without regenerating
    if _looks_like_save_only(description, output_path) and (code or _LAST.get("code")):
        body = code or _LAST["code"]
        lang = language or _LAST.get("lang") or "python"
        path = _resolve_save_path(output_path, lang)
        status = _save_file(path, body)
        _display(player, f"{lang.upper()} — saved", body)
        return f"Saved last generated {lang} to: {path}\n{status}"
    # Ready-made snippet (SQL, Python, …) — show it; do not regenerate.
    if not description and code:
        _display(player, f"{lang.upper()} — snippet", code)
        if output_path:
            path = _resolve_save_path(output_path, lang)
            _save_file(path, code)
            return f"Code shown in the content panel. Saved to: {path}"
        return "Code shown in the content panel (not saved to disk)."
    if not description:
        return "Please describe what you want me to write, or pass the code to display."
    if player:
        player.write_log("[Code] Writing code...")
    try:
        generated, path = _write(description, lang, output_path, player)
        print(f"[Code] ✅ Written: {path or 'content panel'}")
        _display(player, f"{lang.upper()} — generated", generated)
        if path:
            return f"Code written. Saved to: {path}\n\nPreview:\n{_preview(generated)}"
        return (
            "Code written and shown in the content panel (not saved to disk). "
            "Ask to save it if you want a file.\n\n"
            f"Preview:\n{_preview(generated)}"
        )
    except Exception as e:
        if _is_quota_err(e):
            return _quota_message(e)
        return f"Could not generate code: {e}"


def _edit_action(file_path, instruction, player) -> str:
    if not file_path:
        return "Please provide a file path to edit, sir."
    if not instruction:
        return "Please describe what change to make, sir."

    content, err = _read_file(file_path)
    if err:
        return err

    if player:
        player.write_log("[Code] Editing file...")

    model  = _get_gemini()
    prompt = f"""You are an expert code editor.
Apply the following change to the code below.
Return ONLY the complete updated code — no explanation, no markdown, no backticks.

Change: {instruction}

Original code:
{content}

Updated code:"""

    try:
        response = model.generate_content(prompt)
        edited   = _clean_code(response.text)
    except Exception as e:
        if _is_quota_err(e):
            return _quota_message(e)
        return f"Could not edit code: {e}"

    status = _save_file(Path(file_path), edited)
    print(f"[Code] ✅ Edited: {file_path}")
    _display(player, f"EDIT — {Path(file_path).name}", edited)
    return f"File edited. {status}\n\nPreview:\n{_preview(edited)}"


def _explain_action(file_path, code, player) -> str:
    if file_path and not code:
        code, err = _read_file(file_path)
        if err:
            return err
    if not code:
        return "Please provide code or a file path to explain, sir."

    if player:
        player.write_log("[Code] Analyzing code...")

    prompt = f"""Explain what this code does in simple, clear language.
Focus on: what it does, how it works, and any important details.
Be concise — 3 to 6 sentences maximum.

Code:
{code[:4000]}

Explanation:"""

    try:
        explanation = _gemini_text(prompt)
        label = Path(file_path).name if file_path else "code"
        # Show the source in the panel so "extract / show me the file" still works
        # if Gemini classified this as explain.
        if file_path and code:
            _display(player, f"FILE — {label}", code)
        else:
            _display(player, f"EXPLAIN — {label}", explanation)
        return explanation
    except Exception as e:
        if _is_quota_err(e):
            if file_path and code:
                _display(player, f"FILE — {Path(file_path).name}", code)
                return (
                    f"Shown {Path(file_path).name} in the content panel. "
                    f"Explanation skipped (quota): {e}"
                )
            return _quota_message(e)
        return f"Could not explain code: {e}"


def _normalize_args(args) -> list:
    if not args:
        return []
    if isinstance(args, list):
        return [str(a) for a in args]
    if isinstance(args, str):
        return args.split()
    return [str(args)]


def _run_action(file_path, args, timeout, player, code="", language="python") -> str:
    args = _normalize_args(args)
    lang = (language or "python").lower()
    if code and not file_path:
        if lang in ("sql",):
            _display(player, "SQL — snippet", code)
            return (
                "SQL cannot be executed locally. Shown in the content panel. "
                "Use a database or Metabase to run it."
            )
        tmp = _resolve_save_path("", lang, temp=True)
        tmp = tmp.parent / f"athena_run_{int(time.time())}{tmp.suffix}"
        _save_file(tmp, code)
        file_path = str(tmp)
    if not file_path:
        return "Please provide a file path or inline code to run, sir."
    p = Path(file_path)
    if not p.exists():
        return f"File not found: {file_path}"
    if player:
        player.write_log(f"[Code] Running {p.name}...")
    output = _run_file(p, args, timeout)
    _display(player, f"RUN — {p.name}", output)
    return output


def _show_action(file_path, code, player) -> str:
    if file_path and not code:
        code, err = _read_file(file_path)
        if err:
            return err
    if not code:
        return "Please provide a file path or code to show, sir."
    label = Path(file_path).name if file_path else "code"
    _display(player, f"FILE — {label}", code)
    n = len(code.splitlines())
    return f"Shown {label} in the content panel ({n} lines). Not regenerated."


def _optimize_action(file_path, code, language, output_path, player) -> str:

    if file_path and not code:
        code, err = _read_file(file_path)
        if err:
            return err
    if not code:
        return "Please provide code or a file path to optimize, sir."

    if player:
        player.write_log("[Code] Optimizing code...")

    lang  = language or "python"
    prompt = f"""You are an expert {lang} developer and code reviewer.
Optimize the following code for:
1. Performance — eliminate unnecessary operations, use efficient data structures
2. Readability — clear variable names, proper formatting, logical structure
3. Best practices — modern {lang} patterns, error handling, type hints if applicable
4. Remove dead code, redundant comments, and unnecessary complexity

Return ONLY the optimized code — no explanation, no markdown, no backticks.

Original code:
{code[:6000]}

Optimized code:"""

    try:
        optimized = _clean_code(_gemini_text(prompt))
    except Exception as e:
        if _is_quota_err(e):
            return _quota_message(e)
        return f"Could not optimize code: {e}"

    if file_path:
        save_path = Path(file_path)
        status = _save_file(save_path, optimized)
        print(f"[Code] ✅ Optimized: {save_path}")
    elif output_path or not _panel_on():
        save_path = _resolve_save_path(output_path, lang)
        status = _save_file(save_path, optimized)
        print(f"[Code] ✅ Optimized: {save_path}")
    else:
        status = "Shown in the content panel (not saved to disk)."
        print("[Code] ✅ Optimized: content panel")

    _display(player, f"{lang.upper()} — optimized", optimized)

    original_lines  = len(code.splitlines())
    optimized_lines = len(optimized.splitlines())
    diff = original_lines - optimized_lines

    return (
        f"Code optimized. {status}\n"
        f"Lines: {original_lines} → {optimized_lines} "
        f"({'−' if diff > 0 else '+'}{abs(diff)} lines)\n\n"
        f"Preview:\n{_preview(optimized)}"
    )


def _screen_debug_action(description, file_path, player, speak=None) -> str:

    if player:
        player.write_log("[Code] Taking screenshot for analysis...")

    print("[Code] 📸 Capturing screen for debug...")


    screenshot_path = _take_screenshot()
    if not screenshot_path:
        return "Could not take screenshot, sir. Please make sure PyAutoGUI is installed."


    file_content = ""
    if file_path:
        file_content, err = _read_file(file_path)
        if err:
            print(f"[Code] ⚠️ Could not read file: {err}")

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=_get_api_key())

        image_bytes  = screenshot_path.read_bytes()
        image_base64 = _image_to_base64(screenshot_path)

        user_question = description or "What error or problem do you see on the screen? How can it be fixed?"

        context = ""
        if file_content:
            context = f"\n\nAdditionally, here is the related file content:\n```\n{file_content[:4000]}\n```"

        analysis_prompt = f"""You are an expert programmer and debugger analyzing a screenshot.

User's question: {user_question}{context}

Please:
1. Identify any errors, exceptions, or problems visible on the screen
2. Explain what is causing the problem in simple terms
3. Provide a concrete fix or solution
4. If there's code visible, show the corrected version

Be specific and actionable. If you see an error message, quote it exactly."""

        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            analysis_prompt,
        ]

        response = client.models.generate_content(
            model=get_flash_model(),
            contents=contents,
        )

        analysis = response.text.strip()
        print(f"[Code] ✅ Screen analysis complete")

        try:
            screenshot_path.unlink()
        except Exception:
            pass

        if file_path and file_content:

            code_match = re.search(r"```[a-zA-Z]*\n(.*?)```", analysis, re.DOTALL)
            if code_match:
                fixed_code = code_match.group(1).strip()
                save_path  = Path(file_path)
                _save_file(save_path, fixed_code)
                analysis += f"\n\n✅ Fixed code has been saved to: {file_path}"
                print(f"[Code] ✅ Fixed code saved: {file_path}")

        return analysis

    except Exception as e:

        try:
            screenshot_path.unlink()
        except Exception:
            pass
        return f"Screen analysis failed: {e}"


def code_helper(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None
) -> str:
    """
    Called from main.py.

    parameters:
        action      : write | edit | explain | run | build | screen_debug | optimize | auto
        description : What the code should do / what change to make / what problem to analyze
        language    : Programming language (default: python)
        output_path : Where to save — user specifies full path or filename
        file_path   : Path to existing file (edit / explain / run / build / optimize)
        code        : Raw code string (explain/optimize without a file)
        args        : CLI argument list for run/build
        timeout     : Execution timeout in seconds (default: 30)
    """
    p           = parameters or {}
    action      = p.get("action", "auto").lower().strip()
    description = p.get("description", "").strip()
    language    = p.get("language", "python").strip()
    output_path = p.get("output_path", "").strip()
    file_path   = p.get("file_path", "").strip()
    code        = p.get("code", "").strip()
    args        = p.get("args", [])
    timeout     = int(p.get("timeout", 30))

    if action == "auto":
        action = _detect_intent(description, file_path, code)
        print(f"[Code] 🤖 Auto-detected: {action}")

    if action in ("show", "display", "read"):
        return _show_action(file_path, code, player)

    if action == "write":
        return _write_action(description, language, output_path, player, code=code)

    elif action == "edit":
        return _edit_action(
            file_path,
            description or p.get("instruction", ""),
            player
        )

    elif action == "explain":
        desc_l = description.lower()
        if file_path and any(
            w in desc_l
            for w in ("show", "display", "content panel", "content window", "extract")
        ):
            return _show_action(file_path, code, player)
        return _explain_action(file_path, code, player)

    elif action == "run":
        return _run_action(file_path, args, timeout, player, code=code, language=language)

    elif action == "build":
        return _build(description, language, output_path, args, timeout, speak, player)

    elif action == "optimize":
        return _optimize_action(file_path, code, language, output_path, player)

    elif action == "screen_debug":
        return _screen_debug_action(description, file_path, player, speak)

    else:
        return f"Unknown action: '{action}'. Use write, edit, explain, show, run, build, optimize, or screen_debug."