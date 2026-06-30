"""
Hermes Switch — 多端点快速切换器

用法:
  hermes-switch                启动 Web UI
  hermes-switch web [端口]     启动 Web UI (默认自动找可用端口)
  hermes-switch stop           停止正在运行的 Web UI
  hermes-switch list           列出所有端点（分组显示）
  hermes-switch use <名称>     切换到指定端点
  hermes-switch current        显示当前端点
  hermes-switch remove <名称>  删除端点
  hermes-switch rescan         重新扫描并合并端点
"""
import os, sys
# 避免字节码缓存覆盖源码更改
sys.dont_write_bytecode = True


def _parse_profile():
    """Parse -p/--profile argument from sys.argv."""
    for i, arg in enumerate(sys.argv):
        if arg in ('-p', '--profile') and i + 1 < len(sys.argv):
            # Remove from args so downstream parsers don't see it
            val = sys.argv.pop(i + 1)
            sys.argv.pop(i)
            return val
    return ''


def main():
    profile = _parse_profile()
    if not profile:
        from .endpoints import _active_profile
        profile = _active_profile()

    if len(sys.argv) < 2:
        _cmd_web(profile=profile)
        return

    cmd = sys.argv[1].lower()

    if cmd in ('-v', '--version', 'version'):
        print("Hermes Switch v4.0")
        return

    if cmd in ('web', 'ui', 'serve'):
        _cmd_web(sys.argv[2] if len(sys.argv) > 2 else None, profile=profile)
    elif cmd == 'list':
        _cmd_list(profile=profile)
    elif cmd == 'current':
        _cmd_current(profile=profile)
    elif cmd == 'use':
        _cmd_use(sys.argv, profile=profile)
    elif cmd == 'undo':
        _cmd_undo(profile=profile)
    elif cmd == 'remove':
        _cmd_remove(sys.argv, profile=profile)
    elif cmd == 'rescan':
        _cmd_rescan(profile=profile)
    elif cmd == 'stop':
        _cmd_stop()
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)


def _cmd_web(port_arg=None, profile=None):
    from .server import run_server
    port = None
    if port_arg:
        try:
            port = int(port_arg)
        except ValueError:
            print(f"无效端口: {port_arg}")
            sys.exit(1)
    run_server(port=port, profile=profile)


def _cmd_list(profile=None):
    from .endpoints import (
        load_endpoints, get_current,
        get_provider_family, get_provider_display
    )
    eps = load_endpoints(profile)
    cur = get_current(profile)

    if not eps:
        print("没有注册的端点。")
        print("运行 hermes-switch 打开 Web UI 添加，或 hermes-switch rescan 扫描。")
        return

    # Group
    builtin = {k: v for k, v in eps.items()
               if get_provider_family(v.get('provider', 'custom')) == 'builtin'}
    custom = {k: v for k, v in eps.items()
              if k not in builtin}

    for group_name, group in [('内置 Provider', builtin), ('自定义端点', custom)]:
        if not group:
            continue
        print(f"\n  {group_name}:")
        for name in sorted(group.keys()):
            ep = group[name]
            active = (
                ep.get('provider') == cur['provider'] and
                ep.get('base_url', '') == cur.get('base_url', '')
            )
            marker = ' ◀ 当前' if active else ''
            prov_display = get_provider_display(ep.get('provider', 'custom'))
            model = ep.get('model', '') or '(未设)'
            url = ep.get('base_url', '') or '(内置默认)'
            mcount = len(ep.get('_models', []))
            models_str = f' [{mcount} models]' if mcount else ''
            note = f' — {ep["note"]}' if ep.get('note') else ''
            print(f"    {name:<16} {prov_display:<12} {model:<20}{marker}")
            print(f"    {'':16} {url}")
            if mcount:
                preview = ', '.join(ep['_models'][:4])
                if mcount > 4:
                    preview += f' …+{mcount-4}'
                print(f"    {'':16} 📦 {preview}")
            if note:
                print(f"    {'':16}{note}")
            print()

    print(f"  共 {len(eps)} 个端点")


