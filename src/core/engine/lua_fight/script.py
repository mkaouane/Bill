from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from lupa.lua54 import LuaError, LuaRuntime

# Actions that need the bot to talk to the server: the script coroutine yields and resumes on completion.
BLOCKING_FUNCTIONS = (
    "CastSpell",
    "MoveToCell",
    "MoveToClosestEnemy",
    "Delay",
    "PassTurn",
    "RequestChallengeChoice",
    "SelectChallenge",
)

# Script-visible globals besides `fight`; everything else (os, io, load, require, python...) is removed.
_SAFE_GLOBALS = (
    "assert",
    "error",
    "ipairs",
    "next",
    "pairs",
    "pcall",
    "print",
    "rawequal",
    "rawget",
    "rawlen",
    "rawset",
    "select",
    "setmetatable",
    "getmetatable",
    "tonumber",
    "tostring",
    "type",
    "xpcall",
    "_VERSION",
    "coroutine",
    "math",
    "string",
    "table",
    "utf8",
)

_BOOTSTRAP = """
local api, sync_names, blocking_names = ...

local fight = {}
for _, name in ipairs(sync_names) do
    local fn = api[name]
    fight[name] = function(self, ...) return fn(...) end
end
for _, name in ipairs(blocking_names) do
    fight[name] = function(self, ...) return coroutine.yield(name, ...) end
end
function fight:GetProperty(obj, key)
    if type(obj) == "table" then return obj[key] end
    return nil
end
fight.GetChallengeProperty = fight.GetProperty
setmetatable(fight, {
    __index = function(_, name)
        error("fight:" .. tostring(name) .. " is not supported by Bill", 2)
    end,
})

local registry, next_id = {}, 0
local function step(id, co, ...)
    local result = table.pack(coroutine.resume(co, ...))
    local done = coroutine.status(co) == "dead"
    if done then registry[id] = nil end
    return done, result
end
local runner = {}
function runner.start(fn, ...)
    next_id = next_id + 1
    local co = coroutine.create(fn)
    registry[next_id] = co
    return next_id, step(next_id, co, ...)
end
function runner.resume(id, ...)
    return step(id, registry[id], ...)
end
function runner.cancel(id)
    registry[id] = nil
end
return fight, runner
"""


_MAX_MEMORY_BYTES = 64 * 1024 * 1024


class LuaScriptError(Exception):
    pass


@dataclass(frozen=True)
class LuaAction:
    name: str
    args: tuple[Any, ...]


@dataclass(frozen=True)
class LuaFinished:
    values: tuple[Any, ...]


LuaStep = LuaAction | LuaFinished
ToLua = Callable[[object], object]
ApiFactory = Callable[[ToLua], Mapping[str, Callable[..., object]]]


def _deny_python_attributes(obj: object, attr_name: str, is_setting: bool) -> str:
    raise AttributeError(f"Python attribute access is disabled in fight scripts: {attr_name}")


class LuaCall:
    def __init__(self, script: "LuaFightScript", call_id: int) -> None:
        self._script = script
        self._call_id = call_id
        self.is_done = False

    def resume(self, *values: object) -> LuaStep:
        if self.is_done:
            raise LuaScriptError("Lua call already finished")
        try:
            done, result = self._script.runner.resume(self._call_id, *values)
        except LuaError as error:
            self.is_done = True
            raise LuaScriptError(str(error)) from error
        return self._handle(done, result)

    def cancel(self) -> None:
        if not self.is_done:
            self.is_done = True
            self._script.runner.cancel(self._call_id)

    def _handle(self, done: bool, result: Any) -> LuaStep:
        values = tuple(result[index] for index in range(2, result.n + 1))
        if done:
            self.is_done = True
        if not result[1]:
            raise LuaScriptError(str(values[0]) if values else "Unknown Lua error")
        if done:
            return LuaFinished(values)
        if not values or not isinstance(values[0], str):
            raise LuaScriptError("Script yielded outside of a fight action")
        return LuaAction(values[0], values[1:])


class LuaFightScript:
    """A DoFarm-style fight script running in an isolated Lua 5.4 state."""

    def __init__(self, source: str, chunk_name: str, api_factory: ApiFactory) -> None:
        self._lua = LuaRuntime(
            max_memory=_MAX_MEMORY_BYTES,
            unpack_returned_tuples=True,
            register_eval=False,
            register_builtins=False,
            attribute_filter=_deny_python_attributes,
        )
        # lupa objects are dynamically typed proxies over Lua values.
        lua_globals: Any = self._lua.globals()
        for name in list(lua_globals):
            if name not in _SAFE_GLOBALS:
                lua_globals[name] = None
        api = api_factory(self.to_lua)
        bootstrap: Any = self._lua.execute("return function(...) " + _BOOTSTRAP + " end")
        self.fight: Any
        self.runner: Any
        self.fight, self.runner = bootstrap(
            self.to_lua(dict(api)),
            self.to_lua(list(api)),
            self.to_lua(list(BLOCKING_FUNCTIONS)),
        )
        lua_globals.fight = self.fight
        try:
            # Text mode only: precompiled bytecode can escape the sandbox.
            chunk = self._lua.compile(source, chunk_name, mode="t")
        except LuaError as error:
            raise LuaScriptError(str(error)) from error
        call = self._start(chunk)
        if not isinstance(call[1], LuaFinished):
            call[0].cancel()
            raise LuaScriptError("The script must not call fight actions while loading")

    @classmethod
    def load(cls, path: Path, api_factory: ApiFactory) -> "LuaFightScript":
        try:
            source = path.read_text(encoding="utf-8-sig")
        except OSError as error:
            raise LuaScriptError(f"Cannot read {path}: {error}") from error
        return cls(source, f"@{path.name}", api_factory)

    def to_lua(self, value: object) -> object:
        if isinstance(value, Mapping | list | tuple):
            return self._lua.table_from(cast(Iterable[object], value), recursive=True)
        return value

    def has_main(self) -> bool:
        return bool(self._lua.eval("type(main) == 'function'"))

    def has_placement(self) -> bool:
        return bool(self._lua.eval("type(rawget(fight, 'placement')) == 'function'"))

    def start_main(self) -> tuple[LuaCall, LuaStep]:
        return self._start(self._lua.eval("main"))

    def start_placement(self, possible_cells: list[int], available_cells: list[int]) -> tuple[LuaCall, LuaStep]:
        placement = self._lua.eval("rawget(fight, 'placement')")
        return self._start(placement, self.fight, self.to_lua(possible_cells), self.to_lua(available_cells))

    def _start(self, function: object, *args: object) -> tuple[LuaCall, LuaStep]:
        try:
            call_id, done, result = self.runner.start(function, *args)
        except LuaError as error:
            raise LuaScriptError(str(error)) from error
        call = LuaCall(self, int(call_id))
        return call, call._handle(done, result)
