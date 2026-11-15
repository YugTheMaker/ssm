#!/usr/bin/env python3
"""S S <slot>: a small, local Sasquatch save console. Never evaluates shell/Python input."""
import argparse
from decimal import Decimal
import fcntl
import json
from pathlib import Path
import re
import sys
import slot3_mod as saves

WORDS = dict(zip('zero one two three four five six seven eight nine ten'.split(), range(11)))
SCALE = {'': 1, 'k': 1000, 'thousand': 1000, 'm': 1000000, 'million': 1000000, 'b': 1000000000, 'billion': 1000000000}

def parse_amount(text):
    text = text.strip().lower()
    is_neg = False
    if text.startswith('-'):
        is_neg = True
        text = text[1:].strip()
    match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?|[0-9]{1,3}(?:,[0-9]{3})+|zero|one|two|three|four|five|six|seven|eight|nine|ten)\s*(thousand|million|billion|k|m|b)?', text)
    if not match:
        raise saves.ModError('Use a number such as -1, -2, 4444, 2,000,000, 2m, or 2 billion.')
    raw, suffix = match.groups()
    value = Decimal(WORDS[raw]) if raw in WORDS else Decimal(raw.replace(',', ''))
    value *= SCALE[suffix or '']
    if is_neg:
        value = -value
    if value != value.to_integral_value() or not -saves.MAX_TOTAL <= value <= saves.MAX_TOTAL:
        raise saves.ModError('Enter a whole number from -2 billion to 2 billion.')
    return int(value)

CURRENCIES = {
    'c': ('Wallet coins', 'coins'), 'b': ('Bank coins', 'bankcoin'),
    't': ('Arcade prize tickets', 'ptkt'), 'l': ('Lumber', 'lumber'),
    'film': ('Camera film', 'cf'), 'pages': ('Photo album pages', 'pap'),
    'bags': ('Poop bags', 'pb'), 'balls': ('Tennis balls', 'tb'),
    'trash': ('Underwater trash', 'st'), 'candy': ('Halloween candy', 'hwcd'),
    'canes': ('Christmas candy canes', 'xmcc'),
    'badges': ('Raccoon Club badges', '4o'),
}
ALIASES = {
    'coins':'c', 'bank':'b', 'tickets':'t', 'tokens':'t', 'ikt':'t', 'lumber':'l',
    'badge':'badges', 'badges':'badges', 'rcb':'badges', 'raccoon':'badges', 'batches':'badges'
}

def show_status(root, slot):
    _, _, data = saves.read_save(root, slot)
    msg = f"Slot {slot} | C (wallet) = {data.get('coins', 0):,} | B (bank) = {data.get('bankcoin', 0):,} | T (arcade tickets) = {data.get('ptkt', 0):,}"
    try:
        _, _, vdata = saves.read_variables(root, slot)
        doc_lvl = vdata.get('sR')
        if type(doc_lvl) is int and 0 <= doc_lvl <= 3:
            msg += f" | Doctor: {saves.DOCTOR_RANKS[doc_lvl + 1]} (Level {doc_lvl + 1}/4)"
        ff = saves.get_firefighter_info(root, slot)
        if ff['level'] > 1 or ff['funding'] > 0:
            msg += f" | Fire: {ff['rank']} (Lvl {ff['level']}/8, Funding: {ff['funding']:,})"
    except Exception:
        pass
    print(msg)

def show_cars(root, slot):
    try:
        status_list = saves.get_all_vehicles_status(root, slot)
        owned_count = sum(1 for v in status_list if v['owned'])
        print(f"Slot {slot}: {owned_count}/{len(status_list)} vehicles owned")
        for v in status_list:
            if v['owned']:
                lvl_str = f"Lvl {v['level']}/5" if v['level'] is not None else "Owned"
                print(f"  [✓ OWNED: {lvl_str:9}] {v['name']} ({v['id']}) - {v['category']}")
            else:
                print(f"  [🔒 LOCKED      ] {v['name']} ({v['id']}) - {v['category']}")
        print("\nUnlock any vehicle: own <name>  (e.g. own slow mobile, own pickup truck, own forklift)")
        print("Unlock all vehicles: maxcars")
    except Exception:
        _, _, data = saves.read_equipment(root, slot)
        print(f"Slot {slot}: {len(data['vehicles'])} owned vehicle records")
        for vehicle in data['vehicles']:
            stored = vehicle.get('lvl', 0)
            print(' ', vehicle['id'], '| garage level:', stored + 1 if type(stored) is int else 'unknown')
        print('Supported IDs:', ', '.join(sorted(saves.BASIC_CARS)))

