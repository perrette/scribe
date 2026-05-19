from pathlib import Path
import re
import sys
import tomllib
from typing import Callable

from desktop_ai_core.frontends import AbstractFrontendApp
from desktop_ai_core.frontends.terminal import Menu, Item, SetValueItem

from scribe.backends import BACKENDS, probe_backend

_VENDOR_PREFIX = {
    "openai": "OpenAI",
    "groq": "Groq",
    "whisper": "Whisper",
    "vosk": "Vosk",
}

_vosk_model_to_lang: dict[str, str] | None = None


def _vosk_language_for_model(model_id: str) -> str | None:
    global _vosk_model_to_lang
    if _vosk_model_to_lang is None:
        toml_path = Path(__file__).parent / "models.toml"
        with open(toml_path, "rb") as f:
            config = tomllib.load(f)
        _vosk_model_to_lang = {}
        for lang_code, entry in config.get("vosk", {}).items():
            mid = entry.get("model")
            if mid:
                lang_name = config.get("_meta", {}).get(lang_code, {}).get("language", lang_code)
                _vosk_model_to_lang[mid] = lang_name
    return _vosk_model_to_lang.get(model_id)


def format_model_label(backend_name: str, model_id: str) -> str:
    vendor = _VENDOR_PREFIX.get(backend_name, backend_name.capitalize())
    backend_cls = BACKENDS.get(backend_name)
    is_local = backend_cls.is_local if backend_cls is not None else False

    if backend_name == "vosk":
        lang = _vosk_language_for_model(model_id)
        display = lang if lang is not None else model_id
        return f"{vendor} {display} (local, live partials)"

    qualifier = ""
    if backend_name == "openai" and model_id == "whisper-1":
        qualifier = " (deprecated)"
    elif is_local:
        qualifier = " (local)"

    return f"{vendor} {model_id}{qualifier}"


_DEFAULT_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-4o-mini-transcribe", "whisper-1"],
    "groq": ["whisper-large-v3-turbo"],
    "whisper": ["small", "medium", "large", "large-v3", "large-v3-turbo"],
    "vosk": [],
}


def _vosk_models_from_toml() -> list[str]:
    toml_path = Path(__file__).parent / "models.toml"
    with open(toml_path, "rb") as f:
        config = tomllib.load(f)
    return [entry["model"] for entry in config.get("vosk", {}).values() if "model" in entry]


def _models_for_backend(backend_name: str, app_state) -> list[str]:
    o = getattr(app_state, "o", None)
    if backend_name == "whisper":
        models = getattr(o, "whisper_models", None) if o is not None else None
        return list(models) if models else list(_DEFAULT_MODELS["whisper"])
    if backend_name == "vosk":
        models = getattr(o, "vosk_models", None) if o is not None else None
        if models:
            return list(models)
        try:
            return _vosk_models_from_toml()
        except Exception:
            return list(_DEFAULT_MODELS["vosk"])
    return list(_DEFAULT_MODELS.get(backend_name, []))


class AppState(AbstractFrontendApp):
    """Shared state + callbacks consumed by build_menu.

    Inherits params / set_param / get_param / checked / callback_toggle_option /
    notify_error / error_callback / logger from AbstractFrontendApp.
    """

    def __init__(self, transcriber=None, session=None, o=None, view=None, error_callback=None):
        super().__init__(
            params=vars(o) if o is not None else {},
            view=view,
            error_callback=error_callback,
        )
        self.transcriber = transcriber
        self.session = session
        self.o = o
        self.is_running = True

    # ── Predicates ─────────────────────────────────────────────────
    def is_recording(self, item=None) -> bool:
        return bool(self.session is not None and getattr(self.session, "busy", False))

    def is_not_recording(self, item=None) -> bool:
        return not self.is_recording(item)

    def _is_whisper(self, item=None) -> bool:
        return self.transcriber is not None and getattr(self.transcriber, "backend", None) == "whisper"

    def _has_keyboard(self, item=None) -> bool:
        return bool(getattr(self.o, "keyboard", False))

    # ── Top-level callbacks ────────────────────────────────────────
    def cb_record(self, view, item):
        # exit menu loop → main() proceeds to start_recording
        return False

    def cb_stop(self, view, item):
        if self.session is not None:
            self.session.interrupt = True
        return True

    def cb_cancel(self, view, item):
        if self.session is not None:
            self.session.cancelled = True
            self.session.interrupt = True
        return True

    def cb_quit(self, view, item):
        sys.exit(0)

    def cb_set_model(self, backend_name: str, model_id: str) -> Callable:
        """Factory: return a callback that switches to (backend, model)."""
        def _cb(view, item):
            self.transcriber = None
            self.session = None
            self.o.backend = backend_name
            self.o.model = model_id
            return False
        return _cb

    # ── Option-toggle callbacks ────────────────────────────────────
    def cb_toggle_clipboard(self, view, item):
        self.o.clipboard = not self.o.clipboard
        self.params["clipboard"] = self.o.clipboard
        return True

    def cb_toggle_keyboard(self, view, item):
        self.o.keyboard = not bool(self.o.keyboard)
        self.params["keyboard"] = self.o.keyboard
        return True

    def cb_toggle_frontend(self, view, item):
        self.o.frontend = "terminal" if self.o.frontend == "tray" else "tray"
        self.params["frontend"] = self.o.frontend
        return True

    def cb_toggle_auto_restart(self, view, item):
        new = not bool(getattr(self.transcriber, "restart_after_silence", False))
        if self.transcriber is not None:
            self.transcriber.restart_after_silence = new
        self.o.restart_after_silence = new
        self.params["restart_after_silence"] = new
        return True

    # ── SetValueItem callbacks ─────────────────────────────────────
    def _coerce_float(self, raw, label):
        try:
            return float(raw)
        except (TypeError, ValueError):
            print(f"Invalid {label}. Must be a float.")
            return None

    def cb_set_duration(self, view, item):
        val = self._coerce_float(item.value(item), "duration")
        if val is not None:
            self.o.duration = val
            if self.transcriber is not None:
                self.transcriber.timeout = val
        return True

    def cb_set_silence(self, view, item):
        val = self._coerce_float(item.value(item), "duration")
        if val is not None:
            self.o.silence = val
            if self.transcriber is not None:
                self.transcriber.silence_duration = val
        return True

    def cb_set_silence_db(self, view, item):
        val = self._coerce_float(item.value(item), "threshold")
        if val is not None:
            self.o.silence_db = val
            if self.transcriber is not None:
                self.transcriber.silence_thresh = val
        return True

    def cb_set_output_file(self, view, item):
        ans = item.value(item)
        if not ans:
            self.o.output_file = None
            return True
        invalid_regex = re.compile(r'[^A-Za-z0-9_\-\\\/\.]')
        if not invalid_regex.search(ans):
            self.o.output_file = ans
        else:
            print(f"Invalid characters: {' '.join(map(repr, invalid_regex.findall(ans)))}")
            print(f"Invalid file name: {repr(ans)}")
        return True

    def cb_set_latency(self, view, item):
        val = self._coerce_float(item.value(item), "latency")
        if val is not None:
            self.o.latency = val
        return True

    def current_model_label(self) -> str:
        if self.transcriber is None:
            return ""
        return format_model_label(self.transcriber.backend, self.transcriber.model_name)


