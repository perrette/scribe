import math
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
    "whisper-futo": "Whisper (FUTO)",
    "vosk": "Vosk",
}


def _model_supports_streaming(backend_name: str, model_id: str) -> bool:
    """Return True if (backend, model) maps to a streaming transcriber.

    Two signals: a class-level `supports_streaming` on the registered backend
    (e.g. Vosk), or a model that the registered class dispatches to a
    streaming sibling for (e.g. openai → gpt-realtime-whisper)."""
    backend_cls = BACKENDS.get(backend_name)
    if backend_cls is not None and bool(getattr(backend_cls, "supports_streaming", False)):
        return True
    if backend_name == "openai":
        from scribe.backends.openai_api import REALTIME_MODELS
        return model_id in REALTIME_MODELS
    return False


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
    supports_streaming = _model_supports_streaming(backend_name, model_id)

    if backend_name == "vosk":
        lang = _vosk_language_for_model(model_id)
        display = lang if lang is not None else model_id
        if include_vendor:
            return f"{vendor} {display} (local, streaming)"
        return display

    streaming_suffix = " (streaming)" if supports_streaming else ""
    qualifier = " (local)" if (is_local and include_vendor) else ""

    if include_vendor:
        return f"{vendor} {model_id}{qualifier}{streaming_suffix}"
    return f"{model_id}{qualifier}{streaming_suffix}"


