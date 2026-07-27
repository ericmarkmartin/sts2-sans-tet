using System.Collections;
using System.Reflection;

namespace STS2Headless;

/// <summary>
/// Builds an engine-independent decision observation from authoritative game
/// models. Localized text and scene nodes are intentionally excluded: IDs,
/// numeric values, phases, and choice legality are stable policy inputs.
/// </summary>
internal static class StandaloneObservationBuilder
{
    public const string Schema = "sts2.standalone.combat.v1";

    public static Dictionary<string, object?> Build(
        Assembly gameAssembly,
        object runManager)
    {
        var combatManagerType = gameAssembly.GetType(
            "MegaCrit.Sts2.Core.Combat.CombatManager", throwOnError: true)!;
        var combatManager = GetRequiredProperty(
            combatManagerType, null, "Instance");
        var combatState = combatManagerType.GetField(
                "_state", BindingFlags.NonPublic | BindingFlags.Instance)
            ?.GetValue(combatManager)
            ?? throw new MissingFieldException(combatManagerType.FullName, "_state");
        var players = AsObjects(GetRequiredProperty(
            combatState.GetType(), combatState, "Players"));
        var player = players.Single();
        var playerCombatState = GetRequiredProperty(
            player.GetType(), player, "PlayerCombatState");
        var enemies = AsObjects(GetRequiredProperty(
            combatState.GetType(), combatState, "Enemies"));
        var phase = ReadString(playerCombatState, "Phase");
        var legalActions = BuildLegalActions(
            playerCombatState, enemies, phase);

        return new Dictionary<string, object?>
        {
            ["schema"] = Schema,
            ["information_policy"] = "omniscient_authoritative",
            ["decision"] = new Dictionary<string, object?>
            {
                ["phase"] = phase,
                ["turn_number"] = ReadInt(playerCombatState, "TurnNumber"),
                ["round_number"] = ReadInt(combatState, "RoundNumber"),
                ["current_side"] = ReadString(combatState, "CurrentSide"),
                ["combat_in_progress"] = ReadBool(
                    combatManager, "IsInProgress"),
                ["player_actions_disabled"] = ReadBool(
                    combatManager, "PlayerActionsDisabled")
            },
            ["player"] = BuildPlayer(player, playerCombatState),
            ["enemies"] = enemies.Select(BuildEnemy).ToList(),
            ["legal_actions"] = legalActions,
            ["checksum"] = BuildChecksumState(runManager)
        };
    }

    private static Dictionary<string, object?> BuildPlayer(
        object player,
        object combatState)
    {
        var creature = GetRequiredProperty(player.GetType(), player, "Creature");
        return new Dictionary<string, object?>
        {
            ["net_id"] = ReadUnsigned(player, "NetId"),
            ["character_id"] = ModelId(
                GetRequiredProperty(player.GetType(), player, "Character")),
            ["hp"] = ReadInt(creature, "CurrentHp"),
            ["max_hp"] = ReadInt(creature, "MaxHp"),
            ["block"] = ReadInt(creature, "Block"),
            ["energy"] = ReadInt(combatState, "Energy"),
            ["max_energy"] = ReadInt(combatState, "MaxEnergy"),
            ["stars"] = ReadInt(combatState, "Stars"),
            ["gold"] = ReadInt(player, "Gold"),
            ["powers"] = BuildModels(
                GetRequiredProperty(creature.GetType(), creature, "Powers"),
                includeAmount: true),
            ["relics"] = BuildModels(
                GetRequiredProperty(player.GetType(), player, "Relics"),
                includeAmount: true),
            ["potions"] = BuildModels(
                GetRequiredProperty(player.GetType(), player, "PotionSlots"),
                includeAmount: false),
            ["piles"] = new Dictionary<string, object?>
            {
                ["hand"] = BuildPile(combatState, "Hand", includeCanPlay: true),
                ["draw"] = BuildPile(combatState, "DrawPile", includeCanPlay: false),
                ["discard"] = BuildPile(
                    combatState, "DiscardPile", includeCanPlay: false),
                ["exhaust"] = BuildPile(
                    combatState, "ExhaustPile", includeCanPlay: false)
            }
        };
    }

