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


def main():
    if len(sys.argv) < 2:
        _cmd_web()
        return

    cmd = sys.argv[1].lower()

    if cmd in ('-v', '--version', 'version'):
        print("Hermes Switch v4.0")
        return

    if cmd in ('web', 'ui', 'serve'):
        _cmd_web(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == 'list':
        _cmd_list()
    elif cmd == 'current':
        _cmd_current()
    elif cmd == 'use':
        _cmd_use(sys.argv)
    elif cmd == 'remove':
        _cmd_remove(sys.argv)
    elif cmd == 'rescan':
        _cmd_rescan()
    elif cmd == 'stop':
        _cmd_stop()
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)


def _cmd_web(port_arg=None):
    from .server import run_server
    port = None
    if port_arg:
        try:
            port = int(port_arg)
        except ValueError:
            print(f"无效端口: {port_arg}")
            sys.exit(1)
    run_server(port=port)


def _cmd_list():
    from .endpoints import (
        load_endpoints, get_current,
        get_provider_family, get_provider_display
    )
    eps = load_endpoints()
    cur = get_current()

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


def _cmd_current():
    from .endpoints import get_current, get_provider_display
    cur = get_current()
    display = get_provider_display(cur.get('provider', ''))
    print(f"Provider  : {cur['provider'] or '(未设置)'} ({display})")
    print(f"Base URL  : {cur['base_url'] or '(内置默认)'}")
    print(f"Model     : {cur['model'] or '(未设置)'}")
    print(f"API Key   : {cur['api_key'] or '(环境变量)'}")


def _cmd_use(argv):
    if len(argv) < 3:
        print("用法: hermes-switch use <端点名称> [模型]")
        print("示例: hermes-switch use deepseek")
        print("      hermes-switch use myproxy gpt-4")
        sys.exit(1)
    from .endpoints import switch_endpoint
    name = argv[2]
    model = argv[3] if len(argv) > 3 else None
    try:
        ep = switch_endpoint(name, model)
        target = model or ep.get('model', '')
        print(f"✓ 已切换到 '{name}' ({ep.get('provider', '')})")
        if target:
            print(f"  模型: {target}")
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
    eps = load_endpoints()
    if name not in eps:
        print(f"❌ 端点 '{name}' 不存在")
        sys.exit(1)
    del eps[name]
    save_endpoints(eps)
    print(f"✓ 已删除 '{name}'")


def _cmd_rescan():
    from .endpoints import auto_discover, load_endpoints, save_endpoints
    from .server import Handler
    discovered = auto_discover()
    existing = load_endpoints()
    fresh = dict(discovered)
    for name, ep in existing.items():
        if name not in fresh and not Handler._is_auto_discovered(ep):
            fresh[name] = ep
    save_endpoints(fresh)
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
