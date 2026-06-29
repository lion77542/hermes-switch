"""
模型能力系统 — 三层合并

能力来源（优先级从高到低）:
  3. override — 用户手动设的 per-model 覆盖
  2. inferred  — 按 provider 提取的默认值
  1. auto      — 从 /v1/models API 自动发现的

存储结构 (endpoints.json):
  endpoint._params: {}               — 端点级默认参数
  endpoint._model_caps[模型名]: {}   — per-model 的 override 层 (层3)
"""
import os, json, ssl, time, urllib.request
from urllib.parse import urlparse

# ── 层 2: 按 provider 推断的默认能力 ──

# 各 provider 支持的推理强度
REASONING_PROVIDERS = {
    'openai':      ['low', 'medium', 'high'],       # o-series reasoning_effort
    'anthropic':   ['low', 'medium', 'high', 'xhigh'],  # Claude thinking
    'deepseek':    ['low', 'medium', 'high'],        # DeepSeek R1
    'custom':      ['low', 'medium', 'high', 'xhigh'],  # 通用
}

# 各 provider 默认能力（层 2）
INFERRED_CAPABILITIES = {
    'anthropic': {
        'reasoning_effort': 'high',
        'supports_reasoning': True,
        'supports_streaming': True,
        'supports_vision': True,
        'supports_tool_calls': True,
        'max_completion_tokens': 8192,
    },
    'openai': {
        'supports_streaming': True,
        'supports_tool_calls': True,
        'supports_structured_outputs': True,
    },
    'deepseek': {
        'reasoning_effort': 'medium',
        'supports_reasoning': True,
        'supports_streaming': True,
        'supports_tool_calls': True,
    },
    'openrouter': {
        'supports_streaming': True,
        'supports_tool_calls': True,
    },
    'google': {
        'supports_vision': True,
        'supports_streaming': True,
    },
    'moonshot': {
        'supports_streaming': True,
    },
    'minimax': {
        'supports_streaming': True,
    },
    'dashscope': {
        'supports_streaming': True,
        'supports_tool_calls': True,
    },
    'custom': {
        'supports_streaming': True,
    },
}


# ── 核心函数 ──

def get_reasoning_options(provider):
    """获取某个 provider 的可用推理强度选项"""
    return REASONING_PROVIDERS.get(provider, REASONING_PROVIDERS.get('custom', []))


def merge_capabilities(endpoint, model_name=None, auto_caps=None):
    """
    三层合并：override (层3) > inferred (层2) > auto (层1)
    
    endpoint: 端点 dict (from endpoints.json)
    model_name: 模型名，可选
    auto_caps: 从 /v1/models API 自动发现的能力，可选 dict
    
    Returns: 合并后的能力 dict
    """
    caps = {}
    
    # 层 1: auto — 从 API 响应解析的能力
    if auto_caps:
        caps.update(auto_caps)
    
    # 层 2: inferred — 按 provider 的默认值
    provider = (endpoint or {}).get('provider', 'custom')
    inferred = INFERRED_CAPABILITIES.get(provider, INFERRED_CAPABILITIES.get('custom', {}))
    for k, v in inferred.items():
        if k not in caps or not caps[k]:
            caps[k] = v
    
    # 层 3: override — 端点级默认参数
    ep_params = (endpoint or {}).get('_params', {}) or {}
    for k in ['reasoning_effort', 'temperature', 'max_tokens', 'top_p']:
        if k in ep_params and ep_params[k]:
            caps[k] = ep_params[k]
    
    # 层 3: override — per-model 覆盖
    if model_name:
        model_caps = (endpoint or {}).get('_model_caps', {}) or {}
        if model_name in model_caps:
            mc = model_caps[model_name]
            for k, v in mc.items():
                if v or v is False:
                    caps[k] = v
    
    return caps


def get_model_caps(endpoint, model_name=None):
    """简写: 无 auto_caps 时只用层2+层3"""
    return merge_capabilities(endpoint, model_name, auto_caps=None)


