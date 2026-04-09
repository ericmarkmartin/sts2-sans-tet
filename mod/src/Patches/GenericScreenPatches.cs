using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.AutoSlay;
using MegaCrit.Sts2.Core.AutoSlay.Handlers.Rooms;
using MegaCrit.Sts2.Core.AutoSlay.Handlers.Screens;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Cards;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Events;
using MegaCrit.Sts2.Core.Nodes.RestSite;
using MegaCrit.Sts2.Core.Nodes.Rewards;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.Screens;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Random;
using MegaCrit.Sts2.Core.Runs;

namespace RLBridge.Patches;

/// <summary>
/// Patches for non-combat screen decisions: card rewards, events, rewards screen,
/// rest site, shop. These all follow the same pattern: build options, ask agent, execute.
/// Falls back to original AutoSlay behavior if no agent connection.
/// </summary>

// --- Card Reward Screen ---
[HarmonyPatch(typeof(CardRewardScreenHandler), nameof(CardRewardScreenHandler.HandleAsync))]
public static class CardRewardPatch
{
    static bool Prefix(Rng random, CancellationToken ct, ref Task __result)
    {
        if (AgentConnection.Instance == null || !AgentConnection.Instance.IsConnected)
            return true;
        __result = HandleAsync(random, ct);
        return false;
    }

    static async Task HandleAsync(Rng random, CancellationToken ct)
    {
        AutoSlayer.CurrentWatchdog?.Reset("RL Card reward selection");

        var screen = AutoSlayer.GetCurrentScreen<NCardRewardSelectionScreen>();
        await WaitHelper.Until(() =>
        {
            var holders = UiHelper.FindAll<NCardHolder>(screen);
            return holders.Count > 0 && holders.All(h => h.Visible);
        }, ct, AutoSlayConfig.nodeWaitTimeout, "Card holders not ready");

        var cardHolders = UiHelper.FindAll<NCardHolder>(screen);

        var runState = RunManager.Instance.DebugOnlyGetState();
        var player = LocalContext.GetMe(runState);

        var options = cardHolders.Select((ch, i) => new OptionInfo
        {
            Index = i,
            Id = ch.CardModel?.Id.Entry ?? "unknown",
            Description = ch.CardModel?.Id.Entry ?? "unknown"
        }).ToList();

        var obs = ObservationBuilder.BuildOptionsObs("card_reward", options, canSkip: true);
        var runCtx = ObservationBuilder.BuildRunContext(player, runState);

        AgentAction action;
        try
        {
            await AgentConnection.Instance!.SendObservationAsync("card_reward", obs, runCtx, ct);
            action = await AgentConnection.Instance!.ReceiveActionAsync(ct);
        }
        catch
        {
            action = new AgentAction { ActionType = "skip" };
        }

        if (action.ActionType == "skip")
        {
            // Find and click skip/proceed button
            var skipBtn = UiHelper.FindFirst<NProceedButton>((Node)screen);
            if (skipBtn != null)
            {
                await UiHelper.Click(skipBtn);
            }
            return;
        }

        int idx = action.OptionIndex;
        if (idx < 0 || idx >= cardHolders.Count)
            idx = 0;

        RLLog.Info($"Agent picks card: {cardHolders[idx].CardModel?.Id.Entry}");
        cardHolders[idx].EmitSignal(NCardHolder.SignalName.Pressed, cardHolders[idx]);
    }
}

// --- Event Option Screen ---
[HarmonyPatch(typeof(EventRoomHandler), nameof(EventRoomHandler.HandleAsync))]
public static class EventPatch
{
    static bool Prefix(Rng random, CancellationToken ct, ref Task __result)
    {
        if (AgentConnection.Instance == null || !AgentConnection.Instance.IsConnected)
            return true;
        __result = HandleAsync(random, ct);
        return false;
    }

