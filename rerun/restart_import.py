"""Import game-UI templates from your local ReStart install.

ReStart unpacks itself to %LOCALAPPDATA%\\ReStart, with its template images in
templates/<area>/<name>.png, cropped from 720x1280 portrait frames - the same
frame Rerun sees. This copies the ones Rerun's scripts use, under Rerun's names.
Templates you captured yourself are never overwritten unless you ask.
"""
from __future__ import annotations

import os
from pathlib import Path

from .vision import TemplateStore

RESTART_FRAME = (720, 1280)

# Rerun template name -> ReStart path (relative to its templates/ folder)
MAPPING: dict[str, str] = {
    # Auto-Loop flow (Any Quest + Crest)
    "solo_quest_button": "default/solo_quest_button.png",
    "challenge_button": "story/challenge.png",
    "past_party_button": "default/past_party_button.png",
    "include_ai_button": "default/include_ai_button.png",
    "apply_button": "default/apply_button.png",
    "auto_button": "training/7auto_button.png",
    "battle_button": "training/6battle_button.png",
    "use_potions_button": "training/9use_potions_button.png",
    "looping_button": "training/8looping_button.png",
    "drop_info": "default/drop_info.png",
    "results_redeploy": "crest/results_redeploy.png",
    "ok_button": "training/10ok_button.png",
    "use_pot_button": "training/11use_pot.png",
    "continue_box": "crest/continue_box.png",
    "cancel_btn": "crest/cancel_btn.png",
    "restart_btn": "crest/restart_btn.png",
    "small_next_button": "default/small_next_button.png",
    # Crest
    "crest_icon_lv5plus": "crest/crest_icon_lv5plus.png",
    "equip_crest_screen": "crest/equip_crest_screen.png",
    "crest_checkbox": "crest/crest_checkbox.png",
    "crest_icon_lv3": "crest/crest_icon_lv3.png",
    "crest_icon_lv3plus": "crest/crest_icon_lv3plus.png",
    "crest_icon_lv4": "crest/crest_icon_lv4.png",
    "crest_icon_lv4plus": "crest/crest_icon_lv4plus.png",
    "redeploy_button": "crest/redeploy_button.png",
    "select_crest_ok": "crest/select_crest_ok.png",
    "select_crest_ok2": "crest/select_crest_ok2.png",
    "crest_fragment": "crest/crest_fragment.png",
    "crest_fragment_ok": "crest/crest_fragment_ok.png",
    "quest_list": "crest/quest_list.png",
    "exploring_button": "default/exploring_button.png",
    "crest_palace_icon": "crest/crest_palace_icon.png",
    "crest_palace_icon2": "crest/crest_palace_icon2.png",
    "crest_palace_header": "crest/crest_palace_header.png",
    # Popups / login / mail
    "unexpected_error": "arena/9unexpected_error.png",
    "xpop_up": "default/xpop_up.png",
    "summon_later_button": "login/summon_later_button.png",
    "summon_close_button": "login/summon_close_button.png",
    "total_sign_in_bonus": "login/total_sign_in_bonus.png",
    "data_download_ok": "login/data_download_ok.png",
    "data_download_prompt": "login/data_download.png",
    "game_start_screen": "login/transfer_device_button.png",
    "mail_chest": "login/mail_chest.png",
    "claim_all_button": "login/claim_all_button.png",
    "claim_all_button_dim": "login/claim_all_button_dim.png",
    "claim_ok_button": "login/claim_ok_button.png",
    "mail_close_button": "login/mail_close_button.png",
    # (unexpected_error_text is NOT imported: ReStart's copy comes from Grand
    # Crusade's popup and scores only 0.48 on the quest-screen one. Rerun ships
    # a capture from the real popup instead.)
    # Multiplayer / results
    "ready_button": "default/ready_button.png",
    "next_button": "default/next_button.png",
    "hyper_rare": "default/hyper_rare.png",
    # Arena
    "arena_home_button": "arena/1arena_home_button.png",
    "arena_find_battle": "arena/2arena_find_battle.png",
    "arena_ready": "arena/3arena_ready.png",
    "arena_battle_button": "arena/4arena_battle_button.png",
    "arena_vs_screen": "arena/5arena_vs_screen.png",
    "arena_win_fighter": "arena/6fighter_ss_win.png",
    "arena_win_master": "arena/6master_win.png",
    "arena_ok_button": "arena/7arena_ok_button.png",
    "arena_no_orbs_cancel": "arena/8no_orbs_cancel.png",
    "arena_restore_all": "arena/10restore_all.png",
    "arena_match_results": "arena/match_results.png",
    # Raids
    "raid_home": "raids/1raids_home.png",
    "raid_create": "raids/create_raid.png",
    "raid_defeated": "raids/defeated.png",
    "raid_defeat_rewards": "raids/defeat_rewards.png",
    "raid_exchange_btn": "raids/exchange_btn.png",
    "raid_exchange_btn2": "raids/exchange_btn2.png",
    "raid_expand_btn": "raids/expand_btn.png",
    "raid_friend_only_btn": "raids/friend_only_btn.png",
    "raid_green_sos": "raids/green_sos.png",
    "raid_join": "raids/join_raid.png",
    "raid_ok_btn": "raids/ok_btn.png",
    "raid_orange_ok_btn": "raids/orange_ok_btn.png",
    "raid_orange_ok_btn2": "raids/orange_ok_btn2.png",
    "raid_btn": "raids/raid_btn.png",
    "raid_ticket_btn": "raids/raid_ticket_btn.png",
    "raid_refresh_btn": "raids/refresh_btn.png",
    "raid_small_next": "raids/small_next.png",
    "raid_sos_btn": "raids/sos_btn.png",
    "raid_sos_join_btn": "raids/sos_join_btn.png",
    "raid_sos_tab": "raids/sos_tab.png",
    "raid_sos_tab2": "raids/sos_tab2.png",
    "raid_start": "raids/start_raid.png",
    "raid_ticket_ok_btn": "raids/ticket_ok_btn.png",
}

