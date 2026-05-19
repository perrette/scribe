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


def format_model_label(backend_name: str, model_id: str, include_vendor: bool = True) -> str:
    vendor = _VENDOR_PREFIX.get(backend_name, backend_name.capitalize())
    backend_cls = BACKENDS.get(backend_name)
    is_local = backend_cls.is_local if backend_cls is not None else False

    if backend_name == "vosk":
        lang = _vosk_language_for_model(model_id)
        display = lang if lang is not None else model_id
        if include_vendor:
            return f"{vendor} {display} (local, streaming)"
        return display

    qualifier = ""
    if is_local and include_vendor:
        qualifier = " (local)"

    if include_vendor:
        return f"{vendor} {model_id}{qualifier}"
    return f"{model_id}{qualifier}"


_DEFAULT_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-4o-transcribe", "gpt-4o-mini-transcribe"],
    "groq": ["whisper-large-v3-turbo"],
    "whisper": ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"],
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

    The same instance backs both the terminal and tray frontends. ``bind_tray``
    attaches a pystray Icon + Microphone so the tray-mode branches of the
    callbacks below can drive recording threads directly; without binding, the
    callbacks behave as the terminal flow (exit the menu loop and let ``main``
    drive the next iteration).
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
        self.icon = None
        self.micro = None

    def bind_tray(self, icon, micro) -> None:
        """Attach a pystray Icon + Microphone for tray-mode callbacks."""
        self.icon = icon
        self.micro = micro

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
        if self.icon is not None:
            return self._tray_record()
        # terminal: exit menu loop → main() proceeds to start_recording
        return False

    def cb_stop(self, view, item):
        if self.icon is not None:
            if self.icon._session is not None:
                self.icon._session.interrupt = True
            return None
        if self.session is not None:
            self.session.interrupt = True
        return True

    def cb_cancel(self, view, item):
        if self.icon is not None:
            sess = self.icon._session
            if sess is not None:
                sess.cancelled = True
                sess.interrupt = True
            return None
        if self.session is not None:
            self.session.cancelled = True
            self.session.interrupt = True
        return True

    def cb_quit(self, view, item):
        if self.icon is not None:
            return self._tray_quit()
        sys.exit(0)

    def cb_set_model(self, backend_name: str, model_id: str) -> Callable:
        """Factory: return a callback that switches to (backend, model)."""
        def _cb(view, item):
            if self.icon is not None:
                return self._tray_set_model(backend_name, model_id)
            self.transcriber = None
            self.session = None
            self.o.backend = backend_name
            self.o.model = model_id
            return False
        return _cb

    # ── Tray-mode helpers ──────────────────────────────────────────
    def _tray_join_recording_threads(self) -> None:
        icon = self.icon
        if icon is None:
            return
        thread = getattr(icon, "_recording_thread", None)
        if thread is not None:
            thread.join()
        thread = getattr(icon, "_monitoring_thread", None)
        if thread is not None:
            thread.join()

    def _tray_record(self):
        """Start a recording thread on the bound icon (play/stop toggle).

        Preserves the SIGUSR1 toggle semantics from the previous closure
        implementation: invoking this while a recording is in flight signals
        the running session to stop instead of starting a fresh one.
        """
        import threading
        from scribe.app import start_recording

        icon = self.icon
        session = icon._session
        if session.busy:
            session.interrupt = True
            return None

        thread = getattr(icon, "_recording_thread", None)
        if thread is not None and thread.is_alive():
            thread.join()
        thread = getattr(icon, "_monitoring_thread", None)
        if thread is not None and thread.is_alive():
            thread.join()

        # Pre-mark busy to avoid a race with the monitoring thread.
        session.busy = True

        o = self.o

        def _safe_start():
            try:
                start_recording(
                    self.micro, session,
                    clipboard=getattr(o, "clipboard", False),
                    keyboard=getattr(o, "keyboard", False),
                    auto_paste=getattr(o, "auto_paste", False),
                    latency=getattr(o, "latency", 0),
                    ascii=getattr(o, "ascii", False),
                    output_file=getattr(o, "output_file", None),
                    start_message="Listening... Use the tray icon menu to stop.",
                )
            except Exception as exc:
                session.notify_error("Recording error", repr(exc))
            finally:
                session.recording = False
                session.busy = False

        icon._recording_thread = threading.Thread(target=_safe_start)
        icon._recording_thread.start()
        icon._monitoring_thread = threading.Thread(
            target=icon._state_machine.start_monitoring,
            args=(lambda: icon._session.busy,),
        )
        icon._monitoring_thread.start()
        return None

    def _tray_quit(self):
        from desktop_ai_core.frontends.tray import remove_pidfile

        icon = self.icon
        icon.visible = False
        if icon._session is not None:
            icon._session.interrupt = True
        self._tray_join_recording_threads()
        remove_pidfile("scribe")
        icon.stop()
        return None

    def _tray_set_model(self, backend_name: str, model_id: str):
        import threading
        from scribe.app import get_transcriber
        from scribe.session import RecordingSession
        from desktop_ai_core.frontends.dialog import show_error_dialog

        icon = self.icon
        current = icon._transcriber
        if (current is not None
                and getattr(current, "backend", None) == backend_name
                and getattr(current, "model_name", None) == model_id):
            icon._session.log(f"Already using model {model_id}")
            return None

        if icon._session is not None and icon._session.busy:
            icon._session.interrupt = True
        self._tray_join_recording_threads()

        new_kwargs = {**vars(self.o), "backend": backend_name, "model": model_id, "prompt": False}

        # Construction can block on model-weight downloads (faster-whisper)
        # or other I/O. Run on a background thread so the tray stays
        # responsive; the busy icon flags activity to the user.
        def _swap():
            new_transcriber = None
            try:
                new_transcriber = get_transcriber(**new_kwargs)
            except Exception as exc:
                self.logger.error(f"Failed to load {backend_name}/{model_id}: {exc}")
                show_error_dialog(
                    "Model load failed",
                    f"{backend_name}/{model_id}: {type(exc).__name__}: {exc}",
                )
            icon._loading = False
            if new_transcriber is None:
                icon.update_menu()
                return
            icon._transcriber = new_transcriber
            icon._session = RecordingSession(backend=new_transcriber, error_callback=show_error_dialog)
            icon.title = f"scribe — {format_model_label(new_transcriber.backend, new_transcriber.model_name)}"
            icon._model_selection = False
            self.transcriber = new_transcriber
            self.session = icon._session
            self.o.backend = backend_name
            self.o.model = model_id
            icon.update_menu()

        icon._loading = True
        icon.update_menu()
        threading.Thread(target=_swap, daemon=True, name="scribe-model-swap").start()
        return None

    def _refresh_tray_menu(self):
        if self.icon is not None:
            try:
                self.icon.update_menu()
            except Exception:
                pass

    # ── Option-toggle callbacks ────────────────────────────────────
    def cb_toggle_clipboard(self, view, item):
        self.o.clipboard = not self.o.clipboard
        self.params["clipboard"] = self.o.clipboard
        self._refresh_tray_menu()
        return True

    def cb_toggle_keyboard(self, view, item):
        self.o.keyboard = not bool(self.o.keyboard)
        self.params["keyboard"] = self.o.keyboard
        self._refresh_tray_menu()
        return True

    def cb_toggle_frontend(self, view, item):
        self.o.frontend = "terminal" if self.o.frontend == "tray" else "tray"
        self.params["frontend"] = self.o.frontend
        self._refresh_tray_menu()
        return True

    def cb_toggle_auto_restart(self, view, item):
        new = not bool(getattr(self.transcriber, "restart_after_silence", False))
        if self.transcriber is not None:
            self.transcriber.restart_after_silence = new
        self.o.restart_after_silence = new
        self.params["restart_after_silence"] = new
        self._refresh_tray_menu()
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
    items = []
    for model in _models_for_backend(backend_name, app_state):
        def _is_current(_item, _b=backend_name, _m=model):
            t = app_state.transcriber
            return (t is not None
                    and getattr(t, "backend", None) == _b
                    and getattr(t, "model_name", None) == _m)
        item = Item(
            format_model_label(backend_name, model, include_vendor=False),
            app_state.cb_set_model(backend_name, model),
            checked=_is_current,
        )
        item.radio = True
        items.append(item)
    vendor = _VENDOR_PREFIX.get(backend_name, backend_name.capitalize())
    return Menu(items, name=vendor)


