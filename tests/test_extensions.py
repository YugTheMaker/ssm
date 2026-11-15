import base64
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).parents[1]/'tools'))
import slot3_mod as saves
import ss_console as console
import ss_web

class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.package=Path(self.tmp.name)/'package';self.package.mkdir()
        self.root=Path(self.tmp.name)/'saves'
        for slot in (1,2,3):
            folder=saves.slot_path(self.root,slot);folder.mkdir(parents=True,exist_ok=True)
            (folder/'sasquatch.stuff').write_text(json.dumps({'VERSION':2,'coins':100,'ptkt':110,'quest':'keep'}))
            (folder/'equipment.stuff').write_text(json.dumps({'vehicles':[{'id':'sportscar','lvl':2,'m':[]}] if slot==2 else [],'equipment':[{'type':42}]}))
            (folder/'variables.stuff').write_text(json.dumps({'VERSION':1,'flags':{'BZ':1} if slot==2 else {},'sR':2 if slot==2 else None,'UA':26 if slot==2 else None}))
    def test_tickets_isolated_and_undo(self):
        original={p:p.read_bytes() for p in self.root.rglob('*.stuff')}
        b=saves.apply(self.root,self.package/'console-backups',check_closed=lambda:None,slot_number=2,currency_updates={'ptkt':9999})
        f=self.root/'default2/sasquatch.stuff'
        self.assertEqual(json.loads(f.read_text())['ptkt'],9999)
        for p,raw in original.items():
            if p!=f:self.assertEqual(p.read_bytes(),raw)
        saves.undo(self.root,b,check_closed=lambda:None,slot_number=2)
        self.assertEqual(f.read_bytes(),original[f])
    def test_all_resource_fields_and_reject_unknown(self):
        for key in saves.EXTRA_CURRENCIES:
            saves.apply(self.root,self.package/'backups',check_closed=lambda:None,currency_updates={key:42})
        for key in saves.EXTRA_CURRENCIES:self.assertEqual(saves.read_save(self.root)[2][key],42)
        with self.assertRaises(saves.ModError):saves.apply(self.root,self.package/'backups',check_closed=lambda:None,currency_updates={'quest':0})
    def test_car_copy_preserves_source_and_undo(self):
        source=(self.root/'default2/equipment.stuff').read_bytes()
        target=self.root/'default3/equipment.stuff';original=target.read_bytes()
        b=saves.own_car(self.root,self.package/'console-backups',3,'sportscar',check_closed=lambda:None)
        self.assertEqual((self.root/'default2/equipment.stuff').read_bytes(),source)
        self.assertEqual(json.loads(target.read_text())['equipment'],[{'type':42}])
        self.assertIsNone(saves.own_car(self.root,self.package/'console-backups',3,'sportscar',check_closed=lambda:None))
        saves.undo(self.root,b,check_closed=lambda:None,slot_number=3)
        self.assertEqual(target.read_bytes(),original)
    def test_car_unknown_and_linked_rejected(self):
        with self.assertRaises(saves.ModError):saves.own_car(self.root,self.package/'backups',3,'unknown',check_closed=lambda:None)
        p=self.root/'default2/equipment.stuff';d=json.loads(p.read_text());d['vehicles'][0]['aT']=['linked'];p.write_text(json.dumps(d))
        with self.assertRaises(saves.ModError):saves.own_car(self.root,self.package/'backups',3,'sportscar',check_closed=lambda:None)
    def test_t_console_alias(self):
        commands=iter(['t=1','resources','exit'])
        with contextlib.redirect_stdout(io.StringIO()):console.session(2,self.root,self.package,lambda _:next(commands),lambda:None)
        self.assertEqual(saves.read_save(self.root,2)[2]['ptkt'],1)
    def test_car_level_isolation_and_undo(self):
        original={p:p.read_bytes() for p in self.root.rglob('*.stuff')}
        target=self.root/'default2/equipment.stuff'
        for level in (1, 5):
            backup=saves.set_car_level(self.root,self.package/'backups',2,'Sports Car',level,check_closed=lambda:None)
            expected=json.loads(original[target]);expected['vehicles'][0]['lvl']=level-1
            self.assertEqual(json.loads(target.read_bytes()),expected)
            for p,raw in original.items():
                if p!=target:self.assertEqual(p.read_bytes(),raw)
            saves.undo(self.root,backup,check_closed=lambda:None,slot_number=2)
            self.assertEqual(target.read_bytes(),original[target])
        self.assertIsNone(saves.set_car_level(self.root,self.package/'backups',2,'sportscar',3,check_closed=lambda:None))
    def test_car_level_rejections(self):
        original={p:p.read_bytes() for p in self.root.rglob('*.stuff')}
        for slot,name,level in ((3,'sportscar',2),(2,'unknown',2),(2,'sportscar',0),(2,'sportscar',6),(2,'sportscar',True)):
            with self.assertRaises(saves.ModError):
                saves.set_car_level(self.root,self.package/'backups',slot,name,level,check_closed=lambda:None)
        def running():raise saves.ModError('Game running')
        with self.assertRaises(saves.ModError):
            saves.set_car_level(self.root,self.package/'backups',2,'sportscar',1,check_closed=running)
        for p,raw in original.items():self.assertEqual(p.read_bytes(),raw)
    def test_gokart_level_aliases(self):
        target=self.root/'default2/equipment.stuff'
        data=json.loads(target.read_text())
        data['vehicles'].append({'id':'gokart','lvl':0,'m':[]})
        target.write_text(json.dumps(data))
        for name in ('go-kart','go kart','gokart'):
            backup=saves.set_car_level(self.root,self.package/'backups',2,name,5,check_closed=lambda:None)
            actual=json.loads(target.read_text())
            self.assertEqual(actual['vehicles'][1]['lvl'],4)
            self.assertEqual(actual['vehicles'][0],data['vehicles'][0])
            saves.undo(self.root,backup,check_closed=lambda:None,slot_number=2)
            self.assertEqual(json.loads(target.read_text()),data)
    def test_running_shoes_gift_and_undo(self):
        original={p:p.read_bytes() for p in self.root.rglob('*.stuff')}
        target=self.root/'default3/equipment.stuff'
        backup=saves.gift_running_shoes(self.root,self.package/'backups',3,check_closed=lambda:None)
        expected=json.loads(original[target]);expected['equipment'].append({'type':2524})
        self.assertEqual(json.loads(target.read_bytes()),expected)
        self.assertIsNone(saves.gift_running_shoes(self.root,self.package/'backups',3,check_closed=lambda:None))
        for p,raw in original.items():
            if p!=target:self.assertEqual(p.read_bytes(),raw)
        saves.undo(self.root,backup,check_closed=lambda:None,slot_number=3)
        self.assertEqual(target.read_bytes(),original[target])
    def test_running_shoes_commands(self):
        for command in ('RS G','RS-C G','rs-c gift'):
            commands=iter([command,'exit'])
            with contextlib.redirect_stdout(io.StringIO()):
                console.session(3,self.root,self.package,lambda _:next(commands),lambda:None)
        items=saves.read_equipment(self.root,3)[2]['equipment']
        self.assertEqual(sum(x['type']==2524 for x in items),1)
    def test_running_shoes_running_game_blocked(self):
        target=self.root/'default3/equipment.stuff';original=target.read_bytes()
        def running():raise saves.ModError('Game running')
        with self.assertRaises(saves.ModError):
            saves.gift_running_shoes(self.root,self.package/'backups',3,check_closed=running)
        self.assertEqual(target.read_bytes(),original)
    def test_running_shoes_activation(self):
        with self.assertRaises(saves.ModError):
            saves.activate_running_shoes(self.root,self.package/'backups',3,check_closed=lambda:None)
        saves.gift_running_shoes(self.root,self.package/'backups',3,check_closed=lambda:None)
        target=self.root/'default3/sasquatch.stuff'
        data=json.loads(target.read_bytes());data['togtool']={'dwatch':1};target.write_text(json.dumps(data))
        original={p:p.read_bytes() for p in self.root.rglob('*.stuff')}
        backup=saves.activate_running_shoes(self.root,self.package/'backups',3,check_closed=lambda:None)
        expected=dict(data,togtool={'dwatch':1,'runshoes':1})
        self.assertEqual(json.loads(target.read_bytes()),expected)
        self.assertIsNone(saves.activate_running_shoes(self.root,self.package/'backups',3,check_closed=lambda:None))
        for p,raw in original.items():
            if p!=target:self.assertEqual(p.read_bytes(),raw)
        saves.undo(self.root,backup,check_closed=lambda:None,slot_number=3)
        self.assertEqual(target.read_bytes(),original[target])
    def test_sc_console(self):
        commands=iter(['SC sports car 5','exit']);output=io.StringIO()
        with contextlib.redirect_stdout(output):
            console.session(2,self.root,self.package,lambda _:next(commands),lambda:None)
        self.assertEqual(saves.read_equipment(self.root,2)[2]['vehicles'][0]['lvl'],4)
        self.assertIn('Increased speed is not verified',output.getvalue())
    def start_server(self,checker=lambda:None):
        self.server=ss_web.Server(('127.0.0.1',0),self.root,self.package,checker)
        thread=threading.Thread(target=self.server.serve_forever,daemon=True);thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        return f'http://127.0.0.1:{self.server.server_port}'
    def test_http_read_write_and_csrf(self):
        base=self.start_server()
        with urlopen(base+'/api/state?slot=2') as r:state=json.load(r)
        self.assertEqual(next(x['value'] for x in state['resources'] if x['key']=='t'),110)
        body=json.dumps({'slot':2,'action':'currency','key':'t','value':'2m'}).encode()
        req=Request(base+'/api/edit',data=body,headers={'Content-Type':'application/json'})
        with self.assertRaises(HTTPError) as error:urlopen(req)
        self.assertEqual(error.exception.code,403)
        req=Request(base+'/api/edit',data=body,headers={'Content-Type':'application/json','Origin':base,'X-SS-Token':state['token']})
        with urlopen(req) as r:response=json.load(r)
        self.assertIn('2,000,000',response['message'])
        self.assertEqual(saves.read_save(self.root,2)[2]['ptkt'],2000000)
        with self.assertRaises(HTTPError):urlopen(Request(base+'/api/state?slot=2',headers={'Host':'evil.example'}))
    def test_http_running_game_blocks(self):
        def running():raise saves.ModError('Game running')
        base=self.start_server(running)
        body=json.dumps({'slot':3,'action':'currency','key':'c','value':'12'}).encode()
        req=Request(base+'/api/edit',data=body,headers={'Content-Type':'application/json','Origin':base,'X-SS-Token':self.server.token})
        with self.assertRaises(HTTPError):urlopen(req)
        self.assertEqual(saves.read_save(self.root,3)[2]['coins'],100)

    def test_http_reads_leave_a_fresh_slot_untouched(self):
        base = self.start_server()
        before = {path: path.read_bytes() for path in self.root.rglob('*.stuff')}
        with urlopen(base + '/api/state') as response:
            self.assertEqual(json.load(response)['slot'], 1)
        with urlopen(base + '/api/documents?slot=1') as response:
            self.assertEqual(set(json.load(response)['files']),
                             {'sasquatch.stuff', 'equipment.stuff', 'variables.stuff'})
        self.assertEqual({path: path.read_bytes() for path in self.root.rglob('*.stuff')}, before)

    def test_http_save_fields_validate_and_undo(self):
        folder = saves.slot_path(self.root, 2)
        target = folder / 'birds.stuff'
        original = b'{"VERSION":1,"bs":{}}'
        target.write_bytes(original)
        base = self.start_server()
        url = base + '/api/documents?slot=2&name=birds.stuff'
        with urlopen(url) as response:
            document = json.load(response)
        self.assertEqual(document['fields'], {'bs': '{}'})

        def post(**body):
            headers = {'Content-Type': 'application/json', 'Origin': base, 'X-SS-Token': self.server.token}
            return urlopen(Request(base + '/api/edit', data=json.dumps(dict(body, slot=2)).encode(), headers=headers))

        edit = {'action': 'set_document_field', 'name': 'birds.stuff',
                'key': 'bs', 'value': '{"test":{"hsv":3,"nps":1}}', 'revision': document['revision']}
        for bad in ({'key': 'VERSION'}, {'name': '../variables.stuff'}, {'value': '[]'}, {'value': '{"test":NaN}'}):
            with self.assertRaises(HTTPError) as error:
                post(**(edit | bad))
            self.assertEqual(error.exception.code, 400)
        self.assertEqual(target.read_bytes(), original)
        with post(**edit) as response:
            self.assertTrue(json.load(response)['backup'])
        self.assertEqual(json.loads(target.read_bytes())['bs']['test'], {'hsv': 3, 'nps': 1})
        self.assertFalse((self.root / 'default3/birds.stuff').exists())
        with self.assertRaises(HTTPError) as error:
            post(**edit)
        self.assertIn('changed', json.load(error.exception)['error'])
        with post(action='undo') as response:
            self.assertIn('restored', json.load(response)['message'])
        self.assertEqual(target.read_bytes(), original)

    def test_doctor_level_set_and_undo(self):
        original={p:p.read_bytes() for p in self.root.rglob('*.stuff')}
        target=self.root/'default2/variables.stuff'
        backup=saves.set_doctor_level(self.root,self.package/'backups',2,4,check_closed=lambda:None)
        self.assertIsNotNone(backup)
        actual=json.loads(target.read_text())
        self.assertEqual(actual['sR'],3)
        self.assertEqual(actual['flags']['BZ'],1)
        self.assertEqual(actual['flags']['Jv'],0)
        self.assertEqual(actual['UA'],0)
        for p,raw in original.items():
            if p!=target:self.assertEqual(p.read_bytes(),raw)
        saves.undo(self.root,backup,check_closed=lambda:None,slot_number=2)
        self.assertEqual(target.read_bytes(),original[target])

    def test_doctor_level_validation(self):
        original={p:p.read_bytes() for p in self.root.rglob('*.stuff')}
        for level in (0, 5, '4', -1):
            with self.assertRaises(saves.ModError):
                saves.set_doctor_level(self.root,self.package/'backups',2,level,check_closed=lambda:None)
        def running():raise saves.ModError('Game running')
        with self.assertRaises(saves.ModError):
            saves.set_doctor_level(self.root,self.package/'backups',2,4,check_closed=running)
        for p,raw in original.items():self.assertEqual(p.read_bytes(),raw)

    def test_doctor_console_commands(self):
        commands=iter(['JD','exit'])
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            console.session(2,self.root,self.package,lambda _:next(commands),lambda:None)
        actual=json.loads((self.root/'default2/variables.stuff').read_text())
        self.assertEqual(actual['sR'],3)
        self.assertIn('Junior Head Doctor',output.getvalue())

    def test_doctor_direct_cli(self):
        ret=console.main(['JD','2'], root=self.root, package=self.package, check_closed=lambda:None)
        self.assertEqual(ret,0)
        actual=json.loads((self.root/'default2/variables.stuff').read_text())
        self.assertEqual(actual['sR'],3)

    def test_slot1_in_default_folder_and_version1(self):
        def_folder = self.root / 'default'
        def_folder.mkdir(parents=True, exist_ok=True)
        (def_folder / 'sasquatch.stuff').write_text(json.dumps({'VERSION':1, 'coins':10, 'bankcoin':0, 'current_map':'test', 'map_locations':{}}))
        (def_folder / 'inventory.stuff').write_text('unchanged')
        commands = iter(['C = 500k', 'exit'])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            console.session(1, self.root, self.package, lambda _: next(commands), lambda: None)
        actual = json.loads((def_folder / 'sasquatch.stuff').read_text())
        self.assertEqual(actual['coins'], 500000)
        self.assertEqual(actual['VERSION'], 1)

    def test_sneaky_shoes_and_all_shoes(self):
        saves.activate_sneaky_shoes(self.root, self.package / 'backups', 2, check_closed=lambda: None)
        eq = json.loads((self.root / 'default2/equipment.stuff').read_text())
        save = json.loads((self.root / 'default2/sasquatch.stuff').read_text())
        self.assertTrue(any(x.get('type') == 469 for x in eq['equipment']))
        self.assertEqual(save.get('togtool', {}).get('T9'), 1)

        saves.unlock_all_shoes(self.root, self.package / 'backups', 2, check_closed=lambda: None)
        eq2 = json.loads((self.root / 'default2/equipment.stuff').read_text())
        save2 = json.loads((self.root / 'default2/sasquatch.stuff').read_text())
        self.assertTrue(any(x.get('type') == 2524 for x in eq2['equipment']))
        self.assertTrue(any(x.get('type') == 469 for x in eq2['equipment']))
        self.assertEqual(save2['togtool']['runshoes'], 1)
        self.assertEqual(save2['togtool']['T9'], 1)
        self.assertEqual(save2['togtool']['SK'], 1)

    def test_own_car_template_and_maxcars(self):
        # Slot 3 doesn't have polcar initially, and neither does slot 1
        saves.own_car(self.root, self.package / 'backups', 3, 'polcar', check_closed=lambda: None)
        eq = json.loads((self.root / 'default3/equipment.stuff').read_text())
        self.assertTrue(any(v.get('id') == 'polcar' for v in eq['vehicles']))

        saves.own_all_cars(self.root, self.package / 'backups', 3, max_level=True, check_closed=lambda: None)
        eq_all = json.loads((self.root / 'default3/equipment.stuff').read_text())
        car_ids = {v['id'] for v in eq_all['vehicles']}
        self.assertTrue(saves.BASIC_CARS.issubset(car_ids))

    def test_c_and_o_console_menus(self):
        # Test C menu flow: select '1' then '777', and O menu flow: select 'sneaky'
        commands = iter(['C', '1', '777', 'O', 'sneaky', 'exit'])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            console.session(2, self.root, self.package, lambda _: next(commands), lambda: None)
        save = json.loads((self.root / 'default2/sasquatch.stuff').read_text())
        self.assertEqual(save['coins'], 777)
        self.assertEqual(save['togtool']['T9'], 1)
        self.assertIn('CURRENCY MENU', output.getvalue())
        self.assertIn('OWNED STUFF MENU', output.getvalue())

    def test_ss_cli_args(self):
        ret = console.main(['s', '2'], root=self.root, package=self.package, check_closed=lambda: None, read=lambda _: 'exit')
        self.assertEqual(ret, 0)

    def test_user_metadata_touched_on_save_edit(self):
        u_path = self.root / 'default2/user.stuff'
        u_path.write_text(json.dumps({'st': 1000, 'sc': 50, 'lst': 'token123', 'gert': {'token123': 50}}))
        saves.apply(self.root, self.package / 'backups', coins=500, check_closed=lambda: None, slot_number=2)
        u_data = json.loads(u_path.read_text())
        self.assertGreater(u_data['st'], 1000)
        self.assertGreater(u_data['sc'], 50)
        self.assertEqual(u_data['gert']['token123'], u_data['sc'])

    def test_firefighter_funding_and_undo(self):
        original = (self.root / 'default2/variables.stuff').read_bytes()
        backup = saves.set_firefighter_funding(self.root, self.package / 'backups', 2, 750000, check_closed=lambda: None)
        self.assertIsNotNone(backup)
        v = json.loads((self.root / 'default2/variables.stuff').read_text())
        self.assertEqual(v['sM'], 750000)

        info = saves.get_firefighter_info(self.root, 2)
        self.assertEqual(info['funding'], 750000)

        saves.undo(self.root, backup, check_closed=lambda: None, slot_number=2)
        self.assertEqual((self.root / 'default2/variables.stuff').read_bytes(), original)

    def test_firefighter_level_and_max_fire(self):
        backup = saves.set_firefighter_level(self.root, self.package / 'backups', 2, 8, check_closed=lambda: None)
        self.assertIsNotNone(backup)
        v = json.loads((self.root / 'default2/variables.stuff').read_text())
        self.assertEqual(v['Og'], 7)
        self.assertEqual(v['flags']['3N'], 0)

        info = saves.get_firefighter_info(self.root, 2)
        self.assertEqual(info['level'], 8)
        self.assertEqual(info['rank'], 'Junior Battalion Chief')

        backup2 = saves.max_fire_station(self.root, self.package / 'backups', 2, check_closed=lambda: None)
        v2 = json.loads((self.root / 'default2/variables.stuff').read_text())
        self.assertGreaterEqual(v2['sM'], 500000)
        self.assertEqual(v2['Og'], 7)
        for k, max_v in saves.FIRE_UPGRADES_MAX.items():
            self.assertEqual(v2[k], max_v)

    def test_custom_variable_and_undo(self):
        backup = saves.set_custom_variable(self.root, self.package / 'backups', 2, 'my_custom_key', 4242, check_closed=lambda: None)
        v = json.loads((self.root / 'default2/variables.stuff').read_text())
        self.assertEqual(v['my_custom_key'], 4242)

        saves.set_custom_variable(self.root, self.package / 'backups', 2, 'flag:special_unlocked', 1, check_closed=lambda: None)
        v2 = json.loads((self.root / 'default2/variables.stuff').read_text())
        self.assertEqual(v2['flags']['special_unlocked'], 1)

    def test_firefighter_console_commands(self):
        commands = iter(['FF = 250k', 'fire rank 8', 'maxfire', 'exit'])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            console.session(2, self.root, self.package, lambda _: next(commands), lambda: None)
        v = json.loads((self.root / 'default2/variables.stuff').read_text())
        self.assertGreaterEqual(v['sM'], 500000)
        self.assertEqual(v['Og'], 7)
        self.assertIn('Junior Battalion Chief', output.getvalue())

    def test_http_firefighter_and_new_actions(self):
        base = self.start_server()
        with urlopen(base + '/api/state?slot=2') as r:
            state = json.load(r)
        self.assertIn('firefighter', state)
        self.assertIn('doctor', state)
        self.assertIn('shoes', state)

        # Test fire_funding action
        body = json.dumps({'slot': 2, 'action': 'fire_funding', 'value': '100000'}).encode()
        req = Request(base + '/api/edit', data=body, headers={'Content-Type': 'application/json', 'Origin': base, 'X-SS-Token': state['token']})
        with urlopen(req) as r:
            res = json.load(r)
        self.assertIn('100,000', res['message'])
        self.assertEqual(res['firefighter']['funding'], 100000)

        # Test max_currencies action
        body = json.dumps({'slot': 2, 'action': 'max_currencies'}).encode()
        req = Request(base + '/api/edit', data=body, headers={'Content-Type': 'application/json', 'Origin': base, 'X-SS-Token': state['token']})
        with urlopen(req) as r:
            res = json.load(r)
        self.assertIn('2,000,000', res['message'])

        # Test max_fire action
        body = json.dumps({'slot': 2, 'action': 'max_fire'}).encode()
        req = Request(base + '/api/edit', data=body, headers={'Content-Type': 'application/json', 'Origin': base, 'X-SS-Token': state['token']})
        with urlopen(req) as r:
            res = json.load(r)
        self.assertIn('Junior Battalion Chief', res['message'])
        self.assertEqual(res['firefighter']['level'], 8)

        # Test custom_var action
        body = json.dumps({'slot': 2, 'action': 'custom_var', 'key': 'secret_pass', 'value': '12345'}).encode()
        req = Request(base + '/api/edit', data=body, headers={'Content-Type': 'application/json', 'Origin': base, 'X-SS-Token': state['token']})
        with urlopen(req) as r:
            res = json.load(r)
        self.assertIn('secret_pass', res['message'])

    def test_slowmobile_and_all_vehicles_unlock(self):
        # 1. Slot 3 does not have snowmobile (VL) initially
        status_before = saves.get_all_vehicles_status(self.root, 3)
        vl_entry = next(v for v in status_before if v['id'] == 'VL')
        self.assertFalse(vl_entry['owned'])

        # 2. Unlock using alias "slow mobile"
        saves.own_car(self.root, self.package / 'backups', 3, 'slow mobile', check_closed=lambda: None)
        eq = json.loads((self.root / 'default3/equipment.stuff').read_text())
        self.assertTrue(any(v.get('id') == 'VL' for v in eq['vehicles']))

        # Verify status now reports VL as owned
        status_after = saves.get_all_vehicles_status(self.root, 3)
        vl_entry_after = next(v for v in status_after if v['id'] == 'VL')
        self.assertTrue(vl_entry_after['owned'])
        self.assertEqual(vl_entry_after['name'], 'Snowmobile')

        # 3. Unlock ALL vehicles
        saves.own_all_known_vehicles(self.root, self.package / 'backups', 3, max_level=True, check_closed=lambda: None)
        eq_all = json.loads((self.root / 'default3/equipment.stuff').read_text())
        all_ids = {v['id'] for v in eq_all['vehicles']}
        # Verify key vehicles are all present
        self.assertIn('VL', all_ids) # Snowmobile
        self.assertIn('pickupTruck', all_ids) # Pickup
        self.assertIn('dj', all_ids) # Forklift
        self.assertIn('supercar', all_ids)
        self.assertIn('Jo', all_ids) # 4x4

        status_full = saves.get_all_vehicles_status(self.root, 3)
        self.assertTrue(all(v['owned'] for v in status_full))

    def test_halloween_event_candy_and_bowls(self):
        # 1. Halloween event toggle
        saves.set_halloween_event(self.root, self.package / 'backups', 2, active=True, check_closed=lambda: None)
        info = saves.get_halloween_info(self.root, 2)
        self.assertTrue(info['active'])

        # 2. Set Halloween candy currency
        saves.set_halloween_candy(self.root, self.package / 'backups', 2, 7500, check_closed=lambda: None)
        info2 = saves.get_halloween_info(self.root, 2)
        self.assertEqual(info2['candy'], 7500)

        # 3. Set up a dummy map file with collected candy bowl flag
        map_dir = self.root / 'default2/map'
        map_dir.mkdir(parents=True, exist_ok=True)
        dummy_map = map_dir / 'test_map.stuff'
        dummy_map.write_text(json.dumps({
            'VERSION': 1,
            'csd': {'candy_collected_1': 1},
            'objects': [{'id': 'bowl_1', 'cD': {'alreadyCollected': True}}]
        }))

        # Refill candy bowls
        saves.refill_candy_bowls(self.root, self.package / 'backups', 2, check_closed=lambda: None)
        map_data = json.loads(dummy_map.read_text())
        self.assertNotIn('candy_collected_1', map_data['csd'])
        self.assertFalse(map_data['objects'][0]['cD']['alreadyCollected'])

    def test_http_vehicles_and_halloween_api(self):
        base = self.start_server()
        with urlopen(base + '/api/state?slot=2') as r:
            state = json.load(r)
        self.assertIn('allVehicles', state)
        self.assertIn('halloween', state)

        # Test unlocking slow mobile via API
        body = json.dumps({'slot': 2, 'action': 'own', 'car': 'slow mobile'}).encode()
        req = Request(base + '/api/edit', data=body, headers={'Content-Type': 'application/json', 'Origin': base, 'X-SS-Token': state['token']})
        with urlopen(req) as r:
            res = json.load(r)
        self.assertIn('slow mobile', res['message'])
        vl_item = next(v for v in res['allVehicles'] if v['id'] == 'VL')
        self.assertTrue(vl_item['owned'])

        # Test refill candy bowls via API
        body = json.dumps({'slot': 2, 'action': 'refill_candy_bowls'}).encode()
        req = Request(base + '/api/edit', data=body, headers={'Content-Type': 'application/json', 'Origin': base, 'X-SS-Token': state['token']})
        with urlopen(req) as r:
            res = json.load(r)
        self.assertIn('refilled', res['message'])
        self.assertTrue(res['halloween']['active'])

        # Test set candy via API
        body = json.dumps({'slot': 2, 'action': 'halloween_candy', 'value': '15000'}).encode()
        req = Request(base + '/api/edit', data=body, headers={'Content-Type': 'application/json', 'Origin': base, 'X-SS-Token': state['token']})
        with urlopen(req) as r:
            res = json.load(r)
        self.assertEqual(res['halloween']['candy'], 15000)

        # Test Christmas API
        self.assertIn('christmas', res)
        body = json.dumps({'slot': 2, 'action': 'christmas_event', 'active': True}).encode()
        req = Request(base + '/api/edit', data=body, headers={'Content-Type': 'application/json', 'Origin': base, 'X-SS-Token': state['token']})
        with urlopen(req) as r:
            res = json.load(r)
        self.assertTrue(res['christmas']['active'])

        body = json.dumps({'slot': 2, 'action': 'christmas_candy_canes', 'value': '50000'}).encode()
        req = Request(base + '/api/edit', data=body, headers={'Content-Type': 'application/json', 'Origin': base, 'X-SS-Token': state['token']})
        with urlopen(req) as r:
            res = json.load(r)
        self.assertEqual(res['christmas']['candyCanes'], 50000)

        body = json.dumps({'slot': 2, 'action': 'unlock_christmas_decorations'}).encode()
        req = Request(base + '/api/edit', data=body, headers={'Content-Type': 'application/json', 'Origin': base, 'X-SS-Token': state['token']})
        with urlopen(req) as r:
            res = json.load(r)
        self.assertTrue(all(d['unlocked'] for d in res['christmas']['decorations'].values()))

        # Test Raccoon Club & Badges API
        self.assertIn('raccoonClub', res)
        body = json.dumps({'slot': 2, 'action': 'raccoon_badges', 'value': 25}).encode()
        req = Request(base + '/api/edit', data=body, headers={'Content-Type': 'application/json', 'Origin': base, 'X-SS-Token': state['token']})
        with urlopen(req) as r:
            res = json.load(r)
        self.assertEqual(res['raccoonClub']['badges'], 25)
        self.assertTrue(res['raccoonClub']['unlocked'])

        body = json.dumps({'slot': 2, 'action': 'unlock_all_badges'}).encode()
        req = Request(base + '/api/edit', data=body, headers={'Content-Type': 'application/json', 'Origin': base, 'X-SS-Token': state['token']})
        with urlopen(req) as r:
            res = json.load(r)
        self.assertEqual(res['raccoonClub']['badges'], 80)
        self.assertEqual(res['raccoonClub']['earnedCount'], 80)
        self.assertTrue(res['raccoonClub']['unlocked'])

    def test_raccoon_club_and_badges(self):
        # 1. Check initial info
        info = saves.get_raccoon_club_info(self.root, 2)
        self.assertFalse(info['unlocked'])

        # 2. Set badges number
        b_badges = saves.set_raccoon_badges(self.root, self.package / 'console-backups', 2, 45, check_closed=lambda: None)
        self.assertIsNotNone(b_badges)
        info2 = saves.get_raccoon_club_info(self.root, 2)
        self.assertEqual(info2['badges'], 45)
        self.assertTrue(info2['unlocked'])  # 45 >= 20 unlocks clubhouse

        # 3. Unlock all 80 badges
        (self.root / 'default2/achievements.stuff').write_text(json.dumps({'VERSION': 1, 'eb': [], 'qb': []}))
        b_all = saves.unlock_all_badges(self.root, self.package / 'console-backups', 2, check_closed=lambda: None)
        info3 = saves.get_raccoon_club_info(self.root, 2)
        self.assertEqual(info3['badges'], 80)
        self.assertEqual(info3['earnedCount'], 80)
        self.assertTrue(info3['unlocked'])

    def test_christmas_event_candy_canes_and_decorations(self):
        # 1. Initial Christmas state is inactive
        info = saves.get_christmas_info(self.root, 2)
        self.assertFalse(info['active'])
        self.assertEqual(info['candyCanes'], 0)
        self.assertFalse(any(d['unlocked'] for d in info['decorations'].values()))

        # 2. Enable Christmas event
        b_event = saves.set_christmas_event(self.root, self.package / 'console-backups', 2, active=True, check_closed=lambda: None)
        self.assertIsNotNone(b_event)
        info2 = saves.get_christmas_info(self.root, 2)
        self.assertTrue(info2['active'])
        self.assertTrue(info2['forceToday'])

        # 3. Set Christmas Candy Canes
        b_canes = saves.set_christmas_candy_canes(self.root, self.package / 'console-backups', 2, 75000, check_closed=lambda: None)
        self.assertIsNotNone(b_canes)
        info3 = saves.get_christmas_info(self.root, 2)
        self.assertEqual(info3['candyCanes'], 75000)

        # 4. Unlock all decorations
        b_decor = saves.unlock_all_christmas_decorations(self.root, self.package / 'console-backups', 2, check_closed=lambda: None)
        self.assertIsNotNone(b_decor)
        info4 = saves.get_christmas_info(self.root, 2)
        self.assertTrue(all(d['unlocked'] for d in info4['decorations'].values()))

        # 5. Calling unlock again when all are unlocked returns None (no-op)
        b_noop = saves.unlock_all_christmas_decorations(self.root, self.package / 'console-backups', 2, check_closed=lambda: None)
        self.assertIsNone(b_noop)

        # 6. Max Christmas grants everything
        b_max = saves.max_christmas(self.root, self.package / 'console-backups', 2, check_closed=lambda: None)
        info5 = saves.get_christmas_info(self.root, 2)
        self.assertTrue(info5['active'])
        self.assertEqual(info5['candyCanes'], 2000000)
        self.assertTrue(all(d['unlocked'] for d in info5['decorations'].values()))

    def test_bird_sanctuary_backend(self):
        # 1. Funding
        saves.set_bird_sanctuary_funding(self.root, self.package / 'backups', 2, 75000, check_closed=lambda: None)
        info = saves.get_bird_sanctuary_info(self.root, 2)
        self.assertEqual(info['funding'], 75000)
        self.assertTrue(info['isPhotographer'])

        # 2. Level
        saves.set_bird_sanctuary_level(self.root, self.package / 'backups', 2, 4, check_closed=lambda: None)
        info = saves.get_bird_sanctuary_info(self.root, 2)
        self.assertEqual(info['level'], 4)

        # 3. Build projects
        saves.build_all_bird_sanctuary_projects(self.root, self.package / 'backups', 2, check_closed=lambda: None)
        info = saves.get_bird_sanctuary_info(self.root, 2)
        self.assertTrue(info['allBuilt'])
        self.assertTrue(all(p['built'] for p in info['projects'].values()))

        # 4. Complete Bird Guide
        saves.complete_bird_guide(self.root, self.package / 'backups', 2, check_closed=lambda: None)
        info = saves.get_bird_sanctuary_info(self.root, 2)
        self.assertEqual(info['photographedCount'], 40)
        self.assertTrue(all(b['photographed'] for b in info['birds'].values()))

        # 5. Create painted photo
        tiny_png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        photo_id, _ = saves.create_photo(self.root, self.package / 'backups', 2, tiny_png, category='bird', bird_id='qL', quality=3, check_closed=lambda: None)
        photos = saves.get_photos_list(self.root, 2)
        self.assertTrue(any(p['id'] == photo_id for p in photos))
        matching = next(p for p in photos if p['id'] == photo_id)
        self.assertEqual(matching['birds'][0]['id'], 'qL')
        self.assertEqual(matching['birds'][0]['name'], 'Bald Eagle')

    def test_http_bird_and_photo_api(self):
        base = self.start_server()
        with urlopen(base + '/api/state?slot=2') as r:
            state = json.load(r)
        self.assertIn('birdSanctuary', state)
        self.assertIn('photos', state)
        self.assertIn('allBirds', state)

        # Set bird funding via API
        body = json.dumps({'slot': 2, 'action': 'bird_funding', 'value': '125000'}).encode()
        req = Request(base + '/api/edit', data=body, headers={'Content-Type': 'application/json', 'Origin': base, 'X-SS-Token': state['token']})
        with urlopen(req) as r:
            res = json.load(r)
        self.assertIn('125,000', res['message'])
        self.assertEqual(res['birdSanctuary']['funding'], 125000)

        # Create photo via API
        tiny_b64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        body = json.dumps({
            'slot': 2,
            'action': 'create_photo',
            'image_data': tiny_b64,
            'category': 'bird',
            'bird_id': 'V2',
            'quality': 3
        }).encode()
        req = Request(base + '/api/edit', data=body, headers={'Content-Type': 'application/json', 'Origin': base, 'X-SS-Token': state['token']})
        with urlopen(req) as r:
            res = json.load(r)
        self.assertIn('Mallard', res['message'])

        # Verify photo was added to photos list
        photo_id = res['photos'][0]['id']
        # Fetch image endpoint
        with urlopen(base + f'/api/photo_image/{photo_id}?slot=2') as r:
            img_bytes = r.read()
            ct = r.headers.get('Content-Type')
        self.assertEqual(ct, 'image/png')
        self.assertTrue(img_bytes.startswith(b'\x89PNG\r\n\x1a\n'))

if __name__=='__main__':unittest.main()
