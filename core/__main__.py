"""Full Cast command line.

  python -m core step0                      free: balance, model check, starting dialogue price
  python -m core cast [--recast]            free: pick premade voices, lock core/adaptation/voices.json
  python -m core run --dry-run [--scene N]  free: show the work list and estimated credits
  python -m core run --scene 1              paid: render one scene into <output>/preview-s01
  python -m core run                        paid: render everything into the output folder
"""
import argparse
import sys

from core import ledger
from core.config import ADAPTATION_DIR, DIALOGUE_MODEL_ID, api_key, output_dir
from core.interface import load_json


def make_client():
    from elevenlabs.client import ElevenLabs  # imported here so dry runs work without the package

    return ElevenLabs(api_key=api_key())


def step0(client, out_root):
    sub = client.user.subscription.get()
    remaining = sub.character_limit - sub.character_count
    print(f"tier: {sub.tier} | used {sub.character_count} of {sub.character_limit} | remaining {remaining}")
    models = {m.model_id: m for m in client.models.list()}
    model = models.get(DIALOGUE_MODEL_ID)
    if model is None:
        print(f"STOP: model {DIALOGUE_MODEL_ID!r} not in this account's list: {sorted(models)}")
        return 1
    rates = model.model_rates
    multiplier = rates.character_cost_multiplier if rates else None
    print(f"{DIALOGUE_MODEL_ID}: character_cost_multiplier={multiplier}, "
          f"max chars per request={model.maximum_text_length_per_request}")
    prices_path = out_root / "pricing.json"
    prices = ledger.load_prices(prices_path)
    if prices.get("dialogue_basis") != "measured" and multiplier is not None:
        # An assumption until the first dialogue call measures the real rate from the balance.
        prices["dialogue_credits_per_char"] = multiplier
        prices["dialogue_basis"] = "assumed (1 credit per character x model multiplier)"
        ledger.save_prices(prices_path, prices)
    print(f"starting prices: {prices}")
    if remaining < ledger.RESERVE_CREDITS:
        print(f"STOP: only {remaining} credits left, below the {ledger.RESERVE_CREDITS} reserve")
        return 1
    return 0


def main(argv):
    parser = argparse.ArgumentParser(prog="python -m core", description="Full Cast pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("step0")
    p_cast = sub.add_parser("cast")
    p_cast.add_argument("--recast", action="store_true")
    p_run = sub.add_parser("run")
    p_run.add_argument("--scene", type=int, action="append", help="render only this scene (repeatable)")
    p_run.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    script = load_json(ADAPTATION_DIR / "script.json")
    out_root = output_dir()
    if args.command == "step0":
        return step0(make_client(), out_root)
    if args.command == "cast":
        from core.cast import cast

        picks = cast(make_client(), script, ADAPTATION_DIR / "voices.json", recast=args.recast)
        for cid, p in picks.items():
            print(f"  {cid:16} -> {p['label']} (score {p['score']})")
        return 0

    from core.render import run

    voices_path = ADAPTATION_DIR / "voices.json"
    if not voices_path.exists():
        print("no voices.json yet: run `python -m core cast` first")
        return 1
    scenes = set(args.scene) if args.scene else None
    client = None if args.dry_run else make_client()
    try:
        run(client, script, load_json(voices_path), out_root, scenes=scenes, dry_run=args.dry_run)
    except ledger.BudgetError as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
