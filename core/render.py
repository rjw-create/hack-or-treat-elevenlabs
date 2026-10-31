"""Render stems: every paid call goes through the cache, the budget guard and the usage log.

A dry run builds the same work list and prints what each item would cost, without any API call
and without writing files.
"""
import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from core import cache, ledger
from core.config import DIALOGUE_MODEL_ID, OUTPUT_FORMAT
from core.interface import check_folder, script_lines, strip_tags
from core.plan import AMBIENCE_LENGTH_S, build_segments, scene_subset


@dataclass
class Item:
    item_id: str
    feature: str  # as logged in usage.jsonl (Proof's feature list)
    price_key: str  # which price applies; ambience beds are SFX calls with their own price
    endpoint: str
    chars: int
    params: dict
    out_file: str
    call: Callable  # call(client) -> (audio bytes, meta dict)


# The API rejects longer context (422 string_too_long on future_text, found on the first real call);
# previous_text gets the same cap to be safe.
CONTEXT_MAX_CHARS = 100


def _context(text, from_end):
    """Up to CONTEXT_MAX_CHARS of text, cut at a word boundary: the tail if from_end, else the head."""
    if len(text) <= CONTEXT_MAX_CHARS:
        return text
    if from_end:
        tail = text[-CONTEXT_MAX_CHARS:]
        return tail.split(" ", 1)[1] if " " in tail else tail
    head = text[:CONTEXT_MAX_CHARS + 1]
    return head.rsplit(" ", 1)[0] if " " in head else text[:CONTEXT_MAX_CHARS]


def _join(chunks):
    return b"".join(chunks)


def _dialogue_call(params):
    def call(client):
        r = client.text_to_dialogue.convert_with_timestamps(**params)
        # voice_segments carry dialogue_input_index, so each input line gets its own start and end.
        times = {}
        for vs in r.voice_segments or []:
            start, end = times.get(vs.dialogue_input_index, (vs.start_time_seconds, vs.end_time_seconds))
            times[vs.dialogue_input_index] = (min(start, vs.start_time_seconds), max(end, vs.end_time_seconds))
        return base64.b64decode(r.audio_base_64), {"input_times_s": {str(k): v for k, v in times.items()}}
    return call


def build_items(script, voices, plan):
    lines = {k: v[1] for k, v in script_lines(script).items()}
    voice_of = {cid: entry["voice_id"] for cid, entry in voices["voices"].items()}
    dialogue = [s for s in plan["segments"] if s["kind"] == "dialogue"]
    items = []
    for seg in plan["segments"]:
        if seg["kind"] == "dialogue":
            i = dialogue.index(seg)
            # Neighbouring text gives the model context, so small segments keep their tone.
            prev_text = " ".join(strip_tags(lines[l]["text"]) for l in dialogue[i - 1]["line_ids"]) if i else None
            next_text = (" ".join(strip_tags(lines[l]["text"]) for l in dialogue[i + 1]["line_ids"])
                         if i + 1 < len(dialogue) else None)
            inputs = [{"text": lines[l]["text"], "voice_id": voice_of[lines[l]["speaker"]]} for l in seg["line_ids"]]
            params = {"inputs": inputs, "model_id": DIALOGUE_MODEL_ID, "output_format": OUTPUT_FORMAT,
                      "previous_text": prev_text and _context(prev_text, from_end=True),
                      "future_text": next_text and _context(next_text, from_end=False)}
            params = {k: v for k, v in params.items() if v is not None}
            items.append(Item(seg["id"], "dialogue", "dialogue", "text-to-dialogue",
                              sum(len(x["text"]) for x in inputs), params, seg["file"], _dialogue_call(params)))
        else:
            params = {"text": seg["cue"], "output_format": OUTPUT_FORMAT}
            items.append(Item(seg["id"], "sfx", "sfx", "sound-generation", len(seg["cue"]), params, seg["file"],
                              lambda c, p=params: (_join(c.text_to_sound_effects.convert(**p)), {})))
    for bed in plan["beds"]:
        if bed["kind"] == "ambience":
            params = {"text": f"{bed['prompt']}, continuous background ambience", "loop": True,
                      "duration_seconds": AMBIENCE_LENGTH_S, "output_format": OUTPUT_FORMAT}
            items.append(Item(bed["id"], "sfx", "ambience", "sound-generation", len(params["text"]), params,
                              bed["file"], lambda c, p=params: (_join(c.text_to_sound_effects.convert(**p)), {})))
        else:
            # The Music API returns 402 on the free plan, so the theme is a looping musical drone
            # made with the sound-effects endpoint, logged honestly as an sfx call.
            params = {"text": f"Slow ominous orchestral string drone, Victorian horror underscore, {bed['prompt']}",
                      "loop": True, "duration_seconds": AMBIENCE_LENGTH_S, "output_format": OUTPUT_FORMAT}
            items.append(Item(bed["id"], "sfx", "ambience", "sound-generation", len(params["text"]), params,
                              bed["file"], lambda c, p=params: (_join(c.text_to_sound_effects.convert(**p)), {})))
    flat = plan.get("flat_clip")
    if flat:
        text = " ".join(strip_tags(lines[l]["text"]) for l in flat["line_ids"])
        params = {"inputs": [{"text": text, "voice_id": voice_of[flat["voice"]]}], "model_id": DIALOGUE_MODEL_ID,
                  "output_format": OUTPUT_FORMAT}
        items.append(Item("flat", "flat", "flat", "text-to-dialogue", len(text), params, flat["file"],
                          lambda c, p=params: (_join(c.text_to_dialogue.convert(**p)), {})))
    return items


