import argparse
import difflib
import json
import os
from datetime import date, timedelta
from pathlib import Path

DEFAULT_FILE = Path.home() / ".habits.json"
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
GROUPS = {"daily": [0, 1, 2, 3, 4, 5, 6], "weekdays": [0, 1, 2, 3, 4], "weekends": [5, 6]}
DONE, MISSED, OFF, PENDING = "■", "□", "·", "○"
MILESTONES = (7, 14, 30, 60, 100, 365)


def parse_days(text: str) -> list[int]:
    """'daily', 'weekdays', 'weekends' or a list like 'mon,wed,fri' -> weekday numbers (Mon=0)."""
    text = text.strip().lower()
    if text in GROUPS:
        return GROUPS[text]
    days = set()
    for part in text.split(","):
        part = part.strip()[:3]
        if part not in WEEKDAYS:
            raise ValueError(f"Unknown day '{part}'. Use daily, weekdays, weekends or e.g. mon,wed,fri.")
        days.add(WEEKDAYS.index(part))
    return sorted(days)


def describe_days(days: list[int]) -> str:
    for label, group in GROUPS.items():
        if days == group:
            return "every day" if label == "daily" else label
    return ", ".join(WEEKDAYS[d].capitalize() for d in days)


def done_set(habit: dict) -> set[date]:
    return {date.fromisoformat(d) for d in habit["log"]}


def start_date(habit: dict) -> date:
    return min([date.fromisoformat(habit["created"])] + list(done_set(habit)))


def is_scheduled(habit: dict, day: date) -> bool:
    return day.weekday() in habit["days"]


def current_streak(habit: dict, today: date) -> int:
    """Scheduled days completed in a row, counting back from today."""
    done, start = done_set(habit), start_date(habit)
    day = today
    if is_scheduled(habit, day) and day not in done:
        day -= timedelta(days=1)  
    streak = 0
    while day >= start:
        if is_scheduled(habit, day):
            if day not in done:
                break
            streak += 1
        day -= timedelta(days=1)
    return streak


def longest_streak(habit: dict, today: date) -> int:
    done = done_set(habit)
    best = run = 0
    day = start_date(habit)
    while day <= today:
        if is_scheduled(habit, day):
            if day in done:
                run += 1
                best = max(best, run)
            elif day != today:  
                run = 0
        day += timedelta(days=1)
    return best


def completion_rate(habit: dict, today: date, window: int = 30) -> float | None:
    """Share of scheduled days completed in the last `window` days (None if nothing was due)."""
    done = done_set(habit)
    day = max(start_date(habit), today - timedelta(days=window - 1))
    due = hit = 0
    while day <= today:
        if is_scheduled(habit, day) and (day in done or day != today):
            due += 1
            hit += day in done
        day += timedelta(days=1)
    return hit / due if due else None


def glyph(habit: dict, day: date, today: date, done: set[date]) -> str:
    if day < start_date(habit):
        return " "
    if day in done:
        return DONE
    if not is_scheduled(habit, day):
        return OFF
    return PENDING if day == today else MISSED


def heatmap(habit: dict, today: date, weeks: int = 12) -> list[str]:
    """One row per weekday, one column per week, oldest week on the left."""
    done = done_set(habit)
    first_monday = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)
    rows = []
    for row, label in enumerate(WEEKDAYS):
        cells = []
        for week in range(weeks):
            day = first_monday + timedelta(weeks=week, days=row)
            cells.append(" " if day > today else glyph(habit, day, today, done))
        rows.append(f"{label.capitalize()}  " + " ".join(cells))
    return rows