    private static List<Dictionary<string, object?>> BuildPile(
        object playerCombatState,
        string propertyName,
        bool includeCanPlay)
    {
        var pile = GetRequiredProperty(
            playerCombatState.GetType(), playerCombatState, propertyName);
        return AsObjects(GetRequiredProperty(pile.GetType(), pile, "Cards"))
            .Select((card, index) => BuildCard(card, index, includeCanPlay))
            .ToList();
    }

    private static Dictionary<string, object?> BuildCard(
        object card,
        int index,
        bool includeCanPlay)
    {
        var result = new Dictionary<string, object?>
        {
            ["index"] = index,
            ["id"] = ModelId(card),
            ["type"] = ReadString(card, "Type"),
            ["rarity"] = ReadString(card, "Rarity"),
            ["upgraded"] = ReadBool(card, "IsUpgraded")
        };
        var energyCost = GetRequiredProperty(
            card.GetType(), card, "EnergyCost");
        result["energy_cost"] = new Dictionary<string, object?>
        {
            ["amount"] = Convert.ToInt32(
                energyCost.GetType().GetMethod("GetAmountToSpend")
                    ?.Invoke(energyCost, null)),
            ["is_x"] = ReadBool(energyCost, "CostsX")
        };
        result["star_cost"] = ReadInt(card, "CurrentStarCost");
        result["target_type"] = ReadString(card, "TargetType");
        result["dynamic_vars"] = BuildDynamicVars(card);
        if (includeCanPlay)
        {
            result["can_play"] = card.GetType().GetMethod(
                    "CanPlay", Type.EmptyTypes)?.Invoke(card, null) is true;
        }
        return result;
    }

    private static Dictionary<string, object?> BuildEnemy(object creature)
    {
        var monster = creature.GetType().GetProperty("Monster")?.GetValue(creature);
        return new Dictionary<string, object?>
        {
            ["combat_id"] = ReadNullableUnsigned(creature, "CombatId"),
            ["model_id"] = monster is null ? null : ModelId(monster),
            ["hp"] = ReadInt(creature, "CurrentHp"),
            ["max_hp"] = ReadInt(creature, "MaxHp"),
            ["block"] = ReadInt(creature, "Block"),
            ["is_dead"] = ReadBool(creature, "IsDead"),
            ["powers"] = BuildModels(
                GetRequiredProperty(creature.GetType(), creature, "Powers"),
                includeAmount: true),
            ["intents"] = monster is null
                ? []
                : BuildIntents(monster)
        };
    }

    private static List<Dictionary<string, object?>> BuildIntents(object monster)
    {
        var nextMove = monster.GetType().GetProperty("NextMove")?.GetValue(monster);
        if (nextMove is null)
            return [];
        var intents = nextMove.GetType().GetProperty("Intents")?.GetValue(nextMove);
        if (intents is null)
            return [];
        return AsObjects(intents).Select(intent =>
        {
            var item = new Dictionary<string, object?>
            {
                ["type"] = ReadString(intent, "IntentType")
            };
            var repeats = intent.GetType().GetProperty("Repeats");
            if (repeats is not null)
                item["repeats"] = Convert.ToInt32(repeats.GetValue(intent));
            var damageCalc = intent.GetType().GetProperty("DamageCalc")
                ?.GetValue(intent) as Delegate;
            if (damageCalc is not null)
                item["damage_per_hit"] = Convert.ToDecimal(
                    damageCalc.DynamicInvoke());
            return item;
        }).ToList();
    }

    private static List<Dictionary<string, object?>> BuildDynamicVars(
        object model)
    {
        var set = model.GetType().GetProperty("DynamicVars")?.GetValue(model);
        var values = set?.GetType().GetProperty("Values")?.GetValue(set);
        if (values is null)
            return [];
        return AsObjects(values).Select(value =>
            new Dictionary<string, object?>
            {
                ["name"] = ReadString(value, "Name"),
                ["base_value"] = Convert.ToDecimal(
                    GetRequiredProperty(value.GetType(), value, "BaseValue")),
                ["value"] = ReadInt(value, "IntValue")
            }).ToList();
    }

    private static List<Dictionary<string, object?>> BuildModels(
        object values,
        bool includeAmount)
    {
        var result = new List<Dictionary<string, object?>>();
        var slot = 0;
        foreach (var model in AsObjects(values))
        {
            var item = new Dictionary<string, object?>
            {
                ["slot"] = slot++,
                ["id"] = ModelId(model)
            };
            if (includeAmount
                && model.GetType().GetProperty("Amount") is not null)
                item["amount"] = ReadInt(model, "Amount");
            if (includeAmount
                && model.GetType().GetProperty("StackCount") is not null)
                item["stack_count"] = ReadInt(model, "StackCount");
            result.Add(item);
        }
        return result;
    }

