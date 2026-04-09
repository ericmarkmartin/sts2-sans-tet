using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.MonsterMoves;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using MegaCrit.Sts2.Core.MonsterMoves.MonsterMoveStateMachine;
using MegaCrit.Sts2.Core.Runs;

namespace RLBridge;

public static class ObservationBuilder
{
    public static JsonElement BuildRunContext(Player player, RunState runState)
    {
        using var stream = new MemoryStream();
        using var writer = new Utf8JsonWriter(stream);

        writer.WriteStartObject();
        writer.WriteString("character", player.Character?.Id.Entry ?? "unknown");
        writer.WriteNumber("act", runState.CurrentActIndex + 1);
        writer.WriteNumber("floor", runState.ActFloor);
        writer.WriteNumber("total_floor", runState.TotalFloor);
        writer.WriteNumber("ascension", runState.AscensionLevel);
        writer.WriteNumber("hp", player.Creature?.CurrentHp ?? 0);
        writer.WriteNumber("max_hp", player.Creature?.MaxHp ?? 0);
        writer.WriteNumber("gold", player.Gold);

        // Deck
        writer.WriteStartArray("deck");
        foreach (var card in player.Deck?.Cards ?? Enumerable.Empty<CardModel>())
        {
            WriteCardBrief(writer, card);
        }
        writer.WriteEndArray();

        // Relics
        writer.WriteStartArray("relics");
        foreach (var relic in player.Relics ?? Enumerable.Empty<RelicModel>())
        {
            writer.WriteStringValue(relic.Id.Entry);
        }
        writer.WriteEndArray();

        // Potions
        writer.WriteStartArray("potions");
        foreach (var potion in player.Potions ?? Enumerable.Empty<PotionModel>())
        {
            if (potion != null)
                writer.WriteStringValue(potion.Id.Entry);
            else
                writer.WriteNullValue();
        }
        writer.WriteEndArray();

        writer.WriteEndObject();
        writer.Flush();

        return JsonDocument.Parse(stream.ToArray()).RootElement.Clone();
    }

    public static JsonElement BuildCombatObs(Player player, CombatState combatState)
    {
        using var stream = new MemoryStream();
        using var writer = new Utf8JsonWriter(stream);

        var pcs = player.PlayerCombatState;
        var creature = player.Creature;

        writer.WriteStartObject();

        writer.WriteNumber("energy", pcs?.Energy ?? 0);
        writer.WriteNumber("max_energy", pcs?.MaxEnergy ?? 0);
        writer.WriteNumber("stars", pcs?.Stars ?? 0);
        writer.WriteNumber("round", combatState.RoundNumber);

        // Hand
        writer.WriteStartArray("hand");
        var handCards = pcs?.Hand?.Cards ?? Enumerable.Empty<CardModel>();
        int cardIdx = 0;
        foreach (var card in handCards)
        {
            WriteCardDetailed(writer, card, cardIdx);
            cardIdx++;
        }
        writer.WriteEndArray();

        writer.WriteNumber("draw_pile_count", pcs?.DrawPile?.Cards?.Count() ?? 0);
        writer.WriteNumber("discard_pile_count", pcs?.DiscardPile?.Cards?.Count() ?? 0);
        writer.WriteNumber("exhaust_pile_count", pcs?.ExhaustPile?.Cards?.Count() ?? 0);

        // Player
        writer.WriteStartObject("player");
        writer.WriteNumber("hp", creature?.CurrentHp ?? 0);
        writer.WriteNumber("max_hp", creature?.MaxHp ?? 0);
        writer.WriteNumber("block", creature?.Block ?? 0);
        WritePowers(writer, creature);
        writer.WriteEndObject();

        // Enemies
        writer.WriteStartArray("enemies");
        int enemyIdx = 0;
        foreach (var enemy in combatState.HittableEnemies ?? Enumerable.Empty<Creature>())
        {
            WriteEnemy(writer, enemy, enemyIdx, combatState);
            enemyIdx++;
        }
        // Also include non-hittable alive enemies so agent sees full board
        foreach (var enemy in (combatState.Enemies ?? Enumerable.Empty<Creature>())
            .Where(e => e.IsAlive && !combatState.HittableEnemies.Contains(e)))
        {
            WriteEnemy(writer, enemy, enemyIdx, combatState);
            enemyIdx++;
        }
        writer.WriteEndArray();

        // Valid actions
        writer.WriteStartObject("valid_actions");

        var playable = new List<int>();
        var needsTarget = new List<int>();
        cardIdx = 0;
        foreach (var card in handCards)
        {
            if (card.CanPlay(out UnplayableReason _, out AbstractModel _))
            {
                playable.Add(cardIdx);
                if (card.TargetType == TargetType.AnyEnemy)
                {
                    needsTarget.Add(cardIdx);
                }
            }
            cardIdx++;
        }

        writer.WriteStartArray("playable_cards");
        foreach (var i in playable) writer.WriteNumberValue(i);
        writer.WriteEndArray();

        writer.WriteStartArray("cards_needing_target");
        foreach (var i in needsTarget) writer.WriteNumberValue(i);
        writer.WriteEndArray();

        var usablePotions = new List<int>();
        var potions = player.Potions?.ToList() ?? new List<PotionModel>();
        for (int pi = 0; pi < potions.Count; pi++)
        {
            if (potions[pi] != null)
                usablePotions.Add(pi);
        }
        writer.WriteStartArray("potions_usable");
        foreach (var i in usablePotions) writer.WriteNumberValue(i);
        writer.WriteEndArray();

        writer.WriteBoolean("can_end_turn", true);

        writer.WriteEndObject(); // valid_actions

        writer.WriteEndObject();
        writer.Flush();

        return JsonDocument.Parse(stream.ToArray()).RootElement.Clone();
    }

