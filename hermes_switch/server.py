"""
Hermes Switch Web Server
"""
import json, os, sys, signal, socket, time, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# CRITICAL: prevent stale .pyc from overriding source changes
sys.dont_write_bytecode = True

from .endpoints import (
    load_endpoints, save_endpoints,
    get_current, switch_endpoint, test_endpoint, fetch_models,
    auto_discover, undo_switch, has_undo,
    get_provider_family, get_provider_display,
    ENDPOINTS_FILE, CONFIG_FILE
)

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'templates')
DEFAULT_PORT = 9020
SERVER_START_TIME = 0.0
ACTIVE_PROFILE = ''  # Set by run_server()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        if os.environ.get('HERMES_SWITCH_VERBOSE'):
            sys.stderr.write("[%s] %s\n" % (self.address_string(), format % args))

    def _profile(self):
        """Return the active profile name or empty string for default.
        Checks query parameter first, then falls back to global ACTIVE_PROFILE."""
        from urllib.parse import parse_qs
        qs = parse_qs(urlparse(self.path).query)
        qp = qs.get('profile', [None])[0]
        if qp:
            return qp
        return ACTIVE_PROFILE

    def _send_json(self, data, status=200):
        try:
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        except Exception:
            body = json.dumps({'error': '序列化失败'}).encode()
            status = 500
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, path):
        filepath = os.path.join(TEMPLATE_DIR, path)
        if not os.path.exists(filepath):
            self.send_error(404)
            return
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                body = f.read().encode('utf-8')
        except Exception:
            self.send_error(500)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length == 0:
                return {}
            return json.loads(self.rfile.read(length).decode('utf-8'))
        except Exception:
            return {}

    def _enrich_endpoints(self, eps, current):
        """Add computed fields to each endpoint for the UI."""
        for name, ep in eps.items():
            ep['family'] = get_provider_family(ep.get('provider', 'custom'))
            ep['provider_display'] = get_provider_display(ep.get('provider', 'custom'))
            ep['active'] = (
                ep.get('provider') == current['provider'] and
                ep.get('base_url', '') == current.get('base_url', '')
            )
            # Add reasoning options for the provider
            from .capabilities import get_reasoning_options
            ep['_reasoning_options'] = get_reasoning_options(ep.get('provider', 'custom'))
            # Ensure _model_caps exists
            if '_model_caps' not in ep:
                ep['_model_caps'] = {}
        return eps

    @staticmethod
    def _is_auto_discovered(ep):
        """Check if an endpoint was auto-discovered vs user-added."""
        src = (ep.get('_source') or ep.get('note', '') or '').lower()
        auto_keywords = ['环境变量', '当前配置', 'config custom', 'profile', '检测到', 'env:']
        return any(k in src for k in auto_keywords)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        try:
            self._do_GET()
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def _do_GET(self):
        path = urlparse(self.path).path

        if path in ('/', '/index.html'):
            self._send_html('index.html')

        elif path == '/api/endpoints':
            try:
                eps = load_endpoints(self._profile())
                current = get_current(self._profile())
                eps = self._enrich_endpoints(eps, current)
            except Exception as e:
                self._send_json({'error': f'读取配置失败: {e}', 'endpoints': {}, 'current': {}}, 500)
                return
            num_available = sum(1 for e in eps.values() if e.get('_models'))
            self._send_json({
                'endpoints': eps,
                'current': current,
                'stats': {
                    'total': len(eps),
                    'with_models': num_available,
                }
            })

        elif path == '/api/rescan':
            discovered = auto_discover(self._profile())
            existing = load_endpoints(self._profile())
            # Keep user-added endpoints, replace auto-discovered ones with fresh data
            fresh = dict(discovered)
            for name, ep in existing.items():
                if name not in fresh and not Handler._is_auto_discovered(ep):
                    fresh[name] = ep
            save_endpoints(fresh, self._profile())
            self._send_json({'ok': True, 'found': len(discovered), 'total': len(fresh), 'kept': len(fresh) - len(discovered)})

        elif path == '/api/fetch-models':
            """Lightweight: get model list from an endpoint (no chat test)."""
            qs = parse_qs(urlparse(self.path).query)
            url = qs.get('url', [''])[0]
            key = qs.get('key', [''])[0]
            prov = qs.get('provider', ['custom'])[0]
            proxy = qs.get('proxy', [''])[0]
            # Use enriched fetch that also parses model capabilities
            from .capabilities import enrich_fetch_models_result
            result = enrich_fetch_models_result(url, key, prov, proxy)
            self._send_json(result)

        elif path == '/api/debug':
            from . import endpoints as ep
            import inspect
            src = inspect.getsource(ep.test_endpoint)
            self._send_json({
                'version': '4.0',
                'endpoints_file': ep.__file__,
                'known_providers': list(ep.KNOWN_PROVIDERS.keys()),
                'env_file': ep.ENV_FILE,
                'env_exists': __import__('os').path.exists(ep.ENV_FILE),
                'has_fetch_models': hasattr(ep, 'fetch_models'),
            })

        elif path == '/api/current':
            cur = get_current(self._profile())
            cur['provider_display'] = get_provider_display(cur.get('provider', ''))
            cur['profile'] = self._profile()
            self._send_json(cur)

        elif path == '/api/profiles':
            """List available profiles."""
            import glob
            profiles_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'profiles')
            if not os.path.isdir(profiles_dir):
                profiles_dir = os.path.join(os.path.expanduser('~/.hermes' if os.name != 'nt' else os.environ.get('LOCALAPPDATA', os.path.expanduser('~/AppData/Local')) + '/hermes'), 'profiles')
            profiles = []
            if os.path.isdir(profiles_dir):
                for p in sorted(os.listdir(profiles_dir)):
                    if os.path.isfile(os.path.join(profiles_dir, p, 'config.yaml')):
                        profiles.append(p)
            self._send_json({'profiles': profiles, 'active': self._profile()})

        elif path == '/api/health':
            """Quick health check for process management."""
            nonlocal_start = __import__('hermes_switch.server', fromlist=['SERVER_START_TIME']).SERVER_START_TIME
            self._send_json({
                'ok': True,
                'version': '4.0',
                'pid': os.getpid(),
                'uptime': int(time.time() - nonlocal_start) if nonlocal_start else 0,
            })

        elif path == '/api/undo':
            self._send_json({'available': has_undo(self._profile())})

        elif path == '/api/test':
            qs = parse_qs(urlparse(self.path).query)
            name = qs.get('name', [None])[0]
            if not name:
                self._send_json({'error': 'name required'}, 400)
                return
            eps = load_endpoints(self._profile())
            if name not in eps:
                self._send_json({'error': f'端点 "{name}" 不存在'}, 404)
                return
            ep = eps[name]
            result = test_endpoint(
                ep.get('base_url', ''),
                ep.get('api_key', ''),
                ep.get('provider', 'custom'),
                ep.get('proxy', '')
            )
            # On success, cache models
            if result.get('ok') and result.get('models'):
                eps[name]['_models'] = result['models']
                save_endpoints(eps, self._profile())
            self._send_json(result)

        else:
            self.send_error(404)

    def do_POST(self):
        try:
            self._do_POST()
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def _do_POST(self):
        path = urlparse(self.path).path
        data = self._read_body()

        if path == '/api/endpoints':
            name = data.get('name', '').strip()
            if not name:
                self._send_json({'error': '名称不能为空'}, 400)
                return
            if '/' in name or '\\' in name:
                self._send_json({'error': '名称不能包含 / 或 \\'}, 400)
                return
            eps = load_endpoints(self._profile())
            if name in eps:
                self._send_json({'error': f'端点 "{name}" 已存在'}, 409)
                return
            model = data.get('model', '').strip()
            all_models = data.get('_models', [])
            eps[name] = {
                'base_url': data.get('base_url', '').strip(),
                'api_key': data.get('api_key', '').strip(),
                'provider': data.get('provider', 'custom').strip(),
                'model': model,
                'note': data.get('note', '').strip(),
                'proxy': data.get('proxy', '').strip(),
                '_models': all_models if isinstance(all_models, list) else [],
                '_model_caps': data.get('_model_caps', {}),
                '_params': data.get('_params', {}),
            }
            save_endpoints(eps, self._profile())
            self._send_json({'ok': True, 'name': name})

        elif path == '/api/switch':
            name = data.get('name', '')
            model = data.get('model', None) or None
            params = data.get('params', None) or None
            if not name:
                self._send_json({'error': '端点名称不能为空'}, 400)
                return
            try:
                ep = switch_endpoint(name, model, params, self._profile())
                self._send_json({
                    'ok': True,
                    'switched': name,
                    'provider': ep.get('provider', ''),
                    'model': model or ep.get('model', ''),
                    'note': f'已切换到 "{name}" — /reset 生效'
                })
            except ValueError as e:
                self._send_json({'error': str(e)}, 404)
            except Exception as e:
                self._send_json({'error': f'切换失败: {e}'}, 500)

        elif path == '/api/undo':
            try:
                prev = undo_switch(self._profile())
                self._send_json({
                    'ok': True,
                    'restored': prev.get('provider', ''),
                    'model': prev.get('default', ''),
                })
            except ValueError as e:
                self._send_json({'error': str(e)}, 404)
            except Exception as e:
                self._send_json({'error': f'撤销失败: {e}'}, 500)

        elif path == '/api/stop':
            """Shut down the server gracefully."""
            self._send_json({'ok': True, 'message': '正在关闭…'})
            import threading
            threading.Thread(target=lambda: (
                time.sleep(0.1),
                _cleanup_server(),
                os._exit(0)
            ), daemon=True).start()

        elif path == '/api/model-caps':
            """Save model capabilities for an endpoint."""
            name = data.get('name', '')
            model = data.get('model', '')
            caps = data.get('caps', {})
            if not name or not model:
                self._send_json({'error': '需要端点名和模型名'}, 400)
                return
            eps = load_endpoints(self._profile())
            if name not in eps:
                self._send_json({'error': f'端点 "{name}" 不存在'}, 404)
                return
            if '_model_caps' not in eps[name]:
                eps[name]['_model_caps'] = {}
            eps[name]['_model_caps'][model] = caps
            save_endpoints(eps, self._profile())
            self._send_json({'ok': True})

        else:
            self.send_error(404)

    def do_PUT(self):
        try:
            self._do_PUT()
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def _do_PUT(self):
        path = urlparse(self.path).path
        if not path.startswith('/api/endpoints/'):
            self.send_error(404)
            return
        name = path.split('/')[-1]
        eps = load_endpoints(self._profile())
        if name not in eps:
            self._send_json({'error': f'端点 "{name}" 不存在'}, 404)
            return
        data = self._read_body()
        existing = eps[name]
        all_models = data.get('_models', existing.get('_models', []))
        eps[name] = {
            'base_url': data.get('base_url', existing.get('base_url', '')).strip(),
            'api_key': data.get('api_key', existing.get('api_key', '')).strip(),
            'provider': data.get('provider', existing.get('provider', 'custom')).strip(),
            'model': data.get('model', existing.get('model', '')).strip(),
            'note': data.get('note', existing.get('note', '')).strip(),
            'proxy': data.get('proxy', existing.get('proxy', '')).strip(),
            '_models': all_models if isinstance(all_models, list) else existing.get('_models', []),
            '_model_caps': existing.get('_model_caps', {}),
            '_params': existing.get('_params', {}),
        }
        save_endpoints(eps, self._profile())
        self._send_json({'ok': True, 'name': name})

    def do_DELETE(self):
        try:
            self._do_DELETE()
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def _do_DELETE(self):
        path = urlparse(self.path).path
        if not path.startswith('/api/endpoints/'):
            self.send_error(404)
            return
        name = path.split('/')[-1]
        eps = load_endpoints(self._profile())
        if name not in eps:
            self._send_json({'error': f'端点 "{name}" 不存在'}, 404)
            return
        del eps[name]
        save_endpoints(eps, self._profile())
        self._send_json({'ok': True, 'deleted': name})


