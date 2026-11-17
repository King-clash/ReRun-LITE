"""Settings > Profiles: save an emulator's Crest settings under a name and apply them again later.

See profiles.py for what a profile holds (Crest's own settings only - not the palace schedule, accounts or Discord)."""
from __future__ import annotations

from rerun.gui_common import *  # noqa: F401,F403 - tk, ios, C, F, px, errlog, filedialog, Path
from rerun.scripts import SCRIPTS

from . import __version__, channel, profiles

SCRIPT = "crest"


class ProfilesMixin:

    def _store(self) -> "profiles.ProfileStore":
        if getattr(self, "_prof_store", None) is None:
            self._prof_store = profiles.ProfileStore(channel.data_dir(self.m.root) / profiles.FILE, __version__)
        return self._prof_store

    def _build_profiles_page(self):
        _, page, hdr = self._page("Profiles", "Profiles", "settings", scroll=True)
        info = self._label(page, "A profile is a saved copy of the Crest settings (Settings > Auto Crest). It does not "
                                 "include the palace schedule, accounts or Discord.", anchor="w", justify="left")
        info.pack(fill="x", padx=px(20), pady=(0, px(8)))
        info.bind("<Configure>", lambda e: info.configure(wraplength=max(px(200), e.width - 4)))

        g = ios.Group(page, header="Use a profile")
        g.pack(fill="x", padx=px(20), pady=(0, px(12)))
        self._prof_inst = ios.Select(g.row("Emulator"), values=list(self.m.instances), accent=True)
        self._prof_inst.pack()
        if self.m.instances:
            self._prof_inst.set(next(iter(self.m.instances)))
        self._prof_pick = ios.Select(g.row("Profile"), values=[], accent=True)
        self._prof_pick.pack()
        r = g.row("Actions")
        ios.Button(r, "Apply to emulator", self._prof_apply, small=True).pack(side="left")
        ios.Button(r, "Rename…", self._prof_rename, kind="tinted", small=True).pack(side="left", padx=px(6))
        ios.Button(r, "Delete", self._prof_delete, kind="tinted", color="red", small=True).pack(side="left")

        g2 = ios.Group(page, header="Save the emulator's current settings as a new profile")
        g2.pack(fill="x", padx=px(20), pady=(0, px(12)))
        self._prof_name = tk.StringVar()
        ios.Field(g2.row("Name"), self._prof_name, width=24).pack()
        ios.Button(g2.row("Save"), "Save profile", self._prof_save, small=True).pack()

        g3 = ios.Group(page, header="Share",
                       footer="Export writes one profile to a file; Import adds a file as a new profile "
                              "(it never replaces one you already have).")
        g3.pack(fill="x", padx=px(20), pady=(0, px(12)))
        r = g3.row("Files")
        ios.Button(r, "Export…", self._prof_export, kind="tinted", small=True).pack(side="left")
        ios.Button(r, "Import…", self._prof_import, kind="tinted", small=True).pack(side="left", padx=px(6))
        self._prof_msg = self._label(page, "", anchor="w", justify="left")
        self._prof_msg.pack(fill="x", padx=px(20), pady=(0, px(16)))
        self._prof_msg.bind("<Configure>", lambda e: self._prof_msg.configure(wraplength=max(px(200), e.width - 4)))
        self._prof_refresh()

    # ---------------------------------------------------------------- helpers
    def _prof_say(self, text: str, kind: str = "info"):
        color = {"ok": C["green"], "err": C["red"], "warn": C["orange"]}.get(kind, C["secondary"])
        self._prof_msg.configure(text=text, fg=color)

    def _prof_refresh(self, select: str | None = None):
        store = self._store()
        store.load()
        self._prof_inst["values"] = list(self.m.instances)
        names = store.names()
        self._prof_pick["values"] = names
        if select in names:
            self._prof_pick.set(select)
        elif self._prof_pick.get() not in names:
            self._prof_pick.set(names[0] if names else "")
        if store.read_only:
            self._prof_say(store.read_only, "warn")

    def _prof_spec(self):
        return SCRIPTS[SCRIPT].SETTINGS

    def _prof_idle(self, inst: str) -> bool:
        i = self.m.instances.get(inst)
        return i is not None and i.status in ("idle", "error")

    # ---------------------------------------------------------------- actions
    def _prof_save(self):
        inst = self._prof_inst.get()
        if inst not in self.m.instances:
            return self._prof_say("Pick an emulator first.", "err")
        try:
            name = self._store().save(self._prof_name.get(), self.m.script_settings(inst, SCRIPT), self._prof_spec())
        except profiles.ProfileError as e:
            return self._prof_say(str(e), "err")
        self._prof_name.set("")
        self._prof_refresh(name)
        self._prof_say(f"Saved '{name}' from {inst}.", "ok")

    def _prof_apply(self):
        inst, name = self._prof_inst.get(), self._prof_pick.get()
        store = self._store()
        if inst not in self.m.instances or name not in store.profiles:
            return self._prof_say("Pick an emulator and a profile.", "err")
        if not self._prof_idle(inst):
            return self._prof_say(f"{inst} is running. Stop it first so the settings are not changed under it.", "err")
        spec = self._prof_spec()
        clean, problems = profiles.validate(store.profiles[name]["values"], spec)
        current = self.m.script_settings(inst, SCRIPT)
        changes = profiles.diff(current, clean, spec)
        if not changes:
            return self._prof_say(f"'{name}' matches {inst}'s settings already: nothing to change."
                                  + (f" ({len(problems)} value(s) in it are no longer valid.)" if problems else ""), "ok")
        lines = [f"{label}: {old!r} -> {new!r}" for label, old, new in changes[:12]]
        if len(changes) > 12:
            lines.append(f"... and {len(changes) - 12} more")
        if not ios.confirm(self, f"Apply '{name}' to {inst}? These settings will change:\n\n" + "\n".join(lines),
                           "Apply profile?", ok="Apply"):
            return None
        self.m.save_script_settings(inst, SCRIPT, {**current, **clean})
        try:
            self._load_settings_form()
        except Exception as e:  # noqa: BLE001 - the open form is refreshed when you next open it
            errlog.note("lite.profiles_form", e)
        note = f" Skipped: {'; '.join(problems[:3])}." if problems else ""
        self._prof_say(f"Applied '{name}' to {inst}: {len(changes)} setting(s) changed.{note}", "warn" if problems else "ok")
        return None

    def _prof_delete(self):
        name = self._prof_pick.get()
        if name in self._store().profiles and ios.confirm(self, f"Delete the profile '{name}'?", "Delete profile?",
                                                           ok="Delete", destructive=True):
            try:
                self._store().delete(name)
            except profiles.ProfileError as e:
                return self._prof_say(str(e), "err")
            self._prof_refresh()
            self._prof_say(f"Deleted '{name}'.", "ok")
        return None

    def _prof_rename(self):
        name = self._prof_pick.get()
        new = self._prof_name.get()
        if name not in self._store().profiles:
            return self._prof_say("Pick a profile to rename.", "err")
        if not new.strip():
            return self._prof_say("Type the new name in the Name box under 'Save', then press Rename.", "err")
        try:
            final = self._store().rename(name, new)
        except profiles.ProfileError as e:
            return self._prof_say(str(e), "err")
        self._prof_name.set("")
        self._prof_refresh(final)
        self._prof_say(f"Renamed to '{final}'.", "ok")
        return None

    def _prof_export(self):
        name = self._prof_pick.get()
        if name not in self._store().profiles:
            return self._prof_say("Pick a profile to export.", "err")
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile=f"{name}.rerun-profile.json")
        if path:
            Path(path).write_text(self._store().export_text(name), encoding="utf-8")
            self._prof_say(f"Exported '{name}'.", "ok")
        return None

    def _prof_import(self):
        path = filedialog.askopenfilename(filetypes=[("Profile", "*.json"), ("All files", "*.*")])
        if not path:
            return None
        try:
            name, problems = self._store().import_text(Path(path).read_text(encoding="utf-8"), self._prof_spec())
        except (profiles.ProfileError, OSError) as e:
            return self._prof_say(str(e), "err")
        self._prof_refresh(name)
        self._prof_say(f"Imported as '{name}'." + (f" {len(problems)} value(s) were skipped as not valid." if problems else ""),
                       "warn" if problems else "ok")
        return None
