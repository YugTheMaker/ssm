#!/usr/bin/env python3
"""Save-editing backend; this module's CLI defaults to and stays on slot 3."""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import string
import subprocess
import sys
import tempfile

ROOT = Path.home() / 'Library/Containers/com.rac7.SneakySasquatchMac/Data/Library/Application Support/com.rac7.SneakySasquatchMac'
PACKAGE = Path(__file__).resolve().parent.parent
MAX_TOTAL = 2_000_000_000
EDITABLE_DOCUMENTS = (
    'sasquatch.stuff', 'variables.stuff', 'equipment.stuff', 'achievements.stuff',
    'birds.stuff', 'bldg.stuff', 'photos.stuff',
)

class ModError(Exception):
    pass

def digest(data):
    return hashlib.sha256(data).hexdigest()

def require_closed():
    p = subprocess.run(['/usr/bin/pgrep', '-x', 'Sasquatch'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode == 0:
        raise ModError('Sasquatch is running. Save and quit it with Command+Q, then retry your command or click Refresh. Nothing was changed.')
    if p.returncode != 1:
        raise ModError('Could not check whether the game is running; refusing to edit.')

def unique_object(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ModError('Duplicate save keys; refusing to edit.')
        d[k] = v
    return d

def slot_path(root, slot_number):
    if type(slot_number) is not int or slot_number not in (1, 2, 3):
        raise ModError('Choose slot 1, 2, or 3.')
    if slot_number == 1:
        if (root / 'default').is_dir():
            return root / 'default'
        return root
    return root / ('default' + str(slot_number))

def read_save(root, slot_number=3):
    slot = slot_path(root, slot_number)
    f = slot / 'sasquatch.stuff'
    if slot.is_symlink() or f.is_symlink() or not f.is_file():
        raise ModError(f'A normal save file for slot {slot_number} was not found. Create that slot in the game first.')
    if f.resolve().parent != slot_path(root.resolve(), slot_number):
        raise ModError('Unexpected slot path; refusing to edit.')
    raw = f.read_bytes()
    try:
        d = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError) as e:
        raise ModError('This save format is not supported.') from e
    if not isinstance(d, dict) or type(d.get('VERSION')) is not int or d.get('VERSION') not in (1, 2):
        raise ModError('This does not match the inspected version-1 or version-2 currency save format.')
    if 'coins' in d:
        if type(d.get('coins', 0)) is not int:
            raise ModError('Unexpected wallet balance format.')
    elif not isinstance(d.get('current_map'), str) or not isinstance(d.get('map_locations'), dict):
        raise ModError('Missing wallet field in an unrecognized save layout.')
    # Fresh version-2 saves omit an unset wallet. Do not insert it during reads.
    if 'bankcoin' in d and type(d['bankcoin']) is not int:
        raise ModError('Unexpected bank balance format.')
    return f, raw, d

def atomic_replace(f, expected, updated):
    if f.read_bytes() != expected:
        raise ModError('The save changed during preparation; nothing was overwritten.')
    fd, tmp = tempfile.mkstemp(prefix='.ssm-', dir=f.parent)
    try:
        os.fchmod(fd, f.stat().st_mode & 0o777)
        with os.fdopen(fd, 'wb') as out:
            out.write(updated)
            out.flush()
            os.fsync(out.fileno())
        if f.read_bytes() != expected:
            raise ModError('The save changed; refusing to overwrite it.')
        os.replace(tmp, f)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def apply(root, backup_root, coins=None, bank=None, check_closed=require_closed, *, slot_number=3, currency_updates=None):
    check_closed()
    f, original, d = read_save(root, slot_number)
    changed = dict(d)
    for key, value in [('coins', coins), ('bankcoin', bank)]:
        if value is not None:
            if type(value) is not int or not -MAX_TOTAL <= value <= MAX_TOTAL:
                raise ModError('Balances must be whole numbers from -2,000,000,000 to 2,000,000,000.')
            changed[key] = value
    for key, value in (currency_updates or {}).items():
        if key not in EXTRA_CURRENCIES:
            raise ModError('Unsupported currency field.')
        if type(value) is not int or not -MAX_TOTAL <= value <= MAX_TOTAL:
            raise ModError('Currency must be a whole number from -2 billion to 2 billion.')
        if key in d and type(d[key]) is not int:
            raise ModError('Unexpected currency save format.')
        changed[key] = value
    if changed.get('coins', 0) + changed.get('bankcoin', 0) > MAX_TOTAL:
        raise ModError('Keep wallet plus bank at or below 2 billion to avoid integer overflow.')
    if changed.get('coins', 0) + changed.get('bankcoin', 0) < -MAX_TOTAL:
        raise ModError('Keep wallet plus bank at or above -2 billion to avoid integer overflow.')
    if changed == d:
        return None
    return commit_document(root, backup_root, slot_number, f, original, changed, check_closed)

def commit_document(root, backup_root, slot_number, f, original, changed, check_closed):
    check_closed()
    target_folder = slot_path(root, slot_number)
    try:
        rel_to_slot = f.resolve().relative_to(target_folder.resolve())
    except ValueError:
        raise ModError('Unexpected save target.')
    if f.is_symlink() or f.suffix != '.stuff':
        raise ModError('Unexpected save target.')
    d = json.loads(original, object_pairs_hook=unique_object)
    # Exclude other slots and old game backups
    excluded = {'default', 'default2', 'default3', 'backups'} if target_folder == root else {'backups'}
    entries = [p for p in target_folder.iterdir() if p.name not in excluded]
    for entry in entries:
        if entry.is_symlink() or (entry.is_dir() and any(p.is_symlink() for p in entry.rglob('*'))):
            raise ModError('The selected slot contains a symlink; refusing an incomplete backup.')
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = backup_root / stamp
    destination = backup / ('default' + str(slot_number))
    destination.mkdir(parents=True, exist_ok=False)
    for entry in entries:
        if entry.is_dir():
            shutil.copytree(entry, destination / entry.name)
        else:
            shutil.copy2(entry, destination / entry.name)
    if (destination / rel_to_slot).read_bytes() != original:
        raise ModError('Save changed during backup; no edit was made.')
    updated = (json.dumps(changed, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
    manifest = {'slot': slot_number, 'file': str(f.relative_to(root)), 'before_sha256': digest(original),
                'after_sha256': digest(updated), 'before': {k: d.get(k) for k in changed if isinstance(d, dict) and changed[k] != d.get(k)},
                'after': {k: changed[k] for k in changed if isinstance(d, dict) and changed[k] != d.get(k)}}
    (backup / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    check_closed()
    atomic_replace(f, original, updated)
    if f.read_bytes() != updated:
        raise ModError('Could not verify the edited file. Backup: ' + str(backup))
    # Preserve the older slot 1 layout's legacy mirror.
    if slot_number == 1 and f.parent != root and (root / f.name).is_file() and not (root / f.name).is_symlink():
        try:
            (root / f.name).write_bytes(updated)
        except OSError:
            pass
    touch_user_metadata(target_folder, root, slot_number)
    return backup

def touch_user_metadata(folder, root, slot_number):
    """Keep user.stuff in sync with local modifications so Sneaky Sasquatch's
    cloud conflict sync (CCS) recognizes the local save as newer and does not
    auto-advance/revert to older iCloud saves."""
    user_files = [folder / 'user.stuff']
    if slot_number == 1 and folder != root:
        user_files.append(root / 'user.stuff')
    now_ts = int(datetime.datetime.now().timestamp())
    for ufile in user_files:
        if ufile.is_file() and not ufile.is_symlink():
            try:
                raw_u = ufile.read_bytes()
                u_data = json.loads(raw_u, object_pairs_hook=unique_object)
                if isinstance(u_data, dict):
                    prev_st = u_data.get('st', 0)
                    u_data['st'] = max(now_ts, prev_st + 10)
                    new_sc = u_data.get('sc', 0) + 10
                    u_data['sc'] = new_sc
                    lst = u_data.get('lst')
                    if lst and isinstance(u_data.get('gert'), dict):
                        u_data['gert'][lst] = new_sc
                    updated_u = (json.dumps(u_data, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
                    atomic_replace(ufile, raw_u, updated_u)
            except Exception:
                pass

def undo(root, backup, check_closed=require_closed, *, slot_number=3):
    check_closed()
    manifest = json.loads((backup / 'manifest.json').read_text())
    target_folder = slot_path(root, slot_number)
    allowed = {str((target_folder / name).relative_to(root)): name for name in (*EDITABLE_DOCUMENTS, 'lfs.stuff')}
    manifest_file = manifest.get('file', '')
    name = allowed.get(manifest_file)
    if not name:
        base_name = Path(manifest_file).name
        if manifest_file == base_name and base_name in allowed.values():
            name = base_name
        else:
            raise ModError('Unexpected backup target.')
    if name == 'sasquatch.stuff':
        f, current, _ = read_save(root, slot_number)
    elif name == 'equipment.stuff':
        f, current, _ = read_equipment(root, slot_number)
    elif name == 'variables.stuff':
        f, current, _ = read_variables(root, slot_number)
    else:
        f, current, _ = read_json_document(root, slot_number, name)
    original = (backup / ('default' + str(slot_number)) / name).read_bytes()
    if manifest.get('slot') != slot_number or digest(original) != manifest.get('before_sha256'):
        raise ModError('Backup verification failed.')
    if digest(current) != manifest.get('after_sha256'):
        raise ModError('The game has changed this save since the mod. Automatic undo stopped to avoid overwriting newer progress. Your slot backup is still available at ' + str(backup))
    check_closed()
    atomic_replace(f, current, original)
    if slot_number == 1 and f.parent != root and (root / f.name).is_file() and not (root / f.name).is_symlink():
        try:
            (root / f.name).write_bytes(original)
        except OSError:
            pass
    touch_user_metadata(target_folder, root, slot_number)
    (backup / 'undone').touch()


def reject_json_constant(value):
    raise ModError(f'{value} is not a valid JSON value.')


def read_json_document(root, slot_number, name):
    folder = slot_path(root, slot_number)
    f = folder / name
    if folder.is_symlink() or f.is_symlink() or not f.is_file():
        raise ModError(f'{name} is unavailable in slot {slot_number}.')
    raw = f.read_bytes()
    d = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_json_constant)
    if not isinstance(d, dict):
        raise ModError(f'{name} must contain a JSON object.')
    return f, raw, d


def read_editable_document(root, slot_number, name):
    if name not in EDITABLE_DOCUMENTS:
        raise ModError('Choose a supported save file.')
    return read_json_document(root, slot_number, name)


def set_document_field(root, backup_root, slot_number, name, key, value_text, revision, check_closed):
    if not isinstance(key, str) or not key.strip() or key == 'VERSION':
        raise ModError('Enter a field name other than VERSION.')
    if not isinstance(value_text, str):
        raise ModError('Enter a JSON value.')
    check_closed()
    read_save(root, slot_number)
    f, raw, d = read_editable_document(root, slot_number, name)
    if revision != digest(raw):
        raise ModError('This file changed. Reload it before saving.')
    value = json.loads(value_text, object_pairs_hook=unique_object, parse_constant=reject_json_constant)
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    encoded.encode('utf-8')
    if key in d and d[key] is not None and type(value) is not type(d[key]):
        if not (type(value) in (int, float) and type(d[key]) in (int, float)):
            raise ModError('Use the same JSON type as the existing field.')

    changed = dict(d)
    changed[key] = value
    if name == 'sasquatch.stuff':
        balances = [changed.get(k, 0) for k in ('coins', 'bankcoin', *EXTRA_CURRENCIES)]
        if any(type(v) is not int or abs(v) > MAX_TOTAL for v in balances) or abs(sum(balances[:2])) > MAX_TOTAL:
            raise ModError('Currency values and the combined wallet and bank must be whole numbers within ±2 billion.')
        if not isinstance(changed.get('togtool', {}), dict):
            raise ModError('togtool must be a JSON object.')
    elif name == 'equipment.stuff':
        vehicles = changed.get('vehicles')
        if not isinstance(vehicles, list) or any(not isinstance(v, dict) or not isinstance(v.get('id'), str) for v in vehicles):
            raise ModError('Each vehicle needs a text id.')
        if not isinstance(changed.get('equipment', []), list):
            raise ModError('equipment must be a JSON array.')
    elif name == 'variables.stuff' and not isinstance(changed.get('flags'), dict):
        raise ModError('flags must be a JSON object.')

    if key in d and encoded == json.dumps(d[key], ensure_ascii=False):
        return None
    return commit_document(root, backup_root, slot_number, f, raw, changed, check_closed)

# Verified against Currency ScriptableObjects in installed resources.assets (2.2/993).
EXTRA_CURRENCIES = {'ptkt', 'lumber', 'cf', 'pap', 'pb', 'tb', 'st', 'hwcd', 'xmcc', '4o'}
BASIC_CARS = {'car', 'sportscar', 'pickupTruck', 'golfcart', 'supercar', 'polcar'}
LEVEL_CARS = BASIC_CARS | {'gokart'}

ALL_VEHICLES = {
    # Cars & Sports
    'car': {'id': 'car', 'name': 'Compact Car', 'category': 'Cars', 'template': {'id': 'car', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': 'FF6666'}},
    'sportscar': {'id': 'sportscar', 'name': 'Sports Car', 'category': 'Cars', 'template': {'id': 'sportscar', 'lvl': 2, 'm': [{'d': 'XE', 'e': 1}, {'d': 'qr'}, {'d': 'af'}], 'color': 'DF595B'}},
    'supercar': {'id': 'supercar', 'name': 'Super Car', 'category': 'Cars', 'template': {'id': 'supercar', 'lvl': 2, 'm': [{'d': 'MP'}, {'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    'pickupTruck': {'id': 'pickupTruck', 'name': 'Pickup Truck', 'category': 'Trucks', 'template': {'id': 'pickupTruck', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': 'FF6666'}},
    'gokart': {'id': 'gokart', 'name': 'Go-Kart', 'category': 'Cars', 'template': {'id': 'gokart', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    'golfcart': {'id': 'golfcart', 'name': 'Golf Cart', 'category': 'Cars', 'template': {'id': 'golfcart', 'lvl': 0, 'm': [{'d': 'qr'}, {'d': 'af'}]}},
    'polcar': {'id': 'polcar', 'name': 'Police Car', 'category': 'Emergency', 'template': {'id': 'polcar', 'lvl': 1, 'm': [{'d': 'F8', 'e': 1}, {'d': '1V', 'e': 1}, {'d': 'qr'}, {'d': 'af'}], 'color': 'DD8358'}},
    'j7': {'id': 'j7', 'name': 'Taxi', 'category': 'Cars', 'template': {'id': 'j7', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    'Jo': {'id': 'Jo', 'name': '4x4 Truck', 'category': 'Trucks', 'template': {'id': 'Jo', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    'Ow': {'id': 'Ow', 'name': 'ATV (Quad)', 'category': 'Off-Road', 'template': {'id': 'Ow', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    
    # Snowmobile / Winter
    'VL': {'id': 'VL', 'name': 'Snowmobile', 'category': 'Winter', 'template': {'id': 'VL', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    '5J': {'id': '5J', 'name': 'Snowmobile (Ranger)', 'category': 'Winter', 'template': {'id': '5J', 'lvl': 0, 'm': [{'d': 'qr'}, {'d': 'af'}]}},
    
    # Bikes & Motorcycles
    'JE': {'id': 'JE', 'name': 'Dirt Bike', 'category': 'Bikes', 'template': {'id': 'JE', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    'pH': {'id': 'pH', 'name': 'Sport Bike', 'category': 'Bikes', 'template': {'id': 'pH', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    'kp': {'id': 'kp', 'name': 'Motorcycle', 'category': 'Bikes', 'template': {'id': 'kp', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    'Jy': {'id': 'Jy', 'name': 'Chopper', 'category': 'Bikes', 'template': {'id': 'Jy', 'lvl': 0, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    'Xw': {'id': 'Xw', 'name': 'Bicycle', 'category': 'Bikes', 'template': {'id': 'Xw', 'lvl': 0, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    'Ae': {'id': 'Ae', 'name': 'Scooter', 'category': 'Bikes', 'template': {'id': 'Ae', 'lvl': 0, 'm': [{'d': 'qr'}, {'d': 'af'}]}},
    
    # Boats & Water
    'xD': {'id': 'xD', 'name': 'Boatercycle (Jetski)', 'category': 'Boats', 'template': {'id': 'xD', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    'OF': {'id': 'OF', 'name': 'Speed Boat', 'category': 'Boats', 'template': {'id': 'OF', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': 'FFFFFF'}},
    'As': {'id': 'As', 'name': 'Motor Boat', 'category': 'Boats', 'template': {'id': 'As', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    'zk': {'id': 'zk', 'name': 'Inflatable Boat', 'category': 'Boats', 'template': {'id': 'zk', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': 'FF6666'}},
    'canoe': {'id': 'canoe', 'name': 'Canoe', 'category': 'Boats', 'template': {'id': 'canoe', 'lvl': 0, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': 'FF6060'}},
    '1b': {'id': '1b', 'name': 'Innertube', 'category': 'Boats', 'template': {'id': '1b', 'lvl': 0, 'm': [{'d': 'qr'}, {'d': 'af'}]}},
    'vX': {'id': 'vX', 'name': 'Ferry', 'category': 'Boats', 'template': {'id': 'vX', 'lvl': 0, 'm': [{'d': 'qr'}, {'d': 'af'}]}},

    # Commercial & Service
    'dj': {'id': 'dj', 'name': 'Forklift', 'category': 'Industrial', 'template': {'id': 'dj', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    'ZL': {'id': 'ZL', 'name': 'Tractor', 'category': 'Industrial', 'template': {'id': 'ZL', 'lvl': 0, 'm': [{'d': 'qr'}, {'d': 'af'}]}},
    'deliveryVan': {'id': 'deliveryVan', 'name': 'Delivery Van', 'category': 'Commercial', 'template': {'id': 'deliveryVan', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    'Xe': {'id': 'Xe', 'name': 'Van', 'category': 'Commercial', 'template': {'id': 'Xe', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    'ux': {'id': 'ux', 'name': 'Bus', 'category': 'Commercial', 'template': {'id': 'ux', 'lvl': 0, 'm': [{'d': 'qr'}, {'d': 'af'}]}},

    # Emergency
    'J1': {'id': 'J1', 'name': 'Ambulance', 'category': 'Emergency', 'template': {'id': 'J1', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}]}},
    'aS': {'id': 'aS', 'name': 'Fire Engine', 'category': 'Emergency', 'template': {'id': 'aS', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'}},
    'Ek': {'id': 'Ek', 'name': 'Mini Pumper', 'category': 'Emergency', 'template': {'id': 'Ek', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}]}},
}

CAR_NAMES = {
    # Basic aliases
    'sports car': 'sportscar',
    'super car': 'supercar',
    'pickup truck': 'pickupTruck',
    'pickup': 'pickupTruck',
    'truck': 'pickupTruck',
    'golf cart': 'golfcart',
    'police car': 'polcar',
    'police': 'polcar',
    'cop car': 'polcar',
    'go-kart': 'gokart',
    'go kart': 'gokart',
    'kart': 'gokart',
    'compact': 'car',
    'sedan': 'car',
    # Snowmobile / user's "slow mobile"
    'snowmobile': 'VL',
    'snow mobile': 'VL',
    'slow mobile': 'VL',
    'slowmobile': 'VL',
    'snowmobile ranger': '5J',
    'ranger snowmobile': '5J',
    # 4x4 / ATV
    '4x4': 'Jo',
    'jeep': 'Jo',
    '4x4 truck': 'Jo',
    'atv': 'Ow',
    'quad': 'Ow',
    # Bikes
    'dirt bike': 'JE',
    'dirtbike': 'JE',
    'sport bike': 'pH',
    'sportbike': 'pH',
    'motorcycle': 'kp',
    'bike': 'kp',
    'chopper': 'Jy',
    'bicycle': 'Xw',
    'scooter': 'Ae',
    # Boats
    'boatercycle': 'xD',
    'jetski': 'xD',
    'jet ski': 'xD',
    'speed boat': 'OF',
    'speedboat': 'OF',
    'motor boat': 'As',
    'motorboat': 'As',
    'inflatable boat': 'zk',
    'inflatable': 'zk',
    'canoe': 'canoe',
    'innertube': '1b',
    'tube': '1b',
    'ferry': 'vX',
    # Industrial & Commercial
    'forklift': 'dj',
    'tractor': 'ZL',
    'delivery van': 'deliveryVan',
    'van': 'Xe',
    'bus': 'ux',
    'taxi': 'j7',
    # Emergency
    'ambulance': 'J1',
    'fire engine': 'aS',
    'fire truck': 'aS',
    'firetruck': 'aS',
    'mini pumper': 'Ek',
}

def set_car_level(root, backup_root, slot_number, identifier, level, check_closed=require_closed):
    """Set a stored garage level; levels 4–5 are experimental, not proven speeds."""
    check_closed()
    if type(level) is not int or not 1 <= level <= 5:
        raise ModError('Car level must be a whole number from 1 to 5.')
    name = ' '.join(identifier.lower().split())
    all_lvl_cars = LEVEL_CARS | {k for k, v in ALL_VEHICLES.items() if 'lvl' in v.get('template', {})}
    identifier = CAR_NAMES.get(name, {v.lower(): v for v in all_lvl_cars}.get(name))
    if identifier is None:
        raise ModError('Supported cars: ' + ', '.join(sorted(LEVEL_CARS)))
    read_save(root, slot_number)
    f, raw, data = read_equipment(root, slot_number)
    matches = [v for v in data['vehicles'] if v['id'] == identifier]
    if len(matches) != 1:
        raise ModError('This slot must own exactly one matching car. Type cars to list owned cars.')
    vehicle = matches[0]
    current = vehicle.get('lvl', 0)
    if type(current) is not int or not 0 <= current <= 4:
        raise ModError('Unsupported existing car upgrade level; nothing changed.')
    if current == level - 1:
        return None
    changed = json.loads(raw)
    next(v for v in changed['vehicles'] if v['id'] == identifier)['lvl'] = level - 1
    return commit_document(root, backup_root, slot_number, f, raw, changed, check_closed)

def read_equipment(root, slot_number):
    folder = slot_path(root, slot_number)
    f = folder / 'equipment.stuff'
    if folder.is_symlink() or f.is_symlink() or not f.is_file():
        raise ModError('No supported equipment save for this slot.')
    raw = f.read_bytes()
    d = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(d, dict) or d.get('VERSION', 1) != 1 or not isinstance(d.get('vehicles'), list):
        raise ModError('Unsupported vehicle save format.')
    if any(not isinstance(v, dict) or not isinstance(v.get('id'), str) for v in d['vehicles']):
        raise ModError('Unsupported vehicle record.')
    return f, raw, d

def read_variables(root, slot_number):
    folder = slot_path(root, slot_number)
    f = folder / 'variables.stuff'
    if folder.is_symlink() or f.is_symlink() or not f.is_file():
        raise ModError(f'No supported variables save for slot {slot_number}.')
    raw = f.read_bytes()
    d = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(d, dict) or not isinstance(d.get('flags'), dict):
        raise ModError('Unsupported variables save format.')
    return f, raw, d

DOCTOR_RANKS = {
    1: 'Junior Doctor',
    2: 'Doctor',
    3: 'Senior Doctor',
    4: 'Junior Head Doctor',
}

def set_doctor_level(root, backup_root, slot_number, level=4, check_closed=require_closed):
    """Set the doctor job level (1: Junior Doctor, 2: Doctor, 3: Senior Doctor, 4: Junior Head Doctor / max rank)."""
    check_closed()
    if type(level) is not int or not 1 <= level <= 4:
        raise ModError('Doctor level must be a whole number from 1 to 4 (1: Junior Doctor, 2: Doctor, 3: Senior Doctor, 4: Junior Head Doctor).')
    read_save(root, slot_number)
    f, raw, data = read_variables(root, slot_number)
    current_stored = data.get('sR', -1)
    target_stored = level - 1
    flags = dict(data.get('flags', {}))
    if current_stored == target_stored and flags.get('BZ') == 1 and (level != 4 or (flags.get('Jv') == 0 and data.get('UA') == 0)):
        return None
    changed = dict(data)
    changed['sR'] = target_stored
    flags['BZ'] = 1  # Medical Diploma
    if level == 4:
        flags['Jv'] = 0  # No promotion pending
        changed['UA'] = 0  # Max level progress
    changed['flags'] = flags
    return commit_document(root, backup_root, slot_number, f, raw, changed, check_closed)

def find_doctor_slot(root):
    """Find the best slot for doctor modifications (prefers slot with doctor progress, then slot 2, then slot 1)."""
    candidates = []
    for s in (2, 1, 3):
        try:
            _, _, vdata = read_variables(root, s)
            if 'sR' in vdata:
                return s
            candidates.append(s)
        except Exception:
            pass
    return candidates[0] if candidates else 2

FIREFIGHTER_RANKS = {
    1: 'Probationary Firefighter',
    2: 'Junior Firefighter',
    3: 'Firefighter',
    4: 'Junior Lieutenant',
    5: 'Lieutenant',
    6: 'Junior Captain',
    7: 'Captain',
    8: 'Junior Battalion Chief',
}

FIRE_UPGRADES_MAX = {
    'wa': 1,  # Arcade Game
    'BN': 1,  # Bed
    'po': 1,  # Fire Engine Water Cannon
    '8T': 2,  # Fire Engine Engine
    'R9': 4,  # Fire Engine Water Tank
    'ni': 3,  # Fire Engine Hoses
    'cO': 3,  # Fire Engine Water Pump
    'wH': 4,  # Firefighter Jacket (Protection)
    'YK': 3,  # Oxygen Tank
    'Oz': 5,  # Bonus Paycheck %
    'N4': 2,  # Mini Pumper Engine
    'dh': 4,  # Mini Pumper Water Tank
    'zb': 2,  # Mini Pumper Hoses
    'Xd': 3,  # Mini Pumper Water Pump
}

FIRE_UPGRADE_LABELS = {
    'wa': 'Arcade Game',
    'BN': 'Fire Station Bed',
    'po': 'Engine Water Cannon',
    '8T': 'Engine Horsepower',
    'R9': 'Engine Water Tank',
    'ni': 'Engine Hoses',
    'cO': 'Engine Water Pump',
    'wH': 'Firefighter Jacket',
    'YK': 'Oxygen Tank',
    'Oz': 'Salary Bonus %',
    'N4': 'Pumper Engine',
    'dh': 'Pumper Water Tank',
    'zb': 'Pumper Hoses',
    'Xd': 'Pumper Water Pump',
}

def get_firefighter_info(root, slot_number):
    """Return dictionary with firefighter funding, career level/rank, and equipment upgrades."""
    try:
        _, _, vdata = read_variables(root, slot_number)
    except Exception:
        return {'funding': 0, 'level': 1, 'rank': FIREFIGHTER_RANKS[1], 'upgrades': {}}
    funding = vdata.get('sM', 0)
    level_stored = vdata.get('Og', 0)
    level = level_stored + 1 if type(level_stored) is int and 0 <= level_stored <= 7 else 1
    upgrades = {}
    for k, max_v in FIRE_UPGRADES_MAX.items():
        curr = vdata.get(k, 0)
        upgrades[k] = {
            'key': k,
            'label': FIRE_UPGRADE_LABELS.get(k, k),
            'current': curr if type(curr) is int else 0,
            'max': max_v
        }
    return {
        'funding': funding if type(funding) is int else 0,
        'level': level,
        'rank': FIREFIGHTER_RANKS.get(level, f'Level {level}'),
        'upgrades': upgrades,
    }

def set_firefighter_funding(root, backup_root, slot_number, amount, check_closed=require_closed):
    """Set extra funding for the Fire Station computer app (stored in variables.stuff key 'sM')."""
    check_closed()
    if type(amount) is not int or not 0 <= amount <= MAX_TOTAL:
        raise ModError(f'Firefighter funding must be a whole number between 0 and {MAX_TOTAL:,}.')
    read_save(root, slot_number)
    f, raw, data = read_variables(root, slot_number)
    if data.get('sM') == amount:
        return None
    changed = dict(data)
    changed['sM'] = amount
    return commit_document(root, backup_root, slot_number, f, raw, changed, check_closed)

def set_firefighter_level(root, backup_root, slot_number, level=8, check_closed=require_closed):
    """Set Firefighter rank level (1: Probationary to 8: Junior Battalion Chief / max rank)."""
    check_closed()
    if type(level) is not int or not 1 <= level <= 8:
        raise ModError('Firefighter level must be a whole number from 1 to 8 (1: Probationary to 8: Junior Battalion Chief).')
    read_save(root, slot_number)
    f, raw, data = read_variables(root, slot_number)
    target_stored = level - 1
    flags = dict(data.get('flags', {}))
    if data.get('Og') == target_stored and (level != 8 or flags.get('3N') == 0):
        return None
    changed = dict(data)
    changed['Og'] = target_stored
    changed['5G'] = 0
    if level == 8:
        flags['3N'] = 0  # No promotion pending
    changed['flags'] = flags
    return commit_document(root, backup_root, slot_number, f, raw, changed, check_closed)

def max_fire_station(root, backup_root, slot_number, check_closed=require_closed):
    """Max out firefighter funding (at least 500,000), max rank (Junior Battalion Chief), and all truck & station upgrades."""
    check_closed()
    read_save(root, slot_number)
    f, raw, data = read_variables(root, slot_number)
    changed = dict(data)
    flags = dict(data.get('flags', {}))
    current_funding = data.get('sM', 0)
    changed['sM'] = max(current_funding if type(current_funding) is int else 0, 500_000)
    changed['Og'] = 7  # Junior Battalion Chief
    changed['5G'] = 0
    flags['3N'] = 0
    for k, max_v in FIRE_UPGRADES_MAX.items():
        changed[k] = max_v
    changed['flags'] = flags
    return commit_document(root, backup_root, slot_number, f, raw, changed, check_closed)

def set_custom_variable(root, backup_root, slot_number, key, value, check_closed=require_closed):
    """Set any variable in variables.stuff or its flags dictionary."""
    check_closed()
    if not isinstance(key, str) or not key.strip():
        raise ModError('Variable key cannot be empty.')
    key = key.strip()
    read_save(root, slot_number)
    f, raw, data = read_variables(root, slot_number)
    changed = dict(data)
    flags = dict(data.get('flags', {}))

    is_flag = False
    if key.startswith('flag:'):
        is_flag = True
        key = key[5:].strip()
    elif key in flags:
        is_flag = True

    if is_flag:
        if flags.get(key) == value:
            return None
        flags[key] = value
        changed['flags'] = flags
    else:
        if changed.get(key) == value:
            return None
        changed[key] = value

    return commit_document(root, backup_root, slot_number, f, raw, changed, check_closed)

def activate_running_shoes(root, backup_root, slot_number, check_closed=require_closed):
    check_closed()
    _, _, equipment = read_equipment(root, slot_number)
    items = equipment.get('equipment')
    if not isinstance(items, list) or not any(isinstance(item, dict) and item.get('type') == 2524 for item in items):
        raise ModError('Give running shoes with RS G first.')
    f, raw, data = read_save(root, slot_number)
    toggles = data.get('togtool', {})
    if not isinstance(toggles, dict) or any(type(v) is not int or v not in (0, 1) for v in toggles.values()):
        raise ModError('Unsupported tool activation format; nothing changed.')
    # Tool_RunningShoes_Level 1 has persistent tool identifier "runshoes".
    if toggles.get('runshoes') == 1:
        return None
    changed = dict(data)
    changed['togtool'] = dict(toggles, runshoes=1)
    return commit_document(root, backup_root, slot_number, f, raw, changed, check_closed)

def gift_running_shoes(root, backup_root, slot_number, check_closed=require_closed):
    # Game 2.2/993: Tool_RunningShoes_Level 1 references resources.assets
    # path ID 118914, EquipmentData "Sasquatch RunningShoes", equipment ID 2524.
    check_closed()
    read_save(root, slot_number)
    f, raw, data = read_equipment(root, slot_number)
    equipment = data.get('equipment')
    if not isinstance(equipment, list) or any(not isinstance(item, dict) or type(item.get('type')) is not int for item in equipment):
        raise ModError('Unsupported equipment ownership format; nothing changed.')
    if any(item['type'] == 2524 for item in equipment):
        return None
    changed = dict(data)
    changed['equipment'] = equipment + [{'type': 2524}]
    return commit_document(root, backup_root, slot_number, f, raw, changed, check_closed)

def gift_sneaky_shoes(root, backup_root, slot_number, check_closed=require_closed):
    # Equipment type 469: SneakBoots / Sneaking Boots ("Sneaky shoes").
    check_closed()
    read_save(root, slot_number)
    f, raw, data = read_equipment(root, slot_number)
    equipment = data.get('equipment')
    if not isinstance(equipment, list) or any(not isinstance(item, dict) or type(item.get('type')) is not int for item in equipment):
        raise ModError('Unsupported equipment ownership format; nothing changed.')
    if any(item.get('type') == 469 for item in equipment):
        return None
    changed = dict(data)
    changed['equipment'] = equipment + [{'type': 469}]
    return commit_document(root, backup_root, slot_number, f, raw, changed, check_closed)

def activate_sneaky_shoes(root, backup_root, slot_number, check_closed=require_closed):
    # Tool_RunningShoes_Sneaking has persistent tool identifier "T9".
    check_closed()
    _, _, equipment = read_equipment(root, slot_number)
    items = equipment.get('equipment', [])
    if not any(isinstance(item, dict) and item.get('type') == 469 for item in items):
        gift_sneaky_shoes(root, backup_root, slot_number, check_closed=check_closed)
    f, raw, data = read_save(root, slot_number)
    toggles = data.get('togtool', {})
    if not isinstance(toggles, dict) or any(type(v) is not int or v not in (0, 1) for v in toggles.values()):
        raise ModError('Unsupported tool activation format; nothing changed.')
    if toggles.get('T9') == 1:
        return None
    changed = dict(data)
    changed['togtool'] = dict(toggles, T9=1)
    return commit_document(root, backup_root, slot_number, f, raw, changed, check_closed)

def unlock_all_shoes(root, backup_root, slot_number, check_closed=require_closed):
    """Grant and activate Sneaky shoes, Running shoes, and Sprinting shoes all at once."""
    check_closed()
    read_save(root, slot_number)
    f_eq, raw_eq, data_eq = read_equipment(root, slot_number)
    equipment = list(data_eq.get('equipment', []))
    owned_types = {item.get('type') for item in equipment if isinstance(item, dict)}
    added = False
    for shoe_type in (2524, 469):
        if shoe_type not in owned_types:
            equipment.append({'type': shoe_type})
            added = True
    if added:
        changed_eq = dict(data_eq)
        changed_eq['equipment'] = equipment
        commit_document(root, backup_root, slot_number, f_eq, raw_eq, changed_eq, check_closed)

    f_save, raw_save, data_save = read_save(root, slot_number)
    toggles = dict(data_save.get('togtool', {}))
    toggles['runshoes'] = 1
    toggles['T9'] = 1
    toggles['SK'] = 1
    changed_save = dict(data_save)
    changed_save['togtool'] = toggles
    return commit_document(root, backup_root, slot_number, f_save, raw_save, changed_save, check_closed)

BASIC_CAR_TEMPLATES = {
    'car': {'id': 'car', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': 'FF6666'},
    'sportscar': {'id': 'sportscar', 'lvl': 2, 'm': [{'d': 'XE', 'e': 1}, {'d': 'qr'}, {'d': 'af'}], 'color': 'DF595B'},
    'supercar': {'id': 'supercar', 'lvl': 2, 'm': [{'d': 'MP'}, {'d': 'qr'}, {'d': 'af'}], 'color': '333333'},
    'pickupTruck': {'id': 'pickupTruck', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': 'FF6666'},
    'golfcart': {'id': 'golfcart', 'lvl': 0, 'm': [{'d': 'qr'}, {'d': 'af'}]},
    'polcar': {'id': 'polcar', 'lvl': 1, 'm': [{'d': 'F8', 'e': 1}, {'d': '1V', 'e': 1}, {'d': 'qr'}, {'d': 'af'}], 'color': 'DD8358'},
    'gokart': {'id': 'gokart', 'lvl': 2, 'm': [{'d': 'qr'}, {'d': 'af'}], 'color': '333333'},
}

CAR_TEMPLATES = {k: v['template'] for k, v in ALL_VEHICLES.items()}

def own_car(root, backup_root, slot_number, identifier, check_closed=require_closed):
    check_closed()
    read_save(root, slot_number)
    f, raw, data = read_equipment(root, slot_number)
    supported = {x.lower(): x for x in (BASIC_CARS | {'gokart'} | set(ALL_VEHICLES.keys()))}
    supported.update(CAR_NAMES)
    resolved_id = supported.get(identifier.lower().strip())
    if not resolved_id:
        raise ModError('Supported cars: ' + ', '.join(sorted(BASIC_CARS)))
    if any(v.get('id') == resolved_id for v in data['vehicles']):
        return None
    template = None
    for other in (1, 2, 3):
        if other == slot_number:
            continue
        try:
            _, _, source = read_equipment(root, other)
        except (ModError, OSError, ValueError):
            continue
        for vehicle in source['vehicles']:
            if vehicle.get('id') == resolved_id:
                template = vehicle
                break
        if template:
            break
    if template is None:
        if resolved_id in CAR_TEMPLATES:
            template = CAR_TEMPLATES[resolved_id]
        elif resolved_id in ALL_VEHICLES:
            template = ALL_VEHICLES[resolved_id]['template']
        else:
            raise ModError('This car must already be owned in another local slot before it can be copied.')
    if set(template) - {'id', 'lvl', 'm', 'color', 'ft'}:
        raise ModError('This car has linked/custom state; it cannot be safely copied by this version.')
    changed = dict(data)
    changed['vehicles'] = data['vehicles'] + [json.loads(json.dumps(template))]
    return commit_document(root, backup_root, slot_number, f, raw, changed, check_closed)

def own_all_cars(root, backup_root, slot_number, max_level=True, all_vehicles=True, check_closed=require_closed):
    """Grant vehicles and optionally set garage levels to maximum."""
    check_closed()
    read_save(root, slot_number)
    f, raw, data = read_equipment(root, slot_number)
    vehicles = list(data.get('vehicles', []))
    owned_ids = {v.get('id') for v in vehicles if isinstance(v, dict)}
    changed = False
    templates = CAR_TEMPLATES if all_vehicles else BASIC_CAR_TEMPLATES
    for car_id, template in templates.items():
        if car_id not in owned_ids:
            v_copy = json.loads(json.dumps(template))
            if max_level and 'lvl' in v_copy:
                v_copy['lvl'] = 2
            vehicles.append(v_copy)
            changed = True
        elif max_level:
            v = next((v for v in vehicles if v.get('id') == car_id), None)
            if v and 'lvl' in v and v.get('lvl', 0) < 2:
                v['lvl'] = 2
                changed = True
    if not changed:
        return None
    changed_data = dict(data)
    changed_data['vehicles'] = vehicles
    return commit_document(root, backup_root, slot_number, f, raw, changed_data, check_closed)

def own_all_known_vehicles(root, backup_root, slot_number, max_level=True, check_closed=require_closed):
    """Grant all 30+ vehicles in the fleet and max out levels."""
    return own_all_cars(root, backup_root, slot_number, max_level=max_level, all_vehicles=True, check_closed=check_closed)

def get_all_vehicles_status(root, slot_number):
    """Return status of all ~32 known vehicles with ownership, level, and category."""
    read_save(root, slot_number)
    f, raw, data = read_equipment(root, slot_number)
    vehicles = data.get('vehicles', [])
    owned_map = {}
    for v in vehicles:
        if isinstance(v, dict) and 'id' in v:
            owned_map[v['id']] = v

    status_list = []
    for vid, info in ALL_VEHICLES.items():
        owned = vid in owned_map
        v_data = owned_map.get(vid, {})
        lvl = v_data.get('lvl') if owned else None
        status_list.append({
            'id': vid,
            'name': info['name'],
            'category': info['category'],
            'owned': owned,
            'level': (lvl + 1) if (lvl is not None and isinstance(lvl, int)) else None,
            'color': v_data.get('color') if owned else None,
        })
    return status_list

def get_halloween_info(root, slot_number):
    """Return current Halloween event status and candy currency balance."""
    f, raw, data = read_save(root, slot_number)
    return {
        'active': bool(data.get('se_h', 0)),
        'candy': data.get('hwcd', 0)
    }

def set_halloween_event(root, backup_root, slot_number, active=True, check_closed=require_closed):
    """Enable (1) or disable (0) the Halloween seasonal event."""
    check_closed()
    f, raw, data = read_save(root, slot_number)
    new_val = 1 if active else 0
    if data.get('se_h', 0) == new_val:
        return None
    changed = dict(data)
    changed['se_h'] = new_val
    return commit_document(root, backup_root, slot_number, f, raw, changed, check_closed)

def set_halloween_candy(root, backup_root, slot_number, amount, check_closed=require_closed):
    """Set Halloween candy currency (hwcd) balance."""
    check_closed()
    if type(amount) is not int or amount < 0 or amount > MAX_TOTAL:
        raise ModError(f'Candy amount must be between 0 and {MAX_TOTAL:,}.')
    f, raw, data = read_save(root, slot_number)
    if data.get('hwcd') == amount:
        return None
    changed = dict(data)
    changed['hwcd'] = amount
    return commit_document(root, backup_root, slot_number, f, raw, changed, check_closed)

def refill_candy_bowls(root, backup_root, slot_number, check_closed=require_closed):
    """Refill and reset all Halloween candy bowls, clear alreadyCollected flags, and ensure Halloween is active."""
    check_closed()
    slot_dir = slot_path(root, slot_number)

    # 1. Ensure Halloween event is active (se_h = 1)
    f_save, raw_save, data_save = read_save(root, slot_number)
    if data_save.get('se_h', 0) != 1:
        changed_save = dict(data_save)
        changed_save['se_h'] = 1
        commit_document(root, backup_root, slot_number, f_save, raw_save, changed_save, check_closed)

    # 2. Reset day.stuff cb (coolers/boxes/candy bowls) if present
    day_file = slot_dir / 'day.stuff'
    if day_file.is_file():
        try:
            raw_day = day_file.read_bytes()
            data_day = json.loads(raw_day.decode('utf-8'))
            if data_day.get('cb') or any('candy' in str(k).lower() for k in data_day.get('cb', {})):
                data_day['cb'] = {}
                commit_document(root, backup_root, slot_number, day_file, raw_day, data_day, check_closed)
        except Exception:
            pass

    # 3. Scan map directory and reset alreadyCollected flags or candy bowl container states
    map_dir = slot_dir / 'map'
    if map_dir.is_dir():
        for mf in map_dir.glob('*.stuff'):
            try:
                raw_m = mf.read_bytes()
                data_m = json.loads(raw_m.decode('utf-8'))
                modified = False

                # Check csd (custom save data)
                if 'csd' in data_m and isinstance(data_m['csd'], dict):
                    keys_to_remove = [k for k in data_m['csd'] if 'alreadycollected' in str(k).lower() or 'candy' in str(k).lower()]
                    for k in keys_to_remove:
                        del data_m['csd'][k]
                        modified = True

                # Check objects
                if 'objects' in data_m and isinstance(data_m['objects'], list):
                    for obj in data_m['objects']:
                        if isinstance(obj, dict):
                            # Reset cD alreadyCollected
                            if 'cD' in obj and isinstance(obj['cD'], dict):
                                if 'alreadyCollected' in obj['cD']:
                                    obj['cD']['alreadyCollected'] = False
                                    modified = True
                            if 'alreadyCollected' in obj:
                                obj['alreadyCollected'] = False
                                modified = True

                if modified:
                    commit_document(root, backup_root, slot_number, mf, raw_m, data_m, check_closed)
            except Exception:
                pass
    return True

CHRISTMAS_DECORATIONS = {
    '5o': 'Candy Cane Lawn Decorations',
    '0R': 'Decorated Christmas Tree',
    'fP': 'Christmas House & Roof Lights',
    'LF': 'Snowflake Window & Wall Decorations',
    'Z3': 'Hanging Stocking Decorations',
    'w7': 'Wreath Front Door Decorations',
}

def get_christmas_info(root, slot_number):
    """Return current Christmas / Winter Holiday event status, candy cane currency balance, and decoration unlocks."""
    f_save, _, data_save = read_save(root, slot_number)
    try:
        f_var, _, data_var = read_variables(root, slot_number)
    except Exception:
        data_var = {}
    active = bool(data_save.get('se_c', 0) or data_var.get('Eq', 0))
    decorations = {
        k: {'name': name, 'unlocked': bool(data_var.get(k, 0))}
        for k, name in CHRISTMAS_DECORATIONS.items()
    }
    return {
        'active': active,
        'candyCanes': data_save.get('xmcc', 0),
        'forceToday': bool(data_var.get('Eq', 0)),
        'decorations': decorations,
    }

def set_christmas_event(root, backup_root, slot_number, active=True, check_closed=require_closed):
    """Enable (1) or disable (0) the Christmas / Winter Holiday seasonal event and force today flag."""
    check_closed()
    f_save, raw_save, data_save = read_save(root, slot_number)
    new_val = 1 if active else 0
    save_changed = (data_save.get('se_c', 0) != new_val)
    
    last_backup = None
    if save_changed:
        changed_save = dict(data_save)
        changed_save['se_c'] = new_val
        last_backup = commit_document(root, backup_root, slot_number, f_save, raw_save, changed_save, check_closed)
        
    try:
        f_var, raw_var, data_var = read_variables(root, slot_number)
        var_changed = (data_var.get('Eq', 0) != new_val)
        if var_changed:
            changed_var = dict(data_var)
            changed_var['Eq'] = new_val
            last_backup = commit_document(root, backup_root, slot_number, f_var, raw_var, changed_var, check_closed)
    except Exception:
        pass
        
    return last_backup

def set_christmas_candy_canes(root, backup_root, slot_number, amount, check_closed=require_closed):
    """Set Christmas Candy Canes currency (xmcc) balance."""
    check_closed()
    if type(amount) is not int or amount < 0 or amount > MAX_TOTAL:
        raise ModError(f'Candy Canes amount must be between 0 and {MAX_TOTAL:,}.')
    f, raw, data = read_save(root, slot_number)
    if data.get('xmcc') == amount:
        return None
    changed = dict(data)
    changed['xmcc'] = amount
    return commit_document(root, backup_root, slot_number, f, raw, changed, check_closed)

def unlock_all_christmas_decorations(root, backup_root, slot_number, check_closed=require_closed):
    """Unlock all Jack Frost Christmas decorations in variables.stuff."""
    check_closed()
    f_var, raw_var, data_var = read_variables(root, slot_number)
    changed = False
    new_data = dict(data_var)
    for k in CHRISTMAS_DECORATIONS:
        if new_data.get(k) != 1:
            new_data[k] = 1
            changed = True
    if not changed:
        return None
    return commit_document(root, backup_root, slot_number, f_var, raw_var, new_data, check_closed)

def max_christmas(root, backup_root, slot_number, check_closed=require_closed):
    """Enable Christmas event, grant 2,000,000 Candy Canes, and unlock all decorations."""
    check_closed()
    b1 = set_christmas_event(root, backup_root, slot_number, active=True, check_closed=check_closed)
    b2 = set_christmas_candy_canes(root, backup_root, slot_number, 2_000_000, check_closed=check_closed)
    b3 = unlock_all_christmas_decorations(root, backup_root, slot_number, check_closed=check_closed)
    return b3 or b2 or b1

ALL_BADGE_CODES = [
    '0M', '13', '1D', '1g', '2K', '2o', '45', '5l', '6R', '6X', '6b', '75', '7u', '8V', '8p', '8z',
    'AE', 'By', 'EX', 'FL', 'GN', 'Gw', 'Ju', 'Kl', 'LG', 'MM', 'NK', 'Ol', 'Pc', 'QV', 'Qi', 'Rm',
    'Rw', 'Sf', 'Te', 'Tp', 'Ue', 'Us', 'Vu', 'Wi', 'Xy', 'YR', 'aS', 'bC', 'bG', 'c4', 'cL', 'dH',
    'fC', 'fY', 'gp', 'hb', 'i8', 'k2', 'kA', 'kN', 'lq', 'ls', 'm1', 'mM', 'oE', 'oU', 'pD', 'qq',
    'rX', 'rk', 's4', 'sR', 't9', 'tl', 'to', 'tu', 'vu', 'wR', 'wS', 'wv', 'wy', 'x2', 'y0', 'zv'
]

def read_achievements(root, slot_number):
    """Read achievements.stuff document for slot."""
    slot = slot_path(root, slot_number)
    f = slot / 'achievements.stuff'
    if not f.is_file():
        return f, b'{}', {'VERSION': 1, 'eb': [], 'qb': []}
    raw = f.read_bytes()
    d = json.loads(raw.decode('utf-8'))
    return f, raw, d

def get_raccoon_club_info(root, slot_number):
    """Return Raccoon Club unlock state, badge currency balance, and earned badges count."""
    f_save, _, data_save = read_save(root, slot_number)
    try:
        f_var, _, data_var = read_variables(root, slot_number)
    except Exception:
        data_var = {}
    try:
        _, _, data_ach = read_achievements(root, slot_number)
    except Exception:
        data_ach = {'eb': [], 'qb': []}
        
    earned_badges = data_ach.get('eb', [])
    stored_badges = data_save.get('4o')
    badge_count = stored_badges if isinstance(stored_badges, int) else len(earned_badges)
    unlocked = bool(data_var.get('Li', 0))
    
    return {
        'unlocked': unlocked,
        'badges': badge_count,
        'earnedCount': len(earned_badges),
        'queuedCount': len(data_ach.get('qb', [])),
        'totalAchievements': len(ALL_BADGE_CODES),
        'readyToUnlock': unlocked or badge_count >= 20,
    }

def set_raccoon_badges(root, backup_root, slot_number, amount, check_closed=require_closed):
    """Set Raccoon Club badges currency (4o) balance."""
    check_closed()
    if type(amount) is not int or amount < 0 or amount > MAX_TOTAL:
        raise ModError(f'Badge number must be between 0 and {MAX_TOTAL:,}.')
    f_save, raw_save, data_save = read_save(root, slot_number)
    
    save_changed = (data_save.get('4o') != amount)
    last_backup = None
    if save_changed:
        changed_save = dict(data_save)
        changed_save['4o'] = amount
        last_backup = commit_document(root, backup_root, slot_number, f_save, raw_save, changed_save, check_closed)
        
    if amount >= 20:
        try:
            f_var, raw_var, data_var = read_variables(root, slot_number)
            if data_var.get('Li') != 1 or data_var.get('pt') != 1 or data_var.get('Os') != 1:
                changed_var = dict(data_var)
                changed_var['Li'] = 1
                changed_var['pt'] = 1
                changed_var['Os'] = 1
                last_backup = commit_document(root, backup_root, slot_number, f_var, raw_var, changed_var, check_closed)
        except Exception:
            pass
            
    return last_backup

def unlock_raccoon_club(root, backup_root, slot_number, check_closed=require_closed):
    """Unlock Raccoon Club Clubhouse and ensure at least 20 badges are credited."""
    check_closed()
    f_var, raw_var, data_var = read_variables(root, slot_number)
    f_save, raw_save, data_save = read_save(root, slot_number)
    
    last_backup = None
    current_badges = data_save.get('4o', 0)
    if type(current_badges) is not int or current_badges < 20:
        changed_save = dict(data_save)
        changed_save['4o'] = max(current_badges if type(current_badges) is int else 0, 20)
        last_backup = commit_document(root, backup_root, slot_number, f_save, raw_save, changed_save, check_closed)
        
    changed_var = dict(data_var)
    var_changed = False
    for k in ('Li', 'pt', 'Os'):
        if changed_var.get(k) != 1:
            changed_var[k] = 1
            var_changed = True
    if var_changed:
        last_backup = commit_document(root, backup_root, slot_number, f_var, raw_var, changed_var, check_closed)
        
    return last_backup

def unlock_all_badges(root, backup_root, slot_number, check_closed=require_closed):
    """Unlock and award all 80 achievement badges on the Badge Sash, set 80 badges, and unlock Raccoon Club."""
    check_closed()
    last_backup = unlock_raccoon_club(root, backup_root, slot_number, check_closed=check_closed)
    
    f_save, raw_save, data_save = read_save(root, slot_number)
    if data_save.get('4o') != len(ALL_BADGE_CODES):
        changed_save = dict(data_save)
        changed_save['4o'] = len(ALL_BADGE_CODES)
        last_backup = commit_document(root, backup_root, slot_number, f_save, raw_save, changed_save, check_closed)
        
    slot = slot_path(root, slot_number)
    f_ach = slot / 'achievements.stuff'
    if not f_ach.is_file():
        raw_ach = b'{"VERSION":1,"eb":[],"qb":[]}\n'
        f_ach.write_bytes(raw_ach)
    else:
        raw_ach = f_ach.read_bytes()
    data_ach = json.loads(raw_ach.decode('utf-8'))
    changed_ach = dict(data_ach)
    changed_ach['eb'] = list(ALL_BADGE_CODES)
    changed_ach['qb'] = []
    for code in ALL_BADGE_CODES:
        if code not in changed_ach:
            changed_ach[code] = 1
    last_backup = commit_document(root, backup_root, slot_number, f_ach, raw_ach, changed_ach, check_closed)
        
    return last_backup

def max_all_currencies(root, backup_root, slot_number, amount=2_000_000, check_closed=require_closed):
    """Set wallet, bank, and all extra resources to amount."""
    currency_updates = {field: amount for field in EXTRA_CURRENCIES}
    return apply(root, backup_root, coins=amount, bank=amount, check_closed=check_closed, slot_number=slot_number, currency_updates=currency_updates)


ALL_BIRDS = {
    'qL': 'Bald Eagle',
    'Gm': 'Barred Owl',
    's9': 'Black-capped Chickadee',
    'RS': 'Black Oystercatcher',
    '5m': 'California Quail',
    '6q': 'Canada Goose',
    'Fg': 'Canada Jay',
    'jW': 'Cedar Waxwing',
    '2r': 'Common Loon',
    'sm': 'Common Merganser',
    'Bm': 'Dark-eyed Junco',
    'tk': 'Duck',
    'nb': 'Dunlin',
    'ro': 'American Goldfinch',
    'AT': "Anna's Hummingbird",
    'qh': 'Killdeer',
    'aU': 'Belted Kingfisher',
    'V2': 'Mallard',
    'BZ': 'Osprey',
    '59': 'Pacific Wren',
    '8I': 'Pelagic Cormorant',
    'wt': 'Rock Pigeon',
    'Ji': 'Rock Ptarmigan',
    'Nw': 'Red-tailed Hawk',
    'OX': 'Red-winged Blackbird',
    'uQ': 'American Robin',
    'DI': 'Scarlet Macaw',
    'q4': 'Glaucous-winged Gull',
    '8F': 'Song Sparrow',
    '14': 'Sooty Grouse',
    'QV': 'Spotted Towhee',
    '2Q': "Steller's Jay",
    'v7': 'Surf Scoter',
    'Ew': 'Tufted Puffin',
    'uP': 'Turkey Vulture',
    'Kv': 'Violet-green Swallow',
    'fE': "Townsend's Warbler",
    'Xs': 'Wood Duck',
    'dN': 'Pileated Woodpecker',
    'l8': 'American Crow',
}

BIRD_SANCTUARY_PROJECTS = {
    'boardwalk': {'name': 'Boardwalk', 'flag': 'NI7q', 'bldg': 'W6'},
    'outhouse': {'name': 'Outhouse', 'flag': 'op', 'bldg': 'wB'},
    'photo_shelves': {'name': 'Extra Photo Shelves', 'flag': 'l1', 'bldg': '3z'},
    'observation_tower': {'name': 'Observation Tower', 'flag': 'dri1', 'bldg': 'DY'},
    'benches_and_trash': {'name': 'Benches & Trash Cans', 'flag': 'On7X', 'bldg': 'pj'},
}

def read_photos(root, slot_number=2, *, initialize=True):
    slot = slot_path(root, slot_number)
    f = slot / 'photos.stuff'
    if not f.is_file():
        raw = b'{"VERSION":1,"photos":[]}\n'
        if initialize:
            f.write_bytes(raw)
        return f, raw, {"VERSION": 1, "photos": []}
    raw = f.read_bytes()
    try:
        d = json.loads(raw.decode('utf-8'))
    except Exception as e:
        raise ModError(f'Could not read photos.stuff: {e}')
    return f, raw, d

def read_birds(root, slot_number=2, *, initialize=True):
    slot = slot_path(root, slot_number)
    f = slot / 'birds.stuff'
    if not f.is_file():
        raw = b'{"VERSION":1,"bs":{}}\n'
        if initialize:
            f.write_bytes(raw)
        return f, raw, {"VERSION": 1, "bs": {}}
    raw = f.read_bytes()
    try:
        d = json.loads(raw.decode('utf-8'))
    except Exception as e:
        raise ModError(f'Could not read birds.stuff: {e}')
    return f, raw, d

def read_bldg(root, slot_number=2, *, initialize=True):
    slot = slot_path(root, slot_number)
    f = slot / 'bldg.stuff'
    if not f.is_file():
        raw = b'{"VERSION":1,"b":[]}\n'
        if initialize:
            f.write_bytes(raw)
        return f, raw, {"VERSION": 1, "b": []}
    raw = f.read_bytes()
    try:
        d = json.loads(raw.decode('utf-8'))
    except Exception as e:
        raise ModError(f'Could not read bldg.stuff: {e}')
    return f, raw, d

def read_lfs(root, slot_number=2):
    slot = slot_path(root, slot_number)
    f = slot / 'lfs.stuff'
    if not f.is_file():
        raw = b'{"records":[],"VERSION":1}\n'
        f.write_bytes(raw)
        return f, raw, {"records": [], "VERSION": 1}
    raw = f.read_bytes()
    try:
        d = json.loads(raw.decode('utf-8'))
    except Exception as e:
        raise ModError(f'Could not read lfs.stuff: {e}')
    return f, raw, d

def sync_photos_lfs(root, backup_root, slot_number=2, check_closed=require_closed):
    """Ensure all photo files referenced in photos.stuff that exist on disk are registered in lfs.stuff."""
    slot = slot_path(root, slot_number)
    f_lfs, raw_lfs, data_lfs = read_lfs(root, slot_number)
    changed_lfs = dict(data_lfs)
    records = list(changed_lfs.get('records', []))
    existing_paths = {r.get('f') for r in records if isinstance(r, dict)}
    
    _, _, data_photos = read_photos(root, slot_number)
    changed = False
    for p in data_photos.get('photos', []):
        fn = p.get('fn')
        if fn and fn not in existing_paths and (slot / fn).is_file():
            records.append({'f': fn, 'c': 1})
            existing_paths.add(fn)
            changed = True
            
    if changed:
        check_closed()
        changed_lfs['records'] = records
        return commit_document(root, backup_root, slot_number, f_lfs, raw_lfs, changed_lfs, check_closed)
    return None

def get_bird_sanctuary_info(root, slot_number=2):
    try:
        _, _, data_var = read_variables(root, slot_number)
    except Exception:
        data_var = {}
    try:
        _, _, data_bldg = read_bldg(root, slot_number, initialize=False)
        built_bldg = {b.get('d') for b in data_bldg.get('b', []) if isinstance(b, dict)}
    except Exception:
        built_bldg = set()
    try:
        _, _, data_birds = read_birds(root, slot_number, initialize=False)
        bird_map = data_birds.get('bs', {})
    except Exception:
        bird_map = {}

    flags = data_var.get('flags', {})
    funding = data_var.get('nt', 0)
    level = data_var.get('Rk', 1)
    is_photographer = bool(flags.get('sz', 0))

    projects = {}
    all_built = True
    for key, proj in BIRD_SANCTUARY_PROJECTS.items():
        is_built = bool(flags.get(proj['flag']) == 1 or proj['bldg'] in built_bldg)
        projects[key] = {
            'name': proj['name'],
            'flag': proj['flag'],
            'bldg': proj['bldg'],
            'built': is_built
        }
        if not is_built:
            all_built = False

    birds_status = {}
    photographed_count = 0
    for code, name in ALL_BIRDS.items():
        b_info = bird_map.get(code, {})
        hsv = b_info.get('hsv', 0)
        nps = b_info.get('nps', 0)
        is_photographed = bool(code in bird_map or hsv > 0 or nps > 0)
        if is_photographed:
            photographed_count += 1
        stars = min(3, max(1, hsv - 1)) if hsv > 1 else (1 if hsv == 1 else 0)
        birds_status[code] = {
            'code': code,
            'name': name,
            'photographed': is_photographed,
            'stars': stars,
            'hsv': hsv,
            'photoCount': nps
        }

    return {
        'funding': funding,
        'level': level,
        'isPhotographer': is_photographer,
        'projects': projects,
        'allBuilt': all_built,
        'photographedCount': photographed_count,
        'totalBirds': len(ALL_BIRDS),
        'birds': birds_status,
    }

def set_bird_sanctuary_funding(root, backup_root, slot_number, amount, check_closed=require_closed):
    """Set Bird Sanctuary Funding (variable 'nt')."""
    if type(amount) is not int or not (0 <= amount <= MAX_TOTAL):
        raise ModError(f'Bird sanctuary funding must be a whole number between 0 and {MAX_TOTAL:,}.')
    check_closed()
    read_save(root, slot_number)
    f_var, raw_var, data_var = read_variables(root, slot_number)
    changed_var = dict(data_var)
    changed_var['nt'] = amount
    flags = dict(changed_var.get('flags', {}))
    flags['sz'] = 1
    changed_var['flags'] = flags
    return commit_document(root, backup_root, slot_number, f_var, raw_var, changed_var, check_closed)

def set_bird_sanctuary_level(root, backup_root, slot_number, level, check_closed=require_closed):
    """Set Bird Sanctuary Funding Level (variable 'Rk', 1 to 5)."""
    if type(level) is not int or not (1 <= level <= 5):
        raise ModError('Bird sanctuary funding level must be between 1 and 5.')
    check_closed()
    read_save(root, slot_number)
    f_var, raw_var, data_var = read_variables(root, slot_number)
    changed_var = dict(data_var)
    changed_var['Rk'] = level
    flags = dict(changed_var.get('flags', {}))
    flags['sz'] = 1
    changed_var['flags'] = flags
    return commit_document(root, backup_root, slot_number, f_var, raw_var, changed_var, check_closed)

def build_all_bird_sanctuary_projects(root, backup_root, slot_number, check_closed=require_closed):
    """Build all Bird Sanctuary construction projects (Boardwalk, Outhouse, Photo Shelves, Tower, Benches/Trash)."""
    check_closed()
    read_save(root, slot_number)
    f_var, raw_var, data_var = read_variables(root, slot_number)
    changed_var = dict(data_var)
    flags = dict(changed_var.get('flags', {}))
    for proj in BIRD_SANCTUARY_PROJECTS.values():
        flags[proj['flag']] = 1
    flags['sz'] = 1
    changed_var['flags'] = flags
    last_backup = commit_document(root, backup_root, slot_number, f_var, raw_var, changed_var, check_closed)

    f_bldg, raw_bldg, data_bldg = read_bldg(root, slot_number)
    changed_bldg = dict(data_bldg)
    b_list = list(changed_bldg.get('b', []))
    existing_bldgs = {b.get('d') for b in b_list if isinstance(b, dict)}
    bldg_changed = False
    for proj in BIRD_SANCTUARY_PROJECTS.values():
        if proj['bldg'] not in existing_bldgs:
            b_list.append({'d': proj['bldg']})
            existing_bldgs.add(proj['bldg'])
            bldg_changed = True
    if bldg_changed:
        changed_bldg['b'] = b_list
        last_backup = commit_document(root, backup_root, slot_number, f_bldg, raw_bldg, changed_bldg, check_closed)

    return last_backup

def complete_bird_guide(root, backup_root, slot_number, check_closed=require_closed):
    """Mark all 40 birds as photographed with top star rating (hsv: 4)."""
    check_closed()
    read_save(root, slot_number)
    f_var, raw_var, data_var = read_variables(root, slot_number)
    changed_var = dict(data_var)
    flags = dict(changed_var.get('flags', {}))
    flags['sz'] = 1
    changed_var['flags'] = flags
    last_backup = commit_document(root, backup_root, slot_number, f_var, raw_var, changed_var, check_closed)

    f_birds, raw_birds, data_birds = read_birds(root, slot_number)
    changed_birds = dict(data_birds)
    bs = dict(changed_birds.get('bs', {}))
    for code in ALL_BIRDS:
        cur = bs.get(code, {})
        nps = max(cur.get('nps', 1), 1)
        bs[code] = {'d': code, 'hsv': 4, 'nps': nps}
    changed_birds['bs'] = bs
    last_backup = commit_document(root, backup_root, slot_number, f_birds, raw_birds, changed_birds, check_closed)

    return last_backup

def max_bird_sanctuary(root, backup_root, slot_number, amount=2_000_000, check_closed=require_closed):
    """Set 2M funding, level 5, build all projects, and complete bird guide."""
    check_closed()
    set_bird_sanctuary_funding(root, backup_root, slot_number, amount, check_closed=check_closed)
    set_bird_sanctuary_level(root, backup_root, slot_number, 5, check_closed=check_closed)
    build_all_bird_sanctuary_projects(root, backup_root, slot_number, check_closed=check_closed)
    return complete_bird_guide(root, backup_root, slot_number, check_closed=check_closed)

def create_photo(root, backup_root, slot_number, image_bytes, category='bird', bird_id=None, quality=3, check_closed=require_closed):
    """Save a user-painted or uploaded photo into slot's images folder and register in photos.stuff & birds.stuff."""
    if not isinstance(image_bytes, (bytes, bytearray)) or len(image_bytes) < 8:
        raise ModError('Invalid image data.')
    is_png = image_bytes.startswith(b'\x89PNG\r\n\x1a\n')
    is_jpg = image_bytes.startswith(b'\xff\xd8\xff')
    if not (is_png or is_jpg):
        raise ModError('Image must be a valid PNG or JPEG.')
    ext = 'png' if is_png else 'jpg'

    check_closed()
    read_save(root, slot_number)
    slot = slot_path(root, slot_number)
    images_dir = slot / 'images'
    images_dir.mkdir(parents=True, exist_ok=True)

    photo_id = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    img_filename = f'photo_{photo_id}.{ext}'
    img_path = images_dir / img_filename
    img_path.write_bytes(image_bytes)

    # 1. Register in lfs.stuff (CRITICAL: Unity LargeFileSaveData requires this to load into photo album)
    f_lfs, raw_lfs, data_lfs = read_lfs(root, slot_number)
    changed_lfs = dict(data_lfs)
    records = list(changed_lfs.get('records', []))
    rel_fn = f'images/{img_filename}'
    if not any(r.get('f') == rel_fn for r in records if isinstance(r, dict)):
        records.append({'f': rel_fn, 'c': 1})
    f_photos_check, _, data_photos_check = read_photos(root, slot_number)
    for p in data_photos_check.get('photos', []):
        p_fn = p.get('fn')
        if p_fn and not any(r.get('f') == p_fn for r in records if isinstance(r, dict)) and (slot / p_fn).is_file():
            records.append({'f': p_fn, 'c': 1})
    changed_lfs['records'] = records
    commit_document(root, backup_root, slot_number, f_lfs, raw_lfs, changed_lfs, check_closed)

    # 2. Register in photos.stuff
    f_photos, raw_photos, data_photos = read_photos(root, slot_number)
    changed_photos = dict(data_photos)
    photo_list = list(changed_photos.get('photos', []))

    ts = int(datetime.datetime.now().timestamp())
    quality = max(1, min(3, int(quality)))

    # Fetch current game day and time from sasquatch.stuff
    try:
        _, _, data_save = read_save(root, slot_number)
        current_day = data_save.get('day', 1074)
        current_time = data_save.get('time', 500)
        gt = round(float(current_day) + (float(current_time) / 1000.0), 4)
    except Exception:
        current_day = 1074
        gt = 1074.5

    photo_record = {
        'id': photo_id,
        'fn': rel_fn,
        'ts': ts,
        'gt': gt,
        'tw': 1200,
        'th': 800,
        'w': 288,
        'h': 192
    }

    if category == 'bird' and bird_id in ALL_BIRDS:
        photo_record['brd'] = {
            'dt': current_day,
            'birds': [{
                'bid': bird_id,
                'x': 250,
                'y': 150,
                'w': 500,
                'h': 500,
                'fpx': 500,
                'fpy': 400,
                's': quality,
                'fc': 0.5
            }]
        }

    photo_list.append(photo_record)
    changed_photos['photos'] = photo_list
    last_backup = commit_document(root, backup_root, slot_number, f_photos, raw_photos, changed_photos, check_closed)

    if category == 'bird' and bird_id in ALL_BIRDS:
        f_birds, raw_birds, data_birds = read_birds(root, slot_number)
        changed_birds = dict(data_birds)
        bs = dict(changed_birds.get('bs', {}))
        cur = bs.get(bird_id, {})
        new_hsv = max(cur.get('hsv', 0), quality + 1)
        new_nps = cur.get('nps', 0) + 1
        bs[bird_id] = {'d': bird_id, 'hsv': new_hsv, 'nps': new_nps}
        changed_birds['bs'] = bs
        commit_document(root, backup_root, slot_number, f_birds, raw_birds, changed_birds, check_closed)

        try:
            f_var, raw_var, data_var = read_variables(root, slot_number)
            flags = dict(data_var.get('flags', {}))
            if flags.get('sz') != 1:
                changed_var = dict(data_var)
                flags['sz'] = 1
                changed_var['flags'] = flags
                commit_document(root, backup_root, slot_number, f_var, raw_var, changed_var, check_closed)
        except Exception:
            pass

    return photo_id, last_backup

def get_photos_list(root, slot_number=2):
    try:
        _, _, data_photos = read_photos(root, slot_number, initialize=False)
        photos = []
        for p in data_photos.get('photos', []):
            if not isinstance(p, dict):
                continue
            birds = []
            brd = p.get('brd')
            if isinstance(brd, dict):
                for b in brd.get('birds', []):
                    bid = b.get('bid')
                    name = ALL_BIRDS.get(bid, bid)
                    stars = b.get('s', 1)
                    birds.append({'id': bid, 'name': name, 'stars': stars})
            photos.append({
                'id': p.get('id'),
                'fn': p.get('fn'),
                'ts': p.get('ts', 0),
                'birds': birds,
                'width': p.get('w', 600),
                'height': p.get('h', 400),
            })
        return list(reversed(photos))
    except Exception:
        return []


def interactive():
    require_closed()
    _, _, d = read_save(ROOT)
    print('\nSASQUATCH SLOT 3 MOD — experimental, offline\n')
    print('Only slot 3 is edited. Slots 1 and 2 are never written by this tool.')
    print('A full slot-3 backup is made before every change.')
    print('The game/iCloud may replace local changes; in-game acceptance is not yet tested.\n')
    print('Slot 3 wallet:', d.get('coins', 0), '| bank:', d.get('bankcoin', 0))
    print('\n1. Set wallet coins\n2. Set bank coins\n3. Undo the last change (only if the game has not changed that file)\n4. Exit\n')
    while True:
        parts = input('Type 1 4444 for wallet coins, or choose 1–4: ').split()
        if not parts:
            print('Enter a choice; for example: 1 4444')
            continue
        choice = parts[0]
        if choice in ('1', '2'):
            if len(parts) > 2:
                print('Use a choice and one amount, for example: 1 4444')
                continue
            text = parts[1] if len(parts) == 2 else input('New balance: ').strip()
            if not text.isascii() or not text.isdecimal():
                print('Enter digits only, for example: 4444. Nothing changed.')
                continue
            value = int(text)
            try:
                backup = apply(ROOT, PACKAGE / 'backups', coins=value if choice=='1' else None, bank=value if choice=='2' else None)
            except ModError as e:
                print('Stopped:', e)
                continue
            _, _, actual = read_save(ROOT)
            key = 'coins' if choice == '1' else 'bankcoin'
            print('\nSlot 3', 'wallet' if choice == '1' else 'bank', 'is now', actual.get(key, 0), 'in the local save.')
            if backup:
                print('Backup:', backup)
            else:
                print('Already at that value; nothing changed.')
            print('Open Sasquatch and select the THIRD save. No new game settings are added.')
            return
        if choice == '3' and len(parts) == 1:
            backups = sorted((PACKAGE / 'backups').glob('*/manifest.json'))
            if not backups:
                print('No mod backups found. Nothing changed.')
                continue
            backup = backups[-1].parent
            undo(ROOT, backup)
            print('Restored the slot-3 currency file from:', backup)
            return
        if choice == '4' and len(parts) == 1:
            print('Nothing changed.')
            return
        print('Unknown choice. Type 1 4444 to set wallet coins, or 4 to exit.')

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--coins', type=int)
    p.add_argument('--bank', type=int)
    p.add_argument('--status', action='store_true')
    p.add_argument('--undo', type=Path, metavar='BACKUP_FOLDER')
    args = p.parse_args()
    try:
        if args.status:
            _, _, d = read_save(ROOT)
            print(json.dumps({'slot': 3, 'coins': d.get('coins', 0), 'bank': d.get('bankcoin', 0)}))
        elif args.undo:
            undo(ROOT, args.undo.resolve())
            print('Undid the slot-3 mod edit.')
        elif args.coins is not None or args.bank is not None:
            backup = apply(ROOT, PACKAGE / 'backups', args.coins, args.bank)
            print('Backup: ' + str(backup) if backup else 'Nothing changed.')
        else:
            interactive()
    except (ModError, OSError, ValueError, EOFError) as e:
        print('Stopped:', e, file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    # Serialize this tool's invocations without ever locking a game save file.
    with (PACKAGE / '.slot3-mod.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit('Another slot-3 mod operation is running. Nothing changed.')
        sys.exit(main())
