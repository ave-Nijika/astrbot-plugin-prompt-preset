"""pytest 引导。

1. 把插件根目录加入 sys.path，并以包别名 ``astrbot_plugin_prompt_preset``
   暴露（仓库目录名与插件包名不一致，且 VM 上以 data.plugins.<包名> 加载）。
2. 若当前环境没有安装 astrbot（如 CI/开发沙箱），注入最小化的 astrbot 桩，
   使 main.py 可以导入；在 AstrBot venv 内则使用真实 astrbot。
"""

import sys
import types
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_PKG_NAME = "astrbot_plugin_prompt_preset"

if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

if PLUGIN_PKG_NAME not in sys.modules:
    try:
        __import__(PLUGIN_PKG_NAME)
    except ImportError:
        _pkg = types.ModuleType(PLUGIN_PKG_NAME)
        _pkg.__path__ = [str(PLUGIN_ROOT)]
        sys.modules[PLUGIN_PKG_NAME] = _pkg


def _install_astrbot_stubs() -> None:
    import logging

    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api_star = types.ModuleType("astrbot.api.star")
    api_event = types.ModuleType("astrbot.api.event")
    api_filter = types.ModuleType("astrbot.api.event.filter")
    api_provider = types.ModuleType("astrbot.api.provider")
    api_web = types.ModuleType("astrbot.api.web")

    api.logger = logging.getLogger("astrbot")

    class Star:
        def __init__(self, context, config=None, *args, **kwargs):
            self.context = context
            self.config = config

    class Context:
        pass

    def register(name=None, author=None, desc=None, version=None, repo=None):
        def deco(cls):
            return cls

        return deco

    api_star.Star = Star
    api_star.Context = Context
    api_star.register = register

    class _Filter:
        def _identity(self, *args, **kwargs):
            def deco(func):
                return func

            return deco

        command = _identity
        command_group = _identity
        on_llm_request = _identity
        on_astrbot_loaded = _identity
        event_message_type = _identity
        permission_type = _identity
        platform_adapter_type = _identity
        regex = _identity

    api_filter.filter = _Filter()

    class AstrMessageEvent:
        message_str = ""
        unified_msg_origin = ""

        def plain_result(self, text):
            return text

    class ProviderRequest:
        def __init__(self, system_prompt="", contexts=None, prompt=""):
            self.system_prompt = system_prompt
            self.contexts = list(contexts) if contexts is not None else []
            self.prompt = prompt

    # astrbot.api.web：插件 Web API 的 request 上下文与响应构造器
    class ApiRequest:
        method = "GET"
        headers = {}
        query = {}
        path_params = {}

        async def json(self, default=None):
            return default

    def _json_response(data, status_code=200):
        return {"status": "ok", "data": data, "status_code": status_code}

    def _error_response(message, status_code=400):
        return {"status": "error", "message": message, "status_code": status_code}

    api_web.request = ApiRequest()
    api_web.json_response = _json_response
    api_web.error_response = _error_response

    api_event.AstrMessageEvent = AstrMessageEvent
    api_event.filter = api_filter.filter
    api_provider.ProviderRequest = ProviderRequest

    astrbot.api = api
    for name, module in {
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.api.star": api_star,
        "astrbot.api.event": api_event,
        "astrbot.api.event.filter": api_filter,
        "astrbot.api.provider": api_provider,
        "astrbot.api.web": api_web,
    }.items():
        sys.modules.setdefault(name, module)


try:
    import astrbot  # noqa: F401
except ImportError:
    _install_astrbot_stubs()