_DEFAULT_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-4o-transcribe", "gpt-4o-mini-transcribe", "gpt-realtime-whisper"],
    "groq": ["whisper-large-v3-turbo"],
    "whisper": ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"],
    "whisper-futo": ["tiny", "base", "small"],
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
    if backend_name == "whisper-futo":
        models = getattr(o, "whisper_futo_models", None) if o is not None else None
        return list(models) if models else list(_DEFAULT_MODELS["whisper-futo"])
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

    def _is_batch_backend(self, item=None) -> bool:
        """True for backends that don't stream natively (so pseudo-streaming
        applies). Anything where supports_streaming is falsy on the class."""
        if self.transcriber is None:
            return False
        return not getattr(type(self.transcriber), "supports_streaming", False)

    def _is_realtime(self, item=None) -> bool:
        """True for the OpenAI realtime backend (has the silence gate)."""
        return self.transcriber is not None and hasattr(self.transcriber, "_gate_enabled")

    def _is_mode_stream(self, item=None) -> bool:
        """Mode=Stream: native streaming backend OR pseudo-streaming is on."""
        t = self.transcriber
        if t is None:
            return bool(getattr(self.o, "pseudo_streaming", False))
        return (bool(getattr(type(t), "supports_streaming", False))
                or bool(getattr(t, "pseudo_streaming", False)))

    def _is_mode_clip(self, item=None) -> bool:
        return not self._is_mode_stream()

    def _is_stream_batch(self, item=None) -> bool:
        return self._is_mode_stream() and self._is_batch_backend()

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

    def cb_set_language(self, language: str | None) -> Callable:
        """Factory: return a callback that switches the recognition language.

        For backends where the language picks the model (vosk) or substitutes a
        specialist variant (whisper / whisper-futo with .en) this triggers the
        same background model-swap as cb_set_model. For backends that take
        language as a per-call parameter (openai, groq, multilingual whisper)
        the live transcriber's `language` attribute is updated in place.
        """
        def _cb(view, item):
            if self.icon is not None:
                return self._tray_set_language(language)
            self.o.language = language
            # In terminal mode the model is re-derived on the next loop pass
            # via pick_specialist_model in get_transcriber, so force a rebuild.
            self.transcriber = None
            self.session = None
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
                    mode=getattr(o, "mode", "keystroke"),
                    typer=getattr(o, "typer", "auto"),
                    output_file=getattr(o, "output_file", None),
                    type_direct=getattr(o, "type_direct", False),
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

    def _tray_set_language(self, language: str | None):
        """Tray-mode language switch. Mirrors _tray_set_model's reload path
        when the model name changes (vosk per-language model, or whisper /
        whisper-futo .en substitution); otherwise patches the live
        transcriber and refreshes the menu."""
        current = self.transcriber
        if current is None:
            self.o.language = language
            self._refresh_tray_menu()
            return None
        backend = current.backend
        current_model = current.model_name
        new_model = current_model

        if backend == "vosk":
            if language is None:
                return None  # vosk has no auto-detect
            toml_path = Path(__file__).parent / "models.toml"
            with open(toml_path, "rb") as f:
                cfg = tomllib.load(f)
            entry = cfg.get("vosk", {}).get(language)
            if not entry or "model" not in entry:
                self.notify_error("Language unavailable",
                                  f"No vosk model mapped for {language!r}")
                return None
            new_model = entry["model"]
        else:
            from scribe.app import pick_specialist_model
            # Strip any `.en` suffix first so switching English → French
            # collapses `small.en` back to the multilingual `small`.
            base_model = current_model[:-3] if current_model.endswith(".en") else current_model
            new_model = pick_specialist_model(base_model, language, backend)

        self.o.language = language

        if new_model != current_model:
            return self._tray_set_model(backend, new_model)

        # Same model — just patch the language on the live transcriber.
        try:
            self.transcriber.language = language
        except AttributeError:
            pass
        self._refresh_tray_menu()
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

        new_kwargs = {**vars(self.o), "backend": backend_name, "model": model_id, "interactive": False}

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

    # ── Option callbacks ────────────────────────────────────────────
    def cb_set_output_mode(self, mode: str) -> Callable:
        """Factory: callback that sets the single 'Keyboard mode' radio.

        ``mode`` ∈ {'keystroke', 'clipboard', 'terminal'} — mirrors the
        ``--mode`` CLI flag. ``start_recording`` derives the actual
        mechanism (paste-per-chunk on streaming backends vs single Ctrl+V
        on batch backends) from this and the active backend at recording
        time, so switching backends via the Model menu re-evaluates
        correctly without us having to refresh stored state.
        """
        def _cb(view, item):
            self.o.mode = mode
            self.params["mode"] = mode
            self._refresh_tray_menu()
            return True
        return _cb

    def cb_toggle_frontend(self, view, item):
        self.o.frontend = "terminal" if self.o.frontend == "tray" else "tray"
        self.params["frontend"] = self.o.frontend
        self._refresh_tray_menu()
        return True

    def cb_set_mode(self, stream: bool) -> Callable:
        """Factory: callback for the Mode submenu's Stream/Clip radio items.

        `stream=True` sets pseudo_streaming on; `stream=False` sets it off.
        On native streamers (supports_streaming=True) both radios no-op —
        those backends are always Stream and the Clip radio is hidden
        anyway, so this only fires if someone clicks the (already-checked)
        Stream radio.
        """
        def _cb(view, item):
            if not self._is_batch_backend():
                return True
            if self.transcriber is not None:
                self.transcriber.pseudo_streaming = stream
            self.o.pseudo_streaming = stream
            self.params["pseudo_streaming"] = stream
            self._refresh_tray_menu()
            return True
        return _cb

    def cb_toggle_realtime_gate(self, view, item):
        new = not bool(getattr(self.transcriber, "_gate_enabled", True))
        if self.transcriber is not None and hasattr(self.transcriber, "_gate_enabled"):
            self.transcriber._gate_enabled = new
        self.o.realtime_gate = new
        self.params["realtime_gate"] = new
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

    def cb_set_silence_duration(self, view, item):
        val = self._coerce_float(item.value(item), "duration")
        if val is not None:
            self.o.silence_duration = val
            if self.transcriber is not None:
                self.transcriber.silence_duration = val
        return True

    def cb_set_silence_db(self, view, item):
        val = self._coerce_float(item.value(item), "threshold")
        if val is not None:
            self.o.silence_db = val
            if self.transcriber is not None:
                self.transcriber.silence_thresh = val
                self.transcriber._invalidate_silence_gate()
        return True

    def cb_toggle_vad_mode(self, view, item):
        # Two-state toggle between "db" and "silero". Tries to instantiate
        # the new gate immediately so the user sees the import error here,
        # not at first audio frame; reverts on failure.
        cur = getattr(self.transcriber, "vad_mode", "db") if self.transcriber else self.o.vad_mode
        new = "silero" if cur == "db" else "db"
        if self.transcriber is not None:
            old = self.transcriber.vad_mode
            self.transcriber.vad_mode = new
            self.transcriber._invalidate_silence_gate()
            try:
                self.transcriber.silence_gate  # forces construction
            except ImportError as exc:
                self.transcriber.vad_mode = old
                self.transcriber._invalidate_silence_gate()
                print(f"[VAD] Cannot switch to silero: {exc}")
                return True
        self.o.vad_mode = new
        self._refresh_tray_menu()
        return True

    def cb_set_vad_threshold(self, view, item):
        val = self._coerce_float(item.value(item), "threshold")
        if val is not None:
            self.o.vad_threshold = val
            if self.transcriber is not None:
                self.transcriber.vad_threshold = val
                self.transcriber._invalidate_silence_gate()
        return True

    def cb_set_vad_min_silence_ms(self, view, item):
        # Reuse the float coercer then snap to int — VADIterator wants int ms.
        val = self._coerce_float(item.value(item), "duration (ms)")
        if val is not None:
            self.o.vad_min_silence_ms = int(val)
            if self.transcriber is not None:
                self.transcriber.vad_min_silence_ms = int(val)
                self.transcriber._invalidate_silence_gate()
        return True

    def _set_stream_attr(self, attr: str, value) -> None:
        setattr(self.o, attr, value)
        self.params[attr] = value
        if self.transcriber is not None:
            setattr(self.transcriber, attr, value)
        self._refresh_tray_menu()

    def cb_set_stream_chunk_min(self, value) -> Callable:
        def _cb(view, item):
            self._set_stream_attr("stream_chunk_min", value)
            return True
        return _cb

    def cb_set_stream_chunk_max(self, value) -> Callable:
        def _cb(view, item):
            self._set_stream_attr("stream_chunk_max", value)
            return True
        return _cb

    def cb_set_stream_chunk_silence_break(self, value) -> Callable:
        def _cb(view, item):
            self._set_stream_attr("stream_chunk_silence_break", value)
            return True
        return _cb

    def cb_set_stream_context_reset_silence(self, value) -> Callable:
        def _cb(view, item):
            self._set_stream_attr("stream_context_reset_silence", value)
            return True
        return _cb

    def cb_set_realtime_timeout(self, value) -> Callable:
        """Mode=Stream auto-stop timeout. Writes to o.realtime_timeout and, if
        a Stream-mode session is currently armed, updates the live timeout."""
        def _cb(view, item):
            self.o.realtime_timeout = value
            self.params["realtime_timeout"] = value
            if self.transcriber is not None and self._is_mode_stream():
                self.transcriber.timeout = value
            self._refresh_tray_menu()
            return True
        return _cb

    def cb_set_clip_timeout(self, value) -> Callable:
        def _cb(view, item):
            self.o.clip_timeout = value
            self.params["clip_timeout"] = value
            if self.transcriber is not None and self._is_mode_clip():
                self.transcriber.timeout = value
            self._refresh_tray_menu()
            return True
        return _cb

    def cb_set_realtime_stream_mode(self, value) -> Callable:
        """value=None → Live (gate off, commit-silence=0); value=float → Offline."""
        def _cb(view, item):
            gate = value is not None
            commit_silence = 0.0 if value is None else value
            self.o.realtime_gate = gate
            self.params["realtime_gate"] = gate
            self.o.realtime_commit_silence = commit_silence
            self.params["realtime_commit_silence"] = commit_silence
            if self.transcriber is not None and hasattr(self.transcriber, "_gate_enabled"):
                self.transcriber._gate_enabled = gate
                self.transcriber.realtime_commit_silence = commit_silence
            self._refresh_tray_menu()
            return True
        return _cb

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

    def cb_set_typer(self, typer_name: str) -> Callable:
        """Factory: return a callback that sets the active typer backend."""
        def _cb(view, item):
            self.o.typer = typer_name
            self.params["typer"] = typer_name
            self._refresh_tray_menu()
            return True
        return _cb

    def cb_toggle_type_direct(self, view, item):
        new = not bool(getattr(self.o, "type_direct", False))
        self.o.type_direct = new
        self.params["type_direct"] = new
        self._refresh_tray_menu()
        return True

    def current_model_label(self) -> str:
        if self.transcriber is None:
            return ""
        return format_model_label(self.transcriber.backend, self.transcriber.model_name)


