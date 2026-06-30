"""
Hermes Switch — 多端点管理器核心逻辑

核心概念：
  - Provider: 服务商类型 (deepseek, openai, custom 等)
  - Endpoint: 一个具体的 API 接入点（包含 provider + base_url + api_key + 默认模型）
  - Model: 某个端点上可用的具体模型名

每个 endpoint 有唯一名称，切换时指定 endpoint + 可选的 model。
"""
import os, json, yaml, sys, ssl, time, urllib.request
from urllib.parse import urlparse


def _hermes_dir(profile=None):
    if os.name == 'nt':
        d = os.environ.get('LOCALAPPDATA', '')
        if not d:
            d = os.path.expanduser('~/AppData/Local')
        base = os.path.join(d, 'hermes')
    else:
        base = os.path.expanduser('~/.hermes')
    if profile:
        return os.path.join(base, 'profiles', profile)
    return base

def _active_profile():
    """Detect the active Hermes profile from environment."""
    return os.environ.get('HERMES_PROFILE', '')


def write_pid():
    """Write current process PID to PID file."""
    try:
        os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def kill_previous_instance():
    """Kill any previous Hermes Switch server instance and remove stale PID file."""
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, 'r') as f:
            old_pid = int(f.read().strip())
        if old_pid == os.getpid():
            return False
        # Try to kill
        try:
            os.kill(old_pid, 9 if os.name == 'nt' else signal.SIGTERM)
            return True
        except (OSError, ProcessLookupError):
            # Process already dead
            pass
    except (ValueError, IOError):
        pass
    finally:
        try:
            os.remove(PID_FILE)
        except Exception:
            pass
    return False


def remove_pid():
    """Remove PID file on shutdown."""
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            if pid == os.getpid():
                os.remove(PID_FILE)
    except Exception:
        pass


ENDPOINTS_FILE = os.path.join(_hermes_dir(), 'endpoints.json')
CONFIG_FILE = os.path.join(_hermes_dir(), 'config.yaml')
ENV_FILE = os.path.join(_hermes_dir(), '.env')
PID_FILE = os.path.join(_hermes_dir(), 'hermes-switch.pid')

# 已知 Provider 元信息（内置 = 不需要手动填 base_url，有默认地址）
KNOWN_PROVIDERS = {
    'deepseek':      {'env': 'DEEPSEEK_API_KEY',      'name': 'DeepSeek',         'base': 'https://api.deepseek.com/v1'},
    'openai':        {'env': 'OPENAI_API_KEY',        'name': 'OpenAI',           'base': 'https://api.openai.com/v1'},
    'anthropic':     {'env': 'ANTHROPIC_API_KEY',     'name': 'Anthropic',        'base': 'https://api.anthropic.com'},
    'openrouter':    {'env': 'OPENROUTER_API_KEY',    'name': 'OpenRouter',       'base': 'https://openrouter.ai/api/v1'},
    'xai':           {'env': 'XAI_API_KEY',           'name': 'xAI Grok',         'base': 'https://api.x.ai/v1'},
    'google':        {'env': 'GOOGLE_API_KEY',        'name': 'Google Gemini',    'base': ''},
    'moonshot':      {'env': 'KIMI_API_KEY',           'name': 'Moonshot Kimi',   'base': 'https://api.moonshot.cn/v1'},
    'minimax':       {'env': 'MINIMAX_API_KEY',        'name': 'MiniMax',          'base': 'https://api.minimax.chat/v1'},
    'dashscope':     {'env': 'DASHSCOPE_API_KEY',      'name': 'DashScope (阿里)', 'base': ''},
    'opencode-zen':  {'env': 'OPENCODE_ZEN_API_KEY',   'name': 'OpenCode Zen',     'base': 'https://opencode.ai/zen/v1'},
    'github-copilot':{'env': 'COPILOT_GITHUB_TOKEN',   'name': 'GitHub Copilot',   'base': ''},
    'huggingface':   {'env': 'HF_TOKEN',               'name': 'HuggingFace',      'base': ''},
}


def get_provider_family(provider):
    """判断 provider 是内置的还是自定义的"""
    if provider in KNOWN_PROVIDERS:
        return 'builtin'
    return 'custom'


def get_provider_display(provider):
    """获取 provider 的可读名称"""
    info = KNOWN_PROVIDERS.get(provider)
    return info['name'] if info else provider


