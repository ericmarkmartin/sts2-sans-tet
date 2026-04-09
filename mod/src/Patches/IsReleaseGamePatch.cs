using HarmonyLib;
using MegaCrit.Sts2.Core.Nodes;

namespace RLBridge.Patches;

[HarmonyPatch(typeof(NGame), nameof(NGame.IsReleaseGame))]
public static class IsReleaseGamePatch
{
    static bool Prefix(ref bool __result)
    {
        __result = false;
        return false; // skip original
    }
}