# Mines and Grand Crusade keep ReStart's file names, with an area prefix.
MINES_FILES = [
    "abandon_quest_button", "arcana_dialogue", "area_change_dialogue", "auto_advance_title",
    "auto_checked", "challenge_button", "clear_time_failed", "date_changed", "go_mining",
    "go_to_mines", "mines_close_button", "no_support_unit", "not_enough_energy",
    "omega_change_boss", "omega_dialogue", "omega_proceed", "omega_standby",
    "select_support_unit_header"]
GC_FILES = [
    "ap_standby_recover", "area_select", "auto_advance_btn", "auto_advance_btn2", "close_btn",
    "end_advance_button", "fight_btn", "fight_btn2", "game_error", "gc_icon", "gc_icon2",
    "item_cancel", "next_area_btn", "no_stamina_ok", "party_button", "party_list_back",
    "party_load_confirm", "party_load_slot", "party_ready", "results_end_advance",
    "save_load_button", "yuna_card_back", "yuna_chance", "yuna_lets_go", "yuna_regalia_pick",
    "yuna_slots_start", "yuna_slots_stop", "yuna_slots_touch",
    # GC Area navigation
    "area_list_button", "area_list_end_arrow", "area_page_first", "destination_prompt",
    "map_menu_button", "menu_areas_button"]
HELPER_FILES = [
    "back_button", "cancel_ready_button", "confirm_farm_party_join", "food_blue_cheese",
    "food_camembert", "food_emmental", "food_gorgonzola", "food_list_header", "food_red_cheese",
    "friends_filter", "full_lobby_button", "helper_reward_badge", "join_multi_button",
    "leave_lobby_ok", "lobby_back_button", "manage_parties_ready", "multiplayer_bonus",
    "ready_button", "refine_search_button", "same_as_host_button", "select_food", "update_button"]
COMPENDIUM_FILES = ["card_lv", "card_lv_rainbow", "detail_marker", "grid_header"]
for _f in HELPER_FILES:
    MAPPING["helper_" + _f.removeprefix("helper_")] = f"helper/{_f}.png"
for _f in COMPENDIUM_FILES:
    MAPPING["compendium_" + _f] = f"compendium/{_f}.png"
MAPPING["mines_button"] = "mines/mines_button.png"
for _f in MINES_FILES:
    MAPPING["mines_" + _f.removeprefix("mines_")] = f"mines/{_f}.png"
for _f in GC_FILES:
    MAPPING["gc_" + _f.removeprefix("gc_")] = f"grand_crusade/{_f}.png"


def default_restart_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "ReStart"


def find_templates_dir(base: str | Path | None = None) -> Path | None:
    """Accepts the ReStart folder or its templates folder."""
    base = Path(base) if base else default_restart_dir()
    for cand in (base / "templates", base):
        if (cand / "crest").is_dir() and (cand / "default").is_dir():
            return cand
    return None


def import_templates(store: TemplateStore, base: str | Path | None = None,
                     overwrite_own: bool = False) -> dict[str, list[str]]:
    """Copy mapped templates into `store`. Returns {'imported', 'skipped_own', 'not_found'}."""
    src_dir = find_templates_dir(base)
    if src_dir is None:
        raise FileNotFoundError(
            f"No ReStart templates folder found in {base or default_restart_dir()}. "
            "Run ReStart once so it unpacks, or pick its folder.")
    out = {"imported": [], "skipped_own": [], "not_found": []}
    for name, rel in MAPPING.items():
        src = src_dir / rel
        if not src.exists():
            out["not_found"].append(name)
            continue
        if store.has(name) and store.meta.get(name, {}).get("source") != "restart" and not overwrite_own:
            out["skipped_own"].append(name)
            continue
        store.import_file(name, src, *RESTART_FRAME, source="restart")
        out["imported"].append(name)
    # Digit glyphs for reading the Auto-Loop "Loops" counter.
    digits = src_dir / "loop_digits"
    if digits.is_dir():
        for p in sorted(digits.glob("*.png")):
            name = f"loopdigit_{p.stem}"
            if store.has(name) and store.meta.get(name, {}).get("source") != "restart" \
                    and not overwrite_own:
                out["skipped_own"].append(name)
                continue
            store.import_file(name, p, *RESTART_FRAME, source="restart")
            out["imported"].append(name)
    return out
