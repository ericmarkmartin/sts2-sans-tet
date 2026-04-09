using System;
using System.Threading.Tasks;
using HarmonyLib;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Modding;

namespace RLBridge;

[ModInitializer("Initialize")]
public static class RLBridgeInit
{
    private static AgentConnection? _connection;

    public static void Initialize()
    {
        RLLog.Info("RL Bridge mod initializing...");

        // Apply all Harmony patches in this assembly
        var harmony = new Harmony("sts2_sans_tet.rl_bridge");
        harmony.PatchAll(typeof(RLBridgeInit).Assembly);
        RLLog.Info("Harmony patches applied");

        // Read port from environment variable or use default
        int port = 19720;
        var portEnv = Environment.GetEnvironmentVariable("RL_BRIDGE_PORT");
        if (portEnv != null && int.TryParse(portEnv, out int p))
        {
            port = p;
        }

        // Connect to Python agent asynchronously
        _connection = new AgentConnection(port: port);
        Task.Run(async () =>
        {
            try
            {
                // Retry connection with backoff — Python server might not be up yet
                for (int attempt = 0; attempt < 30; attempt++)
                {
                    try
                    {
                        await _connection.ConnectAsync();
                        RLLog.Info("Agent connection established");
                        return;
                    }
                    catch (Exception ex) when (attempt < 29)
                    {
                        RLLog.Info($"Connection attempt {attempt + 1} failed, retrying in 2s...");
                        await Task.Delay(2000);
                    }
                }
                RLLog.Error("Failed to connect to Python agent after 30 attempts");
            }
            catch (Exception ex)
            {
                RLLog.Error("Fatal error connecting to agent", ex);
            }
        });
    }
}
