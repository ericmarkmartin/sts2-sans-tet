using System;
using System.IO;

namespace RLBridge;

public static class RLLog
{
    private const string Prefix = "[RLBridge] ";
    private static readonly string LogPath;
    private static readonly object Lock = new();

    static RLLog()
    {
        // Write to a file next to the game exe, or temp
        try
        {
            var dir = AppDomain.CurrentDomain.BaseDirectory;
            LogPath = Path.Combine(dir, "rl_bridge.log");
            // Clear on startup
            File.WriteAllText(LogPath, $"=== RL Bridge Log Started {DateTime.Now} ===\n");
        }
        catch
        {
            LogPath = Path.Combine(Path.GetTempPath(), "rl_bridge.log");
            File.WriteAllText(LogPath, $"=== RL Bridge Log Started {DateTime.Now} ===\n");
        }
    }

    private static void Write(string line)
    {
        var msg = $"[{DateTime.Now:HH:mm:ss.fff}] {line}";
        Console.WriteLine(Prefix + line);
        lock (Lock)
        {
            try { File.AppendAllText(LogPath, msg + "\n"); } catch { }
        }
    }

    public static void Info(string message) => Write(message);
    public static void Warn(string message) => Write("WARN: " + message);
    public static void Error(string message) => Write("ERROR: " + message);
    public static void Error(string message, Exception ex) => Write("ERROR: " + message + "\n" + ex);
}