HELP = ('MAIN OPTIONS:\n'
        '  C          Currency menu (wallet, bank, tickets, lumber, all currencies)\n'
        '  O          Owned stuff menu (Sneaky shoes, cars, doctor rank, firefighter career)\n'
        '  Q / exit   Save & leave the console\n'
        '  undo       Undo the latest unchanged edit for this slot\n\n'
        'DIRECT COMMANDS:\n'
        '  C = 4444   wallet coins\n  B = 2m     bank coins\n  T = 1000   arcade prize tickets\n'
        '  L = 1000   lumber\n  film = 20  camera film\n  pages = 20 photo album pages\n'
        '  bags = 20  poop bags\n  balls = 20 tennis balls\n  trash = 20 underwater trash\n'
        '  candy = 20 Halloween candy\n  canes = 20 Christmas candy canes\n'
        '  FF = 500k  firefighter funding (or funding = 500k)\n'
        '  fire rank 8 set firefighter rank (1-8, 8 is Junior Battalion Chief)\n'
        '  maxfire    max funding (500k), max rank (8), and max station upgrades\n'
        '  cars       list owned vehicle IDs\n  own = car  own/copy a supported car\n'
        '  maxcars    own all cars at max garage level\n'
        '  SC sports car 1   set car garage level (1–5)\n'
        '  sneaky     own & activate Sneaky shoes\n'
        '  RS G       give running shoes\n  RS A       activate running shoes\n'
        '  JD         become Junior Head Doctor (Level 4; or JD 1-4)\n'
        '  resources  show all supported currencies\n  status     read balances\n'
        'Amounts accept 2b, 2 billion, or two billion. Assignments SET totals, not increments.')