def _cmd_current(profile=None):
    from .endpoints import get_current, get_provider_display
    cur = get_current(profile)
    profile_label = f' (profile: {profile})' if profile else ''
    print(f"Provider  : {cur['provider'] or '(未设置)'} ({get_provider_display(cur.get('provider', ''))}){profile_label}")
    print(f"Base URL  : {cur['base_url'] or '(内置默认)'}")
    print(f"Model     : {cur['model'] or '(未设置)'}")
    print(f"API Key   : {cur['api_key'] or '(环境变量)'}")
    if profile:
        print(f"Profile   : {profile}")


def _cmd_use(argv, profile=None):
    if len(argv) < 3:
        print("用法: hermes-switch use <端点名称> [模型]")
        print("示例: hermes-switch use deepseek")
        print("      hermes-switch use myproxy gpt-4")
        print("      hermes-switch use myproxy -p st67")
        sys.exit(1)
    from .endpoints import switch_endpoint, get_provider_display
    name = argv[2]
    model = None
    # Check for -p/--profile after name
    remaining = argv[3:] if len(argv) > 3 else []
    filtered = []
    for i, arg in enumerate(remaining):
        if arg in ('-p', '--profile') and i + 1 < len(remaining):
            profile = remaining[i + 1]
            break
        elif not arg.startswith('-'):
            filtered.append(arg)
    if filtered:
        model = filtered[0]
    try:
        ep = switch_endpoint(name, model, profile=profile)
        target = model or ep.get('model', '')
        prov_display = get_provider_display(ep.get('provider', ''))
        print(f"✓ 已切换到 '{name}' ({prov_display})")
        if target:
            print(f"  模型: {target}")
        if profile:
            print(f"  Profile: {profile}")
        print("  /reset 生效 (或重启 hermes)")
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)


def _cmd_undo(profile=None):
    from .endpoints import undo_switch
    try:
        restored = undo_switch(profile)
        prov = restored.get('provider', '')
        model = restored.get('default', '')
        print(f"✓ 已撤销切换，恢复到上一端点")
        print(f"  Provider: {prov}")
        if model:
            print(f"  Model: {model}")
        if profile:
            print(f"  Profile: {profile}")
        print("  /reset 生效 (或重启 hermes)")
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)


def _cmd_remove(argv):
    if len(argv) < 3:
        print("用法: hermes-switch remove <端点名称>")
        sys.exit(1)
    from .endpoints import load_endpoints, save_endpoints
    name = argv[2]
    eps = load_endpoints(profile)
    if name not in eps:
        print(f"❌ 端点 '{name}' 不存在")
        sys.exit(1)
    del eps[name]
    save_endpoints(eps, profile)
    print(f"✓ 已删除 '{name}'")


def _cmd_rescan(profile=None):
    from .endpoints import auto_discover, load_endpoints, save_endpoints
    from .server import Handler
    discovered = auto_discover(profile)
    existing = load_endpoints(profile)
    fresh = dict(discovered)
    for name, ep in existing.items():
        if name not in fresh and not Handler._is_auto_discovered(ep):
            fresh[name] = ep
    save_endpoints(fresh, profile)
    print(f"✓ 扫描完成：发现 {len(discovered)} 个，合并后共 {len(fresh)} 个端点")
    removed = len(existing) - (len(fresh) - len(discovered)) - len(discovered)
    if removed > 0:
        print(f"  已清理 {removed} 个已失效的自动发现端点")
    for name in sorted(discovered):
        ep = discovered[name]
        print(f"  + {name:<16} ({ep.get('provider','?')}) {ep.get('base_url','')}")
    if not discovered:
        print("  （没有发现新端点）")


def _cmd_stop():
    """Stop a running Hermes Switch server instance."""
    from .endpoints import PID_FILE, kill_previous_instance
    if not os.path.exists(PID_FILE):
        print("❌ 没有正在运行的 Hermes Switch 实例")
        return
    try:
        with open(PID_FILE, 'r') as f:
            old_pid = int(f.read().strip())
        print(f"  PID: {old_pid}")
        killed = kill_previous_instance()
        if killed:
            print("✓ 已停止")
        else:
            print("👋 已清理 PID 文件（进程可能已自行退出）")
    except Exception as e:
        print(f"❌ 停止失败: {e}")


if __name__ == '__main__':
    main()