def _backend_models_menu(app_state, backend_name: str) -> Menu:
    items = [
        Item(format_model_label(backend_name, model),
             app_state.cb_set_model(backend_name, model))
        for model in _models_for_backend(backend_name, app_state)
    ]
    vendor = _VENDOR_PREFIX.get(backend_name, backend_name.capitalize())
    return Menu(items, name=vendor)


def _choose_model_menu(app_state) -> Menu:
    items = []
    for backend_name in BACKENDS:
        try:
            ok, _ = probe_backend(backend_name)
        except Exception:
            ok = False
        if not ok:
            continue
        vendor = _VENDOR_PREFIX.get(backend_name, backend_name.capitalize())
        is_local = bool(getattr(BACKENDS[backend_name], "is_local", False))
        label = f"{vendor} (local)" if is_local else vendor
        items.append(Item(label, _backend_models_menu(app_state, backend_name)))
    return Menu(items, name="Choose Model")


def _toggle_options_menu(app_state) -> Menu:
    items = [
        Item("c", app_state.cb_toggle_clipboard, help="toggle clipboard",
             checked=lambda item: bool(getattr(app_state.o, "clipboard", False))),
        Item("k", app_state.cb_toggle_keyboard, help="toggle keyboard",
             checked=lambda item: bool(getattr(app_state.o, "keyboard", False))),
        Item("x", app_state.cb_toggle_frontend, help="toggle tray app mode",
             checked=lambda item: getattr(app_state.o, "frontend", None) == "tray"),
        Item("a", app_state.cb_toggle_auto_restart, help="auto-restart after silence",
             checked=lambda item: bool(getattr(app_state.transcriber, "restart_after_silence", False)),
             visible=app_state._is_whisper),
        SetValueItem("t", app_state.cb_set_duration,
                     value=lambda item: getattr(app_state.transcriber, "timeout", None),
                     type=float, help="duration (s)", visible=app_state._is_whisper),
        SetValueItem("b", app_state.cb_set_silence,
                     value=lambda item: getattr(app_state.transcriber, "silence_duration", None),
                     type=float, help="silence break (s)", visible=app_state._is_whisper),
        SetValueItem("db", app_state.cb_set_silence_db,
                     value=lambda item: getattr(app_state.transcriber, "silence_thresh", None),
                     type=float, help="silence threshold (db)", visible=app_state._is_whisper),
        SetValueItem("f", app_state.cb_set_output_file,
                     value=lambda item: getattr(app_state.o, "output_file", None) or "",
                     type=str, help="output file"),
        SetValueItem("latency", app_state.cb_set_latency,
                     value=lambda item: getattr(app_state.o, "latency", None),
                     type=float, help="keyboard latency (s)", visible=app_state._has_keyboard),
    ]
    return Menu(items, name="Toggle Options")


def build_menu(app_state) -> Menu:
    """Construct the unified scribe menu spec shared between frontends."""
    items = [
        Item("Record", app_state.cb_record, visible=app_state.is_not_recording,
             help="[Enter] start recording"),
        Item("Stop", app_state.cb_stop, visible=app_state.is_recording,
             help="stop the current recording"),
        Item("Cancel", app_state.cb_cancel, visible=app_state.is_recording,
             help="cancel the current recording"),
        Item("Choose Model", _choose_model_menu(app_state),
             help="select backend and model"),
        Item("Toggle Options", _toggle_options_menu(app_state),
             help="toggle output / recording options"),
        Item("Quit", app_state.cb_quit, help="quit scribe"),
    ]
    return Menu(items)
