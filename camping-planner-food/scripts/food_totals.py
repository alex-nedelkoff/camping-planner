#!/usr/bin/env python3
"""
Resolve foods + meals from data/foods.yaml and data/meals.yaml.

Foods carry per-serving macros (matches nutrition labels). The script
derives per-100g internally for any quantity scaling, and shows
kcal/100g in the `list foods` output for comparability.

Usage:
  food_totals.py food <food-id> [--grams N | --servings N]
  food_totals.py meal <meal-id> [--people N]
  food_totals.py list (foods|meals) [--category X | --slot X | --tag X]

Examples:
  food_totals.py food filet-mignon-raw --grams 227
  food_totals.py food clif-bar --servings 1
  food_totals.py meal rice-chana-masala --people 2
  food_totals.py list foods --category protein
  food_totals.py list meals --slot dinner
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pip install pyyaml")


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FOODS_PATH = DATA_DIR / "foods.yaml"
MEALS_PATH = DATA_DIR / "meals.yaml"

REQUIRED_SERVING_KEYS = ("g", "kcal", "protein_g", "carbs_g", "fat_g")


@dataclass
class Macros:
    kcal: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    weight_g: float = 0.0

    def __add__(self, other: "Macros") -> "Macros":
        return Macros(
            self.kcal + other.kcal,
            self.protein_g + other.protein_g,
            self.carbs_g + other.carbs_g,
            self.fat_g + other.fat_g,
            self.weight_g + other.weight_g,
        )

    def scaled(self, factor: float) -> "Macros":
        return Macros(
            self.kcal * factor,
            self.protein_g * factor,
            self.carbs_g * factor,
            self.fat_g * factor,
            self.weight_g * factor,
        )


def load_foods() -> dict[str, dict]:
    with FOODS_PATH.open() as f:
        items = yaml.safe_load(f) or []
    by_id: dict[str, dict] = {}
    for it in items:
        fid = it["id"]
        if fid in by_id:
            sys.exit(f"Duplicate food id: {fid}")
        serving = it.get("serving")
        if not isinstance(serving, dict):
            sys.exit(f"Food '{fid}' is missing a `serving:` block")
        for k in REQUIRED_SERVING_KEYS:
            if k not in serving:
                sys.exit(f"Food '{fid}' serving is missing key: {k}")
        if serving["g"] <= 0:
            sys.exit(f"Food '{fid}' serving.g must be > 0")
        by_id[fid] = it
    return by_id


def load_meals() -> dict[str, dict]:
    if not MEALS_PATH.exists():
        return {}
    with MEALS_PATH.open() as f:
        items = yaml.safe_load(f) or []
    by_id: dict[str, dict] = {}
    for it in items:
        mid = it["id"]
        if mid in by_id:
            sys.exit(f"Duplicate meal id: {mid}")
        by_id[mid] = it
    return by_id


def per_100g(food: dict) -> dict[str, float]:
    """Derived per-100g view of a food."""
    s = food["serving"]
    f = 100.0 / s["g"]
    return {
        "kcal": s["kcal"] * f,
        "protein_g": s["protein_g"] * f,
        "carbs_g": s["carbs_g"] * f,
        "fat_g": s["fat_g"] * f,
    }


def macros_for_grams(food: dict, grams: float) -> Macros:
    s = food["serving"]
    factor = grams / s["g"]
    return Macros(
        kcal=s["kcal"] * factor,
        protein_g=s["protein_g"] * factor,
        carbs_g=s["carbs_g"] * factor,
        fat_g=s["fat_g"] * factor,
        weight_g=grams,
    )


def macros_for_servings(food: dict, n: float) -> Macros:
    s = food["serving"]
    return Macros(
        kcal=s["kcal"] * n,
        protein_g=s["protein_g"] * n,
        carbs_g=s["carbs_g"] * n,
        fat_g=s["fat_g"] * n,
        weight_g=s["g"] * n,
    )


def resolve_ingredient(food: dict, ref: dict) -> Macros:
    has_g = "g" in ref
    has_s = "servings" in ref
    if has_g and has_s:
        sys.exit(f"Ingredient {food['id']}: specify g OR servings, not both")
    if has_g:
        return macros_for_grams(food, float(ref["g"]))
    if has_s:
        return macros_for_servings(food, float(ref["servings"]))
    sys.exit(f"Ingredient {food['id']}: needs g: or servings:")


def macros_for_meal(meal: dict, foods: dict[str, dict],
                     include_optional: bool = False):
    """Return (totals for the whole recipe, breakdown rows, recipe servings)."""
    rows = []
    totals = Macros()
    servings = float(meal.get("servings", 1))
    for ing in meal["ingredients"]:
        if ing.get("optional") and not include_optional:
            continue
        fid = ing["food"]
        if fid not in foods:
            sys.exit(f"Unknown food '{fid}' in meal '{meal['id']}'")
        food = foods[fid]
        m = resolve_ingredient(food, ing)
        rows.append((food["name"], m))
        totals = totals + m
    return totals, rows, servings


def fmt(m: Macros) -> str:
    return (f"{m.kcal:>5.0f} kcal  "
            f"P {m.protein_g:>4.0f}g  "
            f"C {m.carbs_g:>4.0f}g  "
            f"F {m.fat_g:>4.0f}g  "
            f"({m.weight_g:>5.0f}g)")


# ─── Commands ───────────────────────────────────────────────────────────────

def cmd_food(args):
    foods = load_foods()
    if args.id not in foods:
        sys.exit(f"Unknown food id: {args.id}")
    food = foods[args.id]
    s = food["serving"]
    if args.grams is not None:
        m = macros_for_grams(food, args.grams)
        label = f"{args.grams:.0f}g"
    elif args.servings is not None:
        m = macros_for_servings(food, args.servings)
        sl = food.get("serving_label", f"{s['g']:.0f}g")
        label = f"{args.servings:g} × ({sl})"
    else:
        m = macros_for_servings(food, 1)
        sl = food.get("serving_label", f"{s['g']:.0f}g")
        label = f"1 × ({sl})"
    p100 = per_100g(food)
    print(f"{food['name']}")
    print(f"  @ {label:<28s} →  {fmt(m)}")
    print(f"  per 100g                       "
          f"   {p100['kcal']:>5.0f} kcal  "
          f"P {p100['protein_g']:>4.1f}g  "
          f"C {p100['carbs_g']:>4.1f}g  "
          f"F {p100['fat_g']:>4.1f}g")


def cmd_meal(args):
    foods = load_foods()
    meals = load_meals()
    if args.id not in meals:
        sys.exit(f"Unknown meal id: {args.id}")
    meal = meals[args.id]
    totals, rows, servings = macros_for_meal(
        meal, foods, include_optional=args.include_optional)

    print(f"{meal['name']}  ·  {meal.get('slot', '?')}  ·  yields {servings:.0f} serving(s)")
    print()
    for name, m in rows:
        print(f"  {name:<42s}  {fmt(m)}")
    print(f"  {'─' * 90}")
    print(f"  {'TOTAL (whole recipe)':<42s}  {fmt(totals)}")
    print(f"  {'per serving':<42s}  {fmt(totals.scaled(1.0 / servings))}")

    if args.people:
        factor = args.people / servings
        print()
        print(f"  Scaled for {args.people} people  ({factor:.2f}× recipe):")
        print(f"  {'TOTAL':<42s}  {fmt(totals.scaled(factor))}")


def cmd_list(args):
    if args.kind == "foods":
        foods = load_foods()
        rows = list(foods.values())
        if args.category:
            rows = [r for r in rows if r.get("category") == args.category]
        if args.tag:
            rows = [r for r in rows if args.tag in (r.get("tags") or [])]
        rows.sort(key=lambda r: (r.get("category", ""), r["id"]))
        for r in rows:
            p = per_100g(r)
            s = r["serving"]
            print(f"  {r['id']:<32s} {r.get('category', '-'):<10s}  "
                  f"{p['kcal']:>4.0f} kcal/100g   "
                  f"serving {s['g']:>4.0f}g={s['kcal']:>4.0f} kcal   "
                  f"{r['name']}")
    elif args.kind == "meals":
        meals = load_meals()
        rows = list(meals.values())
        if args.slot:
            rows = [r for r in rows if r.get("slot") == args.slot]
        if args.tag:
            rows = [r for r in rows if args.tag in (r.get("tags") or [])]
        rows.sort(key=lambda r: (r.get("slot", ""), r["id"]))
        for r in rows:
            print(f"  {r['id']:<32s} {r.get('slot', '-'):<10s} "
                  f"yields {r.get('servings', 1)}  {r['name']}")


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("food", help="Show macros for a food at a given quantity")
    pf.add_argument("id")
    g = pf.add_mutually_exclusive_group()
    g.add_argument("--grams", type=float)
    g.add_argument("--servings", type=float)
    pf.set_defaults(func=cmd_food)

    pm = sub.add_parser("meal", help="Show macros for a meal")
    pm.add_argument("id")
    pm.add_argument("--people", type=int,
                     help="Scale totals to feed this many people")
    pm.add_argument("--include-optional", action="store_true")
    pm.set_defaults(func=cmd_meal)

    pl = sub.add_parser("list", help="List foods or meals")
    pl.add_argument("kind", choices=["foods", "meals"])
    pl.add_argument("--category")
    pl.add_argument("--slot")
    pl.add_argument("--tag")
    pl.set_defaults(func=cmd_list)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
