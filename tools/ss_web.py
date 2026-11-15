#!/usr/bin/env python3
"""Loopback-only browser UI for the Sasquatch save console."""
import argparse
import base64
from contextlib import ExitStack
import fcntl
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
import secrets
import sys
import tempfile
from urllib.parse import urlsplit, parse_qs
import webbrowser
import ss_console as console
import slot3_mod as saves

class Server(HTTPServer):
    def __init__(self, address, root=saves.ROOT, package=saves.PACKAGE, check_closed=saves.require_closed, *, data_dir=None, demo=False):
        super().__init__(address, Handler)
        self.root, self.package, self.check_closed = root, package, check_closed
        self.data_dir = package if data_dir is None else data_dir
        self.demo = demo
        self.token = secrets.token_urlsafe(32)
    def state(self, slot):
        _, _, data = saves.read_save(self.root, slot)
        try:
            _, _, equipment = saves.read_equipment(self.root, slot)
            cars = [{'id': v['id'], 'level': v.get('lvl', 0)} for v in equipment.get('vehicles', [])]
            eq_items = equipment.get('equipment', [])
            shoes = {
                'runningOwned': any(isinstance(item, dict) and item.get('type') == 2524 for item in eq_items),
                'sneakyOwned': any(isinstance(item, dict) and item.get('type') == 2523 for item in eq_items),
                'runningActive': data.get('togtool', {}).get('runshoes') == 1,
                'sneakyActive': data.get('togtool', {}).get('sneakshoes') == 1,
            }
        except (saves.ModError, ValueError, OSError):
            cars = []
            shoes = {'runningOwned': False, 'sneakyOwned': False, 'runningActive': False, 'sneakyActive': False}

        try:
            _, _, vdata = saves.read_variables(self.root, slot)
            doc_stored = vdata.get('sR')
            doc_lvl = doc_stored + 1 if type(doc_stored) is int and 0 <= doc_stored <= 3 else None
            doc_rank = saves.DOCTOR_RANKS.get(doc_lvl, 'Not Started') if doc_lvl else 'Not Started'
        except Exception:
            doc_lvl = None
            doc_rank = 'Not Started'

        ff_info = saves.get_firefighter_info(self.root, slot)

        try:
            catalog = saves.get_all_vehicles_status(self.root, slot)
        except Exception:
            catalog = []

        try:
            halloween = saves.get_halloween_info(self.root, slot)
        except Exception:
            halloween = {'active': False, 'candy': 0}

        try:
            christmas = saves.get_christmas_info(self.root, slot)
        except Exception:
            christmas = {'active': False, 'candyCanes': 0, 'forceToday': False, 'decorations': {}}

        try:
            raccoon_club = saves.get_raccoon_club_info(self.root, slot)
        except Exception:
            raccoon_club = {'unlocked': False, 'badges': 0, 'earnedCount': 0, 'queuedCount': 0, 'totalAchievements': 80, 'readyToUnlock': False}

        try:
            bird_sanctuary = saves.get_bird_sanctuary_info(self.root, slot)
        except Exception:
            bird_sanctuary = {'funding': 0, 'level': 1, 'isPhotographer': False, 'projects': {}, 'allBuilt': False, 'photographedCount': 0, 'totalBirds': len(saves.ALL_BIRDS), 'birds': {}}

        try:
            photos = saves.get_photos_list(self.root, slot)
        except Exception:
            photos = []

        slots_overview = []
        for s in (1, 2, 3):
            try:
                save_f, _, s_data = saves.read_save(self.root, s)
                try:
                    _, _, equipment = saves.read_equipment(self.root, s)
                    vehicle_count = len(equipment['vehicles'])
                except (saves.ModError, ValueError, OSError):
                    vehicle_count = 0
                slots_overview.append({
                    'slot': s,
                    'coins': s_data.get('coins', 0),
                    'bank': s_data.get('bankcoin', 0),
                    'vehicles_count': vehicle_count,
                    'mtime': save_f.stat().st_mtime,
                })
            except Exception:
                slots_overview.append({'slot': s, 'coins': 0, 'bank': 0, 'vehicles_count': 0, 'mtime': 0})

        active_slot = max(slots_overview, key=lambda x: x['mtime'])['slot'] if slots_overview else slot

        try:
            self.check_closed()
            blocked = None
        except saves.ModError as e:
            blocked = str(e)

        return {
            'slot': slot,
            'demo': self.demo,
            'activeSlot': active_slot,
            'slotsOverview': slots_overview,
            'resources': [{'key': key, 'label': label, 'value': raccoon_club['badges'] if field == '4o' and field not in data else data.get(field, 0)} for key, (label, field) in console.CURRENCIES.items()],
            'cars': cars,
            'supportedCars': sorted(saves.LEVEL_CARS),
            'allVehicles': catalog,
            'halloween': halloween,
            'christmas': christmas,
            'raccoonClub': raccoon_club,
            'firefighter': ff_info,
            'doctor': {'level': doc_lvl, 'rank': doc_rank},
            'shoes': shoes,
            'birdSanctuary': bird_sanctuary,
            'photos': photos,
            'allBirds': saves.ALL_BIRDS,
            'birdProjects': saves.BIRD_SANCTUARY_PROJECTS,
            'blocked': blocked,
            'token': self.token
        }

    def documents(self, slot):
        folder = saves.slot_path(self.root, slot)
        if folder.is_symlink():
            return []
        return [name for name in saves.EDITABLE_DOCUMENTS
                if (folder / name).is_file() and not (folder / name).is_symlink()]

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def host_ok(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')
    def send(self, code, value, html=False, content_type=None):
        if content_type:
            raw = value if isinstance(value, (bytes, bytearray)) else str(value).encode()
            ct = content_type
        elif html:
            raw = value if isinstance(value, (bytes, bytearray)) else str(value).encode()
            ct = 'text/html; charset=utf-8'
        else:
            raw = value if isinstance(value, (bytes, bytearray)) else json.dumps(value).encode()
            ct = 'application/json'
        self.send_response(code)
        self.send_header('Content-Type', ct)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(raw)
    def do_GET(self):
        if not self.host_ok(): return self.send(403,{'error':'Invalid host'})
        url=urlsplit(self.path)
        try:
            if url.path=='/':
                return self.send(200,(self.server.package/'web/index.html').read_bytes(),True)
            if url.path == '/save-fields.js':
                return self.send(200, (self.server.package/'web/save-fields.js').read_bytes(),
                                 content_type='text/javascript; charset=utf-8')
            if url.path=='/api/state':
                query = parse_qs(url.query)
                if 'slot' not in query:
                    for slot in (1, 2, 3):
                        try:
                            saves.read_save(self.server.root, slot)
                        except (saves.ModError, OSError):
                            continue
                        return self.send(200, self.server.state(slot))
                slot=int(query.get('slot',['1'])[0])
                return self.send(200,self.server.state(slot))
            if url.path == '/api/documents':
                query = parse_qs(url.query)
                slot = int(query.get('slot', ['1'])[0])
                name = query.get('name', [''])[0]
                files = self.server.documents(slot)
                if not name:
                    return self.send(200, {'files': files})
                _, raw, document = saves.read_editable_document(self.server.root, slot, name)
                fields = {key: json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2)
                          for key, value in document.items() if key != 'VERSION'}
                return self.send(200, {'name': name, 'revision': saves.digest(raw), 'fields': fields})
            if url.path.startswith('/api/photo_image/'):
                photo_id = url.path[len('/api/photo_image/'):]
                if not re.match(r'^[A-Za-z0-9_-]+$', photo_id):
                    return self.send(400, {'error': 'Invalid photo ID'})
                slot = int(parse_qs(url.query).get('slot', ['2'])[0])
                folder = saves.slot_path(self.server.root, slot)
                if folder.is_symlink() or (folder / 'images').is_symlink():
                    return self.send(404, {'error': 'Photo image not found'})
                for ext, ct in [('png', 'image/png'), ('jpg', 'image/jpeg')]:
                    f_img = folder / 'images' / f'photo_{photo_id}.{ext}'
                    if not f_img.is_symlink() and f_img.is_file():
                        return self.send(200, f_img.read_bytes(), content_type=ct)
                return self.send(404, {'error': 'Photo image not found'})
            return self.send(404,{'error':'Not found'})
        except (saves.ModError,ValueError,OSError,RecursionError) as e:
            return self.send(400,{'error':str(e)})
    def do_HEAD(self):
        return self.do_GET()
    def do_POST(self):
        origin=self.headers.get('Origin')
        if not self.host_ok() or origin != 'http://'+self.headers.get('Host','') or not secrets.compare_digest(self.headers.get('X-SS-Token',''),self.server.token):
            return self.send(403,{'error':'Refresh this localhost page and retry.'})
        if self.path!='/api/edit': return self.send(404,{'error':'Not found'})
        try:
            if self.headers.get('Content-Type')!='application/json':
                raise saves.ModError('JSON required')
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=10*1024*1024: raise saves.ModError('Invalid request size')
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict): raise saves.ModError('Invalid request')
            slot=data.get('slot')
            saves.slot_path(self.server.root,slot)
            with (self.server.data_dir/'.slot3-mod.lock').open('a') as lock:
                try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:raise saves.ModError('Exit the terminal editor first, then retry here.')
                backups=self.server.data_dir/'console-backups'
                action=data.get('action')
                if action == 'set_document_field':
                    name = data.get('name')
                    key = data.get('key')
                    backup = saves.set_document_field(self.server.root, backups, slot, name, key,
                                                      data.get('value'), data.get('revision'), self.server.check_closed)
                    message = f'{key} saved in {name} (slot {slot}).' if backup else 'The field already has this value.'
                elif action=='currency':
                    key=data.get('key')
                    if key not in console.CURRENCIES:raise saves.ModError('Unknown currency')
                    value=console.parse_amount(str(data.get('value','')))
                    field=console.CURRENCIES[key][1]
                    kwargs={'coins':value} if key=='c' else {'bank':value} if key=='b' else {'currency_updates':{field:value}}
                    backup=saves.apply(self.server.root,backups,check_closed=self.server.check_closed,slot_number=slot,**kwargs)
                    message=f'{console.CURRENCIES[key][0]} set to {value:,} in slot {slot}.'
                elif action=='max_currencies':
                    backup=saves.max_all_currencies(self.server.root,backups,slot,check_closed=self.server.check_closed)
                    message=f'All 11 currency balances set to 2,000,000 in slot {slot}!'
                elif action=='fire_funding':
                    value=console.parse_amount(str(data.get('value','')))
                    backup=saves.set_firefighter_funding(self.server.root,backups,slot,value,check_closed=self.server.check_closed)
                    message=f'Firefighter funding set to {value:,} in slot {slot}.'
                elif action=='fire_rank':
                    level=int(data.get('level', 8))
                    backup=saves.set_firefighter_level(self.server.root,backups,slot,level,check_closed=self.server.check_closed)
                    rank_name=saves.FIREFIGHTER_RANKS.get(level, f'Level {level}')
                    message=f'Firefighter rank set to {rank_name} (Level {level}/8) in slot {slot}.'
                elif action=='max_fire':
                    backup=saves.max_fire_station(self.server.root,backups,slot,check_closed=self.server.check_closed)
                    message=f'Fire station maxed! Funding at least 500k, rank Junior Battalion Chief (8/8), and all upgrades maxed in slot {slot}.'
                elif action=='doctor':
                    level=int(data.get('level', 4))
                    backup=saves.set_doctor_level(self.server.root,backups,slot,level,check_closed=self.server.check_closed)
                    rank_name=saves.DOCTOR_RANKS.get(level, f'Level {level}')
                    message=f'Doctor career set to {rank_name} (Level {level}/4) in slot {slot}.'
                elif action=='shoes':
                    kind=data.get('kind', 'all')
                    if kind=='all':
                        backup=saves.unlock_all_shoes(self.server.root,backups,slot,check_closed=self.server.check_closed)
                        message=f'Unlocked and activated ALL shoes (Sneaky + Running + Sprinting) in slot {slot}.'
                    elif kind=='sneaky':
                        saves.gift_sneaky_shoes(self.server.root,backups,slot,check_closed=self.server.check_closed)
                        backup=saves.activate_sneaky_shoes(self.server.root,backups,slot,check_closed=self.server.check_closed)
                        message=f'Sneaky shoes owned and activated in slot {slot}.'
                    elif kind=='running':
                        saves.gift_running_shoes(self.server.root,backups,slot,check_closed=self.server.check_closed)
                        backup=saves.activate_running_shoes(self.server.root,backups,slot,check_closed=self.server.check_closed)
                        message=f'Running shoes owned and activated in slot {slot}.'
                    else:raise saves.ModError('Unknown shoe type')
                elif action in ('own', 'own_vehicle'):
                    identifier = data.get('car') or data.get('vehicle_id') or data.get('identifier')
                    if not isinstance(identifier, str) or not identifier.strip():
                        raise saves.ModError('Choose or type a car name')
                    backup = saves.own_car(self.server.root, backups, slot, identifier, check_closed=self.server.check_closed)
                    if backup is None:
                        message = f'Vehicle {identifier} is ALREADY owned in slot {slot}! Nothing changed.'
                    else:
                        message = f'Vehicle {identifier} is now owned in slot {slot}!'
                elif action in ('max_cars', 'own_all_vehicles'):
                    backup = saves.own_all_known_vehicles(self.server.root, backups, slot, max_level=True, check_closed=self.server.check_closed)
                    if backup is None:
                        message = f'All vehicles are already owned and maxed in slot {slot}!'
                    else:
                        message = f'All {len(saves.ALL_VEHICLES)} vehicles unlocked and garage levels maxed in slot {slot}!'
                elif action == 'car_level':
                    car = data.get('car') or data.get('vehicle_id')
                    level = int(data.get('level', 5))
                    backup = saves.set_car_level(self.server.root, backups, slot, car, level, check_closed=self.server.check_closed)
                    message = f'Vehicle {car} garage level set to {level} in slot {slot}.'
                elif action == 'halloween_event':
                    active = bool(data.get('active', True))
                    backup = saves.set_halloween_event(self.server.root, backups, slot, active=active, check_closed=self.server.check_closed)
                    message = f'Halloween seasonal event {"enabled" if active else "disabled"} in slot {slot}.'
                elif action == 'halloween_candy':
                    value = console.parse_amount(str(data.get('value', data.get('amount', 0))))
                    backup = saves.set_halloween_candy(self.server.root, backups, slot, value, check_closed=self.server.check_closed)
                    message = f'Halloween candy balance set to {value:,} in slot {slot}.'
                elif action == 'refill_candy_bowls':
                    backup = saves.refill_candy_bowls(self.server.root, backups, slot, check_closed=self.server.check_closed)
                    message = f'All Halloween candy bowls refilled and reset in slot {slot}!'
                elif action == 'christmas_event':
                    active = bool(data.get('active', True))
                    backup = saves.set_christmas_event(self.server.root, backups, slot, active=active, check_closed=self.server.check_closed)
                    message = f'Christmas & Winter Holiday event {"enabled" if active else "disabled"} in slot {slot}.'
                elif action == 'christmas_candy_canes':
                    value = console.parse_amount(str(data.get('value', data.get('amount', 0))))
                    backup = saves.set_christmas_candy_canes(self.server.root, backups, slot, value, check_closed=self.server.check_closed)
                    message = f'Christmas candy canes balance set to {value:,} in slot {slot}.'
                elif action == 'unlock_christmas_decorations':
                    backup = saves.unlock_all_christmas_decorations(self.server.root, backups, slot, check_closed=self.server.check_closed)
                    message = f'All Jack Frost Christmas decorations unlocked in slot {slot}!'
                elif action == 'max_christmas':
                    backup = saves.max_christmas(self.server.root, backups, slot, check_closed=self.server.check_closed)
                    message = f'Christmas enabled, candy canes maxed, and all holiday decorations unlocked in slot {slot}!'
                elif action in ('raccoon_badges', 'badges'):
                    value = console.parse_amount(str(data.get('value', data.get('amount', data.get('badges', 0)))))
                    backup = saves.set_raccoon_badges(self.server.root, backups, slot, value, check_closed=self.server.check_closed)
                    message = f'Raccoon Club badges set to {value} in slot {slot}!'
                elif action == 'unlock_raccoon_club':
                    backup = saves.unlock_raccoon_club(self.server.root, backups, slot, check_closed=self.server.check_closed)
                    message = f'Raccoon Club Clubhouse unlocked in slot {slot}!'
                elif action == 'unlock_all_badges':
                    backup = saves.unlock_all_badges(self.server.root, backups, slot, check_closed=self.server.check_closed)
                    message = f'All 80 achievement badges unlocked, badge sash filled, and Raccoon Club unlocked in slot {slot}!'
                elif action == 'bird_funding':
                    value = console.parse_amount(str(data.get('value', data.get('amount', 0))))
                    backup = saves.set_bird_sanctuary_funding(self.server.root, backups, slot, value, check_closed=self.server.check_closed)
                    message = f'Bird Sanctuary funding set to {value:,} in slot {slot}.'
                elif action == 'bird_level':
                    level = int(data.get('level', 1))
                    backup = saves.set_bird_sanctuary_level(self.server.root, backups, slot, level, check_closed=self.server.check_closed)
                    message = f'Bird Sanctuary funding level set to {level}/5 in slot {slot}.'
                elif action == 'build_bird_sanctuary':
                    backup = saves.build_all_bird_sanctuary_projects(self.server.root, backups, slot, check_closed=self.server.check_closed)
                    message = f'All 5 Bird Sanctuary construction projects built in slot {slot}!'
                elif action == 'complete_bird_guide':
                    backup = saves.complete_bird_guide(self.server.root, backups, slot, check_closed=self.server.check_closed)
                    message = f'All 40 birds completed in Bird Guide with 3-Star sightings in slot {slot}!'
                elif action == 'max_bird_sanctuary':
                    backup = saves.max_bird_sanctuary(self.server.root, backups, slot, check_closed=self.server.check_closed)
                    message = f'Bird Sanctuary fully funded (2,000,000), level 5, all projects built, and all 40 birds completed in slot {slot}!'
                elif action == 'create_photo':
                    img_data = str(data.get('image_data', ''))
                    if ',' in img_data:
                        img_data = img_data.split(',', 1)[1]
                    try:
                        raw_bytes = base64.b64decode(img_data)
                    except Exception as e:
                        raise saves.ModError(f'Invalid image data: {e}')
                    cat = str(data.get('category', 'bird'))
                    bird_id = data.get('bird_id')
                    quality = int(data.get('quality', 3))
                    photo_id, backup = saves.create_photo(self.server.root, backups, slot, raw_bytes, category=cat, bird_id=bird_id, quality=quality, check_closed=self.server.check_closed)
                    bird_str = f" as {saves.ALL_BIRDS.get(bird_id, bird_id)}" if cat == 'bird' and bird_id else ""
                    message = f'Photo created and saved to game album with ID {photo_id}{bird_str} in slot {slot}!'
                elif action=='custom_var':
                    key=str(data.get('key','')).strip()
                    raw_val=data.get('value')
                    if isinstance(raw_val, str):
                        raw_val=raw_val.strip()
                        if raw_val.lower() == 'true': val = True
                        elif raw_val.lower() == 'false': val = False
                        else:
                            try:
                                if '.' in raw_val: val = float(raw_val)
                                else: val = int(raw_val)
                            except ValueError: val = raw_val
                    else:
                        val = raw_val
                    backup=saves.set_custom_variable(self.server.root,backups,slot,key,val,check_closed=self.server.check_closed)
                    message=f"Variable '{key}' set to {val} in slot {slot}."
                elif action=='undo':
                    candidates=[p for p in backups.glob('*/manifest.json')
                                if not (p.parent/'undone').exists() and json.loads(p.read_text()).get('slot')==slot]
                    if not candidates:raise saves.ModError('No backups for this slot yet.')
                    backup=sorted(candidates)[-1].parent
                    saves.undo(self.server.root,backup,check_closed=self.server.check_closed,slot_number=slot)
                    message=f'Last unchanged edit restored for slot {slot}.'
                else:raise saves.ModError('Unknown action')
                state=self.server.state(slot)
                state.update(message=message,backup=str(backup) if backup else None)
                return self.send(200,state)
        except (saves.ModError,ValueError,OSError,TypeError,RecursionError) as e:
            return self.send(400,{'error':str(e)})

