using System.Reflection;
using System.Text.Json;

namespace STS2Headless;

/// <summary>
/// Narrow pre-initialization patches for platform queries that otherwise call
/// uninstalled Godot native callbacks. Patches must be installed before the
/// affected game type's static constructor runs.
/// </summary>
internal static class StandaloneRuntimePatches
{
    public static void Install(Assembly gameAssembly)
    {
        var harmonyAssembly = Assembly.Load(new AssemblyName("0Harmony"));
        var harmonyType = harmonyAssembly.GetType(
            "HarmonyLib.Harmony", throwOnError: true)!;
        var harmonyMethodType = harmonyAssembly.GetType(
            "HarmonyLib.HarmonyMethod", throwOnError: true)!;
        var harmony = Activator.CreateInstance(
                harmonyType, ["com.sts2sanset.standalone"])
            ?? throw new InvalidOperationException("Could not construct Harmony");
        var patch = harmonyType.GetMethod(
                "Patch",
                [
                    typeof(MethodBase),
                    harmonyMethodType,
                    harmonyMethodType,
                    harmonyMethodType,
                    harmonyMethodType
                ])
            ?? throw new MissingMethodException(harmonyType.FullName, "Patch");

        var loggerType = gameAssembly.GetType(
            "MegaCrit.Sts2.Core.Logging.Logger", throwOnError: true)!;
        var editorProbe = loggerType.GetMethod(
                "GetIsRunningFromGodotEditor",
                BindingFlags.NonPublic | BindingFlags.Static)
            ?? throw new MissingMethodException(
                loggerType.FullName, "GetIsRunningFromGodotEditor");
        PatchPrefix(
            harmony,
            patch,
            harmonyMethodType,
            editorProbe,
            nameof(UseConsoleLoggerWithoutGodot));
        var playCardType = gameAssembly.GetType(
            "MegaCrit.Sts2.Core.GameActions.PlayCardAction",
            throwOnError: true)!;
        var playCardToString = playCardType.GetMethod(
                nameof(ToString),
                BindingFlags.Public | BindingFlags.Instance |
                BindingFlags.DeclaredOnly)
            ?? throw new MissingMethodException(
                playCardType.FullName, nameof(ToString));
        PatchPrefix(
            harmony,
            patch,
            harmonyMethodType,
            playCardToString,
            nameof(UseStandalonePlayCardDescription));
        var creatureType = gameAssembly.GetType(
            "MegaCrit.Sts2.Core.Entities.Creatures.Creature",
            throwOnError: true)!;
        var creatureLogName = creatureType.GetMethod(
                "get_LogName",
                BindingFlags.Public | BindingFlags.Instance)
            ?? throw new MissingMethodException(
                creatureType.FullName, "get_LogName");
        PatchPrefix(
            harmony,
            patch,
            harmonyMethodType,
            creatureLogName,
            nameof(UseStandaloneCreatureLogName));
        var godotAssembly = Assembly.Load(new AssemblyName("GodotSharp"));
        var timeType = godotAssembly.GetType("Godot.Time", throwOnError: true)!;
        var ticksMsec = timeType.GetMethod(
                "GetTicksMsec",
                BindingFlags.Public | BindingFlags.Static)
            ?? throw new MissingMethodException(
                timeType.FullName, "GetTicksMsec");
        PatchPrefix(
            harmony,
            patch,
            harmonyMethodType,
            ticksMsec,
            nameof(UseManagedMonotonicMilliseconds));
        var logType = gameAssembly.GetType(
            "MegaCrit.Sts2.Core.Logging.Log", throwOnError: true)!;
        foreach (var infoMethod in logType.GetMethods(
                     BindingFlags.Public | BindingFlags.Static |
                     BindingFlags.DeclaredOnly)
                     .Where(method => method.Name == "Info"))
        {
            PatchPrefix(
                harmony,
                patch,
                harmonyMethodType,
                infoMethod,
                nameof(SuppressStandaloneGameLog));
        }

        // Native callback failures terminate the process rather than producing
        // managed stack traces. These prefixes provide the equivalent of a
        // boundary trace while leaving the original game methods untouched.
        if (Environment.GetEnvironmentVariable(
                "STS2_STANDALONE_TRACE") != "1")
            return;
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.Multiplayer.CombatStateSynchronizer",
            "StartSync",
            "WaitForSync");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.Runs.RunState",
            "AppendToMapPointHistory");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.Runs.RunManager",
            "get_Instance",
            "ClearScreens",
            "CreateRoom",
            "EnterRoom",
            "EnterRoomInternal");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.Rooms.CombatRoom",
            "StartCombat");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.Combat.CombatManager",
            "SetUpCombat",
            "AfterCombatRoomLoaded",
            "StartCombatInternal",
            "AfterCreatureAdded",
            "StartTurn",
            "SetupPlayerTurn");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.GameActions.Multiplayer.ActionQueueSynchronizer",
            "RequestEnqueue",
            "EnqueueAction");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.GameActions.Multiplayer.ActionQueueSet",
            "EnqueueWithoutSynchronizing");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.GameActions.ActionExecutor",
            "FinishedExecutingActions",
            "ExecuteActions");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.GameActions.GameAction",
            "Execute");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.GameActions.PlayCardAction",
            "ExecuteAction");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.Models.CardModel",
            "CanPlay",
            "IsValidTarget",
            "SpendResources",
            "OnPlayWrapper");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.Combat.CombatState",
            "GetCreatureAsync");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.Commands.Cmd",
            "CustomScaledWait",
            "Wait");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.Commands.SfxCmd",
            "Play");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.Commands.CardPileCmd",
            "Draw",
            "Add",
            "AddDuringManualCardPlay",
            "ShuffleIfNecessary",
            "CheckIfDrawIsPossibleAndShowThoughtBubbleIfNot");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.Multiplayer.Game.ChecksumTracker",
            "GenerateChecksum");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.Saves.SaveManager",
            "SeenFtue");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.Nodes.NRun",
            "get_Instance");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.Nodes.Audio.NRunMusicController",
            "get_Instance");
        TraceMethods(
            gameAssembly,
            harmony,
            patch,
            harmonyMethodType,
            "MegaCrit.Sts2.Core.Nodes.Rooms.NCombatRoom",
            "get_Instance");
    }

    public static bool UseConsoleLoggerWithoutGodot(ref bool __result)
    {
        __result = false;
        return false;
    }

    public static bool UseStandalonePlayCardDescription(ref string __result)
    {
        __result = "PlayCardAction";
        return false;
    }

    public static bool UseStandaloneCreatureLogName(ref string __result)
    {
        __result = "Creature";
        return false;
    }

    public static bool UseManagedMonotonicMilliseconds(ref ulong __result)
    {
        __result = unchecked((ulong)Environment.TickCount64);
        return false;
    }

    public static bool SuppressStandaloneGameLog() => false;

    public static void TraceGameBoundary(MethodBase __originalMethod)
    {
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "game_boundary",
            method = $"{__originalMethod.DeclaringType?.FullName}.{__originalMethod.Name}"
        }));
    }

    private static void TraceMethods(
        Assembly gameAssembly,
        object harmony,
        MethodInfo patch,
        Type harmonyMethodType,
        string typeName,
        params string[] methodNames)
    {
        var type = gameAssembly.GetType(typeName, throwOnError: true)!;
        foreach (var methodName in methodNames)
        {
            var methods = type.GetMethods(
                    BindingFlags.Public | BindingFlags.NonPublic |
                    BindingFlags.Instance | BindingFlags.Static |
                    BindingFlags.DeclaredOnly)
                .Where(candidate => candidate.Name == methodName)
                .ToArray();
            if (methods.Length == 0)
                throw new MissingMethodException(type.FullName, methodName);
            foreach (var method in methods)
                PatchPrefix(
                    harmony,
                    patch,
                    harmonyMethodType,
                    method,
                    nameof(TraceGameBoundary));
        }
    }

    private static void PatchPrefix(
        object harmony,
        MethodInfo patch,
        Type harmonyMethodType,
        MethodBase original,
        string prefixName)
    {
        var prefix = typeof(StandaloneRuntimePatches).GetMethod(
                prefixName,
                BindingFlags.Public | BindingFlags.Static)
            ?? throw new MissingMethodException(
                typeof(StandaloneRuntimePatches).FullName, prefixName);
        var harmonyPrefix = Activator.CreateInstance(
                harmonyMethodType, [prefix])
            ?? throw new InvalidOperationException(
                $"Could not construct HarmonyMethod for {prefixName}");
        patch.Invoke(
            harmony,
            [original, harmonyPrefix, null, null, null]);
    }
}