def _read_env_vars():
    """Read environment variables from .env file AND os.environ.
    .env file values take priority (loaded later overwrites earlier)."""
    envs = dict(os.environ.items())
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        envs[k.strip()] = v.strip()
        except Exception:
            pass
    return envs


def load_config(profile=None):
    dir = _hermes_dir(profile)
    cfg_file = os.path.join(dir, 'config.yaml')
    if not os.path.exists(cfg_file):
        return {}
    try:
        with open(cfg_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f.read()) or {}
    except Exception:
        return {}


def save_config(cfg, profile=None):
    dir = _hermes_dir(profile)
    os.makedirs(dir, exist_ok=True)
    cfg_file = os.path.join(dir, 'config.yaml')
    with open(cfg_file, 'w', encoding='utf-8') as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)


def load_endpoints():
    """Load endpoints. Auto-discover on first run or if file is empty/corrupted."""
    if os.path.exists(ENDPOINTS_FILE):
        try:
            with open(ENDPOINTS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                return _normalize_all(data)
        except (json.JSONDecodeError, IOError):
            pass

    discovered = auto_discover()
    if discovered:
        save_endpoints(discovered)
    return discovered


def save_endpoints(eps):
    os.makedirs(os.path.dirname(ENDPOINTS_FILE), exist_ok=True)
    with open(ENDPOINTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(eps, f, indent=2, ensure_ascii=False)


def _normalize(ep):
    """Ensure an endpoint dict has all required fields with defaults."""
    return {
        'base_url': ep.get('base_url', ''),
        'api_key': ep.get('api_key', ''),
        'provider': ep.get('provider', 'custom'),
        'model': ep.get('model', ''),
        'note': ep.get('note', ''),
        'proxy': ep.get('proxy', ''),
        '_source': ep.get('_source', ''),
        '_models': ep.get('_models', []),
        '_model_caps': ep.get('_model_caps', {}),
        '_params': ep.get('_params', {}),
    }


def _normalize_all(eps):
    return {k: _normalize(v) for k, v in eps.items()}


def get_current(profile=None):
    cfg = load_config(profile)
    m = cfg.get('model', {})
    key = m.get('api_key', '') or ''
    masked = key[:15] + '...' if len(key) > 15 else (key[:6] + '...' if key else '')
    return {
        'provider': m.get('provider', ''),
        'base_url': m.get('base_url', ''),
        'model': m.get('default', ''),
        'api_key': masked,
    }


def _find_matching_profile(provider, base_url, api_key=''):
    """Check if any profile matches the given provider+base_url combo.
    Returns the profile name if found, None otherwise."""
    profiles_dir = os.path.join(_hermes_dir(), 'profiles')
    if not os.path.isdir(profiles_dir):
        return None
    for pname in sorted(os.listdir(profiles_dir)):
        pcfg_path = os.path.join(profiles_dir, pname, 'config.yaml')
        if not os.path.isfile(pcfg_path):
            continue
        try:
            with open(pcfg_path, 'r', encoding='utf-8') as f:
                pcfg = yaml.safe_load(f.read()) or {}
        except Exception:
            continue
        pm = pcfg.get('model', {})
        if (pm.get('provider') == provider and
                pm.get('base_url', '') == base_url):
            return pname
    return None


def auto_discover():
    """Scan all sources for usable endpoints.

    Sources (priority order, later sources don't overwrite earlier):
    1. Current active config (model section)
    2. custom_providers in main config
    3. All profiles
    4. Profile custom_providers
    """
    discovered = {}
    cfg = load_config()
    model_cfg = cfg.get('model', {})
    envs = _read_env_vars()

    # ── 1) Current active endpoint ──
    cur_provider = model_cfg.get('provider', '')
    cur_url = model_cfg.get('base_url', '')
    cur_model = model_cfg.get('default', '')
    cur_key = model_cfg.get('api_key', '')

    if cur_provider:
        # Determine name: for built-in providers use provider name,
        # for custom with URL, use hostname (but check if a profile matches first)
        if cur_provider in KNOWN_PROVIDERS:
            name = cur_provider
        elif cur_url:
            # Check profiles first - if a profile has the same provider+base_url, use that name
            match = _find_matching_profile(cur_provider, cur_url, cur_key)
            if match:
                name = match
            else:
                try:
                    name = urlparse(cur_url).hostname or cur_provider
                except Exception:
                    name = cur_provider
        else:
            name = cur_provider

        discovered[name] = _normalize({
            'base_url': cur_url,
            'api_key': cur_key,
            'provider': cur_provider,
            'model': cur_model,
            'note': '当前活跃配置',
            '_source': '当前配置',
        })

    # ── 2) Known providers with .env keys — clearly marked as built-in ──
    for provider, info in KNOWN_PROVIDERS.items():
        if info['env'] in envs:
            raw_val = envs[info['env']]
            if raw_val in ('***', 'sk-xxx', 'sk-...'):
                continue
            if raw_val.count('*') > len(raw_val) * 0.5:
                continue
            if len(raw_val) < 10:
                continue
            if provider not in discovered:
                discovered[provider] = _normalize({
                    'base_url': '',
                    'api_key': '',
                    'provider': provider,
                    'model': '',
                    'note': f'检测到 {info["env"]}，Key 从环境变量读取',
                    '_source': f'环境变量 {info["env"]}',
                })

    # ── 3) custom_providers in main config ──
    for name, cp in cfg.get('custom_providers', {}).items():
        if name not in discovered:
            discovered[name] = _normalize({
                'base_url': cp.get('base_url', ''),
                'api_key': cp.get('api_key', ''),
                'provider': 'custom',
                'model': cp.get('model', cp.get('default', '')),
                'note': cp.get('note', 'custom_providers'),
                '_source': 'config custom_providers',
            })

    # ── 4) Profiles ──
    profiles_dir = os.path.join(_hermes_dir(), 'profiles')
    if os.path.isdir(profiles_dir):
        for pname in sorted(os.listdir(profiles_dir)):
            pcfg_path = os.path.join(profiles_dir, pname, 'config.yaml')
            if not os.path.isfile(pcfg_path):
                continue
            try:
                with open(pcfg_path, 'r', encoding='utf-8') as f:
                    pcfg = yaml.safe_load(f.read()) or {}
            except Exception:
                continue

            pm = pcfg.get('model', {})
            pp = pm.get('provider', '')
            pu = pm.get('base_url', '')
            pmodel = pm.get('default', '')
            pkey = pm.get('api_key', '')

            if pp:
                key = pname
                if key not in discovered:
                    discovered[key] = _normalize({
                        'base_url': pu,
                        'api_key': pkey,
                        'provider': pp,
                        'model': pmodel,
                        'note': f'Profile: {pname}',
                        '_source': f'profiles/{pname}/config.yaml',
                    })

            # Profile custom_providers
            for cn, cp in pcfg.get('custom_providers', {}).items():
                if cn not in discovered:
                    discovered[cn] = _normalize({
                        'base_url': cp.get('base_url', ''),
                        'api_key': cp.get('api_key', ''),
                        'provider': 'custom',
                        'model': cp.get('model', cp.get('default', '')),
                        'note': f'Profile {pname}: custom_provider',
                        '_source': f'profiles/{pname}/custom_providers',
                    })

    return discovered


def switch_endpoint(name, model=None, params=None, profile=None):
    """Switch to a named endpoint, optionally with a specific model and params."""
    eps = load_endpoints()
    if name not in eps:
        raise ValueError(f"端点 '{name}' 不存在")

    ep = eps[name]
    cfg = load_config(profile)

    # Backup for undo
    backup = {'model': dict(cfg.get('model', {})), 'profile': profile}
    # Also backup agent.reasoning_effort if set
    if 'agent' in cfg and 'reasoning_effort' in cfg.get('agent', {}):
        backup['agent'] = {'reasoning_effort': cfg['agent']['reasoning_effort']}
    _save_backup(backup, profile)

    if 'model' not in cfg:
        cfg['model'] = {}

    cfg['model']['provider'] = ep['provider']
    cfg['model'].pop('api_mode', None)

    if ep.get('base_url'):
        cfg['model']['base_url'] = ep['base_url']
    else:
        cfg['model'].pop('base_url', None)

    if ep.get('api_key'):
        cfg['model']['api_key'] = ep['api_key']
    else:
        cfg['model'].pop('api_key', None)

    if ep.get('proxy'):
        cfg['model']['proxy'] = ep['proxy']
    else:
        cfg['model'].pop('proxy', None)

    target = model or ep.get('model', '')
    if target:
        cfg['model']['default'] = target

    # ── Write model capabilities to config ──
    # Use explicit params if provided, otherwise look up from _model_caps
    if params is None:
        params = {}
        model_caps = ep.get('_model_caps', {}) or {}
        if target and target in model_caps:
            params = model_caps[target]
    
    reasoning = params.get('reasoning_effort') or ''
    if reasoning:
        if 'agent' not in cfg:
            cfg['agent'] = {}
        cfg['agent']['reasoning_effort'] = reasoning

    save_config(cfg, profile)
    return ep


def _backup_path(profile=None):
    dir = _hermes_dir(profile)
    return os.path.join(dir, 'config.yaml.hermes-switch.bak')


def _save_backup(cfg_snapshot, profile=None):
    try:
        os.makedirs(os.path.dirname(_backup_path(profile)), exist_ok=True)
        with open(_backup_path(profile), 'w', encoding='utf-8') as f:
            yaml.dump(cfg_snapshot, f, allow_unicode=True, default_flow_style=False)
    except Exception:
        pass


def undo_switch(profile=None):
    """Undo last switch, restoring backed-up config."""
    bp = _backup_path(profile)
    if not os.path.exists(bp):
        raise ValueError('没有可撤销的切换（未找到备份）')
    with open(bp, 'r', encoding='utf-8') as f:
        backup = yaml.safe_load(f.read()) or {}
    if not backup.get('model', {}).get('provider'):
        raise ValueError('备份无效')
    cfg = load_config(profile)
    cfg['model'] = backup['model']
    # Restore agent.reasoning_effort if backed up
    if 'agent' in backup:
        if 'agent' not in cfg:
            cfg['agent'] = {}
        cfg['agent']['reasoning_effort'] = backup['agent']['reasoning_effort']
    save_config(cfg, profile)
    try:
        os.remove(bp)
    except Exception:
        pass
    return backup['model']


def has_undo(profile=None):
    return os.path.exists(_backup_path(profile))


def fetch_models(base_url, api_key, provider='custom', proxy=''):
    """
    Lightweight: GET /v1/models only, no chat test.
    Returns {'ok': bool, 'models': [...], 'error': str, 'latency_ms': int}
    """
    info = KNOWN_PROVIDERS.get(provider, {})
    resolved_key = api_key or ''
    resolved_url = base_url or ''

    if not resolved_url and info.get('base'):
        resolved_url = info['base']
    if not resolved_url:
        return {'ok': False, 'models': [], 'error': '无法确定 Base URL', 'latency_ms': 0}

    if not resolved_key and info.get('env'):
        envs = _read_env_vars()
        resolved_key = envs.get(info['env'], '')

    if not resolved_key:
        return {'ok': False, 'models': [], 'error': '需要 API Key', 'latency_ms': 0}

    url = resolved_url.rstrip('/')
    if not url.endswith('/v1'):
        url += '/v1'

    ctx = ssl.create_default_context()
    if url.startswith('http://') or '127.0.0.1' in url or 'localhost' in url:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    if proxy:
        ph = urllib.request.ProxyHandler({'http': proxy, 'https': proxy})
        opener = urllib.request.build_opener(ph)
    else:
        opener = urllib.request.build_opener()

    t0 = time.time()
    try:
        req = urllib.request.Request(f'{url}/models',
                                     headers={'Authorization': f'Bearer {resolved_key}'})
        with opener.open(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        models = [m['id'] for m in data.get('data', [])]
        t = int((time.time() - t0) * 1000)
        return {'ok': True, 'models': models, 'error': '', 'latency_ms': t}
    except urllib.error.HTTPError as e:
        codes = {401: 'Key 无效', 403: '无权访问', 404: '地址不对', 429: '限流',
                 500: '服务端错误', 502: '网关错误', 503: '服务不可用'}
        hint = codes.get(e.code, f'HTTP {e.code}')
        return {'ok': False, 'models': [], 'error': hint,
                'latency_ms': int((time.time() - t0) * 1000)}
    except urllib.error.URLError as e:
        reason = str(e.reason) if hasattr(e, 'reason') else str(e)
        if 'refused' in reason.lower():
            return {'ok': False, 'models': [], 'error': '连接被拒绝（服务未启动）',
                    'latency_ms': 0}
        if 'timeout' in reason.lower():
            return {'ok': False, 'models': [], 'error': '连接超时',
                    'latency_ms': int((time.time() - t0) * 1000)}
        return {'ok': False, 'models': [], 'error': f'连接失败: {reason[:80]}',
                'latency_ms': int((time.time() - t0) * 1000)}
    except Exception as e:
        return {'ok': False, 'models': [], 'error': str(e)[:100],
                'latency_ms': int((time.time() - t0) * 1000)}


def test_endpoint(base_url, api_key, provider='custom', proxy=''):
    """
    Full test: GET /v1/models + chat completion test.
    Returns {'ok': bool, 'models': [...], 'reply': str, 'error': str,
             'latency_ms': int, 'source': str}
    """
    info = KNOWN_PROVIDERS.get(provider, {})
    key_source = 'config'
    resolved_key = api_key or ''
    resolved_url = base_url or ''

    if not resolved_url and info.get('base'):
        resolved_url = info['base']
    if not resolved_url:
        return {'ok': False, 'error': '无法确定 Base URL', 'models': [], 'latency_ms': 0, 'source': ''}
    if not resolved_key and info.get('env'):
        envs = _read_env_vars()
        resolved_key = envs.get(info['env'], '')
        key_source = f'环境变量 {info["env"]}' if resolved_key else f'未找到 {info["env"]}'
    if not resolved_key:
        return {'ok': False, 'error': f'未找到 API Key（请设置 {info.get("env","API Key")}）',
                'models': [], 'latency_ms': 0, 'source': ''}

    url = resolved_url.rstrip('/')
    if not url.endswith('/v1'):
        url += '/v1'

    ctx = ssl.create_default_context()
    if url.startswith('http://') or '127.0.0.1' in url or 'localhost' in url:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    if proxy:
        ph = urllib.request.ProxyHandler({'http': proxy, 'https': proxy})
        opener = urllib.request.build_opener(ph)
    else:
        opener = urllib.request.build_opener()

    t0 = time.time()
    models = []

    # Step 1: GET /v1/models
    try:
        req = urllib.request.Request(f'{url}/models',
                                     headers={'Authorization': f'Bearer {resolved_key}'})
        with opener.open(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        models = [m['id'] for m in data.get('data', [])]
    except urllib.error.HTTPError as e:
        codes = {401: 'Key 无效或已过期', 403: '无权访问', 404: '端点地址不对',
                 429: '请求太频繁', 500: '服务端错误', 502: '网关错误', 503: '服务不可用'}
        hint = codes.get(e.code, f'HTTP {e.code}')
        return {'ok': False, 'error': hint, 'models': [], 'latency_ms': int((time.time()-t0)*1000),
                'source': key_source}
    except urllib.error.URLError as e:
        reason = str(e.reason) if hasattr(e, 'reason') else str(e)
        if 'refused' in reason.lower():
            return {'ok': False, 'error': '连接被拒绝（服务未启动或端口不对）', 'models': [],
                    'latency_ms': 0, 'source': ''}
        if 'timeout' in reason.lower():
            return {'ok': False, 'error': '连接超时（网络不通或地址错误）', 'models': [],
                    'latency_ms': int((time.time()-t0)*1000), 'source': ''}
        return {'ok': False, 'error': f'连接失败: {reason[:80]}', 'models': [],
                'latency_ms': int((time.time()-t0)*1000), 'source': ''}
    except Exception as e:
        return {'ok': False, 'error': f'请求异常: {str(e)[:100]}', 'models': [],
                'latency_ms': int((time.time()-t0)*1000), 'source': ''}

    # Step 2: test chat
    try:
        test_model = models[0] if models else 'default'
        payload = json.dumps({
            'model': test_model,
            'messages': [{'role': 'user', 'content': 'hi'}],
            'max_tokens': 5
        }).encode()
        headers = {
            'Authorization': f'Bearer {resolved_key}',
            'Content-Type': 'application/json'
        }
        req = urllib.request.Request(f'{url}/chat/completions', data=payload, headers=headers)
        with opener.open(req, timeout=12) as resp:
            chat_data = json.loads(resp.read().decode())
        reply = chat_data['choices'][0]['message'].get('content', '')
        t = int((time.time() - t0) * 1000)
        return {'ok': True, 'models': models, 'reply': reply[:200] if reply else '(空响应)',
                'latency_ms': t, 'source': key_source}
    except Exception as e:
        t = int((time.time() - t0) * 1000)
        return {'ok': True, 'models': models, 'reply': f'(chat 测试失败: {e})',
                'latency_ms': t, 'source': key_source}