def seed_demo(root):
    for slot in (1, 2, 3):
        folder = saves.slot_path(root, slot)
        folder.mkdir(parents=True)
        documents = {
            'sasquatch.stuff': {'VERSION': 2, 'coins': slot * 1250, 'bankcoin': 5000, 'togtool': {}},
            'variables.stuff': {'VERSION': 1, 'flags': {}, 'sM': 25000, 'sR': 1},
            'equipment.stuff': {'VERSION': 1, 'vehicles': [{'id': 'sportscar', 'lvl': 1}], 'equipment': []},
            'achievements.stuff': {'VERSION': 1, 'eb': [], 'qb': []},
            'birds.stuff': {'VERSION': 1, 'bs': {}},
            'bldg.stuff': {'VERSION': 1, 'b': []},
            'photos.stuff': {'VERSION': 1, 'photos': []},
        }
        for name, document in documents.items():
            (folder/name).write_text(json.dumps(document), encoding='utf-8')


def run_server(args, **options):
    server=None
    target_port = args.port
    ports_to_try = [target_port] if target_port != 6789 else [6789] + list(range(6790, 6805))
    for p in ports_to_try:
        try:
            server=Server(('127.0.0.1',p), **options)
            break
        except OSError as e:
            if target_port != 6789:
                sys.exit(f'Cannot start localhost server on port {target_port}: {e}')
    if not server:
        sys.exit('Cannot start localhost server: ports occupied.')
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Sasquatch editor: {url}',flush=True)
    if args.demo:
        print('Demo mode uses temporary sample saves.', flush=True)
    print('Press Ctrl+C to stop. Opening the page does not edit any save.',flush=True)
    if args.open:
        webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=6789)
    parser.add_argument('--data-dir', type=Path, help='Store backups and the editor lock in this directory.')
    parser.add_argument('--demo', action='store_true', help='Try the editor with temporary sample saves.')
    parser.add_argument('--open', action='store_true', help='Open the editor in your default browser.')
    args = parser.parse_args()
    if not args.demo:
        if args.data_dir is not None:
            args.data_dir.mkdir(parents=True, exist_ok=True)
        return run_server(args, data_dir=args.data_dir)
    with tempfile.TemporaryDirectory(prefix='sasquatch-studio-') as demo_dir:
        data_dir = Path(demo_dir)
        root = data_dir / 'saves'
        seed_demo(root)
        run_server(args, root=root, check_closed=lambda: None, data_dir=data_dir, demo=True)

if __name__=='__main__':main()
