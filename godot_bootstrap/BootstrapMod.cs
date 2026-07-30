using HarmonyLib;
using Godot;
using System.Text.Json;
using System.Text.Json.Serialization;
using MegaCrit.Sts2.Core.Assets;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Acts;
using MegaCrit.Sts2.Core.Models.Characters;
using MegaCrit.Sts2.Core.Models.Encounters;
using MegaCrit.Sts2.Core.Modding;
using MegaCrit.Sts2.Core.Multiplayer.Replay;
using MegaCrit.Sts2.Core.Multiplayer.Serialization;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Debug;
using MegaCrit.Sts2.Core.Nodes.Debug.Multiplayer;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves;
using MegaCrit.Sts2.Core.Settings;
using MegaCrit.Sts2.Core.Unlocks;

namespace STS2Bootstrap;

[ModInitializer(nameof(Initialize))]
public static class BootstrapMod
{
    private static int _resetting;
    private static int _nextResetId;
    private static int _completedResetId;
    private static string? _resetError;

    public static void Initialize()
    {
        var harmony = new Harmony("com.sts2sanset.bootstrap");
        harmony.PatchAll(typeof(BootstrapMod).Assembly);

        var executeAction = AccessTools.Method(
            AccessTools.TypeByName("STS2_MCP.McpMod"),
            "ExecuteAction");
        if (executeAction != null)
        {
            harmony.Patch(
                executeAction,
                prefix: new HarmonyMethod(
                    AccessTools.Method(typeof(BootstrapMod), nameof(McpExecuteActionPrefix))));
        }
    }

    public static bool McpExecuteActionPrefix(
        string action,
        Dictionary<string, JsonElement> data,
        ref Dictionary<string, object?> __result)
    {
        if (action == "write_replay")
        {
            bool wasRecording = RunManager.Instance.IsInProgress
                && RunManager.Instance.CombatReplayWriter.IsRecordingReplay;
            if (wasRecording)
                RunManager.Instance.WriteReplay(stopRecording: true);
            __result = new()
            {
                ["status"] = "ok",
                ["wrote_replay"] = wasRecording
            };
            return false;
        }

        if (action == "reset_status")
        {
            __result = new()
            {
                ["status"] = Volatile.Read(ref _resetting) == 0 ? "idle" : "resetting",
                ["completed_reset_id"] = Volatile.Read(ref _completedResetId),
                ["error"] = _resetError
            };
            return false;
        }

        if (action != "reset")
            return true;

        if (Interlocked.CompareExchange(ref _resetting, 1, 0) != 0)
        {
            __result = new()
            {
                ["status"] = "error",
                ["message"] = "Reset already in progress"
            };
            return false;
        }

        string seed = data.TryGetValue("seed", out var seedElement)
            ? seedElement.GetString() ?? "HEADLESSBENCH"
            : "HEADLESSBENCH";
        int resetId = Interlocked.Increment(ref _nextResetId);
        _resetError = null;
        TaskHelper.RunSafely(ResetAsync(seed, resetId));
        __result = new()
        {
            ["status"] = "accepted",
            ["message"] = "Warm reset started",
            ["reset_id"] = resetId,
            ["seed"] = seed
        };
        return false;
    }

    private static async Task ResetAsync(string seed, int resetId)
    {
        try
        {
            RunManager.Instance.CleanUp();

            var settings = new HeadlessBootstrapSettings(seed);
            var acts = ActModel.GetDefaultList().Select(act => act.ToMutable()).ToList();
            acts[0] = settings.Act.ToMutable();
            var player = Player.CreateForNewRun(
                settings.Character,
                SaveManager.Instance.GenerateUnlockStateFromProgress(),
                1uL);
            var runState = RunState.CreateForNewRun(
                [player],
                acts,
                settings.Modifiers,
                GameMode.Standard,
                settings.Ascension,
                settings.Seed);

            RunManager.Instance.SetUpNewSingleplayer(runState, settings.SaveRunHistory);
            await PreloadManager.LoadRunAssets([settings.Character]);
            RunManager.Instance.Launch();
            var game = NGame.Instance
                ?? throw new InvalidOperationException("NGame is unavailable during warm reset");
            game.RootSceneContainer.SetCurrentScene(NRun.Create(runState));
            await RunManager.Instance.SetActInternal(0);
            RunManager.Instance.RunLocationTargetedBuffer.OnLocationChanged(runState.RunLocation);
            RunManager.Instance.MapSelectionSynchronizer.OnLocationChanged(runState.MapLocation);
            await settings.Setup(player);
            await RunManager.Instance.EnterRoomDebug(
                settings.RoomType,
                MapPointType.Unassigned,
                settings.Encounter.ToMutable());
        }
        catch (Exception exception)
        {
            _resetError = exception.ToString();
            GD.PrintErr($"[STS2 Bootstrap] Warm reset failed: {exception}");
        }
        finally
        {
            Volatile.Write(ref _completedResetId, resetId);
            Interlocked.Exchange(ref _resetting, 0);
        }
    }
}

