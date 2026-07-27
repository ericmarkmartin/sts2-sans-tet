using System.Collections;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.Loader;
using System.Text.Json;

namespace STS2Headless;

internal static class Program
{
    private const string RunManagerTypeName = "MegaCrit.Sts2.Core.Runs.RunManager";

    public static int Main(string[] args)
    {
        Console.SetOut(new StreamWriter(Console.OpenStandardOutput()) { AutoFlush = true });
        Console.SetError(new StreamWriter(Console.OpenStandardError()) { AutoFlush = true });

        try
        {
            var options = Options.Parse(args);
            using var host = new GameAssemblyHost(options.GameDataDirectory);
            return options.Command switch
            {
                "probe" => Probe(host),
                "inspect" => Inspect(host, options.TypeName),
                "phase-b-startup" => PhaseBStartup(
                    host, initializeManager: false, enterCombat: false,
                    driveActionCycle: false, emitObservation: false),
                "phase-b-manager" => PhaseBStartup(
                    host, initializeManager: true, enterCombat: false,
                    driveActionCycle: false, emitObservation: false),
                "phase-c-combat" => PhaseBStartup(
                    host, initializeManager: true, enterCombat: true,
                    driveActionCycle: false, emitObservation: false),
                "phase-c-action-cycle" => PhaseBStartup(
                    host, initializeManager: true, enterCombat: true,
                    driveActionCycle: true, emitObservation: false),
                "phase-d-observation" => PhaseBStartup(
                    host, initializeManager: true, enterCombat: true,
                    driveActionCycle: false, emitObservation: true),
                "stdio" => Stdio(host),
                _ => throw new ArgumentException($"Unknown command: {options.Command}")
            };
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception);
            return 1;
        }
    }

    private static int PhaseBStartup(
        GameAssemblyHost host,
        bool initializeManager,
        bool enterCombat,
        bool driveActionCycle,
        bool emitObservation)
    {
        var assembly = InitializeStandaloneAssembly(host);
        var state = CreateStandaloneRunState(assembly, "HEADLESSBENCH");
        if (!initializeManager)
            return 0;
        var manager = SetupStandaloneManager(assembly, state, enterCombat);
        if (driveActionCycle)
            RunScriptedActionCycle(assembly, manager);
        if (emitObservation)
            WriteObservation(assembly, manager);
        return 0;
    }

    private static Assembly InitializeStandaloneAssembly(GameAssemblyHost host)
    {
        var assembly = host.LoadGameAssembly();
        StandaloneRuntimePatches.Install(assembly);
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "standalone_runtime_patches_installed"
        }));
        EnableGameTestMode(assembly);
        MarkModLoadingSkipped(assembly);
        var modelDbType = assembly.GetType("MegaCrit.Sts2.Core.Models.ModelDb", throwOnError: true)!;
        modelDbType.GetMethod("Init", BindingFlags.Public | BindingFlags.Static)!.Invoke(null, null);
        Console.WriteLine(JsonSerializer.Serialize(new { stage = "model_instances_created" }));
        var cache = StandaloneModelCacheInitializer.Initialize(assembly);
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "model_cache_initialized_without_godot",
            model_types = cache.ModelTypes,
            categories = cache.Categories,
            entries = cache.Entries,
            epochs = cache.Epochs,
            hash = cache.Hash
        }));
        modelDbType.GetMethod("InitIds", BindingFlags.Public | BindingFlags.Static)!.Invoke(null, null);
        Console.WriteLine(JsonSerializer.Serialize(new { stage = "model_db_initialized" }));
        InstallInMemorySaveManager(assembly);
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "in_memory_save_manager_installed"
        }));
        return assembly;
    }

    private static object CreateStandaloneRunState(
        Assembly assembly,
        string seed)
    {
        var runStateType = assembly.GetType("MegaCrit.Sts2.Core.Runs.RunState", throwOnError: true)!;
        var createForTest = runStateType.GetMethod(
            "CreateForTest",
            BindingFlags.Public | BindingFlags.Static)
            ?? throw new MissingMethodException(runStateType.FullName, "CreateForTest");

        // Reflection does not apply optional parameter defaults. Null selects the
        // game's default player/acts/modifiers; 0 is GameMode.Standard. Supply a
        // seed explicitly so SeedHelper does not consult engine-backed entropy.
        var players = CreateStandalonePlayers(assembly);
        var state = createForTest.Invoke(
                null,
                [players, null, null, 0, 0, seed])
            ?? throw new InvalidOperationException("CreateForTest returned null");
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "test_run_state_created",
            type = state.GetType().FullName,
            seed
        }));
        return state;
    }

    private static object SetupStandaloneManager(
        Assembly assembly,
        object state,
        bool enterCombat)
    {
        var managerType = assembly.GetType(RunManagerTypeName, throwOnError: true)!;
        // Combat and command code consistently resolves RunManager.Instance.
        // Configure that canonical singleton instead of creating a second,
        // split-brain manager that only the host knows about.
        var manager = managerType.GetProperty(
                "Instance", BindingFlags.Public | BindingFlags.Static)
            ?.GetValue(null)
            ?? throw new MissingMemberException(managerType.FullName, "Instance");
        var netService = CreateStandaloneNetService(assembly);
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "standalone_net_service_created"
        }));
        managerType.GetMethod("SetUpTest")!.Invoke(
            manager, [state, netService, true, false]);
        Console.WriteLine(JsonSerializer.Serialize(new { stage = "singleplayer_setup_complete" }));

        var launchedState = managerType.GetMethod("Launch")!.Invoke(manager, null);
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "run_launched",
            same_state = ReferenceEquals(state, launchedState)
        }));
        if (enterCombat)
            EnterTestCombat(assembly, manager);
        return manager;
    }

    private static void WriteObservation(Assembly assembly, object manager)
    {
        SetChecksumTrackingEnabled(manager, true);
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "standalone_observation",
            observation = StandaloneObservationBuilder.Build(
                assembly, manager)
        }));
    }

    private static Array CreateStandalonePlayers(Assembly assembly)
    {
        var playerType = assembly.GetType(
            "MegaCrit.Sts2.Core.Entities.Players.Player",
            throwOnError: true)!;
        var characterType = assembly.GetType(
            "MegaCrit.Sts2.Core.Models.Characters.Ironclad",
            throwOnError: true)!;
        var modelDbType = assembly.GetType(
            "MegaCrit.Sts2.Core.Models.ModelDb", throwOnError: true)!;
        var getModel = modelDbType.GetMethod(
                "Get",
                BindingFlags.NonPublic | BindingFlags.Static,
                binder: null,
                types: [typeof(Type)],
                modifiers: null)
            ?? throw new MissingMethodException(modelDbType.FullName, "Get(Type)");
        var character = getModel.Invoke(null, [characterType])
            ?? throw new InvalidOperationException("Ironclad lookup returned null");
        var unlockStateType = assembly.GetType(
            "MegaCrit.Sts2.Core.Unlocks.UnlockState",
            throwOnError: true)!;
        var allUnlocks = unlockStateType.GetField(
                "all", BindingFlags.Public | BindingFlags.Static)
            ?.GetValue(null)
            ?? throw new MissingFieldException(unlockStateType.FullName, "all");
        var createPlayer = playerType.GetMethods(
                BindingFlags.Public | BindingFlags.Static)
            .Single(method =>
                method.Name == "CreateForNewRun"
                && !method.IsGenericMethod
                && method.GetParameters().Length == 3);
        var player = createPlayer.Invoke(null, [character, allUnlocks, 1UL])
            ?? throw new InvalidOperationException(
                "Player.CreateForNewRun returned null");
        var players = Array.CreateInstance(playerType, 1);
        players.SetValue(player, 0);
        return players;
    }

    private static void EnterTestCombat(Assembly assembly, object manager)
    {
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "test_combat_entry_started"
        }));
        var encounterType = assembly.GetType(
            "MegaCrit.Sts2.Core.Models.Encounters.FuzzyWurmCrawlerWeak",
            throwOnError: true)!;
        var modelDbType = assembly.GetType(
            "MegaCrit.Sts2.Core.Models.ModelDb", throwOnError: true)!;
        var getModel = modelDbType.GetMethod(
                "Get",
                BindingFlags.NonPublic | BindingFlags.Static,
                binder: null,
                types: [typeof(Type)],
                modifiers: null)
            ?? throw new MissingMethodException(modelDbType.FullName, "Get(Type)");
        var canonicalEncounter = getModel.Invoke(null, [encounterType])
            ?? throw new InvalidOperationException("Encounter lookup returned null");
        var encounter = canonicalEncounter.GetType().GetMethod("ToMutable")
            ?.Invoke(canonicalEncounter, null)
            ?? throw new MissingMethodException(
                canonicalEncounter.GetType().FullName, "ToMutable");
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "test_encounter_created",
            encounter = encounterType.FullName
        }));
        var roomType = encounter.GetType().GetProperty("RoomType")?.GetValue(encounter)
            ?? throw new MissingMemberException(
                encounter.GetType().FullName, "RoomType");
        var mapPointType = assembly.GetType(
            "MegaCrit.Sts2.Core.Map.MapPointType", throwOnError: true)!;
        var unassigned = Enum.Parse(mapPointType, "Unassigned");
        var enterRoom = manager.GetType().GetMethod("EnterRoomDebug")
            ?? throw new MissingMethodException(
                manager.GetType().FullName, "EnterRoomDebug");
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "test_combat_enter_room_invoking"
        }));
        var task = enterRoom.Invoke(
                manager, [roomType, unassigned, encounter, false]) as Task
            ?? throw new InvalidOperationException(
                "EnterRoomDebug did not return a Task");
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "test_combat_enter_room_task_created",
            task_status = task.Status.ToString()
        }));
        if (!task.Wait(TimeSpan.FromSeconds(10)))
            throw new TimeoutException("Standalone combat entry exceeded 10 seconds");
        task.GetAwaiter().GetResult();

        var combatManagerType = assembly.GetType(
            "MegaCrit.Sts2.Core.Combat.CombatManager", throwOnError: true)!;
        var combatManager = combatManagerType.GetProperty(
                "Instance", BindingFlags.Public | BindingFlags.Static)
            ?.GetValue(null)
            ?? throw new MissingMemberException(
                combatManagerType.FullName, "Instance");
        var combatState = combatManagerType.GetField(
                "_state", BindingFlags.NonPublic | BindingFlags.Instance)
            ?.GetValue(combatManager)
            ?? throw new MissingFieldException(combatManagerType.FullName, "_state");
        var players = combatState.GetType().GetProperty("Players")?.GetValue(combatState)
            as IEnumerable
            ?? throw new MissingMemberException(combatState.GetType().FullName, "Players");
        var player = players.Cast<object>().Single();
        var playerCombatState = player.GetType().GetProperty("PlayerCombatState")
            ?.GetValue(player)
            ?? throw new MissingMemberException(
                player.GetType().FullName, "PlayerCombatState");
        var phase = playerCombatState.GetType().GetProperty("Phase")
            ?.GetValue(playerCombatState)?.ToString();
        var handCount = GetPileCardCount(playerCombatState, "Hand");
        var drawPileCount = GetPileCardCount(playerCombatState, "DrawPile");
        var enemyCount = CountEnumerable(
            combatState.GetType().GetProperty("Enemies")?.GetValue(combatState));
        if (phase != "Play" || handCount != 5 || enemyCount == 0)
            throw new InvalidOperationException(
                $"Unexpected opening combat state: phase={phase}, " +
                $"hand={handCount}, enemies={enemyCount}");
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "test_combat_entered",
            is_starting = combatManagerType.GetProperty("IsStarting")
                ?.GetValue(combatManager),
            is_in_progress = combatManagerType.GetProperty("IsInProgress")
                ?.GetValue(combatManager),
            phase,
            hand_count = handCount,
            draw_pile_count = drawPileCount,
            enemy_count = enemyCount
        }));
    }

    private static int GetPileCardCount(object playerCombatState, string pileName)
    {
        var pile = playerCombatState.GetType().GetProperty(pileName)
            ?.GetValue(playerCombatState)
            ?? throw new MissingMemberException(
                playerCombatState.GetType().FullName, pileName);
        return CountEnumerable(
            pile.GetType().GetProperty("Cards")?.GetValue(pile));
    }

    private static int CountEnumerable(object? value)
    {
        if (value is not IEnumerable enumerable)
            throw new InvalidOperationException("Expected an enumerable game value");
        return enumerable.Cast<object>().Count();
    }

    private static void RunScriptedActionCycle(Assembly assembly, object manager)
    {
        var context = GetCombatContext(assembly);
        var before = ReadCombatSnapshot(context.Player, context.Enemy);
        SetChecksumTrackingEnabled(manager, true);
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "scripted_action_cycle_started"
        }));
        var checksumBefore = GenerateChecksum(manager, "Standalone before card play");
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "scripted_pre_action_checksum",
            checksum = checksumBefore
        }));

        var hand = GetPileCards(context.PlayerCombatState, "Hand");
        var canPlayTargeting = hand[0].GetType().GetMethod(
                "CanPlayTargeting",
                BindingFlags.Public | BindingFlags.Instance)
            ?? throw new MissingMethodException(
                hand[0].GetType().FullName, "CanPlayTargeting");
        var card = hand.FirstOrDefault(candidate =>
                canPlayTargeting.Invoke(candidate, [context.Enemy]) is true)
            ?? throw new InvalidOperationException(
                "Opening hand contained no playable enemy-targeting card");
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "scripted_card_selected",
            card = GetModelIdEntry(card)
        }));

        var playCardType = assembly.GetType(
            "MegaCrit.Sts2.Core.GameActions.PlayCardAction",
            throwOnError: true)!;
        var playAction = Activator.CreateInstance(
                playCardType, [card, context.Enemy])
            ?? throw new InvalidOperationException("Could not create PlayCardAction");
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "scripted_play_action_created"
        }));
        SubmitAndWait(manager, playAction, "card play");
        var afterPlay = ReadCombatSnapshot(context.Player, context.Enemy);
        if (afterPlay.Energy >= before.Energy
            || afterPlay.HandCount >= before.HandCount
            || afterPlay.EnemyHp >= before.EnemyHp)
        {
            throw new InvalidOperationException(
                "Card play did not consume energy/card and damage the enemy");
        }
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "scripted_card_play_complete",
            card = GetModelIdEntry(card),
            energy_before = before.Energy,
            energy_after = afterPlay.Energy,
            hand_before = before.HandCount,
            hand_after = afterPlay.HandCount,
            enemy_hp_before = before.EnemyHp,
            enemy_hp_after = afterPlay.EnemyHp
        }));

        var endTurnType = assembly.GetType(
            "MegaCrit.Sts2.Core.GameActions.EndPlayerTurnAction",
            throwOnError: true)!;
        var endTurnAction = Activator.CreateInstance(
                endTurnType, [context.Player, afterPlay.TurnNumber])
            ?? throw new InvalidOperationException(
                "Could not create EndPlayerTurnAction");
        SubmitAndWait(manager, endTurnAction, "end turn");
        WaitForNextPlayPhase(context.PlayerCombatState, afterPlay.TurnNumber);

        var afterTurn = ReadCombatSnapshot(context.Player, context.Enemy);
        var checksumAfter = GenerateChecksum(manager, "Standalone after turn cycle");
        if (afterTurn.Phase != "Play"
            || afterTurn.TurnNumber <= afterPlay.TurnNumber
            || afterTurn.HandCount == 0
            || checksumAfter == checksumBefore)
        {
            throw new InvalidOperationException(
                "End turn did not reach a changed, player-ready combat state");
        }
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "scripted_action_cycle_complete",
            phase = afterTurn.Phase,
            turn_before = afterPlay.TurnNumber,
            turn_after = afterTurn.TurnNumber,
            player_hp_before = before.PlayerHp,
            player_hp_after = afterTurn.PlayerHp,
            enemy_hp_after = afterTurn.EnemyHp,
            hand_count = afterTurn.HandCount,
            energy = afterTurn.Energy,
            checksum_before = checksumBefore,
            checksum_after = checksumAfter
        }));
    }

    private static (
        object Player,
        object PlayerCombatState,
        object Enemy) GetCombatContext(Assembly assembly)
    {
        var combatManagerType = assembly.GetType(
            "MegaCrit.Sts2.Core.Combat.CombatManager", throwOnError: true)!;
        var combatManager = combatManagerType.GetProperty(
                "Instance", BindingFlags.Public | BindingFlags.Static)
            ?.GetValue(null)
            ?? throw new MissingMemberException(
                combatManagerType.FullName, "Instance");
        var combatState = combatManagerType.GetField(
                "_state", BindingFlags.NonPublic | BindingFlags.Instance)
            ?.GetValue(combatManager)
            ?? throw new MissingFieldException(combatManagerType.FullName, "_state");
        var player = ((IEnumerable)(combatState.GetType().GetProperty("Players")
                ?.GetValue(combatState)
            ?? throw new MissingMemberException(
                combatState.GetType().FullName, "Players")))
            .Cast<object>().Single();
        var playerCombatState = player.GetType().GetProperty("PlayerCombatState")
            ?.GetValue(player)
            ?? throw new MissingMemberException(
                player.GetType().FullName, "PlayerCombatState");
        var enemy = ((IEnumerable)(combatState.GetType().GetProperty("Enemies")
                ?.GetValue(combatState)
            ?? throw new MissingMemberException(
                combatState.GetType().FullName, "Enemies")))
            .Cast<object>().Single();
        return (player, playerCombatState, enemy);
    }

    private static List<object> GetPileCards(
        object playerCombatState,
        string pileName)
    {
        var pile = playerCombatState.GetType().GetProperty(pileName)
            ?.GetValue(playerCombatState)
            ?? throw new MissingMemberException(
                playerCombatState.GetType().FullName, pileName);
        return ((IEnumerable)(pile.GetType().GetProperty("Cards")?.GetValue(pile)
                ?? throw new MissingMemberException(
                    pile.GetType().FullName, "Cards")))
            .Cast<object>().ToList();
    }

    private static CombatSnapshot ReadCombatSnapshot(object player, object enemy)
    {
        var playerCombatState = player.GetType().GetProperty("PlayerCombatState")
            ?.GetValue(player)
            ?? throw new MissingMemberException(
                player.GetType().FullName, "PlayerCombatState");
        var playerCreature = player.GetType().GetProperty("Creature")
            ?.GetValue(player)
            ?? throw new MissingMemberException(player.GetType().FullName, "Creature");
        return new CombatSnapshot(
            Phase: playerCombatState.GetType().GetProperty("Phase")
                ?.GetValue(playerCombatState)?.ToString()
                ?? "Unknown",
            TurnNumber: Convert.ToInt32(
                playerCombatState.GetType().GetProperty("TurnNumber")
                    ?.GetValue(playerCombatState)),
            Energy: Convert.ToInt32(
                playerCombatState.GetType().GetProperty("Energy")
                    ?.GetValue(playerCombatState)),
            HandCount: GetPileCards(playerCombatState, "Hand").Count,
            PlayerHp: ReadIntProperty(playerCreature, "CurrentHp"),
            EnemyHp: ReadIntProperty(enemy, "CurrentHp"));
    }

    private static int ReadIntProperty(object value, string propertyName) =>
        Convert.ToInt32(value.GetType().GetProperty(propertyName)
            ?.GetValue(value));

    private static string GetModelIdEntry(object model)
    {
        var id = model.GetType().GetProperty("Id")?.GetValue(model)
            ?? throw new MissingMemberException(model.GetType().FullName, "Id");
        return id.GetType().GetProperty("Entry")?.GetValue(id)?.ToString()
            ?? id.ToString() ?? "unknown";
    }

    private static void SubmitAndWait(
        object manager,
        object action,
        string description)
    {
        var synchronizer = manager.GetType().GetProperty("ActionQueueSynchronizer")
            ?.GetValue(manager)
            ?? throw new MissingMemberException(
                manager.GetType().FullName, "ActionQueueSynchronizer");
        synchronizer.GetType().GetMethod("RequestEnqueue")
            ?.Invoke(synchronizer, [action]);
        var completion = action.GetType().GetProperty("CompletionTask")
            ?.GetValue(action) as Task
            ?? throw new MissingMemberException(
                action.GetType().FullName, "CompletionTask");
        if (!completion.Wait(TimeSpan.FromSeconds(10)))
            throw new TimeoutException($"{description} exceeded 10 seconds");
        completion.GetAwaiter().GetResult();
    }

    private static void WaitForNextPlayPhase(
        object playerCombatState,
        int priorTurn)
    {
        var deadline = DateTime.UtcNow + TimeSpan.FromSeconds(10);
        while (DateTime.UtcNow < deadline)
        {
            var phase = playerCombatState.GetType().GetProperty("Phase")
                ?.GetValue(playerCombatState)?.ToString();
            var turn = Convert.ToInt32(
                playerCombatState.GetType().GetProperty("TurnNumber")
                    ?.GetValue(playerCombatState));
            if (phase == "Play" && turn > priorTurn)
                return;
            Thread.Sleep(1);
        }
        throw new TimeoutException(
            "Combat did not reach the next player play phase in 10 seconds");
    }

    private static uint GenerateChecksum(object manager, string reason)
    {
        var tracker = manager.GetType().GetProperty("ChecksumTracker")
            ?.GetValue(manager)
            ?? throw new MissingMemberException(
                manager.GetType().FullName, "ChecksumTracker");
        var generate = tracker.GetType().GetMethods()
            .Single(method =>
                method.Name == "GenerateChecksum"
                && method.GetParameters().Length == 2);
        var data = generate.Invoke(tracker, [reason, null])
            ?? throw new InvalidOperationException(
                "GenerateChecksum returned null");
        return Convert.ToUInt32(data.GetType().GetField("checksum")
            ?.GetValue(data));
    }

    private static void SetChecksumTrackingEnabled(object manager, bool enabled)
    {
        var tracker = manager.GetType().GetProperty("ChecksumTracker")
            ?.GetValue(manager)
            ?? throw new MissingMemberException(
                manager.GetType().FullName, "ChecksumTracker");
        tracker.GetType().GetProperty("IsEnabled")
            ?.SetValue(tracker, enabled);
    }

    private sealed record CombatSnapshot(
        string Phase,
        int TurnNumber,
        int Energy,
        int HandCount,
        int PlayerHp,
        int EnemyHp);

    private static object CreateStandaloneNetService(Assembly assembly)
    {
        var serviceInterface = assembly.GetType(
            "MegaCrit.Sts2.Core.Multiplayer.Game.INetGameService",
            throwOnError: true)!;
        var createProxy = typeof(DispatchProxy).GetMethods()
            .Single(method =>
                method.Name == nameof(DispatchProxy.Create)
                && method.IsGenericMethodDefinition
                && method.GetGenericArguments().Length == 2
                && method.GetParameters().Length == 0);
        return createProxy
            .MakeGenericMethod(
                serviceInterface, typeof(StandaloneNetGameServiceProxy))
            .Invoke(null, null)
            ?? throw new InvalidOperationException(
                "Could not create INetGameService proxy");
    }

    private static void EnableGameTestMode(Assembly assembly)
    {
        var testModeType = assembly.GetType(
            "MegaCrit.Sts2.Core.TestSupport.TestMode", throwOnError: true)!;
        testModeType.GetMethod(
                "TurnOnInternal", BindingFlags.Public | BindingFlags.Static)
            ?.Invoke(null, null);
    }

    private static void InstallInMemorySaveManager(Assembly assembly)
    {
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "save_manager_host_start"
        }));
        var managerType = assembly.GetType(
            "MegaCrit.Sts2.Core.Saves.SaveManager", throwOnError: true)!;
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "save_manager_types_loaded"
        }));

        // SaveManager's public test constructor initializes every persistence
        // subsystem, including Godot/Sentry-adjacent paths we do not need just
        // to construct a Player. Install the narrow object graph read by the
        // Player constructor: SaveManager -> ProgressSaveManager -> Progress.
        var progressManagerType = assembly.GetType(
            "MegaCrit.Sts2.Core.Saves.Managers.ProgressSaveManager",
            throwOnError: true)!;
        var progressType = assembly.GetType(
            "MegaCrit.Sts2.Core.Saves.ProgressState", throwOnError: true)!;
        var progress = progressType.GetMethod(
                "CreateDefault", BindingFlags.Public | BindingFlags.Static)
            ?.Invoke(null, null)
            ?? throw new MissingMethodException(progressType.FullName, "CreateDefault");
        // A fresh profile normally opens tutorial UI during the first combat.
        // Standalone simulation has no scene tree, so use the game's supported
        // profile setting to mark FTUE presentation disabled. This affects only
        // tutorial overlays, not run or combat mechanics.
        progressType.GetProperty(
                "EnableFtues", BindingFlags.Public | BindingFlags.Instance)
            ?.SetValue(progress, false);
        var progressManager = RuntimeHelpers.GetUninitializedObject(progressManagerType);
        progressManagerType.GetField(
                "<Progress>k__BackingField",
                BindingFlags.NonPublic | BindingFlags.Instance)
            ?.SetValue(progressManager, progress);
        var manager = RuntimeHelpers.GetUninitializedObject(managerType);
        managerType.GetField(
                "_progressSaveManager",
                BindingFlags.NonPublic | BindingFlags.Instance)
            ?.SetValue(manager, progressManager);
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "save_manager_constructed"
        }));
        managerType.GetMethod(
                "MockInstanceForTesting", BindingFlags.Public | BindingFlags.Static)
            ?.Invoke(null, [manager]);
    }

    private static void MarkModLoadingSkipped(Assembly assembly)
    {
        // ModelDb.Init includes model types contributed by mods. A standalone
        // training process intentionally loads none, but ReflectionHelper still
        // requires ModManager to have reached a terminal initialization state.
        var managerType = assembly.GetType(
            "MegaCrit.Sts2.Core.Modding.ModManager", throwOnError: true)!;
        var stateType = assembly.GetType(
            "MegaCrit.Sts2.Core.Modding.ModManagerState", throwOnError: true)!;
        var skipped = Enum.Parse(stateType, "Skipped");
        var stateField = managerType.GetField(
            "<State>k__BackingField", BindingFlags.NonPublic | BindingFlags.Static)
            ?? throw new MissingFieldException(managerType.FullName, "<State>k__BackingField");
        stateField.SetValue(null, skipped);
    }

    private static int Inspect(GameAssemblyHost host, string? requestedTypeName)
    {
        if (string.IsNullOrWhiteSpace(requestedTypeName))
            throw new ArgumentException("inspect requires --type <full-or-partial-name>");

        var assembly = host.LoadGameAssembly();
        var matches = assembly.GetTypes()
            .Where(t =>
                t.FullName?.Contains(requestedTypeName, StringComparison.OrdinalIgnoreCase) == true)
            .OrderBy(t => t.FullName)
            .ToArray();
        foreach (var type in matches)
        {
            Console.WriteLine($"TYPE {type.FullName} : {type.BaseType?.FullName}");
            foreach (var constructor in type.GetConstructors(
                         BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
                Console.WriteLine($"  CTOR {constructor}");
            foreach (var property in type.GetProperties(
                         BindingFlags.Public | BindingFlags.NonPublic |
                         BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
                Console.WriteLine($"  PROPERTY {property.PropertyType.FullName} {property.Name} " +
                                  $"get={property.GetMethod?.IsPublic} set={property.SetMethod?.IsPublic}");
            foreach (var method in type.GetMethods(
                         BindingFlags.Public | BindingFlags.NonPublic |
                         BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)
                         .Where(m => !m.IsSpecialName)
                         .OrderBy(m => m.Name))
                Console.WriteLine($"  METHOD {method}");
        }
        return matches.Length == 0 ? 3 : 0;
    }

    private static int Probe(GameAssemblyHost host)
    {
        var assembly = host.LoadGameAssembly();
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "assembly_loaded",
            assembly = assembly.FullName,
            location = assembly.Location
        }));

        Type[] types;
        try
        {
            types = assembly.GetTypes();
        }
        catch (ReflectionTypeLoadException exception)
        {
            foreach (var loaderException in exception.LoaderExceptions.Where(e => e is not null))
                Console.Error.WriteLine(loaderException);
            types = exception.Types.Where(t => t is not null).Cast<Type>().ToArray();
            Console.WriteLine(JsonSerializer.Serialize(new
            {
                stage = "types_partially_loaded",
                loaded = types.Length,
                failed = exception.Types.Length - types.Length
            }));
        }

        var runManagerType = types.FirstOrDefault(t => t.FullName == RunManagerTypeName)
            ?? throw new TypeLoadException($"{RunManagerTypeName} was not found in sts2.dll");
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "run_manager_found",
            type = runManagerType.FullName,
            base_type = runManagerType.BaseType?.FullName,
            constructors = runManagerType
                .GetConstructors(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)
                .Select(c => c.ToString())
        }));

        try
        {
            var instance = Activator.CreateInstance(runManagerType, nonPublic: true);
            Console.WriteLine(JsonSerializer.Serialize(new
            {
                stage = "run_manager_constructed",
                type = instance?.GetType().FullName
            }));
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine("RunManager construction failed:");
            Console.Error.WriteLine(exception);
            Console.WriteLine(JsonSerializer.Serialize(new
            {
                stage = "run_manager_construction_failed",
                error_type = exception.GetBaseException().GetType().FullName,
                error = exception.GetBaseException().Message
            }));
            return 2;
        }
    }

    private static int Stdio(GameAssemblyHost host)
    {
        var assembly = InitializeStandaloneAssembly(host);
        object? manager = null;
        string? activeSeed = null;
        string? line;
        while ((line = Console.ReadLine()) is not null)
        {
            JsonElement? requestId = null;
            try
            {
                using var command = JsonDocument.Parse(line);
                var name = command.RootElement.GetProperty("cmd").GetString();
                requestId = command.RootElement.TryGetProperty(
                    "request_id", out var requestIdElement)
                    ? requestIdElement.Clone()
                    : default(JsonElement?);
                object response;
                switch (name)
                {
                    case "health":
                        response = new
                        {
                            ok = true,
                            request_id = requestId,
                            assembly = assembly.GetName().Name,
                            ready = manager is not null,
                            seed = activeSeed,
                            schema = StandaloneObservationBuilder.Schema
                        };
                        break;
                    case "reset":
                    {
                        var seed = command.RootElement.TryGetProperty(
                                "seed", out var seedElement)
                            ? seedElement.GetString()
                            : null;
                        seed = string.IsNullOrWhiteSpace(seed)
                            ? "HEADLESSBENCH"
                            : seed;
                        if (manager is not null)
                        {
                            manager.GetType().GetMethod("CleanUp")
                                ?.Invoke(manager, [true]);
                        }
                        var state = CreateStandaloneRunState(assembly, seed);
                        manager = SetupStandaloneManager(
                            assembly, state, enterCombat: true);
                        SetChecksumTrackingEnabled(manager, true);
                        activeSeed = seed;
                        response = new
                        {
                            ok = true,
                            request_id = requestId,
                            seed = activeSeed,
                            observation = StandaloneObservationBuilder.Build(
                                assembly, manager)
                        };
                        break;
                    }
                    case "observe":
                        RequireManager(manager);
                        response = new
                        {
                            ok = true,
                            request_id = requestId,
                            seed = activeSeed,
                            observation = StandaloneObservationBuilder.Build(
                                assembly, manager!)
                        };
                        break;
                    case "step":
                        RequireManager(manager);
                        ExecuteStdioStep(
                            assembly, manager!, command.RootElement);
                        response = new
                        {
                            ok = true,
                            request_id = requestId,
                            seed = activeSeed,
                            observation = StandaloneObservationBuilder.Build(
                                assembly, manager!)
                        };
                        break;
                    case "shutdown":
                        response = new
                        {
                            ok = true,
                            request_id = requestId
                        };
                        break;
                    default:
                        response = new
                        {
                            error = $"Unsupported command: {name}",
                            request_id = requestId
                        };
                        break;
                }
                Console.WriteLine(JsonSerializer.Serialize(response));
                if (name == "shutdown")
                    break;
            }
            catch (Exception exception)
            {
                Console.WriteLine(JsonSerializer.Serialize(new
                {
                    error = exception.Message,
                    error_type = exception.GetType().FullName,
                    request_id = requestId
                }));
            }
        }
        return 0;
    }

    private static void ExecuteStdioStep(
        Assembly assembly,
        object manager,
        JsonElement command)
    {
        var requestedAction = command.GetProperty("action").GetString()
            ?? throw new ArgumentException("step requires action");
        var observation = StandaloneObservationBuilder.Build(assembly, manager);
        var legalActions = (IEnumerable<Dictionary<string, object?>>)
            observation["legal_actions"]!;

        if (requestedAction == "play_card")
        {
            var cardIndex = command.GetProperty("card_index").GetInt32();
            ulong? targetId = null;
            if (command.TryGetProperty(
                    "target_combat_id", out var targetElement)
                && targetElement.ValueKind != JsonValueKind.Null)
            {
                targetId = targetElement.GetUInt64();
            }
            var isLegal = legalActions.Any(action =>
                Equals(action["action"], "play_card")
                && Convert.ToInt32(action["card_index"]) == cardIndex
                && NullableUnsignedEquals(
                    action["target_combat_id"], targetId));
            if (!isLegal)
                throw new InvalidOperationException(
                    "Requested card/target pair is not a legal action");

            var context = GetCombatContext(assembly);
            var hand = GetPileCards(context.PlayerCombatState, "Hand");
            var card = hand[cardIndex];
            object? target = null;
            if (targetId.HasValue)
            {
                target = GetCombatEnemies(assembly).Single(enemy =>
                    Convert.ToUInt64(enemy.GetType().GetProperty("CombatId")
                        ?.GetValue(enemy)) == targetId.Value);
            }
            var actionType = assembly.GetType(
                "MegaCrit.Sts2.Core.GameActions.PlayCardAction",
                throwOnError: true)!;
            var action = Activator.CreateInstance(actionType, [card, target])
                ?? throw new InvalidOperationException(
                    "Could not create PlayCardAction");
            SubmitAndWait(manager, action, "card play");
            return;
        }

        if (requestedAction == "end_turn")
        {
            if (!legalActions.Any(action =>
                    Equals(action["action"], "end_turn")))
                throw new InvalidOperationException(
                    "End turn is not legal at this decision point");
            var context = GetCombatContext(assembly);
            var priorTurn = ReadIntProperty(
                context.PlayerCombatState, "TurnNumber");
            var actionType = assembly.GetType(
                "MegaCrit.Sts2.Core.GameActions.EndPlayerTurnAction",
                throwOnError: true)!;
            var action = Activator.CreateInstance(
                    actionType, [context.Player, priorTurn])
                ?? throw new InvalidOperationException(
                    "Could not create EndPlayerTurnAction");
            SubmitAndWait(manager, action, "end turn");
            WaitForNextPlayPhase(context.PlayerCombatState, priorTurn);
            return;
        }

        throw new InvalidOperationException(
            $"Unsupported step action: {requestedAction}");
    }

    private static List<object> GetCombatEnemies(Assembly assembly)
    {
        var combatManagerType = assembly.GetType(
            "MegaCrit.Sts2.Core.Combat.CombatManager", throwOnError: true)!;
        var combatManager = combatManagerType.GetProperty(
                "Instance", BindingFlags.Public | BindingFlags.Static)
            ?.GetValue(null)
            ?? throw new MissingMemberException(
                combatManagerType.FullName, "Instance");
        var combatState = combatManagerType.GetField(
                "_state", BindingFlags.NonPublic | BindingFlags.Instance)
            ?.GetValue(combatManager)
            ?? throw new MissingFieldException(combatManagerType.FullName, "_state");
        return ((IEnumerable)(combatState.GetType().GetProperty("Enemies")
                ?.GetValue(combatState)
            ?? throw new MissingMemberException(
                combatState.GetType().FullName, "Enemies")))
            .Cast<object>().ToList();
    }

    private static bool NullableUnsignedEquals(
        object? observed,
        ulong? requested)
    {
        if (observed is null)
            return requested is null;
        return requested.HasValue
            && Convert.ToUInt64(observed) == requested.Value;
    }

    private static void RequireManager(object? manager)
    {
        if (manager is null)
            throw new InvalidOperationException(
                "No active episode. Send reset first.");
    }
}

internal sealed record Options(string Command, string GameDataDirectory, string? TypeName)
{
    public static Options Parse(string[] args)
    {
        var command = args.FirstOrDefault(a => !a.StartsWith("--", StringComparison.Ordinal)) ?? "probe";
        var gameDataDirectory = GetOption(args, "--game-data-dir")
            ?? Environment.GetEnvironmentVariable("STS2_GAME_DATA_DIR")
            ?? throw new ArgumentException(
                "Set STS2_GAME_DATA_DIR or pass --game-data-dir <path>.");
        gameDataDirectory = Path.GetFullPath(gameDataDirectory);
        if (!Directory.Exists(gameDataDirectory))
            throw new DirectoryNotFoundException(gameDataDirectory);
        return new Options(command, gameDataDirectory, GetOption(args, "--type"));
    }

    private static string? GetOption(string[] args, string option)
    {
        var index = Array.IndexOf(args, option);
        return index >= 0 && index + 1 < args.Length ? args[index + 1] : null;
    }
}
