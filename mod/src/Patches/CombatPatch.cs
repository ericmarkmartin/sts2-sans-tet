using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using HarmonyLib;
using MegaCrit.Sts2.Core.AutoSlay;
using MegaCrit.Sts2.Core.AutoSlay.Handlers.Rooms;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Random;
using MegaCrit.Sts2.Core.Runs;

namespace RLBridge.Patches;

[HarmonyPatch(typeof(CombatRoomHandler), nameof(CombatRoomHandler.HandleAsync))]
public static class CombatPatch
{
    static bool Prefix(Rng random, CancellationToken ct, ref Task __result)
    {
        var conn = AgentConnection.Instance;
        if (conn == null || !conn.IsConnected)
        {
            RLLog.Warn("No agent connection, falling back to original AutoSlay combat");
            return true; // run original
        }

        __result = HandleCombatAsync(ct);
        return false; // skip original
    }

    private static async Task HandleCombatAsync(CancellationToken ct)
    {
        RLLog.Info("Waiting for combat to start");
        await WaitHelper.Until(
            () => CombatManager.Instance.IsInProgress,
            ct, AutoSlayConfig.nodeWaitTimeout, "Combat not started");

        RLLog.Info("Combat started (RL-driven)");

        Player player = LocalContext.GetMe(RunManager.Instance.DebugOnlyGetState());
        RunState runState = RunManager.Instance.DebugOnlyGetState();

        int turnCount = 0;
        while (CombatManager.Instance.IsInProgress && turnCount < 200)
        {
            ct.ThrowIfCancellationRequested();
            turnCount++;

            await WaitHelper.Until(
                () => CombatManager.Instance.IsPlayPhase || !CombatManager.Instance.IsInProgress,
                ct, TimeSpan.FromSeconds(30), "Play phase not started");

            if (!CombatManager.Instance.IsInProgress) break;

            AutoSlayer.CurrentWatchdog?.Reset($"RL Combat turn {turnCount}");
            RLLog.Info($"Turn {turnCount}: requesting agent decisions");

            // Per-turn action loop — agent can play multiple cards per turn
            int actionsThisTurn = 0;
            while (CombatManager.Instance.IsPlayPhase && CombatManager.Instance.IsInProgress && actionsThisTurn < 50)
            {
                ct.ThrowIfCancellationRequested();
                actionsThisTurn++;

                if (actionsThisTurn % 10 == 0)
                    AutoSlayer.CurrentWatchdog?.Reset($"RL Combat turn {turnCount}, action {actionsThisTurn}");

                CombatState combatState = CombatManager.Instance.DebugOnlyGetState();
                var obs = ObservationBuilder.BuildCombatObs(player, combatState);
                var runCtx = ObservationBuilder.BuildRunContext(player, runState);

                AgentAction action;
                try
                {
                    await AgentConnection.Instance!.SendObservationAsync("combat", obs, runCtx, ct);
                    action = await AgentConnection.Instance!.ReceiveActionAsync(ct);
                }
                catch (Exception ex)
                {
                    RLLog.Error("Failed to get agent action, ending turn", ex);
                    break;
                }

                if (action.ActionType == "end_turn")
                {
                    RLLog.Info("Agent chose: end_turn");
                    break;
                }

                if (action.ActionType == "play_card")
                {
                    var hand = PileType.Hand.GetPile(player);
                    var handCards = hand.Cards.ToList();

                    if (action.CardIndex < 0 || action.CardIndex >= handCards.Count)
                    {
                        RLLog.Warn($"Invalid card index {action.CardIndex}, ending turn");
                        break;
                    }

                    CardModel card = handCards[action.CardIndex];
                    if (!card.CanPlay(out UnplayableReason reason, out AbstractModel _))
                    {
                        RLLog.Warn($"Card {card.Id.Entry} not playable ({reason}), ending turn");
                        break;
                    }

                    Creature? target = null;
                    if (card.TargetType == TargetType.AnyEnemy)
                    {
                        var enemies = combatState.HittableEnemies.ToList();
                        if (action.TargetIndex >= 0 && action.TargetIndex < enemies.Count)
                        {
                            target = enemies[action.TargetIndex];
                        }
                        else if (enemies.Count > 0)
                        {
                            target = enemies[0]; // fallback to first enemy
                        }
                        else
                        {
                            RLLog.Warn("No hittable enemies for targeted card, ending turn");
                            break;
                        }
                    }

                    RLLog.Info($"Agent plays: {card.Id.Entry} -> {target?.Monster?.Id.Entry ?? "no target"}");
                    await CardCmd.AutoPlay(new MegaCrit.Sts2.Core.GameActions.Multiplayer.BlockingPlayerChoiceContext(), card, target);
                    await Task.Delay(100, ct);
                }
                else if (action.ActionType == "use_potion")
                {
                    var potions = player.Potions?.ToList() ?? new List<PotionModel>();
                    if (action.PotionIndex >= 0 && action.PotionIndex < potions.Count && potions[action.PotionIndex] != null)
                    {
                        var potion = potions[action.PotionIndex];
                        Creature? target = null;

                        if (potion.TargetType == TargetType.AnyEnemy)
                        {
                            var enemies = combatState.HittableEnemies.ToList();
                            if (action.TargetIndex >= 0 && action.TargetIndex < enemies.Count)
                                target = enemies[action.TargetIndex];
                            else if (enemies.Count > 0)
                                target = enemies[0];
                        }
                        else if (potion.TargetType == TargetType.AnyAlly || potion.TargetType == TargetType.Self || potion.TargetType == TargetType.AnyPlayer)
                        {
                            target = player.Creature;
                        }

                        RLLog.Info($"Agent uses potion: {potion.Id.Entry}");
                        potion.EnqueueManualUse(target);
                        await Task.Delay(300, ct);
                    }
                    else
                    {
                        RLLog.Warn($"Invalid potion index {action.PotionIndex}, ending turn");
                        break;
                    }
                }
                else
                {
                    RLLog.Warn($"Unknown action type: {action.ActionType}, ending turn");
                    break;
                }
            }

            // End turn
            if (CombatManager.Instance.IsPlayPhase && CombatManager.Instance.IsInProgress)
            {
                PlayerCmd.EndTurn(player, canBackOut: false);
            }
        }

        await WaitHelper.Until(
            () => !CombatManager.Instance.IsInProgress,
            ct, TimeSpan.FromSeconds(30), "Combat did not end");

        RLLog.Info("Combat finished");
    }
}