    public static JsonElement BuildOptionsObs(string decisionType, List<OptionInfo> options, bool canSkip = false)
    {
        using var stream = new MemoryStream();
        using var writer = new Utf8JsonWriter(stream);

        writer.WriteStartObject();
        writer.WriteString("decision_type", decisionType);

        writer.WriteStartArray("options");
        foreach (var opt in options)
        {
            writer.WriteStartObject();
            writer.WriteNumber("index", opt.Index);
            writer.WriteString("id", opt.Id);
            writer.WriteString("description", opt.Description);
            if (opt.ExtraInfo != null)
            {
                foreach (var kv in opt.ExtraInfo)
                {
                    writer.WriteString(kv.Key, kv.Value);
                }
            }
            writer.WriteEndObject();
        }
        writer.WriteEndArray();

        writer.WriteBoolean("can_skip", canSkip);

        writer.WriteEndObject();
        writer.Flush();

        return JsonDocument.Parse(stream.ToArray()).RootElement.Clone();
    }

    private static void WriteCardBrief(Utf8JsonWriter writer, CardModel card)
    {
        writer.WriteStartObject();
        writer.WriteString("id", card.Id.Entry);
        writer.WriteNumber("upgrade_level", card.CurrentUpgradeLevel);
        writer.WriteEndObject();
    }

    private static void WriteCardDetailed(Utf8JsonWriter writer, CardModel card, int index)
    {
        writer.WriteStartObject();
        writer.WriteNumber("index", index);
        writer.WriteString("id", card.Id.Entry);
        writer.WriteNumber("upgrade_level", card.CurrentUpgradeLevel);
        writer.WriteNumber("cost", card.EnergyCost?.GetResolved() ?? 0);
        writer.WriteNumber("star_cost", card.GetStarCostWithModifiers());
        writer.WriteString("type", card.Type.ToString());
        writer.WriteString("rarity", card.Rarity.ToString());
        writer.WriteString("target_type", card.TargetType.ToString());

        bool canPlay = card.CanPlay(out UnplayableReason _, out AbstractModel _);
        writer.WriteBoolean("can_play", canPlay);

        writer.WriteStartArray("keywords");
        foreach (var kw in card.Keywords ?? Enumerable.Empty<CardKeyword>())
        {
            if (kw != CardKeyword.None)
                writer.WriteStringValue(kw.ToString());
        }
        writer.WriteEndArray();

        writer.WriteEndObject();
    }

    private static void WriteEnemy(Utf8JsonWriter writer, Creature enemy, int index, CombatState combatState)
    {
        writer.WriteStartObject();
        writer.WriteNumber("index", index);
        writer.WriteString("id", enemy.Monster?.Id.Entry ?? "unknown");
        writer.WriteNumber("hp", enemy.CurrentHp);
        writer.WriteNumber("max_hp", enemy.MaxHp);
        writer.WriteNumber("block", enemy.Block);
        writer.WriteBoolean("is_hittable", combatState.HittableEnemies?.Contains(enemy) ?? false);

        WritePowers(writer, enemy);

        // Intents
        writer.WriteStartArray("intents");
        var nextMove = enemy.Monster?.NextMove;
        if (nextMove is MoveState moveState)
        {
            foreach (var intent in moveState.Intents ?? Enumerable.Empty<AbstractIntent>())
            {
                writer.WriteStartObject();
                writer.WriteString("type", intent.IntentType.ToString());

                if (intent is AttackIntent attackIntent)
                {
                    try
                    {
                        var targets = combatState.PlayerCreatures ?? Enumerable.Empty<Creature>();
                        writer.WriteNumber("damage", attackIntent.GetSingleDamage(targets, enemy));
                        writer.WriteNumber("hits", attackIntent.Repeats);
                    }
                    catch
                    {
                        writer.WriteNumber("damage", -1);
                        writer.WriteNumber("hits", 1);
                    }
                }

                writer.WriteEndObject();
            }
        }
        writer.WriteEndArray();

        writer.WriteEndObject();
    }

    private static void WritePowers(Utf8JsonWriter writer, Creature? creature)
    {
        writer.WriteStartArray("powers");
        if (creature != null)
        {
            foreach (var power in creature.Powers ?? Enumerable.Empty<PowerModel>())
            {
                if (power.IsVisible)
                {
                    writer.WriteStartObject();
                    writer.WriteString("id", power.Id.Entry);
                    writer.WriteNumber("amount", power.Amount);
                    writer.WriteString("type", power.Type.ToString());
                    writer.WriteEndObject();
                }
            }
        }
        writer.WriteEndArray();
    }
}

public class OptionInfo
{
    public int Index { get; set; }
    public string Id { get; set; } = "";
    public string Description { get; set; } = "";
    public Dictionary<string, string>? ExtraInfo { get; set; }
}
