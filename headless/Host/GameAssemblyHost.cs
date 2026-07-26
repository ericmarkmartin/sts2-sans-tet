using System.Reflection;
using System.Runtime.Loader;

namespace STS2Headless;

internal sealed class GameAssemblyHost : IDisposable
{
    private readonly string _gameDataDirectory;

    public GameAssemblyHost(string gameDataDirectory)
    {
        _gameDataDirectory = gameDataDirectory;
        AssemblyLoadContext.Default.Resolving += Resolve;
    }

    public Assembly LoadGameAssembly()
    {
        var path = Path.Combine(_gameDataDirectory, "sts2.dll");
        if (!File.Exists(path))
            throw new FileNotFoundException("sts2.dll was not found", path);
        return AssemblyLoadContext.Default.LoadFromAssemblyPath(path);
    }

    private Assembly? Resolve(AssemblyLoadContext context, AssemblyName assemblyName)
    {
        var path = Path.Combine(_gameDataDirectory, $"{assemblyName.Name}.dll");
        if (!File.Exists(path))
            return null;
        Console.Error.WriteLine($"Resolving {assemblyName} from {path}");
        return context.LoadFromAssemblyPath(path);
    }

    public void Dispose() => AssemblyLoadContext.Default.Resolving -= Resolve;
}