def _is_terminal_frontend(app_state):
    def _predicate(_item=None):
        return app_state.icon is None
    return _predicate


def _vendor_label_fn(app_state, backend_name: str, base_label: str):
    """Return a label callable that prefixes ✓ when this vendor is active."""
    def _label():
        t = app_state.transcriber
        active = t is not None and getattr(t, "backend", None) == backend_name
        return f"✓ {base_label}" if active else f"  {base_label}"
    return _label


_MENU_BACKEND_ORDER = ("whisper", "vosk", "openai", "groq")


def _choose_model_menu(app_state) -> Menu:
    items = []
    unavailable: list[tuple[str, str]] = []
    ordered = [b for b in _MENU_BACKEND_ORDER if b in BACKENDS] + \
              [b for b in BACKENDS if b not in _MENU_BACKEND_ORDER]
    for backend_name in ordered:
        try:
            ok, msg = probe_backend(backend_name)
        except Exception as exc:
            ok, msg = False, f"probe raised: {exc}"
        vendor = _VENDOR_PREFIX.get(backend_name, backend_name.capitalize())
        is_local = bool(getattr(BACKENDS[backend_name], "is_local", False))
        if not ok:
            unavailable.append((vendor, msg or "unavailable"))
            continue
        if backend_name == "vosk":
            base_label = f"{vendor} (local, streaming)"
        elif is_local:
            base_label = f"{vendor} (local)"
        else:
            base_label = vendor
        sub_item = Item(base_label, _backend_models_menu(app_state, backend_name))
        sub_item.label_fn = _vendor_label_fn(app_state, backend_name, base_label)
        items.append(sub_item)
    for vendor, msg in unavailable:
        item = Item(f"{vendor} — {msg}", _noop_callback)
        item.enabled = False
        items.append(item)
    return Menu(items, name="Model")