_RECOMMENDED_MODELS = {
    "whisper": "small",
    "whisper-futo": "small",
}


# Curated languages surfaced in the Language submenu. The set matches the
# vosk-pre-mapped languages in models.toml so the same labels work for every
# backend; display names come from `_meta.<lang>.language` when present.
_CURATED_LANGUAGES = ["en", "fr", "de", "it"]

_LANGUAGE_DISPLAY_FALLBACK = {
    "en": "English",
    "fr": "French",
    "de": "German",
    "it": "Italian",
}


def _language_display(lang_code: str | None) -> str:
    if lang_code is None:
        return "Auto"
    toml_path = Path(__file__).parent / "models.toml"
    try:
        with open(toml_path, "rb") as f:
            cfg = tomllib.load(f)
        name = cfg.get("_meta", {}).get(lang_code, {}).get("language")
        if name:
            return name
    except Exception:
        pass
    return _LANGUAGE_DISPLAY_FALLBACK.get(lang_code, lang_code)


def _languages_for_backend(backend_name: str) -> list[str | None]:
    """Curated language list, filtered by what the active backend can handle.

    Vosk requires a per-language model (no auto-detect) and only the languages
    pre-mapped in models.toml are exposed. Everything else accepts Auto + the
    full curated set."""
    if backend_name == "vosk":
        toml_path = Path(__file__).parent / "models.toml"
        try:
            with open(toml_path, "rb") as f:
                cfg = tomllib.load(f)
            return [lang for lang in _CURATED_LANGUAGES if lang in cfg.get("vosk", {})]
        except Exception:
            return list(_CURATED_LANGUAGES)
    return [None] + list(_CURATED_LANGUAGES)