[HarmonyPatch(typeof(BootstrapSettingsUtil), nameof(BootstrapSettingsUtil.Get))]
internal static class BootstrapSettingsPatch
{
    private static bool Prefix(ref Type? __result)
    {
        __result = typeof(HeadlessBootstrapSettings);
        return false;
    }
}

[HarmonyPatch(
    typeof(SaveManager),
    nameof(SaveManager.GenerateUnlockStateFromProgress))]
internal static class PortableProfilePatch
{
    private static bool Prefix(ref UnlockState __result)
    {
        string? snapshotPath = System.Environment.GetEnvironmentVariable(
            "STS2_BOOTSTRAP_PROFILE_SNAPSHOT");
        if (string.IsNullOrWhiteSpace(snapshotPath))
            return true;

        var snapshot = JsonSerializer.Deserialize<PortableProfileSnapshot>(
            File.ReadAllText(snapshotPath))
            ?? throw new InvalidOperationException(
                $"Invalid portable profile snapshot: {snapshotPath}");

        if (string.Equals(
            snapshot.Mode,
            "all_unlocks",
            StringComparison.Ordinal))
        {
            __result = UnlockState.all;
            GD.Print("[STS2 Bootstrap] Using injected all-unlocks profile");
            return false;
        }
        if (!string.Equals(
            snapshot.Mode,
            "progress_snapshot",
            StringComparison.Ordinal))
        {
            throw new InvalidOperationException(
                $"Unsupported portable profile mode: {snapshot.Mode}");
        }
        if (snapshot.NumberOfRuns < 0)
            throw new InvalidOperationException(
                "Portable profile number_of_runs must be nonnegative");

        var encountersSeen = new List<ModelId>();
        foreach (string encounterId in snapshot.EncounterIdsSeen)
        {
            int separator = encounterId.IndexOf('.');
            if (separator <= 0 || separator == encounterId.Length - 1)
                throw new InvalidOperationException(
                    $"Invalid portable encounter ID: {encounterId}");
            encountersSeen.Add(
                new ModelId(
                    encounterId[..separator],
                    encounterId[(separator + 1)..]));
        }

        __result = new UnlockState(
            snapshot.UnlockedEpochIds,
            encountersSeen,
            snapshot.NumberOfRuns);
        GD.Print(
            "[STS2 Bootstrap] Using injected profile snapshot "
            + $"{snapshot.Sha256} "
            + $"({snapshot.UnlockedEpochIds.Count} epochs, "
            + $"{encountersSeen.Count} encounters, "
            + $"{snapshot.NumberOfRuns} runs)");
        return false;
    }
}

internal sealed class PortableProfileSnapshot
{
    [JsonPropertyName("mode")]
    public string Mode { get; init; } = "";

    [JsonPropertyName("unlocked_epoch_ids")]
    public List<string> UnlockedEpochIds { get; init; } = [];

    [JsonPropertyName("encounter_ids_seen")]
    public List<string> EncounterIdsSeen { get; init; } = [];

    [JsonPropertyName("number_of_runs")]
    public int NumberOfRuns { get; init; }

    [JsonPropertyName("sha256")]
    public string? Sha256 { get; init; }
}

[HarmonyPatch(typeof(NSceneBootstrapper), nameof(NSceneBootstrapper._Ready))]
internal static class ReplayBootstrapPatch
{
    private static bool Prefix(NSceneBootstrapper __instance)
    {
        string? replayPath =
            System.Environment.GetEnvironmentVariable("STS2_REPLAY_PATH");
        if (string.IsNullOrWhiteSpace(replayPath))
            return true;

        TaskHelper.RunSafely(PlayReplayAndQuit(__instance, replayPath));
        return false;
    }

