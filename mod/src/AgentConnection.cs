using System;
using System.IO;
using System.Net.Sockets;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace RLBridge;

public class AgentConnection
{
    public static AgentConnection? Instance { get; private set; }

    private TcpClient? _client;
    private StreamReader? _reader;
    private StreamWriter? _writer;

    private readonly string _host;
    private readonly int _port;
    private readonly TimeSpan _timeout;

    public bool IsConnected => _client?.Connected ?? false;

    public AgentConnection(string host = "127.0.0.1", int port = 19720, int timeoutSeconds = 30)
    {
        _host = host;
        _port = port;
        _timeout = TimeSpan.FromSeconds(timeoutSeconds);
        Instance = this;
    }

    public async Task ConnectAsync(CancellationToken ct = default)
    {
        RLLog.Info($"Connecting to Python agent at {_host}:{_port}...");
        _client = new TcpClient();

        var connectTask = _client.ConnectAsync(_host, _port);
        var timeoutTask = Task.Delay(_timeout, ct);

        if (await Task.WhenAny(connectTask, timeoutTask) == timeoutTask)
        {
            throw new TimeoutException($"Connection to {_host}:{_port} timed out after {_timeout.TotalSeconds}s");
        }

        await connectTask; // propagate any exception

        var stream = _client.GetStream();
        _reader = new StreamReader(stream);
        _writer = new StreamWriter(stream) { AutoFlush = true };

        RLLog.Info("Connected to Python agent");
    }

    public async Task SendObservationAsync(string decisionType, JsonElement obs, JsonElement runContext, CancellationToken ct = default)
    {
        var msg = new
        {
            type = "obs",
            decision_type = decisionType,
            obs = obs,
            run_context = runContext
        };
        await SendJsonAsync(msg, ct);
    }

    public async Task SendEpisodeEndAsync(string result, int floorReached, int finalHp, JsonElement runContext, CancellationToken ct = default)
    {
        var msg = new
        {
            type = "episode_end",
            result = result,
            floor_reached = floorReached,
            final_hp = finalHp,
            run_context = runContext
        };
        await SendJsonAsync(msg, ct);
    }

    public async Task<AgentAction> ReceiveActionAsync(CancellationToken ct = default)
    {
        var line = await ReadLineWithTimeoutAsync(ct);
        if (line == null)
        {
            throw new IOException("Connection closed by Python agent");
        }

        var doc = JsonDocument.Parse(line);
        var root = doc.RootElement;

        var action = new AgentAction
        {
            Type = root.GetProperty("type").GetString() ?? "action",
            ActionType = root.TryGetProperty("action_type", out var at) ? at.GetString() ?? "end_turn" : "end_turn",
            CardIndex = root.TryGetProperty("card_index", out var ci) ? ci.GetInt32() : -1,
            TargetIndex = root.TryGetProperty("target_index", out var ti) ? ti.GetInt32() : -1,
            OptionIndex = root.TryGetProperty("option_index", out var oi) ? oi.GetInt32() : -1,
            PotionIndex = root.TryGetProperty("potion_index", out var pi) ? pi.GetInt32() : -1,
        };

        return action;
    }

    public async Task WaitForResetAckAsync(CancellationToken ct = default)
    {
        var line = await ReadLineWithTimeoutAsync(ct);
        // We don't need to parse it strictly, just consume it
    }

    private async Task SendJsonAsync(object msg, CancellationToken ct)
    {
        if (_writer == null) throw new InvalidOperationException("Not connected");

        var json = JsonSerializer.Serialize(msg, new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            WriteIndented = false
        });
        await _writer.WriteLineAsync(json.AsMemory(), ct);
    }

    private async Task<string?> ReadLineWithTimeoutAsync(CancellationToken ct)
    {
        if (_reader == null) throw new InvalidOperationException("Not connected");

        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(_timeout);

        try
        {
            return await _reader.ReadLineAsync(cts.Token);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            RLLog.Warn("Timeout waiting for agent response, returning end_turn fallback");
            return null;
        }
    }

    public void Dispose()
    {
        _writer?.Dispose();
        _reader?.Dispose();
        _client?.Dispose();
        _client = null;
        Instance = null;
    }
}

public class AgentAction
{
    public string Type { get; set; } = "action";
    public string ActionType { get; set; } = "end_turn";
    public int CardIndex { get; set; } = -1;
    public int TargetIndex { get; set; } = -1;
    public int OptionIndex { get; set; } = -1;
    public int PotionIndex { get; set; } = -1;
}
