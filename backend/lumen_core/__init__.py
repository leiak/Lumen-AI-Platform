# langchain 1.0.1 兼容性 shim:把 langchain.verbose / langchain.debug /
# langchain.llm_cache 三个被移除的 module-level attribute 补回 None / False。
# langchain_core/globals.py 第 86 / 148 / 216 行仍然直接读老 attribute,没这些
# 就 AttributeError,导致 48 个 pytest fail(test_agent_team_sse /
# test_chat_service / test_skill_executors / test_memory_api 等)。
#
# - verbose / debug:历史语义是 bool log 开关,塞 False 是最小补丁。
# - llm_cache:历史是 LLM 响应缓存的可选 InMemoryCache / SQLiteCache 等实例,
#   塞 None 等价于 "不缓存",与历史 _NONE 行为一致 —— get_llm_cache() 内部
#   None 检查返 _NO_STACK_TRACE / InMemoryCache 兜底,本项目没启用任何 LLM
#   cache 配置,等价 no-op。
#
# 真正干净的做法是 upstream 升级到用 `langchain.globals.get_verbose()` /
# `set_debug()` / `set_llm_cache()`,但那要改大量调用点,留后续 langchain
# 升级 commit 一起清。本文件首次 import 就触发,任何 `from lumen_* import X`
# 之前 conftest.py 已经走过。
import langchain

if not hasattr(langchain, "verbose"):
    langchain.verbose = False
if not hasattr(langchain, "debug"):
    langchain.debug = False
if not hasattr(langchain, "llm_cache"):
    langchain.llm_cache = None