    static async Task HandleAsync(Rng random, CancellationToken ct)
    {
        AutoSlayer.CurrentWatchdog?.Reset("RL Event handling");

        var runState = RunManager.Instance.DebugOnlyGetState();
        var player = LocalContext.GetMe(runState);

        // Wait for event options to appear
        Node root = ((SceneTree)Engine.GetMainLoop()).Root;
        Node? eventRoom = null;

        await WaitHelper.Until(() =>
        {
            eventRoom = root.GetNodeOrNull("/root/Game/RootSceneContainer/Run/RoomContainer/EventRoom");
            return eventRoom != null;
        }, ct, AutoSlayConfig.nodeWaitTimeout, "Event room not found");

        // Handle options loop
        int maxAttempts = 20;
        for (int attempt = 0; attempt < maxAttempts; attempt++)
        {
            ct.ThrowIfCancellationRequested();

            var optionButtons = UiHelper.FindAll<NEventOptionButton>(eventRoom!)
                .Where(o => !o.Option.IsLocked)
                .ToList();

            if (optionButtons.Count == 0)
                break;

            // Check if only proceed option left
            if (optionButtons.All(o => o.Option.IsProceed))
            {
                await UiHelper.Click(optionButtons[0]);
                break;
            }

            var nonProceedOptions = optionButtons.Where(o => !o.Option.IsProceed).ToList();

            var options = nonProceedOptions.Select((ob, i) => new OptionInfo
            {
                Index = i,
                Id = ob.Option?.TextKey ?? $"option_{i}",
                Description = ob.Option?.TextKey ?? $"Option {i}"
            }).ToList();

            var obs = ObservationBuilder.BuildOptionsObs("event", options);
            var runCtx = ObservationBuilder.BuildRunContext(player, runState);

            AgentAction action;
            try
            {
                await AgentConnection.Instance!.SendObservationAsync("event", obs, runCtx, ct);
                action = await AgentConnection.Instance!.ReceiveActionAsync(ct);
            }
            catch
            {
                action = new AgentAction { ActionType = "select_option", OptionIndex = 0 };
            }

            int idx = action.OptionIndex;
            if (idx < 0 || idx >= nonProceedOptions.Count)
                idx = 0;

            RLLog.Info($"Agent picks event option: {nonProceedOptions[idx].Option?.TextKey}");
            await UiHelper.Click(nonProceedOptions[idx]);
            await Task.Delay(500, ct);
        }
    }
}

// --- Rewards Screen ---
// No patch — original AutoSlay behavior (claim all rewards) is fine.
// The interesting decision is the card reward, handled by CardRewardPatch.

// --- Rest Site ---
[HarmonyPatch(typeof(RestSiteRoomHandler), nameof(RestSiteRoomHandler.HandleAsync))]
public static class RestSitePatch
{
    static bool Prefix(Rng random, CancellationToken ct, ref Task __result)
    {
        if (AgentConnection.Instance == null || !AgentConnection.Instance.IsConnected)
            return true;
        __result = HandleAsync(random, ct);
        return false;
    }

    static async Task HandleAsync(Rng random, CancellationToken ct)
    {
        AutoSlayer.CurrentWatchdog?.Reset("RL Rest site");

        var runState = RunManager.Instance.DebugOnlyGetState();
        var player = LocalContext.GetMe(runState);

        Node root = ((SceneTree)Engine.GetMainLoop()).Root;

        var room = await WaitHelper.ForNode<NRestSiteRoom>(root,
            "/root/Game/RootSceneContainer/Run/RoomContainer/RestSiteRoom", ct);

        var validButtons = UiHelper.FindAll<NRestSiteButton>(room)
            .Where(b => b.Option.IsEnabled)
            .ToList();

        if (validButtons.Count == 0)
        {
            RLLog.Warn("No rest site options found");
            return;
        }

        var options = validButtons.Select((b, i) => new OptionInfo
        {
            Index = i,
            Id = b.Option.GetType().Name,
            Description = b.Option.GetType().Name
        }).ToList();

        var obs = ObservationBuilder.BuildOptionsObs("rest_site", options);
        var runCtx = ObservationBuilder.BuildRunContext(player, runState);

        AgentAction action;
        try
        {
            await AgentConnection.Instance!.SendObservationAsync("rest_site", obs, runCtx, ct);
            action = await AgentConnection.Instance!.ReceiveActionAsync(ct);
        }
        catch
        {
            action = new AgentAction { ActionType = "select_option", OptionIndex = 0 };
        }

        int idx = action.OptionIndex;
        if (idx < 0 || idx >= validButtons.Count)
            idx = 0;

        RLLog.Info($"Agent picks rest option: {validButtons[idx].Option.GetType().Name}");
        await UiHelper.Click(validButtons[idx]);
    }
}

// --- Shop ---
// No patch — original AutoSlay behavior (random purchasing) is fine for now.