RATE_LIMIT_RETRIES = 3
RATE_LIMIT_WAIT_S = 3


def _with_retry(fn, sleep=None):
    """Call fn, waiting and retrying on 429 (rate limited, seen on the first full run)."""
    import time

    sleep = sleep or time.sleep
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            return fn()
        except Exception as e:
            if getattr(e, "status_code", None) != 429 or attempt == RATE_LIMIT_RETRIES:
                raise
            sleep(RATE_LIMIT_WAIT_S * (attempt + 1))


def _balance(client):
    s = _with_retry(client.user.subscription.get, getattr(client, "sleep", None))
    return s.character_count, s.character_limit - s.character_count


BALANCE_SETTLE_TRIES = 2  # the balance can lag a call by a few seconds (seen on the first real run)


def _settled_usage(client, used_before, sleep=None):
    import time

    sleep = sleep or time.sleep
    used = used_before
    for _ in range(BALANCE_SETTLE_TRIES):
        try:
            used, _ = _balance(client)
        except Exception as e:
            if getattr(e, "status_code", None) == 429:
                return used_before  # cost stays unmeasured; the next call's balance read catches up
            raise
        if used > used_before:
            break
        sleep(1)
    return used


def run(client, script, voices, out_root, scenes=None, dry_run=False, log=print):
    """Render all items (or one preview scene set). Returns the usage rows written by this run."""
    plan = build_segments(script, scenes)
    sub_script = script if scenes is None else scene_subset(script, scenes)
    folder = out_root if scenes is None else out_root / ("preview-" + "-".join(f"s{n:02d}" for n in sorted(scenes)))
    usage_path, prices_path = out_root / "usage.jsonl", out_root / "pricing.json"
    rows, prices = ledger.read_usage(usage_path), ledger.load_prices(prices_path)
    items = build_items(script, voices, plan)

    if dry_run:
        planned, unknown = 0, 0
        for it in items:
            key = cache.cache_key(it.endpoint, it.params)
            if cache.lookup(key) is not None:
                log(f"  {it.item_id:10} {it.feature:9} cached (0 credits)")
                continue
            est, basis = ledger.estimate(it.price_key, it.chars, prices)
            if basis.startswith("unknown"):
                unknown += 1
                log(f"  {it.item_id:10} {it.feature:9} price unknown ({it.chars} chars)")
            else:
                planned += est
                log(f"  {it.item_id:10} {it.feature:9} ~{est} credits ({basis})")
        spent = ledger.credits_spent(rows)
        log(f"dry run: {len(items)} items, ~{planned} credits at known prices + {unknown} calls of unknown "
            f"price; already spent {spent}; cap {ledger.SPEND_CAP_CREDITS}")
        return []

    run_id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    times_by_segment, new_rows = {}, []
    for it in items:
        key = cache.cache_key(it.endpoint, it.params)
        hit = cache.lookup(key)
        actual = None
        if hit:
            audio, meta = hit
            est = 0
        else:
            est, _ = ledger.estimate(it.price_key, it.chars, prices)
            used_before, remaining = _balance(client)
            # The hackathon account started at 0, so its usage is the real spend; the log total
            # (estimates where a cost could not be measured) is only the fallback.
            ledger.check_budget(used_before, est, remaining)
            audio, meta = _with_retry(lambda: it.call(client), getattr(client, "sleep", None))
            used_after = _settled_usage(client, used_before, sleep=getattr(client, "sleep", None))
            actual = used_after - used_before if used_after > used_before else None
            cache.store(key, audio, meta)
            prices = ledger.record_price(prices, it.price_key, it.chars, actual)
            ledger.save_prices(prices_path, prices)
        target = folder / it.out_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(audio)
        if "input_times_s" in meta:
            times_by_segment[it.item_id] = meta["input_times_s"]
        row = {"ts": ledger.now_iso(), "run_id": run_id, "feature": it.feature, "endpoint": it.endpoint,
               "model_id": it.params.get("model_id"), "chars": it.chars, "audio_ms": None,
               "credits_estimated": est, "credits_actual": actual, "cache_hit": bool(hit),
               # Relative to the folder holding usage.jsonl, so preview stems resolve too.
               "item_id": it.item_id, "output": target.relative_to(out_root).as_posix()}
        ledger.append_usage(usage_path, row)
        rows.append(row)  # the guard counts everything spent, including earlier runs
        new_rows.append(row)
        log(f"  {it.item_id:10} {'cached' if hit else 'rendered'}"
            + ("" if hit else f", {actual if actual is not None else '?'} credits (est {est})"))

    for seg in plan["segments"]:
        times = times_by_segment.get(seg["id"])
        if times:
            seg["line_times_ms"] = [{"line_id": lid, "start_ms": round(times[str(i)][0] * 1000),
                                     "end_ms": round(times[str(i)][1] * 1000)}
                                    for i, lid in enumerate(seg["line_ids"]) if str(i) in times]
    for bed in plan["beds"]:
        bed.pop("prompt", None)
    folder.mkdir(parents=True, exist_ok=True)
    # segments.json goes last and lands in one rename, so Surface's watcher never sees a partial plan.
    for name, data in (("script.json", sub_script), ("voices.json", voices), ("segments.json", plan)):
        tmp = folder / f".{name}.tmp"
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(folder / name)
    errors = check_folder(folder)
    if errors:
        raise RuntimeError("rendered folder fails the interface check:\n" + "\n".join(errors))
    return new_rows