def _find_free_port(start=DEFAULT_PORT, end=9050):
    for port in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    return None


def _cleanup_server():
    """Cleanup PID file on shutdown."""
    from .endpoints import remove_pid
    remove_pid()


def run_server(host='127.0.0.1', port=None, open_browser=True, profile=''):
    import glob
    from .endpoints import write_pid, kill_previous_instance, PID_FILE

    # Set active profile globally for handlers
    global ACTIVE_PROFILE
    ACTIVE_PROFILE = profile

    # Kill previous instance if running
    killed = kill_previous_instance()
    if killed:
        print("  👋 已关闭旧的 Hermes Switch 实例")
        import time as _t
        _t.sleep(0.5)  # Wait for port release

    pkg_dir = os.path.dirname(__file__)
    for pattern in [os.path.join(pkg_dir, '__pycache__', '*.pyc'),
                    os.path.join(pkg_dir, '*.pyc')]:
        for f in glob.glob(pattern):
            try:
                os.remove(f)
            except Exception:
                pass
    for cache_dir in glob.glob(os.path.join(pkg_dir, '**/__pycache__'), recursive=True):
        try:
            import shutil
            shutil.rmtree(cache_dir)
        except Exception:
            pass

    if port is None:
        port = _find_free_port()
        if port is None:
            print("❌ 无法找到可用端口 (9020-9050 都被占用)")
            sys.exit(1)

    for attempt in range(3):
        try:
            server = HTTPServer((host, port), Handler)
            break
        except OSError:
            if attempt < 2:
                port = _find_free_port(port + 1)
                if port is None:
                    print("❌ 无法找到可用端口")
                    sys.exit(1)
            else:
                raise

    # Register cleanup on shutdown
    def _shutdown_handler(sig, frame):
        print('\n  已停止')
        _cleanup_server()
        sys.exit(0)

    if hasattr(signal, 'SIGINT'):
        signal.signal(signal.SIGINT, _shutdown_handler)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, _shutdown_handler)

    # Write PID file
    global SERVER_START_TIME
    SERVER_START_TIME = time.time()
    write_pid()

    url = f'http://{host}:{port}'
    print(f'\n  ⚡ Hermes Switch → {url}')
    print(f'  按 Ctrl+C 停止\n')

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n  已停止')
        server.shutdown()
