using System;
using System.Text.Json;
using HarmonyLib;
using MegaCrit.Sts2.Core.AutoSlay;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Runs;

namespace RLBridge.Patches;

/// <summary>
/// Patches QuitGame to send episode_end to the Python agent before quitting.
/// This ensures the agent gets the final result even on death/victory.
/// The game still quits after one episode for now.
/// </summary>
[HarmonyPatch(typeof(AutoSlayer), "QuitGame")]
public static class QuitGamePatch
{
    static void Prefix(int exitCode)
    {
        var conn = AgentConnection.Instance;
        if (conn == null || !conn.IsConnected)
            return;

        try
        {
            var runState = RunManager.Instance.DebugOnlyGetState();
            var player = runState != null ? LocalContext.GetMe(runState) : null;

            string result = exitCode == 0 ? "victory" : "death";
            int floorReached = runState?.TotalFloor ?? 0;
            int finalHp = player?.Creature?.CurrentHp ?? 0;

            if (finalHp <= 0) result = "death";
            else if (floorReached >= 49) result = "victory";

            var runCtx = player != null && runState != null
                ? ObservationBuilder.BuildRunContext(player, runState)
                : JsonDocument.Parse("{}").RootElement;

            RLLog.Info($"Episode end: {result} at floor {floorReached}, HP={finalHp}");

            // Send synchronously since we're about to quit
            conn.SendEpisodeEndAsync(result, floorReached, finalHp, runCtx).Wait();
        }
        catch (Exception ex)
        {
            RLLog.Error("Failed to send episode end", ex);
        }
    }
}