def _backend_models_menu(app_state, backend_name: str) -> Menu:
    items = []
    recommended = _RECOMMENDED_MODELS.get(backend_name)
    for model in _models_for_backend(backend_name, app_state):
        def _is_current(_item, _b=backend_name, _m=model):
            t = app_state.transcriber
            return (t is not None
                    and getattr(t, "backend", None) == _b
                    and getattr(t, "model_name", None) == _m)
        label = format_model_label(backend_name, model, include_vendor=False)
        if model == recommended:
            label = f"{label} (recommended)"
        item = Item(
            label,
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


def _active_backend_name(app_state) -> str | None:
    t = app_state.transcriber
    if t is not None and getattr(t, "backend", None):
        return t.backend
    return getattr(getattr(app_state, "o", None), "backend", None)


def _language_menu(app_state) -> Menu:
    """Radio submenu of curated languages. Items not supported by the current
    backend (e.g. Auto on vosk) hide themselves via the visible predicate, so
    one Menu object covers every backend without rebuilding on switch."""
    items: list[Item] = []
    # Build entries for the union of all curated languages + Auto; per-item
    # visibility predicates filter at render time based on the active backend.
    for lang in [None] + list(_CURATED_LANGUAGES):
        label = _language_display(lang)

        def _is_current(_item, _l=lang):
            return getattr(app_state.o, "language", None) == _l

        def _is_visible(_item, _l=lang):
            backend = _active_backend_name(app_state)
            if backend is None:
                return True
            return _l in _languages_for_backend(backend)

        item = Item(label, app_state.cb_set_language(lang),
                    checked=_is_current, visible=_is_visible)
        item.radio = True
        items.append(item)
    return Menu(items, name="Language")


def _vendor_label_fn(app_state, backend_name: str, base_label: str):
    """Return a label callable that prefixes ✓ when this vendor is active."""
    def _label():
        t = app_state.transcriber
        active = t is not None and getattr(t, "backend", None) == backend_name
        return f"✓ {base_label}" if active else f"  {base_label}"
    return _label


_MENU_BACKEND_ORDER = ("whisper-futo", "whisper", "vosk", "openai", "groq")


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


def _output_mode(o) -> str:
    """Return the active Keyboard-mode radio value, stored as ``o.mode``."""
    return getattr(o, "mode", "keystroke")


def _output_mode_radio(app_state, key: str, mode: str, label: str) -> Item:
    def _is_current(_item, _m=mode):
        return _output_mode(app_state.o) == _m
    item = Item(key, app_state.cb_set_output_mode(mode), help=label, checked=_is_current)
    item.radio = True
    return item


def _output_mode_submenu(app_state) -> Menu:
    """Mutually-exclusive output modes, grouped as a radio submenu.

    Three modes — the underlying mechanism (paste-per-chunk live vs
    Ctrl+V at end of recording) is picked automatically for the current
    backend, so the user sees only 'where does the text go'.
    """
    modes = [
        ("c", "clipboard", "Clipboard only (press Ctrl+V yourself)"),
        ("s", "keystroke", "Send to focused window (recommended)"),
        ("t", "terminal",  "Terminal only"),
    ]
    items = []
    for key, mode, label in modes:
        items.append(_output_mode_radio(app_state, key, mode, label))
    return Menu(items, name="Keyboard mode")


_TYPER_ORDER = ("eitype", "pynput", "ydotool", "wtype")


def _compatible_typers() -> list[tuple[str, object]]:
    """Return [(name, instance), …] for typers that could in principle run on
    this OS / session. Filters out structurally-impossible backends (wtype on
    GNOME, ydotool on macOS, etc.). Order follows ``_TYPER_ORDER``."""
    from scribe.typers import TYPERS

    ordered = [n for n in _TYPER_ORDER if n in TYPERS] + \
              [n for n in TYPERS if n not in _TYPER_ORDER]
    compatible = []
    for name in ordered:
        try:
            instance = TYPERS[name]()
        except Exception:
            continue
        try:
            ok = instance.compatible() if hasattr(instance, "compatible") else True
        except Exception:
            ok = False
        if ok:
            compatible.append((name, instance))
    return compatible


def _typer_menu(app_state) -> Menu:
    """Radio submenu listing the keystroke-injection backends compatible with
    the current OS. Incompatible backends are hidden entirely; compatible-but-
    unset-up backends are shown disabled with a hint. 'Auto' is resolved at
    startup in scribe.app.main, so ``o.typer`` is already a concrete name.

    Also exposes a ``Type directly`` checkbox: when on, keystroke mode types
    the transcription raw instead of synthesising Ctrl+V — needed in terminals
    where Ctrl+V is the ^V control character."""
    items = []
    for name, instance in _compatible_typers():
        try:
            available = instance.available()
        except Exception:
            available = False
        try:
            caveat = instance.caveat() if hasattr(instance, "caveat") else None
        except Exception:
            caveat = None
        if not available:
            label = f"{name} — not set up"
        elif caveat:
            label = f"{name} ({caveat})"
        else:
            label = name

        def _is_current(_item, _n=name):
            return getattr(app_state.o, "typer", None) == _n

        item = Item(label, app_state.cb_set_typer(name), checked=_is_current)
        item.radio = True
        item.enabled = available
        items.append(item)

    items.append(Item(
        "type-direct",
        app_state.cb_toggle_type_direct,
        help="Type directly (no Ctrl+V)",
        checked=lambda item: bool(getattr(app_state.o, "type_direct", False)),
    ))

    return Menu(items, name="Keyboard backend")


def _format_seconds(value) -> str:
    """Compact seconds label: '1.5s', '2 min', '1 h'."""
    if value >= 3600 and value % 3600 == 0:
        hours = int(value // 3600)
        return f"{hours} h"
    if value >= 60 and value % 60 == 0:
        return f"{int(value // 60)} min"
    return f"{value:g}s"


def _chunk_min_label(v) -> str:
    return f"{v:g}s"


def _chunk_max_label(v) -> str:
    return "Unlimited" if v is None else f"{v:g}s"


def _silence_break_label(v) -> str:
    if v is None:
        return "Max"
    if v == 0:
        return "Auto"
    return f"{v:g}s"


def _context_reset_label(v) -> str:
    if isinstance(v, float) and math.isinf(v):
        return "Never"
    return f"{v:g}× silence"


def _timeout_label(v) -> str:
    if v is None:
        return "Always On"
    return _format_seconds(v)


def _realtime_stream_label(v) -> str:
    """None → 'Live'; float → 'Offline after Xs'."""
    if v is None:
        return "Live"
    return f"Offline after {v:g}s"


def _picker_submenu(name: str, choices: list, getter, value_to_label, cb_factory) -> Menu:
    """Radio submenu over a fixed value list.

    Each child Item is `radio=True`, marked `checked` when `getter() == choice`.
    Selecting an item runs `cb_factory(choice)` to commit the new value. The
    parent Item's label (set by the caller) shows the active selection."""
    items = []
    for v in choices:
        def _is_current(_it, _v=v):
            return getter() == _v
        item = Item(value_to_label(v), cb_factory(v), checked=_is_current)
        item.radio = True
        items.append(item)
    return Menu(items, name=name)


def _stream_advanced_submenu(app_state) -> Menu:
    """The `Stream (advanced)` submenu — visible iff Mode=Stream.

    Holds pickers for the four pseudo-streaming chunk knobs (batch backend
    only) and the Stream-mode auto-stop timeout. The OpenAI-realtime-specific
    `Stream: Live / Offline after X` picker is added by Item 9."""
    def _get_attr(name: str, default=None):
        t = app_state.transcriber
        if t is not None:
            return getattr(t, name, default)
        return getattr(app_state.o, name, default)

    def get_chunk_min(): return _get_attr("stream_chunk_min")
    def get_chunk_max(): return _get_attr("stream_chunk_max")
    def get_silence_break(): return _get_attr("stream_chunk_silence_break")
    def get_context_reset(): return _get_attr("stream_context_reset_silence")
    def get_realtime_timeout(): return getattr(app_state.o, "realtime_timeout", None)

    chunk_min_item = Item("min",
                          _picker_submenu("Chunk min",
                                          [0.1, 1.5, 3.0, 5.0, 10.0],
                                          get_chunk_min, _chunk_min_label,
                                          app_state.cb_set_stream_chunk_min),
                          visible=app_state._is_batch_backend)
    chunk_min_item.label_fn = lambda: f"Chunk min: {_chunk_min_label(get_chunk_min())}"

    chunk_max_item = Item("max",
                          _picker_submenu("Chunk max",
                                          [3.0, 5.0, 10.0, 20.0, None],
                                          get_chunk_max, _chunk_max_label,
                                          app_state.cb_set_stream_chunk_max),
                          visible=app_state._is_batch_backend)
    chunk_max_item.label_fn = lambda: f"Chunk max: {_chunk_max_label(get_chunk_max())}"

    silence_break_item = Item("silence",
                              _picker_submenu("Silence break",
                                              [0.0, 0.3, 0.6, 1.2, 2.4, None],
                                              get_silence_break, _silence_break_label,
                                              app_state.cb_set_stream_chunk_silence_break),
                              visible=app_state._is_batch_backend)
    silence_break_item.label_fn = lambda: f"Silence break: {_silence_break_label(get_silence_break())}"

    def _context_reset_parent_label():
        sb = get_silence_break()
        factor = get_context_reset()
        if sb in (None, 0):
            return "Context reset: (unavailable — silence-break is Auto/Max)"
        if isinstance(factor, float) and math.isinf(factor):
            return "Context reset: Never"
        return f"Context reset: {factor:g}× silence (= {factor * sb:g}s)"

    context_reset_item = Item("reset",
                              _picker_submenu("Context reset",
                                              [1.0, 1.5, 2.0, 3.0, math.inf],
                                              get_context_reset, _context_reset_label,
                                              app_state.cb_set_stream_context_reset_silence),
                              visible=app_state._is_batch_backend)
    context_reset_item.label_fn = _context_reset_parent_label

    realtime_timeout_item = Item("rt",
                                 _picker_submenu("Realtime timeout",
                                                 [120, 300, 600, 3600, None],
                                                 get_realtime_timeout, _timeout_label,
                                                 app_state.cb_set_realtime_timeout))
    realtime_timeout_item.label_fn = lambda: f"Realtime timeout: {_timeout_label(get_realtime_timeout())}"

    def get_realtime_stream_mode():
        t = app_state.transcriber
        if t is not None and hasattr(t, "_gate_enabled"):
            return None if not t._gate_enabled else getattr(t, "realtime_commit_silence", 0.6)
        gate = getattr(app_state.o, "realtime_gate", True)
        return None if not gate else getattr(app_state.o, "realtime_commit_silence", 0.6)

    realtime_stream_item = Item(
        "rtstream",
        _picker_submenu("Stream",
                        [None, 0.6, 1.2, 2.0, 5.0, 10.0],
                        get_realtime_stream_mode, _realtime_stream_label,
                        app_state.cb_set_realtime_stream_mode),
        visible=app_state._is_realtime)
    realtime_stream_item.label_fn = lambda: f"Stream: {_realtime_stream_label(get_realtime_stream_mode())}"

    items = [
        chunk_min_item,
        chunk_max_item,
        silence_break_item,
        context_reset_item,
        realtime_timeout_item,
        realtime_stream_item,
    ]
    return Menu(items, name="Stream (advanced)")


def _advanced_options_menu(app_state) -> Menu:
    """Backend-specific knobs + numerical tuning — kept off the main Options
    panel so it stays uncluttered for common use. Items retain their
    ``visible=`` predicates so vosk users still don't see whisper-only
    fields."""
    # The dB and silero parameter groups are intentionally separate (no
    # shared API yet — see SilenceGate docstring in scribe/audio.py).
    # `visible` on each group hides the inactive set so the user only sees
    # knobs that actually matter for the current vad_mode.
    is_db_mode = lambda: getattr(app_state.transcriber, "vad_mode", "db") == "db"
    is_silero_mode = lambda: getattr(app_state.transcriber, "vad_mode", "db") == "silero"
    items = [
        SetValueItem("t", app_state.cb_set_duration,
                     value=lambda item: getattr(app_state.transcriber, "timeout", None),
                     type=float, help="Duration (s)", visible=app_state._is_whisper),
        SetValueItem("b", app_state.cb_set_silence_duration,
                     value=lambda item: getattr(app_state.transcriber, "silence_duration", None),
                     type=float, help="Silence duration (s)"),
        Item("vad", app_state.cb_toggle_vad_mode,
             help="VAD: silero (noise-robust) instead of dB volume",
             checked=lambda item: is_silero_mode()),
        SetValueItem("db", app_state.cb_set_silence_db,
                     value=lambda item: getattr(app_state.transcriber, "silence_thresh", None),
                     type=float, help="[dB] Silence threshold (dB)",
                     visible=lambda *_: is_db_mode()),
        SetValueItem("vth", app_state.cb_set_vad_threshold,
                     value=lambda item: getattr(app_state.transcriber, "vad_threshold", None),
                     type=float, help="[silero] Speech-probability threshold (0..1)",
                     visible=lambda *_: is_silero_mode()),
        SetValueItem("vms", app_state.cb_set_vad_min_silence_ms,
                     value=lambda item: getattr(app_state.transcriber, "vad_min_silence_ms", None),
                     type=int, help="[silero] Min silence duration (ms)",
                     visible=lambda *_: is_silero_mode()),
        SetValueItem("f", app_state.cb_set_output_file,
                     value=lambda item: getattr(app_state.o, "output_file", None) or "",
                     type=str, help="Output file"),
    ]
    return Menu(items, name="Advanced")


def _toggle_options_menu(app_state) -> Menu:
    is_terminal = _is_terminal_frontend(app_state)

    stream_advanced_item = Item("stream", _stream_advanced_submenu(app_state),
                                help="Stream (advanced)",
                                visible=app_state._is_mode_stream)

    def get_clip_timeout():
        return getattr(app_state.o, "clip_timeout", None)

    clip_timeout_item = Item("clip",
                             _picker_submenu("Clip timeout",
                                             [30, 60, 120, 300, 600],
                                             get_clip_timeout, _timeout_label,
                                             app_state.cb_set_clip_timeout),
                             visible=app_state._is_mode_clip)
    clip_timeout_item.label_fn = lambda: f"Clip timeout: {_timeout_label(get_clip_timeout())}"

    items = [
        stream_advanced_item,
        clip_timeout_item,
        Item("mode", _output_mode_submenu(app_state), help="Keyboard mode"),
        Item("x", app_state.cb_toggle_frontend, help="Toggle tray app mode",
             checked=lambda item: getattr(app_state.o, "frontend", None) == "tray",
             visible=is_terminal),
        # The Keyboard backend submenu always carries the "Type directly"
        # checkbox, so it's worth showing even when only one typer is
        # compatible (macOS, Windows — pynput only). Hide only if no typer
        # is compatible at all (unlikely).
        *([Item("backend", _typer_menu(app_state), help="Keyboard backend")]
          if len(_compatible_typers()) >= 1 else []),
        Item("advanced", _advanced_options_menu(app_state), help="Advanced"),
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

    language_item = Item("Language", _language_menu(app_state))
    def _language_label():
        lang = getattr(app_state.o, "language", None)
        return f"Language: {_language_display(lang)}"
    language_item.label_fn = _language_label

    def _mode_is_stream():
        """Stream is active when native streaming OR pseudo-streaming is on
        — matches the `is_streaming` disjunction used in start_recording."""
        t = app_state.transcriber
        if t is None:
            return bool(getattr(app_state.o, "pseudo_streaming", False))
        return (bool(getattr(type(t), "supports_streaming", False))
                or bool(getattr(t, "pseudo_streaming", False)))

    def _mode_is_native_streamer():
        t = app_state.transcriber
        return t is not None and bool(getattr(type(t), "supports_streaming", False))

    def _mode_label():
        if _mode_is_native_streamer():
            return "Mode: Stream (native)"
        return "Mode: Stream" if _mode_is_stream() else "Mode: Clip"

    # Mode is a radio with 2 elements (Stream / Clip) so the top-level
    # label can show the active selection dynamically — same pattern as
    # Model and Language above. The radio modeling (not checkbox) is
    # intentional: a checkbox's checkmark + a changing label would double-
    # encode the same state.
    stream_radio = Item("r", app_state.cb_set_mode(True),
                        help="Stream (live transcription as you speak)",
                        checked=lambda _it: _mode_is_stream())
    stream_radio.radio = True
    clip_radio = Item("c", app_state.cb_set_mode(False),
                      help="Clip (transcribe at end of recording)",
                      checked=lambda _it: not _mode_is_stream(),
                      visible=app_state._is_batch_backend)
    clip_radio.radio = True
    mode_item = Item("Mode", Menu([stream_radio, clip_radio], name="Mode"))
    mode_item.label_fn = _mode_label

    items = [
        Item("Record", app_state.cb_record, visible=app_state.is_not_recording),
        Item("Stop", app_state.cb_stop, visible=app_state.is_recording),
        Item("Cancel", app_state.cb_cancel, visible=app_state.is_recording),
        mode_item,
        model_item,
        language_item,
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
