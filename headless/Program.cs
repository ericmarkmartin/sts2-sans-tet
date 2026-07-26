using System.Reflection;
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
                "phase-b-startup" => PhaseBStartup(host),
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

    private static int PhaseBStartup(GameAssemblyHost host)
    {
        var assembly = host.LoadGameAssembly();
        MarkModLoadingSkipped(assembly);
        var modelDbType = assembly.GetType("MegaCrit.Sts2.Core.Models.ModelDb", throwOnError: true)!;
        modelDbType.GetMethod("Init", BindingFlags.Public | BindingFlags.Static)!.Invoke(null, null);
        var modelIdCacheType = assembly.GetType(
            "MegaCrit.Sts2.Core.Multiplayer.Serialization.ModelIdSerializationCache",
            throwOnError: true)!;
        modelIdCacheType.GetMethod("Init", BindingFlags.Public | BindingFlags.Static)!.Invoke(null, null);
        modelDbType.GetMethod("InitIds", BindingFlags.Public | BindingFlags.Static)!.Invoke(null, null);
        Console.WriteLine(JsonSerializer.Serialize(new { stage = "model_db_initialized" }));

        var runStateType = assembly.GetType("MegaCrit.Sts2.Core.Runs.RunState", throwOnError: true)!;
        var createForTest = runStateType.GetMethod(
            "CreateForTest",
            BindingFlags.Public | BindingFlags.Static)
            ?? throw new MissingMethodException(runStateType.FullName, "CreateForTest");

        // Reflection does not apply optional parameter defaults. Null selects the
        // game's default player/acts/modifiers and seed; 0 is GameMode.Standard.
        var state = createForTest.Invoke(null, [null, null, null, 0, 0, null])
            ?? throw new InvalidOperationException("CreateForTest returned null");
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "test_run_state_created",
            type = state.GetType().FullName
        }));

        var managerType = assembly.GetType(RunManagerTypeName, throwOnError: true)!;
        var manager = Activator.CreateInstance(managerType, nonPublic: true)!;
        managerType.GetMethod("SetUpNewSingleplayer")!.Invoke(
            manager, [state, false, null]);
        Console.WriteLine(JsonSerializer.Serialize(new { stage = "singleplayer_setup_complete" }));

        var launchedState = managerType.GetMethod("Launch")!.Invoke(manager, null);
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            stage = "run_launched",
            same_state = ReferenceEquals(state, launchedState)
        }));
        return 0;
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
        var assembly = host.LoadGameAssembly();
        string? line;
        while ((line = Console.ReadLine()) is not null)
        {
            try
            {
                using var command = JsonDocument.Parse(line);
                var name = command.RootElement.GetProperty("cmd").GetString();
                object response = name switch
                {
                    "health" => new { ok = true, assembly = assembly.GetName().Name },
                    "shutdown" => new { ok = true },
                    _ => new { error = $"Unsupported command: {name}" }
                };
                Console.WriteLine(JsonSerializer.Serialize(response));
                if (name == "shutdown")
                    break;
            }
            catch (Exception exception)
            {
                Console.WriteLine(JsonSerializer.Serialize(new
                {
                    error = exception.Message,
                    error_type = exception.GetType().FullName
                }));
            }
        }
        return 0;
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