    private static async Task PlayReplayAndQuit(
        NSceneBootstrapper bootstrapper,
        string replayPath)
    {
        try
        {
            await bootstrapper.GetTree().Root.AwaitProcessFrame();
            byte[] bytes = File.ReadAllBytes(replayPath);
            var reader = new PacketReader();
            reader.Reset(bytes);
            CombatReplay replay = reader.Read<CombatReplay>();
            if (replay.modelIdHash != ModelIdSerializationCache.Hash)
            {
                throw new InvalidOperationException(
                    $"Replay model hash {replay.modelIdHash} does not match "
                    + $"loaded models {ModelIdSerializationCache.Hash}");
            }

            var runReplay = AccessTools.Method(
                typeof(NMultiplayerTest),
                "RunReplay")
                ?? throw new MissingMethodException(
                    typeof(NMultiplayerTest).FullName,
                    "RunReplay");
            var replayTask = runReplay.Invoke(
                null,
                [replay, bootstrapper.GetTree()]) as Task
                ?? throw new InvalidOperationException("RunReplay did not return a Task");
            await replayTask;
            await RunManager.Instance.ActionExecutor.FinishedExecutingActions();

            // Leave a short tail so the final action is visible in the movie.
            for (int frame = 0; frame < 120; frame++)
                await bootstrapper.GetTree().Root.AwaitProcessFrame();

            GD.Print($"[STS2 Bootstrap] Replay complete: {replayPath}");
            bootstrapper.GetTree().Quit();
        }
        catch (Exception exception)
        {
            GD.PrintErr($"[STS2 Bootstrap] Replay failed: {exception}");
            bootstrapper.GetTree().Quit(2);
        }
    }
}

public sealed class HeadlessBootstrapSettings : IBootstrapSettings
{
    private readonly string? _seed;

    public HeadlessBootstrapSettings()
    {
    }

    public HeadlessBootstrapSettings(string seed) => _seed = seed;

    public CharacterModel Character =>
        (System.Environment.GetEnvironmentVariable(
            "STS2_BOOTSTRAP_CHARACTER") ?? "Ironclad").Trim().ToLowerInvariant()
        switch
        {
            "ironclad" => ModelDb.Character<Ironclad>(),
            "silent" => ModelDb.Character<Silent>(),
            "defect" => ModelDb.Character<Defect>(),
            "regent" => ModelDb.Character<Regent>(),
            "necrobinder" => ModelDb.Character<Necrobinder>(),
            var character => throw new InvalidOperationException(
                $"Unsupported bootstrap character: {character}")
        };
    public RoomType RoomType =>
        string.Equals(
            System.Environment.GetEnvironmentVariable("STS2_BOOTSTRAP_MODE"),
            "full",
            StringComparison.OrdinalIgnoreCase)
            ? RoomType.Unassigned
            : RoomType.Monster;
    public EncounterModel Encounter => ModelDb.Encounter<FuzzyWurmCrawlerWeak>();
    public EventModel Event => null!;
    public ActModel Act => ModelDb.Act<Overgrowth>();
    public int Ascension
    {
        get
        {
            string? value = System.Environment.GetEnvironmentVariable(
                "STS2_BOOTSTRAP_ASCENSION");
            if (string.IsNullOrWhiteSpace(value))
                return 0;
            if (!int.TryParse(value, out int ascension) || ascension < 0)
                throw new InvalidOperationException(
                    $"Invalid bootstrap ascension: {value}");
            return ascension;
        }
    }
    public bool SaveRunHistory => false;
    public string Seed => _seed ?? System.Environment.GetEnvironmentVariable("STS2_BOOTSTRAP_SEED")
        ?? "HEADLESSBENCH";
    public bool DoPreloading => false;
    public bool BootstrapInMultiplayer => false;
    public List<ModifierModel> Modifiers => [];

    public Task Setup(Player localPlayer)
    {
        SaveManager.Instance.PrefsSave.FastMode = FastModeType.Instant;
        return Task.CompletedTask;
    }
}
