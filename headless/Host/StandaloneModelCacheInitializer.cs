using System.Collections;
using System.Reflection;
using System.Text;

namespace STS2Headless;

/// <summary>
/// Initializes ModelIdSerializationCache without touching Godot.Mathf or the
/// game's Godot-backed logger. This mirrors the unmodded, no-mod branch of the
/// game's initializer and deliberately fails closed when its private shape
/// changes.
/// </summary>
internal static class StandaloneModelCacheInitializer
{
    private const string CacheTypeName =
        "MegaCrit.Sts2.Core.Multiplayer.Serialization.ModelIdSerializationCache";
    private const string ModelDbTypeName = "MegaCrit.Sts2.Core.Models.ModelDb";
    private const string ModelSubtypeTypeName =
        "MegaCrit.Sts2.Core.Models.AbstractModelSubtypes";
    private const string EpochModelTypeName =
        "MegaCrit.Sts2.Core.Timeline.EpochModel";

    public static ModelCacheSummary Initialize(Assembly assembly)
    {
        var cacheType = RequiredType(assembly, CacheTypeName);
        var modelDbType = RequiredType(assembly, ModelDbTypeName);
        var subtypeType = RequiredType(assembly, ModelSubtypeTypeName);
        var epochType = RequiredType(assembly, EpochModelTypeName);

        var categoryToId = RequiredDictionary(cacheType, "_categoryNameToNetIdMap");
        var categories = RequiredList(cacheType, "_netIdToCategoryNameMap");
        var entryToId = RequiredDictionary(cacheType, "_entryNameToNetIdMap");
        var entries = RequiredList(cacheType, "_netIdToEntryNameMap");
        var epochToId = RequiredDictionary(cacheType, "_epochNameToNetIdMap");
        var epochs = RequiredList(cacheType, "_netIdToEpochNameMap");

        // The cache's static constructor supplies the NONE sentinel. Refuse to
        // run twice because duplicate entries would silently produce a bad hash.
        if (categories.Count != 1 || entries.Count != 1 || epochs.Count != 0)
        {
            throw new InvalidOperationException(
                "Model cache was already initialized or has an unexpected initial shape");
        }

        var allModels = subtypeType.GetProperty(
                "All", BindingFlags.Public | BindingFlags.Static)
            ?.GetValue(null) as IEnumerable
            ?? throw new MissingMemberException(ModelSubtypeTypeName, "All");
        var modelTypes = allModels.Cast<Type>().ToList();
        // Match List<T>.Sort from the game exactly. Two built-in model types
        // share a simple name; stable LINQ ordering produces a different cache
        // hash even though the unique entry/category counts are identical.
        modelTypes.Sort(
            (left, right) => string.CompareOrdinal(left.Name, right.Name));
        var getId = modelDbType.GetMethod(
                "GetId",
                BindingFlags.Public | BindingFlags.Static,
                binder: null,
                types: [typeof(Type)],
                modifiers: null)
            ?? throw new MissingMethodException(ModelDbTypeName, "GetId(Type)");

        var hash = new RuntimeXxHash32();
        foreach (var modelType in modelTypes)
        {
            var id = getId.Invoke(null, [modelType])
                ?? throw new InvalidOperationException($"No ModelId for {modelType}");
            var idType = id.GetType();
            var category = idType.GetProperty("Category")?.GetValue(id) as string
                ?? throw new MissingMemberException(idType.FullName, "Category");
            var entry = idType.GetProperty("Entry")?.GetValue(id) as string
                ?? throw new MissingMemberException(idType.FullName, "Entry");
            AddUnique(categoryToId, categories, category);
            AddUnique(entryToId, entries, entry);
            hash.AppendUtf8(category);
            hash.AppendUtf8(entry);
        }

        var allEpochIds = epochType.GetProperty(
                "AllEpochIds", BindingFlags.Public | BindingFlags.Static)
            ?.GetValue(null) as IEnumerable
            ?? throw new MissingMemberException(EpochModelTypeName, "AllEpochIds");
        foreach (var value in allEpochIds)
        {
            var epoch = value as string
                ?? throw new InvalidOperationException("Epoch ID was not a string");
            AddUnique(epochToId, epochs, epoch);
            hash.AppendUtf8(epoch);
        }

        hash.AppendInt32LittleEndian(categories.Count);
        hash.AppendInt32LittleEndian(entries.Count);
        hash.AppendInt32LittleEndian(epochs.Count);
        var hashValue = hash.GetCurrentHashAsUInt32();

        SetAutoProperty(cacheType, "CategoryIdBitSize", BitsForCount(categories.Count));
        SetAutoProperty(cacheType, "EntryIdBitSize", BitsForCount(entries.Count));
        SetAutoProperty(cacheType, "EpochIdBitSize", BitsForCount(epochs.Count));
        SetAutoProperty(cacheType, "Hash", hashValue);
        return new ModelCacheSummary(
            modelTypes.Count,
            categories.Count,
            entries.Count,
            epochs.Count,
            hashValue);
    }

