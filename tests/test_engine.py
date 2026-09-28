import io
import json
import logging
from pathlib import Path
import socket
import struct
import tempfile
import unittest
import importlib.util
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import requests
from urllib3.exceptions import ProtocolError
import ahu_login as app


class EngineTests(unittest.TestCase):
    def row(self, ip='172.21.4.242', index=18, hardware=True):
        return dict(ip=ip, index=index, hardware=hardware)

    def test_normal_path_never_starts_powershell(self):
        with patch.object(app, 'route_source', return_value='172.21.4.242'), patch.object(app, 'network_inventory') as scan:
            self.assertEqual(app.get_selection({}), app.Selection('172.21.4.242'))
            scan.assert_not_called()

    def test_tun_fallback_does_not_wait_twenty_seconds(self):
        with patch.object(app, 'route_source', return_value='198.18.0.1'), patch.object(app, 'network_inventory', return_value=[self.row(), self.row('198.18.0.1', 59, False)]), patch.object(app.time, 'sleep') as sleep:
            self.assertEqual(app.get_selection({}), app.Selection('172.21.4.242', 18))
            sleep.assert_not_called()

    def test_dhcp_wait_then_normal_route(self):
        with patch.object(app, 'route_source', side_effect=[None, None, '172.21.4.242']), patch.object(app, 'network_inventory', return_value=[]), patch.object(app.time, 'sleep') as sleep:
            self.assertEqual(app.get_selection({}), app.Selection('172.21.4.242'))
            self.assertEqual(sleep.call_count, 2)

    def test_dhcp_behind_tun_gets_final_scan(self):
        with patch.object(app, 'route_source', return_value='198.18.0.1'), patch.object(app, 'network_inventory', side_effect=[[], [self.row()]]) as scan, patch.object(app.time, 'sleep'):
            self.assertEqual(app.get_selection({}, attempts=3).index, 18)
            self.assertEqual(scan.call_count, 2)

    def test_no_campus_is_bounded(self):
        with patch.object(app, 'route_source', return_value='192.168.1.2'), patch.object(app, 'network_inventory', return_value=[self.row('192.168.1.2')]) as scan, patch.object(app.time, 'sleep') as sleep:
            self.assertIsNone(app.get_selection({}))
            self.assertEqual(scan.call_count, 2)
            self.assertEqual(sleep.call_count, 19)

    def test_inventory_failure_does_not_block_later_valid_route(self):
        with patch.object(app, 'route_source', side_effect=[None, '172.21.4.242']), patch.object(app, 'network_inventory', side_effect=OSError), patch.object(app.time, 'sleep'):
            self.assertEqual(app.get_selection({}).ip, '172.21.4.242')

    def test_ambiguity_never_chooses_first(self):
        with self.assertRaises(ValueError):
            app.select_fallback([self.row(), self.row('10.1.2.3', 20)], app.DEFAULT_PREFIXES)

    def test_physical_preferred_without_excluding_virtual_override(self):
        rows = [self.row('10.1.2.3', 20, False), self.row()]
        self.assertEqual(app.select_fallback(rows, app.DEFAULT_PREFIXES).index, 18)
        self.assertEqual(app.select_fallback(rows, app.DEFAULT_PREFIXES, 20).index, 20)

    def test_override_honored_even_with_valid_default_route(self):
        with patch.object(app, 'route_source', return_value='172.21.4.242'), patch.object(app, 'network_inventory', return_value=[self.row('10.1.2.3', 20)]):
            self.assertEqual(app.get_selection({'CAMPUS_INTERFACE_INDEX':'20'}), app.Selection('10.1.2.3', 20))

    def test_prefixes_and_exclusions(self):
        self.assertTrue(app.is_valid_campus_ip('172.22.1.2', ('172.22.',)))
        for ip in ('198.18.0.1','198.19.0.1','127.0.0.1','169.254.1.1','192.168.1.1'):
            self.assertFalse(app.is_valid_campus_ip(ip, ('',)))

    def test_source_binding_options(self):
        adapter = app.SourceAdapter(app.Selection('172.21.4.242', 18))
        opts = adapter.poolmanager.connection_pool_kw
        self.assertEqual(opts['source_address'], ('172.21.4.242', 0))
        self.assertIn((socket.IPPROTO_IP, 31, struct.pack('!I', 18)), opts['socket_options'])
        adapter.close()

    def test_direct_path_has_no_forced_interface(self):
        adapter = app.SourceAdapter(app.Selection('172.21.4.242'))
        self.assertFalse(any(option[1] == 31 for option in adapter.poolmanager.connection_pool_kw['socket_options']))
        adapter.close()

    def test_request_parameters_and_encoding(self):
        env = {'CAMPUS_ACCOUNT':'E123@telecom', 'CAMPUS_PASSWORD':'a&b=+%#中文'}
        request = requests.Request('GET', app.TARGET_URL, params=app.payload_for('172.21.4.242', env)).prepare()
        self.assertEqual(urlsplit(request.url).path, '/eportal/')
        values = parse_qs(urlsplit(request.url).query)
        self.assertEqual(values, {k:[v] for k,v in {
            'c':'Portal','a':'login','callback':'dr1003','login_method':'1',
            'user_account':env['CAMPUS_ACCOUNT'],'user_password':env['CAMPUS_PASSWORD'],
            'wlan_user_ip':'172.21.4.242','jsVersion':'3.3.2','terminal_type':'1','v':'7379','lang':'zh-cn'}.items()})

    def test_payload_matches_original_source(self):
        spec = importlib.util.spec_from_file_location('legacy', Path(__file__).with_name('legacy_login.py'))
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        env = {'CAMPUS_ACCOUNT':'E123@telecom', 'CAMPUS_PASSWORD':'a&b=+%#中文'}
        session = Mock()
        session.get.return_value = Mock(status_code=200, text='{}')
        with patch.object(old.requests, 'Session', return_value=session), patch.object(old, 'log'):
            old.login('172.21.4.242', env)
        self.assertEqual(app.TARGET_URL, old.TARGET_URL)
        self.assertEqual(app.payload_for('172.21.4.242', env), session.get.call_args.kwargs['params'])

    def test_auth_failure_propagates_exit_code(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'.env').write_text('CAMPUS_ACCOUNT=FAKE\nCAMPUS_PASSWORD=FAKE\n')
            with patch.object(app, 'get_selection', return_value=app.Selection('172.21.4.242')), patch.object(app, 'request_portal', return_value=(5,'authentication_rejected')):
                self.assertEqual(app.main(['--config-dir',folder]), 5)

    def test_delay_uses_sleep_before_selecting(self):
        sequence = []
        with tempfile.TemporaryDirectory() as folder, patch.object(app.time, 'sleep', side_effect=lambda n: sequence.append(('sleep',n))), patch.object(app, 'get_selection', side_effect=lambda _: sequence.append(('select',0)) or app.Selection('172.21.4.242')):
            self.assertEqual(app.main(['--diagnose','--delay','15','--config-dir',folder]), 0)
        self.assertEqual(sequence, [('sleep',15),('select',0)])

    def test_response_matrix(self):
        cases = [(200, '{"result":1}', 0), (200, 'dr1003({"result":"1"});', 0),
                 (200, 'dr1003({"result":"0","ret_code":2})', 0),
                 (200, '{"result":0,"ret_code":"2"}', 0),
                 (200, '{"result":0,"ret_code":1}', 5), (200, '<html>login</html>', 6),
                 (200, 'null', 6), (200, '{}', 6), (200, '{"result":true}', 6), (302, '', 4), (503, '', 4)]
        for status, body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(app.classify_response(status, body)[0], expected)

    def fake_session(self, body=b'{"result":1}'):
        response = Mock(status_code=200)
        response.raw.read.return_value = body
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        session = Mock()
        session.get.return_value = response
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        return session, response

    def test_no_proxy_redirect_or_extra_auth_attempt(self):
        session, _ = self.fake_session(b'{"result":0,"ret_code":1}')
        with patch.object(app.requests, 'Session', return_value=session):
            self.assertEqual(app.request_portal(app.Selection('172.21.4.242'), {'CAMPUS_ACCOUNT':'x','CAMPUS_PASSWORD':'y'})[0], 5)
        self.assertFalse(session.trust_env)
        self.assertFalse(session.get.call_args.kwargs['allow_redirects'])
        self.assertEqual(session.get.call_count, 1)

    def test_probe_never_sends_credentials(self):
        session, _ = self.fake_session()
        with patch.object(app.requests, 'Session', return_value=session):
            self.assertEqual(app.request_portal(app.Selection('172.21.4.242',18), {}, probe=True)[0], 0)
        self.assertIsNone(session.get.call_args.kwargs['params'])

    def test_exception_logs_do_not_contain_secrets(self):
        session, response = self.fake_session()
        response.raw.read.side_effect = ProtocolError('url?user_password=SECRET_VALUE')
        with patch.object(app.requests, 'Session', return_value=session), self.assertLogs(app.LOG, level='INFO') as captured:
            result = app.request_portal(app.Selection('172.21.4.242'), {'CAMPUS_ACCOUNT':'x','CAMPUS_PASSWORD':'SECRET_VALUE'})
        self.assertEqual(result[0], 4)
        self.assertNotIn('SECRET_VALUE', '\n'.join(captured.output))

    def test_config_semantics_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'.env'
            path.write_text('\ufeff# hi\nCAMPUS_ACCOUNT= E1 \nCAMPUS_PASSWORD=a=b#c%+\nCUSTOM=yes\n', encoding='utf-8')
            self.assertEqual(app.load_env(path), {'CAMPUS_ACCOUNT':'E1','CAMPUS_PASSWORD':'a=b#c%+','CUSTOM':'yes'})

    def test_diagnose_does_not_authenticate(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app, 'get_selection', return_value=app.Selection('172.21.4.242')), patch.object(app, 'request_portal') as send:
            self.assertEqual(app.main(['--diagnose','--config-dir',folder]), 0)
            send.assert_not_called()

    def test_missing_credentials_does_not_query_network(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app, 'get_selection') as scan:
            self.assertEqual(app.main(['--config-dir',folder]), 3)
            scan.assert_not_called()


if __name__ == '__main__':
    unittest.main()
