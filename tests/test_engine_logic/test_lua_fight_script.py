from collections.abc import Callable

import pytest

from src.core.engine.lua_fight.script import LuaAction, LuaFightScript, LuaFinished, LuaScriptError, ToLua


def _api(logs: list[str]) -> Callable[[ToLua], dict[str, Callable[..., object]]]:
    def factory(to_lua: ToLua) -> dict[str, Callable[..., object]]:
        def send_logs(message: object, color: object = None) -> None:
            logs.append(str(message))

        return {
            "GetPA": lambda: 6,
            "SendLogs": send_logs,
            "GetAllEnnemyFighter": lambda: to_lua({"12": {"id": "12", "cellId": 300}}),
        }

    return factory


def _load(source: str, logs: list[str] | None = None) -> LuaFightScript:
    return LuaFightScript(source, "@test.lua", _api([] if logs is None else logs))


class TestLuaFightScript:
    def test_blocking_call_inside_pcall_resumes_with_the_bot_answer(self) -> None:
        logs: list[str] = []
        script = _load(
            """
            function main()
                local ok, err = pcall(function()
                    local cast = fight:CastSpell("Nausée", 300)
                    fight:SendLogs("cast=" .. tostring(cast) .. " pa=" .. fight:GetPA())
                end)
                fight:PassTurn()
            end
            """,
            logs,
        )

        call, step = script.start_main()
        assert step == LuaAction("CastSpell", ("Nausée", 300))
        assert call.resume(True) == LuaAction("PassTurn", ())
        assert logs == ["cast=true pa=6"]
        assert isinstance(call.resume(), LuaFinished)

    def test_placement_returns_the_chosen_cell(self) -> None:
        script = _load("function fight:placement(possible, available) return available[2] end")

        assert script.has_placement()
        assert not script.has_main()
        _, step = script.start_placement([10, 20, 30], [20, 30])
        assert step == LuaFinished((30,))

    def test_python_tables_are_readable_from_lua(self) -> None:
        script = _load(
            """
            function main()
                local cells = {}
                for id, fighter in pairs(fight:GetAllEnnemyFighter()) do
                    cells[#cells + 1] = id .. ":" .. fight:GetProperty(fighter, "cellId")
                end
                return table.concat(cells, ",")
            end
            """
        )

        _, step = script.start_main()
        assert step == LuaFinished(("12:300",))

    def test_sandbox_hides_system_access(self) -> None:
        script = _load("function main() return os, io, load, require, dofile, python, debug, package end")

        _, step = script.start_main()
        assert step == LuaFinished((None,) * 8)

    def test_python_function_attributes_are_not_reachable(self) -> None:
        script = _load(
            """
            function main()
                local ok = pcall(function() return fight.GetPA.__globals__ end)
                return ok
            end
            """
        )

        _, step = script.start_main()
        assert step == LuaFinished((False,))

    def test_precompiled_bytecode_is_rejected(self) -> None:
        with pytest.raises(LuaScriptError):
            _load("\x1bLua")

    def test_unsupported_dofarm_function_names_the_missing_function(self) -> None:
        script = _load("function main() fight:Teleport(12) end")

        with pytest.raises(LuaScriptError, match="fight:Teleport is not supported"):
            script.start_main()

    def test_runtime_error_after_resume_is_reported(self) -> None:
        script = _load("function main() fight:Delay(10); error('boom') end")

        call, step = script.start_main()
        assert step == LuaAction("Delay", (10,))
        with pytest.raises(LuaScriptError, match="boom"):
            call.resume()

    def test_fight_actions_are_refused_while_loading(self) -> None:
        with pytest.raises(LuaScriptError, match="while loading"):
            _load("fight:PassTurn()")