    private static Type RequiredType(Assembly assembly, string name) =>
        assembly.GetType(name, throwOnError: true)!;

    private static IDictionary RequiredDictionary(Type type, string name) =>
        type.GetField(name, BindingFlags.NonPublic | BindingFlags.Static)
            ?.GetValue(null) as IDictionary
        ?? throw new MissingFieldException(type.FullName, name);

    private static IList RequiredList(Type type, string name) =>
        type.GetField(name, BindingFlags.NonPublic | BindingFlags.Static)
            ?.GetValue(null) as IList
        ?? throw new MissingFieldException(type.FullName, name);

    private static void AddUnique(IDictionary map, IList values, string value)
    {
        if (map.Contains(value))
            return;
        map.Add(value, values.Count);
        values.Add(value);
    }

    private static void SetAutoProperty(Type type, string property, object value)
    {
        var field = type.GetField(
                $"<{property}>k__BackingField",
                BindingFlags.NonPublic | BindingFlags.Static)
            ?? throw new MissingFieldException(type.FullName, property);
        field.SetValue(null, value);
    }

    private static int BitsForCount(int count) =>
        count <= 1 ? 0 : (int)Math.Ceiling(Math.Log2(count));

}

internal sealed record ModelCacheSummary(
    int ModelTypes,
    int Categories,
    int Entries,
    int Epochs,
    uint Hash);

internal sealed class RuntimeXxHash32
{
    private readonly object _instance;
    private readonly MethodInfo _append;
    private readonly MethodInfo _getCurrentHash;

    public RuntimeXxHash32()
    {
        var type = Type.GetType(
                "System.IO.Hashing.XxHash32, System.IO.Hashing",
                throwOnError: true)!
            ?? throw new TypeLoadException("System.IO.Hashing.XxHash32");
        _instance = Activator.CreateInstance(type)
            ?? throw new InvalidOperationException("Could not construct XxHash32");
        _append = type.GetMethod("Append", [typeof(byte[])])
            ?? throw new MissingMethodException(type.FullName, "Append(byte[])");
        _getCurrentHash = type.GetMethod("GetCurrentHashAsUInt32", Type.EmptyTypes)
            ?? throw new MissingMethodException(
                type.FullName, "GetCurrentHashAsUInt32()");
    }

    public void AppendUtf8(string value) =>
        _append.Invoke(_instance, [Encoding.UTF8.GetBytes(value)]);

    public void AppendInt32LittleEndian(int value) =>
        _append.Invoke(_instance,
        [
            new byte[]
            {
                (byte)value,
                (byte)(value >> 8),
                (byte)(value >> 16),
                (byte)(value >> 24)
            }
        ]);

    public uint GetCurrentHashAsUInt32() =>
        (uint)(_getCurrentHash.Invoke(_instance, null)
            ?? throw new InvalidOperationException("XxHash32 returned null"));
}