def _noop_callback(view, item):
    return None


def _toggle_options_menu(app_state) -> Menu:
    is_terminal = _is_terminal_frontend(app_state)
    items = [
        Item("c", app_state.cb_toggle_clipboard, help="Copy to clipboard",
             checked=lambda item: bool(getattr(app_state.o, "clipboard", False))),
        Item("k", app_state.cb_toggle_keyboard, help="Auto-type via keyboard",
             checked=lambda item: bool(getattr(app_state.o, "keyboard", False))),
        Item("x", app_state.cb_toggle_frontend, help="Toggle tray app mode",
             checked=lambda item: getattr(app_state.o, "frontend", None) == "tray",
             visible=is_terminal),
        Item("a", app_state.cb_toggle_auto_restart, help="Auto-restart after silence",
             checked=lambda item: bool(getattr(app_state.transcriber, "restart_after_silence", False)),
             visible=app_state._is_whisper),
        SetValueItem("t", app_state.cb_set_duration,
                     value=lambda item: getattr(app_state.transcriber, "timeout", None),
                     type=float, help="Duration (s)", visible=app_state._is_whisper),
        SetValueItem("b", app_state.cb_set_silence,
                     value=lambda item: getattr(app_state.transcriber, "silence_duration", None),
                     type=float, help="Silence break (s)", visible=app_state._is_whisper),
        SetValueItem("db", app_state.cb_set_silence_db,
                     value=lambda item: getattr(app_state.transcriber, "silence_thresh", None),
                     type=float, help="Silence threshold (db)", visible=app_state._is_whisper),
        SetValueItem("f", app_state.cb_set_output_file,
                     value=lambda item: getattr(app_state.o, "output_file", None) or "",
                     type=str, help="Output file"),
        SetValueItem("latency", app_state.cb_set_latency,
                     value=lambda item: getattr(app_state.o, "latency", None),
                     type=float, help="Keyboard latency (s)", visible=app_state._has_keyboard),
    ]
    return Menu(items, name="Options")