def currency_menu(slot, root, package, read, check_closed):
    backup_root = package / 'console-backups'
    _, _, data = saves.read_save(root, slot)
    print("\n" + "=" * 54)
    print(f"             CURRENCY MENU — SLOT {slot}")
    print("=" * 54)
    items = list(CURRENCIES.items())
    for idx, (cmd, (label, field)) in enumerate(items, 1):
        print(f"  {idx:2d}. {label:<24} [{cmd.upper():>4}]: {data.get(field, 0):,}")
    print(f"  12. {'MAX ALL CURRENCIES':<24} [ MAX]: Set all to 2,000,000!")
    print("-" * 54)
    print("Type a number or currency (e.g. '1', 'C', '1 50000', 'C = 2m', 'max').")
    print("Press Enter or type 'back' to return to main menu.")

    while True:
        try:
            choice = read(f"SS [slot {slot}] Currency > ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not choice or choice.lower() in ('back', 'exit', 'q', 'b'):
            return
        try:
            if choice.lower() in ('12', 'max', 'all'):
                backup = saves.max_all_currencies(root, backup_root, slot, check_closed=check_closed)
                print("All currencies set to 2,000,000!")
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
                show_status(root, slot)
                return

            parts = choice.split(None, 1)
            target = parts[0].lower()
            amt_text = parts[1].lstrip('=').strip() if len(parts) > 1 else None

            field_cmd = None
            if target.isdigit():
                num = int(target)
                if 1 <= num <= len(items):
                    field_cmd = items[num - 1][0]
                elif num == 12:
                    backup = saves.max_all_currencies(root, backup_root, slot, check_closed=check_closed)
                    print("All currencies set to 2,000,000!")
                    print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
                    show_status(root, slot)
                    return
            else:
                target = ALIASES.get(target, target)
                if target in CURRENCIES:
                    field_cmd = target

            if not field_cmd:
                raise saves.ModError("Choose 1–12 or a resource like C, B, T, L, film, candy, max.")

            label, field = CURRENCIES[field_cmd]
            if amt_text is None:
                amt_text = read(f"New amount for {label} (e.g. 50000, 2m, 2 billion): ").strip()
                if not amt_text:
                    continue

            value = parse_amount(amt_text)
            kwargs = {'coins': value} if field_cmd == 'c' else {'bank': value} if field_cmd == 'b' else {'currency_updates': {field: value}}
            backup = saves.apply(root, backup_root, check_closed=check_closed, slot_number=slot, **kwargs)
            _, _, actual = saves.read_save(root, slot)
            print(f"{label} = {actual.get(field, 0):,}")
            show_status(root, slot)
            print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
            return
        except (saves.ModError, OSError, ValueError) as e:
            print("Stopped:", e)

def owned_menu(slot, root, package, read, check_closed):
    backup_root = package / 'console-backups'
    print("\n" + "=" * 54)
    print(f"            OWNED STUFF MENU — SLOT {slot}")
    print("=" * 54)
    print("SHOES & SNEAKERS:")
    print("  1. [sneaky]   Own & Activate Sneaky Shoes (Sneaking Boots)")
    print("  2. [running]  Own & Activate Running Shoes")
    print("  3. [shoes]    Unlock ALL Shoes (Sneaky + Running + Sprinting)")
    print("\nVEHICLES:")
    print("  4. [cars]     List currently owned cars & levels")
    print("  5. [own]      Own a car (supercar, sportscar, pickupTruck, car, golfcart, polcar, gokart)")
    print("  6. [maxcars]  Own ALL cars and upgrade them to maximum level")
    print("  7. [sc]       Set garage level for an owned car (1–5)")
    print("\nCAREER:")
    print("  8. [doctor]   Become Junior Head Doctor (Level 4, Max Doctor Rank)")
    print("  9. [fire]     Firefighter Career, Funding & Station (rank 1-8, funding, max station)")
    print("-" * 54)
    print("Choose 1–9 or type an option (e.g. '1', 'sneaky', 'own supercar', 'maxcars', 'doctor', 'fire').")
    print("Press Enter or type 'back' to return to main menu.")

    while True:
        try:
            choice = read(f"SS [slot {slot}] Owned > ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not choice or choice.lower() in ('back', 'exit', 'q', 'b'):
            return
        try:
            c = choice.lower()
            if c in ('1', 'sneaky', 'sneak'):
                backup = saves.activate_sneaky_shoes(root, backup_root, slot, check_closed=check_closed)
                print("Sneaky Shoes (Sneaking Boots) owned and activated!")
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already active; nothing changed.')
                return
            elif c in ('2', 'running', 'run'):
                b1 = saves.gift_running_shoes(root, backup_root, slot, check_closed=check_closed)
                b2 = saves.activate_running_shoes(root, backup_root, slot, check_closed=check_closed)
                backup = b2 or b1
                print("Running Shoes owned and activated!")
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already active; nothing changed.')
                return
            elif c in ('3', 'shoes', 'all shoes', 'allshoes'):
                backup = saves.unlock_all_shoes(root, backup_root, slot, check_closed=check_closed)
                print("All shoes (Sneaky Shoes, Running Shoes, Sprinting Shoes) unlocked & activated!")
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already unlocked; nothing changed.')
                return
            elif c in ('4', 'cars', 'vehicles'):
                show_cars(root, slot)
                return
            elif c.startswith('5') or c.startswith('own'):
                parts = choice.split(None, 1)
                car_name = parts[1].lstrip('=').strip() if len(parts) > 1 and parts[0].lower() in ('5', 'own') else None
                if not car_name:
                    print("Available vehicles to unlock (30+ vehicles):")
                    print("  e.g. slow mobile, pickup truck, forklift, 4x4, dirt bike, supercar, sportscar...")
                    car_name = read("Enter vehicle name to own: ").strip()
                if car_name:
                    backup = saves.own_car(root, backup_root, slot, car_name, check_closed=check_closed)
                    print(f"Vehicle '{car_name}' added to slot {slot}!")
                    show_cars(root, slot)
                    print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already owned; nothing changed.')
                return
            elif c in ('6', 'maxcars', 'all cars', 'allcars'):
                backup = saves.own_all_cars(root, backup_root, slot, max_level=True, check_closed=check_closed)
                print("All cars granted and upgraded to maximum garage level!")
                show_cars(root, slot)
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already at maximum; nothing changed.')
                return
            elif c.startswith('7') or c.startswith('sc'):
                parts = choice.split()
                if len(parts) >= 3 and parts[0].lower() in ('7', 'sc'):
                    name = ' '.join(parts[1:-1])
                    lvl = int(parts[-1])
                else:
                    show_cars(root, slot)
                    name = read("Enter car name: ").strip()
                    lvl = int(read("Enter level (1–5): ").strip())
                backup = saves.set_car_level(root, backup_root, slot, name, lvl, check_closed=check_closed)
                show_cars(root, slot)
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
                return
            elif c in ('8', 'doctor', 'jd'):
                backup = saves.set_doctor_level(root, backup_root, slot, 4, check_closed=check_closed)
                title = saves.DOCTOR_RANKS[4]
                print(f"Doctor rank set to {title} (Level 4/4 - Max Level)!")
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
                show_status(root, slot)
                return
            elif c.startswith('9') or c.startswith('fire') or c.startswith('ff') or c == 'maxfire':
                if c in ('maxfire', 'fire max'):
                    backup = saves.max_fire_station(root, backup_root, slot, check_closed=check_closed)
                    print(f"Fire station maxed! Funding 500k+, rank Junior Battalion Chief (8/8), and all upgrades maxed in slot {slot}!")
                elif 'funding' in c or 'fund' in c:
                    parts = choice.split(None, 2)
                    amt_str = parts[-1] if len(parts) > 2 or (len(parts) == 2 and any(ch.isdigit() for ch in parts[1])) else None
                    if not amt_str:
                        amt_str = read("Enter firefighter funding amount (e.g. 50000, 2m): ").strip()
                    amt = parse_amount(amt_str)
                    backup = saves.set_firefighter_funding(root, backup_root, slot, amt, check_closed=check_closed)
                    print(f"Firefighter funding set to {amt:,} in slot {slot}!")
                elif 'rank' in c or 'level' in c or any(ch.isdigit() for ch in c if c != '9'):
                    match = re.search(r'\b([1-8])\b', c)
                    lvl = int(match.group(1)) if match else int(read("Enter firefighter level (1-8): ").strip())
                    backup = saves.set_firefighter_level(root, backup_root, slot, lvl, check_closed=check_closed)
                    print(f"Firefighter rank set to {saves.FIREFIGHTER_RANKS[lvl]} (Level {lvl}/8) in slot {slot}!")
                else:
                    sub = read("Firefighter: [1] Set Funding, [2] Set Rank (1-8), [3] Max Fire Station: ").strip().lower()
                    if sub in ('1', 'funding', 'fund'):
                        amt = parse_amount(read("Enter firefighter funding amount: ").strip())
                        backup = saves.set_firefighter_funding(root, backup_root, slot, amt, check_closed=check_closed)
                        print(f"Firefighter funding set to {amt:,} in slot {slot}!")
                    elif sub in ('2', 'rank', 'level'):
                        lvl = int(read("Enter firefighter rank level (1-8): ").strip())
                        backup = saves.set_firefighter_level(root, backup_root, slot, lvl, check_closed=check_closed)
                        print(f"Firefighter rank set to {saves.FIREFIGHTER_RANKS[lvl]} (Level {lvl}/8) in slot {slot}!")
                    else:
                        backup = saves.max_fire_station(root, backup_root, slot, check_closed=check_closed)
                        print(f"Fire station maxed! Funding 500k+, Junior Battalion Chief rank (8/8), and all upgrades maxed in slot {slot}!")
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
                show_status(root, slot)
                return
            else:
                raise saves.ModError("Choose 1–9 or an option like 'sneaky', 'shoes', 'own supercar', 'maxcars', 'doctor', 'fire'.")
        except (saves.ModError, OSError, ValueError) as e:
            print("Stopped:", e)

def session(slot, root=saves.ROOT, package=saves.PACKAGE, read=input, check_closed=saves.require_closed):
    saves.read_save(root, slot)  # Validate before accepting commands.
    backup_root = package / 'console-backups'
    print(f'\n============================================================')
    print(f'               SNEAKY SASQUATCH — SLOT {slot}')
    print(f'============================================================')
    print('Edits affect only this selected slot. Quit the game before changing values.')
    print('Every edit is backed up. This changes local saves, not in-game menus.\n')
    print('OPTIONS:')
    print('  [C] Currency     - Set coins, bank, tickets, lumber, all currencies')
    print('  [O] Owned Stuff  - Own Sneaky shoes, cars, garage levels, doctor rank')
    print('  [Q] Exit         - Save & close console (or type U to undo)')
    print('\n(Type help to view all direct commands)')
    show_status(root, slot)
    while True:
        try:
            line = read(f'SS [slot {slot}] > ').strip()
        except (EOFError, KeyboardInterrupt):
            print('\nConsole closed.')
            return
        if line.lower() in ('exit', 'quit', 'q'):
            print('Console closed. Open the game and select slot', slot, 'to test your changes.')
            return
        if not line:
            continue
        try:
            cmd = line.lower()
            if cmd in ('help', '?'):
                print(HELP)
            elif cmd in ('c', 'currency', 'currencies'):
                currency_menu(slot, root, package, read, check_closed)
            elif cmd in ('o', 'own', 'owned'):
                owned_menu(slot, root, package, read, check_closed)
            elif cmd in ('sneaky', 'sneak'):
                backup = saves.activate_sneaky_shoes(root, backup_root, slot, check_closed=check_closed)
                print("Sneaky Shoes (Sneaking Boots) owned and activated!")
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already active; nothing changed.')
            elif cmd in ('shoes', 'allshoes', 'all shoes'):
                backup = saves.unlock_all_shoes(root, backup_root, slot, check_closed=check_closed)
                print("All shoes (Sneaky Shoes, Running Shoes, Sprinting Shoes) unlocked & activated!")
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already unlocked; nothing changed.')
            elif cmd in ('maxcars', 'allcars'):
                backup = saves.own_all_cars(root, backup_root, slot, max_level=True, check_closed=check_closed)
                print("All cars granted and upgraded to maximum garage level!")
                show_cars(root, slot)
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already at maximum; nothing changed.')
            elif cmd in ('max', 'maxall'):
                backup = saves.max_all_currencies(root, backup_root, slot, check_closed=check_closed)
                print("All currencies set to 2,000,000!")
                show_status(root, slot)
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
            elif cmd in ('status', 'show'):
                show_status(root, slot)
            elif cmd in ('cars', 'vehicles'):
                show_cars(root, slot)
            elif cmd in ('halloween', 'hallow', 'hal'):
                h_info = saves.get_halloween_info(root, slot)
                new_state = not h_info['active']
                backup = saves.set_halloween_event(root, backup_root, slot, active=new_state, check_closed=check_closed)
                print(f"Halloween seasonal event {'enabled' if new_state else 'disabled'} in slot {slot}!")
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
            elif cmd in ('bowls', 'refill', 'candybowls'):
                backup = saves.refill_candy_bowls(root, backup_root, slot, check_closed=check_closed)
                print(f"All Halloween candy bowls refilled and reset in slot {slot}!")
                print('Saved and verified locally. Open the game to trick-or-treat!')
            elif cmd in ('christmas', 'xmas', 'holiday'):
                c_info = saves.get_christmas_info(root, slot)
                new_state = not c_info['active']
                backup = saves.set_christmas_event(root, backup_root, slot, active=new_state, check_closed=check_closed)
                print(f"Christmas & Winter Holiday seasonal event {'enabled' if new_state else 'disabled'} in slot {slot}!")
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
            elif cmd in ('xmasdecor', 'decorations', 'holidaydecor'):
                backup = saves.unlock_all_christmas_decorations(root, backup_root, slot, check_closed=check_closed)
                print(f"All Jack Frost Christmas decorations unlocked in slot {slot}!")
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
            elif re.match(r'^own\s*(?:=|\s)\s*(.+)', line, re.I):
                match = re.fullmatch(r'^own\s*(?:=|\s)\s*(.+)', line, re.I)
                car_name = match.group(1).strip()
                backup = saves.own_car(root, backup_root, slot, car_name, check_closed=check_closed)
                print(f"Vehicle '{car_name}' added to slot {slot}!")
                show_cars(root, slot)
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already owned; nothing changed.')
            elif cmd in ('resources', 'currencies_list'):
                _, _, data = saves.read_save(root, slot)
                for command, (label, field) in CURRENCIES.items():
                    print(f'{command.upper():6} {label}: {data.get(field, 0):,}')
            elif cmd in ('undo', 'u'):
                candidates = []
                for manifest in backup_root.glob('*/manifest.json'):
                    if not (manifest.parent / 'undone').exists() and json.loads(manifest.read_text()).get('slot') == slot:
                        candidates.append(manifest)
                if not candidates:
                    raise saves.ModError('No console backups for this slot yet.')
                backup = sorted(candidates)[-1].parent
                saves.undo(root, backup, check_closed=check_closed, slot_number=slot)
                print('Previous local save restored. Backup:', backup)
                show_status(root, slot)
            elif re.match(r'^rs(?:-c)?(?:\s|$)', line, re.I):
                match = re.fullmatch(r'rs(?:-c)?\s+(g|gift|a|activate)', line, re.I)
                if not match:
                    raise saves.ModError('Use RS G to give running shoes, then RS A to activate.')
                activating = match.group(1).lower() in ('a', 'activate')
                action = saves.activate_running_shoes if activating else saves.gift_running_shoes
                backup = action(root, backup_root, slot, check_closed=check_closed)
                print('Running-shoe activation saved.' if activating else 'Running-shoe ownership saved. Use RS A to activate.')
                print('Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
                print('In-game speed effect is not verified; reopen the game to test.')
            elif re.match(r'^sc(?:\s|$)', line, re.I):
                match = re.fullmatch(r'sc\s+(.+?)\s+([1-5])', line, re.I)
                if not match:
                    raise saves.ModError('Use SC sports car 1 or SC super car 5. Levels: 1–5.')
                name, level = match.groups()
                backup = saves.set_car_level(root, backup_root, slot, name, int(level), check_closed=check_closed)
                show_cars(root, slot)
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
                print('Garage upgrades may also affect handling. In-game acceptance is not verified; iCloud may replace edits.')
                if int(level) > 3:
                    print('Experimental level: the game may cap or ignore levels 4–5. Increased speed is not verified.')
            elif re.match(r'^(?:maxfire|fire\s+max)$', line, re.I):
                backup = saves.max_fire_station(root, backup_root, slot, check_closed=check_closed)
                print(f"Fire station maxed! Funding 500k+, Junior Battalion Chief rank (8/8), and all upgrades maxed in slot {slot}!")
                print('Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
                show_status(root, slot)
                print('Saved and verified locally. Reopen Sneaky Sasquatch to test.')
            elif re.match(r'^(?:fire|ff)\s+rank(?:\s|$)', line, re.I):
                match = re.fullmatch(r'(?:fire|ff)\s+rank\s+([1-8])', line, re.I)
                if not match:
                    raise saves.ModError('Use fire rank 1 to fire rank 8 (8 is Junior Battalion Chief).')
                level = int(match.group(1))
                backup = saves.set_firefighter_level(root, backup_root, slot, level, check_closed=check_closed)
                rank_name = saves.FIREFIGHTER_RANKS[level]
                print(f'Firefighter rank set to {rank_name} (Level {level}/8).' + (' (Max Level)' if level == 8 else ''))
                print('Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
                show_status(root, slot)
                print('Saved and verified locally. Reopen Sneaky Sasquatch to test.')
            elif re.match(r'^(?:ff|funding|fire)\s*(?:=|equals)\s*(.+)', line, re.I):
                match = re.fullmatch(r'(?:ff|funding|fire)\s*(?:=|equals)\s*(.+)', line, re.I)
                amt = parse_amount(match.group(1))
                backup = saves.set_firefighter_funding(root, backup_root, slot, amt, check_closed=check_closed)
                print(f'Firefighter funding set to {amt:,} in slot {slot}.')
                print('Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
                show_status(root, slot)
                print('Saved and verified locally. Reopen Sneaky Sasquatch to test.')
            elif re.match(r'^(?:jd|doctor)(?:\s|$)', line, re.I):
                match = re.fullmatch(r'(?:jd|doctor)(?:\s+([1-4]))?', line, re.I)
                if not match:
                    raise saves.ModError('Use JD (for max level) or JD 1 to JD 4.')
                lvl_str = match.group(1)
                level = int(lvl_str) if lvl_str else 4
                backup = saves.set_doctor_level(root, backup_root, slot, level, check_closed=check_closed)
                title = saves.DOCTOR_RANKS[level]
                print(f'Doctor rank set to {title} (Level {level}/4).' + (' (Max Level)' if level == 4 else ''))
                print('Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
                show_status(root, slot)
                print('Saved and verified locally. Reopen Sneaky Sasquatch to test.')
            else:
                match = re.fullmatch(r'([a-z]+)\s*(?:=|equals)\s*(.+)', line, re.I)
                if not match:
                    raise saves.ModError('Use T = 1000, C = 4444, own = sportscar, JD, or C/O for menus.')
                key, text = match.groups()
                key = ALIASES.get(key.lower(), key.lower())
                if key == 'own':
                    backup = saves.own_car(root, backup_root, slot, text.strip(), check_closed=check_closed)
                    show_cars(root, slot)
                else:
                    if key not in CURRENCIES:
                        raise saves.ModError('Unknown resource. Type help for supported commands.')
                    value = parse_amount(text)
                    label, field = CURRENCIES[key]
                    kwargs = {'coins': value} if key == 'c' else {'bank': value} if key == 'b' else {'currency_updates': {field: value}}
                    backup = saves.apply(root, backup_root, check_closed=check_closed, slot_number=slot, **kwargs)
                    _, _, actual = saves.read_save(root, slot)
                    print(f'{label} = {actual.get(field, 0):,}')
                show_status(root, slot)
                print('Saved and verified locally. Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
                print('Save metadata (timestamp & save counter) updated to prevent iCloud cloud-save reverts.')
        except (saves.ModError, OSError, ValueError) as e:
            print('Stopped:', e)

def main(argv=None, root=saves.ROOT, package=saves.PACKAGE, check_closed=saves.require_closed, read=input):
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0].lower() in ('jd', 'doctor'):
        args_list.pop(0)
        target_slot = None
        target_level = 4
        for arg in args_list:
            if arg.isdigit():
                val = int(arg)
                if val in (1, 2, 3) and target_slot is None:
                    target_slot = val
                elif 1 <= val <= 4:
                    target_level = val
        if target_slot is None:
            target_slot = saves.find_doctor_slot(root)
        try:
            with (package / '.slot3-mod.lock').open('a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise saves.ModError('Another Sasquatch editor is open. Exit it first.')
                backup = saves.set_doctor_level(root, package / 'console-backups', target_slot, target_level, check_closed=check_closed)
                title = saves.DOCTOR_RANKS[target_level]
                print(f'Slot {target_slot}: Doctor rank set to {title} (Level {target_level}/4).' + (' (Max Level)' if target_level == 4 else ''))
                print('Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
                show_status(root, target_slot)
                print('Saved and verified locally. Open Sneaky Sasquatch to play as ' + title + '!')
                return 0
        except (saves.ModError, OSError, ValueError) as e:
            print('Stopped:', e, file=sys.stderr)
            return 1

    if args_list and args_list[0].lower() in ('maxfire', 'fire', 'ff'):
        cmd = args_list.pop(0).lower()
        target_slot = None
        for arg in list(args_list):
            if arg.isdigit() and int(arg) in (1, 2, 3) and target_slot is None:
                target_slot = int(arg)
                args_list.remove(arg)
        if target_slot is None:
            target_slot = saves.find_doctor_slot(root)
        try:
            with (package / '.slot3-mod.lock').open('a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise saves.ModError('Another Sasquatch editor is open. Exit it first.')
                if cmd == 'maxfire' or (args_list and args_list[0].lower() == 'max'):
                    backup = saves.max_fire_station(root, package / 'console-backups', target_slot, check_closed=check_closed)
                    print(f'Slot {target_slot}: Fire station maxed out (500k+ funding, Junior Battalion Chief, all upgrades maxed)!')
                elif args_list and args_list[0].lower() in ('funding', 'fund'):
                    amt = parse_amount(args_list[1] if len(args_list) > 1 else '500k')
                    backup = saves.set_firefighter_funding(root, package / 'console-backups', target_slot, amt, check_closed=check_closed)
                    print(f'Slot {target_slot}: Firefighter funding set to {amt:,}!')
                elif args_list and args_list[0].lower() in ('rank', 'lvl', 'level'):
                    lvl = int(args_list[1]) if len(args_list) > 1 else 8
                    backup = saves.set_firefighter_level(root, package / 'console-backups', target_slot, lvl, check_closed=check_closed)
                    print(f'Slot {target_slot}: Firefighter rank set to {saves.FIREFIGHTER_RANKS[lvl]} (Level {lvl}/8)!')
                else:
                    backup = saves.max_fire_station(root, package / 'console-backups', target_slot, check_closed=check_closed)
                    print(f'Slot {target_slot}: Fire station maxed out!')
                print('Backup: ' + str(backup) if backup else 'Already set; nothing changed.')
                show_status(root, target_slot)
                return 0
        except (saves.ModError, OSError, ValueError) as e:
            print('Stopped:', e, file=sys.stderr)
            return 1

    cleaned = [a.lower() for a in args_list]
    target_slot = None
    if cleaned in ([], ['s'], ['slot']):
        print('\nSelect Sneaky Sasquatch Slot:')
        print('  1: Slot 1')
        print('  2: Slot 2')
        print('  3: Slot 3')
        try:
            choice = read('Choose slot (1-3) [default: 1]: ').strip()
            target_slot = int(choice) if choice in ('1', '2', '3') else 1
        except (EOFError, KeyboardInterrupt):
            return 0
    elif len(cleaned) == 1 and cleaned[0] in ('1', '2', '3'):
        target_slot = int(cleaned[0])
    elif len(cleaned) == 2 and cleaned[0] in ('s', 'slot') and cleaned[1] in ('1', '2', '3'):
        target_slot = int(cleaned[1])

    if target_slot is None:
        parser = argparse.ArgumentParser(description='Open a Sasquatch slot console: ss s 1, ss s 2, or ss s 3')
        parser.add_argument('selector', type=str.upper, choices=['S'], help='S means slot')
        parser.add_argument('slot', type=int, choices=[1, 2, 3])
        args = parser.parse_args(args_list)
        target_slot = args.slot

    try:
        with (package / '.slot3-mod.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise saves.ModError('Another Sasquatch editor is open. Exit it first.')
            session(target_slot, root=root, package=package, read=read, check_closed=check_closed)
    except (saves.ModError, OSError, ValueError) as e:
        print('Stopped:', e, file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
