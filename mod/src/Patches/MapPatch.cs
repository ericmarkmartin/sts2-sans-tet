using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.AutoSlay;
using MegaCrit.Sts2.Core.AutoSlay.Handlers.Screens;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.Random;
using MegaCrit.Sts2.Core.Runs;

namespace RLBridge.Patches;

[HarmonyPatch(typeof(MapScreenHandler), nameof(MapScreenHandler.HandleAsync))]
public static class MapPatch
{
    static bool Prefix(Rng random, CancellationToken ct, ref Task __result)
    {
        var conn = AgentConnection.Instance;
        if (conn == null || !conn.IsConnected)
            return true;

        __result = HandleMapAsync(random, ct);
        return false;
    }

    private static async Task HandleMapAsync(Rng random, CancellationToken ct)
    {
        RLLog.Info("Map handler: waiting for map screen");

        Node root = ((SceneTree)Engine.GetMainLoop()).Root;
        NRun runNode = root.GetNode<NRun>("/root/Game/RootSceneContainer/Run");

        await WaitHelper.Until(
            () => runNode.GlobalUi.MapScreen.IsVisibleInTree(),
            ct, AutoSlayConfig.mapScreenTimeout, "Map screen not visible");

        List<NMapPoint> allMapPoints = UiHelper.FindAll<NMapPoint>(runNode.GlobalUi.MapScreen);
        RunState runState = RunManager.Instance.DebugOnlyGetState();
        Player player = LocalContext.GetMe(runState);

        // Determine which NMapPoints are valid next choices
        List<NMapPoint> validNextPoints;
        List<MapPoint> validChildren;

        if (runState.VisitedMapCoords.Count == 0)
        {
            // First room: row 0
            validNextPoints = allMapPoints
                .Where(mp => mp.Point.coord.row == 0)
                .ToList();
            validChildren = validNextPoints.Select(mp => mp.Point).ToList();
            RLLog.Info($"Map: first room, {validChildren.Count} starting options");
        }
        else
        {
            var visited = runState.VisitedMapCoords;
            MapCoord lastCoord = visited[visited.Count - 1];
            NMapPoint currentNode = allMapPoints.First(mp => mp.Point.coord.Equals(lastCoord));
            var children = currentNode.Point.Children.ToList();
            validChildren = children;

            validNextPoints = new List<NMapPoint>();
            foreach (var child in children)
            {
                var nmp = allMapPoints.FirstOrDefault(mp => mp.Point.coord.Equals(child.coord));
                if (nmp != null)
                    validNextPoints.Add(nmp);
            }
            RLLog.Info($"Map: {validChildren.Count} children from ({lastCoord.col}, {lastCoord.row})");
        }

        if (validNextPoints.Count == 0)
        {
            RLLog.Error("Map: no valid next points found, cannot proceed");
            return;
        }

        // If only one choice, just pick it without asking agent
        int chosenIdx = 0;
        if (validNextPoints.Count > 1)
        {
            // Ask agent
            var options = validChildren.Select((mp, i) => new OptionInfo
            {
                Index = i,
                Id = mp.PointType.ToString(),
                Description = $"{mp.PointType} at ({mp.coord.col}, {mp.coord.row})",
                ExtraInfo = new Dictionary<string, string>
                {
                    ["col"] = mp.coord.col.ToString(),
                    ["row"] = mp.coord.row.ToString(),
                    ["type"] = mp.PointType.ToString()
                }
            }).ToList();

            try
            {
                var obs = ObservationBuilder.BuildOptionsObs("map", options);
                var runCtx = ObservationBuilder.BuildRunContext(player, runState);
                await AgentConnection.Instance!.SendObservationAsync("map", obs, runCtx, ct);
                var action = await AgentConnection.Instance!.ReceiveActionAsync(ct);

                chosenIdx = action.OptionIndex;
                if (chosenIdx < 0 || chosenIdx >= validNextPoints.Count)
                    chosenIdx = 0;
            }
            catch (Exception ex)
            {
                RLLog.Error("Map decision failed, picking first option", ex);
                chosenIdx = 0;
            }
        }

        NMapPoint nextRoom = validNextPoints[chosenIdx];
        RLLog.Info($"Map: selected {validChildren[chosenIdx].PointType} at ({validChildren[chosenIdx].coord.col}, {validChildren[chosenIdx].coord.row})");

        // Wait for the point to become clickable
        await WaitHelper.Until(
            () => nextRoom.IsEnabled,
            ct, TimeSpan.FromSeconds(10), "Map point not enabled");

        // Click and wait for room entry (same as original handler)
        var roomEnteredTcs = new TaskCompletionSource();
        void OnRoomEntered() => roomEnteredTcs.TrySetResult();

        RunManager.Instance.RoomEntered += OnRoomEntered;
        try
        {
            await UiHelper.Click(nextRoom);
            await WaitHelper.ForTask(
                roomEnteredTcs.Task, ct,
                AutoSlayConfig.mapScreenTimeout, "Room not entered after map click");
        }
        finally
        {
            RunManager.Instance.RoomEntered -= OnRoomEntered;
        }

        RLLog.Info("Map: room entered");
    }
}