def build_menu(app_state) -> Menu:
    """Construct the unified scribe menu spec shared between frontends."""
    model_item = Item("Model", _choose_model_menu(app_state))
    def _model_label():
        t = app_state.transcriber
        if t is None:
            return "Model"
        if t.backend == "vosk":
            return t.model_name
        vendor = _VENDOR_PREFIX.get(t.backend, t.backend.capitalize())
        return f"{vendor} {t.model_name}"
    model_item.label_fn = _model_label
    items = [
        Item("Record", app_state.cb_record, visible=app_state.is_not_recording),
        Item("Stop", app_state.cb_stop, visible=app_state.is_recording),
        Item("Cancel", app_state.cb_cancel, visible=app_state.is_recording),
        model_item,
        Item("Options", _toggle_options_menu(app_state)),
        Item("Quit", app_state.cb_quit),
    ]
    return Menu(items)


# NOTE: pystray menus are static once built — SetValueItem entries cannot be
# inline-edited from the tray, so they render as disabled "name: value" labels
# (the user changes them via the terminal frontend or CLI flags).
def _menu_to_pystray(menu: Menu, app_state):
    """Walk a desktop_ai_core Menu tree and return a pystray.Menu mirror.

    Submenus map to nested pystray.Menu instances; Item callbacks pass through
    with (icon, menu_item) → (view, item) shape; the Record item is marked as
    pystray's default action to preserve double-click behavior.
    """
    import pystray

    py_items = [_item_to_pystray(it, app_state) for it in menu.items]
    return pystray.Menu(*py_items)


def _item_to_pystray(item, app_state):
    import pystray

    visible = _make_visible(item)

    # Tray-friendly label: `item.name` is the terminal keystroke (e.g. "c",
    # "k") while `item.help` is the human-readable description ("toggle
    # clipboard"). Prefer the latter for pystray rendering. An optional
    # `item.label_fn` callable wins over both — used for live labels like
    # "Model: <current>" that should refresh on update_menu().
    label_fn = getattr(item, "label_fn", None)
    if callable(label_fn):
        label = lambda _mi, _f=label_fn: _f()
    else:
        label = item.help or item.name

    if isinstance(item._callback, Menu):
        submenu = _menu_to_pystray(item._callback, app_state)
        return pystray.MenuItem(label, submenu, visible=visible)

    if isinstance(item, SetValueItem):
        return pystray.MenuItem(
            _make_setvalue_text(item),
            _noop_action,
            visible=visible,
            enabled=False,
        )

    checked = _make_checked(item) if item.checkable else None
    return pystray.MenuItem(
        label,
        _make_action(item),
        checked=checked,
        radio=getattr(item, "radio", False),
        default=(item.name == "Record"),
        visible=visible,
        enabled=getattr(item, "enabled", True),
    )


def _make_visible(item):
    def _visible(_mi):
        if not bool(item.visible(item)):
            return False
        if isinstance(item, SetValueItem):
            val = item.value(item) if callable(item.value) else item.value
            if val in (None, ""):
                return False
        return True
    return _visible


def _make_checked(item):
    def _checked(_mi):
        return bool(item.checked(item))
    return _checked


def _make_action(item):
    callback = item._callback
    def _action(icon, _mi):
        return callback(icon, item)
    return _action


def _make_setvalue_text(item):
    label = item.help or item.name
    def _text(_mi):
        val = item.value(item) if callable(item.value) else item.value
        return f"{label}: {val}"
    return _text


def _noop_action(_icon, _mi):
    return None