def parse_model_response_meta(raw_data):
    """
    从 /v1/models API 响应解析模型能力（层 1: auto）
    兼容 OpenRouter 格式：reasoning, architecture, top_provider, default_parameters
    Returns: {model_id: caps_dict}
    """
    caps = {}
    models = raw_data.get('data', []) if isinstance(raw_data, dict) else []
    for m in models:
        mid = m.get('id', '')
        if not mid:
            continue
        mc = {}
        
        # Architecture/modality info
        arch = m.get('architecture', {}) or {}
        modalities = (arch.get('input_modalities') or []) + (arch.get('output_modalities') or [])
        if 'image' in str(modalities):
            mc['supports_vision'] = True
        
        # Context length
        ctx = m.get('context_length') or (m.get('top_provider') or {}).get('context_length')
        if ctx:
            mc['context_length'] = ctx
        
        # Max completion tokens
        max_comp = (m.get('top_provider') or {}).get('max_completion_tokens')
        if max_comp:
            mc['max_completion_tokens'] = max_comp
        
        # Reasoning capability (OpenRouter's reasoning field)
        reasoning = m.get('reasoning') or {}
        if reasoning:
            mc['supports_reasoning'] = True
            if reasoning.get('effort') or reasoning.get('allowed'):
                mc['reasoning_effort'] = reasoning.get('effort', reasoning.get('allowed', ''))
        
        # Default parameters from OpenRouter
        defaults = m.get('default_parameters') or {}
        if defaults.get('temperature'):
            mc['temperature'] = defaults['temperature']
        if defaults.get('max_tokens'):
            mc['max_tokens'] = defaults['max_tokens']
        if defaults.get('top_p'):
            mc['top_p'] = defaults['top_p']
        
        # Supported parameters
        sp = m.get('supported_parameters') or []
        if sp:
            mc['supported_params'] = sp
        
        if mc:
            caps[mid] = mc
    
    return caps


def enrich_fetch_models_result(base_url, api_key, provider='custom', proxy=''):
    """
    获取模型列表 + 能力信息一次搞定
    返回: {'ok': bool, 'models': [...], 'model_caps': {...}, 'error': str, 'latency_ms': int}
    """
    from .endpoints import KNOWN_PROVIDERS, _read_env_vars
    info = KNOWN_PROVIDERS.get(provider, {})
    resolved_key = api_key or ''
    resolved_url = base_url or ''

    if not resolved_url and info.get('base'):
        resolved_url = info['base']
    if not resolved_url:
        return {'ok': False, 'models': [], 'model_caps': {}, 'error': '无法确定 Base URL', 'latency_ms': 0}

    if not resolved_key and info.get('env'):
        envs = _read_env_vars()
        resolved_key = envs.get(info['env'], '')

    if not resolved_key:
        return {'ok': False, 'models': [], 'model_caps': {}, 'error': '需要 API Key', 'latency_ms': 0}

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
        with opener.open(req, timeout=8, context=ctx) as resp:
            raw = json.loads(resp.read().decode())
        models = [m['id'] for m in raw.get('data', [])]
        t = int((time.time() - t0) * 1000)
        result = {'ok': True, 'models': models, 'error': '', 'latency_ms': t}
        caps = parse_model_response_meta(raw)
        if caps:
            result['model_caps'] = caps
        return result
    except urllib.error.HTTPError as e:
        codes = {401: 'Key 无效', 403: '无权访问', 404: '地址不对', 429: '限流',
                 500: '服务端错误', 502: '网关错误', 503: '服务不可用'}
        hint = codes.get(e.code, f'HTTP {e.code}')
        return {'ok': False, 'models': [], 'error': hint,
                'latency_ms': int((time.time() - t0) * 1000)}
    except urllib.error.URLError as e:
        reason = str(e.reason) if hasattr(e, 'reason') else str(e)
        if 'timeout' in reason.lower():
            return {'ok': False, 'models': [], 'error': '连接超时',
                    'latency_ms': int((time.time() - t0) * 1000)}
        return {'ok': False, 'models': [], 'error': f'连接失败: {reason[:80]}',
                'latency_ms': int((time.time() - t0) * 1000)}
    except Exception as e:
        return {'ok': False, 'models': [], 'error': str(e)[:100],
                'latency_ms': int((time.time() - t0) * 1000)}