def load(path: Path) -> dict:
    if not path.exists():
        return {"habits": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["habits"].items()
        return data
    except (ValueError, KeyError, AttributeError):
        raise SystemExit(f"{path} is not a valid habits file. Fix or delete it to start fresh.")


def save(path: Path, data: dict) -> None:
    temp = path.with_name(path.name + ".tmp")  
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(temp, path)


def resolve(data: dict, name: str) -> str:
    """Find a habit by exact name (any case) or unique prefix."""
    lowered = {key.lower(): key for key in data["habits"]}
    wanted = name.strip().lower()
    if wanted in lowered:
        return lowered[wanted]
    matches = [key for low, key in lowered.items() if wanted and low.startswith(wanted)]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise SystemExit(f"'{name}' matches several habits: {', '.join(sorted(matches))}")
    close = difflib.get_close_matches(wanted, lowered, n=3, cutoff=0.5)
    hint = f" Did you mean: {', '.join(lowered[c] for c in close)}?" if close else ""
    raise SystemExit(f"No habit called '{name}'.{hint}")


def target_day(args) -> date:
    if args.yesterday:
        day = args.today - timedelta(days=1)
    elif args.date:
        try:
            day = date.fromisoformat(args.date)
        except ValueError:
            raise SystemExit("Dates look like 2026-11-14.")
    else:
        day = args.today
    if day > args.today:
        raise SystemExit("You can't change a day in the future.")
    return day


def cmd_add(args) -> None:
    data = load(args.file)
    name = args.name.strip()
    if not name or len(name) > 40:
        raise SystemExit("A habit name needs 1-40 characters.")
    if any(key.lower() == name.lower() for key in data["habits"]):
        raise SystemExit(f"'{name}' already exists.")
    try:
        days = parse_days(args.days)
    except ValueError as error:
        raise SystemExit(str(error))
    data["habits"][name] = {"created": args.today.isoformat(), "days": days, "log": []}
    save(args.file, data)
    print(f"Added '{name}' ({describe_days(days)}). Check it off with: python habits.py done {name}")


def cmd_done(args) -> None:
    data = load(args.file)
    name = resolve(data, args.name)
    habit, day = data["habits"][name], target_day(args)
    if day.isoformat() in habit["log"]:
        print(f"'{name}' is already checked off for {day:%a %d %b}.")
        return
    habit["log"] = sorted(habit["log"] + [day.isoformat()])
    save(args.file, data)
    streak = current_streak(habit, args.today)
    print(f"{DONE} {name} done for {day:%a %d %b}. Current streak: {streak}")
    if streak in MILESTONES:
        print(f"   {streak} in a row. Keep it going!")


def cmd_undo(args) -> None:
    data = load(args.file)
    name = resolve(data, args.name)
    habit, day = data["habits"][name], target_day(args)
    if day.isoformat() not in habit["log"]:
        raise SystemExit(f"'{name}' wasn't checked off for {day:%a %d %b}.")
    habit["log"].remove(day.isoformat())
    save(args.file, data)
    print(f"Removed the check-off for '{name}' on {day:%a %d %b}.")


def cmd_status(args) -> None:
    habits = load(args.file)["habits"]
    if not habits:
        print("No habits yet. Add one with: python habits.py add meditate")
        return
    today = args.today
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    width = max(len(name) for name in habits)
    print(f"{today:%A %d %B %Y}\n")
    print(" " * width + "  " + " ".join(f"{d:%a}"[:2] for d in days) + "  streak")
    due = finished = 0
    for name in sorted(habits, key=str.lower):
        habit, done = habits[name], done_set(habits[name])
        cells = " ".join(f"{glyph(habit, d, today, done):<2}" for d in days)
        print(f"{name:<{width}}  {cells} {current_streak(habit, today):>6}")
        if is_scheduled(habit, today):
            due += 1
            finished += today in done
    print(f"\n{DONE} done   {PENDING} to do today   {MISSED} missed   {OFF} day off")
    print(f"Today: {finished} of {due} scheduled habits done." if due else "Nothing is scheduled today.")


def cmd_stats(args) -> None:
    habits = load(args.file)["habits"]
    if not habits:
        print("No habits yet. Add one with: python habits.py add meditate")
        return
    today = args.today
    if args.name:
        name = resolve({"habits": habits}, args.name)
        habit = habits[name]
        rate = completion_rate(habit, today)
        print(f"{name}  ({describe_days(habit['days'])}, tracking since {start_date(habit):%d %b %Y})")
        print(f"  current streak : {current_streak(habit, today)}")
        print(f"  longest streak : {longest_streak(habit, today)}")
        print(f"  total check-ins: {len(habit['log'])}")
        print(f"  last 30 days   : {f'{rate:.0%}' if rate is not None else 'n/a'}\n")
        print("\n".join(heatmap(habit, today)))
        print(f"\n{DONE} done  {MISSED} missed  {OFF} day off   (12 weeks, oldest on the left)")
        return
    width = max(len(name) for name in habits)
    print(f"{'':<{width}}  streak   best  total  30 days")
    for name in sorted(habits, key=str.lower):
        habit, rate = habits[name], completion_rate(habits[name], today)
        shown = f"{rate:.0%}" if rate is not None else "n/a"
        print(f"{name:<{width}}  {current_streak(habit, today):>6} {longest_streak(habit, today):>6} "
              f"{len(habit['log']):>6} {shown:>8}")


def cmd_delete(args) -> None:
    data = load(args.file)
    name = resolve(data, args.name)
    if input(f"Delete '{name}' and its {len(data['habits'][name]['log'])} check-ins? [y/N] ").strip().lower() in ("y", "yes"):
        del data["habits"][name]
        save(args.file, data)
        print("Deleted.")


def main(argv: list[str] | None = None, today: date | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--file", type=Path, default=DEFAULT_FILE, help=f"data file (default: {DEFAULT_FILE})")
    dated = argparse.ArgumentParser(add_help=False)
    dated.add_argument("--date", help="a past day, like 2026-11-10 (default: today)")
    dated.add_argument("--yesterday", action="store_true")

    add = sub.add_parser("add", parents=[common], help="create a habit")
    add.add_argument("name")
    add.add_argument("--days", default="daily", help="daily, weekdays, weekends or e.g. mon,wed,fri")
    add.set_defaults(run=cmd_add)

    for name, helptext, run in (("done", "check off a habit", cmd_done), ("undo", "remove a check-off", cmd_undo)):
        command = sub.add_parser(name, parents=[common, dated], help=helptext)
        command.add_argument("name")
        command.set_defaults(run=run)

    sub.add_parser("status", parents=[common], help="today and the last 7 days").set_defaults(run=cmd_status)
    stats = sub.add_parser("stats", parents=[common], help="streaks and completion rates")
    stats.add_argument("name", nargs="?", help="show one habit in detail, with a heatmap")
    stats.set_defaults(run=cmd_stats)
    delete = sub.add_parser("delete", parents=[common], help="remove a habit")
    delete.add_argument("name")
    delete.set_defaults(run=cmd_delete)

    args = parser.parse_args(argv)
    args.today = today or date.today()
    args.run(args)


if __name__ == "__main__":
    main()