    private static List<Dictionary<string, object?>> BuildLegalActions(
        object playerCombatState,
        IReadOnlyList<object> enemies,
        string phase)
    {
        var actions = new List<Dictionary<string, object?>>();
        if (phase != "Play")
            return actions;

        var hand = BuildRawPile(playerCombatState, "Hand");
        for (var index = 0; index < hand.Count; index++)
        {
            var card = hand[index];
            if (card.GetType().GetMethod(
                    "CanPlay", Type.EmptyTypes)?.Invoke(card, null) is not true)
                continue;
            var isValidTarget = card.GetType().GetMethod(
                    "IsValidTarget",
                    BindingFlags.Public | BindingFlags.Instance)
                ?? throw new MissingMethodException(
                    card.GetType().FullName, "IsValidTarget");
            var validTargets = enemies
                .Where(enemy =>
                    !ReadBool(enemy, "IsDead")
                    && isValidTarget.Invoke(card, [enemy]) is true)
                .Select(enemy => ReadNullableUnsigned(enemy, "CombatId"))
                .ToList();
            if (validTargets.Count > 0)
            {
                actions.AddRange(validTargets.Select(target =>
                    new Dictionary<string, object?>
                    {
                        ["action"] = "play_card",
                        ["card_index"] = index,
                        ["card_id"] = ModelId(card),
                        ["target_combat_id"] = target
                    }));
            }
            else if (isValidTarget.Invoke(card, [null]) is true)
            {
                actions.Add(new Dictionary<string, object?>
                {
                    ["action"] = "play_card",
                    ["card_index"] = index,
                    ["card_id"] = ModelId(card),
                    ["target_combat_id"] = null
                });
            }
        }
        actions.Add(new Dictionary<string, object?>
        {
            ["action"] = "end_turn"
        });
        return actions;
    }

    private static List<object> BuildRawPile(
        object playerCombatState,
        string propertyName)
    {
        var pile = GetRequiredProperty(
            playerCombatState.GetType(), playerCombatState, propertyName);
        return AsObjects(GetRequiredProperty(pile.GetType(), pile, "Cards"));
    }

    private static Dictionary<string, object?> BuildChecksumState(
        object runManager)
    {
        var tracker = GetRequiredProperty(
            runManager.GetType(), runManager, "ChecksumTracker");
        return new Dictionary<string, object?>
        {
            ["enabled"] = ReadBool(tracker, "IsEnabled"),
            ["next_id"] = ReadUnsigned(tracker, "NextId")
        };
    }

    private static object GetRequiredProperty(
        Type type,
        object? instance,
        string propertyName) =>
        type.GetProperty(
                propertyName,
                BindingFlags.Public | BindingFlags.NonPublic |
                BindingFlags.Instance | BindingFlags.Static)
            ?.GetValue(instance)
        ?? throw new MissingMemberException(type.FullName, propertyName);

    private static List<object> AsObjects(object enumerable) =>
        ((IEnumerable)enumerable).Cast<object?>()
            .Where(value => value is not null)
            .Cast<object>()
            .ToList();

    private static string ModelId(object model)
    {
        var id = GetRequiredProperty(model.GetType(), model, "Id");
        return GetRequiredProperty(id.GetType(), id, "Entry").ToString()
            ?? "unknown";
    }

    private static string ReadString(object value, string propertyName) =>
        GetRequiredProperty(value.GetType(), value, propertyName).ToString()
        ?? "Unknown";

    private static int ReadInt(object value, string propertyName) =>
        Convert.ToInt32(
            GetRequiredProperty(value.GetType(), value, propertyName));

    private static bool ReadBool(object value, string propertyName) =>
        Convert.ToBoolean(
            GetRequiredProperty(value.GetType(), value, propertyName));

    private static ulong ReadUnsigned(object value, string propertyName) =>
        Convert.ToUInt64(
            GetRequiredProperty(value.GetType(), value, propertyName));

    private static ulong? ReadNullableUnsigned(
        object value,
        string propertyName)
    {
        var raw = value.GetType().GetProperty(propertyName)?.GetValue(value);
        return raw is null ? null : Convert.ToUInt64(raw);
    }
}
