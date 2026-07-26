using System.Reflection;

namespace STS2Headless;

/// <summary>
/// No-op INetGameService used by RunManager.SetUpTest. It keeps standalone
/// startup from loading the Steam-aware singleplayer service.
/// </summary>
internal class StandaloneNetGameServiceProxy : DispatchProxy
{
    protected override object? Invoke(MethodInfo? targetMethod, object?[]? args)
    {
        if (targetMethod is null)
            throw new ArgumentNullException(nameof(targetMethod));
        return targetMethod.Name switch
        {
            "get_IsConnected" => true,
            "get_IsGameLoading" => false,
            "get_NetId" => 1UL,
            "get_Type" => Enum.Parse(targetMethod.ReturnType, "Singleplayer"),
            "get_Platform" => Enum.ToObject(targetMethod.ReturnType, 0),
            "GetRawLobbyIdentifier" => null,
            _ => DefaultValue(targetMethod.ReturnType)
        };
    }

    private static object? DefaultValue(Type type)
    {
        if (type == typeof(void))
            return null;
        if (type == typeof(Task))
            return Task.CompletedTask;
        if (type.IsGenericType && type.GetGenericTypeDefinition() == typeof(Task<>))
        {
            var resultType = type.GetGenericArguments()[0];
            var value = resultType.IsValueType
                ? Activator.CreateInstance(resultType)
                : null;
            return typeof(Task).GetMethod(nameof(Task.FromResult))!
                .MakeGenericMethod(resultType)
                .Invoke(null, [value]);
        }
        return type.IsValueType ? Activator.CreateInstance(type) : null;
    }
}
